"""Tests for ``MainWindow`` system-tray-icon theme tracking.

Regression for the bug where the tray icon picked its light/dark variant
once at startup and then never updated. On Linux/KDE a day/night (or manual)
theme switch flipped the rest of the app but left the tray icon frozen at
its launch variant, so it ended up dark-on-dark or light-on-light.

``_update_tray_icon_for_theme`` is now the single source of truth for the
variant choice, keyed off the app's effective theme (``get_current_theme``),
and it is re-invoked on every theme change: OS auto-switch
(``_on_system_theme_changed``) and manual Settings changes (the dialog's
``theme_applied`` signal).

Handlers are tested as unbound methods against a mock ``MainWindow`` — the
same pattern ``test_detail_panel_toggle.py`` uses — to avoid the cost of a
full MainWindow + Database + config stack.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pytodo_qt.gui.main_window import MainWindow
from pytodo_qt.gui.styles.themes import Theme


def _make_mock_window(*, tray_icon: object | None = "auto") -> MagicMock:
    window = MagicMock()
    if tray_icon == "auto":
        window.tray_icon = MagicMock()
    else:
        window.tray_icon = tray_icon
    # _get_icon returns a fresh sentinel so we can assert it reaches setIcon.
    window._get_icon.return_value = MagicMock(name="icon")
    return window


class TestUpdateTrayIconForTheme:
    """Variant selection tracks the active theme off-darwin."""

    def test_dark_theme_picks_light_icon(self, monkeypatch):
        """Dark theme needs the light glyph so it shows on a dark panel."""
        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.setattr("pytodo_qt.gui.main_window.get_current_theme", lambda: Theme.DARK)
        window = _make_mock_window()

        MainWindow._update_tray_icon_for_theme(window)

        window._get_icon.assert_called_once_with("tray-light.svg")
        window.tray_icon.setIcon.assert_called_once_with(window._get_icon.return_value)

    def test_light_theme_picks_dark_icon(self, monkeypatch):
        """Light theme needs the dark glyph so it shows on a light panel."""
        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.setattr("pytodo_qt.gui.main_window.get_current_theme", lambda: Theme.LIGHT)
        window = _make_mock_window()

        MainWindow._update_tray_icon_for_theme(window)

        window._get_icon.assert_called_once_with("tray.svg")
        window.tray_icon.setIcon.assert_called_once_with(window._get_icon.return_value)

    def test_no_tray_icon_is_a_noop(self, monkeypatch):
        """Headless / no-tray platforms set tray_icon to None — don't crash."""
        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.setattr("pytodo_qt.gui.main_window.get_current_theme", lambda: Theme.DARK)
        window = _make_mock_window(tray_icon=None)

        MainWindow._update_tray_icon_for_theme(window)

        window._get_icon.assert_not_called()

    def test_macos_uses_template_mask(self, monkeypatch):
        """macOS uses one template image the menu bar recolors itself."""
        monkeypatch.setattr("sys.platform", "darwin")
        # get_current_theme must not be consulted on darwin.
        monkeypatch.setattr(
            "pytodo_qt.gui.main_window.get_current_theme",
            lambda: pytest.fail("theme should not be read on darwin"),
        )
        window = _make_mock_window()

        MainWindow._update_tray_icon_for_theme(window)

        window._get_icon.assert_called_once_with("tray.svg")
        window._get_icon.return_value.setIsMask.assert_called_once_with(True)
        window.tray_icon.setIcon.assert_called_once_with(window._get_icon.return_value)


class TestThemeChangeRefreshesTray:
    """Every theme-change path re-evaluates the tray variant."""

    def test_system_switch_refreshes_when_following_os(self, monkeypatch):
        """OS day/night switch flips the tray while theme == 'system'."""
        monkeypatch.setattr("pytodo_qt.gui.main_window.apply_current_theme", lambda: None)
        window = _make_mock_window()
        window._config.appearance.theme = "system"

        MainWindow._on_system_theme_changed(window)

        window._update_tray_icon_for_theme.assert_called_once_with()

    def test_system_switch_ignored_with_manual_theme(self, monkeypatch):
        """A pinned Light/Dark app theme does not follow the OS auto-switch."""
        monkeypatch.setattr("pytodo_qt.gui.main_window.apply_current_theme", lambda: None)
        window = _make_mock_window()
        window._config.appearance.theme = "dark"

        MainWindow._on_system_theme_changed(window)

        window._update_tray_icon_for_theme.assert_not_called()
