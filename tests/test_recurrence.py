"""Comprehensive tests for recurring tasks feature.

Tests cover: model fields, serialization, date computation, end conditions,
undo/redo commands, schema migration, and filter integration.
"""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from pytodo_qt.core.database import DatabaseStorage
from pytodo_qt.core.models import (
    Database,
    TodoItem,
    compute_next_due_date,
    create_todo_item,
    create_todo_list,
    format_recurrence,
    is_recurrence_ended,
)
from pytodo_qt.gui.commands import (
    EditRecurrenceCommand,
    ToggleCompleteRecurringCommand,
)


# ---------------------------------------------------------------------------
# Helpers (mirror test_commands.py pattern)
# ---------------------------------------------------------------------------
class FakeConfigManager:
    def save(self):
        pass


class FakeConfig:
    class database:
        active_list = ""


def make_window(db: Database | None = None) -> MagicMock:
    window = MagicMock()
    window._database = db or Database()
    window._save_database = MagicMock()
    window._refresh_ui = MagicMock()
    window._config = FakeConfig()
    window._config_manager = FakeConfigManager()
    window.status_bar_widget = MagicMock()
    return window


def make_recurring_item(
    reminder: str = "Buy groceries",
    due_date: date | None = None,
    recurrence_type: str = "weekly",
    recurrence_interval: int = 1,
    recurrence_end_date: date | None = None,
    recurrence_end_count: int | None = None,
    recurrence_count: int = 0,
) -> TodoItem:
    item = create_todo_item(
        reminder=reminder,
        due_date=due_date or date.today(),
        recurrence_type=recurrence_type,
        recurrence_interval=recurrence_interval,
        recurrence_end_date=recurrence_end_date,
        recurrence_end_count=recurrence_end_count,
    )
    item.recurrence_count = recurrence_count
    return item


# ---------------------------------------------------------------------------
# Model field tests
# ---------------------------------------------------------------------------
class TestRecurrenceModelFields:
    def test_default_not_recurring(self):
        item = create_todo_item("Simple task")
        assert item.is_recurring is False
        assert item.recurrence_type is None
        assert item.recurrence_interval == 1
        assert item.recurrence_end_date is None
        assert item.recurrence_end_count is None
        assert item.recurrence_count == 0

    def test_recurring_item(self):
        item = make_recurring_item(recurrence_type="daily")
        assert item.is_recurring is True
        assert item.recurrence_type == "daily"

    def test_all_recurrence_types(self):
        for rtype in ("daily", "weekly", "monthly", "yearly"):
            item = make_recurring_item(recurrence_type=rtype)
            assert item.is_recurring is True
            assert item.recurrence_type == rtype

    def test_custom_interval(self):
        item = make_recurring_item(recurrence_interval=3)
        assert item.recurrence_interval == 3

    def test_end_date(self):
        end = date(2026, 12, 31)
        item = make_recurring_item(recurrence_end_date=end)
        assert item.recurrence_end_date == end

    def test_end_count(self):
        item = make_recurring_item(recurrence_end_count=5)
        assert item.recurrence_end_count == 5


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------
class TestRecurrenceSerialization:
    def test_to_dict_includes_recurrence(self):
        item = make_recurring_item(
            recurrence_type="monthly",
            recurrence_interval=2,
            recurrence_end_date=date(2026, 6, 15),
            recurrence_end_count=None,
            recurrence_count=3,
        )
        d = item.to_dict()
        assert d["recurrence_type"] == "monthly"
        assert d["recurrence_interval"] == 2
        assert d["recurrence_end_date"] == "2026-06-15"
        assert d["recurrence_end_count"] is None
        assert d["recurrence_count"] == 3

    def test_round_trip(self):
        item = make_recurring_item(
            recurrence_type="weekly",
            recurrence_interval=2,
            recurrence_end_count=10,
            recurrence_count=4,
        )
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.recurrence_type == "weekly"
        assert restored.recurrence_interval == 2
        assert restored.recurrence_end_count == 10
        assert restored.recurrence_count == 4
        assert restored.recurrence_end_date is None

    def test_round_trip_with_end_date(self):
        end = date(2027, 1, 1)
        item = make_recurring_item(recurrence_end_date=end)
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.recurrence_end_date == end

    def test_backward_compat_missing_fields(self):
        """Data from older peers without recurrence fields."""
        d = {
            "id": str(uuid4()),
            "reminder": "Old item",
            "priority": 2,
            "complete": False,
            "due_date": None,
            "created_at": 1000,
            "updated_at": 2000,
            "deleted": False,
        }
        item = TodoItem.from_dict(d)
        assert item.is_recurring is False
        assert item.recurrence_type is None
        assert item.recurrence_interval == 1
        assert item.recurrence_count == 0

    def test_non_recurring_to_dict(self):
        item = create_todo_item("Plain task")
        d = item.to_dict()
        assert d["recurrence_type"] is None
        assert d["recurrence_interval"] == 1
        assert d["recurrence_end_date"] is None
        assert d["recurrence_end_count"] is None
        assert d["recurrence_count"] == 0


# ---------------------------------------------------------------------------
# compute_next_due_date
# ---------------------------------------------------------------------------
class TestComputeNextDueDate:
    def test_daily(self):
        today = date.today()
        result = compute_next_due_date(today, "daily", 1)
        assert result == today + timedelta(days=1)

    def test_daily_interval(self):
        today = date.today()
        result = compute_next_due_date(today, "daily", 3)
        assert result == today + timedelta(days=3)

    def test_weekly_preserves_weekday(self):
        # Use a known Monday
        monday = date(2026, 3, 2)
        result = compute_next_due_date(monday, "weekly", 1)
        assert result.weekday() == 0  # Monday

    def test_weekly_interval_2(self):
        monday = date(2026, 3, 2)
        result = compute_next_due_date(monday, "weekly", 2)
        assert result.weekday() == 0  # Monday
        assert result >= date.today() + timedelta(days=7)

    def test_monthly(self):
        today = date.today()
        due = date(today.year, today.month, 15)
        result = compute_next_due_date(due, "monthly", 1)
        assert result.day == 15
        assert result > today

    def test_monthly_end_of_month_clamping(self):
        """Day 31 monthly should clamp to shorter months."""
        import calendar

        due = date(2026, 1, 31)  # day=31
        result = compute_next_due_date(due, "monthly", 1)
        # Result month's max day should be respected
        max_day = calendar.monthrange(result.year, result.month)[1]
        assert result.day == min(31, max_day)

    def test_yearly(self):
        today = date.today()
        due = date(today.year, 6, 15)
        result = compute_next_due_date(due, "yearly", 1)
        assert result.month == 6
        assert result.day == 15
        assert result.year >= today.year + 1

    def test_yearly_feb_29_non_leap(self):
        """Feb 29 yearly on non-leap year → Feb 28."""
        due = date(2024, 2, 29)  # 2024 is leap
        result = compute_next_due_date(due, "yearly", 1)
        # target year might not be leap
        if result.month == 2 and result.day == 28:
            pass  # Expected fallback
        else:
            assert result.month == 2 and result.day == 29  # Still leap year

    def test_unknown_type_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Unknown recurrence type"):
            compute_next_due_date(date.today(), "biweekly", 1)


# ---------------------------------------------------------------------------
# is_recurrence_ended
# ---------------------------------------------------------------------------
class TestIsRecurrenceEnded:
    def test_not_recurring(self):
        item = create_todo_item("Plain")
        assert is_recurrence_ended(item) is True

    def test_no_end_condition(self):
        item = make_recurring_item()
        assert is_recurrence_ended(item) is False

    def test_end_by_count_not_reached(self):
        item = make_recurring_item(recurrence_end_count=5, recurrence_count=2)
        assert is_recurrence_ended(item) is False

    def test_end_by_count_reached(self):
        item = make_recurring_item(recurrence_end_count=5, recurrence_count=4)
        # count + 1 >= end_count → 4 + 1 >= 5 → True
        assert is_recurrence_ended(item) is True

    def test_end_by_date_not_reached(self):
        future = date.today() + timedelta(days=365)
        item = make_recurring_item(recurrence_end_date=future)
        next_due = date.today() + timedelta(days=7)
        assert is_recurrence_ended(item, next_due) is False

    def test_end_by_date_reached(self):
        past = date.today() - timedelta(days=1)
        item = make_recurring_item(recurrence_end_date=past)
        next_due = date.today() + timedelta(days=7)
        assert is_recurrence_ended(item, next_due) is True

    def test_end_date_without_next_due(self):
        past = date.today() - timedelta(days=1)
        item = make_recurring_item(recurrence_end_date=past)
        # Without next_due, date check can't fire
        assert is_recurrence_ended(item, None) is False


# ---------------------------------------------------------------------------
# format_recurrence
# ---------------------------------------------------------------------------
class TestFormatRecurrence:
    def test_not_recurring(self):
        item = create_todo_item("Plain")
        assert format_recurrence(item) == ""

    def test_daily(self):
        item = make_recurring_item(recurrence_type="daily")
        assert format_recurrence(item) == "Every day"

    def test_weekly(self):
        item = make_recurring_item(recurrence_type="weekly")
        assert format_recurrence(item) == "Every week"

    def test_monthly(self):
        item = make_recurring_item(recurrence_type="monthly")
        assert format_recurrence(item) == "Every month"

    def test_yearly(self):
        item = make_recurring_item(recurrence_type="yearly")
        assert format_recurrence(item) == "Every year"

    def test_custom_interval(self):
        item = make_recurring_item(recurrence_type="weekly", recurrence_interval=2)
        assert format_recurrence(item) == "Every 2 weeks"

    def test_with_end_count(self):
        item = make_recurring_item(recurrence_end_count=10, recurrence_count=3)
        result = format_recurrence(item)
        assert "3/10 completed" in result

    def test_with_end_date(self):
        end = date(2026, 12, 31)
        item = make_recurring_item(recurrence_end_date=end)
        result = format_recurrence(item)
        assert "until" in result
        assert "Dec 31, 2026" in result


# ---------------------------------------------------------------------------
# ToggleCompleteRecurringCommand
# ---------------------------------------------------------------------------
class TestToggleCompleteRecurringCommand:
    def test_redo_advances_due_date(self):
        db = Database()
        lst = create_todo_list("Test")
        item = make_recurring_item(due_date=date.today())
        lst.add_item(item)
        db.add_list(lst)
        window = make_window(db)

        next_due = date.today() + timedelta(days=7)
        cmd = ToggleCompleteRecurringCommand(
            window,
            lst.id,
            item.id,
            old_due_date=item.due_date,
            new_due_date=next_due,
            old_count=0,
            recurrence_ended=False,
        )
        cmd.redo()

        assert item.complete is False
        assert item.due_date == next_due
        assert item.recurrence_count == 1
        window._save_database.assert_called()

    def test_redo_ends_recurrence(self):
        db = Database()
        lst = create_todo_list("Test")
        item = make_recurring_item(recurrence_end_count=1, recurrence_count=0)
        lst.add_item(item)
        db.add_list(lst)
        window = make_window(db)

        cmd = ToggleCompleteRecurringCommand(
            window,
            lst.id,
            item.id,
            old_due_date=item.due_date,
            new_due_date=None,
            old_count=0,
            recurrence_ended=True,
        )
        cmd.redo()

        assert item.complete is True
        assert item.recurrence_count == 1

    def test_undo_restores_state(self):
        db = Database()
        lst = create_todo_list("Test")
        original_due = date.today()
        item = make_recurring_item(due_date=original_due)
        lst.add_item(item)
        db.add_list(lst)
        window = make_window(db)

        next_due = date.today() + timedelta(days=7)
        cmd = ToggleCompleteRecurringCommand(
            window,
            lst.id,
            item.id,
            old_due_date=original_due,
            new_due_date=next_due,
            old_count=0,
            recurrence_ended=False,
        )
        cmd.redo()
        assert item.due_date == next_due
        assert item.recurrence_count == 1

        cmd.undo()
        assert item.complete is False
        assert item.due_date == original_due
        assert item.recurrence_count == 0

    def test_redo_undo_redo_consistent(self):
        db = Database()
        lst = create_todo_list("Test")
        original_due = date.today()
        item = make_recurring_item(due_date=original_due)
        lst.add_item(item)
        db.add_list(lst)
        window = make_window(db)

        next_due = date.today() + timedelta(days=7)
        cmd = ToggleCompleteRecurringCommand(
            window,
            lst.id,
            item.id,
            old_due_date=original_due,
            new_due_date=next_due,
            old_count=0,
            recurrence_ended=False,
        )
        cmd.redo()
        cmd.undo()
        cmd.redo()

        assert item.due_date == next_due
        assert item.recurrence_count == 1

    def test_noop_missing_list(self):
        db = Database()
        window = make_window(db)
        cmd = ToggleCompleteRecurringCommand(
            window,
            uuid4(),
            uuid4(),
            old_due_date=date.today(),
            new_due_date=date.today() + timedelta(days=1),
            old_count=0,
            recurrence_ended=False,
        )
        cmd.redo()  # Should not raise
        cmd.undo()  # Should not raise

    def test_noop_missing_item(self):
        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)
        window = make_window(db)
        cmd = ToggleCompleteRecurringCommand(
            window,
            lst.id,
            uuid4(),
            old_due_date=date.today(),
            new_due_date=date.today() + timedelta(days=1),
            old_count=0,
            recurrence_ended=False,
        )
        cmd.redo()  # Should not raise
        cmd.undo()  # Should not raise


# ---------------------------------------------------------------------------
# EditRecurrenceCommand
# ---------------------------------------------------------------------------
class TestEditRecurrenceCommand:
    def test_redo_sets_recurrence(self):
        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", due_date=date.today())
        lst.add_item(item)
        db.add_list(lst)
        window = make_window(db)

        old = (None, 1, None, None)
        new = ("weekly", 2, None, None)
        cmd = EditRecurrenceCommand(window, lst.id, item.id, old, new)
        cmd.redo()

        assert item.recurrence_type == "weekly"
        assert item.recurrence_interval == 2

    def test_undo_restores_recurrence(self):
        db = Database()
        lst = create_todo_list("Test")
        item = make_recurring_item(recurrence_type="daily", recurrence_interval=1)
        lst.add_item(item)
        db.add_list(lst)
        window = make_window(db)

        old = ("daily", 1, None, None)
        new = ("weekly", 2, date(2026, 12, 31), None)
        cmd = EditRecurrenceCommand(window, lst.id, item.id, old, new)
        cmd.redo()
        assert item.recurrence_type == "weekly"
        assert item.recurrence_end_date == date(2026, 12, 31)

        cmd.undo()
        assert item.recurrence_type == "daily"
        assert item.recurrence_interval == 1
        assert item.recurrence_end_date is None

    def test_remove_recurrence(self):
        db = Database()
        lst = create_todo_list("Test")
        item = make_recurring_item()
        lst.add_item(item)
        db.add_list(lst)
        window = make_window(db)

        old = (item.recurrence_type, item.recurrence_interval, None, None)
        new = (None, 1, None, None)
        cmd = EditRecurrenceCommand(window, lst.id, item.id, old, new)
        cmd.redo()

        assert item.is_recurring is False
        assert item.recurrence_type is None

    def test_noop_missing_item(self):
        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)
        window = make_window(db)
        cmd = EditRecurrenceCommand(
            window,
            lst.id,
            uuid4(),
            (None, 1, None, None),
            ("daily", 1, None, None),
        )
        cmd.redo()  # Should not raise
        cmd.undo()  # Should not raise


# ---------------------------------------------------------------------------
# Schema migration and DatabaseStorage round-trip
# ---------------------------------------------------------------------------
class TestRecurrenceMigration:
    def test_fresh_database_has_recurrence_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            cursor = storage.connection.execute("PRAGMA table_info(items)")
            columns = [row[1] for row in cursor.fetchall()]

            assert "recurrence_type" in columns
            assert "recurrence_interval" in columns
            assert "recurrence_end_date" in columns
            assert "recurrence_end_count" in columns
            assert "recurrence_count" in columns

            storage.close()

    def test_schema_version_is_7(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            assert storage.get_schema_version() == 15
            storage.close()

    def test_save_load_recurring_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = create_todo_list("Test")
            storage.save_list(lst)

            item = make_recurring_item(
                recurrence_type="monthly",
                recurrence_interval=2,
                recurrence_end_date=date(2027, 6, 15),
                recurrence_count=5,
            )
            storage.save_item(lst.id, item)

            loaded = storage.get_item(item.id)
            assert loaded is not None
            assert loaded.recurrence_type == "monthly"
            assert loaded.recurrence_interval == 2
            assert loaded.recurrence_end_date == date(2027, 6, 15)
            assert loaded.recurrence_end_count is None
            assert loaded.recurrence_count == 5

            storage.close()

    def test_save_load_non_recurring_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = create_todo_list("Test")
            storage.save_list(lst)

            item = create_todo_item("Plain task")
            storage.save_item(lst.id, item)

            loaded = storage.get_item(item.id)
            assert loaded is not None
            assert loaded.recurrence_type is None
            assert loaded.recurrence_interval == 1
            assert loaded.recurrence_count == 0

            storage.close()

    def test_full_database_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            db = Database()
            lst = create_todo_list("My List")
            recurring_item = make_recurring_item(
                reminder="Weekly groceries",
                recurrence_type="weekly",
                recurrence_count=3,
            )
            plain_item = create_todo_item("One-off task")
            lst.add_item(recurring_item)
            lst.add_item(plain_item)
            db.add_list(lst)
            db.set_active_list(lst.id)

            storage.save_database(db)
            loaded = storage.load_database()

            loaded_list = loaded.lists.get(lst.id)
            assert loaded_list is not None
            loaded_recurring = loaded_list.get_item(recurring_item.id)
            assert loaded_recurring is not None
            assert loaded_recurring.is_recurring is True
            assert loaded_recurring.recurrence_type == "weekly"
            assert loaded_recurring.recurrence_count == 3

            loaded_plain = loaded_list.get_item(plain_item.id)
            assert loaded_plain is not None
            assert loaded_plain.is_recurring is False

            storage.close()


# ---------------------------------------------------------------------------
# Filter integration
# ---------------------------------------------------------------------------
class TestRecurringFilter:
    def test_filter_recurring_only(self):
        items = [
            create_todo_item("Plain 1"),
            make_recurring_item(reminder="Recurring 1"),
            create_todo_item("Plain 2"),
            make_recurring_item(reminder="Recurring 2"),
        ]
        filtered = [i for i in items if i.is_recurring]
        assert len(filtered) == 2
        assert all(i.is_recurring for i in filtered)

    def test_filter_non_recurring(self):
        items = [
            create_todo_item("Plain 1"),
            make_recurring_item(reminder="Recurring 1"),
        ]
        filtered = [i for i in items if not i.is_recurring]
        assert len(filtered) == 1
        assert filtered[0].reminder == "Plain 1"
