from __future__ import annotations

import os
import ctypes
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
    """用系统消息框显示崩溃信息，避免依赖 GUI 框架"""
    detail = str(exc)
    if log_path:
        detail += f"\n\n崩溃日志已保存至：{log_path}"
    try:
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(
                None, detail, "字幕采集工具 - 启动失败", 0x10
            )
        else:
            print(detail, file=sys.stderr)
    except Exception:
        pass  # 消息框也失败，只能靠日志文件


def _global_excepthook(exc_type, exc_value, exc_tb) -> None:
    """全局异常钩子，捕获未处理异常并写入崩溃日志。"""
    exc = exc_value or exc_type()
    _write_crash_log(exc)


# 执行 Velopack 启动钩子，必须在创建主窗口之前运行
def _run_velopack_hooks() -> None:
    if not getattr(sys, "frozen", False):
        return
    try:
        from velopack import App

        App().run()
    except Exception:
        # 更新框架异常不能阻止主程序启动
        pass


def main() -> int:
    _run_velopack_hooks()
    sys.excepthook = _global_excepthook

    try:
        from subtitle_info_collection.web.shell import run_app
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
