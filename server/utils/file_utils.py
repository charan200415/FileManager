import os
import string
import ctypes

def format_file_size(size):
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size/1024:.1f} KB"
    else:
        return f"{size/(1024*1024):.1f} MB"

def get_file_icon(filename):
    if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
        return '<i class="fas fa-image"></i>', 'image'
    elif filename.lower().endswith(('.mp4', '.avi', '.mov')):
        return '<i class="fas fa-video"></i>', 'video'
    elif filename.lower().endswith(('.mp3', '.wav')):
        return '<i class="fas fa-music"></i>', 'audio'
    elif filename.lower().endswith('.pdf'):
        return '<i class="fas fa-file-pdf"></i>', 'pdf'
    elif filename.lower().endswith(('.doc', '.docx')):
        return '<i class="fas fa-file-word"></i>', 'doc'
    elif filename.lower().endswith(('.zip', '.rar', '.7z')):
        return '<i class="fas fa-file-archive"></i>', 'archive'
    else:
        return '<i class="fas fa-file"></i>', 'file'

def get_drives():
    """Get list of Windows drives"""
    drives = []
    if os.name == 'nt':  # Windows
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drive = f"{letter}:\\"
                try:
                    label = get_drive_label(drive)
                    total, used, free = get_drive_space(drive)
                    drives.append({
                        'path': drive,
                        'label': label or f"Local Disk ({drive})",
                        'total': total,
                        'used': used,
                        'free': free
                    })
                except:
                    pass
            bitmask >>= 1
    else:  # Linux/Mac
        drives.append({
            'path': '/',
            'label': 'Root',
            'total': 0,
            'used': 0,
            'free': 0
        })
    return drives

def get_drive_label(drive):
    """Get drive label on Windows"""
    if os.name == 'nt':
        kernel32 = ctypes.windll.kernel32
        volumeNameBuffer = ctypes.create_unicode_buffer(1024)
        fileSystemNameBuffer = ctypes.create_unicode_buffer(1024)
        serial_number = None
        max_component_length = None
        file_system_flags = None

        rc = kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive),
            volumeNameBuffer,
            ctypes.sizeof(volumeNameBuffer),
            serial_number,
            max_component_length,
            file_system_flags,
            fileSystemNameBuffer,
            ctypes.sizeof(fileSystemNameBuffer)
        )
        if rc:
            return volumeNameBuffer.value
    return None

def get_drive_space(drive):
    """Get drive space information"""
    total, used, free = 0, 0, 0
    try:
        st = os.statvfs(drive) if os.name != 'nt' else None
        if os.name == 'nt':
            free_bytes = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(drive),
                None,
                ctypes.pointer(total_bytes),
                ctypes.pointer(free_bytes)
            )
            total = total_bytes.value
            free = free_bytes.value
            used = total - free
        else:
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = (st.f_blocks - st.f_bfree) * st.f_frsize
    except:
        pass
    return total, used, free

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB" 