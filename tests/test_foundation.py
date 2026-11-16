import json
from pathlib import Path

from app.config import Config
from app.dependencies import check_dependencies
from core.media.models import MediaKind, classify


def test_config_roundtrip(tmp_path: Path):
    p = tmp_path / "c.json"
    c = Config(analysis_sample_rate=8000)
    c.add_recent("/a"); c.add_recent("/b"); c.add_recent("/a")
    c.save(p)
    d = Config.load(p)
    assert d.analysis_sample_rate == 8000 and d.recent_projects == ["/a", "/b"]


def test_config_corrupt_is_backed_up_not_lost(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text("{not json")
    c = Config.load(p)
    assert c == Config()
    assert (tmp_path / "c.json.corrupt").exists()


def test_config_ignores_unknown_keys(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"future_key": 1, "autosave_interval_s": 30}))
    assert Config.load(p).autosave_interval_s == 30


def test_dependency_report_finds_tools():
    r = check_dependencies()
    assert not r.missing_packages
    assert r.python_ok
    assert r.ffmpeg and r.ffprobe, r.problems()


def test_dependency_report_reports_missing(monkeypatch, tmp_path):
    # Isolate from the machine: no PATH lookup, and an empty "bundled" third_party directory.
    monkeypatch.setattr("app.dependencies.shutil.which", lambda n: None)
    monkeypatch.setattr("app.dependencies.resource_root", lambda: tmp_path)
    r = check_dependencies("/nonexistent/ffmpeg", "/nonexistent/ffprobe")
    assert not r.ok and any("FFmpeg" in p for p in r.problems()) and any("FFprobe" in p for p in r.problems())


def test_bundled_ffmpeg_is_preferred_over_path(monkeypatch, tmp_path):
    import sys
    exe = ".exe" if sys.platform == "win32" else ""
    d = tmp_path / "third_party" / "ffmpeg"; d.mkdir(parents=True)
    for n in ("ffmpeg", "ffprobe"):
        (d / (n + exe)).write_bytes(b"x")
    monkeypatch.setattr("app.dependencies.resource_root", lambda: tmp_path)
    monkeypatch.setattr("app.dependencies.shutil.which", lambda n: "/usr/bin/" + n)
    from app.dependencies import find_binary
    assert find_binary("ffmpeg") == str(d / ("ffmpeg" + exe))


def test_classify():
    assert classify("a.MOV") is MediaKind.VIDEO
    assert classify("a.flac") is MediaKind.AUDIO
    assert classify("a.txt") is None
