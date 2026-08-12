import socket
import os
import sys
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
    Custom reliable UDP protocol for client
    - Sequence numbers for ordering
    - ACK mechanism
    - Timeout and retransmission
    - Checksum for data integrity
    """

    def __init__(self):
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(UDP_TIMEOUT)
        self.local_port = self.sock.getsockname()[1]
        self.server_addr: Optional[tuple[str, int]] = None
        self.sequence = 0

    def calculate_checksum(self, data: bytes) -> int:
        """Calculate checksum for data integrity"""
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
        """Create reliable UDP packet with 12-byte header"""
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
        """Parse packet, return (seq, ack, flags, payload, is_valid)"""
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

    def connect_to_server(self, host, port):
        """Connect to server's UDP port"""
        self.server_addr = (host, port)
        print(f"Connected to server UDP at {self.server_addr}")

    def send_packet(self, sequence: int, payload: bytes = b"", flags: int = 0x04):
        """Send packet with retransmission"""
        if self.server_addr is None:
            return False

        packet = self.create_packet(
            sequence,
            0,
            flags,
            payload
        )

        for _ in range(UDP_MAX_RETRIES):
            try:
                self.sock.sendto(
                    packet,
                    self.server_addr
                )

                try:
                    ack_data, _ = self.sock.recvfrom(64)

                    if (
                        len(ack_data) >= 12
                        and ack_data[4] & 0x01
                    ):
                        return True

                except TimeoutError:
                    pass

            except Exception as e:
                print(f"Send error: {e}")

        return False
    def send_ack(self, ack_sequence: int):
        """Send ACK for received packet"""
        if self.server_addr is None:
            return
        ack_packet = self.create_packet(ack_sequence, 0, 0x01)
        self.sock.sendto(ack_packet, self.server_addr)

    def receive_packet(self):
        """Receive and parse packet, send ACK"""
        try:
            data, _ = self.sock.recvfrom(UDP_BUFFER_SIZE + 128)
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

    def receive_all(self):
        """Receive all packets until FIN flag"""
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

    def download(self, remote_file: str, local_file: str = None):
        """Download file from server"""
        if not local_file:
            local_file = remote_file

        # Enter passive mode
        response = self._send_command("PASV")
        if not response.startswith("227"):
            print(f"PASV failed: {response}")
            return False

        # Parse port from PASV response
        try:
            # Format: 227 Entering Passive Mode (127,0,0,1,high,low)
            port_start = response.find("(") + 1
            port_end = response.find(")")
            port_info = response[port_start:port_end]
            parts = port_info.split(",")
            server_ip = f"{parts[0]}.{parts[1]}.{parts[2]}.{parts[3]}"
            server_port = int(parts[4]) * 256 + int(parts[5])
        except Exception as e:
            print(f"Failed to parse PASV response: {e}")
            return False

        # Initialize UDP client
        self.udp_client = ReliableUDPClient()
        self.udp_client.connect_to_server(server_ip, server_port)

        # Request file transfer
        response = self._send_command(f"RETR {remote_file}")
        if not response.startswith("150"):
            print(f"RETR failed: {response}")
            return False

        print(f"Downloading {remote_file} to {local_file}...")

        # Receive data via UDP
        packets = self.udp_client.receive_all()

        # Write to local file
        with open(local_file, 'wb') as f:
            for _, payload in packets:
                f.write(payload)

        print(f"Downloaded {len(packets)} packets, {len(packets) * (UDP_BUFFER_SIZE - 12)} bytes")

        # Check completion
        response = self._receive_response()
        print(response)

        self.udp_client.close()
        return response.startswith("226")

    def upload(self, local_file: str, remote_file: str = None):
        """Upload file to server"""
        if not remote_file:
            remote_file = os.path.basename(local_file)

        if not os.path.exists(local_file):
            print(f"Local file not found: {local_file}")
            return False

        # Initialize UDP client
        self.udp_client = ReliableUDPClient()

        # Enter passive mode FIRST to get data port
        response = self._send_command("PASV")
        if not response.startswith("227"):
            print(f"PASV failed: {response}")
            return False

        try:
            port_start = response.find("(") + 1
            port_end = response.find(")")
            port_info = response[port_start:port_end]
            parts = port_info.split(",")
            server_ip = f"{parts[0]}.{parts[1]}.{parts[2]}.{parts[3]}"
            server_port = int(parts[4]) * 256 + int(parts[5])
        except Exception:
            print("Failed to parse PASV response")
            return False

        self.udp_client.connect_to_server(server_ip, server_port)

        # NOW request upload
        response = self._send_command(f"STOR {remote_file}")
        if not response.startswith("150"):
            print(f"STOR failed: {response}")
            return False

        print(f"Uploading {local_file} to {remote_file}...")

        # Read and send file data
        with open(local_file, 'rb') as f:
            file_data = f.read()

        chunk_size = UDP_BUFFER_SIZE - 12
        chunks = [file_data[i:i + chunk_size] for i in range(0, len(file_data), chunk_size)]

        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1

            flags = 0x04

            if is_last:
                flags |= 0x02

            if not self.udp_client.send_packet(
                i,
                chunk,
                flags
            ):
                print(
                    f"Upload failed at packet {i}"
                )
                return False

        print(
            f"Uploaded {len(chunks)} packets"
        )

        self.udp_client.close()

        return True

        print(f"Uploaded {len(chunks)} packets")
        self.udp_client.close()
        return True

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
    parser.add_argument("-h", "--host", default=SERVER_HOST, help="Server host")
    parser.add_argument("-p", "--port", type=int, default=SERVER_PORT, help="Server port")
    parser.add_argument("-u", "--user", help="Username")
    parser.add_argument("-P", "--password", help="Password")
    parser.add_argument("-c", "--command", help="Execute command and exit")
    parser.add_argument("-d", "--download", help="Download file")
    parser.add_argument("-u", "--upload", help="Upload file")
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


# ================================================================
# Main Entry Point
# ================================================================
if __name__ == "__main__":
    print("Hybrid FTP Client")
    print("Usage:")
    print("  python ftp_client.py -i                    # Interactive mode")
    print("  python ftp_client.py -h <host> -p <port>  # Connect to specific server")

    if len(sys.argv) > 1 and sys.argv[1] == "-i":
        # Interactive mode
        cli = InteractiveCLI()
        cli.run()
    else:
        # Direct connection mode
        host = SERVER_HOST
        port = SERVER_PORT
        if len(sys.argv) > 2 and sys.argv[1] == "-h":
            host = sys.argv[2]
        if len(sys.argv) > 4 and sys.argv[3] == "-p":
            port = int(sys.argv[4])

        client = FTPClient(host, port)
        if client.connect():
            username = input("Username: ")
            password = input("Password: ")
            if client.login(username, password):
                # Interactive session
                while True:
                    command = input("ftp> ").strip()
                    if command == "quit" or command == "exit":
                        break
                    client.send_command(command)
            client.disconnect()
