"""Comprehensive tests for due times feature.

Tests cover: model field, serialization, format display, overdue granularity,
is_overdue time-awareness, database schema v8, commands, config, sort order,
and recurrence preservation.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch

from pytodo_qt.core.config import AppConfig, AppearanceConfig
from pytodo_qt.core.models import (
    Database,
    TodoItem,
    _format_overdue_delta,
    _format_time,
    create_todo_item,
    create_todo_list,
    format_due_date,
    is_overdue,
)
from pytodo_qt.gui.commands import EditDueDateCommand, EditDueTimeCommand
from pytodo_qt.gui.widgets.time_combo import TimeComboBox, parse_time_text


# ---------------------------------------------------------------------------
# Helpers
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


def _mock_date(fake_today: date):
    """Create a date subclass whose today() returns fake_today."""

    class MockDate(date):
        @classmethod
        def today(cls) -> date:
            return fake_today

    return MockDate


def _mock_datetime(fake_now: datetime):
    """Create a datetime subclass whose now() returns fake_now."""

    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None) -> datetime:  # noqa: ARG003
            return fake_now

    return MockDatetime


# ---------------------------------------------------------------------------
# Model field tests
# ---------------------------------------------------------------------------
class TestDueTimeField:
    def test_default_none(self):
        item = TodoItem()
        assert item.due_time is None

    def test_set_time(self):
        item = TodoItem(due_time=time(14, 30))
        assert item.due_time == time(14, 30)

    def test_time_with_date(self):
        item = TodoItem(due_date=date(2026, 3, 15), due_time=time(9, 0))
        assert item.due_date == date(2026, 3, 15)
        assert item.due_time == time(9, 0)

    def test_time_without_date(self):
        item = TodoItem(due_time=time(10, 0))
        assert item.due_date is None
        assert item.due_time == time(10, 0)


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------
class TestDueTimeSerialization:
    def test_to_dict_with_time(self):
        item = TodoItem(due_date=date(2026, 3, 15), due_time=time(14, 30))
        d = item.to_dict()
        assert d["due_time"] == "14:30:00"
        assert d["due_date"] == "2026-03-15"

    def test_to_dict_without_time(self):
        item = TodoItem(due_date=date(2026, 3, 15))
        d = item.to_dict()
        assert d["due_time"] is None

    def test_from_dict_with_time(self):
        d = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "due_date": "2026-03-15",
            "due_time": "14:30:00",
        }
        item = TodoItem.from_dict(d)
        assert item.due_time == time(14, 30)
        assert item.due_date == date(2026, 3, 15)

    def test_from_dict_without_time(self):
        d = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "due_date": "2026-03-15",
        }
        item = TodoItem.from_dict(d)
        assert item.due_time is None

    def test_from_dict_time_none(self):
        d = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "due_time": None,
        }
        item = TodoItem.from_dict(d)
        assert item.due_time is None

    def test_roundtrip(self):
        original = TodoItem(due_date=date(2026, 6, 15), due_time=time(9, 45))
        d = original.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.due_date == original.due_date
        assert restored.due_time == original.due_time

    def test_roundtrip_no_time(self):
        original = TodoItem(due_date=date(2026, 6, 15))
        d = original.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.due_time is None


# ---------------------------------------------------------------------------
# Factory function tests
# ---------------------------------------------------------------------------
class TestCreateTodoItemWithTime:
    def test_with_time(self):
        item = create_todo_item("Buy milk", due_date=date(2026, 3, 15), due_time=time(10, 0))
        assert item.due_time == time(10, 0)

    def test_without_time(self):
        item = create_todo_item("Buy milk", due_date=date(2026, 3, 15))
        assert item.due_time is None

    def test_default(self):
        item = create_todo_item("Buy milk")
        assert item.due_time is None


# ---------------------------------------------------------------------------
# _format_time tests
# ---------------------------------------------------------------------------
class TestFormatTime:
    def test_12h_am(self):
        assert _format_time(time(9, 0), "12h") == "9:00 AM"

    def test_12h_pm(self):
        assert _format_time(time(14, 30), "12h") == "2:30 PM"

    def test_12h_midnight(self):
        assert _format_time(time(0, 0), "12h") == "12:00 AM"

    def test_12h_noon(self):
        assert _format_time(time(12, 0), "12h") == "12:00 PM"

    def test_24h(self):
        assert _format_time(time(14, 30), "24h") == "14:30"

    def test_24h_midnight(self):
        assert _format_time(time(0, 0), "24h") == "00:00"

    def test_24h_single_digit(self):
        assert _format_time(time(9, 5), "24h") == "09:05"

    def test_system_format(self):
        result = _format_time(time(14, 30), "system")
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# format_due_date with time tests
# ---------------------------------------------------------------------------
class TestFormatDueDateWithTime:
    def test_today_with_time(self):
        fake_today = date(2026, 3, 15)
        fake_now = datetime(2026, 3, 15, 8, 0)
        with (
            patch("pytodo_qt.core.models.date", _mock_date(fake_today)),
            patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)),
        ):
            result = format_due_date(fake_today, due_time=time(14, 30), time_format="12h")
        assert result == "Today 2:30 PM"

    def test_tomorrow_with_time(self):
        tomorrow = date.today() + timedelta(days=1)
        result = format_due_date(tomorrow, due_time=time(9, 0), time_format="12h")
        assert result == "Tomorrow 9:00 AM"

    def test_this_week_with_time(self):
        three_days = date.today() + timedelta(days=3)
        result = format_due_date(three_days, due_time=time(15, 0), time_format="12h")
        expected = three_days.strftime("%A") + " 3:00 PM"
        assert result == expected

    def test_same_year_with_time(self):
        future = date.today() + timedelta(days=15)
        if future.year == date.today().year:
            result = format_due_date(future, due_time=time(9, 0), time_format="12h")
            expected = future.strftime("%b %d") + " 9:00 AM"
            assert result == expected

    def test_different_year_with_time(self):
        next_year = date(date.today().year + 1, 3, 15)
        result = format_due_date(next_year, due_time=time(14, 0), time_format="12h")
        expected = next_year.strftime("%b %d, %Y") + " 2:00 PM"
        assert result == expected

    def test_completed_with_time(self):
        today = date.today()
        result = format_due_date(today, complete=True, due_time=time(14, 30), time_format="12h")
        expected = today.strftime("%b %d") + " 2:30 PM"
        assert result == expected

    def test_completed_different_year_with_time(self):
        past = date(date.today().year - 1, 6, 15)
        result = format_due_date(past, complete=True, due_time=time(10, 0), time_format="24h")
        expected = past.strftime("%b %d, %Y") + " 10:00"
        assert result == expected

    def test_today_without_time(self):
        today = date.today()
        assert format_due_date(today) == "Today"

    def test_none_date(self):
        assert format_due_date(None, due_time=time(14, 0)) == ""

    def test_overdue_date_only_unchanged(self):
        yesterday = date.today() - timedelta(days=1)
        result = format_due_date(yesterday)
        assert result == "Overdue (1d)"

    def test_24h_format(self):
        fake_today = date(2026, 3, 15)
        fake_now = datetime(2026, 3, 15, 8, 0)
        with (
            patch("pytodo_qt.core.models.date", _mock_date(fake_today)),
            patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)),
        ):
            result = format_due_date(fake_today, due_time=time(14, 30), time_format="24h")
        assert result == "Today 14:30"


# ---------------------------------------------------------------------------
# Overdue with time (mocked)
# ---------------------------------------------------------------------------
class TestFormatDueDateOverdueWithTime:
    def test_today_past_time_is_overdue(self):
        fake_today = date(2026, 3, 15)
        fake_now = datetime(2026, 3, 15, 11, 30)
        with (
            patch("pytodo_qt.core.models.date", _mock_date(fake_today)),
            patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)),
        ):
            result = format_due_date(date(2026, 3, 15), due_time=time(9, 0), time_format="12h")
        assert result.startswith("Overdue")
        assert "h" in result or "m" in result

    def test_today_future_time_not_overdue(self):
        fake_today = date(2026, 3, 15)
        fake_now = datetime(2026, 3, 15, 8, 0)
        with (
            patch("pytodo_qt.core.models.date", _mock_date(fake_today)),
            patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)),
        ):
            result = format_due_date(date(2026, 3, 15), due_time=time(9, 0), time_format="12h")
        assert result == "Today 9:00 AM"


# ---------------------------------------------------------------------------
# _format_overdue_delta tests (mocked)
# ---------------------------------------------------------------------------
class TestFormatOverdueDelta:
    def test_date_only_day_level(self):
        fake_today = date(2026, 3, 15)
        fake_now = datetime(2026, 3, 15, 10, 0)
        with (
            patch("pytodo_qt.core.models.date", _mock_date(fake_today)),
            patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)),
        ):
            result = _format_overdue_delta(date(2026, 3, 13))
        assert result == "Overdue (2d)"

    def test_timed_minutes(self):
        fake_now = datetime(2026, 3, 15, 9, 23)
        with patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)):
            result = _format_overdue_delta(date(2026, 3, 15), time(9, 0))
        assert result == "Overdue (23m)"

    def test_timed_hours_minutes(self):
        fake_now = datetime(2026, 3, 15, 12, 15)
        with patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)):
            result = _format_overdue_delta(date(2026, 3, 15), time(9, 0))
        assert result == "Overdue (3h 15m)"

    def test_timed_hours_only(self):
        fake_now = datetime(2026, 3, 15, 12, 0)
        with patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)):
            result = _format_overdue_delta(date(2026, 3, 15), time(9, 0))
        assert result == "Overdue (3h)"

    def test_timed_days_hours(self):
        fake_now = datetime(2026, 3, 17, 14, 0)
        with patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)):
            result = _format_overdue_delta(date(2026, 3, 15), time(9, 0))
        assert result == "Overdue (2d 5h)"

    def test_timed_days_only(self):
        fake_now = datetime(2026, 3, 17, 9, 0)
        with patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)):
            result = _format_overdue_delta(date(2026, 3, 15), time(9, 0))
        assert result == "Overdue (2d)"

    def test_timed_1_minute(self):
        fake_now = datetime(2026, 3, 15, 9, 0, 30)
        with patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)):
            result = _format_overdue_delta(date(2026, 3, 15), time(9, 0))
        assert result == "Overdue (1m)"

    def test_not_overdue_returns_empty(self):
        fake_now = datetime(2026, 3, 15, 8, 0)
        with patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)):
            result = _format_overdue_delta(date(2026, 3, 15), time(9, 0))
        assert result == ""


# ---------------------------------------------------------------------------
# is_overdue with time tests (mocked)
# ---------------------------------------------------------------------------
class TestIsOverdueWithTime:
    def test_past_date_overdue_regardless(self):
        yesterday = date.today() - timedelta(days=1)
        assert is_overdue(yesterday, time(23, 59)) is True

    def test_future_date_not_overdue(self):
        tomorrow = date.today() + timedelta(days=1)
        assert is_overdue(tomorrow, time(0, 0)) is False

    def test_today_past_time(self):
        fake_today = date(2026, 3, 15)
        fake_now = datetime(2026, 3, 15, 11, 0)
        with (
            patch("pytodo_qt.core.models.date", _mock_date(fake_today)),
            patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)),
        ):
            assert is_overdue(date(2026, 3, 15), time(9, 0)) is True

    def test_today_future_time(self):
        fake_today = date(2026, 3, 15)
        fake_now = datetime(2026, 3, 15, 8, 0)
        with (
            patch("pytodo_qt.core.models.date", _mock_date(fake_today)),
            patch("pytodo_qt.core.models.datetime", _mock_datetime(fake_now)),
        ):
            assert is_overdue(date(2026, 3, 15), time(9, 0)) is False

    def test_today_no_time_not_overdue(self):
        today = date.today()
        assert is_overdue(today) is False

    def test_none_not_overdue(self):
        assert is_overdue(None, time(9, 0)) is False


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------
class TestTimeFormatConfig:
    def test_default(self):
        config = AppConfig()
        assert config.appearance.time_format == "system"

    def test_custom_value(self):
        config = AppConfig(appearance=AppearanceConfig(time_format="24h"))
        assert config.appearance.time_format == "24h"

    def test_to_toml_includes_time_format(self):
        config = AppConfig(appearance=AppearanceConfig(time_format="12h"))
        toml_str = config.to_toml()
        assert 'time_format = "12h"' in toml_str

    def test_from_dict_reads_time_format(self):
        data = {"appearance": {"theme": "dark", "time_format": "24h"}}
        config = AppConfig.from_dict(data)
        assert config.appearance.time_format == "24h"

    def test_from_dict_default_time_format(self):
        data = {"appearance": {"theme": "light"}}
        config = AppConfig.from_dict(data)
        assert config.appearance.time_format == "system"


# ---------------------------------------------------------------------------
# Sort order tests
# ---------------------------------------------------------------------------
class TestSortWithTime:
    def test_same_date_sorted_by_time(self):
        items = [
            TodoItem(due_date=date(2026, 3, 15), due_time=time(15, 0), reminder="Later"),
            TodoItem(due_date=date(2026, 3, 15), due_time=time(9, 0), reminder="Earlier"),
            TodoItem(due_date=date(2026, 3, 15), reminder="No time"),
        ]

        def sort_key(item):
            if item.due_date is None:
                return (1, "", "", item.priority, item.reminder.lower())
            time_key = item.due_time.isoformat() if item.due_time else ""
            return (0, item.due_date.isoformat(), time_key, item.priority, item.reminder.lower())

        sorted_items = sorted(items, key=sort_key)
        # Items without time sort before timed items (empty string < any time string)
        assert sorted_items[0].reminder == "No time"
        assert sorted_items[1].reminder == "Earlier"
        assert sorted_items[2].reminder == "Later"


# ---------------------------------------------------------------------------
# Command tests
# ---------------------------------------------------------------------------
class TestEditDueTimeCommand:
    def _make_db_with_item(self, due_time=None):
        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", due_date=date(2026, 3, 15), due_time=due_time)
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        return db, lst, item

    def test_redo_sets_time(self):
        db, lst, item = self._make_db_with_item()
        window = make_window(db)
        cmd = EditDueTimeCommand(window, lst.id, item.id, None, time(14, 30))
        cmd.redo()
        assert item.due_time == time(14, 30)
        window._save_database.assert_called()
        window._refresh_ui.assert_called()

    def test_undo_restores_time(self):
        db, lst, item = self._make_db_with_item(due_time=time(14, 30))
        window = make_window(db)
        cmd = EditDueTimeCommand(window, lst.id, item.id, time(14, 30), time(9, 0))
        cmd.redo()
        assert item.due_time == time(9, 0)
        cmd.undo()
        assert item.due_time == time(14, 30)

    def test_clear_time(self):
        db, lst, item = self._make_db_with_item(due_time=time(14, 30))
        window = make_window(db)
        cmd = EditDueTimeCommand(window, lst.id, item.id, time(14, 30), None)
        cmd.redo()
        assert item.due_time is None

    def test_missing_list_noop(self):
        from uuid import uuid4

        db = Database()
        window = make_window(db)
        cmd = EditDueTimeCommand(window, uuid4(), uuid4(), None, time(9, 0))
        cmd.redo()  # Should not raise

    def test_missing_item_noop(self):
        from uuid import uuid4

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)
        window = make_window(db)
        cmd = EditDueTimeCommand(window, lst.id, uuid4(), None, time(9, 0))
        cmd.redo()  # Should not raise


class TestEditDueDateClearsTime:
    def test_clearing_date_clears_time(self):
        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", due_date=date(2026, 3, 15), due_time=time(14, 0))
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = make_window(db)

        cmd = EditDueDateCommand(
            window, lst.id, item.id, date(2026, 3, 15), None, old_due_time=time(14, 0)
        )
        cmd.redo()
        assert item.due_date is None
        assert item.due_time is None

    def test_undo_clearing_date_restores_time(self):
        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", due_date=date(2026, 3, 15), due_time=time(14, 0))
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = make_window(db)

        cmd = EditDueDateCommand(
            window, lst.id, item.id, date(2026, 3, 15), None, old_due_time=time(14, 0)
        )
        cmd.redo()
        assert item.due_time is None
        cmd.undo()
        assert item.due_date == date(2026, 3, 15)
        assert item.due_time == time(14, 0)

    def test_changing_date_keeps_time(self):
        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", due_date=date(2026, 3, 15), due_time=time(14, 0))
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = make_window(db)

        cmd = EditDueDateCommand(window, lst.id, item.id, date(2026, 3, 15), date(2026, 3, 20))
        cmd.redo()
        assert item.due_date == date(2026, 3, 20)
        assert item.due_time == time(14, 0)  # Time preserved when date changes


# ---------------------------------------------------------------------------
# Recurrence time preservation
# ---------------------------------------------------------------------------
class TestRecurrenceTimePreservation:
    def test_recurring_completion_preserves_time(self):
        """When a recurring item completes, the time should stay unchanged."""
        from pytodo_qt.core.models import compute_next_due_date
        from pytodo_qt.gui.commands import ToggleCompleteRecurringCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item(
            "Daily standup",
            due_date=date(2026, 3, 15),
            due_time=time(9, 0),
            recurrence_type="daily",
            recurrence_interval=1,
        )
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = make_window(db)

        assert item.due_date is not None
        next_due = compute_next_due_date(item.due_date, "daily", 1)
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
        # Time should be preserved (command doesn't touch due_time)
        assert item.due_time == time(9, 0)
        assert item.due_date == next_due
        assert item.complete is False

    def test_recurring_without_time(self):
        """Existing behavior unchanged for items without a due time."""
        from pytodo_qt.core.models import compute_next_due_date
        from pytodo_qt.gui.commands import ToggleCompleteRecurringCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item(
            "Weekly review",
            due_date=date(2026, 3, 15),
            recurrence_type="weekly",
            recurrence_interval=1,
        )
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = make_window(db)

        assert item.due_date is not None
        next_due = compute_next_due_date(item.due_date, "weekly", 1)
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
        assert item.due_time is None
        assert item.due_date == next_due


# ---------------------------------------------------------------------------
# Database tests (SQLite)
# ---------------------------------------------------------------------------
class TestDatabaseDueTime:
    def test_save_and_load_item_with_time(self, tmp_path):
        from pytodo_qt.core.database import DatabaseStorage

        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("Task", due_date=date(2026, 3, 15), due_time=time(14, 30))
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.due_time == time(14, 30)
        assert loaded.due_date == date(2026, 3, 15)

    def test_save_and_load_item_without_time(self, tmp_path):
        from pytodo_qt.core.database import DatabaseStorage

        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("Task", due_date=date(2026, 3, 15))
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.due_time is None

    def test_schema_version_8(self, tmp_path):
        from pytodo_qt.core.database import DatabaseStorage

        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)
        assert storage.get_schema_version() == 13


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------
class TestBackwardCompat:
    def test_legacy_item_no_time(self):
        legacy = {"reminder": "Old item", "priority": 1, "complete": False}
        item = TodoItem.from_legacy(legacy)
        assert item.due_time is None

    def test_sync_dict_missing_time_key(self):
        d = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "reminder": "Test",
            "priority": 2,
            "complete": False,
            "due_date": "2026-03-15",
            "created_at": 1000000,
            "updated_at": 1000000,
        }
        item = TodoItem.from_dict(d)
        assert item.due_time is None
        assert item.due_date == date(2026, 3, 15)


# ---------------------------------------------------------------------------
# TimeComboBox and parse_time_text
# ---------------------------------------------------------------------------


class TestParseTimeText:
    """Tests for parse_time_text() parsing various formats."""

    def test_12h_with_space(self):
        assert parse_time_text("2:30 PM") == time(14, 30)

    def test_12h_no_space(self):
        assert parse_time_text("2:30PM") == time(14, 30)

    def test_12h_lowercase(self):
        assert parse_time_text("2:30pm") == time(14, 30)

    def test_12h_am(self):
        assert parse_time_text("9:15 AM") == time(9, 15)

    def test_12h_12am_is_midnight(self):
        assert parse_time_text("12:00 AM") == time(0, 0)

    def test_12h_12pm_is_noon(self):
        assert parse_time_text("12:00 PM") == time(12, 0)

    def test_hour_only_pm(self):
        assert parse_time_text("2pm") == time(14, 0)

    def test_hour_only_am(self):
        assert parse_time_text("9 AM") == time(9, 0)

    def test_no_colon_pm(self):
        assert parse_time_text("230pm") == time(14, 30)

    def test_24h_format(self):
        assert parse_time_text("14:30") == time(14, 30)

    def test_24h_single_digit(self):
        assert parse_time_text("9:00") == time(9, 0)

    def test_bare_number_hour(self):
        assert parse_time_text("14") == time(14, 0)

    def test_midnight_24h(self):
        assert parse_time_text("0:00") == time(0, 0)

    def test_empty_string(self):
        assert parse_time_text("") is None

    def test_whitespace_only(self):
        assert parse_time_text("   ") is None

    def test_invalid_text(self):
        assert parse_time_text("not a time") is None

    def test_invalid_hour_24h(self):
        assert parse_time_text("25:00") is None

    def test_invalid_minute(self):
        assert parse_time_text("14:60") is None

    def test_invalid_12h_hour(self):
        assert parse_time_text("13:00 PM") is None

    def test_bare_number_too_high(self):
        assert parse_time_text("25") is None

    def test_strips_whitespace(self):
        assert parse_time_text("  2:30 PM  ") == time(14, 30)


class TestTimeComboBox:
    """Tests for the TimeComboBox widget."""

    def test_has_48_presets(self, qtbot):
        combo = TimeComboBox()
        qtbot.addWidget(combo)
        assert combo.count() == 48

    def test_first_item_is_midnight(self, qtbot):
        combo = TimeComboBox()
        qtbot.addWidget(combo)
        assert combo.itemData(0) == time(0, 0)

    def test_last_item_is_2330(self, qtbot):
        combo = TimeComboBox()
        qtbot.addWidget(combo)
        assert combo.itemData(47) == time(23, 30)

    def test_is_editable(self, qtbot):
        combo = TimeComboBox()
        qtbot.addWidget(combo)
        assert combo.isEditable()

    def test_set_time_exact_preset(self, qtbot):
        combo = TimeComboBox()
        qtbot.addWidget(combo)
        combo.set_time(time(14, 30))
        assert combo.get_time() == time(14, 30)

    def test_set_time_non_preset(self, qtbot):
        combo = TimeComboBox()
        qtbot.addWidget(combo)
        combo.set_time(time(14, 45))
        assert combo.get_time() == time(14, 45)

    def test_default_to_next_hour(self, qtbot):
        combo = TimeComboBox()
        qtbot.addWidget(combo)
        combo.default_to_next_hour()
        result = combo.get_time()
        assert result is not None
        assert result.minute == 0

    def test_get_time_from_preset_selection(self, qtbot):
        combo = TimeComboBox()
        qtbot.addWidget(combo)
        combo.setCurrentIndex(5)  # 2:30 AM
        assert combo.get_time() == time(2, 30)

    def test_12h_format_labels(self, qtbot):
        combo = TimeComboBox(time_format="12h")
        qtbot.addWidget(combo)
        assert combo.itemText(0) == "12:00 AM"
        assert combo.itemText(1) == "12:30 AM"
        assert combo.itemText(24) == "12:00 PM"
        assert combo.itemText(25) == "12:30 PM"

    def test_24h_format_labels(self, qtbot):
        combo = TimeComboBox(time_format="24h")
        qtbot.addWidget(combo)
        assert combo.itemText(0) == "00:00"
        assert combo.itemText(1) == "00:30"
        assert combo.itemText(24) == "12:00"
        assert combo.itemText(47) == "23:30"

    def test_has_placeholder_text(self, qtbot):
        combo = TimeComboBox()
        qtbot.addWidget(combo)
        line_edit = combo.lineEdit()
        assert line_edit is not None
        assert "2:30 PM" in line_edit.placeholderText()

    def test_has_tooltip(self, qtbot):
        combo = TimeComboBox()
        qtbot.addWidget(combo)
        tooltip = combo.toolTip()
        assert "arrow" in tooltip.lower()
        assert "type" in tooltip.lower()
