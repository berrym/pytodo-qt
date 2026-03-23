"""Date-mocked integration tests for recurring tasks.

These tests patch date.today() to specific dates, allowing us to verify
exact behavior of compute_next_due_date, ToggleCompleteRecurringCommand,
and is_recurrence_ended without waiting or relying on the real clock.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from pytodo_qt.core.models import (
    Database,
    TodoItem,
    compute_next_due_date,
    create_todo_item,
    create_todo_list,
    is_recurrence_ended,
)
from pytodo_qt.gui.commands import ToggleCompleteRecurringCommand


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


# ---------------------------------------------------------------------------
# Daily — overdue cascade prevention
# ---------------------------------------------------------------------------
class TestDailyDateMocked:
    def test_overdue_by_one_day(self):
        """Due yesterday, completed today → next = today + 1, not yesterday + 1."""
        fake_today = date(2026, 3, 10)
        due = date(2026, 3, 9)  # yesterday
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "daily", 1)
        assert result == date(2026, 3, 11)

    def test_overdue_by_many_days(self):
        """Due 10 days ago → next = today + 1, not due + 1."""
        fake_today = date(2026, 3, 15)
        due = date(2026, 3, 5)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "daily", 1)
        assert result == date(2026, 3, 16)

    def test_interval_3_overdue(self):
        """Due 5 days ago, interval=3 → next = today + 3."""
        fake_today = date(2026, 4, 10)
        due = date(2026, 4, 5)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "daily", 3)
        assert result == date(2026, 4, 13)

    def test_completed_on_due_date(self):
        """Due today, completed today → next = today + interval."""
        fake_today = date(2026, 6, 1)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(fake_today, "daily", 1)
        assert result == date(2026, 6, 2)

    def test_daily_crosses_month_boundary(self):
        """Daily from Jan 31 → Feb 1."""
        fake_today = date(2026, 1, 31)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(fake_today, "daily", 1)
        assert result == date(2026, 2, 1)

    def test_daily_crosses_year_boundary(self):
        """Daily from Dec 31 → Jan 1."""
        fake_today = date(2026, 12, 31)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(fake_today, "daily", 1)
        assert result == date(2027, 1, 1)


# ---------------------------------------------------------------------------
# Weekly — weekday preservation across boundaries
# ---------------------------------------------------------------------------
class TestWeeklyDateMocked:
    def test_preserves_weekday_same_week(self):
        """Due on Wednesday, today=Monday → next Wednesday this week? No,
        since days_ahead > 0 but interval=1 means same week's Wednesday."""
        fake_today = date(2026, 3, 2)  # Monday
        due = date(2026, 3, 4)  # Wednesday
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "weekly", 1)
        # Wednesday is 2 days ahead, days_ahead=2, interval=1 → stays 2
        assert result == date(2026, 3, 4)  # This Wednesday
        assert result.weekday() == 2  # Wednesday

    def test_preserves_weekday_past_in_week(self):
        """Due on Monday, today=Wednesday → next Monday = next week."""
        fake_today = date(2026, 3, 4)  # Wednesday
        due = date(2026, 3, 2)  # Monday (past)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "weekly", 1)
        # Monday is -2 days, so days_ahead = -2 + 7 = 5
        assert result == date(2026, 3, 9)  # Next Monday
        assert result.weekday() == 0

    def test_same_weekday_today(self):
        """Due on Wednesday, today=Wednesday → days_ahead=0 → add 7."""
        fake_today = date(2026, 3, 4)  # Wednesday
        due = date(2026, 3, 4)  # Also Wednesday
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "weekly", 1)
        assert result == date(2026, 3, 11)  # Next Wednesday
        assert result.weekday() == 2

    def test_biweekly_preserves_weekday(self):
        """Every 2 weeks, due on Friday, today=Friday → next = 14 days later."""
        fake_today = date(2026, 3, 6)  # Friday
        due = date(2026, 3, 6)  # Friday
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "weekly", 2)
        assert result == date(2026, 3, 20)  # Two Fridays later
        assert result.weekday() == 4  # Friday

    def test_biweekly_different_day(self):
        """Every 2 weeks, due on Thursday, today=Monday → Thursday + extra week."""
        fake_today = date(2026, 3, 2)  # Monday
        due = date(2026, 2, 26)  # Thursday
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "weekly", 2)
        # Thursday weekday=3, Monday weekday=0, days_ahead=3, interval=2 → 3 + 7*(2-1) = 10
        assert result == date(2026, 3, 12)  # Thursday in 10 days
        assert result.weekday() == 3  # Thursday

    def test_weekly_across_month_boundary(self):
        """Due on Friday Jan 30, today=Jan 30 → next = Feb 6."""
        fake_today = date(2026, 1, 30)  # Friday
        due = date(2026, 1, 30)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "weekly", 1)
        assert result.weekday() == fake_today.weekday()
        assert result.month == 2

    def test_weekly_across_year_boundary(self):
        """Due on Wednesday Dec 31, today=Dec 31 → next = Jan 7."""
        fake_today = date(2025, 12, 31)  # Wednesday
        due = date(2025, 12, 31)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "weekly", 1)
        assert result.weekday() == fake_today.weekday()
        assert result.year == 2026
        assert result.month == 1

    def test_weekly_overdue_by_weeks(self):
        """Due 3 weeks ago on Monday, today=Thursday → next Monday."""
        fake_today = date(2026, 3, 26)  # Thursday
        due = date(2026, 3, 2)  # Monday, 24 days ago
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "weekly", 1)
        # Monday weekday=0, Thursday weekday=3, days_ahead = 0-3 = -3 → -3+7 = 4
        assert result == date(2026, 3, 30)  # Next Monday
        assert result.weekday() == 0


# ---------------------------------------------------------------------------
# Monthly — end-of-month clamping
# ---------------------------------------------------------------------------
class TestMonthlyDateMocked:
    def test_jan31_to_feb(self):
        """Monthly item due on 31st → Feb clamps to 28 (non-leap)."""
        fake_today = date(2026, 1, 31)
        due = date(2026, 1, 31)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 1)
        assert result == date(2026, 2, 28)

    def test_jan31_to_feb_leap_year(self):
        """Monthly item due on 31st → Feb in leap year clamps to 29."""
        fake_today = date(2028, 1, 31)  # 2028 is leap year
        due = date(2028, 1, 31)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 1)
        assert result == date(2028, 2, 29)

    def test_jan30_to_feb(self):
        """Monthly item due on 30th → Feb clamps to 28."""
        fake_today = date(2026, 1, 30)
        due = date(2026, 1, 30)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 1)
        assert result == date(2026, 2, 28)

    def test_march31_to_april(self):
        """Monthly item due on 31st → April has 30 days → 30th."""
        fake_today = date(2026, 3, 31)
        due = date(2026, 3, 31)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 1)
        assert result == date(2026, 4, 30)

    def test_feb28_to_march_preserves_original_day(self):
        """Feb 28 monthly: original due was 28th → March 28th (not 31st)."""
        fake_today = date(2026, 2, 28)
        due = date(2026, 2, 28)  # original day is 28
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 1)
        assert result == date(2026, 3, 28)

    def test_december_wraps_to_january(self):
        """Monthly from December → January next year."""
        fake_today = date(2026, 12, 15)
        due = date(2026, 12, 15)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 1)
        assert result == date(2027, 1, 15)

    def test_november_wraps_to_january_bimonthly(self):
        """Every 2 months from November → January next year."""
        fake_today = date(2026, 11, 10)
        due = date(2026, 11, 10)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 2)
        assert result == date(2027, 1, 10)

    def test_quarterly_wraps_year(self):
        """Every 3 months from November → February next year."""
        fake_today = date(2026, 11, 5)
        due = date(2026, 11, 5)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 3)
        assert result == date(2027, 2, 5)

    def test_monthly_overdue(self):
        """Due Jan 15, today=Mar 10 → next = Apr 15 (1 month from today)."""
        fake_today = date(2026, 3, 10)
        due = date(2026, 1, 15)  # overdue
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 1)
        assert result == date(2026, 4, 15)

    def test_day15_every_month_sequence(self):
        """Simulate completing a monthly-on-15th across several months."""
        due = date(2026, 1, 15)
        expected_sequence = [
            date(2026, 2, 15),
            date(2026, 3, 15),
            date(2026, 4, 15),
            date(2026, 5, 15),
        ]
        for i, expected in enumerate(expected_sequence):
            # Simulate completing on the due date each time
            fake_today = due
            with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
                next_due = compute_next_due_date(due, "monthly", 1)
            assert next_due == expected, f"Iteration {i}: expected {expected}, got {next_due}"
            due = next_due

    def test_day31_clamping_sequence(self):
        """31st monthly: Jan→Feb(28)→Mar(28*)→... tracks original day=31."""
        fake_today = date(2026, 1, 31)
        due = date(2026, 1, 31)  # original_day = 31
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            feb = compute_next_due_date(due, "monthly", 1)
        assert feb == date(2026, 2, 28)  # Clamped

        # Now completing the Feb 28 item — but the original due was 31
        # Key: the function uses current_due.day to determine the target
        # So if we pass the clamped Feb 28, it becomes "every 28th" not "every 31st"
        # This is a known trade-off of the advance-in-place model
        fake_today2 = date(2026, 2, 28)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today2)):
            mar = compute_next_due_date(feb, "monthly", 1)
        assert mar == date(2026, 3, 28)


# ---------------------------------------------------------------------------
# Yearly — leap year edge cases
# ---------------------------------------------------------------------------
class TestYearlyDateMocked:
    def test_feb29_to_non_leap_year(self):
        """Feb 29 yearly → Feb 28 in non-leap year."""
        fake_today = date(2024, 2, 29)  # 2024 is leap
        due = date(2024, 2, 29)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "yearly", 1)
        assert result == date(2025, 2, 28)

    def test_feb29_to_next_leap_year(self):
        """Feb 29 every 4 years → Feb 29 in next leap year."""
        fake_today = date(2024, 2, 29)
        due = date(2024, 2, 29)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "yearly", 4)
        assert result == date(2028, 2, 29)

    def test_feb29_interval2_skips_leap(self):
        """Feb 29 every 2 years: 2024 → 2026 (non-leap) → Feb 28."""
        fake_today = date(2024, 2, 29)
        due = date(2024, 2, 29)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "yearly", 2)
        assert result == date(2026, 2, 28)

    def test_normal_date_yearly(self):
        """June 15 yearly → June 15 next year."""
        fake_today = date(2026, 6, 15)
        due = date(2026, 6, 15)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "yearly", 1)
        assert result == date(2027, 6, 15)

    def test_yearly_overdue(self):
        """Due 2025-06-15, today=2026-03-10 → next = 2027-06-15."""
        fake_today = date(2026, 3, 10)
        due = date(2025, 6, 15)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "yearly", 1)
        assert result == date(2027, 6, 15)

    def test_dec31_yearly(self):
        """Dec 31 yearly → Dec 31 next year."""
        fake_today = date(2026, 12, 31)
        due = date(2026, 12, 31)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "yearly", 1)
        assert result == date(2027, 12, 31)

    def test_jan1_yearly(self):
        """Jan 1 yearly → Jan 1 next year."""
        fake_today = date(2026, 1, 1)
        due = date(2026, 1, 1)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "yearly", 1)
        assert result == date(2027, 1, 1)


# ---------------------------------------------------------------------------
# is_recurrence_ended with mocked dates
# ---------------------------------------------------------------------------
class TestIsRecurrenceEndedDateMocked:
    def test_end_date_exactly_on_boundary(self):
        """Next due == end_date → not ended (ends when PAST end_date)."""
        item = TodoItem(
            reminder="Test",
            recurrence_type="weekly",
            recurrence_end_date=date(2026, 6, 15),
        )
        # next_due exactly equals end_date → next_due > end_date is False
        assert is_recurrence_ended(item, next_due=date(2026, 6, 15)) is False

    def test_end_date_one_day_past(self):
        """Next due one day past end_date → ended."""
        item = TodoItem(
            reminder="Test",
            recurrence_type="weekly",
            recurrence_end_date=date(2026, 6, 15),
        )
        assert is_recurrence_ended(item, next_due=date(2026, 6, 16)) is True

    def test_end_count_exact_boundary(self):
        """count=4, end_count=5 → count+1 >= 5 → ended."""
        item = TodoItem(
            reminder="Test",
            recurrence_type="daily",
            recurrence_end_count=5,
        )
        item.recurrence_count = 4
        assert is_recurrence_ended(item) is True

    def test_end_count_one_before(self):
        """count=3, end_count=5 → count+1=4 < 5 → not ended."""
        item = TodoItem(
            reminder="Test",
            recurrence_type="daily",
            recurrence_end_count=5,
        )
        item.recurrence_count = 3
        assert is_recurrence_ended(item) is False


# ---------------------------------------------------------------------------
# ToggleCompleteRecurringCommand — full integration with mocked dates
# ---------------------------------------------------------------------------
class TestToggleCompleteRecurringCommandMocked:
    def _make_setup(
        self,
        due: date,
        recurrence_type: str = "weekly",
        interval: int = 1,
        end_count: int | None = None,
        count: int = 0,
    ):
        """Set up a database with a recurring item and return components."""
        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item(
            reminder="Recurring task",
            due_date=due,
            recurrence_type=recurrence_type,
            recurrence_interval=interval,
            recurrence_end_count=end_count,
        )
        item.recurrence_count = count
        lst.add_item(item)
        db.add_list(lst)
        window = make_window(db)
        return db, lst, item, window

    def test_daily_complete_and_advance(self):
        """Complete a daily task: marks complete, due_date unchanged (auto-advance cycles later)."""
        fake_today = date(2026, 4, 15)
        due = date(2026, 4, 15)
        db, lst, item, window = self._make_setup(due, "daily")

        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            next_due = compute_next_due_date(due, "daily", 1)
            ended = is_recurrence_ended(item, next_due)

        cmd = ToggleCompleteRecurringCommand(window, lst.id, item.id, due, next_due, 0, ended)
        cmd.redo()

        assert item.complete is True
        assert item.due_date == due  # unchanged; auto-advance cycles later
        assert item.recurrence_count == 1

    def test_weekly_complete_preserves_weekday(self):
        """Complete weekly task: marks complete, due_date stays at original."""
        fake_today = date(2026, 3, 4)  # Wednesday
        due = date(2026, 3, 4)  # Wednesday
        db, lst, item, window = self._make_setup(due, "weekly")

        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            next_due = compute_next_due_date(due, "weekly", 1)
            ended = is_recurrence_ended(item, next_due)

        cmd = ToggleCompleteRecurringCommand(window, lst.id, item.id, due, next_due, 0, ended)
        cmd.redo()

        assert item.complete is True
        assert item.due_date == due  # unchanged; auto-advance cycles later

    def test_monthly_complete_with_clamping(self):
        """Complete monthly Jan 31: marks complete, due_date stays at original."""
        fake_today = date(2026, 1, 31)
        due = date(2026, 1, 31)
        db, lst, item, window = self._make_setup(due, "monthly")

        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            next_due = compute_next_due_date(due, "monthly", 1)
            ended = is_recurrence_ended(item, next_due)

        cmd = ToggleCompleteRecurringCommand(window, lst.id, item.id, due, next_due, 0, ended)
        cmd.redo()

        assert item.complete is True
        assert item.due_date == due  # unchanged; auto-advance cycles later
        assert item.recurrence_count == 1

    def test_yearly_feb29_to_feb28(self):
        """Complete yearly Feb 29 in leap year: marks complete, due_date stays."""
        fake_today = date(2024, 2, 29)
        due = date(2024, 2, 29)
        db, lst, item, window = self._make_setup(due, "yearly")

        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            next_due = compute_next_due_date(due, "yearly", 1)
            ended = is_recurrence_ended(item, next_due)

        cmd = ToggleCompleteRecurringCommand(window, lst.id, item.id, due, next_due, 0, ended)
        cmd.redo()

        assert item.complete is True
        assert item.due_date == due  # unchanged; auto-advance cycles later

    def test_undo_restores_exact_original(self):
        """Undo after completing a recurring task restores original state."""
        fake_today = date(2026, 5, 1)
        due = date(2026, 5, 1)
        db, lst, item, window = self._make_setup(due, "daily")

        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            next_due = compute_next_due_date(due, "daily", 1)

        cmd = ToggleCompleteRecurringCommand(window, lst.id, item.id, due, next_due, 0, False)
        cmd.redo()
        assert item.complete is True
        assert item.recurrence_count == 1

        cmd.undo()
        assert item.due_date == date(2026, 5, 1)
        assert item.recurrence_count == 0
        assert item.complete is False

    def test_end_count_reached_marks_complete(self):
        """When recurrence end count is reached, item stays complete."""
        fake_today = date(2026, 6, 1)
        due = date(2026, 6, 1)
        db, lst, item, window = self._make_setup(due, "daily", end_count=3, count=2)

        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            next_due = compute_next_due_date(due, "daily", 1)
            ended = is_recurrence_ended(item, next_due)

        assert ended is True

        cmd = ToggleCompleteRecurringCommand(window, lst.id, item.id, due, None, 2, True)
        cmd.redo()

        assert item.complete is True
        assert item.recurrence_count == 3

    def test_end_count_not_reached_continues(self):
        """When count is below end_count, item marks complete (auto-advance cycles later)."""
        fake_today = date(2026, 6, 1)
        due = date(2026, 6, 1)
        db, lst, item, window = self._make_setup(due, "daily", end_count=5, count=1)

        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            next_due = compute_next_due_date(due, "daily", 1)
            ended = is_recurrence_ended(item, next_due)

        assert ended is False

        cmd = ToggleCompleteRecurringCommand(window, lst.id, item.id, due, next_due, 1, False)
        cmd.redo()

        assert item.complete is True
        assert item.due_date == due  # unchanged; auto-advance cycles later
        assert item.recurrence_count == 2

    def test_multiple_completions_sequence(self):
        """Simulate completing a daily task 5 times, with auto-advance between cycles."""
        due = date(2026, 7, 1)
        db, lst, item, window = self._make_setup(due, "daily")

        for i in range(5):
            fake_today = due
            with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
                next_due = compute_next_due_date(due, "daily", 1)
                ended = is_recurrence_ended(item, next_due)

            cmd = ToggleCompleteRecurringCommand(window, lst.id, item.id, due, next_due, i, ended)
            cmd.redo()

            assert item.complete is True
            assert item.recurrence_count == i + 1
            assert item.due_date == due  # unchanged by toggle

            # Simulate auto-advance cycling the item to the next occurrence
            item.complete = False
            item.due_date = next_due
            due = next_due

    def test_overdue_weekly_complete_marks_done(self):
        """Overdue weekly on Monday, completed on Thursday: marks complete, date unchanged."""
        original_due = date(2026, 3, 2)  # Monday
        fake_today = date(2026, 3, 5)  # Thursday (3 days late)
        db, lst, item, window = self._make_setup(original_due, "weekly")

        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            next_due = compute_next_due_date(original_due, "weekly", 1)
            ended = is_recurrence_ended(item, next_due)

        cmd = ToggleCompleteRecurringCommand(
            window, lst.id, item.id, original_due, next_due, 0, ended
        )
        cmd.redo()

        assert item.complete is True
        assert item.due_date == original_due  # unchanged; auto-advance cycles later


# ---------------------------------------------------------------------------
# Edge case: month arithmetic overflow
# ---------------------------------------------------------------------------
class TestMonthArithmeticEdgeCases:
    def test_every_11_months_from_february(self):
        """Every 11 months from Feb → January next year."""
        fake_today = date(2026, 2, 15)
        due = date(2026, 2, 15)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 11)
        assert result == date(2027, 1, 15)

    def test_every_12_months_equals_yearly(self):
        """Every 12 months should behave like yearly."""
        fake_today = date(2026, 3, 10)
        due = date(2026, 3, 10)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            monthly_12 = compute_next_due_date(due, "monthly", 12)
            yearly_1 = compute_next_due_date(due, "yearly", 1)
        assert monthly_12 == yearly_1

    def test_every_13_months(self):
        """Every 13 months — wraps past 12 correctly."""
        fake_today = date(2026, 1, 20)
        due = date(2026, 1, 20)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 13)
        assert result == date(2027, 2, 20)

    def test_every_24_months(self):
        """Every 24 months = every 2 years."""
        fake_today = date(2026, 6, 1)
        due = date(2026, 6, 1)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 24)
        assert result == date(2028, 6, 1)

    def test_every_6_months_from_august_31(self):
        """Every 6 months from Aug 31 → Feb 28 (clamped)."""
        fake_today = date(2026, 8, 31)
        due = date(2026, 8, 31)
        with patch("pytodo_qt.core.models.date", _mock_date(fake_today)):
            result = compute_next_due_date(due, "monthly", 6)
        assert result == date(2027, 2, 28)
