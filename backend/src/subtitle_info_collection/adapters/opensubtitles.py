from __future__ import annotations

import httpx

from ..errors import CollectorError, ErrorType
from ..models import (
    DownloadedPayload,
    MovieInfo,
    SubtitleCandidate,
    chinese_language_label,
    format_chinese_description,
)
from ..engines.subtitle_engine import detect_subtitle_format
from .base import DownloadContext, LogCallback, ProviderHealth


class OpenSubtitlesProvider:
    id = "opensubtitles"
    download_supported = True

    def __init__(
        self,
        api_key: str = "",
        username: str = "",
        password: str = "",
        base_url: str = "https://api.opensubtitles.com/api/v1",
        user_agent: str = "subtitleInfoCollection v0.1",
        timeout: float = 30,
        proxy: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout
        self.proxy = proxy
        self._token = ""

    async def health(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(
                self.id, enabled=False, healthy=False, error_type=ErrorType.PROVIDER_DISABLED,
                message="缺少 OPENSUBTITLES_API_KEY",
            )
        return ProviderHealth(self.id, enabled=True, healthy=True)

    def _headers(self, auth: bool = False) -> dict[str, str]:
        headers = {
            "Api-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _ensure_login(self, client: httpx.AsyncClient) -> None:
        if self._token:
            return
        if not self.username or not self.password:
            raise CollectorError(
                "OpenSubtitles 下载需要用户名和密码",
                ErrorType.PROVIDER_DISABLED,
                self.id,
            )
        response = await client.post(
            f"{self.base_url}/login",
            headers=self._headers(),
            json={"username": self.username, "password": self.password},
        )
        self._raise_for_status(response, "login")
        payload = response.json()
        self._token = payload.get("token") or ""
        returned_base_url = payload.get("base_url") or ""
        if returned_base_url:
            if returned_base_url.startswith("http"):
                self.base_url = returned_base_url.rstrip("/")
            else:
                self.base_url = f"https://{returned_base_url.strip('/')}/api/v1"

    def _movie_keyword(self, movie: MovieInfo) -> str:
        return movie.original_title or movie.title or movie.title_zh

    def _search_params(self, movie: MovieInfo) -> dict[str, object]:
        params: dict[str, object] = {
            "languages": "ze,zh-cn,en",
            "type": "movie",
            "order_by": "download_count",
            "order_direction": "desc",
        }
        if movie.tmdb_id:
            params["tmdb_id"] = movie.tmdb_id
            return params
        params["query"] = self._movie_keyword(movie)
        if movie.year:
            params["year"] = movie.year
        return params

    def _response_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip()
        if isinstance(payload, dict):
            for key in ["message", "error"]:
                value = payload.get(key)
                if value:
                    return str(value)
            errors = payload.get("errors")
            if isinstance(errors, list):
                return "; ".join(str(item) for item in errors if item)
        return str(payload)

    def _raise_for_status(self, response: httpx.Response, operation: str) -> None:
        if response.status_code < 400:
            return
        detail = self._response_error_message(response)
        suffix = f"：{detail}" if detail else ""
        if response.status_code == 406 and operation == "download":
            raise CollectorError(
                f"OpenSubtitles 拒绝下载请求（406），通常表示每日下载额度已用完或账号权限不足{suffix}",
                ErrorType.DOWNLOAD_QUOTA_EXCEEDED,
                self.id,
            )
        if response.status_code == 429:
            raise CollectorError(
                f"OpenSubtitles 请求频率受限（429）{suffix}",
                ErrorType.RATE_LIMITED,
                self.id,
            )
        if response.status_code in {401, 403}:
            raise CollectorError(
                f"OpenSubtitles 认证或权限失败（{response.status_code}）{suffix}",
                ErrorType.DOWNLOAD_BLOCKED,
                self.id,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CollectorError(
                f"OpenSubtitles {operation} 请求失败（HTTP {response.status_code}）{suffix}",
                ErrorType.DOWNLOAD_FAILED,
                self.id,
            ) from exc

    async def search(
        self,
        movie: MovieInfo,
        log: LogCallback | None = None,
    ) -> list[SubtitleCandidate]:
        if not self.api_key:
            return []
        params = self._search_params(movie)
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            proxy=self.proxy,
        ) as client:
            response = await client.get(
                f"{self.base_url}/subtitles",
                params=params,
                headers=self._headers(),
            )
            self._raise_for_status(response, "search")
            payload = response.json()
        return [self._map_item(item, movie) for item in payload.get("data", [])]

    def _map_item(self, raw: dict, movie: MovieInfo) -> SubtitleCandidate:
        attrs = raw.get("attributes") or {}
        files = attrs.get("files") or []
        file_info = files[0] if files else {}
        file_name = file_info.get("file_name") or attrs.get("release") or ""
        subtitle_format = detect_subtitle_format(file_name) or detect_subtitle_format(attrs.get("format", ""))
        language = chinese_language_label(attrs.get("language") or attrs.get("language_name") or "")
        title = attrs.get("release") or file_name or (attrs.get("feature_details") or {}).get("title") or ""
        description = format_chinese_description(
            ("字幕标题", title),
            ("语言", language),
            ("格式", subtitle_format or "srt"),
            ("文件名", file_name),
        )
        return SubtitleCandidate(
            provider=self.id,
            provider_subtitle_id=str(raw.get("id") or file_info.get("file_id") or ""),
            movie_id=movie.movie_id,
            movie_title=movie.title,
            movie_original_title=movie.original_title,
            movie_title_zh=movie.title_zh,
            movie_year=movie.year,
            subtitle_title=title,
            language_type=language,
            subtitle_format=subtitle_format or "srt",
            download_count=int(attrs.get("download_count") or 0),
            rating=float(attrs.get("ratings") or 0),
            detail_url=attrs.get("url") or "",
            description=description[:1000],
            file_names=[file_name] if file_name else [],
            raw=raw,
        )

    async def download(
        self,
        candidate: SubtitleCandidate,
        context: DownloadContext,
    ) -> list[DownloadedPayload]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            proxy=self.proxy,
        ) as client:
            await self._ensure_login(client)
            file_id = candidate.raw.get("attributes", {}).get("files", [{}])[0].get("file_id")
            if not file_id:
                file_id = candidate.provider_subtitle_id
            response = await client.post(
                f"{self.base_url}/download",
                headers=self._headers(auth=True),
                json={"file_id": file_id},
            )
            self._raise_for_status(response, "download")
            payload = response.json()
            link = payload.get("link") or payload.get("url")
            if not link:
                raise CollectorError("OpenSubtitles 没有返回下载链接", ErrorType.DOWNLOAD_FAILED, self.id)
            file_response = await client.get(link, headers={"User-Agent": self.user_agent})
            file_response.raise_for_status()
            file_name = payload.get("file_name") or (
                candidate.file_names[0] if candidate.file_names else "subtitle.srt"
            )
            return [
                DownloadedPayload(
                    file_name=file_name,
                    content=file_response.content,
                    source_url=link,
                    content_type=file_response.headers.get("content-type", ""),
                )
            ]
