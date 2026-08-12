import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, filedialog
from tkinter import simpledialog
import threading
import socket
import os
import time
from datetime import datetime

# Import from project root
import sys
import os.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ftp_client import FTPClient, ReliableUDPClient, UDP_BUFFER_SIZE, UDP_MAX_RETRIES, UDP_TIMEOUT


class FTPClientGUI:
    """GUI for Hybrid FTP Client"""

    def __init__(self):
        self.client = None
        self.connected = False
        self.authenticated = False
        self.server_host = "127.0.0.1"
        self.server_port = 21
        self.udp_client = None
        self.data_port = None
        self.transfer_thread = None
        self.is_transferring = False
        self.transfer_mode = "binary"  # binary or ascii
        self.remote_files_list = []  # Store remote file info
        self.local_selected_file = None  # Store locally selected file
        self.transfer_size = 0
        self.transfer_transferred = 0

    def create_window(self):
        """Create main window and all UI components"""
        self.root = tk.Tk()
        self.root.title("Hybrid FTP Client")
        self.root.geometry("1000x700")
        self.root.configure(bg="#f0f5f9")

        # Create main container
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")

        # Configure grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Create all UI sections
        self.create_connection_panel(main_frame)
        self.create_login_panel(main_frame)
        self.create_file_browser(main_frame)
        self.create_log_panel(main_frame)
        self.create_status_bar(main_frame)

    def create_connection_panel(self, parent):
        """Create connection panel with IP and Port"""
        conn_frame = ttk.LabelFrame(parent, text="Connection", padding=5)
        conn_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        # IP Address
        ttk.Label(conn_frame, text="Host/IP:").grid(row=0, column=0, padx=5, pady=5)
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.host_entry = ttk.Entry(conn_frame, textvariable=self.host_var, width=20)
        self.host_entry.grid(row=0, column=1, padx=5, pady=5)

        # Port
        ttk.Label(conn_frame, text="Port:").grid(row=0, column=2, padx=5, pady=5)
        self.port_var = tk.StringVar(value="21")
        self.port_entry = ttk.Entry(conn_frame, textvariable=self.port_var, width=5)
        self.port_entry.grid(row=0, column=3, padx=5, pady=5)

        # Transfer mode
        ttk.Label(conn_frame, text="Mode:").grid(row=0, column=4, padx=5, pady=5)
        self.mode_var = tk.StringVar(value="Binary")
        self.mode_combo = ttk.Combobox(conn_frame, textvariable=self.mode_var, 
                                        values=["Binary", "ASCII"], width=10,
                                        state="readonly")
        self.mode_combo.grid(row=0, column=5, padx=5, pady=5)
        self.mode_var.trace_add("write", self.set_transfer_mode)

        # Connect/Disconnect buttons
        btn_frame = ttk.Frame(conn_frame)
        btn_frame.grid(row=0, column=6, padx=5, pady=5)

        self.connect_btn = ttk.Button(btn_frame, text="Connect", command=self.connect)
        self.connect_btn.grid(row=0, column=0, padx=5)

        self.disconnect_btn = ttk.Button(btn_frame, text="Disconnect", command=self.disconnect, state=tk.DISABLED)
        self.disconnect_btn.grid(row=0, column=1, padx=5)

        # Progress bar
        progress_frame = ttk.LabelFrame(conn_frame, text="Transfer Progress", padding=3)
        progress_frame.grid(row=0, column=7, padx=5, pady=5, sticky="ew")
        progress_frame.columnconfigure(1, weight=1)

        self.progress = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, length=200, 
                                         mode='determinate', maximum=100)
        self.progress.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=2)

        self.progress_text_var = tk.StringVar(value="Ready")
        ttk.Label(progress_frame, textvariable=self.progress_text_var, font=("Arial", 8)).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=2)

    def set_transfer_mode(self, event=None):
        """Set transfer mode (binary/ascii)"""
        self.transfer_mode = "binary" if self.mode_var.get() == "Binary" else "ascii"
        if self.authenticated:
            try:
                self.client.set_type("I" if self.transfer_mode == "binary" else "A")
                self.add_log(f"Transfer mode set to {self.transfer_mode.upper()}")
            except Exception as e:
                self.add_log(f"Failed to set transfer mode: {str(e)}", "red")

    def create_login_panel(self, parent):
        """Create login panel with username and password"""
        login_frame = ttk.LabelFrame(parent, text="Login", padding=5)
        login_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        # Username
        ttk.Label(login_frame, text="Username:").grid(row=0, column=0, padx=5, pady=5)
        self.username_var = tk.StringVar()
        self.username_entry = ttk.Entry(login_frame, textvariable=self.username_var, width=20)
        self.username_entry.grid(row=0, column=1, padx=5, pady=5)

        # Password
        ttk.Label(login_frame, text="Password:").grid(row=0, column=2, padx=5, pady=5)
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(login_frame, textvariable=self.password_var, show="*", width=20)
        self.password_entry.grid(row=0, column=3, padx=5, pady=5)

        # Login button
        self.login_btn = ttk.Button(login_frame, text="Login", command=self.login, state=tk.DISABLED)
        self.login_btn.grid(row=0, column=4, padx=5, pady=5)

    def create_file_browser(self, parent):
        """Create file browser with remote and local file views"""
        browser_frame = ttk.Frame(parent)
        browser_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        browser_frame.columnconfigure(0, weight=1)
        browser_frame.columnconfigure(1, weight=1)
        browser_frame.rowconfigure(1, weight=1)

        # Remote File Section
        remote_frame = ttk.LabelFrame(browser_frame, text="Remote Files", padding=5)
        remote_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        remote_frame.columnconfigure(1, weight=1)
        remote_frame.rowconfigure(1, weight=1)

        # Remote directory info
        self.remote_dir_label = ttk.Label(remote_frame, text="Not connected", foreground="red")
        self.remote_dir_label.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        # Remote directory navigation buttons
        remote_nav_frame = ttk.Frame(remote_frame)
        remote_nav_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=5)

        ttk.Button(remote_nav_frame, text="Up", width=3, command=self.remote_cdup).grid(row=0, column=0, padx=2)
        self.remote_path_var = tk.StringVar()
        ttk.Entry(remote_nav_frame, textvariable=self.remote_path_var, width=30).grid(row=0, column=1, padx=2)
        ttk.Button(remote_nav_frame, text="Go", width=3, command=self.remote_cwd).grid(row=0, column=2, padx=2)

        # Remote file list with scrollbar
        remote_list_frame = ttk.Frame(remote_frame)
        remote_list_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        remote_list_frame.columnconfigure(0, weight=1)
        remote_list_frame.rowconfigure(0, weight=1)

        self.remote_list = tk.Listbox(remote_list_frame, width=50, height=15)
        self.remote_list.grid(row=0, column=0, sticky="nsew")
        self.remote_list.bind("<<Double-Button-1>>", self.remote_file_double_click)
        
        # Remote scrollbar
        remote_scrollbar = ttk.Scrollbar(remote_list_frame, orient=tk.VERTICAL, 
                                          command=self.remote_list.yview)
        remote_scrollbar.grid(row=0, column=1, sticky="ns")
        self.remote_list.config(yscrollcommand=remote_scrollbar.set)
        
        # Create context menu for remote files
        self.remote_menu = tk.Menu(remote_frame, tearoff=0)
        self.remote_menu.add_command(label="Download", command=self.download_file)
        self.remote_menu.add_command(label="Navigate", command=lambda: self.remote_cwd(self.remote_list.get(self.remote_list.curselection()[0]).split("]  ")[1].strip()))
        self.remote_list.bind("<Button-3>", self.show_remote_context_menu)

        # Remote navigation buttons
        remote_btn_frame = ttk.Frame(remote_frame)
        remote_btn_frame.grid(row=2, column=0, columnspan=2, padx=5, pady=5)

        ttk.Button(remote_btn_frame, text="Refresh", width=10, command=self.refresh_remote).grid(row=0, column=0, padx=5)
        ttk.Button(remote_btn_frame, text="New Folder", width=10, command=self.remote_mkdir).grid(row=0, column=1, padx=5)

        # Transfer buttons (middle)
        transfer_frame = ttk.Frame(browser_frame)
        transfer_frame.grid(row=0, rowspan=2, column=1, sticky="n", padx=5, pady=100)
        transfer_frame.columnconfigure(0, weight=1)
        transfer_frame.rowconfigure(0, weight=1)

        # Download button
        self.download_btn = ttk.Button(transfer_frame, text="Download ▼", command=self.download_file, width=15)
        self.download_btn.grid(row=0, column=0, sticky="w", pady=5)

        # Upload button
        self.upload_btn = ttk.Button(transfer_frame, text="Upload ▲", command=self.upload_file, width=15)
        self.upload_btn.grid(row=1, column=0, sticky="w", pady=5)

        # Local File Section
        local_frame = ttk.LabelFrame(browser_frame, text="Local Files", padding=5)
        local_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
        local_frame.columnconfigure(1, weight=1)
        local_frame.rowconfigure(1, weight=1)

        # Local directory info
        self.local_dir_label = ttk.Label(local_frame, text="Local directory: " + os.getcwd(), foreground="blue")
        self.local_dir_label.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        # Local directory navigation buttons
        local_nav_frame = ttk.Frame(local_frame)
        local_nav_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=5)

        ttk.Button(local_nav_frame, text="Up", width=3, command=self.local_cdup).grid(row=0, column=0, padx=2)
        self.local_path_var = tk.StringVar(value=os.getcwd())
        ttk.Entry(local_nav_frame, textvariable=self.local_path_var, width=30).grid(row=0, column=1, padx=2)
        ttk.Button(local_nav_frame, text="Go", width=3, command=self.local_cwd).grid(row=0, column=2, padx=2)

        # Local file list with scrollbar
        local_list_frame = ttk.Frame(local_frame)
        local_list_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        local_list_frame.columnconfigure(0, weight=1)
        local_list_frame.rowconfigure(0, weight=1)

        self.local_list = tk.Listbox(local_list_frame, width=50, height=15)
        self.local_list.grid(row=0, column=0, sticky="nsew")
        self.local_list.bind("<<Double-Button-1>>", self.local_file_double_click)
        
        # Local scrollbar
        local_scrollbar = ttk.Scrollbar(local_list_frame, orient=tk.VERTICAL, 
                                         command=self.local_list.yview)
        local_scrollbar.grid(row=0, column=1, sticky="ns")
        self.local_list.config(yscrollcommand=local_scrollbar.set)
        
        # Create context menu for local files
        self.local_menu = tk.Menu(local_frame, tearoff=0)
        self.local_menu.add_command(label="Upload", command=self.upload_selected_file)
        self.local_menu.add_command(label="Navigate", command=lambda: self.local_cwd(os.path.join(self.local_path_var.get(), self.local_list.get(self.local_list.curselection()[0]).split("]  ")[1].strip())))
        self.local_list.bind("<Button-3>", self.show_local_context_menu)

        # Local navigation buttons
        local_btn_frame = ttk.Frame(local_frame)
        local_btn_frame.grid(row=2, column=0, columnspan=2, padx=5, pady=5)

        ttk.Button(local_btn_frame, text="Refresh", width=10, command=self.refresh_local).grid(row=0, column=0, padx=5)
        ttk.Button(local_btn_frame, text="Open Folder", width=10, command=self.local_select_dir).grid(row=0, column=1, padx=5)

        # Populate local file list
        self.refresh_local()

    def create_log_panel(self, parent):
        """Create log panel to display operations"""
        log_frame = ttk.LabelFrame(parent, text="Log", padding=5)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=5, pady=5)
        log_frame.columnconfigure(1, weight=1)
        log_frame.rowconfigure(1, weight=1)

        # Log text with scrollbar
        log_content_frame = ttk.Frame(log_frame)
        log_content_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        log_content_frame.columnconfigure(0, weight=1)
        log_content_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_content_frame, height=8, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.config(font=("Consolas", 9))

        # Log scrollbar
        log_scrollbar = ttk.Scrollbar(log_content_frame, orient=tk.VERTICAL, 
                                       command=self.log_text.yview)
        log_scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.config(yscrollcommand=log_scrollbar.set)

        # Clear log button
        ttk.Button(log_frame, text="Clear Log", command=self.clear_log).grid(row=0, column=1, sticky="e", padx=5, pady=5)
        
        # Command input
        self.command_var = tk.StringVar()
        self.command_entry = ttk.Entry(log_frame, textvariable=self.command_var, width=60)
        self.command_entry.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        self.command_entry.bind("<Return>", self.execute_command)
        ttk.Button(log_frame, text="Send", command=self.execute_command_func).grid(row=2, column=2, sticky="e", padx=5, pady=5)
        
        self.command_var.trace_add("write", self._on_command_change)

    def create_status_bar(self, parent):
        """Create status bar at the bottom"""
        self.status_frame = ttk.Frame(parent)
        self.status_frame.grid(row=4, column=0, sticky="ew", padx=5, pady=5)

        # Status label
        self.status_var = tk.StringVar(value="Not connected")
        self.status_label = ttk.Label(self.status_frame, textvariable=self.status_var, foreground="red")
        self.status_label.pack(side=tk.LEFT, padx=5)

        # Transfer progress
        self.progress_var = tk.StringVar(value="")
        self.progress_label = ttk.Label(self.status_frame, textvariable=self.progress_var)
        self.progress_label.pack(side=tk.RIGHT, padx=5)

    def add_log(self, message, color="black"):
        """Add log entry to the log panel"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("[%H:%M:%S.%f]")
        self.log_text.insert(tk.END, f"{timestamp} - {message}\n")
        self.log_text.tag_add("tag", "end-1l")
        self.log_text.tag_configure("tag", foreground=color)
        self.log_text.config(state=tk.DISABLED)
        self.log_text.see(tk.END)

    def clear_log(self):
        """Clear log panel"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

    def set_status(self, status, color="red"):
        """Update status bar"""
        self.status_var.set(status)
        self.status_label.config(foreground=color)

    def connect(self):
        """Connect to FTP server"""
        if self.connected:
            messagebox.showwarning("Warning", "Already connected!")
            return

        self.server_host = self.host_var.get()
        self.server_port = int(self.port_var.get())

        self.add_log(f"Connecting to {self.server_host}:{self.server_port}...")
        self.set_status("Connecting...", "orange")

        try:
            # Create FTP client
            self.client = FTPClient(self.server_host, self.server_port)

            # Connect in background thread
            thread = threading.Thread(target=self.connect_thread, args=(self.server_host, self.server_port), daemon=True)
            thread.start()

        except Exception as e:
            self.add_log(f"Connection error: {str(e)}", "red")
            self.set_status("Connection failed", "red")
            messagebox.showerror("Error", f"Connection failed: {str(e)}")

    def connect_thread(self, host, port):
        """Connect thread function"""
        try:
            # Create TCP socket for control channel
            self.client.control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client.control_socket.settimeout(5)
            self.client.control_socket.connect((host, port))

            # Receive welcome message
            welcome = self.client._receive_response()
            self.connected = True
            self.authenticated = False

            # Update UI
            self.root.after(0, self.on_connect_success, welcome)

        except Exception as e:
            self.root.after(0, self.on_connect_error, str(e))

    def on_connect_success(self, welcome):
        """Handle successful connection"""
        self.set_status("Connected", "green")
        self.add_log(f"Connected successfully")
        self.add_log(f"Welcome: {welcome}")

        # Update UI state
        self.login_btn.config(state=tk.NORMAL)
        self.connect_btn.config(state=tk.DISABLED)
        self.disconnect_btn.config(state=tk.NORMAL)
        self.host_entry.config(state=tk.DISABLED)
        self.port_entry.config(state=tk.DISABLED)
        self.progress_text_var.set("Connected - Ready to login")

    def on_connect_error(self, error):
        """Handle connection error"""
        self.set_status("Connection failed", "red")
        self.add_log(f"Connection failed: {error}", "red")
        messagebox.showerror("Error", f"Connection failed: {error}")

    def disconnect(self):
        """Disconnect from server"""
        if not self.connected:
            messagebox.showwarning("Warning", "Not connected!")
            return

        self.add_log("Disconnecting...")
        try:
            if self.client:
                self.client.send_command("QUIT")
            self.client.disconnect()
            self.connected = False
            self.authenticated = False
            self.set_status("Disconnected", "red")
            self.add_log("Disconnected successfully")

            # Reset UI state
            self.login_btn.config(state=tk.DISABLED)
            self.connect_btn.config(state=tk.NORMAL)
            self.disconnect_btn.config(state=tk.DISABLED)
            self.remote_dir_label.config(text="Not connected", foreground="red")
            self.host_entry.config(state=tk.NORMAL)
            self.port_entry.config(state=tk.NORMAL)
            self.remote_list.delete(0, tk.END)
            self.remote_files_list = []
            self.progress_text_var.set("Ready")
            self.progress["value"] = 0

        except Exception as e:
            self.add_log(f"Disconnect error: {str(e)}", "red")

    def login(self):
        """Login to FTP server"""
        if not self.connected:
            messagebox.showwarning("Warning", "Not connected!")
            return

        username = self.username_var.get()
        password = self.password_var.get()

        if not username or not password:
            messagebox.showwarning("Warning", "Username and password are required!")
            return

        self.add_log(f"Logging in as {username}...")
        thread = threading.Thread(target=self.login_thread, args=(username, password), daemon=True)
        thread.start()

    def login_thread(self, username, password):
        """Login thread function"""
        try:
            response = self.client._send_command(f"USER {username}")
            if not response.startswith("331"):
                self.root.after(0, self.login_failed, "Invalid username")
                return

            response = self.client._send_command(f"PASS {password}")
            if response.startswith("230"):
                self.authenticated = True
                self.client.authenticated = True
                self.client.username = username

                # Get current directory
                self.client.pwd()

                self.root.after(0, self.on_login_success)
            else:
                self.root.after(0, self.login_failed, "Invalid password")

        except Exception as e:
            self.root.after(0, self.login_failed, f"Login error: {str(e)}")

    def on_login_success(self):
        """Handle successful login"""
        self.set_status("Logged in", "green")
        self.add_log("Login successful")
        self.add_log(f"Current directory: {self.client.current_directory}")
        self.remote_dir_label.config(text=self.client.current_directory, foreground="green")
        self.refresh_remote()

    def login_failed(self, error):
        """Handle login failure"""
        self.set_status("Login failed", "red")
        self.add_log(f"Login failed: {error}", "red")
        messagebox.showerror("Error", f"Login failed: {error}")

    def remote_cdup(self):
        """Change to parent directory on remote server"""
        if not self.authenticated:
            messagebox.showwarning("Warning", "Not logged in!")
            return
        try:
            self.client.cdup()
            self.refresh_remote()
        except Exception as e:
            self.add_log(f"Error: {str(e)}", "red")

    def remote_cwd(self, path=None):
        """Change working directory on remote server"""
        if not self.authenticated:
            messagebox.showwarning("Warning", "Not logged in!")
            return
        if not path:
            path = self.remote_path_var.get()
        try:
            self.client.cwd(path)
            self.refresh_remote()
        except Exception as e:
            self.add_log(f"Error: {str(e)}", "red")

    def remote_mkdir(self):
        """Create directory on remote server"""
        if not self.authenticated:
            messagebox.showwarning("Warning", "Not logged in!")
            return
        dirname = simpledialog.askstring("New Folder", "Enter folder name:")
        if dirname:
            try:
                self.client.mkdir(dirname)
                self.refresh_remote()
            except Exception as e:
                self.add_log(f"Error: {str(e)}", "red")

    def refresh_remote(self):
        """Refresh remote file list"""
        if not self.authenticated:
            return
        try:
            self.remote_list.delete(0, tk.END)
            self.remote_files_list = []
            
            # Use LIST command to get remote files
            self.client.send_command("LIST")
            
            # Receive file listing from server
            try:
                # Wait a bit for server to send data
                import time
                time.sleep(0.1)
                self.client.control_socket.settimeout(1)
                data = self.client.control_socket.recv(4096).decode()
                self.client.control_socket.settimeout(30)
                
                # Parse listing
                lines = data.split('\r\n')
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parts = line.rsplit(' ', 2)
                        if len(parts) >= 3:
                            is_dir = parts[0].startswith('d')
                            size = int(parts[-2])
                            filename = parts[-1]
                            
                            if is_dir and filename not in ['.', '..']:
                                self.remote_list.insert(tk.END, f"[DIR]  {filename:<40} {size} bytes")
                                self.remote_files_list.append((filename, True, size))
                            else:
                                self.remote_list.insert(tk.END, f"[FILE] {filename:<40} {size} bytes")
                                self.remote_files_list.append((filename, False, size))
                    except:
                        # Try to add line as-is
                        if line and not line.startswith("226"):
                            self.remote_list.insert(tk.END, line)
                
            except socket.timeout:
                pass
            except Exception:
                pass
            
            self.add_log("Remote files refreshed")
        except Exception as e:
            self.add_log(f"Failed to refresh remote files: {str(e)}", "red")

    def refresh_local(self):
        """Refresh local file list"""
        try:
            current_dir = self.local_path_var.get()
            self.local_list.delete(0, tk.END)
            for item in os.listdir(current_dir):
                path = os.path.join(current_dir, item)
                if os.path.isdir(path):
                    self.local_list.insert(tk.END, f"[DIR]  {item}")
                else:
                    size = os.path.getsize(path)
                    self.local_list.insert(tk.END, f"[FILE] {item:<40} {size} bytes")
        except Exception:
            pass

    def local_cdup(self):
        """Change to parent directory locally"""
        current_dir = self.local_path_var.get()
        parent_dir = os.path.dirname(current_dir)
        self.local_path_var.set(parent_dir)
        self.refresh_local()

    def local_cwd(self):
        """Change working directory locally"""
        path = self.local_path_var.get()
        if os.path.isdir(path):
            self.local_path_var.set(path)
            self.refresh_local()

    def local_select_dir(self):
        """Select local directory"""
        path = filedialog.askdirectory()
        if path:
            self.local_path_var.set(path)
            self.refresh_local()

    def local_file_double_click(self, event):
        """Double-click local file to select it for upload"""
        selection = self.local_list.curselection()
        if selection:
            item = self.local_list.get(selection[0])
            if item.startswith("[DIR]"):
                # Navigate to directory
                dir_name = item.split("]  ")[1].strip()
                current_dir = self.local_path_var.get()
                new_path = os.path.join(current_dir, dir_name)
                if os.path.isdir(new_path):
                    self.local_path_var.set(new_path)
                    self.refresh_local()
            else:
                # Select file for upload
                self.local_selected_file = item.split("] ")[1].strip().split()[0]
                self.add_log(f"Selected for upload: {self.local_selected_file}")

    def remote_file_double_click(self, event):
        """Double-click remote file to download"""
        selection = self.remote_list.curselection()
        if selection:
            item = self.remote_list.get(selection[0])
            if item.startswith("[DIR]"):
                # Navigate to directory
                dir_name = item.split("]  ")[1].strip()
                self.remote_cwd(dir_name)
            else:
                # Download file
                self.download_file()

    def download_file(self):
        """Download file from remote to local"""
        if not self.authenticated:
            messagebox.showwarning("Warning", "Not logged in!")
            return

        selection = self.remote_list.curselection()
        if not selection:
            messagebox.showwarning("Warning", "No file selected!")
            return

        # Get selected file name
        file_name = self.remote_list.get(selection[0]).split("] ")[1].strip().split()[0]
        if file_name.startswith("[DIR]"):
            messagebox.showwarning("Warning", "Cannot download directory!")
            return

        # Ask for save location
        local_path = filedialog.asksaveasfilename(
            title="Save As",
            initialfile=file_name
        )
        if not local_path:
            return

        # Reset progress
        self.progress["value"] = 0
        self.progress_text_var.set(f"Downloading {file_name}...")

        # Start download
        thread = threading.Thread(target=self.download_thread, args=(file_name, local_path), daemon=True)
        thread.start()

    def download_thread(self, file_name, local_path):
        """Download thread function"""
        try:
            self.client.download(file_name, local_path)
            self.root.after(0, self.on_download_complete, file_name, local_path, True)
        except Exception as e:
            self.root.after(0, self.on_download_complete, file_name, local_path, False, str(e))

    def on_download_complete(self, file_name, local_path, success, error=None):
        """Handle download completion"""
        if success:
            self.progress["value"] = 100
            self.progress_text_var.set("Download complete")
            self.add_log(f"Downloaded: {file_name} to {local_path}")
            messagebox.showinfo("Success", "Download complete!")
            self.refresh_remote()
        else:
            self.progress["value"] = 0
            self.progress_text_var.set("Download failed")
            self.add_log(f"Download failed: {error}", "red")
            messagebox.showerror("Error", f"Download failed: {error}")

    def upload_file(self):
        """Upload file from local to remote"""
        if not self.authenticated:
            messagebox.showwarning("Warning", "Not logged in!")
            return

        # Ask for file to upload
        local_path = filedialog.askopenfilename(
            title="Select File to Upload",
            filetypes=(("All Files", "*.*"),)
        )
        if not local_path:
            return

        # Get remote file name
        remote_file = os.path.basename(local_path)

        # Reset progress
        self.progress["value"] = 0
        self.progress_text_var.set(f"Uploading {remote_file}...")

        # Start upload
        thread = threading.Thread(target=self.upload_thread, args=(local_path, remote_file), daemon=True)
        thread.start()

    def upload_thread(self, local_path, remote_file):
        """Upload thread function"""
        try:
            self.add_log(
                f"Starting upload: {local_path}"
            )

            success = self.client.upload(
                local_path,
                remote_file
            )

            if success:
                self.root.after(
                    0,
                    self.on_upload_complete,
                    remote_file,
                    True
                )
            else:
                self.root.after(
                    0,
                    self.on_upload_complete,
                    remote_file,
                    False,
                    "FTP client upload returned False"
                )

        except Exception as e:
            self.root.after(
                0,
                self.on_upload_complete,
                remote_file,
                False,
                str(e)
            )
    def on_upload_complete(self, remote_file, success, error=None):
        """Handle upload completion"""
        if success:
            self.progress["value"] = 100
            self.progress_text_var.set("Upload complete")
            self.add_log(f"Uploaded: {remote_file}")
            messagebox.showinfo("Success", "Upload complete!")
            self.refresh_remote()
        else:
            self.progress["value"] = 0
            self.progress_text_var.set("Upload failed")
            self.add_log(f"Upload failed: {error}", "red")
            messagebox.showerror("Error", f"Upload failed: {error}")

    def show_remote_context_menu(self, event):
        """Show context menu for remote files"""
        # Update menu based on selection
        self.remote_menu.delete(0, tk.END)
        
        selection = self.remote_list.curselection()
        if selection:
            item = self.remote_list.get(selection[0])
            if item.startswith("[DIR]"):
                self.remote_menu.add_command(label="Navigate", command=lambda: self.remote_cwd(item.split("]  ")[1].strip()))
            else:
                self.remote_menu.add_command(label="Download", command=self.download_file)
        
        self.remote_menu.tk_popup(event.x_root, event.y_root)

    def show_local_context_menu(self, event):
        """Show context menu for local files"""
        # Update menu based on selection
        self.local_menu.delete(0, tk.END)
        
        selection = self.local_list.curselection()
        if selection:
            item = self.local_list.get(selection[0])
            if item.startswith("[DIR]"):
                dir_name = item.split("]  ")[1].strip()
                self.local_menu.add_command(label="Navigate", command=lambda: self.local_cwd(os.path.join(self.local_path_var.get(), dir_name)))
            else:
                self.local_menu.add_command(label="Upload", command=self.upload_selected_file)
        
        self.local_menu.tk_popup(event.x_root, event.y_root)

    def upload_selected_file(self):
        """Upload selected file from local list"""
        if not self.authenticated:
            messagebox.showwarning("Warning", "Not logged in!")
            return

        selection = self.local_list.curselection()
        if not selection:
            messagebox.showwarning("Warning", "No file selected!")
            return

        item = self.local_list.get(selection[0])
        if item.startswith("[DIR]"):
            messagebox.showwarning("Warning", "Cannot upload directory!")
            return

        file_name = item.split("] ")[1].strip().split()[0]
        local_path = os.path.join(self.local_path_var.get(), file_name)

        # Reset progress
        self.progress["value"] = 0
        self.progress_text_var.set(f"Uploading {file_name}...")

        # Start upload
        thread = threading.Thread(target=self.upload_thread, args=(local_path, file_name), daemon=True)
        thread.start()

    def execute_command(self, event=None):
        """Execute command from command input (called on Enter key)"""
        self.execute_command_func()

    def execute_command_func(self):
        """Execute command from command input"""
        if not self.connected:
            messagebox.showwarning("Warning", "Not connected!")
            return
        
        command = self.command_var.get().strip()
        if not command:
            return
        
        self.add_log(f"Command: {command}")
        try:
            response = self.client._send_command(command)
            self.add_log(f"Response: {response}")
        except Exception as e:
            self.add_log(f"Command error: {str(e)}", "red")
        
        self.command_var.set("")

    def _on_command_change(self, *args):
        """Handle command input change"""
        # Optional: add validation or hints here
        pass

    def run(self):
        """Run the GUI application"""
        self.create_window()
        self.root.mainloop()


if __name__ == "__main__":
    gui = FTPClientGUI()
    gui.run()


if __name__ == "__main__":
    app = FTPClientGUI()
    app.run()


