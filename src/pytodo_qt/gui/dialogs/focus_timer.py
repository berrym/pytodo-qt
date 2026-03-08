"""focus_timer.py

Floating always-on-top focus timer window.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_ICONS_DIR = Path(__file__).parent.parent / "icons"


class FocusTimerDialog(QDialog):
    """Floating timer window for the Pomodoro focus feature.

    Shows countdown, progress bar, item name, session counter,
    and pause/stop/skip controls. Always stays on top.

    Signals:
        pause_requested: Pause or resume the timer
        stop_requested: Stop the timer
        skip_break_requested: Skip the current break
    """

    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    skip_break_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Focus Timer")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(300)
        self._sessions_expanded = False
        self._tomato_pixmap: QPixmap | None = None
        path = _ICONS_DIR / "pomodoro-work.svg"
        if path.exists():
            self._tomato_pixmap = QPixmap(str(path)).scaled(
                16,
                16,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._setup_ui()
        self.adjustSize()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Large countdown display
        self._time_label = QLabel("00:00")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(36)
        font.setBold(True)
        self._time_label.setFont(font)
        layout.addWidget(self._time_label)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(8)
        layout.addWidget(self._progress_bar)

        # Item name
        self._item_label = QLabel()
        self._item_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._item_label.setWordWrap(True)
        layout.addWidget(self._item_label)

        # Session counter (cycle position, e.g. "Session 2 of 4")
        self._session_label = QLabel()
        self._session_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._session_label.setStyleSheet("color: gray;")
        layout.addWidget(self._session_label)

        # Item pomodoro progress — row of tomato icons
        self._item_progress_container = QWidget()
        self._item_progress_layout = QHBoxLayout(self._item_progress_container)
        self._item_progress_layout.setContentsMargins(0, 0, 0, 0)
        self._item_progress_layout.setSpacing(4)
        self._item_progress_layout.addStretch()
        self._item_progress_layout.addStretch()
        self._item_progress_container.hide()
        layout.addWidget(self._item_progress_container)

        # Daily goal progress
        self._daily_goal_label = QLabel()
        self._daily_goal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._daily_goal_label.setStyleSheet("color: gray;")
        self._daily_goal_label.hide()
        layout.addWidget(self._daily_goal_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._pause_btn = QPushButton("\u23f8 Pause")
        self._pause_btn.setMinimumWidth(80)
        self._pause_btn.clicked.connect(self.pause_requested.emit)
        btn_layout.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("\u25a0 Stop")
        self._stop_btn.setMinimumWidth(80)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        btn_layout.addWidget(self._stop_btn)

        self._skip_btn = QPushButton("\u23ed Skip")
        self._skip_btn.setMinimumWidth(80)
        self._skip_btn.clicked.connect(self.skip_break_requested.emit)
        self._skip_btn.setVisible(False)
        btn_layout.addWidget(self._skip_btn)

        layout.addLayout(btn_layout)

        # Today's Sessions (collapsible)
        self._sessions_toggle = QPushButton("\u25b6 Today's Sessions")
        self._sessions_toggle.setFlat(True)
        self._sessions_toggle.setStyleSheet("text-align: left; color: gray;")
        self._sessions_toggle.clicked.connect(self._toggle_sessions)
        layout.addWidget(self._sessions_toggle)

        self._sessions_container = QWidget()
        self._sessions_layout = QVBoxLayout(self._sessions_container)
        self._sessions_layout.setContentsMargins(4, 0, 4, 0)
        self._sessions_layout.setSpacing(2)
        self._sessions_container.setVisible(False)
        layout.addWidget(self._sessions_container)

    def _toggle_sessions(self) -> None:
        """Toggle the sessions section visibility."""
        self._sessions_expanded = not self._sessions_expanded
        self._sessions_container.setVisible(self._sessions_expanded)
        arrow = "\u25bc" if self._sessions_expanded else "\u25b6"
        count = self._sessions_layout.count()
        self._sessions_toggle.setText(f"{arrow} Today's Sessions ({count})")
        self.adjustSize()

    def update_sessions(self, sessions: list[dict[str, Any]]) -> None:
        """Update the Today's Sessions display.

        Args:
            sessions: List of dicts with keys: start_time, end_time,
                      duration_seconds, completed, session_type
        """
        # Clear existing session labels
        while self._sessions_layout.count():
            item = self._sessions_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        for i, s in enumerate(sessions, 1):
            label = self._format_session_label(i, s)
            self._sessions_layout.addWidget(label)

        # Update toggle button text
        arrow = "\u25bc" if self._sessions_expanded else "\u25b6"
        self._sessions_toggle.setText(f"{arrow} Today's Sessions ({len(sessions)})")

        if self._sessions_expanded:
            self.adjustSize()

    def _format_session_label(self, index: int, session: dict[str, Any]) -> QLabel:
        """Create a formatted label for a session entry."""
        duration = session.get("duration_seconds", 0)
        m, s = divmod(duration, 60)
        completed = session.get("completed", True)
        mark = "\u2713" if completed else "\u2717"

        # Parse times for display
        start = session.get("start_time", "")
        end = session.get("end_time", "")
        time_range = ""
        try:
            from datetime import datetime

            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            time_range = f"  ({start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')})"
        except (ValueError, TypeError):
            pass

        text = f"Session {index}: {m:02d}:{s:02d} {mark}{time_range}"
        label = QLabel(text)
        label.setStyleSheet("color: gray; font-size: 11px;")

        # Add separator line
        label.setFrameShape(QFrame.Shape.NoFrame)
        return label

    def update_display(
        self,
        state: str,
        remaining: int,
        item_name: str,
        session_count: int,
        total_sessions: int,
        total_duration: int = 0,
        item_pomodoro_count: int = 0,
        item_estimated: int = 0,
    ) -> None:
        """Update all display elements.

        Args:
            state: Timer state ("working", "break", "paused", "idle")
            remaining: Remaining seconds
            item_name: Name of the focused item
            session_count: Completed sessions in current cycle
            total_sessions: Sessions before long break
            total_duration: Total duration of current session in seconds
            item_pomodoro_count: Completed pomodoros on the focused item
            item_estimated: Estimated pomodoros for the item (0 = no estimate)
        """
        if state == "idle":
            self.hide()
            return

        # Time display
        m, s = divmod(max(0, remaining), 60)
        self._time_label.setText(f"{m:02d}:{s:02d}")

        # Progress bar
        if total_duration > 0:
            self._progress_bar.setMaximum(total_duration)
            self._progress_bar.setValue(total_duration - remaining)
        else:
            self._progress_bar.setMaximum(1)
            self._progress_bar.setValue(0)

        # Color based on state
        if state == "working":
            self._time_label.setStyleSheet("color: #E74C3C;")
        elif state == "break":
            self._time_label.setStyleSheet("color: #27AE60;")
        elif state == "paused":
            self._time_label.setStyleSheet("color: #F39C12;")

        # Item name
        self._item_label.setText(item_name)

        # Session counter — use item estimate when available, else cycle position
        if item_estimated > 0:
            current = item_pomodoro_count + (1 if state in ("working", "paused") else 0)
            self._session_label.setText(f"Session {current}/{item_estimated}")
        else:
            current = session_count + (1 if state in ("working", "paused") else 0)
            self._session_label.setText(f"Session {current} of {total_sessions}")

        # Pause button text
        if state == "paused":
            self._pause_btn.setText("\u25b6 Resume")
        else:
            self._pause_btn.setText("\u23f8 Pause")

        # Pause button enabled during working, break, and paused
        self._pause_btn.setEnabled(state in ("working", "break", "paused"))

        # Skip button visible only during break
        skip_visible = state == "break"
        if self._skip_btn.isVisible() != skip_visible:
            self._skip_btn.setVisible(skip_visible)
            self.adjustSize()

    def update_item_progress(self, pomodoro_count: int, estimated: int) -> None:
        """Update the focused item's pomodoro progress as tomato icons.

        Shows filled tomatoes for completed sessions and dimmed tomatoes for
        remaining slots (when an estimate is set). Hidden when count is 0.

        Args:
            pomodoro_count: Completed pomodoros for this item
            estimated: Estimated pomodoros (0 = no estimate)
        """
        if pomodoro_count <= 0 and estimated <= 0:
            self._item_progress_container.hide()
            return

        # Clear previous icons (skip the two stretch items at index 0 and end)
        layout = self._item_progress_layout
        while layout.count() > 2:
            item = layout.takeAt(1)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        total = max(pomodoro_count, estimated)
        # Cap display to avoid overflow — show "N+" text beyond limit
        max_icons = 12
        show_icons = min(total, max_icons)
        overflow = total > max_icons

        for i in range(show_icons):
            icon_label = QLabel()
            icon_label.setFixedSize(16, 16)
            if self._tomato_pixmap:
                icon_label.setPixmap(self._tomato_pixmap)
                icon_label.setScaledContents(True)
            if i >= pomodoro_count:
                # Dimmed for remaining/unfilled slots
                effect = QGraphicsOpacityEffect(icon_label)
                effect.setOpacity(0.3)
                icon_label.setGraphicsEffect(effect)
            # Insert before the trailing stretch
            layout.insertWidget(layout.count() - 1, icon_label)

        if overflow:
            overflow_label = QLabel(f"+{total - max_icons}")
            overflow_label.setStyleSheet("color: gray; font-size: 11px;")
            layout.insertWidget(layout.count() - 1, overflow_label)

        self._item_progress_container.show()

    def update_daily_goal(self, completed: int, goal: int) -> None:
        """Update the daily goal progress display.

        Args:
            completed: Number of completed work sessions today
            goal: Daily goal target (0 = no goal)
        """
        if goal <= 0:
            self._daily_goal_label.hide()
            return
        self._daily_goal_label.setText(f"Today: {completed}/{goal} sessions")
        self._daily_goal_label.show()

    def closeEvent(self, a0) -> None:  # noqa: N802
        """Hide instead of closing so the dialog can be reopened."""
        if a0:
            a0.ignore()
        self.hide()

    def reject(self) -> None:
        """Hide on Escape key instead of closing."""
        self.hide()
