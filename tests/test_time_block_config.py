"""Tests for TimeBlockConfig — TOML round-trip + defaults."""

from __future__ import annotations

from datetime import date, datetime

from pytodo_qt.core.config import (
    AppConfig,
    TimeBlockConfig,
)


class TestTimeBlockConfigDefaults:
    def test_default_morning(self):
        c = TimeBlockConfig()
        assert c.morning_start == 6
        assert c.morning_end == 12

    def test_default_afternoon(self):
        c = TimeBlockConfig()
        assert c.afternoon_start == 12
        assert c.afternoon_end == 17

    def test_default_evening(self):
        c = TimeBlockConfig()
        assert c.evening_start == 17
        assert c.evening_end == 21

    def test_default_night_crosses_midnight(self):
        c = TimeBlockConfig()
        assert c.night_start == 21
        assert c.night_end == 6  # crosses midnight


class TestTimeBlockConfigCustom:
    def test_custom_values(self):
        c = TimeBlockConfig(
            morning_start=5,
            morning_end=11,
            afternoon_start=11,
            afternoon_end=18,
            evening_start=18,
            evening_end=22,
            night_start=22,
            night_end=5,
        )
        assert c.morning_start == 5
        assert c.evening_end == 22


class TestTimeBlockConfigTomlRoundTrip:
    def test_default_round_trip(self):
        original = AppConfig()
        toml_str = original.to_toml()
        # The defaults should serialize to TOML
        assert "[time_blocks]" in toml_str

    def test_custom_round_trip(self):
        original = AppConfig()
        original.time_blocks = TimeBlockConfig(
            morning_start=4,
            morning_end=11,
            afternoon_start=11,
            afternoon_end=16,
            evening_start=16,
            evening_end=20,
            night_start=20,
            night_end=4,
        )
        toml_str = original.to_toml()

        import tomllib

        parsed = tomllib.loads(toml_str)
        restored = AppConfig.from_dict(parsed)

        assert restored.time_blocks.morning_start == 4
        assert restored.time_blocks.morning_end == 11
        assert restored.time_blocks.afternoon_start == 11
        assert restored.time_blocks.afternoon_end == 16
        assert restored.time_blocks.evening_start == 16
        assert restored.time_blocks.evening_end == 20
        assert restored.time_blocks.night_start == 20
        assert restored.time_blocks.night_end == 4

    def test_missing_section_uses_defaults(self):
        c = AppConfig.from_dict({})
        assert c.time_blocks.morning_start == 6
        assert c.time_blocks.morning_end == 12

    def test_partial_section_uses_defaults_for_missing(self):
        c = AppConfig.from_dict({"time_blocks": {"morning_start": 5}})
        assert c.time_blocks.morning_start == 5
        assert c.time_blocks.morning_end == 12  # default


class TestBlockForHourDefaults:
    """The default config covers all 24 hours. Each range is split at
    its midpoint into early and late halves, matching the vocabulary
    users speak ("early morning", "late afternoon", etc.)."""

    def test_morning_early(self):
        # Morning range is [6, 12), midpoint 9 → hours 6-8 are early.
        c = TimeBlockConfig()
        assert c.block_for_hour(6) == "early_morning"
        assert c.block_for_hour(7) == "early_morning"
        assert c.block_for_hour(8) == "early_morning"

    def test_morning_late(self):
        c = TimeBlockConfig()
        assert c.block_for_hour(9) == "late_morning"
        assert c.block_for_hour(10) == "late_morning"
        assert c.block_for_hour(11) == "late_morning"

    def test_afternoon_split(self):
        # Afternoon range is [12, 17), midpoint 14.5 → hours 12-14
        # are early_afternoon, hours 15-16 are late_afternoon.
        c = TimeBlockConfig()
        assert c.block_for_hour(12) == "early_afternoon"
        assert c.block_for_hour(14) == "early_afternoon"
        assert c.block_for_hour(15) == "late_afternoon"
        assert c.block_for_hour(16) == "late_afternoon"

    def test_evening_split(self):
        # Evening range is [17, 21), midpoint 19 → hours 17-18 are
        # early_evening, hours 19-20 are late_evening.
        c = TimeBlockConfig()
        assert c.block_for_hour(17) == "early_evening"
        assert c.block_for_hour(18) == "early_evening"
        assert c.block_for_hour(19) == "late_evening"
        assert c.block_for_hour(20) == "late_evening"

    def test_night_crosses_midnight(self):
        # Night range crosses midnight: [21, 24) then [0, 6).
        # Span is 9 hours, midpoint 4.5 hours in = hour 1.5, so
        # hours 21/22/23/0/1 are early (night) and hours 2/3/4/5 are
        # late (late_night).
        c = TimeBlockConfig()
        assert c.block_for_hour(21) == "night"
        assert c.block_for_hour(22) == "night"
        assert c.block_for_hour(23) == "night"
        assert c.block_for_hour(0) == "night"
        assert c.block_for_hour(1) == "night"
        assert c.block_for_hour(2) == "late_night"
        assert c.block_for_hour(3) == "late_night"
        assert c.block_for_hour(5) == "late_night"

    def test_wraparound(self):
        # Hours outside 0-23 are normalized modulo 24.
        c = TimeBlockConfig()
        assert c.block_for_hour(24) == c.block_for_hour(0)
        assert c.block_for_hour(30) == c.block_for_hour(6)


class TestBlockForHourCustom:
    def test_custom_range(self):
        # Shifted schedule — early riser.
        c = TimeBlockConfig(
            morning_start=4,
            morning_end=10,
            afternoon_start=10,
            afternoon_end=15,
            evening_start=15,
            evening_end=19,
            night_start=19,
            night_end=4,
        )
        # Morning [4, 10), midpoint 7.
        assert c.block_for_hour(4) == "early_morning"
        assert c.block_for_hour(6) == "early_morning"
        assert c.block_for_hour(7) == "late_morning"
        assert c.block_for_hour(9) == "late_morning"
        # Afternoon [10, 15), midpoint 12.5.
        assert c.block_for_hour(10) == "early_afternoon"
        assert c.block_for_hour(12) == "early_afternoon"
        assert c.block_for_hour(13) == "late_afternoon"
        # Evening [15, 19), midpoint 17.
        assert c.block_for_hour(15) == "early_evening"
        assert c.block_for_hour(17) == "late_evening"
        # Night [19, 24) ∪ [0, 4) spans 9 hours.
        assert c.block_for_hour(19) == "night"
        assert c.block_for_hour(3) == "late_night"


class TestBlockRange:
    """block_range resolves a named block to minute offsets from the
    midnight that starts the block's day."""

    def test_parent_blocks_span_their_configured_range(self):
        c = TimeBlockConfig()
        assert c.block_range("morning") == (6 * 60, 12 * 60)
        assert c.block_range("afternoon") == (12 * 60, 17 * 60)
        assert c.block_range("evening") == (17 * 60, 21 * 60)

    def test_night_runs_past_midnight(self):
        # 21:00 to 06:00 the next day: the end is 30 hours after the
        # midnight that starts the block's day.
        c = TimeBlockConfig()
        assert c.block_range("night") == (21 * 60, 30 * 60)

    def test_early_and_late_split_at_the_midpoint(self):
        c = TimeBlockConfig()
        assert c.block_range("early_morning") == (6 * 60, 9 * 60)
        assert c.block_range("late_morning") == (9 * 60, 12 * 60)
        assert c.block_range("early_evening") == (17 * 60, 19 * 60)
        assert c.block_range("late_evening") == (19 * 60, 21 * 60)

    def test_odd_length_range_splits_on_the_half_hour(self):
        # Afternoon is five hours long, so its midpoint is 14:30 —
        # the same boundary block_for_hour uses (hours 12-14 early,
        # 15-16 late).
        c = TimeBlockConfig()
        assert c.block_range("early_afternoon") == (12 * 60, 14 * 60 + 30)
        assert c.block_range("late_afternoon") == (14 * 60 + 30, 17 * 60)

    def test_late_night_starts_after_midnight(self):
        # Night is nine hours from 21:00; its second half starts at
        # 01:30 on the following calendar day.
        c = TimeBlockConfig()
        assert c.block_range("late_night") == (25 * 60 + 30, 30 * 60)

    def test_fixed_bands(self):
        c = TimeBlockConfig()
        assert c.block_range("noon") == (11 * 60 + 30, 12 * 60 + 30)
        assert c.block_range("midnight") == (23 * 60 + 30, 24 * 60 + 30)

    def test_fixed_bands_ignore_configuration(self):
        c = TimeBlockConfig(morning_start=4, morning_end=10, afternoon_start=10)
        assert c.block_range("noon") == (11 * 60 + 30, 12 * 60 + 30)

    def test_custom_configuration(self):
        c = TimeBlockConfig(
            morning_start=4,
            morning_end=10,
            afternoon_start=10,
            afternoon_end=15,
            evening_start=15,
            evening_end=19,
            night_start=19,
            night_end=4,
        )
        assert c.block_range("morning") == (4 * 60, 10 * 60)
        assert c.block_range("late_afternoon") == (12 * 60 + 30, 15 * 60)
        assert c.block_range("night") == (19 * 60, 28 * 60)
        assert c.block_range("late_night") == (23 * 60 + 30, 28 * 60)

    def test_night_that_does_not_cross_midnight(self):
        c = TimeBlockConfig(night_start=20, night_end=23)
        assert c.block_range("night") == (20 * 60, 23 * 60)
        assert c.block_range("late_night") == (21 * 60 + 30, 23 * 60)

    def test_unknown_block_is_none(self):
        c = TimeBlockConfig()
        assert c.block_range("teatime") is None
        assert c.block_range("early_teatime") is None
        assert c.block_range("") is None

    def test_zero_length_range_is_none(self):
        c = TimeBlockConfig(evening_start=18, evening_end=18)
        assert c.block_range("evening") is None
        assert c.block_range("late_evening") is None

    def test_agrees_with_block_for_hour(self):
        # Every hour falls inside the range block_range reports for the
        # name block_for_hour gives it. block_for_hour uses "night" for
        # the first half of the night only; block_range("night") is the
        # whole range, which still contains those hours.
        c = TimeBlockConfig()
        for hour in range(24):
            name = c.block_for_hour(hour)
            rng = c.block_range(name)
            assert rng is not None, name
            start, end = rng
            minute = hour * 60
            assert start <= minute < end or start <= minute + 24 * 60 < end, (hour, name)


class TestNextOccurrence:
    """next_occurrence dates a block named without a date: today while
    the block is still to come or under way, tomorrow once it has ended."""

    DAY = date(2026, 3, 11)

    def _at(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 3, 11, hour, minute)

    def test_before_the_block(self):
        assert TimeBlockConfig().next_occurrence("afternoon", self._at(9)) == self.DAY

    def test_during_the_block(self):
        assert TimeBlockConfig().next_occurrence("afternoon", self._at(16, 59)) == self.DAY

    def test_at_the_end_of_the_block(self):
        assert TimeBlockConfig().next_occurrence("afternoon", self._at(17)) == date(2026, 3, 12)

    def test_after_the_block(self):
        assert TimeBlockConfig().next_occurrence("morning", self._at(13)) == date(2026, 3, 12)

    def test_half_block(self):
        c = TimeBlockConfig()
        # Early afternoon is 12:00-14:30.
        assert c.next_occurrence("early_afternoon", self._at(14, 29)) == self.DAY
        assert c.next_occurrence("early_afternoon", self._at(14, 30)) == date(2026, 3, 12)

    def test_block_crossing_midnight_never_ends_today(self):
        c = TimeBlockConfig()
        assert c.next_occurrence("night", self._at(23, 59)) == self.DAY
        assert c.next_occurrence("late_night", self._at(0, 30)) == self.DAY

    def test_fixed_blocks(self):
        c = TimeBlockConfig()
        assert c.next_occurrence("noon", self._at(12, 29)) == self.DAY
        assert c.next_occurrence("noon", self._at(12, 30)) == date(2026, 3, 12)

    def test_custom_boundaries(self):
        c = TimeBlockConfig(evening_start=18, evening_end=22)
        assert c.next_occurrence("evening", self._at(21, 30)) == self.DAY
        assert c.next_occurrence("evening", self._at(22)) == date(2026, 3, 12)

    def test_unknown_block(self):
        assert TimeBlockConfig().next_occurrence("teatime", self._at(9)) is None
