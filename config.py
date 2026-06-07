import json
import sys
import shutil
from pathlib import Path

def get_base_path() -> Path:
    """Возвращает путь к папке с ресурсами приложения (работает в .exe и в разработке)."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    else:
        return Path(__file__).parent

DEFAULTS = {
    "download_dir": str(Path.home() / "Downloads" / "KSDtube"),
    "last_url": "",
    "last_format": "mp3",
    "last_quality": "best",
    "theme": "dark",
    "zapret_auto_start": False,
    "zapret_strategy": "general.bat",
    "zapret_last_check": ""
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
}

def get_ffmpeg_path():
    """Возвращает путь к ffmpeg.exe (встроенному или системному)"""
    base = get_base_path()
    candidates = [
        base / 'ffmpeg' / 'bin' / 'ffmpeg.exe',
        base / 'ffmpeg' / 'ffmpeg.exe',
        base / 'ffmpeg.exe',
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    # fallback: ищем в PATH
    return shutil.which('ffmpeg') or 'ffmpeg'

def get_zapret_dir():
    """Возвращает путь к папке zapret"""
    return get_base_path() / 'tools' / 'zapret'