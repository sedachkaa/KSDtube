import os
import sys
import subprocess
import threading
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from config import get_zapret_dir

if sys.platform == 'win32':
    CREATE_NO_WINDOW = 0x08000000
else:
    CREATE_NO_WINDOW = 0

class ZapretManager(QObject):
    log_output = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.zapret_dir = get_zapret_dir()
        self.service_process = None

    def is_active(self):
        try:
            result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq windivert64.exe'],
                                    capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            if "windivert64.exe" in result.stdout:
                return True
            result = subprocess.run(['sc', 'query', 'WinDivert'],
                                    capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            return "RUNNING" in result.stdout
        except:
            return False

    def run_service_bat(self, output_callback=None, finished_callback=None):
        service_bat = self.zapret_dir / "service.bat"
        if not service_bat.exists():
            return False, "service.bat не найден"
        try:
            self.service_process = subprocess.Popen(
                ['cmd.exe', '/c', str(service_bat)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='cp866',
                errors='replace',
                creationflags=CREATE_NO_WINDOW
            )
            if output_callback:
                def read_output():
                    for line in self.service_process.stdout:
                        output_callback(line.rstrip())
                    for line in self.service_process.stderr:
                        output_callback(line.rstrip())
                threading.Thread(target=read_output, daemon=True).start()
            if finished_callback:
                def wait():
                    self.service_process.wait()
                    finished_callback()
                threading.Thread(target=wait, daemon=True).start()
            return True, "Запущен"
        except Exception as e:
            return False, str(e)