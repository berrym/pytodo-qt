#!/usr/bin/env python3


"""todo.py

A todo list program written in Python using Qt5

Copyright (C) <2020>  <Michael Berry>

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

import core.defaults
import core.TodoDatabase
from gui import MainWindow


# Main function
def main():
    # make the working directory same as the directory that PyTodo is located
    os.chdir(os.sys.path[0])

    # create a command line arg_parser
    arg_parser = argparse.ArgumentParser(
        prog="todo.py",
        description="To-Do List Program",
        epilog="Copyright Michael Berry 2020",
    )

    # add net_server command group
    server_group = arg_parser.add_argument_group("Server Commands")

    # add options
    server_group.add_argument(
        "-s",
        "--run",
        action="store",
        type=str,
        choices=["yes", "no"],
        help="run a simple todo list net_server",
    )

    server_group.add_argument(
        "-a",
        "--pull",
        action="store",
        type=str,
        choices=["yes", "no"],
        help="allow remote users to grab your list",
    )

    server_group.add_argument(
        "-A",
        "--push",
        action="store",
        type=str,
        choices=["yes", "no"],
        help="allow remote users to send you their lists",
    )

    server_group.add_argument(
        "-i", "--ip_address", type=str, help="set the servers ip addressess."
    )

    server_group.add_argument(
        "-p", "--port", type=int, help="specify which port the net_server will bind to"
    )

    arg_parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s v{core.defaults.__version__}"
    )

    # parse args then convert to dict format
    args = arg_parser.parse_args()
    for k, v in vars(args).items():
        if v is not None:
            core.defaults.options[k] = v

    # create a database
    core.defaults.db = core.TodoDatabase.CreateTodoDatabase()

    # create a QApplication, the main window, then hand over control to Qt
    app = QtWidgets.QApplication(sys.argv)
    main_win = MainWindow.CreateMainWindow()
    sys.exit(app.exec_())


# Main? - Program entry point
if __name__ == "__main__":
    main()
