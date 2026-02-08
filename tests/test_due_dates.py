"""Tests for due date functionality."""

from datetime import date, timedelta

from pytodo_qt.core.models import (
    TodoItem,
    create_todo_item,
    format_due_date,
    is_due_this_week,
    is_due_today,
    is_overdue,
)
from pytodo_qt.gui.widgets.search_filter import FilterState


class TestDueDateHelpers:
    """Tests for due date helper functions."""

    def test_format_due_date_none(self):
        """Test formatting None due date."""
        assert format_due_date(None) == ""

    def test_format_due_date_today(self):
        """Test formatting today's date."""
        today = date.today()
        assert format_due_date(today) == "Today"

    def test_format_due_date_tomorrow(self):
        """Test formatting tomorrow's date."""
        tomorrow = date.today() + timedelta(days=1)
        assert format_due_date(tomorrow) == "Tomorrow"

    def test_format_due_date_overdue(self):
        """Test formatting overdue date."""
        yesterday = date.today() - timedelta(days=1)
        assert format_due_date(yesterday) == "Overdue (1d)"

        two_days_ago = date.today() - timedelta(days=2)
        assert format_due_date(two_days_ago) == "Overdue (2d)"

    def test_format_due_date_this_week(self):
        """Test formatting date within this week."""
        # 3 days from now should show day name
        three_days = date.today() + timedelta(days=3)
        result = format_due_date(three_days)
        assert result == three_days.strftime("%A")

    def test_format_due_date_same_year(self):
        """Test formatting date in same year but beyond this week."""
        # 15 days from now
        future = date.today() + timedelta(days=15)
        if future.year == date.today().year:
            result = format_due_date(future)
            assert result == future.strftime("%b %d")

    def test_format_due_date_different_year(self):
        """Test formatting date in different year."""
        next_year = date(date.today().year + 1, 3, 15)
        result = format_due_date(next_year)
        assert result == next_year.strftime("%b %d, %Y")

    def test_format_due_date_overdue_completed(self):
        """Test that completed items don't show 'Overdue'."""
        yesterday = date.today() - timedelta(days=1)
        # Incomplete item shows "Overdue"
        assert format_due_date(yesterday, complete=False) == "Overdue (1d)"
        # Complete item shows the date instead
        result = format_due_date(yesterday, complete=True)
        assert "Overdue" not in result
        # Should show the date
        if yesterday.year == date.today().year:
            assert result == yesterday.strftime("%b %d")
        else:
            assert result == yesterday.strftime("%b %d, %Y")

    def test_format_due_date_exactly_7_days(self):
        """Test that exactly 7 days out shows date, not day name."""
        in_7_days = date.today() + timedelta(days=7)
        result = format_due_date(in_7_days)
        # Should NOT be just a day name (which would be ambiguous)
        # Should be "Jan 15" or similar
        assert result == in_7_days.strftime("%b %d")

    def test_format_due_date_6_days_shows_day_name(self):
        """Test that 6 days out shows day name (unambiguous)."""
        in_6_days = date.today() + timedelta(days=6)
        result = format_due_date(in_6_days)
        assert result == in_6_days.strftime("%A")

    def test_is_overdue_none(self):
        """Test is_overdue with None."""
        assert is_overdue(None) is False

    def test_is_overdue_past(self):
        """Test is_overdue with past date."""
        yesterday = date.today() - timedelta(days=1)
        assert is_overdue(yesterday) is True

    def test_is_overdue_today(self):
        """Test is_overdue with today's date."""
        today = date.today()
        assert is_overdue(today) is False

    def test_is_overdue_future(self):
        """Test is_overdue with future date."""
        tomorrow = date.today() + timedelta(days=1)
        assert is_overdue(tomorrow) is False

    def test_is_due_today_none(self):
        """Test is_due_today with None."""
        assert is_due_today(None) is False

    def test_is_due_today_today(self):
        """Test is_due_today with today's date."""
        today = date.today()
        assert is_due_today(today) is True

    def test_is_due_today_tomorrow(self):
        """Test is_due_today with tomorrow's date."""
        tomorrow = date.today() + timedelta(days=1)
        assert is_due_today(tomorrow) is False

    def test_is_due_this_week_none(self):
        """Test is_due_this_week with None."""
        assert is_due_this_week(None) is False

    def test_is_due_this_week_today(self):
        """Test is_due_this_week with today's date."""
        today = date.today()
        assert is_due_this_week(today) is True

    def test_is_due_this_week_within_week(self):
        """Test is_due_this_week with date within 7 days."""
        in_5_days = date.today() + timedelta(days=5)
        assert is_due_this_week(in_5_days) is True

    def test_is_due_this_week_exactly_7_days(self):
        """Test is_due_this_week with date exactly 7 days out."""
        in_7_days = date.today() + timedelta(days=7)
        assert is_due_this_week(in_7_days) is True

    def test_is_due_this_week_8_days(self):
        """Test is_due_this_week with date 8 days out."""
        in_8_days = date.today() + timedelta(days=8)
        assert is_due_this_week(in_8_days) is False

    def test_is_due_this_week_overdue(self):
        """Test is_due_this_week with overdue date."""
        yesterday = date.today() - timedelta(days=1)
        assert is_due_this_week(yesterday) is False


class TestTodoItemDueDate:
    """Tests for TodoItem due date field."""

    def test_create_item_without_due_date(self):
        """Test creating item without due date."""
        item = create_todo_item("Test task")
        assert item.due_date is None

    def test_create_item_with_due_date(self):
        """Test creating item with due date."""
        due = date.today() + timedelta(days=3)
        item = create_todo_item("Test task", due_date=due)
        assert item.due_date == due

    def test_due_date_serialization(self):
        """Test due date in to_dict and from_dict."""
        due = date(2025, 6, 15)
        item = create_todo_item("Test task", due_date=due)

        data = item.to_dict()
        assert data["due_date"] == "2025-06-15"

        item2 = TodoItem.from_dict(data)
        assert item2.due_date == due

    def test_none_due_date_serialization(self):
        """Test None due date in to_dict and from_dict."""
        item = create_todo_item("Test task")

        data = item.to_dict()
        assert data["due_date"] is None

        item2 = TodoItem.from_dict(data)
        assert item2.due_date is None

    def test_modify_due_date(self):
        """Test modifying due date."""
        item = create_todo_item("Test task")
        assert item.due_date is None

        due = date.today() + timedelta(days=5)
        item.due_date = due
        item.mark_updated()

        assert item.due_date == due


class TestFilterStateDueDate:
    """Tests for FilterState due date filter."""

    def test_default_due_date_filter(self):
        """Test default due date filter is 0 (All)."""
        state = FilterState()
        assert state.due_date == 0

    def test_due_date_filter_makes_active(self):
        """Test non-zero due_date makes filter active."""
        state = FilterState(due_date=1)  # Overdue
        assert state.is_active is True

    def test_due_date_filter_overdue(self):
        """Test filtering by overdue."""
        state = FilterState(due_date=1)
        assert state.due_date == 1

    def test_due_date_filter_today(self):
        """Test filtering by today."""
        state = FilterState(due_date=2)
        assert state.due_date == 2

    def test_due_date_filter_this_week(self):
        """Test filtering by this week."""
        state = FilterState(due_date=3)
        assert state.due_date == 3

    def test_due_date_filter_no_due_date(self):
        """Test filtering by no due date."""
        state = FilterState(due_date=4)
        assert state.due_date == 4


class TestApplyDueDateFilter:
    """Tests for applying due date filter to items."""

    def _apply_filter(self, items: list, filter_state: FilterState | None) -> list:
        """Simulate the _apply_filter method from TodoTableWidget."""
        if filter_state is None:
            return items
        filtered = items
        if filter_state.text:
            search = filter_state.text.lower()
            filtered = [i for i in filtered if search in i.reminder.lower()]
        if filter_state.priority != 0:
            filtered = [i for i in filtered if i.priority == filter_state.priority]
        if filter_state.status == 1:
            filtered = [i for i in filtered if not i.complete]
        elif filter_state.status == 2:
            filtered = [i for i in filtered if i.complete]
        # Due date filters
        if filter_state.due_date == 1:  # Overdue
            filtered = [i for i in filtered if is_overdue(i.due_date)]
        elif filter_state.due_date == 2:  # Today
            filtered = [i for i in filtered if is_due_today(i.due_date)]
        elif filter_state.due_date == 3:  # This Week
            filtered = [i for i in filtered if is_due_this_week(i.due_date)]
        elif filter_state.due_date == 4:  # No Due Date
            filtered = [i for i in filtered if i.due_date is None]
        return filtered

    def test_filter_overdue(self):
        """Test filtering for overdue items."""
        yesterday = date.today() - timedelta(days=1)
        tomorrow = date.today() + timedelta(days=1)

        items = [
            create_todo_item("Overdue task", due_date=yesterday),
            create_todo_item("Tomorrow task", due_date=tomorrow),
            create_todo_item("No date task"),
        ]
        state = FilterState(due_date=1)

        result = self._apply_filter(items, state)

        assert len(result) == 1
        assert result[0].reminder == "Overdue task"

    def test_filter_today(self):
        """Test filtering for items due today."""
        today = date.today()
        tomorrow = date.today() + timedelta(days=1)

        items = [
            create_todo_item("Today task", due_date=today),
            create_todo_item("Tomorrow task", due_date=tomorrow),
            create_todo_item("No date task"),
        ]
        state = FilterState(due_date=2)

        result = self._apply_filter(items, state)

        assert len(result) == 1
        assert result[0].reminder == "Today task"

    def test_filter_this_week(self):
        """Test filtering for items due this week."""
        today = date.today()
        in_5_days = today + timedelta(days=5)
        in_15_days = today + timedelta(days=15)

        items = [
            create_todo_item("Today task", due_date=today),
            create_todo_item("This week task", due_date=in_5_days),
            create_todo_item("Later task", due_date=in_15_days),
            create_todo_item("No date task"),
        ]
        state = FilterState(due_date=3)

        result = self._apply_filter(items, state)

        assert len(result) == 2
        reminders = [item.reminder for item in result]
        assert "Today task" in reminders
        assert "This week task" in reminders

    def test_filter_no_due_date(self):
        """Test filtering for items without due date."""
        today = date.today()

        items = [
            create_todo_item("Today task", due_date=today),
            create_todo_item("No date 1"),
            create_todo_item("No date 2"),
        ]
        state = FilterState(due_date=4)

        result = self._apply_filter(items, state)

        assert len(result) == 2
        assert all(item.due_date is None for item in result)

    def test_combined_text_and_due_date_filter(self):
        """Test combining text and due date filters."""
        today = date.today()

        items = [
            create_todo_item("Buy milk", due_date=today),
            create_todo_item("Buy bread", due_date=today + timedelta(days=5)),
            create_todo_item("Call doctor", due_date=today),
        ]
        state = FilterState(text="buy", due_date=2)

        result = self._apply_filter(items, state)

        assert len(result) == 1
        assert result[0].reminder == "Buy milk"


class TestSortingByDueDate:
    """Tests for sorting items by due date."""

    def test_sort_items_with_due_dates_first(self):
        """Test that items with due dates sort before those without."""
        today = date.today()
        tomorrow = today + timedelta(days=1)

        items = [
            create_todo_item("No date", priority=1),
            create_todo_item("Tomorrow", priority=1, due_date=tomorrow),
            create_todo_item("Today", priority=1, due_date=today),
        ]

        # Sort key: items with due dates first (by date, then priority), then items without
        def sort_key(item):
            if item.due_date is None:
                return (1, item.priority, item.reminder.lower())
            else:
                return (0, item.due_date.isoformat(), item.priority, item.reminder.lower())

        sorted_items = sorted(items, key=sort_key)

        assert sorted_items[0].reminder == "Today"
        assert sorted_items[1].reminder == "Tomorrow"
        assert sorted_items[2].reminder == "No date"

    def test_sort_items_by_due_date_then_priority(self):
        """Test sorting by due date, then by priority."""
        today = date.today()

        items = [
            create_todo_item("Low today", priority=3, due_date=today),
            create_todo_item("High today", priority=1, due_date=today),
            create_todo_item("Normal today", priority=2, due_date=today),
        ]

        def sort_key(item):
            if item.due_date is None:
                return (1, item.priority, item.reminder.lower())
            else:
                return (0, item.due_date.isoformat(), item.priority, item.reminder.lower())

        sorted_items = sorted(items, key=sort_key)

        assert sorted_items[0].reminder == "High today"
        assert sorted_items[1].reminder == "Normal today"
        assert sorted_items[2].reminder == "Low today"
