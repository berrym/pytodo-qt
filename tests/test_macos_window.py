"""The number macOS lists a window under, read through the Objective-C
runtime; on any platform but cocoa nothing is sent.

The tests run offscreen, where a window's id is no NSView: the runtime
call is replaced by a stand-in. On cocoa the number read matched the one
the window server reported for a shown banner.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QWidget

from pytodo_qt.gui import macos_window

_WINDOW = 0x7F00


class _Runtime:
    """Stands in for objc_msgSend: answers ``window`` and ``windowNumber``."""

    def __init__(self, window: int = _WINDOW) -> None:
        self.window = window
        self.sent: list[str] = []

    def __call__(self, receiver, selector, *args, argtypes=(), restype=None):
        self.sent.append(selector)
        if selector == "window":
            return self.window
        assert receiver == self.window
        if selector == "windowNumber":
            return 4242
        raise AssertionError(f"unexpected message {selector}")


@pytest.fixture()
def cocoa(monkeypatch):
    monkeypatch.setattr(macos_window, "_is_cocoa", lambda: True)


def _widget(qtbot) -> QWidget:
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def test_the_offscreen_platform_is_not_cocoa():
    assert macos_window._is_cocoa() is False


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
