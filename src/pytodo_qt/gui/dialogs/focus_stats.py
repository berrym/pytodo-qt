"""focus_stats.py

Focus Statistics dialog showing summary cards, weekly bar chart, top tasks,
and streak tracking.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
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
    from ...core.models import Database, FocusSession

_TIME_BLOCKS: list[tuple[int, str]] = [
    (0, "12 – 2 AM"),
    (2, "2 – 4 AM"),
    (4, "4 – 6 AM"),
    (6, "6 – 8 AM"),
    (8, "8 – 10 AM"),
    (10, "10 AM – 12 PM"),
    (12, "12 – 2 PM"),
    (14, "2 – 4 PM"),
    (16, "4 – 6 PM"),
    (18, "6 – 8 PM"),
    (20, "8 – 10 PM"),
    (22, "10 PM – 12 AM"),
]


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

        insights_group = self._build_insights_section()
        if insights_group is not None:
            layout.addWidget(insights_group)

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
        """Compute current streak of consecutive days with completed work sessions."""
        return self._storage.compute_current_streak(self._config.daily_goal)

    # ------------------------------------------------------------------
    # Interruption Insights
    # ------------------------------------------------------------------

    def _get_work_sessions(self) -> list[FocusSession]:
        """Return all work sessions from storage."""
        all_sessions = self._storage.get_all_focus_sessions()
        return [s for s in all_sessions if s.session_type == "work"]

    def _build_insights_section(self) -> QGroupBox | None:
        """Build the Insights group box. Returns None if no work sessions exist."""
        work = self._get_work_sessions()
        if not work:
            return None

        group = QGroupBox("Insights")
        group_layout = QVBoxLayout(group)

        def _add(text: str) -> None:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            group_layout.addWidget(lbl)

        # --- Always-visible insights ---

        # Completion rate (always show)
        completed = sum(1 for s in work if s.completed)
        total = len(work)
        pct = round(completed / total * 100)
        interrupted = total - completed
        if interrupted > 0:
            _add(f"Completion rate: {pct}% ({interrupted}/{total} sessions interrupted)")
        else:
            _add(f"Completion rate: {pct}% ({total} sessions, none interrupted)")

        # Average session duration (always show)
        avg_dur = sum(s.duration_seconds for s in work) / total
        _add(f"Average session duration: {_format_duration(round(avg_dur))}")

        # Most active time block (needs 2+ sessions in any block)
        active = self._compute_most_active_time(work)
        if active:
            _add(active)

        # --- Conditional insights (need enough data) ---

        best = self._compute_best_focus_time(work)
        if best:
            _add(best)

        worst = self._compute_worst_focus_time(work)
        if worst:
            _add(worst)

        trend = self._compute_completion_rate_trend(work)
        if trend:
            _add(trend)

        most_interrupted = self._compute_most_interrupted_tasks(work)
        if most_interrupted:
            _add("<b>Most interrupted tasks:</b>")
            for i, (name, item_total, item_completed, _rate) in enumerate(most_interrupted, 1):
                _add(f"  {i}. {name} \u2014 {item_completed}/{item_total} completed")

        duration_cmp = self._compute_interruption_duration_comparison(work)
        if duration_cmp:
            _add(duration_cmp)

        return group

    def _compute_most_active_time(self, work_sessions: list[FocusSession]) -> str | None:
        """Find the 2-hour block with the most sessions (min 2)."""
        blocks: dict[int, int] = defaultdict(int)
        for s in work_sessions:
            try:
                hour = datetime.fromisoformat(s.start_time).hour
            except (ValueError, TypeError):
                continue
            blocks[(hour // 2) * 2] += 1

        if not blocks:
            return None

        best_block = max(blocks, key=lambda k: blocks[k])
        count = blocks[best_block]
        if count < 2:
            return None

        label = dict(_TIME_BLOCKS).get(best_block, f"{best_block}:00")
        return f"Most active time: {label} ({count} sessions)"

    def _compute_interruption_rate(self, work_sessions: list[FocusSession]) -> str | None:
        """Overall interruption rate across all work sessions."""
        total = len(work_sessions)
        if total == 0:
            return None
        interrupted = sum(1 for s in work_sessions if not s.completed)
        if interrupted == 0:
            return None
        pct = round(interrupted / total * 100)
        return f"Interruption rate: {pct}% ({interrupted}/{total} sessions interrupted)"

    def _compute_best_focus_time(self, work_sessions: list[FocusSession]) -> str | None:
        """Find the 2-hour block with the highest completion rate (min 3 sessions)."""
        blocks: dict[int, list[bool]] = defaultdict(list)
        for s in work_sessions:
            try:
                hour = datetime.fromisoformat(s.start_time).hour
            except (ValueError, TypeError):
                continue
            block_key = (hour // 2) * 2
            blocks[block_key].append(s.completed)

        best_rate = -1.0
        best_block: int | None = None
        best_total = 0
        for block_key, outcomes in blocks.items():
            if len(outcomes) < 3:
                continue
            rate = sum(outcomes) / len(outcomes)
            if rate > best_rate or (rate == best_rate and len(outcomes) > best_total):
                best_rate = rate
                best_block = block_key
                best_total = len(outcomes)

        if best_block is None:
            return None

        label = dict(_TIME_BLOCKS).get(best_block, f"{best_block}:00")
        pct = round(best_rate * 100)
        return f"Best focus time: {label} ({pct}% completion, {best_total} sessions)"

    def _compute_worst_focus_time(self, work_sessions: list[FocusSession]) -> str | None:
        """Find the 2-hour block with the lowest completion rate (min 3 sessions)."""
        blocks: dict[int, list[bool]] = defaultdict(list)
        for s in work_sessions:
            try:
                hour = datetime.fromisoformat(s.start_time).hour
            except (ValueError, TypeError):
                continue
            block_key = (hour // 2) * 2
            blocks[block_key].append(s.completed)

        worst_rate = 2.0
        worst_block: int | None = None
        worst_total = 0
        for block_key, outcomes in blocks.items():
            if len(outcomes) < 3:
                continue
            rate = sum(outcomes) / len(outcomes)
            if rate >= 1.0:
                continue  # Skip blocks with no interruptions
            if rate < worst_rate or (rate == worst_rate and len(outcomes) > worst_total):
                worst_rate = rate
                worst_block = block_key
                worst_total = len(outcomes)

        if worst_block is None:
            return None

        label = dict(_TIME_BLOCKS).get(worst_block, f"{worst_block}:00")
        pct = round(worst_rate * 100)
        return f"Worst focus time: {label} ({pct}% completion, {worst_total} sessions)"

    def _compute_completion_rate_trend(self, work_sessions: list[FocusSession]) -> str | None:
        """Compare this week's vs last week's completion rate (min 2 per week)."""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        last_week_start = week_start - timedelta(days=7)

        this_week: list[bool] = []
        last_week: list[bool] = []
        for s in work_sessions:
            try:
                d = date.fromisoformat(s.date)
            except (ValueError, TypeError):
                continue
            if week_start <= d <= today:
                this_week.append(s.completed)
            elif last_week_start <= d < week_start:
                last_week.append(s.completed)

        if len(this_week) < 2 or len(last_week) < 2:
            return None

        this_pct = round(sum(this_week) / len(this_week) * 100)
        last_pct = round(sum(last_week) / len(last_week) * 100)
        delta = this_pct - last_pct

        if abs(delta) < 3:
            avg = round((this_pct + last_pct) / 2)
            return f"Completion rate: steady at {avg}%"
        arrow = "\u2191" if delta > 0 else "\u2193"
        return f"{arrow} Completion rate: {this_pct}% this week vs {last_pct}% last week"

    def _compute_most_interrupted_tasks(
        self,
        work_sessions: list[FocusSession],
    ) -> list[tuple[str, int, int, float]] | None:
        """Find tasks with the lowest completion rate (min 2 sessions, <100%).

        Returns list of (name, total, completed, rate), top 3 by lowest rate.
        """
        by_item: dict[str, list[bool]] = defaultdict(list)
        for s in work_sessions:
            by_item[str(s.item_id)].append(s.completed)

        candidates: list[tuple[str, int, int, float]] = []
        for item_id_str, outcomes in by_item.items():
            if len(outcomes) < 2:
                continue
            completed = sum(outcomes)
            rate = completed / len(outcomes)
            if rate >= 1.0:
                continue
            name = self._resolve_item_name(item_id_str)
            candidates.append((name, len(outcomes), completed, rate))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[3], -x[1]))
        return candidates[:3]

    def _compute_interruption_duration_comparison(
        self,
        work_sessions: list[FocusSession],
    ) -> str | None:
        """Compare avg duration of interrupted vs completed sessions."""
        completed_durations: list[int] = []
        interrupted_durations: list[int] = []
        for s in work_sessions:
            if s.completed:
                completed_durations.append(s.duration_seconds)
            else:
                interrupted_durations.append(s.duration_seconds)

        if len(completed_durations) < 2 or len(interrupted_durations) < 2:
            return None

        avg_completed = sum(completed_durations) / len(completed_durations)
        avg_interrupted = sum(interrupted_durations) / len(interrupted_durations)

        completed_min = round(avg_completed / 60)
        interrupted_min = round(avg_interrupted / 60)

        if avg_completed > 0 and avg_interrupted < avg_completed * 0.5:
            timing = "early"
        else:
            timing = "near the end"

        return (
            f"Interrupted sessions avg {interrupted_min}m vs completed "
            f"{completed_min}m \u2014 most interruptions happen {timing}"
        )
