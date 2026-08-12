"""
Hybrid FTP Server Test Suite
=============================
Tests for FTP server and reliable UDP layer functionality

Author: Student
Course: Internet Networking Protocol
"""

import socket
import threading
import time
import os
import sys
from unittest import TestCase

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ftp_server import ReliableUDP, FTPSession, FTPServer, UDP_BUFFER_SIZE, FTPResponse


# ================================================================
# Test Reliable UDP Layer
# ================================================================
class TestReliableUDP(TestCase):
    """Test cases for custom reliable UDP protocol"""

    def setUp(self):
        """Setup test environment"""
        self.udp_server = ReliableUDP("127.0.0.1", 0)
        self.server_port = self.udp_server.local_port

    def tearDown(self):
        """Cleanup"""
        if hasattr(self, 'udp_server'):
            self.udp_server.close()

    def test_create_packet(self):
        """Test packet creation with header"""
        sequence = 1
        payload = b"Test payload data"
        packet = self.udp_server.create_packet(sequence, 0, 0x04, payload)

        # Verify packet structure
        self.assertEqual(len(packet), 12 + len(payload))  # 12 header + payload
        self.assertEqual(packet[0:2], sequence.to_bytes(2, 'big'))
        self.assertEqual(packet[4], 0x04)  # SYN flag

    def test_parse_packet(self):
        """Test packet parsing and validation"""
        sequence = 5
        payload = b"Sample data"
        packet = self.udp_server.create_packet(sequence, 0, 0x02, payload)

        # Parse packet
        seq, ack, flags, data, is_valid = self.udp_server.parse_packet(packet)

        self.assertEqual(seq, sequence)
        self.assertEqual(flags, 0x02)  # FIN flag
        self.assertEqual(data, payload)
        self.assertTrue(is_valid)

    def test_checksum_calculation(self):
        """Test checksum calculation for data integrity"""
        data = b"Test checksum"
        checksum1 = self.udp_server.calculate_checksum(data)
        checksum2 = self.udp_server.calculate_checksum(data)

        # Same data should produce same checksum
        self.assertEqual(checksum1, checksum2)

    def test_packet_integrity(self):
        """Test packet data integrity through send-receive cycle"""
        sequence = 10
        payload = b"Integrity test data"
        packet = self.udp_server.create_packet(sequence, 0, 0x04, payload)

        # Parse received packet
        seq, ack, flags, data, is_valid = self.udp_server.parse_packet(packet)

        self.assertTrue(is_valid)
        self.assertEqual(data, payload)


# ================================================================
# Test FTP Commands
# ================================================================
class TestFTPCommands(TestCase):
    """Test cases for FTP command handling"""

    def test_user_command(self):
        """Test USER command for authentication"""
        # Create mock session
        mock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        session = FTPSession(mock_socket, ("127.0.0.1", 8000))

        # Execute USER command
        session.execute_command("USER testuser")

        # Verify username is set
        self.assertEqual(session.username, "testuser")
        mock_socket.close()

    def test_pwd_command(self):
        """Test PWD command for current directory"""
        mock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        session = FTPSession(mock_socket, ("127.0.0.1", 8000))

        # Execute PWD command
        session.execute_command("PWD")
        mock_socket.close()

    def test_noop_command(self):
        """Test NOOP keep-alive command"""
        mock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        session = FTPSession(mock_socket, ("127.0.0.1", 8000))

        # Execute NOOP command
        session.execute_command("NOOP")
        mock_socket.close()


# ================================================================
# Test File Operations
# ================================================================
class TestFileOperations(TestCase):
    """Test cases for file transfer operations"""

    def setUp(self):
        """Create test directory and file"""
        self.test_dir = "test_ftp_data"
        if not os.path.exists(self.test_dir):
            os.makedirs(self.test_dir)
        self.test_file = os.path.join(self.test_dir, "test.txt")
        with open(self.test_file, 'w') as f:
            f.write("Test file content for FTP transfer\n" * 100)

    def tearDown(self):
        """Cleanup test files"""
        if os.path.exists(self.test_file):
            os.remove(self.test_file)
        if os.path.exists(self.test_dir):
            os.rmdir(self.test_dir)

    def test_file_size(self):
        """Test SIZE command for file"""
        mock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        session = FTPSession(mock_socket, ("127.0.0.1", 8000))
        session.authenticated = True
        session.current_directory = self.test_dir

        # Execute SIZE command
        session.execute_command("SIZE test.txt")
        mock_socket.close()

    def test_type_command(self):
        """Test TYPE command for transfer type"""
        mock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        session = FTPSession(mock_socket, ("127.0.0.1", 8000))

        # Set to binary mode
        session.execute_command("TYPE I")
        self.assertEqual(session.transfer_type, "binary")

        # Set to ASCII mode
        session.execute_command("TYPE A")
        self.assertEqual(session.transfer_type, "ascii")
        mock_socket.close()


# ================================================================
# Test UDP Data Transfer
# ================================================================
class TestUDPTransfer(TestCase):
    """Test cases for UDP data transfer with reliable layer"""

    def test_receive_until_fin(self):
        """Test receiving packets until FIN flag"""
        udp_server = ReliableUDP("127.0.0.1", 0)
        udp_client = ReliableUDP("127.0.0.1", 0)

        try:
            # Prepare test packets
            packets = []
            for i in range(3):
                payload = f"Data chunk {i}".encode()
                flags = 0x04  # SYN flag
                if i == 2:
                    flags |= 0x02  # FIN flag on last packet
                packet = udp_client.create_packet(i, 0, flags, payload)
                udp_client.sock.sendto(packet, ("127.0.0.1", udp_server.local_port))
                time.sleep(0.01)

            # Receive packets
            received = udp_server.receive_until_fin()

            # Verify received packets
            self.assertEqual(len(received), 3)

        finally:
            udp_server.close()
            udp_client.close()


# ================================================================
# Test Concurrent Sessions
# ================================================================
class TestConcurrentSessions(TestCase):
    """Test cases for multiple client sessions"""

    def test_multiple_sessions(self):
        """Test handling multiple concurrent sessions"""
        server = FTPServer("127.0.0.1", 2121)

        # Start server in background
        server_thread = threading.Thread(target=server.start, daemon=True)
        server_thread.start()
        time.sleep(1)  # Wait for server to start

        # Create multiple client connections
        clients = []
        try:
            for i in range(3):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(("127.0.0.1", 2121))
                clients.append(sock)
                time.sleep(0.1)

            # Verify connections
            self.assertEqual(len(server.sessions), 3)

        finally:
            server.stop()
            for client in clients:
                client.close()


# ================================================================
# Run All Tests
# ================================================================
if __name__ == "__main__":
    import unittest

    # Create test suite using proper method
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test methods from each class
    suite.addTests(loader.loadTestsFromTestCase(TestReliableUDP))
    suite.addTests(loader.loadTestsFromTestCase(TestFTPCommands))
    suite.addTests(loader.loadTestsFromTestCase(TestFileOperations))
    suite.addTests(loader.loadTestsFromTestCase(TestUDPTransfer))
    suite.addTests(loader.loadTestsFromTestCase(TestConcurrentSessions))

    # Run tests
    print("=" * 50)
    print("Running Hybrid FTP Server Test Suite")
    print("=" * 50)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print(f"\nTests Run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")
