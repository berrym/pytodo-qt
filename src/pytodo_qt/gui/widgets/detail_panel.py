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
from typing import TypeVar
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

from ...core.models import TodoItem, TodoList, format_duration

_W = TypeVar("_W", bound=QWidget)


class TaskDetailPanel(QDockWidget):
    """Sliding detail panel with view/edit toggle for task metadata."""

    # Signals matching the pattern other views use so MainWindow
    # handles them identically via existing undo-command infrastructure.
    edit_requested = pyqtSignal(object, str, object)  # (item_id, field_name, new_value)
    item_reminder_changed = pyqtSignal(object, str)
    item_priority_changed = pyqtSignal(object, int)
    item_due_date_changed = pyqtSignal(object, object)
    item_due_time_changed = pyqtSignal(object, object)
    item_due_time_end_changed = pyqtSignal(object, object)
    item_location_changed = pyqtSignal(object, str)
    toggle_requested = pyqtSignal()
    edit_tags_requested = pyqtSignal(object)
    # Subtask CRUD: emitted so MainWindow can route each action through
    # the same undo-command paths the rest of the app already uses.
    # The panel is the view layer; it never mutates the model directly.
    subtask_add_requested = pyqtSignal(object)  # parent_id
    subtask_delete_requested = pyqtSignal(object)  # subtask_id
    subtask_complete_toggled = pyqtSignal(object, bool)  # subtask_id, checked
    subtask_selected = pyqtSignal(object)  # item_id — drill-down navigation
    # Breadcrumb navigation back to a subtask's parent task.
    parent_navigation_requested = pyqtSignal(object)  # parent_id

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
        self._todo_list: TodoList | None = None
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
        self._build_subtasks_section()
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

    def _track_editable(self, widget: _W) -> _W:
        """Register a widget for batch view/edit mode toggling."""
        self._editable_widgets.append(widget)
        return widget

    def _build_header_section(self) -> None:
        # Parent breadcrumb — only visible when the current item has a
        # parent_id. Clicking navigates the detail panel up to the
        # parent, matching the drill-down semantics in the Subtasks
        # section below.
        self._parent_breadcrumb = QPushButton()
        self._parent_breadcrumb.setFlat(True)
        self._parent_breadcrumb.setCursor(Qt.CursorShape.PointingHandCursor)
        self._parent_breadcrumb.setStyleSheet(
            "QPushButton { text-align: left; color: palette(highlight);"
            " background: transparent; border: none; padding: 0 0 4px 0;"
            " font-size: 11px; }"
            "QPushButton:hover { text-decoration: underline; }"
        )
        self._parent_breadcrumb.clicked.connect(self._on_parent_breadcrumb_clicked)
        self._parent_breadcrumb.hide()
        self._detail_layout.addWidget(self._parent_breadcrumb)

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

        # Join meeting — visible only when the reminder contains a
        # recognized video-conference URL. Sits directly under the
        # title row so it reads as a primary action.
        self._join_meeting_btn = QPushButton()
        self._join_meeting_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._join_meeting_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 6px 10px;"
            " border: 1px solid palette(highlight); border-radius: 4px;"
            " color: palette(highlightedText);"
            " background: palette(highlight); font-weight: bold; }"
            "QPushButton:hover { padding: 6px 10px; }"
        )
        self._join_meeting_btn.clicked.connect(self._on_join_meeting_clicked)
        self._join_meeting_btn.hide()
        self._detail_layout.addWidget(self._join_meeting_btn)
        self._meeting_link_url: str | None = None

    def _on_parent_breadcrumb_clicked(self) -> None:
        if self._item is not None and self._item.parent_id is not None:
            self.parent_navigation_requested.emit(self._item.parent_id)

    def _on_join_meeting_clicked(self) -> None:
        """Open the detected meeting URL in the system's default browser."""
        if not self._meeting_link_url:
            return
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(self._meeting_link_url))

    def _refresh_meeting_link_button(self, item: TodoItem | None) -> None:
        """Show or hide the Join button based on the reminder content."""
        from ...core.meeting_link import detect_meeting_link

        if item is None:
            self._meeting_link_url = None
            self._join_meeting_btn.hide()
            return
        link = detect_meeting_link(item.reminder)
        if link is None:
            self._meeting_link_url = None
            self._join_meeting_btn.hide()
            return
        self._meeting_link_url = link.url
        self._join_meeting_btn.setText(
            self.tr("Join {provider} meeting").format(provider=link.provider)
        )
        self._join_meeting_btn.show()

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
        # Calendar lifecycle state (Future / In progress / Due soon / Overdue /
        # Completed) shown as plain text. The calendar legend's color channel
        # already carries this information; surfacing it here in words is the
        # WCAG 1.4.1 redundancy required for users who can't easily resolve
        # the legend's two-green palette at small swatch sizes.
        self._lifecycle_value = self._make_value_label()
        form.addRow(self.tr("Priority:"), self._priority_combo)
        form.addRow(self.tr("Status:"), self._complete_check)
        form.addRow(self.tr("Completed:"), self._completed_at_value)
        form.addRow(self.tr("Lifecycle:"), self._lifecycle_value)

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

        self._due_time_end_edit = self._track_editable(QTimeEdit())
        self._due_time_end_edit.setDisplayFormat("hh:mm AP")
        self._due_time_end_edit.timeChanged.connect(self._on_due_time_end_changed)

        self._time_block_value = self._make_value_label()
        self._event_date_value = self._make_value_label()
        # Location — free-form text, edit-mode-gated like the other
        # row-level edits in this section. Round-trips through VTODO
        # LOCATION for CalDAV interop.
        self._location_edit = self._track_editable(QLineEdit())
        self._location_edit.setPlaceholderText(
            self.tr("e.g. Conference Room B, 123 Main St, phone call")
        )
        self._location_edit.editingFinished.connect(self._on_location_changed)
        form.addRow(self.tr("Due date:"), self._due_date_edit)
        form.addRow(self.tr("Due time:"), self._due_time_edit)
        form.addRow(self.tr("End time:"), self._due_time_end_edit)
        form.addRow(self.tr("Time block:"), self._time_block_value)
        form.addRow(self.tr("Event date:"), self._event_date_value)
        form.addRow(self.tr("Location:"), self._location_edit)

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

    def _on_due_time_end_changed(self, qtime: QTime) -> None:
        if self._populating or not self._edit_mode:
            return
        if self._item is not None:
            from datetime import time as time_type

            self.item_due_time_end_changed.emit(
                self._item.id, time_type(qtime.hour(), qtime.minute())
            )

    def _on_location_changed(self) -> None:
        if self._populating or not self._edit_mode:
            return
        if self._item is not None:
            new_location = self._location_edit.text().strip()
            if new_location != (self._item.location or ""):
                self.item_location_changed.emit(self._item.id, new_location)

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

    def _build_subtasks_section(self) -> None:
        """Subtasks list + add/delete/toggle/select controls.

        Nesting is intentionally single-layer: a subtask cannot have
        its own subtasks. When the current item is itself a subtask,
        the "+ Add Subtask" button is hidden. The controls route
        through MainWindow's existing undo-command paths via the
        signals declared on this class; no direct model mutation
        happens here.
        """
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QLabel(self.tr("Subtasks"))
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

        self._subtasks_container = QWidget()
        self._subtasks_layout = QVBoxLayout(self._subtasks_container)
        self._subtasks_layout.setContentsMargins(0, 4, 0, 0)
        self._subtasks_layout.setSpacing(2)
        layout.addWidget(self._subtasks_container)

        self._subtasks_empty_label = QLabel(self.tr("No subtasks. Click + Add Subtask to add one."))
        self._subtasks_empty_label.setStyleSheet(
            "color: palette(placeholderText); font-style: italic; font-size: 10px;"
        )
        self._subtasks_empty_label.setWordWrap(True)
        self._subtasks_layout.addWidget(self._subtasks_empty_label)

        # + Add Subtask is always visible for top-level items — not gated
        # behind edit mode — so the instructional empty-state text ("click
        # + Add Subtask to add one") resolves to a control the user can
        # actually see. Opens a confirmation dialog, so it's not a
        # destructive control and does not need a safety gate. The button
        # is hidden when the current item is itself a subtask (single-
        # layer nesting rule).
        self._add_subtask_btn = QPushButton(self.tr("+ Add Subtask"))
        self._add_subtask_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 4px 6px;"
            " color: palette(highlight); border: 1px dashed palette(mid);"
            " border-radius: 3px; background: transparent; }"
            "QPushButton:hover { background: palette(alternate-base); }"
        )
        self._add_subtask_btn.clicked.connect(self._on_add_subtask_clicked)
        layout.addWidget(self._add_subtask_btn)

        self._detail_layout.addWidget(section)

    def _on_add_subtask_clicked(self) -> None:
        if self._item is not None and self._item.parent_id is None:
            self.subtask_add_requested.emit(self._item.id)

    def _populate_subtasks(self, item: TodoItem) -> None:
        """Render a row per child of ``item``. Clears previous rows
        first so repeated calls do not accumulate widgets. The
        ``+ Add Subtask`` button is visible whenever the current item
        is top-level — not gated on edit mode, since it opens a
        confirmation dialog rather than mutating state directly."""
        # Clear any previously rendered subtask rows.
        while self._subtasks_layout.count() > 0:
            layout_item = self._subtasks_layout.takeAt(0)
            if layout_item is None:
                continue
            w = layout_item.widget()
            if w is not None and w is not self._subtasks_empty_label:
                w.setParent(None)
                w.deleteLater()

        # Re-insert the empty-state label; it will be hidden below
        # when there are children to show.
        self._subtasks_layout.addWidget(self._subtasks_empty_label)

        is_top_level = item.parent_id is None
        children: list[TodoItem] = []
        if is_top_level and self._todo_list is not None:
            children = [i for i in self._todo_list.active_items() if i.parent_id == item.id]

        if children:
            self._subtasks_empty_label.hide()
            for child in children:
                self._subtasks_layout.addWidget(self._build_subtask_row(child))
        else:
            self._subtasks_empty_label.show()

        # Add-button visibility depends purely on item shape. Single-
        # layer nesting means only top-level items can gain children.
        self._add_subtask_btn.setVisible(is_top_level)

    def _build_subtask_row(self, child: TodoItem) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(6)

        check = QCheckBox()
        check.setChecked(child.complete)
        check.toggled.connect(
            lambda checked, cid=child.id: self.subtask_complete_toggled.emit(cid, checked)
        )
        row_layout.addWidget(check)

        title_btn = QPushButton(child.reminder or self.tr("(untitled)"))
        title_btn.setFlat(True)
        title_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        strike = "text-decoration: line-through;" if child.complete else ""
        title_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 1px 4px;"
            f" background: transparent; border: none; {strike} }}"
            "QPushButton:hover { text-decoration: underline; }"
        )
        title_btn.clicked.connect(
            lambda _checked=False, cid=child.id: self.subtask_selected.emit(cid)
        )
        row_layout.addWidget(title_btn, 1)

        delete_btn = QPushButton("\u2715")
        delete_btn.setFixedSize(20, 20)
        delete_btn.setToolTip(self.tr("Delete subtask"))
        delete_btn.setStyleSheet(
            "QPushButton { border: none; color: palette(mid); background: transparent; }"
            "QPushButton:hover { color: palette(window-text); }"
        )
        delete_btn.clicked.connect(
            lambda _checked=False, cid=child.id: self.subtask_delete_requested.emit(cid)
        )
        delete_btn.setVisible(self._edit_mode)
        # Stash on the row so _set_edit_mode can flip visibility when
        # the user toggles edit mode without a full re-populate.
        row._delete_btn = delete_btn  # type: ignore[attr-defined]
        row_layout.addWidget(delete_btn)

        return row

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

        # Subtasks: per-row delete glyphs are the destructive controls,
        # so they flip visibility with edit mode. The + Add Subtask
        # button is non-destructive (opens a confirmation dialog) and
        # stays visible whenever the current item is top-level — its
        # visibility is managed by _populate_subtasks based on item
        # shape, not edit mode.
        if hasattr(self, "_subtasks_layout"):
            for i in range(self._subtasks_layout.count()):
                layout_item = self._subtasks_layout.itemAt(i)
                if layout_item is None:
                    continue
                w = layout_item.widget()
                delete_btn = getattr(w, "_delete_btn", None) if w is not None else None
                if delete_btn is not None:
                    delete_btn.setVisible(enabled)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_item(self, item: TodoItem | None, todo_list: TodoList | None = None) -> None:
        """Bind the panel to a task. When ``todo_list`` is provided,
        the Subtasks section can enumerate child items and the parent
        breadcrumb can resolve the parent's title; when it is None,
        those surfaces show empty state."""
        self._item = item
        self._todo_list = todo_list
        self._refresh_meeting_link_button(item)
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

        # Parent breadcrumb — visible only when viewing a subtask. The
        # label resolves the parent's reminder when the todo_list is
        # available; otherwise it falls back to a generic back label
        # so the breadcrumb is still functional without the list.
        if item.parent_id is not None:
            parent_reminder = None
            if self._todo_list is not None:
                parent = self._todo_list.get_item(item.parent_id)
                if parent is not None:
                    parent_reminder = parent.reminder
            label_text = (
                f"\u2190  {parent_reminder}"
                if parent_reminder
                else self.tr("\u2190  Back to parent task")
            )
            self._parent_breadcrumb.setText(label_text)
            self._parent_breadcrumb.show()
        else:
            self._parent_breadcrumb.hide()

        # Subtasks — populated from the todo_list's direct children of
        # this item. Each row wires into a MainWindow-handled signal
        # so edits go through the same undo/redo infrastructure as the
        # rest of the app.
        self._populate_subtasks(item)

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

        # Lifecycle state — computed from compute_bar_state against "now", so
        # the panel agrees with whatever the calendar bar currently shows.
        # Items with no due_date have no window and therefore no lifecycle.
        from ...core.calendar_layout import compute_bar_state, compute_bar_window
        from .calendar_view import bar_state_label

        window = compute_bar_window(item)
        if window is not None:
            state = compute_bar_state(item, window, datetime.now())
            self._lifecycle_value.setText(bar_state_label(state))
        else:
            self._lifecycle_value.setText("\u2014")

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

        if item.due_time_end:
            self._due_time_end_edit.setTime(QTime(item.due_time_end.hour, item.due_time_end.minute))
        else:
            self._due_time_end_edit.setTime(QTime(0, 0))

        if item.due_time_block:
            self._time_block_value.setText(item.due_time_block.replace("_", " ").title())
        else:
            self._time_block_value.setText("\u2014")

        if item.event_date:
            self._event_date_value.setText(item.event_date.strftime("%a, %b %d %Y"))
        else:
            self._event_date_value.setText("\u2014")

        self._location_edit.setText(item.location or "")

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
        # Use the MONO_FONT_FAMILIES stack rather than the CSS
        # generic "monospace" — the generic triggers a Qt font-alias
        # resolution cost and a console warning on systems where it
        # doesn't resolve to an installed family.
        from ..styles.themes import MONO_FONT_FAMILIES

        mono_css = ", ".join(f'"{f}"' for f in MONO_FONT_FAMILIES)
        self._id_value.setText(str(item.id))
        self._id_value.setStyleSheet(f"font-family: {mono_css}; font-size: 10px;")
        if item.parent_id:
            self._parent_value.setText(str(item.parent_id))
            self._parent_value.setStyleSheet(f"font-family: {mono_css}; font-size: 10px;")
        else:
            self._parent_value.setText("\u2014")
            self._parent_value.setStyleSheet("")
        self._board_value.setText(item.board_column or "\u2014")
