import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, simpledialog
import threading
import socket
import time
import os
from datetime import datetime

# Import from project root
import sys
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

from ftp_server import FTPServer, HOST, TCP_PORT, MAX_CONNECTIONS, SESSION_TIMEOUT, DATA_DIR


class FTPServerGUI:
    """GUI for Hybrid FTP Server - Admin Interface"""

    def __init__(self):
        self.server = None
        self.server_thread = None
        self.is_running = False
        self.host = HOST
        self.port = TCP_PORT
        self.max_connections = MAX_CONNECTIONS
        self.session_timeout = SESSION_TIMEOUT
        self.data_dir = DATA_DIR
        self.refresh_interval = 1000  # Refresh clients every 1 second
        self.log_lock = threading.Lock()

    def create_window(self):
        """Create main window and all UI components"""
        self.root = tk.Tk()
        self.root.title("Hybrid FTP Server - Admin Panel")
        self.root.geometry("1100x750")
        self.root.configure(bg="#f1f5f9")

        # Create main container
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")

        # Configure grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Create all UI sections
        self.create_server_control_panel(main_frame)
        self.create_connected_clients_panel(main_frame)
        self.create_log_panel(main_frame)
        self.create_status_bar(main_frame)

    def create_server_control_panel(self, parent):
        """Create server control panel with start/stop and settings"""
        control_frame = ttk.LabelFrame(parent, text="Server Control", padding=5)
        control_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        # Server settings row
        ttk.Label(control_frame, text="Host/IP:").grid(row=0, column=0, padx=5, pady=5)
        self.host_var = tk.StringVar(value=self.host)
        ttk.Entry(control_frame, textvariable=self.host_var, width=20).grid(
            row=0, column=1, padx=5, pady=5)

        ttk.Label(control_frame, text="Port:").grid(row=0, column=2, padx=5, pady=5)
        self.port_var = tk.StringVar(value=str(self.port))
        ttk.Entry(control_frame, textvariable=self.port_var, width=10).grid(
            row=0, column=3, padx=5, pady=5)

        ttk.Label(control_frame, text="Max Connections:").grid(row=0, column=4, padx=5, pady=5)
        self.max_conn_var = tk.StringVar(value=str(self.max_connections))
        ttk.Entry(control_frame, textvariable=self.max_conn_var, width=5).grid(
            row=0, column=5, padx=5, pady=5)

        ttk.Label(control_frame, text="Timeout (s):").grid(row=0, column=6, padx=5, pady=5)
        self.timeout_var = tk.StringVar(value=str(self.session_timeout))
        ttk.Entry(control_frame, textvariable=self.timeout_var, width=5).grid(
            row=0, column=7, padx=5, pady=5)

        ttk.Label(control_frame, text="Data Dir:").grid(row=0, column=8, padx=5, pady=5)
        self.data_dir_var = tk.StringVar(value=self.data_dir)
        ttk.Entry(control_frame, textvariable=self.data_dir_var, width=20).grid(
            row=0, column=9, padx=5, pady=5)

        # Control buttons
        self.start_btn = ttk.Button(control_frame, text="Start Server", 
                                     command=self.start_server, style="Start.TButton")
        self.start_btn.grid(row=0, column=10, padx=5, pady=5)

        self.stop_btn = ttk.Button(control_frame, text="Stop Server", 
                                    command=self.stop_server, state=tk.DISABLED,
                                    style="Stop.TButton")
        self.stop_btn.grid(row=0, column=11, padx=5, pady=5)

        self.refresh_clients_btn = ttk.Button(control_frame, text="Refresh Clients", 
                                               command=self.refresh_clients)
        self.refresh_clients_btn.grid(row=0, column=12, padx=5, pady=5)

    def create_connected_clients_panel(self, parent):
        """Create panel to display connected clients"""
        clients_frame = ttk.LabelFrame(parent, text="Connected Clients", padding=5)
        clients_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        clients_frame.columnconfigure(0, weight=1)
        clients_frame.rowconfigure(1, weight=1)

        # Client count
        self.client_count_var = tk.IntVar(value=0)
        ttk.Label(clients_frame, text=f"Connected: {self.client_count_var.get()}/{self.max_connections}").grid(
            row=0, column=0, padx=5, pady=5)

        # Create TreeView for clients
        columns = ("#", "IP Address", "Port", "Username", "Authenticated", "Current Dir", "Last Activity", "Status")
        self.clients_tree = ttk.Treeview(clients_frame, columns=columns, show="headings")

        # Define columns
        self.clients_tree.heading("#", text="#")
        self.clients_tree.heading("IP Address", text="IP Address")
        self.clients_tree.heading("Port", text="Port")
        self.clients_tree.heading("Username", text="Username")
        self.clients_tree.heading("Authenticated", text="Authenticated")
        self.clients_tree.heading("Current Dir", text="Current Dir")
        self.clients_tree.heading("Last Activity", text="Last Activity")
        self.clients_tree.heading("Status", text="Status")

        self.clients_tree.column("#", width=30)
        self.clients_tree.column("IP Address", width=120)
        self.clients_tree.column("Port", width=60)
        self.clients_tree.column("Username", width=100)
        self.clients_tree.column("Authenticated", width=100)
        self.clients_tree.column("Current Dir", width=200)
        self.clients_tree.column("Last Activity", width=120)
        self.clients_tree.column("Status", width=80)

        # Add scrollbar
        scrollbar = ttk.Scrollbar(clients_frame, orient=tk.VERTICAL, command=self.clients_tree.yview)
        self.clients_tree.configure(yscrollcommand=scrollbar.set)

        # Create container for treeview and scrollbar
        tree_frame = ttk.Frame(clients_frame)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.clients_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Context menu for clients
        self.client_context_menu = tk.Menu(clients_frame, tearoff=0)
        self.client_context_menu.add_command(label="Disconnect Client", command=self.disconnect_client)
        self.client_context_menu.add_command(label="View Details", command=self.view_client_details)
        self.clients_tree.bind("<Button-3>", self.show_client_context_menu)

        # Client action buttons
        action_frame = ttk.Frame(clients_frame)
        action_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        ttk.Button(action_frame, text="Disconnect Selected", 
                   command=self.disconnect_client).grid(row=0, column=0, padx=5)
        ttk.Button(action_frame, text="View Details", 
                   command=self.view_client_details).grid(row=0, column=1, padx=5)
        ttk.Button(action_frame, text="Disconnect All", 
                   command=self.disconnect_all_clients).grid(row=0, column=2, padx=5)

    def create_log_panel(self, parent):
        """Create log panel to display server activity"""
        log_frame = ttk.LabelFrame(parent, text="Server Log", padding=5)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        # Log controls
        ttk.Button(log_frame, text="Clear Log", command=self.clear_log).grid(
            row=0, column=0, padx=5, pady=5)
        ttk.Button(log_frame, text="Pause", command=self.toggle_log_pause).grid(
            row=0, column=1, padx=5, pady=5)

        # Log text with scrollbar
        log_content_frame = ttk.Frame(log_frame)
        log_content_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        log_content_frame.columnconfigure(0, weight=1)
        log_content_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_content_frame, height=15, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.config(font=("Consolas", 9))

        # Log scrollbar
        log_scrollbar = ttk.Scrollbar(log_content_frame, orient=tk.VERTICAL, 
                                       command=self.log_text.yview)
        log_scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.config(yscrollcommand=log_scrollbar.set)

        # Log filtering
        self.log_filter_var = tk.StringVar(value="All")
        ttk.Label(log_frame, text="Filter:").grid(row=2, column=0, padx=5, pady=5)
        ttk.Combobox(log_frame, textvariable=self.log_filter_var, 
                     values=["All", "Info", "Warning", "Error"],
                     state="readonly", width=10).grid(
            row=2, column=1, padx=5, pady=5)

    def create_status_bar(self, parent):
        """Create status bar at the bottom"""
        status_frame = ttk.Frame(parent)
        status_frame.grid(row=3, column=0, sticky="ew", padx=5, pady=5)

        # Server status
        self.server_status_var = tk.StringVar(value="Server: Stopped")
        ttk.Label(status_frame, textvariable=self.server_status_var, 
                  foreground="red").pack(side=tk.LEFT, padx=5)

        # Current time
        self.time_var = tk.StringVar()
        ttk.Label(status_frame, textvariable=self.time_var).pack(side=tk.RIGHT, padx=5)

        # Update time
        self.update_time()
    def add_log(self, message, level="info"):
        """Add log entry to the log panel"""

        if not hasattr(self, "root"):
            return

        self.root.after(
            0,
            lambda: self._add_log(message, level)
        )

    def _add_log(self, message, level="info"):
        """Update log widget safely from Tkinter thread"""

        self.log_text.config(state=tk.NORMAL)

        timestamp = datetime.now().strftime("[%H:%M:%S.%f]")

        if level == "info":
            color = "black"
        elif level == "warning":
            color = "orange"
        elif level == "error":
            color = "red"
        else:
            color = "black"

        tag_name = f"log_{level}"

        self.log_text.tag_configure(
            tag_name,
            foreground=color
        )

        self.log_text.insert(
            tk.END,
            f"{timestamp} [{level.upper()}] - {message}\n",
            tag_name
        )

        self.log_text.config(state=tk.DISABLED)
        self.log_text.see(tk.END)
    def clear_log(self):
        """Clear log panel"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)

    def start_server(self):
        """Start FTP server"""
        if self.is_running:
            messagebox.showwarning("Warning", "Server is already running!")
            return

        try:
            self.host = self.host_var.get()
            self.port = int(self.port_var.get())
            self.max_connections = int(self.max_conn_var.get())
            self.session_timeout = int(self.timeout_var.get())
            self.data_dir = self.data_dir_var.get()

            self.server = FTPServer(
                self.host,
                self.port,
                log_callback=self.add_log
            )
            self.add_log(f"Starting server on {self.host}:{self.port}")

            # Start server in background thread
            self.server_thread = threading.Thread(target=self.run_server, daemon=True)
            self.server_thread.start()

            self.is_running = True
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.server_status_var.set("Server: Running")
            self.add_log("Server started successfully", "info")

            # Start automatic client list refresh
            self.auto_refresh_clients()

        except Exception as e:
            self.add_log(f"Failed to start server: {str(e)}", "error")
            messagebox.showerror("Error", f"Failed to start server: {str(e)}")

    def run_server(self):
        """Run server in background thread"""
        try:
            self.server.start()
        except Exception as e:
            self.root.after(
                0,
                self.add_log,
                f"Server error: {e}",
                "error"
            )
        finally:
            self.root.after(0, self.stop_server)

    def stop_server(self):
        """Stop FTP server"""
        if not self.is_running:
            messagebox.showwarning("Warning", "Server is not running!")
            return

        try:
            self.add_log("Stopping server...")
            self.is_running = False
            self.server.stop()
            
            # Update UI
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.server_status_var.set("Server: Stopped")
            
            # Clear clients list
            self.clients_tree.delete(*self.clients_tree.get_children())
            self.client_count_var.set(0)
            
            self.add_log("Server stopped successfully")
        except Exception as e:
            self.add_log(f"Error stopping server: {str(e)}", "error")

    def auto_refresh_clients(self):
        """Automatically refresh client list"""
        if self.is_running:
            self.refresh_clients()
            self.root.after(self.refresh_interval, self.auto_refresh_clients)

    def refresh_clients(self):
        """Refresh connected clients list"""
        if not self.is_running or not self.server:
            return

        try:
            # Get connected clients
            clients = self.server.get_connected_clients()
            self.client_count_var.set(len(clients))

            # Clear existing entries
            for item in self.clients_tree.get_children():
                self.clients_tree.delete(item)

            # Add new entries
            for idx, client in enumerate(clients, 1):
                if isinstance(client, tuple):
                    client_addr, username, authenticated, current_dir, active = client
                    self.clients_tree.insert("", "end", values=(
                        idx,
                        client_addr[0] if client_addr else "N/A",
                        client_addr[1] if client_addr else "N/A",
                        username or "Anonymous",
                        "Yes" if authenticated else "No",
                        current_dir or "N/A",
                        datetime.now().strftime("%H:%M:%S"),
                        "Active" if active else "Inactive"
                    ))
        except Exception as e:
            # Silently handle errors to keep refresh working
            pass

    def show_client_context_menu(self, event):
        """Show context menu for selected client"""
        selection = self.clients_tree.selection()
        if selection:
            self.client_context_menu.tk_popup(event.x_root, event.y_root)

    def disconnect_client(self):
        """Disconnect selected client"""
        selection = self.clients_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No client selected!")
            return

        if messagebox.askyesno("Confirm", "Disconnect this client?"):
            item = self.clients_tree.item(selection[0])
            ip = item["values"][1]
            port = item["values"][2]
            username = item["values"][3]

            self.add_log(f"Disconnecting client {ip}:{port} ({username})")
            # Note: In a real implementation, you'd close the client's socket
            # This is a placeholder for demonstration
            self.refresh_clients()

    def view_client_details(self):
        """View details of selected client"""
        selection = self.clients_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No client selected!")
            return

        item = self.clients_tree.item(selection[0])
        details = f"""Client Details
===============
IP Address: {item["values"][1]}
Port: {item["values"][2]}
Username: {item["values"][3]}
Authenticated: {item["values"][4]}
Current Directory: {item["values"][5]}
Last Activity: {item["values"][6]}
Status: {item["values"][7]}"""

        messagebox.showinfo("Client Details", details)

    def disconnect_all_clients(self):
        """Disconnect all connected clients"""
        if not messagebox.askyesno("Confirm", "Disconnect all clients?"):
            return

        client_count = self.client_count_var.get()
        self.add_log(f"Disconnecting all {client_count} clients")
        self.clients_tree.delete(*self.clients_tree.get_children())
        self.client_count_var.set(0)

    def update_time(self):
        """Update current time in status bar"""
        self.time_var.set(datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self.update_time)

    def toggle_log_pause(self):
        """Toggle log pause (placeholder)"""
        # Implementation would pause/resume log updates
        pass

    def run(self):
        """Run the GUI application"""
        self.create_window()
        self.root.mainloop()


if __name__ == "__main__":
    gui = FTPServerGUI()
    gui.run()