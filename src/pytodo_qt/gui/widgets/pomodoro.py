"""pomodoro.py

Focus timer widget implementing the Pomodoro Technique.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ...core.config import PomodoroConfig

if TYPE_CHECKING:
    pass


class TimerState(Enum):
    IDLE = "idle"
    WORKING = "working"
    BREAK = "break"
    PAUSED = "paused"


class PomodoroWidget(QWidget):
    """Focus timer with work/break cycles.

    Signals:
        session_completed(UUID, int): item_id and seconds when a work session ends
        state_changed(str): emitted on every state transition with state name
    """

    session_completed = pyqtSignal(object, int, str)  # (item_id, seconds, start_iso)
    break_completed = pyqtSignal(object, int, str)  # (item_id, seconds, start_iso)
    stopped = pyqtSignal(object, int, str, str)  # (item_id, elapsed, start_iso, session_type)
    state_changed = pyqtSignal(str)  # state name

    def __init__(self, config: PomodoroConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._state = TimerState.IDLE
        self._item_id: UUID | None = None
        self._item_name: str = ""
        self._remaining_seconds: int = 0
        self._session_count: int = 0  # completed sessions in current cycle
        self._session_start_time: datetime | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    @property
    def state(self) -> TimerState:
        return self._state

    @property
    def item_id(self) -> UUID | None:
        return self._item_id

    @property
    def item_name(self) -> str:
        return self._item_name

    @property
    def remaining_seconds(self) -> int:
        return self._remaining_seconds

    @property
    def session_count(self) -> int:
        return self._session_count

    @property
    def session_start_time(self) -> datetime | None:
        return self._session_start_time

    @property
    def sessions_before_long_break(self) -> int:
        return self._config.sessions_before_long_break

    def update_config(self, config: PomodoroConfig) -> None:
        """Update config (takes effect on next session, not mid-timer)."""
        self._config = config

    def start(self, item_id: UUID, item_name: str = "") -> None:
        """Start a work session for the given item."""
        if self._state == TimerState.WORKING or self._state == TimerState.BREAK:
            self.stop()

        self._item_id = item_id
        self._item_name = item_name
        self._session_count = 0
        self._start_work_session()

    def stop(self) -> None:
        """Stop the timer. Emits stopped signal for partial session tracking."""
        was_state = self._state
        if was_state == TimerState.PAUSED:
            was_state = getattr(self, "_paused_from", TimerState.WORKING)
        item_id = self._item_id
        start_time = self._session_start_time

        # Calculate elapsed time for partial session
        if was_state in (TimerState.WORKING, TimerState.BREAK) and item_id is not None:
            if was_state == TimerState.WORKING:
                total = self._config.work_duration * 60
            elif (
                self._session_count > 0
                and self._session_count % self._config.sessions_before_long_break == 0
            ):
                total = self._config.long_break_duration * 60
            else:
                total = self._config.break_duration * 60
            elapsed = total - self._remaining_seconds
            start_iso = start_time.isoformat() if start_time else ""
            session_type = "work" if was_state == TimerState.WORKING else "break"
            self.stopped.emit(item_id, elapsed, start_iso, session_type)

        self._timer.stop()
        self._state = TimerState.IDLE
        self._remaining_seconds = 0
        self._item_id = None
        self._item_name = ""
        self._session_start_time = None
        self.state_changed.emit(self._state.value)

    def pause(self) -> None:
        """Pause a running work or break session."""
        if self._state in (TimerState.WORKING, TimerState.BREAK):
            self._paused_from = self._state
            self._timer.stop()
            self._state = TimerState.PAUSED
            self.state_changed.emit(self._state.value)

    def resume(self) -> None:
        """Resume a paused session (returns to work or break)."""
        if self._state == TimerState.PAUSED:
            self._state = getattr(self, "_paused_from", TimerState.WORKING)
            self._timer.start()
            self.state_changed.emit(self._state.value)

    def _start_work_session(self) -> None:
        self._remaining_seconds = self._config.work_duration * 60
        self._session_start_time = datetime.now()
        self._state = TimerState.WORKING
        self._timer.start()
        self.state_changed.emit(self._state.value)

    def _start_break(self) -> None:
        if (
            self._session_count > 0
            and self._session_count % self._config.sessions_before_long_break == 0
        ):
            self._remaining_seconds = self._config.long_break_duration * 60
        else:
            self._remaining_seconds = self._config.break_duration * 60
        self._session_start_time = datetime.now()
        self._state = TimerState.BREAK
        self._timer.start()
        self.state_changed.emit(self._state.value)

    def _tick(self) -> None:
        self._remaining_seconds -= 1

        if self._remaining_seconds <= 0:
            self._timer.stop()
            if self._state == TimerState.WORKING:
                self._on_work_complete()
            elif self._state == TimerState.BREAK:
                self._on_break_complete()

    def _on_work_complete(self) -> None:
        duration_seconds = self._config.work_duration * 60
        self._session_count += 1
        start_iso = self._session_start_time.isoformat() if self._session_start_time else ""
        if self._item_id is not None:
            self.session_completed.emit(self._item_id, duration_seconds, start_iso)
        if self._config.auto_start_break:
            self._start_break()
        else:
            self._state = TimerState.IDLE
            self.state_changed.emit(self._state.value)

    def _on_break_complete(self) -> None:
        start_iso = self._session_start_time.isoformat() if self._session_start_time else ""
        if self._item_id is not None:
            break_duration = self._remaining_seconds  # already 0 at completion
            if (
                self._session_count > 0
                and self._session_count % self._config.sessions_before_long_break == 0
            ):
                break_duration = self._config.long_break_duration * 60
            else:
                break_duration = self._config.break_duration * 60
            self.break_completed.emit(self._item_id, break_duration, start_iso)
        if self._config.auto_start_break and self._item_id is not None:
            self._start_work_session()
        else:
            self._state = TimerState.IDLE
            self.state_changed.emit(self._state.value)

    @staticmethod
    def format_time(seconds: int) -> str:
        """Format seconds as MM:SS."""
        m, s = divmod(max(0, seconds), 60)
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def format_time_spent(seconds: int) -> str:
        """Format cumulative seconds as human-readable string."""
        if seconds <= 0:
            return ""
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
