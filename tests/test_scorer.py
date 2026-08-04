from subtitle_info_collection.engines.scorer import (
    build_movie_search_keywords,
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
    assert strong.scores["yearScore"] == 100
    assert weak.scores["yearScore"] == 0


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


def test_identity_rejects_sequel_incredibles_2():
    movie = MovieInfo(
        movie_id="tmdb-1",
        title="The Incredibles",
        original_title="The Incredibles",
        title_zh="超人总动员",
        year=2004,
    )
    sequel = candidate(
        "inc2",
        "超人总动员2 YYeTs字幕组 Incredibles.2.2018.1080p.BluRay.x264-SECTOR7",
        100,
    )
    assert not has_movie_identity_match(sequel, movie)


def test_identity_rejects_kung_fu_panda_for_kung_fu():
    movie = MovieInfo(
        movie_id="tmdb-1",
        title="Kung Fu Hustle",
        original_title="Gong fu",
        title_zh="功夫",
        year=2004,
    )
    panda = candidate(
        "panda",
        "功夫熊猫2 Kung Fu Panda 2 2011 UHD BluRay 2160p",
        100,
    )
    assert not has_movie_identity_match(panda, movie)


def test_identity_rejects_episode_marker():
    movie = MovieInfo(
        movie_id="tmdb-1",
        title="Nobody Knows",
        original_title="Dare mo shiranai",
        title_zh="无人知晓",
        year=2004,
    )
    episode = candidate(
        "ep",
        "医院五日.Five.Days.at.Memorial.S01E07.Nobody.Knows.The.Troubles.Ive.Seen.1080p",
        50,
    )
    assert not has_movie_identity_match(episode, movie)


def test_identity_rejects_wrong_year():
    movie = MovieInfo(
        movie_id="tmdb-1",
        title="Empty House",
        original_title="Bin-jip",
        title_zh="空房间",
        year=2004,
    )
    wrong_year = candidate(
        "iron",
        "铁肺 Iron.Lung.2026.2160p.WEB-DL.HDR",
        20,
    )
    assert not has_movie_identity_match(wrong_year, movie)
    scored = score_candidate(wrong_year, movie)
    assert scored.scores["yearScore"] == -150


def test_identity_rejects_valkyrie_for_passion():
    movie = MovieInfo(
        movie_id="tmdb-1",
        title="The Passion of the Christ",
        original_title="The Passion of the Christ",
        title_zh="耶稣受难记",
        year=2004,
    )
    wrong = candidate("val", "Valkyrie.2008.BluRay.720p.x264.DTS-WiKi.ass", 10)
    assert not has_movie_identity_match(wrong, movie)


def test_identity_accepts_matching_bilingual_same_year():
    movie = MovieInfo(
        movie_id="tmdb-1",
        title="Howl's Moving Castle",
        original_title="Hauru no ugoku shiro",
        title_zh="哈尔的移动城堡",
        year=2004,
    )
    item = candidate(
        "howl",
        "哈尔的移动城堡 Howls.Moving.Castle.2004.JAPANESE.1080p.BluRay.chs&eng",
        80,
    )
    assert has_movie_identity_match(item, movie)
    scored = score_candidate(item, movie)
    assert scored.scores["yearScore"] == 100


def test_build_movie_search_keywords_includes_year():
    movie = MovieInfo(
        movie_id="tmdb-1",
        title="The Notebook",
        original_title="The Notebook",
        title_zh="恋恋笔记本",
        year=2004,
    )
    keywords = build_movie_search_keywords(movie)
    assert "恋恋笔记本" in keywords
    assert "恋恋笔记本 2004" in keywords
    assert "The Notebook 2004" in keywords
