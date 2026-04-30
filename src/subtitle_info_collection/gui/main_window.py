from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
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
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import AppSettings
from ..models import TaskConfig
from ..storage import AppStorage
from .worker import CollectorWorker, ParserWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings.from_env()
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage = AppStorage(self.settings.database_path)
        self.collector_worker: CollectorWorker | None = None
        self.parser_worker: ParserWorker | None = None

        self.setWindowTitle("字幕信息自动采集工具")
        self.resize(1220, 780)
        self._apply_style()

        tabs = QTabWidget()
        tabs.addTab(self._build_collector_tab(), "采集任务")
        tabs.addTab(self._build_parser_tab(), "字幕解析")
        tabs.addTab(self._build_history_tab(), "历史记录")
        tabs.addTab(self._build_settings_tab(), "设置")
        self.setCentralWidget(tabs)
        self.refresh_history()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                font-size: 14px;
                color: #1f2937;
            }
            QMainWindow, QWidget {
                background: #f6f7fb;
            }
            QTabWidget::pane {
                border: 1px solid #d7dce5;
                border-radius: 8px;
                background: #ffffff;
            }
            QTabBar::tab {
                background: #e8ecf3;
                border: 1px solid #d7dce5;
                border-bottom: none;
                padding: 9px 18px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #0f172a;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #d7dce5;
                border-radius: 8px;
                margin-top: 14px;
                padding: 16px 12px 12px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLineEdit, QSpinBox, QTextEdit, QTextBrowser, QTableWidget {
                background: #ffffff;
                border: 1px solid #d7dce5;
                border-radius: 6px;
            }
            QLineEdit, QSpinBox {
                min-height: 30px;
                padding: 2px 8px;
            }
            QPushButton {
                background: #2563eb;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #1d4ed8;
            }
            QPushButton:disabled {
                background: #aeb8c8;
            }
            QPushButton#secondaryButton {
                background: #eef2f7;
                color: #1f2937;
                border: 1px solid #d7dce5;
            }
            QPushButton#secondaryButton:hover {
                background: #e2e8f0;
            }
            QPushButton#dangerButton {
                background: #dc2626;
            }
            QPushButton#dangerButton:hover {
                background: #b91c1c;
            }
            QProgressBar {
                border: 1px solid #d7dce5;
                border-radius: 6px;
                background: #eef2f7;
                text-align: center;
                height: 18px;
            }
            QProgressBar::chunk {
                border-radius: 6px;
                background: #2563eb;
            }
            QHeaderView::section {
                background: #f1f5f9;
                border: none;
                border-bottom: 1px solid #d7dce5;
                padding: 8px;
                font-weight: 600;
            }
            QTableWidget {
                gridline-color: #e2e8f0;
                alternate-background-color: #f8fafc;
            }
            """
        )

    def _build_collector_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form_group = QGroupBox("采集参数")
        form = QGridLayout(form_group)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)

        self.year_spin = QSpinBox()
        self.year_spin.setRange(1900, datetime.now().year + 1)
        self.year_spin.setValue(2026)

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

        status_group = QGroupBox("任务状态")
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(10)
        self.collect_status = QLabel("等待开始")
        self.collect_progress = QProgressBar()
        self.collect_result_table = QTableWidget(0, 2)
        self.collect_result_table.setHorizontalHeaderLabels(["指标", "值"])
        self._configure_table(self.collect_result_table)
        self.collect_result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.collect_result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        status_layout.addWidget(self.collect_status)
        status_layout.addWidget(self.collect_progress)
        status_layout.addWidget(self.collect_result_table)

        log_header = QHBoxLayout()
        log_title = QLabel("采集日志")
        self.copy_collect_log_button = QPushButton("复制日志")
        self.copy_collect_log_button.setObjectName("secondaryButton")
        self.copy_collect_log_button.clicked.connect(self.copy_collect_log)
        log_header.addWidget(log_title)
        log_header.addStretch(1)
        log_header.addWidget(self.copy_collect_log_button)

        self.collect_log = QTextEdit()
        self.collect_log.setReadOnly(True)

        layout.addWidget(form_group)
        layout.addWidget(status_group, 2)
        layout.addLayout(log_header)
        layout.addWidget(self.collect_log, 3)
        return page

    def _build_parser_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        actions = QHBoxLayout()
        self.parse_button = QPushButton("选择 SRT/ASS 文件")
        self.parse_button.clicked.connect(self.select_parse_files)
        self.parse_status = QLabel("等待文件")
        actions.addWidget(self.parse_button)
        actions.addWidget(self.parse_status, 1)

        self.parse_table = QTableWidget(0, 6)
        self.parse_table.setHorizontalHeaderLabels(
            ["文件路径", "电影", "电影 ID", "原始字幕", "导出字幕", "状态/关键词"]
        )
        self._configure_table(self.parse_table)
        self.parse_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 6):
            self.parse_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)

        self.parse_log = QTextEdit()
        self.parse_log.setReadOnly(True)

        layout.addLayout(actions)
        layout.addWidget(self.parse_table, 3)
        layout.addWidget(QLabel("解析日志"))
        layout.addWidget(self.parse_log, 2)
        return page

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        actions = QHBoxLayout()
        refresh_button = QPushButton("刷新历史")
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self.refresh_history)
        actions.addWidget(refresh_button)
        actions.addStretch(1)

        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(
            ["ID", "状态", "年份", "Top", "开始时间", "结束时间", "输出目录"]
        )
        self._configure_table(self.history_table)
        for column in range(0, 6):
            self.history_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)

        layout.addLayout(actions)
        layout.addWidget(self.history_table)
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form_group = QGroupBox("本机配置")
        form = QFormLayout(form_group)
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)
        self.data_dir_input = QLineEdit(str(self.settings.data_dir))
        form.addRow("数据目录", self.data_dir_input)

        config_buttons = QHBoxLayout()
        browse_button = QPushButton("选择数据目录")
        browse_button.setObjectName("secondaryButton")
        browse_button.clicked.connect(self.browse_data_dir)
        save_button = QPushButton("保存数据目录")
        save_button.clicked.connect(self.save_data_dir_to_env)
        config_buttons.addWidget(browse_button)
        config_buttons.addWidget(save_button)
        config_buttons.addStretch(1)

        maintenance_group = QGroupBox("数据维护")
        maintenance_buttons = QHBoxLayout(maintenance_group)
        self.reset_history_button = QPushButton("重置历史")
        self.reset_history_button.setObjectName("secondaryButton")
        self.reset_history_button.clicked.connect(self.reset_history)
        self.delete_output_button = QPushButton("删除输出文件")
        self.delete_output_button.setObjectName("dangerButton")
        self.delete_output_button.clicked.connect(self.delete_output_files)
        maintenance_buttons.addWidget(self.reset_history_button)
        maintenance_buttons.addWidget(self.delete_output_button)
        maintenance_buttons.addStretch(1)

        layout.addWidget(form_group)
        layout.addLayout(config_buttons)
        layout.addWidget(maintenance_group)
        layout.addStretch(1)
        return page

    def _configure_table(self, table: QTableWidget) -> None:
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        table.horizontalHeader().setHighlightSections(False)

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

    def selected_providers(self) -> list[str]:
        providers = []
        if self.subhd_check.isChecked():
            providers.append("subhd")
        if self.assrt_check.isChecked():
            providers.append("assrt")
        if self.opensubtitles_check.isChecked():
            providers.append("opensubtitles")
        return providers

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

        env_settings = AppSettings.from_env()
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
        QMessageBox.information(self, "采集完成", f"输出目录：{Path(result.get('bestPath', '')).parent}")

    def collection_failed(self, message: str) -> None:
        self.start_button.setEnabled(True)
        self._set_maintenance_enabled(True)
        self.collect_status.setText("任务失败")
        self.collect_log.append(message)
        self.refresh_history()
        QMessageBox.critical(self, "采集失败", message)

    def show_result_summary(self, result: dict) -> None:
        rows = [
            ("电影数量", result.get("movieCount", 0)),
            ("候选字幕", result.get("subtitleCount", 0)),
            ("最佳候选", result.get("bestCount", 0)),
            ("失败记录", result.get("failedCount", 0)),
            ("下载成功", result.get("downloadCount", 0)),
            ("电影 JSON", result.get("moviesPath", "")),
            ("全部候选 JSON", result.get("allPath", "")),
            ("最佳候选 JSON", result.get("bestPath", "")),
            ("失败记录 JSON", result.get("failedPath", "")),
            ("字幕压缩包", result.get("subtitlePackagePath", "")),
        ]
        self.collect_result_table.setRowCount(len(rows))
        for row, (name, value) in enumerate(rows):
            name_item = QTableWidgetItem(str(name))
            value_item = QTableWidgetItem(str(value))
            value_item.setToolTip(str(value))
            self.collect_result_table.setItem(row, 0, name_item)
            self.collect_result_table.setItem(row, 1, value_item)

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
        env_settings = AppSettings.from_env()
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
        self.parse_log.append(f"电影 JSON：{result.get('moviesPath')}")
        self.parse_log.append(f"字幕 JSON：{result.get('subtitlesPath')}")

    def parse_failed(self, message: str) -> None:
        self.parse_button.setEnabled(True)
        self.parse_status.setText("解析失败")
        QMessageBox.critical(self, "解析失败", message)

    def refresh_history(self) -> None:
        try:
            self._ensure_storage_for_current_data_dir()
        except ValueError:
            return
        rows = self.storage.list_task_runs()
        self.history_table.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            output_dir = Path(item.get("result", {}).get("bestPath", "")).parent
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
        env_path = Path.cwd() / ".env"
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
        self.settings = AppSettings.from_env()
        self.storage = AppStorage(data_dir / "subtitle_info_collection.sqlite3")
        self.refresh_history()
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
        self.collect_status.setText("输出文件已删除，历史记录已清空")
        QMessageBox.information(self, "已删除", "采集输出文件和历史记录已清理完成。")


def run_app(argv: list[str]) -> int:
    app = QApplication(argv)
    window = MainWindow()
    window.show()
    return app.exec()
