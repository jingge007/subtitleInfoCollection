from subtitle_info_collection.models import MovieInfo, SubtitleCandidate
from subtitle_info_collection.orchestrator import get_run_paths
from subtitle_info_collection.storage import AppStorage


def test_storage_saves_task_movie_and_candidate(tmp_path):
    storage = AppStorage(tmp_path / "app.sqlite3")
    run_id = storage.create_task_run(2026, 5)
    storage.save_movie(MovieInfo(movie_id="tmdb-1", title="Example", year=2026))
    storage.save_candidate(
        SubtitleCandidate(
            provider="subhd",
            provider_subtitle_id="s1",
            movie_id="tmdb-1",
            movie_title="Example",
            subtitle_title="Example.简英双语.srt",
            subtitle_format="srt",
        )
    )
    storage.finish_task_run(run_id, "completed", {"bestCount": 1})
    rows = storage.list_task_runs()
    assert rows[0]["status"] == "completed"
    assert rows[0]["result"]["bestCount"] == 1


def test_storage_clears_task_runs_only(tmp_path):
    storage = AppStorage(tmp_path / "app.sqlite3")
    run_id = storage.create_task_run(2026, 5)
    storage.save_movie(MovieInfo(movie_id="tmdb-1", title="Example", year=2026))
    storage.save_candidate(
        SubtitleCandidate(
            provider="subhd",
            provider_subtitle_id="s1",
            movie_id="tmdb-1",
            movie_title="Example",
            subtitle_title="Example.简英双语.srt",
            subtitle_format="srt",
        )
    )
    storage.finish_task_run(run_id, "completed", {"bestCount": 1})

    storage.clear_task_runs()

    assert storage.list_task_runs() == []


def test_storage_returns_task_center_summary(tmp_path):
    storage = AppStorage(tmp_path / "app.sqlite3")
    run_id = storage.create_task_run(2026, 3)
    storage.finish_task_run(
        run_id,
        "completed",
        {
            "movieCount": 3,
            "bestCount": 2,
            "failedCount": 1,
            "downloadCount": 2,
            "subtitlePackagePath": "C:/data/output/subtitles.zip",
            "latestRecords": [
                {
                    "movieTitleZh": "示例电影",
                    "movieTitle": "Example Movie",
                    "provider": "subhd",
                    "subtitleTitle": "Example.简英双语.srt",
                    "totalScore": 98.5,
                }
            ],
            "sourceHealth": {"subhd": {"healthy": True}},
            "providerStats": {"subhd": {"hitCount": 2}},
        },
    )

    summary = storage.task_center_summary()

    assert summary["totals"]["runs"] == 1
    assert summary["totals"]["movies"] == 3
    assert summary["totals"]["best"] == 2
    assert summary["totals"]["failed"] == 1
    assert summary["totals"]["downloads"] == 2
    assert summary["latest_records"][0]["movieTitleZh"] == "示例电影"
    assert summary["recent_runs"][0]["status"] == "completed"
    assert summary["source_health"]["subhd"]["healthy"] is True


def test_run_paths_write_downloads_directly_in_task_output_dir(tmp_path):
    paths = get_run_paths(tmp_path, 2026, 10)

    assert paths.download_dir == paths.output_dir
    assert paths.download_dir.parent == tmp_path
