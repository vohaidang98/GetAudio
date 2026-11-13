import os
import sys
import threading
import subprocess
import json
import re
import time
import queue
import concurrent.futures
import shutil
import unicodedata
from urllib.parse import parse_qs, urlsplit
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLineEdit, QPlainTextEdit, QPushButton, QComboBox, QLabel, QProgressBar, QFileDialog,
                             QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QGridLayout,
                             QGroupBox, QAbstractItemView, QButtonGroup, QMessageBox, QInputDialog)
from PyQt6.QtCore import Qt, pyqtSignal, QSettings, QTimer
from PyQt6.QtGui import QColor, QBrush, QIcon, QPalette
import licensing
import updater

APP_VERSION = "4.2.1"


class ThemeModeControl(QWidget):
    """Compact segmented control for light, automatic, and dark themes."""

    mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("themeSelector")
        self.setAccessibleName("Chọn giao diện Sáng, Auto hoặc Tối")
        self.setToolTip("Chọn giao diện sáng, theo giao diện Windows, hoặc giao diện tối.")
        self._buttons = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        for mode, label in (("Sáng", "☀️ Sáng"), ("Auto", "🖥 Auto"), ("Tối", "🌙 Tối")):
            button = QPushButton(label, self)
            button.setObjectName("themeSegment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setAccessibleName(f"Giao diện {mode}")
            button.setMinimumHeight(28)
            self._group.addButton(button)
            self._buttons[mode] = button
            layout.addWidget(button)
            button.clicked.connect(lambda _checked=False, selected=mode: self.mode_changed.emit(selected))

    def set_mode(self, mode):
        button = self._buttons.get(mode)
        if button:
            button.setChecked(True)

class AudioDownloaderApp(QMainWindow):
    main_status_signal = pyqtSignal(str, str)
    button_signal = pyqtSignal(str) 
    worker_status_signal = pyqtSignal(int, str, str)
    worker_progress_signal = pyqtSignal(int, float)
    scan_done_signal = pyqtSignal(list, str)
    row_status_signal = pyqtSignal(str, str, str) 
    row_uncheck_signal = pyqtSignal(str)
    update_signal = pyqtSignal(object, bool)
    update_error_signal = pyqtSignal(str, bool)
    update_install_signal = pyqtSignal(str)

    COOKIES_AUTH_LABEL = "Dùng file cookies.txt (thư mục GetAudio)"
    AUDIO_MODE = "Audio gốc (MP3)"
    DUBBED_MODE = "Audio lồng tiếng (MP3)"
    VIDEO_MODE = "Tải Video MP4"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Youtube Multi-Language Pro Ver {APP_VERSION}")
        self.resize(1040, 840)
        self.setMinimumSize(900, 680)

        if getattr(sys, 'frozen', False):
            self.resource_path = sys._MEIPASS
            self.app_path = os.path.dirname(os.path.abspath(sys.executable))
            possible_project_path = os.path.dirname(self.app_path)
            self.project_path = (possible_project_path
                                 if os.path.isfile(os.path.join(possible_project_path, "app.py"))
                                 else None)
        else:
            self.resource_path = os.path.dirname(os.path.abspath(__file__))
            self.app_path = self.resource_path
            self.project_path = self.app_path

        # Keep base_path for compatibility with the existing app layout.
        self.base_path = self.resource_path
        self.settings = QSettings("GetAudio", "AudioDownloader")
        default_output_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.output_dir = str(self.settings.value("output_dir", default_output_dir) or default_output_dir)
        self.proxy_save_file = self.resolve_data_file("proxy.txt")
        self.cookies_file = self.resolve_data_file("cookies.txt")
        self.saved_proxy_text = str(self.settings.value("proxy", "") or "")
        
        icon_path = self.get_bin_path("icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.ytdlp_path = self.get_bin_path("yt-dlp.exe")
        self.ffmpeg_path = self.get_bin_path("ffmpeg.exe")
        
        self.is_stopped = False
        self.active_processes = set()
        self.process_lock = threading.Lock()
        self.url_queue = queue.Queue()
        self.active_workers_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.last_download_error = ""
        self.total_videos = 0
        self.reserved_filenames = set() 

        self.video_quality_heights = {
            "Tốt nhất có sẵn": None,
            "2160p (4K)": 2160,
            "1440p (2K)": 1440,
            "1080p": 1080,
            "720p": 720,
            "480p": 480,
            "360p": 360,
            "144p": 144,
        }

        self.language_map = {
            "Tiếng Anh (English)": ["en", "english", "anh"],
            "Tiếng Tây Ban Nha (Spanish)": ["es", "spanish", "español", "tây ban nha"],
            "Tiếng Bồ Đào Nha (Portuguese)": ["pt", "portuguese", "português", "bồ đào nha", "br"],
            "Tiếng Việt (Vietnamese)": ["vi", "vietnamese", "việt"],
        }

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget(self)
        central_widget.setObjectName("appRoot")
        self.root_widget = central_widget
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("GetAudio")
        title.setObjectName("heroTitle")
        header.addWidget(title, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()

        saved_theme_mode = str(self.settings.value("theme", "Sáng") or "Sáng")
        self.theme_mode = saved_theme_mode if saved_theme_mode in ("Sáng", "Auto", "Tối") else "Sáng"
        self.theme_name = self.resolve_theme_mode(self.theme_mode)
        self.theme_control = ThemeModeControl(self)
        self.theme_control.set_mode(self.theme_mode)
        self.theme_control.mode_changed.connect(self.set_theme_mode)
        header.addWidget(self.theme_control, alignment=Qt.AlignmentFlag.AlignVCenter)

        version_badge = QLabel(f"VER {APP_VERSION}")
        version_badge.setObjectName("versionBadge")
        header.addWidget(version_badge, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.update_button = QPushButton("Cập nhật")
        self.update_button.setToolTip("Kiểm tra bản cập nhật trên thư mục mạng LAN")
        self.update_button.clicked.connect(lambda: self.check_update(True))
        header.addWidget(self.update_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.updating = False
        self.update_signal.connect(self.offer_update)
        self.update_error_signal.connect(self.on_update_error)
        self.update_install_signal.connect(self.install_update)
        QTimer.singleShot(3000, lambda: self.check_update(False))
        layout.addLayout(header)

        source_group = QGroupBox("1.  Nguồn video")
        source_layout = QVBoxLayout(source_group)
        source_layout.setContentsMargins(10, 12, 10, 9)
        source_layout.setSpacing(0)

        self.url_input = QPlainTextEdit(self)
        self.url_input.setPlaceholderText(
            "Dán link video, kênh hoặc playlist; ngăn cách bằng dấu phẩy hoặc xuống dòng")
        self.url_input.setMinimumHeight(88)
        self.url_input.setMaximumHeight(140)
        self.url_input.setToolTip(
            "Có thể dán nhiều link trên một dòng, phân cách bằng dấu phẩy, hoặc mỗi link một dòng.")
        source_layout.addWidget(self.url_input)
        layout.addWidget(source_group)

        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)

        output_group = QGroupBox("2.  Thiết lập tải")
        output_grid = QGridLayout(output_group)
        output_grid.setContentsMargins(10, 12, 10, 9)
        output_grid.setHorizontalSpacing(8)
        output_grid.setVerticalSpacing(8)
        output_grid.setColumnStretch(1, 1)
        output_grid.setColumnStretch(3, 1)

        output_grid.addWidget(QLabel("Định dạng"), 0, 0)
        self.combo_media = QComboBox(self)
        self.combo_media.addItems([self.AUDIO_MODE, self.DUBBED_MODE, self.VIDEO_MODE])
        output_grid.addWidget(self.combo_media, 0, 1)

        output_grid.addWidget(QLabel("Độ phân giải"), 0, 2)
        self.combo_video_quality = QComboBox(self)
        self.combo_video_quality.addItems(list(self.video_quality_heights.keys()))
        self.combo_video_quality.setCurrentText("1080p")
        self.combo_video_quality.setToolTip(
            "Nếu video không có mức đã chọn, yt-dlp sẽ chọn mức thấp hơn phù hợp.")
        output_grid.addWidget(self.combo_video_quality, 0, 3)

        output_grid.addWidget(QLabel("Ngôn ngữ lồng tiếng"), 1, 0)
        self.combo_lang = QComboBox(self)
        self.combo_lang.addItems(list(self.language_map.keys()))
        output_grid.addWidget(self.combo_lang, 1, 1)

        output_grid.addWidget(QLabel("Chất lượng MP3"), 1, 2)
        self.combo_quality = QComboBox(self)
        self.combo_quality.addItems(["Tiêu chuẩn (Mặc định)", "Cao nhất (320kbps)"])
        output_grid.addWidget(self.combo_quality, 1, 3)

        output_grid.addWidget(QLabel("Lưu tại"), 2, 0)
        self.path_input = QLineEdit(self)
        self.path_input.setText(self.output_dir)
        self.path_input.setClearButtonEnabled(True)
        self.path_input.setToolTip("Thư mục chứa các file MP3 hoặc MP4 sau khi tải.")
        output_grid.addWidget(self.path_input, 2, 1)

        self.btn_browse = QPushButton("Chọn thư mục")
        self.btn_browse.clicked.connect(self.browse_folder)
        output_grid.addWidget(self.btn_browse, 2, 2)

        self.btn_clean_trash = QPushButton("Dọn file tạm")
        self.btn_clean_trash.setProperty("role", "subtle")
        self.btn_clean_trash.setToolTip("Xóa các tệp tải tạm .part và .ytdl trong thư mục lưu.")
        self.btn_clean_trash.clicked.connect(self.manual_clean_trash)
        output_grid.addWidget(self.btn_clean_trash, 2, 3)

        connection_group = QGroupBox("Kết nối & xác thực")
        connection_layout = QGridLayout(connection_group)
        connection_layout.setContentsMargins(10, 12, 10, 9)
        connection_layout.setHorizontalSpacing(7)
        connection_layout.setVerticalSpacing(6)
        connection_layout.setColumnStretch(0, 1)

        connection_layout.addWidget(QLabel("Proxy (không bắt buộc)"), 0, 0, 1, 3)
        self.proxy_input = QComboBox(self)
        self.proxy_input.setEditable(True)
        self.proxy_input.setToolTip(
            "Chọn proxy đã lưu hoặc nhập proxy mới có dạng giao thức://máy-chủ:cổng.")

        proxies = ["(Không dùng Proxy)"]
        if os.path.exists(self.proxy_save_file):
            try:
                with open(self.proxy_save_file, "r", encoding="utf-8") as f:
                    saved_proxies = [line.strip() for line in f.readlines() if line.strip()]
                    for proxy in saved_proxies:
                        if proxy not in proxies:
                            proxies.append(proxy)
            except Exception:
                pass

        self.proxy_input.addItems(proxies)
        if len(proxies) > 1:
            self.proxy_input.setCurrentIndex(1)
        if self.saved_proxy_text:
            self.proxy_input.setCurrentText(self.saved_proxy_text)
        connection_layout.addWidget(self.proxy_input, 1, 0, 1, 3)

        self.btn_save_proxy = QPushButton("Lưu proxy")
        self.btn_save_proxy.setProperty("role", "subtle")
        self.btn_save_proxy.clicked.connect(self.save_proxy)
        self.btn_delete_proxy = QPushButton("Xóa proxy")
        self.btn_delete_proxy.setProperty("role", "subtle")
        self.btn_delete_proxy.clicked.connect(self.delete_proxy)
        connection_layout.addWidget(self.btn_save_proxy, 2, 0)
        connection_layout.addWidget(self.btn_delete_proxy, 2, 1, 1, 2)

        connection_layout.addWidget(QLabel("Xác thực (video giới hạn tuổi)"), 3, 0, 1, 3)
        self.combo_auth = QComboBox(self)
        self.combo_auth.addItems([
            self.COOKIES_AUTH_LABEL,
            "Tự động lấy từ Microsoft Edge (Khuyên dùng)",
            "Tự động lấy từ Google Chrome",
            "Tự động lấy từ Firefox",
            "Không xác thực (Sẽ lỗi nếu video 18+)"
        ])
        self.combo_auth.setToolTip(f"Tệp cookie: {self.cookies_file}")
        connection_layout.addWidget(self.combo_auth, 4, 0, 1, 3)

        settings_row.addWidget(output_group, 3)
        settings_row.addWidget(connection_group, 2)
        layout.addLayout(settings_row)

        for combo, setting_name in (
                (self.combo_auth, "auth_mode"),
                (self.combo_lang, "language"),
                (self.combo_quality, "quality"),
                (self.combo_media, "media_mode"),
                (self.combo_video_quality, "video_quality")):
            saved_value = str(self.settings.value(setting_name, "") or "")
            saved_index = combo.findText(saved_value)
            if saved_index >= 0:
                combo.setCurrentIndex(saved_index)
        for combo, popup_width in (
                (self.combo_media, 190),
                (self.combo_video_quality, 170),
                (self.combo_lang, 260),
                (self.combo_quality, 230),
                (self.proxy_input, 360),
                (self.combo_auth, 380)):
            combo.setMinimumHeight(36)
            combo.view().setMinimumWidth(popup_width)
        self.combo_media.currentTextChanged.connect(self.update_media_controls)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)

        self.btn_update = QPushButton("Cập nhật yt-dlp")
        self.btn_update.setProperty("role", "subtle")
        self.btn_update.setToolTip("Cập nhật lõi yt-dlp lên phiên bản mới.")
        self.btn_update.clicked.connect(self.start_update_thread)

        self.btn_scan = QPushButton("1. Quét link")
        self.btn_scan.setProperty("role", "primary")
        self.btn_scan.clicked.connect(self.start_scan_thread)

        self.btn_download = QPushButton("2. Bắt đầu tải")
        self.btn_download.setProperty("role", "success")
        self.btn_download.clicked.connect(self.start_download_thread)

        self.btn_retry = QPushButton("3. Tải lại lỗi")
        self.btn_retry.setProperty("role", "warning")
        self.btn_retry.clicked.connect(self.retry_failed_links)

        self.btn_stop = QPushButton("Dừng tải")
        self.btn_stop.setProperty("role", "danger")
        self.btn_stop.clicked.connect(self.stop_download)
        self.btn_stop.setEnabled(False)

        action_layout.addWidget(self.btn_update, 1)
        action_layout.addWidget(self.btn_scan, 1)
        action_layout.addWidget(self.btn_download, 2)
        action_layout.addWidget(self.btn_retry, 1)
        action_layout.addWidget(self.btn_stop, 1)
        layout.addLayout(action_layout)

        list_group = QGroupBox("3.  Danh sách video")
        list_layout = QVBoxLayout(list_group)
        list_layout.setContentsMargins(10, 12, 10, 9)
        list_layout.setSpacing(8)

        control_layout = QHBoxLayout()
        self.queue_summary_label = QLabel("0 video  ·  0 đã chọn")
        self.queue_summary_label.setObjectName("queueSummary")
        control_layout.addWidget(self.queue_summary_label)
        control_layout.addStretch()

        self.chk_select_all = QCheckBox("Chọn / Bỏ chọn tất cả")
        self.chk_select_all.setChecked(True)
        self.chk_select_all.stateChanged.connect(self.toggle_select_all)
        control_layout.addWidget(self.chk_select_all)

        self.btn_select_error = QPushButton("Chọn video lỗi")
        self.btn_select_error.setProperty("role", "warning")
        self.btn_select_error.clicked.connect(self.select_only_errors)
        control_layout.addWidget(self.btn_select_error)

        self.btn_delete_selected = QPushButton("Xóa khỏi danh sách")
        self.btn_delete_selected.setProperty("role", "subtle")
        self.btn_delete_selected.clicked.connect(self.delete_selected_rows)
        control_layout.addWidget(self.btn_delete_selected)
        list_layout.addLayout(control_layout)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Chọn", "Video", "Trạng thái"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 54)
        self.table.setColumnWidth(2, 250)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(180)
        self.table.itemChanged.connect(self.update_queue_summary)
        list_layout.addWidget(self.table)
        layout.addWidget(list_group, 1)

        progress_group = QGroupBox("4.  Tiến độ xử lý")
        progress_layout = QGridLayout(progress_group)
        progress_layout.setContentsMargins(10, 12, 10, 9)
        progress_layout.setHorizontalSpacing(12)
        progress_layout.setVerticalSpacing(7)

        self.worker_labels = []
        self.worker_bars = []
        self.worker_status_colors = []
        for i in range(3):
            worker_panel = QWidget(progress_group)
            worker_panel_layout = QVBoxLayout(worker_panel)
            worker_panel_layout.setContentsMargins(0, 0, 0, 0)
            worker_panel_layout.setSpacing(4)

            label = QLabel(f"Luồng {i + 1}: Đang nghỉ...")
            label.setObjectName("workerStatus")
            label.setMinimumWidth(0)
            progress_bar = QProgressBar(worker_panel)
            progress_bar.setValue(0)
            progress_bar.setTextVisible(False)
            progress_bar.setFixedHeight(10)

            worker_panel_layout.addWidget(label)
            worker_panel_layout.addWidget(progress_bar)
            progress_layout.addWidget(worker_panel, 0, i)
            self.worker_labels.append(label)
            self.worker_bars.append(progress_bar)
            self.worker_status_colors.append("#757575")

        for column in range(3):
            progress_layout.setColumnStretch(column, 1)

        self.main_status_raw_color = "cyan"
        self.main_status_label = QLabel(
            f"Sẵn sàng! Lõi yt-dlp đang dùng: {os.path.basename(self.ytdlp_path)}")
        self.main_status_label.setObjectName("mainStatus")
        self.main_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_status_label.setWordWrap(True)
        self.main_status_label.setMinimumHeight(32)
        self.main_status_label.setToolTip(self.main_status_label.text())
        progress_layout.addWidget(self.main_status_label, 1, 0, 1, 3)
        layout.addWidget(progress_group)

        self.main_status_signal.connect(self.update_main_status)
        self.button_signal.connect(self.toggle_buttons)
        self.worker_status_signal.connect(self.update_worker_status)
        self.worker_progress_signal.connect(self.update_worker_progress)
        self.scan_done_signal.connect(self.populate_table)
        self.row_status_signal.connect(self.update_row_status)
        self.row_uncheck_signal.connect(self.uncheck_row)
        self.update_media_controls()
        self.update_queue_summary()
        self.apply_theme(self.theme_name)

        app = QApplication.instance()
        if app and hasattr(app, "paletteChanged"):
            app.paletteChanged.connect(self.on_system_palette_changed)

    def apply_theme(self, theme=None):
        if theme not in ("Sáng", "Tối"):
            theme = getattr(self, "theme_name", "Sáng")
        self.theme_name = theme

        if theme == "Tối":
            palette = {
                "window": "#0B1220",
                "card": "#121C2D",
                "input": "#182438",
                "text": "#E2E8F0",
                "muted": "#94A3B8",
                "border": "#2B3A52",
                "focus": "#60A5FA",
                "accent": "#3B82F6",
                "accent_hover": "#2563EB",
                "accent_soft": "#172F50",
                "accent_text": "#BFDBFE",
                "success": "#16A34A",
                "success_hover": "#15803D",
                "warning_bg": "#3A2915",
                "warning_text": "#FDBA74",
                "warning_border": "#8A4B1C",
                "danger": "#DC2626",
                "danger_hover": "#B91C1C",
                "table_alt": "#172338",
                "table_header": "#1B2940",
                "selection": "#1E3A5F",
                "selection_text": "#DBEAFE",
                "status_bg": "#1B2940",
                "progress_bg": "#26354B",
            }
        else:
            palette = {
                "window": "#F3F6FB",
                "card": "#FFFFFF",
                "input": "#FFFFFF",
                "text": "#1E293B",
                "muted": "#64748B",
                "border": "#DCE4EF",
                "focus": "#3B82F6",
                "accent": "#2563EB",
                "accent_hover": "#1D4ED8",
                "accent_soft": "#DBEAFE",
                "accent_text": "#1D4ED8",
                "success": "#15803D",
                "success_hover": "#166534",
                "warning_bg": "#FFF7ED",
                "warning_text": "#C2410C",
                "warning_border": "#FDBA74",
                "danger": "#DC2626",
                "danger_hover": "#B91C1C",
                "table_alt": "#F8FAFC",
                "table_header": "#F1F5F9",
                "selection": "#DBEAFE",
                "selection_text": "#0F172A",
                "status_bg": "#F8FAFC",
                "progress_bg": "#E8EEF6",
            }

        self.theme_palette = palette
        arrow_file = "dropdown-arrow-dark.svg" if theme == "Tối" else "dropdown-arrow-light.svg"
        arrow_path = self.get_bin_path(arrow_file).replace("\\", "/")
        self.root_widget.setStyleSheet(f"""
            QWidget {{ font-family: "Segoe UI"; font-size: 9.5pt; color: {palette["text"]}; }}
            QWidget#appRoot {{ background: {palette["window"]}; }}
            QGroupBox {{
                background: {palette["card"]}; color: {palette["text"]};
                border: 1px solid {palette["border"]}; border-radius: 12px;
                margin-top: 11px; padding: 13px 12px 11px 12px; font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 12px; padding: 0 5px;
                color: {palette["accent_text"]}; background: {palette["card"]};
            }}
            QLineEdit, QPlainTextEdit, QComboBox {{
                background: {palette["input"]}; color: {palette["text"]};
                border: 1px solid {palette["border"]}; border-radius: 8px;
                padding: 7px 10px; min-height: 22px;
                selection-background-color: {palette["selection"]};
                selection-color: {palette["selection_text"]};
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {palette["focus"]}; }}
            QComboBox::drop-down {{
                subcontrol-origin: padding; subcontrol-position: top right; width: 25px;
                border-left: 1px solid {palette["border"]}; background: {palette["table_header"]};
                border-top-right-radius: 7px; border-bottom-right-radius: 7px;
            }}
            QComboBox::down-arrow {{ image: url("{arrow_path}"); width: 12px; height: 8px; }}
            QComboBox::down-arrow:on {{ position: relative; top: 1px; }}
            QComboBox QAbstractItemView {{
                background: {palette["card"]}; color: {palette["text"]};
                border: 1px solid {palette["border"]};
                selection-background-color: {palette["selection"]};
                selection-color: {palette["selection_text"]}; padding: 4px;
            }}
            QPushButton {{
                background: {palette["card"]}; color: {palette["text"]};
                border: 1px solid {palette["border"]}; border-radius: 8px;
                padding: 8px 12px; min-height: 22px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {palette["table_header"]}; border-color: {palette["muted"]}; }}
            QPushButton:focus {{ border-color: {palette["focus"]}; }}
            QPushButton:pressed {{ background: {palette["selection"]}; }}
            QPushButton:disabled {{
                color: {palette["muted"]}; background: {palette["window"]}; border-color: {palette["border"]};
            }}
            QPushButton[role="primary"] {{
                background: {palette["accent"]}; color: #FFFFFF; border-color: {palette["accent"]};
            }}
            QPushButton[role="primary"]:hover {{ background: {palette["accent_hover"]}; }}
            QPushButton[role="success"] {{
                background: {palette["success"]}; color: #FFFFFF; border-color: {palette["success"]};
            }}
            QPushButton[role="success"]:hover {{ background: {palette["success_hover"]}; }}
            QPushButton[role="warning"] {{
                background: {palette["warning_bg"]}; color: {palette["warning_text"]};
                border-color: {palette["warning_border"]};
            }}
            QPushButton[role="danger"] {{
                background: {palette["danger"]}; color: #FFFFFF; border-color: {palette["danger"]};
            }}
            QPushButton[role="danger"]:hover {{ background: {palette["danger_hover"]}; }}
            QPushButton[role="subtle"] {{ color: {palette["muted"]}; }}
            QLabel#heroTitle {{ color: {palette["accent_text"]}; font-size: 21pt; font-weight: 700; }}
            QWidget#themeSelector {{
                background: {palette["table_header"]};
                border: 1px solid {palette["border"]}; border-radius: 9px;
            }}
            QPushButton#themeSegment {{
                background: transparent; color: {palette["muted"]};
                border: 1px solid transparent; border-radius: 6px;
                padding: 4px 9px; min-height: 20px; font-weight: 600;
            }}
            QPushButton#themeSegment:hover {{
                background: {palette["accent_soft"]}; color: {palette["accent_text"]};
            }}
            QPushButton#themeSegment:checked {{
                background: {palette["card"]}; color: {palette["accent_text"]};
                border-color: {palette["border"]}; font-weight: 700;
            }}
            QPushButton#themeSegment:focus {{ border-color: {palette["focus"]}; }}
            QLabel#versionBadge {{
                color: {palette["accent_text"]}; background: {palette["accent_soft"]};
                border-radius: 9px; padding: 5px 10px; font-weight: 700;
            }}
            QLabel#queueSummary {{ color: {palette["accent_text"]}; font-weight: 700; }}
            QLabel#workerStatus {{ font-weight: 600; }}
            QTableWidget {{
                background: {palette["card"]}; alternate-background-color: {palette["table_alt"]};
                color: {palette["text"]}; border: 1px solid {palette["border"]};
                border-radius: 7px; gridline-color: {palette["border"]};
                selection-background-color: {palette["selection"]};
                selection-color: {palette["selection_text"]};
            }}
            QHeaderView::section {{
                background: {palette["table_header"]}; color: {palette["muted"]};
                border: 0; border-bottom: 1px solid {palette["border"]};
                padding: 8px; font-weight: 700;
            }}
            QProgressBar {{
                background: {palette["progress_bg"]}; border: 0; border-radius: 5px;
                min-height: 10px; max-height: 10px;
            }}
            QProgressBar::chunk {{ background: {palette["accent"]}; border-radius: 5px; }}
            QCheckBox {{ spacing: 7px; color: {palette["text"]}; }}
            QCheckBox::indicator {{ width: 16px; height: 16px; }}
            QCheckBox::indicator:checked {{
                background: {palette["accent"]}; border: 1px solid {palette["accent"]}; border-radius: 4px;
            }}
        """)

        if hasattr(self, "main_status_label"):
            self.update_main_status(
                self.main_status_label.text(),
                getattr(self, "main_status_raw_color", "cyan"))
        for index, label in enumerate(getattr(self, "worker_labels", [])):
            raw_color = self.worker_status_colors[index]
            label.setStyleSheet(
                f"color: {self.theme_semantic_color(raw_color)}; font-weight: 600;")
        if hasattr(self, "table"):
            status_color_role = Qt.ItemDataRole.UserRole + 1
            for row in range(self.table.rowCount()):
                status_item = self.table.item(row, 2)
                if status_item:
                    raw_color = status_item.data(status_color_role)
                    if raw_color:
                        status_item.setForeground(
                            QBrush(QColor(self.theme_semantic_color(raw_color))))

    def theme_semantic_color(self, color):
        palette = getattr(self, "theme_palette", {})
        normalized = str(color).lower()
        if normalized in ("red", "#d32f2f", "#e53935"):
            return "#F87171" if self.theme_name == "Tối" else "#B91C1C"
        if normalized in ("green", "#2e7d32", "#15803d"):
            return "#4ADE80" if self.theme_name == "Tối" else "#15803D"
        if normalized in ("orange", "#ffa000", "#f57c00"):
            return "#FBBF24" if self.theme_name == "Tối" else "#B45309"
        if normalized in ("cyan", "#1e88e5", "#1976d2"):
            return "#60A5FA" if self.theme_name == "Tối" else "#1D4ED8"
        if normalized in ("#757575", "#64748b"):
            return palette.get("muted", "#64748B")
        return color

    def resolve_theme_mode(self, mode):
        if mode in ("Sáng", "Tối"):
            return mode

        try:
            import winreg
            personalize_key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, personalize_key) as key:
                use_light_theme, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "Sáng" if int(use_light_theme) else "Tối"
        except (ImportError, OSError, ValueError, TypeError):
            app = QApplication.instance()
            system_palette = app.palette() if app else QPalette()
            window_color = system_palette.color(QPalette.ColorRole.Window)
            return "Tối" if window_color.lightness() < 128 else "Sáng"

    def on_system_palette_changed(self, _palette=None):
        if getattr(self, "theme_mode", None) == "Auto":
            self.apply_theme(self.resolve_theme_mode("Auto"))

    def set_theme_mode(self, mode):
        if mode not in ("Sáng", "Auto", "Tối"):
            return
        self.theme_mode = mode
        self.theme_control.set_mode(mode)
        self.apply_theme(self.resolve_theme_mode(mode))
        self.settings.setValue("theme", mode)
        self.settings.sync()

    def resolve_data_file(self, filename):
        search_dirs = [self.app_path]
        if self.project_path and self.project_path not in search_dirs:
            search_dirs.append(self.project_path)
        legacy_dir = r"C:\GetAudio"
        if legacy_dir not in search_dirs:
            search_dirs.append(legacy_dir)

        for directory in search_dirs:
            candidate = os.path.abspath(os.path.join(directory, filename))
            if os.path.isfile(candidate):
                return candidate
        return os.path.abspath(os.path.join(self.app_path, filename))

    def get_bin_path(self, filename):
        search_dirs = [self.app_path]
        if self.project_path and self.project_path not in search_dirs:
            search_dirs.append(self.project_path)
        if self.resource_path not in search_dirs:
            search_dirs.append(self.resource_path)

        for directory in search_dirs:
            candidate = os.path.abspath(os.path.join(directory, filename))
            if os.path.isfile(candidate):
                return candidate
        return shutil.which(filename) or os.path.abspath(os.path.join(self.app_path, filename))

    @staticmethod
    def proxy_error(proxy):
        if not proxy:
            return ""
        try:
            parsed = urlsplit(proxy)
            if (parsed.scheme.lower() not in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}
                    or not parsed.hostname or parsed.port is None):
                return "Proxy cần có giao thức, máy chủ và cổng hợp lệ."
        except ValueError:
            return "Proxy không hợp lệ; hãy kiểm tra địa chỉ và cổng."
        return ""

    def save_settings(self):
        if not hasattr(self, "path_input"):
            return
        self.settings.setValue("output_dir", self.path_input.text().strip())
        self.settings.setValue("proxy", self.proxy_input.currentText().strip())
        self.settings.setValue("auth_mode", self.combo_auth.currentText())
        self.settings.setValue("language", self.combo_lang.currentText())
        self.settings.setValue("quality", self.combo_quality.currentText())
        self.settings.setValue("media_mode", self.combo_media.currentText())
        self.settings.setValue("video_quality", self.combo_video_quality.currentText())
        self.settings.setValue("theme", self.theme_name)
        self.settings.sync()

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu tệp tải xuống")
        if folder:
            self.output_dir = folder
            self.path_input.setText(folder)

    def manual_clean_trash(self):
        save_path = self.path_input.text().strip()
        if not os.path.exists(save_path):
            self.update_main_status("Thư mục lưu không tồn tại!", "red")
            return
            
        deleted = 0
        try:
            for file_name in os.listdir(save_path):
                if file_name.endswith('.ytdl') or file_name.endswith('.part') or '.part-Frag' in file_name:
                    file_path = os.path.join(save_path, file_name)
                    try:
                        os.remove(file_path)
                        deleted += 1
                    except OSError as cleanup_error:
                        self.update_main_status(
                            f"Không xóa được {file_name}: {cleanup_error}", "orange")
        except Exception as e:
            self.update_main_status(f"Lỗi khi dọn rác: {str(e)}", "red")
            return
            
        if deleted > 0:
            self.update_main_status(f"Đã dọn sạch {deleted} tệp rác tạm thời trong thư mục!", "green")
        else:
            self.update_main_status("Thư mục đã sạch sẽ, không có tệp rác nào!", "green")

    def update_main_status(self, text, color):
        self.main_status_label.setText(text)
        self.main_status_label.setToolTip(text)
        self.main_status_raw_color = color
        display_color = self.theme_semantic_color(color)
        status_bg = getattr(self, "theme_palette", {}).get("status_bg", "#F8FAFC")
        self.main_status_label.setStyleSheet(
            f"color: {display_color}; font-weight: 600; background: {status_bg}; "
            "padding: 7px 10px; border-radius: 7px;"
        )

    def update_queue_summary(self, *_args):
        if not hasattr(self, "table") or not hasattr(self, "queue_summary_label"):
            return
        total = self.table.rowCount()
        selected = sum(
            1 for row in range(total)
            if self.table.item(row, 0)
            and self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        )
        self.queue_summary_label.setText(f"{total} video  ·  {selected} đã chọn")

    def update_worker_status(self, worker_id, text, color):
        self.worker_labels[worker_id].setText(f"Luồng {worker_id+1}: {text}")
        self.worker_status_colors[worker_id] = color
        self.worker_labels[worker_id].setStyleSheet(
            f"color: {self.theme_semantic_color(color)}; font-weight: 600;")

    def update_worker_progress(self, worker_id, val):
        self.worker_bars[worker_id].setValue(int(val * 100))

    def toggle_buttons(self, state):
        busy = state != "idle"
        downloading = state == "downloading"

        for button in (self.btn_scan, self.btn_download, self.btn_retry, self.btn_update,
                       self.btn_save_proxy, self.btn_delete_proxy, self.btn_clean_trash,
                       self.btn_browse, self.chk_select_all, self.btn_select_error,
                       self.btn_delete_selected):
            button.setEnabled(not busy)

        self.btn_stop.setEnabled(downloading)
        self.table.setEnabled(not busy)
        for widget in (self.url_input, self.proxy_input, self.combo_auth, self.path_input,
                       self.combo_media):
            widget.setEnabled(not busy)
        self.update_media_controls(busy=busy)

    def update_media_controls(self, *_args, busy=None):
        if busy is None:
            busy = any(not button.isEnabled() for button in
                       (self.btn_scan, self.btn_download, self.btn_update))
        is_video = self.combo_media.currentText() == self.VIDEO_MODE
        self.combo_lang.setEnabled(not busy and self.combo_media.currentText() == self.DUBBED_MODE)
        self.combo_quality.setEnabled(not busy and not is_video)
        self.combo_video_quality.setEnabled(not busy and is_video)

    def toggle_select_all(self, state):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if state == Qt.CheckState.Checked.value else Qt.CheckState.Unchecked)

    def select_only_errors(self):
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, 0)
            status_item = self.table.item(row, 2)
            if chk_item and status_item:
                status_text = status_item.text().lower()
                if "lỗi" in status_text or "không có lồng tiếng" in status_text:
                    chk_item.setCheckState(Qt.CheckState.Checked)
                else:
                    chk_item.setCheckState(Qt.CheckState.Unchecked)

    def delete_selected_rows(self):
        deleted_count = 0
        for row in range(self.table.rowCount() - 1, -1, -1):
            chk_item = self.table.item(row, 0)
            if chk_item and chk_item.checkState() == Qt.CheckState.Checked:
                self.table.removeRow(row)
                deleted_count += 1
        
        if deleted_count > 0:
            self.update_queue_summary()
            self.update_main_status(f"Đã xóa {deleted_count} video khỏi danh sách.", "orange")
        else:
            self.update_main_status("Vui lòng tích chọn video muốn xóa!", "red")

    def update_row_status(self, url, text, color):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item and item.data(Qt.ItemDataRole.UserRole) == url:
                status_item = self.table.item(row, 2)
                if status_item:
                    status_item.setText(text)
                    status_item.setData(Qt.ItemDataRole.UserRole + 1, color)
                    status_item.setForeground(
                        QBrush(QColor(self.theme_semantic_color(color))))
                    status_item.setToolTip(self.download_error_guidance(text))
                break

    def uncheck_row(self, url):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item and item.data(Qt.ItemDataRole.UserRole) == url:
                chk_item = self.table.item(row, 0)
                if chk_item:
                    chk_item.setCheckState(Qt.CheckState.Unchecked)
                break

    def populate_table(self, videos, summary):
        existing_urls = set()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item:
                existing_urls.add(item.data(Qt.ItemDataRole.UserRole))
            
        added = 0
        for title, url in videos:
            if url not in existing_urls:
                row = self.table.rowCount()
                self.table.insertRow(row)
                
                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                chk_item.setCheckState(Qt.CheckState.Checked)
                self.table.setItem(row, 0, chk_item)
                
                title_item = QTableWidgetItem(title)
                title_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                title_item.setData(Qt.ItemDataRole.UserRole, url) 
                self.table.setItem(row, 1, title_item)
                
                status_item = QTableWidgetItem("Đang chờ...")
                status_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(row, 2, status_item)
                added += 1
                
        already_present = len(videos) - added
        self.update_queue_summary()
        status = f"{summary}. Đã thêm {added} video mới vào danh sách chờ"
        if already_present:
            status += f"; bỏ qua {already_present} video đã có"
        self.update_main_status(status + ".", "green")
        self.button_signal.emit("idle")

    def retry_failed_links(self):
        self.select_only_errors()
        
        has_error = False
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, 0)
            if chk_item and chk_item.checkState() == Qt.CheckState.Checked:
                has_error = True
                break
                
        if not has_error:
            self.update_main_status("Không tìm thấy video bị lỗi nào trong danh sách!", "orange")
            return
            
        self.start_download_thread()

    def stop_download(self):
        self.is_stopped = True
        self.update_main_status("Đang ép dừng quá trình tải...", "orange")
        self.btn_stop.setEnabled(False)
        with self.process_lock:
            for p in self.active_processes:
                try: p.kill()
                except OSError as kill_error:
                    self.update_main_status(f"Không dừng được tiến trình: {kill_error}", "orange")

    def save_proxy(self):
        current_proxy = self.proxy_input.currentText().strip()
        if not current_proxy or current_proxy == "(Không dùng Proxy)":
            self.update_main_status("Vui lòng nhập Proxy hợp lệ để lưu!", "orange")
            return
        proxy_issue = self.proxy_error(current_proxy)
        if proxy_issue:
            self.update_main_status(proxy_issue, "red")
            return

        try:
            os.makedirs(os.path.dirname(self.proxy_save_file), exist_ok=True)
            saved_proxies = []
            if os.path.exists(self.proxy_save_file):
                with open(self.proxy_save_file, "r", encoding="utf-8") as f:
                    saved_proxies = [line.strip() for line in f if line.strip()]

            if current_proxy in saved_proxies:
                self.update_main_status("Proxy này đã có trong danh sách!", "orange")
                return

            saved_proxies.append(current_proxy)
            with open(self.proxy_save_file, "w", encoding="utf-8") as f:
                f.write("\n".join(saved_proxies))
            self.proxy_input.addItem(current_proxy)
            self.proxy_input.setCurrentText(current_proxy)
            self.update_main_status("Đã thêm Proxy mới vào danh sách thành công!", "green")
        except Exception as e:
            self.update_main_status(f"Lỗi khi lưu Proxy: {str(e)}", "red")

    def delete_proxy(self):
        current_proxy = self.proxy_input.currentText().strip()
        if not current_proxy or current_proxy == "(Không dùng Proxy)":
            self.update_main_status("Không thể xóa tùy chọn mặc định hoặc rỗng!", "orange")
            return
            
        try:
            saved_proxies = []
            if os.path.exists(self.proxy_save_file):
                with open(self.proxy_save_file, "r", encoding="utf-8") as f:
                    saved_proxies = [line.strip() for line in f.readlines() if line.strip()]
            
            if current_proxy in saved_proxies:
                saved_proxies.remove(current_proxy)
                with open(self.proxy_save_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(saved_proxies))
                    
                index = self.proxy_input.findText(current_proxy)
                if index >= 0:
                    self.proxy_input.removeItem(index)
                self.proxy_input.setCurrentIndex(0)
                
                self.update_main_status(f"Đã xóa Proxy thành công!", "green")
            else:
                self.update_main_status("Proxy này không có trong danh sách đã lưu!", "orange")
        except Exception as e:
            self.update_main_status(f"Lỗi khi xóa Proxy: {str(e)}", "red")

    def start_update_thread(self):
        self.toggle_buttons("scanning")
        self.update_main_status("Đang cập nhật yt-dlp, vui lòng chờ...", "cyan")
        threading.Thread(target=self.process_update, daemon=True).start()
        
    def process_update(self):
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            ytdlp_path = self.ytdlp_path
            if (getattr(sys, 'frozen', False)
                    and os.path.dirname(os.path.abspath(ytdlp_path)).casefold()
                    == os.path.abspath(self.resource_path).casefold()):
                persistent_path = os.path.join(self.app_path, "yt-dlp.exe")
                if not os.path.isfile(persistent_path):
                    shutil.copy2(ytdlp_path, persistent_path)
                ytdlp_path = persistent_path
                self.ytdlp_path = persistent_path

            p = subprocess.Popen([ytdlp_path, "-U"], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 errors="replace", startupinfo=startupinfo)
            stdout, _ = p.communicate()
            if p.returncode == 0:
                self.main_status_signal.emit("Cập nhật yt-dlp hoàn tất.", "green")
            else:
                details = (stdout or "").strip()[-120:]
                self.main_status_signal.emit(f"Cập nhật thất bại: {details or 'không rõ nguyên nhân'}", "red")
        except Exception as e:
            self.main_status_signal.emit(f"Không thể cập nhật yt-dlp: {str(e)[:120]}", "red")
        self.button_signal.emit("idle")

    def extract_real_error(self, stderr_text):
        err_msg = ""
        for line in stderr_text.split('\n'):
            if 'ERROR:' in line: err_msg = line.strip()
        if not err_msg and stderr_text:
            err_msg = stderr_text.strip().split('\n')[-1]
        return err_msg if err_msg else "Lỗi không xác định từ hệ thống tải"

    def download_error_guidance(self, error_text):
        if "403" not in str(error_text):
            return str(error_text)
        return (
            f"{error_text}\n\n"
            "HTTP 403 nghĩa là máy chủ từ chối luồng tải. Hãy thử cập nhật yt-dlp, "
            "tắt Proxy rồi tải lại. Nếu cần dùng Proxy cùng cookies Firefox, hãy làm mới "
            "cookies trên cùng kết nối/IP với Proxy."
        )

    def record_download_failure(self, error_text=""):
        with self.process_lock:
            self.failure_count += 1
            if error_text:
                self.last_download_error = str(error_text)

    def auth_error(self, auth_mode):
        if auth_mode == self.COOKIES_AUTH_LABEL and not os.path.isfile(self.cookies_file):
            return f"Không tìm thấy cookies.txt tại: {self.cookies_file}"
        return ""

    def apply_auth_to_cmd(self, cmd_list, auth_mode):
        if auth_mode == "Tự động lấy từ Microsoft Edge (Khuyên dùng)":
            cmd_list.extend(["--cookies-from-browser", "edge"])
        elif auth_mode == "Tự động lấy từ Google Chrome":
            cmd_list.extend(["--cookies-from-browser", "chrome"])
        elif auth_mode == "Tự động lấy từ Firefox":
            cmd_list.extend(["--cookies-from-browser", "firefox"])
        elif auth_mode == self.COOKIES_AUTH_LABEL:
            cmd_list.extend(["--cookies", self.cookies_file])
        return cmd_list

    def start_scan_thread(self):
        raw_url_text = self.url_input.toPlainText().strip()
        urls = [part.strip() for line in raw_url_text.splitlines()
                for part in line.split(",") if part.strip()]
        if not urls:
            self.update_main_status("Vui lòng dán đường link vào ô trống!", "red")
            return
        if not os.path.isfile(self.ytdlp_path):
            self.update_main_status(f"Không tìm thấy yt-dlp.exe: {self.ytdlp_path}", "red")
            return

        proxy = self.proxy_input.currentText().strip()
        if proxy == "(Không dùng Proxy)":
            proxy = ""
        proxy_issue = self.proxy_error(proxy)
        if proxy_issue:
            self.update_main_status(proxy_issue, "red")
            return

        auth_mode = self.combo_auth.currentText()
        auth_issue = self.auth_error(auth_mode)
        if auth_issue:
            self.update_main_status(auth_issue, "red")
            return

        self.toggle_buttons("scanning")
        threading.Thread(target=self.scan_thread_func, args=(urls, proxy, auth_mode), daemon=True).start()

    def scan_thread_func(self, input_urls, proxy, auth_mode):
        self.main_status_signal.emit("Đang quét tiêu đề và link video...", "orange")
        final_videos = []
        failed_sources = 0
        last_error = ""
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        for url in input_urls:
            cmd_scan = [self.ytdlp_path, "--flat-playlist", "-j", "--no-warnings"]
            if proxy:
                cmd_scan.extend(["--proxy", proxy])
            cmd_scan = self.apply_auth_to_cmd(cmd_scan, auth_mode)
            cmd_scan.append(url)

            try:
                process = subprocess.Popen(cmd_scan, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, startupinfo=startupinfo, encoding="utf-8",
                                           errors="replace")
                stdout, stderr = process.communicate()
                records_before = len(final_videos)
                if process.returncode == 0 and stdout.strip():
                    for line in stdout.splitlines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        video_id = data.get("id")
                        if video_id:
                            title = str(data.get("title") or f"Video {video_id}")
                            final_videos.append((title, f"https://www.youtube.com/watch?v={video_id}"))
                if process.returncode != 0 or len(final_videos) == records_before:
                    failed_sources += 1
                    last_error = self.extract_real_error(stderr)
            except Exception as e:
                failed_sources += 1
                last_error = str(e)

        seen = set()
        unique_videos = []
        for title, url in final_videos:
            if url not in seen:
                seen.add(url)
                unique_videos.append((title, url))

        if not unique_videos:
            message = "Không tìm thấy video hợp lệ. Hãy kiểm tra link, proxy và xác thực."
            if last_error:
                safe_error = last_error.replace(proxy, "[proxy]") if proxy else last_error
                message += f" Lỗi gần nhất: {safe_error[:140]}"
            self.main_status_signal.emit(message, "red")
            self.button_signal.emit("idle")
            return

        summary = f"Quét xong: tìm thấy {len(unique_videos)} video"
        if failed_sources:
            summary += f"; {failed_sources} nguồn không quét được"
        self.scan_done_signal.emit(unique_videos, summary)

    def start_download_thread(self):
        selected_rows = []
        for row in range(self.table.rowCount()):
            check_item = self.table.item(row, 0)
            title_item = self.table.item(row, 1)
            if (check_item and title_item
                    and check_item.checkState() == Qt.CheckState.Checked):
                url = title_item.data(Qt.ItemDataRole.UserRole)
                if url:
                    selected_rows.append((url, self.table.item(row, 2)))

        if not selected_rows:
            self.update_main_status("Vui lòng tích chọn ít nhất 1 video để tải!", "red")
            return

        save_path = os.path.expandvars(os.path.expanduser(self.path_input.text().strip()))
        if not save_path:
            self.update_main_status("Vui lòng chọn thư mục lưu!", "red")
            return
        try:
            os.makedirs(save_path, exist_ok=True)
            if not os.path.isdir(save_path):
                raise OSError("Đường dẫn không phải là thư mục.")
        except OSError as e:
            self.update_main_status(f"Không thể tạo thư mục lưu: {str(e)}", "red")
            return

        if not os.path.isfile(self.ytdlp_path):
            self.update_main_status(f"Không tìm thấy yt-dlp.exe: {self.ytdlp_path}", "red")
            return
        if not os.path.isfile(self.ffmpeg_path):
            self.update_main_status(f"Không tìm thấy ffmpeg.exe: {self.ffmpeg_path}", "red")
            return

        proxy = self.proxy_input.currentText().strip()
        if proxy == "(Không dùng Proxy)":
            proxy = ""
        proxy_issue = self.proxy_error(proxy)
        if proxy_issue:
            self.update_main_status(proxy_issue, "red")
            return

        lang = self.combo_lang.currentText()
        auth_mode = self.combo_auth.currentText()
        auth_issue = self.auth_error(auth_mode)
        if auth_issue:
            self.update_main_status(auth_issue, "red")
            return
        audio_quality = self.combo_quality.currentText()
        media_type = self.combo_media.currentText()
        video_quality = self.combo_video_quality.currentText()

        urls_to_download = []
        for url, status_item in selected_rows:
            urls_to_download.append(url)
            if status_item:
                status_item.setText("Đang chờ...")
                status_item.setForeground(QBrush(QColor("black")))
                status_item.setToolTip("")

        self.output_dir = save_path
        self.is_stopped = False
        self.success_count = 0
        self.failure_count = 0
        self.last_download_error = ""
        self.active_processes.clear()
        self.reserved_filenames.clear()

        for i in range(3):
            self.update_worker_status(i, "Đang đợi lệnh...", "#757575")
            self.update_worker_progress(i, 0)

        self.toggle_buttons("downloading")
        self.total_videos = len(urls_to_download)
        self.update_main_status(f"Đang tiến hành tải: Thành công 0/{self.total_videos} video đã chọn...", "cyan")
        threading.Thread(target=self.process_batch,
                         args=(urls_to_download, save_path, lang, proxy, auth_mode,
                               audio_quality, media_type, video_quality),
                         daemon=True).start()

    def clean_trash_files(self, save_path):
        try:
            for file_name in os.listdir(save_path):
                if file_name.endswith('.ytdl') or file_name.endswith('.part') or '.part-Frag' in file_name:
                    file_path = os.path.join(save_path, file_name)
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass  # File tạm đang bị yt-dlp giữ — lần dọn sau sẽ xóa được
        except OSError:
            pass  # Thư mục lưu không đọc được — không ảnh hưởng luồng tải chính

    def process_batch(self, urls, save_path, lang_display, proxy, auth_mode,
                      audio_quality, media_type, video_quality):
        with self.url_queue.mutex:
            self.url_queue.queue.clear()
        for url in urls:
            self.url_queue.put(url)
            
        self.active_workers_count = min(3, self.total_videos)
        
        for worker_id in range(self.active_workers_count):
            threading.Thread(target=self.worker_task,
                             args=(worker_id, save_path, lang_display, proxy, auth_mode,
                                   audio_quality, media_type, video_quality),
                             daemon=True).start()

    @staticmethod
    def language_tokens(value):
        normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
        ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
        return re.findall(r"[a-z0-9]+", ascii_text)

    def format_matches_language(self, format_info, target_kws):
        short_codes = {self.language_tokens(alias)[0]
                       for alias in target_kws
                       if len(self.language_tokens(alias)) == 1
                       and len(self.language_tokens(alias)[0]) <= 2}
        fields = [format_info.get("language"), format_info.get("format_note"),
                  format_info.get("format_id")]
        token_fields = [self.language_tokens(value) for value in fields]
        for tokens in token_fields:
            if short_codes.intersection(tokens):
                return True

        aliases = [self.language_tokens(alias) for alias in target_kws
                   if len(self.language_tokens(alias)) > 2]
        for tokens in token_fields:
            for alias_tokens in aliases:
                size = len(alias_tokens)
                if any(tokens[index:index + size] == alias_tokens
                       for index in range(len(tokens) - size + 1)):
                    return True
        return False

    def video_format_selector(self, quality):
        max_height = self.video_quality_heights.get(quality)
        if max_height is None:
            return "bestvideo+bestaudio/best"
        return f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]"

    @staticmethod
    def is_original_audio(format_info):
        note = str(format_info.get("format_note") or "").casefold()
        return "original" in note or format_info.get("language_preference") == 10

    def choose_original_audio_format(self, info):
        formats = [f for f in info.get("formats", [])
                   if f.get("acodec") not in (None, "none") and self.is_original_audio(f)]
        if not formats:
            return "bestaudio/best"
        return self.choose_audio_format({"formats": formats}, None)

    def choose_audio_format(self, info, target_kws):
        candidates = []
        original_languages = {
            str(f.get("language") or "").lower().split("-")[0]
            for f in info.get("formats", []) if self.is_original_audio(f) and f.get("language")
        }
        for format_info in info.get("formats", []):
            codec = str(format_info.get("acodec") or "").lower()
            if not codec or codec == "none":
                continue
            if target_kws is not None:
                if not self.format_matches_language(format_info, target_kws) or self.is_original_audio(format_info):
                    continue
                note = str(format_info.get("format_note") or "").casefold()
                language = str(format_info.get("language") or "").lower().split("-")[0]
                explicit_dub = "dubbed" in note or "dub" in self.language_tokens(note)
                separate_language = bool(language and original_languages and language not in original_languages)
                if not (explicit_dub or separate_language):
                    continue
            try:
                bitrate = float(format_info.get("abr") or format_info.get("tbr") or 0)
            except (TypeError, ValueError):
                bitrate = 0
            audio_only = str(format_info.get("vcodec") or "").lower() == "none"
            format_id = format_info.get("format_id")
            if format_id is not None:
                candidates.append((audio_only, bitrate, str(format_id)))
        if not candidates:
            return None
        return max(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]

    @staticmethod
    def video_label(url):
        try:
            parsed = urlsplit(url)
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            if not video_id:
                video_id = parsed.path.rstrip("/").split("/")[-1]
            return str(video_id or parsed.hostname or url)[:24]
        except Exception:
            return str(url)[:24]

    def worker_task(self, worker_id, save_path, lang_display, proxy, auth_mode,
                    audio_quality, media_type, video_quality):
        target_kws = self.language_map[lang_display]
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        current_proxy = proxy

        while not self.is_stopped:
            try:
                url = self.url_queue.get_nowait()
            except queue.Empty:
                break 

            vid_id = self.video_label(url)
            self.row_status_signal.emit(url, "Đang chuẩn bị tải...", "#1E88E5")
            self.worker_status_signal.emit(worker_id, f"Xử lý: {vid_id}", "#1E88E5")
            self.worker_progress_signal.emit(worker_id, 0.0)

            cmd_info = [self.ytdlp_path, "-J", "--no-warnings"]
            if current_proxy: cmd_info.extend(["--proxy", current_proxy])
            cmd_info = self.apply_auth_to_cmd(cmd_info, auth_mode)
            cmd_info.append(url)

            try:
                process = subprocess.Popen(cmd_info, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo, encoding='utf-8', errors='ignore')
                with self.process_lock: self.active_processes.add(process)
                stdout, stderr = process.communicate()
                with self.process_lock: self.active_processes.discard(process)

                if self.is_stopped: break

                if process.returncode != 0:
                    real_err = self.extract_real_error(stderr)
                    self.record_download_failure(real_err)
                    self.row_status_signal.emit(url, f"Lỗi quét: {real_err}", "red")
                    self.url_queue.task_done()
                    continue
                    
                info = json.loads(stdout)
                vid_id = str(info.get("id") or vid_id)
            except Exception as e:
                self.record_download_failure(str(e))
                self.row_status_signal.emit(url, f"Lỗi hệ thống: {str(e)}", "red")
                self.url_queue.task_done()
                continue

            raw_title = str(info.get("title") or f"Video_{vid_id}")
            safe_title = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "_", raw_title).strip(" .")
            safe_title = safe_title[:150].rstrip(" .") or f"Video_{vid_id}"
            reserved_names = {"CON", "PRN", "AUX", "NUL"}
            reserved_names.update(f"COM{i}" for i in range(1, 10))
            reserved_names.update(f"LPT{i}" for i in range(1, 10))
            if safe_title.split(".", 1)[0].upper() in reserved_names:
                safe_title = f"_{safe_title}"
            is_video = media_type == self.VIDEO_MODE
            base_name = safe_title if is_video else f"{safe_title} [{lang_display if media_type == self.DUBBED_MODE else 'Audio gốc'}]"
            
            with self.process_lock:
                final_name = base_name
                counter = 1
                output_extensions = ("mp4",) if is_video else ("mp3",)
                existing_output = any(os.path.exists(os.path.join(save_path, f"{final_name}.{extension}"))
                                      for extension in output_extensions)
                while existing_output or final_name.casefold() in self.reserved_filenames:
                    final_name = f"{base_name} ({counter})"
                    counter += 1
                    existing_output = any(os.path.exists(os.path.join(save_path, f"{final_name}.{extension}"))
                                          for extension in output_extensions)
                self.reserved_filenames.add(final_name.casefold())
            
            template_name = final_name.replace('%', '%%')
            output_template = os.path.join(save_path, f"{template_name}.%(ext)s")

            if is_video:
                found_id = self.video_format_selector(video_quality)
            elif media_type == self.AUDIO_MODE:
                found_id = self.choose_original_audio_format(info)
            else:
                found_id = self.choose_audio_format(info, target_kws)

            if not found_id:
                error_text = f"Không có lồng tiếng {lang_display}"
                self.record_download_failure(error_text)
                self.row_status_signal.emit(url, error_text, "red")
                self.url_queue.task_done()
                continue

            self.row_status_signal.emit(
                url,
                f"Đang tải video ({video_quality})..." if is_video else "Đang tải audio...",
                "#FFA000")

            cmd_dl = [
                self.ytdlp_path, "-f", str(found_id), "-o", output_template,
                "--ffmpeg-location", self.ffmpeg_path, "-N", "4", "--newline"
            ]
            if is_video:
                cmd_dl.extend(["--merge-output-format", "mp4", "--remux-video", "mp4",
                               "--embed-metadata"])
            else:
                cmd_dl.extend(["-x", "--audio-format", "mp3", "--embed-metadata"])
                if "Cao nhất" in audio_quality:
                    cmd_dl.extend(["--audio-quality", "320K"])
                
            if current_proxy: cmd_dl.extend(["--proxy", current_proxy])
            cmd_dl = self.apply_auth_to_cmd(cmd_dl, auth_mode)
            cmd_dl.append(url)

            try:
                process_dl = subprocess.Popen(cmd_dl, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, startupinfo=startupinfo, encoding='utf-8', errors='ignore')
                with self.process_lock: self.active_processes.add(process_dl)
                
                dl_error_log = ""
                for line in process_dl.stdout:
                    dl_error_log = (dl_error_log + line)[-16000:]
                    if self.is_stopped:
                        process_dl.kill()
                        break
                    
                    if (not is_video
                            and ("[ExtractAudio]" in line
                                 or ("Destination:" in line and ".mp3" in line))):
                        self.row_status_signal.emit(url, "Đang chuyển đổi MP3 (Vui lòng đợi)...", "#FF8F00")
                    elif is_video and ("[Merger]" in line or "[VideoRemuxer]" in line):
                        self.row_status_signal.emit(url, "Đang ghép video MP4 (Vui lòng đợi)...", "#FF8F00")
                        
                    match = re.search(r'\[download\]\s+([\d\.]+)%', line)
                    if match:
                        pct = float(match.group(1)) / 100.0
                        self.worker_progress_signal.emit(worker_id, pct)
                        
                        if pct >= 1.0:
                            if is_video:
                                status_text = "Đang hoàn tất video MP4 (Vui lòng đợi)..."
                            else:
                                status_text = "Đang chuyển đổi MP3 (Vui lòng đợi)..."
                            self.row_status_signal.emit(url, status_text, "#FF8F00")
                        
                process_dl.wait()
                with self.process_lock: self.active_processes.discard(process_dl)

                if self.is_stopped: break
                    
                if process_dl.returncode == 0:
                    with self.process_lock: 
                        self.success_count += 1
                        curr_success = self.success_count
                        
                    self.row_status_signal.emit(url, "Tải thành công!", "green")
                    self.row_uncheck_signal.emit(url)
                    
                    self.worker_status_signal.emit(worker_id, f"{vid_id} Xong!", "green")
                    self.main_status_signal.emit(f"Đang tiến hành tải: Thành công {curr_success}/{self.total_videos} video...", "cyan")
                else:
                    real_err = self.extract_real_error(dl_error_log)
                    self.record_download_failure(real_err)
                    self.row_status_signal.emit(url, f"Lỗi tải: {real_err}", "red")
            except Exception as e:
                self.record_download_failure(str(e))
                self.row_status_signal.emit(url, f"Lỗi tiến trình: {str(e)}", "red")
                
            self.url_queue.task_done()

        self.worker_status_signal.emit(worker_id, "Xong việc, đang nghỉ...", "#757575")
        self.worker_progress_signal.emit(worker_id, 0.0)
        
        with self.process_lock:
            self.active_workers_count -= 1
            if self.active_workers_count == 0:
                # Keep partial downloads so yt-dlp can resume them on retry.
                if self.is_stopped:
                    summary = (f"Đã hủy: thành công {self.success_count}/{self.total_videos}, "
                               f"lỗi {self.failure_count}.")
                    self.main_status_signal.emit(summary, "orange")
                elif self.failure_count:
                    summary = (f"Hoàn tất: thành công {self.success_count}/{self.total_videos}, "
                               f"lỗi {self.failure_count}.")
                    if "403" in self.last_download_error:
                        summary += " Cập nhật yt-dlp hoặc thử tắt Proxy; rê chuột lên dòng lỗi để xem thêm."
                    else:
                        summary += " Rê chuột lên dòng lỗi để xem chi tiết."
                    self.main_status_signal.emit(summary, "orange")
                else:
                    self.main_status_signal.emit(
                        f"Hoàn tất: tải thành công {self.success_count}/{self.total_videos} video.",
                        "green")
                self.button_signal.emit("idle")

    # ---- Cập nhật qua GitHub Releases (chỉ bản đã kích hoạt) ----
    def check_update(self, manual):
        if self.updating:
            return
        if not licensing.is_activated():
            if manual:
                QMessageBox.information(self, "GetAudio", "Chỉ bản đã kích hoạt mới cập nhật được.")
            return
        self.updating = True

        def work():
            try:
                self.update_signal.emit(updater.check_latest(APP_VERSION), manual)
            except Exception as exc:
                self.update_error_signal.emit(str(exc), manual)
        threading.Thread(target=work, daemon=True).start()

    def offer_update(self, info, manual):
        if not info:
            self.updating = False
            if manual:
                QMessageBox.information(self, "GetAudio", f"Bạn đang dùng bản mới nhất ({APP_VERSION}).")
            return
        notes = str(info.get("notes", "")).strip()[:600]
        answer = QMessageBox.question(
            self, "GetAudio",
            f"Có bản mới {info['version']} (đang dùng {APP_VERSION}).\n\n{notes}\n\nCập nhật ngay? Đang tải dở sẽ bị dừng.")
        if answer != QMessageBox.StandardButton.Yes:
            self.updating = False
            return
        self.main_status_signal.emit(f"Đang tải bản {info['version']}...", "cyan")

        def work():
            try:
                last = [-1]

                def progress(p):
                    if int(p) // 10 != last[0]:
                        last[0] = int(p) // 10
                        self.main_status_signal.emit(f"Đang tải bản cập nhật... {int(p)}%", "cyan")
                self.update_install_signal.emit(updater.download(info, progress))
            except Exception as exc:
                self.update_error_signal.emit(str(exc), True)
        threading.Thread(target=work, daemon=True).start()

    def on_update_error(self, message, manual):
        self.updating = False
        if not manual:
            return
        QMessageBox.warning(self, "GetAudio", f"Không cập nhật được:\n{message}")

    def install_update(self, path):
        try:
            updater.install(path)
        except Exception as exc:
            self.on_update_error(str(exc), True)
            return
        QApplication.quit()


def ensure_activated():
    """Bắt buộc nhập đúng mã kích hoạt (hiện dấu *) trước khi dùng app."""
    while not licensing.is_activated():
        code, ok = QInputDialog.getText(None, "Kích hoạt GetAudio", "Nhập mã kích hoạt để sử dụng GetAudio:",
                                        QLineEdit.EchoMode.Password)
        if not ok:
            return False
        if licensing.activate(code):
            QMessageBox.information(None, "GetAudio", "Kích hoạt thành công.")
        else:
            QMessageBox.warning(None, "GetAudio", "Mã không đúng. Hãy thử lại.")
    return True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if not ensure_activated():
        sys.exit(0)
    window = AudioDownloaderApp()
    window.show()
    sys.exit(app.exec())
