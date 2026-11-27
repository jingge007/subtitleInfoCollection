from __future__ import annotations

from types import SimpleNamespace

import pytest

from subtitle_info_collection.web.updater import UpdateService


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
    service = UpdateService("0.2.0")
    monkeypatch.setattr(service, "_get_manager", lambda: manager)

    state = service.check()

    assert state["status"] == "available"
    assert state["available"] is True
    assert state["latestVersion"] == "0.3.0"
    assert state["notes"] == "更新说明"


def test_check_reports_latest_when_no_release(monkeypatch):
    service = UpdateService("0.2.0")
    monkeypatch.setattr(service, "_get_manager", lambda: FakeManager(None))

    state = service.check()

    assert state["status"] == "latest"
    assert state["available"] is False
    assert state["latestVersion"] == "0.2.0"


def test_check_skips_network_in_source_mode():
    service = UpdateService("0.2.0", enabled=False)

    state = service.check()

    assert state["status"] == "latest"
    assert state["available"] is False
    assert "源码开发模式" in state["notes"]


def test_check_reports_error(monkeypatch):
    service = UpdateService("0.2.0")
    monkeypatch.setattr(
        service,
        "_get_manager",
        lambda: FakeManager(error=RuntimeError("断网")),
    )

    state = service.check()

    assert state["status"] == "error"
    assert "断网" in state["error"]


def test_download_requires_check_first():
    service = UpdateService("0.2.0")

    with pytest.raises(RuntimeError, match="请先检查更新"):
        service.download()


def test_download_and_apply_updates(monkeypatch):
    manager = FakeManager(make_info())
    service = UpdateService("0.2.0")
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
