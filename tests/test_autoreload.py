import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mdviewer
import uiprefs


def test_file_stamp_changes_with_content(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("one", encoding="utf-8")
    s1 = mdviewer.Api.file_stamp(str(p))
    assert isinstance(s1, list) and len(s1) == 2 and s1[1] == 3
    time.sleep(0.02)
    p.write_text("three", encoding="utf-8")
    s2 = mdviewer.Api.file_stamp(str(p))
    assert s2 != s1 and s2[1] == 5


def test_file_stamp_missing_or_bad_input(tmp_path):
    assert mdviewer.Api.file_stamp(str(tmp_path / "none.md")) is None
    assert mdviewer.Api.file_stamp(None) is None
    assert mdviewer.Api.file_stamp("a\0b") is None


def test_open_file_returns_stamp(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("# t", encoding="utf-8")
    api = mdviewer.Api(None)
    r = api.open_file(str(p))
    assert r["error"] is None and r["stamp"] == mdviewer.Api.file_stamp(str(p))


def test_auto_reload_pref_accepts_only_booleans():
    assert uiprefs.clean_prefs({"auto_reload": False}) == {"auto_reload": False}
    assert uiprefs.clean_prefs({"auto_reload": True}) == {"auto_reload": True}
    assert uiprefs.clean_prefs({"auto_reload": "no"}) == {}
    assert uiprefs.clean_prefs({"auto_reload": 0}) == {}
