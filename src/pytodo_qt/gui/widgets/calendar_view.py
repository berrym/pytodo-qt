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
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import pyqtgraph as pg
from PyQt6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QMimeData,
    QModelIndex,
    QPoint,
    QRect,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QDrag, QFont, QFontMetrics, QPainter, QPen, QPixmap
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
    from ...core.models import TodoItem, TodoList
    from ..widgets.search_filter import FilterState

# Enable anti-aliasing for all pyqtgraph chart rendering
pg.setConfigOptions(antialias=True)


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


def bar_state_label(state) -> str:
    """Map a BarState to the user-visible label used by the legend.

    Shared across the legend widget, calendar bar tooltips, and the task
    detail panel so that one enum value produces one identical string in
    every surface. This is the WCAG 1.4.1 redundancy channel — the color
    swatch is reinforced by an identical name wherever state is shown.
    """
    from ...core.calendar_layout import BarState

    _tr = QCoreApplication.translate
    # Keep the string literals in sync with the legend row in
    # _LegendWidget.refresh() — the translator context is shared.
    labels = {
        BarState.FUTURE: _tr("BarStateLabels", "Future"),
        BarState.IN_WORK_WINDOW: _tr("BarStateLabels", "In progress"),
        BarState.DUE_NOW: _tr("BarStateLabels", "Due soon"),
        BarState.OVERDUE_ACTIVE: _tr("BarStateLabels", "Overdue"),
        BarState.COMPLETED_EARLY: _tr("BarStateLabels", "Completed (early)"),
        BarState.COMPLETED_ONTIME: _tr("BarStateLabels", "Completed"),
        BarState.COMPLETED_LATE: _tr("BarStateLabels", "Completed (late)"),
        BarState.COMPLETED_UNKNOWN: _tr("BarStateLabels", "Completed (unknown)"),
    }
    return labels.get(state, _tr("BarStateLabels", "Unknown"))


class _CellBarLayout:
    """Result of laying out the bars within a single hour cell.

    Bars that begin in this cell ("starting") and bars that span into
    this cell from a previous one ("continuing") are each equally real
    in the current moment — a 30-minute focus block and a 2-hour task
    both deserve the same horizontal claim on any cell they occupy. The
    layout splits the cell width evenly across every bar present,
    regardless of where each one began.

    The continuing/starting distinction is preserved on this object
    because downstream code (painting, hit-testing) needs to know which
    edges of a bar are clipped by a cell boundary, but the two lists
    are sized from the same pool and follow the same slot-width rules.

    Each slot tuple is (item, window, seg, slot_left, slot_right_edge).

    `overflow_items` holds the real TodoItems (or _ProjectedItem proxies)
    that didn't fit into the visible slot cap. The painter draws a "+N"
    badge for them; the hit-test routes badge clicks to the day-popover
    handler so the user can still reach them.
    """

    __slots__ = ("continuing", "starting", "overflow_items")

    def __init__(
        self,
        continuing: list[tuple],
        starting: list[tuple],
        overflow_items: list,
    ) -> None:
        self.continuing = continuing
        self.starting = starting
        self.overflow_items = overflow_items

    @property
    def overflow(self) -> int:
        return len(self.overflow_items)


def _compute_cell_bar_layout(
    column_items: list,
    cell_date,
    cell_minute_start: int,
    cell_minute_end: int,
    bar_left: int,
    bar_width: int,
    current_time,
) -> _CellBarLayout:
    """Compute the bar layout for a single hour cell.

    Walks the column items, builds the intersecting list with id-dedup,
    and assigns equal-width slots to every bar present in the cell
    regardless of whether it starts here or was already running. The
    painter and the hit-test BOTH call this function so they always
    agree on which item is at which x position.

    The total bars in the cell are capped at MAX_VISIBLE_SLOTS=3; any
    excess is collapsed into an overflow count. When the cap is hit,
    bars that begin in this cell are preferred over continuing bars,
    on the theory that a user who just glances at a dense cell is more
    likely to want to see what's newly scheduled there. Continuing
    bars that overflow remain reachable through the "+N" badge.
    """
    from ...core.calendar_layout import compute_bar_segments, compute_bar_window

    MAX_VISIBLE_SLOTS = 3

    intersecting: list[tuple] = []
    seen_ids: set = set()
    deduped = _dedup_by_id(column_items)
    for item in deduped:
        iid = getattr(item, "id", None)
        if iid is not None and iid in seen_ids:
            continue
        window = compute_bar_window(item)
        if window is None:
            continue
        segments = compute_bar_segments(item, window, cell_date, current_time)
        for seg in segments:
            if seg.is_all_day or seg.is_marker:
                continue
            if seg.end_minute <= cell_minute_start or seg.start_minute >= cell_minute_end:
                continue
            intersecting.append((item, window, seg))
            if iid is not None:
                seen_ids.add(iid)
            break  # one entry per item per cell

    if not intersecting:
        return _CellBarLayout([], [], [])

    # Split: continuing (started before this cell) vs starting (begins in this cell)
    continuing_raw = [t for t in intersecting if t[2].start_minute < cell_minute_start]
    starting_raw = [t for t in intersecting if t[2].start_minute >= cell_minute_start]

    continuing: list[tuple] = []
    starting: list[tuple] = []

    # Cap policy under MAX_VISIBLE_SLOTS: starting bars get preference,
    # continuing bars fill the remainder. This keeps newly-scheduled work
    # visible in dense cells; overflowed continuing bars are still reachable
    # via the "+N" badge.
    max_start = min(len(starting_raw), MAX_VISIBLE_SLOTS)
    cap_remaining = MAX_VISIBLE_SLOTS - max_start
    max_cont = min(len(continuing_raw), cap_remaining)

    visible_count = max_start + max_cont
    if visible_count == 0:
        return _CellBarLayout(continuing, starting, [])

    slot_w = max(1, bar_width // visible_count)
    slot_gap = 2 if visible_count > 1 else 0

    # Slot ordering: continuing bars on the left (they arrived in an earlier
    # cell, so they sit "upstream" of bars starting here), starting bars to
    # their right in source order. This produces a stable left-to-right
    # arrival sequence that matches the time dimension running down the
    # column.
    slot_idx = 0
    for i in range(max_cont):
        item, window, seg = continuing_raw[i]
        slot_left = bar_left + slot_idx * slot_w
        slot_right = slot_left + slot_w - slot_gap
        continuing.append((item, window, seg, slot_left, slot_right))
        slot_idx += 1

    for i in range(max_start):
        item, window, seg = starting_raw[i]
        slot_left = bar_left + slot_idx * slot_w
        slot_right = slot_left + slot_w - slot_gap
        starting.append((item, window, seg, slot_left, slot_right))
        slot_idx += 1

    overflow_items = [t[0] for t in continuing_raw[max_cont:]] + [
        t[0] for t in starting_raw[max_start:]
    ]
    return _CellBarLayout(continuing, starting, overflow_items)


# Minimum label width (pixels, *after* slot padding) at which a chip's
# elided reminder text is still readable. Below this, the painter skips
# the label entirely and the user must rely on hover tooltips / the +N
# popover. With the 10 px bold font this fits roughly 5–6 elided
# characters, the minimum that conveys any task identity. Tuned so:
#   - day-view cells (wide single-column) show labels even with 3 slots
#   - week-view cells (narrow seven-column) skip labels at 3 slots
#     rather than cramming 2-char gibberish, but still show labels at
#     1–2 slots
_MIN_LABEL_WIDTH = 40
# Minimum slice height (in pixels after insets) at which a bar is
# tall enough to render a label. Cells with slice height below this
# threshold either skip the label entirely or delegate labeling to
# the next cell that clears the threshold.
_MIN_LABEL_HEIGHT = 14
# Minimum vertical size of a hit-test zone, per WCAG 2.5.5 Target Size
# (Minimum). Applied independently of the visual bar height: a short
# bar rendered at the layout-layer minimum (~10 px) still gets a
# 24-pixel-tall click zone centered on its visual middle and clamped
# to the containing cell, so sub-threshold bars remain reliably
# clickable without inflating their visual appearance.
_MIN_HIT_HEIGHT = 24


def _dilate_hit_zone(
    seg_top_y: int,
    seg_bot_y: int,
    *,
    cell_top: int,
    cell_bottom: int,
    min_height: int = _MIN_HIT_HEIGHT,
) -> tuple[int, int]:
    """Return a (top_y, bottom_y) pair expanded to at least
    ``min_height`` pixels tall, centered on the segment's visual
    middle, clamped to ``[cell_top, cell_bottom]``.

    The visual extent is unchanged; only the hit zone grows. Called
    from the week/day view's hit-test to bring the click target of
    minimum-floored bars up to the accessibility standard.
    """
    seg_height = seg_bot_y - seg_top_y
    if seg_height >= min_height:
        return seg_top_y, seg_bot_y
    center_y = (seg_top_y + seg_bot_y) // 2
    half = min_height // 2
    top_y = max(cell_top, center_y - half)
    bot_y = min(cell_bottom, center_y + (min_height - half))
    return top_y, bot_y


def _slice_is_first_labelable(
    seg,
    cell_minute_start: int,
    cell_minute_width: int,
    row_height_px: int,
) -> bool:
    """Return True if this cell should paint the bar label, False if
    an earlier cell in the same segment already crosses the height
    threshold and will own the label.

    Rule: "the first cell whose slice is ≥ _MIN_LABEL_HEIGHT px
    labels; every later cell suppresses." Preserves the thin-start-
    sliver fallback (a 5-min 19:55-20:00 slice is below threshold
    so the 20:00 body cell takes over) while eliminating the bug
    where a 25-minute task crossing an hour boundary got labeled in
    both slices and read as two separate tasks.

    The helper computes per-slice pixel height using the same inset
    model as the painter:
        inset_top = 4 if slice starts in this cell (not continuing)
        inset_bot = 4 if segment ends in this cell (not continuing)
    For cells between the start and the end of the segment, both
    insets are 0.
    """
    if seg.start_minute >= cell_minute_start:
        # This cell IS the start cell — always the first labelable
        # cell (if it has enough height; the caller separately
        # checks its own height).
        return True
    # Walk earlier cells in the segment; if any has slice height
    # ≥ threshold, that cell owns the label and this one suppresses.
    earlier_hour = seg.start_minute // cell_minute_width
    this_hour = cell_minute_start // cell_minute_width
    while earlier_hour < this_hour:
        earlier_start = earlier_hour * cell_minute_width
        earlier_end = earlier_start + cell_minute_width
        earlier_vs = max(seg.start_minute, earlier_start)
        earlier_ve = min(seg.end_minute, earlier_end)
        earlier_raw = int((earlier_ve - earlier_vs) / cell_minute_width * row_height_px)
        earlier_itop = 4 if seg.start_minute >= earlier_start else 0
        earlier_ibot = 4 if seg.end_minute <= earlier_end else 0
        earlier_height = earlier_raw - earlier_itop - earlier_ibot
        if earlier_height >= _MIN_LABEL_HEIGHT:
            return False
        earlier_hour += 1
    return True


def _compute_overflow_badge_rect(rect, overflow_count: int) -> QRect | None:
    """Geometry of the "+N" overflow badge for an hour-grid cell.

    Both the painter and the hit-test call this so the rect drawn on
    screen is the rect that registers a click. Returns None when there
    is no overflow (caller should skip painting / hit-testing).

    The badge sits in the cell's top-right corner, sized to the
    rendered "+N" text in the same 9 px bold font the painter uses.
    """
    if overflow_count <= 0:
        return None
    badge_font = QFont()
    badge_font.setPixelSize(9)
    badge_font.setBold(True)
    fm = QFontMetrics(badge_font)
    badge_text = f"+{overflow_count}"
    text_width = fm.horizontalAdvance(badge_text) + 8
    text_height = fm.height() + 2
    badge_x = rect.right() - text_width - 4
    badge_y = rect.top() + 2
    return QRect(badge_x, badge_y, text_width, text_height)


def _dedup_by_id(items: list) -> list:
    """Return a copy of `items` with duplicate ids removed.

    Defensive measure to ensure the calendar never renders the same
    task twice in the same cell. The first occurrence wins; subsequent
    items with the same id are silently dropped. Items without an id
    attribute (shouldn't happen in practice) are kept.
    """
    seen: set = set()
    out: list = []
    for item in items:
        iid = getattr(item, "id", None)
        if iid is None:
            out.append(item)
            continue
        if iid in seen:
            continue
        seen.add(iid)
        out.append(item)
    return out


class _ProjectedItem:
    """Lightweight proxy presenting a recurring item's projected occurrence
    on a specific future date.

    Forwards every attribute access to the underlying item EXCEPT
    `due_date`, `complete`, and `completed_at`, which are overridden to
    describe the projected occurrence rather than the template.

    `due_date` returns the projected date so compute_bar_window computes a
    fresh bar window for each occurrence on its actual scheduled date —
    daily standups appear as proper bars on every day, not as Q6 overdue
    markers from today's instance.

    `complete`/`completed_at` always return False/None because a projection
    represents a strictly future occurrence that has not happened yet.
    The underlying template's completion state refers to the most recently
    completed occurrence (before auto-advance runs on the next due date)
    and would otherwise propagate into every future day on the calendar —
    rendering them as COMPLETED_EARLY until tomorrow. Projection code
    only ever projects dates AFTER item.due_date, so a _ProjectedItem is
    never used for a past occurrence where the override would be wrong.

    Identity (`id`, `parent_id`, etc.) and all other state come from the
    real underlying item, so click handlers, edits, and completion
    affect the real (current-cycle) instance — clicking a projection
    is equivalent to clicking the real task.
    """

    __slots__ = ("_item", "_projected_date")

    def __init__(self, item, projected_date: date) -> None:
        # Use object.__setattr__ to bypass __getattr__ during construction
        object.__setattr__(self, "_item", item)
        object.__setattr__(self, "_projected_date", projected_date)

    @property
    def due_date(self) -> date:
        return self._projected_date

    @property
    def complete(self) -> bool:
        return False

    @property
    def completed_at(self) -> int | None:
        return None

    def __getattr__(self, name: str):
        # Called only when normal attribute lookup fails — forward to
        # the wrapped item. Note: `due_date`, `complete`, and `completed_at`
        # are overridden by properties above so they never reach this method.
        return getattr(self._item, name)

    def __repr__(self) -> str:
        return f"_ProjectedItem({self._item!r} on {self._projected_date})"


class _MarkerChip:
    """Wrapper around an item that should appear as a Q6 overdue marker
    in the All Day row of a viewing day after the item's due day.

    Q6 marker semantics: when a task's due date has passed, every
    subsequent day shows a fixed marker (not a growing bar) in the
    pinned All Day row carrying the elapsed-overdue duration label
    from `compute_bar_segments`. The label format is set in pure-layer
    `_make_marker` (e.g., "3d overdue", "~2w overdue").

    This wrapper carries the underlying item plus the marker_label and
    BarState produced by `compute_bar_segments` for a particular
    viewing day. The chip painter detects `_MarkerChip` via attribute
    sniff (`marker_label is not None`) and renders distinct
    OVERDUE_ACTIVE-colored chips with the duration label as the
    primary text instead of the task reminder.

    Forwards `.id` and all other attributes to the wrapped item so
    hit-test, click handlers, selection state, and edit dialogs
    transparently operate on the real underlying task — clicking a
    marker is equivalent to clicking the real task.
    """

    __slots__ = ("_item", "marker_label", "marker_state")

    def __init__(self, item, marker_label: str, marker_state) -> None:
        object.__setattr__(self, "_item", item)
        object.__setattr__(self, "marker_label", marker_label)
        object.__setattr__(self, "marker_state", marker_state)

    @property
    def id(self):
        return self._item.id

    def __getattr__(self, name: str):
        return getattr(self._item, name)

    def __repr__(self) -> str:
        return f"_MarkerChip({self._item!r} label={self.marker_label!r})"


def _collect_markers_for_dates(
    items: list,
    dates: list,
    current_time: datetime,
) -> dict:
    """Walk every (item, viewing_day) pair and collect Q6 marker chips.

    For each item with a `due_date`, asks `compute_bar_segments` what
    segments it would emit on each visible date. Marker segments
    (`is_marker=True`) become `_MarkerChip` entries keyed by viewing
    day so the All Day row of that day can render them.

    `current_time` is passed straight through so the markers reflect
    the same "as_of" semantics the pure layer uses — viewing today
    uses real now, viewing past/future uses end-of-that-day.

    **Q7 — recurring tasks are excluded.** Recurring tasks reset
    cleanly with no carryover (per Q7 in the design doc). The
    recurrence projection system (_project_recurrences_into +
    _ProjectedItem) handles their visibility on each cycle's actual
    due date. If we let recurring tasks generate markers here, every
    future viewing day would show a spurious "overdue" marker for
    yesterday's missed cycle ALONGSIDE the projected fresh bar,
    double-rendering the same task.

    Returns a dict mapping each date in `dates` to a list of
    `_MarkerChip` instances (empty list when no markers apply).
    De-dups by item id within each day so a single task can't
    accidentally produce multiple marker chips for the same day.
    """
    from ...core.calendar_layout import compute_bar_segments, compute_bar_window

    out: dict = {d: [] for d in dates}
    seen: dict = {d: set() for d in dates}
    for item in items:
        if getattr(item, "due_date", None) is None:
            continue
        # Q7: recurring tasks are excluded — see docstring above.
        if getattr(item, "is_recurring", False):
            continue
        window = compute_bar_window(item)
        if window is None:
            continue
        end_day = window.end.date()
        for d in dates:
            # Markers only apply on days strictly after the due day —
            # the due day itself shows the bar in the hour grid, not
            # a marker. Pre-filter so we don't waste a segment-compute
            # call on every (item, day) pair.
            if d <= end_day:
                continue
            segments = compute_bar_segments(item, window, d, current_time)
            for seg in segments:
                if not seg.is_marker:
                    continue
                if item.id in seen[d]:
                    continue
                out[d].append(_MarkerChip(item, seg.marker_label or "", seg.state))
                seen[d].add(item.id)
    return out


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

    def paint(
        self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        if painter is None:
            return
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
                QCoreApplication.translate("CalendarViewWidget", f"+{overflow} more"),
            )

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> Any:
        from PyQt6.QtCore import QSize

        return QSize(100, 90)


def _make_drag_pixmap(text: str) -> QPixmap:
    """Build a small accent-blue pill drag preview for a task.

    Used by every drag source in the calendar (month chip, week/day
    bar, unscheduled-panel button) so the cursor carries a visible
    preview of what's being moved instead of just a generic Qt
    "grabbing" hand.
    """
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QBrush, QFontMetrics, QPainter, QPen, QPixmap

    label = (text or "Task").strip() or "Task"
    if len(label) > 32:
        label = label[:30] + "\u2026"

    font = QFont()
    font.setPointSize(10)
    font.setBold(True)
    fm = QFontMetrics(font)

    pad_x, pad_y = 14, 7
    text_w = fm.horizontalAdvance(label)
    text_h = fm.height()

    pill_w = text_w + 2 * pad_x
    pill_h = text_h + 2 * pad_y

    # 4 px extra so the soft drop shadow has room to render.
    pm = QPixmap(pill_w + 4, pill_h + 4)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Single offset rounded rect approximates a soft shadow without
    # the overhead of QGraphicsDropShadowEffect.
    p.setBrush(QBrush(QColor(0, 0, 0, 80)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(2, 3, pill_w, pill_h), 8, 8)

    # Main pill: accent blue with a slightly darker outline.
    p.setBrush(QBrush(QColor("#2563eb")))
    p.setPen(QPen(QColor("#1e40af"), 1))
    p.drawRoundedRect(QRectF(0, 0, pill_w, pill_h), 8, 8)

    # White bold text — high contrast against the blue.
    p.setFont(font)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 0, pill_w, pill_h), Qt.AlignmentFlag.AlignCenter, label)

    p.end()
    return pm


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
        from ...gui.styles.themes import get_colors as _get_colors

        _overlay = _get_colors()["interactive_overlay"]
        # Persistent tooltip label — same pattern as _WeekTableView
        self._tooltip_label = QLabel(self)
        self._tooltip_label.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self._tooltip_label.setStyleSheet(
            "QLabel { background: palette(toolTipBase); color: palette(toolTipText); "
            "border: 1px solid palette(mid); padding: 6px 8px; font-size: 12px; }"
        )
        self._tooltip_label.hide()
        self._tooltip_item_id = None
        self._drag_start_pos = None
        self._drag_item_id = None
        self._drag_item_reminder = ""
        self._dragging = False
        # Drop-target highlight overlay — child of the viewport
        # positioned over the cell currently under the drag cursor so
        # users see exactly which day they are about to drop into.
        # Transparent to mouse events so it never swallows drops.
        self._drop_highlight = QFrame(self.viewport())
        self._drop_highlight.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._drop_highlight.setStyleSheet(
            "QFrame { background: rgba(37, 99, 235, 40); "
            f"border: 2px solid {_overlay}; border-radius: 4px; }}"
        )
        self._drop_highlight.hide()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
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

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._tooltip_label.hide()
        self._tooltip_item_id = None
        self._drag_start_pos = None
        self._drag_item_id = None
        self._drag_item_reminder = ""
        self._dragging = False
        if e is None:
            return
        hit = self._hit_test(e.pos())
        if hit is None:
            return
        if hit[0] == "task":
            self.task_clicked.emit(hit[1].id)
            if e.button() == Qt.MouseButton.LeftButton:
                self._drag_start_pos = e.pos()
                self._drag_item_id = hit[1].id
                self._drag_item_reminder = getattr(hit[1], "reminder", "") or ""
        elif hit[0] == "more":
            self.more_clicked.emit(hit[1], hit[2])

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        if e is None:
            return
        hit = self._hit_test(e.pos())
        if hit is not None and hit[0] == "task":
            self.task_double_clicked.emit(hit[1].id)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag_start_pos = None
        self._drag_item_id = None
        self._drag_item_reminder = ""
        self._dragging = False
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if e is None:
            return
        # Drag initiation
        if (
            not self._dragging
            and self._drag_start_pos is not None
            and self._drag_item_id is not None
            and (e.pos() - self._drag_start_pos).manhattanLength()
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
            pm = _make_drag_pixmap(self._drag_item_reminder)
            drag.setPixmap(pm)
            drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
            drag.exec(Qt.DropAction.MoveAction)
            # Reset after exec — mouseReleaseEvent won't fire
            self._drag_start_pos = None
            self._drag_item_id = None
            self._drag_item_reminder = ""
            self._dragging = False
            return
        # Tooltip on hover — persistent QLabel, not QToolTip.showText()
        hit = self._hit_test(e.pos())
        if hit is not None and hit[0] == "task":
            from ...core.models import build_rich_tooltip
            from ...gui.styles.themes import get_colors

            item = hit[1]
            item_id = getattr(item, "id", None)
            if item_id != self._tooltip_item_id:
                self._tooltip_item_id = item_id
                self._tooltip_label.setText(build_rich_tooltip(item, theme_colors=get_colors()))
                self._tooltip_label.adjustSize()
            cursor = e.globalPosition().toPoint()
            self._tooltip_label.move(cursor.x() + 16, cursor.y() + 8)
            self._tooltip_label.show()
        elif hit is not None and hit[0] == "more":
            n = len(hit[2])
            self._tooltip_item_id = None
            self._tooltip_label.setText(
                QCoreApplication.translate("CalendarViewWidget", f"Click to see all {n} tasks")
            )
            self._tooltip_label.adjustSize()
            cursor = e.globalPosition().toPoint()
            self._tooltip_label.move(cursor.x() + 16, cursor.y() + 8)
            self._tooltip_label.show()
        else:
            self._tooltip_label.hide()
            self._tooltip_item_id = None

    def leaveEvent(self, a0) -> None:  # noqa: N802
        self._tooltip_label.hide()
        self._tooltip_item_id = None
        super().leaveEvent(a0)

    def contextMenuEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        hit = self._hit_test(a0.pos())
        if hit is not None and hit[0] == "task":
            self.task_clicked.emit(hit[1].id)
            self.task_right_clicked.emit(hit[1].id, a0.globalPos())
        else:
            super().contextMenuEvent(a0)

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e is None:
            return
        mime = e.mimeData()
        if mime and mime.hasFormat("application/x-pytodo-item-id"):
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:  # noqa: N802
        if e is None:
            return
        mime = e.mimeData()
        if not (mime and mime.hasFormat("application/x-pytodo-item-id")):
            return
        e.acceptProposedAction()
        index = self.indexAt(e.position().toPoint())
        if index.isValid() and index.data(_DATE_ROLE) is not None:
            self._drop_highlight.setGeometry(self.visualRect(index))
            self._drop_highlight.show()
            self._drop_highlight.raise_()
        else:
            self._drop_highlight.hide()

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._drop_highlight.hide()
        super().dragLeaveEvent(e)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._drop_highlight.hide()
        if event is None:
            return
        mime = event.mimeData()
        if mime is None or not mime.hasFormat("application/x-pytodo-item-id"):
            return
        item_id_str = bytes(mime.data("application/x-pytodo-item-id")).decode()  # type: ignore[arg-type]
        index = self.indexAt(event.position().toPoint())
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
        event.acceptProposedAction()


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

        self._items: list = []
        self._range_start: date = date.today() - timedelta(days=3)
        self._range_end: date = date.today() + timedelta(days=11)
        self._selected_item_id: UUID | None = None
        self._todo_list = None
        self._active_item_id: UUID | None = None
        self._active_elapsed: int = 0
        self._active_session_type: str = ""

        # Persistent item references (typed via Any since pyqtgraph is lazy)
        self._span_bar = None
        self._overdue_bar = None
        self._est_bar = None
        self._pom_bar = None
        self._sw_bar = None
        self._overflow_bar = None
        self._event_bar = None
        self._today_line = None

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

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Lazy PlotWidget — created on first _rebuild_plot(). Eager
        # construction in __init__ exposed a pyqtgraph teardown race on
        # Linux/Windows offscreen CI: the AxisItem queues a deferred
        # boundingRect repaint that fires after pytest-qt destroys the
        # widget, by which time the linked ViewBox has been deleted.
        # Deferring construction means the PlotWidget never exists for
        # off-screen QStackedWidget pages, sidestepping the race entirely.
        self._plot = None

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

        # Plot slot; replaced with the real PlotWidget on first _rebuild_plot().
        self._plot_placeholder = QWidget()
        self._layout.addWidget(self._plot_placeholder, 1)

        # Legend
        self._legend_widget = QWidget()
        self._legend_widget.setFixedHeight(28)
        legend_layout = QHBoxLayout(self._legend_widget)
        legend_layout.setContentsMargins(160, 4, 10, 4)
        legend_layout.setSpacing(16)
        self._legend_labels: list[QLabel] = []
        self._layout.addWidget(self._legend_widget)

    def _ensure_plot(self) -> None:
        """First-use construction of the pg.PlotWidget. Replaces the
        placeholder so layout stretching is preserved."""
        if self._plot is not None:
            return
        import pyqtgraph as pg

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=True, y=False)
        self._plot.showGrid(x=True, y=True, alpha=0.35)
        self._plot.setMenuEnabled(False)
        self._plot.getAxis("left").setWidth(160)
        self._plot.getAxis("bottom").setHeight(30)

        scene = self._plot.scene()
        assert scene is not None
        scene.sigMouseClicked.connect(self._on_plot_clicked)  # type: ignore[attr-defined]
        self._hover_proxy = pg.SignalProxy(
            scene.sigMouseMoved,  # type: ignore[attr-defined]
            rateLimit=30,
            slot=self._on_mouse_moved,
        )

        self._layout.replaceWidget(self._plot_placeholder, self._plot)
        self._plot_placeholder.deleteLater()

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

        # Event date
        ev_c = QColor(c.get("event_date", "#7C3AED"))
        ev_c.setAlpha(120)
        self._event_brush = QBrush(ev_c)

        self._col_text = QColor(c.get("text", "#e0e0e0"))
        self._col_border = QColor(c.get("border", "#3c3c3c"))
        self._col_highlight = QColor(c.get("highlight", "#0078d4"))

    def set_data(self, items: list, current_date: date, todo_list=None) -> None:
        from ...core.config import get_config

        self._items = [i for i in items if i.parent_id is None]

        try:
            sort_tiers = get_config().database.sort_tiers()
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
        if (
            self._pom_bar is None
            or self._sw_bar is None
            or self._overflow_bar is None
            or self._pom_widths is None
            or self._sw_x0s is None
            or self._sw_widths is None
            or self._overflow_x0s is None
            or self._overflow_widths is None
        ):
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
        self._ensure_plot()
        assert self._plot is not None  # _ensure_plot() guarantees this
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
        self._event_bar = None
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

        ev_x0 = np.zeros(n)
        ev_y0 = np.zeros(n)
        ev_w = np.zeros(n)
        ev_h = np.full(n, span_h)

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

            # Event date (target period bar above span)
            if hasattr(item, "event_date") and item.event_date is not None:
                ev_start = self._date_to_days(item.event_date)
                ev_end = ev_start + 1.0  # Show as 1-day marker
                ev_x0[i] = ev_start
                ev_y0[i] = y_base + 0.40
                ev_w[i] = max(0.5, ev_end - ev_start)
            else:
                ev_y0[i] = y_base + 0.40

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

        # Event date bar (light purple)
        self._event_bar = pg.BarGraphItem(
            x0=ev_x0,
            y0=ev_y0,
            width=ev_w,
            height=ev_h,
            brush=self._event_brush,
            pen=pg.mkPen(None),
        )
        plot.addItem(self._event_bar)

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

        plot.setXRange(-0.5, total_days + 0.5, padding=0)  # type: ignore[call-arg]
        plot.setYRange(-0.8, n - 0.2, padding=0.02)  # type: ignore[call-arg]

        self._build_legend()

    def _build_legend(self) -> None:
        c = self._colors
        text_color = c.get("text", "#e0e0e0")
        legend_layout = cast(QHBoxLayout, self._legend_widget.layout())
        _tr = QCoreApplication.translate
        for hex_c, name in [
            (c.get("chart_span", "#4992ff"), _tr("CalendarViewWidget", "Time Span")),
            (c.get("chart_estimate", "#3D4147"), _tr("CalendarViewWidget", "Estimated")),
            (c.get("chart_pomodoro", "#D55E00"), _tr("CalendarViewWidget", "Pomodoro")),
            (c.get("chart_stopwatch", "#0072B2"), _tr("CalendarViewWidget", "Stopwatch")),
            (c.get("event_date", "#7C3AED"), _tr("CalendarViewWidget", "Event Date")),
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
        from ...gui.styles.themes import get_colors

        config_work_mins = get_config().pomodoro.work_duration
        work_mins = _item_work_mins(item, config_work_mins)
        overdue_color = get_colors()["due_overdue"]
        parts = [f"<b>{item.reminder}</b>"]

        if item.due_date:
            overdue = ""
            if date.today() > item.due_date and not item.complete:
                days_over = (date.today() - item.due_date).days
                overdue = f" <span style='color:{overdue_color};'>({days_over}d overdue)</span>"
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
        if hasattr(item, "event_date") and item.event_date:
            parts.append(f"Event: {item.event_date.strftime('%b %d, %Y')}")
        if hasattr(item, "due_time_block") and item.due_time_block:
            block_label = item.due_time_block.replace("_", " ").title()
            parts.append(f"Time block: {block_label}")
        if item.complete:
            parts.insert(1, "<i>Completed</i>")

        return "<br>".join(parts)

    def _on_mouse_moved(self, event_args) -> None:
        # Connected only inside _ensure_plot, so self._plot is realized.
        assert self._plot is not None
        pos = event_args[0]
        plot_item = self._plot.plotItem
        assert plot_item is not None
        vb = plot_item.vb
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

    def leaveEvent(self, a0) -> None:  # noqa: N802
        """Hide tooltip when mouse leaves the widget."""
        self._tooltip_label.hide()
        self._last_hover_row = -1

    def hideEvent(self, a0) -> None:  # noqa: N802
        """Hide tooltip when widget is hidden (view switch)."""
        self._tooltip_label.hide()
        self._last_hover_row = -1

    def _on_plot_clicked(self, event) -> None:
        # Connected only inside _ensure_plot, so self._plot is realized.
        assert self._plot is not None
        pos = event.scenePos()
        plot_item = self._plot.plotItem
        assert plot_item is not None
        vb = plot_item.vb
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

        self._analytics = None
        self._current_date: date = date.today()
        self._active_elapsed: int = 0
        self._active_session_type: str = ""

        # Persistent item references (typed via Any since pyqtgraph is lazy)
        self._pom_bar = None
        self._sw_bar = None
        self._trend_line = None
        self._base_pom_mins = None
        self._base_sw_mins = None
        self._trend_x = None
        self._trend_y = None

        self._create_styles()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Lazy PlotWidget — created on first rebuild(). See
        # _TimelineTimingWidget for the full rationale (pyqtgraph
        # AxisItem teardown race on offscreen CI).
        self._plot = None

        self._last_hover_idx = -1
        self._tooltip_label = QLabel(self)
        self._tooltip_label.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self._tooltip_label.setStyleSheet(
            "QLabel { background: palette(toolTipBase); color: palette(toolTipText); "
            "border: 1px solid palette(mid); padding: 6px 8px; font-size: 12px; }"
        )
        self._tooltip_label.hide()

        # Plot slot; replaced with the real PlotWidget on first rebuild().
        self._plot_placeholder = QWidget()
        self._layout.addWidget(self._plot_placeholder, 1)

        # Legend (always visible)
        self._legend_widget = QWidget()
        self._legend_widget.setFixedHeight(28)
        legend_layout = QHBoxLayout(self._legend_widget)
        legend_layout.setContentsMargins(10, 4, 10, 4)
        legend_layout.setSpacing(16)
        self._legend_labels: list[QLabel] = []
        self._layout.addWidget(self._legend_widget)

    def _ensure_plot(self) -> None:
        """First-use construction of the pg.PlotWidget. Replaces the
        placeholder so layout stretching is preserved."""
        if self._plot is not None:
            return
        import pyqtgraph as pg

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=False, y=True)
        self._plot.showGrid(x=False, y=True, alpha=0.25)
        self._plot.setMenuEnabled(False)
        self._plot.enableAutoRange(axis="y")

        scene = self._plot.scene()
        assert scene is not None
        self._hover_proxy = pg.SignalProxy(
            scene.sigMouseMoved,  # type: ignore[attr-defined]
            rateLimit=30,
            slot=self._on_mouse_moved,
        )

        self._layout.replaceWidget(self._plot_placeholder, self._plot)
        self._plot_placeholder.deleteLater()

    def _on_mouse_moved(self, event_args) -> None:
        """Show tooltip for hovered day bar."""
        # Connected only inside _ensure_plot, so self._plot is realized.
        assert self._plot is not None
        pos = event_args[0]
        plot_item = self._plot.plotItem
        assert plot_item is not None
        vb = plot_item.vb
        if vb is None:
            return
        mouse_point = vb.mapSceneToView(pos)
        day_idx = round(mouse_point.x())

        if day_idx != self._last_hover_idx:
            self._last_hover_idx = day_idx
            if (
                0 <= day_idx < 7
                and self._base_pom_mins is not None
                and self._base_sw_mins is not None
            ):
                pom = float(self._base_pom_mins[day_idx])
                sw = float(self._base_sw_mins[day_idx])
                # Add active projection
                if self._active_elapsed > 0:
                    week_start = self._current_date - timedelta(days=self._current_date.weekday())
                    today_idx = (date.today() - week_start).days
                    if day_idx == today_idx:
                        extra = self._active_elapsed / 60.0
                        if self._active_session_type == "work":
                            pom += extra
                        else:
                            sw += extra
                total = pom + sw
                day_names = [
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                    "Sunday",
                ]
                week_start = self._current_date - timedelta(days=self._current_date.weekday())
                d = week_start + timedelta(days=day_idx)
                parts = [f"<b>{day_names[day_idx]}, {d.strftime('%b %d')}</b>"]
                if pom > 0:
                    parts.append(f"Pomodoro: {int(pom)}m")
                if sw > 0:
                    parts.append(f"Stopwatch: {int(sw)}m")
                parts.append(f"<b>Total: {int(total)}m</b>")

                self._tooltip_label.setText("<br>".join(parts))
                self._tooltip_label.adjustSize()
                from PyQt6.QtCore import QPoint

                mapped = self._plot.mapFromScene(pos)
                qpoint = mapped if isinstance(mapped, QPoint) else mapped.toPoint()
                cursor_pos = self.mapToGlobal(qpoint)
                self._tooltip_label.move(cursor_pos.x() + 16, cursor_pos.y() + 8)
                self._tooltip_label.show()
            else:
                self._tooltip_label.hide()

    def leaveEvent(self, a0) -> None:  # noqa: N802
        self._tooltip_label.hide()
        self._last_hover_idx = -1

    def hideEvent(self, a0) -> None:  # noqa: N802
        self._tooltip_label.hide()
        self._last_hover_idx = -1

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
        trend_color = QColor(c.get("highlight", "#0078d4"))
        self._trend_pen = QPen(trend_color, 2)
        self._trend_pen.setStyle(Qt.PenStyle.DashLine)
        fill_color = QColor(trend_color)
        fill_color.setAlpha(40)
        self._trend_fill_brush = QBrush(fill_color)

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
        if (
            self._pom_bar is None
            or self._sw_bar is None
            or self._base_pom_mins is None
            or self._base_sw_mins is None
        ):
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
        if (
            self._trend_line is not None
            and self._trend_x is not None
            and self._trend_y is not None
            and len(self._trend_x) > 0
        ):
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
        self._ensure_plot()
        assert self._plot is not None  # _ensure_plot() guarantees this
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
            self._show_empty(
                QCoreApplication.translate("CalendarViewWidget", "Analytics service not available")
            )
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
            fillLevel=0,
            fillBrush=self._trend_fill_brush,
        )
        plot.addItem(self._trend_line)

        # Empty state
        total = pom_mins.sum() + sw_mins.sum()
        if total == 0:
            self._show_empty(
                QCoreApplication.translate(
                    "CalendarViewWidget",
                    "No sessions this week \u2014 use \u25c0 \u25b6 to navigate",
                )
            )

        # Legend
        self._build_legend()

        # Axes
        left_axis = plot.getAxis("left")
        left_axis.setTextPen(self._col_text)
        left_axis.setPen(pg.mkPen(self._col_border))
        left_axis.setLabel(QCoreApplication.translate("CalendarViewWidget", "Minutes"))

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTicks([[(float(i), day_labels[i]) for i in range(7)]])
        bottom_axis.setTextPen(self._col_text)
        bottom_axis.setPen(pg.mkPen(self._col_border))

        plot.setXRange(-0.5, 6.5, padding=0)  # type: ignore[call-arg]
        max_y = max(float((pom_mins + sw_mins).max()), 1)
        plot.setYRange(0, max_y * 1.15, padding=0)  # type: ignore[call-arg]

    def _build_legend(self) -> None:
        c = self._colors
        text_color = c.get("text", "#e0e0e0")
        legend_layout = cast(QHBoxLayout, self._legend_widget.layout())
        _tr = QCoreApplication.translate
        for hex_c, name in [
            (c.get("chart_pomodoro", "#D55E00"), _tr("CalendarViewWidget", "Pomodoro")),
            (c.get("chart_stopwatch", "#0072B2"), _tr("CalendarViewWidget", "Stopwatch")),
            (c.get("highlight", "#0078d4"), _tr("CalendarViewWidget", "7-day avg")),
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

        # _show_empty is only called from rebuild() which has already
        # ensured the plot exists; the assert documents the invariant.
        assert self._plot is not None
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

        self._analytics = None
        self._active_elapsed: int = 0
        self._active_session_type: str = ""

        # Persistent item references (12 of each)
        self._block_pom_bars: list = []
        self._block_sw_bars: list = []
        self._base_blocks = None

        self._create_styles()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Lazy PlotWidget — created on first rebuild(). See
        # _TimelineTimingWidget for the full rationale (pyqtgraph
        # AxisItem teardown race on offscreen CI).
        self._plot = None

        self._last_hover_idx = -1
        self._tooltip_label = QLabel(self)
        self._tooltip_label.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self._tooltip_label.setStyleSheet(
            "QLabel { background: palette(toolTipBase); color: palette(toolTipText); "
            "border: 1px solid palette(mid); padding: 6px 8px; font-size: 12px; }"
        )
        self._tooltip_label.hide()

        # Plot slot; replaced with the real PlotWidget on first rebuild().
        self._plot_placeholder = QWidget()
        self._layout.addWidget(self._plot_placeholder, 1)

        self._legend_widget = QWidget()
        self._legend_widget.setFixedHeight(28)
        legend_layout = QHBoxLayout(self._legend_widget)
        legend_layout.setContentsMargins(10, 4, 10, 4)
        legend_layout.setSpacing(16)
        self._legend_labels: list[QLabel] = []
        self._layout.addWidget(self._legend_widget)

    def _ensure_plot(self) -> None:
        """First-use construction of the pg.PlotWidget. Replaces the
        placeholder so layout stretching is preserved."""
        if self._plot is not None:
            return
        import pyqtgraph as pg

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=True, y=False)
        self._plot.showGrid(x=True, y=False, alpha=0.2)
        self._plot.setMenuEnabled(False)

        scene = self._plot.scene()
        assert scene is not None
        self._hover_proxy = pg.SignalProxy(
            scene.sigMouseMoved,  # type: ignore[attr-defined]
            rateLimit=30,
            slot=self._on_mouse_moved,
        )

        self._layout.replaceWidget(self._plot_placeholder, self._plot)
        self._plot_placeholder.deleteLater()

    def _on_mouse_moved(self, event_args) -> None:
        """Show tooltip for hovered time block."""
        if self._base_blocks is None:
            return
        # Connected only inside _ensure_plot, so self._plot is realized.
        assert self._plot is not None
        pos = event_args[0]
        plot_item = self._plot.plotItem
        assert plot_item is not None
        vb = plot_item.vb
        if vb is None:
            return
        mouse_point = vb.mapSceneToView(pos)
        n = len(self._base_blocks)
        block_idx = n - 1 - round(mouse_point.y())

        if block_idx != self._last_hover_idx:
            self._last_hover_idx = block_idx
            if 0 <= block_idx < n:
                row = self._base_blocks.iloc[block_idx]
                label = str(row["block_label"])
                pom = float(row.get("pomodoro_minutes", 0))
                sw = float(row.get("stopwatch_minutes", 0))
                count = int(row["session_count"])
                rate = float(row["completion_rate"])
                avg = float(row["avg_duration_minutes"])

                from datetime import datetime as _dt

                current_block = (_dt.now().hour // 2) * 2
                block_hour = int(row["block_start_hour"])
                if self._active_elapsed > 0 and block_hour == current_block:
                    extra = self._active_elapsed / 60.0
                    if self._active_session_type == "work":
                        pom += extra
                    else:
                        sw += extra

                total = pom + sw
                parts = [f"<b>{label}</b>"]
                parts.append(f"Sessions: {count}")
                if pom > 0:
                    parts.append(f"Pomodoro: {int(pom)}m")
                if sw > 0:
                    parts.append(f"Stopwatch: {int(sw)}m")
                parts.append(f"<b>Total: {int(total)}m</b>")
                parts.append(f"Completion: {round(rate * 100)}%")
                if avg > 0:
                    parts.append(f"Avg session: {int(avg)}m")

                self._tooltip_label.setText("<br>".join(parts))
                self._tooltip_label.adjustSize()
                from PyQt6.QtCore import QPoint

                mapped = self._plot.mapFromScene(pos)
                qpoint = mapped if isinstance(mapped, QPoint) else mapped.toPoint()
                cursor_pos = self.mapToGlobal(qpoint)
                self._tooltip_label.move(cursor_pos.x() + 16, cursor_pos.y() + 8)
                self._tooltip_label.show()
            else:
                self._tooltip_label.hide()

    def leaveEvent(self, a0) -> None:  # noqa: N802
        self._tooltip_label.hide()
        self._last_hover_idx = -1

    def hideEvent(self, a0) -> None:  # noqa: N802
        self._tooltip_label.hide()
        self._last_hover_idx = -1

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

        # _block_pom_bars is non-empty only after rebuild() ran _ensure_plot.
        assert self._plot is not None
        self._plot.setXRange(0, max_minutes * 1.75, padding=0)  # type: ignore[call-arg]

    def rebuild(self) -> None:
        import pyqtgraph as pg

        self._create_styles()
        self._ensure_plot()
        assert self._plot is not None  # _ensure_plot() guarantees this
        plot = self._plot
        plot.clear()
        plot.setBackground(self._colors.get("base", "#252526"))
        self._block_pom_bars = []
        self._block_sw_bars = []
        self._base_blocks = None

        for lbl in self._legend_labels:
            lbl.deleteLater()
        self._legend_labels.clear()

        if self._analytics is None:
            self._show_empty(
                QCoreApplication.translate("CalendarViewWidget", "Analytics service not available")
            )
            self._build_legend()
            return

        blocks = self._analytics.time_block_analysis()
        if blocks.empty or blocks["session_count"].sum() == 0:
            self._show_empty(
                QCoreApplication.translate(
                    "CalendarViewWidget",
                    "Complete some focus sessions to see productivity patterns",
                )
            )
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

        # Axes
        left_axis = plot.getAxis("left")
        left_axis.setTicks([y_ticks])
        left_axis.setTextPen(self._col_text)
        left_axis.setPen(pg.mkPen(self._col_border))
        left_axis.setWidth(100)

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(self._col_text)
        bottom_axis.setPen(pg.mkPen(self._col_border))
        bottom_axis.setLabel(QCoreApplication.translate("CalendarViewWidget", "Minutes"))

        plot.setXRange(0, max_minutes * 1.75, padding=0)  # type: ignore[call-arg]
        plot.setYRange(-0.7, n - 0.3, padding=0.02)  # type: ignore[call-arg]

        self._build_legend()

    def _build_legend(self) -> None:
        c = self._colors
        text_color = c.get("text", "#e0e0e0")
        legend_layout = cast(QHBoxLayout, self._legend_widget.layout())
        _tr = QCoreApplication.translate
        for hex_c, name in [
            (c.get("chart_pomodoro", "#D55E00"), _tr("CalendarViewWidget", "Pomodoro")),
            (c.get("chart_stopwatch", "#0072B2"), _tr("CalendarViewWidget", "Stopwatch")),
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
            f"{_tr('CalendarViewWidget', '% = sessions finished without interruption')}</span>"
        )
        note.setStyleSheet("font-size: 10px;")
        if legend_layout is not None:
            legend_layout.addWidget(note)
        self._legend_labels.append(note)
        if legend_layout is not None:
            legend_layout.addStretch()

    def _show_empty(self, message: str) -> None:
        import pyqtgraph as pg

        # _show_empty is only called from rebuild() which has already
        # ensured the plot exists; the assert documents the invariant.
        assert self._plot is not None
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

        self._analytics = None
        self._list_id: str | None = None
        self._active_item_id: UUID | None = None
        self._active_elapsed: int = 0

        # Persistent item references (typed via Any since pyqtgraph is lazy)
        self._scatter = None
        self._ref_line = None
        self._base_estimated = None
        self._base_actual = None
        self._base_brushes = None

        self._create_styles()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Lazy PlotWidget — created on first rebuild(). See
        # _TimelineTimingWidget for the full rationale (pyqtgraph
        # AxisItem teardown race on offscreen CI).
        self._plot = None

        self._last_hover_idx = -1
        self._tooltip_label = QLabel(self)
        self._tooltip_label.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self._tooltip_label.setStyleSheet(
            "QLabel { background: palette(toolTipBase); color: palette(toolTipText); "
            "border: 1px solid palette(mid); padding: 6px 8px; font-size: 12px; }"
        )
        self._tooltip_label.hide()

        # Plot slot; replaced with the real PlotWidget on first rebuild().
        self._plot_placeholder = QWidget()
        self._layout.addWidget(self._plot_placeholder, 1)

        self._legend_widget = QWidget()
        self._legend_widget.setFixedHeight(28)
        legend_layout = QHBoxLayout(self._legend_widget)
        legend_layout.setContentsMargins(10, 4, 10, 4)
        legend_layout.setSpacing(16)
        self._legend_labels: list[QLabel] = []
        self._layout.addWidget(self._legend_widget)

    def _ensure_plot(self) -> None:
        """First-use construction of the pg.PlotWidget. Replaces the
        placeholder so layout stretching is preserved."""
        if self._plot is not None:
            return
        import pyqtgraph as pg

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=True, y=True)
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setMenuEnabled(False)

        scene = self._plot.scene()
        assert scene is not None
        self._hover_proxy = pg.SignalProxy(
            scene.sigMouseMoved,  # type: ignore[attr-defined]
            rateLimit=30,
            slot=self._on_mouse_moved,
        )

        self._layout.replaceWidget(self._plot_placeholder, self._plot)
        self._plot_placeholder.deleteLater()

    def _on_mouse_moved(self, event_args) -> None:
        """Show tooltip for nearest scatter point."""
        if (
            self._base_estimated is None
            or self._base_actual is None
            or len(self._base_estimated) == 0
        ):
            return
        import numpy as np

        # Connected only inside _ensure_plot, so self._plot is realized.
        assert self._plot is not None
        pos = event_args[0]
        plot_item = self._plot.plotItem
        assert plot_item is not None
        vb = plot_item.vb
        if vb is None:
            return
        mouse_point = vb.mapSceneToView(pos)
        mx, my = mouse_point.x(), mouse_point.y()

        # Find nearest point
        dx = self._base_estimated - mx
        dy = self._base_actual - my
        # Account for active session projection
        actual = self._base_actual.copy()
        if (
            self._active_item_id is not None
            and self._active_elapsed > 0
            and hasattr(self, "_item_ids")
        ):
            for j, iid in enumerate(self._item_ids):
                if iid == str(self._active_item_id):
                    actual[j] += self._active_elapsed / 60.0
                    break
            dy = actual - my

        dist = np.sqrt(dx * dx + dy * dy)
        nearest = int(np.argmin(dist))
        min_dist = float(dist[nearest])

        # Only show if reasonably close (within 20% of axis range)
        max_val = max(float(self._base_estimated.max()), float(actual.max()), 10)
        threshold = max_val * 0.15

        if min_dist < threshold and nearest != self._last_hover_idx:
            self._last_hover_idx = nearest
            est = float(self._base_estimated[nearest])
            act = float(actual[nearest])
            ratio = act / est if est > 0 else 0.0
            status = (
                "Under-estimated"
                if ratio > 1.2
                else "Over-estimated"
                if ratio < 0.8
                else "Accurate"
            )

            parts = [f"<b>{status}</b>"]
            parts.append(f"Estimated: {int(est)}m")
            parts.append(f"Actual: {int(act)}m")
            if est > 0:
                parts.append(f"Ratio: {ratio:.1%}")
            variance = act - est
            parts.append(f"Variance: {'+' if variance >= 0 else ''}{int(variance)}m")

            self._tooltip_label.setText("<br>".join(parts))
            self._tooltip_label.adjustSize()
            from PyQt6.QtCore import QPoint

            mapped = self._plot.mapFromScene(pos)
            qpoint = mapped if isinstance(mapped, QPoint) else mapped.toPoint()
            cursor_pos = self.mapToGlobal(qpoint)
            self._tooltip_label.move(cursor_pos.x() + 16, cursor_pos.y() + 8)
            self._tooltip_label.show()
        elif min_dist >= threshold:
            self._tooltip_label.hide()
            self._last_hover_idx = -1

    def leaveEvent(self, a0) -> None:  # noqa: N802
        self._tooltip_label.hide()
        self._last_hover_idx = -1

    def hideEvent(self, a0) -> None:  # noqa: N802
        self._tooltip_label.hide()
        self._last_hover_idx = -1

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
        if self._scatter is None or self._base_actual is None or self._base_estimated is None:
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
        self._ensure_plot()
        assert self._plot is not None  # _ensure_plot() guarantees this
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
        left_axis.setLabel(QCoreApplication.translate("CalendarViewWidget", "Actual (min)"))

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(self._col_text)
        bottom_axis.setPen(pg.mkPen(self._col_border))
        bottom_axis.setLabel(QCoreApplication.translate("CalendarViewWidget", "Estimated (min)"))

        if self._analytics is None:
            self._show_empty(
                QCoreApplication.translate("CalendarViewWidget", "Analytics service not available")
            )
            return

        accuracy = self._analytics.estimate_accuracy(list_id=self._list_id)
        if accuracy.empty:
            self._show_empty(
                QCoreApplication.translate(
                    "CalendarViewWidget", "Add estimates and complete sessions to track accuracy"
                )
            )
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
            pos=(0, 0),
            angle=45,
            pen=self._ref_pen,
        )
        plot.addItem(self._ref_line)

        max_val = max(float(estimated.max()), float(actual.max()), 10)
        plot.setXRange(0, max_val * 1.1, padding=0)  # type: ignore[call-arg]
        plot.setYRange(0, max_val * 1.1, padding=0)  # type: ignore[call-arg]

    def _build_legend(self) -> None:
        c = self._colors
        text_color = c.get("text", "#e0e0e0")
        legend_layout = cast(QHBoxLayout, self._legend_widget.layout())
        _tr = QCoreApplication.translate
        for hex_c, name in [
            (c.get("chart_overdue", "#b12f25"), _tr("CalendarViewWidget", "Under-estimated")),
            (c.get("chart_span", "#4a90d2"), _tr("CalendarViewWidget", "Accurate")),
            (c.get("chart_stopwatch", "#0072B2"), _tr("CalendarViewWidget", "Over-estimated")),
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

        # _show_empty is only called from rebuild() which has already
        # ensured the plot exists; the assert documents the invariant.
        assert self._plot is not None
        col_text = QColor(self._colors.get("completed_text", "#8c8c8c"))
        text = pg.TextItem(message, color=col_text, anchor=(0.5, 0.5))
        text.setPos(50.0, 50.0)
        self._plot.addItem(text)


# ---------------------------------------------------------------------------
# Timeline Timing Chart — completion-timing bars (Early / On time / Late)
# ---------------------------------------------------------------------------


def _wrap_title_with_info_link(title: str) -> str:
    """Compose a title label string with a trailing ⓘ glyph rendered as
    an `info://` link. The widget owns the QLabel and connects its
    `linkActivated` signal to its own `_show_explanation` slot. Using a
    link inside the existing QLabel rather than a sibling QPushButton
    keeps the widget tree shape identical to the pre-popover layout —
    important because adding a peer widget under the same parent shifted
    pyqtgraph teardown ordering enough to surface a ViewBox-deletion
    race on the Ubuntu 3.12 + offscreen CI matrix only."""
    return f"{title} <a href='info://' style='color: gray; text-decoration: none;'>ⓘ</a>"


class _TimelineTimingWidget(QWidget):
    """Horizontal bar chart showing the Early / On-time / Late split.

    Uses the same `BarState` palette as the day/week calendar bars and
    the matplotlib export so completion-timing reads identically across
    surfaces. The slip rate is shown in the title; the unknown cohort
    is summarized as a footer note when present.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._analytics = None
        self._list_id: str | None = None
        # Lazy PlotWidget — created on first rebuild(). Eager construction
        # in __init__ exposed a pyqtgraph teardown race on Linux/Windows
        # 3.12 + offscreen CI: the AxisItem queues a deferred boundingRect
        # repaint that fires after pytest-qt destroys the widget, by which
        # time the linked ViewBox has been deleted and the call crashes
        # the test runner. Deferring construction until the widget is
        # actually used means the PlotWidget never exists for the
        # off-screen QStackedWidget pages, sidestepping the race entirely.
        self._plot = None

        self._title_text = QCoreApplication.translate("CalendarViewWidget", "Completion Timing")
        self._title_label = QLabel(_wrap_title_with_info_link(self._title_text))
        self._title_label.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px 10px;")
        self._title_label.setOpenExternalLinks(False)
        self._title_label.setToolTip(self.tr("Click ⓘ for the full explanation."))
        self._title_label.linkActivated.connect(lambda _href: self._show_explanation())
        self._note_label = QLabel("")
        self._note_label.setStyleSheet("font-size: 11px; padding: 0px 10px 6px 10px;")
        self._note_label.setVisible(False)

        self._create_styles()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self._title_label)
        # Plot slot; replaced with the real PlotWidget on first rebuild().
        self._plot_placeholder = QWidget()
        self._layout.addWidget(self._plot_placeholder, 1)
        self._layout.addWidget(self._note_label)

    def _ensure_plot(self) -> None:
        """First-use construction of the pg.PlotWidget. Replaces the
        placeholder so layout stretching is preserved."""
        if self._plot is not None:
            return
        import pyqtgraph as pg

        self._plot = pg.PlotWidget()
        self._plot.setBackground(self._colors.get("base", "#252526"))
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.showGrid(x=True, y=False, alpha=0.2)
        self._plot.setMenuEnabled(False)
        self._layout.replaceWidget(self._plot_placeholder, self._plot)
        self._plot_placeholder.deleteLater()

    def _create_styles(self) -> None:
        from ...core.bar_palette import get_palette
        from ...core.calendar_layout import BarState
        from ...gui.styles.themes import Theme, get_colors, get_current_theme

        c = get_colors()
        self._colors = c
        theme_name = "dark" if get_current_theme() == Theme.DARK else "light"
        bar_palette = get_palette(theme_name)
        # Use deviation color for LATE since base is the universal
        # "completed" green; the deviation channel is what marks late
        # bars in the calendar UI.
        self._row_colors = {
            "early": bar_palette[BarState.COMPLETED_EARLY].base,
            "ontime": bar_palette[BarState.COMPLETED_ONTIME].base,
            "late": bar_palette[BarState.COMPLETED_LATE].deviation,
        }
        self._col_text = QColor(c.get("text", "#e0e0e0"))
        self._col_border = QColor(c.get("border", "#3c3c3c"))
        self._col_muted = QColor(c.get("completed_text", "#8c8c8c"))

    def set_analytics(self, analytics) -> None:
        self._analytics = analytics

    def set_list_id(self, list_id: str | None) -> None:
        self._list_id = list_id

    def set_active_session(
        self, item_id: UUID | None = None, elapsed: int = 0, session_type: str = ""
    ) -> None:
        # Completion-timing changes only when items reach completion;
        # accept the call for shape parity with sibling widgets but
        # don't react to in-progress focus sessions.
        del item_id, elapsed, session_type

    def rebuild(self) -> None:
        import pyqtgraph as pg

        self._create_styles()
        self._ensure_plot()
        assert self._plot is not None  # _ensure_plot() guarantees this
        plot = self._plot
        plot.clear()
        plot.setBackground(self._colors.get("base", "#252526"))
        self._note_label.setVisible(False)

        _tr = QCoreApplication.translate
        if self._analytics is None:
            self._set_title(_tr("CalendarViewWidget", "Completion Timing"))
            self._show_empty(_tr("CalendarViewWidget", "Analytics service not available"))
            return

        timing = self._analytics.completion_timing(list_id=self._list_id)
        slip = self._analytics.slip_rate(list_id=self._list_id)

        if slip.rate is not None:
            pct = round(slip.rate * 100)
            self._set_title(
                _tr("CalendarViewWidget", "Completion Timing — slip rate {pct}%").format(pct=pct)
            )
        else:
            self._set_title(_tr("CalendarViewWidget", "Completion Timing"))

        if timing.total == 0:
            self._show_empty(_tr("CalendarViewWidget", "No completed tasks in range"))
            return

        rows = [
            ("late", _tr("CalendarViewWidget", "Late"), timing.late_count),
            ("ontime", _tr("CalendarViewWidget", "On time"), timing.ontime_count),
            ("early", _tr("CalendarViewWidget", "Early"), timing.early_count),
        ]
        max_count = max(timing.early_count, timing.ontime_count, timing.late_count, 1)

        y_ticks = []
        for i, (key, label, count) in enumerate(rows):
            y = float(i)
            y_ticks.append((y, label))
            color = QColor(self._row_colors[key])
            bar = pg.BarGraphItem(
                x0=[0],
                y0=[y - 0.35],
                width=[count],
                height=[0.7],
                brush=color,
                pen=pg.mkPen(color.darker(130), width=1),
            )
            plot.addItem(bar)
            value_text = pg.TextItem(str(count), color=self._col_text, anchor=(0, 0.5))
            value_text.setPos(count + max_count * 0.02, y)
            plot.addItem(value_text)

        left_axis = plot.getAxis("left")
        left_axis.setTicks([y_ticks])
        left_axis.setTextPen(self._col_text)
        left_axis.setPen(pg.mkPen(self._col_border))
        left_axis.setWidth(80)

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(self._col_text)
        bottom_axis.setPen(pg.mkPen(self._col_border))
        bottom_axis.setLabel(_tr("CalendarViewWidget", "Tasks"))

        plot.setXRange(0, max_count * 1.2, padding=0)  # type: ignore[call-arg]
        plot.setYRange(-0.7, len(rows) - 0.3, padding=0.02)  # type: ignore[call-arg]

        if timing.unknown_count > 0:
            self._note_label.setStyleSheet(
                f"font-size: 11px; color: {self._col_muted.name()}; padding: 0px 10px 6px 10px;"
            )
            self._note_label.setText(
                _tr(
                    "CalendarViewWidget",
                    "{n} completed without a recorded timestamp (excluded from classification)",
                ).format(n=timing.unknown_count)
            )
            self._note_label.setVisible(True)

    def _show_empty(self, message: str) -> None:
        import pyqtgraph as pg

        # _show_empty is only called from rebuild() which has already
        # ensured the plot exists; the assert documents the invariant.
        assert self._plot is not None
        text = pg.TextItem(message, color=self._col_muted, anchor=(0.5, 0.5))
        text.setPos(0.5, 0.5)
        self._plot.addItem(text)
        self._plot.setXRange(0, 1, padding=0)  # type: ignore[call-arg]
        self._plot.setYRange(0, 1, padding=0)  # type: ignore[call-arg]

    def _set_title(self, text: str) -> None:
        """Update the title while preserving the trailing ⓘ link."""
        self._title_label.setText(_wrap_title_with_info_link(text))

    def _show_explanation(self) -> None:
        """Popover anchored at the title label. Mirrors the focus-score
        pattern in `dialogs/focus_timer.py`. The text matches the
        classification rules in `core/analytics.py::completion_timing`;
        keep the two in sync if the rules change."""
        from PyQt6.QtWidgets import QToolTip

        text = self.tr(
            "<b>Completion Timing</b><br/>"
            "Where completed tasks landed relative to their deadline.<br/><br/>"
            "<b>Early</b> &nbsp;completed before the deadline<br/>"
            "<b>On time</b> &nbsp;completed exactly at the deadline<br/>"
            "<b>Late</b> &nbsp;completed after the deadline<br/><br/>"
            "The deadline is the task's <code>due_date</code>+<code>due_time</code> "
            "when set, or end-of-day (next-day midnight) for all-day items.<br/><br/>"
            "<b>Slip rate</b> = late ÷ (early + on time + late). Tasks completed "
            "without a recorded timestamp are excluded from both the count and "
            "the rate."
        )
        anchor = self._title_label.mapToGlobal(self._title_label.rect().bottomLeft())
        QToolTip.showText(anchor, text, self._title_label)


# ---------------------------------------------------------------------------
# Timeline Cycle Chart — created→completed cycle-time stats
# ---------------------------------------------------------------------------


class _TimelineCycleWidget(QWidget):
    """Stat tiles for created→completed cycle time (mean / median / p90).

    `cycle_time` returns scalar statistics with no underlying
    distribution at this layer, so a stat-tile layout is the honest
    rendering — a chart of three numbers would be theatre.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._analytics = None
        self._list_id: str | None = None

        self._title_label = QLabel(
            _wrap_title_with_info_link(
                QCoreApplication.translate("CalendarViewWidget", "Cycle Time")
            )
        )
        self._title_label.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px 10px;")
        self._title_label.setOpenExternalLinks(False)
        self._title_label.setToolTip(self.tr("Click ⓘ for the full explanation."))
        self._title_label.linkActivated.connect(lambda _href: self._show_explanation())

        self._tiles_widget = QWidget()
        self._tiles_layout = QHBoxLayout(self._tiles_widget)
        self._tiles_layout.setContentsMargins(20, 10, 20, 10)
        self._tiles_layout.setSpacing(20)

        self._mean_value = QLabel("—")
        self._mean_label = QLabel(QCoreApplication.translate("CalendarViewWidget", "Mean"))
        self._median_value = QLabel("—")
        self._median_label = QLabel(QCoreApplication.translate("CalendarViewWidget", "Median"))
        self._p90_value = QLabel("—")
        self._p90_label = QLabel(QCoreApplication.translate("CalendarViewWidget", "p90"))

        for tile_widget in self._build_tiles():
            self._tiles_layout.addWidget(tile_widget, 1)

        self._subtitle_label = QLabel("")
        self._subtitle_label.setStyleSheet("font-size: 11px; padding: 0px 10px 10px 10px;")
        self._subtitle_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._title_label)
        layout.addWidget(self._tiles_widget)
        layout.addWidget(self._subtitle_label)
        layout.addStretch(1)

        self._apply_styles()

    def _build_tiles(self) -> list[QWidget]:
        tiles: list[QWidget] = []
        for value, label in [
            (self._mean_value, self._mean_label),
            (self._median_value, self._median_label),
            (self._p90_value, self._p90_label),
        ]:
            tile = QWidget()
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(12, 14, 12, 14)
            tile_layout.setSpacing(4)
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile_layout.addWidget(value)
            tile_layout.addWidget(label)
            tiles.append(tile)
        return tiles

    def _apply_styles(self) -> None:
        from ...gui.styles.themes import get_colors

        c = get_colors()
        text_color = c.get("text", "#e0e0e0")
        muted_color = c.get("completed_text", "#8c8c8c")
        border_color = c.get("border", "#3c3c3c")
        alt_bg = c.get("alternate_base", "#2d2d30")

        for value_label in (self._mean_value, self._median_value, self._p90_value):
            value_label.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {text_color};")
        for tag_label in (self._mean_label, self._median_label, self._p90_label):
            tag_label.setStyleSheet(
                f"font-size: 11px; color: {muted_color}; text-transform: uppercase;"
                " letter-spacing: 1px;"
            )
        self._tiles_widget.setStyleSheet(
            f"QWidget {{ background: {alt_bg}; border: 1px solid {border_color};"
            " border-radius: 6px; }"
        )
        self._subtitle_label.setStyleSheet(
            f"font-size: 11px; color: {muted_color}; padding: 0px 10px 10px 10px;"
        )

    def set_analytics(self, analytics) -> None:
        self._analytics = analytics

    def set_list_id(self, list_id: str | None) -> None:
        self._list_id = list_id

    def set_active_session(
        self, item_id: UUID | None = None, elapsed: int = 0, session_type: str = ""
    ) -> None:
        # Cycle time only updates on completion events.
        del item_id, elapsed, session_type

    def rebuild(self) -> None:
        self._apply_styles()
        _tr = QCoreApplication.translate

        if self._analytics is None:
            self._set_values("—", "—", "—")
            self._subtitle_label.setText(
                _tr("CalendarViewWidget", "Analytics service not available")
            )
            return

        result = self._analytics.cycle_time(list_id=self._list_id)
        if result.sample_count == 0 or result.mean_minutes is None:
            self._set_values("—", "—", "—")
            self._subtitle_label.setText(
                _tr(
                    "CalendarViewWidget",
                    "No data yet — cycle time emerges as items reach completion",
                )
            )
            return

        self._set_values(
            self._format_minutes(result.mean_minutes),
            self._format_minutes(result.median_minutes),
            self._format_minutes(result.p90_minutes),
        )
        parts = [
            _tr("CalendarViewWidget", "over {n} completed tasks").format(n=result.sample_count)
        ]
        if result.unknown_count > 0:
            parts.append(
                _tr(
                    "CalendarViewWidget",
                    "{n} completed without a recorded timestamp",
                ).format(n=result.unknown_count)
            )
        self._subtitle_label.setText(" — ".join(parts))

    def _set_values(self, mean: str, median: str, p90: str) -> None:
        self._mean_value.setText(mean)
        self._median_value.setText(median)
        self._p90_value.setText(p90)

    @staticmethod
    def _format_minutes(minutes: float | None) -> str:
        if minutes is None:
            return "—"
        if minutes < 60:
            return f"{round(minutes)}m"
        if minutes < 1440:
            return f"{minutes / 60:.1f}h"
        return f"{minutes / 1440:.1f}d"

    def _show_explanation(self) -> None:
        """Popover anchored at the title label. Mirrors the focus-score
        pattern in `dialogs/focus_timer.py`. Statistics computed in
        `core/analytics.py::cycle_time`; keep in sync."""
        from PyQt6.QtWidgets import QToolTip

        text = self.tr(
            "<b>Cycle Time</b><br/>"
            "How long tasks stay open — from creation "
            "(<code>created_at</code>) to completion "
            "(<code>completed_at</code>).<br/><br/>"
            "<b>Mean</b> &nbsp;arithmetic average across the sample<br/>"
            "<b>Median</b> &nbsp;middle value (50th percentile); robust to outliers<br/>"
            "<b>p90</b> &nbsp;90th percentile; 90% of tasks finished at or "
            "below this duration<br/><br/>"
            "Only completed tasks with both timestamps are included. "
            "Negative durations from clock drift or manual edits are excluded."
        )
        anchor = self._title_label.mapToGlobal(self._title_label.rect().bottomLeft())
        QToolTip.showText(anchor, text, self._title_label)


# ---------------------------------------------------------------------------
# Day-of-week header bar
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Week View — 7 day columns × 25 rows (all-day + 24 hours)
# ---------------------------------------------------------------------------

_WEEK_ITEMS_ROLE = Qt.ItemDataRole.UserRole + 10
_WEEK_HOUR_ROLE = Qt.ItemDataRole.UserRole + 11
_WEEK_DATE_ROLE = Qt.ItemDataRole.UserRole + 12
# Step 6 of calendar Gantt redesign: returns the FULL list of items for
# this column's date regardless of row. The Gantt-bar delegate uses this
# to compute which bars intersect each cell instead of querying per-hour
# items via _WEEK_ITEMS_ROLE (which only returns the items at row.hour).
_WEEK_COLUMN_ITEMS_ROLE = Qt.ItemDataRole.UserRole + 13


class _WeekModel(QAbstractTableModel):
    """Data model for week view — 7 columns (days) × 25 rows (all-day + hours)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._week_dates: list[date] = []
        self._items_by_date: dict[date, list] = {}
        # Q6 marker chips per viewing day. Populated by the widget's
        # refresh() via set_markers(). Markers are computed from items
        # whose due_date is BEFORE the viewing day, so they can never
        # land in _items_by_date naturally.
        self._markers_by_date: dict[date, list] = {}
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
                # All Day row composition (Q6):
                #   1. Marker chips first — these represent past-due
                #      tasks projected forward to this viewing day, and
                #      are visually the most urgent thing on the row.
                #   2. Regular all-day chips next — items keyed on this
                #      day with no hour-grid placement (true all-day +
                #      visibility-fallback fallthrough).
                # Dedup is applied across the union: a marker shadows a
                # regular chip with the same item id (shouldn't happen
                # in practice because markers come from past-due items
                # and regular chips come from items keyed on `d`, but
                # be defensive).
                markers = self._markers_by_date.get(d, [])
                all_day = self._all_day_items(items, d)
                return _dedup_by_id(list(markers) + all_day)
            hour = row - 1
            return _dedup_by_id([i for i in items if i.due_time and i.due_time.hour == hour])

        if role == _WEEK_COLUMN_ITEMS_ROLE:
            # Full column items list with defensive dedup by id. The
            # Gantt delegate uses this to compute intersecting bars for
            # the cell's hour. Dedup catches any source-side duplicate
            # (e.g., a task somehow added twice to the bucket) so the
            # painter only ever renders one bar per unique item id.
            return _dedup_by_id(self._items_by_date.get(d, []))

        if role == Qt.ItemDataRole.DisplayRole:
            if row == 0:
                return QCoreApplication.translate("CalendarViewWidget", "All Day")
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

    def _all_day_items(self, items: list, cell_date: date) -> list:
        """Decide which items render in the All Day row for a cell date.

        The visibility guarantee: every item with due_date == cell_date
        must be visible SOMEWHERE on the calendar. If an item doesn't
        produce an hour-grid segment for this viewing day, it falls
        back to the All Day row so it's still visible.

        Classification:
            - due_time is None         → all-day by definition
            - Q1 window is ALL_DAY     → sanitization fallthrough
            - Q1 window is other but
              no hour-grid segment
              for this day             → visibility fallback
            - Q1 window produces
              an hour-grid segment     → skipped (hour grid handles it)
        """
        from ...core.calendar_layout import (
            WindowKind,
            compute_bar_segments,
            compute_bar_window,
        )

        now = datetime.now()
        out: list = []
        for item in items:
            # Fast path: no due_time → traditional all-day
            if item.due_time is None:
                out.append(item)
                continue
            window = compute_bar_window(item)
            if window is None:
                # Shouldn't happen (items_by_date is keyed on due_date),
                # but defensive.
                out.append(item)
                continue
            if window.kind == WindowKind.ALL_DAY:
                out.append(item)
                continue
            # Does the item produce a visible hour-grid segment for this
            # day? If yes, the hour grid handles it. If no, fall back to
            # the all-day row.
            segments = compute_bar_segments(item, window, cell_date, now)
            has_hour_grid_seg = any(not s.is_all_day and not s.is_marker for s in segments)
            if not has_hour_grid_seg:
                out.append(item)
        return out

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

    def set_markers(self, markers_by_date: dict) -> None:
        """Install Q6 overdue marker chips per viewing day.

        Markers are computed by the calendar widget's refresh() via
        `_collect_markers_for_dates()`. They live in the All Day row
        of viewing days strictly after each item's due day, and reflect
        whatever the lifecycle case (active overdue, historical
        overdue, projected overdue, completed-late historical) demands
        per Q6.
        """
        self.beginResetModel()
        self._markers_by_date = markers_by_date
        self.endResetModel()

    def week_dates(self) -> list[date]:
        return list(self._week_dates)


class _WeekDelegate(QStyledItemDelegate):
    """Painter for week view cells — Gantt-bar rendering model.

    Each task with a temporal anchor produces a bar via
    core.calendar_layout.compute_bar_window/compute_bar_segments. The
    delegate queries the model's _WEEK_COLUMN_ITEMS_ROLE to get the
    full set of items for the cell's column-date, then computes which
    bar slices intersect the cell's hour range and paints them with
    colors from core.bar_palette per the BarState lifecycle.

    A single horizontal "now line" is painted in the cell containing
    the current hour on today's column. The 30-second viewport repaint
    timer installed by CalendarViewWidget triggers fresh state lookups
    so live bars advance their visual treatment as time passes.

    Hour grid (rows 1–24) renders bars; row 0 (All Day) renders task
    chips for items with no due_time. The All Day row will be moved to
    its own pinned widget in Step 9; until then it shares this delegate.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._today = date.today()
        self._selected_item_id: UUID | None = None
        self._colors: dict[str, str] = {}
        self._theme_name = "light"
        self._bar_palette: dict = {}
        self._refresh_colors()

    def _refresh_colors(self) -> None:
        from ...core.bar_palette import get_palette
        from ...gui.styles.themes import Theme, get_colors, get_current_theme

        self._colors = get_colors()
        self._theme_name = "dark" if get_current_theme() == Theme.DARK else "light"
        self._bar_palette = get_palette(self._theme_name)

    def set_selected(self, item_id: UUID | None) -> None:
        self._selected_item_id = item_id

    def _paint_bar_segments(
        self,
        painter: QPainter,
        rect: Any,
        index: QModelIndex,
        current_time: datetime,
    ) -> None:
        """Paint Gantt bar slices for the cell's hour.

        Walks every item in the column (via _WEEK_COLUMN_ITEMS_ROLE),
        computes its segments for the cell's date, and paints the slice
        that intersects this cell's [hour*60, (hour+1)*60) minute range.
        Skips all-day and marker segments — those belong in the All Day
        row, which is rendered separately.
        """
        from ...core.calendar_layout import BarState

        cell_date = index.data(_WEEK_DATE_ROLE)
        hour = index.data(_WEEK_HOUR_ROLE)
        if cell_date is None or hour < 0:
            return  # All Day row handled by chip path
        column_items = index.data(_WEEK_COLUMN_ITEMS_ROLE) or []
        if not column_items:
            return

        cell_minute_start = hour * 60
        cell_minute_end = (hour + 1) * 60
        cell_minute_width = cell_minute_end - cell_minute_start

        # Visual layout: bars are inset from the cell edges so today
        # highlights and grid lines remain visible around them. Horizontal
        # padding is larger (6px each side) to make bars clearly narrower
        # than the cell and read as chips rather than background fills.
        bar_left = rect.left() + 6
        bar_width = rect.width() - 12

        # ------------------------------------------------------------------
        # Compute the cell's bar layout. Continuation slices (bars that
        # span into this cell from a previous one) get a thin ribbon on
        # the left edge so they don't compete with in-cell tasks for
        # horizontal space. In-cell tasks get the rest of the bar width
        # divided into slots with labels.
        # ------------------------------------------------------------------
        layout = _compute_cell_bar_layout(
            column_items,
            cell_date,
            cell_minute_start,
            cell_minute_end,
            bar_left,
            bar_width,
            current_time,
        )
        if not layout.continuing and not layout.starting and not layout.overflow:
            return

        # Convenience aliases for the painting loop below.
        continuing_slots = layout.continuing
        starting_slots = layout.starting
        overflow = layout.overflow

        # Build a single iteration list of (item, window, seg, slot_left,
        # slot_right_edge, is_continuing) tuples so the painting loop
        # below stays simple. Label visibility is decided per-slot from
        # the slot's actual width (see _MIN_LABEL_WIDTH) — day view's
        # wide cells show labels even with 3 slots, week view's narrow
        # cells skip them.
        all_slots = [(*c, True) for c in continuing_slots] + [(*s, False) for s in starting_slots]
        # We re-purpose the existing iteration variables — slot_idx is
        # an index for the visible_count guard below, but that guard is
        # now per-list rather than global.
        visible_count = len(all_slots)
        if visible_count == 0 and overflow == 0:
            return

        # ------------------------------------------------------------------
        # PASS 2: Paint each slot. The slot's geometry was already
        # computed by _compute_cell_bar_layout — for in-cell tasks
        # that's a wide chip; for continuing slices that's a thin
        # ribbon on the left edge that doesn't crowd in-cell tasks.
        # ------------------------------------------------------------------
        for item, window, seg, slot_left, slot_right_edge, _is_ribbon in all_slots:
            visible_start = max(seg.start_minute, cell_minute_start)
            visible_end = min(seg.end_minute, cell_minute_end)
            raw_top = rect.top() + int(
                (visible_start - cell_minute_start) / cell_minute_width * rect.height()
            )
            raw_bot = rect.top() + int(
                (visible_end - cell_minute_start) / cell_minute_width * rect.height()
            )
            # Multi-cell coherence: when the bar continues into an adjacent
            # cell, no inset/border on the continuing edge so adjacent
            # slices merge visually.
            is_continuing_top = seg.start_minute < cell_minute_start
            is_continuing_bot = seg.end_minute > cell_minute_end
            inset_top = 0 if is_continuing_top else 4
            inset_bot = 0 if is_continuing_bot else 4
            top_y = raw_top + inset_top
            bot_y = raw_bot - inset_bot
            if bot_y <= top_y:
                continue

            colors = self._bar_palette[seg.state]
            base_qcolor = QColor(colors.base)
            base_qcolor.setAlpha(235)
            border_color = QColor(colors.base).darker(160)
            border_color.setAlpha(255)

            bar_rect = QRect(
                int(slot_left),
                int(top_y),
                int(slot_right_edge - slot_left),
                int(bot_y - top_y),
            )

            painter.save()
            if not is_continuing_top and not is_continuing_bot:
                # Bar is entirely within this cell — rounded corners +
                # full border (the "chip" look).
                painter.setBrush(base_qcolor)
                painter.setPen(QPen(border_color, 1.5))
                painter.drawRoundedRect(bar_rect, 4, 4)
            else:
                # Multi-cell slice: fill flat, then draw borders only on
                # NON-continuing (exterior) edges. The continuing edges
                # have no horizontal border line, letting adjacent slices
                # blend seamlessly into one bar.
                painter.fillRect(bar_rect, base_qcolor)
                painter.setPen(QPen(border_color, 1.5))
                # Left and right edges always have borders (vertical sides
                # of the bar are always exposed)
                painter.drawLine(
                    bar_rect.left(), bar_rect.top(), bar_rect.left(), bar_rect.bottom()
                )
                painter.drawLine(
                    bar_rect.right(), bar_rect.top(), bar_rect.right(), bar_rect.bottom()
                )
                # Top edge only when segment starts in this cell
                if not is_continuing_top:
                    painter.drawLine(
                        bar_rect.left(), bar_rect.top(), bar_rect.right(), bar_rect.top()
                    )
                # Bottom edge only when segment ends in this cell
                if not is_continuing_bot:
                    painter.drawLine(
                        bar_rect.left(),
                        bar_rect.bottom(),
                        bar_rect.right(),
                        bar_rect.bottom(),
                    )
            painter.restore()

            # Two-zone deviation overlay for completed bars
            if seg.state in (BarState.COMPLETED_EARLY, BarState.COMPLETED_LATE):
                self._paint_deviation_overlay(
                    painter,
                    rect,
                    item,
                    window,
                    seg,
                    cell_minute_start,
                    cell_minute_end,
                    slot_left,
                    slot_right_edge - slot_left,
                )

            # Selection highlight
            if self._selected_item_id is not None and item.id == self._selected_item_id:
                painter.save()
                painter.setPen(QPen(QColor(self._colors["highlight"]), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(bar_rect.adjusted(-1, -1, 1, 1), 4, 4)
                painter.restore()

            # Label — rendered only ONCE per bar. _slice_is_first_labelable
            # does the cross-cell coordination: returns True only when
            # this cell's slice is the FIRST one in the segment whose
            # pixel height crosses the label threshold. Preserves the
            # thin-start-sliver fallback (5-min 19:55-20:00 hands off
            # labeling to the 20:00 body cell) while preventing every
            # subsequent body cell from redundantly labeling.
            this_cell_is_first_labelable = _slice_is_first_labelable(
                seg, cell_minute_start, cell_minute_width, rect.height()
            )
            if (bot_y - top_y) >= 14 and this_cell_is_first_labelable:
                label_width = slot_right_edge - slot_left - 8
                if label_width >= _MIN_LABEL_WIDTH:
                    painter.save()
                    text_font = QFont(painter.font())
                    text_font.setPixelSize(10)
                    text_font.setBold(True)
                    painter.setFont(text_font)
                    fm = QFontMetrics(text_font)
                    label = fm.elidedText(
                        item.reminder or "",
                        Qt.TextElideMode.ElideRight,
                        label_width,
                    )
                    base_c = QColor(colors.base)
                    luminance = (
                        0.299 * base_c.red() + 0.587 * base_c.green() + 0.114 * base_c.blue()
                    )
                    text_color = QColor("white") if luminance < 140 else QColor("#111827")
                    painter.setPen(text_color)
                    painter.drawText(
                        int(slot_left + 4),
                        int(top_y + 1),
                        int(label_width),
                        min(int(bot_y - top_y - 2), 14),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        label,
                    )
                    painter.restore()

        # ------------------------------------------------------------------
        # Overflow badge. Drawn in the top-right corner of the cell so
        # it's always visible and doesn't obscure the displayed bars.
        # The badge geometry comes from _compute_overflow_badge_rect so
        # the hit-test can re-derive the same rect and route badge
        # clicks to the day-popover handler.
        # ------------------------------------------------------------------
        badge_rect = _compute_overflow_badge_rect(rect, overflow)
        if badge_rect is not None:
            painter.save()
            badge_font = QFont(painter.font())
            badge_font.setPixelSize(9)
            badge_font.setBold(True)
            painter.setFont(badge_font)
            painter.setBrush(QColor(17, 24, 39, 220))  # near-black translucent
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.drawText(
                badge_rect,
                Qt.AlignmentFlag.AlignCenter,
                f"+{overflow}",
            )
            painter.restore()

    def _paint_deviation_overlay(
        self,
        painter: QPainter,
        rect: Any,
        item: Any,
        window: Any,
        seg: Any,
        cell_minute_start: int,
        cell_minute_end: int,
        bar_left: int,
        bar_width: int,
    ) -> None:
        """Paint the deviation zone for a COMPLETED_EARLY or COMPLETED_LATE bar.

        Both rely on item.completed_at being set (the BarState classification
        guarantees this for EARLY/LATE — UNKNOWN doesn't trigger this path).
        """
        from ...core.calendar_layout import BarState

        if item.completed_at is None:
            return  # Defensive: should not happen given the state check

        cell_minute_width = cell_minute_end - cell_minute_start
        completed_dt = datetime.fromtimestamp(item.completed_at / 1000)

        # Only paint deviation on the same calendar day as the cell, since
        # we map datetime → minute-of-day for layout.
        if completed_dt.date() != window.end.date():
            # Cross-day deviation will be handled when the cell on
            # completed_dt's day is painted via _maybe_marker_segment's
            # completion-day path. Skip here to avoid double-painting.
            return

        completed_minute = completed_dt.hour * 60 + completed_dt.minute
        end_minute = window.end.hour * 60 + window.end.minute

        if seg.state == BarState.COMPLETED_EARLY:
            zone_start = max(completed_minute, cell_minute_start)
            zone_end = min(end_minute, cell_minute_end)
        else:  # COMPLETED_LATE
            zone_start = max(end_minute, cell_minute_start)
            zone_end = min(completed_minute, cell_minute_end)

        if zone_end <= zone_start:
            return

        zone_top = rect.top() + int(
            (zone_start - cell_minute_start) / cell_minute_width * rect.height()
        )
        zone_bot = rect.top() + int(
            (zone_end - cell_minute_start) / cell_minute_width * rect.height()
        )
        if zone_bot <= zone_top:
            return

        # Two-channel redundancy per WCAG 1.4.1: deviation zones are
        # reinforced by BOTH a chroma bump (stronger alpha than the prior
        # subtle tint) AND a diagonal-hatch texture. Hatching keeps the
        # zone structurally distinct from the base fill even on bars too
        # narrow for the color shift to read, and also serves users with
        # color-vision deficiency who can't resolve the two greens.
        deviation_color = QColor(self._bar_palette[seg.state].deviation)
        if seg.state == BarState.COMPLETED_EARLY:
            deviation_color.setAlpha(200)
            pattern = Qt.BrushStyle.BDiagPattern
        else:  # COMPLETED_LATE
            deviation_color.setAlpha(220)
            pattern = Qt.BrushStyle.FDiagPattern
        brush = QBrush(deviation_color, pattern)
        painter.fillRect(bar_left, zone_top, bar_width, zone_bot - zone_top, brush)

    def _paint_now_line(
        self,
        painter: QPainter,
        rect: Any,
        index: QModelIndex,
        current_time: datetime,
    ) -> None:
        """Paint a single horizontal line at the current minute on today's column.

        Replaces the rejected `_paint_now_overlays` cell-spans approach.
        Single line, single color, simple, honest.
        """
        cell_date = index.data(_WEEK_DATE_ROLE)
        hour = index.data(_WEEK_HOUR_ROLE)
        if cell_date is None or hour < 0:
            return
        if cell_date != current_time.date():
            return
        if hour != current_time.hour:
            return

        line_y = rect.top() + int((current_time.minute / 60.0) * rect.height())
        from ...core.calendar_layout import BarState

        line_color = QColor(self._bar_palette[BarState.OVERDUE_ACTIVE].base)
        painter.save()
        painter.setPen(QPen(line_color, 2))
        painter.drawLine(rect.left() + 1, line_y, rect.right() - 1, line_y)
        painter.restore()

    def _paint_marker_chip(
        self,
        painter: QPainter,
        marker,
        chip_y: int,
        chip_height: int,
        rect: Any,
        x: int,
        text_width: int,
        fm: QFontMetrics,
        is_selected: bool,
        col_alt_base: QColor,
        col_border: QColor,
    ) -> None:
        """Paint a Q6 overdue marker chip in the All Day row.

        Distinct visual treatment from regular all-day chips:
          - Filled background in the OVERDUE_ACTIVE palette color
            (same red the now-line and overdue bars use, so the visual
            language is consistent)
          - White text for WCAG contrast against the red background
          - The marker_label ("3d overdue", "~2w overdue") is the
            primary signal, followed by " · <reminder>" so the user
            can also identify which task is overdue
          - Bold font weight throughout (the marker is the most urgent
            thing in the row and should grab attention)
          - Selection ring re-uses the existing style so clicking still
            visibly highlights the chip
        """
        from ...core.calendar_layout import BarState

        marker_state = getattr(marker, "marker_state", BarState.OVERDUE_ACTIVE)
        bg = QColor(self._bar_palette[marker_state].base)
        bg.setAlpha(235)
        border = QColor(self._bar_palette[marker_state].base).darker(160)

        chip_rect = rect.adjusted(2, 0, -2, 0)
        chip_rect.setTop(chip_y)
        chip_rect.setHeight(chip_height)

        painter.save()
        painter.setBrush(bg)
        painter.setPen(QPen(border, 1.5))
        painter.drawRoundedRect(chip_rect, 3, 3)

        if is_selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(col_border.lighter(150), 2))
            painter.drawRoundedRect(chip_rect.adjusted(-1, -1, 1, 1), 3, 3)

        # Bold text. White on the red bg gives ~7:1 contrast (well
        # above WCAG AA).
        marker_font = QFont(painter.font())
        marker_font.setBold(True)
        painter.setFont(marker_font)
        bold_fm = QFontMetrics(marker_font)

        label = getattr(marker, "marker_label", "") or ""
        reminder = getattr(marker, "reminder", "") or ""
        full_text = f"{label} \u00b7 {reminder}" if reminder else label
        elided = bold_fm.elidedText(full_text, Qt.TextElideMode.ElideRight, text_width - 4)

        painter.setPen(QColor("white"))
        painter.drawText(
            x + 6,
            chip_y,
            text_width,
            chip_height,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided,
        )
        painter.restore()

    def paint(
        self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        if painter is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(option.rect)

        rect = option.rect
        c = self._colors
        cell_date = index.data(_WEEK_DATE_ROLE)
        hour = index.data(_WEEK_HOUR_ROLE)
        items: list = index.data(_WEEK_ITEMS_ROLE) or []

        # Refresh today every paint so the calendar wakes up correctly across
        # midnight without requiring a manual refresh
        self._today = date.today()

        col_base = QColor(c["base"])
        col_alt_base = QColor(c["alternate_base"])
        col_highlight = QColor(c["highlight"])
        col_text = QColor(c["text"])
        col_completed_text = QColor(c["completed_text"])
        col_border = QColor(c["border"])

        # Background
        is_today = cell_date == self._today if cell_date else False
        is_weekend = cell_date.weekday() >= 5 if cell_date else False
        is_all_day = hour == -1

        if is_today and is_all_day:
            # Translucent today tint — paint the base first so the
            # highlight reads as a wash, not a solid block. Higher
            # alpha than hour-grid today cells (60 vs 30) since the
            # all-day band is the primary today-orientation cue.
            today_bg = QColor(col_highlight)
            today_bg.setAlpha(60)
            painter.fillRect(rect, col_base)
            painter.fillRect(rect, today_bg)
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

        # ------------------------------------------------------------------
        # Hour-grid cells: paint Gantt bar segments via the pure-function
        # layer in core.calendar_layout. The All Day row (hour == -1)
        # falls through to the chip path below — it will be moved into
        # its own pinned widget in Step 9.
        # ------------------------------------------------------------------
        current_time = datetime.now()
        if not is_all_day:
            self._paint_bar_segments(painter, rect, index, current_time)
            if is_today:
                self._paint_now_line(painter, rect, index, current_time)

        # Grid lines
        painter.setPen(QPen(col_border, 1))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        # Hour-grid cells use the bar path above; only the All Day row
        # falls through to chip rendering. This avoids drawing chips on
        # top of bars (a half-state that the spec rules out).
        if not is_all_day:
            painter.restore()
            return

        if not items:
            painter.restore()
            return

        # Draw task chips (All Day row only)
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

            # Q6 marker chip — distinct OVERDUE_ACTIVE-colored chip with
            # the elapsed-overdue duration label (e.g., "3d overdue") as
            # the primary text. Renders ABOVE the regular chip code path,
            # which falls through for plain TodoItems.
            if getattr(item, "marker_label", None) is not None:
                self._paint_marker_chip(
                    painter,
                    item,
                    chip_y,
                    chip_height,
                    rect,
                    x,
                    text_width,
                    fm,
                    is_selected,
                    col_alt_base,
                    col_border,
                )
                continue

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

        # Overflow indicator. Today-all-day no longer needs a special
        # text color override now that its background is a translucent
        # tint over col_base rather than a solid highlight fill — the
        # standard muted-gray reads against the wash the same way it
        # does on a non-today cell.
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
                QCoreApplication.translate("CalendarViewWidget", f"+{overflow} more"),
            )

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> Any:
        from PyQt6.QtCore import QSize

        return QSize(100, 40)


class _HoverAddCellButton(QWidget):
    """Floating "+" button shown on hover over hour-grid calendar cells.

    Click adds a task at the cell's date and hour (cell-hour, minute=0).
    Universal affordance: appears whether the cell is empty or already
    contains task bars. Lives as a child of the table viewport so Qt
    routes events naturally — clicks on the button fire ``clicked``;
    clicks outside the button bounds fall through to the table's
    ``mousePressEvent`` and the existing task hit-test path.

    Implemented as a custom-painted QWidget rather than QPushButton
    because macOS's native aqua QPushButton style renders pill-shaped
    backgrounds regardless of QSS ``border-radius``. A manually-painted
    ellipse + "+" glyph gives a perfect circle on every platform with
    no native-style interference.

    Tooltip-stacking coordination: emits ``hover_started`` on enter so
    the parent table view can immediately hide its persistent task
    tooltip when the cursor crosses into the button. The button
    captures all mouse events the moment the cursor enters its bounds,
    so the table's mouseMoveEvent (which would otherwise hide the
    tooltip via geometry check) stops firing. Without this signal the
    persistent tooltip from the previous frame would remain visible
    until the user moved the cursor off the button.
    """

    _SIZE = 32  # outer widget size; visible circle fills it exactly

    clicked = pyqtSignal()
    hover_started = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._cell_date: date | None = None
        self._hour: int = -1
        self._hovered = False
        self._pressed = False
        self.setFixedSize(self._SIZE, self._SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        # Theme-aware colors cached at construction.
        from ...gui.styles.themes import get_colors

        c = get_colors()
        self._color_base = QColor(c.get("base", "#ffffff"))
        self._color_highlight = QColor(c.get("highlight", "#1976d2"))
        self._color_highlight_text = QColor(c.get("highlight_text", "#ffffff"))
        # No animations — see commit message for the b8 lazy-PlotWidget /
        # teardown-race story; the same family of segfaults applies to
        # QPropertyAnimation on this widget's geometry/opacity. Snap
        # show/hide and snap repositioning are teardown-safe.
        self.hide()

    def paintEvent(self, a0) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Inset by 1 px on each side so the 2 px border draws cleanly
        # within the widget bounds (no clipping at the rect edges).
        rect = self.rect().adjusted(1, 1, -1, -1)
        if self._hovered or self._pressed:
            fill_color = self._color_highlight
            glyph_color = self._color_highlight_text
        else:
            fill_color = self._color_base
            glyph_color = self._color_highlight
        painter.setBrush(QBrush(fill_color))
        painter.setPen(QPen(self._color_highlight, 2))
        painter.drawEllipse(rect)
        # "+" glyph: two perpendicular lines centered on the widget.
        glyph_pen = QPen(glyph_color, 2.5)
        painter.setPen(glyph_pen)
        cx = rect.center().x()
        cy = rect.center().y()
        arm = self._SIZE // 4
        painter.drawLine(cx - arm, cy, cx + arm, cy)
        painter.drawLine(cx, cy - arm, cx, cy + arm)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        self.hover_started.emit()
        super().enterEvent(event)

    def leaveEvent(self, a0) -> None:  # noqa: N802
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(a0)

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(a0)

    def mouseReleaseEvent(self, a0) -> None:  # noqa: N802
        was_pressed = self._pressed
        self._pressed = False
        self.update()
        if (
            a0 is not None
            and a0.button() == Qt.MouseButton.LeftButton
            and was_pressed
            and self.rect().contains(a0.pos())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(a0)

    def show_at(self, target_top_left: QPoint, cell_date: date, hour: int) -> None:
        """Position the button at ``target_top_left`` and ensure it is
        visible. Snaps to the new position when moved between cells."""
        self._cell_date = cell_date
        self._hour = hour
        self.setToolTip(self._format_tooltip(cell_date, hour))
        if self.pos() != target_top_left:
            self.move(target_top_left)
        if not self.isVisible():
            self.show()
            self.raise_()

    def hide_smoothly(self) -> None:
        """Hide. Idempotent if already hidden."""
        if self.isVisible():
            self.hide()

    def cell_date(self) -> date | None:
        return self._cell_date

    def cell_hour(self) -> int:
        return self._hour

    @staticmethod
    def _format_tooltip(cell_date: date, hour: int) -> str:
        # 12-hour clock with am/pm; calendar surface uses the same
        # convention for hour-row labels.
        if hour == 0:
            time_str = "12am"
        elif hour < 12:
            time_str = f"{hour}am"
        elif hour == 12:
            time_str = "12pm"
        else:
            time_str = f"{hour - 12}pm"
        return f"Add task on {cell_date.strftime('%a %b %d')} at {time_str}"


class _WeekTableView(QTableView):
    """Week grid with day columns and hour rows."""

    task_clicked = pyqtSignal(object)
    task_double_clicked = pyqtSignal(object)
    task_right_clicked = pyqtSignal(object, object)
    task_dropped = pyqtSignal(object, object, object)  # (item_id, target_date, target_hour or None)
    more_clicked = pyqtSignal(object, object)  # (date, list[TodoItem])
    # Edge-drag-to-resize completion. Emits (item_id, field_name, new_value)
    # where field_name is one of "due_time", "due_time_end", or
    # "estimated_minutes".
    task_resized = pyqtSignal(object, str, object)
    # Click on an empty hour-grid cell — emits (cell_date, hour) so the
    # main window can open AddTodoDialog with the cell's date + hour
    # pre-filled. The hour value is the cell's hour-of-day (0-23).
    add_task_at_requested = pyqtSignal(object, int)

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
        # Cached interactive-overlay color for drag-preview / resize-snap
        # affordances created below. Looked up once at construction time;
        # the value is theme-invariant by design (#2563eb in both LIGHT
        # and DARK_COLORS) so a runtime theme switch does not change it.
        from ...gui.styles.themes import get_colors as _get_colors

        _overlay = _get_colors()["interactive_overlay"]
        # Persistent tooltip label — stays visible as long as the mouse
        # hovers over a task bar, unaffected by viewport repaints from
        # the now-timer. Same pattern as the timeline chart tooltips.
        self._tooltip_label = QLabel(self)
        self._tooltip_label.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self._tooltip_label.setStyleSheet(
            "QLabel { background: palette(toolTipBase); color: palette(toolTipText); "
            "border: 1px solid palette(mid); padding: 6px 8px; font-size: 12px; }"
        )
        self._tooltip_label.hide()
        self._tooltip_item_id = None
        self._drag_start_pos = None
        self._drag_item_id = None
        self._drag_item_reminder = ""
        self._dragging = False
        # Drop-target highlight overlay — child of the viewport
        # positioned over the cell currently under the drag cursor.
        # Transparent to mouse events so it never swallows drops.
        self._drop_highlight = QFrame(self.viewport())
        self._drop_highlight.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._drop_highlight.setStyleSheet(
            "QFrame { background: rgba(37, 99, 235, 40); "
            f"border: 2px solid {_overlay}; border-radius: 4px; }}"
        )
        self._drop_highlight.hide()
        # Floating preview label that follows the cursor during a drag
        # and shows the exact date + time the drop will land on. Uses
        # the same tool-window pattern as _tooltip_label so repaints
        # from the now-timer don't flicker it.
        self._drag_preview_label = QLabel(self)
        self._drag_preview_label.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self._drag_preview_label.setStyleSheet(
            f"QLabel {{ background: {_overlay}; color: white; "
            "border-radius: 6px; padding: 6px 10px; "
            "font-size: 12px; font-weight: bold; }"
        )
        self._drag_preview_label.hide()

        # Edge-drag-to-resize state (#18). None when not actively
        # resizing; a dict otherwise:
        #   item_id, edge ("top"|"bottom"), kind (WindowKind name),
        #   original_due_time, original_due_time_end,
        #   original_estimated_minutes, target_minute_of_day,
        #   target_date.
        self._edge_resize: dict | None = None
        # Snap-line indicator painted at the snapped target y while
        # resizing — gives the user visual confirmation of what minute
        # the edge will land on. Transparent to mouse events.
        self._resize_snap_line = QFrame(self.viewport())
        self._resize_snap_line.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._resize_snap_line.setStyleSheet(f"QFrame {{ background: {_overlay}; border: none; }}")
        self._resize_snap_line.setFixedHeight(2)
        self._resize_snap_line.hide()
        # Floating label showing the snap-target time during a resize.
        self._resize_snap_label = QLabel(self)
        self._resize_snap_label.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self._resize_snap_label.setStyleSheet(
            f"QLabel {{ background: {_overlay}; color: white; "
            "border-radius: 6px; padding: 4px 8px; "
            "font-size: 11px; font-weight: bold; }"
        )
        self._resize_snap_label.hide()

        # Floating "+" button shown on hover over hour-grid cells.
        # Universal add-task affordance: works whether the cell is empty
        # or already contains task bars. Lives as a child of the viewport
        # so Qt routes events naturally — clicks on the button fire its
        # `clicked`; clicks outside the button bounds fall through to
        # mousePressEvent and the existing task hit-test path.
        viewport_for_btn = self.viewport()
        assert viewport_for_btn is not None
        self._hover_add_btn = _HoverAddCellButton(viewport_for_btn)
        self._hover_add_btn.clicked.connect(self._on_hover_add_clicked)
        # Tooltip coordination: hide the persistent task tooltip the
        # moment the cursor enters the "+" button. Complements the
        # mouseMoveEvent geometry check (which only fires while the
        # cursor is on the table viewport, not on the button).
        self._hover_add_btn.hover_started.connect(self._hide_task_tooltip)

    def _on_hover_add_clicked(self) -> None:
        """Forward a "+" button click to the same signal the empty-cell
        click flow uses, with the date/hour the button is currently
        positioned for."""
        cell_date = self._hover_add_btn.cell_date()
        if cell_date is not None:
            self.add_task_at_requested.emit(cell_date, self._hover_add_btn.cell_hour())

    def _hide_task_tooltip(self) -> None:
        """Hide the persistent task-bar tooltip. Called from the "+"
        button's ``hover_started`` signal so two tooltips don't render
        on top of each other when the cursor enters the button."""
        self._tooltip_label.hide()
        self._tooltip_item_id = None

    def _hit_test(self, pos):
        """Find what was clicked at `pos`.

        Hour-grid cells (rows 1–24) hit-test against Gantt bar segments
        from core.calendar_layout. The All Day row (row 0) still uses
        the chip-rectangle hit logic until Step 9 moves it to its own
        widget.

        Returns:
            ("task", TodoItem, QModelIndex) when a bar slice or chip
                was hit
            ("more", date, items) when the All Day overflow area was
                hit
            None when nothing was under the cursor
        """
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        cell_date = index.data(_WEEK_DATE_ROLE)
        hour = index.data(_WEEK_HOUR_ROLE)
        if cell_date is None:
            return None

        rect = self.visualRect(index)

        # ------------------------------------------------------------------
        # Hour grid: bar segment hit-test
        # ------------------------------------------------------------------
        if hour >= 0:
            return self._hit_test_bar_segments(pos, rect, index, cell_date, hour)

        # ------------------------------------------------------------------
        # All Day row: chip hit-test (preserved until Step 9)
        # ------------------------------------------------------------------
        items = index.data(_WEEK_ITEMS_ROLE) or []
        if not items:
            return None

        font = QFont()
        font.setPixelSize(10)
        fm = QFontMetrics(font)
        chip_height = fm.height() + 4
        overflow_height = fm.height() + 2
        available = rect.height() - 4

        if len(items) * chip_height <= available:
            max_chips = len(items)
        else:
            max_chips = max(1, (available - overflow_height) // chip_height)

        click_y = pos.y() - rect.top() - 2
        item_idx = int(click_y / chip_height) if chip_height > 0 else -1

        if len(items) > max_chips and item_idx >= max_chips:
            return ("more", cell_date, items)

        if 0 <= item_idx < min(max_chips, len(items)):
            return ("task", items[item_idx], index)
        return None

    def _hit_test_bar_segments(self, pos, rect, index, cell_date, hour):
        """Find which bar slice (if any) is under `pos` in an hour-grid cell.

        Mirrors _WeekDelegate._paint_bar_segments geometry: walks the
        column items, computes segments via calendar_layout, and returns
        the first item whose visible slice contains the click point.
        Iteration order matches paint order so the front-most bar wins.
        """
        from datetime import datetime as _dt

        column_items = index.data(_WEEK_COLUMN_ITEMS_ROLE) or []
        if not column_items:
            return None

        click_x = pos.x()
        click_y = pos.y()

        cell_minute_start = hour * 60
        cell_minute_end = (hour + 1) * 60
        cell_minute_width = cell_minute_end - cell_minute_start

        # Compute the same layout the painter uses, then test the click
        # against each slot's actual on-screen rectangle. This ensures
        # the slot the user CLICKED ON is the slot that returns a hit,
        # not just any item whose segment time range happens to include
        # the click time.
        bar_left = rect.left() + 6
        bar_width = rect.width() - 12
        layout = _compute_cell_bar_layout(
            column_items,
            cell_date,
            cell_minute_start,
            cell_minute_end,
            bar_left,
            bar_width,
            _dt.now(),
        )

        # Overflow badge: if the click is on the "+N" badge, hand the
        # popover EVERY task in this cell — both the visible chips and
        # the hidden overflow. Once labels get disabled (3+ in-cell
        # tasks), the visible chips are unidentifiable, so the popover
        # is the only way for the user to actually read which tasks
        # are in this hour. Tested first because the badge sits on top
        # of the bar slots in the cell's top-right corner.
        if layout.overflow_items:
            badge_rect = _compute_overflow_badge_rect(rect, len(layout.overflow_items))
            if badge_rect is not None and badge_rect.contains(pos):
                visible_starting = [t[0] for t in layout.starting]
                all_in_cell = visible_starting + list(layout.overflow_items)
                return ("more", cell_date, all_in_cell)

        # Test starting (in-cell) slots first — they're the wider, more
        # specific slots and the user is most likely clicking those.
        # Hit zones are dilated to a minimum of _MIN_HIT_HEIGHT pixels
        # (WCAG 2.5.5 Target Size) centered on the bar's visual middle
        # and clamped to the cell rect. The minimum-height layout floor
        # keeps the visible bar as a short strip; this dilation makes
        # that strip clickable at the accessibility standard without
        # altering its appearance.
        for item, _window, seg, slot_left, slot_right in layout.starting:
            if not (slot_left <= click_x <= slot_right):
                continue
            visible_start = max(seg.start_minute, cell_minute_start)
            visible_end = min(seg.end_minute, cell_minute_end)
            seg_top_y = rect.top() + int(
                (visible_start - cell_minute_start) / cell_minute_width * rect.height()
            )
            seg_bot_y = rect.top() + int(
                (visible_end - cell_minute_start) / cell_minute_width * rect.height()
            )
            hit_top_y, hit_bot_y = _dilate_hit_zone(
                seg_top_y, seg_bot_y, cell_top=rect.top(), cell_bottom=rect.bottom()
            )
            if hit_top_y <= click_y <= hit_bot_y:
                return ("task", item, index)

        # Then test continuing ribbons (narrow strips on the left edge).
        for item, _window, _seg, slot_left, slot_right in layout.continuing:
            if not (slot_left <= click_x <= slot_right):
                continue
            # Continuing slices fill the cell vertically — any click in
            # the ribbon x range is a hit.
            return ("task", item, index)

        return None

    # Within this many pixels of a bar's visible top or bottom edge,
    # cursor switches to vertical-resize and a click enters edge-drag
    # mode (#18). Tuned to the same 6 px the spec calls out — small
    # enough not to swallow body clicks on tall bars, large enough to
    # be reachable on a short floored bar.
    _EDGE_HIT_PIXELS = 6

    def _hit_test_edge(self, pos):
        """Find a draggable bar edge at `pos`, or return None.

        Tests starting (in-cell origin) slots only — continuing slot
        edges are clip indicators per Q3 and are NOT draggable. The
        top edge is also suppressed for DEADLINE_FROM_CREATED bars
        per the #18 spec (the top of those bars is the clip-from-created
        indicator, not a real start time).

        Returns a dict on hit, None otherwise. The dict has:
            edge: "top" or "bottom"
            item: the TodoItem the edge belongs to
            kind: WindowKind enum value
            cell_rect: the cell rect in viewport coordinates
            cell_date: the date the cell represents
            slot_x_range: (left, right) slot x-bounds in viewport coords
        """
        from datetime import datetime as _dt

        from ...core.calendar_layout import WindowKind, compute_bar_window

        index = self.indexAt(pos)
        if not index.isValid():
            return None
        cell_date = index.data(_WEEK_DATE_ROLE)
        hour = index.data(_WEEK_HOUR_ROLE)
        if cell_date is None or hour < 0:
            return None

        rect = self.visualRect(index)
        column_items = index.data(_WEEK_COLUMN_ITEMS_ROLE) or []
        if not column_items:
            return None

        cell_minute_start = hour * 60
        cell_minute_end = (hour + 1) * 60
        cell_minute_width = cell_minute_end - cell_minute_start
        bar_left = rect.left() + 6
        bar_width = rect.width() - 12
        layout = _compute_cell_bar_layout(
            column_items,
            cell_date,
            cell_minute_start,
            cell_minute_end,
            bar_left,
            bar_width,
            _dt.now(),
        )

        click_x = pos.x()
        click_y = pos.y()

        # Combine starting and continuing slots — both can hold a true
        # edge of the bar in the current cell. A starting slot's
        # clipped_top is False (origin in this cell); a continuing
        # slot's clipped_bottom may be False (true end in this cell).
        # The clipped_top / clipped_bottom flags on the segment are
        # the source of truth for "is this a real edge or a clip
        # indicator," not the slot category.
        all_slots = list(layout.starting) + list(layout.continuing)
        for item, _window, seg, slot_left, slot_right in all_slots:
            if not (slot_left <= click_x <= slot_right):
                continue
            visible_start = max(seg.start_minute, cell_minute_start)
            visible_end = min(seg.end_minute, cell_minute_end)
            seg_top_y = rect.top() + int(
                (visible_start - cell_minute_start) / cell_minute_width * rect.height()
            )
            seg_bot_y = rect.top() + int(
                (visible_end - cell_minute_start) / cell_minute_width * rect.height()
            )

            window = compute_bar_window(item)
            if window is None:
                continue

            # Top edge — only when the segment's true origin is in this
            # cell (not clipped from earlier) and the bar's window kind
            # has a draggable top per #18.
            if (
                not seg.clipped_top
                and abs(click_y - seg_top_y) <= self._EDGE_HIT_PIXELS
                and window.kind != WindowKind.DEADLINE_FROM_CREATED
                and window.kind != WindowKind.ALL_DAY
            ):
                return {
                    "edge": "top",
                    "item": item,
                    "kind": window.kind,
                    "cell_rect": rect,
                    "cell_date": cell_date,
                    "slot_x_range": (slot_left, slot_right),
                }

            # Bottom edge — only when the segment's true end is in this
            # cell. Draggable for every kind that renders in the hour
            # grid (EVENT, WORKBACK, DEADLINE_FROM_CREATED).
            if (
                not seg.clipped_bottom
                and abs(click_y - seg_bot_y) <= self._EDGE_HIT_PIXELS
                and window.kind != WindowKind.ALL_DAY
            ):
                return {
                    "edge": "bottom",
                    "item": item,
                    "kind": window.kind,
                    "cell_rect": rect,
                    "cell_date": cell_date,
                    "slot_x_range": (slot_left, slot_right),
                }

        return None

    # Granularity for the resize-drag snap. Default is 15 minutes
    # (the half-hour rhythm Google / Apple Calendar use); holding Shift
    # disengages snap so the user can land on any minute.
    _RESIZE_SNAP_MINUTES = 15

    def _y_to_minute_of_day(self, y: int, x_for_column: int):
        """Map a viewport y-coordinate to (minute_of_day, target_date).

        Uses indexAt() at the given x to find which hour-cell the y is
        in, then computes the fractional position within that cell.
        Clamps to [0, 1440) so a drag that overshoots the top/bottom of
        the visible grid still produces a sensible value. Returns
        (None, None) only when no valid hour cell is reachable from
        the x column at all (e.g. the All Day row).
        """
        from PyQt6.QtCore import QPoint as _QPoint

        index = self.indexAt(_QPoint(x_for_column, y))
        if index.isValid():
            hour = index.data(_WEEK_HOUR_ROLE)
            target_date = index.data(_WEEK_DATE_ROLE)
            rect = self.visualRect(index)
            if hour is not None and hour >= 0 and target_date is not None and rect.height() > 0:
                frac = (y - rect.top()) / rect.height()
                frac = max(0.0, min(1.0, frac))
                minute_in_hour = int(round(frac * 60))
                minute = hour * 60 + minute_in_hour
                return max(0, min(1439, minute)), target_date
        # Out of grid — clamp by walking to the nearest hour cell at
        # row 1 (top) or row 24 (bottom) of the same column.
        model = self.model()
        if model is None:
            return None, None
        for probe_row in (1, 24):
            probe = model.index(probe_row, 0)
            if not probe.isValid():
                continue
            rect = self.visualRect(probe)
            target_date = probe.data(_WEEK_DATE_ROLE)
            if target_date is None:
                continue
            if y <= rect.top():
                return 0, target_date
            if y >= rect.bottom():
                return 1439, target_date
        return None, None

    def _snap_minute(self, minute: int, fine: bool) -> int:
        snap = 1 if fine else self._RESIZE_SNAP_MINUTES
        return max(0, min(1439, round(minute / snap) * snap))

    def _minute_to_field_change(self, edge: str, kind, item, target_minute: int):
        """Return (field_name, new_value) for committing a resize, or None.

        Maps each (edge, WindowKind) pair to the correct field per the
        locked Q1 origin rules (see issue #18 and
        docs/plans/calendar-gantt-redesign.md):

            top + EVENT      → due_time = target
            top + WORKBACK   → estimated_minutes = (due_minute - target)
            bottom + EVENT   → due_time_end = target
            bottom + WORKBACK → due_time = target
            bottom + DEADLINE_FROM_CREATED → due_time = target

        Returns None when the resulting value would be no-change or
        would produce a negative duration (e.g. dragging the top of a
        workback bar onto or past the due_time).
        """
        from datetime import time as _time

        from ...core.calendar_layout import WindowKind

        new_time = _time(target_minute // 60, target_minute % 60)

        if edge == "top" and kind == WindowKind.EVENT:
            if item.due_time_end is None:
                return None
            end_minute = item.due_time_end.hour * 60 + item.due_time_end.minute
            if target_minute >= end_minute:
                return None
            if item.due_time == new_time:
                return None
            return ("due_time", new_time)

        if edge == "top" and kind == WindowKind.WORKBACK:
            if item.due_time is None:
                return None
            due_minute = item.due_time.hour * 60 + item.due_time.minute
            new_estimate = due_minute - target_minute
            if new_estimate <= 0:
                return None
            if item.estimated_minutes == new_estimate:
                return None
            return ("estimated_minutes", new_estimate)

        if edge == "bottom" and kind == WindowKind.EVENT:
            if item.due_time is None:
                return None
            start_minute = item.due_time.hour * 60 + item.due_time.minute
            if target_minute <= start_minute:
                return None
            if item.due_time_end == new_time:
                return None
            return ("due_time_end", new_time)

        if edge == "bottom" and kind in (WindowKind.WORKBACK, WindowKind.DEADLINE_FROM_CREATED):
            if item.due_time == new_time:
                return None
            return ("due_time", new_time)

        return None

    def _update_resize_preview(self, target_minute: int) -> None:
        """Position the snap-line overlay and update the snap label."""
        from datetime import time as _time

        if self._edge_resize is None:
            return
        slot_left, slot_right = self._edge_resize["slot_x_range"]
        # Find the row whose cell contains target_minute and use its
        # rect to compute the snap y. Row 0 is All Day, rows 1-24 are
        # hours 0-23.
        hour = max(0, min(23, target_minute // 60))
        row = hour + 1
        target_date = self._edge_resize["cell_date"]
        # Find the column index whose date matches target_date — fall
        # back to column 0 if the model isn't a multi-day week.
        model = self.model()
        if model is None:
            return
        col = 0
        for c in range(model.columnCount()):
            probe = model.index(row, c)
            if probe.data(_WEEK_DATE_ROLE) == target_date:
                col = c
                break
        index = model.index(row, col)
        rect = self.visualRect(index)
        if rect.height() <= 0:
            return
        minute_in_hour = target_minute - hour * 60
        snap_y = rect.top() + int(minute_in_hour / 60 * rect.height())
        viewport = self.viewport()
        if viewport is None:
            return
        self._resize_snap_line.setGeometry(slot_left, snap_y - 1, slot_right - slot_left, 2)
        self._resize_snap_line.show()
        self._resize_snap_line.raise_()
        # Snap label — render to the right of the slot, near the line.
        snap_time = _time(target_minute // 60, target_minute % 60)
        label_text = snap_time.strftime("%I:%M %p").lstrip("0")
        self._resize_snap_label.setText(label_text)
        self._resize_snap_label.adjustSize()
        viewport_pt = viewport.mapToGlobal(QPoint(slot_right + 6, snap_y - 12))
        self._resize_snap_label.move(viewport_pt)
        self._resize_snap_label.show()

    def _hide_resize_preview(self) -> None:
        self._resize_snap_line.hide()
        self._resize_snap_label.hide()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._tooltip_label.hide()
        self._tooltip_item_id = None
        self._drag_start_pos = None
        self._drag_item_id = None
        self._drag_item_reminder = ""
        self._dragging = False
        if e is None:
            return
        # Edge-drag-to-resize takes precedence over body click — when
        # the cursor is on a draggable edge, a press enters resize mode
        # and the existing click-and-drag-to-reschedule path is skipped
        # for this gesture.
        edge_hit = self._hit_test_edge(e.pos())
        if edge_hit is not None and e.button() == Qt.MouseButton.LeftButton:
            slot_left, slot_right = edge_hit["slot_x_range"]
            raw_minute, _td = self._y_to_minute_of_day(e.pos().y(), (slot_left + slot_right) // 2)
            if raw_minute is None:
                raw_minute = 0
            # Snap immediately so a no-movement click doesn't commit a
            # one-minute change just because the click landed inside the
            # 6 px hit zone but a pixel off the true edge.
            fine = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            target_minute = self._snap_minute(raw_minute, fine)
            self._edge_resize = {
                "item_id": edge_hit["item"].id,
                "item": edge_hit["item"],
                "edge": edge_hit["edge"],
                "kind": edge_hit["kind"],
                "cell_date": edge_hit["cell_date"],
                "slot_x_range": edge_hit["slot_x_range"],
                "target_minute": target_minute,
            }
            self._update_resize_preview(target_minute)
            return
        hit = self._hit_test(e.pos())
        if not hit:
            # Empty hour-grid cell: launch AddTodo with the cell's date
            # and hour pre-filled. Only fires for left-button presses on
            # hour-grid cells (not the All Day row, which has its own
            # add path via the dialog's date picker). The signal carries
            # (date, hour) so the main window can construct the dialog
            # with the right defaults.
            if e.button() == Qt.MouseButton.LeftButton:
                index = self.indexAt(e.pos())
                if index.isValid():
                    cell_date = index.data(_WEEK_DATE_ROLE)
                    hour = index.data(_WEEK_HOUR_ROLE)
                    if cell_date is not None and hour is not None and hour >= 0:
                        self.add_task_at_requested.emit(cell_date, hour)
            return
        if hit[0] == "task":
            self.task_clicked.emit(hit[1].id)
            if e.button() == Qt.MouseButton.LeftButton:
                self._drag_start_pos = e.pos()
                self._drag_item_id = hit[1].id
                self._drag_item_reminder = getattr(hit[1], "reminder", "") or ""
        elif hit[0] == "more":
            self.more_clicked.emit(hit[1], hit[2])

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        # Commit an in-progress edge resize, if any. Emits task_resized
        # only when the resulting field value differs from the current
        # one (no-op edits don't produce undo entries).
        if self._edge_resize is not None:
            from ...core.calendar_layout import WindowKind  # noqa: F401

            state = self._edge_resize
            self._hide_resize_preview()
            self._edge_resize = None
            change = self._minute_to_field_change(
                state["edge"],
                state["kind"],
                state["item"],
                state["target_minute"],
            )
            if change is not None:
                field_name, new_value = change
                self.task_resized.emit(state["item_id"], field_name, new_value)
            super().mouseReleaseEvent(e)
            return
        self._drag_start_pos = None
        self._drag_item_id = None
        self._drag_item_reminder = ""
        self._dragging = False
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if e is None:
            return
        # Active edge resize — update the snap target and preview.
        # Holding Shift disengages the 15-minute snap so the user can
        # land on any minute. The resize commits on mouseReleaseEvent.
        if self._edge_resize is not None:
            slot_left, slot_right = self._edge_resize["slot_x_range"]
            x_for_column = max(slot_left, min(slot_right, e.pos().x()))
            raw_minute, _td = self._y_to_minute_of_day(e.pos().y(), x_for_column)
            if raw_minute is None:
                return
            fine = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            snapped = self._snap_minute(raw_minute, fine)
            self._edge_resize["target_minute"] = snapped
            self._update_resize_preview(snapped)
            return
        # Drag initiation
        if (
            not self._dragging
            and self._drag_start_pos is not None
            and self._drag_item_id is not None
            and (e.pos() - self._drag_start_pos).manhattanLength()
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
            pm = _make_drag_pixmap(self._drag_item_reminder)
            drag.setPixmap(pm)
            drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
            drag.exec(Qt.DropAction.MoveAction)
            self._drag_start_pos = None
            self._drag_item_id = None
            self._drag_item_reminder = ""
            self._dragging = False
            return
        # Hover affordance for the edge-drag-to-resize interaction (#18).
        # When the cursor is within _EDGE_HIT_PIXELS of a draggable
        # bar edge, switch to vertical-resize so the user discovers
        # the interaction without needing tooltip text. Cursor falls
        # back to the table's default when not over an edge.
        edge_hit = self._hit_test_edge(e.pos())
        viewport = self.viewport()
        if edge_hit is not None:
            if viewport is not None:
                viewport.setCursor(Qt.CursorShape.SizeVerCursor)
            # Suppress the bar tooltip while the cursor is on an edge
            # so the affordance reads cleanly.
            self._tooltip_label.hide()
            self._tooltip_item_id = None
            self._hover_add_btn.hide_smoothly()
            return
        # Hover "+" affordance — universal add-task button for hour-grid
        # cells regardless of whether the cell already contains bars.
        # Positioned at the cell's center; slides between cells as the
        # cursor moves so the affordance follows naturally without
        # flickering. All-Day row, agenda row, and any non-hour-grid
        # surface skip the button.
        index = self.indexAt(e.pos())
        cell_date = index.data(_WEEK_DATE_ROLE) if index.isValid() else None
        hour = index.data(_WEEK_HOUR_ROLE) if index.isValid() else None
        if cell_date is not None and hour is not None and hour >= 0:
            rect = self.visualRect(index)
            center = rect.center()
            # Center the 36 px button on the cell center.
            top_left = QPoint(
                center.x() - self._hover_add_btn.width() // 2,
                center.y() - self._hover_add_btn.height() // 2,
            )
            self._hover_add_btn.show_at(top_left, cell_date, hour)
        else:
            self._hover_add_btn.hide_smoothly()
        # Tooltip handling — uses a persistent QLabel instead of
        # QToolTip.showText() so viewport repaints from the now-timer
        # don't dismiss it prematurely. When the cursor is within the
        # "+" hover button's geometry, the button's own tooltip ("Add
        # task on …") wins — we suppress the persistent task tooltip
        # entirely to prevent two tooltips rendering on top of each
        # other. Geometry check (rather than relying on the button's
        # enterEvent) handles the case where the button appears under
        # a stationary cursor: enterEvent doesn't fire when the widget
        # moves under the cursor, only when the cursor moves into the
        # widget's bounds.
        cursor_on_add_btn = (
            self._hover_add_btn.isVisible() and self._hover_add_btn.geometry().contains(e.pos())
        )
        hit = self._hit_test(e.pos())
        if cursor_on_add_btn:
            self._tooltip_label.hide()
            self._tooltip_item_id = None
            if viewport is not None:
                viewport.unsetCursor()
        elif hit and hit[0] == "task":
            if viewport is not None:
                viewport.unsetCursor()
            item = hit[1]
            item_id = getattr(item, "id", None)
            if item_id != self._tooltip_item_id:
                self._tooltip_item_id = item_id
                self._tooltip_label.setText(self._build_bar_tooltip(item))
                self._tooltip_label.adjustSize()
            cursor = e.globalPosition().toPoint()
            self._tooltip_label.move(cursor.x() + 16, cursor.y() + 8)
            self._tooltip_label.show()
        else:
            self._tooltip_label.hide()
            self._tooltip_item_id = None
            if viewport is not None:
                viewport.unsetCursor()

    @staticmethod
    def _build_bar_tooltip(item) -> str:
        """Build the comprehensive rich-text tooltip for a calendar bar.

        Uses the shared build_rich_tooltip from core.models which shows
        every field that affects the task's visual representation. The
        calendar passes the current BarState's legend label so the tooltip
        reinforces the bar's color with a readable name — the WCAG 1.4.1
        redundancy channel for users who can't easily distinguish the
        legend's two greens (In progress vs Completed).
        """
        from datetime import datetime

        from ...core.calendar_layout import compute_bar_state, compute_bar_window
        from ...core.models import build_rich_tooltip
        from ...gui.styles.themes import get_colors

        window = compute_bar_window(item)
        status_label: str | None = None
        if window is not None:
            state = compute_bar_state(item, window, datetime.now())
            status_label = bar_state_label(state)
        return build_rich_tooltip(item, status_label=status_label, theme_colors=get_colors())

    def leaveEvent(self, a0) -> None:  # noqa: N802
        self._tooltip_label.hide()
        self._tooltip_item_id = None
        self._hover_add_btn.hide_smoothly()
        super().leaveEvent(a0)

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        if e is None:
            return
        self._tooltip_label.hide()
        hit = self._hit_test(e.pos())
        if hit and hit[0] == "task":
            self.task_double_clicked.emit(hit[1].id)

    def contextMenuEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        self._tooltip_label.hide()
        hit = self._hit_test(a0.pos())
        if hit and hit[0] == "task":
            self.task_clicked.emit(hit[1].id)
            self.task_right_clicked.emit(hit[1].id, a0.globalPos())
        else:
            super().contextMenuEvent(a0)

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e is None:
            return
        mime = e.mimeData()
        if mime and mime.hasFormat("application/x-pytodo-item-id"):
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:  # noqa: N802
        if e is None:
            return
        mime = e.mimeData()
        if not (mime and mime.hasFormat("application/x-pytodo-item-id")):
            return
        e.acceptProposedAction()
        index = self.indexAt(e.position().toPoint())
        target_date = index.data(_WEEK_DATE_ROLE) if index.isValid() else None
        target_hour = index.data(_WEEK_HOUR_ROLE) if index.isValid() else None
        if target_date is not None and target_hour is not None:
            self._drop_highlight.setGeometry(self.visualRect(index))
            self._drop_highlight.show()
            self._drop_highlight.raise_()
            self._drag_preview_label.setText(_format_drop_target(target_date, int(target_hour)))
            self._drag_preview_label.adjustSize()
            cursor = e.position().toPoint()
            viewport = self.viewport()
            assert viewport is not None
            global_cursor = viewport.mapToGlobal(cursor)
            self._drag_preview_label.move(global_cursor.x() + 18, global_cursor.y() + 12)
            self._drag_preview_label.show()
        else:
            self._drop_highlight.hide()
            self._drag_preview_label.hide()

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._drop_highlight.hide()
        self._drag_preview_label.hide()
        super().dragLeaveEvent(e)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._drop_highlight.hide()
        self._drag_preview_label.hide()
        if event is None:
            return
        mime = event.mimeData()
        if mime is None or not mime.hasFormat("application/x-pytodo-item-id"):
            return
        item_id_str = bytes(mime.data("application/x-pytodo-item-id")).decode()  # type: ignore[arg-type]
        index = self.indexAt(event.position().toPoint())
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
        # hour = -1 means all-day (no time); otherwise the target due_time
        # is the END of the hour block, matching the convention that
        # due_time is a deadline. The MainWindow drop handler applies a
        # forward-clamp so the computed window origin is never before now.
        from datetime import time as _time

        if target_hour < 0:
            target_time = None
        elif target_hour >= 23:
            target_time = _time(23, 59)
        else:
            target_time = _time(target_hour + 1, 0)
        self.task_dropped.emit(item_id, target_date, target_time)
        event.acceptProposedAction()


def _format_drop_target(target_date: date, target_hour: int) -> str:
    """Format the floating drag preview label text for week/day view drops.

    `target_hour == -1` is the all-day row sentinel. Regular hours
    render as 12-hour clock with AM/PM so the tooltip matches the
    conventions used elsewhere in the calendar.
    """
    day = target_date.strftime("%a %b %d")
    if target_hour < 0:
        return f"{day}  \u00b7  All day"
    if target_hour == 0:
        time_str = "12:00 AM"
    elif target_hour < 12:
        time_str = f"{target_hour}:00 AM"
    elif target_hour == 12:
        time_str = "12:00 PM"
    else:
        time_str = f"{target_hour - 12}:00 PM"
    return f"{day}  \u00b7  {time_str}"


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

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e is not None and e.button() == Qt.MouseButton.LeftButton:
            self._drag_start = e.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, a0) -> None:  # noqa: N802
        if (
            a0 is not None
            and self._drag_start is not None
            and (a0.pos() - self._drag_start).manhattanLength() >= QApplication.startDragDistance()
        ):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(str(self._item_id))
            mime.setData("application/x-pytodo-item-id", str(self._item_id).encode())
            drag.setMimeData(mime)
            # Use the button's own appearance as the drag pixmap so
            # the cursor carries an exact preview of what the user
            # grabbed. The hotspot stays at the press position so
            # the pixmap doesn't jump under the cursor.
            pm = self.grab()
            drag.setPixmap(pm)
            drag.setHotSpot(self._drag_start)
            drag.exec(Qt.DropAction.MoveAction)
            self._drag_start = None
        else:
            super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag_start = None
        super().mouseReleaseEvent(e)


class _UnscheduledPanel(QFrame):
    """Sidebar showing tasks without due dates.

    Accepts item-id drops from the calendar grid so a scheduled task
    can be demoted back to unscheduled — the reverse of the drop
    that schedules an unscheduled task by placing it in a cell. The
    drop is translated by the parent CalendarViewWidget into an
    EditDueDateCommand with a null due_date, which also clears
    due_time, so undo/redo round-trips the change cleanly.
    """

    task_clicked = pyqtSignal(object)  # item_id
    task_double_clicked = pyqtSignal(object)  # item_id
    task_dropped_to_unscheduled = pyqtSignal(object)  # item_id (UUID)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(200)
        self._default_style = "QFrame { border-left: 1px solid palette(mid); }"
        self._drag_over_style = (
            "QFrame { border-left: 1px solid palette(mid);"
            " background-color: palette(alternate-base); }"
        )
        self.setStyleSheet(self._default_style)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header = QLabel(self.tr("Unscheduled"))
        header.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(header)

        self._count_label = QLabel(self.tr("0 tasks"))
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

    # ------------------------------------------------------------------
    # Drag-and-drop: accept item-id drops to unschedule a scheduled task
    # ------------------------------------------------------------------

    def dragEnterEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        mime = a0.mimeData()
        if mime is not None and mime.hasFormat("application/x-pytodo-item-id"):
            a0.acceptProposedAction()
            self.setStyleSheet(self._drag_over_style)

    def dragMoveEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        mime = a0.mimeData()
        if mime is not None and mime.hasFormat("application/x-pytodo-item-id"):
            a0.acceptProposedAction()

    def dragLeaveEvent(self, a0) -> None:  # noqa: N802
        self.setStyleSheet(self._default_style)
        if a0 is not None:
            a0.accept()

    def dropEvent(self, a0) -> None:  # noqa: N802
        self.setStyleSheet(self._default_style)
        if a0 is None:
            return
        mime = a0.mimeData()
        if mime is None or not mime.hasFormat("application/x-pytodo-item-id"):
            return
        item_id_str = bytes(mime.data("application/x-pytodo-item-id")).decode()  # type: ignore[arg-type]
        try:
            item_id = UUID(item_id_str)
        except ValueError:
            return
        self.task_dropped_to_unscheduled.emit(item_id)
        a0.acceptProposedAction()

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
        self._count_label.setText(self.tr(f"{n} task{'s' if n != 1 else ''}"))


# ---------------------------------------------------------------------------
# Calendar legend — explains the bar color palette to users
# ---------------------------------------------------------------------------


class _CalendarLegend(QWidget):
    """Compact horizontal legend showing each BarState color with its label.

    Displayed in week/day views so users know what the bar colors mean.
    Refreshes automatically on theme change.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6, 2, 6, 2)
        self._layout.setSpacing(10)
        self._swatches: list[QWidget] = []
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the legend from the current theme's bar palette."""
        from ...core.bar_palette import get_palette
        from ...core.calendar_layout import BarState
        from ...gui.styles.themes import Theme, get_current_theme

        # Clear existing content
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._swatches.clear()

        theme_name = "dark" if get_current_theme() == Theme.DARK else "light"
        palette = get_palette(theme_name)

        legend_entries = [
            BarState.FUTURE,
            BarState.IN_WORK_WINDOW,
            BarState.DUE_NOW,
            BarState.OVERDUE_ACTIVE,
            BarState.COMPLETED_ONTIME,
        ]

        # "Legend:" prefix
        prefix = QLabel(self.tr("Legend:"))
        prefix.setStyleSheet("QLabel { color: palette(text); font-size: 11px; font-weight: bold; }")
        self._layout.addWidget(prefix)

        # Swatches are sized for WCAG 1.4.11 legibility — the prior 14x12 was
        # too small for the two greens (IN_WORK_WINDOW vs COMPLETED_*) to read
        # as distinct at a glance. 20x16 lands in the Material Design status-
        # chip range while still fitting the 28px-tall legend strip.
        for state in legend_entries:
            colors = palette[state]
            swatch = QLabel()
            swatch.setFixedSize(20, 16)
            swatch.setStyleSheet(
                f"QLabel {{ background-color: {colors.base}; "
                f"border: 1px solid {QColor(colors.base).darker(130).name()}; "
                f"border-radius: 3px; }}"
            )
            self._layout.addWidget(swatch)
            text_label = QLabel(bar_state_label(state))
            text_label.setStyleSheet("QLabel { color: palette(text); font-size: 11px; }")
            self._layout.addWidget(text_label)
            self._swatches.append(swatch)

        # Spacer between lifecycle states and deviation markers
        spacer = QLabel("  |  ")
        spacer.setStyleSheet("QLabel { color: palette(mid); font-size: 10px; }")
        self._layout.addWidget(spacer)

        # Deviation indicators — using the COMPLETED_EARLY and COMPLETED_LATE
        # deviation colors to show the two-zone concept.
        early_colors = palette[BarState.COMPLETED_EARLY]
        early_swatch = QLabel()
        early_swatch.setFixedSize(20, 16)
        early_swatch_color = QColor(early_colors.deviation)
        early_swatch_color.setAlpha(150)
        early_swatch.setStyleSheet(
            f"QLabel {{ background-color: rgba("
            f"{early_swatch_color.red()},"
            f"{early_swatch_color.green()},"
            f"{early_swatch_color.blue()},"
            f"{early_swatch_color.alpha()}); "
            f"border: 1px solid {QColor(early_colors.deviation).darker(130).name()}; "
            f"border-radius: 2px; }}"
        )
        self._layout.addWidget(early_swatch)
        early_label = QLabel(self.tr("Early surplus"))
        early_label.setStyleSheet("QLabel { color: palette(text); font-size: 10px; }")
        self._layout.addWidget(early_label)

        late_colors = palette[BarState.COMPLETED_LATE]
        late_swatch = QLabel()
        late_swatch.setFixedSize(20, 16)
        late_swatch.setStyleSheet(
            f"QLabel {{ background-color: {late_colors.deviation}; "
            f"border: 1px solid {QColor(late_colors.deviation).darker(130).name()}; "
            f"border-radius: 2px; }}"
        )
        self._layout.addWidget(late_swatch)
        late_label = QLabel(self.tr("Late overflow"))
        late_label.setStyleSheet("QLabel { color: palette(text); font-size: 10px; }")
        self._layout.addWidget(late_label)

        # Separator before the now-line indicator
        spacer2 = QLabel("  |  ")
        spacer2.setStyleSheet("QLabel { color: palette(mid); font-size: 10px; }")
        self._layout.addWidget(spacer2)

        # Now-line indicator — a small horizontal red line swatch matching
        # the actual now line drawn in the hour grid.
        now_color = palette[BarState.OVERDUE_ACTIVE].base  # same color as the line
        now_swatch = QLabel()
        now_swatch.setFixedSize(20, 16)
        # Two-pixel horizontal line centered vertically in the swatch,
        # matching the look of the actual now line drawn by _paint_now_line.
        now_swatch.setStyleSheet(
            "QLabel { "
            "background-color: transparent; "
            "border-top: 5px solid transparent; "
            "border-bottom: 5px solid transparent; "
            "border-image: none; "
            "}"
        )
        # Override with a direct linear-gradient-like fill simulating a line
        now_swatch.setStyleSheet(
            f"QLabel {{ "
            f"background: qlineargradient("
            f"x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 transparent, "
            f"stop:0.4 transparent, "
            f"stop:0.45 {now_color}, "
            f"stop:0.55 {now_color}, "
            f"stop:0.6 transparent, "
            f"stop:1 transparent); "
            f"}}"
        )
        self._layout.addWidget(now_swatch)
        now_label = QLabel(self.tr("Now"))
        now_label.setStyleSheet("QLabel { color: palette(text); font-size: 10px; }")
        self._layout.addWidget(now_label)
        self._swatches.append(now_swatch)

        self._layout.addStretch()


# ---------------------------------------------------------------------------
# Pinned All Day row container
# ---------------------------------------------------------------------------


# Visible gap between the all-day band and the timed-hour grid. The
# two surfaces are conceptually different — fixed top band for
# undated/full-day tasks vs. scrolling chronological grid for timed
# tasks — and the gap communicates that separation. Same pixel size
# in both day and week views (structural separator, not a margin).
_ALL_DAY_TO_GRID_GAP = 14

# Padding around the "All Day" label in the vertical header. Total
# header width is computed at runtime from fontMetrics so the label
# never clips on any platform/DPI combination.
_ALL_DAY_LABEL_PADDING = 24

# Fixed baseline height for the all-day row's content area, applied
# identically in day and week views. Day view's hour-grid uses a
# larger row size for detail (see CalendarViewWidget.__init__), but
# the all-day row stays on this shared baseline so the band looks
# pixel-identical above the hour grid no matter which view is active.
# Comparable in size to a typical hour row; chip overflow beyond what
# fits in the row falls through to the delegate's existing "+N more"
# indicator.
_ALL_DAY_ROW_HEIGHT = 60


class _AllDayTableView(_WeekTableView):
    """All-day band: a single visible row pinned to a fixed baseline
    height shared across day and week views.

    _WeekTableView's resizeEvent distributes the viewport equally across
    all 25 rows in the model, which works for the hour grid (where 24
    rows are visible) but produces a microscopic row height on the
    all-day band (which only shows row 0 in a fixed-height area). This
    subclass overrides resize so row 0 always uses the shared baseline
    `_ALL_DAY_ROW_HEIGHT`. Day view's larger hour-grid row size is
    intentionally not propagated here so the all-day band looks
    pixel-identical no matter which view is active.
    """

    def resizeEvent(self, e) -> None:  # noqa: N802
        QTableView.resizeEvent(self, e)
        self._apply_row_height()

    def _apply_row_height(self) -> None:
        model = self.model()
        if model is None:
            return
        for row in range(model.rowCount()):
            self.setRowHeight(row, _ALL_DAY_ROW_HEIGHT)


class _PinnedWeekContainer(QWidget):
    """Stacks an all-day band above an hour-grid table with a visible gap.

    Both inner tables share the same _WeekModel and _WeekDelegate. The
    all-day table hides rows 1-24 (showing only row 0); the hour-grid
    table hides row 0 (showing only the scrollable hours). Horizontal
    scroll positions are kept in sync so columns stay aligned.

    The all-day band's row height mirrors the hour grid's per-row
    height — when the user resizes the window and the hour grid's rows
    grow or shrink, the all-day row tracks them so the two surfaces
    always present rows of the same vertical size. Overflow chips
    beyond what fits in the single row use the delegate's existing
    "+N more" indicator. The band itself never scrolls.
    """

    def __init__(
        self,
        model: _WeekModel,
        delegate: _WeekDelegate,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        from PyQt6.QtWidgets import QHeaderView, QStyle

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_ALL_DAY_TO_GRID_GAP)

        # Vertical header width — computed from "All Day" font metrics
        # plus padding so the label never clips on any platform/DPI.
        # The previous magic number (72 px) clipped on Linux at HiDPI.
        fm = self.fontMetrics()
        self._shared_v_header_width = fm.horizontalAdvance("All Day") + _ALL_DAY_LABEL_PADDING
        style = self.style()
        assert style is not None
        self._scrollbar_width = style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)

        # All Day pinned band — shows row 0 only. This is the ONLY
        # table that shows the horizontal day header; the hour-grid's
        # header is hidden so users see a single day header above the
        # all-day band.
        self.all_day_table = _AllDayTableView()
        self.all_day_table.setModel(model)
        self.all_day_table.setItemDelegate(delegate)
        v_header = self.all_day_table.verticalHeader()
        if v_header is not None:
            for source_row in range(1, 25):
                v_header.hideSection(source_row)
            v_header.setFixedWidth(self._shared_v_header_width)
        self.all_day_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.all_day_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.all_day_table)

        # Hour grid table — shows rows 1-24 only, hides the horizontal
        # day header.
        self.hour_grid_table = _WeekTableView()
        self.hour_grid_table.setModel(model)
        self.hour_grid_table.setItemDelegate(delegate)
        v_header_h = self.hour_grid_table.verticalHeader()
        if v_header_h is not None:
            v_header_h.hideSection(0)
            v_header_h.setFixedWidth(self._shared_v_header_width)
        h_header_hg = self.hour_grid_table.horizontalHeader()
        if h_header_hg is not None:
            h_header_hg.setVisible(False)
        layout.addWidget(self.hour_grid_table, 1)

        # Both tables use Fixed resize mode with manually-computed
        # widths (see resizeEvent). This gives exact column alignment
        # regardless of scrollbar reservations, which Stretch mode
        # cannot guarantee because the all-day table has no vertical
        # scrollbar reservation while the hour grid does.
        ad_hh = self.all_day_table.horizontalHeader()
        hg_hh = self.hour_grid_table.horizontalHeader()
        if ad_hh is not None:
            ad_hh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        if hg_hh is not None:
            hg_hh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        # Horizontal scroll synchronization (narrow-window case).
        self._syncing_hscroll = False
        all_day_hbar = self.all_day_table.horizontalScrollBar()
        hour_grid_hbar = self.hour_grid_table.horizontalScrollBar()
        if all_day_hbar is not None and hour_grid_hbar is not None:
            all_day_hbar.valueChanged.connect(self._on_all_day_hscroll)
            hour_grid_hbar.valueChanged.connect(self._on_hour_grid_hscroll)

    def _on_all_day_hscroll(self, value: int) -> None:
        if self._syncing_hscroll:
            return
        self._syncing_hscroll = True
        try:
            hbar = self.hour_grid_table.horizontalScrollBar()
            if hbar is not None:
                hbar.setValue(value)
        finally:
            self._syncing_hscroll = False

    def _on_hour_grid_hscroll(self, value: int) -> None:
        if self._syncing_hscroll:
            return
        self._syncing_hscroll = True
        try:
            hbar = self.all_day_table.horizontalScrollBar()
            if hbar is not None:
                hbar.setValue(value)
        finally:
            self._syncing_hscroll = False

    def resizeEvent(self, a0) -> None:  # noqa: N802
        """Compute matching column widths for both inner tables on resize,
        then size the all-day band's table to fit its fixed baseline row
        plus the horizontal day header.

        Uses Fixed resize mode with manual widths so column alignment is
        exact regardless of scrollbar reservations. The authoritative
        viewport width is the hour grid's (which reserves vertical
        scrollbar space) minus its vertical header — divided equally
        across visible columns. Both tables get the same per-column
        width.
        """
        super().resizeEvent(a0)
        self._recompute_column_widths()
        self._size_all_day_table()

    def showEvent(self, a0) -> None:  # noqa: N802
        super().showEvent(a0)
        self._recompute_column_widths()
        self._size_all_day_table()

    def _size_all_day_table(self) -> None:
        """Set the all-day table's total height to fit one shared-baseline
        row plus its horizontal day header. Identical between day and
        week views so the band is pixel-identical above the hour grid
        regardless of view.
        """
        h_header = self.all_day_table.horizontalHeader()
        h_header_height = h_header.height() if h_header is not None else 28
        frame = self.all_day_table.frameWidth() * 2
        self.all_day_table.setFixedHeight(h_header_height + _ALL_DAY_ROW_HEIGHT + frame)

    def _recompute_column_widths(self) -> None:
        model = self.all_day_table.model()
        if model is None:
            return
        col_count = model.columnCount()
        visible_cols = [c for c in range(col_count) if not self.all_day_table.isColumnHidden(c)]
        if not visible_cols:
            return
        # Available width = hour grid viewport width - vertical header
        # - scrollbar width. The hour grid is authoritative because its
        # vertical scrollbar is the one that takes real space.
        total = self.width() - self._shared_v_header_width - self._scrollbar_width
        if total <= 0:
            return
        col_w = total // len(visible_cols)
        remainder = total - (col_w * len(visible_cols))
        # Give the remainder to the first visible column so widths sum
        # exactly to the total (no sub-pixel drift at the right edge).
        for i, col in enumerate(visible_cols):
            w = col_w + (remainder if i == 0 else 0)
            self.all_day_table.setColumnWidth(col, w)
            self.hour_grid_table.setColumnWidth(col, w)

    def hide_columns(self, columns: list[int]) -> None:
        """Hide the same columns in both inner tables (used by day view)."""
        for col in columns:
            self.all_day_table.setColumnHidden(col, True)
            self.hour_grid_table.setColumnHidden(col, True)
        self._recompute_column_widths()

    def update_viewports(self) -> None:
        """Trigger a repaint of both inner tables. Used by the now-tick timer."""
        for table in (self.all_day_table, self.hour_grid_table):
            viewport = table.viewport()
            if viewport is not None:
                viewport.update()

    def connect_task_signals(
        self,
        on_task_clicked,
        on_task_double_clicked,
        on_task_right_clicked,
        on_task_dropped,
        on_more_clicked,
        on_add_task_at_requested=None,
    ) -> None:
        """Wire both inner tables' signals to the same handlers.

        Centralizing the wiring here keeps CalendarViewWidget's setup
        code from having to know about the two-table internal structure.
        """
        for table in (self.all_day_table, self.hour_grid_table):
            table.task_clicked.connect(on_task_clicked)
            table.task_double_clicked.connect(on_task_double_clicked)
            table.task_right_clicked.connect(on_task_right_clicked)
            table.task_dropped.connect(on_task_dropped)
            table.more_clicked.connect(on_more_clicked)
            if on_add_task_at_requested is not None:
                table.add_task_at_requested.connect(on_add_task_at_requested)


# ---------------------------------------------------------------------------
# Schedule / agenda sub-view — chronological scrollable list grouped by day
# ---------------------------------------------------------------------------


class _AgendaRow(QFrame):
    """Single row representing one scheduled item in the agenda list."""

    clicked = pyqtSignal(object)  # (item_id)
    double_clicked = pyqtSignal(object)
    right_clicked = pyqtSignal(object, QPoint)

    def __init__(
        self,
        item: TodoItem,
        time_format: str,
        colors: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._item_id = item.id
        self._colors = colors
        self._selected = False
        self._drag_start_pos: QPoint | None = None
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.right_clicked.emit(self._item_id, self.mapToGlobal(pos))
        )
        self._apply_row_style()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Time / "All Day" — fixed-width column so reminders align. Uses
        # the theme's standard text color (rather than palette(mid))
        # because muted-gray fails WCAG against the dark-theme cell
        # background; the time column carries functional information
        # and must remain legible in either theme.
        if item.due_time is None:
            time_text = self.tr("All Day")
        elif time_format == "24h":
            time_text = item.due_time.strftime("%H:%M")
        else:
            time_text = item.due_time.strftime("%I:%M %p").lstrip("0")
        time_label = QLabel(time_text)
        time_label.setFixedWidth(80)
        time_label.setStyleSheet(f"color: {colors['text']}; font-size: 11px; border: none;")
        layout.addWidget(time_label)

        # Priority dot
        priority_color = {
            1: colors["priority_high"],
            2: colors["priority_normal"],
            3: colors["priority_low"],
        }.get(item.priority, colors["priority_normal"])
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background: {priority_color}; border-radius: 4px; border: none;")
        layout.addWidget(dot)

        # Reminder
        text = item.reminder or self.tr("(no text)")
        reminder_label = QLabel(text)
        reminder_label.setWordWrap(False)
        reminder_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if item.complete:
            reminder_label.setStyleSheet(
                f"color: {colors['completed_text']};"
                " text-decoration: line-through;"
                " font-size: 12px; border: none;"
            )
        else:
            reminder_label.setStyleSheet(f"color: {colors['text']}; font-size: 12px; border: none;")
        layout.addWidget(reminder_label, 1)

        # Tag chips — compact, capped at 3 + overflow count.
        if item.tags:
            shown = item.tags[:3]
            tags_text = " ".join(shown)
            if len(item.tags) > 3:
                tags_text += f" +{len(item.tags) - 3}"
            tag_label = QLabel(tags_text)
            tag_label.setStyleSheet(
                f"color: {colors['entity_tag']}; font-size: 11px; border: none;"
            )
            layout.addWidget(tag_label)

    def set_selected(self, selected: bool) -> None:
        """Toggle the selected visual state. The selected row paints with a
        highlight tint so the user has a visual confirmation that their
        click was registered, separate from the detail panel content
        update on the side."""
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_row_style()

    def _apply_row_style(self) -> None:
        """Apply the row's stylesheet for the current selection state.

        Hover shows a subtle midlight tint; selection shows a stronger
        highlight tint so the row reads as "the one you clicked" without
        competing with the detail panel's own selection indicators.
        """
        if self._selected:
            self.setStyleSheet(
                "_AgendaRow { background: palette(highlight);"
                " border-radius: 4px; border: 1px solid palette(highlight); }"
                "_AgendaRow QLabel { color: palette(highlightedText); }"
            )
        else:
            self.setStyleSheet(
                "_AgendaRow { background: transparent; border-radius: 4px;"
                " border: 1px solid transparent; }"
                "_AgendaRow:hover { background: palette(midlight); }"
            )

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = a0.pos()
            self.clicked.emit(self._item_id)
        super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0) -> None:  # noqa: N802
        # Begin a drag once the cursor has moved past the system's drag
        # threshold while the left button is held. Carries item_id in
        # the same mime format that _AgendaView and _UnscheduledPanel
        # already accept, so the drop side needs no changes.
        if (
            a0 is None
            or self._drag_start_pos is None
            or not (a0.buttons() & Qt.MouseButton.LeftButton)
        ):
            super().mouseMoveEvent(a0)
            return
        if (a0.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(a0)
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-pytodo-item-id", str(self._item_id).encode())
        drag.setMimeData(mime)
        # Drag preview = pixmap of the row itself so the cursor carries
        # a recognizable representation of what's being moved.
        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(self._drag_start_pos)

        self._drag_start_pos = None
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, a0) -> None:  # noqa: N802
        self._drag_start_pos = None
        super().mouseReleaseEvent(a0)

    def mouseDoubleClickEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._item_id)
        super().mouseDoubleClickEvent(a0)


class _AgendaView(QWidget):
    """Chronological scrollable list of scheduled items grouped by day.

    Renders one section per day across a configurable forward-looking
    range starting at `current_date`. Each section has a day-header
    row plus one `_AgendaRow` per scheduled item; days with no items
    show a single muted placeholder so absence is visible. All-day
    items render before timed items within a single day.
    """

    item_clicked = pyqtSignal(object)
    item_double_clicked = pyqtSignal(object)
    item_right_clicked = pyqtSignal(object, QPoint)
    task_dropped = pyqtSignal(object, object)  # (item_id UUID, target_date)

    DEFAULT_DAYS = 30

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[TodoItem] = []
        self._current_date: date = date.today()
        self._time_format: str = "system"
        self._selected_item_id: UUID | None = None
        self._rows_by_id: dict[UUID, _AgendaRow] = {}
        # (date, header_widget) pairs in render order. Drop handling
        # walks this list to map a drop y-coordinate back to the day
        # section the drop landed in.
        self._day_widgets: list[tuple[date, QLabel]] = []
        # Currently-hovered day section during a drag, used by
        # _refresh_day_header_styles to paint a drop-target indicator.
        self._drag_target_date: date | None = None
        self._setup_ui()
        # Accept drops from the unscheduled panel so dragging an
        # unscheduled task into a day grouping schedules it on that day.
        self.setAcceptDrops(True)
        # Selection follows clicks and is repainted across rebuilds so
        # the user's last-clicked row stays visually anchored.
        self.item_clicked.connect(self._on_item_clicked)

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.setSpacing(0)

        scroll.setWidget(self._content)
        outer.addWidget(scroll)

    def set_data(
        self,
        items: list[TodoItem],
        current_date: date,
        time_format: str,
    ) -> None:
        """Bind items, anchor date, and time-format preference."""
        self._items = items
        self._current_date = current_date
        self._time_format = time_format
        self._rebuild()

    def _on_item_clicked(self, item_id: UUID) -> None:
        """Update internal selection state and repaint affected rows."""
        prev = self._selected_item_id
        self._selected_item_id = item_id
        if prev is not None and prev in self._rows_by_id:
            self._rows_by_id[prev].set_selected(False)
        if item_id in self._rows_by_id:
            self._rows_by_id[item_id].set_selected(True)

    def _rebuild(self) -> None:
        # Tear down previous content
        self._rows_by_id = {}
        self._day_widgets = []
        while self._content_layout.count():
            layout_item = self._content_layout.takeAt(0)
            if layout_item is None:
                continue
            w = layout_item.widget()
            if w is not None:
                w.deleteLater()

        from ..styles.themes import get_colors

        colors = get_colors()

        # Group scheduled items by due_date.
        from collections import defaultdict

        by_day: dict[date, list[TodoItem]] = defaultdict(list)
        for item in self._items:
            if item.due_date is not None:
                by_day[item.due_date].append(item)

        # Sort each day: all-day items (no due_time) first, then timed
        # items in chronological order within the day.
        from datetime import time as _time

        for d in by_day:
            by_day[d].sort(key=lambda it: (it.due_time is not None, it.due_time or _time(0, 0)))

        # Render the forward-looking range.
        end = self._current_date + timedelta(days=self.DEFAULT_DAYS)
        d = self._current_date
        while d < end:
            self._add_day_header(d, colors)
            day_items = by_day.get(d, [])
            if day_items:
                for item in day_items:
                    self._add_row(item, colors)
            else:
                self._add_empty_placeholder(colors)
            d += timedelta(days=1)

        self._content_layout.addStretch()

    def _add_day_header(self, d: date, colors: dict[str, str]) -> None:
        # Portable date formatting — %-d is POSIX only and rejected on
        # Windows ("Invalid format string"). Compose the day-of-month
        # without leading zero from d.day directly so the same source
        # renders identically across platforms.
        text = f"{d.strftime('%A, %B')} {d.day}, {d.year}"
        if d == date.today():
            text = self.tr("{date} — Today").format(date=text)
        label = QLabel(text)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(13)
        label.setFont(font)
        self._content_layout.addWidget(label)
        # Track this header so drop handling can map a drop y back to
        # the day it landed in. The header is the y-anchor for its
        # day's section: every row that follows belongs to the day
        # whose header sits above it in the layout.
        self._day_widgets.append((d, label))
        # Apply current style (today / drop-target / default).
        self._style_day_header(d, label)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {colors['border']}; margin: 0 4px 4px 4px;")
        self._content_layout.addWidget(line)

    def _add_row(self, item: TodoItem, colors: dict[str, str]) -> None:
        row = _AgendaRow(item, self._time_format, colors, parent=self._content)
        row.clicked.connect(self.item_clicked.emit)
        row.double_clicked.connect(self.item_double_clicked.emit)
        row.right_clicked.connect(self.item_right_clicked.emit)
        # Re-apply selection state across rebuilds so a refresh doesn't
        # silently drop the user's last-clicked anchor.
        if item.id == self._selected_item_id:
            row.set_selected(True)
        self._rows_by_id[item.id] = row
        self._content_layout.addWidget(row)

    def _add_empty_placeholder(self, colors: dict[str, str]) -> None:
        label = QLabel(self.tr("(no scheduled items)"))
        label.setStyleSheet(
            f"color: {colors['completed_text']}; font-style: italic; padding: 4px 16px;"
        )
        self._content_layout.addWidget(label)

    def _style_day_header(self, d: date, label: QLabel) -> None:
        """Paint a single day-section header with the right styling for
        today / drop-target / default state.

        Today is colored with the highlight tone so it stands out in
        a long forward-looking range. The current drop target during a
        drag carries a tinted background so users see exactly which
        day will receive the drop.
        """
        from ..styles.themes import get_colors

        colors = get_colors()
        is_today = d == date.today()
        is_target = d == self._drag_target_date
        text_color = colors["highlight"] if is_today else colors["text"]
        if is_target:
            label.setStyleSheet(
                f"color: {text_color}; background: {colors['highlight']};"
                " border-radius: 4px; padding: 12px 4px 4px 4px;"
            )
        else:
            label.setStyleSheet(f"color: {text_color}; padding: 12px 4px 4px 4px;")

    def _refresh_day_header_styles(self) -> None:
        """Re-apply styling on every day-section header. Used during a
        drag to repaint the previous and current drop-target headers.
        """
        for d, label in self._day_widgets:
            if label is not None:
                self._style_day_header(d, label)

    # ------------------------------------------------------------------
    # Drag-and-drop — accept drops from any agenda row or the
    # unscheduled panel; emit task_dropped with the target date so the
    # parent can route through EditDueDateCommand (which preserves
    # due_time on a date-only change, satisfying the cross-day
    # time-preservation rule).
    # ------------------------------------------------------------------

    def _date_at_y(self, y: int) -> date | None:
        """Map a y-coordinate (in this view's local frame) back to the
        day section that contains it.

        Walks the recorded (date, header_widget) pairs and picks the
        latest header whose top is at or above the drop y in this
        widget's coordinate space. Returns None when the view is empty
        or the drop falls above every section header.
        """
        if not self._day_widgets:
            return None
        best: date | None = None
        for d, header in self._day_widgets:
            if header is None:
                continue
            top_left = header.mapTo(self, QPoint(0, 0))
            if top_left.y() <= y:
                best = d
            else:
                break
        return best

    def dragEnterEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        mime = a0.mimeData()
        if mime is not None and mime.hasFormat("application/x-pytodo-item-id"):
            a0.acceptProposedAction()
        else:
            a0.ignore()

    def dragMoveEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        mime = a0.mimeData()
        if mime is None or not mime.hasFormat("application/x-pytodo-item-id"):
            a0.ignore()
            return
        a0.acceptProposedAction()
        # Repaint the day-section header that's currently under the
        # cursor so the user sees the drop target.
        target = self._date_at_y(int(a0.position().y()))
        if target != self._drag_target_date:
            self._drag_target_date = target
            self._refresh_day_header_styles()

    def dragLeaveEvent(self, a0) -> None:  # noqa: N802
        self._drag_target_date = None
        self._refresh_day_header_styles()
        if a0 is not None:
            a0.accept()

    def dropEvent(self, a0) -> None:  # noqa: N802
        # Always clear the drop-target highlight before any early return
        # so a rejected drop does not leave a section painted.
        self._drag_target_date = None
        self._refresh_day_header_styles()
        if a0 is None:
            return
        mime = a0.mimeData()
        if mime is None or not mime.hasFormat("application/x-pytodo-item-id"):
            a0.ignore()
            return
        try:
            item_id_str = bytes(mime.data("application/x-pytodo-item-id")).decode()  # type: ignore[arg-type]
            item_id = UUID(item_id_str)
        except (ValueError, UnicodeDecodeError):
            a0.ignore()
            return
        target_date = self._date_at_y(int(a0.position().y()))
        if target_date is None:
            # Drop landed above the first day header — fall back to the
            # anchor date so the drop still has a sensible result.
            target_date = self._current_date
        a0.acceptProposedAction()
        self.task_dropped.emit(item_id, target_date)


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
    item_due_time_end_changed = pyqtSignal(object, object)
    item_estimated_minutes_changed = pyqtSignal(object, int)
    date_and_time_dropped = pyqtSignal(object, object, object)  # item_id, date, time
    edit_tags_requested = pyqtSignal(object)
    focus_requested = pyqtSignal(object)
    add_subtask_requested = pyqtSignal(object)
    # Click on an empty hour-grid cell — emits (cell_date, hour). The main
    # window opens AddTodoDialog with the cell's date + hour pre-filled.
    add_task_at_requested = pyqtSignal(object, int)
    item_selected = pyqtSignal(object)  # (item_id or None)
    item_edit_requested = pyqtSignal(object)  # (item_id) — open detail panel in edit mode
    toggle_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    edit_recurrence_requested = pyqtSignal()

    SUB_DAY = 0
    SUB_WEEK = 1
    SUB_MONTH = 2
    SUB_AGENDA = 3
    SUB_TIMELINE = 4

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
            "agenda": self.SUB_AGENDA,
        }
        self._sub_view = sub_map.get(saved, self.SUB_WEEK)

        # Load saved timeline sub-view
        tl_sub_map = {
            "tasks": 0,
            "daily": 1,
            "productivity": 2,
            "accuracy": 3,
            "timing": 4,
            "cycle": 5,
        }
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
        for i, label in enumerate(
            [
                self.tr("Day"),
                self.tr("Week"),
                self.tr("Month"),
                self.tr("Agenda"),
                self.tr("Timeline"),
            ]
        ):
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

        self._today_btn = QPushButton(self.tr("Today"))
        self._today_btn.setStyleSheet(
            "QPushButton { border: 1px solid palette(mid); border-radius: 3px;"
            " padding: 3px 10px; font-size: 11px; }"
        )
        self._today_btn.clicked.connect(self._navigate_today)
        top_layout.addWidget(self._today_btn)

        layout.addWidget(top_bar)

        # Legend bar — explains the bar color palette to users. Visible in
        # week/day sub-views, hidden in month/timeline. Initial visibility
        # is set by the first _set_sub_view call below.
        self._legend = _CalendarLegend()
        self._legend.setStyleSheet(
            "QWidget { background: palette(alternate-base); "
            "border-bottom: 1px solid palette(mid); }"
        )
        self._legend.setVisible(self._sub_view in (self.SUB_DAY, self.SUB_WEEK))
        layout.addWidget(self._legend)

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
        for i, label in enumerate(
            [
                self.tr("Tasks"),
                self.tr("Daily"),
                self.tr("Productivity"),
                self.tr("Accuracy"),
                self.tr("Timing"),
                self.tr("Cycle"),
            ]
        ):
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

        # Day view — single-column version of week view with pinned All Day row
        self._day_model = _WeekModel()
        self._day_delegate = _WeekDelegate()
        self._day_container = _PinnedWeekContainer(self._day_model, self._day_delegate)
        # Larger hour slots for day view — more room for detail. Applied
        # ONLY to the hour-grid table so the all-day row stays on the
        # shared 60 px baseline and day/week views match pixel-for-pixel
        # above the hour grid.
        _day_hg_v_header = self._day_container.hour_grid_table.verticalHeader()
        if _day_hg_v_header:
            _day_hg_v_header.setDefaultSectionSize(80)
        # Hide columns 1-6 in both inner tables, show only column 0 (the single day)
        self._day_container.hide_columns(list(range(1, 7)))
        self._day_container.connect_task_signals(
            self._on_task_clicked,
            self._on_task_double_clicked,
            self._on_task_right_clicked,
            self._on_week_task_dropped,
            self._on_more_clicked,
            self._on_add_task_at_requested,
        )
        # Edge-drag-to-resize emits from the hour-grid only (the All Day
        # row has no bars to resize). Wire directly rather than threading
        # an optional through connect_task_signals.
        self._day_container.hour_grid_table.task_resized.connect(self._on_task_resized)
        # Backward-compat references — code that previously did
        # self._day_table.scrollTo(...) etc. now targets the hour-grid
        # table inside the container.
        self._day_table = self._day_container.hour_grid_table
        self._sub_stack.addWidget(self._day_container)  # 0

        # Week view — pinned All Day row over scrollable hour grid
        self._week_model = _WeekModel()
        self._week_delegate = _WeekDelegate()
        self._week_container = _PinnedWeekContainer(self._week_model, self._week_delegate)
        self._week_container.connect_task_signals(
            self._on_task_clicked,
            self._on_task_double_clicked,
            self._on_task_right_clicked,
            self._on_week_task_dropped,
            self._on_more_clicked,
            self._on_add_task_at_requested,
        )
        self._week_container.hour_grid_table.task_resized.connect(self._on_task_resized)
        self._week_table = self._week_container.hour_grid_table
        self._sub_stack.addWidget(self._week_container)  # 1

        # Now-aware repaint timer: every 30 seconds, ask both day and week
        # tables to repaint so the now line creeps and spans shrink as time
        # passes. The delegate paints the indicators directly in cell paint
        # events — no overlay widget, no z-order issues, no model-sync issues.
        from PyQt6.QtCore import QTimer

        self._now_timer = QTimer(self)
        self._now_timer.setInterval(30_000)
        self._now_timer.timeout.connect(self._tick_now_indicators)
        self._now_timer.start()

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

        # [4] Timing — completion-timing horizontal bars
        self._timeline_timing_widget = _TimelineTimingWidget()
        self._timeline_sub_stack.addWidget(self._timeline_timing_widget)  # 4

        # [5] Cycle — created→completed cycle-time stat tiles
        self._timeline_cycle_widget = _TimelineCycleWidget()
        self._timeline_sub_stack.addWidget(self._timeline_cycle_widget)  # 5

        tl_container_layout.addWidget(self._timeline_sub_stack)
        self._timeline_sub_stack.setCurrentIndex(self._tl_sub_view)

        # Agenda — chronological scrollable list grouped by day.
        # Added before Timeline so the QStackedWidget index matches
        # SUB_AGENDA = 3 / SUB_TIMELINE = 4 (agenda is conceptually
        # closer to the spatial calendar views than to the timeline
        # analytics charts and reads more naturally beside Month).
        self._agenda_view = _AgendaView()
        self._agenda_view.item_clicked.connect(self._on_task_clicked)
        self._agenda_view.item_double_clicked.connect(self._on_task_double_clicked)
        self._agenda_view.item_right_clicked.connect(self._on_task_right_clicked)
        self._agenda_view.task_dropped.connect(self._on_task_dropped)
        self._sub_stack.addWidget(self._agenda_view)  # 3

        self._sub_stack.addWidget(self._timeline_container)  # 4

        self._sub_stack.setCurrentIndex(self._sub_view)
        content.addWidget(self._sub_stack, 1)

        # Unscheduled panel
        self._unscheduled = _UnscheduledPanel()
        self._unscheduled.task_dropped_to_unscheduled.connect(self._on_task_dropped_to_unscheduled)
        content.addWidget(self._unscheduled)

        layout.addLayout(content, 1)

        self._update_nav_label()

        # Initial stack position — use the saved sub-view directly
        # without going through _set_sub_view (which has side effects
        # like writing to config and calling refresh before the
        # widget's set_list() has run).
        self._sub_stack.setCurrentIndex(self._sub_view)
        self._initial_scroll_done = False

    def showEvent(self, a0) -> None:  # noqa: N802
        """Scroll to the current hour the first time the widget is shown.

        Calling _set_sub_view in __init__ doesn't reliably scroll because
        the table viewport hasn't been laid out yet — scrollTo computes
        positions from rendered geometry. We defer the initial scroll
        to the first showEvent (when the widget is being painted for
        real) and use a one-shot QTimer to ensure the scroll happens
        AFTER the layout pass completes.
        """
        super().showEvent(a0)
        if not self._initial_scroll_done:
            self._initial_scroll_done = True
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(0, self._scroll_to_current_hour)

    def _scroll_to_current_hour(self) -> None:
        """Scroll the active sub-view to put the current hour in view.

        Used for the initial scroll on first show, and also called by
        _set_sub_view when the user switches between day/week views so
        the active grid is always centered on now.
        """
        from datetime import datetime as _dt

        current_hour = _dt.now().hour
        target_row = current_hour + 1  # row 0 = All Day, row N = hour N-1

        if self._sub_view == self.SUB_DAY:
            index = self._day_model.index(target_row, 0)
            self._day_table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        elif self._sub_view == self.SUB_WEEK:
            index = self._week_model.index(target_row, 0)
            self._week_table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

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
        self._timeline_timing_widget.set_analytics(analytics)
        self._timeline_cycle_widget.set_analytics(analytics)

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
        # Refresh delegate colors first so painting uses up-to-date theme
        self._cal_delegate._refresh_colors()
        self._week_delegate._refresh_colors()
        self._day_delegate._refresh_colors()

        self._close_popover()
        if self._todo_list is None:
            self._cal_model.set_items({})
            self._week_model.set_items({})
            self._day_model.set_items({})
            self._unscheduled.set_items([])
            return

        # Calendar views (month, week, day) and the unscheduled sidebar
        # render top-level items only. Subtasks are reachable — and
        # fully editable — through their parent task's detail panel,
        # where the CRUD affordances already live. Rendering subtasks
        # as first-class entries in calendar cells or in the
        # unscheduled sidebar creates confusion about whose deadline
        # is whose (a subtask bar floating in an earlier time bucket
        # than its parent reads as an unrelated top-level task) and
        # isn't necessary for their discoverability.
        all_items = list(self._todo_list.active_items())
        all_items = self._apply_filter(all_items)
        top_level = [i for i in all_items if i.parent_id is None]

        scheduled_real: dict[date, list] = {}
        unscheduled: list = []
        for item in top_level:
            if item.due_date:
                scheduled_real.setdefault(item.due_date, []).append(item)
            else:
                unscheduled.append(item)

        # Build a SEPARATE scheduled dict for week/day views with
        # recurrence projections layered in. The month view explicitly
        # uses scheduled_real (no projections) so it stays clean.
        scheduled_with_projections: dict[date, list] = {
            d: list(items) for d, items in scheduled_real.items()
        }
        self._project_recurrences_into(scheduled_with_projections)
        # Cross-midnight spill: a task whose bar window spans multiple
        # days must appear in EVERY day's bucket the window touches,
        # not just its due_date bucket. Without this, a 23:30+60min
        # task's 00:00-00:30 tail is invisible on the next day's hour
        # grid (the next day's cells only look up items keyed on that
        # day). Applies to both real items and projections.
        self._spill_cross_midnight(scheduled_with_projections)

        sort_key = lambda i: (  # noqa: E731
            i.complete,
            i.priority,
            i.due_time.hour * 60 + i.due_time.minute if i.due_time else 9999,
            i.reminder.lower(),
        )
        for d in scheduled_real:
            scheduled_real[d].sort(key=sort_key)
        for d in scheduled_with_projections:
            scheduled_with_projections[d].sort(key=sort_key)

        # Month view: uses real scheduled (no projections).
        self._cal_model.set_items(scheduled_real)
        self._cal_model.set_month(self._current_date.year, self._current_date.month)
        self._cal_delegate._today = date.today()
        self._cal_delegate._todo_list = self._todo_list

        # Week view: uses projections so future occurrences are visible.
        self._week_model.set_items(scheduled_with_projections)
        self._week_model.set_week(self._current_date)
        # Q6: collect overdue markers for every visible day in the
        # week. Source items are top_level (subtasks never appear in
        # the calendar grid). Real items only — not projections —
        # because projections represent FUTURE occurrences and a
        # future occurrence can't be "overdue" yet.
        now = datetime.now()
        week_dates_for_markers = self._week_model.week_dates()
        week_markers = _collect_markers_for_dates(top_level, week_dates_for_markers, now)
        self._week_model.set_markers(week_markers)
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

        # Day view — uses projections too. Single day from a 7-row
        # model with 1 visible column starting at current_date.
        self._day_model.set_items(scheduled_with_projections)
        # Create a fake "week" starting from current_date
        self._day_model._set_week(self._current_date)
        # Shift so column 0 is the target date
        self._day_model._week_dates = [self._current_date] + [
            self._current_date + timedelta(days=i) for i in range(1, 7)
        ]
        # Q6 markers for the day view's visible date (only column 0
        # is shown but markers must still be computed for it).
        day_markers = _collect_markers_for_dates(top_level, self._day_model._week_dates, now)
        self._day_model.set_markers(day_markers)
        self._day_model.layoutChanged.emit()
        self._day_delegate._today = date.today()
        # Update header to show the day name
        h_header = self._day_table.horizontalHeader()
        if h_header:
            h_header.hide()  # Single column doesn't need day header

        # Timeline view — top-level items, used for the Gantt chart.
        # Reuse the already-computed top_level list.
        self._timeline_tasks_widget.set_data(top_level, self._current_date, self._todo_list)

        # Refresh active timeline sub-view (Daily/Productivity/Accuracy)
        if self._sub_view == self.SUB_TIMELINE and self._tl_sub_view > 0:
            self._refresh_timeline_sub_view()

        # Agenda — top-level items only, real schedule (no projections).
        # Time format mirrors what the day/week views use.
        from ...core.config import get_config

        time_format = get_config().appearance.time_format
        agenda_items = [it for it in top_level if it.due_date is not None]
        self._agenda_view.set_data(agenda_items, self._current_date, time_format)

        self._unscheduled.set_items(unscheduled, todo_list=self._todo_list)

    def _spill_cross_midnight(self, scheduled: dict[date, list]) -> None:
        """Add each item to every day its bar window intersects.

        The buckets are keyed by ``item.due_date`` only. A task whose
        window spans midnight (e.g. a 23:30+60min workback that reaches
        00:30 the next day, or a due_time=00:30+60min workback that
        reaches back to 23:30 the previous day) is otherwise invisible
        on every day except its due_date, because the hour-grid cell
        lookup does ``self._items_by_date.get(cell_date, [])``. Mutates
        the dict in place; new buckets are created on demand. Dedup is
        by ``id`` so an item is never added twice to the same day.
        """
        from ...core.calendar_layout import WindowKind, compute_bar_window

        # Snapshot the (date, item) pairs before mutation so we don't
        # iterate over newly-added entries.
        pairs = [(d, item) for d, items in scheduled.items() for item in items]
        for _origin_date, item in pairs:
            window = compute_bar_window(item)
            if window is None or window.kind == WindowKind.ALL_DAY:
                continue
            start_day = window.origin.date()
            end_day = window.end.date()
            if start_day == end_day:
                continue
            # Add to every day the window touches. For windows ending
            # exactly at 00:00 of end_day (conventional hour-grid
            # midnight boundary), end_day is conceptually the same as
            # start_day for most purposes, but _hour_grid_segment's
            # adjustment produces a valid slice at end_day-1 covering
            # the full 24h. We conservatively include end_day in the
            # spill set; if compute_bar_segments returns [] for a cell
            # date it's a no-op.
            day = start_day
            while day <= end_day:
                bucket = scheduled.setdefault(day, [])
                if not any(
                    getattr(existing, "id", None) == getattr(item, "id", None)
                    for existing in bucket
                ):
                    bucket.append(item)
                day = day + timedelta(days=1)

    def _project_recurrences_into(self, scheduled: dict[date, list]) -> None:
        """Project recurring tasks into future date buckets.

        For each recurring task that's currently in the scheduled dict,
        walk forward N days computing its next occurrences and add the
        same item object to each matching future date's bucket. This
        makes recurring tasks visible on their future occurrence dates
        without materializing virtual items in the database.

        The projection horizon is ~42 days (6 weeks) — enough to cover
        the visible range of month view plus navigation to the next
        couple of months without overloading.
        """
        from dateutil.relativedelta import relativedelta

        PROJECTION_DAYS = 42
        today = date.today()
        horizon = today + timedelta(days=PROJECTION_DAYS)

        def next_occurrence(d: date, kind: str, interval: int) -> date | None:
            """Step forward by ONE cycle from `d`. Unlike
            compute_next_due_date which always computes the next
            occurrence FROM TODAY, this advances FROM `d` so we can
            iterate to project arbitrary distance."""
            if interval < 1:
                interval = 1
            if kind == "daily":
                return d + timedelta(days=interval)
            if kind == "weekly":
                return d + timedelta(weeks=interval)
            if kind == "monthly":
                return d + relativedelta(months=interval)
            if kind == "yearly":
                return d + relativedelta(years=interval)
            return None

        # Snapshot the keys because we'll be adding to the dict
        starting_dates = list(scheduled.keys())
        for start_date in starting_dates:
            for item in list(scheduled[start_date]):
                if not item.is_recurring:
                    continue
                if item.recurrence_type is None:
                    continue
                if item.due_date is None:
                    continue
                current = item.due_date
                safety_counter = 0
                while safety_counter < PROJECTION_DAYS + 10:
                    safety_counter += 1
                    next_due = next_occurrence(
                        current, item.recurrence_type, item.recurrence_interval
                    )
                    if next_due is None or next_due > horizon:
                        break
                    if item.recurrence_end_date is not None and next_due > item.recurrence_end_date:
                        break
                    # `recurrence_end_count` parity with the model layer:
                    # `cycle_completed_recurring` and `auto_advance_overdue_recurring`
                    # both stop touching the template's due_date once
                    # `recurrence_count >= recurrence_end_count`, so the
                    # template stays pinned on its last real due_date
                    # forever. Without this matching check here, the
                    # projection loop kept emitting `_ProjectedItem`
                    # proxies into every visible day past that pinned
                    # date — phantom cells of a recurrence that has
                    # officially ended. The phantoms rendered as
                    # OVERDUE / FUTURE bars, shared the template's
                    # `id`, and made the calendar look like the task
                    # was still active when the model knew it wasn't.
                    if (
                        item.recurrence_end_count is not None
                        and item.recurrence_count >= item.recurrence_end_count
                    ):
                        break
                    bucket = scheduled.setdefault(next_due, [])
                    # Wrap as _ProjectedItem so compute_bar_window sees
                    # the projected date as due_date and produces a fresh
                    # bar (not an "overdue from today's instance" marker).
                    # Dedupe by item id to avoid double-adding when the
                    # real next instance is already in the dict.
                    if not any(getattr(existing, "id", None) == item.id for existing in bucket):
                        bucket.append(_ProjectedItem(item, next_due))
                    current = next_due

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

        tl_name_map = {
            0: "tasks",
            1: "daily",
            2: "productivity",
            3: "accuracy",
            4: "timing",
            5: "cycle",
        }
        get_config().database.timeline_sub_view = tl_name_map.get(idx, "tasks")
        get_config_manager().save()

    def _update_timeline_nav_state(self) -> None:
        """Enable/disable navigation buttons based on active timeline sub-view."""
        # Tasks and Daily support navigation; Productivity, Accuracy,
        # Timing, and Cycle are all-time aggregates with no nav.
        nav_enabled = self._tl_sub_view <= 1  # 0=Tasks, 1=Daily
        self._prev_btn.setEnabled(nav_enabled)
        self._next_btn.setEnabled(nav_enabled)
        self._today_btn.setEnabled(nav_enabled)

    def _refresh_timeline_sub_view(self) -> None:
        """Refresh the active timeline sub-view chart."""
        list_id = str(self._todo_list.id) if self._todo_list else None
        if self._tl_sub_view == 1:  # Daily
            self._timeline_daily_widget.set_current_date(self._current_date)
        elif self._tl_sub_view == 2:  # Productivity
            self._timeline_productivity_widget.rebuild()
        elif self._tl_sub_view == 3:  # Accuracy
            self._timeline_accuracy_widget.set_list_id(list_id)
            self._timeline_accuracy_widget.rebuild()
        elif self._tl_sub_view == 4:  # Timing
            self._timeline_timing_widget.set_list_id(list_id)
            self._timeline_timing_widget.rebuild()
        elif self._tl_sub_view == 5:  # Cycle
            self._timeline_cycle_widget.set_list_id(list_id)
            self._timeline_cycle_widget.rebuild()

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
        elif self._sub_view == self.SUB_AGENDA:
            self._current_date -= timedelta(days=_AgendaView.DEFAULT_DAYS)
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
        elif self._sub_view == self.SUB_AGENDA:
            self._current_date += timedelta(days=_AgendaView.DEFAULT_DAYS)
        else:
            self._current_date += timedelta(days=1)
        self._update_nav_label()
        self.refresh()

    def _navigate_today(self) -> None:
        self._current_date = date.today()
        self._update_nav_label()
        self.refresh()

    def notify_day_changed(self, old_today: date, new_today: date) -> None:
        """Advance the anchor when the wall-clock day crosses while the app
        is running. Only shifts when the user was viewing a range that
        contained the previous today — deliberate navigation away is
        preserved. Called by MainWindow's periodic tick.
        """
        if old_today == new_today:
            return
        contained = False
        if self._sub_view == self.SUB_MONTH:
            contained = (self._current_date.year, self._current_date.month) == (
                old_today.year,
                old_today.month,
            )
        elif self._sub_view in (self.SUB_WEEK,) or (
            self._sub_view == self.SUB_TIMELINE and self._tl_sub_view == 1
        ):
            week_start = self._current_date - timedelta(days=self._current_date.weekday())
            week_end = week_start + timedelta(days=6)
            contained = week_start <= old_today <= week_end
        else:
            contained = self._current_date == old_today
        if contained:
            self._current_date = new_today
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
        elif self._sub_view == self.SUB_AGENDA:
            end = d + timedelta(days=_AgendaView.DEFAULT_DAYS - 1)
            self._nav_label.setText(f"{d.strftime('%b %d')} — {end.strftime('%b %d, %Y')}")
        elif self._sub_view == self.SUB_TIMELINE:
            if self._tl_sub_view == 1:  # Daily
                start = d - timedelta(days=d.weekday())
                end = start + timedelta(days=6)
                self._nav_label.setText(
                    f"{start.strftime('%b %d')} \u2014 {end.strftime('%b %d, %Y')}"
                )
            elif self._tl_sub_view == 2:  # Productivity
                self._nav_label.setText(self.tr("Productivity \u2014 All Time"))
            elif self._tl_sub_view == 3:  # Accuracy
                self._nav_label.setText(self.tr("Accuracy \u2014 All Time"))
            elif self._tl_sub_view == 4:  # Timing
                self._nav_label.setText(self.tr("Timing \u2014 All Time"))
            elif self._tl_sub_view == 5:  # Cycle
                self._nav_label.setText(self.tr("Cycle Time \u2014 All Time"))
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

        # Legend is only meaningful for day/week (the sub-views that use
        # the Gantt-bar palette). Hide it in month and timeline.
        is_day_or_week = idx in (self.SUB_DAY, self.SUB_WEEK)
        self._legend.setVisible(is_day_or_week)

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
            self.SUB_AGENDA: "agenda",
        }
        get_config().database.calendar_sub_view = name_map.get(idx, "week")
        get_config_manager().save()

        # Auto-scroll to current hour for day and week views. Use a
        # one-shot timer because the table viewport may not be laid out
        # immediately after switching the stack widget.
        if idx in (self.SUB_DAY, self.SUB_WEEK):
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(0, self._scroll_to_current_hour)

    # --- Task interaction ---

    def _tick_now_indicators(self) -> None:
        """Repaint the day/week table viewports so the now line creeps and
        DUE_NOW/OVERDUE_ACTIVE bars advance their visual treatment as time
        passes. Called every 30 seconds by self._now_timer.

        Updates BOTH inner tables of each pinned container (the All Day
        row and the hour grid) so all-day bars and Q6 overdue markers
        also refresh on each tick.
        """
        self._day_container.update_viewports()
        self._week_container.update_viewports()

    def _on_task_clicked(self, item_id: UUID) -> None:
        self._selected_item_id = item_id
        self.item_selected.emit(item_id)
        self._cal_delegate.set_selected(item_id)
        self._week_delegate.set_selected(item_id)
        self._day_delegate.set_selected(item_id)
        self._timeline_tasks_widget.set_selected(item_id)
        self._cal_table.viewport().update()  # type: ignore[union-attr]
        # Both inner tables of each pinned container must repaint so
        # the selection highlight appears regardless of whether the
        # selected task is an all-day bar or an hour-grid bar.
        self._week_container.update_viewports()
        self._day_container.update_viewports()

    def _on_task_double_clicked(self, item_id: UUID) -> None:
        """Double-click opens the Edit Reminder dialog — same entry
        point that the context menu's Edit Reminder action uses, and
        mirrors the kanban board's card-double-click behavior."""
        from PyQt6.QtWidgets import QInputDialog

        self._selected_item_id = item_id
        if self._todo_list is None:
            return
        item = self._todo_list.items.get(item_id)
        if item is None:
            return
        text, ok = QInputDialog.getText(
            self,
            self.tr("Edit Reminder"),
            self.tr("Reminder:"),
            text=item.reminder,
        )
        if ok and text.strip() and text.strip() != item.reminder:
            self.item_reminder_changed.emit(item_id, text.strip())

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
            edit_action = QAction(self.tr("Edit Reminder..."), self)

            def _edit_reminder(_checked=False, it=item, iid=item_id):
                text, ok = QInputDialog.getText(
                    self, self.tr("Edit Reminder"), self.tr("Reminder:"), text=it.reminder
                )
                if ok and text.strip():
                    self.item_reminder_changed.emit(iid, text.strip())

            edit_action.triggered.connect(_edit_reminder)
            menu.addAction(edit_action)

            # Join meeting — only when the reminder contains a recognized
            # video-conference URL. Sits at the top of the menu for fast
            # reach during a meeting block.
            from ...core.meeting_link import detect_meeting_link

            meeting = detect_meeting_link(item.reminder)
            if meeting is not None:
                join_action = QAction(
                    self.tr("Join {provider} meeting").format(provider=meeting.provider),
                    self,
                )

                def _open_join(_checked=False, url=meeting.url):
                    from PyQt6.QtCore import QUrl
                    from PyQt6.QtGui import QDesktopServices

                    QDesktopServices.openUrl(QUrl(url))

                join_action.triggered.connect(_open_join)
                menu.addAction(join_action)
                menu.addSeparator()

        edit_tags = QAction(self.tr("Edit Tags..."), self)
        edit_tags.triggered.connect(lambda: self.edit_tags_requested.emit(item_id))
        menu.addAction(edit_tags)

        edit_rec = QAction(self.tr("Edit Recurrence..."), self)
        edit_rec.triggered.connect(self.edit_recurrence_requested.emit)
        menu.addAction(edit_rec)

        focus = QAction(self.tr("Start Focus Session"), self)
        focus.triggered.connect(lambda: self.focus_requested.emit(item_id))
        menu.addAction(focus)

        if item and item.parent_id is None:
            add_sub = QAction(self.tr("Add Subtask..."), self)
            add_sub.triggered.connect(lambda: self.add_subtask_requested.emit(item_id))
            menu.addAction(add_sub)

        menu.addSeparator()

        toggle = QAction(self.tr("Toggle Complete"), self)
        toggle.triggered.connect(self.toggle_requested.emit)
        menu.addAction(toggle)

        delete = QAction(self.tr("Delete"), self)
        delete.triggered.connect(self.delete_requested.emit)
        menu.addAction(delete)

        menu.exec(global_pos)

    def _on_more_clicked(self, cell_date: date, items: list) -> None:
        """Show popover with all tasks for a date."""
        self._show_day_popover(cell_date, items)

    def _on_add_task_at_requested(self, cell_date: date, hour: int) -> None:
        """Forward an empty-cell click up to the main window so it can
        open AddTodoDialog with the cell's date and hour pre-filled."""
        self.add_task_at_requested.emit(cell_date, hour)

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

            # _DraggableTaskButton subclasses QPushButton to emit drag
            # events with the application/x-pytodo-item-id mime when the
            # press-and-move distance exceeds the drag threshold. Short
            # clicks still fire the QPushButton `clicked` signal below,
            # preserving the edit-on-click path. Overflowed tasks in
            # this popover can now be dragged to other cells or back to
            # the unscheduled panel without needing to close and
            # re-open the popover first.
            row = _DraggableTaskButton(item.id)
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

            row.clicked.connect(lambda _checked=False, iid=item.id: self._edit_from_popover(iid))
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

    def _edit_from_popover(self, item_id: UUID) -> None:
        """Open the day popover task in the detail panel for editing.

        The popover is the user's escape hatch when too many tasks
        share a day for the calendar grid to show them all. Once
        they pick one, they want to edit it — not just highlight it
        — so we close the popover and ask the parent window to
        surface the detail panel in edit mode.
        """
        self._select_from_popover(item_id)
        self._close_popover()
        self.item_edit_requested.emit(item_id)

    def _popover_context_menu(self, item_id: UUID, global_pos) -> None:
        """Right-click on popover item — select and show context menu."""
        self._select_from_popover(item_id)
        self._show_context_menu(item_id, global_pos)

    def _on_task_resized(self, item_id, field_name: str, new_value) -> None:
        """Forward an edge-drag-to-resize completion to the matching
        item-changed signal.

        Mirrors the calendar widget's existing pattern (the dropped /
        date / time handlers all emit signals up to MainWindow rather
        than constructing commands directly). MainWindow owns the
        QUndoStack and routes each item-changed signal through the
        right Edit command — keeps the view layer free of database /
        undo-stack coupling.
        """
        if field_name == "due_time":
            self.item_due_time_changed.emit(item_id, new_value)
        elif field_name == "due_time_end":
            self.item_due_time_end_changed.emit(item_id, new_value)
        elif field_name == "estimated_minutes":
            self.item_estimated_minutes_changed.emit(item_id, int(new_value))

    def _on_task_dropped(self, item_id: UUID, target_date: date) -> None:
        """Handle a task being dropped onto a month calendar date."""
        self.item_due_date_changed.emit(item_id, target_date)

    def _on_task_dropped_to_unscheduled(self, item_id: UUID) -> None:
        """Handle a task dropped from the calendar back onto the
        unscheduled panel. Clears due_date; EditDueDateCommand also
        clears due_time when the new due_date is None, so the item
        returns to a fully unscheduled state in one undoable step."""
        self.item_due_date_changed.emit(item_id, None)

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
