"""add_todo.py

Dialog for adding a new to-do item.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.logger import Logger
from ...core.models import TodoItem
from ..widgets.time_combo import TimeComboBox

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
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

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

        # Due date with checkbox
        due_date_layout = QHBoxLayout()

        self.due_date_checkbox = QCheckBox("Set due date")
        self.due_date_checkbox.stateChanged.connect(self._on_due_date_toggled)

        self.due_date_edit = QDateEdit()
        self.due_date_edit.setCalendarPopup(True)
        self.due_date_edit.setDate(QDate.currentDate())
        self.due_date_edit.setEnabled(False)

        due_date_layout.addWidget(self.due_date_checkbox)
        due_date_layout.addWidget(self.due_date_edit, 1)
        form.addRow("Due Date:", due_date_layout)

        # Due time with checkbox
        due_time_layout = QHBoxLayout()

        self.due_time_checkbox = QCheckBox("Set due time")
        self.due_time_checkbox.setEnabled(False)
        self.due_time_checkbox.stateChanged.connect(self._on_due_time_toggled)

        self.due_time_edit = TimeComboBox()
        self.due_time_edit.setEnabled(False)
        self.due_time_edit.default_to_next_hour()

        due_time_layout.addWidget(self.due_time_checkbox)
        due_time_layout.addWidget(self.due_time_edit, 1)
        form.addRow("Due Time:", due_time_layout)

        # Recurrence section
        self.recurrence_checkbox = QCheckBox("Repeat")
        self.recurrence_checkbox.setEnabled(False)
        self.recurrence_checkbox.stateChanged.connect(self._on_recurrence_toggled)

        recurrence_layout = QHBoxLayout()
        recurrence_layout.addWidget(QLabel("Every"))

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 99)
        self.interval_spin.setValue(1)
        self.interval_spin.setEnabled(False)
        recurrence_layout.addWidget(self.interval_spin)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Day(s)", "daily")
        self.type_combo.addItem("Week(s)", "weekly")
        self.type_combo.addItem("Month(s)", "monthly")
        self.type_combo.addItem("Year(s)", "yearly")
        self.type_combo.setEnabled(False)
        recurrence_layout.addWidget(self.type_combo)

        recurrence_row = QWidget()
        recurrence_row_layout = QHBoxLayout(recurrence_row)
        recurrence_row_layout.setContentsMargins(0, 0, 0, 0)
        recurrence_row_layout.addWidget(self.recurrence_checkbox)
        recurrence_row_layout.addLayout(recurrence_layout)
        recurrence_row_layout.addStretch()
        form.addRow("Recurrence:", recurrence_row)

        # End condition
        self.end_never_radio = QRadioButton("Never")
        self.end_never_radio.setChecked(True)
        self.end_date_radio = QRadioButton("On date")
        self.end_count_radio = QRadioButton("After")

        end_group = QButtonGroup(self)
        end_group.addButton(self.end_never_radio)
        end_group.addButton(self.end_date_radio)
        end_group.addButton(self.end_count_radio)
        end_group.buttonClicked.connect(self._on_end_condition_changed)

        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QDate.currentDate().addMonths(3))
        self.end_date_edit.setEnabled(False)

        self.end_count_spin = QSpinBox()
        self.end_count_spin.setRange(1, 999)
        self.end_count_spin.setValue(10)
        self.end_count_spin.setEnabled(False)

        end_layout = QHBoxLayout()
        end_layout.addWidget(self.end_never_radio)
        end_layout.addWidget(self.end_date_radio)
        end_layout.addWidget(self.end_date_edit)
        end_layout.addWidget(self.end_count_radio)
        end_layout.addWidget(self.end_count_spin)
        end_layout.addWidget(QLabel("times"))
        end_layout.addStretch()

        self.end_widget = QWidget()
        self.end_widget.setLayout(end_layout)
        self.end_widget.setEnabled(False)
        form.addRow("Ends:", self.end_widget)

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

    def _on_due_date_toggled(self, state: int) -> None:
        """Handle due date checkbox toggle."""
        enabled = state == Qt.CheckState.Checked.value
        self.due_date_edit.setEnabled(enabled)
        self.due_time_checkbox.setEnabled(enabled)
        self.recurrence_checkbox.setEnabled(enabled)
        if not enabled:
            self.due_time_checkbox.setChecked(False)
            self.recurrence_checkbox.setChecked(False)

    def _on_due_time_toggled(self, state: int) -> None:
        """Handle due time checkbox toggle."""
        self.due_time_edit.setEnabled(state == Qt.CheckState.Checked.value)

    def _on_recurrence_toggled(self, state: int) -> None:
        """Handle recurrence checkbox toggle."""
        enabled = state == Qt.CheckState.Checked.value
        self.interval_spin.setEnabled(enabled)
        self.type_combo.setEnabled(enabled)
        self.end_widget.setEnabled(enabled)
        if not enabled:
            self.end_never_radio.setChecked(True)
            self.end_date_edit.setEnabled(False)
            self.end_count_spin.setEnabled(False)

    def _on_end_condition_changed(self) -> None:
        """Handle end condition radio button change."""
        self.end_date_edit.setEnabled(self.end_date_radio.isChecked())
        self.end_count_spin.setEnabled(self.end_count_radio.isChecked())

    def _on_accept(self) -> None:
        """Handle OK button."""
        reminder = self.reminder_edit.text().strip()
        if not reminder:
            QMessageBox.warning(self, "Validation Error", "Please enter a reminder.")
            self.reminder_edit.setFocus()
            return

        priority = self.priority_combo.currentData()

        due_date = None
        due_time = None
        if self.due_date_checkbox.isChecked():
            qdate = self.due_date_edit.date()
            due_date = date(qdate.year(), qdate.month(), qdate.day())
            if self.due_time_checkbox.isChecked():
                due_time = self.due_time_edit.get_time()

        recurrence_type = None
        recurrence_interval = 1
        recurrence_end_date = None
        recurrence_end_count = None

        if self.recurrence_checkbox.isChecked() and due_date is not None:
            recurrence_type = self.type_combo.currentData()
            recurrence_interval = self.interval_spin.value()
            if self.end_date_radio.isChecked():
                qd = self.end_date_edit.date()
                recurrence_end_date = date(qd.year(), qd.month(), qd.day())
            elif self.end_count_radio.isChecked():
                recurrence_end_count = self.end_count_spin.value()

        self._item = TodoItem(
            reminder=reminder,
            priority=priority,
            due_date=due_date,
            due_time=due_time,
            recurrence_type=recurrence_type,
            recurrence_interval=recurrence_interval,
            recurrence_end_date=recurrence_end_date,
            recurrence_end_count=recurrence_end_count,
        )
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
