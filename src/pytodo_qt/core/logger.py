"""logger.py

Modern logging system using rich for beautiful console output.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

if TYPE_CHECKING:
    pass


# Custom theme for log output
THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "critical": "bold white on red",
        "debug": "dim",
        "repr.number": "bold cyan",
        "repr.path": "magenta",
        "repr.str": "green",
        "repr.tag_name": "bold magenta",
        "log.time": "dim cyan",
        "log.message": "default",
    }
)

# Global console for rich output
console = Console(theme=THEME, stderr=True)


def _xdg_state_log_file() -> Path:
    """Return the XDG state home log file path.

    Duplicates the small slice of paths.get_log_file() needed here
    to avoid a circular import: paths.py instantiates Logger during
    its own module body, which is BEFORE paths.get_log_file is
    defined, so neither a top-level nor a lazy `from . import paths`
    here works. Keeping the XDG layout in lockstep with paths.py is
    a one-time copy — the layout is locked by the XDG spec and the
    APP_NAME constant has been stable since the project started.
    """
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state) if xdg_state else Path.home() / ".local" / "state"
    return base / "pytodo-qt" / "pytodo-qt.log"


# Configure root logger once
_configured = False


def _configure_logging() -> None:
    """Configure the logging system."""
    global _configured
    if _configured:
        return

    log_file = _xdg_state_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Rich handler for console
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        markup=True,
    )
    rich_handler.setLevel(logging.DEBUG)

    # File handler for persistent logs
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(rich_handler)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name, typically __name__ of the calling module

    Returns:
        Configured logger instance
    """
    _configure_logging()
    return logging.getLogger(name)


class Logger:
    """Legacy-compatible logger wrapper.

    Provides backward compatibility with old Logger class usage.
    """

    def __init__(self, name: str):
        """Initialize logger.

        Args:
            name: Logger name, typically __name__
        """
        self.log = get_logger(name)


# Convenience functions for quick logging
def debug(msg: str, *args, **kwargs) -> None:
    """Log a debug message."""
    get_logger("pytodo").debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs) -> None:
    """Log an info message."""
    get_logger("pytodo").info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs) -> None:
    """Log a warning message."""
    get_logger("pytodo").warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs) -> None:
    """Log an error message."""
    get_logger("pytodo").error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs) -> None:
    """Log a critical message."""
    get_logger("pytodo").critical(msg, *args, **kwargs)


def exception(msg: str, *args, **kwargs) -> None:
    """Log an exception with traceback."""
    get_logger("pytodo").exception(msg, *args, **kwargs)
