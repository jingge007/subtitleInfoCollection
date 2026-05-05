from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


DEFAULT_LOGIN_URL = "https://33tc.net"
DEFAULT_API_URL = "https://ssv-api.agilestudio.cn/api/recommend/subtitle-list"
TOKEN_CACHE_FILE = "classic-lines-token-cache.json"


class ClassicLinesAutomationError(RuntimeError):
    """Raised when the 33台词 automation flow cannot continue."""


@dataclass(frozen=True, slots=True)
class SignedRequest:
    params: dict[str, Any]
    signature: str
    timestamp_ms: int


@dataclass(slots=True)
class ClassicLinesAutomationOptions:
    data_dir: Path
    page_size: int = 50
    request_delay_seconds: float = 1.0
    headless: bool = False
    login_timeout_seconds: int = 60
    login_url: str = DEFAULT_LOGIN_URL
    api_url: str = DEFAULT_API_URL
    now_provider: Callable[[], datetime] = field(default_factory=lambda: datetime.now)

    @property
    def automation_dir(self) -> Path:
        return self.data_dir / "automation"

    @property
    def token_cache_path(self) -> Path:
        return self.automation_dir / TOKEN_CACHE_FILE


@dataclass(frozen=True, slots=True)
class ClassicLinesAutomationResult:
    output_path: Path
    token_cache_path: Path
    total_count: int
    page_count: int
    started_at: str
    finished_at: str


TokenProvider = Callable[[], str | Awaitable[str]]
LogCallback = Callable[[str], None]
SleepCallback = Callable[[float], Awaitable[None]]


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


class ClassicLinesAutomationRunner:
    def __init__(
        self,
        options: ClassicLinesAutomationOptions,
        *,
        token_provider: TokenProvider | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepCallback = asyncio.sleep,
        log: LogCallback | None = None,
    ) -> None:
        self.options = options
        self.token_provider = token_provider
        self.transport = transport
        self.sleep = sleep
        self.log = log or (lambda message: None)

    async def run(self) -> ClassicLinesAutomationResult:
        self.options.automation_dir.mkdir(parents=True, exist_ok=True)
        started = self.options.now_provider()
        self.log("启动 33 台词今日台词采集")

        async with httpx.AsyncClient(transport=self.transport, timeout=30.0) as client:
            token = await self._get_valid_token(client)
            items, page_count = await self._fetch_all_items(client, token)

        output_path = self._build_output_path(started)
        output_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        finished = self.options.now_provider()
        self.log(f"已保存 {len(items)} 条数据：{output_path}")
        return ClassicLinesAutomationResult(
            output_path=output_path,
            token_cache_path=self.options.token_cache_path,
            total_count=len(items),
            page_count=page_count,
            started_at=started.isoformat(timespec="seconds"),
            finished_at=finished.isoformat(timespec="seconds"),
        )

    def _build_output_path(self, stamp: datetime) -> Path:
        file_stamp = stamp.strftime("%Y-%m-%d_%H-%M-%S")
        return self.options.automation_dir / f"classic-lines-{file_stamp}.json"

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
        path = self.options.token_cache_path
        if not path.exists():
            return ""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return str(payload.get("token") or "").strip()

    def _write_cached_token(self, token: str) -> None:
        self.options.token_cache_path.write_text(
            json.dumps({"token": token, "time": int(time.time() * 1000)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def _request_new_token(self) -> str:
        if self.token_provider:
            result = self.token_provider()
            token = await result if inspect.isawaitable(result) else result
        else:
            token = await self._get_token_by_playwright()

        token = str(token or "").strip()
        if not token:
            raise ClassicLinesAutomationError("未获取到 33 台词登录 token")
        return token

    async def _get_token_by_playwright(self) -> str:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise ClassicLinesAutomationError("缺少 Playwright，无法打开 33 台词登录页") from exc

        browser = None
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.options.headless)
            try:
                page = await browser.new_page()
                await page.goto(self.options.login_url, wait_until="networkidle")
                self.log("请在打开的浏览器中完成 33 台词登录")
                await page.wait_for_function(
                    "() => document.cookie.includes('web_user_token')",
                    timeout=self.options.login_timeout_seconds * 1000,
                )
                cookies = await page.context.cookies()
                token = next(
                    (cookie["value"] for cookie in cookies if cookie.get("name") == "web_user_token"),
                    "",
                )
                if not token:
                    raise ClassicLinesAutomationError("登录完成后仍未找到 web_user_token")
                return token
            finally:
                if browser:
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
                raise ClassicLinesAutomationError(str(message))

            data = payload.get("data") or {}
            page_items = list(data.get("list") or [])
            total = int(data.get("total") or total or len(items) + len(page_items))
            if not page_items:
                break

            items.extend(page_items)
            page_count += 1
            self.log(f"第 {page} 页获取 {len(page_items)} 条，累计 {len(items)}/{total}")

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
