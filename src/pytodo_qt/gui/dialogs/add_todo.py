"""add_todo.py

Dialog for adding a new to-do item.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ...core.logger import Logger
from ...core.models import TodoItem

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class AddTodoDialog(QDialog):
    """Dialog for adding a new to-do item."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add To-Do")
        self.setMinimumWidth(400)

        self._item: TodoItem | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Form layout
        form = QFormLayout()

        # Reminder input
        self.reminder_edit = QLineEdit()
        self.reminder_edit.setPlaceholderText("Enter reminder text...")
        form.addRow("Reminder:", self.reminder_edit)

        # Priority combo
        self.priority_combo = QComboBox()
        self.priority_combo.addItem("High", 1)
        self.priority_combo.addItem("Normal", 2)
        self.priority_combo.addItem("Low", 3)
        self.priority_combo.setCurrentIndex(1)  # Default to Normal
        form.addRow("Priority:", self.priority_combo)

        layout.addLayout(form)

        # Button box
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Focus reminder field
        self.reminder_edit.setFocus()

    def _on_accept(self) -> None:
        """Handle OK button."""
        reminder = self.reminder_edit.text().strip()
        if not reminder:
            QMessageBox.warning(self, "Validation Error", "Please enter a reminder.")
            self.reminder_edit.setFocus()
            return

        priority = self.priority_combo.currentData()
        self._item = TodoItem(reminder=reminder, priority=priority)
        logger.log.info("Created new todo item: %s", reminder[:50])
        self.accept()

    def get_item(self) -> TodoItem | None:
        """Get the created to-do item, or None if cancelled."""
        return self._item

    @classmethod
    def create_item(cls, parent=None) -> TodoItem | None:
        """Convenience method to show dialog and get result."""
        dialog = cls(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_item()
        return None
