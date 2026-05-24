import re

with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    content = f.read()

count = 0

# --- Convert logger.info to self._emit in download/captcha path ---
# download warmup
if re.search(r'logger\.info\("SubHD /down/ warmup failed: %s", exc\)', content):
    content = re.sub(r'logger\.info\("SubHD /down/ warmup failed: %s", exc\)',
        r'self._emit("subhd.download.warmup_fail", "SubHD /down/ warmup failed", log=context.log, error=repr(exc))', content)
    count += 1

# download invalid content (multi-line)
if 'subhd.download.invalid_content' in content:
    old = '''logger.info(
                        "subhd.download.invalid_content subtitle_id=%s size=%d",
                        candidate.provider_subtitle_id,
                        len(content) if content else 0,
                    )'''
    new = '''self._emit("subhd.download.invalid_content", "SubHD invalid content", log=context.log, subtitle_id=candidate.provider_subtitle_id, size=str(len(content) if content else 0))'''
    if old in content:
        content = content.replace(old, new)
        count += 1

# download.api.attempt
if 'subhd.download.api.attempt' in content and 'logger.info' in content:
    old = '''logger.info("subhd.download.api.attempt subtitle_id=%s base=%s attempt=%d has_captcha=%s exc=%s", candidate.provider_subtitle_id, base_url, attempt + 1, bool(captcha_code), exc)'''
    new = '''self._emit("subhd.download.api.attempt", "SubHD API attempt", log=context.log, subtitle_id=candidate.provider_subtitle_id, base_url=base_url, attempt=str(attempt + 1), has_captcha=str(bool(captcha_code)), error=repr(exc))'''
    if old in content:
        content = content.replace(old, new)
        count += 1

# download.api.captcha_required
old = '''logger.info("subhd.download.api.captcha_required subtitle_id=%s attempt=%d", candidate.provider_subtitle_id, attempt + 1)'''
new = '''self._emit("subhd.download.api.captcha_required", "SubHD captcha required", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1))'''
if old in content:
    content = content.replace(old, new)
    count += 1

# capture refresh
old = '''logger.info("subhd.captcha.refresh subtitle_id=%s attempt=%d", candidate.provider_subtitle_id, attempt + 1)'''
new = '''self._emit("subhd.captcha.refresh", "SubHD captcha refresh", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1))'''
if old in content:
    content = content.replace(old, new)
    count += 1

# captcha empty_cancel
old = '''logger.info("subhd.captcha.empty_cancel subtitle_id=%s", candidate.provider_subtitle_id)'''
new = '''self._emit("subhd.captcha.empty_cancel", "SubHD captcha cancelled", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''
if old in content:
    content = content.replace(old, new)
    count += 1

# captcha api_submit
old = '''logger.info("subhd.captcha.api_submit subtitle_id=%s code=%s attempt=%d", candidate.provider_subtitle_id, masked, attempt + 1)'''
new = '''self._emit("subhd.captcha.api_submit", "SubHD captcha submit", log=context.log, subtitle_id=candidate.provider_subtitle_id, code_masked=masked, attempt=str(attempt + 1))'''
if old in content:
    content = content.replace(old, new)
    count += 1

# verify_success + got_url
old = '''logger.info("subhd.captcha.verify_success subtitle_id=%s", candidate.provider_subtitle_id)'''
new = '''self._emit("subhd.captcha.verify_success", "SubHD captcha verified", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.download.api.got_url subtitle_id=%s dl_url=%s", candidate.provider_subtitle_id, dl_url)'''
new = '''self._emit("subhd.download.api.got_url", "SubHD got download URL", log=context.log, subtitle_id=candidate.provider_subtitle_id, dl_url=dl_url)'''
if old in content:
    content = content.replace(old, new)
    count += 1

# file_fetch_fail
old = '''logger.info("subhd.download.file_fetch_fail subtitle_id=%s exc=%s", candidate.provider_subtitle_id, exc)'''
new = '''self._emit("subhd.download.file_fetch_fail", "SubHD file fetch failed", log=context.log, subtitle_id=candidate.provider_subtitle_id, error=repr(exc))'''
if old in content:
    content = content.replace(old, new)
    count += 1

# all_failed
old = '''logger.info("subhd.download.all_failed subtitle_id=%s", candidate.provider_subtitle_id)'''
new = '''self._emit("subhd.download.all_failed", "SubHD all download attempts failed", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''
if old in content:
    content = content.replace(old, new)
    count += 1

# --- download captcha Chinese text ---
old = '''logger.info("SubHD ...", attempt + 1)'''
new = '''self._emit("subhd.captcha.required", "SubHD captcha needed", log=context.log, attempt=str(attempt + 1))'''
if old not in content:
    # try actual text
    old2 = '''logger.info("SubHD \u9700\u8981\u8f93\u5165\u9a8c\u8bc1\u7801 (\u7b2c %d \u6b21\u5c1d\u8bd5)", attempt + 1)'''
    new2 = '''self._emit("subhd.captcha.required", "SubHD captcha needed", log=context.log, attempt=str(attempt + 1))'''
    if old2 in content:
        content = content.replace(old2, new2)
        count += 1
else:
    content = content.replace(old, new)
    count += 1

# unexpected response
old = '''logger.info("SubHD api/sub/down unexpected response: %s", str(data)[:200])'''
new = '''self._emit("subhd.download.api.unexpected", "SubHD unexpected API response", log=context.log, response=str(data)[:200])'''
if old in content:
    content = content.replace(old, new)
    count += 1

# --- Captcha flow in _handle_captcha ---
old = '''logger.info("subhd.captcha.ocr.start subtitle_id=%s", candidate.provider_subtitle_id)'''
new = '''self._emit("subhd.captcha.ocr.start", "SubHD OCR start", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.ocr.fail subtitle_id=%s reason=%s", candidate.provider_subtitle_id, ocr_message)'''
new = '''self._emit("subhd.captcha.ocr.fail", "SubHD OCR fail", log=context.log, subtitle_id=candidate.provider_subtitle_id, reason=ocr_message)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.ocr.exception subtitle_id=%s exc=%s", candidate.provider_subtitle_id, exc)'''
new = '''self._emit("subhd.captcha.ocr.exception", "SubHD OCR exception", log=context.log, subtitle_id=candidate.provider_subtitle_id, error=repr(exc))'''
if old in content:
    content = content.replace(old, new)
    count += 1

# wait_user
old = '''logger.info("subhd.captcha.wait_user subtitle_id=%s reason=ocr_no_result", candidate.provider_subtitle_id)'''
new = '''self._emit("subhd.captcha.wait_user", "SubHD wait user, OCR no result", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.wait_user subtitle_id=%s reason=ocr_disabled", candidate.provider_subtitle_id)'''
new = '''self._emit("subhd.captcha.wait_user", "SubHD wait user, OCR disabled", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.no_callback subtitle_id=%s", candidate.provider_subtitle_id)'''
new = '''self._emit("subhd.captcha.no_callback", "SubHD no callback", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.user_input subtitle_id=%s code=%s", candidate.provider_subtitle_id, user_code)'''
new = '''self._emit("subhd.captcha.user_input", "SubHD user input", log=context.log, subtitle_id=candidate.provider_subtitle_id, code=user_code)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.user_cancel subtitle_id=%s", candidate.provider_subtitle_id)'''
new = '''self._emit("subhd.captcha.user_cancel", "SubHD user cancelled", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''
if old in content:
    content = content.replace(old, new)
    count += 1

# --- OCR result multi-line ---
old = '''logger.info(
                        "subhd.captcha.ocr.result subtitle_id=%s code=%s confidence=%.0f%%",
                        candidate.provider_subtitle_id, suggested_code, suggested_confidence * 100,
                    )'''
new = '''self._emit("subhd.captcha.ocr.result", "SubHD OCR result", log=context.log, subtitle_id=candidate.provider_subtitle_id, code=suggested_code, confidence=f"{suggested_confidence * 100:.0f}%")'''
if old in content:
    content = content.replace(old, new)
    count += 1

# auto_submit
old = '''logger.info("subhd.captcha.auto_submit subtitle_id=%s code=%s confidence=%.0f%% threshold=%.0f%%", candidate.provider_subtitle_id, suggested_code, suggested_confidence * 100, context.captcha_auto_submit_min_confidence * 100)'''
new = '''self._emit("subhd.captcha.auto_submit", "SubHD OCR auto-submit", log=context.log, subtitle_id=candidate.provider_subtitle_id, code=suggested_code, confidence=f"{suggested_confidence * 100:.0f}%", threshold=f"{context.captcha_auto_submit_min_confidence * 100:.0f}%")'''
if old in content:
    content = content.replace(old, new)
    count += 1

# verify_fail
old = '''logger.info("subhd.captcha.verify_fail subtitle_id=%s attempt=%d msg=%s", candidate.provider_subtitle_id, attempt + 1, server_msg[:100])'''
new = '''self._emit("subhd.captcha.verify_fail", "SubHD captcha verify fail", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1), msg=server_msg[:100])'''
if old in content:
    content = content.replace(old, new)
    count += 1

# api.fail
old = '''logger.info("subhd.download.api.fail subtitle_id=%s attempt=%d msg=%s", candidate.provider_subtitle_id, attempt + 1, server_msg[:100])'''
new = '''self._emit("subhd.download.api.fail", "SubHD API fail", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1), msg=server_msg[:100])'''
if old in content:
    content = content.replace(old, new)
    count += 1

# api.success multi-line
old = '''logger.info(
                        "subhd.download.api.success subtitle_id=%s size=%d file=%s",
                        candidate.provider_subtitle_id, len(content), file_name,
                    )'''
new = '''self._emit("subhd.download.api.success", "SubHD download success", log=context.log, subtitle_id=candidate.provider_subtitle_id, size=str(len(content)), file=file_name)'''
if old in content:
    content = content.replace(old, new)
    count += 1

# --- Image fetch helpers ---
old = '''logger.info("subhd.captcha.image_fetch source=down_page_httpx status=fail status_code=%d", resp.status_code)'''
new = '''self._emit("subhd.captcha.image_fetch", "SubHD captcha image fetch fail", log=context.log, status_code=str(resp.status_code))'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.image_fetch source=down_page_httpx status=cloudflare")'''
new = '''self._emit("subhd.captcha.image_fetch", "SubHD captcha image Cloudflare", log=context.log)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.image_fetch source=down_page_httpx status=found_html")'''
new = '''self._emit("subhd.captcha.image_fetch", "SubHD captcha image found", log=context.log)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.image_fetch source=down_page_httpx status=no_captcha")'''
new = '''self._emit("subhd.captcha.image_fetch", "SubHD captcha image not found", log=context.log)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.image_fetch source=down_page_httpx status=exception exc=%s", exc)'''
new = '''self._emit("subhd.captcha.image_fetch", "SubHD captcha image exception", log=context.log, error=repr(exc))'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.image_fetch fallback=playwright")'''
new = '''self._emit("subhd.captcha.image_fetch", "SubHD captcha image fallback to Playwright", log=context.log)'''
if old in content:
    content = content.replace(old, new)
    count += 1

# --- Playwright captcha fetch ---
old = '''logger.info("subhd.captcha.playwright.error reason=browser_unavailable")'''
new = '''self._emit("subhd.captcha.playwright.error", "SubHD Playwright unavailable", log=context.log)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.playwright.screenshot selector=%s size=%d", selector, len(screenshot_bytes))'''
new = '''self._emit("subhd.captcha.playwright.screenshot", "SubHD Playwright screenshot", log=context.log, selector=selector, size=str(len(screenshot_bytes)))'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.playwright.no_captcha")'''
new = '''self._emit("subhd.captcha.playwright.no_captcha", "SubHD Playwright no captcha", log=context.log)'''
if old in content:
    content = content.replace(old, new)
    count += 1

old = '''logger.info("subhd.captcha.playwright.error exc=%s", exc)'''
new = '''self._emit("subhd.captcha.playwright.error", "SubHD Playwright error", log=context.log, error=repr(exc))'''
if old in content:
    content = content.replace(old, new)
    count += 1

print(f"Converted {count} logger.info calls")

# --- Add subhd_mode=True ---
old = 'ocr_result = solve_captcha_data_uri(image_data_uri)'
new = 'ocr_result = solve_captcha_data_uri(image_data_uri, subhd_mode=True)'
if old in content:
    content = content.replace(old, new)
    print("Added subhd_mode=True")

# --- Add OCR auto-retry ---
# Find the captcha handling block in download
old_block = '''                captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                if captcha_code == _CAPTCHA_REFRESH:
                    self._emit("subhd.captcha.refresh", "SubHD captcha refresh", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1))
                    captcha_code = ""
                    continue
                if not captcha_code:
                    self._emit("subhd.captcha.empty_cancel", "SubHD captcha cancelled", log=context.log, subtitle_id=candidate.provider_subtitle_id)
                    return None
                masked = captcha_code[0] + "*" * (len(captcha_code) - 1) if len(captcha_code) > 1 else captcha_code
                self._emit("subhd.captcha.api_submit", "SubHD captcha submit", log=context.log, subtitle_id=candidate.provider_subtitle_id, code_masked=masked, attempt=str(attempt + 1))
                continue'''

new_block = '''                # OCR auto-retry: if last was auto-submit and API still returns captcha, auto-refresh once
                if getattr(self, "_ocr_auto_submitted", False):
                    self._ocr_auto_submitted = False
                    self._emit("subhd.captcha.auto_retry", "SubHD OCR auto-submit failed, auto-refreshing", log=context.log, subtitle_id=candidate.provider_subtitle_id)
                    captcha_code = _CAPTCHA_REFRESH
                else:
                    captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                if captcha_code == _CAPTCHA_REFRESH:
                    self._emit("subhd.captcha.refresh", "SubHD captcha refresh", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1))
                    captcha_code = ""
                    self._ocr_auto_submitted = False
                    continue
                if not captcha_code:
                    self._emit("subhd.captcha.empty_cancel", "SubHD captcha cancelled", log=context.log, subtitle_id=candidate.provider_subtitle_id)
                    return None
                masked = captcha_code[0] + "*" * (len(captcha_code) - 1) if len(captcha_code) > 1 else captcha_code
                self._emit("subhd.captcha.api_submit", "SubHD captcha submit", log=context.log, subtitle_id=candidate.provider_subtitle_id, code_masked=masked, attempt=str(attempt + 1))
                continue'''

if old_block in content:
    content = content.replace(old_block, new_block)
    print("Added OCR auto-retry in download loop")
else:
    print("OCR auto-retry block not found")

# Set _ocr_auto_submitted = True when auto-submit happens
content = content.replace(
    'return suggested_code',
    'self._ocr_auto_submitted = True\n            return suggested_code'
)
print("Set _ocr_auto_submitted flag")

with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Done - all subhd.py changes applied")