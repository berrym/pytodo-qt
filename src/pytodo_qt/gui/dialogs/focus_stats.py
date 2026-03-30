"""focus_stats.py

Focus Statistics dialog showing summary cards, weekly bar chart, top tasks,
and streak tracking. Data powered by AnalyticsService (pandas DataFrames).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
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
    from ...core.analytics import AnalyticsService
    from ...core.config import PomodoroConfig
    from ...core.models import Database


class WeeklyChartWidget(QWidget):
    """pyqtgraph horizontal bar chart of daily session counts."""

    def __init__(self, day_counts: list[tuple[str, int]], parent: QWidget | None = None):
        """Initialize the chart.

        Args:
            day_counts: List of (day_label, count) tuples for 7 days (Mon-Sun).
            parent: Parent widget.
        """
        super().__init__(parent)
        import numpy as np
        import pyqtgraph as pg

        from ...gui.styles.themes import get_colors

        c = get_colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        plot = pg.PlotWidget()
        plot.setBackground(c.get("base", "#252526"))
        plot.setMouseEnabled(x=False, y=False)
        plot.setMenuEnabled(False)
        plot.showGrid(x=True, y=False, alpha=0.2)
        plot.setFixedHeight(len(day_counts) * 32 + 20)

        labels = [label for label, _ in day_counts]
        counts = [count for _, count in day_counts]
        n = len(day_counts)

        # Y positions (inverted so Mon is at top)
        y_pos = np.arange(n - 1, -1, -1, dtype=float)

        # Bar color from theme
        bar_color = QColor(c.get("chart_pomodoro", "#D55E00"))
        bar_color.setAlpha(200)

        bar_item = pg.BarGraphItem(
            x0=np.zeros(n),
            y0=y_pos - 0.3,
            width=np.array(counts, dtype=float),
            height=0.6,
            brush=pg.mkBrush(bar_color),
            pen=pg.mkPen(None),
        )
        plot.addItem(bar_item)

        # Add count labels as text items
        col_text = QColor(c.get("text", "#e0e0e0"))
        for i, count in enumerate(counts):
            if count > 0:
                text = pg.TextItem(str(count), color=col_text, anchor=(0, 0.5))
                text.setPos(count + 0.1, y_pos[i])
                plot.addItem(text)

        # Configure axes
        left_axis = plot.getAxis("left")
        left_axis.setTicks([[(y_pos[i], labels[i]) for i in range(n)]])
        left_axis.setTextPen(col_text)
        left_axis.setPen(pg.mkPen(QColor(c.get("border", "#3c3c3c"))))
        left_axis.setWidth(40)

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(col_text)
        bottom_axis.setPen(pg.mkPen(QColor(c.get("border", "#3c3c3c"))))

        max_count = max(counts) if counts else 1
        plot.setXRange(0, max(max_count * 1.2, 1), padding=0)
        plot.setYRange(-0.5, n - 0.5, padding=0.05)

        layout.addWidget(plot)


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
        analytics: AnalyticsService,
        database: Database,
        config: PomodoroConfig,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._analytics = analytics
        self._database = database
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
        today_summary = self._analytics.daily_summary(start_date=today_str, end_date=today_str)
        today_sessions = (
            int(today_summary["completed_sessions"].sum()) if not today_summary.empty else 0
        )
        today_minutes = (
            float(today_summary["total_minutes"].sum()) if not today_summary.empty else 0.0
        )
        today_duration = int(today_minutes * 60)
        today_card = self._create_card("Today", today_sessions, today_duration)
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
        week_summary = self._analytics.daily_summary(
            start_date=week_start.isoformat(), end_date=today_str
        )
        week_sessions = (
            int(week_summary["completed_sessions"].sum()) if not week_summary.empty else 0
        )
        week_minutes = float(week_summary["total_minutes"].sum()) if not week_summary.empty else 0.0
        cards_layout.addWidget(
            self._create_card("This Week", week_sessions, int(week_minutes * 60))
        )

        # This Month card
        month_start = today.replace(day=1)
        month_summary = self._analytics.daily_summary(
            start_date=month_start.isoformat(), end_date=today_str
        )
        month_sessions = (
            int(month_summary["completed_sessions"].sum()) if not month_summary.empty else 0
        )
        month_minutes = (
            float(month_summary["total_minutes"].sum()) if not month_summary.empty else 0.0
        )
        cards_layout.addWidget(
            self._create_card("This Month", month_sessions, int(month_minutes * 60))
        )

        layout.addLayout(cards_layout)

        # Weekly bar chart
        chart_group = QGroupBox("This Week")
        chart_layout_box = QVBoxLayout(chart_group)
        weekly = self._analytics.weekly_chart(week_start)
        day_counts = [
            (row["day_name"][:3], int(row["session_count"])) for _, row in weekly.iterrows()
        ]
        chart = WeeklyChartWidget(day_counts)
        chart_layout_box.addWidget(chart)
        layout.addWidget(chart_group)

        # Top tasks this week
        top = self._analytics.top_items(week_start.isoformat(), today_str, limit=5)
        if not top.empty:
            tasks_group = QGroupBox("Top Tasks This Week")
            tasks_layout = QVBoxLayout(tasks_group)
            for i, (_, row) in enumerate(top.iterrows(), 1):
                name = self._resolve_item_name(row["item_id"])
                count = int(row["session_count"])
                duration = int(row["total_minutes"] * 60)
                label = QLabel(f"{i}. {name} \u2014 {count} ({_format_duration(duration)})")
                label.setWordWrap(True)
                tasks_layout.addWidget(label)
            layout.addWidget(tasks_group)

        # Streak
        streak = self._analytics.streak(
            self._config.daily_goal if self._config.daily_goal > 0 else 1
        )
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

    # ------------------------------------------------------------------
    # Insights — powered by AnalyticsService DataFrames
    # ------------------------------------------------------------------

    def _build_insights_section(self) -> QGroupBox | None:
        """Build the Insights group box. Returns None if no work sessions exist."""
        all_sessions = self._analytics.sessions()
        work = all_sessions[
            (all_sessions["session_type"] == "work") | (all_sessions["session_type"] == "stopwatch")
        ]
        if work.empty:
            return None

        group = QGroupBox("Insights")
        group_layout = QVBoxLayout(group)

        def _add(text: str) -> None:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            group_layout.addWidget(lbl)

        # Completion rate
        completed = int(work["completed"].sum())
        total = len(work)
        pct = round(completed / total * 100) if total > 0 else 0
        interrupted = total - completed
        if interrupted > 0:
            _add(f"Completion rate: {pct}% ({interrupted}/{total} sessions interrupted)")
        else:
            _add(f"Completion rate: {pct}% ({total} sessions, none interrupted)")

        # Average session duration
        avg_dur = float(work["duration_seconds"].mean())
        _add(f"Average session duration: {_format_duration(round(avg_dur))}")

        # Time block analysis
        blocks = self._analytics.time_block_analysis()
        active_blocks = blocks[blocks["session_count"] >= 2]
        if not active_blocks.empty:
            most_active = active_blocks.loc[active_blocks["session_count"].idxmax()]
            _add(
                f"Most active time: {most_active['block_label']} "
                f"({int(most_active['session_count'])} sessions)"
            )

        # Best focus time (highest completion rate, min 3 sessions)
        qualified = blocks[blocks["session_count"] >= 3]
        if not qualified.empty:
            best = qualified.loc[qualified["completion_rate"].idxmax()]
            if best["completion_rate"] > 0:
                _add(
                    f"Best focus time: {best['block_label']} "
                    f"({round(best['completion_rate'] * 100)}% completion, "
                    f"{int(best['session_count'])} sessions)"
                )

            # Worst focus time (lowest completion rate < 100%, min 3 sessions)
            imperfect = qualified[qualified["completion_rate"] < 1.0]
            if not imperfect.empty:
                worst = imperfect.loc[imperfect["completion_rate"].idxmin()]
                _add(
                    f"Worst focus time: {worst['block_label']} "
                    f"({round(worst['completion_rate'] * 100)}% completion, "
                    f"{int(worst['session_count'])} sessions)"
                )

        # Completion rate trend (this week vs last week)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        last_week_start = week_start - timedelta(days=7)

        this_week = work[work["date"] >= str(week_start)]
        last_week = work[(work["date"] >= str(last_week_start)) & (work["date"] < str(week_start))]

        if len(this_week) >= 2 and len(last_week) >= 2:
            this_pct = round(this_week["completed"].mean() * 100)
            last_pct = round(last_week["completed"].mean() * 100)
            delta = this_pct - last_pct
            if abs(delta) < 3:
                avg = round((this_pct + last_pct) / 2)
                _add(f"Completion rate: steady at {avg}%")
            else:
                arrow = "\u2191" if delta > 0 else "\u2193"
                _add(f"{arrow} Completion rate: {this_pct}% this week vs {last_pct}% last week")

        # Most interrupted tasks
        item_summary = self._analytics.item_summary()
        if not item_summary.empty:
            # Items with 2+ sessions and < 100% completion
            candidates = item_summary[
                (item_summary["work_sessions"] + item_summary["stopwatch_sessions"] >= 2)
                & (item_summary["completion_rate"] < 1.0)
            ].sort_values("completion_rate")

            if not candidates.empty:
                _add("<b>Most interrupted tasks:</b>")
                for _, row in candidates.head(3).iterrows():
                    name = self._resolve_item_name(row["item_id"])
                    item_total = int(row["work_sessions"] + row["stopwatch_sessions"])
                    item_completed = int(row["completed_sessions"])
                    _add(f"  \u2022 {name} \u2014 {item_completed}/{item_total} completed")

        # Interruption duration comparison
        completed_work = work[work["completed"]]
        interrupted_work = work[~work["completed"]]
        if len(completed_work) >= 2 and len(interrupted_work) >= 2:
            avg_c = float(completed_work["duration_seconds"].mean())
            avg_i = float(interrupted_work["duration_seconds"].mean())
            c_min = round(avg_c / 60)
            i_min = round(avg_i / 60)
            timing = "early" if avg_c > 0 and avg_i < avg_c * 0.5 else "near the end"
            _add(
                f"Interrupted sessions avg {i_min}m vs completed "
                f"{c_min}m \u2014 most interruptions happen {timing}"
            )

        return group
