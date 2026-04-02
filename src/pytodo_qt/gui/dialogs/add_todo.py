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
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.logger import Logger
from ...core.models import TodoItem
from ...core.nlp_parser import ParseResult
from ..widgets.smart_input import SmartInputWidget
from ..widgets.time_combo import TimeComboBox

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class AddTodoDialog(QDialog):
    """Dialog for adding a new to-do item."""

    def __init__(self, parent=None, *, known_tags: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add To-Do")
        self.setMinimumWidth(720)

        self._item: TodoItem | None = None
        self._advanced_shown = False
        self._syncing = False
        self._setup_ui()
        self._clamp_to_screen()

        if known_tags:
            self._smart_input.set_known_tags(known_tags)

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Smart input widget (always visible)
        self._smart_input = SmartInputWidget()
        self._smart_input.parse_changed.connect(self._on_smart_parse_changed)
        self._smart_input.accepted.connect(self._on_accept)
        layout.addWidget(self._smart_input)

        # Advanced toggle
        self._advanced_toggle = QLabel('<a href="#">Advanced ▶</a>')
        self._advanced_toggle.setTextFormat(Qt.TextFormat.RichText)
        self._advanced_toggle.linkActivated.connect(self._on_toggle_advanced)
        layout.addWidget(self._advanced_toggle)

        # Advanced container (hidden by default, scrollable)
        self._advanced_scroll = QScrollArea()
        self._advanced_scroll.setWidgetResizable(True)
        self._advanced_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._advanced_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._advanced_scroll.setVisible(False)

        self._advanced_container = QWidget()
        self._advanced_scroll.setWidget(self._advanced_container)

        # Form layout (inside advanced container)
        form = QFormLayout(self._advanced_container)
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

        # Tags input
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("e.g. @work, @errands, @quick")
        self.tags_edit.setToolTip("Comma-separated tags (@ prefix added automatically)")
        form.addRow("Tags:", self.tags_edit)

        # Estimated focus sessions
        self.estimated_pomodoros_spin = QSpinBox()
        self.estimated_pomodoros_spin.setRange(0, 99)
        self.estimated_pomodoros_spin.setValue(0)
        self.estimated_pomodoros_spin.setSpecialValueText("None")
        self.estimated_pomodoros_spin.setToolTip("Estimated number of focus sessions to complete")
        form.addRow("Estimated Sessions:", self.estimated_pomodoros_spin)

        # Estimated time (minutes) for stopwatch users
        self.estimated_minutes_spin = QSpinBox()
        self.estimated_minutes_spin.setRange(0, 9999)
        self.estimated_minutes_spin.setValue(0)
        self.estimated_minutes_spin.setSuffix(" min")
        self.estimated_minutes_spin.setSpecialValueText("None")
        self.estimated_minutes_spin.setToolTip(
            "Estimated time to complete (for stopwatch tracking)"
        )
        form.addRow("Estimated Time:", self.estimated_minutes_spin)

        # Per-task pomodoro durations (optional overrides)
        self.task_work_duration_spin = QSpinBox()
        self.task_work_duration_spin.setRange(0, 120)
        self.task_work_duration_spin.setValue(0)
        self.task_work_duration_spin.setSuffix(" min")
        self.task_work_duration_spin.setSpecialValueText("Default")
        self.task_work_duration_spin.setToolTip(
            "Override work session length (0 = use global setting)"
        )
        form.addRow("Session Length:", self.task_work_duration_spin)

        self.task_break_duration_spin = QSpinBox()
        self.task_break_duration_spin.setRange(0, 30)
        self.task_break_duration_spin.setValue(0)
        self.task_break_duration_spin.setSuffix(" min")
        self.task_break_duration_spin.setSpecialValueText("Default")
        self.task_break_duration_spin.setToolTip(
            "Override short break length (0 = use global setting)"
        )
        form.addRow("Break Length:", self.task_break_duration_spin)

        self.task_long_break_spin = QSpinBox()
        self.task_long_break_spin.setRange(0, 60)
        self.task_long_break_spin.setValue(0)
        self.task_long_break_spin.setSuffix(" min")
        self.task_long_break_spin.setSpecialValueText("Default")
        self.task_long_break_spin.setToolTip("Override long break length (0 = use global setting)")
        form.addRow("Long Break:", self.task_long_break_spin)

        # Recurrence section
        self.recurrence_checkbox = QCheckBox("Repeat")
        # Recurrence always available — auto-sets due_date=today if needed
        self.recurrence_checkbox.stateChanged.connect(self._on_recurrence_toggled)

        recurrence_layout = QHBoxLayout()
        recurrence_layout.addWidget(QLabel("Every"))

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 99)
        self.interval_spin.setValue(1)
        self.interval_spin.setEnabled(False)
        recurrence_layout.addWidget(self.interval_spin)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Minute(s)", "minutely")
        self.type_combo.addItem("Day(s)", "daily")
        self.type_combo.addItem("Week(s)", "weekly")
        self.type_combo.addItem("Month(s)", "monthly")
        self.type_combo.addItem("Year(s)", "yearly")
        self.type_combo.setCurrentIndex(1)  # Default to daily
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

        layout.addWidget(self._advanced_scroll, 1)  # stretch factor for scroll area

        # Button box
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Focus smart input
        self._smart_input.set_focus()

    def _on_toggle_advanced(self) -> None:
        """Toggle advanced fields visibility."""
        self._advanced_shown = not self._advanced_shown
        self._advanced_scroll.setVisible(self._advanced_shown)
        arrow = "\u25bc" if self._advanced_shown else "\u25b6"
        self._advanced_toggle.setText(f'<a href="#">Advanced {arrow}</a>')
        # Populate fields from current parse result when opening advanced
        if self._advanced_shown:
            result = self._smart_input.get_parse_result()
            if result:
                # Temporarily bypass guard to populate fields once
                self._advanced_shown = False
                self._on_smart_parse_changed(result)
                self._advanced_shown = True
        self.adjustSize()
        self._clamp_to_screen()

    def _clamp_to_screen(self) -> None:
        """Resize dialog to fit screen, then center on parent window."""
        screen = self.screen()
        if not screen:
            return
        avail = screen.availableGeometry()
        # Fit within screen bounds
        max_h = int(avail.height() * 0.85)
        max_w = int(avail.width() * 0.6)
        w = max(self.minimumWidth(), min(self.sizeHint().width(), max_w))
        h = min(self.sizeHint().height(), max_h)
        self.resize(w, h)
        # Center on parent window
        parent = self.parentWidget()
        if parent:
            parent_geo = parent.geometry()
            cx = parent_geo.center().x() - w // 2
            cy = parent_geo.center().y() - h // 2
        else:
            cx = avail.center().x() - w // 2
            cy = avail.center().y() - h // 2
        # Clamp to screen edges
        cx = max(avail.left(), min(cx, avail.right() - w))
        cy = max(avail.top(), min(cy, avail.bottom() - h))
        self.move(cx, cy)

    def _on_smart_parse_changed(self, result: ParseResult) -> None:
        """Sync smart input parse result to discrete fields.

        When advanced mode is shown, the user is editing fields directly —
        don't overwrite their edits with parsed values from the smart input.
        """
        if self._syncing or self._advanced_shown:
            return
        self._syncing = True
        try:
            self.reminder_edit.setText(result.reminder)

            # Priority
            if result.priority is not None:
                idx = self.priority_combo.findData(result.priority)
                if idx >= 0:
                    self.priority_combo.setCurrentIndex(idx)
            else:
                self.priority_combo.setCurrentIndex(1)  # Normal

            # Due date
            if result.due_date is not None:
                self.due_date_checkbox.setChecked(True)
                self.due_date_edit.setDate(
                    QDate(result.due_date.year, result.due_date.month, result.due_date.day)
                )
            else:
                self.due_date_checkbox.setChecked(False)

            # Due time
            if result.due_time is not None:
                self.due_time_checkbox.setChecked(True)
                self.due_time_edit.set_time(result.due_time)
            else:
                self.due_time_checkbox.setChecked(False)

            # Tags
            if result.tags:
                self.tags_edit.setText(", ".join(result.tags))
            else:
                self.tags_edit.clear()

            # Pomodoro
            self.estimated_pomodoros_spin.setValue(result.pomodoro_estimate or 0)

            # Estimated time
            self.estimated_minutes_spin.setValue(result.estimated_minutes or 0)

            # Per-task session length
            self.task_work_duration_spin.setValue(result.work_duration or 0)

            # Recurrence
            if result.recurrence_type is not None:
                self.recurrence_checkbox.setChecked(True)
                self.interval_spin.setValue(result.recurrence_interval)
                type_idx = self.type_combo.findData(result.recurrence_type)
                if type_idx >= 0:
                    self.type_combo.setCurrentIndex(type_idx)
                if result.recurrence_end_date is not None:
                    self.end_date_radio.setChecked(True)
                    self.end_date_edit.setDate(
                        QDate(
                            result.recurrence_end_date.year,
                            result.recurrence_end_date.month,
                            result.recurrence_end_date.day,
                        )
                    )
                    self.end_date_edit.setEnabled(True)
                elif result.recurrence_end_count is not None:
                    self.end_count_radio.setChecked(True)
                    self.end_count_spin.setValue(result.recurrence_end_count)
                    self.end_count_spin.setEnabled(True)
                else:
                    self.end_never_radio.setChecked(True)
            else:
                self.recurrence_checkbox.setChecked(False)

        finally:
            self._syncing = False

    def _on_due_date_toggled(self, state: int) -> None:
        """Handle due date checkbox toggle."""
        enabled = state == Qt.CheckState.Checked.value
        self.due_date_edit.setEnabled(enabled)
        self.due_time_checkbox.setEnabled(enabled)
        # Recurrence is always available — auto-sets today if no date
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
        if not self._advanced_shown:
            # Build item from smart input parse result
            result = self._smart_input.get_parse_result()
            reminder = result.reminder.strip()
            if not reminder:
                QMessageBox.warning(self, "Validation Error", "Please enter a reminder.")
                self._smart_input.set_focus()
                return

            # Auto-set due date/time when recurrence is set without one
            due_date = result.due_date
            due_time = result.due_time
            if result.recurrence_type is not None and due_date is None:
                due_date = date.today()
            # Minutely recurrence needs a due_time — auto-set to now + interval
            if result.recurrence_type == "minutely" and due_time is None:
                from datetime import datetime as _dt
                from datetime import timedelta as _td

                next_dt = _dt.now() + _td(minutes=result.recurrence_interval)
                due_time = next_dt.time().replace(second=0, microsecond=0)

            self._item = TodoItem(
                reminder=reminder,
                priority=result.priority or 2,
                due_date=due_date,
                due_time=due_time,
                tags=result.tags,
                recurrence_type=result.recurrence_type,
                recurrence_interval=result.recurrence_interval,
                recurrence_end_date=result.recurrence_end_date,
                recurrence_end_count=result.recurrence_end_count,
                estimated_pomodoros=result.pomodoro_estimate or 0,
            )
        else:
            # Build item from discrete fields
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

            if self.recurrence_checkbox.isChecked():
                recurrence_type = self.type_combo.currentData()
                recurrence_interval = self.interval_spin.value()
                # Auto-set due date to today when recurrence is set without one
                if due_date is None:
                    due_date = date.today()
                # Minutely needs a due_time
                if recurrence_type == "minutely" and due_time is None:
                    from datetime import datetime as _dt
                    from datetime import timedelta as _td

                    next_dt = _dt.now() + _td(minutes=recurrence_interval)
                    due_time = next_dt.time().replace(second=0, microsecond=0)
                if self.end_date_radio.isChecked():
                    qd = self.end_date_edit.date()
                    recurrence_end_date = date(qd.year(), qd.month(), qd.day())
                elif self.end_count_radio.isChecked():
                    recurrence_end_count = self.end_count_spin.value()

            # Parse tags
            tags_text = self.tags_edit.text().strip()
            tags: list[str] = []
            if tags_text:
                for tag in tags_text.replace(",", " ").split():
                    tag = tag.strip()
                    if tag:
                        if not tag.startswith("@"):
                            tag = f"@{tag}"
                        if tag not in tags:
                            tags.append(tag)

            estimated_pomodoros = self.estimated_pomodoros_spin.value()
            estimated_minutes = self.estimated_minutes_spin.value()

            self._item = TodoItem(
                reminder=reminder,
                priority=priority,
                due_date=due_date,
                due_time=due_time,
                tags=tags,
                recurrence_type=recurrence_type,
                recurrence_interval=recurrence_interval,
                recurrence_end_date=recurrence_end_date,
                recurrence_end_count=recurrence_end_count,
                estimated_pomodoros=estimated_pomodoros,
                estimated_minutes=estimated_minutes,
                work_duration=self.task_work_duration_spin.value(),
                break_duration=self.task_break_duration_spin.value(),
                long_break_duration=self.task_long_break_spin.value(),
            )
        logger.log.info("Created new todo item: %s", reminder[:50])
        self.accept()

    def get_item(self) -> TodoItem | None:
        """Get the created to-do item, or None if cancelled."""
        return self._item

    @classmethod
    def create_item(
        cls,
        parent=None,
        title: str = "Add To-Do",
        known_tags: list[str] | None = None,
    ) -> TodoItem | None:
        """Convenience method to show dialog and get result."""
        dialog = cls(parent, known_tags=known_tags)
        dialog.setWindowTitle(title)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_item()
        return None
