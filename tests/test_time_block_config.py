"""Tests for TimeBlockConfig and NotificationConfig — TOML round-trip + defaults."""

from __future__ import annotations

from pytodo_qt.core.config import (
    AppConfig,
    NotificationConfig,
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


class TestNotificationConfigDefaults:
    def test_defaults(self):
        n = NotificationConfig()
        assert n.enabled is True
        assert n.upcoming_days == 3
        assert n.check_hour == 9
        assert n.notify_overdue is True
        assert n.notify_due_today is True


class TestNotificationConfigTomlRoundTrip:
    def test_round_trip(self):
        original = AppConfig()
        original.notifications = NotificationConfig(
            enabled=False,
            upcoming_days=7,
            check_hour=8,
            notify_overdue=False,
            notify_due_today=True,
        )
        toml_str = original.to_toml()

        import tomllib

        parsed = tomllib.loads(toml_str)
        restored = AppConfig.from_dict(parsed)

        assert restored.notifications.enabled is False
        assert restored.notifications.upcoming_days == 7
        assert restored.notifications.check_hour == 8
        assert restored.notifications.notify_overdue is False
        assert restored.notifications.notify_due_today is True

    def test_missing_section_uses_defaults(self):
        c = AppConfig.from_dict({})
        assert c.notifications.enabled is True
        assert c.notifications.upcoming_days == 3
