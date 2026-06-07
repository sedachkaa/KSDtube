import os
import shutil
import tempfile
import zipfile
from pathlib import Path
import requests
from PyQt6.QtCore import QThread, pyqtSignal
from datetime import datetime
from config import settings, save_settings, get_zapret_dir

class ZapretUpdater(QThread):
    status_update = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    GITHUB_REPO = "Flowseal/zapret-discord-youtube"
    LISTS_DIR = "lists"

    def __init__(self):
        super().__init__()
        self.zapret_path = get_zapret_dir()

    def get_current_version(self):
        service_file = self.zapret_path / "service.bat"
        if not service_file.exists():
            return None
        try:
            with open(service_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if 'set "LOCAL_VERSION=' in line:
                        return line.split('=')[1].strip('"\n\r ')
        except:
            return None

    def get_latest_version(self):
        url = f"https://raw.githubusercontent.com/{self.GITHUB_REPO}/main/.service/version.txt"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            return r.text.strip()
        except:
            return None

    def download_and_install(self, version):
        download_url = f"https://github.com/{self.GITHUB_REPO}/archive/refs/tags/{version}.zip"
        try:
            r = requests.get(download_url, stream=True, timeout=30)
            r.raise_for_status()
            temp_dir = tempfile.TemporaryDirectory()
            zip_path = Path(temp_dir.name) / "update.zip"
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            backup_dir = Path(temp_dir.name) / "backup"
            backup_dir.mkdir()
            lists_dir = self.zapret_path / self.LISTS_DIR
            if lists_dir.exists():
                shutil.copytree(lists_dir, backup_dir / self.LISTS_DIR)
            for bat_file in self.zapret_path.glob("general*.bat"):
                shutil.copy2(bat_file, backup_dir / bat_file.name)
            extract_dir = Path(temp_dir.name) / "extracted"
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_dir)
            source_dir = None
            for item in extract_dir.iterdir():
                if item.is_dir() and item.name.startswith("zapret-discord-youtube-"):
                    source_dir = item
                    break
            if not source_dir:
                raise Exception("Source dir not found")
            if self.zapret_path.exists():
                shutil.rmtree(self.zapret_path)
            shutil.copytree(source_dir, self.zapret_path)
            if (backup_dir / self.LISTS_DIR).exists():
                target = self.zapret_path / self.LISTS_DIR
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(backup_dir / self.LISTS_DIR, target)
            for saved_bat in backup_dir.glob("general*.bat"):
                shutil.copy2(saved_bat, self.zapret_path / saved_bat.name)
            return True
        except Exception as e:
            return False

    def run(self):
        last_check = settings.get("zapret_last_check", "")
        today = datetime.now().strftime("%Y-%m-%d")
        if last_check == today:
            self.finished_signal.emit(False, "")
            return
        current = self.get_current_version()
        if not current:
            settings["zapret_last_check"] = today
            save_settings(settings)
            self.finished_signal.emit(False, "")
            return
        latest = self.get_latest_version()
        if not latest or latest == current:
            settings["zapret_last_check"] = today
            save_settings(settings)
            self.finished_signal.emit(False, "")
            return
        success = self.download_and_install(latest)
        if success:
            self.status_update.emit(f"Zapret обновлён до {latest}")
            self.finished_signal.emit(True, f"Обновлён до {latest}")
        else:
            self.finished_signal.emit(False, "Ошибка обновления")
        settings["zapret_last_check"] = today
        save_settings(settings)