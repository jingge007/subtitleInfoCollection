import json

from subtitle_info_collection import local_parser
from subtitle_info_collection.local_parser import (
    build_movie_search_keywords,
    parse_local_subtitle_file,
    write_subtitle_export_files,
)
from subtitle_info_collection.models import MovieInfo


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


async def test_parse_local_subtitle_file_strips_tmdb_prefix(tmp_path, monkeypatch):
    path = tmp_path / "Example.Movie.2026.srt"
    path.write_text(make_srt_text(2500), encoding="utf-8")

    async def fake_match_movie(path_arg, tmdb_token=""):
        return MovieInfo(movie_id="tmdb-533514", tmdb_id=533514, title="Example Movie"), "Example"

    monkeypatch.setattr(local_parser, "_match_movie", fake_match_movie)

    parsed = await local_parser.parse_local_subtitle_file(path, "token")
    payload = parsed.payload()

    assert payload["movieId"] == "533514"
    assert payload["movieData"]["id"] == "533514"
    assert payload["movieData"]["movieId"] == "533514"
    assert payload["movieData"]["tmdbId"] == 533514
    assert payload["subtitlesData"][0]["movieId"] == "533514"
    assert payload["subtitlesData"][0]["subtitlesId"].startswith("533514-")


async def test_parse_local_subtitle_file_rejects_under_100kb(tmp_path):
    path = tmp_path / "Example.Movie.2026.简英双语.srt"
    path.write_text(make_srt_text(1), encoding="utf-8")

    try:
        await parse_local_subtitle_file(path)
    except ValueError as exc:
        assert "小于 100KB" in str(exc)
    else:
        raise AssertionError("Expected small subtitle file to be rejected")


def test_write_subtitle_export_files_defaults_to_unicloud_jsonl(tmp_path):
    subtitles = [
        {
            "subtitlesId": "533514-1",
            "movieId": "533514",
            "startTime": "00:01:46",
            "endTime": "00:01:48",
            "zhContent": "时候到了",
            "enContent": "It is time.",
            "content": "时候到了\nIt is time.",
        },
        {
            "subtitlesId": "533514-2",
            "movieId": "533514",
            "startTime": "00:02:24",
            "endTime": "00:02:25",
            "zhContent": "很美吧",
            "enContent": "It's beautiful, isn't it?",
            "content": "很美吧\nIt's beautiful, isn't it?",
        },
    ]

    result = write_subtitle_export_files(subtitles, tmp_path, "20260506-143732")

    assert result.export_format == "unicloud-jsonl"
    assert result.paths == [tmp_path / "20260506-143732-subtitles.json"]
    lines = result.paths[0].read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == subtitles


def test_write_subtitle_export_files_splits_unicloud_jsonl_by_bytes(tmp_path):
    subtitles = [
        {
            "subtitlesId": f"533514-{index}",
            "movieId": "533514",
            "startTime": "00:00:01",
            "endTime": "00:00:02",
            "zhContent": "测试",
            "enContent": "Test",
            "content": "测试\n" + ("Test " * 10),
        }
        for index in range(1, 5)
    ]

    result = write_subtitle_export_files(
        subtitles,
        tmp_path,
        "20260506-143732",
        split_limit_bytes=220,
    )

    assert [path.name for path in result.paths] == [
        "20260506-143732-subtitles-1.json",
        "20260506-143732-subtitles-2.json",
        "20260506-143732-subtitles-3.json",
        "20260506-143732-subtitles-4.json",
    ]
    assert all(path.stat().st_size <= 220 for path in result.paths)
    loaded = [
        json.loads(line)
        for path in result.paths
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert loaded == subtitles


def test_write_subtitle_export_files_can_keep_legacy_json_array(tmp_path):
    subtitles = [
        {
            "subtitlesId": "533514-1",
            "movieId": "533514",
            "startTime": "00:01:46",
            "endTime": "00:01:48",
            "zhContent": "时候到了",
            "enContent": "It is time.",
            "content": "时候到了\nIt is time.",
        }
    ]

    result = write_subtitle_export_files(
        subtitles,
        tmp_path,
        "20260506-143732",
        unicloud_import_format=False,
    )

    assert result.export_format == "json-array"
    assert result.paths == [tmp_path / "20260506-143732-subtitles.json"]
    assert json.loads(result.paths[0].read_text(encoding="utf-8")) == subtitles

