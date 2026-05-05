import sys

from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QTableWidget, QTextEdit
from qfluentwidgets import FluentWindow

from subtitle_info_collection.gui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication(sys.argv)


def test_main_window_uses_fluent_navigation_chrome(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()

    assert window.windowTitle() == "字幕采集工具"
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
    button_texts = {button.text() for button in window.findChildren(QPushButton)}
    assert "自动化脚本" in button_texts or "执行" in button_texts
    assert "自动上传经典台词" not in button_texts
    assert "上传到经典台词" not in button_texts

    window.close()
    app.quit()


def test_professional_pages_fit_existing_desktop_window(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _app()
    window = MainWindow()
    window.resize(1320, 840)
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
