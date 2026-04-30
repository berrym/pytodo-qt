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
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..styles.themes import get_colors

_TOMATO_EMOJI = "\U0001f345"


def _format_duration(seconds: int) -> str:
    """Format a duration in seconds as a human-readable string.

    Picks the most readable unit based on magnitude:
      < 1 minute  → "Ns"
      < 1 hour    → "MmSSs" (e.g. "12m 03s")
      otherwise   → "HhMMm" (e.g. "2h 30m")
    """
    if seconds < 60:
        return f"{seconds}s"
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


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

        # Focus score display — score text plus a small info icon
        # that surfaces the formula on hover (compact tooltip) or
        # click (richer popover). Without this affordance "Score: D"
        # is meaningless to a first-time user — they have no way to
        # know what's being measured or how to improve it.
        self._focus_score_container = QWidget()
        _fs_layout = QHBoxLayout(self._focus_score_container)
        _fs_layout.setContentsMargins(0, 0, 0, 0)
        _fs_layout.setSpacing(4)
        _fs_layout.addStretch()
        self._focus_score_label = QLabel()
        self._focus_score_label.setStyleSheet("color: gray;")
        _fs_layout.addWidget(self._focus_score_label)
        self._focus_score_info_btn = QPushButton("ⓘ")  # circled-i glyph
        self._focus_score_info_btn.setFlat(True)
        self._focus_score_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._focus_score_info_btn.setFixedWidth(20)
        self._focus_score_info_btn.setStyleSheet(
            "QPushButton { color: gray; font-size: 14px; border: none;"
            " padding: 0; background: transparent; }"
            "QPushButton:hover { color: palette(highlight); }"
        )
        self._focus_score_info_btn.setToolTip(
            self.tr("What's this? Click for the full explanation.")
        )
        self._focus_score_info_btn.clicked.connect(self._show_focus_score_explanation)
        _fs_layout.addWidget(self._focus_score_info_btn)
        _fs_layout.addStretch()
        self._focus_score_container.hide()
        layout.addWidget(self._focus_score_container)

        # Stopwatch-specific stats — parallel to the pomodoro
        # daily-goal / streak / focus-score widgets but populated from
        # session_type="stopwatch" data only. Hidden in pomodoro mode.

        # Total stopwatch time tracked on the active item across all
        # sessions (parallel to the per-item pomodoro tomato row).
        self._item_tracked_label = QLabel()
        self._item_tracked_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._item_tracked_label.setStyleSheet("color: gray;")
        self._item_tracked_label.hide()
        layout.addWidget(self._item_tracked_label)

        # Total stopwatch time tracked today across all items
        # (parallel to the daily pomodoro goal).
        self._daily_tracked_label = QLabel()
        self._daily_tracked_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._daily_tracked_label.setStyleSheet("color: gray;")
        self._daily_tracked_label.hide()
        layout.addWidget(self._daily_tracked_label)

        # Consecutive days with at least one stopwatch session
        # (parallel to the pomodoro streak).
        self._tracking_streak_label = QLabel()
        self._tracking_streak_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tracking_streak_label.setStyleSheet("color: gray;")
        self._tracking_streak_label.hide()
        layout.addWidget(self._tracking_streak_label)

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
        # Muted text for the resting state; :hover / :pressed / :focus
        # switch to highlight_text on the highlight band so the label
        # stays legible when the focus rectangle or press tint lands on
        # it (the inline `color: gray` this replaces went unreadable on
        # the blue band).
        _toggle_colors = get_colors()
        self._sessions_toggle = QPushButton(self.tr("\u25b6 Today's Sessions"))
        self._sessions_toggle.setFlat(True)
        self._sessions_toggle.setStyleSheet(
            "QPushButton {"
            f" text-align: left; color: {_toggle_colors['completed_text']};"
            " border: none; background: transparent; padding: 4px 0px;"
            "}"
            "QPushButton:hover {"
            f" color: {_toggle_colors['text']};"
            "}"
            "QPushButton:pressed, QPushButton:focus {"
            f" color: {_toggle_colors['highlight_text']};"
            f" background: {_toggle_colors['highlight']};"
            " border-radius: 4px;"
            "}"
        )
        self._sessions_toggle.clicked.connect(self._toggle_sessions)
        layout.addWidget(self._sessions_toggle)

        self._sessions_container = QWidget()
        sessions_outer = QVBoxLayout(self._sessions_container)
        sessions_outer.setContentsMargins(4, 0, 4, 0)
        sessions_outer.setSpacing(4)

        # Stats summary row
        self._stats_label = QLabel()
        self._stats_label.setStyleSheet(
            f"color: {_toggle_colors['completed_text']}; font-size: 11px;"
        )
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
        self._refresh_sessions_toggle_text()
        self.adjustSize()

    def _refresh_sessions_toggle_text(self) -> None:
        """Update the toggle button label using the right phrasing
        for the current mode. Pomodoro shows "Today's Sessions";
        stopwatch shows "Today's Tracking" \u2014 distinct labels make it
        clear the dropdown reflects this mode's data, not the other.
        """
        arrow = "\u25bc" if self._sessions_expanded else "\u25b6"
        if self._mode == "stopwatch":
            self._sessions_toggle.setText(
                self.tr(f"{arrow} Today's Tracking ({self._session_total_count})")
            )
        else:
            self._sessions_toggle.setText(
                self.tr(f"{arrow} Today's Sessions ({self._session_total_count})")
            )

    def set_mode(self, mode: str) -> None:
        """Set the dialog mode: 'pomodoro' or 'stopwatch'.

        Toggles visibility of the mode-specific subset of widgets so
        each mode shows only stats that make sense for it. The two
        modes share the layout shape (countdown + progress bar +
        item name + collapsible Today's panel) but render distinct
        data underneath: pomodoro shows session counter / tomato row /
        daily goal / streak / focus score; stopwatch shows total
        tracked on this item / daily total tracked / tracking streak.
        Pomodoro session-history and stopwatch session-history never
        mix \u2014 the two are filtered by `session_type` upstream.
        """
        self._mode = mode
        is_stopwatch = mode == "stopwatch"
        self.setWindowTitle(self.tr("Stopwatch") if is_stopwatch else self.tr("Focus Timer"))
        self.setAccessibleName(self.tr("Stopwatch") if is_stopwatch else self.tr("Focus Timer"))
        # Pomodoro-only widgets
        self._progress_bar.setVisible(not is_stopwatch)
        self._session_label.setVisible(not is_stopwatch)
        self._skip_btn.setVisible(False)
        self._item_progress_container.setVisible(not is_stopwatch)
        self._daily_goal_label.setVisible(False)
        self._streak_label.setVisible(False)
        # Hide the focus-score *container* (which holds the label and
        # the info icon together). Hiding only the label leaves the
        # icon visible alone and persists across update_focus_score
        # calls because the label's own setVisible(False) sticks.
        self._focus_score_container.setVisible(False)
        # Stopwatch-only widgets \u2014 hidden when entering pomodoro mode,
        # shown empty initially when entering stopwatch mode (the
        # main_window callers populate them with real values via the
        # update_stopwatch_* methods below).
        self._item_tracked_label.setVisible(False)
        self._daily_tracked_label.setVisible(False)
        self._tracking_streak_label.setVisible(False)
        # Reset the session counter and toggle label so a mode switch
        # never leaves stale text from the previous mode.
        self._session_total_count = 0
        self._refresh_sessions_toggle_text()

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

        # Color — sourced from the canonical theme palette so light /
        # dark themes each render the timer in their tuned variant.
        colors = get_colors()
        if state == "stopwatch_running":
            self._time_label.setStyleSheet(f"color: {colors['focus_timer_stopwatch_running']};")
        elif state == "stopwatch_paused":
            self._time_label.setStyleSheet(f"color: {colors['focus_timer_paused']};")

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

    # ------------------------------------------------------------------
    # Stopwatch-mode stats — populate the stopwatch-specific labels
    # and the "Today's Tracking" dropdown. Pomodoro has its own
    # update_daily_goal / update_streak / update_focus_score / update_sessions
    # methods; the stopwatch equivalents below carry exclusively
    # stopwatch (`session_type == "stopwatch"`) data.
    # ------------------------------------------------------------------

    def update_stopwatch_item_total(self, seconds: int) -> None:
        """Show total stopwatch time tracked on the active item across
        all sessions. Hidden when zero so a fresh item doesn't display
        "0m" and clutter the dialog."""
        if seconds <= 0:
            self._item_tracked_label.setVisible(False)
            return
        self._item_tracked_label.setText(
            self.tr(f"Tracked on this item: {_format_duration(seconds)}")
        )
        self._item_tracked_label.setVisible(True)

    def update_stopwatch_daily_total(self, seconds: int) -> None:
        """Show total stopwatch time tracked today across all items.
        Hidden when zero."""
        if seconds <= 0:
            self._daily_tracked_label.setVisible(False)
            return
        self._daily_tracked_label.setText(self.tr(f"Today's tracked: {_format_duration(seconds)}"))
        self._daily_tracked_label.setVisible(True)

    def update_stopwatch_streak(self, days: int) -> None:
        """Show consecutive days with at least one stopwatch session.
        Hidden when streak is 0 or 1 — a one-day streak is just "today,"
        not yet a streak worth surfacing."""
        if days < 2:
            self._tracking_streak_label.setVisible(False)
            return
        self._tracking_streak_label.setText(self.tr(f"\U0001f525 {days}-day tracking streak"))
        self._tracking_streak_label.setVisible(True)

    def update_stopwatch_sessions(self, sessions: list[dict[str, Any]]) -> None:
        """Populate the "Today's Tracking" dropdown with stopwatch
        sessions. Mirrors `update_sessions` but uses stopwatch
        terminology and includes the item name on each row, since
        for stopwatch sessions the item being tracked is more
        identifying than a sequence number."""
        self._session_total_count = len(sessions)

        durations = [
            s.get("duration_seconds", 0) for s in sessions if s.get("duration_seconds", 0) > 0
        ]
        total_time = sum(durations)
        unique_items = {s.get("item_name", "") for s in sessions if s.get("item_name")}

        stats_parts = [self.tr(f"Sessions: {len(sessions)}")]
        if total_time > 0:
            stats_parts.append(self.tr(f"Time: {_format_duration(total_time)}"))
        if durations and len(durations) > 1:
            longest = max(durations)
            shortest = min(durations)
            stats_parts.append(self.tr(f"Longest: {_format_duration(longest)}"))
            stats_parts.append(self.tr(f"Shortest: {_format_duration(shortest)}"))
        if unique_items:
            stats_parts.append(self.tr(f"Items: {len(unique_items)}"))

        self._stats_label.setText("  •  ".join(stats_parts))

        # Clear recent sessions
        while self._recent_layout.count():
            item = self._recent_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        # Show most recent 5 sessions, item name first
        max_recent = 5
        recent = sessions[-max_recent:]
        for s in recent:
            label = self._format_stopwatch_session_label(s)
            self._recent_layout.addWidget(label)

        if len(sessions) > max_recent:
            more = QLabel(self.tr(f"... and {len(sessions) - max_recent} earlier"))
            more.setStyleSheet("color: gray; font-size: 10px; font-style: italic;")
            self._recent_layout.insertWidget(0, more)

        # Update toggle button text via the mode-aware helper.
        self._refresh_sessions_toggle_text()

        if self._sessions_expanded:
            self.adjustSize()

    def _format_stopwatch_session_label(self, session: dict[str, Any]) -> QLabel:
        """Stopwatch session row: item name + duration + time range."""
        duration = session.get("duration_seconds", 0)
        item_name = session.get("item_name", "") or self.tr("(unknown item)")
        # Elide the item name so a long task title doesn't blow out
        # the dropdown's compact layout.
        if len(item_name) > 28:
            item_name = item_name[:27] + "…"
        time_range = ""
        try:
            from datetime import datetime

            start_dt = datetime.fromisoformat(session.get("start_time", ""))
            end_dt = datetime.fromisoformat(session.get("end_time", ""))
            time_range = f"  ({start_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')})"
        except (ValueError, TypeError):
            pass

        text = f"{item_name}: {_format_duration(duration)}{time_range}"
        label = QLabel(text)
        label.setStyleSheet("color: gray; font-size: 11px;")
        label.setFrameShape(QFrame.Shape.NoFrame)
        return label

    def update_sessions(self, sessions: list[dict[str, Any]]) -> None:
        """Update the Today's Sessions display.

        Args:
            sessions: List of dicts with keys: start_time, end_time,
                      duration_seconds, completed, session_type
        """
        # Pomodoro-mode dropdown only. Stopwatch mode populates the
        # same toggle/container via update_stopwatch_sessions and uses
        # different stat formatting; ignoring this call in stopwatch
        # mode prevents pomodoro-format text from clobbering it on a
        # background tick.
        if self._mode == "stopwatch":
            return
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

        # Update toggle button text via the mode-aware helper so a
        # mode switch never leaves stale "Today's Sessions" text under
        # stopwatch mode (or vice-versa).
        self._refresh_sessions_toggle_text()

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

        # Color based on state — theme-aware via the canonical palette.
        colors = get_colors()
        if state == "working":
            self._time_label.setStyleSheet(f"color: {colors['focus_timer_working']};")
        elif state == "break":
            self._time_label.setStyleSheet(f"color: {colors['focus_timer_break']};")
        elif state == "paused":
            self._time_label.setStyleSheet(f"color: {colors['focus_timer_paused']};")

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

    def update_item_progress(self, pomodoro_count: int, estimated: int = 0) -> None:
        """Show one tomato emoji per completed pomodoro session.

        Capped at 12 icons; beyond that, a `+N` overflow label fills
        in for the rest. Hidden until the item has at least one
        completed pomodoro — there's nothing to show until then, and
        an empty row is just visual noise.

        The `estimated` parameter is accepted for backward compatibility
        with existing callers but is not used: pending / not-yet-done
        slots are deliberately not rendered. The simpler "completed
        sessions only" model avoids the cross-platform emoji-opacity
        problem (macOS renders emoji as colored bitmaps that don't
        respond to QGraphicsOpacityEffect) and reads more cleanly —
        each tomato that appears means a session was actually done.
        """
        # Stopwatch mode never shows the tomato row — its per-item
        # equivalent is the item-tracked label populated separately.
        if self._mode == "stopwatch" or pomodoro_count <= 0:
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

        max_icons = 12
        show_icons = min(pomodoro_count, max_icons)
        overflow = pomodoro_count > max_icons

        for _ in range(show_icons):
            icon_label = QLabel(_TOMATO_EMOJI)
            # Insert before the trailing stretch
            layout.insertWidget(layout.count() - 1, icon_label)

        if overflow:
            overflow_label = QLabel(f"+{pomodoro_count - max_icons}")
            overflow_label.setStyleSheet("color: gray; font-size: 11px;")
            layout.insertWidget(layout.count() - 1, overflow_label)

        self._item_progress_container.show()

    def update_daily_goal(self, completed: int, goal: int) -> None:
        """Update the daily goal progress display.

        Args:
            completed: Number of completed work sessions today
            goal: Daily goal target (0 = no goal)
        """
        # Pomodoro-only stat — never visible in stopwatch mode, even
        # when callers update unconditionally on a tick.
        if self._mode == "stopwatch" or goal <= 0:
            self._daily_goal_label.hide()
            return
        self._daily_goal_label.setText(self.tr(f"Today: {completed}/{goal} sessions"))
        self._daily_goal_label.show()

    def update_streak(self, streak: int) -> None:
        """Update the streak display.

        Args:
            streak: Current consecutive days with focus sessions
        """
        # Pomodoro streak is gated on daily goal; stopwatch has its
        # own tracking_streak label populated by update_stopwatch_streak.
        if self._mode == "stopwatch" or streak <= 0:
            self._streak_label.hide()
            return
        self._streak_label.setText(self.tr(f"Streak: {streak} day{'s' if streak != 1 else ''}"))
        self._streak_label.show()

    def update_focus_score(self, score: int) -> None:
        """Update the focus score display.

        Args:
            score: Focus score 0-100
        """
        # Focus score is a pomodoro-completion metric — N/A in
        # stopwatch mode (stopwatch sessions are open-ended, no
        # completed/incomplete distinction).
        if self._mode == "stopwatch" or score < 0:
            self._focus_score_container.hide()
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
        # Defensive: re-show the inner label in case a prior set_mode
        # hid it directly (older builds did so before the container
        # wrapper was introduced; this keeps the label visible across
        # any mode-toggle sequence).
        self._focus_score_label.setVisible(True)
        self._focus_score_container.show()

    def _show_focus_score_explanation(self) -> None:
        """Display the focus-score formula in a popover anchored to
        the info icon. The explanation matches the implementation in
        `core/analytics.py::focus_score`; if the formula changes,
        keep this text in sync."""
        from PyQt6.QtWidgets import QToolTip

        text = self.tr(
            "<b>Focus Score</b><br/>"
            "A 0–100 measure of today's focus quality, computed from "
            "three components.<br/><br/>"
            "<b>Goal ratio</b> &nbsp;(up to 40 points)<br/>"
            "Your completed sessions today vs. your daily goal. "
            "Hits 40 when you complete the goal; partial progress "
            "scales linearly. With no goal set, each completed session "
            "is worth 10 points up to 40.<br/><br/>"
            "<b>Completion rate</b> &nbsp;(up to 40 points)<br/>"
            "The share of today's sessions you finished without "
            "interrupting them. 40 points if every session was "
            "completed; less if some were stopped early.<br/><br/>"
            "<b>Streak bonus</b> &nbsp;(up to 20 points)<br/>"
            "4 points for each consecutive day with at least one "
            "session, capped at 20 (5 days).<br/><br/>"
            "<b>Grade</b><br/>"
            "A 90+ &nbsp; B 75+ &nbsp; C 60+ &nbsp; D 40+ &nbsp; F below 40"
        )
        # Anchor the popover at the icon's bottom-left so it appears
        # below the label rather than covering it.
        anchor = self._focus_score_info_btn.mapToGlobal(
            self._focus_score_info_btn.rect().bottomLeft()
        )
        QToolTip.showText(anchor, text, self._focus_score_info_btn)

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
