#!/usr/bin/env python3

"""__main__.py

A to-do list program written in Python using Qt5

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
from PyQt5 import QtWidgets

from todo.core.Logger import Logger
from todo.core import settings, TodoDataBase
from todo.gui import MainWindow


logger = Logger(__name__)


# Main function
def main():
    location = ""
    for i in range(0, len(sys.path)):
        if sys.path[i].__contains__("site-packages"):
            location = sys.path[i]
            location += "/todo"
            os.chdir(location)
            break

    if location == "":
        logger.log.exception("Unknown installation or invocation, exiting")
        sys.exit(0)

    # create a command line arg_parser
    arg_parser = argparse.ArgumentParser(
        prog="To-Do",
        description="To-Do List Program",
        epilog="Copyright Michael Berry 2020",
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
        help="allow remote users to grab your lists",
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
        "-i", "--ip", type=str, help="set the servers ip addresses."
    )

    server_group.add_argument(
        "-p",
        "--port",
        type=int,
        help="specify which port the network server will bind to",
    )

    arg_parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s v{settings.__version__}"
    )

    # parse args then convert to dict format
    args = arg_parser.parse_args()
    for k, v in vars(args).items():
        if v is not None:
            settings.options[k] = v

    # create a to-do database
    settings.db = TodoDataBase.CreateTodoDataBase()

    # create a QApplication, the main window, then hand over control to Qt
    app = QtWidgets.QApplication(sys.argv)
    _ = MainWindow.CreateMainWindow()
    sys.exit(app.exec())


# Main? - Program entry point
if __name__ == "__main__":
    main()
