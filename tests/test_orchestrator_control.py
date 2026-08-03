from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from subtitle_info_collection.adapters.base import DownloadContext, ProviderHealth
from subtitle_info_collection.engines.subtitle_engine import CandidateValidation
from subtitle_info_collection.models import (
    DownloadedPayload,
    MovieInfo,
    SubtitleCandidate,
    TaskConfig,
)
from subtitle_info_collection.orchestrator import (
    CollectionControl,
    SubtitleCollectionOrchestrator,
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


class ControllableProvider:
    def __init__(self, provider_id: str = "assrt") -> None:
        self.id = provider_id
        self.download_supported = True
        self.search_titles: list[str] = []
        self._gate = asyncio.Event()
        self._gate.set()
        self._started = asyncio.Event()

    # 阻塞后续 search，便于测试暂停窗口
    def hold(self) -> None:
        self._gate.clear()

    # 放开 search 阻塞
    def release(self) -> None:
        self._gate.set()

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.id, enabled=True, healthy=True)

    async def search(self, movie: MovieInfo, log=None) -> list[SubtitleCandidate]:
        self.search_titles.append(movie.title)
        self._started.set()
        await self._gate.wait()
        await asyncio.sleep(0.02)
        return [_candidate(self.id, subtitle_id=movie.title)]

    async def download(self, candidate: SubtitleCandidate, context: DownloadContext):
        return [DownloadedPayload(file_name=f"{self.id}.srt", content=_srt_bytes())]


def _patch_orch(monkeypatch: pytest.MonkeyPatch, movies: list[MovieInfo], provider: ControllableProvider):
    async def fake_resolve(self, config):
        return movies

    monkeypatch.setattr(SubtitleCollectionOrchestrator, "_resolve_movies", fake_resolve)
    monkeypatch.setattr(
        "subtitle_info_collection.orchestrator.create_provider_registry",
        lambda config: {provider.id: provider},
    )
    monkeypatch.setattr(
        "subtitle_info_collection.orchestrator.select_providers",
        lambda config, registry: [registry[provider.id]],
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


def _config(tmp_path: Path, limit: int = 3) -> TaskConfig:
    return TaskConfig(
        year=2024,
        limit=limit,
        request_interval_ms=0,
        movie_concurrency=1,
        subtitle_providers=["assrt"],
        provider_priority=["assrt"],
        subtitle_min_bilingual_ratio=0.0,
        output_root=tmp_path,
        assrt_token="token",
    )


@pytest.mark.asyncio
async def test_pause_blocks_next_movie_until_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    movies = [_movie("MovieA"), _movie("MovieB"), _movie("MovieC")]
    provider = ControllableProvider()
    control = CollectionControl()
    _patch_orch(monkeypatch, movies, provider)

    orch = SubtitleCollectionOrchestrator(control=control)
    task = asyncio.create_task(orch.run(_config(tmp_path)))

    await asyncio.wait_for(provider._started.wait(), timeout=2)
    provider.hold()
    control.pause()
    await asyncio.sleep(0.05)
    provider.release()
    await asyncio.sleep(0.15)
    assert provider.search_titles == ["MovieA"]

    control.resume()
    result = await asyncio.wait_for(task, timeout=5)
    assert result["runStatus"] == "completed"
    assert provider.search_titles == ["MovieA", "MovieB", "MovieC"]
    assert result["downloadCount"] == 3


@pytest.mark.asyncio
async def test_abort_skips_remaining_movies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    movies = [_movie("MovieA"), _movie("MovieB"), _movie("MovieC")]
    provider = ControllableProvider()
    control = CollectionControl()
    _patch_orch(monkeypatch, movies, provider)

    orch = SubtitleCollectionOrchestrator(control=control)
    task = asyncio.create_task(orch.run(_config(tmp_path)))

    await asyncio.wait_for(provider._started.wait(), timeout=2)
    provider.hold()
    control.abort()
    provider.release()
    result = await asyncio.wait_for(task, timeout=5)

    assert result["runStatus"] == "aborted"
    assert provider.search_titles == ["MovieA"]
    assert result["downloadCount"] == 1
    assert result["movieCount"] == 3


@pytest.mark.asyncio
async def test_live_stats_increment_on_movie_start_and_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    movies = [_movie("MovieA"), _movie("MovieB"), _movie("MovieC")]
    provider = ControllableProvider()
    _patch_orch(monkeypatch, movies, provider)
    progress_payloads: list[dict] = []

    orch = SubtitleCollectionOrchestrator(progress=progress_payloads.append)
    result = await orch.run(_config(tmp_path))

    assert result["runStatus"] == "completed"
    assert result["downloadCount"] == 3
    movie_counts = [
        int(p["movieCount"])
        for p in progress_payloads
        if "movieCount" in p
    ]
    download_counts = [
        int(p["downloadCount"])
        for p in progress_payloads
        if "downloadCount" in p
    ]
    # 电影按「采集：」开始逐步 +1，不应一次跳到总数
    assert movie_counts
    assert movie_counts[0] == 1
    assert max(movie_counts) == 3
    assert sorted(set(movie_counts)) == [1, 2, 3]
    assert download_counts
    assert max(download_counts) == 3
    assert 1 in download_counts


@pytest.mark.asyncio
async def test_collection_control_interruptible_sleep_stops_on_abort():
    control = CollectionControl()
    control.bind_loop(asyncio.get_running_loop())
    t0 = asyncio.get_running_loop().time()
    sleeper = asyncio.create_task(control.interruptible_sleep(2.0))
    await asyncio.sleep(0.05)
    control.abort()
    await asyncio.wait_for(sleeper, timeout=1)
    elapsed = asyncio.get_running_loop().time() - t0
    assert elapsed < 1.0
