import sqlite3
from pathlib import Path
from datetime import datetime
import shutil
import random

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
    c.execute('''
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            folder_path TEXT,
            avatar_path TEXT,
            color TEXT,
            created_at TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS playlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            file_path TEXT,
            downloaded INTEGER DEFAULT 0,
            added_at TIMESTAMP,
            FOREIGN KEY(playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
        )
    ''')
    # Добавляем столбцы, если их нет (миграция)
    try:
        c.execute('ALTER TABLE playlists ADD COLUMN avatar_path TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        c.execute('ALTER TABLE playlists ADD COLUMN color TEXT')
    except sqlite3.OperationalError:
        pass
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

def create_playlist(name, type_, folder_path, avatar_path=None, color=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if color is None:
        color = "#{:02x}{:02x}{:02x}".format(
            random.randint(100, 255),
            random.randint(100, 255),
            random.randint(100, 255)
        )
    c.execute('INSERT INTO playlists (name, type, folder_path, avatar_path, color, created_at) VALUES (?, ?, ?, ?, ?, ?)',
              (name, type_, folder_path, avatar_path, color, datetime.now().isoformat()))
    conn.commit()
    playlist_id = c.lastrowid
    conn.close()
    return playlist_id

def get_playlists(type_=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if type_:
        c.execute('SELECT id, name, type, folder_path, avatar_path, color, created_at FROM playlists WHERE type = ? ORDER BY name', (type_,))
    else:
        c.execute('SELECT id, name, type, folder_path, avatar_path, color, created_at FROM playlists ORDER BY type, name')
    rows = c.fetchall()
    conn.close()
    return rows

def delete_playlist(playlist_id, folder_path=None):
    if folder_path and Path(folder_path).exists():
        shutil.rmtree(folder_path, ignore_errors=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM playlists WHERE id = ?', (playlist_id,))
    conn.commit()
    conn.close()

def add_to_playlist(playlist_id, title, url, file_path):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    downloaded = 1 if file_path and Path(file_path).exists() else 0
    c.execute('''
        INSERT INTO playlist_items (playlist_id, title, url, file_path, downloaded, added_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (playlist_id, title, url, file_path, downloaded, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_playlist_items(playlist_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, title, url, file_path, downloaded, added_at FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def remove_from_playlist(item_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM playlist_items WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()

def update_playlist_item_file(item_id, file_path):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    downloaded = 1 if file_path and Path(file_path).exists() else 0
    c.execute('UPDATE playlist_items SET file_path = ?, downloaded = ? WHERE id = ?', (file_path, downloaded, item_id))
    conn.commit()
    conn.close()

def update_playlist_avatar(playlist_id, avatar_path):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE playlists SET avatar_path = ? WHERE id = ?', (avatar_path, playlist_id))
    conn.commit()
    conn.close()

def sync_playlist_with_folder(playlist_id, folder_path):
    """Обновляет содержимое плейлиста по файлам в папке"""
    folder = Path(folder_path)
    if not folder.exists():
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, file_path FROM playlist_items WHERE playlist_id = ?', (playlist_id,))
    existing = {row[1]: row[0] for row in c.fetchall()}
    # Сканируем папку
    current_files = [f for f in folder.iterdir() if f.suffix.lower() in ('.mp3', '.mp4')]
    for file in current_files:
        file_path_str = str(file)
        title = file.stem
        if file_path_str not in existing:
            c.execute('''
                INSERT INTO playlist_items (playlist_id, title, url, file_path, downloaded, added_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (playlist_id, title, "", file_path_str, 1, datetime.now().isoformat()))
        else:
            c.execute('UPDATE playlist_items SET downloaded = 1 WHERE id = ?', (existing[file_path_str],))
    # Удаляем записи, файлы которых пропали
    for file_path_str, item_id in existing.items():
        if not Path(file_path_str).exists():
            c.execute('DELETE FROM playlist_items WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()