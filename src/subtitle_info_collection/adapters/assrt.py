from __future__ import annotations

import asyncio
import logging
from urllib.parse import urljoin

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

class AssrtProvider:
    id = "assrt"
    download_supported = True

    def __init__(
        self,
        token: str = "",
        base_url: str = "https://api.assrt.net/v1",
        request_interval_ms: int = 500,
        timeout: float = 30,
        proxy: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.request_interval_ms = request_interval_ms
        self.timeout = timeout
        self.proxy = proxy
        self.transport = transport
        self._last_request = 0.0

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

    async def _request_json(
        self,
        endpoint: str,
        params: dict[str, object],
        log: LogCallback | None = None,
        stage: str = "assrt.request",
    ) -> dict:
        await self._rate_limit()
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                async with self._client() as client:
                    response = await client.get(
                        f"{self.base_url}{endpoint}",
                        params={"token": self.token, **params},
                        headers={
                            "Accept": "application/json",
                            "User-Agent": "subtitleInfoCollection/0.1",
                        },
                    )
                    if response.status_code in {429, 509}:
                        raise CollectorError(f"HTTP {response.status_code}", ErrorType.RATE_LIMITED, self.id)
                    response.raise_for_status()
                    payload = response.json()
                    break
            except _TRANSIENT_HTTPX_ERRORS as exc:
                last_exc = exc
                error_text = str(exc) or repr(exc)
                if attempt >= 3:
                    self._emit(
                        f"{stage}.fail",
                        "ASSRT 请求网络异常，已停止重试",
                        log,
                        endpoint=endpoint,
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        error=error_text,
                    )
                    raise CollectorError(
                        f"{type(exc).__name__}: {error_text}",
                        ErrorType.NETWORK_UNREACHABLE,
                        self.id,
                    ) from exc
                self._emit(
                    f"{stage}.retry",
                    "ASSRT 请求网络异常，准备重试",
                    log,
                    endpoint=endpoint,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    error=error_text,
                )
                await asyncio.sleep(0.2 * attempt)
            except httpx.HTTPError as exc:
                error_text = str(exc) or repr(exc)
                raise CollectorError(
                    f"{type(exc).__name__}: {error_text}",
                    ErrorType.NETWORK_UNREACHABLE,
                    self.id,
                ) from exc
        else:
            raise CollectorError(
                f"ASSRT 请求失败：{last_exc!r}",
                ErrorType.NETWORK_UNREACHABLE,
                self.id,
            )
        if payload.get("status") not in (None, 0):
            raise CollectorError(str(payload.get("error") or payload), ErrorType.PARSE_FAILED, self.id)
        return payload

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
                base_url=self.base_url,
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
                    full_url = urljoin(self.base_url, download_url)
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
                            f"HTTP {response.status_code}",
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
                    )
                    return [
                        DownloadedPayload(
                            file_name=file_name,
                            content=response.content,
                            source_url=str(response.url),
                            content_type=response.headers.get("content-type", ""),
                        )
                    ]
            except _TRANSIENT_HTTPX_ERRORS as exc:
                last_exc = exc
                error_text = str(exc) or repr(exc)
                if attempt >= 3:
                    self._emit(
                        "assrt.download.fail",
                        "ASSRT 下载文件网络异常，已停止重试",
                        log=context.log,
                        subtitle_id=candidate.provider_subtitle_id,
                        base_url=self.base_url,
                        endpoint=download_url,
                        attempt=str(attempt),
                        error_type=type(exc).__name__,
                        error=error_text,
                    )
                    raise CollectorError(
                        f"{type(exc).__name__}: {error_text}",
                        ErrorType.NETWORK_UNREACHABLE,
                        self.id,
                    ) from exc
                self._emit(
                    "assrt.download.retry",
                    "ASSRT 下载文件网络异常，准备重试",
                    log=context.log,
                    subtitle_id=candidate.provider_subtitle_id,
                    base_url=self.base_url,
                    endpoint=download_url,
                    attempt=str(attempt),
                    error_type=type(exc).__name__,
                    error=error_text,
                )
                await asyncio.sleep(0.2 * attempt)
            except httpx.HTTPError as exc:
                error_text = str(exc) or repr(exc)
                raise CollectorError(
                    f"{type(exc).__name__}: {error_text}",
                    ErrorType.NETWORK_UNREACHABLE,
                    self.id,
                ) from exc
        raise CollectorError(
            f"ASSRT 下载失败: {last_exc!r}",
            ErrorType.NETWORK_UNREACHABLE,
            self.id,
        )
