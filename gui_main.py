import sys
import os
import sqlite3
import subprocess
import platform
import yt_dlp
import requests
import shutil
from pathlib import Path
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

from gui_worker import DownloadWorker
from config import settings, save_settings, DOWNLOADS_DIR, get_ffmpeg_path, get_zapret_dir
from search_dialog import SearchDialog
from database import init_db, add_download, get_all_downloads, scan_folder_and_sync, \
                     create_playlist, get_playlists, delete_playlist, add_to_playlist, \
                     get_playlist_items, remove_from_playlist, update_playlist_item_file, \
                     update_playlist_avatar, DB_PATH
from zapret_manager import ZapretManager
from zapret_updater import ZapretUpdater
from tg_proxy_manager import TgProxyManager, TgProxyUpdater

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
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
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
        self.setMinimumSize(1200, 750)

        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent
        icon_path = base / 'ksdtube.ico'
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
            QApplication.instance().setWindowIcon(QIcon(str(icon_path)))

        self.setup_styles()

        self.current_download_dir = DOWNLOADS_DIR
        self.current_worker = None
        self.current_fetcher = None
        self.current_info = None

        self.zapret_updater = None
        self.tg_proxy_updater = None

        self.zapret_manager = ZapretManager()
        self.zapret_auto_start = settings.get("zapret_auto_start", False)
        self.tg_proxy_manager = TgProxyManager()

        init_db()
        scan_folder_and_sync()

        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        self.download_tab = QWidget()
        self.setup_download_tab()
        self.tab_widget.addTab(self.download_tab, "Загрузчик")

        self.playlists_tab = QWidget()
        self.setup_playlists_tab()
        self.tab_widget.addTab(self.playlists_tab, "Плейлисты")

        # Статусбар
        self.zapret_status_label = QLabel("🛡️ Zapret: проверка...")
        self.zapret_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zapret_status_label.setToolTip("Нажмите, чтобы запустить service.bat для настройки Zapret")
        self.zapret_status_label.mousePressEvent = self.on_zapret_clicked
        self.tg_proxy_status_label = QLabel("📡 Telegram Proxy: проверка...")
        self.tg_proxy_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tg_proxy_status_label.setToolTip("Нажмите, чтобы запустить/остановить обход Telegram")
        self.tg_proxy_status_label.mousePressEvent = self.on_tg_proxy_clicked
        self.lists_status_label = QLabel("📄 Списки Zapret")
        self.lists_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lists_status_label.setToolTip("Нажмите, чтобы редактировать txt-файлы списков")
        self.lists_status_label.mousePressEvent = self.open_lists_editor

        self.statusBar().addPermanentWidget(self.zapret_status_label)
        self.statusBar().addPermanentWidget(self.tg_proxy_status_label)
        self.statusBar().addPermanentWidget(self.lists_status_label)
        self.statusBar().showMessage("Сделано KSD")
        self.statusBar().setStyleSheet("QStatusBar::item { border: none; }")
        self.hint_label = QLabel("⚙️ Кликните по статусу Zapret для настройки")
        self.hint_label.setStyleSheet("color: #888; font-size: 8pt;")
        self.statusBar().addPermanentWidget(self.hint_label)

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_all_statuses)
        self.status_timer.start(5000)

        self.check_updates_once()
        self.update_all_statuses()

        # --- Синхронизация плейлистов (каждые 2 секунды) ---
        self.sync_timer = QTimer()
        self.sync_timer.timeout.connect(self.sync_playlists_from_folders)
        self.sync_timer.start(2000)
        self.sync_playlists_from_folders()

        # --- Динамическое обновление истории загрузок (каждые 3 секунды) ---
        self.history_sync_timer = QTimer()
        self.history_sync_timer.timeout.connect(self.sync_history_from_folder)
        self.history_sync_timer.start(3000)
        self.sync_history_from_folder()

    def setup_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; }
            QLabel { color: #e0e0e0; }
            QPushButton { background-color: #2d2d2d; color: #ffffff; border: none; padding: 6px; border-radius: 4px; }
            QPushButton:hover { background-color: #3d3d3d; }
            QPushButton:pressed { background-color: #1d1d1d; }
            QLineEdit, QTextEdit, QComboBox, QTableWidget { background-color: #1e1e1e; color: #ffffff; border: 1px solid #3d3d3d; border-radius: 4px; padding: 4px; }
            QTabWidget::pane { background: #1e1e1e; border: 1px solid #3d3d3d; }
            QTabBar::tab { background: #2d2d2d; color: #ffffff; padding: 8px 12px; margin-right: 2px; }
            QTabBar::tab:selected { background: #3d3d3d; }
            QTableWidget { alternate-background-color: #2a2a2a; }
            QHeaderView::section { background-color: #2d2d2d; color: white; }
            QProgressBar { border: 1px solid #3d3d3d; border-radius: 4px; text-align: center; }
            QProgressBar::chunk { background-color: #00aaff; }
        """)
        self.title_label = QLabel("KSDtube")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-size: 24pt; font-weight: bold; color: #00aaff; margin: 10px;")

    # ---------- Вкладка Загрузчик ----------
    def setup_download_tab(self):
        layout = QVBoxLayout(self.download_tab)
        layout.addWidget(self.title_label)

        input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Вставьте ссылку на YouTube видео или плейлист...")
        self.url_input.textChanged.connect(self.on_url_changed)
        input_layout.addWidget(self.url_input)
        self.preview_btn = QPushButton("Предпросмотр")
        self.preview_btn.clicked.connect(self.fetch_video_info)
        input_layout.addWidget(self.preview_btn)
        self.search_btn = QPushButton("🔍 Поиск")
        self.search_btn.clicked.connect(self.open_search)
        input_layout.addWidget(self.search_btn)
        self.download_btn = QPushButton("Скачать")
        self.download_btn.setStyleSheet("background-color: #4CAF50;")
        self.download_btn.clicked.connect(self.start_download)
        input_layout.addWidget(self.download_btn)
        layout.addLayout(input_layout)

        self.preview_frame = QFrame()
        self.preview_frame.setVisible(False)
        self.preview_frame.setStyleSheet("background-color: #1e1e1e; border-radius: 8px;")
        preview_layout = QHBoxLayout(self.preview_frame)
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(160, 160)
        self.thumbnail_label.setStyleSheet("border: 2px solid #3d3d3d; border-radius: 8px;")
        preview_layout.addWidget(self.thumbnail_label)
        info_layout = QVBoxLayout()
        self.title_label_preview = QLabel()
        self.title_label_preview.setWordWrap(True)
        self.title_label_preview.setStyleSheet("font-size: 14pt; font-weight: bold;")
        self.uploader_label = QLabel()
        self.views_label = QLabel()
        self.duration_label = QLabel()
        info_layout.addWidget(self.title_label_preview)
        info_layout.addWidget(self.uploader_label)
        info_layout.addWidget(self.views_label)
        info_layout.addWidget(self.duration_label)
        preview_layout.addLayout(info_layout)
        layout.addWidget(self.preview_frame)

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
        self.trim_start = QLineEdit()
        self.trim_start.setPlaceholderText("0:00")
        self.trim_start.setFixedWidth(70)
        self.trim_start.setEnabled(False)
        self.trim_end = QLineEdit()
        self.trim_end.setPlaceholderText("3:30")
        self.trim_end.setFixedWidth(70)
        self.trim_end.setEnabled(False)
        format_layout.addWidget(QLabel("С:"))
        format_layout.addWidget(self.trim_start)
        format_layout.addWidget(QLabel("По:"))
        format_layout.addWidget(self.trim_end)
        self.folder_btn = QPushButton("📁 Выбрать папку")
        self.folder_btn.clicked.connect(self.change_download_folder)
        format_layout.addWidget(self.folder_btn)
        self.open_folder_btn = QPushButton("📂 Открыть папку")
        self.open_folder_btn.clicked.connect(self.open_download_folder)
        format_layout.addWidget(self.open_folder_btn)
        self.folder_label = QLabel(f"Сохранять в: {self.current_download_dir}")
        format_layout.addWidget(self.folder_label)
        format_layout.addStretch()
        layout.addLayout(format_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("Введите ссылку для предпросмотра")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("История загрузок:"))
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["Тип", "Название", "Путь", "Статус"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self.history_context_menu)
        layout.addWidget(self.history_table)

        self.url_timer = QTimer()
        self.url_timer.setSingleShot(True)
        self.url_timer.timeout.connect(self.fetch_video_info)
        # refresh_timer уже не нужен, будет sync_history_from_folder

    def history_context_menu(self, pos):
        item = self.history_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        file_path = self.history_table.item(row, 2).text()
        title = self.history_table.item(row, 1).text()
        menu = QMenu()
        add_to_playlist_action = menu.addAction("Добавить в плейлист")
        open_folder_action = menu.addAction("Открыть папку с файлом")
        action = menu.exec(self.history_table.viewport().mapToGlobal(pos))
        if action == add_to_playlist_action:
            self.show_add_to_playlist_dialog(title, file_path)
        elif action == open_folder_action:
            subprocess.run(['explorer', '/select,', file_path])

    def show_add_to_playlist_dialog(self, title, file_path):
        playlists = get_playlists()
        if not playlists:
            QMessageBox.warning(self, "Нет плейлистов", "Сначала создайте плейлист на вкладке 'Плейлисты'.")
            return
        items = [f"{pl[1]} ({pl[2]})" for pl in playlists]
        item, ok = QInputDialog.getItem(self, "Добавить в плейлист", "Выберите плейлист:", items, 0, False)
        if ok and item:
            name = item.split(" (")[0]
            for pl in playlists:
                if pl[1] == name:
                    pl_id = pl[0]
                    folder = pl[3]
                    dest = Path(folder) / Path(file_path).name
                    if not dest.exists():
                        shutil.copy2(file_path, dest)
                    add_to_playlist(pl_id, title, "", str(dest))
                    QMessageBox.information(self, "Готово", f"Добавлено в плейлист '{name}'")
                    break

    # ---------- Динамическое обновление истории загрузок ----------
    def sync_history_from_folder(self):
        """Сканирует папку загрузок и синхронизирует таблицу истории: добавляет новые файлы, удаляет отсутствующие."""
        # Получаем текущие файлы в папке
        current_files = set()
        for ext in ['*.mp3', '*.mp4']:
            current_files.update(self.current_download_dir.glob(ext))
        current_paths = {str(f) for f in current_files}
        # Получаем файлы из БД
        db_files = {row[0] for row in get_all_downloads()}
        # Удаляем из БД те, которых нет на диске
        for file_path in db_files - current_paths:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('DELETE FROM downloads WHERE file_path = ?', (file_path,))
            conn.commit()
            conn.close()
        # Добавляем в БД те, что есть на диске, но нет в БД
        for file_path in current_paths - db_files:
            p = Path(file_path)
            file_type = "MP3" if p.suffix == '.mp3' else "MP4"
            title = p.stem
            add_download(file_path, file_type, title)
        # Обновляем таблицу
        self.load_history()

    # ---------- Синхронизация плейлистов ----------
    def sync_playlists_from_folders(self):
        current_playlist_id = self.current_playlist_id if hasattr(self, 'current_playlist_id') else None
        
        playlists = get_playlists()
        for pl in playlists:
            pl_id, name, pl_type, folder_path, avatar_path, color, _ = pl
            if not folder_path or not Path(folder_path).exists():
                delete_playlist(pl_id, None)
                continue
            current_files = set()
            for ext in ['*.mp3', '*.mp4']:
                current_files.update(Path(folder_path).glob(ext))
            items = get_playlist_items(pl_id)
            db_files = {Path(it[3]) for it in items if it[3]}
            for it in items:
                if it[3] and not Path(it[3]).exists():
                    remove_from_playlist(it[0])
            for file_path in current_files:
                if file_path not in db_files:
                    title = file_path.stem
                    add_to_playlist(pl_id, title, "", str(file_path))
        
        self.refresh_playlists(restore_id=current_playlist_id)
        
        if current_playlist_id is not None:
            exists = any(pl[0] == current_playlist_id for pl in get_playlists())
            if exists:
                self.on_playlist_selected_by_id(current_playlist_id)
            else:
                self.playlist_name_label.setText("Выберите плейлист")
                self.playlist_avatar_label.clear()
                self.playlist_content.setRowCount(0)
                self.delete_playlist_btn.setEnabled(False)
                self.open_playlist_folder_btn.setEnabled(False)
                self.current_playlist_id = None
                self.current_playlist_folder = None

    # ---------- Редактирование списков Zapret ----------
    def open_lists_editor(self, event=None):
        lists_dir = get_zapret_dir() / "lists"
        if not lists_dir.exists():
            QMessageBox.warning(self, "Ошибка", f"Папка с файлами списков не найдена:\n{lists_dir}")
            return
        txt_files = list(lists_dir.glob("*.txt"))
        if not txt_files:
            QMessageBox.information(self, "Нет файлов", "В папке lists нет txt-файлов.")
            return
        self.show_lists_dialog(txt_files, lists_dir)

    def show_lists_dialog(self, files, lists_dir):
        dialog = QDialog(self)
        dialog.setWindowTitle("Редактирование списков Zapret")
        dialog.setMinimumSize(500, 400)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Двойной клик по файлу для редактирования в блокноте:"))
        list_widget = QListWidget()
        for f in files:
            list_widget.addItem(f.name)
        list_widget.itemDoubleClicked.connect(lambda item: self.open_with_notepad(lists_dir / item.text()))
        layout.addWidget(list_widget)
        btn_layout = QHBoxLayout()
        open_folder_btn = QPushButton("📂 Открыть папку lists")
        open_folder_btn.clicked.connect(lambda: self.open_lists_folder(lists_dir))
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(open_folder_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        dialog.exec()

    def open_with_notepad(self, file_path):
        if not file_path.exists():
            QMessageBox.warning(self, "Ошибка", "Файл не найден")
            return
        try:
            subprocess.run(['notepad.exe', str(file_path)], check=True)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть файл: {e}")

    def open_lists_folder(self, lists_dir):
        if platform.system() == "Windows":
            os.startfile(lists_dir)
        else:
            subprocess.run(["open" if platform.system()=="Darwin" else "xdg-open", str(lists_dir)])

    # ---------- Вкладка Плейлисты ----------
    def setup_playlists_tab(self):
        layout = QHBoxLayout(self.playlists_tab)
        
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("Плейлисты:"))
        self.playlists_list = QListWidget()
        self.playlists_list.setIconSize(QSize(32, 32))
        self.playlists_list.itemClicked.connect(self.on_playlist_selected)
        left_layout.addWidget(self.playlists_list)
        
        btn_layout = QHBoxLayout()
        self.create_playlist_btn = QPushButton("+ Создать")
        self.create_playlist_btn.clicked.connect(self.create_playlist_dialog)
        btn_layout.addWidget(self.create_playlist_btn)
        self.delete_playlist_btn = QPushButton("🗑 Удалить")
        self.delete_playlist_btn.setEnabled(False)
        self.delete_playlist_btn.clicked.connect(self.delete_current_playlist)
        btn_layout.addWidget(self.delete_playlist_btn)
        left_layout.addLayout(btn_layout)
        
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        header_layout = QHBoxLayout()
        self.playlist_avatar_label = QLabel()
        self.playlist_avatar_label.setFixedSize(80, 80)
        self.playlist_avatar_label.setStyleSheet("border: 2px solid #555; border-radius: 10px; background-color: #2a2a2a;")
        self.playlist_avatar_label.setScaledContents(True)
        self.playlist_avatar_label.mousePressEvent = self.change_playlist_avatar
        header_layout.addWidget(self.playlist_avatar_label)
        self.playlist_name_label = QLabel("Выберите плейлист")
        self.playlist_name_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        header_layout.addWidget(self.playlist_name_label)
        header_layout.addStretch()
        right_layout.addLayout(header_layout)
        
        self.playlist_content = QTableWidget(0, 3)
        self.playlist_content.setHorizontalHeaderLabels(["Название", "Статус", "Действия"])
        self.playlist_content.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(self.playlist_content)
        
        track_btn_layout = QHBoxLayout()
        self.add_track_btn = QPushButton("➕ Добавить трек")
        self.add_track_btn.clicked.connect(self.add_track_to_playlist)
        track_btn_layout.addWidget(self.add_track_btn)
        self.open_playlist_folder_btn = QPushButton("📂 Открыть папку плейлиста")
        self.open_playlist_folder_btn.clicked.connect(self.open_current_playlist_folder)
        self.open_playlist_folder_btn.setEnabled(False)
        track_btn_layout.addWidget(self.open_playlist_folder_btn)
        right_layout.addLayout(track_btn_layout)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 600])
        layout.addWidget(splitter)
        
        self.refresh_playlists()
        self.current_playlist_id = None
        self.current_playlist_folder = None

    def refresh_playlists(self, restore_id=None):
        current_row = self.playlists_list.currentRow() if self.playlists_list.currentItem() else 0
        self.playlists_list.clear()
        playlists = get_playlists()
        self.playlist_items = playlists
        found_restore = False
        for pl in playlists:
            pl_id, name, pl_type, folder, avatar_path, color, _ = pl
            item = QListWidgetItem(name)
            if color:
                item.setForeground(QColor(color))
            else:
                item.setForeground(QColor(200, 200, 200))
            if avatar_path and Path(avatar_path).exists():
                pixmap = QPixmap(avatar_path).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                item.setIcon(QIcon(pixmap))
            else:
                default_pix = QPixmap(32, 32)
                default_pix.fill(QColor(50, 50, 50))
                item.setIcon(QIcon(default_pix))
            self.playlists_list.addItem(item)
            item.setData(Qt.ItemDataRole.UserRole, pl_id)
            if restore_id is not None and pl_id == restore_id:
                found_restore = True
                self.playlists_list.setCurrentItem(item)
                self.on_playlist_selected(item)
        if not found_restore and restore_id is not None:
            self.playlist_name_label.setText("Нет плейлистов. Создайте новый.")
            self.playlist_avatar_label.clear()
            self.playlist_content.setRowCount(0)
            self.delete_playlist_btn.setEnabled(False)
            self.open_playlist_folder_btn.setEnabled(False)
            self.current_playlist_id = None
            self.current_playlist_folder = None
            if self.playlists_list.count() > 0:
                self.playlists_list.setCurrentRow(0)
                self.on_playlist_selected(self.playlists_list.currentItem())
        elif not found_restore and restore_id is None and self.playlists_list.count() > 0:
            if current_row < self.playlists_list.count():
                self.playlists_list.setCurrentRow(current_row)
                self.on_playlist_selected(self.playlists_list.currentItem())
            else:
                self.playlists_list.setCurrentRow(0)
                self.on_playlist_selected(self.playlists_list.currentItem())
        elif found_restore:
            pass

    def on_playlist_selected(self, item):
        if not item:
            return
        pl_id = item.data(Qt.ItemDataRole.UserRole)
        if pl_id is None:
            return
        name = item.text()
        playlists = get_playlists()
        self.current_playlist_id = pl_id
        self.current_playlist_folder = None
        current_color = None
        avatar_path = None
        for pl in playlists:
            if pl[0] == pl_id:
                self.current_playlist_folder = pl[3]
                avatar_path = pl[4]
                current_color = pl[5]
                break
        if self.current_playlist_id is None:
            return
        self.playlist_name_label.setText(name)
        if current_color:
            self.playlist_name_label.setStyleSheet(f"font-size: 16pt; font-weight: bold; color: {current_color};")
        else:
            self.playlist_name_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #ffffff;")
        if avatar_path and Path(avatar_path).exists():
            pixmap = QPixmap(avatar_path).scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.playlist_avatar_label.setPixmap(pixmap)
        else:
            self.playlist_avatar_label.clear()
            self.playlist_avatar_label.setText("Аватар")
        self.delete_playlist_btn.setEnabled(True)
        self.open_playlist_folder_btn.setEnabled(True)
        items = get_playlist_items(self.current_playlist_id)
        self.playlist_content.setRowCount(0)
        for it in items:
            row = self.playlist_content.rowCount()
            self.playlist_content.insertRow(row)
            self.playlist_content.setItem(row, 0, QTableWidgetItem(it[1]))
            status = "Скачан" if it[4] else "Не скачан"
            self.playlist_content.setItem(row, 1, QTableWidgetItem(status))
            del_btn = QPushButton("Удалить")
            del_btn.clicked.connect(lambda checked, iid=it[0]: self.remove_track_from_playlist(iid))
            self.playlist_content.setCellWidget(row, 2, del_btn)

    def on_playlist_selected_by_id(self, pl_id):
        for i in range(self.playlists_list.count()):
            item = self.playlists_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == pl_id:
                self.playlists_list.setCurrentItem(item)
                self.on_playlist_selected(item)
                break

    def create_playlist_dialog(self):
        name, ok = QInputDialog.getText(self, "Новый плейлист", "Название:")
        if ok and name:
            playlist_folder = self.current_download_dir / "Playlists" / name
            playlist_folder.mkdir(parents=True, exist_ok=True)
            pl_id = create_playlist(name, "music", str(playlist_folder))
            self.refresh_playlists(restore_id=pl_id)
            self.sync_playlists_from_folders()
            QMessageBox.information(self, "Успех", f"Плейлист '{name}' создан. Папка: {playlist_folder}")

    def delete_current_playlist(self):
        if self.current_playlist_id is None:
            return
        reply = QMessageBox.question(self, "Удалить плейлист", "Удалить плейлист вместе со всеми треками (файлы останутся в папке загрузок)?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            delete_playlist(self.current_playlist_id, self.current_playlist_folder)
            self.current_playlist_id = None
            self.current_playlist_folder = None
            self.refresh_playlists(restore_id=None)
            self.sync_playlists_from_folders()
            if self.playlists_list.count() > 0:
                self.playlists_list.setCurrentRow(0)
                self.on_playlist_selected(self.playlists_list.currentItem())
            QMessageBox.information(self, "Готово", "Плейлист удалён.")

    def remove_track_from_playlist(self, item_id):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT file_path, playlist_id FROM playlist_items WHERE id = ?', (item_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            QMessageBox.warning(self, "Ошибка", "Трек не найден в базе.")
            return
        file_path, playlist_id = row
        reply = QMessageBox.question(self, "Удаление трека", 
                                     "Удалить файл из папки плейлиста? (Если файл используется в других плейлистах, лучше оставить)",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Cancel:
            return
        remove_from_playlist(item_id)
        if reply == QMessageBox.StandardButton.Yes and file_path and Path(file_path).exists():
            Path(file_path).unlink()
            QMessageBox.information(self, "Готово", "Трек удалён из плейлиста и файл удалён.")
        else:
            QMessageBox.information(self, "Готово", "Трек удалён из плейлиста (файл сохранён).")
        self.sync_playlists_from_folders()
        if self.current_playlist_id:
            items = get_playlist_items(self.current_playlist_id)
            self.playlist_content.setRowCount(0)
            for it in items:
                row = self.playlist_content.rowCount()
                self.playlist_content.insertRow(row)
                self.playlist_content.setItem(row, 0, QTableWidgetItem(it[1]))
                status = "Скачан" if it[4] else "Не скачан"
                self.playlist_content.setItem(row, 1, QTableWidgetItem(status))
                del_btn = QPushButton("Удалить")
                del_btn.clicked.connect(lambda checked, iid=it[0]: self.remove_track_from_playlist(iid))
                self.playlist_content.setCellWidget(row, 2, del_btn)

    def add_track_to_playlist(self):
        if self.current_playlist_id is None:
            QMessageBox.warning(self, "Ошибка", "Сначала выберите плейлист.")
            return
        file_paths, _ = QFileDialog.getOpenFileNames(self, "Выберите аудио/видео файлы", str(self.current_download_dir),
                                                     "Медиа файлы (*.mp3 *.mp4);;Все файлы (*.*)")
        if not file_paths:
            return
        for fp in file_paths:
            title = Path(fp).stem
            dest = Path(self.current_playlist_folder) / Path(fp).name
            if not dest.exists():
                shutil.copy2(fp, dest)
            add_to_playlist(self.current_playlist_id, title, "", str(dest))
        self.sync_playlists_from_folders()
        QMessageBox.information(self, "Готово", f"Добавлено {len(file_paths)} треков.")

    def change_playlist_avatar(self, event):
        if self.current_playlist_id is None:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите изображение для аватарки плейлиста", "",
                                                   "Изображения (*.png *.jpg *.jpeg *.bmp);;Все файлы (*.*)")
        if file_path:
            dest_folder = Path(self.current_playlist_folder) / "avatar"
            dest_folder.mkdir(exist_ok=True)
            ext = Path(file_path).suffix
            dest = dest_folder / f"avatar{ext}"
            shutil.copy2(file_path, dest)
            update_playlist_avatar(self.current_playlist_id, str(dest))
            self.refresh_playlists(restore_id=self.current_playlist_id)
            QMessageBox.information(self, "Готово", "Аватарка плейлиста обновлена.")

    def open_current_playlist_folder(self):
        if self.current_playlist_folder and Path(self.current_playlist_folder).exists():
            if platform.system() == "Windows":
                os.startfile(self.current_playlist_folder)
            else:
                subprocess.run(["open" if platform.system()=="Darwin" else "xdg-open", self.current_playlist_folder])
        else:
            QMessageBox.warning(self, "Ошибка", "Папка плейлиста не найдена.")

    # ---------- Общие методы (загрузка, статусы, обновления) ----------
    def on_url_changed(self):
        self.url_timer.start(800)

    def fetch_video_info(self):
        if self.current_fetcher and self.current_fetcher.isRunning():
            return
        url = self.url_input.text().strip()
        if not url:
            self.preview_frame.setVisible(False)
            return
        self.status_label.setText("Получение информации...")
        self.current_fetcher = InfoFetcher(url)
        self.current_fetcher.info_ready.connect(self.display_video_info)
        self.current_fetcher.error.connect(self.on_info_error)
        self.current_fetcher.start()

    def display_video_info(self, info):
        self.current_info = info
        self.preview_frame.setVisible(True)
        self.title_label_preview.setText(info['title'])
        self.uploader_label.setText(f"Канал: {info['uploader']}")
        self.views_label.setText(f"Просмотров: {info['view_count']:,}")
        dur = info['duration']
        self.duration_label.setText(f"Длительность: {dur//60}:{dur%60:02d}")
        if info['thumbnail']:
            try:
                r = requests.get(info['thumbnail'], timeout=10)
                pix = QPixmap()
                pix.loadFromData(r.content)
                if not pix.isNull():
                    self.thumbnail_label.setPixmap(pix.scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatio))
            except:
                pass
        self.status_label.setText("Информация загружена")

    def on_info_error(self, err):
        self.preview_frame.setVisible(False)
        self.status_label.setText(f"Ошибка: {err}")

    def on_format_changed(self):
        is_mp4 = (self.format_combo.currentIndex() == 1)
        self.quality_label.setVisible(is_mp4)
        self.quality_combo.setVisible(is_mp4)

    def on_trim_toggle(self, state):
        en = (state == Qt.CheckState.Checked.value)
        self.trim_start.setEnabled(en)
        self.trim_end.setEnabled(en)

    def change_download_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку", str(self.current_download_dir))
        if folder:
            self.current_download_dir = Path(folder)
            self.folder_label.setText(f"Сохранять в: {self.current_download_dir}")
            settings["download_dir"] = str(self.current_download_dir)
            save_settings(settings)
            scan_folder_and_sync()
            self.sync_history_from_folder()
            self.sync_playlists_from_folders()

    def open_download_folder(self):
        path = str(self.current_download_dir)
        if os.path.exists(path):
            if platform.system() == "Windows":
                os.startfile(path)
            else:
                subprocess.run(["open" if platform.system()=="Darwin" else "xdg-open", path])

    def open_search(self):
        dialog = SearchDialog(self)
        dialog.video_selected.connect(self.on_search_selected)
        dialog.exec()

    def on_search_selected(self, url):
        self.url_input.setText(url)
        self.fetch_video_info()

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Введите ссылку")
            return
        media_type = "mp3" if self.format_combo.currentIndex() == 0 else "mp4"
        quality = None
        if media_type == "mp4":
            quality = self.quality_combo.currentText().replace('p', '')
            if quality == "best":
                quality = "best"
        trim_start = self.trim_start.text() if self.trim_checkbox.isChecked() else None
        trim_end = self.trim_end.text() if self.trim_checkbox.isChecked() else None
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

    def update_progress(self, percent, speed, text):
        self.progress_bar.setValue(percent)
        self.status_label.setText(text)

    def on_playlist_progress(self, cur, total, msg):
        self.status_label.setText(f"Плейлист: {msg}")

    def on_download_finished(self, path, media_type, info):
        self.progress_bar.setVisible(False)
        self.download_btn.setEnabled(True)
        if path:
            file_type = "MP3" if media_type == "mp3" else "MP4"
            add_download(path, file_type, info['title'])
            self.sync_history_from_folder()  # сразу обновить историю
            QMessageBox.information(self, "Успех", f"Скачано: {path}")
        self.status_label.setText("Готово")

    def on_download_error(self, err):
        self.progress_bar.setVisible(False)
        self.download_btn.setEnabled(True)
        self.status_label.setText(f"Ошибка: {err}")

    def load_history(self):
        rows = get_all_downloads()
        self.history_table.setRowCount(0)
        for file_path, file_type, title, status in rows:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            self.history_table.setItem(row, 0, QTableWidgetItem("🎵 "+file_type if file_type=="MP3" else "🎬 "+file_type))
            self.history_table.setItem(row, 1, QTableWidgetItem(title))
            self.history_table.setItem(row, 2, QTableWidgetItem(file_path))
            self.history_table.setItem(row, 3, QTableWidgetItem(status))

    def update_all_statuses(self):
        active = self.zapret_manager.is_active()
        self.zapret_status_label.setText(f"🛡️ Zapret: {'активен' if active else 'неактивен'}")
        self.zapret_status_label.setStyleSheet(f"color: {'#2ecc71' if active else '#e74c3c'}")
        running = self.tg_proxy_manager.is_running()
        self.tg_proxy_status_label.setText(f"📡 Telegram Proxy: {'активен' if running else 'неактивен'}")
        self.tg_proxy_status_label.setStyleSheet(f"color: {'#2ecc71' if running else '#e74c3c'}")

    def on_zapret_clicked(self, event):
        dialog = ConsoleDialog("Zapret service.bat", self)
        def on_out(text): dialog.append_text(text)
        def on_fin(): dialog.append_text("\n[Завершено]")
        self.zapret_manager.run_service_bat(on_out, on_fin)

    def on_tg_proxy_clicked(self, event):
        if self.tg_proxy_manager.is_running():
            self.tg_proxy_manager.stop()
            self.status_label.setText("Telegram Proxy остановлен")
        else:
            if not TG_PROXY_EXE.exists():
                reply = QMessageBox.question(self, "Файл не найден", "Скачать последнюю версию?",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    self.status_label.setText("Скачивание...")
                    self.tg_proxy_updater = TgProxyUpdater()
                    self.tg_proxy_updater.progress.connect(self.status_label.setText)
                    self.tg_proxy_updater.finished_signal.connect(lambda s,m: self.update_all_statuses())
                    self.tg_proxy_updater.start()
                return
            self.tg_proxy_manager.start()
            self.status_label.setText("Telegram Proxy запущен (свёрнут в трей)")
        self.update_all_statuses()

    def check_updates_once(self):
        self.zapret_updater = ZapretUpdater()
        self.zapret_updater.status_update.connect(lambda msg: None)
        self.zapret_updater.finished_signal.connect(self.on_zapret_update_finished)
        self.zapret_updater.start()
        self.tg_proxy_updater = TgProxyUpdater()
        self.tg_proxy_updater.progress.connect(lambda msg: None)
        self.tg_proxy_updater.finished_signal.connect(self.on_tg_proxy_update_finished)
        self.tg_proxy_updater.start()

    def on_zapret_update_finished(self, success, msg):
        if success:
            self.status_label.setText(f"Zapret: {msg}")
            self.update_all_statuses()

    def on_tg_proxy_update_finished(self, success, msg):
        if success:
            self.status_label.setText(f"Telegram Proxy: {msg}")
            self.update_all_statuses()

    def closeEvent(self, event):
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.quit()
            self.current_worker.wait(1000)
        if self.current_fetcher and self.current_fetcher.isRunning():
            self.current_fetcher.quit()
            self.current_fetcher.wait(1000)
        if self.zapret_updater and self.zapret_updater.isRunning():
            self.zapret_updater.quit()
            self.zapret_updater.wait(1000)
        if self.tg_proxy_updater and self.tg_proxy_updater.isRunning():
            self.tg_proxy_updater.quit()
            self.tg_proxy_updater.wait(1000)
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = KSDtubeGUI()
    window.show()
    sys.exit(app.exec())