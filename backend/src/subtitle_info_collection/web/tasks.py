from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Coroutine

from ..errors import VerificationResult

MAX_LOG_LINES = 2000
ACTIVE_STATUSES = {"starting", "running", "pausing", "paused", "aborting"}


@dataclass(slots=True)
class TaskContext:
    """单个后台任务的线程安全状态与日志缓冲。"""

    name: str
    status: str = "idle"
    current: int = 0
    total: int = 0
    current_item: str = ""
    error: str = ""
    stats: dict[str, Any] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    _lock: threading.Lock = field(init=False, repr=False)
    _logs: deque[tuple[int, str]] = field(init=False, repr=False)
    _log_seq: int = field(init=False, default=0, repr=False)
    _verification_event: threading.Event = field(init=False, repr=False)
    _verification_payload: dict[str, Any] | None = field(init=False, default=None, repr=False)
    _verification_code: str = field(init=False, default="", repr=False)
    _verification_refresh: bool = field(init=False, default=False, repr=False)
    _future: Any = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._logs = deque(maxlen=MAX_LOG_LINES)
        self._log_seq = 0
        self._verification_event = threading.Event()
        self._verification_payload = None
        self._verification_code = ""
        self._verification_refresh = False
        self._future = None

    # 重置任务状态并清空上一轮日志
    def reset(self, *, total: int = 0) -> None:
        with self._lock:
            self.status = "starting"
            self.current = 0
            self.total = max(0, int(total))
            self.current_item = ""
            self.error = ""
            self.stats = {}
            self.outputs = []
            self.started_at = time.time()
            self.finished_at = 0.0
            self._logs.clear()
            self._log_seq = 0
            self._verification_event.clear()
            self._verification_payload = None
            self._verification_code = ""
            self._verification_refresh = False

    # 更新任务状态，任务结束后记录结束时间
    def set_status(self, status: str, *, error: str = "") -> None:
        with self._lock:
            self.status = status
            if error:
                self.error = error
            if status in {"finished", "error", "aborted", "idle"}:
                self.finished_at = time.time()

    # 更新进度与当前处理对象，并保证总数不小于当前进度
    def set_progress(self, current: int, total: int | None = None, item: str = "") -> None:
        normalized_current = max(0, int(current))
        with self._lock:
            self.current = normalized_current
            if total is not None:
                self.total = max(normalized_current, int(total), 0)
            elif self.total > 0:
                self.total = max(self.total, normalized_current)
            if item:
                self.current_item = str(item)

    # 合并实时统计字段，调用方统一使用关键字参数
    def update_stats(self, **values: Any) -> None:
        with self._lock:
            self.stats.update(values)

    # 写入日志并分配递增游标
    def append_log(self, message: str) -> None:
        text = str(message).rstrip()
        if not text:
            return
        with self._lock:
            for line in text.splitlines():
                self._log_seq += 1
                self._logs.append((self._log_seq, line))

    # 生成前端轮询快照，日志按游标增量返回
    def snapshot(self, log_cursor: int = 0, log_limit: int = 300) -> dict[str, Any]:
        with self._lock:
            cursor = max(0, int(log_cursor))
            pending = [(seq, line) for seq, line in self._logs if seq > cursor]
            selected = pending[-max(1, min(int(log_limit), 1000)) :]
            next_cursor = selected[-1][0] if selected else max(cursor, self._log_seq)
            verification = dict(self._verification_payload) if self._verification_payload else None
            display_total = max(self.total, self.current)
            return {
                "status": self.status,
                "current": self.current,
                "total": display_total,
                "currentItem": self.current_item,
                "stats": dict(self.stats),
                "error": self.error,
                "outputPaths": list(self.outputs),
                "logs": [line for _, line in selected],
                "nextLogCursor": next_cursor,
                "verification": verification,
                "startedAt": self.started_at,
                "finishedAt": self.finished_at,
            }

    # 暴露验证码请求给前端，并等待人工输入或刷新
    async def request_verification(self, request: Any) -> VerificationResult:
        payload = {
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
        with self._lock:
            self._verification_payload = payload
            self._verification_refresh = False
            self._verification_code = ""
            self._verification_event.clear()
        self.append_log(f"[验证码] {request.provider} 需要人工校验")

        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self.status in {"aborting", "aborted"}:
                self.clear_verification()
                return VerificationResult(code="")
            if await asyncio.to_thread(self._verification_event.wait, 0.5):
                with self._lock:
                    code = self._verification_code
                    refresh = self._verification_refresh
                    self._verification_payload = None
                    self._verification_event.clear()
                if refresh:
                    return VerificationResult(refresh=True)
                return VerificationResult(code=code)

        self.clear_verification()
        self.append_log("[验证码] 等待超时，已跳过当前验证码")
        return VerificationResult(code="")

    # 接收前端提交的验证码
    def submit_verification(self, code: str) -> None:
        with self._lock:
            self._verification_code = str(code or "").strip()
            self._verification_refresh = False
            self._verification_event.set()

    # 通知后台刷新验证码
    def refresh_verification(self) -> None:
        with self._lock:
            self._verification_refresh = True
            self._verification_event.set()

    # 清理验证码请求
    def clear_verification(self) -> None:
        with self._lock:
            self._verification_payload = None
            self._verification_event.set()

    # 记录后台 Future，供中止时取消
    def set_future(self, future: Any) -> None:
        with self._lock:
            self._future = future

    # 取消后台协程
    def cancel(self) -> None:
        with self._lock:
            future = self._future
        if future is not None and not future.done():
            future.cancel()


class TaskRuntime:
    """维护专用 asyncio 事件循环线程，供所有 js_api 任务提交协程。"""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # 惰性创建事件循环线程
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever,
                name="subtitle-web-task-loop",
                daemon=True,
            )
            thread.start()
            self._loop = loop
            self._thread = thread
            return loop

    # 提交协程并返回 concurrent.futures.Future
    def submit(self, context: TaskContext, coroutine: Coroutine[Any, Any, Any]) -> Any:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._ensure_loop())
        context.set_future(future)
        return future

    # 判断任务是否仍处于活动状态
    @staticmethod
    def is_active(context: TaskContext) -> bool:
        return context.status in ACTIVE_STATUSES
