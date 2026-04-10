"""Tests for chart_export.py — matplotlib-based chart rendering."""

from __future__ import annotations

import sys
from datetime import date, timedelta

import pytest

from pytodo_qt.core.database import DatabaseStorage
from pytodo_qt.core.models import TodoItem

# Skip the entire module if matplotlib isn't installed
matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

from pytodo_qt.core.analytics import AnalyticsService  # noqa: E402
from pytodo_qt.core.chart_export import (  # noqa: E402
    export_pdf_report,
    export_png,
    render_accuracy,
    render_daily_activity,
    render_gantt,
    render_time_blocks,
)


@pytest.fixture
def sample_storage(tmp_path):
    storage = DatabaseStorage(tmp_path / "test.db")
    storage.open()
    yield storage
    storage.close()


@pytest.fixture
def sample_items():
    """Plain list of TodoItems for chart rendering tests (no DB persistence)."""
    today = date.today()
    items = []
    for i in range(5):
        items.append(
            TodoItem(
                reminder=f"Task {i}",
                priority=2,
                due_date=today + timedelta(days=i),
                estimated_minutes=30 + i * 15,
                time_spent=(20 + i * 10) * 60,
                complete=(i % 2 == 0),
            )
        )
    return items


@pytest.fixture
def analytics(sample_storage):
    return AnalyticsService(sample_storage.connection)


class TestRenderGantt:
    def test_renders_with_items(self, sample_items):
        fig = render_gantt(sample_items)
        assert fig is not None
        assert len(fig.axes) >= 1

    def test_renders_empty(self):
        fig = render_gantt([])
        assert fig is not None

    def test_skips_items_without_due_date(self):
        item = TodoItem(reminder="No date")
        fig = render_gantt([item])
        assert fig is not None

    def test_truncates_long_labels(self, sample_items):
        """Labels that exceed the width cap are truncated with an ellipsis."""
        long_item = TodoItem(
            reminder="this is a ridiculously long reminder text that should definitely "
            "get ellipsis-truncated in the chart",
            priority=2,
        )
        long_item.due_date = date.today() + timedelta(days=2)
        items = [*sample_items, long_item]
        fig = render_gantt(items)
        assert fig is not None
        # Find the y-tick labels and verify at least one has been truncated
        axes = fig.axes
        assert len(axes) >= 1
        ytick_labels = [t.get_text() for t in axes[0].get_yticklabels()]
        assert any("…" in lbl for lbl in ytick_labels)

    def test_short_labels_not_truncated(self, sample_items):
        """Short labels should stay untouched."""
        fig = render_gantt(sample_items)
        ytick_labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
        # sample_items has "Task 0"..."Task 4" — none should be truncated
        assert all("…" not in lbl for lbl in ytick_labels)

    def test_include_full_legend_adds_text(self, sample_items):
        """include_full_legend=True appends a numbered legend below the chart."""
        fig_without = render_gantt(sample_items, include_full_legend=False)
        fig_with = render_gantt(sample_items, include_full_legend=True)
        # With-legend figure should be taller
        assert fig_with.get_size_inches()[1] > fig_without.get_size_inches()[1]
        # Check that the fig.texts contain a numbered entry
        text_contents = [t.get_text() for t in fig_with.texts]
        assert any("Full task reminders" in t for t in text_contents)
        assert any(t.startswith("1.") for t in text_contents)


class TestRenderDailyActivity:
    def test_renders_empty(self, analytics):
        fig = render_daily_activity(analytics)
        assert fig is not None

    def test_renders_with_days_param(self, analytics):
        fig = render_daily_activity(analytics, days=7)
        assert fig is not None


class TestRenderTimeBlocks:
    def test_renders_empty(self, analytics):
        fig = render_time_blocks(analytics)
        assert fig is not None


class TestRenderAccuracy:
    def test_renders_empty(self, analytics):
        fig = render_accuracy(analytics)
        assert fig is not None

    def test_renders_with_uuid_list_id(self, analytics):
        """Regression: AnalyticsService.estimate_accuracy must accept UUID list_id.

        Previously crashed with 'Error binding parameter 1: type UUID is not supported'
        because the UUID was passed directly to sqlite3 without str() coercion.
        """
        from uuid import uuid4

        list_id = uuid4()
        fig = render_accuracy(analytics, list_id=list_id)
        assert fig is not None


class TestExport:
    def test_export_png(self, sample_items, tmp_path):
        fig = render_gantt(sample_items)
        out = tmp_path / "gantt.png"
        export_png(fig, out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_export_pdf_report(self, sample_items, analytics, tmp_path):
        out = tmp_path / "report.pdf"
        export_pdf_report(analytics, sample_items, out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_export_pdf_with_date_range(self, sample_items, analytics, tmp_path):
        out = tmp_path / "ranged.pdf"
        today = date.today()
        export_pdf_report(
            analytics,
            sample_items,
            out,
            start_date=today,
            end_date=today + timedelta(days=10),
        )
        assert out.exists()

    def test_export_pdf_with_chart_selection(self, sample_items, analytics, tmp_path):
        out = tmp_path / "selection.pdf"
        export_pdf_report(analytics, sample_items, out, include={"gantt"})
        assert out.exists()
        # Single-page PDF is smaller than full report
        assert out.stat().st_size > 0


class TestDateRangeFiltering:
    def test_gantt_filters_by_date_range(self, sample_items):
        today = date.today()
        # sample_items have due_date today through today+4
        fig = render_gantt(
            sample_items,
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=3),
        )
        assert fig is not None

    def test_daily_activity_with_explicit_range(self, analytics):
        today = date.today()
        fig = render_daily_activity(
            analytics,
            start_date=today - timedelta(days=7),
            end_date=today,
        )
        assert fig is not None

    def test_time_blocks_with_date_range(self, analytics):
        today = date.today()
        fig = render_time_blocks(
            analytics,
            start_date=today - timedelta(days=30),
            end_date=today,
        )
        assert fig is not None


class TestMatplotlibUnavailable:
    def test_raises_when_matplotlib_missing(self, monkeypatch):
        from pytodo_qt.core import chart_export

        # Simulate matplotlib being absent by patching the import
        original_modules = {}
        for name in list(sys.modules.keys()):
            if name.startswith("matplotlib"):
                original_modules[name] = sys.modules.pop(name)

        monkeypatch.setitem(sys.modules, "matplotlib", None)
        try:
            with pytest.raises(chart_export.MatplotlibUnavailable):
                chart_export._import_matplotlib()
        finally:
            # Restore matplotlib so other tests aren't affected
            sys.modules.pop("matplotlib", None)
            for name, mod in original_modules.items():
                sys.modules[name] = mod
