"""Task detail panel — sliding QDockWidget showing full task metadata.

Docks to the right side of MainWindow. Updates when the user clicks
a task in any view (list, kanban, calendar). Shows every field that
affects the task's visual representation and behavior, organized in
a readable form layout.

The panel solves the "invisible metadata" UX gap: before this, the
user had no way to see fields like estimated_minutes, work_duration,
recurrence_interval, or created_at without querying the SQLite
database directly. The enriched tooltips (Phase 1) partially address
this for hover interactions; the detail panel provides a persistent,
scannable view.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDockWidget,
    QFormLayout,
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.models import TodoItem, format_duration


class TaskDetailPanel(QDockWidget):
    """Sliding detail panel showing full metadata of the selected task.

    Docks to the right side of MainWindow. The panel content updates
    whenever `set_item(item)` is called — MainWindow wires this to
    the selection signal from whichever view is active.

    `set_item(None)` clears the panel and shows a placeholder.
    """

    # Emitted when the user wants to edit a field. MainWindow handles
    # the actual persistence via the existing undo-command infrastructure.
    edit_requested = pyqtSignal(object, str, object)  # (item_id, field_name, new_value)

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
        self._setup_ui()

    def _setup_ui(self) -> None:
        # Scroll area wrapping the form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12, 12, 12, 12)
        self._content_layout.setSpacing(0)

        # Placeholder when no item is selected
        self._placeholder = QLabel(self.tr("Select a task to view details"))
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: palette(mid); font-style: italic;")
        self._content_layout.addWidget(self._placeholder)

        # Detail sections (hidden until an item is set)
        self._detail_widget = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_widget)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_layout.setSpacing(16)
        self._detail_widget.hide()
        self._content_layout.addWidget(self._detail_widget)

        self._content_layout.addStretch()

        scroll.setWidget(self._content)
        self.setWidget(scroll)

        # Build sections
        self._build_header_section()
        self._build_status_section()
        self._build_schedule_section()
        self._build_estimate_section()
        self._build_recurrence_section()
        self._build_tags_section()
        self._build_timing_section()
        self._build_meta_section()

    # --- Section builders ---

    def _add_section(self, title: str) -> QFormLayout:
        """Add a titled section with a form layout."""
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

        # Separator line
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
        """Create a value label with word-wrap and selectable text."""
        label = QLabel()
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return label

    def _build_header_section(self) -> None:
        self._reminder_label = QLabel()
        self._reminder_label.setWordWrap(True)
        self._reminder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(14)
        self._reminder_label.setFont(font)
        self._detail_layout.addWidget(self._reminder_label)

    def _build_status_section(self) -> None:
        form = self._add_section(self.tr("Status"))
        self._priority_value = self._make_value_label()
        self._status_value = self._make_value_label()
        self._completed_at_value = self._make_value_label()
        form.addRow(self.tr("Priority:"), self._priority_value)
        form.addRow(self.tr("Status:"), self._status_value)
        form.addRow(self.tr("Completed:"), self._completed_at_value)

    def _build_schedule_section(self) -> None:
        form = self._add_section(self.tr("Schedule"))
        self._due_date_value = self._make_value_label()
        self._due_time_value = self._make_value_label()
        self._time_block_value = self._make_value_label()
        self._event_date_value = self._make_value_label()
        form.addRow(self.tr("Due date:"), self._due_date_value)
        form.addRow(self.tr("Due time:"), self._due_time_value)
        form.addRow(self.tr("Time block:"), self._time_block_value)
        form.addRow(self.tr("Event date:"), self._event_date_value)

    def _build_estimate_section(self) -> None:
        form = self._add_section(self.tr("Estimates"))
        self._est_minutes_value = self._make_value_label()
        self._est_pomodoros_value = self._make_value_label()
        self._work_duration_value = self._make_value_label()
        self._effective_value = self._make_value_label()
        form.addRow(self.tr("Minutes:"), self._est_minutes_value)
        form.addRow(self.tr("Pomodoros:"), self._est_pomodoros_value)
        form.addRow(self.tr("Work dur:"), self._work_duration_value)
        form.addRow(self.tr("Effective:"), self._effective_value)

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
        self._tags_value = self._make_value_label()
        form.addRow(self._tags_value)

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

    # --- Public API ---

    def set_item(self, item: TodoItem | None) -> None:
        """Update the panel to show the given item's metadata.

        Pass None to clear the panel and show the placeholder.
        """
        self._item = item
        if item is None:
            self._detail_widget.hide()
            self._placeholder.show()
            return
        self._placeholder.hide()
        self._detail_widget.show()
        self._populate(item)

    def current_item_id(self) -> UUID | None:
        return self._item.id if self._item else None

    def sizeHint(self) -> QSize:
        return QSize(320, 600)

    # --- Field population ---

    def _populate(self, item: TodoItem) -> None:
        """Fill all fields from the item's current state."""
        # Header
        self._reminder_label.setText(item.reminder or "(no reminder)")

        # Status
        prio_names = {1: "High", 2: "Normal", 3: "Low"}
        prio_colors = {1: "#ef4444", 2: "#3b82f6", 3: "#6b7280"}
        prio = prio_names.get(item.priority, "Normal")
        prio_color = prio_colors.get(item.priority, "#3b82f6")
        self._priority_value.setText(f"<span style='color:{prio_color}'>{prio}</span>")

        if item.complete:
            self._status_value.setText("<span style='color:#22c55e'>Complete</span>")
            if item.completed_at is not None:
                dt = datetime.fromtimestamp(item.completed_at / 1000)
                self._completed_at_value.setText(dt.strftime("%b %d %Y %I:%M %p"))
            else:
                self._completed_at_value.setText(
                    "<span style='color:#f59e0b'>Unknown (pre-v19)</span>"
                )
        else:
            self._status_value.setText("Active")
            self._completed_at_value.setText("\u2014")

        # Schedule — compact date format to fit narrow panel
        if item.due_date:
            self._due_date_value.setText(item.due_date.strftime("%a, %b %d %Y"))
            if not item.complete and item.due_date < date.today():
                self._due_date_value.setStyleSheet("color: #ef4444; font-weight: bold;")
            else:
                self._due_date_value.setStyleSheet("")
        else:
            self._due_date_value.setText("\u2014")
            self._due_date_value.setStyleSheet("")

        if item.due_time:
            time_str = item.due_time.strftime("%I:%M %p").lstrip("0")
            if item.due_time_end:
                time_str += f" \u2013 {item.due_time_end.strftime('%I:%M %p').lstrip('0')}"
            self._due_time_value.setText(time_str)
        else:
            self._due_time_value.setText("All day" if item.due_date else "\u2014")

        if item.due_time_block:
            self._time_block_value.setText(item.due_time_block.replace("_", " ").title())
        else:
            self._time_block_value.setText("\u2014")

        if item.event_date:
            self._event_date_value.setText(item.event_date.strftime("%a, %b %d %Y"))
        else:
            self._event_date_value.setText("\u2014")

        # Estimates
        if item.estimated_minutes > 0:
            self._est_minutes_value.setText(f"{item.estimated_minutes} min")
        else:
            self._est_minutes_value.setText("\u2014")

        if item.estimated_pomodoros > 0:
            self._est_pomodoros_value.setText(str(item.estimated_pomodoros))
        else:
            self._est_pomodoros_value.setText("\u2014")

        if item.work_duration > 0:
            self._work_duration_value.setText(f"{item.work_duration} min (custom)")
        else:
            self._work_duration_value.setText("Default")

        # Effective duration calculation
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

        # Metadata — compact timestamps
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
