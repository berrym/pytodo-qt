"""The list view selects a task only when it is chosen (#125).

Each row has a priority box, a widget in the first column. Qt makes the
row of such a widget current and selected whenever the widget takes the
keyboard focus, and the table, taking the focus with no current cell,
hands it to the first row's box. So the first task came up selected,
with the arrow keys on its priority, after a view switch, after a task
was deleted behind a dialog, and whenever the window became active
again. A task ticked or unticked that moved stayed selected out of view.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QStackedWidget, QVBoxLayout, QWidget

from pytodo_qt.core.models import TodoList, create_todo_item, create_todo_list
from pytodo_qt.gui.main_window import show_view
from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

_NAMES = ("Alpha", "Bravo", "Charlie", "Delta", "Echo")


@pytest.fixture()
def todo_list() -> TodoList:
    todo_list = create_todo_list("Letters")
    for name in _NAMES:
        todo_list.add_item(create_todo_item(name))
    return todo_list


@pytest.fixture()
def shown(qtbot, todo_list):
    """A window with a search field and the list view, as the main window."""
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
    window.activateWindow()
    qtbot.waitExposed(window)
    search.setFocus()
    QApplication.processEvents()
    return window, search, table


def _selected(table: TodoTableWidget, todo_list: TodoList) -> list[str]:
    return sorted(todo_list.get_item(i).reminder for i in table.get_selected_item_ids())


def _row_of(table: TodoTableWidget, todo_list: TodoList, name: str) -> int:
    for row in range(table.rowCount()):
        if todo_list.get_item(table.get_item_id_at_row(row)).reminder == name:
            return row
    raise AssertionError(f"no row named {name!r}")


def _box(table: TodoTableWidget, todo_list: TodoList, name: str) -> QWidget:
    box = table.cellWidget(_row_of(table, todo_list, name), 0)
    assert box is not None
    return box


def _behind_a_dialog(window: QWidget, action) -> None:
    """Do ``action`` while a dialog of the window is in front, then close it."""
    dialog = QDialog(window)
    dialog.setModal(True)
    dialog.show()
    dialog.activateWindow()
    QApplication.processEvents()
    action()
    QApplication.processEvents()
    dialog.accept()
    dialog.deleteLater()
    window.activateWindow()
    QApplication.processEvents()


class TestTheTableTakingTheFocus:
    @pytest.mark.parametrize(
        "reason",
        [Qt.FocusReason.OtherFocusReason, Qt.FocusReason.ActiveWindowFocusReason],
    )
    def test_no_row_is_chosen(self, shown, todo_list, reason):
        window, _search, table = shown

        table.setFocus(reason)
        QApplication.processEvents()

        assert window.focusWidget() is table
        assert table.get_selected_item_ids() == []
        assert not table.currentIndex().isValid()

    def test_the_first_arrow_key_goes_to_the_first_row(self, shown, todo_list):
        _window, _search, table = shown
        table.setFocus(Qt.FocusReason.OtherFocusReason)

        QTest.keyClick(table, Qt.Key.Key_Down)

        assert _selected(table, todo_list) == ["Alpha"]

    def test_a_click_on_a_row_still_selects_it(self, shown, todo_list):
        _window, _search, table = shown
        row = _row_of(table, todo_list, "Charlie")
        viewport = table.viewport()
        assert viewport is not None
        rect = table.visualRect(table.model().index(row, 2))

        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=rect.center())

        assert _selected(table, todo_list) == ["Charlie"]


class TestAPriorityBoxTakingTheFocus:
    @pytest.mark.parametrize(
        "reason",
        [Qt.FocusReason.OtherFocusReason, Qt.FocusReason.ActiveWindowFocusReason],
    )
    def test_its_row_is_not_chosen_by_the_focus_coming_back(self, shown, todo_list, reason):
        _window, _search, table = shown

        _box(table, todo_list, "Charlie").setFocus(reason)
        QApplication.processEvents()

        assert table.get_selected_item_ids() == []

    @pytest.mark.parametrize(
        "reason",
        [
            Qt.FocusReason.MouseFocusReason,
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
        ],
    )
    def test_its_row_is_chosen_by_a_click_or_tab(self, shown, todo_list, reason):
        _window, _search, table = shown
        table.select_item(todo_list.items[next(iter(todo_list.items))].id)

        _box(table, todo_list, "Charlie").setFocus(reason)
        QApplication.processEvents()

        assert _selected(table, todo_list) == ["Charlie"]

    def test_a_deselected_row_stays_deselected_when_the_window_comes_back(self, shown, todo_list):
        window, _search, table = shown
        _box(table, todo_list, "Bravo").setFocus(Qt.FocusReason.TabFocusReason)
        assert _selected(table, todo_list) == ["Bravo"]
        table.clearSelection()

        _behind_a_dialog(window, lambda: None)

        assert table.get_selected_item_ids() == []


class TestFocusLeftByARowThatIsGone:
    def test_the_table_takes_it_and_no_row_is_chosen(self, shown, todo_list):
        window, _search, table = shown
        _box(table, todo_list, "Charlie").setFocus(Qt.FocusReason.TabFocusReason)
        charlie = table.get_selected_item_ids()[0]

        todo_list.get_item(charlie).deleted = True
        table.refresh()
        QApplication.processEvents()

        assert window.focusWidget() is table
        assert table.get_selected_item_ids() == []

    def test_nothing_is_chosen_when_a_dialog_closes(self, shown, todo_list):
        """A delete is confirmed in a dialog; the window looks for a
        focus widget when the dialog closes."""
        window, _search, table = shown
        _box(table, todo_list, "Charlie").setFocus(Qt.FocusReason.TabFocusReason)
        charlie = table.get_selected_item_ids()[0]

        def delete() -> None:
            todo_list.get_item(charlie).deleted = True
            table.refresh()

        _behind_a_dialog(window, delete)

        assert table.get_selected_item_ids() == []
        assert window.focusWidget() is table

    def test_the_table_takes_it_when_the_last_task_is_gone(self, shown, todo_list):
        window, _search, table = shown
        _box(table, todo_list, "Echo").setFocus(Qt.FocusReason.TabFocusReason)
        for item in todo_list.items.values():
            item.deleted = True

        table.refresh()
        QApplication.processEvents()

        assert window.focusWidget() is table

    def test_a_row_that_is_still_there_keeps_it(self, shown, todo_list):
        window, _search, table = shown
        _box(table, todo_list, "Charlie").setFocus(Qt.FocusReason.TabFocusReason)

        table.refresh()

        assert window.focusWidget() is _box(table, todo_list, "Charlie")
        assert _selected(table, todo_list) == ["Charlie"]


class TestSwitchingToTheListView:
    @pytest.fixture()
    def stacked(self, qtbot, todo_list):
        window = QWidget()
        qtbot.addWidget(window)
        layout = QVBoxLayout(window)
        search = QLineEdit()
        stack = QStackedWidget()
        table = TodoTableWidget()
        board = QWidget()
        board_field = QLineEdit(board)
        stack.addWidget(table)
        stack.addWidget(board)
        layout.addWidget(search)
        layout.addWidget(stack)
        window.resize(900, 400)
        table.set_list(todo_list)
        stack.setCurrentIndex(1)
        window.show()
        window.activateWindow()
        qtbot.waitExposed(window)
        return window, search, stack, table, board_field

    def test_focus_in_the_page_left_goes_to_the_table(self, stacked, todo_list):
        window, _search, stack, table, board_field = stacked
        board_field.setFocus()
        QApplication.processEvents()

        show_view(stack, 0, table)
        QApplication.processEvents()

        assert window.focusWidget() is table
        assert table.get_selected_item_ids() == []

    def test_the_focus_goes_straight_to_the_table(self, stacked, todo_list):
        """It does not stop on the first row's priority box on the way."""
        _window, _search, stack, table, board_field = stacked
        board_field.setFocus()
        QApplication.processEvents()
        took_it: list[object] = []
        app = QApplication.instance()
        assert isinstance(app, QApplication)

        def record(_old, new) -> None:
            if new is not None:
                took_it.append(new)

        app.focusChanged.connect(record)
        try:
            show_view(stack, 0, table)
            QApplication.processEvents()
        finally:
            app.focusChanged.disconnect(record)

        assert took_it == [table]

    def test_focus_outside_the_stack_stays_there(self, stacked, todo_list):
        window, search, stack, table, _board_field = stacked
        search.setFocus()
        QApplication.processEvents()

        show_view(stack, 0, table)
        QApplication.processEvents()

        assert window.focusWidget() is search
        assert table.get_selected_item_ids() == []

    def test_another_page_is_shown_as_before(self, stacked):
        window, _search, stack, table, board_field = stacked
        stack.setCurrentIndex(0)
        table.setFocus()

        show_view(stack, 1, table)

        assert stack.currentIndex() == 1


class TestATickedTaskThatMoves:
    """Finished tasks sort to the bottom by default."""

    def test_is_no_longer_selected(self, shown, todo_list):
        _window, _search, table = shown
        bravo = todo_list.get_item(table.get_item_id_at_row(_row_of(table, todo_list, "Bravo")))
        table.select_item(bravo.id)
        reported: list[object] = []
        table.item_selected.connect(reported.append)

        bravo.complete = True
        table.refresh()

        assert _row_of(table, todo_list, "Bravo") == len(_NAMES) - 1
        assert table.get_selected_item_ids() == []
        assert reported == [None]

    def test_is_no_longer_current(self, shown, todo_list):
        """With the focus in the search field, a current cell outside
        the priority column is put back after a refresh."""
        window, search, table = shown
        row = _row_of(table, todo_list, "Bravo")
        table.setCurrentCell(row, 2)
        assert window.focusWidget() is search
        bravo = todo_list.get_item(table.get_item_id_at_row(row))

        bravo.complete = True
        table.refresh()

        current = table.currentIndex()
        assert not current.isValid() or table.get_item_id_at_row(current.row()) != bravo.id

    def test_unticked_and_moved_is_no_longer_selected(self, shown, todo_list):
        _window, _search, table = shown
        bravo = todo_list.get_item(table.get_item_id_at_row(_row_of(table, todo_list, "Bravo")))
        bravo.complete = True
        table.refresh()
        table.select_item(bravo.id)

        bravo.complete = False
        table.refresh()

        assert _row_of(table, todo_list, "Bravo") == 1
        assert table.get_selected_item_ids() == []

    def test_ticked_and_still_in_its_row_stays_selected(self, shown, todo_list):
        _window, _search, table = shown
        echo = todo_list.get_item(table.get_item_id_at_row(_row_of(table, todo_list, "Echo")))
        table.select_item(echo.id)

        echo.complete = True
        table.refresh()

        assert _selected(table, todo_list) == ["Echo"]

    def test_the_other_selected_tasks_stay_selected(self, shown, todo_list):
        _window, _search, table = shown
        table.selectAll()
        bravo = todo_list.get_item(table.get_item_id_at_row(_row_of(table, todo_list, "Bravo")))

        bravo.complete = True
        table.refresh()

        assert "Bravo" not in _selected(table, todo_list)
        assert "Alpha" in _selected(table, todo_list)


class TestSelectingATaskFromOutside:
    """Open from a notification selects the task's row."""

    def test_the_row_is_selected_and_the_focus_stays_where_it_is(self, shown, todo_list):
        window, search, table = shown
        charlie = table.get_item_id_at_row(_row_of(table, todo_list, "Charlie"))

        assert table.select_item(charlie)
        QApplication.processEvents()

        assert _selected(table, todo_list) == ["Charlie"]
        assert window.focusWidget() is search
        assert table.currentIndex().column() == 1
