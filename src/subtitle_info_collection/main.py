from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _crash_log_dir() -> Path:
    """崩溃日志目录：%APPDATA%/subtitleInfoCollection"""
    return Path(os.getenv("APPDATA", Path.home())) / "subtitleInfoCollection"


def _write_crash_log(exc: BaseException) -> Path | None:
    """将异常信息写入崩溃日志文件，返回日志路径（失败返回 None）"""
    try:
        log_dir = _crash_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "crash.log"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tb_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        entry = (
            f"\n{'=' * 60}\n"
            f"[{timestamp}] 应用崩溃\n"
            f"{'=' * 60}\n"
            f"{tb_text}\n"
        )
        if log_path.exists():
            existing = log_path.read_text(encoding="utf-8", errors="replace")
            log_path.write_text(existing + entry, encoding="utf-8")
        else:
            log_path.write_text(entry, encoding="utf-8")
        return log_path
    except Exception:
        return None


def _show_crash_dialog(exc: BaseException, log_path: Path | None) -> None:
    """尝试用 QMessageBox 显示崩溃对话框"""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("字幕采集工具 - 启动失败")
        msg.setText("应用启动时发生错误，无法继续运行。")
        detail = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        if log_path:
            detail += f"\n\n崩溃日志已保存至：{log_path}"
        else:
            detail += "\n\n崩溃日志写入失败。"
        msg.setDetailedText(detail)
        msg.exec()
    except Exception:
        pass  # QMessageBox 也失败，只能靠日志文件


def _global_excepthook(exc_type, exc_value, exc_tb) -> None:
    """全局异常钩子，捕获 Qt 事件循环中的未处理异常，写入日志"""
    exc = exc_value or exc_type()
    _write_crash_log(exc)


def main() -> int:
    sys.excepthook = _global_excepthook

    try:
        from subtitle_info_collection.gui.main_window import run_app
    except ImportError as exc:
        log_path = _write_crash_log(exc)
        _show_crash_dialog(exc, log_path)
        return 1

    try:
        return run_app(sys.argv)
    except Exception as exc:
        log_path = _write_crash_log(exc)
        _show_crash_dialog(exc, log_path)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
