from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ...engines.subtitle_engine import (
    MIN_VALID_SUBTITLE_BYTES,
    decode_subtitle_bytes,
    validate_is_simplified_chinese_english,
)
from ...local_parser import (
    parse_local_subtitle_file,
    write_movie_export_files,
    write_movie_search_index_file,
    write_subtitle_export_files,
)
from ..tasks import TaskContext


# 校验前端选择的字幕文件并返回可用于列表展示的元数据
def inspect_subtitle_files(paths: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(str(raw_path)).expanduser()
        item: dict[str, Any] = {
            "path": str(path),
            "name": path.name,
            "size": 0,
            "valid": False,
            "reason": "",
        }
        try:
            item["size"] = path.stat().st_size
        except OSError as exc:
            item["reason"] = f"读取失败：{exc}"
            items.append(item)
            continue

        if path.suffix.lower() not in {".srt", ".ass"}:
            item["reason"] = "格式不符，仅支持 .srt / .ass"
            items.append(item)
            continue
        if item["size"] < MIN_VALID_SUBTITLE_BYTES:
            item["reason"] = f"文件小于 100KB（当前 {item['size'] / 1024:.1f} KB）"
            items.append(item)
            continue
        try:
            decoded = decode_subtitle_bytes(path.read_bytes())
            is_valid, message = validate_is_simplified_chinese_english(decoded.content)
            if not is_valid:
                item["reason"] = message
            else:
                item["valid"] = True
        except Exception as exc:  # noqa: BLE001
            item["reason"] = f"读取失败：{exc}"
        items.append(item)
    return items


# 批量解析本地字幕并导出电影、字幕与搜索索引文件
async def run_parser(
    context: TaskContext,
    files: list[str],
    output_dir: Path,
    tmdb_token: str,
    unicloud_import_format: bool,
) -> dict[str, Any]:
    paths = [Path(item).expanduser() for item in files if str(item).strip()]
    context.reset(total=len(paths))
    context.set_status("running")
    context.update_stats(
        totalCount=len(paths),
        successCount=0,
        failureCount=0,
        exportCount=0,
    )
    if not paths:
        raise ValueError("请至少选择一个字幕文件")

    output_dir.mkdir(parents=True, exist_ok=True)
    movies_by_id: dict[str, dict[str, Any]] = {}
    subtitles: list[dict[str, Any]] = []
    success_count = 0
    failure_count = 0
    results: list[dict[str, Any]] = []

    try:
        for index, path in enumerate(paths, start=1):
            context.set_progress(index - 1, len(paths), path.name)
            context.append_log(f"解析字幕：{path.name}")
            try:
                parsed = await parse_local_subtitle_file(path, tmdb_token)
                payload = parsed.payload()
                movie_id = str(payload["movieId"])
                movies_by_id[movie_id] = dict(payload["movieData"])
                subtitles.extend(payload["subtitlesData"])
                success_count += 1
                results.append(
                    {
                        "name": path.name,
                        "path": str(path),
                        "status": "success",
                        "movieId": movie_id,
                        "subtitleCount": len(payload["subtitlesData"]),
                        "reason": "",
                    }
                )
                context.append_log(f"解析成功：{path.name}")
            except Exception as exc:  # noqa: BLE001
                failure_count += 1
                results.append(
                    {
                        "name": path.name,
                        "path": str(path),
                        "status": "failed",
                        "movieId": "",
                        "subtitleCount": 0,
                        "reason": str(exc),
                    }
                )
                context.append_log(f"解析失败：{path.name} / {exc}")
            context.update_stats(
                successCount=success_count,
                failureCount=failure_count,
                exportCount=len(subtitles),
            )
            context.set_progress(index, len(paths), path.name)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        movies_export = write_movie_export_files(
            list(movies_by_id.values()),
            output_dir,
            stamp,
            unicloud_import_format=unicloud_import_format,
        )
        subtitles_export = write_subtitle_export_files(
            subtitles,
            output_dir,
            stamp,
            unicloud_import_format=unicloud_import_format,
        )
        index_export = write_movie_search_index_file(
            subtitles=subtitles,
            movies=list(movies_by_id.values()),
            output_dir=output_dir,
            stamp=stamp,
            unicloud_import_format=unicloud_import_format,
        )
        output_paths = [
            *[str(path) for path in movies_export.paths],
            *[str(path) for path in subtitles_export.paths],
            *[str(path) for path in index_export.paths],
        ]
        context.outputs = output_paths
        context.set_status("finished")
        context.append_log(
            f"解析完成：成功 {success_count}，失败 {failure_count}，"
            f"导出字幕 {len(subtitles)} 条"
        )
        return {
            "results": results,
            "outputPaths": output_paths,
            "moviesPaths": [str(path) for path in movies_export.paths],
            "subtitlesPaths": [str(path) for path in subtitles_export.paths],
            "movieSearchIndexPaths": [str(path) for path in index_export.paths],
            "totalCount": len(paths),
            "successCount": success_count,
            "failureCount": failure_count,
            "exportCount": len(subtitles),
        }
    except Exception as exc:  # noqa: BLE001
        context.set_status("error", error=str(exc))
        context.append_log(f"解析任务失败：{exc}")
        raise
