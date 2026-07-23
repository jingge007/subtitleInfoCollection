from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from subtitle_info_collection.automation.classic_lines import (
    ClassicLinesAutomationOptions,
    ClassicLinesAutomationRunner,
    _find_lean_js_url,
    _find_lines_index_js_url,
    _js_to_json,
    _parse_detail_lean_js,
    _parse_index_movie_ids,
    _parse_index_movies,
    _parse_listing_movies,
    collect_missing_fields,
    flatten_classic_lines_data,
    write_classic_lines_export_files,
)


SAMPLE_LISTING_HTML = """
<a class="line-movie-card" href="/lines/234">
  <h2>业余小偷经典台词</h2>
  <img src="https://example.com/cover.jpg" />
  <div class="line-movie-meta">
    <span>14 句对白</span>
    <span>豆瓣 7.4</span>
  </div>
</a>
"""

SAMPLE_LEAN_JS = """
const u=JSON.parse('{"title":"x"}');
const m=Object.assign(i,{setup(s){const e={movie:{id:234,zhName:"业余小偷",cover:"https://x.jpg",director:"伍迪·艾伦",screenwriter:"伍迪·艾伦",region:"美国",releaseDate:"2000-05-19",actor:"伍迪·艾伦",lang:"英语",type:"喜剧 / 犯罪",doubanStar:7.4,classicLineCount:1},intro:"",classicLines:[{sentence:`I love you. Can I tell you this?`,zhSentence:"我爱你。",keywords:["love you"],lines:[{id:"1",content:"I love you.",zhContent:"我爱你。"}]}]};return e}});
"""

# 模拟失败页：e 仅为 movie 元数据，完整详情在 t
SAMPLE_LEAN_JS_ALT_VAR = """
const e={id:613,zhName:"侏罗纪公园3",cover:"https://x.jpg",director:"乔·庄斯顿",screenwriter:"A",region:"美国",releaseDate:"2001",actor:"B",lang:"英语",type:"冒险",doubanStar:7.1,classicLineCount:1};
const t={movie:{id:613,zhName:"侏罗纪公园3",cover:"https://x.jpg",director:"乔·庄斯顿",screenwriter:"A / B",region:"美国",releaseDate:"2001-07-18",actor:"山姆·尼尔",lang:"英语",type:"冒险 / 科幻",doubanStar:7.1,classicLineCount:1},intro:"",classicLines:[{sentence:`You got to go slowly.`,zhSentence:"你得慢慢来。",keywords:["slowly"],lines:[]}]};
"""


def test_parse_listing_movies_strips_suffix_and_reads_meta():
    movies = _parse_listing_movies(SAMPLE_LISTING_HTML)
    assert len(movies) == 1
    assert movies[0]["id"] == 234
    assert movies[0]["name"] == "业余小偷"
    assert movies[0]["quoteCount"] == 14
    assert movies[0]["doubanRating"] == 7.4


def test_find_lean_js_url_allows_underscore_hash():
    html = '<script src="/assets/lines_289.md.CVFinP_g.lean.js"></script>'
    assert _find_lean_js_url(html, 289) == "https://33tc.net/assets/lines_289.md.CVFinP_g.lean.js"


def test_find_lines_index_js_url():
    html = '<link href="/assets/lines_index.md.foz-p6Br.lean.js">'
    assert (
        _find_lines_index_js_url(html)
        == "https://33tc.net/assets/lines_index.md.foz-p6Br.lean.js"
    )


def test_parse_index_movie_ids_from_movies_array_ref():
    js_text = (
        'const G=[{id:234,zhName:"业余小偷"},{id:247,zhName:"香笺泪"}];'
        "F={movies:G};"
    )
    assert _parse_index_movie_ids(js_text) == [234, 247]


def test_parse_index_movies_keeps_zh_name():
    js_text = (
        'const G=[{id:234,zhName:"业余小偷",cover:"https://a.jpg",doubanStar:7.4}];'
        "F={movies:G};"
    )
    movies = _parse_index_movies(js_text)
    assert movies[0]["zhName"] == "业余小偷"
    assert movies[0]["cover"] == "https://a.jpg"


def test_js_to_json_handles_backtick_strings():
    raw = '{sentence:`Then I began "lose" temper.`,count:1}'
    data = json.loads(_js_to_json(raw))
    assert data["sentence"] == 'Then I began "lose" temper.'
    assert data["count"] == 1


def test_parse_detail_lean_js_builds_expected_fields():
    result = _parse_detail_lean_js(SAMPLE_LEAN_JS)
    assert result is not None
    assert result["name"] == "业余小偷"
    assert result["detail"]["title"] == "电影 业余小偷 中的 1 句经典对白"
    assert result["detail"]["info"]["导演"] == "伍迪·艾伦"
    assert "<mark>love you</mark>" in result["detail"]["classicLines"][0]["content"]
    assert collect_missing_fields(result) == []


def test_parse_detail_lean_js_uses_non_e_payload_variable():
    result = _parse_detail_lean_js(SAMPLE_LEAN_JS_ALT_VAR)
    assert result is not None
    assert result["id"] == 613
    assert result["name"] == "侏罗纪公园3"
    assert result["detail"]["classicLines"][0]["zhTranslation"] == "你得慢慢来。"
    assert collect_missing_fields(result) == []


def test_collect_missing_fields_reports_required_gaps():
    missing = collect_missing_fields({
        "id": None,
        "name": "",
        "cover": "",
        "quoteCount": 0,
        "doubanRating": None,
        "detail": {"info": {}, "classicLines": []},
    })
    assert "classicLinesId" in missing
    assert "name" in missing
    assert "cover" in missing
    assert "quoteCount" in missing
    assert "doubanRating" in missing
    assert "detail.classicLines" in missing
    assert "detail.info.导演" in missing


def test_flatten_and_export_unicloud_jsonl(tmp_path: Path):
    movies = [
        {
            "id": 234,
            "name": "业余小偷",
            "detail": {"id": 234, "classicLines": []},
        }
    ]
    records = flatten_classic_lines_data(movies)
    assert records[0]["classicLinesId"] == 234
    assert "id" not in records[0]
    assert records[0]["detail"]["classicLinesId"] == 234

    export = write_classic_lines_export_files(
        records, tmp_path, "20260722", unicloud_import_format=True
    )
    assert export.export_format == "unicloud-jsonl"
    assert export.paths[0].exists()
    line = export.paths[0].read_text(encoding="utf-8").strip()
    assert json.loads(line)["classicLinesId"] == 234


@pytest.mark.asyncio
async def test_runner_page_logs_and_skips_incomplete(tmp_path: Path):
    index_js = (
        'const G=['
        '{id:234,zhName:"业余小偷"},'
        '{id:613,zhName:"侏罗纪公园3"}'
        '];F={movies:G};'
    )
    listing_html = '<link href="/assets/lines_index.md.test.lean.js">'
    detail_234_html = '<script src="/assets/lines_234.md.aaa.lean.js"></script>'
    detail_613_html = '<script src="/assets/lines_613.md.bbb.lean.js"></script>'
    # 613 只有空壳 e，没有 movie+classicLines 详情对象
    lean_613_empty = 'const e={id:613,zhName:"侏罗纪公园3",cover:"https://x.jpg"};'

    responses = {
        "https://33tc.net/lines/": listing_html,
        "https://33tc.net/assets/lines_index.md.test.lean.js": index_js,
        "https://33tc.net/lines/234": detail_234_html,
        "https://33tc.net/assets/lines_234.md.aaa.lean.js": SAMPLE_LEAN_JS,
        "https://33tc.net/lines/613": detail_613_html,
        "https://33tc.net/assets/lines_613.md.bbb.lean.js": lean_613_empty,
    }

    # 按 URL 返回预置 HTML/JS，模拟站点响应
    def handler(request: httpx.Request) -> httpx.Response:
        text = responses.get(str(request.url))
        if text is None:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, text=text)

    logs: list[str] = []
    options = ClassicLinesAutomationOptions(
        data_dir=tmp_path,
        page_size=24,
        concurrency=2,
        request_delay_seconds=0.0,
        unicloud_import_format=True,
    )
    runner = ClassicLinesAutomationRunner(
        options,
        transport=httpx.MockTransport(handler),
        log=logs.append,
    )
    result = await runner.run()

    assert result.total_movies == 1
    assert result.failed_movies == 1
    assert any("===== 第 1/1 页（本页 2 部）=====" in line for line in logs)
    assert any("[成功] 1. 业余小偷" in line for line in logs)
    assert any(line.startswith("[失败] 2. 侏罗纪公园3 | 缺失:") for line in logs)
    assert any("采集完成：成功 1 部，失败 1 部" in line for line in logs)

    export_text = result.output_path.read_text(encoding="utf-8").strip()
    assert "业余小偷" in export_text
    assert "侏罗纪公园3" not in export_text
