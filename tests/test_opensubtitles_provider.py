import httpx
import pytest

from subtitle_info_collection.adapters.opensubtitles import OpenSubtitlesProvider
from subtitle_info_collection.errors import CollectorError, ErrorType
from subtitle_info_collection.models import MovieInfo


def test_search_params_prefers_tmdb_id_over_ambiguous_query():
    provider = OpenSubtitlesProvider(api_key="key")
    movie = MovieInfo(
        movie_id="tmdb-1",
        tmdb_id=12345,
        title="The Deep End of the Ocean",
        title_zh="海洋深处",
        year=1999,
    )

    params = provider._search_params(movie)

    assert params["tmdb_id"] == 12345
    assert "query" not in params
    assert "year" not in params


def test_download_406_is_reported_as_quota_exceeded():
    provider = OpenSubtitlesProvider(api_key="key")
    request = httpx.Request("POST", "https://api.opensubtitles.com/api/v1/download")
    response = httpx.Response(
        406,
        json={"message": "Daily limit quota exceeded"},
        request=request,
    )

    with pytest.raises(CollectorError) as exc_info:
        provider._raise_for_status(response, "download")

    assert exc_info.value.error_type == ErrorType.DOWNLOAD_QUOTA_EXCEEDED
    assert "406" in str(exc_info.value)
    assert "Daily limit quota exceeded" in str(exc_info.value)
