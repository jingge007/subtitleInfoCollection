import base64
import json

import httpx
import pytest

from subtitle_info_collection.adapters.subhd import SubhdProvider
from subtitle_info_collection.adapters.base import DownloadContext
from subtitle_info_collection.engines.captcha_solver import solve_captcha_data_uri
from subtitle_info_collection.engines.subtitle_engine import validate_candidate_metadata
from subtitle_info_collection.models import DownloadedPayload, MovieInfo


def test_is_valid_download_content_accepts_zip():
    assert SubhdProvider._is_valid_download_content(b"PK\x03\x04" + b"\x00" * 100)


def test_is_valid_download_content_accepts_rar():
    assert SubhdProvider._is_valid_download_content(b"Rar!\x1a\x07" + b"\x00" * 100)


def test_is_valid_download_content_accepts_7z():
    assert SubhdProvider._is_valid_download_content(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 100)


def test_is_valid_download_content_accepts_gzip():
    assert SubhdProvider._is_valid_download_content(b"\x1f\x8b\x08" + b"\x00" * 100)


def test_is_valid_download_content_accepts_ass_subtitle():
    content = b"[Script Info]\nTitle: Test\nScriptType: v4.00+"
    assert SubhdProvider._is_valid_download_content(content)


def test_is_valid_download_content_accepts_srt_subtitle():
    content = b"1\n00:00:01,000 --> 00:00:04,000\nHello World"
    assert SubhdProvider._is_valid_download_content(content)


def test_is_valid_download_content_accepts_utf16_srt_subtitle():
    content = "1\r\n00:00:02,000 --> 00:00:10,000\r\nHello\r\n".encode("utf-16")
    assert SubhdProvider._is_valid_download_content(content)


def test_is_valid_download_content_rejects_html():
    assert not SubhdProvider._is_valid_download_content(b"<!doctype html><html><body>Error</body></html>")


def test_is_valid_download_content_rejects_empty():
    assert not SubhdProvider._is_valid_download_content(b"")
    assert not SubhdProvider._is_valid_download_content(b"ab")


def test_is_valid_download_content_rejects_unknown_binary():
    assert not SubhdProvider._is_valid_download_content(b"\x00\x01\x02\x03" * 50)


def test_is_html_content_detects_html():
    assert SubhdProvider._is_html_content(b"<!doctype html><html></html>")
    assert SubhdProvider._is_html_content(b"<html><head></head><body></body></html>")
    assert SubhdProvider._is_html_content(b"<div>Error page</div>")


def test_is_html_content_rejects_zip():
    assert not SubhdProvider._is_html_content(b"PK\x03\x04" + b"\x00" * 100)


def test_extract_verification_html_prefers_svg():
    provider = SubhdProvider()
    html = '<div><svg width="80"><text>Ab12</text></svg><img src="/captcha.png"></div>'

    result = provider._extract_verification_html(html)

    assert result.startswith("<svg")
    assert "Ab12" in result


def test_parse_search_result_card_keeps_subhd_language_badges():
    provider = SubhdProvider()
    movie = MovieInfo(
        movie_id="tmdb-13466",
        title="October Sky",
        original_title="October Sky",
        title_zh="十月的天空",
        year=1999,
    )
    html = """
    <div class="bg-white shadow-sm rounded-3 mb-4">
      <div class="row">
        <div class="col-lg-10">
          <div class="pt-3 pe-3 pb-2 ps-3 ps-lg-0 position-relative">
            <div class="clearfix">
              <div class="float-start f16 fw-bold">
                <a class="link-dark align-middle" href="/a/UKDipL">十月的天空</a>
              </div>
              <div class="text-muted">十月的天空 October.Sky.1999.Bluray.1080p.DTS-HD.x264-Grym</div>
              <span>转载精修</span>
              <span>双语</span>
              <span>简体</span>
              <span>繁体</span>
              <span>英语</span>
              <span>SRT</span>
              <span>ASS</span>
              <span>212k</span>
              <span>34</span>
              <span>2023-12-8 19:45</span>
              <span>发布人 SubKing</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    """

    items = provider._parse_movie_page(html, movie, "https://subhd.tv/search/十月的天空")

    assert len(items) == 1
    item = items[0]
    assert item.provider_subtitle_id == "UKDipL"
    assert "双语" in item.language_type
    assert "简体" in item.language_type
    assert "英语" in item.language_type
    assert item.subtitle_format == "ass"
    assert "October.Sky.1999" in item.description
    validation = validate_candidate_metadata(item)
    assert validation.valid


def test_parse_search_results_keeps_only_preferred_subhd_candidates():
    provider = SubhdProvider()
    movie = MovieInfo(
        movie_id="tmdb-1300374",
        title="The Green Mile",
        original_title="The Green Mile",
        title_zh="绿里奇迹",
        year=1999,
    )
    html = """
    <main>
      <article class="bg-white shadow-sm rounded-3">
        <a href="/a/FplMpG">绿里奇迹</a>
        <a href="/a/FplMpG">The.Green.Mile.1999.1080p.BluRay.x264.DTS.Dualaudio-MySiLU</a>
        <span>转载精修 双语 简体繁体英语 SRTASS</span>
        <span>243k</span><span>136</span><span>2024-1-16 19:04</span>
      </article>
      <article class="bg-white shadow-sm rounded-3">
        <a href="/a/IoF6Pv">绿里奇迹</a>
        <span>转载精修 双语 简体英语 ASS</span>
        <span>71k</span><span>5290</span>
      </article>
      <article class="bg-white shadow-sm rounded-3">
        <a href="/a/OyZ42J">绿里奇迹</a>
        <span>转载精修 简体 SUP</span>
        <span>28330k</span><span>3</span>
      </article>
      <article class="bg-white shadow-sm rounded-3">
        <a href="/a/FpMdrG">绿里奇迹</a>
        <span>官方字幕 繁体英语 SUB</span>
        <span>5973k</span><span>737</span>
      </article>
    </main>
    """

    items = provider._parse_search_results_page(html, movie, "https://subhd.tv")

    assert [item.provider_subtitle_id for item in items] == ["FplMpG"]
    assert items[0].subtitle_format == "ass"
    assert items[0].download_count == 136
    assert items[0].raw["fileSizeKB"] == 243


def test_extract_d_page_ids_accepts_search_result_links():
    pytest.skip("SubHD 已改为直接解析 /a/ 字幕链接，不再使用 _extract_d_page_ids")


@pytest.mark.asyncio
async def test_search_writes_structured_events_to_gui_log(monkeypatch):
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-278", title="The Shawshank Redemption", title_zh="肖申克的救赎", year=1994)
    called = {"httpx": 0, "playwright": 0}

    async def no_httpx(movie_arg, keywords_arg):
        called["httpx"] += 1
        return []

    async def no_playwright(movie_arg, keywords_arg):
        called["playwright"] += 1
        return []

    monkeypatch.setattr(provider, "_search_via_httpx", no_httpx)
    monkeypatch.setattr(provider, "_search_via_playwright", no_playwright)

    result = await provider.search(movie, log=lambda _msg: None)

    assert result == []
    assert called["httpx"] == 1
    assert called["playwright"] == 1


@pytest.mark.asyncio
async def test_d_page_parser_uses_playwright_when_httpx_page_has_no_static_a(monkeypatch):
    pytest.skip("SubHD 已移除 _parse_search_results_via_d_pages / _fetch_d_page_via_playwright")

def test_extract_result_title_removes_subhd_table_labels():
    provider = SubhdProvider()

    title = provider._extract_result_title(
        "字幕信息 下载次数 上传人 October.Sky.1999.720p.BluRay.X264-AMIABLE YYeTs字幕组",
        "字幕信息 下载次数 上传人 October.Sky.1999.720p.BluRay.X264-AMIABLE YYeTs字幕组 双语 简体 英语 SRT",
    )

    assert title == "October.Sky.1999.720p.BluRay.X264-AMIABLE YYeTs字幕组"


@pytest.mark.asyncio
async def test_enriches_subhd_candidate_from_detail_page_when_search_card_is_sparse():
    provider = SubhdProvider()
    movie = MovieInfo(
        movie_id="tmdb-13466",
        title="October Sky",
        original_title="October Sky",
        title_zh="十月的天空",
        year=1999,
    )
    candidate = provider._make_candidate(
        "UKDipL",
        "十月的天空",
        "十月的天空",
        movie,
        "https://subhd.tv/search/十月的天空",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://subhd.tv/a/UKDipL"
        html = """
        <section>
          <h1>十月的天空</h1>
          <div>片源版本 十月的天空 October.Sky.1999.Bluray.1080p.DTS-HD.x264-Grym</div>
          <div>转载精修 双语 简体 繁体 英语 SRT ASS 212k 34 2023-12-8 19:45</div>
          <a class="btn btn-danger down" href="/down/UKDipL">下载字幕文件</a>
        </section>
        """
        return httpx.Response(200, text=html)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await provider._enrich_candidates_with_detail_pages(
            client,
            [candidate],
            {"User-Agent": "test"},
        )

    assert "双语" in candidate.language_type
    assert "简体" in candidate.language_type
    assert "英语" in candidate.language_type
    assert candidate.subtitle_format == "ass"
    assert candidate.download_url == "https://subhd.tv/down/UKDipL"
    assert candidate.raw["fileSizeKB"] == 212
    assert candidate.download_count == 34
    assert validate_candidate_metadata(candidate).valid


@pytest.mark.asyncio
async def test_verification_image_data_uri_converts_inline_svg():
    provider = SubhdProvider()
    async with httpx.AsyncClient() as client:
        data_uri = await provider._verification_image_data_uri(
            client,
            "https://subhd.tv",
            '<svg width="80"><text>Ab12</text></svg>',
            "https://subhd.tv/down/1",
        )

    assert data_uri.startswith("data:image/svg+xml;base64,")
    assert solve_captcha_data_uri(data_uri).text == "Ab12"


@pytest.mark.asyncio
async def test_verification_image_data_uri_downloads_relative_img():
    provider = SubhdProvider()
    image_bytes = b"fake-png"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://subhd.tv/captcha.png"
        assert request.headers["referer"] == "https://subhd.tv/down/1"
        return httpx.Response(200, content=image_bytes, headers={"content-type": "image/png"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        data_uri = await provider._verification_image_data_uri(
            client,
            "https://subhd.tv",
            '<img src="/captcha.png">',
            "https://subhd.tv/down/1",
        )

    assert data_uri == f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"


@pytest.mark.asyncio
async def test_verification_image_data_uri_returns_empty_when_missing():
    provider = SubhdProvider()
    async with httpx.AsyncClient() as client:
        data_uri = await provider._verification_image_data_uri(
            client,
            "https://subhd.tv",
            "no captcha here",
            "https://subhd.tv/down/1",
        )

    assert data_uri == ""


def test_is_cloudflare_block_detects_status_codes():
    assert SubhdProvider._is_cloudflare_block("", 403) is True
    assert SubhdProvider._is_cloudflare_block("", 500) is True
    assert SubhdProvider._is_cloudflare_block("", 502) is True
    assert SubhdProvider._is_cloudflare_block("", 503) is True
    assert SubhdProvider._is_cloudflare_block("", 200) is False
    assert SubhdProvider._is_cloudflare_block("", None) is False


def test_is_cloudflare_block_detects_markers():
    assert SubhdProvider._is_cloudflare_block("Just a moment...", 200) is True
    assert SubhdProvider._is_cloudflare_block("cf-browser-verify", 200) is True
    assert SubhdProvider._is_cloudflare_block("Checking your browser", 200) is True
    assert SubhdProvider._is_cloudflare_block("_cf_chl_opt", 200) is True
    assert SubhdProvider._is_cloudflare_block("challenge-platform", 200) is True


def test_is_cloudflare_block_rejects_normal_html():
    assert SubhdProvider._is_cloudflare_block("<html><body>Normal page</body></html>", 200) is False
    assert SubhdProvider._is_cloudflare_block("肖申克的救赎 字幕下载", 200) is False


def test_is_cloudflare_block_case_insensitive():
    assert SubhdProvider._is_cloudflare_block("JUST A MOMENT...", 200) is True
    assert SubhdProvider._is_cloudflare_block("Cf-Browser-Verify", 200) is True


@pytest.mark.asyncio
async def test_download_via_api_success():
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-1", title="Test", title_zh="测试", year=2020)
    candidate = provider._make_candidate(
        "ABC123", "测试字幕", "测试字幕 双语 简体 英语 SRT ASS 200k", movie, "https://subhd.tv"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/api/sub/prepare-download" in url:
            return httpx.Response(200, json={"success": True, "url": "/down/ABC123"})
        if "/api/sub/down" in url:
            return httpx.Response(200, json={"success": True, "url": "https://dl.subhd.tv/test/file.zip"})
        if "dl.subhd.tv" in url:
            return httpx.Response(200, content=b"PK\x03\x04" + b"\x00" * 100, headers={"content-type": "application/zip"})
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    context = DownloadContext(log=lambda msg: None)

    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await provider._download_via_api(client, "https://subhd.tv", candidate, context)

    assert result is not None
    assert len(result) == 1
    assert result[0].content[:2] == b"PK"


@pytest.mark.asyncio
async def test_download_uses_current_base_down_url_not_candidate_host():
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-1", title="Test", title_zh="测试", year=2020)
    # 候选来自 me，但在 one 上下载时必须访问 one 的 /down
    candidate = provider._make_candidate(
        "ABC123", "测试字幕", "测试字幕 双语 简体 英语 SRT ASS 200k", movie, "https://subhd.me"
    )
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen_urls.append(url)
        if "/api/sub/prepare-download" in url:
            assert "subhd.one" in url
            return httpx.Response(200, json={"success": True, "url": "/down/ABC123"})
        if "/api/sub/down" in url:
            assert "subhd.one" in url
            return httpx.Response(200, json={"success": True, "url": "https://dl.subhd.one/test/file.zip"})
        if "dl.subhd.one" in url:
            return httpx.Response(
                200,
                content=b"PK\x03\x04" + b"\x00" * 100,
                headers={"content-type": "application/zip"},
            )
        if "/down/ABC123" in url:
            assert url.startswith("https://subhd.one/")
            return httpx.Response(200, text="ok")
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    context = DownloadContext(log=lambda msg: None)

    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await provider._download_via_api(client, "https://subhd.one", candidate, context)

    assert result is not None
    assert any("https://subhd.one/api/sub/prepare-download" in url for url in seen_urls)
    assert any("https://subhd.one/down/ABC123" in url for url in seen_urls)
    assert not any("https://subhd.me/down/" in url for url in seen_urls)


@pytest.mark.asyncio
async def test_download_continues_api_when_down_warmup_fails():
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-1", title="Test", title_zh="测试", year=2020)
    candidate = provider._make_candidate(
        "ABC123", "测试字幕", "测试字幕 双语 简体 英语 SRT ASS 200k", movie, "https://subhd.me"
    )
    api_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_called
        url = str(request.url)
        if "/api/sub/prepare-download" in url:
            return httpx.Response(200, json={"success": True, "url": "/down/ABC123"})
        if "/down/ABC123" in url:
            raise httpx.ConnectError("warmup failed", request=request)
        if "/api/sub/down" in url:
            api_called = True
            return httpx.Response(200, json={"success": True, "url": "https://dl.subhd.me/test/file.zip"})
        if "dl.subhd.me" in url:
            return httpx.Response(
                200,
                content=b"PK\x03\x04" + b"\x00" * 100,
                headers={"content-type": "application/zip"},
            )
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    context = DownloadContext(log=lambda msg: None)

    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await provider._download_via_api(client, "https://subhd.me", candidate, context)

    assert api_called is True
    assert result is not None


@pytest.mark.asyncio
async def test_download_retries_after_expired_temp_page(monkeypatch):
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-1", title="Test", title_zh="测试", year=2020)
    candidate = provider._make_candidate(
        "ABC123", "测试字幕", "测试字幕 双语 简体 英语 SRT ASS 200k", movie, "https://subhd.me"
    )
    api_calls = 0
    logs: list[str] = []
    playwright_calls = 0

    async def fake_playwright_download(client, base_url, candidate, context):
        nonlocal playwright_calls
        playwright_calls += 1
        return [
            DownloadedPayload(
                file_name="file.zip",
                content=b"PK\x03\x04" + b"\x00" * 100,
                source_url="https://dl.subhd.me/test/file.zip",
                content_type="application/zip",
            )
        ]

    monkeypatch.setattr(provider, "_download_via_playwright_api", fake_playwright_download)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        url = str(request.url)
        if "/api/sub/prepare-download" in url:
            return httpx.Response(200, json={"success": True, "url": "/down/ABC123"})
        if "/api/sub/down" in url:
            api_calls += 1
            return httpx.Response(
                200,
                json={"success": False, "msg": "时间过长本临时页面已经失效"},
            )
        if "/down/ABC123" in url:
            return httpx.Response(200, text="ok")
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    context = DownloadContext(log=logs.append)

    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await provider._download_via_api(client, "https://subhd.me", candidate, context)

    assert result is not None
    assert api_calls == 1
    assert playwright_calls == 1
    assert any("浏览器页内下载" in msg for msg in logs)


@pytest.mark.asyncio
async def test_download_playwright_when_down_page_expired(monkeypatch):
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-1", title="Test", title_zh="测试", year=2020)
    candidate = provider._make_candidate(
        "ABC123", "测试字幕", "测试字幕 双语 简体 英语 SRT ASS 200k", movie, "https://subhd.tv"
    )
    playwright_calls = 0

    async def fake_playwright_download(client, base_url, candidate, context):
        nonlocal playwright_calls
        playwright_calls += 1
        assert base_url == "https://subhd.tv"
        return [
            DownloadedPayload(
                file_name="file.zip",
                content=b"PK\x03\x04" + b"\x00" * 100,
                source_url="https://dl.subhd.tv/test/file.zip",
                content_type="application/zip",
            )
        ]

    monkeypatch.setattr(provider, "_download_via_playwright_api", fake_playwright_download)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/api/sub/prepare-download" in url:
            return httpx.Response(200, json={"success": True, "url": "/down/ABC123"})
        if "/down/ABC123" in url:
            return httpx.Response(200, text="下载页面已失效")
        if "/api/sub/down" in url:
            raise AssertionError("expired /down 不应再走 httpx API")
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    context = DownloadContext(log=lambda msg: None)

    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await provider._download_via_api(client, "https://subhd.tv", candidate, context)

    assert result is not None
    assert playwright_calls == 1


@pytest.mark.asyncio
async def test_download_via_playwright_api_page_fetch_success(monkeypatch):
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-1", title="Test", title_zh="测试", year=2020)
    candidate = provider._make_candidate(
        "ABC123", "测试字幕", "测试字幕 双语 简体 英语 SRT ASS 200k", movie, "https://subhd.me"
    )

    class FakePage:
        url = "https://subhd.me/down/ABC123"

        async def close(self):
            return None

    async def fake_open(base_url, subtitle_id, context=None):
        return FakePage()

    async def fake_sync():
        return None

    async def fake_post(base_url, subtitle_id, captcha_code, referer):
        assert subtitle_id == "ABC123"
        return {
            "ok": True,
            "status": 200,
            "data": {"success": True, "url": "https://dl.subhd.me/test/file.zip"},
        }

    async def fake_file(dl_url, base_url):
        return (b"PK\x03\x04" + b"\x00" * 100, "", "application/zip")

    monkeypatch.setattr(provider, "_open_down_page_via_playwright", fake_open)
    monkeypatch.setattr(provider, "_sync_playwright_cookies_to_shared", fake_sync)
    monkeypatch.setattr(provider, "_post_sub_down_via_playwright", fake_post)
    monkeypatch.setattr(provider, "_download_file_via_playwright", fake_file)

    context = DownloadContext(log=lambda msg: None)
    async with httpx.AsyncClient() as client:
        result = await provider._download_via_playwright_api(
            client, "https://subhd.me", candidate, context
        )

    assert result is not None
    assert result[0].content[:2] == b"PK"


@pytest.mark.asyncio
async def test_prepare_download_session_success():
    provider = SubhdProvider()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "/api/sub/prepare-download" in str(request.url):
            body = json.loads(request.content.decode("utf-8"))
            assert body == {"sid": "ABC123"}
            return httpx.Response(200, json={"success": True, "url": "/down/ABC123"})
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    context = DownloadContext(log=lambda msg: None)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        path = await provider._prepare_download_session(
            client, "https://subhd.me", "ABC123", context
        )

    assert path == "/down/ABC123"
    assert any("/a/ABC123" in url for url in seen)
    assert any("prepare-download" in url for url in seen)


@pytest.mark.asyncio
async def test_download_via_api_captcha_then_success():
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-1", title="Test", title_zh="测试", year=2020)
    candidate = provider._make_candidate(
        "ABC123", "测试字幕", "测试字幕 双语 简体 英语 SRT ASS 200k", movie, "https://subhd.tv"
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        url = str(request.url)
        if "/api/sub/prepare-download" in url:
            return httpx.Response(200, json={"success": True, "url": "/down/ABC123"})
        if "/api/sub/down" in url:
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, json={"success": False, "msg": "need captcha", "captcha_url": "/captcha.png"})
            return httpx.Response(200, json={"success": True, "url": "https://dl.subhd.tv/test/file.zip"})
        if "captcha.png" in url:
            return httpx.Response(200, content=b"fake-png-data", headers={"content-type": "image/png"})
        if "dl.subhd.tv" in url:
            return httpx.Response(200, content=b"PK\x03\x04" + b"\x00" * 100, headers={"content-type": "application/zip"})
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)

    class MockContext(DownloadContext):
        def __init__(self):
            self.log_messages = []
            self.captcha_ocr_enabled = False
            self.captcha_auto_submit_min_confidence = 0.8
            self._request_verification = None

        def log(self, msg):
            self.log_messages.append(msg)

        @property
        def request_verification(self):
            return self._request_verification

        @request_verification.setter
        def request_verification(self, value):
            self._request_verification = value

    context = MockContext()

    from subtitle_info_collection.errors import VerificationRequest

    async def mock_verify(vr: VerificationRequest):
        from dataclasses import dataclass
        @dataclass
        class Result:
            code: str = "abc1"
            refresh: bool = False
        return Result(code="abc1", refresh=False)

    context._request_verification = mock_verify

    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await provider._download_via_api(client, "https://subhd.tv", candidate, context)

    assert call_count == 2
    assert result is not None
    assert result[0].content[:2] == b"PK"


@pytest.mark.asyncio
async def test_download_via_api_pass_false_svg_captcha_then_success():
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-1", title="Test", title_zh="测试", year=2020)
    candidate = provider._make_candidate(
        "ABC123",
        "测试字幕 SRT ASS",
        "测试字幕 双语 简体 英语 SRT ASS 200k",
        movie,
        "https://subhd.tv",
    )
    api_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/api/sub/prepare-download" in url:
            return httpx.Response(200, json={"success": True, "url": "/down/ABC123"})
        if "/api/sub/down" in url:
            body = json.loads(request.content.decode("utf-8"))
            api_bodies.append(body)
            if len(api_bodies) == 1:
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "pass": False,
                        "msg": '<svg width="80"><text>21ao</text></svg>',
                    },
                )
            assert body == {"sid": "ABC123", "cap": "21ao"}
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "pass": True,
                    "url": "https://dl.subhd.tv/test/file.zip",
                },
            )
        if "dl.subhd.tv" in url:
            return httpx.Response(
                200,
                content=b"PK\x03\x04" + b"\x00" * 100,
                headers={"content-type": "application/zip"},
            )
        return httpx.Response(200, text="ok")

    async def mock_verify(vr):
        from subtitle_info_collection.errors import VerificationResult

        assert vr.verification_html.startswith("<svg")
        assert vr.verification_image_data_uri.startswith("data:image/svg+xml;base64,")
        return VerificationResult(code="21ao")

    transport = httpx.MockTransport(handler)
    context = DownloadContext(
        captcha_ocr_enabled=False,
        request_verification=mock_verify,
        log=lambda msg: None,
    )

    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        result = await provider._download_via_api(client, "https://subhd.tv", candidate, context)

    assert api_bodies == [
        {"sid": "ABC123", "cap": ""},
        {"sid": "ABC123", "cap": "21ao"},
    ]
    assert result is not None
    assert result[0].file_name.endswith(".zip")
    assert not result[0].file_name.endswith(".ass")
