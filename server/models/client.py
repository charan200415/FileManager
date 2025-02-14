from datetime import datetime
from typing import Tuple, Dict, Optional

class ClientData:
    def __init__(self, address: Tuple[str, int]):
        self.address = address
        self.files: Dict = {}
        self.last_update = datetime.now()
        self.current_path = "."
        self.last_file_data: Optional[bytes] = None 