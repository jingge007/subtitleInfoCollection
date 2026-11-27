from __future__ import annotations

import asyncio
import logging
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx

from ..errors import CollectorError, ErrorType
from ..engines.scorer import extract_years
from ..engines.subtitle_engine import detect_subtitle_format
from ..models import (
    DownloadedPayload,
    MovieInfo,
    SubtitleCandidate,
    chinese_language_label,
    format_chinese_description,
)
from .base import DownloadContext, ProviderHealth
from .base import LogCallback

logger = logging.getLogger(__name__)

_TRANSIENT_HTTPX_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
)

# 官方文档：主域网络不通时可用备用域名 api.makedie.me
_DEFAULT_ASSRT_BASE = "https://api.assrt.net/v1"
_FALLBACK_ASSRT_BASE = "https://api.makedie.me/v1"
_DEFAULT_ASSRT_SITE = "https://2.assrt.net"
_FALLBACK_ASSRT_SITES = ("https://assrt.net",)
# 本账号实际配额（文档初始值为 20 次/分钟）
_ASSRT_QUOTA_PER_MINUTE = 5
_ASSRT_QUOTA_WINDOW_S = 60.0
_TOKEN_QUERY_RE = re.compile(r"(token=)[^&\s]+", re.IGNORECASE)
_DETAIL_HREF_RE = re.compile(r"/xml/sub/(\d+)/(\d+)\.xml", re.I)
_DOWNLOAD_HREF_RE = re.compile(r"/download/\d+/[^\"'\s<>]+", re.I)
_DOWNLOAD_COUNT_RE = re.compile(r"下载次数\s*[：:]\s*(\d+)", re.I)
_LANG_RE = re.compile(r"语言\s*[：:]\s*([^\n<]+)", re.I)
_FORMAT_RE = re.compile(r"格式\s*[：:]\s*([^\n<]+)", re.I)
_VERSION_RE = re.compile(r"版本\s*[：:]\s*([^\n<]+)", re.I)
_FILENAME_RE = re.compile(r"文件名\s*[：:]\s*([^\n<]+)", re.I)
_SUBTITLE_EXT_RE = re.compile(r"\.(zip|rar|7z|srt|ass|ssa)(?:\?|$)", re.I)
# 详情页/文件名中的双语标记（点击与解压共用语义）
_BILINGUAL_NAME_RE = re.compile(
    r"(简体\s*[&+_]\s*英文|简繁英|chs\s*[&_.-]\s*eng|eng\s*[&_.-]\s*chs|"
    r"chs_eng|zh[-_.]?en|中英|简英)",
    re.I,
)
_ENGLISH_ONLY_NAME_RE = re.compile(
    r"(^|[._\s-])(eng|english|英文)([._\s-]|$)",
    re.I,
)
# 过短/泛化英文原标题：关键词与身份匹配应偏中文名
_GENERIC_SHORT_ENGLISH_TITLES = frozenset(
    {"up", "it", "her", "us", "one", "two", "big", "war", "elf", "ray", "bob", "max"}
)
_ASSRT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,text/plain,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# ASSRT JSON status → (错误类型, 中文说明模板)；模板可用 {detail}
_ASSRT_STATUS_ERRORS: dict[int, tuple[str, str]] = {
    1: (ErrorType.PROVIDER_DISABLED, "用户不存在（status=1），请检查 ASSRT_TOKEN"),
    101: (
        ErrorType.PARSE_FAILED,
        "搜索关键词过短（须大于 3 个字符，status=101）{detail}",
    ),
    20000: (ErrorType.PARSE_FAILED, "请求缺少必要参数（status=20000）{detail}"),
    20001: (ErrorType.PROVIDER_DISABLED, "Token 无效（status=20001），请检查 ASSRT_TOKEN"),
    20400: (ErrorType.PARSE_FAILED, "API 终结点不存在（status=20400）{detail}"),
    20900: (ErrorType.NO_MATCH, "字幕不存在（status=20900）{detail}"),
    30000: (ErrorType.DOWNLOAD_FAILED, "ASSRT 服务端异常（status=30000）{detail}"),
    30001: (ErrorType.DOWNLOAD_FAILED, "ASSRT 数据库不可用（status=30001）{detail}"),
    30002: (ErrorType.DOWNLOAD_FAILED, "ASSRT 搜索引擎不可用（status=30002）{detail}"),
    30300: (ErrorType.DOWNLOAD_FAILED, "ASSRT API 暂时不可用（status=30300）{detail}"),
    30900: (
        ErrorType.RATE_LIMITED,
        "ASSRT API 配额超限（5 次/分钟，status=30900），请降低请求频率后重试",
    ),
}


class AssrtProvider:
    id = "assrt"
    download_supported = True

    def __init__(
        self,
        token: str = "",
        base_url: str = _DEFAULT_ASSRT_BASE,
        site_base_url: str = _DEFAULT_ASSRT_SITE,
        request_interval_ms: int = 500,
        timeout: float = 30,
        proxy: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        fallback_base_urls: list[str] | None = None,
        fallback_site_urls: list[str] | None = None,
        quota_per_minute: int = _ASSRT_QUOTA_PER_MINUTE,
        quota_window_s: float = _ASSRT_QUOTA_WINDOW_S,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.site_base_url = site_base_url.rstrip("/")
        self.request_interval_ms = request_interval_ms
        self.timeout = timeout
        self.proxy = proxy
        self.transport = transport
        self.quota_per_minute = quota_per_minute
        self.quota_window_s = quota_window_s
        self._last_request = 0.0
        self._quota_times: list[float] = []
        # 主域失败后尝试的备用 API 根路径（不含 endpoint）
        if fallback_base_urls is not None:
            self.fallback_base_urls = [item.rstrip("/") for item in fallback_base_urls if item]
        else:
            fallbacks: list[str] = []
            if self.base_url != _FALLBACK_ASSRT_BASE.rstrip("/"):
                fallbacks.append(_FALLBACK_ASSRT_BASE.rstrip("/"))
            self.fallback_base_urls = fallbacks
        if fallback_site_urls is not None:
            self.fallback_site_urls = [item.rstrip("/") for item in fallback_site_urls if item]
        else:
            self.fallback_site_urls = [
                item.rstrip("/")
                for item in _FALLBACK_ASSRT_SITES
                if item.rstrip("/") != self.site_base_url
            ]
        self._active_base_url = self.base_url
        self._active_site_url = self.site_base_url
        self._skipped_https_hosts: set[str] = set()
        self._browser = None
        self._browser_context = None
        self._playwright_instance = None
        self._browser_proxy: str | None = None

    async def health(self) -> ProviderHealth:
        if not self.token:
            return ProviderHealth(
                self.id, enabled=False, healthy=False, error_type=ErrorType.PROVIDER_DISABLED,
                message="缺少 ASSRT_TOKEN",
            )
        return ProviderHealth(self.id, enabled=True, healthy=True)

    async def _rate_limit(self) -> None:
        now = asyncio.get_running_loop().time()
        elapsed_ms = (now - self._last_request) * 1000
        remaining = self.request_interval_ms - elapsed_ms
        if self._last_request and remaining > 0:
            await asyncio.sleep(remaining / 1000)
        self._last_request = asyncio.get_running_loop().time()

    # 滚动窗口内超过配额则等待，避免触发 30900
    async def _respect_quota(self, log: LogCallback | None = None) -> None:
        if self.quota_per_minute <= 0:
            return
        loop = asyncio.get_running_loop()
        now = loop.time()
        self._prune_quota(now)
        if len(self._quota_times) < self.quota_per_minute:
            return
        wait_s = self.quota_window_s - (now - self._quota_times[0])
        if wait_s <= 0:
            self._prune_quota(loop.time())
            return
        self._emit(
            "assrt.quota.wait",
            "ASSRT 已达 5 次/分钟上限，等待窗口腾出名额",
            log,
            used=len(self._quota_times),
            limit=f"{self.quota_per_minute}/分钟",
            wait_s=f"{wait_s:.1f}",
        )
        await asyncio.sleep(wait_s)
        self._prune_quota(loop.time())

    def _prune_quota(self, now: float) -> None:
        cutoff = now - self.quota_window_s
        self._quota_times = [item for item in self._quota_times if item > cutoff]

    # 仅统计已收到 HTTP 响应的 API 调用（ConnectError 未消耗服务端配额）
    def _record_quota(self, log: LogCallback | None = None) -> None:
        if self.quota_per_minute <= 0:
            return
        now = asyncio.get_running_loop().time()
        self._prune_quota(now)
        self._quota_times.append(now)
        used = len(self._quota_times)
        self._emit(
            "assrt.quota.local",
            "ASSRT 本地配额计数",
            log,
            used=used,
            remaining_est=max(0, self.quota_per_minute - used),
            limit=f"{self.quota_per_minute}/分钟",
        )

    # 原标题优先；短/泛化英文原标题则中文名优先，减少 Up→在云端 串片
    def _keywords(self, movie: MovieInfo) -> list[str]:
        prefer_zh = self._is_generic_short_english_title(movie)
        if prefer_zh:
            title_order = [movie.title_zh, movie.title, movie.original_title]
        else:
            title_order = [movie.original_title, movie.title, movie.title_zh]
        titles: list[str] = []
        for value in title_order:
            text = (value or "").strip()
            if text and len(text) >= 2 and text not in titles:
                titles.append(text)
        ordered: list[str] = []
        if movie.year:
            year = str(movie.year)
            ordered.extend(f"{title} {year}" for title in titles)
        ordered.extend(titles)
        return list(dict.fromkeys(ordered))

    @staticmethod
    def _is_generic_short_english_title(movie: MovieInfo) -> bool:
        original = (movie.original_title or movie.title or "").strip()
        if not original:
            return False
        if any("\u4e00" <= ch <= "\u9fff" for ch in original):
            return False
        folded = original.casefold()
        if folded in _GENERIC_SHORT_ENGLISH_TITLES:
            return True
        return len(original) <= 3

    def _emit(
        self,
        event: str,
        message: str,
        log: LogCallback | None = None,
        *,
        ui: bool | None = None,
        **fields: object,
    ) -> None:
        # 过程噪声默认只写 logger，不刷采集界面
        if ui is None:
            ui = not any(
                token in event
                for token in (
                    ".retry",
                    ".failover",
                    "quota.local",
                    "keyword.try",
                    "web.search.try",
                )
            )
        detail = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
        line = f"{event} {message}" + (f" {detail}" if detail else "")
        logger.info(line)
        if ui and log:
            log(line)

    def _movie_label(self, movie: MovieInfo | None = None, candidate: SubtitleCandidate | None = None) -> str | None:
        if movie:
            return (movie.title_zh or movie.title or movie.original_title or "").strip() or None
        if candidate:
            return (
                candidate.movie_title_zh
                or candidate.movie_title
                or candidate.subtitle_title
                or ""
            ).strip() or None
        return None

    # 下载失败：GUI 友好短句，完整异常仅 logger
    def _friendly_download_fail(self, exc: BaseException) -> str:
        text = str(exc)
        lower = text.lower()
        if "interrupted" in lower or "navigation" in lower or "打开详情页" in text:
            return "详情页打开失败，将重试或换候选"
        if "未找到" in text or "下载链接" in text or "未触发" in text or "浏览器不可用" in text:
            return "详情页未找到下载链接"
        if "timeout" in lower or "超时" in text:
            return "下载超时"
        if any(token in lower for token in ("proxy", "connect", "network", "ssl")) or "不可达" in text:
            return "网络不可达，请检查系统代理"
        short = " ".join(text.replace("\n", " ").split())
        if len(short) > 40:
            short = short[:40] + "…"
        return f"下载失败：{short}" if short else "下载失败"

    def _headers(self) -> dict[str, str]:
        return dict(_ASSRT_HEADERS)

    # 配置代理优先，否则读取 Windows 系统代理（对齐浏览器环境）
    def _resolve_browser_proxy(self) -> str | None:
        if self.proxy:
            return self.proxy
        return self._read_windows_system_proxy()

    # 从注册表读取系统代理并规范为 http://host:port
    @staticmethod
    def _read_windows_system_proxy() -> str | None:
        if sys.platform != "win32":
            return None
        try:
            import winreg
        except ImportError:
            return None
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            ) as key:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if not int(enabled or 0):
                    return None
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
        except OSError:
            return None
        raw = str(server or "").strip()
        if not raw:
            return None
        # 可能是 host:port 或 http=host:port;https=host:port
        candidate = raw
        if "=" in raw or ";" in raw:
            parts = [item.strip() for item in raw.split(";") if item.strip()]
            picked = ""
            for part in parts:
                lower = part.lower()
                if lower.startswith("https="):
                    picked = part.split("=", 1)[1].strip()
                    break
                if lower.startswith("http=") and not picked:
                    picked = part.split("=", 1)[1].strip()
            candidate = picked or parts[0].split("=", 1)[-1].strip()
        if "://" not in candidate:
            candidate = f"http://{candidate}"
        parsed = urlparse(candidate)
        if not parsed.hostname:
            return None
        port = f":{parsed.port}" if parsed.port else ""
        return f"http://{parsed.hostname}{port}"

    # 任务结束关闭 Playwright，避免浏览器泄漏
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
        self._browser_proxy = None

    # browser/context 在整次采集任务内复用
    async def _ensure_browser(self) -> None:
        if self._browser is not None and self._browser.is_connected():
            return
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        from playwright.async_api import async_playwright

        proxy = self._resolve_browser_proxy()
        self._browser_proxy = proxy
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
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
        self._browser = await self._playwright_instance.chromium.launch(**launch_kwargs)
        self._browser_context = await self._browser.new_context(
            user_agent=_ASSRT_HEADERS["User-Agent"],
            accept_downloads=True,
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

    # 默认走系统网络栈；Connect 失败重试时可强制 IPv4
    def _client(self, *, force_ipv4: bool = False) -> httpx.AsyncClient:
        transport = self.transport
        if transport is None and force_ipv4:
            transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
        return httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            proxy=self.proxy,
            transport=transport,
            headers=self._headers(),
        )

    def _host_of(self, base_url: str) -> str:
        return urlparse(base_url).netloc or base_url

    def _scheme_of(self, base_url: str) -> str:
        return urlparse(base_url).scheme or "https"

    # 统一为带 scheme 的 API 根路径
    def _with_scheme(self, base_url: str, scheme: str) -> str:
        raw = base_url if "://" in base_url else f"https://{base_url}"
        return urlparse(raw)._replace(scheme=scheme).geturl().rstrip("/")

    # HTTPS 按配置顺序；HTTP 备用域优先（同 IP 下 Host 决定成败）；已通 active 置顶
    def _api_bases(self) -> list[str]:
        roots: list[str] = []
        seen: set[str] = set()
        for item in [self.base_url, *self.fallback_base_urls, self._active_base_url]:
            if not item:
                continue
            https_root = self._with_scheme(item, "https")
            key = f"{self._host_of(https_root).lower()}{urlparse(https_root).path}".rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            roots.append(https_root)
        bases: list[str] = []
        for root in roots:
            https = self._with_scheme(root, "https")
            host = self._host_of(https).lower()
            if https not in bases and host not in self._skipped_https_hosts:
                bases.append(https)
        # HTTP：备用域（后加入的 fallback 根）优先于主域
        for root in reversed(roots):
            http = self._with_scheme(root, "http")
            if http not in bases:
                bases.append(http)
        active = self._active_base_url.rstrip("/")
        if active:
            if active in bases:
                bases.remove(active)
            bases.insert(0, active)
        return bases

    # HTTPS 证书主机名不匹配，或 HTTPS 连接被重置时无需反复重试
    def _is_ssl_hostname_mismatch(self, exc: Exception) -> bool:
        detail = self._exception_detail(exc).lower()
        return (
            "hostname mismatch" in detail
            or "certificate verify failed" in detail
            or "certificate_verify_failed" in detail
        )

    def _should_skip_https_retries(self, exc: Exception, base_url: str) -> bool:
        if self._scheme_of(base_url) != "https":
            return False
        if self._is_ssl_hostname_mismatch(exc):
            return True
        return isinstance(exc, httpx.ConnectError)

    def _mask_secret(self, text: str) -> str:
        return _TOKEN_QUERY_RE.sub(r"\1***", text)

    def _fallback_hint(self, tried_base: str) -> str:
        unused = [item for item in self.fallback_base_urls if item != tried_base]
        if unused:
            return (
                f"可改 ASSRT_API_BASE_URL={unused[0]} "
                f"（官方备用域名），或检查 HTTPS_PROXY/网络"
            )
        if tried_base not in {
            _FALLBACK_ASSRT_BASE.rstrip("/"),
            _FALLBACK_ASSRT_BASE.replace("https://", "http://").rstrip("/"),
        }:
            return (
                f"可将 ASSRT_API_BASE_URL 设为 {_FALLBACK_ASSRT_BASE} "
                f"（官方备用域名），或检查 HTTPS_PROXY/网络"
            )
        return "请检查 HTTPS_PROXY/网络，或确认 ASSRT_API_BASE_URL 是否正确"

    # 提取底层异常摘要（脱敏），便于区分连不上 / 读中断
    def _exception_detail(self, exc: Exception) -> str:
        parts: list[str] = []
        text = str(exc).strip()
        if text:
            parts.append(text)
        underlying = exc.__cause__ or exc.__context__
        if underlying is not None:
            nested = str(underlying).strip()
            if nested and nested not in parts:
                parts.append(nested)
        if not parts:
            return ""
        return self._mask_secret("；".join(parts))[:200]

    # 将瞬时网络异常整理为可读中文说明
    def _network_error_message(
        self,
        exc: Exception,
        *,
        base_url: str,
        endpoint: str,
        stage: str,
    ) -> str:
        host = self._host_of(base_url)
        target = self._mask_secret(f"{base_url}{endpoint}")
        name = type(exc).__name__
        hint = self._fallback_hint(base_url)
        scheme = self._scheme_of(base_url)
        detail = self._exception_detail(exc)
        detail_suffix = f"：{detail}" if detail else ""
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return (
                f"无法连接 ASSRT API 主机 {host}（{name}），"
                f"scheme={scheme} 目标 {target}{detail_suffix}。{hint}"
            )
        if isinstance(exc, httpx.ReadTimeout):
            return (
                f"ASSRT 已连通但响应超时（{name}）：{target}{detail_suffix}。"
                f"可增大超时或检查网络稳定性"
            )
        if isinstance(exc, httpx.RemoteProtocolError):
            return (
                f"ASSRT 连接中断（{name}）：{target}{detail_suffix}。"
                f"请稍后重试或检查代理"
            )
        return f"ASSRT {stage} 网络异常（{name}）：{target}{detail_suffix}。{hint}"

    def _payload_status(self, payload: dict) -> int:
        status = payload.get("status")
        if status in (None, 0):
            return 0
        try:
            return int(status)
        except (TypeError, ValueError):
            return -1

    # 解析 ASSRT JSON status 非 0 的业务错误
    def _raise_for_payload_status(self, payload: dict, *, keyword: str = "") -> None:
        status_code = self._payload_status(payload)
        if status_code == 0:
            return
        detail_raw = payload.get("error") or payload.get("message") or ""
        detail = f"：{detail_raw}" if detail_raw else ""
        if keyword and status_code == 101:
            detail = f"：q={keyword}{detail}"
        mapped = _ASSRT_STATUS_ERRORS.get(status_code)
        if mapped:
            error_type, template = mapped
            raise CollectorError(
                template.format(detail=detail),
                error_type,
                self.id,
            )
        raise CollectorError(
            f"ASSRT 返回业务错误 status={payload.get('status')}{detail}",
            ErrorType.PARSE_FAILED,
            self.id,
        )

    # 配额超限只记本地日志，不再请求 /user/quota（该接口本身占配额）
    def _log_quota_exceeded(
        self,
        log: LogCallback | None,
        payload: dict,
    ) -> None:
        self._emit(
            "assrt.quota.exceeded",
            "ASSRT 配额超限",
            log,
            status=self._payload_status(payload) or 30900,
            limit=f"{self.quota_per_minute}/分钟",
            share="token与IP共享",
        )

    # 当前 base 失败后切下一候选，或抛出终态网络错误
    def _failover_or_raise(
        self,
        *,
        stage: str,
        log: LogCallback | None,
        base_url: str,
        bases: list[str],
        base_index: int,
        endpoint: str,
        attempt: int,
        error_type: str,
        last_message: str,
        last_exc: Exception | None,
    ) -> bool:
        if base_index + 1 < len(bases):
            next_base = bases[base_index + 1]
            self._emit(
                f"{stage}.failover",
                (
                    f"{self._scheme_of(base_url)}://{self._host_of(base_url)} "
                    f"连续失败（{error_type}），切换 "
                    f"{self._scheme_of(next_base)}://{self._host_of(next_base)}"
                ),
                log,
                from_base=base_url,
                to_base=next_base,
            )
            return True
        self._emit(
            f"{stage}.fail",
            last_message + "；已停止重试",
            log,
            endpoint=endpoint,
            host=self._host_of(base_url),
            scheme=self._scheme_of(base_url),
            attempt=attempt,
            error_type=error_type,
        )
        raise CollectorError(
            last_message,
            ErrorType.NETWORK_UNREACHABLE,
            self.id,
        ) from last_exc

    async def _request_json(
        self,
        endpoint: str,
        params: dict[str, object],
        log: LogCallback | None = None,
        stage: str = "assrt.request",
        count_against_quota: bool = True,
        raise_status: bool = True,
    ) -> dict:
        last_exc: Exception | None = None
        last_message = ""
        bases = self._api_bases()
        for base_index, base_url in enumerate(bases):
            switch_to_fallback = False
            force_ipv4 = False
            for attempt in range(1, 4):
                await self._rate_limit()
                if count_against_quota:
                    await self._respect_quota(log)
                try:
                    async with self._client(force_ipv4=force_ipv4) as client:
                        response = await client.get(
                            f"{base_url}{endpoint}",
                            params={"token": self.token, **params},
                            headers=self._headers(),
                        )
                        if count_against_quota:
                            self._record_quota(log)
                        if response.status_code in {429, 509}:
                            raise CollectorError(
                                f"ASSRT HTTP {response.status_code} 限流/过载，主机 "
                                f"{self._host_of(base_url)}",
                                ErrorType.RATE_LIMITED,
                                self.id,
                            )
                        # 5xx：同 base 重试后切下一候选（避免 503 卡死在不可用 Host）
                        if response.status_code >= 500:
                            last_message = (
                                f"ASSRT HTTP {response.status_code} 服务端错误，"
                                f"scheme={self._scheme_of(base_url)} "
                                f"主机 {self._host_of(base_url)} 目标 "
                                f"{self._mask_secret(f'{base_url}{endpoint}')}"
                            )
                            last_exc = httpx.HTTPStatusError(
                                f"Server error '{response.status_code}'",
                                request=response.request,
                                response=response,
                            )
                            error_name = f"HTTP{response.status_code}"
                            if attempt < 3:
                                self._emit(
                                    f"{stage}.retry",
                                    last_message + f"；准备重试（{attempt}/3）",
                                    log,
                                    endpoint=endpoint,
                                    host=self._host_of(base_url),
                                    scheme=self._scheme_of(base_url),
                                    attempt=attempt,
                                    error_type=error_name,
                                )
                                await asyncio.sleep(0.2 * attempt)
                                continue
                            switch_to_fallback = self._failover_or_raise(
                                stage=stage,
                                log=log,
                                base_url=base_url,
                                bases=bases,
                                base_index=base_index,
                                endpoint=endpoint,
                                attempt=attempt,
                                error_type=error_name,
                                last_message=last_message,
                                last_exc=last_exc,
                            )
                            break
                        response.raise_for_status()
                        payload = response.json()
                    if base_url != self._active_base_url:
                        self._emit(
                            f"{stage}.fallback",
                            "ASSRT 已切换到备用 API 主机",
                            log,
                            host=self._host_of(base_url),
                            scheme=self._scheme_of(base_url),
                            base_url=base_url,
                        )
                        self._active_base_url = base_url
                    payload_dict = payload if isinstance(payload, dict) else {}
                    if raise_status and self._payload_status(payload_dict) == 30900:
                        self._log_quota_exceeded(log, payload_dict)
                    if raise_status:
                        self._raise_for_payload_status(
                            payload_dict,
                            keyword=str(params.get("q") or ""),
                        )
                    return payload_dict
                except CollectorError:
                    raise
                except _TRANSIENT_HTTPX_ERRORS as exc:
                    last_exc = exc
                    last_message = self._network_error_message(
                        exc, base_url=base_url, endpoint=endpoint, stage=stage
                    )
                    # HTTPS 连不上或证书不匹配：立即切下一候选
                    if self._should_skip_https_retries(exc, base_url):
                        self._skipped_https_hosts.add(self._host_of(base_url).lower())
                        reason = (
                            "证书主机名不匹配，跳过该 HTTPS 候选"
                            if self._is_ssl_hostname_mismatch(exc)
                            else "HTTPS 无法连接，跳过该候选"
                        )
                        self._emit(
                            f"{stage}.retry",
                            last_message + f"；{reason}",
                            log,
                            endpoint=endpoint,
                            host=self._host_of(base_url),
                            scheme=self._scheme_of(base_url),
                            attempt=attempt,
                            error_type=type(exc).__name__,
                        )
                        switch_to_fallback = self._failover_or_raise(
                            stage=stage,
                            log=log,
                            base_url=base_url,
                            bases=bases,
                            base_index=base_index,
                            endpoint=endpoint,
                            attempt=attempt,
                            error_type=type(exc).__name__,
                            last_message=last_message,
                            last_exc=exc,
                        )
                        break
                    if attempt < 3:
                        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                            force_ipv4 = True
                        self._emit(
                            f"{stage}.retry",
                            last_message + f"；准备重试（{attempt}/3）",
                            log,
                            endpoint=endpoint,
                            host=self._host_of(base_url),
                            scheme=self._scheme_of(base_url),
                            attempt=attempt,
                            error_type=type(exc).__name__,
                            force_ipv4=force_ipv4 or None,
                        )
                        await asyncio.sleep(0.2 * attempt)
                        continue
                    # 任意瞬时网络错误都切下一候选（含 ReadError）
                    switch_to_fallback = self._failover_or_raise(
                        stage=stage,
                        log=log,
                        base_url=base_url,
                        bases=bases,
                        base_index=base_index,
                        endpoint=endpoint,
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        last_message=last_message,
                        last_exc=exc,
                    )
                    break
                except httpx.HTTPError as exc:
                    error_text = self._mask_secret(str(exc) or repr(exc))
                    message = (
                        f"ASSRT HTTP 错误（{type(exc).__name__}）："
                        f"{base_url}{endpoint} — {error_text}"
                    )
                    raise CollectorError(
                        message,
                        ErrorType.NETWORK_UNREACHABLE,
                        self.id,
                    ) from exc
            if switch_to_fallback:
                continue
        raise CollectorError(
            last_message or f"ASSRT 请求失败：{last_exc!r}",
            ErrorType.NETWORK_UNREACHABLE,
            self.id,
        )

    def _lang_flags(self, raw: dict) -> dict:
        lang = raw.get("lang") if isinstance(raw.get("lang"), dict) else {}
        flags = lang.get("langlist") if isinstance(lang.get("langlist"), dict) else {}
        return flags

    # 官方 langlist：langdou 或 简体+英文；否则回退 desc
    def _is_bilingual_lang(self, raw: dict) -> bool:
        flags = self._lang_flags(raw)
        if flags.get("langdou") or (flags.get("langchs") and flags.get("langeng")):
            return True
        desc = chinese_language_label((raw.get("lang") or {}).get("desc") or "")
        return "双语" in desc or desc == "中英双语"

    def _is_traditional_only(self, raw: dict) -> bool:
        flags = self._lang_flags(raw)
        if flags.get("langdou") or flags.get("langchs"):
            return False
        if flags.get("langcht") and not flags.get("langeng"):
            return True
        desc = chinese_language_label((raw.get("lang") or {}).get("desc") or "")
        return desc == "繁体中文"

    def _is_vobsub_pack(self, raw: dict) -> bool:
        subtype = str(raw.get("subtype") or "").lower()
        return "vobsub" in subtype or subtype in {"idx", "sub"}

    def _file_names_of(self, raw: dict) -> list[str]:
        names = [raw.get("filename")]
        filelist = raw.get("filelist") or []
        names.extend(item.get("f") for item in filelist if isinstance(item, dict))
        return [str(item) for item in names if item]

    def _has_supported_subtitle_file(self, raw: dict) -> bool:
        names = self._file_names_of(raw)
        if any(detect_subtitle_format(name) in {"ass", "srt"} for name in names):
            return True
        filelist = raw.get("filelist") or []
        if filelist:
            return False
        return detect_subtitle_format(str(raw.get("subtype") or "")) in {"ass", "srt"}

    def _language_type_of(self, raw: dict) -> str:
        flags = self._lang_flags(raw)
        if flags.get("langdou") or (flags.get("langchs") and flags.get("langeng")):
            return "中英双语"
        return chinese_language_label((raw.get("lang") or {}).get("desc") or "")

    # 搜索阶段丢掉明显不可用包，避免浪费 detail 配额
    def _is_qualified_search_hit(self, raw: dict) -> bool:
        if not isinstance(raw, dict) or not raw.get("id"):
            return False
        if raw.get("vote_machine_translate"):
            return False
        if self._is_vobsub_pack(raw):
            return False
        if self._is_traditional_only(raw):
            return False
        if not self._has_supported_subtitle_file(raw):
            return False
        return self._is_bilingual_lang(raw)

    # 网页语言标签：须同时含「双语」与「简」
    def _is_web_bilingual_simplified(self, lang: str) -> bool:
        text = (lang or "").strip()
        return "双语" in text and "简" in text

    # 详情页路径：id=628615 → /xml/sub/628/628615.xml
    def _detail_path(self, subtitle_id: str | int) -> str:
        sid = int(str(subtitle_id).strip())
        return f"/xml/sub/{sid // 1000}/{sid}.xml"

    def _detail_url_for(self, subtitle_id: str | int, site_base: str | None = None) -> str:
        base = (site_base or self._active_site_url or self.site_base_url).rstrip("/")
        return f"{base}{self._detail_path(subtitle_id)}"

    # 站点候选：配置域 → 备用域，HTTPS 优先再试 HTTP；active 置顶
    def _site_bases(self) -> list[str]:
        roots: list[str] = []
        seen: set[str] = set()
        for item in [self.site_base_url, *self.fallback_site_urls, self._active_site_url]:
            if not item:
                continue
            host_key = self._host_of(self._with_scheme(item, "https")).lower()
            if host_key in seen:
                continue
            seen.add(host_key)
            roots.append(self._with_scheme(item, "https"))
        bases: list[str] = []
        for root in roots:
            https = self._with_scheme(root, "https")
            http = self._with_scheme(root, "http")
            host = self._host_of(https).lower()
            if https not in bases and host not in self._skipped_https_hosts:
                bases.append(https)
            if http not in bases:
                bases.append(http)
        active = (self._active_site_url or "").rstrip("/")
        if active:
            if active in bases:
                bases.remove(active)
            bases.insert(0, active)
        return bases

    # 拉取站点 HTML/二进制（不占 API 配额）
    async def _request_site(
        self,
        path_or_url: str,
        *,
        log: LogCallback | None = None,
        stage: str = "assrt.web.request",
        referer: str | None = None,
        params: dict[str, object] | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        absolute = "://" in path_or_url
        last_exc: Exception | None = None
        last_message = ""
        bases = [""] if absolute else self._site_bases()
        for base_index, base_url in enumerate(bases):
            target = path_or_url if absolute else f"{base_url.rstrip('/')}{path_or_url}"
            force_ipv4 = False
            for attempt in range(1, 4):
                await self._rate_limit()
                headers = {
                    **self._headers(),
                    "Accept": accept
                    or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
                if referer:
                    headers["Referer"] = referer
                try:
                    async with self._client(force_ipv4=force_ipv4) as client:
                        response = await client.get(target, params=params, headers=headers)
                    if response.status_code in {429, 509}:
                        raise CollectorError(
                            f"ASSRT 站点 HTTP {response.status_code} 限流，主机 "
                            f"{self._host_of(str(response.url))}",
                            ErrorType.RATE_LIMITED,
                            self.id,
                        )
                    if response.status_code >= 500:
                        last_message = (
                            f"ASSRT 站点 HTTP {response.status_code}，"
                            f"主机 {self._host_of(str(response.url))}"
                        )
                        last_exc = httpx.HTTPStatusError(
                            last_message,
                            request=response.request,
                            response=response,
                        )
                        if attempt < 3:
                            await asyncio.sleep(0.2 * attempt)
                            continue
                        if not absolute and base_index + 1 < len(bases):
                            next_base = bases[base_index + 1]
                            self._emit(
                                f"{stage}.failover",
                                "ASSRT 站点失败，切换备用站点",
                                log,
                                from_base=base_url,
                                to_base=next_base,
                                status=response.status_code,
                            )
                            break
                        raise CollectorError(last_message, ErrorType.NETWORK_UNREACHABLE, self.id)
                    response.raise_for_status()
                    if not absolute and base_url and base_url != self._active_site_url:
                        self._emit(
                            f"{stage}.fallback",
                            "ASSRT 已切换到备用站点",
                            log,
                            site=base_url,
                        )
                        self._active_site_url = base_url
                    return response
                except CollectorError:
                    raise
                except _TRANSIENT_HTTPX_ERRORS as exc:
                    last_exc = exc
                    host = self._host_of(target)
                    last_message = (
                        f"ASSRT 站点网络异常（{type(exc).__name__}），主机 {host}："
                        f"{self._exception_detail(exc)}"
                    )
                    if not absolute and self._should_skip_https_retries(exc, base_url or target):
                        self._skipped_https_hosts.add(self._host_of(base_url or target).lower())
                        if base_index + 1 < len(bases):
                            self._emit(
                                f"{stage}.failover",
                                last_message + "；切换备用站点",
                                log,
                                from_base=base_url,
                                to_base=bases[base_index + 1],
                            )
                            break
                        raise CollectorError(
                            last_message,
                            ErrorType.NETWORK_UNREACHABLE,
                            self.id,
                        ) from exc
                    if attempt < 3:
                        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                            force_ipv4 = True
                        await asyncio.sleep(0.2 * attempt)
                        continue
                    if not absolute and base_index + 1 < len(bases):
                        self._emit(
                            f"{stage}.failover",
                            last_message + "；切换备用站点",
                            log,
                            from_base=base_url,
                            to_base=bases[base_index + 1],
                        )
                        break
                    raise CollectorError(
                        last_message,
                        ErrorType.NETWORK_UNREACHABLE,
                        self.id,
                    ) from exc
                except httpx.HTTPError as exc:
                    raise CollectorError(
                        f"ASSRT 站点 HTTP 错误（{type(exc).__name__}）："
                        f"{self._mask_secret(str(exc))}",
                        ErrorType.NETWORK_UNREACHABLE,
                        self.id,
                    ) from exc
            else:
                continue
            continue
        raise CollectorError(
            last_message or f"ASSRT 站点请求失败：{last_exc!r}",
            ErrorType.NETWORK_UNREACHABLE,
            self.id,
        )

    def _strip_html(self, text: str) -> str:
        return re.sub(r"<[^>]+>", " ", text or "")

    # 解析搜索页卡片：详情链接 + 语言/格式/下载次数/版本
    def _parse_search_html(self, html: str, site_base: str) -> list[dict]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise CollectorError(
                "缺少 BeautifulSoup，无法解析 ASSRT 搜索页",
                ErrorType.PARSE_FAILED,
                self.id,
            ) from exc
        soup = BeautifulSoup(html or "", "html.parser")
        hits: list[dict] = []
        seen_ids: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            match = _DETAIL_HREF_RE.search(href)
            if not match:
                continue
            subtitle_id = match.group(2)
            if subtitle_id in seen_ids:
                continue
            seen_ids.add(subtitle_id)
            container = anchor
            for _ in range(6):
                parent = container.parent
                if parent is None:
                    break
                container = parent
                if "下载次数" in container.get_text(" ", strip=True):
                    break
            block_html = str(container)
            block_text = self._strip_html(block_html)
            lang_match = _LANG_RE.search(block_text)
            format_match = _FORMAT_RE.search(block_text)
            version_match = _VERSION_RE.search(block_text)
            count_match = _DOWNLOAD_COUNT_RE.search(block_text)
            title = anchor.get_text(" ", strip=True) or (version_match.group(1).strip() if version_match else "")
            version = version_match.group(1).strip() if version_match else ""
            lang = lang_match.group(1).strip() if lang_match else ""
            subtype = format_match.group(1).strip() if format_match else ""
            detail_url = urljoin(site_base.rstrip("/") + "/", href)
            file_hint = ""
            file_match = re.search(r"字幕文件名\s*[：:]\s*([^\n]+)", block_text)
            if file_match:
                file_hint = file_match.group(1).strip()
            hits.append(
                {
                    "id": subtitle_id,
                    "title": title or version,
                    "version": version,
                    "lang": lang,
                    "subtype": subtype,
                    "down_count": int(count_match.group(1)) if count_match else 0,
                    "detail_url": detail_url,
                    "filename": file_hint or version or title,
                }
            )
        return hits

    # 解析详情页：整包「下载字幕」优先，其次单文件 /download/ 链接
    def _parse_detail_downloads(self, html: str, site_base: str) -> list[tuple[str, str]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise CollectorError(
                "缺少 BeautifulSoup，无法解析 ASSRT 详情页",
                ErrorType.PARSE_FAILED,
                self.id,
            ) from exc
        soup = BeautifulSoup(html or "", "html.parser")
        package: list[tuple[str, str]] = []
        singles: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(bucket: list[tuple[str, str]], href: str, name: str) -> None:
            url = urljoin(site_base.rstrip("/") + "/", href)
            if url in seen:
                return
            seen.add(url)
            file_name = name or unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "subtitle"
            bucket.append((url, file_name))

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            if not _DOWNLOAD_HREF_RE.search(href):
                continue
            text = anchor.get_text(" ", strip=True)
            name = text
            if "下载字幕" in text:
                fname_match = _FILENAME_RE.search(self._strip_html(html))
                if fname_match:
                    name = fname_match.group(1).strip()
                add(package, href, name)
            elif _SUBTITLE_EXT_RE.search(href) or _SUBTITLE_EXT_RE.search(text):
                add(singles, href, text)
            else:
                add(singles, href, text)
        if not package and not singles:
            for match in _DOWNLOAD_HREF_RE.finditer(html or ""):
                href = match.group(0)
                add(package if href.lower().endswith(".zip") else singles, href, "")
        return package + singles

    # 用标题/版本/文件名判断错年（避免搜索关键词年份污染 description）
    def _raw_year_conflict(self, raw: dict, movie: MovieInfo) -> bool:
        if not movie.year:
            return False
        text = " ".join(
            str(part)
            for part in [
                raw.get("title"),
                raw.get("version"),
                raw.get("filename"),
                raw.get("native_name"),
                raw.get("videoname"),
                raw.get("detail_url"),
                *self._file_names_of(raw),
            ]
            if part
        )
        years = extract_years(text)
        if not years:
            return False
        return movie.year not in years

    # 年份冲突则丢弃并记日志
    def _keep_by_year(
        self,
        raw: dict,
        movie: MovieInfo,
        log: LogCallback | None,
    ) -> bool:
        if not self._raw_year_conflict(raw, movie):
            return True
        self._emit(
            "assrt.web.year.skip",
            "ASSRT 因年份冲突丢弃候选",
            log,
            id=raw.get("id"),
            title=raw.get("title") or raw.get("native_name") or raw.get("version") or "",
            movie_year=movie.year,
        )
        return False

    def _map_web_item(self, raw: dict, movie: MovieInfo, keyword: str) -> SubtitleCandidate:
        file_names = [name for name in [raw.get("filename"), raw.get("version")] if name]
        language = str(raw.get("lang") or "")
        if self._is_web_bilingual_simplified(language):
            language_type = "中英双语"
        else:
            language_type = chinese_language_label(language) or language
        subtitle_format = detect_subtitle_format(" ".join(file_names)) or detect_subtitle_format(
            str(raw.get("subtype") or "")
        )
        title = str(raw.get("title") or raw.get("version") or raw.get("filename") or "")
        return SubtitleCandidate(
            provider=self.id,
            provider_subtitle_id=str(raw.get("id") or ""),
            movie_id=movie.movie_id,
            movie_title=movie.title,
            movie_original_title=movie.original_title,
            movie_title_zh=movie.title_zh,
            movie_year=movie.year,
            subtitle_title=title,
            language_type=language_type,
            subtitle_format=subtitle_format,
            download_count=int(raw.get("down_count") or 0),
            rating=0.0,
            detail_url=str(raw.get("detail_url") or self._detail_url_for(raw.get("id") or "")),
            description=format_chinese_description(
                ("搜索关键词", keyword),
                ("字幕标题", title),
                ("版本", raw.get("version")),
                ("语言", language),
                ("格式", raw.get("subtype") or subtitle_format),
                ("文件名", file_names),
            ),
            file_names=file_names,
            raw={**raw, "source": "web"},
        )

    def _map_item(self, raw: dict, movie: MovieInfo, keyword: str) -> SubtitleCandidate:
        file_names = self._file_names_of(raw)
        language = self._language_type_of(raw)
        text = " ".join(
            str(part)
            for part in [
                raw.get("native_name"),
                raw.get("videoname"),
                raw.get("title"),
                raw.get("filename"),
                raw.get("subtype"),
                raw.get("release_site"),
                (raw.get("lang") or {}).get("desc"),
                *file_names,
            ]
            if part
        )
        subtitle_format = detect_subtitle_format(" ".join(file_names)) or detect_subtitle_format(text)
        subtitle_id = raw.get("id")
        detail_url = self._detail_url_for(subtitle_id) if subtitle_id else ""
        return SubtitleCandidate(
            provider=self.id,
            provider_subtitle_id=str(subtitle_id or ""),
            movie_id=movie.movie_id,
            movie_title=movie.title,
            movie_original_title=movie.original_title,
            movie_title_zh=movie.title_zh,
            movie_year=movie.year,
            subtitle_title=raw.get("title") or raw.get("native_name") or raw.get("filename") or "",
            language_type=language,
            subtitle_format=subtitle_format,
            download_count=int(raw.get("down_count") or raw.get("download_count") or 0),
            rating=float(raw.get("vote_score") or 0),
            detail_url=detail_url,
            description=format_chinese_description(
                ("搜索关键词", keyword),
                ("字幕标题", raw.get("title") or raw.get("native_name") or raw.get("filename")),
                ("视频名称", raw.get("videoname")),
                ("字幕类型", raw.get("subtype")),
                ("发布站点", raw.get("release_site")),
                ("语言", language),
                ("格式", subtitle_format),
                ("文件名", file_names),
            ),
            file_names=file_names,
            raw={**raw, "source": "api"},
        )

    async def _search_via_web(
        self,
        movie: MovieInfo,
        log: LogCallback | None = None,
    ) -> list[SubtitleCandidate]:
        result: list[SubtitleCandidate] = []
        for keyword in self._keywords(movie):
            self._emit(
                "assrt.web.search.try",
                "ASSRT 网页搜索",
                log,
                searchword=keyword,
                year=movie.year or None,
                site=self._active_site_url or self.site_base_url,
            )
            response = await self._request_site(
                "/sub/",
                log=log,
                stage="assrt.web.search",
                params={"searchword": keyword},
            )
            site_base = f"{response.url.scheme}://{response.url.host}"
            raw_hits = self._parse_search_html(response.text, site_base)
            skipped_lang = 0
            skipped_year = 0
            qualified: list[SubtitleCandidate] = []
            for raw in raw_hits:
                if not self._is_web_bilingual_simplified(str(raw.get("lang") or "")):
                    skipped_lang += 1
                    continue
                if not self._keep_by_year(raw, movie, log):
                    skipped_year += 1
                    continue
                candidate = self._map_web_item(raw, movie, keyword)
                if not candidate.provider_subtitle_id:
                    continue
                qualified.append(candidate)
            if qualified:
                self._emit(
                    "assrt.web.search.ok",
                    "ASSRT 网页搜索成功",
                    log,
                    keyword=keyword,
                    count=len(qualified),
                    total=len(raw_hits),
                    skipped_lang=skipped_lang,
                    skipped_year=skipped_year,
                )
                for item in qualified[:15]:
                    self._emit(
                        "assrt.web.search.hit",
                        "ASSRT 网页搜索命中",
                        log,
                        id=item.provider_subtitle_id,
                        title=item.subtitle_title,
                        lang=item.language_type,
                        format=item.subtitle_format,
                        down_count=item.download_count,
                        detail_url=item.detail_url,
                    )
                result.extend(qualified)
                break
            self._emit(
                "assrt.web.search.empty",
                "ASSRT 网页无合格双语结果",
                log,
                keyword=keyword,
                total=len(raw_hits),
                skipped_lang=skipped_lang,
                skipped_year=skipped_year,
            )
        return result

    async def _search_via_api(
        self,
        movie: MovieInfo,
        log: LogCallback | None = None,
    ) -> list[SubtitleCandidate]:
        result: list[SubtitleCandidate] = []
        for keyword in self._keywords(movie):
            self._emit(
                "assrt.search.keyword.try",
                "ASSRT 尝试关键词搜索",
                log,
                keyword=keyword,
                q=keyword,
                cnt=15,
                pos=0,
                filelist=1,
                base_url=self._active_base_url,
                host=self._host_of(self._active_base_url),
                scheme=self._scheme_of(self._active_base_url),
            )
            payload = await self._request_json(
                "/sub/search",
                {"q": keyword, "cnt": 15, "pos": 0, "filelist": 1},
                log=log,
                stage="assrt.search",
            )
            sub_meta = payload.get("sub") or {}
            subs = [item for item in (sub_meta.get("subs") or []) if isinstance(item, dict)]
            qualified_raw = [
                item
                for item in subs
                if self._is_qualified_search_hit(item) and self._keep_by_year(item, movie, log)
            ]
            mapped = [self._map_item(raw, movie, keyword) for raw in qualified_raw]
            hits = [item for item in mapped if item.provider_subtitle_id]
            if hits:
                self._emit(
                    "assrt.search.ok",
                    "ASSRT 搜索成功",
                    log,
                    via="api",
                    keyword=sub_meta.get("keyword") or keyword,
                    count=len(hits),
                    movie=self._movie_label(movie),
                )
                for item in hits[:3]:
                    self._emit(
                        "assrt.search.hit",
                        "ASSRT 搜索命中",
                        log,
                        id=item.provider_subtitle_id,
                        title=item.subtitle_title,
                        lang=item.language_type,
                        movie=self._movie_label(movie),
                    )
                result.extend(hits)
                break
            self._emit(
                "assrt.search.empty",
                "ASSRT 无合格双语搜索结果",
                log,
                keyword=sub_meta.get("keyword") or keyword,
                count=len(subs),
                movie=self._movie_label(movie),
            )
        return result

    async def search(
        self,
        movie: MovieInfo,
        log: LogCallback | None = None,
    ) -> list[SubtitleCandidate]:
        if not self.token:
            return []
        # 网页 httpx 在本环境长期不可达，直接 API，避免每片 failover 空转
        self._emit(
            "assrt.search.via",
            "ASSRT 本轮直接 API 搜索",
            log,
            movie=self._movie_label(movie),
            host=self._host_of(self._active_base_url),
        )
        return await self._search_via_api(movie, log=log)

    async def download(self, candidate: SubtitleCandidate, context: DownloadContext) -> list[DownloadedPayload]:
        if not self.token:
            raise CollectorError("缺少 ASSRT_TOKEN", ErrorType.PROVIDER_DISABLED, self.id)
        if not candidate.provider_subtitle_id:
            raise CollectorError("ASSRT 缺少字幕 ID", ErrorType.DOWNLOAD_FAILED, self.id)
        detail_url = candidate.detail_url or self._detail_url_for(candidate.provider_subtitle_id)
        movie_label = self._movie_label(candidate=candidate)
        self._emit(
            "assrt.download.start",
            "ASSRT 开始下载",
            log=context.log,
            id=candidate.provider_subtitle_id,
            host=self._host_of(detail_url),
            movie=movie_label,
        )
        # 代理细节仅写 logger
        logger.info(
            "assrt.download.start.detail id=%s proxy=%s detail_url=%s",
            candidate.provider_subtitle_id,
            self._resolve_browser_proxy() or "direct",
            detail_url,
        )
        try:
            return await self._download_via_playwright(candidate, context, detail_url)
        except CollectorError as exc:
            friendly = self._friendly_download_fail(exc)
            self._emit(
                "assrt.download.fail",
                friendly,
                log=context.log,
                id=candidate.provider_subtitle_id,
                movie=movie_label,
            )
            logger.info("assrt.download.fail.detail id=%s error=%s", candidate.provider_subtitle_id, exc)
            raise CollectorError(friendly, exc.error_type, self.id) from exc
        except Exception as exc:  # noqa: BLE001 - 统一归类
            friendly = self._friendly_download_fail(exc)
            self._emit(
                "assrt.download.fail",
                friendly,
                log=context.log,
                id=candidate.provider_subtitle_id,
                movie=movie_label,
            )
            logger.info("assrt.download.fail.detail id=%s error=%r", candidate.provider_subtitle_id, exc)
            raise CollectorError(friendly, ErrorType.NETWORK_UNREACHABLE, self.id) from exc

    # 首选站点详情 URL；仅当首选失败时再试一个不同 host
    def _detail_urls_for_download(self, candidate: SubtitleCandidate, preferred: str) -> list[str]:
        urls: list[str] = []
        seen_hosts: set[str] = set()
        primary = preferred or self._detail_url_for(
            candidate.provider_subtitle_id,
            self.site_base_url,
        )
        for item in [primary, self._detail_url_for(candidate.provider_subtitle_id, self.site_base_url)]:
            if not item:
                continue
            host = self._host_of(item).lower()
            if host in seen_hosts:
                continue
            seen_hosts.add(host)
            urls.append(item)
        for base in self._site_bases():
            host = self._host_of(base).lower()
            if host in seen_hosts:
                continue
            urls.append(self._detail_url_for(candidate.provider_subtitle_id, base))
            break
        return urls

    # 打开详情：允许重定向；navigation interrupted 时若已落到目标 path 则视为成功
    async def _goto_detail_page(self, page, page_url: str, expected_path: str) -> str:
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:  # noqa: BLE001 - 可能是重定向打断
            current = str(getattr(page, "url", "") or "")
            if expected_path and expected_path in current:
                return current
            message = str(exc)
            if "interrupted" in message.lower() and expected_path and expected_path in message:
                # 另一导航目标已是正确详情 path
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15_000)
                except Exception:
                    pass
                current = str(getattr(page, "url", "") or "")
                if expected_path in current:
                    return current
            raise CollectorError(
                f"打开详情页失败（{type(exc).__name__}）：{exc}",
                ErrorType.NETWORK_UNREACHABLE,
                self.id,
            ) from exc
        final_url = str(page.url or page_url)
        if expected_path and expected_path not in final_url:
            raise CollectorError(
                f"打开详情页失败：最终地址不符 {final_url}",
                ErrorType.NETWORK_UNREACHABLE,
                self.id,
            )
        return final_url

    # Playwright 打开详情页并点击下载
    async def _download_via_playwright(
        self,
        candidate: SubtitleCandidate,
        context: DownloadContext,
        detail_url: str,
    ) -> list[DownloadedPayload]:
        await self._ensure_browser()
        if not self._browser_context:
            raise CollectorError(
                "ASSRT Playwright 浏览器不可用",
                ErrorType.NETWORK_UNREACHABLE,
                self.id,
            )
        expected_path = self._detail_path(candidate.provider_subtitle_id)
        page = await self._browser_context.new_page()
        last_message = ""
        try:
            for page_url in self._detail_urls_for_download(candidate, detail_url):
                try:
                    final_url = await self._goto_detail_page(page, page_url, expected_path)
                except CollectorError as exc:
                    last_message = str(exc)
                    continue
                host = self._host_of(final_url)
                if host:
                    self._active_site_url = f"{urlparse(final_url).scheme}://{host}"
                payload = await self._click_download_on_page(page, final_url, candidate, context)
                if payload:
                    return payload
                last_message = "详情页未触发有效下载"
            raise CollectorError(
                last_message or "ASSRT Playwright 下载失败",
                ErrorType.NETWORK_UNREACHABLE,
                self.id,
            )
        finally:
            try:
                await page.close()
            except Exception:
                pass

    # 双语单文件优先，再整包「下载字幕」，再其它单文件
    async def _click_download_on_page(
        self,
        page,
        page_url: str,
        candidate: SubtitleCandidate,
        context: DownloadContext,
    ) -> list[DownloadedPayload] | None:
        anchors = page.locator('a[href*="/download/"]')
        count = await anchors.count()
        if count <= 0:
            return None
        bilingual_indexes: list[int] = []
        package_indexes: list[int] = []
        other_indexes: list[int] = []
        for index in range(count):
            anchor = anchors.nth(index)
            text = (await anchor.inner_text()).strip()
            href = str(await anchor.get_attribute("href") or "")
            blob = f"{text} {unquote(href)}"
            if "下载字幕" in text:
                package_indexes.append(index)
            elif _BILINGUAL_NAME_RE.search(blob):
                bilingual_indexes.append(index)
            elif _SUBTITLE_EXT_RE.search(href) or _SUBTITLE_EXT_RE.search(text) or href:
                other_indexes.append(index)
        for index in bilingual_indexes + package_indexes + other_indexes:
            anchor = anchors.nth(index)
            text = (await anchor.inner_text()).strip()
            href = str(await anchor.get_attribute("href") or "")
            try:
                async with page.expect_download(timeout=60_000) as download_info:
                    await anchor.click(timeout=15_000)
                download = await download_info.value
                failure = await download.failure()
                if failure:
                    continue
                file_name = (
                    download.suggested_filename
                    or text
                    or unquote(urlparse(href).path.rsplit("/", 1)[-1])
                    or "subtitle"
                )
                if "下载字幕" in file_name:
                    file_name = unquote(urlparse(href).path.rsplit("/", 1)[-1]) or "subtitle.zip"
                temp_path = await download.path()
                if temp_path:
                    content = Path(temp_path).read_bytes()
                else:
                    with tempfile.NamedTemporaryFile(delete=False) as handle:
                        temp_name = handle.name
                    await download.save_as(temp_name)
                    content = Path(temp_name).read_bytes()
                    Path(temp_name).unlink(missing_ok=True)
                if not content:
                    continue
                host = urlparse(page_url).netloc or self._host_of(self.site_base_url)
                self._emit(
                    "assrt.download.ok",
                    "ASSRT 下载成功",
                    log=context.log,
                    id=candidate.provider_subtitle_id,
                    file=file_name,
                    size=str(len(content)),
                    host=host,
                    movie=self._movie_label(candidate=candidate),
                )
                return [
                    DownloadedPayload(
                        file_name=file_name,
                        content=content,
                        source_url=urljoin(page_url, href) if href else page_url,
                        content_type="application/octet-stream",
                    )
                ]
            except Exception:  # noqa: BLE001 - 换下一链接
                continue
        return None

