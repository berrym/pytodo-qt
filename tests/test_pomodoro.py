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
    def test_current_version_is_10(self):
        assert SCHEMA_VERSION == 11

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
