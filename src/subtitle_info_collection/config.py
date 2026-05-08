from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


DEFAULT_PROVIDER_PRIORITY = ["subhd", "subdl", "assrt", "opensubtitles"]
DEFAULT_REQUEST_INTERVAL_MS = 13_000
DEFAULT_MIN_BILINGUAL_RATIO = 0.70
PROVIDER_LABELS = {
    "subhd": "SubHD",
    "subdl": "SubDL",
    "assrt": "ASSRT",
    "opensubtitles": "OpenSubtitles",
}


def _load_dotenv(env_path: Path | None = None) -> None:
    if not load_dotenv:
        return
    if env_path and env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=True)


def parse_csv(value: str | None, fallback: list[str] | None = None) -> list[str]:
    items = [item.strip().lower() for item in str(value or "").split(",") if item.strip()]
    return items or list(fallback or [])


def parse_int(value: str | None, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def parse_bool(value: str | None, fallback: bool = False) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return fallback
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return fallback


def parse_float(value: str | None, fallback: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def parse_ratio(value: str | None, fallback: float) -> float:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        ratio = float(text)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, ratio))


def default_data_dir() -> Path:
    configured = os.getenv("SUBTITLE_COLLECTION_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "subtitleInfoCollection").resolve()


def _default_env_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def _env_example_candidates(base_dir: Path) -> list[Path]:
    candidates = [
        base_dir / ".env.example",
        base_dir / "_internal" / ".env.example",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / ".env.example")
    return candidates


@dataclass(slots=True)
class EnvBootstrapResult:
    env_path: Path
    created: bool


@dataclass(slots=True)
class ProviderConfigStatus:
    id: str
    label: str
    enabled: bool
    configured: bool
    detail: str


@dataclass(slots=True)
class ConfigCheckResult:
    env_path: Path
    env_exists: bool
    data_dir: Path
    data_dir_exists: bool
    tmdb_configured: bool
    request_interval_ms: int
    providers: list[ProviderConfigStatus]
    proxies_configured: bool
    warnings: list[str]

    @property
    def enabled_provider_count(self) -> int:
        return sum(1 for provider in self.providers if provider.enabled)

    @property
    def configured_provider_count(self) -> int:
        return sum(
            1
            for provider in self.providers
            if provider.enabled and provider.configured
        )

    @property
    def ready(self) -> bool:
        return (
            self.env_exists
            and self.data_dir_exists
            and self.tmdb_configured
            and self.configured_provider_count > 0
        )


def _find_existing_env(base_dir: Path) -> Path | None:
    candidates = [
        base_dir / ".env",
        base_dir / "_internal" / ".env",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / ".env")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def bootstrap_env_file(root: Path | None = None) -> EnvBootstrapResult:
    base_dir = root.resolve() if root else _default_env_base_dir()

    existing = _find_existing_env(base_dir)
    if existing is not None:
        return EnvBootstrapResult(env_path=existing, created=False)

    env_path = base_dir / ".env"
    example_path = next(
        (candidate for candidate in _env_example_candidates(base_dir) if candidate.exists()),
        None,
    )
    if not example_path:
        searched = ", ".join(str(candidate) for candidate in _env_example_candidates(base_dir))
        raise FileNotFoundError(f"缺少环境模板文件：{searched}")
    shutil.copyfile(example_path, env_path)
    return EnvBootstrapResult(env_path=env_path, created=True)


def evaluate_config(
    settings: "AppSettings",
    env_path: Path | None = None,
) -> ConfigCheckResult:
    resolved_env_path = (env_path or Path.cwd() / ".env").resolve()
    disabled = set(settings.provider_disabled)

    provider_statuses = [
        ProviderConfigStatus(
            id="subhd",
            label=PROVIDER_LABELS["subhd"],
            enabled="subhd" not in disabled,
            configured=True,
            detail="无需 Token，可直接搜索，下载时可能需要验证码。",
        ),
        ProviderConfigStatus(
            id="subdl",
            label=PROVIDER_LABELS["subdl"],
            enabled="subdl" not in disabled,
            configured=bool(settings.subdl_api_key.strip()),
            detail="需要 SUBDL_API_KEY；默认语言 ZH,EN 用于扩大中英双语候选召回。",
        ),
        ProviderConfigStatus(
            id="assrt",
            label=PROVIDER_LABELS["assrt"],
            enabled="assrt" not in disabled,
            configured=bool(settings.assrt_token.strip()),
            detail="需要 ASSRT_TOKEN 才能启用。",
        ),
        ProviderConfigStatus(
            id="opensubtitles",
            label=PROVIDER_LABELS["opensubtitles"],
            enabled="opensubtitles" not in disabled,
            configured=bool(
                settings.opensubtitles_api_key.strip()
                and settings.opensubtitles_username.strip()
                and settings.opensubtitles_password.strip()
            ),
            detail="需要 API Key、用户名和密码，搜索与下载才完整可用。",
        ),
    ]

    warnings = []
    if not resolved_env_path.exists():
        warnings.append("未找到 .env，本地密钥和运行配置尚未初始化。")
    if not settings.tmdb_token.strip():
        warnings.append("TMDb Token 缺失，无法采集电影榜单或自动匹配本地字幕电影信息。")
    if not settings.data_dir.exists():
        warnings.append("数据目录尚不存在，应用启动时会尝试自动创建。")
    if not any(provider.enabled and provider.configured for provider in provider_statuses):
        warnings.append("没有可用字幕源，请至少启用 SubHD 或配置 ASSRT/OpenSubtitles。")

    return ConfigCheckResult(
        env_path=resolved_env_path,
        env_exists=resolved_env_path.exists(),
        data_dir=settings.data_dir,
        data_dir_exists=settings.data_dir.exists(),
        tmdb_configured=bool(settings.tmdb_token.strip()),
        request_interval_ms=settings.request_interval_ms,
        providers=provider_statuses,
        proxies_configured=bool(settings.http_proxy.strip() or settings.https_proxy.strip()),
        warnings=warnings,
    )


@dataclass(slots=True)
class AppSettings:
    """应用程序配置数据类"""
    subdl_api_key: str = ""
    subdl_base_url: str = "https://api.subdl.com/api/v1"
    subdl_download_base_url: str = "https://dl.subdl.com"
    subdl_languages: str = "ZH,EN"
    subdl_include_traditional: bool = False
    subtitle_min_bilingual_ratio: float = DEFAULT_MIN_BILINGUAL_RATIO
    subhd_captcha_ocr_enabled: bool = True
    subhd_captcha_auto_submit_min_confidence: float = 0.85
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
    def from_env(cls, env_path: Path | None = None) -> "AppSettings":
        _load_dotenv(env_path)
        return cls(
            data_dir=default_data_dir(),
            tmdb_token=os.getenv("TMDB_TOKEN", ""),
            assrt_token=os.getenv("ASSRT_TOKEN", ""),
            assrt_api_base_url=os.getenv("ASSRT_API_BASE_URL", "https://api.assrt.net/v1"),
            subdl_api_key=os.getenv("SUBDL_API_KEY", ""),
            subdl_base_url=os.getenv("SUBDL_BASE_URL", "https://api.subdl.com/api/v1"),
            subdl_download_base_url=os.getenv("SUBDL_DOWNLOAD_BASE_URL", "https://dl.subdl.com"),
            subdl_languages=os.getenv("SUBDL_LANGUAGES", "ZH,EN"),
            subdl_include_traditional=parse_bool(os.getenv("SUBDL_INCLUDE_TRADITIONAL"), False),
            subtitle_min_bilingual_ratio=parse_ratio(
                os.getenv("SUBTITLE_MIN_BILINGUAL_RATIO"), DEFAULT_MIN_BILINGUAL_RATIO
            ),
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
            subhd_captcha_ocr_enabled=parse_bool(os.getenv("SUBHD_CAPTCHA_OCR_ENABLED"), True),
            subhd_captcha_auto_submit_min_confidence=max(
                0.0,
                min(
                    1.0,
                    parse_float(os.getenv("SUBHD_CAPTCHA_AUTO_SUBMIT_MIN_CONFIDENCE"), 0.85),
                ),
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
