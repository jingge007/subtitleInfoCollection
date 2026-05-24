import re

with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the captcha.required section and handle_captcha call
idx = content.find("captcha.required")
hc_idx = content.find("captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)", idx)
if idx < 0 or hc_idx < 0:
    print(f"NOT FOUND: idx={idx}, hc_idx={hc_idx}")
    exit()

# Get line bounds
line_start = content.rfind("\n", 0, idx) + 1
line_end = content.find("\n", hc_idx) + 1
old_block = content[line_start:line_end]

new_block = '''                self._emit("subhd.captcha.required", "SubHD ...", log=context.log, attempt=str(attempt + 1))
                # OCR auto-retry
                if getattr(self, "_ocr_auto_submitted", False):
                    self._ocr_auto_submitted = False
                    self._emit("subhd.captcha.auto_retry", "SubHD OCR auto-submit failed, auto-refreshing", log=context.log, subtitle_id=candidate.provider_subtitle_id)
                    captcha_code = _CAPTCHA_REFRESH
                else:
                    captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                if captcha_code == _CAPTCHA_REFRESH:
                    self._ocr_auto_submitted = False
'''

content = content[:line_start] + new_block + content[line_end:]

# Set auto_submit flag
as_idx = content.find("subhd.captcha.auto_submit")
if as_idx > 0:
    ret_idx = content.find("return suggested_code", as_idx)
    if 0 < ret_idx - as_idx < 1000:
        content = content.replace("return suggested_code", "self._ocr_auto_submitted = True\n            return suggested_code", 1)
        print("Set _ocr_auto_submitted=True")

with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.write(content)
print("OK")
