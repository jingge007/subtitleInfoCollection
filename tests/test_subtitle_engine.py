from subtitle_info_collection.engines.subtitle_engine import (
    decode_subtitle_bytes,
    parse_subtitle_text,
    validate_candidate_metadata,
    validate_downloaded_subtitle_bytes,
)
from subtitle_info_collection.models import SubtitleCandidate


def make_srt_bytes(repeat: int = 1) -> bytes:
    block = "1\n00:00:01,000 --> 00:00:02,000\n你好\nHello world\n\n"
    return (block * repeat).encode()


def make_candidate(**patch):
    data = {
        "provider": "subhd",
        "provider_subtitle_id": "1",
        "movie_id": "tmdb-1",
        "movie_title": "Example Movie",
        "subtitle_title": "Example.Movie.2026.简英双语.1080p.ass",
        "language_type": "简体/英语/双语",
        "subtitle_format": "ass",
    }
    data.update(patch)
    return SubtitleCandidate(**data)


def test_parse_srt_bilingual_entries():
    content = """1
00:00:01,000 --> 00:00:02,000
你好
Hello

2
00:00:03,000 --> 00:00:04,000
再见 Goodbye
"""
    entries = parse_subtitle_text(content, "srt", "movie-1")
    assert len(entries) == 2
    assert entries[0].zh_content == "你好"
    assert entries[0].en_content == "Hello"
    assert entries[1].zh_content == "再见"
    assert entries[1].en_content == "Goodbye"
    assert entries[0].start_time == "00:00:01"


def test_parse_ass_dialogue_entries():
    content = """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,你好\\NHello
"""
    entries = parse_subtitle_text(content, "ass", "movie-1")
    assert len(entries) == 1
    assert entries[0].zh_content == "你好"
    assert entries[0].en_content == "Hello"


def test_decode_gb18030_subtitle():
    data = "1\n00:00:01,000 --> 00:00:02,000\n你好\nHello\n".encode("gb18030")
    decoded = decode_subtitle_bytes(data)
    assert "你好" in decoded.content
    assert decoded.replacement_count <= 5


def test_validate_candidate_metadata_accepts_bilingual_ass():
    validation = validate_candidate_metadata(make_candidate())
    assert validation.valid
    assert validation.subtitle_format == "ass"


def test_validate_candidate_metadata_rejects_traditional_only():
    validation = validate_candidate_metadata(
        make_candidate(
            subtitle_title="Example.Movie.繁体.英文.srt",
            language_type="繁体/英语",
            subtitle_format="srt",
        )
    )
    assert not validation.valid
    assert validation.error_type == "INVALID_LANGUAGE"


def test_validate_downloaded_subtitle_bytes_rejects_small_movie_subtitle_file():
    data = make_srt_bytes(1)
    validation = validate_downloaded_subtitle_bytes(data, "srt", "demo.srt")
    assert not validation.valid
    assert validation.error_type == "CONTENT_VALIDATION_FAILED"
    assert "小于 100KB" in validation.reason


def test_validate_downloaded_subtitle_bytes_requires_bilingual_content():
    data = make_srt_bytes(2500)
    validation = validate_downloaded_subtitle_bytes(data, "srt", "demo.srt")
    assert validation.valid
    assert validation.bilingual_count == 2500

    invalid = ("1\n00:00:01,000 --> 00:00:02,000\n你好\n\n" * 4000).encode()
    invalid_validation = validate_downloaded_subtitle_bytes(invalid, "srt", "demo.srt")
    assert not invalid_validation.valid
    assert invalid_validation.error_type == "CONTENT_VALIDATION_FAILED"


def test_validate_downloaded_subtitle_bytes_lenient_still_rejects_chinese_only_content():
    data = ("1\n00:00:01,000 --> 00:00:02,000\n你好，这是中文字幕\n\n" * 4000).encode()
    validation = validate_downloaded_subtitle_bytes(data, "srt", "demo.srt", lenient=True)
    assert not validation.valid
    assert validation.error_type == "CONTENT_VALIDATION_FAILED"

