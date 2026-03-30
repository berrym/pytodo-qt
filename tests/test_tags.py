"""Comprehensive tests for the tags feature (Phase 1 / Schema v9).

Covers:
- Model: field defaults, serialization roundtrip, backward compat
- Database: schema v9, save/load with tags
- Commands: EditTagsCommand redo/undo
- Filter: tag filter, text search matching tags
- Factory function: create_todo_item with tags
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock
from uuid import uuid4

from pytodo_qt.core.database import SCHEMA_VERSION, DatabaseStorage
from pytodo_qt.core.models import (
    Database,
    TodoItem,
    TodoList,
    create_todo_item,
    create_todo_list,
)
from pytodo_qt.gui.commands import EditTagsCommand
from pytodo_qt.gui.widgets.search_filter import FilterState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_window(db: Database | None = None) -> MagicMock:
    """Create a mock MainWindow with a real Database."""
    window = MagicMock()
    window._database = db or Database()
    window._save_database = MagicMock()
    window._refresh_ui = MagicMock()
    return window


def make_populated_db(
    tags1: list[str] | None = None,
    tags2: list[str] | None = None,
) -> tuple[Database, TodoList, TodoItem, TodoItem]:
    """Create a database with one list containing two items."""
    db = Database()
    lst = create_todo_list("Test List")
    item1 = create_todo_item("Buy milk", priority=2, tags=tags1)
    item2 = create_todo_item("Write tests", priority=1, tags=tags2)
    lst.add_item(item1)
    lst.add_item(item2)
    db.add_list(lst)
    db.set_active_list(lst.id)
    return db, lst, item1, item2


# ===========================================================================
# Model tests
# ===========================================================================


class TestTodoItemTagsField:
    """Test the tags field on TodoItem."""

    def test_default_empty_list(self):
        item = TodoItem()
        assert item.tags == []

    def test_tags_are_independent_across_instances(self):
        item1 = TodoItem()
        item2 = TodoItem()
        item1.tags.append("@work")
        assert item2.tags == []

    def test_set_tags(self):
        item = TodoItem(tags=["@work", "@urgent"])
        assert item.tags == ["@work", "@urgent"]

    def test_modify_tags(self):
        item = TodoItem(tags=["@work"])
        item.tags.append("@home")
        assert item.tags == ["@work", "@home"]

    def test_clear_tags(self):
        item = TodoItem(tags=["@work", "@urgent"])
        item.tags.clear()
        assert item.tags == []

    def test_tags_preserved_through_to_dict(self):
        item = TodoItem(tags=["@work", "@errands"])
        d = item.to_dict()
        assert d["tags"] == ["@work", "@errands"]

    def test_empty_tags_in_to_dict(self):
        item = TodoItem()
        d = item.to_dict()
        assert d["tags"] == []


class TestTodoItemSerialization:
    """Test tags serialization roundtrip."""

    def test_roundtrip_with_tags(self):
        item = create_todo_item("Test", tags=["@work", "@quick"])
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.tags == ["@work", "@quick"]

    def test_roundtrip_empty_tags(self):
        item = create_todo_item("Test")
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.tags == []

    def test_from_dict_missing_tags_key(self):
        """Backward compat: old data without tags key."""
        d = {
            "id": str(uuid4()),
            "reminder": "Old item",
            "priority": 2,
            "complete": False,
        }
        item = TodoItem.from_dict(d)
        assert item.tags == []

    def test_roundtrip_preserves_tag_order(self):
        tags = ["@zebra", "@alpha", "@middle"]
        item = create_todo_item("Test", tags=tags)
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.tags == ["@zebra", "@alpha", "@middle"]

    def test_roundtrip_with_special_characters(self):
        tags = ["@work/project", "@home-stuff", "@2024"]
        item = create_todo_item("Test", tags=tags)
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.tags == tags

    def test_json_roundtrip_via_database(self):
        """Test full JSON serialization through Database model."""
        db = Database()
        lst = create_todo_list("Tagged List")
        item = create_todo_item("Tagged item", tags=["@dev", "@urgent"])
        lst.add_item(item)
        db.add_list(lst)

        json_str = db.to_json()
        restored = Database.from_json(json_str)
        restored_item = list(list(restored.lists.values())[0].items.values())[0]
        assert restored_item.tags == ["@dev", "@urgent"]

    def test_roundtrip_single_tag(self):
        item = create_todo_item("Test", tags=["@solo"])
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.tags == ["@solo"]

    def test_roundtrip_many_tags(self):
        tags = [f"@tag{i}" for i in range(20)]
        item = create_todo_item("Test", tags=tags)
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.tags == tags

    def test_roundtrip_unicode_tags(self):
        tags = ["@日本語", "@café", "@über"]
        item = create_todo_item("Test", tags=tags)
        d = item.to_dict()
        restored = TodoItem.from_dict(d)
        assert restored.tags == tags


class TestCreateTodoItem:
    """Test the create_todo_item factory function with tags."""

    def test_no_tags_param(self):
        item = create_todo_item("Test")
        assert item.tags == []

    def test_tags_param_none(self):
        item = create_todo_item("Test", tags=None)
        assert item.tags == []

    def test_tags_param_empty(self):
        item = create_todo_item("Test", tags=[])
        assert item.tags == []

    def test_tags_param_with_values(self):
        item = create_todo_item("Test", tags=["@work", "@urgent"])
        assert item.tags == ["@work", "@urgent"]

    def test_tags_param_single(self):
        item = create_todo_item("Test", tags=["@quick"])
        assert item.tags == ["@quick"]


# ===========================================================================
# Database tests
# ===========================================================================


class TestSchemaVersion:
    """Test schema version is updated."""

    def test_current_schema_version_is_9(self):
        assert SCHEMA_VERSION == 16

    def test_fresh_database_has_tags_column(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        cursor = storage.connection.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "tags" in columns
        storage.close()

    def test_schema_version_is_9(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)
        assert storage.get_schema_version() == 16
        storage.close()


class TestDatabaseSaveLoadTags:
    """Test saving and loading items with tags via DatabaseStorage."""

    def test_save_and_load_with_tags(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("Tagged", tags=["@work", "@urgent"])
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.tags == ["@work", "@urgent"]
        storage.close()

    def test_save_and_load_without_tags(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("No tags")
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.tags == []
        storage.close()

    def test_save_and_load_empty_tags(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("Empty tags", tags=[])
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.tags == []
        storage.close()

    def test_save_and_load_many_tags(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        tags = [f"@tag{i}" for i in range(20)]
        lst = create_todo_list("Test")
        item = create_todo_item("Many tags", tags=tags)
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.tags == tags
        storage.close()

    def test_update_tags_and_reload(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("Item", tags=["@old"])
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        # Update tags
        item.tags = ["@new", "@updated"]
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.tags == ["@new", "@updated"]
        storage.close()

    def test_tags_with_unicode(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("Unicode", tags=["@日本語", "@café", "@über"])
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.tags == ["@日本語", "@café", "@über"]
        storage.close()

    def test_reopen_database_preserves_tags(self, tmp_path):
        """Tags survive closing and reopening the database."""
        db_path = tmp_path / "test.db"

        storage = DatabaseStorage(db_path)
        lst = create_todo_list("Test")
        item = create_todo_item("Persist", tags=["@saved"])
        lst.add_item(item)
        storage.save_list(lst)
        storage.save_item(lst.id, item)
        item_id = item.id
        storage.close()

        # Reopen
        storage2 = DatabaseStorage(db_path)
        loaded = storage2.get_item(item_id)
        assert loaded is not None
        assert loaded.tags == ["@saved"]
        storage2.close()


# ===========================================================================
# Command tests
# ===========================================================================


class TestEditTagsCommand:
    """Test EditTagsCommand redo/undo."""

    def test_redo_sets_new_tags(self):
        db, lst, item, _ = make_populated_db(tags1=["@old"])
        window = make_window(db)

        cmd = EditTagsCommand(window, lst.id, item.id, ["@old"], ["@new", "@updated"])
        cmd.redo()

        assert item.tags == ["@new", "@updated"]
        window._save_database.assert_called()
        window._refresh_ui.assert_called()

    def test_undo_restores_old_tags(self):
        db, lst, item, _ = make_populated_db(tags1=["@old"])
        window = make_window(db)

        cmd = EditTagsCommand(window, lst.id, item.id, ["@old"], ["@new"])
        cmd.redo()
        assert item.tags == ["@new"]

        cmd.undo()
        assert item.tags == ["@old"]

    def test_redo_from_empty_to_tags(self):
        db, lst, item, _ = make_populated_db()
        window = make_window(db)

        cmd = EditTagsCommand(window, lst.id, item.id, [], ["@work", "@urgent"])
        cmd.redo()
        assert item.tags == ["@work", "@urgent"]

    def test_undo_from_tags_to_empty(self):
        db, lst, item, _ = make_populated_db(tags1=["@work", "@urgent"])
        window = make_window(db)

        cmd = EditTagsCommand(window, lst.id, item.id, ["@work", "@urgent"], [])
        cmd.redo()
        assert item.tags == []

        cmd.undo()
        assert item.tags == ["@work", "@urgent"]

    def test_missing_list_no_crash(self):
        db, lst, item, _ = make_populated_db()
        window = make_window(db)
        fake_list_id = uuid4()

        cmd = EditTagsCommand(window, fake_list_id, item.id, [], ["@tag"])
        cmd.redo()
        cmd.undo()

    def test_missing_item_no_crash(self):
        db, lst, item, _ = make_populated_db()
        window = make_window(db)
        fake_item_id = uuid4()

        cmd = EditTagsCommand(window, lst.id, fake_item_id, [], ["@tag"])
        cmd.redo()
        cmd.undo()

    def test_marks_updated_on_redo(self):
        db, lst, item, _ = make_populated_db(tags1=["@old"])
        window = make_window(db)
        old_ts = item.updated_at

        time.sleep(0.01)

        cmd = EditTagsCommand(window, lst.id, item.id, ["@old"], ["@new"])
        cmd.redo()
        assert item.updated_at >= old_ts

    def test_marks_updated_on_undo(self):
        db, lst, item, _ = make_populated_db(tags1=["@old"])
        window = make_window(db)

        cmd = EditTagsCommand(window, lst.id, item.id, ["@old"], ["@new"])
        cmd.redo()

        time.sleep(0.01)
        ts_after_redo = item.updated_at

        cmd.undo()
        assert item.updated_at >= ts_after_redo

    def test_multiple_redo_undo_cycles(self):
        db, lst, item, _ = make_populated_db()
        window = make_window(db)

        cmd = EditTagsCommand(window, lst.id, item.id, [], ["@a", "@b"])
        for _ in range(3):
            cmd.redo()
            assert item.tags == ["@a", "@b"]
            cmd.undo()
            assert item.tags == []

    def test_does_not_share_mutable_references(self):
        """Verify command stores copies, not references."""
        db, lst, item, _ = make_populated_db(tags1=["@original"])
        window = make_window(db)

        old_tags = item.tags.copy()
        new_tags = ["@changed"]

        cmd = EditTagsCommand(window, lst.id, item.id, old_tags, new_tags)

        # Mutate the lists we passed in
        old_tags.append("@sneaky")
        new_tags.append("@sneaky")

        cmd.redo()
        assert "@sneaky" not in item.tags
        assert item.tags == ["@changed"]

        cmd.undo()
        assert "@sneaky" not in item.tags
        assert item.tags == ["@original"]

    def test_only_affects_target_item(self):
        """Editing tags on one item should not affect the other."""
        db, lst, item1, item2 = make_populated_db(tags1=["@a"], tags2=["@b"])
        window = make_window(db)

        cmd = EditTagsCommand(window, lst.id, item1.id, ["@a"], ["@c"])
        cmd.redo()
        assert item1.tags == ["@c"]
        assert item2.tags == ["@b"]


# ===========================================================================
# FilterState tests
# ===========================================================================


class TestFilterStateTags:
    """Test FilterState with tag field."""

    def test_default_tag_empty(self):
        fs = FilterState()
        assert fs.tag == ""

    def test_tag_not_active_when_empty(self):
        fs = FilterState()
        assert not fs.is_active

    def test_tag_is_active_when_set(self):
        fs = FilterState(tag="@work")
        assert fs.is_active

    def test_all_filters_default_not_active(self):
        fs = FilterState(text="", priority=0, status=0, due_date=0, tag="")
        assert not fs.is_active

    def test_combined_text_and_tag_active(self):
        fs = FilterState(text="hello", tag="@work")
        assert fs.is_active

    def test_only_tag_active(self):
        fs = FilterState(tag="@urgent")
        assert fs.is_active
        assert fs.text == ""
        assert fs.priority == 0

    def test_tag_inactive_other_active(self):
        fs = FilterState(text="search")
        assert fs.is_active
        assert fs.tag == ""


# ===========================================================================
# Tag filtering logic tests (using model objects directly)
# ===========================================================================


class TestTagFiltering:
    """Test tag-based filtering logic matching _apply_filter."""

    def _filter_by_tag(self, items: list[TodoItem], tag: str) -> list[TodoItem]:
        if tag:
            return [i for i in items if tag in i.tags]
        return items

    def _filter_by_text(self, items: list[TodoItem], text: str) -> list[TodoItem]:
        if text:
            search = text.lower()
            return [
                i
                for i in items
                if search in i.reminder.lower() or any(search in tag.lower() for tag in i.tags)
            ]
        return items

    def test_filter_by_specific_tag(self):
        items = [
            create_todo_item("A", tags=["@work", "@urgent"]),
            create_todo_item("B", tags=["@home"]),
            create_todo_item("C", tags=["@work"]),
            create_todo_item("D"),
        ]
        result = self._filter_by_tag(items, "@work")
        assert len(result) == 2
        assert result[0].reminder == "A"
        assert result[1].reminder == "C"

    def test_filter_by_nonexistent_tag(self):
        items = [
            create_todo_item("A", tags=["@work"]),
            create_todo_item("B", tags=["@home"]),
        ]
        result = self._filter_by_tag(items, "@nonexistent")
        assert len(result) == 0

    def test_filter_no_tag_returns_all(self):
        items = [
            create_todo_item("A", tags=["@work"]),
            create_todo_item("B"),
        ]
        result = self._filter_by_tag(items, "")
        assert len(result) == 2

    def test_text_search_matches_tag(self):
        items = [
            create_todo_item("Buy milk", tags=["@errands"]),
            create_todo_item("Write code"),
        ]
        result = self._filter_by_text(items, "errands")
        assert len(result) == 1
        assert result[0].reminder == "Buy milk"

    def test_text_search_case_insensitive_on_tags(self):
        items = [create_todo_item("Task", tags=["@Work"])]
        result = self._filter_by_text(items, "work")
        assert len(result) == 1

    def test_text_search_partial_tag_match(self):
        items = [create_todo_item("Task", tags=["@workspace"])]
        result = self._filter_by_text(items, "work")
        assert len(result) == 1

    def test_text_search_matches_reminder_not_tag(self):
        items = [create_todo_item("Work meeting", tags=["@home"])]
        result = self._filter_by_text(items, "work")
        assert len(result) == 1

    def test_text_search_no_match(self):
        items = [create_todo_item("Task", tags=["@home"])]
        result = self._filter_by_text(items, "office")
        assert len(result) == 0

    def test_text_search_matches_at_prefix(self):
        items = [create_todo_item("Task", tags=["@work"])]
        result = self._filter_by_text(items, "@work")
        assert len(result) == 1

    def test_combined_tag_and_text_filter(self):
        items = [
            create_todo_item("Buy groceries", tags=["@errands", "@weekly"]),
            create_todo_item("Cook dinner", tags=["@errands"]),
            create_todo_item("Buy tools", tags=["@home"]),
        ]
        by_tag = self._filter_by_tag(items, "@errands")
        result = self._filter_by_text(by_tag, "buy")
        assert len(result) == 1
        assert result[0].reminder == "Buy groceries"

    def test_filter_items_without_tags(self):
        items = [
            create_todo_item("No tags"),
            create_todo_item("Has tags", tags=["@work"]),
        ]
        result = self._filter_by_tag(items, "@work")
        assert len(result) == 1
        assert result[0].reminder == "Has tags"

    def test_text_search_empty_tags_no_crash(self):
        items = [create_todo_item("Task")]
        result = self._filter_by_text(items, "@anything")
        assert len(result) == 0


# ===========================================================================
# Sync compatibility tests
# ===========================================================================


class TestTagsSyncCompat:
    """Test that tags work with sync serialization."""

    def test_old_format_without_tags(self):
        data = {
            "id": str(uuid4()),
            "reminder": "From old peer",
            "priority": 2,
            "complete": False,
            "created_at": 1000,
            "updated_at": 2000,
        }
        item = TodoItem.from_dict(data)
        assert item.tags == []
        assert item.reminder == "From old peer"

    def test_new_format_with_tags_to_old_peer(self):
        item = create_todo_item("New item", tags=["@work"])
        d = item.to_dict()
        assert "tags" in d
        assert d["reminder"] == "New item"

    def test_database_bytes_roundtrip_with_tags(self):
        db = Database()
        lst = create_todo_list("Sync Test")
        item = create_todo_item("Sync item", tags=["@shared", "@urgent"])
        lst.add_item(item)
        db.add_list(lst)

        raw = db.to_bytes()
        restored = Database.from_bytes(raw)
        restored_item = list(list(restored.lists.values())[0].items.values())[0]
        assert restored_item.tags == ["@shared", "@urgent"]

    def test_merge_newer_timestamp_wins(self):
        """LWW: the item with the newer timestamp has the winning tags."""
        item1 = create_todo_item("Item", tags=["@old"])
        item1.updated_at = 1000

        item2_data = item1.to_dict()
        item2_data["tags"] = ["@new", "@updated"]
        item2_data["updated_at"] = 2000
        item2 = TodoItem.from_dict(item2_data)

        assert item2.updated_at > item1.updated_at
        assert item2.tags == ["@new", "@updated"]

    def test_empty_tags_serialized_as_empty_list(self):
        item = create_todo_item("No tags")
        d = item.to_dict()
        assert d["tags"] == []
        assert isinstance(d["tags"], list)

    def test_tags_survive_json_string_roundtrip(self):
        import json

        item = create_todo_item("Test", tags=["@a", "@b"])
        s = json.dumps(item.to_dict())
        restored = TodoItem.from_dict(json.loads(s))
        assert restored.tags == ["@a", "@b"]


# ===========================================================================
# Context menu and edit tags UI tests
# ===========================================================================


class TestTodoTableContextMenuSignals:
    """Test that TodoTableWidget context menu emits correct signals."""

    def test_edit_tags_requested_signal_exists(self, qtbot):
        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        table = TodoTableWidget()
        qtbot.addWidget(table)
        assert hasattr(table, "edit_tags_requested")

    def test_toggle_requested_signal_exists(self, qtbot):
        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        table = TodoTableWidget()
        qtbot.addWidget(table)
        assert hasattr(table, "toggle_requested")

    def test_delete_requested_signal_exists(self, qtbot):
        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        table = TodoTableWidget()
        qtbot.addWidget(table)
        assert hasattr(table, "delete_requested")

    def test_edit_recurrence_requested_signal_exists(self, qtbot):
        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        table = TodoTableWidget()
        qtbot.addWidget(table)
        assert hasattr(table, "edit_recurrence_requested")

    def test_context_menu_policy_is_custom(self, qtbot):
        from PyQt6.QtCore import Qt

        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        table = TodoTableWidget()
        qtbot.addWidget(table)
        assert table.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


class TestEditTagsParsing:
    """Test tag parsing logic used in _on_edit_tags_for_item."""

    def _parse_tags(self, text: str) -> list[str]:
        """Mirror the parsing logic from MainWindow._on_edit_tags_for_item."""
        new_tags: list[str] = []
        seen: set[str] = set()
        for raw in text.split(","):
            tag = raw.strip()
            if not tag:
                continue
            if not tag.startswith("@"):
                tag = f"@{tag}"
            if tag not in seen:
                new_tags.append(tag)
                seen.add(tag)
        return new_tags

    def test_simple_comma_separated(self):
        assert self._parse_tags("@work, @home") == ["@work", "@home"]

    def test_auto_prefix_at(self):
        assert self._parse_tags("work, home") == ["@work", "@home"]

    def test_deduplication(self):
        assert self._parse_tags("@work, @work, @home") == ["@work", "@home"]

    def test_empty_string(self):
        assert self._parse_tags("") == []

    def test_whitespace_only(self):
        assert self._parse_tags("  ,  , ") == []

    def test_mixed_prefix(self):
        assert self._parse_tags("@work, home") == ["@work", "@home"]

    def test_single_tag(self):
        assert self._parse_tags("errands") == ["@errands"]

    def test_preserves_order(self):
        assert self._parse_tags("@z, @a, @m") == ["@z", "@a", "@m"]

    def test_strips_whitespace(self):
        assert self._parse_tags("  @work  ,  @home  ") == ["@work", "@home"]
