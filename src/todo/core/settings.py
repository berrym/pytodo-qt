"""settings.py

This module creates To-Do core global variables and functions.
"""

import sys

from pathlib import Path

__version__ = "0.2.3"
options = {}
db = None

home_dir = Path.home()
if home_dir is not None:
    todo_dir = Path.joinpath(home_dir, ".todo")
else:
    print("Error: unable to write log file, exiting")
    sys.exit(1)

if not Path.exists(todo_dir):
    try:
        Path.mkdir(todo_dir)
    except OSError as e:
        print(f"Error creating To-Do configuration directory: {e}")
        sys.exit(1)


# private files
ini_fn = Path.joinpath(todo_dir, "todo.ini")
lists_fn = Path.joinpath(todo_dir, "todo_lists.json")
