from __future__ import annotations

from subtitle_info_collection.web import shell


def test_webui_url_carries_version_and_content_digest(tmp_path, monkeypatch):
    webui = tmp_path / "webui"
    webui.mkdir()
    index_path = webui / "index.html"
    index_path.write_text("<html>build-a</html>", encoding="utf-8")
    monkeypatch.setattr(shell, "_webui_dir", lambda: webui)

    first = shell._webui_url()

    assert first.startswith(str(index_path))
    assert "?v=" in first
    assert shell.__version__ in first

    # 同一份内容重复启动必须得到同一个缓存键
    assert shell._webui_url() == first

    # 重新打包导致内容变化时，缓存键必须跟着变化，绕开旧的缓存页面
    index_path.write_text("<html>build-b</html>", encoding="utf-8")
    assert shell._webui_url() != first
