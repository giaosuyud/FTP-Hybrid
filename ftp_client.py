import socket
import os
import sys
import time
from typing import Optional


# ================================================================
# FTP Client Configuration
# ================================================================
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 21          # Standard FTP control port
BUFFER_SIZE = 4096

# UDP Reliable Layer Configuration
UDP_BUFFER_SIZE = 1024
UDP_MAX_RETRIES = 5
UDP_TIMEOUT = 2.0


# ================================================================
# Custom Reliable UDP Layer (Client Side)
# ================================================================
class ReliableUDPClient:
    """
    Reliable UDP:
    - Sequence number
    - ACK number
    - Checksum
    - Retransmission
    - Duplicate detection
    - FIN
    """

    HEADER_SIZE = 12

    FLAG_ACK = 0x01
    FLAG_FIN = 0x02
    FLAG_DATA = 0x04
    FLAG_HELLO = 0x08

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(UDP_TIMEOUT)

        self.local_port = self.sock.getsockname()[1]
        self.server_addr = None

        self.expected_sequence = 0

    # ------------------------------------------------------------
    # CHECKSUM
    # ------------------------------------------------------------

    def calculate_checksum(self, data: bytes) -> int:
        checksum = 0

        for i in range(0, len(data), 2):
            if i + 1 < len(data):
                checksum += (data[i] << 8) | data[i + 1]
            else:
                checksum += data[i] << 8

        while checksum > 0xFFFF:
            checksum = (checksum >> 16) + (checksum & 0xFFFF)

        return checksum & 0xFFFF

    # ------------------------------------------------------------
    # PACKET
    # ------------------------------------------------------------

    def create_packet(
        self,
        sequence: int,
        ack: int,
        flags: int,
        payload: bytes = b""
    ):
        checksum = self.calculate_checksum(payload)

        header = (
            sequence.to_bytes(2, "big") +
            ack.to_bytes(2, "big") +
            bytes([flags]) +
            len(payload).to_bytes(2, "big") +
            checksum.to_bytes(2, "big") +
            b"\x00" * 3
        )

        return header + payload

    def parse_packet(self, data: bytes):

        if len(data) < self.HEADER_SIZE:
            return None

        try:
            sequence = int.from_bytes(data[0:2], "big")
            ack = int.from_bytes(data[2:4], "big")
            flags = data[4]

            payload_length = int.from_bytes(
                data[5:7],
                "big"
            )

            received_checksum = int.from_bytes(
                data[7:9],
                "big"
            )

            if len(data) < self.HEADER_SIZE + payload_length:
                return None

            payload = data[
                self.HEADER_SIZE:
                self.HEADER_SIZE + payload_length
            ]

            calculated_checksum = self.calculate_checksum(payload)

            if received_checksum != calculated_checksum:
                print("UDP checksum error")
                return None

            return (
                sequence,
                ack,
                flags,
                payload
            )

        except Exception:
            return None

    # ------------------------------------------------------------
    # CONNECT
    # ------------------------------------------------------------

    def connect_to_server(self, host, port):

        self.server_addr = (
            host,
            port
        )

        print(
            f"UDP connected to "
            f"{self.server_addr}"
        )

    # ------------------------------------------------------------
    # UDP HELLO HANDSHAKE
    # ------------------------------------------------------------
    def hello(self):
        """Establish UDP peer connection with the server."""
        if not self.server_addr:
            return False

        packet = self.create_packet(0, 0, self.FLAG_HELLO)

        for attempt in range(UDP_MAX_RETRIES):
            try:
                self.sock.sendto(packet, self.server_addr)

                while True:
                    ack_data, addr = self.sock.recvfrom(
                        self.HEADER_SIZE + 64
                    )

                    if addr != self.server_addr:
                        continue

                    parsed = self.parse_packet(ack_data)
                    if parsed is None:
                        continue

                    recv_seq, ack, flags, payload = parsed

                    if flags & self.FLAG_ACK and ack == 1:
                        print("UDP handshake successful")
                        return True

            except socket.timeout:
                print(
                    f"UDP HELLO timeout "
                    f"({attempt + 1}/{UDP_MAX_RETRIES})"
                )
            except Exception as e:
                print(f"UDP HELLO error: {e}")
                return False

        return False

    # ------------------------------------------------------------
    # ACK
    # ------------------------------------------------------------

    def send_ack(self, ack_sequence):

        if not self.server_addr:
            return

        packet = self.create_packet(
            0,
            ack_sequence,
            self.FLAG_ACK
        )

        self.sock.sendto(
            packet,
            self.server_addr
        )

    # ------------------------------------------------------------
    # SEND ONE RELIABLE PACKET
    # ------------------------------------------------------------

    def send_packet(
        self,
        sequence,
        payload=b"",
        flags=FLAG_DATA
    ):

        if not self.server_addr:
            return False

        packet = self.create_packet(
            sequence,
            0,
            flags,
            payload
        )

        expected_ack = sequence + 1

        for attempt in range(UDP_MAX_RETRIES):

            try:

                self.sock.sendto(
                    packet,
                    self.server_addr
                )

                print(
                    f"UDP SEND seq={sequence} "
                    f"attempt={attempt + 1}"
                )

                while True:

                    ack_data, addr = self.sock.recvfrom(
                        UDP_BUFFER_SIZE + 128
                    )

                    if addr != self.server_addr:
                        continue

                    parsed = self.parse_packet(
                        ack_data
                    )

                    if parsed is None:
                        continue

                    recv_seq, ack, recv_flags, payload = parsed

                    if recv_flags & self.FLAG_ACK:

                        if ack == expected_ack:

                            print(
                                f"UDP ACK seq={sequence}"
                            )

                            return True

                        # ACK cũ -> bỏ qua

            except socket.timeout:
                print(
                    f"UDP timeout seq={sequence}"
                )

            except Exception as e:
                print(
                    f"UDP send error: {e}"
                )

        print(
            f"UDP FAILED seq={sequence}"
        )

        return False

    # ------------------------------------------------------------
    # RECEIVE ONE PACKET
    # ------------------------------------------------------------

    def receive_packet(self):

        try:

            data, addr = self.sock.recvfrom(
                UDP_BUFFER_SIZE + 128
            )

            if self.server_addr and addr != self.server_addr:
                return None

            parsed = self.parse_packet(data)

            if parsed is None:
                return None

            sequence, ack, flags, payload = parsed

            # ACK packet
            if flags & self.FLAG_ACK:
                return (
                    sequence,
                    ack,
                    flags,
                    payload
                )

            # ----------------------------------------------------
            # EXPECTED PACKET
            # ----------------------------------------------------

            if sequence == self.expected_sequence:

                self.send_ack(
                    sequence + 1
                )

                self.expected_sequence += 1

                return (
                    sequence,
                    ack,
                    flags,
                    payload
                )

            # ----------------------------------------------------
            # DUPLICATE PACKET
            # ----------------------------------------------------

            elif sequence < self.expected_sequence:

                # Gửi lại ACK
                self.send_ack(
                    self.expected_sequence
                )

                print(
                    f"Duplicate UDP packet "
                    f"seq={sequence}"
                )

                return None

            # ----------------------------------------------------
            # OUT OF ORDER
            # ----------------------------------------------------

            else:

                self.send_ack(
                    self.expected_sequence
                )

                print(
                    f"Out-of-order packet "
                    f"seq={sequence}, "
                    f"expected={self.expected_sequence}"
                )

                return None

        except socket.timeout:
            return None

        except Exception as e:

            print(
                f"UDP receive error: {e}"
            )

            return None

    # ------------------------------------------------------------
    # RECEIVE FILE
    # ------------------------------------------------------------

    def receive_all(self):

        packets = []

        self.expected_sequence = 0

        last_packet_time = time.time()

        while True:

            try:

                data, addr = self.sock.recvfrom(
                    UDP_BUFFER_SIZE + 128
                )

                if addr != self.server_addr:
                    continue

                parsed = self.parse_packet(data)

                if parsed is None:
                    continue

                sequence, ack, flags, payload = parsed

                # Ignore ACK
                if flags & self.FLAG_ACK:
                    continue

                # ------------------------------------------------
                # EXPECTED
                # ------------------------------------------------

                if sequence == self.expected_sequence:

                    self.send_ack(
                        sequence + 1
                    )

                    packets.append(
                        (
                            sequence,
                            payload
                        )
                    )

                    print(
                        f"UDP RECV seq={sequence}, "
                        f"{len(payload)} bytes"
                    )

                    self.expected_sequence += 1
                    last_packet_time = time.time()

                    # FIN
                    if flags & self.FLAG_FIN:

                        print(
                            "UDP FIN received"
                        )

                        break

                # ------------------------------------------------
                # DUPLICATE
                # ------------------------------------------------

                elif sequence < self.expected_sequence:

                    self.send_ack(
                        self.expected_sequence
                    )

                    print(
                        f"Duplicate seq={sequence}, "
                        f"re-ACK={self.expected_sequence}"
                    )

                # ------------------------------------------------
                # OUT OF ORDER
                # ------------------------------------------------

                else:

                    self.send_ack(
                        self.expected_sequence
                    )

                    print(
                        f"Out of order seq={sequence}, "
                        f"expected={self.expected_sequence}"
                    )

            except socket.timeout:

                if packets:
                    if time.time() - last_packet_time > 10:
                        raise RuntimeError(
                            "UDP transfer timeout"
                        )

            except Exception as e:

                print(
                    f"Receive error: {e}"
                )

                raise

        packets.sort(
            key=lambda x: x[0]
        )

        return packets

    # ------------------------------------------------------------

    def close(self):

        try:
            self.sock.close()
        except Exception:
            pass

# ================================================================
# FTP Client
# ================================================================
class FTPClient:
    """FTP Client class for connecting to server"""

    def __init__(self, host=SERVER_HOST, port=SERVER_PORT):
        self.host = host
        self.port = port
        self.control_socket = None
        self.udp_client = None
        self.authenticated = False
        self.username = None
        self.current_directory = None
        self.response_buffer = ""
        self.data_port = None
        self.transfer_type = "ascii"

    def connect(self):
        """Connect to FTP server via TCP control channel"""
        try:
            # Create TCP socket for control channel
            self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.control_socket.connect((self.host, self.port))

            # Receive welcome message
            welcome = self._receive_response()
            print(f"Connected to {self.host}:{self.port}")
            print(f"Welcome: {welcome}")
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from FTP server"""
        try:
            self.send_command("QUIT")
        except Exception:
            pass
        if self.control_socket:
            self.control_socket.close()
        if self.udp_client:
            self.udp_client.close()
        print("Disconnected from server")

    def _receive_response(self):
        """Receive one FTP response from server."""
        try:
            while True:
                # Nếu buffer đã có một dòng hoàn chỉnh
                if "\r\n" in self.response_buffer:
                    line, self.response_buffer = self.response_buffer.split(
                        "\r\n", 1
                    )

                    if line and len(line) >= 3 and line[:3].isdigit():
                        return line

                # Chưa có response hoàn chỉnh -> đọc thêm từ socket
                data = self.control_socket.recv(BUFFER_SIZE)

                if not data:
                    return ""

                self.response_buffer += data.decode(
                    "utf-8",
                    errors="replace"
                )

        except Exception as e:
            print(f"Receive response error: {e}")
            return ""

    def _send_command(self, command: str):
        """Send command to server and receive response"""
        try:
            command_str = command + '\r\n'
            self.control_socket.send(command_str.encode())
            response = self._receive_response()
            return response
        except Exception as e:
            print(f"Command error: {e}")
            return ""

    def send_command(self, command: str):
        """Send command with error handling"""
        try:
            response = self._send_command(command)
            code = int(response[:3]) if response and len(response) >= 3 else 0
            if code in [200, 220, 221, 226, 230, 250, 257, 227]:
                return True
            elif code == 331:  # Password required
                return True
            return False
        except Exception:
            return False

    def login(self, username: str, password: str):
        """Login to FTP server"""
        # Send username
        response = self._send_command(f"USER {username}")
        if not response.startswith("331"):
            print(f"Login failed: {response}")
            return False

        # Send password
        response = self._send_command(f"PASS {password}")
        if response.startswith("230"):
            self.authenticated = True
            self.username = username
            print("Login successful")
            return True

        print(f"Login failed: {response}")
        return False

    def pwd(self):
        """Get current working directory"""
        response = self._send_command("PWD")
        if response.startswith("257"):
            self.current_directory = response[4:-2]
            print(f"Current directory: {self.current_directory}")
            return self.current_directory
        print(response)
        return None

    def cwd(self, path: str):
        """Change working directory"""
        response = self._send_command(f"CWD {path}")
        if response.startswith("257"):
            self.current_directory = response[4:-2]
            print(f"Changed to: {self.current_directory}")
            return True
        print(response)
        return False

    def cdup(self):
        """Change to parent directory"""
        return self.cwd("..")

    def mkdir(self, dirname: str):
        """Create directory"""
        response = self._send_command(f"MKD {dirname}")
        print(response)
        return response.startswith("257")

    def rmdir(self, dirname: str):
        """Remove directory"""
        response = self._send_command(f"RMD {dirname}")
        print(response)
        return response.startswith("250")

    def list_files(self, path: str = ""):
        """List directory contents"""
        cmd = "LIST" if not path else f"LIST {path}"
        response = self._send_command(cmd)
        print(response)
        # Receive file listing
        try:
            data = self.control_socket.recv(BUFFER_SIZE).decode()
            print(data)
        except Exception:
            pass

    def size(self, filename: str):
        """Get file size"""
        response = self._send_command(f"SIZE {filename}")
        print(response)
        return response

    def set_type(self, transfer_type: str):
        """Set transfer type: A=ASCII, I=Binary"""
        response = self._send_command(f"TYPE {transfer_type}")
        if response.startswith("200"):
            self.transfer_type = "ascii" if transfer_type == "A" else "binary"
            return True
        print(response)
        return False

    def download(
        self,
        remote_file: str,
        local_file: str = None
    ):

        if not local_file:
            local_file = remote_file

        # ------------------------------------------------------------
        # PASV
        # ------------------------------------------------------------

        response = self._send_command(
            "PASV"
        )

        if not response.startswith("227"):

            print(
                f"PASV failed: {response}"
            )

            return False

        try:

            port_start = response.find("(") + 1
            port_end = response.find(")")

            port_info = response[
                port_start:port_end
            ]

            parts = port_info.split(",")

            server_ip = (
                f"{parts[0]}."
                f"{parts[1]}."
                f"{parts[2]}."
                f"{parts[3]}"
            )

            server_port = (
                int(parts[4]) * 256
                + int(parts[5])
            )

        except Exception as e:

            print(
                f"PASV parse error: {e}"
            )

            return False

        # ------------------------------------------------------------
        # UDP CLIENT
        # ------------------------------------------------------------

        self.udp_client = ReliableUDPClient()

        self.udp_client.connect_to_server(
            server_ip,
            server_port
        )

        # ------------------------------------------------------------
        # RETR
        # ------------------------------------------------------------

        response = self._send_command(
            f"RETR {remote_file}"
        )

        if not response.startswith("150"):

            print(
                f"RETR failed: {response}"
            )

            self.udp_client.close()
            self.udp_client = None

            return False

        # Server is now waiting for UDP HELLO.
        if not self.udp_client.hello():
            print("UDP handshake failed")
            self.udp_client.close()
            self.udp_client = None
            return False

        print(
            f"Downloading "
            f"{remote_file}..."
        )

        # ------------------------------------------------------------
        # RECEIVE UDP
        # ------------------------------------------------------------

        try:

            packets = (
                self.udp_client.receive_all()
            )

        except Exception as e:

            print(
                f"UDP download failed: {e}"
            )

            self.udp_client.close()
            self.udp_client = None

            return False

        # ------------------------------------------------------------
        # WRITE FILE
        # ------------------------------------------------------------

        try:

            with open(
                local_file,
                "wb"
            ) as f:

                total_bytes = 0

                for sequence, payload in packets:

                    if payload:

                        f.write(payload)

                        total_bytes += (
                            len(payload)
                        )

        except Exception as e:

            print(
                f"File write error: {e}"
            )

            self.udp_client.close()
            self.udp_client = None

            return False

        print(
            f"Downloaded "
            f"{total_bytes} bytes "
            f"in {len(packets)} UDP packets"
        )

        # ------------------------------------------------------------
        # TCP 226
        # ------------------------------------------------------------

        response = self._receive_response()

        print(
            f"Server: {response}"
        )

        self.udp_client.close()
        self.udp_client = None

        return response.startswith(
            "226"
        )

    def upload(
        self,
        local_file: str,
        remote_file: str = None
    ):

        if remote_file is None:
            remote_file = os.path.basename(
                local_file
            )

        if not os.path.isfile(local_file):

            print(
                f"Local file not found: "
                f"{local_file}"
            )

            return False

        # ------------------------------------------------------------
        # PASV
        # ------------------------------------------------------------

        response = self._send_command(
            "PASV"
        )

        if not response.startswith("227"):

            print(
                f"PASV failed: {response}"
            )

            return False

        try:

            start = response.find("(") + 1
            end = response.find(")")

            parts = response[
                start:end
            ].split(",")

            server_ip = (
                f"{parts[0]}."
                f"{parts[1]}."
                f"{parts[2]}."
                f"{parts[3]}"
            )

            server_port = (
                int(parts[4]) * 256
                + int(parts[5])
            )

        except Exception as e:

            print(
                f"PASV parse error: {e}"
            )

            return False

        # ------------------------------------------------------------
        # UDP
        # ------------------------------------------------------------

        self.udp_client = ReliableUDPClient()

        self.udp_client.connect_to_server(
            server_ip,
            server_port
        )

        # ------------------------------------------------------------
        # STOR
        # ------------------------------------------------------------

        response = self._send_command(
            f"STOR {remote_file}"
        )

        if not response.startswith("150"):

            print(
                f"STOR failed: {response}"
            )

            self.udp_client.close()
            self.udp_client = None

            return False

        # Server is now waiting for UDP HELLO.
        if not self.udp_client.hello():
            print("UDP handshake failed")
            self.udp_client.close()
            self.udp_client = None
            return False

        print(
            f"Uploading "
            f"{local_file}..."
        )
        # ------------------------------------------------------------
        # READ FILE
        # ------------------------------------------------------------
    
        with open(
            local_file,
            "rb"
        ) as f:
    
            file_data = f.read()
    
        chunk_size = (
            UDP_BUFFER_SIZE
            - ReliableUDPClient.HEADER_SIZE
        )
    
        # ------------------------------------------------------------
        # EMPTY FILE
        # ------------------------------------------------------------
    
        if len(file_data) == 0:
    
            success = (
                self.udp_client.send_packet(
                    0,
                    b"",
                    ReliableUDPClient.FLAG_DATA
                    | ReliableUDPClient.FLAG_FIN
                )
            )
    
            if not success:
    
                print(
                    "Failed to upload empty file"
                )
    
                self.udp_client.close()
                self.udp_client = None
    
                return False
    
        # ------------------------------------------------------------
        # NORMAL FILE
        # ------------------------------------------------------------
    
        else:
    
            chunks = [
                file_data[i:i + chunk_size]
                for i in range(
                    0,
                    len(file_data),
                    chunk_size
                )
            ]
    
            for sequence, chunk in enumerate(
                chunks
            ):
    
                flags = (
                    ReliableUDPClient.FLAG_DATA
                )
    
                if sequence == len(chunks) - 1:
    
                    flags |= (
                        ReliableUDPClient.FLAG_FIN
                    )
    
                success = (
                    self.udp_client.send_packet(
                        sequence,
                        chunk,
                        flags
                    )
                )
    
                if not success:
    
                    print(
                        f"Upload failed at "
                        f"packet {sequence}"
                    )
    
                    self.udp_client.close()
                    self.udp_client = None
    
                    return False
    
        print(
            f"UDP upload complete: "
            f"{len(file_data)} bytes"
        )
    
        self.udp_client.close()
        self.udp_client = None
    
        # ------------------------------------------------------------
        # SERVER 226
        # ------------------------------------------------------------
    
        response = self._receive_response()
    
        print(
            f"Server: {response}"
        )
    
        return response.startswith(
            "226"
        )
    def help(self):
        """Show help"""
        print("Available commands:")
        print("  USER <username> - Login")
        print("  PASS <password> - Password")
        print("  QUIT - Disconnect")
        print("  PWD - Show current directory")
        print("  CWD <path> - Change directory")
        print("  CDUP - Go to parent directory")
        print("  MKD <dirname> - Create directory")
        print("  RMD <dirname> - Remove directory")
        print("  LIST - List files")
        print("  SIZE <filename> - Get file size")
        print("  TYPE {A|I} - Set transfer type")
        print("  RETR <filename> - Download file")
        print("  STOR <filename> - Upload file")
        print("  HELP - Show this help")
        print("  exit - Exit client")


# ================================================================
# Interactive CLI
# ================================================================
class InteractiveCLI:
    """Interactive command-line interface for FTP client"""

    def __init__(self):
        self.client = None
        self.commands = {
            'connect': self.do_connect,
            'disconnect': self.do_disconnect,
            'quit': self.do_quit,
            'exit': self.do_quit,
            'user': self.do_user,
            'pass': self.do_pass,
            'login': self.do_login,
            'pwd': self.do_pwd,
            'cwd': self.do_cwd,
            'cdup': self.do_cdup,
            'mkdir': self.do_mkdir,
            'rmdir': self.do_rmdir,
            'list': self.do_list,
            'ls': self.do_list,
            'size': self.do_size,
            'type': self.do_type,
            'retr': self.do_retr,
            'stor': self.do_stor,
            'get': self.do_retr,
            'put': self.do_stor,
            'help': self.do_help,
            '?': self.do_help,
        }

    def run(self):
        """Run interactive CLI"""
        print("=" * 50)
        print("Hybrid FTP Client - Interactive Mode")
        print("Control: TCP | Data: UDP (with custom reliable layer)")
        print("=" * 50)
        print("Type 'help' or '?' for available commands")

        while True:
            try:
                prompt = "ftp> " if self.client and self.client.authenticated else "ftp (not logged in)> "
                command = input(prompt).strip()

                if not command:
                    continue

                # Parse command
                parts = command.split(None, 1)
                cmd = parts[0].lower()
                args = parts[1].strip() if len(parts) > 1 else ""

                if cmd in self.commands:
                    self.commands[cmd](args)
                else:
                    if self.client:
                        # Forward command to server
                        self.client.send_command(command)
                    else:
                        print("Not connected. Use 'connect' first.")

            except KeyboardInterrupt:
                print("\nExiting...")
                break

    def do_connect(self, args):
        """Connect to server"""
        if not self.client:
            self.client = FTPClient()

        # Parse host:port from args
        host = SERVER_HOST
        port = SERVER_PORT
        if args:
            if ':' in args:
                host, port_str = args.split(':')
                port = int(port_str)

        if self.client.connect():
            print(f"Connected to {host}:{port}")
            self.client.pwd()

    def do_disconnect(self, args):
        """Disconnect from server"""
        if self.client:
            self.client.disconnect()
            print("Disconnected")

    def do_quit(self, args):
        """Quit client"""
        if self.client:
            self.client.disconnect()
        sys.exit(0)

    def do_user(self, args):
        """Send username"""
        if not self.client:
            print("Not connected")
            return
        self.client.send_command(f"USER {args}")

    def do_pass(self, args):
        """Send password"""
        if not self.client:
            print("Not connected")
            return
        self.client.send_command(f"PASS {args}")

    def do_login(self, args):
        """Login with username:password"""
        if not self.client:
            self.client = FTPClient()
            self.client.connect()

        if ':' in args:
            username, password = args.split(':')
            self.client.login(username, password)
        else:
            print("Usage: login <username>:<password>")

    def do_pwd(self, args):
        """Print working directory"""
        if self.client:
            self.client.pwd()

    def do_cwd(self, args):
        """Change working directory"""
        if self.client and args:
            self.client.cwd(args)

    def do_cdup(self, args):
        """Change to parent directory"""
        if self.client:
            self.client.cdup()

    def do_mkdir(self, args):
        """Create directory"""
        if self.client and args:
            self.client.mkdir(args)

    def do_rmdir(self, args):
        """Remove directory"""
        if self.client and args:
            self.client.rmdir(args)

    def do_list(self, args):
        """List directory contents"""
        if self.client:
            self.client.list_files(args)

    def do_size(self, args):
        """Get file size"""
        if self.client and args:
            self.client.size(args)

    def do_type(self, args):
        """Set transfer type"""
        if self.client and args:
            self.client.set_type(args)

    def do_retr(self, args):
        """Download file"""
        if not self.client:
            print("Not connected")
            return
        if not args:
            print("Usage: retr <filename>")
            return
        self.client.download(args)

    def do_stor(self, args):
        """Upload file"""
        if not self.client:
            print("Not connected")
            return
        if not args:
            print("Usage: stor <filename>")
            return
        self.client.upload(args)

    def do_help(self, args):
        """Show help"""
        self.client.help() if self.client else print("Type 'connect' to connect to server")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hybrid FTP Client")
    parser.add_argument("-i", "--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("-H", "--host", default=SERVER_HOST, help="Server host")
    parser.add_argument("-p", "--port", type=int, default=SERVER_PORT, help="Server port")
    parser.add_argument("-u", "--user", help="Username")
    parser.add_argument("-P", "--password", help="Password")
    parser.add_argument("-c", "--command", help="Execute command and exit")
    parser.add_argument("-d", "--download", help="Download file")
    parser.add_argument("-U", "--upload", help="Upload file")
    args = parser.parse_args()

    if args.interactive:
        cli = InteractiveCLI()
        cli.run()
    else:
        client = FTPClient(args.host, args.port)
        if client.connect():
            if args.user and args.password:
                client.login(args.user, args.password)
            if args.command:
                client.send_command(args.command)
            elif args.download:
                client.download(args.download)
            elif args.upload:
                client.upload(args.upload)
        client.disconnect()