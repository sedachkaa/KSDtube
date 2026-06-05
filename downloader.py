import yt_dlp
from config import BASE_YTDL_OPTS, DOWNLOADS_DIR

def download_audio(url: str, progress_hook=None):
    opts = BASE_YTDL_OPTS.copy()
    opts.update({
        'format': 'bestaudio/best',
        'postprocessors': [
            {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
            {'key': 'FFmpegMetadata', 'add_metadata': True},
        ],
        'writethumbnail': True,
        'addmetadata': True,
    })
    if progress_hook:
        opts['progress_hooks'] = [progress_hook]
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        base = ydl.prepare_filename(info).rsplit('.', 1)[0]
        mp3_path = base + '.mp3'
        return mp3_path, info

def download_video(url: str, resolution: str = "best", progress_hook=None):
    opts = BASE_YTDL_OPTS.copy()
    if resolution == "best":
        fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    else:
        fmt = f'bestvideo[height<={resolution}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]'
    opts.update({'format': fmt, 'merge_output_format': 'mp4'})
    if progress_hook:
        opts['progress_hooks'] = [progress_hook]
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_path = ydl.prepare_filename(info)
        if not video_path.endswith('.mp4'):
            video_path = video_path.rsplit('.', 1)[0] + '.mp4'
        return video_path, info