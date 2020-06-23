"""core.py

This module creates todo core global variables and functions.
"""

import os


__version__ = "0.1.0"
options = {}
db = None
todo_dir = os.path.join(os.getenv("HOME"), ".todo")

if not os.path.exists(todo_dir):
    try:
        os.mkdir(todo_dir)
    except OSError as e:
        print(f"Error: {e}")
        exit(1)


ini_fn = os.path.join(todo_dir, "todo.ini")
lists_fn = os.path.join(todo_dir, "todo_lists.json")
log_fn = os.path.join(todo_dir, "todo.log")
