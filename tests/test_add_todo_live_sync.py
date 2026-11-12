"""Tests for the Add Todo input line driving the Advanced fields.

With Advanced closed the discrete fields mirror the line. With it open
the task is built from the fields, which may have been set by hand, so
the line updates only the fields it has just changed.
"""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from PyQt6.QtCore import QDate

from pytodo_qt.gui.dialogs.add_todo import AddTodoDialog

TOMORROW = date.today() + timedelta(days=1)
HAND_DATE = date.today() + timedelta(days=40)


@pytest.fixture(autouse=True)
def validation_warning_fails(monkeypatch):
    """A validation warning fails the test. Left alone it is a modal
    box, which would block the run instead."""

    def fail(_parent, _title, text, *args, **kwargs):
        raise AssertionError(f"validation warning: {text}")

    monkeypatch.setattr("pytodo_qt.gui.dialogs.add_todo.QMessageBox.warning", fail)


def open_advanced(qtbot, text: str = "", **kwargs) -> AddTodoDialog:
    """A dialog with Advanced opened first, then ``text`` typed."""
    dialog = AddTodoDialog(**kwargs)
    qtbot.addWidget(dialog)
    dialog._advanced_toggle.setChecked(True)
    if text:
        type_line(dialog, text)
    return dialog


def type_line(dialog: AddTodoDialog, text: str) -> None:
    """Replace the line's text and let its parse reach the dialog."""
    dialog._smart_input.set_text(text)
    dialog._smart_input.get_parse_result()


def field_date(dialog: AddTodoDialog) -> date | None:
    if not dialog.due_date_checkbox.isChecked():
        return None
    qdate = dialog.due_date_edit.date()
    return date(qdate.year(), qdate.month(), qdate.day())


def set_date_by_hand(dialog: AddTodoDialog, day: date) -> None:
    dialog.due_date_checkbox.setChecked(True)
    dialog.due_date_edit.setDate(QDate(day.year, day.month, day.day))


def accepted(dialog: AddTodoDialog):
    dialog._on_accept()
    item = dialog.get_item()
    assert item is not None
    return item


# ---------------------------------------------------------------------------
# Typing with Advanced open reaches the fields
# ---------------------------------------------------------------------------


class TestTypingReachesTheFields:
    def test_task_typed_after_opening_advanced_is_created(self, qtbot):
        dialog = open_advanced(qtbot, "Tax return tomorrow remind me 3 days before")
        item = accepted(dialog)
        assert item.reminder == "Tax return"
        assert item.due_date == TOMORROW
        assert (item.remind_before_days, item.reminder_cadence) == (3, "once")

    def test_title(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk")
        assert dialog.reminder_edit.text() == "Buy milk"

    def test_due_date(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk tomorrow")
        assert field_date(dialog) == TOMORROW

    def test_due_time_and_end(self, qtbot):
        dialog = open_advanced(qtbot, "Standup tomorrow from 9 to 10 am")
        assert dialog.due_time_checkbox.isChecked()
        assert dialog.due_time_edit.get_time() == time(9, 0)
        assert dialog.due_time_end_checkbox.isChecked()
        assert dialog.due_time_end_edit.get_time() == time(10, 0)

    def test_priority(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk p1")
        assert dialog.priority_combo.currentData() == 1

    def test_tags(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk @errands")
        assert dialog.tags_edit.text() == "@errands"

    def test_subtasks(self, qtbot):
        dialog = open_advanced(qtbot, "Pack: socks, charger")
        assert dialog.subtasks_edit.toPlainText() == "socks\ncharger"

    def test_recurrence(self, qtbot):
        dialog = open_advanced(qtbot, "Water plants every 2 days")
        assert dialog.recurrence_checkbox.isChecked()
        assert dialog.type_combo.currentData() == "daily"
        assert dialog.interval_spin.value() == 2

    def test_pomodoros_and_estimate(self, qtbot):
        dialog = open_advanced(qtbot, "Write essay ~2h ~3 pom")
        assert dialog.estimated_pomodoros_spin.value() == 3
        assert dialog._get_duration_minutes() == 120

    def test_advance_reminder_row(self, qtbot):
        dialog = open_advanced(qtbot, "Tax return tomorrow remind me daily from a week before")
        assert dialog.advance_reminder_editor.isEnabled()
        assert dialog.advance_reminder_editor.value() == (7, "daily_until_due")

    def test_fields_follow_each_keystroke(self, qtbot):
        dialog = open_advanced(qtbot)
        for text in ("Buy", "Buy milk", "Buy milk tom", "Buy milk tomorrow"):
            type_line(dialog, text)
        assert dialog.reminder_edit.text() == "Buy milk"
        assert field_date(dialog) == TOMORROW

    def test_removed_phrase_clears_its_field(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk tomorrow p1 @errands")
        type_line(dialog, "Buy milk")
        assert field_date(dialog) is None
        assert dialog.priority_combo.currentData() == 2
        assert dialog.tags_edit.text() == ""

    def test_text_typed_just_before_ok_is_taken_in(self, qtbot):
        dialog = open_advanced(qtbot)
        # Still inside the line's parse delay when OK is pressed.
        dialog._smart_input.set_text("Buy milk tomorrow")
        item = accepted(dialog)
        assert item.reminder == "Buy milk"
        assert item.due_date == TOMORROW


# ---------------------------------------------------------------------------
# Fields set by hand
# ---------------------------------------------------------------------------


class TestHandEditsSurvive:
    def test_priority_survives_more_typing(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk")
        dialog.priority_combo.setCurrentIndex(dialog.priority_combo.findData(1))
        type_line(dialog, "Buy milk and eggs tomorrow")
        assert dialog.priority_combo.currentData() == 1
        assert dialog.reminder_edit.text() == "Buy milk and eggs"

    def test_title_survives_typing_about_something_else(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk")
        dialog.reminder_edit.setText("Buy oat milk")
        type_line(dialog, "Buy milk p1")
        assert dialog.reminder_edit.text() == "Buy oat milk"
        assert dialog.priority_combo.currentData() == 1

    def test_tags_survive_more_typing(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk")
        dialog.tags_edit.setText("@home")
        type_line(dialog, "Buy milk tomorrow")
        assert dialog.tags_edit.text() == "@home"

    def test_recurrence_survives_more_typing(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk tomorrow")
        dialog.recurrence_checkbox.setChecked(True)
        type_line(dialog, "Buy milk tomorrow p1")
        assert dialog.recurrence_checkbox.isChecked()

    def test_advance_reminder_survives_more_typing(self, qtbot):
        dialog = open_advanced(qtbot, "Tax return tomorrow")
        editor = dialog.advance_reminder_editor
        editor.cadence_combo.setCurrentIndex(editor.cadence_combo.findData("once"))
        editor.days_spin.setValue(5)
        type_line(dialog, "Tax return tomorrow p1")
        assert editor.value() == (5, "once")

    def test_stored_task_has_the_hand_edits(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk tomorrow")
        dialog.priority_combo.setCurrentIndex(dialog.priority_combo.findData(3))
        type_line(dialog, "Buy milk tomorrow @errands")
        item = accepted(dialog)
        assert item.priority == 3
        assert item.tags == ["@errands"]


class TestTheLineTakesAFieldBack:
    def test_typed_priority_replaces_one_set_by_hand(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk")
        dialog.priority_combo.setCurrentIndex(dialog.priority_combo.findData(1))
        type_line(dialog, "Buy milk p3")
        assert dialog.priority_combo.currentData() == 3

    def test_typed_title_replaces_one_set_by_hand(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk")
        dialog.reminder_edit.setText("Buy oat milk")
        type_line(dialog, "Buy bread")
        assert dialog.reminder_edit.text() == "Buy bread"

    def test_typed_reminder_replaces_one_set_by_hand(self, qtbot):
        dialog = open_advanced(qtbot, "Tax return tomorrow")
        editor = dialog.advance_reminder_editor
        editor.cadence_combo.setCurrentIndex(editor.cadence_combo.findData("once"))
        type_line(dialog, "Tax return tomorrow remind me daily 4 days before")
        assert editor.value() == (4, "daily_until_due")


# ---------------------------------------------------------------------------
# The due date set by hand
# ---------------------------------------------------------------------------


class TestDueDateSetByHand:
    def test_survives_typing_about_something_else(self, qtbot):
        dialog = open_advanced(qtbot, "Dentist")
        set_date_by_hand(dialog, HAND_DATE)
        type_line(dialog, "Dentist p1")
        assert field_date(dialog) == HAND_DATE

    def test_is_not_replaced_by_a_date_inferred_from_a_time(self, qtbot):
        dialog = open_advanced(qtbot, "Dentist")
        set_date_by_hand(dialog, HAND_DATE)
        type_line(dialog, "Dentist at 3pm")
        assert field_date(dialog) == HAND_DATE
        assert dialog.due_time_edit.get_time() == time(15, 0)
        item = accepted(dialog)
        assert (item.due_date, item.due_time) == (HAND_DATE, time(15, 0))

    def test_survives_the_time_being_removed_again(self, qtbot):
        dialog = open_advanced(qtbot, "Dentist")
        set_date_by_hand(dialog, HAND_DATE)
        type_line(dialog, "Dentist at 3pm")
        type_line(dialog, "Dentist")
        assert field_date(dialog) == HAND_DATE
        assert not dialog.due_time_checkbox.isChecked()

    def test_date_changed_by_hand_after_the_line_set_it(self, qtbot):
        # The line ticked the date (inferred from the time); only the
        # date itself is then changed by hand.
        dialog = open_advanced(qtbot, "Dentist at 3pm")
        dialog.due_date_edit.setDate(QDate(HAND_DATE.year, HAND_DATE.month, HAND_DATE.day))
        type_line(dialog, "Dentist")
        assert field_date(dialog) == HAND_DATE

    def test_is_replaced_by_a_date_written_in_the_line(self, qtbot):
        dialog = open_advanced(qtbot, "Dentist")
        set_date_by_hand(dialog, HAND_DATE)
        type_line(dialog, "Dentist tomorrow")
        assert field_date(dialog) == TOMORROW

    def test_date_from_the_line_goes_when_its_words_go(self, qtbot):
        dialog = open_advanced(qtbot, "Dentist")
        set_date_by_hand(dialog, HAND_DATE)
        type_line(dialog, "Dentist tomorrow")
        type_line(dialog, "Dentist")
        assert field_date(dialog) is None

    def test_unticked_by_hand_stays_unticked_while_a_time_is_typed(self, qtbot):
        dialog = open_advanced(qtbot, "Dentist tomorrow")
        dialog.due_date_checkbox.setChecked(False)
        type_line(dialog, "Dentist tomorrow p1")
        assert field_date(dialog) is None

    def test_inferred_date_applies_when_none_was_set_by_hand(self, qtbot):
        dialog = open_advanced(qtbot, "Dentist at 3pm")
        assert field_date(dialog) is not None
        assert dialog.due_time_edit.get_time() == time(15, 0)

    def test_calendar_cell_date_is_not_a_hand_edit(self, qtbot):
        cell = date.today() + timedelta(days=9)
        dialog = open_advanced(qtbot, "Dentist", default_due_date=cell)
        assert field_date(dialog) == cell
        type_line(dialog, "Dentist tomorrow")
        assert field_date(dialog) == TOMORROW


# ---------------------------------------------------------------------------
# Opening and closing Advanced
# ---------------------------------------------------------------------------


class TestOpeningAndClosing:
    def test_opening_shows_what_was_typed(self, qtbot):
        dialog = AddTodoDialog()
        qtbot.addWidget(dialog)
        type_line(dialog, "Buy milk tomorrow p1 @errands")
        dialog._advanced_toggle.setChecked(True)
        assert dialog.reminder_edit.text() == "Buy milk"
        assert field_date(dialog) == TOMORROW
        assert dialog.priority_combo.currentData() == 1
        assert dialog.tags_edit.text() == "@errands"

    def test_closed_fields_mirror_the_line(self, qtbot):
        dialog = AddTodoDialog()
        qtbot.addWidget(dialog)
        type_line(dialog, "Buy milk p1")
        type_line(dialog, "Buy milk")
        assert dialog.priority_combo.currentData() == 2

    def test_reopening_shows_the_line_again(self, qtbot):
        # Closed, the task is built from the line, so a hand edit made
        # while open is not carried through a close and reopen.
        dialog = open_advanced(qtbot, "Buy milk")
        dialog.priority_combo.setCurrentIndex(dialog.priority_combo.findData(1))
        dialog._advanced_toggle.setChecked(False)
        dialog._advanced_toggle.setChecked(True)
        assert dialog.priority_combo.currentData() == 2

    def test_typing_after_reopening_changes_only_what_it_changes(self, qtbot):
        dialog = open_advanced(qtbot, "Buy milk")
        dialog._advanced_toggle.setChecked(False)
        dialog._advanced_toggle.setChecked(True)
        dialog.tags_edit.setText("@home")
        type_line(dialog, "Buy milk p1")
        assert dialog.tags_edit.text() == "@home"
        assert dialog.priority_combo.currentData() == 1
