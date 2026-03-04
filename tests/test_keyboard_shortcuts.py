"""Tests for keyboard shortcuts (Phase 2).

Covers:
- ShortcutsHelpDialog: creation, table contents
- ListSelectorWidget: set_current_by_index, cycle_list
- FilterState/search shortcuts (existing, verified)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidget

from pytodo_qt.core.models import Database, create_todo_list
from pytodo_qt.gui.dialogs.shortcuts_help import _SHORTCUTS, ShortcutsHelpDialog
from pytodo_qt.gui.widgets.list_selector import ListSelectorWidget

# ===========================================================================
# ShortcutsHelpDialog tests
# ===========================================================================


class TestShortcutsHelpDialog:
    """Test the keyboard shortcuts help dialog."""

    def test_dialog_creates(self, qtbot):
        dialog = ShortcutsHelpDialog()
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "Keyboard Shortcuts"

    def test_dialog_has_table(self, qtbot):
        dialog = ShortcutsHelpDialog()
        qtbot.addWidget(dialog)
        table = dialog.findChild(QTableWidget)
        assert table is not None

    def test_table_row_count_matches_shortcuts(self, qtbot):
        dialog = ShortcutsHelpDialog()
        qtbot.addWidget(dialog)
        table = dialog.findChild(QTableWidget)
        assert table is not None
        assert table.rowCount() == len(_SHORTCUTS)

    def test_table_has_three_columns(self, qtbot):
        dialog = ShortcutsHelpDialog()
        qtbot.addWidget(dialog)
        table = dialog.findChild(QTableWidget)
        assert table is not None
        assert table.columnCount() == 3

    def test_table_not_editable(self, qtbot):
        dialog = ShortcutsHelpDialog()
        qtbot.addWidget(dialog)
        table = dialog.findChild(QTableWidget)
        assert table is not None
        for row in range(table.rowCount()):
            for col in range(table.columnCount()):
                item = table.item(row, col)
                assert item is not None
                assert not (item.flags() & Qt.ItemFlag.ItemIsEditable)

    def test_shortcuts_list_not_empty(self):
        assert len(_SHORTCUTS) > 0

    def test_shortcuts_have_all_fields(self):
        for category, shortcut, description in _SHORTCUTS:
            assert category, "Category must not be empty"
            assert shortcut, "Shortcut must not be empty"
            assert description, "Description must not be empty"

    def test_categories_exist(self):
        categories = {s[0] for s in _SHORTCUTS}
        assert "Items" in categories
        assert "Lists" in categories
        assert "Navigation" in categories
        assert "Edit" in categories

    def test_ctrl_f_in_shortcuts(self):
        shortcuts = {s[1] for s in _SHORTCUTS}
        assert "Ctrl+F" in shortcuts

    def test_f1_in_shortcuts(self):
        shortcuts = {s[1] for s in _SHORTCUTS}
        assert "F1" in shortcuts


# ===========================================================================
# ListSelectorWidget tests
# ===========================================================================


class TestListSelectorSetByIndex:
    """Test set_current_by_index on ListSelectorWidget."""

    def _make_selector(self, qtbot, list_count: int = 3) -> tuple[ListSelectorWidget, Database]:
        db = Database()
        for i in range(list_count):
            lst = create_todo_list(f"List {i + 1}")
            db.add_list(lst)
        if db.lists:
            db.set_active_list(list(db.lists.keys())[0])

        selector = ListSelectorWidget()
        qtbot.addWidget(selector)
        selector.set_database(db)
        return selector, db

    def test_set_current_by_index_valid(self, qtbot):
        selector, _ = self._make_selector(qtbot)
        assert selector.set_current_by_index(1)
        assert selector.combo.currentIndex() == 1

    def test_set_current_by_index_zero(self, qtbot):
        selector, _ = self._make_selector(qtbot)
        selector.set_current_by_index(2)
        assert selector.set_current_by_index(0)
        assert selector.combo.currentIndex() == 0

    def test_set_current_by_index_last(self, qtbot):
        selector, _ = self._make_selector(qtbot)
        assert selector.set_current_by_index(2)
        assert selector.combo.currentIndex() == 2

    def test_set_current_by_index_out_of_range(self, qtbot):
        selector, _ = self._make_selector(qtbot)
        assert not selector.set_current_by_index(5)

    def test_set_current_by_index_negative(self, qtbot):
        selector, _ = self._make_selector(qtbot)
        assert not selector.set_current_by_index(-1)

    def test_set_current_by_index_empty(self, qtbot):
        db = Database()
        selector = ListSelectorWidget()
        qtbot.addWidget(selector)
        selector.set_database(db)
        assert not selector.set_current_by_index(0)


class TestListSelectorCycle:
    """Test cycle_list on ListSelectorWidget."""

    def _make_selector(self, qtbot, list_count: int = 3) -> ListSelectorWidget:
        db = Database()
        for i in range(list_count):
            lst = create_todo_list(f"List {i + 1}")
            db.add_list(lst)
        if db.lists:
            db.set_active_list(list(db.lists.keys())[0])

        selector = ListSelectorWidget()
        qtbot.addWidget(selector)
        selector.set_database(db)
        return selector

    def test_cycle_forward(self, qtbot):
        selector = self._make_selector(qtbot)
        selector.combo.setCurrentIndex(0)
        selector.cycle_list(1)
        assert selector.combo.currentIndex() == 1

    def test_cycle_forward_wraps(self, qtbot):
        selector = self._make_selector(qtbot)
        selector.combo.setCurrentIndex(2)
        selector.cycle_list(1)
        assert selector.combo.currentIndex() == 0

    def test_cycle_backward(self, qtbot):
        selector = self._make_selector(qtbot)
        selector.combo.setCurrentIndex(1)
        selector.cycle_list(-1)
        assert selector.combo.currentIndex() == 0

    def test_cycle_backward_wraps(self, qtbot):
        selector = self._make_selector(qtbot)
        selector.combo.setCurrentIndex(0)
        selector.cycle_list(-1)
        assert selector.combo.currentIndex() == 2

    def test_cycle_single_list_no_change(self, qtbot):
        selector = self._make_selector(qtbot, list_count=1)
        selector.cycle_list(1)
        assert selector.combo.currentIndex() == 0

    def test_cycle_empty_no_crash(self, qtbot):
        db = Database()
        selector = ListSelectorWidget()
        qtbot.addWidget(selector)
        selector.set_database(db)
        selector.cycle_list(1)  # Should not crash
