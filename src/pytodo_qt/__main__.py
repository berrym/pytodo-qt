"""__main__.py

pytodo-qt

A modern to-do list application with secure synchronization.

Copyright (C) 2024 Michael Berry <trismegustis@gmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
import ctypes.util
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core.instance_lock import InstanceLock

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from .core import settings
from .core.logger import Logger

logger = Logger(__name__)

_APP_DISPLAY_NAME = "PyTodo-Qt"


def _set_macos_app_name() -> None:
    """Set the macOS menu bar application name via NSBundle.

    Must be called before QApplication() is created. Uses ctypes to
    call into the Objective-C runtime (zero external dependencies).
    """
    if sys.platform != "darwin":
        return

    try:
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))  # type: ignore[arg-type]

        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        NSBundle = objc.objc_getClass(b"NSBundle")
        bundle = objc.objc_msgSend(NSBundle, objc.sel_registerName(b"mainBundle"))

        info = objc.objc_msgSend(bundle, objc.sel_registerName(b"infoDictionary"))

        # Create NSString key and value
        NSString = objc.objc_getClass(b"NSString")
        sel_str = objc.sel_registerName(b"stringWithUTF8String:")
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
        key = objc.objc_msgSend(NSString, sel_str, b"CFBundleName")
        value = objc.objc_msgSend(NSString, sel_str, _APP_DISPLAY_NAME.encode())

        # Set CFBundleName in the info dictionary
        objc.objc_msgSend.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        objc.objc_msgSend(info, objc.sel_registerName(b"setObject:forKey:"), value, key)
    except Exception:
        pass  # Non-fatal — menu bar will just show "Python"


def _activate_macos_app() -> None:
    """Bring this process to the foreground on macOS via NSApplication."""
    if sys.platform != "darwin":
        return
    try:
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))  # type: ignore[arg-type]
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        NSApp = objc.objc_msgSend(
            objc.objc_getClass(b"NSApplication"),
            objc.sel_registerName(b"sharedApplication"),
        )
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        objc.objc_msgSend(NSApp, objc.sel_registerName(b"activateIgnoringOtherApps:"), True)
    except Exception:
        pass


def _setup_activation_handler(window: object) -> None:
    """Register SIGUSR1 handler to raise the window when signaled.

    Uses a socketpair to safely bridge the Unix signal into the Qt
    event loop (signal handlers cannot call Qt methods directly).
    """
    import signal
    import socket as _socket

    from PyQt6.QtCore import QSocketNotifier

    sig_read, sig_write = _socket.socketpair(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sig_read.setblocking(False)
    sig_write.setblocking(False)

    def _on_signal(_signum: int, _frame: object) -> None:
        with contextlib.suppress(Exception):
            sig_write.send(b"\x01")

    signal.signal(signal.SIGUSR1, _on_signal)

    def _on_activated() -> None:
        with contextlib.suppress(Exception):
            sig_read.recv(1)
        _activate_macos_app()
        from .gui.main_window import MainWindow

        if isinstance(window, MainWindow):
            window.showNormal()
            window.raise_()
            window.activateWindow()
            logger.log.info("Window activated by second instance signal")

    # QSocketNotifier must be stored to prevent garbage collection
    from PyQt6 import sip

    notifier = QSocketNotifier(sip.voidptr(sig_read.fileno()), QSocketNotifier.Type.Read)
    notifier.activated.connect(_on_activated)

    # Store references to prevent GC
    window._activation_notifier = notifier  # type: ignore[union-attr]
    window._activation_sockets = (sig_read, sig_write)  # type: ignore[union-attr]


def _signal_existing_instance(pid: int) -> bool:
    """Send activation signal to an existing instance.

    Returns True if the signal was delivered (instance should raise itself).
    """
    if sys.platform == "win32":
        return False
    try:
        import signal

        os.kill(pid, signal.SIGUSR1)
        return True
    except OSError:
        return False


def _handle_instance_conflict(lock: InstanceLock) -> str:
    """Handle detection of an already-running instance.

    First tries to signal the existing instance to raise its window.
    Falls back to a Replace/Quit dialog if signaling fails.

    Returns "quit" or "replace".
    """
    import time as _time_mod

    from PyQt6.QtWidgets import QMessageBox, QPushButton

    from .core.instance_lock import terminate_process

    pid = lock.read_pid()

    # Try signaling the existing instance to raise itself
    if pid and _signal_existing_instance(pid):
        logger.log.info("Signaled existing instance (PID %d) to activate", pid)
        sys.exit(0)

    # Signal failed — show fallback dialog
    pid_text = f" (PID {pid})" if pid else ""

    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle(_APP_DISPLAY_NAME)
    msg.setText(f"{_APP_DISPLAY_NAME} is already running{pid_text}.")
    msg.setInformativeText(
        "The running instance could not be activated.\nWhat would you like to do?"
    )

    quit_btn = msg.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
    replace_btn: QPushButton | None = msg.addButton("Replace", QMessageBox.ButtonRole.AcceptRole)
    msg.setDefaultButton(quit_btn)
    msg.exec()

    if msg.clickedButton() != replace_btn:
        return "quit"

    # Attempt to replace the existing instance
    if pid is None:
        if lock.acquire():
            return "replace"
        QMessageBox.critical(
            None,
            _APP_DISPLAY_NAME,
            "Cannot determine the PID of the running instance.\n"
            "Please close it manually and try again.",
        )
        return "quit"

    killed = terminate_process(pid)
    if not killed:
        QMessageBox.critical(
            None,
            _APP_DISPLAY_NAME,
            f"Could not terminate the running instance (PID {pid}).\n"
            "Please close it manually and try again.",
        )
        return "quit"

    for _attempt in range(10):
        if lock.acquire():
            return "replace"
        _time_mod.sleep(0.2)

    QMessageBox.critical(
        None,
        _APP_DISPLAY_NAME,
        "The previous instance was terminated but the lock\n"
        "could not be acquired. Please try again.",
    )
    return "quit"


def main():
    """Application entry point."""
    # Initialize configuration system
    config = settings.init_config()

    # Create command line argument parser
    arg_parser = argparse.ArgumentParser(
        prog="pytodo-qt",
        description="Modern To-Do List Application with Secure Sync",
        epilog="Copyright (C) 2024 Michael Berry",
    )

    # Server options
    server_group = arg_parser.add_argument_group("Server Options")

    server_group.add_argument(
        "-s",
        "--server",
        action="store",
        type=str,
        choices=["yes", "no"],
        help="enable/disable network server",
    )

    server_group.add_argument(
        "--pull",
        action="store",
        type=str,
        choices=["yes", "no"],
        help="allow remote pull requests",
    )

    server_group.add_argument(
        "--push",
        action="store",
        type=str,
        choices=["yes", "no"],
        help="allow remote push requests",
    )

    server_group.add_argument(
        "-i",
        "--ip",
        type=str,
        help="server bind address",
    )

    server_group.add_argument(
        "-p",
        "--port",
        type=int,
        help="server port",
    )

    # Discovery options
    discovery_group = arg_parser.add_argument_group("Discovery Options")

    discovery_group.add_argument(
        "-d",
        "--discovery",
        action="store",
        type=str,
        choices=["yes", "no"],
        help="enable/disable mDNS discovery",
    )

    # Appearance options
    appearance_group = arg_parser.add_argument_group("Appearance Options")

    appearance_group.add_argument(
        "-t",
        "--theme",
        type=str,
        choices=["light", "dark", "system"],
        help="UI theme",
    )

    # Web UI options
    web_group = arg_parser.add_argument_group("Web UI Options")

    web_group.add_argument(
        "--web",
        type=str,
        choices=["yes", "no"],
        help="Enable/disable embedded web server",
    )

    web_group.add_argument(
        "--web-port",
        type=int,
        help="Web server port (default: 8080)",
    )

    # General options
    arg_parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s v{settings.__version__}",
    )

    # Parse arguments
    args = arg_parser.parse_args()

    # Apply command-line overrides to config
    if args.server is not None:
        config.server.enabled = args.server == "yes"
    if args.pull is not None:
        config.server.allow_pull = args.pull == "yes"
    if args.push is not None:
        config.server.allow_push = args.push == "yes"
    if args.ip is not None:
        config.server.address = args.ip
    if args.port is not None:
        config.server.port = args.port
    if args.discovery is not None:
        config.discovery.enabled = args.discovery == "yes"
    if args.theme is not None:
        config.appearance.theme = args.theme
    if args.web is not None:
        config.web.enabled = args.web == "yes"
    if args.web_port is not None:
        config.web.port = args.web_port

    # Set macOS menu bar name before Qt reads bundle info
    _set_macos_app_name()

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName(_APP_DISPLAY_NAME)
    app.setApplicationVersion(settings.__version__)
    app.setOrganizationName("pytodo-qt")
    app.setDesktopFileName("pytodo-qt")

    # Set application icon (overrides platform default when running as script)
    from pathlib import Path

    _icon_dir = Path(__file__).parent / "gui" / "icons"
    _app_icon = QIcon()
    _app_icon.addFile(str(_icon_dir / "pytodo-qt.svg"))
    _app_icon.addFile(str(_icon_dir / "pytodo-qt-256.png"))
    _app_icon.addFile(str(_icon_dir / "pytodo-qt-1024.png"))
    app.setWindowIcon(_app_icon)

    # Single-instance guard
    from .core.instance_lock import InstanceLock

    instance_lock = InstanceLock()
    if not instance_lock.acquire():
        _result = _handle_instance_conflict(instance_lock)
        if _result == "quit":
            sys.exit(0)

    app.aboutToQuit.connect(instance_lock.release)

    # Set up async event loop with qasync
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Apply theme
    from .gui.styles import apply_current_theme, get_current_theme

    apply_current_theme()
    logger.log.info("Applied theme: %s", get_current_theme().value)

    # Create main window
    logger.log.info("Starting pytodo-qt v%s", settings.__version__)
    from .gui.main_window import MainWindow

    _window = MainWindow()  # noqa: F841 - window must stay alive for event loop

    # Set up SIGUSR1 handler so a second instance can activate this one
    if sys.platform != "win32":
        _setup_activation_handler(_window)

    # Run application with async event loop
    with loop:
        sys.exit(loop.run_forever())


if __name__ == "__main__":
    main()
