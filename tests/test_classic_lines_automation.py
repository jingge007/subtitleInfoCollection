from __future__ import annotations

import hashlib
import json
from datetime import datetime

import httpx
import pytest

from subtitle_info_collection.automation.classic_lines import (
    ClassicLinesAutomationOptions,
    ClassicLinesAutomationRunner,
    generate_signed_params,
    prepare_classic_line_import_payload,
    write_classic_line_export_files,
)


def test_generate_signed_params_matches_legacy_md5_rule() -> None:
    signed = generate_signed_params(
        {
            "page": 2,
            "limit": 50,
            "_platform": "web",
            "_versioin": "0.2.5",
        },
        timestamp_ms=1234567890,
    )

    expected_source = "_platform=web,_ts=1234567890,_versioin=0.2.5,limit=50,page=2,"
    assert signed.timestamp_ms == 1234567890
    assert signed.signature == hashlib.md5(expected_source.encode()).hexdigest()
    assert signed.params["_ts"] == 1234567890


@pytest.mark.asyncio
async def test_runner_fetches_all_pages_and_writes_unicloud_jsonl_by_default(tmp_path) -> None:
    seen_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-token"] == "cached-token"
        assert request.headers["x-signature"]
        page = int(request.url.params["page"])
        seen_pages.append(page)
        if page == 1:
            payload = {"code": 0, "data": {"list": [{"id": 1}, {"id": 2}], "total": 3}}
        elif page == 2:
            payload = {"code": 0, "data": {"list": [{"id": 3}], "total": 3}}
        else:
            payload = {"code": 0, "data": {"list": [], "total": 3}}
        return httpx.Response(200, json=payload)

    runner = ClassicLinesAutomationRunner(
        ClassicLinesAutomationOptions(
            data_dir=tmp_path,
            env_path=tmp_path / ".env",
            page_size=2,
            request_delay_seconds=0,
            now_provider=lambda: datetime(2026, 5, 5, 8, 9, 10),
        ),
        token_provider=lambda: "cached-token",
        transport=httpx.MockTransport(handler),
    )

    result = await runner.run()

    assert seen_pages == [1, 2]
    assert result.total_count == 3
    assert result.output_path.parent == tmp_path / "automation"
    assert result.output_path.name == "classic-lines-2026-05-05_08-09-10.json"
    assert result.export_format == "unicloud-jsonl"
    assert [
        json.loads(line)
        for line in result.output_path.read_text(encoding="utf-8").splitlines()
    ] == [
        {"classicLinesId": 1, "zhContent": "", "enContent": "", "movieName": "", "picUrl": "", "movieId": 1},
        {"classicLinesId": 2, "zhContent": "", "enContent": "", "movieName": "", "picUrl": "", "movieId": 2},
        {"classicLinesId": 3, "zhContent": "", "enContent": "", "movieName": "", "picUrl": "", "movieId": 3},
    ]
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "CLASSIC_LINES_TOKEN=cached-token" in env_text
    assert not (tmp_path / "automation" / "classic-lines-token-cache.json").exists()


@pytest.mark.asyncio
async def test_runner_can_keep_legacy_json_array_export(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"list": [{"id": 1}], "total": 1}})

    runner = ClassicLinesAutomationRunner(
        ClassicLinesAutomationOptions(
            data_dir=tmp_path,
            env_path=tmp_path / ".env",
            request_delay_seconds=0,
            unicloud_import_format=False,
            now_provider=lambda: datetime(2026, 5, 5, 8, 9, 10),
        ),
        token_provider=lambda: "cached-token",
        transport=httpx.MockTransport(handler),
    )

    result = await runner.run()

    assert result.export_format == "json-array"
    assert json.loads(result.output_path.read_text(encoding="utf-8")) == [{"id": 1}]


def test_write_classic_line_export_files_splits_unicloud_jsonl_by_bytes(tmp_path) -> None:
    records = [
        {"classicLinesId": index, "zhContent": "测", "enContent": "Test"}
        for index in range(1, 5)
    ]

    result = write_classic_line_export_files(
        records,
        tmp_path,
        "2026-05-05_08-09-10",
        split_limit_bytes=70,
    )

    assert [path.name for path in result.paths] == [
        "classic-lines-2026-05-05_08-09-10-1.json",
        "classic-lines-2026-05-05_08-09-10-2.json",
        "classic-lines-2026-05-05_08-09-10-3.json",
        "classic-lines-2026-05-05_08-09-10-4.json",
    ]
    assert all(path.stat().st_size <= 70 for path in result.paths)
    loaded = [
        json.loads(line)
        for path in result.paths
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert loaded == records


@pytest.mark.asyncio
async def test_prepare_classic_line_import_payload_transforms_dedupes_and_translates_once() -> None:
    calls: list[str] = []

    async def translate(text: str) -> str:
        calls.append(text)
        return "Translated line"

    payload = await prepare_classic_line_import_payload(
        [
            {"id": "10", "description": "台词", "movieName": "电影", "subtitlesId": "old-subtitle-id"},
            {"classicLinesId": 10, "zhContent": "台词", "movieName": "电影"},
            {
                "id": "11",
                "description": "台词",
                "originContent": "Existing English",
                "subtitle": {
                    "subtitlesId": "nested-subtitle-id",
                    "video": {"title": "Fallback Movie", "cover": "cover.jpg"},
                },
            },
        ],
        translate_text=translate,
    )

    assert calls == ["台词"]
    assert payload.input_count == 3
    assert payload.local_duplicate_count == 1
    assert payload.translation_requested_count == 1
    assert payload.translation_filled_count == 1
    assert payload.records[0]["classicLinesId"] == 10
    assert payload.records[0]["movieId"] == 10
    assert "subtitlesId" not in payload.records[0]
    assert payload.records[0]["zhContent"] == "台词"
    assert payload.records[0]["enContent"] == "Translated line"
    assert payload.records[1]["classicLinesId"] == 11
    assert payload.records[1]["movieId"] == 11
    assert "subtitlesId" not in payload.records[1]
    assert "subtitlesId" not in payload.records[1]["subtitle"]
    assert payload.records[1]["movieName"] == "Fallback Movie"
