with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    c = f.read()

# Find the captcha handling block (original logger.info form)
old = '''                captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
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

new = '''                # OCR auto-retry
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

if old in c:
    c = c.replace(old, new)
    print("Added OCR auto-retry")
else:
    # Try original pattern (without _emit)
    old2 = '''                captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                if captcha_code == _CAPTCHA_REFRESH:
                    captcha_code = ""
                    continue
                if not captcha_code:
                    return None
                masked = captcha_code[0] + "*" * (len(captcha_code) - 1) if len(captcha_code) > 1 else captcha_code
                logger.info("SubHD captcha submit: %s (attempt %d)", captcha_code, attempt + 1)
                continue'''
    if old2 in c:
        c = c.replace(old2, new)
        print("Added OCR auto-retry (original pattern)")
    else:
        print("Auto-retry block not found in either form")

with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.write(c)
print("Done")