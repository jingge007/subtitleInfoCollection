from __future__ import annotations

import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

from .. import __version__
from ..config import (
    CONFIG_GROUP_LABELS,
    ENV_FIELD_META,
    AppSettings,
    bootstrap_env_file,
    read_env_values,
    upsert_env_values,
)
from ..orchestrator import CollectionControl
from ..storage import AppStorage
from .services.automation import run_classic_lines, run_todays_lines
from .services.collection import run_collection
from .services.parser import inspect_subtitle_files, run_parser
from .tasks import ACTIVE_STATUSES, TaskContext, TaskRuntime
from .updater import UpdateService


def _project_root() -> Path:
    """源码运行时的仓库根目录。"""
    return Path(__file__).resolve().parents[4]


def _program_dir() -> Path:
    """打包后返回程序目录，源码运行返回仓库根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _project_root()


class AppApi:
    """暴露给前端 js_api 的应用接口。"""

    def __init__(self) -> None:
        self._bootstrap = bootstrap_env_file()
        self._settings = AppSettings.from_env(self._bootstrap.env_path)
        self._settings_lock = threading.RLock()
        self._window: Any = None
        self._runtime = TaskRuntime()
        self._collector = TaskContext("collector")
        self._parser = TaskContext("parser")
        self._automation = TaskContext("automation")
        self._control: CollectionControl | None = None
        self._updater = UpdateService(
            __version__,
            enabled=bool(getattr(sys, "frozen", False)),
        )

    def bind_window(self, window: Any) -> None:
        """壳创建窗口后回填，供文件对话框使用。"""
        self._window = window

    # ---------- 应用信息与更新 ----------

    def app_info(self) -> dict[str, Any]:
        with self._settings_lock:
            return {
                "version": __version__,
                "dataDir": str(self._settings.data_dir),
                "envPath": str(self._bootstrap.env_path),
                "programDir": str(_program_dir()),
                "platform": sys.platform,
                "frozen": bool(getattr(sys, "frozen", False)),
            }

    def app_check_update(self) -> dict[str, Any]:
        return self._updater.check()

    def app_update_state(self) -> dict[str, Any]:
        return self._updater.state()

    def app_download_update(self) -> None:
        self._updater.download()

    def app_apply_update_and_restart(self) -> None:
        self._updater.apply_and_restart()

    def app_set_always_on_top(self, enabled: bool) -> bool:
        """切换窗口置顶状态并返回目标状态。

        Windows 下 WinForms 的 TopMost 是跨线程同步调用，js_api 回调线程直接赋值会
        阻塞 UI 线程，因此通过 BeginInvoke 投递到 UI 线程异步执行。
        """
        if self._window is None:
            return False
        on_top = bool(enabled)
        if sys.platform == "win32":
            try:
                from System import Action
                from webview.platforms import winforms

                view = winforms.BrowserView.instances.get(self._window.uid)
                if view is not None:
                    view.BeginInvoke(Action(lambda: setattr(view, "TopMost", on_top)))
                    return on_top
            except Exception:  # noqa: BLE001 - 回退到 pywebview 原生接口
                pass
        self._window.on_top = on_top
        return bool(getattr(self._window, "on_top", on_top))

    def app_has_active_tasks(self) -> bool:
        return any(
            context.status in ACTIVE_STATUSES
            for context in (self._collector, self._parser, self._automation)
        )

    def app_status(self) -> dict[str, Any]:
        """返回各任务的运行状态概览，供顶栏展示真实状态。"""
        return {
            "collector": self._collector.status,
            "parser": self._parser.status,
            "automation": self._automation.status,
            "active": self.app_has_active_tasks(),
        }

    # ---------- 配置 ----------

    def config_list(self) -> list[dict[str, Any]]:
        with self._settings_lock:
            values = read_env_values(self._bootstrap.env_path)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for meta in ENV_FIELD_META:
            grouped.setdefault(meta.group, []).append(
                {
                    "key": meta.key,
                    "label": meta.label,
                    "group": meta.group,
                    "widget": meta.widget,
                    "description": meta.description,
                    "value": values.get(meta.key, ""),
                    "secret": meta.secret,
                }
            )
        return [
            {
                "key": group,
                "label": CONFIG_GROUP_LABELS.get(group, group),
                "fields": fields,
            }
            for group, fields in grouped.items()
        ]

    def config_save(self, values: dict[str, str]) -> None:
        if not isinstance(values, dict):
            raise ValueError("配置内容格式不正确")
        normalized = {str(key): str(value) for key, value in values.items()}
        with self._settings_lock:
            upsert_env_values(self._bootstrap.env_path, normalized)
            for key, value in normalized.items():
                if value:
                    os.environ[key] = value
                else:
                    os.environ.pop(key, None)
            self._settings = AppSettings.from_env(self._bootstrap.env_path)

    # ---------- 历史 ----------

    def _storage(self) -> AppStorage:
        with self._settings_lock:
            return AppStorage(self._settings.database_path)

    def history_list(
        self,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = min(max(1, int(page_size)), 200)
        runs, total = self._storage().list_task_runs_page(page, page_size, keyword)
        items = [
            {
                "id": run.get("id"),
                "startedAt": run.get("started_at", ""),
                "finishedAt": run.get("finished_at", ""),
                "year": run.get("year", 0),
                "limit": run.get("limit", 0),
                "status": run.get("status", ""),
                "movieCount": int((run.get("result") or {}).get("movieCount") or 0),
                "failedCount": int((run.get("result") or {}).get("failedCount") or 0),
                "downloadCount": int(
                    (run.get("result") or {}).get("downloadCount") or 0
                ),
                "downloadDir": str((run.get("result") or {}).get("downloadDir") or ""),
            }
            for run in runs
        ]
        return {
            "items": items,
            "total": total,
            "page": page,
            "pageSize": page_size,
        }

    def history_reset(self) -> None:
        if self.app_has_active_tasks():
            raise RuntimeError("任务运行中，请先停止采集、解析或自动化任务")
        self._storage().clear_task_runs()

    # ---------- 采集任务 ----------

    def _ensure_not_active(self, context: TaskContext, label: str) -> None:
        if context.status in ACTIVE_STATUSES:
            raise RuntimeError(f"{label}正在运行，请先停止当前任务")

    def collector_start(self, options: dict[str, Any]) -> bool:
        self._ensure_not_active(self._collector, "采集任务")
        self._collector.reset()
        self._collector.set_status("starting")
        self._control = CollectionControl()
        self._runtime.submit(
            self._collector,
            run_collection(
                self._collector,
                self._settings,
                self._storage(),
                dict(options or {}),
                self._control,
            ),
        )
        return True

    def collector_pause(self) -> None:
        if self._control is not None:
            self._control.pause()
        if self._collector.status == "running":
            self._collector.set_status("paused")

    def collector_resume(self) -> None:
        if self._control is not None:
            self._control.resume()
        if self._collector.status == "paused":
            self._collector.set_status("running")

    def collector_abort(self) -> None:
        if self._control is not None:
            self._control.abort()
        self._collector.set_status("aborting")
        self._collector.clear_verification()
        self._collector.append_log("已请求中止采集")

    def collector_state(self, log_cursor: int = 0) -> dict[str, Any]:
        return self._collector.snapshot(log_cursor)

    def collector_submit_verification(self, code: str) -> bool:
        if self._collector.snapshot().get("verification") is None:
            return False
        self._collector.submit_verification(code)
        return True

    def collector_refresh_captcha(self) -> bool:
        if self._collector.snapshot().get("verification") is None:
            return False
        self._collector.refresh_verification()
        return True

    # ---------- 字幕解析 ----------

    def parser_pick_files(self) -> list[str]:
        if self._window is None:
            return []
        import webview

        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("字幕文件 (*.srt;*.ass)", "所有文件 (*.*)"),
        )
        if not result:
            return []
        if isinstance(result, str):
            return [result]
        return [str(path) for path in result]

    def parser_inspect_files(self, paths: list[str]) -> list[dict[str, Any]]:
        if not isinstance(paths, list):
            raise ValueError("文件列表格式不正确")
        return inspect_subtitle_files([str(path) for path in paths])

    def parser_start(self, options: dict[str, Any]) -> bool:
        self._ensure_not_active(self._parser, "字幕解析")
        files = options.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("请先选择字幕文件")
        with self._settings_lock:
            default_output = self._settings.data_dir / "parsed"
        output_dir = Path(str(options.get("outputDir") or default_output)).expanduser()
        unicloud = str(options.get("format") or "unicloud") == "unicloud"
        self._parser.reset(total=len(files))
        self._parser.set_status("starting")
        self._runtime.submit(
            self._parser,
            run_parser(
                self._parser,
                [str(path) for path in files],
                output_dir,
                self._settings.tmdb_token,
                unicloud,
            ),
        )
        return True

    def parser_state(self, log_cursor: int = 0) -> dict[str, Any]:
        return self._parser.snapshot(log_cursor)

    def parser_abort(self) -> None:
        self._parser.set_status("aborting")
        self._parser.cancel()

    # ---------- 33 台词自动化 ----------

    def automation_start_todays(self, options: dict[str, Any]) -> bool:
        self._ensure_not_active(self._automation, "自动化任务")
        self._automation.reset()
        self._automation.set_status("starting")
        unicloud = str(options.get("format") or "unicloud") == "unicloud"
        self._runtime.submit(
            self._automation,
            run_todays_lines(
                self._automation,
                self._settings.data_dir,
                self._bootstrap.env_path,
                unicloud,
            ),
        )
        return True

    def automation_start_classic(self, options: dict[str, Any]) -> bool:
        self._ensure_not_active(self._automation, "自动化任务")
        self._automation.reset()
        self._automation.set_status("starting")
        unicloud = str(options.get("format") or "unicloud") == "unicloud"
        max_pages_raw = str(options.get("maxPages") or "").strip()
        max_pages = int(max_pages_raw) if max_pages_raw.isdigit() else None
        self._runtime.submit(
            self._automation,
            run_classic_lines(
                self._automation,
                self._settings.data_dir,
                unicloud,
                int(options.get("concurrency") or 8),
                max_pages,
            ),
        )
        return True

    def automation_state(self, log_cursor: int = 0) -> dict[str, Any]:
        return self._automation.snapshot(log_cursor)

    def automation_abort(self) -> None:
        self._automation.set_status("aborting")
        self._automation.cancel()

    # ---------- 桌面壳能力 ----------

    def shell_open_path(self, path: str) -> bool:
        target = Path(str(path)).expanduser()
        if not target.exists():
            raise FileNotFoundError(f"路径不存在：{target}")
        os.startfile(str(target))  # type: ignore[attr-defined]
        return True

    def shell_pick_directory(self) -> str | None:
        if self._window is None:
            return None
        import webview

        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return None
        if isinstance(result, str):
            return result
        return str(result[0])

    def shell_delete_outputs(self) -> bool:
        if self.app_has_active_tasks():
            raise RuntimeError("任务运行中，请先停止采集、解析或自动化任务")
        with self._settings_lock:
            data_dir = self._settings.data_dir.expanduser().resolve()
        output_dir = (data_dir / "output").resolve()
        try:
            output_dir.relative_to(data_dir)
        except ValueError as exc:
            raise ValueError("输出目录不在当前数据目录内，请取消删除") from exc
        if output_dir.name != "output":
            raise ValueError("输出目录名称异常，请取消删除")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self._storage().clear_task_runs()
        return True
