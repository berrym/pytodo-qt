"""Unit tests for the pure-function calendar layout layer.

These tests have NO Qt dependency. They lock in the seven foundational
decisions from docs/plans/calendar-gantt-redesign.md by execution.

Q1 (compute_bar_window) and Q2 (work-back semantics in WORKBACK kind)
are load-bearing — these tests must always pass; their failure means
the spec foundation has cracked.

Q3 (cross-day clipping), Q5 (BarState classification), Q6 (overdue
marker lifecycle) tests verify the visual rules but are refinable in
tone (exact thresholds, etc.).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from pytodo_qt.core.calendar_layout import (
    DUE_NOW_THRESHOLD,
    BarSegment,
    BarState,
    BarWindow,
    WindowKind,
    compute_bar_segments,
    compute_bar_state,
    compute_bar_window,
)
from pytodo_qt.core.models import TodoItem


def _ms(dt: datetime) -> int:
    """datetime → ms-since-epoch (int)."""
    return int(dt.timestamp() * 1000)


def _make_item(**kwargs) -> TodoItem:
    """Build a TodoItem with overridable defaults."""
    return TodoItem(reminder=kwargs.pop("reminder", "Test"), **kwargs)


# ===========================================================================
# Q1: compute_bar_window — origin rules
# ===========================================================================


class TestComputeBarWindowEvent:
    """Q1 Rule 1: due_time AND due_time_end → EVENT."""

    def test_event_basic(self):
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(14, 0),
            due_time_end=time(15, 30),
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.EVENT
        assert window.origin == datetime(2026, 4, 10, 14, 0)
        assert window.end == datetime(2026, 4, 10, 15, 30)

    def test_event_with_estimate_still_event(self):
        """When both due_time_end and estimated_minutes are set, EVENT wins.
        Q1 rule order: EVENT before WORKBACK."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(14, 0),
            due_time_end=time(15, 0),
            estimated_minutes=240,  # would imply 10 AM origin if WORKBACK
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.EVENT
        assert window.origin == datetime(2026, 4, 10, 14, 0)

    def test_event_negative_duration_falls_through(self):
        """Sanitization: due_time_end < due_time falls through to next rule."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            due_time_end=time(14, 0),  # before due_time
            estimated_minutes=60,
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.WORKBACK
        assert window.end == datetime(2026, 4, 10, 15, 0)
        assert window.origin == datetime(2026, 4, 10, 14, 0)


class TestComputeBarWindowWorkback:
    """Q1 Rule 2 + Q2: due_time + estimated_minutes → WORKBACK from deadline."""

    def test_workback_basic(self):
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.WORKBACK
        assert window.end == datetime(2026, 4, 10, 15, 0)
        assert window.origin == datetime(2026, 4, 10, 13, 0)

    def test_workback_crosses_midnight(self):
        """A 4-hour estimate against a 2 AM deadline produces a 10 PM origin
        on the previous day."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(2, 0),
            estimated_minutes=240,
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.WORKBACK
        assert window.end == datetime(2026, 4, 10, 2, 0)
        assert window.origin == datetime(2026, 4, 9, 22, 0)

    def test_workback_zero_estimate_falls_through(self):
        """estimated_minutes=0 doesn't qualify; falls through to deadline-only."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=0,
            created_at=_ms(datetime(2026, 4, 9, 10, 0)),
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.DEADLINE_FROM_CREATED

    def test_workback_pomodoro_fields(self):
        """A task with estimated_pomodoros and no estimated_minutes should
        still get a WORKBACK window, using estimated_pomodoros * 25 as the
        duration (the global default work_duration).

        This is the fix for pomodoro-style recurring tasks that were
        previously falling through to DEADLINE_FROM_CREATED and rendering
        as multi-hour bars because estimated_minutes was 0.
        """
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=0,
            estimated_pomodoros=2,
            # work_duration=0 means "use global default" (25 min)
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.WORKBACK
        assert window.end == datetime(2026, 4, 10, 15, 0)
        # 2 pomodoros * 25 min = 50 minutes
        assert window.origin == datetime(2026, 4, 10, 14, 10)

    def test_workback_per_task_work_duration(self):
        """Per-task work_duration overrides the 25-minute default."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=0,
            estimated_pomodoros=2,
            work_duration=50,  # per-task override
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.WORKBACK
        # 2 pomodoros * 50 min = 100 minutes
        assert window.origin == datetime(2026, 4, 10, 13, 20)

    def test_per_task_work_duration_10_min(self):
        """A task with custom per-task `work_duration=10` uses 10 min
        per pomodoro, NOT the global default. This is the user's
        specific question: 'if pomodoro time was set to 10 instead of
        the current 25 default would it correctly render using 10?'"""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=0,
            estimated_pomodoros=3,
            work_duration=10,  # per-task: 10 min per pomodoro
        )
        # Pass an explicit default of 25 to prove the per-task wins
        window = compute_bar_window(item, default_work_minutes=25)
        assert window is not None
        assert window.kind == WindowKind.WORKBACK
        # 3 pomodoros * 10 min per-task = 30 minutes
        assert window.origin == datetime(2026, 4, 10, 14, 30)

    def test_no_per_task_uses_global_default_from_config(self):
        """A task without per-task `work_duration` uses the global
        default. The user's other question: 'pomodoros without a custom
        per-task time always use whatever is currently set as default
        in settings by user, is that correct?' YES.
        """
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=0,
            estimated_pomodoros=3,
            work_duration=0,  # no per-task override
        )
        # User has set their global default to 10 min in preferences
        window = compute_bar_window(item, default_work_minutes=10)
        assert window is not None
        assert window.kind == WindowKind.WORKBACK
        # 3 pomodoros * 10 min global default = 30 minutes
        assert window.origin == datetime(2026, 4, 10, 14, 30)

        # Same task, but the user changes their default to 50 min
        window = compute_bar_window(item, default_work_minutes=50)
        assert window is not None
        # 3 pomodoros * 50 min global default = 150 minutes
        assert window.origin == datetime(2026, 4, 10, 12, 30)

    def test_get_default_work_minutes_reads_config(self):
        """get_default_work_minutes() returns a positive integer
        regardless of config state. The function gracefully degrades
        to 25 if config can't be loaded."""
        from pytodo_qt.core.calendar_layout import get_default_work_minutes

        result = get_default_work_minutes()
        assert isinstance(result, int)
        assert result >= 1

    def test_workback_alternative_fields_take_max(self):
        """When BOTH estimated_minutes and estimated_pomodoros are set,
        they're treated as ALTERNATIVE expressions of the same duration
        (not additive). The max wins.

        This fixes the "one small bar, one large bar for the same 25-min
        task" visual bug — it occurred when the AddTodo dialog populated
        both fields with equivalent values, and the old summing logic
        rendered a 50-minute bar instead of 25.
        """
        # 25 min via direct field, 25 min via 1 pomodoro (default 25)
        # → effective duration is max(25, 25) = 25 min, not 50
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=25,
            estimated_pomodoros=1,
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.WORKBACK
        # 25 minutes total — origin is 14:35, NOT 14:10
        assert window.origin == datetime(2026, 4, 10, 14, 35)

    def test_workback_pomodoro_dominates_when_larger(self):
        """When pomodoros produce a longer duration than estimated_minutes,
        the pomodoro side wins (max of the two interpretations)."""
        # 4 pomodoros * 25 = 100 min, vs 10 min direct → 100 wins
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=10,
            estimated_pomodoros=4,
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.WORKBACK
        # 100 minutes → origin at 13:20
        assert window.origin == datetime(2026, 4, 10, 13, 20)


class TestComputeBarWindowDeadlineFromCreated:
    """Q1 Rule 3: due_time only (no estimate, no end) → DEADLINE_FROM_CREATED.

    Refinement (2026-04-10): origin is clamped to max(created_at, end - 1h).
    Without this clamp, a recurring task that's been around for days would
    produce a bar spanning many hours, dominating the hour grid. The clamp
    ensures Rule 3 bars are compact 1-hour markers unless the task was
    created within the last hour before its due time.
    """

    def test_deadline_recent_creation_unclamped(self):
        """A task created WITHIN the last hour before its due time keeps
        its real creation-to-due span — the clamp doesn't kick in."""
        created = datetime(2026, 4, 10, 14, 30)  # 30 min before due
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            created_at=_ms(created),
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.DEADLINE_FROM_CREATED
        assert window.end == datetime(2026, 4, 10, 15, 0)
        assert abs((window.origin - created).total_seconds()) < 1

    def test_deadline_old_creation_clamped_to_1_hour(self):
        """A task created days before its due time is clamped: origin
        becomes due_time - 1h, so the bar is a compact 1-hour marker.
        This is the fix for 'recurring task bar spans every hour cell'."""
        created = datetime(2026, 4, 8, 10, 0)  # 2 days before due
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            created_at=_ms(created),
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.DEADLINE_FROM_CREATED
        assert window.end == datetime(2026, 4, 10, 15, 0)
        # Clamped to 1 hour before due_time
        assert window.origin == datetime(2026, 4, 10, 14, 0)

    def test_deadline_with_created_after_due_falls_through(self):
        """Sanitization: created_at after due_time → already-overdue at
        creation. Falls through to ALL_DAY so the item still appears."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            created_at=_ms(datetime(2026, 4, 11, 9, 0)),  # tomorrow
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.ALL_DAY


class TestComputeBarWindowAllDay:
    """Q1 Rule 4: due_date only (no due_time) → ALL_DAY."""

    def test_all_day_basic(self):
        item = _make_item(due_date=date(2026, 4, 10))
        window = compute_bar_window(item)
        assert window is not None
        assert window.kind == WindowKind.ALL_DAY
        assert window.origin == datetime(2026, 4, 10, 0, 0)
        assert window.end == datetime(2026, 4, 11, 0, 0)


class TestComputeBarWindowNoDate:
    """No due_date → no window at all (item belongs in unscheduled sidebar)."""

    def test_no_due_date_returns_none(self):
        item = _make_item()
        assert compute_bar_window(item) is None

    def test_no_due_date_with_other_fields_returns_none(self):
        """Even with due_time set, no due_date means no window. The item
        has no anchored day to live on."""
        item = _make_item(due_time=time(14, 0), estimated_minutes=60)
        assert compute_bar_window(item) is None


# ===========================================================================
# Q5: compute_bar_state — lifecycle classification
# ===========================================================================


class TestComputeBarStateActive:
    """States for incomplete items (FUTURE, IN_WORK_WINDOW, DUE_NOW, OVERDUE_ACTIVE)."""

    def _window(self) -> BarWindow:
        return BarWindow(
            origin=datetime(2026, 4, 10, 13, 0),
            end=datetime(2026, 4, 10, 15, 0),
            kind=WindowKind.WORKBACK,
        )

    def test_future(self):
        item = _make_item()
        window = self._window()
        as_of = datetime(2026, 4, 10, 12, 0)  # before origin
        assert compute_bar_state(item, window, as_of) == BarState.FUTURE

    def test_in_work_window(self):
        item = _make_item()
        window = self._window()
        as_of = datetime(2026, 4, 10, 13, 30)  # 90 min before end
        assert compute_bar_state(item, window, as_of) == BarState.IN_WORK_WINDOW

    def test_due_now_at_threshold(self):
        item = _make_item()
        window = self._window()
        # Exactly at the start of the DUE_NOW window
        as_of = window.end - DUE_NOW_THRESHOLD
        assert compute_bar_state(item, window, as_of) == BarState.DUE_NOW

    def test_due_now_just_before_end(self):
        item = _make_item()
        window = self._window()
        as_of = window.end - timedelta(minutes=1)
        assert compute_bar_state(item, window, as_of) == BarState.DUE_NOW

    def test_overdue_active_at_end(self):
        """as_of == end is OVERDUE_ACTIVE: the deadline has been reached.
        The boundary is `< end` for in-window, `>= end` for overdue."""
        item = _make_item()
        window = self._window()
        assert compute_bar_state(item, window, window.end) == BarState.OVERDUE_ACTIVE

    def test_overdue_active_past_end(self):
        item = _make_item()
        window = self._window()
        as_of = window.end + timedelta(hours=2)
        assert compute_bar_state(item, window, as_of) == BarState.OVERDUE_ACTIVE

    def test_in_work_window_just_before_due_now_threshold(self):
        item = _make_item()
        window = self._window()
        as_of = window.end - DUE_NOW_THRESHOLD - timedelta(minutes=1)
        assert compute_bar_state(item, window, as_of) == BarState.IN_WORK_WINDOW

    def test_at_origin_is_in_work_window(self):
        """The window is half-open: [origin, end). At exactly origin, the
        item has just entered the work window."""
        item = _make_item()
        window = self._window()
        assert compute_bar_state(item, window, window.origin) == BarState.IN_WORK_WINDOW


class TestComputeBarStateCompleted:
    """States for completed items, exact classification with no fuzz."""

    def _window(self) -> BarWindow:
        return BarWindow(
            origin=datetime(2026, 4, 10, 13, 0),
            end=datetime(2026, 4, 10, 15, 0),
            kind=WindowKind.WORKBACK,
        )

    def test_completed_unknown_when_completed_at_is_none(self):
        item = _make_item(complete=True)
        # completed_at is None by default
        assert item.completed_at is None
        window = self._window()
        assert (
            compute_bar_state(item, window, datetime(2026, 4, 10, 12, 0))
            == BarState.COMPLETED_UNKNOWN
        )

    def test_completed_early_one_second_before(self):
        """Any amount before due_end counts as EARLY (no fuzz)."""
        window = self._window()
        item = _make_item(
            complete=True,
            completed_at=_ms(window.end - timedelta(seconds=1)),
        )
        assert compute_bar_state(item, window, window.end) == BarState.COMPLETED_EARLY

    def test_completed_early_hours_before(self):
        window = self._window()
        item = _make_item(
            complete=True,
            completed_at=_ms(window.end - timedelta(hours=1)),
        )
        assert compute_bar_state(item, window, window.end) == BarState.COMPLETED_EARLY

    def test_completed_ontime_exact_match(self):
        """Exact match only — no fuzz."""
        window = self._window()
        item = _make_item(complete=True, completed_at=_ms(window.end))
        assert compute_bar_state(item, window, window.end) == BarState.COMPLETED_ONTIME

    def test_completed_late_one_second_after(self):
        """Any amount after due_end counts as LATE (no fuzz)."""
        window = self._window()
        item = _make_item(
            complete=True,
            completed_at=_ms(window.end + timedelta(seconds=1)),
        )
        assert compute_bar_state(item, window, window.end) == BarState.COMPLETED_LATE

    def test_completed_late_hours_after(self):
        window = self._window()
        item = _make_item(
            complete=True,
            completed_at=_ms(window.end + timedelta(hours=4)),
        )
        assert compute_bar_state(item, window, window.end) == BarState.COMPLETED_LATE

    def test_completed_state_independent_of_as_of(self):
        """A completed item's state doesn't depend on the as_of argument —
        the completion is frozen in time."""
        window = self._window()
        item = _make_item(complete=True, completed_at=_ms(window.end - timedelta(minutes=10)))
        # Whatever as_of we pass, the state is COMPLETED_EARLY
        for as_of in (
            datetime(2025, 1, 1),
            datetime(2026, 4, 10, 9, 0),
            datetime(2027, 12, 31),
        ):
            assert compute_bar_state(item, window, as_of) == BarState.COMPLETED_EARLY


# ===========================================================================
# Q3 + Q6: compute_bar_segments — clipping and marker lifecycle
# ===========================================================================


class TestComputeBarSegmentsAllDay:
    """ALL_DAY items live in the All Day row of their due_date.

    Q6 marker lifecycle also applies to ALL_DAY items: an uncompleted
    all-day task whose due day has passed produces an OVERDUE_ACTIVE
    marker on every subsequent viewing day, just like an hour-grid
    task with a due_time. The "due day" reference for ALL_DAY is
    `window.origin.date()` (= the actual due_date), not the
    end-of-day boundary `window.end.date()` which is 00:00 of the
    next day.
    """

    def test_all_day_on_correct_day(self):
        item = _make_item(due_date=date(2026, 4, 10))
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(
            item, window, date(2026, 4, 10), datetime(2026, 4, 10, 12, 0)
        )
        assert len(segments) == 1
        assert segments[0].is_all_day is True
        assert segments[0].is_marker is False

    def test_all_day_before_due_day_empty(self):
        """A viewing day BEFORE the due day produces no segment —
        the task is in the future."""
        item = _make_item(due_date=date(2026, 4, 10))
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(item, window, date(2026, 4, 9), datetime(2026, 4, 9, 12, 0))
        assert segments == []

    def test_all_day_uncomplete_subsequent_day_produces_marker(self):
        """An uncompleted all-day task whose due day has passed
        produces a Q6 OVERDUE_ACTIVE marker on the subsequent day."""
        item = _make_item(due_date=date(2026, 4, 10), complete=False)
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(
            item, window, date(2026, 4, 11), datetime(2026, 4, 11, 12, 0)
        )
        assert len(segments) == 1
        seg = segments[0]
        assert seg.is_marker is True
        assert seg.is_all_day is True
        assert seg.state == BarState.OVERDUE_ACTIVE
        assert seg.marker_label is not None
        assert "overdue" in seg.marker_label.lower()

    def test_all_day_uncomplete_marker_grows_each_day(self):
        """The marker label reflects the elapsed time from the due
        day to end-of-viewing-day, so it grows on each subsequent day."""
        item = _make_item(due_date=date(2026, 4, 10), complete=False)
        window = compute_bar_window(item)
        assert window is not None
        # Day right after due
        seg_d1 = compute_bar_segments(
            item, window, date(2026, 4, 11), datetime(2026, 4, 15, 12, 0)
        )[0]
        # Three days after due
        seg_d3 = compute_bar_segments(
            item, window, date(2026, 4, 13), datetime(2026, 4, 15, 12, 0)
        )[0]
        # The d3 marker label should differ from d1 (more elapsed time)
        assert seg_d1.marker_label != seg_d3.marker_label

    def test_all_day_completed_unknown_no_marker_on_subsequent(self):
        """COMPLETED_UNKNOWN (complete=True, completed_at=None) means
        we don't know when the task was finished, so we can't honestly
        claim it was overdue on day X. No marker on subsequent days."""
        item = _make_item(due_date=date(2026, 4, 10), complete=True, completed_at=None)
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(
            item, window, date(2026, 4, 11), datetime(2026, 4, 11, 12, 0)
        )
        assert segments == []

    def test_all_day_completed_late_intermediate_day_shows_marker(self):
        """ALL_DAY task due Mon, completed Wed, viewed Tue → marker
        on Tue because the task was overdue-active on Tue."""
        completed_at_ms = int(datetime(2026, 4, 12, 15, 0).timestamp() * 1000)
        item = _make_item(
            due_date=date(2026, 4, 10),
            complete=True,
            completed_at=completed_at_ms,
        )
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(
            item, window, date(2026, 4, 11), datetime(2026, 4, 15, 12, 0)
        )
        assert len(segments) == 1
        assert segments[0].is_marker is True
        assert segments[0].state == BarState.OVERDUE_ACTIVE

    def test_all_day_completed_late_post_completion_no_marker(self):
        """After the completion day, no marker — the task is done."""
        completed_at_ms = int(datetime(2026, 4, 12, 15, 0).timestamp() * 1000)
        item = _make_item(
            due_date=date(2026, 4, 10),
            complete=True,
            completed_at=completed_at_ms,
        )
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(
            item, window, date(2026, 4, 13), datetime(2026, 4, 15, 12, 0)
        )
        assert segments == []

    def test_all_day_completed_early_no_marker(self):
        """A task completed BEFORE its due day was never overdue —
        no marker on any subsequent day. The chip on the due day
        itself shows the COMPLETED_EARLY state."""
        completed_at_ms = int(datetime(2026, 4, 8, 15, 0).timestamp() * 1000)
        item = _make_item(
            due_date=date(2026, 4, 10),
            complete=True,
            completed_at=completed_at_ms,
        )
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(
            item, window, date(2026, 4, 11), datetime(2026, 4, 15, 12, 0)
        )
        assert segments == []


class TestComputeBarSegmentsHourGridSingleDay:
    """Hour-grid items where origin and end are on the same day."""

    def test_workback_on_due_day(self):
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
        )
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(
            item, window, date(2026, 4, 10), datetime(2026, 4, 10, 9, 0)
        )
        assert len(segments) == 1
        seg = segments[0]
        assert seg.is_marker is False
        assert seg.is_all_day is False
        assert seg.start_minute == 13 * 60  # 1 PM
        assert seg.end_minute == 15 * 60  # 3 PM
        assert seg.clipped_top is False
        assert seg.clipped_bottom is False
        assert seg.state == BarState.FUTURE  # current_time is 9 AM, before origin

    def test_event_on_event_day(self):
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(14, 0),
            due_time_end=time(15, 30),
        )
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(
            item, window, date(2026, 4, 10), datetime(2026, 4, 10, 14, 30)
        )
        assert len(segments) == 1
        seg = segments[0]
        assert seg.start_minute == 14 * 60
        assert seg.end_minute == 15 * 60 + 30
        # We're in the middle of the event, no clipping
        assert seg.clipped_top is False
        assert seg.clipped_bottom is False


class TestComputeBarSegmentsCrossDayClipping:
    """Q3: bars that span multiple days produce clipped slices on each day."""

    def test_workback_clipped_top_on_due_day(self):
        """A 4-hour workback to a 2 AM deadline → origin is 10 PM the night
        before. Viewing the due day shows a clipped-top slice from
        midnight to 2 AM."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(2, 0),
            estimated_minutes=240,
        )
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(
            item, window, date(2026, 4, 10), datetime(2026, 4, 10, 1, 0)
        )
        assert len(segments) == 1
        seg = segments[0]
        assert seg.start_minute == 0  # midnight
        assert seg.end_minute == 2 * 60
        assert seg.clipped_top is True
        assert seg.clipped_bottom is False

    def test_workback_clipped_bottom_on_origin_day(self):
        """Same item, viewing the previous day → clipped-bottom slice
        from 10 PM to midnight."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(2, 0),
            estimated_minutes=240,
        )
        window = compute_bar_window(item)
        assert window is not None
        segments = compute_bar_segments(item, window, date(2026, 4, 9), datetime(2026, 4, 9, 23, 0))
        assert len(segments) == 1
        seg = segments[0]
        assert seg.start_minute == 22 * 60  # 10 PM
        assert seg.end_minute == 1440  # midnight (end of day)
        assert seg.clipped_top is False
        assert seg.clipped_bottom is True

    def test_deadline_only_clamped_to_one_hour_single_cell(self):
        """After the Rule 3 clamp, a deadline-only task (no estimate)
        produces a compact 1-hour bar on the due day and NOTHING on
        earlier days — no multi-day bars from ancient created_at."""
        created = datetime(2026, 4, 8, 10, 0)  # 3 days before due
        item = _make_item(
            due_date=date(2026, 4, 11),
            due_time=time(10, 0),
            created_at=_ms(created),
        )
        window = compute_bar_window(item)
        assert window is not None
        # Clamped: origin is 1 hour before due, all on the same day
        assert window.origin == datetime(2026, 4, 11, 9, 0)
        assert window.end == datetime(2026, 4, 11, 10, 0)

        # Viewing Apr 9 (2 days before due) — no segment, because the
        # bar no longer spans multiple days.
        segments_middle = compute_bar_segments(
            item, window, date(2026, 4, 9), datetime(2026, 4, 9, 12, 0)
        )
        # Case: viewing a day after end.date would be Q6 marker path;
        # viewing a day before origin is Case A (empty list). Apr 9
        # is before origin date (Apr 11), so empty.
        assert segments_middle == []

        # Viewing Apr 11 — one compact slice in hour 9 (9:00-10:00)
        segments_due = compute_bar_segments(
            item, window, date(2026, 4, 11), datetime(2026, 4, 11, 8, 0)
        )
        assert len(segments_due) == 1
        seg = segments_due[0]
        assert seg.start_minute == 540  # 9:00
        assert seg.end_minute == 600  # 10:00
        assert seg.clipped_top is False
        assert seg.clipped_bottom is False

    def test_viewing_day_before_origin_empty(self):
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
        )
        window = compute_bar_window(item)
        assert window is not None
        # Origin is 1 PM on Apr 10. Viewing Apr 9.
        segments = compute_bar_segments(item, window, date(2026, 4, 9), datetime(2026, 4, 9, 12, 0))
        assert segments == []


class TestComputeBarSegmentsQ6Marker:
    """Q6: subsequent-day overdue lifecycle."""

    def _overdue_item_window(self) -> tuple[TodoItem, BarWindow]:
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
        )
        window = compute_bar_window(item)
        assert window is not None
        return item, window

    def test_active_overdue_subsequent_day_marker(self):
        """Not complete, viewing day > due day (today is the viewing day)."""
        item, window = self._overdue_item_window()
        # Today = Apr 13, due was Apr 10
        segments = compute_bar_segments(
            item, window, date(2026, 4, 13), datetime(2026, 4, 13, 12, 0)
        )
        assert len(segments) == 1
        seg = segments[0]
        assert seg.is_marker is True
        assert seg.is_all_day is True
        assert seg.state == BarState.OVERDUE_ACTIVE
        assert seg.marker_label is not None
        assert "overdue" in seg.marker_label

    def test_active_overdue_marker_label_uses_format_duration(self):
        """The marker label is the natural-scale duration since due_end."""
        item, window = self._overdue_item_window()
        # Today = 3 days after due
        current = datetime(2026, 4, 13, 15, 0)
        segments = compute_bar_segments(item, window, current.date(), current)
        assert len(segments) == 1
        # Should produce a label like "~3d overdue"
        assert "d" in segments[0].marker_label
        assert "overdue" in segments[0].marker_label

    def test_active_overdue_historical_view_uses_end_of_viewing_day(self):
        """When navigating to a past day where the task was overdue,
        the marker label reflects what was true at end-of-that-day."""
        item, window = self._overdue_item_window()
        # Today is Apr 15 (3 days late and counting), navigating to Apr 12
        segments = compute_bar_segments(
            item, window, date(2026, 4, 12), datetime(2026, 4, 15, 12, 0)
        )
        assert len(segments) == 1
        seg = segments[0]
        assert seg.is_marker is True
        # Apr 12 EOD - Apr 10 15:00 ≈ 1 day 9 hours → format_duration likely "~1d 9h"
        assert seg.marker_label is not None
        assert "overdue" in seg.marker_label

    def test_completed_late_intermediate_day_shows_marker(self):
        """A task completed on Apr 13 with due Apr 10 — viewing Apr 11 (an
        intermediate day) shows the historical marker, not a bar."""
        item, window = self._overdue_item_window()
        item.complete = True
        item.completed_at = _ms(datetime(2026, 4, 13, 11, 0))
        # Viewing Apr 11
        segments = compute_bar_segments(
            item, window, date(2026, 4, 11), datetime(2026, 4, 14, 12, 0)
        )
        assert len(segments) == 1
        seg = segments[0]
        assert seg.is_marker is True
        assert seg.state == BarState.OVERDUE_ACTIVE  # historical truth on that day

    def test_completed_late_completion_day_shows_bar(self):
        """The completion day itself shows a bar with the late portion in
        the visual, NOT a marker. compute_bar_segments delegates to
        _hour_grid_segment with a synthetic window ending at completed_at."""
        item, window = self._overdue_item_window()
        item.complete = True
        item.completed_at = _ms(datetime(2026, 4, 13, 11, 0))
        # Viewing Apr 13 (completion day)
        segments = compute_bar_segments(
            item, window, date(2026, 4, 13), datetime(2026, 4, 14, 12, 0)
        )
        assert len(segments) == 1
        seg = segments[0]
        assert seg.is_marker is False  # bar, not marker
        # State should be COMPLETED_LATE
        assert seg.state == BarState.COMPLETED_LATE

    def test_completed_late_after_completion_day_no_segment(self):
        """A day after the completion day shows nothing — the task is
        fully done and behind us."""
        item, window = self._overdue_item_window()
        item.complete = True
        item.completed_at = _ms(datetime(2026, 4, 13, 11, 0))
        # Viewing Apr 14 (after completion)
        segments = compute_bar_segments(
            item, window, date(2026, 4, 14), datetime(2026, 4, 14, 12, 0)
        )
        assert segments == []

    def test_completed_early_no_marker_on_subsequent_day(self):
        """A task completed at or before due_end never produces a Q6 marker
        on subsequent days — there was no overdue period."""
        item, window = self._overdue_item_window()
        item.complete = True
        item.completed_at = _ms(window.end - timedelta(minutes=30))
        # Viewing the day after due
        segments = compute_bar_segments(
            item, window, date(2026, 4, 11), datetime(2026, 4, 11, 12, 0)
        )
        assert segments == []

    def test_completed_unknown_no_marker_on_subsequent_day(self):
        """COMPLETED_UNKNOWN: we don't know when it was finished, so we
        can't honestly say it was overdue on day X. No marker."""
        item, window = self._overdue_item_window()
        item.complete = True
        item.completed_at = None
        # Viewing the day after due
        segments = compute_bar_segments(
            item, window, date(2026, 4, 11), datetime(2026, 4, 11, 12, 0)
        )
        assert segments == []


class TestComputeBarSegmentsFutureViewingDay:
    """Future viewing days use current_time as the reference moment, not
    end-of-viewing-day. Asking "will this be overdue by midnight of a future
    day?" is semantically wrong for a planning view — the user wants to see
    "as of right now, is the task's window open?" Before the fix this path
    painted every future-dated bar as OVERDUE_ACTIVE from the moment the
    week was rendered, which was visually indistinguishable from a real
    past-due task."""

    def test_future_day_non_recurring_renders_future(self):
        """A normal non-recurring task dated in the future renders FUTURE
        when viewed from an earlier day, not OVERDUE_ACTIVE."""
        item = _make_item(
            due_date=date(2026, 4, 13),
            due_time=time(13, 0),
            estimated_minutes=30,
            complete=False,
        )
        window = compute_bar_window(item)
        assert window is not None
        # Today is Apr 10 (three days before the due day)
        segs = compute_bar_segments(item, window, date(2026, 4, 13), datetime(2026, 4, 10, 9, 49))
        assert len(segs) == 1
        assert segs[0].is_marker is False
        assert segs[0].state == BarState.FUTURE

    def test_future_day_all_day_renders_future(self):
        """An ALL_DAY task dated in the future renders FUTURE too — the
        previous end-of-viewing-day semantics would have classified it as
        OVERDUE_ACTIVE on every day preceding its due date."""
        item = _make_item(due_date=date(2026, 4, 13), complete=False)
        window = compute_bar_window(item)
        assert window is not None
        segs = compute_bar_segments(item, window, date(2026, 4, 13), datetime(2026, 4, 10, 9, 49))
        assert len(segs) == 1
        assert segs[0].is_all_day is True
        assert segs[0].state == BarState.FUTURE

    def test_past_day_still_uses_end_of_day(self):
        """Past viewing days retain the historical end-of-day semantics —
        the marker on Apr 12 must reflect "overdue by end of Apr 12", not
        "overdue as of current_time"."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
            complete=False,
        )
        window = compute_bar_window(item)
        assert window is not None
        # Today is Apr 15, viewing Apr 12 (past day)
        segs = compute_bar_segments(item, window, date(2026, 4, 12), datetime(2026, 4, 15, 12, 0))
        assert len(segs) == 1
        assert segs[0].is_marker is True
        assert segs[0].state == BarState.OVERDUE_ACTIVE


class TestComputeBarSegmentsAsOfCapping:
    """The as_of value is capped at completed_at for completed items so
    historical days past completion show the final state, not 'still active.'"""

    def test_completed_state_persists_when_viewing_long_after(self):
        """A task completed on Apr 13 viewed in 2027 still renders as
        COMPLETED_LATE (cap behavior), not as OVERDUE_ACTIVE."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
            complete=True,
            completed_at=_ms(datetime(2026, 4, 13, 11, 0)),
        )
        window = compute_bar_window(item)
        assert window is not None
        # Viewing the completion day from very far in the future
        segments = compute_bar_segments(
            item, window, date(2026, 4, 13), datetime(2027, 12, 31, 23, 0)
        )
        assert len(segments) == 1
        assert segments[0].state == BarState.COMPLETED_LATE


# ===========================================================================
# Integration smoke tests — combinations the spec lifecycle table covers
# ===========================================================================


class TestQ6LifecycleTableComplete:
    """Walks every row in the Q6 lifecycle table from the design doc.

    Setup: workback task with origin Apr 10 1 PM, due Apr 10 3 PM.
    """

    def _setup(self) -> tuple[TodoItem, BarWindow]:
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
        )
        window = compute_bar_window(item)
        assert window is not None
        return item, window

    def test_row1_not_complete_viewing_due_day(self):
        """Bar in hour grid, growing past due_time in OVERDUE_ACTIVE."""
        item, window = self._setup()
        # current_time = 5 PM on due day (2 hours past due)
        segs = compute_bar_segments(item, window, date(2026, 4, 10), datetime(2026, 4, 10, 17, 0))
        assert len(segs) == 1
        assert segs[0].is_marker is False
        assert segs[0].state == BarState.OVERDUE_ACTIVE

    def test_row2_not_complete_viewing_today_after_due_day(self):
        item, window = self._setup()
        segs = compute_bar_segments(item, window, date(2026, 4, 13), datetime(2026, 4, 13, 12, 0))
        assert len(segs) == 1
        assert segs[0].is_marker is True
        assert segs[0].state == BarState.OVERDUE_ACTIVE

    def test_row3_not_complete_viewing_past_day(self):
        """Today is Apr 15, navigating to Apr 12 (a past intermediate day)."""
        item, window = self._setup()
        segs = compute_bar_segments(item, window, date(2026, 4, 12), datetime(2026, 4, 15, 12, 0))
        assert len(segs) == 1
        assert segs[0].is_marker is True
        assert segs[0].state == BarState.OVERDUE_ACTIVE

    def test_row4_not_complete_viewing_future_day(self):
        """Today is Apr 11, navigating to Apr 13 (a future projection).

        Markers are suppressed on future viewing days — they are
        historical truth and current state only. Projected overdue
        markers would flood the All Day row with spurious chips."""
        item, window = self._setup()
        segs = compute_bar_segments(item, window, date(2026, 4, 13), datetime(2026, 4, 11, 12, 0))
        assert segs == []

    def test_row5_complete_viewing_completion_day(self):
        """Bar in hour grid with two-zone visual via COMPLETED_LATE state."""
        item, window = self._setup()
        item.complete = True
        item.completed_at = _ms(datetime(2026, 4, 13, 11, 0))
        segs = compute_bar_segments(item, window, date(2026, 4, 13), datetime(2026, 4, 14, 12, 0))
        assert len(segs) == 1
        assert segs[0].is_marker is False
        assert segs[0].state == BarState.COMPLETED_LATE

    def test_row6_complete_viewing_intermediate_day(self):
        """Marker (historical truth)."""
        item, window = self._setup()
        item.complete = True
        item.completed_at = _ms(datetime(2026, 4, 13, 11, 0))
        segs = compute_bar_segments(item, window, date(2026, 4, 11), datetime(2026, 4, 14, 12, 0))
        assert len(segs) == 1
        assert segs[0].is_marker is True

    def test_row7_complete_viewing_day_before_due(self):
        """Standard bar, FUTURE or IN_WORK_WINDOW state."""
        # We need a longer window so 'before due' is meaningful
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=24 * 60 * 2,  # 2 days back
            complete=True,
            completed_at=_ms(datetime(2026, 4, 11, 9, 0)),
        )
        window = compute_bar_window(item)
        assert window is not None
        # Origin is Apr 8 3 PM. Viewing Apr 9 (between origin and due day).
        segs = compute_bar_segments(item, window, date(2026, 4, 9), datetime(2026, 4, 11, 12, 0))
        assert len(segs) == 1
        assert segs[0].is_marker is False
        # On Apr 9 EOD (capped at completed_at since complete), state is...
        # completed_at is Apr 11 9 AM, which is past EOD Apr 9, so as_of is
        # EOD Apr 9. The item is complete though, so state lookup uses the
        # completed branch → COMPLETED_LATE (since completed_at > end).
        assert segs[0].state == BarState.COMPLETED_LATE

    def test_row8_complete_viewing_after_completion(self):
        """No marker, no bar — task is fully done."""
        item, window = self._setup()
        item.complete = True
        item.completed_at = _ms(datetime(2026, 4, 13, 11, 0))
        segs = compute_bar_segments(item, window, date(2026, 4, 14), datetime(2026, 4, 14, 12, 0))
        assert segs == []


# ===========================================================================
# BarSegment NamedTuple sanity
# ===========================================================================


class TestBarSegmentDataclass:
    def test_named_tuple_field_count(self):
        """Defensive: BarSegment has the expected 9 fields. Adding a field
        without updating tests would be caught here."""
        assert len(BarSegment._fields) == 9

    def test_named_tuple_immutable(self):
        """NamedTuples are immutable — assigning a field raises."""
        seg = BarSegment(
            item_id=_make_item().id,
            start_minute=0,
            end_minute=60,
            state=BarState.IN_WORK_WINDOW,
            clipped_top=False,
            clipped_bottom=False,
            is_marker=False,
            marker_label=None,
            is_all_day=False,
        )
        with pytest.raises(AttributeError):
            seg.start_minute = 100  # type: ignore[misc]


# ===========================================================================
# Fix A: future-day overdue markers are suppressed
# ===========================================================================


class TestFutureDayMarkersSuppressed:
    """Markers are historical truth and current state only. On future
    viewing days, the task lives in its actual bar/chip — projected
    overdue markers are noise that floods the All Day row."""

    def test_hour_grid_no_marker_on_future_day(self):
        """An overdue hour-grid task viewed on a future day produces no
        marker segment."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
            complete=False,
        )
        window = compute_bar_window(item)
        assert window is not None
        # Today is Apr 11, viewing Apr 13 (a future day)
        segs = compute_bar_segments(item, window, date(2026, 4, 13), datetime(2026, 4, 11, 12, 0))
        assert segs == []

    def test_all_day_no_marker_on_future_day(self):
        """An overdue all-day task viewed on a future day produces no
        marker segment."""
        item = _make_item(due_date=date(2026, 4, 10), complete=False)
        window = compute_bar_window(item)
        assert window is not None
        # Today is Apr 11, viewing Apr 13 (a future day)
        segs = compute_bar_segments(item, window, date(2026, 4, 13), datetime(2026, 4, 11, 12, 0))
        assert segs == []

    def test_marker_still_emitted_on_today(self):
        """Markers are still produced when viewing_day == current_time.date()."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
            complete=False,
        )
        window = compute_bar_window(item)
        assert window is not None
        # Today is Apr 13 and we are viewing today
        segs = compute_bar_segments(item, window, date(2026, 4, 13), datetime(2026, 4, 13, 12, 0))
        assert len(segs) == 1
        assert segs[0].is_marker is True
        assert segs[0].state == BarState.OVERDUE_ACTIVE

    def test_marker_still_emitted_on_past_day(self):
        """Markers are still produced when viewing a past day."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
            complete=False,
        )
        window = compute_bar_window(item)
        assert window is not None
        # Today is Apr 15, viewing Apr 12 (a past day after due)
        segs = compute_bar_segments(item, window, date(2026, 4, 12), datetime(2026, 4, 15, 12, 0))
        assert len(segs) == 1
        assert segs[0].is_marker is True

    def test_completed_late_future_day_no_marker(self):
        """Even a completed-late task produces no marker on a future viewing
        day that would normally be an intermediate day."""
        item = _make_item(
            due_date=date(2026, 4, 10),
            due_time=time(15, 0),
            estimated_minutes=120,
            complete=True,
            completed_at=_ms(datetime(2026, 4, 15, 11, 0)),
        )
        window = compute_bar_window(item)
        assert window is not None
        # Today is Apr 11, viewing Apr 13 (future, but would be intermediate)
        segs = compute_bar_segments(item, window, date(2026, 4, 13), datetime(2026, 4, 11, 12, 0))
        assert segs == []


# ===========================================================================
# Fix C: recurring tasks exempt from midnight rollback
# ===========================================================================


class TestRecurringMidnightRollbackExempt:
    """Recurring tasks with due_time=00:00 render on their due_date,
    not the previous day. The midnight rollback is for one-time tasks
    only — recurring tasks mean 'start of that day'."""

    def test_recurring_midnight_renders_on_due_date(self):
        """A recurring task with due_time=00:00 on Apr 12 renders a bar
        segment on Apr 12, NOT Apr 11."""
        item = _make_item(
            due_date=date(2026, 4, 12),
            due_time=time(0, 0),
            estimated_minutes=60,
            recurrence_type="daily",
            recurrence_interval=1,
        )
        window = compute_bar_window(item)
        assert window is not None
        # Window should end at midnight of Apr 12 (= 00:00 on Apr 12)
        assert window.end == datetime(2026, 4, 12, 0, 0)

        # Viewing Apr 12 — should get a segment (the bar lives here)
        segs_apr12 = compute_bar_segments(
            item, window, date(2026, 4, 12), datetime(2026, 4, 12, 8, 0)
        )
        # The bar's end_day for recurring should be Apr 12 (no rollback),
        # and viewing Apr 12 means we are within [origin_day, end_day].
        # The bar origin is 23:00 Apr 11 (workback 1 hour from midnight).
        # So on Apr 12, start_minute=0, end_minute=0 which is an empty
        # slice — the segment actually lives on Apr 11. But crucially,
        # Apr 12 should NOT produce a Q6 marker (which was the bug:
        # without the fix, end_day rolled back to Apr 11, and viewing
        # Apr 12 was > end_day, triggering spurious marker mode).
        # With the fix, end_day stays Apr 12, viewing Apr 12 <= end_day,
        # so no marker is produced.
        for seg in segs_apr12:
            assert seg.is_marker is False

    def test_nonrecurring_midnight_still_rolls_back(self):
        """A one-time task with due_time=00:00 still gets the midnight
        rollback behavior — the bar belongs to the previous day."""
        item = _make_item(
            due_date=date(2026, 4, 12),
            due_time=time(0, 0),
            estimated_minutes=60,
            # No recurrence_type — one-time task
        )
        window = compute_bar_window(item)
        assert window is not None
        assert window.end == datetime(2026, 4, 12, 0, 0)

        # Viewing Apr 11 — bar should render here (workback from midnight
        # gives origin 23:00 Apr 11, same day as the rolled-back end_day)
        segs_apr11 = compute_bar_segments(
            item, window, date(2026, 4, 11), datetime(2026, 4, 11, 20, 0)
        )
        assert len(segs_apr11) == 1
        seg = segs_apr11[0]
        assert seg.is_marker is False
        assert seg.start_minute == 23 * 60  # 11 PM
        assert seg.end_minute == 1440  # midnight

    def test_recurring_midnight_no_spurious_marker_day_after(self):
        """The key regression this fix prevents: a recurring task with
        due_time=00:00 on Apr 12 must NOT produce a Q6 overdue marker
        on Apr 12 (which would happen if end_day rolled back to Apr 11)."""
        item = _make_item(
            due_date=date(2026, 4, 12),
            due_time=time(0, 0),
            estimated_minutes=60,
            recurrence_type="weekly",
            recurrence_interval=1,
            complete=False,
        )
        window = compute_bar_window(item)
        assert window is not None

        # Without the fix, end_day would be Apr 11 (rolled back), and
        # viewing Apr 12 > Apr 11 would trigger _maybe_marker_segment.
        # With the fix, end_day stays Apr 12, viewing Apr 12 <= end_day,
        # so we go through _hour_grid_segment (or empty slice) instead.
        segs = compute_bar_segments(item, window, date(2026, 4, 12), datetime(2026, 4, 12, 8, 0))
        for seg in segs:
            assert seg.is_marker is False, (
                f"Recurring task should not produce a marker on its due_date; "
                f"got marker with label={seg.marker_label}"
            )
