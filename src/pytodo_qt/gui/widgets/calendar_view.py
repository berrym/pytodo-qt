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


class _CloseButton(QWidget):
    """QPainter-rendered close button for reliable cross-platform display."""

    def __init__(self, on_click=None, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, a0):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(128, 128, 128, 60))
        p.drawEllipse(0, 0, 20, 20)
        p.setPen(QPen(QColor(200, 200, 200), 2))
        p.drawLine(6, 6, 14, 14)
        p.drawLine(14, 6, 6, 14)
        p.end()

    def mousePressEvent(self, a0):  # noqa: N802
        if self._on_click:
            self._on_click()


_ITEMS_ROLE = Qt.ItemDataRole.UserRole + 1
_DATE_ROLE = Qt.ItemDataRole.UserRole + 2
_DAY_HEADER_HEIGHT = 18
_ITEM_FONT_SIZE = 10


def _calc_cell_layout(
    cell_height: int, item_count: int, font: QFont | None = None
) -> tuple[int, int, int, int]:
    """Calculate shared layout geometry for a calendar cell.

    Returns (item_height, max_visible, overflow_height, y_start).
    Used by both the delegate paint and the table view hit-test
    to ensure click zones align with rendered positions.
    """
    if font is None:
        font = QFont()
        font.setPixelSize(_ITEM_FONT_SIZE)
    fm = QFontMetrics(font)
    item_height = fm.height() + 4
    overflow_height = fm.height() + 2
    y_start = _DAY_HEADER_HEIGHT
    available = cell_height - _DAY_HEADER_HEIGHT - 2

    if item_count * item_height <= available:
        max_visible = item_count
    else:
        max_visible = max(1, (available - overflow_height) // item_height)

    return item_height, max_visible, overflow_height, y_start


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
        self._todo_list: TodoList | None = None
        self._colors: dict[str, str] = {}
        self._refresh_colors()

    def _refresh_colors(self) -> None:
        from ...gui.styles.themes import get_colors

        self._colors = get_colors()

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
        c = self._colors

        # Semantic colors from theme system (WCAG AA tuned)
        col_base = QColor(c["base"])
        col_alt_base = QColor(c["alternate_base"])
        col_highlight = QColor(c["highlight"])
        col_highlight_text = QColor(c["highlight_text"])
        col_text = QColor(c["text"])
        col_completed_text = QColor(c["completed_text"])
        col_border = QColor(c["border"])
        col_priority = {
            1: QColor(c["priority_high"]),
            2: QColor(c["priority_normal"]),
            3: QColor(c["priority_low"]),
        }

        # --- Background ---
        if cell_date is None:
            painter.fillRect(rect, QColor(c["window"]))
        elif cell_date == self._today:
            painter.fillRect(rect, col_highlight)
        elif cell_date.weekday() >= 5:
            painter.fillRect(rect, col_alt_base)
        else:
            painter.fillRect(rect, col_base)

        # --- Border ---
        painter.setPen(QPen(col_border, 1))
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
        painter.setPen(col_highlight_text if cell_date == self._today else col_text)

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
        item_font.setPixelSize(_ITEM_FONT_SIZE)
        painter.setFont(item_font)
        fm = QFontMetrics(item_font)

        item_height, max_items, overflow_height, y_start = _calc_cell_layout(
            rect.height(), len(items), item_font
        )
        y = rect.top() + y_start
        x = rect.left() + 4
        text_width = rect.width() - 14

        for i in range(min(max_items, len(items))):
            item = items[i]
            item_y = y + i * item_height
            is_selected = bool(self._selected_item_id and item.id == self._selected_item_id)

            chip_rect = rect.adjusted(3, 0, -3, 0)
            chip_rect.setTop(item_y)
            chip_rect.setHeight(item_height)

            # Background: completed (green) or selected (neutral) or none
            if item.complete:
                painter.fillRect(chip_rect, QColor(c["completed_bg"]))
            if is_selected:
                sel_bg = QColor(col_alt_base)
                sel_bg.setAlpha(200)
                painter.fillRect(chip_rect, sel_bg)
                painter.setPen(QPen(col_border.lighter(150), 2))
                painter.drawRoundedRect(chip_rect, 3, 3)

            # Priority color bar
            p_color = col_priority.get(item.priority, col_priority[2])
            painter.fillRect(x, item_y + 1, 3, item_height - 2, p_color)

            # Text — clean month view: checkmark + title only
            if item.complete:
                painter.setPen(col_completed_text)
            elif cell_date == self._today:
                painter.setPen(col_highlight_text)
            else:
                painter.setPen(col_text)

            prefix = "\u2713 " if item.complete else ""
            full_text = prefix + item.reminder
            text = fm.elidedText(full_text, Qt.TextElideMode.ElideRight, text_width)
            text_rect = rect.adjusted(x + 6 - rect.left(), 0, -4, 0)
            text_rect.setTop(item_y)
            text_rect.setHeight(item_height)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

            # Strikethrough for completed (over the text after checkmark)
            if item.complete:
                painter.setPen(QPen(col_completed_text, 1))
                strike_y = item_y + item_height // 2
                # Strikethrough only the reminder part, not the checkmark
                prefix_w = fm.horizontalAdvance(prefix)
                reminder_w = fm.horizontalAdvance(text) - prefix_w
                painter.drawLine(
                    x + 6 + prefix_w,
                    strike_y,
                    x + 6 + prefix_w + reminder_w,
                    strike_y,
                )

        # --- Overflow indicator ---
        overflow = len(items) - max_items
        if overflow > 0:
            painter.setPen(col_completed_text)
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
    task_right_clicked = pyqtSignal(object, object)  # (item_id, QPoint global pos)
    more_clicked = pyqtSignal(object, object)  # (date, list[TodoItem])

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
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)
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

    def _hit_test(self, pos):
        """Determine what was clicked: ('task', item, index), ('more', date, items), or None."""
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        items = index.data(_ITEMS_ROLE) or []
        cell_date = index.data(_DATE_ROLE)
        if not items or cell_date is None:
            return None

        rect = self.visualRect(index)

        # Use the SAME font and layout calculation as the delegate paint
        font = QFont()
        font.setPixelSize(_ITEM_FONT_SIZE)
        item_height, max_visible, _overflow_h, y_start = _calc_cell_layout(
            rect.height(), len(items), font
        )

        click_y = pos.y() - rect.top() - y_start
        item_idx = int(click_y / item_height) if item_height > 0 else -1

        # Check if clicking "+N more" area
        if len(items) > max_visible and item_idx >= max_visible:
            return ("more", cell_date, items)

        if 0 <= item_idx < min(max_visible, len(items)):
            return ("task", items[item_idx], index)

        return None

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        super().mousePressEvent(a0)
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit is None:
            return
        if hit[0] == "task":
            self.task_clicked.emit(hit[1].id)
        elif hit[0] == "more":
            self.more_clicked.emit(hit[1], hit[2])

    def mouseDoubleClickEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit is not None and hit[0] == "task":
            self.task_double_clicked.emit(hit[1].id)

    def mouseMoveEvent(self, a0) -> None:  # noqa: N802
        """Show tooltip with full task info on hover."""
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit is not None and hit[0] == "task":
            item = hit[1]
            parts = [item.reminder]
            if item.due_time:
                parts.append(f"Due: {item.due_time.strftime('%I:%M %p').lstrip('0')}")
            if item.recurrence_type:
                from ...core.models import format_recurrence

                parts.append(format_recurrence(item))
            if item.estimated_pomodoros > 0 or item.pomodoro_count > 0:
                pom = (
                    f"\U0001f345 {item.pomodoro_count}/{item.estimated_pomodoros}"
                    if item.estimated_pomodoros
                    else f"\U0001f345 {item.pomodoro_count}"
                )
                parts.append(pom)
            if item.tags:
                parts.append(f"Tags: {', '.join(item.tags)}")
            if item.complete:
                parts.append("\u2713 Completed")
            from PyQt6.QtWidgets import QToolTip

            QToolTip.showText(a0.globalPosition().toPoint(), "\n".join(parts), self)
        elif hit is not None and hit[0] == "more":
            from PyQt6.QtWidgets import QToolTip

            n = len(hit[2])
            QToolTip.showText(
                a0.globalPosition().toPoint(),
                f"Click to see all {n} tasks",
                self,
            )
        else:
            from PyQt6.QtWidgets import QToolTip

            QToolTip.hideText()

    def contextMenuEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit is not None and hit[0] == "task":
            self.task_clicked.emit(hit[1].id)
            self.task_right_clicked.emit(hit[1].id, a0.globalPos())
        else:
            super().contextMenuEvent(a0)


# ---------------------------------------------------------------------------
# Timeline View — horizontal bars showing task spans and effort
# ---------------------------------------------------------------------------


class _TimelineWidget(QWidget):
    """Custom-painted horizontal timeline with task bars.

    Three bar types per task (layered):
    - Blue: time span (creation → due date)
    - Amber: estimated effort (estimated_pomodoros)
    - Green: actual work done (pomodoro_count / time_spent)
    """

    task_clicked = pyqtSignal(object)  # item_id
    task_right_clicked = pyqtSignal(object, object)  # item_id, global_pos

    ROW_HEIGHT = 32
    HEADER_HEIGHT = 30
    LABEL_WIDTH = 160
    BAR_HEIGHT = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list = []
        self._range_start: date = date.today() - timedelta(days=3)
        self._range_end: date = date.today() + timedelta(days=11)
        self._selected_item_id: UUID | None = None
        self._colors: dict[str, str] = {}
        self._todo_list = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._refresh_colors()

    def _refresh_colors(self) -> None:
        from ...gui.styles.themes import get_colors

        self._colors = get_colors()

    def set_data(self, items: list, current_date: date, todo_list=None) -> None:
        self._items = [i for i in items if i.parent_id is None]
        self._range_start = current_date - timedelta(days=3)
        self._range_end = current_date + timedelta(days=11)
        self._todo_list = todo_list
        self.setMinimumHeight(self.HEADER_HEIGHT + len(self._items) * self.ROW_HEIGHT + 20)
        self.update()

    def set_selected(self, item_id: UUID | None) -> None:
        self._selected_item_id = item_id
        self.update()

    def _date_to_x(self, d: date) -> float:
        """Map a date to x coordinate in the timeline area."""
        total_days = (self._range_end - self._range_start).days
        if total_days <= 0:
            return float(self.LABEL_WIDTH)
        day_offset = (d - self._range_start).days
        timeline_width = self.width() - self.LABEL_WIDTH - 10
        return self.LABEL_WIDTH + (day_offset / total_days) * timeline_width

    def _ms_to_date(self, ms: int) -> date:
        from datetime import datetime as _dt

        return _dt.fromtimestamp(ms / 1000).date()

    def paintEvent(self, a0) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        c = self._colors
        col_base = QColor(c["base"])
        col_text = QColor(c["text"])
        col_border = QColor(c["border"])
        col_completed_text = QColor(c["completed_text"])
        col_completed_bg = QColor(c["completed_bg"])
        col_highlight = QColor(c["highlight"])
        today = date.today()

        # Background
        painter.fillRect(self.rect(), col_base)

        # --- Header: date labels ---
        painter.setPen(col_text)
        header_font = QFont(painter.font())
        header_font.setPixelSize(10)
        painter.setFont(header_font)

        total_days = (self._range_end - self._range_start).days
        for i in range(total_days + 1):
            d = self._range_start + timedelta(days=i)
            x = self._date_to_x(d)
            # Vertical grid line
            line_color = col_highlight if d == today else col_border
            painter.setPen(QPen(line_color, 1 if d != today else 2))
            painter.drawLine(int(x), self.HEADER_HEIGHT, int(x), self.height())
            # Date label (show every other day to avoid crowding)
            if i % 2 == 0 or d == today:
                painter.setPen(col_highlight if d == today else col_text)
                label = d.strftime("%b %d")
                painter.drawText(
                    int(x) - 20, 2, 50, self.HEADER_HEIGHT - 4, Qt.AlignmentFlag.AlignCenter, label
                )

        # --- Task rows ---
        item_font = QFont(painter.font())
        item_font.setPixelSize(11)
        painter.setFont(item_font)
        fm = QFontMetrics(item_font)

        # Bar colors
        col_span = QColor("#4a90d2")  # Blue: time span
        col_span.setAlpha(120)
        col_estimated = QColor("#e6a817")  # Amber: estimated effort
        col_actual = QColor("#27ae60")  # Green: actual work

        # Pomodoro work duration from config (stored in minutes)
        from ...core.config import get_config

        config_work_mins = get_config().pomodoro.work_duration

        for row, item in enumerate(self._items):
            y = self.HEADER_HEIGHT + row * self.ROW_HEIGHT
            is_selected = bool(self._selected_item_id and item.id == self._selected_item_id)

            # Row background
            if is_selected:
                sel_bg = QColor(c["alternate_base"])
                sel_bg.setAlpha(200)
                painter.fillRect(0, y, self.width(), self.ROW_HEIGHT, sel_bg)
            elif item.complete:
                painter.fillRect(0, y, self.width(), self.ROW_HEIGHT, col_completed_bg)

            # Row separator
            painter.setPen(QPen(col_border, 1))
            painter.drawLine(0, y + self.ROW_HEIGHT - 1, self.width(), y + self.ROW_HEIGHT - 1)

            # Task label (left side)
            painter.setPen(col_completed_text if item.complete else col_text)
            prefix = "\u2713 " if item.complete else ""
            label = fm.elidedText(
                prefix + item.reminder, Qt.TextElideMode.ElideRight, self.LABEL_WIDTH - 10
            )
            painter.drawText(
                4,
                y,
                self.LABEL_WIDTH - 8,
                self.ROW_HEIGHT,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

            # --- Bars ---
            bar_y = y + (self.ROW_HEIGHT - self.BAR_HEIGHT * 3 - 4) // 2

            # Blue bar: creation → end of due date (or today if no due date)
            # Due date is inclusive — task is due BY end of that day
            created_date = self._ms_to_date(item.created_at)
            end_date = (item.due_date + timedelta(days=1)) if item.due_date else today
            x_start = max(self._date_to_x(created_date), self.LABEL_WIDTH)
            x_end = min(self._date_to_x(end_date), self.width() - 10)
            if x_end > x_start:
                painter.fillRect(
                    int(x_start), bar_y, int(x_end - x_start), self.BAR_HEIGHT, col_span
                )

            # --- Effort bars: independent of time span ---
            # Effort scales by sessions, not calendar time.
            # pixels_per_session is a constant that makes bars readable.
            span_width = int(x_end - x_start) if x_end > x_start else 0
            pixels_per_session = 15

            # Amber bar: estimated effort (sessions × pixels)
            bar_y += self.BAR_HEIGHT + 2
            est_pixel_width = 0
            if item.estimated_pomodoros > 0 and span_width > 0:
                est_pixel_width = min(
                    span_width,
                    item.estimated_pomodoros * pixels_per_session,
                )
                est_pixel_width = max(est_pixel_width, 20)  # minimum visibility
                painter.fillRect(
                    int(x_start), bar_y, est_pixel_width, self.BAR_HEIGHT, col_estimated
                )

            # Green bar: actual work done
            bar_y += self.BAR_HEIGHT + 2
            if (item.pomodoro_count > 0 or item.time_spent > 0) and span_width > 0:
                if est_pixel_width > 0 and item.estimated_pomodoros > 0:
                    # Has estimate: green = ratio of amber
                    actual_sessions = (
                        item.time_spent / (config_work_mins * 60)
                        if item.time_spent > 0
                        else item.pomodoro_count
                    )
                    ratio = min(1.0, actual_sessions / item.estimated_pomodoros)
                    actual_width = max(2, int(est_pixel_width * ratio))
                else:
                    # No estimate: green = sessions × pixels
                    actual_sessions = (
                        item.time_spent / (config_work_mins * 60)
                        if item.time_spent > 0
                        else item.pomodoro_count
                    )
                    actual_width = min(
                        span_width,
                        max(8, int(actual_sessions * pixels_per_session)),
                    )
                painter.fillRect(int(x_start), bar_y, actual_width, self.BAR_HEIGHT, col_actual)

        # --- Legend ---
        legend_y = self.height() - 16
        painter.setPen(col_text)
        legend_font = QFont(painter.font())
        legend_font.setPixelSize(9)
        painter.setFont(legend_font)
        lx = self.LABEL_WIDTH
        for color, label in [
            (col_span, "Time Span"),
            (col_estimated, "Estimated"),
            (col_actual, "Actual Work"),
        ]:
            color_full = QColor(color)
            color_full.setAlpha(255)
            painter.fillRect(lx, legend_y, 10, 10, color_full)
            painter.drawText(lx + 14, legend_y - 1, 70, 12, Qt.AlignmentFlag.AlignLeft, label)
            lx += 90

        painter.end()

    def _hit_test_row(self, pos) -> int:
        """Return item index at pos, or -1."""
        y = pos.y() - self.HEADER_HEIGHT
        if y < 0:
            return -1
        row = int(y / self.ROW_HEIGHT)
        if 0 <= row < len(self._items):
            return row
        return -1

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        row = self._hit_test_row(a0.pos())
        if row >= 0:
            self.task_clicked.emit(self._items[row].id)

    def contextMenuEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        row = self._hit_test_row(a0.pos())
        if row >= 0:
            item = self._items[row]
            self.task_clicked.emit(item.id)
            self.task_right_clicked.emit(item.id, a0.globalPos())

    def mouseMoveEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        row = self._hit_test_row(a0.pos())
        if row >= 0:
            item = self._items[row]
            parts = [item.reminder]
            if item.due_date:
                parts.append(f"Due: {item.due_date.strftime('%b %d')}")
            if item.due_time:
                parts.append(f"Time: {item.due_time.strftime('%I:%M %p').lstrip('0')}")
            if item.estimated_pomodoros:
                parts.append(f"Estimated: {item.estimated_pomodoros} pomodoros")
            if item.pomodoro_count:
                parts.append(f"Completed: {item.pomodoro_count} pomodoros")
            if item.time_spent:
                mins = item.time_spent // 60
                parts.append(f"Time spent: {mins}m")
            if item.tags:
                parts.append(f"Tags: {', '.join(item.tags)}")
            from PyQt6.QtWidgets import QToolTip

            QToolTip.showText(a0.globalPosition().toPoint(), "\n".join(parts), self)
        else:
            from PyQt6.QtWidgets import QToolTip

            QToolTip.hideText()


# ---------------------------------------------------------------------------
# Day-of-week header bar
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Week View — 7 day columns × 25 rows (all-day + 24 hours)
# ---------------------------------------------------------------------------

_WEEK_ITEMS_ROLE = Qt.ItemDataRole.UserRole + 10
_WEEK_HOUR_ROLE = Qt.ItemDataRole.UserRole + 11
_WEEK_DATE_ROLE = Qt.ItemDataRole.UserRole + 12


class _WeekModel(QAbstractTableModel):
    """Data model for week view — 7 columns (days) × 25 rows (all-day + hours)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._week_dates: list[date] = []
        self._items_by_date: dict[date, list] = {}
        self._set_week(date.today())

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 25  # row 0 = all-day, rows 1-24 = hours 0-23

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 7

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if col >= len(self._week_dates):
            return None

        d = self._week_dates[col]

        if role == _WEEK_DATE_ROLE:
            return d
        if role == _WEEK_HOUR_ROLE:
            return row - 1 if row > 0 else -1  # -1 = all-day

        if role == _WEEK_ITEMS_ROLE:
            items = self._items_by_date.get(d, [])
            if row == 0:
                # All-day: items with due_date but no due_time
                return [i for i in items if i.due_time is None]
            hour = row - 1
            return [i for i in items if i.due_time and i.due_time.hour == hour]

        if role == Qt.ItemDataRole.DisplayRole:
            if row == 0:
                return "All Day"
            return f"{row - 1:02d}:00"
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if section < len(self._week_dates):
                d = self._week_dates[section]
                return d.strftime("%a %d")
            return ""
        # Vertical: hour labels
        if section == 0:
            return "All Day"
        return f"{section - 1:02d}:00"

    def _set_week(self, d: date) -> None:
        start = d - timedelta(days=d.weekday())
        self._week_dates = [start + timedelta(days=i) for i in range(7)]

    def set_week(self, d: date) -> None:
        self.beginResetModel()
        self._set_week(d)
        self.endResetModel()

    def set_items(self, items_by_date: dict[date, list]) -> None:
        self.beginResetModel()
        self._items_by_date = items_by_date
        self.endResetModel()

    def week_dates(self) -> list[date]:
        return list(self._week_dates)


class _WeekDelegate(QStyledItemDelegate):
    """Painter for week view cells — shows task chips in hour slots."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._today = date.today()
        self._selected_item_id: UUID | None = None
        self._colors: dict[str, str] = {}
        self._refresh_colors()

    def _refresh_colors(self) -> None:
        from ...gui.styles.themes import get_colors

        self._colors = get_colors()

    def set_selected(self, item_id: UUID | None) -> None:
        self._selected_item_id = item_id

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(option.rect)

        rect = option.rect
        c = self._colors
        cell_date = index.data(_WEEK_DATE_ROLE)
        hour = index.data(_WEEK_HOUR_ROLE)
        items: list = index.data(_WEEK_ITEMS_ROLE) or []

        col_base = QColor(c["base"])
        col_alt_base = QColor(c["alternate_base"])
        col_highlight = QColor(c["highlight"])
        col_highlight_text = QColor(c["highlight_text"])
        col_text = QColor(c["text"])
        col_completed_text = QColor(c["completed_text"])
        col_border = QColor(c["border"])

        # Background
        is_today = cell_date == self._today if cell_date else False
        is_weekend = cell_date.weekday() >= 5 if cell_date else False
        is_all_day = hour == -1

        if is_today and is_all_day:
            painter.fillRect(rect, col_highlight)
        elif is_today:
            # Subtle today tint for hour cells
            today_bg = QColor(col_highlight)
            today_bg.setAlpha(30)
            painter.fillRect(rect, col_base)
            painter.fillRect(rect, today_bg)
        elif is_weekend:
            painter.fillRect(rect, col_alt_base)
        else:
            painter.fillRect(rect, col_base)

        # Grid lines
        painter.setPen(QPen(col_border, 1))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        if not items:
            painter.restore()
            return

        # Draw task chips
        item_font = QFont(painter.font())
        item_font.setPixelSize(10)
        painter.setFont(item_font)
        fm = QFontMetrics(item_font)

        chip_height = fm.height() + 4
        y = rect.top() + 2
        x = rect.left() + 2
        text_width = rect.width() - 8
        max_chips = max(1, (rect.height() - 4) // chip_height)

        col_priority = {
            1: QColor(c["priority_high"]),
            2: QColor(c["priority_normal"]),
            3: QColor(c["priority_low"]),
        }

        for i in range(min(max_chips, len(items))):
            item = items[i]
            chip_y = y + i * chip_height
            is_selected = bool(self._selected_item_id and item.id == self._selected_item_id)

            # Completed bg
            if item.complete:
                chip_rect = rect.adjusted(2, 0, -2, 0)
                chip_rect.setTop(chip_y)
                chip_rect.setHeight(chip_height)
                painter.fillRect(chip_rect, QColor(c["completed_bg"]))

            # Selection
            if is_selected:
                sel_rect = rect.adjusted(2, 0, -2, 0)
                sel_rect.setTop(chip_y)
                sel_rect.setHeight(chip_height)
                sel_bg = QColor(col_alt_base)
                sel_bg.setAlpha(200)
                painter.fillRect(sel_rect, sel_bg)
                painter.setPen(QPen(col_border.lighter(150), 2))
                painter.drawRoundedRect(sel_rect, 2, 2)

            # Priority bar
            p_color = col_priority.get(item.priority, col_priority[2])
            painter.fillRect(x, chip_y + 1, 3, chip_height - 2, p_color)

            # Text
            if item.complete:
                painter.setPen(col_completed_text)
            elif is_today and is_all_day:
                painter.setPen(col_highlight_text)
            else:
                painter.setPen(col_text)

            prefix = "\u2713 " if item.complete else ""
            text = fm.elidedText(prefix + item.reminder, Qt.TextElideMode.ElideRight, text_width)
            painter.drawText(
                x + 6,
                chip_y,
                text_width,
                chip_height,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

            # Strikethrough
            if item.complete:
                painter.setPen(QPen(col_completed_text, 1))
                strike_y = chip_y + chip_height // 2
                prefix_w = fm.horizontalAdvance(prefix)
                painter.drawLine(
                    x + 6 + prefix_w,
                    strike_y,
                    x + 6 + fm.horizontalAdvance(text),
                    strike_y,
                )

        # Overflow
        overflow = len(items) - max_chips
        if overflow > 0:
            painter.setPen(QColor(c["completed_text"]))
            painter.drawText(
                rect.adjusted(4, 0, -4, 0).translated(0, max_chips * chip_height),
                Qt.AlignmentFlag.AlignCenter,
                f"+{overflow}",
            )

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> Any:
        from PyQt6.QtCore import QSize

        return QSize(100, 40)


class _WeekTableView(QTableView):
    """Week grid with day columns and hour rows."""

    task_clicked = pyqtSignal(object)
    task_double_clicked = pyqtSignal(object)
    task_right_clicked = pyqtSignal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        h_header = self.horizontalHeader()
        assert h_header is not None
        h_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        h_header.setFixedHeight(28)

        v_header = self.verticalHeader()
        assert v_header is not None
        v_header.setDefaultSectionSize(60)
        v_header.setMinimumSectionSize(40)
        v_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        self.setShowGrid(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)
        self.setStyleSheet("QTableView { border: none; background: palette(window); }")

    def _hit_test(self, pos):
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        items = index.data(_WEEK_ITEMS_ROLE) or []
        cell_date = index.data(_WEEK_DATE_ROLE)
        if not items or cell_date is None:
            return None

        rect = self.visualRect(index)
        font = QFont()
        font.setPixelSize(10)
        fm = QFontMetrics(font)
        chip_height = fm.height() + 4
        click_y = pos.y() - rect.top() - 2
        item_idx = int(click_y / chip_height) if chip_height > 0 else -1

        if 0 <= item_idx < len(items):
            return ("task", items[item_idx], index)
        return None

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        super().mousePressEvent(a0)
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit and hit[0] == "task":
            self.task_clicked.emit(hit[1].id)

    def mouseDoubleClickEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit and hit[0] == "task":
            self.task_double_clicked.emit(hit[1].id)

    def contextMenuEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit and hit[0] == "task":
            self.task_clicked.emit(hit[1].id)
            self.task_right_clicked.emit(hit[1].id, a0.globalPos())
        else:
            super().contextMenuEvent(a0)

    def mouseMoveEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit and hit[0] == "task":
            item = hit[1]
            parts = [item.reminder]
            if item.due_time:
                parts.append(f"Due: {item.due_time.strftime('%I:%M %p').lstrip('0')}")
            if item.recurrence_type:
                from ...core.models import format_recurrence

                parts.append(format_recurrence(item))
            if item.estimated_pomodoros > 0 or item.pomodoro_count > 0:
                pom = (
                    f"\U0001f345 {item.pomodoro_count}/{item.estimated_pomodoros}"
                    if item.estimated_pomodoros
                    else f"\U0001f345 {item.pomodoro_count}"
                )
                parts.append(pom)
            if item.tags:
                parts.append(f"Tags: {', '.join(item.tags)}")
            if item.complete:
                parts.append("\u2713 Completed")
            from PyQt6.QtWidgets import QToolTip

            QToolTip.showText(a0.globalPosition().toPoint(), "\n".join(parts), self)
        else:
            from PyQt6.QtWidgets import QToolTip

            QToolTip.hideText()


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

    def set_items(self, items: list, todo_list=None) -> None:
        from ...gui.styles.themes import get_colors

        c = get_colors()

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(3)

        for item in items:
            p_key = {1: "priority_high", 2: "priority_normal", 3: "priority_low"}.get(
                item.priority, "priority_normal"
            )
            bg = c["completed_bg"] if item.complete else c["base"]
            text_color = c["completed_text"] if item.complete else c["text"]
            strike = "text-decoration: line-through;" if item.complete else ""

            row = QPushButton()
            row.setStyleSheet(
                f"QPushButton {{ border-left: 3px solid {c[p_key]}; border-radius: 3px;"
                f" padding: 3px 5px; background: {bg}; text-align: left; margin: 1px 0; }}"
                f" QPushButton:hover {{ background: {c['alternate_base']}; }}"
            )
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(1)

            # Title with checkmark
            prefix = "\u2713 " if item.complete else ""
            title = QLabel(prefix + item.reminder)
            title.setWordWrap(True)
            title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            title.setStyleSheet(
                f"font-size: 10px; {strike} color: {text_color}; border: none; background: none;"
            )
            row_layout.addWidget(title)

            # Detail line
            details = []
            if item.recurrence_type:
                from ...core.models import format_recurrence

                details.append("\u21bb " + format_recurrence(item))
            if item.estimated_pomodoros > 0 or item.pomodoro_count > 0:
                pom = (
                    f"\U0001f345 {item.pomodoro_count}/{item.estimated_pomodoros}"
                    if item.estimated_pomodoros
                    else f"\U0001f345 {item.pomodoro_count}"
                )
                details.append(pom)
            if todo_list:
                children = [
                    ch
                    for ch in todo_list.items.values()
                    if ch.parent_id == item.id and not ch.deleted
                ]
                if children:
                    done_n = sum(1 for ch in children if ch.complete)
                    details.append(f"[{done_n}/{len(children)}]")
            if item.tags:
                details.append(" ".join(item.tags))
            if details:
                detail_lbl = QLabel(" \u2022 ".join(details))
                detail_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                detail_lbl.setStyleSheet(
                    f"font-size: 9px; color: {c['completed_text']}; border: none; background: none;"
                )
                row_layout.addWidget(detail_lbl)

            # Tooltip with full info
            tip_parts = [item.reminder]
            if item.tags:
                tip_parts.append("Tags: " + ", ".join(item.tags))
            if item.recurrence_type:
                from ...core.models import format_recurrence as _fmt_rec

                tip_parts.append(_fmt_rec(item))
            row.setToolTip("\n".join(tip_parts))

            row.clicked.connect(lambda _checked=False, iid=item.id: self.task_clicked.emit(iid))
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

        # Day view — single-column version of week view with larger slots
        self._day_model = _WeekModel()
        self._day_delegate = _WeekDelegate()
        self._day_table = _WeekTableView()
        self._day_table.setModel(self._day_model)
        self._day_table.setItemDelegate(self._day_delegate)
        self._day_table.task_clicked.connect(self._on_task_clicked)
        self._day_table.task_double_clicked.connect(self._on_task_double_clicked)
        self._day_table.task_right_clicked.connect(self._on_task_right_clicked)
        # Larger slots for day view — more room for detail
        v_header = self._day_table.verticalHeader()
        if v_header:
            v_header.setDefaultSectionSize(80)
        # Hide columns 1-6, show only column 0 (the single day)
        for col in range(1, 7):
            self._day_table.setColumnHidden(col, True)
        self._sub_stack.addWidget(self._day_table)  # 0

        # Week view — QTableView with hour rows and day columns
        self._week_model = _WeekModel()
        self._week_delegate = _WeekDelegate()
        self._week_table = _WeekTableView()
        self._week_table.setModel(self._week_model)
        self._week_table.setItemDelegate(self._week_delegate)
        self._week_table.task_clicked.connect(self._on_task_clicked)
        self._week_table.task_double_clicked.connect(self._on_task_double_clicked)
        self._week_table.task_right_clicked.connect(self._on_task_right_clicked)
        self._sub_stack.addWidget(self._week_table)  # 1

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
        self._cal_table.task_right_clicked.connect(self._on_task_right_clicked)
        self._cal_table.more_clicked.connect(self._on_more_clicked)
        month_layout.addWidget(self._cal_table, 1)

        self._sub_stack.addWidget(month_container)  # 2

        # Timeline view — horizontal bars
        self._timeline_widget = _TimelineWidget()
        self._timeline_widget.task_clicked.connect(self._on_task_clicked)
        self._timeline_widget.task_right_clicked.connect(self._on_task_right_clicked)
        timeline_scroll = QScrollArea()
        timeline_scroll.setWidgetResizable(True)
        timeline_scroll.setFrameShape(QFrame.Shape.NoFrame)
        timeline_scroll.setWidget(self._timeline_widget)
        self._sub_stack.addWidget(timeline_scroll)  # 3

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
        self._close_popover()
        if self._todo_list is None:
            self._cal_model.set_items({})
            self._week_model.set_items({})
            self._day_model.set_items({})
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
        self._cal_delegate._todo_list = self._todo_list

        # Week view
        self._week_model.set_items(scheduled)
        self._week_model.set_week(self._current_date)
        self._week_delegate._today = date.today()
        # Update week header labels
        week_dates = self._week_model.week_dates()
        h_header = self._week_table.horizontalHeader()
        if h_header:
            wmodel = self._week_table.model()
            if wmodel:
                for col in range(7):
                    d = week_dates[col] if col < len(week_dates) else None
                    if d:
                        is_today = d == date.today()
                        label = d.strftime("%a %d")
                        if is_today:
                            label = f"\u25cf {label}"
                        wmodel.setHeaderData(col, Qt.Orientation.Horizontal, label)

        # Day view — show single day using week model with 1 visible column
        # Set the week starting from current_date so column 0 = current_date
        self._day_model.set_items(scheduled)
        # Create a fake "week" starting from current_date
        self._day_model._set_week(self._current_date)
        # Shift so column 0 is the target date
        self._day_model._week_dates = [self._current_date] + [
            self._current_date + timedelta(days=i) for i in range(1, 7)
        ]
        self._day_model.layoutChanged.emit()
        self._day_delegate._today = date.today()
        # Update header to show the day name
        h_header = self._day_table.horizontalHeader()
        if h_header:
            h_header.hide()  # Single column doesn't need day header

        # Timeline view — all items with any date info
        all_items = list(self._todo_list.active_items())
        all_items = [i for i in all_items if i.parent_id is None]
        all_items = self._apply_filter(all_items)
        self._timeline_widget.set_data(all_items, self._current_date, self._todo_list)

        self._unscheduled.set_items(unscheduled, todo_list=self._todo_list)

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

        # Auto-scroll to current hour for day and week views
        if idx == self.SUB_DAY:
            from datetime import datetime as _dt

            current_hour = _dt.now().hour
            target_row = current_hour + 1
            index = self._day_model.index(target_row, 0)
            self._day_table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        elif idx == self.SUB_WEEK:
            from datetime import datetime as _dt

            current_hour = _dt.now().hour
            # Row 0 = All Day, row N = hour N-1, so current hour is row current_hour+1
            target_row = current_hour + 1
            index = self._week_model.index(target_row, 0)
            self._week_table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    # --- Task interaction ---

    def _on_task_clicked(self, item_id: UUID) -> None:
        self._selected_item_id = item_id
        self._cal_delegate.set_selected(item_id)
        self._week_delegate.set_selected(item_id)
        self._day_delegate.set_selected(item_id)
        self._timeline_widget.set_selected(item_id)
        self._cal_table.viewport().update()  # type: ignore[union-attr]
        self._week_table.viewport().update()  # type: ignore[union-attr]
        self._day_table.viewport().update()  # type: ignore[union-attr]

    def _on_task_double_clicked(self, item_id: UUID) -> None:
        self._selected_item_id = item_id
        # TODO: open task detail/edit dialog

    def _on_task_right_clicked(self, item_id: UUID, global_pos) -> None:
        """Show context menu — parity with list/kanban context menus."""
        self._on_task_clicked(item_id)
        self._show_context_menu(item_id, global_pos)

    def _show_context_menu(self, item_id: UUID, global_pos) -> None:
        """Build and show context menu for a task."""
        from PyQt6.QtGui import QAction
        from PyQt6.QtWidgets import QInputDialog, QMenu

        item = None
        if self._todo_list:
            item = self._todo_list.items.get(item_id)

        menu = QMenu(self)

        if item:
            edit_action = QAction("Edit Reminder...", self)

            def _edit_reminder(_checked=False, it=item, iid=item_id):
                text, ok = QInputDialog.getText(
                    self, "Edit Reminder", "Reminder:", text=it.reminder
                )
                if ok and text.strip():
                    self.item_reminder_changed.emit(iid, text.strip())

            edit_action.triggered.connect(_edit_reminder)
            menu.addAction(edit_action)

        edit_tags = QAction("Edit Tags...", self)
        edit_tags.triggered.connect(lambda: self.edit_tags_requested.emit(item_id))
        menu.addAction(edit_tags)

        edit_rec = QAction("Edit Recurrence...", self)
        edit_rec.triggered.connect(self.edit_recurrence_requested.emit)
        menu.addAction(edit_rec)

        focus = QAction("Start Focus Session", self)
        focus.triggered.connect(lambda: self.focus_requested.emit(item_id))
        menu.addAction(focus)

        if item and item.parent_id is None:
            add_sub = QAction("Add Subtask...", self)
            add_sub.triggered.connect(lambda: self.add_subtask_requested.emit(item_id))
            menu.addAction(add_sub)

        menu.addSeparator()

        toggle = QAction("Toggle Complete", self)
        toggle.triggered.connect(self.toggle_requested.emit)
        menu.addAction(toggle)

        delete = QAction("Delete", self)
        delete.triggered.connect(self.delete_requested.emit)
        menu.addAction(delete)

        menu.exec(global_pos)

    def _on_more_clicked(self, cell_date: date, items: list) -> None:
        """Show popover with all tasks for a date."""
        self._show_day_popover(cell_date, items)

    def _show_day_popover(self, cell_date: date, items: list) -> None:
        """Display a floating panel listing all tasks for a specific date."""
        self._close_popover()

        from ...gui.styles.themes import get_colors

        c = get_colors()

        popover = QFrame(
            self,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        popover.setStyleSheet(
            f"QFrame {{ background: {c['base']}; border: 1px solid {c['border']};"
            f" border-radius: 6px; }}"
        )
        popover.setMinimumWidth(340)
        popover.setMaximumWidth(450)
        popover.setMaximumHeight(400)

        pop_layout = QVBoxLayout(popover)
        pop_layout.setContentsMargins(10, 8, 10, 8)
        pop_layout.setSpacing(4)

        # Header with close button (QPainter rendered for readability)
        header_row = QHBoxLayout()
        header = QLabel(cell_date.strftime("%A, %B %d"))
        header.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {c['text']}; border: none;"
        )
        header_row.addWidget(header)
        header_row.addStretch()

        close_btn = _CloseButton(on_click=self._close_popover)
        header_row.addWidget(close_btn)
        pop_layout.addLayout(header_row)

        count_lbl = QLabel(f"{len(items)} task{'s' if len(items) != 1 else ''}")
        count_lbl.setStyleSheet(f"font-size: 10px; color: {c['completed_text']}; border: none;")
        pop_layout.addWidget(count_lbl)

        # Scrollable task list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(270)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 4, 0, 0)
        content_layout.setSpacing(3)

        for item in items:
            p_key = {1: "priority_high", 2: "priority_normal", 3: "priority_low"}.get(
                item.priority, "priority_normal"
            )
            p_color = c[p_key]
            bg = c["completed_bg"] if item.complete else "none"
            text_color = c["completed_text"] if item.complete else c["text"]
            strike = "text-decoration: line-through;" if item.complete else ""

            row = QPushButton()
            row._item_id = item.id  # type: ignore[attr-defined]
            row.setStyleSheet(
                f"QPushButton {{ border-left: 3px solid {p_color}; border-radius: 4px;"
                f" padding: 6px 8px; background: {bg}; text-align: left; }}"
                f" QPushButton:hover {{ background: {c['alternate_base']}; }}"
            )
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(6, 3, 6, 3)
            row_layout.setSpacing(2)

            # Title line: checkmark + reminder
            prefix = "\u2713 " if item.complete else ""
            title = QLabel(prefix + item.reminder)
            title.setWordWrap(True)
            title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            title.setStyleSheet(
                f"font-size: 12px; {strike} color: {text_color}; border: none; background: none;"
            )
            row_layout.addWidget(title)

            # Detail line: time, recurrence, pomodoro, subtasks, tags
            details = []
            if item.due_time:
                details.append(item.due_time.strftime("%I:%M %p").lstrip("0"))
            if item.recurrence_type:
                from ...core.models import format_recurrence

                details.append("\u21bb " + format_recurrence(item))
            if item.estimated_pomodoros > 0 or item.pomodoro_count > 0:
                pom = (
                    f"\U0001f345 {item.pomodoro_count}/{item.estimated_pomodoros}"
                    if item.estimated_pomodoros
                    else f"\U0001f345 {item.pomodoro_count}"
                )
                details.append(pom)
            # Subtask count
            if self._todo_list:
                children = [
                    ch
                    for ch in self._todo_list.items.values()
                    if ch.parent_id == item.id and not ch.deleted
                ]
                if children:
                    done_n = sum(1 for ch in children if ch.complete)
                    details.append(f"[{done_n}/{len(children)}]")
            if item.tags:
                details.append(" ".join(item.tags))
            if details:
                detail_lbl = QLabel(" \u2022 ".join(details))
                detail_lbl.setWordWrap(True)
                detail_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                detail_lbl.setStyleSheet(
                    f"font-size: 10px; color: {c['completed_text']};"
                    f" border: none; background: none;"
                )
                row_layout.addWidget(detail_lbl)

            row.clicked.connect(lambda _checked=False, iid=item.id: self._select_from_popover(iid))
            row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            row.customContextMenuRequested.connect(
                lambda pos, btn=row, iid=item.id: self._popover_context_menu(
                    iid, btn.mapToGlobal(pos)
                )
            )
            content_layout.addWidget(row)

        content_layout.addStretch()
        scroll.setWidget(content)
        pop_layout.addWidget(scroll)

        # Position near the mouse
        from PyQt6.QtGui import QCursor

        pos = QCursor.pos()
        popover.move(pos.x() - 125, pos.y() + 10)
        popover.show()
        self._popover = popover

    def _select_from_popover(self, item_id: UUID) -> None:
        """Select a task from the day popover — stays open, highlights selection."""
        self._selected_item_id = item_id
        self._cal_delegate.set_selected(item_id)
        vp = self._cal_table.viewport()
        if vp:
            vp.update()
        # Highlight the selected row in the popover
        if hasattr(self, "_popover") and self._popover is not None:
            from ...gui.styles.themes import get_colors

            c = get_colors()
            for btn in self._popover.findChildren(QPushButton):
                if getattr(btn, "_item_id", None) == item_id:
                    btn.setStyleSheet(
                        btn.styleSheet().replace(
                            "background: none", f"background: {c['alternate_base']}"
                        )
                    )
                elif hasattr(btn, "_item_id"):
                    # Reset other buttons
                    btn.setStyleSheet(
                        btn.styleSheet().replace(
                            f"background: {c['alternate_base']}", "background: none"
                        )
                    )

    def _popover_context_menu(self, item_id: UUID, global_pos) -> None:
        """Right-click on popover item — select and show context menu."""
        self._select_from_popover(item_id)
        self._show_context_menu(item_id, global_pos)

    def _close_popover(self) -> None:
        """Close the day popover."""
        if hasattr(self, "_popover") and self._popover is not None:
            self._popover.close()
            self._popover = None
