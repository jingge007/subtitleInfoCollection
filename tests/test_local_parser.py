from subtitle_info_collection.local_parser import build_movie_search_keywords, parse_local_subtitle_file


def test_build_movie_search_keywords_removes_release_noise():
    keywords = build_movie_search_keywords("Example.Movie.2026.1080p.BluRay.CHS.ENG.ass")
    assert any("Example Movie 2026" in item for item in keywords)


async def test_parse_local_subtitle_file_without_tmdb(tmp_path):
    path = tmp_path / "Example.Movie.2026.简英双语.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n你好\nHello\n",
        encoding="utf-8",
    )
    parsed = await parse_local_subtitle_file(path)
    assert parsed.original_subtitle_count == 1
    assert len(parsed.subtitles) == 1
    assert parsed.payload()["subtitlesData"][0]["zhContent"] == "你好"

