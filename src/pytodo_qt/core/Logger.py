"""Logger.py

A Generic logging class.
"""

import logging
import sys

from pathlib import Path

home_dir = Path.home()
if home_dir is not None:
    app_dir = Path.joinpath(home_dir, ".pytodo-qt")
else:
    print("Error: unable to get home directory, exiting")
    sys.exit(1)

if not Path.exists(app_dir):
    try:
        Path.mkdir(app_dir)
    except OSError as e:
        print(f"Error: failed to create pytodo-qt directory {app_dir}: {e}")
        sys.exit(1)

log_fn = Path.joinpath(app_dir, "pytodo-qt.log")

if not Path.exists(log_fn):
    try:
        log_fn.touch()
    except OSError as e:
        print(f"Error: failed to create pytodo-qt log file {log_fn}: {e}")
        sys.exit(1)


class Logger:
    """A flexible logger."""

    def __init__(
        self,
        module_name,
        file_name=log_fn,
        file_mode="w",
        file_handler_level=logging.DEBUG,
        file_handler_format="%(asctime)-15s [%(threadName)-12s][%(levelname)-8s]  %(message)s",
        console_handler=logging.StreamHandler(),
        console_handler_level=logging.DEBUG,
        console_handler_format=logging.Formatter(
            "%(asctime)-15s [%(threadName)-12s][%(levelname)-8s]  %(message)s"
        ),
    ):
        """Initialize the logger."""
        logging.basicConfig(
            level=file_handler_level,
            format=file_handler_format,
            filename=file_name,
            filemode=file_mode,
        )

        self.log = logging.getLogger(module_name)
        console_handler.setLevel(console_handler_level)
        console_handler.setFormatter(console_handler_format)
        self.log.addHandler(console_handler)
