"""paths.py

XDG Base Directory compliant path management.

Follows the XDG Base Directory Specification:
- $XDG_CONFIG_HOME (default: ~/.config) - configuration files
- $XDG_DATA_HOME (default: ~/.local/share) - data files
- $XDG_STATE_HOME (default: ~/.local/state) - state/log files
"""

from __future__ import annotations

import os
from pathlib import Path

from .logger import Logger

logger = Logger(__name__)

APP_NAME = "pytodo-qt"


def get_xdg_config_home() -> Path:
    """Get XDG_CONFIG_HOME directory."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config)
    return Path.home() / ".config"


def get_xdg_data_home() -> Path:
    """Get XDG_DATA_HOME directory."""
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data)
    return Path.home() / ".local" / "share"


def get_xdg_state_home() -> Path:
    """Get XDG_STATE_HOME directory."""
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state)
    return Path.home() / ".local" / "state"


def get_config_dir() -> Path:
    """Get application config directory."""
    return get_xdg_config_home() / APP_NAME


def get_data_dir() -> Path:
    """Get application data directory."""
    return get_xdg_data_home() / APP_NAME


def get_state_dir() -> Path:
    """Get application state directory (for logs, etc.)."""
    return get_xdg_state_home() / APP_NAME


def get_config_file() -> Path:
    """Get path to config.toml."""
    return get_config_dir() / "config.toml"


def get_database_file() -> Path:
    """Get path to SQLite database file."""
    return get_data_dir() / "pytodo-qt.db"


def get_log_file() -> Path:
    """Get path to log file."""
    return get_state_dir() / "pytodo-qt.log"


def ensure_directories() -> None:
    """Ensure all application directories exist."""
    for dir_path in [get_config_dir(), get_data_dir(), get_state_dir()]:
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True)
                logger.log.debug("Created directory: %s", dir_path)
            except OSError as e:
                logger.log.exception("Error creating directory %s: %s", dir_path, e)
                raise
