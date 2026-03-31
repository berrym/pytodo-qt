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

from PyQt6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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


def _format_hour(hour: int) -> str:
    """Format an hour (0-23) using the app's time_format config."""
    from ...core.config import get_config

    fmt = get_config().appearance.time_format
    if fmt == "12h" or (fmt == "system" and _is_system_12h()):
        if hour == 0:
            return "12 AM"
        if hour < 12:
            return f"{hour} AM"
        if hour == 12:
            return "12 PM"
        return f"{hour - 12} PM"
    return f"{hour:02d}:00"


def _is_system_12h() -> bool:
    """Check if the system locale uses 12-hour time."""
    from PyQt6.QtCore import QLocale

    locale = QLocale.system()
    fmt = locale.timeFormat(QLocale.FormatType.ShortFormat)
    return "AP" in fmt.upper() or "AM" in fmt.upper()


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
    task_dropped = pyqtSignal(object, object)  # (item_id UUID, target_date)

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
        self.setAcceptDrops(True)
        self.setStyleSheet("QTableView { border: none; background: palette(window); }")
        self._drag_start_pos = None
        self._drag_item_id = None
        self._dragging = False

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
        self._drag_start_pos = None
        self._drag_item_id = None
        self._dragging = False
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit is None:
            return
        if hit[0] == "task":
            self.task_clicked.emit(hit[1].id)
            if a0.button() == Qt.MouseButton.LeftButton:
                self._drag_start_pos = a0.pos()
                self._drag_item_id = hit[1].id
        elif hit[0] == "more":
            self.more_clicked.emit(hit[1], hit[2])

    def mouseDoubleClickEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit is not None and hit[0] == "task":
            self.task_double_clicked.emit(hit[1].id)

    def mouseReleaseEvent(self, a0) -> None:  # noqa: N802
        self._drag_start_pos = None
        self._drag_item_id = None
        self._dragging = False
        super().mouseReleaseEvent(a0)

    def mouseMoveEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        # Drag initiation
        if (
            not self._dragging
            and self._drag_start_pos is not None
            and self._drag_item_id is not None
            and (a0.pos() - self._drag_start_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._dragging = True
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(
                "application/x-pytodo-item-id",
                str(self._drag_item_id).encode(),
            )
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
            # Reset after exec — mouseReleaseEvent won't fire
            self._drag_start_pos = None
            self._drag_item_id = None
            self._dragging = False
            return
        # Tooltip on hover (only when not dragging)
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

    def dragEnterEvent(self, a0) -> None:  # noqa: N802
        if a0 and a0.mimeData() and a0.mimeData().hasFormat("application/x-pytodo-item-id"):
            a0.acceptProposedAction()

    def dragMoveEvent(self, a0) -> None:  # noqa: N802
        if a0 and a0.mimeData() and a0.mimeData().hasFormat("application/x-pytodo-item-id"):
            a0.acceptProposedAction()

    def dropEvent(self, a0) -> None:  # noqa: N802
        if a0 is None or a0.mimeData() is None:
            return
        mime = a0.mimeData()
        if not mime.hasFormat("application/x-pytodo-item-id"):
            return
        item_id_str = bytes(mime.data("application/x-pytodo-item-id")).decode()
        index = self.indexAt(a0.position().toPoint())
        if not index.isValid():
            return
        target_date = index.data(_DATE_ROLE)
        if target_date is None:
            return
        try:
            item_id = UUID(item_id_str)
        except ValueError:
            return
        self.task_dropped.emit(item_id, target_date)
        a0.acceptProposedAction()


# ---------------------------------------------------------------------------
# Timeline View — horizontal bars showing task spans and effort
# ---------------------------------------------------------------------------


def _item_work_mins(item, config_default: int) -> int:
    """Per-item work_duration or global config fallback."""
    return item.work_duration if item.work_duration > 0 else config_default


class _TimelineTasksWidget(QWidget):
    """Gantt-style horizontal timeline with task bars.

    Batched rendering: 6 BarGraphItems total (not N per item), each with
    N-element numpy arrays. Real-time updates via setOpts() on persistent items.
    Gradient brushes, pen outlines, persistent today line and tooltip.
    """

    task_clicked = pyqtSignal(object)  # item_id
    task_right_clicked = pyqtSignal(object, object)  # item_id, global_pos

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import pyqtgraph as pg

        self._items: list = []
        self._range_start: date = date.today() - timedelta(days=3)
        self._range_end: date = date.today() + timedelta(days=11)
        self._selected_item_id: UUID | None = None
        self._todo_list = None
        self._active_item_id: UUID | None = None
        self._active_elapsed: int = 0
        self._active_session_type: str = ""

        # Persistent item references
        self._span_bar: pg.BarGraphItem | None = None
        self._overdue_bar: pg.BarGraphItem | None = None
        self._est_bar: pg.BarGraphItem | None = None
        self._pom_bar: pg.BarGraphItem | None = None
        self._sw_bar: pg.BarGraphItem | None = None
        self._overflow_bar: pg.BarGraphItem | None = None
        self._today_line: pg.InfiniteLine | None = None

        # Base data arrays (N items)
        self._item_indices: dict[UUID, int] = {}
        self._pom_widths = None
        self._pom_x0s = None
        self._sw_widths = None
        self._sw_x0s = None
        self._overflow_widths = None
        self._overflow_x0s = None
        self._est_widths_arr = None

        self._create_styles()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=True, y=False)
        self._plot.showGrid(x=True, y=True, alpha=0.35)
        self._plot.setMenuEnabled(False)
        self._plot.getAxis("left").setWidth(160)
        self._plot.getAxis("bottom").setHeight(30)

        # Click and hover
        self._plot.scene().sigMouseClicked.connect(self._on_plot_clicked)
        self._hover_proxy = pg.SignalProxy(
            self._plot.scene().sigMouseMoved, rateLimit=30, slot=self._on_mouse_moved
        )
        self._last_hover_row = -1
        self._tooltip_label = QLabel(self)
        self._tooltip_label.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self._tooltip_label.setStyleSheet(
            "QLabel { background: palette(toolTipBase); color: palette(toolTipText); "
            "border: 1px solid palette(mid); padding: 6px 8px; font-size: 12px; }"
        )
        self._tooltip_label.hide()

        layout.addWidget(self._plot)

        # Legend
        self._legend_widget = QWidget()
        self._legend_widget.setFixedHeight(28)
        legend_layout = QHBoxLayout(self._legend_widget)
        legend_layout.setContentsMargins(160, 4, 10, 4)
        legend_layout.setSpacing(16)
        self._legend_labels: list[QLabel] = []
        layout.addWidget(self._legend_widget)

    def _create_styles(self) -> None:
        from PyQt6.QtGui import QBrush, QGradient, QLinearGradient, QPen

        from ...gui.styles.themes import get_colors

        c = get_colors()
        self._colors = c

        # Span (flat, semi-transparent)
        span_c = QColor(c.get("chart_span", "#4992ff"))
        span_c.setAlpha(int(c.get("chart_span_alpha", "90")))
        self._span_brush = QBrush(span_c)
        self._span_pen = QPen(Qt.PenStyle.NoPen)

        # Estimate (gradient)
        est_base = QColor(c.get("chart_estimate", "#3D4147"))
        est_grad = QLinearGradient(0, 0, 0, 1)
        est_grad.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
        est_grad.setColorAt(0.0, est_base.lighter(115))
        est_grad.setColorAt(1.0, est_base)
        self._est_brush = QBrush(est_grad)
        est_border = QColor(c.get("chart_estimate_border", "#555B63"))
        self._est_pen = QPen(est_border, 1)

        # Pomodoro (gradient)
        pom_base = QColor(c.get("chart_pomodoro", "#D55E00"))
        pom_base.setAlpha(int(c.get("chart_pomodoro_alpha", "200")))
        pom_grad = QLinearGradient(0, 0, 1, 0)
        pom_grad.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
        pom_grad.setColorAt(0.0, pom_base)
        pom_grad.setColorAt(1.0, pom_base.lighter(115))
        self._pom_brush = QBrush(pom_grad)
        self._pom_pen = QPen(pom_base.darker(130), 1)

        # Stopwatch (gradient)
        sw_base = QColor(c.get("chart_stopwatch", "#0072B2"))
        sw_base.setAlpha(int(c.get("chart_stopwatch_alpha", "200")))
        sw_grad = QLinearGradient(0, 0, 1, 0)
        sw_grad.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
        sw_grad.setColorAt(0.0, sw_base)
        sw_grad.setColorAt(1.0, sw_base.lighter(115))
        self._sw_brush = QBrush(sw_grad)
        self._sw_pen = QPen(sw_base.darker(130), 1)

        # Overdue
        od_c = QColor(c.get("chart_overdue", "#ff6e76"))
        od_c.setAlpha(int(c.get("chart_overdue_alpha", "60")))
        self._overdue_brush = QBrush(od_c)

        # Overflow
        of_c = QColor(c.get("chart_overflow_actual", "#ff6e76"))
        of_c.setAlpha(int(c.get("chart_overflow_actual_alpha", "80")))
        self._overflow_brush = QBrush(of_c)

        self._col_text = QColor(c.get("text", "#e0e0e0"))
        self._col_border = QColor(c.get("border", "#3c3c3c"))
        self._col_highlight = QColor(c.get("highlight", "#0078d4"))

    def set_data(self, items: list, current_date: date, todo_list=None) -> None:
        from ...core.config import ConfigManager

        self._items = [i for i in items if i.parent_id is None]

        try:
            sort_tiers = ConfigManager().load().database.sort_tiers()
        except Exception:
            sort_tiers = [("completion", False), ("due_date", False), ("priority", False)]

        from .todo_table import _sort_fragment

        def sort_key(item):
            key: list = []
            for dimension, reverse in sort_tiers:
                key.extend(_sort_fragment(item, dimension, reverse))
            key.append(item.reminder.lower())
            return tuple(key)

        self._items.sort(key=sort_key)

        self._range_start = current_date - timedelta(days=3)
        self._range_end = current_date + timedelta(days=11)
        self._todo_list = todo_list
        self._rebuild_plot()

    def set_active_session(
        self, item_id: UUID | None, elapsed: int = 0, session_type: str = ""
    ) -> None:
        old_id = self._active_item_id
        self._active_item_id = item_id
        self._active_elapsed = elapsed
        self._active_session_type = session_type

        if item_id != old_id:
            self._rebuild_plot()
        else:
            self._update_realtime()

    def set_selected(self, item_id: UUID | None) -> None:
        self._selected_item_id = item_id

    def _date_to_days(self, d: date) -> float:
        return float((d - self._range_start).days)

    def _ms_to_date(self, ms: int) -> date:
        from datetime import datetime as _dt

        return _dt.fromtimestamp(ms / 1000).date()

    def _update_realtime(self) -> None:
        """In-place update: only modify active item's pom/sw/overflow bars via setOpts."""
        if self._pom_bar is None or self._pom_widths is None:
            return
        if self._active_item_id is None or self._active_item_id not in self._item_indices:
            return

        from ...core.config import get_config

        idx = self._item_indices[self._active_item_id]
        item = self._items[idx]
        config_work_mins = get_config().pomodoro.work_duration
        work_mins = _item_work_mins(item, config_work_mins)
        minutes_per_day = 480.0

        pomodoro_seconds = item.pomodoro_count * work_mins * 60
        total_time = item.time_spent

        if self._active_elapsed > 0:
            if self._active_session_type == "work":
                pomodoro_seconds += self._active_elapsed
            total_time += self._active_elapsed

        pomodoro_seconds = min(pomodoro_seconds, total_time)
        stopwatch_seconds = max(0, total_time - pomodoro_seconds)

        pom_days = (pomodoro_seconds / 60.0) / minutes_per_day
        sw_days = (stopwatch_seconds / 60.0) / minutes_per_day
        span_start = float(self._pom_x0s[idx]) if self._pom_x0s is not None else 0.0

        # Update arrays at active index
        self._pom_widths[idx] = pom_days
        self._sw_x0s[idx] = span_start + pom_days
        self._sw_widths[idx] = sw_days

        # Overflow
        total_days = pom_days + sw_days
        if self._est_widths_arr is not None and self._est_widths_arr[idx] > 0:
            est_d = self._est_widths_arr[idx]
            if total_days > est_d:
                self._overflow_x0s[idx] = span_start + est_d
                self._overflow_widths[idx] = total_days - est_d
            else:
                self._overflow_widths[idx] = 0.0

        self._pom_bar.setOpts(width=self._pom_widths)
        self._sw_bar.setOpts(x0=self._sw_x0s, width=self._sw_widths)
        self._overflow_bar.setOpts(x0=self._overflow_x0s, width=self._overflow_widths)

    def _rebuild_plot(self) -> None:
        import numpy as np
        import pyqtgraph as pg

        self._create_styles()
        plot = self._plot
        plot.clear()
        plot.setBackground(self._colors.get("base", "#252526"))

        # Clear legend
        for lbl in self._legend_labels:
            lbl.deleteLater()
        self._legend_labels.clear()

        # Reset references
        self._span_bar = None
        self._overdue_bar = None
        self._est_bar = None
        self._pom_bar = None
        self._sw_bar = None
        self._overflow_bar = None
        self._today_line = None
        self._item_indices = {}

        if not self._items:
            self._build_legend()
            return

        from ...core.config import get_config

        config_work_mins = get_config().pomodoro.work_duration
        today = date.today()
        n = len(self._items)
        minutes_per_day = 480.0

        # Bar geometry constants
        span_h = 0.06
        bar_h = 0.25

        # Pre-allocate numpy arrays for all N items x 6 bar types
        span_x0 = np.zeros(n)
        span_y0 = np.zeros(n)
        span_w = np.zeros(n)
        span_h_arr = np.full(n, span_h)

        od_x0 = np.zeros(n)
        od_y0 = np.zeros(n)
        od_w = np.zeros(n)
        od_h = np.full(n, span_h)

        est_x0 = np.zeros(n)
        est_y0 = np.zeros(n)
        est_w = np.zeros(n)
        est_h = np.full(n, bar_h)

        pom_x0 = np.zeros(n)
        pom_y0 = np.zeros(n)
        pom_w = np.zeros(n)
        pom_h = np.full(n, bar_h)

        sw_x0 = np.zeros(n)
        sw_y0 = np.zeros(n)
        sw_w = np.zeros(n)
        sw_h = np.full(n, bar_h)

        of_x0 = np.zeros(n)
        of_y0 = np.zeros(n)
        of_w = np.zeros(n)
        of_h = np.full(n, bar_h)

        y_ticks = []

        for i, item in enumerate(self._items):
            y_base = float(n - 1 - i)
            self._item_indices[item.id] = i

            label_text = item.reminder
            if len(label_text) > 28:
                label_text = label_text[:26] + "\u2026"
            if item.complete:
                label_text = "\u2713 " + label_text
            y_ticks.append((y_base, label_text))

            created_date = self._ms_to_date(item.created_at)
            end_date = (item.due_date + timedelta(days=1)) if item.due_date else today
            s_start = self._date_to_days(created_date)
            s_end = self._date_to_days(end_date)
            s_width = max(0.1, s_end - s_start)

            # Span
            span_x0[i] = s_start
            span_y0[i] = y_base + 0.30
            span_w[i] = s_width

            # Overdue
            if item.due_date and today > item.due_date and not item.complete:
                od_s = self._date_to_days(item.due_date + timedelta(days=1))
                od_e = self._date_to_days(today + timedelta(days=1))
                od_x0[i] = od_s
                od_y0[i] = y_base + 0.30
                od_w[i] = max(0.0, od_e - od_s)
            else:
                od_y0[i] = y_base + 0.30

            # Estimate
            work_mins = _item_work_mins(item, config_work_mins)
            est_minutes = 0.0
            if item.estimated_minutes > 0 and item.estimated_pomodoros > 0:
                est_minutes = item.estimated_minutes + item.estimated_pomodoros * work_mins
            elif item.estimated_minutes > 0:
                est_minutes = float(item.estimated_minutes)
            elif item.estimated_pomodoros > 0:
                est_minutes = float(item.estimated_pomodoros * work_mins)

            est_days = est_minutes / minutes_per_day if est_minutes > 0 else 0.0
            est_x0[i] = s_start
            est_y0[i] = y_base
            est_w[i] = est_days

            # Actual work
            pomodoro_seconds = item.pomodoro_count * work_mins * 60
            total_time = item.time_spent

            # Active session projection
            active_pom_extra = 0
            active_sw_extra = 0
            if (
                self._active_item_id
                and item.id == self._active_item_id
                and self._active_elapsed > 0
            ):
                if self._active_session_type == "work":
                    active_pom_extra = self._active_elapsed
                else:
                    active_sw_extra = self._active_elapsed
                total_time += self._active_elapsed

            pomodoro_seconds = min(pomodoro_seconds + active_pom_extra, total_time)
            stopwatch_seconds = max(0, total_time - pomodoro_seconds) + active_sw_extra
            if pomodoro_seconds + stopwatch_seconds > total_time:
                stopwatch_seconds = max(0, total_time - pomodoro_seconds)

            pom_days = (pomodoro_seconds / 60.0) / minutes_per_day
            sw_days = (stopwatch_seconds / 60.0) / minutes_per_day

            actual_y0 = y_base - 0.30
            pom_x0[i] = s_start
            pom_y0[i] = actual_y0
            pom_w[i] = pom_days

            sw_x0[i] = s_start + pom_days
            sw_y0[i] = actual_y0
            sw_w[i] = sw_days

            # Overflow
            total_actual_days = pom_days + sw_days
            if est_days > 0 and total_actual_days > est_days:
                of_x0[i] = s_start + est_days
                of_y0[i] = actual_y0
                of_w[i] = total_actual_days - est_days
            else:
                of_y0[i] = actual_y0

        # Store arrays for real-time updates
        self._pom_widths = pom_w
        self._pom_x0s = pom_x0
        self._sw_widths = sw_w
        self._sw_x0s = sw_x0
        self._overflow_widths = of_w
        self._overflow_x0s = of_x0
        self._est_widths_arr = est_w

        # Create 6 persistent batched BarGraphItems
        self._span_bar = pg.BarGraphItem(
            x0=span_x0,
            y0=span_y0,
            width=span_w,
            height=span_h_arr,
            brush=self._span_brush,
            pen=self._span_pen,
        )
        plot.addItem(self._span_bar)

        self._overdue_bar = pg.BarGraphItem(
            x0=od_x0,
            y0=od_y0,
            width=od_w,
            height=od_h,
            brush=self._overdue_brush,
            pen=pg.mkPen(None),
        )
        plot.addItem(self._overdue_bar)

        self._est_bar = pg.BarGraphItem(
            x0=est_x0,
            y0=est_y0,
            width=est_w,
            height=est_h,
            brush=self._est_brush,
            pen=self._est_pen,
        )
        plot.addItem(self._est_bar)

        self._pom_bar = pg.BarGraphItem(
            x0=pom_x0,
            y0=pom_y0,
            width=pom_w,
            height=pom_h,
            brush=self._pom_brush,
            pen=self._pom_pen,
        )
        plot.addItem(self._pom_bar)

        self._sw_bar = pg.BarGraphItem(
            x0=sw_x0,
            y0=sw_y0,
            width=sw_w,
            height=sw_h,
            brush=self._sw_brush,
            pen=self._sw_pen,
        )
        plot.addItem(self._sw_bar)

        self._overflow_bar = pg.BarGraphItem(
            x0=of_x0,
            y0=of_y0,
            width=of_w,
            height=of_h,
            brush=self._overflow_brush,
            pen=pg.mkPen(None),
        )
        plot.addItem(self._overflow_bar)

        # Today line (persistent)
        today_x = self._date_to_days(today)
        self._today_line = pg.InfiniteLine(
            pos=today_x,
            angle=90,
            pen=pg.mkPen(self._col_highlight, width=2, style=Qt.PenStyle.DashLine),
        )
        plot.addItem(self._today_line)

        # Axes
        left_axis = plot.getAxis("left")
        left_axis.setTicks([y_ticks])
        left_axis.setTextPen(self._col_text)
        left_axis.setPen(pg.mkPen(self._col_border))

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(self._col_text)
        bottom_axis.setPen(pg.mkPen(self._col_border))

        total_days = (self._range_end - self._range_start).days
        date_ticks = []
        for i in range(total_days + 1):
            d = self._range_start + timedelta(days=i)
            if i % 2 == 0 or d == today:
                label = d.strftime("%b %d")
                if d == today:
                    label = f"\u25b6 {label}"
                date_ticks.append((float(i), label))
        bottom_axis.setTicks([date_ticks])

        plot.setXRange(-0.5, total_days + 0.5, padding=0)
        plot.setYRange(-0.8, n - 0.2, padding=0.02)

        self._build_legend()

    def _build_legend(self) -> None:
        c = self._colors
        text_color = c.get("text", "#e0e0e0")
        legend_layout = self._legend_widget.layout()
        for hex_c, name in [
            (c.get("chart_span", "#4992ff"), "Time Span"),
            (c.get("chart_estimate", "#3D4147"), "Estimated"),
            (c.get("chart_pomodoro", "#D55E00"), "Pomodoro"),
            (c.get("chart_stopwatch", "#0072B2"), "Stopwatch"),
        ]:
            lbl = QLabel(
                f'<span style="color:{hex_c};">\u25a0</span> '
                f'<span style="color:{text_color};">{name}</span>'
            )
            lbl.setStyleSheet("font-size: 11px;")
            if legend_layout is not None:
                legend_layout.addWidget(lbl)
            self._legend_labels.append(lbl)
        if legend_layout is not None:
            legend_layout.addStretch()

    # --- Hover and click ---

    def _row_from_y(self, y_val: float) -> int:
        n = len(self._items)
        row_idx = n - 1 - round(y_val)
        if 0 <= row_idx < n:
            return row_idx
        return -1

    def _build_tooltip(self, item) -> str:
        from ...core.config import get_config

        config_work_mins = get_config().pomodoro.work_duration
        work_mins = _item_work_mins(item, config_work_mins)
        parts = [f"<b>{item.reminder}</b>"]

        if item.due_date:
            overdue = ""
            if date.today() > item.due_date and not item.complete:
                days_over = (date.today() - item.due_date).days
                overdue = f" <span style='color:#ff6e76;'>({days_over}d overdue)</span>"
            parts.append(f"Due: {item.due_date.strftime('%b %d, %Y')}{overdue}")
        if item.due_time:
            parts.append(f"Time: {item.due_time.strftime('%I:%M %p').lstrip('0')}")

        est_parts = []
        if item.estimated_pomodoros > 0:
            est_parts.append(f"{item.estimated_pomodoros} sessions")
        if item.estimated_minutes > 0:
            est_parts.append(f"{item.estimated_minutes} min")
        if est_parts:
            parts.append(f"Estimated: {', '.join(est_parts)}")

        if item.pomodoro_count > 0:
            pom_mins = item.pomodoro_count * work_mins
            parts.append(f"Pomodoro: {item.pomodoro_count} sessions ({pom_mins} min)")

        sw_seconds = max(0, item.time_spent - (item.pomodoro_count * work_mins * 60))
        if sw_seconds > 0:
            sw_mins = sw_seconds // 60
            parts.append(f"Stopwatch: {sw_mins} min")

        if item.time_spent > 0:
            total_mins = item.time_spent // 60
            hours, mins = divmod(total_mins, 60)
            if hours > 0:
                parts.append(f"<b>Total: {hours}h {mins}m</b>")
            else:
                parts.append(f"<b>Total: {mins}m</b>")

        if item.tags:
            parts.append(f"Tags: {', '.join(item.tags)}")
        if item.complete:
            parts.insert(1, "<i>Completed</i>")

        return "<br>".join(parts)

    def _on_mouse_moved(self, event_args) -> None:
        pos = event_args[0]
        vb = self._plot.plotItem.vb
        if vb is None:
            return
        mouse_point = vb.mapSceneToView(pos)
        row_idx = self._row_from_y(mouse_point.y())

        if row_idx != self._last_hover_row:
            self._last_hover_row = row_idx
            if row_idx >= 0:
                item = self._items[row_idx]
                tooltip_text = self._build_tooltip(item)
                self._tooltip_label.setText(tooltip_text)
                self._tooltip_label.adjustSize()

                from PyQt6.QtCore import QPoint

                mapped = self._plot.mapFromScene(pos)
                qpoint = mapped if isinstance(mapped, QPoint) else mapped.toPoint()
                cursor_pos = self.mapToGlobal(qpoint)
                self._tooltip_label.move(cursor_pos.x() + 16, cursor_pos.y() + 8)
                self._tooltip_label.show()
            else:
                self._tooltip_label.hide()

    def _on_plot_clicked(self, event) -> None:
        pos = event.scenePos()
        vb = self._plot.plotItem.vb
        if vb is None:
            return
        mouse_point = vb.mapSceneToView(pos)
        row_idx = self._row_from_y(mouse_point.y())

        if 0 <= row_idx < len(self._items):
            item = self._items[row_idx]
            if event.button() == Qt.MouseButton.LeftButton:
                self.task_clicked.emit(item.id)
            elif event.button() == Qt.MouseButton.RightButton:
                screen_pos = event.screenPos()
                from PyQt6.QtCore import QPoint

                self.task_right_clicked.emit(
                    item.id, QPoint(int(screen_pos.x()), int(screen_pos.y()))
                )


# ---------------------------------------------------------------------------
# Timeline Daily Chart — stacked vertical bars + trend line
# ---------------------------------------------------------------------------


class _TimelineDailyWidget(QWidget):
    """Stacked vertical bar chart: pomodoro + stopwatch minutes per day.

    All items persistent — created once in rebuild(), updated in-place
    via setOpts()/setData() during real-time active session projection.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import pyqtgraph as pg

        self._analytics = None
        self._current_date: date = date.today()
        self._active_elapsed: int = 0
        self._active_session_type: str = ""

        # Persistent item references
        self._pom_bar: pg.BarGraphItem | None = None
        self._sw_bar: pg.BarGraphItem | None = None
        self._trend_line: pg.PlotDataItem | None = None
        self._base_pom_mins = None
        self._base_sw_mins = None
        self._trend_x = None
        self._trend_y = None

        self._create_styles()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=False, y=True)
        self._plot.showGrid(x=False, y=True, alpha=0.25)
        self._plot.setMenuEnabled(False)
        self._plot.enableAutoRange(axis="y")
        layout.addWidget(self._plot)

        # Legend (always visible)
        self._legend_widget = QWidget()
        self._legend_widget.setFixedHeight(28)
        legend_layout = QHBoxLayout(self._legend_widget)
        legend_layout.setContentsMargins(10, 4, 10, 4)
        legend_layout.setSpacing(16)
        self._legend_labels: list[QLabel] = []
        layout.addWidget(self._legend_widget)

    def _create_styles(self) -> None:
        from PyQt6.QtGui import QBrush, QGradient, QLinearGradient, QPen

        from ...gui.styles.themes import get_colors

        c = get_colors()
        self._colors = c

        # Pomodoro: vertical gradient (bottom→top = dark→light)
        pom_base = QColor(c.get("chart_pomodoro", "#D55E00"))
        pom_grad = QLinearGradient(0, 1, 0, 0)
        pom_grad.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
        pom_grad.setColorAt(0.0, pom_base)
        pom_grad.setColorAt(1.0, pom_base.lighter(115))
        self._pom_brush = QBrush(pom_grad)
        self._pom_pen = QPen(pom_base.darker(130), 1)

        # Stopwatch: vertical gradient
        sw_base = QColor(c.get("chart_stopwatch", "#0072B2"))
        sw_grad = QLinearGradient(0, 1, 0, 0)
        sw_grad.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
        sw_grad.setColorAt(0.0, sw_base)
        sw_grad.setColorAt(1.0, sw_base.lighter(115))
        self._sw_brush = QBrush(sw_grad)
        self._sw_pen = QPen(sw_base.darker(130), 1)

        # Trend line
        self._trend_pen = QPen(QColor(c.get("highlight", "#0078d4")), 2)
        self._trend_pen.setStyle(Qt.PenStyle.DashLine)

        # Text/border
        self._col_text = QColor(c.get("text", "#e0e0e0"))
        self._col_border = QColor(c.get("border", "#3c3c3c"))

    def set_analytics(self, analytics) -> None:
        self._analytics = analytics

    def set_active_session(self, elapsed: int = 0, session_type: str = "") -> None:
        self._active_elapsed = elapsed
        self._active_session_type = session_type
        self._update_realtime()

    def set_current_date(self, d: date) -> None:
        self._current_date = d
        self.rebuild()

    def _update_realtime(self) -> None:
        """In-place update: setOpts on bars, setData on trend. Zero item creation."""
        if self._pom_bar is None or self._base_pom_mins is None:
            return

        pom = self._base_pom_mins.copy()
        sw = self._base_sw_mins.copy()

        if self._active_elapsed > 0:
            week_start = self._current_date - timedelta(days=self._current_date.weekday())
            today_idx = (date.today() - week_start).days
            if 0 <= today_idx < 7:
                extra = self._active_elapsed / 60.0
                if self._active_session_type == "work":
                    pom[today_idx] += extra
                else:
                    sw[today_idx] += extra

        self._pom_bar.setOpts(height=pom)
        self._sw_bar.setOpts(height=sw, y0=pom)

        # Update trend line with projected today value
        if self._trend_line is not None and self._trend_x is not None and len(self._trend_x) > 0:
            trend_y = self._trend_y.copy()
            # Adjust the last trend point if it falls on today
            week_start = self._current_date - timedelta(days=self._current_date.weekday())
            today_idx = (date.today() - week_start).days
            if 0 <= today_idx < 7:
                for j, tx in enumerate(self._trend_x):
                    if int(tx) == today_idx:
                        trend_y[j] += self._active_elapsed / 60.0
            self._trend_line.setData(self._trend_x, trend_y)

    def rebuild(self) -> None:
        import numpy as np
        import pyqtgraph as pg

        self._create_styles()
        plot = self._plot
        plot.clear()
        plot.setBackground(self._colors.get("base", "#252526"))

        # Clear legend
        for lbl in self._legend_labels:
            lbl.deleteLater()
        self._legend_labels.clear()

        # Reset item references
        self._pom_bar = None
        self._sw_bar = None
        self._trend_line = None
        self._base_pom_mins = None
        self._base_sw_mins = None
        self._trend_x = None
        self._trend_y = None

        if self._analytics is None:
            self._show_empty("Analytics service not available")
            self._build_legend()
            return

        week_start = self._current_date - timedelta(days=self._current_date.weekday())
        week_end = week_start + timedelta(days=6)
        summary = self._analytics.daily_summary(
            start_date=week_start.isoformat(), end_date=week_end.isoformat()
        )

        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        x_pos = np.arange(7, dtype=float)
        pom_mins = np.zeros(7)
        sw_mins = np.zeros(7)

        if not summary.empty:
            import pandas as pd

            for _, row in summary.iterrows():
                d = row["date"]
                if isinstance(d, pd.Timestamp):
                    d = d.date()
                idx = (d - week_start).days if hasattr(d, "__sub__") else -1
                if 0 <= idx < 7:
                    pom_mins[idx] = float(row.get("work_minutes", 0))
                    sw_mins[idx] = float(row.get("stopwatch_minutes", 0))

        # Store base data for real-time updates
        self._base_pom_mins = pom_mins.copy()
        self._base_sw_mins = sw_mins.copy()

        # Create persistent bar items (always, even if zero — for real-time growth)
        self._pom_bar = pg.BarGraphItem(
            x=x_pos,
            width=0.6,
            height=pom_mins,
            y0=np.zeros(7),
            brush=self._pom_brush,
            pen=self._pom_pen,
        )
        plot.addItem(self._pom_bar)

        self._sw_bar = pg.BarGraphItem(
            x=x_pos,
            width=0.6,
            height=sw_mins,
            y0=pom_mins,
            brush=self._sw_brush,
            pen=self._sw_pen,
        )
        plot.addItem(self._sw_bar)

        # Trend line (persistent — updated via setData in _update_realtime)
        rolling = self._analytics.rolling_averages(window_7=True, window_30=False)
        trend_x_list: list[float] = []
        trend_y_list: list[float] = []
        if not rolling.empty and len(rolling) >= 2:
            import pandas as pd

            for _, row in rolling.iterrows():
                rd = row["date"]
                if isinstance(rd, pd.Timestamp):
                    rd = rd.date()
                idx = (rd - week_start).days if hasattr(rd, "__sub__") else -1
                if 0 <= idx < 7:
                    trend_x_list.append(float(idx))
                    trend_y_list.append(float(row.get("rolling_7d_minutes", 0)))

        self._trend_x = (
            np.array(trend_x_list, dtype=float) if trend_x_list else np.array([], dtype=float)
        )
        self._trend_y = (
            np.array(trend_y_list, dtype=float) if trend_y_list else np.array([], dtype=float)
        )

        self._trend_line = pg.PlotDataItem(
            self._trend_x,
            self._trend_y,
            pen=self._trend_pen,
            symbol=None,
        )
        plot.addItem(self._trend_line)

        # Empty state
        total = pom_mins.sum() + sw_mins.sum()
        if total == 0:
            self._show_empty("No sessions this week \u2014 use \u25c0 \u25b6 to navigate")

        # Legend
        self._build_legend()

        # Axes
        left_axis = plot.getAxis("left")
        left_axis.setTextPen(self._col_text)
        left_axis.setPen(pg.mkPen(self._col_border))
        left_axis.setLabel("Minutes")

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTicks([[(float(i), day_labels[i]) for i in range(7)]])
        bottom_axis.setTextPen(self._col_text)
        bottom_axis.setPen(pg.mkPen(self._col_border))

        plot.setXRange(-0.5, 6.5, padding=0)
        max_y = max(float((pom_mins + sw_mins).max()), 1)
        plot.setYRange(0, max_y * 1.15, padding=0)

    def _build_legend(self) -> None:
        c = self._colors
        text_color = c.get("text", "#e0e0e0")
        legend_layout = self._legend_widget.layout()
        for hex_c, name in [
            (c.get("chart_pomodoro", "#D55E00"), "Pomodoro"),
            (c.get("chart_stopwatch", "#0072B2"), "Stopwatch"),
            (c.get("highlight", "#0078d4"), "7-day avg"),
        ]:
            lbl = QLabel(
                f'<span style="color:{hex_c};">\u25a0</span> '
                f'<span style="color:{text_color};">{name}</span>'
            )
            lbl.setStyleSheet("font-size: 11px;")
            if legend_layout is not None:
                legend_layout.addWidget(lbl)
            self._legend_labels.append(lbl)
        if legend_layout is not None:
            legend_layout.addStretch()

    def _show_empty(self, message: str) -> None:
        import pyqtgraph as pg

        col_text = QColor(self._colors.get("completed_text", "#8c8c8c"))
        text = pg.TextItem(message, color=col_text, anchor=(0.5, 0.5))
        text.setPos(3.0, 5.0)
        self._plot.addItem(text)


# ---------------------------------------------------------------------------
# Timeline Productivity Chart — time block heatmap
# ---------------------------------------------------------------------------


class _TimelineProductivityWidget(QWidget):
    """Time block heatmap: 12 two-hour blocks with split pomodoro/stopwatch bars.

    All 12x2 bars + 12 labels persistent — created in rebuild(),
    updated in-place via setOpts()/setText()/setPos() during real-time.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import pyqtgraph as pg

        self._analytics = None
        self._active_elapsed: int = 0
        self._active_session_type: str = ""

        # Persistent item references (12 of each)
        self._block_pom_bars: list = []
        self._block_sw_bars: list = []
        self._block_labels: list = []
        self._base_blocks = None

        self._create_styles()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=True, y=False)
        self._plot.showGrid(x=True, y=False, alpha=0.2)
        self._plot.setMenuEnabled(False)
        layout.addWidget(self._plot)

        self._legend_widget = QWidget()
        self._legend_widget.setFixedHeight(28)
        legend_layout = QHBoxLayout(self._legend_widget)
        legend_layout.setContentsMargins(10, 4, 10, 4)
        legend_layout.setSpacing(16)
        self._legend_labels: list[QLabel] = []
        layout.addWidget(self._legend_widget)

    def _create_styles(self) -> None:
        from PyQt6.QtGui import QBrush, QGradient, QLinearGradient, QPen

        from ...gui.styles.themes import get_colors

        c = get_colors()
        self._colors = c

        # Pomodoro: horizontal gradient (left→right = dark→light)
        pom_base = QColor(c.get("chart_pomodoro", "#D55E00"))
        pom_grad = QLinearGradient(0, 0, 1, 0)
        pom_grad.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
        pom_grad.setColorAt(0.0, pom_base)
        pom_grad.setColorAt(1.0, pom_base.lighter(115))
        self._pom_pen = QPen(pom_base.darker(130), 1)

        # Stopwatch: horizontal gradient
        sw_base = QColor(c.get("chart_stopwatch", "#0072B2"))
        sw_grad = QLinearGradient(0, 0, 1, 0)
        sw_grad.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
        sw_grad.setColorAt(0.0, sw_base)
        sw_grad.setColorAt(1.0, sw_base.lighter(115))
        self._sw_pen = QPen(sw_base.darker(130), 1)

        # Pre-compute alpha-bucketed brushes (9 levels: alpha 80,100,...,255)
        self._pom_brushes: list[QBrush] = []
        self._sw_brushes: list[QBrush] = []
        for alpha in range(80, 260, 20):
            alpha = min(alpha, 255)
            pg = QLinearGradient(0, 0, 1, 0)
            pg.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
            pc = QColor(pom_base)
            pc.setAlpha(alpha)
            pl = QColor(pom_base.lighter(115))
            pl.setAlpha(alpha)
            pg.setColorAt(0.0, pc)
            pg.setColorAt(1.0, pl)
            self._pom_brushes.append(QBrush(pg))

            sg = QLinearGradient(0, 0, 1, 0)
            sg.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
            sc = QColor(sw_base)
            sc.setAlpha(alpha)
            sl = QColor(sw_base.lighter(115))
            sl.setAlpha(alpha)
            sg.setColorAt(0.0, sc)
            sg.setColorAt(1.0, sl)
            self._sw_brushes.append(QBrush(sg))

        self._col_text = QColor(c.get("text", "#e0e0e0"))
        self._col_border = QColor(c.get("border", "#3c3c3c"))

    def _alpha_brush_index(self, total_mins: float, max_minutes: float) -> int:
        """Get the index into pre-computed alpha-bucketed brushes."""
        if max_minutes <= 0 or total_mins <= 0:
            return 0
        alpha = int(80 + (175 * total_mins / max_minutes))
        return min((alpha - 80) // 20, len(self._pom_brushes) - 1)

    def set_analytics(self, analytics) -> None:
        self._analytics = analytics

    def set_active_session(self, elapsed: int = 0, session_type: str = "") -> None:
        self._active_elapsed = elapsed
        self._active_session_type = session_type
        self._update_realtime()

    def _update_realtime(self) -> None:
        """In-place update: setOpts on bars, setText/setPos on labels."""
        if not self._block_pom_bars or self._base_blocks is None:
            return
        from datetime import datetime as _dt

        current_block = (_dt.now().hour // 2) * 2
        n = len(self._base_blocks)

        # Compute max for scaling
        max_minutes = 0.1
        for _, row in self._base_blocks.iterrows():
            pom = float(row.get("pomodoro_minutes", 0))
            sw = float(row.get("stopwatch_minutes", 0))
            if self._active_elapsed > 0 and int(row["block_start_hour"]) == current_block:
                extra = self._active_elapsed / 60.0
                if self._active_session_type == "work":
                    pom += extra
                else:
                    sw += extra
            max_minutes = max(max_minutes, pom + sw)

        # Update all persistent items in-place
        for i, (_, row) in enumerate(self._base_blocks.iterrows()):
            y = float(n - 1 - i)
            pom_mins = float(row.get("pomodoro_minutes", 0))
            sw_mins = float(row.get("stopwatch_minutes", 0))
            block_hour = int(row["block_start_hour"])

            if self._active_elapsed > 0 and block_hour == current_block:
                extra_mins = self._active_elapsed / 60.0
                if self._active_session_type == "work":
                    pom_mins += extra_mins
                else:
                    sw_mins += extra_mins

            total_mins = pom_mins + sw_mins
            bi = self._alpha_brush_index(total_mins, max_minutes)

            self._block_pom_bars[i].setOpts(width=[pom_mins], brush=self._pom_brushes[bi])
            self._block_sw_bars[i].setOpts(
                x0=[pom_mins], width=[sw_mins], brush=self._sw_brushes[bi]
            )

            # Update label
            parts = []
            if pom_mins > 0:
                parts.append(f"{int(pom_mins)}m pom")
            if sw_mins > 0:
                parts.append(f"{int(sw_mins)}m sw")
            rate = float(row["completion_rate"])
            label_text = (
                f"{' + '.join(parts)} \u2014 {round(rate * 100)}% completed" if parts else ""
            )
            self._block_labels[i].setText(label_text)
            self._block_labels[i].setPos(total_mins + max_minutes * 0.02, y)

        self._plot.setXRange(0, max_minutes * 1.75, padding=0)

    def rebuild(self) -> None:
        import pyqtgraph as pg

        self._create_styles()
        plot = self._plot
        plot.clear()
        plot.setBackground(self._colors.get("base", "#252526"))
        self._block_pom_bars = []
        self._block_sw_bars = []
        self._block_labels = []
        self._base_blocks = None

        for lbl in self._legend_labels:
            lbl.deleteLater()
        self._legend_labels.clear()

        if self._analytics is None:
            self._show_empty("Analytics service not available")
            self._build_legend()
            return

        blocks = self._analytics.time_block_analysis()
        if blocks.empty or blocks["session_count"].sum() == 0:
            self._show_empty("Complete some focus sessions to see productivity patterns")
            self._build_legend()
            return

        self._base_blocks = blocks.copy()
        max_minutes = max(float(blocks["total_minutes"].max()), 0.1)
        n = len(blocks)
        y_ticks = []

        # Create persistent items for all 12 blocks
        for i, (_, row) in enumerate(blocks.iterrows()):
            y = float(n - 1 - i)
            label = str(row["block_label"])
            pom_mins = float(row.get("pomodoro_minutes", 0))
            sw_mins = float(row.get("stopwatch_minutes", 0))
            total_mins = pom_mins + sw_mins
            rate = float(row["completion_rate"])
            bi = self._alpha_brush_index(total_mins, max_minutes)
            y_ticks.append((y, label))

            # Pomodoro bar (persistent)
            pom_bar = pg.BarGraphItem(
                x0=[0],
                y0=[y - 0.35],
                width=[pom_mins],
                height=[0.7],
                brush=self._pom_brushes[bi],
                pen=self._pom_pen,
            )
            plot.addItem(pom_bar)
            self._block_pom_bars.append(pom_bar)

            # Stopwatch bar (persistent)
            sw_bar = pg.BarGraphItem(
                x0=[pom_mins],
                y0=[y - 0.35],
                width=[sw_mins],
                height=[0.7],
                brush=self._sw_brushes[bi],
                pen=self._sw_pen,
            )
            plot.addItem(sw_bar)
            self._block_sw_bars.append(sw_bar)

            # Label (persistent)
            parts = []
            if pom_mins > 0:
                parts.append(f"{int(pom_mins)}m pom")
            if sw_mins > 0:
                parts.append(f"{int(sw_mins)}m sw")
            label_text = (
                f"{' + '.join(parts)} \u2014 {round(rate * 100)}% completed" if parts else ""
            )
            text_item = pg.TextItem(label_text, color=self._col_text, anchor=(0, 0.5))
            text_item.setPos(total_mins + max_minutes * 0.02, y)
            plot.addItem(text_item)
            self._block_labels.append(text_item)

        # Axes
        left_axis = plot.getAxis("left")
        left_axis.setTicks([y_ticks])
        left_axis.setTextPen(self._col_text)
        left_axis.setPen(pg.mkPen(self._col_border))
        left_axis.setWidth(100)

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(self._col_text)
        bottom_axis.setPen(pg.mkPen(self._col_border))
        bottom_axis.setLabel("Minutes")

        plot.setXRange(0, max_minutes * 1.75, padding=0)
        plot.setYRange(-0.7, n - 0.3, padding=0.02)

        self._build_legend()

    def _build_legend(self) -> None:
        c = self._colors
        text_color = c.get("text", "#e0e0e0")
        legend_layout = self._legend_widget.layout()
        for hex_c, name in [
            (c.get("chart_pomodoro", "#D55E00"), "Pomodoro"),
            (c.get("chart_stopwatch", "#0072B2"), "Stopwatch"),
        ]:
            lbl = QLabel(
                f'<span style="color:{hex_c};">\u25a0</span> '
                f'<span style="color:{text_color};">{name}</span>'
            )
            lbl.setStyleSheet("font-size: 11px;")
            if legend_layout is not None:
                legend_layout.addWidget(lbl)
            self._legend_labels.append(lbl)
        note = QLabel(
            f'<span style="color:{c.get("completed_text", "#8c8c8c")};">'
            f"% = sessions finished without interruption</span>"
        )
        note.setStyleSheet("font-size: 10px;")
        if legend_layout is not None:
            legend_layout.addWidget(note)
        self._legend_labels.append(note)
        if legend_layout is not None:
            legend_layout.addStretch()

    def _show_empty(self, message: str) -> None:
        import pyqtgraph as pg

        col_text = QColor(self._colors.get("completed_text", "#8c8c8c"))
        text = pg.TextItem(message, color=col_text, anchor=(0.5, 0.5))
        text.setPos(5.0, 5.5)
        self._plot.addItem(text)


# ---------------------------------------------------------------------------
# Timeline Accuracy Chart — estimate vs actual scatter plot
# ---------------------------------------------------------------------------


class _TimelineAccuracyWidget(QWidget):
    """Scatter plot: estimated vs actual minutes per item.

    Persistent ScatterPlotItem + InfiniteLine. Real-time: active item's
    dot moves upward as actual_minutes grows during a session.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import pyqtgraph as pg

        self._analytics = None
        self._list_id: str | None = None
        self._active_item_id: UUID | None = None
        self._active_elapsed: int = 0

        # Persistent item references
        self._scatter: pg.ScatterPlotItem | None = None
        self._ref_line: pg.InfiniteLine | None = None
        self._base_estimated = None
        self._base_actual = None
        self._base_brushes = None

        self._create_styles()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setMenuEnabled(False)
        layout.addWidget(self._plot)

        self._legend_widget = QWidget()
        self._legend_widget.setFixedHeight(28)
        legend_layout = QHBoxLayout(self._legend_widget)
        legend_layout.setContentsMargins(10, 4, 10, 4)
        legend_layout.setSpacing(16)
        self._legend_labels: list[QLabel] = []
        layout.addWidget(self._legend_widget)

    def _create_styles(self) -> None:
        from PyQt6.QtGui import QPen

        from ...gui.styles.themes import get_colors

        c = get_colors()
        self._colors = c

        # Pre-create category brushes
        import pyqtgraph as pg

        self._brush_over = pg.mkBrush(QColor(c.get("chart_overdue", "#b12f25")))
        self._brush_under = pg.mkBrush(QColor(c.get("chart_stopwatch", "#0072B2")))
        self._brush_accurate = pg.mkBrush(QColor(c.get("chart_span", "#4a90d2")))
        self._scatter_pen = pg.mkPen("w", width=0.5)
        self._col_text = QColor(c.get("text", "#e0e0e0"))
        self._col_border = QColor(c.get("border", "#3c3c3c"))
        self._ref_pen = QPen(self._col_text, 1)
        self._ref_pen.setStyle(Qt.PenStyle.DashLine)

    def set_analytics(self, analytics) -> None:
        self._analytics = analytics

    def set_list_id(self, list_id: str | None) -> None:
        self._list_id = list_id

    def set_active_session(
        self, item_id: UUID | None = None, elapsed: int = 0, session_type: str = ""
    ) -> None:
        self._active_item_id = item_id
        self._active_elapsed = elapsed
        self._update_realtime()

    def _update_realtime(self) -> None:
        """In-place scatter update: active item's actual_minutes grows."""
        if self._scatter is None or self._base_actual is None:
            return

        actual = self._base_actual.copy()

        # Add elapsed to active item if it has an estimate
        if (
            self._active_item_id is not None
            and self._active_elapsed > 0
            and hasattr(self, "_item_ids")
        ):
            item_id_str = str(self._active_item_id)
            for i, iid in enumerate(self._item_ids):
                if iid == item_id_str:
                    actual[i] += self._active_elapsed / 60.0
                    break

        # Recompute brushes based on new ratios
        brushes = []
        for i in range(len(self._base_estimated)):
            est = float(self._base_estimated[i])
            act = float(actual[i])
            ratio = act / est if est > 0 else 0.0
            if ratio > 1.2:
                brushes.append(self._brush_over)
            elif ratio < 0.8:
                brushes.append(self._brush_under)
            else:
                brushes.append(self._brush_accurate)

        self._scatter.setData(
            x=self._base_estimated,
            y=actual,
            brush=brushes,
            pen=self._scatter_pen,
        )

    def rebuild(self) -> None:
        import pyqtgraph as pg

        self._create_styles()
        plot = self._plot
        plot.clear()
        plot.setBackground(self._colors.get("base", "#252526"))

        self._scatter = None
        self._ref_line = None
        self._base_estimated = None
        self._base_actual = None
        self._item_ids = []

        for lbl in self._legend_labels:
            lbl.deleteLater()
        self._legend_labels.clear()

        # Legend (always visible)
        self._build_legend()

        # Axes (always set up)
        left_axis = plot.getAxis("left")
        left_axis.setTextPen(self._col_text)
        left_axis.setPen(pg.mkPen(self._col_border))
        left_axis.setLabel("Actual (min)")

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(self._col_text)
        bottom_axis.setPen(pg.mkPen(self._col_border))
        bottom_axis.setLabel("Estimated (min)")

        if self._analytics is None:
            self._show_empty("Analytics service not available")
            return

        accuracy = self._analytics.estimate_accuracy(list_id=self._list_id)
        if accuracy.empty:
            self._show_empty("Add estimates and complete sessions to track accuracy")
            return

        estimated = accuracy["estimated_minutes"].values.astype(float)
        actual = accuracy["actual_minutes"].values.astype(float)
        self._item_ids = list(accuracy["item_id"].values)
        self._base_estimated = estimated.copy()
        self._base_actual = actual.copy()

        # Compute brushes
        brushes = []
        for _, row in accuracy.iterrows():
            ratio = float(row["accuracy_ratio"])
            if ratio > 1.2:
                brushes.append(self._brush_over)
            elif ratio < 0.8:
                brushes.append(self._brush_under)
            else:
                brushes.append(self._brush_accurate)
        self._base_brushes = brushes

        # Persistent scatter
        self._scatter = pg.ScatterPlotItem(
            x=estimated,
            y=actual,
            size=12,
            brush=brushes,
            pen=self._scatter_pen,
        )
        plot.addItem(self._scatter)

        # Persistent reference line (y=x)
        self._ref_line = pg.InfiniteLine(
            pos=0,
            angle=45,
            pen=self._ref_pen,
        )
        plot.addItem(self._ref_line)

        max_val = max(float(estimated.max()), float(actual.max()), 10)
        plot.setXRange(0, max_val * 1.1, padding=0)
        plot.setYRange(0, max_val * 1.1, padding=0)

    def _build_legend(self) -> None:
        c = self._colors
        text_color = c.get("text", "#e0e0e0")
        legend_layout = self._legend_widget.layout()
        for hex_c, name in [
            (c.get("chart_overdue", "#b12f25"), "Under-estimated"),
            (c.get("chart_span", "#4a90d2"), "Accurate"),
            (c.get("chart_stopwatch", "#0072B2"), "Over-estimated"),
        ]:
            lbl = QLabel(
                f'<span style="color:{hex_c};">\u25cf</span> '
                f'<span style="color:{text_color};">{name}</span>'
            )
            lbl.setStyleSheet("font-size: 11px;")
            if legend_layout is not None:
                legend_layout.addWidget(lbl)
            self._legend_labels.append(lbl)
        if legend_layout is not None:
            legend_layout.addStretch()

    def _show_empty(self, message: str) -> None:
        import pyqtgraph as pg

        col_text = QColor(self._colors.get("completed_text", "#8c8c8c"))
        text = pg.TextItem(message, color=col_text, anchor=(0.5, 0.5))
        text.setPos(50.0, 50.0)
        self._plot.addItem(text)


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
            return _format_hour(row - 1)
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
        return _format_hour(section - 1)

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
        overflow_height = fm.height() + 2
        y = rect.top() + 2
        x = rect.left() + 2
        text_width = rect.width() - 8
        available = rect.height() - 4

        # Same logic as month view _calc_cell_layout:
        # if all fit, show all; if overflow, reserve space for "+N" text
        if len(items) * chip_height <= available:
            max_chips = len(items)
        else:
            max_chips = max(1, (available - overflow_height) // chip_height)

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

        # Overflow indicator
        overflow = len(items) - max_chips
        if overflow > 0:
            overflow_y = y + max_chips * chip_height
            overflow_rect = rect.adjusted(4, 0, -4, 0)
            overflow_rect.setTop(overflow_y)
            overflow_rect.setHeight(overflow_height)
            painter.setPen(QColor(c["completed_text"]))
            painter.drawText(
                overflow_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"+{overflow} more",
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
    task_dropped = pyqtSignal(object, object, object)  # (item_id, target_date, target_hour or None)
    more_clicked = pyqtSignal(object, object)  # (date, list[TodoItem])

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
        self.setAcceptDrops(True)
        self.setStyleSheet("QTableView { border: none; background: palette(window); }")
        self._drag_start_pos = None
        self._drag_item_id = None
        self._dragging = False

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
        overflow_height = fm.height() + 2
        available = rect.height() - 4

        # Same overflow calculation as delegate paint
        if len(items) * chip_height <= available:
            max_chips = len(items)
        else:
            max_chips = max(1, (available - overflow_height) // chip_height)

        click_y = pos.y() - rect.top() - 2
        item_idx = int(click_y / chip_height) if chip_height > 0 else -1

        # Check overflow area
        if len(items) > max_chips and item_idx >= max_chips:
            return ("more", cell_date, items)

        if 0 <= item_idx < min(max_chips, len(items)):
            return ("task", items[item_idx], index)
        return None

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        self._drag_start_pos = None
        self._drag_item_id = None
        self._dragging = False
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if not hit:
            return
        if hit[0] == "task":
            self.task_clicked.emit(hit[1].id)
            if a0.button() == Qt.MouseButton.LeftButton:
                self._drag_start_pos = a0.pos()
                self._drag_item_id = hit[1].id
        elif hit[0] == "more":
            self.more_clicked.emit(hit[1], hit[2])

    def mouseReleaseEvent(self, a0) -> None:  # noqa: N802
        self._drag_start_pos = None
        self._drag_item_id = None
        self._dragging = False
        super().mouseReleaseEvent(a0)

    def mouseMoveEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        # Drag initiation
        if (
            not self._dragging
            and self._drag_start_pos is not None
            and self._drag_item_id is not None
            and (a0.pos() - self._drag_start_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._dragging = True
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(
                "application/x-pytodo-item-id",
                str(self._drag_item_id).encode(),
            )
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
            self._drag_start_pos = None
            self._drag_item_id = None
            self._dragging = False
            return
        # Tooltip handling
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

    def dragEnterEvent(self, a0) -> None:  # noqa: N802
        if a0 and a0.mimeData() and a0.mimeData().hasFormat("application/x-pytodo-item-id"):
            a0.acceptProposedAction()

    def dragMoveEvent(self, a0) -> None:  # noqa: N802
        if a0 and a0.mimeData() and a0.mimeData().hasFormat("application/x-pytodo-item-id"):
            a0.acceptProposedAction()

    def dropEvent(self, a0) -> None:  # noqa: N802
        if a0 is None or a0.mimeData() is None:
            return
        mime = a0.mimeData()
        if not mime.hasFormat("application/x-pytodo-item-id"):
            return
        item_id_str = bytes(mime.data("application/x-pytodo-item-id")).decode()
        index = self.indexAt(a0.position().toPoint())
        if not index.isValid():
            return
        target_date = index.data(_WEEK_DATE_ROLE)
        target_hour = index.data(_WEEK_HOUR_ROLE)
        if target_date is None:
            return
        try:
            item_id = UUID(item_id_str)
        except ValueError:
            return
        # hour = -1 means all-day (no time), otherwise set due_time
        from datetime import time as _time

        target_time = _time(target_hour, 0) if target_hour >= 0 else None
        self.task_dropped.emit(item_id, target_date, target_time)
        a0.acceptProposedAction()


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


class _DraggableTaskButton(QPushButton):
    """A task button that supports drag-and-drop to schedule."""

    def __init__(self, item_id: UUID, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item_id = item_id
        self._drag_start = None

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self._drag_start = a0.pos()
        super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0) -> None:  # noqa: N802
        if (
            a0
            and self._drag_start
            and (a0.pos() - self._drag_start).manhattanLength() >= QApplication.startDragDistance()
        ):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(str(self._item_id))
            mime.setData("application/x-pytodo-item-id", str(self._item_id).encode())
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
            self._drag_start = None
        else:
            super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0) -> None:  # noqa: N802
        self._drag_start = None
        super().mouseReleaseEvent(a0)


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

            row = _DraggableTaskButton(item.id)
            row.setStyleSheet(
                f"QPushButton {{ border-left: 3px solid {c[p_key]}; border-radius: 3px;"
                f" padding: 3px 5px; background: {bg}; text-align: left; margin: 1px 0; }}"
                f" QPushButton:hover {{ background: {c['alternate_base']}; }}"
            )
            row.setCursor(Qt.CursorShape.OpenHandCursor)
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
    date_and_time_dropped = pyqtSignal(object, object, object)  # item_id, date, time
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
        # Load saved sub-view from config, default to week
        from ...core.config import get_config

        config = get_config()
        saved = config.database.calendar_sub_view
        sub_map = {
            "day": self.SUB_DAY,
            "week": self.SUB_WEEK,
            "month": self.SUB_MONTH,
            "timeline": self.SUB_TIMELINE,
        }
        self._sub_view = sub_map.get(saved, self.SUB_WEEK)

        # Load saved timeline sub-view
        tl_sub_map = {"tasks": 0, "daily": 1, "productivity": 2, "accuracy": 3}
        self._initial_tl_sub_view = tl_sub_map.get(config.database.timeline_sub_view, 0)

        self._setup_ui()

        # Apply initial visibility for timeline mode
        if self._sub_view == self.SUB_TIMELINE:
            self._unscheduled.setVisible(False)
            self._timeline_pill_frame.setVisible(True)
            self._update_timeline_nav_state()

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
        self._prev_btn = QToolButton()
        self._prev_btn.setText("\u25c0")
        self._prev_btn.setStyleSheet("border: none; font-size: 14px; padding: 4px;")
        self._prev_btn.clicked.connect(self._navigate_prev)
        top_layout.addWidget(self._prev_btn)

        self._nav_label = QLabel()
        self._nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._nav_label.setStyleSheet("font-size: 13px; font-weight: bold; min-width: 140px;")
        top_layout.addWidget(self._nav_label)

        self._next_btn = QToolButton()
        self._next_btn.setText("\u25b6")
        self._next_btn.setStyleSheet("border: none; font-size: 14px; padding: 4px;")
        self._next_btn.clicked.connect(self._navigate_next)
        top_layout.addWidget(self._next_btn)

        self._today_btn = QPushButton("Today")
        self._today_btn.setStyleSheet(
            "QPushButton { border: 1px solid palette(mid); border-radius: 3px;"
            " padding: 3px 10px; font-size: 11px; }"
        )
        self._today_btn.clicked.connect(self._navigate_today)
        top_layout.addWidget(self._today_btn)

        layout.addWidget(top_bar)

        # Secondary pill row for timeline sub-views (hidden unless Timeline selected)
        self._timeline_pill_frame = QFrame()
        self._timeline_pill_frame.setStyleSheet(
            "QFrame { background: palette(window); border: 1px solid palette(mid);"
            " border-radius: 4px; padding: 0; }"
        )
        tl_pill_layout = QHBoxLayout(self._timeline_pill_frame)
        tl_pill_layout.setContentsMargins(2, 2, 2, 2)
        tl_pill_layout.setSpacing(0)

        self._tl_sub_view = self._initial_tl_sub_view
        self._tl_sub_buttons: list[QPushButton] = []
        for i, label in enumerate(["Tasks", "Daily", "Productivity", "Accuracy"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(i == self._tl_sub_view)
            btn.setStyleSheet(
                "QPushButton { border: none; padding: 4px 10px; font-size: 10px;"
                " border-radius: 3px; }"
                " QPushButton:checked { background: palette(highlight); color: white;"
                " font-weight: bold; }"
            )
            btn.clicked.connect(lambda checked, idx=i: self._set_timeline_sub_view(idx))
            tl_pill_layout.addWidget(btn)
            self._tl_sub_buttons.append(btn)

        self._timeline_pill_frame.setVisible(self._sub_view == self.SUB_TIMELINE)
        layout.addWidget(self._timeline_pill_frame)

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
        self._day_table.task_dropped.connect(self._on_week_task_dropped)
        self._day_table.more_clicked.connect(self._on_more_clicked)
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
        self._week_table.task_dropped.connect(self._on_week_task_dropped)
        self._week_table.more_clicked.connect(self._on_more_clicked)
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
        self._cal_table.task_dropped.connect(self._on_task_dropped)
        month_layout.addWidget(self._cal_table, 1)

        self._sub_stack.addWidget(month_container)  # 2

        # Timeline container with sub-stack for multiple chart types
        self._timeline_container = QWidget()
        tl_container_layout = QVBoxLayout(self._timeline_container)
        tl_container_layout.setContentsMargins(0, 0, 0, 0)
        tl_container_layout.setSpacing(0)

        self._timeline_sub_stack = QStackedWidget()

        # [0] Tasks — existing Gantt chart
        self._timeline_tasks_widget = _TimelineTasksWidget()
        self._timeline_tasks_widget.task_clicked.connect(self._on_task_clicked)
        self._timeline_tasks_widget.task_right_clicked.connect(self._on_task_right_clicked)
        self._timeline_sub_stack.addWidget(self._timeline_tasks_widget)  # 0

        # [1] Daily — stacked bar chart
        self._timeline_daily_widget = _TimelineDailyWidget()
        self._timeline_sub_stack.addWidget(self._timeline_daily_widget)  # 1

        # [2] Productivity — time block heatmap
        self._timeline_productivity_widget = _TimelineProductivityWidget()
        self._timeline_sub_stack.addWidget(self._timeline_productivity_widget)  # 2

        # [3] Accuracy — estimate scatter plot
        self._timeline_accuracy_widget = _TimelineAccuracyWidget()
        self._timeline_sub_stack.addWidget(self._timeline_accuracy_widget)  # 3

        tl_container_layout.addWidget(self._timeline_sub_stack)
        self._timeline_sub_stack.setCurrentIndex(self._tl_sub_view)
        self._sub_stack.addWidget(self._timeline_container)  # 3

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

    def set_analytics(self, analytics) -> None:
        """Set the AnalyticsService for timeline chart sub-views."""
        self._analytics = analytics
        self._timeline_daily_widget.set_analytics(analytics)
        self._timeline_productivity_widget.set_analytics(analytics)
        self._timeline_accuracy_widget.set_analytics(analytics)

    def set_active_session(
        self, item_id: UUID | None, elapsed: int = 0, session_type: str = ""
    ) -> None:
        """Pass active focus session to all timeline sub-views for pseudo-real-time updates."""
        self._timeline_tasks_widget.set_active_session(item_id, elapsed, session_type)
        # Only update the visible sub-view to avoid unnecessary rebuilds
        if self._sub_view == self.SUB_TIMELINE:
            if self._tl_sub_view == 1:  # Daily
                self._timeline_daily_widget.set_active_session(elapsed, session_type)
            elif self._tl_sub_view == 2:  # Productivity
                self._timeline_productivity_widget.set_active_session(elapsed, session_type)
            elif self._tl_sub_view == 3:  # Accuracy
                self._timeline_accuracy_widget.set_active_session(item_id, elapsed, session_type)

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
        self._timeline_tasks_widget.set_data(all_items, self._current_date, self._todo_list)

        # Refresh active timeline sub-view (Daily/Productivity/Accuracy)
        if self._sub_view == self.SUB_TIMELINE and self._tl_sub_view > 0:
            self._refresh_timeline_sub_view()

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

    def _set_timeline_sub_view(self, idx: int) -> None:
        """Switch between timeline chart sub-views (Tasks/Daily/Productivity/Accuracy)."""
        self._tl_sub_view = idx
        self._timeline_sub_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tl_sub_buttons):
            btn.setChecked(i == idx)
        self._update_timeline_nav_state()
        self._update_nav_label()
        self._refresh_timeline_sub_view()

        # Persist timeline sub-view choice
        from ...core.config import get_config, get_config_manager

        tl_name_map = {0: "tasks", 1: "daily", 2: "productivity", 3: "accuracy"}
        get_config().database.timeline_sub_view = tl_name_map.get(idx, "tasks")
        get_config_manager().save()

    def _update_timeline_nav_state(self) -> None:
        """Enable/disable navigation buttons based on active timeline sub-view."""
        # Tasks and Daily support navigation; Productivity and Accuracy don't
        nav_enabled = self._tl_sub_view <= 1  # 0=Tasks, 1=Daily
        self._prev_btn.setEnabled(nav_enabled)
        self._next_btn.setEnabled(nav_enabled)
        self._today_btn.setEnabled(nav_enabled)

    def _refresh_timeline_sub_view(self) -> None:
        """Refresh the active timeline sub-view chart."""
        if self._tl_sub_view == 1:  # Daily
            self._timeline_daily_widget.set_current_date(self._current_date)
        elif self._tl_sub_view == 2:  # Productivity
            self._timeline_productivity_widget.rebuild()
        elif self._tl_sub_view == 3:  # Accuracy
            list_id = str(self._todo_list.id) if self._todo_list else None
            self._timeline_accuracy_widget.set_list_id(list_id)
            self._timeline_accuracy_widget.rebuild()

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
        elif self._sub_view == self.SUB_TIMELINE and self._tl_sub_view == 1:
            # Daily: shift by week
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
        elif self._sub_view == self.SUB_TIMELINE and self._tl_sub_view == 1:
            # Daily: shift by week
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
        elif self._sub_view == self.SUB_TIMELINE:
            if self._tl_sub_view == 1:  # Daily
                start = d - timedelta(days=d.weekday())
                end = start + timedelta(days=6)
                self._nav_label.setText(
                    f"{start.strftime('%b %d')} \u2014 {end.strftime('%b %d, %Y')}"
                )
            elif self._tl_sub_view == 2:  # Productivity
                self._nav_label.setText("Productivity \u2014 All Time")
            elif self._tl_sub_view == 3:  # Accuracy
                self._nav_label.setText("Accuracy \u2014 All Time")
            else:  # Tasks
                self._nav_label.setText(f"Timeline \u2014 {d.strftime('%B %Y')}")

    # --- Sub-view switching ---

    def _set_sub_view(self, idx: int) -> None:
        self._sub_view = idx
        self._sub_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._sub_buttons):
            btn.setChecked(i == idx)

        # Show/hide timeline secondary pills and unscheduled panel
        is_timeline = idx == self.SUB_TIMELINE
        self._timeline_pill_frame.setVisible(is_timeline)
        self._unscheduled.setVisible(not is_timeline)

        # Nav button state for timeline sub-views
        if is_timeline:
            self._update_timeline_nav_state()

        self._update_nav_label()
        self.refresh()

        # Persist sub-view choice
        from ...core.config import get_config, get_config_manager

        name_map = {
            self.SUB_DAY: "day",
            self.SUB_WEEK: "week",
            self.SUB_MONTH: "month",
            self.SUB_TIMELINE: "timeline",
        }
        get_config().database.calendar_sub_view = name_map.get(idx, "week")
        get_config_manager().save()

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
        self._timeline_tasks_widget.set_selected(item_id)
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

        # Position near the mouse, clamped to screen bounds
        from PyQt6.QtGui import QCursor

        popover.adjustSize()
        pos = QCursor.pos()
        target_x = pos.x() - 125
        target_y = pos.y() + 10

        screen = self.screen()
        if screen:
            screen_rect = screen.availableGeometry()
            pw = popover.width()
            ph = popover.height()
            if target_x + pw > screen_rect.right():
                target_x = screen_rect.right() - pw
            if target_x < screen_rect.left():
                target_x = screen_rect.left()
            if target_y + ph > screen_rect.bottom():
                target_y = pos.y() - ph - 10  # flip above cursor
            if target_y < screen_rect.top():
                target_y = screen_rect.top()

        popover.move(target_x, target_y)
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

    def _on_task_dropped(self, item_id: UUID, target_date: date) -> None:
        """Handle a task being dropped onto a month calendar date."""
        self.item_due_date_changed.emit(item_id, target_date)

    def _on_week_task_dropped(self, item_id: UUID, target_date: date, target_time) -> None:
        """Handle a task dropped on week/day view — set date and optionally time.

        Emits date_and_time_dropped signal when both date and time are set,
        so MainWindow can group them as a single undo macro.
        """
        if target_time is not None:
            self.date_and_time_dropped.emit(item_id, target_date, target_time)
        else:
            self.item_due_date_changed.emit(item_id, target_date)

    def _close_popover(self) -> None:
        """Close the day popover."""
        if hasattr(self, "_popover") and self._popover is not None:
            self._popover.close()
            self._popover = None
