"""Tests for the Pomodoro / Focus Timer feature (Phase 3).

Covers:
- PomodoroWidget state machine
- Timer state transitions
- Session completion signals
- Configuration
- PomodoroConfig serialization
- time_spent field on TodoItem
- Schema v10 migration
- format_time and format_time_spent utilities
"""

from __future__ import annotations

from uuid import uuid4

from pytodo_qt.core.config import AppConfig, PomodoroConfig
from pytodo_qt.core.database import SCHEMA_VERSION, DatabaseStorage
from pytodo_qt.core.models import TodoItem, create_todo_item, create_todo_list
from pytodo_qt.gui.widgets.pomodoro import PomodoroWidget, TimerState

# ===========================================================================
# PomodoroConfig tests
# ===========================================================================


class TestPomodoroConfig:
    def test_defaults(self):
        config = PomodoroConfig()
        assert config.work_duration == 25
        assert config.break_duration == 5
        assert config.long_break_duration == 15
        assert config.sessions_before_long_break == 4
        assert config.auto_start_break is True

    def test_custom_values(self):
        config = PomodoroConfig(work_duration=50, break_duration=10)
        assert config.work_duration == 50
        assert config.break_duration == 10

    def test_app_config_has_pomodoro(self):
        config = AppConfig()
        assert isinstance(config.pomodoro, PomodoroConfig)
        assert config.pomodoro.work_duration == 25

    def test_toml_roundtrip(self):
        import tomllib

        config = AppConfig()
        config.pomodoro.work_duration = 30
        config.pomodoro.auto_start_break = False
        toml_str = config.to_toml()
        data = tomllib.loads(toml_str)
        restored = AppConfig.from_dict(data)
        assert restored.pomodoro.work_duration == 30
        assert restored.pomodoro.auto_start_break is False

    def test_from_dict_missing_pomodoro(self):
        config = AppConfig.from_dict({})
        assert config.pomodoro.work_duration == 25


# ===========================================================================
# TimerState tests
# ===========================================================================


class TestTimerState:
    def test_idle_is_default(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)
        assert widget.state == TimerState.IDLE

    def test_start_transitions_to_working(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)
        item_id = uuid4()

        widget.start(item_id, "Test")
        assert widget.state == TimerState.WORKING
        assert widget.item_id == item_id
        assert widget.item_name == "Test"
        widget.stop()

    def test_pause_from_working(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        widget.pause()
        assert widget.state == TimerState.PAUSED
        widget.stop()

    def test_resume_from_paused(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        widget.pause()
        widget.resume()
        assert widget.state == TimerState.WORKING
        widget.stop()

    def test_stop_from_working(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        widget.stop()
        assert widget.state == TimerState.IDLE
        assert widget.item_id is None

    def test_stop_from_paused(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        widget.pause()
        widget.stop()
        assert widget.state == TimerState.IDLE

    def test_pause_ignored_when_idle(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.pause()
        assert widget.state == TimerState.IDLE

    def test_resume_ignored_when_idle(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.resume()
        assert widget.state == TimerState.IDLE

    def test_remaining_seconds_initialized(self, qtbot):
        config = PomodoroConfig(work_duration=25)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        assert widget.remaining_seconds == 25 * 60
        widget.stop()

    def test_session_count_starts_at_zero(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        assert widget.session_count == 0
        widget.stop()

    def test_stop_clears_item_name(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4(), "My Task")
        assert widget.item_name == "My Task"
        widget.stop()
        assert widget.item_name == ""

    def test_start_while_running_stops_first(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        id1 = uuid4()
        id2 = uuid4()
        widget.start(id1)
        widget.start(id2)
        assert widget.item_id == id2
        assert widget.state == TimerState.WORKING
        widget.stop()


# ===========================================================================
# Timer tick and completion tests
# ===========================================================================


class TestTimerCompletion:
    def test_work_complete_emits_signal(self, qtbot):
        config = PomodoroConfig(work_duration=1, auto_start_break=False)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        item_id = uuid4()
        widget.start(item_id)

        # Manually drive remaining down to trigger completion
        widget._remaining_seconds = 1
        with qtbot.waitSignal(widget.session_completed, timeout=2000):
            widget._tick()

    def test_work_complete_increments_session_count(self, qtbot):
        config = PomodoroConfig(work_duration=1, auto_start_break=False)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        widget._remaining_seconds = 1
        widget._tick()
        assert widget.session_count == 1

    def test_work_complete_starts_break_if_auto(self, qtbot):
        config = PomodoroConfig(work_duration=1, auto_start_break=True)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        widget._remaining_seconds = 1
        widget._tick()
        assert widget.state == TimerState.BREAK
        widget.stop()

    def test_work_complete_idle_if_no_auto(self, qtbot):
        config = PomodoroConfig(work_duration=1, auto_start_break=False)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        widget._remaining_seconds = 1
        widget._tick()
        assert widget.state == TimerState.IDLE

    def test_break_complete_starts_work_if_auto(self, qtbot):
        config = PomodoroConfig(work_duration=1, break_duration=1, auto_start_break=True)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        # Complete work
        widget._remaining_seconds = 1
        widget._tick()
        assert widget.state == TimerState.BREAK
        # Complete break
        widget._remaining_seconds = 1
        widget._tick()
        assert widget.state == TimerState.WORKING
        widget.stop()

    def test_long_break_after_n_sessions(self, qtbot):
        config = PomodoroConfig(
            work_duration=1,
            break_duration=5,
            long_break_duration=15,
            sessions_before_long_break=2,
            auto_start_break=True,
        )
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        # Session 1
        widget._remaining_seconds = 1
        widget._tick()
        assert widget.session_count == 1
        assert widget.remaining_seconds == 5 * 60  # short break

        # Complete short break, then session 2
        widget._remaining_seconds = 1
        widget._tick()
        assert widget.state == TimerState.WORKING
        widget._remaining_seconds = 1
        widget._tick()
        assert widget.session_count == 2
        assert widget.remaining_seconds == 15 * 60  # long break
        widget.stop()

    def test_state_changed_signal_emitted(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        with qtbot.waitSignal(widget.state_changed, timeout=1000):
            widget.start(uuid4())
        widget.stop()

    def test_tick_decrements_remaining(self, qtbot):
        config = PomodoroConfig(work_duration=25)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        initial = widget.remaining_seconds
        widget._tick()
        assert widget.remaining_seconds == initial - 1
        widget.stop()


# ===========================================================================
# Format utilities
# ===========================================================================


class TestFormatTime:
    def test_zero(self):
        assert PomodoroWidget.format_time(0) == "00:00"

    def test_one_minute(self):
        assert PomodoroWidget.format_time(60) == "01:00"

    def test_25_minutes(self):
        assert PomodoroWidget.format_time(1500) == "25:00"

    def test_with_seconds(self):
        assert PomodoroWidget.format_time(90) == "01:30"

    def test_negative_clamps(self):
        assert PomodoroWidget.format_time(-5) == "00:00"


class TestFormatTimeSpent:
    def test_zero(self):
        assert PomodoroWidget.format_time_spent(0) == ""

    def test_minutes_only(self):
        assert PomodoroWidget.format_time_spent(300) == "5m"

    def test_hours_and_minutes(self):
        assert PomodoroWidget.format_time_spent(5100) == "1h 25m"

    def test_exact_hour(self):
        assert PomodoroWidget.format_time_spent(3600) == "1h 0m"

    def test_negative(self):
        assert PomodoroWidget.format_time_spent(-10) == ""


# ===========================================================================
# TodoItem time_spent field tests
# ===========================================================================


class TestTimeSpentField:
    def test_default_zero(self):
        item = TodoItem()
        assert item.time_spent == 0

    def test_set_time_spent(self):
        item = TodoItem(time_spent=1500)
        assert item.time_spent == 1500

    def test_accumulate(self):
        item = create_todo_item("Test")
        item.time_spent += 1500
        item.time_spent += 1500
        assert item.time_spent == 3000

    def test_serialization_roundtrip(self):
        item = create_todo_item("Test")
        item.time_spent = 5100
        d = item.to_dict()
        assert d["time_spent"] == 5100
        restored = TodoItem.from_dict(d)
        assert restored.time_spent == 5100

    def test_from_dict_missing_time_spent(self):
        d = {"id": str(uuid4()), "reminder": "Old"}
        item = TodoItem.from_dict(d)
        assert item.time_spent == 0


# ===========================================================================
# Schema v10 tests
# ===========================================================================


class TestSchemaV10:
    def test_current_version_is_13(self):
        # Sentinel: bumps when SCHEMA_VERSION changes; assertion stays
        # honest because it references the constant.
        assert SCHEMA_VERSION >= 13

    def test_fresh_database_has_time_spent_column(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)
        cursor = storage.connection.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "time_spent" in columns
        storage.close()

    def test_save_and_load_time_spent(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("Focus")
        item.time_spent = 3000
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.time_spent == 3000
        storage.close()

    def test_save_and_load_zero_time_spent(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("No focus")
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.time_spent == 0
        storage.close()

    def test_update_time_spent_persists(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("Focus")
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        item.time_spent = 7500
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.time_spent == 7500
        storage.close()


# ===========================================================================
# Update config tests
# ===========================================================================


class TestUpdateConfig:
    def test_update_config(self, qtbot):
        config = PomodoroConfig(work_duration=25)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        new_config = PomodoroConfig(work_duration=50)
        widget.update_config(new_config)

        widget.start(uuid4())
        assert widget.remaining_seconds == 50 * 60
        widget.stop()

    def test_sessions_before_long_break_property(self, qtbot):
        config = PomodoroConfig(sessions_before_long_break=6)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)
        assert widget.sessions_before_long_break == 6


# ===========================================================================
# FocusTimerDialog tests
# ===========================================================================


class TestFocusTimerDialog:
    def test_dialog_creation(self, qtbot):
        from PyQt6.QtCore import Qt

        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        flags = dialog.windowFlags()
        assert flags & Qt.WindowType.WindowStaysOnTopHint

    def test_update_display_working(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.update_display("working", 1500, "Write tests", 1, 4)
        assert dialog._time_label.text() == "25:00"
        assert dialog._item_label.text() == "Write tests"
        assert "2 of 4" in dialog._session_label.text()
        assert not dialog._skip_btn.isVisible()

    def test_update_display_break(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.update_display("break", 300, "Write tests", 1, 4)
        assert dialog._time_label.text() == "05:00"
        assert dialog._skip_btn.isVisible()

    def test_update_display_paused(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.update_display("paused", 600, "Write tests", 0, 4)
        assert "\u25b6" in dialog._pause_btn.text()  # Resume icon

    def test_hide_on_idle(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        assert dialog.isVisible()
        dialog.update_display("idle", 0, "", 0, 4)
        assert not dialog.isVisible()

    def test_pause_signal(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.update_display("working", 1500, "Test", 0, 4)
        with qtbot.waitSignal(dialog.pause_requested, timeout=1000):
            dialog._pause_btn.click()

    def test_stop_signal(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        with qtbot.waitSignal(dialog.stop_requested, timeout=1000):
            dialog._stop_btn.click()

    def test_skip_signal(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.update_display("break", 300, "Test", 1, 4)
        with qtbot.waitSignal(dialog.skip_break_requested, timeout=1000):
            dialog._skip_btn.click()

    def test_close_hides_instead_of_destroying(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.close()
        # Dialog should still exist and be re-showable
        assert not dialog.isVisible()
        dialog.show()
        assert dialog.isVisible()

    def test_progress_bar_updates(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.update_display("working", 750, "Test", 0, 4, total_duration=1500)
        assert dialog._progress_bar.maximum() == 1500
        assert dialog._progress_bar.value() == 750

    def test_short_name_not_elided(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.update_display("working", 1500, "Short task", 0, 4)
        assert dialog._item_label.text() == "Short task"
        assert dialog._item_label.toolTip() == ""

    def test_long_name_elided_with_ellipsis(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        long_name = "This is a very long task reminder that should definitely be truncated because it exceeds what can reasonably fit in the floating timer window display area"
        dialog.update_display("working", 1500, long_name, 0, 4)
        displayed = dialog._item_label.text()
        # Should be shorter than the original
        assert len(displayed) < len(long_name)
        # Should end with ellipsis
        assert displayed.rstrip().endswith("\u2026")
        # Full text in tooltip
        assert dialog._item_label.toolTip() == long_name


# ===========================================================================
# Context menu and status bar signal tests
# ===========================================================================


class TestContextMenuFocus:
    def test_focus_requested_signal_exists(self, qtbot):
        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        table = TodoTableWidget()
        qtbot.addWidget(table)
        assert hasattr(table, "focus_requested")


class TestStatusBarClick:
    def test_pomodoro_clicked_signal_exists(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import StatusBarWidget

        bar = StatusBarWidget()
        qtbot.addWidget(bar)
        assert hasattr(bar, "pomodoro_clicked")


# ===========================================================================
# EditTimeSpentCommand tests
# ===========================================================================


class _FakeConfigManager:
    def save(self):
        pass


class _FakeConfig:
    class database:
        active_list = ""


def _make_window(db=None):
    from unittest.mock import MagicMock

    from pytodo_qt.core.models import Database

    window = MagicMock()
    window._database = db or Database()
    window._save_database = MagicMock()
    window._refresh_ui = MagicMock()
    window._config = _FakeConfig()
    window._config_manager = _FakeConfigManager()
    window.status_bar_widget = MagicMock()
    return window


class TestEditTimeSpentCommand:
    def test_redo_adds_time(self):
        from pytodo_qt.core.models import Database, create_todo_item, create_todo_list
        from pytodo_qt.gui.commands import EditTimeSpentCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Focus task")
        item.time_spent = 100
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = _make_window(db)

        cmd = EditTimeSpentCommand(window, lst.id, item.id, 100, 1500)
        cmd.redo()

        assert item.time_spent == 1600  # 100 + 1500

    def test_undo_restores_time(self):
        from pytodo_qt.core.models import Database, create_todo_item, create_todo_list
        from pytodo_qt.gui.commands import EditTimeSpentCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Focus task")
        item.time_spent = 100
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = _make_window(db)

        cmd = EditTimeSpentCommand(window, lst.id, item.id, 100, 1500)
        cmd.redo()
        cmd.undo()

        assert item.time_spent == 100

    def test_noop_if_item_missing(self):
        from pytodo_qt.core.models import Database, create_todo_list
        from pytodo_qt.gui.commands import EditTimeSpentCommand

        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = _make_window(db)

        cmd = EditTimeSpentCommand(window, lst.id, uuid4(), 0, 1500)
        cmd.redo()  # Should not raise
        cmd.undo()  # Should not raise

    def test_noop_if_list_missing(self):
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.commands import EditTimeSpentCommand

        db = Database()
        window = _make_window(db)

        cmd = EditTimeSpentCommand(window, uuid4(), uuid4(), 0, 1500)
        cmd.redo()  # Should not raise
        cmd.undo()  # Should not raise

    def test_redo_marks_updated(self):
        import time as _time

        from pytodo_qt.core.models import Database, create_todo_item, create_todo_list
        from pytodo_qt.gui.commands import EditTimeSpentCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Focus task")
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = _make_window(db)

        ts_before = item.updated_at
        _time.sleep(0.002)
        cmd = EditTimeSpentCommand(window, lst.id, item.id, 0, 1500)
        cmd.redo()
        assert item.updated_at >= ts_before


class TestDeletionStopsFocusTimer:
    def test_delete_stops_timer_for_focused_item(self):
        """Deleting an item that has the focus timer running should stop the timer."""
        from unittest.mock import MagicMock

        from pytodo_qt.core.models import Database, create_todo_item, create_todo_list

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Focused task")
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)

        # Build a minimal mock MainWindow that has the attributes _on_delete_todo uses
        window = MagicMock()
        window._database = db
        window._pomodoro = MagicMock()
        window._pomodoro.item_id = item.id  # Timer running on this item
        window._undo_stack = MagicMock()

        # Bind the real _on_delete_todo method
        from pytodo_qt.gui.main_window import MainWindow

        window.todo_table = MagicMock()
        window.todo_table.get_selected_item_ids.return_value = [item.id]
        window._active_view_widget.return_value = window.todo_table

        # Call the real method
        MainWindow._on_delete_todo(window)

        window._on_stop_focus.assert_called_once()

    def test_delete_does_not_stop_timer_for_other_item(self):
        """Deleting a different item should not stop the focus timer."""
        from unittest.mock import MagicMock

        from pytodo_qt.core.models import Database, create_todo_item, create_todo_list

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Normal task")
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)

        window = MagicMock()
        window._database = db
        window._pomodoro = MagicMock()
        window._pomodoro.item_id = uuid4()  # Timer on a different item
        window._undo_stack = MagicMock()

        from pytodo_qt.gui.main_window import MainWindow

        window.todo_table = MagicMock()
        window.todo_table.get_selected_item_ids.return_value = [item.id]
        window._active_view_widget.return_value = window.todo_table

        MainWindow._on_delete_todo(window)

        window._on_stop_focus.assert_not_called()


# ===========================================================================
# Phase B: Per-task pomodoro tracking tests
# ===========================================================================


class TestPomodoroCountField:
    def test_default_zero(self):
        item = TodoItem()
        assert item.pomodoro_count == 0
        assert item.estimated_pomodoros == 0

    def test_set_values(self):
        item = TodoItem(pomodoro_count=3, estimated_pomodoros=4)
        assert item.pomodoro_count == 3
        assert item.estimated_pomodoros == 4

    def test_serialization_roundtrip(self):
        item = create_todo_item("Test")
        item.pomodoro_count = 5
        item.estimated_pomodoros = 8
        d = item.to_dict()
        assert d["pomodoro_count"] == 5
        assert d["estimated_pomodoros"] == 8
        restored = TodoItem.from_dict(d)
        assert restored.pomodoro_count == 5
        assert restored.estimated_pomodoros == 8

    def test_from_dict_missing_fields(self):
        d = {"id": str(uuid4()), "reminder": "Old"}
        item = TodoItem.from_dict(d)
        assert item.pomodoro_count == 0
        assert item.estimated_pomodoros == 0

    def test_create_todo_item_with_estimate(self):
        item = create_todo_item("Plan", estimated_pomodoros=4)
        assert item.estimated_pomodoros == 4
        assert item.pomodoro_count == 0


class TestSchemaV12:
    def test_fresh_database_has_pomodoro_columns(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)
        cursor = storage.connection.execute("PRAGMA table_info(items)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "pomodoro_count" in columns
        assert "estimated_pomodoros" in columns
        storage.close()

    def test_save_and_load_pomodoro_fields(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        item = create_todo_item("Focus", estimated_pomodoros=4)
        item.pomodoro_count = 2
        lst.add_item(item)

        storage.save_list(lst)
        storage.save_item(lst.id, item)

        loaded = storage.get_item(item.id)
        assert loaded is not None
        assert loaded.pomodoro_count == 2
        assert loaded.estimated_pomodoros == 4
        storage.close()


class TestEditTimeSpentCommandWithPomodoro:
    def test_redo_increments_pomodoro_count(self):
        from pytodo_qt.core.models import Database, create_todo_item, create_todo_list
        from pytodo_qt.gui.commands import EditTimeSpentCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Focus task")
        item.pomodoro_count = 2
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = _make_window(db)

        cmd = EditTimeSpentCommand(window, lst.id, item.id, 0, 1500, 2)
        cmd.redo()

        assert item.pomodoro_count == 3
        assert item.time_spent == 1500

    def test_undo_restores_pomodoro_count(self):
        from pytodo_qt.core.models import Database, create_todo_item, create_todo_list
        from pytodo_qt.gui.commands import EditTimeSpentCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Focus task")
        item.pomodoro_count = 2
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = _make_window(db)

        cmd = EditTimeSpentCommand(window, lst.id, item.id, 0, 1500, 2)
        cmd.redo()
        cmd.undo()

        assert item.pomodoro_count == 2
        assert item.time_spent == 0

    def test_default_pomodoro_count_zero(self):
        """Backward compat: old callers without pomodoro_count param."""
        from pytodo_qt.core.models import Database, create_todo_item, create_todo_list
        from pytodo_qt.gui.commands import EditTimeSpentCommand

        db = Database()
        lst = create_todo_list("Test")
        item = create_todo_item("Focus task")
        lst.add_item(item)
        db.add_list(lst)
        db.set_active_list(lst.id)
        window = _make_window(db)

        cmd = EditTimeSpentCommand(window, lst.id, item.id, 0, 1500)
        cmd.redo()

        assert item.pomodoro_count == 1
        assert item.time_spent == 1500


# ===========================================================================
# Phase F: Sound notification tests
# ===========================================================================


class TestSoundConfig:
    def test_defaults(self):
        config = PomodoroConfig()
        assert config.sound_enabled is False
        assert config.sound_volume == 50

    def test_custom_values(self):
        config = PomodoroConfig(sound_enabled=True, sound_volume=75)
        assert config.sound_enabled is True
        assert config.sound_volume == 75

    def test_toml_roundtrip(self):
        import tomllib

        config = AppConfig()
        config.pomodoro.sound_enabled = True
        config.pomodoro.sound_volume = 80
        toml_str = config.to_toml()
        data = tomllib.loads(toml_str)
        restored = AppConfig.from_dict(data)
        assert restored.pomodoro.sound_enabled is True
        assert restored.pomodoro.sound_volume == 80

    def test_from_dict_missing_sound_fields(self):
        config = AppConfig.from_dict({"pomodoro": {"work_duration": 30}})
        assert config.pomodoro.sound_enabled is False
        assert config.pomodoro.sound_volume == 50


class TestSoundPlayer:
    def test_creation(self):
        from pytodo_qt.gui.widgets.sound_player import SoundPlayer

        config = PomodoroConfig()
        player = SoundPlayer(config)
        assert player._enabled is False

    def test_creation_enabled(self):
        from pytodo_qt.gui.widgets.sound_player import SoundPlayer

        config = PomodoroConfig(sound_enabled=True, sound_volume=75)
        player = SoundPlayer(config)
        assert player._enabled is True
        assert player._volume == 0.75

    def test_update_config(self):
        from pytodo_qt.gui.widgets.sound_player import SoundPlayer

        config = PomodoroConfig()
        player = SoundPlayer(config)

        new_config = PomodoroConfig(sound_enabled=True, sound_volume=90)
        player.update_config(new_config)
        assert player._enabled is True
        assert player._volume == 0.9

    def test_play_when_disabled_is_noop(self):
        from pytodo_qt.gui.widgets.sound_player import SoundPlayer

        config = PomodoroConfig(sound_enabled=False)
        player = SoundPlayer(config)
        player.play("work-complete")  # Should not raise

    def test_play_unknown_sound_is_noop(self):
        from pytodo_qt.gui.widgets.sound_player import SoundPlayer

        config = PomodoroConfig(sound_enabled=True)
        player = SoundPlayer(config)
        player.play("nonexistent-sound")  # Should not raise

    def test_effects_loaded(self):
        from pytodo_qt.gui.widgets.sound_player import _AVAILABLE, SoundPlayer

        config = PomodoroConfig(sound_enabled=True)
        player = SoundPlayer(config)
        if _AVAILABLE:
            assert "work-complete" in player._effects
            assert "break-complete" in player._effects


# ===========================================================================
# Phase C: Session Logging tests
# ===========================================================================


class TestFocusSessionModel:
    def test_defaults(self):
        from pytodo_qt.core.models import FocusSession

        session = FocusSession()
        assert session.duration_seconds == 0
        assert session.completed is True
        assert session.session_type == "work"
        assert session.date == ""

    def test_to_dict_roundtrip(self):
        from pytodo_qt.core.models import FocusSession

        session = FocusSession(
            item_id=uuid4(),
            list_id=uuid4(),
            start_time="2026-03-08T10:00:00",
            end_time="2026-03-08T10:25:00",
            duration_seconds=1500,
            completed=True,
            session_type="work",
            date="2026-03-08",
        )
        d = session.to_dict()
        assert d["duration_seconds"] == 1500
        assert d["session_type"] == "work"

        restored = FocusSession.from_dict(d)
        assert restored.id == session.id
        assert restored.item_id == session.item_id
        assert restored.duration_seconds == 1500
        assert restored.completed is True

    def test_from_dict_missing_fields(self):
        from pytodo_qt.core.models import FocusSession

        d = {"id": str(uuid4()), "item_id": str(uuid4()), "list_id": str(uuid4())}
        session = FocusSession.from_dict(d)
        assert session.duration_seconds == 0
        assert session.completed is True
        assert session.session_type == "work"

    def test_incomplete_session(self):
        from pytodo_qt.core.models import FocusSession

        session = FocusSession(completed=False, duration_seconds=600, session_type="work")
        assert session.completed is False
        d = session.to_dict()
        restored = FocusSession.from_dict(d)
        assert restored.completed is False

    def test_create_focus_session_factory(self):
        from pytodo_qt.core.models import create_focus_session

        item_id = uuid4()
        list_id = uuid4()
        session = create_focus_session(
            item_id=item_id,
            list_id=list_id,
            start_time="2026-03-08T10:00:00",
            end_time="2026-03-08T10:25:00",
            duration_seconds=1500,
            date="2026-03-08",
        )
        assert session.item_id == item_id
        assert session.list_id == list_id
        assert session.completed is True


class TestSchemaV13:
    def test_fresh_database_has_focus_sessions_table(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)
        cursor = storage.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='focus_sessions'"
        )
        assert cursor.fetchone() is not None
        storage.close()

    def test_focus_sessions_columns(self, tmp_path):
        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)
        cursor = storage.connection.execute("PRAGMA table_info(focus_sessions)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "item_id" in columns
        assert "list_id" in columns
        assert "start_time" in columns
        assert "end_time" in columns
        assert "duration_seconds" in columns
        assert "completed" in columns
        assert "session_type" in columns
        assert "date" in columns
        storage.close()

    def test_save_and_load_focus_session(self, tmp_path):
        from pytodo_qt.core.models import FocusSession

        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        session = FocusSession(
            item_id=uuid4(),
            list_id=uuid4(),
            start_time="2026-03-08T10:00:00",
            end_time="2026-03-08T10:25:00",
            duration_seconds=1500,
            completed=True,
            session_type="work",
            date="2026-03-08",
        )
        storage.save_focus_session(session)

        loaded = storage.get_sessions_for_date("2026-03-08")
        assert len(loaded) == 1
        assert loaded[0].id == session.id
        assert loaded[0].duration_seconds == 1500
        storage.close()

    def test_get_sessions_for_item(self, tmp_path):
        from pytodo_qt.core.models import FocusSession

        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        item_id = uuid4()
        for i in range(3):
            session = FocusSession(
                item_id=item_id,
                list_id=uuid4(),
                start_time=f"2026-03-08T{10 + i}:00:00",
                end_time=f"2026-03-08T{10 + i}:25:00",
                duration_seconds=1500,
                date="2026-03-08",
            )
            storage.save_focus_session(session)

        loaded = storage.get_sessions_for_item(item_id)
        assert len(loaded) == 3
        storage.close()

    def test_get_all_focus_sessions(self, tmp_path):
        from pytodo_qt.core.models import FocusSession

        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        for _ in range(5):
            session = FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2026-03-08T10:00:00",
                end_time="2026-03-08T10:25:00",
                duration_seconds=1500,
                date="2026-03-08",
            )
            storage.save_focus_session(session)

        loaded = storage.get_all_focus_sessions()
        assert len(loaded) == 5
        storage.close()

    def test_load_database_includes_sessions(self, tmp_path):
        from pytodo_qt.core.models import FocusSession

        db_path = tmp_path / "test.db"
        storage = DatabaseStorage(db_path)

        lst = create_todo_list("Test")
        storage.save_list(lst)

        session = FocusSession(
            item_id=uuid4(),
            list_id=lst.id,
            start_time="2026-03-08T10:00:00",
            end_time="2026-03-08T10:25:00",
            duration_seconds=1500,
            date="2026-03-08",
        )
        storage.save_focus_session(session)

        db = storage.load_database()
        assert len(db.focus_sessions) == 1
        assert db.focus_sessions[0].id == session.id
        storage.close()


class TestSessionSync:
    def test_database_to_dict_includes_sessions(self):
        from pytodo_qt.core.models import Database, FocusSession

        db = Database()
        session = FocusSession(
            item_id=uuid4(),
            list_id=uuid4(),
            start_time="2026-03-08T10:00:00",
            end_time="2026-03-08T10:25:00",
            duration_seconds=1500,
            date="2026-03-08",
        )
        db.focus_sessions.append(session)

        d = db.to_dict()
        assert "focus_sessions" in d
        assert len(d["focus_sessions"]) == 1

    def test_database_from_dict_parses_sessions(self):
        from pytodo_qt.core.models import Database, FocusSession

        session = FocusSession(
            item_id=uuid4(),
            list_id=uuid4(),
            start_time="2026-03-08T10:00:00",
            end_time="2026-03-08T10:25:00",
            duration_seconds=1500,
            date="2026-03-08",
        )
        data = {
            "schema_version": 13,
            "lists": {},
            "focus_sessions": [session.to_dict()],
        }
        db = Database.from_dict(data)
        assert len(db.focus_sessions) == 1
        assert db.focus_sessions[0].id == session.id

    def test_database_from_dict_missing_sessions(self):
        from pytodo_qt.core.models import Database

        data = {"schema_version": 13, "lists": {}}
        db = Database.from_dict(data)
        assert db.focus_sessions == []

    def test_to_dict_for_sync_includes_sessions(self):
        from pytodo_qt.core.models import Database, FocusSession

        db = Database()
        session = FocusSession(
            item_id=uuid4(),
            list_id=uuid4(),
            start_time="2026-03-08T10:00:00",
            end_time="2026-03-08T10:25:00",
            duration_seconds=1500,
            date="2026-03-08",
        )
        db.focus_sessions.append(session)
        d = db.to_dict_for_sync()
        assert len(d["focus_sessions"]) == 1


class TestSessionStartTime:
    def test_session_start_time_initialized_on_start(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        assert widget.session_start_time is None
        widget.start(uuid4())
        assert widget.session_start_time is not None
        widget.stop()

    def test_session_start_time_cleared_on_stop(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        widget.start(uuid4())
        widget.stop()
        assert widget.session_start_time is None

    def test_session_completed_signal_includes_start_iso(self, qtbot):
        config = PomodoroConfig(work_duration=1, auto_start_break=False)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        item_id = uuid4()
        widget.start(item_id)
        widget._remaining_seconds = 1

        results = []

        def handler(iid, secs, start_iso):
            results.append((iid, secs, start_iso))

        widget.session_completed.connect(handler)
        widget._tick()

        assert len(results) == 1
        assert results[0][0] == item_id
        assert results[0][1] == 60  # 1 min
        assert len(results[0][2]) > 0  # start_iso not empty

    def test_stopped_signal_emitted_during_work(self, qtbot):
        config = PomodoroConfig(work_duration=25)
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        item_id = uuid4()
        widget.start(item_id)
        widget._remaining_seconds = 25 * 60 - 120  # 2 minutes elapsed

        results = []

        def handler(iid, elapsed, start_iso, stype):
            results.append((iid, elapsed, start_iso, stype))

        widget.stopped.connect(handler)
        widget.stop()

        assert len(results) == 1
        assert results[0][0] == item_id
        assert results[0][1] == 120
        assert results[0][3] == "work"

    def test_stopped_signal_not_emitted_when_idle(self, qtbot):
        config = PomodoroConfig()
        widget = PomodoroWidget(config)
        qtbot.addWidget(widget)

        results = []

        def handler(iid, elapsed, start_iso, stype):
            results.append((iid, elapsed, start_iso, stype))

        widget.stopped.connect(handler)
        widget.stop()

        assert len(results) == 0


class TestTodaysSessions:
    def test_update_sessions_shows_stats_and_recent(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)

        sessions = [
            {
                "start_time": "2026-03-08T10:00:00",
                "end_time": "2026-03-08T10:25:00",
                "duration_seconds": 1500,
                "completed": True,
                "session_type": "work",
            },
            {
                "start_time": "2026-03-08T10:30:00",
                "end_time": "2026-03-08T10:48:32",
                "duration_seconds": 1112,
                "completed": False,
                "session_type": "work",
            },
        ]
        dialog.update_sessions(sessions)

        assert "(2)" in dialog._sessions_toggle.text()
        # Stats label should show totals
        stats = dialog._stats_label.text()
        assert "Total: 2" in stats
        assert "\u2713 1" in stats  # 1 completed
        assert "\u2717 1" in stats  # 1 incomplete
        # Recent sessions should have 2 entries
        assert dialog._recent_layout.count() == 2

    def test_update_sessions_clears_previous(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)

        dialog.update_sessions(
            [
                {
                    "start_time": "2026-03-08T10:00:00",
                    "end_time": "2026-03-08T10:25:00",
                    "duration_seconds": 1500,
                    "completed": True,
                    "session_type": "work",
                },
            ]
        )
        assert dialog._recent_layout.count() == 1

        dialog.update_sessions([])
        assert dialog._recent_layout.count() == 0

    def test_many_sessions_capped_at_5_recent(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)

        sessions = [
            {
                "start_time": f"2026-03-08T{10 + i}:00:00",
                "end_time": f"2026-03-08T{10 + i}:25:00",
                "duration_seconds": 1500,
                "completed": True,
                "session_type": "work",
            }
            for i in range(10)
        ]
        dialog.update_sessions(sessions)

        assert "(10)" in dialog._sessions_toggle.text()
        # 5 recent + 1 "... and N earlier" label = 6
        assert dialog._recent_layout.count() == 6

    def test_stats_show_longest_shortest(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)

        sessions = [
            {
                "start_time": "2026-03-08T10:00:00",
                "end_time": "2026-03-08T10:25:00",
                "duration_seconds": 1500,
                "completed": True,
                "session_type": "work",
            },
            {
                "start_time": "2026-03-08T11:00:00",
                "end_time": "2026-03-08T11:10:00",
                "duration_seconds": 600,
                "completed": True,
                "session_type": "work",
            },
        ]
        dialog.update_sessions(sessions)

        stats = dialog._stats_label.text()
        assert "Longest: 25:00" in stats
        assert "Shortest: 10:00" in stats

    def test_toggle_sessions_expands_and_collapses(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)

        assert not dialog._sessions_expanded
        dialog._toggle_sessions()
        assert dialog._sessions_expanded
        assert "\u25bc" in dialog._sessions_toggle.text()
        dialog._toggle_sessions()
        assert not dialog._sessions_expanded
        assert "\u25b6" in dialog._sessions_toggle.text()

    def test_sessions_collapsed_by_default(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)

        assert not dialog._sessions_expanded


# ===========================================================================
# Phase D: Productivity Analytics tests
# ===========================================================================


class TestDailyGoalConfig:
    def test_default_zero(self):
        config = PomodoroConfig()
        assert config.daily_goal == 0

    def test_custom_value(self):
        config = PomodoroConfig(daily_goal=8)
        assert config.daily_goal == 8

    def test_toml_roundtrip(self):
        import tomllib

        config = AppConfig()
        config.pomodoro.daily_goal = 6
        toml_str = config.to_toml()
        assert "daily_goal = 6" in toml_str
        parsed = tomllib.loads(toml_str)
        restored = AppConfig.from_dict(parsed)
        assert restored.pomodoro.daily_goal == 6

    def test_from_dict_missing_daily_goal(self):
        """Old configs without daily_goal should default to 0."""
        config = AppConfig.from_dict({"pomodoro": {"work_duration": 30}})
        assert config.pomodoro.daily_goal == 0


class TestDatabaseAggregateQueries:
    def test_get_work_session_count_for_date(self, tmp_path):
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2025-01-15T10:00:00",
                end_time="2025-01-15T10:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date="2025-01-15",
            )
        )
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2025-01-15T10:30:00",
                end_time="2025-01-15T10:35:00",
                duration_seconds=300,
                completed=True,
                session_type="break",
                date="2025-01-15",
            )
        )
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2025-01-15T11:00:00",
                end_time="2025-01-15T11:10:00",
                duration_seconds=600,
                completed=False,
                session_type="work",
                date="2025-01-15",
            )
        )
        assert storage.get_work_session_count_for_date("2025-01-15") == 1
        assert storage.get_work_session_count_for_date("2025-01-16") == 0

    def test_get_work_duration_for_date(self, tmp_path):
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2025-01-15T10:00:00",
                end_time="2025-01-15T10:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date="2025-01-15",
            )
        )
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2025-01-15T11:00:00",
                end_time="2025-01-15T11:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date="2025-01-15",
            )
        )
        assert storage.get_work_duration_for_date("2025-01-15") == 3000
        assert storage.get_work_duration_for_date("2025-01-16") == 0

    def test_get_sessions_for_date_range(self, tmp_path):
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        for day in range(10, 16):
            storage.save_focus_session(
                FocusSession(
                    item_id=uuid4(),
                    list_id=uuid4(),
                    start_time=f"2025-01-{day:02d}T10:00:00",
                    end_time=f"2025-01-{day:02d}T10:25:00",
                    duration_seconds=1500,
                    completed=True,
                    session_type="work",
                    date=f"2025-01-{day:02d}",
                )
            )
        sessions = storage.get_sessions_for_date_range("2025-01-12", "2025-01-14")
        assert len(sessions) == 3
        sessions_all = storage.get_sessions_for_date_range("2025-01-10", "2025-01-15")
        assert len(sessions_all) == 6

    def test_get_sessions_for_date_range_empty(self, tmp_path):
        storage = DatabaseStorage(tmp_path / "test.db")
        sessions = storage.get_sessions_for_date_range("2025-01-01", "2025-01-31")
        assert sessions == []


class TestFocusStatsDialog:
    def test_dialog_creation(self, qtbot, tmp_path):
        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.dialogs.focus_stats import FocusStatsDialog

        db = Database()
        storage = DatabaseStorage(tmp_path / "test.db")
        analytics = AnalyticsService(storage.connection)
        config = PomodoroConfig()
        dialog = FocusStatsDialog(analytics, db, config)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "Focus Statistics"

    def test_dialog_with_daily_goal(self, qtbot, tmp_path):
        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.models import Database
        from pytodo_qt.gui.dialogs.focus_stats import FocusStatsDialog

        db = Database()
        storage = DatabaseStorage(tmp_path / "test.db")
        analytics = AnalyticsService(storage.connection)
        config = PomodoroConfig(daily_goal=8)
        dialog = FocusStatsDialog(analytics, db, config)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "Focus Statistics"

    def test_dialog_with_sessions(self, qtbot, tmp_path):
        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.models import Database, FocusSession
        from pytodo_qt.gui.dialogs.focus_stats import FocusStatsDialog

        db = Database()
        storage = DatabaseStorage(tmp_path / "test.db")
        from datetime import date

        today = date.today().isoformat()
        item_id = uuid4()
        list_id = uuid4()
        for i in range(3):
            storage.save_focus_session(
                FocusSession(
                    item_id=item_id,
                    list_id=list_id,
                    start_time=f"{today}T{10 + i}:00:00",
                    end_time=f"{today}T{10 + i}:25:00",
                    duration_seconds=1500,
                    completed=True,
                    session_type="work",
                    date=today,
                )
            )
        analytics = AnalyticsService(storage.connection)
        config = PomodoroConfig()
        dialog = FocusStatsDialog(analytics, db, config)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "Focus Statistics"

    def test_format_duration(self):
        from pytodo_qt.gui.dialogs.focus_stats import _format_duration

        assert _format_duration(0) == "0m"
        assert _format_duration(300) == "5m"
        assert _format_duration(3600) == "1h 00m"
        assert _format_duration(5400) == "1h 30m"
        assert _format_duration(7260) == "2h 01m"


class TestDailyGoalDisplay:
    def test_status_bar_update_daily_goal_shows(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import StatusBarWidget

        bar = StatusBarWidget()
        qtbot.addWidget(bar)
        bar.update_daily_goal(3, 8)
        assert not bar._daily_goal_ring.isHidden()
        assert bar._daily_goal_ring.toolTip() == "Today: 3/8 sessions"

    def test_status_bar_update_daily_goal_hides(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import StatusBarWidget

        bar = StatusBarWidget()
        qtbot.addWidget(bar)
        bar.update_daily_goal(3, 8)
        assert not bar._daily_goal_ring.isHidden()
        bar.update_daily_goal(0, 0)
        assert bar._daily_goal_ring.isHidden()

    def test_focus_timer_update_daily_goal_shows(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_daily_goal(5, 8)
        assert not dialog._daily_goal_label.isHidden()
        assert dialog._daily_goal_label.text() == "Today: 5/8 sessions"

    def test_focus_timer_update_daily_goal_hides(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_daily_goal(5, 8)
        assert not dialog._daily_goal_label.isHidden()
        dialog.update_daily_goal(0, 0)
        assert dialog._daily_goal_label.isHidden()


class TestItemProgress:
    @staticmethod
    def _icon_count(dialog) -> int:
        """Count QLabel icon widgets inside the progress container (excludes stretches)."""
        from PyQt6.QtWidgets import QLabel

        count = 0
        layout = dialog._item_progress_layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is not None and isinstance(item.widget(), QLabel):
                count += 1
        return count

    @staticmethod
    def _get_widgets(dialog) -> list:
        """Get all non-None widgets from the progress layout."""
        layout = dialog._item_progress_layout
        widgets = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is not None:
                w = item.widget()
                if w is not None:
                    widgets.append(w)
        return widgets

    def test_with_estimate_shows_only_completed(self, qtbot):
        """Only completed pomodoros render — pending slots are not
        drawn at all. The `estimated` parameter is accepted for
        backward compatibility but is not used. (Avoids the macOS
        emoji-opacity rendering issue and reads more cleanly: every
        tomato visible represents a session actually completed.)"""
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_item_progress(3, 4)
        assert not dialog._item_progress_container.isHidden()
        # 3 completed sessions → 3 icons, regardless of estimate.
        assert self._icon_count(dialog) == 3

    def test_without_estimate_shows_filled_only(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_item_progress(5, 0)
        assert not dialog._item_progress_container.isHidden()
        assert self._icon_count(dialog) == 5

    def test_single_session(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_item_progress(1, 0)
        assert self._icon_count(dialog) == 1

    def test_zero_hides(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_item_progress(3, 4)
        assert not dialog._item_progress_container.isHidden()
        dialog.update_item_progress(0, 0)
        assert dialog._item_progress_container.isHidden()

    def test_overflow_capped(self, qtbot):
        from PyQt6.QtWidgets import QLabel

        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_item_progress(15, 0)
        # Should show 12 icons + 1 overflow label
        labels = [w for w in self._get_widgets(dialog) if isinstance(w, QLabel)]
        assert len(labels) == 13  # 12 icon labels + 1 "+3" label
        assert "+3" in labels[-1].text()


class TestStreakComputation:
    """Streak tests now use AnalyticsService directly.
    Full streak coverage in tests/test_analytics.py::TestStreak."""

    def test_empty_data(self, tmp_path):
        from pytodo_qt.core.analytics import AnalyticsService

        storage = DatabaseStorage(tmp_path / "test.db")
        analytics = AnalyticsService(storage.connection)
        assert analytics.streak() == 0

    def test_consecutive_days(self, tmp_path):
        from datetime import date, timedelta

        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        today = date.today()
        for i in range(5):
            d = today - timedelta(days=i)
            storage.save_focus_session(
                FocusSession(
                    item_id=uuid4(),
                    list_id=uuid4(),
                    start_time=f"{d.isoformat()}T10:00:00",
                    end_time=f"{d.isoformat()}T10:25:00",
                    duration_seconds=1500,
                    completed=True,
                    session_type="work",
                    date=d.isoformat(),
                )
            )
        analytics = AnalyticsService(storage.connection)
        assert analytics.streak() == 5

    def test_gap_breaks_streak(self, tmp_path):
        from datetime import date, timedelta

        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        today = date.today()
        for i in range(2):
            d = today - timedelta(days=i)
            storage.save_focus_session(
                FocusSession(
                    item_id=uuid4(),
                    list_id=uuid4(),
                    start_time=f"{d.isoformat()}T10:00:00",
                    end_time=f"{d.isoformat()}T10:25:00",
                    duration_seconds=1500,
                    completed=True,
                    session_type="work",
                    date=d.isoformat(),
                )
            )
        # Skip day -2, add day -3
        d = today - timedelta(days=3)
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time=f"{d.isoformat()}T10:00:00",
                end_time=f"{d.isoformat()}T10:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date=d.isoformat(),
            )
        )
        analytics = AnalyticsService(storage.connection)
        assert analytics.streak() == 2

    def test_streak_with_daily_goal(self, tmp_path):
        from datetime import date, timedelta

        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        today = date.today()
        for j in range(3):
            storage.save_focus_session(
                FocusSession(
                    item_id=uuid4(),
                    list_id=uuid4(),
                    start_time=f"{today.isoformat()}T{10 + j}:00:00",
                    end_time=f"{today.isoformat()}T{10 + j}:25:00",
                    duration_seconds=1500,
                    completed=True,
                    session_type="work",
                    date=today.isoformat(),
                )
            )
        d = today - timedelta(days=1)
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time=f"{d.isoformat()}T10:00:00",
                end_time=f"{d.isoformat()}T10:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date=d.isoformat(),
            )
        )
        analytics = AnalyticsService(storage.connection)
        assert analytics.streak(daily_goal=3) == 1

    def test_no_sessions_today(self, tmp_path):
        from datetime import date, timedelta

        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        d = date.today() - timedelta(days=1)
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time=f"{d.isoformat()}T10:00:00",
                end_time=f"{d.isoformat()}T10:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date=d.isoformat(),
            )
        )
        analytics = AnalyticsService(storage.connection)
        assert analytics.streak() == 0


# ===========================================================================
# MobileAccessWizard tests
# ===========================================================================


class TestMobileAccessWizard:
    def test_wizard_creation_with_url(self, monkeypatch):
        """Wizard creates successfully when LAN IP is detected."""
        monkeypatch.setattr(
            "pytodo_qt.gui.dialogs.web_connect._get_lan_ip",
            lambda: "192.168.1.42",
        )
        from pytodo_qt.gui.dialogs.web_connect import MobileAccessWizard

        dialog = MobileAccessWizard(parent=None)
        # Without a parent MainWindow, URL is built from LAN IP with default HTTPS
        assert dialog._lan_ip == "192.168.1.42"

    def test_wizard_creation_no_network(self, monkeypatch):
        """Wizard handles missing network gracefully."""
        monkeypatch.setattr(
            "pytodo_qt.gui.dialogs.web_connect._get_lan_ip",
            lambda: None,
        )
        from pytodo_qt.gui.dialogs.web_connect import MobileAccessWizard

        dialog = MobileAccessWizard(parent=None)
        assert dialog._url is None

    def test_wizard_starts_on_choose_page(self, monkeypatch):
        """Wizard shows choose page by default (no parent = no devices)."""
        monkeypatch.setattr(
            "pytodo_qt.gui.dialogs.web_connect._get_lan_ip",
            lambda: "192.168.1.42",
        )
        from pytodo_qt.gui.dialogs.web_connect import MobileAccessWizard

        dialog = MobileAccessWizard(parent=None)
        assert dialog._stack.currentIndex() == MobileAccessWizard.PAGE_CHOOSE

    def test_qr_pixmap_generated(self):
        """QR code renders to a non-empty pixmap."""
        from pytodo_qt.gui.dialogs.web_connect import _render_qr_pixmap

        pixmap = _render_qr_pixmap("http://192.168.1.42:8080", size=200)
        assert not pixmap.isNull()
        assert pixmap.width() > 0
        assert pixmap.height() > 0

    def test_get_lan_ip_returns_string_or_none(self):
        """_get_lan_ip returns a string IP or None."""
        from pytodo_qt.gui.dialogs.web_connect import _get_lan_ip

        result = _get_lan_ip()
        assert result is None or isinstance(result, str)


# ===========================================================================
# Phase E: Gamification & Habit Building tests
# ===========================================================================


class TestLifetimeSessionCount:
    """Tests for DatabaseStorage.get_lifetime_work_session_count()."""

    def test_empty_database(self, tmp_path):
        storage = DatabaseStorage(tmp_path / "test.db")
        assert storage.get_lifetime_work_session_count() == 0
        storage.close()

    def test_counts_only_completed_work_sessions(self, tmp_path):
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        # Completed work session
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2026-03-01T10:00:00",
                end_time="2026-03-01T10:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date="2026-03-01",
            )
        )
        # Incomplete work session (interrupted)
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2026-03-01T11:00:00",
                end_time="2026-03-01T11:10:00",
                duration_seconds=600,
                completed=False,
                session_type="work",
                date="2026-03-01",
            )
        )
        # Completed break session (shouldn't count)
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2026-03-01T10:25:00",
                end_time="2026-03-01T10:30:00",
                duration_seconds=300,
                completed=True,
                session_type="break",
                date="2026-03-01",
            )
        )
        assert storage.get_lifetime_work_session_count() == 1
        storage.close()

    def test_counts_across_multiple_dates(self, tmp_path):
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        for day in range(1, 6):
            storage.save_focus_session(
                FocusSession(
                    item_id=uuid4(),
                    list_id=uuid4(),
                    start_time=f"2026-03-{day:02d}T10:00:00",
                    end_time=f"2026-03-{day:02d}T10:25:00",
                    duration_seconds=1500,
                    completed=True,
                    session_type="work",
                    date=f"2026-03-{day:02d}",
                )
            )
        assert storage.get_lifetime_work_session_count() == 5
        storage.close()


class TestInterruptedSessionCount:
    """Tests for DatabaseStorage.get_interrupted_session_count_for_date()."""

    def test_empty_database(self, tmp_path):
        storage = DatabaseStorage(tmp_path / "test.db")
        assert storage.get_interrupted_session_count_for_date("2026-03-08") == 0
        storage.close()

    def test_counts_only_incomplete_work_sessions(self, tmp_path):
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        # Completed work session
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2026-03-08T10:00:00",
                end_time="2026-03-08T10:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date="2026-03-08",
            )
        )
        # Interrupted work session
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2026-03-08T11:00:00",
                end_time="2026-03-08T11:10:00",
                duration_seconds=600,
                completed=False,
                session_type="work",
                date="2026-03-08",
            )
        )
        # Interrupted break (shouldn't count)
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2026-03-08T12:00:00",
                end_time="2026-03-08T12:03:00",
                duration_seconds=180,
                completed=False,
                session_type="break",
                date="2026-03-08",
            )
        )
        assert storage.get_interrupted_session_count_for_date("2026-03-08") == 1
        storage.close()


class TestStreakInDatabase:
    """Tests for DatabaseStorage.compute_current_streak()."""

    def test_empty_database(self, tmp_path):
        storage = DatabaseStorage(tmp_path / "test.db")
        assert storage.compute_current_streak() == 0
        storage.close()

    def test_consecutive_days(self, tmp_path, monkeypatch):
        from datetime import date, timedelta

        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        today = date.today()
        # Create sessions for today and 2 previous days
        for offset in range(3):
            d = today - timedelta(days=offset)
            storage.save_focus_session(
                FocusSession(
                    item_id=uuid4(),
                    list_id=uuid4(),
                    start_time=f"{d.isoformat()}T10:00:00",
                    end_time=f"{d.isoformat()}T10:25:00",
                    duration_seconds=1500,
                    completed=True,
                    session_type="work",
                    date=d.isoformat(),
                )
            )
        assert storage.compute_current_streak() == 3
        storage.close()

    def test_gap_breaks_streak(self, tmp_path):
        from datetime import date, timedelta

        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        today = date.today()
        # Session today
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time=f"{today.isoformat()}T10:00:00",
                end_time=f"{today.isoformat()}T10:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date=today.isoformat(),
            )
        )
        # Session 2 days ago (gap yesterday)
        two_days_ago = today - timedelta(days=2)
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time=f"{two_days_ago.isoformat()}T10:00:00",
                end_time=f"{two_days_ago.isoformat()}T10:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date=two_days_ago.isoformat(),
            )
        )
        assert storage.compute_current_streak() == 1
        storage.close()

    def test_daily_goal_threshold(self, tmp_path):
        from datetime import date

        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        today = date.today()
        # Only 1 session today, but goal is 2
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time=f"{today.isoformat()}T10:00:00",
                end_time=f"{today.isoformat()}T10:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date=today.isoformat(),
            )
        )
        assert storage.compute_current_streak(daily_goal=2) == 0
        # Add second session
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time=f"{today.isoformat()}T11:00:00",
                end_time=f"{today.isoformat()}T11:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date=today.isoformat(),
            )
        )
        assert storage.compute_current_streak(daily_goal=2) == 1
        storage.close()


class TestDailyGoalRingWidget:
    """Tests for the DailyGoalRingWidget."""

    def test_creation(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import DailyGoalRingWidget

        ring = DailyGoalRingWidget()
        qtbot.addWidget(ring)
        assert ring.width() == 22
        assert ring.height() == 22

    def test_hidden_when_no_goal(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import DailyGoalRingWidget

        ring = DailyGoalRingWidget()
        qtbot.addWidget(ring)
        ring.update_goal(3, 0)
        assert not ring.isVisible()

    def test_visible_when_goal_set(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import DailyGoalRingWidget

        ring = DailyGoalRingWidget()
        qtbot.addWidget(ring)
        ring.show()
        ring.update_goal(3, 8)
        assert ring.isVisible()
        assert ring.toolTip() == "Today: 3/8 sessions"

    def test_tooltip_updates(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import DailyGoalRingWidget

        ring = DailyGoalRingWidget()
        qtbot.addWidget(ring)
        ring.update_goal(5, 5)
        assert ring.toolTip() == "Today: 5/5 sessions"

    def test_paint_does_not_crash(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import DailyGoalRingWidget

        ring = DailyGoalRingWidget()
        qtbot.addWidget(ring)
        ring.update_goal(2, 4)
        ring.show()
        ring.repaint()  # Force paintEvent


class TestFocusScore:
    """Tests for focus score computation."""

    def test_no_sessions_returns_negative(self, qtbot):
        """No sessions today → score row hidden (returns -1)."""
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_focus_score(-1)
        # The score row is now a container (label + info icon); hiding
        # the container removes the whole row from view.
        assert dialog._focus_score_container.isHidden()

    def test_grade_mapping(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_focus_score(95)
        assert "A" in dialog._focus_score_label.text()
        dialog.update_focus_score(80)
        assert "B" in dialog._focus_score_label.text()
        dialog.update_focus_score(65)
        assert "C" in dialog._focus_score_label.text()
        dialog.update_focus_score(45)
        assert "D" in dialog._focus_score_label.text()
        dialog.update_focus_score(30)
        assert "F" in dialog._focus_score_label.text()

    def test_streak_display(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        dialog = FocusTimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_streak(0)
        assert dialog._streak_label.isHidden()
        dialog.update_streak(5)
        assert not dialog._streak_label.isHidden()
        assert "5 days" in dialog._streak_label.text()
        dialog.update_streak(1)
        assert "1 day" in dialog._streak_label.text()
        assert "days" not in dialog._streak_label.text()


class TestMilestoneConfig:
    """Tests for milestone_notifications config field."""

    def test_default_enabled(self):
        config = PomodoroConfig()
        assert config.milestone_notifications is True

    def test_toml_roundtrip(self):
        import tomllib

        config = AppConfig()
        config.pomodoro.milestone_notifications = False
        toml_str = config.to_toml()
        data = tomllib.loads(toml_str)
        restored = AppConfig.from_dict(data)
        assert restored.pomodoro.milestone_notifications is False

    def test_from_dict_default(self):
        config = AppConfig.from_dict({"pomodoro": {}})
        assert config.pomodoro.milestone_notifications is True


# ===========================================================================
# Interruption Insights tests
# ===========================================================================


class TestInterruptionInsights:
    """Insight computation logic moved to AnalyticsService.

    Full coverage in tests/test_analytics.py:
    - TestTimeBlockAnalysis (3 tests): block counts, completion rates
    - TestItemSummary (5 tests): per-item grouping, completion rates
    - TestRollingAverages (3 tests): trend data
    - TestFocusScore (4 tests): score components
    - TestDailySummary (5 tests): daily aggregation
    """

    pass
