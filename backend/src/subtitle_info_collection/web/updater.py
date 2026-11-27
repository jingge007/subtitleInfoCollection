from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

REPOSITORY_URL = "https://github.com/jingge007/subtitleInfoCollection"

# 运行形态：源码开发版 / Velopack 安装版 / Velopack 便携解压版 / 原始 onedir 产物
RUN_MODE_SOURCE = "source"
RUN_MODE_INSTALLED = "installed"
RUN_MODE_PORTABLE = "portable"
RUN_MODE_ONEDIR = "onedir"

# 具备 Velopack 自更新能力的运行形态
UPDATE_CAPABLE_MODES = (RUN_MODE_INSTALLED, RUN_MODE_PORTABLE)

# 不具备自更新能力时的中文说明
UNSUPPORTED_NOTES = {
    RUN_MODE_SOURCE: "源码开发模式不检查更新，请使用打包后的安装版或便携解压版验证升级流程。",
    RUN_MODE_ONEDIR: (
        "当前运行的是未注册的便携目录原始产物，Velopack 未安装，无法检查更新。"
        "请改用安装版（Setup.exe）或便携解压版（Portable.zip）后重试。"
    ),
}

# Velopack 定位应用清单失败时的原始异常特征
MANIFEST_ERROR_HINTS = ("not properly installed", "auto-locate", "app manifest")


def detect_run_mode() -> str:
    """识别当前运行形态，判断是否具备 Velopack 自更新能力。"""
    if not getattr(sys, "frozen", False):
        return RUN_MODE_SOURCE
    exe_dir = Path(sys.executable).resolve().parent
    # Velopack 安装版与便携解压版都会在程序目录放置应用清单 sq.version
    if not (exe_dir / "sq.version").exists():
        return RUN_MODE_ONEDIR
    # 便携解压版根目录带 .portable 标记，安装版没有
    if (exe_dir.parent / ".portable").exists():
        return RUN_MODE_PORTABLE
    return RUN_MODE_INSTALLED


class UpdateService:
    """封装 Velopack 更新检查、下载与应用更新流程。"""

    def __init__(
        self,
        current_version: str,
        enabled: bool = True,
        run_mode: str | None = None,
    ) -> None:
        self.current_version = current_version
        self.run_mode = run_mode if run_mode is not None else detect_run_mode()
        self.enabled = enabled and self.run_mode in UPDATE_CAPABLE_MODES
        self._lock = threading.Lock()
        self._manager: Any = None
        self._pending: Any = None
        self._state: dict[str, Any] = {
            "status": "idle",
            "available": False,
            "currentVersion": current_version,
            "latestVersion": "",
            "notes": "",
            "progress": 0,
            "error": "",
        }

    # 获取当前更新状态快照
    def state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    # 创建匿名 GitHub Releases 更新管理器
    def _get_manager(self) -> Any:
        if self._manager is not None:
            return self._manager
        from velopack import GithubSource, UpdateManager

        self._manager = UpdateManager(GithubSource(REPOSITORY_URL))
        return self._manager

    # 检查是否有新版本
    def check(self) -> dict[str, Any]:
        if not self.enabled:
            with self._lock:
                self._pending = None
                self._state.update(
                    status="unsupported",
                    available=False,
                    latestVersion=self.current_version,
                    notes="",
                    progress=0,
                    error=UNSUPPORTED_NOTES.get(
                        self.run_mode, "当前运行形态不支持自更新。"
                    ),
                )
            return self.state()
        with self._lock:
            self._state.update(status="checking", error="", progress=0)
        try:
            info = self._get_manager().check_for_updates()
            if info is None:
                with self._lock:
                    self._pending = None
                    self._state.update(
                        status="latest",
                        available=False,
                        latestVersion=self.current_version,
                        notes="",
                    )
                return self.state()

            release = info.TargetFullRelease
            with self._lock:
                self._pending = info
                self._state.update(
                    status="available",
                    available=True,
                    latestVersion=str(release.Version),
                    notes=str(release.NotesMarkdown or ""),
                    progress=0,
                )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._pending = None
                self._state.update(
                    status="error",
                    available=False,
                    latestVersion="",
                    notes="",
                    error=self._describe_error(exc),
                )
        return self.state()

    # 下载已发现的新版本并回调进度
    def download(self) -> None:
        if not self.enabled:
            raise RuntimeError("当前运行形态不支持自更新")
        with self._lock:
            info = self._pending
        if info is None:
            raise RuntimeError("请先检查更新")

        with self._lock:
            self._state.update(status="downloading", progress=0, error="")

        def progress_callback(*args: Any) -> None:
            percent = self._parse_progress(args)
            with self._lock:
                self._state["progress"] = percent

        try:
            self._get_manager().download_updates(info, progress_callback)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._state.update(status="error", error=f"下载更新失败：{exc}")
            raise

        with self._lock:
            self._state.update(status="ready", progress=100)

    # 退出当前进程并重启到新版本
    def apply_and_restart(self) -> None:
        if not self.enabled:
            raise RuntimeError("当前运行形态不支持自更新")
        with self._lock:
            info = self._pending
            self._state.update(status="restarting")
        if info is None:
            raise RuntimeError("没有可安装的更新")
        try:
            self._get_manager().apply_updates_and_restart(info)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._state.update(status="error", error=f"安装更新失败：{exc}")
            raise

    # 把 Velopack 原始异常翻译成中文提示
    @staticmethod
    def _describe_error(exc: Exception) -> str:
        text = str(exc)
        lowered = text.lower()
        if any(hint in lowered for hint in MANIFEST_ERROR_HINTS):
            return (
                "Velopack 未能识别当前程序（缺少应用清单 sq.version），"
                "请改用安装版（Setup.exe）或便携解压版（Portable.zip）运行。"
            )
        return f"检查更新失败：{exc}"

    # 兼容 Velopack 不同版本的进度回调参数
    @staticmethod
    def _parse_progress(args: tuple[Any, ...]) -> int:
        if not args:
            return 0
        progress = args[0]
        for attribute in ("Percent", "percent", "Progress", "progress"):
            if hasattr(progress, attribute):
                try:
                    value = float(getattr(progress, attribute))
                except (TypeError, ValueError):
                    break
                if 0 <= value <= 1:
                    value *= 100
                return max(0, min(100, int(value)))
        if len(args) >= 2:
            try:
                current = float(args[0])
                total = float(args[1])
                if total > 0:
                    return max(0, min(100, int(current / total * 100)))
            except (TypeError, ValueError):
                pass
        value = progress
        if isinstance(value, dict):
            value = value.get("percent", value.get("progress", 0))
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0
        if 0 <= number <= 1:
            number *= 100
        return max(0, min(100, int(number)))
