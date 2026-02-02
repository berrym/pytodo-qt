"""migration.py

Migration utilities for pytodo-qt database.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from .database import DatabaseStorage
from .logger import Logger
from .models import Database

logger = Logger(__name__)


class MigrationError(Exception):
    """Error during database migration."""

    pass


def backup_json_file(json_path: Path) -> Path:
    """Create timestamped backup of JSON file.

    Args:
        json_path: Path to the JSON file to backup

    Returns:
        Path to the backup file

    Raises:
        MigrationError: If backup fails
    """
    if not json_path.exists():
        raise MigrationError(f"JSON file does not exist: {json_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = json_path.with_suffix(f".json.backup_{timestamp}")

    try:
        shutil.copy2(json_path, backup_path)
        logger.log.info("Created backup: %s", backup_path)
        return backup_path
    except OSError as e:
        raise MigrationError(f"Failed to create backup: {e}") from e


def load_json_database(json_path: Path) -> Database:
    """Load database from JSON file.

    Handles both current format (schema_version=2) and legacy format (v0.2.x).

    Args:
        json_path: Path to the JSON database file

    Returns:
        Database object

    Raises:
        MigrationError: If loading fails
    """
    if not json_path.exists():
        raise MigrationError(f"JSON file does not exist: {json_path}")

    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise MigrationError(f"Invalid JSON: {e}") from e
    except OSError as e:
        raise MigrationError(f"Failed to read file: {e}") from e

    try:
        # Check if it's new format (has schema_version) or legacy
        if "schema_version" in data:
            db = Database.from_dict(data)
            logger.log.info("Loaded JSON database (schema version %d)", db.schema_version)
        else:
            # Legacy format: {"list_name": [items...]}
            db = Database.from_legacy(data)
            logger.log.info("Loaded legacy JSON database")

        return db
    except Exception as e:
        raise MigrationError(f"Failed to parse database: {e}") from e


def migrate_json_to_sqlite(
    json_path: Path,
    sqlite_path: Path,
    backup: bool = True,
) -> bool:
    """Migrate JSON database to SQLite.

    Args:
        json_path: Path to existing JSON database
        sqlite_path: Path for new SQLite database
        backup: Whether to backup JSON file before migration

    Returns:
        True if migration succeeded

    Raises:
        MigrationError: If migration fails
    """
    logger.log.info("Starting migration from %s to %s", json_path, sqlite_path)

    # Verify JSON exists
    if not json_path.exists():
        raise MigrationError(f"Source JSON file does not exist: {json_path}")

    # Don't overwrite existing SQLite
    if sqlite_path.exists():
        raise MigrationError(f"Target SQLite file already exists: {sqlite_path}")

    # Create backup
    backup_path = None
    if backup:
        backup_path = backup_json_file(json_path)

    # Load JSON
    try:
        db = load_json_database(json_path)
    except MigrationError:
        raise
    except Exception as e:
        raise MigrationError(f"Failed to load JSON database: {e}") from e

    # Create SQLite and transfer data
    storage = DatabaseStorage(sqlite_path)
    try:
        storage.open()
        storage.save_database(db)
        storage.close()
    except Exception as e:
        # Cleanup on failure
        storage.close()
        if sqlite_path.exists():
            sqlite_path.unlink()
        raise MigrationError(f"Failed to write SQLite database: {e}") from e

    # Verify migration
    try:
        verification_ok = verify_migration(json_path, sqlite_path)
        if not verification_ok:
            raise MigrationError("Migration verification failed")
    except MigrationError:
        # Cleanup on failure
        if sqlite_path.exists():
            sqlite_path.unlink()
        raise

    logger.log.info(
        "Migration completed successfully. Backup at: %s",
        backup_path if backup_path else "none",
    )
    return True


def verify_migration(json_path: Path, sqlite_path: Path) -> bool:
    """Verify that migration was successful by comparing counts.

    Args:
        json_path: Path to original JSON database
        sqlite_path: Path to new SQLite database

    Returns:
        True if verification passes
    """
    # Load both databases
    json_db = load_json_database(json_path)

    storage = DatabaseStorage(sqlite_path)
    storage.open()
    sqlite_db = storage.load_database()
    storage.close()

    # Compare list counts
    json_list_count = len(json_db.lists)
    sqlite_list_count = len(sqlite_db.lists)
    if json_list_count != sqlite_list_count:
        logger.log.error(
            "List count mismatch: JSON=%d, SQLite=%d",
            json_list_count,
            sqlite_list_count,
        )
        return False

    # Compare item counts
    json_item_count = sum(len(lst.items) for lst in json_db.lists.values())
    sqlite_item_count = sum(len(lst.items) for lst in sqlite_db.lists.values())
    if json_item_count != sqlite_item_count:
        logger.log.error(
            "Item count mismatch: JSON=%d, SQLite=%d",
            json_item_count,
            sqlite_item_count,
        )
        return False

    # Compare active list
    if json_db.active_list_id != sqlite_db.active_list_id:
        logger.log.error(
            "Active list mismatch: JSON=%s, SQLite=%s",
            json_db.active_list_id,
            sqlite_db.active_list_id,
        )
        return False

    logger.log.info(
        "Migration verified: %d lists, %d items",
        sqlite_list_count,
        sqlite_item_count,
    )
    return True


def needs_migration(json_path: Path, sqlite_path: Path) -> bool:
    """Check if migration is needed.

    Migration is needed when:
    - JSON file exists AND
    - SQLite file does not exist

    Args:
        json_path: Path to JSON database
        sqlite_path: Path to SQLite database

    Returns:
        True if migration should be performed
    """
    return json_path.exists() and not sqlite_path.exists()


def get_migration_status(json_path: Path, sqlite_path: Path) -> str:
    """Get human-readable migration status.

    Args:
        json_path: Path to JSON database
        sqlite_path: Path to SQLite database

    Returns:
        Status string describing current state
    """
    json_exists = json_path.exists()
    sqlite_exists = sqlite_path.exists()

    if sqlite_exists and not json_exists:
        return "sqlite_only"  # Normal post-migration state
    elif sqlite_exists and json_exists:
        return "both_exist"  # Migration done, JSON not yet cleaned up
    elif json_exists and not sqlite_exists:
        return "needs_migration"  # Migration required
    else:
        return "fresh_install"  # No database exists
