"""Integration tests for SQLite storage."""

import json
import tempfile
from pathlib import Path

from pytodo_qt.core.database import DatabaseStorage
from pytodo_qt.core.migration import migrate_json_to_sqlite, needs_migration
from pytodo_qt.core.models import Database, TodoItem, TodoList
from pytodo_qt.core.sync_engine import merge_databases


class TestFullWorkflow:
    """Test complete database workflow."""

    def test_create_save_reload_verify(self):
        """Test creating data, saving, reloading, and verifying."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create and populate database
            storage = DatabaseStorage(db_path)
            storage.open()

            db = Database()

            # Add multiple lists with items
            work_list = TodoList(name="Work")
            work_list.add_item(TodoItem(reminder="Review PRs", priority=1))
            work_list.add_item(TodoItem(reminder="Update docs", priority=2))
            work_list.add_item(TodoItem(reminder="Team meeting", priority=2, complete=True))
            db.add_list(work_list)

            personal_list = TodoList(name="Personal")
            personal_list.add_item(TodoItem(reminder="Buy groceries", priority=2))
            personal_list.add_item(TodoItem(reminder="Call mom", priority=1))
            db.add_list(personal_list)

            db.active_list_id = work_list.id

            # Save
            storage.save_database(db)
            storage.close()

            # Reload in new session
            storage2 = DatabaseStorage(db_path)
            storage2.open()
            loaded = storage2.load_database()
            storage2.close()

            # Verify structure
            assert len(loaded.lists) == 2
            assert loaded.active_list_id == work_list.id

            # Verify Work list
            loaded_work = loaded.get_list(work_list.id)
            assert loaded_work is not None
            assert loaded_work.name == "Work"
            assert len(loaded_work.items) == 3

            # Verify items
            work_items = list(loaded_work.items.values())
            reminders = {item.reminder for item in work_items}
            assert reminders == {"Review PRs", "Update docs", "Team meeting"}

            # Verify completed status preserved
            completed_items = [item for item in work_items if item.complete]
            assert len(completed_items) == 1
            assert completed_items[0].reminder == "Team meeting"

            # Verify Personal list
            loaded_personal = loaded.get_list(personal_list.id)
            assert loaded_personal is not None
            assert loaded_personal.name == "Personal"
            assert len(loaded_personal.items) == 2

    def test_incremental_saves(self):
        """Test multiple save/load cycles with modifications."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            # Initial save
            db = Database()
            lst = TodoList(name="Tasks")
            lst.add_item(TodoItem(reminder="Task 1"))
            db.add_list(lst)
            storage.save_database(db)

            # Modify and save again
            loaded = storage.load_database()
            loaded_list = list(loaded.lists.values())[0]
            loaded_list.add_item(TodoItem(reminder="Task 2"))
            storage.save_database(loaded)

            # Modify and save again
            loaded2 = storage.load_database()
            loaded_list2 = list(loaded2.lists.values())[0]
            loaded_list2.add_item(TodoItem(reminder="Task 3"))
            storage.save_database(loaded2)

            # Final verification
            final = storage.load_database()
            final_list = list(final.lists.values())[0]
            assert len(final_list.items) == 3

            storage.close()

    def test_delete_operations(self):
        """Test soft delete (tombstone) workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            # Create with items
            db = Database()
            lst = TodoList(name="Tasks")
            item1 = TodoItem(reminder="Keep this")
            item2 = TodoItem(reminder="Delete this")
            lst.add_item(item1)
            lst.add_item(item2)
            db.add_list(lst)
            storage.save_database(db)

            # Soft delete an item
            loaded = storage.load_database()
            loaded_list = list(loaded.lists.values())[0]
            loaded_list.remove_item(item2.id)
            storage.save_database(loaded)

            # Reload and verify
            final = storage.load_database()
            final_list = list(final.lists.values())[0]

            # Both items exist in storage (tombstone preserved)
            assert len(final_list.items) == 2

            # But only one is active
            active_items = list(final_list.active_items())
            assert len(active_items) == 1
            assert active_items[0].reminder == "Keep this"

            storage.close()


class TestMigrationIntegration:
    """Integration tests for JSON to SQLite migration."""

    def test_full_migration_workflow(self):
        """Test complete migration from JSON to SQLite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "pytodo-qt-db.json"
            sqlite_path = Path(tmpdir) / "pytodo-qt.db"

            # Create JSON database
            db = Database()
            lst = TodoList(name="Migrated List")
            lst.add_item(TodoItem(reminder="Migrated Task 1", priority=1))
            lst.add_item(TodoItem(reminder="Migrated Task 2", priority=3))
            db.add_list(lst)
            db.active_list_id = lst.id

            json_path.write_text(json.dumps(db.to_dict()))

            # Verify migration is needed
            assert needs_migration(json_path, sqlite_path) is True

            # Perform migration
            migrate_json_to_sqlite(json_path, sqlite_path, backup=True)

            # Verify migration no longer needed
            assert needs_migration(json_path, sqlite_path) is False

            # Verify backup was created
            backups = list(Path(tmpdir).glob("*.backup_*"))
            assert len(backups) == 1

            # Load from SQLite and verify
            storage = DatabaseStorage(sqlite_path)
            storage.open()
            loaded = storage.load_database()
            storage.close()

            assert len(loaded.lists) == 1
            assert loaded.active_list_id == lst.id

            loaded_list = list(loaded.lists.values())[0]
            assert loaded_list.name == "Migrated List"
            assert len(loaded_list.items) == 2

    def test_migration_preserves_all_data(self):
        """Test that migration preserves all data exactly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "test.json"
            sqlite_path = Path(tmpdir) / "test.db"

            # Create complex database
            db = Database()

            for i in range(5):
                lst = TodoList(name=f"List {i}")
                for j in range(10):
                    item = TodoItem(
                        reminder=f"Task {i}-{j}",
                        priority=(j % 3) + 1,
                        complete=j % 2 == 0,
                    )
                    if j % 4 == 0:  # Some deleted items
                        item.mark_deleted()
                    lst.items[item.id] = item
                db.add_list(lst)

            db.active_list_id = list(db.lists.keys())[2]  # Third list active

            json_path.write_text(json.dumps(db.to_dict()))

            # Migrate
            migrate_json_to_sqlite(json_path, sqlite_path, backup=False)

            # Load and compare
            storage = DatabaseStorage(sqlite_path)
            storage.open()
            loaded = storage.load_database()
            storage.close()

            # Compare counts
            assert len(loaded.lists) == len(db.lists)
            assert loaded.active_list_id == db.active_list_id

            for list_id, original_list in db.lists.items():
                loaded_list = loaded.get_list(list_id)
                assert loaded_list is not None
                assert loaded_list.name == original_list.name
                assert len(loaded_list.items) == len(original_list.items)

                for item_id, original_item in original_list.items.items():
                    loaded_item = loaded_list.items.get(item_id)
                    assert loaded_item is not None
                    assert loaded_item.reminder == original_item.reminder
                    assert loaded_item.priority == original_item.priority
                    assert loaded_item.complete == original_item.complete
                    assert loaded_item.deleted == original_item.deleted


class TestSyncWithSQLite:
    """Test sync operations work with SQLite storage."""

    def test_sync_merge_with_sqlite(self):
        """Test that sync merge works correctly with SQLite-backed databases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two separate SQLite databases (simulating two devices)
            db1_path = Path(tmpdir) / "device1.db"
            db2_path = Path(tmpdir) / "device2.db"

            # Device 1: Create initial data
            storage1 = DatabaseStorage(db1_path)
            storage1.open()

            db1 = Database()
            shared_list = TodoList(name="Shared")
            shared_list.add_item(TodoItem(reminder="From Device 1"))
            db1.add_list(shared_list)
            db1.active_list_id = shared_list.id
            storage1.save_database(db1)

            # Device 2: Start with same data, then add more
            storage2 = DatabaseStorage(db2_path)
            storage2.open()

            db2 = Database()
            # Simulate having synced the shared list
            shared_list_copy = TodoList(
                id=shared_list.id,
                name="Shared",
                created_at=shared_list.created_at,
                updated_at=shared_list.updated_at,
            )
            for item in shared_list.items.values():
                shared_list_copy.items[item.id] = TodoItem(
                    id=item.id,
                    reminder=item.reminder,
                    priority=item.priority,
                    complete=item.complete,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
            # Add new item on device 2
            shared_list_copy.add_item(TodoItem(reminder="From Device 2"))
            db2.add_list(shared_list_copy)
            db2.active_list_id = shared_list_copy.id
            storage2.save_database(db2)

            # Reload both
            local_db = storage1.load_database()
            remote_db = storage2.load_database()

            # Merge (remote into local)
            result = merge_databases(local_db, remote_db)

            # Save merged result
            storage1.save_database(result.merged_db)
            storage1.close()
            storage2.close()

            # Reload and verify
            storage_verify = DatabaseStorage(db1_path)
            storage_verify.open()
            merged = storage_verify.load_database()
            storage_verify.close()

            merged_list = merged.get_list(shared_list.id)
            assert merged_list is not None
            assert len(merged_list.items) == 2

            reminders = {item.reminder for item in merged_list.items.values()}
            assert reminders == {"From Device 1", "From Device 2"}

    def test_sync_serialization_compatibility(self):
        """Test that SQLite databases can serialize for sync protocol."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            # Create database
            db = Database()
            lst = TodoList(name="Sync Test")
            lst.add_item(TodoItem(reminder="Sync item"))
            db.add_list(lst)
            storage.save_database(db)

            # Load and serialize (as sync protocol does)
            loaded = storage.load_database()
            sync_bytes = loaded.to_bytes()

            # Deserialize (as receiving end does)
            received = Database.from_bytes(sync_bytes)

            # Verify round-trip
            assert len(received.lists) == 1
            received_list = list(received.lists.values())[0]
            assert received_list.name == "Sync Test"
            assert len(received_list.items) == 1

            storage.close()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_database(self):
        """Test handling of empty database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "empty.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            # Save empty database
            db = Database()
            storage.save_database(db)

            # Reload
            loaded = storage.load_database()
            assert len(loaded.lists) == 0
            assert loaded.active_list_id is None

            storage.close()

    def test_unicode_content(self):
        """Test handling of unicode in task content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "unicode.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            db = Database()
            lst = TodoList(name="日本語リスト")
            lst.add_item(TodoItem(reminder="买菜 🛒"))
            lst.add_item(TodoItem(reminder="Ümläuts and ñ"))
            lst.add_item(TodoItem(reminder="Emoji: 🎉🚀💻"))
            db.add_list(lst)
            storage.save_database(db)

            # Reload and verify
            loaded = storage.load_database()
            loaded_list = list(loaded.lists.values())[0]
            assert loaded_list.name == "日本語リスト"

            reminders = {item.reminder for item in loaded_list.items.values()}
            assert "买菜 🛒" in reminders
            assert "Ümläuts and ñ" in reminders
            assert "Emoji: 🎉🚀💻" in reminders

            storage.close()

    def test_large_database(self):
        """Test handling of larger database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "large.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            db = Database()

            # Create 100 lists with 100 items each
            for i in range(100):
                lst = TodoList(name=f"List {i}")
                for j in range(100):
                    lst.add_item(
                        TodoItem(
                            reminder=f"Task {i}-{j} with some longer text content",
                            priority=(j % 3) + 1,
                        )
                    )
                db.add_list(lst)

            storage.save_database(db)

            # Reload and verify
            loaded = storage.load_database()
            assert len(loaded.lists) == 100

            total_items = sum(len(lst.items) for lst in loaded.lists.values())
            assert total_items == 10000

            storage.close()

    def test_reopen_after_close(self):
        """Test reopening database after close."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "reopen.db"
            storage = DatabaseStorage(db_path)

            # First session
            storage.open()
            db = Database()
            lst = TodoList(name="Test")
            lst.add_item(TodoItem(reminder="Task"))
            db.add_list(lst)
            storage.save_database(db)
            storage.close()

            # Reopen same storage object
            storage.open()
            loaded = storage.load_database()
            assert len(loaded.lists) == 1
            storage.close()
