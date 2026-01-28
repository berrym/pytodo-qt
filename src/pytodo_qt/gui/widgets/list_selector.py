"""list_selector.py

Widget for selecting and managing to-do lists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ...core.logger import Logger
from ...core.models import Database, TodoList

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._database: Database | None = None
        self._updating = False  # Prevent signal loops

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the widget UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Label
        layout.addWidget(QLabel("List:"))

        # Combo box for list selection
        self.combo = QComboBox()
        self.combo.setMinimumWidth(200)
        self.combo.currentIndexChanged.connect(self._on_selection_changed)
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
