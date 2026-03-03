"""Tests for private lists feature."""

import tempfile
import time
from pathlib import Path

from pytodo_qt.core.database import SCHEMA_VERSION, DatabaseStorage
from pytodo_qt.core.models import Database, TodoItem, TodoList, create_todo_list


class TestPrivateListModel:
    """Tests for private flag on TodoList model."""

    def test_default_is_not_private(self):
        """Test that new lists are shared by default."""
        lst = create_todo_list("My List")
        assert lst.private is False

    def test_toggle_private(self):
        """Test toggling private status updates field and timestamp."""
        lst = create_todo_list("My List")
        original_updated = lst.updated_at
        assert lst.private is False

        time.sleep(0.002)  # Ensure timestamp advances
        lst.toggle_private()

        assert lst.private is True
        assert lst.updated_at >= original_updated

        lst.toggle_private()
        assert lst.private is False

    def test_serialization_includes_private(self):
        """Test that to_dict includes private field."""
        lst = create_todo_list("My List")
        lst.private = True

        data = lst.to_dict()

        assert "private" in data
        assert data["private"] is True

    def test_from_dict_backward_compatible(self):
        """Test that missing private field defaults to False."""
        data = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "name": "Old List",
            "items": {},
            "created_at": 1234567890000,
            "updated_at": 1234567890000,
            "deleted": False,
            # Note: no "private" field
        }

        lst = TodoList.from_dict(data)

        assert lst.private is False

    def test_from_dict_with_private(self):
        """Test that private field is read from dict."""
        data = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "name": "Private List",
            "items": {},
            "created_at": 1234567890000,
            "updated_at": 1234567890000,
            "deleted": False,
            "private": True,
        }

        lst = TodoList.from_dict(data)

        assert lst.private is True


class TestDatabaseSyncFiltering:
    """Tests for to_dict_for_sync excluding private lists."""

    def test_to_dict_for_sync_excludes_private(self):
        """Test that private lists are excluded from sync data."""
        db = Database()

        # Add a shared list
        shared_list = create_todo_list("Shared")
        shared_list.add_item(TodoItem(reminder="Shared task"))
        db.add_list(shared_list)

        # Add a private list
        private_list = create_todo_list("Private")
        private_list.private = True
        private_list.add_item(TodoItem(reminder="Private task"))
        db.add_list(private_list)

        # Get sync data
        sync_data = db.to_dict_for_sync()

        # Only shared list should be in sync data
        assert len(sync_data["lists"]) == 1
        assert str(shared_list.id) in sync_data["lists"]
        assert str(private_list.id) not in sync_data["lists"]

    def test_to_dict_includes_all_lists(self):
        """Test that regular to_dict includes all lists."""
        db = Database()

        shared_list = create_todo_list("Shared")
        db.add_list(shared_list)

        private_list = create_todo_list("Private")
        private_list.private = True
        db.add_list(private_list)

        # Regular to_dict includes both
        data = db.to_dict()
        assert len(data["lists"]) == 2

    def test_all_lists_private_results_in_empty_sync(self):
        """Test that all-private lists result in empty sync data."""
        db = Database()

        private_list1 = create_todo_list("Private 1")
        private_list1.private = True
        db.add_list(private_list1)

        private_list2 = create_todo_list("Private 2")
        private_list2.private = True
        db.add_list(private_list2)

        sync_data = db.to_dict_for_sync()

        assert len(sync_data["lists"]) == 0


class TestDatabaseStoragePrivate:
    """Tests for SQLite storage of private lists."""

    def test_save_and_load_private_list(self):
        """Test saving and loading a private list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Private List")
            lst.private = True
            storage.save_list(lst)

            retrieved = storage.get_list(lst.id)

            assert retrieved is not None
            assert retrieved.private is True
            storage.close()

    def test_save_and_load_shared_list(self):
        """Test that shared lists have private=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Shared List")
            storage.save_list(lst)

            retrieved = storage.get_list(lst.id)

            assert retrieved is not None
            assert retrieved.private is False
            storage.close()

    def test_database_round_trip_preserves_private(self):
        """Test that save_database/load_database preserves private flag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            db = Database()
            private_list = create_todo_list("Private")
            private_list.private = True
            private_list.add_item(TodoItem(reminder="Secret task"))
            db.add_list(private_list)

            shared_list = create_todo_list("Shared")
            db.add_list(shared_list)

            storage.save_database(db)

            loaded = storage.load_database()

            loaded_private = loaded.get_list(private_list.id)
            assert loaded_private is not None
            assert loaded_private.private is True

            loaded_shared = loaded.get_list(shared_list.id)
            assert loaded_shared is not None
            assert loaded_shared.private is False

            storage.close()


class TestSchemaMigration:
    """Tests for schema migration v3 to v4 (private column)."""

    def test_schema_version_is_current(self):
        """Test that current schema version is 8."""
        assert SCHEMA_VERSION == 8

    def test_new_database_has_private_column(self):
        """Test that new database has private column."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            # Check that private column exists
            cursor = storage.connection.execute("PRAGMA table_info(lists)")
            columns = [row[1] for row in cursor.fetchall()]

            assert "private" in columns
            storage.close()

    def test_migration_adds_private_column(self):
        """Test that migration adds private column to existing database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create a v3 database manually without private column
            import sqlite3

            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            conn.execute(
                """
                CREATE TABLE lists (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                )
            """
            )
            conn.execute(
                """
                CREATE TABLE items (
                    id TEXT PRIMARY KEY,
                    list_id TEXT NOT NULL,
                    reminder TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 2,
                    complete INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                )
            """
            )
            conn.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '3')")
            conn.execute(
                """
                INSERT INTO lists (id, name, created_at, updated_at, deleted)
                VALUES ('test-id', 'Test List', 1234567890000, 1234567890000, 0)
            """
            )
            conn.commit()
            conn.close()

            # Now open with DatabaseStorage which should run migration
            storage = DatabaseStorage(db_path)
            storage.open()

            # Check that private column was added
            cursor = storage.connection.execute("PRAGMA table_info(lists)")
            columns = [row[1] for row in cursor.fetchall()]
            assert "private" in columns

            # Check schema version was updated (migrates through v4 to v5 to v6 to v7 to v8)
            assert storage.get_schema_version() == 8

            # Check existing list has private=0 (False)
            cursor = storage.connection.execute("SELECT private FROM lists WHERE id = 'test-id'")
            row = cursor.fetchone()
            assert row[0] == 0

            storage.close()
