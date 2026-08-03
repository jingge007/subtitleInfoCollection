from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ..config import read_env_values, upsert_env_values


DEFAULT_LOGIN_URL = "https://33tc.net"
DEFAULT_API_URL = "https://ssv-api.agilestudio.cn/api/recommend/subtitle-list"
DEFAULT_BAIDU_TRANSLATE_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"
TOKEN_CACHE_FILE = "todays-lines-token-cache.json"
UNICLOUD_IMPORT_SPLIT_BYTES = 45 * 1024 * 1024

TODAYS_LINES_USERNAME_ENV = "TODAYS_LINES_USERNAME"
TODAYS_LINES_PASSWORD_ENV = "TODAYS_LINES_PASSWORD"
TODAYS_LINES_TOKEN_ENV = "TODAYS_LINES_TOKEN"
TODAYS_LINES_TOKEN_TIME_ENV = "TODAYS_LINES_TOKEN_TIME"
BAIDU_TRANSLATE_APP_ID_ENV = "BAIDU_TRANSLATE_APP_ID"
BAIDU_TRANSLATE_SECRET_ENV = "BAIDU_TRANSLATE_SECRET"


class TodaysLinesAutomationError(RuntimeError):
    """Raised when the 33 lines automation flow cannot continue."""


@dataclass(frozen=True, slots=True)
class SignedRequest:
    params: dict[str, Any]
    signature: str
    timestamp_ms: int


@dataclass(frozen=True, slots=True)
class TodaysLineExportResult:
    paths: list[Path]
    export_format: str
    split_limit_bytes: int | None = None
    oversized_records: int = 0


@dataclass(frozen=True, slots=True)
class TodaysLineImportPayload:
    records: list[dict[str, Any]]
    skipped_records: list[dict[str, Any]]
    input_count: int
    completed_count: int
    local_duplicate_count: int
    translation_requested_count: int = 0
    translation_filled_count: int = 0
    translation_failure_count: int = 0


@dataclass(slots=True)
class TodaysLinesAutomationOptions:
    data_dir: Path
    page_size: int = 50
    request_delay_seconds: float = 1.0
    headless: bool = True
    login_timeout_seconds: int = 60
    login_url: str = DEFAULT_LOGIN_URL
    api_url: str = DEFAULT_API_URL
    baidu_translate_url: str = DEFAULT_BAIDU_TRANSLATE_URL
    env_path: Path | None = None
    unicloud_import_format: bool = True
    split_limit_bytes: int = UNICLOUD_IMPORT_SPLIT_BYTES
    now_provider: Callable[[], datetime] = field(default_factory=lambda: datetime.now)

    @property
    def automation_dir(self) -> Path:
        return self.data_dir / "automation"

    @property
    def token_cache_path(self) -> Path:
        return self.automation_dir / TOKEN_CACHE_FILE


@dataclass(frozen=True, slots=True)
class TodaysLinesAutomationResult:
    output_path: Path
    output_paths: list[Path]
    total_count: int
    page_count: int
    started_at: str
    finished_at: str
    export_format: str
    input_count: int
    skipped_count: int = 0
    split_limit_bytes: int | None = None
    oversized_records: int = 0
    translation_requested_count: int = 0
    translation_filled_count: int = 0
    translation_failure_count: int = 0


TokenProvider = Callable[[], str | Awaitable[str]]
TranslateProvider = Callable[[str], str | Awaitable[str]]
LogCallback = Callable[[str], None]
SleepCallback = Callable[[float], Awaitable[None]]
ProgressCallback = Callable[[int, int, str], None]


def generate_signed_params(
    params: dict[str, Any],
    timestamp_ms: int | None = None,
) -> SignedRequest:
    signed_params = dict(params)
    timestamp = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    signed_params["_ts"] = timestamp

    source = "".join(
        f"{key}={signed_params[key]},"
        for key in sorted(signed_params)
        if signed_params[key] is not None
    )
    signature = hashlib.md5(source.encode()).hexdigest()
    return SignedRequest(params=signed_params, signature=signature, timestamp_ms=timestamp)


def normalize_todays_line_text(value: Any = "") -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def get_todays_line_primary_key(record: dict[str, Any] | None = None) -> str:
    source = record or {}
    value = source.get("todaySLinesId", source.get("id"))
    if value is None or value == "":
        return ""
    return str(value).strip()


def get_todays_line_content_key(record: dict[str, Any] | None = None) -> str:
    source = record or {}
    movie_name = normalize_todays_line_text(source.get("movieName"))
    zh_content = normalize_todays_line_text(source.get("zhContent", source.get("description")))
    en_content = normalize_todays_line_text(source.get("enContent", source.get("originContent")))
    return "::".join([movie_name, zh_content, en_content]).lower()


def dedupe_todays_line_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    primary_keys: set[str] = set()
    content_keys: set[str] = set()
    unique_records: list[dict[str, Any]] = []
    skipped_records: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        primary_key = get_todays_line_primary_key(record)
        content_key = get_todays_line_content_key(record)
        has_content_key = bool(content_key.replace("::", ""))
        duplicated_by_primary_key = bool(primary_key and primary_key in primary_keys)
        duplicated_by_content = bool(has_content_key and content_key in content_keys)

        if duplicated_by_primary_key or duplicated_by_content:
            skipped_records.append(
                {
                    "record": record,
                    "index": index,
                    "reason": (
                        "duplicate todaySLinesId in current import"
                        if duplicated_by_primary_key
                        else "duplicate todays line content in current import"
                    ),
                }
            )
            continue

        if primary_key:
            primary_keys.add(primary_key)
        if has_content_key:
            content_keys.add(content_key)
        unique_records.append(record)

    return unique_records, skipped_records


def transform_todays_line_record(item: dict[str, Any] | None, index: int) -> dict[str, Any]:
    source = dict(item or {})
    description = source.pop("description", None)
    origin_content = source.pop("originContent", None)
    source_id = source.pop("id", None)
    source_subtitles_id = source.pop("subtitlesId", None)
    has_subtitle_object = isinstance(source.get("subtitle"), dict)
    subtitle = dict(source.get("subtitle")) if has_subtitle_object else {}
    subtitle_subtitles_id = subtitle.pop("subtitlesId", None)
    if has_subtitle_object:
        source["subtitle"] = subtitle
    subtitle_video = subtitle.get("video") if isinstance(subtitle.get("video"), dict) else {}
    generated_id = int(time.time() * 1000) + index
    record_id = _normalize_record_id(
        _first_present(
            source.get("movieId"),
            subtitle.get("movieId"),
            source_id,
            source.get("todaySLinesId"),
            source_subtitles_id,
            subtitle_subtitles_id,
            generated_id,
        ),
        generated_id,
    )

    result = dict(source)
    result.pop("subtitlesId", None)
    result["todaySLinesId"] = record_id
    result["zhContent"] = description if description is not None else source.get("zhContent", "")
    result["enContent"] = origin_content if origin_content is not None else source.get("enContent", "")
    result["movieName"] = (
        source.get("movieName")
        or subtitle_video.get("zhName")
        or subtitle_video.get("title")
        or ""
    )
    result["picUrl"] = source.get("picUrl") or subtitle_video.get("cover") or ""
    result["movieId"] = record_id
    return result


async def prepare_todays_line_import_payload(
    raw_list: list[dict[str, Any]],
    *,
    translate_text: TranslateProvider | None = None,
    log: LogCallback | None = None,
) -> TodaysLineImportPayload:
    transformed_records = [
        transform_todays_line_record(item, index)
        for index, item in enumerate(raw_list)
    ]
    completed_records, translation_stats = await fill_missing_english_content(
        transformed_records,
        translate_text=translate_text,
        log=log,
    )
    unique_records, skipped_records = dedupe_todays_line_records(completed_records)
    return TodaysLineImportPayload(
        records=unique_records,
        skipped_records=skipped_records,
        input_count=len(raw_list),
        completed_count=len(completed_records),
        local_duplicate_count=len(skipped_records),
        translation_requested_count=translation_stats["requested"],
        translation_filled_count=translation_stats["filled"],
        translation_failure_count=translation_stats["failed"],
    )


async def fill_missing_english_content(
    records: list[dict[str, Any]],
    *,
    translate_text: TranslateProvider | None,
    log: LogCallback | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if translate_text is None:
        return records, {"requested": 0, "filled": 0, "failed": 0}

    pending_texts: list[str] = []
    seen_texts: set[str] = set()
    for record in records:
        zh_content = normalize_todays_line_text(record.get("zhContent"))
        en_content = normalize_todays_line_text(record.get("enContent"))
        if zh_content and not en_content and zh_content not in seen_texts:
            seen_texts.add(zh_content)
            pending_texts.append(zh_content)

    translations: dict[str, str] = {}
    failed = 0
    for text in pending_texts:
        try:
            result = translate_text(text)
            translation = await result if inspect.isawaitable(result) else result
            normalized = normalize_todays_line_text(translation)
            if normalized:
                translations[text] = normalized
                continue
        except Exception as exc:  # noqa: BLE001
            if log:
                log(f"翻译失败，保留英文为空：{text[:30]} / {exc}")
        failed += 1

    completed = [
        {
            **record,
            "enContent": record.get("enContent") or translations.get(
                normalize_todays_line_text(record.get("zhContent")),
                "",
            ),
        }
        for record in records
    ]
    return completed, {
        "requested": len(pending_texts),
        "filled": len(translations),
        "failed": failed,
    }


def write_todays_line_export_files(
    records: list[dict[str, Any]],
    output_dir: Path,
    file_stamp: str,
    *,
    unicloud_import_format: bool = True,
    split_limit_bytes: int = UNICLOUD_IMPORT_SPLIT_BYTES,
) -> TodaysLineExportResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    base_path = output_dir / f"todays-lines-{file_stamp}.json"

    if not unicloud_import_format:
        base_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return TodaysLineExportResult(paths=[base_path], export_format="json-array")

    if split_limit_bytes <= 0:
        raise ValueError("split_limit_bytes must be greater than 0")

    chunks: list[list[bytes]] = []
    current_chunk: list[bytes] = []
    current_size = 0
    oversized_records = 0

    for record in records:
        line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
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
        return TodaysLineExportResult(
            paths=[base_path],
            export_format="unicloud-jsonl",
            split_limit_bytes=split_limit_bytes,
            oversized_records=oversized_records,
        )

    paths: list[Path] = []
    for index, chunk in enumerate(chunks, start=1):
        path = output_dir / f"todays-lines-{file_stamp}-{index}.json"
        path.write_bytes(b"".join(chunk))
        paths.append(path)

    return TodaysLineExportResult(
        paths=paths,
        export_format="unicloud-jsonl",
        split_limit_bytes=split_limit_bytes,
        oversized_records=oversized_records,
    )


class TodaysLinesAutomationRunner:
    def __init__(
        self,
        options: TodaysLinesAutomationOptions,
        *,
        token_provider: TokenProvider | None = None,
        translate_provider: TranslateProvider | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepCallback = asyncio.sleep,
        log: LogCallback | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.options = options
        self.token_provider = token_provider
        self.translate_provider = translate_provider
        self.transport = transport
        self.sleep = sleep
        self.log = log or (lambda message: None)
        self.progress = progress or (lambda current, total, tip: None)
        self._last_baidu_request_at = 0.0

    async def run(self) -> TodaysLinesAutomationResult:
        self.options.automation_dir.mkdir(parents=True, exist_ok=True)
        started = self.options.now_provider()
        self.log("启动 33 台词今日台词采集")

        async with httpx.AsyncClient(transport=self.transport, timeout=30.0) as client:
            token = await self._get_valid_token(client)
            items, page_count = await self._fetch_all_items(client, token)

            payload: TodaysLineImportPayload | None = None
            export_items = items
            if self.options.unicloud_import_format:
                self.log("按 todays-line / uniCloud 控制台导入格式处理数据")
                translate_text = self._resolve_translate_provider(client)
                payload = await prepare_todays_line_import_payload(
                    items,
                    translate_text=translate_text,
                    log=self.log,
                )
                export_items = payload.records

        file_stamp = started.strftime("%Y-%m-%d_%H-%M-%S")
        export_result = write_todays_line_export_files(
            export_items,
            self.options.automation_dir,
            file_stamp,
            unicloud_import_format=self.options.unicloud_import_format,
            split_limit_bytes=self.options.split_limit_bytes,
        )
        finished = self.options.now_provider()
        self._log_export_result(export_result, len(export_items), payload)
        return TodaysLinesAutomationResult(
            output_path=export_result.paths[0],
            output_paths=export_result.paths,
            total_count=len(export_items),
            page_count=page_count,
            started_at=started.isoformat(timespec="seconds"),
            finished_at=finished.isoformat(timespec="seconds"),
            export_format=export_result.export_format,
            input_count=len(items),
            skipped_count=payload.local_duplicate_count if payload else 0,
            split_limit_bytes=export_result.split_limit_bytes,
            oversized_records=export_result.oversized_records,
            translation_requested_count=payload.translation_requested_count if payload else 0,
            translation_filled_count=payload.translation_filled_count if payload else 0,
            translation_failure_count=payload.translation_failure_count if payload else 0,
        )

    async def _get_valid_token(self, client: httpx.AsyncClient) -> str:
        cached_token = self._read_cached_token()
        if cached_token:
            self.log("检测缓存 token")
            if await self._check_token_valid(client, cached_token):
                self.log("使用缓存 token")
                return cached_token
            self.log("缓存 token 已失效")

        token = await self._request_new_token()
        self._write_cached_token(token)
        return token

    def _read_cached_token(self) -> str:
        env_values = self._read_env_values()
        token = str(env_values.get(TODAYS_LINES_TOKEN_ENV) or "").strip()
        if token:
            return token

        legacy_payload = self._read_legacy_token_cache()
        legacy_token = str(legacy_payload.get("token") or "").strip()
        if legacy_token:
            self.log("检测到旧 token 缓存，迁移到 .env")
            self._write_cached_token(legacy_token, legacy_payload.get("time"))
            return legacy_token
        return ""

    def _write_cached_token(self, token: str, token_time: Any | None = None) -> None:
        token = str(token or "").strip()
        if not token:
            return
        timestamp = str(token_time or int(time.time() * 1000))
        values = {
            TODAYS_LINES_TOKEN_ENV: token,
            TODAYS_LINES_TOKEN_TIME_ENV: timestamp,
        }
        upsert_env_values(self.options.env_path, values)
        os.environ.update(values)

    async def _request_new_token(self) -> str:
        if self.token_provider:
            result = self.token_provider()
            token = await result if inspect.isawaitable(result) else result
        else:
            token = await self._get_token_by_playwright()

        token = str(token or "").strip()
        if not token:
            raise TodaysLinesAutomationError("未获取到 33 台词登录 token")
        return token

    async def _get_token_by_playwright(self) -> str:
        env_values = self._read_env_values()
        username = str(env_values.get(TODAYS_LINES_USERNAME_ENV) or "").strip()
        password = str(env_values.get(TODAYS_LINES_PASSWORD_ENV) or "").strip()
        if not username or not password:
            raise TodaysLinesAutomationError(
                "缺少 TODAYS_LINES_USERNAME 或 TODAYS_LINES_PASSWORD，无法自动登录 33 台词"
            )

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise TodaysLinesAutomationError("缺少 Playwright，无法自动登录 33 台词") from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.options.headless)
            try:
                page = await browser.new_page()
                await page.goto(self.options.login_url, wait_until="networkidle")
                username_selectors = [
                    "input[name='username']",
                    "input[name='account']",
                    "input[name='phone']",
                    "input[name='mobile']",
                    "input[placeholder*='账号']",
                    "input[placeholder*='手机']",
                    "input[placeholder*='用户名']",
                    "input[type='text']",
                ]
                try:
                    await self._fill_first_visible(page, username_selectors, username)
                except TodaysLinesAutomationError:
                    await self._click_first_visible(
                        page,
                        [
                            "button:has-text('登录')",
                            "button:has-text('登陆')",
                            "a:has-text('登录')",
                            "a:has-text('登陆')",
                            "text=登录",
                            "text=登陆",
                        ],
                    )
                    await page.wait_for_timeout(500)
                    await self._fill_first_visible(page, username_selectors, username)
                await self._fill_first_visible(
                    page,
                    [
                        "input[name='password']",
                        "input[placeholder*='密码']",
                        "input[type='password']",
                    ],
                    password,
                )
                await self._click_first_visible(
                    page,
                    [
                        "button[type='submit']",
                        "button:has-text('登录')",
                        "button:has-text('登陆')",
                        "text=登录",
                        "text=登陆",
                    ],
                )
                await page.wait_for_function(
                    "() => document.cookie.includes('web_user_token')",
                    timeout=self.options.login_timeout_seconds * 1000,
                )
                cookies = await page.context.cookies()
                token = next(
                    (
                        cookie["value"]
                        for cookie in cookies
                        if cookie.get("name") == "web_user_token"
                    ),
                    "",
                )
                if not token:
                    raise TodaysLinesAutomationError("登录完成后仍未找到 web_user_token")
                return token
            finally:
                await browser.close()

    async def _check_token_valid(self, client: httpx.AsyncClient, token: str) -> bool:
        try:
            data = await self._request_page(client, token, page=1, limit=1)
        except Exception:  # noqa: BLE001
            return False
        return int(data.get("code", -1)) == 0

    async def _fetch_all_items(self, client: httpx.AsyncClient, token: str) -> tuple[list[dict[str, Any]], int]:
        items: list[dict[str, Any]] = []
        page = 1
        page_count = 0
        total = 0

        while True:
            self.log(f"请求第 {page} 页")
            payload = await self._request_page(client, token, page=page, limit=self.options.page_size)
            if int(payload.get("code", -1)) != 0:
                message = payload.get("msg") or "33 台词接口返回错误"
                raise TodaysLinesAutomationError(str(message))

            data = payload.get("data") or {}
            page_items = list(data.get("list") or [])
            total = int(data.get("total") or total or len(items) + len(page_items))
            if not page_items:
                break

            items.extend(page_items)
            page_count += 1
            self.log(f"第 {page} 页获取 {len(page_items)} 条，累计 {len(items)}/{total}")
            self.progress(len(items), total or len(items), f"第 {page} 页")

            if total and len(items) >= total:
                break

            page += 1
            if self.options.request_delay_seconds > 0:
                await self.sleep(self.options.request_delay_seconds)

        return items, page_count

    async def _request_page(
        self,
        client: httpx.AsyncClient,
        token: str,
        *,
        page: int,
        limit: int,
    ) -> dict[str, Any]:
        signed = generate_signed_params(
            {
                "page": page,
                "limit": limit,
                "_platform": "web",
                "_versioin": "0.2.5",
            }
        )
        response = await client.get(
            self.options.api_url,
            params=signed.params,
            headers={
                "x-token": token,
                "x-signature": signed.signature,
            },
        )
        response.raise_for_status()
        return dict(response.json())

    # 有外部注入或百度凭据时启用英译；未配置则跳过
    def _resolve_translate_provider(
        self,
        client: httpx.AsyncClient,
    ) -> TranslateProvider | None:
        if self.translate_provider is not None:
            return self.translate_provider
        env_values = self._read_env_values()
        if not self._has_baidu_translate_credentials(env_values):
            self.log("未配置百度翻译，跳过英文补全")
            return None
        return lambda text: self._translate_chinese_to_english(client, text, env_values)

    # 判断百度翻译 App ID 与 Secret 是否均已配置
    @staticmethod
    def _has_baidu_translate_credentials(env_values: dict[str, str]) -> bool:
        return bool(
            str(env_values.get(BAIDU_TRANSLATE_APP_ID_ENV) or "").strip()
            and str(env_values.get(BAIDU_TRANSLATE_SECRET_ENV) or "").strip()
        )

    # 仅通过百度翻译将中文台词补全为英文
    async def _translate_chinese_to_english(
        self,
        client: httpx.AsyncClient,
        text: str,
        env_values: dict[str, str] | None = None,
    ) -> str:
        values = env_values if env_values is not None else self._read_env_values()
        if not self._has_baidu_translate_credentials(values):
            raise TodaysLinesAutomationError("未配置百度翻译凭据")
        return await self._translate_by_baidu(client, text, values)

    # 调用百度通用翻译 API（含 QPS 间隔与错误码透出）
    async def _translate_by_baidu(
        self,
        client: httpx.AsyncClient,
        text: str,
        env_values: dict[str, str],
    ) -> str:
        now = asyncio.get_running_loop().time()
        elapsed = now - self._last_baidu_request_at
        if self._last_baidu_request_at and elapsed < 1.2:
            await self.sleep(1.2 - elapsed)
        self._last_baidu_request_at = asyncio.get_running_loop().time()

        app_id = str(env_values.get(BAIDU_TRANSLATE_APP_ID_ENV) or "")
        secret = str(env_values.get(BAIDU_TRANSLATE_SECRET_ENV) or "")
        salt = f"{int(time.time() * 1000)}"
        sign = hashlib.md5(f"{app_id}{text}{salt}{secret}".encode("utf-8")).hexdigest()
        response = await client.get(
            self.options.baidu_translate_url,
            params={
                "q": text,
                "from": "zh",
                "to": "en",
                "appid": app_id,
                "salt": salt,
                "sign": sign,
            },
        )
        response.raise_for_status()
        data = response.json()
        error_code = data.get("error_code")
        if error_code:
            error_msg = data.get("error_msg") or "百度翻译接口返回错误"
            raise TodaysLinesAutomationError(f"百度翻译失败[{error_code}]：{error_msg}")
        results = data.get("trans_result") or []
        return "".join(str(item.get("dst") or "") for item in results).strip()

    def _read_env_values(self) -> dict[str, str]:
        # 已指定 env_path 时以文件为准，避免进程内其它测试/加载污染 os.environ
        if self.options.env_path is not None:
            return read_env_values(self.options.env_path)
        values: dict[str, str] = {}
        for key in [
            TODAYS_LINES_USERNAME_ENV,
            TODAYS_LINES_PASSWORD_ENV,
            TODAYS_LINES_TOKEN_ENV,
            TODAYS_LINES_TOKEN_TIME_ENV,
            BAIDU_TRANSLATE_APP_ID_ENV,
            BAIDU_TRANSLATE_SECRET_ENV,
        ]:
            if key in os.environ:
                values[key] = os.environ[key]
        return values

    def _read_legacy_token_cache(self) -> dict[str, Any]:
        path = self.options.token_cache_path
        if not path.exists():
            return {}
        try:
            return dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return {}

    async def _fill_first_visible(self, page: Any, selectors: list[str], value: str) -> None:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    await locator.fill(value)
                    return
            except Exception:  # noqa: BLE001
                continue
        raise TodaysLinesAutomationError("自动登录失败：未找到可填写的登录输入框")

    async def _click_first_visible(self, page: Any, selectors: list[str]) -> None:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    await locator.click()
                    return
            except Exception:  # noqa: BLE001
                continue
        raise TodaysLinesAutomationError("自动登录失败：未找到登录按钮")

    def _log_export_result(
        self,
        export_result: TodaysLineExportResult,
        count: int,
        payload: TodaysLineImportPayload | None,
    ) -> None:
        if payload:
            self.log(
                "todays-line 处理完成："
                f"输入 {payload.input_count} 条，导出 {count} 条，"
                f"本地去重 {payload.local_duplicate_count} 条"
            )
            if payload.translation_requested_count:
                self.log(
                    "英文补全："
                    f"请求 {payload.translation_requested_count} 条，"
                    f"成功 {payload.translation_filled_count} 条，"
                    f"失败 {payload.translation_failure_count} 条"
                )
        if len(export_result.paths) > 1:
            self.log(f"已按 45MB 拆分保存 {count} 条数据：")
            for path in export_result.paths:
                self.log(f"- {path}")
        else:
            self.log(f"已保存 {count} 条数据：{export_result.paths[0]}")


def _to_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    try:
        text = str(value).strip()
        if not text:
            return None
        number = float(text)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _normalize_record_id(value: Any, fallback: int) -> int | float | str:
    number = _to_number(value)
    if number is not None:
        return number
    text = str(value).strip() if value is not None else ""
    return text or fallback

