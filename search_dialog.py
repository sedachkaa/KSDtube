import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
                             QPushButton, QListWidget, QListWidgetItem, QLabel,
                             QProgressBar, QMessageBox, QWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
import requests
import yt_dlp

class SearchWorker(QThread):
    result_ready = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                },
                'playlistend': 10,
            }
            search_query = f"ytsearch10:{self.query}"
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                entries = info.get('entries', [])
                results = []
                for entry in entries:
                    duration = entry.get('duration', 0)
                    if isinstance(duration, float):
                        duration = int(duration)
                    url = entry.get('webpage_url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                    results.append({
                        'title': entry.get('title', 'Нет названия'),
                        'uploader': entry.get('uploader', 'Неизвестный канал'),
                        'url': url,
                        'thumbnail': entry.get('thumbnail', ''),
                        'duration': duration,
                    })
                self.result_ready.emit(results)
        except Exception as e:
            self.error.emit(str(e))

class SearchDialog(QDialog):
    video_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Поиск видео на YouTube")
        self.setMinimumSize(700, 500)
        self.setModal(True)

        layout = QVBoxLayout(self)

        search_layout = QHBoxLayout()
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Введите название песни или исполнителя...")
        self.query_input.returnPressed.connect(self.start_search)
        search_layout.addWidget(self.query_input)

        self.search_btn = QPushButton("🔍 Искать")
        self.search_btn.clicked.connect(self.start_search)
        search_layout.addWidget(self.search_btn)

        layout.addLayout(search_layout)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.on_item_double_click)
        layout.addWidget(self.results_list)

        btn_layout = QHBoxLayout()
        self.select_btn = QPushButton("✅ Выбрать")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self.on_select_clicked)
        btn_layout.addStretch()
        btn_layout.addWidget(self.select_btn)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.worker = None
        self.results_urls = []

    def start_search(self):
        query = self.query_input.text().strip()
        if not query:
            return
        self.search_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.results_list.clear()
        self.results_urls.clear()
        self.select_btn.setEnabled(False)
        self.worker = SearchWorker(query)
        self.worker.result_ready.connect(self.display_results)
        self.worker.error.connect(self.show_error)
        self.worker.start()

    def display_results(self, results):
        self.progress.setVisible(False)
        self.search_btn.setEnabled(True)

        if not results:
            self.results_list.addItem("Ничего не найдено")
            return

        for idx, res in enumerate(results):
            self.results_urls.append(res['url'])
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(5, 5, 5, 5)

            thumb_label = QLabel()
            thumb_label.setFixedSize(120, 68)
            thumb_label.setScaledContents(True)
            thumb_label.setStyleSheet("border: 1px solid #555; border-radius: 4px; background-color: #1e1e1e;")
            if res['thumbnail']:
                try:
                    response = requests.get(res['thumbnail'], timeout=5)
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)
                    if not pixmap.isNull():
                        pixmap = pixmap.scaled(120, 68, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        thumb_label.setPixmap(pixmap)
                    else:
                        thumb_label.setText("нет фото")
                except Exception:
                    thumb_label.setText("ошибка")
            else:
                thumb_label.setText("нет фото")
            item_layout.addWidget(thumb_label)

            text_layout = QVBoxLayout()
            title_label = QLabel(res['title'])
            title_label.setStyleSheet("font-weight: bold; color: #fff;")
            title_label.setWordWrap(True)
            uploader_label = QLabel(f"📺 {res['uploader']}")
            uploader_label.setStyleSheet("color: #aaa;")
            duration = res['duration']
            if duration:
                minutes = duration // 60
                seconds = duration % 60
                dur_str = f"⏱️ {minutes}:{seconds:02d}"
            else:
                dur_str = ""
            duration_label = QLabel(dur_str)
            duration_label.setStyleSheet("color: #888;")
            text_layout.addWidget(title_label)
            text_layout.addWidget(uploader_label)
            text_layout.addWidget(duration_label)
            item_layout.addLayout(text_layout)

            item_widget.setLayout(item_layout)
            item_widget.setMinimumHeight(80)

            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            self.results_list.addItem(list_item)
            self.results_list.setItemWidget(list_item, item_widget)
            list_item.setData(Qt.ItemDataRole.UserRole, idx)

        self.results_list.itemSelectionChanged.connect(self.on_selection_changed)

    def on_selection_changed(self):
        self.select_btn.setEnabled(len(self.results_list.selectedItems()) > 0)

    def on_item_double_click(self, item):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is not None and 0 <= idx < len(self.results_urls):
            self.video_selected.emit(self.results_urls[idx])
            self.accept()

    def on_select_clicked(self):
        selected = self.results_list.selectedItems()
        if selected:
            idx = selected[0].data(Qt.ItemDataRole.UserRole)
            if idx is not None and 0 <= idx < len(self.results_urls):
                self.video_selected.emit(self.results_urls[idx])
                self.accept()

    def show_error(self, error_msg):
        self.progress.setVisible(False)
        self.search_btn.setEnabled(True)
        QMessageBox.warning(self, "Ошибка поиска", error_msg)