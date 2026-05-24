import base64
import base64
import json

import httpx
import pytest

from subtitle_info_collection.adapters.subhd import SubhdProvider
from subtitle_info_collection.adapters.base import DownloadContext
from subtitle_info_collection.engines.captcha_solver import solve_captcha_data_uri
from subtitle_info_collection.engines.subtitle_engine import validate_candidate_metadata
from subtitle_info_collection.models import MovieInfo


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
    provider = SubhdProvider()
    html = """
    <a href="/d/12345">电影详情</a>
    <a href='/d/abcDEF'>动态详情</a>
    <a class="x" href="/d/12345?from=search">重复详情</a>
    <a href="/a/ABCD12">字幕详情</a>
    """

    assert provider._extract_d_page_ids(html) == ["12345", "abcDEF"]


@pytest.mark.asyncio
async def test_search_writes_structured_events_to_gui_log(monkeypatch):
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-278", title="The Shawshank Redemption", title_zh="肖申克的救赎", year=1994)
    logs: list[str] = []

    async def no_httpx(movie_arg, keywords_arg):
        return []

    async def no_playwright(movie_arg, keywords_arg):
        return []

    monkeypatch.setattr(provider, "_search_via_httpx", no_httpx)
    monkeypatch.setattr(provider, "_search_via_playwright", no_playwright)

    result = await provider.search(movie, log=logs.append)

    assert result == []
    assert any("subhd.search.start" in item and "开始搜索" in item for item in logs)
    assert any("subhd.search.done" in item and "候选总数=0" in item for item in logs)


@pytest.mark.asyncio
async def test_d_page_parser_uses_playwright_when_httpx_page_has_no_static_a(monkeypatch):
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-13466", title="October Sky", title_zh="十月的天空", year=1999)

    class Client:
        async def get(self, url):
            return httpx.Response(200, text="<html><body>字幕列表由 JS 动态加载</body></html>")

    async def rendered_page(base_url: str, d_id: str) -> str:
        assert d_id == "777"
        return """
        <article class="bg-white shadow-sm rounded-3">
          <a href="/a/UKDipL">十月的天空 October.Sky.1999.Bluray.1080p.DTS-HD.x264-Grym</a>
          <span>转载精修 双语 简体 英语 SRT ASS 212k 34</span>
        </article>
        """

    monkeypatch.setattr(provider, "_fetch_d_page_via_playwright", rendered_page)

    items = await provider._parse_search_results_via_d_pages(
        Client(),
        ["777"],
        movie,
        ["十月的天空"],
        "https://subhd.tv",
    )

    assert [item.provider_subtitle_id for item in items] == ["UKDipL"]


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
        if "/api/sub/down" in str(request.url):
            return httpx.Response(200, json={"success": True, "url": "https://dl.subhd.tv/test/file.zip"})
        if "dl.subhd.tv" in str(request.url):
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
async def test_download_via_api_captcha_then_success():
    provider = SubhdProvider()
    movie = MovieInfo(movie_id="tmdb-1", title="Test", title_zh="测试", year=2020)
    candidate = provider._make_candidate(
        "ABC123", "测试字幕", "测试字幕 双语 简体 英语 SRT ASS 200k", movie, "https://subhd.tv"
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        if "/api/sub/down" in str(request.url):
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, json={"success": False, "msg": "need captcha", "captcha_url": "/captcha.png"})
            return httpx.Response(200, json={"success": True, "url": "https://dl.subhd.tv/test/file.zip"})
        if "captcha.png" in str(request.url):
            return httpx.Response(200, content=b"fake-png-data", headers={"content-type": "image/png"})
        if "dl.subhd.tv" in str(request.url):
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
        if "/api/sub/down" in str(request.url):
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
        if "dl.subhd.tv" in str(request.url):
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
