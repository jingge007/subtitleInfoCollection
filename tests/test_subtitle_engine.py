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


def make_mixed_srt_bytes(
    bilingual: int = 0,
    chinese_only: int = 0,
    english_only: int = 0,
) -> bytes:
    blocks = []
    index = 1
    for _ in range(bilingual):
        blocks.append(f"{index}\n00:00:01,000 --> 00:00:02,000\n你好\nHello world\n\n")
        index += 1
    for _ in range(chinese_only):
        blocks.append(f"{index}\n00:00:01,000 --> 00:00:02,000\n你好，这是中文字幕\n\n")
        index += 1
    for _ in range(english_only):
        blocks.append(f"{index}\n00:00:01,000 --> 00:00:02,000\nThis is English only\n\n")
        index += 1
    return "".join(blocks).encode()


def make_ass_bytes(bilingual: int = 0, chinese_only: int = 0) -> bytes:
    lines = [
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for _ in range(bilingual):
        lines.append("Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,你好\\NHello")
    for _ in range(chinese_only):
        lines.append("Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,你好，这是中文字幕")
    return ("\n".join(lines) + "\n").encode()


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
    assert "字幕条目过少" in validation.reason


def test_validate_downloaded_subtitle_bytes_accepts_structured_movie_subtitle_under_100kb():
    data = make_srt_bytes(1600)
    assert len(data) < 100 * 1024

    validation = validate_downloaded_subtitle_bytes(data, "srt", "demo.srt")

    assert validation.valid
    assert validation.entry_count == 1600
    assert validation.bilingual_ratio == 1.0


def test_validate_downloaded_subtitle_bytes_requires_bilingual_content():
    data = make_srt_bytes(2500)
    validation = validate_downloaded_subtitle_bytes(data, "srt", "demo.srt")
    assert validation.valid
    assert validation.bilingual_count == 2500
    assert validation.entry_count == 2500
    assert validation.bilingual_ratio == 1.0

    invalid = ("1\n00:00:01,000 --> 00:00:02,000\n你好\n\n" * 4000).encode()
    invalid_validation = validate_downloaded_subtitle_bytes(invalid, "srt", "demo.srt")
    assert not invalid_validation.valid
    assert invalid_validation.error_type == "CONTENT_VALIDATION_FAILED"
    assert "双语占比不足" in invalid_validation.reason


def test_validate_downloaded_subtitle_bytes_requires_default_70_percent_bilingual_ratio():
    valid = validate_downloaded_subtitle_bytes(
        make_mixed_srt_bytes(bilingual=2100, chinese_only=900),
        "srt",
        "demo.srt",
    )
    assert valid.valid
    assert valid.entry_count == 3000
    assert valid.bilingual_count == 2100
    assert valid.chinese_only_count == 900
    assert valid.bilingual_ratio == 0.7

    invalid = validate_downloaded_subtitle_bytes(
        make_mixed_srt_bytes(bilingual=2070, chinese_only=930),
        "srt",
        "demo.srt",
    )
    assert not invalid.valid
    assert invalid.error_type == "CONTENT_VALIDATION_FAILED"
    assert "双语占比不足(69.0%)" in invalid.reason
    assert "双语占比不足" in invalid.reason
    assert "69.0%" in invalid.reason


def test_validate_downloaded_subtitle_bytes_accepts_custom_bilingual_ratio():
    validation = validate_downloaded_subtitle_bytes(
        make_mixed_srt_bytes(bilingual=1500, chinese_only=1500),
        "srt",
        "demo.srt",
        min_bilingual_ratio=0.50,
    )
    assert validation.valid
    assert validation.bilingual_ratio == 0.5
    assert validation.min_bilingual_ratio == 0.5


def test_validate_downloaded_subtitle_bytes_rejects_english_only_content():
    validation = validate_downloaded_subtitle_bytes(
        make_mixed_srt_bytes(english_only=4000),
        "srt",
        "demo.srt",
    )
    assert not validation.valid
    assert validation.error_type == "CONTENT_VALIDATION_FAILED"
    assert "纯英文字幕" in validation.reason


def test_validate_downloaded_subtitle_bytes_checks_ass_bilingual_ratio():
    validation = validate_downloaded_subtitle_bytes(
        make_ass_bytes(bilingual=1400, chinese_only=600),
        "ass",
        "demo.ass",
    )
    assert validation.valid
    assert validation.bilingual_ratio == 0.7

    invalid = validate_downloaded_subtitle_bytes(
        make_ass_bytes(bilingual=1300, chinese_only=700),
        "ass",
        "demo.ass",
    )
    assert not invalid.valid
    assert "双语占比不足(65.0%)" in invalid.reason


def test_validate_downloaded_subtitle_bytes_lenient_still_rejects_chinese_only_content():
    data = ("1\n00:00:01,000 --> 00:00:02,000\n你好，这是中文字幕\n\n" * 4000).encode()
    validation = validate_downloaded_subtitle_bytes(data, "srt", "demo.srt", lenient=True)
    assert not validation.valid
    assert validation.error_type == "CONTENT_VALIDATION_FAILED"


def test_looks_like_english_only_candidate_detects_eng_filename():
    from subtitle_info_collection.engines.subtitle_engine import looks_like_english_only_candidate
    from subtitle_info_collection.models import SubtitleCandidate

    eng = SubtitleCandidate(
        provider="subdl",
        provider_subtitle_id="1",
        movie_id="m1",
        movie_title="Inception",
        subtitle_title="Inception.2010.1080p.eng.srt",
        language_type="English",
        file_names=["Inception.2010.1080p.eng.srt"],
    )
    bilingual = SubtitleCandidate(
        provider="subdl",
        provider_subtitle_id="2",
        movie_id="m1",
        movie_title="Inception",
        subtitle_title="Inception.2010.chs&eng.srt",
        language_type="双语",
        file_names=["Inception.2010.chs&eng.srt"],
    )
    # 站点误标双语，但文件名明显纯英 → 视为伪双语
    mislabeled = SubtitleCandidate(
        provider="assrt",
        provider_subtitle_id="3",
        movie_id="m1",
        movie_title="Tropa de Elite",
        subtitle_title="Tropa.De.Elite.2007.720p.BluRay.x264-CtrlHD.eng.srt",
        language_type="中英双语",
        file_names=["Tropa.De.Elite.2007.720p.BluRay.x264-CtrlHD.eng.srt"],
    )
    assert looks_like_english_only_candidate(eng) is True
    assert looks_like_english_only_candidate(bilingual) is False
    assert looks_like_english_only_candidate(mislabeled) is True


def test_validate_candidate_metadata_lenient_rejects_english_only_language_type():
    validation = validate_candidate_metadata(
        make_candidate(
            subtitle_title="Inception.2010.1080p.srt",
            language_type="English",
            subtitle_format="srt",
            description="English subtitle",
        ),
        lenient=True,
    )
    assert not validation.valid
    assert validation.error_type == "INVALID_LANGUAGE"
    assert "中文与英文" in validation.reason


def test_validate_candidate_metadata_lenient_accepts_chinese_and_english_markers():
    validation = validate_candidate_metadata(
        make_candidate(
            subtitle_title="盗梦空间.2010.中英.srt",
            language_type="中文",
            subtitle_format="srt",
            description="Chinese English",
        ),
        lenient=True,
    )
    assert validation.valid

