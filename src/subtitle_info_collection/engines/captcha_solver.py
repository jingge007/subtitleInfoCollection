from __future__ import annotations

import base64
import logging
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from io import BytesIO

logger = logging.getLogger(__name__)

DATA_URI_RE = re.compile(r"^data:(?P<mime>[^;,]+)?(?:;charset=[^;,]+)?;base64,(?P<data>.+)$", re.I | re.S)
CAPTCHA_TEXT_RE = re.compile(r"[A-Za-z0-9]{3,8}")

ALPHANUMERIC_WHITELIST = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
LOWERCASE_WHITELIST = "abcdefghijklmnopqrstuvwxyz"
UPPERCASE_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS_WHITELIST = "0123456789"

PSM_SINGLE_WORD = 8
PSM_SINGLE_LINE = 7
PSM_SINGLE_CHAR = 10
PSM_RAW_LINE = 13

_PREPROCESS_CONFIGS = [
    {"name": "autocontrast_sharpen", "autocontrast": True, "sharpen": True, "binarize": False, "denoise": False, "morph": False},
    {"name": "otsu_only", "autocontrast": False, "sharpen": False, "binarize": True, "denoise": False, "morph": False},
    {"name": "denoise_otsu", "autocontrast": False, "sharpen": False, "binarize": True, "denoise": True, "morph": False},
    {"name": "denoise_morph", "autocontrast": False, "sharpen": False, "binarize": True, "denoise": True, "morph": True},
    {"name": "autocontrast_otsu", "autocontrast": True, "sharpen": False, "binarize": True, "denoise": False, "morph": False},
    {"name": "full_pipeline", "autocontrast": True, "sharpen": True, "binarize": True, "denoise": True, "morph": True},
]

# SubHD 专用预处理配置（裁剪空白 -> 放大 -> 灰度增强 -> 二值化 -> 去噪）
_SUBHD_PREPROCESS_CONFIGS = [
    {"name": "subhd_crop_upscale_otsu", "crop": True, "upscale": 2.0, "autocontrast": True, "sharpen": True, "binarize": True, "denoise": True, "morph": True},
    {"name": "subhd_crop_otsu", "crop": True, "upscale": 1.5, "autocontrast": True, "sharpen": False, "binarize": True, "denoise": True, "morph": False},
    {"name": "subhd_crop_autocontrast", "crop": True, "upscale": 2.0, "autocontrast": True, "sharpen": False, "binarize": False, "denoise": True, "morph": False},
    {"name": "subhd_invert_candidates", "crop": True, "upscale": 2.0, "autocontrast": True, "sharpen": True, "binarize": True, "denoise": True, "morph": True, "invert": True},
]

_PSM_MODES = [
    {"psm": PSM_SINGLE_LINE, "name": "single_line"},
    {"psm": PSM_SINGLE_WORD, "name": "single_word"},
    {"psm": PSM_RAW_LINE, "name": "raw_line"},
]

_WHITELIST_CONFIGS = [
    {"name": "alphanumeric", "whitelist": ALPHANUMERIC_WHITELIST},
    {"name": "lowercase", "whitelist": LOWERCASE_WHITELIST},
    {"name": "uppercase", "whitelist": UPPERCASE_WHITELIST},
    {"name": "digits", "whitelist": DIGITS_WHITELIST},
]


@dataclass(frozen=True, slots=True)
class CaptchaOcrResult:
    text: str = ""
    confidence: float = 0.0
    message: str = ""


@dataclass(frozen=True, slots=True)
class _OcrAttempt:
    text: str
    confidence: float
    config_desc: str


def clean_captcha_text(value: str = "") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value)
    matches = CAPTCHA_TEXT_RE.findall(cleaned)
    if matches:
        return max(matches, key=len)
    if 3 <= len(cleaned) <= 8:
        return cleaned
    return ""


def _decode_data_uri(data_uri: str) -> tuple[str, bytes]:
    match = DATA_URI_RE.match(data_uri.strip())
    if not match:
        return "", b""
    try:
        return match.group("mime") or "", base64.b64decode(match.group("data"), validate=False)
    except ValueError:
        return "", b""


def _crop_whitespace(image):
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

    return img


def _otsu_threshold(arr):
    import numpy as np
    hist, bins = np.histogram(arr.flatten(), bins=256, range=[0, 256])
    total_pixels = arr.size
    current_max_var = 0
    threshold = 0
    sum_total = np.dot(np.arange(256), hist)
    sum_background = 0
    weight_background = 0
    for t in range(256):
        weight_background += hist[t]
        if weight_background == 0:
            continue
        weight_foreground = total_pixels - weight_background
        if weight_foreground == 0:
            break
        sum_background += t * hist[t]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_total - sum_background) / weight_foreground
        inter_class_var = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if inter_class_var > current_max_var:
            current_max_var = inter_class_var
            threshold = t
    arr = np.where(arr > threshold, 255, 0).astype(np.uint8)
    return threshold, arr


def _run_tesseract_ocr(image, psm: int, whitelist: str) -> _OcrAttempt | None:
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError:
        return None

    config = f"--psm {psm} -c tessedit_char_whitelist={whitelist}"
    try:
        ocr_data = pytesseract.image_to_data(
            image,
            output_type=Output.DICT,
            config=config,
        )
    except Exception:
        return None

    words: list[str] = []
    confidences: list[float] = []
    for raw_text, raw_confidence in zip(ocr_data.get("text", []), ocr_data.get("conf", []), strict=False):
        text = clean_captcha_text(str(raw_text or ""))
        if not text:
            continue
        try:
            confidence = max(0.0, float(raw_confidence)) / 100
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence > 0:
            words.append(text)
            confidences.append(confidence)

    if not words:
        return None

    combined = clean_captcha_text("".join(words))
    if not combined:
        return None

    avg_confidence = sum(confidences) / len(confidences)
    return _OcrAttempt(
        text=combined,
        confidence=min(avg_confidence, 1.0),
        config_desc=f"psm{psm}_wl{whitelist[:5]}",
    )


def _run_tesseract_single_char(image, whitelist: str) -> _OcrAttempt | None:
    try:
        import pytesseract
    except ImportError:
        return None

    try:
        result = pytesseract.image_to_string(
            image,
            config=f"--psm {PSM_SINGLE_CHAR} -c tessedit_char_whitelist={whitelist}",
        ).strip()
        cleaned = clean_captcha_text(result)
        if cleaned:
            return _OcrAttempt(text=cleaned, confidence=0.7, config_desc="psm10_char")
    except Exception:
        pass
    return None


def _vote_best_result(attempts: list[_OcrAttempt]) -> _OcrAttempt | None:
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
    )


def _infer_whitelist_from_attempts(attempts: list[_OcrAttempt]) -> list[dict]:
    all_text = "".join(a.text for a in attempts)
    has_upper = bool(re.search(r"[A-Z]", all_text))
    has_lower = bool(re.search(r"[a-z]", all_text))
    has_digit = bool(re.search(r"[0-9]", all_text))

    configs = []
    if has_upper and has_lower and has_digit:
        configs.append({"name": "alphanumeric", "whitelist": ALPHANUMERIC_WHITELIST})
    if has_upper and not has_lower:
        configs.append({"name": "upper_digits", "whitelist": UPPERCASE_WHITELIST + DIGITS_WHITELIST})
    if has_lower and not has_upper:
        configs.append({"name": "lower_digits", "whitelist": LOWERCASE_WHITELIST + DIGITS_WHITELIST})
    if has_digit and not has_upper and not has_lower:
        configs.append({"name": "digits", "whitelist": DIGITS_WHITELIST})

    if not configs:
        configs.append({"name": "alphanumeric", "whitelist": ALPHANUMERIC_WHITELIST})

    return configs


def _solve_image_ocr(data: bytes, subhd_mode: bool = False) -> CaptchaOcrResult:
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
    )


def _solve_svg_text(data: bytes, subhd_mode: bool = False) -> CaptchaOcrResult:
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

    return CaptchaOcrResult(message="captcha SVG contains no readable text")


def _parse_svg_with_element_tree(svg_text: str) -> CaptchaOcrResult | None:
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return None

    text_parts: list[str] = []
    _extract_text_from_svg_element(root, text_parts)

    if not text_parts:
        return None

    combined = "".join(text_parts)
    cleaned = clean_captcha_text(combined)
    if cleaned:
        return CaptchaOcrResult(cleaned, 0.95, "captcha text extracted from SVG (ElementTree)")
    return None


def _extract_text_from_svg_element(element, text_parts: list[str]) -> None:
    tag = element.tag
    tag_local = tag.split("}")[-1] if "}" in tag else tag

    if tag_local in ("text", "tspan"):
        direct_text = element.text or ""
        if direct_text.strip():
            text_parts.append(direct_text.strip())

        for child in element:
            child_text = child.text or ""
            if child_text.strip():
                text_parts.append(child_text.strip())
            _extract_text_from_svg_element(child, text_parts)

        tail = element.tail or ""
        if tail.strip():
            text_parts.append(tail.strip())
    else:
        if element.text and element.text.strip():
            text_parts.append(element.text.strip())
        for child in element:
            _extract_text_from_svg_element(child, text_parts)
        if element.tail and element.tail.strip():
            text_parts.append(element.tail.strip())


def _parse_svg_with_regex(svg_text: str) -> CaptchaOcrResult | None:
    text_parts = [re.sub(r"<[^>]+>", "", item) for item in re.findall(r"<text[^>]*>(.*?)</text>", svg_text, re.I | re.S)]

    tspan_texts = re.findall(r"<tspan[^>]*>(.*?)</tspan>", svg_text, re.I | re.S)
    for tspan_text in tspan_texts:
        cleaned = re.sub(r"<[^>]+>", "", tspan_text).strip()
        if cleaned:
            text_parts.append(cleaned)

    combined = "".join(text_parts)
    cleaned = clean_captcha_text(combined)
    if cleaned:
        return CaptchaOcrResult(cleaned, 0.90, "captcha text extracted from SVG (regex)")
    return None


def _solve_svg_via_rendering(data: bytes, subhd_mode: bool = False) -> CaptchaOcrResult | None:
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

    return None


def solve_captcha_data_uri(data_uri: str, subhd_mode: bool = False) -> CaptchaOcrResult:
    mime_type, data = _decode_data_uri(data_uri)
    if not data:
        return CaptchaOcrResult(message="captcha image is unavailable")

    if "svg" in mime_type:
        return _solve_svg_text(data, subhd_mode=subhd_mode)

    return _solve_image_ocr(data, subhd_mode=subhd_mode)
