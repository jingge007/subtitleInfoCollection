from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import AppSettings, bootstrap_env_file, evaluate_config
from ..models import TaskConfig
from ..storage import AppStorage
from .worker import CollectorWorker, ParserWorker


PAGE_BG = "#F0F2F5"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F8FAFB"
LINE = "#D1D9E0"
LINE_SOFT = "#E4E9EF"
LINE_HOVER = "#B0BCCA"
TEXT = "#1A1D23"
TEXT_MUTED = "#5A6272"
TEXT_SOFT = "#8B95A5"
PRIMARY = "#4F6EF7"
PRIMARY_SOFT = "#EEF1FE"
PRIMARY_DARK = "#3B54D4"
PRIMARY_LIGHT = "#7B92FA"
GREEN = "#10A050"
GREEN_SOFT = "#E8F8EF"
ORANGE = "#D97706"
ORANGE_SOFT = "#FFF8ED"
RED = "#E04040"
RED_SOFT = "#FDEEEE"
LOG_BG = "#0D1117"
LOG_TEXT = "#C9D1D9"
DANGER_BG = "#FEF5F5"
DANGER_BORDER = "#F5B8B8"
DANGER_TEXT = "#991B1B"
DANGER_TEXT_MUTED = "#B91C1C"


class MainWindow(QMainWindow):
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
        self.nav_buttons: list[QPushButton] = []

        self.setWindowTitle("字幕采集工具")
        self.resize(1320, 840)
        self._set_app_icon()
        self._apply_style()

        self.setCentralWidget(self._build_shell())
        self.refresh_history()
        self.refresh_task_center()

    # ── App Icon ─────────────────────────────────────────────────────

    def _set_app_icon(self) -> None:
        import sys as _sys

        candidates: list[Path] = []
        if getattr(_sys, "frozen", False):
            candidates.append(Path(_sys.executable).parent / "assets" / "head_logo.ico")
            candidates.append(Path(_sys.executable).parent / "_internal" / "assets" / "head_logo.ico")
        else:
            candidates.append(Path(__file__).resolve().parents[3] / "assets" / "head_logo.ico")
        for icon_path in candidates:
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
                return

    # ── Global Stylesheet ─────────────────────────────────────────────

    def _apply_style(self) -> None:
        self.setStyleSheet(f"""
            * {{
                font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
                font-size: 13px;
                color: {TEXT};
            }}
            QMainWindow {{
                background: {PAGE_BG};
            }}

            /* ── Sidebar ── */
            QFrame#sidebar {{
                background: {SURFACE};
                border-right: 1px solid {LINE};
            }}
            QLabel#brandTitle {{
                color: {PRIMARY};
                font-size: 20px;
                font-weight: 800;
            }}
            QLabel#brandSubtitle {{
                color: {TEXT_MUTED};
                font-size: 12px;
            }}
            QFrame#sidebarDivider {{
                background: {LINE_SOFT};
                max-height: 1px;
                min-height: 1px;
            }}
            QPushButton#navButton {{
                background: transparent;
                color: {TEXT};
                border: none;
                border-radius: 8px;
                padding: 10px 14px;
                text-align: left;
                font-weight: 500;
                font-size: 13px;
            }}
            QPushButton#navButton:hover {{
                background: {SURFACE_ALT};
                color: {TEXT};
            }}
            QPushButton#navButton:checked {{
                background: {PRIMARY_SOFT};
                color: {PRIMARY_DARK};
                font-weight: 700;
                border-left: 3px solid {PRIMARY};
                padding-left: 11px;
            }}
            QLabel#sidebarHint {{
                color: {TEXT_SOFT};
                font-size: 11px;
            }}

            /* ── Page titles ── */
            QLabel#pageTitle {{
                color: {TEXT};
                font-size: 24px;
                font-weight: 800;
            }}
            QLabel#sectionTitle {{
                color: {TEXT};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#mutedText {{
                color: {TEXT_MUTED};
                font-size: 13px;
            }}
            QLabel#metricValue {{
                color: {TEXT};
                font-size: 24px;
                font-weight: 800;
            }}
            QLabel#metricLabel {{
                color: {TEXT_MUTED};
                font-size: 12px;
            }}
            QLabel#badgeGreen {{
                background: {GREEN_SOFT};
                color: {GREEN};
                border-radius: 8px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#badgeOrange {{
                background: {ORANGE_SOFT};
                color: {ORANGE};
                border-radius: 8px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#badgeRed {{
                background: {RED_SOFT};
                color: {RED};
                border-radius: 8px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#badgeBlue {{
                background: {PRIMARY_SOFT};
                color: {PRIMARY};
                border-radius: 8px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#badgeGray {{
                background: {SURFACE_ALT};
                color: {TEXT_MUTED};
                border-radius: 8px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 700;
            }}

            /* ── Panels & Cards ── */
            QFrame#panel, QFrame#metricCard, QFrame#statusCard, QFrame#recordCard, QGroupBox {{
                background: {SURFACE};
                border: 1px solid {LINE};
                border-radius: 10px;
            }}
            QFrame#dangerZone {{
                background: {DANGER_BG};
                border: 1px solid {DANGER_BORDER};
                border-radius: 10px;
            }}

            /* ── GroupBox ── */
            QGroupBox {{
                margin-top: 18px;
                padding: 16px 14px 14px;
                font-weight: 700;
                font-size: 13px;
                color: {TEXT};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 8px;
                color: {PRIMARY};
            }}

            /* ── Inputs ── */
            QLineEdit, QSpinBox, QTextEdit, QTextBrowser {{
                background: {SURFACE};
                border: 1px solid {LINE};
                border-radius: 8px;
                color: {TEXT};
                font-size: 13px;
            }}
            QLineEdit:hover, QSpinBox:hover {{
                border-color: {LINE_HOVER};
            }}
            QLineEdit:focus, QSpinBox:focus {{
                border-color: {PRIMARY};
                border-width: 2px;
                padding: 2px 7px;
            }}
            QLineEdit, QSpinBox {{
                min-height: 32px;
                padding: 4px 10px;
                font-size: 13px;
            }}
            QSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 28px;
                min-height: 14px;
                border-left: 1px solid {LINE};
                border-bottom: 1px solid {LINE};
                border-top-right-radius: 7px;
                background: {SURFACE_ALT};
            }}
            QSpinBox::up-button:hover {{
                background: {PRIMARY_SOFT};
            }}
            QSpinBox::up-button:pressed {{
                background: {PRIMARY};
            }}
            QSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 28px;
                min-height: 14px;
                border-left: 1px solid {LINE};
                border-bottom-right-radius: 7px;
                background: {SURFACE_ALT};
            }}
            QSpinBox::down-button:hover {{
                background: {PRIMARY_SOFT};
            }}
            QSpinBox::down-button:pressed {{
                background: {PRIMARY};
            }}
            QSpinBox::up-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-bottom: 6px solid {TEXT_MUTED};
                width: 0px;
                height: 0px;
            }}
            QSpinBox::up-arrow:hover {{
                border-bottom-color: {PRIMARY};
            }}
            QSpinBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid {TEXT_MUTED};
                width: 0px;
                height: 0px;
            }}
            QSpinBox::down-arrow:hover {{
                border-top-color: {PRIMARY};
            }}

            /* ── CheckBox ── */
            QCheckBox {{
                spacing: 10px;
                color: {TEXT};
                font-weight: 500;
                font-size: 13px;
                min-height: 24px;
            }}
            QCheckBox::indicator {{
                width: 22px;
                height: 22px;
                border-radius: 6px;
                border: 2px solid {LINE};
                background: {SURFACE};
            }}
            QCheckBox::indicator:hover {{
                border-color: {PRIMARY_LIGHT};
                background: {PRIMARY_SOFT};
            }}
            QCheckBox::indicator:checked {{
                background: {PRIMARY};
                border-color: {PRIMARY};
            }}
            QCheckBox::indicator:checked:hover {{
                background: {PRIMARY_DARK};
                border-color: {PRIMARY_DARK};
            }}

            /* ── Buttons ── */
            QPushButton {{
                background: {PRIMARY};
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: {PRIMARY_DARK};
            }}
            QPushButton:pressed {{
                background: #2E46C0;
            }}
            QPushButton:disabled {{
                background: #C8CDD8;
                color: #F5F6F8;
            }}
            QPushButton#secondaryButton {{
                background: {SURFACE};
                color: {TEXT};
                border: 1px solid {LINE};
            }}
            QPushButton#secondaryButton:hover {{
                background: {SURFACE_ALT};
                border-color: {LINE_HOVER};
            }}
            QPushButton#secondaryButton:pressed {{
                background: #E4E9EF;
            }}
            QPushButton#ghostButton {{
                background: transparent;
                color: {TEXT_MUTED};
                border: 1px solid {LINE_SOFT};
            }}
            QPushButton#ghostButton:hover {{
                background: {SURFACE_ALT};
                color: {TEXT};
                border-color: {LINE};
            }}
            QPushButton#dangerButton {{
                background: {RED};
            }}
            QPushButton#dangerButton:hover {{
                background: #C53030;
            }}
            QPushButton#dangerButton:pressed {{
                background: #9B2020;
            }}

            /* ── ProgressBar ── */
            QProgressBar {{
                border: 1px solid {LINE};
                border-radius: 10px;
                background: {SURFACE_ALT};
                text-align: center;
                height: 22px;
                font-size: 11px;
                color: {TEXT};
                font-weight: 600;
            }}
            QProgressBar::chunk {{
                border-radius: 9px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {PRIMARY}, stop:1 {PRIMARY_LIGHT});
            }}

            /* ── Tables ── */
            QHeaderView::section {{
                background: {SURFACE_ALT};
                border: none;
                border-bottom: 2px solid {LINE};
                padding: 9px 12px;
                font-weight: 700;
                font-size: 12px;
                color: {TEXT};
            }}
            QTableWidget {{
                background: {SURFACE};
                gridline-color: {LINE_SOFT};
                alternate-background-color: {SURFACE_ALT};
                outline: 0;
                border: none;
                font-size: 12px;
                color: {TEXT};
            }}
            QTableWidget#dataTable {{
                selection-background-color: {PRIMARY_SOFT};
                selection-color: {TEXT};
            }}

            /* ── Log Panel ── */
            QTextEdit#logPanel {{
                background: {LOG_BG};
                border: 1px solid #21262D;
                border-radius: 8px;
                color: {LOG_TEXT};
                font-family: "Cascadia Code", "JetBrains Mono", "Consolas", monospace;
                font-size: 12px;
                padding: 6px;
            }}

            /* ── ScrollBar ── */
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #C8CDD8;
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #A0A8B8;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: transparent;
            }}

            QScrollBar:horizontal {{
                background: transparent;
                height: 8px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: #C8CDD8;
                border-radius: 4px;
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: #A0A8B8;
            }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
        """)

    # ── Shell (Sidebar + Stack) ──────────────────────────────────────

    def _build_shell(self) -> QWidget:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 22, 18, 18)
        sidebar_layout.setSpacing(6)

        brand = QLabel("字幕采集工具")
        brand.setObjectName("brandTitle")
        brand_subtitle = QLabel("专业数据运维台")
        brand_subtitle.setObjectName("brandSubtitle")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(brand_subtitle)
        sidebar_layout.addSpacing(14)

        divider = QFrame()
        divider.setObjectName("sidebarDivider")
        sidebar_layout.addWidget(divider)
        sidebar_layout.addSpacing(8)

        nav_items = [
            ("工作台", self._build_task_center_page),
            ("采集任务", self._build_collector_tab),
            ("字幕解析", self._build_parser_tab),
            ("历史记录", self._build_history_tab),
            ("设置与维护", self._build_settings_tab),
        ]
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"QStackedWidget {{ background: {PAGE_BG}; }}")
        for index, (title, _) in enumerate(nav_items):
            button = QPushButton(title)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page_index=index: self.switch_page(page_index))
            self.nav_buttons.append(button)
            sidebar_layout.addWidget(button)
        for _, builder in nav_items:
            self.stack.addWidget(builder())
        sidebar_layout.addStretch(1)
        hint = QLabel("密钥仅从本机 .env 读取")
        hint.setObjectName("sidebarHint")
        hint.setWordWrap(True)
        sidebar_layout.addWidget(hint)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack, 1)

        self.switch_page(0)
        return root

    def switch_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
        if index == 0:
            self.refresh_task_center()
        elif index == 3:
            self.refresh_history()

    # ── Dashboard ─────────────────────────────────────────────────────

    def _build_task_center_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"QWidget {{ background: {PAGE_BG}; }}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        self.dashboard_title = QLabel("任务工作台")
        self.dashboard_title.setObjectName("pageTitle")
        subtitle = QLabel("集中查看配置状态、近期任务、输出位置和常用操作。")
        subtitle.setObjectName("mutedText")
        subtitle.setWordWrap(True)
        title_col.addWidget(self.dashboard_title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        header_right = QHBoxLayout()
        header_right.setSpacing(8)
        self.dashboard_ready_label = QLabel()
        header_right.addWidget(self.dashboard_ready_label)
        start_button = QPushButton("开始采集")
        start_button.clicked.connect(lambda: self.switch_page(1))
        parse_button = QPushButton("解析本地字幕")
        parse_button.setObjectName("secondaryButton")
        parse_button.clicked.connect(lambda: self.switch_page(2))
        header_right.addWidget(start_button)
        header_right.addWidget(parse_button)
        header.addLayout(header_right)

        self.metric_labels: dict[str, QLabel] = {}
        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        metric_items = [
            ("runs", "最近任务"),
            ("movies", "电影数"),
            ("best", "最佳字幕"),
            ("failed", "失败记录"),
            ("downloads", "下载成功"),
        ]
        for key, label in metric_items:
            card, value_label = self._metric_card(label)
            self.metric_labels[key] = value_label
            metrics.addWidget(card, 1)

        body_row = QHBoxLayout()
        body_row.setSpacing(12)
        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        config_panel = self._panel("配置预检")
        self.config_cards_layout = QGridLayout()
        self.config_cards_layout.setSpacing(8)
        config_panel.layout().addLayout(self.config_cards_layout)

        library_panel = self._panel("最近字幕资料")
        self.latest_records_layout = QVBoxLayout()
        self.latest_records_layout.setSpacing(8)
        library_panel.layout().addLayout(self.latest_records_layout)

        left_col.addWidget(config_panel)
        left_col.addWidget(library_panel, 1)

        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        source_panel = self._panel("字幕源状态")
        self.source_status_layout = QGridLayout()
        self.source_status_layout.setSpacing(8)
        source_panel.layout().addLayout(self.source_status_layout)

        output_panel = self._panel("输出与维护")
        self.latest_output_label = QLabel("暂无输出")
        self.latest_output_label.setObjectName("mutedText")
        self.latest_output_label.setWordWrap(True)
        self.latest_output_label.setMinimumWidth(0)
        self.latest_output_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        output_actions = QHBoxLayout()
        output_actions.setSpacing(8)
        open_output = QPushButton("打开最近输出")
        open_output.setObjectName("secondaryButton")
        open_output.clicked.connect(self.open_latest_output_dir)
        open_data = QPushButton("数据目录")
        open_data.setObjectName("ghostButton")
        open_data.clicked.connect(lambda: self.open_path(self._current_data_dir()))
        rerun_button = QPushButton("复用最近任务")
        rerun_button.setObjectName("ghostButton")
        rerun_button.clicked.connect(self.prepare_latest_run)
        output_actions.addWidget(open_output)
        output_actions.addWidget(open_data)
        output_actions.addWidget(rerun_button)
        output_actions.addStretch(1)
        output_panel.layout().addWidget(self.latest_output_label)
        output_panel.layout().addLayout(output_actions)

        right_col.addWidget(source_panel)
        right_col.addWidget(output_panel, 1)

        body_row.addLayout(left_col, 2)
        body_row.addLayout(right_col, 1)

        layout.addLayout(header)
        layout.addLayout(metrics)
        layout.addLayout(body_row, 1)
        return page

    # ── Panels & Cards Helpers ────────────────────────────────────────

    def _panel(self, title: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        return panel

    def _metric_card(self, label: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setObjectName("metricCard")
        card.setFixedHeight(72)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        value = QLabel("0")
        value.setObjectName("metricValue")
        caption = QLabel(label)
        caption.setObjectName("metricLabel")
        layout.addWidget(value)
        layout.addWidget(caption)
        return card, value

    def _status_card(self, title: str, value: str, detail: str, ok: bool | None = True) -> QFrame:
        card = QFrame()
        card.setObjectName("statusCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        heading = QLabel(title)
        heading.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {TEXT};")
        badge = QLabel(value)
        if ok is True:
            badge.setObjectName("badgeGreen")
        elif ok is False:
            badge.setObjectName("badgeOrange")
        else:
            badge.setObjectName("badgeBlue")
        body = QLabel(detail)
        body.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED};")
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

    # ── Dashboard Refresh ─────────────────────────────────────────────

    def refresh_task_center(self) -> None:
        if not hasattr(self, "config_cards_layout"):
            return
        self.settings = AppSettings.from_env(self.env_bootstrap.env_path)
        self.config_check = evaluate_config(self.settings, self.env_bootstrap.env_path)
        self.task_summary = self.storage.task_center_summary()
        totals = self.task_summary.get("totals", {})
        for key, label in self.metric_labels.items():
            label.setText(str(totals.get(key, 0)))

        if self.config_check.ready:
            self.dashboard_ready_label.setObjectName("badgeGreen")
            self.dashboard_ready_label.setText("配置可用")
        else:
            self.dashboard_ready_label.setObjectName("badgeOrange")
            self.dashboard_ready_label.setText("配置待完善")

        self._refresh_config_cards()
        self._refresh_latest_records()
        self._refresh_source_status()

        package_path = self.task_summary.get("package_path") or ""
        self.latest_output_label.setText(package_path or f"数据目录：{self.settings.data_dir}")

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
        self._clear_layout(self.latest_records_layout)
        records = self.task_summary.get("latest_records") or []
        if not records:
            empty = QLabel("暂无字幕结果。完成一次采集后，这里会展示电影式资料卡。")
            empty.setObjectName("mutedText")
            empty.setWordWrap(True)
            self.latest_records_layout.addWidget(empty)
            self.latest_records_layout.addStretch(1)
            return
        for record in records[:4]:
            card = QFrame()
            card.setObjectName("recordCard")
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            layout = QGridLayout(card)
            layout.setContentsMargins(10, 8, 10, 8)
            layout.setHorizontalSpacing(12)
            layout.setVerticalSpacing(2)
            title = QLabel(record.get("movieTitleZh") or record.get("movieTitle") or "未命名电影")
            title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {TEXT};")
            title.setWordWrap(True)
            meta = QLabel(f"{record.get('provider', '-')} · {record.get('totalScore', 0)}")
            meta.setStyleSheet(f"font-size: 12px; color: {TEXT_MUTED};")
            subtitle = QLabel(record.get("subtitleTitle") or "字幕标题缺失")
            subtitle.setStyleSheet(f"font-size: 12px; color: {TEXT_MUTED};")
            subtitle.setWordWrap(True)
            layout.addWidget(title, 0, 0)
            layout.addWidget(meta, 0, 1, Qt.AlignRight)
            layout.addWidget(subtitle, 1, 0, 1, 2)
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
                index,
                0,
            )

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
        self.switch_page(1)

    # ── Collector Tab ─────────────────────────────────────────────────

    def _build_collector_tab(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"QWidget {{ background: {PAGE_BG}; }}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel("采集任务")
        title.setObjectName("pageTitle")
        subtitle = QLabel("选择年份、Top 数量、字幕源和下载策略，运行采集工作流。")
        subtitle.setObjectName("mutedText")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form_group = QGroupBox("采集参数")
        form = QGridLayout(form_group)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.year_spin = QSpinBox()
        self.year_spin.setRange(1900, datetime.now().year + 1)
        self.year_spin.setValue(datetime.now().year)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 500)
        self.limit_spin.setValue(100)

        disabled_providers = set(self.settings.provider_disabled)
        self.subhd_check = QCheckBox("SubHD")
        self.assrt_check = QCheckBox("ASSRT")
        self.opensubtitles_check = QCheckBox("OpenSubtitles")
        provider_checks = {
            "subhd": self.subhd_check,
            "assrt": self.assrt_check,
            "opensubtitles": self.opensubtitles_check,
        }
        for provider, checkbox in provider_checks.items():
            checkbox.setChecked(provider not in disabled_providers)

        self.fallback_check = QCheckBox("源兜底")
        self.fallback_check.setChecked(True)
        self.download_check = QCheckBox("下载字幕")
        self.download_check.setChecked(True)

        self.start_button = QPushButton("开始采集")
        self.start_button.clicked.connect(self.start_collection)

        form.addWidget(QLabel("年份"), 0, 0)
        form.addWidget(self.year_spin, 0, 1)
        form.addWidget(QLabel("Top 数量"), 0, 2)
        form.addWidget(self.limit_spin, 0, 3)
        form.addWidget(self.start_button, 0, 5)
        form.addWidget(QLabel("字幕源"), 1, 0)
        form.addWidget(self.subhd_check, 1, 1)
        form.addWidget(self.assrt_check, 1, 2)
        form.addWidget(self.opensubtitles_check, 1, 3)
        form.addWidget(self.fallback_check, 1, 4)
        form.addWidget(self.download_check, 1, 5)
        form.setColumnStretch(4, 1)

        monitor_row = QHBoxLayout()
        monitor_row.setSpacing(10)

        status_panel = QFrame()
        status_panel.setObjectName("panel")
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(14, 12, 14, 14)
        status_layout.setSpacing(8)
        status_title = QLabel("任务状态")
        status_title.setObjectName("sectionTitle")
        self.collect_status = QLabel("等待开始")
        self.collect_progress = QProgressBar()
        self.collect_result_table = QTableWidget(0, 2)
        self.collect_result_table.setObjectName("dataTable")
        self.collect_result_table.setHorizontalHeaderLabels(["指标", "值"])
        self._configure_table(self.collect_result_table)
        self.collect_result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.collect_result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        status_layout.addWidget(status_title)
        status_layout.addWidget(self.collect_status)
        status_layout.addWidget(self.collect_progress)
        status_layout.addWidget(self.collect_result_table)

        log_panel = self._panel("采集日志")
        log_header = QHBoxLayout()
        log_header.setSpacing(8)
        log_title = QLabel("采集日志")
        log_title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {TEXT};")
        self.copy_collect_log_button = QPushButton("复制日志")
        self.copy_collect_log_button.setObjectName("secondaryButton")
        self.copy_collect_log_button.clicked.connect(self.copy_collect_log)
        log_header.addWidget(log_title)
        log_header.addStretch(1)
        log_header.addWidget(self.copy_collect_log_button)

        self.collect_log = QTextEdit()
        self.collect_log.setObjectName("logPanel")
        self.collect_log.setReadOnly(True)
        log_panel.layout().addLayout(log_header)
        log_panel.layout().addWidget(self.collect_log)

        monitor_row.addWidget(status_panel, 1)
        monitor_row.addWidget(log_panel, 2)

        layout.addWidget(form_group)
        layout.addLayout(monitor_row, 1)
        return page

    # ── Parser Tab ────────────────────────────────────────────────────

    def _build_parser_tab(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"QWidget {{ background: {PAGE_BG}; }}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = QLabel("字幕解析")
        title.setObjectName("pageTitle")
        subtitle = QLabel("选择本地 SRT/ASS 文件，解析双语字幕并导出电影 JSON 与字幕 JSON。")
        subtitle.setObjectName("mutedText")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        action_panel = self._panel("文件选择")
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.parse_button = QPushButton("选择 SRT/ASS 文件")
        self.parse_button.clicked.connect(self.select_parse_files)
        self.parse_status = QLabel("等待文件")
        actions.addWidget(self.parse_button)
        actions.addWidget(self.parse_status, 1)
        action_panel.layout().addLayout(actions)

        result_panel = self._panel("解析结果")
        self.parse_table = QTableWidget(0, 6)
        self.parse_table.setObjectName("dataTable")
        self.parse_table.setHorizontalHeaderLabels(
            ["文件路径", "电影", "电影 ID", "原始", "导出", "状态/关键词"]
        )
        self._configure_table(self.parse_table)
        self.parse_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 6):
            self.parse_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        result_panel.layout().addWidget(self.parse_table)

        log_panel = self._panel("解析日志")
        self.parse_log = QTextEdit()
        self.parse_log.setObjectName("logPanel")
        self.parse_log.setReadOnly(True)
        log_panel.layout().addWidget(self.parse_log)

        layout.addWidget(action_panel)
        layout.addWidget(result_panel, 3)
        layout.addWidget(log_panel, 2)
        return page

    # ── History Tab ───────────────────────────────────────────────────

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"QWidget {{ background: {PAGE_BG}; }}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title = QLabel("历史记录")
        title.setObjectName("pageTitle")
        subtitle = QLabel("查看最近采集任务状态、参数、开始结束时间和输出目录。")
        subtitle.setObjectName("mutedText")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_row.addLayout(title_col, 1)
        refresh_button = QPushButton("刷新历史")
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self.refresh_history)
        header_row.addWidget(refresh_button)

        table_panel = self._panel("任务列表")
        self.history_table = QTableWidget(0, 7)
        self.history_table.setObjectName("dataTable")
        self.history_table.setHorizontalHeaderLabels(
            ["ID", "状态", "年份", "Top", "开始时间", "结束时间", "输出目录"]
        )
        self._configure_table(self.history_table)
        for column in range(0, 6):
            self.history_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        table_panel.layout().addWidget(self.history_table)

        layout.addLayout(header_row)
        layout.addWidget(table_panel, 1)
        return page

    # ── Settings Tab ──────────────────────────────────────────────────

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"QWidget {{ background: {PAGE_BG}; }}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("设置与维护")
        title.setObjectName("pageTitle")
        subtitle = QLabel("管理数据目录与本地维护操作，密钥和请求策略仅从 .env 读取。")
        subtitle.setObjectName("mutedText")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        config_panel = self._panel("本机配置")
        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(10)
        cfg_row.addWidget(QLabel("数据目录"))
        self.data_dir_input = QLineEdit(str(self.settings.data_dir))
        cfg_row.addWidget(self.data_dir_input, 1)
        browse_button = QPushButton("选择")
        browse_button.setObjectName("secondaryButton")
        browse_button.clicked.connect(self.browse_data_dir)
        save_button = QPushButton("保存")
        save_button.clicked.connect(self.save_data_dir_to_env)
        cfg_row.addWidget(browse_button)
        cfg_row.addWidget(save_button)
        config_panel.layout().addLayout(cfg_row)

        tips_panel = self._panel("配置提示")
        tips_grid = QGridLayout()
        tips_grid.setSpacing(10)
        tips_items = [
            (".env 密钥", "只读", "TMDB_TOKEN、ASSRT_TOKEN、OpenSubtitles 账号均不在界面编辑。"),
            ("代理与间隔", "来自 .env", "HTTP_PROXY、HTTPS_PROXY、SUBTITLE_REQUEST_INTERVAL_MS。"),
            ("源优先级", "来自 .env", "SUBTITLE_PROVIDER_PRIORITY / SUBTITLE_PROVIDER_DISABLED。"),
        ]
        for col, (tip_title, tip_val, tip_detail) in enumerate(tips_items):
            card = QFrame()
            card.setObjectName("statusCard")
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(3)
            h = QLabel(tip_title)
            h.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {TEXT};")
            b = QLabel(tip_val)
            b.setObjectName("badgeBlue")
            d = QLabel(tip_detail)
            d.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED};")
            d.setWordWrap(True)
            d.setMinimumWidth(0)
            d.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            card_layout.addWidget(h)
            card_layout.addWidget(b)
            card_layout.addWidget(d)
            tips_grid.addWidget(card, 0, col)
        tips_panel.layout().addLayout(tips_grid)

        danger_panel = QFrame()
        danger_panel.setObjectName("dangerZone")
        danger_layout = QVBoxLayout(danger_panel)
        danger_layout.setContentsMargins(14, 12, 14, 14)
        danger_layout.setSpacing(8)
        danger_title = QLabel("数据维护")
        danger_title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {DANGER_TEXT};")
        danger_hint = QLabel("危险操作需要明确视觉隔离，运行中的采集任务会禁用这些操作，不会删除 parsed、数据库或缓存。")
        danger_hint.setStyleSheet(f"font-size: 12px; color: {DANGER_TEXT_MUTED};")
        danger_hint.setWordWrap(True)

        danger_btn_row = QHBoxLayout()
        danger_btn_row.setSpacing(10)
        self.reset_history_button = QPushButton("重置历史")
        self.reset_history_button.setObjectName("secondaryButton")
        self.reset_history_button.clicked.connect(self.reset_history)
        reset_desc = QLabel("清空采集历史记录，保留 output 文件。")
        reset_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self.delete_output_button = QPushButton("删除输出文件")
        self.delete_output_button.setObjectName("dangerButton")
        self.delete_output_button.clicked.connect(self.delete_output_files)
        delete_desc = QLabel("删除 数据目录/output 并清空采集历史。不会删除 parsed、数据库或缓存。")
        delete_desc.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")

        danger_btn_row.addWidget(self.reset_history_button)
        danger_btn_row.addWidget(reset_desc)
        danger_btn_row.addSpacing(20)
        danger_btn_row.addWidget(self.delete_output_button)
        danger_btn_row.addWidget(delete_desc)
        danger_btn_row.addStretch(1)

        danger_layout.addWidget(danger_title)
        danger_layout.addWidget(danger_hint)
        danger_layout.addLayout(danger_btn_row)

        layout.addWidget(config_panel)
        layout.addWidget(tips_panel)
        layout.addWidget(danger_panel)
        layout.addStretch(1)
        return page

    # ── Table Config ──────────────────────────────────────────────────

    def _configure_table(self, table: QTableWidget) -> None:
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        table.horizontalHeader().setHighlightSections(False)

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
            QMessageBox.warning(self, "缺少字幕源", "请至少选择一个字幕源。")
            return
        try:
            data_dir = self._ensure_storage_for_current_data_dir()
        except ValueError as exc:
            QMessageBox.warning(self, "数据目录无效", str(exc))
            return

        env_settings = AppSettings.from_env(self.env_bootstrap.env_path)
        config = TaskConfig(
            year=self.year_spin.value(),
            limit=self.limit_spin.value(),
            subtitle_providers=providers,
            fallback_enabled=self.fallback_check.isChecked(),
            download_enabled=self.download_check.isChecked(),
            request_interval_ms=env_settings.request_interval_ms,
            output_root=data_dir / "output",
            tmdb_token=env_settings.tmdb_token,
            assrt_token=env_settings.assrt_token,
            assrt_api_base_url=env_settings.assrt_api_base_url,
            opensubtitles_api_key=env_settings.opensubtitles_api_key,
            opensubtitles_username=env_settings.opensubtitles_username,
            opensubtitles_password=env_settings.opensubtitles_password,
            opensubtitles_base_url=env_settings.opensubtitles_base_url,
            opensubtitles_user_agent=env_settings.opensubtitles_user_agent,
            provider_priority=env_settings.provider_priority,
            provider_disabled=env_settings.provider_disabled,
            proxies=env_settings.proxies(),
        )
        self.collect_log.clear()
        self.collect_progress.setValue(0)
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
            QMessageBox.information(self, "暂无日志", "当前没有可复制的采集日志。")
            return
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "已复制", "采集日志已复制到剪贴板。")

    def update_collect_progress(self, current: int, total: int, movie: str) -> None:
        percent = int(current / total * 100) if total else 0
        self.collect_progress.setValue(percent)
        self.collect_status.setText(f"{current}/{total} {movie}")

    def handle_verification_request(self, payload: dict) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("SubHD 验证码")
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(payload.get("subtitleTitle") or payload.get("detailUrl") or "需要验证码"))
        browser = QTextBrowser()
        browser.setHtml(payload.get("verificationHtml") or "请打开详情页查看验证码。")
        browser.setMinimumHeight(180)
        code_input = QLineEdit()
        code_input.setPlaceholderText("输入验证码")
        buttons = QHBoxLayout()
        submit = QPushButton("提交")
        cancel = QPushButton("跳过")
        cancel.setObjectName("secondaryButton")
        buttons.addWidget(submit)
        buttons.addWidget(cancel)
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
        self.collect_progress.setValue(100)
        self.collect_status.setText("任务完成")
        self.show_result_summary(result)
        self.refresh_history()
        self.refresh_task_center()
        QMessageBox.information(self, "采集完成", f"输出目录：{result.get('downloadDir', '')}")

    def collection_failed(self, message: str) -> None:
        self.start_button.setEnabled(True)
        self._set_maintenance_enabled(True)
        self.collect_status.setText("任务失败")
        self.collect_log.append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
        self.refresh_history()
        self.refresh_task_center()
        QMessageBox.critical(self, "采集失败", message)

    def show_result_summary(self, result: dict) -> None:
        rows = [
            ("电影数量", result.get("movieCount", 0)),
            ("候选字幕", result.get("subtitleCount", 0)),
            ("最佳候选", result.get("bestCount", 0)),
            ("失败记录", result.get("failedCount", 0)),
            ("下载成功", result.get("downloadCount", 0)),
            ("输出目录", result.get("downloadDir", "")),
        ]
        self.collect_result_table.setRowCount(len(rows))
        for row, (name, value) in enumerate(rows):
            name_item = QTableWidgetItem(str(name))
            value_item = QTableWidgetItem(str(value))
            value_item.setToolTip(str(value))
            self.collect_result_table.setItem(row, 0, name_item)
            self.collect_result_table.setItem(row, 1, value_item)

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
        try:
            data_dir = self._ensure_storage_for_current_data_dir()
        except ValueError as exc:
            QMessageBox.warning(self, "数据目录无效", str(exc))
            return
        self.parse_table.setRowCount(0)
        self.parse_log.clear()
        self.parse_status.setText("解析中")
        self.parse_button.setEnabled(False)
        output_dir = data_dir / "parsed"
        env_settings = AppSettings.from_env(self.env_bootstrap.env_path)
        self.parser_worker = ParserWorker(
            [Path(file) for file in files],
            output_dir,
            env_settings.tmdb_token,
        )
        self.parser_worker.log_message.connect(self.parse_log.append)
        self.parser_worker.file_parsed.connect(self.add_parse_row)
        self.parser_worker.finished_success.connect(self.parse_finished)
        self.parser_worker.finished_error.connect(self.parse_failed)
        self.parser_worker.start()

    def add_parse_row(self, row: dict) -> None:
        index = self.parse_table.rowCount()
        self.parse_table.insertRow(index)
        if "error" in row:
            values = [row.get("file", ""), "-", "-", "-", "-", row["error"]]
        else:
            values = [
                row.get("file", ""),
                row.get("title", ""),
                row.get("movieId", ""),
                row.get("originalCount", 0),
                row.get("exportCount", 0),
                row.get("matchedKeyword", ""),
            ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            if column in {2, 3, 4}:
                item.setTextAlignment(Qt.AlignCenter)
            self.parse_table.setItem(index, column, item)

    def parse_finished(self, result: dict) -> None:
        self.parse_button.setEnabled(True)
        self.parse_status.setText(
            f"完成：成功 {len(result.get('successes', []))}，失败 {len(result.get('failures', []))}"
        )
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.parse_log.append(f"[{stamp}] 电影 JSON：{result.get('moviesPath')}")
        self.parse_log.append(f"[{stamp}] 字幕 JSON：{result.get('subtitlesPath')}")
        self.refresh_task_center()

    def parse_failed(self, message: str) -> None:
        self.parse_button.setEnabled(True)
        self.parse_status.setText("解析失败")
        self.parse_log.append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
        QMessageBox.critical(self, "解析失败", message)

    # ── History ───────────────────────────────────────────────────────

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
                item.get("id", ""),
                item.get("status", ""),
                item.get("year", ""),
                item.get("limit", ""),
                item.get("started_at", ""),
                item.get("finished_at", ""),
                str(output_dir) if str(output_dir) != "." else "",
            ]
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                table_item.setToolTip(str(value))
                if column in {0, 1, 2, 3}:
                    table_item.setTextAlignment(Qt.AlignCenter)
                self.history_table.setItem(row_index, column, table_item)

    # ── Settings Actions ──────────────────────────────────────────────

    def browse_data_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择数据目录", self.data_dir_input.text())
        if directory:
            self.data_dir_input.setText(directory)

    def save_data_dir_to_env(self) -> None:
        try:
            data_dir = self._current_data_dir()
        except ValueError as exc:
            QMessageBox.warning(self, "数据目录无效", str(exc))
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
        QMessageBox.information(self, "已保存", f"数据目录已保存到 {env_path}")

    def reset_history(self) -> None:
        if self.collector_worker and self.collector_worker.isRunning():
            QMessageBox.warning(self, "任务运行中", "采集任务运行中，暂时不能重置历史。")
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
            QMessageBox.warning(self, "数据目录无效", str(exc))
            return
        self.storage.clear_task_runs()
        self.refresh_history()
        self.refresh_task_center()
        self.collect_status.setText("历史记录已清空")
        QMessageBox.information(self, "已重置", "采集历史记录已清空。")

    def delete_output_files(self) -> None:
        if self.collector_worker and self.collector_worker.isRunning():
            QMessageBox.warning(self, "任务运行中", "采集任务运行中，暂时不能删除输出文件。")
            return
        try:
            data_dir = self._ensure_storage_for_current_data_dir()
        except ValueError as exc:
            QMessageBox.warning(self, "数据目录无效", str(exc))
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
        self.collect_result_table.setRowCount(0)
        self.refresh_history()
        self.refresh_task_center()
        self.collect_status.setText("输出文件已删除，历史记录已清空")
        QMessageBox.information(self, "已删除", "采集输出文件和历史记录已清理完成。")


def run_app(argv: list[str]) -> int:
    app = QApplication(argv)
    window = MainWindow()
    window.show()
    return app.exec()
