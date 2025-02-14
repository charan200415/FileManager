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
from .handlers.file_manager import FileManagerHandler
from .models.client import ClientData
from .combined_server import CombinedServer

def handle_tcp_client(server, client_socket, address):
    """Handle TCP client connections"""
    print(f"[+] Starting TCP handler for {address[0]}:{address[1]}")
    try:
        # Wait for CLIENT_HELLO
        print(f"[*] Waiting for CLIENT_HELLO from {address[0]}")
        data = client_socket.recv(1024*1024).decode('utf-8')
        if not data:
            print(f"[-] Client {address[0]} disconnected before hello")
            return
            
        # Split the received data by newlines
        messages = data.split('\n')
        if not messages or messages[0].strip() != "CLIENT_HELLO":
            print(f"[!] Invalid client hello from {address[0]}: {messages[0] if messages else 'empty'}")
            return
            
        print(f"[+] Valid CLIENT_HELLO received from {address[0]}")
        
        # Process the initial drive list if it was sent along with CLIENT_HELLO
        if len(messages) > 1 and messages[1].strip():
            try:
                initial_data = messages[1].strip()
                print(f"[*] Processing initial drive list from {address[0]}")
                client_data = ClientData(address)
                client_data.files = json.loads(initial_data)
                client_data.last_update = datetime.now()
                server.clients[address[0]] = client_data
                server.client_sockets[address[0]] = client_socket
                print(f"[+] Successfully processed initial drive list from {address[0]}")
            except json.JSONDecodeError as e:
                print(f"[!] Invalid JSON in initial data from {address[0]}: {e}")
                return
            except Exception as e:
                print(f"[!] Error processing initial data from {address[0]}: {e}")
                return
        else:
            # Initialize client data
            client_data = ClientData(address)
            server.clients[address[0]] = client_data
            server.client_sockets[address[0]] = client_socket
        
        # Set socket timeout
        client_socket.settimeout(None)  # No timeout for main connection
        
        # Request initial directory listing if we didn't get it already
        if not client_data.files:
            print(f"[+] Requesting initial directory listing from {address[0]}")
            client_socket.send("PATH:.\n".encode('utf-8'))
        
        while True:
            try:
                print(f"[*] Waiting for data from {address[0]}")
                data = client_socket.recv(1024*1024).decode('utf-8')
                if not data:
                    print(f"[-] Client {address[0]} disconnected (empty data)")
                    break
                
                print(f"[+] Received {len(data)} bytes from {address[0]}")
                
                # Try to parse JSON data
                try:
                    client_data.files = json.loads(data)
                    client_data.last_update = datetime.now()
                    print(f"[+] Successfully updated file list from {address[0]}")
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
        print(f"[-] Cleaning up connection for {address[0]}:{address[1]}")
        server.remove_client(address[0])

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