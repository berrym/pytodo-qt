"""status_bar.py

Enhanced status bar widget.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QStatusBar,
    QWidget,
)

from ...core.logger import Logger
from ..styles.themes import get_colors

_POMODORO_EMOJI = {"work": "\U0001f345", "break": "\u2615", "pause": "\u23f8\ufe0f"}
_STOPWATCH_EMOJI = {"running": "\u23f1\ufe0f", "paused": "\u23f8\ufe0f"}

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
        self.setToolTip(self.tr(f"Today: {completed}/{goal} sessions") if goal > 0 else "")
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
            colors = get_colors()
            color = (
                QColor("#43a047")
                if self._completed >= self._goal
                else QColor(colors["focus_timer_stopwatch_running"])
            )
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


class _PomodoroAttentionOverlay(QWidget):
    """Transparent halo painted around the status-bar focus-session
    section to draw the eye when a pomodoro/stopwatch session starts.

    A new user can easily miss that the bottom-of-window timer is
    live and clickable. On session start this pulses three times
    (the attention burst) then settles into a faint steady ring (a
    passive "active here" cue) for the rest of the session, fading
    out when the session ends.

    Driven by a single QTimer parented to this widget with manual
    paint — no QGraphicsEffect, no QPropertyAnimation. That is the
    teardown-safe pattern established for floating/overlay widgets
    in this codebase; QGraphicsEffect/QPropertyAnimation destabilise
    pytest-qt teardown. The timer runs only during the pulse burst
    and the fade-out; the steady phase is a static paint with the
    timer stopped. Mouse-transparent so clicks fall through to the
    timer labels beneath.
    """

    _GLOW_MARGIN = 9  # px the halo extends beyond the timer region
    _TICK_MS = 16  # ~60 fps
    _PULSE_MS = 560  # one pulse hump
    _PULSE_COUNT = 3
    _FADE_OUT_MS = 260
    _STEADY = 0.40  # resting intensity after the burst
    _PEAK = 1.10  # pulse-crest intensity
    # (outward spread px, alpha fraction) — outer rings fainter, the
    # ring nearest the text the brightest. Stroked outlines only, so
    # the timer digits in the centre are never washed out.
    _RING_LAYERS = ((8, 0.12), (5, 0.24), (3, 0.42), (1, 0.62))

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._color = QColor("#1976d2")
        self._intensity = 0.0
        self._phase = "idle"  # idle | pulse | steady | fade
        self._elapsed = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._on_tick)
        self.hide()

    def start_attention(self, color: str) -> None:
        """Begin the pulse burst, then settle to the steady accent."""
        self._color = QColor(color)
        self._phase = "pulse"
        self._elapsed = 0
        self._intensity = self._STEADY
        if not self.isVisible():
            self.show()
        self.raise_()
        if not self._timer.isActive():
            self._timer.start()

    def set_color(self, color: str) -> None:
        """Recolor without re-triggering the burst (e.g. work->break)."""
        new = QColor(color)
        if new != self._color:
            self._color = new
            if self._phase in ("steady", "pulse"):
                self.update()

    def end_session(self) -> None:
        """Fade the halo out, then hide. Idempotent — a no-op if the
        overlay is already idle or already fading."""
        if self._phase in ("idle", "fade"):
            return
        self._phase = "fade"
        self._elapsed = 0
        if not self._timer.isActive():
            self._timer.start()

    def _on_tick(self) -> None:
        self._elapsed += self._TICK_MS
        if self._phase == "pulse":
            total = self._PULSE_MS * self._PULSE_COUNT
            if self._elapsed >= total:
                self._phase = "steady"
                self._intensity = self._STEADY
                self._timer.stop()  # steady is a static paint
            else:
                local = (self._elapsed % self._PULSE_MS) / self._PULSE_MS
                hump = math.sin(math.pi * local)
                self._intensity = self._STEADY + (self._PEAK - self._STEADY) * hump
        elif self._phase == "fade":
            frac = min(1.0, self._elapsed / self._FADE_OUT_MS)
            self._intensity = self._STEADY * (1.0 - frac)
            if frac >= 1.0:
                self._phase = "idle"
                self._intensity = 0.0
                self._timer.stop()
                self.hide()
                return
        self.update()

    def paintEvent(self, a0) -> None:  # noqa: N802
        if self._intensity <= 0.0 or self._phase == "idle":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Inner frame = the original timer region (overlay inset by the
        # glow margin). Rings are stroked outward from it so the centre
        # stays clear and the digits remain readable.
        m = self._GLOW_MARGIN
        inner = QRectF(self.rect().adjusted(m, m, -m, -m))
        radius = inner.height() / 2.0
        for spread, alpha_frac in self._RING_LAYERS:
            color = QColor(self._color)
            color.setAlphaF(max(0.0, min(1.0, self._intensity * alpha_frac)))
            painter.setPen(QPen(color, 2))
            r = inner.adjusted(-spread, -spread, spread, spread)
            painter.drawRoundedRect(r, radius + spread, radius + spread)
        painter.end()

    def hideEvent(self, a0) -> None:  # noqa: N802
        # Teardown safety: never run the timer into widget destruction.
        self._timer.stop()
        self._phase = "idle"
        super().hideEvent(a0)


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
        # Set before any widget so resizeEvent (which Qt can fire during
        # construction) short-circuits before the overlay attrs exist.
        self._prev_pomodoro_state = "idle"

        # Build all widgets
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumWidth(130)
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat(self.tr("%p% complete"))

        self.list_count_label = QLabel()
        self._pomodoro_icon_label = QLabel()
        self._pomodoro_icon_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pomodoro_label = QLabel()
        self.pomodoro_label.setCursor(Qt.CursorShape.PointingHandCursor)
        # Monospace digits so the timer doesn't shift width as glyphs change each second.
        # Bold is set on the QFont (not via QSS font-weight) so per-state setStyleSheet
        # calls below can change color without resetting the font family.
        _timer_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        _timer_font.setBold(True)
        self.pomodoro_label.setFont(_timer_font)
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

        # Attention halo around the focus-session region. Child of the
        # container (so it shares the labels' coordinate space) but not
        # in the layout — manually positioned over the timer's icon +
        # label. Mouse-transparent; clicks fall through to the labels.
        self._pomodoro_container = container
        self._pomodoro_attention = _PomodoroAttentionOverlay(container)

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

    def resizeEvent(self, a0) -> None:  # noqa: N802
        # Keep the attention halo aligned with the timer region when the
        # window width changes during a live session. Deferred so the
        # status-bar layout settles before geometry is read.
        super().resizeEvent(a0)
        if self._prev_pomodoro_state != "idle":
            QTimer.singleShot(0, self._reposition_pomodoro_attention)

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
        self.list_count_label.setText(self.tr(f"Lists: {list_count}"))
        self.item_count_label.setText(self.tr(f"Current: {completed_count}/{item_count}"))
        self.total_label.setText(self.tr(f"Total: {total_completed}/{total_items}"))

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
            self.server_status_label.setText(self.tr(f"Server: {address}:{port}"))
            self.server_status_label.setStyleSheet("color: green;")
        else:
            self.server_status_label.setText(self.tr("Server: Off"))
            self.server_status_label.setStyleSheet("color: gray;")

    def set_web_status(self, running: bool, port: int = 0, pin: str = "") -> None:
        """Set the web server status display."""
        if running:
            text = f"Web: :{port}"
            if pin:
                text += f"  PIN: {pin}"
            self.web_status_label.setText(text)
            self.web_status_label.setStyleSheet("color: green;")
            self.web_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.web_status_label.setToolTip(self.tr("Click to show connection QR code"))
        else:
            self.web_status_label.setText(self.tr("Web: Off"))
            self.web_status_label.setStyleSheet("color: gray;")
            self.web_status_label.setToolTip("")
            self.web_status_label.unsetCursor()

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
            self.sync_status_label.setText(self.tr("Syncing"))
            self.sync_status_label.setStyleSheet(
                f"color: {get_colors()['focus_timer_stopwatch_running']};"
            )
        elif state == "success":
            self._last_sync_time = datetime.now()
            self._last_auto_sync = auto
            self._update_sync_time_display()
            self.sync_status_label.setStyleSheet("color: green;")
        elif state == "error":
            self.sync_status_label.setText(self.tr("Sync failed"))
            self.sync_status_label.setStyleSheet("color: red;")
        else:  # idle
            if self._last_sync_time:
                self._update_sync_time_display()
                self.sync_status_label.setStyleSheet("")
            else:
                self.sync_status_label.setText(self.tr("Not synced"))
                self.sync_status_label.setStyleSheet("color: gray;")

    def _update_sync_time_display(self) -> None:
        """Update the sync time display with relative time."""
        if self._last_sync_time:
            time_ago = _format_time_ago(self._last_sync_time)
            prefix = self.tr("Auto-synced") if self._last_auto_sync else self.tr("Synced")
            self.sync_status_label.setText(f"{prefix} {time_ago}")
        else:
            self.sync_status_label.setText(self.tr("Not synced"))

    def update_pomodoro_display(self, state: str, time_str: str = "") -> None:
        """Update the Pomodoro/stopwatch timer display in the status bar.

        Args:
            state: One of "idle", "working", "break", "paused",
                   "stopwatch_running", "stopwatch_paused"
            time_str: Formatted time (e.g., "23:41")
        """
        if state == "idle" or not time_str:
            self._pomodoro_icon_label.setVisible(False)
            self.pomodoro_label.setVisible(False)
            self._pomodoro_separator.setVisible(False)
            if self._prev_pomodoro_state != "idle":
                self._pomodoro_attention.end_session()
                self._prev_pomodoro_state = "idle"
            return

        colors = get_colors()
        state_color = {
            "working": colors["focus_timer_working"],
            "break": colors["focus_timer_break"],
            "paused": colors["focus_timer_paused"],
            "stopwatch_running": colors["focus_timer_stopwatch_running"],
            "stopwatch_paused": colors["focus_timer_paused"],
        }.get(state)
        if state_color is None:
            return

        if state == "working":
            self._set_pomodoro_icon("work")
        elif state == "break":
            self._set_pomodoro_icon("break")
        elif state == "paused":
            self._set_pomodoro_icon("pause")
        elif state == "stopwatch_running":
            self._pomodoro_icon_label.setText(_STOPWATCH_EMOJI.get("running", "\u23f1\ufe0f"))
        elif state == "stopwatch_paused":
            self._pomodoro_icon_label.setText(_STOPWATCH_EMOJI.get("paused", "\u23f8\ufe0f"))

        self.pomodoro_label.setText(time_str)
        self.pomodoro_label.setStyleSheet(f"color: {state_color};")
        self._pomodoro_icon_label.setVisible(True)
        self.pomodoro_label.setVisible(True)
        self._pomodoro_separator.setVisible(True)

        # Attention halo. Session start (idle -> active) triggers the
        # pulse burst; a state change within a live session (e.g.
        # work -> break) just recolors the steady accent without
        # re-bursting. The halo tracks the session *type*, not the
        # paused sub-state: pausing a stopwatch keeps the stopwatch
        # blue rather than flipping to the shared amber paused color
        # (the label text still uses state_color).
        attention_color = (
            colors["focus_timer_stopwatch_running"] if state == "stopwatch_paused" else state_color
        )
        if self._prev_pomodoro_state == "idle":
            # Labels were just made visible; their geometry isn't final
            # until the layout pass runs, so position on the next loop.
            QTimer.singleShot(0, self._reposition_pomodoro_attention)
            self._pomodoro_attention.start_attention(attention_color)
        elif state != self._prev_pomodoro_state:
            self._pomodoro_attention.set_color(attention_color)
        self._prev_pomodoro_state = state

    def _reposition_pomodoro_attention(self) -> None:
        """Position the attention halo over the union of the timer's
        icon + label, inflated by the halo margin. No-op while the
        timer is hidden."""
        if not self.pomodoro_label.isVisible():
            return
        region = self._pomodoro_icon_label.geometry().united(self.pomodoro_label.geometry())
        m = _PomodoroAttentionOverlay._GLOW_MARGIN
        self._pomodoro_attention.setGeometry(
            QRect(
                region.x() - m,
                region.y() - m,
                region.width() + 2 * m,
                region.height() + 2 * m,
            )
        )
        self._pomodoro_attention.raise_()

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
            self.pending_sync_label.setText(self.tr(f"Queued: {count}"))
            self.pending_sync_label.setStyleSheet("color: orange;")
            self.pending_sync_label.setToolTip(
                self.tr(f"{count} sync(s) queued for offline devices")
            )
            self.pending_sync_label.setVisible(True)
        else:
            self.pending_sync_label.setText("")
            self.pending_sync_label.setVisible(False)
