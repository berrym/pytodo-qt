"""Decide which task notifications are due.

The policy is a pure function of the lists, the settings, the current
time and the record of what has already fired. It has no Qt dependency,
never reads the clock and performs no I/O, so every rule can be
exercised with a fixed ``now``.

Notification kinds:

- **Lead reminder** — a fixed number of minutes before a timed item's
  due time, or before the start of a named time block.
- **Due-now alert** — at the due time of a timed item that is still
  incomplete. By default only deadlines get one; an event (an item with
  an end time or a meeting link) is something already being attended
  when its start arrives.
- **Daily summary** — once per logical day: how many items are due
  today, how many are overdue, and the next item with a time.
- **Advance reminder** — a line in the daily summary on the days
  leading up to an item's due date, for items that ask for one. It is
  never a notification of its own.
- **Missed items** — reminders whose moment passed while nothing was
  evaluating (app closed, machine asleep). They are reported once,
  inside the daily summary when it fires in the same evaluation and on
  their own otherwise.

Each timed notification is keyed by item, kind and occurrence (the due
datetime). Rescheduling an item produces a new occurrence and so re-arms
its reminders; completing or deleting it removes it from consideration.

Two things can make a notification wait:

- **Quiet hours** — a daily window, by default overnight, in which the
  summary and the report of missed items are not delivered. Lead
  reminders and due-now alerts are delivered inside it unless the
  settings silence them too.
- **A focus session** — while one is running, the summary and the
  report of missed items wait for it to end. Lead reminders and due-now
  alerts are delivered regardless.

A notification that waits is not recorded as fired, so the first
evaluation after the wait is over produces it from the state of things
at that moment.

Items in private or deleted lists are never considered, not even in
counts: a notification is visible to anyone who can see the screen.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import NamedTuple
from uuid import UUID

from .config import AppConfig, TimeBlockConfig
from .meeting_link import detect_meeting_link
from .models import TodoItem, TodoList

# A due-now alert is still worth showing this long after the due time.
# Past that, the moment is reported as missed instead.
STALE_AFTER = timedelta(minutes=10)


class Kind(Enum):
    """The kinds of notification the policy produces."""

    LEAD = "lead"
    DUE_NOW = "due_now"
    SUMMARY = "summary"
    ADVANCE = "advance"


class DueNowMode(Enum):
    """Which timed items get an alert at their due time."""

    DEADLINES = "deadlines"
    ALL = "all"
    OFF = "off"


class FiredKey(NamedTuple):
    """Identifies one notification that has fired.

    ``item_id`` is the empty string for notifications that are not about
    a single item. ``occurrence`` is an ISO datetime for timed
    notifications and an ISO date for per-day ones.
    """

    item_id: str
    kind: str
    occurrence: str


@dataclass(frozen=True)
class PolicySettings:
    """Tunable behavior of the policy."""

    enabled: bool = True
    summary_enabled: bool = True
    summary_time: time = time(9, 0)
    lead_enabled: bool = True
    lead_minutes: int = 15
    due_now: DueNowMode = DueNowMode.DEADLINES
    day_start_hour: int = 0
    quiet_hours_enabled: bool = True
    quiet_start: time = time(22, 0)
    quiet_end: time = time(7, 0)
    """Quiet hours run from ``quiet_start`` up to, not including,
    ``quiet_end``, and may cross midnight."""
    quiet_allow_timed: bool = True
    """Deliver lead reminders and due-now alerts inside quiet hours."""
    hold_during_focus: bool = True


@dataclass(frozen=True)
class Reminder:
    """A lead reminder or due-now alert for one item."""

    item_id: UUID
    title: str
    kind: Kind
    at: datetime
    """The item's due time, or the start of its time block."""
    is_event: bool
    block: str | None
    """The named time block ``at`` was resolved from, if any."""
    minutes_until: int
    """Whole minutes from now until ``at``, rounded up; 0 for due-now."""


@dataclass(frozen=True)
class TimedItem:
    """An item and the moment it is anchored to."""

    item_id: UUID
    title: str
    at: datetime
    is_event: bool
    block: str | None


class AdvanceCadence(Enum):
    """How often an item's advance reminder appears. The values are the
    ones stored in ``TodoItem.reminder_cadence``."""

    NONE = "none"
    ONCE = "once"
    DAILY_UNTIL_DUE = "daily_until_due"


# The fewest and the most days before the due date an advance reminder
# can start.
ADVANCE_DAYS_RANGE = (1, 90)


@dataclass(frozen=True)
class ComingUp:
    """An item whose due date is near enough for its advance reminder."""

    item_id: UUID
    title: str
    due_date: date
    days_until: int
    """Whole logical days from the summary's day to the due date; 1 is tomorrow."""


@dataclass(frozen=True)
class Summary:
    """The once-per-day overview."""

    day: date
    due_today: int
    overdue: int
    """Items whose due date is before ``day``."""
    next_up: TimedItem | None
    """The earliest item still ahead in the day, if any has a time."""
    missed: tuple[TimedItem, ...]
    """Reminders from earlier in the day that were never delivered."""
    coming_up: tuple[ComingUp, ...] = ()
    """Advance reminders: items due on a later day, soonest first."""


@dataclass(frozen=True)
class Evaluation:
    """What to deliver now, and what to record as fired.

    ``reminders`` belong in one notification, however many there are.
    ``missed`` is empty whenever ``summary`` is present, because the
    summary carries them.

    ``held_items`` and ``held_summary`` describe what is waiting for
    quiet hours or a focus session to end. Nothing held is in ``fired``.
    """

    reminders: tuple[Reminder, ...] = ()
    summary: Summary | None = None
    missed: tuple[TimedItem, ...] = ()
    fired: tuple[FiredKey, ...] = ()
    held_items: tuple[TimedItem, ...] = ()
    held_summary: bool = False

    @property
    def has_notifications(self) -> bool:
        return bool(self.reminders or self.summary or self.missed)


def settings_from_config(config: AppConfig) -> PolicySettings:
    """Build the policy's settings from the application configuration."""
    notifications = config.notifications
    try:
        due_now = DueNowMode(notifications.due_now)
    except ValueError:
        due_now = DueNowMode.DEADLINES
    return PolicySettings(
        enabled=notifications.enabled,
        summary_enabled=notifications.summary_enabled,
        summary_time=notifications.summary_time,
        lead_enabled=notifications.lead_enabled,
        lead_minutes=notifications.lead_minutes,
        due_now=due_now,
        day_start_hour=config.database.day_start_hour,
        quiet_hours_enabled=notifications.quiet_hours_enabled,
        quiet_start=notifications.quiet_start,
        quiet_end=notifications.quiet_end,
        quiet_allow_timed=notifications.quiet_allow_timed,
        hold_during_focus=notifications.hold_during_focus,
    )


def logical_day(now: datetime, day_start_hour: int) -> date:
    """Return the day ``now`` belongs to, given when a day starts.

    With a day start of 04:00, 02:00 on Tuesday is still Monday.
    """
    if day_start_hour > 0 and now.hour < day_start_hour:
        return now.date() - timedelta(days=1)
    return now.date()


def in_quiet_hours(moment: time, settings: PolicySettings) -> bool:
    """Whether a time of day falls inside the quiet hours.

    The window includes its start and excludes its end. A start later
    than the end crosses midnight. Equal start and end make an empty
    window.
    """
    if not settings.quiet_hours_enabled:
        return False
    start, end = settings.quiet_start, settings.quiet_end
    if start < end:
        return start <= moment < end
    if start > end:
        return moment >= start or moment < end
    return False


def is_event(item: TodoItem) -> bool:
    """Whether an item is something attended over a span.

    An item with an end time or a recognized meeting link is an event;
    any other timed item is a deadline.
    """
    return item.due_time_end is not None or detect_meeting_link(item.reminder) is not None


def anchor_for(item: TodoItem, time_blocks: TimeBlockConfig) -> tuple[datetime, str | None] | None:
    """Return the moment an item's reminders are measured from.

    A timed item is anchored to its due time. An item with only a named
    time block is anchored to the start of that block; the block name is
    returned alongside. An explicit time takes precedence over a block.
    Date-only items, and items whose block cannot be resolved, have no
    anchor.
    """
    if item.due_date is None:
        return None
    if item.due_time is not None:
        return datetime.combine(item.due_date, item.due_time), None
    if item.due_time_block:
        block_range = time_blocks.block_range(item.due_time_block)
        if block_range is not None:
            midnight = datetime.combine(item.due_date, time.min)
            return midnight + timedelta(minutes=block_range[0]), item.due_time_block
    return None


def advance_reminder_for(item: TodoItem, day: date) -> ComingUp | None:
    """Return the advance reminder an item calls for on a given day.

    An item asks for one with ``remind_before_days`` of at least 1 and a
    cadence of once or daily-until-due. The reminder applies from that
    many days before the due date through the day before it; on the due
    date itself the item is counted as due today instead.
    """
    if item.due_date is None or item.remind_before_days < 1:
        return None
    if item.reminder_cadence not in (
        AdvanceCadence.ONCE.value,
        AdvanceCadence.DAILY_UNTIL_DUE.value,
    ):
        return None
    days_until = (item.due_date - day).days
    if not 1 <= days_until <= item.remind_before_days:
        return None
    return ComingUp(item.id, item.reminder, item.due_date, days_until)


def _to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _eligible_items(lists: Iterable[TodoList]) -> Iterable[TodoItem]:
    for todo_list in lists:
        if todo_list.deleted or todo_list.private:
            continue
        for item in todo_list.active_items():
            if not item.complete and item.due_date is not None:
                yield item


def evaluate(
    lists: Iterable[TodoList],
    settings: PolicySettings,
    now: datetime,
    fired: Collection[tuple[str, str, str]],
    time_blocks: TimeBlockConfig,
    *,
    focus_active: bool = False,
) -> Evaluation:
    """Work out which notifications are due at ``now``.

    ``fired`` is the set of keys already recorded. The returned
    ``Evaluation.fired`` lists the keys this evaluation consumed; they
    must be recorded so the same notification is not produced again.

    ``focus_active`` is whether a focus session is running: a focus
    timer in its work phase, or a running stopwatch. A paused session
    and a break do not count.
    """
    if not settings.enabled:
        return Evaluation()

    quiet = in_quiet_hours(now.time(), settings)
    # The summary and the report of missed items wait.
    digests_held = quiet or (settings.hold_during_focus and focus_active)
    # Lead reminders and due-now alerts wait as well.
    timed_held = quiet and not settings.quiet_allow_timed

    day = logical_day(now, settings.day_start_hour)
    day_start = datetime.combine(day, time(settings.day_start_hour))
    day_end = day_start + timedelta(days=1)
    lead = timedelta(minutes=settings.lead_minutes)

    reminders: list[Reminder] = []
    missed: list[TimedItem] = []
    held: list[TimedItem] = []
    coming_up: list[ComingUp] = []
    advance_keys: list[FiredKey] = []
    newly_fired: list[FiredKey] = []
    due_today = 0
    overdue = 0
    next_up: TimedItem | None = None

    for item in _eligible_items(lists):
        assert item.due_date is not None  # narrowed by _eligible_items
        if item.due_date == day:
            due_today += 1
        elif item.due_date < day:
            overdue += 1
        else:
            advance = advance_reminder_for(item, day)
            if advance is not None:
                # "Once" means the first summary in the window, which is
                # not necessarily the window's first day: the summary may
                # not have been given then. The key carries the due
                # date, so a rescheduled item is reminded again.
                advance_key = FiredKey(str(item.id), Kind.ADVANCE.value, item.due_date.isoformat())
                once = item.reminder_cadence == AdvanceCadence.ONCE.value
                if not (once and advance_key in fired):
                    coming_up.append(advance)
                    if once:
                        advance_keys.append(advance_key)

        anchored = anchor_for(item, time_blocks)
        if anchored is None:
            continue
        anchor, block = anchored
        event = is_event(item)
        timed = TimedItem(item.id, item.reminder, anchor, event, block)

        occurrence = anchor.isoformat(timespec="minutes")
        lead_key = FiredKey(str(item.id), Kind.LEAD.value, occurrence)
        due_key = FiredKey(str(item.id), Kind.DUE_NOW.value, occurrence)
        # A sub-daily repeat is its own reminder; warning ahead of each
        # one would double the volume for nothing.
        lead_applies = settings.lead_enabled and item.recurrence_type != "minutely"
        # A block is a window, not a cutoff, so it gets no due-now alert.
        due_applies = block is None and (
            settings.due_now is DueNowMode.ALL
            or (settings.due_now is DueNowMode.DEADLINES and not event)
        )
        lead_at = anchor - lead

        if now < anchor:
            if anchor < day_end and (next_up is None or anchor < next_up.at):
                next_up = timed
            if lead_applies and lead_key not in fired and now >= lead_at:
                # An item created or edited inside its own lead window
                # was just handled; reminding about it at once is noise.
                wanted = item.updated_at <= _to_ms(lead_at)
                if timed_held:
                    if wanted:
                        held.append(timed)
                    continue
                newly_fired.append(lead_key)
                if wanted:
                    minutes_until = math.ceil((anchor - now).total_seconds() / 60)
                    reminders.append(
                        Reminder(
                            item.id, item.reminder, Kind.LEAD, anchor, event, block, minutes_until
                        )
                    )
            continue

        # The anchor has passed.
        age = now - anchor
        if age > STALE_AFTER and anchor < day_start:
            # An earlier day's item: it is simply overdue, and the
            # summary's count covers it.
            continue

        if due_applies and due_key not in fired:
            # Edited after it came due: nothing to announce.
            edited_since = item.updated_at > _to_ms(anchor)
            fresh = age <= STALE_AFTER
            if not edited_since and (timed_held or (digests_held and not fresh)):
                held.append(timed)
                continue
            newly_fired.append(due_key)
            if lead_applies and lead_key not in fired:
                newly_fired.append(lead_key)
            if edited_since:
                pass
            elif fresh:
                reminders.append(
                    Reminder(item.id, item.reminder, Kind.DUE_NOW, anchor, event, block, 0)
                )
            else:
                missed.append(timed)
        elif not due_applies and lead_applies and lead_key not in fired:
            # No alert is due at the anchor itself, and the lead reminder
            # never went out.
            wanted = item.updated_at <= _to_ms(lead_at)
            if wanted and digests_held:
                held.append(timed)
                continue
            newly_fired.append(lead_key)
            if wanted:
                missed.append(timed)

    reminders.sort(key=lambda r: (r.at, r.title))
    missed.sort(key=lambda m: (m.at, m.title))
    held.sort(key=lambda h: (h.at, h.title))
    coming_up.sort(key=lambda c: (c.due_date, c.title))

    summary: Summary | None = None
    held_summary = False
    summary_key = FiredKey("", Kind.SUMMARY.value, day.isoformat())
    if settings.summary_enabled and summary_key not in fired:
        summary_time = settings.summary_time
        if in_quiet_hours(summary_time, settings):
            # A summary set for a time inside quiet hours is given when
            # they end, on the same logical day. Waiting out the window
            # instead would lose a late-evening summary altogether: the
            # day would be over before the window was.
            summary_time = settings.quiet_end
        summary_at = datetime.combine(day, summary_time)
        if summary_time.hour < settings.day_start_hour:
            # A summary time before the day's start falls on the next
            # calendar date of the same logical day.
            summary_at += timedelta(days=1)
        if now >= summary_at:
            if digests_held:
                held_summary = bool(due_today or overdue or held or coming_up)
            else:
                newly_fired.append(summary_key)
                if due_today or overdue or missed or coming_up:
                    summary = Summary(
                        day, due_today, overdue, next_up, tuple(missed), tuple(coming_up)
                    )
                    missed = []
                    # Recorded only now that the summary carrying them
                    # is given; a held summary leaves them unrecorded.
                    newly_fired.extend(advance_keys)

    return Evaluation(
        reminders=tuple(reminders),
        summary=summary,
        missed=tuple(missed),
        fired=tuple(newly_fired),
        held_items=tuple(held),
        held_summary=held_summary,
    )
