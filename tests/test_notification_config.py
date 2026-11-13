"""Tests for the ``[notifications]`` configuration section.

Covers the defaults, the TOML round trip, reading sections written
before the current keys existed, values of the wrong kind, and the
conversion to the notification policy's settings.
"""

from __future__ import annotations

import tomllib
from datetime import time

import pytest

from pytodo_qt.core.config import AppConfig, NotificationConfig
from pytodo_qt.core.notification_policy import DueNowMode, PolicySettings, settings_from_config


def load(section_toml: str) -> NotificationConfig:
    """Parse a ``[notifications]`` section body as the application does."""
    data = tomllib.loads("[notifications]\n" + section_toml)
    return AppConfig.from_dict(data).notifications


def saved_section(config: AppConfig) -> dict:
    return tomllib.loads(config.to_toml())["notifications"]


class TestDefaults:
    def test_defaults(self):
        n = NotificationConfig()
        assert n.enabled is True
        assert n.summary_enabled is True
        assert n.summary_time == time(9, 0)
        assert n.preview_enabled is False
        assert n.preview_time == time(20, 0)
        assert n.lead_enabled is True
        assert n.lead_minutes == 15
        assert n.due_now == "deadlines"
        assert n.quiet_hours_enabled is True
        assert (n.quiet_start, n.quiet_end) == (time(22, 0), time(7, 0))
        assert n.quiet_allow_timed is True
        assert n.hold_during_focus is True

    def test_defaults_match_the_policy_defaults(self):
        """The configuration and the policy state the defaults separately;
        they must agree."""
        assert settings_from_config(AppConfig()) == PolicySettings()

    def test_missing_section_uses_defaults(self):
        assert AppConfig.from_dict({}).notifications == NotificationConfig()

    def test_empty_section_uses_defaults(self):
        assert load("") == NotificationConfig()


class TestRoundTrip:
    CHANGED = NotificationConfig(
        enabled=False,
        summary_enabled=False,
        summary_time=time(7, 45),
        preview_enabled=True,
        preview_time=time(19, 15),
        lead_enabled=False,
        lead_minutes=30,
        due_now="all",
        quiet_hours_enabled=False,
        quiet_start=time(23, 30),
        quiet_end=time(6, 15),
        quiet_allow_timed=False,
        hold_during_focus=False,
    )

    def test_every_field_survives(self):
        original = AppConfig()
        original.notifications = self.CHANGED
        restored = AppConfig.from_dict(tomllib.loads(original.to_toml()))
        assert restored.notifications == self.CHANGED

    def test_times_are_written_as_hour_and_minute_strings(self):
        config = AppConfig()
        config.notifications = self.CHANGED
        section = saved_section(config)
        assert section["summary_time"] == "07:45"
        assert section["preview_time"] == "19:15"
        assert section["quiet_start"] == "23:30"
        assert section["quiet_end"] == "06:15"

    def test_written_keys(self):
        assert set(saved_section(AppConfig())) == {
            "enabled",
            "summary_enabled",
            "summary_time",
            "preview_enabled",
            "preview_time",
            "lead_enabled",
            "lead_minutes",
            "due_now",
            "quiet_hours_enabled",
            "quiet_start",
            "quiet_end",
            "quiet_allow_timed",
            "hold_during_focus",
        }


class TestSectionsFromBeforeTheseKeys:
    def test_check_hour_becomes_the_summary_time(self):
        assert load("check_hour = 7").summary_time == time(7, 0)

    def test_check_hour_at_midnight(self):
        assert load("check_hour = 0").summary_time == time(0, 0)

    def test_check_hour_out_of_range_is_ignored(self):
        assert load("check_hour = 24").summary_time == time(9, 0)

    def test_both_content_options_off_turn_the_summary_off(self):
        n = load("notify_overdue = false\nnotify_due_today = false")
        assert n.summary_enabled is False

    @pytest.mark.parametrize("still_on", ["notify_overdue", "notify_due_today"])
    def test_one_content_option_off_leaves_the_summary_on(self, still_on):
        other = "notify_due_today" if still_on == "notify_overdue" else "notify_overdue"
        assert load(f"{still_on} = true\n{other} = false").summary_enabled is True

    def test_one_content_option_alone_and_off_leaves_the_summary_on(self):
        assert load("notify_overdue = false").summary_enabled is True

    def test_upcoming_days_is_ignored(self):
        assert load("upcoming_days = 14") == NotificationConfig()

    def test_master_switch_carries_over(self):
        assert load("enabled = false").enabled is False

    def test_a_whole_old_section(self):
        n = load(
            "enabled = true\nupcoming_days = 5\ncheck_hour = 6\n"
            "notify_overdue = false\nnotify_due_today = true"
        )
        assert n == NotificationConfig(summary_time=time(6, 0))

    def test_current_key_wins_over_the_key_it_replaces(self):
        n = load(
            'check_hour = 6\nsummary_time = "08:30"\n'
            "notify_overdue = false\nnotify_due_today = false\nsummary_enabled = true"
        )
        assert n.summary_time == time(8, 30)
        assert n.summary_enabled is True

    def test_old_keys_are_not_written_back(self):
        config = AppConfig.from_dict(
            tomllib.loads(
                "[notifications]\nupcoming_days = 5\ncheck_hour = 6\n"
                "notify_overdue = false\nnotify_due_today = false\n"
            )
        )
        section = saved_section(config)
        for old_key in ("upcoming_days", "check_hour", "notify_overdue", "notify_due_today"):
            assert old_key not in section
        assert section["summary_time"] == "06:00"
        assert section["summary_enabled"] is False

    def test_old_attributes_are_gone(self):
        n = NotificationConfig()
        for old_name in ("upcoming_days", "check_hour", "notify_overdue", "notify_due_today"):
            assert not hasattr(n, old_name)


class TestValuesOfTheWrongKind:
    @pytest.mark.parametrize(
        "value", ['"9am"', '"25:00"', '"09:60"', '""', "9", "true", '"09:00:00"']
    )
    def test_unreadable_time_falls_back_to_the_default(self, value):
        assert load(f"summary_time = {value}").summary_time == time(9, 0)

    def test_unreadable_time_does_not_disturb_the_other_keys(self):
        n = load('quiet_start = "late"\nquiet_end = "06:00"\nlead_minutes = 20')
        assert (n.quiet_start, n.quiet_end, n.lead_minutes) == (time(22, 0), time(6, 0), 20)

    def test_single_digit_hour_is_read(self):
        assert load('summary_time = "7:05"').summary_time == time(7, 5)

    def test_surrounding_spaces_are_ignored(self):
        assert load('summary_time = " 07:05 "').summary_time == time(7, 5)

    def test_toml_local_time_is_read(self):
        """An unquoted time is a TOML local time, not a string."""
        assert load("quiet_end = 06:30:00").quiet_end == time(6, 30)

    def test_toml_local_time_drops_its_seconds(self):
        assert load("quiet_end = 06:30:45").quiet_end == time(6, 30)

    @pytest.mark.parametrize("value", ['"yes"', "1", '"true"'])
    def test_flag_that_is_not_true_or_false_falls_back(self, value):
        assert load(f"lead_enabled = {value}").lead_enabled is True
        assert load(f"enabled = {value}").enabled is True

    @pytest.mark.parametrize("value", ['"15"', "15.5", "true"])
    def test_lead_minutes_that_is_not_a_whole_number_falls_back(self, value):
        assert load(f"lead_minutes = {value}").lead_minutes == 15

    @pytest.mark.parametrize(("value", "used"), [(0, 1), (-5, 1), (121, 120), (600, 120)])
    def test_lead_minutes_outside_the_range_uses_the_nearest_limit(self, value, used):
        assert load(f"lead_minutes = {value}").lead_minutes == used

    @pytest.mark.parametrize("value", [1, 120])
    def test_lead_minutes_at_the_limits(self, value):
        assert load(f"lead_minutes = {value}").lead_minutes == value

    @pytest.mark.parametrize("value", ['"always"', '"Deadlines"', "true", "1"])
    def test_unknown_due_now_mode_falls_back(self, value):
        assert load(f"due_now = {value}").due_now == "deadlines"

    @pytest.mark.parametrize("mode", ["deadlines", "all", "off"])
    def test_every_due_now_mode_is_read(self, mode):
        assert load(f'due_now = "{mode}"').due_now == mode


class TestSettingsFromConfig:
    def test_every_field_is_carried_over(self):
        config = AppConfig()
        config.notifications = TestRoundTrip.CHANGED
        config.database.day_start_hour = 4
        assert settings_from_config(config) == PolicySettings(
            enabled=False,
            summary_enabled=False,
            summary_time=time(7, 45),
            preview_enabled=True,
            preview_time=time(19, 15),
            lead_enabled=False,
            lead_minutes=30,
            due_now=DueNowMode.ALL,
            day_start_hour=4,
            quiet_hours_enabled=False,
            quiet_start=time(23, 30),
            quiet_end=time(6, 15),
            quiet_allow_timed=False,
            hold_during_focus=False,
        )

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [("deadlines", DueNowMode.DEADLINES), ("all", DueNowMode.ALL), ("off", DueNowMode.OFF)],
    )
    def test_due_now_modes(self, mode, expected):
        config = AppConfig()
        config.notifications.due_now = mode
        assert settings_from_config(config).due_now is expected

    def test_unknown_due_now_mode_set_in_code_means_deadlines(self):
        config = AppConfig()
        config.notifications.due_now = "sometimes"
        assert settings_from_config(config).due_now is DueNowMode.DEADLINES

    def test_an_old_section_reaches_the_policy(self):
        config = AppConfig.from_dict(
            tomllib.loads(
                "[notifications]\ncheck_hour = 6\n"
                "notify_overdue = false\nnotify_due_today = false\n"
            )
        )
        settings = settings_from_config(config)
        assert settings.summary_time == time(6, 0)
        assert settings.summary_enabled is False


class TestPreviewKeys:
    def test_read_from_a_section(self):
        n = load('preview_enabled = true\npreview_time = "18:30"')
        assert n.preview_enabled is True
        assert n.preview_time == time(18, 30)

    def test_a_section_without_them_leaves_the_preview_off(self):
        n = load("enabled = true\ncheck_hour = 6")
        assert n.preview_enabled is False
        assert n.preview_time == time(20, 0)

    def test_unreadable_time_falls_back_to_the_default(self):
        assert load('preview_time = "late"').preview_time == time(20, 0)

    def test_flag_that_is_not_true_or_false_falls_back(self):
        assert load('preview_enabled = "yes"').preview_enabled is False
