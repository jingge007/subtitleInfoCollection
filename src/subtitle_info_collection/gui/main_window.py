from __future__ import annotations

import base64
import os
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
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
from .worker import AutomationScriptWorker, CollectorWorker, ParserWorker


DEFAULT_WINDOW_WIDTH = 1100
DEFAULT_WINDOW_HEIGHT = 580
PAGE_MARGINS = (18, 8, 18, 8)
PAGE_SPACING = 8
CARD_VIEW_MARGINS = (14, 6, 14, 10)
CARD_HEADER_MARGINS = (14, 8, 14, 0)


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
        self.latest_automation_output_path: Path | None = None
        self.latest_automation_output_paths: list[Path] = []

        self.setWindowTitle("字幕采集工具")
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self._set_app_icon()
        self._apply_theme()

        self._dashboard_page = self._build_task_center_page()
        self._collector_page = self._build_collector_tab()
        self._parser_page = self._build_parser_tab()
        self._automation_page = self._build_automation_tab()
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
            self._automation_page, FIF.ROBOT, "自动化脚本", NavigationItemPosition.TOP,
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
            candidates.append(Path(_sys.executable).parent / "_internal" / "assets" / "head_logo.png")
        else:
            candidates.append(Path(__file__).resolve().parents[3] / "assets" / "head_logo.png")
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
        self.fallback_check.setChecked(True)
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
        self.collect_status = StrongBodyLabel("等待开始")
        self.collect_status.setStyleSheet(f"font-size: 15px; color: {TEXT};")
        self.collect_status.setWordWrap(True)
        self.collect_status.setMinimumWidth(260)
        self.collect_progress_label = CaptionLabel("0%")
        self.collect_progress_label.setStyleSheet(f"color: {TEXT_SOFT}; font-size: 12px;")
        progress_info.addWidget(self.collect_status)
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

    def _build_automation_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("automationPage")
        layout = self._page_layout(page)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = SubtitleLabel("自动化脚本")
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {TEXT};")
        subtitle = BodyLabel("运行 33 台词今日台词采集，结果保存到数据目录的 automation 文件夹")
        subtitle.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 12px;")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
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
        export_desc = CaptionLabel("开启后按 classic-line 导入规则解析、翻译补全英文，并按 45MB 拆分 jsonl 文件")
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
            ("output", "输出文件", ORANGE, ORANGE_SOFT, 360),
        ]:
            stat = QFrame(self)
            stat.setStyleSheet(
                f"background: {bg_color}; border: 1px solid {LINE_SOFT}; border-radius: 8px;"
            )
            stat.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            stat.setFixedWidth(width)
            stat.setFixedHeight(68 if key == "output" else 48)
            stat_layout = QVBoxLayout(stat)
            stat_layout.setContentsMargins(8, 5, 8, 5)
            stat_layout.setSpacing(1)
            stat_layout.setAlignment(Qt.AlignCenter)
            value = QLabel("0" if key != "output" else "-")
            value.setAlignment(Qt.AlignCenter)
            value.setWordWrap(True)
            if key == "output":
                value.setTextInteractionFlags(Qt.TextSelectableByMouse)
                value.setMinimumWidth(0)
                value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
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
            proxies=env_settings.proxies(),
        )
        self.collect_log.clear()
        self.collect_progress_ring.setValue(0)
        self.collect_progress_label.setText("0%")
        self.collect_status.setText("任务启动中")
        self.start_button.setEnabled(False)
        self._set_maintenance_enabled(False)
        self.collector_worker = CollectorWorker(config, self.storage.database_path)
        self.collector_worker.log_message.connect(self.append_collect_log)
        self.collector_worker.progress_changed.connect(self.update_collect_progress)
        self.collector_worker.verification_requested.connect(self.handle_verification_request)
        self.collector_worker.finished_success.connect(self.collection_finished)
        self.collector_worker.finished_error.connect(self.collection_failed)
        self.collector_worker.start()

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
        pixmap = QPixmap()
        pixmap.loadFromData(image_bytes)
        return pixmap

    def handle_verification_request(self, payload: dict) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("SubHD 验证码")
        dialog.setMinimumWidth(520)
        dialog.setStyleSheet(f"background: {SURFACE};")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.addWidget(StrongBodyLabel(payload.get("subtitleTitle") or payload.get("detailUrl") or "需要验证码"))
        image_data_uri = str(payload.get("verificationImageDataUri") or "")
        pixmap = self._pixmap_from_data_uri(image_data_uri)
        if not pixmap.isNull():
            image_label = QLabel(self)
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setStyleSheet(f"background: white; border: 1px solid {LINE_SOFT}; padding: 8px;")
            image_label.setPixmap(
                pixmap.scaled(360, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            layout.addWidget(image_label)
        browser = QTextBrowser()
        browser.setHtml(payload.get("verificationHtml") or "请打开详情页查看验证码。")
        browser.setMinimumHeight(200)
        code_input = LineEdit(self)
        suggested_code = str(payload.get("suggestedCode") or "").strip()
        if suggested_code:
            code_input.setText(suggested_code)
        code_input.setPlaceholderText("输入验证码")
        if suggested_code:
            confidence = float(payload.get("suggestedConfidence") or 0)
            layout.addWidget(CaptionLabel(f"OCR suggestion: {suggested_code} ({confidence:.0%})"))
        elif payload.get("ocrMessage"):
            layout.addWidget(CaptionLabel(str(payload.get("ocrMessage"))))
        buttons = QHBoxLayout()
        submit = PrimaryPushButton("提交", self)
        cancel = PushButton("跳过", self)
        open_detail = PushButton("打开详情页", self)
        open_detail.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(str(payload.get("detailUrl") or "")))
        )
        buttons.addWidget(submit)
        buttons.addWidget(cancel)
        buttons.addWidget(open_detail)
        buttons.addStretch(1)
        layout.addWidget(browser)
        layout.addWidget(code_input)
        layout.addLayout(buttons)
        submit.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        accepted = dialog.exec() == QDialog.Accepted
        if self.collector_worker:
            self.collector_worker.submit_verification(code_input.text().strip() if accepted else "")

    def collection_finished(self, result: dict) -> None:
        self.start_button.setEnabled(True)
        self._set_maintenance_enabled(True)
        self.collect_progress_ring.setValue(100)
        self.collect_progress_label.setText("100%")
        self.collect_status.setText("任务完成")
        self.show_result_summary(result)
        self.refresh_history()
        self.refresh_task_center()
        InfoBar.success(
            "采集完成",
            f"输出目录：{result.get('downloadDir', '')}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000,
        )

    def collection_failed(self, message: str) -> None:
        self.start_button.setEnabled(True)
        self._set_maintenance_enabled(True)
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
        self.automation_progress_ring.setValue(35)
        self.automation_progress_label.setText("执行中")
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
        self.automation_worker.finished_success.connect(self.automation_finished)
        self.automation_worker.finished_error.connect(self.automation_failed)
        self.automation_worker.start()

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
        self.parse_log.append(f"[{stamp}] 电影 JSON：{result.get('moviesPath')}")
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
