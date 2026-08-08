import httpx
import pytest

from subtitle_info_collection.adapters.assrt import AssrtProvider
from subtitle_info_collection.errors import CollectorError, ErrorType
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
        fallback_base_urls=[],
    )

    result = await provider.search(movie(), log=logs.append)

    assert result == []
    # 首个关键词 ConnectError 重试 2 次后空结果，再试「标题+年份」关键词 1 次
    assert attempts == 4
    assert any("assrt.search.retry" in item and "ConnectError" in item for item in logs)
    assert any("api.assrt.net" in item or "无法连接" in item for item in logs)
    assert any("Shawshank 1994" in item for item in logs)


@pytest.mark.asyncio
async def test_assrt_connect_error_fails_over_to_makedie_host():
    hosts_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        hosts_seen.append(host)
        if host == "api.assrt.net":
            raise httpx.ConnectError("", request=request)
        return httpx.Response(
            200,
            json={
                "status": 0,
                "sub": {
                    "subs": [
                        {
                            "id": 123456,
                            "native_name": "Shawshank",
                            "videoname": "shawshank",
                            "subtype": "Subrip(srt)",
                            "lang": {"desc": "双语"},
                        }
                    ]
                },
            },
        )

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(handler),
    )
    result = await provider.search(movie(), log=logs.append)

    assert len(result) == 1
    assert result[0].provider_subtitle_id == "123456"
    assert "api.assrt.net" in hosts_seen
    assert "api.makedie.me" in hosts_seen
    assert any("failover" in item or "备用" in item for item in logs)


@pytest.mark.asyncio
async def test_assrt_status_30900_is_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 30900, "error": "you are exceeding request limits"})

    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(handler),
        fallback_base_urls=[],
    )
    with pytest.raises(CollectorError) as exc_info:
        await provider.search(movie())
    assert exc_info.value.error_type == ErrorType.RATE_LIMITED
    assert "配额" in str(exc_info.value)


@pytest.mark.asyncio
async def test_assrt_status_20001_invalid_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 20001, "error": "invalid token"})

    provider = AssrtProvider(
        token="bad",
        request_interval_ms=0,
        transport=httpx.MockTransport(handler),
        fallback_base_urls=[],
    )
    with pytest.raises(CollectorError) as exc_info:
        await provider.search(movie())
    assert exc_info.value.error_type == ErrorType.PROVIDER_DISABLED
    assert "Token" in str(exc_info.value)
