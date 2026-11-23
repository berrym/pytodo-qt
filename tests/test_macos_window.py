"""A reminder banner is seen over an application in full screen (#128).

A full-screen application has a Space of its own, and macOS lets another
application's panel into it only when the panel does not activate its
application; a panel stays in view on a Space entered after it was shown
only when it belongs to every Space. The banner is given both settings,
through the Objective-C runtime, before it is shown; on any platform but
cocoa nothing is done.

The tests run offscreen, where a window's id is no NSView: the runtime
calls are replaced by a recorder. The settings themselves were checked on
the cocoa platform (style 0xe before, 0x8e once shown; collection behavior
0x102 before, 0x101 once shown, also after hiding and showing again).
"""

from __future__ import annotations

import ctypes
import logging

import pytest
from PyQt6.QtWidgets import QWidget

from pytodo_qt.gui import macos_window
from pytodo_qt.gui.macos_window import (
    CAN_JOIN_ALL_SPACES,
    FULL_SCREEN_AUXILIARY,
    MOVE_TO_ACTIVE_SPACE,
    NONACTIVATING_PANEL,
)
from pytodo_qt.gui.widgets import notification_overlay
from pytodo_qt.gui.widgets.notification_overlay import NotificationOverlay

_WINDOW = 0x7F00
# What Qt 6.10 gives a Qt::Tool window on macOS.
_QT_STYLE = 0xE
_QT_BEHAVIOR = MOVE_TO_ACTIVE_SPACE | FULL_SCREEN_AUXILIARY  # 0x102


class _Runtime:
    """Stands in for objc_msgSend: answers ``window``, ``styleMask``,
    ``collectionBehavior`` and ``windowNumber``, and records the setters.
    Like macOS, it refuses CanJoinAllSpaces with MoveToActiveSpace."""

    def __init__(self, style: int = _QT_STYLE, behavior: int = _QT_BEHAVIOR, window: int = _WINDOW):
        self.style = style
        self.behavior = behavior
        self.window = window
        self.sent: list[tuple[str, tuple]] = []

    def __call__(self, receiver, selector, *args, argtypes=(), restype=None):
        self.sent.append((selector, args))
        if selector == "window":
            return self.window
        assert receiver == self.window
        if selector == "styleMask":
            return self.style
        if selector == "collectionBehavior":
            return self.behavior
        if selector == "windowNumber":
            return 4242
        (value,) = args
        value = value.value if isinstance(value, ctypes.c_ulong) else value
        if selector == "setStyleMask:":
            self.style = value
            return None
        if selector == "setCollectionBehavior:":
            if value & CAN_JOIN_ALL_SPACES and value & MOVE_TO_ACTIVE_SPACE:
                raise AssertionError("NSInternalInconsistencyException: both Space behaviors")
            self.behavior = value
            return None
        raise AssertionError(f"unexpected message {selector}")

    def setters(self) -> list[str]:
        return [selector for selector, _ in self.sent if selector.startswith("set")]


@pytest.fixture()
def cocoa(monkeypatch):
    monkeypatch.setattr(macos_window, "_is_cocoa", lambda: True)


def _widget(qtbot) -> QWidget:
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


class TestTheStyle:
    def test_is_added_to_the_window_style(self, qtbot, cocoa, monkeypatch):
        runtime = _Runtime()
        monkeypatch.setattr(macos_window, "_send", runtime)

        assert macos_window.show_on_every_space(_widget(qtbot)) is True

        assert runtime.style == _QT_STYLE | NONACTIVATING_PANEL == 0x8E

    def test_a_window_that_has_it_keeps_it_unsent(self, qtbot, cocoa, monkeypatch):
        runtime = _Runtime(style=0x8E)
        monkeypatch.setattr(macos_window, "_send", runtime)

        assert macos_window.show_on_every_space(_widget(qtbot)) is True

        assert "setStyleMask:" not in runtime.setters()


class TestTheSpaces:
    def test_the_window_belongs_to_every_space(self, qtbot, cocoa, monkeypatch):
        runtime = _Runtime()
        monkeypatch.setattr(macos_window, "_send", runtime)

        assert macos_window.show_on_every_space(_widget(qtbot)) is True

        assert runtime.behavior == CAN_JOIN_ALL_SPACES | FULL_SCREEN_AUXILIARY == 0x101

    def test_a_window_that_belongs_to_every_space_is_left_alone(self, qtbot, cocoa, monkeypatch):
        runtime = _Runtime(style=0x8E, behavior=0x101)
        monkeypatch.setattr(macos_window, "_send", runtime)

        assert macos_window.show_on_every_space(_widget(qtbot)) is True

        assert runtime.setters() == []

    @pytest.mark.parametrize("behavior", [0x0, 0x2, 0x100, 0x102, 0x112, 0x101])
    def test_never_both_space_behaviors_at_once(self, behavior):
        """macOS raises an exception for CanJoinAllSpaces together with
        MoveToActiveSpace; other bits the window has are kept."""
        wanted = macos_window.every_space_behavior(behavior)

        assert wanted & CAN_JOIN_ALL_SPACES
        assert wanted & FULL_SCREEN_AUXILIARY
        assert not wanted & MOVE_TO_ACTIVE_SPACE
        others = ~(CAN_JOIN_ALL_SPACES | MOVE_TO_ACTIVE_SPACE | FULL_SCREEN_AUXILIARY)
        assert wanted & others == behavior & others


class TestOtherPlatformsAndFailures:
    def test_nothing_is_sent_on_another_platform(self, qtbot, monkeypatch):
        """The offscreen platform of the tests among them: its window id
        is no NSView, and a message sent to it would crash."""
        runtime = _Runtime()
        monkeypatch.setattr(macos_window, "_send", runtime)

        assert macos_window.show_on_every_space(_widget(qtbot)) is False

        assert runtime.sent == []

    def test_the_offscreen_platform_is_not_cocoa(self):
        assert macos_window._is_cocoa() is False

    def test_a_view_without_a_window_is_logged_and_left(self, qtbot, cocoa, monkeypatch, caplog):
        runtime = _Runtime(window=0)
        monkeypatch.setattr(macos_window, "_send", runtime)

        with caplog.at_level(logging.WARNING):
            assert macos_window.show_on_every_space(_widget(qtbot)) is False

        assert "full screen" in caplog.text
        assert [selector for selector, _ in runtime.sent] == ["window"]

    def test_a_failing_call_is_logged_and_left(self, qtbot, cocoa, monkeypatch, caplog):
        def fail(*_args, **_kwargs):
            raise OSError("no runtime")

        monkeypatch.setattr(macos_window, "_send", fail)

        with caplog.at_level(logging.WARNING):
            assert macos_window.show_on_every_space(_widget(qtbot)) is False

        assert "full screen" in caplog.text


class TestTheWindowNumber:
    """The number macOS lists a window under, which ties a banner's lines
    in the log to what the window server reports."""

    def test_is_read_from_the_window(self, qtbot, cocoa, monkeypatch):
        monkeypatch.setattr(macos_window, "_send", _Runtime())

        assert macos_window.window_number(_widget(qtbot)) == 4242

    def test_is_none_on_another_platform(self, qtbot, monkeypatch):
        runtime = _Runtime()
        monkeypatch.setattr(macos_window, "_send", runtime)

        assert macos_window.window_number(_widget(qtbot)) is None
        assert runtime.sent == []

    def test_is_none_for_a_view_without_a_window(self, qtbot, cocoa, monkeypatch):
        monkeypatch.setattr(macos_window, "_send", _Runtime(window=0))

        assert macos_window.window_number(_widget(qtbot)) is None

    def test_is_none_when_the_call_fails(self, qtbot, cocoa, monkeypatch):
        def fail(*_args, **_kwargs):
            raise OSError("no runtime")

        monkeypatch.setattr(macos_window, "_send", fail)

        assert macos_window.window_number(_widget(qtbot)) is None


class TestTheBanner:
    def test_is_given_the_settings_each_time_it_is_shown(self, qtbot, monkeypatch):
        given: list[QWidget] = []
        monkeypatch.setattr(notification_overlay, "show_on_every_space", given.append)
        banner = NotificationOverlay("Call the bank", "Due at 14:30")
        qtbot.addWidget(banner)

        banner.show()
        banner.hide()
        banner.show()

        assert given == [banner, banner]

    def test_is_shown_when_the_settings_cannot_be_given(self, qtbot, monkeypatch):
        monkeypatch.setattr(notification_overlay, "show_on_every_space", lambda _w: False)
        banner = NotificationOverlay("Call the bank", "Due at 14:30")
        qtbot.addWidget(banner)

        banner.show()

        assert banner.isVisible()
