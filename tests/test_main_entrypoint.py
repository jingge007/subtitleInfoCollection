from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

import pytest


def test_main_py_can_run_as_direct_packaged_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    fake_main_window = types.ModuleType("subtitle_info_collection.gui.main_window")

    def run_app(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    fake_main_window.run_app = run_app  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "subtitle_info_collection.gui.main_window", fake_main_window)
    monkeypatch.setattr(sys, "argv", ["subtitleInfoCollection.exe"])

    entrypoint = Path(__file__).resolve().parents[1] / "src" / "subtitle_info_collection" / "main.py"
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(entrypoint), run_name="__main__")

    assert exc_info.value.code == 0
    assert calls == [["subtitleInfoCollection.exe"]]
