from __future__ import annotations

import base64
import re
from urllib.parse import quote, urljoin

import httpx

from ..errors import CollectorError, ErrorType, VerificationRequest
from ..engines.captcha_solver import solve_captcha_data_uri
from ..engines.scorer import normalize_text
from ..engines.subtitle_engine import detect_subtitle_format
from ..models import DownloadedPayload, MovieInfo, SubtitleCandidate, format_chinese_description
from .base import DownloadContext, ProviderHealth

DEFAULT_BASE_URLS = ["https://subhd.tv", "https://subhd.cc", "https://subhd.me", "https://subhd.la"]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
)


class SubhdProvider:
    id = "subhd"
    download_supported = True

    def __init__(self, base_urls: list[str] | None = None, timeout: float = 30) -> None:
        self.base_urls = [url.rstrip("/") for url in (base_urls or DEFAULT_BASE_URLS)]
        self.timeout = timeout

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.id, enabled=True, healthy=True)

    def _keywords(self, movie: MovieInfo) -> list[str]:
        values = [movie.title_zh, movie.title, movie.original_title]
        return list(dict.fromkeys([value for value in values if value and len(value.strip()) >= 2]))

    async def search(self, movie: MovieInfo) -> list[SubtitleCandidate]:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/html,*/*"}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for base_url in self.base_urls:
                for keyword in self._keywords(movie):
                    suggest_url = f"{base_url}/searchD/{quote(keyword)}"
                    try:
                        suggest = await client.get(suggest_url, headers=headers)
                        suggest.raise_for_status()
                        movie_pages = self._parse_suggest(suggest.text, base_url)
                        for page in movie_pages:
                            response = await client.get(page["url"], headers=headers)
                            response.raise_for_status()
                            items = self._parse_movie_page(response.text, movie, page["url"])
                            if items:
                                for item in items:
                                    item.description = format_chinese_description(
                                        ("搜索关键词", keyword),
                                        ("字幕信息", item.description),
                                    )
                                return items
                    except Exception:
                        continue
        return await self._search_with_playwright(movie)

    async def _search_with_playwright(self, movie: MovieInfo) -> list[SubtitleCandidate]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return []

        for base_url in self.base_urls:
            for keyword in self._keywords(movie):
                browser = None
                try:
                    async with async_playwright() as playwright:
                        browser = await playwright.chromium.launch(headless=True)
                        page = await browser.new_page(user_agent=USER_AGENT)
                        await page.goto(
                            f"{base_url}/search/{quote(keyword)}",
                            wait_until="networkidle",
                            timeout=30_000,
                        )
                        html_text = await page.content()
                        items = self._parse_movie_page(html_text, movie, base_url)
                        if items:
                            for item in items:
                                item.description = format_chinese_description(
                                    ("搜索关键词", keyword),
                                    ("字幕信息", item.description),
                                )
                            return items
                except Exception:
                    continue
                finally:
                    if browser:
                        await browser.close()
        return []

    def _parse_suggest(self, text: str, base_url: str) -> list[dict[str, str]]:
        try:
            payload = httpx.Response(200, content=text).json()
            html_text = payload.get("text") or ""
        except Exception:
            html_text = text
        result = []
        for match in re.finditer(r'href="(/d/[^"]+)">([\s\S]*?)</a>', html_text):
            result.append(
                {
                    "url": urljoin(base_url, match.group(1)),
                    "title": re.sub(r"<[^>]+>", "", match.group(2)).strip(),
                }
            )
        return result

    def _parse_movie_page(self, html_text: str, movie: MovieInfo, page_url: str) -> list[SubtitleCandidate]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:  # pragma: no cover
            return self._parse_movie_page_regex(html_text, movie, page_url)

        soup = BeautifulSoup(html_text, "html.parser")
        result: list[SubtitleCandidate] = []
        for link in soup.find_all("a", href=re.compile(r"^/a/")):
            subtitle_id = link.get("href", "").split("/a/")[-1].strip("/")
            title = link.get_text(" ", strip=True)
            row = link.find_parent(["div", "li", "tr"]) or link.parent
            text = row.get_text(" ", strip=True) if row else title
            result.append(self._make_candidate(subtitle_id, title, text, movie, page_url))
        return [item for item in result if item.provider_subtitle_id]

    def _parse_movie_page_regex(
        self, html_text: str, movie: MovieInfo, page_url: str
    ) -> list[SubtitleCandidate]:
        result: list[SubtitleCandidate] = []
        for match in re.finditer(r'href="/a/([^"]+)">([\s\S]*?)</a>', html_text):
            start = max(0, match.start() - 600)
            end = min(len(html_text), match.end() + 1000)
            title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            text = re.sub(r"<[^>]+>", " ", html_text[start:end])
            result.append(self._make_candidate(match.group(1), title, text, movie, page_url))
        return result

    def _detect_language_type(self, text: str) -> str:
        labels = []
        if re.search(r"(双语|中英|简英|简繁英|chs.*eng|ze\b)", text, re.I):
            labels.append("双语")
        if re.search(r"(简体|简中|chs|zh[-_ ]?cn|simplified|gb2312|gbk|gb18030)", text, re.I):
            labels.append("简体")
        elif re.search(r"(中文|chinese|zh|chi|zho|cn\b)", text, re.I):
            labels.append("中文")
        if re.search(r"(繁体|繁中|cht|zh[-_ ]?tw|traditional|big5)", text, re.I):
            labels.append("繁体")
        if re.search(r"(英文|英语|英字|english|eng\b|\ben\b)", text, re.I):
            labels.append("英语")
        if not labels:
            if "简" in text:
                labels.append("简体")
            if "英" in text:
                labels.append("英语")
        return "/".join(labels)

    def _make_candidate(
        self,
        subtitle_id: str,
        title: str,
        text: str,
        movie: MovieInfo,
        page_url: str,
    ) -> SubtitleCandidate:
        numbers = [int(value) for value in re.findall(r"\b(\d{1,7})\b", text)]
        return SubtitleCandidate(
            provider=self.id,
            provider_subtitle_id=subtitle_id,
            movie_id=movie.movie_id,
            movie_title=movie.title,
            movie_original_title=movie.original_title,
            movie_title_zh=movie.title_zh,
            movie_year=movie.year,
            subtitle_title=title,
            language_type=self._detect_language_type(text),
            subtitle_format=detect_subtitle_format(text),
            download_count=max(numbers) if numbers else 0,
            detail_url=urljoin(page_url, f"/a/{subtitle_id}"),
            description=format_chinese_description(
                ("字幕标题", title),
                ("页面内容", text),
            ),
            file_names=[title],
        )

    async def download(self, candidate: SubtitleCandidate, context: DownloadContext) -> list[DownloadedPayload]:
        detail_url = candidate.detail_url or f"{self.base_urls[0]}/a/{candidate.provider_subtitle_id}"
        base_url = detail_url.split("/a/")[0]
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            detail = await client.get(detail_url)
            detail.raise_for_status()
            down_url = f"{base_url}/down/{candidate.provider_subtitle_id}"
            down_page = await client.get(down_url, headers={"Referer": detail_url, **headers})
            down_page.raise_for_status()
            sid = self._extract_sid(down_page.text, candidate.provider_subtitle_id)
            if not sid:
                raise CollectorError("未找到 SubHD 下载参数 SID", ErrorType.DOWNLOAD_FAILED, self.id)

            payload = await self._request_download_payload(client, base_url, sid, "", down_url)
            if payload.get("pass") is False:
                code = ""
                code_from_ocr = False
                verification_source = payload.get("msg") or down_page.text
                verification_html = self._extract_verification_html(verification_source)
                verification_image = await self._verification_image_data_uri(
                    client,
                    base_url,
                    verification_html or verification_source,
                    down_url,
                )
                ocr_result = (
                    solve_captcha_data_uri(verification_image)
                    if context.captcha_ocr_enabled and verification_image
                    else None
                )
                if (
                    ocr_result
                    and ocr_result.text
                    and ocr_result.confidence >= context.captcha_auto_submit_min_confidence
                ):
                    code = ocr_result.text
                    code_from_ocr = True
                    if context.log:
                        context.log(
                            f"SubHD captcha OCR auto-submit confidence={ocr_result.confidence:.0%}"
                        )
                elif context.request_verification:
                    code = await context.request_verification(
                        VerificationRequest(
                            provider=self.id,
                            provider_subtitle_id=candidate.provider_subtitle_id,
                            subtitle_title=candidate.subtitle_title,
                            detail_url=detail_url,
                            verification_html=verification_html,
                            verification_image_data_uri=verification_image,
                            suggested_code=ocr_result.text if ocr_result else "",
                            suggested_confidence=ocr_result.confidence if ocr_result else 0.0,
                            ocr_message=ocr_result.message if ocr_result else "",
                        )
                    )
                if not code:
                    raise CollectorError("已取消 SubHD 验证", ErrorType.VERIFICATION_REQUIRED, self.id)
                payload = await self._request_download_payload(client, base_url, sid, code, down_url)
                if payload.get("pass") is False and code_from_ocr and context.request_verification:
                    code = await context.request_verification(
                        VerificationRequest(
                            provider=self.id,
                            provider_subtitle_id=candidate.provider_subtitle_id,
                            subtitle_title=candidate.subtitle_title,
                            detail_url=detail_url,
                            verification_html=verification_html,
                            verification_image_data_uri=verification_image,
                            suggested_code=ocr_result.text if ocr_result else "",
                            suggested_confidence=ocr_result.confidence if ocr_result else 0.0,
                            ocr_message="OCR code was rejected; please enter it manually.",
                        )
                    )
                    if code:
                        payload = await self._request_download_payload(client, base_url, sid, code, down_url)

            if payload.get("success") is False or payload.get("pass") is False or not payload.get("url"):
                raise CollectorError(str(payload.get("msg") or "SubHD 没有返回下载地址"), ErrorType.DOWNLOAD_FAILED, self.id)

            file_url = payload["url"]
            response = await client.get(file_url, headers={"Referer": down_url, "User-Agent": USER_AGENT})
            response.raise_for_status()
            file_name = self._download_file_name(file_url, candidate)
            return [
                DownloadedPayload(
                    file_name=file_name,
                    content=response.content,
                    source_url=file_url,
                    content_type=response.headers.get("content-type", ""),
                )
            ]

    async def _request_download_payload(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        sid: str,
        captcha_code: str,
        referer: str,
    ) -> dict:
        response = await client.post(
            f"{base_url}/api/sub/down",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json,*/*",
                "Referer": referer,
                "User-Agent": USER_AGENT,
            },
            json={"sid": sid, "cap": captcha_code},
        )
        response.raise_for_status()
        return response.json()

    def _extract_sid(self, html_text: str, fallback: str) -> str:
        match = re.search(r'class="[^"]*\bdown\b[^"]*"[^>]*\bsid="([^"]+)"', html_text)
        if not match:
            match = re.search(r'\bsid="([^"]+)"[^>]*class="[^"]*\bdown\b[^"]*"', html_text)
        return match.group(1) if match else fallback

    def _extract_verification_html(self, text: str) -> str:
        svg = re.search(r"<svg[^>]*>[\s\S]*?</svg>", text, re.I)
        if svg:
            return svg.group(0)
        img = re.search(r"<img[^>]+>", text, re.I)
        return img.group(0) if img else text

    def _image_mime_type(self, url: str, fallback: str = "") -> str:
        if fallback and fallback.lower().startswith("image/"):
            return fallback.split(";", 1)[0].strip().lower()
        suffix = url.split("?", 1)[0].rsplit(".", 1)[-1].lower() if "." in url else ""
        if suffix == "svg":
            return "image/svg+xml"
        if suffix in {"jpg", "jpeg"}:
            return "image/jpeg"
        if suffix == "gif":
            return "image/gif"
        return "image/png"

    def _to_data_uri(self, content: bytes, mime_type: str) -> str:
        encoded = base64.b64encode(content).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _extract_image_src(self, html_text: str) -> str:
        match = re.search(r"<img[^>]+\bsrc=[\"']?([^\"'\s>]+)", html_text, re.I)
        return match.group(1) if match else ""

    async def _verification_image_data_uri(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        verification_html: str,
        referer: str,
    ) -> str:
        if not verification_html:
            return ""
        if verification_html.strip().startswith("data:image/"):
            return verification_html.strip()
        svg = re.search(r"<svg[^>]*>[\s\S]*?</svg>", verification_html, re.I)
        if svg:
            return self._to_data_uri(svg.group(0).encode("utf-8"), "image/svg+xml")
        image_src = self._extract_image_src(verification_html)
        if not image_src:
            return ""
        if image_src.startswith("data:image/"):
            return image_src
        image_url = urljoin(base_url, image_src)
        try:
            response = await client.get(
                image_url,
                headers={
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Referer": referer,
                    "User-Agent": USER_AGENT,
                },
            )
            response.raise_for_status()
        except Exception:
            return ""
        return self._to_data_uri(
            response.content,
            self._image_mime_type(image_url, response.headers.get("content-type", "")),
        )

    def _download_file_name(self, url: str, candidate: SubtitleCandidate) -> str:
        suffix = detect_subtitle_format(url) or detect_subtitle_format(candidate.subtitle_title) or "zip"
        title = normalize_text(candidate.movie_title_zh or candidate.movie_title or "subtitle").replace(" ", ".")
        return f"{title}.{suffix}"
