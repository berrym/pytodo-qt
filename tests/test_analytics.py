"""Tests for AnalyticsService — pandas data pipeline.

Uses in-memory SQLite fixtures. No Qt dependency.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from uuid import uuid4

import pandas as pd
import pytest

from pytodo_qt.core.analytics import AnalyticsService

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
            complete INTEGER NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0
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
    time_spent=0,
    pomodoro_count=0,
    estimated_pomodoros=0,
    estimated_minutes=0,
):
    item_id = item_id or str(uuid4())
    list_id = list_id or str(uuid4())
    db.execute(
        "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
        (
            item_id,
            list_id,
            "test item",
            time_spent,
            pomodoro_count,
            estimated_pomodoros,
            estimated_minutes,
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
