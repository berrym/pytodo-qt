"""Tests for the main window's once-a-minute housekeeping.

Methods are tested as unbound methods against a mock ``MainWindow`` — the
pattern ``test_detail_panel_toggle.py`` uses — to avoid the cost of a full
MainWindow + Database + config stack.
"""

from __future__ import annotations

from datetime import datetime, time
from unittest.mock import MagicMock

from pytodo_qt.core.config import AppConfig
from pytodo_qt.core.notification_policy import DueNowMode
from pytodo_qt.gui import main_window as main_window_module
from pytodo_qt.gui.main_window import MainWindow


class TestMinuteTick:
    def test_notifications_are_evaluated_before_recurring_items_advance(self):
        """An overdue recurring item moves to its next occurrence in
        _check_timed_overdue. Evaluating notifications after that would
        miss the alert for the occurrence that just came due."""
        window = MagicMock()
        calls: list[str] = []
        window._evaluate_task_notifications.side_effect = lambda: calls.append("notify")
        window._check_timed_overdue.side_effect = lambda: calls.append("advance")
        window._check_lan_address.side_effect = lambda: calls.append("lan")

        MainWindow._on_minute_tick(window)

        assert calls == ["notify", "advance", "lan"]

    def test_tick_re_arms_the_timer(self):
        window = MagicMock()
        MainWindow._on_minute_tick(window)
        window._arm_minute_timer.assert_called_once_with()

    def test_web_pin_is_refreshed_when_the_server_runs(self):
        window = MagicMock()
        window._config.web.port = 8080
        window._web_server.pairing_pin = "123456"
        MainWindow._on_minute_tick(window)
        window.status_bar_widget.set_web_status.assert_called_once_with(
            True, port=8080, pin="123456"
        )

    def test_web_pin_is_left_alone_without_a_server(self):
        window = MagicMock()
        window._web_server = None
        MainWindow._on_minute_tick(window)
        window.status_bar_widget.set_web_status.assert_not_called()


class TestArmMinuteTimer:
    def _armed_interval(self, monkeypatch, now: datetime) -> int:
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        monkeypatch.setattr("datetime.datetime", FixedDatetime)
        window = MagicMock()
        MainWindow._arm_minute_timer(window)
        (interval,) = window._minute_timer.start.call_args.args
        return interval

    def test_fires_just_after_the_next_minute(self, monkeypatch):
        interval = self._armed_interval(monkeypatch, datetime(2026, 11, 12, 14, 44, 20))
        assert interval == 40_000 + 50

    def test_accounts_for_sub_second_time(self, monkeypatch):
        interval = self._armed_interval(monkeypatch, datetime(2026, 11, 12, 14, 44, 59, 900_000))
        assert interval == 100 + 50

    def test_on_the_boundary_waits_a_full_minute(self, monkeypatch):
        interval = self._armed_interval(monkeypatch, datetime(2026, 11, 12, 14, 45, 0))
        assert interval == 60_000 + 50


class TestEvaluateTaskNotifications:
    def test_a_failure_does_not_escape_the_tick(self):
        window = MagicMock()
        window._task_notifier.evaluate.side_effect = RuntimeError("storage unavailable")
        MainWindow._evaluate_task_notifications(window)
        window._task_notifier.evaluate.assert_called_once_with()


class TestNotificationPolicySettings:
    def _settings(self, **notification_fields):
        config = AppConfig()
        for name, value in notification_fields.items():
            setattr(config.notifications, name, value)
        window = MagicMock()
        window._config_manager.config = config
        return MainWindow._notification_policy_settings(window), config

    def test_defaults(self):
        settings, _ = self._settings()
        assert settings.enabled
        assert settings.summary_enabled
        assert settings.summary_time == time(9)
        assert settings.lead_enabled
        assert settings.lead_minutes == 15
        assert settings.due_now is DueNowMode.DEADLINES
        assert settings.day_start_hour == 0

    def test_daily_check_time_sets_the_summary_time(self):
        settings, _ = self._settings(check_hour=7)
        assert settings.summary_time == time(7)

    def test_master_switch(self):
        settings, _ = self._settings(enabled=False)
        assert not settings.enabled

    def test_summary_stays_on_while_either_content_option_is_on(self):
        assert self._settings(notify_overdue=False)[0].summary_enabled
        assert self._settings(notify_due_today=False)[0].summary_enabled

    def test_summary_is_off_when_both_content_options_are_off(self):
        settings, _ = self._settings(notify_overdue=False, notify_due_today=False)
        assert not settings.summary_enabled

    def test_day_start_follows_the_database_setting(self):
        config = AppConfig()
        config.database.day_start_hour = 4
        window = MagicMock()
        window._config_manager.config = config
        assert MainWindow._notification_policy_settings(window).day_start_hour == 4


class TestCheckLanAddress:
    def test_reports_a_changed_address(self, monkeypatch):
        monkeypatch.setattr("pytodo_qt.core.network.get_lan_ip", lambda: "192.168.1.20")
        window = MagicMock()
        window._last_known_ip = "192.168.1.10"
        window.tr.side_effect = lambda text: text

        MainWindow._check_lan_address(window)

        assert window._last_known_ip == "192.168.1.20"
        window.status_bar_widget.show_message.assert_called_once()

    def test_silent_when_unchanged(self, monkeypatch):
        monkeypatch.setattr("pytodo_qt.core.network.get_lan_ip", lambda: "192.168.1.10")
        window = MagicMock()
        window._last_known_ip = "192.168.1.10"

        MainWindow._check_lan_address(window)

        window.status_bar_widget.show_message.assert_not_called()

    def test_silent_when_no_address_is_available(self, monkeypatch):
        monkeypatch.setattr("pytodo_qt.core.network.get_lan_ip", lambda: None)
        window = MagicMock()
        window._last_known_ip = "192.168.1.10"

        MainWindow._check_lan_address(window)

        assert window._last_known_ip == "192.168.1.10"
        window.status_bar_widget.show_message.assert_not_called()


def test_old_notification_entry_points_are_gone():
    assert not hasattr(MainWindow, "_check_due_notifications")
    assert not hasattr(main_window_module, "_DAILY_NOTIFICATION_KIND")
