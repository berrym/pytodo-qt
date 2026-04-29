"""focus_timer.py

Floating always-on-top focus timer window.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
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

_TOMATO_EMOJI = "\U0001f345"


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
        self.setWindowTitle(self.tr("Focus Timer"))
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(300)
        self._sessions_expanded = False
        self._session_total_count = 0
        self._mode = "pomodoro"  # "pomodoro" or "stopwatch"
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

        # Item name — elided to 2 lines with tooltip for full text
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

        # Streak display
        self._streak_label = QLabel()
        self._streak_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._streak_label.setStyleSheet("color: gray;")
        self._streak_label.hide()
        layout.addWidget(self._streak_label)

        # Focus score display
        self._focus_score_label = QLabel()
        self._focus_score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._focus_score_label.setStyleSheet("color: gray;")
        self._focus_score_label.hide()
        layout.addWidget(self._focus_score_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._pause_btn = QPushButton(self.tr("\u23f8 Pause"))
        self._pause_btn.setMinimumWidth(80)
        self._pause_btn.clicked.connect(self.pause_requested.emit)
        btn_layout.addWidget(self._pause_btn)

        self._stop_btn = QPushButton(self.tr("\u25a0 Stop"))
        self._stop_btn.setMinimumWidth(80)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        btn_layout.addWidget(self._stop_btn)

        self._skip_btn = QPushButton(self.tr("\u23ed Skip"))
        self._skip_btn.setMinimumWidth(80)
        self._skip_btn.clicked.connect(self.skip_break_requested.emit)
        self._skip_btn.setVisible(False)
        btn_layout.addWidget(self._skip_btn)

        layout.addLayout(btn_layout)

        # Today's Sessions — compact stats + collapsible recent list
        self._sessions_toggle = QPushButton(self.tr("\u25b6 Today's Sessions"))
        self._sessions_toggle.setFlat(True)
        self._sessions_toggle.setStyleSheet("text-align: left; color: gray;")
        self._sessions_toggle.clicked.connect(self._toggle_sessions)
        layout.addWidget(self._sessions_toggle)

        self._sessions_container = QWidget()
        sessions_outer = QVBoxLayout(self._sessions_container)
        sessions_outer.setContentsMargins(4, 0, 4, 0)
        sessions_outer.setSpacing(4)

        # Stats summary row
        self._stats_label = QLabel()
        self._stats_label.setStyleSheet("color: gray; font-size: 11px;")
        self._stats_label.setWordWrap(True)
        sessions_outer.addWidget(self._stats_label)

        # Recent sessions (capped at 5 most recent)
        self._recent_container = QWidget()
        self._recent_layout = QVBoxLayout(self._recent_container)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(2)
        sessions_outer.addWidget(self._recent_container)

        self._sessions_container.setVisible(False)
        layout.addWidget(self._sessions_container)

    def _toggle_sessions(self) -> None:
        """Toggle the sessions section visibility."""
        self._sessions_expanded = not self._sessions_expanded
        self._sessions_container.setVisible(self._sessions_expanded)
        arrow = "\u25bc" if self._sessions_expanded else "\u25b6"
        self._sessions_toggle.setText(
            self.tr(f"{arrow} Today's Sessions ({self._session_total_count})")
        )
        self.adjustSize()

    def set_mode(self, mode: str) -> None:
        """Set the dialog mode: 'pomodoro' or 'stopwatch'.

        In stopwatch mode, hides progress bar, skip button, session counter,
        and tomato progress. Shows elapsed time counting up.
        """
        self._mode = mode
        is_stopwatch = mode == "stopwatch"
        self.setWindowTitle(self.tr("Stopwatch") if is_stopwatch else self.tr("Focus Timer"))
        self.setAccessibleName(self.tr("Stopwatch") if is_stopwatch else self.tr("Focus Timer"))
        self._progress_bar.setVisible(not is_stopwatch)
        self._session_label.setVisible(not is_stopwatch)
        self._skip_btn.setVisible(False)
        self._item_progress_container.setVisible(not is_stopwatch)
        self._daily_goal_label.setVisible(False)
        self._streak_label.setVisible(False)
        self._focus_score_label.setVisible(False)

    def update_stopwatch_display(
        self,
        state: str,
        elapsed: int,
        item_name: str,
        estimated_minutes: int = 0,
    ) -> None:
        """Update display for stopwatch mode.

        Args:
            state: "stopwatch_running", "stopwatch_paused", or "idle"
            elapsed: Elapsed seconds
            item_name: Name of the tracked item
            estimated_minutes: Estimated minutes (0 = no estimate)
        """
        if state == "idle":
            self.hide()
            return

        # Time display — count up, HH:MM:SS for 1h+
        h, remainder = divmod(max(0, elapsed), 3600)
        m, s = divmod(remainder, 60)
        if h > 0:
            self._time_label.setText(f"{h}:{m:02d}:{s:02d}")
        else:
            self._time_label.setText(f"{m:02d}:{s:02d}")

        # Color
        if state == "stopwatch_running":
            self._time_label.setStyleSheet("color: #3498DB;")
        elif state == "stopwatch_paused":
            self._time_label.setStyleSheet("color: #F39C12;")

        # Progress bar — show if estimate exists
        if estimated_minutes > 0:
            total_seconds = estimated_minutes * 60
            self._progress_bar.setMaximum(total_seconds)
            self._progress_bar.setValue(min(elapsed, total_seconds))
            self._progress_bar.setVisible(True)
            elapsed_m = elapsed // 60
            self._session_label.setText(self.tr(f"{elapsed_m} of {estimated_minutes} min"))
            self._session_label.setVisible(True)
        else:
            self._progress_bar.setVisible(False)
            self._session_label.setVisible(False)

        # Item name
        display_name = self._elide_item_name(item_name)
        self._item_label.setText(display_name)
        self._item_label.setToolTip(item_name if display_name != item_name else "")

        # Pause button text
        if state == "stopwatch_paused":
            self._pause_btn.setText(self.tr("\u25b6 Resume"))
        else:
            self._pause_btn.setText(self.tr("\u23f8 Pause"))

        self._pause_btn.setEnabled(True)
        self._skip_btn.setVisible(False)

    def update_sessions(self, sessions: list[dict[str, Any]]) -> None:
        """Update the Today's Sessions display.

        Args:
            sessions: List of dicts with keys: start_time, end_time,
                      duration_seconds, completed, session_type
        """
        self._session_total_count = len(sessions)

        # Compute stats
        completed = [s for s in sessions if s.get("completed", False)]
        incomplete = [s for s in sessions if not s.get("completed", False)]
        durations = [
            s.get("duration_seconds", 0) for s in sessions if s.get("duration_seconds", 0) > 0
        ]

        total_time = sum(durations)
        total_m, total_s = divmod(total_time, 60)
        total_h, total_m = divmod(total_m, 60)

        stats_parts = [
            self.tr(f"Total: {len(sessions)}"),
            f"\u2713 {len(completed)}",
            f"\u2717 {len(incomplete)}",
        ]
        if total_h > 0:
            stats_parts.append(self.tr(f"Time: {total_h}h {total_m:02d}m"))
        elif total_time > 0:
            stats_parts.append(self.tr(f"Time: {total_m}m {total_s:02d}s"))

        if durations:
            longest = max(durations)
            shortest = min(durations)
            lm, ls = divmod(longest, 60)
            sm, ss = divmod(shortest, 60)
            if len(durations) > 1:
                stats_parts.append(self.tr(f"Longest: {lm:02d}:{ls:02d}"))
                stats_parts.append(self.tr(f"Shortest: {sm:02d}:{ss:02d}"))

        self._stats_label.setText("  \u2022  ".join(stats_parts))

        # Clear recent sessions
        while self._recent_layout.count():
            item = self._recent_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        # Show most recent 5 sessions
        max_recent = 5
        recent = sessions[-max_recent:]
        start_index = max(1, len(sessions) - max_recent + 1)
        for i, s in enumerate(recent, start_index):
            label = self._format_session_label(i, s)
            self._recent_layout.addWidget(label)

        if len(sessions) > max_recent:
            more = QLabel(self.tr(f"... and {len(sessions) - max_recent} earlier"))
            more.setStyleSheet("color: gray; font-size: 10px; font-style: italic;")
            # Insert at top
            self._recent_layout.insertWidget(0, more)

        # Update toggle button text
        arrow = "\u25bc" if self._sessions_expanded else "\u25b6"
        self._sessions_toggle.setText(self.tr(f"{arrow} Today's Sessions ({len(sessions)})"))

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

        text = self.tr(f"Session {index}: {m:02d}:{s:02d} {mark}{time_range}")
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

        # Item name — elide to ~2 lines, tooltip for full text
        display_name = self._elide_item_name(item_name)
        self._item_label.setText(display_name)
        self._item_label.setToolTip(item_name if display_name != item_name else "")

        # Session counter — use item estimate when available, else cycle position
        if item_estimated > 0:
            current = item_pomodoro_count + (1 if state in ("working", "paused") else 0)
            self._session_label.setText(self.tr(f"Session {current}/{item_estimated}"))
        else:
            current = session_count + (1 if state in ("working", "paused") else 0)
            self._session_label.setText(self.tr(f"Session {current} of {total_sessions}"))

        # Pause button text
        if state == "paused":
            self._pause_btn.setText(self.tr("\u25b6 Resume"))
        else:
            self._pause_btn.setText(self.tr("\u23f8 Pause"))

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
            icon_label = QLabel(_TOMATO_EMOJI)
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
        self._daily_goal_label.setText(self.tr(f"Today: {completed}/{goal} sessions"))
        self._daily_goal_label.show()

    def update_streak(self, streak: int) -> None:
        """Update the streak display.

        Args:
            streak: Current consecutive days with focus sessions
        """
        if streak <= 0:
            self._streak_label.hide()
            return
        self._streak_label.setText(self.tr(f"Streak: {streak} day{'s' if streak != 1 else ''}"))
        self._streak_label.show()

    def update_focus_score(self, score: int) -> None:
        """Update the focus score display.

        Args:
            score: Focus score 0-100
        """
        if score < 0:
            self._focus_score_label.hide()
            return
        if score >= 90:
            grade = "A"
        elif score >= 75:
            grade = "B"
        elif score >= 60:
            grade = "C"
        elif score >= 40:
            grade = "D"
        else:
            grade = "F"
        self._focus_score_label.setText(self.tr(f"Score: {grade} ({score})"))
        self._focus_score_label.show()

    def _elide_item_name(self, name: str, max_lines: int = 2) -> str:
        """Truncate name to fit within max_lines, adding ellipsis if needed."""
        fm = self._item_label.fontMetrics()
        available_width = max(self.minimumWidth() - 48, 200)  # margins
        lines: list[str] = []
        remaining = name

        for line_num in range(max_lines):
            if not remaining:
                break
            if line_num == max_lines - 1:
                # Last allowed line — elide the rest
                elided = fm.elidedText(remaining, Qt.TextElideMode.ElideRight, available_width)
                lines.append(elided)
            else:
                # Find how much fits on this line
                fit_len = len(remaining)
                for i in range(1, len(remaining) + 1):
                    if fm.horizontalAdvance(remaining[:i]) > available_width:
                        fit_len = i - 1
                        break
                if fit_len >= len(remaining):
                    lines.append(remaining)
                    remaining = ""
                else:
                    # Break at last space for readability
                    break_at = remaining.rfind(" ", 0, fit_len + 1)
                    if break_at > 0:
                        lines.append(remaining[:break_at])
                        remaining = remaining[break_at + 1 :]
                    else:
                        lines.append(remaining[:fit_len])
                        remaining = remaining[fit_len:]

        return "\n".join(lines)

    def closeEvent(self, a0) -> None:  # noqa: N802
        """Hide instead of closing so the dialog can be reopened."""
        if a0:
            a0.ignore()
        self.hide()

    def reject(self) -> None:
        """Hide on Escape key instead of closing."""
        self.hide()
