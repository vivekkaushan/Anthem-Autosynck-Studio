"""In-memory project state observed by the UI."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from pathlib import Path

from core.media.models import MediaItem, MediaKind, classify, natural_key, role_from_group


class ProjectState(QObject):
    changed = Signal()
    media_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.name = "Untitled Project"
        self.path: str | None = None
        self.dirty = False
        self.media: list[MediaItem] = []
        self.sync_results: dict = {}

    # -- helpers ---------------------------------------------------------
    def _next_role(self, kind: MediaKind) -> str:
        prefix = "CAM" if kind is MediaKind.VIDEO else "AUDIO"
        used = {m.role for m in self.media}
        n = 1
        while f"{prefix} {n:02d}" in used:
            n += 1
        return f"{prefix} {n:02d}"

    def _touch(self) -> None:
        self.dirty = True
        self.media_changed.emit()
        self.changed.emit()

    # -- mutations -------------------------------------------------------
    def reset(self) -> None:
        self.name, self.path, self.dirty, self.media = "Untitled Project", None, False, []
        self.sync_results = {}
        self.media_changed.emit()
        self.changed.emit()

    def add_files(self, paths: list[str], force: MediaKind | None = None, session: str | None = None,
                  role: str | None = None) -> tuple[list[MediaItem], list[str]]:
        """Add files; returns (added, rejected). Unsupported types and duplicates are rejected.

        `session` puts every file in one library group; `role` gives them all the same role
        (several clips of one camera share a track)."""
        added: list[MediaItem] = []
        rejected: list[str] = []
        known = {m.path for m in self.media}
        for p in paths:
            kind = classify(p)
            if kind is None or (force and kind is not force) or p in known:
                rejected.append(p)
                continue
            item = MediaItem(path=p, kind=kind, role=role or self._next_role(kind))
            if session:
                item.session = session
            self.media.append(item)
            known.add(p)
            added.append(item)
        if added:
            self._touch()
        return added, rejected

    def get(self, media_id: str) -> MediaItem | None:
        return next((m for m in self.media if m.id == media_id), None)

    def remove(self, media_id: str) -> None:
        self.media = [m for m in self.media if m.id != media_id]
        self.sync_results.pop(media_id, None)
        self._touch()

    def set_master(self, media_id: str) -> bool:
        item = self.get(media_id)
        if item is None or item.kind is not MediaKind.AUDIO:
            return False
        for m in self.media:
            m.is_master = m.id == media_id
        self._touch()
        return True

    def rename(self, media_id: str, name: str) -> None:
        if (m := self.get(media_id)) and name.strip():
            m.name = name.strip()
            self._touch()

    def set_role(self, media_id: str, role: str) -> None:
        if (m := self.get(media_id)) and role.strip():
            m.role = role.strip().upper()
            self._touch()

    def set_session(self, media_id: str, session: str) -> None:
        if (m := self.get(media_id)) and session.strip():
            m.session = session.strip()
            self._touch()

    def set_probe(self, media_id: str, result: object | None, error: str = "") -> None:
        if m := self.get(media_id):
            m.info, m.error = result, error
            self.media_changed.emit()
            self.changed.emit()

    def set_sync_results(self, results: dict) -> None:
        self.sync_results = dict(results)
        self.dirty = True
        self.changed.emit()

    def add_folder(self, root: str) -> tuple[list[MediaItem], list[str], list[str]]:
        """Import a folder, keeping its structure: each sub-folder (Camera 1, Camera 2, ...) is one group.

        Everything inside a sub-folder, at any depth, goes into that group and shares one role.
        Returns (added, rejected, group_names). Hidden files (e.g. macOS '._' files) are ignored.
        """
        base = Path(root)

        def media_in(files) -> list[Path]:
            return sorted((f for f in files if f.is_file() and not f.name.startswith(".") and classify(f)),
                          key=natural_key)

        groups: list[tuple[str, list[Path]]] = []
        loose = media_in(base.iterdir())
        if loose:
            groups.append((base.name, loose))
        for d in sorted((d for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")), key=natural_key):
            files = media_in(d.rglob("*"))
            if files:
                groups.append((d.name, files))
        added: list[MediaItem] = []
        rejected: list[str] = []
        for name, files in groups:
            for kind in (MediaKind.VIDEO, MediaKind.AUDIO):
                part = [str(f) for f in files if classify(f) is kind]
                if not part:
                    continue
                role = role_from_group(name, kind) or self._next_role(kind)
                a, r = self.add_files(part, session=name, role=role)
                added += a
                rejected += r
        return added, rejected, [g for g, _ in groups]
