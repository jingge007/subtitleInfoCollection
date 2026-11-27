from __future__ import annotations

import threading
from typing import Any

REPOSITORY_URL = "https://github.com/jingge007/subtitleInfoCollection"


class UpdateService:
    """封装 Velopack 更新检查、下载与应用更新流程。"""

    def __init__(self, current_version: str, enabled: bool = True) -> None:
        self.current_version = current_version
        self.enabled = enabled
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
                    status="latest",
                    available=False,
                    latestVersion=self.current_version,
                    notes="源码开发模式不检查更新，请使用打包后的 Portable 版本验证。",
                    progress=0,
                    error="",
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
                    error=f"检查更新失败：{exc}",
                )
        return self.state()

    # 下载已发现的新版本并回调进度
    def download(self) -> None:
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
