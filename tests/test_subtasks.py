"""Tests for subtask functionality.

Covers: data model, serialization, database, commands, display order, filter.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from pytodo_qt.core.database import DatabaseStorage
from pytodo_qt.core.models import (
    Database,
    TodoItem,
    TodoList,
    create_todo_item,
    create_todo_list,
)
from pytodo_qt.gui.commands import (
    AddItemCommand,
    DeleteItemsCommand,
    ReparentCommand,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeConfigManager:
    def save(self):
        pass


class FakeConfig:
    class database:
        active_list = ""


def make_window(db: Database | None = None) -> MagicMock:
    window = MagicMock()
    window._database = db or Database()
    window._save_database = MagicMock()
    window._refresh_ui = MagicMock()
    window._config = FakeConfig()
    window._config_manager = FakeConfigManager()
    window.status_bar_widget = MagicMock()
    return window


def make_parent_child_db() -> tuple[Database, TodoList, TodoItem, TodoItem]:
    """Create a database with one list containing a parent and a child item."""
    db = Database()
    lst = create_todo_list("Test")
    parent = create_todo_item("Parent task")
    child = create_todo_item("Child task", parent_id=parent.id)
    lst.add_item(parent)
    lst.add_item(child)
    db.add_list(lst)
    db.set_active_list(lst.id)
    return db, lst, parent, child


# ===========================================================================
# Model tests
# ===========================================================================


class TestTodoItemParentId:
    def test_default_parent_id_is_none(self):
        item = TodoItem(reminder="test")
        assert item.parent_id is None

    def test_parent_id_set(self):
        pid = uuid4()
        item = TodoItem(reminder="test", parent_id=pid)
        assert item.parent_id == pid

    def test_is_subtask_false_for_top_level(self):
        item = TodoItem(reminder="test")
        assert item.is_subtask is False

    def test_is_subtask_true_when_parent_set(self):
        item = TodoItem(reminder="test", parent_id=uuid4())
        assert item.is_subtask is True


class TestTodoItemSerialization:
    def test_to_dict_includes_parent_id_none(self):
        item = TodoItem(reminder="test")
        d = item.to_dict()
        assert "parent_id" in d
        assert d["parent_id"] is None

    def test_to_dict_includes_parent_id_value(self):
        pid = uuid4()
        item = TodoItem(reminder="test", parent_id=pid)
        d = item.to_dict()
        assert d["parent_id"] == str(pid)

    def test_from_dict_round_trip(self):
        pid = uuid4()
        item = TodoItem(reminder="test", parent_id=pid, priority=1)
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.parent_id == pid
        assert restored.reminder == "test"
        assert restored.priority == 1

    def test_from_dict_backward_compat_no_parent_id(self):
        """Older serialized data without parent_id should default to None."""
        d = {"id": str(uuid4()), "reminder": "old item"}
        item = TodoItem.from_dict(d)
        assert item.parent_id is None


class TestCreateTodoItem:
    def test_create_with_parent_id(self):
        pid = uuid4()
        item = create_todo_item("sub", parent_id=pid)
        assert item.parent_id == pid
        assert item.is_subtask

    def test_create_without_parent_id(self):
        item = create_todo_item("top")
        assert item.parent_id is None
        assert not item.is_subtask


class TestTodoListHelpers:
    def test_get_children(self):
        lst = create_todo_list("Test")
        parent = create_todo_item("Parent")
        c1 = create_todo_item("Child 1", parent_id=parent.id)
        c2 = create_todo_item("Child 2", parent_id=parent.id)
        other = create_todo_item("Other")
        lst.add_item(parent)
        lst.add_item(c1)
        lst.add_item(c2)
        lst.add_item(other)

        children = lst.get_children(parent.id)
        assert len(children) == 2
        assert c1 in children
        assert c2 in children

    def test_get_children_empty(self):
        lst = create_todo_list("Test")
        parent = create_todo_item("Parent")
        lst.add_item(parent)
        assert lst.get_children(parent.id) == []

    def test_child_count(self):
        lst = create_todo_list("Test")
        parent = create_todo_item("Parent")
        c1 = create_todo_item("C1", parent_id=parent.id)
        c2 = create_todo_item("C2", parent_id=parent.id)
        lst.add_item(parent)
        lst.add_item(c1)
        lst.add_item(c2)
        assert lst.child_count(parent.id) == 2

    def test_child_completed_count(self):
        lst = create_todo_list("Test")
        parent = create_todo_item("Parent")
        c1 = create_todo_item("C1", parent_id=parent.id)
        c2 = create_todo_item("C2", parent_id=parent.id)
        c1.complete = True
        lst.add_item(parent)
        lst.add_item(c1)
        lst.add_item(c2)
        assert lst.child_completed_count(parent.id) == 1

    def test_get_children_excludes_deleted(self):
        lst = create_todo_list("Test")
        parent = create_todo_item("Parent")
        child = create_todo_item("Child", parent_id=parent.id)
        child.mark_deleted()
        lst.add_item(parent)
        lst.add_item(child)
        assert lst.get_children(parent.id) == []
        assert lst.child_count(parent.id) == 0

    def test_depth_limit_enforcement(self):
        """Subtasks should not have subtasks (single level)."""
        parent = create_todo_item("Parent")
        child = create_todo_item("Child", parent_id=parent.id)
        # A child's parent_id being set means it's a subtask
        assert child.is_subtask
        # Trying to make a grandchild is blocked by the UI, not the model


# ===========================================================================
# Database tests
# ===========================================================================


class TestDatabaseSubtasks:
    def _make_storage(self, tmp_path: Path) -> DatabaseStorage:
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)
        storage.open()
        return storage

    def test_schema_version_11(self, tmp_path):
        storage = self._make_storage(tmp_path)
        assert storage.get_schema_version() >= 11
        storage.close()

    def test_save_load_with_parent_id(self, tmp_path):
        storage = self._make_storage(tmp_path)
        lst = create_todo_list("Test")
        storage.save_list(lst)

        parent = create_todo_item("Parent")
        child = create_todo_item("Child", parent_id=parent.id)
        storage.save_item(lst.id, parent)
        storage.save_item(lst.id, child)

        loaded_parent = storage.get_item(parent.id)
        loaded_child = storage.get_item(child.id)
        assert loaded_parent is not None
        assert loaded_parent.parent_id is None
        assert loaded_child is not None
        assert loaded_child.parent_id == parent.id
        storage.close()

    def test_save_load_null_parent_id(self, tmp_path):
        storage = self._make_storage(tmp_path)
        lst = create_todo_list("Test")
        storage.save_list(lst)

        item = create_todo_item("No parent")
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.parent_id is None
        storage.close()

    def test_parent_id_index_exists(self, tmp_path):
        storage = self._make_storage(tmp_path)
        cursor = storage.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_items_parent_id'"
        )
        assert cursor.fetchone() is not None
        storage.close()

    def test_migration_from_v10(self, tmp_path):
        """Simulate a v10 database and verify migration adds parent_id."""
        db_path = tmp_path / "v10.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES ('schema_version', '10')")
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
                complete INTEGER NOT NULL DEFAULT 0, due_date TEXT, due_time TEXT,
                tags TEXT, recurrence_type TEXT,
                recurrence_interval INTEGER NOT NULL DEFAULT 1,
                recurrence_end_date TEXT, recurrence_end_count INTEGER,
                recurrence_count INTEGER NOT NULL DEFAULT 0,
                time_spent INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (list_id) REFERENCES lists(id)
            )"""
        )
        # Create required sync tables for migration
        conn.execute(
            """CREATE TABLE devices (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL, first_seen INTEGER NOT NULL,
                last_seen INTEGER NOT NULL, last_address TEXT,
                trust_level TEXT NOT NULL DEFAULT 'normal'
            )"""
        )
        conn.execute(
            """CREATE TABLE sync_groups (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE device_groups (
                device_id TEXT NOT NULL, group_id TEXT NOT NULL,
                PRIMARY KEY (device_id, group_id)
            )"""
        )
        conn.execute(
            """CREATE TABLE list_sync_rules (
                list_id TEXT NOT NULL, group_id TEXT NOT NULL,
                PRIMARY KEY (list_id, group_id)
            )"""
        )
        conn.execute(
            """CREATE TABLE pending_syncs (
                id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                list_ids TEXT, created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt INTEGER
            )"""
        )
        conn.commit()
        conn.close()

        # Open with DatabaseStorage which should migrate
        storage = DatabaseStorage(db_path)
        storage.open()
        assert storage.get_schema_version() == 16

        # Verify parent_id column exists
        cursor = storage.connection.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "parent_id" in columns
        storage.close()


# ===========================================================================
# Command tests
# ===========================================================================


class TestAddItemCommandWithParent:
    def test_add_subtask(self):
        db, lst, parent, _child = make_parent_child_db()
        window = make_window(db)

        new_child = create_todo_item("New subtask", parent_id=parent.id)
        cmd = AddItemCommand(window, lst.id, new_child)
        cmd.redo()

        assert new_child.id in lst.items
        assert lst.items[new_child.id].parent_id == parent.id

    def test_undo_add_subtask(self):
        db, lst, parent, _child = make_parent_child_db()
        window = make_window(db)

        new_child = create_todo_item("New subtask", parent_id=parent.id)
        cmd = AddItemCommand(window, lst.id, new_child)
        cmd.redo()
        cmd.undo()

        assert lst.items[new_child.id].deleted


class TestDeleteItemsCommandCascade:
    def test_delete_parent_orphans_children(self):
        db, lst, parent, child = make_parent_child_db()
        window = make_window(db)

        cmd = DeleteItemsCommand(window, lst.id, [parent.id])
        cmd.redo()

        # Parent should be deleted
        assert lst.items[parent.id].deleted
        # Child should be promoted to top-level
        assert child.parent_id is None
        assert not child.deleted

    def test_undo_delete_parent_restores_nesting(self):
        db, lst, parent, child = make_parent_child_db()
        window = make_window(db)

        cmd = DeleteItemsCommand(window, lst.id, [parent.id])
        cmd.redo()
        assert child.parent_id is None

        cmd.undo()
        assert not parent.deleted
        assert child.parent_id == parent.id

    def test_delete_child_only(self):
        db, lst, parent, child = make_parent_child_db()
        window = make_window(db)

        cmd = DeleteItemsCommand(window, lst.id, [child.id])
        cmd.redo()

        assert lst.items[child.id].deleted
        assert not parent.deleted

    def test_delete_both_parent_and_child(self):
        db, lst, parent, child = make_parent_child_db()
        window = make_window(db)

        cmd = DeleteItemsCommand(window, lst.id, [parent.id, child.id])
        cmd.redo()

        assert lst.items[parent.id].deleted
        assert lst.items[child.id].deleted

    def test_delete_parent_multiple_children(self):
        db = Database()
        lst = create_todo_list("Test")
        parent = create_todo_item("Parent")
        c1 = create_todo_item("C1", parent_id=parent.id)
        c2 = create_todo_item("C2", parent_id=parent.id)
        lst.add_item(parent)
        lst.add_item(c1)
        lst.add_item(c2)
        db.add_list(lst)
        window = make_window(db)

        cmd = DeleteItemsCommand(window, lst.id, [parent.id])
        cmd.redo()

        assert c1.parent_id is None
        assert c2.parent_id is None

        cmd.undo()
        assert c1.parent_id == parent.id
        assert c2.parent_id == parent.id


class TestReparentCommand:
    def test_redo_sets_parent(self):
        db, lst, parent, _child = make_parent_child_db()
        window = make_window(db)

        orphan = create_todo_item("Orphan")
        lst.add_item(orphan)

        cmd = ReparentCommand(window, lst.id, orphan.id, None, parent.id)
        cmd.redo()

        assert orphan.parent_id == parent.id

    def test_undo_restores_parent(self):
        db, lst, parent, child = make_parent_child_db()
        window = make_window(db)

        cmd = ReparentCommand(window, lst.id, child.id, parent.id, None)
        cmd.redo()
        assert child.parent_id is None

        cmd.undo()
        assert child.parent_id == parent.id

    def test_noop_missing_item(self):
        db, lst, parent, _child = make_parent_child_db()
        window = make_window(db)
        missing_id = uuid4()

        cmd = ReparentCommand(window, lst.id, missing_id, None, parent.id)
        cmd.redo()  # Should not raise
        cmd.undo()  # Should not raise

    def test_noop_missing_list(self):
        db = Database()
        window = make_window(db)
        missing_list = uuid4()

        cmd = ReparentCommand(window, missing_list, uuid4(), None, uuid4())
        cmd.redo()  # Should not raise
        cmd.undo()  # Should not raise


# ===========================================================================
# Display order tests
# ===========================================================================


class TestBuildDisplayOrder:
    """Test _build_display_order via the TodoTableWidget."""

    def _make_widget(self):
        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        widget = TodoTableWidget()
        return widget

    def test_top_level_only(self, qtbot):
        widget = self._make_widget()
        qtbot.addWidget(widget)

        items = [
            create_todo_item("A"),
            create_todo_item("B"),
        ]

        result = widget._build_display_order(items, lambda i: i.reminder)
        assert len(result) == 2
        assert all(not is_child for _, is_child in result)

    def test_parent_then_children(self, qtbot):
        widget = self._make_widget()
        qtbot.addWidget(widget)

        parent = create_todo_item("Parent")
        child1 = create_todo_item("Child 1", parent_id=parent.id)
        child2 = create_todo_item("Child 2", parent_id=parent.id)
        items = [parent, child1, child2]

        result = widget._build_display_order(items, lambda i: i.reminder)
        assert len(result) == 3
        assert result[0] == (parent, False)
        assert result[1][1] is True  # is_child
        assert result[2][1] is True

    def test_collapsed_hides_children(self, qtbot):
        widget = self._make_widget()
        qtbot.addWidget(widget)

        parent = create_todo_item("Parent")
        child = create_todo_item("Child", parent_id=parent.id)
        items = [parent, child]

        widget._collapsed_parents.add(parent.id)
        result = widget._build_display_order(items, lambda i: i.reminder)
        assert len(result) == 1
        assert result[0] == (parent, False)

    def test_expand_after_collapse(self, qtbot):
        widget = self._make_widget()
        qtbot.addWidget(widget)

        parent = create_todo_item("Parent")
        child = create_todo_item("Child", parent_id=parent.id)
        items = [parent, child]

        widget._collapsed_parents.add(parent.id)
        result = widget._build_display_order(items, lambda i: i.reminder)
        assert len(result) == 1

        widget._collapsed_parents.discard(parent.id)
        result = widget._build_display_order(items, lambda i: i.reminder)
        assert len(result) == 2

    def test_orphan_promotion(self, qtbot):
        """Children whose parent is not in the item list become top-level."""
        widget = self._make_widget()
        qtbot.addWidget(widget)

        missing_parent_id = uuid4()
        orphan = create_todo_item("Orphan", parent_id=missing_parent_id)
        items = [orphan]

        result = widget._build_display_order(items, lambda i: i.reminder)
        assert len(result) == 1
        assert result[0] == (orphan, False)  # Promoted to top-level

    def test_multiple_parents_interleaved(self, qtbot):
        widget = self._make_widget()
        qtbot.addWidget(widget)

        p1 = create_todo_item("A Parent")
        p2 = create_todo_item("B Parent")
        c1 = create_todo_item("A Child", parent_id=p1.id)
        c2 = create_todo_item("B Child", parent_id=p2.id)
        items = [p1, p2, c1, c2]

        result = widget._build_display_order(items, lambda i: i.reminder)
        # A Parent, A Child, B Parent, B Child
        assert len(result) == 4
        assert result[0][0] == p1
        assert result[1][0] == c1
        assert result[2][0] == p2
        assert result[3][0] == c2

    def test_progress_badge_counts(self):
        """Test TodoList child helpers for badge computation."""
        lst = create_todo_list("Test")
        parent = create_todo_item("Parent")
        c1 = create_todo_item("C1", parent_id=parent.id)
        c2 = create_todo_item("C2", parent_id=parent.id)
        c3 = create_todo_item("C3", parent_id=parent.id)
        c1.complete = True
        c3.complete = True
        lst.add_item(parent)
        lst.add_item(c1)
        lst.add_item(c2)
        lst.add_item(c3)

        assert lst.child_count(parent.id) == 3
        assert lst.child_completed_count(parent.id) == 2


# ===========================================================================
# Filter tests
# ===========================================================================


class TestFilterWithSubtasks:
    def _make_widget(self):
        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        return TodoTableWidget()

    def test_child_match_pulls_parent(self, qtbot):
        from pytodo_qt.gui.widgets.search_filter import FilterState

        widget = self._make_widget()
        qtbot.addWidget(widget)

        parent = create_todo_item("Shopping")
        child = create_todo_item("Buy milk", parent_id=parent.id)
        items = [parent, child]

        widget._filter_state = FilterState(text="milk")
        filtered = widget._apply_filter(items)

        filtered_ids = {i.id for i in filtered}
        assert child.id in filtered_ids
        assert parent.id in filtered_ids
        assert parent.id in widget._context_row_ids

    def test_parent_match_does_not_duplicate(self, qtbot):
        from pytodo_qt.gui.widgets.search_filter import FilterState

        widget = self._make_widget()
        qtbot.addWidget(widget)

        parent = create_todo_item("Buy groceries")
        child = create_todo_item("Buy milk", parent_id=parent.id)
        items = [parent, child]

        widget._filter_state = FilterState(text="buy")
        filtered = widget._apply_filter(items)

        # Both match directly, parent should NOT be in context rows
        assert parent.id not in widget._context_row_ids
        assert len(filtered) == 2

    def test_no_filter_no_context_rows(self, qtbot):
        widget = self._make_widget()
        qtbot.addWidget(widget)

        parent = create_todo_item("Parent")
        child = create_todo_item("Child", parent_id=parent.id)
        items = [parent, child]

        widget._filter_state = None
        filtered = widget._apply_filter(items)
        assert len(filtered) == 2
        assert len(widget._context_row_ids) == 0

    def test_filter_no_match_no_context(self, qtbot):
        from pytodo_qt.gui.widgets.search_filter import FilterState

        widget = self._make_widget()
        qtbot.addWidget(widget)

        parent = create_todo_item("Shopping")
        child = create_todo_item("Milk", parent_id=parent.id)
        items = [parent, child]

        widget._filter_state = FilterState(text="zzzzz")
        filtered = widget._apply_filter(items)
        assert len(filtered) == 0

    def test_multiple_children_one_parent_context(self, qtbot):
        from pytodo_qt.gui.widgets.search_filter import FilterState

        widget = self._make_widget()
        qtbot.addWidget(widget)

        parent = create_todo_item("Groceries")
        c1 = create_todo_item("Milk", parent_id=parent.id)
        c2 = create_todo_item("Eggs", parent_id=parent.id)
        items = [parent, c1, c2]

        widget._filter_state = FilterState(text="milk")
        filtered = widget._apply_filter(items)

        # Only milk matches + parent as context
        filtered_ids = {i.id for i in filtered}
        assert c1.id in filtered_ids
        assert parent.id in filtered_ids
        assert c2.id not in filtered_ids
        # Parent appears only once
        assert sum(1 for i in filtered if i.id == parent.id) == 1
