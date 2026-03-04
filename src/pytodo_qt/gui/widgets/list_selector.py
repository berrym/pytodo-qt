"""list_selector.py

Widget for selecting and managing to-do lists.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap, QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QWidget,
)

from ...core.logger import Logger
from ...core.models import Database, TodoList
from ..styles.themes import get_colors

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class ListSelectorWidget(QWidget):
    """Widget for selecting and managing to-do lists."""

    # Signals
    list_changed = pyqtSignal(object)  # Emits TodoList or None
    add_list_requested = pyqtSignal()
    delete_list_requested = pyqtSignal()
    rename_list_requested = pyqtSignal()
    toggle_private_requested = pyqtSignal()
    sync_settings_requested = pyqtSignal()  # Open sync settings for current list

    def __init__(self, parent=None):
        super().__init__(parent)
        self._database: Database | None = None
        self._updating = False  # Prevent signal loops
        self._unseen_list_ids: set[UUID] = set()

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the widget UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Load lock icon
        self._lock_icon = self._load_icon("lock.svg")

        # Label
        layout.addWidget(QLabel("List:"))

        # Combo box for list selection
        self.combo = QComboBox()
        self.combo.setMinimumWidth(200)
        self.combo.currentIndexChanged.connect(self._on_selection_changed)
        self.combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.combo.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.combo, 1)

        # Add button
        self.add_btn = QPushButton("+")
        self.add_btn.setMaximumWidth(30)
        self.add_btn.setToolTip("Add new list")
        self.add_btn.clicked.connect(self.add_list_requested.emit)
        layout.addWidget(self.add_btn)

        # Delete button
        self.delete_btn = QPushButton("-")
        self.delete_btn.setMaximumWidth(30)
        self.delete_btn.setToolTip("Delete current list")
        self.delete_btn.clicked.connect(self.delete_list_requested.emit)
        layout.addWidget(self.delete_btn)

        # Rename button
        self.rename_btn = QPushButton("✎")
        self.rename_btn.setMaximumWidth(30)
        self.rename_btn.setToolTip("Rename current list")
        self.rename_btn.clicked.connect(self.rename_list_requested.emit)
        layout.addWidget(self.rename_btn)

    def set_database(self, database: Database) -> None:
        """Set the database and refresh the list."""
        self._database = database
        self.refresh()

    def set_unseen(self, list_ids: set[UUID]) -> None:
        """Update which lists have unviewed sync changes."""
        self._unseen_list_ids = list_ids
        self._apply_unseen_styling()

    def refresh(self) -> None:
        """Refresh the combo box with current lists."""
        self._updating = True
        try:
            self.combo.clear()

            if self._database is None:
                return

            # Add all non-deleted lists
            current_idx = 0
            for i, lst in enumerate(self._database.active_lists()):
                if lst.private:
                    self.combo.addItem(self._lock_icon, lst.name, lst.id)
                else:
                    self.combo.addItem(lst.name, lst.id)
                if lst.id == self._database.active_list_id:
                    current_idx = i

            # Select the active list
            if self.combo.count() > 0:
                self.combo.setCurrentIndex(current_idx)

            # Update button states
            has_lists = self.combo.count() > 0
            self.delete_btn.setEnabled(has_lists)
            self.rename_btn.setEnabled(has_lists)

            # Apply unseen indicators after rebuilding items
            self._apply_unseen_styling()

        finally:
            self._updating = False

    def get_current_list(self) -> TodoList | None:
        """Get the currently selected list."""
        if self._database is None:
            return None

        idx = self.combo.currentIndex()
        if idx < 0:
            return None

        list_id = self.combo.itemData(idx)
        if list_id is None:
            return None

        return self._database.get_list(list_id)

    def get_current_list_id(self) -> UUID | None:
        """Get the ID of the currently selected list."""
        idx = self.combo.currentIndex()
        if idx < 0:
            return None
        return self.combo.itemData(idx)

    def set_current_list(self, list_id: UUID) -> bool:
        """Set the current list by ID."""
        for i in range(self.combo.count()):
            if self.combo.itemData(i) == list_id:
                self.combo.setCurrentIndex(i)
                return True
        return False

    def set_current_by_index(self, index: int) -> bool:
        """Set the current list by combo box index (0-based)."""
        if 0 <= index < self.combo.count():
            self.combo.setCurrentIndex(index)
            return True
        return False

    def cycle_list(self, direction: int) -> None:
        """Cycle to the next (direction=1) or previous (direction=-1) list."""
        count = self.combo.count()
        if count <= 1:
            return
        new_index = (self.combo.currentIndex() + direction) % count
        self.combo.setCurrentIndex(new_index)

    def _on_selection_changed(self, index: int) -> None:
        """Handle selection change in combo box."""
        if self._updating:
            return

        if index < 0 or self._database is None:
            self.list_changed.emit(None)
            return

        list_id = self.combo.itemData(index)
        if list_id is not None:
            self._database.set_active_list(list_id)
            lst = self._database.get_list(list_id)
            self.list_changed.emit(lst)
            logger.log.info("Switched to list: %s", lst.name if lst else "None")

    def _apply_unseen_styling(self) -> None:
        """Apply visual indicators for lists with unviewed sync changes."""
        colors = get_colors()
        highlight = colors["highlight"]

        # Widget-level: colored border when any unseen changes exist
        if self._unseen_list_ids:
            self.combo.setStyleSheet(f"QComboBox {{ border: 2px solid {highlight}; }}")
        else:
            self.combo.setStyleSheet("")

        # Per-item: dot icon and text color for individual unseen lists
        model = self.combo.model()
        if not isinstance(model, QStandardItemModel):
            return

        dot_icon = self._make_dot_icon(highlight)
        accent_brush = QBrush(QColor(highlight))

        for i in range(model.rowCount()):
            item = model.item(i)
            if item is None:
                continue
            list_id = self.combo.itemData(i)
            if list_id in self._unseen_list_ids:
                item.setForeground(accent_brush)
                # Only set dot icon for non-private lists (private keep their lock)
                if not item.icon().isNull():
                    pass  # Keep existing lock icon
                else:
                    item.setIcon(dot_icon)
            else:
                # Clear previously applied unseen styling
                item.setForeground(QBrush())
                # Remove dot icon; private lists keep their lock
                if self._database:
                    lst = self._database.get_list(list_id)
                    if not lst or not lst.private:
                        item.setIcon(QIcon())

    def _make_dot_icon(self, color: str) -> QIcon:
        """Generate a notification dot icon using the given theme color."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(3, 3, 10, 10)
        painter.end()
        icon = QIcon()
        for mode in (
            QIcon.Mode.Normal,
            QIcon.Mode.Active,
            QIcon.Mode.Disabled,
            QIcon.Mode.Selected,
        ):
            icon.addPixmap(pixmap, mode)
        return icon

    def _load_icon(self, name: str) -> QIcon:
        """Load an icon from the icons directory."""
        icon_dir = Path(__file__).parent.parent / "icons"
        icon_path = icon_dir / name
        if not icon_path.exists():
            return QIcon()

        if name.endswith(".svg"):
            pixmap = QPixmap(str(icon_path))
            icon = QIcon()
            for mode in (
                QIcon.Mode.Normal,
                QIcon.Mode.Active,
                QIcon.Mode.Disabled,
                QIcon.Mode.Selected,
            ):
                icon.addPixmap(pixmap, mode)
            return icon
        return QIcon(str(icon_path))

    def _show_context_menu(self, position) -> None:
        """Show context menu for list operations."""
        current_list = self.get_current_list()
        if current_list is None:
            return

        menu = QMenu(self)

        # Sync settings
        menu.addAction("Sync Settings...", self.sync_settings_requested.emit)

        menu.addSeparator()

        # Private/Shared toggle
        if current_list.private:
            action = menu.addAction(self._lock_icon, "Make Shared")
        else:
            action = menu.addAction(self._lock_icon, "Make Private")
        if action:
            action.triggered.connect(self.toggle_private_requested.emit)

        menu.addSeparator()
        menu.addAction("Rename...", self.rename_list_requested.emit)
        menu.addAction("Delete...", self.delete_list_requested.emit)

        menu.exec(self.combo.mapToGlobal(position))
