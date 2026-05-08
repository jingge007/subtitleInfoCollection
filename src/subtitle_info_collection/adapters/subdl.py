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
from .base import DownloadContext, ProviderHealth


class SubdlProvider:
    id = "subdl"
    download_supported = True

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.subdl.com/api/v1",
        download_base_url: str = "https://dl.subdl.com",
        languages: str = "ZH,EN",
        include_traditional: bool = False,
        timeout: float = 30,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.download_base_url = download_base_url.rstrip("/")
        self.languages = languages
        self.include_traditional = include_traditional
        self.timeout = timeout

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
            for item in str(self.languages or "ZH,EN").split(",")
            if item.strip()
        ]
        if not values:
            values = ["ZH", "EN"]
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

    async def search(self, movie: MovieInfo) -> list[SubtitleCandidate]:
        if not self.api_key:
            return []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(
                f"{self.base_url}/subtitles",
                params=self._search_params(movie),
                headers={
                    "Accept": "application/json",
                    "User-Agent": "subtitleInfoCollection/0.1",
                },
            )
            if response.status_code == 429:
                raise CollectorError("SubDL rate limit", ErrorType.RATE_LIMITED, self.id)
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
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(
                download_url,
                headers={
                    "Accept": "application/zip,application/octet-stream,text/plain,*/*",
                    "User-Agent": "subtitleInfoCollection/0.1",
                    "Referer": candidate.detail_url or "https://subdl.com/",
                },
            )
            if response.status_code == 429:
                raise CollectorError("SubDL rate limit", ErrorType.RATE_LIMITED, self.id)
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
