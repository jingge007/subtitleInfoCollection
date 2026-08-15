import base64
import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTextBrowser,
    QTextEdit,
    QWidget,
)
from qfluentwidgets import CaptionLabel, FluentWindow, HeaderCardWidget, NavigationWidget, SwitchButton

from subtitle_info_collection.gui.config_editor import FullWidthIndicatorSegmentedWidget
from subtitle_info_collection.gui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MainWindow,
)


def _header_index(window: MainWindow, title: str, widget) -> int:
    for card in window.findChildren(HeaderCardWidget):
        if card.title == title:
            return card.headerLayout.indexOf(widget)
    return -1


def _app() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


def test_main_window_uses_fluent_navigation_chrome(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()

    assert window.windowTitle() == "字幕采集工具"
    assert window.width() == DEFAULT_WINDOW_WIDTH
    assert window.height() == DEFAULT_WINDOW_HEIGHT
    assert isinstance(window, FluentWindow)
    assert window.navigationInterface is not None
    assert window.stackedWidget.count() == 9
    assert "QFrame#heroPanel" not in window.styleSheet()
    assert "QLabel#posterBlock" not in window.styleSheet()
    nav_items = window.navigationInterface.findChildren(NavigationWidget)
    assert nav_items
    assert all(item.cursor().shape() == Qt.PointingHandCursor for item in nav_items)

    window.close()
    app.quit()


def test_main_window_exposes_professional_ops_layout_objects(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()

    style = window.styleSheet()
    assert "QFrame#dangerZone" in style
    assert "QTableWidget#dataTable" in style
    assert "QTextEdit#logArea" in style
    assert "NavigationInterface" in style

    page_names = {
        window.stackedWidget.widget(index).objectName()
        for index in range(window.stackedWidget.count())
    }
    assert page_names == {
        "dashboardPage",
        "collectorPage",
        "parserPage",
        "scriptCenterPage",
        "classicLinesPage",
        "automationPage",
        "configPage",
        "historyPage",
        "settingsPage",
    }

    assert len(window.findChildren(QTableWidget, "dataTable")) >= 1
    assert window._parser_page.findChildren(QTableWidget, "dataTable") == []
    assert len(window.findChildren(QTextEdit, "logArea")) >= 2
    assert hasattr(window, "copy_automation_log_button")
    unicloud_switch = window.findChild(SwitchButton, "unicloudImportFormatSwitch")
    assert unicloud_switch is not None
    assert unicloud_switch.isChecked()
    automation_unicloud_switch = window.findChild(
        SwitchButton,
        "automationUnicloudImportFormatSwitch",
    )
    assert automation_unicloud_switch is not None
    assert automation_unicloud_switch.isChecked()
    assert not hasattr(window, "parse_table")
    assert hasattr(window, "parse_progress_ring")
    assert hasattr(window, "parse_progress_label")
    assert set(window.parse_stat_labels) == {
        "total",
        "success",
        "failed",
        "exported",
        "accuracy",
    }
    assert window.parse_stat_labels["accuracy"].text() == "0%"
    assert window._parse_success_stat_card is not None
    assert window._parse_success_stat_card.cursor().shape() == Qt.PointingHandCursor
    assert window._parse_success_stat_card.toolTip() == "点击打开解析输出目录"
    assert set(window.collect_stat_labels) == {
        "movies",
        "remaining",
        "failed",
        "downloaded",
        "accuracy",
    }
    assert window.collect_stat_labels["accuracy"].text() == "0%"
    assert window.collect_stat_labels["remaining"].text() == "0"
    assert bool(
        window.collect_provider_hit_labels["subhd"].textInteractionFlags()
        & Qt.TextSelectableByMouse
    )
    assert bool(window.collect_status.textInteractionFlags() & Qt.TextSelectableByMouse)
    assert bool(
        window.collect_elapsed_label.textInteractionFlags() & Qt.TextSelectableByMouse
    )
    assert window.collect_elapsed_label.text() == "耗时 00:00:00"
    assert set(window.collect_provider_hit_labels) == {
        "subhd",
        "subdl",
        "assrt",
        "opensubtitles",
    }
    assert window.collect_provider_hit_labels["subhd"].text() == "SubHD 成功采集0条"
    for label in window.collect_provider_hit_labels.values():
        parent = label.parentWidget()
        assert isinstance(parent, QFrame)
        assert parent.objectName() == "providerHitCard"
        assert "background:" in parent.styleSheet()
    assert set(window.collect_provider_hit_cards) == set(window.collect_provider_hit_labels)
    # 取消勾选后对应色块隐藏，勾选后重新显示
    window.subhd_check.setChecked(False)
    assert window.collect_provider_hit_cards["subhd"].isHidden()
    assert not window.collect_provider_hit_cards["subdl"].isHidden()
    window.subhd_check.setChecked(True)
    assert not window.collect_provider_hit_cards["subhd"].isHidden()
    hits_panel = window.findChild(QWidget, "collectProviderHitsPanel")
    assert hits_panel is not None
    assert isinstance(hits_panel.layout(), QHBoxLayout)
    # 命中色块在「任务状态」标题行右侧
    collector_status = next(
        (
            card
            for card in window.findChildren(HeaderCardWidget)
            if card.title == "任务状态" and hits_panel.parentWidget() is card.headerView
        ),
        None,
    )
    assert collector_status is not None
    assert hits_panel.parentWidget() is collector_status.headerView
    assert hasattr(window, "config_precheck_layout")
    assert window.config_precheck_layout.count() >= 8
    tip = window.findChild(CaptionLabel, "configPrecheckTip")
    assert tip is not None
    assert "以下状态来自当前 .env" in tip.text()
    # 说明在配置预检卡片标题行，而非内容区首项
    precheck_headers = [
        card
        for card in window.findChildren(HeaderCardWidget)
        if card.title == "配置预检"
    ]
    assert precheck_headers
    assert tip.parentWidget() is precheck_headers[0].headerView
    assert isinstance(window.config_editor.segment, FullWidthIndicatorSegmentedWidget)
    assert not hasattr(window, "source_status_layout")
    assert window._collect_success_stat_card is not None
    assert window._collect_success_stat_card.cursor().shape() == Qt.PointingHandCursor
    assert window._collect_success_stat_card.toolTip() == "点击打开采集输出目录"
    assert set(window.automation_stat_labels) == {"total", "pages"}
    assert set(window.classic_stat_labels) == {"movies", "lines", "pages"}
    assert window.copy_collect_log_button.toolTip() == "复制日志"
    assert window.download_collect_log_button.toolTip() == "下载日志"
    copy_index = _header_index(window, "采集日志", window.copy_collect_log_button)
    download_index = _header_index(window, "采集日志", window.download_collect_log_button)
    assert 0 <= copy_index < download_index
    assert window.pin_button.toolTip() == "窗口置顶"
    assert window.pin_button.cursor().shape() == Qt.PointingHandCursor
    pin_index = window.titleBar.buttonLayout.indexOf(window.pin_button)
    min_index = window.titleBar.buttonLayout.indexOf(window.titleBar.minBtn)
    assert 0 <= pin_index < min_index
    assert window._window_pinned is False

    window.pin_button.setChecked(True)
    window._toggle_always_on_top()
    assert window.pin_button.toolTip() == "取消置顶"
    assert window._window_pinned is True
    handle = window.windowHandle()
    if handle is not None:
        assert bool(handle.flags() & Qt.WindowStaysOnTopHint)

    window.pin_button.setChecked(False)
    window._toggle_always_on_top()
    assert window.pin_button.toolTip() == "窗口置顶"
    assert window._window_pinned is False
    handle = window.windowHandle()
    if handle is not None:
        assert not bool(handle.flags() & Qt.WindowStaysOnTopHint)

    assert window.start_button.cursor().shape() == Qt.PointingHandCursor
    assert window.history_table.columnCount() == 5
    assert not hasattr(window, "latest_records_layout")
    assert all(
        log.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOn
        for log in [window.collect_log, window.parse_log, window.automation_log]
    )
    button_texts = {button.text() for button in window.findChildren(QPushButton)}
    assert "删除选中" not in button_texts
    assert "自动化脚本" in button_texts or "执行" in button_texts
    assert "自动上传经典台词" not in button_texts
    assert "上传到经典台词" not in button_texts

    window.close()
    app.quit()


def test_automation_clickable_stats_open_without_output_panel(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()

    first = tmp_path / "automation" / "todays-lines-1.json"
    second = tmp_path / "automation" / "todays-lines-2.json"
    first.parent.mkdir()
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")

    window.automation_finished(
        {
            "outputPath": str(first),
            "outputPaths": [str(first), str(second)],
            "totalCount": 2,
            "pageCount": 1,
        }
    )

    assert window.automation_stat_labels["total"].text() == "2"
    assert window.automation_stat_labels["pages"].text() == "1"
    assert "output" not in window.automation_stat_labels
    assert window.latest_automation_output_paths == [first, second]

    window.close()
    app.quit()


def test_parse_stats_accuracy_and_success_card(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()

    parse_dir = tmp_path / "parsed"
    parse_dir.mkdir()
    window._parse_output_dir = parse_dir
    window.update_parse_stats(
        {
            "totalCount": 10,
            "successCount": 8,
            "failureCount": 2,
        }
    )
    assert window.parse_stat_labels["total"].text() == "10"
    assert window.parse_stat_labels["success"].text() == "8"
    assert window.parse_stat_labels["failed"].text() == "2"
    assert window.parse_stat_labels["accuracy"].text() == "80%"

    window.parse_finished(
        {
            "totalCount": 10,
            "successCount": 9,
            "failureCount": 1,
            "exportCount": 100,
            "moviesPaths": [str(parse_dir / "movies.json")],
            "subtitlesPaths": [str(parse_dir / "subtitles.json")],
        }
    )
    assert window.parse_stat_labels["accuracy"].text() == "90%"
    assert window.parse_stat_labels["exported"].text() == "100"

    window.close()
    app.quit()


def test_automation_log_copy_uses_timestamped_content(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()

    window.append_automation_log("启动测试")
    text = window.automation_log.toPlainText()
    assert re.fullmatch(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] 启动测试", text)

    window.copy_automation_log()
    assert QApplication.clipboard().text() == text

    window.close()
    app.quit()


def test_captcha_dialog_uses_single_borderless_display_and_visible_input(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()
    captured: dict[str, QDialog] = {}

    svg = '<svg width="120" height="48"><text x="10" y="36">y0Qg</text></svg>'
    data_uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode("ascii")

    class Worker:
        def submit_verification(self, code: str) -> None:
            self.code = code

        def request_captcha_refresh(self) -> None:
            self.refreshed = True

    def fake_exec(self):
        captured["dialog"] = self
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    window.collector_worker = Worker()

    window.handle_verification_request(
        {
            "providerSubtitleId": "LK4IUp",
            "subtitleTitle": "布朗克斯的故事 ZiMuZu字幕组 A.Bronx.Tale.1993.1080p.BluRay.X264-AMIABLE",
            "detailUrl": "https://subhd.tv/a/LK4IUp",
            "verificationHtml": svg,
            "verificationImageDataUri": data_uri,
            "suggestedCode": "",
            "ocrMessage": "OCR returned no captcha text",
        }
    )

    dialog = captured["dialog"]
    assert dialog.findChildren(QTextBrowser) == []
    assert window._verification_image_label is None
    style = dialog.styleSheet() + "".join(child.styleSheet() for child in dialog.findChildren(QLineEdit))
    assert "border: 1px solid" in style
    assert "QTextBrowser" not in style

    window.close()
    app.quit()


def test_professional_pages_fit_existing_desktop_window(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()
    window.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    window.show()
    app.processEvents()

    for index in range(window.stackedWidget.count()):
        window.stackedWidget.setCurrentIndex(index)
        app.processEvents()
        current = window.stackedWidget.currentWidget()
        if isinstance(current, QScrollArea):
            assert current.widget().width() <= current.viewport().width()
        else:
            assert current.minimumSizeHint().width() <= current.width()

    window.close()
    app.quit()


def test_package_dist_dir_env_setting_is_documented_and_used():
    root = Path(__file__).resolve().parents[1]
    env_example = (root / ".env.example").read_text(encoding="utf-8")
    build_script = (root / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    browser_copy_script = (root / "scripts" / "copy_playwright_browsers.ps1").read_text(
        encoding="utf-8"
    )
    spec_files = {
        path.name: path.read_text(encoding="utf-8")
        for path in root.glob("*.spec")
    }
    package_spec = spec_files["字幕采集工具.spec"]

    assert "SUBTITLE_COLLECTION_PACKAGE_DIST_DIR=" in env_example
    assert "TODAYS_LINES_USERNAME=" in env_example
    assert "TODAYS_LINES_PASSWORD=" in env_example
    assert "TODAYS_LINES_TOKEN=" in env_example
    assert "BAIDU_TRANSLATE_APP_ID=" in env_example
    assert "BAIDU_TRANSLATE_SECRET=" in env_example
    assert "推荐填写最终目录" in env_example
    assert "SUBTITLE_COLLECTION_PACKAGE_DIST_DIR" in build_script
    assert "--distpath" in build_script
    assert "字幕采集工具.spec" in build_script
    assert "PLAYWRIGHT_BROWSERS_PATH" in build_script
    assert "ms-playwright" in build_script
    assert "playwrightBrowserSourcePath" in build_script
    assert ".local-browsers" in build_script
    assert "chrome-headless-shell.exe" in build_script
    assert "playwright\\driver\\package\\.local-browsers" in build_script
    assert "--clean" in build_script
    assert "copy_playwright_browsers.ps1" in build_script
    assert "Copy-PlaywrightBrowserCache" in build_script
    assert "Copy-ItemWithRetry" in browser_copy_script
    assert "Get-ChildItem -LiteralPath $SourcePath -Recurse -File" in browser_copy_script
    assert "Start-Sleep -Seconds 2" in browser_copy_script
    assert "Start-Sleep -Seconds 5" in browser_copy_script
    assert "chrome_elf.dll" in browser_copy_script
    assert "D3DCompiler_47.dll" in browser_copy_script
    assert "cmd /d /c" in browser_copy_script
    assert "copy /Y" in browser_copy_script
    assert ".copytmp" in browser_copy_script
    assert "复制 Playwright 浏览器失败" in build_script
    assert "Get-CimInstance Win32_Process" in build_script
    assert "CommandLine" in build_script
    assert "$LASTEXITCODE" in build_script
    assert "命令执行失败" in build_script
    assert "占用打包目录" in build_script
    assert "请先关闭正在运行的旧版程序" in build_script
    assert "SUBTITLE_COLLECTION_PACKAGE_DIST_DIR" in package_spec
    assert "CONF['distpath']" in package_spec
    assert all("ms-playwright" in content for content in spec_files.values())
    assert all(".local-browsers" in content for content in spec_files.values())


def test_collect_stats_accuracy_and_download_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()

    download_dir = tmp_path / "output" / "run-1"
    download_dir.mkdir(parents=True)

    window.update_collect_stats(
        {
            "movieCount": 30,
            "failedCount": 3,
            "downloadCount": 16,
            "downloadDir": str(download_dir),
        }
    )

    assert window.collect_stat_labels["movies"].text() == "30"
    assert window.collect_stat_labels["remaining"].text() == "11"
    assert window.collect_stat_labels["failed"].text() == "3"
    assert window.collect_stat_labels["downloaded"].text() == "16"
    assert window.collect_stat_labels["accuracy"].text() == "53%"
    assert window._collect_download_dir == download_dir

    window.show_result_summary(
        {
            "movieCount": 30,
            "failedCount": 4,
            "downloadCount": 26,
            "downloadDir": str(download_dir),
        }
    )
    assert window.collect_stat_labels["remaining"].text() == "0"
    assert window.collect_stat_labels["accuracy"].text() == "86%"

    window.close()
    app.quit()


def test_download_collect_log_writes_utf8_txt(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()
    window.collect_log.setPlainText("第一行\nASSRT 搜索成功")
    target = tmp_path / "采集日志.txt"

    monkeypatch.setattr(
        "subtitle_info_collection.gui.main_window.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(target), "文本文件 (*.txt)"),
    )
    window.download_collect_log()
    assert target.read_text(encoding="utf-8") == "第一行\nASSRT 搜索成功"

    window.close()
    app.quit()


def _layout_widgets(layout: QHBoxLayout) -> list[QWidget]:
    widgets: list[QWidget] = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget() if item is not None else None
        if widget is not None:
            widgets.append(widget)
    return widgets


def test_provider_ui_order_follows_priority(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()

    for checkbox in window.provider_checks.values():
        checkbox.setChecked(True)

    ordered = window._ordered_provider_ids()
    assert ordered == [
        pid for pid in window.settings.provider_priority if pid in window.provider_checks
    ]
    assert window.selected_providers() == ordered

    check_widgets = [
        widget
        for widget in _layout_widgets(window._provider_checks_layout)
        if widget in window.provider_checks.values()
    ]
    assert check_widgets == [window.provider_checks[pid] for pid in ordered]

    hit_widgets = _layout_widgets(window._provider_hits_layout)
    assert hit_widgets == [window.collect_provider_hit_cards[pid] for pid in ordered]

    custom = ["subdl", "assrt", "subhd", "opensubtitles"]
    window.settings.provider_priority = list(custom)
    window._sync_provider_ui_order()
    assert window._ordered_provider_ids() == custom
    assert window.selected_providers() == custom
    assert [
        widget
        for widget in _layout_widgets(window._provider_checks_layout)
        if widget in window.provider_checks.values()
    ] == [window.provider_checks[pid] for pid in custom]
    assert _layout_widgets(window._provider_hits_layout) == [
        window.collect_provider_hit_cards[pid] for pid in custom
    ]

    # 未列入 PRIORITY 的源应隐藏且不参与 selected_providers
    partial = ["subhd", "opensubtitles", "subdl"]
    window.settings.provider_priority = list(partial)
    for checkbox in window.provider_checks.values():
        checkbox.setChecked(False)
    window._sync_provider_ui_order()
    assert window._ordered_provider_ids() == partial
    assert window.assrt_check.isHidden()
    assert not window.assrt_check.isChecked()
    assert window.collect_provider_hit_cards["assrt"].isHidden()
    # 保存/同步后 PRIORITY 内的源默认勾选
    assert all(window.provider_checks[pid].isChecked() for pid in partial)
    assert window.selected_providers() == partial
    assert [
        widget
        for widget in _layout_widgets(window._provider_checks_layout)
        if widget in window.provider_checks.values()
    ] == [window.provider_checks[pid] for pid in partial]

    # DISABLED 中的源保持不勾选
    window.settings.provider_disabled = ["subdl"]
    window._sync_provider_ui_order()
    assert window.selected_providers() == ["subhd", "opensubtitles"]
    assert not window.subdl_check.isChecked()

    window.close()
    app.quit()
