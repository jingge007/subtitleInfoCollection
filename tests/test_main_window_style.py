import sys

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QScrollArea, QTableWidget, QTextEdit

from subtitle_info_collection.gui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


def test_main_window_uses_professional_tool_chrome(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()

    assert window.windowTitle() == "字幕采集工具"
    assert window.nav_buttons[0].text() == "工作台"
    assert "QFrame#heroPanel" not in window.styleSheet()
    assert "QLabel#posterBlock" not in window.styleSheet()
    assert "任务工作台" in window.dashboard_title.text()

    window.close()
    app.quit()


def test_main_window_exposes_professional_ops_layout_objects(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()

    style = window.styleSheet()
    assert "QFrame#dangerZone" in style
    assert "QTableWidget#dataTable" in style
    assert "QTextEdit#logPanel" in style
    assert "QPushButton#navButton" in style

    page_titles = sorted(
        label.text()
        for label in window.findChildren(QLabel, "pageTitle")
    )
    expected = sorted(["任务工作台", "采集任务", "字幕解析", "历史记录", "设置与维护"])
    assert page_titles == expected

    assert window.findChild(QFrame, "sidebar") is not None
    assert window.findChild(QFrame, "dangerZone") is not None
    assert len(window.findChildren(QTableWidget, "dataTable")) >= 3
    assert len(window.findChildren(QTextEdit, "logPanel")) >= 2

    window.close()
    app.quit()


def test_professional_pages_fit_existing_desktop_window(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()
    window.resize(1320, 840)
    window.show()
    app.processEvents()

    for index in range(window.stack.count()):
        window.switch_page(index)
        app.processEvents()
        current = window.stack.currentWidget()
        if isinstance(current, QScrollArea):
            assert current.widget().width() <= current.viewport().width()
        else:
            assert current.minimumSizeHint().width() <= current.width()

    window.close()
    app.quit()
