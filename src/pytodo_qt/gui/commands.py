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


def _best_incomplete_column(item: TodoItem, todo_list: TodoList) -> str:
    """Return the best column for an incomplete item based on work indicators.

    Items with pomodoro time or completed subtasks go to the "In Progress"
    column since they clearly have work done. Searches by name first (handles
    Backlog preset where In Progress is col 3), falls back to second column
    for custom layouts. Items without work indicators go to inbox (first col).
    """
    cols = todo_list.board_columns
    if not cols:
        return ""
    first_col = cols[0]
    if len(cols) < 3:
        # With only 2 columns (inbox + done), no meaningful progress column
        return first_col
    # Prefer "In Progress" by name (works across all presets), else second col
    progress_col = next((c for c in cols[1:-1] if c == "In Progress"), cols[1])

    # Check for pomodoro work
    if item.time_spent > 0:
        return progress_col

    # Check for completed subtasks
    for child in todo_list.items.values():
        if child.parent_id == item.id and not child.deleted and child.complete:
            return progress_col

    return first_col


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
        # (child_id, old_parent_id, old_board_column)
        self._orphaned_children: list[tuple[UUID, UUID | None, str]] = []

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        deleted_ids = set(self._item_ids)
        first_col = todo_list.board_columns[0] if todo_list.board_columns else ""
        # Find children that will be orphaned and promote them to top-level
        self._orphaned_children.clear()
        for item in todo_list.items.values():
            if not item.deleted and item.parent_id in deleted_ids and item.id not in deleted_ids:
                self._orphaned_children.append((item.id, item.parent_id, item.board_column))
                item.parent_id = None
                # Assign board column for newly top-level items
                if not item.board_column and first_col:
                    item.board_column = first_col
                item.mark_updated()
        for item_id in self._item_ids:
            todo_list.remove_item(item_id)
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        # Restore orphaned children's parent_id and board_column
        for child_id, old_parent_id, old_board_column in self._orphaned_children:
            child = todo_list.items.get(child_id)
            if child:
                child.parent_id = old_parent_id
                child.board_column = old_board_column
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
        self._old_board_columns: dict[UUID, str] = {}

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        cols = todo_list.board_columns
        last_col = cols[-1] if cols else ""
        for item_id, _old_complete in self._item_states:
            item = todo_list.get_item(item_id)
            if item:
                self._old_board_columns[item_id] = item.board_column
                item.toggle_complete()
                # Sync board_column with new completion state
                if item.complete and last_col and item.board_column != last_col:
                    item.board_column = last_col
                elif not item.complete and item.board_column == last_col:
                    item.board_column = _best_incomplete_column(item, todo_list)
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
                if item_id in self._old_board_columns:
                    item.board_column = self._old_board_columns[item_id]
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
        self._old_board_column: str = ""

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if not item:
            return
        self._old_board_column = item.board_column
        item.recurrence_count = self._old_count + 1
        cols = todo_list.board_columns
        last_col = cols[-1] if cols else ""
        if self._ended:
            item.complete = True
            # Exhausted recurrence → move to completion column
            if last_col and item.board_column != last_col:
                item.board_column = last_col
        else:
            item.complete = False
            item.due_date = self._new_due_date
            # Recurrence advance → place based on work indicators
            if item.board_column == last_col:
                item.board_column = _best_incomplete_column(item, todo_list)
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
        item.board_column = self._old_board_column
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
    """Add focus session time and increment pomodoro count (undo-able)."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_time_spent: int,
        seconds_to_add: int,
        old_pomodoro_count: int = 0,
    ) -> None:
        super().__init__("Focus session")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_time_spent = old_time_spent
        self._new_time_spent = old_time_spent + seconds_to_add
        self._old_pomodoro_count = old_pomodoro_count
        self._new_pomodoro_count = old_pomodoro_count + 1

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.time_spent = self._new_time_spent
            item.pomodoro_count = self._new_pomodoro_count
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
            item.pomodoro_count = self._old_pomodoro_count
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


class MoveToColumnCommand(QUndoCommand):
    """Move a todo item to a different kanban column."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_column: str,
        new_column: str,
        auto_complete: bool | None = None,
    ) -> None:
        super().__init__(f'Move to "{new_column}"')
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_column = old_column
        self._new_column = new_column
        self._auto_complete = auto_complete
        self._old_complete: bool | None = None

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if not item:
            return
        item.board_column = self._new_column
        if self._auto_complete is True:
            self._old_complete = item.complete
            item.complete = True
        elif self._auto_complete is False:
            self._old_complete = item.complete
            item.complete = False
        item.mark_updated()
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if not item:
            return
        item.board_column = self._old_column
        if self._old_complete is not None:
            item.complete = self._old_complete
        item.mark_updated()
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class AddColumnCommand(QUndoCommand):
    """Add a column to a list's kanban board."""

    def __init__(self, window: MainWindow, list_id: UUID, column_name: str) -> None:
        super().__init__(f'Add column "{column_name}"')
        self._window = window
        self._list_id = list_id
        self._column_name = column_name

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        if self._column_name not in todo_list.board_columns:
            # Insert before the last column (completion column stays last)
            if len(todo_list.board_columns) >= 1:
                todo_list.board_columns.insert(len(todo_list.board_columns) - 1, self._column_name)
            else:
                todo_list.board_columns.append(self._column_name)
            todo_list.mark_updated()
            self._window._save_database()
            self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        if self._column_name in todo_list.board_columns:
            todo_list.board_columns.remove(self._column_name)
            todo_list.mark_updated()
            self._window._save_database()
            self._window._refresh_ui()


class ApplyLayoutPresetCommand(QUndoCommand):
    """Apply a board layout preset, remapping items to new columns."""

    def __init__(self, window: MainWindow, list_id: UUID, new_columns: list[str]) -> None:
        super().__init__("Apply board layout")
        self._window = window
        self._list_id = list_id
        self._new_columns = new_columns
        self._old_columns: list[str] = []
        self._old_item_columns: dict[UUID, str] = {}
        self._old_wip_limits: dict[str, int] = {}

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return

        # Save old state for undo
        self._old_columns = list(todo_list.board_columns)
        self._old_wip_limits = {
            col: todo_list.get_wip_limit(col)
            for col in todo_list.board_columns
            if todo_list.get_wip_limit(col) > 0
        }
        self._old_item_columns.clear()
        for item in todo_list.active_items():
            self._old_item_columns[item.id] = item.board_column

        # Remap items: (1) exact name match, (2) completion→completion,
        # (3) positional mapping by relative column position
        new_set = set(self._new_columns)
        last_old = self._old_columns[-1] if self._old_columns else ""
        last_new = self._new_columns[-1] if self._new_columns else ""
        first_new = self._new_columns[0] if self._new_columns else ""
        old_index = {col: i for i, col in enumerate(self._old_columns)}
        old_len = max(len(self._old_columns) - 1, 1)
        new_len = max(len(self._new_columns) - 1, 1)
        for item in todo_list.active_items():
            if item.board_column in new_set:
                pass  # Column still exists, keep it
            elif item.board_column == last_old and last_new:
                # Was in old completion column → move to new completion column
                item.board_column = last_new
                item.mark_updated()
            elif item.board_column in old_index and self._new_columns:
                # Positional remapping: map by relative position
                rel_pos = old_index[item.board_column] / old_len
                new_idx = round(rel_pos * new_len)
                new_idx = max(0, min(new_idx, len(self._new_columns) - 1))
                item.board_column = self._new_columns[new_idx]
                item.mark_updated()
            else:
                # Fallback: unknown column → inbox
                item.board_column = first_new
                item.mark_updated()

        # Clear WIP limits for removed columns
        for col in self._old_columns:
            if col not in new_set:
                todo_list.set_wip_limit(col, 0)

        todo_list.board_columns = list(self._new_columns)
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return

        # Restore old columns
        todo_list.board_columns = list(self._old_columns)

        # Restore item column assignments
        for item in todo_list.active_items():
            if item.id in self._old_item_columns:
                item.board_column = self._old_item_columns[item.id]
                item.mark_updated()

        # Restore WIP limits
        for col, limit in self._old_wip_limits.items():
            todo_list.set_wip_limit(col, limit)

        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class RemoveColumnCommand(QUndoCommand):
    """Remove a column from a list's kanban board."""

    def __init__(self, window: MainWindow, list_id: UUID, column_name: str, index: int) -> None:
        super().__init__(f'Remove column "{column_name}"')
        self._window = window
        self._list_id = list_id
        self._column_name = column_name
        self._index = index
        self._displaced_items: list[UUID] = []

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        if self._column_name in todo_list.board_columns:
            todo_list.board_columns.remove(self._column_name)
            # Move items from removed column to first remaining column
            first_col = todo_list.board_columns[0] if todo_list.board_columns else ""
            self._displaced_items.clear()
            for item in todo_list.active_items():
                if item.board_column == self._column_name:
                    item.board_column = first_col
                    item.mark_updated()
                    self._displaced_items.append(item.id)
            todo_list.mark_updated()
            self._window._save_database()
            self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        todo_list.board_columns.insert(self._index, self._column_name)
        # Restore items to the original column
        for item_id in self._displaced_items:
            item = todo_list.get_item(item_id)
            if item:
                item.board_column = self._column_name
                item.mark_updated()
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class RenameColumnCommand(QUndoCommand):
    """Rename a kanban column."""

    def __init__(self, window: MainWindow, list_id: UUID, old_name: str, new_name: str) -> None:
        super().__init__(f'Rename column "{old_name}" to "{new_name}"')
        self._window = window
        self._list_id = list_id
        self._old_name = old_name
        self._new_name = new_name

    def redo(self) -> None:
        self._rename(self._old_name, self._new_name)

    def undo(self) -> None:
        self._rename(self._new_name, self._old_name)

    def _rename(self, from_name: str, to_name: str) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        try:
            idx = todo_list.board_columns.index(from_name)
        except ValueError:
            return
        todo_list.board_columns[idx] = to_name
        # Update items referencing the old column name
        for item in todo_list.active_items():
            if item.board_column == from_name:
                item.board_column = to_name
                item.mark_updated()
        # Update WIP limits key
        if from_name in todo_list.wip_limits:
            todo_list.wip_limits[to_name] = todo_list.wip_limits.pop(from_name)
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()


class SetWipLimitCommand(QUndoCommand):
    """Set WIP limit for a kanban column."""

    def __init__(
        self, window: MainWindow, list_id: UUID, column_name: str, old_limit: int, new_limit: int
    ) -> None:
        super().__init__(f'Set WIP limit for "{column_name}" to {new_limit}')
        self._window = window
        self._list_id = list_id
        self._column_name = column_name
        self._old_limit = old_limit
        self._new_limit = new_limit

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        todo_list.set_wip_limit(self._column_name, self._new_limit)
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        todo_list.set_wip_limit(self._column_name, self._old_limit)
        todo_list.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()
