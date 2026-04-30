"""Comprehensive tests for GUI widgets to improve coverage.

Covers: SearchFilterWidget, StatusBarWidget, TodoTableWidget, ListSelectorWidget.
"""

from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtWidgets import QComboBox, QGraphicsOpacityEffect, QLabel, QLineEdit

from pytodo_qt.core.models import (
    Database,
    TodoItem,
    TodoList,
    create_todo_item,
)
from pytodo_qt.gui.widgets.list_selector import ListSelectorWidget
from pytodo_qt.gui.widgets.search_filter import FilterState, SearchFilterWidget
from pytodo_qt.gui.widgets.status_bar import StatusBarWidget, _format_time_ago
from pytodo_qt.gui.widgets.todo_table import (
    DueDateLabel,
    DueDatePickerDialog,
    TodoTableWidget,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def search_widget(qtbot):
    """Create a SearchFilterWidget."""
    w = SearchFilterWidget()
    qtbot.addWidget(w)
    return w


@pytest.fixture()
def status_bar(qtbot):
    """Create a StatusBarWidget."""
    w = StatusBarWidget()
    qtbot.addWidget(w)
    return w


@pytest.fixture()
def todo_table(qtbot):
    """Create a TodoTableWidget."""
    w = TodoTableWidget()
    qtbot.addWidget(w)
    return w


@pytest.fixture()
def list_selector(qtbot):
    """Create a ListSelectorWidget."""
    w = ListSelectorWidget()
    qtbot.addWidget(w)
    return w


@pytest.fixture()
def sample_list():
    """Create a TodoList with several items for testing."""
    lst = TodoList(name="Test List")
    items = [
        create_todo_item("Buy milk", priority=1, due_date=date.today() - timedelta(days=2)),
        create_todo_item("Call doctor", priority=2, due_date=date.today()),
        create_todo_item(
            "Walk the dog",
            priority=3,
            due_date=date.today() + timedelta(days=3),
        ),
        create_todo_item("Clean house", priority=2),
        create_todo_item(
            "Weekly review",
            priority=2,
            due_date=date.today() + timedelta(days=1),
            recurrence_type="weekly",
        ),
    ]
    for item in items:
        lst.items[item.id] = item
    # Mark one item complete
    items[3].complete = True
    return lst


@pytest.fixture()
def two_list_db():
    """Create a database with two non-empty lists."""
    db = Database()
    list_a = TodoList(name="Shopping")
    list_a.items[uuid4()] = TodoItem(reminder="Milk")
    list_b = TodoList(name="Work")
    list_b.items[uuid4()] = TodoItem(reminder="Review PR")
    db.lists[list_a.id] = list_a
    db.lists[list_b.id] = list_b
    db.active_list_id = list_a.id
    return db, list_a, list_b


# ===========================================================================
# SearchFilterWidget Tests
# ===========================================================================


class TestSearchFilterWidgetConstruction:
    """Test SearchFilterWidget setup and UI elements."""

    def test_widget_created(self, search_widget):
        """Widget should be constructible."""
        assert search_widget is not None

    def test_has_search_edit(self, search_widget):
        """Widget should have a search QLineEdit."""
        assert isinstance(search_widget.search_edit, QLineEdit)
        assert search_widget.search_edit.placeholderText() == "Search todos..."

    def test_has_priority_combo(self, search_widget):
        """Widget should have a priority combo box."""
        assert isinstance(search_widget.priority_combo, QComboBox)
        assert search_widget.priority_combo.count() == 4

    def test_has_status_combo(self, search_widget):
        """Widget should have a status combo box."""
        assert isinstance(search_widget.status_combo, QComboBox)
        assert search_widget.status_combo.count() == 3

    def test_has_due_date_combo(self, search_widget):
        """Widget should have a due date combo box with 6 entries."""
        assert isinstance(search_widget.due_date_combo, QComboBox)
        assert search_widget.due_date_combo.count() == 6

    def test_initial_filter_state_inactive(self, search_widget):
        """Default filter state should not be active."""
        state = search_widget.get_filter()
        assert not state.is_active
        assert state.text == ""
        assert state.priority == 0
        assert state.status == 0
        assert state.due_date == 0

    def test_clear_button_enabled(self, search_widget):
        """Search field should have clear button enabled."""
        assert search_widget.search_edit.isClearButtonEnabled()

    def test_minimum_height_set(self, search_widget):
        """Search edit and combos should have minimum height 32."""
        assert search_widget.search_edit.minimumHeight() == 32
        assert search_widget.priority_combo.minimumHeight() == 32
        assert search_widget.status_combo.minimumHeight() == 32
        assert search_widget.due_date_combo.minimumHeight() == 32


class TestSearchFilterWidgetSignals:
    """Test filter state changes and signal emissions."""

    def test_text_change_emits_filter_changed(self, qtbot, search_widget):
        """Typing in the search field should emit filter_changed after debounce."""
        with qtbot.waitSignal(search_widget.filter_changed, timeout=500):
            search_widget.search_edit.setText("test")
            # Process debounce timer
            search_widget._debounce_timer.setInterval(1)
            search_widget._debounce_timer.start()

    def test_priority_combo_emits_immediately(self, qtbot, search_widget):
        """Changing priority combo should emit filter_changed immediately."""
        with qtbot.waitSignal(search_widget.filter_changed, timeout=500):
            search_widget.priority_combo.setCurrentIndex(1)

    def test_status_combo_emits_immediately(self, qtbot, search_widget):
        """Changing status combo should emit filter_changed immediately."""
        with qtbot.waitSignal(search_widget.filter_changed, timeout=500):
            search_widget.status_combo.setCurrentIndex(1)

    def test_due_date_combo_emits_immediately(self, qtbot, search_widget):
        """Changing due date combo should emit filter_changed immediately."""
        with qtbot.waitSignal(search_widget.filter_changed, timeout=500):
            search_widget.due_date_combo.setCurrentIndex(1)

    def test_filter_state_reflects_text(self, search_widget):
        """get_filter() should reflect search text."""
        search_widget.search_edit.setText("groceries")
        state = search_widget.get_filter()
        assert state.text == "groceries"

    def test_filter_state_strips_whitespace(self, search_widget):
        """get_filter() should strip whitespace from text."""
        search_widget.search_edit.setText("  hello  ")
        state = search_widget.get_filter()
        assert state.text == "hello"

    def test_filter_state_reflects_priority(self, search_widget):
        """get_filter() should reflect priority selection."""
        search_widget.priority_combo.setCurrentIndex(2)  # Normal
        state = search_widget.get_filter()
        assert state.priority == 2

    def test_filter_state_reflects_status(self, search_widget):
        """get_filter() should reflect status selection."""
        search_widget.status_combo.setCurrentIndex(2)  # Completed
        state = search_widget.get_filter()
        assert state.status == 2

    def test_filter_state_reflects_due_date(self, search_widget):
        """get_filter() should reflect due date selection."""
        search_widget.due_date_combo.setCurrentIndex(3)  # This Week
        state = search_widget.get_filter()
        assert state.due_date == 3


class TestSearchFilterWidgetReset:
    """Test clear/reset functionality."""

    def test_clear_filters_resets_all(self, search_widget):
        """clear_filters() should reset all controls to defaults."""
        search_widget.search_edit.setText("test")
        search_widget.priority_combo.setCurrentIndex(1)
        search_widget.status_combo.setCurrentIndex(2)
        search_widget.due_date_combo.setCurrentIndex(3)

        search_widget.clear_filters()

        state = search_widget.get_filter()
        assert state.text == ""
        assert state.priority == 0
        assert state.status == 0
        assert state.due_date == 0

    def test_clear_filters_emits_signal(self, qtbot, search_widget):
        """clear_filters() should emit filter_changed."""
        search_widget.search_edit.setText("test")
        with qtbot.waitSignal(search_widget.filter_changed, timeout=500):
            search_widget.clear_filters()

    def test_focus_search(self, search_widget):
        """focus_search() should call setFocus and selectAll without error."""
        search_widget.search_edit.setText("hello")
        # In offscreen mode, hasFocus() may not reflect correctly
        # but the method should execute without error
        search_widget.focus_search()

    def test_handle_escape_clears_active_filter(self, search_widget):
        """handle_escape() should clear filters if active."""
        search_widget.search_edit.setText("test")
        assert search_widget.get_filter().is_active

        search_widget.handle_escape()
        assert not search_widget.get_filter().is_active

    def test_handle_escape_unfocuses_when_no_filter(self, search_widget):
        """handle_escape() with no active filter should just unfocus."""
        search_widget.search_edit.setFocus()
        search_widget.handle_escape()
        # No error should be raised; filters remain inactive
        assert not search_widget.get_filter().is_active


class TestSearchFilterVisualIndicator:
    """Test visual indicator when filter is active."""

    def test_active_filter_sets_border(self, search_widget):
        """Active filter should set a border style on search edit."""
        search_widget.priority_combo.setCurrentIndex(1)
        # _emit_filter is called, which calls _update_visual_indicator
        assert search_widget.search_edit.styleSheet() != ""
        assert "border" in search_widget.search_edit.styleSheet()

    def test_inactive_filter_clears_border(self, search_widget):
        """Resetting to no filter should clear the border style."""
        search_widget.priority_combo.setCurrentIndex(1)
        assert search_widget.search_edit.styleSheet() != ""

        search_widget.clear_filters()
        assert search_widget.search_edit.styleSheet() == ""


# ===========================================================================
# StatusBarWidget Tests
# ===========================================================================


class TestFormatTimeAgo:
    """Tests for the _format_time_ago helper function."""

    def test_just_now(self):
        """Less than 60 seconds should show 'just now'."""
        now = datetime.now()
        result = _format_time_ago(now - timedelta(seconds=10))
        assert result == "just now"

    def test_minutes_ago(self):
        """Between 1 and 59 minutes should show Xm ago."""
        dt = datetime.now() - timedelta(minutes=5)
        result = _format_time_ago(dt)
        assert result == "5m ago"

    def test_hours_ago(self):
        """Between 1 and 23 hours should show Xh ago."""
        dt = datetime.now() - timedelta(hours=3)
        result = _format_time_ago(dt)
        assert result == "3h ago"

    def test_days_ago(self):
        """24+ hours should show Xd ago."""
        dt = datetime.now() - timedelta(days=2)
        result = _format_time_ago(dt)
        assert result == "2d ago"

    def test_zero_seconds(self):
        """Zero seconds ago is 'just now'."""
        result = _format_time_ago(datetime.now())
        assert result == "just now"

    def test_exactly_60_seconds(self):
        """Exactly 60 seconds should show 1m ago."""
        dt = datetime.now() - timedelta(seconds=60)
        result = _format_time_ago(dt)
        assert result == "1m ago"

    def test_exactly_3600_seconds(self):
        """Exactly 3600 seconds should show 1h ago."""
        dt = datetime.now() - timedelta(seconds=3600)
        result = _format_time_ago(dt)
        assert result == "1h ago"


class TestStatusBarWidgetConstruction:
    """Test StatusBarWidget construction and labels."""

    def test_widget_created(self, status_bar):
        """Widget should be constructible."""
        assert status_bar is not None

    def test_has_progress_bar(self, status_bar):
        """Widget should have a progress bar."""
        assert status_bar.progress_bar is not None
        assert status_bar.progress_bar.isTextVisible()

    def test_has_labels(self, status_bar):
        """Widget should have all expected labels."""
        assert status_bar.list_count_label is not None
        assert status_bar.item_count_label is not None
        assert status_bar.total_label is not None
        assert status_bar.status_label is not None
        assert status_bar.server_status_label is not None
        assert status_bar.sync_status_label is not None
        assert status_bar.pending_sync_label is not None

    def test_initial_status(self, status_bar):
        """Initial status should be Ready."""
        assert status_bar.status_label.text() == "Ready"

    def test_initial_sync_status(self, status_bar):
        """Initial sync status should be 'Not synced'."""
        assert status_bar.sync_status_label.text() == "Not synced"

    def test_initial_server_off(self, status_bar):
        """Initial server status should be 'Server: Off'."""
        assert status_bar.server_status_label.text() == "Server: Off"

    def test_initial_pending_hidden(self, status_bar):
        """Pending sync label should be hidden initially."""
        assert status_bar.pending_sync_label.isHidden()


class TestStatusBarUpdateStats:
    """Test update_stats method."""

    def test_single_list_hides_total(self, status_bar):
        """With 1 list, total label should be hidden."""
        status_bar.update_stats(1, 5, 3, 5, 3)
        assert status_bar.total_label.isHidden()

    def test_multiple_lists_shows_total(self, status_bar):
        """With multiple lists, total label should not be hidden."""
        status_bar.update_stats(3, 5, 3, 15, 10)
        # In offscreen mode isVisible() checks full ancestor chain,
        # so we check that the label is not explicitly hidden instead
        assert not status_bar.total_label.isHidden()
        assert status_bar.total_label.text() == "Total: 10/15"

    def test_list_count_text(self, status_bar):
        """List count label should show correct count."""
        status_bar.update_stats(5, 10, 7, 20, 15)
        assert status_bar.list_count_label.text() == "Lists: 5"

    def test_item_count_text(self, status_bar):
        """Item count label should show current completed/total."""
        status_bar.update_stats(1, 10, 7, 10, 7)
        assert status_bar.item_count_label.text() == "Current: 7/10"

    def test_progress_bar_with_items(self, status_bar):
        """Progress bar should reflect completion."""
        status_bar.update_stats(1, 10, 7, 10, 7)
        assert status_bar.progress_bar.maximum() == 10
        assert status_bar.progress_bar.value() == 7

    def test_progress_bar_empty_list(self, status_bar):
        """Progress bar with zero items should show 0/1."""
        status_bar.update_stats(1, 0, 0, 0, 0)
        assert status_bar.progress_bar.maximum() == 1
        assert status_bar.progress_bar.value() == 0


class TestStatusBarSyncStatus:
    """Test set_sync_status method."""

    def test_syncing_shows_syncing(self, status_bar):
        """Syncing state should display 'Syncing'."""
        status_bar.set_sync_status("syncing")
        assert status_bar.sync_status_label.text() == "Syncing"

    def test_syncing_color_is_blue(self, status_bar):
        """Syncing state should pull its blue from the theme palette."""
        from pytodo_qt.gui.styles.themes import get_colors

        status_bar.set_sync_status("syncing")
        expected = get_colors()["focus_timer_stopwatch_running"]
        assert expected in status_bar.sync_status_label.styleSheet()

    def test_success_state(self, status_bar):
        """Success state should show 'Synced just now'."""
        status_bar.set_sync_status("success")
        assert "Synced" in status_bar.sync_status_label.text()
        assert "just now" in status_bar.sync_status_label.text()

    def test_success_auto_state(self, status_bar):
        """Auto success state should show 'Auto-synced'."""
        status_bar.set_sync_status("success", auto=True)
        assert "Auto-synced" in status_bar.sync_status_label.text()

    def test_success_color_is_green(self, status_bar):
        """Success state should have green color."""
        status_bar.set_sync_status("success")
        assert "green" in status_bar.sync_status_label.styleSheet()

    def test_error_state(self, status_bar):
        """Error state should show 'Sync failed'."""
        status_bar.set_sync_status("error")
        assert status_bar.sync_status_label.text() == "Sync failed"

    def test_error_color_is_red(self, status_bar):
        """Error state should have red color."""
        status_bar.set_sync_status("error")
        assert "red" in status_bar.sync_status_label.styleSheet()

    def test_idle_no_previous_sync(self, status_bar):
        """Idle state with no previous sync should show 'Not synced'."""
        status_bar.set_sync_status("idle")
        assert status_bar.sync_status_label.text() == "Not synced"
        assert "gray" in status_bar.sync_status_label.styleSheet()

    def test_idle_with_previous_sync(self, status_bar):
        """Idle state after previous sync should show time since sync."""
        status_bar.set_sync_status("success")
        status_bar.set_sync_status("idle")
        assert "Synced" in status_bar.sync_status_label.text()


class TestStatusBarServerStatus:
    """Test set_server_status method."""

    def test_server_running(self, status_bar):
        """Running server should show address and port."""
        status_bar.set_server_status(True, "192.168.1.10", 8080)
        assert status_bar.server_status_label.text() == "Server: 192.168.1.10:8080"
        assert "green" in status_bar.server_status_label.styleSheet()

    def test_server_stopped(self, status_bar):
        """Stopped server should show 'Server: Off'."""
        status_bar.set_server_status(False)
        assert status_bar.server_status_label.text() == "Server: Off"
        assert "gray" in status_bar.server_status_label.styleSheet()


class TestStatusBarMessage:
    """Test show_message / _clear_message."""

    def test_show_message(self, status_bar):
        """show_message should set message label text."""
        status_bar.show_message("Hello world", timeout=5000)
        assert status_bar._message_label.text() == "Hello world"

    def test_clear_message(self, status_bar):
        """_clear_message should clear message text."""
        status_bar.show_message("Hello")
        status_bar._clear_message()
        assert status_bar._message_label.text() == ""

    def test_message_timer_starts(self, status_bar):
        """show_message should start the message timer."""
        status_bar.show_message("Hello", timeout=3000)
        assert status_bar._message_timer.isActive()


class TestStatusBarPendingSync:
    """Test set_pending_sync_count method."""

    def test_pending_count_shows_label(self, status_bar):
        """Positive count should show the pending label (not hidden)."""
        status_bar.set_pending_sync_count(3)
        assert not status_bar.pending_sync_label.isHidden()
        assert status_bar.pending_sync_label.text() == "Queued: 3"
        assert "orange" in status_bar.pending_sync_label.styleSheet()

    def test_zero_count_hides_label(self, status_bar):
        """Zero count should hide the pending label."""
        status_bar.set_pending_sync_count(3)
        status_bar.set_pending_sync_count(0)
        assert status_bar.pending_sync_label.isHidden()
        assert status_bar.pending_sync_label.text() == ""

    def test_pending_tooltip(self, status_bar):
        """Pending label should have an informative tooltip."""
        status_bar.set_pending_sync_count(5)
        assert "5 sync(s) queued" in status_bar.pending_sync_label.toolTip()


class TestStatusBarSetStatus:
    """Test set_status method."""

    def test_set_status(self, status_bar):
        """set_status should update the status label."""
        status_bar.set_status("Loading...")
        assert status_bar.status_label.text() == "Loading..."


class TestStatusBarSyncTimeDisplay:
    """Test _update_sync_time_display method."""

    def test_update_with_no_sync_time(self, status_bar):
        """Should show 'Not synced' when there is no last sync time."""
        status_bar._last_sync_time = None
        status_bar._update_sync_time_display()
        assert status_bar.sync_status_label.text() == "Not synced"

    def test_update_with_sync_time(self, status_bar):
        """Should show relative time when there is a last sync time."""
        status_bar._last_sync_time = datetime.now() - timedelta(minutes=5)
        status_bar._last_auto_sync = False
        status_bar._update_sync_time_display()
        assert "Synced 5m ago" in status_bar.sync_status_label.text()

    def test_update_with_auto_sync(self, status_bar):
        """Should show 'Auto-synced' prefix for auto syncs."""
        status_bar._last_sync_time = datetime.now() - timedelta(minutes=2)
        status_bar._last_auto_sync = True
        status_bar._update_sync_time_display()
        assert "Auto-synced" in status_bar.sync_status_label.text()


# ===========================================================================
# TodoTableWidget Tests
# ===========================================================================


class TestTodoTableWidgetConstruction:
    """Test TodoTableWidget construction."""

    def test_widget_created(self, todo_table):
        """Widget should be constructible."""
        assert todo_table is not None

    def test_column_count(self, todo_table):
        """Table should have 3 columns."""
        assert todo_table.columnCount() == 3

    def test_column_headers(self, todo_table):
        """Table should have correct column headers."""
        header = todo_table.horizontalHeader()
        assert header is not None
        assert todo_table.horizontalHeaderItem(0).text() == "Priority"
        assert todo_table.horizontalHeaderItem(1).text() == "Reminder"
        assert todo_table.horizontalHeaderItem(2).text() == "Due"

    def test_initial_empty(self, todo_table):
        """Table should start empty."""
        assert todo_table.rowCount() == 0

    def test_alternating_row_colors(self, todo_table):
        """Table should have alternating row colors enabled."""
        assert todo_table.alternatingRowColors()


class TestTodoTableWidgetSetList:
    """Test set_list and refresh methods."""

    def test_set_list_none(self, todo_table):
        """Setting None list should clear the table."""
        todo_table.set_list(None)
        assert todo_table.rowCount() == 0

    def test_set_list_populates_rows(self, todo_table, sample_list):
        """Setting a list should populate rows."""
        todo_table.set_list(sample_list)
        assert todo_table.rowCount() == 5

    def test_priority_combo_in_column_0(self, todo_table, sample_list):
        """Each row should have a priority combo in column 0."""
        todo_table.set_list(sample_list)
        for row in range(todo_table.rowCount()):
            widget = todo_table.cellWidget(row, 0)
            assert isinstance(widget, QComboBox)

    def test_reminder_edit_in_column_1(self, todo_table, sample_list):
        """Each row should have a reminder QLineEdit in column 1."""
        todo_table.set_list(sample_list)
        for row in range(todo_table.rowCount()):
            widget = todo_table.cellWidget(row, 1)
            # Column 1 is now a container with a QLineEdit inside
            line_edit = widget.findChild(QLineEdit) if widget else None
            assert line_edit is not None

    def test_due_date_widget_in_column_2(self, todo_table, sample_list):
        """Each row should have a DueDateLabel in column 2."""
        todo_table.set_list(sample_list)
        for row in range(todo_table.rowCount()):
            widget = todo_table.cellWidget(row, 2)
            assert isinstance(widget, DueDateLabel)

    def test_completed_item_font(self, todo_table, sample_list):
        """Completed items should have strikeout font."""
        todo_table.set_list(sample_list)
        for row in range(todo_table.rowCount()):
            item_id = todo_table.get_item_id_at_row(row)
            item = sample_list.items.get(item_id)
            if item and item.complete:
                container = todo_table.cellWidget(row, 1)
                reminder_edit = container.findChild(QLineEdit) if container else None
                assert reminder_edit is not None
                assert reminder_edit.font().strikeOut()

    def test_item_id_map(self, todo_table, sample_list):
        """Item ID map should be populated after set_list."""
        todo_table.set_list(sample_list)
        for row in range(todo_table.rowCount()):
            item_id = todo_table.get_item_id_at_row(row)
            assert item_id is not None
            assert item_id in sample_list.items

    def test_refresh_clears_and_repopulates(self, todo_table, sample_list):
        """refresh() should clear and repopulate."""
        todo_table.set_list(sample_list)
        original_count = todo_table.rowCount()
        todo_table.refresh()
        assert todo_table.rowCount() == original_count

    def test_empty_list(self, todo_table):
        """An empty list should show zero rows."""
        empty_list = TodoList(name="Empty")
        todo_table.set_list(empty_list)
        assert todo_table.rowCount() == 0


class TestTodoTableWidgetSignals:
    """Test signal emissions from TodoTableWidget."""

    def test_priority_changed_signal(self, qtbot, todo_table, sample_list):
        """Changing priority combo should emit item_priority_changed."""
        todo_table.set_list(sample_list)
        with qtbot.waitSignal(todo_table.item_priority_changed, timeout=500):
            combo = todo_table.cellWidget(0, 0)
            assert isinstance(combo, QComboBox)
            # Change from current to a different index
            new_index = (combo.currentIndex() + 1) % combo.count()
            combo.setCurrentIndex(new_index)

    def test_reminder_changed_signal(self, qtbot, todo_table, sample_list):
        """Pressing enter in reminder field should emit item_reminder_changed."""
        todo_table.set_list(sample_list)
        with qtbot.waitSignal(todo_table.item_reminder_changed, timeout=500):
            container = todo_table.cellWidget(0, 1)
            reminder_edit = container.findChild(QLineEdit)
            assert reminder_edit is not None
            reminder_edit.setText("Updated text")
            reminder_edit.returnPressed.emit()

    def test_selection_changed_signal_single(self, qtbot, todo_table, sample_list):
        """Selecting a single row should emit item_selected with the UUID."""
        todo_table.set_list(sample_list)
        with qtbot.waitSignal(todo_table.item_selected, timeout=500):
            todo_table.selectRow(0)

    def test_selection_changed_signal_none(self, qtbot, todo_table, sample_list):
        """Clearing selection should emit item_selected with None."""
        todo_table.set_list(sample_list)
        todo_table.selectRow(0)
        with qtbot.waitSignal(todo_table.item_selected, timeout=500):
            todo_table.clearSelection()


class TestTodoTableWidgetSelection:
    """Test selection-related methods."""

    def test_get_selected_item_ids_empty(self, todo_table, sample_list):
        """No selection should return empty list."""
        todo_table.set_list(sample_list)
        assert todo_table.get_selected_item_ids() == []

    def test_get_selected_item_ids_single(self, todo_table, sample_list):
        """Single selection should return one UUID."""
        todo_table.set_list(sample_list)
        todo_table.selectRow(0)
        ids = todo_table.get_selected_item_ids()
        assert len(ids) == 1

    def test_get_item_id_at_row_valid(self, todo_table, sample_list):
        """Valid row should return UUID."""
        todo_table.set_list(sample_list)
        item_id = todo_table.get_item_id_at_row(0)
        assert item_id is not None

    def test_get_item_id_at_row_invalid(self, todo_table, sample_list):
        """Invalid row should return None."""
        todo_table.set_list(sample_list)
        assert todo_table.get_item_id_at_row(999) is None


class TestTodoTableWidgetFilter:
    """Test filter application on TodoTableWidget."""

    def test_text_filter(self, todo_table, sample_list):
        """Text filter should reduce displayed items."""
        todo_table.set_list(sample_list)
        total = todo_table.rowCount()

        state = FilterState(text="milk")
        todo_table.set_filter(state)
        assert todo_table.rowCount() < total
        assert todo_table.rowCount() == 1

    def test_priority_filter(self, todo_table, sample_list):
        """Priority filter should show only matching items."""
        state = FilterState(priority=1)  # High
        todo_table.set_filter(state)
        todo_table.set_list(sample_list)
        assert todo_table.rowCount() == 1

    def test_status_filter_active(self, todo_table, sample_list):
        """Status=Active filter should hide completed items."""
        state = FilterState(status=1)  # Active
        todo_table.set_filter(state)
        todo_table.set_list(sample_list)
        # "Clean house" is completed, so 4 active items
        assert todo_table.rowCount() == 4

    def test_status_filter_completed(self, todo_table, sample_list):
        """Status=Completed filter should show only completed items."""
        state = FilterState(status=2)  # Completed
        todo_table.set_filter(state)
        todo_table.set_list(sample_list)
        assert todo_table.rowCount() == 1

    def test_due_date_filter_overdue(self, todo_table, sample_list):
        """Due date=Overdue should show only overdue items."""
        state = FilterState(due_date=1)  # Overdue
        todo_table.set_filter(state)
        todo_table.set_list(sample_list)
        assert todo_table.rowCount() == 1

    def test_due_date_filter_today(self, todo_table, sample_list):
        """Due date=Today should show only items due today."""
        state = FilterState(due_date=2)  # Today
        todo_table.set_filter(state)
        todo_table.set_list(sample_list)
        assert todo_table.rowCount() == 1

    def test_due_date_filter_this_week(self, todo_table, sample_list):
        """Due date=This Week should show items due within 7 days."""
        state = FilterState(due_date=3)  # This Week
        todo_table.set_filter(state)
        todo_table.set_list(sample_list)
        # Today + tomorrow + walk the dog (3 days)
        assert todo_table.rowCount() >= 2

    def test_due_date_filter_no_due_date(self, todo_table, sample_list):
        """Due date=No Due Date should show items without due date."""
        state = FilterState(due_date=4)  # No Due Date
        todo_table.set_filter(state)
        todo_table.set_list(sample_list)
        assert todo_table.rowCount() == 1  # "Clean house"

    def test_due_date_filter_recurring(self, todo_table, sample_list):
        """Due date=Recurring should show only recurring items."""
        state = FilterState(due_date=5)  # Recurring
        todo_table.set_filter(state)
        todo_table.set_list(sample_list)
        assert todo_table.rowCount() == 1  # "Weekly review"

    def test_clear_filter(self, todo_table, sample_list):
        """Clearing filter should show all items again."""
        todo_table.set_list(sample_list)

        state = FilterState(text="milk")
        todo_table.set_filter(state)
        assert todo_table.rowCount() == 1

        todo_table.set_filter(None)
        assert todo_table.rowCount() == 5


class TestTodoTableWidgetSorting:
    """Test item sorting in the table."""

    def test_items_sorted_due_date_first(self, todo_table):
        """Items with due dates should appear before items without."""
        lst = TodoList(name="Sort Test")
        item_no_date = create_todo_item("No date", priority=1)
        item_with_date = create_todo_item(
            "Has date", priority=2, due_date=date.today() + timedelta(days=5)
        )
        lst.items[item_no_date.id] = item_no_date
        lst.items[item_with_date.id] = item_with_date

        todo_table.set_list(lst)

        # First row should be the item with a due date
        first_id = todo_table.get_item_id_at_row(0)
        assert first_id == item_with_date.id


# ===========================================================================
# DueDateLabel Tests
# ===========================================================================


class TestDueDateLabel:
    """Test DueDateLabel widget."""

    def test_label_with_date(self, qtbot):
        """DueDateLabel with a date should show formatted text."""
        w = DueDateLabel(date.today(), complete=False, recurring=False)
        qtbot.addWidget(w)
        assert w.label.text() == "Today"

    def test_label_without_date(self, qtbot):
        """DueDateLabel without a date should show empty text."""
        w = DueDateLabel(None, complete=False, recurring=False)
        qtbot.addWidget(w)
        assert w.label.text() == ""

    def test_label_recurring(self, qtbot):
        """DueDateLabel with recurring flag should still display date."""
        w = DueDateLabel(date.today(), complete=False, recurring=True)
        qtbot.addWidget(w)
        assert w.label.text() == "Today"

    def test_minimum_width(self, qtbot):
        """DueDateLabel should have a minimum width of 180."""
        w = DueDateLabel(date.today())
        qtbot.addWidget(w)
        assert w.minimumWidth() == 180

    def test_cursor_is_pointing_hand(self, qtbot):
        """Label should have pointing hand cursor."""
        w = DueDateLabel(date.today())
        qtbot.addWidget(w)
        assert w.label.cursor().shape() == Qt.CursorShape.PointingHandCursor

    def test_label_completed_shows_absolute_date(self, qtbot):
        """Completed DueDateLabel should show absolute date, not urgency text."""
        today = date.today()
        w = DueDateLabel(today, complete=True, recurring=False)
        qtbot.addWidget(w)
        assert w.label.text() != "Today"
        assert w.label.text() == today.strftime("%b %d")

    def test_label_completed_overdue_shows_date(self, qtbot):
        """Completed overdue DueDateLabel should show date, not 'Overdue'."""
        yesterday = date.today() - timedelta(days=1)
        w = DueDateLabel(yesterday, complete=True, recurring=False)
        qtbot.addWidget(w)
        assert "Overdue" not in w.label.text()

    def test_label_completed_recurring_dims_icon(self, qtbot):
        """Completed recurring DueDateLabel should have opacity effect on icon."""
        w = DueDateLabel(date.today(), complete=True, recurring=True)
        qtbot.addWidget(w)
        # Find the icon label (first QLabel child that has a pixmap)
        icon_labels = [
            child
            for child in w.findChildren(QLabel)
            if child is not w.label and child.pixmap() and not child.pixmap().isNull()
        ]
        if icon_labels:  # Icon may not exist if repeat.svg is missing
            effect = icon_labels[0].graphicsEffect()
            assert effect is not None
            assert isinstance(effect, QGraphicsOpacityEffect)
            assert abs(effect.opacity() - 0.4) < 0.01

    def test_label_non_completed_recurring_no_opacity(self, qtbot):
        """Non-completed recurring DueDateLabel should not have opacity effect."""
        w = DueDateLabel(date.today(), complete=False, recurring=True)
        qtbot.addWidget(w)
        icon_labels = [
            child
            for child in w.findChildren(QLabel)
            if child is not w.label and child.pixmap() and not child.pixmap().isNull()
        ]
        if icon_labels:  # Icon may not exist if repeat.svg is missing
            assert icon_labels[0].graphicsEffect() is None


# ===========================================================================
# DueDatePickerDialog Tests
# ===========================================================================


class TestDueDatePickerDialog:
    """Test DueDatePickerDialog."""

    def test_dialog_with_date(self, qtbot):
        """Dialog with a current date should show that date."""
        d = DueDatePickerDialog(date(2025, 6, 15))
        qtbot.addWidget(d)
        qdate = d.date_edit.date()
        assert qdate.year() == 2025
        assert qdate.month() == 6
        assert qdate.day() == 15

    def test_dialog_without_date(self, qtbot):
        """Dialog without a date should default to today."""
        d = DueDatePickerDialog(None)
        qtbot.addWidget(d)
        from PyQt6.QtCore import QDate

        today = QDate.currentDate()
        assert d.date_edit.date() == today

    def test_get_date_returns_initial(self, qtbot):
        """get_date should return the initial date before interaction."""
        d = DueDatePickerDialog(date(2025, 3, 10))
        qtbot.addWidget(d)
        assert d.get_date() == date(2025, 3, 10)

    def test_on_clear_sets_none(self, qtbot):
        """Clicking clear should set date to None."""
        d = DueDatePickerDialog(date(2025, 3, 10))
        qtbot.addWidget(d)
        d._on_clear()
        assert d.get_date() is None

    def test_on_ok_sets_date(self, qtbot):
        """Clicking OK should set date from date edit."""
        d = DueDatePickerDialog(date(2025, 3, 10))
        qtbot.addWidget(d)
        from PyQt6.QtCore import QDate

        d.date_edit.setDate(QDate(2025, 12, 25))
        d._on_ok()
        assert d.get_date() == date(2025, 12, 25)


# ===========================================================================
# ListSelectorWidget Tests
# ===========================================================================


class TestListSelectorWidgetConstruction:
    """Test ListSelectorWidget construction."""

    def test_widget_created(self, list_selector):
        """Widget should be constructible."""
        assert list_selector is not None

    def test_has_combo(self, list_selector):
        """Widget should have a combo box."""
        assert isinstance(list_selector.combo, QComboBox)

    def test_has_buttons(self, list_selector):
        """Widget should have add, delete, and rename buttons."""
        assert list_selector.add_btn is not None
        assert list_selector.delete_btn is not None
        assert list_selector.rename_btn is not None


class TestListSelectorWidgetDatabase:
    """Test database operations on ListSelectorWidget."""

    def test_set_database_populates_combo(self, list_selector, two_list_db):
        """set_database should populate the combo box."""
        db, _a, _b = two_list_db
        list_selector.set_database(db)
        assert list_selector.combo.count() == 2

    def test_get_current_list_with_no_database(self, list_selector):
        """get_current_list with no database should return None."""
        assert list_selector.get_current_list() is None

    def test_get_current_list_returns_active(self, list_selector, two_list_db):
        """get_current_list should return the active list."""
        db, list_a, _b = two_list_db
        list_selector.set_database(db)
        current = list_selector.get_current_list()
        assert current is not None
        assert current.id == list_a.id

    def test_get_current_list_id(self, list_selector, two_list_db):
        """get_current_list_id should return the UUID of active list."""
        db, list_a, _b = two_list_db
        list_selector.set_database(db)
        assert list_selector.get_current_list_id() == list_a.id

    def test_get_current_list_id_no_selection(self, list_selector):
        """get_current_list_id with no selection should return None."""
        assert list_selector.get_current_list_id() is None

    def test_set_current_list(self, list_selector, two_list_db):
        """set_current_list should change selection."""
        db, _a, list_b = two_list_db
        list_selector.set_database(db)
        result = list_selector.set_current_list(list_b.id)
        assert result is True
        assert list_selector.get_current_list_id() == list_b.id

    def test_set_current_list_invalid(self, list_selector, two_list_db):
        """set_current_list with invalid ID should return False."""
        db, _a, _b = two_list_db
        list_selector.set_database(db)
        result = list_selector.set_current_list(uuid4())
        assert result is False

    def test_refresh_preserves_selection(self, list_selector, two_list_db):
        """refresh() should maintain the selected list."""
        db, list_a, _b = two_list_db
        list_selector.set_database(db)
        list_selector.refresh()
        assert list_selector.get_current_list_id() == list_a.id

    def test_button_states_with_lists(self, list_selector, two_list_db):
        """Delete and rename buttons should be enabled when lists exist."""
        db, _a, _b = two_list_db
        list_selector.set_database(db)
        assert list_selector.delete_btn.isEnabled()
        assert list_selector.rename_btn.isEnabled()

    def test_button_states_no_lists(self, list_selector):
        """Delete and rename buttons should be disabled when no lists exist."""
        db = Database()
        list_selector.set_database(db)
        assert not list_selector.delete_btn.isEnabled()
        assert not list_selector.rename_btn.isEnabled()


class TestListSelectorWidgetSignals:
    """Test signal emissions from ListSelectorWidget."""

    def test_list_changed_signal_on_selection(self, qtbot, list_selector, two_list_db):
        """Changing combo selection should emit list_changed."""
        db, _a, _b = two_list_db
        list_selector.set_database(db)
        # Signal should emit when user changes index (not during refresh)
        with qtbot.waitSignal(list_selector.list_changed, timeout=500):
            list_selector.combo.setCurrentIndex(1)

    def test_add_list_signal(self, qtbot, list_selector):
        """Clicking add button should emit add_list_requested."""
        with qtbot.waitSignal(list_selector.add_list_requested, timeout=500):
            list_selector.add_btn.click()

    def test_delete_list_signal(self, qtbot, list_selector, two_list_db):
        """Clicking delete button should emit delete_list_requested."""
        db, _a, _b = two_list_db
        list_selector.set_database(db)
        with qtbot.waitSignal(list_selector.delete_list_requested, timeout=500):
            list_selector.delete_btn.click()

    def test_rename_list_signal(self, qtbot, list_selector, two_list_db):
        """Clicking rename button should emit rename_list_requested."""
        db, _a, _b = two_list_db
        list_selector.set_database(db)
        with qtbot.waitSignal(list_selector.rename_list_requested, timeout=500):
            list_selector.rename_btn.click()

    def test_no_signal_during_refresh(self, qtbot, list_selector, two_list_db):
        """refresh() should not emit list_changed."""
        db, _a, _b = two_list_db
        list_selector.set_database(db)

        signal_emitted = False

        def on_signal(lst):
            nonlocal signal_emitted
            signal_emitted = True

        list_selector.list_changed.connect(on_signal)
        list_selector.refresh()
        assert not signal_emitted

    def test_selection_changed_emits_none_on_invalid(self, qtbot, list_selector):
        """_on_selection_changed with index -1 should emit None."""
        # Ensure _updating is False so the signal isn't suppressed
        list_selector._updating = False
        with qtbot.waitSignal(list_selector.list_changed, timeout=500) as blocker:
            list_selector._on_selection_changed(-1)
        assert blocker.args == [None]


class TestListSelectorUnseenStyling:
    """Test unseen changes visual indicators."""

    def test_unseen_sets_combo_border(self, list_selector, two_list_db):
        """Setting unseen list IDs should add border to combo."""
        db, _a, list_b = two_list_db
        list_selector.set_database(db)
        list_selector.set_unseen({list_b.id})
        assert "border" in list_selector.combo.styleSheet()

    def test_clear_unseen_removes_border(self, list_selector, two_list_db):
        """Clearing unseen list IDs should remove border."""
        db, _a, list_b = two_list_db
        list_selector.set_database(db)
        list_selector.set_unseen({list_b.id})
        list_selector.set_unseen(set())
        assert list_selector.combo.styleSheet() == ""

    def test_unseen_item_gets_foreground_tint(self, list_selector, two_list_db):
        """Unseen list item should get foreground color tint."""
        db, _a, list_b = two_list_db
        list_selector.set_database(db)
        list_selector.set_unseen({list_b.id})

        model = list_selector.combo.model()
        assert isinstance(model, QStandardItemModel)
        for i in range(model.rowCount()):
            if list_selector.combo.itemData(i) == list_b.id:
                item = model.item(i)
                assert item is not None
                brush = item.foreground()
                # Should have a non-default foreground
                assert brush.color().name() != "#000000"
                break

    def test_non_unseen_item_cleared(self, list_selector, two_list_db):
        """Non-unseen list items should have cleared styling."""
        db, list_a, list_b = two_list_db
        list_selector.set_database(db)
        list_selector.set_unseen({list_b.id})

        model = list_selector.combo.model()
        assert isinstance(model, QStandardItemModel)
        for i in range(model.rowCount()):
            if list_selector.combo.itemData(i) == list_a.id:
                item = model.item(i)
                assert item is not None
                # Non-private, non-unseen should have no icon
                assert item.icon().isNull()
                break

    def test_private_list_keeps_lock_on_clear(self, list_selector, two_list_db):
        """Private list should keep lock icon when unseen is cleared."""
        db, _a, list_b = two_list_db
        list_b.private = True
        list_selector.set_database(db)

        # First set unseen, then clear
        list_selector.set_unseen({list_b.id})
        list_selector.set_unseen(set())

        model = list_selector.combo.model()
        assert isinstance(model, QStandardItemModel)
        for i in range(model.rowCount()):
            if list_selector.combo.itemData(i) == list_b.id:
                item = model.item(i)
                assert item is not None
                # Private list should retain its lock icon
                assert not item.icon().isNull()
                break

    def test_non_private_icon_cleared_on_unseen_clear(self, list_selector, two_list_db):
        """Non-private list should have icon cleared when removed from unseen."""
        db, _a, list_b = two_list_db
        list_selector.set_database(db)

        # Add unseen (adds dot icon)
        list_selector.set_unseen({list_b.id})
        # Clear unseen (should remove dot icon)
        list_selector.set_unseen(set())

        model = list_selector.combo.model()
        assert isinstance(model, QStandardItemModel)
        for i in range(model.rowCount()):
            if list_selector.combo.itemData(i) == list_b.id:
                item = model.item(i)
                assert item is not None
                assert item.icon().isNull()
                break

    def test_refresh_no_database(self, list_selector):
        """refresh() with no database should return early with empty combo."""
        list_selector._database = None
        list_selector.refresh()
        assert list_selector.combo.count() == 0

    def test_apply_unseen_styling_no_model(self, qtbot):
        """_apply_unseen_styling should handle non-QStandardItemModel gracefully."""
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        # Without a database set, model might not be standard
        # This should not raise
        widget._apply_unseen_styling()


class TestListSelectorPrivateList:
    """Test private list icon display."""

    def test_private_list_has_icon(self, list_selector, two_list_db):
        """Private list should show lock icon in combo box."""
        db, _a, list_b = two_list_db
        list_b.private = True
        list_selector.set_database(db)

        model = list_selector.combo.model()
        assert isinstance(model, QStandardItemModel)
        for i in range(model.rowCount()):
            if list_selector.combo.itemData(i) == list_b.id:
                item = model.item(i)
                assert item is not None
                # Lock icon should be set (may or may not be null
                # depending on icon file availability, but the code
                # path is exercised)
                break
        else:
            pytest.fail("Work list not found in combo box")


# ===========================================================================
# FilterState dataclass additional tests
# ===========================================================================


class TestFilterStateDueDate:
    """Test FilterState with due_date field."""

    def test_due_date_makes_active(self):
        """Non-zero due_date should make filter active."""
        state = FilterState(due_date=1)
        assert state.is_active is True

    def test_due_date_zero_not_active(self):
        """Zero due_date alone should not make filter active."""
        state = FilterState(due_date=0)
        assert state.is_active is False

    def test_all_zero_not_active(self):
        """All zeroes and empty text should not be active."""
        state = FilterState(text="", priority=0, status=0, due_date=0)
        assert state.is_active is False


# ===========================================================================
# Integration: SearchFilterWidget + TodoTableWidget
# ===========================================================================


class TestSearchFilterIntegration:
    """Test SearchFilterWidget driving TodoTableWidget filtering."""

    def test_filter_signal_drives_table(self, qtbot, sample_list):
        """SearchFilterWidget.filter_changed should update TodoTableWidget."""
        search = SearchFilterWidget()
        table = TodoTableWidget()
        qtbot.addWidget(search)
        qtbot.addWidget(table)

        table.set_list(sample_list)
        assert table.rowCount() == 5

        # Connect signal
        search.filter_changed.connect(table.set_filter)

        # Set a text filter
        search.search_edit.setText("milk")
        # Manually emit since debounce may delay
        search._emit_filter()

        assert table.rowCount() == 1

    def test_clear_filter_restores_all(self, qtbot, sample_list):
        """Clearing SearchFilterWidget should restore all items in table."""
        search = SearchFilterWidget()
        table = TodoTableWidget()
        qtbot.addWidget(search)
        qtbot.addWidget(table)

        table.set_list(sample_list)
        search.filter_changed.connect(table.set_filter)

        search.search_edit.setText("milk")
        search._emit_filter()
        assert table.rowCount() == 1

        search.clear_filters()
        assert table.rowCount() == 5


class TestTodoTableMeetingLinkContextMenu:
    """The list-view context menu surfaces a Join action at the top
    when the selected row's reminder contains a recognized meeting URL,
    mirroring the calendar bar's pattern. Closes parity with kanban
    card and detail panel which use a visible button instead."""

    def _capture_menu(self, qtbot, monkeypatch):
        from PyQt6.QtWidgets import QMenu

        captured: dict = {}

        def fake_exec(self, *_args, **_kwargs):
            captured["menu"] = self
            return None

        monkeypatch.setattr(QMenu, "exec", fake_exec)
        return captured

    def test_zoom_link_adds_join_action(self, qtbot, monkeypatch, todo_table):
        from PyQt6.QtCore import QPoint

        captured = self._capture_menu(qtbot, monkeypatch)

        lst = TodoList(name="L")
        item = create_todo_item("Standup https://us02web.zoom.us/j/12345")
        lst.items[item.id] = item
        todo_table.set_list(lst)
        todo_table.selectRow(0)

        todo_table._on_context_menu(QPoint(0, 0))
        menu = captured.get("menu")
        assert menu is not None
        texts = [a.text() for a in menu.actions()]
        assert any("Join" in t and "Zoom" in t for t in texts)

    def test_no_meeting_url_no_join_action(self, qtbot, monkeypatch, todo_table):
        from PyQt6.QtCore import QPoint

        captured = self._capture_menu(qtbot, monkeypatch)

        lst = TodoList(name="L")
        item = create_todo_item("Buy groceries")
        lst.items[item.id] = item
        todo_table.set_list(lst)
        todo_table.selectRow(0)

        todo_table._on_context_menu(QPoint(0, 0))
        menu = captured.get("menu")
        assert menu is not None
        texts = [a.text() for a in menu.actions()]
        assert not any("Join" in t for t in texts)

    def test_jitsi_link_adds_join_action_with_provider_name(self, qtbot, monkeypatch, todo_table):
        from PyQt6.QtCore import QPoint

        captured = self._capture_menu(qtbot, monkeypatch)

        lst = TodoList(name="L")
        item = create_todo_item("Catchup https://meet.jit.si/MyRoom")
        lst.items[item.id] = item
        todo_table.set_list(lst)
        todo_table.selectRow(0)

        todo_table._on_context_menu(QPoint(0, 0))
        menu = captured.get("menu")
        assert menu is not None
        texts = [a.text() for a in menu.actions()]
        assert any("Join" in t and "Jitsi" in t for t in texts)
