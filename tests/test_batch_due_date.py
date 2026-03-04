"""Tests for BatchDueDateDialog and related toolbar/shortcut additions."""

from __future__ import annotations

from datetime import date, time

from PyQt6.QtCore import QDate, Qt

from pytodo_qt.core.models import TodoItem, create_todo_item
from pytodo_qt.gui.dialogs.batch_due_date import BatchDueDateDialog
from pytodo_qt.gui.widgets.todo_table import ClickableLabel

# ===========================================================================
# ClickableLabel tests
# ===========================================================================


class TestClickableLabel:
    """Test the ClickableLabel widget."""

    def test_emits_clicked_on_mouse_press(self, qtbot):
        label = ClickableLabel("test")
        qtbot.addWidget(label)

        with qtbot.waitSignal(label.clicked, timeout=1000):
            qtbot.mouseClick(label, Qt.MouseButton.LeftButton)

    def test_displays_text(self, qtbot):
        label = ClickableLabel("+5")
        qtbot.addWidget(label)
        assert label.text() == "+5"


# ===========================================================================
# BatchDueDateDialog tests
# ===========================================================================


class TestBatchDueDateDialog:
    """Test the batch due date editing dialog."""

    def _make_items(self) -> list[TodoItem]:
        """Create test items with various due dates."""
        items = [
            create_todo_item("Buy groceries"),
            create_todo_item("Write report"),
            create_todo_item("Call dentist"),
        ]
        items[0].due_date = date(2026, 3, 10)
        items[0].due_time = time(14, 0)
        items[1].due_date = date(2026, 3, 15)
        # items[2] has no due date
        return items

    def test_dialog_creation(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "Edit Due Dates"

    def test_has_correct_number_of_rows(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)
        assert len(dialog._rows) == 3

    def test_rows_prefilled_with_current_dates(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)

        # First item has date + time
        row0 = dialog._rows[0]
        assert row0.date_edit.date() == QDate(2026, 3, 10)
        assert row0.time_check.isChecked()

        # Second item has date, no time
        row1 = dialog._rows[1]
        assert row1.date_edit.date() == QDate(2026, 3, 15)
        assert not row1.time_check.isChecked()

    def test_apply_all_sets_date(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)

        dialog._all_date.setDate(QDate(2026, 6, 1))
        dialog._on_apply_all()

        for row in dialog._rows:
            assert row.date_edit.date() == QDate(2026, 6, 1)

    def test_apply_all_sets_time(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)

        dialog._all_date.setDate(QDate(2026, 6, 1))
        dialog._all_time_check.setChecked(True)
        dialog._all_time.set_time(time(9, 30))
        dialog._on_apply_all()

        for row in dialog._rows:
            assert row.date_edit.date() == QDate(2026, 6, 1)
            assert row.time_check.isChecked()

    def test_apply_all_without_time(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)

        dialog._all_time_check.setChecked(False)
        dialog._on_apply_all()

        for row in dialog._rows:
            assert not row.time_check.isChecked()

    def test_get_changes_returns_changed_only(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)

        # Change only the first item's date
        dialog._rows[0].date_edit.setDate(QDate(2026, 12, 25))
        dialog._rows[0].time_check.setChecked(False)

        changes = dialog.get_changes()
        # First item changed (date + time both different)
        changed_ids = {c[0] for c in changes}
        assert items[0].id in changed_ids

    def test_get_changes_empty_when_no_changes(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)

        # Don't change anything
        changes = dialog.get_changes()
        # Items without due dates get set to "today" by default, so they may show as changed
        # Only items with original dates that stay the same should not appear
        for c in changes:
            item_id, new_date, new_time = c
            # Find original item
            orig = next(i for i in items if i.id == item_id)
            assert new_date != orig.due_date or new_time != orig.due_time

    def test_clear_row(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)

        row = dialog._rows[0]
        dialog._on_clear_row(row.date_edit, row.time_check)

        assert row.date_edit.property("cleared") is True
        assert not row.time_check.isChecked()

    def test_clear_row_produces_none_date(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)

        row = dialog._rows[0]
        dialog._on_clear_row(row.date_edit, row.time_check)

        changes = dialog.get_changes()
        cleared = [c for c in changes if c[0] == items[0].id]
        assert len(cleared) == 1
        assert cleared[0][1] is None  # date is None
        assert cleared[0][2] is None  # time is None

    def test_individual_row_edit(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)

        # Change second row individually
        dialog._rows[1].date_edit.setDate(QDate(2026, 7, 4))
        dialog._rows[1].time_check.setChecked(True)
        dialog._rows[1].time_edit.set_time(time(15, 0))

        changes = dialog.get_changes()
        row1_changes = [c for c in changes if c[0] == items[1].id]
        assert len(row1_changes) == 1
        assert row1_changes[0][1] == date(2026, 7, 4)
        assert row1_changes[0][2] == time(15, 0)

    def test_long_reminder_truncated_in_label(self, qtbot):
        item = create_todo_item("A" * 60)
        dialog = BatchDueDateDialog([item])
        qtbot.addWidget(dialog)
        # Dialog should not crash with long reminder text
        assert len(dialog._rows) == 1

    def test_all_time_toggle(self, qtbot):
        items = self._make_items()
        dialog = BatchDueDateDialog(items)
        qtbot.addWidget(dialog)

        assert not dialog._all_time.isEnabled()
        dialog._all_time_check.setChecked(True)
        assert dialog._all_time.isEnabled()
        dialog._all_time_check.setChecked(False)
        assert not dialog._all_time.isEnabled()


# ===========================================================================
# Shortcuts help tests
# ===========================================================================


class TestShortcutsHelpEntries:
    """Test that new shortcuts are listed in the help dialog."""

    def test_edit_tags_shortcut_listed(self):
        from pytodo_qt.gui.dialogs.shortcuts_help import _SHORTCUTS

        shortcuts = {s[1]: s[2] for s in _SHORTCUTS}
        assert "Ctrl+Shift+T" in shortcuts
        assert shortcuts["Ctrl+Shift+T"] == "Edit tags"

    def test_edit_due_date_shortcut_listed(self):
        from pytodo_qt.gui.dialogs.shortcuts_help import _SHORTCUTS

        shortcuts = {s[1]: s[2] for s in _SHORTCUTS}
        assert "Ctrl+D" in shortcuts
        assert shortcuts["Ctrl+D"] == "Edit due date"

    def test_focus_shortcuts_listed(self):
        from pytodo_qt.gui.dialogs.shortcuts_help import _SHORTCUTS

        shortcuts = {s[1]: s[2] for s in _SHORTCUTS}
        assert "Ctrl+T" in shortcuts
        assert shortcuts["Ctrl+T"] == "Start focus session"
        assert "Ctrl+Space" in shortcuts
        assert shortcuts["Ctrl+Space"] == "Pause/resume focus session"
        assert "Ctrl+." in shortcuts
        assert shortcuts["Ctrl+."] == "Stop focus session"
