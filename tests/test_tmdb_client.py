from __future__ import annotations

import httpx
import pytest

from subtitle_info_collection.adapters.tmdb import TmdbClient


@pytest.mark.asyncio
async def test_fetch_top_movies_merges_en_and_zh_discover_pages(monkeypatch: pytest.MonkeyPatch):
    request_urls: list[str] = []
    request_languages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_urls.append(str(request.url))
        language = str(request.url.params.get("language", ""))
        request_languages.append(language)
        page = int(request.url.params.get("page", "1"))
        assert page == 1
        if language == "en-US":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": 101,
                            "title": "Howl's Moving Castle",
                            "original_title": "Howl's Moving Castle",
                            "release_date": "2004-11-20",
                            "vote_average": 8.4,
                            "vote_count": 9000,
                            "popularity": 50.0,
                            "overview": "English overview",
                            "poster_path": "/poster.jpg",
                        }
                    ]
                },
            )
        if language == "zh-CN":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": 101,
                            "title": "哈尔的移动城堡",
                            "original_title": "Howl's Moving Castle",
                            "release_date": "2004-11-20",
                            "vote_average": 8.4,
                            "vote_count": 9000,
                            "popularity": 50.0,
                            "overview": "中文简介",
                            "poster_path": "/poster.jpg",
                        }
                    ]
                },
            )
        return httpx.Response(500, json={"error": "unexpected language"})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    client = TmdbClient(token="test-token", base_urls=["https://api.tmdb.org/3"])
    movies = await client.fetch_top_movies(year=2004, limit=1, vote_count_min=100)

    assert len(movies) == 1
    assert movies[0].title == "Howl's Moving Castle"
    assert movies[0].title_zh == "哈尔的移动城堡"
    assert movies[0].overview_zh == "中文简介"
    assert request_languages.count("en-US") == 1
    assert request_languages.count("zh-CN") == 1
    assert all("/movie/" not in url for url in request_urls)
    assert all("/discover/movie" in url for url in request_urls)
