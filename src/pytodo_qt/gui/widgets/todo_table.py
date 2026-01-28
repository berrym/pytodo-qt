"""todo_table.py

Table widget for displaying and editing to-do items.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QLineEdit,
    QTableWidget,
)

from ...core.logger import Logger
from ...core.models import TodoList
from ..styles.themes import get_colors

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class TodoTableWidget(QTableWidget):
    """Table widget for displaying and editing to-do items."""

    # Signals
    item_priority_changed = pyqtSignal(object, int)  # (item_id, new_priority)
    item_reminder_changed = pyqtSignal(object, str)  # (item_id, new_text)
    item_selected = pyqtSignal(object)  # (item_id or None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_list: TodoList | None = None
        self._item_id_map: dict[int, UUID] = {}  # row -> item_id

        # Setup table
        self._setup_table()

        # Fonts
        self._normal_font = QFont("Helvetica", 12)
        self._completed_font = QFont("Helvetica", 12)
        self._completed_font.setBold(True)
        self._completed_font.setStrikeOut(True)

    def _setup_table(self) -> None:
        """Configure the table widget."""
        # Columns: Priority, Reminder
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels(["Priority", "Reminder"])

        # Stretch the reminder column
        header = self.horizontalHeader()
        if header:
            header.setStretchLastSection(True)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)

        # Set row height so text is readable
        v_header = self.verticalHeader()
        if v_header:
            v_header.setDefaultSectionSize(36)

        # Selection behavior
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Tooltips
        self.setToolTip("Your to-do list")

        # Alternating row colors
        self.setAlternatingRowColors(True)

        # Connect selection changed
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def set_list(self, todo_list: TodoList | None) -> None:
        """Set the list to display."""
        self._current_list = todo_list
        self.refresh()

    def refresh(self) -> None:
        """Refresh the table contents."""
        self.setRowCount(0)
        self._item_id_map.clear()

        if self._current_list is None:
            return

        colors = get_colors()

        # Sort items by priority, then by reminder
        items = sorted(
            self._current_list.active_items(), key=lambda x: (x.priority, x.reminder.lower())
        )

        for row, item in enumerate(items):
            self.insertRow(row)
            self.setRowHeight(row, 36)
            self._item_id_map[row] = item.id

            # Priority combo box
            priority_combo = QComboBox()
            priority_combo.setMinimumHeight(32)
            priority_combo.addItems(["Low", "Normal", "High"])
            priority_combo.setCurrentIndex(
                2 - item.priority + 1
            )  # 1=High->2, 2=Normal->1, 3=Low->0
            priority_combo.currentIndexChanged.connect(
                lambda idx, r=row: self._on_priority_changed(r, idx)
            )

            # Set priority color
            if item.priority == 1:
                priority_combo.setStyleSheet(f"color: {colors['priority_high']};")
            elif item.priority == 2:
                priority_combo.setStyleSheet(f"color: {colors['priority_normal']};")
            else:
                priority_combo.setStyleSheet(f"color: {colors['priority_low']};")

            self.setCellWidget(row, 0, priority_combo)

            # Reminder text field
            reminder_edit = QLineEdit(item.reminder)
            reminder_edit.setMinimumHeight(32)
            reminder_edit.returnPressed.connect(lambda r=row: self._on_reminder_changed(r))

            # Style based on completion status
            if item.complete:
                reminder_edit.setFont(self._completed_font)
                reminder_edit.setStyleSheet(
                    f"color: {colors['completed_text']}; "
                    f"background-color: {colors['completed_bg']};"
                )
            else:
                reminder_edit.setFont(self._normal_font)

            self.setCellWidget(row, 1, reminder_edit)

        # Resize rows to fit widget contents
        self.resizeRowsToContents()

        logger.log.info("Refreshed table with %d items", len(items))

    def get_selected_item_ids(self) -> list[UUID]:
        """Get IDs of selected items."""
        ids = []
        for row in {index.row() for index in self.selectedIndexes()}:
            if row in self._item_id_map:
                ids.append(self._item_id_map[row])
        return ids

    def get_item_id_at_row(self, row: int) -> UUID | None:
        """Get item ID for a specific row."""
        return self._item_id_map.get(row)

    def _on_priority_changed(self, row: int, combo_index: int) -> None:
        """Handle priority combo box change."""
        item_id = self._item_id_map.get(row)
        if item_id is None:
            return

        # Convert combo index to priority (0=Low->3, 1=Normal->2, 2=High->1)
        priority = 3 - combo_index
        self.item_priority_changed.emit(item_id, priority)

    def _on_reminder_changed(self, row: int) -> None:
        """Handle reminder text change."""
        item_id = self._item_id_map.get(row)
        if item_id is None:
            return

        reminder_edit = self.cellWidget(row, 1)
        if isinstance(reminder_edit, QLineEdit):
            self.item_reminder_changed.emit(item_id, reminder_edit.text())

    def _on_selection_changed(self) -> None:
        """Handle selection change."""
        selected = self.get_selected_item_ids()
        if len(selected) == 1:
            self.item_selected.emit(selected[0])
        else:
            self.item_selected.emit(None)
