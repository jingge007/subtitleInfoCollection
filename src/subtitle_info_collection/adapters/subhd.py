from __future__ import annotations

import base64
import logging
import re
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

from ..errors import CollectorError, ErrorType
from ..engines.scorer import normalize_text
from ..engines.subtitle_engine import detect_subtitle_format
from ..models import DownloadedPayload, MovieInfo, SubtitleCandidate, format_chinese_description
from .base import DownloadContext, ProviderHealth

DEFAULT_BASE_URLS = ["https://subhd.tv", "https://subhd.cc", "https://subhd.me", "https://subhd.la"]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

AJAX_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "DNT": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

API_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

logger = logging.getLogger(__name__)

_CF_CHALLENGE_MARKERS = [
    "cf-browser-verify",
    "Checking your browser",
    "Please enable JavaScript",
    "just a moment",
    "_cf_chl_opt",
    "cf-turnstile",
]

_CAPTCHA_REFRESH = "__SUBHD_REFRESH_CAPTCHA__"
_MIN_SEARCH_FILE_SIZE_KB = 100.0


def _is_cloudflare_challenge_page(html_text: str) -> bool:
    lower = html_text.lower()
    return any(marker.lower() in lower for marker in _CF_CHALLENGE_MARKERS)


def _stealth_script() -> str:
    return """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
            Promise.resolve({state: Notification.permission}) :
            originalQuery(parameters)
        );
    """


class SubhdProvider:
    id = "subhd"
    download_supported = True

    def __init__(self, base_urls: list[str] | None = None, timeout: float = 30) -> None:
        self.base_urls = [url.rstrip("/") for url in (base_urls or DEFAULT_BASE_URLS)]
        self.timeout = timeout
        self._shared_cookies = httpx.Cookies()
        self._browser = None
        self._browser_context = None
        self._playwright_instance = None

    async def cleanup(self) -> None:
        if self._browser_context:
            try:
                await self._browser_context.close()
            except Exception:
                pass
            self._browser_context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright_instance:
            try:
                await self._playwright_instance.stop()
            except Exception:
                pass
            self._playwright_instance = None

    async def _ensure_browser(self) -> None:
        if self._browser is None or not self._browser.is_connected():
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
            from playwright.async_api import async_playwright
            self._playwright_instance = await async_playwright().start()
            self._browser = await self._playwright_instance.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-infobars",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            self._browser_context = await self._browser.new_context(
                user_agent=USER_AGENT,
                accept_downloads=True,
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.id, enabled=True, healthy=True)

    def _keywords(self, movie: MovieInfo) -> list[str]:
        values = [movie.title_zh, movie.title, movie.original_title]
        return list(dict.fromkeys([value for value in values if value and len(value.strip()) >= 2]))

    async def _navigate_with_challenge_handling(
        self,
        page,
        url: str,
        max_retries: int = 3,
        wait_seconds: int = 5,
    ) -> str | None:
        for attempt in range(max_retries):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as exc:
                logger.info("SubHD navigate failed (attempt %d/%d): %s", attempt + 1, max_retries, exc)
                if attempt < max_retries - 1:
                    await page.wait_for_timeout(wait_seconds * 1000)
                    continue
                return None

            await page.wait_for_timeout(2_000)
            html_text = await page.content()

            if _is_cloudflare_challenge_page(html_text):
                logger.info("SubHD Cloudflare challenge detected (attempt %d/%d), waiting...", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    await page.wait_for_timeout(wait_seconds * 1000)
                    continue
                return None

            return html_text

        return None

    async def search(self, movie: MovieInfo) -> list[SubtitleCandidate]:
        keywords = self._keywords(movie)
        logger.info("SubHD search start, movie=%s, keywords=%s", movie.title_zh or movie.title, keywords)

        result = await self._search_via_httpx(movie, keywords)
        if result:
            logger.info("SubHD httpx fast search hits, candidates=%d", len(result))
            return result

        logger.info("SubHD httpx fast search exhausted or blocked, falling back to Playwright")
        return await self._search_via_playwright(movie, keywords)

    async def _search_via_httpx(self, movie: MovieInfo, keywords: list[str]) -> list[SubtitleCandidate]:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
            headers=BROWSER_HEADERS,
            cookies=self._shared_cookies,
        ) as client:
            for base_url in self.base_urls:
                for keyword in keywords:
                    try:
                        search_url = f"{base_url}/search/{quote(keyword)}"
                        logger.info("SubHD httpx search: %s", search_url)
                        resp = await client.get(search_url)
                        if resp.status_code != 200:
                            logger.info("SubHD httpx search HTTP %d: %s", resp.status_code, search_url)
                            continue
                        html_text = resp.text
                        if _is_cloudflare_challenge_page(html_text):
                            logger.info("SubHD httpx search blocked by Cloudflare: %s", search_url)
                            continue
                        items = self._parse_search_results_page(html_text, movie, base_url)
                        if items:
                            logger.info("SubHD httpx search hits, candidates=%d, keyword=%s", len(items), keyword)
                            await self._enrich_candidates_with_detail_pages(client, items, BROWSER_HEADERS)
                            for item in items:
                                item.description = format_chinese_description(
                                    ("搜索关键词", keyword),
                                    ("字幕信息", item.description),
                                )
                            return items
                        logger.info("SubHD httpx search no match: keyword=%s, base=%s", keyword, base_url)
                    except Exception as exc:
                        logger.info("SubHD httpx search failed: keyword=%s, base=%s, exc=%s", keyword, base_url, exc)
                        continue
        return []

    async def _search_via_playwright(self, movie: MovieInfo, keywords: list[str]) -> list[SubtitleCandidate]:
        try:
            import importlib.util
            if importlib.util.find_spec("playwright") is None:
                logger.info("SubHD Playwright not available, search failed")
                return []
        except ImportError:
            logger.info("SubHD Playwright not available, search failed")
            return []

        try:
            await self._ensure_browser()
        except Exception as exc:
            logger.info("SubHD search: browser init failed: %s", exc)
            return []

        for base_url in self.base_urls:
            for keyword in keywords:
                page = None
                try:
                    page = await self._browser_context.new_page()
                    await page.add_init_script(_stealth_script())
                    search_url = f"{base_url}/search/{quote(keyword)}"
                    logger.info("SubHD Playwright search: %s", search_url)

                    html_text = await self._navigate_with_challenge_handling(
                        page, search_url, max_retries=2, wait_seconds=3
                    )

                    if not html_text:
                        logger.info("SubHD Playwright search: failed to load page, keyword=%s, base=%s", keyword, base_url)
                        continue

                    items = self._parse_search_results_page(html_text, movie, base_url)
                    if items:
                        logger.info(
                            "SubHD Playwright search hits, candidates=%d, keyword=%s",
                            len(items), keyword,
                        )
                        await self._enrich_candidates_with_playwright(page, items)
                        for item in items:
                            item.description = format_chinese_description(
                                ("搜索关键词", keyword),
                                ("字幕信息", item.description),
                            )
                        return items
                    logger.info("SubHD Playwright search no match: keyword=%s, base=%s", keyword, base_url)
                except Exception as exc:
                    logger.info("SubHD Playwright search failed: keyword=%s, base=%s, exc=%s", keyword, base_url, exc)
                    continue
                finally:
                    if page:
                        try:
                            await page.close()
                        except Exception:
                            pass

        logger.info("SubHD Playwright search exhausted, no results")
        return []

    def _parse_search_results_page(self, html_text: str, movie: MovieInfo, base_url: str) -> list[SubtitleCandidate]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html_text, "html.parser")
        result: list[SubtitleCandidate] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=re.compile(r"^/a/")):
            subtitle_id = link.get("href", "").split("/a/")[-1].strip("/")
            if not subtitle_id or subtitle_id in seen:
                continue
            seen.add(subtitle_id)
            text = self._candidate_container_text(link)
            title = self._extract_result_title(link.get_text(" ", strip=True), text)
            result.append(self._make_candidate(subtitle_id, title, text, movie, base_url))
        return [
            item
            for item in result
            if item.provider_subtitle_id and self._is_preferred_search_candidate(item)
        ]

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
        except ImportError:
            return self._parse_movie_page_regex(html_text, movie, page_url)

        soup = BeautifulSoup(html_text, "html.parser")
        result: list[SubtitleCandidate] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=re.compile(r"^/a/")):
            subtitle_id = link.get("href", "").split("/a/")[-1].strip("/")
            if not subtitle_id or subtitle_id in seen:
                continue
            seen.add(subtitle_id)
            text = self._candidate_container_text(link)
            title = self._extract_result_title(link.get_text(" ", strip=True), text)
            result.append(self._make_candidate(subtitle_id, title, text, movie, page_url))
        return [item for item in result if item.provider_subtitle_id]

    def _candidate_container_text(self, link) -> str:
        best_text = link.get_text(" ", strip=True)
        best_key = (-1, -len(best_text))
        node = link
        for _ in range(8):
            if not node:
                break
            text = node.get_text(" ", strip=True)
            if text:
                class_names = " ".join(str(item) for item in (node.get("class") or []))
                score = self._metadata_score(text)
                if re.search(r"(bg-white|shadow|rounded|clearfix|position-relative|row)", class_names):
                    score += 1
                try:
                    subtitle_ids = {
                        str(anchor.get("href", "")).split("/a/")[-1].strip("/")
                        for anchor in node.find_all("a", href=re.compile(r"^/a/"))
                    }
                    subtitle_ids.discard("")
                    if len(subtitle_ids) > 1:
                        score -= 20
                except Exception:
                    pass
                if len(text) > 1200:
                    score -= 2
                key = (score, -len(text))
                if key > best_key:
                    best_key = key
                    best_text = text
            node = getattr(node, "parent", None)
        return best_text

    def _metadata_score(self, text: str) -> int:
        score = 0
        if re.search(r"(双语|中英|简英|简繁英|chs.*eng|zh.*en)", text, re.I):
            score += 4
        if re.search(r"(简体|简中|chs|zh[-_ ]?cn|simplified)", text, re.I):
            score += 3
        if re.search(r"(英语|英文|英字|english|eng\b|\ben\b)", text, re.I):
            score += 3
        if self._detect_subtitle_format(text):
            score += 3
        if re.search(r"(发布人|转载|原创|最后更新|\d+k\b|\d{4}-\d{1,2}-\d{1,2})", text, re.I):
            score += 1
        return score

    def _detect_subtitle_format(self, text: str = "") -> str:
        detected = detect_subtitle_format(text)
        if detected:
            return detected
        normalized = re.sub(r"[^A-Za-z0-9]+", " ", str(text or "")).upper()
        compact = re.sub(r"[^A-Za-z0-9]+", "", str(text or "")).upper()
        tokens = set(normalized.split())
        if "ASS" in tokens or "SRTASS" in compact or "ASSSRT" in compact:
            return "ass"
        if "SRT" in tokens or "SRTSUB" in compact:
            return "srt"
        return ""

    def _parse_file_size_kb(self, text: str = "") -> float:
        sizes: list[float] = []
        for value, unit in re.findall(r"\b(\d+(?:\.\d+)?)\s*([kmg])b?\b", text, re.I):
            number = float(value)
            unit_lower = unit.lower()
            if unit_lower == "m":
                number *= 1024
            elif unit_lower == "g":
                number *= 1024 * 1024
            sizes.append(number)
        return max(sizes) if sizes else 0.0

    def _parse_download_count(self, text: str = "") -> int:
        label_match = re.search(r"下载次数\s*[:：]?\s*(\d{1,7})", text)
        if label_match:
            return int(label_match.group(1))
        size_match = re.search(
            r"\b\d+(?:\.\d+)?\s*[kmg]b?\b\s+[\"“”']?(\d{1,7})[\"“”']?",
            text,
            re.I,
        )
        if size_match:
            return int(size_match.group(1))
        return 0

    def _is_preferred_search_candidate(self, candidate: SubtitleCandidate) -> bool:
        text = candidate.metadata_text()
        file_size_kb = float(candidate.raw.get("fileSizeKB") or 0)
        has_bilingual = bool(re.search(r"(双语|中英|简英|简繁英|chs.*eng|zh.*en)", text, re.I))
        has_simplified = bool(re.search(r"(简体|简中|chs|zh[-_ ]?cn|simplified)", text, re.I))
        has_english = bool(re.search(r"(英文|英语|英字|english|eng\b|\ben\b)", text, re.I))
        return (
            file_size_kb >= _MIN_SEARCH_FILE_SIZE_KB
            and candidate.subtitle_format in {"ass", "srt"}
            and has_bilingual
            and has_simplified
            and has_english
        )

    def _extract_result_title(self, link_title: str, container_text: str) -> str:
        title = self._strip_subhd_title_labels(re.sub(r"\s+", " ", link_title or "").strip())
        text = re.sub(r"\s+", " ", container_text or "").strip()
        if not text:
            return title
        marker_split = re.split(
            r"(?:转载精修|原创翻译|校订翻译|听译|双语|简体|繁体|英语|英文|SRT|ASS)",
            text,
            maxsplit=1,
            flags=re.I,
        )
        prefix = self._strip_subhd_title_labels(marker_split[0].strip())
        if title and prefix.startswith(f"{title} {title} "):
            prefix = f"{title} {prefix[len(title + ' ' + title + ' '):]}"
        if title and prefix == f"{title} {title}":
            prefix = title
        if prefix and len(prefix) <= 180 and (not title or len(prefix) > len(title)):
            return prefix
        return title or prefix

    def _strip_subhd_title_labels(self, value: str) -> str:
        return re.sub(
            r"^(?:(?:字幕信息|下载次数|上传人|片源版本|字幕来源|字幕版本)\s+)+",
            "",
            value,
        ).strip()

    def _parse_movie_page_regex(
        self, html_text: str, movie: MovieInfo, page_url: str
    ) -> list[SubtitleCandidate]:
        result: list[SubtitleCandidate] = []
        for match in re.finditer(r'href="/a/([^"]+)">([\s\S]*?)</a>', html_text):
            start = max(0, match.start() - 600)
            end = min(len(html_text), match.end() + 1000)
            title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            text = re.sub(r"<[^>]+>", " ", html_text[start:end])
            title = self._extract_result_title(title, text)
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
        file_size_kb = self._parse_file_size_kb(text)
        download_count = self._parse_download_count(text)
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
            subtitle_format=self._detect_subtitle_format(text),
            download_count=download_count,
            detail_url=urljoin(page_url, f"/a/{subtitle_id}"),
            download_url=urljoin(page_url, f"/down/{subtitle_id}"),
            description=format_chinese_description(
                ("字幕标题", title),
                ("页面内容", text),
            ),
            file_names=[title],
            raw={
                "subhdText": text,
                "fileSizeKB": file_size_kb,
                "downloadCount": download_count,
            },
        )

    def _needs_detail_metadata(self, candidate: SubtitleCandidate) -> bool:
        language = candidate.language_type
        has_language = bool(
            language
            and re.search(r"(双语|中英|简英)", language)
            and re.search(r"(简体|简中|中文)", language)
            and re.search(r"(英语|英文)", language)
        )
        return (
            not candidate.subtitle_format
            or not has_language
            or not candidate.raw.get("fileSizeKB")
            or not candidate.download_url
            or "subhdDetailText" not in candidate.raw
        )

    def _detail_download_url(self, html_text: str, page_url: str, subtitle_id: str) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            match = re.search(r'href=["\'](/down/[^"\']+)["\']', html_text, re.I)
            if match:
                return urljoin(page_url, match.group(1))
            return urljoin(page_url, f"/down/{subtitle_id}")

        soup = BeautifulSoup(html_text, "html.parser")
        link = soup.find("a", href=re.compile(r"^/down/"))
        if link and link.get("href"):
            return urljoin(page_url, str(link.get("href")))
        button = soup.select_one(".down[sid], button[sid]")
        sid = button.get("sid") if button else ""
        return urljoin(page_url, f"/down/{sid or subtitle_id}")

    def _detail_page_text(self, html_text: str) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return re.sub(r"<[^>]+>", " ", html_text)
        soup = BeautifulSoup(html_text, "html.parser")
        return soup.get_text(" ", strip=True)

    def _merge_detail_metadata(self, candidate: SubtitleCandidate, html_text: str) -> None:
        detail_text = self._detail_page_text(html_text)
        combined_text = " ".join(
            value
            for value in [
                candidate.subtitle_title,
                candidate.description,
                detail_text,
            ]
            if value
        )
        language_type = self._detect_language_type(combined_text)
        if language_type and len(language_type) >= len(candidate.language_type):
            candidate.language_type = language_type
        subtitle_format = self._detect_subtitle_format(combined_text)
        if subtitle_format:
            candidate.subtitle_format = subtitle_format
        file_size_kb = self._parse_file_size_kb(combined_text)
        if file_size_kb:
            candidate.raw["fileSizeKB"] = file_size_kb
        download_count = self._parse_download_count(combined_text)
        if download_count:
            candidate.download_count = download_count
            candidate.raw["downloadCount"] = download_count
        candidate.download_url = self._detail_download_url(
            html_text,
            candidate.detail_url,
            candidate.provider_subtitle_id,
        )
        candidate.description = format_chinese_description(
            ("字幕标题", candidate.subtitle_title),
            ("页面内容", combined_text),
        )
        candidate.raw["subhdDetailText"] = detail_text

    async def _enrich_candidates_with_detail_pages(
        self,
        client: httpx.AsyncClient,
        candidates: list[SubtitleCandidate],
        headers: dict[str, str],
    ) -> None:
        for candidate in candidates:
            if not self._needs_detail_metadata(candidate):
                continue
            try:
                response = await client.get(candidate.detail_url, headers=headers)
                response.raise_for_status()
            except Exception as exc:
                logger.info("SubHD detail page fetch failed: %s, exc=%s", candidate.detail_url, exc)
                continue
            self._merge_detail_metadata(candidate, response.text)

    async def _enrich_candidates_with_playwright(self, page, candidates: list[SubtitleCandidate]) -> None:
        for candidate in candidates:
            if not self._needs_detail_metadata(candidate):
                continue
            try:
                await page.goto(candidate.detail_url, wait_until="networkidle", timeout=30_000)
                self._merge_detail_metadata(candidate, await page.content())
            except Exception:
                continue

    async def download(self, candidate: SubtitleCandidate, context: DownloadContext) -> list[DownloadedPayload]:
        detail_url = candidate.detail_url or f"{self.base_urls[0]}/a/{candidate.provider_subtitle_id}"
        original_base = detail_url.split("/a/")[0]
        tried_bases = {original_base}
        base_urls_ordered = [original_base] + [b for b in self.base_urls if b not in tried_bases]

        logger.info(
            "SubHD download start, id=%s, title=%s, bases=%s",
            candidate.provider_subtitle_id, candidate.subtitle_title, base_urls_ordered,
        )

        for base_url in base_urls_ordered:
            if context.log:
                context.log(f"SubHD httpx 下载：{base_url}")
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout),
                    follow_redirects=True,
                    headers=BROWSER_HEADERS,
                    cookies=self._shared_cookies,
                ) as client:
                    try:
                        warmup_url = f"{base_url}/search/{quote(candidate.movie_title_zh or candidate.movie_title or '')}"
                        await client.get(warmup_url)
                    except Exception:
                        pass

                    result = await self._download_via_api(client, base_url, candidate, context)
                    if result:
                        logger.info("SubHD download success: id=%s", candidate.provider_subtitle_id)
                        return result
            except Exception as exc:
                logger.info(
                    "SubHD download failed: base=%s, id=%s, exc=%s",
                    base_url, candidate.provider_subtitle_id, exc,
                )
                if context.log:
                    context.log(f"SubHD 下载失败（{base_url}）：{exc}，尝试备用域名")
                continue

        logger.info("SubHD ALL download paths failed: id=%s", candidate.provider_subtitle_id)
        raise CollectorError("SubHD 所有下载路径均失败", ErrorType.DOWNLOAD_FAILED, self.id)

    async def _download_via_api(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        candidate: SubtitleCandidate,
        context: DownloadContext,
    ) -> list[DownloadedPayload] | None:
        headers = {
            **API_HEADERS,
            "Origin": base_url,
            "Referer": f"{base_url}/down/{candidate.provider_subtitle_id}",
        }
        down_url = candidate.download_url or f"{base_url}/down/{candidate.provider_subtitle_id}"
        try:
            await client.get(down_url, headers={**BROWSER_HEADERS, "Referer": f"{base_url}/"})
        except Exception as exc:
            logger.info("SubHD /down/ warmup failed: %s", exc)

        captcha_code = ""
        for attempt in range(3):
            body = {"sid": candidate.provider_subtitle_id, "cap": captcha_code}
            try:
                resp = await client.post(
                    f"{base_url}/api/sub/down",
                    json=body,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.info("SubHD api/sub/down failed: base=%s, attempt=%d, exc=%s", base_url, attempt + 1, exc)
                return None

            if data.get("success") and data.get("pass") is False:
                logger.info("SubHD api/sub/down requires captcha, attempt=%d", attempt + 1)
                captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                if captcha_code == _CAPTCHA_REFRESH:
                    captcha_code = ""
                    continue
                if not captcha_code:
                    return None
                continue

            if data.get("success") and data.get("url"):
                dl_url = data["url"]
                logger.info("SubHD api/sub/down got url: %s", dl_url)
                try:
                    download_resp = await client.get(
                        dl_url,
                        headers={
                            "User-Agent": USER_AGENT,
                            "Accept": "*/*",
                            "Referer": base_url,
                        },
                    )
                    download_resp.raise_for_status()
                    content = download_resp.content
                except Exception as exc:
                    logger.info("SubHD download file failed: %s", exc)
                    return None

                if not self._is_valid_download_content(content):
                    logger.info(
                        "SubHD download content is not a valid subtitle payload, size=%d",
                        len(content) if content else 0,
                    )
                    return None

                content_disposition = download_resp.headers.get("content-disposition", "")
                content_type = download_resp.headers.get("content-type", "")
                file_name = self._download_file_name(dl_url, candidate, content_disposition)
                logger.info("SubHD download success: size=%d, file=%s", len(content), file_name)
                return [DownloadedPayload(
                    file_name=file_name,
                    content=content,
                    source_url=dl_url,
                    content_type=content_type or self._content_type_for_file_name(file_name),
                )]

            if not data.get("success"):
                logger.info("SubHD api/sub/down returned success=false, attempt=%d, data=%s", attempt + 1, str(data)[:200])
                if not self._api_response_has_captcha(data):
                    return None
                captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                if captcha_code == _CAPTCHA_REFRESH:
                    captcha_code = ""
                    continue
                if not captcha_code:
                    return None
                continue

            logger.info("SubHD api/sub/down unexpected response: %s", str(data)[:200])
            return None

        return None

    def _api_response_has_captcha(self, api_response: dict) -> bool:
        msg = str(api_response.get("msg") or "")
        return bool(
            api_response.get("captcha_url")
            or api_response.get("captchaUrl")
            or re.search(r"<svg[^>]*>[\s\S]*?</svg>", msg, re.I)
            or re.search(r"<img[^>]+>", msg, re.I)
            or re.search(r"(验证码|验证|captcha|cap)", msg, re.I)
        )

    async def _handle_captcha(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        candidate: SubtitleCandidate,
        context: DownloadContext,
        api_response: dict,
    ) -> str:
        msg = str(api_response.get("msg") or "")
        verification_html = self._extract_verification_html(msg) if msg else ""
        image_data_uri = ""

        svg_match = re.search(r'<svg[^>]*>[\s\S]*?</svg>', msg, re.I)
        if svg_match:
            svg_content = svg_match.group(0)
            image_data_uri = self._to_data_uri(svg_content.encode("utf-8"), "image/svg+xml")
            verification_html = svg_content

        if not image_data_uri:
            captcha_url = api_response.get("captcha_url") or api_response.get("captchaUrl") or ""
            if not captcha_url:
                img_match = re.search(r'<img[^>]+\bsrc=["\']?([^"\'\s>]+)', msg, re.I)
                if img_match:
                    captcha_url = img_match.group(1)
            if captcha_url:
                image_data_uri = await self._fetch_captcha_image(
                    client, base_url, captcha_url,
                    referer=f"{base_url}/down/{candidate.provider_subtitle_id}",
                )

        if not image_data_uri:
            image_data_uri = await self._fetch_captcha_from_down_page(client, base_url, candidate)

        suggested_code = ""
        suggested_confidence = 0.0
        ocr_message = ""

        if context.captcha_ocr_enabled and image_data_uri:
            try:
                from ..engines.captcha_solver import solve_captcha_data_uri
                ocr_result = solve_captcha_data_uri(image_data_uri)
                if ocr_result:
                    suggested_code = ocr_result.text or ""
                    suggested_confidence = ocr_result.confidence or 0.0
                    ocr_message = ocr_result.message or ""
            except Exception as exc:
                logger.info("SubHD OCR failed: %s", exc)
                ocr_message = str(exc)

        if suggested_code and suggested_confidence >= context.captcha_auto_submit_min_confidence:
            logger.info("SubHD OCR auto submit: code=%s, confidence=%.2f", suggested_code, suggested_confidence)
            return suggested_code

        if not context.request_verification:
            logger.info("SubHD captcha required but no verification callback")
            return ""

        from ..errors import VerificationRequest
        vr = await context.request_verification(VerificationRequest(
            provider=self.id,
            provider_subtitle_id=candidate.provider_subtitle_id,
            subtitle_title=candidate.subtitle_title,
            detail_url=candidate.detail_url or "",
            verification_html=verification_html,
            verification_image_data_uri=image_data_uri,
            suggested_code=suggested_code,
            suggested_confidence=suggested_confidence,
            ocr_message=ocr_message,
        ))

        if vr and vr.refresh:
            return _CAPTCHA_REFRESH
        if vr and vr.code:
            return vr.code.strip()

        return ""

    async def _fetch_captcha_from_down_page(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        candidate: SubtitleCandidate,
    ) -> str:
        down_url = f"{base_url}/down/{candidate.provider_subtitle_id}"
        try:
            resp = await client.get(down_url, headers={**BROWSER_HEADERS, "Referer": f"{base_url}/"})
            if resp.status_code != 200:
                logger.info("SubHD /down/ page fetch failed: HTTP %d", resp.status_code)
            else:
                html_text = resp.text
                if _is_cloudflare_challenge_page(html_text):
                    logger.info("SubHD /down/ page blocked by Cloudflare")
                else:
                    verification_html = self._extract_captcha_html_from_down_page(html_text)
                    if verification_html:
                        return await self._verification_image_data_uri(
                            client, base_url, verification_html, referer=down_url,
                        )

                    logger.info("SubHD /down/ page: no captcha image found")
        except Exception as exc:
            logger.info("SubHD /down/ page fetch exception: %s", exc)

        logger.info("SubHD httpx failed to get captcha, trying Playwright fallback")
        return await self._fetch_captcha_via_playwright(base_url, candidate)

    def _extract_captcha_html_from_down_page(self, html_text: str) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            container = re.search(
                r'<[^>]+id=["\']svgCap["\'][^>]*>([\s\S]*?)</[^>]+>',
                html_text,
                re.I,
            )
            scoped = container.group(1) if container else html_text
            svg = re.search(r"<svg[^>]*>[\s\S]*?</svg>", scoped, re.I)
            if svg:
                return svg.group(0)
            img = re.search(
                r'<img[^>]+(?:class|id|src)=["\'][^"\']*captcha[^"\']*["\'][^>]*>',
                scoped,
                re.I,
            )
            return img.group(0) if img else ""

        soup = BeautifulSoup(html_text, "html.parser")
        for selector in [
            "#svgCap svg",
            "#captcha svg",
            ".captcha svg",
            ".captcha-img svg",
            "#svgCap img",
            "img.captcha",
            "img[id*='captcha']",
            "img[src*='captcha']",
            ".captcha img",
            ".captcha-img img",
        ]:
            element = soup.select_one(selector)
            if element:
                return str(element)
        return ""

    async def _fetch_captcha_via_playwright(
        self,
        base_url: str,
        candidate: SubtitleCandidate,
    ) -> str:
        page = None
        try:
            await self._ensure_browser()
            if not self._browser_context:
                logger.info("SubHD Playwright browser not available for captcha")
                return ""

            page = await self._browser_context.new_page()
            down_url = f"{base_url}/down/{candidate.provider_subtitle_id}"

            await self._navigate_with_challenge_handling(page, down_url)

            captcha_selectors = [
                "#svgCap svg",
                "#svgCap img",
                "#captcha svg",
                "img.captcha",
                "img[src*='captcha']",
                "img[id*='captcha']",
                "img[alt*='验证']",
                "img[alt*='captcha']",
                "#captcha",
                ".captcha-img",
                ".captcha img",
            ]

            for selector in captcha_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0 and await element.is_visible():
                        screenshot_bytes = await element.screenshot()
                        if screenshot_bytes and len(screenshot_bytes) > 100:
                            logger.info("SubHD Playwright got captcha image via selector: %s", selector)
                            return self._to_data_uri(screenshot_bytes, "image/png")
                except Exception:
                    continue

            logger.info("SubHD Playwright: no captcha image found on /down/ page")
            return ""
        except Exception as exc:
            logger.info("SubHD Playwright captcha fetch failed: %s", exc)
            return ""
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    @staticmethod
    def _is_cloudflare_block(html_text: str, status_code: int | None = None) -> bool:
        if status_code in (403, 500, 502, 503):
            return True
        cf_markers = [
            "cf-browser-verify", "challenge-platform",
            "Checking your browser", "Please enable JavaScript",
            "just a moment", "_cf_chl_opt",
            "cf-challenge", "cf-turnstile",
        ]
        lower = html_text.lower()
        return any(marker.lower() in lower for marker in cf_markers)

    @staticmethod
    def _is_html_content(content: bytes) -> bool:
        if not content:
            return False
        stripped = content.lstrip()
        if not stripped:
            return False
        lower_stripped = stripped[:100].lower()
        if lower_stripped.startswith(b"<!doctype") or lower_stripped.startswith(b"<html"):
            return True
        head = stripped[:500].lower()
        html_markers = [
            b"<head", b"<body", b"<div", b"<script", b"<meta",
            b"<title>", b"<!doctype", b"<html", b"<!--",
        ]
        for marker in html_markers:
            if marker in head:
                return True
        return False

    @staticmethod
    def _is_valid_download_content(content: bytes) -> bool:
        if not content or len(content) < 4:
            return False
        if SubhdProvider._is_html_content(content):
            return False
        if content[:2] == b"PK":
            return True
        if content[:4] == b"Rar!":
            return True
        if content[:2] == b"7z":
            return True
        if content[:3] == b"\x1f\x8b\x08":
            return True
        text_head = content[:200].decode("utf-8", errors="ignore").strip().lower()
        if text_head.startswith("[script info]") or text_head.startswith("\ufeff[script info]"):
            return True
        if re.match(r"\A\s*\d+\s*\n\d{1,2}:\d{2}:\d{2}", text_head):
            return True
        return False

    @staticmethod
    def _is_download_response(content_type: str, content_disposition: str) -> bool:
        if "attachment" in content_disposition.lower():
            return True
        ct = content_type.lower()
        binary_types = [
            "octet-stream", "zip", "x-rar", "x-7z-compressed",
            "x-rar-compressed", "application/x-7z", "application/rar",
            "application/x-bzip2", "application/gzip",
        ]
        if any(t in ct for t in binary_types):
            return True
        return False

    @staticmethod
    def _extract_filename_from_cd(content_disposition: str) -> str:
        if not content_disposition:
            return ""
        match2 = re.search(r'filename\*[^;]*=\s*["\']?([^"\';\n]+)', content_disposition, re.I)
        if match2:
            value = match2.group(1).strip()
            if "''" in value:
                value = value.split("''", 1)[1]
            return unquote(value).strip()
        match = re.search(r'filename[^;]*=\s*["\']?([^"\';\n]+)', content_disposition, re.I)
        if match:
            return unquote(match.group(1).strip())
        return ""

    async def _fetch_captcha_image(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        captcha_url: str,
        referer: str,
    ) -> str:
        image_url = urljoin(base_url, captcha_url) if not captcha_url.startswith("http") else captcha_url
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

    def _download_extension(self, url: str, content_disposition: str = "") -> str:
        cd_name = self._extract_filename_from_cd(content_disposition)
        candidates = [
            cd_name,
            unquote(urlparse(url).path.rsplit("/", 1)[-1]),
        ]
        for value in candidates:
            suffix = value.rsplit(".", 1)[-1].lower() if "." in value else ""
            if suffix in {"zip", "rar", "7z", "gz", "ass", "srt"}:
                return suffix
        return "zip"

    def _content_type_for_file_name(self, file_name: str) -> str:
        suffix = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        return {
            "zip": "application/zip",
            "rar": "application/vnd.rar",
            "7z": "application/x-7z-compressed",
            "gz": "application/gzip",
            "ass": "text/plain",
            "srt": "text/plain",
        }.get(suffix, "application/octet-stream")

    def _download_file_name(
        self,
        url: str,
        candidate: SubtitleCandidate,
        content_disposition: str = "",
    ) -> str:
        cd_name = self._extract_filename_from_cd(content_disposition)
        if cd_name:
            return cd_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        suffix = self._download_extension(url, content_disposition)
        title = normalize_text(candidate.subtitle_title or candidate.movie_title_zh or candidate.movie_title or "subtitle")
        title = title.replace(" ", ".") or "subtitle"
        return f"{title}.{suffix}"
