"""Tests for the notification dispatch decision (#43).

Covers ``_prefer_os_notification`` — the pure function that picks
between the OS native notification path (desktop-notifier) and the
in-app overlay based on the current platform and the availability of
the notifier instance. The helper is deliberately small and testable
without Qt or async machinery.
"""

from __future__ import annotations

import pytest

from pytodo_qt.gui.main_window import _prefer_os_notification


class TestPreferOsNotificationPlatformBranches:
    """Linux and Windows prefer the OS path; macOS prefers the overlay."""

    @pytest.mark.parametrize(
        "platform",
        ["linux", "linux2", "win32", "cygwin", "freebsd", "freebsd13", "openbsd7"],
    )
    def test_non_darwin_with_notifier_prefers_os(self, platform):
        assert _prefer_os_notification(notifier_available=True, platform=platform) is True

    def test_darwin_with_notifier_prefers_overlay(self):
        # macOS is special-cased because the OS notification on an
        # ad-hoc-signed bundle shows a generic placeholder rather than
        # the title and body — overlay is the better UX there.
        assert _prefer_os_notification(notifier_available=True, platform="darwin") is False


class TestPreferOsNotificationNotifierUnavailable:
    """When the notifier object is not available, no platform gets the
    OS path — the overlay is the only working channel."""

    @pytest.mark.parametrize(
        "platform",
        ["linux", "darwin", "win32", "freebsd"],
    )
    def test_no_notifier_always_returns_false(self, platform):
        assert _prefer_os_notification(notifier_available=False, platform=platform) is False
