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


class _TimelineTasksWidget(QWidget):
    """pyqtgraph-based horizontal timeline with task bars.

    3-lane layout per task:
    - Blue: time span (creation -> due date)
    - Gray: estimated effort (baseline bar)
    - Split red+cyan: actual work (pomodoro + stopwatch segments)

    Uses pyqtgraph for professional rendering with anti-aliasing,
    hover tooltips, zoom/pan, and real-time updates.
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
        self._colors: dict[str, str] = {}
        self._todo_list = None
        self._active_item_id: UUID | None = None
        self._active_elapsed: int = 0
        self._active_session_type: str = ""

        self._refresh_colors()

        # Layout: plot + legend
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # pyqtgraph PlotWidget
        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=True, y=False)
        self._plot.showGrid(x=True, y=True, alpha=0.35)
        self._plot.setMenuEnabled(False)

        # Configure axes
        self._plot.getAxis("left").setWidth(160)
        self._plot.getAxis("bottom").setHeight(30)
        self._plot.setLabel("bottom", "")

        # Click handling
        self._plot.scene().sigMouseClicked.connect(self._on_plot_clicked)

        # Hover tooltip via proxy
        import pyqtgraph as pg

        self._hover_proxy = pg.SignalProxy(
            self._plot.scene().sigMouseMoved, rateLimit=30, slot=self._on_mouse_moved
        )
        self._last_hover_row = -1

        # Persistent tooltip label (stays until mouse moves to different row)
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

        # Legend bar at bottom (always visible)
        self._legend_widget = QWidget()
        self._legend_widget.setFixedHeight(28)
        legend_layout = QHBoxLayout(self._legend_widget)
        legend_layout.setContentsMargins(160, 4, 10, 4)
        legend_layout.setSpacing(16)
        self._legend_labels: list[QLabel] = []
        layout.addWidget(self._legend_widget)

    def _refresh_colors(self) -> None:
        from ...gui.styles.themes import get_colors

        self._colors = get_colors()

    def _build_legend(self) -> None:
        """Build the legend bar with color swatches."""
        for lbl in self._legend_labels:
            lbl.deleteLater()
        self._legend_labels.clear()

        c = self._colors
        entries = [
            (c.get("chart_span", "#4a90d2"), "Time Span"),
            (c.get("chart_estimate", "#D4E9F3"), "Estimated"),
            (c.get("chart_pomodoro", "#D55E00"), "Pomodoro"),
            (c.get("chart_stopwatch", "#0072B2"), "Stopwatch"),
            (c.get("chart_overdue", "#b12f25"), "Overdue"),
        ]
        text_color = c.get("text", "#e0e0e0")
        legend_layout = self._legend_widget.layout()
        for hex_color, name in entries:
            lbl = QLabel(
                f'<span style="color:{hex_color};">\u25a0</span> '
                f'<span style="color:{text_color};">{name}</span>'
            )
            lbl.setStyleSheet("font-size: 11px;")
            if legend_layout is not None:
                legend_layout.addWidget(lbl)
            self._legend_labels.append(lbl)
        if legend_layout is not None:
            legend_layout.addStretch()

    def set_data(self, items: list, current_date: date, todo_list=None) -> None:
        from ...core.config import ConfigManager

        self._items = [i for i in items if i.parent_id is None]

        # Apply 3-tier sort (same as list/board views) with reminder tiebreaker
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
        """Set the active focus session for pseudo-real-time bar projection."""
        self._active_item_id = item_id
        self._active_elapsed = elapsed
        self._active_session_type = session_type
        self._rebuild_plot()

    def set_selected(self, item_id: UUID | None) -> None:
        self._selected_item_id = item_id

    def _date_to_days(self, d: date) -> float:
        """Convert a date to days offset from range_start."""
        return float((d - self._range_start).days)

    def _ms_to_date(self, ms: int) -> date:
        from datetime import datetime as _dt

        return _dt.fromtimestamp(ms / 1000).date()

    def _rebuild_plot(self) -> None:
        """Rebuild the pyqtgraph plot from current data."""
        import pyqtgraph as pg

        self._refresh_colors()
        c = self._colors

        plot = self._plot
        plot.clear()
        plot.setBackground(c.get("base", "#252526"))

        if not self._items:
            self._build_legend()
            return

        from ...core.config import get_config

        config_work_mins = get_config().pomodoro.work_duration
        today = date.today()
        n = len(self._items)

        # Colors
        col_span = QColor(c.get("chart_span", "#4a90d2"))
        col_span.setAlpha(int(c.get("chart_span_alpha", "100")))
        col_estimate = QColor(c.get("chart_estimate", "#D4E9F3"))
        col_est_border = QColor(c.get("chart_estimate_border", "#B0C4D8"))
        col_pomodoro = QColor(c.get("chart_pomodoro", "#D55E00"))
        col_pomodoro.setAlpha(int(c.get("chart_pomodoro_alpha", "200")))
        col_stopwatch = QColor(c.get("chart_stopwatch", "#0072B2"))
        col_stopwatch.setAlpha(int(c.get("chart_stopwatch_alpha", "200")))
        col_overdue = QColor(c.get("chart_overdue", "#b12f25"))
        col_overdue.setAlpha(int(c.get("chart_overdue_alpha", "80")))
        col_overflow = QColor(c.get("chart_overflow_actual", "#8B0000"))
        col_overflow.setAlpha(int(c.get("chart_overflow_actual_alpha", "100")))
        col_text = QColor(c.get("text", "#e0e0e0"))
        col_border = QColor(c.get("border", "#3c3c3c"))

        # Effort scaling: map minutes to x-axis (days).
        # 1 day width = 8 hours of effort (480 minutes).
        minutes_per_day = 480.0

        # Bar height constants (in y-axis units, 1.0 = full row)
        span_h = 0.06
        bar_h = 0.25
        # Vertical positions within each row (centered at y_base):
        #   span:    y_base + 0.30 to +0.36
        #   estimate: y_base + 0.00 to +0.25
        #   actual:  y_base - 0.30 to -0.05

        y_ticks = []

        for i, item in enumerate(self._items):
            y_base = float(n - 1 - i)  # Invert: first item at top
            label_text = item.reminder
            if len(label_text) > 28:
                label_text = label_text[:26] + "\u2026"
            if item.complete:
                label_text = "\u2713 " + label_text
            y_ticks.append((y_base, label_text))

            created_date = self._ms_to_date(item.created_at)
            end_date = (item.due_date + timedelta(days=1)) if item.due_date else today

            # --- Time span bar ---
            span_start = self._date_to_days(created_date)
            span_end = self._date_to_days(end_date)
            span_width = max(0.1, span_end - span_start)

            span_bar = pg.BarGraphItem(
                x0=[span_start],
                y0=[y_base + 0.30],
                width=[span_width],
                height=[span_h],
                brush=pg.mkBrush(col_span),
                pen=pg.mkPen(None),
            )
            plot.addItem(span_bar)

            # Overdue indicator
            if item.due_date and today > item.due_date and not item.complete:
                od_start = self._date_to_days(item.due_date + timedelta(days=1))
                od_end = self._date_to_days(today + timedelta(days=1))
                if od_end > od_start:
                    od_bar = pg.BarGraphItem(
                        x0=[od_start],
                        y0=[y_base + 0.30],
                        width=[od_end - od_start],
                        height=[span_h],
                        brush=pg.mkBrush(col_overdue),
                        pen=pg.mkPen(None),
                    )
                    plot.addItem(od_bar)

            # --- Estimate bar (gray baseline) ---
            est_minutes = 0.0
            if item.estimated_minutes > 0 and item.estimated_pomodoros > 0:
                est_minutes = item.estimated_minutes + (item.estimated_pomodoros * config_work_mins)
            elif item.estimated_minutes > 0:
                est_minutes = float(item.estimated_minutes)
            elif item.estimated_pomodoros > 0:
                est_minutes = float(item.estimated_pomodoros * config_work_mins)

            if est_minutes > 0:
                est_days = est_minutes / minutes_per_day
                est_bar = pg.BarGraphItem(
                    x0=[span_start],
                    y0=[y_base],
                    width=[est_days],
                    height=[bar_h],
                    brush=pg.mkBrush(col_estimate),
                    pen=pg.mkPen(col_est_border, width=1),
                )
                plot.addItem(est_bar)

            # --- Actual work bar (split: pomodoro + stopwatch) ---
            pomodoro_seconds = item.pomodoro_count * config_work_mins * 60
            total_time = item.time_spent

            # Pseudo-real-time projection
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

            if total_time > 0:
                pom_days = (pomodoro_seconds / 60.0) / minutes_per_day
                sw_days = (stopwatch_seconds / 60.0) / minutes_per_day
                actual_y0 = y_base - 0.30

                if pom_days > 0:
                    pom_bar = pg.BarGraphItem(
                        x0=[span_start],
                        y0=[actual_y0],
                        width=[pom_days],
                        height=[bar_h],
                        brush=pg.mkBrush(col_pomodoro),
                        pen=pg.mkPen(None),
                    )
                    plot.addItem(pom_bar)

                if sw_days > 0:
                    sw_bar = pg.BarGraphItem(
                        x0=[span_start + pom_days],
                        y0=[actual_y0],
                        width=[sw_days],
                        height=[bar_h],
                        brush=pg.mkBrush(col_stopwatch),
                        pen=pg.mkPen(None),
                    )
                    plot.addItem(sw_bar)

                # Overflow: actual exceeds estimate
                total_actual_days = pom_days + sw_days
                if est_minutes > 0:
                    est_days_val = est_minutes / minutes_per_day
                    if total_actual_days > est_days_val:
                        of_bar = pg.BarGraphItem(
                            x0=[span_start + est_days_val],
                            y0=[actual_y0],
                            width=[total_actual_days - est_days_val],
                            height=[bar_h],
                            brush=pg.mkBrush(col_overflow),
                            pen=pg.mkPen(None),
                        )
                        plot.addItem(of_bar)

        # --- Configure axes ---
        left_axis = plot.getAxis("left")
        left_axis.setTicks([y_ticks])
        left_axis.setTextPen(col_text)
        left_axis.setPen(pg.mkPen(col_border))

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(col_text)
        bottom_axis.setPen(pg.mkPen(col_border))

        # Date tick labels
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

        # Today line
        today_x = self._date_to_days(today)
        today_line = pg.InfiniteLine(
            pos=today_x,
            angle=90,
            pen=pg.mkPen(
                QColor(c.get("highlight", "#0078d4")),
                width=2,
                style=Qt.PenStyle.DashLine,
            ),
        )
        plot.addItem(today_line)

        # Set view range
        plot.setXRange(-0.5, total_days + 0.5, padding=0)
        plot.setYRange(-0.8, n - 0.2, padding=0.02)

        self._build_legend()

    def _row_from_y(self, y_val: float) -> int:
        """Convert a y-axis value to an item row index, or -1."""
        n = len(self._items)
        row_idx = n - 1 - round(y_val)
        if 0 <= row_idx < n:
            return row_idx
        return -1

    def _build_tooltip(self, item) -> str:
        """Build rich tooltip text for a task item."""
        from ...core.config import get_config

        config_work_mins = get_config().pomodoro.work_duration
        parts = [f"<b>{item.reminder}</b>"]

        if item.due_date:
            overdue = ""
            if date.today() > item.due_date and not item.complete:
                days_over = (date.today() - item.due_date).days
                overdue = f" <span style='color:#ff6e76;'>({days_over}d overdue)</span>"
            parts.append(f"Due: {item.due_date.strftime('%b %d, %Y')}{overdue}")
        if item.due_time:
            parts.append(f"Time: {item.due_time.strftime('%I:%M %p').lstrip('0')}")

        # Estimates
        est_parts = []
        if item.estimated_pomodoros > 0:
            est_parts.append(f"{item.estimated_pomodoros} sessions")
        if item.estimated_minutes > 0:
            est_parts.append(f"{item.estimated_minutes} min")
        if est_parts:
            parts.append(f"Estimated: {', '.join(est_parts)}")

        # Actual work
        if item.pomodoro_count > 0:
            pom_mins = item.pomodoro_count * config_work_mins
            parts.append(f"Pomodoro: {item.pomodoro_count} sessions ({pom_mins} min)")

        sw_seconds = max(0, item.time_spent - (item.pomodoro_count * config_work_mins * 60))
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
        """Handle mouse movement for persistent hover tooltips."""
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
                # Position tooltip to the right and slightly below cursor
                self._tooltip_label.move(cursor_pos.x() + 16, cursor_pos.y() + 8)
                self._tooltip_label.show()
            else:
                self._tooltip_label.hide()

    def _on_plot_clicked(self, event) -> None:
        """Handle click on the plot to find which item row was clicked."""
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
    """pyqtgraph stacked bar chart: sessions per day, pomodoro + stopwatch."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import pyqtgraph as pg

        self._analytics = None
        self._current_date: date = date.today()
        self._colors: dict[str, str] = {}
        self._refresh_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.showGrid(x=False, y=True, alpha=0.25)
        self._plot.setMenuEnabled(False)
        layout.addWidget(self._plot)

        # Legend
        self._legend_widget = QWidget()
        self._legend_widget.setFixedHeight(28)
        legend_layout = QHBoxLayout(self._legend_widget)
        legend_layout.setContentsMargins(10, 4, 10, 4)
        legend_layout.setSpacing(16)
        self._legend_labels: list[QLabel] = []
        layout.addWidget(self._legend_widget)

    def _refresh_colors(self) -> None:
        from ...gui.styles.themes import get_colors

        self._colors = get_colors()

    def set_analytics(self, analytics) -> None:
        self._analytics = analytics

    def set_current_date(self, d: date) -> None:
        self._current_date = d
        self.rebuild()

    def rebuild(self) -> None:
        import numpy as np
        import pyqtgraph as pg

        self._refresh_colors()
        c = self._colors
        plot = self._plot
        plot.clear()
        plot.setBackground(c.get("base", "#252526"))

        # Build legend
        for lbl in self._legend_labels:
            lbl.deleteLater()
        self._legend_labels.clear()
        text_color = c.get("text", "#e0e0e0")

        if self._analytics is None:
            self._show_empty("Analytics service not available")
            return

        # Week range
        week_start = self._current_date - timedelta(days=self._current_date.weekday())
        week_end = week_start + timedelta(days=6)
        start_str = week_start.isoformat()
        end_str = week_end.isoformat()

        summary = self._analytics.daily_summary(start_date=start_str, end_date=end_str)

        col_pom = QColor(c.get("chart_pomodoro", "#D55E00"))
        col_pom.setAlpha(200)
        col_sw = QColor(c.get("chart_stopwatch", "#0072B2"))
        col_sw.setAlpha(200)
        col_trend = QColor(c.get("highlight", "#0078d4"))
        col_text = QColor(text_color)
        col_border = QColor(c.get("border", "#3c3c3c"))

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

        # Pomodoro bars (bottom)
        if pom_mins.sum() > 0:
            pom_bars = pg.BarGraphItem(
                x=x_pos,
                width=0.6,
                height=pom_mins,
                y0=np.zeros(7),
                brush=pg.mkBrush(col_pom),
                pen=pg.mkPen(None),
            )
            plot.addItem(pom_bars)

        # Stopwatch bars (stacked on top)
        if sw_mins.sum() > 0:
            sw_bars = pg.BarGraphItem(
                x=x_pos,
                width=0.6,
                height=sw_mins,
                y0=pom_mins,
                brush=pg.mkBrush(col_sw),
                pen=pg.mkPen(None),
            )
            plot.addItem(sw_bars)

        # Trend line (7-day rolling average)
        rolling = self._analytics.rolling_averages(window_7=True, window_30=False)
        if not rolling.empty and len(rolling) >= 2:
            # Map rolling data to x positions where dates overlap
            import pandas as pd

            trend_x = []
            trend_y = []
            for _, row in rolling.iterrows():
                rd = row["date"]
                if isinstance(rd, pd.Timestamp):
                    rd = rd.date()
                idx = (rd - week_start).days if hasattr(rd, "__sub__") else -1
                if 0 <= idx < 7:
                    trend_x.append(float(idx))
                    trend_y.append(float(row.get("rolling_7d_minutes", 0)))
            if len(trend_x) >= 2:
                trend_line = pg.PlotDataItem(
                    trend_x,
                    trend_y,
                    pen=pg.mkPen(col_trend, width=2, style=Qt.PenStyle.DashLine),
                    symbol=None,
                )
                plot.addItem(trend_line)

        # Legend (always visible)
        self._build_legend(c, text_color)

        # Axes (always set up for visual consistency)
        left_axis = plot.getAxis("left")
        left_axis.setTextPen(col_text)
        left_axis.setPen(pg.mkPen(col_border))
        left_axis.setLabel("Minutes")

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTicks([[(float(i), day_labels[i]) for i in range(7)]])
        bottom_axis.setTextPen(col_text)
        bottom_axis.setPen(pg.mkPen(col_border))

        # Empty state check
        total = pom_mins.sum() + sw_mins.sum()
        if total == 0:
            self._show_empty("No sessions this week \u2014 use \u25c0 \u25b6 to navigate")
            plot.setXRange(-0.5, 6.5, padding=0)
            plot.setYRange(0, 10, padding=0)
            return

        max_y = max(float((pom_mins + sw_mins).max()), 1)
        plot.setXRange(-0.5, 6.5, padding=0)
        plot.setYRange(0, max_y * 1.15, padding=0)

    def _build_legend(self, c: dict, text_color: str) -> None:
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

        c = self._colors
        col_text = QColor(c.get("completed_text", "#8c8c8c"))
        text = pg.TextItem(message, color=col_text, anchor=(0.5, 0.5))
        text.setPos(3.0, 5.0)
        self._plot.addItem(text)


# ---------------------------------------------------------------------------
# Timeline Productivity Chart — time block heatmap
# ---------------------------------------------------------------------------


class _TimelineProductivityWidget(QWidget):
    """pyqtgraph horizontal bars: 12 two-hour blocks colored by activity intensity."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import pyqtgraph as pg

        self._analytics = None
        self._colors: dict[str, str] = {}
        self._refresh_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=False, y=False)
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

    def _refresh_colors(self) -> None:
        from ...gui.styles.themes import get_colors

        self._colors = get_colors()

    def set_analytics(self, analytics) -> None:
        self._analytics = analytics

    def rebuild(self) -> None:
        import pyqtgraph as pg

        self._refresh_colors()
        c = self._colors
        plot = self._plot
        plot.clear()
        plot.setBackground(c.get("base", "#252526"))

        for lbl in self._legend_labels:
            lbl.deleteLater()
        self._legend_labels.clear()
        text_color = c.get("text", "#e0e0e0")

        if self._analytics is None:
            self._show_empty("Analytics service not available")
            return

        blocks = self._analytics.time_block_analysis()
        if blocks.empty or blocks["session_count"].sum() == 0:
            self._show_empty("Complete some focus sessions to see productivity patterns")
            return

        max_minutes = max(float(blocks["total_minutes"].max()), 0.1)
        col_pom = QColor(c.get("chart_pomodoro", "#D55E00"))
        col_pom.setAlpha(200)
        col_sw = QColor(c.get("chart_stopwatch", "#0072B2"))
        col_sw.setAlpha(200)
        col_text = QColor(text_color)
        col_border = QColor(c.get("border", "#3c3c3c"))

        n = len(blocks)
        y_ticks = []

        for i, (_, row) in enumerate(blocks.iterrows()):
            y = float(n - 1 - i)
            label = str(row["block_label"])
            pom_mins = float(row.get("pomodoro_minutes", 0))
            sw_mins = float(row.get("stopwatch_minutes", 0))
            total_mins = pom_mins + sw_mins
            count = int(row["session_count"])
            rate = float(row["completion_rate"])
            y_ticks.append((y, label))

            if total_mins > 0:
                # Pomodoro segment (left)
                if pom_mins > 0:
                    pom_alpha = int(80 + (175 * total_mins / max_minutes))
                    pom_color = QColor(col_pom)
                    pom_color.setAlpha(pom_alpha)
                    pom_bar = pg.BarGraphItem(
                        x0=[0],
                        y0=[y - 0.35],
                        width=[pom_mins],
                        height=[0.7],
                        brush=pg.mkBrush(pom_color),
                        pen=pg.mkPen(None),
                    )
                    plot.addItem(pom_bar)

                # Stopwatch segment (stacked right of pomodoro)
                if sw_mins > 0:
                    sw_alpha = int(80 + (175 * total_mins / max_minutes))
                    sw_color = QColor(col_sw)
                    sw_color.setAlpha(sw_alpha)
                    sw_bar = pg.BarGraphItem(
                        x0=[pom_mins],
                        y0=[y - 0.35],
                        width=[sw_mins],
                        height=[0.7],
                        brush=pg.mkBrush(sw_color),
                        pen=pg.mkPen(None),
                    )
                    plot.addItem(sw_bar)

                # Label: minutes + completion rate
                mins_display = (
                    f"{int(total_mins)}m"
                    if total_mins < 60
                    else f"{int(total_mins // 60)}h {int(total_mins % 60)}m"
                )
                rate_text = pg.TextItem(
                    f"{mins_display} ({count} sessions, {round(rate * 100)}%)",
                    color=col_text,
                    anchor=(0, 0.5),
                )
                rate_text.setPos(total_mins + max_minutes * 0.02, y)
                plot.addItem(rate_text)

        # Axes
        left_axis = plot.getAxis("left")
        left_axis.setTicks([y_ticks])
        left_axis.setTextPen(col_text)
        left_axis.setPen(pg.mkPen(col_border))
        left_axis.setWidth(100)

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(col_text)
        bottom_axis.setPen(pg.mkPen(col_border))
        bottom_axis.setLabel("Minutes")

        plot.setXRange(0, max_minutes * 1.5, padding=0)
        plot.setYRange(-0.5, n - 0.5, padding=0.05)

        # Legend
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
        if legend_layout is not None:
            legend_layout.addStretch()

    def _show_empty(self, message: str) -> None:
        import pyqtgraph as pg

        c = self._colors
        col_text = QColor(c.get("completed_text", "#8c8c8c"))
        text = pg.TextItem(message, color=col_text, anchor=(0.5, 0.5))
        text.setPos(5.0, 5.5)
        self._plot.addItem(text)


# ---------------------------------------------------------------------------
# Timeline Accuracy Chart — estimate vs actual scatter plot
# ---------------------------------------------------------------------------


class _TimelineAccuracyWidget(QWidget):
    """pyqtgraph scatter plot: estimated vs actual minutes per item."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        import pyqtgraph as pg

        self._analytics = None
        self._list_id: str | None = None
        self._colors: dict[str, str] = {}
        self._refresh_colors()

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

    def _refresh_colors(self) -> None:
        from ...gui.styles.themes import get_colors

        self._colors = get_colors()

    def set_analytics(self, analytics) -> None:
        self._analytics = analytics

    def set_list_id(self, list_id: str | None) -> None:
        self._list_id = list_id

    def rebuild(self) -> None:
        import pyqtgraph as pg

        self._refresh_colors()
        c = self._colors
        plot = self._plot
        plot.clear()
        plot.setBackground(c.get("base", "#252526"))

        for lbl in self._legend_labels:
            lbl.deleteLater()
        self._legend_labels.clear()
        text_color = c.get("text", "#e0e0e0")

        col_text = QColor(text_color)
        col_border = QColor(c.get("border", "#3c3c3c"))

        # Legend (always visible)
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

        # Axes (always set up)
        left_axis = plot.getAxis("left")
        left_axis.setTextPen(col_text)
        left_axis.setPen(pg.mkPen(col_border))
        left_axis.setLabel("Actual (min)")

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(col_text)
        bottom_axis.setPen(pg.mkPen(col_border))
        bottom_axis.setLabel("Estimated (min)")

        if self._analytics is None:
            self._show_empty("Analytics service not available")
            return

        accuracy = self._analytics.estimate_accuracy(list_id=self._list_id)
        if accuracy.empty:
            self._show_empty("Add estimates and complete sessions to track accuracy")
            return

        col_over = QColor(c.get("chart_overdue", "#b12f25"))  # Under-estimated
        col_under = QColor(c.get("chart_stopwatch", "#0072B2"))  # Over-estimated
        col_accurate = QColor(c.get("chart_span", "#4a90d2"))  # Close to estimate

        estimated = accuracy["estimated_minutes"].values.astype(float)
        actual = accuracy["actual_minutes"].values.astype(float)

        # Color by variance
        brushes = []
        for _, row in accuracy.iterrows():
            ratio = float(row["accuracy_ratio"])
            if ratio > 1.2:
                brushes.append(pg.mkBrush(col_over))
            elif ratio < 0.8:
                brushes.append(pg.mkBrush(col_under))
            else:
                brushes.append(pg.mkBrush(col_accurate))

        scatter = pg.ScatterPlotItem(
            x=estimated,
            y=actual,
            size=12,
            brush=brushes,
            pen=pg.mkPen("w", width=0.5),
        )
        plot.addItem(scatter)

        # Reference line (y = x)
        max_val = max(float(estimated.max()), float(actual.max()), 10)
        ref_line = pg.InfiniteLine(
            pos=0,
            angle=45,
            pen=pg.mkPen(col_text, width=1, style=Qt.PenStyle.DashLine),
        )
        plot.addItem(ref_line)

        plot.setXRange(0, max_val * 1.1, padding=0)
        plot.setYRange(0, max_val * 1.1, padding=0)

    def _show_empty(self, message: str) -> None:
        import pyqtgraph as pg

        c = self._colors
        col_text = QColor(c.get("completed_text", "#8c8c8c"))
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
    task_dropped = pyqtSignal(object, object, object)  # (item_id, target_date, target_hour or None)

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
        click_y = pos.y() - rect.top() - 2
        item_idx = int(click_y / chip_height) if chip_height > 0 else -1

        if 0 <= item_idx < len(items):
            return ("task", items[item_idx], index)
        return None

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        self._drag_start_pos = None
        self._drag_item_id = None
        self._dragging = False
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit and hit[0] == "task":
            self.task_clicked.emit(hit[1].id)
            if a0.button() == Qt.MouseButton.LeftButton:
                self._drag_start_pos = a0.pos()
                self._drag_item_id = hit[1].id

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

        saved = get_config().database.calendar_sub_view
        sub_map = {
            "day": self.SUB_DAY,
            "week": self.SUB_WEEK,
            "month": self.SUB_MONTH,
            "timeline": self.SUB_TIMELINE,
        }
        self._sub_view = sub_map.get(saved, self.SUB_WEEK)

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

        self._tl_sub_view = 0  # Default: Tasks
        self._tl_sub_buttons: list[QPushButton] = []
        for i, label in enumerate(["Tasks", "Daily", "Productivity", "Accuracy"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
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
        """Pass active focus session to timeline for pseudo-real-time bar updates."""
        self._timeline_tasks_widget.set_active_session(item_id, elapsed, session_type)

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

    def _on_task_dropped(self, item_id: UUID, target_date: date) -> None:
        """Handle a task being dropped onto a month calendar date."""
        self.item_due_date_changed.emit(item_id, target_date)

    def _on_week_task_dropped(self, item_id: UUID, target_date: date, target_time) -> None:
        """Handle a task dropped on week/day view — set date and optionally time."""
        self.item_due_date_changed.emit(item_id, target_date)
        if target_time is not None:
            self.item_due_time_changed.emit(item_id, target_time)

    def _close_popover(self) -> None:
        """Close the day popover."""
        if hasattr(self, "_popover") and self._popover is not None:
            self._popover.close()
            self._popover = None
