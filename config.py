import json
import sys
import shutil
from pathlib import Path

DEFAULTS = {
    "download_dir": str(Path.home() / "Downloads" / "KSDtube"),
    "last_url": "",
    "last_format": "mp3",
    "last_quality": "best",
    "theme": "dark",
    "zapret_auto_start": False,
    "zapret_strategy": "general.bat"
}

SETTINGS_FILE = Path.home() / ".ksdtube_settings.json"

def load_settings():
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return {**DEFAULTS, **json.load(f)}
    return DEFAULTS.copy()

def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4)

settings = load_settings()
DOWNLOADS_DIR = Path(settings["download_dir"])
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

BASE_YTDL_OPTS = {
    'outtmpl': str(DOWNLOADS_DIR / '%(title)s.%(ext)s'),
    'progress_hooks': [],
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    },
    'extractor_args': {
        'youtube': {
            'skip': ['hls', 'dash'],
        }
    },
    'quiet': True,
    'no_warnings': True,
    # Ускорение скачивания
    'concurrent_fragment_downloads': 5,
    'throttledratelimit': 100000000,  # 100 MB/s
    'retries': 10,
    'fragment_retries': 10,
}

def get_ffmpeg_path():
    """Возвращает путь к ffmpeg.exe (встроенному или системному)"""
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
        candidates = [
            base / 'ffmpeg' / 'bin' / 'ffmpeg.exe',
            base / 'ffmpeg' / 'ffmpeg.exe',
            base / 'ffmpeg.exe',
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
    local_ffmpeg = Path(__file__).parent / 'ffmpeg' / 'bin' / 'ffmpeg.exe'
    if local_ffmpeg.exists():
        return str(local_ffmpeg)
    return shutil.which('ffmpeg') or 'ffmpeg'

def get_zapret_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'tools' / 'zapret'
    else:
        return Path(__file__).parent / 'tools' / 'zapret'