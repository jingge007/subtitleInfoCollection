from __future__ import annotations

import base64
import logging
import ctypes
import os
import shutil
import time
import winsound
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPainter, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit as QtTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    FluentIcon as FIF,
    FluentWindow,
    HeaderCardWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    NavigationItemPosition,
    PrimaryPushButton,
    ProgressRing,
    PushButton,
    SearchLineEdit,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TransparentToolButton,
    setTheme,
    setThemeColor,
    Theme,
)

from ..config import AppSettings, bootstrap_env_file, evaluate_config
from ..engines.subtitle_engine import MIN_VALID_SUBTITLE_BYTES
from ..models import TaskConfig
from ..storage import AppStorage
from .styles import (
    GLOBAL_QSS,
    LOG_STYLE,
    SURFACE,
    LINE_SOFT,
    TEXT,
    TEXT_MUTED,
    TEXT_SOFT,
    TEXT_PLACEHOLDER,
    PRIMARY,
    PRIMARY_SOFT,
    GREEN,
    GREEN_SOFT,
    ORANGE,
    ORANGE_SOFT,
    RED,
    RED_SOFT,
)
from .worker import (
    AutomationScriptWorker,
    ClassicLinesAutomationWorker,
    CollectorWorker,
    ParserWorker,
)

logger = logging.getLogger(__name__)


DEFAULT_WINDOW_WIDTH = 1100
DEFAULT_WINDOW_HEIGHT = 580
PAGE_MARGINS = (18, 8, 18, 8)
PAGE_SPACING = 8
CARD_VIEW_MARGINS = (14, 6, 14, 10)
CARD_HEADER_MARGINS = (14, 8, 14, 0)


def _play_captcha_alert() -> None:
    """播放验证码提示音（Windows 系统感叹音）"""
    try:
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass


def _flash_taskbar(window_handle: int) -> None:
    """闪烁 Windows 任务栏图标以提醒用户"""
    try:
        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        FLASHW_ALL = 0x00000003  # 闪烁标题栏 + 任务栏按钮
        info = FLASHWINFO()
        info.cbSize = ctypes.sizeof(FLASHWINFO)
        info.hwnd = window_handle
        info.dwFlags = FLASHW_ALL
        info.uCount = 5       # 闪烁5次
        info.dwTimeout = 0    # 使用默认光标闪烁频率
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.env_bootstrap = bootstrap_env_file()
        self.settings = AppSettings.from_env(self.env_bootstrap.env_path)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage = AppStorage(self.settings.database_path)
        self.config_check = evaluate_config(self.settings, self.env_bootstrap.env_path)
        self.task_summary: dict = {}
        self.collector_worker: CollectorWorker | None = None
        self.parser_worker: ParserWorker | None = None
        self.automation_worker: AutomationScriptWorker | None = None
        self.classic_automation_worker: ClassicLinesAutomationWorker | None = None
        self.latest_classic_output_path: Path | None = None
        self.latest_classic_output_paths: list[Path] = []
        self.latest_automation_output_path: Path | None = None
        self.latest_automation_output_paths: list[Path] = []
        self._verification_dialog: QDialog | None = None
        self._verification_image_label: QLabel | None = None
        self._verification_refresh_btn: TransparentToolButton | None = None
        self._verification_code_input: LineEdit | None = None
        self._verification_ocr_label: CaptionLabel | None = None
        self._collect_elapsed_ms = 0
        self._collect_elapsed_running = False
        self._collect_elapsed_last_tick: float | None = None
        self._collect_paused = False
        self._collect_elapsed_timer = QTimer(self)
        self._collect_elapsed_timer.setInterval(1000)
        self._collect_elapsed_timer.timeout.connect(self._tick_collect_elapsed)

        self.setWindowTitle("字幕采集工具")
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self._set_app_icon()
        self._apply_theme()

        # 系统托盘图标（用于验证码最小化时的气泡通知）
        self._tray_icon = QSystemTrayIcon(self)
        tray_icon = self.windowIcon()
        if tray_icon.isNull():
            tray_icon = QIcon()
        self._tray_icon.setIcon(tray_icon)
        self._tray_icon.setToolTip("字幕采集工具")
        self._tray_icon.show()

        self._dashboard_page = self._build_task_center_page()
        self._collector_page = self._build_collector_tab()
        self._parser_page = self._build_parser_tab()
        self._automation_page = self._build_automation_tab()
        self._todays_lines_detail_page = self._automation_page
        self._classic_lines_page = self._build_classic_lines_page()
        self._script_center_page = self._build_script_center_page()
        self._config_page = self._build_config_page()
        self._history_page = self._build_history_tab()
        self._settings_page = self._build_settings_tab()

        self.addSubInterface(
            self._dashboard_page, FIF.HOME, "工作台", NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self._collector_page, FIF.CLOUD_DOWNLOAD, "采集任务", NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self._parser_page, FIF.DOCUMENT, "字幕解析", NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self._script_center_page, FIF.ROBOT, "脚本中心", NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self._todays_lines_detail_page, FIF.CALENDAR, "33台词今日台词", NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self._classic_lines_page, FIF.MOVIE, "33台词经典台词", NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self._config_page, FIF.GLOBE, "配置项", NavigationItemPosition.TOP,
        )
        self.addSubInterface(
            self._history_page, FIF.HISTORY, "历史记录", NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self._settings_page, FIF.SETTING, "设置与维护", NavigationItemPosition.BOTTOM,
        )

        self.setStyleSheet(GLOBAL_QSS)
        self.navigationInterface.setExpandWidth(200)
        self.refresh_history()
        self.refresh_task_center()

    def _set_app_icon(self) -> None:
        import sys as _sys

        candidates: list[Path] = []
        if getattr(_sys, "frozen", False):
            candidates.append(Path(_sys.executable).parent / "assets" / "head_logo.png")
            candidates.append(Path(_sys.executable).parent / "assets" / "head_logo.ico")
            candidates.append(Path(_sys.executable).parent / "_internal" / "assets" / "head_logo.png")
            candidates.append(Path(_sys.executable).parent / "_internal" / "assets" / "head_logo.ico")
        else:
            candidates.append(Path(__file__).resolve().parents[3] / "assets" / "head_logo.png")
            candidates.append(Path(__file__).resolve().parents[3] / "assets" / "head_logo.ico")
        for icon_path in candidates:
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
                return

    def _apply_theme(self) -> None:
        setTheme(Theme.LIGHT)
        setThemeColor(PRIMARY)

    def _card(self, title: str = "") -> HeaderCardWidget:
        card = HeaderCardWidget(self)
        if title:
            card.setTitle(title)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        card.headerLayout.setContentsMargins(*CARD_HEADER_MARGINS)
        card.viewLayout.setContentsMargins(*CARD_VIEW_MARGINS)
        card.viewLayout.setSpacing(PAGE_SPACING)
        return card

    def _page_layout(self, page: QWidget) -> QVBoxLayout:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(*PAGE_MARGINS)
        layout.setSpacing(PAGE_SPACING)
        return layout

    def _scroll_page(self, object_name: str) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        scroll_area = QScrollArea(self)
        scroll_area.setObjectName(object_name)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        content = QWidget()
        content.setObjectName(f"{object_name}Content")
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout = self._page_layout(content)
        scroll_area.setWidget(content)
        return scroll_area, content, layout

    def _metric_card(self, icon: FIF, label: str, color: str = PRIMARY) -> tuple[CardWidget, QLabel, QLabel]:
        card = CardWidget(self)
        card.setFixedHeight(52)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        icon_frame = QFrame()
        icon_frame.setFixedSize(36, 36)
        icon_frame.setStyleSheet(
            f"background: {color}15; border-radius: 10px;"
        )
        icon_layout = QVBoxLayout(icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_label = QLabel()
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignCenter)
        from PySide6.QtGui import QFont
        font = QFont()
        font.setPixelSize(18)
        icon_label.setFont(font)
        icon_map = {
            FIF.CALENDAR: "\U0001F4C5",
            FIF.MOVIE: "\U0001F3AC",
            FIF.CHECKBOX: "\u2705",
            FIF.CLOSE: "\u274C",
            FIF.DOWNLOAD: "\U0001F4E5",
        }
        icon_label.setText(icon_map.get(icon, "\U0001F4CA"))
        icon_layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        value = QLabel("0")
        value.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {TEXT};")
        caption = CaptionLabel(label)
        caption.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 12px;")
        text_col.addWidget(value)
        text_col.addWidget(caption)

        layout.addWidget(icon_frame)
        layout.addLayout(text_col, 1)
        return card, value, caption

    def _status_badge(self, text: str, ok: bool | None = True) -> QLabel:
        badge = QLabel(text)
        if ok is True:
            badge.setStyleSheet(
                f"background: {GREEN_SOFT}; color: {GREEN}; border-radius: 8px; "
                f"padding: 3px 10px; font-size: 12px; font-weight: 700;"
            )
        elif ok is False:
            badge.setStyleSheet(
                f"background: {ORANGE_SOFT}; color: {ORANGE}; border-radius: 8px; "
                f"padding: 3px 10px; font-size: 12px; font-weight: 700;"
            )
        else:
            badge.setStyleSheet(
                f"background: {PRIMARY_SOFT}; color: {PRIMARY}; border-radius: 8px; "
                f"padding: 3px 10px; font-size: 12px; font-weight: 700;"
            )
        return badge

    def _status_card(self, title: str, value: str, detail: str, ok: bool | None = True) -> CardWidget:
        card = CardWidget(self)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)
        heading = StrongBodyLabel(title)
        heading.setStyleSheet(f"font-size: 13px; color: {TEXT};")
        badge = self._status_badge(value, ok)
        body = CaptionLabel(detail)
        body.setWordWrap(True)
        body.setMinimumWidth(0)
        body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(heading)
        layout.addWidget(badge)
        layout.addWidget(body)
        return card

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _configure_table(self, table: QTableWidget) -> None:
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(32)
        table.horizontalHeader().setHighlightSections(False)

    def _configure_log_area(self, text_edit: QtTextEdit) -> None:
        text_edit.setReadOnly(True)
        text_edit.setObjectName("logArea")
        text_edit.setStyleSheet(LOG_STYLE)
        text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    # ── Dashboard Page ────────────────────────────────────────────────

    def _build_task_center_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("dashboardPage")
        layout = self._page_layout(page)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("任务工作台")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("集中查看字幕源状态、近期任务和输出位置")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        header_right = QHBoxLayout()
        header_right.setSpacing(10)
        self.dashboard_ready_label = QLabel()
        start_button = PrimaryPushButton("开始采集", self)
        start_button.setIcon(FIF.PLAY)
        start_button.clicked.connect(lambda: self.switchTo(self._collector_page))
        parse_button = PushButton("解析本地字幕", self)
        parse_button.setIcon(FIF.DOCUMENT)
        parse_button.clicked.connect(lambda: self.switchTo(self._parser_page))
        header_right.addWidget(self.dashboard_ready_label)
        header_right.addWidget(start_button)
        header_right.addWidget(parse_button)
        header.addLayout(header_right)

        self.metric_labels: dict[str, QLabel] = {}
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(10)
        metric_items = [
            ("runs", FIF.CALENDAR, "最近任务", PRIMARY),
            ("movies", FIF.MOVIE, "电影数", PRIMARY),
            ("best", FIF.CHECKBOX, "最佳字幕", GREEN),
            ("failed", FIF.CLOSE, "失败记录", RED),
            ("downloads", FIF.DOWNLOAD, "下载成功", GREEN),
        ]
        for key, icon, label, color in metric_items:
            card, value_label, _ = self._metric_card(icon, label, color)
            self.metric_labels[key] = value_label
            metrics_row.addWidget(card, 1)

        source_card = self._card("字幕源状态")
        self.source_status_layout = QHBoxLayout()
        self.source_status_layout.setSpacing(10)
        source_card.viewLayout.addLayout(self.source_status_layout)

        output_card = self._card("输出与维护")
        output_inner = QVBoxLayout()
        output_inner.setSpacing(10)
        self.latest_output_label = BodyLabel("暂无输出")
        self.latest_output_label.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 13px;")
        self.latest_output_label.setWordWrap(True)
        self.latest_output_label.setMinimumWidth(0)
        self.latest_output_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        output_actions = QHBoxLayout()
        output_actions.setSpacing(10)
        open_output = PushButton("打开最近输出", self)
        open_output.setIcon(FIF.FOLDER)
        open_output.clicked.connect(self.open_latest_output_dir)
        open_data = PushButton("数据目录", self)
        open_data.setIcon(FIF.FOLDER)
        open_data.clicked.connect(lambda: self.open_path(self._current_data_dir()))
        rerun_button = PushButton("复用最近任务", self)
        rerun_button.setIcon(FIF.SYNC)
        rerun_button.clicked.connect(self.prepare_latest_run)
        output_actions.addWidget(open_output)
        output_actions.addWidget(open_data)
        output_actions.addWidget(rerun_button)
        output_actions.addStretch(1)
        output_inner.addWidget(self.latest_output_label)
        output_inner.addLayout(output_actions)
        output_card.viewLayout.addLayout(output_inner)

        layout.addLayout(header)
        layout.addLayout(metrics_row)
        layout.addWidget(source_card, 1)
        layout.addWidget(output_card)
        return page

    # ── Dashboard Refresh ─────────────────────────────────────────────

    def refresh_task_center(self) -> None:
        if not hasattr(self, "source_status_layout"):
            return
        self.settings = AppSettings.from_env(self.env_bootstrap.env_path)
        self.config_check = evaluate_config(self.settings, self.env_bootstrap.env_path)
        self.task_summary = self.storage.task_center_summary()
        totals = self.task_summary.get("totals", {})
        for key, label in self.metric_labels.items():
            label.setText(str(totals.get(key, 0)))

        if self.config_check.ready:
            self.dashboard_ready_label = self._update_badge_label(
                self.dashboard_ready_label, "配置可用", True
            )
        else:
            self.dashboard_ready_label = self._update_badge_label(
                self.dashboard_ready_label, "配置待完善", False
            )

        self._refresh_source_status()

        package_path = self.task_summary.get("package_path") or ""
        self.latest_output_label.setText(package_path or f"数据目录：{self.settings.data_dir}")

        self.refresh_config_page()

    def _update_badge_label(self, label: QLabel, text: str, ok: bool | None = True) -> QLabel:
        label.setText(text)
        if ok is True:
            label.setStyleSheet(
                f"background: {GREEN_SOFT}; color: {GREEN}; border-radius: 8px; "
                f"padding: 4px 12px; font-size: 12px; font-weight: 700;"
            )
        elif ok is False:
            label.setStyleSheet(
                f"background: {ORANGE_SOFT}; color: {ORANGE}; border-radius: 8px; "
                f"padding: 4px 12px; font-size: 12px; font-weight: 700;"
            )
        else:
            label.setStyleSheet(
                f"background: {PRIMARY_SOFT}; color: {PRIMARY}; border-radius: 8px; "
                f"padding: 4px 12px; font-size: 12px; font-weight: 700;"
            )
        return label

    def _refresh_config_cards(self) -> None:
        self._clear_layout(self.config_cards_layout)
        cards = [
            self._status_card(
                ".env",
                "已创建" if self.config_check.env_exists else "未找到",
                str(self.config_check.env_path),
                self.config_check.env_exists,
            ),
            self._status_card(
                "TMDb",
                "已配置" if self.config_check.tmdb_configured else "缺少 Token",
                "电影榜单与本地字幕匹配",
                self.config_check.tmdb_configured,
            ),
            self._status_card(
                "数据目录",
                "可用" if self.config_check.data_dir_exists else "待创建",
                str(self.config_check.data_dir),
                self.config_check.data_dir_exists,
            ),
            self._status_card(
                "字幕源",
                f"{self.config_check.configured_provider_count}/{self.config_check.enabled_provider_count} 可用",
                "SubHD 无需 Token，ASSRT/OpenSubtitles 需要密钥",
                self.config_check.configured_provider_count > 0,
            ),
            self._status_card(
                "请求间隔",
                f"{self.config_check.request_interval_ms} ms",
                "已自动限制到安全下限",
                None,
            ),
            self._status_card(
                "电影并发",
                f"{self.config_check.movie_concurrency}",
                "SUBTITLE_MOVIE_CONCURRENCY（1～4）",
                None,
            ),
            self._status_card(
                "代理",
                "已启用" if self.config_check.proxies_configured else "未启用",
                "HTTP_PROXY / HTTPS_PROXY",
                None,
            ),
        ]
        for index, card in enumerate(cards):
            self.config_cards_layout.addWidget(card, index // 3, index % 3)

    def _refresh_latest_records(self) -> None:
        if not hasattr(self, "latest_records_layout"):
            return
        self._clear_layout(self.latest_records_layout)
        records = self.task_summary.get("latest_records") or []
        if not records:
            empty_widget = QWidget()
            empty_inner = QVBoxLayout(empty_widget)
            empty_inner.setContentsMargins(0, 16, 0, 16)
            empty_inner.setSpacing(8)
            empty_inner.setAlignment(Qt.AlignCenter)
            empty_icon = QLabel("\U0001F4ED")
            empty_icon.setAlignment(Qt.AlignCenter)
            from PySide6.QtGui import QFont
            font = QFont()
            font.setPixelSize(36)
            empty_icon.setFont(font)
            empty_text = BodyLabel("暂无字幕结果。完成一次采集后，这里会展示电影式资料卡。")
            empty_text.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 13px;")
            empty_text.setAlignment(Qt.AlignCenter)
            empty_text.setWordWrap(True)
            empty_inner.addWidget(empty_icon)
            empty_inner.addWidget(empty_text)
            self.latest_records_layout.addWidget(empty_widget, 1)
            return
        for record in records[:4]:
            card = CardWidget(self)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            card.setMinimumWidth(200)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 10, 14, 10)
            card_layout.setSpacing(4)
            title = StrongBodyLabel(record.get("movieTitleZh") or record.get("movieTitle") or "未命名电影")
            title.setStyleSheet(f"font-size: 14px; color: {TEXT};")
            title.setWordWrap(True)
            meta = CaptionLabel(f"{record.get('provider', '-')} · {record.get('totalScore', 0)}")
            meta.setStyleSheet(f"color: {TEXT_MUTED};")
            subtitle = CaptionLabel(record.get("subtitleTitle") or "字幕标题缺失")
            subtitle.setStyleSheet(f"color: {TEXT_SOFT};")
            subtitle.setWordWrap(True)
            card_layout.addWidget(title)
            card_layout.addWidget(meta)
            card_layout.addWidget(subtitle)
            self.latest_records_layout.addWidget(card)
        self.latest_records_layout.addStretch(1)

    def _refresh_source_status(self) -> None:
        self._clear_layout(self.source_status_layout)
        health = self.task_summary.get("source_health") or {}
        stats = self.task_summary.get("provider_stats") or {}
        for index, provider in enumerate(self.config_check.providers):
            provider_health = health.get(provider.id, {})
            provider_stats = stats.get(provider.id, {})
            if provider_health:
                healthy = bool(provider_health.get("healthy"))
                status = "健康" if healthy else "异常"
                ok = True if healthy else False
                detail = provider_health.get("message") or f"命中 {provider_stats.get('hitCount', 0)} 条"
            else:
                configured = provider.enabled and provider.configured
                status = "已配置" if configured else "待配置"
                ok = configured if configured else False
                detail = provider.detail
            self.source_status_layout.addWidget(
                self._status_card(provider.label, status, detail, ok),
            )

    # ── Config Page ────────────────────────────────────────────────────

    def _build_config_page(self) -> QWidget:
        page, _content, layout = self._scroll_page("configPage")

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("配置项")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("管理应用配置、环境变量和配置提示")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        layout.addLayout(header)

        config_card = self._card("配置预检")
        self.config_cards_layout = QGridLayout()
        self.config_cards_layout.setSpacing(PAGE_SPACING)
        config_card.viewLayout.addLayout(self.config_cards_layout)

        env_overview_card = self._card("环境概览")
        self.env_items_layout = QVBoxLayout()
        self.env_items_layout.setSpacing(6)
        env_overview_card.viewLayout.addLayout(self.env_items_layout)

        tips_card = self._card("配置提示")
        tips_inner = QVBoxLayout()
        tips_inner.setSpacing(6)
        tips_items = [
            (".env 密钥", "TMDB_TOKEN、ASSRT_TOKEN、OpenSubtitles 账号均不在界面编辑，请直接修改 .env 文件。"),
            ("代理与间隔", "HTTP_PROXY、HTTPS_PROXY、SUBTITLE_REQUEST_INTERVAL_MS 从 .env 读取。"),
            ("源优先级", "SUBTITLE_PROVIDER_PRIORITY / SUBTITLE_PROVIDER_DISABLED 从 .env 读取。"),
        ]
        for tip_title, tip_detail in tips_items:
            tip_row = QHBoxLayout()
            tip_row.setSpacing(10)
            tip_h = StrongBodyLabel(tip_title)
            tip_h.setFixedWidth(80)
            tip_d = CaptionLabel(tip_detail)
            tip_d.setWordWrap(True)
            tip_d.setMinimumWidth(0)
            tip_d.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            tip_row.addWidget(tip_h)
            tip_row.addWidget(tip_d, 1)
            tips_inner.addLayout(tip_row)
        tips_card.viewLayout.addLayout(tips_inner)

        overview_row = QHBoxLayout()
        overview_row.setSpacing(PAGE_SPACING)
        overview_row.addWidget(env_overview_card, 3)
        overview_row.addWidget(tips_card, 2)

        layout.addWidget(config_card)
        layout.addLayout(overview_row, 1)
        return page

    def refresh_config_page(self) -> None:
        if not hasattr(self, "config_cards_layout"):
            return
        self.settings = AppSettings.from_env(self.env_bootstrap.env_path)
        self.config_check = evaluate_config(self.settings, self.env_bootstrap.env_path)
        self._refresh_config_cards()
        self._refresh_env_table()

    def _refresh_env_table(self) -> None:
        self._clear_layout(self.env_items_layout)
        env_items = [
            ("TMDB_TOKEN", self.config_check.tmdb_configured, "电影榜单与本地字幕匹配"),
            ("ASSRT_TOKEN", bool(os.environ.get("ASSRT_TOKEN", "").strip()), "ASSRT 字幕源密钥"),
            ("OpenSubtitles", bool(os.environ.get("OPENSUBTITLES_API_KEY", "").strip()), "OpenSubtitles API 密钥"),
            ("HTTP_PROXY", bool(os.environ.get("HTTP_PROXY", "").strip() or os.environ.get("HTTPS_PROXY", "").strip()), "HTTP/HTTPS 代理"),
            ("请求间隔", True, f"{self.config_check.request_interval_ms} ms"),
            ("电影并发", True, f"{self.config_check.movie_concurrency}"),
        ]
        for name, configured, desc in env_items:
            row_widget = CardWidget(self)
            row_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row_widget.setFixedHeight(38)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(12, 6, 12, 6)
            row_layout.setSpacing(10)
            name_label = StrongBodyLabel(name)
            name_label.setFixedWidth(120)
            name_label.setStyleSheet(f"font-size: 13px; color: {TEXT};")
            badge = self._status_badge("已配置" if configured else "未配置", configured)
            desc_label = CaptionLabel(desc)
            desc_label.setStyleSheet(f"color: {TEXT_SOFT};")
            desc_label.setWordWrap(True)
            desc_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            row_layout.addWidget(name_label)
            row_layout.addWidget(badge)
            row_layout.addWidget(desc_label, 1)
            self.env_items_layout.addWidget(row_widget)

    # ── Path Helpers ──────────────────────────────────────────────────

    def open_path(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, "路径不存在", f"路径不存在：{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_latest_output_dir(self) -> None:
        package_path = self.task_summary.get("package_path") or ""
        if package_path:
            self.open_path(Path(package_path))
            return
        self.open_path(self.settings.data_dir)

    def prepare_latest_run(self) -> None:
        recent_runs = self.task_summary.get("recent_runs") or []
        if not recent_runs:
            QMessageBox.information(self, "暂无任务", "还没有可以复用的历史任务。")
            return
        latest = recent_runs[0]
        self.year_spin.setValue(int(latest.get("year") or self.year_spin.value()))
        self.limit_spin.setValue(int(latest.get("limit") or self.limit_spin.value()))
        self.switchTo(self._collector_page)

    # ── Collector Tab ─────────────────────────────────────────────────

    def _build_collector_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("collectorPage")
        layout = self._page_layout(page)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("采集任务")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("选择年份、Top 数量、字幕源和下载策略，运行采集工作流")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        self.start_button = PrimaryPushButton("开始采集", self)
        self.start_button.setIcon(FIF.PLAY)
        self.start_button.setFixedHeight(36)
        self.start_button.clicked.connect(self.start_collection)
        header.addWidget(self.start_button)
        self.pause_button = PushButton("暂停", self)
        self.pause_button.setIcon(FIF.PAUSE)
        self.pause_button.setFixedHeight(36)
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self.toggle_collect_pause)
        header.addWidget(self.pause_button)
        self.abort_button = PushButton("中止", self)
        self.abort_button.setIcon(FIF.CANCEL)
        self.abort_button.setFixedHeight(36)
        self.abort_button.setEnabled(False)
        self.abort_button.clicked.connect(self.abort_collection)
        header.addWidget(self.abort_button)

        params_card = self._card("采集参数")
        params_layout = QVBoxLayout()
        params_layout.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(12)
        year_label = StrongBodyLabel("年份")
        self.year_spin = SpinBox(self)
        self.year_spin.setRange(1900, datetime.now().year + 1)
        self.year_spin.setValue(datetime.now().year)
        self.year_spin.setFixedWidth(180)
        limit_label = StrongBodyLabel("Top 数量")
        self.limit_spin = SpinBox(self)
        self.limit_spin.setRange(1, 500)
        self.limit_spin.setValue(100)
        self.limit_spin.setFixedWidth(180)
        row1.addWidget(year_label)
        row1.addWidget(self.year_spin)
        row1.addSpacing(24)
        row1.addWidget(limit_label)
        row1.addWidget(self.limit_spin)
        row1.addStretch(1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        strategy_label = StrongBodyLabel("策略")
        self.fallback_check = CheckBox("源兜底", self)
        self.fallback_check.setChecked(False)
        self.download_check = CheckBox("下载字幕", self)
        self.download_check.setChecked(True)
        row2.addWidget(strategy_label)
        row2.addWidget(self.fallback_check)
        row2.addWidget(self.download_check)
        row2.addSpacing(24)
        source_label = StrongBodyLabel("字幕源")
        disabled_providers = set(self.settings.provider_disabled)
        self.subhd_check = CheckBox("SubHD", self)
        self.subdl_check = CheckBox("SubDL", self)
        self.assrt_check = CheckBox("ASSRT", self)
        self.opensubtitles_check = CheckBox("OpenSubtitles", self)
        provider_checks = {
            "subhd": self.subhd_check,
            "subdl": self.subdl_check,
            "assrt": self.assrt_check,
            "opensubtitles": self.opensubtitles_check,
        }
        for provider, checkbox in provider_checks.items():
            checkbox.setChecked(provider not in disabled_providers)
        row2.addWidget(source_label)
        row2.addWidget(self.subhd_check)
        row2.addWidget(self.subdl_check)
        row2.addWidget(self.assrt_check)
        row2.addWidget(self.opensubtitles_check)
        row2.addStretch(1)

        params_layout.addLayout(row1)
        params_layout.addLayout(row2)
        params_card.viewLayout.addLayout(params_layout)

        monitor_col = QVBoxLayout()
        monitor_col.setSpacing(8)

        status_card = self._card("任务状态")
        status_inner = QVBoxLayout()
        status_inner.setSpacing(8)

        progress_and_stats = QHBoxLayout()
        progress_and_stats.setSpacing(8)

        self.collect_progress_ring = ProgressRing(self)
        self.collect_progress_ring.setFixedSize(48, 48)
        self.collect_progress_ring.setRange(0, 100)
        self.collect_progress_ring.setValue(0)
        self.collect_progress_ring.setStrokeWidth(5)
        progress_info = QVBoxLayout()
        progress_info.setSpacing(3)
        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        self.collect_status = StrongBodyLabel("等待开始")
        self.collect_status.setStyleSheet(f"font-size: 15px; color: {TEXT};")
        self.collect_status.setWordWrap(True)
        self.collect_status.setMinimumWidth(200)
        self.collect_elapsed_label = StrongBodyLabel("耗时 00:00:00")
        self.collect_elapsed_label.setStyleSheet(f"font-size: 14px; color: {TEXT_SOFT};")
        self.collect_elapsed_label.setMinimumWidth(120)
        status_row.addWidget(self.collect_status, 1)
        status_row.addWidget(self.collect_elapsed_label, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.collect_progress_label = CaptionLabel("0%")
        self.collect_progress_label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 12px;")
        progress_info.addLayout(status_row)
        progress_info.addWidget(self.collect_progress_label)
        progress_info.addStretch(1)
        progress_panel = QWidget(self)
        progress_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        progress_panel_layout = QHBoxLayout(progress_panel)
        progress_panel_layout.setContentsMargins(0, 0, 0, 0)
        progress_panel_layout.setSpacing(10)
        progress_panel_layout.addWidget(self.collect_progress_ring)
        progress_panel_layout.addLayout(progress_info, 1)
        progress_and_stats.addWidget(progress_panel, 3)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(6)

        self.collect_stat_labels: dict[str, QLabel] = {}
        stat_items = [
            ("movies", "电影", PRIMARY, PRIMARY_SOFT),
            ("hits", "命中", GREEN, GREEN_SOFT),
            ("filtered", "过滤", ORANGE, ORANGE_SOFT),
            ("failed", "失败", RED, RED_SOFT),
            ("downloaded", "下载", GREEN, GREEN_SOFT),
        ]
        for key, label_text, color, bg_color in stat_items:
            stat_card = QFrame(self)
            stat_card.setStyleSheet(
                f"background: {bg_color}; border: 1px solid {LINE_SOFT}; border-radius: 8px;"
            )
            stat_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            stat_card.setFixedWidth(72)
            stat_card.setFixedHeight(48)
            stat_layout = QVBoxLayout(stat_card)
            stat_layout.setContentsMargins(8, 5, 8, 5)
            stat_layout.setSpacing(1)
            stat_layout.setAlignment(Qt.AlignCenter)
            value_label = QLabel("0")
            value_label.setAlignment(Qt.AlignCenter)
            value_label.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {color};")
            caption_label = QLabel(label_text)
            caption_label.setAlignment(Qt.AlignCenter)
            caption_label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 11px;")
            stat_layout.addWidget(value_label)
            stat_layout.addWidget(caption_label)
            self.collect_stat_labels[key] = value_label
            stats_row.addWidget(stat_card)

        progress_and_stats.addLayout(stats_row, 0)

        status_inner.addLayout(progress_and_stats)
        status_card.viewLayout.addLayout(status_inner)

        log_card = self._card("采集日志")
        self.copy_collect_log_button = TransparentToolButton(FIF.COPY, self)
        self.copy_collect_log_button.setFixedSize(28, 28)
        self.copy_collect_log_button.clicked.connect(self.copy_collect_log)
        log_card.headerLayout.addStretch(1)
        log_card.headerLayout.addWidget(self.copy_collect_log_button)

        self.collect_log = QtTextEdit(self)
        self._configure_log_area(self.collect_log)
        log_card.viewLayout.addWidget(self.collect_log)

        monitor_col.addWidget(status_card)
        monitor_col.addWidget(log_card, 1)

        layout.addLayout(header)
        layout.addWidget(params_card)
        layout.addLayout(monitor_col, 1)
        return page

    # ── Parser Tab ────────────────────────────────────────────────────

    def _build_parser_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("parserPage")
        layout = self._page_layout(page)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("字幕解析")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("选择本地 SRT/ASS 文件，解析双语字幕并导出电影 JSON 与字幕 JSON")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        layout.addLayout(header)

        action_card = self._card("文件选择")
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.parse_button = PrimaryPushButton("选择 SRT/ASS 文件", self)
        self.parse_button.setIcon(FIF.FOLDER_ADD)
        self.parse_button.clicked.connect(self.select_parse_files)
        self.parse_status = BodyLabel("等待文件")
        self.parse_status.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 13px;")
        actions.addWidget(self.parse_button)
        actions.addStretch(1)
        action_card.viewLayout.addLayout(actions)

        export_options = QHBoxLayout()
        export_options.setSpacing(10)
        export_text = QVBoxLayout()
        export_text.setSpacing(2)
        export_title = StrongBodyLabel("uniCloud 导入格式")
        export_desc = CaptionLabel("开启后字幕 JSON 使用控制台 jsonl 规格导出，并按 45MB 自动拆分")
        export_desc.setStyleSheet(f"color: {TEXT_PLACEHOLDER};")
        export_desc.setWordWrap(True)
        export_text.addWidget(export_title)
        export_text.addWidget(export_desc)
        self.unicloud_import_switch = SwitchButton(self)
        self.unicloud_import_switch.setObjectName("unicloudImportFormatSwitch")
        self.unicloud_import_switch.setOnText("开启")
        self.unicloud_import_switch.setOffText("关闭")
        self.unicloud_import_switch.setChecked(True)
        export_options.addLayout(export_text, 1)
        export_options.addWidget(self.unicloud_import_switch)
        action_card.viewLayout.addLayout(export_options)

        task_card = self._card("任务状态")
        task_inner = QVBoxLayout()
        task_inner.setSpacing(8)
        status_and_stats = QHBoxLayout()
        status_and_stats.setSpacing(8)

        self.parse_progress_ring = ProgressRing(self)
        self.parse_progress_ring.setFixedSize(48, 48)
        self.parse_progress_ring.setRange(0, 100)
        self.parse_progress_ring.setValue(0)
        self.parse_progress_ring.setStrokeWidth(5)

        parse_status_info = QVBoxLayout()
        parse_status_info.setSpacing(3)
        self.parse_progress_label = CaptionLabel("0%")
        self.parse_progress_label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 12px;")
        parse_status_info.addWidget(self.parse_status)
        parse_status_info.addWidget(self.parse_progress_label)
        parse_status_info.addStretch(1)

        status_panel = QWidget(self)
        status_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        status_panel_layout = QHBoxLayout(status_panel)
        status_panel_layout.setContentsMargins(0, 0, 0, 0)
        status_panel_layout.setSpacing(10)
        status_panel_layout.addWidget(self.parse_progress_ring)
        status_panel_layout.addLayout(parse_status_info, 1)
        status_and_stats.addWidget(status_panel, 3)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(6)
        self.parse_stat_labels: dict[str, QLabel] = {}
        for key, caption, color, bg_color, width in [
            ("total", "字幕文件", PRIMARY, PRIMARY_SOFT, 82),
            ("success", "成功", GREEN, GREEN_SOFT, 72),
            ("failed", "失败", RED, RED_SOFT, 72),
            ("exported", "导出条数", ORANGE, ORANGE_SOFT, 88),
        ]:
            stat = QFrame(self)
            stat.setStyleSheet(
                f"background: {bg_color}; border: 1px solid {LINE_SOFT}; border-radius: 8px;"
            )
            stat.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            stat.setFixedWidth(width)
            stat.setFixedHeight(48)
            stat_layout = QVBoxLayout(stat)
            stat_layout.setContentsMargins(8, 5, 8, 5)
            stat_layout.setSpacing(1)
            stat_layout.setAlignment(Qt.AlignCenter)
            value = QLabel("0")
            value.setAlignment(Qt.AlignCenter)
            value.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {color};")
            label = CaptionLabel(caption)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 11px;")
            stat_layout.addWidget(value)
            stat_layout.addWidget(label)
            self.parse_stat_labels[key] = value
            stats_row.addWidget(stat)
        status_and_stats.addLayout(stats_row, 0)
        task_inner.addLayout(status_and_stats)

        output_stat = QFrame(self)
        output_stat.setStyleSheet(
            f"background: {ORANGE_SOFT}; border: 1px solid {LINE_SOFT}; border-radius: 8px;"
        )
        output_stat.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        output_layout = QVBoxLayout(output_stat)
        output_layout.setContentsMargins(10, 6, 10, 6)
        output_layout.setSpacing(2)
        output_caption = CaptionLabel("输出文件")
        output_caption.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 11px;")
        output_value = QLabel("-")
        output_value.setWordWrap(True)
        output_value.setMinimumWidth(0)
        output_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        output_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        output_value.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {ORANGE};")
        output_layout.addWidget(output_caption)
        output_layout.addWidget(output_value)
        self.parse_stat_labels["output"] = output_value
        task_inner.addWidget(output_stat)
        task_card.viewLayout.addLayout(task_inner)

        log_card = self._card("解析日志")
        self.parse_log = QtTextEdit(self)
        self._configure_log_area(self.parse_log)
        log_card.viewLayout.addWidget(self.parse_log)

        layout.addWidget(action_card)
        layout.addWidget(task_card)
        layout.addWidget(log_card, 3)
        return page

    # ── History Tab ───────────────────────────────────────────────────


    # 构建脚本中心卡片概览页
    def _build_script_center_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("scriptCenterPage")
        layout = self._page_layout(page)
        layout.setAlignment(Qt.AlignTop)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("脚本中心")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("选择需要运行的自动化脚本")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        layout.addLayout(header)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        # 生成脚本中心入口卡片
        def _sc(icon_t, title_t, desc_t, status_fn, target):
            card = CardWidget(self)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            card.setFixedHeight(200)
            inner = QVBoxLayout(card)
            inner.setContentsMargins(16, 12, 16, 12)
            inner.setSpacing(6)
            il = StrongBodyLabel(icon_t)
            il.setStyleSheet("font-size: 28px;")
            inner.addWidget(il)
            inner.addWidget(StrongBodyLabel(title_t))
            d = BodyLabel(desc_t)
            d.setWordWrap(True)
            d.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
            inner.addWidget(d)
            s = CaptionLabel(status_fn())
            s.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 11px;")
            inner.addWidget(s)
            inner.addStretch(1)
            btn = PushButton("进入脚本", self)
            btn.setIcon(FIF.FOLDER)
            btn.clicked.connect(lambda checked=False, t=target: self.switchTo(t))
            inner.addWidget(btn)
            return card

        # 今日台词卡片状态文案
        def ts():
            if not self.latest_automation_output_paths:
                return "尚未运行"
            v = [p for p in self.latest_automation_output_paths if p.exists()]
            return f"上次运行: 输出 {len(v)} 个文件" if v else "已运行"

        # 经典台词卡片状态文案
        def cs():
            if not self.latest_classic_output_paths:
                return "尚未运行"
            v = [p for p in self.latest_classic_output_paths if p.exists()]
            return f"上次运行: 输出 {len(v)} 个文件" if v else "已运行"

        cards_row.addWidget(_sc(
            "📋", "33台词今日台词采集",
            "从 33 台词 API 实时采集每日台词对白",
            ts, self._todays_lines_detail_page,
        ), 1)
        cards_row.addWidget(_sc(
            "🎬", "33台词经典台词爬取",
            "从 33tc.net/lines 爬取影片经典对白",
            cs, self._classic_lines_page,
        ), 1)

        pc = CardWidget(self)
        pc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        pc.setFixedHeight(200)
        pi = QVBoxLayout(pc)
        pi.setContentsMargins(16, 12, 16, 12)
        pi.setAlignment(Qt.AlignCenter)
        p2 = StrongBodyLabel("+")
        p2.setStyleSheet(f"font-size: 32px; color: {TEXT_PLACEHOLDER};")
        pi.addWidget(p2, 0, Qt.AlignCenter)
        p3 = CaptionLabel("更多脚本待续")
        p3.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        pi.addWidget(p3, 0, Qt.AlignCenter)
        cards_row.addWidget(pc, 1)

        layout.addLayout(cards_row)
        layout.addStretch(1)
        return page

    # 构建经典台词采集详情页（布局对齐今日台词）
    def _build_classic_lines_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("classicLinesPage")
        layout = self._page_layout(page)

        header = QHBoxLayout()
        header.setSpacing(12)
        back_btn = PushButton("← 返回脚本中心", self)
        back_btn.clicked.connect(lambda: self.switchTo(self._script_center_page))
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("33台词经典台词采集")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("从 33tc.net/lines 爬取影片经典对白，约 1300 部电影 / 19000+ 句对白")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addWidget(back_btn)
        header.addLayout(title_col, 1)
        layout.addLayout(header)

        action_card = self._card("33 台词经典台词")
        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.classic_run_button = PrimaryPushButton("执行", self)
        self.classic_run_button.setIcon(FIF.PLAY)
        self.classic_run_button.clicked.connect(self.start_classic_automation)
        self.classic_open_button = PushButton("打开文件", self)
        self.classic_open_button.setIcon(FIF.FOLDER)
        self.classic_open_button.setEnabled(False)
        self.classic_open_button.clicked.connect(self.open_classic_output_file)
        self.classic_reset_button = PushButton("重置", self)
        self.classic_reset_button.setIcon(FIF.SYNC)
        self.classic_reset_button.clicked.connect(self.reset_classic_panel)
        self.classic_status = BodyLabel("等待执行")
        self.classic_status.setStyleSheet(f"font-size: 15px; color: {TEXT};")
        self.classic_status.setWordWrap(True)
        self.classic_status.setMinimumWidth(260)
        action_row.addWidget(self.classic_run_button)
        action_row.addWidget(self.classic_open_button)
        action_row.addWidget(self.classic_reset_button)
        action_row.addStretch(1)
        action_card.viewLayout.addLayout(action_row)

        export_options = QHBoxLayout()
        export_options.setSpacing(10)
        export_text = QVBoxLayout()
        export_text.setSpacing(2)
        export_title = StrongBodyLabel("uniCloud 控制台导入格式")
        export_desc = CaptionLabel("开启后按 jsonl 格式导出并按 45MB 拆分文件")
        export_desc.setStyleSheet(f"color: {TEXT_PLACEHOLDER};")
        export_desc.setWordWrap(True)
        export_text.addWidget(export_title)
        export_text.addWidget(export_desc)
        self.classic_unicloud_switch = SwitchButton(self)
        self.classic_unicloud_switch.setChecked(True)
        self.classic_unicloud_switch.setOnText("开启")
        self.classic_unicloud_switch.setOffText("关闭")
        export_options.addLayout(export_text, 1)
        export_options.addWidget(self.classic_unicloud_switch)
        action_card.viewLayout.addLayout(export_options)

        stats_card = self._card("任务状态")
        stats_inner = QVBoxLayout()
        stats_inner.setSpacing(8)

        status_and_stats = QHBoxLayout()
        status_and_stats.setSpacing(8)
        self.classic_progress_ring = ProgressRing(self)
        self.classic_progress_ring.setFixedSize(48, 48)
        self.classic_progress_ring.setRange(0, 100)
        self.classic_progress_ring.setValue(0)
        self.classic_progress_ring.setStrokeWidth(5)
        classic_status_info = QVBoxLayout()
        classic_status_info.setSpacing(3)
        self.classic_progress_label = CaptionLabel("0%")
        self.classic_progress_label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 12px;")
        classic_status_info.addWidget(self.classic_status)
        classic_status_info.addWidget(self.classic_progress_label)
        classic_status_info.addStretch(1)
        status_panel = QWidget(self)
        status_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        status_panel_layout = QHBoxLayout(status_panel)
        status_panel_layout.setContentsMargins(0, 0, 0, 0)
        status_panel_layout.setSpacing(10)
        status_panel_layout.addWidget(self.classic_progress_ring)
        status_panel_layout.addLayout(classic_status_info, 1)
        status_and_stats.addWidget(status_panel, 3)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(6)
        self.classic_stat_labels: dict[str, QLabel] = {}
        for key, caption, color, bg_color, width in [
            ("movies", "电影数", PRIMARY, PRIMARY_SOFT, 88),
            ("lines", "台词数", GREEN, GREEN_SOFT, 88),
            ("pages", "请求页数", ORANGE, ORANGE_SOFT, 88),
        ]:
            stat = QFrame(self)
            stat.setStyleSheet(
                f"background: {bg_color}; border: 1px solid {LINE_SOFT}; border-radius: 8px;"
            )
            stat.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            stat.setFixedWidth(width)
            stat.setFixedHeight(48)
            stat_layout = QVBoxLayout(stat)
            stat_layout.setContentsMargins(8, 5, 8, 5)
            stat_layout.setSpacing(1)
            stat_layout.setAlignment(Qt.AlignCenter)
            value = QLabel("0")
            value.setAlignment(Qt.AlignCenter)
            value.setWordWrap(True)
            value.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {color};")
            label = CaptionLabel(caption)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 11px;")
            stat_layout.addWidget(value)
            stat_layout.addWidget(label)
            self.classic_stat_labels[key] = value
            stats_row.addWidget(stat)
        status_and_stats.addLayout(stats_row, 0)
        stats_inner.addLayout(status_and_stats)

        output_stat = QFrame(self)
        output_stat.setStyleSheet(
            f"background: {ORANGE_SOFT}; border: 1px solid {LINE_SOFT}; border-radius: 8px;"
        )
        output_stat.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        output_layout = QVBoxLayout(output_stat)
        output_layout.setContentsMargins(8, 5, 8, 5)
        output_layout.setSpacing(1)
        output_value = QLabel("-")
        output_value.setAlignment(Qt.AlignCenter)
        output_value.setWordWrap(True)
        output_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        output_value.setMinimumWidth(0)
        output_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        output_value.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {ORANGE};")
        output_layout.addWidget(output_value)
        output_caption = CaptionLabel("输出文件")
        output_caption.setAlignment(Qt.AlignCenter)
        output_caption.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 11px;")
        output_layout.addWidget(output_caption)
        self.classic_stat_labels["output"] = output_value
        stats_inner.addWidget(output_stat)
        stats_card.viewLayout.addLayout(stats_inner)

        log_card = self._card("日志")
        self.classic_copy_log_button = TransparentToolButton(FIF.COPY, self)
        self.classic_copy_log_button.setFixedSize(28, 28)
        self.classic_copy_log_button.setToolTip("复制日志")
        self.classic_copy_log_button.clicked.connect(self.copy_classic_log)
        log_card.headerLayout.addStretch(1)
        log_card.headerLayout.addWidget(self.classic_copy_log_button)
        self.classic_log = QtTextEdit(self)
        self._configure_log_area(self.classic_log)
        log_card.viewLayout.addWidget(self.classic_log)

        layout.addWidget(action_card)
        layout.addWidget(stats_card)
        layout.addWidget(log_card, 1)
        return page

    # 构建今日台词采集详情页
    def _build_automation_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("automationPage")
        layout = self._page_layout(page)

        header = QHBoxLayout()
        header.setSpacing(12)
        back_btn = PushButton("← 返回脚本中心", self)
        back_btn.clicked.connect(lambda: self.switchTo(self._script_center_page))
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("33台词今日台词采集")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("从 33 台词 API 实时采集每日台词对白，结果保存到数据目录的 automation 文件夹")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addWidget(back_btn)
        header.addLayout(title_col, 1)
        layout.addLayout(header)

        action_card = self._card("33 台词今日台词")
        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.automation_run_button = PrimaryPushButton("执行", self)
        self.automation_run_button.setIcon(FIF.PLAY)
        self.automation_run_button.clicked.connect(self.start_automation_script)
        self.automation_open_button = PushButton("打开文件", self)
        self.automation_open_button.setIcon(FIF.FOLDER)
        self.automation_open_button.setEnabled(False)
        self.automation_open_button.clicked.connect(self.open_automation_output_file)
        self.automation_reset_button = PushButton("重置", self)
        self.automation_reset_button.setIcon(FIF.SYNC)
        self.automation_reset_button.clicked.connect(self.reset_automation_panel)
        self.automation_status = BodyLabel("等待执行")
        self.automation_status.setStyleSheet(f"font-size: 15px; color: {TEXT};")
        self.automation_status.setWordWrap(True)
        self.automation_status.setMinimumWidth(260)
        action_row.addWidget(self.automation_run_button)
        action_row.addWidget(self.automation_open_button)
        action_row.addWidget(self.automation_reset_button)
        action_row.addStretch(1)
        action_card.viewLayout.addLayout(action_row)
        export_options = QHBoxLayout()
        export_options.setSpacing(10)
        export_text = QVBoxLayout()
        export_text.setSpacing(2)
        export_title = StrongBodyLabel("uniCloud 控制台导入格式")
        export_desc = CaptionLabel("开启后按 todays-line 导入规则解析、翻译补全英文，并按 45MB 拆分 jsonl 文件")
        export_desc.setStyleSheet(f"color: {TEXT_PLACEHOLDER};")
        export_desc.setWordWrap(True)
        export_text.addWidget(export_title)
        export_text.addWidget(export_desc)
        self.automation_unicloud_import_switch = SwitchButton(self)
        self.automation_unicloud_import_switch.setObjectName("automationUnicloudImportFormatSwitch")
        self.automation_unicloud_import_switch.setOnText("开启")
        self.automation_unicloud_import_switch.setOffText("关闭")
        self.automation_unicloud_import_switch.setChecked(True)
        export_options.addLayout(export_text, 1)
        export_options.addWidget(self.automation_unicloud_import_switch)
        action_card.viewLayout.addLayout(export_options)

        stats_card = self._card("任务状态")
        stats_inner = QVBoxLayout()
        stats_inner.setSpacing(8)

        status_and_stats = QHBoxLayout()
        status_and_stats.setSpacing(8)

        self.automation_progress_ring = ProgressRing(self)
        self.automation_progress_ring.setFixedSize(48, 48)
        self.automation_progress_ring.setRange(0, 100)
        self.automation_progress_ring.setValue(0)
        self.automation_progress_ring.setStrokeWidth(5)
        automation_status_info = QVBoxLayout()
        automation_status_info.setSpacing(3)
        self.automation_progress_label = CaptionLabel("0%")
        self.automation_progress_label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 12px;")
        automation_status_info.addWidget(self.automation_status)
        automation_status_info.addWidget(self.automation_progress_label)
        automation_status_info.addStretch(1)
        status_panel = QWidget(self)
        status_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        status_panel_layout = QHBoxLayout(status_panel)
        status_panel_layout.setContentsMargins(0, 0, 0, 0)
        status_panel_layout.setSpacing(10)
        status_panel_layout.addWidget(self.automation_progress_ring)
        status_panel_layout.addLayout(automation_status_info, 1)
        status_and_stats.addWidget(status_panel, 3)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(6)
        self.automation_stat_labels: dict[str, QLabel] = {}
        for key, caption, color, bg_color, width in [
            ("total", "采集条数", GREEN, GREEN_SOFT, 88),
            ("pages", "请求页数", PRIMARY, PRIMARY_SOFT, 88),
        ]:
            stat = QFrame(self)
            stat.setStyleSheet(
                f"background: {bg_color}; border: 1px solid {LINE_SOFT}; border-radius: 8px;"
            )
            stat.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            stat.setFixedWidth(width)
            stat.setFixedHeight(48)
            stat_layout = QVBoxLayout(stat)
            stat_layout.setContentsMargins(8, 5, 8, 5)
            stat_layout.setSpacing(1)
            stat_layout.setAlignment(Qt.AlignCenter)
            value = QLabel("0")
            value.setAlignment(Qt.AlignCenter)
            value.setWordWrap(True)
            value.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {color};")
            label = CaptionLabel(caption)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 11px;")
            stat_layout.addWidget(value)
            stat_layout.addWidget(label)
            self.automation_stat_labels[key] = value
            stats_row.addWidget(stat)
        status_and_stats.addLayout(stats_row, 0)

        stats_inner.addLayout(status_and_stats)

        output_stat = QFrame(self)
        output_stat.setStyleSheet(
            f"background: {ORANGE_SOFT}; border: 1px solid {LINE_SOFT}; border-radius: 8px;"
        )
        output_stat.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        output_layout = QVBoxLayout(output_stat)
        output_layout.setContentsMargins(8, 5, 8, 5)
        output_layout.setSpacing(1)

        output_value = QLabel("-")
        output_value.setAlignment(Qt.AlignCenter)
        output_value.setWordWrap(True)
        output_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        output_value.setMinimumWidth(0)
        output_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        output_value.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {ORANGE};")
        output_layout.addWidget(output_value)

        output_caption = CaptionLabel("输出文件")
        output_caption.setAlignment(Qt.AlignCenter)
        output_caption.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 11px;")
        output_layout.addWidget(output_caption)

        self.automation_stat_labels["output"] = output_value
        stats_inner.addWidget(output_stat)

        stats_card.viewLayout.addLayout(stats_inner)

        log_card = self._card("日志")
        self.copy_automation_log_button = TransparentToolButton(FIF.COPY, self)
        self.copy_automation_log_button.setFixedSize(28, 28)
        self.copy_automation_log_button.setToolTip("复制日志")
        self.copy_automation_log_button.clicked.connect(self.copy_automation_log)
        log_card.headerLayout.addStretch(1)
        log_card.headerLayout.addWidget(self.copy_automation_log_button)

        self.automation_log = QtTextEdit(self)
        self._configure_log_area(self.automation_log)
        log_card.viewLayout.addWidget(self.automation_log)

        layout.addWidget(action_card)
        layout.addWidget(stats_card)
        layout.addWidget(log_card, 1)
        return page

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("historyPage")
        layout = self._page_layout(page)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("历史记录")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("查看最近采集任务状态、参数、开始结束时间和输出目录")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.history_search = SearchLineEdit(self)
        self.history_search.setPlaceholderText("搜索任务...")
        self.history_search.setFixedWidth(240)
        self.history_search.textChanged.connect(self._filter_history_table)
        refresh_button = PushButton("刷新历史", self)
        refresh_button.setIcon(FIF.SYNC)
        refresh_button.clicked.connect(self.refresh_history)
        toolbar.addWidget(self.history_search)
        toolbar.addStretch(1)
        toolbar.addWidget(refresh_button)

        table_card = self._card("任务列表")
        self.history_table = QTableWidget(0, 5, self)
        self.history_table.setObjectName("dataTable")
        self.history_table.setHorizontalHeaderLabels(
            ["年份", "Top", "开始时间", "结束时间", "输出目录"]
        )
        self._configure_table(self.history_table)
        for column in range(0, 4):
            self.history_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        table_card.viewLayout.addWidget(self.history_table)

        layout.addLayout(header)
        layout.addLayout(toolbar)
        layout.addWidget(table_card, 1)
        return page

    def _filter_history_table(self, filter_text: str = "") -> None:
        query = (filter_text or self.history_search.text()).strip().lower()
        for row in range(self.history_table.rowCount()):
            if not query:
                self.history_table.setRowHidden(row, False)
                continue
            row_text = " ".join(
                self.history_table.item(row, column).text().lower()
                for column in range(self.history_table.columnCount())
                if self.history_table.item(row, column)
            )
            self.history_table.setRowHidden(row, query not in row_text)

    def _delete_selected_history(self) -> None:
        if self.collector_worker and self.collector_worker.isRunning():
            InfoBar.warning("任务运行中", "采集任务运行中，暂时不能删除历史。", parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        selected_ids: list[str] = []
        for row in range(self.history_table.rowCount()):
            container = self.history_table.cellWidget(row, 0)
            check_widget = None
            if container:
                for child in container.findChildren(CheckBox):
                    check_widget = child
                    break
            if check_widget and check_widget.isChecked():
                id_item = self.history_table.item(row, 1)
                if id_item:
                    selected_ids.append(id_item.text())
        if not selected_ids:
            InfoBar.info("未选中", "请先勾选要删除的记录。", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        answer = QMessageBox.question(
            self,
            "删除确认",
            f"确定删除选中的 {len(selected_ids)} 条记录吗？",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._ensure_storage_for_current_data_dir()
        except ValueError as exc:
            InfoBar.warning("数据目录无效", str(exc), parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        self.storage.delete_task_runs_by_ids(selected_ids)
        self.refresh_history()
        self.refresh_task_center()
        InfoBar.success("已删除", f"已删除 {len(selected_ids)} 条历史记录。", parent=self, position=InfoBarPosition.TOP, duration=2000)

    # ── Settings Tab ──────────────────────────────────────────────────

    def _build_settings_tab(self) -> QWidget:
        page, _content, layout = self._scroll_page("settingsPage")

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("设置与维护")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("管理数据目录与本地维护操作")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        layout.addLayout(header)

        config_card = self._card("本机配置")
        config_inner = QVBoxLayout()
        config_inner.setSpacing(6)
        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(10)
        cfg_label = StrongBodyLabel("数据目录")
        cfg_label.setFixedWidth(70)
        self.data_dir_input = LineEdit(self)
        self.data_dir_input.setText(str(self.settings.data_dir))
        browse_button = PushButton("选择", self)
        browse_button.setIcon(FIF.FOLDER)
        browse_button.clicked.connect(self.browse_data_dir)
        save_button = PrimaryPushButton("保存", self)
        save_button.setIcon(FIF.SAVE)
        save_button.clicked.connect(self.save_data_dir_to_env)
        cfg_row.addWidget(cfg_label)
        cfg_row.addWidget(self.data_dir_input, 1)
        cfg_row.addWidget(browse_button)
        cfg_row.addWidget(save_button)

        env_row = QHBoxLayout()
        env_row.setSpacing(10)
        env_label = StrongBodyLabel(".env 路径")
        env_label.setFixedWidth(70)
        env_path_text = LineEdit(self)
        env_path_text.setText(str(self.env_bootstrap.env_path))
        env_path_text.setReadOnly(True)
        open_env_button = PushButton("打开", self)
        open_env_button.setIcon(FIF.FOLDER)
        open_env_button.clicked.connect(lambda: self.open_path(self.env_bootstrap.env_path.parent))
        env_row.addWidget(env_label)
        env_row.addWidget(env_path_text, 1)
        env_row.addWidget(open_env_button)

        config_inner.addLayout(cfg_row)
        config_inner.addLayout(env_row)

        # 验证码提示音开关
        sound_row = QHBoxLayout()
        sound_row.setSpacing(10)
        sound_label = StrongBodyLabel("验证码提示音")
        sound_label.setFixedWidth(70)
        self.captcha_sound_switch = SwitchButton(self)
        self.captcha_sound_switch.setChecked(self.settings.captcha_sound_enabled)
        self.captcha_sound_switch.setOnText("开")
        self.captcha_sound_switch.setOffText("关")
        sound_desc = CaptionLabel("验证码弹出时播放系统提示音（最小化时仍会闪烁任务栏和显示托盘通知）")
        sound_desc.setStyleSheet(f"color: {TEXT_SOFT};")
        sound_desc.setWordWrap(True)
        sound_row.addWidget(sound_label)
        sound_row.addWidget(self.captcha_sound_switch)
        sound_row.addWidget(sound_desc, 1)
        self.captcha_sound_switch.checkedChanged.connect(self._save_captcha_sound_to_env)
        config_inner.addLayout(sound_row)
        config_card.viewLayout.addLayout(config_inner)

        maintenance_card = self._card("数据维护")
        maintenance_layout = QHBoxLayout()
        maintenance_layout.setSpacing(10)

        reset_card = CardWidget(self)
        reset_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        reset_inner = QVBoxLayout(reset_card)
        reset_inner.setContentsMargins(14, 10, 14, 10)
        reset_inner.setSpacing(6)
        reset_header = QHBoxLayout()
        reset_header.setSpacing(10)
        reset_icon_label = QLabel("\U0001F4CB")
        reset_icon_label.setFixedSize(32, 32)
        reset_icon_label.setAlignment(Qt.AlignCenter)
        from PySide6.QtGui import QFont as _QFont
        _font = _QFont()
        _font.setPixelSize(18)
        reset_icon_label.setFont(_font)
        reset_title_label = StrongBodyLabel("重置历史")
        reset_title_label.setStyleSheet(f"font-size: 14px; color: {TEXT};")
        reset_header.addWidget(reset_icon_label)
        reset_header.addWidget(reset_title_label)
        reset_header.addStretch(1)
        reset_desc = CaptionLabel("清空采集历史记录，保留 output 文件。")
        reset_desc.setStyleSheet(f"color: {TEXT_SOFT};")
        reset_desc.setWordWrap(True)
        self.reset_history_button = PushButton("重置", self)
        self.reset_history_button.setIcon(FIF.DELETE)
        self.reset_history_button.clicked.connect(self.reset_history)
        reset_inner.addLayout(reset_header)
        reset_inner.addWidget(reset_desc)
        reset_inner.addStretch(1)
        reset_inner.addWidget(self.reset_history_button)

        delete_card = CardWidget(self)
        delete_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        delete_inner = QVBoxLayout(delete_card)
        delete_inner.setContentsMargins(14, 10, 14, 10)
        delete_inner.setSpacing(6)
        delete_header = QHBoxLayout()
        delete_header.setSpacing(10)
        delete_icon_label = QLabel("\U0001F5D1\uFE0F")
        delete_icon_label.setFixedSize(32, 32)
        delete_icon_label.setAlignment(Qt.AlignCenter)
        delete_icon_label.setFont(_font)
        delete_title_label = StrongBodyLabel("删除输出文件")
        delete_title_label.setStyleSheet(f"font-size: 14px; color: {RED};")
        delete_header.addWidget(delete_icon_label)
        delete_header.addWidget(delete_title_label)
        delete_header.addStretch(1)
        delete_desc = CaptionLabel("删除 数据目录/output 并清空采集历史。不会删除 parsed、数据库或缓存。")
        delete_desc.setStyleSheet(f"color: {TEXT_SOFT};")
        delete_desc.setWordWrap(True)
        self.delete_output_button = PushButton("删除", self)
        self.delete_output_button.setStyleSheet(
            f"background: {RED}; color: #FFFFFF; border-radius: 6px; padding: 6px 16px; font-weight: 700;"
        )
        self.delete_output_button.clicked.connect(self.delete_output_files)
        delete_inner.addLayout(delete_header)
        delete_inner.addWidget(delete_desc)
        delete_inner.addStretch(1)
        delete_inner.addWidget(self.delete_output_button)

        maintenance_layout.addWidget(reset_card)
        maintenance_layout.addWidget(delete_card)
        maintenance_card.viewLayout.addLayout(maintenance_layout)

        layout.addWidget(config_card)
        layout.addWidget(maintenance_card, 1)
        return page

    # ── Data Dir Helpers ──────────────────────────────────────────────

    def _current_data_dir(self) -> Path:
        text = self.data_dir_input.text().strip()
        if not text:
            raise ValueError("请先设置数据目录。")
        return Path(text).expanduser().resolve()

    def _ensure_storage_for_current_data_dir(self) -> Path:
        data_dir = self._current_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        database_path = data_dir / "subtitle_info_collection.sqlite3"
        if self.storage.database_path != database_path:
            self.storage = AppStorage(database_path)
        return data_dir

    def _set_maintenance_enabled(self, enabled: bool) -> None:
        self.reset_history_button.setEnabled(enabled)
        self.delete_output_button.setEnabled(enabled)

    # ── Provider Selection ────────────────────────────────────────────

    def selected_providers(self) -> list[str]:
        providers = []
        if self.subhd_check.isChecked():
            providers.append("subhd")
        if self.subdl_check.isChecked():
            providers.append("subdl")
        if self.assrt_check.isChecked():
            providers.append("assrt")
        if self.opensubtitles_check.isChecked():
            providers.append("opensubtitles")
        return providers

    # ── Collection Flow ───────────────────────────────────────────────

    def start_collection(self) -> None:
        if self.collector_worker and self.collector_worker.isRunning():
            return
        providers = self.selected_providers()
        if not providers:
            InfoBar.warning(
                "缺少字幕源",
                "请至少选择一个字幕源。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000,
            )
            return
        try:
            data_dir = self._ensure_storage_for_current_data_dir()
        except ValueError as exc:
            InfoBar.warning("数据目录无效", str(exc), parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        env_settings = AppSettings.from_env(self.env_bootstrap.env_path)
        config = TaskConfig(
            year=self.year_spin.value(),
            limit=self.limit_spin.value(),
            subtitle_providers=providers,
            fallback_enabled=self.fallback_check.isChecked(),
            download_enabled=self.download_check.isChecked(),
            subtitle_min_bilingual_ratio=env_settings.subtitle_min_bilingual_ratio,
            request_interval_ms=env_settings.request_interval_ms,
            movie_concurrency=env_settings.movie_concurrency,
            output_root=data_dir / "output",
            tmdb_token=env_settings.tmdb_token,
            assrt_token=env_settings.assrt_token,
            assrt_api_base_url=env_settings.assrt_api_base_url,
            subdl_api_key=env_settings.subdl_api_key,
            subdl_base_url=env_settings.subdl_base_url,
            subdl_download_base_url=env_settings.subdl_download_base_url,
            subdl_languages=env_settings.subdl_languages,
            subdl_include_traditional=env_settings.subdl_include_traditional,
            opensubtitles_api_key=env_settings.opensubtitles_api_key,
            opensubtitles_username=env_settings.opensubtitles_username,
            opensubtitles_password=env_settings.opensubtitles_password,
            opensubtitles_base_url=env_settings.opensubtitles_base_url,
            opensubtitles_user_agent=env_settings.opensubtitles_user_agent,
            provider_priority=env_settings.provider_priority,
            provider_disabled=env_settings.provider_disabled,
            subhd_captcha_ocr_enabled=env_settings.subhd_captcha_ocr_enabled,
            subhd_captcha_auto_submit_min_confidence=env_settings.subhd_captcha_auto_submit_min_confidence,
            subhd_search_timeout=env_settings.subhd_search_timeout,
            provider_search_timeout=env_settings.provider_search_timeout,
            proxies=env_settings.proxies(),
        )
        self.collect_log.clear()
        self.collect_progress_ring.setValue(0)
        self.collect_progress_label.setText("0%")
        self.collect_status.setText("任务启动中")
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.pause_button.setText("暂停")
        self.pause_button.setIcon(FIF.PAUSE)
        self.abort_button.setEnabled(True)
        self._collect_paused = False
        self._set_maintenance_enabled(False)
        self._reset_collect_elapsed()
        self._start_collect_elapsed()
        self.collector_worker = CollectorWorker(config, self.storage.database_path)
        self.collector_worker.log_message.connect(self.append_collect_log)
        self.collector_worker.progress_changed.connect(self.update_collect_progress)
        self.collector_worker.verification_requested.connect(self.handle_verification_request)
        self.collector_worker.finished_success.connect(self.collection_finished)
        self.collector_worker.finished_error.connect(self.collection_failed)
        self.collector_worker.start()

    # 切换采集暂停/继续
    def toggle_collect_pause(self) -> None:
        if not self.collector_worker or not self.collector_worker.isRunning():
            return
        if self._collect_paused:
            self.collector_worker.resume_collection()
            self._collect_paused = False
            self.pause_button.setText("暂停")
            self.pause_button.setIcon(FIF.PAUSE)
            self._start_collect_elapsed()
            if self.collect_status.text() == "已暂停":
                self.collect_status.setText("采集中")
            return
        self.collector_worker.pause_collection()
        self._collect_paused = True
        self.pause_button.setText("继续")
        self.pause_button.setIcon(FIF.PLAY)
        self._pause_collect_elapsed()
        self.collect_status.setText("已暂停")

    # 中止当前采集任务
    def abort_collection(self) -> None:
        if not self.collector_worker or not self.collector_worker.isRunning():
            return
        self.abort_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.collect_status.setText("正在中止…")
        if self._collect_paused:
            self._collect_paused = False
            self.pause_button.setText("暂停")
            self.pause_button.setIcon(FIF.PAUSE)
            self._start_collect_elapsed()
        self.collector_worker.abort_collection()
        if self._verification_dialog is not None and self._verification_dialog.isVisible():
            self._verification_dialog.reject()

    # 将毫秒格式化为 HH:MM:SS
    def _format_elapsed(self, elapsed_ms: int) -> str:
        total_seconds = max(0, elapsed_ms) // 1000
        hours, rem = divmod(total_seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    # 刷新耗时标签文案
    def _update_collect_elapsed_label(self) -> None:
        self.collect_elapsed_label.setText(f"耗时 {self._format_elapsed(self._collect_elapsed_ms)}")

    # 重置采集耗时计数
    def _reset_collect_elapsed(self) -> None:
        self._collect_elapsed_timer.stop()
        self._collect_elapsed_ms = 0
        self._collect_elapsed_running = False
        self._collect_elapsed_last_tick = None
        self._update_collect_elapsed_label()

    # 开始或恢复累计耗时
    def _start_collect_elapsed(self) -> None:
        self._collect_elapsed_last_tick = time.monotonic()
        self._collect_elapsed_running = True
        if not self._collect_elapsed_timer.isActive():
            self._collect_elapsed_timer.start()
        self._update_collect_elapsed_label()

    # 暂停累计耗时（冻结显示）
    def _pause_collect_elapsed(self) -> None:
        if self._collect_elapsed_running and self._collect_elapsed_last_tick is not None:
            self._collect_elapsed_ms += int((time.monotonic() - self._collect_elapsed_last_tick) * 1000)
        self._collect_elapsed_running = False
        self._collect_elapsed_last_tick = None
        self._update_collect_elapsed_label()

    # 停止计时并定格最终耗时
    def _stop_collect_elapsed(self) -> None:
        if self._collect_elapsed_running and self._collect_elapsed_last_tick is not None:
            self._collect_elapsed_ms += int((time.monotonic() - self._collect_elapsed_last_tick) * 1000)
        self._collect_elapsed_running = False
        self._collect_elapsed_last_tick = None
        self._collect_elapsed_timer.stop()
        self._update_collect_elapsed_label()

    # 定时刷新采集耗时显示
    def _tick_collect_elapsed(self) -> None:
        if not self._collect_elapsed_running or self._collect_elapsed_last_tick is None:
            return
        now = time.monotonic()
        self._collect_elapsed_ms += int((now - self._collect_elapsed_last_tick) * 1000)
        self._collect_elapsed_last_tick = now
        self._update_collect_elapsed_label()

    # 采集结束时复位控制按钮
    def _reset_collect_controls(self) -> None:
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.pause_button.setText("暂停")
        self.pause_button.setIcon(FIF.PAUSE)
        self.abort_button.setEnabled(False)
        self._collect_paused = False
        self._set_maintenance_enabled(True)

    def append_collect_log(self, message: str) -> None:
        self.collect_log.append(message)

    def copy_collect_log(self) -> None:
        text = self.collect_log.toPlainText()
        if not text.strip():
            InfoBar.info("暂无日志", "当前没有可复制的采集日志。", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        QApplication.clipboard().setText(text)
        InfoBar.success("已复制", "采集日志已复制到剪贴板。", parent=self, position=InfoBarPosition.TOP, duration=2000)

    def update_collect_progress(self, current: int, total: int, movie: str) -> None:
        percent = int(current / total * 100) if total else 0
        self.collect_progress_ring.setValue(percent)
        self.collect_progress_label.setText(f"{percent}%")
        self.collect_status.setText(f"{current}/{total} {movie}")

    def _pixmap_from_data_uri(self, data_uri: str) -> QPixmap:
        if not data_uri.startswith("data:image/") or "," not in data_uri:
            return QPixmap()
        try:
            image_bytes = base64.b64decode(data_uri.split(",", 1)[1], validate=False)
        except ValueError:
            return QPixmap()
        mime = data_uri.split(",", 1)[0].split(":")[1].split(";")[0]
        if mime == "image/svg+xml":
            try:
                from PySide6.QtSvg import QSvgRenderer
                from PySide6.QtCore import QRectF
                renderer = QSvgRenderer(image_bytes)
                if not renderer.isValid():
                    return QPixmap()
                target_w = 480
                target_h = 160
                pixmap = QPixmap(target_w, target_h)
                pixmap.fill(Qt.white)
                painter = QPainter(pixmap)
                renderer.render(painter, QRectF(0, 0, target_w, target_h))
                painter.end()
                return pixmap
            except ImportError:
                pixmap = QPixmap()
                pixmap.loadFromData(image_bytes)
                return pixmap
        pixmap = QPixmap()
        pixmap.loadFromData(image_bytes)
        return pixmap

    @staticmethod
    def _localize_ocr_message(message: str) -> str:
        """将 OCR 英文错误消息映射为中文友好提示"""
        _MAPPING = {
            "captcha SVG contains no readable text": "自动识别失败，请手动输入",
            "captcha SVG decode failed": "验证码解码失败，请手动输入",
            "captcha image is unavailable": "验证码图片加载失败，请点击刷新",
            "optional OCR dependencies are not installed": "OCR 功能未启用",
            "OCR returned no captcha text": "自动识别无结果，请手动输入",
        }
        if not message:
            return ""
        for key, value in _MAPPING.items():
            if key in message:
                return value
        if message.startswith("OCR failed:"):
            return "自动识别失败，请手动输入"
        return message

    def handle_verification_request(self, payload: dict) -> None:
        subtitle_title = payload.get("subtitleTitle") or payload.get("detailUrl") or ""
        subtitle_id = str(payload.get("providerSubtitleId") or "").strip()
        captcha_type = "none"
        image_data_uri = str(payload.get("verificationImageDataUri") or "")
        if image_data_uri:
            captcha_type = "svg" if "svg" in image_data_uri.lower() else "image"
        logger.info(
            "subhd.captcha.dialog.open subtitle_title=%s subtitle_id=%s captcha_type=%s",
            subtitle_title, subtitle_id, captcha_type,
        )

        # ── 验证码提醒（声音 + 托盘 + 闪烁）──
        if self.settings.captcha_sound_enabled:
            _play_captcha_alert()

        subtitle_title = payload.get("subtitleTitle") or payload.get("detailUrl") or ""
        self._tray_icon.showMessage(
            "验证码提醒",
            f"SubHD 需要输入验证码：{subtitle_title}" if subtitle_title else "SubHD 需要输入验证码",
            QSystemTrayIcon.Information,
            5000,
        )

        if self.isMinimized():
            _flash_taskbar(int(self.winId()))

        subtitle_title = payload.get("subtitleTitle") or payload.get("detailUrl") or ""
        self.append_collect_log(
            f"[{datetime.now().strftime('%H:%M:%S')}] 验证码弹窗：{subtitle_title}，请输入验证码"
        )

        if self._verification_dialog is not None:
            self._update_verification_dialog(payload)
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("SubHD 验证码")
        dialog.setMinimumWidth(480)
        dialog.setMaximumWidth(520)
        dialog.setStyleSheet(
            f"QDialog {{ background: {SURFACE}; border-radius: 12px; }}"
        )

        root = QVBoxLayout(dialog)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title_bar = QHBoxLayout()
        title_bar.setSpacing(10)
        icon_label = QLabel("🔐")
        icon_label.setFixedSize(28, 28)
        icon_label.setStyleSheet("font-size: 20px;")
        title_bar.addWidget(icon_label)
        title_text = StrongBodyLabel("SubHD 验证码")
        title_text.setStyleSheet(f"font-size: 16px; color: {TEXT};")
        title_bar.addWidget(title_text)
        title_bar.addStretch(1)
        root.addLayout(title_bar)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background: {LINE_SOFT}; border: none;")
        root.addWidget(separator)

        subtitle_title = payload.get("subtitleTitle") or payload.get("detailUrl") or ""
        if subtitle_title:
            sub_label = StrongBodyLabel(subtitle_title)
            sub_label.setWordWrap(True)
            sub_label.setMaximumWidth(460)
            sub_label.setStyleSheet(f"color: {TEXT}; font-size: 14px;")
            root.addWidget(sub_label)

        provider_subtitle_id = str(payload.get("providerSubtitleId") or "").strip()
        if provider_subtitle_id:
            id_label = CaptionLabel(f"字幕ID: {provider_subtitle_id}")
            id_label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 12px;")
            root.addWidget(id_label)

        # Unified captcha container - single adaptive display area
        captcha_container = QVBoxLayout()
        captcha_container.setSpacing(6)

        image_label = QLabel(self)
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setMinimumHeight(100)
        image_data_uri = str(payload.get("verificationImageDataUri") or "")
        pixmap = self._pixmap_from_data_uri(image_data_uri)
        captcha_rendered = False
        fallback_html = ""

        if not pixmap.isNull():
            # Render captcha (QSvgRenderer handles SVG, QPixmap handles PNG/JPEG)
            image_label.setPixmap(
                pixmap.scaled(480, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            image_label.setStyleSheet(f"border: 1px solid {LINE_SOFT}; border-radius: 8px; padding: 4px;")
            captcha_container.addWidget(image_label)
            captcha_rendered = True
        else:
            logger.info("subhd.captcha.render.fail reason=no_usable_captcha subtitle_id=%s", subtitle_id)

        # Refresh button row
        refresh_row = QHBoxLayout()
        refresh_row.addStretch(1)
        refresh_btn = TransparentToolButton(FIF.SYNC, self)
        refresh_btn.setFixedSize(36, 36)
        refresh_btn.setToolTip("刷新验证码")
        refresh_btn.clicked.connect(self._on_captcha_refresh)
        refresh_row.addWidget(refresh_btn)
        captcha_container.addLayout(refresh_row)

        if not captcha_rendered:
            verification_html = str(payload.get("verificationHtml") or "").strip()
            if verification_html and len(verification_html) > 10:
                # Only show HTML fallback when no image/SVG can be rendered
                browser = QTextBrowser()
                browser.setHtml(verification_html)
                browser.setMaximumHeight(120)
                browser.setStyleSheet(f"border: 1px solid {LINE_SOFT}; border-radius: 6px;")
                captcha_container.addWidget(browser)
            else:
                fallback_label = QLabel("验证码加载失败，请点击刷新")
                fallback_label.setAlignment(Qt.AlignCenter)
                fallback_label.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 13px; padding: 24px; border: none;")
                captcha_container.addWidget(fallback_label)

        root.addLayout(captcha_container)

        ocr_label = CaptionLabel("")
        suggested_code = str(payload.get("suggestedCode") or "").strip()
        if suggested_code:
            confidence = float(payload.get("suggestedConfidence") or 0)
            ocr_label.setText(f"OCR 识别: {suggested_code} ({confidence:.0%})")
            ocr_label.setStyleSheet(f"color: {GREEN}; font-size: 12px;")
        else:
            localized_msg = self._localize_ocr_message(str(payload.get("ocrMessage") or ""))
            if localized_msg:
                ocr_label.setText(localized_msg)
                ocr_label.setStyleSheet(f"color: {RED}; font-size: 12px;")
        root.addWidget(ocr_label)

        code_input = LineEdit(self)
        if suggested_code:
            code_input.setText(suggested_code)
        code_input.setPlaceholderText("请输入验证码")
        code_input.setFixedHeight(40)
        code_input.setStyleSheet(
            "font-size: 16px; border-radius: 8px; border: 1px solid #d0d0d0; "
            "background: #ffffff; padding: 4px 12px; "
            "selection-background-color: #4a90d9;"
        )
        code_input.setFocus()
        root.addWidget(code_input)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        submit = PrimaryPushButton("提交", self)
        submit.setMinimumWidth(100)
        cancel = PushButton("跳过", self)
        open_detail = PushButton("打开详情页", self)
        open_detail.setStyleSheet(f"color: {TEXT_SOFT};")
        open_detail.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(str(payload.get("detailUrl") or "")))
        )
        buttons.addWidget(submit)
        buttons.addWidget(cancel)
        buttons.addWidget(open_detail)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self._verification_dialog = dialog
        self._verification_image_label = image_label
        self._verification_refresh_btn = refresh_btn
        self._verification_code_input = code_input
        self._verification_ocr_label = ocr_label

        submit.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        accepted = dialog.exec() == QDialog.Accepted

        # Log dialog result
        user_input = code_input.text().strip() if accepted else ""
        if accepted and user_input:
            self.append_collect_log(
                f"[{datetime.now().strftime('%H:%M:%S')}] 验证码已提交：{user_input}"
            )
            suggested = str(payload.get("suggestedCode") or "").strip()
            logger.info(
                "subhd.captcha.dialog.submit subtitle_id=%s user_code=%s ocr_suggested=%s",
                provider_subtitle_id, user_input, suggested,
            )
        elif accepted:
            self.append_collect_log(
                f"[{datetime.now().strftime('%H:%M:%S')}] 验证码已提交（空）"
            )
            logger.info("subhd.captcha.dialog.submit subtitle_id=%s user_code=(empty)", provider_subtitle_id)
        else:
            self.append_collect_log(
                f"[{datetime.now().strftime('%H:%M:%S')}] 已跳过验证码"
            )
            logger.info("subhd.captcha.dialog.skip subtitle_id=%s", provider_subtitle_id)

        self._verification_dialog = None
        self._verification_image_label = None
        self._verification_refresh_btn = None
        self._verification_code_input = None
        self._verification_ocr_label = None
        if self.collector_worker:
            self.collector_worker.submit_verification(code_input.text().strip() if accepted else "")

    def _on_captcha_refresh(self) -> None:
        self.append_collect_log(
            f"[{datetime.now().strftime('%H:%M:%S')}] 验证码已刷新"
        )
        logger.info("subhd.captcha.dialog.refresh")
        if self._verification_code_input:
            self._verification_code_input.clear()
            self._verification_code_input.setPlaceholderText("刷新中，请稍候...")
        if self._verification_refresh_btn:
            self._verification_refresh_btn.setEnabled(False)
        if self._verification_ocr_label:
            self._verification_ocr_label.setText("正在刷新验证码...")
            self._verification_ocr_label.setStyleSheet("color: #666; font-size: 12px;")
        if self.collector_worker:
            self.collector_worker.request_captcha_refresh()

    def _update_verification_dialog(self, payload: dict) -> None:
        subtitle_id = str(payload.get("providerSubtitleId") or "").strip()
        logger.info("subhd.captcha.dialog.update subtitle_id=%s", subtitle_id)
        # Always render via pixmap (QSvgRenderer handles SVG, QPixmap handles images)
        if self._verification_image_label:
            image_data_uri = str(payload.get("verificationImageDataUri") or "")
            pixmap = self._pixmap_from_data_uri(image_data_uri)
            if not pixmap.isNull():
                self._verification_image_label.setPixmap(
                    pixmap.scaled(480, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
        # Restore refresh button
        if self._verification_refresh_btn:
            self._verification_refresh_btn.setEnabled(True)
        if self._verification_code_input:
            self._verification_code_input.setPlaceholderText("请输入验证码")
            suggested_code = str(payload.get("suggestedCode") or "").strip()
            if suggested_code:
                self._verification_code_input.setText(suggested_code)
            else:
                self._verification_code_input.clear()
        if self._verification_ocr_label:
            suggested_code = str(payload.get("suggestedCode") or "").strip()
            if suggested_code:
                confidence = float(payload.get("suggestedConfidence") or 0)
                self._verification_ocr_label.setText(f"OCR: {suggested_code} ({confidence:.0%})")
                self._verification_ocr_label.setStyleSheet("font-size: 12px;")
            else:
                localized_msg = self._localize_ocr_message(str(payload.get("ocrMessage") or ""))
                if localized_msg:
                    self._verification_ocr_label.setText(localized_msg)
                    self._verification_ocr_label.setStyleSheet("color: #ff6b6b; font-size: 12px;")
                else:
                    self._verification_ocr_label.setText("")
                    self._verification_ocr_label.setStyleSheet("font-size: 12px;")

    def collection_finished(self, result: dict) -> None:
        self._stop_collect_elapsed()
        self._reset_collect_controls()
        self.show_result_summary(result)
        self.refresh_history()
        self.refresh_task_center()
        if result.get("runStatus") == "aborted":
            self.collect_status.setText("任务已中止")
            InfoBar.warning(
                "采集已中止",
                f"已保留部分结果。输出目录：{result.get('downloadDir', '')}",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=5000,
            )
            return
        self.collect_progress_ring.setValue(100)
        self.collect_progress_label.setText("100%")
        self.collect_status.setText("任务完成")
        InfoBar.success(
            "采集完成",
            f"输出目录：{result.get('downloadDir', '')}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    def collection_failed(self, message: str) -> None:
        self._stop_collect_elapsed()
        self._reset_collect_controls()
        self.collect_status.setText("任务失败")
        self.collect_log.append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
        self.refresh_history()
        self.refresh_task_center()
        InfoBar.error("采集失败", message, parent=self, position=InfoBarPosition.TOP, duration=5000)

    def show_result_summary(self, result: dict) -> None:
        stat_map = {
            "movies": result.get("movieCount", 0),
            "hits": result.get("bestCount", 0),
            "filtered": result.get("subtitleCount", 0) - result.get("bestCount", 0),
            "failed": result.get("failedCount", 0),
            "downloaded": result.get("downloadCount", 0),
        }
        for key, value in stat_map.items():
            if key in self.collect_stat_labels:
                self.collect_stat_labels[key].setText(str(value))

    # ── Automation Flow ───────────────────────────────────────────────

    def start_automation_script(self) -> None:
        if self.automation_worker and self.automation_worker.isRunning():
            return
        try:
            data_dir = self._ensure_storage_for_current_data_dir()
        except ValueError as exc:
            InfoBar.warning("数据目录无效", str(exc), parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        self.automation_log.clear()
        self.automation_status.setText("执行中")
        self.automation_progress_ring.setValue(0)
        self.automation_progress_label.setText("0%")
        self.automation_run_button.setEnabled(False)
        self.automation_open_button.setEnabled(False)
        self.latest_automation_output_path = None
        self.latest_automation_output_paths = []
        self.automation_stat_labels["total"].setText("0")
        self.automation_stat_labels["pages"].setText("0")
        self.automation_stat_labels["output"].setText("-")
        self.automation_stat_labels["output"].setToolTip("")

        self.automation_worker = AutomationScriptWorker(
            data_dir,
            self.env_bootstrap.env_path,
            self.automation_unicloud_import_switch.isChecked(),
        )
        self.automation_worker.log_message.connect(self.append_automation_log)
        self.automation_worker.progress_changed.connect(self._on_automation_progress)
        self.automation_worker.finished_success.connect(self.automation_finished)
        self.automation_worker.finished_error.connect(self.automation_failed)
        self.automation_worker.start()

    # 刷新今日台词采集进度百分比与条数
    def _on_automation_progress(self, current: int, total: int, tip: str) -> None:
        if total > 0:
            pct = min(100, int(current * 100 / total))
            self.automation_progress_ring.setValue(pct)
            self.automation_progress_label.setText(f"{pct}%")
        self.automation_stat_labels["total"].setText(str(current))
        if tip.startswith("第 ") and tip.endswith(" 页"):
            page_text = tip[2:-2].strip()
            if page_text.isdigit():
                self.automation_stat_labels["pages"].setText(page_text)

    def append_automation_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = str(message).splitlines() or [""]
        for line in lines:
            self.automation_log.append(f"[{stamp}] {line}")

    def copy_automation_log(self) -> None:
        text = self.automation_log.toPlainText()
        if not text.strip():
            InfoBar.info(
                "暂无日志",
                "当前没有可复制的自动化脚本日志。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000,
            )
            return
        QApplication.clipboard().setText(text)
        InfoBar.success(
            "已复制",
            "自动化脚本日志已复制到剪贴板。",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2000,
        )

    def automation_finished(self, result: dict) -> None:
        self.automation_run_button.setEnabled(True)
        self.automation_status.setText("执行完成")
        self.automation_progress_ring.setValue(100)
        self.automation_progress_label.setText("100%")
        output_paths = [
            Path(str(path))
            for path in (result.get("outputPaths") or [])
            if str(path or "").strip()
        ]
        output_path = output_paths[0] if output_paths else Path(str(result.get("outputPath") or ""))
        self.latest_automation_output_path = output_path
        self.latest_automation_output_paths = output_paths or ([output_path] if str(output_path) else [])
        self.automation_open_button.setEnabled(any(path.exists() for path in self.latest_automation_output_paths))
        self.automation_stat_labels["total"].setText(str(result.get("totalCount", 0)))
        self.automation_stat_labels["pages"].setText(str(result.get("pageCount", 0)))
        output_label = "\n".join(str(path) for path in self.latest_automation_output_paths) or "-"
        self.automation_stat_labels["output"].setText(output_label)
        self.automation_stat_labels["output"].setToolTip(
            "\n".join(str(path) for path in self.latest_automation_output_paths)
        )
        if result.get("skippedCount"):
            self.append_automation_log(f"本地去重：{result.get('skippedCount')} 条")
        if result.get("translationRequestedCount"):
            self.append_automation_log(
                "英文补全："
                f"请求 {result.get('translationRequestedCount')} 条，"
                f"成功 {result.get('translationFilledCount')} 条，"
                f"失败 {result.get('translationFailureCount')} 条"
            )
        for path in self.latest_automation_output_paths:
            self.append_automation_log(f"输出文件：{path}")
        toast_output = (
            f"{len(self.latest_automation_output_paths)} 个文件"
            if len(self.latest_automation_output_paths) > 1
            else output_label
        )
        InfoBar.success("自动化脚本完成", f"输出 {toast_output}", parent=self, position=InfoBarPosition.TOP, duration=5000)

    def automation_failed(self, message: str) -> None:
        self.automation_run_button.setEnabled(True)
        self.automation_status.setText("执行失败")
        self.automation_progress_ring.setValue(0)
        self.automation_progress_label.setText("失败")
        self.append_automation_log(message)
        InfoBar.error("自动化脚本失败", message, parent=self, position=InfoBarPosition.TOP, duration=5000)

    def open_automation_output_file(self) -> None:
        if len(self.latest_automation_output_paths) > 1 and self.latest_automation_output_paths[0].parent:
            self.open_path(self.latest_automation_output_paths[0].parent)
        elif self.latest_automation_output_path:
            self.open_path(self.latest_automation_output_path)

    def reset_automation_panel(self) -> None:
        if self.automation_worker and self.automation_worker.isRunning():
            InfoBar.warning("任务运行中", "自动化脚本执行中，暂时不能重置。", parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        self.latest_automation_output_path = None
        self.automation_status.setText("等待执行")
        self.automation_progress_ring.setValue(0)
        self.automation_progress_label.setText("0%")
        self.latest_automation_output_paths = []
        self.automation_open_button.setEnabled(False)
        self.automation_log.clear()
        self.automation_stat_labels["total"].setText("0")
        self.automation_stat_labels["pages"].setText("0")
        self.automation_stat_labels["output"].setText("-")
        self.automation_stat_labels["output"].setToolTip("")



    # ── Classic Lines Flow ────────────────────────────────────────────

    # 启动经典台词全量采集（延迟/无头等参数使用内部默认值）
    def start_classic_automation(self) -> None:
        if self.classic_automation_worker and self.classic_automation_worker.isRunning():
            return
        try:
            data_dir = self._ensure_storage_for_current_data_dir()
        except ValueError as exc:
            InfoBar.warning("\u6570\u636e\u76ee\u5f55\u65e0\u6548", str(exc), parent=self, duration=3000)
            return
        self.classic_log.clear()
        self.classic_status.setText("执行中")
        self.classic_progress_ring.setValue(0)
        self.classic_progress_label.setText("0%")
        self.classic_run_button.setEnabled(False)
        self.classic_open_button.setEnabled(False)
        self.latest_classic_output_path = None
        self.latest_classic_output_paths = []
        for k in ["movies", "lines", "pages"]:
            self.classic_stat_labels[k].setText("0")
        self.classic_stat_labels["output"].setText("-")
        self.classic_stat_labels["output"].setToolTip("")
        self.classic_automation_worker = ClassicLinesAutomationWorker(
            data_dir,
            unicloud_import_format=self.classic_unicloud_switch.isChecked(),
        )
        self.classic_automation_worker.log_message.connect(self.append_classic_log)
        self.classic_automation_worker.progress_changed.connect(self._on_classic_progress)
        self.classic_automation_worker.finished_success.connect(self.classic_automation_finished)
        self.classic_automation_worker.finished_error.connect(self.classic_automation_failed)
        self.classic_automation_worker.start()

    # 刷新经典台词采集进度环与统计（分页明细由 Runner 写日志）
    def _on_classic_progress(self, current: int, total: int, movie_name: str) -> None:
        if total > 0:
            pct = int(current * 100 / total)
            self.classic_progress_ring.setValue(pct)
            self.classic_progress_label.setText(f"{pct}%")
        self.classic_stat_labels["movies"].setText(str(current))
        # 按站点每页 24 部估算当前页数
        self.classic_stat_labels["pages"].setText(str(max(1, (current + 23) // 24)))

    def append_classic_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        for t in str(message).splitlines() or [""]:
            self.classic_log.append(f"[{stamp}] {t}")

    def copy_classic_log(self) -> None:
        t = self.classic_log.toPlainText()
        if not t.strip():
            InfoBar.info("\u6682\u65e0\u65e5\u5fd7", "\u5f53\u524d\u6ca1\u6709\u53ef\u590d\u5236\u7684\u65e5\u5fd7\u3002", parent=self, duration=2000)
            return
        QApplication.clipboard().setText(t)
        InfoBar.success("\u5df2\u590d\u5236", "\u7ecf\u5178\u53f0\u8bcd\u65e5\u5fd7\u5df2\u590d\u5236\u5230\u526a\u8d34\u677f\u3002", parent=self, duration=2000)

    def classic_automation_finished(self, result: dict) -> None:
        self.classic_run_button.setEnabled(True)
        self.classic_status.setText("\u6267\u884c\u5b8c\u6210")
        self.classic_progress_ring.setValue(100)
        self.classic_progress_label.setText("100%")
        output_paths = [Path(str(p)) for p in (result.get("outputPaths") or []) if str(p or "").strip()]
        op = output_paths[0] if output_paths else Path(str(result.get("outputPath") or ""))
        self.latest_classic_output_path = op
        self.latest_classic_output_paths = output_paths or ([op] if str(op) else [])
        self.classic_open_button.setEnabled(any(p.exists() for p in self.latest_classic_output_paths))
        self.classic_stat_labels["movies"].setText(str(result.get("totalMovies", 0)))
        self.classic_stat_labels["lines"].setText(str(result.get("totalLines", 0)))
        self.classic_stat_labels["pages"].setText(str(result.get("pageCount", 0)))
        ol = "\n".join(str(p) for p in self.latest_classic_output_paths) or "-"
        self.classic_stat_labels["output"].setText(ol)
        self.classic_stat_labels["output"].setToolTip("\n".join(str(p) for p in self.latest_classic_output_paths))
        InfoBar.success("\u7ecf\u5178\u53f0\u8bcd\u91c7\u96c6\u5b8c\u6210", f"\u8f93\u51fa {len(self.latest_classic_output_paths)} \u4e2a\u6587\u4ef6", parent=self, duration=5000)

    def classic_automation_failed(self, message: str) -> None:
        self.classic_run_button.setEnabled(True)
        self.classic_status.setText("\u6267\u884c\u5931\u8d25")
        self.classic_progress_ring.setValue(0)
        self.classic_progress_label.setText("\u5931\u8d25")
        self.append_classic_log(message)
        InfoBar.error("\u7ecf\u5178\u53f0\u8bcd\u91c7\u96c6\u5931\u8d25", message, parent=self, duration=5000)

    def open_classic_output_file(self) -> None:
        if len(self.latest_classic_output_paths) > 1 and self.latest_classic_output_paths[0].parent:
            self.open_path(self.latest_classic_output_paths[0].parent)
        elif self.latest_classic_output_path:
            self.open_path(self.latest_classic_output_path)

    def reset_classic_panel(self) -> None:
        if self.classic_automation_worker and self.classic_automation_worker.isRunning():
            InfoBar.warning("\u4efb\u52a1\u8fd0\u884c\u4e2d", "\u7ecf\u5178\u53f0\u8bcd\u91c7\u96c6\u6267\u884c\u4e2d\uff0c\u6682\u65f6\u4e0d\u80fd\u91cd\u7f6e\u3002", parent=self, duration=3000)
            return
        self.latest_classic_output_path = None
        self.classic_status.setText("\u7b49\u5f85\u6267\u884c")
        self.classic_progress_ring.setValue(0)
        self.classic_progress_label.setText("0%")
        self.latest_classic_output_paths = []
        self.classic_open_button.setEnabled(False)
        self.classic_log.clear()
        for k in ["movies", "lines", "pages"]:
            self.classic_stat_labels[k].setText("0")
        self.classic_stat_labels["output"].setText("-")
        self.classic_stat_labels["output"].setToolTip("")

    # ── Parser Flow ───────────────────────────────────────────────────

    def select_parse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择字幕文件",
            "",
            "字幕文件 (*.srt *.ass)",
        )
        if not files:
            return

        validated_files: list[Path] = []
        skipped_small: list[str] = []
        skipped_suffix: list[str] = []
        skipped_invalid: list[str] = []
        min_file_size = MIN_VALID_SUBTITLE_BYTES
        for file in files:
            path = Path(file)
            suffix = path.suffix.lower()
            if suffix not in {".srt", ".ass"}:
                skipped_suffix.append(path.name)
                continue
            file_size = path.stat().st_size
            if file_size < min_file_size:
                skipped_small.append(f"{path.name} ({file_size / 1024:.1f} KB)")
                continue
            try:
                content = path.read_bytes()
                decoded_text = content.decode("utf-8", errors="ignore")
                if len(decoded_text.strip()) < 50:
                    skipped_invalid.append(f"{path.name}（内容过少，可能不是有效字幕）")
                    continue
                from ..engines.subtitle_engine import validate_is_simplified_chinese_english
                is_valid, msg = validate_is_simplified_chinese_english(decoded_text)
                if not is_valid:
                    skipped_invalid.append(f"{path.name}（{msg}）")
                    continue
            except Exception as e:
                skipped_invalid.append(f"{path.name}（读取失败：{e}）")
                continue
            validated_files.append(path)

        if skipped_small or skipped_suffix or skipped_invalid:
            parts = []
            if skipped_suffix:
                parts.append("格式不符（仅支持 .srt/.ass）：\n" + "\n".join(skipped_suffix))
            if skipped_small:
                parts.append("文件过小（< 100 KB 视作无效电影字幕）：\n" + "\n".join(skipped_small))
            if skipped_invalid:
                parts.append("内容校验未通过：\n" + "\n".join(skipped_invalid))
            InfoBar.warning("文件校验提示", "\n\n".join(parts), parent=self, position=InfoBarPosition.TOP, duration=5000)

        if not validated_files:
            if skipped_small or skipped_suffix or skipped_invalid:
                self.parse_log.clear()
                self._reset_parse_stats()
                self.parse_status.setText("文件校验未通过")
                for item in skipped_suffix:
                    self.parse_log.append(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 跳过：{item} / 格式不符（仅支持 .srt/.ass）"
                    )
                for item in skipped_small:
                    self.parse_log.append(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 跳过：{item} / 文件过小"
                    )
                for item in skipped_invalid:
                    self.parse_log.append(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 跳过：{item}"
                    )
            return

        try:
            data_dir = self._ensure_storage_for_current_data_dir()
        except ValueError as exc:
            InfoBar.warning("数据目录无效", str(exc), parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        self.parse_log.clear()
        self._reset_parse_stats()
        self.parse_status.setText(f"解析中：共 {len(validated_files)} 个文件")
        self.parse_stat_labels["total"].setText(str(len(validated_files)))
        if skipped_suffix or skipped_small or skipped_invalid:
            for item in skipped_suffix:
                self.parse_log.append(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 跳过：{item} / 格式不符（仅支持 .srt/.ass）"
                )
            for item in skipped_small:
                self.parse_log.append(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 跳过：{item} / 文件过小"
                )
            for item in skipped_invalid:
                self.parse_log.append(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 跳过：{item}"
                )
        self.parse_button.setEnabled(False)
        output_dir = data_dir / "parsed"
        env_settings = AppSettings.from_env(self.env_bootstrap.env_path)
        self.parser_worker = ParserWorker(
            validated_files,
            output_dir,
            env_settings.tmdb_token,
            self.unicloud_import_switch.isChecked(),
        )
        self.parser_worker.log_message.connect(self.parse_log.append)
        self.parser_worker.progress_changed.connect(self.update_parse_progress)
        self.parser_worker.finished_success.connect(self.parse_finished)
        self.parser_worker.finished_error.connect(self.parse_failed)
        self.parser_worker.start()

    def _reset_parse_stats(self) -> None:
        if not hasattr(self, "parse_stat_labels"):
            return
        for key, value in self.parse_stat_labels.items():
            value.setText("-" if key == "output" else "0")
            value.setToolTip("")
        self.parse_progress_ring.setValue(0)
        self.parse_progress_label.setText("0%")

    def update_parse_progress(self, current: int, total: int, current_file: str) -> None:
        percent = int(current / total * 100) if total else 0
        self.parse_progress_ring.setValue(percent)
        self.parse_progress_label.setText(f"{percent}%")
        if current < total:
            self.parse_status.setText(f"{current}/{total} 解析中：{current_file}")
        else:
            self.parse_status.setText(f"{current}/{total} 解析完成")

    def parse_finished(self, result: dict) -> None:
        self.parse_button.setEnabled(True)
        self.parse_progress_ring.setValue(100)
        self.parse_progress_label.setText("100%")
        success_count = result.get("successCount", 0)
        failure_count = result.get("failureCount", 0)
        self.parse_status.setText(
            f"完成：成功 {success_count}，失败 {failure_count}"
        )
        self.parse_stat_labels["total"].setText(str(result.get("totalCount", 0)))
        self.parse_stat_labels["success"].setText(str(success_count))
        self.parse_stat_labels["failed"].setText(str(failure_count))
        self.parse_stat_labels["exported"].setText(str(result.get("exportCount", 0)))
        output_paths = [str(path) for path in (result.get("outputPaths") or []) if str(path or "").strip()]
        self.parse_stat_labels["output"].setText("\n".join(output_paths) if output_paths else "-")
        self.parse_stat_labels["output"].setToolTip("\n".join(output_paths))
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.parse_log.append(
            f"[{stamp}] 解析汇总：共 {result.get('totalCount', 0)} 个文件，"
            f"成功 {success_count}，"
            f"失败 {failure_count}，"
            f"导出字幕 {result.get('exportCount', 0)} 条"
        )
        movies_paths = result.get("moviesPaths") or [result.get("moviesPath")]
        movies_format_label = (
            "uniCloud jsonl"
            if result.get("moviesFormat") == "unicloud-jsonl"
            else "JSON 数组"
        )
        if len(movies_paths) > 1:
            self.parse_log.append(
                f"[{stamp}] 电影 JSON：{len(movies_paths)} 个文件（{movies_format_label}，45MB 拆分）"
            )
            for path in movies_paths:
                self.parse_log.append(f"[{stamp}] - {path}")
        else:
            self.parse_log.append(f"[{stamp}] 电影 JSON：{movies_paths[0]}（{movies_format_label}）")
        if result.get("moviesOversizedRecords"):
            self.parse_log.append(
                f"[{stamp}] 提示：{result.get('moviesOversizedRecords')} 条电影记录单条超过拆分限制，已单独写入文件"
            )
        subtitles_paths = result.get("subtitlesPaths") or [result.get("subtitlesPath")]
        format_label = (
            "uniCloud jsonl"
            if result.get("subtitlesFormat") == "unicloud-jsonl"
            else "JSON 数组"
        )
        if len(subtitles_paths) > 1:
            self.parse_log.append(
                f"[{stamp}] 字幕 JSON：{len(subtitles_paths)} 个文件（{format_label}，45MB 拆分）"
            )
            for path in subtitles_paths:
                self.parse_log.append(f"[{stamp}] - {path}")
        else:
            self.parse_log.append(f"[{stamp}] 字幕 JSON：{subtitles_paths[0]}（{format_label}）")
        if result.get("subtitleOversizedRecords"):
            self.parse_log.append(
                f"[{stamp}] 提示：{result.get('subtitleOversizedRecords')} 条字幕记录单条超过拆分限制，已单独写入文件"
            )
        self.refresh_task_center()

    def parse_failed(self, message: str) -> None:
        self.parse_button.setEnabled(True)
        self.parse_status.setText("解析失败")
        self.parse_progress_ring.setValue(0)
        self.parse_progress_label.setText("失败")
        self.parse_log.append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
        InfoBar.error("解析失败", message, parent=self, position=InfoBarPosition.TOP, duration=5000)

    # ── History ───────────────────────────────────────────────────────

    def _format_history_time(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = text.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return text[:19].replace("T", " ")

    def refresh_history(self) -> None:
        try:
            self._ensure_storage_for_current_data_dir()
        except ValueError:
            return
        rows = self.storage.list_task_runs()
        self.history_table.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            output_dir = Path(item.get("result", {}).get("downloadDir", ""))
            values = [
                item.get("year", ""),
                item.get("limit", ""),
                self._format_history_time(item.get("started_at", "")),
                self._format_history_time(item.get("finished_at", "")),
                str(output_dir) if str(output_dir) != "." else "",
            ]
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                table_item.setToolTip(str(value))
                if column in {0, 1}:
                    table_item.setTextAlignment(Qt.AlignCenter)
                self.history_table.setItem(row_index, column, table_item)
        self._filter_history_table()

    # ── Settings Actions ──────────────────────────────────────────────

    def browse_data_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择数据目录", self.data_dir_input.text())
        if directory:
            self.data_dir_input.setText(directory)

    def _save_captcha_sound_to_env(self, checked: bool) -> None:
        """保存验证码提示音开关到 .env 文件"""
        env_path = self.env_bootstrap.env_path
        key = "CAPTCHA_SOUND_ENABLED"
        value = "true" if checked else "false"
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        updated = False
        for index, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[index] = f"{key}={value}"
                updated = True
                break
        if not updated:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"{key}={value}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.environ[key] = value
        self.settings = AppSettings.from_env(self.env_bootstrap.env_path)

    def save_data_dir_to_env(self) -> None:
        try:
            data_dir = self._current_data_dir()
        except ValueError as exc:
            InfoBar.warning("数据目录无效", str(exc), parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        data_dir.mkdir(parents=True, exist_ok=True)
        env_path = self.env_bootstrap.env_path
        key = "SUBTITLE_COLLECTION_DATA_DIR"
        value = str(data_dir)
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        updated = False
        for index, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[index] = f"{key}={value}"
                updated = True
                break
        if not updated:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"{key}={value}")

        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.environ[key] = value
        self.settings = AppSettings.from_env(self.env_bootstrap.env_path)
        self.config_check = evaluate_config(self.settings, self.env_bootstrap.env_path)
        self.storage = AppStorage(data_dir / "subtitle_info_collection.sqlite3")
        self.refresh_history()
        self.refresh_task_center()
        InfoBar.success("已保存", f"数据目录已保存到 {env_path}", parent=self, position=InfoBarPosition.TOP, duration=3000)

    def reset_history(self) -> None:
        if self.collector_worker and self.collector_worker.isRunning():
            InfoBar.warning("任务运行中", "采集任务运行中，暂时不能重置历史。", parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        answer = QMessageBox.question(
            self,
            "重置历史",
            "确定清空采集历史记录吗？输出文件会保留。",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._ensure_storage_for_current_data_dir()
        except ValueError as exc:
            InfoBar.warning("数据目录无效", str(exc), parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        self.storage.clear_task_runs()
        self.refresh_history()
        self.refresh_task_center()
        self.collect_status.setText("历史记录已清空")
        InfoBar.success("已重置", "采集历史记录已清空。", parent=self, position=InfoBarPosition.TOP, duration=2000)

    def delete_output_files(self) -> None:
        if self.collector_worker and self.collector_worker.isRunning():
            InfoBar.warning("任务运行中", "采集任务运行中，暂时不能删除输出文件。", parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        try:
            data_dir = self._ensure_storage_for_current_data_dir()
        except ValueError as exc:
            InfoBar.warning("数据目录无效", str(exc), parent=self, position=InfoBarPosition.TOP, duration=3000)
            return

        output_dir = (data_dir / "output").resolve()
        try:
            output_dir.relative_to(data_dir)
        except ValueError:
            QMessageBox.critical(self, "路径异常", "输出目录不在当前数据目录内，已取消删除。")
            return
        if output_dir.name != "output":
            QMessageBox.critical(self, "路径异常", "输出目录名称异常，已取消删除。")
            return

        answer = QMessageBox.warning(
            self,
            "删除输出文件",
            f"确定删除 {output_dir} 并清空采集历史记录吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.storage.clear_task_runs()
        for label in self.collect_stat_labels.values():
            label.setText("0")
        self.refresh_history()
        self.refresh_task_center()
        self.collect_status.setText("输出文件已删除，历史记录已清空")
        InfoBar.success("已删除", "采集输出文件和历史记录已清理完成。", parent=self, position=InfoBarPosition.TOP, duration=3000)


def run_app(argv: list[str]) -> int:
    app = QApplication(argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()
