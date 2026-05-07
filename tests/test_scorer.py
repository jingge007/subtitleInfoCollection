from subtitle_info_collection.engines.scorer import (
    has_movie_identity_match,
    score_candidate,
    sort_candidates,
)
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


def test_identity_match_rejects_same_year_wrong_opensubtitles_title():
    movie = MovieInfo(
        movie_id="tmdb-1",
        title="The Deep End of the Ocean",
        original_title="The Deep End of the Ocean",
        title_zh="海洋深处",
        year=1999,
        rating=7.0,
    )
    wrong = score_candidate(
        candidate(
            "wrong",
            "The.Virgin.Suicides.1999.720p.Bluray.x264.DTS-HDChina[chs&eng]",
            10_000,
        ),
        movie,
    )
    assert wrong.scores["titleMatchScore"] == 0
    assert not has_movie_identity_match(wrong, movie)


def test_identity_match_accepts_distinctive_title_without_article():
    movie = MovieInfo(
        movie_id="tmdb-1",
        title="The Matrix",
        original_title="The Matrix",
        title_zh="黑客帝国",
        year=1999,
    )
    item = score_candidate(candidate("matrix", "Matrix.1999.REMASTERED.1080p.BluRay.chs_eng.ass", 50), movie)
    assert has_movie_identity_match(item, movie)
