from __future__ import annotations

from types import SimpleNamespace

import pytest

from subtitle_info_collection.web import updater as updater_module
from subtitle_info_collection.web.updater import (
    RUN_MODE_INSTALLED,
    RUN_MODE_ONEDIR,
    RUN_MODE_PORTABLE,
    RUN_MODE_SOURCE,
    UpdateService,
    detect_run_mode,
)


class FakeManager:
    def __init__(self, info=None, error: Exception | None = None) -> None:
        self.info = info
        self.error = error
        self.downloaded = None
        self.applied = None

    def check_for_updates(self):
        if self.error:
            raise self.error
        return self.info

    def download_updates(self, info, callback):
        self.downloaded = info
        callback(SimpleNamespace(Percent=0.42))
        callback(SimpleNamespace(Percent=100))

    def apply_updates_and_restart(self, info):
        self.applied = info


def make_info(version: str = "0.3.0") -> SimpleNamespace:
    release = SimpleNamespace(Version=version, NotesMarkdown="更新说明")
    return SimpleNamespace(TargetFullRelease=release)


def test_check_reports_available_release(monkeypatch):
    manager = FakeManager(make_info())
    service = UpdateService("0.2.0", run_mode=RUN_MODE_PORTABLE)
    monkeypatch.setattr(service, "_get_manager", lambda: manager)

    state = service.check()

    assert state["status"] == "available"
    assert state["available"] is True
    assert state["latestVersion"] == "0.3.0"
    assert state["notes"] == "更新说明"


def test_check_reports_latest_when_no_release(monkeypatch):
    service = UpdateService("0.2.0", run_mode=RUN_MODE_PORTABLE)
    monkeypatch.setattr(service, "_get_manager", lambda: FakeManager(None))

    state = service.check()

    assert state["status"] == "latest"
    assert state["available"] is False
    assert state["latestVersion"] == "0.2.0"


@pytest.mark.parametrize(
    ("run_mode", "expected_note"),
    [
        (RUN_MODE_SOURCE, "源码开发模式"),
        (RUN_MODE_ONEDIR, "便携目录原始产物"),
    ],
)
def test_check_reports_unsupported_for_non_updateable_modes(run_mode, expected_note):
    service = UpdateService("0.2.0", run_mode=run_mode)

    state = service.check()

    assert state["status"] == "unsupported"
    assert state["available"] is False
    assert expected_note in state["error"]


def test_check_reports_error(monkeypatch):
    service = UpdateService("0.2.0", run_mode=RUN_MODE_PORTABLE)
    monkeypatch.setattr(
        service,
        "_get_manager",
        lambda: FakeManager(error=RuntimeError("断网")),
    )

    state = service.check()

    assert state["status"] == "error"
    assert "断网" in state["error"]


def test_download_requires_check_first():
    service = UpdateService("0.2.0", run_mode=RUN_MODE_PORTABLE)

    with pytest.raises(RuntimeError, match="请先检查更新"):
        service.download()


def test_download_rejected_on_non_updateable_mode():
    service = UpdateService("0.2.0", run_mode=RUN_MODE_ONEDIR)

    with pytest.raises(RuntimeError, match="不支持自更新"):
        service.download()


def test_manifest_error_is_translated_to_chinese_hint():
    service = UpdateService("0.2.0", run_mode=RUN_MODE_PORTABLE)

    message = service._describe_error(
        RuntimeError(
            "This application is not properly installed: Could not auto-locate app manifest"
        )
    )

    assert "sq.version" in message
    assert "Portable.zip" in message


def test_download_and_apply_updates(monkeypatch):
    manager = FakeManager(make_info())
    service = UpdateService("0.2.0", run_mode=RUN_MODE_PORTABLE)
    monkeypatch.setattr(service, "_get_manager", lambda: manager)
    service.check()

    service.download()
    service.apply_and_restart()

    assert manager.downloaded is not None
    assert manager.applied is manager.downloaded
    assert service.state()["status"] == "restarting"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((), 0),
        ((SimpleNamespace(Percent=0.42),), 42),
        ((SimpleNamespace(Percent=100),), 100),
        (({"percent": 0.5},), 50),
        ((3, 4), 75),
        ((150,), 100),
        (("bad",), 0),
    ],
)
def test_parse_progress_supports_velopack_shapes(args, expected):
    assert UpdateService._parse_progress(args) == expected


def test_detect_run_mode_returns_source_when_not_frozen(monkeypatch):
    monkeypatch.setattr(updater_module.sys, "frozen", False, raising=False)

    assert detect_run_mode() == RUN_MODE_SOURCE


def test_detect_run_mode_detects_onedir_without_manifest(monkeypatch, tmp_path):
    exe_dir = tmp_path / "portable"
    exe_dir.mkdir()
    exe_path = exe_dir / "字幕采集工具.exe"
    exe_path.write_bytes(b"")
    monkeypatch.setattr(updater_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater_module.sys, "executable", str(exe_path))

    assert detect_run_mode() == RUN_MODE_ONEDIR


def test_detect_run_mode_detects_portable_with_marker(monkeypatch, tmp_path):
    root = tmp_path / "portable"
    exe_dir = root / "current"
    exe_dir.mkdir(parents=True)
    exe_path = exe_dir / "字幕采集工具.exe"
    exe_path.write_bytes(b"")
    (exe_dir / "sq.version").write_text("<package />", encoding="utf-8")
    (root / ".portable").write_text("", encoding="utf-8")
    monkeypatch.setattr(updater_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater_module.sys, "executable", str(exe_path))

    assert detect_run_mode() == RUN_MODE_PORTABLE


def test_detect_run_mode_detects_installed_without_marker(monkeypatch, tmp_path):
    exe_dir = tmp_path / "SubtitleInfoCollection" / "current"
    exe_dir.mkdir(parents=True)
    exe_path = exe_dir / "字幕采集工具.exe"
    exe_path.write_bytes(b"")
    (exe_dir / "sq.version").write_text("<package />", encoding="utf-8")
    monkeypatch.setattr(updater_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater_module.sys, "executable", str(exe_path))

    assert detect_run_mode() == RUN_MODE_INSTALLED


def test_service_disables_updates_for_onedir_mode():
    service = UpdateService("0.2.0", run_mode=RUN_MODE_ONEDIR)

    assert service.enabled is False
