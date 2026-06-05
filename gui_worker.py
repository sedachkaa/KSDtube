import os
import sys
import traceback
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal
import yt_dlp
import requests
from PIL import Image
import io
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, error
from config import BASE_YTDL_OPTS, get_ffmpeg_path

if sys.platform == 'win32':
    CREATE_NO_WINDOW = 0x08000000
else:
    CREATE_NO_WINDOW = 0

class DownloadWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str, str, dict)
    playlist_progress = pyqtSignal(int, int, str)
    error = pyqtSignal(str)

    def __init__(self, url, media_type, quality=None, trim_start=None, trim_end=None, download_dir=None):
        super().__init__()
        self.url = url
        self.media_type = media_type
        self.quality = quality
        self.trim_start = trim_start
        self.trim_end = trim_end
        self.download_dir = download_dir

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            percent_str = d.get('_percent_str', '0%').strip()
            try:
                percent = float(percent_str.replace('%', ''))
            except:
                percent = 0
            speed = d.get('_speed_str', '0 B/s').strip()
            self.progress.emit(int(percent), 0, f"Скачивание: {percent_str} {speed}")
        elif d['status'] == 'finished':
            self.progress.emit(100, 0, "Постобработка...")

    def embed_thumbnail_manually(self, mp3_path, thumbnail_url):
        try:
            resp = requests.get(thumbnail_url, timeout=10)
            img_data = resp.content
            with Image.open(io.BytesIO(img_data)) as img:
                with io.BytesIO() as output:
                    img.save(output, format='PNG')
                    png_data = output.getvalue()
            audio = MP3(mp3_path, ID3=ID3)
            try:
                audio.add_tags()
            except error:
                pass
            audio.tags.add(APIC(
                encoding=3,
                mime='image/png',
                type=3,
                desc='Cover',
                data=png_data
            ))
            audio.save()
            return True
        except Exception as e:
            print(f"Manual thumbnail embed error: {e}")
            return False

    def cleanup_temp_files(self, base_path):
        for ext in ['.webp', '.png', '.jpg', '.jpeg', '.temp.mp3', '.temp.mp4']:
            test_path = base_path + ext
            if os.path.exists(test_path):
                os.remove(test_path)

    def process_single_video(self, entry, index=None, total=None):
        # Получаем URL видео из entry (может быть в 'webpage_url' или 'url')
        video_url = entry.get('webpage_url') or entry.get('url')
        if not video_url:
            self.error.emit(f"Не удалось получить URL для {entry.get('title', 'unknown')}")
            return

        opts = BASE_YTDL_OPTS.copy()
        if self.download_dir:
            opts['outtmpl'] = str(self.download_dir / '%(title)s.%(ext)s')
        else:
            from config import DOWNLOADS_DIR
            opts['outtmpl'] = str(DOWNLOADS_DIR / '%(title)s.%(ext)s')

        if self.media_type == 'mp3':
            opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
                    {'key': 'FFmpegMetadata', 'add_metadata': True},
                ],
                'writethumbnail': True,
                'addmetadata': True,
            })
        else:
            if self.quality == "best":
                fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            else:
                fmt = f'bestvideo[height<={self.quality}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]'
            opts.update({
                'format': fmt,
                'merge_output_format': 'mp4',
            })

        # Указываем путь к ffmpeg
        ffmpeg_path = get_ffmpeg_path()
        opts['ffmpeg_location'] = ffmpeg_path

        opts['progress_hooks'] = [self.progress_hook]
        os.environ['PYTHONIOENCODING'] = 'utf-8'

        with yt_dlp.YoutubeDL(opts) as ydl:
            downloaded_info = ydl.extract_info(video_url, download=True)
            if self.media_type == 'mp3':
                base = ydl.prepare_filename(downloaded_info).rsplit('.', 1)[0]
                mp3_path = base + '.mp3'
                thumbnail_url = downloaded_info.get('thumbnail')
                
                if self.trim_start or self.trim_end:
                    self.progress.emit(95, 0, "Обрезка аудио...")
                    temp_file = mp3_path + ".temp.mp3"
                    cmd = [ffmpeg_path, '-i', mp3_path]
                    if self.trim_start:
                        cmd.extend(['-ss', self.trim_start])
                    if self.trim_end:
                        cmd.extend(['-to', self.trim_end])
                    cmd.extend(['-c', 'copy', temp_file])
                    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   encoding='utf-8', errors='replace',
                                   creationflags=CREATE_NO_WINDOW)
                    os.replace(temp_file, mp3_path)
                
                if thumbnail_url:
                    self.progress.emit(98, 0, "Встраивание обложки...")
                    self.embed_thumbnail_manually(mp3_path, thumbnail_url)
                else:
                    self.progress.emit(98, 0, "Обложка не найдена")
                
                self.cleanup_temp_files(base)
                self.finished.emit(mp3_path, self.media_type, downloaded_info)
            else:
                video_path = ydl.prepare_filename(downloaded_info)
                if not video_path.endswith('.mp4'):
                    video_path = video_path.rsplit('.', 1)[0] + '.mp4'
                if self.trim_start or self.trim_end:
                    self.progress.emit(95, 0, "Обрезка видео...")
                    temp_file = video_path + ".temp.mp4"
                    cmd = [ffmpeg_path, '-i', video_path]
                    if self.trim_start:
                        cmd.extend(['-ss', self.trim_start])
                    if self.trim_end:
                        cmd.extend(['-to', self.trim_end])
                    cmd.extend(['-c', 'copy', temp_file])
                    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   encoding='utf-8', errors='replace',
                                   creationflags=CREATE_NO_WINDOW)
                    os.replace(temp_file, video_path)
                self.finished.emit(video_path, self.media_type, downloaded_info)
            base = ydl.prepare_filename(downloaded_info).rsplit('.', 1)[0]
            self.cleanup_temp_files(base)

    def run(self):
        try:
            # Сначала определяем, является ли ссылка плейлистом
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': 'in_playlist',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                }
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if 'entries' in info and info['entries']:
                    entries = info['entries']
                    total = len(entries)
                    self.playlist_progress.emit(0, total, f"Плейлист: 0/{total}")
                    for idx, entry in enumerate(entries):
                        if entry is None:
                            continue
                        self.playlist_progress.emit(idx, total, f"Обработка {idx+1}/{total}: {entry.get('title', '')}")
                        self.process_single_video(entry, idx, total)
                    self.progress.emit(0, 0, "Плейлист полностью загружен")
                else:
                    # Обычное видео
                    self.process_single_video({'webpage_url': self.url})
        except Exception as e:
            traceback.print_exc()
            self.error.emit(str(e))