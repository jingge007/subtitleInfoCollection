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


def _candidate_identity_text(candidate: SubtitleCandidate) -> str:
    attrs = candidate.raw.get("attributes") if isinstance(candidate.raw, dict) else {}
    attrs = attrs if isinstance(attrs, dict) else {}
    feature_details = attrs.get("feature_details") if isinstance(attrs.get("feature_details"), dict) else {}
    parts = [
        candidate.subtitle_title,
        candidate.description,
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


def has_movie_identity_match(candidate: SubtitleCandidate, movie: MovieInfo) -> bool:
    if movie.tmdb_id and _candidate_tmdb_id(candidate) == movie.tmdb_id:
        return True

    target_tokens = _tokens(_candidate_identity_text(candidate))
    if any(
        title and _contains_token_sequence(target_tokens, title)
        for title in [movie.title_zh, movie.title, movie.original_title]
    ):
        return True

    significant_words = _significant_title_tokens(movie.title) | _significant_title_tokens(movie.original_title)
    if not significant_words:
        return False
    matched_words = significant_words & set(target_tokens)
    required_matches = 1 if len(significant_words) == 1 else 2
    return len(matched_words) >= required_matches


def score_candidate(candidate: SubtitleCandidate, movie: MovieInfo) -> SubtitleCandidate:
    language_score = 1000.0
    rating_score = float(movie.rating or 0) * 100
    year_score = 100.0 if str(movie.year or "") in candidate.metadata_text() else 0.0
    download_score = math.log(float(candidate.download_count or 0) + 1) * 15
    provider_rating_score = float(candidate.rating or 0) * 10
    title_match_score = get_title_match_score(candidate, movie)
    resolution_score = get_resolution_score(candidate.metadata_text())
    format_score = get_format_score(candidate.subtitle_format)
    total = (
        language_score
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
