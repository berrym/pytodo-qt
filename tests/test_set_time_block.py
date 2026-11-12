"""Tests for the 'Set Time Block...' action on the main window.

The method is tested unbound against a mock ``MainWindow`` — the pattern
``test_detail_panel_toggle.py`` uses — to avoid the cost of a full
MainWindow + Database + config stack.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from pytodo_qt.core.config import AppConfig
from pytodo_qt.core.models import TodoItem, TodoList
from pytodo_qt.gui.main_window import MainWindow


def _window_with(item: TodoItem) -> MagicMock:
    todo_list = TodoList(name="Tasks")
    todo_list.add_item(item)
    window = MagicMock()
    window._database.active_list = todo_list
    window._config_manager.config = AppConfig()
    window.tr.side_effect = lambda text: text
    return window


def _pushed(window: MagicMock) -> list[tuple[str, object]]:
    """The (field, value) pairs of the commands pushed to the undo stack."""
    return [
        (call.args[0]._field_name, call.args[0]._new_value)
        for call in window._undo_stack.push.call_args_list
    ]


def _choose(window: MagicMock, item: TodoItem, label: str) -> None:
    with patch("pytodo_qt.gui.main_window.QInputDialog.getItem", return_value=(label, True)):
        MainWindow._on_set_time_block(window, item.id)


class TestSetTimeBlock:
    def test_block_on_a_dateless_item_also_sets_a_date(self):
        item = TodoItem(reminder="walk")
        window = _window_with(item)

        _choose(window, item, "Evening")

        pushed = dict(_pushed(window))
        assert pushed["due_time_block"] == "evening"
        assert pushed["due_date"] in (date.today(), date.today() + timedelta(days=1))

    def test_block_and_date_are_one_undo_step(self):
        item = TodoItem(reminder="walk")
        window = _window_with(item)

        _choose(window, item, "Evening")

        window._undo_stack.beginMacro.assert_called_once()
        window._undo_stack.endMacro.assert_called_once()

    def test_existing_date_is_kept(self):
        item = TodoItem(reminder="walk", due_date=date(2030, 1, 15))
        window = _window_with(item)

        _choose(window, item, "Evening")

        assert _pushed(window) == [("due_time_block", "evening")]
        window._undo_stack.beginMacro.assert_not_called()

    def test_clearing_the_block_sets_no_date(self):
        item = TodoItem(reminder="walk", due_time_block="evening")
        window = _window_with(item)

        _choose(window, item, "None")

        assert _pushed(window) == [("due_time_block", None)]

    def test_unchanged_block_pushes_nothing(self):
        item = TodoItem(reminder="walk", due_time_block="evening")
        window = _window_with(item)

        _choose(window, item, "Evening")

        window._undo_stack.push.assert_not_called()
