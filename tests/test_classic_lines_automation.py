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
async def test_runner_fetches_all_pages_and_writes_to_automation_dir(tmp_path) -> None:
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
    assert json.loads(result.output_path.read_text(encoding="utf-8")) == [
        {"id": 1},
        {"id": 2},
        {"id": 3},
    ]
