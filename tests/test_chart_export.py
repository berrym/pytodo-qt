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
    render_completion_timing,
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

    def test_uses_bar_state_palette_for_legend(self, sample_items):
        """The legend reflects the BarState palette: in-progress, due-soon,
        overdue, completed, early surplus, late overflow."""
        fig = render_gantt(sample_items)
        legends = [entry.get_text() for ax in fig.axes for entry in ax.get_legend().texts]
        joined = " ".join(legends).lower()
        # The five lifecycle labels should appear
        assert "in progress" in joined
        assert "overdue" in joined
        assert "completed" in joined
        assert "early surplus" in joined
        assert "late overflow" in joined

    def test_short_bars_meet_minimum_visible_width(self):
        """Sub-day tasks on a multi-day chart get a minimum visible
        width so they don't collapse to invisible 1-pixel rectangles.

        A 25-minute task on a 16-day chart would naturally render at
        ~0.1 % of the chart width — about 1 px on a 1200 px figure
        and effectively invisible. Every bar should occupy at least
        a small but readable fraction of the chart's x-axis range
        regardless of the raw duration.
        """
        from datetime import time as _time

        today = date.today()
        items = []
        for days_ago in (15, 12, 10, 7, 5, 3, 1, 0):
            d = today - timedelta(days=days_ago)
            it = TodoItem(reminder=f"Task {days_ago}d ago", due_date=d, due_time=_time(14, 0))
            it.estimated_minutes = 25
            items.append(it)

        fig = render_gantt(
            items,
            today=today,
            start_date=today - timedelta(days=15),
            end_date=today + timedelta(days=1),
        )
        ax = fig.axes[0]
        x_range = ax.get_xlim()[1] - ax.get_xlim()[0]
        # Every plotted patch covers at least 0.5 % of the x-axis range
        # (a hair below the 0.6 % threshold in the renderer to absorb
        # any rounding).
        for patch in ax.patches:
            if hasattr(patch, "get_width"):
                width_fraction = patch.get_width() / x_range
                assert width_fraction >= 0.005

    def test_naturally_wide_bars_keep_actual_width(self):
        """Bars whose natural duration already exceeds the minimum
        visible width keep their accurate width — the floor only
        applies to sub-threshold bars."""
        today = date.today()
        # An all-day task on a single-day chart spans the entire range.
        item = TodoItem(reminder="All-day", due_date=today)
        fig = render_gantt([item], today=today, start_date=today, end_date=today)
        ax = fig.axes[0]
        # A 1.0-day bar in a 1.0-day window is exactly 100 %.
        widest = max(p.get_width() for p in ax.patches if hasattr(p, "get_width"))
        x_range = ax.get_xlim()[1] - ax.get_xlim()[0]
        assert widest / x_range == pytest.approx(1.0, abs=0.01)

    def test_xlim_honours_explicit_date_range(self):
        """When the caller passes a start_date and end_date, the chart
        x-axis stretches to at least that range so the visible frame
        matches the export dialog selection."""
        from matplotlib import dates as mdates

        today = date.today()
        item = TodoItem(reminder="Today only", due_date=today)
        start = today - timedelta(days=10)
        end = today + timedelta(days=10)
        fig = render_gantt([item], today=today, start_date=start, end_date=end)
        ax = fig.axes[0]
        xlim = ax.get_xlim()
        assert xlim[0] <= mdates.date2num(start)
        assert xlim[1] >= mdates.date2num(end)


class TestGanttTaskSetParity:
    """The exported chart pulls the same set of tasks the desktop
    Timeline tab pulls — top-level only, sorted by user tiers, no
    silent truncation. Subtasks render through their parent in the
    calendar pipeline so the Gantt export filters them out."""

    def test_subtasks_excluded(self):
        from uuid import uuid4

        today = date.today()
        parent = TodoItem(reminder="Parent", due_date=today)
        sub = TodoItem(reminder="Subtask", due_date=today, parent_id=parent.id)
        # Defensive uuid hygiene — the model assigns ids on construct
        # but we want to be explicit here.
        if parent.id is None:
            parent.id = uuid4()
        sub.parent_id = parent.id

        fig = render_gantt([parent, sub], today=today)
        ytick_labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
        # Only the parent renders.
        assert any("Parent" in lbl for lbl in ytick_labels)
        assert not any("Subtask" in lbl for lbl in ytick_labels)

    def test_no_silent_cap_on_large_lists(self):
        """A 50-item input renders all 50 rows. The previous render
        capped at 25 which dropped half the data without warning."""
        today = date.today()
        items = [
            TodoItem(reminder=f"Task {i:02d}", due_date=today + timedelta(days=i % 14))
            for i in range(50)
        ]
        fig = render_gantt(items, today=today)
        ytick_labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
        assert len(ytick_labels) == 50

    def test_items_without_due_date_still_render(self):
        """Items without a due_date are kept and given a synthetic
        bar window from created_at through today, matching the
        desktop Timeline tab. Filtering them out caused a real
        complaint about missing tasks."""
        today = date.today()
        plain = TodoItem(reminder="No due date task")
        scheduled = TodoItem(reminder="Scheduled task", due_date=today)
        fig = render_gantt([plain, scheduled], today=today)
        ytick_labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
        assert any("No due date task" in lbl for lbl in ytick_labels)
        assert any("Scheduled task" in lbl for lbl in ytick_labels)

    def test_date_range_does_not_filter_rows(self):
        """start_date / end_date are a viewport hint, not a row filter.
        Items outside the requested range still appear in the row list
        — only the x-axis frame is constrained."""
        today = date.today()
        in_range = TodoItem(reminder="Today", due_date=today)
        out_of_range = TodoItem(reminder="Far future", due_date=today + timedelta(days=365))
        fig = render_gantt(
            [in_range, out_of_range],
            today=today,
            start_date=today - timedelta(days=7),
            end_date=today + timedelta(days=7),
        )
        ytick_labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
        assert any("Today" in lbl for lbl in ytick_labels)
        assert any("Far future" in lbl for lbl in ytick_labels)


class TestGanttWorkOverlay:
    """The work-done overlay on the Gantt export shows pomodoro and
    stopwatch time as horizontally stacked segments in a top-half
    band over the lifecycle bar, so retrospective exports communicate
    actual work performed instead of looking empty when planned
    windows are sub-day."""

    def test_overlay_present_for_pomodoro(self):
        today = date.today()
        item = TodoItem(reminder="Pom task", due_date=today)
        item.pomodoro_count = 3
        item.work_duration = 25  # 75 minutes total
        item.time_spent = 75 * 60

        fig = render_gantt([item], today=today)
        # Find rectangles painted in the pomodoro orange.
        from pytodo_qt.core.chart_export import _COLOR_POMODORO

        pom_color_lower = _COLOR_POMODORO.lower()
        pom_patches = [
            p
            for p in fig.axes[0].patches
            if hasattr(p, "get_facecolor")
            and _hex_from_rgba(p.get_facecolor()).lower() == pom_color_lower
        ]
        assert len(pom_patches) >= 1

    def test_overlay_present_for_stopwatch(self):
        today = date.today()
        item = TodoItem(reminder="Stopwatch task", due_date=today)
        item.pomodoro_count = 0  # all stopwatch
        item.time_spent = 45 * 60  # 45 minutes via stopwatch

        fig = render_gantt([item], today=today)
        from pytodo_qt.core.chart_export import _COLOR_STOPWATCH

        sw_color_lower = _COLOR_STOPWATCH.lower()
        sw_patches = [
            p
            for p in fig.axes[0].patches
            if hasattr(p, "get_facecolor")
            and _hex_from_rgba(p.get_facecolor()).lower() == sw_color_lower
        ]
        assert len(sw_patches) >= 1

    def test_overlay_present_for_both(self):
        today = date.today()
        item = TodoItem(reminder="Mixed work", due_date=today)
        item.pomodoro_count = 2
        item.work_duration = 25  # 50 minutes pomodoro
        item.time_spent = 80 * 60  # 80 minutes total → 30 minutes stopwatch

        fig = render_gantt([item], today=today)
        from pytodo_qt.core.chart_export import _COLOR_POMODORO, _COLOR_STOPWATCH

        all_colors = [
            _hex_from_rgba(p.get_facecolor()).lower()
            for p in fig.axes[0].patches
            if hasattr(p, "get_facecolor")
        ]
        assert _COLOR_POMODORO.lower() in all_colors
        assert _COLOR_STOPWATCH.lower() in all_colors

    def test_no_overlay_when_no_work(self):
        today = date.today()
        item = TodoItem(reminder="No work", due_date=today)
        item.pomodoro_count = 0
        item.time_spent = 0

        fig = render_gantt([item], today=today)
        from pytodo_qt.core.chart_export import _COLOR_POMODORO, _COLOR_STOPWATCH

        all_colors = [
            _hex_from_rgba(p.get_facecolor()).lower()
            for p in fig.axes[0].patches
            if hasattr(p, "get_facecolor")
        ]
        assert _COLOR_POMODORO.lower() not in all_colors
        assert _COLOR_STOPWATCH.lower() not in all_colors


class TestGanttEventMarkers:
    """Items with an event_date carry a magenta diamond milestone
    marker — the traditional Gantt vocabulary for a deadline anchor
    that's distinct from the work window."""

    def test_event_date_produces_marker(self):
        from datetime import time as _time

        today = date.today()
        item = TodoItem(reminder="Event task", due_date=today, due_time=_time(14, 0))
        item.event_date = today + timedelta(days=5)

        fig = render_gantt([item], today=today)
        ax = fig.axes[0]
        # The scatter call adds at least one collection with diamond
        # markers — verify by checking the collection count grew
        # (>= 1) and that at least one collection's offset exists.
        assert len(ax.collections) >= 1
        any_diamond = any(len(c.get_offsets()) > 0 for c in ax.collections)
        assert any_diamond

    def test_no_event_date_no_marker(self):
        today = date.today()
        item = TodoItem(reminder="Plain task", due_date=today)
        item.event_date = None

        fig = render_gantt([item], today=today)
        ax = fig.axes[0]
        # No event marker collection should be created when no items
        # carry an event_date.
        non_empty = [c for c in ax.collections if len(c.get_offsets()) > 0]
        assert len(non_empty) == 0


def _hex_from_rgba(rgba) -> str:
    """Convert a matplotlib RGBA tuple to a #rrggbb hex string."""
    r, g, b = rgba[0], rgba[1], rgba[2]
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


class TestGanttTwoZoneRendering:
    """Two-zone rendering for completed bars based on completed_at."""

    def test_completed_late_draws_overflow_zone(self):
        """A late-completed item gets a hatched late-overflow zone past
        due_end. The bar count increases by 1 for the deviation patch."""
        from datetime import datetime, time

        today = date.today()
        item = TodoItem(
            reminder="Late task",
            due_date=today,
            due_time=time(15, 0),
            estimated_minutes=120,
            complete=True,
        )
        # Completed 2 hours after due_time
        item.completed_at = int(datetime.combine(today, time(17, 0)).timestamp() * 1000)

        fig = render_gantt([item])
        ax = fig.axes[0]
        # Two patches for this item: planned span + late overflow zone.
        # The bar count for a single late item is 2.
        # (We can't easily count patches by category, but we can verify at
        # least one patch with a hatch pattern exists for the late case.)
        hatched = [p for p in ax.patches if p.get_hatch()]
        assert len(hatched) >= 1, "expected at least one hatched late-overflow patch"

    def test_completed_early_draws_surplus_zone(self):
        """An early-completed item gets a translucent surplus zone."""
        from datetime import datetime, time

        today = date.today()
        item = TodoItem(
            reminder="Early task",
            due_date=today,
            due_time=time(15, 0),
            estimated_minutes=120,
            complete=True,
        )
        # Completed 30 min before due_time, well into the planned window
        item.completed_at = int(datetime.combine(today, time(14, 30)).timestamp() * 1000)

        fig = render_gantt([item])
        ax = fig.axes[0]
        # Should have at least 2 patches: solid planned span + translucent surplus
        patches = [p for p in ax.patches if hasattr(p, "get_alpha")]
        # The surplus zone uses alpha 0.45; the main bar uses 0.85
        translucent = [p for p in patches if p.get_alpha() and p.get_alpha() < 0.6]
        assert len(translucent) >= 1, "expected at least one translucent surplus patch"

    def test_completed_unknown_no_two_zone(self):
        """A completed item with NULL completed_at renders as a single bar
        (no two-zone) since we don't know when it was finished."""
        from datetime import time

        today = date.today()
        item = TodoItem(
            reminder="Unknown completion",
            due_date=today,
            due_time=time(15, 0),
            estimated_minutes=120,
            complete=True,
        )
        item.completed_at = None

        fig = render_gantt([item])
        ax = fig.axes[0]
        # No hatched patches and no special translucent overlays
        hatched = [p for p in ax.patches if p.get_hatch()]
        assert len(hatched) == 0

    def test_active_overdue_renders_with_overdue_color(self):
        """Active overdue items use the OVERDUE_ACTIVE base color."""
        from datetime import time

        from pytodo_qt.core.bar_palette import get_palette
        from pytodo_qt.core.calendar_layout import BarState

        today = date.today()
        item = TodoItem(
            reminder="Overdue task",
            due_date=today - timedelta(days=2),  # past due
            due_time=time(15, 0),
            estimated_minutes=60,
            complete=False,
        )

        fig = render_gantt([item])
        ax = fig.axes[0]
        expected_color = get_palette("light")[BarState.OVERDUE_ACTIVE].base
        # Check that at least one bar has the overdue color
        # (matplotlib stores colors as RGBA tuples; we convert hex to compare)
        from matplotlib.colors import to_rgba

        expected_rgba = to_rgba(expected_color, alpha=0.85)
        bar_colors = [p.get_facecolor() for p in ax.patches if hasattr(p, "get_facecolor")]
        # Allow small floating-point differences in alpha
        matched = any(
            abs(c[0] - expected_rgba[0]) < 0.01
            and abs(c[1] - expected_rgba[1]) < 0.01
            and abs(c[2] - expected_rgba[2]) < 0.01
            for c in bar_colors
        )
        assert matched, f"no bar with OVERDUE_ACTIVE color {expected_color} found"


class TestRenderCompletionTiming:
    """Tests for the new completion timing chart."""

    def test_renders_empty(self, analytics):
        """No completed items in the cohort → returns an empty-message figure."""
        fig = render_completion_timing(analytics)
        assert fig is not None

    def test_renders_with_data(self, sample_storage):
        """A populated cohort produces a real chart with two panels."""
        from datetime import datetime, time

        from pytodo_qt.core.models import create_todo_list

        # Use the existing storage to insert items so the analytics service
        # has something to query.
        storage = sample_storage
        lst = create_todo_list("Timing test")
        storage.save_list(lst)
        today = date.today()

        # Three early, one ontime, two late
        for i, hour_offset in enumerate([-1, -2, -1, 0, 1, 2]):
            item = TodoItem(
                reminder=f"Item {i}",
                due_date=today,
                due_time=time(15, 0),
                complete=True,
            )
            item.completed_at = int(
                datetime.combine(today, time(15 + hour_offset, 0)).timestamp() * 1000
            )
            storage.save_item(lst.id, item)

        analytics = AnalyticsService(storage.connection)
        fig = render_completion_timing(
            analytics,
            list_id=lst.id,
            start_date=today,
            end_date=today,
        )
        assert fig is not None
        # Two panels: cohort breakdown bar chart + per-item scatter
        assert len(fig.axes) >= 2

    def test_export_png(self, analytics, tmp_path):
        """The new chart can be exported as PNG."""
        fig = render_completion_timing(analytics)
        out = tmp_path / "timing.png"
        export_png(fig, out)
        assert out.exists()
        assert out.stat().st_size > 0


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

    def test_export_pdf_includes_timing_chart(self, sample_items, analytics, tmp_path):
        """Step 5: timing chart is part of the default export set."""
        out = tmp_path / "with-timing.pdf"
        export_pdf_report(analytics, sample_items, out, include={"timing"})
        assert out.exists()
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
