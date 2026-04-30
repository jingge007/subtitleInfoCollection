from subtitle_info_collection.models import MovieInfo, SubtitleCandidate
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
