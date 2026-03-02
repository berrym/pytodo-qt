"""auto_sync.py

Scheduler for automatic sync operations.

Two complementary mechanisms:
- Debounced push: After local changes, push to peers after a quiet period.
- Periodic sync: Full bidirectional sync at regular intervals.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..core.logger import Logger

logger = Logger(__name__)


class AutoSyncScheduler(QWidget):
    """Schedules automatic sync with online trusted peers.

    Owns two QTimers and emits signals when sync should happen.
    Knows nothing about networking — only timing.
    """

    push_requested = pyqtSignal()
    sync_requested = pyqtSignal()

    def __init__(
        self,
        delay_seconds: int = 0,
        interval_minutes: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._delay_seconds = delay_seconds
        self._interval_minutes = interval_minutes

        # Debounce timer: singleshot, restarted on each notify_change()
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._on_debounce)

        # Periodic timer: repeating
        self._periodic_timer = QTimer(self)
        self._periodic_timer.timeout.connect(self._on_periodic)

        self._running = False

    def start(self) -> None:
        """Start the scheduler (timers activate based on config values)."""
        self._running = True

        if self._interval_minutes > 0:
            interval_ms = self._interval_minutes * 60 * 1000
            self._periodic_timer.start(interval_ms)
            logger.log.info(
                "Auto-sync periodic timer started: every %d minute(s)",
                self._interval_minutes,
            )

        if self._delay_seconds > 0:
            logger.log.info(
                "Auto-sync debounce enabled: %d second(s) after changes",
                self._delay_seconds,
            )

    def stop(self) -> None:
        """Stop both timers."""
        self._running = False
        self._debounce_timer.stop()
        self._periodic_timer.stop()

    def notify_change(self) -> None:
        """Local data changed. Restart the debounce timer."""
        if not self._running or self._delay_seconds <= 0:
            return
        self._debounce_timer.start(self._delay_seconds * 1000)

    def update_config(self, delay_seconds: int, interval_minutes: int) -> None:
        """Reconfigure timers from updated config values."""
        old_delay = self._delay_seconds
        old_interval = self._interval_minutes
        self._delay_seconds = delay_seconds
        self._interval_minutes = interval_minutes

        if not self._running:
            return

        # Update periodic timer
        if interval_minutes != old_interval:
            self._periodic_timer.stop()
            if interval_minutes > 0:
                self._periodic_timer.start(interval_minutes * 60 * 1000)
                logger.log.info(
                    "Auto-sync periodic timer updated: every %d minute(s)",
                    interval_minutes,
                )

        # Update debounce (stop pending if delay changed or disabled)
        if delay_seconds != old_delay:
            self._debounce_timer.stop()
            if delay_seconds > 0:
                logger.log.info(
                    "Auto-sync debounce updated: %d second(s) after changes",
                    delay_seconds,
                )

    def _on_debounce(self) -> None:
        """Debounce timer fired — emit push request."""
        logger.log.debug("Auto-sync debounce fired, requesting push")
        self.push_requested.emit()

    def _on_periodic(self) -> None:
        """Periodic timer fired — emit full sync request."""
        logger.log.debug("Auto-sync periodic timer fired, requesting sync")
        self.sync_requested.emit()
