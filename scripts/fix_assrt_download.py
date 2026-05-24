"""Fix ASSRT download with retry and better error messages."""

def main():
    with open(r'src\subtitle_info_collection\adapters\assrt.py', 'r', encoding='utf-8') as f:
        content = f.read()

    old = '''    async def download(self, candidate: SubtitleCandidate, context: DownloadContext) -> list[DownloadedPayload]:
        if not self.token:
            raise CollectorError("缺少 ASSRT_TOKEN", ErrorType.PROVIDER_DISABLED, self.id)
        detail = await self._request_json(
            "/sub/detail",
            {"id": candidate.provider_subtitle_id},
            log=context.log,
            stage="assrt.download.detail",
        )
        subs = detail.get("sub", {}).get("subs") or []
        if not subs:
            raise CollectorError("ASSRT 明细接口没有返回字幕信息", ErrorType.DOWNLOAD_FAILED, self.id)
        sub_detail = subs[0]
        filelist = [item for item in (sub_detail.get("filelist") or []) if isinstance(item, dict)]
        download_url = ""
        file_name = sub_detail.get("filename") or sub_detail.get("title") or "subtitle"
        for item in filelist:
            if item.get("url") and detect_subtitle_format(item.get("f", "")) in {"ass", "srt"}:
                download_url = item["url"]
                file_name = item.get("f") or file_name
                break
        if not download_url:
            download_url = sub_detail.get("url") or ""
        if not download_url:
            raise CollectorError("ASSRT 明细接口没有返回下载链接", ErrorType.DOWNLOAD_FAILED, self.id)

        await self._rate_limit()
        async with self._client() as client:
            response = await client.get(
                urljoin(self.base_url, download_url),
                headers={
                    "Accept": "application/zip,application/octet-stream,text/plain,*/*",
                    "User-Agent": "subtitleInfoCollection/0.1",
                    "Referer": "https://assrt.net/",
                },
            )
            response.raise_for_status()
            return [
                DownloadedPayload(
                    file_name=file_name,
                    content=response.content,
                    source_url=str(response.url),
                    content_type=response.headers.get("content-type", ""),
                )
            ]'''

    new = '''    async def download(self, candidate: SubtitleCandidate, context: DownloadContext) -> list[DownloadedPayload]:
        if not self.token:
            raise CollectorError("缺少 ASSRT_TOKEN", ErrorType.PROVIDER_DISABLED, self.id)
        self._emit(
            "assrt.download.start",
            "ASSRT 开始下载字幕",
            log=context.log,
            subtitle_id=candidate.provider_subtitle_id,
            title=candidate.subtitle_title,
        )
        detail = await self._request_json(
            "/sub/detail",
            {"id": candidate.provider_subtitle_id},
            log=context.log,
            stage="assrt.download.detail",
        )
        subs = detail.get("sub", {}).get("subs") or []
        if not subs:
            raise CollectorError("ASSRT 明细接口没有返回字幕信息", ErrorType.DOWNLOAD_FAILED, self.id)
        sub_detail = subs[0]
        filelist = [item for item in (sub_detail.get("filelist") or []) if isinstance(item, dict)]
        download_url = ""
        file_name = sub_detail.get("filename") or sub_detail.get("title") or "subtitle"
        for item in filelist:
            if item.get("url") and detect_subtitle_format(item.get("f", "")) in {"ass", "srt"}:
                download_url = item["url"]
                file_name = item.get("f") or file_name
                break
        if not download_url:
            download_url = sub_detail.get("url") or ""
        if not download_url:
            raise CollectorError("ASSRT 明细接口没有返回下载链接", ErrorType.DOWNLOAD_FAILED, self.id)

        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                await self._rate_limit()
                async with self._client() as client:
                    full_url = urljoin(self.base_url, download_url)
                    response = await client.get(
                        full_url,
                        headers={
                            "Accept": "application/zip,application/octet-stream,text/plain,*/*",
                            "User-Agent": "subtitleInfoCollection/0.1",
                            "Referer": "https://assrt.net/",
                        },
                    )
                    if response.status_code in {429, 509}:
                        raise CollectorError(
                            f"HTTP {response.status_code}",
                            ErrorType.RATE_LIMITED,
                            self.id,
                        )
                    response.raise_for_status()
                    self._emit(
                        "assrt.download.success",
                        "ASSRT 字幕下载成功",
                        log=context.log,
                        subtitle_id=candidate.provider_subtitle_id,
                        size=str(len(response.content)),
                        file=file_name,
                    )
                    return [
                        DownloadedPayload(
                            file_name=file_name,
                            content=response.content,
                            source_url=str(response.url),
                            content_type=response.headers.get("content-type", ""),
                        )
                    ]
            except _TRANSIENT_HTTPX_ERRORS as exc:
                last_exc = exc
                error_text = str(exc) or repr(exc)
                if attempt >= 3:
                    self._emit(
                        "assrt.download.fail",
                        "ASSRT 下载文件网络异常，已停止重试",
                        log=context.log,
                        subtitle_id=candidate.provider_subtitle_id,
                        base_url=self.base_url,
                        endpoint=download_url,
                        attempt=str(attempt),
                        error_type=type(exc).__name__,
                        error=error_text,
                    )
                    raise CollectorError(
                        f"{type(exc).__name__}: {error_text}",
                        ErrorType.NETWORK_UNREACHABLE,
                        self.id,
                    ) from exc
                self._emit(
                    "assrt.download.retry",
                    "ASSRT 下载文件网络异常，准备重试",
                    log=context.log,
                    subtitle_id=candidate.provider_subtitle_id,
                    base_url=self.base_url,
                    endpoint=download_url,
                    attempt=str(attempt),
                    error_type=type(exc).__name__,
                    error=error_text,
                )
                await asyncio.sleep(0.2 * attempt)
            except httpx.HTTPError as exc:
                error_text = str(exc) or repr(exc)
                raise CollectorError(
                    f"{type(exc).__name__}: {error_text}",
                    ErrorType.NETWORK_UNREACHABLE,
                    self.id,
                ) from exc
        raise CollectorError(
            f"ASSRT 下载失败: {last_exc!r}",
            ErrorType.NETWORK_UNREACHABLE,
            self.id,
        )'''

    if old in content:
        content = content.replace(old, new)
        with open(r'src\subtitle_info_collection\adapters\assrt.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print('OK: ASSRT download fixed with retry and logging')
    else:
        print('NOT FOUND: old block not found')
        # Check partial match
        marker = 'async def download(self, candidate: SubtitleCandidate, context: DownloadContext)'
        idx = content.find(marker)
        if idx >= 0:
            print(f'Found download method at {idx}')
            print(repr(content[idx:idx+300]))

if __name__ == '__main__':
    main()
