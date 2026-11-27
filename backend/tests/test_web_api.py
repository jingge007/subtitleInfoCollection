from __future__ import annotations

import os
import sys

import pytest

from subtitle_info_collection import __version__
from subtitle_info_collection.config import EnvBootstrapResult
from subtitle_info_collection.web import api as api_module
from subtitle_info_collection.web.api import AppApi


ENV_KEYS_TO_RESTORE = [
    "TMDB_TOKEN",
    "SUBTITLE_MOVIE_CONCURRENCY",
    "SUBTITLE_COLLECTION_DATA_DIR",
]


@pytest.fixture
def app(tmp_path, monkeypatch):
    """构造使用临时 .env 与数据目录的 AppApi。"""
    data_dir = tmp_path / "data"
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"SUBTITLE_COLLECTION_DATA_DIR={data_dir}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api_module,
        "bootstrap_env_file",
        lambda: EnvBootstrapResult(env_path=env_path, created=False),
    )

    before = {key: os.environ.get(key) for key in ENV_KEYS_TO_RESTORE}
    instance = AppApi()
    try:
        yield instance
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_app_info_reports_version_and_paths(app, tmp_path):
    info = app.app_info()

    assert info["version"] == __version__
    assert info["envPath"] == str(tmp_path / ".env")
    assert info["dataDir"] == str((tmp_path / "data").resolve())
    assert info["platform"] == sys.platform
    assert info["frozen"] is False


def test_config_list_marks_secrets_and_save_writes_env(app, tmp_path):
    groups = app.config_list()
    secrets = next(group for group in groups if group["key"] == "secrets")
    tmdb = next(field for field in secrets["fields"] if field["key"] == "TMDB_TOKEN")

    assert tmdb["secret"] is True
    assert tmdb["widget"] == "secret"

    app.config_save(
        {
            "TMDB_TOKEN": "test-token",
            "SUBTITLE_MOVIE_CONCURRENCY": "3",
        }
    )

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TMDB_TOKEN=test-token" in env_text
    assert "SUBTITLE_MOVIE_CONCURRENCY=3" in env_text
    assert app._settings.tmdb_token == "test-token"
    assert app._settings.movie_concurrency == 3


def test_history_list_and_reset(app):
    storage = app._storage()
    run_id = storage.create_task_run(2024, 10)
    storage.finish_task_run(
        run_id,
        "finished",
        {
            "movieCount": 2,
            "failedCount": 1,
            "downloadCount": 2,
            "downloadDir": "D:/output",
        },
    )

    result = app.history_list(page=1, page_size=10, keyword="2024")

    assert result["total"] == 1
    assert result["items"][0]["movieCount"] == 2
    assert result["items"][0]["failedCount"] == 1

    app.history_reset()
    assert app.history_list()["total"] == 0


def test_history_list_searches_and_paginates_in_storage(app):
    storage = app._storage()
    for index in range(5):
        run_id = storage.create_task_run(2020 + index, 10 + index)
        storage.finish_task_run(
            run_id,
            "finished",
            {
                "movieCount": index + 1,
                "failedCount": 0,
                "downloadCount": index + 1,
                "downloadDir": f"D:/output/{index}",
            },
        )

    first = app.history_list(page=1, page_size=2, keyword="2023")
    second = app.history_list(page=2, page_size=2, keyword="2023")

    assert first["total"] == 1
    assert first["items"][0]["year"] == 2023
    assert second["items"] == []


def test_history_maintenance_rejects_active_tasks(app):
    app._collector.set_status("running")

    with pytest.raises(RuntimeError, match="任务运行中"):
        app.history_reset()
    with pytest.raises(RuntimeError, match="任务运行中"):
        app.shell_delete_outputs()


def test_window_topmost_toggle(app):
    class FakeWindow:
        on_top = False

    app.bind_window(FakeWindow())

    assert app.app_set_always_on_top(True) is True
    assert app._window.on_top is True
    assert app.app_set_always_on_top(False) is False


def test_collector_verification_is_rejected_when_not_requested(app):
    assert app.collector_submit_verification("1234") is False
    assert app.collector_refresh_captcha() is False
    assert app.app_has_active_tasks() is False


def test_parser_start_requires_selected_files(app):
    with pytest.raises(ValueError, match="请先选择字幕文件"):
        app.parser_start({"files": []})


def test_parser_pick_files_uses_window_dialog(app, tmp_path):
    subtitle = tmp_path / "movie.srt"

    class FakeWindow:
        def create_file_dialog(self, *_args, **_kwargs):
            return [str(subtitle)]

    app.bind_window(FakeWindow())
    assert app.parser_pick_files() == [str(subtitle)]


def test_shell_delete_outputs_recreates_output_dir(app):
    data_dir = app._settings.data_dir
    output_dir = data_dir / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "old.srt").write_text("old", encoding="utf-8")

    assert app.shell_delete_outputs() is True

    assert output_dir.exists()
    assert list(output_dir.iterdir()) == []


def test_shell_open_path_rejects_missing_path(app, tmp_path):
    with pytest.raises(FileNotFoundError, match="路径不存在"):
        app.shell_open_path(str(tmp_path / "missing"))
