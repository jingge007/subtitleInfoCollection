"""Apply ALL subhd.py changes in one pass."""
import re

with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    c = f.read()

changes = 0

# === 1. subhd_mode=True ===
old = "ocr_result = solve_captcha_data_uri(image_data_uri)"
new = "ocr_result = solve_captcha_data_uri(image_data_uri, subhd_mode=True)"
if old in c:
    c = c.replace(old, new)
    changes += 1

# === 2. Set _active_log at download start ===
# Find download method start
dl_start = c.find("async def download(self, candidate: SubtitleCandidate, context: DownloadContext)")
if dl_start > 0:
    # Find first real statement line
    first_stmt = c.find("\n        ", c.find(":\n", dl_start) + 2)
    if first_stmt > 0:
        insert = "\n        self._active_log = context.log"
        # Insert after the docstring/early returns but before main logic
        # Find the "detail_url" line
        du_idx = c.find("detail_url = candidate.detail_url", dl_start)
        if du_idx > 0:
            line_start = c.rfind("\n", 0, du_idx)
            c = c[:line_start] + "\n        self._active_log = context.log" + c[line_start:]
            changes += 1

# === 3. Fix captcha block with OCR auto-retry + _emit ===
old_block = '''            if data.get("success") and data.get("pass") is False:
                captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                if captcha_code == _CAPTCHA_REFRESH:
                    captcha_code = ""
                    continue
                if not captcha_code:
                    return None
                logger.info("SubHD captcha submit: %s (attempt %d)", captcha_code, attempt + 1)
                continue'''

new_block = '''            if data.get("success") and data.get("pass") is False:
                # OCR auto-retry
                if getattr(self, "_ocr_auto_submitted", False):
                    self._ocr_auto_submitted = False
                    self._emit("subhd.captcha.auto_retry", "SubHD OCR auto-submit failed, auto-refreshing", log=context.log, subtitle_id=candidate.provider_subtitle_id)
                    captcha_code = _CAPTCHA_REFRESH
                else:
                    captcha_code = await self._handle_captcha(client, base_url, candidate, context, data)
                if captcha_code == _CAPTCHA_REFRESH:
                    self._emit("subhd.captcha.refresh", "SubHD captcha refresh requested", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1))
                    captcha_code = ""
                    self._ocr_auto_submitted = False
                    continue
                if not captcha_code:
                    self._emit("subhd.captcha.empty_cancel", "SubHD captcha cancelled or empty", log=context.log, subtitle_id=candidate.provider_subtitle_id)
                    return None
                masked = captcha_code[0] + "*" * (len(captcha_code) - 1) if len(captcha_code) > 1 else captcha_code
                self._emit("subhd.captcha.api_submit", "SubHD captcha submitted to API", log=context.log, subtitle_id=candidate.provider_subtitle_id, code_masked=masked, attempt=str(attempt + 1))
                continue'''

if old_block in c:
    c = c.replace(old_block, new_block)
    changes += 1
    print("Replaced captcha handling block")
else:
    print("Captcha block not found - searching...")
    # Search for alternative pattern
    idx = c.find("data.get(\"success\") and data.get(\"pass\") is False")
    if idx > 0:
        print(f"Found at {idx}: {repr(c[idx:idx+200])}")

# === 4. Set _ocr_auto_submitted in auto-submit path ===
old = "return suggested_code"
new = "self._ocr_auto_submitted = True\n            return suggested_code"
if old in c and "self._ocr_auto_submitted = True" not in c:
    # Only replace the one in _handle_captcha (after auto_submit emit)
    as_idx = c.find("subhd.captcha.auto_submit")
    if as_idx > 0:
        ret_idx = c.find("return suggested_code", as_idx)
        if 0 < ret_idx - as_idx < 1000:
            c = c[:ret_idx] + "self._ocr_auto_submitted = True\n            " + c[ret_idx:]
            changes += 1

# === 5. Convert key logger.info in download/captcha path to self._emit ===
conv_map = {
    'logger.info("SubHD download start, id=%s, title=%s, bases=%s",': 'self._emit("subhd.download.start", "SubHD download started", log=context.log, subtitle_id=candidate.provider_subtitle_id, title=candidate.subtitle_title, bases=str(base_urls_ordered))',
}
# Single-line conversions
for old_pat, new_pat in conv_map.items():
    if old_pat in c:
        # Find the full logger.info call (may span multiple lines)
        start = c.find(old_pat)
        # Find matching closing paren
        depth = 1
        end = start + len(old_pat)
        for i in range(end, len(c)):
            if c[i] == '(':
                depth += 1
            elif c[i] == ')':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        old_full = c[start:end]
        if old_full.count('\n') <= 3:  # Only convert simple calls
            c = c[:start] + new_pat + c[end:]
            changes += 1

with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.write(c)

print(f"Applied {changes} changes")