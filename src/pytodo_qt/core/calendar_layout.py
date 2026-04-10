"""calendar_layout.py

Pure-function layer for the calendar Gantt-bar rendering model.

This module is the source of truth for the seven locked decisions in
docs/plans/calendar-gantt-redesign.md. It has zero Qt imports — every
function is pure Python and unit-testable in isolation.

The delegate layer in gui/widgets/calendar_view.py consumes the output
of these functions; it does not duplicate the logic. If a layout question
arises during rendering, the answer lives here.

Key types:
    BarState     — lifecycle state enum (8 states)
    WindowKind   — origin-rule classification (4 kinds, one per Q1 rule)
    BarWindow    — (origin, end, kind) for an item
    BarSegment   — drawable slice of a bar for one viewing day

Key functions:
    compute_bar_window(item)                           — Q1 origin rules
    compute_bar_state(item, window, as_of)             — Q5 lifecycle state
    compute_bar_segments(item, window, viewing_day,    — Q3 clipping +
                         current_time)                   Q6 marker mode
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from .models import format_duration

if TYPE_CHECKING:
    from .models import TodoItem


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BarState(Enum):
    """Lifecycle state of a task as of a reference moment in time.

    The state depends on the relationship between `as_of` and the bar's
    origin/end timestamps, plus the item's `complete` flag and
    `completed_at` value.

    See docs/plans/calendar-gantt-redesign.md Q5.
    """

    FUTURE = "future"  # as_of < origin
    IN_WORK_WINDOW = "in_work_window"  # origin <= as_of < (end - DUE_NOW_THRESHOLD)
    DUE_NOW = "due_now"  # within DUE_NOW_THRESHOLD of end (and not yet past)
    OVERDUE_ACTIVE = "overdue_active"  # as_of > end AND not complete
    COMPLETED_EARLY = "completed_early"  # complete AND completed_at < end
    COMPLETED_ONTIME = "completed_ontime"  # complete AND completed_at == end
    COMPLETED_LATE = "completed_late"  # complete AND completed_at > end
    COMPLETED_UNKNOWN = "completed_unknown"  # complete AND completed_at IS NULL


class WindowKind(Enum):
    """Which Q1 origin rule applies to this item.

    See docs/plans/calendar-gantt-redesign.md Q1.
    """

    EVENT = "event"  # due_time + due_time_end → event range
    WORKBACK = "workback"  # due_time + estimated_minutes → work-back from deadline
    DEADLINE_FROM_CREATED = "deadline_from_created"  # due_time only → from created_at
    ALL_DAY = "all_day"  # due_date only, no due_time → All Day row


# Threshold for the DUE_NOW state. Refinable per spec Q5; locked at 15
# minutes as the starting value. Pre-deadline alerting only — completion
# classification (EARLY/ONTIME/LATE) uses no fuzz.
DUE_NOW_THRESHOLD = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class BarWindow(NamedTuple):
    """The temporal window a task occupies, computed via Q1's four rules.

    For ALL_DAY items, origin is the start of due_date (00:00 local) and
    end is the start of the next day (00:00 local of the day after).
    """

    origin: datetime
    end: datetime
    kind: WindowKind


class BarSegment(NamedTuple):
    """A drawable slice of a bar for a single viewing day.

    Either a hour-grid bar segment or a Q6 overdue marker. The delegate
    chooses the rendering style based on `is_marker` and `is_all_day`.

    `start_minute` and `end_minute` are minute offsets within the viewing
    day's 24-hour grid (0..1440). For markers and all-day segments, the
    minute fields are not meaningful for time-grid placement; they default
    to 0..1440 so callers that range-check still get sensible bounds.

    `clipped_top` is True when the segment's true origin is before the
    viewing day's midnight (the bar continues earlier). `clipped_bottom`
    is True when the segment's true end is after the next midnight (the
    bar continues later). The delegate paints an edge marker on clipped
    sides per Q3.
    """

    item_id: UUID
    start_minute: int
    end_minute: int
    state: BarState
    clipped_top: bool
    clipped_bottom: bool
    is_marker: bool
    marker_label: str | None
    is_all_day: bool


# ---------------------------------------------------------------------------
# compute_bar_window — Q1 origin rules
# ---------------------------------------------------------------------------


def compute_bar_window(item: TodoItem) -> BarWindow | None:
    """Compute the bar window for an item per Q1's four rules.

    Returns None if the item has no temporal anchor (no due_date),
    indicating it should not appear in the calendar grid at all.

    Sanitization: any rule that produces end < origin (negative duration)
    falls through to the next applicable rule. Sanitization happens here,
    at the layout layer, not by mutating the model.

    The four rules in order:
        EVENT                  due_time AND due_time_end
        WORKBACK               due_time AND estimated_minutes > 0
        DEADLINE_FROM_CREATED  due_time only (no estimate, no end)
        ALL_DAY                due_date only (no due_time)
    """
    if item.due_date is None:
        return None

    base_date = item.due_date

    # Rule 1: EVENT — both endpoints set explicitly
    if item.due_time is not None and item.due_time_end is not None:
        origin = datetime.combine(base_date, item.due_time)
        end = datetime.combine(base_date, item.due_time_end)
        if end > origin:
            return BarWindow(origin=origin, end=end, kind=WindowKind.EVENT)
        # Otherwise fall through to the next rule (sanitization)

    # Rule 2: WORKBACK — due_time + positive estimate
    if item.due_time is not None and item.estimated_minutes > 0:
        end = datetime.combine(base_date, item.due_time)
        origin = end - timedelta(minutes=item.estimated_minutes)
        if end > origin:
            return BarWindow(origin=origin, end=end, kind=WindowKind.WORKBACK)
        # Sanitization: estimated_minutes <= 0 is technically caught by the
        # condition above, but a future negative-estimate case would fall
        # through here.

    # Rule 3: DEADLINE_FROM_CREATED — due_time only, origin from created_at
    if item.due_time is not None:
        end = datetime.combine(base_date, item.due_time)
        origin = datetime.fromtimestamp(item.created_at / 1000)
        if end > origin:
            return BarWindow(origin=origin, end=end, kind=WindowKind.DEADLINE_FROM_CREATED)
        # Sanitization: created_at after due_time means the deadline is
        # already in the past at creation time. Fall through to ALL_DAY
        # so the item still shows up somewhere honest (the All Day row of
        # its due date).

    # Rule 4: ALL_DAY — due_date with no usable time anchor
    origin = datetime.combine(base_date, time(0, 0, 0))
    end = datetime.combine(base_date + timedelta(days=1), time(0, 0, 0))
    return BarWindow(origin=origin, end=end, kind=WindowKind.ALL_DAY)


# ---------------------------------------------------------------------------
# compute_bar_state — Q5 lifecycle classification
# ---------------------------------------------------------------------------


def compute_bar_state(item: TodoItem, window: BarWindow, as_of: datetime) -> BarState:
    """Classify a task's lifecycle state as of a reference moment.

    The `as_of` argument is the reference time. For the live view of
    today's column it is `datetime.now()`; for past or future days it is
    the latest moment of the viewing day (end-of-day). compute_bar_segments
    is responsible for choosing the right `as_of` value.

    Completion classification is exact (no fuzz):
        EARLY  = completed_at < end
        ONTIME = completed_at == end (exact match only)
        LATE   = completed_at > end

    UNKNOWN is reserved for items completed before schema v19 introduced
    the timestamp column — `complete=True AND completed_at IS NULL`.
    """
    if item.complete:
        if item.completed_at is None:
            return BarState.COMPLETED_UNKNOWN
        completed_dt = datetime.fromtimestamp(item.completed_at / 1000)
        if completed_dt < window.end:
            return BarState.COMPLETED_EARLY
        if completed_dt == window.end:
            return BarState.COMPLETED_ONTIME
        return BarState.COMPLETED_LATE

    # Not complete — state depends on `as_of` relative to the window.
    if as_of < window.origin:
        return BarState.FUTURE
    if as_of >= window.end:
        return BarState.OVERDUE_ACTIVE
    # Within the planned window. DUE_NOW kicks in for the last
    # DUE_NOW_THRESHOLD minutes before end.
    if as_of >= window.end - DUE_NOW_THRESHOLD:
        return BarState.DUE_NOW
    return BarState.IN_WORK_WINDOW


# ---------------------------------------------------------------------------
# compute_bar_segments — Q3 clipping + Q6 marker mode
# ---------------------------------------------------------------------------


def _as_of_for_viewing_day(viewing_day: date, current_time: datetime) -> datetime:
    """Compute the reference moment for state evaluation on a viewing day.

    For today, the reference is `current_time` (so live updates advance the
    state). For any other day (past or future), the reference is the end of
    that day, so the visual answers "what was/will be true at the latest
    moment of this day."
    """
    if viewing_day == current_time.date():
        return current_time
    return datetime.combine(viewing_day, time(23, 59, 59))


def _minute_of_day(dt: datetime, day: date) -> int:
    """Convert a datetime to a minute offset within `day`.

    Returns 0 if dt is at or before day-start, 1440 if at or after the next
    day-start. Otherwise returns hour*60 + minute, snapped to the [0, 1440]
    range.
    """
    day_start = datetime.combine(day, time(0, 0, 0))
    next_day_start = datetime.combine(day + timedelta(days=1), time(0, 0, 0))
    if dt <= day_start:
        return 0
    if dt >= next_day_start:
        return 1440
    return dt.hour * 60 + dt.minute


def compute_bar_segments(
    item: TodoItem,
    window: BarWindow,
    viewing_day: date,
    current_time: datetime,
) -> list[BarSegment]:
    """Compute the visible bar segments for a task on a viewing day.

    Returns:
        - Empty list if the bar does not intersect this viewing day.
        - One BarSegment for an all-day item that lives on its due_date.
        - One BarSegment for a hour-grid item slice that intersects this day.
        - One marker BarSegment for the Q6 subsequent-day overdue case
          (overrides the hour-grid bar on days strictly after due_end's day
          when the task is OVERDUE_ACTIVE or historically was on that day).

    Q6 marker lifecycle:
        - Not complete, viewing_day > end.date()              → marker (active overdue)
        - Complete late, viewing_day in (end.date(), completed_at.date())
                                                              → marker (historical truth)
        - Complete late, viewing_day == completed_at.date()   → bar (two-zone visual)
        - Complete late, viewing_day > completed_at.date()    → no marker, no bar
        - Complete late, viewing_day < end.date()             → bar (FUTURE/IN_WORK_WINDOW)

    The delegate uses BarSegment.is_marker / .is_all_day to choose the
    rendering treatment.
    """
    # ALL_DAY items live on their due_date row regardless of state.
    if window.kind == WindowKind.ALL_DAY:
        if viewing_day != window.origin.date():
            return []
        as_of = _as_of_for_viewing_day(viewing_day, current_time)
        # Cap as_of at completed_at for completed items so historical days
        # past the completion show the final state, not "still active."
        if item.complete and item.completed_at is not None:
            completed_dt = datetime.fromtimestamp(item.completed_at / 1000)
            if as_of > completed_dt:
                as_of = completed_dt
        state = compute_bar_state(item, window, as_of)
        return [
            BarSegment(
                item_id=item.id,
                start_minute=0,
                end_minute=1440,
                state=state,
                clipped_top=False,
                clipped_bottom=False,
                is_marker=False,
                marker_label=None,
                is_all_day=True,
            )
        ]

    # Hour-grid items.
    end_day = window.end.date()
    origin_day = window.origin.date()

    # Case A: viewing day is before the bar's origin day → bar not yet visible.
    if viewing_day < origin_day:
        return []

    # Case B: Q6 marker mode — viewing day is strictly after the bar's
    # planned end day. Whether to render a marker depends on the item's
    # complete state and (if complete) the relationship to completed_at.
    if viewing_day > end_day:
        return _maybe_marker_segment(item, window, viewing_day, current_time)

    # Case C: viewing day is within [origin_day, end_day] (inclusive of
    # both). Render a clipped slice of the bar in the hour grid.
    return _hour_grid_segment(item, window, viewing_day, current_time)


def _hour_grid_segment(
    item: TodoItem,
    window: BarWindow,
    viewing_day: date,
    current_time: datetime,
) -> list[BarSegment]:
    """Render a single hour-grid slice of the bar for a viewing day.

    Called when viewing_day is in [window.origin.date(), window.end.date()].
    Computes start_minute / end_minute by clipping at the day boundaries
    and sets clipped_top / clipped_bottom flags accordingly.
    """
    start_minute = _minute_of_day(window.origin, viewing_day)
    end_minute = _minute_of_day(window.end, viewing_day)

    # Sanitization: an empty slice (start >= end) means the bar's range
    # didn't actually intersect this day's hours. This shouldn't normally
    # happen because Case C in compute_bar_segments only fires when
    # viewing_day is in [origin.date(), end.date()], but defend anyway.
    if start_minute >= end_minute:
        return []

    clipped_top = window.origin.date() < viewing_day
    clipped_bottom = window.end.date() > viewing_day

    as_of = _as_of_for_viewing_day(viewing_day, current_time)
    if item.complete and item.completed_at is not None:
        completed_dt = datetime.fromtimestamp(item.completed_at / 1000)
        if as_of > completed_dt:
            as_of = completed_dt
    state = compute_bar_state(item, window, as_of)

    return [
        BarSegment(
            item_id=item.id,
            start_minute=start_minute,
            end_minute=end_minute,
            state=state,
            clipped_top=clipped_top,
            clipped_bottom=clipped_bottom,
            is_marker=False,
            marker_label=None,
            is_all_day=False,
        )
    ]


def _maybe_marker_segment(
    item: TodoItem,
    window: BarWindow,
    viewing_day: date,
    current_time: datetime,
) -> list[BarSegment]:
    """Compute the Q6 marker segment for a viewing day strictly after end day.

    Returns empty list if no marker should appear (e.g., item is complete
    and viewing_day is after the completion day).
    """
    end_day = window.end.date()

    if not item.complete:
        # Active overdue marker on every day after the due day.
        as_of_for_label = _as_of_for_viewing_day(viewing_day, current_time)
        return [_make_marker(item, window, as_of_for_label, BarState.OVERDUE_ACTIVE)]

    # Complete: marker behavior depends on completed_at relative to viewing_day.
    if item.completed_at is None:
        # COMPLETED_UNKNOWN — no historical marker (we don't know when it
        # was completed, so we can't honestly say it was overdue on day X).
        # The bar lives on its end_day in the hour grid; on subsequent
        # days it does not appear at all.
        return []

    completed_dt = datetime.fromtimestamp(item.completed_at / 1000)
    completed_day = completed_dt.date()

    if completed_day <= end_day:
        # Item was completed at or before the due day, so no overdue
        # period existed. No marker on subsequent days; the bar lives on
        # the end day with COMPLETED_EARLY/ONTIME visual.
        return []

    # Late completion: completed_day > end_day.
    if viewing_day < completed_day:
        # Historical: on this day, the task was overdue-active. Show a
        # marker that reflects what was true at end-of-day on viewing_day.
        as_of_for_label = _as_of_for_viewing_day(viewing_day, current_time)
        return [_make_marker(item, window, as_of_for_label, BarState.OVERDUE_ACTIVE)]

    if viewing_day == completed_day:
        # Spec: completion day shows the bar with two-zone visual, NOT a
        # marker. Build the segment manually so the layout extends from
        # midnight (clipped_top because the bar's true origin is days
        # earlier) to completed_at, while the state is computed from the
        # ORIGINAL window so it correctly classifies as COMPLETED_LATE.
        start_minute = _minute_of_day(window.origin, viewing_day)
        end_minute = _minute_of_day(completed_dt, viewing_day)
        if start_minute >= end_minute:
            return []
        # State always uses the original window — the completed_at is
        # past window.end, which produces COMPLETED_LATE.
        state = compute_bar_state(item, window, completed_dt)
        return [
            BarSegment(
                item_id=item.id,
                start_minute=start_minute,
                end_minute=end_minute,
                state=state,
                clipped_top=window.origin.date() < viewing_day,
                clipped_bottom=False,  # The bar truly ends here at completed_at
                is_marker=False,
                marker_label=None,
                is_all_day=False,
            )
        ]

    # viewing_day > completed_day → no marker, no bar (task is fully done).
    return []


def _make_marker(
    item: TodoItem,
    window: BarWindow,
    as_of: datetime,
    state: BarState,
) -> BarSegment:
    """Build a Q6 marker BarSegment with a duration label.

    The label uses format_duration() against the elapsed time from
    window.end to `as_of`, giving a natural-scale string like
    "~3d overdue" or "~2w overdue". Q2 contract: minutes for the
    calculation, natural units for the display.
    """
    elapsed = as_of - window.end
    elapsed_minutes = max(0, int(elapsed.total_seconds() // 60))
    label = f"{format_duration(elapsed_minutes)} overdue"
    return BarSegment(
        item_id=item.id,
        start_minute=0,
        end_minute=1440,
        state=state,
        clipped_top=False,
        clipped_bottom=False,
        is_marker=True,
        marker_label=label,
        is_all_day=True,  # Markers live in the All Day row
    )
