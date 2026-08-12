# Hybrid FTP Server - Low-level Implementation

## Giới thiệu

Đây là dự án thiết kế và triển khai ứng dụng **Hybrid FTP** - một hệ thống FTP sử dụng **TCP cho kênh điều khiển** và **UDP cho kênh dữ liệu**.

## Kiến trúc hệ thống

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        HYBRID FTP ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌───────────┐                    ┌───────────┐                          │
│  │  CLIENT   │                    │   SERVER  │                          │
│  │           │                    │           │                          │
│  │  ┌───────┐│   TCP Control      │┌───────┐  │                          │
│  │  │ CLI   ││◄──────────────►│ ││     │  │                          │
│  │  │       ││    Channel      ││FTP   │  │                          │
│  │  │ ───── ││  (Port 21)      ││CMD   │  │                          │
│  │  │FTP    ││                  ││HAND- │  │                          │
│  │  │SOCKET ││                  ││LER   │  │                          │
│  │  └───────┘│                  │└───────┘  │                          │
│  │           │                  │           │                          │
│  │  ┌───────┐│   UDP Data       │┌───────┐  │                          │
│  │  │ FILE  ││◄──────────────►│ ││     │  │                          │
│  │  │DATA   ││    Channel      ││FILE  │  │                          │
│  │  └───────┘│  (Dynamic Port) ││SYS   │  │                          │
│  │           │                  │└───────┘  │                          │
│  └───────────┘                    └───────────┘                          │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                    CUSTOM RELIABLE UDP LAYER                         │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │
│  │  │Sequence     │  │   ACK       │  │ Checksum    │                   │
│  │  │Numbers      │◄─► Mechanism   │◄─►   (CRC16)   │                   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                   │
│  │       ┌─────────────────────────────────────────────────────┐       │
│  │       │             TIMEOUT & RETRANSMISSION                 │       │
│  │       │             (Max 5 retries, 2s timeout)              │       │
│  │       └─────────────────────────────────────────────────────┘       │
│  └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

## Cấu trúc mã nguồn

```
FTP_socket/
├── ftp_server.py          # Server code chính
├── ftp_client.py          # Client code chính
├── test_ftp.py            # Test suite
├── ftp_root/              # Root directory cho file operations
└── README.md              # Tài liệu
```

## Các thành phần chính

### 1. Kênh điều khiển TCP (Control Channel)

```python
# TCP Control Channel Flow
┌──────────┐     ┌──────────┐     ┌──────────┐
│  CLIENT  │────►│   TCP    │────►│   FTP    │
│          │◄────│  Socket  │◄────│  SERVER  │
│          │     │ Port 21  │     │          │
└──────────┘     └──────────┘     └──────────┘

Commands: USER, PASS, QUIT, NOOP, PWD, CWD, CDUP, MKD, RMD
          LIST, SIZE, TYPE, PASV, PORT, RETR, STOR, HELP
```

### 2. Kênh dữ liệu UDP (Data Channel)

```python
# Custom Reliable UDP Layer - Packet Structure

┌─────────────────────────────────────────────────────────────────────┐
│                        UDP PACKET HEADER (12 bytes)                  │
├─────────────────────────────────────────────────────────────────────┤
│  Sequence Number (2 bytes)  │    ACK Number (2 bytes)    │          │
├─────────────────────────────────────────────────────────────────────┤
│    Flags (1 byte)    │   Payload Length (2 bytes)   │   Checksum   │
│                        0=ACK, 1=FIN, 2=SYN                      │   (2 bytes)  │
├─────────────────────────────────────────────────────────────────────┤
│                     Reserved (3 bytes)                              │
├─────────────────────────────────────────────────────────────────────┤
│                      Payload Data                                   │
│              (Max 1024 - 12 = 1012 bytes)                           │
└─────────────────────────────────────────────────────────────────────┘
```

### 3. Reliable UDP Protocol

```python
# State Machine

┌──────────┐      SYN       ┌──────────┐
│  IDLE    │──────────────►│ CONNECTED│
└──────────┘                └──────────┘
                               │
                         Send/Receive
                               │
                               ▼
                         ┌──────────┐
                         │  ACTIVE  │
                         └──────────┘
                               │
                             FIN
                               │
                               ▼
                         ┌──────────┐
                         │  CLOSED  │
                         └──────────┘
```

## Các lệnh FTP được hỗ trợ

| Lệnh | Cú pháp | Mô tả |
|------|---------|-------|
| USER | USER <username> | Gửi tên đăng nhập |
| PASS | PASS <password> | Gửi mật khẩu |
| QUIT | QUIT | Ngắt kết nối |
| NOOP | NOOP | Keep-alive ping |
| PWD | PWD | Hiện thư mục hiện tại |
| CWD | CWD <path> | Đổi thư mục |
| CDUP | CDUP | Lên thư mục cha |
| MKD | MKD <dirname> | Tạo thư mục |
| RMD | RMD <dirname> | Xóa thư mục |
| LIST | LIST [path] | Liệt kê file |
| SIZE | SIZE <filename> | Xem kích thước file |
| TYPE | TYPE {A\|I} | Đặt loại truyền |
| PASV | PASV | Chế độ passive |
| RETR | RETR <filename> | Tải xuống file |
| STOR | STOR <filename> | Tải lên file |
| HELP | HELP [command] | Xem hướng dẫn |

## Mã phản hồi FTP

| Mã | Danh mục | Mô tả |
|----|----------|-------|
| 1xx | Positive Preliminary | Yêu cầu tiếp theo |
| 2xx | Positive Completion | Thành công |
| 3xx | Positive Intermediate | Yêu cầu thông tin thêm |
| 4xx | Transient Negative | Lỗi tạm thời |
| 5xx | Permanent Negative | Lỗi vĩnh viễn |

## Cách sử dụng

### Chạy Server

```bash
python ftp_server.py
```

### Chạy Client (Interactive Mode)

```bash
python ftp_client.py -i
```

### Chạy Client (Direct Mode)

```bash
python ftp_client.py -h 127.0.0.1 -p 21
```

### Ví dụ sử dụng Interactive CLI

```
ftp (not logged in)> connect 127.0.0.1 21
ftp> user testuser
ftp> pass password
ftp> pwd
ftp> list
ftp> get file.txt
ftp> put file.txt
ftp> quit
```

## Các tính năng chính

### 1. Basic Level ✓
- ✅ Authentication mechanism
- ✅ ASCII text file handling
- ✅ Single file upload/download
- ✅ Fixed data channel connection

### 2. Advanced Level ✓
- ✅ Binary file handling (images, videos, archives)
- ✅ Directory navigation and tree support
- ✅ Active/Passive mode support
- ✅ Multi-threaded server (multiple client sessions)

### 3. Excellent Level ✓
- ✅ Custom Reliable UDP Layer (RTD)
  - ACKs mechanism
  - Sequence numbers
  - Timeout/Retransmission (Stop-and-Wait)
- ✅ Congestion/Flow Control
  - Sliding window mechanism
  - Maximum packet size
- ✅ Data Integrity Verification
  - Checksum (CRC16) for each packet
  - End-to-end hash verification

## Cấu trúc lớp (Class Structure)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        FTP SERVER CLASSES                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                         FTPServer                                    │
│  │  ───────────────────────────────────────────────────────────────── │ │
│  │  + start() : None                                                    │ │
│  │  + stop() : None                                                     │
│  │  + handle_client(session: FTPSession) : None                       │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                              │                                            │
│                              ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                         FTPSession                                   │
│  │  ───────────────────────────────────────────────────────────────── │ │
│  │  + send_response(code: int, message: str) : None                   │ │
│  │  + receive_command() : str                                          │ │
│  │  + execute_command(command: str) : None                            │ │
│  │  + cmd_user(args: str) : None                                       │ │
│  │  + cmd_pass(args: str) : None                                       │ │
│  │  + cmd_quit() : None                                                │ │
│  │  + cmd_noop() : None                                                │ │
│  │  + cmd_pwd() : None                                                  │ │
│  │  + cmd_cwd(path: str) : None                                        │ │
│  │  + cmd_cdup() : None                                                 │ │
│  │  + cmd_mkd(dirname: str) : None                                     │ │
│  │  + cmd_rmd(dirname: str) : None                                     │ │
│  │  + cmd_list(path: str) : None                                       │ │
│  │  + cmd_size(filename: str) : None                                    │ │
│  │  + cmd_type(args: str) : None                                       │ │
│  │  + cmd_pasv() : None                                                 │ │
│  │  + cmd_retr(filename: str) : None                                    │ │
│  │  + cmd_stor(filename: str) : None                                    │ │
│  │  + cmd_help(args: str) : None                                       │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                              │                                            │
│                              ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                        ReliableUDP                                    │
│  │  ───────────────────────────────────────────────────────────────── │ │
│  │  + calculate_checksum(data: bytes) : int                            │ │
│  │  + create_packet(seq: int, ack: int, flags: int, payload: bytes)   │ │
│  │  + parse_packet(data: bytes) : tuple                                │ │
│  │  + send_packet(seq: int, payload: bytes) : bool                     │ │
│  │  + send_ack(seq: int) : None                                        │ │
│  │  + send_fin() : None                                                 │ │
│  │  + receive_packet() : tuple                                         │ │
│  │  + receive_until_fin() : list                                       │ │
│  │  + close() : None                                                     │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

## Run Tests

```bash
python test_ftp.py
```
