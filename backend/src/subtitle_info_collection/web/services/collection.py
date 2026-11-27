from __future__ import annotations

from typing import Any

from ...config import AppSettings
from ...models import TaskConfig
from ...orchestrator import CollectionControl, SubtitleCollectionOrchestrator
from ...storage import AppStorage
from ..tasks import TaskContext


# 将前端采集参数与本地配置合并为领域任务配置
def build_task_config(settings: AppSettings, options: dict[str, Any]) -> TaskConfig:
    providers = options.get("providers")
    if not isinstance(providers, list) or not providers:
        providers = settings.provider_priority
    return TaskConfig(
        year=int(options.get("year") or 2026),
        limit=int(options.get("limit") or 100),
        subtitle_providers=[str(item) for item in providers],
        subtitle_min_bilingual_ratio=float(
            options.get("minBilingualRatio") or settings.subtitle_min_bilingual_ratio
        ),
        request_interval_ms=int(
            options.get("requestIntervalMs") or settings.request_interval_ms
        ),
        movie_concurrency=int(options.get("concurrency") or settings.movie_concurrency),
        output_root=settings.data_dir / "output",
        tmdb_token=settings.tmdb_token,
        assrt_token=settings.assrt_token,
        assrt_api_base_url=settings.assrt_api_base_url,
        assrt_site_base_url=settings.assrt_site_base_url,
        subdl_api_key=settings.subdl_api_key,
        subdl_base_url=settings.subdl_base_url,
        subdl_download_base_url=settings.subdl_download_base_url,
        subdl_languages=settings.subdl_languages,
        subdl_include_traditional=settings.subdl_include_traditional,
        opensubtitles_api_key=settings.opensubtitles_api_key,
        opensubtitles_username=settings.opensubtitles_username,
        opensubtitles_password=settings.opensubtitles_password,
        opensubtitles_base_url=settings.opensubtitles_base_url,
        opensubtitles_user_agent=settings.opensubtitles_user_agent,
        provider_priority=settings.provider_priority,
        provider_disabled=settings.provider_disabled,
        subhd_captcha_ocr_enabled=settings.subhd_captcha_ocr_enabled,
        subhd_captcha_auto_submit_min_confidence=(
            settings.subhd_captcha_auto_submit_min_confidence
        ),
        subhd_search_timeout=settings.subhd_search_timeout,
        provider_search_timeout=settings.provider_search_timeout,
        subhd_download_timeout=settings.subhd_download_timeout,
        provider_download_timeout=settings.provider_download_timeout,
        proxies=settings.proxies(),
    )


# 转发编排器进度到 Web 任务上下文
def _forward_progress(context: TaskContext, payload: dict[str, Any]) -> None:
    if "current" in payload:
        context.set_progress(
            int(payload.get("current") or 0),
            int(payload.get("total") or 0),
            str(payload.get("currentMovie") or ""),
        )
    stats: dict[str, Any] = {}
    if "movieCount" in payload:
        stats.update(
            movieCount=int(payload.get("movieCount") or 0),
            failedCount=int(payload.get("failedCount") or 0),
            downloadCount=int(payload.get("downloadCount") or 0),
        )
    download_dir = str(payload.get("downloadDir") or "").strip()
    if download_dir:
        stats["downloadDir"] = download_dir
    provider_stats = payload.get("providerStats")
    if isinstance(provider_stats, dict):
        stats["providerStats"] = provider_stats
    if stats:
        context.update_stats(**stats)


# 执行完整字幕采集流程并写回任务状态
async def run_collection(
    context: TaskContext,
    settings: AppSettings,
    storage: AppStorage,
    options: dict[str, Any],
    control: CollectionControl,
) -> None:
    context.reset()
    context.set_status("running")
    try:
        orchestrator = SubtitleCollectionOrchestrator(
            storage=storage,
            log=context.append_log,
            progress=lambda payload: _forward_progress(context, payload),
            request_verification=context.request_verification,
            control=control,
        )
        result = await orchestrator.run(build_task_config(settings, options))
        stats = {
            "movieCount": int(result.get("movieCount") or 0),
            "downloadCount": int(result.get("downloadCount") or 0),
            "failedCount": int(result.get("failedCount") or 0),
            "downloadDir": str(result.get("downloadDir") or ""),
        }
        context.update_stats(**stats)
        context.set_progress(
            int(result.get("movieCount") or 0),
            int(result.get("movieCount") or 0),
        )
        if control.is_aborted():
            context.set_status("aborted")
            context.append_log("采集已中止，已完成结果已保留")
        else:
            context.set_status("finished")
            context.append_log("采集完成")
    except Exception as exc:  # noqa: BLE001
        context.set_status("error", error=str(exc))
        context.append_log(f"采集失败：{exc}")
