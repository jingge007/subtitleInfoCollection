from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _clean_description_value(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        parts = [_clean_description_value(item) for item in value]
        return "、".join(item for item in parts if item)
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text


def _single_language_label(value: str) -> str:
    text = value.strip()
    key = text.replace("_", "-").replace(" ", "-").lower()
    exact_map = {
        "ze": "中英双语",
        "zh-cn": "简体中文",
        "zh-hans": "简体中文",
        "chs": "简体中文",
        "zh-tw": "繁体中文",
        "zh-hant": "繁体中文",
        "cht": "繁体中文",
        "en": "英语",
        "eng": "英语",
        "english": "英语",
        "zh": "中文",
        "zho": "中文",
        "chi": "中文",
        "chinese": "中文",
        "cn": "中文",
    }
    if key in exact_map:
        return exact_map[key]
    if any(token in key for token in ["双语", "中英", "简英", "bilingual"]):
        return "中英双语"
    if any(token in key for token in ["简体", "简中", "simplified"]):
        return "简体中文"
    if any(token in key for token in ["繁体", "繁中", "traditional"]):
        return "繁体中文"
    if "english" in key or "英语" in key or "英文" in key:
        return "英语"
    if "chinese" in key or "中文" in key:
        return "中文"
    return text


def chinese_language_label(value: object) -> str:
    text = _clean_description_value(value)
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"[/,，;；|&+]+", text) if part.strip()]
    if len(parts) <= 1:
        return _single_language_label(text)
    labels = [_single_language_label(part) for part in parts]
    return "/".join(dict.fromkeys(label for label in labels if label))


def format_chinese_description(*items: tuple[str, object], limit: int = 1000) -> str:
    parts: list[str] = []
    seen: set[tuple[str, str]] = set()
    for label, value in items:
        text = _clean_description_value(value)
        if not text:
            continue
        key = (label, text)
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"{label}：{text}")
    return "；".join(parts)[:limit]


@dataclass(slots=True)
class MovieInfo:
    """电影信息数据类"""
    movie_id: str  # 电影ID
    tmdb_id: int | None = None  # TMDb电影ID
    title: str = ""  # 电影标题（英文）
    original_title: str = ""  # 原始标题
    title_zh: str = ""  # 中文标题
    year: int = 0  # 年份
    rating: float = 0.0  # 评分
    vote_count: int = 0  # 投票数
    popularity: float = 0.0  # 热度
    release_date: str = ""  # 上映日期
    overview: str = ""  # 剧情简介（英文）
    overview_zh: str = ""  # 剧情简介（中文）
    poster_url: str = ""  # 海报URL
    raw: dict[str, Any] = field(default_factory=dict)  # 原始数据

    @property
    def display_title(self) -> str:
        return self.title_zh or self.title or self.original_title or self.movie_id

    @classmethod
    def from_tmdb(cls, raw: dict[str, Any], zh_raw: dict[str, Any] | None = None) -> "MovieInfo":
        zh_raw = zh_raw or {}
        tmdb_id = raw.get("id")
        release_date = raw.get("release_date") or zh_raw.get("release_date") or ""
        poster_path = zh_raw.get("poster_path") or raw.get("poster_path") or ""
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
        year = int(str(release_date or "0")[:4] or 0)
        return cls(
            movie_id=f"tmdb-{tmdb_id}",
            tmdb_id=int(tmdb_id) if tmdb_id is not None else None,
            title=raw.get("title") or "",
            original_title=raw.get("original_title") or raw.get("title") or "",
            title_zh=zh_raw.get("title") or "",
            year=year,
            rating=float(raw.get("vote_average") or 0),
            vote_count=int(raw.get("vote_count") or 0),
            popularity=float(raw.get("popularity") or 0),
            release_date=release_date,
            overview=raw.get("overview") or "",
            overview_zh=zh_raw.get("overview") or "",
            poster_url=poster_url,
            raw={"tmdb": raw, "tmdb_zh": zh_raw},
        )

    def to_export_dict(self) -> dict[str, Any]:
        movie_id = self.movie_id
        overview_cn = self.overview_zh or self.overview
        release_desc = f"{self.release_date} 上映" if self.release_date else ""
        return {
            "act": "",
            "cat": "",
            "dir": "",
            "dur": 0,
            "enm": self.original_title or self.title,
            "fra": "",
            "frt": self.release_date,
            "ftime": "",
            "globalReleased": bool(self.release_date),
            "id": movie_id,
            "img": self.poster_url,
            "movieAlias": "",
            "movieType": 0,
            "movieTypeDesc": "电影",
            "nm": self.title_zh or self.title,
            "onlinePlay": False,
            "pubDesc": release_desc,
            "renderStyle": 0,
            "rt": f"{self.rating:.1f}" if self.rating else "",
            "sc": self.vote_count,
            "show": "",
            "showst": 0,
            "src": "tmdb",
            "star": "",
            "stype": 0,
            "type": 0,
            "ver": "",
            "vodPlay": False,
            "wish": 0,
            "wishst": 0,
            "movieId": movie_id,
            "tmdbId": self.tmdb_id,
            "title": self.title,
            "originalTitle": self.original_title,
            "titleZh": self.title_zh,
            "year": self.year,
            "rating": self.rating,
            "voteCount": self.vote_count,
            "popularity": self.popularity,
            "releaseDate": self.release_date,
            "overview": overview_cn,
            "overviewZh": overview_cn,
            "overviewOriginal": self.overview,
        }


@dataclass(slots=True)
class SubtitleCandidate:
    """字幕候选数据类"""
    provider: str  # 字幕源提供商
    provider_subtitle_id: str  # 字幕源字幕ID
    movie_id: str  # 电影ID
    movie_title: str  # 电影标题
    movie_original_title: str = ""  # 电影原始标题
    movie_title_zh: str = ""  # 电影中文标题
    movie_year: int = 0  # 电影年份
    subtitle_title: str = ""  # 字幕标题
    language_type: str = ""  # 语言类型
    subtitle_format: str = ""  # 字幕格式
    download_count: int = 0  # 下载次数
    rating: float = 0.0  # 评分
    detail_url: str = ""  # 详情URL
    download_url: str = ""  # 下载URL
    description: str = ""  # 中文描述
    file_names: list[str] = field(default_factory=list)  # 文件名列表
    total_score: float = 0.0  # 总评分
    scores: dict[str, float] = field(default_factory=dict)  # 各项评分
    raw: dict[str, Any] = field(default_factory=dict)  # 原始数据
    collect_time: str = field(default_factory=now_iso)  # 采集时间

    def metadata_text(self) -> str:
        return " ".join(
            [
                self.subtitle_title,
                self.language_type,
                self.subtitle_format,
                self.description,
                *self.file_names,
            ]
        )

    def to_export_dict(self, is_best: bool = False) -> dict[str, Any]:
        description = self.description or format_chinese_description(
            ("字幕标题", self.subtitle_title),
            ("语言", self.language_type),
            ("格式", self.subtitle_format),
            ("文件名", self.file_names),
        )
        return {
            "provider": self.provider,
            "providerSubtitleId": self.provider_subtitle_id,
            "movieId": self.movie_id,
            "movieTitle": self.movie_title,
            "movieOriginalTitle": self.movie_original_title,
            "movieTitleZh": self.movie_title_zh,
            "movieYear": self.movie_year,
            "subtitleTitle": self.subtitle_title,
            "languageType": self.language_type,
            "subtitleFormat": self.subtitle_format,
            "downloadCount": self.download_count,
            "rating": self.rating,
            "detailUrl": self.detail_url,
            "downloadUrl": self.download_url,
            "description": description,
            "fileNames": self.file_names,
            "totalScore": self.total_score,
            "scores": self.scores,
            "isBest": is_best,
            "status": "confirmed" if is_best else "candidate",
            "collectTime": self.collect_time,
        }


@dataclass(slots=True)
class SubtitleEntry:
    """字幕条目数据类"""
    subtitles_id: str  # 字幕ID
    movie_id: str  # 电影ID
    start_time: str  # 开始时间
    end_time: str  # 结束时间
    zh_content: str  # 中文内容
    en_content: str  # 英文内容
    content: str  # 原始内容

    def to_export_dict(self) -> dict[str, str]:
        return {
            "subtitlesId": self.subtitles_id,
            "movieId": self.movie_id,
            "startTime": self.start_time,
            "endTime": self.end_time,
            "zhContent": self.zh_content,
            "enContent": self.en_content,
            "content": self.content,
        }


@dataclass(slots=True)
class DownloadedPayload:
    """已下载字幕载荷数据类"""
    file_name: str  # 文件名
    content: bytes  # 文件内容
    source_url: str = ""  # 来源URL
    content_type: str = ""  # 内容类型


@dataclass(slots=True)
class DownloadResult:
    """下载结果数据类"""
    provider: str  # 字幕源提供商
    provider_subtitle_id: str  # 字幕源字幕ID
    subtitle_title: str  # 字幕标题
    movie_title: str  # 电影标题
    saved_paths: list[Path]  # 保存路径列表

    def to_export_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "providerSubtitleId": self.provider_subtitle_id,
            "subtitleTitle": self.subtitle_title,
            "movieTitle": self.movie_title,
            "savedPaths": [str(path) for path in self.saved_paths],
        }


@dataclass(slots=True)
class FailedRecord:
    """失败记录数据类"""
    movie: MovieInfo | None  # 电影信息
    movie_name: str  # 电影名称
    provider: str  # 字幕源提供商
    error_type: str  # 错误类型
    error: str  # 错误信息
    subtitle_title: str = ""  # 字幕标题
    provider_subtitle_id: str = ""  # 字幕源字幕ID
    time: str = field(default_factory=now_iso)  # 时间

    def to_export_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["movie"] = self.movie.to_export_dict() if self.movie else None
        data["reasonCn"] = failure_reason_cn(self.error_type, self.provider, self.error)
        return data


@dataclass(slots=True)
class TaskConfig:
    """任务配置数据类"""
    subdl_api_key: str = ""
    subdl_base_url: str = "https://api.subdl.com/api/v1"
    subdl_download_base_url: str = "https://dl.subdl.com"
    subdl_languages: str = "ZH,EN"
    subdl_include_traditional: bool = False
    subhd_captcha_ocr_enabled: bool = True
    subhd_captcha_auto_submit_min_confidence: float = 0.85
    subhd_search_timeout: int = 60
    provider_search_timeout: int = 45
    year: int = 2026  # 年份
    limit: int = 100  # 限制数量
    movie_source: str = "tmdb"  # 电影来源
    subtitle_providers: list[str] = field(  # 字幕源提供商列表
        default_factory=lambda: ["subhd", "subdl", "assrt", "opensubtitles"]
    )
    fallback_enabled: bool = True  # 是否启用兜底
    download_enabled: bool = True  # 是否启用下载
    subtitle_min_bilingual_ratio: float = 0.70  # 下载字幕内容双语条目最低占比
    request_interval_ms: int = 8_000  # 请求间隔（毫秒）
    vote_count_min: int = 500  # 最小投票数
    output_root: Path | None = None  # 输出根目录
    manual_movies: list[MovieInfo] = field(default_factory=list)  # 手动指定的电影列表
    tmdb_token: str = ""  # TMDb访问令牌
    assrt_token: str = ""  # ASSRT访问令牌
    assrt_api_base_url: str = "https://api.assrt.net/v1"  # ASSRT API基础URL
    opensubtitles_api_key: str = ""  # OpenSubtitles API密钥
    opensubtitles_username: str = ""  # OpenSubtitles用户名
    opensubtitles_password: str = ""  # OpenSubtitles密码
    opensubtitles_base_url: str = "https://api.opensubtitles.com/api/v1"  # OpenSubtitles API基础URL
    opensubtitles_user_agent: str = "subtitleInfoCollection v0.1"  # OpenSubtitles用户代理
    provider_priority: list[str] = field(  # 字幕源优先级
        default_factory=lambda: ["subhd", "subdl", "assrt", "opensubtitles"]
    )
    provider_disabled: list[str] = field(default_factory=list)  # 禁用的字幕源
    proxies: dict[str, str] = field(default_factory=dict)  # 代理设置


def failure_reason_cn(error_type: str, provider: str = "", raw: str = "") -> str:
    prefix = f"【{provider}】" if provider and provider != "-" else ""
    mapping = {
        "NETWORK_UNREACHABLE": "网络不可达或请求超时，请稍后重试或检查代理/网络。",
        "RATE_LIMITED": "触发访问频率限制，请降低采集速度后重试。",
        "NO_MATCH": "没有找到符合要求的简体中文 + 英文双语 ass/srt 字幕。",
        "PARSE_FAILED": "页面或接口结构异常，目标站点可能已经变化。",
        "DOWNLOAD_BLOCKED": "下载被阻止，可能需要登录、验证码或被站点拦截。",
        "DOWNLOAD_QUOTA_EXCEEDED": "OpenSubtitles 下载额度已用完或账号权限不足，请等待额度重置、升级账号，或暂时禁用该字幕源下载。",
        "DOWNLOAD_FAILED": "字幕下载失败，可能是下载链接失效、压缩包异常或保存失败。",
        "PROVIDER_DISABLED": "字幕源未启用或缺少必要配置。",
        "VERIFICATION_REQUIRED": "需要验证码验证，本条字幕未能自动完成下载。",
        "INVALID_FORMAT": "候选字幕格式不符合要求，只支持 ass 或 srt。",
        "INVALID_LANGUAGE": "候选字幕语言不符合要求，需要简体中文 + 英文双语。",
        "DECODE_FAILED": "下载到的字幕文件编码无法可靠识别。",
        "CONTENT_VALIDATION_FAILED": "下载到的字幕内容没有同时包含中文和英文对白。",
    }
    suffix = f" 原始信息：{raw}" if raw else ""
    return f"{prefix}{mapping.get(error_type, '采集失败，原因暂时无法自动归类。')}{suffix}"
