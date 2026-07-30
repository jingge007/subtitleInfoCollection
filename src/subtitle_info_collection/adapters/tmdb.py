from __future__ import annotations

import asyncio
import math
from typing import Callable

import httpx

from ..errors import CollectorError, ErrorType
from ..models import MovieInfo

DEFAULT_TMDB_BASE_URLS = ["https://api.tmdb.org/3", "https://api.themoviedb.org/3"]
TMDB_PAGE_SIZE = 20
# 单页中文详情并发上限
_ZH_DETAIL_CONCURRENCY = 8


class TmdbClient:
    def __init__(
        self,
        token: str,
        base_urls: list[str] | None = None,
        timeout: float = 30,
    ) -> None:
        self.token = token
        self.base_urls = [url.rstrip("/") for url in (base_urls or DEFAULT_TMDB_BASE_URLS)]
        self.timeout = timeout

    async def _request_json(self, endpoint: str, params: dict[str, object] | None = None) -> dict:
        if not self.token:
            raise CollectorError("缺少 TMDB_TOKEN", ErrorType.PROVIDER_DISABLED, "tmdb")

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "subtitleInfoCollection/0.1",
        }
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for base_url in self.base_urls:
                try:
                    response = await client.get(f"{base_url}{endpoint}", params=params, headers=headers)
                    response.raise_for_status()
                    return response.json()
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{base_url}: {exc}")
        raise CollectorError("; ".join(errors), ErrorType.NETWORK_UNREACHABLE, "tmdb")

    async def fetch_top_movies(
        self,
        year: int,
        limit: int = 100,
        vote_count_min: int = 500,
        log: Callable[[str], None] | None = None,
    ) -> list[MovieInfo]:
        pages = math.ceil(limit / TMDB_PAGE_SIZE)
        movies: list[MovieInfo] = []
        detail_sem = asyncio.Semaphore(_ZH_DETAIL_CONCURRENCY)

        # 拉取单部电影的中文详情（受并发信号量限制）
        async def fetch_zh_detail(raw: dict) -> dict:
            async with detail_sem:
                try:
                    return await self._request_json(f"/movie/{raw['id']}", {"language": "zh-CN"})
                except Exception as exc:  # noqa: BLE001
                    log and log(f"中文信息获取失败：{raw.get('title') or raw.get('id')} | {exc}")
                    return {}

        for page in range(1, pages + 1):
            log and log(f"获取 TMDb 电影：{year} 第 {page}/{pages} 页")
            payload = await self._request_json(
                "/discover/movie",
                {
                    "language": "en-US",
                    "primary_release_year": year,
                    "sort_by": "vote_average.desc",
                    "vote_count.gte": vote_count_min,
                    "include_adult": "false",
                    "page": page,
                },
            )
            page_results = list(payload.get("results", []))
            zh_payloads = await asyncio.gather(*(fetch_zh_detail(raw) for raw in page_results))
            for raw, zh_payload in zip(page_results, zh_payloads, strict=True):
                movie = MovieInfo.from_tmdb(raw, zh_payload)
                if movie.year == year:
                    movies.append(movie)

        return sorted(
            movies,
            key=lambda item: (item.rating, item.vote_count, item.popularity),
            reverse=True,
        )[:limit]

    async def search_movie(self, query: str, year: int | None = None) -> MovieInfo | None:
        params: dict[str, object] = {
            "language": "en-US",
            "query": query,
            "include_adult": "false",
        }
        if year:
            params["year"] = year
        payload = await self._request_json("/search/movie", params)
        results = payload.get("results") or []
        if not results:
            return None
        raw = sorted(
            results,
            key=lambda item: (item.get("vote_count") or 0, item.get("popularity") or 0),
            reverse=True,
        )[0]
        zh_payload: dict = {}
        try:
            zh_payload = await self._request_json(f"/movie/{raw['id']}", {"language": "zh-CN"})
        except Exception:
            zh_payload = {}
        return MovieInfo.from_tmdb(raw, zh_payload)
