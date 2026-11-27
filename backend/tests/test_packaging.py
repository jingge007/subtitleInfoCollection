from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_spec_targets_webui_and_has_no_pyside_dependency():
    spec = read_text(BACKEND / "字幕采集工具.spec")

    assert "PySide6" not in spec
    assert "frontend" in spec
    assert '"webui"' in spec
    assert ".env.example" in spec
    assert "webview" in spec
    assert "velopack" in spec
    assert '".env"' not in spec


def test_build_script_builds_frontend_and_velopack_assets():
    script = read_text(ROOT / "scripts" / "build_windows.ps1")

    assert "npm" in script
    assert '"run", "build"' in script
    assert "--packId" in script
    assert "releases.win.json" in script
    assert "PySide6" not in script


def test_powershell_scripts_use_utf8_bom():
    for path in (ROOT / "scripts").glob("*.ps1"):
        data = path.read_bytes()
        assert data.startswith(b"\xef\xbb\xbf"), f"{path.name} 缺少 UTF-8 BOM"


def test_env_file_is_ignored_but_example_is_tracked():
    ignore_text = read_text(ROOT / ".gitignore")

    assert ".env" in ignore_text
    assert "!.env.example" in ignore_text
