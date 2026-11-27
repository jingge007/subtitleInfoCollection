from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

import httpx

from ..engines.subtitle_engine import detect_subtitle_format
from ..errors import CollectorError, ErrorType
from ..models import (
    DownloadedPayload,
    MovieInfo,
    SubtitleCandidate,
    chinese_language_label,
    format_chinese_description,
)
from .base import DownloadContext, LogCallback, ProviderHealth

# SubDL 429 body.error：日配额 vs 短时限流（与 Bazarr/官方语义对齐）
_SUBDL_DOWNLOAD_QUOTA_ERRORS = frozenset(
    {
        "daily_limit",
        "api_download_limit_exceeded",
        "download_limit",
        "quota_exceeded",
    }
)
_SUBDL_RATE_LIMIT_ERRORS = frozenset({"rate_limit", "service_busy"})


class SubdlProvider:
    id = "subdl"
    download_supported = True

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.subdl.com/api/v1",
        download_base_url: str = "https://dl.subdl.com",
        languages: str = "ZH",
        include_traditional: bool = False,
        timeout: float = 30,
        proxy: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.download_base_url = download_base_url.rstrip("/")
        self.languages = languages
        self.include_traditional = include_traditional
        self.timeout = timeout
        self.proxy = proxy

    # 从 429 响应解析错误码与可读信息
    def _parse_429_payload(self, response: httpx.Response) -> tuple[str, str]:
        try:
            payload = response.json()
        except ValueError:
            text = (response.text or "").strip()
            return "", text
        if not isinstance(payload, dict):
            return "", str(payload)
        error_code = str(payload.get("error") or payload.get("code") or "").strip()
        message = str(payload.get("message") or payload.get("error") or "").strip()
        return error_code, message

    # 将 HTTP 429 归类为日配额或短时限流
    def _raise_for_429(self, response: httpx.Response, *, operation: str) -> None:
        error_code, detail = self._parse_429_payload(response)
        code_lower = error_code.lower()
        detail_lower = detail.lower()
        suffix = f"：{detail}" if detail else ""
        if (
            code_lower in _SUBDL_DOWNLOAD_QUOTA_ERRORS
            or "daily" in code_lower
            or "download_limit" in code_lower
            or "daily" in detail_lower
            or "download limit" in detail_lower
        ):
            raise CollectorError(
                f"SubDL 每日下载额度已用完（免费档约 50 次/天）{suffix}。"
                f"请等待配额重置、升级 SubDL Pro，或暂时禁用 subdl",
                ErrorType.DOWNLOAD_QUOTA_EXCEEDED,
                self.id,
            )
        if code_lower in _SUBDL_RATE_LIMIT_ERRORS or "rate" in code_lower:
            raise CollectorError(
                f"SubDL 短时请求频率受限（429）{suffix}",
                ErrorType.RATE_LIMITED,
                self.id,
            )
        # 下载侧无明确 body 时优先按日配额处理（免费档常见撞墙形态）
        if operation == "download":
            raise CollectorError(
                f"SubDL 下载返回 429，疑似每日下载额度已用完{suffix}。"
                f"请等待配额重置或升级 Pro；若为短时限流可稍后重试",
                ErrorType.DOWNLOAD_QUOTA_EXCEEDED,
                self.id,
            )
        raise CollectorError(
            f"SubDL 搜索返回 429 限流{suffix}",
            ErrorType.RATE_LIMITED,
            self.id,
        )

    async def health(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(
                self.id,
                enabled=False,
                healthy=False,
                error_type=ErrorType.PROVIDER_DISABLED,
                message="Missing SUBDL_API_KEY",
            )
        return ProviderHealth(self.id, enabled=True, healthy=True)

    def _effective_languages(self) -> str:
        values = [
            item.strip().upper()
            for item in str(self.languages or "ZH").split(",")
            if item.strip()
        ]
        if not values:
            values = ["ZH"]
        if not self.include_traditional:
            values = [item for item in values if item != "ZH_BG"]
        elif "ZH_BG" not in values:
            values.append("ZH_BG")
        return ",".join(dict.fromkeys(values))

    def _movie_keyword(self, movie: MovieInfo) -> str:
        return movie.title or movie.original_title or movie.title_zh

    def _search_params(self, movie: MovieInfo) -> dict[str, object]:
        params: dict[str, object] = {
            "api_key": self.api_key,
            "type": "movie",
            "languages": self._effective_languages(),
            "subs_per_page": 30,
            "comment": 1,
            "releases": 1,
            "hi": 1,
        }
        if movie.tmdb_id:
            params["tmdb_id"] = movie.tmdb_id
        else:
            params["film_name"] = self._movie_keyword(movie)
            if movie.year:
                params["year"] = movie.year
        return params

    def _response_error_message(self, payload: object) -> str:
        if isinstance(payload, dict):
            return str(payload.get("error") or payload.get("message") or payload)
        return str(payload)

    async def search(
        self,
        movie: MovieInfo,
        log: LogCallback | None = None,
    ) -> list[SubtitleCandidate]:
        if not self.api_key:
            return []
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            proxy=self.proxy,
        ) as client:
            response = await client.get(
                f"{self.base_url}/subtitles",
                params=self._search_params(movie),
                headers={
                    "Accept": "application/json",
                    "User-Agent": "subtitleInfoCollection/0.1",
                },
            )
            if response.status_code == 429:
                self._raise_for_429(response, operation="search")
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict) and payload.get("status") is False:
            raise CollectorError(self._response_error_message(payload), ErrorType.PARSE_FAILED, self.id)
        subtitles = payload.get("subtitles") if isinstance(payload, dict) else []
        if not isinstance(subtitles, list):
            return []
        return [
            candidate
            for candidate in (self._map_item(raw, movie) for raw in subtitles if isinstance(raw, dict))
            if candidate.provider_subtitle_id
        ]

    def _string_values(self, raw: dict, keys: list[str]) -> list[str]:
        values: list[str] = []
        for key in keys:
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
            elif isinstance(value, (int, float)):
                values.append(str(value))
            elif isinstance(value, list):
                values.extend(str(item).strip() for item in value if str(item).strip())
        return values

    def _download_path(self, raw: dict) -> str:
        for key in ["url", "download_url", "downloadUrl", "link", "path", "subtitle_url"]:
            value = str(raw.get(key) or "").strip()
            if value:
                return value
        for value in self._string_values(raw, ["subtitle", "file"]):
            if "/subtitle/" in value or value.endswith(".zip"):
                return value
        return ""

    def _provider_subtitle_id(self, raw: dict, download_path: str) -> str:
        for key in ["id", "sd_id", "sub_id", "subtitle_id", "subtitleId"]:
            value = str(raw.get(key) or "").strip()
            if value:
                return value
        match = re.search(r"/subtitle/([^/?#]+)", download_path)
        if match:
            return match.group(1).removesuffix(".zip")
        return ""

    def _download_url(self, download_path: str) -> str:
        if not download_path:
            return ""
        if download_path.startswith("http://") or download_path.startswith("https://"):
            return download_path
        return urljoin(f"{self.download_base_url}/", download_path.lstrip("/"))

    def _map_item(self, raw: dict, movie: MovieInfo) -> SubtitleCandidate:
        download_path = self._download_path(raw)
        download_url = self._download_url(download_path)
        provider_subtitle_id = self._provider_subtitle_id(raw, download_path)
        file_names = self._string_values(
            raw,
            ["file_name", "filename", "release_name", "release", "releases", "name"],
        )
        title = next(
            (
                value
                for value in self._string_values(
                    raw,
                    ["release_name", "release", "name", "title", "filename", "file_name"],
                )
                if value
            ),
            provider_subtitle_id,
        )
        language_raw = raw.get("language") or raw.get("lang") or raw.get("language_code") or raw.get("languageCode")
        language = chinese_language_label(language_raw or "")
        text = " ".join(
            str(part)
            for part in [
                title,
                language_raw,
                raw.get("comment"),
                raw.get("author"),
                raw.get("hi"),
                download_path,
                *file_names,
            ]
            if part
        )
        subtitle_format = (
            detect_subtitle_format(" ".join(file_names))
            or detect_subtitle_format(download_path)
            or detect_subtitle_format(text)
            or "srt"
        )
        detail_url = str(raw.get("subtitlePage") or raw.get("subtitle_page") or raw.get("page") or "")
        return SubtitleCandidate(
            provider=self.id,
            provider_subtitle_id=provider_subtitle_id,
            movie_id=movie.movie_id,
            movie_title=movie.title,
            movie_original_title=movie.original_title,
            movie_title_zh=movie.title_zh,
            movie_year=movie.year,
            subtitle_title=title,
            language_type=language,
            subtitle_format=subtitle_format,
            download_count=int(raw.get("downloads") or raw.get("download_count") or 0),
            rating=float(raw.get("rating") or 0),
            detail_url=detail_url,
            download_url=download_url,
            description=format_chinese_description(
                ("Source", "SubDL"),
                ("Language", language or language_raw),
                ("Title", title),
                ("Comment", raw.get("comment")),
                ("Releases", file_names),
            ),
            file_names=file_names,
            raw=raw,
        )

    async def download(
        self,
        candidate: SubtitleCandidate,
        context: DownloadContext,
    ) -> list[DownloadedPayload]:
        download_url = candidate.download_url or self._download_url(self._download_path(candidate.raw))
        if not download_url:
            raise CollectorError("SubDL did not return a download URL", ErrorType.DOWNLOAD_FAILED, self.id)
        # 下载鉴权：官方文档支持 api_key query 或 x-api-key，计入账号下载配额
        headers = {
            "Accept": "application/zip,application/octet-stream,text/plain,*/*",
            "User-Agent": "subtitleInfoCollection/0.1",
            "Referer": candidate.detail_url or "https://subdl.com/",
        }
        params: dict[str, str] = {}
        if self.api_key:
            params["api_key"] = self.api_key
            headers["x-api-key"] = self.api_key
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            proxy=self.proxy,
        ) as client:
            response = await client.get(
                download_url,
                params=params or None,
                headers=headers,
            )
            if response.status_code == 429:
                self._raise_for_429(response, operation="download")
            response.raise_for_status()
        file_name = Path(download_url.split("?", 1)[0]).name or f"{candidate.provider_subtitle_id}.zip"
        return [
            DownloadedPayload(
                file_name=file_name,
                content=response.content,
                source_url=download_url,
                content_type=response.headers.get("content-type", ""),
            )
        ]
