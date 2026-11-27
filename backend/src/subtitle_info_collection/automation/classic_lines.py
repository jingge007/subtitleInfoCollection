from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


BASE_URL = "https://33tc.net"
LINES_LIST_URL = f"{BASE_URL}/lines/"
UNICLOUD_IMPORT_SPLIT_BYTES = 45 * 1024 * 1024
INFO_FIELD_MAP = (
    ("导演", "director"),
    ("编剧", "screenwriter"),
    ("主演", "actor"),
    ("类型", "type"),
)


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]
SleepCallback = Callable[[float], Awaitable[None]]


class ClassicLinesAutomationError(RuntimeError):
    """经典台词采集异常"""


@dataclass(frozen=True, slots=True)
class ClassicLinesExportResult:
    paths: list[Path]
    export_format: str
    split_limit_bytes: int | None = None
    oversized_records: int = 0


@dataclass(slots=True)
class ClassicLinesAutomationOptions:
    data_dir: Path
    page_size: int = 24
    request_delay_seconds: float = 0.0
    concurrency: int = 8
    headless: bool = True
    max_pages: int | None = None
    unicloud_import_format: bool = True
    split_limit_bytes: int = UNICLOUD_IMPORT_SPLIT_BYTES
    now_provider: Callable[[], datetime] = field(default_factory=lambda: datetime.now)

    @property
    def automation_dir(self) -> Path:
        return self.data_dir / "automation"


@dataclass(frozen=True, slots=True)
class ClassicLinesAutomationResult:
    output_path: Path
    output_paths: list[Path]
    total_movies: int
    failed_movies: int
    total_lines: int
    page_count: int
    started_at: str
    finished_at: str
    export_format: str
    split_limit_bytes: int | None = None
    oversized_records: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "outputPath": str(self.output_path),
            "outputPaths": [str(p) for p in self.output_paths],
            "totalMovies": self.total_movies,
            "failedMovies": self.failed_movies,
            "totalLines": self.total_lines,
            "pageCount": self.page_count,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "exportFormat": self.export_format,
        }


@dataclass(frozen=True, slots=True)
class _MovieFetchOutcome:
    index: int
    movie_id: int
    display_name: str
    record: dict[str, Any] | None
    missing: list[str]

    @property
    def ok(self) -> bool:
        return self.record is not None and not self.missing


def _find_matching_bracket(text: str, start: int) -> int:
    bracket = text[start]
    close = {"{": "}", "[": "]"}[bracket]
    count = 0
    in_string: str | None = None
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in ('"', "'", "`"):
            in_string = ch
            continue
        if ch == bracket:
            count += 1
        elif ch == close:
            count -= 1
            if count == 0:
                return i
    return len(text) - 1


# 将 JS 字符串字面量（含单引号/反引号）转为 JSON 双引号字符串
def _convert_js_string_literals(js_text: str) -> str:
    result: list[str] = []
    i = 0
    n = len(js_text)
    while i < n:
        ch = js_text[i]
        if ch not in ('"', "'", "`"):
            result.append(ch)
            i += 1
            continue
        quote = ch
        i += 1
        chars: list[str] = []
        while i < n:
            c = js_text[i]
            if c == "\\" and i + 1 < n:
                nxt = js_text[i + 1]
                if nxt == "n":
                    chars.append("\n")
                elif nxt == "r":
                    chars.append("\r")
                elif nxt == "t":
                    chars.append("\t")
                elif nxt == "\\":
                    chars.append("\\")
                elif nxt in ('"', "'", "`"):
                    chars.append(nxt)
                else:
                    chars.append(nxt)
                i += 2
                continue
            if c == quote:
                i += 1
                break
            chars.append(c)
            i += 1
        result.append(json.dumps("".join(chars), ensure_ascii=False))
    return "".join(result)


# 将 JS 对象字面量转为可 json.loads 的文本
def _js_to_json(js_text: str) -> str:
    converted = _convert_js_string_literals(js_text)
    converted = re.sub(r",(\s*[}\]])", r"\1", converted)
    result: list[str] = []
    i = 0
    n = len(converted)
    while i < n:
        ch = converted[i]
        if ch == '"':
            # 已是 JSON 字符串，整段原样保留
            result.append(ch)
            i += 1
            while i < n:
                c = converted[i]
                result.append(c)
                if c == "\\" and i + 1 < n:
                    result.append(converted[i + 1])
                    i += 2
                    continue
                i += 1
                if c == '"':
                    break
            continue
        # 为未加引号的对象键补双引号
        if ch in "{,":
            result.append(ch)
            i += 1
            while i < n and converted[i].isspace():
                result.append(converted[i])
                i += 1
            if i < n and re.match(r"[a-zA-Z_$]", converted[i]):
                start = i
                i += 1
                while i < n and re.match(r"[a-zA-Z0-9_$]", converted[i]):
                    i += 1
                key = converted[start:i]
                j = i
                while j < n and converted[j].isspace():
                    j += 1
                if j < n and converted[j] == ":":
                    result.append(f'"{key}"')
                    while i < j:
                        result.append(converted[i])
                        i += 1
                    continue
                result.append(key)
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _extract_js_obj(js_text: str, name: str) -> str | None:
    pattern = rf"(?:const\s+)?{re.escape(name)}\s*(?::|=)\s*([\[{{])"
    match = re.search(pattern, js_text)
    if not match:
        return None
    start = match.start(1)
    end = _find_matching_bracket(js_text, start)
    return js_text[start : end + 1]


# 从 lean.js 中定位同时含 movie 与 classicLines 的详情对象（变量名不固定）
def _find_detail_payload(js_text: str) -> dict[str, Any] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for match in re.finditer(r"(?:const\s+)?([A-Za-z_$][\w$]*)\s*(?::|=)\s*(\{)", js_text):
        name = match.group(1)
        if len(name) > 3:
            continue
        start = match.start(2)
        end = _find_matching_bracket(js_text, start)
        raw = js_text[start : end + 1]
        try:
            data = json.loads(_js_to_json(raw))
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if "movie" in data and "classicLines" in data:
            candidates.append((len(raw), data))
    if not candidates:
        return None
    # 取体积最大的匹配，避免误命中残缺对象
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _apply_mark_tags(sentence: str, keywords: list[str]) -> str:
    if not keywords:
        return sentence
    result = sentence
    for keyword in sorted(keywords, key=len, reverse=True):
        if not keyword.strip():
            continue
        escaped = re.escape(keyword)
        result = re.sub(
            f"(?<!<mark>)({escaped})(?!</mark>)",
            r"<mark>\1</mark>",
            result,
            flags=re.IGNORECASE,
        )
    return result


# 校验导出记录必填字段，返回缺失项列表（空表示完整）
def collect_missing_fields(record: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    movie_id = record.get("id", record.get("classicLinesId"))
    if movie_id is None or movie_id == "":
        missing.append("classicLinesId")
    if not str(record.get("name") or "").strip():
        missing.append("name")
    if not str(record.get("cover") or "").strip():
        missing.append("cover")
    quote_count = record.get("quoteCount")
    if not isinstance(quote_count, int | float) or int(quote_count) <= 0:
        missing.append("quoteCount")
    if record.get("doubanRating") is None or record.get("doubanRating") == "":
        missing.append("doubanRating")

    detail = record.get("detail")
    if not isinstance(detail, dict):
        missing.extend([
            "detail.title",
            "detail.poster",
            "detail.releaseDate",
            "detail.country",
            "detail.language",
            "detail.classicLines",
            "detail.info.导演",
            "detail.info.编剧",
            "detail.info.主演",
            "detail.info.类型",
        ])
        return missing

    if not str(detail.get("title") or "").strip():
        missing.append("detail.title")
    if not str(detail.get("poster") or "").strip():
        missing.append("detail.poster")
    if not str(detail.get("releaseDate") or "").strip():
        missing.append("detail.releaseDate")
    if not str(detail.get("country") or "").strip():
        missing.append("detail.country")
    if not str(detail.get("language") or "").strip():
        missing.append("detail.language")

    info = detail.get("info")
    if not isinstance(info, dict):
        missing.extend(["detail.info.导演", "detail.info.编剧", "detail.info.主演", "detail.info.类型"])
    else:
        for label, _src in INFO_FIELD_MAP:
            if not str(info.get(label) or "").strip():
                missing.append(f"detail.info.{label}")

    classic_lines = detail.get("classicLines")
    if not isinstance(classic_lines, list) or not classic_lines:
        missing.append("detail.classicLines")
    else:
        for idx, line in enumerate(classic_lines):
            if not isinstance(line, dict):
                missing.append(f"classicLines[{idx}]")
                continue
            if not str(line.get("content") or "").strip():
                missing.append(f"classicLines[{idx}].content")
            if not str(line.get("zhTranslation") or "").strip():
                missing.append(f"classicLines[{idx}].zhTranslation")
    return missing


def _parse_detail_lean_js(js_text: str) -> dict[str, Any] | None:
    data = _find_detail_payload(js_text)
    if data is None:
        return None

    movie_raw = data.get("movie") or {}
    if not isinstance(movie_raw, dict):
        return None
    classic_lines_raw = data.get("classicLines") or []
    if not isinstance(classic_lines_raw, list):
        classic_lines_raw = []

    info: dict[str, str] = {}
    for label, key in INFO_FIELD_MAP:
        value = movie_raw.get(key)
        if value:
            info[label] = str(value)

    classic_lines: list[dict[str, Any]] = []
    for idx, cl in enumerate(classic_lines_raw, start=1):
        if not isinstance(cl, dict):
            continue
        sentence = cl.get("sentence", "") or ""
        zh_sentence = cl.get("zhSentence", "") or ""
        keywords = cl.get("keywords") or []
        if not isinstance(keywords, list):
            keywords = []
        source_lines = cl.get("lines") or []
        content = _apply_mark_tags(str(sentence), [str(k) for k in keywords])
        classic_lines.append({
            "index": idx,
            "content": content,
            "zhTranslation": str(zh_sentence),
            "keywords": list(keywords),
            "sourceLines": source_lines,
        })

    movie_id = movie_raw.get("id")
    movie_name = str(movie_raw.get("zhName") or "")
    cover = str(movie_raw.get("cover") or "")
    douban_star = movie_raw.get("doubanStar")
    quote_count = movie_raw.get("classicLineCount", len(classic_lines))
    try:
        quote_count = int(quote_count)
    except (TypeError, ValueError):
        quote_count = len(classic_lines)
    douban_rating_str = f"豆瓣 {douban_star}" if douban_star is not None and douban_star != "" else ""
    title_text = f"电影 {movie_name} 中的 {quote_count} 句经典对白" if movie_name else ""

    detail = {
        "classicLinesId": movie_id,
        "title": title_text,
        "poster": cover,
        "doubanRating": douban_rating_str,
        "releaseDate": str(movie_raw.get("releaseDate") or ""),
        "country": str(movie_raw.get("region") or ""),
        "language": str(movie_raw.get("lang") or ""),
        "info": info,
        "classicLines": classic_lines,
    }

    return {
        "id": movie_id,
        "name": movie_name,
        "cover": cover,
        "quoteCount": quote_count,
        "doubanRating": douban_star,
        "detail": detail,
    }


def _find_lean_js_url(html_text: str, movie_id: int) -> str | None:
    pattern = rf"/assets/lines_{movie_id}\.md\.[\w-]+\.lean\.js"
    match = re.search(pattern, html_text)
    if match:
        return f"{BASE_URL}{match.group()}"
    return None


# 从列表页 HTML 中定位 lines_index lean.js（含全部影片）
def _find_lines_index_js_url(html_text: str) -> str | None:
    match = re.search(r"/assets/lines_index\.md\.[\w-]+\.lean\.js", html_text)
    if match:
        return f"{BASE_URL}{match.group()}"
    return None


# 从 lines_index lean.js 解析全部电影元数据
def _parse_index_movies(js_text: str) -> list[dict[str, Any]]:
    ref = re.search(r"\{movies:(\w+)\}", js_text)
    if not ref:
        raise ClassicLinesAutomationError("索引脚本中未找到 movies 数据引用")
    raw = _extract_js_obj(js_text, ref.group(1))
    if not raw:
        raise ClassicLinesAutomationError("索引脚本中未找到 movies 数组")
    try:
        movies = json.loads(_js_to_json(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ClassicLinesAutomationError(f"解析电影索引失败: {exc}") from exc
    if not isinstance(movies, list):
        raise ClassicLinesAutomationError("电影索引格式异常")
    result: list[dict[str, Any]] = []
    for item in movies:
        if not isinstance(item, dict):
            continue
        movie_id = item.get("id")
        if movie_id is None:
            continue
        result.append({
            "id": int(movie_id),
            "zhName": str(item.get("zhName") or ""),
            "cover": str(item.get("cover") or ""),
            "doubanStar": item.get("doubanStar"),
            "classicLineCount": item.get("classicLineCount"),
        })
    return result


# 从 lines_index lean.js 解析全部电影 ID（站点为前端分页，HTTP ?page= 无效）
def _parse_index_movie_ids(js_text: str) -> list[int]:
    return [int(item["id"]) for item in _parse_index_movies(js_text)]


def _parse_listing_movies(html_text: str) -> list[dict[str, Any]]:
    from bs4 import BeautifulSoup
    movies: list[dict[str, Any]] = []
    soup = BeautifulSoup(html_text, "html.parser")
    for card in soup.select("a.line-movie-card"):
        href = card.get("href", "")
        match = re.search(r"/lines/(\d+)", href)
        if not match:
            continue
        movie_id = int(match.group(1))
        h2 = card.find("h2")
        name = h2.get_text(strip=True) if h2 else ""
        name = re.sub(r"经典台词$", "", name).strip()
        img = card.find("img")
        cover = img.get("src", "") if img else ""
        meta = card.select_one(".line-movie-meta")
        quote_count = 0
        douban_rating = 0.0
        if meta:
            for span in meta.find_all("span"):
                text = span.get_text(strip=True)
                cm = re.search(r"(\d+)\s*句", text)
                if cm:
                    quote_count = int(cm.group(1))
                rm = re.search(r"豆瓣\s*([\d.]+)", text)
                if rm:
                    douban_rating = float(rm.group(1))
        movies.append({
            "id": movie_id,
            "name": name,
            "cover": cover,
            "quoteCount": quote_count,
            "doubanRating": douban_rating,
        })
    return movies


def flatten_classic_lines_data(movies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for movie in movies:
        record = dict(movie)
        if "id" in record:
            record["classicLinesId"] = record.pop("id")
        detail = record.get("detail")
        if isinstance(detail, dict) and "id" in detail:
            detail["classicLinesId"] = detail.pop("id")
        result.append(record)
    return result


def write_classic_lines_export_files(
    records: list[dict[str, Any]],
    output_dir: Path,
    file_stamp: str,
    *,
    unicloud_import_format: bool = True,
    split_limit_bytes: int = UNICLOUD_IMPORT_SPLIT_BYTES,
) -> ClassicLinesExportResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    base_path = output_dir / f"classic-lines-{file_stamp}.json"

    if not unicloud_import_format:
        base_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        return ClassicLinesExportResult(paths=[base_path], export_format="json-array")

    if split_limit_bytes <= 0:
        raise ValueError("split_limit_bytes must be greater than 0")

    chunks: list[list[bytes]] = []
    current_chunk: list[bytes] = []
    current_size = 0
    oversized_records = 0

    for record in records:
        line_text = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        line = line_text.encode("utf-8")
        if len(line) > split_limit_bytes:
            oversized_records += 1
        if current_chunk and current_size + len(line) > split_limit_bytes:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append(line)
        current_size += len(line)

    if current_chunk or not records:
        chunks.append(current_chunk)

    if len(chunks) == 1:
        base_path.write_bytes(b"".join(chunks[0]))
        return ClassicLinesExportResult(
            paths=[base_path], export_format="unicloud-jsonl",
            split_limit_bytes=split_limit_bytes, oversized_records=oversized_records,
        )

    paths: list[Path] = []
    for index, chunk in enumerate(chunks, start=1):
        path = output_dir / f"classic-lines-{file_stamp}-{index}.json"
        path.write_bytes(b"".join(chunk))
        paths.append(path)

    return ClassicLinesExportResult(
        paths=paths, export_format="unicloud-jsonl",
        split_limit_bytes=split_limit_bytes, oversized_records=oversized_records,
    )


# 生成单部电影在分页日志中的展示名
def _display_movie_name(meta: dict[str, Any], record: dict[str, Any] | None, movie_id: int) -> str:
    if record and str(record.get("name") or "").strip():
        return str(record["name"]).strip()
    index_name = str(meta.get("zhName") or "").strip()
    if index_name:
        return index_name
    return f"id={movie_id}"


class ClassicLinesAutomationRunner:
    """经典台词爬虫运行器"""

    def __init__(
        self,
        options: ClassicLinesAutomationOptions,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepCallback = asyncio.sleep,
        log: LogCallback | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.options = options
        self.transport = transport
        self.sleep = sleep
        self.log = log or (lambda message: None)
        self.progress = progress or (lambda c, t, n: None)

    # 执行全量经典台词采集并导出文件
    async def run(self) -> ClassicLinesAutomationResult:
        self.options.automation_dir.mkdir(parents=True, exist_ok=True)
        started = self.options.now_provider()
        self.log("开始爬取经典台词")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        async with httpx.AsyncClient(
            transport=self.transport, timeout=30.0, headers=headers, follow_redirects=True
        ) as client:
            self.log("正在获取电影列表...")
            index_movies = await self._fetch_all_movies(client)
            total_movies = len(index_movies)
            self.log(f"共找到 {total_movies} 部电影")
            if total_movies == 0:
                raise ClassicLinesAutomationError("未获取到任何电影列表")

            page_size = max(1, self.options.page_size)
            total_pages = max(1, (total_movies + page_size - 1) // page_size)
            concurrency = max(1, self.options.concurrency)
            semaphore = asyncio.Semaphore(concurrency)
            outcomes: list[_MovieFetchOutcome | None] = [None] * total_movies
            done_flags = [False] * total_movies
            logged_pages: set[int] = set()
            lock = asyncio.Lock()
            completed_count = 0

            # 并发抓取单部电影并在整页完成后写分页日志
            async def worker(index: int, meta: dict[str, Any]) -> None:
                nonlocal completed_count
                async with semaphore:
                    outcome = await self._fetch_movie_detail(client, index, meta)
                    if self.options.request_delay_seconds > 0:
                        await self.sleep(self.options.request_delay_seconds)
                async with lock:
                    outcomes[index] = outcome
                    done_flags[index] = True
                    completed_count += 1
                    self.progress(completed_count, total_movies, outcome.display_name)
                    page_index = index // page_size
                    start = page_index * page_size
                    end = min(start + page_size, total_movies)
                    if page_index not in logged_pages and all(done_flags[start:end]):
                        logged_pages.add(page_index)
                        page_outcomes = [outcomes[i] for i in range(start, end)]
                        self._log_page(page_index, total_pages, page_outcomes)

            await asyncio.gather(*[
                worker(index, meta) for index, meta in enumerate(index_movies)
            ])

            success_records: list[dict[str, Any]] = []
            failed_count = 0
            total_lines = 0
            for outcome in outcomes:
                if outcome is None:
                    failed_count += 1
                    continue
                if outcome.ok and outcome.record is not None:
                    success_records.append(outcome.record)
                    total_lines += int(outcome.record.get("quoteCount") or 0)
                else:
                    failed_count += 1

            self.log("正在写入导出文件...")
            flattened = flatten_classic_lines_data(success_records)
            stamp = started.strftime("%Y%m%d-%H%M%S")
            export_result = write_classic_lines_export_files(
                flattened, self.options.automation_dir, stamp,
                unicloud_import_format=self.options.unicloud_import_format,
                split_limit_bytes=self.options.split_limit_bytes,
            )
            finished = self.options.now_provider()
            self.log(
                f"采集完成：成功 {len(success_records)} 部，失败 {failed_count} 部，"
                f"台词 {total_lines} 句，输出 {len(export_result.paths)} 个文件"
            )
            for path in export_result.paths:
                self.log(f"输出文件：{path}")
            return ClassicLinesAutomationResult(
                output_path=export_result.paths[0],
                output_paths=export_result.paths,
                total_movies=len(success_records),
                failed_movies=failed_count,
                total_lines=total_lines,
                page_count=total_pages,
                started_at=started.isoformat(),
                finished_at=finished.isoformat(),
                export_format=export_result.export_format,
                split_limit_bytes=export_result.split_limit_bytes,
                oversized_records=export_result.oversized_records,
            )

    # 按页输出成功/失败明细日志
    def _log_page(
        self,
        page_index: int,
        total_pages: int,
        page_outcomes: list[_MovieFetchOutcome | None],
    ) -> None:
        count = len(page_outcomes)
        self.log(f"===== 第 {page_index + 1}/{total_pages} 页（本页 {count} 部）=====")
        for offset, outcome in enumerate(page_outcomes, start=1):
            if outcome is None:
                self.log(f"[失败] {offset}. 未知 | 缺失: 采集结果缺失")
                continue
            if outcome.ok:
                self.log(f"[成功] {offset}. {outcome.display_name}")
            else:
                missing_text = ", ".join(outcome.missing) if outcome.missing else "未知原因"
                self.log(f"[失败] {offset}. {outcome.display_name} | 缺失: {missing_text}")

    # 抓取索引中的全部电影元数据
    async def _fetch_all_movies(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        try:
            resp = await client.get(LINES_LIST_URL)
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            raise ClassicLinesAutomationError(f"获取经典台词列表页失败: {exc}") from exc

        index_url = _find_lines_index_js_url(html)
        if not index_url:
            raise ClassicLinesAutomationError("列表页未找到 lines_index 脚本")

        try:
            js_resp = await client.get(index_url)
            js_resp.raise_for_status()
            movies = _parse_index_movies(js_resp.text)
        except ClassicLinesAutomationError:
            raise
        except Exception as exc:
            raise ClassicLinesAutomationError(f"下载或解析电影索引失败: {exc}") from exc

        if self.options.max_pages:
            limit = self.options.max_pages * self.options.page_size
            movies = movies[:limit]
        total_pages = max(1, (len(movies) + self.options.page_size - 1) // self.options.page_size)
        self.log(f"索引共 {len(movies)} 部电影（约 {total_pages} 页）")
        return movies

    # 抓取单部电影详情并做完整字段校验
    async def _fetch_movie_detail(
        self,
        client: httpx.AsyncClient,
        index: int,
        meta: dict[str, Any],
    ) -> _MovieFetchOutcome:
        movie_id = int(meta["id"])
        display_name = _display_movie_name(meta, None, movie_id)
        url = f"{BASE_URL}/lines/{movie_id}"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
        except Exception:
            return _MovieFetchOutcome(
                index=index,
                movie_id=movie_id,
                display_name=display_name,
                record=None,
                missing=["详情页请求失败"],
            )

        lean_url = _find_lean_js_url(html, movie_id)
        if not lean_url:
            return _MovieFetchOutcome(
                index=index,
                movie_id=movie_id,
                display_name=display_name,
                record=None,
                missing=["lean.js脚本"],
            )

        try:
            js_resp = await client.get(lean_url)
            js_resp.raise_for_status()
            js_text = js_resp.text
        except Exception:
            return _MovieFetchOutcome(
                index=index,
                movie_id=movie_id,
                display_name=display_name,
                record=None,
                missing=["lean.js下载失败"],
            )

        result = _parse_detail_lean_js(js_text)
        if not result:
            return _MovieFetchOutcome(
                index=index,
                movie_id=movie_id,
                display_name=display_name,
                record=None,
                missing=["详情解析失败"],
            )

        # 请求 ID 写回，避免脚本缺 id 时 classicLinesId 为空
        if result.get("id") is None:
            result["id"] = movie_id
        detail = result.get("detail")
        if isinstance(detail, dict) and detail.get("classicLinesId") is None:
            detail["classicLinesId"] = movie_id
        if not str(result.get("name") or "").strip() and meta.get("zhName"):
            result["name"] = str(meta["zhName"])
            if isinstance(detail, dict) and result["name"]:
                quote_count = result.get("quoteCount") or 0
                detail["title"] = f"电影 {result['name']} 中的 {quote_count} 句经典对白"

        display_name = _display_movie_name(meta, result, movie_id)
        missing = collect_missing_fields(result)
        if missing:
            return _MovieFetchOutcome(
                index=index,
                movie_id=movie_id,
                display_name=display_name,
                record=None,
                missing=missing,
            )
        return _MovieFetchOutcome(
            index=index,
            movie_id=movie_id,
            display_name=display_name,
            record=result,
            missing=[],
        )
