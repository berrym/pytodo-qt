"""The deviation zone of a completed bar in the Day and the Week.

A task finished late has a hatched zone from its planned end to its
completion, and one finished early a zone from its completion to its
planned end. The layout gave a bar its planned span only, and the
painter worked the zone out again and could paint it only in the cells
of that span: a late zone, which begins where the span ends, was never
drawn. A task finished on a later day than it was due had no bar on that
day at all, as the day was none of its window's.

The layout now gives each bar its zone, and a bar finished late runs on
to its completion. These tests are of the layout's rules, of what the
painter draws from them, of the edge of a bar that is dragged to set
its due time, and of the days a task is shown on.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QStyleOptionViewItem

from pytodo_qt.core.bar_palette import contrast_ratio, get_palette
from pytodo_qt.core.calendar_layout import (
    BarSegment,
    BarState,
    completion_day_beyond_window,
    compute_bar_segments,
    compute_bar_window,
)
from pytodo_qt.core.models import create_todo_item

DAY = date(2026, 4, 10)
NEXT_DAY = DAY + timedelta(days=1)
LATER = datetime(2026, 4, 20, 12, 0)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute, second))


def _task(*, done: datetime | None = None, **fields):
    item = create_todo_item("Task")
    item.due_date = DAY
    for name, value in fields.items():
        setattr(item, name, value)
    if done is not None:
        item.complete = True
        item.completed_at = _ms(done)
    return item


def _bar(item, day: date = DAY) -> BarSegment:
    window = compute_bar_window(item)
    assert window is not None
    segments = compute_bar_segments(item, window, day, LATER)
    assert len(segments) == 1, segments
    return segments[0]


def _zone(segment: BarSegment) -> tuple[int | None, int | None]:
    return segment.zone_start_minute, segment.zone_end_minute


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------


class TestLateOnTheDueDay:
    """The bar runs on to the completion, and that stretch is its zone."""

    def test_the_bar_runs_on_to_the_completion(self):
        bar = _bar(_task(due_time=time(7, 0), estimated_minutes=60, done=_at(DAY, 7, 40)))
        assert bar.state == BarState.COMPLETED_LATE
        assert (bar.start_minute, bar.end_minute) == (6 * 60, 7 * 60 + 40)
        assert _zone(bar) == (7 * 60, 7 * 60 + 40)

    def test_hours_late(self):
        bar = _bar(_task(due_time=time(9, 0), estimated_minutes=60, done=_at(DAY, 12, 10)))
        assert bar.end_minute == 12 * 60 + 10
        assert _zone(bar) == (9 * 60, 12 * 60 + 10)

    def test_a_block_finished_after_it_ended(self):
        item = _task(due_time_block="morning", done=_at(DAY, 23, 0))
        window = compute_bar_window(item)
        assert window is not None
        bar = _bar(item)
        planned_end = window.end.hour * 60 + window.end.minute
        assert _zone(bar) == (planned_end, 23 * 60)

    @pytest.mark.parametrize("done", [_at(DAY, 7, 0, 1), _at(DAY, 7, 1), _at(DAY, 7, 9)])
    def test_the_zone_is_never_shorter_than_ten_minutes(self, done):
        """A task finished late and one finished on time have the same
        color: a zone a pixel high would not tell them apart."""
        bar = _bar(_task(due_time=time(7, 0), estimated_minutes=60, done=done))
        assert bar.state == BarState.COMPLETED_LATE
        assert _zone(bar) == (7 * 60, 7 * 60 + 10)
        assert bar.end_minute == 7 * 60 + 10

    def test_a_short_bar_has_its_zone_after_the_height_it_is_drawn_at(self):
        """A task of five minutes is drawn thirty high. Its zone follows
        that, and does not lie inside it."""
        bar = _bar(_task(due_time=time(7, 5), estimated_minutes=5, done=_at(DAY, 7, 10)))
        assert bar.start_minute == 7 * 60
        assert _zone(bar) == (7 * 60 + 30, 7 * 60 + 40)

    def test_a_bar_ending_near_midnight_keeps_a_zone_of_ten_minutes(self):
        bar = _bar(_task(due_time=time(23, 55), estimated_minutes=30, done=_at(DAY, 23, 58)))
        assert bar.end_minute == 1440
        assert _zone(bar) == (1430, 1440)

    def test_the_zone_lies_within_the_bar(self):
        for done in (_at(DAY, 7, 0, 30), _at(DAY, 7, 40), _at(DAY, 23, 59)):
            bar = _bar(_task(due_time=time(7, 0), estimated_minutes=60, done=done))
            start, end = _zone(bar)
            assert start is not None and end is not None
            assert bar.start_minute <= start < end <= bar.end_minute


class TestLateOnALaterDay:
    """The due day keeps the planned bar; the day of the completion has
    a bar that is all zone."""

    def _item(self):
        return _task(
            due_time=time(15, 0),
            estimated_minutes=60,
            done=_at(DAY + timedelta(days=2), 11, 0),
        )

    def test_the_due_day_keeps_the_planned_span(self):
        bar = _bar(self._item())
        assert (bar.start_minute, bar.end_minute) == (14 * 60, 15 * 60)
        assert bar.state == BarState.COMPLETED_LATE
        assert _zone(bar) == (None, None)

    def test_the_day_between_has_a_marker_and_no_zone(self):
        bar = _bar(self._item(), NEXT_DAY)
        assert bar.is_marker
        assert _zone(bar) == (None, None)

    def test_the_completion_day_is_all_zone(self):
        bar = _bar(self._item(), DAY + timedelta(days=2))
        assert not bar.is_marker and not bar.is_all_day
        assert (bar.start_minute, bar.end_minute) == (0, 11 * 60)
        assert _zone(bar) == (0, 11 * 60)

    def test_finished_soon_after_midnight(self):
        """The bar on the next day has the least height of a bar."""
        item = _task(due_time=time(23, 30), estimated_minutes=60, done=_at(NEXT_DAY, 0, 5))
        assert _zone(_bar(item)) == (None, None)
        bar = _bar(item, NEXT_DAY)
        assert (bar.start_minute, bar.end_minute) == (0, 30)
        assert _zone(bar) == (0, 30)

    def test_finished_in_the_first_minute_of_the_next_day(self):
        item = _task(due_time=time(23, 30), estimated_minutes=60, done=_at(NEXT_DAY, 0, 0, 20))
        bar = _bar(item, NEXT_DAY)
        assert (bar.start_minute, bar.end_minute) == (0, 30)

    def test_an_all_day_task_finished_the_next_morning(self):
        item = _task(done=_at(NEXT_DAY, 10, 0))
        chip = _bar(item)
        assert chip.is_all_day
        assert _zone(chip) == (None, None)
        bar = _bar(item, NEXT_DAY)
        assert not bar.is_all_day
        assert _zone(bar) == (0, 10 * 60)


class TestEarly:
    """The zone is the stretch from the completion to the planned end."""

    def test_finished_within_the_planned_span(self):
        bar = _bar(_task(due_time=time(15, 0), estimated_minutes=120, done=_at(DAY, 14, 0)))
        assert bar.state == BarState.COMPLETED_EARLY
        assert (bar.start_minute, bar.end_minute) == (13 * 60, 15 * 60)
        assert _zone(bar) == (14 * 60, 15 * 60)

    def test_finished_before_the_planned_span_began(self):
        bar = _bar(_task(due_time=time(15, 0), estimated_minutes=120, done=_at(DAY, 9, 0)))
        assert _zone(bar) == (13 * 60, 15 * 60)

    def test_finished_on_an_earlier_day(self):
        done = _at(DAY - timedelta(days=1), 16, 0)
        bar = _bar(_task(due_time=time(15, 0), estimated_minutes=120, done=done))
        assert _zone(bar) == (13 * 60, 15 * 60)

    def test_a_bar_of_two_days_has_its_zone_on_the_day_it_was_finished(self):
        """Finished on the second day: the first day's part has none.
        The painter drew it there too, at the same minutes."""
        item = _task(
            due_date=NEXT_DAY,
            due_time=time(10, 0),
            estimated_minutes=20 * 60,
            done=_at(NEXT_DAY, 8, 0),
        )
        assert _zone(_bar(item, DAY)) == (None, None)
        assert _zone(_bar(item, NEXT_DAY)) == (8 * 60, 10 * 60)

    def test_a_bar_of_two_days_finished_on_the_first(self):
        item = _task(
            due_date=NEXT_DAY,
            due_time=time(10, 0),
            estimated_minutes=20 * 60,
            done=_at(DAY, 20, 0),
        )
        assert _zone(_bar(item, DAY)) == (20 * 60, 1440)
        assert _zone(_bar(item, NEXT_DAY)) == (0, 10 * 60)


class TestNoZone:
    def test_a_task_not_finished(self):
        assert _zone(_bar(_task(due_time=time(15, 0), estimated_minutes=60))) == (None, None)

    def test_finished_at_the_planned_end(self):
        bar = _bar(_task(due_time=time(15, 0), estimated_minutes=60, done=_at(DAY, 15, 0)))
        assert bar.state == BarState.COMPLETED_ONTIME
        assert _zone(bar) == (None, None)

    def test_finished_at_a_time_not_recorded(self):
        item = _task(due_time=time(15, 0), estimated_minutes=60)
        item.complete = True
        bar = _bar(item)
        assert bar.state == BarState.COMPLETED_UNKNOWN
        assert _zone(bar) == (None, None)

    def test_a_segment_made_without_a_zone_has_none(self):
        segment = BarSegment(
            item_id=create_todo_item("x").id,
            start_minute=0,
            end_minute=60,
            state=BarState.FUTURE,
            clipped_top=False,
            clipped_bottom=False,
            is_marker=False,
            marker_label=None,
            is_all_day=False,
        )
        assert _zone(segment) == (None, None)


class TestDueEdge:
    """Where a bar's planned span ends: the edge that is dragged to set
    the due time."""

    def test_a_bar_that_ends_at_its_planned_end(self):
        bar = _bar(_task(due_time=time(15, 0), estimated_minutes=60))
        assert bar.due_edge_minute == 15 * 60

    def test_a_bar_finished_early(self):
        bar = _bar(_task(due_time=time(15, 0), estimated_minutes=120, done=_at(DAY, 14, 0)))
        assert bar.due_edge_minute == 15 * 60

    def test_a_bar_that_runs_on_has_it_where_the_zone_begins(self):
        bar = _bar(_task(due_time=time(7, 0), estimated_minutes=60, done=_at(DAY, 9, 30)))
        assert bar.end_minute == 9 * 60 + 30
        assert bar.due_edge_minute == 7 * 60

    def test_the_bar_of_the_completion_day_has_none(self):
        item = _task(due_time=time(15, 0), estimated_minutes=60, done=_at(NEXT_DAY, 11, 0))
        assert _bar(item, NEXT_DAY).due_edge_minute is None

    def test_a_bar_that_ends_on_a_later_day_has_none(self):
        item = _task(due_date=NEXT_DAY, due_time=time(10, 0), estimated_minutes=20 * 60)
        assert _bar(item, DAY).due_edge_minute is None


class TestCompletionDayBeyondWindow:
    def _day(self, item) -> date | None:
        window = compute_bar_window(item)
        assert window is not None
        return completion_day_beyond_window(item, window)

    def test_finished_on_a_later_day(self):
        item = _task(due_time=time(15, 0), estimated_minutes=60, done=_at(NEXT_DAY, 11, 0))
        assert self._day(item) == NEXT_DAY

    def test_an_all_day_task_finished_on_a_later_day(self):
        assert self._day(_task(done=_at(NEXT_DAY, 10, 0))) == NEXT_DAY

    def test_finished_late_on_the_due_day(self):
        item = _task(due_time=time(15, 0), estimated_minutes=60, done=_at(DAY, 18, 0))
        assert self._day(item) is None

    def test_an_all_day_task_finished_on_its_day(self):
        assert self._day(_task(done=_at(DAY, 22, 0))) is None

    def test_a_task_due_at_midnight_finished_before_it(self):
        """Its window ends at 00:00 of the next day, and its bar is on
        the day before."""
        item = _task(
            due_date=NEXT_DAY, due_time=time(0, 0), estimated_minutes=60, done=_at(DAY, 23, 50)
        )
        assert self._day(item) is None

    def test_a_task_not_finished(self):
        assert self._day(_task(due_time=time(15, 0), estimated_minutes=60)) is None

    def test_agrees_with_the_days_the_layout_gives_a_bar(self):
        """The day it names is the one day past the window's on which
        the layout gives the task a bar in the hours."""
        item = _task(
            due_time=time(15, 0), estimated_minutes=60, done=_at(DAY + timedelta(days=3), 9, 0)
        )
        window = compute_bar_window(item)
        assert window is not None
        days_with_a_bar = [
            DAY + timedelta(days=n)
            for n in range(1, 6)
            if any(
                not s.is_marker and not s.is_all_day
                for s in compute_bar_segments(item, window, DAY + timedelta(days=n), LATER)
            )
        ]
        assert days_with_a_bar == [completion_day_beyond_window(item, window)]


# ---------------------------------------------------------------------------
# What is painted
# ---------------------------------------------------------------------------

_CELL_W = 120
_CELL_H = 60


@pytest.fixture()
def week(qtbot):
    from pytodo_qt.gui.widgets.calendar_view import _WeekDelegate, _WeekModel, _WeekTableView

    view = _WeekTableView()
    model = _WeekModel()
    view.setModel(model)
    view.setItemDelegate(_WeekDelegate())
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.show()
    model._week_dates = [DAY + timedelta(days=n) for n in range(7)]
    return view, model


def _hatched_minutes(view, model, item, column: int, theme: str, state: BarState) -> set[int]:
    """The minutes of a day's column at which pixels of the hatch's color are."""
    palette = get_palette(theme)
    delegate = view.itemDelegate()
    delegate._bar_palette = palette
    model.set_items({day: [item] for day in model._week_dates})
    hatch = QColor(palette[state].deviation).rgb()
    minutes: set[int] = set()
    for hour in range(24):
        pixmap = QPixmap(_CELL_W, _CELL_H)
        pixmap.fill(QColor("#808080"))
        painter = QPainter(pixmap)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, _CELL_W, _CELL_H)
        delegate.paint(painter, option, model.index(hour + 1, column))
        painter.end()
        image = pixmap.toImage()
        for y in range(_CELL_H):
            if any(image.pixel(x, y) == hatch for x in range(_CELL_W)):
                minutes.add(hour * 60 + y)
    return minutes


@pytest.mark.parametrize("theme", ["light", "dark"])
class TestPaintedZone:
    def test_late_on_the_due_day(self, week, theme):
        """The case of the issue: a bar from 06:00 to 07:00 finished at
        07:40 had no hatch at all."""
        view, model = week
        item = _task(due_time=time(7, 0), estimated_minutes=60, done=_at(DAY, 7, 40))
        minutes = _hatched_minutes(view, model, item, 0, theme, BarState.COMPLETED_LATE)
        assert minutes, "no late-overflow zone is painted"
        assert min(minutes) >= 7 * 60
        assert max(minutes) < 7 * 60 + 40
        # Most of the forty minutes: the bar's border and its inset at
        # the end take a few pixels.
        assert len(minutes) >= 30

    def test_late_by_hours_crosses_the_cells(self, week, theme):
        view, model = week
        item = _task(due_time=time(9, 0), estimated_minutes=60, done=_at(DAY, 12, 10))
        minutes = _hatched_minutes(view, model, item, 0, theme, BarState.COMPLETED_LATE)
        assert min(minutes) >= 9 * 60
        assert max(minutes) < 12 * 60 + 10
        for hour in (9, 10, 11):
            assert any(hour * 60 <= m < (hour + 1) * 60 for m in minutes), hour
        assert not any(m < 9 * 60 for m in minutes)

    def test_late_by_a_minute_is_still_shown(self, week, theme):
        view, model = week
        item = _task(due_time=time(7, 0), estimated_minutes=60, done=_at(DAY, 7, 1))
        minutes = _hatched_minutes(view, model, item, 0, theme, BarState.COMPLETED_LATE)
        assert len(minutes) >= 4
        assert min(minutes) >= 7 * 60 and max(minutes) < 7 * 60 + 10

    def test_the_completion_day_of_a_task_finished_on_a_later_day(self, week, theme):
        view, model = week
        item = _task(due_time=time(15, 0), estimated_minutes=60, done=_at(NEXT_DAY, 11, 0))
        due_day = _hatched_minutes(view, model, item, 0, theme, BarState.COMPLETED_LATE)
        assert due_day == set()
        minutes = _hatched_minutes(view, model, item, 1, theme, BarState.COMPLETED_LATE)
        assert minutes
        assert max(minutes) < 11 * 60
        # Below the label, to the end.
        for hour in range(1, 11):
            assert any(hour * 60 <= m < (hour + 1) * 60 for m in minutes), hour

    def test_early(self, week, theme):
        view, model = week
        item = _task(due_time=time(15, 0), estimated_minutes=180, done=_at(DAY, 13, 30))
        minutes = _hatched_minutes(view, model, item, 0, theme, BarState.COMPLETED_EARLY)
        assert minutes
        assert min(minutes) >= 13 * 60 + 30
        assert max(minutes) < 15 * 60

    def test_the_zone_stays_inside_the_bar(self, week, theme):
        """The four pixels between a bar's end and the cell's are not
        hatched."""
        view, model = week
        item = _task(due_time=time(15, 0), estimated_minutes=180, done=_at(DAY, 13, 30))
        minutes = _hatched_minutes(view, model, item, 0, theme, BarState.COMPLETED_EARLY)
        assert max(minutes) < 15 * 60 - 4

    def test_no_hatch_behind_the_label(self, week, theme):
        """The label's color is chosen for the bar's own color."""
        view, model = week
        item = _task(due_time=time(15, 0), estimated_minutes=120, done=_at(DAY, 9, 0))
        minutes = _hatched_minutes(view, model, item, 0, theme, BarState.COMPLETED_EARLY)
        assert minutes
        # The label is in the first lines of the bar, which begins at 13:00.
        assert min(minutes) >= 13 * 60 + 15

    def test_a_bar_without_a_zone_has_no_hatch(self, week, theme):
        view, model = week
        item = _task(due_time=time(15, 0), estimated_minutes=60, done=_at(DAY, 15, 0))
        for state in (BarState.COMPLETED_EARLY, BarState.COMPLETED_LATE):
            assert _hatched_minutes(view, model, item, 0, theme, state) == set()


class TestHatchColors:
    """A hatch is drawn over its bar's color, and is told from it."""

    @pytest.mark.parametrize("theme", ["light", "dark"])
    @pytest.mark.parametrize("state", [BarState.COMPLETED_EARLY, BarState.COMPLETED_LATE])
    def test_a_hatch_has_three_to_one_with_its_bar(self, theme, state):
        colors = get_palette(theme)[state]
        assert contrast_ratio(colors.deviation, colors.base) >= 3.0, (theme, state)

    @pytest.mark.parametrize("late", [False, True])
    def test_the_hatch_is_opaque(self, qapp, late):
        """The contrast is that of the palette's color, not of a blend."""
        from pytodo_qt.gui.widgets.calendar_view import zone_brush

        assert zone_brush(get_palette("light"), late).color().alpha() == 255

    def test_the_two_zones_are_hatched_in_different_directions(self, qapp):
        from pytodo_qt.gui.widgets.calendar_view import zone_brush

        palette = get_palette("light")
        assert zone_brush(palette, True).style() != zone_brush(palette, False).style()

    @pytest.mark.parametrize("theme", ["light", "dark"])
    @pytest.mark.parametrize("late", [False, True])
    def test_the_legend_shows_a_zone_as_a_bar_shows_it(self, qtbot, theme, late):
        from pytodo_qt.gui.widgets.calendar_view import _ZoneSwatch

        palette = get_palette(theme)
        swatch = _ZoneSwatch(palette, late)
        qtbot.addWidget(swatch)
        image = swatch.grab().toImage()
        colors = {image.pixel(x, y) for x in range(image.width()) for y in range(image.height())}
        state = BarState.COMPLETED_LATE if late else BarState.COMPLETED_EARLY
        assert QColor(palette[state].base).rgb() in colors
        assert QColor(palette[state].deviation).rgb() in colors

    def test_the_legend_has_a_swatch_for_each_zone(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _CalendarLegend, _ZoneSwatch

        legend = _CalendarLegend()
        qtbot.addWidget(legend)
        assert len(legend.findChildren(_ZoneSwatch)) == 2


# ---------------------------------------------------------------------------
# The edge that sets the due time
# ---------------------------------------------------------------------------


class TestEdgeOfABarThatRunsOn:
    """A bar due at 15:00 and finished at 16:30 runs from 13:00 to
    16:30. Its due time is still set at 15:00, not at its end."""

    @pytest.fixture()
    def late_bar(self, week):
        view, model = week
        item = _task(due_time=time(15, 0), estimated_minutes=120, done=_at(DAY, 16, 30))
        model.set_items({DAY: [item]})
        return view, model, item

    def _cell(self, view, model, hour: int) -> QRect:
        return view.visualRect(model.index(hour + 1, 0))

    def test_the_edge_is_at_the_due_time(self, late_bar):
        view, model, item = late_bar
        cell = self._cell(view, model, 14)
        hit = view._hit_test_edge(QPoint(cell.center().x(), cell.bottom() - 1))
        assert hit is not None
        assert hit["edge"] == "bottom"
        assert hit["item"].id == item.id

    def test_the_end_of_the_bar_is_no_edge(self, late_bar):
        view, model, _item = late_bar
        cell = self._cell(view, model, 16)
        where = QPoint(cell.center().x(), cell.top() + cell.height() // 2)
        assert view._hit_test_edge(where) is None

    def test_the_zone_is_no_edge(self, late_bar):
        view, model, _item = late_bar
        cell = self._cell(view, model, 15)
        where = QPoint(cell.center().x(), cell.top() + cell.height() // 2)
        assert view._hit_test_edge(where) is None

    def test_the_zone_opens_the_task(self, late_bar):
        """The zone is part of the bar: a click on it finds the task."""
        view, model, item = late_bar
        cell = self._cell(view, model, 16)
        index = model.index(17, 0)
        found = view._hit_test_bar_segments(
            QPoint(cell.center().x(), cell.top() + 10), cell, index, DAY, 16
        )
        assert found is not None


# ---------------------------------------------------------------------------
# The days a task is shown on
# ---------------------------------------------------------------------------


class TestCompletionDayIsShown:
    """A task is among a day's items on the days of its window. The day
    it was finished on, when later, is added."""

    def _spill(self, scheduled: dict) -> dict:
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        CalendarViewWidget._spill_late_completions(MagicMock(), scheduled)
        return scheduled

    def test_a_task_finished_on_a_later_day_is_added_to_that_day(self):
        item = _task(due_time=time(15, 0), estimated_minutes=60, done=_at(NEXT_DAY, 11, 0))
        scheduled = self._spill({DAY: [item]})
        assert scheduled[NEXT_DAY] == [item]
        assert scheduled[DAY] == [item]

    def test_an_all_day_task_finished_on_a_later_day_is_added(self):
        item = _task(done=_at(NEXT_DAY, 10, 0))
        assert self._spill({DAY: [item]})[NEXT_DAY] == [item]

    def test_a_task_is_added_once(self):
        item = _task(due_time=time(15, 0), estimated_minutes=60, done=_at(NEXT_DAY, 11, 0))
        scheduled = self._spill(self._spill({DAY: [item], NEXT_DAY: []}))
        assert scheduled[NEXT_DAY] == [item]

    def test_other_tasks_stay_where_they_are(self):
        late_same_day = _task(due_time=time(15, 0), estimated_minutes=60, done=_at(DAY, 18, 0))
        early = _task(due_time=time(15, 0), estimated_minutes=60, done=_at(DAY, 14, 30))
        not_done = _task(due_time=time(15, 0), estimated_minutes=60)
        scheduled = self._spill({DAY: [late_same_day, early, not_done]})
        assert list(scheduled) == [DAY]

    def test_the_widget_shows_the_bar_on_the_completion_day(self, qtbot):
        from pytodo_qt.core.models import create_todo_list
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        today = date.today()
        due = today - timedelta(days=3)
        finished = today - timedelta(days=1)
        todo_list = create_todo_list("List")
        item = create_todo_item("Finished two days late")
        item.due_date = due
        item.due_time = time(15, 0)
        item.estimated_minutes = 60
        item.complete = True
        item.completed_at = _ms(_at(finished, 11, 0))
        todo_list.add_item(item)

        widget = CalendarViewWidget()
        qtbot.addWidget(widget)
        widget.set_list(todo_list)

        on_the_day = widget._week_model._items_by_date.get(finished, [])
        assert [i.id for i in on_the_day] == [item.id]

    def test_no_chip_in_the_all_day_row_of_the_completion_day(self, week):
        """The task has a bar in the hours there. An all-day task had
        a chip on every day it was among the items of."""
        _view, model = week
        item = _task(done=_at(NEXT_DAY, 10, 0))
        assert model._all_day_items([item], DAY) == [item]
        assert model._all_day_items([item], NEXT_DAY) == []

    def test_an_all_day_task_finished_on_its_day_keeps_its_chip(self, week):
        _view, model = week
        item = _task(done=_at(DAY, 22, 0))
        assert model._all_day_items([item], DAY) == [item]
