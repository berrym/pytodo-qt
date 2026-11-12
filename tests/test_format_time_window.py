"""Tests for _format_time_window — time window display formatting.

Covers specific times, ad-hoc ranges, named time blocks, and edge cases.
"""

from __future__ import annotations

from datetime import time

import pytest

from pytodo_qt.core.models import _format_time_window


class TestNoTime:
    def test_all_none(self):
        assert _format_time_window(None, None, None, "24h") == ""

    def test_only_block_no_times(self):
        # A block returns "(Label, range)" or just "(Label)" depending on config
        result = _format_time_window(None, None, "morning", "24h")
        assert result.startswith(" (")
        assert "Morning" in result


class TestSpecificTime:
    def test_24h_format(self):
        result = _format_time_window(time(15, 30), None, None, "24h")
        assert result == " 15:30"

    def test_12h_format(self):
        result = _format_time_window(time(15, 30), None, None, "12h")
        assert "3:30" in result
        assert "PM" in result.upper() or "pm" in result.lower()

    def test_morning_24h(self):
        result = _format_time_window(time(9, 0), None, None, "24h")
        assert result == " 09:00"

    def test_midnight_24h(self):
        result = _format_time_window(time(0, 0), None, None, "24h")
        assert result == " 00:00"


class TestTimeRange:
    def test_range_24h(self):
        result = _format_time_window(time(14, 0), time(16, 0), None, "24h")
        assert "14:00" in result
        assert "16:00" in result
        assert "-" in result

    def test_range_12h(self):
        result = _format_time_window(time(14, 0), time(16, 0), None, "12h")
        assert "2:00" in result
        assert "4:00" in result

    def test_range_morning_to_afternoon(self):
        result = _format_time_window(time(9, 30), time(17, 0), None, "24h")
        assert "09:30" in result
        assert "17:00" in result


class TestTimeBlocks:
    def test_morning_block(self):
        result = _format_time_window(None, None, "morning", "24h")
        assert "Morning" in result
        # Should include resolved range
        assert "-" in result

    def test_afternoon_block(self):
        result = _format_time_window(None, None, "afternoon", "24h")
        assert "Afternoon" in result

    def test_evening_block(self):
        result = _format_time_window(None, None, "evening", "24h")
        assert "Evening" in result

    def test_night_block(self):
        result = _format_time_window(None, None, "night", "24h")
        assert "Night" in result

    def test_early_morning_derived(self):
        result = _format_time_window(None, None, "early_morning", "24h")
        assert "Early Morning" in result

    def test_late_afternoon_derived(self):
        result = _format_time_window(None, None, "late_afternoon", "24h")
        assert "Late Afternoon" in result

    def test_unknown_block_falls_back_to_label(self):
        result = _format_time_window(None, None, "unknown_block", "24h")
        assert "Unknown Block" in result


class TestTimeBlockRanges:
    """Named blocks display the range the configuration resolves them to,
    through the same resolver reminders use."""

    @pytest.fixture(autouse=True)
    def _default_blocks(self, monkeypatch):
        from pytodo_qt.core import config as config_module

        monkeypatch.setattr(config_module, "get_config", config_module.AppConfig)

    def test_parent_block(self):
        assert _format_time_window(None, None, "evening", "24h") == " (Evening, 17:00-21:00)"

    def test_early_half(self):
        assert _format_time_window(None, None, "early_morning", "24h") == (
            " (Early Morning, 06:00-09:00)"
        )

    def test_odd_length_range_splits_on_the_half_hour(self):
        assert _format_time_window(None, None, "late_afternoon", "24h") == (
            " (Late Afternoon, 14:30-17:00)"
        )
        assert _format_time_window(None, None, "early_afternoon", "24h") == (
            " (Early Afternoon, 12:00-14:30)"
        )

    def test_night_wraps_past_midnight(self):
        assert _format_time_window(None, None, "night", "24h") == " (Night, 21:00-06:00)"

    def test_late_night_starts_after_midnight(self):
        """The midpoint of 21:00-06:00 is 01:30, not the 13:00 an
        hour-of-day average gives."""
        assert _format_time_window(None, None, "late_night", "24h") == (
            " (Late Night, 01:30-06:00)"
        )

    def test_fixed_bands_show_their_range(self):
        assert _format_time_window(None, None, "noon", "24h") == " (Noon, 11:30-12:30)"
        assert _format_time_window(None, None, "midnight", "24h") == " (Midnight, 23:30-00:30)"

    def test_twelve_hour_format(self):
        assert _format_time_window(None, None, "late_night", "12h") == (
            " (Late Night, 1:30 AM-6:00 AM)"
        )

    def test_unknown_block_shows_only_its_label(self):
        assert _format_time_window(None, None, "teatime", "24h") == " (Teatime)"

    def test_unreadable_configuration_shows_only_the_label(self, monkeypatch):
        from pytodo_qt.core import config as config_module

        def broken():
            raise OSError("config unreadable")

        monkeypatch.setattr(config_module, "get_config", broken)
        assert _format_time_window(None, None, "evening", "24h") == " (Evening)"


class TestPrecedence:
    def test_specific_time_takes_precedence_over_block(self):
        """A clock time is shown in place of the block, as it is used in
        place of the block for reminders and on the calendar."""
        result = _format_time_window(time(9, 0), None, "morning", "24h")
        assert result == " 09:00"

    def test_range_takes_precedence_over_block(self):
        result = _format_time_window(time(9, 0), time(11, 0), "morning", "24h")
        assert result == " 09:00-11:00"

    def test_block_is_shown_when_there_is_no_time(self):
        result = _format_time_window(None, None, "morning", "24h")
        assert "Morning" in result

    def test_range_takes_precedence_over_single_time(self):
        result = _format_time_window(time(14, 0), time(16, 0), None, "24h")
        assert "14:00" in result
        assert "16:00" in result


# ---------------------------------------------------------------------------
# logical_today
# ---------------------------------------------------------------------------


class TestLogicalToday:
    def test_zero_hour_returns_today(self, monkeypatch):
        from datetime import date as _date

        from pytodo_qt.core import models

        monkeypatch.setattr(models, "date", _date)
        result = models.logical_today(day_start_hour=0)
        assert result == _date.today()

    def test_negative_threshold_no_shift(self):
        from pytodo_qt.core.models import logical_today

        # day_start_hour=0 never shifts
        result = logical_today(day_start_hour=0)
        from datetime import date as _date

        assert result == _date.today()

    def test_with_threshold_morning(self, monkeypatch):
        """If current hour >= threshold, returns today."""
        from datetime import date as _date
        from datetime import datetime as _dt

        from pytodo_qt.core import models

        class FakeDt:
            @staticmethod
            def now():
                return _dt(2026, 4, 9, 10, 0)  # 10am

        monkeypatch.setattr(models, "datetime", FakeDt)
        result = models.logical_today(day_start_hour=4)
        assert result == _date.today()

    def test_with_threshold_late_night(self, monkeypatch):
        """If current hour < threshold, returns yesterday."""
        from datetime import date as _date
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        from pytodo_qt.core import models

        class FakeDt:
            @staticmethod
            def now():
                return _dt(2026, 4, 9, 2, 0)  # 2am

        monkeypatch.setattr(models, "datetime", FakeDt)
        result = models.logical_today(day_start_hour=4)
        assert result == _date.today() - _td(days=1)
