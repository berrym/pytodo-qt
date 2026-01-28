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
