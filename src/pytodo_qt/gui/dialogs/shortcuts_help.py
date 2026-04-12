"""shortcuts_help.py

Dialog displaying all available keyboard shortcuts.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

# Shortcut definitions: (category, shortcut_key, description)
_SHORTCUTS: list[tuple[str, str, str]] = [
    # Items
    ("Items", "+", "Add new to-do"),
    ("Items", "-", "Delete selected to-do(s)"),
    ("Items", "%", "Toggle completion"),
    ("Items", "Ctrl+Shift+T", "Edit tags"),
    ("Items", "Ctrl+D", "Edit due date"),
    ("Items", "Ctrl+Shift+R", "Edit recurrence"),
    ("Items", "Ctrl+T", "Start focus session"),
    ("Items", "Ctrl+Space", "Pause/resume focus session"),
    ("Items", "Ctrl+.", "Stop focus session"),
    # Lists
    ("Lists", "Ctrl++", "Add new list"),
    ("Lists", "Ctrl+-", "Delete current list"),
    ("Lists", "Ctrl+R", "Rename current list"),
    ("Lists", "Ctrl+Shift+P", "Toggle list private/shared"),
    ("Lists", "Ctrl+1..9", "Switch to list by position"),
    ("Lists", "Ctrl+Left/Right", "Cycle through lists"),
    # Views
    ("Views", "Ctrl+Shift+B", "Cycle views (list/board/calendar)"),
    ("Views", "Ctrl+Shift+D", "Toggle task detail panel"),
    # Navigation
    ("Navigation", "Ctrl+F", "Focus search bar"),
    ("Navigation", "Escape", "Clear search / unfocus"),
    # Edit
    ("Edit", "Ctrl+Z", "Undo"),
    ("Edit", "Ctrl+Shift+Z", "Redo"),
    # Sync
    ("Sync", "F6", "Pull from remote"),
    ("Sync", "F7", "Push to remote"),
    ("Sync", "Ctrl+Shift+S", "Sync all trusted devices"),
    # Application
    ("Application", "Ctrl+I", "Import from .ics"),
    ("Application", "Ctrl+E", "Export list as .ics"),
    ("Application", "Ctrl+P", "Print"),
    ("Application", "Ctrl+Q", "Quit"),
    ("Application", "F1", "Show this help"),
]


class ShortcutsHelpDialog(QDialog):
    """Dialog listing all keyboard shortcuts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Keyboard Shortcuts"))
        self.setMinimumSize(450, 400)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(
            [self.tr("Category"), self.tr("Shortcut"), self.tr("Action")]
        )
        table.setRowCount(len(_SHORTCUTS))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setAlternatingRowColors(True)

        for row, (category, shortcut, description) in enumerate(_SHORTCUTS):
            cat_item = QTableWidgetItem(self.tr(category))
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, cat_item)

            key_item = QTableWidgetItem(shortcut)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 1, key_item)

            desc_item = QTableWidgetItem(self.tr(description))
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 2, desc_item)

        header = table.horizontalHeader()
        if header:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(table)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
