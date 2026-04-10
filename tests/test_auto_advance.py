"""Tests for auto-advancing overdue recurring items."""

from __future__ import annotations

from datetime import date, time, timedelta
from pathlib import Path

from pytodo_qt.core.models import (
    Database,
    TodoItem,
    advance_all_overdue_recurring,
    advance_overdue_recurring,
    create_todo_item,
    create_todo_list,
    cycle_completed_recurring,
    format_recurrence,
)


class _MockDate(date):
    """Date subclass that overrides today()."""

    _today: date

    @classmethod
    def today(cls) -> date:
        return cls._today


class TestAdvanceOverdueRecurring:
    """Pure model tests for advance_overdue_recurring()."""

    def test_not_recurring_unchanged(self):
        """Non-recurring items are not advanced."""
        item = create_todo_item("Task")
        item.due_date = date.today() - timedelta(days=1)
        assert not advance_overdue_recurring(item)
        assert item.missed_recurrences == 0

    def test_completed_unchanged(self):
        """Completed recurring items are not advanced."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)
        item.complete = True
        assert not advance_overdue_recurring(item)

    def test_no_due_date_unchanged(self):
        """Recurring items without due_date are not advanced."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        assert item.due_date is None
        assert not advance_overdue_recurring(item)

    def test_not_overdue_unchanged(self):
        """Recurring items due tomorrow are not advanced."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() + timedelta(days=1)
        assert not advance_overdue_recurring(item)
        assert item.missed_recurrences == 0

    def test_exhausted_by_count_unchanged(self):
        """Items at count limit are not advanced."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)
        item.recurrence_end_count = 5
        item.recurrence_count = 5
        assert not advance_overdue_recurring(item)

    def test_overdue_daily_advances(self):
        """Overdue daily item gets advanced to next valid date."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        item.due_date = date.today() - timedelta(days=3)
        old_date = item.due_date

        assert advance_overdue_recurring(item)
        assert item.due_date > old_date
        assert item.due_date >= date.today()
        assert item.missed_recurrences == 1
        assert not item.complete

    def test_overdue_weekly_advances(self):
        """Overdue weekly item advances preserving weekday."""
        item = create_todo_item("Task")
        item.recurrence_type = "weekly"
        item.recurrence_interval = 1
        item.due_date = date.today() - timedelta(days=14)
        original_weekday = item.due_date.weekday()

        assert advance_overdue_recurring(item)
        assert item.due_date >= date.today()
        assert item.due_date.weekday() == original_weekday

    def test_overdue_monthly_advances(self):
        """Overdue monthly item advances."""
        item = create_todo_item("Task")
        item.recurrence_type = "monthly"
        item.recurrence_interval = 1
        item.due_date = date.today() - timedelta(days=45)

        assert advance_overdue_recurring(item)
        assert item.due_date >= date.today()

    def test_missed_count_incremented(self):
        """missed_recurrences goes from 0 to 1."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)
        assert item.missed_recurrences == 0

        advance_overdue_recurring(item)
        assert item.missed_recurrences == 1

    def test_missed_count_cumulative(self):
        """missed_recurrences accumulates from existing count."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)
        item.missed_recurrences = 3

        advance_overdue_recurring(item)
        assert item.missed_recurrences == 4

    def test_recurrence_count_not_incremented(self):
        """recurrence_count (completions) must NOT change."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)
        item.recurrence_count = 5

        advance_overdue_recurring(item)
        assert item.recurrence_count == 5

    def test_mark_updated_called(self):
        """updated_at timestamp changes after advance."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)
        old_updated = item.updated_at

        # Ensure enough time difference
        import time as _time_mod

        _time_mod.sleep(0.002)
        advance_overdue_recurring(item)
        assert item.updated_at >= old_updated

    def test_exhausted_by_end_date_marks_complete(self):
        """If next_due exceeds end_date, item becomes complete with a timestamp."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)
        # End date is yesterday — next_due (tomorrow) will exceed it
        item.recurrence_end_date = date.today() - timedelta(days=1)
        assert item.completed_at is None

        assert advance_overdue_recurring(item)
        assert item.complete
        assert item.missed_recurrences == 1
        # Auto-completion writes a real completion timestamp.
        assert item.completed_at is not None
        assert item.completed_at > 0

    def test_due_time_preserved_daily(self):
        """due_time is preserved after daily advance (only date changes)."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)
        item.due_time = time(14, 30)

        advance_overdue_recurring(item)
        assert item.due_time == time(14, 30)

    def test_idempotent_after_advance(self):
        """After advancing, calling again returns False (no longer overdue)."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)

        assert advance_overdue_recurring(item)
        assert not advance_overdue_recurring(item)

    def test_minutely_updates_due_time(self, monkeypatch):
        """Minutely advance must update both due_date and due_time."""
        from datetime import datetime as real_datetime

        now = real_datetime(2026, 3, 23, 14, 0, 0)
        monkeypatch.setattr(
            "pytodo_qt.core.models.datetime",
            type("DT", (real_datetime,), {"now": classmethod(lambda cls: now)}),
        )

        item = create_todo_item("Task")
        item.recurrence_type = "minutely"
        item.recurrence_interval = 25
        item.due_date = date(2026, 3, 23)
        item.due_time = time(13, 0)  # 1 hour ago

        assert advance_overdue_recurring(item)
        # Should jump to next future occurrence, not stay at 13:00
        assert item.due_time is not None
        assert item.due_time > time(14, 0)  # Must be after "now"
        assert item.due_date == date(2026, 3, 23)

    def test_minutely_missed_count_correct(self, monkeypatch):
        """Minutely advance counts all missed intervals, not just 1."""
        from datetime import datetime as real_datetime

        now = real_datetime(2026, 3, 23, 15, 0, 0)
        monkeypatch.setattr(
            "pytodo_qt.core.models.datetime",
            type("DT", (real_datetime,), {"now": classmethod(lambda cls: now)}),
        )

        item = create_todo_item("Task")
        item.recurrence_type = "minutely"
        item.recurrence_interval = 25
        item.due_date = date(2026, 3, 23)
        item.due_time = time(13, 0)  # 2 hours = 120 min ago → 4 missed (25, 50, 75, 100)
        item.missed_recurrences = 0

        assert advance_overdue_recurring(item)
        # 120 min / 25 min = 4.8 → 4 missed intervals
        assert item.missed_recurrences == 4

    def test_minutely_idempotent_after_advance(self, monkeypatch):
        """After minutely advance, calling again returns False."""
        from datetime import datetime as real_datetime

        fake_today = date(2026, 3, 23)
        now = real_datetime(2026, 3, 23, 14, 30, 0)
        monkeypatch.setattr(
            "pytodo_qt.core.models.datetime",
            type("DT", (real_datetime,), {"now": classmethod(lambda cls: now)}),
        )
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: fake_today)}),
        )

        item = create_todo_item("Task")
        item.recurrence_type = "minutely"
        item.recurrence_interval = 25
        item.due_date = date(2026, 3, 23)
        item.due_time = time(14, 0)

        assert advance_overdue_recurring(item)
        assert not advance_overdue_recurring(item)

    def test_minutely_hourly_missed_count(self, monkeypatch):
        """Hourly (60-min) recurring after 3 hours = 3 missed, not 57."""
        from datetime import datetime as real_datetime

        now = real_datetime(2026, 3, 23, 21, 42, 0)
        monkeypatch.setattr(
            "pytodo_qt.core.models.datetime",
            type("DT", (real_datetime,), {"now": classmethod(lambda cls: now)}),
        )

        item = create_todo_item("Task")
        item.recurrence_type = "minutely"
        item.recurrence_interval = 60
        item.due_date = date(2026, 3, 23)
        item.due_time = time(18, 42)  # 3 hours ago

        assert advance_overdue_recurring(item)
        assert item.missed_recurrences == 3
        # Next due should be in the future, same day
        assert item.due_date == date(2026, 3, 23)
        assert item.due_time is not None
        assert item.due_time > time(21, 42)


class TestAdvanceAllOverdueRecurring:
    """Database-level scan tests."""

    def test_empty_db_returns_zero(self):
        """Empty database returns 0."""
        db = Database()
        assert advance_all_overdue_recurring(db) == 0

    def test_mixed_items_advances_only_overdue_recurring(self):
        """Only overdue recurring items are advanced."""
        db = Database()
        lst = create_todo_list("Test")

        # Normal item (not recurring) — should NOT advance
        normal = create_todo_item("Normal")
        normal.due_date = date.today() - timedelta(days=1)
        lst.add_item(normal)

        # Recurring but not overdue — should NOT advance
        future = create_todo_item("Future")
        future.recurrence_type = "daily"
        future.due_date = date.today() + timedelta(days=1)
        lst.add_item(future)

        # Overdue recurring — SHOULD advance
        overdue = create_todo_item("Overdue")
        overdue.recurrence_type = "daily"
        overdue.due_date = date.today() - timedelta(days=2)
        lst.add_item(overdue)

        db.add_list(lst)
        assert advance_all_overdue_recurring(db) == 1
        assert overdue.missed_recurrences == 1
        assert normal.missed_recurrences == 0
        assert future.missed_recurrences == 0

    def test_advances_across_multiple_lists(self):
        """Items in different lists all get advanced."""
        db = Database()

        lst1 = create_todo_list("List 1")
        item1 = create_todo_item("A")
        item1.recurrence_type = "daily"
        item1.due_date = date.today() - timedelta(days=1)
        lst1.add_item(item1)
        db.add_list(lst1)

        lst2 = create_todo_list("List 2")
        item2 = create_todo_item("B")
        item2.recurrence_type = "weekly"
        item2.due_date = date.today() - timedelta(days=10)
        lst2.add_item(item2)
        db.add_list(lst2)

        assert advance_all_overdue_recurring(db) == 2

    def test_deleted_items_skipped(self):
        """Deleted recurring overdue items are ignored."""
        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Deleted")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)
        item.mark_deleted()
        lst.add_item(item)
        db.add_list(lst)

        assert advance_all_overdue_recurring(db) == 0

    def test_deleted_lists_skipped(self):
        """Items in deleted lists are ignored."""
        db = Database()
        lst = create_todo_list("Deleted List")
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.due_date = date.today() - timedelta(days=1)
        lst.add_item(item)
        lst.mark_deleted()
        db.add_list(lst)

        assert advance_all_overdue_recurring(db) == 0


class TestMissedRecurrencesSerialization:
    """Serialization and persistence tests."""

    def test_to_dict_includes_field(self):
        """missed_recurrences appears in dict."""
        item = create_todo_item("Task")
        item.missed_recurrences = 3
        d = item.to_dict()
        assert d["missed_recurrences"] == 3

    def test_from_dict_reads_field(self):
        """Field loaded correctly from dict."""
        item = create_todo_item("Task")
        item.missed_recurrences = 5
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.missed_recurrences == 5

    def test_from_dict_defaults_to_zero(self):
        """Old data without field defaults to 0."""
        d = create_todo_item("Task").to_dict()
        del d["missed_recurrences"]
        restored = TodoItem.from_dict(d)
        assert restored.missed_recurrences == 0

    def test_schema_migration_v15(self, tmp_path: Path):
        """Database migration adds column with default 0."""
        from pytodo_qt.core.database import SCHEMA_VERSION, DatabaseStorage

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()
        assert storage.get_schema_version() == SCHEMA_VERSION

        # Verify column exists
        cursor = storage.connection.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "missed_recurrences" in columns
        storage.close()

    def test_sqlite_save_load_roundtrip(self, tmp_path: Path):
        """SQLite save and load preserves missed_recurrences."""
        from pytodo_qt.core.database import DatabaseStorage

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()

        lst = create_todo_list("Test")
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.missed_recurrences = 7
        lst.add_item(item)

        db = Database()
        db.add_list(lst)
        storage.save_database(db)

        loaded = storage.load_database()
        loaded_list = next(iter(loaded.lists.values()))
        loaded_item = next(iter(loaded_list.items.values()))
        assert loaded_item.missed_recurrences == 7
        storage.close()


class TestMissedRecurrencesDisplay:
    """Display formatting tests."""

    def test_format_recurrence_with_missed(self):
        """format_recurrence shows missed count."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.missed_recurrences = 2
        text = format_recurrence(item)
        assert "(2 missed)" in text

    def test_format_recurrence_without_missed(self):
        """format_recurrence doesn't show missed when 0."""
        item = create_todo_item("Task")
        item.recurrence_type = "daily"
        item.missed_recurrences = 0
        text = format_recurrence(item)
        assert "missed" not in text


class TestCycleCompletedRecurring:
    """Tests for cycle_completed_recurring() — cycling completed items at next due date."""

    def test_completed_daily_stays_complete_same_day(self, monkeypatch):
        """A daily item completed today should NOT cycle until tomorrow."""
        today = date(2026, 3, 18)
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: today)}),
        )

        lst = create_todo_list("Tasks")
        item = create_todo_item("Take meds", due_date=today)
        item.recurrence_type = "daily"
        item.complete = True
        item.recurrence_count = 1
        lst.add_item(item)

        result = cycle_completed_recurring(item, lst)
        assert result is False
        assert item.complete is True  # Still complete

    def test_completed_daily_cycles_next_day(self, monkeypatch):
        """A daily item completed yesterday should cycle when tomorrow arrives."""
        yesterday = date(2026, 3, 17)
        today = date(2026, 3, 18)
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: today)}),
        )

        lst = create_todo_list("Tasks")
        item = create_todo_item("Take meds", due_date=yesterday)
        item.recurrence_type = "daily"
        item.complete = True
        item.recurrence_count = 1
        lst.add_item(item)

        result = cycle_completed_recurring(item, lst)
        assert result is True
        assert item.complete is False
        assert item.due_date >= today

    def test_cycle_clears_completed_at(self, monkeypatch):
        """A cycled recurring item starts a fresh cycle: completed_at must be None."""
        yesterday = date(2026, 3, 17)
        today = date(2026, 3, 18)
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: today)}),
        )

        lst = create_todo_list("Tasks")
        item = create_todo_item("Take meds", due_date=yesterday)
        item.recurrence_type = "daily"
        item.complete = True
        item.completed_at = 1_700_000_000_000  # Previous cycle's timestamp
        item.recurrence_count = 1
        lst.add_item(item)

        cycle_completed_recurring(item, lst)
        # New cycle is a fresh instance — no completion timestamp.
        assert item.complete is False
        assert item.completed_at is None

    def test_cycle_clears_subtask_completed_at(self, monkeypatch):
        """Cycling resets each non-recurring subtask's completed_at to None."""
        yesterday = date(2026, 3, 17)
        today = date(2026, 3, 18)
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: today)}),
        )

        lst = create_todo_list("Tasks")
        parent = create_todo_item("Take meds", due_date=yesterday)
        parent.recurrence_type = "daily"
        parent.complete = True
        parent.completed_at = 1_700_000_000_000
        parent.recurrence_count = 1
        lst.add_item(parent)

        sub = create_todo_item("Morning dose")
        sub.parent_id = parent.id
        sub.complete = True
        sub.completed_at = 1_700_000_000_500
        lst.add_item(sub)

        cycle_completed_recurring(parent, lst)
        assert sub.complete is False
        assert sub.completed_at is None

    def test_cycle_resets_subtask_completions(self, monkeypatch):
        """Cycling a parent resets all non-recurring subtask completions."""
        yesterday = date(2026, 3, 17)
        today = date(2026, 3, 18)
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: today)}),
        )

        lst = create_todo_list("Tasks")
        parent = create_todo_item("Take meds", due_date=yesterday)
        parent.recurrence_type = "daily"
        parent.complete = True
        parent.recurrence_count = 1
        lst.add_item(parent)

        sub1 = create_todo_item("Morning dose")
        sub1.parent_id = parent.id
        sub1.complete = True
        lst.add_item(sub1)

        sub2 = create_todo_item("Evening dose")
        sub2.parent_id = parent.id
        sub2.complete = True
        lst.add_item(sub2)

        result = cycle_completed_recurring(parent, lst)
        assert result is True
        assert sub1.complete is False
        assert sub2.complete is False

    def test_cycle_preserves_independently_recurring_subtasks(self, monkeypatch):
        """Subtasks with their own recurrence are NOT reset by parent cycling."""
        yesterday = date(2026, 3, 17)
        today = date(2026, 3, 18)
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: today)}),
        )

        lst = create_todo_list("Tasks")
        parent = create_todo_item("Take meds", due_date=yesterday)
        parent.recurrence_type = "daily"
        parent.complete = True
        parent.recurrence_count = 1
        lst.add_item(parent)

        sub = create_todo_item("Morning dose", due_date=yesterday)
        sub.parent_id = parent.id
        sub.recurrence_type = "daily"  # Has its own recurrence
        sub.complete = True
        lst.add_item(sub)

        cycle_completed_recurring(parent, lst)
        # Independently recurring subtask keeps its state
        assert sub.complete is True

    def test_cycle_resets_board_column_to_inbox(self, monkeypatch):
        """Cycled item moves from Done back to first column."""
        yesterday = date(2026, 3, 17)
        today = date(2026, 3, 18)
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: today)}),
        )

        lst = create_todo_list("Tasks")
        item = create_todo_item("Daily standup", due_date=yesterday)
        item.recurrence_type = "daily"
        item.complete = True
        item.board_column = "Done"  # In completion column
        lst.add_item(item)

        cycle_completed_recurring(item, lst)
        assert item.board_column == "To Do"

    def test_cycle_resets_to_in_progress_with_work_history(self, monkeypatch):
        """Cycled item with pomodoro time goes to In Progress, not To Do."""
        yesterday = date(2026, 3, 17)
        today = date(2026, 3, 18)
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: today)}),
        )

        lst = create_todo_list("Tasks")
        item = create_todo_item("Focus work", due_date=yesterday)
        item.recurrence_type = "daily"
        item.complete = True
        item.time_spent = 1500  # Has pomodoro history
        item.board_column = "Done"
        lst.add_item(item)

        cycle_completed_recurring(item, lst)
        assert item.board_column == "In Progress"

    def test_exhausted_recurrence_does_not_cycle(self, monkeypatch):
        """Exhausted recurring items stay complete permanently."""
        yesterday = date(2026, 3, 17)
        today = date(2026, 3, 18)
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: today)}),
        )

        lst = create_todo_list("Tasks")
        item = create_todo_item("Limited task", due_date=yesterday)
        item.recurrence_type = "daily"
        item.complete = True
        item.recurrence_count = 5
        item.recurrence_end_count = 5  # Exhausted
        lst.add_item(item)

        result = cycle_completed_recurring(item, lst)
        assert result is False
        assert item.complete is True

    def test_advance_all_includes_cycle(self, monkeypatch):
        """advance_all_overdue_recurring also cycles completed recurring items."""
        yesterday = date(2026, 3, 17)
        today = date(2026, 3, 18)
        monkeypatch.setattr(
            "pytodo_qt.core.models.date",
            type("D", (date,), {"today": classmethod(lambda cls: today)}),
        )

        db = Database()
        lst = create_todo_list("Tasks")
        item = create_todo_item("Daily task", due_date=yesterday)
        item.recurrence_type = "daily"
        item.complete = True
        item.recurrence_count = 1
        lst.add_item(item)
        db.add_list(lst)

        count = advance_all_overdue_recurring(db)
        assert count == 1
        assert item.complete is False
