from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .adapters.assrt import AssrtProvider
from .adapters.base import (
    DownloadContext,
    ProviderAdapter,
    ProviderHealth,
    RequestVerificationCallback,
    proxy_from_mapping,
)
from .adapters.opensubtitles import OpenSubtitlesProvider
from .adapters.subdl import SubdlProvider
from .adapters.subhd import SubhdProvider
from .adapters.tmdb import TmdbClient
from .config import ASSRT_INTERNAL_INTERVAL_MS
from .engines.archives import safe_filename, save_downloaded_payloads
from .engines.scorer import has_movie_identity_match, score_candidate, sort_candidates
from .engines.subtitle_engine import validate_candidate_metadata
from .errors import CollectorError, ErrorType, classify_exception
from .models import (
    DownloadResult,
    FailedRecord,
    MovieInfo,
    SubtitleCandidate,
    TaskConfig,
    now_iso,
)
from .storage import AppStorage

LogCallback = Callable[[str], None]
ProgressCallback = Callable[[dict[str, object]], None]

# download 路径需要编排器分桶限流的 API 字幕源（SubHD 仅靠每源互斥）
_DOWNLOAD_RATE_LIMITED_PROVIDERS = frozenset({"assrt", "subdl", "opensubtitles"})


@dataclass(slots=True)
class RunPaths:
    output_dir: Path
    download_dir: Path


class CollectionControl:
    """采集任务协作式暂停/中止控制（GUI 线程可安全调用 pause/resume/abort）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._aborted = False
        self._paused = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._resume_event: asyncio.Event | None = None
        self._abort_event = threading.Event()

    # 绑定当前 asyncio 事件循环，供跨线程控制
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._resume_event = asyncio.Event()
        self._resume_event.set()

    # 是否已请求中止
    def is_aborted(self) -> bool:
        with self._lock:
            return self._aborted

    # 是否处于暂停态
    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    # 请求暂停：已在飞电影继续，后续电影在门闩等待
    def pause(self) -> None:
        with self._lock:
            if self._aborted:
                return
            self._paused = True
        self._schedule(self._clear_resume_event)

    # 继续采集：放开暂停门闩
    def resume(self) -> None:
        with self._lock:
            self._paused = False
        self._schedule(self._set_resume_event)

    # 请求中止：未开始电影跳过，已在飞的跑完后收尾
    def abort(self) -> None:
        with self._lock:
            self._aborted = True
            self._paused = False
        self._abort_event.set()
        self._schedule(self._set_resume_event)

    # 线程安全触发验证码等待提前结束
    def wake_verification_waiters(self) -> None:
        self._abort_event.set()

    # 供验证码等待轮询：中止时返回 True
    def verification_should_stop(self) -> bool:
        return self.is_aborted()

    # 电影入口：中止则跳过；暂停则挂起直到继续或中止
    async def wait_if_paused_or_aborted(self) -> bool:
        if self.is_aborted():
            return True
        event = self._resume_event
        if event is None:
            return self.is_aborted()
        while self.is_paused() and not self.is_aborted():
            await event.wait()
            if self.is_aborted():
                return True
            if self.is_paused():
                event.clear()
                continue
            break
        return self.is_aborted()

    # 可被中止打断的分段 sleep（用于限流等待）
    async def interruptible_sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        end_at = asyncio.get_running_loop().time() + seconds
        while True:
            if self.is_aborted():
                return
            remaining = end_at - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.2, remaining))

    def _schedule(self, callback: Callable[[], None]) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        loop.call_soon_threadsafe(callback)

    def _clear_resume_event(self) -> None:
        if self._resume_event is not None:
            self._resume_event.clear()

    def _set_resume_event(self) -> None:
        if self._resume_event is not None:
            self._resume_event.set()


def timestamp_tag(value: datetime | None = None) -> str:
    date = value or datetime.now()
    return date.strftime("%Y%m%d%H%M%S")


def get_run_paths(output_root: Path, year: int, limit: int, started_at: datetime | None = None) -> RunPaths:
    stamp = timestamp_tag(started_at)
    top_tag = f"top{limit}"
    output_dir = output_root / f"{stamp}-{year}-{top_tag}"
    return RunPaths(
        output_dir=output_dir,
        download_dir=output_dir,
    )


def create_provider_registry(config: TaskConfig) -> dict[str, ProviderAdapter]:
    proxy_url = proxy_from_mapping(config.proxies)
    return {
        "subhd": SubhdProvider(proxy=proxy_url),
        "subdl": SubdlProvider(
            api_key=config.subdl_api_key,
            base_url=config.subdl_base_url,
            download_base_url=config.subdl_download_base_url,
            languages=config.subdl_languages,
            include_traditional=config.subdl_include_traditional,
            proxy=proxy_url,
        ),
        "assrt": AssrtProvider(
            token=config.assrt_token,
            base_url=config.assrt_api_base_url,
            request_interval_ms=ASSRT_INTERNAL_INTERVAL_MS,
            proxy=proxy_url,
        ),
        "opensubtitles": OpenSubtitlesProvider(
            api_key=config.opensubtitles_api_key,
            username=config.opensubtitles_username,
            password=config.opensubtitles_password,
            base_url=config.opensubtitles_base_url,
            user_agent=config.opensubtitles_user_agent,
            proxy=proxy_url,
        ),
    }


def select_providers(config: TaskConfig, registry: dict[str, ProviderAdapter]) -> list[ProviderAdapter]:
    disabled = set(config.provider_disabled)
    requested = set(config.subtitle_providers or registry.keys())
    ordered_ids = []
    for provider_id in [*config.provider_priority, *config.subtitle_providers, *registry.keys()]:
        if provider_id not in ordered_ids:
            ordered_ids.append(provider_id)
    return [
        registry[provider_id]
        for provider_id in ordered_ids
        if provider_id in requested and provider_id not in disabled and provider_id in registry
    ]


def create_provider_stats(providers: list[ProviderAdapter]) -> dict[str, dict[str, object]]:
    return {
        provider.id: {
            "provider": provider.id,
            "searchCount": 0,
            "hitCount": 0,
            "noMatchCount": 0,
            "errorCount": 0,
            "filteredCount": 0,
            "downloadCount": 0,
            "lastError": "",
            "lastErrorType": "",
        }
        for provider in providers
    }


class SubtitleCollectionOrchestrator:
    def __init__(
        self,
        storage: AppStorage | None = None,
        log: LogCallback | None = None,
        progress: ProgressCallback | None = None,
        request_verification: RequestVerificationCallback | None = None,
        control: CollectionControl | None = None,
    ) -> None:
        self.storage = storage
        self.log = log or (lambda message: None)
        self.progress = progress or (lambda payload: None)
        self.request_verification = request_verification
        self.control = control or CollectionControl()
        # 按字幕源分桶的上次请求时间（search / API download 共用）
        self._last_provider_request_at: dict[str, float] = {}

    # 向 GUI 推送电影/失败/下载实时计数（可附带进度环字段）
    def _emit_live_stats(
        self,
        *,
        movie_count: int,
        failed_count: int,
        download_count: int,
        current: int | None = None,
        total: int | None = None,
        current_movie: str = "",
    ) -> None:
        payload: dict[str, object] = {
            "movieCount": movie_count,
            "failedCount": failed_count,
            "downloadCount": download_count,
        }
        if current is not None:
            payload["current"] = current
            payload["total"] = total if total is not None else 0
            payload["currentMovie"] = current_movie
        self.progress(payload)

    async def run(self, config: TaskConfig) -> dict[str, object]:
        started_at = datetime.now()
        self.control.bind_loop(asyncio.get_running_loop())
        output_root = (config.output_root or Path.cwd() / "output").resolve()
        paths = get_run_paths(output_root, config.year, config.limit, started_at)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        paths.download_dir.mkdir(parents=True, exist_ok=True)
        run_id = self.storage.create_task_run(config.year, config.limit) if self.storage else 0

        registry = create_provider_registry(config)
        providers = select_providers(config, registry)
        provider_stats = create_provider_stats(providers)
        failed_records: list[FailedRecord] = []
        all_candidates: list[SubtitleCandidate] = []
        best_candidates: list[SubtitleCandidate] = []
        download_results: list[DownloadResult] = []
        download_blocked_providers: set[str] = set()
        source_health = await self._get_source_health(providers)
        active_providers = [
            provider
            for provider in providers
            if source_health.get(provider.id, {}).get("enabled")
            and source_health.get(provider.id, {}).get("healthy")
        ]
        state_lock = asyncio.Lock()
        movie_concurrency = max(1, min(4, config.movie_concurrency))
        movie_sem = asyncio.Semaphore(movie_concurrency)
        provider_sems = {provider.id: asyncio.Semaphore(1) for provider in active_providers}
        completed_count = 0
        started_movie_count = 0

        # 在持有 state_lock 时调用，推送当前实时计数快照
        def emit_stats_locked(
            *,
            current: int | None = None,
            current_movie: str = "",
        ) -> None:
            self._emit_live_stats(
                movie_count=started_movie_count,
                failed_count=len(failed_records),
                download_count=len(download_results),
                current=current,
                total=len(movies) if current is not None else None,
                current_movie=current_movie,
            )

        try:
            self.log(
                f"[{datetime.now().strftime('%H:%M:%S')}] 任务开始：{config.year} 年 Top{config.limit}，字幕源 "
                f"{', '.join(provider.id for provider in providers) or '无'}，"
                f"电影并发={movie_concurrency}"
            )
            movies = await self._resolve_movies(config)
            for movie in movies:
                self.storage and self.storage.save_movie(movie)
            self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 电影列表数量：{len(movies)}")

            if not active_providers:
                failed_records.append(
                    FailedRecord(
                        movie=None,
                        movie_name="-",
                        provider="-",
                        error_type=ErrorType.PROVIDER_DISABLED,
                        error="没有启用的字幕源",
                    )
                )
                self._emit_live_stats(
                    movie_count=started_movie_count,
                    failed_count=len(failed_records),
                    download_count=len(download_results),
                )

            # 处理单部电影（受电影并发与每源互斥约束）
            async def process_movie(movie: MovieInfo) -> None:
                nonlocal completed_count, started_movie_count
                # 拿并发名额前检查暂停/中止，避免暂停时占满 semaphore
                if await self.control.wait_if_paused_or_aborted():
                    return
                async with movie_sem:
                    if await self.control.wait_if_paused_or_aborted():
                        return
                    movie_name = movie.display_title
                    self.log(
                        f"[{datetime.now().strftime('%H:%M:%S')}] 采集：{movie_name}"
                    )
                    async with state_lock:
                        started_movie_count += 1
                        emit_stats_locked()
                    movie_download_ok = False
                    any_candidate_found = False

                    for provider in active_providers:
                        async with provider_sems[provider.id]:
                            async with state_lock:
                                blocked = provider.id in download_blocked_providers
                            if blocked:
                                self.log(
                                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                                    f"跳过 {provider.id}（下载额度已受限），尝试下一个字幕源"
                                )
                                continue

                            candidates = await self._collect_movie_candidates(
                                movie=movie,
                                providers=[provider],
                                config=config,
                                stats=provider_stats,
                                failed_records=failed_records,
                                state_lock=state_lock,
                                on_stats=emit_stats_locked,
                            )
                            if not candidates:
                                continue

                            any_candidate_found = True
                            sorted_candidates = sort_candidates(candidates)
                            best = sorted_candidates[0]
                            async with state_lock:
                                best_candidates.append(best)
                                all_candidates.extend(sorted_candidates)
                                if self.storage:
                                    for item in sorted_candidates:
                                        self.storage.save_candidate(item)
                            self.log(
                                f"[{datetime.now().strftime('%H:%M:%S')}] {provider.id} 命中 "
                                f"{len(sorted_candidates)} 条，推荐：{best.provider}/{best.subtitle_title}"
                            )

                            max_download_attempts = 3
                            attempted_downloads = 0
                            for candidate_to_download in sorted_candidates:
                                if attempted_downloads >= max_download_attempts:
                                    break
                                attempted_downloads += 1
                                if attempted_downloads > 1:
                                    self.log(
                                        f"[{datetime.now().strftime('%H:%M:%S')}] "
                                        f"尝试第 {attempted_downloads} 个候选："
                                        f"{candidate_to_download.provider}/"
                                        f"{candidate_to_download.subtitle_title}"
                                    )
                                error_type = await self._download_best(
                                    best=candidate_to_download,
                                    providers=active_providers,
                                    config=config,
                                    paths=paths,
                                    stats=provider_stats,
                                    failed_records=failed_records,
                                    download_results=download_results,
                                    state_lock=state_lock,
                                    on_stats=emit_stats_locked,
                                )
                                if error_type == ErrorType.DOWNLOAD_QUOTA_EXCEEDED:
                                    async with state_lock:
                                        download_blocked_providers.add(candidate_to_download.provider)
                                    self.log(
                                        f"[{datetime.now().strftime('%H:%M:%S')}] "
                                        f"{candidate_to_download.provider} 下载额度受限，"
                                        f"本轮后续下载跳过该来源"
                                    )
                                    break
                                async with state_lock:
                                    downloaded_ok = any(
                                        r.provider_subtitle_id
                                        == candidate_to_download.provider_subtitle_id
                                        for r in download_results
                                    )
                                if downloaded_ok:
                                    movie_download_ok = True
                                    break
                                self.log(
                                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                                    f"候选 {attempted_downloads} 下载失败，尝试下一个候选"
                                )

                            if movie_download_ok:
                                break
                            self.log(
                                f"[{datetime.now().strftime('%H:%M:%S')}] "
                                f"{provider.id} 候选下载均失败，尝试下一个字幕源"
                            )

                    if not any_candidate_found:
                        async with state_lock:
                            failed_records.append(
                                FailedRecord(
                                    movie=movie,
                                    movie_name=movie_name,
                                    provider=",".join(p.id for p in active_providers),
                                    error_type=ErrorType.NO_MATCH,
                                    error="没有找到符合要求的双语 ass/srt 字幕候选",
                                )
                            )
                            emit_stats_locked()
                    elif not movie_download_ok:
                        self.log(
                            f"[{datetime.now().strftime('%H:%M:%S')}] 所有字幕源下载失败：{movie_name}"
                        )

                    async with state_lock:
                        completed_count += 1
                        current = completed_count
                        emit_stats_locked(current=current, current_movie=movie_name)

            if movies and active_providers:
                await asyncio.gather(*(process_movie(movie) for movie in movies))

            run_status = "aborted" if self.control.is_aborted() else "completed"
            result = self._build_result(
                config=config,
                paths=paths,
                started_at=started_at,
                movies=movies,
                all_candidates=all_candidates,
                best_candidates=best_candidates,
                failed_records=failed_records,
                download_results=download_results,
                source_health=source_health,
                provider_stats=provider_stats,
                run_status=run_status,
            )
            self.storage and self.storage.finish_task_run(run_id, run_status, result)
            if run_status == "aborted":
                self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 字幕采集任务已中止")
            else:
                self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 字幕采集任务完成")
            return result
        except Exception as exc:
            result = {
                "year": config.year,
                "limit": config.limit,
                "finishedAt": now_iso(),
                "errorType": classify_exception(exc),
                "error": str(exc),
            }
            self.storage and self.storage.finish_task_run(run_id, "failed", result)
            raise
        finally:
            for provider in providers:
                if hasattr(provider, "cleanup"):
                    try:
                        await provider.cleanup()
                    except Exception:
                        pass

    async def _resolve_movies(self, config: TaskConfig) -> list[MovieInfo]:
        client = TmdbClient(config.tmdb_token)
        return await client.fetch_top_movies(
            config.year,
            config.limit,
            vote_count_min=config.vote_count_min,
            log=self.log,
        )

    async def _get_source_health(self, providers: list[ProviderAdapter]) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for provider in providers:
            try:
                health: ProviderHealth = await provider.health()
                result[provider.id] = health.to_dict()
            except Exception as exc:  # noqa: BLE001
                result[provider.id] = ProviderHealth(
                    provider.id,
                    enabled=True,
                    healthy=False,
                    error_type=classify_exception(exc),
                    message=str(exc),
                ).to_dict()
        return result

    # 按字幕源分桶等待，避免跨源共享同一全局间隔
    async def _respect_rate_limit(self, provider_id: str, interval_ms: int) -> None:
        now = asyncio.get_running_loop().time()
        last_at = self._last_provider_request_at.get(provider_id, 0.0)
        elapsed_ms = (now - last_at) * 1000
        remaining_ms = interval_ms - elapsed_ms
        if last_at and remaining_ms > 0:
            await self.control.interruptible_sleep(remaining_ms / 1000)
        self._last_provider_request_at[provider_id] = asyncio.get_running_loop().time()

    async def _collect_movie_candidates(
        self,
        movie: MovieInfo,
        providers: list[ProviderAdapter],
        config: TaskConfig,
        stats: dict[str, dict[str, object]],
        failed_records: list[FailedRecord],
        state_lock: asyncio.Lock | None = None,
        on_stats: Callable[[], None] | None = None,
    ) -> list[SubtitleCandidate]:
        lock = state_lock or asyncio.Lock()
        valid_candidates: list[SubtitleCandidate] = []
        for provider in providers:
            async with lock:
                provider_stats = stats[provider.id]
                provider_stats["searchCount"] = int(provider_stats["searchCount"]) + 1
            try:
                await self._respect_rate_limit(provider.id, config.request_interval_ms)
                timeout = (
                    config.subhd_search_timeout
                    if provider.id == "subhd"
                    else config.provider_search_timeout
                )
                self.log(
                    f"[{datetime.now().strftime('%H:%M:%S')}] {provider.id}.search.start "
                    f"开始搜索字幕源 provider={provider.id} movie={movie.display_title}"
                )
                raw_candidates = await asyncio.wait_for(
                    provider.search(movie, log=self.log),
                    timeout=timeout,
                )
                provider_valid: list[SubtitleCandidate] = []
                provider_lenient: list[SubtitleCandidate] = []
                local_failed: list[FailedRecord] = []
                filtered_delta = 0
                for candidate in raw_candidates:
                    validation = validate_candidate_metadata(candidate)
                    if validation.valid:
                        candidate.subtitle_format = validation.subtitle_format
                        scored = score_candidate(candidate, movie)
                        if has_movie_identity_match(scored, movie):
                            provider_valid.append(scored)
                        else:
                            filtered_delta += 1
                            local_failed.append(
                                FailedRecord(
                                    movie=movie,
                                    movie_name=movie.display_title,
                                    provider=provider.id,
                                    error_type=ErrorType.NO_MATCH,
                                    error="候选字幕标题与目标电影不匹配",
                                    subtitle_title=candidate.subtitle_title,
                                    provider_subtitle_id=candidate.provider_subtitle_id,
                                )
                            )
                        continue

                    lenient_validation = validate_candidate_metadata(candidate, lenient=True)
                    if lenient_validation.valid:
                        candidate.subtitle_format = lenient_validation.subtitle_format
                        scored = score_candidate(candidate, movie)
                        if has_movie_identity_match(scored, movie):
                            provider_lenient.append(scored)
                        else:
                            filtered_delta += 1
                            local_failed.append(
                                FailedRecord(
                                    movie=movie,
                                    movie_name=movie.display_title,
                                    provider=provider.id,
                                    error_type=ErrorType.NO_MATCH,
                                    error="候选字幕标题与目标电影不匹配",
                                    subtitle_title=candidate.subtitle_title,
                                    provider_subtitle_id=candidate.provider_subtitle_id,
                                )
                            )
                        continue

                    filtered_delta += 1
                    local_failed.append(
                        FailedRecord(
                            movie=movie,
                            movie_name=movie.display_title,
                            provider=provider.id,
                            error_type=validation.error_type,
                            error=validation.reason,
                            subtitle_title=candidate.subtitle_title,
                            provider_subtitle_id=candidate.provider_subtitle_id,
                        )
                    )

                async with lock:
                    provider_stats = stats[provider.id]
                    provider_stats["filteredCount"] = (
                        int(provider_stats["filteredCount"]) + filtered_delta
                    )
                    failed_records.extend(local_failed)
                    if local_failed and on_stats is not None:
                        on_stats()
                    if provider_valid:
                        provider_stats["hitCount"] = (
                            int(provider_stats["hitCount"]) + len(provider_valid)
                        )
                        valid_candidates.extend(provider_valid)
                        break
                    elif provider_lenient:
                        self.log(
                            f"[{datetime.now().strftime('%H:%M:%S')}] {provider.id} 严格校验无命中，"
                            f"宽松模式命中 {len(provider_lenient)} 条"
                        )
                        provider_stats["hitCount"] = (
                            int(provider_stats["hitCount"]) + len(provider_lenient)
                        )
                        valid_candidates.extend(provider_lenient)
                        break
                    else:
                        provider_stats["noMatchCount"] = int(provider_stats["noMatchCount"]) + 1
                        self.log(
                            f"[{datetime.now().strftime('%H:%M:%S')}] {provider.id} 无匹配字幕"
                        )
            except asyncio.TimeoutError:
                async with lock:
                    provider_stats = stats[provider.id]
                    provider_stats["errorCount"] = int(provider_stats["errorCount"]) + 1
                    provider_stats["lastError"] = f"搜索超时（{timeout}秒）"
                    provider_stats["lastErrorType"] = ErrorType.NETWORK_UNREACHABLE
                    failed_records.append(
                        FailedRecord(
                            movie=movie,
                            movie_name=movie.display_title,
                            provider=provider.id,
                            error_type=ErrorType.NETWORK_UNREACHABLE,
                            error=f"搜索超时（{timeout}秒）",
                        )
                    )
                    if on_stats is not None:
                        on_stats()
                self.log(
                    f"[{datetime.now().strftime('%H:%M:%S')}] {provider.id} 搜索超时（{timeout}秒），"
                    f"尝试下一个字幕源"
                )
            except Exception as exc:  # noqa: BLE001
                error_type = classify_exception(exc)
                error_msg = str(exc) or repr(exc) or error_type
                async with lock:
                    provider_stats = stats[provider.id]
                    provider_stats["errorCount"] = int(provider_stats["errorCount"]) + 1
                    provider_stats["lastError"] = error_msg
                    provider_stats["lastErrorType"] = error_type
                    failed_records.append(
                        FailedRecord(
                            movie=movie,
                            movie_name=movie.display_title,
                            provider=provider.id,
                            error_type=error_type,
                            error=str(exc),
                        )
                    )
                    if on_stats is not None:
                        on_stats()
                self.log(
                    f"[{datetime.now().strftime('%H:%M:%S')}] {provider.id}.search.fail "
                    f"搜索异常 provider={provider.id} movie={movie.display_title} "
                    f"error_type={error_type} error={error_msg}"
                )
        return valid_candidates

    async def _download_best(
        self,
        best: SubtitleCandidate,
        providers: list[ProviderAdapter],
        config: TaskConfig,
        paths: RunPaths,
        stats: dict[str, dict[str, object]],
        failed_records: list[FailedRecord],
        download_results: list[DownloadResult],
        state_lock: asyncio.Lock | None = None,
        on_stats: Callable[[], None] | None = None,
    ) -> str:
        lock = state_lock or asyncio.Lock()
        provider = next((item for item in providers if item.id == best.provider), None)
        if not provider:
            async with lock:
                failed_records.append(
                    FailedRecord(
                        movie=None,
                        movie_name=best.movie_title_zh or best.movie_title,
                        provider=best.provider,
                        error_type=ErrorType.PROVIDER_DISABLED,
                        error="字幕源不可用",
                        subtitle_title=best.subtitle_title,
                        provider_subtitle_id=best.provider_subtitle_id,
                    )
                )
                if on_stats is not None:
                    on_stats()
            return ErrorType.PROVIDER_DISABLED

        max_retries = 2
        for retry in range(max_retries + 1):
            try:
                # API 源每次 download（含重试）前走分桶；SubHD 不分桶
                if best.provider in _DOWNLOAD_RATE_LIMITED_PROVIDERS:
                    await self._respect_rate_limit(best.provider, config.request_interval_ms)
                payloads = await provider.download(
                    best,
                    DownloadContext(
                        request_interval_ms=config.request_interval_ms,
                        request_verification=self.request_verification,
                        log=self.log,
                        captcha_ocr_enabled=config.subhd_captcha_ocr_enabled,
                        captcha_auto_submit_min_confidence=config.subhd_captcha_auto_submit_min_confidence,
                    ),
                )
                base_name = safe_filename(
                    best.movie_title_zh or best.movie_title or best.provider_subtitle_id
                )
                saved_paths = save_downloaded_payloads(
                    payloads,
                    paths.download_dir,
                    base_name,
                    best,
                    min_bilingual_ratio=config.subtitle_min_bilingual_ratio,
                )
                async with lock:
                    stats[best.provider]["downloadCount"] = (
                        int(stats[best.provider]["downloadCount"]) + len(saved_paths)
                    )
                    download_results.append(
                        DownloadResult(
                            provider=best.provider,
                            provider_subtitle_id=best.provider_subtitle_id,
                            subtitle_title=best.subtitle_title,
                            movie_title=best.movie_title_zh or best.movie_title,
                            saved_paths=saved_paths,
                        )
                    )
                    if on_stats is not None:
                        on_stats()
                self.log(
                    f"[{datetime.now().strftime('%H:%M:%S')}] 下载成功："
                    f"{best.provider}/{best.subtitle_title} "
                    f"→ {', '.join(p.name for p in saved_paths)}"
                )
                return ""
            except CollectorError as exc:
                if retry < max_retries and exc.error_type in {
                    ErrorType.NETWORK_UNREACHABLE,
                    ErrorType.RATE_LIMITED,
                    ErrorType.DOWNLOAD_FAILED,
                }:
                    wait_seconds = (retry + 1) * 5
                    self.log(
                        f"[{datetime.now().strftime('%H:%M:%S')}] 下载失败（{exc.error_type}），"
                        f"{wait_seconds}秒后重试 ({retry + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait_seconds)
                    continue
                async with lock:
                    failed_records.append(
                        FailedRecord(
                            movie=None,
                            movie_name=best.movie_title_zh or best.movie_title,
                            provider=best.provider,
                            error_type=classify_exception(exc),
                            error=str(exc),
                            subtitle_title=best.subtitle_title,
                            provider_subtitle_id=best.provider_subtitle_id,
                        )
                    )
                    if on_stats is not None:
                        on_stats()
                self.log(
                    f"[{datetime.now().strftime('%H:%M:%S')}] 下载失败："
                    f"{best.provider}/{best.subtitle_title} - {exc}"
                )
                return classify_exception(exc)
            except Exception as exc:  # noqa: BLE001
                error_type = classify_exception(exc)
                if retry < max_retries and error_type in {
                    ErrorType.NETWORK_UNREACHABLE,
                    ErrorType.RATE_LIMITED,
                    ErrorType.DOWNLOAD_FAILED,
                }:
                    wait_seconds = (retry + 1) * 5
                    self.log(
                        f"[{datetime.now().strftime('%H:%M:%S')}] 下载异常（{error_type}），"
                        f"{wait_seconds}秒后重试 ({retry + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait_seconds)
                    continue
                async with lock:
                    failed_records.append(
                        FailedRecord(
                            movie=None,
                            movie_name=best.movie_title_zh or best.movie_title,
                            provider=best.provider,
                            error_type=error_type,
                            error=str(exc),
                            subtitle_title=best.subtitle_title,
                            provider_subtitle_id=best.provider_subtitle_id,
                        )
                    )
                    if on_stats is not None:
                        on_stats()
                self.log(
                    f"[{datetime.now().strftime('%H:%M:%S')}] 下载异常："
                    f"{best.provider}/{best.subtitle_title} - {exc}"
                )
                return error_type
        return ErrorType.DOWNLOAD_FAILED

    def _build_result(
        self,
        config: TaskConfig,
        paths: RunPaths,
        started_at: datetime,
        movies: list[MovieInfo],
        all_candidates: list[SubtitleCandidate],
        best_candidates: list[SubtitleCandidate],
        failed_records: list[FailedRecord],
        download_results: list[DownloadResult],
        source_health: dict[str, dict[str, object]],
        provider_stats: dict[str, dict[str, object]],
        run_status: str = "completed",
    ) -> dict[str, object]:
        downloadable = []
        for result_index, result in enumerate(download_results, start=1):
            for file_index, path in enumerate(result.saved_paths, start=1):
                downloadable.append(
                    {
                        "key": f"subtitle-{result_index}-{file_index}",
                        "movieTitle": result.movie_title,
                        "provider": result.provider,
                        "providerSubtitleId": result.provider_subtitle_id,
                        "subtitleTitle": result.subtitle_title,
                        "fileName": path.name,
                        "format": path.suffix.lstrip(".").lower(),
                        "size": path.stat().st_size if path.exists() else 0,
                    }
                )

        return {
            "year": config.year,
            "limit": config.limit,
            "movieSource": config.movie_source,
            "provider": ",".join(config.subtitle_providers),
            "providers": config.subtitle_providers,
            "requestIntervalMs": config.request_interval_ms,
            "movieConcurrency": config.movie_concurrency,
            "startedAt": started_at.replace(microsecond=0).isoformat(),
            "finishedAt": now_iso(),
            "runStatus": run_status,
            "movieCount": len(movies),
            "subtitleCount": len(all_candidates),
            "bestCount": len(best_candidates),
            "failedCount": len(failed_records),
            "downloadCount": len(download_results),
            "downloadDir": str(paths.download_dir),
            "sourceHealth": source_health,
            "providerStats": provider_stats,
            "movies": [movie.to_export_dict() for movie in movies],
            "failedRecords": [record.to_export_dict() for record in failed_records],
            "latestRecords": [item.to_export_dict(is_best=True) for item in best_candidates],
            "downloadableSubtitles": downloadable,
            "downloadResults": [result.to_export_dict() for result in download_results],
        }
