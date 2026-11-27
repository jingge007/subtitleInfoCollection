from __future__ import annotations

import math
import re

from ..models import MovieInfo, SubtitleCandidate

ENGLISH_TITLE_STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

# 剧集集数标记（电影任务应拒绝）
_EPISODE_MARKER_RE = re.compile(
    r"(?:s\d{1,2}e\d{1,3}|\bep?\s*\d{1,3}\b|第\s*\d+\s*[季集话期])",
    re.IGNORECASE,
)
# 候选中的年份（排除单独出现的分辨率数字已由 19/20 前缀约束）
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
# 续集/部数标记
_SEQUEL_MARKER_RE = re.compile(
    r"(?:^|[\s._\-])(?:(?:vol(?:ume)?\.?\s*)|(?:part\.?\s*)|(?:第\s*))?"
    r"(?:ii|iii|iv|vi{0,3}|[2-9]|[１２３４５６７８９])(?:$|[\s._\-：:])",
    re.IGNORECASE,
)
_IDENTITY_DESCRIPTION_MAX = 120


def normalize_text(value: str = "") -> str:
    normalized = re.sub(r"['’]s\b", "s", value.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", normalized)).strip()


def _tokens(value: str = "") -> list[str]:
    normalized = normalize_text(value)
    return normalized.split() if normalized else []


def _contains_token_sequence(target_tokens: list[str], phrase: str = "") -> bool:
    phrase_tokens = _tokens(phrase)
    if not phrase_tokens:
        return False
    size = len(phrase_tokens)
    return any(
        target_tokens[index : index + size] == phrase_tokens
        for index in range(len(target_tokens) - size + 1)
    )


def _significant_title_tokens(value: str = "") -> set[str]:
    result: set[str] = set()
    for token in _tokens(value):
        if token.isdigit() or token in ENGLISH_TITLE_STOP_WORDS:
            continue
        if len(token) >= 3 or re.search(r"[\u3400-\u9fff]", token):
            result.add(token)
    return result


# 构建字幕源搜索关键词（含年份变体，提高同名异年区分度）
def build_movie_search_keywords(movie: MovieInfo) -> list[str]:
    values = [movie.title_zh, movie.title, movie.original_title]
    base = list(dict.fromkeys(value for value in values if value and len(value.strip()) >= 2))
    if not movie.year:
        return base
    year = str(movie.year)
    with_year = [f"{keyword} {year}" for keyword in base]
    return list(dict.fromkeys([*base, *with_year]))


# 去掉 SubHD 页面容器等过长描述，避免串词假阳性
def _slim_description_for_identity(description: str = "") -> str:
    text = re.sub(r"页面内容[：:].*", "", description or "", flags=re.DOTALL).strip()
    if len(text) > _IDENTITY_DESCRIPTION_MAX:
        return text[:_IDENTITY_DESCRIPTION_MAX]
    return text


def _candidate_identity_text(candidate: SubtitleCandidate) -> str:
    attrs = candidate.raw.get("attributes") if isinstance(candidate.raw, dict) else {}
    attrs = attrs if isinstance(attrs, dict) else {}
    feature_details = attrs.get("feature_details") if isinstance(attrs.get("feature_details"), dict) else {}
    parts = [
        candidate.subtitle_title,
        _slim_description_for_identity(candidate.description),
        *candidate.file_names,
        feature_details.get("title"),
        feature_details.get("original_title"),
        feature_details.get("year"),
        feature_details.get("tmdb_id"),
        feature_details.get("imdb_id"),
    ]
    return " ".join(str(part) for part in parts if part)


def _candidate_tmdb_id(candidate: SubtitleCandidate) -> int | None:
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    feature_details = attrs.get("feature_details") if isinstance(attrs.get("feature_details"), dict) else {}
    for value in [feature_details.get("tmdb_id"), attrs.get("tmdb_id"), raw.get("tmdb_id")]:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


# 从文本提取 19xx/20xx 年份集合
def extract_years(text: str = "") -> set[int]:
    return {int(match) for match in _YEAR_RE.findall(text or "")}


# 候选是否像剧集单集（电影任务应拒绝）
def has_episode_marker(text: str = "") -> bool:
    return bool(_EPISODE_MARKER_RE.search(text or ""))


# 目标片名自身是否已带续集/部数
def _movie_has_sequel_marker(movie: MovieInfo) -> bool:
    joined = " ".join(
        part for part in [movie.title_zh, movie.title, movie.original_title] if part
    )
    return bool(_SEQUEL_MARKER_RE.search(normalize_text(joined)))


# 候选是否相对目标片名表现为续集/系列扩展
def has_sequel_conflict(candidate: SubtitleCandidate, movie: MovieInfo) -> bool:
    if _movie_has_sequel_marker(movie):
        return False
    identity = _candidate_identity_text(candidate)
    identity_norm = normalize_text(identity)
    if not identity_norm:
        return False

    # 中文：候选 token 以目标中文片名开头且更长（功夫 → 功夫熊猫2）
    title_zh = (movie.title_zh or "").strip()
    if len(title_zh) >= 2:
        zh_norm = normalize_text(title_zh)
        for token in _tokens(identity):
            if token.startswith(zh_norm) and len(token) > len(zh_norm):
                return True

    # 英文：完整标题序列命中后，紧跟续集标记或额外系列显著词
    for title in [movie.title, movie.original_title]:
        title_tokens = [
            token
            for token in _tokens(title)
            if token not in ENGLISH_TITLE_STOP_WORDS and not token.isdigit()
        ]
        if not title_tokens:
            continue
        identity_tokens = _tokens(identity)
        size = len(title_tokens)
        for index in range(len(identity_tokens) - size + 1):
            if identity_tokens[index : index + size] != title_tokens:
                continue
            rest = identity_tokens[index + size :]
            if not rest:
                continue
            # 紧跟 2 / ii / vol 等
            rest_text = " ".join(rest[:3])
            if _SEQUEL_MARKER_RE.search(f" {rest_text} "):
                return True
            # 紧跟额外显著英文词（Kung Fu + Panda）
            movie_significant = _significant_title_tokens(movie.title) | _significant_title_tokens(
                movie.original_title
            )
            next_token = rest[0]
            if (
                next_token not in ENGLISH_TITLE_STOP_WORDS
                and not next_token.isdigit()
                and (len(next_token) >= 3 or re.search(r"[\u3400-\u9fff]", next_token))
                and next_token not in movie_significant
            ):
                return True
    # 候选整体带续集标记且目标没有（如 Incredibles.2）
    if _SEQUEL_MARKER_RE.search(f" {identity_norm} "):
        # 仅当标题显著词已出现在候选中才视为冲突，避免误伤无关数字
        significant = _significant_title_tokens(movie.title) | _significant_title_tokens(
            movie.original_title
        )
        if significant and significant & set(_tokens(identity)):
            return True
    return False


# 候选明确年份与目标年份冲突
def has_year_conflict(candidate: SubtitleCandidate, movie: MovieInfo) -> bool:
    if not movie.year:
        return False
    years = extract_years(_candidate_identity_text(candidate))
    if not years:
        return False
    return movie.year not in years


# 短中文片名（≤2 字）禁止仅靠英文词交集过关
def _is_short_chinese_title(movie: MovieInfo) -> bool:
    title_zh = (movie.title_zh or "").strip()
    return bool(title_zh) and len(title_zh) <= 2


_GENERIC_SHORT_ENGLISH_TITLES = frozenset(
    {"up", "it", "her", "us", "one", "two", "big", "war", "elf", "ray", "bob", "max"}
)


# 过短/泛化英文原标题：禁止单 token 英文兜底（避免 Up 命中 Up in the Air）
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


def get_resolution_score(text: str = "") -> float:
    value = text.lower()
    if re.search(r"2160p|4k|uhd", value):
        return 20
    if re.search(r"1080p|bluray|blu-ray|web-dl|webrip", value):
        return 15
    if re.search(r"720p|hdtv", value):
        return 8
    return 0


def get_format_score(subtitle_format: str = "") -> float:
    if subtitle_format == "ass":
        return 12
    if subtitle_format == "srt":
        return 10
    return 0


def get_title_match_score(candidate: SubtitleCandidate, movie: MovieInfo) -> float:
    target_tokens = _tokens(_candidate_identity_text(candidate))
    score = 0.0

    if movie.title_zh and _contains_token_sequence(target_tokens, movie.title_zh):
        score += 80
    if movie.title and _contains_token_sequence(target_tokens, movie.title):
        score += 60
    if (
        movie.original_title
        and normalize_text(movie.original_title) != normalize_text(movie.title)
        and _contains_token_sequence(target_tokens, movie.original_title)
    ):
        score += 55

    target_token_set = set(target_tokens)
    words = _significant_title_tokens(movie.title) | _significant_title_tokens(movie.original_title)
    for word in words & target_token_set:
        score += 5

    return score


# 计算年份分：同年奖励、错年惩罚、无年不加不减
def compute_year_score(candidate: SubtitleCandidate, movie: MovieInfo) -> float:
    if not movie.year:
        return 0.0
    years = extract_years(candidate.metadata_text())
    if movie.year in years:
        return 100.0
    if years:
        return -150.0
    return 0.0


def has_movie_identity_match(candidate: SubtitleCandidate, movie: MovieInfo) -> bool:
    identity = _candidate_identity_text(candidate)
    if has_episode_marker(identity):
        return False
    if has_year_conflict(candidate, movie):
        return False
    if has_sequel_conflict(candidate, movie):
        return False

    if movie.tmdb_id and _candidate_tmdb_id(candidate) == movie.tmdb_id:
        return True

    target_tokens = _tokens(identity)
    short_english = _is_generic_short_english_title(movie)
    # 短英文原标题时优先/仅用中文名做序列匹配，避免 Up ⊆ Up in the Air
    title_candidates = [movie.title_zh, movie.title, movie.original_title]
    if short_english:
        title_candidates = [movie.title_zh]
        if (
            movie.title
            and normalize_text(movie.title) != normalize_text(movie.original_title or "")
            and len((movie.title or "").strip()) > 3
        ):
            title_candidates.append(movie.title)
    title_hit = any(
        title and _contains_token_sequence(target_tokens, title)
        for title in title_candidates
        if title
    )
    if title_hit:
        return True

    # 短中文片名：不允许显著词交集兜底（避免「功夫」命中「功夫熊猫」）
    if _is_short_chinese_title(movie):
        return False
    if short_english:
        return False

    significant_words = _significant_title_tokens(movie.title) | _significant_title_tokens(
        movie.original_title
    )
    if not significant_words:
        return False
    matched_words = significant_words & set(target_tokens)
    required_matches = 1 if len(significant_words) == 1 else 2
    return len(matched_words) >= required_matches


# 明确中英双语标记加分，避免仅靠高下载量的空语言包抢先
_BILINGUAL_LANGUAGE_RE = re.compile(r"(中英双语|简英|双语)")
_BILINGUAL_FILENAME_RE = re.compile(
    r"(简体\s*[&+_]\s*英文|简繁英|chs\s*[&_.-]\s*eng|eng\s*[&_.-]\s*chs|chs_eng|zh[-_.]?en|中英|简英)",
    re.I,
)


def bilingual_meta_score(candidate: SubtitleCandidate) -> float:
    score = 0.0
    if _BILINGUAL_LANGUAGE_RE.search(candidate.language_type or ""):
        score += 150.0
    blob = " ".join(
        str(part)
        for part in [candidate.subtitle_title, *candidate.file_names, candidate.description or ""]
        if part
    )
    if _BILINGUAL_FILENAME_RE.search(blob):
        score += 40.0
    return score


def score_candidate(candidate: SubtitleCandidate, movie: MovieInfo) -> SubtitleCandidate:
    language_score = 1000.0
    bilingual_score = bilingual_meta_score(candidate)
    rating_score = float(movie.rating or 0) * 100
    year_score = compute_year_score(candidate, movie)
    download_score = math.log(float(candidate.download_count or 0) + 1) * 15
    provider_rating_score = float(candidate.rating or 0) * 10
    title_match_score = get_title_match_score(candidate, movie)
    resolution_score = get_resolution_score(candidate.metadata_text())
    format_score = get_format_score(candidate.subtitle_format)
    total = (
        language_score
        + bilingual_score
        + rating_score
        + year_score
        + download_score
        + provider_rating_score
        + title_match_score
        + resolution_score
        + format_score
    )
    candidate.total_score = round(total, 2)
    candidate.scores = {
        "languageScore": language_score,
        "bilingualScore": bilingual_score,
        "ratingScore": round(rating_score, 2),
        "yearScore": year_score,
        "downloadScore": round(download_score, 2),
        "providerRatingScore": round(provider_rating_score, 2),
        "titleMatchScore": title_match_score,
        "resolutionScore": resolution_score,
        "formatScore": format_score,
    }
    return candidate


def sort_candidates(candidates: list[SubtitleCandidate]) -> list[SubtitleCandidate]:
    return sorted(
        candidates,
        key=lambda item: (
            item.total_score,
            item.download_count,
            item.rating,
            item.provider_subtitle_id,
        ),
        reverse=True,
    )
