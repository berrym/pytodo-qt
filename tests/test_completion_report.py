"""The status line said after tasks are ticked or unticked (#126).

A tick moves a task out of view: finished tasks sort to the bottom of
the list, on the board a task goes to the last column, and a filter can
hide it. The status bar names the task, says where it went and how to
take the tick back. A tick is one undo step, whatever it was made with.

The window's own methods are driven on a stand-in with a real list view
and undo stack, as tests/test_notification_actions.py does.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QItemSelectionModel
from PyQt6.QtGui import QUndoStack
from PyQt6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from pytodo_qt.core.models import Database, create_todo_item, create_todo_list
from pytodo_qt.gui.completion_report import (
    MESSAGE_MS,
    NAME_LIMIT,
    SHORTEST_NAME,
    Ticked,
    completion_line,
    fitted_line,
    short_name,
)
from pytodo_qt.gui.main_window import MainWindow
from pytodo_qt.gui.widgets.search_filter import FilterState
from pytodo_qt.gui.widgets.status_bar import StatusBarWidget
from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

_NAMES = ("Alpha", "Bravo", "Charlie", "Delta", "Echo")

_BOUND = (
    "_completion_command",
    "_completion_snapshot",
    "_report_completion",
    "_completion_place",
    "_on_toggle_todo",
    "_active_view_widget",
    "_on_item_column_changed",
    "_on_detail_panel_subtask_toggle",
)

LIST_VIEW, BOARD, CALENDAR = 0, 1, 2


@pytest.fixture()
def window(qtbot):
    """A stand-in for the main window: the lists Home and Work, the list
    view, the board and the calendar in a stack, a status filter."""
    db = Database()
    home = create_todo_list("Home")
    for name in _NAMES:
        home.add_item(create_todo_item(name))
    work = create_todo_list("Work")
    work.add_item(create_todo_item("Write the report"))
    db.add_list(home)
    db.add_list(work)
    db.set_active_list(home.id)

    host = QWidget()
    qtbot.addWidget(host)
    stack = QStackedWidget()
    table = TodoTableWidget()
    stack.addWidget(table)
    stack.addWidget(QWidget())
    stack.addWidget(QWidget())
    QVBoxLayout(host).addWidget(stack)
    host.resize(900, 400)
    host.show()
    qtbot.waitExposed(host)

    status = {"value": 0}
    stand_in = SimpleNamespace(
        _database=db,
        _undo_stack=QUndoStack(),
        _save_database=MagicMock(),
        todo_table=table,
        kanban_board=stack.widget(BOARD),
        _view_stack=stack,
        search_filter=SimpleNamespace(get_filter=lambda: FilterState(status=status["value"])),
        status_bar_widget=MagicMock(),
        _undo_native="⌘Z",
        tr=lambda text: text,
        home=home,
        work=work,
        status=status,
        host=host,
    )

    def refresh() -> None:
        table.set_filter(FilterState(status=status["value"]))
        table.set_list(db.active_list)

    stand_in._refresh_ui = refresh
    for name in _BOUND:
        setattr(stand_in, name, getattr(MainWindow, name).__get__(stand_in))
    refresh()
    return stand_in


def _said(window) -> list[str]:
    return [call.args[0] for call in window.status_bar_widget.show_message.call_args_list]


def _item(todo_list, name: str):
    return next(item for item in todo_list.items.values() if item.reminder == name)


def _select(window, *names: str) -> None:
    table = window.todo_table
    selection = table.selectionModel()
    assert selection is not None
    table.clearSelection()
    for name in names:
        item_id = _item(window.home, name).id
        index = table.model().index(table.rows_of([item_id])[item_id], 1)
        selection.select(
            index,
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )


def _tick(window, *names: str) -> None:
    """Tick or untick tasks of the list shown, as Toggle Complete does."""
    _select(window, *names)
    window._on_toggle_todo()


# --- The line ---------------------------------------------------------------


class TestTheLine:
    def test_one_task_done(self):
        line = completion_line(
            [Ticked("check snooze", True)], "moved to the finished tasks", "⌘Z to undo"
        )
        assert line == 'Done: "check snooze" — moved to the finished tasks · ⌘Z to undo'

    def test_one_task_not_done(self):
        line = completion_line([Ticked("check snooze", False)], "moved back to the open tasks")
        assert line == 'Not done: "check snooze" — moved back to the open tasks'

    def test_several_tasks_are_counted(self):
        line = completion_line([Ticked("a", True), Ticked("b", True), Ticked("c", True)])
        assert line == "Done: 3 tasks"

    def test_ticked_and_unticked_together_are_named_apart(self):
        line = completion_line([Ticked("a", True), Ticked("b", False)], "", "Ctrl+Z to undo")
        assert line == 'Done: "a" · Not done: "b" · Ctrl+Z to undo'

    def test_a_long_name_is_cut_short(self):
        name = "Renew the passport and book the photo appointment first"
        shown = short_name(name)
        assert len(shown) == NAME_LIMIT
        assert shown.endswith("…")
        assert name.startswith(shown[:-1])

    def test_a_name_of_the_limit_is_whole(self):
        name = "x" * NAME_LIMIT
        assert short_name(name) == name

    def test_line_breaks_in_a_name_are_spaces(self):
        assert short_name("pack\n  the   bags") == "pack the bags"


class TestFittingTheRoom:
    """Names are cut shorter so that where the task went and how to undo
    stay in view; the rest of the line is never cut by the fitting."""

    LONG = "Renew the passport and book the photo appointment first"

    def test_a_line_that_fits_keeps_the_name_to_its_limit(self):
        line = fitted_line(
            [Ticked(self.LONG, True)], "moved to the finished tasks", "⌘Z to undo", lambda _: True
        )
        assert line == completion_line(
            [Ticked(self.LONG, True)], "moved to the finished tasks", "⌘Z to undo"
        )

    def test_the_name_is_cut_until_the_line_fits(self):
        room = 70
        line = fitted_line(
            [Ticked(self.LONG, True)],
            "moved to the finished tasks",
            "⌘Z to undo",
            lambda text: len(text) <= room,
        )
        assert len(line) <= room
        assert line.endswith('…" — moved to the finished tasks · ⌘Z to undo')
        # As long a name as the room allows.
        largest = max(
            limit
            for limit in range(SHORTEST_NAME, NAME_LIMIT + 1)
            if len(
                completion_line(
                    [Ticked(self.LONG, True)], "moved to the finished tasks", "⌘Z to undo", limit
                )
            )
            <= room
        )
        assert line == completion_line(
            [Ticked(self.LONG, True)], "moved to the finished tasks", "⌘Z to undo", largest
        )

    @pytest.mark.parametrize("short_of_room", [0, 5, 1000])
    def test_a_name_is_never_cut_below_the_shortest(self, short_of_room):
        """Not even where a shorter name would make the line fit."""
        shortest = completion_line(
            [Ticked(self.LONG, True)], 'in "Work"', "⌘Z to undo", SHORTEST_NAME
        )
        room = len(shortest) - short_of_room - 1

        line = fitted_line(
            [Ticked(self.LONG, True)], 'in "Work"', "⌘Z to undo", lambda text: len(text) <= room
        )

        assert line == shortest

    def test_two_names_are_cut_alike(self):
        line = fitted_line(
            [Ticked(self.LONG, True), Ticked(self.LONG, False)],
            "",
            "⌘Z to undo",
            lambda text: len(text) <= 80,
        )
        done, not_done = line.split(" · ")[:2]
        assert done.removeprefix("Done: ") == not_done.removeprefix("Not done: ")


# --- Where the task went ----------------------------------------------------


class TestInTheListView:
    def test_a_task_that_moved_is_with_the_finished_tasks(self, window):
        _tick(window, "Bravo")

        assert _said(window) == ['Done: "Bravo" — moved to the finished tasks · ⌘Z to undo']

    def test_a_task_that_stayed_in_its_row_is_named_only(self, window):
        """The last open task becomes the first finished one, in the same row."""
        _tick(window, "Echo")

        assert _said(window) == ['Done: "Echo" · ⌘Z to undo']

    def test_unticked_it_moves_back_to_the_open_tasks(self, window):
        _tick(window, "Bravo")
        _tick(window, "Bravo")

        assert _said(window)[-1] == (
            'Not done: "Bravo" — moved back to the open tasks · ⌘Z to undo'
        )

    def test_several_tasks(self, window):
        _tick(window, "Alpha", "Bravo")

        assert _said(window) == ["Done: 2 tasks — moved to the finished tasks · ⌘Z to undo"]

    def test_ticked_and_unticked_together_say_no_place(self, window):
        _tick(window, "Bravo")
        _tick(window, "Alpha", "Bravo")

        assert _said(window)[-1] == 'Done: "Alpha" · Not done: "Bravo" · ⌘Z to undo'

    def test_a_long_name_is_cut_to_the_room_in_the_status_bar(self, window):
        long_name = "Book the passport renewal and the photo appointment first"
        _item(window.home, "Bravo").reminder = long_name
        window._refresh_ui()
        window.status_bar_widget.message_fits = lambda line: len(line) <= 64

        _tick(window, long_name)

        line = _said(window)[0]
        assert len(line) <= 64
        assert line.startswith('Done: "Book the')
        assert line.endswith('…" — moved to the finished tasks · ⌘Z to undo')

    def test_the_line_stays_ten_seconds(self, window):
        _tick(window, "Bravo")

        assert window.status_bar_widget.show_message.call_args.args[1] == MESSAGE_MS == 10_000


class TestPrecedence:
    """Another list, then a status filter, then the board or list view."""

    def test_a_task_hidden_by_the_active_filter(self, window):
        window.status["value"] = 1
        window._refresh_ui()

        _tick(window, "Bravo")

        assert _said(window) == ['Done: "Bravo" — hidden by the Active filter · ⌘Z to undo']

    def test_a_task_hidden_by_the_completed_filter(self, window):
        _item(window.home, "Bravo").complete = True
        window.status["value"] = 2
        window._refresh_ui()

        _tick(window, "Bravo")

        assert _said(window) == ['Not done: "Bravo" — hidden by the Completed filter · ⌘Z to undo']

    def test_a_filter_that_still_shows_it_is_not_named(self, window):
        window.status["value"] = 2
        window._refresh_ui()
        _item(window.home, "Bravo").complete = True
        window._refresh_ui()

        _tick(window, "Bravo")
        command = window._completion_command(window.home, [_item(window.home, "Alpha").id])
        assert command is not None
        window._undo_stack.push(command)

        assert "filter" not in _said(window)[-1]

    def test_another_list_comes_before_a_filter(self, window):
        window.status["value"] = 1
        report = _item(window.work, "Write the report")

        command = window._completion_command(window.work, [report.id])
        assert command is not None
        window._undo_stack.push(command)

        assert _said(window) == ['Done: "Write the report" — in "Work" · ⌘Z to undo']

    def test_on_the_board_the_column_it_went_to(self, window):
        window._view_stack.setCurrentIndex(BOARD)

        window._on_item_column_changed(_item(window.home, "Bravo").id, "Done")

        assert _said(window) == ['Done: "Bravo" — moved to "Done" · ⌘Z to undo']

    def test_on_the_board_a_task_taken_out_of_the_last_column(self, window):
        window._view_stack.setCurrentIndex(BOARD)
        bravo = _item(window.home, "Bravo")
        window._on_item_column_changed(bravo.id, "Done")

        window._on_item_column_changed(bravo.id, "To Do")

        assert _said(window)[-1] == 'Not done: "Bravo" — moved to "To Do" · ⌘Z to undo'

    def test_on_the_board_a_card_that_stays_in_its_column_names_none(self, window):
        """A task already in the last column, not yet done, is ticked there."""
        window._view_stack.setCurrentIndex(BOARD)
        bravo = _item(window.home, "Bravo")
        bravo.board_column = "Done"

        command = window._completion_command(window.home, [bravo.id])
        assert command is not None
        window._undo_stack.push(command)

        assert bravo.board_column == "Done"
        assert _said(window) == ['Done: "Bravo" · ⌘Z to undo']

    def test_a_move_between_other_columns_says_nothing(self, window):
        window._view_stack.setCurrentIndex(BOARD)

        window._on_item_column_changed(_item(window.home, "Bravo").id, "In Progress")

        assert _said(window) == []

    def test_in_the_calendar_no_place(self, window):
        window._view_stack.setCurrentIndex(CALENDAR)
        bravo = _item(window.home, "Bravo")

        command = window._completion_command(window.home, [bravo.id])
        assert command is not None
        window._undo_stack.push(command)

        assert _said(window) == ['Done: "Bravo" · ⌘Z to undo']


# --- Undo -------------------------------------------------------------------


class TestUndo:
    def test_undo_says_it_the_other_way_without_the_hint(self, window):
        _tick(window, "Bravo")

        window._undo_stack.undo()

        assert _said(window)[-1] == 'Not done: "Bravo" — moved back to the open tasks'

    def test_redo_says_it_again(self, window):
        _tick(window, "Bravo")
        window._undo_stack.undo()

        window._undo_stack.redo()

        assert _said(window)[-1] == 'Done: "Bravo" — moved to the finished tasks · ⌘Z to undo'

    def test_a_recurring_and_an_ordinary_task_are_one_undo_step(self, window):
        alpha = _item(window.home, "Alpha")
        alpha.due_date = date(2026, 11, 23)
        alpha.recurrence_type = "daily"
        alpha.recurrence_interval = 1
        bravo = _item(window.home, "Bravo")
        window._refresh_ui()

        _tick(window, "Alpha", "Bravo")

        assert window._undo_stack.count() == 1
        assert (alpha.complete, bravo.complete) == (True, True)
        assert _said(window) == ["Done: 2 tasks — moved to the finished tasks · ⌘Z to undo"]
        window._undo_stack.undo()
        assert (alpha.complete, bravo.complete) == (False, False)
        assert alpha.recurrence_count == 0

    def test_a_board_move_into_the_last_column_is_one_undo_step(self, window):
        window._view_stack.setCurrentIndex(BOARD)
        bravo = _item(window.home, "Bravo")
        bravo.board_column = "In Progress"

        window._on_item_column_changed(bravo.id, "Done")
        window._undo_stack.undo()

        assert window._undo_stack.count() == 1
        assert (bravo.complete, bravo.board_column) == (False, "In Progress")


class TestFromTheDetailPanel:
    def test_a_subtask_ticked_there(self, window):
        alpha = _item(window.home, "Alpha")
        step = create_todo_item("Buy stamps")
        step.parent_id = alpha.id
        window.home.add_item(step)
        window._refresh_ui()

        window._on_detail_panel_subtask_toggle(step.id, True)

        assert step.complete is True
        assert window._undo_stack.count() == 1
        assert _said(window)[-1].startswith('Done: "Buy stamps"')
        assert _said(window)[-1].endswith("· ⌘Z to undo")


# --- The status bar ---------------------------------------------------------


class TestTheStatusBar:
    def test_a_newer_message_is_not_cleared_by_the_older_ones_time(self, qtbot):
        bar = StatusBarWidget()
        qtbot.addWidget(bar)

        bar.show_message("older", 50)
        bar.show_message("newer", MESSAGE_MS)
        qtbot.wait(150)
        QApplication.processEvents()

        assert bar._message_label.text() == "newer"

    def test_the_message_is_cleared_after_its_time(self, qtbot):
        bar = StatusBarWidget()
        qtbot.addWidget(bar)

        bar.show_message("Done", 50)

        qtbot.waitUntil(lambda: bar._message_label.text() == "", timeout=1000)

    def test_a_long_message_does_not_widen_the_window(self, qtbot):
        bar = StatusBarWidget()
        qtbot.addWidget(bar)
        least = bar.minimumSizeHint().width()

        bar.show_message("Done: " + "W" * 200, MESSAGE_MS)

        assert bar.minimumSizeHint().width() == least

    def test_a_message_wider_than_its_room_ends_with_an_ellipsis(self, qtbot):
        bar = StatusBarWidget()
        qtbot.addWidget(bar)
        bar.resize(1100, bar.sizeHint().height())
        bar.show()
        qtbot.waitExposed(bar)
        message = "Done: " + "W" * 200

        bar.show_message(message, MESSAGE_MS)
        QApplication.processEvents()

        assert not bar.message_fits(message)
        assert bar._message_label.displayed_text().endswith("…")
        assert bar._message_label.toolTip() == message
        assert bar._message_label.text() == message

    def test_the_message_has_the_room_between_the_two_sections(self, qtbot):
        """Its room grows with the window, whatever message it last had."""
        bar = StatusBarWidget()
        qtbot.addWidget(bar)
        bar.show()
        qtbot.waitExposed(bar)
        rooms = []
        for width in (1100, 1400):
            bar.resize(width, bar.sizeHint().height())
            bar.show_message("Done", MESSAGE_MS)
            QApplication.processEvents()
            rooms.append(bar._message_label.width())

        assert rooms[1] - rooms[0] == 300

    def test_a_message_fits_as_wide_as_its_room(self, qtbot):
        """Measured against the room, as each platform's fonts make it."""
        bar = StatusBarWidget()
        qtbot.addWidget(bar)
        bar.resize(1400, bar.sizeHint().height())
        bar.show()
        qtbot.waitExposed(bar)
        bar.show_message("Done", MESSAGE_MS)
        QApplication.processEvents()
        label = bar._message_label
        assert label.width() > 0
        widest = ""
        while label.fontMetrics().horizontalAdvance(widest + "x") <= label.width():
            widest += "x"

        assert bar.message_fits(widest)
        assert not bar.message_fits(widest + "x")

    def test_the_tooltip_goes_with_the_message(self, qtbot):
        bar = StatusBarWidget()
        qtbot.addWidget(bar)

        bar.show_message("Done", 50)
        qtbot.waitUntil(lambda: bar._message_label.text() == "", timeout=1000)

        assert bar._message_label.toolTip() == ""
