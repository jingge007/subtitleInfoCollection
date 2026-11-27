from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import sys
from pathlib import Path

import webview

from .. import __version__
from .api import AppApi

APP_TITLE = "字幕采集工具"
WINDOW_SIZE = (1280, 820)


def _webui_dir() -> Path:
    """定位前端构建产物：打包目录优先，源码运行回退 frontend/dist"""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "webui")
        candidates.append(exe_dir / "_internal" / "webui")
        candidates.append(exe_dir / "webui")
    candidates.append(Path(__file__).resolve().parents[4] / "frontend" / "dist")
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    searched = ", ".join(str(item) for item in candidates)
    raise FileNotFoundError(f"未找到前端构建产物，请先执行 npm run build：{searched}")


def _webui_url() -> str:
    """打包态入口地址：附带 index.html 内容指纹，规避 WebView2 缓存的旧页面。

    pywebview 的 no-store 响应头会被 bottle.static_file 覆盖，实际只返回
    ETag/Last-Modified；而 PyInstaller 会把文件时间归零，导致 ETag 恒定，
    浏览器条件请求始终命中缓存。程序目录被自更新替换后，缓存里的旧
    index.html 会指向已删除的旧资源，导致白屏。用内容指纹做缓存键可规避。
    """
    index_path = _webui_dir() / "index.html"
    digest = hashlib.sha1(index_path.read_bytes()).hexdigest()[:8]
    return f"{index_path}?v={__version__}-{digest}"


def _acquire_single_instance() -> bool:
    """Windows 命名互斥体，避免重复启动多个窗口"""
    if sys.platform != "win32":
        return True
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\SubtitleInfoCollection")
    if not handle:
        return True
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return False
    globals()["_SINGLE_INSTANCE_HANDLE"] = handle
    return True


def _activate_existing_window() -> None:
    """二次启动时尝试激活已存在的主窗口。"""
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    handle = user32.FindWindowW(None, APP_TITLE)
    if not handle:
        # 打包后标题可能带版本后缀，按前缀枚举窗口更稳妥
        handles: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def collect_window(hwnd: int, _lparam: int) -> int:
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return 1
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value.startswith(APP_TITLE):
                handles.append(hwnd)
                return 0
            return 1

        user32.EnumWindows(callback_type(collect_window), 0)
        handle = handles[0] if handles else 0
    if handle:
        user32.ShowWindow(handle, 9)
        user32.SetForegroundWindow(handle)


def _webview_storage_dir() -> Path:
    """WebView2 用户数据固定到 LocalAppData，避免写入会被更新替换的程序目录。"""
    base = os.getenv("LOCALAPPDATA") or str(Path.home())
    path = Path(base) / "subtitleInfoCollection" / "webview"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _icon_path() -> str | None:
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / "head_logo.ico")
    candidates.append(Path(__file__).resolve().parents[3] / "assets" / "head_logo.ico")
    candidates.append(Path(sys.executable).resolve().parent / "assets" / "head_logo.ico")
    candidates.append(
        Path(sys.executable).resolve().parent / "_internal" / "assets" / "head_logo.ico"
    )
    return next((str(path) for path in candidates if path.exists()), None)


def _show_error(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, f"{APP_TITLE} v{__version__}", 0x10)
    else:
        print(message, file=sys.stderr)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="subtitle-info-collection")
    parser.add_argument("--dev-url", help="Vite 开发服务器地址，例如 http://127.0.0.1:5173")
    parser.add_argument("--devtools", action="store_true", help="打开 WebView2 开发者工具")
    return parser.parse_args(argv[1:])


def run_app(argv: list[str]) -> int:
    args = _parse_args(argv)
    if not _acquire_single_instance():
        _activate_existing_window()
        return 0

    try:
        if args.dev_url:
            url = args.dev_url
        else:
            url = _webui_url()
        api = AppApi()
        window = webview.create_window(
            APP_TITLE,
            url,
            js_api=api,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=(1024, 700),
            text_select=False,
            background_color="#F5F6F8",
        )
        api.bind_window(window)

        def on_closing() -> bool:
            if not api.app_has_active_tasks():
                return True
            return bool(
                window.create_confirmation_dialog(
                    "任务正在运行",
                    "仍有采集、解析或自动化任务在运行，确定关闭并中止任务吗？",
                )
            )

        window.events.closing += on_closing
        webview.start(
            debug=args.devtools,
            http_server=True,
            private_mode=False,
            storage_path=str(_webview_storage_dir()),
            icon=_icon_path(),
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        _show_error(
            "应用启动失败。\n\n"
            f"{exc}\n\n"
            "若提示缺少 WebView2，请安装 Microsoft Edge WebView2 Runtime 后重试。"
        )
        return 1
