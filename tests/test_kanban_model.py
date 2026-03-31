"""Tests for kanban board data model, serialization, and schema migration."""

import sqlite3
from pathlib import Path
from uuid import uuid4

from pytodo_qt.core.database import SCHEMA_VERSION, DatabaseStorage
from pytodo_qt.core.models import TodoItem, TodoList, create_todo_item, create_todo_list


class TestTodoItemBoardColumn:
    """Tests for board_column field on TodoItem."""

    def test_default_empty(self):
        item = create_todo_item("Test")
        assert item.board_column == ""

    def test_explicit_column(self):
        item = create_todo_item("Test", board_column="In Progress")
        assert item.board_column == "In Progress"

    def test_serialization_roundtrip(self):
        item = create_todo_item("Test", board_column="Done")
        d = item.to_dict()
        assert d["board_column"] == "Done"
        restored = TodoItem.from_dict(d)
        assert restored.board_column == "Done"

    def test_backward_compat_missing_field(self):
        """Older serialized data without board_column should default to empty."""
        d = create_todo_item("Test").to_dict()
        del d["board_column"]
        restored = TodoItem.from_dict(d)
        assert restored.board_column == ""


class TestTodoListBoardColumns:
    """Tests for board_columns and wip_limits on TodoList."""

    def test_default_columns(self):
        lst = create_todo_list("Test")
        assert lst.board_columns == ["To Do", "In Progress", "Done"]

    def test_default_wip_limits(self):
        lst = create_todo_list("Test")
        assert lst.wip_limits == {}

    def test_get_wip_limit_no_limit(self):
        lst = create_todo_list("Test")
        assert lst.get_wip_limit("In Progress") == 0

    def test_set_and_get_wip_limit(self):
        lst = create_todo_list("Test")
        lst.set_wip_limit("In Progress", 3)
        assert lst.get_wip_limit("In Progress") == 3

    def test_remove_wip_limit(self):
        lst = create_todo_list("Test")
        lst.set_wip_limit("In Progress", 3)
        lst.set_wip_limit("In Progress", 0)
        assert lst.get_wip_limit("In Progress") == 0
        assert "In Progress" not in lst.wip_limits

    def test_serialization_roundtrip(self):
        lst = create_todo_list("Test")
        lst.board_columns = ["Backlog", "Active", "Review", "Done"]
        d = lst.to_dict()
        assert d["board_columns"] == ["Backlog", "Active", "Review", "Done"]
        restored = TodoList.from_dict(d)
        assert restored.board_columns == ["Backlog", "Active", "Review", "Done"]

    def test_serialization_with_wip_limits(self):
        lst = create_todo_list("Test")
        lst.set_wip_limit("In Progress", 5)
        d = lst.to_dict()
        assert d["wip_limits"] == {"In Progress": 5}
        restored = TodoList.from_dict(d)
        assert restored.wip_limits == {"In Progress": 5}

    def test_backward_compat_missing_fields(self):
        """Older serialized data without board_columns/wip_limits should use defaults."""
        d = create_todo_list("Test").to_dict()
        del d["board_columns"]
        del d["wip_limits"]
        restored = TodoList.from_dict(d)
        assert restored.board_columns == ["To Do", "In Progress", "Done"]
        assert restored.wip_limits == {}


class TestSchemaV14Migration:
    """Tests for schema migration from v13 to v14."""

    def test_schema_version_is_14(self):
        assert SCHEMA_VERSION == 17

    def test_fresh_database_has_board_columns(self, tmp_path: Path):
        """A new database should have board_column on items and board_columns on lists."""
        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()

        assert storage.get_schema_version() == 17

        # Check items table has board_column
        cursor = storage.connection.execute("PRAGMA table_info(items)")
        item_cols = [row[1] for row in cursor]
        assert "board_column" in item_cols

        # Check lists table has board_columns
        cursor = storage.connection.execute("PRAGMA table_info(lists)")
        list_cols = [row[1] for row in cursor]
        assert "board_columns" in list_cols

        storage.close()

    def test_migration_from_v13(self, tmp_path: Path):
        """Opening a v13 database should migrate to v14."""
        db_path = tmp_path / "v13.db"

        # Create a v13 database manually
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)""")
        conn.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '13')")
        conn.execute(
            """CREATE TABLE lists (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                private INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute(
            """CREATE TABLE items (
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
                pomodoro_count INTEGER NOT NULL DEFAULT 0,
                estimated_pomodoros INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                parent_id TEXT,
                FOREIGN KEY (list_id) REFERENCES lists(id)
            )"""
        )
        conn.execute(
            """CREATE TABLE focus_sessions (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                list_id TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                completed INTEGER NOT NULL DEFAULT 1,
                session_type TEXT NOT NULL DEFAULT 'work',
                date TEXT NOT NULL
            )"""
        )

        # Insert test data
        list_id = str(uuid4())
        item_id = str(uuid4())
        now = 1000000
        conn.execute(
            "INSERT INTO lists (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (list_id, "Test List", now, now),
        )
        conn.execute(
            """INSERT INTO items (id, list_id, reminder, priority, complete,
               created_at, updated_at, deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, list_id, "Test item", 2, 0, now, now, 0),
        )
        conn.commit()
        conn.close()

        # Open with DatabaseStorage — should migrate
        storage = DatabaseStorage(db_path)
        storage.open()

        assert storage.get_schema_version() == 17

        # Verify columns exist
        cursor = storage.connection.execute("PRAGMA table_info(items)")
        item_cols = [row[1] for row in cursor]
        assert "board_column" in item_cols

        cursor = storage.connection.execute("PRAGMA table_info(lists)")
        list_cols = [row[1] for row in cursor]
        assert "board_columns" in list_cols

        # Verify existing data survived migration
        from uuid import UUID

        item = storage.get_item(UUID(item_id))
        assert item is not None
        assert item.reminder == "Test item"
        assert item.board_column == ""

        storage.close()


class TestSQLiteRoundTrip:
    """Tests for board_column/board_columns through SQLite save/load."""

    def test_item_board_column_roundtrip(self, tmp_path: Path):
        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()

        lst = create_todo_list("Test")
        storage.save_list(lst)

        item = create_todo_item("Test", board_column="In Progress")
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.board_column == "In Progress"

        storage.close()

    def test_list_board_columns_roundtrip(self, tmp_path: Path):
        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()

        lst = create_todo_list("Test")
        lst.board_columns = ["Backlog", "Active", "Review", "Done"]
        storage.save_list(lst)

        # Load it back
        loaded_lists = storage.get_all_lists()
        assert len(loaded_lists) == 1
        assert loaded_lists[0].board_columns == ["Backlog", "Active", "Review", "Done"]

        storage.close()

    def test_list_with_wip_limits_roundtrip(self, tmp_path: Path):
        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()

        lst = create_todo_list("Test")
        lst.set_wip_limit("In Progress", 3)
        storage.save_list(lst)

        loaded_lists = storage.get_all_lists()
        assert len(loaded_lists) == 1
        assert loaded_lists[0].board_columns == ["To Do", "In Progress", "Done"]
        assert loaded_lists[0].wip_limits == {"In Progress": 3}

        storage.close()

    def test_list_without_board_columns_defaults(self, tmp_path: Path):
        """A list saved without board_columns (NULL in DB) should get defaults."""
        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()

        # Insert a list with NULL board_columns directly
        storage.connection.execute(
            """INSERT INTO lists (id, name, created_at, updated_at, deleted, private, board_columns)
               VALUES (?, ?, ?, ?, 0, 0, NULL)""",
            (str(uuid4()), "Manual", 1000, 1000),
        )
        storage.connection.commit()

        loaded = storage.get_all_lists()
        assert len(loaded) == 1
        assert loaded[0].board_columns == ["To Do", "In Progress", "Done"]
        assert loaded[0].wip_limits == {}

        storage.close()
