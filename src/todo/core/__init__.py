"""__init__.py

todo.core: A decorator to make security checks on the to-do database.
"""

import sys

from PyQt5 import QtWidgets

from todo.core import settings
from todo.core.Logger import Logger


def error_on_none_db(func):
    """Check if settings.db is valid and run func or error out if it is None."""

    logger = Logger(func.__name__)

    def wrapper(*args, **kwargs):
        """Wrap around func and check settings.db"""

        if settings.db is not None:
            try:
                result = func(*args, **kwargs)
                return result
            except OSError as e:
                logger.log.exception(f"To-Do error: {e}")
                return
        else:
            msg = "Database does not exist, exiting"
            QtWidgets.QMessageBox.critical(None, "Database Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

    return wrapper
