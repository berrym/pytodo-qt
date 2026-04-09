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
