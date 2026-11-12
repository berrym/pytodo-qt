"""Tests for dropping a task onto the calendar.

The handler is tested unbound against a mock ``MainWindow`` — the pattern
``test_detail_panel_toggle.py`` uses — to avoid the cost of a full
MainWindow + Database + config stack.
"""

from __future__ import annotations

from datetime import date, time
from unittest.mock import MagicMock

from pytodo_qt.core.models import TodoItem, TodoList
from pytodo_qt.gui.main_window import MainWindow

TARGET = date(2030, 1, 15)


def _window_with(item: TodoItem) -> MagicMock:
    todo_list = TodoList(name="Tasks")
    todo_list.add_item(item)
    window = MagicMock()
    window._refreshing = False
    window._database.active_list = todo_list
    # The forward clamp reads the wall clock; pass the dropped time through.
    window._clamp_drop_due_time_forward.side_effect = lambda _item, _date, due_time: due_time
    return window


def _pushed(window: MagicMock) -> list[str]:
    return [type(call.args[0]).__name__ for call in window._undo_stack.push.call_args_list]


def _field_commands(window: MagicMock) -> list[tuple[str, object]]:
    return [
        (call.args[0]._field_name, call.args[0]._new_value)
        for call in window._undo_stack.push.call_args_list
        if type(call.args[0]).__name__ == "SetFieldCommand"
    ]


class TestDropOntoTheCalendar:
    def test_drop_on_an_hour_replaces_the_time_block(self):
        item = TodoItem(reminder="walk", due_date=date(2030, 1, 14), due_time_block="afternoon")
        window = _window_with(item)

        MainWindow._on_date_and_time_dropped(window, item.id, TARGET, time(10, 0))

        assert _field_commands(window) == [("due_time_block", None)]
        assert _pushed(window)[:2] == ["EditDueDateCommand", "EditDueTimeCommand"]

    def test_drop_on_the_all_day_row_keeps_the_time_block(self):
        item = TodoItem(reminder="walk", due_date=date(2030, 1, 14), due_time_block="afternoon")
        window = _window_with(item)

        MainWindow._on_date_and_time_dropped(window, item.id, TARGET, None)

        assert _field_commands(window) == []

    def test_item_without_a_block_is_unaffected(self):
        item = TodoItem(reminder="walk", due_date=date(2030, 1, 14))
        window = _window_with(item)

        MainWindow._on_date_and_time_dropped(window, item.id, TARGET, time(10, 0))

        assert _field_commands(window) == []

    def test_the_drop_is_one_undo_step(self):
        item = TodoItem(reminder="walk", due_date=date(2030, 1, 14), due_time_block="afternoon")
        window = _window_with(item)

        MainWindow._on_date_and_time_dropped(window, item.id, TARGET, time(10, 0))

        window._undo_stack.beginMacro.assert_called_once()
        window._undo_stack.endMacro.assert_called_once()
