import os
import subprocess
import requests
import shutil
from pathlib import Path
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from config import get_base_path

TG_PROXY_REPO = "Flowseal/tg-ws-proxy"
TG_PROXY_EXE_NAME = "TgWsProxy_windows.exe"
TG_PROXY_DIR = get_base_path() / "tools" / "tg-proxy"
TG_PROXY_EXE = TG_PROXY_DIR / TG_PROXY_EXE_NAME
VERSION_FILE = TG_PROXY_DIR / "version.txt"

class TgProxyManager(QObject):
    status_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        TG_PROXY_DIR.mkdir(parents=True, exist_ok=True)
        self.process = None

    def is_running(self):
        try:
            result = subprocess.run(
                ['tasklist', '/FI', f'IMAGENAME eq {TG_PROXY_EXE_NAME}'],
                capture_output=True, text=True, creationflags=0x08000000
            )
            return TG_PROXY_EXE_NAME in result.stdout
        except:
            return False

    def start(self):
        if not TG_PROXY_EXE.exists():
            return False, "Файл не найден. Сначала скачайте."
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            self.process = subprocess.Popen(
                [str(TG_PROXY_EXE)],
                startupinfo=startupinfo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            return True, "Запущен"
        except Exception as e:
            return False, str(e)

    def stop(self):
        try:
            subprocess.run(['taskkill', '/f', '/im', TG_PROXY_EXE_NAME], capture_output=True)
            return True, "Остановлен"
        except Exception as e:
            return False, str(e)

class TgProxyUpdater(QThread):
    progress = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def get_latest_version(self):
        url = f"https://api.github.com/repos/{TG_PROXY_REPO}/releases/latest"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()['tag_name']
        except:
            return None

    def get_current_version(self):
        if VERSION_FILE.exists():
            try:
                with open(VERSION_FILE, 'r') as f:
                    return f.read().strip()
            except:
                pass
        return None

    def download_and_install(self, version):
        download_url = f"https://github.com/{TG_PROXY_REPO}/releases/download/{version}/{TG_PROXY_EXE_NAME}"
        try:
            resp = requests.get(download_url, stream=True, timeout=30)
            resp.raise_for_status()
            temp_file = TG_PROXY_DIR / f"{TG_PROXY_EXE_NAME}.download"
            with open(temp_file, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            if TG_PROXY_EXE.exists():
                TG_PROXY_EXE.unlink()
            shutil.move(str(temp_file), str(TG_PROXY_EXE))
            with open(VERSION_FILE, 'w') as f:
                f.write(version)
            return True
        except Exception as e:
            return False

    def run(self):
        latest = self.get_latest_version()
        if not latest:
            self.finished_signal.emit(False, "")
            return
        current = self.get_current_version()
        if current == latest:
            self.finished_signal.emit(False, "")
            return
        self.progress.emit(f"Загрузка версии {latest}...")
        success = self.download_and_install(latest)
        if success:
            self.finished_signal.emit(True, f"Обновлён до {latest}")
        else:
            self.finished_signal.emit(False, "Ошибка скачивания")