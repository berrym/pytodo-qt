"""add_todo.py

Dialog for adding a new to-do item.
"""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.logger import Logger
from ...core.models import TodoItem
from ...core.nlp_parser import EntityKind, ParseResult, replace_or_append_category
from ..widgets.smart_input import SmartInputWidget
from ..widgets.time_combo import TimeComboBox

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class AddTodoDialog(QDialog):
    """Dialog for adding a new to-do item."""

    def __init__(
        self,
        parent=None,
        *,
        known_tags: list[str] | None = None,
        columns: list[str] | None = None,
        selected_column: str | None = None,
        default_due_date: date | None = None,
        default_due_time: time | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Add Todo"))
        self.setAccessibleName(self.tr("Add Todo"))
        self.setMinimumWidth(720)

        self._item: TodoItem | None = None
        self._subtask_reminders: list[str] = []
        self._advanced_shown = False
        self._syncing = False
        self._columns: list[str] = list(columns) if columns else []
        self._selected_column: str | None = selected_column
        # When the dialog is launched by clicking an empty calendar cell,
        # the cell's date and (for hour-grid cells) hour are passed here as
        # defaults. The smart-input parse-result still wins if the user
        # types a date/time in the reminder text — these are fallbacks for
        # the case where the user types a bare reminder.
        self._default_due_date: date | None = default_due_date
        self._default_due_time: time | None = default_due_time
        self._setup_ui()
        self._apply_cell_launch_defaults()
        self._clamp_to_screen()

        if known_tags:
            self._smart_input.set_known_tags(known_tags)

    def _apply_cell_launch_defaults(self) -> None:
        """Push ``default_due_date`` / ``default_due_time`` into the discrete
        Advanced fields so the Advanced section reflects the empty-cell
        launch context if the user opens it. Idempotent and safe to call
        before any user interaction."""
        if self._default_due_date is not None:
            self.due_date_checkbox.setChecked(True)
            self.due_date_edit.setDate(
                QDate(
                    self._default_due_date.year,
                    self._default_due_date.month,
                    self._default_due_date.day,
                )
            )
        # The due-time checkbox is gated on the due-date checkbox via
        # _on_due_date_toggled — only enable Time when Date is set.
        if self._default_due_time is not None and self._default_due_date is not None:
            self.due_time_checkbox.setChecked(True)
            self.due_time_edit.set_time(self._default_due_time)

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Smart input widget (always visible)
        self._smart_input = SmartInputWidget()
        self._smart_input.parse_changed.connect(self._on_smart_parse_changed)
        self._smart_input.accepted.connect(self._on_accept)
        layout.addWidget(self._smart_input)

        # Quick-action trigger buttons (Priority / Date / Tag / Recurrence).
        # Each button pops a small preset menu; selecting a preset
        # inserts the corresponding NLP token into the smart input
        # (via replace_or_append_category), so the user sees what the
        # parser would have parsed from typing it manually. Keeps the
        # NLP-first flow intact while giving click-driven users a
        # discoverable entry point for the common categories.
        layout.addWidget(self._build_quick_actions_row())

        # Advanced toggle. QToolButton with checkable=True + autoRaise gives
        # a visually flat surface that still participates in the tab chain
        # and reports its expanded/collapsed state via accessible state. The
        # earlier QLabel-with-linkActivated implementation was visually
        # identical but unreachable for keyboard-only users (#47): QLabel
        # does not accept focus and HTML links inside it are not in the tab
        # chain, so every Advanced field below sat behind an invisible
        # mouse-only gate.
        self._advanced_toggle = QToolButton()
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setAutoRaise(True)
        self._advanced_toggle.setText(self.tr("Advanced ▶"))
        self._advanced_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._advanced_toggle.setAccessibleName(self.tr("Advanced fields"))
        self._advanced_toggle.setAccessibleDescription(
            self.tr("Show or hide additional task fields")
        )
        self._advanced_toggle.toggled.connect(self._on_toggle_advanced)
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.addWidget(self._advanced_toggle)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        # Advanced container (hidden by default, scrollable)
        self._advanced_scroll = QScrollArea()
        self._advanced_scroll.setWidgetResizable(True)
        self._advanced_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._advanced_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._advanced_scroll.setVisible(False)
        self._advanced_scroll.setAccessibleName(self.tr("Advanced fields"))

        self._advanced_container = QWidget()
        self._advanced_scroll.setWidget(self._advanced_container)

        # Main vertical layout inside advanced container
        adv_layout = QVBoxLayout(self._advanced_container)

        # --- Top-level fields (no group) ---
        top_form = QFormLayout()
        top_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.reminder_edit = QLineEdit()
        self.reminder_edit.setPlaceholderText(self.tr("Enter reminder text..."))
        top_form.addRow(self.tr("Reminder:"), self.reminder_edit)

        self.priority_combo = QComboBox()
        self.priority_combo.addItem(self.tr("High"), 1)
        self.priority_combo.addItem(self.tr("Normal"), 2)
        self.priority_combo.addItem(self.tr("Low"), 3)
        self.priority_combo.setCurrentIndex(1)
        top_form.addRow(self.tr("Priority:"), self.priority_combo)

        # Kanban board column. Populated from the caller's list of
        # columns; pre-selected to `selected_column` when provided (the
        # "+" button in a specific kanban column passes this so the
        # user sees their implicit choice). When no columns list is
        # provided (e.g. unit tests without kanban state), the combo
        # is hidden entirely and _on_accept skips writing board_column.
        self.board_column_combo = QComboBox()
        if self._columns:
            for col_name in self._columns:
                self.board_column_combo.addItem(col_name, col_name)
            if self._selected_column and self._selected_column in self._columns:
                self.board_column_combo.setCurrentIndex(self._columns.index(self._selected_column))
            else:
                self.board_column_combo.setCurrentIndex(0)
            top_form.addRow(self.tr("Column:"), self.board_column_combo)

        adv_layout.addLayout(top_form)

        # --- Scheduling group ---
        sched_group = QGroupBox(self.tr("Scheduling"))
        sched_form = QFormLayout(sched_group)

        due_date_layout = QHBoxLayout()
        self.due_date_checkbox = QCheckBox(self.tr("Set due date"))
        self.due_date_checkbox.stateChanged.connect(self._on_due_date_toggled)
        self.due_date_edit = QDateEdit()
        self.due_date_edit.setCalendarPopup(True)
        self.due_date_edit.setDate(QDate.currentDate())
        self.due_date_edit.setEnabled(False)
        self.due_date_edit.setAccessibleName(self.tr("Due date"))
        due_date_layout.addWidget(self.due_date_checkbox)
        due_date_layout.addWidget(self.due_date_edit, 1)
        sched_form.addRow(self.tr("Due Date:"), due_date_layout)

        due_time_layout = QHBoxLayout()
        self.due_time_checkbox = QCheckBox(self.tr("Set due time"))
        self.due_time_checkbox.setEnabled(False)
        self.due_time_checkbox.stateChanged.connect(self._on_due_time_toggled)
        self.due_time_edit = TimeComboBox()
        self.due_time_edit.setEnabled(False)
        self.due_time_edit.default_to_next_hour()
        self.due_time_edit.setAccessibleName(self.tr("Due time start"))
        due_time_layout.addWidget(self.due_time_checkbox)
        due_time_layout.addWidget(self.due_time_edit, 1)
        sched_form.addRow(self.tr("Due Time:"), due_time_layout)

        # Due Time End — pairs with Due Time to form a window. Only
        # interactive when Due Time is set, since a window without a
        # start has no meaning. The parser already extracts this field
        # from "from X to Y" / "between X and Y" phrases; this UI gives
        # users an explicit non-NLP path.
        due_time_end_layout = QHBoxLayout()
        self.due_time_end_checkbox = QCheckBox(self.tr("Set end time"))
        self.due_time_end_checkbox.setEnabled(False)
        self.due_time_end_checkbox.stateChanged.connect(self._on_due_time_end_toggled)
        self.due_time_end_edit = TimeComboBox()
        self.due_time_end_edit.setEnabled(False)
        self.due_time_end_edit.default_to_next_hour()
        self.due_time_end_edit.setAccessibleName(self.tr("Due time end"))
        due_time_end_layout.addWidget(self.due_time_end_checkbox)
        due_time_end_layout.addWidget(self.due_time_end_edit, 1)
        sched_form.addRow(self.tr("End Time:"), due_time_end_layout)

        self.time_block_combo = QComboBox()
        self.time_block_combo.setAccessibleName(self.tr("Time block"))
        self.time_block_combo.addItem(self.tr("None"), "")
        for block_id, label in [
            ("early_morning", "Early Morning"),
            ("morning", "Morning"),
            ("late_morning", "Late Morning"),
            ("noon", "Noon"),
            ("early_afternoon", "Early Afternoon"),
            ("afternoon", "Afternoon"),
            ("late_afternoon", "Late Afternoon"),
            ("early_evening", "Early Evening"),
            ("evening", "Evening"),
            ("late_evening", "Late Evening"),
            ("night", "Night"),
            ("late_night", "Late Night"),
            ("midnight", "Midnight"),
        ]:
            self.time_block_combo.addItem(self.tr(label), block_id)
        sched_form.addRow(self.tr("Time Block:"), self.time_block_combo)

        event_date_layout = QHBoxLayout()
        self.event_date_checkbox = QCheckBox(self.tr("Set event date"))
        self.event_date_checkbox.stateChanged.connect(self._on_event_date_toggled)
        self.event_date_edit = QDateEdit()
        self.event_date_edit.setCalendarPopup(True)
        self.event_date_edit.setDate(QDate.currentDate())
        self.event_date_edit.setEnabled(False)
        self.event_date_edit.setAccessibleName(self.tr("Event date"))
        event_date_layout.addWidget(self.event_date_checkbox)
        event_date_layout.addWidget(self.event_date_edit, 1)
        sched_form.addRow(self.tr("Event Date:"), event_date_layout)

        adv_layout.addWidget(sched_group)

        # --- Estimated Duration group ---
        dur_group = QGroupBox(self.tr("Estimated Duration"))
        dur_form = QFormLayout(dur_group)

        dur_layout = QHBoxLayout()
        self.duration_value_spin = QSpinBox()
        self.duration_value_spin.setRange(0, 9999)
        self.duration_value_spin.setValue(0)
        self.duration_value_spin.setSpecialValueText(self.tr("None"))
        self.duration_value_spin.setAccessibleName(self.tr("Duration value"))
        self.duration_value_spin.setAccessibleDescription(
            self.tr("Duration value — paired with the unit selector to its right")
        )
        dur_layout.addWidget(self.duration_value_spin, 1)

        self.duration_unit_combo = QComboBox()
        self.duration_unit_combo.setAccessibleName(self.tr("Duration unit"))
        self.duration_unit_combo.setAccessibleDescription(
            self.tr("Duration unit — paired with the value selector to its left")
        )
        self.duration_unit_combo.addItem(self.tr("Minutes"), 1)
        self.duration_unit_combo.addItem(self.tr("Hours"), 60)
        self.duration_unit_combo.addItem(self.tr("Days"), 1440)
        self.duration_unit_combo.addItem(self.tr("Weeks"), 10080)
        self.duration_unit_combo.addItem(self.tr("Months"), 43200)
        self.duration_unit_combo.addItem(self.tr("Years"), 525600)
        dur_layout.addWidget(self.duration_unit_combo)

        dur_form.addRow(self.tr("Duration:"), dur_layout)

        # Keep the raw spinbox for backward compat (hidden, used by sync logic)
        self.estimated_minutes_spin = QSpinBox()
        self.estimated_minutes_spin.setRange(0, 9999999)
        self.estimated_minutes_spin.setValue(0)
        self.estimated_minutes_spin.setVisible(False)

        adv_layout.addWidget(dur_group)

        # --- Focus Session group ---
        focus_group = QGroupBox(self.tr("Focus Session"))
        focus_form = QFormLayout(focus_group)

        self.estimated_pomodoros_spin = QSpinBox()
        self.estimated_pomodoros_spin.setRange(0, 99)
        self.estimated_pomodoros_spin.setValue(0)
        self.estimated_pomodoros_spin.setSpecialValueText(self.tr("None"))
        focus_form.addRow(self.tr("Sessions:"), self.estimated_pomodoros_spin)

        self.task_work_duration_spin = QSpinBox()
        self.task_work_duration_spin.setRange(0, 120)
        self.task_work_duration_spin.setValue(0)
        self.task_work_duration_spin.setSuffix(self.tr(" min"))
        self.task_work_duration_spin.setSpecialValueText(self.tr("Default"))
        focus_form.addRow(self.tr("Session Length:"), self.task_work_duration_spin)

        self.task_break_duration_spin = QSpinBox()
        self.task_break_duration_spin.setRange(0, 30)
        self.task_break_duration_spin.setValue(0)
        self.task_break_duration_spin.setSuffix(self.tr(" min"))
        self.task_break_duration_spin.setSpecialValueText(self.tr("Default"))
        focus_form.addRow(self.tr("Break:"), self.task_break_duration_spin)

        self.task_long_break_spin = QSpinBox()
        self.task_long_break_spin.setRange(0, 60)
        self.task_long_break_spin.setValue(0)
        self.task_long_break_spin.setSuffix(self.tr(" min"))
        self.task_long_break_spin.setSpecialValueText(self.tr("Default"))
        focus_form.addRow(self.tr("Long Break:"), self.task_long_break_spin)

        adv_layout.addWidget(focus_group)

        # --- Recurrence group ---
        rec_group = QGroupBox(self.tr("Recurrence"))
        rec_form = QFormLayout(rec_group)

        self.recurrence_checkbox = QCheckBox(self.tr("Repeat"))
        self.recurrence_checkbox.setAccessibleName(self.tr("Recurrence enabled"))
        self.recurrence_checkbox.stateChanged.connect(self._on_recurrence_toggled)

        recurrence_layout = QHBoxLayout()
        recurrence_layout.addWidget(QLabel(self.tr("Every")))

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 99)
        self.interval_spin.setValue(1)
        self.interval_spin.setEnabled(False)
        self.interval_spin.setAccessibleName(self.tr("Recurrence interval"))
        self.interval_spin.setAccessibleDescription(
            self.tr("Recurrence interval — paired with the unit selector to its right")
        )
        recurrence_layout.addWidget(self.interval_spin)

        self.type_combo = QComboBox()
        self.type_combo.setAccessibleName(self.tr("Recurrence unit"))
        self.type_combo.setAccessibleDescription(
            self.tr("Recurrence unit — paired with the interval value to its left")
        )
        self.type_combo.addItem(self.tr("Minute(s)"), "minutely")
        self.type_combo.addItem(self.tr("Day(s)"), "daily")
        self.type_combo.addItem(self.tr("Week(s)"), "weekly")
        self.type_combo.addItem(self.tr("Month(s)"), "monthly")
        self.type_combo.addItem(self.tr("Year(s)"), "yearly")
        self.type_combo.setCurrentIndex(1)
        self.type_combo.setEnabled(False)
        recurrence_layout.addWidget(self.type_combo)

        recurrence_row = QWidget()
        recurrence_row_layout = QHBoxLayout(recurrence_row)
        recurrence_row_layout.setContentsMargins(0, 0, 0, 0)
        recurrence_row_layout.addWidget(self.recurrence_checkbox)
        recurrence_row_layout.addLayout(recurrence_layout)
        recurrence_row_layout.addStretch()
        rec_form.addRow(self.tr("Repeat:"), recurrence_row)

        self.end_never_radio = QRadioButton(self.tr("Never"))
        self.end_never_radio.setChecked(True)
        self.end_never_radio.setAccessibleName(self.tr("Ends never"))
        self.end_date_radio = QRadioButton(self.tr("On date"))
        self.end_date_radio.setAccessibleName(self.tr("Ends on date"))
        self.end_count_radio = QRadioButton(self.tr("After"))
        self.end_count_radio.setAccessibleName(self.tr("Ends after count"))

        end_group = QButtonGroup(self)
        end_group.addButton(self.end_never_radio)
        end_group.addButton(self.end_date_radio)
        end_group.addButton(self.end_count_radio)
        end_group.buttonClicked.connect(self._on_end_condition_changed)

        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QDate.currentDate().addMonths(3))
        self.end_date_edit.setEnabled(False)
        self.end_date_edit.setAccessibleName(self.tr("End date"))

        self.end_count_spin = QSpinBox()
        self.end_count_spin.setRange(1, 999)
        self.end_count_spin.setValue(10)
        self.end_count_spin.setEnabled(False)
        self.end_count_spin.setAccessibleName(self.tr("End count"))

        end_layout = QHBoxLayout()
        end_layout.addWidget(self.end_never_radio)
        end_layout.addWidget(self.end_date_radio)
        end_layout.addWidget(self.end_date_edit)
        end_layout.addWidget(self.end_count_radio)
        end_layout.addWidget(self.end_count_spin)
        end_layout.addWidget(QLabel(self.tr("times")))
        end_layout.addStretch()

        self.end_widget = QWidget()
        self.end_widget.setLayout(end_layout)
        self.end_widget.setEnabled(False)
        rec_form.addRow(self.tr("Ends:"), self.end_widget)

        adv_layout.addWidget(rec_group)

        # --- Tags (standalone) ---
        tags_form = QFormLayout()
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText(self.tr("e.g. @work, @errands, @quick"))
        self.tags_edit.setToolTip(self.tr("Comma-separated tags (@ prefix added automatically)"))
        tags_form.addRow(self.tr("Tags:"), self.tags_edit)
        adv_layout.addLayout(tags_form)

        # --- Subtasks (standalone) ---
        subtasks_form = QFormLayout()
        self.subtasks_edit = QPlainTextEdit()
        self.subtasks_edit.setPlaceholderText(
            self.tr("One subtask per line\ne.g.\nbook flight\npack")
        )
        self.subtasks_edit.setToolTip(
            self.tr(
                "One subtask per line. Each line becomes a child task of the "
                "item being created. Inline syntax (parent: a, b, c) in the "
                "smart input populates this field automatically."
            )
        )
        # Cap visible height so the field doesn't dominate the dialog;
        # users can still enter many lines and scroll.
        fm = self.subtasks_edit.fontMetrics()
        self.subtasks_edit.setFixedHeight(int(fm.lineSpacing() * 4 + 12))
        subtasks_form.addRow(self.tr("Subtasks:"), self.subtasks_edit)
        adv_layout.addLayout(subtasks_form)

        adv_layout.addStretch()

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

    def _on_toggle_advanced(self, checked: bool) -> None:
        """Slot for the advanced toggle button's `toggled` signal.

        Receives the new checked state directly from the button so the
        button is the single source of truth for the open/closed state;
        ``_advanced_shown`` mirrors it for the parse-sync guard below.
        """
        self._advanced_shown = checked
        self._advanced_scroll.setVisible(checked)
        arrow = "\u25bc" if checked else "\u25b6"
        self._advanced_toggle.setText(self.tr("Advanced") + f" {arrow}")
        # Populate fields from current parse result when opening advanced
        if checked:
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

            # Due time end — only meaningful alongside Due Time.
            if result.due_time_end is not None and result.due_time is not None:
                self.due_time_end_checkbox.setChecked(True)
                self.due_time_end_edit.set_time(result.due_time_end)
            else:
                self.due_time_end_checkbox.setChecked(False)

            # Tags
            if result.tags:
                self.tags_edit.setText(", ".join(result.tags))
            else:
                self.tags_edit.clear()

            # Subtasks (one per line)
            if result.subtask_reminders:
                self.subtasks_edit.setPlainText("\n".join(result.subtask_reminders))
            else:
                self.subtasks_edit.clear()

            # Pomodoro
            self.estimated_pomodoros_spin.setValue(result.pomodoro_estimate or 0)

            # Estimated duration — convert minutes to natural scale
            est = result.estimated_minutes or 0
            self.estimated_minutes_spin.setValue(est)
            if est > 0:
                self._set_duration_from_minutes(est)
            else:
                self.duration_value_spin.setValue(0)
                self.duration_unit_combo.setCurrentIndex(0)

            # Per-task session length
            self.task_work_duration_spin.setValue(result.work_duration or 0)

            # Time block
            if result.due_time_block:
                idx = self.time_block_combo.findData(result.due_time_block)
                if idx >= 0:
                    self.time_block_combo.setCurrentIndex(idx)
            else:
                self.time_block_combo.setCurrentIndex(0)

            # Event date
            if result.event_date is not None:
                self.event_date_checkbox.setChecked(True)
                self.event_date_edit.setDate(
                    QDate(result.event_date.year, result.event_date.month, result.event_date.day)
                )
            else:
                self.event_date_checkbox.setChecked(False)

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
            self.due_time_end_checkbox.setChecked(False)
            self.recurrence_checkbox.setChecked(False)

    def _on_due_time_toggled(self, state: int) -> None:
        """Handle due time checkbox toggle."""
        enabled = state == Qt.CheckState.Checked.value
        self.due_time_edit.setEnabled(enabled)
        # End time pairs with due time — without a start, end has no meaning.
        self.due_time_end_checkbox.setEnabled(enabled)
        if not enabled:
            self.due_time_end_checkbox.setChecked(False)

    def _on_due_time_end_toggled(self, state: int) -> None:
        """Handle due time end checkbox toggle."""
        self.due_time_end_edit.setEnabled(state == Qt.CheckState.Checked.value)

    def _on_event_date_toggled(self, state: int) -> None:
        """Handle event date checkbox toggle."""
        self.event_date_edit.setEnabled(state == Qt.CheckState.Checked.value)

    def _set_duration_from_minutes(self, minutes: int) -> None:
        """Set duration value/unit widgets from a raw minutes count."""
        # Pick the largest unit that divides evenly, or the natural scale
        for unit_idx, (_, mult) in reversed(
            list(
                enumerate(
                    (
                        ("min", 1),
                        ("hr", 60),
                        ("d", 1440),
                        ("w", 10080),
                        ("mo", 43200),
                        ("y", 525600),
                    )
                )
            )
        ):
            if minutes >= mult and minutes % mult == 0:
                self.duration_value_spin.setValue(minutes // mult)
                self.duration_unit_combo.setCurrentIndex(unit_idx)
                return
        # Fallback: raw minutes
        self.duration_value_spin.setValue(minutes)
        self.duration_unit_combo.setCurrentIndex(0)

    def _get_duration_minutes(self) -> int:
        """Read estimated duration as minutes from value + unit widgets."""
        value = self.duration_value_spin.value()
        multiplier = self.duration_unit_combo.currentData()
        return value * (multiplier or 1)

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

    # --- Quick action trigger buttons ---

    def _build_quick_actions_row(self) -> QWidget:
        """Construct the row of category trigger buttons shown under
        the smart input. Each button carries a dropdown menu of
        presets for that category; selecting one mutates the text
        input via replace_or_append_category."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 2)
        row_layout.setSpacing(6)

        self._priority_btn = self._make_trigger_button(
            self.tr("Priority"), self._build_priority_menu()
        )
        self._date_btn = self._make_trigger_button(self.tr("Date"), self._build_date_menu())
        self._tag_btn = self._make_trigger_button(self.tr("Tag"), self._build_tag_menu())
        self._recur_btn = self._make_trigger_button(
            self.tr("Recurrence"), self._build_recurrence_menu()
        )

        row_layout.addWidget(self._priority_btn)
        row_layout.addWidget(self._date_btn)
        row_layout.addWidget(self._tag_btn)
        row_layout.addWidget(self._recur_btn)
        row_layout.addStretch()
        return row

    def _make_trigger_button(self, label: str, menu: QMenu) -> QToolButton:
        btn = QToolButton()
        btn.setText(f"{label} \u25be")  # trailing small down arrow
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn.setMenu(menu)
        btn.setStyleSheet(
            "QToolButton { padding: 4px 10px; border: 1px solid palette(mid);"
            " border-radius: 4px; background: palette(base); font-size: 11px; }"
            " QToolButton:hover { background: palette(midlight); }"
            " QToolButton::menu-indicator { image: none; width: 0; }"
        )
        return btn

    def _build_priority_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, token in (
            (self.tr("High"), "high priority"),
            (self.tr("Normal"), "normal priority"),
            (self.tr("Low"), "low priority"),
        ):
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, t=token: self._apply_quick_action(EntityKind.PRIORITY, t)
            )
            menu.addAction(action)
        return menu

    def _build_date_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, token in (
            (self.tr("Today"), "today"),
            (self.tr("Tomorrow"), "tomorrow"),
            (self.tr("This Friday"), "friday"),
            (self.tr("Next Monday"), "next monday"),
            (self.tr("Next Week"), "next week"),
        ):
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, t=token: self._apply_quick_action(EntityKind.DATE, t)
            )
            menu.addAction(action)
        return menu

    def _build_tag_menu(self) -> QMenu:
        import contextlib

        menu = QMenu(self)
        # Pull known tags from the smart input's completer.
        known: list[str] = []
        with contextlib.suppress(AttributeError):
            known = sorted(self._smart_input._tag_popup._all_tags)
        if not known:
            placeholder = QAction(self.tr("(no tags yet — type @name to add)"), self)
            placeholder.setEnabled(False)
            menu.addAction(placeholder)
            return menu
        # Cap at 12 to keep the menu readable
        for tag in known[:12]:
            # Ensure leading @
            display = tag if tag.startswith("@") else f"@{tag}"
            action = QAction(display, self)
            action.triggered.connect(
                lambda _checked=False, t=display: self._apply_quick_action(
                    EntityKind.TAG, t, append_only=True
                )
            )
            menu.addAction(action)
        return menu

    def _build_recurrence_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, token in (
            (self.tr("Daily"), "daily"),
            (self.tr("Weekly"), "weekly"),
            (self.tr("Monthly"), "monthly"),
            (self.tr("Yearly"), "yearly"),
        ):
            action = QAction(label, self)
            action.triggered.connect(
                lambda _checked=False, t=token: self._apply_quick_action(EntityKind.RECURRENCE, t)
            )
            menu.addAction(action)
        return menu

    def _apply_quick_action(
        self, kind: EntityKind, token: str, *, append_only: bool = False
    ) -> None:
        """Apply a quick-action preset to the smart input text.

        Reads the current text + parse result, uses
        replace_or_append_category to produce a mutated string, and
        writes it back to the input. The input's debounced parser
        re-runs naturally on text change so the chips update.
        """
        text = self._smart_input.get_text()
        result = self._smart_input.get_parse_result()
        new_text = replace_or_append_category(
            text, result.spans, kind, token, append_only=append_only
        )
        if new_text == text:
            return
        self._smart_input.set_text(new_text)
        self._smart_input.set_focus()

    def _on_accept(self) -> None:
        """Handle OK button."""
        if not self._advanced_shown:
            # Build item from smart input parse result
            result = self._smart_input.get_parse_result()
            reminder = result.reminder.strip()
            if not reminder:
                QMessageBox.warning(
                    self, self.tr("Validation Error"), self.tr("Please enter a reminder.")
                )
                self._smart_input.set_focus()
                return

            # Auto-set due date/time when recurrence is set without one
            due_date = result.due_date
            due_time = result.due_time
            # Empty-cell-launch fallback: if the user typed a bare reminder
            # (no date/time NLP) and the dialog was launched from an empty
            # calendar cell, inherit that cell's date/hour. The smart-input
            # parse result still wins when the user provided an explicit
            # date or time in the reminder text.
            if due_date is None and self._default_due_date is not None:
                due_date = self._default_due_date
            if due_time is None and self._default_due_time is not None:
                due_time = self._default_due_time
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
                due_time_end=result.due_time_end,
                due_time_block=result.due_time_block,
                tags=result.tags,
                recurrence_type=result.recurrence_type,
                recurrence_interval=result.recurrence_interval,
                recurrence_end_date=result.recurrence_end_date,
                recurrence_end_count=result.recurrence_end_count,
                estimated_pomodoros=result.pomodoro_estimate or 0,
                estimated_minutes=result.estimated_minutes or 0,
                work_duration=result.work_duration or 0,
                event_date=result.event_date,
                conditions=result.conditions or None,
            )
            self._subtask_reminders = result.subtask_reminders
        else:
            # Build item from discrete fields
            reminder = self.reminder_edit.text().strip()
            if not reminder:
                QMessageBox.warning(
                    self, self.tr("Validation Error"), self.tr("Please enter a reminder.")
                )
                self.reminder_edit.setFocus()
                return

            priority = self.priority_combo.currentData()

            due_date = None
            due_time = None
            due_time_end = None
            if self.due_date_checkbox.isChecked():
                qdate = self.due_date_edit.date()
                due_date = date(qdate.year(), qdate.month(), qdate.day())
                if self.due_time_checkbox.isChecked():
                    due_time = self.due_time_edit.get_time()
                    if self.due_time_end_checkbox.isChecked():
                        due_time_end = self.due_time_end_edit.get_time()

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
            estimated_minutes = self._get_duration_minutes()

            # Time block
            time_block = self.time_block_combo.currentData() or None

            # Event date
            event_date = None
            if self.event_date_checkbox.isChecked():
                qd = self.event_date_edit.date()
                event_date = date(qd.year(), qd.month(), qd.day())

            self._item = TodoItem(
                reminder=reminder,
                priority=priority,
                due_date=due_date,
                due_time=due_time,
                due_time_end=due_time_end,
                due_time_block=time_block,
                event_date=event_date,
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
            # Subtasks: one per non-empty line in the multiline field.
            self._subtask_reminders = [
                line.strip()
                for line in self.subtasks_edit.toPlainText().splitlines()
                if line.strip()
            ]

        # Apply the board column dropdown selection to the item
        # regardless of which build path (smart input or advanced
        # fields) ran above. Only touches items when the dialog was
        # actually constructed with a columns list.
        if self._item is not None and self._columns:
            selected = self.board_column_combo.currentData()
            if selected:
                self._item.board_column = selected

        logger.log.info("Created new todo item: %s", reminder[:50])
        self.accept()

    def get_item(self) -> TodoItem | None:
        """Get the created to-do item, or None if cancelled."""
        return self._item

    def get_subtask_reminders(self) -> list[str]:
        """Get subtask reminder texts parsed from inline syntax (e.g. 'task: a, b, c')."""
        return self._subtask_reminders

    @classmethod
    def create_item(
        cls,
        parent=None,
        title: str = "Add Todo",
        known_tags: list[str] | None = None,
        columns: list[str] | None = None,
        selected_column: str | None = None,
    ) -> TodoItem | None:
        """Convenience method to show dialog and get result."""
        dialog = cls(
            parent,
            known_tags=known_tags,
            columns=columns,
            selected_column=selected_column,
        )
        dialog.setWindowTitle(title)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_item()
        return None
