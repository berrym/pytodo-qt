"""Undo/redo commands for all mutation operations.

Each command captures the state needed to reverse an operation
and handles save/refresh on both redo() and undo().
All commands update timestamps via mark_updated() so that
sync LWW resolution works correctly after undo/redo.
"""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtGui import QUndoCommand

from ..core.models import TodoItem, TodoList

if TYPE_CHECKING:
    from .main_window import MainWindow


class AddItemCommand(QUndoCommand):
    """Add a todo item to a list."""

    def __init__(self, window: MainWindow, list_id: UUID, item: TodoItem) -> None:
        super().__init__("Add item")
        self._window = window
        self._list_id = list_id
        self._item = item

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        self._item.deleted = False
        self._item.mark_updated()
        todo_list.items[self._item.id] = self._item
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        todo_list.remove_item(self._item.id)
        self._window._save_database()
        self._window._refresh_ui()


class DeleteItemsCommand(QUndoCommand):
    """Delete one or more todo items (soft delete)."""

    def __init__(self, window: MainWindow, list_id: UUID, item_ids: list[UUID]) -> None:
        super().__init__(f"Delete {len(item_ids)} item(s)")
        self._window = window
        self._list_id = list_id
        self._item_ids = item_ids
        self._orphaned_children: list[tuple[UUID, UUID | None]] = []  # (child_id, old_parent_id)

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        deleted_ids = set(self._item_ids)
        # Find children that will be orphaned and promote them to top-level
        self._orphaned_children.clear()
        for item in todo_list.items.values():
            if not item.deleted and item.parent_id in deleted_ids and item.id not in deleted_ids:
                self._orphaned_children.append((item.id, item.parent_id))
                item.parent_id = None
                item.mark_updated()
        for item_id in self._item_ids:
            todo_list.remove_item(item_id)
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        # Restore orphaned children's parent_id
        for child_id, old_parent_id in self._orphaned_children:
            child = todo_list.items.get(child_id)
            if child:
                child.parent_id = old_parent_id
                child.mark_updated()
        for item_id in self._item_ids:
            item = todo_list.items.get(item_id)
            if item:
                item.deleted = False
                item.mark_updated()
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class ToggleCompleteCommand(QUndoCommand):
    """Toggle completion status of one or more items."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_states: list[tuple[UUID, bool]],
    ) -> None:
        super().__init__(f"Toggle {len(item_states)} item(s)")
        self._window = window
        self._list_id = list_id
        self._item_states = item_states

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        for item_id, _old_complete in self._item_states:
            item = todo_list.get_item(item_id)
            if item:
                item.toggle_complete()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        for item_id, old_complete in self._item_states:
            item = todo_list.get_item(item_id)
            if item:
                item.complete = old_complete
                item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class EditPriorityCommand(QUndoCommand):
    """Change an item's priority."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_priority: int,
        new_priority: int,
    ) -> None:
        super().__init__("Change priority")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_priority = old_priority
        self._new_priority = new_priority

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.priority = self._new_priority
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.priority = self._old_priority
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class EditReminderCommand(QUndoCommand):
    """Change an item's reminder text."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_reminder: str,
        new_reminder: str,
    ) -> None:
        super().__init__("Edit reminder")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_reminder = old_reminder
        self._new_reminder = new_reminder

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.reminder = self._new_reminder
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.reminder = self._old_reminder
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class EditDueDateCommand(QUndoCommand):
    """Change an item's due date."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_due_date: date | None,
        new_due_date: date | None,
        old_due_time: time | None = None,
    ) -> None:
        super().__init__("Change due date")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_due_date = old_due_date
        self._new_due_date = new_due_date
        self._old_due_time = old_due_time

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.due_date = self._new_due_date
            if self._new_due_date is None:
                item.due_time = None
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.due_date = self._old_due_date
            if self._old_due_date is None or self._old_due_time is not None:
                item.due_time = self._old_due_time
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class EditDueTimeCommand(QUndoCommand):
    """Change an item's due time."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_due_time: time | None,
        new_due_time: time | None,
    ) -> None:
        super().__init__("Change due time")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_due_time = old_due_time
        self._new_due_time = new_due_time

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.due_time = self._new_due_time
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.due_time = self._old_due_time
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class EditTagsCommand(QUndoCommand):
    """Change an item's tags."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_tags: list[str],
        new_tags: list[str],
    ) -> None:
        super().__init__("Edit tags")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_tags = list(old_tags)
        self._new_tags = list(new_tags)

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.tags = list(self._new_tags)
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.tags = list(self._old_tags)
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class ToggleCompleteRecurringCommand(QUndoCommand):
    """Complete a recurring item: advance due date and reset completion."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_due_date: date | None,
        new_due_date: date | None,
        old_count: int,
        recurrence_ended: bool,
    ) -> None:
        super().__init__("Complete recurring item")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_due_date = old_due_date
        self._new_due_date = new_due_date
        self._old_count = old_count
        self._ended = recurrence_ended

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if not item:
            return
        item.recurrence_count = self._old_count + 1
        if self._ended:
            item.complete = True
        else:
            item.complete = False
            item.due_date = self._new_due_date
        item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if not item:
            return
        item.complete = False
        item.due_date = self._old_due_date
        item.recurrence_count = self._old_count
        item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class EditRecurrenceCommand(QUndoCommand):
    """Change an item's recurrence settings."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_recurrence: tuple[str | None, int, date | None, int | None],
        new_recurrence: tuple[str | None, int, date | None, int | None],
    ) -> None:
        super().__init__("Edit recurrence")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old = old_recurrence
        self._new = new_recurrence

    def _apply(self, values: tuple[str | None, int, date | None, int | None]) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if not item:
            return
        item.recurrence_type = values[0]
        item.recurrence_interval = values[1]
        item.recurrence_end_date = values[2]
        item.recurrence_end_count = values[3]
        item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def redo(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)


class AddListCommand(QUndoCommand):
    """Add a new todo list."""

    def __init__(
        self, window: MainWindow, new_list: TodoList, prev_active_list_id: UUID | None
    ) -> None:
        super().__init__(f'Add list "{new_list.name}"')
        self._window = window
        self._new_list = new_list
        self._prev_active_list_id = prev_active_list_id

    def redo(self) -> None:
        self._new_list.deleted = False
        self._new_list.mark_updated()
        self._window._database.lists[self._new_list.id] = self._new_list
        self._window._database.set_active_list(self._new_list.id)
        self._window._config.database.active_list = self._new_list.name
        self._window._config_manager.save()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        self._new_list.mark_deleted()
        if self._prev_active_list_id:
            self._window._database.set_active_list(self._prev_active_list_id)
            prev_list = self._window._database.get_list(self._prev_active_list_id)
            if prev_list:
                self._window._config.database.active_list = prev_list.name
        else:
            self._window._database.active_list_id = None
            self._window._config.database.active_list = ""
        self._window._config_manager.save()
        self._window._save_database()
        self._window._refresh_ui()


class DeleteListCommand(QUndoCommand):
    """Delete a todo list (soft delete)."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        list_name: str,
        new_active_list_id: UUID | None,
    ) -> None:
        super().__init__(f'Delete list "{list_name}"')
        self._window = window
        self._list_id = list_id
        self._list_name = list_name
        self._new_active_list_id = new_active_list_id

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        todo_list.mark_deleted()
        if self._new_active_list_id:
            self._window._database.set_active_list(self._new_active_list_id)
        else:
            self._window._database.active_list_id = None
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        todo_list.deleted = False
        todo_list.mark_updated()
        self._window._database.set_active_list(self._list_id)
        self._window._config.database.active_list = self._list_name
        self._window._config_manager.save()
        self._window._save_database()
        self._window._refresh_ui()


class RenameListCommand(QUndoCommand):
    """Rename a todo list."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        old_name: str,
        new_name: str,
    ) -> None:
        super().__init__(f'Rename list to "{new_name}"')
        self._window = window
        self._list_id = list_id
        self._old_name = old_name
        self._new_name = new_name

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        todo_list.name = self._new_name
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        todo_list.name = self._old_name
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class ReparentCommand(QUndoCommand):
    """Change an item's parent (move between top-level and subtask)."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_parent_id: UUID | None,
        new_parent_id: UUID | None,
    ) -> None:
        super().__init__("Reparent item")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_parent_id = old_parent_id
        self._new_parent_id = new_parent_id

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.parent_id = self._new_parent_id
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.parent_id = self._old_parent_id
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class EditTimeSpentCommand(QUndoCommand):
    """Add focus session time to an item (undo-able)."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_time_spent: int,
        seconds_to_add: int,
    ) -> None:
        super().__init__("Focus session")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_time_spent = old_time_spent
        self._new_time_spent = old_time_spent + seconds_to_add

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.time_spent = self._new_time_spent
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.time_spent = self._old_time_spent
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class TogglePrivateCommand(QUndoCommand):
    """Toggle a list's private/shared status."""

    def __init__(self, window: MainWindow, list_id: UUID, was_private: bool) -> None:
        super().__init__("Toggle list private")
        self._window = window
        self._list_id = list_id
        self._was_private = was_private

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        todo_list.private = not self._was_private
        todo_list.mark_updated()
        status = "private (won't sync)" if todo_list.private else "shared"
        self._window.status_bar_widget.show_message(
            f'List "{todo_list.name}" is now {status}', 3000
        )
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        todo_list.private = self._was_private
        todo_list.mark_updated()
        status = "private (won't sync)" if todo_list.private else "shared"
        self._window.status_bar_widget.show_message(
            f'List "{todo_list.name}" is now {status}', 3000
        )
        self._window._save_database()
        self._window._refresh_ui()
