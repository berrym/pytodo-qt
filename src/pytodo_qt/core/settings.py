"""settings.py

This module creates To-Do core global variables and functions.
"""

import sys

from pathlib import Path

from ..core.Logger import Logger


logger = Logger(__name__)


__version__ = "0.2.8"
options = {}
DB = None

home_dir = Path.home()
if home_dir is not None:
    app_dir = Path.joinpath(home_dir, ".pytodo-qt")
else:
    logger.log.exception("Unable to get home directory, exiting")
    sys.exit(1)

if not Path.exists(app_dir):
    try:
        Path.mkdir(app_dir)
    except OSError as e:
        logger.log.exception("Error creating pytodo-qt configuration directory: %s", e)
        sys.exit(1)


# private files
ini_fn = Path.joinpath(app_dir, "pytodo-qt.ini")
db_fn = Path.joinpath(app_dir, "pytodo-qt-db.json")
