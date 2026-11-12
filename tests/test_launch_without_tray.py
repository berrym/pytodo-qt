"""Native notifications are set up on a desktop without a system tray.

The desktop notifier does not depend on the tray: a desktop with no tray
still has a notification service. Every notification path reads the
main window's notifier, so a window constructed without one fails each
time it tries to notify, and the failure is only logged.

The real-application launch shared with ``test_clean_exit.py`` runs
offscreen, where no system tray exists.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from pytodo_qt.gui import main_window as main_window_module
from pytodo_qt.gui.main_window import MainWindow


class TestRealLaunch:
    def test_the_launch_had_no_system_tray(self, exit_report: tuple[int, dict, str]) -> None:
        _code, report, stderr = exit_report
        assert report.get("system_tray_available") is False, f"stderr tail:\n{stderr}"

    def test_the_notifier_is_set_up_all_the_same(self, exit_report: tuple[int, dict, str]) -> None:
        _code, report, _stderr = exit_report
        assert report.get("os_notifier_set_up") is True


@pytest.fixture
def fake_desktop_notifier(monkeypatch):
    """Stand in for the desktop-notifier package; returns the stub module."""
    module = types.ModuleType("desktop_notifier")
    module.DesktopNotifier = MagicMock(name="DesktopNotifier")  # type: ignore[attr-defined]
    module.Icon = MagicMock(name="Icon")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "desktop_notifier", module)
    return module


class TestSetupOsNotifier:
    def test_creates_the_notifier(self, fake_desktop_notifier):
        window = MagicMock()
        MainWindow._setup_os_notifier(window)
        assert window._notifier is fake_desktop_notifier.DesktopNotifier.return_value
        kwargs = fake_desktop_notifier.DesktopNotifier.call_args.kwargs
        assert kwargs["app_name"] == "PyTodo-Qt"

    def test_missing_package_leaves_no_notifier(self, monkeypatch):
        # A None entry makes the import raise ImportError.
        monkeypatch.setitem(sys.modules, "desktop_notifier", None)
        window = MagicMock()
        MainWindow._setup_os_notifier(window)
        assert window._notifier is None

    def test_failing_constructor_leaves_no_notifier(self, fake_desktop_notifier):
        fake_desktop_notifier.DesktopNotifier.side_effect = RuntimeError("no session bus")
        window = MagicMock()
        MainWindow._setup_os_notifier(window)
        assert window._notifier is None


class TestSetupTrayIconWithoutATray:
    def test_leaves_the_notifier_alone(self, monkeypatch):
        tray_class = MagicMock(name="QSystemTrayIcon")
        tray_class.isSystemTrayAvailable.return_value = False
        monkeypatch.setattr(main_window_module, "QSystemTrayIcon", tray_class)
        notifier = object()
        window = MagicMock()
        window._notifier = notifier

        MainWindow._setup_tray_icon(window)

        assert window.tray_icon is None
        assert window._notifier is notifier
        tray_class.assert_not_called()


def test_the_notifier_is_created_before_the_tray_icon():
    """Construction order: the tray setup can return early, so nothing
    that notifications need may be created inside or after it."""
    names = MainWindow.__init__.__code__.co_names
    assert names.index("_setup_os_notifier") < names.index("_setup_tray_icon")
