"""paths.py

XDG Base Directory compliant path management.

Follows the XDG Base Directory Specification:
- $XDG_CONFIG_HOME (default: ~/.config) - configuration files
- $XDG_DATA_HOME (default: ~/.local/share) - data files
- $XDG_STATE_HOME (default: ~/.local/state) - state/log files
"""

from __future__ import annotations

import os
import shutil
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


def get_legacy_dir() -> Path:
    """Get legacy ~/.pytodo-qt directory for migration."""
    return Path.home() / ".pytodo-qt"


def get_config_file() -> Path:
    """Get path to config.toml."""
    return get_config_dir() / "config.toml"


def get_legacy_ini_file() -> Path:
    """Get path to legacy INI config (for migration)."""
    return get_legacy_dir() / "pytodo-qt.ini"


def get_database_file() -> Path:
    """Get path to database JSON file."""
    return get_data_dir() / "pytodo-qt-db.json"


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


def migrate_from_legacy() -> bool:
    """Migrate files from legacy ~/.pytodo-qt directory to XDG locations.

    Returns:
        True if migration occurred, False otherwise.
    """
    legacy_dir = get_legacy_dir()
    if not legacy_dir.exists():
        return False

    migrated = False

    # Ensure new directories exist
    ensure_directories()

    # Migrate config.toml
    legacy_config = legacy_dir / "config.toml"
    new_config = get_config_file()
    if legacy_config.exists() and not new_config.exists():
        try:
            shutil.copy2(legacy_config, new_config)
            logger.log.info("Migrated config from %s to %s", legacy_config, new_config)
            migrated = True
        except OSError as e:
            logger.log.warning("Failed to migrate config: %s", e)

    # Migrate database file
    legacy_db = legacy_dir / "pytodo-qt-db.json"
    new_db = get_database_file()
    if legacy_db.exists() and not new_db.exists():
        try:
            shutil.copy2(legacy_db, new_db)
            logger.log.info("Migrated database from %s to %s", legacy_db, new_db)
            migrated = True
        except OSError as e:
            logger.log.warning("Failed to migrate database: %s", e)

    # Migrate legacy INI file (for further migration to TOML)
    legacy_ini = legacy_dir / "pytodo-qt.ini"
    new_legacy_ini = get_config_dir() / "pytodo-qt.ini"
    if legacy_ini.exists() and not new_legacy_ini.exists():
        try:
            shutil.copy2(legacy_ini, new_legacy_ini)
            logger.log.info("Migrated legacy INI from %s to %s", legacy_ini, new_legacy_ini)
            migrated = True
        except OSError as e:
            logger.log.warning("Failed to migrate legacy INI: %s", e)

    if migrated:
        # Create a marker file in legacy dir indicating migration occurred
        marker = legacy_dir / ".migrated-to-xdg"
        try:
            marker.write_text(
                f"Migrated to XDG directories.\nConfig: {get_config_dir()}\nData: {get_data_dir()}\n"
            )
            logger.log.info(
                "Legacy data migrated to XDG directories. Old files preserved in %s", legacy_dir
            )
        except OSError:
            pass

    return migrated
