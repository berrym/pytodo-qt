"""Tests for setting a task's advance reminder.

Covers the shared editor (a cadence choice and a day count), its row in
the Add Todo dialog and in the detail panel, and the main window storing
a change as one undoable step.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from pytodo_qt.core.config import AppConfig
from pytodo_qt.core.models import TodoItem, TodoList, create_todo_item, create_todo_list
from pytodo_qt.gui.dialogs.add_todo import AddTodoDialog
from pytodo_qt.gui.main_window import MainWindow
from pytodo_qt.gui.widgets.advance_reminder import AdvanceReminderEditor
from pytodo_qt.gui.widgets.detail_panel import TaskDetailPanel


def choose(editor: AdvanceReminderEditor, cadence: str) -> None:
    """Pick a cadence the way a user does, by changing the combo."""
    editor.cadence_combo.setCurrentIndex(editor.cadence_combo.findData(cadence))


# ---------------------------------------------------------------------------
# The editor
# ---------------------------------------------------------------------------


@pytest.fixture
def editor(qtbot):
    widget = AdvanceReminderEditor()
    qtbot.addWidget(widget)
    return widget


class TestEditor:
    def test_starts_off(self, editor):
        assert editor.value() == (0, "none")
        assert not editor.days_spin.isEnabled()

    def test_offers_the_three_choices(self, editor):
        combo = editor.cadence_combo
        assert [combo.itemData(i) for i in range(combo.count())] == [
            "none",
            "once",
            "daily_until_due",
        ]

    def test_day_count_range_and_start(self, editor):
        assert (editor.days_spin.minimum(), editor.days_spin.maximum()) == (1, 90)
        assert editor.days_spin.value() == 1

    def test_choosing_a_cadence_enables_the_day_count(self, editor):
        choose(editor, "once")
        assert editor.days_spin.isEnabled()
        assert editor.value() == (1, "once")

    def test_off_stores_no_day_count(self, editor):
        choose(editor, "daily_until_due")
        editor.days_spin.setValue(7)
        choose(editor, "none")
        assert editor.value() == (0, "none")

    def test_day_count_is_kept_while_off(self, editor):
        """Switching off and on again does not lose the count typed in."""
        choose(editor, "once")
        editor.days_spin.setValue(7)
        choose(editor, "none")
        choose(editor, "once")
        assert editor.value() == (7, "once")

    def test_set_value_shows_a_stored_reminder(self, editor):
        editor.set_value(5, "daily_until_due")
        assert editor.value() == (5, "daily_until_due")

    @pytest.mark.parametrize(
        ("days", "cadence"), [(3, "none"), (0, "once"), (-1, "once"), (3, "weekly"), (3, "")]
    )
    def test_stored_combination_that_asks_for_nothing_shows_as_off(self, editor, days, cadence):
        editor.set_value(days, cadence)
        assert editor.value() == (0, "none")

    def test_stored_day_count_beyond_the_range_is_limited(self, editor):
        editor.set_value(400, "once")
        assert editor.value() == (90, "once")

    def test_suffix_agrees_with_the_count(self, editor):
        choose(editor, "once")
        assert editor.days_spin.suffix() == " day before"
        editor.days_spin.setValue(2)
        assert editor.days_spin.suffix() == " days before"

    def test_controls_have_accessible_names(self, editor):
        assert editor.cadence_combo.accessibleName()
        assert editor.days_spin.accessibleName()
        assert editor.days_spin.accessibleDescription()

    def test_user_changes_are_reported(self, editor):
        seen: list[tuple[int, str]] = []
        editor.changed.connect(lambda days, cadence: seen.append((days, cadence)))
        choose(editor, "once")
        editor.days_spin.setValue(3)
        choose(editor, "none")
        assert seen == [(1, "once"), (3, "once"), (0, "none")]

    def test_set_value_is_not_reported_as_a_change(self, editor):
        seen: list[tuple[int, str]] = []
        editor.changed.connect(lambda days, cadence: seen.append((days, cadence)))
        editor.set_value(5, "daily_until_due")
        editor.set_value(0, "none")
        assert seen == []

    def test_day_count_can_be_hidden_while_off(self, qtbot):
        widget = AdvanceReminderEditor(hide_days_when_off=True)
        qtbot.addWidget(widget)
        widget.show()
        assert not widget.days_spin.isVisible()
        choose(widget, "once")
        assert widget.days_spin.isVisible()

    def test_day_count_stays_visible_by_default(self, editor):
        editor.show()
        assert editor.days_spin.isVisible()


# ---------------------------------------------------------------------------
# Add Todo
# ---------------------------------------------------------------------------


def advanced_dialog(qtbot) -> AddTodoDialog:
    dialog = AddTodoDialog()
    qtbot.addWidget(dialog)
    dialog._advanced_toggle.setChecked(True)
    dialog.reminder_edit.setText("Tax return")
    return dialog


class TestAddTodo:
    def test_row_is_greyed_without_a_due_date(self, qtbot):
        dialog = advanced_dialog(qtbot)
        assert not dialog.advance_reminder_editor.isEnabled()
        assert not dialog._advance_reminder_label.isEnabled()

    def test_row_follows_the_due_date_checkbox(self, qtbot):
        dialog = advanced_dialog(qtbot)
        dialog.due_date_checkbox.setChecked(True)
        assert dialog.advance_reminder_editor.isEnabled()
        assert dialog._advance_reminder_label.isEnabled()
        dialog.due_date_checkbox.setChecked(False)
        assert not dialog.advance_reminder_editor.isEnabled()

    def test_label_has_a_mnemonic_that_reaches_the_choice(self, qtbot):
        dialog = advanced_dialog(qtbot)
        assert "&" in dialog._advance_reminder_label.text()
        assert (
            dialog._advance_reminder_label.buddy() is dialog.advance_reminder_editor.cadence_combo
        )

    def test_created_task_carries_the_reminder(self, qtbot):
        dialog = advanced_dialog(qtbot)
        dialog.due_date_checkbox.setChecked(True)
        choose(dialog.advance_reminder_editor, "daily_until_due")
        dialog.advance_reminder_editor.days_spin.setValue(4)
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert (item.remind_before_days, item.reminder_cadence) == (4, "daily_until_due")

    def test_created_task_has_none_by_default(self, qtbot):
        dialog = advanced_dialog(qtbot)
        dialog.due_date_checkbox.setChecked(True)
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert (item.remind_before_days, item.reminder_cadence) == (0, "none")

    def test_reminder_is_dropped_when_the_due_date_is_unset_again(self, qtbot):
        dialog = advanced_dialog(qtbot)
        dialog.due_date_checkbox.setChecked(True)
        choose(dialog.advance_reminder_editor, "once")
        dialog.due_date_checkbox.setChecked(False)
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_date is None
        assert (item.remind_before_days, item.reminder_cadence) == (0, "none")

    def test_no_note_while_the_summary_is_on(self, qtbot, monkeypatch):
        monkeypatch.setattr("pytodo_qt.gui.dialogs.add_todo.get_config", AppConfig)
        dialog = AddTodoDialog()
        qtbot.addWidget(dialog)
        form = dialog._advance_reminder_note.parentWidget().layout()
        assert not form.isRowVisible(dialog._advance_reminder_note)

    @pytest.mark.parametrize("switched_off", ["summary_enabled", "enabled"])
    def test_note_when_the_summary_cannot_be_shown(self, qtbot, monkeypatch, switched_off):
        config = AppConfig()
        setattr(config.notifications, switched_off, False)
        monkeypatch.setattr("pytodo_qt.gui.dialogs.add_todo.get_config", lambda: config)
        dialog = AddTodoDialog()
        qtbot.addWidget(dialog)
        form = dialog._advance_reminder_note.parentWidget().layout()
        assert form.isRowVisible(dialog._advance_reminder_note)
        assert "daily summary" in dialog._advance_reminder_note.text()


# ---------------------------------------------------------------------------
# Detail panel
# ---------------------------------------------------------------------------


def panel_with(qtbot, **fields) -> tuple[TaskDetailPanel, TodoItem]:
    panel = TaskDetailPanel()
    qtbot.addWidget(panel)
    panel.show()
    todo_list = create_todo_list("L")
    item = create_todo_item("Tax return")
    for name, value in fields.items():
        setattr(item, name, value)
    todo_list.add_item(item)
    panel.set_item(item, todo_list)
    return panel, item


DUE = date(2026, 11, 20)


class TestDetailPanel:
    def test_shows_the_stored_reminder(self, qtbot):
        panel, _ = panel_with(
            qtbot, due_date=DUE, remind_before_days=3, reminder_cadence="daily_until_due"
        )
        assert panel._advance_editor.value() == (3, "daily_until_due")

    def test_shows_off_for_a_task_without_one(self, qtbot):
        panel, _ = panel_with(qtbot, due_date=DUE)
        assert panel._advance_editor.value() == (0, "none")
        assert not panel._advance_editor.days_spin.isVisible()

    def test_read_only_in_view_mode(self, qtbot):
        panel, _ = panel_with(qtbot, due_date=DUE)
        assert not panel._advance_editor.isEnabled()

    def test_live_in_edit_mode_with_a_due_date(self, qtbot):
        panel, _ = panel_with(qtbot, due_date=DUE)
        panel.set_edit_mode(True)
        assert panel._advance_editor.isEnabled()

    def test_greyed_in_edit_mode_without_a_due_date(self, qtbot):
        panel, _ = panel_with(qtbot)
        panel.set_edit_mode(True)
        assert not panel._advance_editor.isEnabled()

    def test_leaving_edit_mode_makes_it_read_only_again(self, qtbot):
        panel, _ = panel_with(qtbot, due_date=DUE)
        panel.set_edit_mode(True)
        panel.set_edit_mode(False)
        assert not panel._advance_editor.isEnabled()

    def test_editing_reports_the_change_for_the_task(self, qtbot):
        panel, item = panel_with(qtbot, due_date=DUE)
        panel.set_edit_mode(True)
        seen: list[tuple[object, int, str]] = []
        panel.item_advance_reminder_changed.connect(lambda *args: seen.append(args))
        choose(panel._advance_editor, "once")
        panel._advance_editor.days_spin.setValue(5)
        assert seen == [(item.id, 1, "once"), (item.id, 5, "once")]

    def test_showing_another_task_reports_nothing(self, qtbot):
        panel, _ = panel_with(qtbot, due_date=DUE)
        panel.set_edit_mode(True)
        seen: list[tuple[object, int, str]] = []
        panel.item_advance_reminder_changed.connect(lambda *args: seen.append(args))
        other_list = create_todo_list("L2")
        other = create_todo_item("Passport")
        other.due_date = DUE + timedelta(days=1)
        other.remind_before_days = 7
        other.reminder_cadence = "once"
        other_list.add_item(other)
        panel.set_item(other, other_list)
        assert panel._advance_editor.value() == (7, "once")
        assert seen == []


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


def window_with(item: TodoItem) -> MagicMock:
    todo_list = TodoList(name="Tasks")
    todo_list.add_item(item)
    window = MagicMock()
    window._database.active_list = todo_list
    window.tr.side_effect = lambda text: text
    return window


def pushed(window: MagicMock) -> list[tuple[str, object]]:
    return [
        (call.args[0]._field_name, call.args[0]._new_value)
        for call in window._undo_stack.push.call_args_list
    ]


class TestStoringAChange:
    def test_both_fields_are_set_as_one_undo_step(self):
        item = TodoItem(reminder="Tax return", due_date=DUE)
        window = window_with(item)

        MainWindow._on_item_advance_reminder_changed(window, item.id, 3, "once")

        assert pushed(window) == [("remind_before_days", 3), ("reminder_cadence", "once")]
        window._undo_stack.beginMacro.assert_called_once()
        window._undo_stack.endMacro.assert_called_once()

    def test_only_the_field_that_changed_is_set(self):
        item = TodoItem(
            reminder="Tax return", due_date=DUE, remind_before_days=3, reminder_cadence="once"
        )
        window = window_with(item)

        MainWindow._on_item_advance_reminder_changed(window, item.id, 5, "once")

        assert pushed(window) == [("remind_before_days", 5)]

    def test_no_change_pushes_nothing(self):
        item = TodoItem(
            reminder="Tax return", due_date=DUE, remind_before_days=3, reminder_cadence="once"
        )
        window = window_with(item)

        MainWindow._on_item_advance_reminder_changed(window, item.id, 3, "once")

        window._undo_stack.push.assert_not_called()
        window._undo_stack.beginMacro.assert_not_called()

    def test_unknown_task_is_ignored(self):
        window = window_with(TodoItem(reminder="Tax return"))
        other = TodoItem(reminder="Elsewhere")

        MainWindow._on_item_advance_reminder_changed(window, other.id, 3, "once")

        window._undo_stack.push.assert_not_called()

    def test_something_that_is_not_a_task_id_is_ignored(self):
        window = window_with(TodoItem(reminder="Tax return"))

        MainWindow._on_item_advance_reminder_changed(window, "not-an-id", 3, "once")

        window._undo_stack.push.assert_not_called()

    def test_detail_panel_signal_is_connected(self):
        """Some method of the main window names both the panel's signal
        and the handler, which is where the two are connected."""
        connecting = [
            name
            for name, method in vars(MainWindow).items()
            if hasattr(method, "__code__")
            and "item_advance_reminder_changed" in method.__code__.co_names
            and "_on_item_advance_reminder_changed" in method.__code__.co_names
        ]
        assert connecting
