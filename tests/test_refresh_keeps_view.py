"""A refresh of the list view and of the board keeps what is on screen.

The list view makes its rows again at every refresh, and a refresh
arrives without anything being done in the window: once a minute while a
task is due today at a set time, at a sync, at a change from the web
page. The scroll position, the selected rows, the current cell and the
keyboard focus are put back; a refresh waits while a row is in use; and a
name is saved when its field is left.
"""

from __future__ import annotations

from datetime import date, time
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pytodo_qt.core.models import TodoList, create_todo_item, create_todo_list
from pytodo_qt.gui.main_window import MainWindow
from pytodo_qt.gui.widgets.kanban_board import KanbanBoardWidget
from pytodo_qt.gui.widgets.todo_table import (
    _HELD_REFRESH_POLL_MS,
    ReminderEdit,
    TodoTableWidget,
)

_ROWS = 50
_LONGER_THAN_A_POLL = _HELD_REFRESH_POLL_MS * 3


def _numbered_list(count: int = _ROWS) -> TodoList:
    todo_list = create_todo_list("Numbered")
    for number in range(count):
        todo_list.add_item(create_todo_item(f"task {number:02d}"))
    return todo_list


@pytest.fixture()
def todo_list() -> TodoList:
    return _numbered_list()


@pytest.fixture()
def table(qtbot, todo_list) -> TodoTableWidget:
    widget = TodoTableWidget()
    qtbot.addWidget(widget)
    widget.resize(900, 400)
    widget.set_list(todo_list)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _edit(table: TodoTableWidget, row: int) -> ReminderEdit:
    container = table.cellWidget(row, 1)
    assert container is not None
    edit = container.findChild(ReminderEdit)
    assert edit is not None
    return edit


def _edit_of(table: TodoTableWidget, text: str) -> ReminderEdit:
    for row in range(table.rowCount()):
        edit = _edit(table, row)
        if edit.stored_text == text:
            return edit
    raise AssertionError(f"no row named {text!r}")


def _top_task(table: TodoTableWidget) -> str:
    return _edit(table, table.rowAt(0)).stored_text


def _scroll_to_the_middle(table: TodoTableWidget) -> None:
    bar = table.verticalScrollBar()
    assert bar is not None and bar.maximum() > 0
    bar.setValue(bar.maximum() // 2 + 3)
    QApplication.processEvents()
    assert table.rowAt(0) > 0


def _focused(table: TodoTableWidget):
    return table.window().focusWidget()


def _window_with_a_search_field(qtbot, todo_list):
    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    search = QLineEdit()
    table = TodoTableWidget()
    layout.addWidget(search)
    layout.addWidget(table)
    window.resize(900, 400)
    table.set_list(todo_list)
    window.show()
    qtbot.waitExposed(window)
    return window, search, table


_SCROLL_MODES = [
    QAbstractItemView.ScrollMode.ScrollPerItem,
    QAbstractItemView.ScrollMode.ScrollPerPixel,
]


class TestScrollPosition:
    @pytest.mark.parametrize("mode", _SCROLL_MODES)
    def test_a_refresh_leaves_the_list_where_it_is(self, table, mode):
        table.setVerticalScrollMode(mode)
        _scroll_to_the_middle(table)
        bar = table.verticalScrollBar()
        position, top = bar.value(), _top_task(table)

        table.refresh()

        assert bar.value() == position
        assert _top_task(table) == top

    @pytest.mark.parametrize("mode", _SCROLL_MODES)
    def test_the_task_at_the_top_stays_there_when_one_is_added_above(self, table, todo_list, mode):
        table.setVerticalScrollMode(mode)
        _scroll_to_the_middle(table)
        top = _top_task(table)

        todo_list.add_item(create_todo_item("task 00 and a half"))
        table.refresh()

        assert _top_task(table) == top

    def test_the_same_row_is_at_the_top_when_its_task_is_gone(self, table, todo_list):
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        _scroll_to_the_middle(table)
        top_row = table.rowAt(0)
        top_id = table.get_item_id_at_row(top_row)

        todo_list.get_item(top_id).deleted = True
        table.refresh()

        assert table.rowAt(0) == top_row

    def test_another_list_is_shown_from_its_top(self, table):
        _scroll_to_the_middle(table)
        table.selectRow(table.rowAt(0) + 1)

        table.set_list(_numbered_list())

        assert table.verticalScrollBar().value() == 0
        assert table.get_selected_item_ids() == []

    def test_the_same_list_set_again_stays_where_it_is(self, table, todo_list):
        _scroll_to_the_middle(table)
        top = _top_task(table)

        table.set_list(todo_list)

        assert _top_task(table) == top


class TestSelection:
    def test_selected_rows_stay_selected(self, table):
        table.selectRow(3)
        chosen = table.get_selected_item_ids()

        table.refresh()

        assert table.get_selected_item_ids() == chosen
        assert table.selectionModel().isRowSelected(3)

    def test_several_selected_rows_stay_selected(self, table):
        table.selectAll()
        table.refresh()
        assert len(table.get_selected_item_ids()) == _ROWS

    def test_a_refresh_that_keeps_the_selection_reports_no_change(self, table):
        table.selectRow(3)
        reported: list[object] = []
        table.item_selected.connect(reported.append)

        table.refresh()

        assert reported == []

    def test_a_selected_task_that_is_gone_is_reported(self, table, todo_list):
        table.selectRow(3)
        todo_list.get_item(table.get_selected_item_ids()[0]).deleted = True
        reported: list[object] = []
        table.item_selected.connect(reported.append)

        table.refresh()

        assert table.get_selected_item_ids() == []
        assert reported == [None]

    def test_the_selection_follows_a_task_that_moves(self, table, todo_list):
        table.selectRow(3)
        chosen = table.get_selected_item_ids()

        todo_list.add_item(create_todo_item("task 00 and a half"))
        table.refresh()

        assert table.get_selected_item_ids() == chosen
        assert table.selectionModel().isRowSelected(4)

    def test_the_current_cell_is_kept(self, table):
        table.setFocus()
        table.setCurrentCell(5, 2)
        table.refresh()
        current = table.currentIndex()
        assert (current.row(), current.column()) == (5, 2)


class TestKeyboardFocus:
    def test_the_name_field_in_use_has_the_focus_again(self, table):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setCursorPosition(3)

        table.refresh()

        again = _edit(table, 4)
        assert again is not edit
        assert _focused(table) is again
        assert again.cursorPosition() == 3

    def test_selected_text_in_the_name_field_is_selected_again(self, table):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setSelection(1, 3)

        table.refresh()

        assert _edit(table, 4).selectedText() == "ask"

    def test_the_priority_box_in_use_has_the_focus_again(self, table):
        combo = table.cellWidget(4, 0)
        combo.setFocus()

        table.refresh()

        assert _focused(table) is table.cellWidget(4, 0)

    def test_a_refresh_does_not_take_the_focus_into_the_table(self, qtbot, todo_list):
        """A current cell in the priority column gives its box the focus.
        With the focus elsewhere in the window, as in the search field,
        that cell is not made the current one again."""
        window, search, table = _window_with_a_search_field(qtbot, todo_list)
        table.selectRow(3)
        search.setFocus()
        assert window.focusWidget() is search

        table.refresh()

        assert window.focusWidget() is search
        assert table.selectionModel().isRowSelected(3)

    def test_the_current_cell_is_kept_with_the_focus_elsewhere(self, qtbot, todo_list):
        window, search, table = _window_with_a_search_field(qtbot, todo_list)
        table.setCurrentCell(5, 2)
        search.setFocus()

        table.refresh()

        current = table.currentIndex()
        assert (current.row(), current.column()) == (5, 2)
        assert window.focusWidget() is search

    def test_typed_text_is_carried_into_the_new_row(self, table):
        """A refresh that follows something done in the window does not
        wait, and the name being typed is still there after it."""
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("half typed")
        edit.setCursorPosition(4)

        table.refresh()

        again = _edit(table, 4)
        assert again.text() == "half typed"
        assert again.stored_text == "task 04"
        assert again.has_unsaved_text()
        assert again.cursorPosition() == 4
        assert _focused(table) is again

    def test_carrying_typed_text_over_saves_nothing(self, table):
        saved: list[tuple[object, str]] = []
        table.item_reminder_changed.connect(lambda item_id, text: saved.append((item_id, text)))
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("half typed")

        table.refresh()
        QTest.qWait(20)

        assert saved == []


class TestRefreshWaits:
    def test_a_background_refresh_waits_while_a_name_is_typed(self, table, todo_list):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("half typed")
        todo_list.add_item(create_todo_item("task 99"))

        table.set_list(todo_list, background=True)

        assert _edit(table, 4) is edit
        assert edit.text() == "half typed"
        assert table.rowCount() == _ROWS

    def test_it_goes_on_waiting(self, table):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("half typed")

        table.refresh(background=True)
        QTest.qWait(_LONGER_THAN_A_POLL)

        assert _edit(table, 4) is edit

    def test_the_waiting_refresh_is_carried_out_when_the_name_is_given_up(
        self, qtbot, table, todo_list
    ):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("half typed")
        todo_list.add_item(create_todo_item("task 99"))
        table.refresh(background=True)

        QTest.keyClick(edit, Qt.Key.Key_Escape)

        qtbot.waitUntil(lambda: table.rowCount() == _ROWS + 1, timeout=2000)
        assert _edit(table, 4).text() == "task 04"

    def test_the_waiting_refresh_is_carried_out_when_the_field_is_left(
        self, qtbot, table, todo_list
    ):
        saved: list[str] = []
        table.item_reminder_changed.connect(lambda _id, text: saved.append(text))
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("typed to the end")
        todo_list.add_item(create_todo_item("task 99"))
        table.refresh(background=True)

        _edit(table, 6).setFocus()

        qtbot.waitUntil(lambda: table.rowCount() == _ROWS + 1, timeout=2000)
        assert saved == ["typed to the end"]

    def test_a_background_refresh_does_not_wait_for_a_field_with_its_stored_name(
        self, table, todo_list
    ):
        edit = _edit(table, 4)
        edit.setFocus()
        todo_list.add_item(create_todo_item("task 99"))

        table.refresh(background=True)

        assert table.rowCount() == _ROWS + 1

    def test_a_refresh_waits_while_a_priority_popup_is_open(self, qtbot, table, todo_list):
        combo = table.cellWidget(4, 0)
        combo.showPopup()
        qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None, timeout=2000)
        todo_list.add_item(create_todo_item("task 99"))

        table.refresh()

        assert table.cellWidget(4, 0) is combo
        assert table.rowCount() == _ROWS

        combo.hidePopup()
        qtbot.waitUntil(lambda: table.rowCount() == _ROWS + 1, timeout=2000)

    def test_a_refresh_does_not_wait_for_a_popup_of_another_widget(self, qtbot, table, todo_list):
        other = QComboBox()
        qtbot.addWidget(other)
        other.addItems(["one", "two"])
        other.show()
        other.showPopup()
        qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None, timeout=2000)
        todo_list.add_item(create_todo_item("task 99"))

        table.refresh()
        other.hidePopup()

        assert table.rowCount() == _ROWS + 1

    def test_another_list_is_shown_at_once(self, table):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("half typed")
        table.refresh(background=True)

        table.set_list(_numbered_list(3), background=True)

        assert table.rowCount() == 3


class TestSavingAName:
    @pytest.fixture()
    def saved(self, table) -> list[tuple[object, str]]:
        names: list[tuple[object, str]] = []
        table.item_reminder_changed.connect(lambda item_id, text: names.append((item_id, text)))
        return names

    def test_enter_saves_the_name(self, table, saved):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("a new name")

        QTest.keyClick(edit, Qt.Key.Key_Return)

        assert saved == [(edit.item_id, "a new name")]

    def test_leaving_the_field_saves_the_name(self, qtbot, table, saved):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("a new name")

        _edit(table, 6).setFocus()

        qtbot.waitUntil(lambda: saved == [(edit.item_id, "a new name")], timeout=2000)

    def test_the_name_is_saved_once(self, table, saved):
        """Enter ends the editing, and so does the loss of the focus
        that follows it."""
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("a new name")

        QTest.keyClick(edit, Qt.Key.Key_Return)
        _edit(table, 6).setFocus()
        QTest.qWait(20)

        assert len(saved) == 1

    def test_a_name_that_was_not_changed_is_not_saved(self, table, saved):
        edit = _edit(table, 4)
        edit.setFocus()

        QTest.keyClick(edit, Qt.Key.Key_Return)
        _edit(table, 6).setFocus()
        QTest.qWait(20)

        assert saved == []

    def test_escape_puts_the_stored_name_back(self, table, saved):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("a slip of the hand")

        QTest.keyClick(edit, Qt.Key.Key_Escape)
        _edit(table, 6).setFocus()
        QTest.qWait(20)

        assert edit.text() == "task 04"
        assert saved == []

    @pytest.mark.parametrize("emptied", ["", "   "])
    def test_an_emptied_field_takes_the_stored_name_back(self, table, saved, emptied):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText(emptied)

        _edit(table, 6).setFocus()
        QTest.qWait(20)

        assert edit.text() == "task 04"
        assert saved == []

    @pytest.mark.parametrize("emptied", ["", "   "])
    def test_enter_in_an_emptied_field_takes_the_stored_name_back(self, table, saved, emptied):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText(emptied)

        QTest.keyClick(edit, Qt.Key.Key_Return)

        assert edit.text() == "task 04"
        assert saved == []

    def test_a_field_that_is_replaced_saves_nothing(self, table, saved):
        """The rows are made again under a name being typed: the old
        field loses the focus without the name having been left."""
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("half typed")

        table.refresh()
        QTest.qWait(20)

        assert saved == []

    def test_a_saved_name_is_shown_after_the_refresh_it_causes(self, table, todo_list):
        def rename(item_id, text):
            todo_list.get_item(item_id).reminder = text
            table.refresh()

        table.item_reminder_changed.connect(rename)
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("task 04 renamed")

        QTest.keyClick(edit, Qt.Key.Key_Return)

        again = _edit_of(table, "task 04 renamed")
        assert not again.has_unsaved_text()


class TestKeysInAWindowWithAnEscapeShortcut:
    """The application's window has a shortcut on Escape, for its search
    field. A shortcut is looked for before a key reaches the widget that
    has the focus."""

    @pytest.fixture()
    def shown(self, qtbot, todo_list):
        window = QWidget()
        qtbot.addWidget(window)
        layout = QVBoxLayout(window)
        table = TodoTableWidget()
        layout.addWidget(table)
        window.resize(900, 400)
        table.set_list(todo_list)
        fired: list[bool] = []
        shortcut = QShortcut(QKeySequence("Escape"), window)
        shortcut.activated.connect(lambda: fired.append(True))
        window.show()
        window.activateWindow()
        qtbot.waitExposed(window)
        return window, table, fired

    def test_escape_puts_the_stored_name_back(self, shown):
        _window, table, fired = shown
        edit = _edit(table, 4)
        edit.setFocus()
        QTest.keyClicks(edit, "xyz")
        assert edit.text() != "task 04"

        QTest.keyClick(edit, Qt.Key.Key_Escape)

        assert edit.text() == "task 04"
        assert fired == []

    def test_escape_is_the_windows_when_nothing_was_typed(self, shown):
        _window, table, fired = shown
        edit = _edit(table, 4)
        edit.setFocus()

        QTest.keyClick(edit, Qt.Key.Key_Escape)

        assert fired == [True]

    def test_escape_leaves_the_cursor_where_it_is(self, shown):
        _window, table, _fired = shown
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setCursorPosition(2)
        QTest.keyClicks(edit, "xyz")

        QTest.keyClick(edit, Qt.Key.Key_Escape)

        assert edit.cursorPosition() == 5

    def test_escape_puts_the_cursor_at_the_end_of_a_shorter_name(self, shown):
        _window, table, _fired = shown
        edit = _edit(table, 4)
        edit.setFocus()
        edit.end(False)
        QTest.keyClicks(edit, "xyz")

        QTest.keyClick(edit, Qt.Key.Key_Escape)

        assert edit.cursorPosition() == len("task 04")


class TestEnterLeavesTheField:
    """The cursor going out of the field shows that Enter was taken."""

    def test_enter_takes_the_focus_out_of_the_field(self, table):
        edit = _edit(table, 4)
        edit.setFocus()
        QTest.keyClicks(edit, "xyz")

        QTest.keyClick(edit, Qt.Key.Key_Return)

        assert _focused(table) is table
        assert not edit.has_unsaved_text()

    def test_enter_with_nothing_typed_takes_the_focus_out_too(self, table):
        edit = _edit(table, 4)
        edit.setFocus()

        QTest.keyClick(edit, Qt.Key.Key_Return)

        assert _focused(table) is table

    def test_enter_in_an_emptied_field_takes_the_focus_out_too(self, table):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.setText("")

        QTest.keyClick(edit, Qt.Key.Key_Return)

        assert _focused(table) is table
        assert edit.text() == "task 04"

    def test_the_fields_row_is_the_current_one(self, table):
        """The arrow keys go on from the row that was edited."""
        edit = _edit(table, 4)
        edit.setFocus()

        QTest.keyClick(edit, Qt.Key.Key_Return)

        current = table.currentIndex()
        assert (current.row(), current.column()) == (4, 1)

    def test_enter_selects_nothing(self, table):
        table.clearSelection()
        table.selectRow(7)
        chosen = table.get_selected_item_ids()
        edit = _edit(table, 4)
        edit.setFocus()

        QTest.keyClick(edit, Qt.Key.Key_Return)

        assert table.get_selected_item_ids() == chosen

    def test_the_focus_stays_out_of_the_field_after_the_save(self, table, todo_list):
        """Saving makes the rows again; the new field of the task does
        not take the focus back."""

        def rename(item_id, text):
            todo_list.get_item(item_id).reminder = text
            table.refresh()

        table.item_reminder_changed.connect(rename)
        edit = _edit(table, 4)
        edit.setFocus()
        edit.end(False)
        QTest.keyClicks(edit, "xyz")

        QTest.keyClick(edit, Qt.Key.Key_Return)

        again = _edit_of(table, "task 04xyz")
        assert again is not edit
        assert _focused(table) is table
        assert table.get_item_id_at_row(table.currentIndex().row()) == again.item_id

    def test_a_field_that_is_left_after_typing_shows_the_start_of_its_text(self, table):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.end(False)
        QTest.keyClicks(edit, "xyz")

        _edit(table, 6).setFocus()

        assert edit.cursorPosition() == 0

    def test_enter_leaves_the_start_of_the_text_in_view(self, table):
        edit = _edit(table, 4)
        edit.setFocus()
        edit.end(False)
        QTest.keyClicks(edit, "xyz")

        QTest.keyClick(edit, Qt.Key.Key_Return)

        assert edit.cursorPosition() == 0


class TestBoardColumns:
    @pytest.fixture()
    def board(self, qtbot, todo_list) -> KanbanBoardWidget:
        widget = KanbanBoardWidget()
        qtbot.addWidget(widget)
        widget.resize(1000, 500)
        widget.set_list(todo_list)
        widget.show()
        qtbot.waitExposed(widget)
        return widget

    @staticmethod
    def _bar(board: KanbanBoardWidget):
        area = board._columns[0].findChild(QScrollArea)
        assert area is not None
        return area.verticalScrollBar()

    def test_a_scrolled_column_stays_where_it_is(self, qtbot, board):
        bar = self._bar(board)
        qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
        position = bar.maximum() // 2
        bar.setValue(position)

        board.refresh()
        QTest.qWait(50)

        assert self._bar(board) is not bar
        assert self._bar(board).value() == position

    def test_a_column_scrolled_to_its_end_stays_at_its_end(self, qtbot, board):
        bar = self._bar(board)
        qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
        bar.setValue(bar.maximum())

        board.refresh()
        QTest.qWait(50)

        again = self._bar(board)
        assert again.value() == again.maximum() > 0

    def test_another_list_is_shown_from_the_top(self, qtbot, board):
        bar = self._bar(board)
        qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
        bar.setValue(bar.maximum() // 2)

        board.set_list(_numbered_list())
        QTest.qWait(50)

        assert self._bar(board).value() == 0

    def test_a_column_scrolled_afterward_is_left_alone(self, qtbot, board):
        """A position that could not be reached at once is given up as
        soon as the column is scrolled by something else."""
        column = board._columns[0]
        bar = self._bar(board)
        qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
        column.restore_scroll_position(bar.maximum() + 500)
        assert column._scroll_to_restore is not None

        bar.setValue(10)

        assert column._scroll_to_restore is None


class TestMainWindowMarksBackgroundRefreshes:
    """Methods are run unbound against a mock window, as in
    ``test_minute_tick.py``."""

    def test_the_refresh_is_passed_on_to_the_list_view(self):
        window = MagicMock()
        window._view_stack.currentIndex.return_value = 0
        window._database.active_list.deleted = False

        MainWindow._refresh_ui(window, background=True)

        window.todo_table.set_list.assert_called_once_with(
            window._database.active_list, background=True
        )

    def test_a_refresh_is_not_a_background_one_unless_it_says_so(self):
        window = MagicMock()
        window._view_stack.currentIndex.return_value = 0
        window._database.active_list.deleted = False

        MainWindow._refresh_ui(window)

        window.todo_table.set_list.assert_called_once_with(
            window._database.active_list, background=False
        )

    def test_the_minute_tick_refreshes_in_the_background(self, monkeypatch):
        from pytodo_qt.core import models

        monkeypatch.setattr(models, "advance_all_overdue_recurring", lambda _db: 0)
        window = MagicMock()
        window._last_known_today = date.today()
        timed = create_todo_item("due at a set time", due_date=date.today())
        timed.due_time = time(23, 59)
        window._database.active_list.active_items.return_value = [timed]

        MainWindow._check_timed_overdue(window)

        window._refresh_ui.assert_called_once_with(background=True)

    def test_a_change_from_the_web_page_refreshes_in_the_background(self):
        window = MagicMock()
        MainWindow._web_save_and_refresh(window)
        window._refresh_ui.assert_called_once_with(background=True)

    def test_a_sync_received_refreshes_in_the_background(self):
        window = MagicMock()
        window._merge_sync_data_internal.return_value = (1, 0, 0, [])

        MainWindow._on_sync_received(window, b"{}")

        window._refresh_ui.assert_called_once_with(background=True)
