"""settings.py

This module creates To-Do core global variables and functions.
"""

import sys
import os

__version__ = "0.2.0"
options = {}
db = None

home_dir = os.getenv("HOME")
if home_dir is not None:
    todo_dir = os.path.join(home_dir, ".todo")
else:
    print("Error: unable to write log file, exiting")
    sys.exit(1)

if not os.path.exists(todo_dir):
    try:
        os.mkdir(todo_dir)
    except OSError as e:
        print(f"Error creating To-Do configuration directory: {e}")
        sys.exit(1)


# private files
ini_fn = os.path.join(todo_dir, "todo.ini")
lists_fn = os.path.join(todo_dir, "todo_lists.json")
