"""Task detail panel — sliding QDockWidget showing full task metadata.

Docks to the right side of MainWindow. Updates when the user clicks
a task in any view (list, kanban, calendar). Shows every field that
affects the task's visual representation and behavior, organized in
a readable form layout.

Two modes:
  - **View mode** (default): fields are read-only and styled as clean
    labels. The panel is a scannable reference.
  - **Edit mode** (pencil toggle): fields become interactive. Changes
    apply live (same as list/kanban inline editing). Toggle back to
    view mode when done.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from PyQt6.QtCore import QDate, QSize, Qt, QTime, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDockWidget,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.models import TodoItem, format_duration


class TaskDetailPanel(QDockWidget):
    """Sliding detail panel with view/edit toggle for task metadata."""

    # Signals matching the pattern other views use so MainWindow
    # handles them identically via existing undo-command infrastructure.
    edit_requested = pyqtSignal(object, str, object)  # (item_id, field_name, new_value)
    item_reminder_changed = pyqtSignal(object, str)
    item_priority_changed = pyqtSignal(object, int)
    item_due_date_changed = pyqtSignal(object, object)
    item_due_time_changed = pyqtSignal(object, object)
    toggle_requested = pyqtSignal()
    edit_tags_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Task Details"))
        self.setObjectName("TaskDetailPanel")
        self.setMinimumWidth(320)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        self._item: TodoItem | None = None
        self._populating = False
        self._edit_mode = False
        # Track all editable widgets for batch enable/disable
        self._editable_widgets: list[QWidget] = []
        self._setup_ui()
        self._set_edit_mode(False)

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12, 12, 12, 12)
        self._content_layout.setSpacing(0)

        # Placeholder
        self._placeholder = QLabel(self.tr("Select a task to view details"))
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: palette(mid); font-style: italic;")
        self._content_layout.addWidget(self._placeholder)

        # Detail sections
        self._detail_widget = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_widget)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_layout.setSpacing(16)
        self._detail_widget.hide()
        self._content_layout.addWidget(self._detail_widget)

        self._content_layout.addStretch()
        scroll.setWidget(self._content)
        self.setWidget(scroll)

        # Build all sections
        self._build_header_section()
        self._build_status_section()
        self._build_schedule_section()
        self._build_estimate_section()
        self._build_recurrence_section()
        self._build_tags_section()
        self._build_timing_section()
        self._build_meta_section()

    # ------------------------------------------------------------------
    # Read-only style for edit widgets in view mode
    # ------------------------------------------------------------------

    _VIEW_MODE_STYLE = (
        "QLineEdit, QSpinBox, QDateEdit, QTimeEdit, QComboBox {"
        "  border: none; background: transparent; padding: 1px 0px;"
        "}"
        "QCheckBox { background: transparent; }"
        "QSpinBox::up-button, QSpinBox::down-button,"
        "QDateEdit::up-button, QDateEdit::down-button,"
        "QDateEdit::drop-down, QTimeEdit::up-button,"
        "QTimeEdit::down-button, QComboBox::drop-down {"
        "  width: 0px; border: none;"
        "}"
    )

    _EDIT_MODE_STYLE = ""  # reset to default Qt styling

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _add_section(self, title: str) -> QFormLayout:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QLabel(title)
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPixelSize(11)
        header.setFont(header_font)
        header.setStyleSheet("color: palette(highlight); margin-bottom: 2px;")
        layout.addWidget(header)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("color: palette(mid);")
        layout.addWidget(line)

        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 0)
        form.setSpacing(4)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addLayout(form)

        self._detail_layout.addWidget(section)
        return form

    def _make_value_label(self) -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return label

    def _track_editable(self, widget: QWidget) -> QWidget:
        """Register a widget for batch view/edit mode toggling."""
        self._editable_widgets.append(widget)
        return widget

    def _build_header_section(self) -> None:
        # Top row: reminder + pencil toggle
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)

        self._reminder_edit = QLineEdit()
        self._reminder_edit.setPlaceholderText("Task name...")
        font = QFont()
        font.setBold(True)
        font.setPixelSize(14)
        self._reminder_edit.setFont(font)
        self._reminder_edit.editingFinished.connect(self._on_reminder_changed)
        self._track_editable(self._reminder_edit)
        header_row.addWidget(self._reminder_edit, 1)

        # Pencil toggle button
        self._edit_toggle_btn = QToolButton()
        self._edit_toggle_btn.setText("\u270e")  # ✎ pencil
        self._edit_toggle_btn.setCheckable(True)
        self._edit_toggle_btn.setToolTip(self.tr("Toggle edit mode"))
        self._edit_toggle_btn.setStyleSheet(
            "QToolButton { font-size: 16px; padding: 2px 4px;"
            " color: palette(highlight); border: none; }"
            "QToolButton:checked { background: palette(highlight);"
            " color: palette(highlightedText); border-radius: 3px; }"
        )
        self._edit_toggle_btn.toggled.connect(self._set_edit_mode)
        header_row.addWidget(self._edit_toggle_btn, 0)

        self._detail_layout.addLayout(header_row)

    def _on_reminder_changed(self) -> None:
        if self._populating or not self._edit_mode:
            return
        if self._item is not None:
            self.item_reminder_changed.emit(self._item.id, self._reminder_edit.text())

    def _build_status_section(self) -> None:
        form = self._add_section(self.tr("Status"))

        self._priority_combo = self._track_editable(QComboBox())
        self._priority_combo.addItem("High", 1)
        self._priority_combo.addItem("Normal", 2)
        self._priority_combo.addItem("Low", 3)
        self._priority_combo.currentIndexChanged.connect(self._on_priority_changed)

        self._complete_check = self._track_editable(QCheckBox(self.tr("Complete")))
        self._complete_check.toggled.connect(self._on_complete_toggled)

        self._completed_at_value = self._make_value_label()
        form.addRow(self.tr("Priority:"), self._priority_combo)
        form.addRow(self.tr("Status:"), self._complete_check)
        form.addRow(self.tr("Completed:"), self._completed_at_value)

    def _on_priority_changed(self, index: int) -> None:
        if self._populating or not self._edit_mode:
            return
        if self._item is not None:
            priority = self._priority_combo.itemData(index)
            if priority is not None:
                self.item_priority_changed.emit(self._item.id, priority)

    def _on_complete_toggled(self, checked: bool) -> None:
        if self._populating or not self._edit_mode:
            return
        self.toggle_requested.emit()

    def _build_schedule_section(self) -> None:
        form = self._add_section(self.tr("Schedule"))

        self._due_date_edit = self._track_editable(QDateEdit())
        self._due_date_edit.setCalendarPopup(True)
        self._due_date_edit.setSpecialValueText("No date")
        self._due_date_edit.setMinimumDate(QDate(1752, 9, 14))
        self._due_date_edit.dateChanged.connect(self._on_due_date_changed)

        self._due_time_edit = self._track_editable(QTimeEdit())
        self._due_time_edit.setDisplayFormat("hh:mm AP")
        self._due_time_edit.timeChanged.connect(self._on_due_time_changed)

        self._time_block_value = self._make_value_label()
        self._event_date_value = self._make_value_label()
        form.addRow(self.tr("Due date:"), self._due_date_edit)
        form.addRow(self.tr("Due time:"), self._due_time_edit)
        form.addRow(self.tr("Time block:"), self._time_block_value)
        form.addRow(self.tr("Event date:"), self._event_date_value)

    def _on_due_date_changed(self, qdate: QDate) -> None:
        if self._populating or not self._edit_mode:
            return
        if self._item is not None:
            if qdate == self._due_date_edit.minimumDate():
                self.item_due_date_changed.emit(self._item.id, None)
            else:
                self.item_due_date_changed.emit(
                    self._item.id, date(qdate.year(), qdate.month(), qdate.day())
                )

    def _on_due_time_changed(self, qtime: QTime) -> None:
        if self._populating or not self._edit_mode:
            return
        if self._item is not None:
            from datetime import time as time_type

            self.item_due_time_changed.emit(self._item.id, time_type(qtime.hour(), qtime.minute()))

    def _build_estimate_section(self) -> None:
        form = self._add_section(self.tr("Estimates"))

        self._est_minutes_spin = self._track_editable(QSpinBox())
        self._est_minutes_spin.setRange(0, 1440)
        self._est_minutes_spin.setSuffix(" min")
        self._est_minutes_spin.setSpecialValueText("\u2014")
        self._est_minutes_spin.valueChanged.connect(self._on_est_minutes_changed)

        self._est_pomodoros_spin = self._track_editable(QSpinBox())
        self._est_pomodoros_spin.setRange(0, 99)
        self._est_pomodoros_spin.setSpecialValueText("\u2014")
        self._est_pomodoros_spin.valueChanged.connect(self._on_est_pomodoros_changed)

        self._work_duration_value = self._make_value_label()
        self._effective_value = self._make_value_label()
        form.addRow(self.tr("Minutes:"), self._est_minutes_spin)
        form.addRow(self.tr("Pomodoros:"), self._est_pomodoros_spin)
        form.addRow(self.tr("Work dur:"), self._work_duration_value)
        form.addRow(self.tr("Effective:"), self._effective_value)

    def _on_est_minutes_changed(self, value: int) -> None:
        if self._populating or not self._edit_mode:
            return
        if self._item is not None:
            self.edit_requested.emit(self._item.id, "estimated_minutes", value)

    def _on_est_pomodoros_changed(self, value: int) -> None:
        if self._populating or not self._edit_mode:
            return
        if self._item is not None:
            self.edit_requested.emit(self._item.id, "estimated_pomodoros", value)

    def _build_recurrence_section(self) -> None:
        form = self._add_section(self.tr("Recurrence"))
        self._rec_type_value = self._make_value_label()
        self._rec_interval_value = self._make_value_label()
        self._rec_end_value = self._make_value_label()
        self._rec_count_value = self._make_value_label()
        self._rec_missed_value = self._make_value_label()
        form.addRow(self.tr("Type:"), self._rec_type_value)
        form.addRow(self.tr("Interval:"), self._rec_interval_value)
        form.addRow(self.tr("End:"), self._rec_end_value)
        form.addRow(self.tr("Count:"), self._rec_count_value)
        form.addRow(self.tr("Missed:"), self._rec_missed_value)

    def _build_tags_section(self) -> None:
        form = self._add_section(self.tr("Tags"))
        tags_container = QWidget()
        tags_layout = QHBoxLayout(tags_container)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(4)

        self._tags_value = self._make_value_label()
        tags_layout.addWidget(self._tags_value, 1)

        self._tags_edit_btn = QPushButton(self.tr("Edit"))
        self._tags_edit_btn.setFixedWidth(40)
        self._tags_edit_btn.clicked.connect(self._on_edit_tags_clicked)
        self._track_editable(self._tags_edit_btn)
        tags_layout.addWidget(self._tags_edit_btn, 0)

        form.addRow(tags_container)

    def _on_edit_tags_clicked(self) -> None:
        if self._item is not None:
            self.edit_tags_requested.emit(self._item.id)

    def _build_timing_section(self) -> None:
        form = self._add_section(self.tr("Focus Sessions"))
        self._time_spent_value = self._make_value_label()
        self._session_count_value = self._make_value_label()
        form.addRow(self.tr("Time spent:"), self._time_spent_value)
        form.addRow(self.tr("Sessions:"), self._session_count_value)

    def _build_meta_section(self) -> None:
        form = self._add_section(self.tr("Metadata"))
        self._created_value = self._make_value_label()
        self._updated_value = self._make_value_label()
        self._id_value = self._make_value_label()
        self._parent_value = self._make_value_label()
        self._board_value = self._make_value_label()
        form.addRow(self.tr("Created:"), self._created_value)
        form.addRow(self.tr("Updated:"), self._updated_value)
        form.addRow(self.tr("ID:"), self._id_value)
        form.addRow(self.tr("Parent:"), self._parent_value)
        form.addRow(self.tr("Board:"), self._board_value)

    # ------------------------------------------------------------------
    # View / Edit mode toggle
    # ------------------------------------------------------------------

    def _set_edit_mode(self, enabled: bool) -> None:
        """Toggle between view mode (read-only) and edit mode (interactive)."""
        self._edit_mode = enabled
        for w in self._editable_widgets:
            if isinstance(w, (QLineEdit,)):
                w.setReadOnly(not enabled)
            elif isinstance(w, (QDateEdit, QTimeEdit)):
                w.setReadOnly(not enabled)
                w.setButtonSymbols(
                    QDateEdit.ButtonSymbols.UpDownArrows
                    if enabled
                    else QDateEdit.ButtonSymbols.NoButtons
                )
            else:
                w.setEnabled(enabled)
        # Stylesheet swap: view mode hides borders/buttons for clean look
        style = self._EDIT_MODE_STYLE if enabled else self._VIEW_MODE_STYLE
        self._detail_widget.setStyleSheet(style)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_item(self, item: TodoItem | None) -> None:
        self._item = item
        if item is None:
            self._detail_widget.hide()
            self._placeholder.show()
            return
        self._placeholder.hide()
        self._detail_widget.show()
        self._populate(item)

    def set_edit_mode(self, enabled: bool) -> None:
        """Enter or leave edit mode programmatically.

        Routes through the existing edit-toggle button so the visible
        button state, the editable-widget enable/disable cascade, and
        the stylesheet swap all stay in sync regardless of who flipped
        the mode.
        """
        if self._edit_toggle_btn.isChecked() == enabled:
            # Button is already in the requested state — fire the
            # internal handler directly so callers can rely on the
            # call having an effect even when no toggled signal would
            # otherwise emit.
            self._set_edit_mode(enabled)
            return
        self._edit_toggle_btn.setChecked(enabled)

    def current_item_id(self) -> UUID | None:
        return self._item.id if self._item else None

    def sizeHint(self) -> QSize:
        return QSize(320, 600)

    # ------------------------------------------------------------------
    # Field population
    # ------------------------------------------------------------------

    def _populate(self, item: TodoItem) -> None:
        self._populating = True
        try:
            self._populate_inner(item)
        finally:
            self._populating = False

    def _populate_inner(self, item: TodoItem) -> None:
        # Header
        self._reminder_edit.setText(item.reminder or "")

        # Status
        self._priority_combo.setCurrentIndex(item.priority - 1)
        self._complete_check.setChecked(item.complete)

        if item.complete:
            if item.completed_at is not None:
                dt = datetime.fromtimestamp(item.completed_at / 1000)
                self._completed_at_value.setText(dt.strftime("%b %d %Y %I:%M %p"))
            else:
                self._completed_at_value.setText(
                    "<span style='color:#f59e0b'>Unknown (pre-v19)</span>"
                )
        else:
            self._completed_at_value.setText("\u2014")

        # Schedule
        if item.due_date:
            self._due_date_edit.setDate(
                QDate(item.due_date.year, item.due_date.month, item.due_date.day)
            )
        else:
            self._due_date_edit.setDate(self._due_date_edit.minimumDate())

        if item.due_time:
            self._due_time_edit.setTime(QTime(item.due_time.hour, item.due_time.minute))
        else:
            self._due_time_edit.setTime(QTime(0, 0))

        if item.due_time_block:
            self._time_block_value.setText(item.due_time_block.replace("_", " ").title())
        else:
            self._time_block_value.setText("\u2014")

        if item.event_date:
            self._event_date_value.setText(item.event_date.strftime("%a, %b %d %Y"))
        else:
            self._event_date_value.setText("\u2014")

        # Estimates
        self._est_minutes_spin.setValue(item.estimated_minutes)
        self._est_pomodoros_spin.setValue(item.estimated_pomodoros)

        if item.work_duration > 0:
            self._work_duration_value.setText(f"{item.work_duration} min (custom)")
        else:
            self._work_duration_value.setText("Default")

        # Effective duration
        direct = max(0, item.estimated_minutes)
        per_work = item.work_duration if item.work_duration > 0 else 25
        pom_total = max(0, item.estimated_pomodoros) * per_work
        effective = max(direct, pom_total)
        if effective > 0:
            parts = []
            if direct > 0 and pom_total > 0:
                parts.append(f"max({direct}, {item.estimated_pomodoros}\u00d7{per_work})")
            parts.append(f"= {effective} min")
            if effective >= 60:
                h, m = divmod(effective, 60)
                parts.append(f"({h}h {m}m)" if m else f"({h}h)")
            self._effective_value.setText(" ".join(parts))
        elif item.due_time is not None:
            self._effective_value.setText(
                "<span style='color:#f59e0b'>None \u2192 1h deadline clamp</span>"
            )
        else:
            self._effective_value.setText("\u2014")

        # Recurrence
        if item.recurrence_type:
            self._rec_type_value.setText(item.recurrence_type.capitalize())
            self._rec_interval_value.setText(
                f"Every {item.recurrence_interval} "
                f"{item.recurrence_type.rstrip('ly')}"
                f"{'s' if item.recurrence_interval > 1 else ''}"
                if item.recurrence_interval > 1
                else "Every cycle"
            )
            if item.recurrence_end_date:
                self._rec_end_value.setText(
                    f"Until {item.recurrence_end_date.strftime('%b %d, %Y')}"
                )
            elif item.recurrence_end_count is not None:
                self._rec_end_value.setText(f"After {item.recurrence_end_count} occurrences")
            else:
                self._rec_end_value.setText("No end")
            self._rec_count_value.setText(f"{item.recurrence_count} completed")
            if item.missed_recurrences > 0:
                self._rec_missed_value.setText(
                    f"<span style='color:#ef4444'>{item.missed_recurrences} auto-advanced</span>"
                )
            else:
                self._rec_missed_value.setText("0")
        else:
            self._rec_type_value.setText("\u2014")
            self._rec_interval_value.setText("\u2014")
            self._rec_end_value.setText("\u2014")
            self._rec_count_value.setText("\u2014")
            self._rec_missed_value.setText("\u2014")

        # Tags
        if item.tags:
            chips = " ".join(
                f"<span style='background: palette(mid); padding: 1px 6px; "
                f"border-radius: 3px;'>{tag}</span>"
                for tag in item.tags
            )
            self._tags_value.setText(chips)
        else:
            self._tags_value.setText("<i>No tags</i>")

        # Focus sessions
        if item.time_spent > 0:
            spent_min = item.time_spent // 60
            self._time_spent_value.setText(format_duration(spent_min))
        else:
            self._time_spent_value.setText("\u2014")
        self._session_count_value.setText(
            f"{item.pomodoro_count}"
            + (f" / {item.estimated_pomodoros} estimated" if item.estimated_pomodoros else "")
        )

        # Metadata
        created = datetime.fromtimestamp(item.created_at / 1000)
        self._created_value.setText(created.strftime("%b %d %Y %I:%M %p"))
        updated = datetime.fromtimestamp(item.updated_at / 1000)
        self._updated_value.setText(updated.strftime("%b %d %Y %I:%M %p"))
        self._id_value.setText(str(item.id))
        self._id_value.setStyleSheet("font-family: monospace; font-size: 10px;")
        if item.parent_id:
            self._parent_value.setText(str(item.parent_id))
            self._parent_value.setStyleSheet("font-family: monospace; font-size: 10px;")
        else:
            self._parent_value.setText("\u2014")
            self._parent_value.setStyleSheet("")
        self._board_value.setText(item.board_column or "\u2014")
