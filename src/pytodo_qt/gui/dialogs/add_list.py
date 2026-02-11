"""add_list.py

Dialog for adding a new todo list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ...core.logger import Logger
from ...core.models import TodoList, create_todo_list

if TYPE_CHECKING:
    from ...core.models import Database


logger = Logger(__name__)


class AddListDialog(QDialog):
    """Dialog for adding a new todo list."""

    def __init__(self, parent=None, database: Database | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add List")
        self.setMinimumWidth(350)

        self._database = database
        self._list: TodoList | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Form layout
        form = QFormLayout()

        # Name input
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Enter list name...")
        form.addRow("Name:", self.name_edit)

        # Private checkbox
        self.private_checkbox = QCheckBox("Private (won't sync)")
        form.addRow("", self.private_checkbox)

        layout.addLayout(form)

        # Button box
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Focus name field
        self.name_edit.setFocus()

    def _on_accept(self) -> None:
        """Handle OK button."""
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Please enter a list name.")
            self.name_edit.setFocus()
            return

        if self._database and self._database.get_list_by_name(name):
            QMessageBox.warning(self, "Duplicate", f'A list named "{name}" already exists.')
            self.name_edit.setFocus()
            return

        new_list = create_todo_list(name)
        if self.private_checkbox.isChecked():
            new_list.private = True
        self._list = new_list
        logger.log.info("Created new list: %s (private=%s)", name, new_list.private)
        self.accept()

    def get_list(self) -> TodoList | None:
        """Get the created list, or None if cancelled."""
        return self._list

    @classmethod
    def create_list(cls, parent=None, database: Database | None = None) -> TodoList | None:
        """Convenience method to show dialog and get result."""
        dialog = cls(parent, database)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_list()
        return None
