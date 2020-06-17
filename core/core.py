"""core.py

This module creates todo core global variables and functions.
"""

import os


__version__ = "0.1.0"
options = {}
db = None
ini_fn = os.path.join(os.getenv("HOME"), ".todo.ini")
lists_fn = os.path.join(os.getenv("HOME"), ".todo_lists.json")
log_fn = os.path.join(os.getenv("HOME"), ".todo.log")
