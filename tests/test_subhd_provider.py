import base64

import httpx
import pytest

from subtitle_info_collection.adapters.subhd import SubhdProvider
from subtitle_info_collection.engines.captcha_solver import solve_captcha_data_uri


def test_extract_verification_html_prefers_svg():
    provider = SubhdProvider()
    html = '<div><svg width="80"><text>Ab12</text></svg><img src="/captcha.png"></div>'

    result = provider._extract_verification_html(html)

    assert result.startswith("<svg")
    assert "Ab12" in result


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
