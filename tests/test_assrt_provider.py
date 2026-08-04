import httpx
import pytest

from subtitle_info_collection.adapters.assrt import AssrtProvider
from subtitle_info_collection.models import MovieInfo


def movie() -> MovieInfo:
    return MovieInfo(
        movie_id="tmdb-278",
        title="Shawshank",
        original_title="Shawshank",
        title_zh="Shawshank",
        year=1994,
    )


@pytest.mark.asyncio
async def test_assrt_search_retries_connect_error_and_logs_readable_message():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("", request=request)
        return httpx.Response(200, json={"status": 0, "sub": {"subs": []}})

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.search(movie(), log=logs.append)

    assert result == []
    # 首个关键词 ConnectError 重试 2 次后空结果，再试「标题+年份」关键词 1 次
    assert attempts == 4
    assert any("assrt.search.retry" in item and "ConnectError" in item for item in logs)
    assert any("Shawshank 1994" in item for item in logs)
