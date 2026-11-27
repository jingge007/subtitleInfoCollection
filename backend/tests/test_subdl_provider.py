import httpx
import pytest

from subtitle_info_collection.adapters.base import DownloadContext
from subtitle_info_collection.adapters.subdl import SubdlProvider
from subtitle_info_collection.engines.subtitle_engine import validate_candidate_metadata
from subtitle_info_collection.errors import CollectorError, ErrorType
from subtitle_info_collection.models import MovieInfo, SubtitleCandidate


def movie() -> MovieInfo:
    return MovieInfo(
        movie_id="tmdb-27205",
        tmdb_id=27205,
        title="Inception",
        original_title="Inception",
        title_zh="盗梦空间",
        year=2010,
    )


@pytest.mark.asyncio
async def test_health_requires_api_key():
    health = await SubdlProvider(api_key="").health()

    assert health.enabled is False
    assert health.error_type == ErrorType.PROVIDER_DISABLED


def test_default_search_params_use_zh_and_tmdb_id():
    provider = SubdlProvider(api_key="key")

    params = provider._search_params(movie())

    assert params["tmdb_id"] == 27205
    assert params["languages"] == "ZH"
    assert params["type"] == "movie"
    assert params["subs_per_page"] == 30
    assert "film_name" not in params


def test_traditional_language_is_opt_in():
    provider = SubdlProvider(api_key="key", languages="ZH,EN,ZH_BG")
    assert provider._effective_languages() == "ZH,EN"

    provider = SubdlProvider(
        api_key="key",
        languages="ZH,EN",
        include_traditional=True,
    )
    assert provider._effective_languages() == "ZH,EN,ZH_BG"


def test_map_item_keeps_zh_en_as_candidate_not_bilingual_truth():
    provider = SubdlProvider(api_key="key")
    candidate = provider._map_item(
        {
            "url": "/subtitle/3197651-3213944.zip",
            "lang": "ZH",
            "release_name": "Inception.2010.1080p.srt",
            "comment": "Chinese subtitle",
        },
        movie(),
    )

    assert candidate.provider == "subdl"
    assert candidate.provider_subtitle_id == "3197651-3213944"
    assert candidate.download_url == "https://dl.subdl.com/subtitle/3197651-3213944.zip"
    assert validate_candidate_metadata(candidate).valid is False


def test_map_item_bilingual_marker_can_enter_existing_validation():
    provider = SubdlProvider(api_key="key")
    candidate = provider._map_item(
        {
            "url": "/subtitle/3197651-3213944.zip",
            "lang": "ZH",
            "release_name": "Inception.2010.1080p.chs&eng.srt",
            "comment": "bilingual",
        },
        movie(),
    )

    assert validate_candidate_metadata(candidate).valid is True


@pytest.mark.asyncio
async def test_download_429_daily_limit_is_quota_exceeded(monkeypatch):
    provider = SubdlProvider(api_key="key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("api_key") == "key"
        assert request.headers.get("x-api-key") == "key"
        return httpx.Response(
            429,
            json={"error": "daily_limit", "message": "Daily download limit exceeded"},
        )

    candidate = SubtitleCandidate(
        provider="subdl",
        provider_subtitle_id="3197651-3213944",
        movie_id="tmdb-27205",
        movie_title="Inception",
        subtitle_title="demo",
        download_url="https://dl.subdl.com/subtitle/3197651-3213944.zip",
    )
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs.pop("proxy", None)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    with pytest.raises(CollectorError) as exc_info:
        await provider.download(candidate, DownloadContext())
    assert exc_info.value.error_type == ErrorType.DOWNLOAD_QUOTA_EXCEEDED
    assert "每日下载额度" in str(exc_info.value)


@pytest.mark.asyncio
async def test_search_429_rate_limit(monkeypatch):
    provider = SubdlProvider(api_key="key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate_limit", "message": "slow down"})

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs.pop("proxy", None)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    with pytest.raises(CollectorError) as exc_info:
        await provider.search(movie())
    assert exc_info.value.error_type == ErrorType.RATE_LIMITED
    assert "频率" in str(exc_info.value)
