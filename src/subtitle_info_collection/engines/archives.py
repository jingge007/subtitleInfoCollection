from __future__ import annotations

import io
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from ..errors import CollectorError, ErrorType
from ..models import DownloadedPayload, SubtitleCandidate
from .scorer import normalize_text
from .subtitle_engine import (
    DEFAULT_MIN_BILINGUAL_RATIO,
    MIN_VALID_SUBTITLE_BYTES,
    detect_subtitle_format,
    validate_downloaded_subtitle_bytes,
)


ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar"}

# 7z.exe 在用户目录的存储位置（自动下载时使用）
_SEVENZIP_USER_DIR = Path.home() / ".subtitle_collection" / "tools"


def _find_sevenzip_exe() -> str | None:
    """按优先级检测 7z.exe 的可用路径"""
    # 1. PyInstaller 打包目录
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).parent / "_internal" / "7z.exe"
        if bundled.exists():
            return str(bundled)
    # 2. 用户目录（自动下载的）
    appdata_7z = _SEVENZIP_USER_DIR / "7z.exe"
    if appdata_7z.exists():
        return str(appdata_7z)
    # 3. 开发环境 assets/ 目录
    dev_7z = Path(__file__).resolve().parents[3] / "assets" / "7z.exe"
    if dev_7z.exists():
        return str(dev_7z)
    # 4. 系统 PATH
    system_7z = shutil.which("7z.exe") or shutil.which("7z")
    if system_7z:
        return system_7z
    # 5. 常见安装路径
    for candidate in [
        Path("C:/Program Files/7-Zip/7z.exe"),
        Path("C:/Program Files (x86)/7-Zip/7z.exe"),
    ]:
        if candidate.exists():
            return str(candidate)
    return None


def _download_sevenzip() -> str | None:
    """自动下载 7z.exe + 7z.dll 到用户目录

    使用两步法：
    1. 下载 7za.exe（独立版，无需 DLL，支持 7z 格式解压）
    2. 下载 7-Zip 安装器（内嵌 7z 压缩数据）
    3. 用 7za.exe 从安装器中提取 7z.exe + 7z.dll（完整版，支持 RAR 解压）
    """
    import httpx
    import subprocess

    _SEVENZIP_USER_DIR.mkdir(parents=True, exist_ok=True)
    sevenza_path = _SEVENZIP_USER_DIR / "7za.exe"
    temp_dir = Path(tempfile.mkdtemp(prefix="7z-download-"))
    try:
        # Step 1: 下载 7za.exe（独立版，支持 7z 格式解压）
        if not sevenza_path.exists():
            sevenza_url = "https://raw.githubusercontent.com/a-sync/7z-extra/master/7za.exe"
            with httpx.Client(follow_redirects=True, timeout=120) as client:
                resp = client.get(sevenza_url)
                resp.raise_for_status()
            sevenza_path.write_bytes(resp.content)

        if not sevenza_path.exists():
            return None

        # Step 2: 下载 7-Zip 安装器（内嵌 7z 压缩数据）
        installer_url = "https://github.com/ip7z/7zip/releases/download/26.01/7z2601-x64.exe"
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            resp = client.get(installer_url)
            resp.raise_for_status()
        installer_data = resp.content

        # Step 3: 在安装器中搜索 7z 签名，定位嵌入的 7z 压缩数据
        # 7-Zip 安装器是 7z SD SFX 格式：PE stub + 7z archive
        # 可能有多个 7z 签名，需要找到正确的那个
        sig = b"7z\xbc\xaf\x27\x1c"
        offset = 0
        valid_offset = None
        while True:
            offset = installer_data.find(sig, offset)
            if offset < 0:
                break
            # 尝试用 7za.exe 解压此偏移处的数据
            inner_path = temp_dir / f"inner_{offset}.7z"
            inner_path.write_bytes(installer_data[offset:])
            extract_dir = temp_dir / f"extract_{offset}"
            extract_dir.mkdir()
            result = subprocess.run(
                [str(sevenza_path), "x", str(inner_path), f"-o{extract_dir}", "-y"],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0:
                exe_candidates = list(extract_dir.rglob("7z.exe"))
                dll_candidates = list(extract_dir.rglob("7z.dll"))
                if exe_candidates:
                    valid_offset = offset
                    # 复制 7z.exe + 7z.dll
                    shutil.copy2(exe_candidates[0], _SEVENZIP_USER_DIR / "7z.exe")
                    if dll_candidates:
                        shutil.copy2(dll_candidates[0], _SEVENZIP_USER_DIR / "7z.dll")
                    break
            offset += 1

        if valid_offset is None:
            return None

        result_path = str(_SEVENZIP_USER_DIR / "7z.exe")
        if not Path(result_path).exists():
            return None

        # 验证 7z.exe 可用
        test_result = subprocess.run(
            [result_path], capture_output=True, timeout=10
        )
        if test_result.returncode != 0 and test_result.returncode != 7:
            return None

        return result_path
    except Exception:
        return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _ensure_sevenzip_available() -> None:
    """确保 rarfile 可以使用 7z.exe 解压 RAR 文件，必要时自动下载"""
    try:
        import rarfile
    except ImportError:
        return

    path = _find_sevenzip_exe()
    if not path:
        path = _download_sevenzip()
    if path:
        rarfile.SEVENZIP_TOOL = path
        rarfile.tool_setup(force=True)


# 模块加载时自动配置 rarfile 的解压工具
_ensure_sevenzip_available()


def safe_filename(value: str = "", fallback: str = "subtitle") -> str:
    """生成安全的文件名"""
    cleaned = "".join("_" if char in '\\/:*?"<>|' else char for char in value)
    cleaned = ".".join(part for part in cleaned.replace(" ", ".").split(".") if part)
    return cleaned[:180] or fallback


def _is_archive_payload(payload: DownloadedPayload) -> bool:
    """检查是否为压缩包载荷"""
    suffix = Path(payload.file_name).suffix.lower()
    if suffix in ARCHIVE_EXTENSIONS:
        return True
    return payload.content[:2] in {b"PK", b"7z"} or payload.content[:4] == b"Rar!"


def _score_extracted_name(path: Path, candidate: SubtitleCandidate) -> float:
    """为提取的文件名评分：双语文件优先，纯英/仅繁靠后"""
    name = path.name
    text = normalize_text(name)
    score = 0.0
    for value, weight in [
        (candidate.movie_title_zh, 80),
        (candidate.movie_title, 60),
        (candidate.movie_original_title, 55),
        (str(candidate.movie_year or ""), 20),
    ]:
        if value and normalize_text(value) in text:
            score += weight
    if path.suffix.lower().lstrip(".") == candidate.subtitle_format:
        score += 8
    bilingual_re = re.compile(
        r"(简体\s*[&+_]\s*英文|简繁英|chs\s*[&_.-]\s*eng|eng\s*[&_.-]\s*chs|"
        r"chs_eng|zh[-_.]?en|中英|简英)",
        re.I,
    )
    if bilingual_re.search(name):
        score += 200.0
    elif re.search(r"(^|[._\s-])(eng|english|英文)([._\s-]|$)", name, re.I) and not re.search(
        r"简|chs|zh|中文|双语", name, re.I
    ):
        score -= 120.0
    elif re.search(r"(繁体|cht|traditional)", name, re.I) and not re.search(
        r"简|chs|双语|eng|英文", name, re.I
    ):
        score -= 80.0
    return score


def _save_validated_bytes(
    data: bytes,
    save_path: Path,
    subtitle_format: str,
    file_name: str,
    lenient: bool = False,
    min_bilingual_ratio: float = DEFAULT_MIN_BILINGUAL_RATIO,
) -> Path:
    validation = validate_downloaded_subtitle_bytes(
        data,
        subtitle_format,
        file_name,
        lenient=lenient,
        min_bilingual_ratio=min_bilingual_ratio,
    )
    if not validation.valid and not lenient:
        validation = validate_downloaded_subtitle_bytes(
            data,
            subtitle_format,
            file_name,
            lenient=True,
            min_bilingual_ratio=min_bilingual_ratio,
        )
        if validation.valid:
            lenient = True

    if not validation.valid:
        raise CollectorError(validation.reason, validation.error_type)

    content = validation.content or data.decode("utf-8", errors="replace")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(content, encoding="utf-8")
    return save_path


def _extract_zip_payload(payload: DownloadedPayload, candidate: SubtitleCandidate) -> list[tuple[str, bytes]]:
    """提取 ZIP 压缩包中的字幕文件"""
    result: list[tuple[str, bytes]] = []
    with tempfile.TemporaryDirectory(prefix="subtitle-zip-") as temp_name:
        archive_path = Path(temp_name) / "archive.zip"
        archive_path.write_bytes(payload.content)
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                suffix = Path(info.filename).suffix.lower().lstrip(".")
                if suffix not in {"ass", "srt"}:
                    continue
                result.append((Path(info.filename).name, archive.read(info)))

    return sorted(
        result,
        key=lambda item: _score_extracted_name(Path(item[0]), candidate),
        reverse=True,
    )


def _is_html_content(data: bytes) -> bool:
    """检测内容是否为 HTML 页面"""
    if not data:
        return False
    stripped = data.lstrip()
    if not stripped:
        return False
    head = stripped[:500].lower()
    html_markers = [
        b"<!doctype", b"<html", b"<head", b"<body", b"<div",
        b"<script", b"<meta", b"<title>", b"<!--",
    ]
    for marker in html_markers:
        if marker in head:
            return True
    return False


def _extract_external_archive(payload: DownloadedPayload, candidate: SubtitleCandidate) -> list[tuple[str, bytes]]:
    """提取外部压缩包（7z/rar）中的字幕文件"""
    # 首先检测是否为 HTML 内容（可能是错误页面）
    if _is_html_content(payload.content):
        raise CollectorError(
            "下载的内容是 HTML 页面而非压缩包，可能是网站返回了错误页面或需要验证。请尝试使用浏览器手动下载。",
            ErrorType.DOWNLOAD_FAILED,
        )

    suffix = Path(payload.file_name).suffix.lower()
    result: list[tuple[str, bytes]] = []
    with tempfile.TemporaryDirectory(prefix="subtitle-archive-") as temp_name:
        temp_dir = Path(temp_name)
        archive_path = temp_dir / f"archive{suffix or '.bin'}"
        extract_dir = temp_dir / "extract"
        archive_path.write_bytes(payload.content)
        extract_dir.mkdir()

        if suffix == ".7z" or payload.content[:2] == b"7z":
            try:
                import py7zr
            except ImportError as exc:  # pragma: no cover
                raise CollectorError("需要 py7zr 才能提取 7z 压缩包", ErrorType.DOWNLOAD_FAILED) from exc
            with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                archive.extractall(extract_dir)
        elif suffix == ".rar" or payload.content[:4] == b"Rar!":
            try:
                import rarfile
            except ImportError as exc:  # pragma: no cover
                raise CollectorError("需要 rarfile 才能提取 RAR 压缩包", ErrorType.DOWNLOAD_FAILED) from exc
            try:
                with rarfile.RarFile(archive_path) as archive:
                    archive.extractall(extract_dir)
            except rarfile.RarCannotExec as exc:
                raise CollectorError(
                    "系统未安装 RAR 解压工具（7-Zip 或 UnRAR），无法解压 RAR 格式字幕。"
                    "请安装 7-Zip（https://7-zip.org）后重试。",
                    ErrorType.DOWNLOAD_FAILED,
                ) from exc
            except rarfile.BadRarFile as exc:
                raise CollectorError(
                    "RAR 文件损坏或格式无效，可能是下载不完整或服务器返回了错误页面。",
                    ErrorType.DOWNLOAD_FAILED,
                ) from exc
        else:
            # 尝试检测实际的压缩格式
            magic = payload.content[:8]
            if magic[:2] == b"PK":
                # ZIP 格式，但不在 zip 路径处理
                raise CollectorError("下载的是 ZIP 格式，但被错误识别。请重试。", ErrorType.DOWNLOAD_FAILED)
            elif magic[:4] == b"Rar!":
                # RAR 格式
                pass  # 已在上面处理
            elif magic[:2] == b"7z":
                # 7z 格式
                pass  # 已在上面处理
            else:
                # 尝试显示内容开头以帮助诊断
                content_preview = payload.content[:100]
                if _is_html_content(payload.content):
                    raise CollectorError(
                        "下载的内容是 HTML 页面而非压缩包，可能是网站返回了错误页面。",
                        ErrorType.DOWNLOAD_FAILED,
                    )
                raise CollectorError(
                    f"不支持的压缩包格式（文件头: {content_preview[:20].hex()}），"
                    f"支持的格式: ZIP, 7z, RAR",
                    ErrorType.DOWNLOAD_FAILED,
                )

        files = sorted(
            [
                path
                for path in extract_dir.rglob("*")
                if path.is_file() and path.suffix.lower().lstrip(".") in {"ass", "srt"}
            ],
            key=lambda item: _score_extracted_name(item, candidate),
            reverse=True,
        )
        for path in files:
            result.append((path.name, path.read_bytes()))

    return result


def save_downloaded_payloads(
    payloads: list[DownloadedPayload],
    save_dir: Path,
    base_name: str,
    candidate: SubtitleCandidate,
    lenient: bool = False,
    min_bilingual_ratio: float = DEFAULT_MIN_BILINGUAL_RATIO,
) -> list[Path]:
    saved: list[Path] = []
    last_error: CollectorError | None = None
    all_extracted: list[tuple[str, bytes, str]] = []

    for payload in payloads:
        extracted_items: list[tuple[str, bytes]]
        if _is_archive_payload(payload):
            if zipfile.is_zipfile(io.BytesIO(payload.content)):
                extracted_items = _extract_zip_payload(payload, candidate)
            else:
                extracted_items = _extract_external_archive(payload, candidate)
        else:
            extracted_items = [(payload.file_name, payload.content)]

        for file_name, data in extracted_items:
            subtitle_format = detect_subtitle_format(file_name) or candidate.subtitle_format
            if subtitle_format not in {"ass", "srt"}:
                continue
            all_extracted.append((file_name, data, subtitle_format))

    for file_name, data, subtitle_format in all_extracted:
        save_path = save_dir / f"{safe_filename(base_name)}.{subtitle_format}"
        try:
            saved.append(
                _save_validated_bytes(
                    data,
                    save_path,
                    subtitle_format,
                    file_name,
                    lenient=lenient,
                    min_bilingual_ratio=min_bilingual_ratio,
                )
            )
            break
        except CollectorError as exc:
            last_error = exc

    if not saved and all_extracted:
        for file_name, data, subtitle_format in all_extracted:
            save_path = save_dir / f"{safe_filename(base_name)}.{subtitle_format}"
            try:
                saved.append(
                    _save_validated_bytes(
                        data,
                        save_path,
                        subtitle_format,
                        file_name,
                        lenient=True,
                        min_bilingual_ratio=min_bilingual_ratio,
                    )
                )
                break
            except CollectorError:
                continue

    if not saved:
        if last_error:
            raise last_error
        raise CollectorError(
            "下载的载荷不包含有效的中英双语 ass/srt 字幕",
            ErrorType.DOWNLOAD_FAILED,
        )

    return saved

