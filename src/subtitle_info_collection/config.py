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
DEFAULT_REQUEST_INTERVAL_MS = 8_000
DEFAULT_MOVIE_CONCURRENCY = 2
DEFAULT_MIN_BILINGUAL_RATIO = 0.70
DEFAULT_SUBHD_SEARCH_TIMEOUT = 120
DEFAULT_PROVIDER_SEARCH_TIMEOUT = 90
DEFAULT_SUBHD_DOWNLOAD_TIMEOUT = 180
DEFAULT_PROVIDER_DOWNLOAD_TIMEOUT = 60
# ASSRT 适配器内部短间隔：长间隔由编排器按源分桶负责
ASSRT_INTERNAL_INTERVAL_MS = 500
# 请求间隔安全下限（毫秒）
MIN_REQUEST_INTERVAL_MS = 8_000
PROVIDER_LABELS = {
    "subhd": "SubHD",
    "subdl": "SubDL",
    "assrt": "ASSRT",
    "opensubtitles": "OpenSubtitles",
}

# 配置项页分组标识
CONFIG_GROUP_SECRETS = "secrets"
CONFIG_GROUP_STRATEGY = "strategy"
CONFIG_GROUP_SUBHD = "subhd"
CONFIG_GROUP_NETWORK = "network"
CONFIG_GROUP_LOCAL = "local"

CONFIG_GROUP_LABELS = {
    CONFIG_GROUP_SECRETS: "密钥与账号",
    CONFIG_GROUP_STRATEGY: "字幕源策略",
    CONFIG_GROUP_SUBHD: "SubHD 与验证码",
    CONFIG_GROUP_NETWORK: "网络与接口",
    CONFIG_GROUP_LOCAL: "本机与打包",
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


def parse_optional_int(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


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
    movie_concurrency: int
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


@dataclass(slots=True)
class EnvFieldMeta:
    """配置项元数据：供 GUI 表单绑定与测试对齐"""

    key: str
    label: str
    group: str
    widget: str
    description: str
    settings_attr: str
    secret: bool = False


# 配置项页可编辑字段元数据（顺序即表单展示顺序）
ENV_FIELD_META: list[EnvFieldMeta] = [
    EnvFieldMeta(
        "TMDB_TOKEN", "TMDb Token", CONFIG_GROUP_SECRETS, "secret",
        "电影榜单采集与本地字幕匹配；留空则榜单不可用。", "tmdb_token", True,
    ),
    EnvFieldMeta(
        "ASSRT_TOKEN", "ASSRT Token", CONFIG_GROUP_SECRETS, "secret",
        "ASSRT 字幕源令牌；留空则 ASSRT 未配置。", "assrt_token", True,
    ),
    EnvFieldMeta(
        "SUBDL_API_KEY", "SubDL API Key", CONFIG_GROUP_SECRETS, "secret",
        "SubDL 官方 API 密钥；留空则 SubDL 未配置。", "subdl_api_key", True,
    ),
    EnvFieldMeta(
        "OPENSUBTITLES_API_KEY", "OpenSubtitles API Key", CONFIG_GROUP_SECRETS, "secret",
        "OpenSubtitles REST API 密钥。", "opensubtitles_api_key", True,
    ),
    EnvFieldMeta(
        "OPENSUBTITLES_USERNAME", "OpenSubtitles 用户名", CONFIG_GROUP_SECRETS, "text",
        "下载字幕时与密码一起使用。", "opensubtitles_username",
    ),
    EnvFieldMeta(
        "OPENSUBTITLES_PASSWORD", "OpenSubtitles 密码", CONFIG_GROUP_SECRETS, "secret",
        "下载字幕时与用户名一起使用。", "opensubtitles_password", True,
    ),
    EnvFieldMeta(
        "TODAYS_LINES_USERNAME", "33 台词账号", CONFIG_GROUP_SECRETS, "text",
        "自动化脚本登录账号。", "todays_lines_username",
    ),
    EnvFieldMeta(
        "TODAYS_LINES_PASSWORD", "33 台词密码", CONFIG_GROUP_SECRETS, "secret",
        "本地 token 不可用时用于登录。", "todays_lines_password", True,
    ),
    EnvFieldMeta(
        "TODAYS_LINES_TOKEN", "33 台词 Token", CONFIG_GROUP_SECRETS, "secret",
        "通常由程序自动写入，可手动覆盖。", "todays_lines_token", True,
    ),
    EnvFieldMeta(
        "TODAYS_LINES_TOKEN_TIME", "33 台词 Token 时间", CONFIG_GROUP_SECRETS, "text",
        "Token 缓存时间戳；通常由程序自动写入。", "todays_lines_token_time",
    ),
    EnvFieldMeta(
        "BAIDU_TRANSLATE_APP_ID", "百度翻译 App ID", CONFIG_GROUP_SECRETS, "text",
        "自动化英文补全；留空则跳过翻译。", "baidu_translate_app_id",
    ),
    EnvFieldMeta(
        "BAIDU_TRANSLATE_SECRET", "百度翻译 Secret", CONFIG_GROUP_SECRETS, "secret",
        "需与 App ID 配套使用。", "baidu_translate_secret", True,
    ),
    EnvFieldMeta(
        "SUBTITLE_PROVIDER_PRIORITY", "字幕源优先级", CONFIG_GROUP_STRATEGY, "text",
        "逗号分隔：subhd,subdl,assrt,opensubtitles；越靠前越优先。", "provider_priority",
    ),
    EnvFieldMeta(
        "SUBTITLE_PROVIDER_DISABLED", "禁用字幕源", CONFIG_GROUP_STRATEGY, "text",
        "逗号分隔；留空表示不额外禁用。", "provider_disabled",
    ),
    EnvFieldMeta(
        "SUBTITLE_REQUEST_INTERVAL_MS", "请求间隔 (ms)", CONFIG_GROUP_STRATEGY, "int",
        "降低限流风险；程序会将过低值抬升到不低于 8000。", "request_interval_ms",
    ),
    EnvFieldMeta(
        "SUBTITLE_MOVIE_CONCURRENCY", "电影并发数", CONFIG_GROUP_STRATEGY, "int",
        "同时处理的电影数量；有效范围 1～4。", "movie_concurrency",
    ),
    EnvFieldMeta(
        "SUBTITLE_MIN_BILINGUAL_RATIO", "双语最低占比", CONFIG_GROUP_STRATEGY, "float",
        "0.0～1.0；例如 0.70 表示至少 70% 条目需中英双语。", "subtitle_min_bilingual_ratio",
    ),
    EnvFieldMeta(
        "SUBHD_SEARCH_TIMEOUT", "SubHD 搜索超时 (秒)", CONFIG_GROUP_STRATEGY, "int",
        "建议不低于 60；留空默认 120。", "subhd_search_timeout",
    ),
    EnvFieldMeta(
        "PROVIDER_SEARCH_TIMEOUT", "其他源搜索超时 (秒)", CONFIG_GROUP_STRATEGY, "int",
        "SubDL / ASSRT / OpenSubtitles；留空默认 90。", "provider_search_timeout",
    ),
    EnvFieldMeta(
        "SUBHD_DOWNLOAD_TIMEOUT", "SubHD 下载超时 (秒)", CONFIG_GROUP_STRATEGY, "int",
        "单次 SubHD 下载硬超时；留空默认 180。", "subhd_download_timeout",
    ),
    EnvFieldMeta(
        "PROVIDER_DOWNLOAD_TIMEOUT", "其他源下载超时 (秒)", CONFIG_GROUP_STRATEGY, "int",
        "SubDL / ASSRT / OpenSubtitles 单次下载硬超时；留空默认 60。", "provider_download_timeout",
    ),
    EnvFieldMeta(
        "SUBHD_CAPTCHA_OCR_ENABLED", "验证码 OCR", CONFIG_GROUP_SUBHD, "bool",
        "启用后尝试自动识别 SubHD 验证码。", "subhd_captcha_ocr_enabled",
    ),
    EnvFieldMeta(
        "SUBHD_CAPTCHA_AUTO_SUBMIT_MIN_CONFIDENCE", "OCR 自动提交置信度", CONFIG_GROUP_SUBHD, "float",
        "0.0～1.0；低于该值等待人工确认。", "subhd_captcha_auto_submit_min_confidence",
    ),
    EnvFieldMeta(
        "SUBHD_CAPTCHA_OCR_MAX_ATTEMPTS", "OCR 最大尝试次数", CONFIG_GROUP_SUBHD, "optional_int",
        "留空表示按组合自动计算；填写后限制最大尝试次数。", "subhd_captcha_ocr_max_attempts",
    ),
    EnvFieldMeta(
        "CAPTCHA_SOUND_ENABLED", "验证码提示音", CONFIG_GROUP_SUBHD, "bool",
        "弹出验证码时播放系统提示音。", "captcha_sound_enabled",
    ),
    EnvFieldMeta(
        "HTTP_PROXY", "HTTP 代理", CONFIG_GROUP_NETWORK, "text",
        "例如 http://127.0.0.1:7890；留空表示不使用。", "http_proxy",
    ),
    EnvFieldMeta(
        "HTTPS_PROXY", "HTTPS 代理", CONFIG_GROUP_NETWORK, "text",
        "例如 http://127.0.0.1:7890；留空表示不使用。", "https_proxy",
    ),
    EnvFieldMeta(
        "ASSRT_API_BASE_URL", "ASSRT API 地址", CONFIG_GROUP_NETWORK, "text",
        "通常保持默认；变更官方地址或使用代理网关时修改。", "assrt_api_base_url",
    ),
    EnvFieldMeta(
        "SUBDL_BASE_URL", "SubDL 搜索地址", CONFIG_GROUP_NETWORK, "text",
        "SubDL 搜索接口基础地址。", "subdl_base_url",
    ),
    EnvFieldMeta(
        "SUBDL_DOWNLOAD_BASE_URL", "SubDL 下载地址", CONFIG_GROUP_NETWORK, "text",
        "用于拼接 SubDL 相对下载路径。", "subdl_download_base_url",
    ),
    EnvFieldMeta(
        "SUBDL_LANGUAGES", "SubDL 语言", CONFIG_GROUP_NETWORK, "text",
        "逗号分隔，默认 ZH,EN。", "subdl_languages",
    ),
    EnvFieldMeta(
        "SUBDL_INCLUDE_TRADITIONAL", "SubDL 含繁体", CONFIG_GROUP_NETWORK, "bool",
        "是否允许繁体中文字幕进入后续校验。", "subdl_include_traditional",
    ),
    EnvFieldMeta(
        "OPENSUBTITLES_BASE_URL", "OpenSubtitles API 地址", CONFIG_GROUP_NETWORK, "text",
        "OpenSubtitles REST API 基础地址。", "opensubtitles_base_url",
    ),
    EnvFieldMeta(
        "OPENSUBTITLES_USER_AGENT", "OpenSubtitles User-Agent", CONFIG_GROUP_NETWORK, "text",
        "建议包含应用名称和版本。", "opensubtitles_user_agent",
    ),
    EnvFieldMeta(
        "SUBTITLE_COLLECTION_DATA_DIR", "数据目录", CONFIG_GROUP_LOCAL, "path",
        "字幕输出、解析结果与本地数据库；留空则使用用户目录默认路径。", "data_dir",
    ),
    EnvFieldMeta(
        "SUBTITLE_COLLECTION_PACKAGE_DIST_DIR", "打包输出目录", CONFIG_GROUP_LOCAL, "path",
        "仅影响 Windows 打包脚本输出目录，不影响运行数据。", "package_dist_dir",
    ),
]


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


# 清洗 .env 行内值（去掉包裹引号）
def clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


# 从 .env 文件按行解析键值（保留注释无关，仅读 KEY=）
def read_env_values(env_path: Path | None) -> dict[str, str]:
    if not env_path or not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        values[key] = clean_env_value(value)
    return values


# 按行更新 .env 键值，保留原有注释与无关行
def upsert_env_values(env_path: Path | None, values: dict[str, str]) -> None:
    if not env_path:
        return
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(values)
    updated_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        key = ""
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key.startswith("export "):
                key = key[7:].strip()
        if key in remaining:
            updated_lines.append(f"{key}={remaining.pop(key)}")
        else:
            updated_lines.append(line)

    if remaining:
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        for key, value in remaining.items():
            updated_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


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
        movie_concurrency=settings.movie_concurrency,
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
    subhd_captcha_ocr_max_attempts: int | None = None
    captcha_sound_enabled: bool = True
    subhd_search_timeout: int = DEFAULT_SUBHD_SEARCH_TIMEOUT
    provider_search_timeout: int = DEFAULT_PROVIDER_SEARCH_TIMEOUT
    subhd_download_timeout: int = DEFAULT_SUBHD_DOWNLOAD_TIMEOUT
    provider_download_timeout: int = DEFAULT_PROVIDER_DOWNLOAD_TIMEOUT
    data_dir: Path = field(default_factory=default_data_dir)
    package_dist_dir: str = ""
    tmdb_token: str = ""
    assrt_token: str = ""
    assrt_api_base_url: str = "https://api.assrt.net/v1"
    opensubtitles_api_key: str = ""
    opensubtitles_username: str = ""
    opensubtitles_password: str = ""
    opensubtitles_base_url: str = "https://api.opensubtitles.com/api/v1"
    opensubtitles_user_agent: str = "subtitleInfoCollection v0.1"
    todays_lines_username: str = ""
    todays_lines_password: str = ""
    todays_lines_token: str = ""
    todays_lines_token_time: str = ""
    baidu_translate_app_id: str = ""
    baidu_translate_secret: str = ""
    provider_priority: list[str] = field(default_factory=lambda: list(DEFAULT_PROVIDER_PRIORITY))
    provider_disabled: list[str] = field(default_factory=list)
    request_interval_ms: int = DEFAULT_REQUEST_INTERVAL_MS
    movie_concurrency: int = DEFAULT_MOVIE_CONCURRENCY
    http_proxy: str = ""
    https_proxy: str = ""

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "AppSettings":
        _load_dotenv(env_path)
        return cls(
            data_dir=default_data_dir(),
            package_dist_dir=os.getenv("SUBTITLE_COLLECTION_PACKAGE_DIST_DIR", ""),
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
            todays_lines_username=os.getenv("TODAYS_LINES_USERNAME", ""),
            todays_lines_password=os.getenv("TODAYS_LINES_PASSWORD", ""),
            todays_lines_token=os.getenv("TODAYS_LINES_TOKEN", ""),
            todays_lines_token_time=os.getenv("TODAYS_LINES_TOKEN_TIME", ""),
            baidu_translate_app_id=os.getenv("BAIDU_TRANSLATE_APP_ID", ""),
            baidu_translate_secret=os.getenv("BAIDU_TRANSLATE_SECRET", ""),
            provider_priority=parse_csv(
                os.getenv("SUBTITLE_PROVIDER_PRIORITY"), DEFAULT_PROVIDER_PRIORITY
            ),
            provider_disabled=parse_csv(os.getenv("SUBTITLE_PROVIDER_DISABLED"), []),
            request_interval_ms=max(
                MIN_REQUEST_INTERVAL_MS,
                parse_int(os.getenv("SUBTITLE_REQUEST_INTERVAL_MS"), DEFAULT_REQUEST_INTERVAL_MS),
            ),
            movie_concurrency=max(
                1,
                min(
                    4,
                    parse_int(os.getenv("SUBTITLE_MOVIE_CONCURRENCY"), DEFAULT_MOVIE_CONCURRENCY),
                ),
            ),
            subhd_captcha_ocr_enabled=parse_bool(os.getenv("SUBHD_CAPTCHA_OCR_ENABLED"), True),
            subhd_captcha_auto_submit_min_confidence=max(
                0.0,
                min(
                    1.0,
                    parse_float(os.getenv("SUBHD_CAPTCHA_AUTO_SUBMIT_MIN_CONFIDENCE"), 0.85),
                ),
            ),
            subhd_captcha_ocr_max_attempts=parse_optional_int(
                os.getenv("SUBHD_CAPTCHA_OCR_MAX_ATTEMPTS")
            ),
            captcha_sound_enabled=parse_bool(os.getenv("CAPTCHA_SOUND_ENABLED"), True),
            subhd_search_timeout=max(
                30,
                parse_int(os.getenv("SUBHD_SEARCH_TIMEOUT"), DEFAULT_SUBHD_SEARCH_TIMEOUT),
            ),
            provider_search_timeout=max(
                30,
                parse_int(os.getenv("PROVIDER_SEARCH_TIMEOUT"), DEFAULT_PROVIDER_SEARCH_TIMEOUT),
            ),
            subhd_download_timeout=max(
                30,
                parse_int(os.getenv("SUBHD_DOWNLOAD_TIMEOUT"), DEFAULT_SUBHD_DOWNLOAD_TIMEOUT),
            ),
            provider_download_timeout=max(
                15,
                parse_int(os.getenv("PROVIDER_DOWNLOAD_TIMEOUT"), DEFAULT_PROVIDER_DOWNLOAD_TIMEOUT),
            ),
            http_proxy=os.getenv("HTTP_PROXY", ""),
            https_proxy=os.getenv("HTTPS_PROXY", ""),
        )

    # 将当前设置序列化为可写回 .env 的字符串键值
    def to_env_values(self) -> dict[str, str]:
        return {
            "TMDB_TOKEN": self.tmdb_token,
            "ASSRT_TOKEN": self.assrt_token,
            "ASSRT_API_BASE_URL": self.assrt_api_base_url,
            "SUBDL_API_KEY": self.subdl_api_key,
            "SUBDL_BASE_URL": self.subdl_base_url,
            "SUBDL_DOWNLOAD_BASE_URL": self.subdl_download_base_url,
            "SUBDL_LANGUAGES": self.subdl_languages,
            "SUBDL_INCLUDE_TRADITIONAL": "true" if self.subdl_include_traditional else "false",
            "OPENSUBTITLES_API_KEY": self.opensubtitles_api_key,
            "OPENSUBTITLES_USERNAME": self.opensubtitles_username,
            "OPENSUBTITLES_PASSWORD": self.opensubtitles_password,
            "OPENSUBTITLES_BASE_URL": self.opensubtitles_base_url,
            "OPENSUBTITLES_USER_AGENT": self.opensubtitles_user_agent,
            "TODAYS_LINES_USERNAME": self.todays_lines_username,
            "TODAYS_LINES_PASSWORD": self.todays_lines_password,
            "TODAYS_LINES_TOKEN": self.todays_lines_token,
            "TODAYS_LINES_TOKEN_TIME": self.todays_lines_token_time,
            "BAIDU_TRANSLATE_APP_ID": self.baidu_translate_app_id,
            "BAIDU_TRANSLATE_SECRET": self.baidu_translate_secret,
            "SUBTITLE_PROVIDER_PRIORITY": ",".join(self.provider_priority),
            "SUBTITLE_PROVIDER_DISABLED": ",".join(self.provider_disabled),
            "SUBTITLE_REQUEST_INTERVAL_MS": str(self.request_interval_ms),
            "SUBTITLE_MOVIE_CONCURRENCY": str(self.movie_concurrency),
            "SUBTITLE_MIN_BILINGUAL_RATIO": f"{self.subtitle_min_bilingual_ratio:.2f}",
            "SUBHD_CAPTCHA_OCR_ENABLED": "true" if self.subhd_captcha_ocr_enabled else "false",
            "SUBHD_CAPTCHA_AUTO_SUBMIT_MIN_CONFIDENCE": (
                f"{self.subhd_captcha_auto_submit_min_confidence:.2f}"
            ),
            "SUBHD_CAPTCHA_OCR_MAX_ATTEMPTS": (
                "" if self.subhd_captcha_ocr_max_attempts is None
                else str(self.subhd_captcha_ocr_max_attempts)
            ),
            "SUBHD_SEARCH_TIMEOUT": str(self.subhd_search_timeout),
            "PROVIDER_SEARCH_TIMEOUT": str(self.provider_search_timeout),
            "SUBHD_DOWNLOAD_TIMEOUT": str(self.subhd_download_timeout),
            "PROVIDER_DOWNLOAD_TIMEOUT": str(self.provider_download_timeout),
            "CAPTCHA_SOUND_ENABLED": "true" if self.captcha_sound_enabled else "false",
            "SUBTITLE_COLLECTION_PACKAGE_DIST_DIR": self.package_dist_dir,
            "SUBTITLE_COLLECTION_DATA_DIR": str(self.data_dir) if self.data_dir else "",
            "HTTP_PROXY": self.http_proxy,
            "HTTPS_PROXY": self.https_proxy,
        }

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
