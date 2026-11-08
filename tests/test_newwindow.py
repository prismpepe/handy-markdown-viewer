import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mdviewer
import multiwin


def test_open_in_new_window_validates_and_launches(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    api = mdviewer.Api(None)
    launched = []
    monkeypatch.setattr(multiwin, "launch_self", lambda args: launched.append(list(args)) or True)
    md = tmp_path / "a.md"
    md.write_text("x", encoding="utf-8")
    exe = tmp_path / "evil.exe"
    exe.write_text("x", encoding="utf-8")
    assert api.open_in_new_window(str(md)) == {"error": None} and launched[-1] == [str(md)]
    assert api.open_in_new_window(str(tmp_path)) == {"error": None} and launched[-1] == [str(tmp_path)]
    assert api.open_in_new_window(None) == {"error": None} and launched[-1] == []
    n = len(launched)
    assert api.open_in_new_window(str(exe))["error"] and api.open_in_new_window(str(tmp_path / "none.md"))["error"]
    assert api.open_in_new_window(123)["error"]
    assert len(launched) == n                                    # Markdown ファイルとフォルダー以外は、起動しない
    monkeypatch.setattr(multiwin, "launch_self", lambda args: False)
    assert api.open_in_new_window(str(md))["error"]


def test_settings_are_written_atomically(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    mdviewer.save_settings({"a": 1})
    mdviewer.save_settings({"a": 2, "window": {"x": 1}})
    assert mdviewer.load_settings() == {"a": 2, "window": {"x": 1}}
    assert not [n for n in os.listdir(os.path.dirname(mdviewer.settings_path())) if n.endswith(".tmp")]
