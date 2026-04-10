"""Tests for stopwatch widget, config, schema, and EditTimeSpentCommand."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from pytodo_qt.core.config import AppConfig, StopwatchConfig
from pytodo_qt.core.database import SCHEMA_VERSION, DatabaseStorage
from pytodo_qt.core.models import TodoItem
from pytodo_qt.gui.widgets.stopwatch import StopwatchState, StopwatchWidget

# --- StopwatchConfig tests ---


class TestStopwatchConfig:
    def test_defaults(self):
        config = StopwatchConfig()
        assert config.minimum_session == 60
        assert config.idle_timeout == 0
        assert config.show_in_status_bar is True
        assert config.sound_on_stop is False

    def test_custom_values(self):
        config = StopwatchConfig(
            minimum_session=30, idle_timeout=10, show_in_status_bar=False, sound_on_stop=True
        )
        assert config.minimum_session == 30
        assert config.idle_timeout == 10
        assert config.show_in_status_bar is False
        assert config.sound_on_stop is True

    def test_toml_roundtrip(self):
        config = AppConfig()
        config.stopwatch.minimum_session = 30
        config.stopwatch.idle_timeout = 5
        config.stopwatch.sound_on_stop = True

        toml_str = config.to_toml()
        assert "minimum_session = 30" in toml_str
        assert "idle_timeout = 5" in toml_str
        assert "sound_on_stop = true" in toml_str

        import tomllib

        data = tomllib.loads(toml_str)
        restored = AppConfig.from_dict(data)
        assert restored.stopwatch.minimum_session == 30
        assert restored.stopwatch.idle_timeout == 5
        assert restored.stopwatch.sound_on_stop is True
        assert restored.stopwatch.show_in_status_bar is True

    def test_app_config_has_stopwatch(self):
        config = AppConfig()
        assert hasattr(config, "stopwatch")
        assert isinstance(config.stopwatch, StopwatchConfig)


# --- Schema v16 tests ---


class TestSchemaV16:
    def test_current_version(self):
        # Sentinel: estimated_minutes was introduced in v16.
        assert SCHEMA_VERSION >= 16

    def test_fresh_database_has_estimated_minutes(self, tmp_path: Path):
        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()
        assert storage.get_schema_version() == SCHEMA_VERSION

        columns = [row[1] for row in storage.connection.execute("PRAGMA table_info(items)")]
        assert "estimated_minutes" in columns
        storage.close()

    def test_migration_from_v15(self, tmp_path: Path):
        """Simulates a v15 database being migrated to v16."""
        import sqlite3

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            """CREATE TABLE items (
                id TEXT PRIMARY KEY, list_id TEXT NOT NULL,
                reminder TEXT NOT NULL DEFAULT '', priority INTEGER NOT NULL DEFAULT 2,
                complete INTEGER NOT NULL DEFAULT 0,
                due_date TEXT, due_time TEXT, tags TEXT,
                recurrence_type TEXT, recurrence_interval INTEGER NOT NULL DEFAULT 1,
                recurrence_end_date TEXT, recurrence_end_count INTEGER,
                recurrence_count INTEGER NOT NULL DEFAULT 0,
                missed_recurrences INTEGER NOT NULL DEFAULT 0,
                time_spent INTEGER NOT NULL DEFAULT 0,
                pomodoro_count INTEGER NOT NULL DEFAULT 0,
                estimated_pomodoros INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                parent_id TEXT, board_column TEXT NOT NULL DEFAULT ''
            )"""
        )
        conn.execute(
            """CREATE TABLE lists (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0, private INTEGER NOT NULL DEFAULT 0,
                board_columns TEXT
            )"""
        )
        conn.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '15')")
        conn.commit()
        conn.close()

        storage = DatabaseStorage(db_path)
        storage.open()
        assert storage.get_schema_version() == SCHEMA_VERSION

        columns = [row[1] for row in storage.connection.execute("PRAGMA table_info(items)")]
        assert "estimated_minutes" in columns
        storage.close()


# --- TodoItem estimated_minutes tests ---


class TestEstimatedMinutes:
    def test_default_zero(self):
        item = TodoItem()
        assert item.estimated_minutes == 0

    def test_serialization_roundtrip(self):
        item = TodoItem(reminder="test", estimated_minutes=90)
        d = item.to_dict()
        assert d["estimated_minutes"] == 90

        restored = TodoItem.from_dict(d)
        assert restored.estimated_minutes == 90

    def test_missing_in_dict_defaults_to_zero(self):
        d = {"id": str(uuid4()), "reminder": "test"}
        item = TodoItem.from_dict(d)
        assert item.estimated_minutes == 0

    def test_database_persistence(self, tmp_path: Path):
        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()

        from pytodo_qt.core.models import TodoList

        todo_list = TodoList(name="Test")
        storage.save_list(todo_list)

        item = TodoItem(reminder="test task", estimated_minutes=45)
        storage.save_item(todo_list.id, item)

        db = storage.load_database()
        loaded_list = db.lists.get(todo_list.id)
        assert loaded_list is not None
        loaded_item = loaded_list.get_item(item.id)
        assert loaded_item is not None
        assert loaded_item.estimated_minutes == 45
        storage.close()


# --- StopwatchWidget state machine tests ---


class TestStopwatchWidget:
    @pytest.fixture()
    def widget(self, qtbot):
        config = StopwatchConfig()
        w = StopwatchWidget(config)
        qtbot.addWidget(w)
        return w

    def test_initial_state(self, widget):
        assert widget.state == StopwatchState.IDLE
        assert widget.item_id is None
        assert widget.item_name == ""
        assert widget.elapsed_seconds == 0

    def test_start(self, widget):
        item_id = uuid4()
        widget.start(item_id, "Test task")
        assert widget.state == StopwatchState.RUNNING
        assert widget.item_id == item_id
        assert widget.item_name == "Test task"
        assert widget.elapsed_seconds == 0

    def test_pause_resume(self, widget):
        widget.start(uuid4(), "Test")
        widget.pause()
        assert widget.state == StopwatchState.PAUSED

        widget.resume()
        assert widget.state == StopwatchState.RUNNING

    def test_pause_from_idle_no_op(self, widget):
        widget.pause()
        assert widget.state == StopwatchState.IDLE

    def test_resume_from_idle_no_op(self, widget):
        widget.resume()
        assert widget.state == StopwatchState.IDLE

    def test_stop_from_running_above_minimum(self, widget, qtbot):
        widget.start(uuid4(), "Test")
        widget._elapsed_seconds = 120  # Simulate 2 minutes elapsed

        with qtbot.waitSignal(widget.session_completed, timeout=1000):
            widget.stop()

        assert widget.state == StopwatchState.IDLE
        assert widget.item_id is None

    def test_stop_from_running_below_minimum(self, widget, qtbot):
        widget.start(uuid4(), "Test")
        widget._elapsed_seconds = 30  # Below 60s minimum

        with qtbot.waitSignal(widget.stopped, timeout=1000):
            widget.stop()

        assert widget.state == StopwatchState.IDLE

    def test_stop_from_paused(self, widget, qtbot):
        widget.start(uuid4(), "Test")
        widget._elapsed_seconds = 120
        widget.pause()

        with qtbot.waitSignal(widget.session_completed, timeout=1000):
            widget.stop()

        assert widget.state == StopwatchState.IDLE

    def test_stop_from_idle_no_signal(self, widget):
        # Should not crash or emit signals
        widget.stop()
        assert widget.state == StopwatchState.IDLE

    def test_start_while_running_stops_first(self, widget, qtbot):
        id1 = uuid4()
        id2 = uuid4()
        widget.start(id1, "First")
        widget._elapsed_seconds = 120

        # Starting on a new item should stop the first
        widget.start(id2, "Second")
        assert widget.item_id == id2
        assert widget.state == StopwatchState.RUNNING

    def test_tick_increments(self, widget):
        widget.start(uuid4(), "Test")
        assert widget.elapsed_seconds == 0
        widget._tick()
        assert widget.elapsed_seconds == 1
        widget._tick()
        assert widget.elapsed_seconds == 2

    def test_state_changed_signals(self, widget, qtbot):
        states = []
        widget.state_changed.connect(states.append)

        widget.start(uuid4(), "Test")
        assert "stopwatch_running" in states

        widget.pause()
        assert "stopwatch_paused" in states

        widget.resume()
        assert states.count("stopwatch_running") == 2

        widget._elapsed_seconds = 120
        widget.stop()
        assert "idle" in states

    def test_session_completed_signal_args(self, widget, qtbot):
        item_id = uuid4()
        widget.start(item_id, "Test")
        widget._elapsed_seconds = 90

        with qtbot.waitSignal(widget.session_completed, timeout=1000) as sig:
            widget.stop()

        assert sig.args[0] == item_id
        assert sig.args[1] == 90
        assert len(sig.args[2]) > 0  # start_iso non-empty

    def test_configurable_minimum_session(self, qtbot):
        config = StopwatchConfig(minimum_session=10)
        w = StopwatchWidget(config)
        qtbot.addWidget(w)

        w.start(uuid4(), "Test")
        w._elapsed_seconds = 15  # Above 10s minimum

        with qtbot.waitSignal(w.session_completed, timeout=1000):
            w.stop()

    def test_minimum_session_zero_records_everything(self, qtbot):
        config = StopwatchConfig(minimum_session=0)
        w = StopwatchWidget(config)
        qtbot.addWidget(w)

        w.start(uuid4(), "Test")
        w._elapsed_seconds = 1  # Just 1 second

        with qtbot.waitSignal(w.session_completed, timeout=1000):
            w.stop()

    def test_update_config(self, widget):
        new_config = StopwatchConfig(minimum_session=30)
        widget.update_config(new_config)
        assert widget._config.minimum_session == 30


# --- Format helpers ---


class TestFormatElapsed:
    def test_zero(self):
        assert StopwatchWidget.format_elapsed(0) == "00:00"

    def test_under_minute(self):
        assert StopwatchWidget.format_elapsed(45) == "00:45"

    def test_minutes(self):
        assert StopwatchWidget.format_elapsed(125) == "02:05"

    def test_one_hour(self):
        assert StopwatchWidget.format_elapsed(3600) == "1:00:00"

    def test_over_hour(self):
        assert StopwatchWidget.format_elapsed(3661) == "1:01:01"

    def test_negative(self):
        assert StopwatchWidget.format_elapsed(-5) == "00:00"

    def test_large(self):
        assert StopwatchWidget.format_elapsed(36000) == "10:00:00"


class TestFormatTimeSpent:
    def test_zero(self):
        assert StopwatchWidget.format_time_spent(0) == ""

    def test_minutes_only(self):
        assert StopwatchWidget.format_time_spent(300) == "5m"

    def test_hours_and_minutes(self):
        assert StopwatchWidget.format_time_spent(5400) == "1h 30m"


# --- EditTimeSpentCommand increment_pomodoro tests ---


class TestEditTimeSpentCommandIncrementPomodoro:
    def test_increment_pomodoro_false(self, tmp_path: Path):
        """Verify that increment_pomodoro=False leaves pomodoro_count unchanged."""
        from unittest.mock import MagicMock

        from pytodo_qt.core.models import TodoList
        from pytodo_qt.gui.commands import EditTimeSpentCommand

        # Build a mock window with database
        window = MagicMock()
        db = MagicMock()
        todo_list = TodoList(name="Test")
        item = TodoItem(reminder="test", time_spent=100, pomodoro_count=3)
        todo_list.items[item.id] = item
        db.lists = {todo_list.id: todo_list}
        window._database = db

        cmd = EditTimeSpentCommand(
            window,
            todo_list.id,
            item.id,
            old_time_spent=100,
            seconds_to_add=60,
            old_pomodoro_count=3,
            increment_pomodoro=False,
        )
        cmd.redo()
        assert item.time_spent == 160  # 100 + 60
        assert item.pomodoro_count == 3  # NOT incremented

        cmd.undo()
        assert item.time_spent == 100
        assert item.pomodoro_count == 3

    def test_increment_pomodoro_true_default(self, tmp_path: Path):
        """Default behavior increments pomodoro_count."""
        from unittest.mock import MagicMock

        from pytodo_qt.core.models import TodoList
        from pytodo_qt.gui.commands import EditTimeSpentCommand

        window = MagicMock()
        db = MagicMock()
        todo_list = TodoList(name="Test")
        item = TodoItem(reminder="test", time_spent=100, pomodoro_count=3)
        todo_list.items[item.id] = item
        db.lists = {todo_list.id: todo_list}
        window._database = db

        cmd = EditTimeSpentCommand(
            window,
            todo_list.id,
            item.id,
            old_time_spent=100,
            seconds_to_add=1500,
            old_pomodoro_count=3,
        )
        cmd.redo()
        assert item.time_spent == 1600  # 100 + 1500
        assert item.pomodoro_count == 4  # Incremented

        cmd.undo()
        assert item.time_spent == 100
        assert item.pomodoro_count == 3
