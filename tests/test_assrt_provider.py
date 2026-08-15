import httpx
import pytest

from subtitle_info_collection.adapters.assrt import AssrtProvider
from subtitle_info_collection.adapters.base import DownloadContext
from subtitle_info_collection.errors import CollectorError, ErrorType
from subtitle_info_collection.models import DownloadedPayload, MovieInfo, SubtitleCandidate


def movie() -> MovieInfo:
    return MovieInfo(
        movie_id="tmdb-278",
        title="Shawshank",
        original_title="Shawshank",
        title_zh="Shawshank",
        year=1994,
    )


def bastards_movie() -> MovieInfo:
    return MovieInfo(
        movie_id="tmdb-16869",
        title="Inglourious Basterds",
        original_title="Inglourious Basterds",
        title_zh="无耻混蛋",
        year=2009,
    )


_EMPTY_SEARCH_HTML = "<html><body><div>找到0条匹配</div></body></html>"

_SEARCH_HTML = """
<html><body>
<div class="sublist_box">
  <a href="/xml/sub/628/628615.xml">无耻混蛋</a>
  版本：Inglourious.Basterds.2009.BluRay
  格式： Subrip(srt) 语言：英 简 双语 来源：转载
  下载次数：1981次
</div>
<div class="sublist_box">
  <a href="/xml/sub/700/700001.xml">同名异年</a>
  版本：Some.Remake.2012
  格式： Subrip(srt) 语言：英 简 双语
  下载次数：10次
</div>
<div class="sublist_box">
  <a href="/xml/sub/111/111001.xml">仅繁体</a>
  版本：Only.Trad.2009
  格式： Subrip(srt) 语言：繁
  下载次数：5次
</div>
<div class="sublist_box">
  <a href="/xml/sub/222/222001.xml">仅英文</a>
  版本：Only.Eng.2009
  格式： Subrip(srt) 语言：英
  下载次数：8次
</div>
</body></html>
"""

_DETAIL_HTML = """
<html><body>
<a href="/download/628615/%5B无耻混蛋%5D.Inglourious.Basterds.2009.zip">下载字幕 | 84KB</a>
文件名：[无耻混蛋].Inglourious.Basterds.2009.zip
<a href="/download/628615/-/1/Inglourious.Basterds.2009.srt">Inglourious.Basterds.2009.srt</a>
</body></html>
"""


def _search_hit_payload() -> dict:
    return {
        "status": 0,
        "sub": {
            "action": "search",
            "keyword": "Shawshank",
            "result": "succeed",
            "subs": [
                {
                    "id": 123456,
                    "native_name": "Shawshank",
                    "videoname": "shawshank",
                    "subtype": "Subrip(srt)",
                    "release_site": "人人影视YYeTs",
                    "vote_score": 50,
                    "upload_time": "2015-08-21 22:11:00",
                    "lang": {"desc": "双语"},
                    "filelist": [{"f": "shawshank.srt"}],
                }
            ],
        },
    }


def _is_site_request(request: httpx.Request) -> bool:
    host = (request.url.host or "").lower()
    path = request.url.path or ""
    if host.endswith("assrt.net") and "api." not in host:
        return True
    if path.startswith("/sub/") or path.startswith("/xml/sub/") or path.startswith("/download/"):
        return True
    return False


def _api_fallback_handler(api_handler):
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_site_request(request):
            return httpx.Response(200, text=_EMPTY_SEARCH_HTML)
        return api_handler(request)

    return handler


@pytest.mark.asyncio
async def test_assrt_search_retries_connect_error_and_logs_readable_message(caplog):
    attempts = 0

    def api_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("", request=request)
        return httpx.Response(200, json={"status": 0, "sub": {"subs": []}})

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_base_urls=[],
        fallback_site_urls=[],
        quota_per_minute=0,
    )

    with caplog.at_level("INFO"):
        result = await provider.search(movie(), log=logs.append)

    assert result == []
    assert attempts == 4
    # retry 细节仅写 logger，不刷 GUI
    assert any("assrt.search.retry" in item and "ConnectError" in item for item in caplog.messages)
    assert any("Shawshank 1994" in item for item in logs)
    assert any("assrt.search.empty" in item for item in logs)
    assert all("token=" not in item.lower() or "token=***" in item.lower() for item in logs)


@pytest.mark.asyncio
async def test_assrt_connect_error_fails_over_to_makedie_host():
    hosts_seen: list[str] = []
    schemes_seen: list[str] = []

    def api_handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        hosts_seen.append(host)
        schemes_seen.append(request.url.scheme)
        if host == "api.assrt.net":
            raise httpx.ConnectError("", request=request)
        return httpx.Response(200, json=_search_hit_payload())

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    result = await provider.search(movie(), log=logs.append)

    assert len(result) == 1
    assert result[0].provider_subtitle_id == "123456"
    assert "api.assrt.net" in hosts_seen
    assert "api.makedie.me" in hosts_seen
    first_makedie = next(i for i, host in enumerate(hosts_seen) if host == "api.makedie.me")
    assert all(schemes_seen[i] == "https" for i in range(first_makedie))
    assert any("assrt.search.ok" in item for item in logs)


@pytest.mark.asyncio
async def test_assrt_read_error_fails_over_to_makedie_host(caplog):
    hosts_seen: list[str] = []

    def api_handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        hosts_seen.append(host)
        if host == "api.assrt.net":
            raise httpx.ReadError("", request=request)
        return httpx.Response(200, json=_search_hit_payload())

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    with caplog.at_level("INFO"):
        result = await provider.search(movie(), log=logs.append)

    assert len(result) == 1
    assert result[0].provider_subtitle_id == "123456"
    assert "api.assrt.net" in hosts_seen
    assert "api.makedie.me" in hosts_seen
    assert any("failover" in item and "ReadError" in item for item in caplog.messages)


def test_assrt_api_bases_prefers_fallback_https_before_http():
    provider = AssrtProvider(token="token", fallback_base_urls=None)
    bases = provider._api_bases()
    assert bases[0] == "https://api.assrt.net/v1"
    assert bases[1] == "https://api.makedie.me/v1"
    assert bases[2] == "http://api.makedie.me/v1"
    assert bases[3] == "http://api.assrt.net/v1"
    assert bases.index("http://api.makedie.me/v1") < bases.index("http://api.assrt.net/v1")


@pytest.mark.asyncio
async def test_assrt_ssl_mismatch_and_503_fail_over_to_makedie_http(caplog):
    seen: list[tuple[str, str]] = []

    def api_handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        scheme = request.url.scheme
        seen.append((scheme, host))
        if host == "api.assrt.net" and scheme == "https":
            raise httpx.ConnectError("", request=request)
        if host == "api.makedie.me" and scheme == "https":
            raise httpx.ConnectError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                "Hostname mismatch, certificate is not valid for 'api.makedie.me'.",
                request=request,
            )
        if host == "api.assrt.net" and scheme == "http":
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json=_search_hit_payload())

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    with caplog.at_level("INFO"):
        result = await provider.search(movie(), log=logs.append)

    assert len(result) == 1
    assert ("http", "api.makedie.me") in seen
    assert ("http", "api.assrt.net") not in seen
    assert any("Hostname mismatch" in item or "证书主机名不匹配" in item for item in caplog.messages)
    assert any("failover" in item for item in caplog.messages)
    assert provider._active_base_url == "http://api.makedie.me/v1"


@pytest.mark.asyncio
async def test_assrt_http_503_fails_over_to_next_base(caplog):
    hosts_schemes: list[tuple[str, str]] = []

    def api_handler(request: httpx.Request) -> httpx.Response:
        hosts_schemes.append((request.url.scheme, request.url.host or ""))
        if request.url.scheme == "https":
            raise httpx.ConnectError("tls unavailable", request=request)
        if request.url.host == "api.assrt.net":
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json=_search_hit_payload())

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        base_url="http://api.assrt.net/v1",
        fallback_base_urls=["http://api.makedie.me/v1"],
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    provider._active_base_url = "http://api.assrt.net/v1"
    with caplog.at_level("INFO"):
        result = await provider.search(movie(), log=logs.append)

    assert len(result) == 1
    assert any(scheme == "http" and host == "api.makedie.me" for scheme, host in hosts_schemes)
    assert any("HTTP503" in item or "503" in item for item in caplog.messages)
    assert any("failover" in item for item in caplog.messages)


@pytest.mark.asyncio
async def test_assrt_https_connect_error_falls_back_to_http_same_host(caplog):
    schemes_seen: list[str] = []

    def api_handler(request: httpx.Request) -> httpx.Response:
        schemes_seen.append(request.url.scheme)
        if request.url.scheme == "https":
            raise httpx.ConnectError("", request=request)
        return httpx.Response(200, json=_search_hit_payload())

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_base_urls=[],
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    with caplog.at_level("INFO"):
        result = await provider.search(movie(), log=logs.append)

    assert len(result) == 1
    assert "https" in schemes_seen
    assert "http" in schemes_seen
    assert any("failover" in item and "http://" in item for item in caplog.messages)


@pytest.mark.asyncio
async def test_assrt_custom_transport_is_not_replaced():
    seen = {"used": False}

    def api_handler(request: httpx.Request) -> httpx.Response:
        seen["used"] = True
        return httpx.Response(200, json={"status": 0, "sub": {"subs": []}})

    transport = httpx.MockTransport(_api_fallback_handler(api_handler))
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=transport,
        fallback_base_urls=[],
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    await provider.search(movie())
    assert seen["used"] is True
    assert provider.transport is transport


@pytest.mark.asyncio
async def test_assrt_status_30900_is_rate_limited():
    paths: list[str] = []

    def api_handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/user/quota"):
            return httpx.Response(200, json={"status": 0, "user": {"quota": 0}})
        return httpx.Response(200, json={"status": 30900, "error": "you are exceeding request limits"})

    logs: list[str] = []
    provider = AssrtProvider(
        token="secret-token-value",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_base_urls=[],
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    with pytest.raises(CollectorError) as exc_info:
        await provider.search(movie(), log=logs.append)
    assert exc_info.value.error_type == ErrorType.RATE_LIMITED
    assert "配额" in str(exc_info.value)
    assert "5 次" in str(exc_info.value)
    assert any("assrt.quota.exceeded" in item for item in logs)
    assert all("/user/quota" not in path for path in paths)
    assert all("secret-token-value" not in item for item in logs)


@pytest.mark.asyncio
async def test_assrt_status_20001_invalid_token():
    def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 20001, "error": "invalid token"})

    provider = AssrtProvider(
        token="bad",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_base_urls=[],
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    with pytest.raises(CollectorError) as exc_info:
        await provider.search(movie())
    assert exc_info.value.error_type == ErrorType.PROVIDER_DISABLED
    assert "Token" in str(exc_info.value)


@pytest.mark.asyncio
async def test_assrt_search_logs_official_fields():
    def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_search_hit_payload())

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_base_urls=[],
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    result = await provider.search(movie(), log=logs.append)
    assert len(result) == 1
    assert any("assrt.search.ok" in item and "count=1" in item for item in logs)
    assert any("assrt.search.hit" in item and "id=123456" in item for item in logs)
    assert any("lang=中英双语" in item or "lang=双语" in item for item in logs)


@pytest.mark.asyncio
async def test_assrt_quota_wait_after_local_limit():
    calls = 0

    def api_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": 0, "sub": {"subs": []}})

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_base_urls=[],
        fallback_site_urls=[],
        quota_per_minute=1,
        quota_window_s=0.2,
    )
    await provider.search(movie(), log=logs.append)
    assert any("assrt.quota.wait" in item for item in logs)
    assert calls >= 2


@pytest.mark.asyncio
async def test_assrt_playwright_download_from_detail_page(monkeypatch):
    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        fallback_site_urls=[],
        quota_per_minute=0,
    )

    async def fake_playwright_download(candidate, context, detail_url):
        assert detail_url.endswith("/xml/sub/628/628615.xml")
        provider._emit(
            "assrt.download.ok",
            "ASSRT 下载成功",
            log=context.log,
            id=candidate.provider_subtitle_id,
            size="12",
            file="movie.zip",
            host="2.assrt.net",
        )
        return [
            DownloadedPayload(
                file_name="movie.zip",
                content=b"PK\x03\x04zip-bytes",
                source_url=detail_url,
                content_type="application/zip",
            )
        ]

    monkeypatch.setattr(provider, "_download_via_playwright", fake_playwright_download)
    candidate = SubtitleCandidate(
        provider="assrt",
        provider_subtitle_id="628615",
        movie_id="tmdb-16869",
        movie_title="Inglourious Basterds",
        subtitle_title="无耻混蛋",
        detail_url="https://2.assrt.net/xml/sub/628/628615.xml",
    )
    payloads = await provider.download(candidate, DownloadContext(log=logs.append))
    assert payloads
    assert payloads[0].content.startswith(b"PK")
    assert any("assrt.download.start" in item for item in logs)
    assert any("assrt.download.ok" in item for item in logs)
    assert all("assrt.web.detail.fallback" not in item for item in logs)
    assert all("file0." not in item for item in logs)


def test_assrt_resolve_browser_proxy_uses_configured_proxy():
    provider = AssrtProvider(token="token", proxy="http://127.0.0.1:7890")
    assert provider._resolve_browser_proxy() == "http://127.0.0.1:7890"


def test_assrt_resolve_browser_proxy_reads_windows_system_proxy(monkeypatch):
    provider = AssrtProvider(token="token", proxy=None)
    monkeypatch.setattr(
        AssrtProvider,
        "_read_windows_system_proxy",
        staticmethod(lambda: "http://127.0.0.1:10808"),
    )
    assert provider._resolve_browser_proxy() == "http://127.0.0.1:10808"


@pytest.mark.asyncio
async def test_assrt_playwright_download_failure_raises_network_unreachable(monkeypatch):
    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        fallback_site_urls=[],
        quota_per_minute=0,
    )

    async def fake_fail(_candidate, _context, _detail_url):
        raise CollectorError(
            "打开详情页失败（Error）：interrupted",
            ErrorType.NETWORK_UNREACHABLE,
            provider.id,
        )

    monkeypatch.setattr(provider, "_download_via_playwright", fake_fail)
    candidate = SubtitleCandidate(
        provider="assrt",
        provider_subtitle_id="628615",
        movie_id="tmdb-16869",
        movie_title="Inglourious Basterds",
        subtitle_title="无耻混蛋",
        detail_url="https://2.assrt.net/xml/sub/628/628615.xml",
    )
    with pytest.raises(CollectorError) as exc_info:
        await provider.download(candidate, DownloadContext(log=logs.append))
    assert exc_info.value.error_type == ErrorType.NETWORK_UNREACHABLE
    assert "详情页打开失败" in str(exc_info.value)
    assert any("assrt.download.start" in item for item in logs)
    assert any("assrt.download.fail" in item and "详情页打开失败" in item for item in logs)


def test_assrt_keywords_prefer_original_title_and_year():
    provider = AssrtProvider(token="token")
    info = bastards_movie()
    keywords = provider._keywords(info)
    assert keywords[0] == "Inglourious Basterds 2009"
    assert "无耻混蛋" in keywords
    assert keywords.index("Inglourious Basterds 2009") < keywords.index("无耻混蛋")


def test_assrt_keywords_short_english_prefers_zh_title():
    provider = AssrtProvider(token="token")
    info = MovieInfo(
        movie_id="tmdb-14160",
        title="Up",
        original_title="Up",
        title_zh="飞屋环游记",
        year=2009,
    )
    keywords = provider._keywords(info)
    assert keywords[0] == "飞屋环游记 2009"
    assert keywords.index("飞屋环游记 2009") < keywords.index("Up 2009")


@pytest.mark.asyncio
async def test_assrt_web_search_filters_lang_and_year():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.rstrip("/").endswith("/sub"):
            return httpx.Response(200, text=_SEARCH_HTML)
        return httpx.Response(404, text="no")

    logs: list[str] = []
    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(handler),
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    result = await provider._search_via_web(bastards_movie(), log=logs.append)
    assert [item.provider_subtitle_id for item in result] == ["628615"]
    assert "英" in result[0].language_type or result[0].language_type == "中英双语"
    assert "2009" in result[0].subtitle_title or any("2009" in name for name in result[0].file_names)
    assert any("assrt.web.search.ok" in item for item in logs)
    assert any("assrt.web.year.skip" in item and "700001" in item for item in logs)
    assert any("assrt.web.search.hit" in item and "628615" in item for item in logs)


@pytest.mark.asyncio
async def test_assrt_search_skips_vobsub_and_machine_translate():
    def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": 0,
                "sub": {
                    "action": "search",
                    "keyword": "Shawshank",
                    "result": "succeed",
                    "subs": [
                        {
                            "id": 1,
                            "native_name": "Shawshank",
                            "subtype": "VobSub",
                            "lang": {"desc": "双语", "langlist": {"langdou": True}},
                            "filelist": [{"f": "a.idx"}],
                        },
                        {
                            "id": 2,
                            "native_name": "Shawshank",
                            "subtype": "Subrip(srt)",
                            "vote_machine_translate": True,
                            "lang": {"desc": "双语", "langlist": {"langdou": True}},
                            "filelist": [{"f": "a.srt"}],
                        },
                        {
                            "id": 3,
                            "native_name": "Shawshank",
                            "subtype": "Subrip(srt)",
                            "lang": {
                                "desc": "英 简 双语",
                                "langlist": {"langdou": True, "langchs": True, "langeng": True},
                            },
                            "vote_score": 12,
                            "filelist": [{"f": "shawshank.chs_eng.srt"}],
                        },
                    ],
                },
            },
        )

    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_base_urls=[],
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    result = await provider.search(movie())
    assert [item.provider_subtitle_id for item in result] == ["3"]
    assert result[0].language_type == "中英双语"
    assert result[0].rating == 12


@pytest.mark.asyncio
async def test_assrt_https_connect_error_skips_without_three_retries():
    https_attempts = 0

    def api_handler(request: httpx.Request) -> httpx.Response:
        nonlocal https_attempts
        if request.url.scheme == "https":
            https_attempts += 1
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json=_search_hit_payload())

    provider = AssrtProvider(
        token="token",
        request_interval_ms=0,
        transport=httpx.MockTransport(_api_fallback_handler(api_handler)),
        fallback_base_urls=[],
        fallback_site_urls=[],
        quota_per_minute=0,
    )
    result = await provider.search(movie())
    assert len(result) == 1
    assert https_attempts == 1


def test_assrt_parse_search_and_detail_helpers():
    provider = AssrtProvider(token="token", site_base_url="https://2.assrt.net")
    hits = provider._parse_search_html(_SEARCH_HTML, "https://2.assrt.net")
    assert {item["id"] for item in hits} >= {"628615", "700001", "111001"}
    downloads = provider._parse_detail_downloads(_DETAIL_HTML, "https://2.assrt.net")
    assert downloads
    assert "download/628615" in downloads[0][0]
    assert downloads[0][0].endswith(".zip") or ".zip" in downloads[0][1]
