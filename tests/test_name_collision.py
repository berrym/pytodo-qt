"""Tests for list name collision resolution and list-level metadata LWW during sync."""

import json
import time
from unittest.mock import MagicMock

from pytodo_qt.core.models import Database, TodoList, create_todo_item, create_todo_list


class TestResolveNameCollision:
    """Tests for Database.resolve_name_collision()."""

    def test_no_collision_returns_original(self):
        """Name returned unchanged when no collision exists."""
        db = Database()
        db.add_list(create_todo_list("Groceries"))

        assert db.resolve_name_collision("Shopping") == "Shopping"

    def test_collision_with_peer_name(self):
        """Collision appends '(from PeerName)' suffix."""
        db = Database()
        db.add_list(create_todo_list("Shopping"))

        assert db.resolve_name_collision("Shopping", "Mac") == "Shopping (from Mac)"

    def test_collision_without_peer_name(self):
        """Collision without peer name appends '(synced)' suffix."""
        db = Database()
        db.add_list(create_todo_list("Shopping"))

        assert db.resolve_name_collision("Shopping") == "Shopping (synced)"

    def test_collision_empty_peer_name(self):
        """Empty peer_name treated same as no peer name."""
        db = Database()
        db.add_list(create_todo_list("Shopping"))

        assert db.resolve_name_collision("Shopping", "") == "Shopping (synced)"

    def test_double_collision_adds_counter(self):
        """When renamed version also collides, appends counter."""
        db = Database()
        db.add_list(create_todo_list("Shopping"))
        db.add_list(create_todo_list("Shopping (from Mac)"))

        assert db.resolve_name_collision("Shopping", "Mac") == "Shopping (from Mac) 2"

    def test_triple_collision_increments_counter(self):
        """Counter increments past existing numbered collisions."""
        db = Database()
        db.add_list(create_todo_list("Shopping"))
        db.add_list(create_todo_list("Shopping (synced)"))
        db.add_list(create_todo_list("Shopping (synced) 2"))

        assert db.resolve_name_collision("Shopping") == "Shopping (synced) 3"

    def test_deleted_lists_ignored(self):
        """Deleted lists don't count as collisions."""
        db = Database()
        deleted_list = create_todo_list("Shopping")
        deleted_list.mark_deleted()
        db.add_list(deleted_list)

        assert db.resolve_name_collision("Shopping") == "Shopping"

    def test_empty_database(self):
        """No collision in empty database."""
        db = Database()

        assert db.resolve_name_collision("Shopping") == "Shopping"

    def test_peer_name_with_spaces(self):
        """Peer names with spaces work correctly."""
        db = Database()
        db.add_list(create_todo_list("Shopping"))

        assert (
            db.resolve_name_collision("Shopping", "Michael's MacBook Pro")
            == "Shopping (from Michael's MacBook Pro)"
        )


class TestMergeNameCollision:
    """Tests for name collision during merge in _merge_sync_data_internal."""

    def _make_merge_window(self, db=None):
        """Create a minimal mock that exercises the real merge logic."""
        window = MagicMock()
        window._database = db or Database()
        window._save_database = MagicMock()
        window._refresh_ui = MagicMock()
        window._storage = MagicMock()
        window.status_bar_widget = MagicMock()
        return window

    def test_new_list_no_collision(self):
        """New list from remote added with original name when no collision."""
        from pytodo_qt.gui.main_window import MainWindow

        db = Database()
        db.add_list(create_todo_list("Groceries"))

        remote_list = create_todo_list("Shopping")
        remote_list.add_item(create_todo_item("Milk"))
        remote_db = Database()
        remote_db.add_list(remote_list)
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        merged, _, _, _ = MainWindow._merge_sync_data_internal(window, remote_data, "Mac")

        assert merged == 1
        # List should keep original name
        added = db.get_list(remote_list.id)
        assert added is not None
        assert added.name == "Shopping"

    def test_new_list_with_collision_renamed(self):
        """New list from remote renamed when name collides with local list."""
        from pytodo_qt.gui.main_window import MainWindow

        db = Database()
        db.add_list(create_todo_list("Shopping"))

        remote_list = create_todo_list("Shopping")
        remote_list.add_item(create_todo_item("Bread"))
        remote_db = Database()
        remote_db.add_list(remote_list)
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        merged, _, _, _ = MainWindow._merge_sync_data_internal(window, remote_data, "Mac")

        assert merged == 1
        added = db.get_list(remote_list.id)
        assert added is not None
        assert added.name == "Shopping (from Mac)"

    def test_new_list_collision_no_peer_name(self):
        """Collision without peer name uses '(synced)' suffix."""
        from pytodo_qt.gui.main_window import MainWindow

        db = Database()
        db.add_list(create_todo_list("Shopping"))

        remote_list = create_todo_list("Shopping")
        remote_db = Database()
        remote_db.add_list(remote_list)
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        MainWindow._merge_sync_data_internal(window, remote_data)

        added = db.get_list(remote_list.id)
        assert added is not None
        assert added.name == "Shopping (synced)"

    def test_existing_list_by_uuid_no_rename(self):
        """Existing list matched by UUID merges items without renaming."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        local_item = create_todo_item("Milk")
        local_list.add_item(local_item)
        db = Database()
        db.add_list(local_list)

        # Remote has same list UUID with a new item
        remote_list = create_todo_list("Shopping")
        remote_list.id = local_list.id  # Same UUID
        remote_list.name = "Shopping"
        new_item = create_todo_item("Bread")
        remote_list.items[new_item.id] = new_item
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        merged, _, _, _ = MainWindow._merge_sync_data_internal(window, remote_data, "Mac")

        assert merged == 1  # New item added
        # Name should NOT be changed — same UUID means same list
        local = db.get_list(local_list.id)
        assert local is not None
        assert local.name == "Shopping"

    def test_multiple_new_lists_collision(self):
        """Multiple new lists with same name each get unique renames."""
        from pytodo_qt.gui.main_window import MainWindow

        db = Database()
        db.add_list(create_todo_list("Shopping"))

        # First remote list
        remote_list1 = create_todo_list("Shopping")
        remote_db1 = Database()
        remote_db1.add_list(remote_list1)
        data1 = json.dumps(remote_db1.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        MainWindow._merge_sync_data_internal(window, data1, "Mac")

        # Now db has "Shopping" and "Shopping (from Mac)"
        # Second remote list with same name
        remote_list2 = create_todo_list("Shopping")
        remote_db2 = Database()
        remote_db2.add_list(remote_list2)
        data2 = json.dumps(remote_db2.to_dict()).encode("utf-8")

        MainWindow._merge_sync_data_internal(window, data2, "Mac")

        added2 = db.get_list(remote_list2.id)
        assert added2 is not None
        assert added2.name == "Shopping (from Mac) 2"


class TestMergeListMetadataLWW:
    """Tests for list-level metadata LWW in _merge_sync_data_internal."""

    def _make_merge_window(self, db=None):
        """Create a minimal mock that exercises the real merge logic."""
        window = MagicMock()
        window._database = db or Database()
        return window

    def test_list_deletion_propagates(self):
        """Remote list deletion syncs to local when remote is newer."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        db = Database()
        db.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        time.sleep(0.01)
        remote_list.mark_deleted()
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        merged, _, _, _ = MainWindow._merge_sync_data_internal(window, remote_data)

        assert merged >= 1
        assert local_list.deleted is True

    def test_list_undeletion_propagates(self):
        """Remote list undeletion syncs to local when remote is newer."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        local_list.mark_deleted()
        db = Database()
        db.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        time.sleep(0.01)
        remote_list.deleted = False
        remote_list.mark_updated()
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        merged, _, _, _ = MainWindow._merge_sync_data_internal(window, remote_data)

        assert merged >= 1
        assert local_list.deleted is False

    def test_list_rename_propagates(self):
        """Remote list rename syncs to local when remote is newer."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        db = Database()
        db.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        time.sleep(0.01)
        remote_list.name = "Groceries"
        remote_list.mark_updated()
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        merged, _, _, _ = MainWindow._merge_sync_data_internal(window, remote_data)

        assert merged >= 1
        assert local_list.name == "Groceries"

    def test_list_rename_with_collision_resolved(self):
        """Remote rename that collides with another local list gets disambiguated."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        other_list = create_todo_list("Groceries")
        db = Database()
        db.add_list(local_list)
        db.add_list(other_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        time.sleep(0.01)
        remote_list.name = "Groceries"  # Collides with other_list
        remote_list.mark_updated()
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        merged, _, _, _ = MainWindow._merge_sync_data_internal(window, remote_data, "Mac")

        assert merged >= 1
        assert local_list.name == "Groceries (from Mac)"

    def test_list_updated_at_propagates(self):
        """Remote updated_at overwrites local when remote is newer."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        db = Database()
        db.add_list(local_list)
        original_ts = local_list.updated_at

        remote_list = TodoList.from_dict(local_list.to_dict())
        time.sleep(0.01)
        remote_list.mark_deleted()
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        MainWindow._merge_sync_data_internal(window, remote_data)

        assert local_list.updated_at > original_ts
        assert local_list.updated_at == remote_list.updated_at

    def test_local_newer_metadata_preserved(self):
        """Local list metadata kept when local is newer than remote."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        db = Database()
        db.add_list(local_list)

        # Clone THEN update local so local is newer
        remote_list = TodoList.from_dict(local_list.to_dict())
        remote_list.name = "Groceries"

        time.sleep(0.01)
        local_list.mark_updated()

        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        _, local_newer, _, _ = MainWindow._merge_sync_data_internal(window, remote_data)

        assert local_list.name == "Shopping"
        assert local_list.deleted is False

    def test_equal_timestamps_no_metadata_change(self):
        """Identical timestamps don't trigger metadata update."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        db = Database()
        db.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        remote_list.name = "Groceries"  # Different name but same timestamp
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        MainWindow._merge_sync_data_internal(window, remote_data)

        assert local_list.name == "Shopping"

    def test_items_merge_independently_of_list_metadata(self):
        """Item-level LWW works regardless of which list timestamp is newer."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        item = create_todo_item("Milk")
        local_list.add_item(item)
        db = Database()
        db.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        # Make remote item newer but remote list metadata older
        remote_item = remote_list.items[item.id]
        time.sleep(0.01)
        remote_item.reminder = "Oat Milk"
        remote_item.mark_updated()
        # Don't call remote_list.mark_updated() — list timestamp stays old
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        merged, _, _, _ = MainWindow._merge_sync_data_internal(window, remote_data)

        assert merged >= 1
        assert local_list.items[item.id].reminder == "Oat Milk"
        # List name unchanged since list metadata wasn't newer
        assert local_list.name == "Shopping"

    def test_deletion_and_items_merge_together(self):
        """List deletion and item updates both apply in a single merge."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        item = create_todo_item("Milk")
        local_list.add_item(item)
        db = Database()
        db.add_list(local_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        time.sleep(0.01)
        # Update both item and list metadata
        remote_item = remote_list.items[item.id]
        remote_item.complete = True
        remote_item.mark_updated()
        remote_list.mark_deleted()  # Also bumps list updated_at
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        merged, _, _, _ = MainWindow._merge_sync_data_internal(window, remote_data)

        assert merged >= 2  # List metadata + item
        assert local_list.deleted is True
        assert local_list.items[item.id].complete is True

    def test_same_name_no_collision_resolution(self):
        """When remote name matches local name, no collision resolution needed."""
        from pytodo_qt.gui.main_window import MainWindow

        local_list = create_todo_list("Shopping")
        other_list = create_todo_list("Shopping (from Mac)")
        db = Database()
        db.add_list(local_list)
        db.add_list(other_list)

        remote_list = TodoList.from_dict(local_list.to_dict())
        time.sleep(0.01)
        remote_list.mark_deleted()  # Metadata changed, name stays "Shopping"
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        MainWindow._merge_sync_data_internal(window, remote_data)

        # Name unchanged, should NOT get collision suffix
        assert local_list.name == "Shopping"
        assert local_list.deleted is True

    def test_active_list_switches_on_sync_delete(self):
        """Active list switches to another list when sync deletes it."""
        from pytodo_qt.gui.main_window import MainWindow

        active_list = create_todo_list("Shopping")
        other_list = create_todo_list("Groceries")
        db = Database()
        db.add_list(active_list)
        db.add_list(other_list)
        db.set_active_list(active_list.id)

        remote_list = TodoList.from_dict(active_list.to_dict())
        time.sleep(0.01)
        remote_list.mark_deleted()
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        window._config.database.active_list = "Shopping"
        MainWindow._merge_sync_data_internal(window, remote_data)
        MainWindow._refresh_ui(window)

        assert active_list.deleted is True
        assert db.active_list_id == other_list.id

    def test_active_list_cleared_when_all_deleted(self):
        """Active list becomes None when sync deletes the only list."""
        from pytodo_qt.gui.main_window import MainWindow

        only_list = create_todo_list("Shopping")
        db = Database()
        db.add_list(only_list)
        db.set_active_list(only_list.id)

        remote_list = TodoList.from_dict(only_list.to_dict())
        time.sleep(0.01)
        remote_list.mark_deleted()
        remote_db = Database()
        remote_db.lists[remote_list.id] = remote_list
        remote_data = json.dumps(remote_db.to_dict()).encode("utf-8")

        window = self._make_merge_window(db)
        window._config.database.active_list = "Shopping"
        MainWindow._merge_sync_data_internal(window, remote_data)
        MainWindow._refresh_ui(window)

        assert only_list.deleted is True
        assert db.active_list_id is None
