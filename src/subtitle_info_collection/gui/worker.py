from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..local_parser import parse_local_subtitle_file
from ..models import TaskConfig
from ..orchestrator import SubtitleCollectionOrchestrator
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

    def submit_verification(self, code: str) -> None:
        self._verification_code = code
        self._verification_event.set()

    async def _request_verification(self, request) -> str:
        self._verification_event.clear()
        self._verification_code = ""
        self.verification_requested.emit(
            {
                "provider": request.provider,
                "providerSubtitleId": request.provider_subtitle_id,
                "subtitleTitle": request.subtitle_title,
                "detailUrl": request.detail_url,
                "verificationHtml": request.verification_html,
            }
        )
        await asyncio.to_thread(self._verification_event.wait, 300)
        return self._verification_code

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
            )
            result = await orchestrator.run(self.config)
            self.finished_success.emit(result)

        try:
            asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(str(exc))


class ParserWorker(QThread):
    log_message = Signal(str)
    file_parsed = Signal(dict)
    finished_success = Signal(dict)
    finished_error = Signal(str)

    def __init__(self, files: list[Path], output_dir: Path, tmdb_token: str = "") -> None:
        super().__init__()
        self.files = files
        self.output_dir = output_dir
        self.tmdb_token = tmdb_token

    def run(self) -> None:
        async def _run() -> None:
            movies_by_id = {}
            subtitles = []
            successes = []
            failures = []
            self.output_dir.mkdir(parents=True, exist_ok=True)

            for path in self.files:
                try:
                    self.log_message.emit(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 解析字幕：{path.name}")
                    parsed = await parse_local_subtitle_file(path, self.tmdb_token)
                    payload = parsed.payload()
                    movie_id = payload["movieId"]
                    movies_by_id[movie_id] = payload["movieData"]
                    subtitles.extend(payload["subtitlesData"])
                    row = {
                        "file": str(path),
                        "title": payload["title"],
                        "movieId": movie_id,
                        "originalCount": parsed.original_subtitle_count,
                        "exportCount": len(payload["subtitlesData"]),
                        "matchedKeyword": parsed.matched_keyword,
                    }
                    successes.append(row)
                    self.file_parsed.emit(row)
                except Exception as exc:  # noqa: BLE001
                    self.log_message.emit(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 解析失败：{path.name} / {exc}")
                    failure = {"file": str(path), "error": str(exc)}
                    failures.append(failure)
                    self.file_parsed.emit(failure)

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            movies_path = self.output_dir / f"{stamp}-movies.json"
            subtitles_path = self.output_dir / f"{stamp}-subtitles.json"
            movies_path.write_text(
                json.dumps(list(movies_by_id.values()), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            subtitles_path.write_text(
                json.dumps(subtitles, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.finished_success.emit(
                {
                    "moviesPath": str(movies_path),
                    "subtitlesPath": str(subtitles_path),
                    "successes": successes,
                    "failures": failures,
                }
            )

        try:
            asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.finished_error.emit(str(exc))
