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
    WindowKind   — origin-rule classification (one kind per Q1 rule)
    BarWindow    — (origin, end, kind) for an item
    BarSegment   — drawable slice of a bar for one viewing day

Key functions:
    compute_bar_window(item)                           — Q1 origin rules
    compute_bar_state(item, window, as_of)             — Q5 lifecycle state
    compute_bar_segments(item, window, viewing_day,    — Q3 clipping +
                         current_time)                   Q6 marker mode
    assign_lanes(spans)                                — side-by-side lanes
                                                         for bars of one day
                                                         that share time
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from .models import format_duration

if TYPE_CHECKING:
    from .config import TimeBlockConfig
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
    BLOCK = "block"  # named time block, no due_time → the block's own window
    ALL_DAY = "all_day"  # due_date only, no due_time or block → All Day row


# Threshold for the DUE_NOW state. Refinable per spec Q5; locked at 15
# minutes as the starting value. Pre-deadline alerting only — completion
# classification (EARLY/ONTIME/LATE) uses no fuzz.
DUE_NOW_THRESHOLD = timedelta(minutes=15)

# Maximum visible width for a Q1 Rule 3 (DEADLINE_FROM_CREATED) bar.
# Without this clamp, a recurring task that's been around for a week
# with due_time=10:00 would produce a bar spanning 7 days — which
# renders on today's grid as a huge stretch from midnight to 10:00,
# covering 10+ hour cells. The clamp makes the bar compact and
# informative: "this is due at X, and we're showing the last hour
# leading up to that time as a focus window."
DEADLINE_DEFAULT_DURATION = timedelta(hours=1)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class BarWindow(NamedTuple):
    """The temporal window a task occupies, computed via Q1's rules.

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

    `zone_start_minute` and `zone_end_minute` bound the deviation zone
    of a completed bar on this day, and are None where there is none.
    For a task finished early it is the stretch from the completion to
    the planned end; for one finished late, the stretch from the planned
    end to the completion, which the segment runs on to. The zone lies
    within the segment, and whoever draws the bar draws it from these.
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
    zone_start_minute: int | None = None
    zone_end_minute: int | None = None

    @property
    def due_edge_minute(self) -> int | None:
        """The minute of this day at which the bar's planned span ends.

        None where the planned end is not on this day. A bar that runs
        on past its planned end, to a late completion, has that end
        where its zone begins and not at its own end.
        """
        if self.clipped_bottom:
            return None
        if self.state == BarState.COMPLETED_LATE and self.zone_start_minute is not None:
            if self.zone_start_minute <= self.start_minute:
                # All of the segment is past the planned end.
                return None
            return self.zone_start_minute
        return self.end_minute


# ---------------------------------------------------------------------------
# compute_bar_window — Q1 origin rules
# ---------------------------------------------------------------------------


def get_default_work_minutes() -> int:
    """Read the user's current pomodoro work duration default from config.

    This is the value that bars use when a task has no per-task
    `work_duration` override. Reading from config (rather than a
    hardcoded constant) ensures bars always match the user's actual
    settings — change the pomodoro default to 10, every task without
    an override re-renders with 10-minute pomodoros.

    Returns 25 (the spec default) if config can't be loaded for any
    reason.
    """
    try:
        from .config import get_config

        cfg = get_config()
        return max(1, cfg.pomodoro.work_duration)
    except Exception:
        return 25


def _effective_work_minutes(item: TodoItem, default_work_minutes: int = 25) -> int:
    """Return the task's effective duration in minutes for WORKBACK.

    `estimated_minutes` and `estimated_pomodoros * work_duration` are
    ALTERNATIVE expressions of the same quantity (task duration), not
    additive components. We take the MAX of the two interpretations.

    Per-task `work_duration` takes precedence over the global default.
    When a task has `work_duration=0` (not set), we fall back to the
    `default_work_minutes` parameter — which the calendar widget passes
    in from the user's current pomodoro settings (PomodoroConfig.
    work_duration). This ensures bars match the user's actual settings,
    not a hardcoded constant.

    Examples:
      estimated_minutes=25, no pomodoros           → 25
      estimated_pomodoros=1, work_duration=10      → 10 (per-task wins)
      estimated_pomodoros=3, work_duration=0,
        default_work_minutes=10                    → 30
      estimated_pomodoros=3, work_duration=0,
        default_work_minutes=25                    → 75
      estimated_minutes=25, estimated_pomodoros=3,
        default_work_minutes=25                    → max(25, 75) = 75

    Returns 0 when the task has no duration information.
    """
    direct = max(0, item.estimated_minutes)
    pom_count = max(0, item.estimated_pomodoros)
    # Per-task work_duration takes precedence; the global default
    # (passed in from the user's PomodoroConfig) is used when not set.
    per_work = item.work_duration if item.work_duration > 0 else default_work_minutes
    pom_total = pom_count * per_work
    return max(direct, pom_total)


_MIN_VISIBLE_MINUTES = 30
"""Minimum visual duration, in minute-of-day units, that any hour-grid
BarSegment must occupy. Segments whose raw duration is smaller are
expanded to this floor while anchored at their semantic endpoint
(origin for head-in-day segments, end for continuing segments).

Rationale: at typical week-view zoom levels, 1 minute of duration is
rendered as ~1 pixel of cell height. Short tasks — a 1-minute pomodoro,
a cross-midnight tail — therefore fall below the human perception
threshold and become invisible and unclickable, even though the layout
computed them correctly. Every production calendar app (Google, Apple,
Outlook, Fantastical) applies a similar floor for this reason. The
floor is expressed in minutes, not pixels, so it behaves consistently
across zoom levels and HiDPI displays.

30 minutes matches the half-hour visual rhythm Google Calendar and
Apple Calendar use as their effective render floor. At the default
~60 px/hour week-view cell that's ~30 px of bar — comfortably above
the perception threshold, holds a one-line label, and lines up with
the half-hour gridline so floored bars still feel grid-native rather
than arbitrary.
"""


# The least stretch of a late bar drawn as its late-overflow zone. A
# task finished late and one finished on time have the same color; the
# zone is what tells them apart, and a completion a minute late would
# otherwise give a zone a pixel high.
_LEAST_ZONE_MINUTES = 10


def _late_zone(start_minute: int, planned_end: int, completed_minute: int) -> tuple[int, int]:
    """The late-overflow zone of a bar finished late on its due day.

    It runs from the planned end, as the bar is drawn, to the
    completion, and is at least ``_LEAST_ZONE_MINUTES`` long. A bar that
    ends too near midnight for that has its zone begin earlier instead,
    not before the bar itself.
    """
    zone_end = min(1440, max(completed_minute, planned_end + _LEAST_ZONE_MINUTES))
    zone_start = planned_end
    if zone_end - zone_start < _LEAST_ZONE_MINUTES:
        zone_start = max(start_minute, zone_end - _LEAST_ZONE_MINUTES)
    return zone_start, zone_end


def completion_day_beyond_window(item: TodoItem, window: BarWindow) -> date | None:
    """The day a task finished late has its bar on, past its window's days.

    A task finished on a later day than its planned end has a bar on
    the day it was finished, from midnight to the completion. That day
    is no day of its window, so a view that sorts tasks by the days of
    their windows has to add it there. None for any other task.
    """
    if not item.complete or item.completed_at is None:
        return None
    completed_day = datetime.fromtimestamp(item.completed_at / 1000).date()
    if window.kind == WindowKind.ALL_DAY:
        last_day = window.origin.date()
    else:
        last_day = window.end.date()
        if window.end.time() == time(0, 0, 0) and window.end > window.origin:
            last_day = last_day - timedelta(days=1)
    return completed_day if completed_day > last_day else None


def _apply_min_height_floor(
    start_minute: int,
    end_minute: int,
    *,
    clipped_top: bool,
    day_end_minute: int = 1440,
) -> tuple[int, int]:
    """Return start/end minutes expanded to ``_MIN_VISIBLE_MINUTES``.

    Anchors expansion at the semantic endpoint:
    - A segment whose origin lies within this day (``clipped_top`` is
      False) expands downward from ``start_minute`` so the bar still
      begins at the correct moment.
    - A segment continuing from a previous day (``clipped_top`` is
      True) expands upward from ``end_minute`` so the bar still ends
      at the correct moment.

    The expanded range is clamped to ``[0, day_end_minute]`` so the
    floor never invents minutes outside the viewing day.
    """
    if end_minute - start_minute >= _MIN_VISIBLE_MINUTES:
        return start_minute, end_minute
    if clipped_top:
        return max(0, end_minute - _MIN_VISIBLE_MINUTES), end_minute
    return start_minute, min(day_end_minute, start_minute + _MIN_VISIBLE_MINUTES)


def clamp_drop_due_time_forward(
    item: TodoItem,
    due_date: date,
    due_time: time | None,
    *,
    now: datetime,
    default_work_minutes: int,
) -> time | None:
    """Return a ``due_time`` whose implied bar-window origin is not
    earlier than ``now`` on ``now.date()``.

    Pure function: ``now`` is injected, not read from the wall clock.
    This lets tests pin exact inputs and assert exact outputs without
    any tolerance windows or time-of-day skips.

    Behavior:
    - ``due_time`` is ``None``           → pass-through (all-day drop).
    - ``due_date != now.date()``         → pass-through (drop onto
      another date; no "no time travel" constraint applies because
      today's clock does not govern other dates).
    - Task carries an estimated duration → window origin is
      ``due_time - estimate``. If that origin falls before ``now``,
      shift ``due_time`` to ``now + estimate`` so origin aligns with
      ``now`` and the bar begins precisely at the current moment.
    - Task has no estimate               → require ``due_time >= now
      + 1 minute`` so the bar has a non-degenerate forward window.
    """
    if due_time is None:
        return due_time
    if due_date != now.date():
        return due_time

    estimate = _effective_work_minutes(item, default_work_minutes)
    candidate_due = datetime.combine(due_date, due_time)

    if estimate > 0:
        if candidate_due - timedelta(minutes=estimate) >= now:
            return due_time
        new_due = now + timedelta(minutes=estimate)
    else:
        if candidate_due >= now + timedelta(minutes=1):
            return due_time
        new_due = now + timedelta(minutes=1)

    return time(new_due.hour, new_due.minute)


def get_time_blocks() -> TimeBlockConfig:
    """Read the user's time block boundaries from config.

    Returns the default boundaries if config can't be loaded for any
    reason.
    """
    from .config import TimeBlockConfig, get_config

    try:
        return get_config().time_blocks
    except Exception:
        return TimeBlockConfig()


def compute_bar_window(
    item: TodoItem,
    default_work_minutes: int | None = None,
    time_blocks: TimeBlockConfig | None = None,
) -> BarWindow | None:
    """Compute the bar window for an item per Q1's rules.

    When `default_work_minutes` is None (the typical case from runtime
    callers), reads the user's current pomodoro work duration default
    via `get_default_work_minutes()`. Tests pass an explicit value to
    avoid depending on whatever config happens to be loaded.

    Returns None if the item has no temporal anchor (no due_date),
    indicating it should not appear in the calendar grid at all.

    Sanitization: any rule that produces end < origin (negative duration)
    falls through to the next applicable rule. Sanitization happens here,
    at the layout layer, not by mutating the model.

    The rules in order:
        EVENT                  due_time AND due_time_end
        WORKBACK               due_time AND estimated_minutes > 0
        DEADLINE_FROM_CREATED  due_time only (no estimate, no end)
        BLOCK                  named time block, no due_time
        ALL_DAY                due_date only (no due_time, no block)

    A clock time takes precedence over a named block: an item with both
    is placed by its time. `time_blocks` gives the block boundaries;
    when None they are read from config, like `default_work_minutes`.
    """
    if item.due_date is None:
        return None

    if default_work_minutes is None:
        default_work_minutes = get_default_work_minutes()

    base_date = item.due_date

    # Rule 1: EVENT — both endpoints set explicitly
    if item.due_time is not None and item.due_time_end is not None:
        origin = datetime.combine(base_date, item.due_time)
        end = datetime.combine(base_date, item.due_time_end)
        if end > origin:
            return BarWindow(origin=origin, end=end, kind=WindowKind.EVENT)
        # Otherwise fall through to the next rule (sanitization)

    # Rule 2: WORKBACK — due_time + positive estimate. The estimate
    # can come from either `estimated_minutes` directly, or from the
    # pomodoro fields (estimated_pomodoros * work_duration, with the
    # global default when per-task work_duration is 0).
    if item.due_time is not None:
        work_minutes = _effective_work_minutes(item, default_work_minutes)
        if work_minutes > 0:
            end = datetime.combine(base_date, item.due_time)
            origin = end - timedelta(minutes=work_minutes)
            if end > origin:
                return BarWindow(origin=origin, end=end, kind=WindowKind.WORKBACK)
            # Sanitization: zero/negative duration falls through.

    # Rule 3: DEADLINE_FROM_CREATED — due_time only, origin from created_at.
    # CLAMPED so the bar is at most DEADLINE_DEFAULT_DURATION wide.
    # Without the clamp, a recurring task created weeks ago with a
    # due_time would produce a multi-day bar that visually dominates
    # every cell from midnight to due_time on the due day.
    if item.due_time is not None:
        end = datetime.combine(base_date, item.due_time)
        created_origin = datetime.fromtimestamp(item.created_at / 1000)
        # Clamp: origin is whichever is LATER between created_at and
        # (end - DEADLINE_DEFAULT_DURATION). For recent creations
        # (creation within the last hour), the original created_at wins
        # and the bar is the real creation-to-due span. For old tasks
        # (created days ago), the clamp wins and the bar is a
        # compact 1-hour marker ending at due_time.
        clamped_origin = end - DEADLINE_DEFAULT_DURATION
        origin = max(created_origin, clamped_origin)
        if end > origin:
            return BarWindow(origin=origin, end=end, kind=WindowKind.DEADLINE_FROM_CREATED)
        # Sanitization: created_at after due_time means the deadline is
        # already in the past at creation time. Fall through to ALL_DAY
        # so the item still shows up somewhere honest (the All Day row of
        # its due date).

    # Rule 4: BLOCK — a named time block and no clock time. The window is
    # the block itself: a block is a stretch of the day to do the task
    # in, not a deadline, so the bar covers all of it. A block that
    # crosses midnight ends on the following day.
    block = getattr(item, "due_time_block", None)
    if item.due_time is None and block:
        if time_blocks is None:
            time_blocks = get_time_blocks()
        block_range = time_blocks.block_range(block)
        if block_range is not None:
            midnight = datetime.combine(base_date, time(0, 0, 0))
            return BarWindow(
                origin=midnight + timedelta(minutes=block_range[0]),
                end=midnight + timedelta(minutes=block_range[1]),
                kind=WindowKind.BLOCK,
            )

    # Rule 5: ALL_DAY — due_date with no usable time anchor
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

    - Today: use `current_time` so live updates advance the state.
    - Past days: use end-of-that-day; the visual answers "what was true at
      the latest moment of this day" (a historical question).
    - Future days: use `current_time`. End-of-future-day would ask the
      question "will it be overdue by midnight?" which for any non-completed
      task with a due_time answers yes — producing spurious OVERDUE_ACTIVE
      bars on every future day of the week view. The user's mental model of
      a future day is "has it happened yet, as of right now?" — not a
      prediction of end-of-day state. Clamping to current_time yields FUTURE
      for tasks whose window hasn't opened at the current moment.
    """
    if viewing_day == current_time.date():
        return current_time
    if viewing_day > current_time.date():
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
    # ALL_DAY items live on their due_date row, plus Q6 markers on
    # subsequent days when overdue or historically overdue.
    if window.kind == WindowKind.ALL_DAY:
        origin_day = window.origin.date()
        if viewing_day < origin_day:
            return []
        if viewing_day > origin_day:
            # Q6 marker mode for all-day overdue tasks. The "due day"
            # for marker semantics is origin_day (= due_date). For
            # ALL_DAY, window.end is 00:00 of the next day, so we
            # cannot use window.end.date() as the boundary — that
            # would suppress the marker on the very first overdue day.
            return _maybe_marker_segment(
                item, window, viewing_day, current_time, effective_end_day=origin_day
            )
        # viewing_day == origin_day: render the all-day chip with the
        # appropriate state.
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
    #
    # Midnight edge case: if window.end falls exactly at 00:00 of day D,
    # the bar visually belongs to day D-1 (ending at 23:59:59), not day D
    # (starting at 00:00). Without this adjustment, a task with
    # due_time=00:00 on day D would produce an empty slice on day D
    # (because _minute_of_day clamps midnight to 0 for both origin and
    # end, yielding start==end==0) and would never render anywhere.
    end_day = window.end.date()
    # Midnight rollback: a one-time task ending at midnight semantically
    # belongs to the previous day's last hour. But recurring tasks are
    # exempt — the user set due_date explicitly, and "recurs at midnight"
    # means "start of that day", not "end of previous day".
    if (
        window.end.time() == time(0, 0, 0)
        and window.end > window.origin
        and not getattr(item, "is_recurring", False)
    ):
        end_day = end_day - timedelta(days=1)

    origin_day = window.origin.date()

    # Case A: viewing day is before the bar's origin day → bar not yet visible.
    if viewing_day < origin_day:
        return []

    # Case B: Q6 marker mode — viewing day is strictly after the bar's
    # planned end day. Whether to render a marker depends on the item's
    # complete state and (if complete) the relationship to completed_at.
    if viewing_day > end_day:
        return _maybe_marker_segment(
            item, window, viewing_day, current_time, effective_end_day=end_day
        )

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

    # Midnight edge case: a bar that ends exactly at the START of the day
    # AFTER viewing_day (e.g., due_time=00:00 on day D+1) should render
    # as filling all 24 hours of viewing_day, not as an empty slice.
    # _minute_of_day clamps start-of-next-day to 0, but for this case we
    # want 1440 (end-of-viewing-day).
    next_day_start = datetime.combine(viewing_day + timedelta(days=1), time(0, 0, 0))
    if window.end == next_day_start:
        end_minute = 1440

    # Sanitization: an empty slice (start >= end) means the bar's range
    # didn't actually intersect this day's hours. This shouldn't normally
    # happen because Case C in compute_bar_segments only fires when
    # viewing_day is in [origin.date(), end.date()], but defend anyway.
    if start_minute >= end_minute:
        return []

    clipped_top = window.origin.date() < viewing_day
    # clipped_bottom when end is on a later day, OR when end is exactly at
    # midnight of the day after viewing_day (handled by the adjustment above).
    clipped_bottom = window.end.date() > viewing_day and window.end != next_day_start

    # Visibility floor: short-duration bars are expanded to a minimum
    # number of minutes so they remain perceivable and clickable. The
    # state and clipping flags are computed from the ORIGINAL window;
    # only the visual extent is widened. Without this, a 1-minute task
    # renders as a 1-pixel sliver and is effectively invisible.
    start_minute, end_minute = _apply_min_height_floor(
        start_minute, end_minute, clipped_top=clipped_top
    )

    as_of = _as_of_for_viewing_day(viewing_day, current_time)
    completed_dt: datetime | None = None
    if item.complete and item.completed_at is not None:
        completed_dt = datetime.fromtimestamp(item.completed_at / 1000)
        if as_of > completed_dt:
            as_of = completed_dt
    state = compute_bar_state(item, window, as_of)

    # The deviation zone of a completed bar, on this day.
    zone_start: int | None = None
    zone_end: int | None = None
    if completed_dt is not None:
        completed_minute = _minute_of_day(completed_dt, viewing_day)
        if state == BarState.COMPLETED_EARLY:
            # From the completion to the planned end: all of this day's
            # slice when the task was finished before it, none of it
            # when the task was finished after this day.
            if max(start_minute, completed_minute) < end_minute:
                zone_start, zone_end = max(start_minute, completed_minute), end_minute
        elif state == BarState.COMPLETED_LATE and completed_dt.date() == viewing_day:
            # Finished late on the day it was due: the bar runs on to
            # the completion. Finished on a later day, the bar here
            # stays its planned span, and the day of the completion has
            # a bar of its own (_maybe_marker_segment).
            zone_start, zone_end = _late_zone(start_minute, end_minute, completed_minute)
            end_minute = zone_end

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
            zone_start_minute=zone_start,
            zone_end_minute=zone_end,
        )
    ]


def _maybe_marker_segment(
    item: TodoItem,
    window: BarWindow,
    viewing_day: date,
    current_time: datetime,
    effective_end_day: date,
) -> list[BarSegment]:
    """Compute the Q6 marker segment for a viewing day strictly after end day.

    `effective_end_day` is the "due day" for marker comparison purposes —
    the last day on which the task is considered to live in the hour grid
    (or all-day chip). For hour-grid items this is the midnight-adjusted
    `window.end.date()`; for ALL_DAY items it is `window.origin.date()`
    (the actual due_date, since `window.end` is 00:00 of the next day).

    Returns empty list if no marker should appear (e.g., item is complete
    and viewing_day is after the completion day).
    """
    end_day = effective_end_day

    # Q6 markers are historical truth and current state. On future viewing
    # days, the task lives in its actual bar/chip — projected overdue
    # markers are noise that floods the All Day row with spurious chips.
    if viewing_day > current_time.date():
        return []

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
        # All of it is past the planned end: the whole segment is its
        # late-overflow zone. A completion soon after midnight still
        # gets a bar of the least height.
        start_minute = _minute_of_day(window.origin, viewing_day)
        end_minute = max(
            _minute_of_day(completed_dt, viewing_day),
            min(1440, start_minute + _MIN_VISIBLE_MINUTES),
        )
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
                zone_start_minute=start_minute,
                zone_end_minute=end_minute,
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


# ---------------------------------------------------------------------------
# Lanes for bars of one day that share time
# ---------------------------------------------------------------------------


def assign_lanes(spans: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Place the timed bars of one day side by side where they share time.

    `spans` holds the (start_minute, end_minute) of each bar, as its
    segment for the day gives them. The answer has, for each span in
    the order given, `(lane, lanes)`: the bar's lane, counted from 0 at
    the left, and the number of lanes its group is divided into.

    A group is a run of bars joined by shared time, directly or through
    other bars: 09:00-10:00 and 09:30-11:00 are a group, and a bar at
    10:30-11:30 joins it through the second. A bar that ends at the
    minute another begins shares no time with it.

    Every bar of a group has the same share of the width, `1 / lanes`,
    and keeps its lane for its whole length, so its width does not
    change part of the way down. A bar that shares time with no other
    is alone in its group: `(0, 1)`, the full width.

    Within a group the bar that begins first is furthest left; of bars
    that begin together, the longer; of bars with the same times, the
    one given first. Each bar takes the leftmost lane that is free when
    it begins, so the group has as many lanes as the most bars it has
    at one minute.
    """
    order = sorted(range(len(spans)), key=lambda i: (spans[i][0], -spans[i][1], i))
    placed: list[tuple[int, int]] = [(0, 1)] * len(spans)

    group: list[int] = []
    lane_of: dict[int, int] = {}
    lane_ends: list[int] = []
    group_end = 0

    def close_group() -> None:
        for index in group:
            placed[index] = (lane_of[index], len(lane_ends))

    for index in order:
        start, end = spans[index]
        # A span with no length still takes the minute it is at.
        end = max(end, start + 1)
        if group and start >= group_end:
            close_group()
            group, lane_ends, group_end = [], [], 0
        # The leftmost lane whose bar has ended, or a new one.
        lane = next(
            (n for n, lane_end in enumerate(lane_ends) if lane_end <= start),
            len(lane_ends),
        )
        if lane == len(lane_ends):
            lane_ends.append(end)
        else:
            lane_ends[lane] = end
        lane_of[index] = lane
        group.append(index)
        group_end = max(group_end, end)
    close_group()
    return placed
