"""Tests for synchronization engine."""

import time

from pytodo_qt.core.models import Database, TodoList, create_todo_item, create_todo_list
from pytodo_qt.core.sync_engine import merge_databases


class TestSyncEngine:
    """Tests for sync engine."""

    def test_merge_empty_databases(self):
        """Test merging two empty databases."""
        local = Database()
        remote = Database()

        result = merge_databases(local, remote)

        assert not result.changes_made
        assert not result.has_conflicts

    def test_merge_add_new_list(self):
        """Test merging when remote has a new list."""
        local = Database()
        remote = Database()

        new_list = create_todo_list("New List")
        remote.add_list(new_list)

        result = merge_databases(local, remote)

        assert result.changes_made
        assert len(result.added_lists) == 1
        assert new_list.id in local.lists

    def test_merge_add_new_item(self):
        """Test merging when remote has a new item in existing list."""
        local = Database()
        remote = Database()

        # Same list in both
        local_list = create_todo_list("Shared")
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Add item only to remote
        new_item = create_todo_item("New Task")
        remote_list.add_item(new_item)

        result = merge_databases(local, remote)

        assert result.changes_made
        assert len(result.added_items) == 1
        assert new_item.id in local_list.items

    def test_merge_lww_update(self):
        """Test Last-Write-Wins for updated items."""
        local = Database()
        remote = Database()

        # Create same list and item in both
        local_list = create_todo_list("Shared")
        local_item = create_todo_item("Task")
        local_list.add_item(local_item)
        local.add_list(local_list)

        # Clone to remote
        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Wait a moment then update remote
        time.sleep(0.01)
        remote_item = remote_list.items[local_item.id]
        remote_item.reminder = "Updated Task"
        remote_item.mark_updated()

        result = merge_databases(local, remote)

        # Remote should win because it has later timestamp
        assert result.has_conflicts
        assert local_list.items[local_item.id].reminder == "Updated Task"

    def test_merge_local_newer_wins(self):
        """Test that local wins when it has later timestamp."""
        local = Database()
        remote = Database()

        # Create same list and item in both
        local_list = create_todo_list("Shared")
        local_item = create_todo_item("Original")
        local_list.add_item(local_item)
        local.add_list(local_list)

        # Clone to remote FIRST
        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Update remote
        remote_item = remote_list.items[local_item.id]
        remote_item.reminder = "Remote Update"
        remote_item.mark_updated()

        # Wait a moment then update local (should be newer)
        time.sleep(0.01)
        local_item.reminder = "Local Update"
        local_item.mark_updated()

        _result = merge_databases(local, remote)  # noqa: F841

        # Local should keep its value
        assert local_item.reminder == "Local Update"

    def test_merge_delete_tombstone(self):
        """Test that deletions sync correctly via tombstones."""
        local = Database()
        remote = Database()

        # Create same list and item in both
        local_list = create_todo_list("Shared")
        local_item = create_todo_item("To Delete")
        local_list.add_item(local_item)
        local.add_list(local_list)

        # Clone to remote
        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Delete on remote
        time.sleep(0.01)
        remote_list.remove_item(local_item.id)

        result = merge_databases(local, remote)

        # Item should be marked deleted in local
        assert local_list.items[local_item.id].deleted is True
        assert len(result.deleted_items) == 1

    def test_merge_concurrent_adds_no_conflict(self):
        """Test that concurrent adds don't conflict (UUID-based)."""
        local = Database()
        remote = Database()

        # Same list in both
        local_list = create_todo_list("Shared")
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Add different items to each
        local_item = create_todo_item("Local Task")
        local_list.add_item(local_item)

        remote_item = create_todo_item("Remote Task")
        remote_list.add_item(remote_item)

        _result = merge_databases(local, remote)  # noqa: F841

        # Both items should exist in local
        assert local_item.id in local_list.items
        assert remote_item.id in local_list.items
        assert local_list.active_item_count() == 2

    def test_conflict_tracking(self):
        """Test that conflicts are properly tracked."""
        local = Database()
        remote = Database()

        local_list = create_todo_list("List")
        local_item = create_todo_item("Task", priority=2)
        local_list.add_item(local_item)
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        time.sleep(0.01)
        remote_item = remote_list.items[local_item.id]
        remote_item.priority = 1  # Changed to High
        remote_item.complete = True  # Also completed
        remote_item.mark_updated()

        result = merge_databases(local, remote)

        # Should have conflicts for priority and complete
        assert len(result.conflicts) >= 2

        priority_conflict = next((c for c in result.conflicts if c.field == "priority"), None)
        assert priority_conflict is not None
        assert priority_conflict.local_value == 2
        assert priority_conflict.remote_value == 1
        assert priority_conflict.winner == "remote"

    def test_sync_copies_completed_at_from_remote(self):
        """When the remote wins on `complete`, completed_at must follow."""
        local = Database()
        remote = Database()

        local_list = create_todo_list("List")
        local_item = create_todo_item("Task")
        local_list.add_item(local_item)
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        time.sleep(0.01)
        remote_item = remote_list.items[local_item.id]
        remote_item.complete = True
        remote_item.completed_at = 1_700_000_000_000  # Remote's truth
        remote_item.mark_updated()

        merge_databases(local, remote)
        merged_local_item = local.lists[local_list.id].items[local_item.id]

        assert merged_local_item.complete is True
        assert merged_local_item.completed_at == 1_700_000_000_000

    def test_sync_propagates_completed_at_only(self):
        """If both sides agree on `complete` but completed_at differs, sync the timestamp."""
        local = Database()
        remote = Database()

        local_list = create_todo_list("List")
        local_item = create_todo_item("Task")
        local_item.complete = True  # Already complete locally, no timestamp
        local_list.add_item(local_item)
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        time.sleep(0.01)
        remote_item = remote_list.items[local_item.id]
        # Same complete flag (True), but the remote learned the actual timestamp
        # via a CalDAV import or similar.
        remote_item.completed_at = 1_700_000_500_000
        remote_item.mark_updated()

        merge_databases(local, remote)
        merged_local_item = local.lists[local_list.id].items[local_item.id]

        assert merged_local_item.complete is True
        assert merged_local_item.completed_at == 1_700_000_500_000


class TestMergeResult:
    """Tests for MergeResult."""

    def test_has_conflicts(self):
        """Test has_conflicts property."""
        from uuid import uuid4

        from pytodo_qt.core.sync_engine import ConflictInfo, MergeResult

        result = MergeResult(merged_db=Database())
        assert not result.has_conflicts

        result.conflicts.append(
            ConflictInfo(
                item_type="item",
                item_id=uuid4(),
                list_id=uuid4(),
                local_value="a",
                remote_value="b",
                winner="remote",
                field="test",
            )
        )
        assert result.has_conflicts

    def test_changes_made(self):
        """Test changes_made property."""
        from uuid import uuid4

        from pytodo_qt.core.sync_engine import MergeResult

        result = MergeResult(merged_db=Database())
        assert not result.changes_made

        result.added_lists.append(uuid4())
        assert result.changes_made


class TestSyncEngineDiff:
    """Tests for diff() method."""

    def test_diff_empty_databases(self):
        """Test diff of two empty databases."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()
        local = Database()
        remote = Database()

        diff = engine.diff(local, remote)

        assert diff["new_lists"] == []
        assert diff["updated_lists"] == []
        assert diff["deleted_lists"] == []
        assert diff["new_items"] == []
        assert diff["updated_items"] == []
        assert diff["deleted_items"] == []

    def test_diff_new_list(self):
        """Test diff when remote has a new list."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()
        local = Database()
        remote = Database()

        new_list = create_todo_list("New List")
        remote.add_list(new_list)

        diff = engine.diff(local, remote)

        assert "New List" in diff["new_lists"]
        assert diff["updated_lists"] == []

    def test_diff_updated_list(self):
        """Test diff when remote has updated list."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()
        local = Database()
        remote = Database()

        # Same list in both
        local_list = create_todo_list("Shared")
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Update remote
        time.sleep(0.01)
        remote_list.name = "Updated Name"
        remote_list.mark_updated()

        diff = engine.diff(local, remote)

        assert "Shared" in diff["updated_lists"]

    def test_diff_deleted_list(self):
        """Test diff when remote has deleted list."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()
        local = Database()
        remote = Database()

        # Same list in both
        local_list = create_todo_list("To Delete")
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Delete on remote
        time.sleep(0.01)
        remote_list.deleted = True
        remote_list.mark_updated()

        diff = engine.diff(local, remote)

        assert "To Delete" in diff["deleted_lists"]

    def test_diff_new_item(self):
        """Test diff when remote has new item."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()
        local = Database()
        remote = Database()

        # Same list in both
        local_list = create_todo_list("Shared")
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Add item only to remote
        new_item = create_todo_item("New Task From Remote")
        remote_list.add_item(new_item)

        diff = engine.diff(local, remote)

        assert "New Task From Remote" in diff["new_items"]

    def test_diff_updated_item(self):
        """Test diff when remote has updated item."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()
        local = Database()
        remote = Database()

        # Same list and item in both
        local_list = create_todo_list("Shared")
        local_item = create_todo_item("Task")
        local_list.add_item(local_item)
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Update remote item
        time.sleep(0.01)
        remote_item = remote_list.items[local_item.id]
        remote_item.reminder = "Updated Task"
        remote_item.mark_updated()

        diff = engine.diff(local, remote)

        assert "Task" in diff["updated_items"]

    def test_diff_deleted_item(self):
        """Test diff when remote has deleted item."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()
        local = Database()
        remote = Database()

        # Same list and item in both
        local_list = create_todo_list("Shared")
        local_item = create_todo_item("Task To Delete")
        local_list.add_item(local_item)
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Delete remote item
        time.sleep(0.01)
        remote_list.remove_item(local_item.id)

        diff = engine.diff(local, remote)

        assert "Task To Delete" in diff["deleted_items"]


class TestGarbageCollection:
    """Tests for _garbage_collect() method."""

    def test_garbage_collect_old_item_tombstone(self):
        """Test that old item tombstones are removed."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()
        engine._tombstone_ttl_ms = 100  # Set very short TTL for testing

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Old Deleted")
        item.deleted = True
        # Set updated_at to far in the past
        item.updated_at = 1000  # Very old timestamp in ms
        lst.items[item.id] = item
        db.add_list(lst)

        # Item should exist before GC
        assert item.id in lst.items

        # Run garbage collection
        engine._garbage_collect(db)

        # Item should be removed
        assert item.id not in lst.items

    def test_garbage_collect_keeps_recent_tombstone(self):
        """Test that recent tombstones are kept."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Recent Deleted")
        item.deleted = True
        item.mark_updated()  # Recent timestamp
        lst.items[item.id] = item
        db.add_list(lst)

        # Item should exist before GC
        assert item.id in lst.items

        engine._garbage_collect(db)

        # Item should still exist (too recent)
        assert item.id in lst.items

    def test_garbage_collect_old_list_tombstone(self):
        """Test that old list tombstones are removed."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()
        engine._tombstone_ttl_ms = 100  # Short TTL

        db = Database()
        lst = create_todo_list("Old Deleted List")
        lst.deleted = True
        lst.updated_at = 1000  # Very old
        db.lists[lst.id] = lst

        # List should exist before GC
        assert lst.id in db.lists

        engine._garbage_collect(db)

        # List should be removed
        assert lst.id not in db.lists

    def test_garbage_collect_keeps_active_items(self):
        """Test that non-deleted items are never removed."""
        from pytodo_qt.core.sync_engine import SyncEngine

        engine = SyncEngine()
        engine._tombstone_ttl_ms = 100

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Active Item")
        item.updated_at = 1000  # Old but not deleted
        lst.items[item.id] = item
        db.add_list(lst)

        engine._garbage_collect(db)

        # Item should still exist
        assert item.id in lst.items


class TestSyncEngineGlobal:
    """Tests for global sync engine functions."""

    def test_get_sync_engine_singleton(self):
        """Test that get_sync_engine returns same instance."""
        import pytodo_qt.core.sync_engine as sync_module

        # Reset global
        sync_module._sync_engine = None

        engine1 = sync_module.get_sync_engine()
        engine2 = sync_module.get_sync_engine()

        assert engine1 is engine2

        # Cleanup
        sync_module._sync_engine = None


class TestListNameConflict:
    """Tests for list name conflict tracking."""

    def test_merge_list_name_conflict(self):
        """Test that list name changes create conflicts."""
        local = Database()
        remote = Database()

        # Same list in both
        local_list = create_todo_list("Original Name")
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Update name on remote
        time.sleep(0.01)
        remote_list.name = "New Name"
        remote_list.mark_updated()

        result = merge_databases(local, remote)

        # Should have conflict for name
        name_conflict = next((c for c in result.conflicts if c.field == "name"), None)
        assert name_conflict is not None
        assert name_conflict.item_type == "list"
        assert name_conflict.local_value == "Original Name"
        assert name_conflict.remote_value == "New Name"
        assert name_conflict.winner == "remote"

        # Local should be updated
        assert local_list.name == "New Name"


class TestListDeletionSync:
    """Tests for list deletion synchronization."""

    def test_merge_list_deletion(self):
        """Test that list deletion syncs correctly."""
        local = Database()
        remote = Database()

        # Same list in both
        local_list = create_todo_list("To Delete")
        local.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        # Delete on remote
        time.sleep(0.01)
        remote_list.deleted = True
        remote_list.mark_updated()

        result = merge_databases(local, remote)

        # Local should be marked deleted
        assert local_list.deleted is True
        assert local_list.id in result.deleted_lists

    def test_merge_list_undelete(self):
        """Test that list undeletion syncs correctly."""
        local = Database()
        remote = Database()

        # Create deleted list in local
        local_list = create_todo_list("Deleted List")
        local_list.deleted = True
        local.add_list(local_list)

        # Clone to remote but undelete
        remote_list = TodoList.from_dict(local_list.to_dict())
        remote.add_list(remote_list)

        time.sleep(0.01)
        remote_list.deleted = False
        remote_list.mark_updated()

        result = merge_databases(local, remote)

        # Local should be restored
        assert local_list.deleted is False
        assert local_list.id in result.updated_lists
