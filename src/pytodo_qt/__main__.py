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

import argparse
import asyncio
import ctypes
import ctypes.util
import sys

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

    # Run application with async event loop
    with loop:
        sys.exit(loop.run_forever())


if __name__ == "__main__":
    main()
