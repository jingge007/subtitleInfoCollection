from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from subtitle_info_collection.engines.archives import save_downloaded_payloads
from subtitle_info_collection.errors import CollectorError
from subtitle_info_collection.models import DownloadedPayload, SubtitleCandidate


def make_candidate() -> SubtitleCandidate:
    return SubtitleCandidate(
        provider="assrt",
        provider_subtitle_id="sub-1",
        movie_id="movie-1",
        movie_title="Example Movie",
        subtitle_title="Example.Movie.2026.简英双语.srt",
        language_type="简体/英语/双语",
        subtitle_format="srt",
    )


def make_srt_bytes(repeat: int) -> bytes:
    block = "1\n00:00:01,000 --> 00:00:02,000\n你好\nHello world\n\n"
    return (block * repeat).encode()


def make_zip_payload(file_name: str, content: bytes) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(file_name, content)
    return buffer.getvalue()


def test_save_downloaded_payloads_rejects_zip_with_small_real_subtitle(tmp_path):
    payload = DownloadedPayload(
        file_name="subtitle.zip",
        content=make_zip_payload("small.srt", make_srt_bytes(1)),
    )

    with pytest.raises(CollectorError, match="小于 100KB"):
        save_downloaded_payloads([payload], tmp_path, "Example Movie", make_candidate())


def test_save_downloaded_payloads_accepts_zip_with_large_real_subtitle(tmp_path):
    payload = DownloadedPayload(
        file_name="subtitle.zip",
        content=make_zip_payload("large.srt", make_srt_bytes(2500)),
    )

    saved_paths = save_downloaded_payloads([payload], tmp_path, "Example Movie", make_candidate())

    assert len(saved_paths) == 1
    assert saved_paths[0].suffix == ".srt"
    assert saved_paths[0].stat().st_size > 100 * 1024
