"""Fixed-clock tests for the notification policy.

Every test passes its own ``now``; nothing here reads the real clock.
Items are created with ``updated_at=0`` unless a test is specifically
about an item edited close to its due time.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from pytodo_qt.core.config import TimeBlockConfig
from pytodo_qt.core.models import TodoItem, TodoList
from pytodo_qt.core.notification_policy import (
    STALE_AFTER,
    ComingUp,
    DueNowMode,
    Evaluation,
    FiredKey,
    Kind,
    PolicySettings,
    Preview,
    advance_reminder_for,
    anchor_for,
    effective_preview_time,
    evaluate,
    in_quiet_hours,
    is_event,
    logical_day,
)

DAY = date(2026, 11, 12)  # a Thursday
BLOCKS = TimeBlockConfig()


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute))


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def make_item(title: str = "Task", **fields) -> TodoItem:
    fields.setdefault("updated_at", 0)
    fields.setdefault("created_at", 0)
    return TodoItem(reminder=title, **fields)


def make_list(*items: TodoItem, **fields) -> TodoList:
    return TodoList(name="List", items={item.id: item for item in items}, **fields)


def run(
    items,
    now: datetime,
    fired=(),
    settings: PolicySettings | None = None,
    blocks: TimeBlockConfig = BLOCKS,
    focus_active: bool = False,
) -> Evaluation:
    """Evaluate a flat list of items, or ready-made lists."""
    lists = items if items and isinstance(items[0], TodoList) else [make_list(*items)]
    return evaluate(
        lists, settings or NO_SUMMARY, now, set(fired), blocks, focus_active=focus_active
    )


# Most tests are about timed reminders; the summary gets its own class.
NO_SUMMARY = PolicySettings(summary_enabled=False)


class Session:
    """Replays the policy across successive moments, recording what
    fires the way the scheduler does."""

    def __init__(self, items, settings: PolicySettings | None = None) -> None:
        self.lists = [make_list(*items)]
        self.settings = settings or NO_SUMMARY
        self.fired: set[tuple[str, str, str]] = set()

    def tick(self, now: datetime, focus_active: bool = False) -> Evaluation:
        result = evaluate(
            self.lists, self.settings, now, self.fired, BLOCKS, focus_active=focus_active
        )
        self.fired.update(result.fired)
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestLogicalDay:
    def test_midnight_start_is_the_calendar_date(self):
        assert logical_day(at(0, 30), 0) == DAY

    def test_before_the_day_start_is_still_yesterday(self):
        assert logical_day(at(2), 4) == DAY - timedelta(days=1)

    def test_at_the_day_start_is_today(self):
        assert logical_day(at(4), 4) == DAY


class TestIsEvent:
    def test_point_time_is_a_deadline(self):
        assert not is_event(make_item(due_date=DAY, due_time=time(15)))

    def test_end_time_makes_an_event(self):
        assert is_event(make_item(due_date=DAY, due_time=time(15), due_time_end=time(16)))

    def test_meeting_link_makes_an_event(self):
        item = make_item(
            "Standup https://us02web.zoom.us/j/12345678901", due_date=DAY, due_time=time(15)
        )
        assert is_event(item)


class TestAnchor:
    def test_date_only_has_no_anchor(self):
        assert anchor_for(make_item(due_date=DAY), BLOCKS) is None

    def test_no_due_date_has_no_anchor(self):
        assert anchor_for(make_item(due_time=time(15)), BLOCKS) is None

    def test_timed_item_anchors_to_its_due_time(self):
        assert anchor_for(make_item(due_date=DAY, due_time=time(15, 30)), BLOCKS) == (
            at(15, 30),
            None,
        )

    def test_block_item_anchors_to_the_block_start(self):
        assert anchor_for(make_item(due_date=DAY, due_time_block="evening"), BLOCKS) == (
            at(17),
            "evening",
        )

    def test_block_start_follows_the_configuration(self):
        blocks = TimeBlockConfig(evening_start=18, evening_end=22)
        item = make_item(due_date=DAY, due_time_block="evening")
        assert anchor_for(item, blocks) == (at(18), "evening")

    def test_late_night_anchors_after_midnight(self):
        item = make_item(due_date=DAY, due_time_block="late_night")
        assert anchor_for(item, BLOCKS) == (at(1, 30, DAY + timedelta(days=1)), "late_night")

    def test_explicit_time_wins_over_a_block(self):
        item = make_item(due_date=DAY, due_time=time(9), due_time_block="evening")
        assert anchor_for(item, BLOCKS) == (at(9), None)

    def test_unknown_block_has_no_anchor(self):
        assert anchor_for(make_item(due_date=DAY, due_time_block="teatime"), BLOCKS) is None


# ---------------------------------------------------------------------------
# Lead reminders
# ---------------------------------------------------------------------------


class TestLeadReminder:
    def test_nothing_before_the_lead_time(self):
        item = make_item(due_date=DAY, due_time=time(15))
        result = run([item], at(14, 44))
        assert not result.has_notifications
        assert result.fired == ()

    def test_fires_exactly_at_the_lead_time(self):
        item = make_item("Dentist", due_date=DAY, due_time=time(15))
        result = run([item], at(14, 45))
        assert len(result.reminders) == 1
        reminder = result.reminders[0]
        assert reminder.kind is Kind.LEAD
        assert reminder.item_id == item.id
        assert reminder.title == "Dentist"
        assert reminder.at == at(15)
        assert reminder.minutes_until == 15
        assert result.fired == (FiredKey(str(item.id), "lead", "2026-11-12T15:00"),)

    def test_never_fires_twice_for_the_same_occurrence(self):
        session = Session([make_item(due_date=DAY, due_time=time(15))])
        assert len(session.tick(at(14, 45)).reminders) == 1
        assert session.tick(at(14, 46)).reminders == ()
        assert session.tick(at(14, 59)).reminders == ()

    def test_late_start_inside_the_window_reports_the_true_remaining_time(self):
        item = make_item(due_date=DAY, due_time=time(15))
        result = run([item], at(14, 54))
        assert result.reminders[0].minutes_until == 6

    def test_remaining_time_rounds_up(self):
        item = make_item(due_date=DAY, due_time=time(15))
        now = at(14, 54) + timedelta(seconds=20)
        assert run([item], now).reminders[0].minutes_until == 6

    def test_lead_minutes_setting(self):
        item = make_item(due_date=DAY, due_time=time(15))
        settings = PolicySettings(summary_enabled=False, lead_minutes=30)
        assert run([item], at(14, 29), settings=settings).reminders == ()
        assert run([item], at(14, 30), settings=settings).reminders[0].minutes_until == 30

    def test_disabled(self):
        item = make_item(due_date=DAY, due_time=time(15))
        settings = PolicySettings(summary_enabled=False, lead_enabled=False)
        result = run([item], at(14, 50), settings=settings)
        assert not result.has_notifications
        assert result.fired == ()

    def test_applies_to_events_and_marks_them(self):
        item = make_item(due_date=DAY, due_time=time(15), due_time_end=time(16))
        reminder = run([item], at(14, 45)).reminders[0]
        assert reminder.kind is Kind.LEAD
        assert reminder.is_event

    def test_item_edited_inside_its_lead_window_is_not_reminded(self):
        """Created at 14:55 for 15:00: the reminder would land moments
        after the item was typed in."""
        item = make_item(due_date=DAY, due_time=time(15), updated_at=ms(at(14, 55)))
        session = Session([item])
        result = session.tick(at(14, 56))
        assert result.reminders == ()
        # Consumed, so it does not fire a minute later either.
        assert FiredKey(str(item.id), "lead", "2026-11-12T15:00") in result.fired
        assert session.tick(at(14, 57)).reminders == ()

    def test_item_edited_before_its_lead_window_is_reminded(self):
        item = make_item(due_date=DAY, due_time=time(15), updated_at=ms(at(14, 44)))
        assert len(run([item], at(14, 45)).reminders) == 1

    def test_minutely_recurrence_gets_no_lead_reminder(self):
        item = make_item(
            due_date=DAY, due_time=time(15), recurrence_type="minutely", recurrence_interval=30
        )
        result = run([item], at(14, 50))
        assert result.reminders == ()
        assert result.fired == ()

    def test_daily_recurrence_gets_a_lead_reminder(self):
        item = make_item(due_date=DAY, due_time=time(15), recurrence_type="daily")
        assert len(run([item], at(14, 45)).reminders) == 1


class TestBlockItems:
    def test_lead_reminder_before_the_block_start(self):
        item = make_item("Call mum", due_date=DAY, due_time_block="evening")
        assert run([item], at(16, 44)).reminders == ()
        reminder = run([item], at(16, 45)).reminders[0]
        assert reminder.kind is Kind.LEAD
        assert reminder.at == at(17)
        assert reminder.block == "evening"
        assert reminder.minutes_until == 15

    def test_no_due_now_alert_at_the_block_start(self):
        session = Session([make_item(due_date=DAY, due_time_block="evening")])
        session.tick(at(16, 45))
        result = session.tick(at(17))
        assert result.reminders == ()
        assert result.missed == ()

    def test_no_due_now_alert_even_when_every_item_gets_one(self):
        item = make_item(due_date=DAY, due_time_block="evening")
        settings = PolicySettings(summary_enabled=False, due_now=DueNowMode.ALL)
        session = Session([item], settings)
        session.tick(at(16, 45))
        assert session.tick(at(17)).reminders == ()

    def test_changing_the_block_configuration_re_arms(self):
        item = make_item(due_date=DAY, due_time_block="evening")
        first = evaluate([make_list(item)], NO_SUMMARY, at(16, 45), set(), BLOCKS)
        assert len(first.reminders) == 1
        later = TimeBlockConfig(evening_start=18, evening_end=22)
        again = evaluate([make_list(item)], NO_SUMMARY, at(17, 45), set(first.fired), later)
        assert len(again.reminders) == 1
        assert again.reminders[0].at == at(18)

    def test_late_night_block_reminds_on_the_following_calendar_day(self):
        item = make_item(due_date=DAY, due_time_block="late_night")
        tomorrow = DAY + timedelta(days=1)
        assert run([item], at(23, 59)).reminders == ()
        reminder = run([item], at(1, 15, tomorrow)).reminders[0]
        assert reminder.at == at(1, 30, tomorrow)


# ---------------------------------------------------------------------------
# Due-now alerts
# ---------------------------------------------------------------------------


class TestDueNow:
    def test_deadline_alerts_at_its_due_time(self):
        item = make_item("Submit report", due_date=DAY, due_time=time(15))
        session = Session([item])
        session.tick(at(14, 45))
        result = session.tick(at(15))
        assert len(result.reminders) == 1
        reminder = result.reminders[0]
        assert reminder.kind is Kind.DUE_NOW
        assert reminder.minutes_until == 0
        assert FiredKey(str(item.id), "due_now", "2026-11-12T15:00") in result.fired

    def test_alerts_only_once(self):
        session = Session([make_item(due_date=DAY, due_time=time(15))])
        session.tick(at(14, 45))
        assert len(session.tick(at(15)).reminders) == 1
        assert session.tick(at(15, 1)).reminders == ()

    def test_event_gets_no_due_now_by_default(self):
        item = make_item(due_date=DAY, due_time=time(15), due_time_end=time(16))
        session = Session([item])
        assert len(session.tick(at(14, 45)).reminders) == 1
        result = session.tick(at(15))
        assert result.reminders == ()
        assert result.missed == ()

    def test_meeting_link_item_gets_no_due_now_by_default(self):
        item = make_item(
            "Sync https://meet.google.com/abc-defg-hij", due_date=DAY, due_time=time(15)
        )
        session = Session([item])
        session.tick(at(14, 45))
        assert session.tick(at(15)).reminders == ()

    def test_mode_all_alerts_events_too(self):
        item = make_item(due_date=DAY, due_time=time(15), due_time_end=time(16))
        settings = PolicySettings(summary_enabled=False, due_now=DueNowMode.ALL)
        session = Session([item], settings)
        session.tick(at(14, 45))
        assert session.tick(at(15)).reminders[0].kind is Kind.DUE_NOW

    def test_mode_off(self):
        settings = PolicySettings(summary_enabled=False, due_now=DueNowMode.OFF)
        session = Session([make_item(due_date=DAY, due_time=time(15))], settings)
        session.tick(at(14, 45))
        result = session.tick(at(15))
        assert result.reminders == ()
        assert result.missed == ()

    def test_still_delivered_shortly_after_the_due_time(self):
        item = make_item(due_date=DAY, due_time=time(15))
        result = run([item], at(15) + STALE_AFTER)
        assert [r.kind for r in result.reminders] == [Kind.DUE_NOW]

    def test_created_inside_the_lead_window_still_alerts_at_the_due_time(self):
        """No lead reminder for an item typed in five minutes ahead, but
        the cutoff itself is still worth an alert."""
        item = make_item(due_date=DAY, due_time=time(15), updated_at=ms(at(14, 55)))
        session = Session([item])
        assert session.tick(at(14, 56)).reminders == ()
        assert [r.kind for r in session.tick(at(15)).reminders] == [Kind.DUE_NOW]

    def test_item_edited_after_it_came_due_is_not_announced(self):
        item = make_item(due_date=DAY, due_time=time(15), updated_at=ms(at(15, 2)))
        result = run([item], at(15, 3))
        assert not result.has_notifications
        # Both moments are consumed.
        assert {key.kind for key in result.fired} == {"lead", "due_now"}

    def test_minutely_recurrence_alerts_per_occurrence(self):
        item = make_item(
            due_date=DAY, due_time=time(15), recurrence_type="minutely", recurrence_interval=30
        )
        session = Session([item])
        assert [r.kind for r in session.tick(at(15)).reminders] == [Kind.DUE_NOW]
        # The recurrence machinery moves the item to its next occurrence.
        item.due_time = time(15, 30)
        assert session.tick(at(15, 1)).reminders == ()
        assert [r.kind for r in session.tick(at(15, 30)).reminders] == [Kind.DUE_NOW]

    def test_recurring_item_alerts_before_it_is_advanced(self):
        """The policy sees the passed occurrence because it is evaluated
        before the item is moved to the next one."""
        item = make_item(due_date=DAY, due_time=time(15), recurrence_type="daily")
        session = Session([item])
        session.tick(at(14, 45))
        assert [r.kind for r in session.tick(at(15)).reminders] == [Kind.DUE_NOW]
        item.due_date = DAY + timedelta(days=1)
        assert session.tick(at(15, 1)).reminders == ()


# ---------------------------------------------------------------------------
# Re-arming and eligibility
# ---------------------------------------------------------------------------


class TestReArming:
    def test_rescheduling_re_arms(self):
        item = make_item(due_date=DAY, due_time=time(15))
        session = Session([item])
        assert len(session.tick(at(14, 45)).reminders) == 1
        item.due_time = time(16)
        assert session.tick(at(14, 46)).reminders == ()
        assert len(session.tick(at(15, 45)).reminders) == 1

    def test_moving_to_another_day_re_arms(self):
        item = make_item(due_date=DAY, due_time=time(15))
        session = Session([item])
        session.tick(at(14, 45))
        tomorrow = DAY + timedelta(days=1)
        item.due_date = tomorrow
        assert len(session.tick(at(14, 45, tomorrow)).reminders) == 1

    def test_completing_cancels(self):
        item = make_item(due_date=DAY, due_time=time(15))
        session = Session([item])
        session.tick(at(14, 45))
        item.complete = True
        assert session.tick(at(15)).reminders == ()

    def test_reopening_does_not_replay(self):
        item = make_item(due_date=DAY, due_time=time(15))
        session = Session([item])
        session.tick(at(14, 45))
        item.complete = True
        session.tick(at(14, 50))
        item.complete = False
        assert session.tick(at(14, 55)).reminders == ()

    def test_deleted_item_is_ignored(self):
        item = make_item(due_date=DAY, due_time=time(15), deleted=True)
        assert not run([item], at(14, 45)).has_notifications


class TestEligibility:
    def test_private_list_contributes_nothing(self):
        item = make_item(due_date=DAY, due_time=time(15))
        overdue = make_item(due_date=DAY - timedelta(days=3))
        private = make_list(item, overdue, private=True)
        result = evaluate([private], PolicySettings(), at(14, 45), set(), BLOCKS)
        assert not result.has_notifications

    def test_private_list_is_absent_from_summary_counts(self):
        public = make_list(make_item(due_date=DAY))
        private = make_list(make_item(due_date=DAY), make_item(due_date=DAY), private=True)
        result = evaluate([public, private], PolicySettings(), at(9), set(), BLOCKS)
        assert result.summary is not None
        assert result.summary.due_today == 1

    def test_deleted_list_contributes_nothing(self):
        deleted = make_list(make_item(due_date=DAY, due_time=time(15)), deleted=True)
        assert not evaluate(
            [deleted], PolicySettings(), at(14, 45), set(), BLOCKS
        ).has_notifications

    def test_item_without_a_due_date_is_ignored(self):
        assert not run([make_item()], at(9), settings=PolicySettings()).has_notifications

    def test_master_switch(self):
        item = make_item(due_date=DAY, due_time=time(15))
        result = run([item], at(14, 45), settings=PolicySettings(enabled=False))
        assert not result.has_notifications
        assert result.fired == ()

    def test_subtasks_are_reminded_like_any_item(self):
        parent = make_item("Parent")
        child = make_item("Child", due_date=DAY, due_time=time(15), parent_id=parent.id)
        result = run([parent, child], at(14, 45))
        assert [r.title for r in result.reminders] == ["Child"]


# ---------------------------------------------------------------------------
# Coalescing
# ---------------------------------------------------------------------------


class TestCoalescing:
    def test_simultaneous_reminders_arrive_in_one_evaluation_in_time_order(self):
        items = [
            make_item("B", due_date=DAY, due_time=time(15)),
            make_item("A", due_date=DAY, due_time=time(15)),
            make_item("Earlier", due_date=DAY, due_time=time(14, 50)),
        ]
        result = run(items, at(14, 45))
        assert [r.title for r in result.reminders] == ["Earlier", "A", "B"]

    def test_lead_and_due_now_can_share_an_evaluation(self):
        items = [
            make_item("Due", due_date=DAY, due_time=time(15)),
            make_item("Soon", due_date=DAY, due_time=time(15, 15)),
        ]
        session = Session(items)
        session.tick(at(14, 45))
        result = session.tick(at(15))
        assert [(r.title, r.kind) for r in result.reminders] == [
            ("Due", Kind.DUE_NOW),
            ("Soon", Kind.LEAD),
        ]


# ---------------------------------------------------------------------------
# Missed reminders
# ---------------------------------------------------------------------------


class TestMissed:
    def test_deadline_passed_long_ago_today_is_missed_not_alerted(self):
        item = make_item("Report", due_date=DAY, due_time=time(10))
        result = run([item], at(11))
        assert result.reminders == ()
        assert [m.title for m in result.missed] == ["Report"]
        assert {key.kind for key in result.fired} == {"lead", "due_now"}

    def test_missed_items_are_reported_once(self):
        session = Session([make_item(due_date=DAY, due_time=time(10))])
        assert len(session.tick(at(11)).missed) == 1
        assert session.tick(at(11, 1)).missed == ()

    def test_event_that_started_while_nothing_was_running_is_missed(self):
        item = make_item("Standup", due_date=DAY, due_time=time(10), due_time_end=time(10, 30))
        result = run([item], at(10, 3))
        assert result.reminders == ()
        assert [m.title for m in result.missed] == ["Standup"]

    def test_event_reminded_on_time_is_not_missed(self):
        item = make_item(due_date=DAY, due_time=time(10), due_time_end=time(10, 30))
        session = Session([item])
        session.tick(at(9, 45))
        assert session.tick(at(11)).missed == ()

    def test_deadline_reminded_ahead_but_asleep_at_the_cutoff_is_missed(self):
        session = Session([make_item("Report", due_date=DAY, due_time=time(10))])
        assert len(session.tick(at(9, 45)).reminders) == 1
        result = session.tick(at(11))
        assert result.reminders == ()
        assert [m.title for m in result.missed] == ["Report"]

    def test_earlier_days_are_not_missed(self):
        """Yesterday's item is simply overdue; it is not replayed."""
        yesterday = DAY - timedelta(days=1)
        item = make_item(due_date=yesterday, due_time=time(10))
        result = run([item], at(8))
        assert not result.has_notifications
        assert result.fired == ()

    def test_due_just_before_midnight_still_alerts_just_after(self):
        yesterday = DAY - timedelta(days=1)
        item = make_item(due_date=yesterday, due_time=time(23, 58))
        result = run([item], at(0, 3))
        assert [r.kind for r in result.reminders] == [Kind.DUE_NOW]

    def test_first_evaluation_with_an_empty_record_is_bounded(self):
        """Nothing recorded yet and a backlog of old items: only today's
        passed items are reported, as missed, and nothing alerts."""
        items = [
            make_item(f"Old {n}", due_date=DAY - timedelta(days=n), due_time=time(9))
            for n in range(1, 30)
        ]
        items.append(make_item("This morning", due_date=DAY, due_time=time(8)))
        result = run(items, at(12))
        assert result.reminders == ()
        assert [m.title for m in result.missed] == ["This morning"]

    def test_item_created_with_a_time_already_past_is_not_missed(self):
        item = make_item(
            due_date=DAY, due_time=time(10), due_time_end=time(11), updated_at=ms(at(12))
        )
        result = run([item], at(12, 1))
        assert not result.has_notifications

    def test_missed_block_item(self):
        item = make_item("Call mum", due_date=DAY, due_time_block="morning")
        result = run([item], at(12))
        assert [(m.title, m.block) for m in result.missed] == [("Call mum", "morning")]

    def test_nothing_is_missed_with_lead_and_due_now_both_off(self):
        settings = PolicySettings(summary_enabled=False, lead_enabled=False, due_now=DueNowMode.OFF)
        item = make_item(due_date=DAY, due_time=time(10))
        result = run([item], at(11), settings=settings)
        assert not result.has_notifications

    def test_missed_items_are_in_time_order(self):
        items = [
            make_item("Later", due_date=DAY, due_time=time(10)),
            make_item("Earlier", due_date=DAY, due_time=time(8)),
        ]
        assert [m.title for m in run(items, at(12)).missed] == ["Earlier", "Later"]


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------


SUMMARY = PolicySettings()


class TestSummary:
    def test_fires_at_the_summary_time(self):
        items = [make_item(due_date=DAY), make_item(due_date=DAY - timedelta(days=2))]
        assert run(items, at(8, 59), settings=SUMMARY).summary is None
        result = run(items, at(9), settings=SUMMARY)
        assert result.summary is not None
        assert result.summary.day == DAY
        assert result.summary.due_today == 1
        assert result.summary.overdue == 1
        assert FiredKey("", "summary", "2026-11-12") in result.fired

    def test_fires_once_per_day(self):
        session = Session([make_item(due_date=DAY)], SUMMARY)
        assert session.tick(at(9)).summary is not None
        assert session.tick(at(9, 1)).summary is None
        assert session.tick(at(17)).summary is None

    def test_fires_again_the_next_day(self):
        tomorrow = DAY + timedelta(days=1)
        session = Session([make_item(due_date=tomorrow)], SUMMARY)
        session.tick(at(9))
        assert session.tick(at(9, 0, tomorrow)).summary is not None

    def test_late_launch_fires_on_first_evaluation(self):
        result = run([make_item(due_date=DAY)], at(13, 20), settings=SUMMARY)
        assert result.summary is not None

    def test_launch_before_the_summary_time_waits(self):
        session = Session([make_item(due_date=DAY)], SUMMARY)
        assert session.tick(at(7)).summary is None
        assert session.tick(at(9)).summary is not None

    def test_skipped_when_there_is_nothing_to_report(self):
        future = make_item(due_date=DAY + timedelta(days=5))
        result = run([future], at(9), settings=SUMMARY)
        assert result.summary is None
        # The decision for the day is made; an item added afterward does
        # not bring a delayed summary.
        assert FiredKey("", "summary", "2026-11-12") in result.fired

    def test_item_added_after_an_empty_summary_does_not_trigger_one(self):
        session = Session([], SUMMARY)
        session.tick(at(9))
        late = make_item(due_date=DAY)
        session.lists[0].items[late.id] = late
        assert session.tick(at(9, 30)).summary is None

    def test_summary_time_setting(self):
        settings = PolicySettings(summary_time=time(7, 30))
        items = [make_item(due_date=DAY)]
        assert run(items, at(7, 29), settings=settings).summary is None
        assert run(items, at(7, 30), settings=settings).summary is not None

    def test_disabled(self):
        result = run([make_item(due_date=DAY)], at(9), settings=NO_SUMMARY)
        assert result.summary is None
        assert result.fired == ()

    def test_completed_items_are_not_counted(self):
        items = [make_item(due_date=DAY), make_item(due_date=DAY, complete=True)]
        summary = run(items, at(9), settings=SUMMARY).summary
        assert summary is not None
        assert summary.due_today == 1

    def test_overdue_alone_produces_a_summary(self):
        summary = run(
            [make_item(due_date=DAY - timedelta(days=1))], at(9), settings=SUMMARY
        ).summary
        assert summary is not None
        assert (summary.due_today, summary.overdue) == (0, 1)

    def test_next_up_is_the_earliest_item_still_ahead(self):
        items = [
            make_item("Passed", due_date=DAY, due_time=time(8)),
            make_item("Lunch", due_date=DAY, due_time=time(12)),
            make_item("Standup", due_date=DAY, due_time=time(10), due_time_end=time(10, 15)),
            make_item("No time", due_date=DAY),
        ]
        summary = run(items, at(9), settings=SUMMARY).summary
        assert summary is not None
        assert summary.due_today == 4
        assert summary.next_up is not None
        assert summary.next_up.title == "Standup"
        assert summary.next_up.at == at(10)
        assert summary.next_up.is_event

    def test_next_up_includes_block_items(self):
        items = [
            make_item("Report", due_date=DAY, due_time=time(18)),
            make_item("Gym", due_date=DAY, due_time_block="afternoon"),
        ]
        summary = run(items, at(9), settings=SUMMARY).summary
        assert summary is not None
        assert summary.next_up is not None
        assert (summary.next_up.title, summary.next_up.block) == ("Gym", "afternoon")

    def test_next_up_is_none_without_timed_items(self):
        summary = run([make_item(due_date=DAY)], at(9), settings=SUMMARY).summary
        assert summary is not None
        assert summary.next_up is None

    def test_next_up_ignores_other_days(self):
        tomorrow = DAY + timedelta(days=1)
        items = [make_item(due_date=DAY), make_item(due_date=tomorrow, due_time=time(8))]
        summary = run(items, at(9), settings=SUMMARY).summary
        assert summary is not None
        assert summary.next_up is None

    def test_absorbs_missed_items(self):
        """One notification, not two, when the summary and the missed
        report would fire together."""
        items = [
            make_item("Early call", due_date=DAY, due_time=time(8), due_time_end=time(8, 30)),
            make_item("Later", due_date=DAY, due_time=time(16)),
        ]
        result = run(items, at(11), settings=SUMMARY)
        assert result.summary is not None
        assert [m.title for m in result.summary.missed] == ["Early call"]
        assert result.missed == ()

    def test_missed_items_alone_produce_a_summary(self):
        """With a 04:00 day start, 02:00 on the 12th still belongs to
        the 11th. An event dated the 12th at 01:00 is then neither due
        today nor overdue by date, but it was missed within this logical
        day, and that alone warrants the summary."""
        settings = PolicySettings(
            day_start_hour=4, summary_time=time(1, 30), quiet_hours_enabled=False
        )
        item = make_item("Night shift", due_date=DAY, due_time=time(1), due_time_end=time(2))
        result = run([item], at(2), settings=settings)
        assert result.summary is not None
        assert result.summary.day == DAY - timedelta(days=1)
        assert (result.summary.due_today, result.summary.overdue) == (0, 0)
        assert [m.title for m in result.summary.missed] == ["Night shift"]

    def test_missed_report_stands_alone_after_the_summary_has_fired(self):
        session = Session([make_item("Report", due_date=DAY, due_time=time(14))], SUMMARY)
        assert session.tick(at(9)).summary is not None
        result = session.tick(at(16))
        assert result.summary is None
        assert [m.title for m in result.missed] == ["Report"]

    def test_summary_and_reminders_can_share_an_evaluation(self):
        items = [make_item("Standup", due_date=DAY, due_time=time(9, 15))]
        result = run(items, at(9), settings=SUMMARY)
        assert result.summary is not None
        assert len(result.reminders) == 1


class TestSummaryAndDayStart:
    # These scenarios sit in the small hours; quiet hours have their own
    # tests, including how they combine with the day start.
    SETTINGS = PolicySettings(day_start_hour=4, quiet_hours_enabled=False)

    def test_due_today_follows_the_logical_day(self):
        """At 02:00 with a 04:00 day start it is still the previous day,
        whose summary has long since been due."""
        yesterday = DAY - timedelta(days=1)
        items = [make_item("Yesterday", due_date=yesterday), make_item("Today", due_date=DAY)]
        result = run(items, at(2), settings=self.SETTINGS)
        assert result.summary is not None
        assert result.summary.day == yesterday
        assert result.summary.due_today == 1
        assert result.summary.overdue == 0

    def test_no_new_summary_at_calendar_midnight(self):
        yesterday = DAY - timedelta(days=1)
        session = Session([make_item(due_date=DAY)], self.SETTINGS)
        session.tick(at(9, 0, yesterday))
        assert session.tick(at(0, 1)).summary is None
        assert session.tick(at(3, 59)).summary is None
        assert session.tick(at(9)).summary is not None

    def test_summary_time_before_the_day_start_lands_on_the_next_calendar_date(self):
        settings = PolicySettings(day_start_hour=4, summary_time=time(2), quiet_hours_enabled=False)
        yesterday = DAY - timedelta(days=1)
        items = [make_item(due_date=yesterday)]
        # 10:00 on the 11th is in the logical day of the 11th, whose
        # summary time (02:00) falls on the 12th.
        assert run(items, at(10, 0, yesterday), settings=settings).summary is None
        result = run(items, at(2), settings=settings)
        assert result.summary is not None
        assert result.summary.day == yesterday


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------


class TestInQuietHours:
    DEFAULT = PolicySettings()

    @pytest.mark.parametrize(
        ("moment", "quiet"),
        [
            (time(21, 59), False),
            (time(22, 0), True),
            (time(23, 30), True),
            (time(0, 0), True),
            (time(6, 59, 59), True),
            (time(7, 0), False),
            (time(12, 0), False),
        ],
    )
    def test_default_window_crosses_midnight(self, moment, quiet):
        assert in_quiet_hours(moment, self.DEFAULT) is quiet

    @pytest.mark.parametrize(
        ("moment", "quiet"),
        [(time(12, 59), False), (time(13, 0), True), (time(14, 59), True), (time(15, 0), False)],
    )
    def test_window_within_one_day(self, moment, quiet):
        settings = PolicySettings(quiet_start=time(13), quiet_end=time(15))
        assert in_quiet_hours(moment, settings) is quiet

    def test_disabled(self):
        assert not in_quiet_hours(time(23), PolicySettings(quiet_hours_enabled=False))

    def test_equal_start_and_end_is_an_empty_window(self):
        settings = PolicySettings(quiet_start=time(8), quiet_end=time(8))
        assert not in_quiet_hours(time(8), settings)
        assert not in_quiet_hours(time(20), settings)


class TestQuietHoursAndTimedReminders:
    def test_lead_reminder_is_delivered_inside_quiet_hours(self):
        item = make_item("Early flight", due_date=DAY, due_time=time(5))
        result = run([item], at(4, 45))
        assert [(r.title, r.kind) for r in result.reminders] == [("Early flight", Kind.LEAD)]
        assert result.held_items == ()

    def test_due_now_alert_is_delivered_inside_quiet_hours(self):
        item = make_item("Early flight", due_date=DAY, due_time=time(5))
        result = run([item], at(5))
        assert [(r.title, r.kind) for r in result.reminders] == [("Early flight", Kind.DUE_NOW)]


class TestQuietHoursSilencingTimedReminders:
    SILENT = PolicySettings(summary_enabled=False, quiet_allow_timed=False)

    def test_lead_reminder_is_held_and_not_recorded(self):
        item = make_item("Early flight", due_date=DAY, due_time=time(5))
        result = run([item], at(4, 45), settings=self.SILENT)
        assert result.reminders == ()
        assert result.fired == ()
        assert [h.title for h in result.held_items] == ["Early flight"]

    def test_due_now_alert_is_held_and_not_recorded(self):
        item = make_item("Early flight", due_date=DAY, due_time=time(5))
        result = run([item], at(5), settings=self.SILENT)
        assert result.reminders == ()
        assert result.fired == ()
        assert [h.title for h in result.held_items] == ["Early flight"]

    def test_outside_quiet_hours_nothing_changes(self):
        item = make_item(due_date=DAY, due_time=time(15))
        result = run([item], at(14, 45), settings=self.SILENT)
        assert [r.kind for r in result.reminders] == [Kind.LEAD]

    def test_lead_reminder_still_ahead_is_delivered_when_the_window_ends(self):
        session = Session([make_item("Standup", due_date=DAY, due_time=time(7, 10))], self.SILENT)
        assert session.tick(at(6, 55)).reminders == ()
        result = session.tick(at(7))
        assert [(r.kind, r.minutes_until) for r in result.reminders] == [(Kind.LEAD, 10)]

    def test_deadline_just_past_is_alerted_when_the_window_ends(self):
        session = Session([make_item("Submit", due_date=DAY, due_time=time(6, 55))], self.SILENT)
        assert session.tick(at(6, 55)).reminders == ()
        result = session.tick(at(7))
        assert [r.kind for r in result.reminders] == [Kind.DUE_NOW]
        assert result.missed == ()

    def test_deadline_long_past_is_reported_as_missed_when_the_window_ends(self):
        session = Session([make_item("Submit", due_date=DAY, due_time=time(5))], self.SILENT)
        for moment in (at(4, 45), at(5), at(6, 59)):
            result = session.tick(moment)
            assert not result.has_notifications
        result = session.tick(at(7))
        assert result.reminders == ()
        assert [m.title for m in result.missed] == ["Submit"]
        assert not session.tick(at(7, 1)).has_notifications

    def test_event_that_started_in_the_window_is_reported_as_missed(self):
        event = make_item("Call", due_date=DAY, due_time=time(6), due_time_end=time(6, 30))
        session = Session([event], self.SILENT)
        assert not session.tick(at(5, 45)).has_notifications
        assert [m.title for m in session.tick(at(7)).missed] == ["Call"]

    def test_item_from_the_evening_before_is_only_overdue(self):
        yesterday = DAY - timedelta(days=1)
        session = Session([make_item(due_date=yesterday, due_time=time(23))], self.SILENT)
        assert not session.tick(at(22, 45, yesterday)).has_notifications
        assert not session.tick(at(23, 0, yesterday)).has_notifications
        result = session.tick(at(7))
        assert not result.has_notifications
        assert result.held_items == ()

    def test_item_edited_inside_its_lead_window_is_not_held(self):
        item = make_item(due_date=DAY, due_time=time(5), updated_at=ms(at(4, 50)))
        result = run([item], at(4, 55), settings=self.SILENT)
        assert result.held_items == ()


class TestQuietHoursAndTheSummary:
    def test_summary_time_inside_quiet_hours_fires_when_they_end(self):
        settings = PolicySettings(summary_time=time(6))
        session = Session([make_item(due_date=DAY)], settings)
        assert session.tick(at(6)).summary is None
        assert session.tick(at(6, 59)).summary is None
        assert session.tick(at(7)).summary is not None
        assert session.tick(at(7, 1)).summary is None

    def test_late_evening_summary_time_fires_that_morning(self):
        settings = PolicySettings(summary_time=time(23))
        session = Session([make_item(due_date=DAY)], settings)
        assert session.tick(at(6, 59)).summary is None
        result = session.tick(at(7))
        assert result.summary is not None
        assert result.summary.day == DAY
        assert session.tick(at(23)).summary is None

    def test_summary_time_at_the_start_of_quiet_hours_counts_as_inside(self):
        settings = PolicySettings(summary_time=time(22))
        assert run([make_item(due_date=DAY)], at(7), settings=settings).summary is not None

    def test_summary_time_at_the_end_of_quiet_hours_is_outside(self):
        settings = PolicySettings(summary_time=time(7))
        session = Session([make_item(due_date=DAY)], settings)
        assert session.tick(at(6, 59)).summary is None
        assert session.tick(at(7)).summary is not None

    def test_launch_inside_quiet_hours_holds_the_summary(self):
        """Launched at 23:30 with the day's summary never given: it is
        not given that night, and is not recorded as given either."""
        result = run([make_item(due_date=DAY)], at(23, 30), settings=PolicySettings())
        assert result.summary is None
        assert result.fired == ()
        assert result.held_summary

    def test_summary_held_overnight_is_not_given_for_the_day_gone_by(self):
        tomorrow = DAY + timedelta(days=1)
        session = Session([make_item(due_date=DAY)], PolicySettings())
        session.tick(at(23, 30))
        assert session.tick(at(7, 0, tomorrow)).summary is None
        result = session.tick(at(9, 0, tomorrow))
        assert result.summary is not None
        assert (result.summary.day, result.summary.overdue) == (tomorrow, 1)

    def test_empty_summary_is_not_reported_as_held(self):
        assert not run([], at(23, 30), settings=PolicySettings()).held_summary

    def test_window_within_the_day_delays_the_summary(self):
        settings = PolicySettings(quiet_start=time(8), quiet_end=time(10))
        session = Session([make_item(due_date=DAY)], settings)
        assert session.tick(at(9)).summary is None
        assert session.tick(at(10)).summary is not None

    def test_quiet_hours_disabled(self):
        settings = PolicySettings(summary_time=time(6), quiet_hours_enabled=False)
        assert run([make_item(due_date=DAY)], at(6), settings=settings).summary is not None

    def test_summary_time_in_quiet_hours_with_a_later_day_start(self):
        """Day start 04:00, summary set for 02:00, quiet until 07:00:
        the summary is given at 07:00, three hours into the logical day."""
        settings = PolicySettings(day_start_hour=4, summary_time=time(2))
        session = Session([make_item(due_date=DAY)], settings)
        assert session.tick(at(4)).summary is None
        result = session.tick(at(7))
        assert result.summary is not None
        assert result.summary.day == DAY


class TestQuietHoursAndMissedItems:
    def test_missed_items_wait_for_the_window_to_end(self):
        """Woken at 23:00 with a 21:00 deadline never alerted: the report
        waits, and with it the record that the alert was dealt with."""
        item = make_item("Submit", due_date=DAY, due_time=time(21))
        result = run([item], at(23))
        assert result.missed == ()
        assert result.fired == ()
        assert [h.title for h in result.held_items] == ["Submit"]

    def test_missed_items_from_the_small_hours_are_reported_when_the_window_ends(self):
        session = Session([make_item("Submit", due_date=DAY, due_time=time(1))], NO_SUMMARY)
        # Asleep at 01:00; the first evaluation is at 03:00.
        assert not session.tick(at(3)).has_notifications
        assert [m.title for m in session.tick(at(7)).missed] == ["Submit"]

    def test_event_missed_in_the_small_hours_waits_for_the_window_to_end(self):
        """An event gets no due-now alert; the one reminder it would
        have had is held, not written off."""
        event = make_item("Call", due_date=DAY, due_time=time(1), due_time_end=time(2))
        session = Session([event], NO_SUMMARY)
        held = session.tick(at(3))
        assert held.missed == ()
        assert held.fired == ()
        assert [h.title for h in held.held_items] == ["Call"]
        assert [m.title for m in session.tick(at(7)).missed] == ["Call"]
        assert not session.tick(at(7, 1)).has_notifications

    def test_waking_after_the_window_has_ended_reports_at_once(self):
        """Asleep from before the window to after it: nothing is held."""
        item = make_item("Submit", due_date=DAY, due_time=time(5))
        result = run([item], at(8))
        assert [m.title for m in result.missed] == ["Submit"]
        assert result.held_items == ()

    def test_held_missed_items_join_the_summary_when_both_are_released(self):
        settings = PolicySettings(summary_time=time(6))
        session = Session([make_item("Submit", due_date=DAY, due_time=time(1))], settings)
        assert not session.tick(at(6, 30)).has_notifications
        result = session.tick(at(7))
        assert result.summary is not None
        assert [m.title for m in result.summary.missed] == ["Submit"]
        assert result.missed == ()

    def test_fresh_due_now_alert_is_not_held_with_the_missed_items(self):
        item = make_item("Submit", due_date=DAY, due_time=time(23))
        result = run([item], at(23, 5))
        assert [r.kind for r in result.reminders] == [Kind.DUE_NOW]


# ---------------------------------------------------------------------------
# Focus sessions
# ---------------------------------------------------------------------------


class TestFocusHold:
    SUMMARY = PolicySettings()

    def test_summary_waits_for_the_session_to_end(self):
        session = Session([make_item(due_date=DAY)], self.SUMMARY)
        held = session.tick(at(9), focus_active=True)
        assert held.summary is None
        assert held.fired == ()
        assert held.held_summary
        assert session.tick(at(9, 20), focus_active=True).summary is None
        assert session.tick(at(9, 25)).summary is not None
        assert session.tick(at(9, 26)).summary is None

    def test_released_summary_reflects_the_moment_it_is_given(self):
        early = make_item("Early", due_date=DAY, due_time=time(9, 30), due_time_end=time(10))
        later = make_item("Later", due_date=DAY, due_time=time(15))
        session = Session([early, later], self.SUMMARY)
        session.tick(at(9), focus_active=True)
        session.tick(at(9, 15), focus_active=True)  # lead reminder for "Early"
        result = session.tick(at(11))
        assert result.summary is not None
        assert result.summary.next_up is not None
        assert result.summary.next_up.title == "Later"

    def test_lead_reminder_passes_through(self):
        item = make_item(due_date=DAY, due_time=time(15))
        result = run([item], at(14, 45), focus_active=True)
        assert [r.kind for r in result.reminders] == [Kind.LEAD]

    def test_due_now_alert_passes_through(self):
        item = make_item(due_date=DAY, due_time=time(15))
        result = run([item], at(15), focus_active=True)
        assert [r.kind for r in result.reminders] == [Kind.DUE_NOW]

    def test_missed_items_wait_for_the_session_to_end(self):
        session = Session([make_item("Submit", due_date=DAY, due_time=time(10))], NO_SUMMARY)
        held = session.tick(at(13), focus_active=True)
        assert held.missed == ()
        assert held.fired == ()
        assert [h.title for h in held.held_items] == ["Submit"]
        assert [m.title for m in session.tick(at(13, 30)).missed] == ["Submit"]
        assert not session.tick(at(13, 31)).has_notifications

    def test_missed_event_waits_for_the_session_to_end(self):
        event = make_item("Call", due_date=DAY, due_time=time(10), due_time_end=time(11))
        session = Session([event], NO_SUMMARY)
        held = session.tick(at(13), focus_active=True)
        assert held.missed == ()
        assert held.fired == ()
        assert [h.title for h in held.held_items] == ["Call"]
        assert [m.title for m in session.tick(at(13, 30)).missed] == ["Call"]

    def test_hold_can_be_turned_off(self):
        settings = PolicySettings(hold_during_focus=False)
        result = run([make_item(due_date=DAY)], at(9), settings=settings, focus_active=True)
        assert result.summary is not None

    def test_no_session_no_hold(self):
        result = run([make_item(due_date=DAY)], at(9), settings=self.SUMMARY)
        assert result.summary is not None
        assert not result.held_summary

    def test_session_running_past_the_end_of_the_day_drops_that_days_summary(self):
        tomorrow = DAY + timedelta(days=1)
        settings = PolicySettings(quiet_hours_enabled=False)
        session = Session([make_item(due_date=DAY)], settings)
        assert session.tick(at(9), focus_active=True).summary is None
        assert session.tick(at(23, 59), focus_active=True).summary is None
        # A new day: its own summary is not due until 09:00.
        assert session.tick(at(0, 5, tomorrow)).summary is None
        result = session.tick(at(9, 0, tomorrow))
        assert result.summary is not None
        assert result.summary.overdue == 1


# ---------------------------------------------------------------------------
# Advance reminders
# ---------------------------------------------------------------------------


def ahead(title: str, days_from_now: int, remind: int, cadence: str = "once", **fields) -> TodoItem:
    """An item due ``days_from_now`` days after DAY with an advance reminder."""
    return make_item(
        title,
        due_date=DAY + timedelta(days=days_from_now),
        remind_before_days=remind,
        reminder_cadence=cadence,
        **fields,
    )


def coming_up_titles(result: Evaluation) -> list[str]:
    return [] if result.summary is None else [c.title for c in result.summary.coming_up]


class TestAdvanceReminderFor:
    def test_inside_the_window(self):
        item = ahead("Tax return", 3, remind=3)
        assert advance_reminder_for(item, DAY) == ComingUp(
            item.id, "Tax return", DAY + timedelta(days=3), 3
        )

    def test_before_the_window(self):
        assert advance_reminder_for(ahead("Tax return", 4, remind=3), DAY) is None

    def test_the_day_before_is_the_last_day(self):
        reminder = advance_reminder_for(ahead("Tax return", 1, remind=3), DAY)
        assert reminder is not None
        assert reminder.days_until == 1

    def test_not_on_the_due_date_itself(self):
        assert advance_reminder_for(ahead("Tax return", 0, remind=3), DAY) is None

    def test_not_once_overdue(self):
        assert advance_reminder_for(ahead("Tax return", -1, remind=3), DAY) is None

    @pytest.mark.parametrize("cadence", ["none", "", "weekly"])
    def test_cadence_that_asks_for_nothing(self, cadence):
        assert advance_reminder_for(ahead("Tax return", 2, remind=3, cadence=cadence), DAY) is None

    @pytest.mark.parametrize("days", [0, -2])
    def test_no_day_count(self, days):
        assert advance_reminder_for(ahead("Tax return", 2, remind=days), DAY) is None

    def test_no_due_date(self):
        item = make_item(remind_before_days=3, reminder_cadence="once")
        assert advance_reminder_for(item, DAY) is None


class TestAdvanceReminders:
    SUMMARY = PolicySettings()

    def test_appears_in_the_summary(self):
        result = run([ahead("Tax return", 3, remind=3)], at(9), settings=self.SUMMARY)
        assert result.summary is not None
        assert [(c.title, c.days_until) for c in result.summary.coming_up] == [("Tax return", 3)]

    def test_alone_is_enough_for_a_summary(self):
        result = run([ahead("Tax return", 3, remind=3)], at(9), settings=self.SUMMARY)
        assert result.summary is not None
        assert (result.summary.due_today, result.summary.overdue) == (0, 0)
        assert result.summary.next_up is None

    def test_is_not_counted_as_due_today_or_overdue(self):
        items = [make_item(due_date=DAY), ahead("Tax return", 2, remind=3)]
        result = run(items, at(9), settings=self.SUMMARY)
        assert result.summary is not None
        assert (result.summary.due_today, result.summary.overdue) == (1, 0)

    def test_produces_no_notification_of_its_own(self):
        """Outside the summary there is nothing: no reminder, nothing missed."""
        session = Session([ahead("Tax return", 3, remind=3)], self.SUMMARY)
        session.tick(at(9))
        later = session.tick(at(12))
        assert not later.has_notifications

    def test_nothing_before_the_summary_time(self):
        result = run([ahead("Tax return", 3, remind=3)], at(8, 59), settings=self.SUMMARY)
        assert not result.has_notifications

    def test_nothing_with_the_summary_off(self):
        result = run([ahead("Tax return", 3, remind=3)], at(9), settings=NO_SUMMARY)
        assert not result.has_notifications
        assert result.fired == ()

    def test_sorted_soonest_first(self):
        items = [
            ahead("Later", 5, remind=7, cadence="daily_until_due"),
            ahead("Sooner", 2, remind=7, cadence="daily_until_due"),
            ahead("Also sooner", 2, remind=7, cadence="daily_until_due"),
        ]
        result = run(items, at(9), settings=self.SUMMARY)
        assert coming_up_titles(result) == ["Also sooner", "Sooner", "Later"]

    def test_timed_item_is_reminded_ahead_like_any_other(self):
        item = ahead("Flight", 2, remind=2, due_time=time(6))
        assert coming_up_titles(run([item], at(9), settings=self.SUMMARY)) == ["Flight"]

    def test_completed_item_is_left_out(self):
        item = ahead("Tax return", 2, remind=3, complete=True)
        assert run([item], at(9), settings=self.SUMMARY).summary is None

    def test_private_list_is_left_out(self):
        private = make_list(ahead("Secret", 2, remind=3), private=True)
        assert run([private], at(9), settings=self.SUMMARY).summary is None

    def test_follows_the_logical_day(self):
        """At 02:00 with a 04:00 day start it is still the day before,
        so an item due on DAY is one day off, not due today."""
        settings = PolicySettings(day_start_hour=4, quiet_hours_enabled=False)
        item = make_item("Tax return", due_date=DAY, remind_before_days=1, reminder_cadence="once")
        result = run([item], at(2), settings=settings)
        assert result.summary is not None
        assert [(c.title, c.days_until) for c in result.summary.coming_up] == [("Tax return", 1)]


class TestAdvanceReminderOnce:
    SUMMARY = PolicySettings()

    def _days(self, session: Session, count: int) -> list[list[str]]:
        """Titles in each day's 09:00 summary over ``count`` days from DAY."""
        return [
            coming_up_titles(session.tick(at(9, 0, DAY + timedelta(days=offset))))
            for offset in range(count)
        ]

    def test_given_once_on_the_first_day_of_the_window(self):
        session = Session([ahead("Tax return", 5, remind=3)], self.SUMMARY)
        assert self._days(session, 6) == [[], [], ["Tax return"], [], [], []]

    def test_records_that_it_was_given(self):
        item = ahead("Tax return", 3, remind=3)
        result = run([item], at(9), settings=self.SUMMARY)
        due = (DAY + timedelta(days=3)).isoformat()
        assert FiredKey(str(item.id), Kind.ADVANCE.value, due) in result.fired

    def test_a_missed_first_day_is_made_up_on_the_next_summary(self):
        """Nothing ran on the first day of the window; the reminder is
        given by the next summary instead of being lost."""
        session = Session([ahead("Tax return", 5, remind=3)], self.SUMMARY)
        assert coming_up_titles(session.tick(at(9, 0, DAY + timedelta(days=3)))) == ["Tax return"]
        assert coming_up_titles(session.tick(at(9, 0, DAY + timedelta(days=4)))) == []

    def test_days_until_is_as_of_the_summary_that_gives_it(self):
        session = Session([ahead("Tax return", 5, remind=3)], self.SUMMARY)
        result = session.tick(at(9, 0, DAY + timedelta(days=4)))
        assert result.summary is not None
        assert result.summary.coming_up[0].days_until == 1

    def test_not_given_once_the_due_date_has_arrived(self):
        session = Session([ahead("Tax return", 2, remind=1)], self.SUMMARY)
        result = session.tick(at(9, 0, DAY + timedelta(days=2)))
        assert result.summary is not None
        assert result.summary.coming_up == ()
        assert result.summary.due_today == 1

    def test_rescheduling_re_arms(self):
        item = ahead("Tax return", 2, remind=3)
        session = Session([item], self.SUMMARY)
        assert coming_up_titles(session.tick(at(9))) == ["Tax return"]
        item.due_date = DAY + timedelta(days=4)
        assert coming_up_titles(session.tick(at(9, 0, DAY + timedelta(days=1)))) == ["Tax return"]

    def test_held_summary_does_not_use_up_the_reminder(self):
        session = Session([ahead("Tax return", 2, remind=3)], self.SUMMARY)
        held = session.tick(at(9), focus_active=True)
        assert held.summary is None
        assert held.fired == ()
        assert held.held_summary
        assert coming_up_titles(session.tick(at(9, 30))) == ["Tax return"]

    def test_summary_held_past_the_end_of_the_day_leaves_it_for_the_next(self):
        settings = PolicySettings(quiet_hours_enabled=False)
        session = Session([ahead("Tax return", 3, remind=3)], settings)
        session.tick(at(9), focus_active=True)
        session.tick(at(23, 59), focus_active=True)
        tomorrow = DAY + timedelta(days=1)
        assert coming_up_titles(session.tick(at(9, 0, tomorrow))) == ["Tax return"]

    def test_already_given_leaves_nothing_to_hold(self):
        session = Session([ahead("Tax return", 3, remind=3)], self.SUMMARY)
        session.tick(at(9))
        tomorrow = DAY + timedelta(days=1)
        assert not session.tick(at(9, 0, tomorrow), focus_active=True).held_summary


class TestAdvanceReminderDaily:
    SUMMARY = PolicySettings()

    def test_given_every_day_through_the_day_before(self):
        session = Session([ahead("Passport", 4, remind=3, cadence="daily_until_due")], self.SUMMARY)
        seen = []
        for offset in range(6):
            result = session.tick(at(9, 0, DAY + timedelta(days=offset)))
            seen.append(
                [] if result.summary is None else [c.days_until for c in result.summary.coming_up]
            )
        # Days 0-5: outside the window, then 3, 2 and 1 days ahead, the
        # due date itself, and the day after.
        assert seen == [[], [3], [2], [1], [], []]

    def test_records_nothing_of_its_own(self):
        item = ahead("Passport", 2, remind=3, cadence="daily_until_due")
        result = run([item], at(9), settings=self.SUMMARY)
        assert [key.kind for key in result.fired] == [Kind.SUMMARY.value]

    def test_once_and_daily_side_by_side(self):
        once = ahead("Once", 3, remind=3)
        daily = ahead("Daily", 3, remind=3, cadence="daily_until_due")
        session = Session([once, daily], self.SUMMARY)
        assert coming_up_titles(session.tick(at(9))) == ["Daily", "Once"]
        tomorrow = DAY + timedelta(days=1)
        assert coming_up_titles(session.tick(at(9, 0, tomorrow))) == ["Daily"]


class TestEvaluationShape:
    def test_empty_database(self):
        result = evaluate([], PolicySettings(), at(9), set(), BLOCKS)
        assert not result.has_notifications
        # The day's summary decision is still recorded.
        assert result.fired == (FiredKey("", "summary", "2026-11-12"),)

    def test_fired_keys_match_the_plain_tuples_storage_returns(self):
        item = make_item(due_date=DAY, due_time=time(15))
        first = run([item], at(14, 45))
        stored = {tuple(key) for key in first.fired}
        assert run([item], at(14, 46), fired=stored).reminders == ()

    @pytest.mark.parametrize("minute", range(0, 60, 7))
    def test_a_full_day_of_ticks_alerts_each_item_at_most_twice(self, minute):
        """Replay a day minute by minute: a deadline yields exactly one
        lead reminder and one due-now alert, an event exactly one lead
        reminder, and the day exactly one summary."""
        deadline = make_item("Deadline", due_date=DAY, due_time=time(13, minute))
        event = make_item("Event", due_date=DAY, due_time=time(16, minute), due_time_end=time(17))
        session = Session([deadline, event], PolicySettings())
        seen: list[tuple[str, Kind]] = []
        summaries = 0
        moment = at(0)
        while moment < at(23, 59):
            result = session.tick(moment)
            seen.extend((r.title, r.kind) for r in result.reminders)
            summaries += result.summary is not None
            assert result.missed == ()
            moment += timedelta(minutes=1)
        assert seen == [
            ("Deadline", Kind.LEAD),
            ("Deadline", Kind.DUE_NOW),
            ("Event", Kind.LEAD),
        ]
        assert summaries == 1


# ---------------------------------------------------------------------------
# Evening preview
# ---------------------------------------------------------------------------

TOMORROW = DAY + timedelta(days=1)
PREVIEW = PolicySettings(summary_enabled=False, preview_enabled=True)
PREVIEW_KEY = FiredKey("", "preview", DAY.isoformat())


class TestEveningPreview:
    def test_off_by_default(self):
        result = run([make_item(due_date=TOMORROW)], at(20))
        assert result.preview is None
        assert PREVIEW_KEY not in result.fired

    def test_given_at_the_preview_time(self):
        result = run([make_item(due_date=TOMORROW)], at(20), settings=PREVIEW)
        assert result.preview == Preview(DAY, 1, None)
        assert PREVIEW_KEY in result.fired
        assert result.has_notifications

    def test_not_before_the_preview_time(self):
        result = run([make_item(due_date=TOMORROW)], at(19, 59), settings=PREVIEW)
        assert result.preview is None
        assert PREVIEW_KEY not in result.fired

    def test_once_per_day(self):
        session = Session([make_item(due_date=TOMORROW)], PREVIEW)
        assert session.tick(at(20)).preview is not None
        assert session.tick(at(20, 1)).preview is None
        assert session.tick(at(21, 30)).preview is None

    def test_given_again_the_next_day(self):
        item = make_item(due_date=DAY + timedelta(days=2))
        session = Session([make_item(due_date=TOMORROW), item], PREVIEW)
        assert session.tick(at(20)).preview is not None
        later = session.tick(at(20, 0, TOMORROW))
        assert later.preview == Preview(TOMORROW, 1, None)

    def test_counts_only_the_next_day(self):
        items = [
            make_item("Today", due_date=DAY),
            make_item("Overdue", due_date=DAY - timedelta(days=1)),
            make_item("Tomorrow A", due_date=TOMORROW),
            make_item("Tomorrow B", due_date=TOMORROW),
            make_item("Later", due_date=DAY + timedelta(days=2)),
            make_item("Undated"),
        ]
        preview = run(items, at(20), settings=PREVIEW).preview
        assert preview is not None
        assert preview.due_tomorrow == 2

    def test_nothing_due_tomorrow_gives_no_preview(self):
        result = run([make_item(due_date=DAY)], at(20), settings=PREVIEW)
        assert result.preview is None
        assert not result.has_notifications
        # The day's decision is recorded all the same.
        assert PREVIEW_KEY in result.fired

    def test_first_is_the_earliest_timed_item(self):
        items = [
            make_item("Lunch", due_date=TOMORROW, due_time=time(12, 30)),
            make_item("Dentist", due_date=TOMORROW, due_time=time(9)),
            make_item("Untimed", due_date=TOMORROW),
        ]
        preview = run(items, at(20), settings=PREVIEW).preview
        assert preview is not None
        assert preview.due_tomorrow == 3
        assert preview.first is not None
        assert (preview.first.title, preview.first.at) == ("Dentist", at(9, 0, TOMORROW))

    def test_a_block_item_counts_from_its_block_start(self):
        items = [
            make_item("Laundry", due_date=TOMORROW, due_time_block="morning"),
            make_item("Call", due_date=TOMORROW, due_time=time(15)),
        ]
        preview = run(items, at(20), settings=PREVIEW).preview
        assert preview is not None and preview.first is not None
        assert preview.first.title == "Laundry"
        assert preview.first.block == "morning"

    def test_a_timed_item_today_is_not_the_first(self):
        items = [
            make_item("Tonight", due_date=DAY, due_time=time(23)),
            make_item("Dentist", due_date=TOMORROW, due_time=time(9)),
        ]
        preview = run(items, at(20), settings=PREVIEW).preview
        assert preview is not None and preview.first is not None
        assert preview.first.title == "Dentist"

    def test_completed_items_are_left_out(self):
        items = [
            make_item("Done", due_date=TOMORROW, complete=True),
            make_item("Open", due_date=TOMORROW),
        ]
        preview = run(items, at(20), settings=PREVIEW).preview
        assert preview is not None
        assert preview.due_tomorrow == 1

    def test_private_lists_are_left_out(self):
        private = make_list(make_item(due_date=TOMORROW), private=True)
        result = run([private], at(20), settings=PREVIEW)
        assert result.preview is None

    def test_master_switch_silences_it(self):
        settings = PolicySettings(enabled=False, preview_enabled=True)
        result = run([make_item(due_date=TOMORROW)], at(20), settings=settings)
        assert result.preview is None
        assert result.fired == ()

    def test_late_start_gives_it_on_the_first_evaluation_after(self):
        result = run([make_item(due_date=TOMORROW)], at(21, 30), settings=PREVIEW)
        assert result.preview is not None

    def test_a_day_that_ended_without_one_is_not_made_up(self):
        # First evaluation is the next morning: yesterday's preview is
        # gone, and today's is not due until the evening.
        item = make_item(due_date=TOMORROW + timedelta(days=1))
        result = run([item], at(8, 0, TOMORROW), settings=PREVIEW)
        assert result.preview is None
        assert result.fired == ()

    def test_custom_preview_time(self):
        settings = PolicySettings(
            summary_enabled=False, preview_enabled=True, preview_time=time(18, 30)
        )
        item = make_item(due_date=TOMORROW)
        assert run([item], at(18, 29), settings=settings).preview is None
        assert run([item], at(18, 30), settings=settings).preview is not None

    def test_with_the_summary_in_one_evaluation(self):
        settings = PolicySettings(preview_enabled=True)
        items = [make_item("Today", due_date=DAY), make_item("Tomorrow", due_date=TOMORROW)]
        result = run(items, at(20, 30), settings=settings)
        assert result.summary is not None
        assert result.preview is not None
        assert {key.kind for key in result.fired} == {"summary", "preview"}


class TestEveningPreviewAndDayStart:
    SETTINGS = PolicySettings(
        summary_enabled=False, preview_enabled=True, day_start_hour=4, quiet_hours_enabled=False
    )

    def test_after_midnight_is_still_the_same_day(self):
        # 01:00 on the 13th belongs to the 12th; "tomorrow" is the 13th.
        item = make_item(due_date=TOMORROW)
        result = run([item], at(1, 0, TOMORROW), settings=self.SETTINGS)
        assert result.preview == Preview(DAY, 1, None)

    def test_preview_time_before_the_day_start_falls_after_midnight(self):
        settings = PolicySettings(
            summary_enabled=False,
            preview_enabled=True,
            preview_time=time(1, 0),
            day_start_hour=4,
            quiet_hours_enabled=False,
        )
        item = make_item(due_date=TOMORROW)
        assert run([item], at(23, 0), settings=settings).preview is None
        assert run([item], at(1, 0, TOMORROW), settings=settings).preview is not None


class TestEffectivePreviewTime:
    def test_outside_quiet_hours_it_is_the_set_time(self):
        assert effective_preview_time(PREVIEW) == time(20, 0)

    @pytest.mark.parametrize("inside", [time(22, 0), time(23, 0), time(2, 0), time(6, 59)])
    def test_inside_quiet_hours_it_is_the_minute_before_they_start(self, inside):
        settings = PolicySettings(preview_enabled=True, preview_time=inside)
        assert effective_preview_time(settings) == time(21, 59)

    def test_the_end_of_quiet_hours_is_outside_them(self):
        settings = PolicySettings(preview_enabled=True, preview_time=time(7, 0))
        assert effective_preview_time(settings) == time(7, 0)

    def test_quiet_hours_starting_at_midnight(self):
        settings = PolicySettings(
            preview_enabled=True,
            preview_time=time(1, 0),
            quiet_start=time(0, 0),
            quiet_end=time(7, 0),
        )
        assert effective_preview_time(settings) == time(23, 59)

    def test_quiet_hours_switched_off(self):
        settings = PolicySettings(
            preview_enabled=True, preview_time=time(23, 0), quiet_hours_enabled=False
        )
        assert effective_preview_time(settings) == time(23, 0)


class TestEveningPreviewAndQuietHours:
    LATE = PolicySettings(summary_enabled=False, preview_enabled=True, preview_time=time(23, 0))

    def test_set_inside_quiet_hours_it_is_given_before_they_start(self):
        item = make_item(due_date=TOMORROW)
        assert run([item], at(21, 58), settings=self.LATE).preview is None
        assert run([item], at(21, 59), settings=self.LATE).preview is not None

    def test_not_given_once_quiet_hours_have_begun(self):
        result = run([make_item(due_date=TOMORROW)], at(22, 0), settings=self.LATE)
        assert result.preview is None
        assert result.held_preview
        assert PREVIEW_KEY not in result.fired

    def test_missed_before_quiet_hours_it_is_not_given_in_the_morning(self):
        session = Session([make_item(due_date=TOMORROW + timedelta(days=1))], self.LATE)
        assert session.tick(at(22, 30)).preview is None
        morning = session.tick(at(7, 0, TOMORROW))
        assert morning.preview is None
        assert not morning.held_preview

    def test_first_evaluation_inside_quiet_hours_holds_a_normal_preview(self):
        result = run([make_item(due_date=TOMORROW)], at(22, 15), settings=PREVIEW)
        assert result.preview is None
        assert result.held_preview

    def test_nothing_due_tomorrow_is_not_reported_as_held(self):
        result = run([make_item(due_date=DAY)], at(22, 15), settings=PREVIEW)
        assert not result.held_preview


class TestEveningPreviewAndFocus:
    def test_held_while_a_session_runs(self):
        result = run([make_item(due_date=TOMORROW)], at(20), settings=PREVIEW, focus_active=True)
        assert result.preview is None
        assert result.held_preview
        assert PREVIEW_KEY not in result.fired

    def test_given_when_the_session_ends(self):
        session = Session([make_item(due_date=TOMORROW)], PREVIEW)
        assert session.tick(at(20), focus_active=True).preview is None
        assert session.tick(at(20, 25), focus_active=True).preview is None
        assert session.tick(at(20, 26)).preview is not None

    def test_not_held_when_holding_is_switched_off(self):
        settings = PolicySettings(
            summary_enabled=False, preview_enabled=True, hold_during_focus=False
        )
        result = run([make_item(due_date=TOMORROW)], at(20), settings=settings, focus_active=True)
        assert result.preview is not None

    def test_a_session_running_into_quiet_hours_loses_it(self):
        session = Session([make_item(due_date=TOMORROW)], PREVIEW)
        assert session.tick(at(20), focus_active=True).preview is None
        assert session.tick(at(22, 5)).preview is None
        assert session.tick(at(7, 0, TOMORROW)).preview is None
