import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path.home() / ".ksdtube_history.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            file_type TEXT,
            title TEXT,
            status TEXT,
            downloaded_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def add_download(file_path, file_type, title, status="Завершено"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR REPLACE INTO downloads (file_path, file_type, title, status, downloaded_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (file_path, file_type, title, status, datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        print(f"DB error: {e}")
    finally:
        conn.close()

def get_all_downloads():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT file_path, file_type, title, status FROM downloads ORDER BY downloaded_at DESC')
    rows = c.fetchall()
    conn.close()
    return rows

def scan_folder_and_sync():
    from config import DOWNLOADS_DIR
    existing = set()
    for row in get_all_downloads():
        existing.add(row[0])
    for file in DOWNLOADS_DIR.iterdir():
        if file.is_file() and file.suffix in ['.mp3', '.mp4']:
            if str(file) not in existing:
                file_type = "MP3" if file.suffix == '.mp3' else "MP4"
                title = file.stem
                add_download(str(file), file_type, title)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for file_path in existing:
        if not Path(file_path).exists():
            c.execute('DELETE FROM downloads WHERE file_path = ?', (file_path,))
    conn.commit()
    conn.close()