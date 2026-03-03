"""Tests for GUI dialogs to improve test coverage.

Covers add_todo.py, add_list.py, and edit_recurrence.py.
"""

from datetime import date

import pytest
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication

from pytodo_qt.core.models import Database, TodoItem, create_todo_list
from pytodo_qt.gui.dialogs.add_list import AddListDialog
from pytodo_qt.gui.dialogs.add_todo import AddTodoDialog
from pytodo_qt.gui.dialogs.edit_recurrence import EditRecurrenceDialog


@pytest.fixture(scope="session")
def app():
    """Create QApplication for tests."""
    _app = QApplication.instance()
    if _app is None:
        _app = QApplication([])
    return _app


class TestAddTodoDialog:
    """Tests for AddTodoDialog."""

    def test_construction(self, app):
        dialog = AddTodoDialog()
        assert dialog.windowTitle() == "Add To-Do"
        assert dialog.get_item() is None

    def test_default_state(self, app):
        dialog = AddTodoDialog()
        assert dialog.reminder_edit.text() == ""
        assert dialog.priority_combo.currentIndex() == 1  # Normal
        assert not dialog.due_date_checkbox.isChecked()
        assert not dialog.due_date_edit.isEnabled()
        assert not dialog.recurrence_checkbox.isEnabled()
        assert not dialog.interval_spin.isEnabled()
        assert not dialog.type_combo.isEnabled()

    def test_due_date_toggle_enables_fields(self, app):
        dialog = AddTodoDialog()
        dialog.due_date_checkbox.setChecked(True)
        assert dialog.due_date_edit.isEnabled()
        assert dialog.recurrence_checkbox.isEnabled()

    def test_due_date_toggle_off_disables_recurrence(self, app):
        dialog = AddTodoDialog()
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        assert dialog.interval_spin.isEnabled()

        dialog.due_date_checkbox.setChecked(False)
        assert not dialog.recurrence_checkbox.isChecked()
        assert not dialog.interval_spin.isEnabled()

    def test_recurrence_toggle_enables_fields(self, app):
        dialog = AddTodoDialog()
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        assert dialog.interval_spin.isEnabled()
        assert dialog.type_combo.isEnabled()
        assert dialog.end_widget.isEnabled()

    def test_recurrence_toggle_off_resets_end_condition(self, app):
        dialog = AddTodoDialog()
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        dialog.end_count_radio.setChecked(True)
        dialog._on_end_condition_changed()

        dialog.recurrence_checkbox.setChecked(False)
        assert dialog.end_never_radio.isChecked()
        assert not dialog.end_date_edit.isEnabled()
        assert not dialog.end_count_spin.isEnabled()

    def test_end_condition_date_enables_date_edit(self, app):
        dialog = AddTodoDialog()
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        dialog.end_date_radio.setChecked(True)
        dialog._on_end_condition_changed()
        assert dialog.end_date_edit.isEnabled()
        assert not dialog.end_count_spin.isEnabled()

    def test_end_condition_count_enables_count_spin(self, app):
        dialog = AddTodoDialog()
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        dialog.end_count_radio.setChecked(True)
        dialog._on_end_condition_changed()
        assert not dialog.end_date_edit.isEnabled()
        assert dialog.end_count_spin.isEnabled()

    def test_accept_with_empty_reminder_does_not_create(self, app, monkeypatch):
        dialog = AddTodoDialog()
        # Patch QMessageBox.warning to not show
        monkeypatch.setattr(
            "pytodo_qt.gui.dialogs.add_todo.QMessageBox.warning",
            lambda *args, **kwargs: None,
        )
        dialog._on_accept()
        assert dialog.get_item() is None

    def test_accept_with_valid_reminder(self, app):
        dialog = AddTodoDialog()
        dialog.reminder_edit.setText("Buy groceries")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.reminder == "Buy groceries"
        assert item.priority == 2  # Normal
        assert item.due_date is None
        assert item.recurrence_type is None

    def test_accept_with_due_date(self, app):
        dialog = AddTodoDialog()
        dialog.reminder_edit.setText("Task with date")
        dialog.due_date_checkbox.setChecked(True)
        dialog.due_date_edit.setDate(QDate(2026, 6, 15))
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_date == date(2026, 6, 15)

    def test_accept_with_high_priority(self, app):
        dialog = AddTodoDialog()
        dialog.reminder_edit.setText("Urgent task")
        dialog.priority_combo.setCurrentIndex(0)  # High
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.priority == 1

    def test_accept_with_recurrence_daily(self, app):
        dialog = AddTodoDialog()
        dialog.reminder_edit.setText("Daily standup")
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        dialog.type_combo.setCurrentIndex(0)  # Daily
        dialog.interval_spin.setValue(1)
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.recurrence_type == "daily"
        assert item.recurrence_interval == 1

    def test_accept_with_recurrence_end_date(self, app):
        dialog = AddTodoDialog()
        dialog.reminder_edit.setText("Weekly report")
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        dialog.type_combo.setCurrentIndex(1)  # Weekly
        dialog.interval_spin.setValue(1)
        dialog.end_date_radio.setChecked(True)
        dialog._on_end_condition_changed()
        dialog.end_date_edit.setDate(QDate(2026, 12, 31))
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.recurrence_type == "weekly"
        assert item.recurrence_end_date == date(2026, 12, 31)

    def test_accept_with_recurrence_end_count(self, app):
        dialog = AddTodoDialog()
        dialog.reminder_edit.setText("Monthly review")
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        dialog.type_combo.setCurrentIndex(2)  # Monthly
        dialog.interval_spin.setValue(3)
        dialog.end_count_radio.setChecked(True)
        dialog._on_end_condition_changed()
        dialog.end_count_spin.setValue(5)
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.recurrence_type == "monthly"
        assert item.recurrence_interval == 3
        assert item.recurrence_end_count == 5


class TestAddListDialog:
    """Tests for AddListDialog."""

    def test_construction(self, app):
        dialog = AddListDialog()
        assert dialog.windowTitle() == "Add List"
        assert dialog.get_list() is None

    def test_construction_with_database(self, app):
        db = Database()
        dialog = AddListDialog(database=db)
        assert dialog._database is db

    def test_default_state(self, app):
        dialog = AddListDialog()
        assert dialog.name_edit.text() == ""
        assert not dialog.private_checkbox.isChecked()

    def test_accept_empty_name_does_not_create(self, app, monkeypatch):
        dialog = AddListDialog()
        monkeypatch.setattr(
            "pytodo_qt.gui.dialogs.add_list.QMessageBox.warning",
            lambda *args, **kwargs: None,
        )
        dialog._on_accept()
        assert dialog.get_list() is None

    def test_accept_valid_name(self, app):
        dialog = AddListDialog()
        dialog.name_edit.setText("Work Tasks")
        dialog._on_accept()
        lst = dialog.get_list()
        assert lst is not None
        assert lst.name == "Work Tasks"
        assert lst.private is False

    def test_accept_private_list(self, app):
        dialog = AddListDialog()
        dialog.name_edit.setText("Secret")
        dialog.private_checkbox.setChecked(True)
        dialog._on_accept()
        lst = dialog.get_list()
        assert lst is not None
        assert lst.private is True

    def test_duplicate_name_rejected(self, app, monkeypatch):
        db = Database()
        existing = create_todo_list("Existing")
        db.add_list(existing)

        dialog = AddListDialog(database=db)
        dialog.name_edit.setText("Existing")
        monkeypatch.setattr(
            "pytodo_qt.gui.dialogs.add_list.QMessageBox.warning",
            lambda *args, **kwargs: None,
        )
        dialog._on_accept()
        assert dialog.get_list() is None

    def test_whitespace_name_rejected(self, app, monkeypatch):
        dialog = AddListDialog()
        dialog.name_edit.setText("   ")
        monkeypatch.setattr(
            "pytodo_qt.gui.dialogs.add_list.QMessageBox.warning",
            lambda *args, **kwargs: None,
        )
        dialog._on_accept()
        assert dialog.get_list() is None


class TestEditRecurrenceDialog:
    """Tests for EditRecurrenceDialog."""

    def test_construction_no_recurrence(self, app):
        item = TodoItem(reminder="Test")
        dialog = EditRecurrenceDialog(item)
        assert dialog.windowTitle() == "Edit Recurrence"

    def test_construction_with_recurrence(self, app):
        item = TodoItem(
            reminder="Daily task",
            recurrence_type="daily",
            recurrence_interval=2,
        )
        dialog = EditRecurrenceDialog(item)
        assert dialog.interval_spin.value() == 2
        type_index = dialog.type_combo.findData("daily")
        assert dialog.type_combo.currentIndex() == type_index

    def test_construction_with_end_date(self, app):
        item = TodoItem(
            reminder="Task",
            recurrence_type="weekly",
            recurrence_interval=1,
            recurrence_end_date=date(2026, 12, 31),
        )
        dialog = EditRecurrenceDialog(item)
        assert dialog.end_date_radio.isChecked()
        assert dialog.end_date_edit.isEnabled()

    def test_construction_with_end_count(self, app):
        item = TodoItem(
            reminder="Task",
            recurrence_type="monthly",
            recurrence_interval=1,
            recurrence_end_count=10,
        )
        dialog = EditRecurrenceDialog(item)
        assert dialog.end_count_radio.isChecked()
        assert dialog.end_count_spin.isEnabled()
        assert dialog.end_count_spin.value() == 10

    def test_construction_with_no_end(self, app):
        item = TodoItem(
            reminder="Task",
            recurrence_type="yearly",
            recurrence_interval=1,
        )
        dialog = EditRecurrenceDialog(item)
        assert dialog.end_never_radio.isChecked()

    def test_end_condition_change(self, app):
        item = TodoItem(reminder="Test", recurrence_type="daily")
        dialog = EditRecurrenceDialog(item)
        dialog.end_date_radio.setChecked(True)
        dialog._on_end_condition_changed()
        assert dialog.end_date_edit.isEnabled()
        assert not dialog.end_count_spin.isEnabled()

        dialog.end_count_radio.setChecked(True)
        dialog._on_end_condition_changed()
        assert not dialog.end_date_edit.isEnabled()
        assert dialog.end_count_spin.isEnabled()

    def test_accept_saves_result(self, app):
        item = TodoItem(reminder="Test", recurrence_type="daily")
        dialog = EditRecurrenceDialog(item)
        dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("weekly"))
        dialog.interval_spin.setValue(2)
        dialog._on_accept()
        result = dialog.get_recurrence()
        assert result == ("weekly", 2, None, None)

    def test_accept_with_end_date(self, app):
        item = TodoItem(reminder="Test", recurrence_type="daily")
        dialog = EditRecurrenceDialog(item)
        dialog.end_date_radio.setChecked(True)
        dialog._on_end_condition_changed()
        dialog.end_date_edit.setDate(QDate(2027, 1, 1))
        dialog._on_accept()
        result = dialog.get_recurrence()
        assert result[0] == "daily"
        assert result[2] == date(2027, 1, 1)

    def test_accept_with_end_count(self, app):
        item = TodoItem(reminder="Test", recurrence_type="monthly")
        dialog = EditRecurrenceDialog(item)
        dialog.end_count_radio.setChecked(True)
        dialog._on_end_condition_changed()
        dialog.end_count_spin.setValue(5)
        dialog._on_accept()
        result = dialog.get_recurrence()
        assert result[3] == 5

    def test_remove_recurrence(self, app):
        item = TodoItem(
            reminder="Test",
            recurrence_type="daily",
            recurrence_interval=1,
        )
        dialog = EditRecurrenceDialog(item)
        dialog._on_remove()
        result = dialog.get_recurrence()
        assert result == (None, 1, None, None)

    def test_cancelled_returns_defaults(self, app):
        item = TodoItem(reminder="Test", recurrence_type="daily")
        dialog = EditRecurrenceDialog(item)
        # Don't call _on_accept or _on_remove — simulate cancel
        result = dialog.get_recurrence()
        assert result == (None, 1, None, None)
