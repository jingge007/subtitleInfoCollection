from __future__ import annotations

import math
from typing import Callable

import httpx

from ..errors import CollectorError, ErrorType
from ..models import MovieInfo

DEFAULT_TMDB_BASE_URLS = ["https://api.tmdb.org/3", "https://api.themoviedb.org/3"]
TMDB_PAGE_SIZE = 20


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

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "subtitleInfoCollection/0.1",
        }

    # 在已复用的 client 上请求 JSON；主域失败时依次尝试备用域
    async def _request_json_with_client(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        params: dict[str, object] | None = None,
    ) -> dict:
        if not self.token:
            raise CollectorError("缺少 TMDB_TOKEN", ErrorType.PROVIDER_DISABLED, "tmdb")
        errors: list[str] = []
        headers = self._headers()
        for base_url in self.base_urls:
            try:
                response = await client.get(f"{base_url}{endpoint}", params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise CollectorError("TMDb 返回非对象 JSON", ErrorType.PARSE_FAILED, "tmdb")
                return payload
            except CollectorError:
                raise
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{base_url}: {exc}")
        raise CollectorError("; ".join(errors), ErrorType.NETWORK_UNREACHABLE, "tmdb")

    async def _request_json(self, endpoint: str, params: dict[str, object] | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            return await self._request_json_with_client(client, endpoint, params)

    # 拉取指定语言的一页 discover 结果
    async def _discover_page(
        self,
        client: httpx.AsyncClient,
        *,
        year: int,
        page: int,
        language: str,
        vote_count_min: int,
    ) -> list[dict]:
        payload = await self._request_json_with_client(
            client,
            "/discover/movie",
            {
                "language": language,
                "primary_release_year": year,
                "sort_by": "vote_average.desc",
                "vote_count.gte": vote_count_min,
                "include_adult": "false",
                "page": page,
            },
        )
        results = payload.get("results") or []
        return [item for item in results if isinstance(item, dict)]

    async def fetch_top_movies(
        self,
        year: int,
        limit: int = 100,
        vote_count_min: int = 500,
        log: Callable[[str], None] | None = None,
    ) -> list[MovieInfo]:
        pages = math.ceil(limit / TMDB_PAGE_SIZE)
        movies: list[MovieInfo] = []

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for page in range(1, pages + 1):
                log and log(f"获取 TMDb 电影：{year} 第 {page}/{pages} 页")
                # en-US / zh-CN 各一页按 id 合并，避免对每部电影再打详情接口
                en_results = await self._discover_page(
                    client,
                    year=year,
                    page=page,
                    language="en-US",
                    vote_count_min=vote_count_min,
                )
                zh_by_id: dict[object, dict] = {}
                try:
                    zh_results = await self._discover_page(
                        client,
                        year=year,
                        page=page,
                        language="zh-CN",
                        vote_count_min=vote_count_min,
                    )
                    for item in zh_results:
                        movie_id = item.get("id")
                        if movie_id is not None:
                            zh_by_id[movie_id] = item
                except Exception as exc:  # noqa: BLE001
                    log and log(f"中文榜单页获取失败：{year} 第 {page}/{pages} 页 | {exc}")

                for raw in en_results:
                    zh_payload = zh_by_id.get(raw.get("id"), {})
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
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            payload = await self._request_json_with_client(client, "/search/movie", params)
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
                zh_payload = await self._request_json_with_client(
                    client, f"/movie/{raw['id']}", {"language": "zh-CN"}
                )
            except Exception:
                zh_payload = {}
            return MovieInfo.from_tmdb(raw, zh_payload)
