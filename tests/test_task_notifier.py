"""Tests for TaskNotifier — evaluation, recording, and notification text.

The notifier runs against a real temporary database with a fixed clock
and a delivery callable that collects what it is handed.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import uuid4

import pytest

from pytodo_qt.core.config import TimeBlockConfig
from pytodo_qt.core.database import DatabaseStorage
from pytodo_qt.core.models import TodoItem, TodoList
from pytodo_qt.core.notification_policy import (
    ComingUp,
    Kind,
    PolicySettings,
    Reminder,
    Summary,
    TimedItem,
)
from pytodo_qt.gui.task_notifier import TaskNotifier

DAY = date(2026, 11, 12)


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute))


def make_item(title: str = "Task", **fields) -> TodoItem:
    fields.setdefault("updated_at", 0)
    fields.setdefault("created_at", 0)
    return TodoItem(reminder=title, **fields)


class Harness:
    """A notifier with everything it depends on under the test's control."""

    def __init__(self, storage: DatabaseStorage) -> None:
        self.storage = storage
        self.todo_list = TodoList(name="List")
        self.now = at(9)
        self.settings = PolicySettings(summary_enabled=False)
        self.time_format = "24h"
        self.focus_active = False
        self.delivered: list[tuple[str, str]] = []
        self.notifier = TaskNotifier(
            storage=storage,
            lists=lambda: [self.todo_list],
            settings=lambda: self.settings,
            time_blocks=TimeBlockConfig,
            time_format=lambda: self.time_format,
            deliver=lambda title, body: self.delivered.append((title, body)),
            focus_active=lambda: self.focus_active,
            clock=lambda: self.now,
        )

    def add(self, item: TodoItem) -> TodoItem:
        self.todo_list.items[item.id] = item
        return item

    def tick(self, now: datetime) -> list[tuple[str, str]]:
        """Evaluate at ``now`` and return what that evaluation delivered."""
        self.now = now
        before = len(self.delivered)
        self.notifier.evaluate()
        return self.delivered[before:]


@pytest.fixture
def harness(qapp, tmp_path):
    storage = DatabaseStorage(tmp_path / "test.db")
    storage.open()
    yield Harness(storage)
    storage.close()


def lead(title: str, when: datetime, minutes: int, **fields) -> Reminder:
    fields.setdefault("is_event", False)
    fields.setdefault("block", None)
    return Reminder(uuid4(), title, Kind.LEAD, when, minutes_until=minutes, **fields)


def due_now(title: str, when: datetime) -> Reminder:
    return Reminder(uuid4(), title, Kind.DUE_NOW, when, False, None, 0)


def timed(title: str, when: datetime, **fields) -> TimedItem:
    fields.setdefault("is_event", False)
    fields.setdefault("block", None)
    return TimedItem(uuid4(), title, when, **fields)


class TestEvaluate:
    def test_delivers_a_due_reminder(self, harness):
        harness.add(make_item("Dentist", due_date=DAY, due_time=time(15)))
        assert harness.tick(at(14, 44)) == []
        assert harness.tick(at(14, 45)) == [("Dentist", "Due at 15:00 · in 15 min")]

    def test_records_what_fired(self, harness):
        item = harness.add(make_item(due_date=DAY, due_time=time(15)))
        harness.tick(at(14, 45))
        assert harness.storage.get_fired_notifications() == {
            (str(item.id), "lead", "2026-11-12T15:00")
        }

    def test_does_not_repeat_across_evaluations(self, harness):
        harness.add(make_item(due_date=DAY, due_time=time(15)))
        assert len(harness.tick(at(14, 45))) == 1
        assert harness.tick(at(14, 46)) == []

    def test_does_not_repeat_across_restarts(self, harness):
        """What fired is read back from storage, so a second notifier on
        the same database stays quiet."""
        harness.add(make_item(due_date=DAY, due_time=time(15)))
        harness.tick(at(14, 45))
        second = Harness(harness.storage)
        second.todo_list = harness.todo_list
        assert second.tick(at(14, 46)) == []

    def test_lead_then_due_now_for_a_deadline(self, harness):
        harness.add(make_item("Report", due_date=DAY, due_time=time(15)))
        assert harness.tick(at(14, 45)) == [("Report", "Due at 15:00 · in 15 min")]
        assert harness.tick(at(15)) == [("Report", "Due now · 15:00")]
        assert harness.tick(at(15, 1)) == []

    def test_evaluating_leaves_items_untouched(self, harness):
        """Notifying is not an edit: updated_at, which drives sync, stays."""
        item = harness.add(make_item(due_date=DAY, due_time=time(15), updated_at=1234))
        harness.tick(at(14, 45))
        harness.tick(at(15))
        assert item.updated_at == 1234

    def test_recorded_before_delivery(self, harness):
        """A delivery that raises must not make the reminder fire again."""
        item = harness.add(make_item(due_date=DAY, due_time=time(15)))

        def broken(title: str, body: str) -> None:
            raise RuntimeError("notification service unavailable")

        harness.notifier._deliver = broken
        harness.now = at(14, 45)
        with pytest.raises(RuntimeError):
            harness.notifier.evaluate()
        assert (str(item.id), "lead", "2026-11-12T15:00") in (
            harness.storage.get_fired_notifications()
        )

    def test_reminders_summary_order(self, harness):
        harness.settings = PolicySettings()
        harness.add(make_item("Standup", due_date=DAY, due_time=time(9, 15)))
        delivered = harness.tick(at(9))
        assert [title for title, _ in delivered] == ["Standup", "Today"]

    def test_summary_delivered_once_a_day(self, harness):
        harness.settings = PolicySettings()
        harness.add(make_item(due_date=DAY))
        assert harness.tick(at(9)) == [("Today", "1 due today")]
        assert harness.tick(at(9, 1)) == []

    def test_missed_delivered_on_its_own(self, harness):
        harness.add(make_item("Report", due_date=DAY, due_time=time(10)))
        assert harness.tick(at(11)) == [("Earlier today", "10:00  Report")]
        assert harness.tick(at(11, 1)) == []

    def test_disabled_delivers_and_records_nothing(self, harness):
        harness.settings = PolicySettings(enabled=False)
        harness.add(make_item(due_date=DAY, due_time=time(15)))
        assert harness.tick(at(14, 45)) == []
        assert harness.storage.get_fired_notifications() == set()

    def test_settings_are_read_on_every_evaluation(self, harness):
        """A change made in Preferences applies from the next tick."""
        harness.add(make_item(due_date=DAY, due_time=time(15)))
        harness.settings = PolicySettings(enabled=False)
        assert harness.tick(at(14, 45)) == []
        harness.settings = PolicySettings(summary_enabled=False)
        assert len(harness.tick(at(14, 46))) == 1

    def test_returns_the_evaluation(self, harness):
        harness.add(make_item(due_date=DAY, due_time=time(15)))
        harness.now = at(14, 45)
        result = harness.notifier.evaluate()
        assert len(result.reminders) == 1


class TestHolding:
    def test_summary_waits_for_the_focus_session_and_is_not_recorded(self, harness):
        harness.settings = PolicySettings()
        harness.add(make_item(due_date=DAY))
        harness.focus_active = True
        assert harness.tick(at(9)) == []
        assert harness.storage.get_fired_notifications() == set()
        harness.focus_active = False
        assert harness.tick(at(9, 25)) == [("Today", "1 due today")]
        assert harness.tick(at(9, 26)) == []

    def test_focus_state_is_read_on_every_evaluation(self, harness):
        harness.settings = PolicySettings()
        harness.add(make_item(due_date=DAY))
        harness.focus_active = True
        for minute in range(5):
            assert harness.tick(at(9, minute)) == []
        harness.focus_active = False
        assert len(harness.tick(at(9, 5))) == 1

    def test_timed_reminder_is_delivered_during_a_focus_session(self, harness):
        harness.add(make_item("Dentist", due_date=DAY, due_time=time(15)))
        harness.focus_active = True
        assert harness.tick(at(14, 45)) == [("Dentist", "Due at 15:00 · in 15 min")]

    def test_summary_waits_for_quiet_hours_to_end(self, harness):
        harness.settings = PolicySettings(summary_time=time(6))
        harness.add(make_item(due_date=DAY))
        assert harness.tick(at(6)) == []
        assert harness.storage.get_fired_notifications() == set()
        assert harness.tick(at(7)) == [("Today", "1 due today")]

    def test_missed_items_wait_for_quiet_hours_to_end(self, harness):
        harness.add(make_item("Report", due_date=DAY, due_time=time(2)))
        assert harness.tick(at(4)) == []
        assert harness.storage.get_fired_notifications() == set()
        assert harness.tick(at(7)) == [("Earlier today", "02:00  Report")]
        assert harness.tick(at(7, 1)) == []

    def test_notifier_without_a_focus_source_never_holds_for_one(self, qapp, tmp_path):
        storage = DatabaseStorage(tmp_path / "plain.db")
        storage.open()
        try:
            todo_list = TodoList(name="List")
            item = make_item(due_date=DAY)
            todo_list.items[item.id] = item
            delivered: list[tuple[str, str]] = []
            notifier = TaskNotifier(
                storage=storage,
                lists=lambda: [todo_list],
                settings=PolicySettings,
                time_blocks=TimeBlockConfig,
                time_format=lambda: "24h",
                deliver=lambda title, body: delivered.append((title, body)),
                clock=lambda: at(9),
            )
            notifier.evaluate()
            assert delivered == [("Today", "1 due today")]
        finally:
            storage.close()


class TestPruning:
    def test_old_entries_are_removed(self, harness):
        harness.storage.record_notification(None, "summary", "2026-09-01")
        harness.storage.record_notification(None, "summary", "2026-11-01")
        harness.tick(at(9))
        assert harness.storage.get_fired_notifications() == {("", "summary", "2026-11-01")}

    def test_prunes_once_per_day(self, harness):
        harness.tick(at(9))
        harness.storage.record_notification(None, "summary", "2026-09-01")
        harness.tick(at(10))
        assert ("", "summary", "2026-09-01") in harness.storage.get_fired_notifications()
        harness.tick(at(9, 0, DAY + timedelta(days=1)))
        assert ("", "summary", "2026-09-01") not in harness.storage.get_fired_notifications()


class TestReminderText:
    def test_deadline_lead(self, harness):
        assert harness.notifier.format_reminders((lead("Report", at(15), 15),)) == (
            "Report",
            "Due at 15:00 · in 15 min",
        )

    def test_event_lead(self, harness):
        reminder = lead("Standup", at(10), 15, is_event=True)
        assert harness.notifier.format_reminders((reminder,)) == (
            "Standup",
            "Starts at 10:00 · in 15 min",
        )

    def test_block_lead(self, harness):
        reminder = lead("Call mum", at(17), 15, block="evening")
        assert harness.notifier.format_reminders((reminder,)) == (
            "Call mum",
            "This evening · 17:00–21:00",
        )

    def test_half_block_names_its_own_window(self, harness):
        reminder = lead("Run", at(14, 30), 15, block="late_afternoon")
        _, body = harness.notifier.format_reminders((reminder,))
        assert body == "Late this afternoon · 14:30–17:00"

    def test_block_window_has_no_countdown(self, harness):
        # A block is a stretch of the day; a late start changes nothing.
        reminder = lead("Run", at(17), 6, block="evening")
        _, body = harness.notifier.format_reminders((reminder,))
        assert body == "This evening · 17:00–21:00"

    def test_block_crossing_midnight(self, harness):
        reminder = lead("Laundry", at(21), 15, block="night")
        _, body = harness.notifier.format_reminders((reminder,))
        assert body == "Tonight · 21:00–06:00"

    def test_late_night_block(self, harness):
        # Late night starts at 01:30 on the day after the due date.
        reminder = lead("Backup", at(1, 30, DAY + timedelta(days=1)), 15, block="late_night")
        _, body = harness.notifier.format_reminders((reminder,))
        assert body == "Late tonight · 01:30–06:00"

    def test_noon_block(self, harness):
        reminder = lead("Lunch", at(11, 30), 15, block="noon")
        _, body = harness.notifier.format_reminders((reminder,))
        assert body == "Around noon · 11:30–12:30"

    def test_block_window_in_twelve_hour_format(self, harness):
        harness.time_format = "12h"
        reminder = lead("Call mum", at(17), 15, block="evening")
        _, body = harness.notifier.format_reminders((reminder,))
        assert body == "This evening · 5:00 PM–9:00 PM"

    def test_block_window_follows_configured_boundaries(self, harness):
        harness.notifier._time_blocks = lambda: TimeBlockConfig(evening_start=18, evening_end=22)
        reminder = lead("Call mum", at(18), 15, block="evening")
        _, body = harness.notifier.format_reminders((reminder,))
        assert body == "This evening · 18:00–22:00"

    def test_unknown_block_falls_back_to_its_name(self, harness):
        reminder = lead("Tea", at(16), 15, block="tea_time")
        _, body = harness.notifier.format_reminders((reminder,))
        assert body == "Tea Time"

    def test_due_now(self, harness):
        assert harness.notifier.format_reminders((due_now("Report", at(15)),)) == (
            "Report",
            "Due now · 15:00",
        )

    def test_true_remaining_minutes(self, harness):
        _, body = harness.notifier.format_reminders((lead("Report", at(15), 6),))
        assert body == "Due at 15:00 · in 6 min"

    def test_twelve_hour_format(self, harness):
        harness.time_format = "12h"
        _, body = harness.notifier.format_reminders((lead("Report", at(15), 15),))
        assert body == "Due at 3:00 PM · in 15 min"

    def test_several_reminders_share_one_notification(self, harness):
        reminders = (
            due_now("Report", at(15)),
            lead("Standup", at(15, 15), 15, is_event=True),
            lead("Invoice", at(15, 15), 15),
            lead("Gym", at(15, 15), 15, block="afternoon"),
        )
        title, body = harness.notifier.format_reminders(reminders)
        assert title == "4 reminders"
        assert body.split("\n") == [
            "15:00  Report — due now",
            "15:15  Standup — starts in 15 min",
            "15:15  Invoice — due in 15 min",
            "15:15  Gym — this afternoon",
        ]

    def test_long_lists_are_capped(self, harness):
        reminders = tuple(lead(f"Task {n}", at(15), 15) for n in range(8))
        title, body = harness.notifier.format_reminders(reminders)
        lines = body.split("\n")
        assert title == "8 reminders"
        assert len(lines) == 6
        assert lines[-1] == "+3 more"

    def test_meeting_url_is_dropped_from_the_title(self, harness):
        reminder = lead("Sync https://meet.google.com/abc-defg-hij with design", at(10), 15)
        title, _ = harness.notifier.format_reminders((reminder,))
        assert title == "Sync with design"

    def test_title_that_is_only_a_meeting_url(self, harness):
        reminder = lead("https://meet.google.com/abc-defg-hij", at(10), 15, is_event=True)
        title, _ = harness.notifier.format_reminders((reminder,))
        assert title == "Google Meet meeting"

    def test_ordinary_url_is_kept(self, harness):
        reminder = lead("Read https://example.com/post", at(10), 15)
        title, _ = harness.notifier.format_reminders((reminder,))
        assert title == "Read https://example.com/post"


class TestSummaryText:
    def test_counts_and_next_item(self, harness):
        summary = Summary(DAY, 3, 2, timed("Standup", at(10), is_event=True), ())
        assert harness.notifier.format_summary(summary) == (
            "Today",
            "3 due today · 2 overdue\nNext: Standup at 10:00",
        )

    def test_only_due_today(self, harness):
        assert harness.notifier.format_summary(Summary(DAY, 1, 0, None, ())) == (
            "Today",
            "1 due today",
        )

    def test_only_overdue(self, harness):
        assert harness.notifier.format_summary(Summary(DAY, 0, 4, None, ())) == (
            "Today",
            "4 overdue",
        )

    def test_missed_items_are_named(self, harness):
        missed = (timed("Early call", at(8)), timed("Invoice", at(8, 30)))
        _, body = harness.notifier.format_summary(Summary(DAY, 2, 0, None, missed))
        assert body.split("\n") == [
            "2 due today",
            "Earlier today: Early call (08:00), Invoice (08:30)",
        ]

    def test_many_missed_items_are_capped(self, harness):
        missed = tuple(timed(f"Task {n}", at(8, n)) for n in range(5))
        _, body = harness.notifier.format_summary(Summary(DAY, 5, 0, None, missed))
        assert body.split("\n")[-1] == (
            "Earlier today: Task 0 (08:00), Task 1 (08:01), Task 2 (08:02), +2 more"
        )

    def test_missed_only(self, harness):
        _, body = harness.notifier.format_summary(
            Summary(DAY, 0, 0, None, (timed("Night shift", at(1)),))
        )
        assert body == "Earlier today: Night shift (01:00)"

    def test_meeting_url_is_dropped_from_next_item(self, harness):
        next_up = timed("Sync https://meet.google.com/abc-defg-hij", at(10), is_event=True)
        _, body = harness.notifier.format_summary(Summary(DAY, 1, 0, next_up, ()))
        assert body.split("\n")[1] == "Next: Sync at 10:00"


class TestMissedText:
    def test_lists_items_with_times(self, harness):
        missed = (timed("Early call", at(8)), timed("Report", at(10)))
        assert harness.notifier.format_missed(missed) == (
            "Earlier today",
            "08:00  Early call\n10:00  Report",
        )

    def test_capped(self, harness):
        missed = tuple(timed(f"Task {n}", at(8, n)) for n in range(7))
        _, body = harness.notifier.format_missed(missed)
        lines = body.split("\n")
        assert len(lines) == 6
        assert lines[-1] == "+2 more"


def coming(title: str, days: int) -> ComingUp:
    return ComingUp(uuid4(), title, DAY + timedelta(days=days), days)


class TestComingUpText:
    def _body(self, harness, *items: ComingUp, due_today: int = 0) -> str:
        summary = Summary(DAY, due_today, 0, None, (), tuple(items))
        return harness.notifier.format_summary(summary)[1]

    def test_tomorrow(self, harness):
        assert self._body(harness, coming("Passport", 1)) == "Coming up: Passport tomorrow"

    def test_in_some_days(self, harness):
        assert self._body(harness, coming("Tax return", 3)) == "Coming up: Tax return in 3 days"

    def test_several_on_one_line(self, harness):
        body = self._body(harness, coming("Passport", 1), coming("Tax return", 3))
        assert body == "Coming up: Passport tomorrow, Tax return in 3 days"

    def test_names_at_most_three(self, harness):
        items = [coming(f"Task {n}", n) for n in range(1, 6)]
        body = self._body(harness, *items)
        assert body == "Coming up: Task 1 tomorrow, Task 2 in 2 days, Task 3 in 3 days, +2 more"

    def test_follows_the_other_lines(self, harness):
        body = self._body(harness, coming("Passport", 1), due_today=2)
        assert body.splitlines() == ["2 due today", "Coming up: Passport tomorrow"]

    def test_meeting_link_is_dropped_from_the_title(self, harness):
        body = self._body(harness, coming("Review https://meet.google.com/abc-defg-hij", 2))
        assert body == "Coming up: Review in 2 days"

    def test_summary_without_any_has_no_such_line(self, harness):
        assert "Coming up" not in self._body(harness, due_today=1)


class TestAdvanceReminderDelivery:
    def test_delivered_in_the_summary_and_recorded(self, harness):
        harness.settings = PolicySettings()
        item = harness.add(
            make_item(
                "Tax return",
                due_date=DAY + timedelta(days=3),
                remind_before_days=3,
                reminder_cadence="once",
            )
        )
        assert harness.tick(at(9)) == [("Today", "Coming up: Tax return in 3 days")]
        due = (DAY + timedelta(days=3)).isoformat()
        assert (str(item.id), "advance", due) in harness.storage.get_fired_notifications()

    def test_once_is_not_repeated_the_next_day(self, harness):
        harness.settings = PolicySettings()
        harness.add(
            make_item(
                "Tax return",
                due_date=DAY + timedelta(days=3),
                remind_before_days=3,
                reminder_cadence="once",
            )
        )
        harness.tick(at(9))
        assert harness.tick(at(9, 0, DAY + timedelta(days=1))) == []
