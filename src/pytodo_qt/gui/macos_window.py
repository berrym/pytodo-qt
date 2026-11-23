"""Window settings on macOS that Qt has no setting for (#128).

A full-screen application has a Space of its own, and macOS lets another
application's panel into it only when the panel does not activate its
application: the window style NSWindowStyleMaskNonactivatingPanel. Qt
6.10 sets that style for no window flags, Qt::Tool with
Qt::WindowDoesNotAcceptFocus included, so a reminder banner shown while
another application is in full screen was placed on the desktop and seen
only when full screen was left.

Qt gives such a window the collection behavior MoveToActiveSpace |
FullScreenAuxiliary (0x102): it is placed in the Space that is active
when it is shown and stays there. A banner shown on the desktop was out
of sight once another application went to full screen, until full screen
was left. A banner waits until it is acted on, so it is made to belong to
every Space instead: CanJoinAllSpaces | FullScreenAuxiliary (0x101).
macOS refuses CanJoinAllSpaces together with MoveToActiveSpace, with an
exception, so the one replaces the other in a single change.

The settings are made through the Objective-C runtime with ctypes, which
needs no other package. Only on the cocoa platform is a window's id an
NSView; on any other platform, the offscreen one of the tests included,
nothing is done.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Any

from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QWidget

from ..core.logger import Logger

logger = Logger(__name__)

# NSWindowStyleMaskNonactivatingPanel
NONACTIVATING_PANEL = 1 << 7
# NSWindowCollectionBehavior
CAN_JOIN_ALL_SPACES = 1 << 0
MOVE_TO_ACTIVE_SPACE = 1 << 1
FULL_SCREEN_AUXILIARY = 1 << 8

_runtime: Any = None


def _objc() -> Any:
    """The Objective-C runtime library, loaded once."""
    global _runtime
    if _runtime is None:
        library = ctypes.util.find_library("objc")
        if library is None:
            raise OSError("the Objective-C runtime library was not found")
        runtime = ctypes.cdll.LoadLibrary(library)
        runtime.sel_registerName.restype = ctypes.c_void_p
        runtime.sel_registerName.argtypes = [ctypes.c_char_p]
        _runtime = runtime
    return _runtime


def _send(receiver: int, selector: str, *args: Any, argtypes: tuple = (), restype: Any = None):
    """Send an Objective-C message: ``[receiver selector:args…]``."""
    runtime = _objc()
    address = ctypes.cast(runtime.objc_msgSend, ctypes.c_void_p).value
    if address is None:
        raise OSError("objc_msgSend was not found")
    function = ctypes.CFUNCTYPE(
        restype or ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, *argtypes
    )(address)
    return function(receiver, runtime.sel_registerName(selector.encode()), *args)


def _is_cocoa() -> bool:
    return sys.platform == "darwin" and QGuiApplication.platformName() == "cocoa"


def window_number(widget: QWidget) -> int | None:
    """The number the window server lists the widget's window under.

    It ties a line of the log to the window macOS reports on screen or
    not. None on a platform other than cocoa, or when it cannot be had.
    """
    if not _is_cocoa():
        return None
    try:
        window = _send(int(widget.winId()), "window")
        if not window:
            return None
        return int(_send(window, "windowNumber", restype=ctypes.c_long))
    except Exception:
        logger.log.debug("Could not read a window's number", exc_info=True)
        return None


def every_space_behavior(behavior: int) -> int:
    """The collection behavior that puts a window in every Space, the
    full-screen ones included, made from the one it has.

    MoveToActiveSpace is taken out in the same value that puts
    CanJoinAllSpaces in: macOS raises an exception for both at once.
    """
    return (behavior & ~MOVE_TO_ACTIVE_SPACE) | CAN_JOIN_ALL_SPACES | FULL_SCREEN_AUXILIARY


def show_on_every_space(widget: QWidget) -> bool:
    """Make the widget's window a non-activating panel that belongs to
    every Space, so that it is seen over an application in full screen,
    also one that went to full screen after the window was shown.

    Returns whether the window has both settings. On a platform other
    than cocoa nothing is done and False is returned; a failure is logged
    and leaves the window as it was.
    """
    if not _is_cocoa():
        return False
    try:
        view = int(widget.winId())
        window = _send(view, "window")
        if not window:
            raise RuntimeError("the widget's view has no window")
        style = _send(window, "styleMask", restype=ctypes.c_ulong)
        if not style & NONACTIVATING_PANEL:
            _send(
                window,
                "setStyleMask:",
                ctypes.c_ulong(style | NONACTIVATING_PANEL),
                argtypes=(ctypes.c_ulong,),
            )
        behavior = _send(window, "collectionBehavior", restype=ctypes.c_ulong)
        wanted = every_space_behavior(behavior)
        if behavior != wanted:
            _send(
                window,
                "setCollectionBehavior:",
                ctypes.c_ulong(wanted),
                argtypes=(ctypes.c_ulong,),
            )
        return True
    except Exception:
        logger.log.warning(
            "Could not make a banner a panel of every Space; it is not shown over an "
            "application in full screen",
            exc_info=True,
        )
        return False
