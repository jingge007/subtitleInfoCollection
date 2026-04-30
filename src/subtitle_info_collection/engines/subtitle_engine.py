from __future__ import annotations

import html
import re
from dataclasses import dataclass

from ..errors import ErrorType
from ..models import SubtitleCandidate, SubtitleEntry

SRT_TIME_RANGE_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)
SRT_BLOCK_RE = re.compile(
    r"(?:^|\n)\s*(?:\d+\s*\n)?"
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})(?:[^\n]*)\n"
    r"(?P<body>.*?)(?=\n\s*\n|\Z)",
    re.S,
)
ASS_SECTION_RE = re.compile(r"^\[[^\]]+\]$")
CHINESE_RE = re.compile(r"[\u3400-\u9fff]")
CHINESE_GLOBAL_RE = re.compile(r"[\u3400-\u9fff]")
ENGLISH_RE = re.compile(r"[A-Za-z]")
ENGLISH_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'.-]*")
REPLACEMENT_RE = re.compile("\ufffd")

SUPPORTED_FORMATS = {"ass", "srt"}
DECODE_ENCODINGS = ["utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16", "utf-16le", "utf-16be"]

SIMPLIFIED_MARKER_RE = re.compile(
    r"(简体|简中|简英|简繁英|中文|中英|双语|chs|zh[-_ ]?cn|simplified|gb2312|gbk|gb18030)",
    re.I,
)
ENGLISH_MARKER_RE = re.compile(
    r"(英文|英语|英字|英双|english|eng(?:lish)?|\ben\b|en[-_ ]?us|en[-_ ]?gb)",
    re.I,
)
BILINGUAL_MARKER_RE = re.compile(
    r"(双语|中英|简英|简繁英|chs[&+._ -]*eng|zh[-_ ]?cn[&+._ -]*en|"
    r"cn[&+._ -]*en|chinese bilingual|\bze\b)",
    re.I,
)
TRADITIONAL_ONLY_MARKER_RE = re.compile(
    r"(繁体|繁中|cht|zh[-_ ]?tw|traditional|big5)",
    re.I,
)


@dataclass(frozen=True, slots=True)
class DecodedSubtitle:
    encoding: str
    content: str
    score: float
    replacement_count: int


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    valid: bool
    error_type: str = ""
    reason: str = ""
    subtitle_format: str = ""


@dataclass(frozen=True, slots=True)
class DownloadValidation:
    valid: bool
    error_type: str = ""
    reason: str = ""
    subtitle_format: str = ""
    encoding: str = ""
    content: str = ""
    bilingual_count: int = 0


def detect_subtitle_format(value: str = "") -> str:
    text = str(value or "").lower()
    if re.search(r"(\.ass\b|\bass\b|advanced substation alpha)", text):
        return "ass"
    if re.search(r"(\.srt\b|\bsrt\b|subrip)", text):
        return "srt"
    return ""


def _has_bom(data: bytes, bom: bytes) -> bool:
    return data.startswith(bom)


def _detect_utf16_by_zero_bytes(data: bytes) -> str:
    sample = data[:4096]
    if not sample:
        return ""
    even_zero = sum(1 for index, value in enumerate(sample) if index % 2 == 0 and value == 0)
    odd_zero = sum(1 for index, value in enumerate(sample) if index % 2 == 1 and value == 0)
    pair_count = max(len(sample) // 2, 1)
    even_ratio = even_zero / pair_count
    odd_ratio = odd_zero / pair_count
    if odd_ratio > 0.2 and odd_ratio > even_ratio * 2:
        return "utf-16le"
    if even_ratio > 0.2 and even_ratio > odd_ratio * 2:
        return "utf-16be"
    return ""


def _decode_with(data: bytes, encoding: str) -> str:
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return ""


def _score_decoded_text(content: str) -> float:
    time_count = len(SRT_TIME_RANGE_RE.findall(content))
    dialogue_count = len(re.findall(r"^Dialogue:", content, flags=re.I | re.M))
    ass_section_count = len(re.findall(r"^\[[^\]]+\]$", content, flags=re.M))
    replacement_count = len(REPLACEMENT_RE.findall(content))
    null_count = content.count("\x00")
    chinese_count = len(CHINESE_GLOBAL_RE.findall(content))
    english_count = len(ENGLISH_WORD_RE.findall(content))
    line_count = content.count("\n")
    header_bonus = 120 if re.match(r"^\ufeff?\d+\s*\n\d{1,2}:\d{2}:\d{2}", content) else 0
    return (
        time_count * 120
        + dialogue_count * 80
        + ass_section_count * 30
        + header_bonus
        + chinese_count * 3
        + english_count * 2
        + min(line_count, 200)
        - replacement_count * 120
        - null_count * 20
    )


def decode_subtitle_bytes(data: bytes) -> DecodedSubtitle:
    preferred: list[str] = []
    if _has_bom(data, b"\xef\xbb\xbf"):
        preferred.append("utf-8-sig")
    if _has_bom(data, b"\xff\xfe") or _has_bom(data, b"\xfe\xff"):
        preferred.append("utf-16")
    detected_utf16 = _detect_utf16_by_zero_bytes(data)
    if detected_utf16:
        preferred.append(detected_utf16)

    candidates = []
    for encoding in dict.fromkeys([*preferred, *DECODE_ENCODINGS]):
        content = _decode_with(data, encoding)
        if not content:
            continue
        candidates.append(
            DecodedSubtitle(
                encoding=encoding,
                content=content.replace("\r\n", "\n").replace("\r", "\n"),
                score=_score_decoded_text(content),
                replacement_count=len(REPLACEMENT_RE.findall(content)),
            )
        )

    if candidates:
        return sorted(candidates, key=lambda item: item.score, reverse=True)[0]

    return DecodedSubtitle(encoding="", content="", score=0, replacement_count=0)


def normalize_subtitle_timestamp(value: str = "") -> str:
    match = re.match(r"^\s*(\d{1,2}):(\d{2}):(\d{2})(?:[,.]\d{1,3})?\s*$", value)
    if not match:
        return value.strip()
    hours, minutes, seconds = match.groups()
    return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"


def clean_subtitle_line(value: str = "") -> list[str]:
    text = html.unescape(str(value or ""))
    text = (
        text.replace("\\N", "\n")
        .replace("\\n", "\n")
        .replace("\\h", " ")
        .replace("\ufeff", "")
    )
    text = re.sub(r"\{\\.*?\}", "", text)
    text = re.sub(r"\{.*?\}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = []
    for line in text.split("\n"):
        normalized = re.sub(r"[ \t]+", " ", line).strip()
        if normalized and "\ufffd" not in normalized:
            lines.append(normalized)
    return lines


def _split_mixed_language_line(line: str) -> tuple[str, str] | None:
    if not CHINESE_RE.search(line) or not ENGLISH_RE.search(line):
        return None

    first_english = re.search(r"[A-Za-z]", line)
    if first_english and first_english.start() > 0:
        zh_part = line[: first_english.start()].strip()
        en_part = line[first_english.start() :].strip()
        if CHINESE_RE.search(zh_part) and ENGLISH_RE.search(en_part):
            return zh_part, en_part

    first_chinese = CHINESE_RE.search(line)
    if first_chinese and first_chinese.start() > 0:
        en_part = line[: first_chinese.start()].strip()
        zh_part = line[first_chinese.start() :].strip()
        if CHINESE_RE.search(zh_part) and ENGLISH_RE.search(en_part):
            return zh_part, en_part

    return None


def split_bilingual_lines(lines: list[str]) -> tuple[str, str]:
    zh_lines: list[str] = []
    en_lines: list[str] = []
    other_lines: list[str] = []

    for line in lines:
        mixed = _split_mixed_language_line(line)
        if mixed:
            zh_lines.append(mixed[0])
            en_lines.append(mixed[1])
            continue

        has_zh = bool(CHINESE_RE.search(line))
        has_en = bool(ENGLISH_RE.search(line))
        if has_zh and not has_en:
            zh_lines.append(line)
        elif has_en and not has_zh:
            en_lines.append(line)
        elif has_zh:
            zh_lines.append(line)
        elif has_en:
            en_lines.append(line)
        else:
            other_lines.append(line)

    if other_lines:
        if zh_lines and not en_lines:
            zh_lines.extend(other_lines)
        elif en_lines and not zh_lines:
            en_lines.extend(other_lines)

    return "\n".join(zh_lines), "\n".join(en_lines)


def _make_entry(
    movie_id: str,
    index: int,
    start: str,
    end: str,
    raw_lines: list[str],
) -> SubtitleEntry | None:
    lines = []
    for raw_line in raw_lines:
        lines.extend(clean_subtitle_line(raw_line))
    if not lines:
        return None
    zh_content, en_content = split_bilingual_lines(lines)
    content = "\n".join([item for item in [zh_content, en_content] if item]) or "\n".join(lines)
    return SubtitleEntry(
        subtitles_id=f"{movie_id or 'unknown'}-{index}",
        movie_id=movie_id,
        start_time=normalize_subtitle_timestamp(start),
        end_time=normalize_subtitle_timestamp(end),
        zh_content=zh_content,
        en_content=en_content,
        content=content,
    )


def parse_srt(content: str, movie_id: str = "") -> list[SubtitleEntry]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    entries: list[SubtitleEntry] = []
    for match in SRT_BLOCK_RE.finditer(normalized):
        entry = _make_entry(
            movie_id=movie_id,
            index=len(entries) + 1,
            start=match.group("start"),
            end=match.group("end"),
            raw_lines=match.group("body").splitlines(),
        )
        if entry:
            entries.append(entry)
    return entries


def _split_ass_dialogue_fields(value: str, field_count: int) -> list[str]:
    if field_count <= 1:
        return [value]
    parts = value.split(",", field_count - 1)
    if len(parts) < field_count:
        parts.extend([""] * (field_count - len(parts)))
    return parts


def parse_ass(content: str, movie_id: str = "") -> list[SubtitleEntry]:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    in_events = False
    format_fields: list[str] = []
    entries: list[SubtitleEntry] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower() == "[events]":
            in_events = True
            continue
        if ASS_SECTION_RE.match(stripped) and stripped.lower() != "[events]":
            in_events = False
            continue
        if not in_events:
            continue
        if stripped.lower().startswith("format:"):
            format_fields = [
                item.strip().lower() for item in stripped.split(":", 1)[1].split(",")
            ]
            continue
        if not stripped.lower().startswith("dialogue:") or not format_fields:
            continue

        values = _split_ass_dialogue_fields(stripped.split(":", 1)[1].strip(), len(format_fields))
        row = dict(zip(format_fields, [value.strip() for value in values], strict=False))
        entry = _make_entry(
            movie_id=movie_id,
            index=len(entries) + 1,
            start=row.get("start", ""),
            end=row.get("end", ""),
            raw_lines=[row.get("text", "")],
        )
        if entry:
            entries.append(entry)

    return entries


def parse_subtitle_text(content: str, subtitle_format: str = "srt", movie_id: str = "") -> list[SubtitleEntry]:
    normalized_format = detect_subtitle_format(subtitle_format) or subtitle_format.lower()
    if normalized_format == "ass":
        return parse_ass(content, movie_id)
    if normalized_format == "srt":
        return parse_srt(content, movie_id)
    return []


def candidate_text(candidate: SubtitleCandidate) -> str:
    return re.sub(r"[_./\\()[\]{}-]+", " ", candidate.metadata_text()).strip()


def validate_candidate_metadata(candidate: SubtitleCandidate) -> CandidateValidation:
    text = candidate_text(candidate)
    subtitle_format = detect_subtitle_format(candidate.subtitle_format) or detect_subtitle_format(text)
    if subtitle_format not in SUPPORTED_FORMATS:
        return CandidateValidation(
            valid=False,
            error_type=ErrorType.INVALID_FORMAT,
            reason="候选字幕不是 ass/srt 格式",
            subtitle_format=subtitle_format,
        )

    has_simplified = bool(SIMPLIFIED_MARKER_RE.search(text))
    has_english = bool(ENGLISH_MARKER_RE.search(text))
    has_bilingual = bool(BILINGUAL_MARKER_RE.search(text))
    traditional_only = bool(TRADITIONAL_ONLY_MARKER_RE.search(text)) and not has_simplified

    if traditional_only or not (has_simplified or has_bilingual) or not (has_english or has_bilingual):
        return CandidateValidation(
            valid=False,
            error_type=ErrorType.INVALID_LANGUAGE,
            reason="候选字幕未标记为简体中文和英文双语",
            subtitle_format=subtitle_format,
        )

    return CandidateValidation(valid=True, subtitle_format=subtitle_format)


def validate_downloaded_subtitle_bytes(
    data: bytes,
    subtitle_format: str = "",
    file_name: str = "",
) -> DownloadValidation:
    normalized_format = (
        detect_subtitle_format(subtitle_format)
        or detect_subtitle_format(file_name)
        or detect_subtitle_format(data[:1000].decode("utf-8", errors="ignore"))
    )
    if normalized_format not in SUPPORTED_FORMATS:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.INVALID_FORMAT,
            reason="下载到的字幕不是 ass/srt 格式",
            subtitle_format=normalized_format,
        )

    decoded = decode_subtitle_bytes(data)
    if not decoded.content or decoded.replacement_count > 5 or decoded.score < -100:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.DECODE_FAILED,
            reason="下载到的字幕无法可靠解码",
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
        )

    entries = parse_subtitle_text(decoded.content, normalized_format, "validation")
    bilingual_count = sum(1 for item in entries if item.zh_content.strip() and item.en_content.strip())
    if bilingual_count <= 0:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.CONTENT_VALIDATION_FAILED,
            reason="下载到的字幕没有同时包含中文和英文对白",
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            bilingual_count=0,
        )

    return DownloadValidation(
        valid=True,
        subtitle_format=normalized_format,
        encoding=decoded.encoding,
        content=decoded.content.lstrip("\ufeff"),
        bilingual_count=bilingual_count,
    )
