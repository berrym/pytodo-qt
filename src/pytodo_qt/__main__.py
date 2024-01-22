"""__main__.py

pytodo-qt

A to-do list program written in Python using PyQt6

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
import os
import sys

from PyQt6.QtWidgets import QApplication

from .core.Logger import Logger
from .core import settings
from .core.TodoDatabase import TodoDatabase
from .gui.MainWindow import MainWindow


logger = Logger(__name__)


# Main function
def main():
    # move to main module dir
    os.chdir(os.path.dirname(__file__))

    # create a command line arg_parser
    arg_parser = argparse.ArgumentParser(
        prog="pytodo-qt",
        description="To-Do List Application written in Python 3 and PyQt6",
        epilog="Copyright Michael Berry 2024",
    )

    # add network server command group
    server_group = arg_parser.add_argument_group("Server Commands")

    # add options
    server_group.add_argument(
        "-s",
        "--run-server",
        action="store",
        type=str,
        choices=["yes", "no"],
        help="run a simple to-do list network server",
    )

    server_group.add_argument(
        "-a",
        "--allow-pull",
        action="store",
        type=str,
        choices=["yes", "no"],
        help="allow remote users to copy your lists",
    )

    server_group.add_argument(
        "-A",
        "--allow-push",
        action="store",
        type=str,
        choices=["yes", "no"],
        help="allow remote users to send you their lists",
    )

    server_group.add_argument(
        "-i", "--ip", type=str, help="set the database server's IP address."
    )

    server_group.add_argument(
        "-p",
        "--port",
        type=int,
        help="specify which port the database server will bind to",
    )

    arg_parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s v{settings.__version__}"
    )

    # parse args then convert to dict format
    args = arg_parser.parse_args()
    for k, v in vars(args).items():
        if v is not None:
            settings.options[k] = v

    # create a QApplication, the main window, DB, then hand over control to Qt
    app = QApplication(sys.argv)
    settings.DB = TodoDatabase()
    _ = MainWindow()
    sys.exit(app.exec())
