import base64

import httpx
import pytest

from subtitle_info_collection.adapters.subhd import SubhdProvider
from subtitle_info_collection.engines.captcha_solver import solve_captcha_data_uri
from subtitle_info_collection.engines.subtitle_engine import validate_candidate_metadata
from subtitle_info_collection.models import MovieInfo


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
