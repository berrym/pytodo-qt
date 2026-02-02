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
from .models import Database, TodoItem, TodoList

if TYPE_CHECKING:
    pass

logger = Logger(__name__)

# Schema version for SQLite database (continues from JSON schema_version=2)
SCHEMA_VERSION = 3

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
    deleted INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    list_id TEXT NOT NULL,
    reminder TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 2,
    complete INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (list_id) REFERENCES lists(id)
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_lists_deleted ON lists(deleted)",
    "CREATE INDEX IF NOT EXISTS idx_lists_name ON lists(name)",
    "CREATE INDEX IF NOT EXISTS idx_items_list_id ON items(list_id)",
    "CREATE INDEX IF NOT EXISTS idx_items_deleted ON items(deleted)",
    "CREATE INDEX IF NOT EXISTS idx_items_complete ON items(complete)",
    "CREATE INDEX IF NOT EXISTS idx_items_priority ON items(priority)",
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

        conn.execute(_CREATE_METADATA_TABLE)
        conn.execute(_CREATE_LISTS_TABLE)
        conn.execute(_CREATE_ITEMS_TABLE)

        for index_sql in _CREATE_INDEXES:
            conn.execute(index_sql)

        # Set schema version if not present
        cursor = conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        if cursor.fetchone() is None:
            conn.execute(
                "INSERT INTO metadata (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

        logger.log.debug("Database schema initialized")

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
            INSERT OR REPLACE INTO lists (id, name, created_at, updated_at, deleted)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(lst.id),
                lst.name,
                lst.created_at,
                lst.updated_at,
                1 if lst.deleted else 0,
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
        return TodoList(
            id=UUID(row["id"]),
            name=row["name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted=bool(row["deleted"]),
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
        self.connection.execute(
            """
            INSERT OR REPLACE INTO items
            (id, list_id, reminder, priority, complete, created_at, updated_at, deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(item.id),
                str(list_id),
                item.reminder,
                item.priority,
                1 if item.complete else 0,
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
        return TodoItem(
            id=UUID(row["id"]),
            reminder=row["reminder"],
            priority=row["priority"],
            complete=bool(row["complete"]),
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

    def clear(self) -> None:
        """Clear all data from the database (for testing)."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM items")
            conn.execute("DELETE FROM lists")
            conn.execute("DELETE FROM metadata WHERE key != 'schema_version'")
