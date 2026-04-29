"""batch_due_date.py

Dialog for editing due dates of multiple items at once.
"""

from __future__ import annotations

from datetime import date, time
from uuid import UUID

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.models import TodoItem
from ..widgets.time_combo import TimeComboBox


class _ItemRow:
    """Holds widgets for a single item row."""

    __slots__ = (
        "item_id",
        "original_date",
        "original_time",
        "date_edit",
        "time_check",
        "time_edit",
    )

    def __init__(
        self,
        item_id: UUID,
        original_date: date | None,
        original_time: time | None,
        date_edit: QDateEdit,
        time_check: QCheckBox,
        time_edit: TimeComboBox,
    ) -> None:
        self.item_id = item_id
        self.original_date = original_date
        self.original_time = original_time
        self.date_edit = date_edit
        self.time_check = time_check
        self.time_edit = time_edit


class BatchDueDateDialog(QDialog):
    """Dialog for editing due dates of multiple items."""

    def __init__(self, items: list[TodoItem], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Edit Due Dates"))
        self.setAccessibleName(self.tr("Edit Due Dates"))
        self.setMinimumWidth(550)
        self.setMinimumHeight(300)
        self._items = items
        self._rows: list[_ItemRow] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- "Set all to..." section ---
        all_group = QGroupBox(self.tr("Set All To"))
        all_layout = QHBoxLayout(all_group)

        self._all_date = QDateEdit()
        self._all_date.setCalendarPopup(True)
        self._all_date.setDate(QDate.currentDate())
        all_layout.addWidget(self._all_date)

        self._all_time_check = QCheckBox(self.tr("Time"))
        self._all_time_check.stateChanged.connect(self._on_all_time_toggled)
        all_layout.addWidget(self._all_time_check)

        self._all_time = TimeComboBox()
        self._all_time.setEnabled(False)
        self._all_time.default_to_next_hour()
        all_layout.addWidget(self._all_time)

        apply_btn = QPushButton(self.tr("Apply to All"))
        apply_btn.clicked.connect(self._on_apply_all)
        all_layout.addWidget(apply_btn)

        layout.addWidget(all_group)

        # --- Per-item list ---
        items_group = QGroupBox(self.tr("Individual Items"))
        items_outer = QVBoxLayout(items_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        form = QFormLayout(container)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        for item in self._items:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)

            date_edit = QDateEdit()
            date_edit.setCalendarPopup(True)
            if item.due_date:
                date_edit.setDate(QDate(item.due_date.year, item.due_date.month, item.due_date.day))
            else:
                date_edit.setDate(QDate.currentDate())
            row_layout.addWidget(date_edit)

            time_check = QCheckBox(self.tr("Time"))
            time_edit = TimeComboBox()
            time_edit.setEnabled(False)
            if item.due_time:
                time_edit.set_time(item.due_time)
                time_check.setChecked(True)
            else:
                time_edit.default_to_next_hour()
            time_check.stateChanged.connect(
                lambda state, te=time_edit: te.setEnabled(state == Qt.CheckState.Checked.value)
            )
            row_layout.addWidget(time_check)
            row_layout.addWidget(time_edit)

            clear_btn = QPushButton(self.tr("Clear"))
            clear_btn.setFixedWidth(50)
            clear_btn.clicked.connect(
                lambda _, de=date_edit, tc=time_check: self._on_clear_row(de, tc)
            )
            row_layout.addWidget(clear_btn)

            # Truncate long reminders for the label
            label_text = item.reminder if len(item.reminder) <= 40 else item.reminder[:37] + "..."
            label = QLabel(label_text)
            label.setToolTip(item.reminder)
            form.addRow(label, row_widget)

            self._rows.append(
                _ItemRow(
                    item_id=item.id,
                    original_date=item.due_date,
                    original_time=item.due_time,
                    date_edit=date_edit,
                    time_check=time_check,
                    time_edit=time_edit,
                )
            )

        scroll.setWidget(container)
        items_outer.addWidget(scroll)
        layout.addWidget(items_group, 1)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton(self.tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton(self.tr("OK"))
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _on_all_time_toggled(self, state: int) -> None:
        self._all_time.setEnabled(state == Qt.CheckState.Checked.value)

    def _on_apply_all(self) -> None:
        """Apply the "Set All To" date/time to every per-item row."""
        qdate = self._all_date.date()
        use_time = self._all_time_check.isChecked()
        t = self._all_time.get_time() if use_time else None

        for row in self._rows:
            row.date_edit.setDate(qdate)
            if use_time and t is not None:
                row.time_check.setChecked(True)
                row.time_edit.set_time(t)
            else:
                row.time_check.setChecked(False)

    def _on_clear_row(self, date_edit: QDateEdit, time_check: QCheckBox) -> None:
        """Clear a row back to 'no due date'."""
        date_edit.setDate(QDate.currentDate())
        time_check.setChecked(False)
        # Mark as cleared by storing a sentinel
        date_edit.setProperty("cleared", True)

    def get_changes(self) -> list[tuple[UUID, date | None, time | None]]:
        """Return list of (item_id, new_date, new_time) for items that changed."""
        changes: list[tuple[UUID, date | None, time | None]] = []
        for row in self._rows:
            # Check if cleared
            if row.date_edit.property("cleared"):
                new_date = None
                new_time = None
            else:
                qd = row.date_edit.date()
                new_date = date(qd.year(), qd.month(), qd.day())
                new_time = row.time_edit.get_time() if row.time_check.isChecked() else None

            if new_date != row.original_date or new_time != row.original_time:
                changes.append((row.item_id, new_date, new_time))
        return changes
