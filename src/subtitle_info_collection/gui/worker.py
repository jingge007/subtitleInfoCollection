from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..automation import (
    ClassicLinesAutomationOptions,
    ClassicLinesAutomationRunner,
    TodaysLinesAutomationOptions,
    TodaysLinesAutomationRunner,
)
from ..errors import VerificationResult
from ..local_parser import (parse_local_subtitle_file, write_movie_export_files, write_movie_search_index_file, write_subtitle_export_files)
from ..models import TaskConfig
from ..orchestrator import CollectionControl, SubtitleCollectionOrchestrator
from ..storage import AppStorage


class CollectorWorker(QThread):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    verification_requested = Signal(dict)
    finished_success = Signal(dict)
    finished_error = Signal(str)

    def __init__(self, config: TaskConfig, database_path: Path) -> None:
        super().__init__()
        self.config = config
        self.database_path = database_path
        self._verification_event = threading.Event()
        self._verification_code = ""
        self._verification_refresh = False
        self._control = CollectionControl()

    # 暂停采集：已在飞电影继续，后续电影等待
    def pause_collection(self) -> None:
        self._control.pause()
        self.log_message.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 已请求暂停采集")

    # 继续采集
    def resume_collection(self) -> None:
        self._control.resume()
        self.log_message.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 已继续采集")

    # 中止采集：未开始电影跳过，保留已完成结果
    def abort_collection(self) -> None:
        self._control.abort()
        self._verification_event.set()
        self.log_message.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 已请求中止采集")

    def submit_verification(self, code: str) -> None:
        self._verification_code = code
        self._verification_refresh = False
        self._verification_event.set()

    def request_captcha_refresh(self) -> None:
        self._verification_refresh = True
        self._verification_event.set()

    async def _request_verification(self, request) -> VerificationResult:
        self._verification_event.clear()
        self._verification_code = ""
        self._verification_refresh = False
        self.verification_requested.emit(
            {
                "provider": request.provider,
                "providerSubtitleId": request.provider_subtitle_id,
                "subtitleTitle": request.subtitle_title,
                "detailUrl": request.detail_url,
                "verificationHtml": request.verification_html,
                "verificationImageDataUri": request.verification_image_data_uri,
                "suggestedCode": request.suggested_code,
                "suggestedConfidence": request.suggested_confidence,
                "ocrMessage": request.ocr_message,
            }
        )
        # 分段等待，便于中止时提前结束验证码弹窗等待
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self._control.verification_should_stop():
                return VerificationResult(code="")
            if await asyncio.to_thread(self._verification_event.wait, 0.5):
                break
        else:
            return VerificationResult(code="")
        if self._control.verification_should_stop():
            return VerificationResult(code="")
        if self._verification_refresh:
            return VerificationResult(refresh=True)
        return VerificationResult(code=self._verification_code)

    def run(self) -> None:
        async def _run() -> None:
            storage = AppStorage(self.database_path)
            orchestrator = SubtitleCollectionOrchestrator(
                storage=storage,
                log=self.log_message.emit,
                progress=lambda payload: self.progress_changed.emit(
                    int(payload.get("current") or 0),
                    int(payload.get("total") or 0),
                    str(payload.get("currentMovie") or ""),
                ),
                request_verification=self._request_verification,
                control=self._control,
            )
            result = await orchestrator.run(self.config)
            self.finished_success.emit(result)

        try:
            asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(str(exc))


class ParserWorker(QThread):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    finished_success = Signal(dict)
    finished_error = Signal(str)

    def __init__(
        self,
        files: list[Path],
        output_dir: Path,
        tmdb_token: str = "",
        unicloud_import_format: bool = True,
    ) -> None:
        super().__init__()
        self.files = files
        self.output_dir = output_dir
        self.tmdb_token = tmdb_token
        self.unicloud_import_format = unicloud_import_format

    def run(self) -> None:
        async def _run() -> None:
            movies_by_id = {}
            subtitles = []
            success_count = 0
            failure_count = 0
            self.output_dir.mkdir(parents=True, exist_ok=True)

            total = len(self.files)
            for index, path in enumerate(self.files, start=1):
                self.progress_changed.emit(index - 1, total, path.name)
                try:
                    self.log_message.emit(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 解析字幕：{path.name}")
                    parsed = await parse_local_subtitle_file(path, self.tmdb_token)
                    payload = parsed.payload()
                    movie_id = payload["movieId"]
                    movies_by_id[movie_id] = payload["movieData"]
                    subtitles.extend(payload["subtitlesData"])
                    success_count += 1
                    self.progress_changed.emit(index, total, path.name)
                except Exception as exc:  # noqa: BLE001
                    self.log_message.emit(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 解析失败：{path.name} / {exc}")
                    failure_count += 1
                    self.progress_changed.emit(index, total, path.name)

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            movies_export = write_movie_export_files(
                list(movies_by_id.values()),
                self.output_dir,
                stamp,
                unicloud_import_format=self.unicloud_import_format,
            )
            subtitles_export = write_subtitle_export_files(
                subtitles,
                self.output_dir,
                stamp,
                unicloud_import_format=self.unicloud_import_format,
            )
            index_export = write_movie_search_index_file(
                subtitles=subtitles,
                movies=list(movies_by_id.values()),
                output_dir=self.output_dir,
                stamp=stamp,
                unicloud_import_format=self.unicloud_import_format,
            )
            self.finished_success.emit(
                {
                    "moviesPath": str(movies_export.paths[0]),
                    "moviesPaths": [str(path) for path in movies_export.paths],
                    "moviesFormat": movies_export.export_format,
                    "moviesSplitLimitBytes": movies_export.split_limit_bytes,
                    "moviesOversizedRecords": movies_export.oversized_records,
                    "subtitlesPath": str(subtitles_export.paths[0]),
                    "subtitlesPaths": [str(path) for path in subtitles_export.paths],
                    "subtitlesFormat": subtitles_export.export_format,
                    "subtitleSplitLimitBytes": subtitles_export.split_limit_bytes,
                    "subtitleOversizedRecords": subtitles_export.oversized_records,
                    "movieSearchIndexPath": str(index_export.paths[0]),
                    "movieSearchIndexPaths": [str(path) for path in index_export.paths],
                    "movieSearchIndexFormat": index_export.export_format,
                    "movieSearchIndexSplitLimitBytes": index_export.split_limit_bytes,
                    "movieSearchIndexOversizedRecords": index_export.oversized_records,
                    "totalCount": total,
                    "successCount": success_count,
                    "failureCount": failure_count,
                    "exportCount": len(subtitles),
                    "outputPaths": [*[str(path) for path in movies_export.paths], *[str(path) for path in subtitles_export.paths], *[str(path) for path in index_export.paths]],
                }
            )

        try:
            asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(str(exc))


class AutomationScriptWorker(QThread):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    finished_success = Signal(dict)
    finished_error = Signal(str)

    def __init__(
        self,
        data_dir: Path,
        env_path: Path | None = None,
        unicloud_import_format: bool = True,
    ) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.env_path = env_path
        self.unicloud_import_format = unicloud_import_format

    def run(self) -> None:
        async def _run() -> None:
            runner = TodaysLinesAutomationRunner(
                TodaysLinesAutomationOptions(
                    data_dir=self.data_dir,
                    env_path=self.env_path,
                    unicloud_import_format=self.unicloud_import_format,
                ),
                log=self.log_message.emit,
                progress=lambda c, t, n: self.progress_changed.emit(c, t, n),
            )
            result = await runner.run()
            self.finished_success.emit(
                {
                    "outputPath": str(result.output_path),
                    "outputPaths": [str(path) for path in result.output_paths],
                    "totalCount": result.total_count,
                    "inputCount": result.input_count,
                    "skippedCount": result.skipped_count,
                    "pageCount": result.page_count,
                    "startedAt": result.started_at,
                    "finishedAt": result.finished_at,
                    "exportFormat": result.export_format,
                    "splitLimitBytes": result.split_limit_bytes,
                    "oversizedRecords": result.oversized_records,
                    "translationRequestedCount": result.translation_requested_count,
                    "translationFilledCount": result.translation_filled_count,
                    "translationFailureCount": result.translation_failure_count,
                }
            )

        try:
            asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(str(exc))


class ClassicLinesAutomationWorker(QThread):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    finished_success = Signal(dict)
    finished_error = Signal(str)

    # 仅接收 uniCloud 开关；其余爬取参数使用内部默认
    def __init__(
        self,
        data_dir: Path,
        *,
        unicloud_import_format: bool = True,
    ) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.unicloud_import_format = unicloud_import_format

    # 在后台线程执行经典台词全量爬取
    def run(self) -> None:
        async def _run() -> None:
            # 默认全量采集：并发 8、无请求间隔、无页数上限
            options = ClassicLinesAutomationOptions(
                data_dir=self.data_dir,
                unicloud_import_format=self.unicloud_import_format,
                request_delay_seconds=0.0,
                concurrency=8,
                max_pages=None,
                headless=True,
            )
            runner = ClassicLinesAutomationRunner(
                options,
                log=self.log_message.emit,
                progress=lambda c, t, n: self.progress_changed.emit(c, t, n),
            )
            result = await runner.run()
            self.finished_success.emit(result.to_dict())

        try:
            asyncio.run(_run())
        except Exception as exc:
            self.finished_error.emit(str(exc))

