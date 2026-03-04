"""database.py

SQLite storage layer for pytodo-qt.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from .logger import Logger
from .models import (
    Database,
    Device,
    ListSyncRule,
    PendingSync,
    SyncGroup,
    TodoItem,
    TodoList,
)

if TYPE_CHECKING:
    pass

logger = Logger(__name__)

# Schema version for SQLite database (continues from JSON schema_version=2)
SCHEMA_VERSION = 10

# SQL statements for schema creation
_CREATE_METADATA_TABLE = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
)
"""

_CREATE_LISTS_TABLE = """
CREATE TABLE IF NOT EXISTS lists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    private INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    list_id TEXT NOT NULL,
    reminder TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 2,
    complete INTEGER NOT NULL DEFAULT 0,
    due_date TEXT,
    due_time TEXT,
    tags TEXT,
    recurrence_type TEXT,
    recurrence_interval INTEGER NOT NULL DEFAULT 1,
    recurrence_end_date TEXT,
    recurrence_end_count INTEGER,
    recurrence_count INTEGER NOT NULL DEFAULT 0,
    time_spent INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (list_id) REFERENCES lists(id)
)
"""

_CREATE_DEVICES_TABLE = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    last_address TEXT,
    trust_level TEXT NOT NULL DEFAULT 'normal'
)
"""

_CREATE_SYNC_GROUPS_TABLE = """
CREATE TABLE IF NOT EXISTS sync_groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
)
"""

_CREATE_DEVICE_GROUPS_TABLE = """
CREATE TABLE IF NOT EXISTS device_groups (
    device_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    PRIMARY KEY (device_id, group_id),
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES sync_groups(id) ON DELETE CASCADE
)
"""

_CREATE_LIST_SYNC_RULES_TABLE = """
CREATE TABLE IF NOT EXISTS list_sync_rules (
    list_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    PRIMARY KEY (list_id, group_id),
    FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES sync_groups(id) ON DELETE CASCADE
)
"""

_CREATE_PENDING_SYNCS_TABLE = """
CREATE TABLE IF NOT EXISTS pending_syncs (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    list_ids TEXT,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt INTEGER,
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_lists_deleted ON lists(deleted)",
    "CREATE INDEX IF NOT EXISTS idx_lists_name ON lists(name)",
    "CREATE INDEX IF NOT EXISTS idx_items_list_id ON items(list_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_deleted ON items(deleted)",
    "CREATE INDEX IF NOT EXISTS idx_items_complete ON items(complete)",
    "CREATE INDEX IF NOT EXISTS idx_items_priority ON items(priority)",
    # Sync groups indexes
    "CREATE INDEX IF NOT EXISTS idx_devices_fingerprint ON devices(fingerprint)",
    "CREATE INDEX IF NOT EXISTS idx_devices_trust_level ON devices(trust_level)",
    "CREATE INDEX IF NOT EXISTS idx_device_groups_device_id ON device_groups(device_id)",
    "CREATE INDEX IF NOT EXISTS idx_device_groups_group_id ON device_groups(group_id)",
    "CREATE INDEX IF NOT EXISTS idx_list_sync_rules_list_id ON list_sync_rules(list_id)",
    "CREATE INDEX IF NOT EXISTS idx_list_sync_rules_group_id ON list_sync_rules(group_id)",
    "CREATE INDEX IF NOT EXISTS idx_pending_syncs_device_id ON pending_syncs(device_id)",
    "CREATE INDEX IF NOT EXISTS idx_pending_syncs_expires_at ON pending_syncs(expires_at)",
]

# Indexes that require schema v6 or later (due_date column)
_CREATE_INDEXES_V6 = [
    "CREATE INDEX IF NOT EXISTS idx_items_due_date ON items(due_date)",
]


class DatabaseError(Exception):
    """Base exception for database errors."""

    pass


class DatabaseStorage:
    """SQLite-backed storage for todo data."""

    def __init__(self, db_path: Path) -> None:
        """Initialize database storage.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._connection: sqlite3.Connection | None = None

    def open(self) -> None:
        """Open database connection and ensure schema exists."""
        if self._connection is not None:
            return

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode, we manage transactions manually
        )
        self._connection.row_factory = sqlite3.Row

        # Enable foreign keys and WAL mode
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")

        self._create_schema()
        logger.log.info("Opened database: %s", self.db_path)

    def close(self) -> None:
        """Close database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            logger.log.info("Closed database: %s", self.db_path)

    @property
    def connection(self) -> sqlite3.Connection:
        """Get the database connection, opening if necessary."""
        if self._connection is None:
            self.open()
        return self._connection  # type: ignore[return-value]

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager for transactions.

        Usage:
            with storage.transaction() as conn:
                conn.execute(...)
                conn.execute(...)
            # Commits on success, rolls back on exception
        """
        conn = self.connection
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def _create_schema(self) -> None:
        """Create database schema if it doesn't exist."""
        conn = self.connection

        # Core tables
        conn.execute(_CREATE_METADATA_TABLE)
        conn.execute(_CREATE_LISTS_TABLE)
        conn.execute(_CREATE_ITEMS_TABLE)

        # Sync groups tables
        conn.execute(_CREATE_DEVICES_TABLE)
        conn.execute(_CREATE_SYNC_GROUPS_TABLE)
        conn.execute(_CREATE_DEVICE_GROUPS_TABLE)
        conn.execute(_CREATE_LIST_SYNC_RULES_TABLE)
        conn.execute(_CREATE_PENDING_SYNCS_TABLE)

        for index_sql in _CREATE_INDEXES:
            conn.execute(index_sql)

        # Set schema version if not present
        cursor = conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        if cursor.fetchone() is None:
            conn.execute(
                "INSERT INTO metadata (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

        # Run migrations if needed
        self._migrate_schema_3_to_4()
        self._migrate_schema_4_to_5()
        self._migrate_schema_5_to_6()
        self._migrate_schema_6_to_7()
        self._migrate_schema_7_to_8()
        self._migrate_schema_8_to_9()
        self._migrate_schema_9_to_10()

        # Create v6+ indexes (after migration ensures due_date column exists)
        for index_sql in _CREATE_INDEXES_V6:
            conn.execute(index_sql)

        logger.log.debug("Database schema initialized")

    def _migrate_schema_3_to_4(self) -> None:
        """Migrate schema from version 3 to 4 (add private column)."""
        current_version = self.get_schema_version()
        if current_version >= 4:
            return

        cursor = self.connection.execute("PRAGMA table_info(lists)")
        columns = [row[1] for row in cursor.fetchall()]

        if "private" not in columns:
            self.connection.execute(
                "ALTER TABLE lists ADD COLUMN private INTEGER NOT NULL DEFAULT 0"
            )
            logger.log.info("Migrated schema 3->4: added private column to lists")

        self.set_schema_version(4)

    def _migrate_schema_4_to_5(self) -> None:
        """Migrate schema from version 4 to 5 (add sync groups tables)."""
        current_version = self.get_schema_version()
        if current_version >= 5:
            return

        # Check if devices table exists (new in v5)
        cursor = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
        )
        if cursor.fetchone() is None:
            # Create all new tables
            self.connection.execute(_CREATE_DEVICES_TABLE)
            self.connection.execute(_CREATE_SYNC_GROUPS_TABLE)
            self.connection.execute(_CREATE_DEVICE_GROUPS_TABLE)
            self.connection.execute(_CREATE_LIST_SYNC_RULES_TABLE)
            self.connection.execute(_CREATE_PENDING_SYNCS_TABLE)

            # Create new indexes
            new_indexes = [
                "CREATE INDEX IF NOT EXISTS idx_devices_fingerprint ON devices(fingerprint)",
                "CREATE INDEX IF NOT EXISTS idx_devices_trust_level ON devices(trust_level)",
                "CREATE INDEX IF NOT EXISTS idx_device_groups_device_id ON device_groups(device_id)",
                "CREATE INDEX IF NOT EXISTS idx_device_groups_group_id ON device_groups(group_id)",
                "CREATE INDEX IF NOT EXISTS idx_list_sync_rules_list_id ON list_sync_rules(list_id)",
                "CREATE INDEX IF NOT EXISTS idx_list_sync_rules_group_id ON list_sync_rules(group_id)",
                "CREATE INDEX IF NOT EXISTS idx_pending_syncs_device_id ON pending_syncs(device_id)",
                "CREATE INDEX IF NOT EXISTS idx_pending_syncs_expires_at ON pending_syncs(expires_at)",
            ]
            for index_sql in new_indexes:
                self.connection.execute(index_sql)

            logger.log.info("Migrated schema 4->5: added sync groups tables")

        self.set_schema_version(5)

    def _migrate_schema_5_to_6(self) -> None:
        """Migrate schema from version 5 to 6 (add due_date column)."""
        current_version = self.get_schema_version()
        if current_version >= 6:
            return

        cursor = self.connection.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]

        if "due_date" not in columns:
            self.connection.execute("ALTER TABLE items ADD COLUMN due_date TEXT")
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_due_date ON items(due_date)"
            )
            logger.log.info("Migrated schema 5->6: added due_date column")

        self.set_schema_version(6)

    def _migrate_schema_6_to_7(self) -> None:
        """Migrate schema from version 6 to 7 (add recurrence columns)."""
        current_version = self.get_schema_version()
        if current_version >= 7:
            return

        cursor = self.connection.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]

        if "recurrence_type" not in columns:
            self.connection.execute("ALTER TABLE items ADD COLUMN recurrence_type TEXT")
            self.connection.execute(
                "ALTER TABLE items ADD COLUMN recurrence_interval INTEGER NOT NULL DEFAULT 1"
            )
            self.connection.execute("ALTER TABLE items ADD COLUMN recurrence_end_date TEXT")
            self.connection.execute("ALTER TABLE items ADD COLUMN recurrence_end_count INTEGER")
            self.connection.execute(
                "ALTER TABLE items ADD COLUMN recurrence_count INTEGER NOT NULL DEFAULT 0"
            )
            logger.log.info("Migrated schema 6->7: added recurrence columns")

        self.set_schema_version(7)

    def _migrate_schema_7_to_8(self) -> None:
        """Migrate schema from version 7 to 8 (add due_time column)."""
        current_version = self.get_schema_version()
        if current_version >= 8:
            return

        cursor = self.connection.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]

        if "due_time" not in columns:
            self.connection.execute("ALTER TABLE items ADD COLUMN due_time TEXT")
            logger.log.info("Migrated schema 7->8: added due_time column")

        self.set_schema_version(8)

    def _migrate_schema_8_to_9(self) -> None:
        """Migrate schema from version 8 to 9 (add tags column)."""
        current_version = self.get_schema_version()
        if current_version >= 9:
            return

        cursor = self.connection.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]

        if "tags" not in columns:
            self.connection.execute("ALTER TABLE items ADD COLUMN tags TEXT")
            logger.log.info("Migrated schema 8->9: added tags column")

        self.set_schema_version(9)

    def _migrate_schema_9_to_10(self) -> None:
        """Migrate schema from version 9 to 10 (add time_spent column)."""
        current_version = self.get_schema_version()
        if current_version >= 10:
            return

        cursor = self.connection.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]

        if "time_spent" not in columns:
            self.connection.execute(
                "ALTER TABLE items ADD COLUMN time_spent INTEGER NOT NULL DEFAULT 0"
            )
            logger.log.info("Migrated schema 9->10: added time_spent column")

        self.set_schema_version(10)

    def get_schema_version(self) -> int:
        """Get current schema version."""
        cursor = self.connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        row = cursor.fetchone()
        return int(row["value"]) if row else 0

    def set_schema_version(self, version: int) -> None:
        """Set schema version."""
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )

    # Active list management

    def get_active_list_id(self) -> UUID | None:
        """Get the active list ID."""
        cursor = self.connection.execute("SELECT value FROM metadata WHERE key = 'active_list_id'")
        row = cursor.fetchone()
        if row and row["value"]:
            return UUID(row["value"])
        return None

    def set_active_list_id(self, list_id: UUID | None) -> None:
        """Set the active list ID."""
        value = str(list_id) if list_id else None
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('active_list_id', ?)",
            (value,),
        )

    # List operations

    def get_all_lists(self, include_deleted: bool = False) -> list[TodoList]:
        """Get all lists from the database.

        Args:
            include_deleted: Whether to include deleted (tombstoned) lists

        Returns:
            List of TodoList objects
        """
        if include_deleted:
            cursor = self.connection.execute("SELECT * FROM lists")
        else:
            cursor = self.connection.execute("SELECT * FROM lists WHERE deleted = 0")

        lists = []
        for row in cursor:
            lst = self._row_to_list(row)
            lst.items = {item.id: item for item in self.get_items_for_list(lst.id, include_deleted)}
            lists.append(lst)

        return lists

    def get_list(self, list_id: UUID) -> TodoList | None:
        """Get a list by ID.

        Args:
            list_id: UUID of the list

        Returns:
            TodoList or None if not found
        """
        cursor = self.connection.execute("SELECT * FROM lists WHERE id = ?", (str(list_id),))
        row = cursor.fetchone()
        if row is None:
            return None

        lst = self._row_to_list(row)
        lst.items = {
            item.id: item for item in self.get_items_for_list(list_id, include_deleted=True)
        }
        return lst

    def save_list(self, lst: TodoList) -> None:
        """Save a list to the database (insert or update).

        Args:
            lst: TodoList to save
        """
        self.connection.execute(
            """
            INSERT OR REPLACE INTO lists (id, name, created_at, updated_at, deleted, private)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(lst.id),
                lst.name,
                lst.created_at,
                lst.updated_at,
                1 if lst.deleted else 0,
                1 if lst.private else 0,
            ),
        )

    def delete_list(self, list_id: UUID) -> bool:
        """Mark a list as deleted (tombstone).

        Args:
            list_id: UUID of the list to delete

        Returns:
            True if list was found and marked deleted
        """
        cursor = self.connection.execute(
            "UPDATE lists SET deleted = 1, updated_at = ? WHERE id = ?",
            (int(__import__("time").time() * 1000), str(list_id)),
        )
        return cursor.rowcount > 0

    def _row_to_list(self, row: sqlite3.Row) -> TodoList:
        """Convert a database row to a TodoList."""
        # Check if private column exists (for backward compatibility during migration)
        try:
            private = bool(row["private"])
        except (KeyError, IndexError):
            private = False

        return TodoList(
            id=UUID(row["id"]),
            name=row["name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted=bool(row["deleted"]),
            private=private,
            items={},  # Items loaded separately
        )

    # Item operations

    def get_items_for_list(self, list_id: UUID, include_deleted: bool = False) -> list[TodoItem]:
        """Get all items for a list.

        Args:
            list_id: UUID of the list
            include_deleted: Whether to include deleted items

        Returns:
            List of TodoItem objects
        """
        if include_deleted:
            cursor = self.connection.execute(
                "SELECT * FROM items WHERE list_id = ?", (str(list_id),)
            )
        else:
            cursor = self.connection.execute(
                "SELECT * FROM items WHERE list_id = ? AND deleted = 0",
                (str(list_id),),
            )

        return [self._row_to_item(row) for row in cursor]

    def get_item(self, item_id: UUID) -> TodoItem | None:
        """Get an item by ID.

        Args:
            item_id: UUID of the item

        Returns:
            TodoItem or None if not found
        """
        cursor = self.connection.execute("SELECT * FROM items WHERE id = ?", (str(item_id),))
        row = cursor.fetchone()
        return self._row_to_item(row) if row else None

    def save_item(self, list_id: UUID, item: TodoItem) -> None:
        """Save an item to the database (insert or update).

        Args:
            list_id: UUID of the list this item belongs to
            item: TodoItem to save
        """
        import json

        self.connection.execute(
            """
            INSERT OR REPLACE INTO items
            (id, list_id, reminder, priority, complete, due_date, due_time, tags,
             recurrence_type, recurrence_interval, recurrence_end_date,
             recurrence_end_count, recurrence_count, time_spent,
             created_at, updated_at, deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(item.id),
                str(list_id),
                item.reminder,
                item.priority,
                1 if item.complete else 0,
                item.due_date.isoformat() if item.due_date else None,
                item.due_time.isoformat() if item.due_time else None,
                json.dumps(item.tags) if item.tags else None,
                item.recurrence_type,
                item.recurrence_interval,
                item.recurrence_end_date.isoformat() if item.recurrence_end_date else None,
                item.recurrence_end_count,
                item.recurrence_count,
                item.time_spent,
                item.created_at,
                item.updated_at,
                1 if item.deleted else 0,
            ),
        )

    def delete_item(self, item_id: UUID) -> bool:
        """Mark an item as deleted (tombstone).

        Args:
            item_id: UUID of the item to delete

        Returns:
            True if item was found and marked deleted
        """
        cursor = self.connection.execute(
            "UPDATE items SET deleted = 1, updated_at = ? WHERE id = ?",
            (int(__import__("time").time() * 1000), str(item_id)),
        )
        return cursor.rowcount > 0

    def _row_to_item(self, row: sqlite3.Row) -> TodoItem:
        """Convert a database row to a TodoItem."""
        import json
        from datetime import date, time

        # Handle due_date column (may not exist in older databases during migration)
        try:
            due_date_str = row["due_date"]
            due_date = date.fromisoformat(due_date_str) if due_date_str else None
        except (KeyError, IndexError):
            due_date = None

        # Handle due_time column (v8+)
        try:
            due_time_str = row["due_time"]
            due_time = time.fromisoformat(due_time_str) if due_time_str else None
        except (KeyError, IndexError):
            due_time = None

        # Handle tags column (v9+)
        try:
            tags_str = row["tags"]
            tags = json.loads(tags_str) if tags_str else []
        except (KeyError, IndexError):
            tags = []

        # Handle recurrence columns (v7+)
        try:
            recurrence_type = row["recurrence_type"]
            recurrence_interval = row["recurrence_interval"] or 1
            end_date_str = row["recurrence_end_date"]
            recurrence_end_date = date.fromisoformat(end_date_str) if end_date_str else None
            recurrence_end_count = row["recurrence_end_count"]
            recurrence_count = row["recurrence_count"] or 0
        except (KeyError, IndexError):
            recurrence_type = None
            recurrence_interval = 1
            recurrence_end_date = None
            recurrence_end_count = None
            recurrence_count = 0

        # Handle time_spent column (v10+)
        try:
            time_spent = row["time_spent"] or 0
        except (KeyError, IndexError):
            time_spent = 0

        return TodoItem(
            id=UUID(row["id"]),
            reminder=row["reminder"],
            priority=row["priority"],
            complete=bool(row["complete"]),
            due_date=due_date,
            due_time=due_time,
            tags=tags,
            recurrence_type=recurrence_type,
            recurrence_interval=recurrence_interval,
            recurrence_end_date=recurrence_end_date,
            recurrence_end_count=recurrence_end_count,
            recurrence_count=recurrence_count,
            time_spent=time_spent,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted=bool(row["deleted"]),
        )

    # Bulk operations (for sync and migration)

    def load_database(self) -> Database:
        """Load complete database into memory.

        Returns:
            Database object with all lists and items
        """
        db = Database(schema_version=self.get_schema_version())
        db.active_list_id = self.get_active_list_id()

        # Load all lists with items (including deleted for sync)
        for lst in self.get_all_lists(include_deleted=True):
            db.lists[lst.id] = lst

        logger.log.info(
            "Loaded database: %d lists, %d total items",
            len(db.lists),
            sum(len(lst.items) for lst in db.lists.values()),
        )
        return db

    def save_database(self, db: Database) -> None:
        """Save complete database from memory.

        Args:
            db: Database object to save
        """
        with self.transaction():
            # Save active list ID
            self.set_active_list_id(db.active_list_id)

            # Save all lists and items
            for lst in db.lists.values():
                self.save_list(lst)
                for item in lst.items.values():
                    self.save_item(lst.id, item)

        logger.log.info(
            "Saved database: %d lists, %d total items",
            len(db.lists),
            sum(len(lst.items) for lst in db.lists.values()),
        )

    # Device operations

    def get_all_devices(self, include_blocked: bool = False) -> list[Device]:
        """Get all known devices.

        Args:
            include_blocked: Whether to include blocked devices

        Returns:
            List of Device objects
        """
        if include_blocked:
            cursor = self.connection.execute("SELECT * FROM devices")
        else:
            cursor = self.connection.execute("SELECT * FROM devices WHERE trust_level != 'blocked'")
        return [self._row_to_device(row) for row in cursor]

    def get_device(self, device_id: UUID) -> Device | None:
        """Get a device by ID."""
        cursor = self.connection.execute("SELECT * FROM devices WHERE id = ?", (str(device_id),))
        row = cursor.fetchone()
        return self._row_to_device(row) if row else None

    def get_device_by_fingerprint(self, fingerprint: str) -> Device | None:
        """Get a device by its fingerprint."""
        cursor = self.connection.execute(
            "SELECT * FROM devices WHERE fingerprint = ?", (fingerprint,)
        )
        row = cursor.fetchone()
        return self._row_to_device(row) if row else None

    def save_device(self, device: Device) -> None:
        """Save a device (insert or update)."""
        self.connection.execute(
            """
            INSERT OR REPLACE INTO devices
            (id, fingerprint, name, first_seen, last_seen, last_address, trust_level)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(device.id),
                device.fingerprint,
                device.name,
                device.first_seen,
                device.last_seen,
                device.last_address,
                device.trust_level,
            ),
        )

    def delete_device(self, device_id: UUID) -> bool:
        """Delete a device and its group memberships."""
        cursor = self.connection.execute("DELETE FROM devices WHERE id = ?", (str(device_id),))
        return cursor.rowcount > 0

    def update_device_fingerprint(self, device_id: UUID, new_fingerprint: str) -> bool:
        """Update a device's fingerprint (security-sensitive operation)."""
        cursor = self.connection.execute(
            "UPDATE devices SET fingerprint = ?, last_seen = ? WHERE id = ?",
            (new_fingerprint, int(__import__("time").time() * 1000), str(device_id)),
        )
        if cursor.rowcount > 0:
            logger.log.warning(
                "Device fingerprint updated: device_id=%s, new_fingerprint=%s",
                device_id,
                new_fingerprint[:16] + "...",
            )
        return cursor.rowcount > 0

    def _row_to_device(self, row: sqlite3.Row) -> Device:
        """Convert a database row to a Device."""
        return Device(
            id=UUID(row["id"]),
            fingerprint=row["fingerprint"],
            name=row["name"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            last_address=row["last_address"],
            trust_level=row["trust_level"],
        )

    # Sync group operations

    def get_all_sync_groups(self) -> list[SyncGroup]:
        """Get all sync groups."""
        cursor = self.connection.execute("SELECT * FROM sync_groups ORDER BY name")
        return [self._row_to_sync_group(row) for row in cursor]

    def get_sync_group(self, group_id: UUID) -> SyncGroup | None:
        """Get a sync group by ID."""
        cursor = self.connection.execute("SELECT * FROM sync_groups WHERE id = ?", (str(group_id),))
        row = cursor.fetchone()
        return self._row_to_sync_group(row) if row else None

    def get_sync_group_by_name(self, name: str) -> SyncGroup | None:
        """Get a sync group by name."""
        cursor = self.connection.execute("SELECT * FROM sync_groups WHERE name = ?", (name,))
        row = cursor.fetchone()
        return self._row_to_sync_group(row) if row else None

    def save_sync_group(self, group: SyncGroup) -> None:
        """Save a sync group (insert or update)."""
        self.connection.execute(
            """
            INSERT OR REPLACE INTO sync_groups (id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (str(group.id), group.name, group.created_at, group.updated_at),
        )

    def delete_sync_group(self, group_id: UUID) -> bool:
        """Delete a sync group (cascades to device_groups and list_sync_rules)."""
        cursor = self.connection.execute("DELETE FROM sync_groups WHERE id = ?", (str(group_id),))
        return cursor.rowcount > 0

    def _row_to_sync_group(self, row: sqlite3.Row) -> SyncGroup:
        """Convert a database row to a SyncGroup."""
        return SyncGroup(
            id=UUID(row["id"]),
            name=row["name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # Device-group membership operations

    def get_devices_in_group(self, group_id: UUID) -> list[Device]:
        """Get all devices in a sync group."""
        cursor = self.connection.execute(
            """
            SELECT d.* FROM devices d
            JOIN device_groups dg ON d.id = dg.device_id
            WHERE dg.group_id = ?
            """,
            (str(group_id),),
        )
        return [self._row_to_device(row) for row in cursor]

    def get_groups_for_device(self, device_id: UUID) -> list[SyncGroup]:
        """Get all sync groups a device belongs to."""
        cursor = self.connection.execute(
            """
            SELECT g.* FROM sync_groups g
            JOIN device_groups dg ON g.id = dg.group_id
            WHERE dg.device_id = ?
            """,
            (str(device_id),),
        )
        return [self._row_to_sync_group(row) for row in cursor]

    def add_device_to_group(self, device_id: UUID, group_id: UUID) -> None:
        """Add a device to a sync group."""
        self.connection.execute(
            "INSERT OR IGNORE INTO device_groups (device_id, group_id) VALUES (?, ?)",
            (str(device_id), str(group_id)),
        )

    def remove_device_from_group(self, device_id: UUID, group_id: UUID) -> bool:
        """Remove a device from a sync group."""
        cursor = self.connection.execute(
            "DELETE FROM device_groups WHERE device_id = ? AND group_id = ?",
            (str(device_id), str(group_id)),
        )
        return cursor.rowcount > 0

    # List sync rule operations

    def get_sync_rules_for_list(self, list_id: UUID) -> list[ListSyncRule]:
        """Get all sync rules for a list."""
        cursor = self.connection.execute(
            "SELECT * FROM list_sync_rules WHERE list_id = ?", (str(list_id),)
        )
        return [self._row_to_list_sync_rule(row) for row in cursor]

    def get_lists_for_group(self, group_id: UUID) -> list[UUID]:
        """Get all list IDs that sync to a group."""
        cursor = self.connection.execute(
            "SELECT list_id FROM list_sync_rules WHERE group_id = ?", (str(group_id),)
        )
        return [UUID(row["list_id"]) for row in cursor]

    def add_list_sync_rule(self, list_id: UUID, group_id: UUID) -> None:
        """Add a sync rule for a list."""
        self.connection.execute(
            "INSERT OR IGNORE INTO list_sync_rules (list_id, group_id) VALUES (?, ?)",
            (str(list_id), str(group_id)),
        )

    def remove_list_sync_rule(self, list_id: UUID, group_id: UUID) -> bool:
        """Remove a sync rule for a list."""
        cursor = self.connection.execute(
            "DELETE FROM list_sync_rules WHERE list_id = ? AND group_id = ?",
            (str(list_id), str(group_id)),
        )
        return cursor.rowcount > 0

    def clear_list_sync_rules(self, list_id: UUID) -> int:
        """Remove all sync rules for a list (makes it sync everywhere)."""
        cursor = self.connection.execute(
            "DELETE FROM list_sync_rules WHERE list_id = ?", (str(list_id),)
        )
        return cursor.rowcount

    def get_syncable_list_ids_for_device(self, device_id: UUID) -> set[UUID]:
        """Get list IDs that should sync to a specific device.

        A list syncs to a device if:
        1. The list is not private
        2. AND either:
           a. The list has no sync rules (syncs everywhere)
           b. OR the list has a rule for a group the device is in

        Returns:
            Set of list IDs that should sync to this device
        """
        # Get all groups this device is in
        device_groups = self.get_groups_for_device(device_id)
        device_group_ids = {g.id for g in device_groups}

        # Get all non-private, non-deleted lists
        cursor = self.connection.execute("SELECT id FROM lists WHERE private = 0 AND deleted = 0")
        all_list_ids = {UUID(row["id"]) for row in cursor}

        # For each list, check if it should sync to this device
        syncable_list_ids = set()

        for list_id in all_list_ids:
            rules = self.get_sync_rules_for_list(list_id)

            if not rules:
                # No rules = syncs everywhere
                syncable_list_ids.add(list_id)
            else:
                # Has rules - check if any rule group matches device groups
                rule_group_ids = {r.group_id for r in rules}
                if rule_group_ids & device_group_ids:  # Intersection
                    syncable_list_ids.add(list_id)

        return syncable_list_ids

    def _row_to_list_sync_rule(self, row: sqlite3.Row) -> ListSyncRule:
        """Convert a database row to a ListSyncRule."""
        return ListSyncRule(
            list_id=UUID(row["list_id"]),
            group_id=UUID(row["group_id"]),
        )

    # Pending sync operations

    def get_pending_syncs_for_device(self, device_id: UUID) -> list[PendingSync]:
        """Get all pending syncs for a device."""
        cursor = self.connection.execute(
            "SELECT * FROM pending_syncs WHERE device_id = ? ORDER BY created_at",
            (str(device_id),),
        )
        return [self._row_to_pending_sync(row) for row in cursor]

    def get_all_pending_syncs(self) -> list[PendingSync]:
        """Get all pending syncs."""
        cursor = self.connection.execute("SELECT * FROM pending_syncs ORDER BY created_at")
        return [self._row_to_pending_sync(row) for row in cursor]

    def save_pending_sync(self, pending: PendingSync) -> None:
        """Save a pending sync."""
        import json

        list_ids_json = json.dumps([str(lid) for lid in pending.list_ids])
        self.connection.execute(
            """
            INSERT OR REPLACE INTO pending_syncs
            (id, device_id, list_ids, created_at, expires_at, attempts, last_attempt)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(pending.id),
                str(pending.device_id),
                list_ids_json,
                pending.created_at,
                pending.expires_at,
                pending.attempts,
                pending.last_attempt,
            ),
        )

    def delete_pending_sync(self, pending_id: UUID) -> bool:
        """Delete a pending sync."""
        cursor = self.connection.execute(
            "DELETE FROM pending_syncs WHERE id = ?", (str(pending_id),)
        )
        return cursor.rowcount > 0

    def delete_expired_pending_syncs(self) -> int:
        """Delete all expired pending syncs."""
        now = int(__import__("time").time() * 1000)
        cursor = self.connection.execute("DELETE FROM pending_syncs WHERE expires_at < ?", (now,))
        if cursor.rowcount > 0:
            logger.log.info("Deleted %d expired pending syncs", cursor.rowcount)
        return cursor.rowcount

    def _row_to_pending_sync(self, row: sqlite3.Row) -> PendingSync:
        """Convert a database row to a PendingSync."""
        import json

        list_ids_json = row["list_ids"]
        list_ids = [UUID(lid) for lid in json.loads(list_ids_json)] if list_ids_json else []

        return PendingSync(
            id=UUID(row["id"]),
            device_id=UUID(row["device_id"]),
            list_ids=list_ids,
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            attempts=row["attempts"],
            last_attempt=row["last_attempt"],
        )

    def clear(self) -> None:
        """Clear all data from the database (for testing)."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM pending_syncs")
            conn.execute("DELETE FROM list_sync_rules")
            conn.execute("DELETE FROM device_groups")
            conn.execute("DELETE FROM sync_groups")
            conn.execute("DELETE FROM devices")
            conn.execute("DELETE FROM items")
            conn.execute("DELETE FROM lists")
            conn.execute("DELETE FROM metadata WHERE key != 'schema_version'")
