"""stopwatch.py

Independent time tracking widget — counts UP from zero.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ...core.config import StopwatchConfig


class StopwatchState(Enum):
    IDLE = "idle"
    RUNNING = "stopwatch_running"
    PAUSED = "stopwatch_paused"


class StopwatchWidget(QWidget):
    """Count-up timer for free-form time tracking.

    Signals:
        session_completed(UUID, int, str): item_id, seconds, start_iso
        stopped(UUID, int, str, str): item_id, elapsed, start_iso, session_type
        state_changed(str): state name
    """

    session_completed = pyqtSignal(object, int, str)  # (item_id, seconds, start_iso)
    stopped = pyqtSignal(object, int, str, str)  # (item_id, elapsed, start_iso, session_type)
    state_changed = pyqtSignal(str)  # state name

    def __init__(self, config: StopwatchConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self._config = config
        self._state = StopwatchState.IDLE
        self._item_id: UUID | None = None
        self._item_name: str = ""
        self._elapsed_seconds: int = 0
        self._session_start_time: datetime | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    @property
    def state(self) -> StopwatchState:
        return self._state

    @property
    def item_id(self) -> UUID | None:
        return self._item_id

    @property
    def item_name(self) -> str:
        return self._item_name

    @property
    def elapsed_seconds(self) -> int:
        return self._elapsed_seconds

    @property
    def session_start_time(self) -> datetime | None:
        return self._session_start_time

    def update_config(self, config: StopwatchConfig) -> None:
        """Update config (takes effect immediately for minimum_session threshold)."""
        self._config = config

    def start(self, item_id: UUID, item_name: str = "") -> None:
        """Start tracking time for the given item."""
        if self._state in (StopwatchState.RUNNING, StopwatchState.PAUSED):
            self.stop()

        self._item_id = item_id
        self._item_name = item_name
        self._elapsed_seconds = 0
        self._session_start_time = datetime.now()
        self._state = StopwatchState.RUNNING
        self._timer.start()
        self.state_changed.emit(self._state.value)

    def stop(self) -> None:
        """Stop tracking. Emits session_completed or stopped based on minimum_session."""
        self._timer.stop()
        item_id = self._item_id
        elapsed = self._elapsed_seconds
        start_iso = self._session_start_time.isoformat() if self._session_start_time else ""

        if item_id is not None and self._state != StopwatchState.IDLE:
            if elapsed >= self._config.minimum_session:
                self.session_completed.emit(item_id, elapsed, start_iso)
            else:
                self.stopped.emit(item_id, elapsed, start_iso, "stopwatch")

        self._state = StopwatchState.IDLE
        self._item_id = None
        self._item_name = ""
        self._elapsed_seconds = 0
        self._session_start_time = None
        self.state_changed.emit(self._state.value)

    def pause(self) -> None:
        """Pause the running stopwatch."""
        if self._state == StopwatchState.RUNNING:
            self._timer.stop()
            self._state = StopwatchState.PAUSED
            self.state_changed.emit(self._state.value)

    def resume(self) -> None:
        """Resume a paused stopwatch."""
        if self._state == StopwatchState.PAUSED:
            self._state = StopwatchState.RUNNING
            self._timer.start()
            self.state_changed.emit(self._state.value)

    def _tick(self) -> None:
        self._elapsed_seconds += 1

    @staticmethod
    def format_elapsed(seconds: int) -> str:
        """Format elapsed seconds as MM:SS or H:MM:SS."""
        seconds = max(0, seconds)
        h, remainder = divmod(seconds, 3600)
        m, s = divmod(remainder, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
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
