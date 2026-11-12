"""Tests for SQLite database storage layer."""

import tempfile
from datetime import date, time
from pathlib import Path
from uuid import uuid4

import pytest

from pytodo_qt.core.database import SCHEMA_VERSION, DatabaseStorage
from pytodo_qt.core.models import Database, TodoItem, TodoList


class TestDatabaseStorageBasics:
    """Basic tests for DatabaseStorage."""

    def test_create_storage(self):
        """Test creating a DatabaseStorage instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)

            assert storage.db_path == db_path
            assert storage._connection is None

    def test_open_creates_database(self):
        """Test that open() creates the database file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)

            storage.open()

            assert db_path.exists()
            storage.close()

    def test_open_creates_parent_directories(self):
        """Test that open() creates parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "subdir" / "nested" / "test.db"
            storage = DatabaseStorage(db_path)

            storage.open()

            assert db_path.exists()
            storage.close()

    def test_close_connection(self):
        """Test closing the database connection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)

            storage.open()
            assert storage._connection is not None

            storage.close()
            assert storage._connection is None

    def test_connection_property_opens_if_needed(self):
        """Test that connection property auto-opens."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)

            # Access connection without explicit open()
            conn = storage.connection

            assert conn is not None
            assert db_path.exists()
            storage.close()


class TestSchemaVersion:
    """Tests for schema version management."""

    def test_initial_schema_version(self):
        """Test that new database has correct schema version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            version = storage.get_schema_version()

            assert version == SCHEMA_VERSION
            storage.close()

    def test_set_schema_version(self):
        """Test setting schema version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            storage.set_schema_version(99)

            assert storage.get_schema_version() == 99
            storage.close()

    def test_schema_version_is_at_least_19(self):
        """Sentinel: completed_at column was introduced in v19."""
        assert SCHEMA_VERSION >= 19


class TestSchemaMigrationV18ToV19:
    """Tests for the v18 -> v19 migration adding completed_at."""

    def test_migration_adds_completed_at_column(self):
        """A v18 database is upgraded to v19 with the completed_at column."""
        import sqlite3

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Build a minimal v18-shaped items table directly, without v19's column.
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '18')")
            conn.execute(
                """
                CREATE TABLE items (
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
                    missed_recurrences INTEGER NOT NULL DEFAULT 0,
                    time_spent INTEGER NOT NULL DEFAULT 0,
                    pomodoro_count INTEGER NOT NULL DEFAULT 0,
                    estimated_pomodoros INTEGER NOT NULL DEFAULT 0,
                    estimated_minutes INTEGER NOT NULL DEFAULT 0,
                    work_duration INTEGER NOT NULL DEFAULT 0,
                    break_duration INTEGER NOT NULL DEFAULT 0,
                    long_break_duration INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    parent_id TEXT,
                    board_column TEXT NOT NULL DEFAULT '',
                    due_time_end TEXT,
                    due_time_block TEXT,
                    event_date TEXT,
                    remind_before_days INTEGER NOT NULL DEFAULT 0,
                    reminder_cadence TEXT NOT NULL DEFAULT 'none',
                    notified_at INTEGER NOT NULL DEFAULT 0,
                    conditions TEXT
                )
                """
            )
            # Insert an existing complete row (no completed_at — pre-v19 data)
            conn.execute(
                "INSERT INTO items (id, list_id, reminder, complete, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), str(uuid4()), "Old completed task", 1, 0, 0),
            )
            conn.commit()
            conn.close()

            # Now open via DatabaseStorage — migration runs automatically
            storage = DatabaseStorage(db_path)
            storage.open()

            try:
                # After migration we must be at least v19 (where completed_at landed).
                assert storage.get_schema_version() >= 19
                cols = [row[1] for row in storage.connection.execute("PRAGMA table_info(items)")]
                assert "completed_at" in cols
                # Existing row's completed_at must be NULL — no backfill
                cursor = storage.connection.execute(
                    "SELECT completed_at FROM items WHERE complete = 1"
                )
                row = cursor.fetchone()
                assert row is not None
                assert row["completed_at"] is None
            finally:
                storage.close()

    def test_migration_is_idempotent(self):
        """Running open() twice on an already-current database does not error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            assert storage.get_schema_version() == SCHEMA_VERSION
            storage.close()

            storage2 = DatabaseStorage(db_path)
            storage2.open()
            assert storage2.get_schema_version() == SCHEMA_VERSION
            storage2.close()


class TestSchemaMigrationToV22:
    """v22 adds the device-local notification log and keeps items intact."""

    def _make_v21_database(self, db_path: Path) -> tuple[str, str]:
        """Create a current database, then rewind it to the v21 shape:
        no notification_log table, version 21, one stored item."""
        storage = DatabaseStorage(db_path)
        storage.open()
        lst = TodoList(name="Errands")
        storage.save_list(lst)
        item = TodoItem(reminder="Renew passport")
        storage.save_item(lst.id, item)
        storage.connection.execute("DROP TABLE notification_log")
        storage.connection.execute("UPDATE items SET notified_at = 1700000000000")
        storage.set_schema_version(21)
        storage.close()
        return str(item.id), str(lst.id)

    def test_migration_creates_log_and_bumps_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            self._make_v21_database(db_path)

            storage = DatabaseStorage(db_path)
            storage.open()
            try:
                assert storage.get_schema_version() == SCHEMA_VERSION
                assert SCHEMA_VERSION >= 22
                tables = {
                    row[0]
                    for row in storage.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                assert "notification_log" in tables
                assert storage.get_fired_notifications() == set()
            finally:
                storage.close()

    def test_migration_keeps_items_and_the_notified_at_column(self):
        """Builds through v0.3.11b8 share the database file and still name
        notified_at when saving an item, so the column must survive."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            item_id, list_id = self._make_v21_database(db_path)

            storage = DatabaseStorage(db_path)
            storage.open()
            try:
                cols = [row[1] for row in storage.connection.execute("PRAGMA table_info(items)")]
                assert "notified_at" in cols
                row = storage.connection.execute(
                    "SELECT reminder, notified_at FROM items WHERE id = ?", (item_id,)
                ).fetchone()
                assert row["reminder"] == "Renew passport"
                assert row["notified_at"] == 1700000000000
                # An insert that names the column, as an older build's
                # save does, still succeeds.
                storage.connection.execute(
                    "INSERT INTO items (id, list_id, reminder, notified_at, created_at, updated_at) "
                    "VALUES (?, ?, 'From an older build', 5, 0, 0)",
                    (str(uuid4()), list_id),
                )
            finally:
                storage.close()

    def test_fresh_database_has_the_notified_at_column(self):
        """A database first created by this version must also be usable
        by an older build pointed at the same file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = DatabaseStorage(Path(tmpdir) / "test.db")
            storage.open()
            try:
                cols = [row[1] for row in storage.connection.execute("PRAGMA table_info(items)")]
                assert "notified_at" in cols
            finally:
                storage.close()


class TestSchemaMigrationToV23:
    """v23 removes the stand-in clock time that a part of the day used to
    be stored with, from open items that have a time block."""

    STAMP = 1700000000000

    def _migrate(self, db_path: Path, items: dict[str, TodoItem]) -> dict[str, TodoItem]:
        """Store the items at v22, reopen to migrate, and return them reloaded."""
        storage = DatabaseStorage(db_path)
        storage.open()
        lst = TodoList(name="Errands")
        storage.save_list(lst)
        for item in items.values():
            storage.save_item(lst.id, item)
        storage.connection.execute("UPDATE items SET updated_at = ?", (self.STAMP,))
        storage.set_schema_version(22)
        storage.close()

        storage = DatabaseStorage(db_path)
        storage.open()
        try:
            assert storage.get_schema_version() == SCHEMA_VERSION
            assert SCHEMA_VERSION >= 23
            reloaded = {}
            for name, item in items.items():
                found = storage.get_item(item.id)
                assert found is not None
                reloaded[name] = found
            return reloaded
        finally:
            storage.close()

    def test_stand_in_times_are_removed_from_open_block_items(self):
        day = date(2026, 4, 10)
        items = {
            "morning": TodoItem(
                reminder="a", due_date=day, due_time=time(9, 0), due_time_block="morning"
            ),
            "first thing": TodoItem(
                reminder="b", due_date=day, due_time=time(9, 0), due_time_block="early_morning"
            ),
            "afternoon": TodoItem(
                reminder="c", due_date=day, due_time=time(14, 0), due_time_block="afternoon"
            ),
            "evening": TodoItem(
                reminder="d", due_date=day, due_time=time(18, 0), due_time_block="evening"
            ),
            "tonight": TodoItem(
                reminder="e", due_date=day, due_time=time(20, 0), due_time_block="evening"
            ),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            reloaded = self._migrate(Path(tmpdir) / "test.db", items)

        for name, item in reloaded.items():
            assert item.due_time is None, name
            assert item.due_time_block == items[name].due_time_block, name
            assert item.due_date == day, name
            # Stamped as edited, so the change wins on the next sync.
            assert item.updated_at > self.STAMP, name

    def test_other_items_are_left_alone(self):
        day = date(2026, 4, 10)
        done = TodoItem(
            reminder="done", due_date=day, due_time=time(14, 0), due_time_block="afternoon"
        )
        done.complete = True
        gone = TodoItem(
            reminder="gone", due_date=day, due_time=time(14, 0), due_time_block="afternoon"
        )
        gone.deleted = True
        items = {
            "completed": done,
            "deleted": gone,
            "chosen time": TodoItem(
                reminder="x", due_date=day, due_time=time(15, 30), due_time_block="afternoon"
            ),
            "event": TodoItem(
                reminder="y",
                due_date=day,
                due_time=time(14, 0),
                due_time_end=time(15, 0),
                due_time_block="afternoon",
            ),
            "no block": TodoItem(reminder="z", due_date=day, due_time=time(14, 0)),
            "block only": TodoItem(reminder="w", due_date=day, due_time_block="late_afternoon"),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            reloaded = self._migrate(Path(tmpdir) / "test.db", items)

        for name, item in reloaded.items():
            assert item.due_time == items[name].due_time, name
            assert item.due_time_block == items[name].due_time_block, name
            assert item.updated_at == self.STAMP, name

    def test_migration_runs_once(self):
        """An item given 14:00 and the afternoon block after the migration
        chose that time, and keeps it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            lst = TodoList(name="Errands")
            storage.save_list(lst)
            item = TodoItem(
                reminder="Call",
                due_date=date(2026, 4, 10),
                due_time=time(14, 0),
                due_time_block="afternoon",
            )
            storage.save_item(lst.id, item)
            storage.close()

            storage = DatabaseStorage(db_path)
            storage.open()
            try:
                found = storage.get_item(item.id)
                assert found is not None
                assert found.due_time == time(14, 0)
            finally:
                storage.close()


class TestNotificationLog:
    """The record of which notifications have fired."""

    @pytest.fixture
    def storage(self, tmp_path):
        s = DatabaseStorage(tmp_path / "test.db")
        s.open()
        yield s
        s.close()

    def test_empty_by_default(self, storage):
        assert storage.get_fired_notifications() == set()

    def test_record_and_read_back(self, storage):
        item_id = uuid4()
        storage.record_notification(item_id, "lead", "2026-11-12T15:00")
        assert storage.get_fired_notifications() == {(str(item_id), "lead", "2026-11-12T15:00")}

    def test_notification_without_an_item_uses_empty_id(self, storage):
        storage.record_notification(None, "summary", "2026-11-12")
        assert storage.get_fired_notifications() == {("", "summary", "2026-11-12")}

    def test_kinds_and_occurrences_are_distinct_keys(self, storage):
        item_id = uuid4()
        storage.record_notification(item_id, "lead", "2026-11-12T15:00")
        storage.record_notification(item_id, "due_now", "2026-11-12T15:00")
        storage.record_notification(item_id, "lead", "2026-11-13T15:00")
        assert len(storage.get_fired_notifications()) == 3

    def test_record_several_keys_at_once(self, storage):
        item_id = str(uuid4())
        storage.record_notifications(
            [(item_id, "lead", "2026-11-12T15:00"), ("", "summary", "2026-11-12")], fired_at=7
        )
        assert storage.get_fired_notifications() == {
            (item_id, "lead", "2026-11-12T15:00"),
            ("", "summary", "2026-11-12"),
        }
        rows = storage.connection.execute("SELECT fired_at FROM notification_log").fetchall()
        assert {row["fired_at"] for row in rows} == {7}

    def test_record_several_keys_ignores_ones_already_recorded(self, storage):
        storage.record_notification(None, "summary", "2026-11-12", fired_at=1)
        storage.record_notifications([("", "summary", "2026-11-12")], fired_at=2)
        row = storage.connection.execute("SELECT fired_at FROM notification_log").fetchone()
        assert row["fired_at"] == 1

    def test_record_no_keys(self, storage):
        storage.record_notifications([])
        assert storage.get_fired_notifications() == set()

    def test_recording_twice_keeps_the_first_timestamp(self, storage):
        item_id = uuid4()
        storage.record_notification(item_id, "lead", "2026-11-12T15:00", fired_at=100)
        storage.record_notification(item_id, "lead", "2026-11-12T15:00", fired_at=200)
        rows = storage.connection.execute("SELECT fired_at FROM notification_log").fetchall()
        assert [row["fired_at"] for row in rows] == [100]

    def test_fired_at_defaults_to_now(self, storage):
        storage.record_notification(uuid4(), "lead", "2026-11-12T15:00")
        row = storage.connection.execute("SELECT fired_at FROM notification_log").fetchone()
        assert row["fired_at"] > 1_700_000_000_000

    def test_prune_removes_older_dates_and_datetimes(self, storage):
        item_id = uuid4()
        storage.record_notification(None, "summary", "2026-10-01")
        storage.record_notification(item_id, "lead", "2026-10-01T09:00")
        storage.record_notification(None, "summary", "2026-11-12")
        storage.record_notification(item_id, "lead", "2026-11-12T09:00")

        removed = storage.prune_notification_log("2026-10-15")

        assert removed == 2
        assert storage.get_fired_notifications() == {
            ("", "summary", "2026-11-12"),
            (str(item_id), "lead", "2026-11-12T09:00"),
        }

    def test_recording_does_not_touch_the_item(self, storage):
        """Notifying must not look like an edit: the item row, and with
        it the updated_at that drives sync, is left alone."""
        lst = TodoList(name="Errands")
        storage.save_list(lst)
        item = TodoItem(reminder="Renew passport")
        storage.save_item(lst.id, item)
        before = dict(
            storage.connection.execute(
                "SELECT * FROM items WHERE id = ?", (str(item.id),)
            ).fetchone()
        )

        storage.record_notification(item.id, "lead", "2026-11-12T15:00")

        after = dict(
            storage.connection.execute(
                "SELECT * FROM items WHERE id = ?", (str(item.id),)
            ).fetchone()
        )
        assert after == before

    def test_clear_empties_the_log(self, storage):
        storage.record_notification(None, "summary", "2026-11-12")
        storage.clear()
        assert storage.get_fired_notifications() == set()

    def test_item_round_trip_without_notified_at(self, storage):
        """TodoItem no longer carries notified_at; saving and loading an
        item works with the column left at its default."""
        lst = TodoList(name="Errands")
        storage.save_list(lst)
        item = TodoItem(reminder="Renew passport")
        storage.save_item(lst.id, item)

        loaded = storage.get_items_for_list(lst.id)
        assert [i.reminder for i in loaded] == ["Renew passport"]
        assert not hasattr(loaded[0], "notified_at")
        assert "notified_at" not in loaded[0].to_dict()

    def test_item_from_dict_ignores_notified_at_from_an_older_peer(self):
        payload = TodoItem(reminder="From a peer").to_dict()
        payload["notified_at"] = 1700000000000
        assert TodoItem.from_dict(payload).reminder == "From a peer"


class TestCompletedAtField:
    """Tests that completed_at round-trips through save_item / get_item."""

    def test_save_and_get_item_with_completed_at(self):
        """Saving an item with completed_at preserves the timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            item = TodoItem(reminder="Done", complete=True, completed_at=1_700_000_000_000)
            storage.save_item(lst.id, item)

            retrieved = storage.get_item(item.id)
            assert retrieved is not None
            assert retrieved.complete is True
            assert retrieved.completed_at == 1_700_000_000_000
            storage.close()

    def test_save_and_get_item_with_null_completed_at(self):
        """A complete item with NULL completed_at round-trips as None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            item = TodoItem(reminder="Done but unknown", complete=True)
            assert item.completed_at is None
            storage.save_item(lst.id, item)

            retrieved = storage.get_item(item.id)
            assert retrieved is not None
            assert retrieved.complete is True
            assert retrieved.completed_at is None
            storage.close()

    def test_default_item_has_null_completed_at(self):
        """A freshly saved incomplete item has completed_at = None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            item = TodoItem(reminder="Not done")
            storage.save_item(lst.id, item)

            retrieved = storage.get_item(item.id)
            assert retrieved is not None
            assert retrieved.complete is False
            assert retrieved.completed_at is None
            storage.close()


class TestActiveList:
    """Tests for active list management."""

    def test_initial_active_list_is_none(self):
        """Test that new database has no active list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            active_id = storage.get_active_list_id()

            assert active_id is None
            storage.close()

    def test_set_and_get_active_list(self):
        """Test setting and getting active list ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            list_id = uuid4()
            storage.set_active_list_id(list_id)

            assert storage.get_active_list_id() == list_id
            storage.close()

    def test_clear_active_list(self):
        """Test clearing active list ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            list_id = uuid4()
            storage.set_active_list_id(list_id)
            storage.set_active_list_id(None)

            assert storage.get_active_list_id() is None
            storage.close()


class TestListOperations:
    """Tests for list CRUD operations."""

    def test_save_and_get_list(self):
        """Test saving and retrieving a list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            retrieved = storage.get_list(lst.id)

            assert retrieved is not None
            assert retrieved.id == lst.id
            assert retrieved.name == "Test List"
            assert retrieved.deleted is False
            storage.close()

    def test_get_nonexistent_list(self):
        """Test getting a list that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            result = storage.get_list(uuid4())

            assert result is None
            storage.close()

    def test_update_list(self):
        """Test updating an existing list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Original")
            storage.save_list(lst)

            lst.name = "Updated"
            lst.mark_updated()
            storage.save_list(lst)

            retrieved = storage.get_list(lst.id)

            assert retrieved is not None
            assert retrieved.name == "Updated"
            storage.close()

    def test_delete_list_tombstone(self):
        """Test that delete_list sets tombstone."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="To Delete")
            storage.save_list(lst)

            result = storage.delete_list(lst.id)

            assert result is True
            retrieved = storage.get_list(lst.id)
            assert retrieved is not None
            assert retrieved.deleted is True
            storage.close()

    def test_get_all_lists_excludes_deleted(self):
        """Test that get_all_lists excludes deleted by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst1 = TodoList(name="Active")
            lst2 = TodoList(name="Deleted")
            lst2.deleted = True

            storage.save_list(lst1)
            storage.save_list(lst2)

            lists = storage.get_all_lists()

            assert len(lists) == 1
            assert lists[0].name == "Active"
            storage.close()

    def test_get_all_lists_includes_deleted(self):
        """Test that get_all_lists can include deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst1 = TodoList(name="Active")
            lst2 = TodoList(name="Deleted")
            lst2.deleted = True

            storage.save_list(lst1)
            storage.save_list(lst2)

            lists = storage.get_all_lists(include_deleted=True)

            assert len(lists) == 2
            storage.close()


class TestItemOperations:
    """Tests for item CRUD operations."""

    def test_save_and_get_item(self):
        """Test saving and retrieving an item."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            item = TodoItem(reminder="Test task", priority=1)
            storage.save_item(lst.id, item)

            retrieved = storage.get_item(item.id)

            assert retrieved is not None
            assert retrieved.id == item.id
            assert retrieved.reminder == "Test task"
            assert retrieved.priority == 1
            assert retrieved.complete is False
            storage.close()

    def test_get_nonexistent_item(self):
        """Test getting an item that doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            result = storage.get_item(uuid4())

            assert result is None
            storage.close()

    def test_update_item(self):
        """Test updating an existing item."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            item = TodoItem(reminder="Original")
            storage.save_item(lst.id, item)

            item.reminder = "Updated"
            item.complete = True
            item.mark_updated()
            storage.save_item(lst.id, item)

            retrieved = storage.get_item(item.id)

            assert retrieved is not None
            assert retrieved.reminder == "Updated"
            assert retrieved.complete is True
            storage.close()

    def test_delete_item_tombstone(self):
        """Test that delete_item sets tombstone."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            item = TodoItem(reminder="To Delete")
            storage.save_item(lst.id, item)

            result = storage.delete_item(item.id)

            assert result is True
            retrieved = storage.get_item(item.id)
            assert retrieved is not None
            assert retrieved.deleted is True
            storage.close()

    def test_get_items_for_list(self):
        """Test getting all items for a list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            item1 = TodoItem(reminder="Task 1")
            item2 = TodoItem(reminder="Task 2")
            storage.save_item(lst.id, item1)
            storage.save_item(lst.id, item2)

            items = storage.get_items_for_list(lst.id)

            assert len(items) == 2
            reminders = {i.reminder for i in items}
            assert reminders == {"Task 1", "Task 2"}
            storage.close()

    def test_get_items_excludes_deleted(self):
        """Test that get_items_for_list excludes deleted by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            item1 = TodoItem(reminder="Active")
            item2 = TodoItem(reminder="Deleted", deleted=True)
            storage.save_item(lst.id, item1)
            storage.save_item(lst.id, item2)

            items = storage.get_items_for_list(lst.id)

            assert len(items) == 1
            assert items[0].reminder == "Active"
            storage.close()


class TestTransactions:
    """Tests for transaction handling."""

    def test_transaction_commits_on_success(self):
        """Test that transaction commits when no exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            with storage.transaction():
                lst = TodoList(name="In Transaction")
                storage.save_list(lst)

            # Data should be persisted
            retrieved = storage.get_list(lst.id)
            assert retrieved is not None
            storage.close()

    def test_transaction_rollback_on_exception(self):
        """Test that transaction rolls back on exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Before Transaction")
            storage.save_list(lst)

            with pytest.raises(ValueError), storage.transaction():
                lst2 = TodoList(name="In Transaction")
                storage.save_list(lst2)
                raise ValueError("Test error")

            # lst2 should not be persisted
            lists = storage.get_all_lists()
            assert len(lists) == 1
            assert lists[0].name == "Before Transaction"
            storage.close()


class TestBulkOperations:
    """Tests for bulk load/save operations."""

    def test_load_empty_database(self):
        """Test loading an empty database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            db = storage.load_database()

            assert len(db.lists) == 0
            assert db.active_list_id is None
            assert db.schema_version == SCHEMA_VERSION
            storage.close()

    def test_save_and_load_database(self):
        """Test saving and loading a complete database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            # Create database with data
            db = Database()
            lst = TodoList(name="My List")
            lst.add_item(TodoItem(reminder="Task 1", priority=1))
            lst.add_item(TodoItem(reminder="Task 2", priority=2))
            db.add_list(lst)
            db.active_list_id = lst.id

            storage.save_database(db)

            # Reload and verify
            loaded = storage.load_database()

            assert len(loaded.lists) == 1
            assert loaded.active_list_id == lst.id
            loaded_list = loaded.get_list(lst.id)
            assert loaded_list is not None
            assert loaded_list.name == "My List"
            assert len(loaded_list.items) == 2
            storage.close()

    def test_load_preserves_tombstones(self):
        """Test that load_database includes tombstoned items."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            db = Database()
            lst = TodoList(name="My List")
            item = TodoItem(reminder="Deleted", deleted=True)
            lst.items[item.id] = item
            db.add_list(lst)

            storage.save_database(db)
            loaded = storage.load_database()

            loaded_list = loaded.get_list(lst.id)
            assert loaded_list is not None
            assert len(loaded_list.items) == 1
            assert list(loaded_list.items.values())[0].deleted is True
            storage.close()

    def test_clear_database(self):
        """Test clearing all data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            # Add some data
            db = Database()
            lst = TodoList(name="My List")
            lst.add_item(TodoItem(reminder="Task"))
            db.add_list(lst)
            db.active_list_id = lst.id
            storage.save_database(db)

            # Clear
            storage.clear()

            # Verify
            loaded = storage.load_database()
            assert len(loaded.lists) == 0
            assert loaded.active_list_id is None
            storage.close()


class TestPersistence:
    """Tests for data persistence across sessions."""

    def test_data_persists_after_close(self):
        """Test that data survives close and reopen."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # First session: create data
            storage1 = DatabaseStorage(db_path)
            storage1.open()

            db = Database()
            lst = TodoList(name="Persistent List")
            lst.add_item(TodoItem(reminder="Persistent Task"))
            db.add_list(lst)
            db.active_list_id = lst.id
            storage1.save_database(db)
            storage1.close()

            # Second session: verify data
            storage2 = DatabaseStorage(db_path)
            storage2.open()

            loaded = storage2.load_database()

            assert len(loaded.lists) == 1
            assert loaded.active_list_id == lst.id
            loaded_list = list(loaded.lists.values())[0]
            assert loaded_list.name == "Persistent List"
            assert len(loaded_list.items) == 1
            storage2.close()


class TestListWithItems:
    """Tests for lists loaded with their items."""

    def test_get_list_includes_items(self):
        """Test that get_list returns list with items populated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            item1 = TodoItem(reminder="Task 1")
            item2 = TodoItem(reminder="Task 2")
            storage.save_item(lst.id, item1)
            storage.save_item(lst.id, item2)

            retrieved = storage.get_list(lst.id)

            assert retrieved is not None
            assert len(retrieved.items) == 2
            storage.close()

    def test_get_all_lists_includes_items(self):
        """Test that get_all_lists returns lists with items populated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Test List")
            storage.save_list(lst)

            item = TodoItem(reminder="Task")
            storage.save_item(lst.id, item)

            lists = storage.get_all_lists()

            assert len(lists) == 1
            assert len(lists[0].items) == 1
            storage.close()
