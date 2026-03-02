"""status_bar.py

Enhanced status bar widget.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QStatusBar,
    QWidget,
)

from ...core.logger import Logger

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


def _format_time_ago(dt: datetime) -> str:
    """Format a datetime as 'X ago' relative to now."""
    now = datetime.now()
    delta = now - dt

    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    else:
        days = seconds // 86400
        return f"{days}d ago"


class StatusBarWidget(QStatusBar):
    """Enhanced status bar with progress and statistics.

    Uses a single permanent container with QHBoxLayout to prevent
    QStatusBar's showMessage() from hiding left-side widgets.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Disable QStatusBar's built-in size grip -- we manage layout ourselves
        self.setSizeGripEnabled(True)

        # Build all widgets
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumWidth(130)
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p% complete")

        self.list_count_label = QLabel()
        self.item_count_label = QLabel()
        self.total_label = QLabel()
        self._message_label = QLabel()
        self.status_label = QLabel()
        self.server_status_label = QLabel()
        self.pending_sync_label = QLabel()
        self.sync_status_label = QLabel()

        # Timer for temporary messages
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._clear_message)

        # Sync state tracking
        self._last_sync_time: datetime | None = None
        self._last_auto_sync: bool = False
        self._sync_update_timer = QTimer(self)
        self._sync_update_timer.timeout.connect(self._update_sync_time_display)
        self._sync_update_timer.start(30000)

        # Single container -- added as permanent so QStatusBar never hides it
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Left section: stats
        layout.addWidget(self.progress_bar)
        layout.addWidget(self._create_separator())
        layout.addWidget(self.list_count_label)
        layout.addWidget(self._create_separator())
        layout.addWidget(self.item_count_label)
        self._total_separator = self._create_separator()
        layout.addWidget(self._total_separator)
        layout.addWidget(self.total_label)
        layout.addWidget(self._create_separator())
        layout.addWidget(self._message_label)

        # Spacer pushes right section to the far right
        layout.addStretch(1)

        # Right section: sync and server info
        layout.addWidget(self.pending_sync_label)
        layout.addWidget(self._create_separator())
        layout.addWidget(self.sync_status_label)
        layout.addWidget(self._create_separator())
        layout.addWidget(self.server_status_label)
        layout.addWidget(self._create_separator())
        layout.addWidget(self.status_label)

        self.addPermanentWidget(container, 1)

        # Initialize
        self.update_stats(0, 0, 0, 0, 0)
        self.set_status("Ready")
        self.set_server_status(False, "", 0)
        self.set_sync_status("idle")
        self.set_pending_sync_count(0)

    def _create_separator(self) -> QWidget:
        """Create a visual separator line."""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedWidth(10)
        return sep

    def update_stats(
        self,
        list_count: int,
        item_count: int,
        completed_count: int,
        total_items: int,
        total_completed: int,
    ) -> None:
        """Update statistics display."""
        self.list_count_label.setText(f"Lists: {list_count}")
        self.item_count_label.setText(f"Current: {completed_count}/{item_count}")
        self.total_label.setText(f"Total: {total_completed}/{total_items}")

        # Show global total only when multiple lists exist
        show_total = list_count > 1
        self.total_label.setVisible(show_total)
        self._total_separator.setVisible(show_total)

        # Progress bar tracks current list completion
        if item_count > 0:
            self.progress_bar.setMaximum(item_count)
            self.progress_bar.setValue(completed_count)
        else:
            self.progress_bar.setMaximum(1)
            self.progress_bar.setValue(0)

    def set_status(self, message: str) -> None:
        """Set the status message."""
        self.status_label.setText(message)

    def set_server_status(self, running: bool, address: str = "", port: int = 0) -> None:
        """Set the server status display."""
        if running:
            self.server_status_label.setText(f"Server: {address}:{port}")
            self.server_status_label.setStyleSheet("color: green;")
        else:
            self.server_status_label.setText("Server: Off")
            self.server_status_label.setStyleSheet("color: gray;")

    def show_message(self, message: str, timeout: int = 3000) -> None:
        """Show a temporary message without disrupting layout."""
        self._message_label.setText(message)
        self._message_timer.start(timeout)

    def _clear_message(self) -> None:
        """Clear the temporary message."""
        self._message_label.setText("")

    def set_sync_status(
        self, state: str, direction: str = "", peer: str = "", auto: bool = False
    ) -> None:
        """Set the sync status display.

        Args:
            state: One of "idle", "syncing", "success", "error"
            direction: "push", "pull", or "" for idle
            peer: Peer name/address for context
            auto: True if this is an auto-sync operation
        """
        if state == "syncing":
            if direction == "push":
                text = f"Pushing to {peer}..." if peer else "Pushing..."
            elif direction == "pull":
                text = f"Pulling from {peer}..." if peer else "Pulling..."
            else:
                text = "Syncing..."
            self.sync_status_label.setText(text)
            self.sync_status_label.setStyleSheet("color: #4A90D9;")  # Blue
        elif state == "success":
            self._last_sync_time = datetime.now()
            self._last_auto_sync = auto
            self._update_sync_time_display()
            self.sync_status_label.setStyleSheet("color: green;")
        elif state == "error":
            self.sync_status_label.setText("Sync failed")
            self.sync_status_label.setStyleSheet("color: red;")
        else:  # idle
            if self._last_sync_time:
                self._update_sync_time_display()
                self.sync_status_label.setStyleSheet("")
            else:
                self.sync_status_label.setText("Not synced")
                self.sync_status_label.setStyleSheet("color: gray;")

    def _update_sync_time_display(self) -> None:
        """Update the sync time display with relative time."""
        if self._last_sync_time:
            time_ago = _format_time_ago(self._last_sync_time)
            prefix = "Auto-synced" if self._last_auto_sync else "Synced"
            self.sync_status_label.setText(f"{prefix} {time_ago}")
        else:
            self.sync_status_label.setText("Not synced")

    def set_pending_sync_count(self, count: int) -> None:
        """Set the pending sync count display.

        Args:
            count: Number of pending syncs across all devices
        """
        if count > 0:
            self.pending_sync_label.setText(f"Queued: {count}")
            self.pending_sync_label.setStyleSheet("color: orange;")
            self.pending_sync_label.setToolTip(f"{count} sync(s) queued for offline devices")
            self.pending_sync_label.setVisible(True)
        else:
            self.pending_sync_label.setText("")
            self.pending_sync_label.setVisible(False)
