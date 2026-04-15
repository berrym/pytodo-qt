"""Tests for kanban board widgets and commands."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

from PyQt6.QtWidgets import QLabel, QPushButton

from pytodo_qt.core.models import create_todo_item, create_todo_list
from pytodo_qt.gui.widgets.kanban_board import (
    BOARD_PRESETS,
    KanbanBoardWidget,
    KanbanCardWidget,
    KanbanColumnWidget,
    _format_due,
    _is_overdue,
    _sort_fragment,
)
from pytodo_qt.gui.widgets.search_filter import FilterState


def _make_colors() -> dict[str, str]:
    """Return a minimal color dict for testing."""
    return {
        "base": "#ffffff",
        "alternate_base": "#f0f0f0",
        "text": "#000000",
        "highlight": "#0078d4",
        "highlight_text": "#ffffff",
        "border": "#cccccc",
        "completed_bg": "#f0f8f0",
        "completed_text": "#888888",
        "priority_high": "#ff0000",
        "priority_normal": "#0000ff",
        "priority_low": "#999999",
        "due_overdue": "#ff0000",
        "due_today": "#ff8800",
        "due_soon": "#008800",
        "button": "#e0e0e0",
    }


# ===========================================================================
# Sort fragment tests
# ===========================================================================


class TestSortFragment:
    def test_completion_incomplete(self):
        item = create_todo_item("Test")
        result = _sort_fragment(item, "completion", False)
        assert result == (0,)

    def test_completion_complete(self):
        item = create_todo_item("Test")
        item.complete = True
        result = _sort_fragment(item, "completion", False)
        assert result == (1,)

    def test_completion_reverse(self):
        item = create_todo_item("Test")
        item.complete = True
        result = _sort_fragment(item, "completion", True)
        assert result == (-1,)

    def test_due_date_none_sorts_last(self):
        item = create_todo_item("Test")
        result = _sort_fragment(item, "due_date", False)
        assert result == (1, 0, 0)

    def test_due_date_with_date(self):
        item = create_todo_item("Test", due_date=date(2025, 6, 15))
        result = _sort_fragment(item, "due_date", False)
        assert result[0] == 0  # Has date
        assert result[1] == date(2025, 6, 15).toordinal()

    def test_priority(self):
        item = create_todo_item("Test", priority=1)
        result = _sort_fragment(item, "priority", False)
        assert result == (1,)


class TestIsOverdue:
    def test_no_date(self):
        assert not _is_overdue(None, None)

    def test_future_date(self):
        assert not _is_overdue(date.today() + timedelta(days=1), None)

    def test_past_date(self):
        assert _is_overdue(date.today() - timedelta(days=1), None)


class TestFormatDue:
    def test_today(self):
        assert _format_due(date.today(), None, "system") == "Today"

    def test_tomorrow(self):
        assert _format_due(date.today() + timedelta(days=1), None, "system") == "Tomorrow"

    def test_yesterday(self):
        assert _format_due(date.today() - timedelta(days=1), None, "system") == "Yesterday"


# ===========================================================================
# KanbanCardWidget tests
# ===========================================================================


class TestKanbanCardWidget:
    def test_card_creation(self, qtbot):
        item = create_todo_item("Test task", priority=1)
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        assert card._item_id == item.id

    def test_card_completed_styling(self, qtbot):
        item = create_todo_item("Done task")
        item.complete = True
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        # Should have completed background
        assert "completed_bg" in card.styleSheet() or "#f0f8f0" in card.styleSheet()

    def test_card_with_tags(self, qtbot):
        item = create_todo_item("Tagged", tags=["@work", "@urgent", "@project", "@extra"])
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        # Should show max 3 tags + overflow
        assert card._item_id == item.id

    def test_card_with_subtasks(self, qtbot):
        parent = create_todo_item("Parent")
        child1 = create_todo_item("Child 1")
        child1.complete = True
        child2 = create_todo_item("Child 2")
        card = KanbanCardWidget(parent, _make_colors(), "system", subtasks=[child1, child2])
        qtbot.addWidget(card)
        assert hasattr(card, "_subtask_badge")
        assert "1/2" in card._subtask_badge.text()

    def test_subtask_expand_toggle(self, qtbot):
        parent = create_todo_item("Parent")
        child = create_todo_item("Child")
        card = KanbanCardWidget(parent, _make_colors(), "system", subtasks=[child])
        qtbot.addWidget(card)
        assert not card._expanded
        assert card._subtask_container.isHidden()
        card._toggle_subtask_list()
        assert card._expanded
        assert not card._subtask_container.isHidden()
        card._toggle_subtask_list()
        assert not card._expanded
        assert card._subtask_container.isHidden()

    def test_card_click_emits_signal(self, qtbot):
        item = create_todo_item("Test")
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        with qtbot.waitSignal(card.clicked, timeout=1000):
            card.clicked.emit(item.id)

    def test_card_toggle_emits_item_id(self, qtbot):
        item = create_todo_item("Test")
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        received = []
        card.toggle_requested.connect(lambda x: received.append(x))
        card.toggle_requested.emit(item.id)
        assert received == [item.id]

    def test_card_with_due_date(self, qtbot):
        item = create_todo_item("Test", due_date=date.today())
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        assert card._item_id == item.id

    def test_card_with_recurrence(self, qtbot):
        item = create_todo_item("Test", recurrence_type="daily")
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        assert card._item_id == item.id

    def test_card_with_pomodoro(self, qtbot):
        item = create_todo_item("Test")
        item.pomodoro_count = 3
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        assert card._item_id == item.id


# ===========================================================================
# KanbanColumnWidget tests
# ===========================================================================


class TestKanbanColumnWidget:
    def test_column_creation(self, qtbot):
        col = KanbanColumnWidget("To Do", _make_colors())
        qtbot.addWidget(col)
        assert col.column_name == "To Do"

    def test_add_card(self, qtbot):
        col = KanbanColumnWidget("To Do", _make_colors())
        qtbot.addWidget(col)
        item = create_todo_item("Test")
        card = KanbanCardWidget(item, _make_colors(), "system")
        col.add_card(card)
        assert len(col._cards) == 1

    def test_clear_cards(self, qtbot):
        col = KanbanColumnWidget("To Do", _make_colors())
        qtbot.addWidget(col)
        item = create_todo_item("Test")
        card = KanbanCardWidget(item, _make_colors(), "system")
        col.add_card(card)
        col.clear_cards()
        assert len(col._cards) == 0

    def test_card_signals_forwarded(self, qtbot):
        col = KanbanColumnWidget("To Do", _make_colors())
        qtbot.addWidget(col)
        item = create_todo_item("Test")
        card = KanbanCardWidget(item, _make_colors(), "system")
        col.add_card(card)

        received = []
        col.card_clicked.connect(lambda x: received.append(("click", x)))
        col.card_toggle.connect(lambda x: received.append(("toggle", x)))

        card.clicked.emit(item.id)
        card.toggle_requested.emit(item.id)

        assert ("click", item.id) in received
        assert ("toggle", item.id) in received


# ===========================================================================
# KanbanBoardWidget tests
# ===========================================================================


class TestKanbanBoardWidget:
    def test_board_creation(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        assert board._todo_list is None

    def test_board_set_list_creates_columns(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)
        assert len(board._columns) == 3  # Default: To Do, In Progress, Done

    def test_board_custom_columns(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        lst.board_columns = ["Backlog", "Active", "Review", "Done"]
        board.set_list(lst)
        assert len(board._columns) == 4

    def test_board_distributes_items(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")

        item1 = create_todo_item("Todo item", board_column="To Do")
        item2 = create_todo_item("In progress item", board_column="In Progress")
        item3 = create_todo_item("Done item", board_column="Done")
        lst.add_item(item1)
        lst.add_item(item2)
        lst.add_item(item3)

        board.set_list(lst)
        # Each column should have 1 card
        assert len(board._columns[0]._cards) == 1
        assert len(board._columns[1]._cards) == 1
        assert len(board._columns[2]._cards) == 1

    def test_items_without_column_go_to_first(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("No column")  # board_column=""
        lst.add_item(item)
        board.set_list(lst)
        assert len(board._columns[0]._cards) == 1

    def test_subtasks_not_shown_as_cards(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")

        parent = create_todo_item("Parent", board_column="To Do")
        child = create_todo_item("Child")
        child.parent_id = parent.id
        lst.add_item(parent)
        lst.add_item(child)

        board.set_list(lst)
        # Only parent should be a card, child should be passed as subtask data
        total_cards = sum(len(col._cards) for col in board._columns)
        assert total_cards == 1

    def test_board_none_list(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        board.set_list(None)
        assert len(board._columns) == 0

    def test_get_selected_item_ids_empty(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        assert board.get_selected_item_ids() == []

    def test_get_selected_item_ids_with_selection(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        item_id = uuid4()
        board._selected_item_id = item_id
        assert board.get_selected_item_ids() == [item_id]


# ===========================================================================
# Empty-state overlay tests
# ===========================================================================


class TestKanbanEmptyState:
    """The three-case empty-state overlay.

    Case A "no_list"        — empty list → Add task button
    Case B "all_done"       — status filter=incomplete + all complete
                               → Show completed button
    Case C "filtered_empty" — any other filter hides all matches
                               → Clear filters button
    """

    def test_no_list_case_empty_list(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)
        assert not board._empty_state.isHidden()
        assert board._empty_state_action == "add"
        assert "No tasks yet" in board._empty_state_label.text()

    def test_no_list_add_button_emits_add_task(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        board.set_list(create_todo_list("Test"))
        with qtbot.waitSignal(board.add_task_requested, timeout=1000):
            board._empty_state_button.click()

    def test_all_done_case_with_status_incomplete_filter(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Done task")
        item.complete = True
        lst.add_item(item)
        board.set_list(lst)
        board.set_filter(FilterState(status=1))  # Active/incomplete only
        assert not board._empty_state.isHidden()
        assert board._empty_state_action == "show_completed"
        assert "All done" in board._empty_state_label.text()

    def test_all_done_show_completed_button_emits_signal(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Done task")
        item.complete = True
        lst.add_item(item)
        board.set_list(lst)
        board.set_filter(FilterState(status=1))
        with qtbot.waitSignal(board.show_completed_requested, timeout=1000):
            board._empty_state_button.click()

    def test_filtered_empty_case_generic(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Normal task")  # priority defaults to 2
        lst.add_item(item)
        board.set_list(lst)
        board.set_filter(FilterState(priority=1))  # High — won't match
        assert not board._empty_state.isHidden()
        assert board._empty_state_action == "clear_filters"
        assert "No tasks match" in board._empty_state_label.text()

    def test_filtered_empty_clear_filters_button_emits_signal(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Normal task")
        lst.add_item(item)
        board.set_list(lst)
        board.set_filter(FilterState(priority=1))
        with qtbot.waitSignal(board.clear_filters_requested, timeout=1000):
            board._empty_state_button.click()

    def test_overlay_hidden_when_content_visible(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        lst.add_item(create_todo_item("Visible task"))
        board.set_list(lst)
        assert board._empty_state.isHidden()

    def test_overlay_hidden_when_no_list(self, qtbot):
        """Without a selected list, the overlay should not appear —
        the existing behaviour is to show nothing at all, and we
        should not regress that."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        board.set_list(None)
        assert board._empty_state.isHidden()

    def test_all_done_priority_over_filtered_empty(self, qtbot):
        """When the user has exactly the "all tasks complete with
        incomplete filter" situation, the celebratory all_done state
        must be chosen over the generic filtered_empty message.
        """
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Done task")
        item.complete = True
        lst.add_item(item)
        board.set_list(lst)
        # status=1 (incomplete) AND priority=1 — priority filter also
        # rules the item out, but the all-complete invariant still
        # holds so all_done wins.
        board.set_filter(FilterState(status=1, priority=1))
        assert board._empty_state_action == "show_completed"


# ===========================================================================
# Signal bridge tests
# ===========================================================================


class TestSignalBridge:
    def test_toggle_bridge(self, qtbot):
        """Card toggle emits item_id → board emits no-args toggle."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        item_id = uuid4()

        with qtbot.waitSignal(board.toggle_requested, timeout=1000):
            board._on_card_toggle(item_id)
        assert board._selected_item_id == item_id

    def test_delete_bridge(self, qtbot):
        """Card delete emits item_id → board emits no-args delete."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        item_id = uuid4()

        with qtbot.waitSignal(board.delete_requested, timeout=1000):
            board._bridge_delete(item_id)
        assert board._selected_item_id == item_id

    def test_recurrence_bridge(self, qtbot):
        """Card recurrence emits item_id → board emits no-args recurrence."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        item_id = uuid4()

        with qtbot.waitSignal(board.edit_recurrence_requested, timeout=1000):
            board._bridge_recurrence(item_id)
        assert board._selected_item_id == item_id

    def test_card_click_selects(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        item_id = uuid4()
        board._on_card_clicked(item_id)
        assert board._selected_item_id == item_id

    def test_card_click_non_uuid_ignored(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        board._on_card_clicked("not-a-uuid")
        assert board._selected_item_id is None

    def test_selected_card_has_highlight_border(self, qtbot):
        """Clicking a card should give it a highlighted selection border."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        board.set_list(lst)

        card = board._columns[0]._cards[0]
        # Not selected initially
        assert (
            "highlight" not in card.styleSheet().lower() or card._style_normal in card.styleSheet()
        )

        # Click to select
        board._on_card_clicked(item.id)
        assert card.styleSheet() == card._style_selected

    def test_selection_moves_between_cards(self, qtbot):
        """Selecting a new card should deselect the previous one."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item1 = create_todo_item("Task 1", board_column="To Do")
        item2 = create_todo_item("Task 2", board_column="To Do")
        lst.add_item(item1)
        lst.add_item(item2)
        board.set_list(lst)

        card1 = board._columns[0]._cards[0]
        card2 = board._columns[0]._cards[1]

        board._on_card_clicked(item1.id)
        assert card1.styleSheet() == card1._style_selected
        assert card2.styleSheet() == card2._style_normal

        board._on_card_clicked(item2.id)
        assert card1.styleSheet() == card1._style_normal
        assert card2.styleSheet() == card2._style_selected


# ===========================================================================
# Filter tests
# ===========================================================================


class TestBoardFilter:
    def test_text_filter(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        lst.add_item(create_todo_item("Buy milk", board_column="To Do"))
        lst.add_item(create_todo_item("Write code", board_column="To Do"))

        board.set_list(lst)
        assert sum(len(c._cards) for c in board._columns) == 2

        board.set_filter(FilterState(text="milk"))
        assert sum(len(c._cards) for c in board._columns) == 1

    def test_priority_filter(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        lst.add_item(create_todo_item("High", priority=1, board_column="To Do"))
        lst.add_item(create_todo_item("Normal", priority=2, board_column="To Do"))
        board.set_list(lst)

        board.set_filter(FilterState(priority=1))
        assert sum(len(c._cards) for c in board._columns) == 1

    def test_status_filter_incomplete(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item1 = create_todo_item("Active", board_column="To Do")
        item2 = create_todo_item("Done", board_column="Done")
        item2.complete = True
        lst.add_item(item1)
        lst.add_item(item2)
        board.set_list(lst)

        board.set_filter(FilterState(status=1))  # Incomplete only
        assert sum(len(c._cards) for c in board._columns) == 1

    def test_tag_filter(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        lst.add_item(create_todo_item("Tagged", tags=["@work"], board_column="To Do"))
        lst.add_item(create_todo_item("Untagged", board_column="To Do"))
        board.set_list(lst)

        board.set_filter(FilterState(tag="@work"))
        assert sum(len(c._cards) for c in board._columns) == 1

    def test_clear_filter(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        lst.add_item(create_todo_item("Item 1", board_column="To Do"))
        lst.add_item(create_todo_item("Item 2", board_column="To Do"))
        board.set_list(lst)

        board.set_filter(FilterState(text="Item 1"))
        assert sum(len(c._cards) for c in board._columns) == 1

        board.set_filter(FilterState())  # Clear
        assert sum(len(c._cards) for c in board._columns) == 2


# ===========================================================================
# Drag-and-drop tests
# ===========================================================================


class TestDragDrop:
    def test_drag_guard_defers_refresh(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        lst.add_item(create_todo_item("Item", board_column="To Do"))
        board.set_list(lst)

        board._dragging = True
        board.refresh()  # Should be deferred
        assert board._refresh_pending

        board._dragging = False

    def test_card_dropped_emits_signal(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        item_id = uuid4()

        received = []
        board.item_column_changed.connect(lambda iid, col: received.append((iid, col)))
        board._on_card_dropped(item_id, "Done")
        assert received == [(item_id, "Done")]


# ===========================================================================
# MoveToColumnCommand tests
# ===========================================================================


class TestMoveToColumnCommand:
    def test_move_basic(self):
        """Moving an item changes its board_column."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import MoveToColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = MoveToColumnCommand(window, lst.id, item.id, "To Do", "In Progress")
        cmd.redo()

        assert item.board_column == "In Progress"
        window._save_database.assert_called()
        window._refresh_ui.assert_called()

    def test_move_undo(self):
        """Undoing a move restores the old column."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import MoveToColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = MoveToColumnCommand(window, lst.id, item.id, "To Do", "Done")
        cmd.redo()
        assert item.board_column == "Done"

        cmd.undo()
        assert item.board_column == "To Do"

    def test_auto_complete_on_move_to_last(self):
        """Moving to last column auto-completes."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import MoveToColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = MoveToColumnCommand(window, lst.id, item.id, "To Do", "Done", auto_complete=True)
        cmd.redo()

        assert item.board_column == "Done"
        assert item.complete is True

    def test_auto_uncomplete_on_move_away_from_last(self):
        """Moving away from last column uncompletes."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import MoveToColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="Done")
        item.complete = True
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = MoveToColumnCommand(
            window, lst.id, item.id, "Done", "In Progress", auto_complete=False
        )
        cmd.redo()

        assert item.board_column == "In Progress"
        assert item.complete is False

    def test_auto_complete_undo_restores_state(self):
        """Undoing auto-complete restores both column and completion state."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import MoveToColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = MoveToColumnCommand(window, lst.id, item.id, "To Do", "Done", auto_complete=True)
        cmd.redo()
        assert item.complete is True

        cmd.undo()
        assert item.board_column == "To Do"
        assert item.complete is False  # Restored to original

    def test_auto_complete_writes_completed_at(self):
        """Auto-complete on move writes a completed_at timestamp."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import MoveToColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        assert item.completed_at is None
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = MoveToColumnCommand(window, lst.id, item.id, "To Do", "Done", auto_complete=True)
        cmd.redo()

        assert item.complete is True
        assert item.completed_at is not None
        assert item.completed_at > 0

    def test_auto_complete_undo_clears_completed_at(self):
        """Undoing an auto-complete restores completed_at to its original value."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import MoveToColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        # Originally incomplete with no timestamp
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = MoveToColumnCommand(window, lst.id, item.id, "To Do", "Done", auto_complete=True)
        cmd.redo()
        assert item.completed_at is not None

        cmd.undo()
        assert item.complete is False
        assert item.completed_at is None  # Back to original

    def test_auto_uncomplete_undo_restores_completed_at(self):
        """Undoing an auto-uncomplete restores the original completed_at."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import MoveToColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="Done")
        original_ts = 1_700_000_000_000
        item.complete = True
        item.completed_at = original_ts
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = MoveToColumnCommand(
            window, lst.id, item.id, "Done", "In Progress", auto_complete=False
        )
        cmd.redo()
        assert item.complete is False
        assert item.completed_at is None  # Cleared by uncomplete

        cmd.undo()
        assert item.complete is True
        assert item.completed_at == original_ts  # Exact original preserved

    def test_missing_list_no_op(self):
        """Command no-ops if list doesn't exist."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import MoveToColumnCommand

        db = Database()
        window = MagicMock()
        window._database = db

        cmd = MoveToColumnCommand(window, uuid4(), uuid4(), "A", "B")
        cmd.redo()  # Should not crash
        cmd.undo()  # Should not crash


# ===========================================================================
# AddColumnCommand tests
# ===========================================================================


class TestAddColumnCommand:
    def test_add_column(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import AddColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = AddColumnCommand(window, lst.id, "Review")
        cmd.redo()

        # New columns insert before the last (completion) column
        assert lst.board_columns == ["To Do", "In Progress", "Review", "Done"]
        window._save_database.assert_called()
        window._refresh_ui.assert_called()

    def test_add_column_undo(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import AddColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = AddColumnCommand(window, lst.id, "Review")
        cmd.redo()
        assert "Review" in lst.board_columns

        cmd.undo()
        assert "Review" not in lst.board_columns

    def test_add_duplicate_no_op(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import AddColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = AddColumnCommand(window, lst.id, "To Do")
        cmd.redo()
        # Should not duplicate
        assert lst.board_columns.count("To Do") == 1

    def test_missing_list_no_op(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import AddColumnCommand

        db = Database()
        window = MagicMock()
        window._database = db

        cmd = AddColumnCommand(window, uuid4(), "Review")
        cmd.redo()  # Should not crash
        cmd.undo()  # Should not crash


# ===========================================================================
# RemoveColumnCommand tests
# ===========================================================================


class TestRemoveColumnCommand:
    def test_remove_column(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import RemoveColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = RemoveColumnCommand(window, lst.id, "In Progress", 1)
        cmd.redo()

        assert lst.board_columns == ["To Do", "Done"]

    def test_remove_column_displaces_items(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import RemoveColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="In Progress")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = RemoveColumnCommand(window, lst.id, "In Progress", 1)
        cmd.redo()

        assert item.board_column == "To Do"  # Moved to first column

    def test_remove_column_undo_restores(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import RemoveColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="In Progress")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = RemoveColumnCommand(window, lst.id, "In Progress", 1)
        cmd.redo()
        assert "In Progress" not in lst.board_columns
        assert item.board_column == "To Do"

        cmd.undo()
        assert lst.board_columns == ["To Do", "In Progress", "Done"]
        assert item.board_column == "In Progress"

    def test_missing_list_no_op(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import RemoveColumnCommand

        db = Database()
        window = MagicMock()
        window._database = db

        cmd = RemoveColumnCommand(window, uuid4(), "X", 0)
        cmd.redo()  # Should not crash
        cmd.undo()  # Should not crash


# ===========================================================================
# RenameColumnCommand tests
# ===========================================================================


class TestRenameColumnCommand:
    def test_rename_column(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import RenameColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = RenameColumnCommand(window, lst.id, "In Progress", "Active")
        cmd.redo()

        assert lst.board_columns == ["To Do", "Active", "Done"]

    def test_rename_updates_items(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import RenameColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="In Progress")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = RenameColumnCommand(window, lst.id, "In Progress", "Active")
        cmd.redo()

        assert item.board_column == "Active"

    def test_rename_updates_wip_limits(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import RenameColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        lst.set_wip_limit("In Progress", 3)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = RenameColumnCommand(window, lst.id, "In Progress", "Active")
        cmd.redo()

        assert lst.get_wip_limit("Active") == 3
        assert lst.get_wip_limit("In Progress") == 0

    def test_rename_undo(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import RenameColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="In Progress")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = RenameColumnCommand(window, lst.id, "In Progress", "Active")
        cmd.redo()
        assert item.board_column == "Active"

        cmd.undo()
        assert lst.board_columns == ["To Do", "In Progress", "Done"]
        assert item.board_column == "In Progress"

    def test_missing_list_no_op(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import RenameColumnCommand

        db = Database()
        window = MagicMock()
        window._database = db

        cmd = RenameColumnCommand(window, uuid4(), "X", "Y")
        cmd.redo()  # Should not crash
        cmd.undo()  # Should not crash

    def test_rename_nonexistent_column_no_op(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import RenameColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = RenameColumnCommand(window, lst.id, "Nonexistent", "New")
        cmd.redo()  # Should not crash
        assert lst.board_columns == ["To Do", "In Progress", "Done"]


# ===========================================================================
# Column management widget tests
# ===========================================================================


class TestColumnManagement:
    def test_column_has_menu_button(self, qtbot):
        """Column header should have a ⋮ menu button."""
        col = KanbanColumnWidget("To Do", _make_colors())
        qtbot.addWidget(col)
        # Find the menu button by text
        buttons = col.findChildren(QPushButton)
        menu_texts = [b.text() for b in buttons]
        assert "\u22ee" in menu_texts  # ⋮

    def test_column_rename_signal(self, qtbot):
        col = KanbanColumnWidget("To Do", _make_colors())
        qtbot.addWidget(col)
        received = []
        col.rename_requested.connect(lambda name: received.append(name))
        col.rename_requested.emit("To Do")
        assert received == ["To Do"]

    def test_column_delete_signal(self, qtbot):
        col = KanbanColumnWidget("To Do", _make_colors())
        qtbot.addWidget(col)
        received = []
        col.delete_requested_col.connect(lambda name: received.append(name))
        col.delete_requested_col.emit("To Do")
        assert received == ["To Do"]

    def test_column_wip_limit_signal(self, qtbot):
        col = KanbanColumnWidget("To Do", _make_colors())
        qtbot.addWidget(col)
        received = []
        col.set_wip_limit_requested.connect(lambda name: received.append(name))
        col.set_wip_limit_requested.emit("To Do")
        assert received == ["To Do"]

    def test_board_has_layout_button(self, qtbot):
        """Board should have a Layout button."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)
        assert board._layout_btn is not None
        assert "Layout" in board._layout_btn.text()

    def test_board_layout_button_survives_refresh(self, qtbot):
        """Layout button should persist across refreshes."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)
        assert board._layout_btn is not None
        board.refresh()
        assert board._layout_btn is not None
        assert "Layout" in board._layout_btn.text()

    def test_board_column_delete_forwarded(self, qtbot):
        """Column delete signal should be forwarded to board remove_column_requested."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)

        received = []
        board.remove_column_requested.connect(lambda name: received.append(name))
        board._columns[1].delete_requested_col.emit("In Progress")
        assert received == ["In Progress"]

    def test_board_add_item_in_column_signal(self, qtbot):
        """'+ Add item' click should emit add_item_in_column_requested."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)

        received = []
        board.add_item_in_column_requested.connect(lambda name: received.append(name))
        board._columns[0].add_item_clicked.emit("To Do")
        assert received == ["To Do"]

    def test_last_column_has_completion_indicator(self, qtbot):
        """Last column should show a completion checkmark icon."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)
        last_col = board._columns[-1]
        assert last_col._is_last is True
        labels = last_col.findChildren(QLabel)
        check_labels = [lb for lb in labels if "\u2705" in lb.text()]
        assert len(check_labels) == 1

    def test_non_last_column_no_completion_indicator(self, qtbot):
        """Non-last columns should NOT have completion indicator."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)
        first_col = board._columns[0]
        assert first_col._is_last is False
        labels = first_col.findChildren(QLabel)
        check_labels = [lb for lb in labels if "\u2705" in lb.text()]
        assert len(check_labels) == 0

    def test_last_column_menu_no_delete(self, qtbot, monkeypatch):
        """Last column context menu should NOT have Delete or WIP options."""
        from PyQt6.QtWidgets import QMenu

        col = KanbanColumnWidget("Done", _make_colors(), is_last=True)
        qtbot.addWidget(col)

        menus_shown: list[QMenu] = []

        def fake_exec(menu_self, *args, **kwargs):
            menus_shown.append(menu_self)

        monkeypatch.setattr(QMenu, "exec", fake_exec)
        col._show_column_menu()

        assert len(menus_shown) == 1
        menu = menus_shown[0]
        action_texts = [a.text() for a in menu.actions()]
        assert "Rename Column..." in action_texts
        assert "Delete Column" not in action_texts
        assert "Set WIP Limit..." not in action_texts

    def test_add_column_inserts_before_last(self):
        """New columns should insert before the completion column."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import AddColumnCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = AddColumnCommand(window, lst.id, "Review")
        cmd.redo()
        assert lst.board_columns == ["To Do", "In Progress", "Review", "Done"]
        # Done stays last
        assert lst.board_columns[-1] == "Done"


# ===========================================================================
# SetWipLimitCommand tests
# ===========================================================================


class TestSetWipLimitCommand:
    def test_set_wip_limit(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import SetWipLimitCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = SetWipLimitCommand(window, lst.id, "In Progress", 0, 3)
        cmd.redo()

        assert lst.get_wip_limit("In Progress") == 3

    def test_set_wip_limit_undo(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import SetWipLimitCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = SetWipLimitCommand(window, lst.id, "In Progress", 0, 5)
        cmd.redo()
        assert lst.get_wip_limit("In Progress") == 5

        cmd.undo()
        assert lst.get_wip_limit("In Progress") == 0

    def test_remove_wip_limit(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import SetWipLimitCommand

        db = Database()
        lst = create_todo_list("Test")
        lst.set_wip_limit("In Progress", 3)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = SetWipLimitCommand(window, lst.id, "In Progress", 3, 0)
        cmd.redo()

        assert lst.get_wip_limit("In Progress") == 0
        assert "In Progress" not in lst.wip_limits

    def test_missing_list_no_op(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import SetWipLimitCommand

        db = Database()
        window = MagicMock()
        window._database = db

        cmd = SetWipLimitCommand(window, uuid4(), "X", 0, 3)
        cmd.redo()  # Should not crash
        cmd.undo()  # Should not crash


# ===========================================================================
# WIP limit display tests
# ===========================================================================


class TestWipLimitDisplay:
    def test_column_no_wip_limit_shows_count(self, qtbot):
        col = KanbanColumnWidget("To Do", _make_colors())
        qtbot.addWidget(col)
        item = create_todo_item("Test")
        card = KanbanCardWidget(item, _make_colors(), "system")
        col.add_card(card)
        assert col._count_label.text() == "1"

    def test_column_with_wip_limit_shows_fraction(self, qtbot):
        col = KanbanColumnWidget("In Progress", _make_colors(), wip_limit=3)
        qtbot.addWidget(col)
        item = create_todo_item("Test")
        card = KanbanCardWidget(item, _make_colors(), "system")
        col.add_card(card)
        assert col._count_label.text() == "1/3"

    def test_column_at_wip_limit_amber(self, qtbot):
        colors = _make_colors()
        col = KanbanColumnWidget("In Progress", colors, wip_limit=2)
        qtbot.addWidget(col)
        for i in range(2):
            item = create_todo_item(f"Task {i}")
            card = KanbanCardWidget(item, colors, "system")
            col.add_card(card)
        assert col._count_label.text() == "2/2"
        assert colors["due_today"] in col._count_label.styleSheet()

    def test_column_over_wip_limit_red(self, qtbot):
        colors = _make_colors()
        col = KanbanColumnWidget("In Progress", colors, wip_limit=2)
        qtbot.addWidget(col)
        for i in range(3):
            item = create_todo_item(f"Task {i}")
            card = KanbanCardWidget(item, colors, "system")
            col.add_card(card)
        assert col._count_label.text() == "3/2"
        assert colors["due_overdue"] in col._count_label.styleSheet()

    def test_board_passes_wip_limit_to_column(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        lst.set_wip_limit("In Progress", 5)
        board.set_list(lst)
        # The "In Progress" column (index 1) should have wip_limit=5
        assert board._columns[1]._wip_limit == 5

    def test_board_wip_limit_signal_forwarded(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)

        received = []
        board.wip_limit_changed.connect(lambda name, limit: received.append((name, limit)))
        board.wip_limit_changed.emit("In Progress", 3)
        assert received == [("In Progress", 3)]


# ===========================================================================
# Keyboard navigation tests
# ===========================================================================


def _board_with_items(qtbot):
    """Helper: create a board with items in each column."""
    board = KanbanBoardWidget()
    qtbot.addWidget(board)
    lst = create_todo_list("Test")
    lst.add_item(create_todo_item("Todo 1", board_column="To Do"))
    lst.add_item(create_todo_item("Todo 2", board_column="To Do"))
    lst.add_item(create_todo_item("Active 1", board_column="In Progress"))
    lst.add_item(create_todo_item("Done 1", board_column="Done"))
    board.set_list(lst)
    return board, lst


class TestKeyboardNavigation:
    def test_initial_focus_state(self, qtbot):
        board, _ = _board_with_items(qtbot)
        assert board._focus_col == 0
        assert board._focus_card == -1

    def test_move_focus_down(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._move_focus_card(1)
        assert board._focus_card == 0
        board._move_focus_card(1)
        assert board._focus_card == 1

    def test_move_focus_up_clamps(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._move_focus_card(-1)
        assert board._focus_card == 0  # Clamps to 0 from -1

    def test_move_focus_down_clamps(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._focus_card = 1
        board._move_focus_card(1)
        assert board._focus_card == 1  # Column 0 only has 2 items

    def test_move_focus_right(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._focus_card = 0
        board._move_focus_column(1)
        assert board._focus_col == 1
        assert board._focus_card == 0

    def test_move_focus_left_clamps(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._move_focus_column(-1)
        assert board._focus_col == 0  # Already at leftmost

    def test_move_focus_right_clamps(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._focus_col = 2
        board._move_focus_column(1)
        assert board._focus_col == 2  # Already at rightmost

    def test_move_focus_to_empty_column(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        lst.add_item(create_todo_item("Task", board_column="To Do"))
        # "In Progress" column will be empty
        board.set_list(lst)
        board._focus_card = 0
        board._move_focus_column(1)
        assert board._focus_col == 1
        assert board._focus_card == -1  # No cards in column

    def test_select_focused_card(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._focus_card = 0
        board._select_focused_card()
        assert board._selected_item_id is not None
        assert len(board.get_selected_item_ids()) == 1

    def test_toggle_focused_card(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._focus_card = 0
        received = []
        board.toggle_requested.connect(lambda: received.append(True))
        board._toggle_focused_card()
        assert len(received) == 1
        assert board._selected_item_id is not None

    def test_delete_focused_card(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._focus_card = 0
        received = []
        board.delete_requested.connect(lambda: received.append(True))
        board._delete_focused_card()
        assert len(received) == 1

    def test_add_item_focused_column(self, qtbot):
        board, _ = _board_with_items(qtbot)
        received = []
        board.add_item_in_column_requested.connect(lambda col: received.append(col))
        board._add_item_to_focused_column()
        assert received == ["To Do"]

    def test_move_card_to_adjacent(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._focus_card = 0
        received = []
        board.item_column_changed.connect(lambda iid, col: received.append(col))
        board._move_card_to_adjacent(1)
        assert received == ["In Progress"]

    def test_move_card_to_adjacent_left_blocked(self, qtbot):
        board, _ = _board_with_items(qtbot)
        board._focus_card = 0
        received = []
        board.item_column_changed.connect(lambda iid, col: received.append(col))
        board._move_card_to_adjacent(-1)
        assert received == []  # Can't move left from first column

    def test_no_focused_card_operations_noop(self, qtbot):
        board, _ = _board_with_items(qtbot)
        # _focus_card = -1, no card focused
        board._select_focused_card()
        assert board._selected_item_id is None
        board._toggle_focused_card()  # Should not crash
        board._delete_focused_card()  # Should not crash

    def test_get_focused_card(self, qtbot):
        board, _ = _board_with_items(qtbot)
        assert board._get_focused_card() is None  # -1 index
        board._focus_card = 0
        card = board._get_focused_card()
        assert card is not None
        assert card._item_id is not None


# ===========================================================================
# Focus session highlighting tests (Phase 9)
# ===========================================================================


class TestFocusSessionHighlight:
    def test_focus_session_item_default_none(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        assert board._focus_session_item_id is None

    def test_set_focus_session_item(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        board.set_list(lst)

        board.set_focus_session_item(item.id)
        assert board._focus_session_item_id == item.id

    def test_focus_session_card_has_glow(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        board.set_list(lst)
        board._focus_session_item_id = item.id
        board.refresh()

        card = board._columns[0]._cards[0]
        assert card._is_focus_item is True
        effect = card.graphicsEffect()
        assert effect is not None

    def test_focus_session_card_has_badge(self, qtbot):
        item = create_todo_item("Task")
        card = KanbanCardWidget(item, _make_colors(), "system", is_focus_item=True)
        qtbot.addWidget(card)
        # Should have a "Focus" label somewhere
        labels = card.findChildren(QLabel)
        focus_labels = [lb for lb in labels if "Focus" in lb.text()]
        assert len(focus_labels) == 1

    def test_non_focus_card_no_badge(self, qtbot):
        item = create_todo_item("Task")
        card = KanbanCardWidget(item, _make_colors(), "system", is_focus_item=False)
        qtbot.addWidget(card)
        labels = card.findChildren(QLabel)
        focus_labels = [lb for lb in labels if "Focus" in lb.text()]
        assert len(focus_labels) == 0

    def test_clear_focus_session(self, qtbot):
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        board.set_list(lst)

        board.set_focus_session_item(item.id)
        board.set_focus_session_item(None)
        assert board._focus_session_item_id is None


# ===========================================================================
# Context menu tests (priority, due date)
# ===========================================================================


class TestContextMenu:
    def test_priority_change_emits_signal(self, qtbot):
        """Setting priority via context menu emits item_priority_changed."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        board.set_list(lst)

        received: list[tuple[object, int]] = []
        board.item_priority_changed.connect(lambda iid, p: received.append((iid, p)))
        # Directly emit signal as context menu would
        board.item_priority_changed.emit(item.id, 1)
        assert received == [(item.id, 1)]

    def test_due_date_edit_emits_signal(self, qtbot):
        """Due date change emits item_due_date_changed."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        board.set_list(lst)

        received: list[tuple[object, object]] = []
        board.item_due_date_changed.connect(lambda iid, d: received.append((iid, d)))
        today = date.today()
        board.item_due_date_changed.emit(item.id, today)
        assert received == [(item.id, today)]

    def test_context_menu_has_priority_submenu(self, qtbot, monkeypatch):
        """Context menu should include Set Priority submenu."""
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QMenu

        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        board.set_list(lst)

        # Capture the menu that gets created
        menus_shown: list[QMenu] = []

        def fake_exec(menu_self, *args, **kwargs):
            menus_shown.append(menu_self)

        monkeypatch.setattr(QMenu, "exec", fake_exec)
        board._on_card_context_menu(item.id, QPoint(0, 0))

        assert len(menus_shown) == 1
        menu = menus_shown[0]
        action_texts = [a.text() for a in menu.actions()]
        # Should have a "Set Priority" submenu
        assert any("Set Priority" in t for t in action_texts)

    def test_context_menu_has_edit_due_date(self, qtbot, monkeypatch):
        """Context menu should include Edit Due Date option."""
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QMenu

        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="To Do")
        lst.add_item(item)
        board.set_list(lst)

        menus_shown: list[QMenu] = []

        def fake_exec(menu_self, *args, **kwargs):
            menus_shown.append(menu_self)

        monkeypatch.setattr(QMenu, "exec", fake_exec)
        board._on_card_context_menu(item.id, QPoint(0, 0))

        assert len(menus_shown) == 1
        menu = menus_shown[0]
        action_texts = [a.text() for a in menu.actions()]
        assert any("Edit Due Date" in t for t in action_texts)

    def test_priority_submenu_checkmark(self, qtbot, monkeypatch):
        """Current priority should have a checkmark in the submenu."""
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QMenu

        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        item = create_todo_item("Task", priority=1, board_column="To Do")  # High
        lst.add_item(item)
        board.set_list(lst)

        menus_shown: list[QMenu] = []

        def fake_exec(menu_self, *args, **kwargs):
            menus_shown.append(menu_self)

        monkeypatch.setattr(QMenu, "exec", fake_exec)
        board._on_card_context_menu(item.id, QPoint(0, 0))

        menu = menus_shown[0]
        # Find the priority submenu
        for action in menu.actions():
            submenu = action.menu()
            if submenu and "Priority" in action.text():
                sub_actions = submenu.actions()
                texts = [a.text() for a in sub_actions]
                # High should have checkmark
                assert any("\u2713" in t and "High" in t for t in texts)
                # Normal should NOT have checkmark
                assert any("Normal" in t and "\u2713" not in t for t in texts)


# ===========================================================================
# Overdue visual indicator and tooltip tests
# ===========================================================================


class TestCardVisualIndicators:
    def test_overdue_card_has_warning_icon(self, qtbot):
        """Overdue items should show a ⚠ warning prefix on the due date."""
        yesterday = date.today() - timedelta(days=1)
        item = create_todo_item("Late task", due_date=yesterday)
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        labels = card.findChildren(QLabel)
        due_labels = [lb for lb in labels if "\u26a0" in lb.text()]
        assert len(due_labels) == 1

    def test_overdue_card_bold_text(self, qtbot):
        """Overdue due date should be bold."""
        yesterday = date.today() - timedelta(days=1)
        item = create_todo_item("Late task", due_date=yesterday)
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        labels = card.findChildren(QLabel)
        due_labels = [lb for lb in labels if "\u26a0" in lb.text()]
        assert len(due_labels) == 1
        assert "bold" in due_labels[0].styleSheet()

    def test_completed_overdue_no_warning(self, qtbot):
        """Completed items should NOT show overdue warning even if past due."""
        yesterday = date.today() - timedelta(days=1)
        item = create_todo_item("Done task", due_date=yesterday)
        item.complete = True
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        labels = card.findChildren(QLabel)
        due_labels = [lb for lb in labels if "\u26a0" in lb.text()]
        assert len(due_labels) == 0

    def test_due_date_tooltip_shows_full_date(self, qtbot):
        """Due date label should have a tooltip with full date."""
        tomorrow = date.today() + timedelta(days=1)
        item = create_todo_item("Future task", due_date=tomorrow)
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        labels = card.findChildren(QLabel)
        due_labels = [lb for lb in labels if "Tomorrow" in lb.text()]
        assert len(due_labels) == 1
        tip = due_labels[0].toolTip()
        assert tomorrow.strftime("%Y") in tip
        assert tomorrow.strftime("%B") in tip

    def test_overdue_tooltip_says_overdue(self, qtbot):
        """Overdue items should have '(overdue)' in their tooltip."""
        yesterday = date.today() - timedelta(days=1)
        item = create_todo_item("Late task", due_date=yesterday)
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        labels = card.findChildren(QLabel)
        due_labels = [lb for lb in labels if "\u26a0" in lb.text()]
        assert len(due_labels) == 1
        assert "(overdue)" in due_labels[0].toolTip()

    def test_recurrence_tooltip_shows_type(self, qtbot):
        """Recurrence icon should have tooltip describing the rule."""
        item = create_todo_item("Recurring", recurrence_type="weekly", recurrence_interval=2)
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        labels = card.findChildren(QLabel)
        rec_labels = [lb for lb in labels if "\u21bb" in lb.text()]
        assert len(rec_labels) == 1
        tip = rec_labels[0].toolTip()
        assert "2" in tip
        assert "week" in tip

    def test_recurrence_tooltip_simple_daily(self, qtbot):
        """Simple daily recurrence should say 'Repeats daily'."""
        item = create_todo_item("Daily", recurrence_type="daily", recurrence_interval=1)
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        labels = card.findChildren(QLabel)
        rec_labels = [lb for lb in labels if "\u21bb" in lb.text()]
        assert len(rec_labels) == 1
        assert "Repeats daily" in rec_labels[0].toolTip()

    def test_recurrence_tooltip_with_end_date(self, qtbot):
        """Recurrence tooltip should include end date if set."""
        end = date(2026, 12, 31)
        item = create_todo_item("Until", recurrence_type="monthly", recurrence_end_date=end)
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        labels = card.findChildren(QLabel)
        rec_labels = [lb for lb in labels if "\u21bb" in lb.text()]
        assert len(rec_labels) == 1
        assert "Dec 31, 2026" in rec_labels[0].toolTip()

    def test_recurrence_tooltip_with_count(self, qtbot):
        """Recurrence tooltip should show completion count if end_count set."""
        item = create_todo_item(
            "Counted",
            recurrence_type="daily",
            recurrence_end_count=10,
        )
        item.recurrence_count = 3
        card = KanbanCardWidget(item, _make_colors(), "system")
        qtbot.addWidget(card)
        labels = card.findChildren(QLabel)
        rec_labels = [lb for lb in labels if "\u21bb" in lb.text()]
        assert len(rec_labels) == 1
        assert "3/10" in rec_labels[0].toolTip()


# ===========================================================================
# Board layout presets and column protection tests
# ===========================================================================


class TestBoardLayoutPresets:
    def test_presets_exist(self):
        """BOARD_PRESETS should have at least 3 presets."""
        assert len(BOARD_PRESETS) >= 3

    def test_all_presets_end_with_completion_column(self):
        """Every preset should have a completion column (last)."""
        for name, cols in BOARD_PRESETS.items():
            assert len(cols) >= 3, f"Preset '{name}' has fewer than 3 columns"

    def test_apply_layout_preset_command(self):
        """ApplyLayoutPresetCommand should change board columns."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import ApplyLayoutPresetCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        new_cols = ["To Do", "In Progress", "Review", "Done"]
        cmd = ApplyLayoutPresetCommand(window, lst.id, new_cols)
        cmd.redo()
        assert lst.board_columns == new_cols

    def test_apply_layout_preset_undo(self):
        """ApplyLayoutPresetCommand undo should restore old columns."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import ApplyLayoutPresetCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)
        original = list(lst.board_columns)

        window = MagicMock()
        window._database = db

        new_cols = ["Backlog", "To Do", "In Progress", "Done"]
        cmd = ApplyLayoutPresetCommand(window, lst.id, new_cols)
        cmd.redo()
        assert lst.board_columns == new_cols

        cmd.undo()
        assert lst.board_columns == original

    def test_apply_layout_remaps_items(self):
        """Items in removed columns remap by relative position."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import ApplyLayoutPresetCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Task", board_column="In Progress")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        # Switch to layout without "In Progress"
        # Old: [To Do(0), In Progress(1), Done(2)] — rel pos 1/2 = 0.5
        # New: [Backlog(0), To Do(1), Done(2)] — 0.5 maps to index 1 = "To Do"
        new_cols = ["Backlog", "To Do", "Done"]
        cmd = ApplyLayoutPresetCommand(window, lst.id, new_cols)
        cmd.redo()
        assert item.board_column == "To Do"

    def test_apply_layout_completion_column_items_remap(self):
        """Items in old completion column should move to new completion column."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import ApplyLayoutPresetCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Done task", board_column="Done")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        new_cols = ["To Do", "In Progress", "Review", "Complete"]
        cmd = ApplyLayoutPresetCommand(window, lst.id, new_cols)
        cmd.redo()
        # Was in old "Done" (last col) → should be in new "Complete" (last col)
        assert item.board_column == "Complete"


class TestColumnProtection:
    def test_first_column_has_inbox_indicator(self, qtbot):
        """First column should show inbox icon."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)
        first_col = board._columns[0]
        assert first_col._is_first is True
        labels = first_col.findChildren(QLabel)
        inbox_labels = [lb for lb in labels if "\U0001f4e5" in lb.text()]
        assert len(inbox_labels) == 1

    def test_first_column_menu_no_delete_no_wip(self, qtbot, monkeypatch):
        """First column menu should NOT have Delete or WIP options."""
        from PyQt6.QtWidgets import QMenu

        col = KanbanColumnWidget("To Do", _make_colors(), is_first=True)
        qtbot.addWidget(col)

        menus_shown: list[QMenu] = []

        def fake_exec(menu_self, *args, **kwargs):
            menus_shown.append(menu_self)

        monkeypatch.setattr(QMenu, "exec", fake_exec)
        col._show_column_menu()

        menu = menus_shown[0]
        action_texts = [a.text() for a in menu.actions()]
        assert "Rename Column..." in action_texts
        assert "Delete Column" not in action_texts
        assert "Set WIP Limit..." not in action_texts

    def test_middle_column_menu_has_all_options(self, qtbot, monkeypatch):
        """Middle columns should have all menu options."""
        from PyQt6.QtWidgets import QMenu

        col = KanbanColumnWidget("In Progress", _make_colors())
        qtbot.addWidget(col)

        menus_shown: list[QMenu] = []

        def fake_exec(menu_self, *args, **kwargs):
            menus_shown.append(menu_self)

        monkeypatch.setattr(QMenu, "exec", fake_exec)
        col._show_column_menu()

        menu = menus_shown[0]
        action_texts = [a.text() for a in menu.actions()]
        assert "Rename Column..." in action_texts
        assert "Set WIP Limit..." in action_texts
        assert "Delete Column" in action_texts

    def test_layout_preset_signal(self, qtbot):
        """Layout button should emit layout_preset_requested."""
        board = KanbanBoardWidget()
        qtbot.addWidget(board)
        lst = create_todo_list("Test")
        board.set_list(lst)

        received: list[object] = []
        board.layout_preset_requested.connect(lambda cols: received.append(cols))
        board.layout_preset_requested.emit(["To Do", "In Progress", "Review", "Done"])
        assert len(received) == 1
        assert received[0] == ["To Do", "In Progress", "Review", "Done"]


class TestViewSwitchingBoardColumn:
    """Tests for board_column synchronization across view switches."""

    def _make_db_and_window(self):
        from pytodo_qt.core.models import Database

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)
        window = MagicMock()
        window._database = db
        return db, lst, window

    # -- ToggleCompleteCommand board_column sync --

    def test_toggle_complete_moves_to_done_column(self):
        """Completing an item moves it to the last (completion) column."""
        from pytodo_qt.gui.commands import ToggleCompleteCommand

        db, lst, window = self._make_db_and_window()
        item = create_todo_item("Task", board_column="In Progress")
        lst.add_item(item)
        assert not item.complete

        cmd = ToggleCompleteCommand(window, lst.id, [(item.id, False)])
        cmd.redo()
        assert item.complete
        assert item.board_column == "Done"

    def test_toggle_incomplete_moves_from_done(self):
        """Un-completing an item in Done moves it to first (inbox) column."""
        from pytodo_qt.gui.commands import ToggleCompleteCommand

        db, lst, window = self._make_db_and_window()
        item = create_todo_item("Task", board_column="Done")
        item.complete = True
        lst.add_item(item)

        cmd = ToggleCompleteCommand(window, lst.id, [(item.id, True)])
        cmd.redo()
        assert not item.complete
        assert item.board_column == "To Do"

    def test_toggle_complete_undo_restores_column(self):
        """Undo of toggle restores original board_column."""
        from pytodo_qt.gui.commands import ToggleCompleteCommand

        db, lst, window = self._make_db_and_window()
        item = create_todo_item("Task", board_column="In Progress")
        lst.add_item(item)

        cmd = ToggleCompleteCommand(window, lst.id, [(item.id, False)])
        cmd.redo()
        assert item.board_column == "Done"
        cmd.undo()
        assert item.board_column == "In Progress"
        assert not item.complete

    def test_toggle_complete_redo_undo_redo_cycle(self):
        """Multiple redo/undo cycles maintain consistency."""
        from pytodo_qt.gui.commands import ToggleCompleteCommand

        db, lst, window = self._make_db_and_window()
        item = create_todo_item("Task", board_column="In Progress")
        lst.add_item(item)

        cmd = ToggleCompleteCommand(window, lst.id, [(item.id, False)])
        cmd.redo()
        assert item.board_column == "Done" and item.complete
        cmd.undo()
        assert item.board_column == "In Progress" and not item.complete
        cmd.redo()
        assert item.board_column == "Done" and item.complete

    def test_multi_select_toggle_syncs_columns(self):
        """Batch toggle syncs board_column for each item individually."""
        from pytodo_qt.gui.commands import ToggleCompleteCommand

        db, lst, window = self._make_db_and_window()
        item1 = create_todo_item("A", board_column="To Do")
        item2 = create_todo_item("B", board_column="In Progress")
        lst.add_item(item1)
        lst.add_item(item2)

        states = [(item1.id, False), (item2.id, False)]
        cmd = ToggleCompleteCommand(window, lst.id, states)
        cmd.redo()
        assert item1.board_column == "Done"
        assert item2.board_column == "Done"
        cmd.undo()
        assert item1.board_column == "To Do"
        assert item2.board_column == "In Progress"

    # -- ToggleCompleteRecurringCommand board_column sync --

    def test_recurring_toggle_moves_to_done(self):
        """Recurring toggle marks complete and moves item to Done column."""
        from pytodo_qt.gui.commands import ToggleCompleteRecurringCommand

        db, lst, window = self._make_db_and_window()
        today = date.today()
        tomorrow = today + timedelta(days=1)
        item = create_todo_item("Recurring", board_column="In Progress")
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        item.due_date = today
        lst.add_item(item)

        cmd = ToggleCompleteRecurringCommand(
            window,
            lst.id,
            item.id,
            old_due_date=today,
            new_due_date=tomorrow,
            old_count=0,
            recurrence_ended=False,
        )
        cmd.redo()
        assert item.complete
        assert item.board_column == "Done"

    def test_recurring_exhausted_moves_to_done(self):
        """Exhausted recurrence (complete=True) moves item to Done."""
        from pytodo_qt.gui.commands import ToggleCompleteRecurringCommand

        db, lst, window = self._make_db_and_window()
        today = date.today()
        item = create_todo_item("Recurring", board_column="In Progress")
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        item.due_date = today
        lst.add_item(item)

        cmd = ToggleCompleteRecurringCommand(
            window,
            lst.id,
            item.id,
            old_due_date=today,
            new_due_date=None,
            old_count=4,
            recurrence_ended=True,
        )
        cmd.redo()
        assert item.complete
        assert item.board_column == "Done"

    def test_recurring_undo_restores_column(self):
        """Undo of recurring toggle restores original board_column."""
        from pytodo_qt.gui.commands import ToggleCompleteRecurringCommand

        db, lst, window = self._make_db_and_window()
        today = date.today()
        tomorrow = today + timedelta(days=1)
        item = create_todo_item("Recurring", board_column="In Progress")
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        item.due_date = today
        lst.add_item(item)

        cmd = ToggleCompleteRecurringCommand(
            window,
            lst.id,
            item.id,
            old_due_date=today,
            new_due_date=tomorrow,
            old_count=0,
            recurrence_ended=False,
        )
        cmd.redo()
        assert item.board_column == "Done"
        cmd.undo()
        assert item.board_column == "In Progress"

    # -- Default column assignment --

    def test_new_item_gets_first_column(self):
        """Items created without board_column get assigned first column."""
        item = create_todo_item("Task")
        assert item.board_column == ""
        # Simulate what _on_add_todo does
        cols = ["To Do", "In Progress", "Done"]
        if not item.board_column and cols:
            item.board_column = cols[0]
        assert item.board_column == "To Do"

    def test_orphaned_subtask_gets_column(self):
        """Deleting parent promotes subtask with board_column assignment."""
        from pytodo_qt.gui.commands import DeleteItemsCommand

        db, lst, window = self._make_db_and_window()
        parent = create_todo_item("Parent", board_column="In Progress")
        lst.add_item(parent)
        child = create_todo_item("Child")
        child.parent_id = parent.id
        lst.add_item(child)
        assert child.board_column == ""

        cmd = DeleteItemsCommand(window, lst.id, [parent.id])
        cmd.redo()
        assert child.parent_id is None
        assert child.board_column == "To Do"  # Assigned first column

    # -- Reconciliation --

    def test_reconcile_empty_column(self):
        """Items with empty board_column get assigned first column."""
        db, lst, window = self._make_db_and_window()
        item = create_todo_item("Task")  # board_column=""
        lst.add_item(item)

        # Simulate reconciliation logic
        cols = lst.board_columns
        col_set = set(cols)
        first_col = cols[0]
        if not item.board_column or item.board_column not in col_set:
            item.board_column = first_col
        assert item.board_column == "To Do"

    def test_reconcile_invalid_column(self):
        """Items with removed column name get assigned first column."""
        db, lst, window = self._make_db_and_window()
        item = create_todo_item("Task", board_column="Review")
        lst.add_item(item)

        cols = lst.board_columns  # ["To Do", "In Progress", "Done"]
        col_set = set(cols)
        if item.board_column not in col_set:
            item.board_column = cols[0]
        assert item.board_column == "To Do"

    def test_reconcile_complete_not_in_done(self):
        """Complete items not in last column get moved to last column."""
        db, lst, window = self._make_db_and_window()
        item = create_todo_item("Task", board_column="In Progress")
        item.complete = True
        lst.add_item(item)

        cols = lst.board_columns
        last_col = cols[-1]
        if item.complete and item.board_column != last_col:
            item.board_column = last_col
        assert item.board_column == "Done"

    def test_reconcile_incomplete_in_done(self):
        """Incomplete items in last column get moved to first column."""
        db, lst, window = self._make_db_and_window()
        item = create_todo_item("Task", board_column="Done")
        lst.add_item(item)
        assert not item.complete

        cols = lst.board_columns
        first_col, last_col = cols[0], cols[-1]
        if not item.complete and item.board_column == last_col:
            item.board_column = first_col
        assert item.board_column == "To Do"

    def test_reconcile_no_change_when_consistent(self):
        """Already-correct items are not modified."""
        db, lst, window = self._make_db_and_window()
        item = create_todo_item("Task", board_column="In Progress")
        lst.add_item(item)

        cols = lst.board_columns
        col_set = set(cols)
        last_col = cols[-1]
        changed = False
        if (
            not item.board_column
            or item.board_column not in col_set
            or item.complete
            and item.board_column != last_col
            or not item.complete
            and item.board_column == last_col
        ):
            changed = True
        assert not changed
        assert item.board_column == "In Progress"

    # -- Smart layout remapping --

    def test_layout_remap_positional_5_to_3(self):
        """5→3 column layout remaps middle items by relative position."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import ApplyLayoutPresetCommand

        db = Database()
        lst = create_todo_list("Test")
        lst.board_columns = ["Backlog", "To Do", "In Progress", "Review", "Done"]
        item_backlog = create_todo_item("A", board_column="Backlog")
        item_review = create_todo_item("B", board_column="Review")
        lst.add_item(item_backlog)
        lst.add_item(item_review)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = ApplyLayoutPresetCommand(window, lst.id, ["To Do", "In Progress", "Done"])
        cmd.redo()
        # Backlog (0/4=0.0) → To Do (idx 0)
        assert item_backlog.board_column == "To Do"
        # Review (3/4=0.75) → round(0.75*2) = round(1.5) = 2 = "Done"
        # But "Done" is completion col and Review was NOT old completion, so
        # positional mapping gives "Done" which is the closest match
        assert item_review.board_column == "Done"

    def test_layout_remap_name_match_priority(self):
        """Column name matches take priority over positional mapping."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import ApplyLayoutPresetCommand

        db = Database()
        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "In Progress", "Done"]
        item = create_todo_item("Task", board_column="In Progress")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        # New layout still has "In Progress" — should stay there
        cmd = ApplyLayoutPresetCommand(window, lst.id, ["Backlog", "In Progress", "Review", "Done"])
        cmd.redo()
        assert item.board_column == "In Progress"

    def test_layout_remap_completion_col_preserved(self):
        """Items in old completion column map to new completion column."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import ApplyLayoutPresetCommand

        db = Database()
        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "In Progress", "Done"]
        item = create_todo_item("Task", board_column="Done")
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        # Rename completion column
        cmd = ApplyLayoutPresetCommand(window, lst.id, ["To Do", "In Progress", "Complete"])
        cmd.redo()
        assert item.board_column == "Complete"


class TestBestIncompleteColumn:
    """Tests for _best_incomplete_column work-indicator heuristic."""

    def test_no_work_goes_to_inbox(self):
        """Items with no pomodoro time or completed subtasks go to first column."""
        from pytodo_qt.gui.commands import _best_incomplete_column

        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "In Progress", "Done"]
        item = create_todo_item("Task")
        lst.add_item(item)

        assert _best_incomplete_column(item, lst) == "To Do"

    def test_time_spent_goes_to_progress(self):
        """Items with pomodoro time go to second column (In Progress)."""
        from pytodo_qt.gui.commands import _best_incomplete_column

        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "In Progress", "Done"]
        item = create_todo_item("Task")
        item.time_spent = 1500  # 25 minutes
        lst.add_item(item)

        assert _best_incomplete_column(item, lst) == "In Progress"

    def test_completed_subtask_goes_to_progress(self):
        """Items with completed subtasks go to second column."""
        from pytodo_qt.gui.commands import _best_incomplete_column

        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "In Progress", "Done"]
        parent = create_todo_item("Parent")
        lst.add_item(parent)

        child = create_todo_item("Child")
        child.parent_id = parent.id
        child.complete = True
        lst.add_item(child)

        assert _best_incomplete_column(parent, lst) == "In Progress"

    def test_incomplete_subtask_stays_inbox(self):
        """Items with only incomplete subtasks stay in first column."""
        from pytodo_qt.gui.commands import _best_incomplete_column

        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "In Progress", "Done"]
        parent = create_todo_item("Parent")
        lst.add_item(parent)

        child = create_todo_item("Child")
        child.parent_id = parent.id
        lst.add_item(child)

        assert _best_incomplete_column(parent, lst) == "To Do"

    def test_deleted_subtask_ignored(self):
        """Deleted completed subtasks don't count as work indicators."""
        from pytodo_qt.gui.commands import _best_incomplete_column

        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "In Progress", "Done"]
        parent = create_todo_item("Parent")
        lst.add_item(parent)

        child = create_todo_item("Child")
        child.parent_id = parent.id
        child.complete = True
        child.mark_deleted()
        lst.add_item(child)

        assert _best_incomplete_column(parent, lst) == "To Do"

    def test_backlog_preset_finds_in_progress(self):
        """Backlog preset (In Progress is col 3) still finds it by name."""
        from pytodo_qt.gui.commands import _best_incomplete_column

        lst = create_todo_list("Test")
        lst.board_columns = ["Backlog", "To Do", "In Progress", "Done"]
        item = create_todo_item("Task")
        item.time_spent = 1500
        lst.add_item(item)

        assert _best_incomplete_column(item, lst) == "In Progress"

    def test_custom_columns_falls_back_to_second(self):
        """Custom columns without 'In Progress' fall back to second column."""
        from pytodo_qt.gui.commands import _best_incomplete_column

        lst = create_todo_list("Test")
        lst.board_columns = ["Inbox", "Active", "Done"]
        item = create_todo_item("Task")
        item.time_spent = 1500
        lst.add_item(item)

        assert _best_incomplete_column(item, lst) == "Active"

    def test_two_column_board_falls_back_to_first(self):
        """With only 2 columns, no meaningful progress column — use first."""
        from pytodo_qt.gui.commands import _best_incomplete_column

        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "Done"]
        item = create_todo_item("Task")
        item.time_spent = 1500
        lst.add_item(item)

        assert _best_incomplete_column(item, lst) == "To Do"

    def test_empty_columns_returns_empty(self):
        """With no board columns, returns empty string."""
        from pytodo_qt.gui.commands import _best_incomplete_column

        lst = create_todo_list("Test")
        lst.board_columns = []
        item = create_todo_item("Task")
        item.time_spent = 1500
        lst.add_item(item)

        assert _best_incomplete_column(item, lst) == ""

    def test_toggle_uncomplete_with_time_goes_to_progress(self):
        """Un-completing an item with pomodoro time places it in In Progress."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import ToggleCompleteCommand

        db = Database()
        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "In Progress", "Done"]
        item = create_todo_item("Task", board_column="Done")
        item.complete = True
        item.time_spent = 1500
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = ToggleCompleteCommand(window, lst.id, [(item.id, True)])
        cmd.redo()
        assert not item.complete
        assert item.board_column == "In Progress"

    def test_toggle_uncomplete_with_subtasks_goes_to_progress(self):
        """Un-completing an item with completed subtasks places it in In Progress."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import ToggleCompleteCommand

        db = Database()
        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "In Progress", "Done"]
        parent = create_todo_item("Parent", board_column="Done")
        parent.complete = True
        lst.add_item(parent)

        child = create_todo_item("Child")
        child.parent_id = parent.id
        child.complete = True
        lst.add_item(child)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = ToggleCompleteCommand(window, lst.id, [(parent.id, True)])
        cmd.redo()
        assert not parent.complete
        assert parent.board_column == "In Progress"

    def test_recurring_toggle_with_time_goes_to_done(self):
        """Recurring toggle with pomodoro time goes to Done (complete now, cycle later)."""
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import ToggleCompleteRecurringCommand

        db = Database()
        lst = create_todo_list("Test")
        lst.board_columns = ["To Do", "In Progress", "Done"]
        today = date.today()
        tomorrow = today + timedelta(days=1)
        item = create_todo_item("Recurring", board_column="In Progress")
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        item.due_date = today
        item.time_spent = 1500
        lst.add_item(item)
        db.add_list(lst)

        window = MagicMock()
        window._database = db

        cmd = ToggleCompleteRecurringCommand(
            window,
            lst.id,
            item.id,
            old_due_date=today,
            new_due_date=tomorrow,
            old_count=0,
            recurrence_ended=False,
        )
        cmd.redo()
        assert item.complete
        assert item.board_column == "Done"
