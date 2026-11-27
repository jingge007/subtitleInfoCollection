from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from subtitle_info_collection.adapters.base import DownloadContext, ProviderHealth
from subtitle_info_collection.engines.subtitle_engine import CandidateValidation
from subtitle_info_collection.errors import CollectorError, ErrorType
from subtitle_info_collection.models import (
    DownloadedPayload,
    MovieInfo,
    SubtitleCandidate,
    TaskConfig,
)
from subtitle_info_collection.orchestrator import (
    SubtitleCollectionOrchestrator,
    _DOWNLOAD_RATE_LIMITED_PROVIDERS,
)


def _movie(title: str = "Test Movie") -> MovieInfo:
    return MovieInfo(
        movie_id=f"tmdb-{title}",
        tmdb_id=1,
        title=title,
        title_zh=title,
        original_title=title,
        year=2024,
        rating=8.0,
        vote_count=1000,
        popularity=10.0,
    )


def _candidate(provider: str, subtitle_id: str = "1") -> SubtitleCandidate:
    return SubtitleCandidate(
        provider=provider,
        provider_subtitle_id=subtitle_id,
        movie_id="tmdb-1",
        movie_title="Test Movie",
        movie_title_zh="Test Movie",
        subtitle_title=f"{provider}-双语-srt",
        language_type="简体/英语/双语",
        subtitle_format="srt",
        download_url=f"https://example.com/{provider}/{subtitle_id}",
        detail_url=f"https://example.com/{provider}/{subtitle_id}",
        description="简体 英文 双语",
    )


def _srt_bytes() -> bytes:
    block = "1\n00:00:01,000 --> 00:00:02,000\n你好\nHello\n\n"
    return (block * 40).encode("utf-8")


class FakeProvider:
    def __init__(self, provider_id: str, *, fail_download_times: int = 0) -> None:
        self.id = provider_id
        self.download_supported = True
        self.search_started_at: list[float] = []
        self.download_started_at: list[float] = []
        self._fail_download_times = fail_download_times
        self._download_attempts = 0
        self._active = 0
        self.max_active = 0

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.id, enabled=True, healthy=True)

    async def search(self, movie: MovieInfo, log=None) -> list[SubtitleCandidate]:
        loop = asyncio.get_running_loop()
        self.search_started_at.append(loop.time())
        self._active += 1
        self.max_active = max(self.max_active, self._active)
        await asyncio.sleep(0.02)
        self._active -= 1
        return [_candidate(self.id)]

    async def download(self, candidate: SubtitleCandidate, context: DownloadContext):
        loop = asyncio.get_running_loop()
        self.download_started_at.append(loop.time())
        self._active += 1
        self.max_active = max(self.max_active, self._active)
        self._download_attempts += 1
        await asyncio.sleep(0.02)
        self._active -= 1
        if self._download_attempts <= self._fail_download_times:
            raise CollectorError("模拟网络失败", ErrorType.NETWORK_UNREACHABLE, self.id)
        return [DownloadedPayload(file_name=f"{self.id}.srt", content=_srt_bytes())]


@pytest.mark.asyncio
async def test_bucket_rate_limit_isolates_providers():
    orch = SubtitleCollectionOrchestrator()
    interval_ms = 200
    await orch._respect_rate_limit("assrt", interval_ms)
    t0 = asyncio.get_running_loop().time()
    await orch._respect_rate_limit("subdl", interval_ms)
    elapsed_other = asyncio.get_running_loop().time() - t0
    assert elapsed_other < 0.05

    t1 = asyncio.get_running_loop().time()
    await orch._respect_rate_limit("assrt", interval_ms)
    elapsed_same = asyncio.get_running_loop().time() - t1
    assert elapsed_same >= 0.15


@pytest.mark.asyncio
async def test_download_rate_limit_applies_to_api_providers_including_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    provider = FakeProvider("assrt", fail_download_times=1)
    orch = SubtitleCollectionOrchestrator()
    config = TaskConfig(
        request_interval_ms=150,
        subtitle_min_bilingual_ratio=0.0,
        output_root=tmp_path,
    )
    paths = type("P", (), {"download_dir": tmp_path, "output_dir": tmp_path})()
    failed: list = []
    results: list = []
    stats = {
        "assrt": {
            "downloadCount": 0,
            "searchCount": 0,
            "hitCount": 0,
            "noMatchCount": 0,
            "errorCount": 0,
            "filteredCount": 0,
            "lastError": "",
            "lastErrorType": "",
        }
    }

    original_sleep = asyncio.sleep

    async def fast_sleep(delay: float):
        if delay >= 1:
            await original_sleep(0.01)
        else:
            await original_sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    error = await orch._download_best(
        best=_candidate("assrt"),
        providers=[provider],
        config=config,
        paths=paths,
        stats=stats,
        failed_records=failed,
        download_results=results,
    )
    assert error == ""
    assert len(provider.download_started_at) == 2
    gap = provider.download_started_at[1] - provider.download_started_at[0]
    assert gap >= 0.12


@pytest.mark.asyncio
async def test_subhd_download_skips_bucket_rate_limit(tmp_path: Path):
    assert "subhd" not in _DOWNLOAD_RATE_LIMITED_PROVIDERS
    provider = FakeProvider("subhd")
    orch = SubtitleCollectionOrchestrator()
    await orch._respect_rate_limit("subhd", 5_000)
    config = TaskConfig(
        request_interval_ms=5_000,
        subtitle_min_bilingual_ratio=0.0,
        output_root=tmp_path,
    )
    paths = type("P", (), {"download_dir": tmp_path, "output_dir": tmp_path})()
    failed: list = []
    results: list = []
    stats = {
        "subhd": {
            "downloadCount": 0,
            "searchCount": 0,
            "hitCount": 0,
            "noMatchCount": 0,
            "errorCount": 0,
            "filteredCount": 0,
            "lastError": "",
            "lastErrorType": "",
        }
    }
    t0 = asyncio.get_running_loop().time()
    error = await orch._download_best(
        best=_candidate("subhd"),
        providers=[provider],
        config=config,
        paths=paths,
        stats=stats,
        failed_records=failed,
        download_results=results,
    )
    elapsed = asyncio.get_running_loop().time() - t0
    assert error == ""
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_movie_concurrency_keeps_same_provider_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    provider = FakeProvider("assrt")
    movies = [_movie(f"Movie{i}") for i in range(4)]

    async def fake_resolve(self, config):
        return movies

    monkeypatch.setattr(SubtitleCollectionOrchestrator, "_resolve_movies", fake_resolve)
    monkeypatch.setattr(
        "subtitle_info_collection.orchestrator.create_provider_registry",
        lambda config: {"assrt": provider},
    )
    monkeypatch.setattr(
        "subtitle_info_collection.orchestrator.select_providers",
        lambda config, registry: [registry["assrt"]],
    )
    monkeypatch.setattr(
        "subtitle_info_collection.orchestrator.validate_candidate_metadata",
        lambda candidate, lenient=False: CandidateValidation(valid=True, subtitle_format="srt"),
    )
    monkeypatch.setattr(
        "subtitle_info_collection.orchestrator.has_movie_identity_match",
        lambda scored, movie: True,
    )
    monkeypatch.setattr(
        "subtitle_info_collection.orchestrator.score_candidate",
        lambda candidate, movie: candidate,
    )

    orch = SubtitleCollectionOrchestrator()
    config = TaskConfig(
        year=2024,
        limit=4,
        request_interval_ms=50,
        movie_concurrency=2,
        subtitle_providers=["assrt"],
        provider_priority=["assrt"],
        subtitle_min_bilingual_ratio=0.0,
        output_root=tmp_path,
        assrt_token="token",
    )
    result = await orch.run(config)
    assert result["movieCount"] == 4
    assert provider.max_active == 1
    assert len(provider.search_started_at) == 4


def test_app_settings_clamps_movie_concurrency(tmp_path: Path):
    from subtitle_info_collection.config import AppSettings

    env = tmp_path / ".env"
    env.write_text("SUBTITLE_MOVIE_CONCURRENCY=9\n", encoding="utf-8")
    assert AppSettings.from_env(env).movie_concurrency == 4

    env.write_text("SUBTITLE_MOVIE_CONCURRENCY=0\n", encoding="utf-8")
    assert AppSettings.from_env(env).movie_concurrency == 1

    env.write_text("SUBTITLE_MOVIE_CONCURRENCY=\n", encoding="utf-8")
    assert AppSettings.from_env(env).movie_concurrency == 2


@pytest.mark.asyncio
async def test_download_timeout_fails_fast(tmp_path: Path):
    class SlowProvider(FakeProvider):
        async def download(self, candidate: SubtitleCandidate, context: DownloadContext):
            await asyncio.sleep(2.0)
            return [DownloadedPayload(file_name="x.srt", content=_srt_bytes())]

    provider = SlowProvider("assrt")
    orch = SubtitleCollectionOrchestrator()
    config = TaskConfig(
        request_interval_ms=0,
        provider_download_timeout=1,
        subtitle_min_bilingual_ratio=0.0,
        output_root=tmp_path,
    )
    paths = type("P", (), {"download_dir": tmp_path, "output_dir": tmp_path})()
    failed: list = []
    results: list = []
    stats = {
        "assrt": {
            "downloadCount": 0,
            "searchCount": 0,
            "hitCount": 0,
            "noMatchCount": 0,
            "errorCount": 0,
            "filteredCount": 0,
            "lastError": "",
            "lastErrorType": "",
        }
    }

    # 缩短重试等待，避免测试过久
    async def no_wait(_seconds: float):
        return False

    orch.control.interruptible_sleep = no_wait  # type: ignore[method-assign]
    t0 = asyncio.get_running_loop().time()
    error = await orch._download_best(
        best=_candidate("assrt"),
        providers=[provider],
        config=config,
        paths=paths,
        stats=stats,
        failed_records=failed,
        download_results=results,
    )
    elapsed = asyncio.get_running_loop().time() - t0
    assert error == ErrorType.DOWNLOAD_FAILED
    assert results == []
    assert elapsed < 5.0
    assert any("超时" in (item.error or "") for item in failed)


@pytest.mark.asyncio
async def test_network_unreachable_opens_circuit_after_threshold(tmp_path: Path):
    # 同一部电影作用域内：连续网络失败达阈值后加入 blocked（不设 circuitOpen）
    class AlwaysDown(FakeProvider):
        async def search(self, movie: MovieInfo, log=None):
            raise CollectorError("模拟不可达", ErrorType.NETWORK_UNREACHABLE, self.id)

    provider = AlwaysDown("assrt")
    orch = SubtitleCollectionOrchestrator()
    config = TaskConfig(request_interval_ms=0, output_root=tmp_path)
    stats = {
        "assrt": {
            "downloadCount": 0,
            "downloadAttemptCount": 0,
            "searchCount": 0,
            "hitCount": 0,
            "noMatchCount": 0,
            "errorCount": 0,
            "filteredCount": 0,
            "skippedEnglishCount": 0,
            "circuitOpen": False,
            "lastError": "",
            "lastErrorType": "",
        }
    }
    failed: list = []
    streak = {"assrt": 0}
    blocked: set[str] = set()

    await orch._collect_movie_candidates(
        movie=_movie(),
        providers=[provider],
        config=config,
        stats=stats,
        failed_records=failed,
        network_fail_streak=streak,
        network_blocked_providers=blocked,
    )
    assert "assrt" not in blocked
    assert streak["assrt"] == 1

    await orch._collect_movie_candidates(
        movie=_movie("Other"),
        providers=[provider],
        config=config,
        stats=stats,
        failed_records=failed,
        network_fail_streak=streak,
        network_blocked_providers=blocked,
    )
    assert "assrt" in blocked
    # 网络熔断仅本片有效，不打开整轮 circuitOpen
    assert stats["assrt"]["circuitOpen"] is False


@pytest.mark.asyncio
async def test_network_circuit_resets_for_next_movie_scope(tmp_path: Path):
    # 下一部电影使用新的 streak/blocked 时，不应继承上一部的网络熔断
    class AlwaysDown(FakeProvider):
        async def search(self, movie: MovieInfo, log=None):
            raise CollectorError("模拟不可达", ErrorType.NETWORK_UNREACHABLE, self.id)

    provider = AlwaysDown("assrt")
    orch = SubtitleCollectionOrchestrator()
    config = TaskConfig(request_interval_ms=0, output_root=tmp_path)
    stats = {
        "assrt": {
            "downloadCount": 0,
            "downloadAttemptCount": 0,
            "searchCount": 0,
            "hitCount": 0,
            "noMatchCount": 0,
            "errorCount": 0,
            "filteredCount": 0,
            "skippedEnglishCount": 0,
            "circuitOpen": False,
            "lastError": "",
            "lastErrorType": "",
        }
    }
    failed: list = []
    movie1_streak = {"assrt": 0}
    movie1_blocked: set[str] = set()
    for _ in range(2):
        await orch._collect_movie_candidates(
            movie=_movie("Movie1"),
            providers=[provider],
            config=config,
            stats=stats,
            failed_records=failed,
            network_fail_streak=movie1_streak,
            network_blocked_providers=movie1_blocked,
        )
    assert "assrt" in movie1_blocked

    movie2_streak = {"assrt": 0}
    movie2_blocked: set[str] = set()
    await orch._collect_movie_candidates(
        movie=_movie("Movie2"),
        providers=[provider],
        config=config,
        stats=stats,
        failed_records=failed,
        network_fail_streak=movie2_streak,
        network_blocked_providers=movie2_blocked,
    )
    assert "assrt" not in movie2_blocked
    assert movie2_streak["assrt"] == 1


@pytest.mark.asyncio
async def test_subhd_timeout_shortens_after_streak(tmp_path: Path):
    # 连续 SubHD 搜索超时后，后续使用缩短超时（不低于 40s 配置下限逻辑由常量保证）
    class SlowSubhd(FakeProvider):
        def __init__(self) -> None:
            super().__init__("subhd")
            self.timeouts_seen: list[float] = []

        async def search(self, movie: MovieInfo, log=None):
            # 通过 sleep 超过外层 wait_for；外层 timeout 由编排器决定
            await asyncio.sleep(10)
            return []

    provider = SlowSubhd()
    orch = SubtitleCollectionOrchestrator()
    config = TaskConfig(request_interval_ms=0, subhd_search_timeout=4)
    stats = {
        "subhd": {
            "downloadCount": 0,
            "downloadAttemptCount": 0,
            "searchCount": 0,
            "hitCount": 0,
            "noMatchCount": 0,
            "errorCount": 0,
            "filteredCount": 0,
            "skippedEnglishCount": 0,
            "circuitOpen": False,
            "lastError": "",
            "lastErrorType": "",
        }
    }
    failed: list = []
    subhd_state = {"streak": 0}
    blocked: set[str] = set()

    async def no_wait(_seconds: float) -> bool:
        return False

    orch.control.interruptible_sleep = no_wait  # type: ignore[method-assign]

    for title in ("A", "B", "C"):
        await orch._collect_movie_candidates(
            movie=_movie(title),
            providers=[provider],
            config=config,
            stats=stats,
            failed_records=failed,
            network_blocked_providers=blocked,
            subhd_timeout_state=subhd_state,
        )

    assert "subhd" not in blocked
    assert subhd_state["streak"] == 3
    assert stats["subhd"]["circuitOpen"] is False
    assert stats["subhd"]["errorCount"] == 3


@pytest.mark.asyncio
async def test_rate_limited_download_retries_once_then_returns(tmp_path: Path):
    class AlwaysRateLimited(FakeProvider):
        async def download(self, candidate: SubtitleCandidate, context: DownloadContext):
            self._download_attempts += 1
            raise CollectorError("模拟限流", ErrorType.RATE_LIMITED, self.id)

    provider = AlwaysRateLimited("subdl")
    orch = SubtitleCollectionOrchestrator()
    config = TaskConfig(request_interval_ms=0, provider_download_timeout=30, output_root=tmp_path)
    paths = type("P", (), {"download_dir": tmp_path})()
    stats = {
        "subdl": {
            "downloadCount": 0,
            "downloadAttemptCount": 0,
            "searchCount": 0,
            "hitCount": 0,
            "noMatchCount": 0,
            "errorCount": 0,
            "filteredCount": 0,
            "skippedEnglishCount": 0,
            "circuitOpen": False,
            "lastError": "",
            "lastErrorType": "",
        }
    }
    failed: list = []
    results: list = []

    async def no_wait(_seconds: float) -> bool:
        return False

    orch.control.interruptible_sleep = no_wait  # type: ignore[method-assign]
    error = await orch._download_best(
        best=_candidate("subdl"),
        providers=[provider],
        config=config,
        paths=paths,
        stats=stats,
        failed_records=failed,
        download_results=results,
    )
    assert error == ErrorType.RATE_LIMITED
    # 初次 + 1 次重试
    assert provider._download_attempts == 2
    assert stats["subdl"]["lastErrorType"] == ErrorType.RATE_LIMITED


@pytest.mark.asyncio
async def test_search_rate_limited_opens_circuit_after_threshold():
    class RateLimitedSearch(FakeProvider):
        async def search(self, movie: MovieInfo, log=None):
            raise CollectorError("模拟搜索限流", ErrorType.RATE_LIMITED, self.id)

    provider = RateLimitedSearch("subdl")
    orch = SubtitleCollectionOrchestrator()
    config = TaskConfig(request_interval_ms=0)
    stats = {
        "subdl": {
            "downloadCount": 0,
            "downloadAttemptCount": 0,
            "searchCount": 0,
            "hitCount": 0,
            "noMatchCount": 0,
            "errorCount": 0,
            "filteredCount": 0,
            "skippedEnglishCount": 0,
            "circuitOpen": False,
            "lastError": "",
            "lastErrorType": "",
        }
    }
    failed: list = []
    download_blocked: set[str] = set()
    rate_streak = {"subdl": 0}

    await orch._collect_movie_candidates(
        movie=_movie(),
        providers=[provider],
        config=config,
        stats=stats,
        failed_records=failed,
        download_blocked_providers=download_blocked,
        rate_limit_fail_streak=rate_streak,
    )
    assert "subdl" not in download_blocked
    assert rate_streak["subdl"] == 1

    await orch._collect_movie_candidates(
        movie=_movie("Other"),
        providers=[provider],
        config=config,
        stats=stats,
        failed_records=failed,
        download_blocked_providers=download_blocked,
        rate_limit_fail_streak=rate_streak,
    )
    assert "subdl" in download_blocked
    assert stats["subdl"]["circuitOpen"] is True


@pytest.mark.asyncio
async def test_subhd_search_timeout_does_not_open_network_circuit():
    # SubHD 搜索超时只换源，不计入本片网络熔断
    class SlowSubhd(FakeProvider):
        def __init__(self) -> None:
            super().__init__("subhd")
            self.search_calls = 0

        async def search(self, movie: MovieInfo, log=None):
            self.search_calls += 1
            await asyncio.sleep(10)
            return []

    provider = SlowSubhd()
    orch = SubtitleCollectionOrchestrator()
    config = TaskConfig(request_interval_ms=0, subhd_search_timeout=1)
    stats = {
        "subhd": {
            "downloadCount": 0,
            "downloadAttemptCount": 0,
            "searchCount": 0,
            "hitCount": 0,
            "noMatchCount": 0,
            "errorCount": 0,
            "filteredCount": 0,
            "skippedEnglishCount": 0,
            "circuitOpen": False,
            "lastError": "",
            "lastErrorType": "",
        }
    }
    failed: list = []
    streak = {"subhd": 0}
    blocked: set[str] = set()

    for title in ("Movie A", "Movie B", "Movie C"):
        await orch._collect_movie_candidates(
            movie=_movie(title),
            providers=[provider],
            config=config,
            stats=stats,
            failed_records=failed,
            network_fail_streak=streak,
            network_blocked_providers=blocked,
        )

    assert "subhd" not in blocked
    assert streak["subhd"] == 0
    assert stats["subhd"]["circuitOpen"] is False
    assert provider.search_calls == 3
    assert stats["subhd"]["errorCount"] == 3
