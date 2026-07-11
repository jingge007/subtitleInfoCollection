from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------- jieba optional dependency ----------
_jieba_available = False
try:
    import jieba
    _jieba_available = True
except ImportError:
    logger.warning('jieba not installed, falling back to simple character splitting')


# ---------- stop words ----------
STOP_WORDS: set[str] = {
    '的', '了', '是', '在', '我', '你', '他', '它', '她', '们',
    '这', '那', '有', '不', '就', '都', '而', '及', '与', '或',
    '一个', '没有', '我们', '他们', '她们', '什么', '怎么',
    '为', '对', '上', '下', '中', '大', '小', '多', '少',
    '很', '太', '非', '吧', '吗', '啊', '哦', '嗯', '呢', '呀',
    '嘛', '哎', '哟', '哈', '哇', '呵', '么', '会', '可', '能', '够',
    # English
    'a', 'an', 'the', 'is', 'it', 'i', 'you', 'he', 'she', 'we', 'they',
    'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
    'and', 'or', 'not', 'are', 'was', 'this', 'that', 'these', 'those',
    'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
    'will', 'would', 'could', 'should', 'but', 'so', 'if', 'as',
}

_PUNCTUATION_RE = re.compile(
    r'[　!-/:-@[-`{-~'
    r'、-〿＀-￯]'
)
_CJK_RE = re.compile(r'[一-鿿]+')
_EN_RE = re.compile(r'[a-z]+')


def _normalize(text: str) -> str:
    """Normalize: lowercase, replace punctuation with space"""
    return _PUNCTUATION_RE.sub(' ', text).strip().lower()


def _jieba_cut(text: str) -> list[str]:
    """jieba precise cut, fallback to char-level on failure"""
    if _jieba_available and text.strip():
        return list(jieba.cut(text, cut_all=False))
    return list(text)


def _split_en(text: str) -> list[str]:
    """English tokens: split by non-alpha, filter short/stop words"""
    words = _EN_RE.findall(text.lower())
    return [w for w in words if len(w) >= 2 and w not in STOP_WORDS]


def _filter_tokens(tokens: list[str]) -> list[str]:
    """Deduplicate, remove stop words, remove empty"""
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        t = t.strip()
        if not t or t in STOP_WORDS or t in seen:
            continue
        if t.isdigit() and len(t) <= 4:
            if not (1000 <= int(t) <= 2099):
                continue
        seen.add(t)
        result.append(t)
    return result


def tokenize_movie_name(
    title_zh: str,
    title: str,
    original_title: str,
    year: int = 0,
) -> list[str]:
    """Generate movie name search tokens.

    Chinese: jieba segmentation. English: split by space/non-alpha.
    Includes year number. Returns empty list on empty input.
    """
    all_tokens: list[str] = []

    if title_zh:
        zh_tokens = _jieba_cut(title_zh)
        for t in zh_tokens:
            t = t.strip()
            if t and t not in STOP_WORDS:
                all_tokens.append(t)

    en_text = f'{title} {original_title}'.strip()
    if en_text:
        all_tokens.extend(_split_en(en_text))

    for src in [title_zh, title, original_title]:
        src = src.strip()
        if src and src.lower() not in STOP_WORDS:
            all_tokens.append(src)

    if year and 1000 <= year <= 2099:
        all_tokens.append(str(year))

    return _filter_tokens(all_tokens)


def tokenize_subtitle_content(
    zh_content: str,
    en_content: str,
    max_tokens: int = 50,
) -> list[str]:
    """Generate subtitle content search tokens.

    Chinese: jieba segmentation. English: split by non-alpha.
    Deduplicate, filter stop words, trim to max_tokens.
    Falls back to char-level split + 2-gram when jieba missing.
    """
    all_tokens: list[str] = []

    if zh_content:
        zh_clean = _normalize(zh_content)
        zh_tokens = _jieba_cut(zh_clean)
        all_tokens.extend(zh_tokens)

    if en_content:
        en_clean = _normalize(en_content)
        all_tokens.extend(_split_en(en_clean))

    if not _jieba_available and zh_content:
        zh_clean = _normalize(zh_content)
        for m in _CJK_RE.finditer(zh_clean):
            chunk = m.group()
            for ch in chunk:
                if ch not in STOP_WORDS:
                    all_tokens.append(ch)
            if len(chunk) >= 2:
                for i in range(len(chunk) - 1):
                    gram = chunk[i:i+2]
                    if gram not in STOP_WORDS:
                        all_tokens.append(gram)

    return _filter_tokens(all_tokens)[:max_tokens]


def merge_deduplicate(*token_lists: list[str]) -> list[str]:
    """Merge multiple token lists, deduplicate, sort by length desc."""
    seen: set[str] = set()
    result: list[str] = []
    for lst in token_lists:
        for t in lst:
            if t not in seen:
                seen.add(t)
                result.append(t)
    result.sort(key=lambda x: -len(x))
    return result
