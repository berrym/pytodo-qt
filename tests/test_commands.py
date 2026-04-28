"""Comprehensive tests for undo/redo command classes.

Tests each QUndoCommand subclass in isolation using a mock MainWindow,
verifying that redo() and undo() correctly mutate state, update timestamps,
and handle edge cases like missing items/lists gracefully.
"""

from __future__ import annotations

import time
from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from PyQt6.QtGui import QUndoStack

from pytodo_qt.core.models import (
    Database,
    TodoItem,
    TodoList,
    create_todo_item,
    create_todo_list,
)
from pytodo_qt.gui.commands import (
    AddItemCommand,
    AddListCommand,
    DeleteItemsCommand,
    DeleteListCommand,
    EditDueDateCommand,
    EditEstimatedMinutesCommand,
    EditPriorityCommand,
    EditReminderCommand,
    RenameListCommand,
    ToggleCompleteCommand,
    TogglePrivateCommand,
)


class FakeConfigManager:
    """Minimal stand-in for ConfigManager."""

    def save(self):
        pass


class FakeConfig:
    """Minimal stand-in for AppConfig."""

    class database:
        active_list = ""


def make_window(db: Database | None = None) -> MagicMock:
    """Create a mock MainWindow with a real Database."""
    window = MagicMock()
    window._database = db or Database()
    window._save_database = MagicMock()
    window._refresh_ui = MagicMock()
    window._config = FakeConfig()
    window._config_manager = FakeConfigManager()
    window.status_bar_widget = MagicMock()
    return window


def make_populated_db() -> tuple[Database, TodoList, TodoItem, TodoItem]:
    """Create a database with one list containing two items."""
    db = Database()
    lst = create_todo_list("Test List")
    item1 = create_todo_item("Buy milk", priority=2)
    item2 = create_todo_item("Write tests", priority=1)
    lst.add_item(item1)
    lst.add_item(item2)
    db.add_list(lst)
    db.set_active_list(lst.id)
    return db, lst, item1, item2


# ---------------------------------------------------------------------------
# AddItemCommand
# ---------------------------------------------------------------------------
class TestAddItemCommand:
    def test_redo_adds_item(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        new_item = create_todo_item("New task")
        cmd = AddItemCommand(window, lst.id, new_item)

        cmd.redo()

        assert new_item.id in lst.items
        assert lst.items[new_item.id].deleted is False
        window._save_database.assert_called()
        window._refresh_ui.assert_called()

    def test_undo_removes_item(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        new_item = create_todo_item("New task")
        cmd = AddItemCommand(window, lst.id, new_item)

        cmd.redo()
        assert new_item.id in lst.items

        cmd.undo()
        assert lst.items[new_item.id].deleted is True

    def test_redo_after_undo_restores_item(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        new_item = create_todo_item("New task")
        cmd = AddItemCommand(window, lst.id, new_item)

        cmd.redo()
        cmd.undo()
        cmd.redo()

        assert lst.items[new_item.id].deleted is False

    def test_redo_marks_updated(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        new_item = create_todo_item("New task")
        original_ts = new_item.updated_at
        time.sleep(0.002)

        cmd = AddItemCommand(window, lst.id, new_item)
        cmd.redo()

        assert new_item.updated_at >= original_ts

    def test_redo_noop_if_list_missing(self):
        db = Database()
        window = make_window(db)
        new_item = create_todo_item("Orphan")
        cmd = AddItemCommand(window, uuid4(), new_item)

        cmd.redo()  # Should not raise
        window._save_database.assert_not_called()

    def test_undo_noop_if_list_missing(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        new_item = create_todo_item("New task")
        cmd = AddItemCommand(window, lst.id, new_item)
        cmd.redo()

        # Remove the list from database
        del db.lists[lst.id]
        cmd.undo()  # Should not raise

    def test_text(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = AddItemCommand(window, lst.id, create_todo_item("x"))
        assert cmd.text() == "Add item"


# ---------------------------------------------------------------------------
# DeleteItemsCommand
# ---------------------------------------------------------------------------
class TestDeleteItemsCommand:
    def test_redo_soft_deletes_items(self):
        db, lst, item1, item2 = make_populated_db()
        window = make_window(db)
        cmd = DeleteItemsCommand(window, lst.id, [item1.id, item2.id])

        cmd.redo()

        assert lst.items[item1.id].deleted is True
        assert lst.items[item2.id].deleted is True

    def test_undo_restores_items(self):
        db, lst, item1, item2 = make_populated_db()
        window = make_window(db)
        cmd = DeleteItemsCommand(window, lst.id, [item1.id, item2.id])

        cmd.redo()
        cmd.undo()

        assert lst.items[item1.id].deleted is False
        assert lst.items[item2.id].deleted is False

    def test_undo_marks_updated(self):
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        cmd = DeleteItemsCommand(window, lst.id, [item1.id])

        cmd.redo()
        ts_after_delete = item1.updated_at
        time.sleep(0.002)
        cmd.undo()

        assert item1.updated_at >= ts_after_delete

    def test_single_item_delete(self):
        db, lst, item1, item2 = make_populated_db()
        window = make_window(db)
        cmd = DeleteItemsCommand(window, lst.id, [item1.id])

        cmd.redo()

        assert lst.items[item1.id].deleted is True
        assert lst.items[item2.id].deleted is False

    def test_noop_if_list_missing(self):
        db = Database()
        window = make_window(db)
        cmd = DeleteItemsCommand(window, uuid4(), [uuid4()])

        cmd.redo()  # Should not raise
        cmd.undo()  # Should not raise

    def test_text_reflects_count(self):
        db, lst, item1, item2 = make_populated_db()
        window = make_window(db)
        cmd = DeleteItemsCommand(window, lst.id, [item1.id, item2.id])
        assert cmd.text() == "Delete 2 item(s)"

        cmd2 = DeleteItemsCommand(window, lst.id, [item1.id])
        assert cmd2.text() == "Delete 1 item(s)"


# ---------------------------------------------------------------------------
# ToggleCompleteCommand
# ---------------------------------------------------------------------------
class TestToggleCompleteCommand:
    def test_redo_toggles_completion(self):
        db, lst, item1, item2 = make_populated_db()
        window = make_window(db)
        states = [(item1.id, False), (item2.id, False)]
        cmd = ToggleCompleteCommand(window, lst.id, states)

        cmd.redo()

        assert item1.complete is True
        assert item2.complete is True

    def test_undo_restores_original_state(self):
        db, lst, item1, item2 = make_populated_db()
        item1.complete = True  # Mixed states
        window = make_window(db)
        states = [(item1.id, True), (item2.id, False)]
        cmd = ToggleCompleteCommand(window, lst.id, states)

        cmd.redo()
        assert item1.complete is False  # Was True, toggled to False
        assert item2.complete is True  # Was False, toggled to True

        cmd.undo()
        assert item1.complete is True  # Restored
        assert item2.complete is False  # Restored

    def test_undo_marks_updated(self):
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        states = [(item1.id, False)]
        cmd = ToggleCompleteCommand(window, lst.id, states)

        cmd.redo()
        ts = item1.updated_at
        time.sleep(0.002)
        cmd.undo()

        assert item1.updated_at >= ts

    def test_noop_if_list_missing(self):
        db = Database()
        window = make_window(db)
        cmd = ToggleCompleteCommand(window, uuid4(), [(uuid4(), False)])
        cmd.redo()
        cmd.undo()

    def test_text_reflects_count(self):
        db, lst, item1, item2 = make_populated_db()
        window = make_window(db)
        cmd = ToggleCompleteCommand(window, lst.id, [(item1.id, False), (item2.id, False)])
        assert cmd.text() == "Toggle 2 item(s)"

    def test_redo_writes_completed_at(self):
        """Toggling an incomplete item to complete writes completed_at."""
        db, lst, item1, _ = make_populated_db()
        assert item1.completed_at is None
        window = make_window(db)
        cmd = ToggleCompleteCommand(window, lst.id, [(item1.id, False)])

        cmd.redo()

        assert item1.complete is True
        assert item1.completed_at is not None
        assert item1.completed_at > 0

    def test_undo_restores_completed_at_to_none(self):
        """Undoing a complete-from-incomplete restores completed_at to None."""
        db, lst, item1, _ = make_populated_db()
        assert item1.completed_at is None
        window = make_window(db)
        cmd = ToggleCompleteCommand(window, lst.id, [(item1.id, False)])

        cmd.redo()
        assert item1.completed_at is not None
        cmd.undo()
        assert item1.complete is False
        assert item1.completed_at is None

    def test_undo_restores_existing_completed_at(self):
        """Undoing an uncomplete-from-complete restores the original timestamp."""
        db, lst, item1, _ = make_populated_db()
        original_ts = 1_700_000_000_000
        item1.complete = True
        item1.completed_at = original_ts
        window = make_window(db)
        cmd = ToggleCompleteCommand(window, lst.id, [(item1.id, True)])

        cmd.redo()
        assert item1.complete is False
        assert item1.completed_at is None  # cleared by toggle

        cmd.undo()
        assert item1.complete is True
        assert item1.completed_at == original_ts  # exact original preserved


# ---------------------------------------------------------------------------
# EditPriorityCommand
# ---------------------------------------------------------------------------
class TestEditPriorityCommand:
    def test_redo_changes_priority(self):
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        cmd = EditPriorityCommand(window, lst.id, item1.id, 2, 1)

        cmd.redo()

        assert item1.priority == 1

    def test_undo_restores_priority(self):
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        cmd = EditPriorityCommand(window, lst.id, item1.id, 2, 1)

        cmd.redo()
        cmd.undo()

        assert item1.priority == 2

    def test_redo_undo_marks_updated(self):
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        cmd = EditPriorityCommand(window, lst.id, item1.id, 2, 3)

        ts_before = item1.updated_at
        time.sleep(0.002)
        cmd.redo()
        assert item1.updated_at >= ts_before

        ts_after_redo = item1.updated_at
        time.sleep(0.002)
        cmd.undo()
        assert item1.updated_at >= ts_after_redo

    def test_noop_if_item_missing(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = EditPriorityCommand(window, lst.id, uuid4(), 2, 1)

        cmd.redo()  # Should not raise
        cmd.undo()  # Should not raise

    def test_all_priority_levels(self):
        """Test transitions between all priority levels."""
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)

        for old, new in [(1, 2), (2, 3), (3, 1), (1, 3), (3, 2), (2, 1)]:
            item1.priority = old
            cmd = EditPriorityCommand(window, lst.id, item1.id, old, new)
            cmd.redo()
            assert item1.priority == new
            cmd.undo()
            assert item1.priority == old


# ---------------------------------------------------------------------------
# EditReminderCommand
# ---------------------------------------------------------------------------
class TestEditReminderCommand:
    def test_redo_changes_reminder(self):
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        cmd = EditReminderCommand(window, lst.id, item1.id, "Buy milk", "Buy eggs")

        cmd.redo()

        assert item1.reminder == "Buy eggs"

    def test_undo_restores_reminder(self):
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        cmd = EditReminderCommand(window, lst.id, item1.id, "Buy milk", "Buy eggs")

        cmd.redo()
        cmd.undo()

        assert item1.reminder == "Buy milk"

    def test_empty_reminder(self):
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        cmd = EditReminderCommand(window, lst.id, item1.id, "Buy milk", "")

        cmd.redo()
        assert item1.reminder == ""

        cmd.undo()
        assert item1.reminder == "Buy milk"

    def test_noop_if_item_missing(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = EditReminderCommand(window, lst.id, uuid4(), "old", "new")
        cmd.redo()
        cmd.undo()


# ---------------------------------------------------------------------------
# EditDueDateCommand
# ---------------------------------------------------------------------------
class TestEditDueDateCommand:
    def test_redo_sets_due_date(self):
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        new_date = date(2026, 3, 15)
        cmd = EditDueDateCommand(window, lst.id, item1.id, None, new_date)

        cmd.redo()

        assert item1.due_date == new_date

    def test_undo_restores_due_date(self):
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        new_date = date(2026, 3, 15)
        cmd = EditDueDateCommand(window, lst.id, item1.id, None, new_date)

        cmd.redo()
        cmd.undo()

        assert item1.due_date is None

    def test_clear_due_date(self):
        db, lst, item1, _ = make_populated_db()
        old_date = date(2026, 1, 1)
        item1.due_date = old_date
        window = make_window(db)
        cmd = EditDueDateCommand(window, lst.id, item1.id, old_date, None)

        cmd.redo()
        assert item1.due_date is None

        cmd.undo()
        assert item1.due_date == old_date

    def test_change_due_date(self):
        db, lst, item1, _ = make_populated_db()
        old_date = date(2026, 1, 1)
        new_date = date(2026, 6, 30)
        item1.due_date = old_date
        window = make_window(db)
        cmd = EditDueDateCommand(window, lst.id, item1.id, old_date, new_date)

        cmd.redo()
        assert item1.due_date == new_date

        cmd.undo()
        assert item1.due_date == old_date

    def test_noop_if_item_missing(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = EditDueDateCommand(window, lst.id, uuid4(), None, date.today())
        cmd.redo()
        cmd.undo()


# ---------------------------------------------------------------------------
# AddListCommand
# ---------------------------------------------------------------------------
class TestAddListCommand:
    def test_redo_adds_list(self):
        db = Database()
        window = make_window(db)
        new_list = create_todo_list("Shopping")
        cmd = AddListCommand(window, new_list, None)

        cmd.redo()

        assert new_list.id in db.lists
        assert db.active_list_id == new_list.id
        assert new_list.deleted is False
        window._save_database.assert_called()

    def test_undo_removes_list(self):
        db = Database()
        window = make_window(db)
        new_list = create_todo_list("Shopping")
        cmd = AddListCommand(window, new_list, None)

        cmd.redo()
        cmd.undo()

        assert db.lists[new_list.id].deleted is True
        assert db.active_list_id is None

    def test_undo_restores_previous_active_list(self):
        db = Database()
        prev_list = create_todo_list("Previous")
        db.add_list(prev_list)
        db.set_active_list(prev_list.id)
        window = make_window(db)

        new_list = create_todo_list("New")
        cmd = AddListCommand(window, new_list, prev_list.id)

        cmd.redo()
        assert db.active_list_id == new_list.id

        cmd.undo()
        assert db.active_list_id == prev_list.id

    def test_redo_updates_config(self):
        db = Database()
        window = make_window(db)
        new_list = create_todo_list("Shopping")
        cmd = AddListCommand(window, new_list, None)

        cmd.redo()

        assert window._config.database.active_list == "Shopping"

    def test_undo_clears_config_when_no_prev(self):
        db = Database()
        window = make_window(db)
        new_list = create_todo_list("Shopping")
        cmd = AddListCommand(window, new_list, None)

        cmd.redo()
        cmd.undo()

        assert window._config.database.active_list == ""

    def test_redo_after_undo_restores_list(self):
        db = Database()
        window = make_window(db)
        new_list = create_todo_list("Shopping")
        cmd = AddListCommand(window, new_list, None)

        cmd.redo()
        cmd.undo()
        cmd.redo()

        assert new_list.deleted is False
        assert db.active_list_id == new_list.id


# ---------------------------------------------------------------------------
# DeleteListCommand
# ---------------------------------------------------------------------------
class TestDeleteListCommand:
    def test_redo_soft_deletes_list(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = DeleteListCommand(window, lst.id, lst.name, None)

        cmd.redo()

        assert lst.deleted is True
        assert db.active_list_id is None

    def test_undo_restores_list(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = DeleteListCommand(window, lst.id, lst.name, None)

        cmd.redo()
        cmd.undo()

        assert lst.deleted is False
        assert db.active_list_id == lst.id

    def test_redo_switches_to_new_active(self):
        db = Database()
        lst1 = create_todo_list("List 1")
        lst2 = create_todo_list("List 2")
        db.add_list(lst1)
        db.add_list(lst2)
        db.set_active_list(lst1.id)
        window = make_window(db)

        cmd = DeleteListCommand(window, lst1.id, lst1.name, lst2.id)
        cmd.redo()

        assert lst1.deleted is True
        assert db.active_list_id == lst2.id

    def test_undo_restores_config(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = DeleteListCommand(window, lst.id, lst.name, None)

        cmd.redo()
        cmd.undo()

        assert window._config.database.active_list == lst.name

    def test_noop_if_list_missing(self):
        db = Database()
        window = make_window(db)
        cmd = DeleteListCommand(window, uuid4(), "Ghost", None)
        cmd.redo()
        cmd.undo()

    def test_undo_marks_updated(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = DeleteListCommand(window, lst.id, lst.name, None)

        cmd.redo()
        ts = lst.updated_at
        time.sleep(0.002)
        cmd.undo()

        assert lst.updated_at >= ts


# ---------------------------------------------------------------------------
# RenameListCommand
# ---------------------------------------------------------------------------
class TestRenameListCommand:
    def test_redo_renames_list(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = RenameListCommand(window, lst.id, "Test List", "Renamed List")

        cmd.redo()

        assert lst.name == "Renamed List"

    def test_undo_restores_name(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = RenameListCommand(window, lst.id, "Test List", "Renamed List")

        cmd.redo()
        cmd.undo()

        assert lst.name == "Test List"

    def test_marks_updated(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = RenameListCommand(window, lst.id, "Test List", "New Name")

        ts_before = lst.updated_at
        time.sleep(0.002)
        cmd.redo()
        assert lst.updated_at >= ts_before

        ts_after_redo = lst.updated_at
        time.sleep(0.002)
        cmd.undo()
        assert lst.updated_at >= ts_after_redo

    def test_noop_if_list_missing(self):
        db = Database()
        window = make_window(db)
        cmd = RenameListCommand(window, uuid4(), "Old", "New")
        cmd.redo()
        cmd.undo()

    def test_text(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = RenameListCommand(window, lst.id, "Old", "New Name")
        assert cmd.text() == 'Rename list to "New Name"'


# ---------------------------------------------------------------------------
# TogglePrivateCommand
# ---------------------------------------------------------------------------
class TestTogglePrivateCommand:
    def test_redo_toggles_private(self):
        db, lst, _, _ = make_populated_db()
        assert lst.private is False
        window = make_window(db)
        cmd = TogglePrivateCommand(window, lst.id, False)

        cmd.redo()

        assert lst.private is True

    def test_undo_restores_private(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = TogglePrivateCommand(window, lst.id, False)

        cmd.redo()
        cmd.undo()

        assert lst.private is False

    def test_toggle_from_private_to_shared(self):
        db, lst, _, _ = make_populated_db()
        lst.private = True
        window = make_window(db)
        cmd = TogglePrivateCommand(window, lst.id, True)

        cmd.redo()
        assert lst.private is False

        cmd.undo()
        assert lst.private is True

    def test_shows_status_message(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = TogglePrivateCommand(window, lst.id, False)

        cmd.redo()
        window.status_bar_widget.show_message.assert_called()

    def test_noop_if_list_missing(self):
        db = Database()
        window = make_window(db)
        cmd = TogglePrivateCommand(window, uuid4(), False)
        cmd.redo()
        cmd.undo()


# ---------------------------------------------------------------------------
# QUndoStack integration
# ---------------------------------------------------------------------------
class TestUndoStackIntegration:
    """Test commands work correctly with a real QUndoStack."""

    def test_push_calls_redo(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        stack = QUndoStack()
        new_item = create_todo_item("Stacked task")
        cmd = AddItemCommand(window, lst.id, new_item)

        stack.push(cmd)

        assert new_item.id in lst.items
        assert stack.canUndo() is True
        assert stack.canRedo() is False

    def test_undo_via_stack(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        stack = QUndoStack()
        new_item = create_todo_item("Stacked task")
        cmd = AddItemCommand(window, lst.id, new_item)

        stack.push(cmd)
        stack.undo()

        assert lst.items[new_item.id].deleted is True
        assert stack.canUndo() is False
        assert stack.canRedo() is True

    def test_redo_via_stack(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        stack = QUndoStack()
        new_item = create_todo_item("Stacked task")
        cmd = AddItemCommand(window, lst.id, new_item)

        stack.push(cmd)
        stack.undo()
        stack.redo()

        assert lst.items[new_item.id].deleted is False

    def test_multiple_commands_undo_order(self):
        """Verify LIFO undo ordering across command types."""
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        stack = QUndoStack()

        # 1. Add an item
        new_item = create_todo_item("Third task")
        stack.push(AddItemCommand(window, lst.id, new_item))

        # 2. Change priority on existing item
        stack.push(EditPriorityCommand(window, lst.id, item1.id, 2, 1))

        # 3. Toggle complete
        stack.push(ToggleCompleteCommand(window, lst.id, [(item1.id, False)]))

        assert item1.complete is True
        assert item1.priority == 1
        assert new_item.id in lst.items

        # Undo #3: toggle
        stack.undo()
        assert item1.complete is False

        # Undo #2: priority
        stack.undo()
        assert item1.priority == 2

        # Undo #1: add item
        stack.undo()
        assert lst.items[new_item.id].deleted is True

    def test_undo_limit(self):
        """Verify undo limit truncates old commands."""
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        stack = QUndoStack()
        stack.setUndoLimit(3)

        items = []
        for i in range(5):
            item = create_todo_item(f"Task {i}")
            stack.push(AddItemCommand(window, lst.id, item))
            items.append(item)

        # Only last 3 should be undoable
        assert stack.count() == 3

        stack.undo()
        stack.undo()
        stack.undo()
        assert stack.canUndo() is False

    def test_push_after_undo_clears_redo(self):
        """Pushing a new command after undo clears the redo stack."""
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        stack = QUndoStack()

        stack.push(EditPriorityCommand(window, lst.id, item1.id, 2, 1))
        stack.push(EditPriorityCommand(window, lst.id, item1.id, 1, 3))

        stack.undo()  # Back to priority 1
        assert item1.priority == 1
        assert stack.canRedo() is True

        # Push a different command — redo stack should be cleared
        stack.push(EditReminderCommand(window, lst.id, item1.id, "Buy milk", "Buy eggs"))
        assert stack.canRedo() is False

    def test_clean_state_tracking(self):
        """QUndoStack tracks clean state correctly."""
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        stack = QUndoStack()

        stack.setClean()
        assert stack.isClean() is True

        stack.push(EditPriorityCommand(window, lst.id, item1.id, 2, 1))
        assert stack.isClean() is False

        stack.undo()
        assert stack.isClean() is True

    def test_undo_text_updates(self):
        """QUndoStack actions have correct descriptive text."""
        db, lst, item1, item2 = make_populated_db()
        window = make_window(db)
        stack = QUndoStack()

        stack.push(AddItemCommand(window, lst.id, create_todo_item("x")))
        assert stack.undoText() == "Add item"

        stack.push(DeleteItemsCommand(window, lst.id, [item1.id, item2.id]))
        assert stack.undoText() == "Delete 2 item(s)"

        stack.undo()
        assert stack.redoText() == "Delete 2 item(s)"
        assert stack.undoText() == "Add item"


# ---------------------------------------------------------------------------
# Edge cases and robustness
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_delete_then_undo_preserves_item_data(self):
        """Undo delete should preserve all original item fields."""
        db, lst, item1, _ = make_populated_db()
        item1.priority = 1
        item1.reminder = "Important task"
        item1.due_date = date(2026, 12, 25)
        item1.complete = True
        window = make_window(db)

        cmd = DeleteItemsCommand(window, lst.id, [item1.id])
        cmd.redo()
        cmd.undo()

        restored = lst.items[item1.id]
        assert restored.deleted is False
        assert restored.priority == 1
        assert restored.reminder == "Important task"
        assert restored.due_date == date(2026, 12, 25)
        assert restored.complete is True

    def test_add_list_delete_list_roundtrip(self):
        """Add list then delete list, undo both."""
        db = Database()
        window = make_window(db)
        stack = QUndoStack()

        new_list = create_todo_list("Groceries")
        stack.push(AddListCommand(window, new_list, None))
        assert len(list(db.active_lists())) == 1

        stack.push(DeleteListCommand(window, new_list.id, "Groceries", None))
        assert len(list(db.active_lists())) == 0

        # Undo delete
        stack.undo()
        assert len(list(db.active_lists())) == 1
        assert new_list.deleted is False

        # Undo add
        stack.undo()
        assert len(list(db.active_lists())) == 0
        assert new_list.deleted is True

    def test_rename_then_delete_then_undo_both(self):
        """Rename + delete, then undo both — name should be restored."""
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        stack = QUndoStack()

        stack.push(RenameListCommand(window, lst.id, "Test List", "Renamed"))
        assert lst.name == "Renamed"

        stack.push(DeleteListCommand(window, lst.id, "Renamed", None))
        assert lst.deleted is True

        stack.undo()  # Undo delete
        assert lst.deleted is False

        stack.undo()  # Undo rename
        assert lst.name == "Test List"

    def test_toggle_complete_mixed_states(self):
        """Toggle items with different initial states, verify exact restoration."""
        db, lst, item1, item2 = make_populated_db()
        item1.complete = True
        item2.complete = False
        window = make_window(db)

        states = [(item1.id, True), (item2.id, False)]
        cmd = ToggleCompleteCommand(window, lst.id, states)

        cmd.redo()
        assert item1.complete is False
        assert item2.complete is True

        cmd.undo()
        assert item1.complete is True
        assert item2.complete is False

    def test_all_item_commands_call_save_and_refresh(self):
        """Every command calls _save_database and _refresh_ui on both redo and undo."""
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)

        commands = [
            AddItemCommand(window, lst.id, create_todo_item("x")),
            DeleteItemsCommand(window, lst.id, [item1.id]),
            ToggleCompleteCommand(window, lst.id, [(item1.id, False)]),
            EditPriorityCommand(window, lst.id, item1.id, 2, 1),
            EditReminderCommand(window, lst.id, item1.id, "Buy milk", "New"),
            EditDueDateCommand(window, lst.id, item1.id, None, date.today()),
        ]

        for cmd in commands:
            window._save_database.reset_mock()
            window._refresh_ui.reset_mock()

            cmd.redo()
            assert window._save_database.called, f"{type(cmd).__name__}.redo() missing save"
            assert window._refresh_ui.called, f"{type(cmd).__name__}.redo() missing refresh"

            window._save_database.reset_mock()
            window._refresh_ui.reset_mock()

            cmd.undo()
            assert window._save_database.called, f"{type(cmd).__name__}.undo() missing save"
            assert window._refresh_ui.called, f"{type(cmd).__name__}.undo() missing refresh"

    def test_all_list_commands_call_save_and_refresh(self):
        """Every list command calls _save_database and _refresh_ui on both redo and undo."""
        db, lst, _, _ = make_populated_db()
        window = make_window(db)

        commands = [
            AddListCommand(window, create_todo_list("New"), lst.id),
            DeleteListCommand(window, lst.id, lst.name, None),
            RenameListCommand(window, lst.id, "Test List", "New Name"),
            TogglePrivateCommand(window, lst.id, False),
        ]

        for cmd in commands:
            window._save_database.reset_mock()
            window._refresh_ui.reset_mock()

            cmd.redo()
            assert window._save_database.called, f"{type(cmd).__name__}.redo() missing save"
            assert window._refresh_ui.called, f"{type(cmd).__name__}.redo() missing refresh"

            window._save_database.reset_mock()
            window._refresh_ui.reset_mock()

            cmd.undo()
            assert window._save_database.called, f"{type(cmd).__name__}.undo() missing save"
            assert window._refresh_ui.called, f"{type(cmd).__name__}.undo() missing refresh"

    def test_timestamps_always_advance_on_undo(self):
        """Undo must call mark_updated() to win LWW resolution after sync."""
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)

        # Edit priority and undo — timestamp must advance
        cmd = EditPriorityCommand(window, lst.id, item1.id, 2, 1)
        cmd.redo()
        ts_after_redo = item1.updated_at
        time.sleep(0.002)
        cmd.undo()
        assert item1.updated_at > ts_after_redo

    def test_rapid_undo_redo_cycle(self):
        """Stress test: rapid undo/redo cycles don't corrupt state."""
        db, lst, item1, _ = make_populated_db()
        window = make_window(db)
        stack = QUndoStack()

        stack.push(EditPriorityCommand(window, lst.id, item1.id, 2, 1))
        stack.push(EditReminderCommand(window, lst.id, item1.id, "Buy milk", "Updated"))
        stack.push(ToggleCompleteCommand(window, lst.id, [(item1.id, False)]))

        for _ in range(10):
            while stack.canUndo():
                stack.undo()
            while stack.canRedo():
                stack.redo()

        # After full redo cycle, state should match final operations
        assert item1.priority == 1
        assert item1.reminder == "Updated"
        assert item1.complete is True

        # After full undo cycle, state should match original
        while stack.canUndo():
            stack.undo()
        assert item1.priority == 2
        assert item1.reminder == "Buy milk"
        assert item1.complete is False


class TestEditEstimatedMinutesCommand:
    def test_redo_changes_estimate(self):
        db, lst, item1, _ = make_populated_db()
        item1.estimated_minutes = 30
        window = make_window(db)
        cmd = EditEstimatedMinutesCommand(window, lst.id, item1.id, 30, 60)

        cmd.redo()

        assert item1.estimated_minutes == 60

    def test_undo_restores_estimate(self):
        db, lst, item1, _ = make_populated_db()
        item1.estimated_minutes = 30
        window = make_window(db)
        cmd = EditEstimatedMinutesCommand(window, lst.id, item1.id, 30, 60)

        cmd.redo()
        cmd.undo()

        assert item1.estimated_minutes == 30

    def test_redo_undo_marks_updated(self):
        db, lst, item1, _ = make_populated_db()
        item1.estimated_minutes = 0
        window = make_window(db)
        cmd = EditEstimatedMinutesCommand(window, lst.id, item1.id, 0, 90)

        ts_before = item1.updated_at
        time.sleep(0.002)
        cmd.redo()
        assert item1.updated_at >= ts_before

        ts_after_redo = item1.updated_at
        time.sleep(0.002)
        cmd.undo()
        assert item1.updated_at >= ts_after_redo

    def test_zero_estimate_is_valid(self):
        # Resizing a deadline-with-estimate bar back to a deadline-only
        # bar collapses estimated_minutes to 0; the command must handle
        # that without coercion.
        db, lst, item1, _ = make_populated_db()
        item1.estimated_minutes = 45
        window = make_window(db)
        cmd = EditEstimatedMinutesCommand(window, lst.id, item1.id, 45, 0)

        cmd.redo()
        assert item1.estimated_minutes == 0
        cmd.undo()
        assert item1.estimated_minutes == 45

    def test_noop_if_item_missing(self):
        db, lst, _, _ = make_populated_db()
        window = make_window(db)
        cmd = EditEstimatedMinutesCommand(window, lst.id, uuid4(), 30, 60)

        cmd.redo()  # Should not raise
        cmd.undo()  # Should not raise
