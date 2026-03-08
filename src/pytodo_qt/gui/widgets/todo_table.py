"""todo_table.py

Table widget for displaying and editing to-do items.
"""

from __future__ import annotations

import contextlib
from datetime import date, time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtCore import QDate, QEvent, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton,
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
    QMenu,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.logger import Logger
from ...core.models import (
    TodoItem,
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


def _sort_fragment(item: TodoItem, dimension: str, reverse: bool) -> tuple:
    """Return a comparable tuple fragment for one sort dimension."""
    if dimension == "completion":
        val = 1 if item.complete else 0
        return (-val,) if reverse else (val,)
    elif dimension == "due_date":
        if item.due_date is None:
            return (1, 0, 0)
        date_ord = item.due_date.toordinal()
        time_secs = (
            item.due_time.hour * 3600 + item.due_time.minute * 60 + item.due_time.second
            if item.due_time
            else -1
        )
        return (0, -date_ord, -time_secs) if reverse else (0, date_ord, time_secs)
    elif dimension == "priority":
        val = item.priority
        return (-val,) if reverse else (val,)
    return ()


class ClickableLabel(QLabel):
    """QLabel that emits a clicked signal on mouse press."""

    clicked = pyqtSignal()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        self.clicked.emit()


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
        if a0 is not None and a0.button() == Qt.MouseButton.RightButton:
            # Let right-click propagate to parent table for context menu
            a0.ignore()
            return
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
    edit_tags_requested = pyqtSignal(object)  # (item_id)
    toggle_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    edit_recurrence_requested = pyqtSignal()
    focus_requested = pyqtSignal(object)  # (item_id)
    add_subtask_requested = pyqtSignal(object)  # (parent_id)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_list: TodoList | None = None
        self._item_id_map: dict[int, UUID] = {}  # row -> item_id
        self._filter_state: FilterState | None = None
        self._v_header_filter_installed = False
        self._ellipsis_pairs: list[tuple[QLineEdit, ClickableLabel]] = []
        self._collapsed_parents: set[UUID] = set()
        self._context_row_ids: set[UUID] = set()

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
            header.sectionResized.connect(self._update_ellipsis_visibility)

        # Set row height so text is readable
        v_header = self.verticalHeader()
        if v_header:
            v_header.setDefaultSectionSize(42)

        # Corner button: toggle select-all / deselect-all
        corner = self.findChild(QAbstractButton)
        if corner:
            corner.clicked.disconnect()
            corner.clicked.connect(self._on_corner_clicked)

        # Selection behavior
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Tooltips
        self.setToolTip("Your to-do list")

        # Alternating row colors
        self.setAlternatingRowColors(True)

        # Connect selection changed
        self.itemSelectionChanged.connect(self._on_selection_changed)

        # Context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def _on_context_menu(self, pos: QPoint) -> None:
        """Show context menu for the table."""
        item_ids = self.get_selected_item_ids()
        if not item_ids:
            return

        menu = QMenu(self)

        if len(item_ids) == 1:
            edit_tags_action = QAction("Edit Tags...", self)
            edit_tags_action.triggered.connect(lambda: self.edit_tags_requested.emit(item_ids[0]))
            menu.addAction(edit_tags_action)

            edit_rec_action = QAction("Edit Recurrence...", self)
            edit_rec_action.triggered.connect(self.edit_recurrence_requested.emit)
            menu.addAction(edit_rec_action)

            focus_action = QAction("Start Focus Session", self)
            focus_action.triggered.connect(
                lambda checked=False, iid=item_ids[0]: self.focus_requested.emit(iid)
            )
            menu.addAction(focus_action)

            # Only allow adding subtasks to top-level items
            item = self._current_list.get_item(item_ids[0]) if self._current_list else None
            if item and item.parent_id is None:
                add_subtask_action = QAction("Add Subtask...", self)
                add_subtask_action.triggered.connect(
                    lambda checked=False, iid=item_ids[0]: self.add_subtask_requested.emit(iid)
                )
                menu.addAction(add_subtask_action)

            menu.addSeparator()

        toggle_action = QAction("Toggle Complete", self)
        toggle_action.triggered.connect(self.toggle_requested.emit)
        menu.addAction(toggle_action)

        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(self.delete_requested.emit)
        menu.addAction(delete_action)

        viewport = self.viewport()
        assert viewport is not None
        menu.exec(viewport.mapToGlobal(pos))

    def showEvent(self, a0) -> None:  # noqa: N802
        """Install header viewport event filter on first show."""
        super().showEvent(a0)
        if not self._v_header_filter_installed:
            v_header = self.verticalHeader()
            if v_header:
                vp = v_header.viewport()
                if vp:
                    vp.installEventFilter(self)
                    self._v_header_filter_installed = True

    def resizeEvent(self, e) -> None:  # noqa: N802
        """Update ellipsis visibility when table resizes (e.g. scrollbar appears)."""
        super().resizeEvent(e)
        if self._ellipsis_pairs:
            self._update_ellipsis_visibility()

    def _on_corner_clicked(self) -> None:
        """Toggle between select-all and deselect-all."""
        sm = self.selectionModel()
        if sm and len(sm.selectedRows()) == self.rowCount():
            self.clearSelection()
        else:
            self.selectAll()

    def eventFilter(self, object, event):  # noqa: N802, A002
        """Toggle row selection when vertical header is clicked."""
        v_header = self.verticalHeader()
        if (
            v_header
            and object is v_header.viewport()
            and isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            row = v_header.logicalIndexAt(event.position().toPoint())
            sm = self.selectionModel()
            m = self.model()
            if row >= 0 and sm and m:
                if sm.isRowSelected(row):
                    sm.select(
                        m.index(row, 0),
                        sm.SelectionFlag.Deselect | sm.SelectionFlag.Rows,
                    )
                else:
                    sm.select(
                        m.index(row, 0),
                        sm.SelectionFlag.Select | sm.SelectionFlag.Rows,
                    )
                return True
        return super().eventFilter(object, event)

    def set_list(self, todo_list: TodoList | None) -> None:
        """Set the list to display."""
        self._current_list = todo_list
        self.refresh()

    def set_filter(self, filter_state: FilterState | None) -> None:
        """Set the current filter and refresh display."""
        self._filter_state = filter_state
        self.refresh()

    def _apply_filter(self, items: list) -> list:
        """Filter items based on current filter state.

        When a child matches but its parent doesn't, the parent is added as a
        context row (muted styling, read-only) so the hierarchy remains visible.
        """
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

        # Pull in parent context rows for children whose parents aren't in results
        filtered_ids = {i.id for i in filtered}
        items_by_id = {i.id: i for i in items}
        self._context_row_ids.clear()
        parents_to_add: list[TodoItem] = []
        for item in filtered:
            if item.parent_id and item.parent_id not in filtered_ids:
                parent = items_by_id.get(item.parent_id)
                if parent and parent.id not in self._context_row_ids:
                    self._context_row_ids.add(parent.id)
                    parents_to_add.append(parent)
                    filtered_ids.add(parent.id)
        filtered.extend(parents_to_add)
        return filtered

    def _build_display_order(self, items: list[TodoItem], sort_key) -> list[tuple[TodoItem, bool]]:
        """Build hierarchical display order: parents followed by their children.

        Returns list of (item, is_child) tuples.
        """
        active_ids = {i.id for i in items}
        top_level: list[TodoItem] = []
        children_by_parent: dict[UUID, list[TodoItem]] = {}

        for item in items:
            if item.parent_id is None or item.parent_id not in active_ids:
                # Top-level item or orphan (parent deleted/filtered)
                top_level.append(item)
            else:
                children_by_parent.setdefault(item.parent_id, []).append(item)

        # Sort top-level items
        with contextlib.suppress(Exception):
            top_level.sort(key=sort_key)

        # Sort children within each group
        for children in children_by_parent.values():
            with contextlib.suppress(Exception):
                children.sort(key=sort_key)

        result: list[tuple[TodoItem, bool]] = []
        for item in top_level:
            result.append((item, False))
            if item.id not in self._collapsed_parents:
                for child in children_by_parent.get(item.id, []):
                    result.append((child, True))
        return result

    def _toggle_collapse(self, parent_id: UUID) -> None:
        """Toggle collapse state of a parent item."""
        if parent_id in self._collapsed_parents:
            self._collapsed_parents.discard(parent_id)
        else:
            self._collapsed_parents.add(parent_id)
        self.refresh()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        """Handle keyboard shortcuts for collapse/expand."""
        if self._current_list and e is not None:
            selected = self.get_selected_item_ids()
            if len(selected) == 1:
                item = self._current_list.get_item(selected[0])
                if item and item.parent_id is None:
                    if e.key() == Qt.Key.Key_Left and item.id not in self._collapsed_parents:
                        self._toggle_collapse(item.id)
                        return
                    if e.key() == Qt.Key.Key_Right and item.id in self._collapsed_parents:
                        self._toggle_collapse(item.id)
                        return
        super().keyPressEvent(e)

    def refresh(self) -> None:
        """Refresh the table contents."""
        self.setRowCount(0)
        self._item_id_map.clear()
        self._ellipsis_pairs.clear()
        self._context_row_ids.clear()

        if self._current_list is None:
            return

        colors = get_colors()

        # Load config once for sort order and time format
        from ...core.config import ConfigManager

        try:
            config = ConfigManager().load()
            sort_tiers = config.database.sort_tiers()
            time_fmt = config.appearance.time_format
        except Exception:
            logger.log.exception("Failed to load config for table refresh")
            sort_tiers = [("completion", False), ("due_date", False), ("priority", False)]
            time_fmt = "system"

        def sort_key(item):
            key: list = []
            for dimension, reverse in sort_tiers:
                key.extend(_sort_fragment(item, dimension, reverse))
            key.append(item.reminder.lower())
            return tuple(key)

        try:
            items = sorted(self._current_list.active_items(), key=sort_key)
        except Exception:
            logger.log.exception("Sort failed, falling back to unsorted")
            items = list(self._current_list.active_items())

        # Apply filter if active
        if self._filter_state is not None and self._filter_state.is_active:
            items = self._apply_filter(items)

        # Build hierarchical display order
        display_items = self._build_display_order(items, sort_key)

        # Pre-compute children info for parent badges
        children_by_parent: dict[UUID, list[TodoItem]] = {}
        for item in items:
            if item.parent_id is not None:
                children_by_parent.setdefault(item.parent_id, []).append(item)

        for row, (item, is_child) in enumerate(display_items):
            is_context = item.id in self._context_row_ids
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

            # Child indentation
            if is_child:
                indent = QWidget()
                indent.setFixedWidth(24)
                reminder_layout.addWidget(indent)
                prefix = QLabel("\u203a")  # Single right-pointing angle quotation mark
                prefix.setStyleSheet(f"color: {colors['completed_text']}; font-size: 14px;")
                prefix.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                reminder_layout.addWidget(prefix)

            # Parent expand/collapse toggle
            has_children = item.id in children_by_parent
            if has_children and not is_child:
                collapsed = item.id in self._collapsed_parents
                toggle_char = "\u25b6" if collapsed else "\u25bc"  # ▶ or ▼
                toggle_btn = ClickableLabel(toggle_char)
                toggle_btn.setStyleSheet(
                    f"color: {colors['completed_text']}; font-size: 10px; padding: 0 2px;"
                )
                toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                toggle_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                toggle_btn.clicked.connect(lambda pid=item.id: self._toggle_collapse(pid))
                reminder_layout.addWidget(toggle_btn)

            reminder_edit = QLineEdit(item.reminder)
            reminder_edit.setMinimumHeight(32)
            reminder_edit.returnPressed.connect(lambda r=row: self._on_reminder_changed(r))

            # Style based on completion status
            if is_context:
                reminder_edit.setFont(self._normal_font)
                reminder_edit.setStyleSheet(f"color: {colors['completed_text']};")
                reminder_edit.setReadOnly(True)
            elif item.complete:
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
            if item.time_spent > 0:
                from .pomodoro import PomodoroWidget

                tooltip_parts.append(
                    f"Time spent: {PomodoroWidget.format_time_spent(item.time_spent)}"
                )
            if tooltip_parts:
                reminder_edit.setToolTip("\n".join(tooltip_parts))

            reminder_layout.addWidget(reminder_edit, 1)
            reminder_edit.setCursorPosition(0)
            reminder_edit.editingFinished.connect(lambda re=reminder_edit: re.setCursorPosition(0))

            # Ellipsis indicator for viewing full reminder text (shown only when truncated)
            ellipsis = ClickableLabel("…")
            ellipsis.setStyleSheet(f"color: {colors['completed_text']}; font-size: 10px;")
            ellipsis.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            ellipsis.setCursor(Qt.CursorShape.PointingHandCursor)
            ellipsis.clicked.connect(
                lambda iid=item.id, e=ellipsis: self._show_reminder_popup(iid, e)
            )
            ellipsis.setVisible(False)
            reminder_layout.addWidget(ellipsis)
            self._ellipsis_pairs.append((reminder_edit, ellipsis))

            # Inline time spent label
            if item.time_spent > 0:
                from .pomodoro import PomodoroWidget

                time_text = PomodoroWidget.format_time_spent(item.time_spent)
                time_label = QLabel(time_text)
                time_label.setStyleSheet(f"color: {colors['completed_text']}; font-size: 10px;")
                time_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                reminder_layout.addWidget(time_label)

            # Parent progress badge [completed/total]
            if has_children and not is_child:
                children = children_by_parent[item.id]
                completed = sum(1 for c in children if c.complete)
                total = len(children)
                badge_text = f"[{completed}/{total}]"
                badge_label = QLabel(badge_text)
                badge_color = (
                    colors.get("due_today", "#4CAF50")
                    if completed == total
                    else colors["completed_text"]
                )
                badge_label.setStyleSheet(
                    f"color: {badge_color}; font-size: 10px; font-weight: bold;"
                )
                badge_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                reminder_layout.addWidget(badge_label)

            # Tag chips (show max 2 inline, overflow badge for the rest)
            _MAX_VISIBLE_TAGS = 2
            if item.tags:
                chip_style = (
                    f"background-color: {colors['highlight']}; "
                    f"color: {colors.get('highlight_text', '#ffffff')}; "
                    "border-radius: 8px; padding: 1px 6px; font-size: 10px;"
                )
                for tag in item.tags[:_MAX_VISIBLE_TAGS]:
                    chip = QLabel(tag)
                    chip.setStyleSheet(chip_style)
                    chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                    reminder_layout.addWidget(chip)
                overflow = len(item.tags) - _MAX_VISIBLE_TAGS
                if overflow > 0:
                    badge = ClickableLabel(f"+{overflow}")
                    badge.setStyleSheet(
                        f"background-color: {colors['button']}; "
                        f"color: {colors['text']}; "
                        "border-radius: 8px; padding: 1px 6px; font-size: 10px;"
                    )
                    badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                    badge.setCursor(Qt.CursorShape.PointingHandCursor)
                    badge.clicked.connect(lambda iid=item.id, b=badge: self._show_tag_popup(iid, b))
                    reminder_layout.addWidget(badge)

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

        logger.log.info("Refreshed table with %d items", len(display_items))
        # Defer ellipsis check until cell widgets have been laid out and sized
        QTimer.singleShot(50, self._update_ellipsis_visibility)

    def _update_ellipsis_visibility(self) -> None:
        """Show/hide ellipsis indicators based on whether reminder text is truncated."""
        for edit, ellipsis in self._ellipsis_pairs:
            available = edit.contentsRect().width()
            # Skip widgets not yet laid out (e.g. last row at edge of viewport)
            if available <= 0:
                ellipsis.setVisible(False)
                continue
            text_width = edit.fontMetrics().horizontalAdvance(edit.text())
            ellipsis.setVisible(text_width > available)

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

    def _show_reminder_popup(self, item_id: UUID, anchor: QWidget) -> None:
        """Show a popup with the full reminder text."""
        if self._current_list is None:
            return
        item = self._current_list.get_item(item_id)
        if not item:
            return

        colors = get_colors()
        popup = QWidget(self, Qt.WindowType.Popup)
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(8, 6, 8, 6)

        label = QLabel(item.reminder)
        label.setWordWrap(True)
        label.setMaximumWidth(400)
        label.setStyleSheet(f"color: {colors['text']}; font-size: 12px;")
        layout.addWidget(label)

        popup.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 2))
        popup.move(pos)
        popup.show()

    def _show_tag_popup(self, item_id: UUID, badge: QWidget) -> None:
        """Show a popup with all overflow tags as styled chips."""
        if self._current_list is None:
            return
        item = self._current_list.get_item(item_id)
        if not item or len(item.tags) <= 2:
            return

        colors = get_colors()
        chip_style = (
            f"background-color: {colors['highlight']}; "
            f"color: {colors.get('highlight_text', '#ffffff')}; "
            "border-radius: 8px; padding: 2px 8px; font-size: 10px;"
        )

        popup = QWidget(self, Qt.WindowType.Popup)
        layout = QHBoxLayout(popup)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        for tag in item.tags[2:]:
            chip = QLabel(tag)
            chip.setStyleSheet(chip_style)
            layout.addWidget(chip)

        edit_btn = QPushButton("Edit...")
        edit_btn.setFixedHeight(20)
        edit_btn.setStyleSheet("font-size: 10px; padding: 1px 6px;")
        edit_btn.clicked.connect(lambda: self._on_popup_edit(popup, item_id))
        layout.addWidget(edit_btn)

        popup.adjustSize()
        pos = badge.mapToGlobal(QPoint(0, badge.height() + 2))
        popup.move(pos)
        popup.show()

    def _on_popup_edit(self, popup: QWidget, item_id: UUID) -> None:
        """Handle 'Edit...' click in tag popup."""
        popup.close()
        self.edit_tags_requested.emit(item_id)

    def _on_selection_changed(self) -> None:
        """Handle selection change."""
        selected = self.get_selected_item_ids()
        if len(selected) == 1:
            self.item_selected.emit(selected[0])
        else:
            self.item_selected.emit(None)
