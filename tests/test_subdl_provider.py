import pytest

from subtitle_info_collection.adapters.subdl import SubdlProvider
from subtitle_info_collection.engines.subtitle_engine import validate_candidate_metadata
from subtitle_info_collection.errors import ErrorType
from subtitle_info_collection.models import MovieInfo


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


def test_default_search_params_use_zh_en_and_tmdb_id():
    provider = SubdlProvider(api_key="key")

    params = provider._search_params(movie())

    assert params["tmdb_id"] == 27205
    assert params["languages"] == "ZH,EN"
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
