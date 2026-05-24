with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    c = f.read()

# Get the exact old block text
idx = c.find('data.get("success") and data.get("pass") is False')
end = c.find("\n\n            ", idx + 50)
if end < 0:
    end = c.find("\n            return None", idx + 100)
old_block = c[idx:end]

new_block = '''data.get("success") and data.get("pass") is False:
                # OCR auto-retry: if last auto-submit failed, refresh once before re-prompting
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
                self._emit("subhd.captcha.api_submit", "SubHD captcha submitted", log=context.log, subtitle_id=candidate.provider_subtitle_id, code_masked=masked, attempt=str(attempt + 1))
                continue'''

c = c.replace(old_block, new_block)
with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.write(c)
print("Replaced captcha block")