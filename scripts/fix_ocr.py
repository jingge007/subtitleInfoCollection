"""Enhance captcha_solver.py with SubHD-specific preprocessing."""

def main():
    with open(r'src\subtitle_info_collection\engines\captcha_solver.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Add SubHD-specific preprocessing pipeline after the existing _PREPROCESS_CONFIGS
    marker = '_PSM_MODES = ['
    subhd_pipeline = '''# SubHD 专用预处理配置（裁剪空白 -> 放大 -> 灰度增强 -> 二值化 -> 去噪）
_SUBHD_PREPROCESS_CONFIGS = [
    {"name": "subhd_crop_upscale_otsu", "crop": True, "upscale": 2.0, "autocontrast": True, "sharpen": True, "binarize": True, "denoise": True, "morph": True},
    {"name": "subhd_crop_otsu", "crop": True, "upscale": 1.5, "autocontrast": True, "sharpen": False, "binarize": True, "denoise": True, "morph": False},
    {"name": "subhd_crop_autocontrast", "crop": True, "upscale": 2.0, "autocontrast": True, "sharpen": False, "binarize": False, "denoise": True, "morph": False},
    {"name": "subhd_invert_candidates", "crop": True, "upscale": 2.0, "autocontrast": True, "sharpen": True, "binarize": True, "denoise": True, "morph": True, "invert": True},
]

'''

    if marker in content and '_SUBHD_PREPROCESS_CONFIGS' not in content:
        content = content.replace(marker, subhd_pipeline + marker)
        print('OK: Added SubHD preprocessing configs')
    else:
        print('SKIP: SubHD configs already exist or marker not found')

    # 2. Add crop_whitespace and enhanced preprocessing function
    old_apply = '''def _apply_preprocessing(image, config: dict):
    from PIL import Image, ImageFilter, ImageOps

    img = image.convert("L")

    if config.get("autocontrast"):
        img = ImageOps.autocontrast(img)

    if config.get("denoise"):
        img = img.filter(ImageFilter.MedianFilter(size=3))

    if config.get("sharpen"):
        img = img.filter(ImageFilter.SHARPEN)

    if config.get("binarize"):
        import numpy as np
        arr = np.array(img)
        _, arr = _otsu_threshold(arr)
        img = Image.fromarray(arr, mode="L")

    if config.get("morph"):
        import numpy as np
        import cv2
        arr = np.array(img)
        kernel = np.ones((2, 2), np.uint8)
        arr = cv2.morphologyEx(arr, cv2.MORPH_CLOSE, kernel)
        arr = cv2.morphologyEx(arr, cv2.MORPH_OPEN, kernel)
        img = Image.fromarray(arr, mode="L")

    return img'''

    new_apply = '''def _crop_whitespace(image):
    """裁剪图片四周空白区域。"""
    try:
        import numpy as np
    except ImportError:
        return image
    arr = np.array(image.convert("L"))
    nonwhite = np.where(arr < 240)
    if nonwhite[0].size == 0:
        return image
    top, bottom = nonwhite[0].min(), nonwhite[0].max()
    left, right = nonwhite[1].min(), nonwhite[1].max()
    # 保留一点边距
    top = max(0, top - 2)
    left = max(0, left - 2)
    bottom = min(arr.shape[0], bottom + 3)
    right = min(arr.shape[1], right + 3)
    return image.crop((left, top, right, bottom))


def _remove_diagonal_lines(image):
    """去除对角线干扰线（SubHD 验证码常见）。"""
    try:
        import numpy as np
        import cv2
    except ImportError:
        return image
    arr = np.array(image)
    if len(arr.shape) > 2:
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    else:
        gray = arr.copy()
    # 二值化
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # 使用形态学找到细长斜线
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
    horizontal_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    vertical_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
    lines = cv2.add(horizontal_lines, vertical_lines)
    # 从原图中减去检测到的线条
    cleaned = cv2.subtract(binary, lines)
    # 连通域过滤：去除过小的噪点
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned, connectivity=8)
    min_area = 15
    result = np.zeros_like(cleaned)
    for i in range(1, num_labels):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            result[labels == i] = 255
    # 恢复为白底黑字
    result = 255 - result
    return Image.fromarray(result, mode="L")


def _apply_preprocessing(image, config: dict):
    from PIL import Image, ImageFilter, ImageOps

    img = image.convert("L")

    if config.get("crop"):
        img = _crop_whitespace(img)

    if config.get("upscale"):
        scale = float(config["upscale"])
        if scale > 1.0:
            new_w = max(int(img.width * scale), 100)
            new_h = max(int(img.height * scale), 40)
            img = img.resize((new_w, new_h), Image.LANCZOS)

    if config.get("autocontrast"):
        img = ImageOps.autocontrast(img)

    if config.get("denoise"):
        img = img.filter(ImageFilter.MedianFilter(size=3))

    if config.get("sharpen"):
        img = img.filter(ImageFilter.SHARPEN)

    if config.get("binarize"):
        import numpy as np
        arr = np.array(img)
        _, arr = _otsu_threshold(arr)
        img = Image.fromarray(arr, mode="L")

    if config.get("morph"):
        import numpy as np
        import cv2
        arr = np.array(img)
        kernel = np.ones((2, 2), np.uint8)
        arr = cv2.morphologyEx(arr, cv2.MORPH_CLOSE, kernel)
        arr = cv2.morphologyEx(arr, cv2.MORPH_OPEN, kernel)
        img = Image.fromarray(arr, mode="L")

    if config.get("invert"):
        import numpy as np
        arr = np.array(img)
        img = Image.fromarray(255 - arr, mode="L")

    return img'''

    if old_apply in content:
        content = content.replace(old_apply, new_apply)
        print('OK: Enhanced _apply_preprocessing with SubHD-specific features')
    else:
        print('NOT FOUND: old _apply_preprocessing')

    # 3. Enhance _solve_image_ocr to use SubHD-specific preprocessing
    old_solve = '''def _solve_image_ocr(data: bytes) -> CaptchaOcrResult:
    try:
        from PIL import Image
    except ImportError:
        return CaptchaOcrResult(message="optional OCR dependencies are not installed")

    try:
        base_image = Image.open(BytesIO(data)).convert("L")
    except Exception as exc:
        return CaptchaOcrResult(message=f"image open failed: {exc}")

    all_attempts: list[_OcrAttempt] = []

    for prep_config in _PREPROCESS_CONFIGS:
        try:
            processed = _apply_preprocessing(base_image, prep_config)
        except Exception:
            continue

        for psm_mode in _PSM_MODES:
            for wl_config in _WHITELIST_CONFIGS[:2]:
                attempt = _run_tesseract_ocr(processed, psm_mode["psm"], wl_config["whitelist"])
                if attempt:
                    attempt_desc = f"{prep_config['name']}_{psm_mode['name']}_{wl_config['name']}"
                    all_attempts.append(attempt)

        char_attempt = _run_tesseract_single_char(processed, ALPHANUMERIC_WHITELIST)
        if char_attempt:
            all_attempts.append(char_attempt)

    if not all_attempts:
        return CaptchaOcrResult(message="OCR returned no captcha text")

    inferred_wl_configs = _infer_whitelist_from_attempts(all_attempts)
    if inferred_wl_configs and inferred_wl_configs[0]["whitelist"] != ALPHANUMERIC_WHITELIST:
        best_prep = _PREPROCESS_CONFIGS[0]
        try:
            processed = _apply_preprocessing(base_image, best_prep)
            for wl_config in inferred_wl_configs:
                for psm_mode in _PSM_MODES:
                    attempt = _run_tesseract_ocr(processed, psm_mode["psm"], wl_config["whitelist"])
                    if attempt:
                        all_attempts.append(attempt)
        except Exception:
            pass

    best = _vote_best_result(all_attempts)
    if not best:
        return CaptchaOcrResult(message="OCR returned no captcha text")

    return CaptchaOcrResult(
        text=best.text,
        confidence=best.confidence,
        message=f"OCR recognized captcha ({best.message})",
    )'''

    new_solve = '''def _solve_image_ocr(data: bytes, subhd_mode: bool = False) -> CaptchaOcrResult:
    try:
        from PIL import Image
    except ImportError:
        return CaptchaOcrResult(message="optional OCR dependencies are not installed")

    try:
        base_image = Image.open(BytesIO(data)).convert("L")
    except Exception as exc:
        return CaptchaOcrResult(message=f"image open failed: {exc}")

    all_attempts: list[_OcrAttempt] = []

    # SubHD 专用预处理管线：先走专用预处理
    if subhd_mode:
        try:
            dediag = _remove_diagonal_lines(base_image)
        except Exception:
            dediag = base_image
        for prep_config in _SUBHD_PREPROCESS_CONFIGS:
            try:
                processed = _apply_preprocessing(dediag, prep_config)
            except Exception:
                continue
            for psm_mode in _PSM_MODES:
                for wl_config in _WHITELIST_CONFIGS[:2]:
                    attempt = _run_tesseract_ocr(processed, psm_mode["psm"], wl_config["whitelist"])
                    if attempt:
                        all_attempts.append(attempt)
            char_attempt = _run_tesseract_single_char(processed, ALPHANUMERIC_WHITELIST)
            if char_attempt:
                all_attempts.append(char_attempt)

    # 通用预处理管线
    for prep_config in _PREPROCESS_CONFIGS:
        try:
            processed = _apply_preprocessing(base_image, prep_config)
        except Exception:
            continue

        for psm_mode in _PSM_MODES:
            for wl_config in _WHITELIST_CONFIGS[:2]:
                attempt = _run_tesseract_ocr(processed, psm_mode["psm"], wl_config["whitelist"])
                if attempt:
                    all_attempts.append(attempt)

        char_attempt = _run_tesseract_single_char(processed, ALPHANUMERIC_WHITELIST)
        if char_attempt:
            all_attempts.append(char_attempt)

    if not all_attempts:
        return CaptchaOcrResult(message="OCR returned no captcha text")

    inferred_wl_configs = _infer_whitelist_from_attempts(all_attempts)
    if inferred_wl_configs and inferred_wl_configs[0]["whitelist"] != ALPHANUMERIC_WHITELIST:
        best_prep = _PREPROCESS_CONFIGS[0]
        try:
            processed = _apply_preprocessing(base_image, best_prep)
            for wl_config in inferred_wl_configs:
                for psm_mode in _PSM_MODES:
                    attempt = _run_tesseract_ocr(processed, psm_mode["psm"], wl_config["whitelist"])
                    if attempt:
                        all_attempts.append(attempt)
        except Exception:
            pass

    best = _vote_best_result(all_attempts)
    if not best:
        return CaptchaOcrResult(message="OCR returned no captcha text")

    return CaptchaOcrResult(
        text=best.text,
        confidence=best.confidence,
        message=f"OCR recognized captcha ({best.message})",
    )'''

    if old_solve in content:
        content = content.replace(old_solve, new_solve)
        print('OK: Enhanced _solve_image_ocr with SubHD-specific preprocessing')
    else:
        print('NOT FOUND: old _solve_image_ocr')

    # 4. Update _solve_svg_via_rendering to use higher resolution
    old_svg_render = '''def _solve_svg_via_rendering(data: bytes) -> CaptchaOcrResult | None:
    try:
        import cairosvg
    except ImportError:
        try:
            from svglib.svglib import svg2rlg
            from reportlab.graphics import renderPM
        except ImportError:
            return None
        try:
            drawing = svg2rlg(BytesIO(data))
            if drawing is None:
                return None
            png_data = BytesIO()
            renderPM.drawToFile(drawing, png_data, "PNG")
            png_data.seek(0)
            return _solve_image_ocr(png_data.read())
        except Exception:
            return None

    try:
        png_data = cairosvg.svg2png(bytestring=data)
        if png_data:
            return _solve_image_ocr(png_data)
    except Exception:
        pass

    return None'''

    new_svg_render = '''def _solve_svg_via_rendering(data: bytes, subhd_mode: bool = False) -> CaptchaOcrResult | None:
    try:
        import cairosvg
    except ImportError:
        try:
            from svglib.svglib import svg2rlg
            from reportlab.graphics import renderPM
        except ImportError:
            return None
        try:
            drawing = svg2rlg(BytesIO(data))
            if drawing is None:
                return None
            # 高分辨率渲染
            scale = 3.0
            drawing.scale(scale, scale)
            png_data = BytesIO()
            renderPM.drawToFile(drawing, png_data, "PNG")
            png_data.seek(0)
            return _solve_image_ocr(png_data.read(), subhd_mode=subhd_mode)
        except Exception:
            return None

    try:
        # 高分辨率渲染 SVG
        png_data = cairosvg.svg2png(bytestring=data, scale=3.0)
        if png_data:
            return _solve_image_ocr(png_data, subhd_mode=subhd_mode)
    except Exception:
        pass

    return None'''

    if old_svg_render in content:
        content = content.replace(old_svg_render, new_svg_render)
        print('OK: Enhanced SVG rendering with high-res support')
    else:
        print('NOT FOUND: old _solve_svg_via_rendering')

    # 5. Update _solve_svg_text to pass subhd_mode
    old_svg_text = '''def _solve_svg_text(data: bytes) -> CaptchaOcrResult:
    try:
        svg_text = data.decode("utf-8", errors="ignore")
    except Exception:
        return CaptchaOcrResult(message="captcha SVG decode failed")

    result = _parse_svg_with_element_tree(svg_text)
    if result:
        return result

    result = _parse_svg_with_regex(svg_text)
    if result:
        return result

    result = _solve_svg_via_rendering(data)
    if result:
        return result

    return CaptchaOcrResult(message="captcha SVG contains no readable text")'''

    new_svg_text = '''def _solve_svg_text(data: bytes, subhd_mode: bool = False) -> CaptchaOcrResult:
    try:
        svg_text = data.decode("utf-8", errors="ignore")
    except Exception:
        return CaptchaOcrResult(message="captcha SVG decode failed")

    result = _parse_svg_with_element_tree(svg_text)
    if result:
        return result

    result = _parse_svg_with_regex(svg_text)
    if result:
        return result

    result = _solve_svg_via_rendering(data, subhd_mode=subhd_mode)
    if result:
        return result

    return CaptchaOcrResult(message="captcha SVG contains no readable text")'''

    if old_svg_text in content:
        content = content.replace(old_svg_text, new_svg_text)
        print('OK: Updated _solve_svg_text with subhd_mode')
    else:
        print('NOT FOUND: old _solve_svg_text')

    # 6. Update solve_captcha_data_uri to accept subhd_mode
    old_entry = '''def solve_captcha_data_uri(data_uri: str) -> CaptchaOcrResult:
    mime_type, data = _decode_data_uri(data_uri)
    if not data:
        return CaptchaOcrResult(message="captcha image is unavailable")

    if "svg" in mime_type:
        return _solve_svg_text(data)

    return _solve_image_ocr(data)'''

    new_entry = '''def solve_captcha_data_uri(data_uri: str, subhd_mode: bool = False) -> CaptchaOcrResult:
    mime_type, data = _decode_data_uri(data_uri)
    if not data:
        return CaptchaOcrResult(message="captcha image is unavailable")

    if "svg" in mime_type:
        return _solve_svg_text(data, subhd_mode=subhd_mode)

    return _solve_image_ocr(data, subhd_mode=subhd_mode)'''

    if old_entry in content:
        content = content.replace(old_entry, new_entry)
        print('OK: Updated solve_captcha_data_uri with subhd_mode')
    else:
        print('NOT FOUND: old solve_captcha_data_uri')

    # 7. Enhance _vote_best_result to prefer 4-character captchas
    old_vote = '''def _vote_best_result(attempts: list[_OcrAttempt]) -> _OcrAttempt | None:
    if not attempts:
        return None

    text_votes: dict[str, list[_OcrAttempt]] = {}
    for attempt in attempts:
        normalized = attempt.text.lower()
        if normalized not in text_votes:
            text_votes[normalized] = []
        text_votes[normalized].append(attempt)

    best_text = max(text_votes.keys(), key=lambda t: (len(text_votes[t]), max(a.confidence for a in text_votes[t])))
    best_attempts = text_votes[best_text]
    best_attempt = max(best_attempts, key=lambda a: a.confidence)

    vote_bonus = min(0.15, len(best_attempts) * 0.05)
    boosted_confidence = min(1.0, best_attempt.confidence + vote_bonus)

    return _OcrAttempt(
        text=best_attempt.text,
        confidence=boosted_confidence,
        message=f"voted from {len(attempts)} attempts, {len(best_attempts)} agreed",
    )'''

    new_vote = '''def _vote_best_result(attempts: list[_OcrAttempt]) -> _OcrAttempt | None:
    if not attempts:
        return None

    text_votes: dict[str, list[_OcrAttempt]] = {}
    for attempt in attempts:
        normalized = attempt.text.lower()
        if normalized not in text_votes:
            text_votes[normalized] = []
        text_votes[normalized].append(attempt)

    # 优先 4 位验证码（SubHD 最常见的格式），按投票数 + 置信度排序
    def _score_key(t: str) -> tuple[int, int, float]:
        votes = len(text_votes[t])
        best_conf = max(a.confidence for a in text_votes[t])
        # 4位验证码加分
        length_bonus = 1 if len(t) == 4 else 0
        return (length_bonus, votes, best_conf)

    best_text = max(text_votes.keys(), key=_score_key)
    best_attempts = text_votes[best_text]
    best_attempt = max(best_attempts, key=lambda a: a.confidence)

    vote_bonus = min(0.15, len(best_attempts) * 0.05)
    # 4位验证码额外的置信度奖励
    if len(best_text) == 4:
        vote_bonus += 0.05
    boosted_confidence = min(1.0, best_attempt.confidence + vote_bonus)

    return _OcrAttempt(
        text=best_attempt.text,
        confidence=boosted_confidence,
        message=f"voted from {len(attempts)} attempts, {len(best_attempts)} agreed",
    )'''

    if old_vote in content:
        content = content.replace(old_vote, new_vote)
        print('OK: Enhanced _vote_best_result to prefer 4-char captchas')
    else:
        print('NOT FOUND: old _vote_best_result')

    with open(r'src\subtitle_info_collection\engines\captcha_solver.py', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    main()
