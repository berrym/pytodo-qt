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
- **Missed items** — reminders whose moment passed while nothing was
  evaluating (app closed, machine asleep). They are reported once,
  inside the daily summary when it fires in the same evaluation and on
  their own otherwise.

Each timed notification is keyed by item, kind and occurrence (the due
datetime). Rescheduling an item produces a new occurrence and so re-arms
its reminders; completing or deleting it removes it from consideration.

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

from .config import TimeBlockConfig
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


@dataclass(frozen=True)
class Evaluation:
    """What to deliver now, and what to record as fired.

    ``reminders`` belong in one notification, however many there are.
    ``missed`` is empty whenever ``summary`` is present, because the
    summary carries them.
    """

    reminders: tuple[Reminder, ...] = ()
    summary: Summary | None = None
    missed: tuple[TimedItem, ...] = ()
    fired: tuple[FiredKey, ...] = ()

    @property
    def has_notifications(self) -> bool:
        return bool(self.reminders or self.summary or self.missed)


def logical_day(now: datetime, day_start_hour: int) -> date:
    """Return the day ``now`` belongs to, given when a day starts.

    With a day start of 04:00, 02:00 on Tuesday is still Monday.
    """
    if day_start_hour > 0 and now.hour < day_start_hour:
        return now.date() - timedelta(days=1)
    return now.date()


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
) -> Evaluation:
    """Work out which notifications are due at ``now``.

    ``fired`` is the set of keys already recorded. The returned
    ``Evaluation.fired`` lists the keys this evaluation consumed; they
    must be recorded so the same notification is not produced again.
    """
    if not settings.enabled:
        return Evaluation()

    day = logical_day(now, settings.day_start_hour)
    day_start = datetime.combine(day, time(settings.day_start_hour))
    day_end = day_start + timedelta(days=1)
    lead = timedelta(minutes=settings.lead_minutes)

    reminders: list[Reminder] = []
    missed: list[TimedItem] = []
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
                newly_fired.append(lead_key)
                # An item created or edited inside its own lead window
                # was just handled; reminding about it at once is noise.
                if item.updated_at <= _to_ms(lead_at):
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
            newly_fired.append(due_key)
            if lead_applies and lead_key not in fired:
                newly_fired.append(lead_key)
            if item.updated_at > _to_ms(anchor):
                # Edited after it came due; nothing to announce.
                pass
            elif age <= STALE_AFTER:
                reminders.append(
                    Reminder(item.id, item.reminder, Kind.DUE_NOW, anchor, event, block, 0)
                )
            else:
                missed.append(timed)
        elif not due_applies and lead_applies and lead_key not in fired:
            # No alert is due at the anchor itself, and the lead reminder
            # never went out.
            newly_fired.append(lead_key)
            if item.updated_at <= _to_ms(lead_at):
                missed.append(timed)

    reminders.sort(key=lambda r: (r.at, r.title))
    missed.sort(key=lambda m: (m.at, m.title))

    summary: Summary | None = None
    summary_key = FiredKey("", Kind.SUMMARY.value, day.isoformat())
    if settings.summary_enabled and summary_key not in fired:
        summary_at = datetime.combine(day, settings.summary_time)
        if settings.summary_time.hour < settings.day_start_hour:
            # A summary time before the day's start falls on the next
            # calendar date of the same logical day.
            summary_at += timedelta(days=1)
        if now >= summary_at:
            newly_fired.append(summary_key)
            if due_today or overdue or missed:
                summary = Summary(day, due_today, overdue, next_up, tuple(missed))
                missed = []

    return Evaluation(
        reminders=tuple(reminders),
        summary=summary,
        missed=tuple(missed),
        fired=tuple(newly_fired),
    )
