from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from datetime import datetime

from ..errors import CollectorError, ErrorType
from ..engines.scorer import build_movie_search_keywords, normalize_text
from ..engines.subtitle_engine import detect_subtitle_format
from ..models import DownloadedPayload, MovieInfo, SubtitleCandidate, format_chinese_description
from .base import DownloadContext, LogCallback, ProviderHealth

# 主域名 subhd.tv；备用 me / one；其余作末位回退
DEFAULT_BASE_URLS = [
    "https://subhd.tv",
    "https://subhd.me",
    "https://subhd.one",
    "https://subhd.cc",
    "https://subhd.la",
]
# 搜索 httpx 单次请求超时（秒）：快速失败，避免多域名叠满外层 120s
_SEARCH_HTTPX_TIMEOUT = 12.0
# httpx 阶段最多探测的域名数（主域 + 少量备用）
_SEARCH_HTTPX_MAX_BASES = 2
# httpx 阶段预算（秒）；用尽则跳过 Playwright，抛出超时由编排器换源
_SEARCH_HTTPX_BUDGET_SECONDS = 45.0

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
    "X-Requested-With": "XMLHttpRequest",
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
_EXPIRED_PAGE_MARKERS = (
    "时间过长本临时页面已经失效",
    "临时页面已经失效",
    "下载页面已失效",
    "本临时下载页面已经失效",
)


def _is_cloudflare_challenge_page(html_text: str) -> bool:
    lower = html_text.lower()
    return any(marker.lower() in lower for marker in _CF_CHALLENGE_MARKERS)


# 判断页面或 API 文案是否表示下载临时页已失效
def _is_expired_temp_page_text(text: str) -> bool:
    return any(marker in (text or "") for marker in _EXPIRED_PAGE_MARKERS)


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

    def __init__(self, base_urls: list[str] | None = None, timeout: float = 30, proxy: str | None = None) -> None:
        self.base_urls = [url.rstrip("/") for url in (base_urls or DEFAULT_BASE_URLS)]
        self.timeout = timeout
        self.proxy = proxy
        self._shared_cookies = httpx.Cookies()
        self._browser = None
        self._browser_context = None
        self._playwright_instance = None

    @staticmethod
    def _emit(event, message, log=None, **kwargs):
        if log:
            log(message)
        logger.info("subhd.%s %s", event, message)


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
        # browser/context 在整次采集任务内复用；仅在未创建或已断开时冷启动
        # page 仍由各次搜索/下载按需 new_page，并在 finally 中 close（page 便宜，browser 贵）
        if self._browser is None or not self._browser.is_connected():
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
            from playwright.async_api import async_playwright
            logger.info("SubHD Playwright 冷启动浏览器")
            self._playwright_instance = await async_playwright().start()
            launch_kwargs: dict[str, object] = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-infobars",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            }
            if self.proxy:
                launch_kwargs["proxy"] = {"server": self.proxy}
            self._browser = await self._playwright_instance.chromium.launch(**launch_kwargs)
            self._browser_context = await self._browser.new_context(
                user_agent=USER_AGENT,
                accept_downloads=True,
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
        else:
            logger.info("SubHD Playwright 复用已有浏览器")

    # 将 Playwright context cookie 合并进目标 jar（默认共享 jar，搜索复用；下载可传按域 jar）
    async def _sync_playwright_cookies_to_shared(
        self,
        target: httpx.Cookies | None = None,
    ) -> None:
        if not self._browser_context:
            return
        jar = target if target is not None else self._shared_cookies
        try:
            cookies = await self._browser_context.cookies()
            for item in cookies:
                name = str(item.get("name") or "")
                value = str(item.get("value") or "")
                if not name:
                    continue
                jar.set(
                    name,
                    value,
                    domain=str(item.get("domain") or ""),
                    path=str(item.get("path") or "/"),
                )
            logger.info("SubHD Playwright cookies synced, count=%d", len(cookies))
        except Exception as exc:
            logger.info("SubHD Playwright cookie sync failed: %s", exc)

    # 用浏览器打开同域 /down，过 CF 后把 cookie 写回共享 jar（仅预热，不调下载 API）
    async def _warm_down_via_playwright(
        self,
        base_url: str,
        subtitle_id: str,
        context: DownloadContext | None = None,
    ) -> bool:
        page = None
        try:
            page = await self._open_down_page_via_playwright(base_url, subtitle_id, context)
            if page is None:
                return False
            await self._sync_playwright_cookies_to_shared()
            return True
        except Exception as exc:
            logger.info("SubHD Playwright down warm failed: %s", exc)
            return False
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    # 打开详情页 → prepare-download → /down，返回仍打开的 page；失败返回 None
    async def _open_down_page_via_playwright(
        self,
        base_url: str,
        subtitle_id: str,
        context: DownloadContext | None = None,
    ):
        try:
            import importlib.util
            if importlib.util.find_spec("playwright") is None:
                logger.info("SubHD Playwright not available for down page")
                return None
        except ImportError:
            return None

        await self._ensure_browser()
        if not self._browser_context:
            return None
        if context and context.log:
            context.log(f"SubHD Playwright 打开下载页建立会话：{base_url}")
        page = await self._browser_context.new_page()
        try:
            await page.add_init_script(_stealth_script())
            detail_url = f"{base_url}/a/{subtitle_id}"
            html = await self._navigate_with_challenge_handling(
                page, detail_url, max_retries=2, wait_seconds=3
            )
            if not html or _is_cloudflare_challenge_page(html):
                reason = "详情页 Cloudflare" if html else "详情页打开失败"
                logger.info("SubHD Playwright %s: %s", reason, detail_url)
                if context and context.log:
                    context.log(f"SubHD Playwright {reason}：{base_url}")
                await page.close()
                return None

            down_path = await self._prepare_download_via_playwright(base_url, subtitle_id, detail_url)
            if not down_path:
                if context and context.log:
                    context.log(f"SubHD Playwright prepare-download 失败：{base_url}")
                await page.close()
                return None

            down_url = urljoin(base_url + "/", down_path.lstrip("/"))
            html = await self._navigate_with_challenge_handling(
                page, down_url, max_retries=3, wait_seconds=3
            )
            if not html:
                logger.info("SubHD Playwright /down navigate failed: %s", down_url)
                if context and context.log:
                    context.log(f"SubHD Playwright /down 打开失败：{base_url}")
                await page.close()
                return None
            if _is_cloudflare_challenge_page(html):
                logger.info("SubHD Playwright /down still Cloudflare: %s", down_url)
                if context and context.log:
                    context.log(f"SubHD Playwright /down 仍被 Cloudflare：{base_url}")
                await page.close()
                return None
            if _is_expired_temp_page_text(html):
                logger.info("SubHD Playwright /down expired, re-prepare once: %s", down_url)
                if context and context.log:
                    context.log(f"SubHD Playwright /down 临时页失效，同域重新 prepare：{base_url}")
                # 临时页失效后同域立即 re-prepare 再打开一次
                retry_path = await self._prepare_download_via_playwright(
                    base_url, subtitle_id, detail_url
                )
                if retry_path:
                    down_url = urljoin(base_url + "/", retry_path.lstrip("/"))
                    html = await self._navigate_with_challenge_handling(
                        page, down_url, max_retries=2, wait_seconds=3
                    )
                    if (
                        html
                        and not _is_cloudflare_challenge_page(html)
                        and not _is_expired_temp_page_text(html)
                    ):
                        return page
                logger.info("SubHD Playwright /down still expired after re-prepare: %s", base_url)
                if context and context.log:
                    context.log(f"SubHD Playwright /down 仍显示临时页失效：{base_url}")
                await page.close()
                return None
            return page
        except Exception:
            try:
                await page.close()
            except Exception:
                pass
            raise

    # 在浏览器请求上下文中调用 prepare-download，返回 /down/... 路径
    async def _prepare_download_via_playwright(
        self,
        base_url: str,
        subtitle_id: str,
        referer: str,
    ) -> str | None:
        if not self._browser_context:
            return None
        try:
            resp = await self._browser_context.request.post(
                f"{base_url}/api/sub/prepare-download",
                data=json.dumps({"sid": subtitle_id}),
                headers={
                    **API_HEADERS,
                    "Origin": base_url,
                    "Referer": referer,
                },
            )
            if not resp.ok:
                logger.info(
                    "SubHD Playwright prepare-download HTTP %s: %s",
                    resp.status, base_url,
                )
                return None
            data = await resp.json()
            url = data.get("url") if isinstance(data, dict) else None
            if data.get("success") and isinstance(url, str) and url.startswith("/down/"):
                return url
            logger.info("SubHD Playwright prepare-download rejected: %s", str(data)[:200])
            return None
        except Exception as exc:
            logger.info("SubHD Playwright prepare-download failed: %s", exc)
            return None

    # 在浏览器会话内 POST /api/sub/down 并拉取文件（使用 request API，避免页内 fetch CORS）
    async def _download_via_playwright_api(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        candidate: SubtitleCandidate,
        context: DownloadContext,
    ) -> list[DownloadedPayload] | None:
        subtitle_id = candidate.provider_subtitle_id
        page = None
        try:
            page = await self._open_down_page_via_playwright(base_url, subtitle_id, context)
            if page is None:
                return None
            # 同步到当前 httpx client 的按域 jar，避免污染其它镜像域名
            await self._sync_playwright_cookies_to_shared(client.cookies)
            if context.log:
                context.log(f"SubHD Playwright 调用下载 API：{base_url}")

            down_url = page.url or f"{base_url}/down/{subtitle_id}"
            captcha_code = ""
            for attempt in range(3):
                try:
                    raw = await self._post_sub_down_via_playwright(
                        base_url, subtitle_id, captcha_code, referer=down_url
                    )
                except Exception as exc:
                    logger.info(
                        "SubHD Playwright api/sub/down failed: base=%s, attempt=%d, exc=%s",
                        base_url, attempt + 1, exc,
                    )
                    if context.log:
                        context.log(f"SubHD Playwright API 调用失败（{base_url}）：{exc}")
                    return None

                if not isinstance(raw, dict):
                    logger.info("SubHD Playwright api/sub/down unexpected raw: %s", str(raw)[:200])
                    return None
                if not raw.get("ok"):
                    logger.info(
                        "SubHD Playwright api/sub/down HTTP %s: %s",
                        raw.get("status"), str(raw.get("data"))[:200],
                    )
                    if context.log:
                        context.log(
                            f"SubHD Playwright API HTTP {raw.get('status')}（{base_url}）"
                        )
                    return None

                data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
                payloads = await self._consume_sub_down_api_result(
                    client,
                    base_url,
                    candidate,
                    context,
                    data,
                    captcha_code,
                    attempt,
                    download_file=self._download_file_via_playwright,
                )
                # None=失败；非空=成功；空列表=需带验证码重试
                if payloads is None:
                    return None
                if payloads:
                    return payloads
                next_cap = getattr(self, "_pending_captcha_code", None)
                if next_cap is None:
                    return None
                captcha_code = "" if next_cap == _CAPTCHA_REFRESH else next_cap
                self._pending_captcha_code = None
                continue
            return None
        except Exception as exc:
            logger.info("SubHD Playwright download failed: %s", exc)
            if context.log:
                context.log(f"SubHD Playwright 下载失败（{base_url}）：{exc}")
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    # 用 Playwright 请求上下文 POST /api/sub/down
    async def _post_sub_down_via_playwright(
        self,
        base_url: str,
        subtitle_id: str,
        captcha_code: str,
        referer: str,
    ) -> dict:
        if not self._browser_context:
            return {"ok": False, "status": 0, "data": {"success": False, "msg": "no browser"}}
        resp = await self._browser_context.request.post(
            f"{base_url}/api/sub/down",
            data=json.dumps({"sid": subtitle_id, "cap": captcha_code}),
            headers={
                **API_HEADERS,
                "Origin": base_url,
                "Referer": referer,
            },
        )
        try:
            data = await resp.json()
        except Exception:
            text = await resp.text()
            data = {"success": False, "msg": (text or "")[:200]}
        return {"ok": resp.ok, "status": resp.status, "data": data}

    # 用 Playwright 请求上下文下载文件内容
    async def _download_file_via_playwright(self, dl_url: str, base_url: str) -> tuple[bytes, str, str] | None:
        if not self._browser_context:
            return None
        try:
            resp = await self._browser_context.request.get(
                dl_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "*/*",
                    "Referer": base_url,
                },
            )
            if not resp.ok:
                logger.info("SubHD Playwright file download HTTP %s: %s", resp.status, dl_url)
                return None
            content = await resp.body()
            headers = resp.headers
            return (
                content,
                headers.get("content-disposition", "") or "",
                headers.get("content-type", "") or "",
            )
        except Exception as exc:
            logger.info("SubHD Playwright file download failed: %s", exc)
            return None

    # 解析 /api/sub/down 结果：成功则下载文件；验证码则写入 _pending_captcha_code 并返回 [] 表示重试
    async def _consume_sub_down_api_result(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        candidate: SubtitleCandidate,
        context: DownloadContext,
        data: dict,
        captcha_code: str,
        attempt: int,
        download_file,
    ) -> list[DownloadedPayload] | None:
        self._pending_captcha_code = None
        subtitle_id = candidate.provider_subtitle_id

        if data.get("success") and data.get("pass") is False:
            if getattr(self, "_ocr_auto_submitted", False):
                self._ocr_auto_submitted = False
                self._emit(
                    "subhd.captcha.auto_retry",
                    "SubHD OCR auto-submit failed, auto-refreshing",
                    log=context.log,
                    subtitle_id=subtitle_id,
                )
                self._pending_captcha_code = _CAPTCHA_REFRESH
                return []
            code = await self._handle_captcha(client, base_url, candidate, context, data)
            if code == _CAPTCHA_REFRESH:
                self._emit(
                    "subhd.captcha.refresh",
                    "SubHD captcha refresh",
                    log=context.log,
                    subtitle_id=subtitle_id,
                    attempt=str(attempt + 1),
                )
                self._ocr_auto_submitted = False
                self._pending_captcha_code = _CAPTCHA_REFRESH
                return []
            if not code:
                self._emit(
                    "subhd.captcha.empty_cancel",
                    "SubHD captcha cancelled",
                    log=context.log,
                    subtitle_id=subtitle_id,
                )
                return None
            masked = code[0] + "*" * (len(code) - 1) if len(code) > 1 else code
            self._emit(
                "subhd.captcha.api_submit",
                "SubHD captcha submitted",
                log=context.log,
                subtitle_id=subtitle_id,
                code_masked=masked,
                attempt=str(attempt + 1),
            )
            self._pending_captcha_code = code
            return []

        if data.get("success") and data.get("url"):
            dl_url = data["url"]
            if captcha_code:
                logger.info("SubHD 验证码验证成功")
            logger.info("SubHD api/sub/down got url: %s", dl_url)
            file_result = await download_file(dl_url, base_url)
            if not file_result:
                return None
            content, content_disposition, content_type = file_result
            if not self._is_valid_download_content(content):
                logger.info(
                    "SubHD download content is not a valid subtitle payload, size=%d",
                    len(content) if content else 0,
                )
                return None
            file_name = self._download_file_name(dl_url, candidate, content_disposition)
            logger.info("SubHD download success: size=%d, file=%s", len(content), file_name)
            return [DownloadedPayload(
                file_name=file_name,
                content=content,
                source_url=dl_url,
                content_type=content_type or self._content_type_for_file_name(file_name),
            )]

        if not data.get("success"):
            server_msg = str(data.get("msg") or str(data)[:200])
            if self._api_response_has_captcha(data):
                logger.info("SubHD 验证码验证失败: %s", server_msg)
                code = await self._handle_captcha(client, base_url, candidate, context, data)
                if code == _CAPTCHA_REFRESH:
                    self._pending_captcha_code = _CAPTCHA_REFRESH
                    return []
                if not code:
                    return None
                self._pending_captcha_code = code
                return []
            logger.info("SubHD api/sub/down 请求失败 (第 %d 次尝试): %s", attempt + 1, server_msg)
            if context.log:
                context.log(f"SubHD API 拒绝下载（{base_url}）：{server_msg[:200]}")
            return None

        logger.info("SubHD api/sub/down unexpected response: %s", str(data)[:200])
        return None

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.id, enabled=True, healthy=True)

    # 搜索关键词含原标题与「标题+年份」变体
    def _keywords(self, movie: MovieInfo) -> list[str]:
        return build_movie_search_keywords(movie)

    async def _navigate_with_challenge_handling(
        self,
        page,
        url: str,
        max_retries: int = 3,
        wait_seconds: int = 3,
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

    async def search(self, movie: MovieInfo, log: LogCallback | None = None) -> list[SubtitleCandidate]:
        keywords = self._keywords(movie)
        logger.info("SubHD search start, movie=%s, keywords=%s", movie.title_zh or movie.title, keywords)
        started = time.monotonic()

        result = await self._search_via_httpx(movie, keywords, started=started)
        if result:
            logger.info("SubHD httpx fast search hits, candidates=%d", len(result))
            return result

        elapsed = time.monotonic() - started
        if elapsed >= _SEARCH_HTTPX_BUDGET_SECONDS:
            logger.info(
                "SubHD skip Playwright: httpx budget exhausted elapsed=%.1fs budget=%.1fs",
                elapsed,
                _SEARCH_HTTPX_BUDGET_SECONDS,
            )
            # 由编排器按搜索超时处理，避免被记成「无匹配」
            raise TimeoutError("SubHD 搜索阶段性超时（httpx 预算用尽）")

        logger.info("SubHD httpx fast search exhausted or blocked, falling back to Playwright")
        return await self._search_via_playwright(movie, keywords, started=started)

    async def _search_via_httpx(
        self,
        movie: MovieInfo,
        keywords: list[str],
        *,
        started: float,
    ) -> list[SubtitleCandidate]:
        # 串行探测域名：并发多域名会把 CF cookie 写入共享 jar，导致后续下载 API 全失败
        search_timeout = httpx.Timeout(_SEARCH_HTTPX_TIMEOUT)
        bases = self.base_urls[:_SEARCH_HTTPX_MAX_BASES]
        async with httpx.AsyncClient(
            timeout=search_timeout,
            follow_redirects=True,
            headers=BROWSER_HEADERS,
            cookies=self._shared_cookies,
            proxy=self.proxy,
        ) as client:
            for base_url in bases:
                if time.monotonic() - started >= _SEARCH_HTTPX_BUDGET_SECONDS:
                    logger.info("SubHD httpx search budget exhausted before base=%s", base_url)
                    break
                for keyword in keywords:
                    if time.monotonic() - started >= _SEARCH_HTTPX_BUDGET_SECONDS:
                        logger.info(
                            "SubHD httpx search budget exhausted before keyword=%s", keyword
                        )
                        break
                    items = await self._httpx_search_one_base(client, movie, keyword, base_url)
                    if not items:
                        continue
                    await self._enrich_candidates_with_detail_pages(client, items, BROWSER_HEADERS)
                    for item in items:
                        item.description = format_chinese_description(
                            ("搜索关键词", keyword),
                            ("字幕信息", item.description),
                        )
                    return items
        return []

    # 在单个 base_url 上执行一次 httpx 搜索并解析候选
    async def _httpx_search_one_base(
        self,
        client: httpx.AsyncClient,
        movie: MovieInfo,
        keyword: str,
        base_url: str,
    ) -> list[SubtitleCandidate] | None:
        try:
            search_url = f"{base_url}/search/{quote(keyword)}"
            logger.info("SubHD httpx search: %s", search_url)
            resp = await client.get(search_url)
            if resp.status_code != 200:
                logger.info("SubHD httpx search HTTP %d: %s", resp.status_code, search_url)
                return None
            html_text = resp.text
            if _is_cloudflare_challenge_page(html_text):
                logger.info("SubHD httpx search blocked by Cloudflare: %s", search_url)
                return None
            items = self._parse_search_results_page(html_text, movie, base_url)
            if items:
                logger.info(
                    "SubHD httpx search hits, candidates=%d, keyword=%s, base=%s",
                    len(items),
                    keyword,
                    base_url,
                )
                return items
            logger.info("SubHD httpx search no match: keyword=%s, base=%s", keyword, base_url)
            return None
        except Exception as exc:
            logger.info("SubHD httpx search failed: keyword=%s, base=%s, exc=%s", keyword, base_url, exc)
            return None

    async def _search_via_playwright(
        self,
        movie: MovieInfo,
        keywords: list[str],
        *,
        started: float | None = None,
    ) -> list[SubtitleCandidate]:
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

        search_started = started if started is not None else time.monotonic()
        # Playwright 仅试主域，减少挂起空等
        bases = self.base_urls[:1]
        for base_url in bases:
            for keyword in keywords[:2]:
                if time.monotonic() - search_started >= _SEARCH_HTTPX_BUDGET_SECONDS + 30:
                    logger.info("SubHD Playwright search budget exhausted")
                    raise TimeoutError("SubHD 搜索阶段性超时（Playwright 预算用尽）")
                page = None
                try:
                    page = await self._browser_context.new_page()
                    await page.add_init_script(_stealth_script())
                    search_url = f"{base_url}/search/{quote(keyword)}"
                    logger.info("SubHD Playwright search: %s", search_url)

                    html_text = await self._navigate_with_challenge_handling(
                        page, search_url, max_retries=1, wait_seconds=2
                    )

                    if not html_text:
                        logger.info(
                            "SubHD Playwright search: failed to load page, keyword=%s, base=%s",
                            keyword,
                            base_url,
                        )
                        continue

                    items = self._parse_search_results_page(html_text, movie, base_url)
                    if items:
                        logger.info(
                            "SubHD Playwright search hits, candidates=%d, keyword=%s",
                            len(items),
                            keyword,
                        )
                        await self._enrich_candidates_with_playwright(page, items)
                        for item in items:
                            item.description = format_chinese_description(
                                ("搜索关键词", keyword),
                                ("字幕信息", item.description),
                            )
                        return items
                    logger.info(
                        "SubHD Playwright search no match: keyword=%s, base=%s", keyword, base_url
                    )
                except TimeoutError:
                    raise
                except Exception as exc:
                    logger.info(
                        "SubHD Playwright search failed: keyword=%s, base=%s, exc=%s",
                        keyword,
                        base_url,
                        exc,
                    )
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
        self._active_log = context.log
        detail_url = candidate.detail_url or f"{self.base_urls[0]}/a/{candidate.provider_subtitle_id}"
        original_base = detail_url.split("/a/")[0]
        tried_bases = {original_base}
        base_urls_ordered = [original_base] + [b for b in self.base_urls if b not in tried_bases]

        logger.info(
            "SubHD download start, id=%s, title=%s, bases=%s",
            candidate.provider_subtitle_id, candidate.subtitle_title, base_urls_ordered,
        )

        loop = asyncio.get_running_loop()
        hard_fail_streak = 0
        forbidden_streak = 0
        # 每个域名最多允许一次 Playwright 降级，避免首域失败后备用域丢浏览器机会
        playwright_bases_used: set[str] = set()

        for base_url in base_urls_ordered:
            if context.deadline_monotonic is not None and loop.time() >= context.deadline_monotonic:
                if context.log:
                    context.log("SubHD 下载已达截止时间，停止尝试剩余域名")
                break
            # 连续多域 403 时快速放弃，避免空转全部镜像
            if forbidden_streak >= 2:
                if context.log:
                    context.log("SubHD 连续多域返回 403，停止尝试剩余域名")
                break
            allow_playwright = hard_fail_streak < 2 and base_url not in playwright_bases_used
            if context.log:
                context.log(f"SubHD httpx 下载：{base_url}")
            # 按域独立 cookie jar，避免 CF cookie 跨镜像污染导致 prepare 全失败
            domain_cookies = httpx.Cookies()
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout),
                    follow_redirects=True,
                    headers=BROWSER_HEADERS,
                    cookies=domain_cookies,
                    proxy=self.proxy,
                ) as client:
                    # 可选搜索预热，失败忽略（与历史可用实现一致）
                    try:
                        warmup_url = (
                            f"{base_url}/search/"
                            f"{quote(candidate.movie_title_zh or candidate.movie_title or '')}"
                        )
                        await client.get(warmup_url)
                    except Exception:
                        pass

                    result = await self._download_via_api(
                        client,
                        base_url,
                        candidate,
                        context,
                        allow_playwright=allow_playwright,
                    )
                    if result:
                        logger.info("SubHD download success: id=%s", candidate.provider_subtitle_id)
                        return result
                    hard_fail_streak += 1
                    if allow_playwright:
                        playwright_bases_used.add(base_url)
            except Exception as exc:
                hard_fail_streak += 1
                exc_text = str(exc)
                if "403" in exc_text or "Forbidden" in exc_text:
                    forbidden_streak += 1
                else:
                    forbidden_streak = 0
                logger.info(
                    "SubHD download failed: base=%s, id=%s, exc=%s",
                    base_url, candidate.provider_subtitle_id, exc,
                )
                if context.log:
                    context.log(f"SubHD 下载失败（{base_url}）：{exc}，尝试备用域名")
                continue

        logger.info("SubHD ALL download paths failed: id=%s", candidate.provider_subtitle_id)
        raise CollectorError("SubHD 所有下载路径均失败", ErrorType.DOWNLOAD_FAILED, self.id)

    # 尽力 GET 同域 /down 建立会话；返回页面正文供判断 CF/失效
    async def _touch_down_page(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        subtitle_id: str,
        down_path: str | None = None,
    ) -> str:
        path = down_path or f"/down/{subtitle_id}"
        if not path.startswith("/"):
            path = "/" + path
        down_url = urljoin(base_url + "/", path.lstrip("/"))
        try:
            resp = await client.get(down_url, headers={**BROWSER_HEADERS, "Referer": f"{base_url}/"})
            return resp.text or ""
        except Exception as exc:
            logger.info("SubHD /down/ warmup failed: %s, exc=%s", down_url, exc)
            return ""

    # 先打开详情页再 prepare-download，创建临时 /down 会话并返回路径
    async def _prepare_download_session(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        subtitle_id: str,
        context: DownloadContext | None = None,
    ) -> str | None:
        detail_url = f"{base_url}/a/{subtitle_id}"
        try:
            await client.get(detail_url, headers={**BROWSER_HEADERS, "Referer": f"{base_url}/"})
        except Exception as exc:
            logger.info("SubHD detail warmup failed: %s, exc=%s", detail_url, exc)

        try:
            resp = await client.post(
                f"{base_url}/api/sub/prepare-download",
                json={"sid": subtitle_id},
                headers={
                    **API_HEADERS,
                    "Origin": base_url,
                    "Referer": detail_url,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.info("SubHD prepare-download failed: base=%s, exc=%s", base_url, exc)
            if context and context.log:
                context.log(f"SubHD prepare-download 失败（{base_url}）：{exc}")
            return None

        url = data.get("url") if isinstance(data, dict) else None
        if data.get("success") and isinstance(url, str) and url.startswith("/down/"):
            if context and context.log:
                context.log(f"SubHD prepare-download 成功：{base_url}")
            return url

        msg = str((data or {}).get("msg") or data)[:200]
        logger.info("SubHD prepare-download rejected: base=%s, msg=%s", base_url, msg)
        if context and context.log:
            context.log(f"SubHD prepare-download 拒绝（{base_url}）：{msg}")
        return None

    async def _download_via_api(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        candidate: SubtitleCandidate,
        context: DownloadContext,
        allow_playwright: bool = True,
    ) -> list[DownloadedPayload] | None:
        subtitle_id = candidate.provider_subtitle_id
        # 新站流程：详情页 → prepare-download → /down → /api/sub/down
        down_path = await self._prepare_download_session(client, base_url, subtitle_id, context)
        if not down_path:
            if not allow_playwright:
                if context.log:
                    context.log(f"SubHD httpx prepare 失败，跳过浏览器降级：{base_url}")
                return None
            if context.log:
                context.log(f"SubHD httpx prepare 失败，改用浏览器下载：{base_url}")
            return await self._download_via_playwright_api(client, base_url, candidate, context)

        down_url = urljoin(base_url + "/", down_path.lstrip("/"))
        headers = {
            **API_HEADERS,
            "Origin": base_url,
            "Referer": down_url,
        }

        down_html = await self._touch_down_page(client, base_url, subtitle_id, down_path=down_path)
        # prepare 后临时页已失效：同域 re-prepare 一次再继续
        if _is_expired_temp_page_text(down_html):
            if context.log:
                context.log(f"SubHD httpx /down 临时页失效，同域重新 prepare：{base_url}")
            retry_path = await self._prepare_download_session(
                client, base_url, subtitle_id, context
            )
            if retry_path:
                down_path = retry_path
                down_url = urljoin(base_url + "/", down_path.lstrip("/"))
                headers = {
                    **API_HEADERS,
                    "Origin": base_url,
                    "Referer": down_url,
                }
                down_html = await self._touch_down_page(
                    client, base_url, subtitle_id, down_path=down_path
                )
        # prepare 后 /down 仍被 CF 或失效页拦截时，改走浏览器完整流程
        if _is_cloudflare_challenge_page(down_html) or _is_expired_temp_page_text(down_html):
            if not allow_playwright:
                if context.log:
                    context.log(f"SubHD httpx /down 不可用，跳过浏览器降级：{base_url}")
                return None
            if context.log:
                context.log(f"SubHD httpx /down 不可用，改用浏览器下载：{base_url}")
            return await self._download_via_playwright_api(client, base_url, candidate, context)

        async def _httpx_download_file(dl_url: str, referer_base: str) -> tuple[bytes, str, str] | None:
            try:
                download_resp = await client.get(
                    dl_url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "*/*",
                        "Referer": referer_base,
                    },
                )
                download_resp.raise_for_status()
                return (
                    download_resp.content,
                    download_resp.headers.get("content-disposition", ""),
                    download_resp.headers.get("content-type", ""),
                )
            except Exception as exc:
                logger.info("SubHD download file failed: %s", exc)
                return None

        captcha_code = ""
        playwright_download_tried = False
        reprepare_tried = False
        for attempt in range(3):
            body = {"sid": subtitle_id, "cap": captcha_code}
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
                if context.log:
                    context.log(f"SubHD API 下载请求失败（{base_url}）：{exc}")
                if allow_playwright and not playwright_download_tried:
                    playwright_download_tried = True
                    if context.log:
                        context.log(f"SubHD httpx API 失败，改用浏览器下载：{base_url}")
                    return await self._download_via_playwright_api(
                        client, base_url, candidate, context
                    )
                return None

            if data.get("success") and data.get("pass") is False:
                if getattr(self, "_ocr_auto_submitted", False):
                    self._ocr_auto_submitted = False
                    self._emit(
                        "subhd.captcha.auto_retry",
                        "SubHD OCR auto-submit failed, auto-refreshing",
                        log=context.log,
                        subtitle_id=subtitle_id,
                    )
                    captcha_code = _CAPTCHA_REFRESH
                else:
                    captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                if captcha_code == _CAPTCHA_REFRESH:
                    self._emit(
                        "subhd.captcha.refresh",
                        "SubHD captcha refresh",
                        log=context.log,
                        subtitle_id=subtitle_id,
                        attempt=str(attempt + 1),
                    )
                    captcha_code = ""
                    self._ocr_auto_submitted = False
                    continue
                if not captcha_code:
                    self._emit(
                        "subhd.captcha.empty_cancel",
                        "SubHD captcha cancelled",
                        log=context.log,
                        subtitle_id=subtitle_id,
                    )
                    return None
                masked = captcha_code[0] + "*" * (len(captcha_code) - 1) if len(captcha_code) > 1 else captcha_code
                self._emit(
                    "subhd.captcha.api_submit",
                    "SubHD captcha submitted",
                    log=context.log,
                    subtitle_id=subtitle_id,
                    code_masked=masked,
                    attempt=str(attempt + 1),
                )
                continue

            if data.get("success") and data.get("url"):
                payloads = await self._consume_sub_down_api_result(
                    client,
                    base_url,
                    candidate,
                    context,
                    data,
                    captcha_code,
                    attempt,
                    download_file=_httpx_download_file,
                )
                return payloads if payloads else None

            if not data.get("success"):
                server_msg = str(data.get("msg") or str(data)[:200])
                if self._api_response_has_captcha(data):
                    logger.info("SubHD 验证码验证失败: %s", server_msg)
                else:
                    logger.info("SubHD api/sub/down 请求失败 (第 %d 次尝试): %s", attempt + 1, server_msg)
                    if context.log:
                        context.log(f"SubHD API 拒绝下载（{base_url}）：{server_msg[:200]}")
                # API 提示临时页失效：先同域 re-prepare，再考虑 Playwright
                if _is_expired_temp_page_text(server_msg) and not reprepare_tried:
                    reprepare_tried = True
                    if context.log:
                        context.log(f"SubHD API 临时页失效，同域重新 prepare：{base_url}")
                    retry_path = await self._prepare_download_session(
                        client, base_url, subtitle_id, context
                    )
                    if retry_path:
                        down_path = retry_path
                        down_url = urljoin(base_url + "/", down_path.lstrip("/"))
                        headers = {
                            **API_HEADERS,
                            "Origin": base_url,
                            "Referer": down_url,
                        }
                        await self._touch_down_page(
                            client, base_url, subtitle_id, down_path=down_path
                        )
                        captcha_code = ""
                        continue
                if _is_expired_temp_page_text(server_msg) and allow_playwright and not playwright_download_tried:
                    playwright_download_tried = True
                    if context.log:
                        context.log(f"SubHD 临时页失效，改用浏览器页内下载：{base_url}")
                    return await self._download_via_playwright_api(
                        client, base_url, candidate, context
                    )
                if not self._api_response_has_captcha(data):
                    return None
                logger.info("SubHD 需要输入验证码 (第 %d 次尝试)", attempt + 1)
                captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                if captcha_code == _CAPTCHA_REFRESH:
                    logger.info("SubHD 验证码刷新请求")
                    captcha_code = ""
                    continue
                if not captcha_code:
                    logger.info("SubHD 验证码输入为空，取消下载")
                    return None
                logger.info("SubHD 提交验证码: %s (第 %d 次尝试)", captcha_code, attempt + 1)
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
        _log = context.log

        def _emit(msg: str) -> None:
            if _log:
                _log(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

        if context.captcha_ocr_enabled and image_data_uri:
            _emit("验证码 OCR 识别中...")
            logger.info("SubHD 验证码 OCR 识别开始")
            try:
                from ..engines.captcha_solver import solve_captcha_data_uri
                ocr_result = solve_captcha_data_uri(image_data_uri, subhd_mode=True)
                if ocr_result and ocr_result.text:
                    suggested_code = ocr_result.text
                    suggested_confidence = ocr_result.confidence or 0.0
                    ocr_message = ocr_result.message or ""
                    logger.info(
                        "SubHD 验证码 OCR 识别结果: %s, 置信度: %.0f%%",
                        suggested_code, suggested_confidence * 100,
                    )
                    _emit(f"验证码 OCR: {suggested_code} ({suggested_confidence:.0%})")
                else:
                    ocr_message = ocr_result.message if ocr_result else "无结果"
                    logger.info("SubHD 验证码 OCR 识别失败: %s", ocr_message)
                    _emit(f"验证码 OCR 失败: {ocr_message}")
            except Exception as exc:
                logger.info("SubHD 验证码 OCR 识别异常: %s", exc)
                ocr_message = str(exc)

        if suggested_code and suggested_confidence >= context.captcha_auto_submit_min_confidence:
            logger.info("SubHD 验证码自动提交: %s (置信度 %.0f%%)", suggested_code, suggested_confidence * 100)
            _emit(f"验证码自动提交: {suggested_code} (置信度:{suggested_confidence:.0%})")
            return suggested_code

        if context.captcha_ocr_enabled and not suggested_code:
            logger.info("SubHD 验证码等待用户手动输入 (OCR 未识别到有效内容)")
            _emit("等待手动输入验证码...")
        elif not context.captcha_ocr_enabled:
            logger.info("SubHD 验证码等待用户手动输入 (OCR 未启用)")
            _emit("等待手动输入验证码 (OCR未启用)...")

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
            user_code = vr.code.strip()
            logger.info("SubHD 验证码用户输入: %s", user_code)
            return user_code

        logger.info("SubHD 验证码用户取消输入")
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
    def _subtitle_text_head(content: bytes) -> str:
        # 识别 UTF-16/UTF-8 字幕正文头部，供 ASS/SRT 特征匹配
        if content.startswith(b"\xff\xfe") or content.startswith(b"\xfe\xff"):
            try:
                return content[:400].decode("utf-16").strip().lower()
            except UnicodeDecodeError:
                pass
        if content.startswith(b"\xef\xbb\xbf"):
            try:
                return content[:400].decode("utf-8-sig").strip().lower()
            except UnicodeDecodeError:
                pass
        text = content[:400].decode("utf-8", errors="ignore")
        # 去掉错误按 UTF-8 解出的 NUL，兼容偶发 UTF-16 无 BOM
        text = text.replace("\x00", "")
        return text.strip().lower()

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
        text_head = SubhdProvider._subtitle_text_head(content)
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
