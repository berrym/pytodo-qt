"""focus_stats.py

Focus Statistics dialog showing summary cards, weekly bar chart, top tasks,
and streak tracking.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from ...core.config import PomodoroConfig
    from ...core.database import DatabaseStorage
    from ...core.models import Database


class WeeklyChartWidget(QWidget):
    """Custom widget that draws a horizontal bar chart of daily session counts."""

    def __init__(self, day_counts: list[tuple[str, int]], parent: QWidget | None = None):
        """Initialize the chart.

        Args:
            day_counts: List of (day_label, count) tuples for 7 days (Mon-Sun).
            parent: Parent widget.
        """
        super().__init__(parent)
        self._day_counts = day_counts
        self._max_count = max((c for _, c in day_counts), default=1) or 1
        self.setMinimumHeight(len(day_counts) * 28 + 16)

    def paintEvent(self, a0) -> None:  # noqa: N802
        """Draw the horizontal bar chart."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        bar_height = 20
        row_height = 28
        label_width = 40
        count_width = 40
        bar_area = w - label_width - count_width - 16
        y = 8

        bar_color = QColor("#4A90D9")
        text_color = self.palette().text().color()
        painter.setPen(QPen(text_color))

        font = QFont()
        font.setPointSize(11)
        painter.setFont(font)

        for label, count in self._day_counts:
            # Day label
            painter.drawText(0, y, label_width, bar_height, Qt.AlignmentFlag.AlignVCenter, label)

            # Bar
            if count > 0 and bar_area > 0:
                bar_width = max(4, int(bar_area * count / self._max_count))
                painter.fillRect(label_width, y + 2, bar_width, bar_height - 4, bar_color)

            # Count
            painter.drawText(
                label_width + bar_area + 4,
                y,
                count_width,
                bar_height,
                Qt.AlignmentFlag.AlignVCenter,
                str(count),
            )

            y += row_height

        painter.end()


def _format_duration(seconds: int) -> str:
    """Format seconds as 'Xh Ym'."""
    h, remainder = divmod(seconds, 3600)
    m = remainder // 60
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


class FocusStatsDialog(QDialog):
    """Dialog showing focus session statistics with summary cards,
    weekly bar chart, top tasks, and streak tracking."""

    def __init__(
        self,
        database: Database,
        storage: DatabaseStorage,
        config: PomodoroConfig,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._database = database
        self._storage = storage
        self._config = config

        self.setWindowTitle("Focus Statistics")
        self.setMinimumWidth(450)
        self.setMinimumHeight(500)

        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(16)

        # Summary cards
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(8)

        today = date.today()
        today_str = today.isoformat()

        # Today card
        today_sessions = self._count_work_sessions(today_str, today_str)
        today_duration = self._sum_work_duration(today_str, today_str)
        today_card = self._create_card("Today", today_sessions, today_duration)
        # Add daily goal to today card if set
        if self._config.daily_goal > 0:
            goal_label = QLabel(f"Goal: {today_sessions}/{self._config.daily_goal}")
            goal_label.setStyleSheet("color: gray;")
            goal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout = today_card.layout()
            if card_layout:
                card_layout.addWidget(goal_label)
        cards_layout.addWidget(today_card)

        # This Week card
        week_start = today - timedelta(days=today.weekday())
        week_sessions = self._count_work_sessions(week_start.isoformat(), today_str)
        week_duration = self._sum_work_duration(week_start.isoformat(), today_str)
        cards_layout.addWidget(self._create_card("This Week", week_sessions, week_duration))

        # This Month card
        month_start = today.replace(day=1)
        month_sessions = self._count_work_sessions(month_start.isoformat(), today_str)
        month_duration = self._sum_work_duration(month_start.isoformat(), today_str)
        cards_layout.addWidget(self._create_card("This Month", month_sessions, month_duration))

        layout.addLayout(cards_layout)

        # Weekly bar chart
        chart_group = QGroupBox("This Week")
        chart_layout = QVBoxLayout(chart_group)
        day_counts = self._compute_week_counts(week_start)
        chart = WeeklyChartWidget(day_counts)
        chart_layout.addWidget(chart)
        layout.addWidget(chart_group)

        # Top tasks this week
        top_tasks = self._compute_top_tasks(week_start.isoformat(), today_str, limit=5)
        if top_tasks:
            tasks_group = QGroupBox("Top Tasks This Week")
            tasks_layout = QVBoxLayout(tasks_group)
            for i, (name, count, duration) in enumerate(top_tasks, 1):
                label = QLabel(f"{i}. {name} \u2014 {count} ({_format_duration(duration)})")
                label.setWordWrap(True)
                tasks_layout.addWidget(label)
            layout.addWidget(tasks_group)

        # Streak
        streak = self._compute_streak()
        streak_label = QLabel(f"Current Streak: {streak} day{'s' if streak != 1 else ''}")
        streak_font = QFont()
        streak_font.setPointSize(13)
        streak_font.setBold(True)
        streak_label.setFont(streak_font)
        streak_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(streak_label)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        outer.addWidget(button_box)

    def _create_card(self, title: str, sessions: int, duration: int) -> QGroupBox:
        """Create a summary card group box."""
        card = QGroupBox(title)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(4)

        sessions_label = QLabel(f"{sessions} session{'s' if sessions != 1 else ''}")
        sessions_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        sessions_label.setFont(font)
        card_layout.addWidget(sessions_label)

        duration_label = QLabel(_format_duration(duration))
        duration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        duration_label.setStyleSheet("color: gray;")
        card_layout.addWidget(duration_label)

        return card

    def _count_work_sessions(self, start_date: str, end_date: str) -> int:
        """Count completed work sessions in a date range."""
        sessions = self._storage.get_sessions_for_date_range(start_date, end_date)
        return sum(1 for s in sessions if s.session_type == "work" and s.completed)

    def _sum_work_duration(self, start_date: str, end_date: str) -> int:
        """Sum duration of completed work sessions in a date range."""
        sessions = self._storage.get_sessions_for_date_range(start_date, end_date)
        return sum(s.duration_seconds for s in sessions if s.session_type == "work" and s.completed)

    def _compute_week_counts(self, week_start: date) -> list[tuple[str, int]]:
        """Compute per-day session counts for the week."""
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        counts: list[tuple[str, int]] = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            count = self._storage.get_work_session_count_for_date(d.isoformat())
            counts.append((day_names[i], count))
        return counts

    def _compute_top_tasks(
        self, start_date: str, end_date: str, limit: int = 5
    ) -> list[tuple[str, int, int]]:
        """Get top tasks by session count in a date range.

        Returns list of (task_name, session_count, total_duration).
        """
        sessions = self._storage.get_sessions_for_date_range(start_date, end_date)
        work_sessions = [s for s in sessions if s.session_type == "work" and s.completed]

        # Group by item_id
        by_item: dict[str, list[int]] = defaultdict(list)
        for s in work_sessions:
            by_item[str(s.item_id)].append(s.duration_seconds)

        # Sort by count descending
        sorted_items = sorted(by_item.items(), key=lambda x: len(x[1]), reverse=True)

        result: list[tuple[str, int, int]] = []
        for item_id_str, durations in sorted_items[:limit]:
            # Look up item name from database
            name = self._resolve_item_name(item_id_str)
            result.append((name, len(durations), sum(durations)))
        return result

    def _resolve_item_name(self, item_id_str: str) -> str:
        """Look up an item's reminder text by ID."""
        from uuid import UUID

        try:
            item_id = UUID(item_id_str)
        except ValueError:
            return "(unknown)"

        for todo_list in self._database.lists.values():
            item = todo_list.get_item(item_id)
            if item is not None:
                return item.reminder or "(untitled)"
        return "(deleted)"

    def _compute_streak(self) -> int:
        """Compute current streak of consecutive days with completed work sessions.

        If daily_goal > 0, a day counts only if sessions >= daily_goal.
        Otherwise, any day with >= 1 completed work session counts.
        """
        streak = 0
        current = date.today()
        goal = self._config.daily_goal

        while True:
            count = self._storage.get_work_session_count_for_date(current.isoformat())
            threshold = goal if goal > 0 else 1
            if count >= threshold:
                streak += 1
                current -= timedelta(days=1)
            else:
                break
        return streak
