with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    c = f.read()

# Get exact full block
full_start = 31595
end_idx = 32284
old_block = c[full_start:end_idx]

# Verify by checking for key markers
if "captcha_code = await self._handle_captcha" not in old_block:
    print("Block verification failed")
    exit()

new_block = '''            if data.get("success") and data.get("pass") is False:
                self._emit("subhd.captcha.required", "SubHD captcha needed", log=context.log, attempt=str(attempt + 1))
                # OCR auto-retry: if last was auto-submit and API still returns captcha, auto-refresh once
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

c = c[:full_start] + new_block + c[end_idx:]

with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.write(c)
print("Applied OCR auto-retry + _emit conversion for captcha block")