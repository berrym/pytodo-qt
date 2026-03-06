"""focus_timer.py

Floating always-on-top focus timer window.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


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
        self.setFixedWidth(300)
        self._setup_ui()

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

        # Session counter
        self._session_label = QLabel()
        self._session_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._session_label.setStyleSheet("color: gray;")
        layout.addWidget(self._session_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._pause_btn = QPushButton("\u23f8 Pause")
        self._pause_btn.clicked.connect(self.pause_requested.emit)
        btn_layout.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("\u25a0 Stop")
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        btn_layout.addWidget(self._stop_btn)

        self._skip_btn = QPushButton("\u23ed Skip")
        self._skip_btn.clicked.connect(self.skip_break_requested.emit)
        self._skip_btn.setVisible(False)
        btn_layout.addWidget(self._skip_btn)

        layout.addLayout(btn_layout)

    def update_display(
        self,
        state: str,
        remaining: int,
        item_name: str,
        session_count: int,
        total_sessions: int,
        total_duration: int = 0,
    ) -> None:
        """Update all display elements.

        Args:
            state: Timer state ("working", "break", "paused", "idle")
            remaining: Remaining seconds
            item_name: Name of the focused item
            session_count: Completed sessions in current cycle
            total_sessions: Sessions before long break
            total_duration: Total duration of current session in seconds
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

        # Session counter
        current = session_count + (1 if state in ("working", "paused") else 0)
        self._session_label.setText(f"Session {current} of {total_sessions}")

        # Pause button text
        if state == "paused":
            self._pause_btn.setText("\u25b6 Resume")
        else:
            self._pause_btn.setText("\u23f8 Pause")

        # Pause button enabled only during working/paused
        self._pause_btn.setEnabled(state in ("working", "paused"))

        # Skip button visible only during break
        self._skip_btn.setVisible(state == "break")

    def closeEvent(self, a0) -> None:  # noqa: N802
        """Hide instead of closing so the dialog can be reopened."""
        if a0:
            a0.ignore()
        self.hide()

    def reject(self) -> None:
        """Hide on Escape key instead of closing."""
        self.hide()
