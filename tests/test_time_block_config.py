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
