from __future__ import annotations

import io
import shutil
import tempfile
import zipfile
from pathlib import Path

from ..errors import CollectorError, ErrorType
from ..models import DownloadedPayload, SubtitleCandidate
from .scorer import normalize_text
from .subtitle_engine import (
    MIN_VALID_SUBTITLE_BYTES,
    detect_subtitle_format,
    validate_downloaded_subtitle_bytes,
)


ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar"}


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
    """为提取的文件名评分"""
    text = normalize_text(path.name)
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
    return score


def _save_validated_bytes(
    data: bytes,
    save_path: Path,
    subtitle_format: str,
    file_name: str,
    lenient: bool = False,
) -> Path:
    validation = validate_downloaded_subtitle_bytes(data, subtitle_format, file_name, lenient=lenient)
    if not validation.valid and not lenient:
        validation = validate_downloaded_subtitle_bytes(data, subtitle_format, file_name, lenient=True)
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


def _extract_external_archive(payload: DownloadedPayload, candidate: SubtitleCandidate) -> list[tuple[str, bytes]]:
    """提取外部压缩包（7z/rar）中的字幕文件"""
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
            with rarfile.RarFile(archive_path) as archive:
                archive.extractall(extract_dir)
        else:
            raise CollectorError("不支持的压缩包格式", ErrorType.DOWNLOAD_FAILED)

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
            saved.append(_save_validated_bytes(data, save_path, subtitle_format, file_name, lenient=lenient))
            break
        except CollectorError as exc:
            last_error = exc

    if not saved and all_extracted:
        for file_name, data, subtitle_format in all_extracted:
            save_path = save_dir / f"{safe_filename(base_name)}.{subtitle_format}"
            try:
                saved.append(_save_validated_bytes(data, save_path, subtitle_format, file_name, lenient=True))
                break
            except CollectorError:
                continue

    if not saved:
        if last_error:
            raise last_error
        raise CollectorError(
            f"下载的载荷不包含大于 {MIN_VALID_SUBTITLE_BYTES // 1024}KB 的有效 ass/srt 字幕",
            ErrorType.DOWNLOAD_FAILED,
        )

    return saved

def create_zip_package(files: list[Path], output_path: Path, root_dir: Path) -> Path | None:
    """创建 ZIP 压缩包"""
    existing = [path for path in files if path.exists() and path.is_file()]
    if not existing:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        used: set[str] = set()
        for file_path in existing:
            try:
                arcname = file_path.relative_to(root_dir).as_posix()
            except ValueError:
                arcname = file_path.name
            base = Path(arcname)
            candidate = arcname
            index = 2
            while candidate in used:
                candidate = f"{base.stem}-{index}{base.suffix}"
                index += 1
            used.add(candidate)
            archive.write(file_path, candidate)
    return output_path


def cleanup_empty_dir(path: Path) -> None:
    """清理空目录"""
    if path.exists() and path.is_dir() and not any(path.iterdir()):
        shutil.rmtree(path, ignore_errors=True)
