"""settings.py

This module creates To-Do core global variables and functions.
"""

import sys

from pathlib import Path

from ..core.Logger import Logger


logger = Logger(__name__)


__version__ = "0.2.5"
options = {}
DB = None

home_dir = Path.home()
if home_dir is not None:
    todo_dir = Path.joinpath(home_dir, ".todo")
else:
    logger.log.exception("Unable to get home directory, exiting")
    sys.exit(1)

if not Path.exists(todo_dir):
    try:
        Path.mkdir(todo_dir)
    except OSError as e:
        logger.log.exception("Error creating To-Do configuration directory: %s", e)
        sys.exit(1)


# private files
ini_fn = Path.joinpath(todo_dir, "todo.ini")
lists_fn = Path.joinpath(todo_dir, "todo_lists.json")
