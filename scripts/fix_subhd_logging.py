"""Convert logger.info to self._emit in subhd.py download/captcha path for GUI logging."""

import re

def main():
    with open(r'src\subtitle_info_collection\adapters\subhd.py', 'r', encoding='utf-8') as f:
        content = f.read()

    replacements = [
        # --- download method ---
        # warmup
        (r'''logger\.info\("SubHD /down/ warmup failed: %s", exc\)''',
         r'''self._emit("subhd.download.warmup_fail", "SubHD /down/ 预热失败", log=context.log, error=repr(exc))'''),

        # download.api.attempt
        (r'''logger\.info\("subhd\.download\.api\.attempt subtitle_id=%s base=%s attempt=%d has_captcha=%s exc=%s", candidate\.provider_subtitle_id, base_url, attempt \+ 1, bool\(captcha_code\), exc\)''',
         r'''self._emit("subhd.download.api.attempt", "SubHD 下载API尝试", log=context.log, subtitle_id=candidate.provider_subtitle_id, base_url=base_url, attempt=str(attempt + 1), has_captcha=str(bool(captcha_code)), error=repr(exc))'''),

        # captcha_required
        (r'''logger\.info\("subhd\.download\.api\.captcha_required subtitle_id=%s attempt=%d", candidate\.provider_subtitle_id, attempt \+ 1\)''',
         r'''self._emit("subhd.download.api.captcha_required", "SubHD 下载需要验证码", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1))'''),

        # got_url
        (r'''logger\.info\("subhd\.download\.api\.got_url subtitle_id=%s dl_url=%s", candidate\.provider_subtitle_id, dl_url\)''',
         r'''self._emit("subhd.download.api.got_url", "SubHD 获取下载链接成功", log=context.log, subtitle_id=candidate.provider_subtitle_id, dl_url=dl_url)'''),

        # file_fetch_fail
        (r'''logger\.info\("subhd\.download\.file_fetch_fail subtitle_id=%s exc=%s", candidate\.provider_subtitle_id, exc\)''',
         r'''self._emit("subhd.download.file_fetch_fail", "SubHD 下载文件获取失败", log=context.log, subtitle_id=candidate.provider_subtitle_id, error=repr(exc))'''),

        # download success fields
        (r'''logger\.info\(\n\s+"subhd\.download\.api\.success subtitle_id=%s size=%d file=%s",\n\s+candidate\.provider_subtitle_id, len\(content\), file_name\)''',
         r'''self._emit("subhd.download.api.success", "SubHD 下载成功", log=context.log, subtitle_id=candidate.provider_subtitle_id, size=str(len(content)), file=file_name)'''),

        # api.fail
        (r'''logger\.info\("subhd\.download\.api\.fail subtitle_id=%s attempt=%d msg=%s", candidate\.provider_subtitle_id, attempt \+ 1, server_msg\[:100\]\)''',
         r'''self._emit("subhd.download.api.fail", "SubHD 下载API请求失败", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1), msg=server_msg[:100])'''),

        # all_failed
        (r'''logger\.info\("subhd\.download\.all_failed subtitle_id=%s", candidate\.provider_subtitle_id\)''',
         r'''self._emit("subhd.download.all_failed", "SubHD 所有下载尝试均失败", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''),

        # verify_fail
        (r'''logger\.info\("subhd\.captcha\.verify_fail subtitle_id=%s attempt=%d msg=%s", candidate\.provider_subtitle_id, attempt \+ 1, server_msg\[:100\]\)''',
         r'''self._emit("subhd.captcha.verify_fail", "SubHD 验证码校验失败", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1), msg=server_msg[:100])'''),

        # captcha refresh during download
        (r'''logger\.info\("subhd\.captcha\.refresh subtitle_id=%s attempt=%d", candidate\.provider_subtitle_id, attempt \+ 1\)''',
         r'''self._emit("subhd.captcha.refresh", "SubHD 刷新验证码", log=context.log, subtitle_id=candidate.provider_subtitle_id, attempt=str(attempt + 1))'''),

        # captcha empty_cancel
        (r'''logger\.info\("subhd\.captcha\.empty_cancel subtitle_id=%s", candidate\.provider_subtitle_id\)''',
         r'''self._emit("subhd.captcha.empty_cancel", "SubHD 验证码取消/为空", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''),

        # captcha api_submit
        (r'''logger\.info\("subhd\.captcha\.api_submit subtitle_id=%s code=%s attempt=%d", candidate\.provider_subtitle_id, masked, attempt \+ 1\)''',
         r'''self._emit("subhd.captcha.api_submit", "SubHD 提交验证码到API", log=context.log, subtitle_id=candidate.provider_subtitle_id, code_masked=masked, attempt=str(attempt + 1))'''),

        # verify_success (before got_url)
        (r'''logger\.info\("subhd\.captcha\.verify_success subtitle_id=%s", candidate\.provider_subtitle_id\)''',
         r'''self._emit("subhd.captcha.verify_success", "SubHD 验证码校验成功", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''),

        # --- _handle_captcha method ---
        # ocr.start (context.log available via context parameter)
        (r'''logger\.info\("subhd\.captcha\.ocr\.start subtitle_id=%s", candidate\.provider_subtitle_id\)''',
         r'''self._emit("subhd.captcha.ocr.start", "SubHD 开始OCR识别", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''),

        # ocr.result (multi-line)
        (r'''logger\.info\(\n\s+"subhd\.captcha\.ocr\.result subtitle_id=%s code=%s confidence=%.0f%%",\n\s+candidate\.provider_subtitle_id, suggested_code, suggested_confidence \* 100,\n\s+\)''',
         r'''self._emit("subhd.captcha.ocr.result", "SubHD OCR识别结果", log=context.log, subtitle_id=candidate.provider_subtitle_id, code=suggested_code, confidence=f"{suggested_confidence * 100:.0f}%")'''),

        # ocr.fail
        (r'''logger\.info\("subhd\.captcha\.ocr\.fail subtitle_id=%s reason=%s", candidate\.provider_subtitle_id, ocr_message\)''',
         r'''self._emit("subhd.captcha.ocr.fail", "SubHD OCR识别失败", log=context.log, subtitle_id=candidate.provider_subtitle_id, reason=ocr_message)'''),

        # ocr.exception
        (r'''logger\.info\("subhd\.captcha\.ocr\.exception subtitle_id=%s exc=%s", candidate\.provider_subtitle_id, exc\)''',
         r'''self._emit("subhd.captcha.ocr.exception", "SubHD OCR异常", log=context.log, subtitle_id=candidate.provider_subtitle_id, error=repr(exc))'''),

        # auto_submit
        (r'''logger\.info\("subhd\.captcha\.auto_submit subtitle_id=%s code=%s confidence=%.0f%% threshold=%.0f%%", candidate\.provider_subtitle_id, suggested_code, suggested_confidence \* 100, context\.captcha_auto_submit_min_confidence \* 100\)''',
         r'''self._emit("subhd.captcha.auto_submit", "SubHD OCR自动提交验证码", log=context.log, subtitle_id=candidate.provider_subtitle_id, code=suggested_code, confidence=f"{suggested_confidence * 100:.0f}%", threshold=f"{context.captcha_auto_submit_min_confidence * 100:.0f}%")'''),

        # wait_user
        (r'''logger\.info\("subhd\.captcha\.wait_user subtitle_id=%s reason=ocr_no_result", candidate\.provider_subtitle_id\)''',
         r'''self._emit("subhd.captcha.wait_user", "SubHD 等待用户输入验证码(OCR无结果)", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''),

        (r'''logger\.info\("subhd\.captcha\.wait_user subtitle_id=%s reason=ocr_disabled", candidate\.provider_subtitle_id\)''',
         r'''self._emit("subhd.captcha.wait_user", "SubHD 等待用户输入验证码(OCR已禁用)", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''),

        # no_callback
        (r'''logger\.info\("subhd\.captcha\.no_callback subtitle_id=%s", candidate\.provider_subtitle_id\)''',
         r'''self._emit("subhd.captcha.no_callback", "SubHD 无验证码回调", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''),

        # user_input
        (r'''logger\.info\("subhd\.captcha\.user_input subtitle_id=%s code=%s", candidate\.provider_subtitle_id, user_code\)''',
         r'''self._emit("subhd.captcha.user_input", "SubHD 用户输入验证码", log=context.log, subtitle_id=candidate.provider_subtitle_id, code=user_code)'''),

        # user_cancel
        (r'''logger\.info\("subhd\.captcha\.user_cancel subtitle_id=%s", candidate\.provider_subtitle_id\)''',
         r'''self._emit("subhd.captcha.user_cancel", "SubHD 用户取消验证码", log=context.log, subtitle_id=candidate.provider_subtitle_id)'''),

        # --- captcha fetch helpers ---
        # image_fetch: fail status_code
        (r'''logger\.info\("subhd\.captcha\.image_fetch source=down_page_httpx status=fail status_code=%d", resp\.status_code\)''',
         r'''self._emit("subhd.captcha.image_fetch", "SubHD 验证码图片获取(httpx)失败", log=context.log, status_code=str(resp.status_code))'''),

        # image_fetch: cloudflare
        (r'''logger\.info\("subhd\.captcha\.image_fetch source=down_page_httpx status=cloudflare"\)''',
         r'''self._emit("subhd.captcha.image_fetch", "SubHD 验证码图片获取(httpx)遇到Cloudflare", log=context.log)'''),

        # image_fetch: found_html
        (r'''logger\.info\("subhd\.captcha\.image_fetch source=down_page_httpx status=found_html"\)''',
         r'''self._emit("subhd.captcha.image_fetch", "SubHD 验证码图片获取(httpx)找到HTML", log=context.log)'''),

        # image_fetch: no_captcha
        (r'''logger\.info\("subhd\.captcha\.image_fetch source=down_page_httpx status=no_captcha"\)''',
         r'''self._emit("subhd.captcha.image_fetch", "SubHD 验证码图片获取(httpx)未找到验证码", log=context.log)'''),

        # image_fetch: exception
        (r'''logger\.info\("subhd\.captcha\.image_fetch source=down_page_httpx status=exception exc=%s", exc\)''',
         r'''self._emit("subhd.captcha.image_fetch", "SubHD 验证码图片获取(httpx)异常", log=context.log, error=repr(exc))'''),

        # image_fetch: fallback
        (r'''logger\.info\("subhd\.captcha\.image_fetch fallback=playwright"\)''',
         r'''self._emit("subhd.captcha.image_fetch", "SubHD 验证码图片获取回退到Playwright", log=context.log)'''),
    ]

    count = 0
    for pattern, replacement in replacements:
        new_content = re.sub(pattern, replacement, content)
        if new_content != content:
            count += 1
            content = new_content

    # Handle remaining misc logger.info in download area that have simpler patterns
    # "SubHD 需要输入验证码" -> chinese text from download method
    content = re.sub(
        r'logger\.info\("SubHD 需要输入验证码 \(第 %d 次尝试\)", attempt \+ 1\)',
        r'self._emit("subhd.captcha.required", "SubHD 需要输入验证码", log=context.log, attempt=str(attempt + 1))',
        content
    )
    content = re.sub(
        r'logger\.info\("SubHD api/sub/down unexpected response: %s", str\(data\)\[:200\]\)',
        r'self._emit("subhd.download.api.unexpected", "SubHD 下载API意外响应", log=context.log, response=str(data)[:200])',
        content
    )
    content = re.sub(
        r'logger\.info\("subhd\.download\.api\.success subtitle_id=%s size=%d file=%s", candidate\.provider_subtitle_id, len\(content\), file_name\)',
        r'self._emit("subhd.download.api.success", "SubHD 下载成功", log=context.log, subtitle_id=candidate.provider_subtitle_id, size=str(len(content)), file=file_name)',
        content
    )

    # Handle caption fetch helper log references - need to pass log through
    # _fetch_captcha_from_down_page receives `client, base_url, candidate, context`
    # _fetch_captcha_via_playwright receives `base_url, candidate`
    content = re.sub(
        r'''logger\.info\("subhd\.captcha\.playwright\.error reason=browser_unavailable"\)''',
        r'''self._emit("subhd.captcha.playwright.error", "SubHD Playwright浏览器不可用", log=context.log)''',
        content
    )
    content = re.sub(
        r'''logger\.info\("subhd\.captcha\.playwright\.screenshot selector=%s size=%d", selector, len\(screenshot_bytes\)\)''',
        r'''self._emit("subhd.captcha.playwright.screenshot", "SubHD Playwright截图验证码", log=context.log, selector=selector, size=str(len(screenshot_bytes)))''',
        content
    )
    content = re.sub(
        r'''logger\.info\("subhd\.captcha\.playwright\.no_captcha"\)''',
        r'''self._emit("subhd.captcha.playwright.no_captcha", "SubHD Playwright未找到验证码", log=context.log)''',
        content
    )
    content = re.sub(
        r'''logger\.info\("subhd\.captcha\.playwright\.error exc=%s", exc\)''',
        r'''self._emit("subhd.captcha.playwright.error", "SubHD Playwright验证码截图异常", log=context.log, error=repr(exc))''',
        content
    )

    with open(r'src\subtitle_info_collection\adapters\subhd.py', 'w', encoding='utf-8') as f:
        f.write(content)

    print(f'OK: Converted {count} logger.info to self._emit calls in subhd.py')

if __name__ == '__main__':
    main()
