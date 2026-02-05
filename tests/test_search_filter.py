"""Tests for search/filter functionality."""

from pytodo_qt.core.models import create_todo_item
from pytodo_qt.gui.widgets.search_filter import FilterState


class TestFilterState:
    """Tests for FilterState dataclass."""

    def test_default_not_active(self):
        """Test that default state is not active."""
        state = FilterState()

        assert state.is_active is False

    def test_text_makes_active(self):
        """Test that text makes filter active."""
        state = FilterState(text="hello")

        assert state.is_active is True

    def test_priority_makes_active(self):
        """Test that non-zero priority makes filter active."""
        state = FilterState(priority=1)

        assert state.is_active is True

    def test_status_makes_active(self):
        """Test that non-zero status makes filter active."""
        state = FilterState(status=1)

        assert state.is_active is True

    def test_combined_active(self):
        """Test that combined filters are active."""
        state = FilterState(text="test", priority=2, status=1)

        assert state.is_active is True

    def test_zero_priority_not_active(self):
        """Test that priority=0 alone doesn't make filter active."""
        state = FilterState(priority=0)

        assert state.is_active is False


class TestFilterLogic:
    """Tests for filter logic using FilterState and TodoItems."""

    def test_text_filter_matches(self):
        """Test text filter matches substring."""
        item = create_todo_item("Buy groceries")
        state = FilterState(text="groc")

        # Simulate filter logic from todo_table
        search = state.text.lower()
        matches = search in item.reminder.lower()

        assert matches is True

    def test_text_filter_case_insensitive(self):
        """Test text filter is case insensitive."""
        item = create_todo_item("Buy Groceries")
        state = FilterState(text="GROC")

        search = state.text.lower()
        matches = search in item.reminder.lower()

        assert matches is True

    def test_text_filter_no_match(self):
        """Test text filter doesn't match unrelated text."""
        item = create_todo_item("Buy groceries")
        state = FilterState(text="doctor")

        search = state.text.lower()
        matches = search in item.reminder.lower()

        assert matches is False

    def test_priority_filter_high(self):
        """Test priority filter matches high priority."""
        item = create_todo_item("Urgent task", priority=1)
        state = FilterState(priority=1)

        matches = item.priority == state.priority

        assert matches is True

    def test_priority_filter_mismatch(self):
        """Test priority filter doesn't match different priority."""
        item = create_todo_item("Normal task", priority=2)
        state = FilterState(priority=1)

        matches = item.priority == state.priority

        assert matches is False

    def test_status_filter_active(self):
        """Test status filter for active items."""
        item = create_todo_item("Incomplete task")
        state = FilterState(status=1)  # Active

        # Active (status=1) means not complete
        matches = state.status == 1 and not item.complete

        assert matches is True

    def test_status_filter_completed(self):
        """Test status filter for completed items."""
        item = create_todo_item("Done task")
        item.complete = True
        state = FilterState(status=2)  # Completed

        # Completed (status=2) matches complete items
        matches = state.status == 2 and item.complete

        assert matches is True

    def test_status_filter_excludes_completed(self):
        """Test active status filter excludes completed items."""
        item = create_todo_item("Done task")
        item.complete = True
        state = FilterState(status=1)  # Active

        # Active (status=1) should not match completed items
        matches = state.status == 1 and not item.complete

        assert matches is False

    def test_combined_filters(self):
        """Test combined text, priority, and status filters."""
        item = create_todo_item("Buy groceries", priority=2)
        item.complete = False
        state = FilterState(text="buy", priority=2, status=1)

        # Apply all filters
        text_match = state.text.lower() in item.reminder.lower()
        priority_match = item.priority == state.priority
        status_match = not item.complete  # status=1 means active

        assert text_match and priority_match and status_match

    def test_combined_filters_partial_fail(self):
        """Test combined filters fail if any condition fails."""
        item = create_todo_item("Buy groceries", priority=3)  # Low priority
        item.complete = False
        state = FilterState(text="buy", priority=2, status=1)  # Expects Normal

        text_match = state.text.lower() in item.reminder.lower()
        priority_match = item.priority == state.priority
        status_match = not item.complete

        # Text and status match, but priority doesn't
        assert text_match is True
        assert priority_match is False
        assert status_match is True


class TestApplyFilter:
    """Tests for the _apply_filter logic pattern."""

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
        return filtered

    def test_no_filter_returns_all(self):
        """Test that None filter returns all items."""
        items = [
            create_todo_item("Item 1"),
            create_todo_item("Item 2"),
            create_todo_item("Item 3"),
        ]

        result = self._apply_filter(items, None)

        assert len(result) == 3

    def test_empty_filter_returns_all(self):
        """Test that empty filter returns all items."""
        items = [
            create_todo_item("Item 1"),
            create_todo_item("Item 2"),
        ]
        state = FilterState()

        result = self._apply_filter(items, state)

        assert len(result) == 2

    def test_text_filter_reduces_results(self):
        """Test that text filter reduces results."""
        items = [
            create_todo_item("Buy milk"),
            create_todo_item("Buy bread"),
            create_todo_item("Call doctor"),
        ]
        state = FilterState(text="buy")

        result = self._apply_filter(items, state)

        assert len(result) == 2
        assert all("buy" in item.reminder.lower() for item in result)

    def test_priority_filter_reduces_results(self):
        """Test that priority filter reduces results."""
        items = [
            create_todo_item("High task", priority=1),
            create_todo_item("Normal task", priority=2),
            create_todo_item("Low task", priority=3),
        ]
        state = FilterState(priority=1)

        result = self._apply_filter(items, state)

        assert len(result) == 1
        assert result[0].priority == 1

    def test_status_filter_active(self):
        """Test status filter for active only."""
        item1 = create_todo_item("Active")
        item2 = create_todo_item("Completed")
        item2.complete = True
        items = [item1, item2]
        state = FilterState(status=1)

        result = self._apply_filter(items, state)

        assert len(result) == 1
        assert result[0].complete is False

    def test_status_filter_completed(self):
        """Test status filter for completed only."""
        item1 = create_todo_item("Active")
        item2 = create_todo_item("Completed")
        item2.complete = True
        items = [item1, item2]
        state = FilterState(status=2)

        result = self._apply_filter(items, state)

        assert len(result) == 1
        assert result[0].complete is True

    def test_combined_filters_stacked(self):
        """Test that combined filters stack correctly."""
        items = [
            create_todo_item("Buy milk", priority=1),  # High, matches text
            create_todo_item("Buy bread", priority=2),  # Normal, matches text
            create_todo_item("Call doctor", priority=1),  # High, no text match
        ]
        state = FilterState(text="buy", priority=1)

        result = self._apply_filter(items, state)

        assert len(result) == 1
        assert result[0].reminder == "Buy milk"

    def test_filter_empty_result(self):
        """Test filter can return empty list."""
        items = [
            create_todo_item("Buy milk"),
            create_todo_item("Buy bread"),
        ]
        state = FilterState(text="xyz")

        result = self._apply_filter(items, state)

        assert len(result) == 0
