"""edit_recurrence.py

Dialog for editing recurrence settings on an existing to-do item.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from ...core.models import TodoItem


class EditRecurrenceDialog(QDialog):
    """Dialog for editing an item's recurrence settings."""

    def __init__(self, item: TodoItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Edit Recurrence"))
        self.setMinimumWidth(400)

        self._result: tuple[str | None, int, date | None, int | None] | None = None
        self._setup_ui(item)

    def _setup_ui(self, item: TodoItem) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Type and interval
        recurrence_layout = QHBoxLayout()
        recurrence_layout.addWidget(QLabel(self.tr("Every")))

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 99)
        self.interval_spin.setValue(item.recurrence_interval)
        recurrence_layout.addWidget(self.interval_spin)

        self.type_combo = QComboBox()
        self.type_combo.addItem(self.tr("Minute(s)"), "minutely")
        self.type_combo.addItem(self.tr("Day(s)"), "daily")
        self.type_combo.addItem(self.tr("Week(s)"), "weekly")
        self.type_combo.addItem(self.tr("Month(s)"), "monthly")
        self.type_combo.addItem(self.tr("Year(s)"), "yearly")
        if item.recurrence_type:
            type_index = self.type_combo.findData(item.recurrence_type)
            if type_index >= 0:
                self.type_combo.setCurrentIndex(type_index)
        recurrence_layout.addWidget(self.type_combo)
        recurrence_layout.addStretch()

        form.addRow(self.tr("Repeat:"), recurrence_layout)

        # End condition
        self.end_never_radio = QRadioButton(self.tr("Never"))
        self.end_date_radio = QRadioButton(self.tr("On date"))
        self.end_count_radio = QRadioButton(self.tr("After"))

        end_group = QButtonGroup(self)
        end_group.addButton(self.end_never_radio)
        end_group.addButton(self.end_date_radio)
        end_group.addButton(self.end_count_radio)
        end_group.buttonClicked.connect(self._on_end_condition_changed)

        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setEnabled(False)

        self.end_count_spin = QSpinBox()
        self.end_count_spin.setRange(1, 999)
        self.end_count_spin.setEnabled(False)

        # Pre-populate end condition
        if item.recurrence_end_date is not None:
            self.end_date_radio.setChecked(True)
            self.end_date_edit.setDate(
                QDate(
                    item.recurrence_end_date.year,
                    item.recurrence_end_date.month,
                    item.recurrence_end_date.day,
                )
            )
            self.end_date_edit.setEnabled(True)
        elif item.recurrence_end_count is not None:
            self.end_count_radio.setChecked(True)
            self.end_count_spin.setValue(item.recurrence_end_count)
            self.end_count_spin.setEnabled(True)
        else:
            self.end_never_radio.setChecked(True)

        # Set defaults for non-selected end widgets
        if not self.end_date_radio.isChecked():
            self.end_date_edit.setDate(QDate.currentDate().addMonths(3))
        if not self.end_count_radio.isChecked():
            self.end_count_spin.setValue(10)

        end_layout = QHBoxLayout()
        end_layout.addWidget(self.end_never_radio)
        end_layout.addWidget(self.end_date_radio)
        end_layout.addWidget(self.end_date_edit)
        end_layout.addWidget(self.end_count_radio)
        end_layout.addWidget(self.end_count_spin)
        end_layout.addWidget(QLabel(self.tr("times")))
        end_layout.addStretch()

        end_widget = QWidget()
        end_widget.setLayout(end_layout)
        form.addRow(self.tr("Ends:"), end_widget)

        layout.addLayout(form)

        # Buttons
        button_layout = QHBoxLayout()

        remove_btn = QPushButton(self.tr("Remove Recurrence"))
        remove_btn.clicked.connect(self._on_remove)
        button_layout.addWidget(remove_btn)

        button_layout.addStretch()

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        button_layout.addWidget(button_box)

        layout.addLayout(button_layout)

    def _on_end_condition_changed(self) -> None:
        """Handle end condition radio button change."""
        self.end_date_edit.setEnabled(self.end_date_radio.isChecked())
        self.end_count_spin.setEnabled(self.end_count_radio.isChecked())

    def _on_accept(self) -> None:
        """Handle OK button — save current recurrence settings."""
        recurrence_type = self.type_combo.currentData()
        recurrence_interval = self.interval_spin.value()
        recurrence_end_date = None
        recurrence_end_count = None

        if self.end_date_radio.isChecked():
            qd = self.end_date_edit.date()
            recurrence_end_date = date(qd.year(), qd.month(), qd.day())
        elif self.end_count_radio.isChecked():
            recurrence_end_count = self.end_count_spin.value()

        self._result = (
            recurrence_type,
            recurrence_interval,
            recurrence_end_date,
            recurrence_end_count,
        )
        self.accept()

    def _on_remove(self) -> None:
        """Handle Remove Recurrence button — clear all recurrence."""
        self._result = (None, 1, None, None)
        self.accept()

    def get_recurrence(self) -> tuple[str | None, int, date | None, int | None]:
        """Get the recurrence settings, or defaults if cancelled."""
        if self._result is not None:
            return self._result
        return (None, 1, None, None)
