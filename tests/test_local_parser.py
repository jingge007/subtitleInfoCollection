from subtitle_info_collection.local_parser import build_movie_search_keywords, parse_local_subtitle_file


def make_srt_text(repeat: int) -> str:
    return (
        "1\n00:00:01,000 --> 00:00:02,000\n你好\n"
        f"{'Hello world ' * repeat}\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n世界\n"
        f"{'World again ' * repeat}\n\n"
        "3\n00:00:05,000 --> 00:00:06,000\n测试\n"
        f"{'Test subtitle ' * repeat}\n\n"
        "4\n00:00:07,000 --> 00:00:08,000\n中文\n"
        f"{'English content ' * repeat}\n\n"
        "5\n00:00:09,000 --> 00:00:10,000\n感谢\n"
        f"{'Thanks friend ' * repeat}\n"
    )


def test_build_movie_search_keywords_removes_release_noise():
    keywords = build_movie_search_keywords("Example.Movie.2026.1080p.BluRay.CHS.ENG.ass")
    assert any("Example Movie 2026" in item for item in keywords)


async def test_parse_local_subtitle_file_without_tmdb(tmp_path):
    path = tmp_path / "Example.Movie.2026.简英双语.srt"
    path.write_text(make_srt_text(2500), encoding="utf-8")
    parsed = await parse_local_subtitle_file(path)
    assert parsed.original_subtitle_count == 5
    assert len(parsed.subtitles) == 5
    assert len(parsed.payload()["subtitlesData"][0]["zhContent"]) > 0


async def test_parse_local_subtitle_file_rejects_under_100kb(tmp_path):
    path = tmp_path / "Example.Movie.2026.简英双语.srt"
    path.write_text(make_srt_text(1), encoding="utf-8")

    try:
        await parse_local_subtitle_file(path)
    except ValueError as exc:
        assert "小于 100KB" in str(exc)
    else:
        raise AssertionError("Expected small subtitle file to be rejected")

