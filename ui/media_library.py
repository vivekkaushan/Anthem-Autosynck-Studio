"""Left panel: media library grouped by recording session."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QInputDialog, QLabel, QMenu, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from app.state import ProjectState
from core.media.models import MediaKind
from ui import theme

ID_ROLE = Qt.UserRole + 1


class MediaLibrary(QWidget):
    selection_changed = Signal(str)  # media id or ""

    def __init__(self, state: ProjectState) -> None:
        super().__init__()
        self.state = state
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        head = QLabel("MEDIA LIBRARY")
        head.setObjectName("heading")
        lay.addWidget(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Role"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(lambda: self.selection_changed.emit(self.selected_id()))
        self.tree.setColumnWidth(0, 170)
        self.tree.header().setStretchLastSection(True)
        lay.addWidget(self.tree)
        state.media_changed.connect(self.refresh)
        self.refresh()

    def selected_id(self) -> str:
        items = self.tree.selectedItems()
        return (items[0].data(0, ID_ROLE) or "") if items else ""

    def refresh(self) -> None:
        keep = self.selected_id()
        self.tree.clear()
        sessions: dict[str, QTreeWidgetItem] = {}
        for m in self.state.media:
            parent = sessions.get(m.session)
            if parent is None:
                parent = QTreeWidgetItem([m.session, ""])
                parent.setFlags(Qt.ItemIsEnabled)
                parent.setForeground(0, QBrush(QColor(theme.TEXT_DIM)))
                self.tree.addTopLevelItem(parent)
                sessions[m.session] = parent
            label = ("★ " if m.is_master else "") + m.name
            it = QTreeWidgetItem([label, m.role + (" · MASTER" if m.is_master else "")])
            it.setData(0, ID_ROLE, m.id)
            it.setToolTip(0, m.path)
            if not m.exists:
                it.setForeground(0, QBrush(QColor(theme.RED)))
                it.setToolTip(0, f"MISSING: {m.path}")
            elif m.is_master:
                it.setForeground(1, QBrush(QColor(theme.ORANGE)))
            elif m.kind is MediaKind.VIDEO:
                it.setForeground(1, QBrush(QColor(theme.TEAL)))
            parent.addChild(it)
            if m.id == keep:
                it.setSelected(True)
        self.tree.expandAll()

    def _menu(self, pos) -> None:
        mid = self.selected_id()
        if not mid:
            return
        m = self.state.get(mid)
        if m is None:
            return
        menu = QMenu(self)
        a_ren = menu.addAction("Rename…")
        a_role = menu.addAction("Set Role…")
        a_sess = menu.addAction("Move to Group…")
        a_master = menu.addAction("Set as Master Audio") if m.kind is MediaKind.AUDIO else None
        menu.addSeparator()
        a_rm = menu.addAction("Remove from Project")
        act = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if act is a_ren:
            t, ok = QInputDialog.getText(self, "Rename", "Name:", text=m.name)
            if ok:
                self.state.rename(mid, t)
        elif act is a_role:
            t, ok = QInputDialog.getText(self, "Set Role", "Role (e.g. CAM 02, AUDIO 01):", text=m.role)
            if ok:
                self.state.set_role(mid, t)
        elif act is a_sess:
            t, ok = QInputDialog.getText(self, "Group", "Group / recording session:", text=m.session)
            if ok:
                self.state.set_session(mid, t)
        elif a_master is not None and act is a_master:
            self.state.set_master(mid)
        elif act is a_rm:
            self.state.remove(mid)
