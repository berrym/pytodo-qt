"""todo_table.py

Table widget for displaying and editing to-do items.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.logger import Logger
from ...core.models import (
    TodoList,
    format_due_date,
    format_recurrence,
    is_due_this_week,
    is_due_today,
    is_overdue,
)
from ..styles.themes import get_colors, make_font
from .time_combo import TimeComboBox

if TYPE_CHECKING:
    from .search_filter import FilterState


logger = Logger(__name__)


class DueDatePickerDialog(QDialog):
    """Dialog for picking or clearing a due date and optional time."""

    def __init__(
        self,
        current_date: date | None,
        current_time: time | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Set Due Date")
        self._date = current_date
        self._time = current_time
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Date picker
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        if self._date:
            self.date_edit.setDate(QDate(self._date.year, self._date.month, self._date.day))
        else:
            self.date_edit.setDate(QDate.currentDate())
        layout.addWidget(self.date_edit)

        # Time picker with checkbox
        time_layout = QHBoxLayout()
        self.time_checkbox = QCheckBox("Set due time")
        self.time_checkbox.stateChanged.connect(self._on_time_toggled)
        time_layout.addWidget(self.time_checkbox)

        self.time_edit = TimeComboBox()
        self.time_edit.setEnabled(False)
        if self._time:
            self.time_edit.set_time(self._time)
            self.time_checkbox.setChecked(True)
        else:
            self.time_edit.default_to_next_hour()
        time_layout.addWidget(self.time_edit, 1)
        layout.addLayout(time_layout)

        # Buttons
        btn_layout = QHBoxLayout()

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _on_time_toggled(self, state: int) -> None:
        self.time_edit.setEnabled(state == Qt.CheckState.Checked.value)

    def _on_ok(self) -> None:
        qdate = self.date_edit.date()
        self._date = date(qdate.year(), qdate.month(), qdate.day())
        if self.time_checkbox.isChecked():
            self._time = self.time_edit.get_time()
        else:
            self._time = None
        self.accept()

    def _on_clear(self) -> None:
        self._date = None
        self._time = None
        self.accept()

    def get_date(self) -> date | None:
        return self._date

    def get_time(self) -> time | None:
        return self._time


class DueDateLabel(QWidget):
    """Clickable due date label that opens date picker on click."""

    date_changed = pyqtSignal(object)  # Emits date or None
    time_changed = pyqtSignal(object)  # Emits time or None

    def __init__(
        self,
        due_date: date | None,
        complete: bool = False,
        recurring: bool = False,
        due_time: time | None = None,
        time_format: str = "system",
        parent=None,
    ):
        super().__init__(parent)
        self._due_date = due_date
        self._due_time = due_time
        self._complete = complete
        self._recurring = recurring
        self._time_format = time_format
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)

        # Center icon + label as a group within the cell
        layout.addStretch()

        if self._recurring:
            icon_path = Path(__file__).parent.parent / "icons" / "repeat.svg"
            if icon_path.exists():
                icon_label = QLabel()
                pixmap = QPixmap(str(icon_path)).scaled(
                    14,
                    14,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                icon_label.setPixmap(pixmap)
                if self._complete:
                    opacity = QGraphicsOpacityEffect(icon_label)
                    opacity.setOpacity(0.4)
                    icon_label.setGraphicsEffect(opacity)
                layout.addWidget(icon_label)

        self.label = QLabel(
            format_due_date(self._due_date, self._complete, self._due_time, self._time_format)
        )
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.label)

        layout.addStretch()

        # Ensure the widget itself reports enough width for time-inclusive strings
        self.setMinimumWidth(180)

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        self._show_date_picker()

    def _show_date_picker(self) -> None:
        """Show date/time picker dialog."""
        dialog = DueDatePickerDialog(self._due_date, self._due_time, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_date = dialog.get_date()
            new_time = dialog.get_time()
            old_date = self._due_date
            old_time = self._due_time
            self._due_date = new_date
            self._due_time = new_time
            self.label.setText(
                format_due_date(self._due_date, self._complete, self._due_time, self._time_format)
            )
            if new_date != old_date:
                self.date_changed.emit(self._due_date)
            if new_time != old_time:
                self.time_changed.emit(self._due_time)


class TodoTableWidget(QTableWidget):
    """Table widget for displaying and editing to-do items."""

    # Signals
    item_priority_changed = pyqtSignal(object, int)  # (item_id, new_priority)
    item_reminder_changed = pyqtSignal(object, str)  # (item_id, new_text)
    item_due_date_changed = pyqtSignal(object, object)  # (item_id, new_date or None)
    item_due_time_changed = pyqtSignal(object, object)  # (item_id, new_time or None)
    item_selected = pyqtSignal(object)  # (item_id or None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_list: TodoList | None = None
        self._item_id_map: dict[int, UUID] = {}  # row -> item_id
        self._filter_state: FilterState | None = None

        # Setup table
        self._setup_table()

        # Fonts
        self._normal_font = make_font(12)
        self._completed_font = make_font(12)
        self._completed_font.setBold(True)
        self._completed_font.setStrikeOut(True)

    def _setup_table(self) -> None:
        """Configure the table widget."""
        # Columns: Priority, Reminder, Due
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(["Priority", "Reminder", "Due"])

        # Configure column sizes
        header = self.horizontalHeader()
        if header:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            # Set minimum width for Due column to fit "Overdue (99d)" or day names
            header.setMinimumSectionSize(80)
            self.setColumnWidth(2, 130)

        # Set row height so text is readable
        v_header = self.verticalHeader()
        if v_header:
            v_header.setDefaultSectionSize(42)

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

    def set_filter(self, filter_state: FilterState | None) -> None:
        """Set the current filter and refresh display."""
        self._filter_state = filter_state
        self.refresh()

    def _apply_filter(self, items: list) -> list:
        """Filter items based on current filter state."""
        if self._filter_state is None:
            return items
        filtered = items
        if self._filter_state.text:
            search = self._filter_state.text.lower()
            filtered = [
                i
                for i in filtered
                if search in i.reminder.lower() or any(search in tag.lower() for tag in i.tags)
            ]
        if self._filter_state.priority != 0:
            filtered = [i for i in filtered if i.priority == self._filter_state.priority]
        if self._filter_state.status == 1:
            filtered = [i for i in filtered if not i.complete]
        elif self._filter_state.status == 2:
            filtered = [i for i in filtered if i.complete]
        # Due date filters
        if self._filter_state.due_date == 1:  # Overdue
            filtered = [i for i in filtered if is_overdue(i.due_date, i.due_time)]
        elif self._filter_state.due_date == 2:  # Today
            filtered = [i for i in filtered if is_due_today(i.due_date)]
        elif self._filter_state.due_date == 3:  # This Week
            filtered = [i for i in filtered if is_due_this_week(i.due_date)]
        elif self._filter_state.due_date == 4:  # No Due Date
            filtered = [i for i in filtered if i.due_date is None]
        elif self._filter_state.due_date == 5:  # Recurring
            filtered = [i for i in filtered if i.is_recurring]
        # Tag filter
        if self._filter_state.tag:
            filtered = [i for i in filtered if self._filter_state.tag in i.tags]
        return filtered

    def refresh(self) -> None:
        """Refresh the table contents."""
        self.setRowCount(0)
        self._item_id_map.clear()

        if self._current_list is None:
            return

        colors = get_colors()

        # Sort items: items with due dates first (by date/time, then priority), then items without
        def sort_key(item):
            if item.due_date is None:
                return (1, "", "", item.priority, item.reminder.lower())
            else:
                time_key = item.due_time.isoformat() if item.due_time else ""
                return (
                    0,
                    item.due_date.isoformat(),
                    time_key,
                    item.priority,
                    item.reminder.lower(),
                )

        items = sorted(self._current_list.active_items(), key=sort_key)

        # Apply filter if active
        if self._filter_state is not None and self._filter_state.is_active:
            items = self._apply_filter(items)

        # Load time format config once for all rows
        from ...core.config import ConfigManager

        time_fmt = ConfigManager().load().appearance.time_format

        for row, item in enumerate(items):
            self.insertRow(row)
            self.setRowHeight(row, 42)
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

            # Reminder column: text field + optional tag chips
            reminder_container = QWidget()
            reminder_layout = QHBoxLayout(reminder_container)
            reminder_layout.setContentsMargins(0, 0, 0, 0)
            reminder_layout.setSpacing(4)

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

            tooltip_parts = []
            if item.is_recurring:
                recurrence_text = format_recurrence(item)
                if recurrence_text:
                    tooltip_parts.append(recurrence_text)
            if item.tags:
                tooltip_parts.append(f"Tags: {', '.join(item.tags)}")
            if tooltip_parts:
                reminder_edit.setToolTip("\n".join(tooltip_parts))

            reminder_layout.addWidget(reminder_edit, 1)

            # Tag chips
            if item.tags:
                for tag in item.tags:
                    chip = QLabel(tag)
                    chip.setStyleSheet(
                        f"background-color: {colors['highlight']}; "
                        f"color: {colors.get('highlight_text', '#ffffff')}; "
                        "border-radius: 8px; padding: 1px 6px; font-size: 10px;"
                    )
                    chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                    reminder_layout.addWidget(chip)

            self.setCellWidget(row, 1, reminder_container)

            # Due date widget
            due_widget = DueDateLabel(
                item.due_date,
                item.complete,
                recurring=item.is_recurring,
                due_time=item.due_time,
                time_format=time_fmt,
            )
            due_widget.date_changed.connect(lambda d, r=row: self._on_due_date_changed(r, d))
            due_widget.time_changed.connect(lambda t, r=row: self._on_due_time_changed(r, t))

            # Apply styling based on due date status
            if not item.complete:
                if is_overdue(item.due_date, item.due_time):
                    due_widget.label.setStyleSheet(
                        f"color: {colors['due_overdue']}; font-weight: bold;"
                    )
                elif is_due_today(item.due_date):
                    due_widget.label.setStyleSheet(
                        f"color: {colors['due_today']}; font-weight: bold;"
                    )
                elif item.due_date and is_due_this_week(item.due_date):
                    due_widget.label.setStyleSheet(f"color: {colors['due_soon']};")
            elif item.due_date:
                due_widget.label.setStyleSheet(f"color: {colors['completed_text']};")

            self.setCellWidget(row, 2, due_widget)

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

        container = self.cellWidget(row, 1)
        if container is None:
            return
        reminder_edit = container.findChild(QLineEdit)
        if isinstance(reminder_edit, QLineEdit):
            self.item_reminder_changed.emit(item_id, reminder_edit.text())

    def _on_due_date_changed(self, row: int, due_date: date | None) -> None:
        """Handle due date change from inline picker."""
        item_id = self._item_id_map.get(row)
        if item_id is not None:
            self.item_due_date_changed.emit(item_id, due_date)

    def _on_due_time_changed(self, row: int, due_time: time | None) -> None:
        """Handle due time change from inline picker."""
        item_id = self._item_id_map.get(row)
        if item_id is not None:
            self.item_due_time_changed.emit(item_id, due_time)

    def _on_selection_changed(self) -> None:
        """Handle selection change."""
        selected = self.get_selected_item_ids()
        if len(selected) == 1:
            self.item_selected.emit(selected[0])
        else:
            self.item_selected.emit(None)
