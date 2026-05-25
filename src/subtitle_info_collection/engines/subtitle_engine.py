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

TRADITIONAL_TO_SIMPLIFIED_MAP = {
    '\u5011': '\u4eec',
    '\u500b': '\u4e2a',
    '\u5e79': '\u5e72',
    '\u4ec0\u9ebc': '\u4ec0\u4e48',
    '\u8aaa': '\u8bf4',
    '\u8a71': '\u8bdd',
    '\u8a9e': '\u8bed',
    '\u8b80': '\u8bfb',
    '\u66f8': '\u4e66',
    '\u5beb': '\u5199',
    '\u5b78': '\u5b66',
    '\u7fd2': '\u4e60',
    '\u96fb': '\u7535',
    '\u8166': '\u8111',
    '\u7db2': '\u7f51',
    '\u8def': '\u8def',
    '\u8cfc': '\u8d2d',
    '\u7269': '\u7269',
    '\u8edf': '\u8f6f',
    '\u9ad4': '\u4f53',
    '\u786c': '\u786c',
    '\u8cc7': '\u8d44',
    '\u6599': '\u6599',
    '\u5eab': '\u5e93',
    '\u554f': '\u95ee',
    '\u984c': '\u9898',
    '\u96e3': '\u96be',
    '\u9ede': '\u70b9',
    '\u958b': '\u5f00',
    '\u95dc': '\u5173',
    '\u5fc3': '\u5fc3',
    '\u60c5': '\u60c5',
    '\u611f': '\u611f',
    '\u89ba': '\u89c9',
    '\u5f97': '\u5f97',
    '\u767c': '\u53d1',
    '\u73fe': '\u73b0',
    '\u807d': '\u542c',
    '\u8b1b': '\u8bb2',
    '\u8ad6': '\u8bba',
    '\u8b70': '\u8bae',
    '\u8ac7': '\u8c08',
    '\u8a2a': '\u8bbf',
    '\u986f': '\u663e',
    '\u793a': '\u793a',
    '\u8077': '\u804c',
    '\u696d': '\u4e1a',
    '\u5c08': '\u4e13',
    '\u512a': '\u4f18',
    '\u52a3': '\u52a3',
    '\u8003': '\u8003',
    '\u8a66': '\u8bd5',
    '\u9a57': '\u9a8c',
    '\u8b49': '\u8bc1',
    '\u660e': '\u660e',
    '\u9867': '\u987e',
    '\u8a0a': '\u8baf',
    '\u5831': '\u62a5',
    '\u544a': '\u544a',
    '\u7d50': '\u7ed3',
    '\u679c': '\u679c',
    '\u5283': '\u5212',
    '\u7b97': '\u7b97',
    '\u8a08': '\u8ba1',
    '\u756b': '\u753b',
    '\u898f': '\u89c4',
    '\u76e3': '\u76d1',
    '\u7763': '\u7763',
    '\u6aa2': '\u68c0',
    '\u67e5': '\u67e5',
    '\u5be9': '\u5ba1',
    '\u6838': '\u6838',
    '\u6279': '\u6279',
    '\u6e96': '\u51c6',
    '\u8a31': '\u8bb8',
    '\u53ef': '\u53ef',
    '\u842c': '\u4e07',
    '\u865f': '\u53f7',
    '\u6a19': '\u6807',
    '\u7bc4': '\u8303',
    '\u8cea': '\u8d28',
    '\u91cf': '\u91cf',
    '\u63a7': '\u63a7',
    '\u5236': '\u5236',
    '\u98a8': '\u98ce',
    '\u96aa': '\u9669',
    '\u7ba1': '\u7ba1',
    '\u7406': '\u7406',
    '\u5c55': '\u5c55',
    '\u5275': '\u521b',
    '\u65b0': '\u65b0',
    '\u7af6': '\u7ade',
    '\u722d': '\u4e89',
    '\u52e2': '\u52bf',
    '\u7522': '\u4ea7',
    '\u54c1': '\u54c1',
    '\u670d': '\u670d',
    '\u52d9': '\u52a1',
    '\u5ba2': '\u5ba2',
    '\u6236': '\u6237',
    '\u9700': '\u9700',
    '\u6c42': '\u6c42',
    '\u6eff': '\u6ee1',
    '\u610f': '\u610f',
    '\u5ea6': '\u5ea6',
    '\u8abf': '\u8c03',
    '\u7d71': '\u7edf',
    '\u5206': '\u5206',
    '\u6790': '\u6790',
    '\u8868': '\u8868',
    '\u904b': '\u8fd0',
    '\u8f38': '\u8f93',
    '\u6d41': '\u6d41',
    '\u5009': '\u4ed3',
    '\u5132': '\u50a8',
    '\u4fdd': '\u4fdd',
    '\u8655': '\u5904',
    '\u89e3': '\u89e3',
    '\u6c7a': '\u51b3',
    '\u6267': '\u6267',
    '\u884c': '\u884c',
    '\u5be6': '\u5b9e',
    '\u65bd': '\u65bd',
    '\u63a8': '\u63a8',
    '\u5ee3': '\u5e7f',
    '\u61c9': '\u5e94',
    '\u7528': '\u7528',
    '\u74b0': '\u73af',
    '\u5883': '\u5883',
    '\u7d93': '\u7ecf',
    '\u50b3': '\u4f20',
    '\u4ee3': '\u4ee3',
    '\u6280': '\u6280',
    '\u8853': '\u672f',
    '\u5de5': '\u5de5',
    '\u7a0b': '\u7a0b',
    '\u79d1': '\u79d1',
    '\u7814': '\u7814',
    '\u7a76': '\u7a76',
    '\u8a2d': '\u8bbe',
    '\u88fd': '\u5236',
    '\u9020': '\u9020',
    '\u52a0': '\u52a0',
    '\u751f': '\u751f',
    '\u5305': '\u5305',
    '\u88dd': '\u88c5',
    '\u6e2c': '\u6d4b',
    '\u68c0': '\u68c0',
    '\u9a4c': '\u9a8c',
    '\u6536': '\u6536',
    '\u8ca8': '\u8d27',
    '\u8cb7': '\u4e70',
    '\u8ce3': '\u5356',
    '\u4ea4': '\u4ea4',
    '\u6613': '\u6613',
    '\u5408': '\u5408',
    '\u540c': '\u540c',
    '\u5354': '\u534f',
    '\u689d': '\u6761',
    '\u6b3e': '\u6b3e',
    '\u5b9a': '\u5b9a',
    '\u4f8b': '\u4f8b',
    '\u6cd5': '\u6cd5',
    '\u653f': '\u653f',
    '\u7b56': '\u7b56',
    '\u63aa': '\u63aa',
    '\u52d5': '\u52a8',
    '\u806f': '\u8054',
    '\u7e6b': '\u7cfb',
    '\u6e9d': '\u6c9f',
    '\u901a': '\u901a',
    '\u914d': '\u914d',
    '\u652f': '\u652f',
    '\u63f4': '\u63f4',
    '\u52a9': '\u52a9',
    '\u5e6b': '\u5e2e',
    '\u5fd9': '\u5fd9',
    '\u63d0': '\u63d0',
    '\u4f9b': '\u4f9b',
    '\u7d66': '\u7ed9',
    '\u4e88': '\u4e88',
    '\u5165': '\u5165',
    '\u51fa': '\u51fa',
    '\u5b58': '\u5b58',
    '\u53d6': '\u53d6',
    '\u5099': '\u5907',
    '\u4efd': '\u4efd',
    '\u9084': '\u8fd8',
    '\u539f': '\u539f',
    '\u6062': '\u6062',
    '\u5fa9': '\u590d',
    '\u91cd': '\u91cd',
    '\u7f6e': '\u7f6e',
    '\u6e05': '\u6e05',
    '\u9664': '\u9664',
    '\u522a': '\u5220',
    '\u64b0': '\u64b0',
    '\u8d77': '\u8d77',
    '\u8349': '\u8349',
    '\u4fee': '\u4fee',
    '\u6539': '\u6539',
    '\u88dc': '\u8865',
    '\u5145': '\u5145',
    '\u589e': '\u589e',
    '\u6e1b': '\u51cf',
    '\u5c11': '\u5c11',
    '\u6b63': '\u6b63',
    '\u6821': '\u6821',
    '\u8a8d': '\u8ba4',
    '\u78ba': '\u786e',
    '\u5f9e': '\u4ece',
    '\u7576': '\u5f53',
    '\u7136': '\u7136',
    '\u5f8c': '\u540e',
    '\u88cf': '\u91cc',
    '\u88e1': '\u91cc',
    '\u885d': '\u51b2',
    '\u885e': '\u51b2',
    '\u885f': '\u51b2',
    '\u8860': '\u51b2',
    '\u8861': '\u8861',
    '\u8862': '\u8862',
    '\u8863': '\u8863',
    '\u8864': '\u8864',
    '\u8865': '\u8865',
    '\u8866': '\u8866',
    '\u8867': '\u8867',
    '\u8869': '\u8869',
    '\u886a': '\u886a',
    '\u886b': '\u886b',
    '\u886c': '\u886c',
    '\u886d': '\u886d',
    '\u886e': '\u886e',
    '\u886f': '\u886f',
    '\u5169': '\u4e24',
    '\u96d9': '\u53cc',
    '\u723e': '\u5c14',
    '\u9ebc': '\u4e48',
    '\u5152': '\u513f',
    '\u96f2': '\u4e91',
    '\u5e7e': '\u51e0',
    '\u53c3': '\u53c2',
    '\u9b25': '\u6597',
    '\u8591': '\u535c',
    '\u85c9': '\u85c9',
}

TRADITIONAL_ONLY_CHARS = frozenset(TRADITIONAL_TO_SIMPLIFIED_MAP.keys())

SUPPORTED_FORMATS = {"ass", "srt"}
# 最小有效文件大小（仅作极端兜底，优先使用结构校验）
MIN_VALID_SUBTITLE_BYTES = 10 * 1024
# 最小有效字幕条目数：低于此值视为无效电影字幕
MIN_VALID_SUBTITLE_ENTRIES = 5
DEFAULT_MIN_BILINGUAL_RATIO = 0.70
TEXT_DECODE_ENCODINGS = ["utf-8-sig", "utf-8", "gb18030", "gbk"]
UTF16_DECODE_ENCODINGS = ["utf-16", "utf-16le", "utf-16be"]

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


def filter_to_simplified_chinese(text: str) -> str:
    """Filter text to only contain simplified Chinese, English, and common punctuation.
    
    Removes:
    - Traditional Chinese characters (converted to simplified if possible, otherwise removed)
    - Japanese Hiragana/Katakana
    - Korean Hangul
    - Other non-Chinese/English scripts
    
    Keeps:
    - Simplified Chinese characters
    - English letters (A-Z, a-z)
    - Numbers and common punctuation
    """
    result = []
    for char in text:
        ascii_char = ord(char)
        if ascii_char < 128:
            result.append(char)
        elif char in TRADITIONAL_TO_SIMPLIFIED_MAP:
            result.append(TRADITIONAL_TO_SIMPLIFIED_MAP[char])
        elif '\u4e00' <= char <= '\u9fff' and char not in TRADITIONAL_ONLY_CHARS:
            result.append(char)
        elif char in '，。！？、；：""''（）【】《》…—·\n\r\t ':
            result.append(char)
    return ''.join(result)


def validate_is_simplified_chinese_english(text: str) -> tuple[bool, str]:
    """Validate that text contains only simplified Chinese and English content.
    
    Checks ORIGINAL text first for traditional characters, then validates
    the filtered content for simplified Chinese + English requirements.
    
    Returns:
        (is_valid, message): tuple of validation result and descriptive message
    """
    if not text.strip():
        return False, "内容为空"
    
    chinese_chars_in_original = re.findall(r'[\u4e00-\u9fff]', text)
    if not chinese_chars_in_original:
        return False, "未检测到中文字符"
    
    trad_count = sum(1 for char in chinese_chars_in_original if char in TRADITIONAL_ONLY_CHARS)
    if len(chinese_chars_in_original) >= 5:
        trad_ratio = trad_count / len(chinese_chars_in_original)
        if trad_ratio >= 0.2:
            return False, f"字幕为繁体中文（繁体占比 {trad_ratio:.0%}），非简体中英双语字幕"
    
    english_words = re.findall(r'[A-Za-z]{2,}', text)
    if len(english_words) < 2:
        return False, "未检测到足够的英文内容"
    
    return True, "简体中英双语字幕"


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
    entry_count: int = 0
    bilingual_count: int = 0
    chinese_only_count: int = 0
    english_only_count: int = 0
    bilingual_ratio: float = 0.0
    min_bilingual_ratio: float = DEFAULT_MIN_BILINGUAL_RATIO


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

    has_utf16_hint = detected_utf16 or any(encoding.startswith("utf-16") for encoding in preferred)
    encoding_candidates = [
        *preferred,
        *TEXT_DECODE_ENCODINGS,
        *(UTF16_DECODE_ENCODINGS if has_utf16_hint else []),
    ]
    candidates = []
    for encoding in dict.fromkeys(encoding_candidates):
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
        cleaned = clean_subtitle_line(raw_line)
        filtered = [filter_to_simplified_chinese(line) for line in cleaned]
        filtered = [line for line in filtered if line.strip()]
        lines.extend(filtered)
    if not lines:
        return None
    zh_content, en_content = split_bilingual_lines(lines)
    content = "\n".join([item for item in [zh_content, en_content] if item])
    if not content.strip():
        return None
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


def normalize_bilingual_ratio(value: float = DEFAULT_MIN_BILINGUAL_RATIO) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return DEFAULT_MIN_BILINGUAL_RATIO
    return max(0.0, min(1.0, ratio))


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def candidate_text(candidate: SubtitleCandidate) -> str:
    return re.sub(r"[_./\\()[\]{}-]+", " ", candidate.metadata_text()).strip()


ANY_CHINESE_MARKER_RE = re.compile(
    r"(简体|简中|简英|简繁英|中文|中英|双语|繁体|繁中|chs|cht|zh[-_ ]?cn|zh[-_ ]?tw|"
    r"chinese|traditional|simplified|big5|gb2312|gbk|gb18030|\bze\b)",
    re.I,
)

LANGUAGE_TYPE_BILINGUAL_RE = re.compile(
    r"(双语|中英|简英|简繁英|chs.*eng|zh.*en|中.*英|英.*中)",
    re.I,
)

LANGUAGE_TYPE_CHINESE_RE = re.compile(
    r"(简体|简中|中文|繁体|繁中|chs|cht|zh|chinese|中文)",
    re.I,
)

LANGUAGE_TYPE_ENGLISH_RE = re.compile(
    r"(英文|英语|英字|eng|english|\ben\b)",
    re.I,
)


LANGUAGE_TYPE_TRADITIONAL_RE = re.compile(
    r"(繁体|繁中|cht|zh[-_ ]?tw|traditional|big5)",
    re.I,
)

LANGUAGE_TYPE_SIMPLIFIED_RE = re.compile(
    r"(简体|简中|chs|zh[-_ ]?cn|simplified|gb2312|gbk|gb18030)",
    re.I,
)


def _check_language_type_bilingual(language_type: str) -> bool:
    if not language_type:
        return False
    return bool(LANGUAGE_TYPE_BILINGUAL_RE.search(language_type))


def _check_language_type_has_chinese_and_english(language_type: str) -> bool:
    if not language_type:
        return False
    has_chinese = bool(LANGUAGE_TYPE_CHINESE_RE.search(language_type))
    has_english = bool(LANGUAGE_TYPE_ENGLISH_RE.search(language_type))
    if not (has_chinese and has_english):
        return False
    has_traditional = bool(LANGUAGE_TYPE_TRADITIONAL_RE.search(language_type))
    has_simplified = bool(LANGUAGE_TYPE_SIMPLIFIED_RE.search(language_type))
    if has_traditional and not has_simplified:
        return False
    return True


def validate_candidate_metadata(candidate: SubtitleCandidate, lenient: bool = False) -> CandidateValidation:
    text = candidate_text(candidate)
    subtitle_format = detect_subtitle_format(candidate.subtitle_format) or detect_subtitle_format(text)
    if subtitle_format not in SUPPORTED_FORMATS:
        return CandidateValidation(
            valid=False,
            error_type=ErrorType.INVALID_FORMAT,
            reason="候选字幕不是 ass/srt 格式",
            subtitle_format=subtitle_format,
        )

    if _check_language_type_bilingual(candidate.language_type):
        return CandidateValidation(valid=True, subtitle_format=subtitle_format)

    if _check_language_type_has_chinese_and_english(candidate.language_type):
        return CandidateValidation(valid=True, subtitle_format=subtitle_format)

    has_simplified = bool(SIMPLIFIED_MARKER_RE.search(text))
    has_english = bool(ENGLISH_MARKER_RE.search(text))
    has_bilingual = bool(BILINGUAL_MARKER_RE.search(text))
    has_any_chinese = bool(ANY_CHINESE_MARKER_RE.search(text))
    traditional_only = bool(TRADITIONAL_ONLY_MARKER_RE.search(text)) and not has_simplified

    if has_simplified and (has_english or has_bilingual):
        return CandidateValidation(valid=True, subtitle_format=subtitle_format)

    if has_bilingual:
        return CandidateValidation(valid=True, subtitle_format=subtitle_format)

    if lenient:
        if traditional_only:
            return CandidateValidation(
                valid=False,
                error_type=ErrorType.INVALID_LANGUAGE,
                reason="候选字幕为繁体中文，非简体中英双语字幕（宽松模式仍排除）",
                subtitle_format=subtitle_format,
            )
        if has_any_chinese or candidate.language_type:
            return CandidateValidation(valid=True, subtitle_format=subtitle_format)
        return CandidateValidation(
            valid=False,
            error_type=ErrorType.INVALID_LANGUAGE,
            reason="候选字幕未包含任何中文标记",
            subtitle_format=subtitle_format,
        )

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
    lenient: bool = False,
    min_bilingual_ratio: float = DEFAULT_MIN_BILINGUAL_RATIO,
) -> DownloadValidation:
    required_ratio = normalize_bilingual_ratio(min_bilingual_ratio)
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
            min_bilingual_ratio=required_ratio,
        )

    # 结构校验优先：先解析字幕条目，用条目数判断有效性
    decoded = decode_subtitle_bytes(data)
    max_replacements = 20 if lenient else 5
    min_score = -500 if lenient else -100
    if not decoded.content or decoded.replacement_count > max_replacements or decoded.score < min_score:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.DECODE_FAILED,
            reason="下载到的字幕无法可靠解码",
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            min_bilingual_ratio=required_ratio,
        )

    entries = parse_subtitle_text(decoded.content, normalized_format, "validation")
    bilingual_count = 0
    chinese_only_count = 0
    english_only_count = 0
    for item in entries:
        has_chinese = bool(item.zh_content.strip())
        has_english = bool(item.en_content.strip())
        if has_chinese and has_english:
            bilingual_count += 1
        elif has_chinese:
            chinese_only_count += 1
        elif has_english:
            english_only_count += 1

    entry_count = bilingual_count + chinese_only_count + english_only_count
    bilingual_ratio = bilingual_count / entry_count if entry_count else 0.0

    # 结构校验：条目数不足视为无效
    if entry_count < MIN_VALID_SUBTITLE_ENTRIES:
        # 额外检查文件大小作为兜底（仅当文件极其小时才用大小判定）
        if len(data) < MIN_VALID_SUBTITLE_BYTES:
            return DownloadValidation(
                valid=False,
                error_type=ErrorType.CONTENT_VALIDATION_FAILED,
                reason=(
                    f"字幕条目过少({entry_count}条)"
                ),
                subtitle_format=normalized_format,
                encoding=decoded.encoding,
                content=decoded.content,
                entry_count=entry_count,
                bilingual_count=bilingual_count,
                chinese_only_count=chinese_only_count,
                english_only_count=english_only_count,
                bilingual_ratio=bilingual_ratio,
                min_bilingual_ratio=required_ratio,
            )
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.CONTENT_VALIDATION_FAILED,
            reason=(
                f"字幕条目过少({entry_count}条)"
            ),
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            entry_count=entry_count,
            bilingual_count=bilingual_count,
            chinese_only_count=chinese_only_count,
            english_only_count=english_only_count,
            bilingual_ratio=bilingual_ratio,
            min_bilingual_ratio=required_ratio,
        )

    if entry_count > 0 and bilingual_ratio >= required_ratio:
        return DownloadValidation(
            valid=True,
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content.lstrip("\ufeff"),
            entry_count=entry_count,
            bilingual_count=bilingual_count,
            chinese_only_count=chinese_only_count,
            english_only_count=english_only_count,
            bilingual_ratio=bilingual_ratio,
            min_bilingual_ratio=required_ratio,
        )

    if entry_count <= 0:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.CONTENT_VALIDATION_FAILED,
            reason="下载到的字幕没有包含有效的中文或英文对白",
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            entry_count=entry_count,
            bilingual_count=0,
            bilingual_ratio=0.0,
            min_bilingual_ratio=required_ratio,
        )

    # 英文-only 检测：中文条目占比过低 -> 拒绝保存
    if bilingual_count == 0 and chinese_only_count == 0 and english_only_count > 0:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.CONTENT_VALIDATION_FAILED,
            reason=(
                "纯英文字幕，无双语内容"
            ),
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            entry_count=entry_count,
            bilingual_count=bilingual_count,
            chinese_only_count=chinese_only_count,
            english_only_count=english_only_count,
            bilingual_ratio=bilingual_ratio,
            min_bilingual_ratio=required_ratio,
        )

    return DownloadValidation(
        valid=False,
        error_type=ErrorType.CONTENT_VALIDATION_FAILED,
        reason=(
            f"双语占比不足({_format_percent(bilingual_ratio)})"
        ),
        subtitle_format=normalized_format,
        encoding=decoded.encoding,
        content=decoded.content,
        entry_count=entry_count,
        bilingual_count=bilingual_count,
        chinese_only_count=chinese_only_count,
        english_only_count=english_only_count,
        bilingual_ratio=bilingual_ratio,
        min_bilingual_ratio=required_ratio,
    )
