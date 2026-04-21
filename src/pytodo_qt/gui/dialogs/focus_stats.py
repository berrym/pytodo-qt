"""focus_stats.py

Focus Statistics dialog showing summary cards, weekly bar chart, top tasks,
and streak tracking. Data powered by AnalyticsService (pandas DataFrames).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, cast

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
    """pyqtgraph horizontal bar chart of daily session counts.

    Uses gradient brushes, 1px pen outlines, persistent items.
    Static chart — no real-time updates needed.
    """

    def __init__(self, day_counts: list[tuple[str, int]], parent: QWidget | None = None):
        super().__init__(parent)
        import numpy as np
        import pyqtgraph as pg
        from PyQt6.QtGui import QBrush, QGradient, QLinearGradient, QPen

        from ...gui.styles.themes import get_colors

        c = get_colors()

        # --- Pre-create styles ---
        bar_base = QColor(c.get("chart_pomodoro", "#D55E00"))
        grad = QLinearGradient(0, 0, 1, 0)  # horizontal: left→right
        grad.setCoordinateMode(QGradient.CoordinateMode.ObjectMode)
        grad.setColorAt(0.0, bar_base)
        grad.setColorAt(1.0, bar_base.lighter(115))
        bar_brush = QBrush(grad)
        bar_pen = QPen(bar_base.darker(130), 1)
        col_text = QColor(c.get("text", "#e0e0e0"))
        col_border = QColor(c.get("border", "#3c3c3c"))

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        plot = pg.PlotWidget()
        plot.setBackground(c.get("base", "#252526"))
        plot.setMouseEnabled(x=False, y=False)
        plot.setMenuEnabled(False)
        plot.showGrid(x=True, y=False, alpha=0.2)
        plot.setFixedHeight(len(day_counts) * 32 + 20)

        labels = [label for label, _ in day_counts]
        counts = np.array([count for _, count in day_counts], dtype=float)
        n = len(day_counts)
        y_pos = np.arange(n - 1, -1, -1, dtype=float)

        # --- Persistent bar item ---
        bar_item = pg.BarGraphItem(
            x0=np.zeros(n),
            y0=y_pos - 0.3,
            width=counts,
            height=0.6,
            brush=bar_brush,
            pen=bar_pen,
        )
        plot.addItem(bar_item)

        # --- Persistent text labels ---
        for i in range(n):
            if counts[i] > 0:
                text = pg.TextItem(str(int(counts[i])), color=col_text, anchor=(0, 0.5))
                text.setPos(float(counts[i]) + 0.1, float(y_pos[i]))
                plot.addItem(text)

        # --- Axes ---
        left_axis = plot.getAxis("left")
        left_axis.setTicks([[(float(y_pos[i]), labels[i]) for i in range(n)]])
        left_axis.setTextPen(col_text)
        left_axis.setPen(pg.mkPen(col_border))
        left_axis.setWidth(40)

        bottom_axis = plot.getAxis("bottom")
        bottom_axis.setTextPen(col_text)
        bottom_axis.setPen(pg.mkPen(col_border))

        max_count = float(counts.max()) if n > 0 else 1.0
        plot.setXRange(0, max(max_count * 1.2, 1), padding=0)  # type: ignore[call-arg]
        plot.setYRange(-0.5, n - 0.5, padding=0.05)  # type: ignore[call-arg]

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

        self.setWindowTitle(self.tr("Focus Statistics"))
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
            int(cast(float, today_summary["completed_sessions"].sum()))
            if not today_summary.empty
            else 0
        )
        today_minutes = (
            float(cast(float, today_summary["total_minutes"].sum()))
            if not today_summary.empty
            else 0.0
        )
        today_duration = int(today_minutes * 60)
        today_card = self._create_card(self.tr("Today"), today_sessions, today_duration)
        if self._config.daily_goal > 0:
            goal_label = QLabel(self.tr(f"Goal: {today_sessions}/{self._config.daily_goal}"))
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
            int(cast(float, week_summary["completed_sessions"].sum()))
            if not week_summary.empty
            else 0
        )
        week_minutes = (
            float(cast(float, week_summary["total_minutes"].sum()))
            if not week_summary.empty
            else 0.0
        )
        cards_layout.addWidget(
            self._create_card(self.tr("This Week"), week_sessions, int(week_minutes * 60))
        )

        # This Month card
        month_start = today.replace(day=1)
        month_summary = self._analytics.daily_summary(
            start_date=month_start.isoformat(), end_date=today_str
        )
        month_sessions = (
            int(cast(float, month_summary["completed_sessions"].sum()))
            if not month_summary.empty
            else 0
        )
        month_minutes = (
            float(cast(float, month_summary["total_minutes"].sum()))
            if not month_summary.empty
            else 0.0
        )
        cards_layout.addWidget(
            self._create_card(self.tr("This Month"), month_sessions, int(month_minutes * 60))
        )

        layout.addLayout(cards_layout)

        # Weekly bar chart
        chart_group = QGroupBox(self.tr("This Week"))
        chart_layout_box = QVBoxLayout(chart_group)
        weekly = self._analytics.weekly_chart(week_start)
        day_counts = [
            (cast(str, row["day_name"])[:3], int(cast(int, row["session_count"])))
            for _, row in weekly.iterrows()
        ]
        chart = WeeklyChartWidget(day_counts)
        chart_layout_box.addWidget(chart)
        layout.addWidget(chart_group)

        # Top tasks this week
        top = self._analytics.top_items(week_start.isoformat(), today_str, limit=5)
        if not top.empty:
            tasks_group = QGroupBox(self.tr("Top Tasks This Week"))
            tasks_layout = QVBoxLayout(tasks_group)
            for i, (_, row) in enumerate(top.iterrows(), 1):
                name = self._resolve_item_name(cast(str, row["item_id"]))
                count = int(cast(int, row["session_count"]))
                duration = int(cast(float, row["total_minutes"]) * 60)
                label = QLabel(f"{i}. {name} \u2014 {count} ({_format_duration(duration)})")
                label.setWordWrap(True)
                tasks_layout.addWidget(label)
            layout.addWidget(tasks_group)

        # Streak
        streak = self._analytics.streak(
            self._config.daily_goal if self._config.daily_goal > 0 else 1
        )
        streak_label = QLabel(self.tr(f"Current Streak: {streak} day{'s' if streak != 1 else ''}"))
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

        sessions_label = QLabel(self.tr(f"{sessions} session{'s' if sessions != 1 else ''}"))
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
            return self.tr("(unknown)")

        for todo_list in self._database.lists.values():
            item = todo_list.get_item(item_id)
            if item is not None:
                return item.reminder or self.tr("(untitled)")
        return self.tr("(deleted)")

    # ------------------------------------------------------------------
    # Insights — powered by AnalyticsService DataFrames
    # ------------------------------------------------------------------

    def _build_insights_section(self) -> QGroupBox | None:
        """Build the Insights group box. Returns None if no work sessions exist."""
        import pandas as pd

        all_sessions = self._analytics.sessions()
        work = cast(
            pd.DataFrame,
            all_sessions[
                (all_sessions["session_type"] == "work")
                | (all_sessions["session_type"] == "stopwatch")
            ],
        )
        if work.empty:
            return None

        group = QGroupBox(self.tr("Insights"))
        group_layout = QVBoxLayout(group)

        def _add(text: str) -> None:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            group_layout.addWidget(lbl)

        # Completion rate
        completed = int(cast(float, work["completed"].sum()))
        total = len(work)
        pct = round(completed / total * 100) if total > 0 else 0
        interrupted = total - completed
        if interrupted > 0:
            _add(self.tr(f"Completion rate: {pct}% ({interrupted}/{total} sessions interrupted)"))
        else:
            _add(self.tr(f"Completion rate: {pct}% ({total} sessions, none interrupted)"))

        # Average session duration
        avg_dur = float(cast(float, work["duration_seconds"].mean()))
        _add(self.tr(f"Average session duration: {_format_duration(round(avg_dur))}"))

        # Time block analysis
        blocks = self._analytics.time_block_analysis()
        active_blocks = cast(pd.DataFrame, blocks[blocks["session_count"] >= 2])
        if not active_blocks.empty:
            most_active = active_blocks.loc[
                cast(pd.Series, active_blocks["session_count"]).idxmax()
            ]
            _add(
                self.tr(
                    f"Most active time: {most_active['block_label']} "
                    f"({int(cast(int, most_active['session_count']))} sessions)"
                )
            )

        # Best focus time (highest completion rate, min 3 sessions)
        qualified = cast(pd.DataFrame, blocks[blocks["session_count"] >= 3])
        if not qualified.empty:
            best = qualified.loc[cast(pd.Series, qualified["completion_rate"]).idxmax()]
            if cast(float, best["completion_rate"]) > 0:
                _add(
                    self.tr(
                        f"Best focus time: {best['block_label']} "
                        f"({round(cast(float, best['completion_rate']) * 100)}% completion, "
                        f"{int(cast(int, best['session_count']))} sessions)"
                    )
                )

            # Worst focus time (lowest completion rate < 100%, min 3 sessions)
            imperfect = cast(pd.DataFrame, qualified[qualified["completion_rate"] < 1.0])
            if not imperfect.empty:
                worst = imperfect.loc[cast(pd.Series, imperfect["completion_rate"]).idxmin()]
                _add(
                    self.tr(
                        f"Worst focus time: {worst['block_label']} "
                        f"({round(cast(float, worst['completion_rate']) * 100)}% completion, "
                        f"{int(cast(int, worst['session_count']))} sessions)"
                    )
                )

        # Completion rate trend (this week vs last week)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        last_week_start = week_start - timedelta(days=7)

        this_week = work[work["date"] >= str(week_start)]
        last_week = work[(work["date"] >= str(last_week_start)) & (work["date"] < str(week_start))]

        if len(this_week) >= 2 and len(last_week) >= 2:
            this_pct = round(cast(float, this_week["completed"].mean()) * 100)
            last_pct = round(cast(float, last_week["completed"].mean()) * 100)
            delta = this_pct - last_pct
            if abs(delta) < 3:
                avg = round((this_pct + last_pct) / 2)
                _add(self.tr(f"Completion rate: steady at {avg}%"))
            else:
                arrow = "\u2191" if delta > 0 else "\u2193"
                _add(
                    self.tr(
                        f"{arrow} Completion rate: {this_pct}% this week vs {last_pct}% last week"
                    )
                )

        # Most interrupted tasks
        item_summary = self._analytics.item_summary()
        if not item_summary.empty:
            # Items with 2+ sessions and < 100% completion
            candidates = cast(
                pd.DataFrame,
                item_summary[
                    (item_summary["work_sessions"] + item_summary["stopwatch_sessions"] >= 2)
                    & (item_summary["completion_rate"] < 1.0)
                ],
            ).sort_values("completion_rate")

            if not candidates.empty:
                _add(self.tr("<b>Most interrupted tasks:</b>"))
                for _, row in candidates.head(3).iterrows():
                    name = self._resolve_item_name(cast(str, row["item_id"]))
                    item_total = int(
                        cast(int, row["work_sessions"]) + cast(int, row["stopwatch_sessions"])
                    )
                    item_completed = int(cast(int, row["completed_sessions"]))
                    _add(self.tr(f"  \u2022 {name} \u2014 {item_completed}/{item_total} completed"))

        # Interruption duration comparison
        completed_work = work[work["completed"]]
        interrupted_work = work[~work["completed"]]
        if len(completed_work) >= 2 and len(interrupted_work) >= 2:
            avg_c = float(cast(float, completed_work["duration_seconds"].mean()))
            avg_i = float(cast(float, interrupted_work["duration_seconds"].mean()))
            c_min = round(avg_c / 60)
            i_min = round(avg_i / 60)
            timing = "early" if avg_c > 0 and avg_i < avg_c * 0.5 else "near the end"
            _add(
                self.tr(
                    f"Interrupted sessions avg {i_min}m vs completed "
                    f"{c_min}m \u2014 most interruptions happen {timing}"
                )
            )

        # Longest streak
        daily_goal = self._config.daily_goal
        goal = daily_goal if daily_goal > 0 else 1
        longest = self._analytics.longest_streak(goal)
        current = self._analytics.streak(goal)
        if longest > 0:
            _add(self.tr(f"Streak: {current} day(s) current, {longest} day(s) longest ever"))

        # Overdue rate
        od_rate = self._analytics.overdue_rate()
        if od_rate > 0:
            _add(self.tr(f"Overdue rate: {round(od_rate * 100)}% of due items are past deadline"))

        # Improvement suggestions
        suggestions = self._analytics.improvement_suggestions(daily_goal)
        if suggestions:
            _add(self.tr("<b>Suggestions:</b>"))
            for s in suggestions:
                _add(f"  \u2022 {s}")

        return group
