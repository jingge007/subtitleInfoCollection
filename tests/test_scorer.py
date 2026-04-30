from subtitle_info_collection.engines.scorer import score_candidate, sort_candidates
from subtitle_info_collection.models import MovieInfo, SubtitleCandidate


def candidate(identifier: str, title: str, downloads: int, subtitle_format: str = "ass"):
    return SubtitleCandidate(
        provider="subhd",
        provider_subtitle_id=identifier,
        movie_id="tmdb-1",
        movie_title="Example Movie",
        movie_original_title="Example Movie",
        movie_title_zh="示例电影",
        movie_year=2026,
        subtitle_title=title,
        language_type="简体/英语/双语",
        subtitle_format=subtitle_format,
        download_count=downloads,
        description=title,
        file_names=[title],
    )


def test_score_prefers_title_match_and_downloads():
    movie = MovieInfo(
        movie_id="tmdb-1",
        title="Example Movie",
        original_title="Example Movie",
        title_zh="示例电影",
        year=2026,
        rating=8.5,
        vote_count=1000,
    )
    weak = score_candidate(candidate("1", "Other.Movie.简英双语.srt", 10, "srt"), movie)
    strong = score_candidate(candidate("2", "示例电影.Example.Movie.2026.简英双语.1080p.ass", 100), movie)
    sorted_items = sort_candidates([weak, strong])
    assert sorted_items[0].provider_subtitle_id == "2"
    assert sorted_items[0].total_score > sorted_items[1].total_score

