"""Add OCR auto-retry in subhd.py download method."""
import re

def main():
    with open(r'src\subtitle_info_collection\adapters\subhd.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the captcha handling block in the download method
    # Key marker: the "subhd.captcha.required" emit call
    marker = 'self._emit("subhd.captcha.required"'
    idx = content.find(marker)
    if idx < 0:
        print('NOT FOUND: captcha.required marker')
        return

    # Find the block from captcha.required to the end of the captcha handling
    # We want to add OCR auto-retry before calling _handle_captcha

    # Find the _handle_captcha call
    handle_idx = content.find('captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)', idx)
    if handle_idx < 0:
        print('NOT FOUND: _handle_captcha call')
        return

    # The block before _handle_captcha: the captcha.required emit + _handle_captcha call
    # We need to replace from: captcha.required emit ... to ... continue (the captcha handling block)

    # Let me be more surgical: insert OCR auto-retry just before calling _handle_captcha
    # Strategy: find the exact line after captcha.required emit and before _handle_captcha

    # Let me find the exact block
    search_start = max(0, idx - 50)
    search_end = min(len(content), handle_idx + 100)
    block = content[search_start:search_end]

    print(f'Found captcha block at idx {idx}, handle_idx {handle_idx}')

    # The captcha_code line
    captcha_line = 'captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)'

    # Replace: after captcha.required emit, before _handle_captcha, add auto-retry
    # Actually, the auto-retry should happen BEFORE _handle_captcha when the previous attempt was an OCR auto-submit
    # But _handle_captcha already handles the auto-submit internally.
    # The retry should happen when _handle_captcha auto-submitted and the result still failed.
    # Since the download loop continues after captcha_code is returned, the NEXT iteration
    # will call _handle_captcha again. So _handle_captcha should detect it's a retry.

    # Simpler approach: modify _handle_captcha to accept a flag, and the download loop passes it.
    # Actually simplest: track whether we auto-submitted last time, and if so, auto-refresh before calling _handle_captcha again.

    # Let me add a tracking variable in the download method
    # Find the beginning of the download method
    download_start = content.find('async def download(self, candidate: SubtitleCandidate, context: DownloadContext)')
    if download_start < 0:
        print('NOT FOUND: download method')
        return

    # Find the API attempt loop
    attempt_start = content.find('for attempt in range(', download_start)
    if attempt_start < 0:
        print('NOT FOUND: attempt loop')

    # Simpler approach: add ocr_auto_retried flag tracking to the download loop
    # Find the captcha handling and add retry logic

    # The block to replace
    old_block = '''                self._emit("subhd.captcha.required", "SubHD 需要输入验证码", log=context.log, attempt=str(attempt + 1))
                captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)'''

    new_block = '''                self._emit("subhd.captcha.required", "SubHD 需要输入验证码", log=context.log, attempt=str(attempt + 1))
                # OCR 自动重试：如果上次是自动提交且 API 仍返回验证码，先自动刷新+重新识别一次
                if getattr(self, "_ocr_auto_submitted", False):
                    self._ocr_auto_submitted = False
                    self._emit("subhd.captcha.auto_retry", "SubHD OCR自动提交失败，自动刷新重试", log=context.log, subtitle_id=candidate.provider_subtitle_id)
                    captcha_code = _CAPTCHA_REFRESH
                else:
                    captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                # 跟踪OCR自动提交状态
                if captcha_code and captcha_code != _CAPTCHA_REFRESH and getattr(self, "_ocr_auto_submitted", False):
                    pass  # already tracked
                elif captcha_code == _CAPTCHA_REFRESH:
                    self._ocr_auto_submitted = False'''

    if old_block in content:
        content = content.replace(old_block, new_block, 1)
        print('OK: Added OCR auto-retry logic')

        # Also need to set _ocr_auto_submitted = True in _handle_captcha when auto-submit happens
        # Find the auto_submit emit in _handle_captcha
        auto_submit_marker = 'self._emit("subhd.captcha.auto_submit"'
        as_idx = content.find(auto_submit_marker)
        if as_idx > 0:
            # Find the return suggested_code line after auto_submit
            return_line = content.find('return suggested_code', as_idx)
            if return_line > 0 and return_line - as_idx < 500:
                # Insert flag before return
                old_return = 'return suggested_code'
                new_return = 'self._ocr_auto_submitted = True\n            return suggested_code'
                content = content.replace(old_return, new_return, 1)
                print('OK: Set _ocr_auto_submitted=True in auto-submit path')

        with open(r'src\subtitle_info_collection\adapters\subhd.py', 'w', encoding='utf-8') as f:
            f.write(content)
    else:
        print('NOT FOUND: captcha.required block')
        # Show what's around the marker
        ctx = content[idx-20:idx+200]
        print(f'Context: {repr(ctx[:100])}')

if __name__ == '__main__':
    main()
