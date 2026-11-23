"""Window facts on macOS that Qt does not give.

The number the window server lists a window under, read through the
Objective-C runtime with ctypes, which needs no other package. Only on
the cocoa platform is a window's id an NSView; on any other platform, the
offscreen one of the tests included, nothing is sent.
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
