"""analytics.py

Pandas-based analytics service for focus sessions and task productivity.

Pure Python + pandas. No Qt dependency. Reads from SQLite via pd.read_sql_query().
All methods return DataFrames or scalar values. Never writes to the database.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import NamedTuple, cast

import pandas as pd

# ---------------------------------------------------------------------------
# Result types for completion-timing analytics (Step 4 of calendar Gantt
# redesign). NamedTuples per feedback-return-type-patterns.md: NamedTuple
# for 3+ field returns.
# ---------------------------------------------------------------------------


class ItemCompletionTiming(NamedTuple):
    """Per-item classification for completion_timing.

    deviation_minutes is signed: negative for early completions, positive
    for late completions, zero for exactly-on-time. UNKNOWN items are not
    included in this list at all (the `unknown_count` on the parent
    result records how many were excluded).
    """

    item_id: str
    classification: str  # "early", "ontime", "late"
    deviation_minutes: int


class CompletionTimingResult(NamedTuple):
    """Result of analyzing completion timing across a date range.

    `items` excludes UNKNOWN-cohort tasks (those completed before
    schema v19 introduced the timestamp). `unknown_count` records
    how many were excluded so the caller can report transparency.
    """

    total: int  # total completed items in range (including unknown)
    early_count: int
    ontime_count: int
    late_count: int
    unknown_count: int
    items: list[ItemCompletionTiming]


class SlipRateResult(NamedTuple):
    """Result of computing slip rate over a date range.

    Slip rate = late_count / (early_count + ontime_count + late_count).
    UNKNOWN cohort is excluded from both numerator and denominator.
    `rate` is None when the denominator is zero (no classifiable items).
    """

    total: int  # total completed items in range (including unknown)
    early_count: int
    ontime_count: int
    late_count: int
    unknown_count: int
    rate: float | None  # None when no classifiable data


class CycleTimeResult(NamedTuple):
    """Result of computing cycle time (created_at → completed_at) stats.

    Operates only on items with both created_at and completed_at known
    (so the UNKNOWN cohort is excluded). All time fields are in minutes.
    Statistics fields are None when no qualifying items exist.
    """

    # Field is named sample_count (not count) to avoid shadowing tuple.count().
    # JSON API keeps the external key "count" for backwards compat.
    sample_count: int
    unknown_count: int  # excluded from stats
    mean_minutes: float | None
    median_minutes: float | None
    p90_minutes: float | None


class AnalyticsService:
    """Analytics data pipeline: SQLite -> pandas DataFrames.

    Provides cached analytical views of focus session and task data
    for consumption by timeline charts, stats dialogs, and UI widgets.
    """

    def __init__(self, connection: sqlite3.Connection, work_duration_minutes: int = 25):
        self._conn = connection
        self._work_duration_minutes = work_duration_minutes
        self._cache: dict[str, tuple[int, pd.DataFrame]] = {}
        self._version: int = 0

    def invalidate(self) -> None:
        """Bump cache version, forcing all cached DataFrames to be rebuilt on next access."""
        self._version += 1

    def set_work_duration(self, minutes: int) -> None:
        """Update the pomodoro work duration used for session-to-minutes conversion."""
        self._work_duration_minutes = minutes
        self.invalidate()

    # --- Cache helpers ---

    def _cache_key(self, method: str, **kwargs) -> str:
        parts = [method]
        for k, v in sorted(kwargs.items()):
            parts.append(f"{k}={v}")
        return ":".join(parts)

    def _get_cached(self, key: str) -> pd.DataFrame | None:
        if key in self._cache:
            cached_version, df = self._cache[key]
            if cached_version == self._version:
                return df
        return None

    def _set_cached(self, key: str, df: pd.DataFrame) -> pd.DataFrame:
        self._cache[key] = (self._version, df)
        return df

    # --- Session-level analytics ---

    def sessions(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        list_id: str | None = None,
        item_id: str | None = None,
        session_type: str | None = None,
    ) -> pd.DataFrame:
        """Base analytical DataFrame: all sessions with computed fields.

        Args:
            start_date: Filter by date >= (YYYY-MM-DD)
            end_date: Filter by date <= (YYYY-MM-DD)
            list_id: Filter by list UUID string
            item_id: Filter by item UUID string
            session_type: Filter by "work", "break", or "stopwatch"

        Returns:
            DataFrame with columns: id, item_id, list_id, start_time, end_time,
            duration_seconds, duration_minutes, completed, session_type, date,
            hour_of_day, day_of_week, day_name, is_work
        """
        key = self._cache_key(
            "sessions",
            start_date=start_date,
            end_date=end_date,
            list_id=list_id,
            item_id=item_id,
            session_type=session_type,
        )
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        # Build query with filters
        conditions = []
        params: list = []

        if start_date is not None:
            conditions.append("date >= ?")
            params.append(start_date)
        if end_date is not None:
            conditions.append("date <= ?")
            params.append(end_date)
        if list_id is not None:
            # SQLite cannot bind UUID objects directly — coerce to string
            conditions.append("list_id = ?")
            params.append(str(list_id))
        if item_id is not None:
            conditions.append("item_id = ?")
            params.append(str(item_id))
        if session_type is not None:
            conditions.append("session_type = ?")
            params.append(session_type)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM focus_sessions{where} ORDER BY start_time"  # noqa: S608

        df = pd.read_sql_query(sql, self._conn, params=params)

        if df.empty:
            # Return empty DataFrame with correct columns
            return self._set_cached(
                key,
                pd.DataFrame(
                    columns=[
                        "id",
                        "item_id",
                        "list_id",
                        "start_time",
                        "end_time",
                        "duration_seconds",
                        "duration_minutes",
                        "completed",
                        "session_type",
                        "date",
                        "hour_of_day",
                        "day_of_week",
                        "day_name",
                        "is_work",
                    ]
                ),
            )

        # Parse and compute columns
        df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
        df["end_time"] = pd.to_datetime(df["end_time"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["duration_seconds"] = df["duration_seconds"].astype("int64")
        df["duration_minutes"] = df["duration_seconds"] / 60.0
        df["completed"] = df["completed"].astype(bool)
        df["hour_of_day"] = df["start_time"].dt.hour.astype("Int64")
        df["day_of_week"] = df["date"].dt.dayofweek.astype("Int64")
        df["day_name"] = df["date"].dt.day_name()
        df["is_work"] = df["session_type"] == "work"

        return self._set_cached(key, df)

    def time_block_analysis(self) -> pd.DataFrame:
        """Session counts, total minutes, and completion rates by 2-hour time blocks.

        Returns:
            DataFrame with 12 rows: block_start_hour, block_label,
            session_count, completed_count, total_minutes,
            completion_rate, avg_duration_minutes
        """
        key = self._cache_key("time_block_analysis")
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        all_sessions = self.sessions()
        work = all_sessions[all_sessions["is_work"] | (all_sessions["session_type"] == "stopwatch")]

        # Build all 12 blocks
        blocks = []
        for hour in range(0, 24, 2):
            label = f"{hour:02d}:00 - {hour + 2:02d}:00"
            mask = (work["hour_of_day"] >= hour) & (work["hour_of_day"] < hour + 2)
            block_data = cast(pd.DataFrame, work[mask])
            count = len(block_data)
            completed = int(cast(float, block_data["completed"].sum())) if count > 0 else 0
            total_mins = (
                float(cast(float, block_data["duration_minutes"].sum())) if count > 0 else 0.0
            )
            pom_data = block_data[block_data["is_work"]] if count > 0 else block_data
            sw_data = (
                block_data[block_data["session_type"] == "stopwatch"] if count > 0 else block_data
            )
            pom_mins = (
                float(cast(float, pom_data["duration_minutes"].sum())) if len(pom_data) > 0 else 0.0
            )
            sw_mins = (
                float(cast(float, sw_data["duration_minutes"].sum())) if len(sw_data) > 0 else 0.0
            )
            rate = completed / count if count > 0 else 0.0
            avg_dur = (
                float(cast(float, block_data["duration_minutes"].mean())) if count > 0 else 0.0
            )
            blocks.append(
                {
                    "block_start_hour": hour,
                    "block_label": label,
                    "session_count": count,
                    "completed_count": completed,
                    "total_minutes": total_mins,
                    "pomodoro_minutes": pom_mins,
                    "stopwatch_minutes": sw_mins,
                    "completion_rate": rate,
                    "avg_duration_minutes": avg_dur,
                }
            )

        return self._set_cached(key, pd.DataFrame(blocks))

    # --- Daily analytics ---

    def daily_summary(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        list_id: str | None = None,
    ) -> pd.DataFrame:
        """Per-day aggregates of focus session activity.

        Returns:
            DataFrame with columns: date, total_sessions, completed_sessions,
            interrupted_sessions, total_minutes, work_minutes, stopwatch_minutes,
            completion_rate
        """
        key = self._cache_key(
            "daily_summary", start_date=start_date, end_date=end_date, list_id=list_id
        )
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        df = self.sessions(start_date=start_date, end_date=end_date, list_id=list_id)

        if df.empty:
            return self._set_cached(
                key,
                pd.DataFrame(
                    columns=[
                        "date",
                        "total_sessions",
                        "completed_sessions",
                        "interrupted_sessions",
                        "total_minutes",
                        "work_minutes",
                        "stopwatch_minutes",
                        "completion_rate",
                    ]
                ),
            )

        # Exclude breaks from summary
        work_and_sw = df[df["session_type"] != "break"]

        if work_and_sw.empty:
            return self._set_cached(
                key,
                pd.DataFrame(
                    columns=[
                        "date",
                        "total_sessions",
                        "completed_sessions",
                        "interrupted_sessions",
                        "total_minutes",
                        "work_minutes",
                        "stopwatch_minutes",
                        "completion_rate",
                    ]
                ),
            )

        grouped = work_and_sw.groupby("date")

        result = pd.DataFrame(
            {
                "date": grouped["date"].first(),
                "total_sessions": grouped.size(),
                "completed_sessions": cast(pd.Series, grouped["completed"].sum()).astype(int),
                "total_minutes": grouped["duration_minutes"].sum(),
            }
        )

        result["interrupted_sessions"] = result["total_sessions"] - result["completed_sessions"]
        result["completion_rate"] = result.apply(
            lambda r: (
                r["completed_sessions"] / r["total_sessions"] if r["total_sessions"] > 0 else 0.0
            ),
            axis=1,
        )

        # Per-type minutes
        work_mins = cast(
            pd.Series,
            cast(pd.DataFrame, work_and_sw[work_and_sw["session_type"] == "work"])
            .groupby("date")["duration_minutes"]
            .sum(),
        )
        sw_mins = cast(
            pd.Series,
            cast(pd.DataFrame, work_and_sw[work_and_sw["session_type"] == "stopwatch"])
            .groupby("date")["duration_minutes"]
            .sum(),
        )
        result["work_minutes"] = work_mins.reindex(result.index, fill_value=0.0)
        result["stopwatch_minutes"] = sw_mins.reindex(result.index, fill_value=0.0)

        result = result.reset_index(drop=True)
        return self._set_cached(key, result)

    def weekly_chart(self, week_start: date) -> pd.DataFrame:
        """7-day breakdown for bar chart visualization.

        Args:
            week_start: Monday of the week to chart.

        Returns:
            DataFrame with 7 rows: date, day_name, session_count, total_minutes
        """
        week_end = week_start + timedelta(days=6)
        start_str = week_start.isoformat()
        end_str = week_end.isoformat()

        key = self._cache_key("weekly_chart", start=start_str)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        df = self.sessions(start_date=start_str, end_date=end_str)
        work_sw = df[(df["session_type"] != "break") & df["completed"]]

        # Build all 7 days
        rows = []
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for i in range(7):
            d = week_start + timedelta(days=i)
            d_ts = pd.Timestamp(d)
            day_data = work_sw[work_sw["date"] == d_ts] if not work_sw.empty else pd.DataFrame()
            rows.append(
                {
                    "date": d,
                    "day_name": day_names[i],
                    "session_count": len(day_data),
                    "total_minutes": float(cast(float, day_data["duration_minutes"].sum()))
                    if len(day_data) > 0
                    else 0.0,
                }
            )

        return self._set_cached(key, pd.DataFrame(rows))

    def rolling_averages(self, *, window_7: bool = True, window_30: bool = True) -> pd.DataFrame:
        """Daily time series with rolling means for trend analysis.

        Returns:
            DataFrame with columns: date, daily_sessions, daily_minutes,
            rolling_7d_sessions, rolling_7d_minutes, [rolling_30d_sessions,
            rolling_30d_minutes]
        """
        key = self._cache_key("rolling_averages", w7=window_7, w30=window_30)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        summary = self.daily_summary()
        if summary.empty:
            cols = ["date", "daily_sessions", "daily_minutes"]
            if window_7:
                cols.extend(["rolling_7d_sessions", "rolling_7d_minutes"])
            if window_30:
                cols.extend(["rolling_30d_sessions", "rolling_30d_minutes"])
            return self._set_cached(key, pd.DataFrame(columns=cols))

        result = pd.DataFrame(
            {
                "date": summary["date"],
                "daily_sessions": summary["completed_sessions"],
                "daily_minutes": summary["total_minutes"],
            }
        )

        if window_7:
            result["rolling_7d_sessions"] = (
                result["daily_sessions"].rolling(7, min_periods=1).mean()
            )
            result["rolling_7d_minutes"] = result["daily_minutes"].rolling(7, min_periods=1).mean()

        if window_30:
            result["rolling_30d_sessions"] = (
                result["daily_sessions"].rolling(30, min_periods=1).mean()
            )
            result["rolling_30d_minutes"] = (
                result["daily_minutes"].rolling(30, min_periods=1).mean()
            )

        return self._set_cached(key, result)

    # --- Item-level analytics ---

    def item_summary(self, list_id: str | None = None) -> pd.DataFrame:
        """Per-item productivity metrics.

        Returns:
            DataFrame with columns: item_id, total_seconds, total_minutes,
            work_sessions, completed_sessions, interrupted_sessions,
            stopwatch_sessions, completion_rate, avg_session_minutes
        """
        key = self._cache_key("item_summary", list_id=list_id)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        df = self.sessions(list_id=list_id)
        work_sw = df[df["session_type"] != "break"]

        if work_sw.empty:
            return self._set_cached(
                key,
                pd.DataFrame(
                    columns=[
                        "item_id",
                        "total_seconds",
                        "total_minutes",
                        "work_sessions",
                        "completed_sessions",
                        "interrupted_sessions",
                        "stopwatch_sessions",
                        "completion_rate",
                        "avg_session_minutes",
                    ]
                ),
            )

        grouped = work_sw.groupby("item_id")

        result = pd.DataFrame(
            {
                "item_id": grouped["item_id"].first(),
                "total_seconds": grouped["duration_seconds"].sum(),
                "total_minutes": grouped["duration_minutes"].sum(),
                "work_sessions": grouped.apply(
                    lambda g: int((g["session_type"] == "work").sum()), include_groups=False
                ),
                "completed_sessions": cast(pd.Series, grouped["completed"].sum()).astype(int),
                "stopwatch_sessions": grouped.apply(
                    lambda g: int((g["session_type"] == "stopwatch").sum()), include_groups=False
                ),
            }
        )

        total = grouped.size()
        result["interrupted_sessions"] = total - result["completed_sessions"]
        result["completion_rate"] = result.apply(
            lambda r: (
                r["completed_sessions"] / (r["completed_sessions"] + r["interrupted_sessions"])
                if (r["completed_sessions"] + r["interrupted_sessions"]) > 0
                else 0.0
            ),
            axis=1,
        )
        result["avg_session_minutes"] = result.apply(
            lambda r: r["total_minutes"] / total[r.name] if total[r.name] > 0 else 0.0,
            axis=1,
        )

        result = result.reset_index(drop=True)
        return self._set_cached(key, result)

    def estimate_accuracy(self, list_id: str | None = None) -> pd.DataFrame:
        """Actual vs estimated effort per item.

        Combines estimated_pomodoros * work_duration + estimated_minutes
        into a unified estimated_minutes value.

        Returns:
            DataFrame with columns: item_id, estimated_minutes, actual_minutes,
            accuracy_ratio, variance_minutes
        """
        key = self._cache_key("estimate_accuracy", list_id=list_id)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        # Read items from DB
        conditions = ["deleted = 0"]
        params: list = []
        if list_id is not None:
            # SQLite cannot bind UUID objects directly — coerce to string
            conditions.append("list_id = ?")
            params.append(str(list_id))

        where = f" WHERE {' AND '.join(conditions)}"
        sql = f"SELECT id, estimated_pomodoros, estimated_minutes, time_spent, work_duration FROM items{where}"  # noqa: S608

        items_df = pd.read_sql_query(sql, self._conn, params=params)

        if items_df.empty:
            return self._set_cached(
                key,
                pd.DataFrame(
                    columns=[
                        "item_id",
                        "estimated_minutes",
                        "actual_minutes",
                        "accuracy_ratio",
                        "variance_minutes",
                    ]
                ),
            )

        # Compute combined estimate — use per-item work_duration if set, else global default
        effective_work = items_df["work_duration"].where(
            items_df["work_duration"] > 0, self._work_duration_minutes
        )
        items_df["estimated_total"] = (
            items_df["estimated_pomodoros"] * effective_work + items_df["estimated_minutes"]
        )
        items_df["actual_minutes"] = items_df["time_spent"] / 60.0

        # Filter to items with at least one estimate
        has_estimate = items_df[items_df["estimated_total"] > 0].copy()

        if has_estimate.empty:
            return self._set_cached(
                key,
                pd.DataFrame(
                    columns=[
                        "item_id",
                        "estimated_minutes",
                        "actual_minutes",
                        "accuracy_ratio",
                        "variance_minutes",
                    ]
                ),
            )

        result = pd.DataFrame(
            {
                "item_id": has_estimate["id"],
                "estimated_minutes": has_estimate["estimated_total"].astype(float),
                "actual_minutes": has_estimate["actual_minutes"],
            }
        )

        result["accuracy_ratio"] = result.apply(
            lambda r: (
                r["actual_minutes"] / r["estimated_minutes"] if r["estimated_minutes"] > 0 else 0.0
            ),
            axis=1,
        )
        result["variance_minutes"] = result["actual_minutes"] - result["estimated_minutes"]
        result = result.reset_index(drop=True)

        return self._set_cached(key, result)

    def top_items(
        self,
        start_date: str,
        end_date: str,
        limit: int = 5,
    ) -> pd.DataFrame:
        """Top items ranked by completed session count within a date range.

        Returns:
            DataFrame with columns: item_id, session_count, total_minutes,
            completed_sessions
        """
        key = self._cache_key("top_items", start=start_date, end=end_date, limit=limit)
        cached = self._get_cached(key)
        if cached is not None:
            return cached

        df = self.sessions(start_date=start_date, end_date=end_date)
        work_sw = df[(df["session_type"] != "break") & df["completed"]]

        if work_sw.empty:
            return self._set_cached(
                key,
                pd.DataFrame(
                    columns=["item_id", "session_count", "total_minutes", "completed_sessions"]
                ),
            )

        grouped = work_sw.groupby("item_id")
        result = pd.DataFrame(
            {
                "item_id": grouped["item_id"].first(),
                "session_count": grouped.size(),
                "total_minutes": grouped["duration_minutes"].sum(),
                "completed_sessions": cast(pd.Series, grouped["completed"].sum()).astype(int),
            }
        )

        result = result.sort_values("session_count", ascending=False).head(limit)
        result = result.reset_index(drop=True)
        return self._set_cached(key, result)

    # --- Scalar metrics ---

    def streak(self, daily_goal: int = 1) -> int:
        """Current consecutive-day streak of meeting the daily goal.

        Args:
            daily_goal: Minimum completed work/stopwatch sessions per day
                        to count as a streak day. Default 1.

        Returns:
            Number of consecutive days (0 if today hasn't met the goal).
        """
        summary = self.daily_summary()
        if summary.empty:
            return 0

        today = date.today()
        streak_count = 0

        # Walk backward from today
        d = today
        while True:
            d_ts = pd.Timestamp(d)
            day_row = summary[summary["date"] == d_ts]

            if day_row.empty:
                completed = 0
            else:
                completed = int(day_row.iloc[0]["completed_sessions"])

            threshold = max(1, daily_goal)
            if completed >= threshold:
                streak_count += 1
                d -= timedelta(days=1)
            else:
                break

        return streak_count

    def focus_score(self, daily_goal: int, today: date | None = None) -> int:
        """Calculate today's focus score (0-100) or -1 if no data.

        Components:
        - Goal ratio (0-40): progress toward daily goal
        - Completion rate (0-40): completed / total sessions
        - Streak bonus (0-20): 4 points per consecutive day

        Args:
            daily_goal: Target sessions per day (0 = no goal)
            today: Date to score (defaults to today)

        Returns:
            -1 if no sessions today, else 0-100
        """
        if today is None:
            today = date.today()

        today_str = today.isoformat()
        df = self.sessions(start_date=today_str, end_date=today_str)
        work_sw = df[df["session_type"] != "break"]

        if work_sw.empty:
            return -1

        completed = int(cast(float, work_sw["completed"].sum()))
        total = len(work_sw)

        # Goal ratio (0-40)
        if daily_goal > 0:
            goal_score = min(40, int(40 * completed / daily_goal))
        else:
            goal_score = min(40, completed * 10)

        # Completion rate (0-40)
        if total > 0:
            rate_score = int(40 * completed / total)
        else:
            rate_score = 0

        # Streak bonus (0-20)
        current_streak = self.streak(daily_goal if daily_goal > 0 else 1)
        streak_score = min(20, current_streak * 4)

        return min(100, goal_score + rate_score + streak_score)

    # --- New v18 analytics methods ---

    def upcoming_digest(self, days: int = 3) -> pd.DataFrame:
        """Return items due within the next N days, sorted by urgency.

        Reads from the items table directly (not focus_sessions).

        Returns DataFrame with columns:
            id, list_id, reminder, priority, due_date, due_time,
            due_time_block, event_date, complete, days_until_due
        """
        cache_key = self._cache_key("upcoming_digest", days=days)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        today = date.today()
        end = today + timedelta(days=days)
        query = """
            SELECT id, list_id, reminder, priority, due_date, due_time,
                   due_time_block, event_date, complete
            FROM items
            WHERE deleted = 0 AND complete = 0
              AND due_date IS NOT NULL AND due_date <= ?
            ORDER BY due_date ASC, priority ASC
        """
        df = pd.read_sql_query(query, self._conn, params=[end.isoformat()])
        if not df.empty:
            df["due_date_parsed"] = pd.to_datetime(df["due_date"])
            df["days_until_due"] = (df["due_date_parsed"] - pd.Timestamp(today)).dt.days
            df = df.drop(columns=["due_date_parsed"])
        else:
            df["days_until_due"] = pd.Series(dtype="int64")

        self._set_cached(cache_key, df)
        return df

    def time_block_distribution(self) -> pd.DataFrame:
        """Distribution of tasks across canonical time blocks.

        Returns DataFrame with columns:
            time_block, task_count, completed_count, completion_rate
        """
        cache_key = self._cache_key("time_block_distribution")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        query = """
            SELECT due_time_block, complete
            FROM items
            WHERE deleted = 0 AND due_time_block IS NOT NULL
        """
        df = pd.read_sql_query(query, self._conn)
        if df.empty:
            result = pd.DataFrame(
                columns=["time_block", "task_count", "completed_count", "completion_rate"]
            )
            self._set_cached(cache_key, result)
            return result

        grouped = (
            df.groupby("due_time_block")
            .agg(
                task_count=("complete", "count"),
                completed_count=("complete", "sum"),
            )
            .reset_index()
        )
        grouped = grouped.rename(columns={"due_time_block": "time_block"})
        grouped["completion_rate"] = (grouped["completed_count"] / grouped["task_count"]).fillna(
            0.0
        )

        self._set_cached(cache_key, grouped)
        return grouped

    def scheduling_accuracy(self, list_id: str | None = None) -> pd.DataFrame:
        """For tasks with event_date: were they completed by the event date?

        Returns DataFrame with columns:
            id, reminder, due_date, event_date, complete, completed_at,
            on_time, timestamp_source

        `timestamp_source` is one of:
            "completed_at"     — used the real schema v19 timestamp
            "updated_at"       — fallback for pre-v19 completions where
                                 completed_at is NULL but complete=1
            "incomplete"       — task is not complete

        `on_time` is True when the task was completed at or before the
        end of its event_date day. UNKNOWN-cohort tasks (complete=1 but
        completed_at IS NULL) fall back to using `updated_at` as an
        approximation, with timestamp_source recording the fallback so
        callers can filter to the accurate cohort if desired.
        """
        cache_key = self._cache_key("scheduling_accuracy", list_id=list_id or "all")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        where = "WHERE deleted = 0 AND event_date IS NOT NULL"
        params: list[str] = []
        if list_id:
            # SQLite cannot bind UUID objects directly — coerce to string
            where += " AND list_id = ?"
            params.append(str(list_id))

        query = f"""
            SELECT id, reminder, due_date, event_date, complete, completed_at, updated_at
            FROM items {where}
        """  # noqa: S608
        df = pd.read_sql_query(query, self._conn, params=params or None)
        if df.empty:
            df["on_time"] = pd.Series(dtype="bool")
            df["timestamp_source"] = pd.Series(dtype="object")
            self._set_cached(cache_key, df)
            return df

        # Determine the timestamp source per row
        def _classify_source(row: pd.Series) -> str:
            if not bool(row["complete"]):
                return "incomplete"
            if bool(pd.notna(row["completed_at"])):
                return "completed_at"
            return "updated_at"

        df["timestamp_source"] = df.apply(_classify_source, axis=1)

        # On-time check: completion timestamp is at or before end-of-event-date.
        # For incomplete tasks, on_time is False.
        def _on_time(row: pd.Series) -> bool:
            if not bool(row["complete"]):
                return False
            event_date_str = cast(str, row["event_date"])
            if not event_date_str:
                # No event_date should not happen given the WHERE filter,
                # but defend anyway.
                return True
            event_d = date.fromisoformat(event_date_str)
            # End-of-day cutoff: a task completed on the event date
            # (any time of day) is on-time. The cutoff is the next day's
            # midnight.
            cutoff_ms = (
                cast(pd.Timestamp, pd.Timestamp(event_d + timedelta(days=1))).timestamp() * 1000
            )
            completed = row["completed_at"]
            ts = completed if bool(pd.notna(completed)) else row["updated_at"]
            return float(cast(float, ts)) < cutoff_ms

        df["on_time"] = df.apply(_on_time, axis=1)

        self._set_cached(cache_key, df)
        return df

    # ------------------------------------------------------------------
    # Completion-timing analytics — Step 4 of calendar Gantt redesign.
    # These methods depend on completed_at (schema v19+). UNKNOWN-cohort
    # items (complete=1 but completed_at IS NULL) are excluded from the
    # classification cohort and reported via the result's unknown_count
    # field for transparency.
    # ------------------------------------------------------------------

    def _query_completed_items(
        self,
        list_id: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> pd.DataFrame:
        """Shared query: completed items with due_date in the given range.

        Returns columns: id, due_date, due_time, completed_at, created_at.
        Filters to deleted=0, complete=1, due_date IS NOT NULL.
        Date range filters operate on due_date.
        """
        conditions = [
            "deleted = 0",
            "complete = 1",
            "due_date IS NOT NULL",
        ]
        params: list = []
        if list_id is not None:
            conditions.append("list_id = ?")
            params.append(str(list_id))
        if start_date is not None:
            conditions.append("due_date >= ?")
            params.append(start_date)
        if end_date is not None:
            conditions.append("due_date <= ?")
            params.append(end_date)

        where = " WHERE " + " AND ".join(conditions)
        sql = (
            "SELECT id, due_date, due_time, completed_at, created_at "
            f"FROM items{where}"  # noqa: S608
        )
        return pd.read_sql_query(sql, self._conn, params=params or None)

    @staticmethod
    def _due_end_ms(due_date_str: str, due_time_str: str | None) -> int:
        """Convert a due_date (and optional due_time) into ms-since-epoch.

        When due_time is missing, the deadline is end-of-day (next-day
        midnight), matching the ALL_DAY semantics in calendar_layout.
        """
        from datetime import datetime, time

        d = date.fromisoformat(due_date_str)
        if due_time_str:
            t = time.fromisoformat(due_time_str)
            return int(datetime.combine(d, t).timestamp() * 1000)
        # All-day deadline: end of due_date = start of next day
        next_day = d + timedelta(days=1)
        return int(datetime.combine(next_day, time(0, 0, 0)).timestamp() * 1000)

    def completion_timing(
        self,
        *,
        list_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> CompletionTimingResult:
        """Classify each completed item in range as EARLY, ONTIME, LATE, or UNKNOWN.

        Classification rules (no fuzz, matching calendar_layout.compute_bar_state):
            EARLY   — completed_at < due_end (any amount)
            ONTIME  — completed_at == due_end (exact)
            LATE    — completed_at > due_end (any amount)
            UNKNOWN — completed_at IS NULL (excluded from `items`)

        `due_end` is the deadline as a ms timestamp: due_date+due_time when
        due_time is set, or end-of-due-date (next-day midnight) for all-day
        items.

        Args:
            list_id: optional list filter
            start_date: optional due_date >= filter (YYYY-MM-DD)
            end_date: optional due_date <= filter (YYYY-MM-DD)

        Returns:
            CompletionTimingResult with counts and per-item classifications.
        """
        df = self._query_completed_items(list_id, start_date, end_date)

        if df.empty:
            return CompletionTimingResult(
                total=0,
                early_count=0,
                ontime_count=0,
                late_count=0,
                unknown_count=0,
                items=[],
            )

        total = len(df)
        items: list[ItemCompletionTiming] = []
        early_count = 0
        ontime_count = 0
        late_count = 0
        unknown_count = 0

        for _, row in df.iterrows():
            if bool(pd.isna(row["completed_at"])):
                unknown_count += 1
                continue
            due_end_ms = self._due_end_ms(cast(str, row["due_date"]), cast(str, row["due_time"]))
            completed_ms = int(cast(int, row["completed_at"]))
            deviation_minutes = (completed_ms - due_end_ms) // 60_000
            if completed_ms < due_end_ms:
                classification = "early"
                early_count += 1
            elif completed_ms == due_end_ms:
                classification = "ontime"
                ontime_count += 1
            else:
                classification = "late"
                late_count += 1
            items.append(
                ItemCompletionTiming(
                    item_id=str(row["id"]),
                    classification=classification,
                    deviation_minutes=int(deviation_minutes),
                )
            )

        return CompletionTimingResult(
            total=total,
            early_count=early_count,
            ontime_count=ontime_count,
            late_count=late_count,
            unknown_count=unknown_count,
            items=items,
        )

    def slip_rate(
        self,
        *,
        list_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> SlipRateResult:
        """Percentage of completed items in range that finished after their deadline.

        slip_rate = late / (early + ontime + late)

        UNKNOWN-cohort items are excluded from both numerator and
        denominator. The rate is None when the denominator is zero
        (no classifiable items in range).
        """
        timing = self.completion_timing(list_id=list_id, start_date=start_date, end_date=end_date)
        classifiable = timing.early_count + timing.ontime_count + timing.late_count
        rate: float | None
        if classifiable == 0:
            rate = None
        else:
            rate = timing.late_count / classifiable
        return SlipRateResult(
            total=timing.total,
            early_count=timing.early_count,
            ontime_count=timing.ontime_count,
            late_count=timing.late_count,
            unknown_count=timing.unknown_count,
            rate=rate,
        )

    def cycle_time(
        self,
        *,
        list_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> CycleTimeResult:
        """Distribution of (completed_at − created_at) for completed items in range.

        Excludes UNKNOWN-cohort items (no completed_at). All returned
        statistics are in minutes. Stats fields are None when no
        qualifying items exist.
        """
        df = self._query_completed_items(list_id, start_date, end_date)

        if df.empty:
            return CycleTimeResult(
                sample_count=0,
                unknown_count=0,
                mean_minutes=None,
                median_minutes=None,
                p90_minutes=None,
            )

        unknown_count = int(cast(pd.Series, df["completed_at"]).isna().sum())
        with_ts = df[df["completed_at"].notna()].copy()
        if with_ts.empty:
            return CycleTimeResult(
                sample_count=0,
                unknown_count=unknown_count,
                mean_minutes=None,
                median_minutes=None,
                p90_minutes=None,
            )

        # Cycle time in minutes: (completed_at − created_at) / 60_000
        cycle_minutes = cast(
            pd.Series,
            (
                cast(pd.Series, with_ts["completed_at"]).astype("int64")
                - cast(pd.Series, with_ts["created_at"]).astype("int64")
            )
            / 60_000,
        )
        # Negative cycle times (clock skew, manual edits) are excluded
        # rather than reported as misleading negative durations.
        cycle_minutes = cast(pd.Series, cycle_minutes[cycle_minutes >= 0])
        if cycle_minutes.empty:
            return CycleTimeResult(
                sample_count=0,
                unknown_count=unknown_count,
                mean_minutes=None,
                median_minutes=None,
                p90_minutes=None,
            )

        return CycleTimeResult(
            sample_count=int(cycle_minutes.count()),
            unknown_count=unknown_count,
            mean_minutes=float(cast(float, cycle_minutes.mean())),
            median_minutes=float(cast(float, cycle_minutes.median())),
            p90_minutes=float(cast(float, cycle_minutes.quantile(0.9))),
        )

    def notification_effectiveness(self) -> pd.DataFrame:
        """Compare notified items vs non-notified: completion rates.

        Returns DataFrame with columns:
            notified (bool), task_count, completed_count, completion_rate
        """
        cache_key = self._cache_key("notification_effectiveness")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        query = """
            SELECT
                CASE WHEN notified_at > 0 THEN 1 ELSE 0 END as notified,
                complete
            FROM items
            WHERE deleted = 0 AND due_date IS NOT NULL
        """
        df = pd.read_sql_query(query, self._conn)
        if df.empty:
            result = pd.DataFrame(
                columns=["notified", "task_count", "completed_count", "completion_rate"]
            )
            self._set_cached(cache_key, result)
            return result

        grouped = (
            df.groupby("notified")
            .agg(
                task_count=("complete", "count"),
                completed_count=("complete", "sum"),
            )
            .reset_index()
        )
        grouped["notified"] = grouped["notified"].astype(bool)
        grouped["completion_rate"] = (grouped["completed_count"] / grouped["task_count"]).fillna(
            0.0
        )

        self._set_cached(cache_key, grouped)
        return grouped

    def longest_streak(self, daily_goal: int = 1) -> int:
        """Longest consecutive-day streak ever (not just current)."""
        summary = self.daily_summary()
        if summary.empty:
            return 0

        sorted_df = summary.sort_values("date")
        threshold = max(1, daily_goal)
        max_streak = 0
        current = 0
        prev_date = None

        for _, row in sorted_df.iterrows():
            raw_d = row["date"]
            d: date = raw_d.date() if isinstance(raw_d, pd.Timestamp) else cast(date, raw_d)
            completed = int(cast(int, row["completed_sessions"]))
            if completed >= threshold:
                if prev_date is not None and (d - prev_date).days == 1:
                    current += 1
                else:
                    current = 1
                max_streak = max(max_streak, current)
            else:
                current = 0
            prev_date = d

        return max_streak

    def overdue_rate(self) -> float:
        """Fraction of incomplete items with due dates that are currently overdue (0.0-1.0)."""
        today_str = date.today().isoformat()
        query = """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN due_date < ? THEN 1 ELSE 0 END) as overdue
            FROM items
            WHERE deleted = 0 AND complete = 0 AND due_date IS NOT NULL
        """
        row = self._conn.execute(query, (today_str,)).fetchone()
        if row is None or row[0] == 0:
            return 0.0
        return row[1] / row[0]

    def improvement_suggestions(self, daily_goal: int = 0) -> list[str]:
        """Generate actionable improvement suggestions based on analytics data."""
        suggestions: list[str] = []

        # Best focus time suggestion
        blocks = self.time_block_analysis()
        qualified = cast(pd.DataFrame, blocks[blocks["session_count"] >= 3])
        if not qualified.empty:
            best = qualified.loc[cast(pd.Series, qualified["completion_rate"]).idxmax()]
            if best["completion_rate"] >= 0.8:
                suggestions.append(
                    f"Your focus is best during {best['block_label']} "
                    f"({round(best['completion_rate'] * 100)}% completion). "
                    f"Schedule important tasks in this window."
                )

        # Interruption suggestion
        all_sessions = self.sessions()
        work = all_sessions[all_sessions["session_type"] != "break"]
        if len(work) >= 5:
            interrupted = work[~work["completed"]]
            rate = len(interrupted) / len(work)
            if rate > 0.3:
                suggestions.append(
                    f"You interrupted {len(interrupted)} of {len(work)} sessions. "
                    f"Try shorter work durations or removing distractions."
                )

        # Overdue suggestion
        od_rate = self.overdue_rate()
        if od_rate > 0.2:
            pct = round(od_rate * 100)
            suggestions.append(
                f"{pct}% of your tasks with due dates are overdue. "
                f"Consider reviewing and rescheduling or breaking them into smaller tasks."
            )

        # Streak encouragement
        goal = daily_goal if daily_goal > 0 else 1
        current = self.streak(goal)
        longest = self.longest_streak(goal)
        if current > 0 and current == longest and current >= 3:
            suggestions.append(f"You're on your longest streak ever ({current} days)! Keep it up.")
        elif longest > current and longest > 3:
            suggestions.append(
                f"Your longest streak was {longest} days. "
                f"Current: {current}. Build back to your record!"
            )

        # Notification effectiveness
        notif = self.notification_effectiveness()
        if len(notif) == 2:  # noqa: PLR2004
            notified_row = notif[notif["notified"]]
            not_notified_row = notif[~notif["notified"]]
            if not notified_row.empty and not not_notified_row.empty:
                n_rate = float(notified_row.iloc[0]["completion_rate"])
                u_rate = float(not_notified_row.iloc[0]["completion_rate"])
                if n_rate > u_rate + 0.1:
                    suggestions.append(
                        f"Notified tasks complete at {round(n_rate * 100)}% vs "
                        f"{round(u_rate * 100)}% for non-notified. Notifications are helping!"
                    )

        return suggestions
