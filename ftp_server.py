import socket
import threading
import os
import sys
import time
import json
from datetime import datetime
from typing import Optional, Tuple


# ================================================================
# FTP Server Configuration
# ================================================================
HOST = "0.0.0.0"
TCP_PORT = 21          # Standard FTP control port
# Thư mục ftp_root nằm cùng cấp với ftp_server.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "gui", "ftp_root")

# File tài khoản nằm bên trong ftp_root
USER_FILE = os.path.join(DATA_DIR, "user.json")
MAX_CONNECTIONS = 10   # Maximum concurrent connections
SESSION_TIMEOUT = 300  # Session timeout in seconds (5 minutes)

def load_users():
    """Load demo FTP users from ftp_root/user.json."""
    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        users = data.get("users", data) if isinstance(data, dict) else {}

        if not isinstance(users, dict):
            raise ValueError("user.json must contain a JSON object")

        # Tạo thư mục home cho từng user
        for username, info in users.items():
            if not isinstance(info, dict):
                continue

            home = info.get("home", username)
            home = str(home).replace("\\", "/")

            # Cho phép ghi "ftp_root/admin" hoặc chỉ "admin"
            if home.lower().startswith("ftp_root/"):
                home = home[len("ftp_root/"):]

            if os.path.isabs(home):
                home_path = os.path.abspath(home)
            else:
                home_path = os.path.abspath(
                    os.path.join(DATA_DIR, home)
                )

            os.makedirs(home_path, exist_ok=True)

        print(f"Loaded {len(users)} FTP user(s) from: {USER_FILE}")
        return users

    except FileNotFoundError:
        print(f"ERROR: user.json not found: {USER_FILE}")
        return {}

    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {USER_FILE}: {e}")
        return {}

    except Exception as e:
        print(f"ERROR: Cannot load users: {e}")
        return {}


USERS = load_users()

print("========== USER DEBUG ==========")
print("USER_FILE:", USER_FILE)
print("USERS:", USERS)
print("USERNAMES:", list(USERS.keys()))
print("================================")

# UDP Reliable Layer Configuration
UDP_BUFFER_SIZE = 1024        # Maximum UDP packet payload
UDP_MAX_RETRIES = 5           # Maximum retry attempts
UDP_TIMEOUT = 2.0             # Timeout for ACK in seconds


# ================================================================
# FTP Response Codes
# ================================================================
class FTPResponse:
    # 1xx - Positive Preliminary Reply
    FILE_ACTION_PENDING = "150 File status okay; about to open data connection."
    DATA_CONNECTION_OPEN = "125 Data connection already open; transfer starting."

    # 2xx - Positive Completion Reply
    COMMAND_OK = "200 Command OK."
    SERVICE_READY = "220 Service ready."
    GOODBYE = "221 Goodbye."
    SERVICE_CLOSING = "221 Service closing control connection."
    LOGIN_SUCCESS = "230 Login successful."
    TRANSFER_COMPLETE = "226 Transfer complete."
    DATA_CONNECTION_CLOSED = "226 Transfer complete; closing data connection."

    # 3xx - Positive Intermediate Reply
    PASSWORD_REQUIRED = "331 Username okay, need password."
    RNTO_REQUIRED = "350 Requested file action pending RNTO command."

    # 4xx - Transient Negative Reply
    SERVICE_UNAVAILABLE = "421 Service not available."
    CANNOT_OPEN_DATA = "425 Can't open data connection."
    CONNECTION_CLOSED = "426 Connection closed."

    # 5xx - Permanent Negative Reply
    SYNTAX_ERROR = "500 Syntax error."
    PARAMETER_ERROR = "501 Syntax error in parameters."
    COMMAND_NOT_IMPLEMENTED = "502 Command not implemented."
    NOT_LOGGED_IN = "530 Not logged in."
    FILE_ACTION_FAILED = "550 File action not taken."
    FILE_NOT_FOUND = "550 File not found."
    DIRECTORY_NOT_FOUND = "550 Directory not found."


# ================================================================
# Custom Reliable UDP Layer
# ================================================================
class ReliableUDP:
    """
    Custom reliable UDP protocol implementation with:
    - Sequence numbers for ordering
    - ACK mechanism
    - Timeout and retransmission
    - Checksum for data integrity
    """

    def __init__(self, host, port):
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.settimeout(UDP_TIMEOUT)
        self.local_port = self.sock.getsockname()[1]
        self.peer_addr: Optional[Tuple[str, int]] = None
        self.sequence = 0
        self.lock = threading.Lock()

    def calculate_checksum(self, data: bytes) -> int:
        """Calculate checksum for data integrity verification"""
        checksum = 0
        for i in range(0, len(data), 2):
            if i + 1 < len(data):
                checksum += (data[i] << 8) + data[i + 1]
            else:
                checksum += data[i] << 8
        while checksum > 0xffff:
            checksum = (checksum >> 16) + (checksum & 0xffff)
        return checksum & 0xffff

    def create_packet(self, sequence: int, ack: int, flags: int, payload: bytes = b""):
        """
        Create reliable UDP packet with custom header (12 bytes)
        - Sequence number (2 bytes)
        - ACK number (2 bytes)
        - Flags (1 byte): 0=ACK, 1=FIN, 2=SYN
        - Payload length (2 bytes)
        - Checksum (2 bytes)
        - Reserved (3 bytes)
        """
        checksum = self.calculate_checksum(payload)
        header = (
            sequence.to_bytes(2, 'big') +
            ack.to_bytes(2, 'big') +
            bytes([flags]) +
            len(payload).to_bytes(2, 'big') +
            checksum.to_bytes(2, 'big') +
            b'\x00' * 3
        )
        return header + payload

    def parse_packet(self, data: bytes):
        """Parse reliable UDP packet, return (seq, ack, flags, payload, is_valid)"""
        if len(data) < 12:
            return None, None, None, None, False
        try:
            sequence = int.from_bytes(data[0:2], 'big')
            ack = int.from_bytes(data[2:4], 'big')
            flags = data[4]
            payload_length = int.from_bytes(data[5:7], 'big')
            received_checksum = int.from_bytes(data[7:9], 'big')
            payload = data[12:12 + payload_length] if payload_length > 0 else b""
            calculated_checksum = self.calculate_checksum(payload)
            is_valid = (received_checksum == calculated_checksum)
            return sequence, ack, flags, payload, is_valid
        except Exception:
            return None, None, None, None, False

    def send_packet(self, sequence: int, payload: bytes = b""):
        """Send packet with retransmission until ACK received"""
        packet = self.create_packet(sequence, 0, 0x04, payload)
        if self.peer_addr is None:
            return False
        for _ in range(UDP_MAX_RETRIES):
            try:
                self.sock.sendto(packet, self.peer_addr)
                try:
                    ack_data, _ = self.sock.recvfrom(64)
                    if len(ack_data) >= 12 and ack_data[4] & 0x01:
                        return True
                except TimeoutError:
                    pass
            except Exception as e:
                print(f"Send error: {e}")
        return False

    def send_ack(self, ack_sequence: int):
        """Send ACK for received packet"""
        if self.peer_addr is None:
            return
        ack_packet = self.create_packet(ack_sequence, 0, 0x01)
        self.sock.sendto(ack_packet, self.peer_addr)

    def send_fin(self):
        """Send FIN to indicate end of transfer"""
        if self.peer_addr is None:
            return
        fin_packet = self.create_packet(self.sequence, 0, 0x02)
        self.sock.sendto(fin_packet, self.peer_addr)

    def receive_packet(self):
        """Receive and parse packet, send ACK"""
        try:
            data, addr = self.sock.recvfrom(UDP_BUFFER_SIZE + 128)
            if self.peer_addr is None:
                self.peer_addr = addr
            sequence, ack, flags, payload, is_valid = self.parse_packet(data)
            if is_valid and sequence is not None:
                self.send_ack(sequence + 1)
                return sequence, ack, flags, payload
            return None, None, None, None
        except TimeoutError:
            return None, None, None, None
        except Exception as e:
            print(f"Receive error: {e}")
            return None, None, None, None

    def receive_until_fin(self):
        """Receive packets until FIN flag is set, return sorted list"""
        received_packets = []
        while True:
            sequence, ack, flags, payload = self.receive_packet()
            if sequence is None:
                break
            received_packets.append((sequence, payload))
            if flags is not None and flags & 0x02:  # FIN flag
                break
        received_packets.sort(key=lambda x: x[0])
        return received_packets

    def close(self):
        """Close UDP socket"""
        if self.sock:
            self.sock.close()


# ================================================================
# FTP Server Session
# ================================================================
class FTPSession:
    """Represents a single FTP client session"""

    def __init__(self, client_socket, client_address):
        self.client_socket = client_socket
        self.client_address = client_address
        self.authenticated = False
        self.username = None
        self.current_directory = os.path.abspath(DATA_DIR)
        self.transfer_type = "ascii"  # ascii or binary
        self.transfer_mode = "passive"  # active or passive
        self.data_port = None
        self.renamed_file = None
        self.last_command_time = time.time()
        self.active = True
        self.udp_server = None

    def send_response(self, code: int, message: str):
        """Send response to client over TCP"""
        response = f"{code} {message}\r\n"
        try:
            self.client_socket.send(response.encode())
        except Exception:
            pass

    def receive_command(self):
        """Receive command from client"""
        try:
            data = self.client_socket.recv(4096)
            if data:
                self.last_command_time = time.time()
                return data.decode().strip()
            return None
        except Exception:
            return None

    def execute_command(self, command: str):
        """Parse and execute FTP command"""
        if not command:
            return

        # Parse command and arguments
        parts = command.split(None, 1)
        cmd = parts[0].upper()
        args = parts[1].strip() if len(parts) > 1 else ""

        # Command handlers
        if cmd == "USER":
            self.cmd_user(args)
        elif cmd == "PASS":
            self.cmd_pass(args)
        elif cmd == "QUIT":
            self.cmd_quit()
        elif cmd == "NOOP":
            self.cmd_noop()
        elif cmd == "PWD":
            self.cmd_pwd()
        elif cmd == "CWD":
            self.cmd_cwd(args)
        elif cmd == "CDUP":
            self.cmd_cdup()
        elif cmd == "MKD":
            self.cmd_mkd(args)
        elif cmd == "RMD":
            self.cmd_rmd(args)
        elif cmd == "LIST":
            self.cmd_list(args)
        elif cmd == "SIZE":
            self.cmd_size(args)
        elif cmd == "TYPE":
            self.cmd_type(args)
        elif cmd == "PASV":
            self.cmd_pasv()
        elif cmd == "RETR":
            self.cmd_retr(args)
        elif cmd == "STOR":
            self.cmd_stor(args)
        elif cmd == "HELP":
            self.cmd_help(args)
        else:
            self.send_response(502, FTPResponse.COMMAND_NOT_IMPLEMENTED)

    def cmd_user(self, args):
        """Handle USER command - Check username against user.json."""
        username = args.strip()

        if not username or username not in USERS:
            self.username = None
            self.authenticated = False
            self.send_response(530, "Invalid username.")
            return

        self.username = username
        self.authenticated = False
        self.send_response(331, FTPResponse.PASSWORD_REQUIRED)

    def cmd_pass(self, args):
        """Handle PASS command - Verify password from user.json."""
        if not self.username or self.username not in USERS:
            self.send_response(530, FTPResponse.NOT_LOGGED_IN)
            return

        user_info = USERS[self.username]

        if args != str(user_info.get("password", "")):
            self.authenticated = False
            self.send_response(530, "Invalid password.")
            return

        # Lấy thư mục home của user
        home = user_info.get("home", self.username)
        home = str(home).replace("\\", "/")

        if home.lower().startswith("ftp_root/"):
           home = home[len("ftp_root/"):]

        if os.path.isabs(home):
            home_path = os.path.abspath(home)
        else:
            home_path = os.path.abspath(
                os.path.join(DATA_DIR, home)
            )

        # Kiểm tra home nằm trong ftp_root
        try:
            if os.path.commonpath(
                [os.path.abspath(DATA_DIR), home_path]
            ) != os.path.abspath(DATA_DIR):
                self.send_response(530, "Invalid user home directory.")
                self.username = None
                return
        except ValueError:
            self.send_response(530, "Invalid user home directory.")
            self.username = None
            return

        os.makedirs(home_path, exist_ok=True)

        self.home_directory = home_path
        self.current_directory = home_path
        self.authenticated = True

        self.send_response(230, FTPResponse.LOGIN_SUCCESS)

    def cmd_quit(self):
        """Handle QUIT command - Close connection"""
        self.send_response(221, FTPResponse.GOODBYE)
        self.active = False

    def cmd_noop(self):
        """Handle NOOP command - Keep-alive ping"""
        self.send_response(200, FTPResponse.COMMAND_OK)

    def cmd_pwd(self):
        """Handle PWD command - Print working directory"""
        self.send_response(257, f'"{self.current_directory}"')

    def cmd_cwd(self, path):
        """Handle CWD command - Change working directory"""
        if not self.authenticated:
            self.send_response(530, FTPResponse.NOT_LOGGED_IN)
            return
        new_path = os.path.normpath(os.path.join(self.current_directory, path))
        if os.path.isdir(new_path):
            self.current_directory = new_path
            self.send_response(257, f'"{new_path}"')
        else:
            self.send_response(550, FTPResponse.DIRECTORY_NOT_FOUND)

    def cmd_cdup(self):
        """Handle CDUP command - Change to parent directory"""
        self.cmd_cwd("..")

    def cmd_mkd(self, dirname):
        """Handle MKD command - Make directory"""
        if not self.authenticated:
            self.send_response(530, FTPResponse.NOT_LOGGED_IN)
            return
        new_dir = os.path.join(self.current_directory, dirname)
        try:
            os.makedirs(new_dir, exist_ok=True)
            self.send_response(257, f'"{new_dir}" created.')
        except Exception:
            self.send_response(550, FTPResponse.FILE_ACTION_FAILED)

    def cmd_rmd(self, dirname):
        """Handle RMD command - Remove directory"""
        if not self.authenticated:
            self.send_response(530, FTPResponse.NOT_LOGGED_IN)
            return
        dir_path = os.path.join(self.current_directory, dirname)
        try:
            os.rmdir(dir_path)
            self.send_response(250, FTPResponse.COMMAND_OK)
        except Exception:
            self.send_response(550, FTPResponse.FILE_ACTION_FAILED)

    def cmd_list(self, path):
        """Handle LIST command - List directory contents"""
        if not self.authenticated:
            self.send_response(530, FTPResponse.NOT_LOGGED_IN)
            return
        target = os.path.join(self.current_directory, path) if path else self.current_directory
        if not os.path.isdir(target):
            self.send_response(550, FTPResponse.DIRECTORY_NOT_FOUND)
            return
        listing = ""
        for item in os.listdir(target):
            item_path = os.path.join(target, item)
            item_stat = os.stat(item_path)
            item_size = item_stat.st_size
            item_time = datetime.fromtimestamp(item_stat.st_mtime).strftime("%Y%m%d %H%M%S")
            item_type = "d" if os.path.isdir(item_path) else "-"
            listing += f"{item_type} {item_size:>10} {item_time} {item}\r\n"
        self.send_response(226, FTPResponse.TRANSFER_COMPLETE)
        # Send listing over control channel (simplified)
        try:
            self.client_socket.send(listing.encode())
        except Exception:
            pass

    def cmd_size(self, filename):
        """Handle SIZE command - Get file size"""
        file_path = os.path.join(self.current_directory, filename)
        if os.path.isfile(file_path):
            size = os.path.getsize(file_path)
            self.send_response(213, f"{size} bytes")
        else:
            self.send_response(550, FTPResponse.FILE_NOT_FOUND)

    def cmd_type(self, args):
        """Handle TYPE command - Set transfer type"""
        if args.upper() in ["A", "I"]:
            self.transfer_type = "ascii" if args.upper() == "A" else "binary"
            self.send_response(200, FTPResponse.COMMAND_OK)
        else:
            self.send_response(501, FTPResponse.PARAMETER_ERROR)

    def cmd_pasv(self):
        """Handle PASV command - Enter passive mode"""

        if not self.authenticated:
            self.send_response(
                530,
                FTPResponse.NOT_LOGGED_IN
            )
            return

        if self.udp_server is not None:
            try:
                self.udp_server.close()
            except Exception:
                pass

            self.udp_server = None
            self.data_port = None

        self.udp_server = ReliableUDP(
            HOST,
            0
        )

        self.data_port = (
            self.udp_server.local_port
        )

        ip = HOST

        if ip == "0.0.0.0":
            try:
                with socket.socket(
                    socket.AF_INET,
                    socket.SOCK_DGRAM
                ) as s:

                    s.connect(
                        (
                            self.client_address[0],
                            9
                        )
                    )

                    ip = s.getsockname()[0]

            except Exception:
                ip = socket.gethostbyname(
                    socket.gethostname()
                )

        parts = ip.split(".")

        self.send_response(
            227,
            (
                "Entering Passive Mode "
                f"({','.join(parts)},"
                f"{self.data_port // 256},"
                f"{self.data_port % 256})"
            )
        )

        print(
            f"PASV for {self.client_address}: "
            f"{ip}:{self.data_port}"
        )

    def cmd_retr(self, filename):
        """Handle RETR command - Retrieve (download) file"""
        if not self.authenticated:
            self.send_response(530, FTPResponse.NOT_LOGGED_IN)
            return
        file_path = os.path.join(self.current_directory, filename)
        if not os.path.isfile(file_path):
            self.send_response(550, FTPResponse.FILE_NOT_FOUND)
            return
        try:
            # Open file for reading
            with open(file_path, 'rb') as f:
                file_data = f.read()

            # Send file over UDP data channel
            self.send_response(150, FTPResponse.FILE_ACTION_PENDING)

            if not self.udp_server:
                self.send_response(425, "No data connection established")
                return

            chunk_size = UDP_BUFFER_SIZE - 12  # Subtract header size
            chunks = [file_data[i:i + chunk_size] for i in range(0, len(file_data), chunk_size)]

            # Send each chunk with sequence number
            for i, chunk in enumerate(chunks):
                is_last = i == len(chunks) - 1
                flags = 0x04  # SYN flag
                if is_last:
                    flags |= 0x02  # FIN flag
                if self.udp_server.peer_addr:
                    packet = self.udp_server.create_packet(i, 0, flags, chunk)
                    self.udp_server.sock.sendto(packet, self.udp_server.peer_addr)
                    # Wait for ACK
                    try:
                        _, _ = self.udp_server.sock.recvfrom(64)
                    except TimeoutError:
                        # Retry
                        pass

            self.send_response(226, FTPResponse.TRANSFER_COMPLETE)
        except Exception:
            self.send_response(451, "Data transfer error")

    def cmd_stor(self, filename):
        """Handle STOR command - Store (upload) file"""

        if not self.authenticated:
            self.send_response(
                530,
                FTPResponse.NOT_LOGGED_IN
            )
            return

        if not filename:
            self.send_response(
                501,
                FTPResponse.PARAMETER_ERROR
            )
            return

        if self.udp_server is None:
            self.send_response(
                425,
                "Use PASV first."
            )
            return

        file_path = os.path.join(
            self.current_directory,
            filename
        )

        # Security: prevent ../ escaping current user directory
        try:
            real_file_path = os.path.abspath(file_path)
            real_current_dir = os.path.abspath(
                self.current_directory
            )
            real_home_dir = os.path.abspath(
                self.home_directory
            )

            if os.path.commonpath(
                [real_home_dir, real_file_path]
            ) != real_home_dir:
                self.send_response(
                    550,
                    FTPResponse.FILE_ACTION_FAILED
                )
                return

        except ValueError:
            self.send_response(
                550,
                FTPResponse.FILE_ACTION_FAILED
            )
            return

        try:
            print(
                f"Starting upload from "
                f"{self.client_address}: "
                f"{filename}"
            )

            print(
                f"Using UDP data port: "
                f"{self.udp_server.local_port}"
            )

        
            self.send_response(
                150,
                FTPResponse.FILE_ACTION_PENDING
            )
            packets = self.udp_server.receive_until_fin()

            if not packets:
                raise RuntimeError(
                    "No UDP packets received."
                )
            total_bytes = 0

            with open(
                real_file_path,
                "wb"
            ) as f:

                for sequence, payload in packets:

                    # FIN packet normally has empty payload.
                    if payload:
                        f.write(payload)
                        total_bytes += len(payload)

            print(
                f"Upload complete: "
                f"{filename} | "
                f"{total_bytes} bytes | "
                f"{len(packets)} packets | "
                f"{real_file_path}"
            )
            self.send_response(
                226,
                FTPResponse.TRANSFER_COMPLETE
            )

        except Exception as e:

            print(
                f"Upload error for "
                f"{filename}: {e}"
            )

            try:
                self.send_response(
                    451,
                    "Data transfer error"
                )
            except Exception:
                pass

        finally:

            if self.udp_server is not None:

                try:
                    self.udp_server.close()
                except Exception:
                    pass

                self.udp_server = None

                self.data_port = None

    def cmd_help(self, args):
        """Handle HELP command - Show available commands"""
        help_text = "Available commands:\r\n"
        commands = [
            "USER <username> - Login with username",
            "PASS <password> - Provide password",
            "QUIT - Close connection",
            "NOOP - Keep-alive ping",
            "PWD - Print working directory",
            "CWD <path> - Change working directory",
            "CDUP - Change to parent directory",
            "MKD <dirname> - Make directory",
            "RMD <dirname> - Remove directory",
            "LIST [path] - List directory contents",
            "SIZE <filename> - Get file size",
            "TYPE {A|I} - Set transfer type (A=ASCII, I=Binary)",
            "PASV - Enter passive mode",
            "RETR <filename> - Download file",
            "STOR <filename> - Upload file",
            "HELP [command] - Show help",
        ]
        for cmd in commands:
            help_text += f"  {cmd}\r\n"
        self.send_response(214, "Help text")
        try:
            self.client_socket.send(help_text.encode())
        except Exception:
            pass


# ================================================================
# Main FTP Server
# ================================================================
class FTPServer:
    """Main FTP Server class that handles multiple client connections"""

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.server_socket = None
        self.sessions = []
        self.sessions_lock = threading.Lock()
        self.running = False

    def start(self):
        """Initialize and start the FTP server"""
        # Create TCP socket for control channel
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(MAX_CONNECTIONS)

        # Create data directory if not exists
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)

        self.running = True
        print(f"FTP Server started on {self.host}:{self.port}")
        print(f"Data directory: {DATA_DIR}")
        print(f"Press Ctrl+C to stop\n")

        # Accept client connections
        try:
            while self.running:
                client_socket, client_address = self.server_socket.accept()
                print(f"New connection from {client_address}")

                # Create session and handle in new thread
                session = FTPSession(client_socket, client_address)
                with self.sessions_lock:
                    self.sessions.append(session)

                thread = threading.Thread(
                    target=self.handle_client,
                    args=(session,),
                    daemon=True
                )
                thread.start()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def handle_client(self, session: FTPSession):
        """Handle a single client session with timeout management"""
        try:
            # Send welcome message
            session.send_response(220, FTPResponse.SERVICE_READY)

            while session.active:
                # Check for session timeout
                if time.time() - session.last_command_time > SESSION_TIMEOUT:
                    print(f"Session timeout for {session.client_address}")
                    session.send_response(421, "Session timed out")
                    session.active = False
                    break

                command = session.receive_command()
                if not command:
                    break
                print(f"Received command from {session.client_address}: {command}")
                session.execute_command(command)
        except Exception as e:
            print(f"Error handling client: {e}")
        finally:
            # Close connections
            try:
                session.client_socket.close()
                if session.udp_server:
                    session.udp_server.close()
            except Exception:
                pass

            # Remove session
            with self.sessions_lock:
                if session in self.sessions:
                    self.sessions.remove(session)

            print(f"Client {session.client_address} disconnected")

    def stop(self):
        """Stop the server gracefully"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print("Server stopped")

    def get_connected_clients(self):
        """Get list of connected clients for GUI"""
        with self.sessions_lock:
            return [(s.client_address, s.username, s.authenticated, 
                     s.current_directory, s.active) for s in self.sessions]


if __name__ == "__main__":
    server = FTPServer(HOST, TCP_PORT)
    try:
        server.start()
    except Exception as e:
        print(f"Server error: {e}")
    finally:
        server.stop()


# ================================================================
# Main Entry Point
# ================================================================
if __name__ == "__main__":
    print("=" * 50)
    print("Hybrid FTP Server - Low-level Implementation")
    print("Control: TCP | Data: UDP (with custom reliable layer)")
    print("=" * 50)

    server = FTPServer(HOST, TCP_PORT)
    try:
        server.start()
    except Exception as e:
        print(f"Server error: {e}")
        sys.exit(1)