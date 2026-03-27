"""calendar_view.py

Calendar view widget — third view mode alongside list and kanban board.

Provides Day, Week, Month, and Timeline sub-views with a pill toggle,
navigation controls, and an unscheduled tasks sidebar panel. Tasks are
displayed on their due dates and can be dragged between dates or from
the unscheduled panel to assign due dates.

The month view uses QTableView + QStyledItemDelegate for guaranteed
equal column/row sizing and QPainter-based rendering (same architecture
as Qt's own QCalendarWidget).

Follows the same signal/API contract as TodoTableWidget and
KanbanBoardWidget for seamless integration with MainWindow.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from ...core.models import TodoList
    from ..widgets.search_filter import FilterState


# ---------------------------------------------------------------------------
# Model/View/Delegate for Month Grid
# ---------------------------------------------------------------------------

_ITEMS_ROLE = Qt.ItemDataRole.UserRole + 1
_DATE_ROLE = Qt.ItemDataRole.UserRole + 2
_PRIORITY_COLORS = {1: QColor("#e74c3c"), 2: QColor("#3498db"), 3: QColor("#95a5a6")}


class _CalendarModel(QAbstractTableModel):
    """Data model for the month grid — 7 columns × 6 rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._year = date.today().year
        self._month = date.today().month
        self._weeks: list[list[int]] = []
        self._items_by_date: dict[date, list] = {}
        self._rebuild_weeks()

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return len(self._weeks)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 7

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row >= len(self._weeks):
            return None
        day_num = self._weeks[row][col]

        if role == Qt.ItemDataRole.DisplayRole:
            return str(day_num) if day_num != 0 else ""
        if role == _DATE_ROLE:
            if day_num == 0:
                return None
            return date(self._year, self._month, day_num)
        if role == _ITEMS_ROLE:
            if day_num == 0:
                return []
            d = date(self._year, self._month, day_num)
            return self._items_by_date.get(d, [])
        return None

    def set_month(self, year: int, month: int) -> None:
        self.beginResetModel()
        self._year = year
        self._month = month
        self._rebuild_weeks()
        self.endResetModel()

    def set_items(self, items_by_date: dict[date, list]) -> None:
        self.beginResetModel()
        self._items_by_date = items_by_date
        self.endResetModel()

    def _rebuild_weeks(self) -> None:
        self._weeks = calendar.monthcalendar(self._year, self._month)
        # Pad to exactly 6 rows for consistent layout
        while len(self._weeks) < 6:
            self._weeks.append([0] * 7)


class _CalendarDelegate(QStyledItemDelegate):
    """Custom painter for month grid cells — draws day numbers, task items, overflow."""

    task_clicked = pyqtSignal(object)  # item_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._today = date.today()
        self._selected_item_id: UUID | None = None

    def set_selected(self, item_id: UUID | None) -> None:
        self._selected_item_id = item_id

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(option.rect)

        rect = option.rect
        cell_date = index.data(_DATE_ROLE)
        items: list = index.data(_ITEMS_ROLE) or []
        day_text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        palette = option.palette

        # --- Background ---
        if cell_date is None:
            # Empty cell (outside month)
            painter.fillRect(rect, palette.window())
        elif cell_date == self._today:
            painter.fillRect(rect, palette.highlight())
        elif cell_date.weekday() >= 5:
            # Weekend — subtle alternate
            bg = palette.alternateBase().color()
            painter.fillRect(rect, bg)
        else:
            painter.fillRect(rect, palette.base())

        # --- Border ---
        painter.setPen(QPen(palette.mid().color(), 1))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        if cell_date is None:
            painter.restore()
            return

        # --- Day number ---
        day_font = QFont(painter.font())
        day_font.setPixelSize(11)
        if cell_date == self._today:
            day_font.setBold(True)
        painter.setFont(day_font)

        if cell_date == self._today:
            painter.setPen(palette.highlightedText().color())
        else:
            painter.setPen(palette.text().color())

        day_rect = rect.adjusted(0, 2, -4, 0)
        painter.drawText(
            day_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
            day_text,
        )

        # --- Task items ---
        if not items:
            painter.restore()
            return

        item_font = QFont(painter.font())
        item_font.setPixelSize(10)
        painter.setFont(item_font)
        fm = QFontMetrics(item_font)

        item_height = fm.height() + 4
        day_header_height = 18
        overflow_height = fm.height() + 2
        y = rect.top() + day_header_height
        x = rect.left() + 4
        available_height = rect.height() - day_header_height - 2
        text_width = rect.width() - 14  # left bar + padding + right margin

        # Calculate how many items fit
        if len(items) * item_height <= available_height:
            max_items = len(items)
        else:
            max_items = max(1, (available_height - overflow_height) // item_height)

        for i in range(min(max_items, len(items))):
            item = items[i]
            item_y = y + i * item_height

            # Priority color bar
            color = _PRIORITY_COLORS.get(item.priority, _PRIORITY_COLORS[2])
            painter.fillRect(x, item_y + 1, 3, item_height - 2, color)

            # Selection highlight
            if self._selected_item_id and item.id == self._selected_item_id:
                sel_rect = rect.adjusted(2, 0, -2, 0)
                sel_rect.setTop(item_y)
                sel_rect.setHeight(item_height)
                painter.setPen(QPen(palette.highlight().color(), 1))
                painter.drawRect(sel_rect)

            # Text
            if item.complete:
                painter.setPen(palette.placeholderText().color())
            elif cell_date == self._today:
                painter.setPen(palette.highlightedText().color())
            else:
                painter.setPen(palette.text().color())

            text = fm.elidedText(item.reminder, Qt.TextElideMode.ElideRight, text_width)
            text_rect = rect.adjusted(x + 6 - rect.left(), 0, -4, 0)
            text_rect.setTop(item_y)
            text_rect.setHeight(item_height)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

            # Strikethrough for completed
            if item.complete:
                strike_y = item_y + item_height // 2
                painter.drawLine(x + 6, strike_y, x + 6 + fm.horizontalAdvance(text), strike_y)

            # Recurrence indicator
            if item.recurrence_type:
                rec_x = rect.right() - 12
                painter.drawText(
                    rec_x, item_y, 10, item_height, Qt.AlignmentFlag.AlignCenter, "\u21bb"
                )

        # --- Overflow indicator ---
        overflow = len(items) - max_items
        if overflow > 0:
            painter.setPen(palette.placeholderText().color())
            overflow_y = y + max_items * item_height
            overflow_rect = rect.adjusted(4, 0, -4, 0)
            overflow_rect.setTop(overflow_y)
            overflow_rect.setHeight(overflow_height)
            painter.drawText(
                overflow_rect,
                Qt.AlignmentFlag.AlignCenter,
                f"+{overflow} more",
            )

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> Any:
        from PyQt6.QtCore import QSize

        return QSize(100, 90)


class _CalendarTableView(QTableView):
    """Month grid table view with guaranteed equal columns and rows."""

    task_clicked = pyqtSignal(object)  # item_id
    task_double_clicked = pyqtSignal(object)  # item_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Hide all chrome
        h_header = self.horizontalHeader()
        assert h_header is not None
        h_header.hide()
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        v_header = self.verticalHeader()
        assert v_header is not None
        v_header.hide()

        self.setShowGrid(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("QTableView { border: none; background: palette(window); }")

    def resizeEvent(self, a0) -> None:  # noqa: N802
        super().resizeEvent(a0)
        model = self.model()
        if model is None:
            return
        row_count = model.rowCount()
        if row_count == 0:
            return
        viewport = self.viewport()
        if viewport is None:
            return
        row_height = viewport.height() // row_count
        for row in range(row_count):
            self.setRowHeight(row, row_height)

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        super().mousePressEvent(a0)
        if a0 is None:
            return
        index = self.indexAt(a0.pos())
        if not index.isValid():
            return
        items = index.data(_ITEMS_ROLE) or []
        if not items:
            return
        # Find which item was clicked based on y position
        rect = self.visualRect(index)
        click_y = a0.pos().y() - rect.top() - 18  # subtract day header
        fm = QFontMetrics(self.font())
        item_height = fm.height() + 4
        item_idx = int(click_y / item_height) if item_height > 0 else 0
        if 0 <= item_idx < len(items):
            self.task_clicked.emit(items[item_idx].id)

    def mouseDoubleClickEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        index = self.indexAt(a0.pos())
        if not index.isValid():
            return
        items = index.data(_ITEMS_ROLE) or []
        if not items:
            return
        rect = self.visualRect(index)
        click_y = a0.pos().y() - rect.top() - 18
        fm = QFontMetrics(self.font())
        item_height = fm.height() + 4
        item_idx = int(click_y / item_height) if item_height > 0 else 0
        if 0 <= item_idx < len(items):
            self.task_double_clicked.emit(items[item_idx].id)


# ---------------------------------------------------------------------------
# Day-of-week header bar
# ---------------------------------------------------------------------------


class _DayHeaders(QWidget):
    """Fixed header row showing Mon-Sun labels."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(24)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                "font-size: 11px; font-weight: bold; padding: 2px;"
                " color: palette(placeholderText); border: none;"
            )
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            layout.addWidget(lbl)


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
        # Rebuild content widget to avoid ghost rendering
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)

        for item in items:
            row = QFrame()
            row.setStyleSheet(
                "QFrame { background: palette(base); border-left: 3px solid #3498db;"
                " border-radius: 3px; padding: 2px 4px; margin: 1px 0; }"
            )
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setToolTip(item.reminder)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(2)

            text = item.reminder
            if len(text) > 22:
                text = text[:21] + "\u2026"
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 10px; border: none; background: none;")
            row_layout.addWidget(lbl)
            content_layout.addWidget(row)

        content_layout.addStretch()
        self._scroll.setWidget(content)

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
        self._sub_view = self.SUB_MONTH

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

        # Placeholder views (Day, Week, Timeline)
        self._day_view = QLabel("Day view — coming soon")
        self._day_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_stack.addWidget(self._day_view)  # 0

        self._week_view = QLabel("Week view — coming soon")
        self._week_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_stack.addWidget(self._week_view)  # 1

        # Month view — QTableView with custom model/delegate
        month_container = QWidget()
        month_layout = QVBoxLayout(month_container)
        month_layout.setContentsMargins(0, 0, 0, 0)
        month_layout.setSpacing(0)

        self._day_headers = _DayHeaders()
        month_layout.addWidget(self._day_headers)

        self._cal_model = _CalendarModel()
        self._cal_delegate = _CalendarDelegate()
        self._cal_table = _CalendarTableView()
        self._cal_table.setModel(self._cal_model)
        self._cal_table.setItemDelegate(self._cal_delegate)
        self._cal_table.task_clicked.connect(self._on_task_clicked)
        self._cal_table.task_double_clicked.connect(self._on_task_double_clicked)
        month_layout.addWidget(self._cal_table, 1)

        self._sub_stack.addWidget(month_container)  # 2

        self._timeline_view = QLabel("Timeline view — coming soon")
        self._timeline_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_stack.addWidget(self._timeline_view)  # 3

        self._sub_stack.setCurrentIndex(self._sub_view)
        content.addWidget(self._sub_stack, 1)

        # Unscheduled panel
        self._unscheduled = _UnscheduledPanel()
        content.addWidget(self._unscheduled)

        layout.addLayout(content, 1)

        self._update_nav_label()

    # --- Public API ---

    def set_list(self, todo_list: TodoList | None) -> None:
        self._todo_list = todo_list
        self.refresh()

    def set_filter(self, filter_state: FilterState | None) -> None:
        self._filter_state = filter_state
        self.refresh()

    def get_selected_item_ids(self) -> list[UUID]:
        if self._selected_item_id is not None:
            return [self._selected_item_id]
        return []

    def set_focus_session_item(self, item_id: UUID | None) -> None:
        if self._focus_session_item_id != item_id:
            self._focus_session_item_id = item_id
            self.refresh()

    def refresh(self) -> None:
        if self._todo_list is None:
            self._cal_model.set_items({})
            self._unscheduled.set_items([])
            return

        items = list(self._todo_list.active_items())
        items = [i for i in items if i.parent_id is None]
        items = self._apply_filter(items)

        scheduled: dict[date, list] = {}
        unscheduled: list = []
        for item in items:
            if item.due_date:
                scheduled.setdefault(item.due_date, []).append(item)
            else:
                unscheduled.append(item)

        for d in scheduled:
            scheduled[d].sort(
                key=lambda i: (
                    i.complete,
                    i.priority,
                    i.due_time.hour * 60 + i.due_time.minute if i.due_time else 9999,
                    i.reminder.lower(),
                )
            )

        self._cal_model.set_items(scheduled)
        self._cal_model.set_month(self._current_date.year, self._current_date.month)
        self._cal_delegate._today = date.today()
        self._unscheduled.set_items(unscheduled)

    # --- Filter ---

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
            start = d - timedelta(days=d.weekday())
            end = start + timedelta(days=6)
            self._nav_label.setText(f"{start.strftime('%b %d')} \u2014 {end.strftime('%b %d, %Y')}")
        elif self._sub_view == self.SUB_DAY:
            self._nav_label.setText(d.strftime("%A, %B %d, %Y"))
        else:
            self._nav_label.setText(f"Timeline \u2014 {d.strftime('%B %Y')}")

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
        self._cal_delegate.set_selected(item_id)
        self._cal_table.viewport().update()  # type: ignore[union-attr]

    def _on_task_double_clicked(self, item_id: UUID) -> None:
        self._selected_item_id = item_id
        # TODO: open task detail/edit dialog (same as list/board views)
