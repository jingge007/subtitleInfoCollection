from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


DEFAULT_PROVIDER_PRIORITY = ["subhd", "assrt", "opensubtitles"]
DEFAULT_REQUEST_INTERVAL_MS = 13_000


def _load_dotenv() -> None:
    if load_dotenv:
        load_dotenv(override=True)


def parse_csv(value: str | None, fallback: list[str] | None = None) -> list[str]:
    items = [item.strip().lower() for item in str(value or "").split(",") if item.strip()]
    return items or list(fallback or [])


def parse_int(value: str | None, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def default_data_dir() -> Path:
    configured = os.getenv("SUBTITLE_COLLECTION_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "subtitleInfoCollection").resolve()


@dataclass(slots=True)
class AppSettings:
    """应用程序配置数据类"""
    data_dir: Path = field(default_factory=default_data_dir)  # 数据目录
    tmdb_token: str = ""  # TMDb访问令牌
    assrt_token: str = ""  # ASSRT访问令牌
    assrt_api_base_url: str = "https://api.assrt.net/v1"  # ASSRT API基础URL
    opensubtitles_api_key: str = ""  # OpenSubtitles API密钥
    opensubtitles_username: str = ""  # OpenSubtitles用户名
    opensubtitles_password: str = ""  # OpenSubtitles密码
    opensubtitles_base_url: str = "https://api.opensubtitles.com/api/v1"  # OpenSubtitles API基础URL
    opensubtitles_user_agent: str = "subtitleInfoCollection v0.1"  # OpenSubtitles用户代理
    provider_priority: list[str] = field(default_factory=lambda: list(DEFAULT_PROVIDER_PRIORITY))  # 字幕源优先级
    provider_disabled: list[str] = field(default_factory=list)  # 禁用的字幕源
    request_interval_ms: int = DEFAULT_REQUEST_INTERVAL_MS  # 请求间隔（毫秒）
    http_proxy: str = ""  # HTTP代理
    https_proxy: str = ""  # HTTPS代理

    @classmethod
    def from_env(cls) -> "AppSettings":
        _load_dotenv()
        return cls(
            data_dir=default_data_dir(),
            tmdb_token=os.getenv("TMDB_TOKEN", ""),
            assrt_token=os.getenv("ASSRT_TOKEN", ""),
            assrt_api_base_url=os.getenv("ASSRT_API_BASE_URL", "https://api.assrt.net/v1"),
            opensubtitles_api_key=os.getenv("OPENSUBTITLES_API_KEY", ""),
            opensubtitles_username=os.getenv("OPENSUBTITLES_USERNAME", ""),
            opensubtitles_password=os.getenv("OPENSUBTITLES_PASSWORD", ""),
            opensubtitles_base_url=os.getenv(
                "OPENSUBTITLES_BASE_URL", "https://api.opensubtitles.com/api/v1"
            ),
            opensubtitles_user_agent=os.getenv(
                "OPENSUBTITLES_USER_AGENT", "subtitleInfoCollection v0.1"
            ),
            provider_priority=parse_csv(
                os.getenv("SUBTITLE_PROVIDER_PRIORITY"), DEFAULT_PROVIDER_PRIORITY
            ),
            provider_disabled=parse_csv(os.getenv("SUBTITLE_PROVIDER_DISABLED"), []),
            request_interval_ms=max(
                12_000,
                parse_int(os.getenv("SUBTITLE_REQUEST_INTERVAL_MS"), DEFAULT_REQUEST_INTERVAL_MS),
            ),
            http_proxy=os.getenv("HTTP_PROXY", ""),
            https_proxy=os.getenv("HTTPS_PROXY", ""),
        )

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "subtitle_info_collection.sqlite3"

    def proxies(self) -> dict[str, str]:
        result: dict[str, str] = {}
        if self.http_proxy:
            result["http://"] = self.http_proxy
        if self.https_proxy:
            result["https://"] = self.https_proxy
        return result
