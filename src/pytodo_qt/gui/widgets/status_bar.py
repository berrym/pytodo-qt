"""status_bar.py

Enhanced status bar widget.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QStatusBar,
    QWidget,
)

from ...core.logger import Logger

_POMODORO_EMOJI = {"work": "\U0001f345", "break": "\u2615", "pause": "\u23f8\ufe0f"}

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


class DailyGoalRingWidget(QWidget):
    """Circular progress ring showing daily goal completion."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self._completed = 0
        self._goal = 0

    def update_goal(self, completed: int, goal: int) -> None:
        self._completed = completed
        self._goal = goal
        self.setToolTip(f"Today: {completed}/{goal} sessions" if goal > 0 else "")
        self.setVisible(goal > 0)
        self.update()

    def paintEvent(self, a0) -> None:  # noqa: N802
        if self._goal <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw area with margin for pen width
        pen_width = 2.5
        margin = pen_width / 2 + 1
        rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)

        # Background ring
        bg_pen = QPen(QColor(180, 180, 180, 80), pen_width)
        bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(rect, 0, 360 * 16)

        # Progress arc
        ratio = min(1.0, self._completed / self._goal) if self._goal > 0 else 0.0
        if ratio > 0:
            color = QColor("#43a047") if self._completed >= self._goal else QColor("#4A90D9")
            fg_pen = QPen(color, pen_width)
            fg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(fg_pen)
            # Qt arcs: 90*16 is 12 o'clock, positive = counter-clockwise
            span = int(-ratio * 360 * 16)
            painter.drawArc(rect, 90 * 16, span)

        # Center text
        font = QFont()
        font.setPointSize(7)
        font.setBold(True)
        painter.setFont(font)
        text_color = (
            QColor("#43a047")
            if self._completed >= self._goal
            else QColor(self.palette().text().color())
        )
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(self._completed))
        painter.end()


class StatusBarWidget(QStatusBar):
    """Enhanced status bar with progress and statistics.

    Uses a single permanent container with QHBoxLayout to prevent
    QStatusBar's showMessage() from hiding left-side widgets.
    """

    pomodoro_clicked = pyqtSignal()
    web_connect_clicked = pyqtSignal()

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
        self._pomodoro_icon_label = QLabel()
        self._pomodoro_icon_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pomodoro_label = QLabel()
        self.pomodoro_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._daily_goal_ring = DailyGoalRingWidget()
        self._daily_goal_ring.hide()
        # Install event filters after both labels exist to avoid AttributeError
        self._pomodoro_icon_label.installEventFilter(self)
        self.pomodoro_label.installEventFilter(self)
        self.item_count_label = QLabel()
        self.total_label = QLabel()
        self._message_label = QLabel()
        self.status_label = QLabel()
        self.server_status_label = QLabel()
        self.web_status_label = QLabel()
        self.web_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.web_status_label.installEventFilter(self)
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
        self._pomodoro_separator = self._create_separator()
        layout.addWidget(self._pomodoro_separator)
        layout.addWidget(self._pomodoro_icon_label)
        layout.addWidget(self.pomodoro_label)
        self._daily_goal_separator = self._create_separator()
        layout.addWidget(self._daily_goal_separator)
        layout.addWidget(self._daily_goal_ring)
        self._daily_goal_separator.hide()
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
        layout.addWidget(self.web_status_label)
        layout.addWidget(self._create_separator())
        layout.addWidget(self.server_status_label)
        layout.addWidget(self._create_separator())
        layout.addWidget(self.status_label)

        self.addPermanentWidget(container, 1)

        # Initialize
        self.update_stats(0, 0, 0, 0, 0)
        self.update_pomodoro_display("idle")
        self.set_status("Ready")
        self.set_web_status(False)
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

    def eventFilter(self, a0, a1) -> bool:  # noqa: N802
        """Detect clicks on the pomodoro and web status labels."""
        if a1 is not None and a1.type() == QEvent.Type.MouseButtonPress:
            if (
                a0 in (self.pomodoro_label, self._pomodoro_icon_label)
                and self.pomodoro_label.isVisible()
            ):
                self.pomodoro_clicked.emit()
                return True
            if a0 is self.web_status_label:
                self.web_connect_clicked.emit()
                return True
        return super().eventFilter(a0, a1)

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

    def set_web_status(self, running: bool, port: int = 0, pin: str = "") -> None:
        """Set the web server status display."""
        if running:
            text = f"Web: :{port}"
            if pin:
                text += f"  PIN: {pin}"
            self.web_status_label.setText(text)
            self.web_status_label.setStyleSheet("color: green; cursor: pointer;")
            self.web_status_label.setToolTip("Click to show connection QR code")
        else:
            self.web_status_label.setText("Web: Off")
            self.web_status_label.setStyleSheet("color: gray;")
            self.web_status_label.setToolTip("")

    def show_message(self, message: str, timeout: int = 3000) -> None:
        """Show a temporary message without disrupting layout."""
        self._message_label.setText(message)
        self._message_timer.start(timeout)

    def _clear_message(self) -> None:
        """Clear the temporary message."""
        self._message_label.setText("")

    def set_sync_status(self, state: str, auto: bool = False) -> None:
        """Set the sync status display.

        Args:
            state: One of "idle", "syncing", "success", "error"
            auto: True if this is an auto-sync operation
        """
        if state == "syncing":
            self.sync_status_label.setText("Syncing")
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

    def update_pomodoro_display(self, state: str, time_str: str = "") -> None:
        """Update the Pomodoro timer display in the status bar.

        Args:
            state: One of "idle", "working", "break", "paused"
            time_str: Formatted remaining time (e.g., "23:41")
        """
        if state == "idle" or not time_str:
            self._pomodoro_icon_label.setVisible(False)
            self.pomodoro_label.setVisible(False)
            self._pomodoro_separator.setVisible(False)
        elif state == "working":
            self._set_pomodoro_icon("work")
            self.pomodoro_label.setText(time_str)
            self.pomodoro_label.setStyleSheet("color: #E74C3C; font-weight: bold;")
            self._pomodoro_icon_label.setVisible(True)
            self.pomodoro_label.setVisible(True)
            self._pomodoro_separator.setVisible(True)
        elif state == "break":
            self._set_pomodoro_icon("break")
            self.pomodoro_label.setText(time_str)
            self.pomodoro_label.setStyleSheet("color: #27AE60; font-weight: bold;")
            self._pomodoro_icon_label.setVisible(True)
            self.pomodoro_label.setVisible(True)
            self._pomodoro_separator.setVisible(True)
        elif state == "paused":
            self._set_pomodoro_icon("pause")
            self.pomodoro_label.setText(time_str)
            self.pomodoro_label.setStyleSheet("color: #F39C12; font-weight: bold;")
            self._pomodoro_icon_label.setVisible(True)
            self.pomodoro_label.setVisible(True)
            self._pomodoro_separator.setVisible(True)

    def _set_pomodoro_icon(self, state_name: str) -> None:
        """Set the pomodoro icon emoji for the given state."""
        emoji = _POMODORO_EMOJI.get(state_name, "")
        self._pomodoro_icon_label.setText(emoji)

    def update_daily_goal(self, completed: int, goal: int) -> None:
        """Update the daily goal progress display.

        Args:
            completed: Number of completed work sessions today
            goal: Daily goal target (0 = no goal)
        """
        if goal <= 0:
            self._daily_goal_ring.hide()
            self._daily_goal_separator.hide()
            return
        self._daily_goal_ring.update_goal(completed, goal)
        self._daily_goal_ring.show()
        self._daily_goal_separator.show()

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
