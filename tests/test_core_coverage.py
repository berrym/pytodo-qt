"""Tests targeting specific uncovered lines in core modules.

Covers gaps in models.py, database.py, migration.py, config.py, paths.py,
logger.py, and offline_queue.py identified by coverage analysis.
"""

import json
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from pytodo_qt.core.database import DatabaseStorage
from pytodo_qt.core.models import (
    Database,
    TodoItem,
    TodoList,
    compute_next_due_date,
    create_todo_list,
    format_due_date,
    is_recurrence_ended,
)

# ── models.py gaps ──────────────────────────────────────────────────────


class TestTodoListRemoveItemNotFound:
    """Cover line 165: TodoList.remove_item returns False for missing ID."""

    def test_remove_nonexistent_item(self):
        lst = create_todo_list("Test")
        assert lst.remove_item(uuid4()) is False

    def test_remove_item_from_empty_list(self):
        lst = create_todo_list("Empty")
        assert lst.remove_item(uuid4()) is False


class TestDatabaseSetActiveListFail:
    """Cover lines 254, 262: set_active_list / set_active_list_by_name return False."""

    def test_set_active_list_nonexistent(self):
        db = Database()
        assert db.set_active_list(uuid4()) is False

    def test_set_active_list_by_name_no_match(self):
        db = Database()
        lst = create_todo_list("Foo")
        db.add_list(lst)
        assert db.set_active_list_by_name("Bar") is False

    def test_set_active_list_by_name_deleted(self):
        """Deleted lists are not found by name."""
        db = Database()
        lst = create_todo_list("Hidden")
        lst.mark_deleted()
        db.add_list(lst)
        assert db.set_active_list_by_name("Hidden") is False


class TestDatabaseGetListByName:
    """Cover lines 274-277: get_list_by_name with deleted and missing."""

    def test_get_list_by_name_exists(self):
        db = Database()
        lst = create_todo_list("Work")
        db.add_list(lst)
        assert db.get_list_by_name("Work") is lst

    def test_get_list_by_name_not_found(self):
        db = Database()
        assert db.get_list_by_name("Nope") is None

    def test_get_list_by_name_skips_deleted(self):
        db = Database()
        lst = create_todo_list("Deleted")
        lst.mark_deleted()
        db.add_list(lst)
        assert db.get_list_by_name("Deleted") is None


class TestDatabaseTotalCompleted:
    """Cover line 313: Database.total_completed."""

    def test_total_completed_empty(self):
        db = Database()
        assert db.total_completed() == 0

    def test_total_completed_multiple_lists(self):
        db = Database()
        lst1 = create_todo_list("A")
        item1 = TodoItem(reminder="done")
        item1.complete = True
        lst1.add_item(item1)
        lst1.add_item(TodoItem(reminder="not done"))
        db.add_list(lst1)

        lst2 = create_todo_list("B")
        item2 = TodoItem(reminder="also done")
        item2.complete = True
        lst2.add_item(item2)
        db.add_list(lst2)

        assert db.total_completed() == 2
        assert db.total_items() == 3


class TestFormatDueDateCompletedOverdueWithYear:
    """Cover line 616: completed overdue item from different year shows year."""

    def test_completed_overdue_different_year(self):
        past = date(2020, 6, 15)
        result = format_due_date(past, complete=True)
        assert "2020" in result
        assert "Jun" in result

    def test_completed_overdue_same_year(self):
        yesterday = date.today() - timedelta(days=2)
        result = format_due_date(yesterday, complete=True)
        # Same year: no year shown
        assert str(yesterday.year) not in result


class TestComputeNextDueDateWeeklyMultiInterval:
    """Cover lines 666-667: weekly with interval > 1 and days_ahead > 0."""

    def test_weekly_interval_2_future_weekday(self):
        """If original weekday is ahead of today, interval > 1 adds extra weeks."""
        today = date.today()
        # Pick a weekday that's 2 days ahead of today
        target_weekday = (today.weekday() + 2) % 7
        future_date = today + timedelta(days=2)
        # Adjust if weekday math doesn't land right
        while future_date.weekday() != target_weekday:
            future_date += timedelta(days=1)

        result = compute_next_due_date(future_date, "weekly", interval=2)
        # Should be at least 8 days from today (2 weeks minus a few days)
        assert (result - today).days >= 7
        assert result.weekday() == target_weekday

    def test_weekly_interval_3(self):
        today = date.today()
        # Use a date with same weekday as today (days_ahead <= 0 branch)
        same_weekday = today
        result = compute_next_due_date(same_weekday, "weekly", interval=3)
        assert result.weekday() == today.weekday()
        assert (result - today).days == 21  # 3 * 7


class TestComputeNextDueDateUnknownType:
    """Cover the ValueError branch for unknown recurrence type."""

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown recurrence type"):
            compute_next_due_date(date.today(), "biweekly")


class TestIsRecurrenceEndedNonRecurring:
    """Cover the not is_recurring early return."""

    def test_non_recurring_item(self):
        item = TodoItem(reminder="No recurrence")
        assert is_recurrence_ended(item) is True


# ── database.py gaps ────────────────────────────────────────────────────


class TestDatabaseStorageOpenAlreadyOpen:
    """Cover line 172: open() early return when already connected."""

    def test_double_open_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            conn1 = storage.connection
            storage.open()  # Should be no-op
            assert storage.connection is conn1
            storage.close()


class TestMigrateSchema4To5:
    """Cover lines 292-312: _migrate_schema_4_to_5 creating tables from scratch."""

    def test_v4_to_v5_creates_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create a v4 database without devices/sync_groups tables
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                """CREATE TABLE lists (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0, private INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.execute(
                """CREATE TABLE items (
                    id TEXT PRIMARY KEY, list_id TEXT NOT NULL,
                    reminder TEXT NOT NULL DEFAULT '', priority INTEGER NOT NULL DEFAULT 2,
                    complete INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '4')")
            conn.commit()
            conn.close()

            storage = DatabaseStorage(db_path)
            storage.open()

            # Verify new tables were created
            cursor = storage.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            assert "devices" in tables
            assert "sync_groups" in tables
            assert "device_groups" in tables
            assert "list_sync_rules" in tables
            assert "pending_syncs" in tables

            # Verify indexes were created
            cursor = storage.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )
            indexes = [row[0] for row in cursor.fetchall()]
            assert "idx_devices_fingerprint" in indexes
            assert "idx_devices_trust_level" in indexes

            assert storage.get_schema_version() == 13
            storage.close()


class TestRemoveListSyncRule:
    """Cover lines 848-852: remove_list_sync_rule."""

    def test_remove_existing_rule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            list_id = uuid4()
            group_id = uuid4()

            # Create a sync group first
            from pytodo_qt.core.models import SyncGroup

            group = SyncGroup(id=group_id, name="Test Group")
            storage.save_sync_group(group)

            # Temporarily disable FK constraints to insert a rule
            storage.connection.execute("PRAGMA foreign_keys = OFF")
            storage.add_list_sync_rule(list_id, group_id)
            storage.connection.execute("PRAGMA foreign_keys = ON")

            # Remove it
            result = storage.remove_list_sync_rule(list_id, group_id)
            assert result is True

            storage.close()

    def test_remove_nonexistent_rule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            result = storage.remove_list_sync_rule(uuid4(), uuid4())
            assert result is False

            storage.close()


class TestDatabaseStorageDeleteList:
    """Cover line 473-474: _row_to_list fallback for private column."""

    def test_delete_list_returns_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Deletable")
            storage.save_list(lst)

            result = storage.delete_list(lst.id)
            assert result is True
            storage.close()

    def test_delete_nonexistent_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            result = storage.delete_list(uuid4())
            assert result is False
            storage.close()


# ── migration.py gaps ───────────────────────────────────────────────────


class TestMigrationErrorPaths:
    """Cover error paths in migration.py."""

    def test_backup_os_error(self):
        """Cover lines 48-49: OSError during backup."""
        from pytodo_qt.core.migration import MigrationError, backup_json_file

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            json_path.write_text("{}")

            with (
                patch("shutil.copy2", side_effect=OSError("Permission denied")),
                pytest.raises(MigrationError, match="Failed to create backup"),
            ):
                backup_json_file(json_path)

    def test_load_json_os_error(self):
        """Cover lines 74-75: OSError reading file."""
        from pytodo_qt.core.migration import MigrationError, load_json_database

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            json_path.write_text("{}")

            with (
                patch("builtins.open", side_effect=OSError("Read error")),
                pytest.raises(MigrationError, match="Failed to read file"),
            ):
                load_json_database(json_path)

    def test_load_json_parse_error(self):
        """Cover lines 88-89: Exception during Database parsing."""
        from pytodo_qt.core.migration import MigrationError, load_json_database

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            # Valid JSON but invalid database structure
            json_path.write_text('{"schema_version": 999, "lists": "not_a_dict"}')

            with pytest.raises(MigrationError, match="Failed to parse database"):
                load_json_database(json_path)

    def test_migrate_sqlite_write_failure(self):
        """Cover lines 139-144: cleanup on SQLite write failure."""
        from pytodo_qt.core.migration import MigrationError, migrate_json_to_sqlite

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            sqlite_path = Path(tmpdir) / "test.db"

            db = Database()
            json_path.write_text(json.dumps(db.to_dict()))

            with (
                patch.object(
                    DatabaseStorage, "save_database", side_effect=Exception("Write failed")
                ),
                pytest.raises(MigrationError, match="Failed to write SQLite"),
            ):
                migrate_json_to_sqlite(json_path, sqlite_path, backup=False)

            # SQLite should be cleaned up
            assert not sqlite_path.exists()

    def test_migrate_verification_failure_cleanup(self):
        """Cover lines 150-155: cleanup on verification failure."""
        from pytodo_qt.core.migration import MigrationError, migrate_json_to_sqlite

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            sqlite_path = Path(tmpdir) / "test.db"

            db = Database()
            lst = create_todo_list("Test")
            db.add_list(lst)
            json_path.write_text(json.dumps(db.to_dict()))

            with (
                patch("pytodo_qt.core.migration.verify_migration", return_value=False),
                pytest.raises(MigrationError, match="verification failed"),
            ):
                migrate_json_to_sqlite(json_path, sqlite_path, backup=False)

            # SQLite should be cleaned up
            assert not sqlite_path.exists()

    def test_verify_active_list_mismatch(self):
        """Cover lines 206-211: active list ID mismatch."""
        from pytodo_qt.core.migration import verify_migration

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            sqlite_path = Path(tmpdir) / "test.db"

            # JSON with active_list_id
            db1 = Database()
            lst = create_todo_list("Test")
            db1.add_list(lst)
            db1.active_list_id = lst.id
            json_path.write_text(json.dumps(db1.to_dict()))

            # SQLite with different active_list_id
            db2 = Database()
            lst2 = TodoList(id=lst.id, name="Test")
            db2.add_list(lst2)
            db2.active_list_id = None  # Different from JSON
            storage = DatabaseStorage(sqlite_path)
            storage.open()
            storage.save_database(db2)
            storage.close()

            result = verify_migration(json_path, sqlite_path)
            assert result is False

    def test_migrate_general_load_exception(self):
        """Cover lines 128-131: general exception during load."""
        from pytodo_qt.core.migration import MigrationError, migrate_json_to_sqlite

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            sqlite_path = Path(tmpdir) / "test.db"
            json_path.write_text("{}")

            with (
                patch(
                    "pytodo_qt.core.migration.load_json_database",
                    side_effect=RuntimeError("unexpected"),
                ),
                pytest.raises(MigrationError, match="Failed to load JSON"),
            ):
                migrate_json_to_sqlite(json_path, sqlite_path, backup=False)


# ── config.py gaps ──────────────────────────────────────────────────────


class TestConfigErrorPaths:
    """Cover error paths in config.py."""

    def test_ensure_directories_os_error(self):
        """Cover lines 200-202: OSError creating directories."""
        from pytodo_qt.core.config import ConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = ConfigManager(
                config_dir=Path(tmpdir) / "config",
                data_dir=Path(tmpdir) / "data",
            )
            # Force state_dir to a non-existent path that will fail
            mgr.state_dir = Path("/nonexistent/deep/path/state")

            with (
                patch.object(Path, "exists", return_value=False),
                patch.object(Path, "mkdir", side_effect=OSError("Permission denied")),
                pytest.raises(OSError),
            ):
                mgr.ensure_directories()

    def test_load_corrupt_toml(self):
        """Cover lines 226-227: error loading TOML config."""
        from pytodo_qt.core.config import ConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            # Write invalid TOML
            config_file = config_dir / "config.toml"
            config_file.write_text("invalid = [toml syntax {{{")

            mgr = ConfigManager(
                config_dir=config_dir,
                data_dir=data_dir,
            )

            # Should fall through to default config
            config = mgr.load()
            assert config is not None

    def test_save_write_error(self):
        """Cover lines 292-294: error saving config."""
        from pytodo_qt.core.config import AppConfig, ConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            mgr = ConfigManager(
                config_dir=config_dir,
                data_dir=data_dir,
            )
            mgr._config = AppConfig()

            with patch("builtins.open", side_effect=OSError("Disk full")):
                result = mgr.save()
                assert result is False

    def test_migrate_from_ini_error(self):
        """Cover lines 276-277: error during INI migration."""
        from pytodo_qt.core.config import ConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            # Create a legacy INI file that will cause an error
            legacy_ini = config_dir / "pytodo-qt.ini"
            legacy_ini.write_text("[database]\nactive_list = Test\n")

            mgr = ConfigManager(
                config_dir=config_dir,
                data_dir=data_dir,
            )

            # Patch copy2 to fail during INI migration
            with patch("shutil.copy2", side_effect=OSError("backup failed")):
                # Should handle error gracefully, returning config with what it could read
                config = mgr._migrate_from_ini()
                assert config is not None
                assert config.database.active_list == "Test"


# ── paths.py gaps ───────────────────────────────────────────────────────


class TestPathsErrorPaths:
    """Cover error paths in paths.py."""

    def test_ensure_directories_os_error(self):
        """Cover lines 100-102: OSError in ensure_directories."""
        from pytodo_qt.core import paths

        with (
            patch.object(Path, "exists", return_value=False),
            patch.object(Path, "mkdir", side_effect=OSError("Permission denied")),
            pytest.raises(OSError),
        ):
            paths.ensure_directories()

    def test_migrate_from_legacy_config_copy_error(self):
        """Cover lines 128-129: OSError copying config."""
        from pytodo_qt.core import paths

        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = Path(tmpdir) / "legacy"
            legacy_dir.mkdir()
            config_file = legacy_dir / "config.toml"
            config_file.write_text("[database]\n")

            with (
                patch.object(paths, "get_legacy_dir", return_value=legacy_dir),
                patch.object(
                    paths,
                    "get_config_file",
                    return_value=Path(tmpdir) / "new" / "config.toml",
                ),
                patch.object(
                    paths,
                    "get_config_dir",
                    return_value=Path(tmpdir) / "new",
                ),
                patch.object(
                    paths,
                    "get_data_dir",
                    return_value=Path(tmpdir) / "data",
                ),
                patch.object(
                    paths,
                    "get_state_dir",
                    return_value=Path(tmpdir) / "state",
                ),
                patch("shutil.copy2", side_effect=OSError("copy failed")),
            ):
                # Should not raise, just log a warning
                result = paths.migrate_from_legacy()
                assert result is False

    def test_migrate_from_legacy_success(self):
        """Cover the full migration path including marker file."""
        from pytodo_qt.core import paths

        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = Path(tmpdir) / "legacy"
            legacy_dir.mkdir()

            new_config_dir = Path(tmpdir) / "config"
            new_config_dir.mkdir()
            new_data_dir = Path(tmpdir) / "data"
            new_data_dir.mkdir()
            new_state_dir = Path(tmpdir) / "state"
            new_state_dir.mkdir()

            # Create a legacy config file
            config_file = legacy_dir / "config.toml"
            config_file.write_text("[database]\n")
            new_config_file = new_config_dir / "config.toml"

            with (
                patch.object(paths, "get_legacy_dir", return_value=legacy_dir),
                patch.object(paths, "get_config_file", return_value=new_config_file),
                patch.object(paths, "get_config_dir", return_value=new_config_dir),
                patch.object(paths, "get_data_dir", return_value=new_data_dir),
                patch.object(paths, "get_state_dir", return_value=new_state_dir),
                patch.object(
                    paths,
                    "get_legacy_json_database",
                    return_value=new_data_dir / "db.json",
                ),
            ):
                result = paths.migrate_from_legacy()
                assert result is True
                # Check marker file was created
                marker = legacy_dir / ".migrated-to-xdg"
                assert marker.exists()


# ── logger.py gaps ──────────────────────────────────────────────────────


class TestLoggerConvenienceFunctions:
    """Cover lines 118, 123, 128, 133, 138, 143: convenience functions."""

    def test_info(self):
        from pytodo_qt.core import logger as log_module

        log_module.info("test info %s", "arg")

    def test_warning(self):
        from pytodo_qt.core import logger as log_module

        log_module.warning("test warning")

    def test_error(self):
        from pytodo_qt.core import logger as log_module

        log_module.error("test error %d", 42)

    def test_critical(self):
        from pytodo_qt.core import logger as log_module

        log_module.critical("test critical")

    def test_exception(self):
        from pytodo_qt.core import logger as log_module

        try:
            raise ValueError("test")
        except ValueError:
            log_module.exception("caught exception")

    def test_debug(self):
        from pytodo_qt.core import logger as log_module

        log_module.debug("test debug")


# ── offline_queue.py gaps ───────────────────────────────────────────────


class TestOfflineQueueCleanup:
    """Cover line 86: cleanup_expired."""

    def test_cleanup_expired(self):
        from pytodo_qt.core.offline_queue import OfflineQueue

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            queue = OfflineQueue(storage)
            # Should return 0 when nothing to clean
            count = queue.cleanup_expired()
            assert count == 0

            storage.close()


# ── Additional database.py edge cases ──────────────────────────────────


class TestDatabaseStorageSaveAndReloadRecurrence:
    """Ensure recurrence fields round-trip through SQLite."""

    def test_recurrence_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            lst = TodoList(name="Recurring")
            item = TodoItem(
                reminder="Daily standup",
                recurrence_type="daily",
                recurrence_interval=1,
                recurrence_end_count=30,
                recurrence_count=5,
                due_date=date.today(),
            )
            lst.add_item(item)
            storage.save_list(lst)
            storage.save_item(lst.id, item)

            # Reload
            loaded_lst = storage.get_list(lst.id)
            assert loaded_lst is not None
            loaded_item = loaded_lst.items[item.id]
            assert loaded_item.recurrence_type == "daily"
            assert loaded_item.recurrence_interval == 1
            assert loaded_item.recurrence_end_count == 30
            assert loaded_item.recurrence_count == 5
            assert loaded_item.due_date == date.today()

            storage.close()

    def test_recurrence_end_date_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            end = date(2026, 12, 31)
            lst = TodoList(name="Yearly")
            item = TodoItem(
                reminder="Annual review",
                recurrence_type="yearly",
                recurrence_interval=1,
                recurrence_end_date=end,
                due_date=date(2026, 6, 1),
            )
            lst.add_item(item)
            storage.save_list(lst)
            storage.save_item(lst.id, item)

            loaded_lst = storage.get_list(lst.id)
            assert loaded_lst is not None
            loaded_item = loaded_lst.items[item.id]
            assert loaded_item.recurrence_end_date == end

            storage.close()
