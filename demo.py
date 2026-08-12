"""
Hybrid FTP Server Demo Script
==============================
Demonstrates basic FTP server and client operations

Usage: python demo.py
"""

import socket
import threading
import time
import os
import sys
from ftp_server import FTPServer, FTPSession, ReliableUDP


def create_test_file(filename, content):
    """Create a test file in ftp_root"""
    path = os.path.join("ftp_root", filename)
    with open(path, 'w') as f:
        f.write(content)
    print(f"Created test file: {path}")


def demonstrate_reliable_udp():
    """Demonstrate Reliable UDP Layer"""
    print("=" * 60)
    print("Testing Reliable UDP Layer")
    print("=" * 60)
    
    # Create Reliable UDP server
    udp_server = ReliableUDP("127.0.0.1", 0)
    print(f"UDP Server listening on port {udp_server.local_port}")
    
    # Create test packet
    sequence = 1
    payload = b"Hello from Reliable UDP!"
    packet = udp_server.create_packet(sequence, 0, 0x04, payload)
    
    # Parse packet
    seq, ack, flags, data, is_valid = udp_server.parse_packet(packet)
    
    print(f"\nPacket Analysis:")
    print(f"  Sequence: {seq}")
    print(f"  Flags: {flags} (SYN=1)")
    print(f"  Payload: {data.decode()}")
    print(f"  Checksum Valid: {is_valid}")
    
    # Calculate checksum
    checksum = udp_server.calculate_checksum(payload)
    print(f"  Checksum: {hex(checksum)}")
    
    udp_server.close()
    print("\nUDP Test completed successfully!\n")


def demonstrate_tcp_connection():
    """Demonstrate TCP Control Channel"""
    print("=" * 60)
    print("Testing TCP Control Channel")
    print("=" * 60)
    
    # Start server on port 2121
    server = FTPServer("127.0.0.1", 2121)
    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()
    time.sleep(1)  # Wait for server to start
    
    try:
        # Create TCP client
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", 2121))
        
        # Receive welcome message
        welcome = client.recv(1024).decode()
        print(f"\nWelcome: {welcome.strip()}")
        
        # Send USER command
        client.send(b"USER testuser\r\n")
        response = client.recv(1024).decode()
        print(f"USER Response: {response.strip()}")
        
        # Send PASS command
        client.send(b"PASS testpass\r\n")
        response = client.recv(1024).decode()
        print(f"PASS Response: {response.strip()}")
        
        # Send PWD command
        client.send(b"PWD\r\n")
        response = client.recv(1024).decode()
        print(f"PWD Response: {response.strip()}")
        
        # Send NOOP command (keep-alive)
        client.send(b"NOOP\r\n")
        response = client.recv(1024).decode()
        print(f"NOOP Response: {response.strip()}")
        
        # Send LIST command
        client.send(b"LIST\r\n")
        response = client.recv(1024).decode()
        print(f"LIST Response: {response.strip()}")
        
        # Send HELP command
        client.send(b"HELP\r\n")
        response = client.recv(1024).decode()
        print(f"HELP Response: {response.strip()}")
        
        # Send QUIT command
        client.send(b"QUIT\r\n")
        response = client.recv(1024).decode()
        print(f"QUIT Response: {response.strip()}")
        
        client.close()
        print("\nTCP Test completed successfully!\n")
        
    except Exception as e:
        print(f"TCP Test error: {e}")
    finally:
        server.stop()


def main():
    """Main demonstration"""
    print("=" * 60)
    print("Hybrid FTP Server - Demonstration")
    print("Control: TCP | Data: UDP (with custom reliable layer)")
    print("=" * 60)
    print()
    
    # Create test files
    print("Creating test files...")
    create_test_file("test.txt", "This is a test file for FTP transfer\n" * 100)
    create_test_file("hello.txt", "Hello World from Hybrid FTP!\n")
    print()
    
    # Test 1: Reliable UDP Layer
    demonstrate_reliable_udp()
    
    # Test 2: TCP Control Channel
    demonstrate_tcp_connection()
    
    # Summary
    print("=" * 60)
    print("Demonstration Complete!")
    print("=" * 60)
    print("\nTo start the FTP server:")
    print("  python ftp_server.py")
    print("\nTo run FTP client:")
    print("  python ftp_client.py -i  # Interactive mode")
    print("\nFor more information, see README.md")


if __name__ == "__main__":
    main()
