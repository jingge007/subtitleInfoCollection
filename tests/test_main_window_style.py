import re
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QTableWidget, QTextEdit
from qfluentwidgets import FluentWindow, SwitchButton

from subtitle_info_collection.gui.main_window import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MainWindow,
)


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
    assert window.stackedWidget.count() == 7
    assert "QFrame#heroPanel" not in window.styleSheet()
    assert "QLabel#posterBlock" not in window.styleSheet()

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
        "automationPage",
        "configPage",
        "historyPage",
        "settingsPage",
    }

    assert len(window.findChildren(QTableWidget, "dataTable")) >= 2
    assert len(window.findChildren(QTextEdit, "logArea")) >= 2
    assert hasattr(window, "copy_automation_log_button")
    unicloud_switch = window.findChild(SwitchButton, "unicloudImportFormatSwitch")
    assert unicloud_switch is not None
    assert unicloud_switch.isChecked()
    button_texts = {button.text() for button in window.findChildren(QPushButton)}
    assert "自动化脚本" in button_texts or "执行" in button_texts
    assert "自动上传经典台词" not in button_texts
    assert "上传到经典台词" not in button_texts

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
    assert "推荐填写最终目录" in env_example
    assert "SUBTITLE_COLLECTION_PACKAGE_DIST_DIR" in build_script
    assert "--distpath" in build_script
    assert "--specpath" in build_script
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
