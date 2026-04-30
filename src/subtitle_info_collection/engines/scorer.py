from __future__ import annotations

import math
import re

from ..models import MovieInfo, SubtitleCandidate


def normalize_text(value: str = "") -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", value.lower())).strip()


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
    target = normalize_text(
        " ".join([candidate.subtitle_title, candidate.description, *candidate.file_names])
    )
    title = normalize_text(movie.title)
    original_title = normalize_text(movie.original_title)
    title_zh = normalize_text(movie.title_zh)
    year = str(movie.year or "")
    score = 0.0

    if title_zh and title_zh in target:
        score += 80
    if title and title in target:
        score += 60
    if original_title and original_title in target:
        score += 55
    if year and year in target:
        score += 40

    words = set(title.split()) | set(original_title.split())
    for word in words:
        if len(word) >= 3 and word in target:
            score += 5

    return score


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

