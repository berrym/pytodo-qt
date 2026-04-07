"""analytics.py

Pandas-based analytics service for focus sessions and task productivity.

Pure Python + pandas. No Qt dependency. Reads from SQLite via pd.read_sql_query().
All methods return DataFrames or scalar values. Never writes to the database.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pandas as pd


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
            conditions.append("list_id = ?")
            params.append(list_id)
        if item_id is not None:
            conditions.append("item_id = ?")
            params.append(item_id)
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
            block_data = work[mask]
            count = len(block_data)
            completed = int(block_data["completed"].sum()) if count > 0 else 0
            total_mins = float(block_data["duration_minutes"].sum()) if count > 0 else 0.0
            pom_data = block_data[block_data["is_work"]] if count > 0 else block_data
            sw_data = (
                block_data[block_data["session_type"] == "stopwatch"] if count > 0 else block_data
            )
            pom_mins = float(pom_data["duration_minutes"].sum()) if len(pom_data) > 0 else 0.0
            sw_mins = float(sw_data["duration_minutes"].sum()) if len(sw_data) > 0 else 0.0
            rate = completed / count if count > 0 else 0.0
            avg_dur = float(block_data["duration_minutes"].mean()) if count > 0 else 0.0
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
                "completed_sessions": grouped["completed"].sum().astype(int),
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
        work_mins = (
            work_and_sw[work_and_sw["session_type"] == "work"]
            .groupby("date")["duration_minutes"]
            .sum()
        )
        sw_mins = (
            work_and_sw[work_and_sw["session_type"] == "stopwatch"]
            .groupby("date")["duration_minutes"]
            .sum()
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
                    "total_minutes": float(day_data["duration_minutes"].sum())
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
                "completed_sessions": grouped["completed"].sum().astype(int),
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
            conditions.append("list_id = ?")
            params.append(list_id)

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
                "completed_sessions": grouped["completed"].sum().astype(int),
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

        completed = int(work_sw["completed"].sum())
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
        df = pd.read_sql_query(query, self._conn, params=(end.isoformat(),))
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
        """For tasks with event_date: were they completed by due_date?

        Returns DataFrame with columns:
            id, reminder, due_date, event_date, complete, on_time
        """
        cache_key = self._cache_key("scheduling_accuracy", list_id=list_id or "all")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        where = "WHERE deleted = 0 AND event_date IS NOT NULL"
        params: list[str] = []
        if list_id:
            where += " AND list_id = ?"
            params.append(list_id)

        query = f"""
            SELECT id, reminder, due_date, event_date, complete, updated_at
            FROM items {where}
        """
        df = pd.read_sql_query(query, self._conn, params=params or None)
        if df.empty:
            df["on_time"] = pd.Series(dtype="bool")
            self._set_cached(cache_key, df)
            return df

        # A task is "on time" if it was completed (complete=1) and
        # either has no due_date or was completed before/on the due_date
        df["on_time"] = df["complete"].astype(bool)

        self._set_cached(cache_key, df)
        return df

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
