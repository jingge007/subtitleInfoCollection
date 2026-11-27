from __future__ import annotations

from subtitle_info_collection.web.tasks import TaskContext


def test_update_stats_accepts_keyword_values():
    context = TaskContext("test")

    context.update_stats(totalCount=12, skippedCount=2)

    assert context.snapshot()["stats"] == {"totalCount": 12, "skippedCount": 2}


def test_progress_snapshot_never_reports_total_below_current():
    context = TaskContext("test")

    context.set_progress(272, 250, "第 6 页")
    snapshot = context.snapshot()

    assert snapshot["current"] == 272
    assert snapshot["total"] == 272
