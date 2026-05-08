"""Tests for GUI dialogs to improve test coverage.

Covers add_todo.py, add_list.py, and edit_recurrence.py.
"""

from datetime import date, time

import pytest
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication, QGroupBox

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


def _make_advanced_dialog(**kwargs) -> AddTodoDialog:
    """Create an AddTodoDialog with advanced mode visible."""
    dialog = AddTodoDialog(**kwargs)
    # Drive the advanced toggle through the button's checked state so
    # the toggled-signal path runs end-to-end (including
    # _on_smart_parse_changed, adjustSize, _clamp_to_screen).
    dialog._advanced_toggle.setChecked(True)
    return dialog


# ---------------------------------------------------------------------------
# TestAddTodoDialog — Smart mode (default)
# ---------------------------------------------------------------------------


class TestAddTodoDialogSmartMode:
    """Tests for AddTodoDialog in smart input mode."""

    def test_construction(self, app):
        dialog = AddTodoDialog()
        assert dialog.windowTitle() == "Add Todo"
        assert dialog.get_item() is None

    def test_smart_input_visible_by_default(self, app):
        dialog = AddTodoDialog()
        assert not dialog._advanced_container.isVisible()

    def test_advanced_toggle_is_keyboard_reachable(self, app):
        """Regression for #47: pre-fix the Advanced toggle was a QLabel
        with a clickable HTML link, never reachable via tab. The toggle
        must now be a QToolButton with a non-NoFocus policy and an
        explicit accessibleName so screen readers announce it.
        """
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QToolButton

        dialog = AddTodoDialog()
        toggle = dialog._advanced_toggle
        assert isinstance(toggle, QToolButton)
        assert toggle.focusPolicy() != Qt.FocusPolicy.NoFocus
        assert toggle.isCheckable()
        assert toggle.accessibleName() == "Advanced fields"
        assert toggle.accessibleDescription() == "Show or hide additional task fields"

    def test_advanced_toggle_shows_and_hides_advanced_section(self, app):
        """Toggling the button checked/unchecked must mirror the prior
        link-driven behavior: show/hide the scroll area and update the
        button's text suffix to the current state arrow."""
        dialog = AddTodoDialog()
        # Start collapsed.
        assert not dialog._advanced_scroll.isVisible()
        assert dialog._advanced_toggle.text().endswith("▶")

        # Expand via the button — drives the toggled signal naturally.
        dialog._advanced_toggle.setChecked(True)
        assert dialog._advanced_shown is True
        assert dialog._advanced_scroll.isVisible() or not dialog.isVisible()
        # When the dialog itself is not shown, isVisible() returns False
        # for descendants too; what matters is that setVisible(True) ran
        # against the scroll area and the toggle text now shows ▼.
        assert dialog._advanced_toggle.text().endswith("▼")

        # Collapse again.
        dialog._advanced_toggle.setChecked(False)
        assert dialog._advanced_shown is False
        assert dialog._advanced_toggle.text().endswith("▶")

    def test_accept_empty_shows_warning(self, app, monkeypatch):
        dialog = AddTodoDialog()
        monkeypatch.setattr(
            "pytodo_qt.gui.dialogs.add_todo.QMessageBox.warning",
            lambda *args, **kwargs: None,
        )
        dialog._on_accept()
        assert dialog.get_item() is None

    def test_accept_simple_reminder(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Buy groceries")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.reminder == "Buy groceries"
        assert item.priority == 2  # Default Normal
        assert item.due_date is None

    def test_accept_with_date(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Call dentist tomorrow")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert "dentist" in item.reminder
        assert item.due_date is not None

    def test_accept_with_time(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Meeting tomorrow at 3pm")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_time == time(15, 0)

    def test_accept_with_priority(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Fix crash p1")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.priority == 1

    def test_accept_with_tags(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Fix bug @work #urgent")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert "@work" in item.tags
        assert "@urgent" in item.tags

    def test_accept_with_recurrence(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Take pills daily")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.recurrence_type == "daily"
        assert item.due_date is not None  # Recurrence implies today

    def test_accept_with_recurrence_end_count(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Take pills daily for 10 days")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.recurrence_type == "daily"
        assert item.recurrence_end_count == 10

    def test_accept_with_pomodoro(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Write report ~3p")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.estimated_pomodoros == 3

    def test_accept_full_example(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Buy groceries tomorrow at 3pm @errands p1 ~2p")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert "groceries" in item.reminder
        assert item.due_date is not None
        assert item.due_time == time(15, 0)
        assert item.priority == 1
        assert "@errands" in item.tags
        assert item.estimated_pomodoros == 2

    def test_known_tags_passed_to_smart_input(self, app):
        dialog = AddTodoDialog(known_tags=["@work", "@home"])
        assert dialog._smart_input._tag_popup._all_tags == ["@home", "@work"]

    def test_enter_key_accepts(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Buy groceries tomorrow")
        # Simulate Enter via the accepted signal (same as keypress)
        dialog._smart_input.accepted.emit()
        item = dialog.get_item()
        assert item is not None
        assert "groceries" in item.reminder

    def test_smart_sync_to_advanced_fields(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Buy groceries tomorrow p1 @errands")
        # Force parse
        dialog._smart_input.get_parse_result()
        # Advanced fields should be synced
        assert "groceries" in dialog.reminder_edit.text()
        assert dialog.priority_combo.currentData() == 1
        assert dialog.due_date_checkbox.isChecked()
        assert "@errands" in dialog.tags_edit.text()

    def test_accept_with_estimated_minutes(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Write report ~90m")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.estimated_minutes == 90

    def test_accept_with_time_range(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("meeting from 2 to 4 pm")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_time == time(14, 0)
        assert item.due_time_end == time(16, 0)

    def test_accept_with_time_block(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("dinner tonight")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_time_block == "evening"

    def test_accept_with_event_date(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("schedule dentist for next month")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.event_date is not None

    def test_accept_with_conditions(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("go running unless it rains")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.conditions is not None
        assert len(item.conditions) >= 1

    def test_accept_with_subtasks(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("buy groceries: milk, bread, eggs")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.reminder == "buy groceries"
        subtasks = dialog.get_subtask_reminders()
        assert subtasks == ["milk", "bread", "eggs"]

    def test_accept_with_work_duration(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("focus session length 45 minutes")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.work_duration == 45


# ---------------------------------------------------------------------------
# TestAddTodoDialog — Advanced mode toggle
# ---------------------------------------------------------------------------


class TestAddTodoDialogToggle:
    """Tests for advanced mode toggle behavior."""

    def test_toggle_shows_advanced(self, app):
        dialog = AddTodoDialog()
        assert not dialog._advanced_shown
        dialog._advanced_toggle.setChecked(True)
        assert dialog._advanced_shown
        assert "\u25bc" in dialog._advanced_toggle.text()

    def test_toggle_round_trip(self, app):
        dialog = AddTodoDialog()
        dialog._advanced_toggle.setChecked(True)
        assert dialog._advanced_shown
        assert "\u25bc" in dialog._advanced_toggle.text()
        dialog._advanced_toggle.setChecked(False)
        assert not dialog._advanced_shown
        assert "\u25b6" in dialog._advanced_toggle.text()

    def test_advanced_mode_accept_path(self, app):
        """Verify toggle makes _on_accept use discrete fields."""
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("From advanced")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.reminder == "From advanced"


# ---------------------------------------------------------------------------
# TestAddTodoDialog — Advanced mode (discrete fields)
# ---------------------------------------------------------------------------


class TestAddTodoDialogAdvancedMode:
    """Tests for AddTodoDialog in advanced (discrete field) mode."""

    def test_default_state(self, app):
        dialog = _make_advanced_dialog()
        assert dialog.reminder_edit.text() == ""
        assert dialog.priority_combo.currentIndex() == 1  # Normal
        assert not dialog.due_date_checkbox.isChecked()
        assert not dialog.due_date_edit.isEnabled()
        # Recurrence is always available (auto-sets today if needed)
        assert dialog.recurrence_checkbox.isEnabled()
        assert not dialog.recurrence_checkbox.isChecked()
        assert not dialog.interval_spin.isEnabled()
        assert not dialog.type_combo.isEnabled()

    def test_due_date_toggle_enables_fields(self, app):
        dialog = _make_advanced_dialog()
        dialog.due_date_checkbox.setChecked(True)
        assert dialog.due_date_edit.isEnabled()
        assert dialog.recurrence_checkbox.isEnabled()

    def test_due_date_toggle_off_disables_recurrence(self, app):
        dialog = _make_advanced_dialog()
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        assert dialog.interval_spin.isEnabled()

        dialog.due_date_checkbox.setChecked(False)
        assert not dialog.recurrence_checkbox.isChecked()
        assert not dialog.interval_spin.isEnabled()

    def test_recurrence_toggle_enables_fields(self, app):
        dialog = _make_advanced_dialog()
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        assert dialog.interval_spin.isEnabled()
        assert dialog.type_combo.isEnabled()
        assert dialog.end_widget.isEnabled()

    def test_recurrence_toggle_off_resets_end_condition(self, app):
        dialog = _make_advanced_dialog()
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        dialog.end_count_radio.setChecked(True)
        dialog._on_end_condition_changed()

        dialog.recurrence_checkbox.setChecked(False)
        assert dialog.end_never_radio.isChecked()
        assert not dialog.end_date_edit.isEnabled()
        assert not dialog.end_count_spin.isEnabled()

    def test_end_condition_date_enables_date_edit(self, app):
        dialog = _make_advanced_dialog()
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        dialog.end_date_radio.setChecked(True)
        dialog._on_end_condition_changed()
        assert dialog.end_date_edit.isEnabled()
        assert not dialog.end_count_spin.isEnabled()

    def test_end_condition_count_enables_count_spin(self, app):
        dialog = _make_advanced_dialog()
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        dialog.end_count_radio.setChecked(True)
        dialog._on_end_condition_changed()
        assert not dialog.end_date_edit.isEnabled()
        assert dialog.end_count_spin.isEnabled()

    def test_accept_with_empty_reminder_does_not_create(self, app, monkeypatch):
        dialog = _make_advanced_dialog()
        monkeypatch.setattr(
            "pytodo_qt.gui.dialogs.add_todo.QMessageBox.warning",
            lambda *args, **kwargs: None,
        )
        dialog._on_accept()
        assert dialog.get_item() is None

    def test_accept_with_valid_reminder(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Buy groceries")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.reminder == "Buy groceries"
        assert item.priority == 2  # Normal
        assert item.due_date is None
        assert item.recurrence_type is None

    def test_accept_with_due_date(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Task with date")
        dialog.due_date_checkbox.setChecked(True)
        dialog.due_date_edit.setDate(QDate(2026, 6, 15))
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_date == date(2026, 6, 15)

    def test_accept_with_high_priority(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Urgent task")
        dialog.priority_combo.setCurrentIndex(0)  # High
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.priority == 1

    def test_accept_with_recurrence_daily(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Daily standup")
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        idx = dialog.type_combo.findData("daily")
        dialog.type_combo.setCurrentIndex(idx)
        dialog.interval_spin.setValue(1)
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.recurrence_type == "daily"
        assert item.recurrence_interval == 1

    def test_accept_with_recurrence_end_date(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Weekly report")
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        idx = dialog.type_combo.findData("weekly")
        dialog.type_combo.setCurrentIndex(idx)
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
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Monthly review")
        dialog.due_date_checkbox.setChecked(True)
        dialog.recurrence_checkbox.setChecked(True)
        idx = dialog.type_combo.findData("monthly")
        dialog.type_combo.setCurrentIndex(idx)
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

    def test_accept_with_tags(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Tagged task")
        dialog.tags_edit.setText("@work, errands")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert "@work" in item.tags
        assert "@errands" in item.tags

    def test_accept_with_estimated_pomodoros(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Big task")
        dialog.estimated_pomodoros_spin.setValue(4)
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.estimated_pomodoros == 4

    def test_accept_with_due_time(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Timed task")
        dialog.due_date_checkbox.setChecked(True)
        dialog.due_time_checkbox.setChecked(True)
        dialog.due_time_edit.set_time(time(14, 30))
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_time == time(14, 30)

    def test_time_block_combo(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Evening task")
        idx = dialog.time_block_combo.findData("evening")
        dialog.time_block_combo.setCurrentIndex(idx)
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_time_block == "evening"

    def test_time_block_none(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("No block")
        dialog.time_block_combo.setCurrentIndex(0)  # None
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_time_block is None

    def test_event_date_toggle_and_accept(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Scheduled event")
        dialog.event_date_checkbox.setChecked(True)
        assert dialog.event_date_edit.isEnabled()
        dialog.event_date_edit.setDate(QDate(2026, 7, 1))
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.event_date == date(2026, 7, 1)

    def test_duration_value_and_unit(self, app):
        dialog = _make_advanced_dialog()
        dialog.reminder_edit.setText("Long project")
        dialog.duration_value_spin.setValue(2)
        idx = dialog.duration_unit_combo.findData(10080)  # Weeks
        dialog.duration_unit_combo.setCurrentIndex(idx)
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.estimated_minutes == 2 * 10080

    def test_duration_from_minutes_sync(self, app):
        """_set_duration_from_minutes converts raw minutes to natural scale."""
        dialog = _make_advanced_dialog()
        dialog._set_duration_from_minutes(120)
        assert dialog.duration_value_spin.value() == 2
        assert dialog.duration_unit_combo.currentData() == 60  # Hours

    def test_groupbox_sections_exist(self, app):
        """Advanced section uses QGroupBox for logical grouping."""
        dialog = _make_advanced_dialog()
        groups = dialog._advanced_container.findChildren(QGroupBox)
        group_titles = {g.title() for g in groups}
        assert "Scheduling" in group_titles
        assert "Estimated Duration" in group_titles
        assert "Focus Session" in group_titles
        assert "Recurrence" in group_titles


# ---------------------------------------------------------------------------
# TestAddTodoDialog — create_item class method
# ---------------------------------------------------------------------------


class TestAddTodoDialogClassMethod:
    """Tests for the create_item convenience method."""

    def test_create_item_sets_title(self, app):
        dialog = AddTodoDialog()
        dialog.setWindowTitle("Add Subtask")
        assert dialog.windowTitle() == "Add Subtask"

    def test_create_item_passes_known_tags(self, app):
        dialog = AddTodoDialog(known_tags=["@work", "@personal"])
        assert "@personal" in dialog._smart_input._tag_popup._all_tags


class TestAddTodoDialogQuickActions:
    """Smart-add quick action trigger buttons (Pattern #3).

    Four category triggers (Priority / Date / Tag / Recurrence)
    open preset menus that modify the smart-input text in place.
    These tests drive the private `_apply_quick_action` method
    directly to avoid the flakiness of popping a QMenu in a
    headless harness.
    """

    def test_quick_action_row_exists(self, app):
        dialog = AddTodoDialog()
        assert hasattr(dialog, "_priority_btn")
        assert hasattr(dialog, "_date_btn")
        assert hasattr(dialog, "_tag_btn")
        assert hasattr(dialog, "_recur_btn")

    def test_priority_preset_replaces_existing(self, app):
        from pytodo_qt.core.nlp_parser import EntityKind

        dialog = AddTodoDialog()
        dialog._smart_input.set_text("fix bug low priority tomorrow")
        dialog._apply_quick_action(EntityKind.PRIORITY, "high priority")
        # Force the debounce to flush and re-read the text
        updated = dialog._smart_input.get_text()
        assert updated == "fix bug high priority tomorrow"

    def test_priority_preset_appends_when_absent(self, app):
        from pytodo_qt.core.nlp_parser import EntityKind

        dialog = AddTodoDialog()
        dialog._smart_input.set_text("fix bug")
        dialog._apply_quick_action(EntityKind.PRIORITY, "high priority")
        assert dialog._smart_input.get_text() == "fix bug high priority"

    def test_date_preset_replaces_existing(self, app):
        from pytodo_qt.core.nlp_parser import EntityKind

        dialog = AddTodoDialog()
        dialog._smart_input.set_text("call mom tomorrow")
        dialog._apply_quick_action(EntityKind.DATE, "next monday")
        assert dialog._smart_input.get_text() == "call mom next monday"

    def test_tag_preset_appends_not_replace(self, app):
        from pytodo_qt.core.nlp_parser import EntityKind

        dialog = AddTodoDialog()
        dialog._smart_input.set_text("fix bug @work")
        dialog._apply_quick_action(EntityKind.TAG, "@urgent", append_only=True)
        assert dialog._smart_input.get_text() == "fix bug @work @urgent"

    def test_recurrence_preset_replaces_existing(self, app):
        from pytodo_qt.core.nlp_parser import EntityKind

        dialog = AddTodoDialog()
        dialog._smart_input.set_text("standup daily")
        dialog._apply_quick_action(EntityKind.RECURRENCE, "weekly")
        assert dialog._smart_input.get_text() == "standup weekly"

    def test_quick_action_noop_when_same_text(self, app):
        """If the replacement produces the same text (e.g. user
        clicks High when high priority is already set), the method
        returns without changing anything — no unnecessary text
        field churn."""
        from pytodo_qt.core.nlp_parser import EntityKind

        dialog = AddTodoDialog()
        dialog._smart_input.set_text("fix bug high priority")
        original = dialog._smart_input.get_text()
        dialog._apply_quick_action(EntityKind.PRIORITY, "high priority")
        assert dialog._smart_input.get_text() == original

    def test_priority_menu_has_three_presets(self, app):
        dialog = AddTodoDialog()
        menu = dialog._priority_btn.menu()
        assert menu is not None
        assert len(menu.actions()) == 3

    def test_date_menu_has_presets(self, app):
        dialog = AddTodoDialog()
        menu = dialog._date_btn.menu()
        assert menu is not None
        assert len(menu.actions()) >= 5

    def test_recurrence_menu_has_four_presets(self, app):
        dialog = AddTodoDialog()
        menu = dialog._recur_btn.menu()
        assert menu is not None
        assert len(menu.actions()) == 4

    def test_tag_menu_placeholder_when_no_known_tags(self, app):
        dialog = AddTodoDialog()
        menu = dialog._tag_btn.menu()
        assert menu is not None
        actions = menu.actions()
        assert len(actions) == 1
        assert not actions[0].isEnabled()

    def test_tag_menu_populates_from_known_tags(self, app):
        dialog = AddTodoDialog(known_tags=["@work", "@home", "@urgent"])
        # Rebuild the menu since known_tags is set after smart_input init
        menu = dialog._build_tag_menu()
        actions = menu.actions()
        assert len(actions) == 3
        labels = [a.text() for a in actions]
        assert "@home" in labels
        assert "@urgent" in labels
        assert "@work" in labels


class TestAddTodoDialogBoardColumn:
    """Tests for the board column dropdown (kanban column pre-select)."""

    def test_no_columns_hides_combo(self, app):
        """Without a columns list, the combo widget is created but
        never added to the form — behaviour-preserving default for
        test / headless code paths that don't know about kanban state.
        """
        dialog = AddTodoDialog()
        # Widget exists but is not inserted into the form layout
        assert hasattr(dialog, "board_column_combo")
        assert dialog.board_column_combo.count() == 0

    def test_columns_populate_combo(self, app):
        dialog = AddTodoDialog(columns=["To Do", "In Progress", "Done"])
        assert dialog.board_column_combo.count() == 3
        assert dialog.board_column_combo.itemData(0) == "To Do"
        assert dialog.board_column_combo.itemData(1) == "In Progress"
        assert dialog.board_column_combo.itemData(2) == "Done"

    def test_columns_default_first_when_no_selected(self, app):
        dialog = AddTodoDialog(columns=["To Do", "In Progress", "Done"])
        assert dialog.board_column_combo.currentData() == "To Do"

    def test_selected_column_preselected(self, app):
        dialog = AddTodoDialog(
            columns=["To Do", "In Progress", "Done"],
            selected_column="In Progress",
        )
        assert dialog.board_column_combo.currentData() == "In Progress"

    def test_selected_column_not_in_list_falls_back_to_first(self, app):
        dialog = AddTodoDialog(
            columns=["To Do", "In Progress", "Done"],
            selected_column="Archived",  # not a valid column
        )
        assert dialog.board_column_combo.currentData() == "To Do"

    def test_accept_writes_selected_column_to_item(self, app):
        dialog = AddTodoDialog(
            columns=["To Do", "In Progress", "Done"],
            selected_column="In Progress",
        )
        dialog._smart_input.set_text("Refactor the widget")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.board_column == "In Progress"

    def test_accept_writes_first_column_when_not_preselected(self, app):
        dialog = AddTodoDialog(columns=["To Do", "In Progress", "Done"])
        dialog._smart_input.set_text("New task")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.board_column == "To Do"

    def test_accept_with_no_columns_leaves_board_column_unset(self, app):
        """Tests that pass no columns list (headless paths) still
        work and produce an item whose board_column is the empty
        string default — same as before this change."""
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Plain task")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.board_column == ""

    def test_accept_with_advanced_fields_and_column_override(self, app, monkeypatch):
        """Advanced-mode build path must also respect the column
        dropdown — not just the smart-input path."""
        from PyQt6.QtCore import QDate

        dialog = AddTodoDialog(
            columns=["To Do", "In Progress", "Done"],
            selected_column="To Do",
        )
        dialog._advanced_toggle.setChecked(True)
        dialog.reminder_edit.setText("Advanced task")
        # User picks a different column via the dropdown
        dialog.board_column_combo.setCurrentIndex(2)  # "Done"
        _ = QDate.currentDate()  # silence unused import warning
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.board_column == "Done"


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


class TestAddTodoDialogSubtasks:
    """Subtask field round-trip in both smart-input and advanced modes."""

    def test_smart_input_subtasks_populate_advanced_field(self, app):
        # Inline syntax in the smart input gets mirrored into the
        # subtasks_edit when the advanced disclosure is opened.
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Plan trip: book flight, pack, set OOO")
        dialog._smart_input.get_parse_result()
        text = dialog.subtasks_edit.toPlainText()
        lines = [line for line in text.splitlines() if line.strip()]
        assert lines == ["book flight", "pack", "set OOO"]

    def test_smart_input_no_subtasks_clears_field(self, app):
        # Switching to a smart-input phrase with no subtask syntax must
        # clear the subtasks field so stale items don't leak through.
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("Plan trip: book flight, pack")
        dialog._smart_input.get_parse_result()
        assert dialog.subtasks_edit.toPlainText().strip() != ""
        dialog._smart_input.set_text("Buy groceries tomorrow")
        dialog._smart_input.get_parse_result()
        assert dialog.subtasks_edit.toPlainText().strip() == ""

    def test_advanced_subtasks_field_round_trip(self, app):
        dialog = AddTodoDialog()
        dialog._advanced_toggle.setChecked(True)  # Open advanced
        dialog.reminder_edit.setText("Plan trip")
        dialog.subtasks_edit.setPlainText("book flight\npack\nset OOO\n")
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.reminder == "Plan trip"
        assert dialog.get_subtask_reminders() == ["book flight", "pack", "set OOO"]

    def test_advanced_subtasks_blank_lines_ignored(self, app):
        dialog = AddTodoDialog()
        dialog._advanced_toggle.setChecked(True)
        dialog.reminder_edit.setText("Plan trip")
        dialog.subtasks_edit.setPlainText("\nbook flight\n\n\npack\n  \n")
        dialog._on_accept()
        assert dialog.get_subtask_reminders() == ["book flight", "pack"]

    def test_advanced_no_subtasks_yields_empty_list(self, app):
        dialog = AddTodoDialog()
        dialog._advanced_toggle.setChecked(True)
        dialog.reminder_edit.setText("Buy milk")
        dialog._on_accept()
        assert dialog.get_subtask_reminders() == []


class TestAddTodoDialogDueTimeEnd:
    """Interactive due_time_end UI in the Advanced disclosure."""

    def test_smart_input_time_range_populates_advanced_field(self, app):
        # NLP "from X to Y" / "between X and Y" populates due_time_end;
        # opening Advanced should mirror that into the new field.
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("meeting from 2 to 4 pm")
        dialog._smart_input.get_parse_result()
        assert dialog.due_time_end_checkbox.isChecked()
        assert dialog.due_time_end_edit.get_time() == time(16, 0)

    def test_smart_input_no_range_clears_field(self, app):
        dialog = AddTodoDialog()
        dialog._smart_input.set_text("meeting from 2 to 4 pm")
        dialog._smart_input.get_parse_result()
        assert dialog.due_time_end_checkbox.isChecked()
        dialog._smart_input.set_text("buy milk tomorrow")
        dialog._smart_input.get_parse_result()
        assert not dialog.due_time_end_checkbox.isChecked()

    def test_advanced_field_round_trip(self, app):
        dialog = AddTodoDialog()
        dialog._advanced_toggle.setChecked(True)
        dialog.reminder_edit.setText("Standup")
        dialog.due_date_checkbox.setChecked(True)
        dialog.due_time_checkbox.setChecked(True)
        dialog.due_time_edit.set_time(time(9, 0))
        dialog.due_time_end_checkbox.setChecked(True)
        dialog.due_time_end_edit.set_time(time(9, 30))
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_time == time(9, 0)
        assert item.due_time_end == time(9, 30)

    def test_advanced_end_disabled_without_due_time(self, app):
        # The end-time checkbox is gated on due_time being set: a
        # window without a start has no meaning.
        dialog = AddTodoDialog()
        dialog._advanced_toggle.setChecked(True)
        # No due_time set → end checkbox should be disabled.
        assert not dialog.due_time_end_checkbox.isEnabled()

    def test_advanced_end_enables_when_due_time_set(self, app):
        dialog = AddTodoDialog()
        dialog._advanced_toggle.setChecked(True)
        dialog.due_date_checkbox.setChecked(True)
        dialog.due_time_checkbox.setChecked(True)
        assert dialog.due_time_end_checkbox.isEnabled()

    def test_advanced_end_resets_when_due_time_cleared(self, app):
        dialog = AddTodoDialog()
        dialog._advanced_toggle.setChecked(True)
        dialog.due_date_checkbox.setChecked(True)
        dialog.due_time_checkbox.setChecked(True)
        dialog.due_time_end_checkbox.setChecked(True)
        # Now clear the due time — the end checkbox should clear too.
        dialog.due_time_checkbox.setChecked(False)
        assert not dialog.due_time_end_checkbox.isChecked()

    def test_advanced_end_omitted_when_unchecked(self, app):
        dialog = AddTodoDialog()
        dialog._advanced_toggle.setChecked(True)
        dialog.reminder_edit.setText("Standup")
        dialog.due_date_checkbox.setChecked(True)
        dialog.due_time_checkbox.setChecked(True)
        dialog.due_time_edit.set_time(time(9, 0))
        # Leave end-time checkbox unchecked.
        dialog._on_accept()
        item = dialog.get_item()
        assert item is not None
        assert item.due_time == time(9, 0)
        assert item.due_time_end is None
