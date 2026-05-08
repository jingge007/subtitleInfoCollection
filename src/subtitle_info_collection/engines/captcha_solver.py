from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from io import BytesIO


@dataclass(frozen=True, slots=True)
class CaptchaOcrResult:
    text: str = ""
    confidence: float = 0.0
    message: str = ""


DATA_URI_RE = re.compile(r"^data:(?P<mime>[^;,]+)?(?:;charset=[^;,]+)?;base64,(?P<data>.+)$", re.I | re.S)
SVG_TEXT_RE = re.compile(r"<text[^>]*>(?P<text>.*?)</text>", re.I | re.S)
CAPTCHA_TEXT_RE = re.compile(r"[A-Za-z0-9]{3,8}")


def clean_captcha_text(value: str = "") -> str:
    matches = CAPTCHA_TEXT_RE.findall(value.replace(" ", ""))
    return matches[0] if matches else ""


def _decode_data_uri(data_uri: str) -> tuple[str, bytes]:
    match = DATA_URI_RE.match(data_uri.strip())
    if not match:
        return "", b""
    try:
        return match.group("mime") or "", base64.b64decode(match.group("data"), validate=False)
    except ValueError:
        return "", b""


def _solve_svg_text(data: bytes) -> CaptchaOcrResult:
    try:
        svg_text = data.decode("utf-8", errors="ignore")
    except Exception:
        return CaptchaOcrResult(message="captcha SVG decode failed")
    text_parts = [re.sub(r"<[^>]+>", "", item) for item in SVG_TEXT_RE.findall(svg_text)]
    cleaned = clean_captcha_text("".join(text_parts))
    if cleaned:
        return CaptchaOcrResult(cleaned, 0.95, "captcha text extracted from SVG")
    return CaptchaOcrResult(message="captcha SVG contains no readable text")


def solve_captcha_data_uri(data_uri: str) -> CaptchaOcrResult:
    mime_type, data = _decode_data_uri(data_uri)
    if not data:
        return CaptchaOcrResult(message="captcha image is unavailable")

    if "svg" in mime_type:
        return _solve_svg_text(data)

    try:
        from PIL import Image, ImageFilter, ImageOps
        import pytesseract
        from pytesseract import Output
    except ImportError:
        return CaptchaOcrResult(message="optional OCR dependencies are not installed")

    try:
        image = Image.open(BytesIO(data)).convert("L")
        image = ImageOps.autocontrast(image)
        image = image.filter(ImageFilter.SHARPEN)
        ocr_data = pytesseract.image_to_data(
            image,
            output_type=Output.DICT,
            config="--psm 8 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        )
    except Exception as exc:  # noqa: BLE001
        return CaptchaOcrResult(message=f"OCR failed: {exc}")

    words: list[str] = []
    confidences: list[float] = []
    for raw_text, raw_confidence in zip(
        ocr_data.get("text", []),
        ocr_data.get("conf", []),
        strict=False,
    ):
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

    cleaned = clean_captcha_text("".join(words))
    if not cleaned:
        return CaptchaOcrResult(message="OCR returned no captcha text")
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return CaptchaOcrResult(cleaned, min(confidence, 1.0), "OCR recognized captcha")
