import os
import html
from datetime import datetime
from urllib.parse import unquote
import time
import aiohttp
import asyncio
from pathlib import Path

from ..utils.file_utils import format_file_size, get_file_icon, get_drives, format_size

# Define STORAGE_DIR
STORAGE_DIR = "server_storage"
if not os.path.exists(STORAGE_DIR):
    os.makedirs(STORAGE_DIR)

class FileManagerHandler:
    def __init__(self):
        self.app = None  # Will be set by the server

    def load_template(self, template_name):
        template_path = os.path.join('templates', template_name)
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()

    def render_template(self, template_name, **kwargs):
        template = self.load_template(template_name)
        # Replace CSS curly braces with double curly braces before formatting
        template = template.replace('{', '{{').replace('}', '}}')
        # Restore single curly braces for our template variables
        for key in kwargs:
            template = template.replace(f'{{{{{key}}}}}', f'{{{key}}}')
        return template.format(**kwargs)

    async def get_saved_files(self):
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

    async def generate_directory_listing(self, client_data, current_path):
        # Generate drives menu
        drives = get_drives()
        drives_menu = ""
        for drive in drives:
            used_percent = (drive['used'] / drive['total'] * 100) if drive['total'] > 0 else 0
            path = drive['path'].replace('\\', '/')  # Convert backslashes to forward slashes
            drives_menu += f"""
                <a href="/?path={path}" class="drive-item">
                    <div class="drive-name">
                        <i class="fas fa-hdd"></i> {drive['label']}
                    </div>
                    <div class="drive-info">
                        {format_size(drive['used'])} of {format_size(drive['total'])}
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: {used_percent}%"></div>
                    </div>
                </a>
            """

        # Get items in current directory
        current_items = {}
        
        if current_path == '.':
            # For root directory, show drives
            for path, info in client_data.files.items():
                if ':' in path and '/' not in path and '\\' not in path:
                    current_items[path] = info
        else:
            # For specific directory, show its contents
            for path, info in client_data.files.items():
                current_items[path] = info

        # Sort items (directories first)
        sorted_items = sorted(
            current_items.items(),
            key=lambda x: (not x[1]['is_dir'], x[0].lower())
        )

        # Generate breadcrumb navigation
        breadcrumb_html = '<a href="/?path=.">Home</a>'
        if current_path != '.':
            parts = current_path.split('/')
            current = ''
            for part in parts:
                if part:
                    current = f"{current}/{part}".lstrip('/')
                    breadcrumb_html += f' / <a href="/?path={current}">{part}</a>'

        # Generate file list HTML
        file_list_html = ""
        
        # Add parent directory link if not in root
        if current_path != '.':
            parent_path = os.path.dirname(current_path.replace('\\', '/')) or '.'
            file_list_html += self.render_template('file_entry.html', 
                entry_name=f'<a href="/?path={parent_path}" class="file-name">..</a>',
                icon='<i class="fas fa-level-up-alt"></i>',
                file_type='folder',
                size="-",
                modified_time="-",
                download_link="",
                action_buttons=""
            )

        # Add files and directories
        for name, info in sorted_items:
            if info['is_dir']:
                size_str = "-"
                link_path = info.get('full_path', f"{current_path}/{name}").replace('\\', '/')
                icon = '<i class="fas fa-folder"></i>'
                file_type = 'folder'
                entry_name = f'<a href="/?path={link_path}" class="file-name">{html.escape(name)}</a>'
                download_link = ""
                action_buttons = ""
                checkbox = '''
                    <div class="checkbox" style="visibility: hidden;">
                        <i class="fas fa-check" style="display: none;"></i>
                    </div>
                '''.strip()
            else:
                size = info.get('size', 0)  # Get size with default 0
                size_str = format_file_size(size)
                icon, file_type = get_file_icon(name)
                entry_name = f'<span class="file-name">{html.escape(name)}</span>'
                full_path = info.get('full_path', f"{current_path}/{name}").replace('\\', '/')
                
                # Add checkbox with size data
                checkbox = f'''
                    <div class="checkbox" onclick="toggleSelect(this, '{full_path}', {size})" data-size="{size}">
                        <i class="fas fa-check" style="display: none;"></i>
                    </div>
                '''.strip()
                
                # Add download and save buttons
                if size > 100 * 1024 * 1024:  # 100MB
                    action_buttons = f'''
                        <a href="#" onclick="confirmLargeDownload('{full_path}', {size})" class="action-button" title="Download">
                            <i class="fas fa-download"></i>
                        </a>
                        <a href="#" onclick="saveFile('{full_path}')" class="action-button" title="Save to Server">
                            <i class="fas fa-save"></i>
                        </a>'''
                else:
                    action_buttons = f'''
                        <a href="/download?path={full_path}" class="action-button" title="Download">
                            <i class="fas fa-download"></i>
                        </a>
                        <a href="#" onclick="saveFile('{full_path}')" class="action-button" title="Save to Server">
                            <i class="fas fa-save"></i>
                        </a>'''

            mod_time = datetime.fromtimestamp(info['mtime']).strftime('%b %d, %Y')
            
            file_list_html += self.render_template('file_entry.html',
                entry_name=entry_name,
                icon=icon,
                file_type=file_type,
                size=size_str,
                modified_time=mod_time,
                download_link="",
                action_buttons=action_buttons,
                save_button="",
                checkbox=checkbox
            )

        # Set active states for menu items
        active_all = "" if current_path == "saved" else "active"
        active_saved = "active" if current_path == "saved" else ""

        # If viewing saved files
        if current_path == 'saved':
            try:
                saved_files = await self.get_saved_files()
                
                file_list_html = ""
                for file in saved_files:
                    size_str = format_file_size(file['size'])
                    icon, file_type = get_file_icon(file['name'])
                    mod_time = datetime.fromtimestamp(file['mtime']).strftime('%b %d, %Y')
                    
                    checkbox = f'''
                        <div class="checkbox" onclick="toggleSelect(this, '{file["path"]}', {file["size"]})">
                            <i class="fas fa-check" style="display: none;"></i>
                        </div>
                    '''.strip()
                    
                    file_list_html += self.render_template('file_entry.html',
                        entry_name=f'<span class="file-name">{html.escape(file["name"])}</span>',
                        icon=icon,
                        file_type=file_type,
                        size=size_str,
                        modified_time=mod_time,
                        download_link="",
                        action_buttons=f'<a href="{file["path"]}" class="action-button" title="Download"><i class="fas fa-download"></i></a>',
                        save_button="",
                        checkbox=checkbox
                    )
                
                # Render directory template for saved files
                directory_html = self.render_template('directory.html',
                    display_path="Saved Files",
                    client_ip=client_data.address[0],
                    client_port=client_data.address[1],
                    breadcrumb_html='<a href="/">Home</a> / Saved Files',
                    file_list=file_list_html
                )
                
                # Render layout with saved files view
                return self.render_template('layout.html',
                    current_path=current_path,
                    content=directory_html,
                    drives_menu=drives_menu,
                    active_all=active_all,
                    active_saved=active_saved
                )

            except Exception as e:
                print(f"Error generating saved files listing: {e}")
                return "Error loading saved files"

        # Render directory template
        directory_html = self.render_template('directory.html',
            client_ip=client_data.address[0],
            client_port=client_data.address[1],
            last_update=client_data.last_update.strftime('%Y-%m-%d %H:%M:%S'),
            display_path=current_path if current_path != '.' else 'Root Directory',
            breadcrumb_html=breadcrumb_html,
            file_list=file_list_html
        )

        # Update final layout render to include active states
        return self.render_template('layout.html',
            current_path=current_path,
            content=directory_html,
            drives_menu=drives_menu,
            active_all=active_all,
            active_saved=active_saved
        ) 