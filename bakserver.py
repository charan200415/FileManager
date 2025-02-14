import socket
import threading
import sys
import os
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, unquote
import html
import json
import time
import os.path
from server.handlers.file_manager import FileManagerHandler
from server.models.client import ClientData
from server.combined_server import CombinedServer

class ClientData:
    def __init__(self, address):
        self.address = address
        self.files = {}
        self.last_update = datetime.now()
        self.current_path = "."  # Track current path

class FileManagerHandler(SimpleHTTPRequestHandler):
    def load_template(self, template_name):
        template_path = os.path.join('templates', template_name)
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()

    def render_template(self, template_name, **kwargs):
        template = self.load_template(template_name)
        return template.format(**kwargs)

    def do_GET(self):
        try:
            # Get client data from server
            client_data = self.server.clients.get(self.client_address[0])
            if not client_data:
                self.send_error(404, "No client connected from this IP")
                return

            # Parse the requested path
            parsed_path = unquote(self.path).strip('/')
            if not parsed_path:
                parsed_path = '.'

            # Request fresh directory contents from client only on actual navigation
            client_socket = self.server.tcp_server.client_sockets.get(self.client_address[0])
            if client_socket and (
                parsed_path != client_data.current_path or 
                'refresh=true' in self.path
            ):
                client_socket.send(f"PATH:{parsed_path}".encode('utf-8'))
                # Wait for response
                time.sleep(0.5)
                client_data.current_path = parsed_path

            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            # Generate HTML content
            html_content = self.generate_directory_listing(client_data, parsed_path)
            self.wfile.write(html_content.encode('utf-8'))
                
        except Exception as e:
            print(f"[!] Error handling request: {e}")
            self.send_error(500, str(e))

    def generate_directory_listing(self, client_data, current_path):
        # Get items in current directory
        current_items = {}
        
        # Debug print
        print(f"\nProcessing directory: {current_path}")
        print(f"All files: {client_data.files}")
        
        for path, info in client_data.files.items():
            try:
                # For root directory
                if current_path == '.':
                    if '/' not in path:
                        current_items[path] = info
                # For subdirectories
                else:
                    # Remove leading/trailing slashes and normalize path
                    norm_current = current_path.strip('/')
                    norm_path = path.strip('/')
                    
                    # Only include direct children of current directory
                    if norm_path.startswith(norm_current + '/'):
                        child_path = norm_path[len(norm_current)+1:]
                        if '/' not in child_path:  # Direct child
                            current_items[child_path] = info
                        
            except Exception as e:
                print(f"Error processing path {path}: {e}")
                continue

        # Debug print
        print(f"Current path: {current_path}")
        print(f"Available files: {list(client_data.files.keys())}")
        print(f"Filtered items: {list(current_items.keys())}")

        # Sort items (directories first)
        sorted_items = sorted(
            current_items.items(),
            key=lambda x: (not x[1]['is_dir'], x[0].lower())
        )

        # Fix the breadcrumb navigation
        breadcrumb_html = '<a href="/">Home</a>'
        if current_path != '.':
            parts = current_path.split('/')
            current = ''
            for part in parts:
                current = f"{current}/{part}".lstrip('/')
                breadcrumb_html += f' / <a href="/{current}">{part}</a>'

        # Generate file list HTML
        file_list_html = ""
        
        # Add parent directory link if not in root
        if current_path != '.':
            parent_path = os.path.dirname(current_path) or ''
            file_list_html += self.render_template('file_entry.html', 
                entry_name=f'<a href="/{parent_path}" class="file-name">..</a>',
                icon='<i class="fas fa-level-up-alt"></i>',
                file_type='folder',
                size="-",
                modified_time="-"
            )

        # Add files and directories
        for name, info in sorted_items:
            is_dir = info['is_dir']
            
            if is_dir:
                size_str = "-"
                link_path = f"{current_path}/{name}".lstrip('/')
                icon = '<i class="fas fa-folder"></i>'
                file_type = 'folder'
                entry_name = f'<a href="/{link_path}" class="file-name">{html.escape(name)}</a>'
            else:
                size = info['size']
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size/1024:.1f} KB"
                else:
                    size_str = f"{size/(1024*1024):.1f} MB"
                
                # Choose icon and type based on file extension
                if name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                    icon = '<i class="fas fa-image"></i>'
                    file_type = 'image'
                elif name.lower().endswith(('.mp4', '.avi', '.mov')):
                    icon = '<i class="fas fa-video"></i>'
                    file_type = 'video'
                elif name.lower().endswith(('.mp3', '.wav')):
                    icon = '<i class="fas fa-music"></i>'
                    file_type = 'audio'
                elif name.lower().endswith('.pdf'):
                    icon = '<i class="fas fa-file-pdf"></i>'
                    file_type = 'pdf'
                elif name.lower().endswith(('.doc', '.docx')):
                    icon = '<i class="fas fa-file-word"></i>'
                    file_type = 'doc'
                elif name.lower().endswith(('.zip', '.rar', '.7z')):
                    icon = '<i class="fas fa-file-archive"></i>'
                    file_type = 'archive'
                else:
                    icon = '<i class="fas fa-file"></i>'
                    file_type = 'file'
                
                entry_name = f'<span class="file-name">{html.escape(name)}</span>'

            mod_time = datetime.fromtimestamp(info['mtime']).strftime('%b %d, %Y')
            
            file_list_html += self.render_template('file_entry.html',
                entry_name=entry_name,
                icon=icon,
                file_type=file_type,
                size=size_str,
                modified_time=mod_time
            )

        # Render directory template
        directory_html = self.render_template('directory.html',
            client_ip=client_data.address[0],
            client_port=client_data.address[1],
            last_update=client_data.last_update.strftime('%Y-%m-%d %H:%M:%S'),
            display_path=current_path if current_path != '.' else 'Root Directory',
            breadcrumb_html=breadcrumb_html,
            file_list=file_list_html
        )

        # Render layout template
        return self.render_template('layout.html',
            current_path=current_path,
            content=directory_html
        )

def handle_tcp_client(server, client_socket, address):
    """Handle TCP client connections"""
    try:
        # Initialize client data
        client_data = ClientData(address)
        server.clients[address[0]] = client_data
        server.client_sockets[address[0]] = client_socket
        
        # Set socket timeout
        client_socket.settimeout(None)  # No timeout for main connection
        
        # Request initial directory listing
        client_socket.send("PATH:.\n".encode('utf-8'))
        
        while True:
            try:
                data = client_socket.recv(1024*1024).decode('utf-8')
                if not data:
                    print(f"[-] Client {address[0]} disconnected")
                    break
                
                # Try to parse JSON data
                try:
                    client_data.files = json.loads(data)
                    client_data.last_update = datetime.now()
                except json.JSONDecodeError as e:
                    print(f"[!] Invalid JSON from {address[0]}: {e}")
                    continue
                
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[!] Error receiving data from {address[0]}: {e}")
                break
                
    except Exception as e:
        print(f"[!] Error handling client {address[0]}:{address[1]}: {e}")
    finally:
        server.remove_client(address[0])
        print(f"[-] Connection closed for {address[0]}:{address[1]}")

def create_server(host='0.0.0.0', port=8080):
    """Create and return the combined server instance"""
    server = CombinedServer(
        (host, port),
        FileManagerHandler,
        handle_tcp_client
    )
    
    # Store TCP server reference in the handler
    FileManagerHandler.tcp_server = server
    
    return server

def run_server(host='0.0.0.0', port=8080):
    """Run the combined server"""
    server = create_server(host, port)
    print(f"[+] Server started on {host}:{port}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down server...")
    finally:
        server.server_close()

if __name__ == "__main__":
    try:
        run_server()
    except KeyboardInterrupt:
        print("\n[!] Server shutting down...")
        sys.exit(0) 