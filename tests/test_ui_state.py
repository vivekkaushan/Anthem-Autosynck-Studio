from app.config import Config
from app.dependencies import check_dependencies
from app.state import ProjectState
from core.media.models import MediaKind


def test_roles_and_rejections(tmp_path):
    s = ProjectState()
    files = []
    for n in ("a.mp4", "b.mov", "x.wav", "y.flac", "z.txt"):
        f = tmp_path / n; f.write_bytes(b"0"); files.append(str(f))
    added, rejected = s.add_files(files)
    assert [m.role for m in added] == ["CAM 01", "CAM 02", "AUDIO 01", "AUDIO 02"]
    assert rejected == [files[-1]]
    again, rej2 = s.add_files(files[:1])
    assert not again and rej2 == files[:1]  # duplicates rejected
    cams, rej3 = s.add_files([files[2]], force=MediaKind.VIDEO)
    assert not cams


def test_master_only_audio_and_exclusive(tmp_path):
    s = ProjectState()
    for n in ("a.mp4", "x.wav", "y.wav"):
        (tmp_path / n).write_bytes(b"0")
    added, _ = s.add_files([str(tmp_path / n) for n in ("a.mp4", "x.wav", "y.wav")])
    cam, a1, a2 = added
    assert not s.set_master(cam.id)
    assert s.set_master(a1.id) and s.set_master(a2.id)
    assert [m.is_master for m in added] == [False, False, True]


def test_main_window_builds_and_lanes(qapp, tmp_path):
    from ui.main_window import MainWindow
    w = MainWindow(Config(), check_dependencies())
    names = [a.text().replace("&&", "&") for a in w._actions]
    assert names == ["New Project", "Open Project", "Save Project", "Import Media", "Import Folder", "Add Camera", "Add Audio",
                     "Set Master Audio", "Analyze & Sync", "Cancel Analysis", "Manual Offset", "Preview Sync",
                     "Export Premiere XML"]
    for n in ("c1.mp4", "c2.mp4", "m.wav", "s.wav"):
        (tmp_path / n).write_bytes(b"0")
    added, _ = w.state.add_files([str(tmp_path / n) for n in ("c1.mp4", "c2.mp4", "m.wav", "s.wav")])
    w.state.set_master(added[3].id)
    assert w.timeline.lanes() == [("V1", "CAM 01"), ("V2", "CAM 02"), ("A1", "Master Audio"), ("A2", "AUDIO 01")]
    assert w.a_master.isEnabled()
    assert w.windowTitle().startswith("Untitled Project*")
    w.library.tree.topLevelItem(0).child(0).setSelected(True)
    assert w.inspector.fields["Role"].text() == "CAM 01"


def test_import_folder_keeps_structure(tmp_path):
    root = tmp_path / "Shoot"
    layout = {"Camera 1": ["clip10.mp4", "clip2.mp4", "sub/deep/clip3.mov", "._clip2.mp4", "notes.txt"],
              "Camera 2": ["a.mp4"], "Camera 3": ["b.mp4", "c.mp4"], "Audio 1": ["rec.wav"], "Recorder": ["z.wav"]}
    for g, files in layout.items():
        for f in files:
            p = root / g / f; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"0")
    s = ProjectState()
    added, rejected, groups = s.add_folder(str(root))
    assert groups == ["Audio 1", "Camera 1", "Camera 2", "Camera 3", "Recorder"]
    cam1 = [m for m in added if m.session == "Camera 1"]
    assert len(cam1) == 3                                     # hidden ._ file and .txt ignored, nested clip kept
    assert {m.role for m in cam1} == {"CAM 01"}               # one camera, one role
    assert [m.name for m in cam1] == ["clip2.mp4", "clip10.mp4", "clip3.mov"]    # natural sort
    assert {m.role for m in added if m.session == "Camera 3"} == {"CAM 03"}
    assert {m.role for m in added if m.session == "Audio 1"} == {"AUDIO 01"}
    assert {m.role for m in added if m.session == "Recorder"} == {"AUDIO 02"}   # un-numbered folder gets next free role
    from ui.timeline_view import TimelineView
    from app.config import Config
    lanes = [l for l in TimelineView(s).lanes()]
    assert [l[1] for l in lanes if l[0].startswith("V")] == ["CAM 01", "CAM 02", "CAM 03"]  # 6 clips, 3 tracks
