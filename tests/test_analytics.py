"""Tests for AnalyticsService — pandas data pipeline.

Uses in-memory SQLite fixtures. No Qt dependency.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from uuid import uuid4

import pandas as pd
import pytest

from pytodo_qt.core.analytics import AnalyticsService


def _ms(dt: datetime) -> int:
    """Convert a naive (local-time) datetime to ms since epoch.

    Matches the behavior of analytics._due_end_ms and the production
    completed_at write path, which both use datetime.timestamp() on
    naive datetimes (local-time interpretation).
    """
    return int(dt.timestamp() * 1000)


# --- Fixtures ---


@pytest.fixture()
def db():
    """In-memory SQLite database with focus_sessions and items tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE focus_sessions (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            list_id TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL,
            completed INTEGER NOT NULL DEFAULT 1,
            session_type TEXT NOT NULL DEFAULT 'work',
            date TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE items (
            id TEXT PRIMARY KEY,
            list_id TEXT NOT NULL,
            reminder TEXT NOT NULL DEFAULT '',
            time_spent INTEGER NOT NULL DEFAULT 0,
            pomodoro_count INTEGER NOT NULL DEFAULT 0,
            estimated_pomodoros INTEGER NOT NULL DEFAULT 0,
            estimated_minutes INTEGER NOT NULL DEFAULT 0,
            work_duration INTEGER NOT NULL DEFAULT 0,
            break_duration INTEGER NOT NULL DEFAULT 0,
            long_break_duration INTEGER NOT NULL DEFAULT 0,
            complete INTEGER NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0,
            priority INTEGER NOT NULL DEFAULT 2,
            due_date TEXT,
            due_time TEXT,
            due_time_block TEXT,
            event_date TEXT,
            notified_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            completed_at INTEGER
        )"""
    )
    yield conn
    conn.close()


@pytest.fixture()
def svc(db):
    """AnalyticsService with empty database."""
    return AnalyticsService(db, work_duration_minutes=25)


def _insert_session(
    db,
    *,
    item_id=None,
    list_id=None,
    start="2026-03-28T10:00:00",
    end="2026-03-28T10:25:00",
    duration=1500,
    completed=1,
    session_type="work",
    day="2026-03-28",
):
    item_id = item_id or str(uuid4())
    list_id = list_id or str(uuid4())
    db.execute(
        "INSERT INTO focus_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid4()), item_id, list_id, start, end, duration, completed, session_type, day),
    )
    return item_id, list_id


def _insert_item(
    db,
    *,
    item_id=None,
    list_id=None,
    reminder="test item",
    time_spent=0,
    pomodoro_count=0,
    estimated_pomodoros=0,
    estimated_minutes=0,
    work_duration=0,
    complete=0,
    due_date=None,
    due_time=None,
    due_time_block=None,
    event_date=None,
    notified_at=0,
    priority=2,
    created_at=0,
    updated_at=0,
    completed_at=None,
):
    item_id = item_id or str(uuid4())
    list_id = list_id or str(uuid4())
    db.execute(
        """INSERT INTO items (id, list_id, reminder, time_spent, pomodoro_count,
           estimated_pomodoros, estimated_minutes, work_duration, break_duration,
           long_break_duration, complete, deleted, priority, due_date, due_time,
           due_time_block, event_date, notified_at, created_at, updated_at, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item_id,
            list_id,
            reminder,
            time_spent,
            pomodoro_count,
            estimated_pomodoros,
            estimated_minutes,
            work_duration,
            complete,
            priority,
            due_date,
            due_time,
            due_time_block,
            event_date,
            notified_at,
            created_at,
            updated_at,
            completed_at,
        ),
    )
    return item_id, list_id


# --- Empty data tests ---


class TestEmptyData:
    def test_sessions_empty(self, svc):
        df = svc.sessions()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert "duration_minutes" in df.columns

    def test_daily_summary_empty(self, svc):
        df = svc.daily_summary()
        assert len(df) == 0
        assert "completion_rate" in df.columns

    def test_item_summary_empty(self, svc):
        df = svc.item_summary()
        assert len(df) == 0

    def test_streak_empty(self, svc):
        assert svc.streak() == 0

    def test_focus_score_empty(self, svc):
        assert svc.focus_score(daily_goal=4) == -1

    def test_weekly_chart_empty(self, svc):
        df = svc.weekly_chart(date(2026, 3, 23))
        assert len(df) == 7
        assert df["session_count"].sum() == 0

    def test_time_block_analysis_empty(self, svc):
        df = svc.time_block_analysis()
        assert len(df) == 12
        assert df["session_count"].sum() == 0

    def test_estimate_accuracy_empty(self, svc):
        df = svc.estimate_accuracy()
        assert len(df) == 0

    def test_rolling_averages_empty(self, svc):
        df = svc.rolling_averages()
        assert len(df) == 0

    def test_top_items_empty(self, svc):
        df = svc.top_items("2026-03-01", "2026-03-31")
        assert len(df) == 0


# --- Sessions DataFrame tests ---


class TestSessions:
    def test_basic_session(self, db, svc):
        _insert_session(db, duration=1500, day="2026-03-28")
        df = svc.sessions()
        assert len(df) == 1
        assert df.iloc[0]["duration_seconds"] == 1500
        assert df.iloc[0]["duration_minutes"] == 25.0

    def test_computed_columns(self, db, svc):
        _insert_session(
            db,
            start="2026-03-28T14:30:00",
            end="2026-03-28T14:55:00",
            day="2026-03-28",
        )
        df = svc.sessions()
        row = df.iloc[0]
        assert row["hour_of_day"] == 14
        assert row["is_work"] == True  # noqa: E712

    def test_completed_cast(self, db, svc):
        _insert_session(db, completed=0)
        df = svc.sessions()
        assert df.iloc[0]["completed"] == False  # noqa: E712

    def test_filter_by_date_range(self, db, svc):
        _insert_session(db, day="2026-03-27")
        _insert_session(db, day="2026-03-28")
        _insert_session(db, day="2026-03-29")
        df = svc.sessions(start_date="2026-03-28", end_date="2026-03-28")
        assert len(df) == 1

    def test_filter_by_item_id(self, db, svc):
        item1, _ = _insert_session(db)
        _insert_session(db)
        df = svc.sessions(item_id=item1)
        assert len(df) == 1

    def test_filter_by_session_type(self, db, svc):
        _insert_session(db, session_type="work")
        _insert_session(db, session_type="stopwatch")
        _insert_session(db, session_type="break")
        df = svc.sessions(session_type="stopwatch")
        assert len(df) == 1
        assert df.iloc[0]["session_type"] == "stopwatch"

    def test_stopwatch_is_not_work(self, db, svc):
        _insert_session(db, session_type="stopwatch")
        df = svc.sessions()
        assert df.iloc[0]["is_work"] == False  # noqa: E712

    def test_multiple_filters(self, db, svc):
        item1, list1 = _insert_session(db, session_type="work", day="2026-03-28")
        _insert_session(db, item_id=item1, list_id=list1, session_type="break", day="2026-03-28")
        df = svc.sessions(item_id=item1, session_type="work")
        assert len(df) == 1


# --- Daily summary tests ---


class TestDailySummary:
    def test_single_day(self, db, svc):
        _insert_session(db, duration=1500, day="2026-03-28", session_type="work")
        _insert_session(db, duration=600, completed=0, day="2026-03-28", session_type="work")
        df = svc.daily_summary()
        assert len(df) == 1
        row = df.iloc[0]
        assert row["total_sessions"] == 2
        assert row["completed_sessions"] == 1
        assert row["interrupted_sessions"] == 1
        assert row["completion_rate"] == 0.5

    def test_multiple_days(self, db, svc):
        _insert_session(db, day="2026-03-27")
        _insert_session(db, day="2026-03-28")
        _insert_session(db, day="2026-03-28")
        df = svc.daily_summary()
        assert len(df) == 2

    def test_work_and_stopwatch_minutes(self, db, svc):
        _insert_session(db, duration=1500, session_type="work", day="2026-03-28")
        _insert_session(db, duration=600, session_type="stopwatch", day="2026-03-28")
        df = svc.daily_summary()
        row = df.iloc[0]
        assert row["work_minutes"] == 25.0
        assert row["stopwatch_minutes"] == 10.0

    def test_breaks_excluded(self, db, svc):
        _insert_session(db, duration=1500, session_type="work", day="2026-03-28")
        _insert_session(db, duration=300, session_type="break", day="2026-03-28")
        df = svc.daily_summary()
        assert len(df) == 1
        assert df.iloc[0]["total_sessions"] == 1  # Break excluded

    def test_date_range_filter(self, db, svc):
        _insert_session(db, day="2026-03-27")
        _insert_session(db, day="2026-03-28")
        df = svc.daily_summary(start_date="2026-03-28")
        assert len(df) == 1


# --- Item summary tests ---


class TestItemSummary:
    def test_single_item(self, db, svc):
        item_id, list_id = _insert_session(db, duration=1500, session_type="work")
        _insert_session(
            db, item_id=item_id, list_id=list_id, duration=600, session_type="stopwatch"
        )
        df = svc.item_summary()
        assert len(df) == 1
        row = df.iloc[0]
        assert row["work_sessions"] == 1
        assert row["stopwatch_sessions"] == 1
        assert row["total_seconds"] == 2100

    def test_multiple_items(self, db, svc):
        _insert_session(db)
        _insert_session(db)
        df = svc.item_summary()
        assert len(df) == 2

    def test_completion_rate(self, db, svc):
        item_id, list_id = _insert_session(db, completed=1)
        _insert_session(db, item_id=item_id, list_id=list_id, completed=0)
        df = svc.item_summary()
        assert df.iloc[0]["completion_rate"] == 0.5

    def test_list_filter(self, db, svc):
        _, list1 = _insert_session(db)
        _, list2 = _insert_session(db)
        df = svc.item_summary(list_id=list1)
        assert len(df) == 1

    def test_breaks_excluded(self, db, svc):
        item_id, list_id = _insert_session(db, session_type="work")
        _insert_session(db, item_id=item_id, list_id=list_id, session_type="break")
        df = svc.item_summary()
        assert len(df) == 1
        assert df.iloc[0]["work_sessions"] == 1


# --- Weekly chart tests ---


class TestWeeklyChart:
    def test_seven_rows(self, db, svc):
        df = svc.weekly_chart(date(2026, 3, 23))
        assert len(df) == 7
        assert df.iloc[0]["day_name"] == "Monday"
        assert df.iloc[6]["day_name"] == "Sunday"

    def test_with_data(self, db, svc):
        # Monday 2026-03-23
        _insert_session(db, duration=1500, day="2026-03-23")
        _insert_session(db, duration=1500, day="2026-03-23")
        df = svc.weekly_chart(date(2026, 3, 23))
        assert df.iloc[0]["session_count"] == 2
        assert df.iloc[0]["total_minutes"] == 50.0
        assert df.iloc[1]["session_count"] == 0

    def test_interrupted_excluded(self, db, svc):
        _insert_session(db, completed=0, day="2026-03-23")
        df = svc.weekly_chart(date(2026, 3, 23))
        assert df.iloc[0]["session_count"] == 0


# --- Rolling averages tests ---


class TestRollingAverages:
    def test_basic(self, db, svc):
        for i in range(10):
            d = date(2026, 3, 20) + timedelta(days=i)
            _insert_session(db, duration=1500, day=d.isoformat())
        df = svc.rolling_averages()
        assert len(df) == 10
        assert "rolling_7d_sessions" in df.columns
        assert "rolling_30d_minutes" in df.columns

    def test_short_series(self, db, svc):
        _insert_session(db, duration=1500, day="2026-03-28")
        df = svc.rolling_averages()
        assert len(df) == 1
        # With min_periods=1, rolling mean equals the single value
        assert df.iloc[0]["rolling_7d_sessions"] == 1.0

    def test_window_toggle(self, db, svc):
        _insert_session(db, day="2026-03-28")
        df = svc.rolling_averages(window_7=True, window_30=False)
        assert "rolling_7d_sessions" in df.columns
        assert "rolling_30d_sessions" not in df.columns


# --- Streak tests ---


class TestStreak:
    def test_consecutive_days(self, db, svc):
        today = date.today()
        for i in range(5):
            d = today - timedelta(days=i)
            _insert_session(db, day=d.isoformat())
        assert svc.streak(daily_goal=1) == 5

    def test_gap_breaks_streak(self, db, svc):
        today = date.today()
        _insert_session(db, day=today.isoformat())
        # Skip yesterday
        _insert_session(db, day=(today - timedelta(days=2)).isoformat())
        assert svc.streak(daily_goal=1) == 1

    def test_goal_threshold(self, db, svc):
        today = date.today()
        _insert_session(db, day=today.isoformat())  # Only 1 session
        assert svc.streak(daily_goal=3) == 0  # Need 3, have 1

    def test_goal_met(self, db, svc):
        today = date.today()
        for _ in range(3):
            _insert_session(db, day=today.isoformat())
        assert svc.streak(daily_goal=3) == 1

    def test_no_sessions_today(self, db, svc):
        yesterday = date.today() - timedelta(days=1)
        _insert_session(db, day=yesterday.isoformat())
        assert svc.streak() == 0


# --- Focus score tests ---


class TestFocusScore:
    def test_no_sessions(self, db, svc):
        assert svc.focus_score(daily_goal=4) == -1

    def test_basic_score(self, db, svc):
        today = date.today()
        _insert_session(db, day=today.isoformat())
        score = svc.focus_score(daily_goal=4, today=today)
        assert 0 <= score <= 100

    def test_max_score(self, db, svc):
        today = date.today()
        # 5 consecutive days + 8 sessions today + all completed
        for i in range(5):
            d = today - timedelta(days=i)
            for _ in range(8):
                _insert_session(db, day=d.isoformat())
        score = svc.focus_score(daily_goal=8, today=today)
        assert score >= 80  # Should be high

    def test_zero_goal(self, db, svc):
        today = date.today()
        _insert_session(db, day=today.isoformat())
        score = svc.focus_score(daily_goal=0, today=today)
        assert score > 0


# --- Time block analysis tests ---


class TestTimeBlockAnalysis:
    def test_twelve_blocks(self, db, svc):
        _insert_session(db, start="2026-03-28T10:00:00", end="2026-03-28T10:25:00")
        df = svc.time_block_analysis()
        assert len(df) == 12
        # 10:00 falls in block 10-12
        block_10 = df[df["block_start_hour"] == 10]
        assert block_10.iloc[0]["session_count"] == 1

    def test_completion_rate(self, db, svc):
        _insert_session(db, start="2026-03-28T10:00:00", completed=1)
        _insert_session(db, start="2026-03-28T11:00:00", completed=0)
        df = svc.time_block_analysis()
        block_10 = df[df["block_start_hour"] == 10]
        assert block_10.iloc[0]["completion_rate"] == 0.5

    def test_stopwatch_included(self, db, svc):
        _insert_session(db, start="2026-03-28T14:00:00", session_type="stopwatch")
        df = svc.time_block_analysis()
        block_14 = df[df["block_start_hour"] == 14]
        assert block_14.iloc[0]["session_count"] == 1


# --- Estimate accuracy tests ---


class TestEstimateAccuracy:
    def test_pomodoro_estimate(self, db, svc):
        item_id, list_id = _insert_item(
            db,
            estimated_pomodoros=4,
            time_spent=5000,  # ~83 min actual
        )
        df = svc.estimate_accuracy()
        assert len(df) == 1
        row = df.iloc[0]
        assert row["estimated_minutes"] == 100.0  # 4 * 25
        assert abs(row["actual_minutes"] - 83.33) < 0.1

    def test_minutes_estimate(self, db, svc):
        _insert_item(db, estimated_minutes=60, time_spent=3600)
        df = svc.estimate_accuracy()
        row = df.iloc[0]
        assert row["estimated_minutes"] == 60.0
        assert row["actual_minutes"] == 60.0
        assert row["accuracy_ratio"] == 1.0
        assert row["variance_minutes"] == 0.0

    def test_combined_estimate(self, db, svc):
        _insert_item(db, estimated_pomodoros=2, estimated_minutes=30, time_spent=0)
        df = svc.estimate_accuracy()
        row = df.iloc[0]
        assert row["estimated_minutes"] == 80.0  # 2*25 + 30

    def test_no_estimate_excluded(self, db, svc):
        _insert_item(db, estimated_pomodoros=0, estimated_minutes=0, time_spent=1000)
        df = svc.estimate_accuracy()
        assert len(df) == 0


# --- Top items tests ---


class TestTopItems:
    def test_ranked_by_count(self, db, svc):
        item1, list1 = _insert_session(db, day="2026-03-28")
        _insert_session(db, item_id=item1, list_id=list1, day="2026-03-28")
        _insert_session(db, item_id=item1, list_id=list1, day="2026-03-28")
        item2, _ = _insert_session(db, day="2026-03-28")
        df = svc.top_items("2026-03-28", "2026-03-28")
        assert len(df) == 2
        assert df.iloc[0]["session_count"] == 3
        assert df.iloc[0]["item_id"] == item1

    def test_limit(self, db, svc):
        for _ in range(10):
            _insert_session(db, day="2026-03-28")
        df = svc.top_items("2026-03-28", "2026-03-28", limit=3)
        assert len(df) == 3


# --- Cache tests ---


class TestCache:
    def test_cache_hit(self, db, svc):
        _insert_session(db)
        df1 = svc.sessions()
        df2 = svc.sessions()
        assert df1 is df2  # Same object — cache hit

    def test_invalidate_clears(self, db, svc):
        _insert_session(db)
        df1 = svc.sessions()
        svc.invalidate()
        df2 = svc.sessions()
        assert df1 is not df2  # Different object — rebuilt

    def test_different_filters_different_cache(self, db, svc):
        _insert_session(db, session_type="work")
        _insert_session(db, session_type="stopwatch")
        df_work = svc.sessions(session_type="work")
        df_all = svc.sessions()
        assert len(df_work) == 1
        assert len(df_all) == 2

    def test_set_work_duration_invalidates(self, db, svc):
        _insert_session(db)
        df1 = svc.sessions()
        svc.set_work_duration(50)
        df2 = svc.sessions()
        assert df1 is not df2


# ---------------------------------------------------------------------------
# v18 analytics methods
# ---------------------------------------------------------------------------


class TestUpcomingDigest:
    def test_empty(self, db, svc):
        df = svc.upcoming_digest(days=3)
        assert len(df) == 0

    def test_returns_due_items(self, db, svc):
        today = date.today()
        _insert_item(db, reminder="Due today", due_date=today.isoformat())
        _insert_item(db, reminder="Due tomorrow", due_date=(today + timedelta(days=1)).isoformat())
        _insert_item(db, reminder="Far away", due_date=(today + timedelta(days=30)).isoformat())
        df = svc.upcoming_digest(days=3)
        assert len(df) == 2
        assert "Due today" in df["reminder"].values
        assert "Due tomorrow" in df["reminder"].values

    def test_excludes_completed(self, db, svc):
        today = date.today()
        _insert_item(db, reminder="Done", due_date=today.isoformat(), complete=1)
        df = svc.upcoming_digest(days=3)
        assert len(df) == 0

    def test_includes_overdue(self, db, svc):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        _insert_item(db, reminder="Overdue", due_date=yesterday)
        df = svc.upcoming_digest(days=3)
        assert len(df) == 1


class TestTimeBlockDistribution:
    def test_empty(self, db, svc):
        df = svc.time_block_distribution()
        assert len(df) == 0

    def test_counts_by_block(self, db, svc):
        _insert_item(db, reminder="Morning 1", due_time_block="morning")
        _insert_item(db, reminder="Morning 2", due_time_block="morning", complete=1)
        _insert_item(db, reminder="Evening 1", due_time_block="evening")
        df = svc.time_block_distribution()
        assert len(df) == 2
        morning = df[df["time_block"] == "morning"]
        assert morning.iloc[0]["task_count"] == 2
        assert morning.iloc[0]["completed_count"] == 1
        assert morning.iloc[0]["completion_rate"] == 0.5


class TestSchedulingAccuracy:
    def test_empty(self, db, svc):
        df = svc.scheduling_accuracy()
        assert len(df) == 0

    def test_returns_event_date_items(self, db, svc):
        # Item completed on the event date (real timestamp) is on time
        completed_ms = _ms(datetime(2026, 5, 1, 14, 30, 0))
        _insert_item(
            db,
            reminder="Dentist",
            event_date="2026-05-01",
            complete=1,
            completed_at=completed_ms,
        )
        _insert_item(db, reminder="No event", due_date="2026-04-10")
        df = svc.scheduling_accuracy()
        assert len(df) == 1
        assert df.iloc[0]["reminder"] == "Dentist"
        assert bool(df.iloc[0]["on_time"]) is True
        assert df.iloc[0]["timestamp_source"] == "completed_at"

    def test_late_completion_marked_not_on_time(self, db, svc):
        """A completion timestamp after the event date is not on-time."""
        # event_date is May 1, but completed May 3
        completed_ms = _ms(datetime(2026, 5, 3, 9, 0, 0))
        _insert_item(
            db,
            reminder="Late dentist",
            event_date="2026-05-01",
            complete=1,
            completed_at=completed_ms,
        )
        df = svc.scheduling_accuracy()
        assert len(df) == 1
        assert bool(df.iloc[0]["on_time"]) is False
        assert df.iloc[0]["timestamp_source"] == "completed_at"

    def test_unknown_completion_falls_back_to_updated_at(self, db, svc):
        """Pre-v19 completion (completed_at IS NULL) uses updated_at fallback."""
        # updated_at on May 1 (on time relative to May 1 event_date)
        updated_ms = _ms(datetime(2026, 5, 1, 12, 0, 0))
        _insert_item(
            db,
            reminder="Old completion",
            event_date="2026-05-01",
            complete=1,
            completed_at=None,  # UNKNOWN cohort
            updated_at=updated_ms,
        )
        df = svc.scheduling_accuracy()
        assert len(df) == 1
        assert df.iloc[0]["timestamp_source"] == "updated_at"
        assert bool(df.iloc[0]["on_time"]) is True

    def test_incomplete_marked_incomplete(self, db, svc):
        """Incomplete tasks have on_time=False and source='incomplete'."""
        _insert_item(
            db,
            reminder="Pending",
            event_date="2026-05-01",
            complete=0,
        )
        df = svc.scheduling_accuracy()
        assert len(df) == 1
        assert df.iloc[0]["timestamp_source"] == "incomplete"
        assert bool(df.iloc[0]["on_time"]) is False


class TestCompletionTiming:
    """Step 4: per-item EARLY/ONTIME/LATE/UNKNOWN classification."""

    def test_empty(self, db, svc):
        result = svc.completion_timing()
        assert result.total == 0
        assert result.early_count == 0
        assert result.late_count == 0
        assert result.items == []

    def test_early_completion(self, db, svc):
        """Completed before due_time → EARLY with negative deviation."""
        # Due Apr 10 at 15:00, completed Apr 10 at 14:00 (60 min early)
        due_end = _ms(datetime(2026, 4, 10, 15, 0, 0))
        completed = _ms(datetime(2026, 4, 10, 14, 0, 0))
        _insert_item(
            db,
            reminder="Early",
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            completed_at=completed,
        )
        result = svc.completion_timing()
        assert result.total == 1
        assert result.early_count == 1
        assert result.ontime_count == 0
        assert result.late_count == 0
        assert len(result.items) == 1
        assert result.items[0].classification == "early"
        assert result.items[0].deviation_minutes == -60
        # Sanity: due_end vs completed math
        assert (completed - due_end) // 60_000 == -60

    def test_ontime_exact_match(self, db, svc):
        """Completed exactly at due_time → ONTIME with zero deviation."""
        completed = _ms(datetime(2026, 4, 10, 15, 0, 0))
        _insert_item(
            db,
            reminder="Ontime",
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            completed_at=completed,
        )
        result = svc.completion_timing()
        assert result.ontime_count == 1
        assert result.items[0].classification == "ontime"
        assert result.items[0].deviation_minutes == 0

    def test_late_completion(self, db, svc):
        """Completed after due_time → LATE with positive deviation."""
        # Due Apr 10 at 15:00, completed Apr 11 at 09:00
        completed = _ms(datetime(2026, 4, 11, 9, 0, 0))
        _insert_item(
            db,
            reminder="Late",
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            completed_at=completed,
        )
        result = svc.completion_timing()
        assert result.late_count == 1
        assert result.items[0].classification == "late"
        # Apr 10 15:00 → Apr 11 09:00 = 18 hours = 1080 minutes
        assert result.items[0].deviation_minutes == 1080

    def test_unknown_excluded_from_items_list(self, db, svc):
        """UNKNOWN cohort items are NOT in items list but are counted separately."""
        _insert_item(
            db,
            reminder="Old completion",
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            completed_at=None,  # UNKNOWN
        )
        result = svc.completion_timing()
        assert result.total == 1
        assert result.unknown_count == 1
        assert result.early_count == 0
        assert result.late_count == 0
        assert result.ontime_count == 0
        assert result.items == []  # excluded from per-item list

    def test_all_day_due_uses_end_of_day(self, db, svc):
        """An item with no due_time uses end-of-day (next-day midnight) as the deadline."""
        # Due Apr 10 (no time), completed Apr 10 at 23:30 — should be EARLY
        # because deadline is Apr 11 00:00
        completed = _ms(datetime(2026, 4, 10, 23, 30, 0))
        _insert_item(
            db,
            reminder="All day done late but on time",
            due_date="2026-04-10",
            due_time=None,
            complete=1,
            completed_at=completed,
        )
        result = svc.completion_timing()
        assert result.early_count == 1

    def test_date_range_filter(self, db, svc):
        """Date range filters operate on due_date."""
        completed = _ms(datetime(2026, 4, 10, 14, 0, 0))
        _insert_item(
            db,
            reminder="In range",
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            completed_at=completed,
        )
        _insert_item(
            db,
            reminder="Out of range",
            due_date="2026-05-15",
            due_time="15:00:00",
            complete=1,
            completed_at=completed,
        )
        result = svc.completion_timing(start_date="2026-04-01", end_date="2026-04-30")
        assert result.total == 1
        assert result.items[0].classification == "early"

    def test_list_id_filter(self, db, svc):
        """list_id filter scopes the cohort."""
        list_a = str(uuid4())
        list_b = str(uuid4())
        completed = _ms(datetime(2026, 4, 10, 14, 0, 0))
        _insert_item(
            db,
            list_id=list_a,
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            completed_at=completed,
        )
        _insert_item(
            db,
            list_id=list_b,
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            completed_at=completed,
        )
        result = svc.completion_timing(list_id=list_a)
        assert result.total == 1


class TestSlipRate:
    def test_empty_returns_none_rate(self, db, svc):
        result = svc.slip_rate()
        assert result.rate is None
        assert result.total == 0

    def test_zero_late_rate(self, db, svc):
        """All early/ontime items → slip rate 0.0."""
        for _ in range(3):
            completed = _ms(datetime(2026, 4, 10, 14, 0, 0))
            _insert_item(
                db,
                due_date="2026-04-10",
                due_time="15:00:00",
                complete=1,
                completed_at=completed,
            )
        result = svc.slip_rate()
        assert result.rate == 0.0
        assert result.early_count == 3
        assert result.late_count == 0

    def test_mixed_slip_rate(self, db, svc):
        """2 late out of 4 → slip rate 0.5."""
        early_ts = _ms(datetime(2026, 4, 10, 14, 0, 0))
        late_ts = _ms(datetime(2026, 4, 11, 9, 0, 0))
        for ts in [early_ts, early_ts, late_ts, late_ts]:
            _insert_item(
                db,
                due_date="2026-04-10",
                due_time="15:00:00",
                complete=1,
                completed_at=ts,
            )
        result = svc.slip_rate()
        assert result.rate == 0.5
        assert result.early_count == 2
        assert result.late_count == 2

    def test_unknown_excluded_from_rate(self, db, svc):
        """UNKNOWN items don't affect rate but are reported separately."""
        late_ts = _ms(datetime(2026, 4, 11, 9, 0, 0))
        # 1 late, 1 unknown — rate should be 1.0 (late/(late) = 1.0), not 0.5
        _insert_item(
            db,
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            completed_at=late_ts,
        )
        _insert_item(
            db,
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            completed_at=None,
        )
        result = svc.slip_rate()
        assert result.rate == 1.0
        assert result.unknown_count == 1
        assert result.late_count == 1

    def test_only_unknown_returns_none_rate(self, db, svc):
        _insert_item(
            db,
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            completed_at=None,
        )
        result = svc.slip_rate()
        assert result.rate is None
        assert result.unknown_count == 1


class TestCycleTime:
    def test_empty_returns_none_stats(self, db, svc):
        result = svc.cycle_time()
        assert result.sample_count == 0
        assert result.mean_minutes is None

    def test_basic_stats(self, db, svc):
        """Three items with cycle times 60, 120, 180 minutes."""
        completed = _ms(datetime(2026, 4, 10, 14, 0, 0))
        for cycle_minutes in [60, 120, 180]:
            created = completed - cycle_minutes * 60_000
            _insert_item(
                db,
                due_date="2026-04-10",
                due_time="15:00:00",
                complete=1,
                created_at=created,
                completed_at=completed,
            )
        result = svc.cycle_time()
        assert result.sample_count == 3
        assert result.mean_minutes == pytest.approx(120.0)
        assert result.median_minutes == pytest.approx(120.0)
        # p90 of [60, 120, 180]
        assert result.p90_minutes == pytest.approx(168.0)

    def test_unknown_excluded(self, db, svc):
        """UNKNOWN items don't contribute to stats."""
        completed = _ms(datetime(2026, 4, 10, 14, 0, 0))
        _insert_item(
            db,
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            created_at=completed - 60 * 60_000,
            completed_at=completed,
        )
        # UNKNOWN — has created_at but no completed_at
        _insert_item(
            db,
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            created_at=completed - 120 * 60_000,
            completed_at=None,
        )
        result = svc.cycle_time()
        assert result.sample_count == 1
        assert result.unknown_count == 1
        assert result.mean_minutes == pytest.approx(60.0)

    def test_negative_cycle_times_excluded(self, db, svc):
        """Negative durations (clock skew, manual edits) are excluded."""
        completed = _ms(datetime(2026, 4, 10, 14, 0, 0))
        # created_at AFTER completed_at — corrupt data
        _insert_item(
            db,
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            created_at=completed + 60 * 60_000,
            completed_at=completed,
        )
        result = svc.cycle_time()
        assert result.sample_count == 0
        assert result.mean_minutes is None

    def test_list_id_and_date_filter(self, db, svc):
        list_a = str(uuid4())
        list_b = str(uuid4())
        completed = _ms(datetime(2026, 4, 10, 14, 0, 0))
        _insert_item(
            db,
            list_id=list_a,
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            created_at=completed - 60 * 60_000,
            completed_at=completed,
        )
        _insert_item(
            db,
            list_id=list_b,
            due_date="2026-04-10",
            due_time="15:00:00",
            complete=1,
            created_at=completed - 200 * 60_000,
            completed_at=completed,
        )
        result = svc.cycle_time(list_id=list_a)
        assert result.sample_count == 1
        assert result.mean_minutes == pytest.approx(60.0)


class TestNotificationEffectiveness:
    def test_empty(self, db, svc):
        df = svc.notification_effectiveness()
        assert len(df) == 0

    def test_groups_notified_vs_not(self, db, svc):
        today = date.today().isoformat()
        _insert_item(db, reminder="Notified done", due_date=today, notified_at=1000, complete=1)
        _insert_item(db, reminder="Notified not done", due_date=today, notified_at=1000)
        _insert_item(db, reminder="Not notified done", due_date=today, complete=1)
        df = svc.notification_effectiveness()
        assert len(df) == 2
        notified = df[df["notified"] == True]  # noqa: E712
        assert notified.iloc[0]["task_count"] == 2
        assert notified.iloc[0]["completed_count"] == 1


class TestLongestStreak:
    def test_empty(self, db, svc):
        assert svc.longest_streak() == 0

    def test_consecutive_days(self, db, svc):
        """5 consecutive days of sessions should produce longest_streak >= 5."""
        # Use fixed dates far in the past so they're never "today"
        for i in range(5):
            d = f"2025-06-{10 + i:02d}"
            _insert_session(db, day=d, start=f"{d}T10:00:00", end=f"{d}T10:25:00")
        assert svc.longest_streak() >= 5

    def test_gap_resets(self, db, svc):
        """A gap in days resets the streak — longest should be 3, not 5."""
        for d in ["2025-06-10", "2025-06-11", "2025-06-12", "2025-06-14", "2025-06-15"]:
            _insert_session(db, day=d, start=f"{d}T10:00:00", end=f"{d}T10:25:00")
        # 3 consecutive (10-12), gap on 13, then 2 consecutive (14-15)
        assert svc.longest_streak() == 3


class TestOverdueRate:
    def test_empty(self, db, svc):
        assert svc.overdue_rate() == 0.0

    def test_all_future(self, db, svc):
        """Items due far in the future have 0% overdue rate."""
        _insert_item(db, reminder="Future 1", due_date="2099-12-31")
        _insert_item(db, reminder="Future 2", due_date="2099-12-30")
        assert svc.overdue_rate() == 0.0

    def test_all_past(self, db, svc):
        """Items due far in the past are 100% overdue."""
        _insert_item(db, reminder="Old 1", due_date="2020-01-01")
        _insert_item(db, reminder="Old 2", due_date="2020-01-02")
        assert svc.overdue_rate() == 1.0

    def test_mixed(self, db, svc):
        """One past, one future = 50% overdue."""
        _insert_item(db, reminder="Old", due_date="2020-01-01")
        _insert_item(db, reminder="Future", due_date="2099-12-31")
        rate = svc.overdue_rate()
        assert abs(rate - 0.5) < 0.01

    def test_completed_excluded(self, db, svc):
        """Completed items are excluded even if past due."""
        _insert_item(db, reminder="Done", due_date="2020-01-01", complete=1)
        assert svc.overdue_rate() == 0.0


class TestImprovementSuggestions:
    def test_empty_returns_list(self, db, svc):
        suggestions = svc.improvement_suggestions()
        assert isinstance(suggestions, list)

    def test_overdue_suggestion_triggers(self, db, svc):
        """When >20% of tasks are overdue, a suggestion should mention it."""
        for i in range(5):
            _insert_item(db, reminder=f"Old {i}", due_date="2020-01-01")
        suggestions = svc.improvement_suggestions()
        assert any("overdue" in s.lower() for s in suggestions)
