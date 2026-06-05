import sys
import os
import subprocess
import platform
import yt_dlp
import requests
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QPushButton, QComboBox, QLabel, QProgressBar,
                             QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
                             QMessageBox, QStatusBar, QFrame, QCheckBox, QDialog,
                             QTextEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QPalette, QColor, QIcon

from gui_worker import DownloadWorker
from config import settings, save_settings, DOWNLOADS_DIR, get_ffmpeg_path
from search_dialog import SearchDialog
from database import init_db, add_download, get_all_downloads, scan_folder_and_sync
from zapret_manager import ZapretManager

class InfoFetcher(QThread):
    info_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
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
                result = {
                    'title': info.get('title', 'Нет названия'),
                    'uploader': info.get('uploader', 'Неизвестный канал'),
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0),
                    'view_count': info.get('view_count', 0),
                    'is_playlist': 'entries' in info and len(info.get('entries', [])) > 1,
                    'playlist_count': len(info.get('entries', [])) if 'entries' in info else 0
                }
                self.info_ready.emit(result)
        except Exception as e:
            self.error.emit(str(e))

class ConsoleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Консоль service.bat")
        self.setMinimumSize(800, 500)
        layout = QVBoxLayout(self)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFontFamily("Courier New")
        layout.addWidget(self.text_edit)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def append_text(self, text):
        self.text_edit.append(text)

class KSDtubeGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KSDtube")
        self.setMinimumSize(900, 750)

        # Иконка
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent
        icon_path = base / 'ksdtube.ico'
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
            QApplication.instance().setWindowIcon(QIcon(str(icon_path)))

        self.setup_dark_theme()

        self.current_download_dir = DOWNLOADS_DIR
        self.current_worker = None
        self.current_info = None

        self.zapret_manager = ZapretManager()
        self.zapret_auto_start = settings.get("zapret_auto_start", False)

        self.zapret_status_timer = QTimer()
        self.zapret_status_timer.timeout.connect(self.update_zapret_status)
        self.zapret_status_timer.start(5000)

        init_db()
        scan_folder_and_sync()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)

        # Название
        title_label = QLabel("🎵 KSDtube")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 20pt; font-weight: bold; color: #2ecc71; margin: 5px;")
        main_layout.addWidget(title_label)

        # Ввод ссылки
        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Вставьте ссылку на YouTube видео или плейлист...")
        self.url_input.clear()
        self.url_input.textChanged.connect(self.on_url_changed)
        self.url_input.setMinimumHeight(35)
        input_layout.addWidget(self.url_input)

        self.preview_btn = QPushButton("Предпросмотр")
        self.preview_btn.clicked.connect(self.fetch_video_info)
        input_layout.addWidget(self.preview_btn)

        self.search_btn = QPushButton("🔍 Поиск")
        self.search_btn.clicked.connect(self.open_search)
        input_layout.addWidget(self.search_btn)

        self.download_btn = QPushButton("Скачать")
        self.download_btn.setMinimumHeight(35)
        self.download_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.download_btn.clicked.connect(self.start_download)
        input_layout.addWidget(self.download_btn)
        main_layout.addLayout(input_layout)

        # Предпросмотр
        self.preview_frame = QFrame()
        self.preview_frame.setFrameShape(QFrame.Shape.Box)
        self.preview_frame.setVisible(False)
        self.preview_frame.setStyleSheet("QFrame { background-color: #2d2d2d; border-radius: 8px; }")
        preview_layout = QHBoxLayout(self.preview_frame)
        preview_layout.setSpacing(20)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(140, 140)
        self.thumbnail_label.setScaledContents(True)
        self.thumbnail_label.setStyleSheet("border: 2px solid #555; border-radius: 8px; background-color: #1e1e1e;")
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.thumbnail_label)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #fff;")
        self.uploader_label = QLabel()
        self.uploader_label.setStyleSheet("color: #bbb; font-size: 11pt;")
        stats_layout = QHBoxLayout()
        self.views_label = QLabel()
        self.views_label.setStyleSheet("color: #888; font-size: 10pt;")
        self.duration_label = QLabel()
        self.duration_label.setStyleSheet("color: #888; font-size: 10pt;")
        stats_layout.addWidget(self.views_label)
        stats_layout.addWidget(self.duration_label)
        stats_layout.addStretch()
        right_layout.addWidget(self.title_label)
        right_layout.addWidget(self.uploader_label)
        right_layout.addLayout(stats_layout)
        right_layout.addStretch()
        preview_layout.addLayout(right_layout, stretch=1)
        main_layout.addWidget(self.preview_frame)

        # Формат, качество, обрезка
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Формат:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["MP3 (аудио)", "MP4 (видео)"])
        self.format_combo.currentIndexChanged.connect(self.on_format_changed)
        format_layout.addWidget(self.format_combo)

        self.quality_label = QLabel("Качество:")
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["best", "720p", "480p", "360p"])
        self.quality_label.setVisible(False)
        self.quality_combo.setVisible(False)
        format_layout.addWidget(self.quality_label)
        format_layout.addWidget(self.quality_combo)

        self.trim_checkbox = QCheckBox("Обрезать")
        self.trim_checkbox.stateChanged.connect(self.on_trim_toggle)
        format_layout.addWidget(self.trim_checkbox)

        self.trim_start_label = QLabel("С:")
        self.trim_start_input = QLineEdit()
        self.trim_start_input.setPlaceholderText("0:00")
        self.trim_start_input.setFixedWidth(70)
        self.trim_start_input.setEnabled(False)
        format_layout.addWidget(self.trim_start_label)
        format_layout.addWidget(self.trim_start_input)

        self.trim_end_label = QLabel("По:")
        self.trim_end_input = QLineEdit()
        self.trim_end_input.setPlaceholderText("3:30")
        self.trim_end_input.setFixedWidth(70)
        self.trim_end_input.setEnabled(False)
        format_layout.addWidget(self.trim_end_label)
        format_layout.addWidget(self.trim_end_input)

        # Папки
        self.folder_btn = QPushButton("📁 Выбрать папку")
        self.folder_btn.clicked.connect(self.change_download_folder)
        format_layout.addWidget(self.folder_btn)

        self.open_folder_btn = QPushButton("📂 Открыть папку")
        self.open_folder_btn.clicked.connect(self.open_download_folder)
        format_layout.addWidget(self.open_folder_btn)

        self.folder_label = QLabel(f"Сохранять в: {self.current_download_dir}")
        self.folder_label.setStyleSheet("font-size: 9pt; color: #ccc;")
        format_layout.addWidget(self.folder_label)

        format_layout.addStretch()
        main_layout.addLayout(format_layout)

        # Прогресс и статус
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Введите ссылку для предпросмотра")
        self.status_label.setStyleSheet("color: #aaa;")
        main_layout.addWidget(self.status_label)

        # Таблица истории
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Тип", "Название", "Путь", "Статус"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        main_layout.addWidget(QLabel("История загрузок:"))
        main_layout.addWidget(self.table)

        # Строка состояния
        self.zapret_status_label = QLabel("🛡️ Zapret: проверка...")
        self.zapret_status_label.setStyleSheet("color: #aaa; font-size: 9pt;")
        self.zapret_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zapret_status_label.setToolTip("Нажмите, чтобы запустить service.bat для настройки Zapret")
        self.zapret_status_label.mousePressEvent = self.on_zapret_clicked
        self.statusBar().addPermanentWidget(self.zapret_status_label)
        self.statusBar().showMessage("Сделано KSD")
        self.statusBar().setStyleSheet("QStatusBar::item { border: none; }")
        self.hint_label = QLabel("⚙️ Кликните по статусу Zapret для настройки")
        self.hint_label.setStyleSheet("color: #888; font-size: 8pt;")
        self.statusBar().addPermanentWidget(self.hint_label)

        # Загрузка настроек
        last_format = settings.get("last_format", "mp3")
        self.format_combo.setCurrentIndex(0 if last_format == "mp3" else 1)
        self.on_format_changed()
        last_quality = settings.get("last_quality", "best")
        idx = self.quality_combo.findText(last_quality, Qt.MatchFlag.MatchContains)
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)

        self.url_timer = QTimer()
        self.url_timer.setSingleShot(True)
        self.url_timer.timeout.connect(self.fetch_video_info)

        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.auto_refresh_history)
        self.refresh_timer.start(5000)

        self.load_history()
        self.update_zapret_status()
        if self.zapret_auto_start:
            self.zapret_manager.run_service_bat(None, None)
            QTimer.singleShot(1000, self.update_zapret_status)

    # ---------- Zapret ----------
    def update_zapret_status(self):
        active = self.zapret_manager.is_active()
        if active:
            self.zapret_status_label.setText("🛡️ Zapret: активен")
            self.zapret_status_label.setStyleSheet("color: #2ecc71; font-size: 9pt;")
        else:
            self.zapret_status_label.setText("🛡️ Zapret: неактивен")
            self.zapret_status_label.setStyleSheet("color: #e74c3c; font-size: 9pt;")

    def on_zapret_clicked(self, event):
        dialog = ConsoleDialog(self)
        def on_output(text):
            dialog.append_text(text)
        def on_finished():
            dialog.append_text("\n[Процесс service.bat завершён]")
        success, msg = self.zapret_manager.run_service_bat(on_output, on_finished)
        if not success:
            QMessageBox.warning(self, "Ошибка", f"Не удалось запустить service.bat: {msg}")
        else:
            dialog.append_text(f"Запуск service.bat...\n{msg}\n")
            dialog.exec()

    # ---------- Остальные методы ----------
    def auto_refresh_history(self):
        scan_folder_and_sync()
        self.load_history()

    def load_history(self):
        rows = get_all_downloads()
        self.table.setRowCount(0)
        for file_path, file_type, title, status in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem("🎵 " + file_type if file_type == "MP3" else "🎬 " + file_type))
            self.table.setItem(row, 1, QTableWidgetItem(title))
            self.table.setItem(row, 2, QTableWidgetItem(file_path))
            self.table.setItem(row, 3, QTableWidgetItem(status))

    def setup_dark_theme(self):
        app = QApplication.instance()
        app.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.black)
        palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        app.setPalette(palette)

    def on_url_changed(self):
        self.url_timer.start(800)

    def fetch_video_info(self):
        url = self.url_input.text().strip()
        if not url:
            self.preview_frame.setVisible(False)
            return
        self.status_label.setText("Получение информации...")
        self.fetcher = InfoFetcher(url)
        self.fetcher.info_ready.connect(self.display_video_info)
        self.fetcher.error.connect(self.on_info_error)
        self.fetcher.start()

    def display_video_info(self, info):
        self.current_info = info
        if info.get('is_playlist'):
            self.title_label.setText(f"📋 ПЛЕЙЛИСТ: {info['title']}")
            self.uploader_label.setText(f"📺 {info['uploader']} | {info['playlist_count']} видео")
            self.views_label.setText("")
            self.duration_label.setText("")
            self.thumbnail_label.setText("нет фото")
        else:
            self.title_label.setText(f"🎬 {info['title']}")
            self.uploader_label.setText(f"📺 {info['uploader']}")
            views = info['view_count']
            views_str = f"{views:,}" if views else "0"
            self.views_label.setText(f"👁️ {views_str} просмотров")
            duration = info['duration']
            if duration:
                minutes = duration // 60
                seconds = duration % 60
                dur_str = f"{minutes}:{seconds:02d}"
            else:
                dur_str = "0:00"
            self.duration_label.setText(f"⏱️ {dur_str}")
            if info['thumbnail']:
                try:
                    resp = requests.get(info['thumbnail'], timeout=10)
                    pixmap = QPixmap()
                    pixmap.loadFromData(resp.content)
                    if not pixmap.isNull():
                        scaled = pixmap.scaled(140, 140, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        self.thumbnail_label.setPixmap(scaled)
                    else:
                        self.thumbnail_label.setText("нет фото")
                except Exception:
                    self.thumbnail_label.setText("ошибка")
            else:
                self.thumbnail_label.setText("нет фото")
        self.preview_frame.setVisible(True)
        self.status_label.setText("Информация загружена")

    def on_info_error(self, error_msg):
        self.preview_frame.setVisible(False)
        self.status_label.setText(f"Ошибка: {error_msg}")

    def on_format_changed(self):
        is_mp4 = (self.format_combo.currentIndex() == 1)
        self.quality_label.setVisible(is_mp4)
        self.quality_combo.setVisible(is_mp4)

    def on_trim_toggle(self, state):
        enabled = (state == Qt.CheckState.Checked.value)
        self.trim_start_input.setEnabled(enabled)
        self.trim_end_input.setEnabled(enabled)

    def change_download_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения", str(self.current_download_dir))
        if folder:
            self.current_download_dir = folder
            self.folder_label.setText(f"Сохранять в: {self.current_download_dir}")
            settings["download_dir"] = folder
            save_settings(settings)
            scan_folder_and_sync()
            self.load_history()

    def open_download_folder(self):
        path = str(self.current_download_dir)
        if os.path.exists(path):
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        else:
            QMessageBox.warning(self, "Ошибка", "Папка не существует")

    def open_search(self):
        dialog = SearchDialog(self)
        dialog.video_selected.connect(self.on_search_selected)
        dialog.exec()

    def on_search_selected(self, url):
        if url:
            self.url_input.setText(url)
            self.fetch_video_info()

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Введите ссылку на видео или плейлист")
            return
        media_type = "mp3" if self.format_combo.currentIndex() == 0 else "mp4"
        quality = None
        if media_type == "mp4":
            quality = self.quality_combo.currentText().replace('p', '')
            if quality == "best":
                quality = "best"

        trim_start = None
        trim_end = None
        if self.trim_checkbox.isChecked():
            trim_start = self.trim_start_input.text().strip()
            trim_end = self.trim_end_input.text().strip()
            if not trim_start and not trim_end:
                QMessageBox.warning(self, "Ошибка", "Укажите время начала или конца для обрезки")
                return

        settings["last_format"] = media_type
        if quality:
            settings["last_quality"] = quality
        save_settings(settings)

        self.download_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Подготовка...")

        self.current_worker = DownloadWorker(url, media_type, quality, trim_start, trim_end, self.current_download_dir)
        self.current_worker.progress.connect(self.update_progress)
        self.current_worker.finished.connect(self.on_download_finished)
        self.current_worker.playlist_progress.connect(self.on_playlist_progress)
        self.current_worker.error.connect(self.on_download_error)
        self.current_worker.start()

    def update_progress(self, percent, speed, status_text):
        self.progress_bar.setValue(percent)
        self.status_label.setText(status_text)

    def on_playlist_progress(self, current, total, message):
        self.status_label.setText(f"Плейлист: {message}")
        if total > 0:
            self.progress_bar.setValue(int((current+1)/total*100))

    def on_download_finished(self, file_path, media_type, info):
        if file_path:
            file_type = "MP3" if media_type == "mp3" else "MP4"
            add_download(file_path, file_type, info.get('title', 'Unknown'))
            self.load_history()
            QMessageBox.information(self, "Успех", f"Скачивание завершено!\n{file_path}")
        self.download_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

    def on_download_error(self, error_msg):
        self.progress_bar.setVisible(False)
        self.status_label.setText("Ошибка: " + error_msg)
        self.download_btn.setEnabled(True)
        QMessageBox.critical(self, "Ошибка", error_msg)

    def closeEvent(self, event):
        if self.current_worker and self.current_worker.isRunning():
            reply = QMessageBox.question(self, "Подтверждение", "Загрузка ещё идёт. Прервать и выйти?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.current_worker.terminate()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = KSDtubeGUI()
    window.show()
    sys.exit(app.exec())