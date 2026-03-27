"""calendar_view.py

Calendar view widget — third view mode alongside list and kanban board.

Provides Day, Week, Month, and Timeline sub-views with a pill toggle,
navigation controls, and an unscheduled tasks sidebar panel. Tasks are
displayed on their due dates and can be dragged between dates or from
the unscheduled panel to assign due dates.

Follows the same signal/API contract as TodoTableWidget and
KanbanBoardWidget for seamless integration with MainWindow.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from ...core.models import TodoItem, TodoList
    from ..widgets.search_filter import FilterState


# ---------------------------------------------------------------------------
# Helper: date utilities
# ---------------------------------------------------------------------------


def _month_calendar(year: int, month: int) -> list[list[int]]:
    """Return weeks of the month as lists of day numbers (0 = empty)."""
    return calendar.monthcalendar(year, month)


def _week_dates(d: date) -> list[date]:
    """Return the 7 dates of the week containing d (Monday-based)."""
    start = d - timedelta(days=d.weekday())
    return [start + timedelta(days=i) for i in range(7)]


# ---------------------------------------------------------------------------
# Task chip — compact task display for calendar cells
# ---------------------------------------------------------------------------


class _TaskChip(QFrame):
    """A compact task item displayed in a calendar cell."""

    clicked = pyqtSignal(object)  # item_id
    double_clicked = pyqtSignal(object)  # item_id

    _PRIORITY_COLORS = {1: "#e74c3c", 2: "#3498db", 3: "#95a5a6"}

    def __init__(self, item: TodoItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item_id = item.id
        self._selected = False

        color = self._PRIORITY_COLORS.get(item.priority, "#3498db")
        completed_style = "text-decoration: line-through; opacity: 0.6;" if item.complete else ""

        self.setStyleSheet(
            f"QFrame {{ background: palette(base); border-left: 3px solid {color};"
            f" border-radius: 3px; padding: 2px 4px; margin: 1px 0; }}"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(item.reminder)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(2)

        text = QLabel(item.reminder)
        text.setStyleSheet(f"font-size: 10px; {completed_style} border: none; background: none;")
        text.setWordWrap(False)
        layout.addWidget(text, 1)

        # Recurrence indicator
        if item.recurrence_type:
            rec = QLabel("\u21bb")
            rec.setStyleSheet("font-size: 9px; border: none; background: none;")
            rec.setToolTip("Recurring")
            layout.addWidget(rec)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        border = "palette(highlight)" if selected else self._PRIORITY_COLORS.get(2, "#3498db")
        self.setStyleSheet(
            f"QFrame {{ background: palette(base); border-left: 3px solid {border};"
            f" border-radius: 3px; padding: 2px 4px; margin: 1px 0;"
            f" {'border: 2px solid palette(highlight);' if selected else ''} }}"
        )

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        self.clicked.emit(self._item_id)

    def mouseDoubleClickEvent(self, a0) -> None:  # noqa: N802
        self.double_clicked.emit(self._item_id)


# ---------------------------------------------------------------------------
# Month view sub-widget
# ---------------------------------------------------------------------------


class _MonthView(QWidget):
    """Traditional month grid with task chips on due dates."""

    task_clicked = pyqtSignal(object)  # item_id
    task_double_clicked = pyqtSignal(object)  # item_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._year = date.today().year
        self._month = date.today().month
        self._items_by_date: dict[date, list] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Day-of-week headers
        header = QHBoxLayout()
        header.setSpacing(0)
        for day_name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            lbl = QLabel(day_name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                "font-size: 11px; font-weight: bold; padding: 4px; color: palette(placeholderText);"
            )
            header.addWidget(lbl)
        layout.addLayout(header)

        # Grid of day cells
        self._grid_widget = QWidget()
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._grid_widget)
        layout.addWidget(scroll, 1)

    def set_month(self, year: int, month: int) -> None:
        self._year = year
        self._month = month
        self._rebuild()

    def set_items(self, items_by_date: dict[date, list]) -> None:
        self._items_by_date = items_by_date
        self._rebuild()

    def _rebuild(self) -> None:
        # Clear existing cells
        while self._grid_layout.count():
            child = self._grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        weeks = _month_calendar(self._year, self._month)
        today = date.today()

        for row, week in enumerate(weeks):
            for col, day_num in enumerate(week):
                cell = QFrame()
                cell_layout = QVBoxLayout(cell)
                cell_layout.setContentsMargins(2, 2, 2, 2)
                cell_layout.setSpacing(1)

                if day_num == 0:
                    cell.setStyleSheet(
                        "QFrame { background: palette(window); border: 1px solid palette(mid);"
                        " border-radius: 2px; }"
                    )
                else:
                    d = date(self._year, self._month, day_num)
                    is_today = d == today
                    is_weekend = col >= 5

                    bg = (
                        "palette(highlight)"
                        if is_today
                        else ("palette(window)" if is_weekend else "palette(base)")
                    )
                    cell.setStyleSheet(
                        f"QFrame {{ background: {bg}; border: 1px solid palette(mid);"
                        f" border-radius: 2px;"
                        f" {'opacity: 0.9;' if is_today else ''} }}"
                    )

                    # Day number
                    day_lbl = QLabel(str(day_num))
                    day_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                    font_style = "font-weight: bold;" if is_today else ""
                    color = "color: white;" if is_today else ""
                    day_lbl.setStyleSheet(
                        f"font-size: 11px; {font_style} {color}"
                        f" border: none; background: none; padding: 1px 3px;"
                    )
                    cell_layout.addWidget(day_lbl)

                    # Task chips for this date
                    items = self._items_by_date.get(d, [])
                    for item in items[:4]:  # Show max 4 per cell
                        chip = _TaskChip(item)
                        chip.clicked.connect(self.task_clicked.emit)
                        chip.double_clicked.connect(self.task_double_clicked.emit)
                        cell_layout.addWidget(chip)

                    if len(items) > 4:
                        more = QLabel(f"+{len(items) - 4} more")
                        more.setStyleSheet(
                            "font-size: 9px; color: palette(placeholderText);"
                            " border: none; background: none;"
                        )
                        more.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        cell_layout.addWidget(more)

                    cell_layout.addStretch()

                cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                cell.setMinimumHeight(80)
                self._grid_layout.addWidget(cell, row, col)


# ---------------------------------------------------------------------------
# Unscheduled panel
# ---------------------------------------------------------------------------


class _UnscheduledPanel(QFrame):
    """Sidebar showing tasks without due dates."""

    task_clicked = pyqtSignal(object)  # item_id
    task_double_clicked = pyqtSignal(object)  # item_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setStyleSheet("QFrame { border-left: 1px solid palette(mid); }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header = QLabel("Unscheduled")
        header.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(header)

        self._count_label = QLabel("0 tasks")
        self._count_label.setStyleSheet("font-size: 10px; color: palette(placeholderText);")
        layout.addWidget(self._count_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(2)
        self._content_layout.addStretch()
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll, 1)

    def set_items(self, items: list) -> None:
        # Clear existing
        while self._content_layout.count():
            child = self._content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for item in items:
            chip = _TaskChip(item)
            chip.clicked.connect(self.task_clicked.emit)
            chip.double_clicked.connect(self.task_double_clicked.emit)
            self._content_layout.addWidget(chip)

        self._content_layout.addStretch()
        n = len(items)
        self._count_label.setText(f"{n} task{'s' if n != 1 else ''}")


# ---------------------------------------------------------------------------
# Main calendar view widget
# ---------------------------------------------------------------------------


class CalendarViewWidget(QWidget):
    """Calendar view with Day/Week/Month/Timeline sub-views.

    Third view mode alongside TodoTableWidget and KanbanBoardWidget.
    Implements the same signal/API contract for MainWindow integration.
    """

    # Shared signals (must match TodoTableWidget and KanbanBoardWidget)
    item_priority_changed = pyqtSignal(object, int)
    item_reminder_changed = pyqtSignal(object, str)
    item_due_date_changed = pyqtSignal(object, object)
    item_due_time_changed = pyqtSignal(object, object)
    edit_tags_requested = pyqtSignal(object)
    focus_requested = pyqtSignal(object)
    add_subtask_requested = pyqtSignal(object)
    toggle_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    edit_recurrence_requested = pyqtSignal()

    SUB_DAY = 0
    SUB_WEEK = 1
    SUB_MONTH = 2
    SUB_TIMELINE = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._todo_list: TodoList | None = None
        self._filter_state: FilterState | None = None
        self._selected_item_id: UUID | None = None
        self._focus_session_item_id: UUID | None = None
        self._current_date = date.today()
        self._sub_view = self.SUB_MONTH  # Start with month for initial build

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top bar: sub-view pills + navigation
        top_bar = QFrame()
        top_bar.setStyleSheet("QFrame { border-bottom: 1px solid palette(mid); padding: 4px; }")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 4, 8, 4)
        top_layout.setSpacing(8)

        # Sub-view pill toggle
        pill_frame = QFrame()
        pill_frame.setStyleSheet(
            "QFrame { background: palette(window); border: 1px solid palette(mid);"
            " border-radius: 4px; padding: 0; }"
        )
        pill_layout = QHBoxLayout(pill_frame)
        pill_layout.setContentsMargins(2, 2, 2, 2)
        pill_layout.setSpacing(0)

        self._sub_buttons: list[QPushButton] = []
        for i, label in enumerate(["Day", "Week", "Month", "Timeline"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(i == self._sub_view)
            btn.setStyleSheet(
                "QPushButton { border: none; padding: 4px 12px; font-size: 11px;"
                " border-radius: 3px; }"
                " QPushButton:checked { background: palette(highlight); color: white;"
                " font-weight: bold; }"
            )
            btn.clicked.connect(lambda checked, idx=i: self._set_sub_view(idx))
            pill_layout.addWidget(btn)
            self._sub_buttons.append(btn)

        top_layout.addWidget(pill_frame)
        top_layout.addStretch()

        # Navigation
        prev_btn = QToolButton()
        prev_btn.setText("\u25c0")
        prev_btn.setStyleSheet("border: none; font-size: 14px; padding: 4px;")
        prev_btn.clicked.connect(self._navigate_prev)
        top_layout.addWidget(prev_btn)

        self._nav_label = QLabel()
        self._nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._nav_label.setStyleSheet("font-size: 13px; font-weight: bold; min-width: 140px;")
        top_layout.addWidget(self._nav_label)

        next_btn = QToolButton()
        next_btn.setText("\u25b6")
        next_btn.setStyleSheet("border: none; font-size: 14px; padding: 4px;")
        next_btn.clicked.connect(self._navigate_next)
        top_layout.addWidget(next_btn)

        today_btn = QPushButton("Today")
        today_btn.setStyleSheet(
            "QPushButton { border: 1px solid palette(mid); border-radius: 3px;"
            " padding: 3px 10px; font-size: 11px; }"
        )
        today_btn.clicked.connect(self._navigate_today)
        top_layout.addWidget(today_btn)

        layout.addWidget(top_bar)

        # Content area: sub-view stack + unscheduled panel
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        # Sub-view stack
        self._sub_stack = QStackedWidget()

        # Placeholder views (Day, Week will be implemented later)
        self._day_view = QLabel("Day view — coming soon")
        self._day_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_stack.addWidget(self._day_view)  # 0

        self._week_view = QLabel("Week view — coming soon")
        self._week_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_stack.addWidget(self._week_view)  # 1

        self._month_view = _MonthView()
        self._month_view.task_clicked.connect(self._on_task_clicked)
        self._month_view.task_double_clicked.connect(self._on_task_double_clicked)
        self._sub_stack.addWidget(self._month_view)  # 2

        self._timeline_view = QLabel("Timeline view — coming soon")
        self._timeline_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_stack.addWidget(self._timeline_view)  # 3

        self._sub_stack.setCurrentIndex(self._sub_view)
        content.addWidget(self._sub_stack, 1)

        # Unscheduled panel
        self._unscheduled = _UnscheduledPanel()
        self._unscheduled.task_clicked.connect(self._on_task_clicked)
        self._unscheduled.task_double_clicked.connect(self._on_task_double_clicked)
        content.addWidget(self._unscheduled)

        layout.addLayout(content, 1)

        self._update_nav_label()

    # --- Public API (matches TodoTableWidget / KanbanBoardWidget) ---

    def set_list(self, todo_list: TodoList | None) -> None:
        """Set the list to display and refresh."""
        self._todo_list = todo_list
        self.refresh()

    def set_filter(self, filter_state: FilterState | None) -> None:
        """Apply a filter state."""
        self._filter_state = filter_state
        self.refresh()

    def get_selected_item_ids(self) -> list[UUID]:
        """Return currently selected item IDs."""
        if self._selected_item_id is not None:
            return [self._selected_item_id]
        return []

    def set_focus_session_item(self, item_id: UUID | None) -> None:
        """Highlight the item with an active focus session."""
        if self._focus_session_item_id != item_id:
            self._focus_session_item_id = item_id
            self.refresh()

    def refresh(self) -> None:
        """Rebuild the calendar with current data."""
        if self._todo_list is None:
            self._month_view.set_items({})
            self._unscheduled.set_items([])
            return

        # Gather items, apply filter
        items = list(self._todo_list.active_items())
        items = [i for i in items if i.parent_id is None]  # Top-level only
        items = self._apply_filter(items)

        # Split into scheduled and unscheduled
        scheduled: dict[date, list] = {}
        unscheduled: list = []
        for item in items:
            if item.due_date:
                scheduled.setdefault(item.due_date, []).append(item)
            else:
                unscheduled.append(item)

        # Sort items within each date
        for d in scheduled:
            scheduled[d].sort(
                key=lambda i: (
                    i.complete,
                    i.priority,
                    i.due_time.hour * 60 + i.due_time.minute if i.due_time else 9999,
                    i.reminder.lower(),
                )
            )

        # Update sub-views
        self._month_view.set_items(scheduled)
        self._month_view.set_month(self._current_date.year, self._current_date.month)
        self._unscheduled.set_items(unscheduled)

    # --- Filter (same logic as kanban) ---

    def _apply_filter(self, items: list) -> list:
        if self._filter_state is None:
            return items

        from ...core.models import is_due_this_week, is_due_today, is_overdue

        filtered = list(items)
        search = getattr(self._filter_state, "text", "").lower()
        if search:
            filtered = [i for i in filtered if search in i.reminder.lower()]
        if self._filter_state.priority != 0:
            filtered = [i for i in filtered if i.priority == self._filter_state.priority]
        if self._filter_state.status == 1:
            filtered = [i for i in filtered if not i.complete]
        elif self._filter_state.status == 2:
            filtered = [i for i in filtered if i.complete]
        if self._filter_state.due_date == 1:
            filtered = [i for i in filtered if is_overdue(i.due_date, i.due_time)]
        elif self._filter_state.due_date == 2:
            filtered = [i for i in filtered if is_due_today(i.due_date)]
        elif self._filter_state.due_date == 3:
            filtered = [i for i in filtered if is_due_this_week(i.due_date)]
        elif self._filter_state.due_date == 4:
            filtered = [i for i in filtered if i.due_date is None]
        elif self._filter_state.due_date == 5:
            filtered = [i for i in filtered if i.is_recurring]
        if self._filter_state.tag:
            filtered = [i for i in filtered if self._filter_state.tag in i.tags]
        return filtered

    # --- Navigation ---

    def _navigate_prev(self) -> None:
        if self._sub_view == self.SUB_MONTH:
            if self._current_date.month == 1:
                self._current_date = self._current_date.replace(
                    year=self._current_date.year - 1, month=12
                )
            else:
                self._current_date = self._current_date.replace(month=self._current_date.month - 1)
        elif self._sub_view == self.SUB_WEEK:
            self._current_date -= timedelta(weeks=1)
        else:
            self._current_date -= timedelta(days=1)
        self._update_nav_label()
        self.refresh()

    def _navigate_next(self) -> None:
        if self._sub_view == self.SUB_MONTH:
            if self._current_date.month == 12:
                self._current_date = self._current_date.replace(
                    year=self._current_date.year + 1, month=1
                )
            else:
                self._current_date = self._current_date.replace(month=self._current_date.month + 1)
        elif self._sub_view == self.SUB_WEEK:
            self._current_date += timedelta(weeks=1)
        else:
            self._current_date += timedelta(days=1)
        self._update_nav_label()
        self.refresh()

    def _navigate_today(self) -> None:
        self._current_date = date.today()
        self._update_nav_label()
        self.refresh()

    def _update_nav_label(self) -> None:
        d = self._current_date
        if self._sub_view == self.SUB_MONTH:
            self._nav_label.setText(f"{calendar.month_name[d.month]} {d.year}")
        elif self._sub_view == self.SUB_WEEK:
            week = _week_dates(d)
            self._nav_label.setText(
                f"{week[0].strftime('%b %d')} — {week[6].strftime('%b %d, %Y')}"
            )
        elif self._sub_view == self.SUB_DAY:
            self._nav_label.setText(d.strftime("%A, %B %d, %Y"))
        else:
            self._nav_label.setText(f"Timeline — {d.strftime('%B %Y')}")

    # --- Sub-view switching ---

    def _set_sub_view(self, idx: int) -> None:
        self._sub_view = idx
        self._sub_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._sub_buttons):
            btn.setChecked(i == idx)
        self._update_nav_label()
        self.refresh()

    # --- Task interaction ---

    def _on_task_clicked(self, item_id: UUID) -> None:
        self._selected_item_id = item_id

    def _on_task_double_clicked(self, item_id: UUID) -> None:
        self._selected_item_id = item_id
        self.edit_tags_requested.emit(item_id)
