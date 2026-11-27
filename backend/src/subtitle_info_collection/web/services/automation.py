from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ...automation import (
    ClassicLinesAutomationOptions,
    ClassicLinesAutomationRunner,
    TodaysLinesAutomationOptions,
    TodaysLinesAutomationRunner,
)
from ..tasks import TaskContext


# 将自动化进度转换成 Web 任务上下文状态
def _progress(context: TaskContext, current: int, total: int, item: str) -> None:
    context.set_progress(current, total, item)


# 执行 33 台词今日台词采集
async def run_todays_lines(
    context: TaskContext,
    data_dir: Path,
    env_path: Path,
    unicloud_import_format: bool,
) -> dict[str, Any]:
    context.reset()
    context.set_status("running")
    try:
        options = TodaysLinesAutomationOptions(
            data_dir=data_dir,
            env_path=env_path,
            unicloud_import_format=unicloud_import_format,
        )
        runner = TodaysLinesAutomationRunner(
            options,
            log=context.append_log,
            progress=lambda current, total, item: _progress(context, current, total, item),
        )
        result = await runner.run()
        payload = {
            "outputPath": str(result.output_path),
            "outputPaths": [str(path) for path in result.output_paths],
            "totalCount": result.total_count,
            "inputCount": result.input_count,
            "skippedCount": result.skipped_count,
            "pageCount": result.page_count,
            "startedAt": result.started_at,
            "finishedAt": result.finished_at,
            "exportFormat": result.export_format,
            "translationRequestedCount": result.translation_requested_count,
            "translationFilledCount": result.translation_filled_count,
            "translationFailureCount": result.translation_failure_count,
        }
        context.outputs = list(payload["outputPaths"])
        context.update_stats(
            totalCount=result.total_count,
            inputCount=result.input_count,
            skippedCount=result.skipped_count,
            pageCount=result.page_count,
        )
        context.set_progress(result.total_count, result.total_count, "今日台词")
        context.set_status("finished")
        context.append_log("今日台词采集完成")
        return payload
    except asyncio.CancelledError:
        context.set_status("aborted")
        context.append_log("今日台词任务已中止")
        raise
    except Exception as exc:  # noqa: BLE001
        context.set_status("error", error=str(exc))
        context.append_log(f"今日台词采集失败：{exc}")
        raise


# 执行经典台词全量采集
async def run_classic_lines(
    context: TaskContext,
    data_dir: Path,
    unicloud_import_format: bool,
    concurrency: int = 8,
    max_pages: int | None = None,
) -> dict[str, Any]:
    context.reset()
    context.set_status("running")
    try:
        options = ClassicLinesAutomationOptions(
            data_dir=data_dir,
            unicloud_import_format=unicloud_import_format,
            request_delay_seconds=0.0,
            concurrency=max(1, min(12, int(concurrency))),
            max_pages=max_pages,
            headless=True,
        )
        runner = ClassicLinesAutomationRunner(
            options,
            log=context.append_log,
            progress=lambda current, total, item: _progress(context, current, total, item),
        )
        result = await runner.run()
        payload = result.to_dict()
        context.outputs = list(payload["outputPaths"])
        context.update_stats(
            totalMovies=result.total_movies,
            failedMovies=result.failed_movies,
            totalLines=result.total_lines,
            pageCount=result.page_count,
        )
        context.set_progress(result.total_movies, result.total_movies, "经典台词")
        context.set_status("finished")
        context.append_log("经典台词采集完成")
        return payload
    except asyncio.CancelledError:
        context.set_status("aborted")
        context.append_log("经典台词任务已中止")
        raise
    except Exception as exc:  # noqa: BLE001
        context.set_status("error", error=str(exc))
        context.append_log(f"经典台词采集失败：{exc}")
        raise
