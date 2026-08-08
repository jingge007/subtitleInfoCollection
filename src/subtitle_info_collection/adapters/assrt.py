from __future__ import annotations

import asyncio
import logging
from urllib.parse import urljoin, urlparse

import httpx

from ..errors import CollectorError, ErrorType
from ..engines.scorer import build_movie_search_keywords
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
        "ASSRT API 配额超限（约 20 次/分钟，status=30900），请降低请求频率后重试",
    ),
}


class AssrtProvider:
    id = "assrt"
    download_supported = True

    def __init__(
        self,
        token: str = "",
        base_url: str = _DEFAULT_ASSRT_BASE,
        request_interval_ms: int = 500,
        timeout: float = 30,
        proxy: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        fallback_base_urls: list[str] | None = None,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.request_interval_ms = request_interval_ms
        self.timeout = timeout
        self.proxy = proxy
        self.transport = transport
        self._last_request = 0.0
        # 主域失败后尝试的备用 API 根路径（不含 endpoint）
        if fallback_base_urls is not None:
            self.fallback_base_urls = [item.rstrip("/") for item in fallback_base_urls if item]
        else:
            fallbacks: list[str] = []
            if self.base_url != _FALLBACK_ASSRT_BASE.rstrip("/"):
                fallbacks.append(_FALLBACK_ASSRT_BASE.rstrip("/"))
            self.fallback_base_urls = fallbacks
        self._active_base_url = self.base_url

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

    # 搜索关键词含原标题与「标题+年份」变体
    def _keywords(self, movie: MovieInfo) -> list[str]:
        return build_movie_search_keywords(movie)

    def _emit(
        self,
        event: str,
        message: str,
        log: LogCallback | None = None,
        **fields: object,
    ) -> None:
        detail = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
        line = f"{event} {message}" + (f" {detail}" if detail else "")
        logger.info(line)
        if log:
            log(line)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            proxy=self.proxy,
            transport=self.transport,
        )

    def _host_of(self, base_url: str) -> str:
        return urlparse(base_url).netloc or base_url

    def _api_bases(self) -> list[str]:
        bases = [self._active_base_url]
        for item in [self.base_url, *self.fallback_base_urls]:
            if item and item not in bases:
                bases.append(item)
        return bases

    def _fallback_hint(self, tried_base: str) -> str:
        unused = [item for item in self.fallback_base_urls if item != tried_base]
        if unused:
            return (
                f"可改 ASSRT_API_BASE_URL={unused[0]} "
                f"（官方备用域名），或检查 HTTPS_PROXY/网络"
            )
        if tried_base != _FALLBACK_ASSRT_BASE.rstrip("/"):
            return (
                f"可将 ASSRT_API_BASE_URL 设为 {_FALLBACK_ASSRT_BASE} "
                f"（官方备用域名），或检查 HTTPS_PROXY/网络"
            )
        return "请检查 HTTPS_PROXY/网络，或确认 ASSRT_API_BASE_URL 是否正确"

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
        target = f"{base_url}{endpoint}"
        name = type(exc).__name__
        hint = self._fallback_hint(base_url)
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return (
                f"无法连接 ASSRT API 主机 {host}（{name}），目标 {target}。"
                f"{hint}"
            )
        if isinstance(exc, httpx.ReadTimeout):
            return f"ASSRT 已连通但响应超时（{name}）：{target}。可增大超时或检查网络稳定性"
        if isinstance(exc, httpx.RemoteProtocolError):
            return f"ASSRT 连接中断（{name}）：{target}。请稍后重试或检查代理"
        return f"ASSRT {stage} 网络异常（{name}）：{target}。{hint}"

    # 解析 ASSRT JSON status 非 0 的业务错误
    def _raise_for_payload_status(self, payload: dict, *, keyword: str = "") -> None:
        status = payload.get("status")
        if status in (None, 0):
            return
        try:
            status_code = int(status)
        except (TypeError, ValueError):
            status_code = -1
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
            f"ASSRT 返回业务错误 status={status}{detail}",
            ErrorType.PARSE_FAILED,
            self.id,
        )

    async def _request_json(
        self,
        endpoint: str,
        params: dict[str, object],
        log: LogCallback | None = None,
        stage: str = "assrt.request",
    ) -> dict:
        last_exc: Exception | None = None
        last_message = ""
        bases = self._api_bases()
        for base_index, base_url in enumerate(bases):
            switch_to_fallback = False
            for attempt in range(1, 4):
                await self._rate_limit()
                try:
                    async with self._client() as client:
                        response = await client.get(
                            f"{base_url}{endpoint}",
                            params={"token": self.token, **params},
                            headers={
                                "Accept": "application/json",
                                "User-Agent": "subtitleInfoCollection/0.1",
                            },
                        )
                        if response.status_code in {429, 509}:
                            raise CollectorError(
                                f"ASSRT HTTP {response.status_code} 限流/过载，主机 "
                                f"{self._host_of(base_url)}",
                                ErrorType.RATE_LIMITED,
                                self.id,
                            )
                        response.raise_for_status()
                        payload = response.json()
                    if base_url != self._active_base_url:
                        self._emit(
                            f"{stage}.fallback",
                            "ASSRT 已切换到备用 API 主机",
                            log,
                            host=self._host_of(base_url),
                            base_url=base_url,
                        )
                        self._active_base_url = base_url
                    self._raise_for_payload_status(
                        payload if isinstance(payload, dict) else {},
                        keyword=str(params.get("q") or ""),
                    )
                    return payload if isinstance(payload, dict) else {}
                except CollectorError:
                    raise
                except _TRANSIENT_HTTPX_ERRORS as exc:
                    last_exc = exc
                    last_message = self._network_error_message(
                        exc, base_url=base_url, endpoint=endpoint, stage=stage
                    )
                    if attempt < 3:
                        self._emit(
                            f"{stage}.retry",
                            last_message + f"；准备重试（{attempt}/3）",
                            log,
                            endpoint=endpoint,
                            host=self._host_of(base_url),
                            attempt=attempt,
                            error_type=type(exc).__name__,
                        )
                        await asyncio.sleep(0.2 * attempt)
                        continue
                    can_try_fallback = (
                        isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
                        and base_index + 1 < len(bases)
                    )
                    if can_try_fallback:
                        next_base = bases[base_index + 1]
                        self._emit(
                            f"{stage}.failover",
                            (
                                f"主域 {self._host_of(base_url)} 连续连接失败，"
                                f"切换备用域 {self._host_of(next_base)}"
                            ),
                            log,
                            from_base=base_url,
                            to_base=next_base,
                        )
                        switch_to_fallback = True
                        break
                    self._emit(
                        f"{stage}.fail",
                        last_message + "；已停止重试",
                        log,
                        endpoint=endpoint,
                        host=self._host_of(base_url),
                        attempt=attempt,
                        error_type=type(exc).__name__,
                    )
                    raise CollectorError(
                        last_message,
                        ErrorType.NETWORK_UNREACHABLE,
                        self.id,
                    ) from exc
                except httpx.HTTPError as exc:
                    error_text = str(exc) or repr(exc)
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

    async def search(
        self,
        movie: MovieInfo,
        log: LogCallback | None = None,
    ) -> list[SubtitleCandidate]:
        if not self.token:
            return []
        result: list[SubtitleCandidate] = []
        for keyword in self._keywords(movie):
            self._emit(
                "assrt.search.keyword.try",
                "ASSRT 尝试关键词搜索",
                log,
                keyword=keyword,
                base_url=self._active_base_url,
                host=self._host_of(self._active_base_url),
            )
            payload = await self._request_json(
                "/sub/search",
                {"q": keyword, "cnt": 15, "pos": 0, "filelist": 1},
                log=log,
                stage="assrt.search",
            )
            subs = payload.get("sub", {}).get("subs") or []
            mapped = [self._map_item(raw, movie, keyword) for raw in subs]
            result.extend([item for item in mapped if item.provider_subtitle_id])
            if result:
                break
        return result

    def _map_item(self, raw: dict, movie: MovieInfo, keyword: str) -> SubtitleCandidate:
        filelist = raw.get("filelist") or []
        file_names = [raw.get("filename"), *[item.get("f") for item in filelist if isinstance(item, dict)]]
        file_names = [item for item in file_names if item]
        language = chinese_language_label((raw.get("lang") or {}).get("desc") or "")
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
        return SubtitleCandidate(
            provider=self.id,
            provider_subtitle_id=str(raw.get("id") or ""),
            movie_id=movie.movie_id,
            movie_title=movie.title,
            movie_original_title=movie.original_title,
            movie_title_zh=movie.title_zh,
            movie_year=movie.year,
            subtitle_title=raw.get("title") or raw.get("native_name") or raw.get("filename") or "",
            language_type=language,
            subtitle_format=subtitle_format,
            download_count=int(raw.get("down_count") or raw.get("download_count") or 0),
            detail_url=f"https://assrt.net/xml/sub/{raw.get('id')}" if raw.get("id") else "",
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
            raw=raw,
        )

    async def download(self, candidate: SubtitleCandidate, context: DownloadContext) -> list[DownloadedPayload]:
        if not self.token:
            raise CollectorError("缺少 ASSRT_TOKEN", ErrorType.PROVIDER_DISABLED, self.id)
        self._emit(
            "assrt.download.start",
            "ASSRT 开始下载字幕",
            log=context.log,
            subtitle_id=candidate.provider_subtitle_id,
            title=candidate.subtitle_title,
        )
        detail = await self._request_json(
            "/sub/detail",
            {"id": candidate.provider_subtitle_id},
            log=context.log,
            stage="assrt.download.detail",
        )
        subs = detail.get("sub", {}).get("subs") or []
        if not subs:
            raise CollectorError("ASSRT 明细接口没有返回字幕信息", ErrorType.DOWNLOAD_FAILED, self.id)
        sub_detail = subs[0]
        filelist = [item for item in (sub_detail.get("filelist") or []) if isinstance(item, dict)]
        download_url = ""
        file_name = sub_detail.get("filename") or sub_detail.get("title") or "subtitle"
        for item in filelist:
            if item.get("url") and detect_subtitle_format(item.get("f", "")) in {"ass", "srt"}:
                download_url = item["url"]
                file_name = item.get("f") or file_name
                break
        if not download_url:
            download_url = sub_detail.get("url") or ""
        if not download_url:
            raise CollectorError("ASSRT 明细接口没有返回下载链接", ErrorType.DOWNLOAD_FAILED, self.id)

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                await self._rate_limit()
                async with self._client() as client:
                    full_url = urljoin(self._active_base_url + "/", download_url)
                    download_host = urlparse(full_url).netloc or full_url
                    response = await client.get(
                        full_url,
                        headers={
                            "Accept": "application/zip,application/octet-stream,text/plain,*/*",
                            "User-Agent": "subtitleInfoCollection/0.1",
                            "Referer": "https://assrt.net/",
                        },
                    )
                    if response.status_code in {429, 509}:
                        raise CollectorError(
                            f"ASSRT 字幕文件下载限流 HTTP {response.status_code}，主机 {download_host}",
                            ErrorType.RATE_LIMITED,
                            self.id,
                        )
                    response.raise_for_status()
                    self._emit(
                        "assrt.download.success",
                        "ASSRT 字幕下载成功",
                        log=context.log,
                        subtitle_id=candidate.provider_subtitle_id,
                        size=str(len(response.content)),
                        file=file_name,
                        host=download_host,
                    )
                    return [
                        DownloadedPayload(
                            file_name=file_name,
                            content=response.content,
                            source_url=str(response.url),
                            content_type=response.headers.get("content-type", ""),
                        )
                    ]
            except CollectorError:
                raise
            except _TRANSIENT_HTTPX_ERRORS as exc:
                last_exc = exc
                full_url = urljoin(self._active_base_url + "/", download_url)
                download_host = urlparse(full_url).netloc or full_url
                error_text = str(exc) or repr(exc)
                message = (
                    f"ASSRT 字幕文件下载失败，主机={download_host}（{type(exc).__name__}）："
                    f"{error_text}。注意：文件域名可能与 API 主机不同"
                )
                if attempt >= 3:
                    self._emit(
                        "assrt.download.fail",
                        message + "；已停止重试",
                        log=context.log,
                        subtitle_id=candidate.provider_subtitle_id,
                        host=download_host,
                        attempt=str(attempt),
                        error_type=type(exc).__name__,
                    )
                    raise CollectorError(
                        message,
                        ErrorType.NETWORK_UNREACHABLE,
                        self.id,
                    ) from exc
                self._emit(
                    "assrt.download.retry",
                    message + f"；准备重试（{attempt}/3）",
                    log=context.log,
                    subtitle_id=candidate.provider_subtitle_id,
                    host=download_host,
                    attempt=str(attempt),
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(0.2 * attempt)
            except httpx.HTTPError as exc:
                error_text = str(exc) or repr(exc)
                full_url = urljoin(self._active_base_url + "/", download_url)
                download_host = urlparse(full_url).netloc or full_url
                raise CollectorError(
                    f"ASSRT 字幕文件下载 HTTP 错误，主机={download_host}："
                    f"{type(exc).__name__}: {error_text}",
                    ErrorType.NETWORK_UNREACHABLE,
                    self.id,
                ) from exc
        raise CollectorError(
            f"ASSRT 下载失败: {last_exc!r}",
            ErrorType.NETWORK_UNREACHABLE,
            self.id,
        )
