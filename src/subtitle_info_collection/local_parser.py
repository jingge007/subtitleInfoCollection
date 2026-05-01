from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .adapters.tmdb import TmdbClient
from .engines.subtitle_engine import (
    TRADITIONAL_ONLY_CHARS,
    decode_subtitle_bytes,
    filter_to_simplified_chinese,
    parse_subtitle_text,
    validate_is_simplified_chinese_english,
)
from .models import MovieInfo, SubtitleEntry

NOISE_RE = re.compile(
    r"\b(?:2160p|1080p|720p|480p|4k|hdr|hdrip|brrip|bluray|blu-?ray|bdrip|"
    r"webrip|web-?dl|webdl|dvdrip|x264|x265|h264|h265|hevc|aac|dts|ddp|"
    r"atmos|remux|proper|repack|extended|imax|multi|uhd|sub|srt|ass|ssa|"
    r"chs|cht|eng|gb|big5|中字|双语|中英|简中|繁中|字幕)\b",
    re.I,
)


def validate_bilingual_subtitle(text: str) -> tuple[bool, str]:
    """Validate if subtitle contains simplified Chinese and English bilingual content.
    
    Returns:
        (is_valid, message): tuple of validation result and descriptive message
    """
    return validate_is_simplified_chinese_english(text)


@dataclass(slots=True)
class ParsedSubtitleFile:
    source_file: Path
    movie: MovieInfo
    original_subtitle_count: int
    subtitles: list[SubtitleEntry]
    matched_keyword: str = ""

    def payload(self) -> dict[str, object]:
        movie_data = self.movie.to_export_dict()
        return {
            "title": movie_data.get("nm", ""),
            "movieId": movie_data.get("movieId", ""),
            "coverUrl": movie_data.get("img", ""),
            "movieData": movie_data,
            "moviesData": [movie_data],
            "subtitlesData": [item.to_export_dict() for item in self.subtitles],
        }


def build_movie_search_keywords(filename: str) -> list[str]:
    base_name = re.sub(r"\.[^.]+$", "", Path(filename).name)
    spaced = re.sub(r"[._-]+", " ", base_name)
    cleaned = re.sub(r"[\[\(（【].*?[\]\)）】]", " ", spaced)
    cleaned = re.sub(r"\b\d{3,4}x\d{3,4}\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:cd|disc)\s?\d+\b", " ", cleaned, flags=re.I)
    cleaned = NOISE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    chinese = re.search(r"[\u3400-\u9fff][\u3400-\u9fffA-Za-z0-9 :：·.-]*", cleaned)
    english = re.search(r"[A-Za-z][A-Za-z0-9'’:\- ]+", cleaned)
    values = [base_name, spaced, cleaned]
    if chinese:
        values.append(chinese.group(0).strip())
    if english:
        values.append(english.group(0).strip())
    result = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _fallback_movie(path: Path) -> MovieInfo:
    title = build_movie_search_keywords(path.name)[-1] if build_movie_search_keywords(path.name) else path.stem
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "local"
    return MovieInfo(movie_id=f"local-{slug}", title=title, original_title=title, title_zh="")


async def _match_movie(path: Path, tmdb_token: str = "") -> tuple[MovieInfo, str]:
    if not tmdb_token:
        return _fallback_movie(path), ""
    client = TmdbClient(tmdb_token)
    latest_keyword = ""
    for keyword in build_movie_search_keywords(path.name):
        latest_keyword = keyword
        try:
            movie = await client.search_movie(keyword)
        except Exception:
            continue
        if movie:
            return movie, keyword
    return _fallback_movie(path), latest_keyword


async def parse_local_subtitle_file(path: Path, tmdb_token: str = "") -> ParsedSubtitleFile:
    suffix = path.suffix.lower().lstrip(".")
    if suffix not in {"srt", "ass"}:
        raise ValueError("仅支持 .srt 和 .ass 字幕文件")

    try:
        file_bytes = path.read_bytes()
        decoded = decode_subtitle_bytes(file_bytes)
    except Exception as e:
        raise ValueError(f"字幕文件无法读取或解码：{e}")
    
    if not decoded.content:
        raise ValueError("字幕文件无法解码")

    full_text = decoded.content
    is_valid, validation_msg = validate_bilingual_subtitle(full_text)
    if not is_valid:
        raise ValueError(f"字幕校验失败：{validation_msg}")

    movie, keyword = await _match_movie(path, tmdb_token)
    parsed = parse_subtitle_text(decoded.content, suffix, movie.movie_id)
    original_count = len(parsed)
    filtered = [
        item
        for item in parsed
        if item.zh_content.strip() and item.en_content.strip()
    ]
    if not filtered:
        raise ValueError(f"未找到包含中英文的字幕内容（原始 {original_count} 条字幕全部被过滤）")

    if len(filtered) < 5:
        raise ValueError(f"有效双语字幕条目仅 {len(filtered)} 条，不足 5 条，判定为无效电影字幕文件")

    normalized = [
        SubtitleEntry(
            subtitles_id=f"{movie.movie_id}-{index}",
            movie_id=movie.movie_id,
            start_time=item.start_time,
            end_time=item.end_time,
            zh_content=item.zh_content,
            en_content=item.en_content,
            content=item.content,
        )
        for index, item in enumerate(filtered, start=1)
    ]
    return ParsedSubtitleFile(
        source_file=path,
        movie=movie,
        original_subtitle_count=original_count,
        subtitles=normalized,
        matched_keyword=keyword,
    )
