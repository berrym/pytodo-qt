"""Comprehensive tests for CalendarViewWidget and all sub-views.

Covers: CalendarViewWidget, _TimelineTasksWidget, _TimelineDailyWidget,
_TimelineProductivityWidget, _TimelineAccuracyWidget, _CalendarModel,
_WeekModel, _CalendarDelegate, _WeekDelegate, _UnscheduledPanel,
drag-and-drop, sub-view switching, active session projection, tooltips.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from PyQt6.QtCore import Qt

from pytodo_qt.core.models import (
    create_todo_item,
    create_todo_list,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def todo_list():
    """Create a TodoList with assorted items for testing."""
    lst = create_todo_list("Test List")
    today = date.today()

    # Item with due date (today)
    item1 = create_todo_item("Task due today")
    item1.due_date = today
    item1.priority = 1
    item1.time_spent = 1500
    item1.pomodoro_count = 1
    item1.estimated_pomodoros = 4
    lst.add_item(item1)

    # Overdue item
    item2 = create_todo_item("Overdue task")
    item2.due_date = today - timedelta(days=3)
    item2.priority = 2
    lst.add_item(item2)

    # Completed item
    item3 = create_todo_item("Done task")
    item3.due_date = today
    item3.complete = True
    lst.add_item(item3)

    # Unscheduled item (no due date)
    item4 = create_todo_item("No date task")
    item4.priority = 3
    lst.add_item(item4)

    # Item with stopwatch time
    item5 = create_todo_item("Stopwatch task")
    item5.due_date = today + timedelta(days=2)
    item5.time_spent = 3600
    item5.estimated_minutes = 90
    lst.add_item(item5)

    # Item with per-task work duration
    item6 = create_todo_item("Custom duration task")
    item6.due_date = today + timedelta(days=1)
    item6.work_duration = 50
    item6.break_duration = 10
    item6.estimated_pomodoros = 3
    item6.pomodoro_count = 1
    item6.time_spent = 3000
    lst.add_item(item6)

    return lst


@pytest.fixture()
def calendar_widget(qtbot, todo_list):
    """Create a CalendarViewWidget with test data."""
    from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

    w = CalendarViewWidget()
    qtbot.addWidget(w)
    w.set_list(todo_list)
    return w


# ---------------------------------------------------------------------------
# CalendarViewWidget — sub-view switching
# ---------------------------------------------------------------------------


class TestSubViewSwitching:
    def test_initial_sub_view(self, calendar_widget):
        """Default sub-view should be week (or whatever config says)."""
        assert calendar_widget._sub_view in (0, 1, 2, 3)

    def test_switch_to_timeline(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_TIMELINE)
        assert calendar_widget._sub_view == calendar_widget.SUB_TIMELINE
        assert not calendar_widget._unscheduled.isVisible()
        assert not calendar_widget._timeline_pill_frame.isHidden()

    def test_switch_to_month(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_MONTH)
        assert calendar_widget._sub_view == calendar_widget.SUB_MONTH
        assert not calendar_widget._unscheduled.isHidden()
        assert calendar_widget._timeline_pill_frame.isHidden()

    def test_switch_to_week(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_WEEK)
        assert calendar_widget._sub_view == calendar_widget.SUB_WEEK

    def test_switch_to_day(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_DAY)
        assert calendar_widget._sub_view == calendar_widget.SUB_DAY

    def test_timeline_sub_view_switching(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_TIMELINE)
        for idx in range(4):
            calendar_widget._set_timeline_sub_view(idx)
            assert calendar_widget._tl_sub_view == idx

    def test_timeline_nav_disabled_for_static_views(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_TIMELINE)
        # Productivity (2) and Accuracy (3) should disable nav
        calendar_widget._set_timeline_sub_view(2)
        assert not calendar_widget._prev_btn.isEnabled()
        assert not calendar_widget._next_btn.isEnabled()
        # Tasks (0) should enable nav
        calendar_widget._set_timeline_sub_view(0)
        assert calendar_widget._prev_btn.isEnabled()


# ---------------------------------------------------------------------------
# CalendarViewWidget — navigation
# ---------------------------------------------------------------------------


class TestNavigation:
    def test_navigate_prev_month(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_MONTH)
        # Use a safe date (not 31st which doesn't exist in all months)
        calendar_widget._current_date = date(2026, 3, 15)
        calendar_widget._navigate_prev()
        assert calendar_widget._current_date.month == 2

    def test_navigate_next_month(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_MONTH)
        calendar_widget._current_date = date(2026, 3, 15)
        calendar_widget._navigate_next()
        assert calendar_widget._current_date.month == 4

    def test_navigate_today(self, calendar_widget):
        calendar_widget._current_date = date(2020, 1, 1)
        calendar_widget._navigate_today()
        assert calendar_widget._current_date == date.today()

    def test_navigate_week(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_WEEK)
        original = calendar_widget._current_date
        calendar_widget._navigate_next()
        assert calendar_widget._current_date == original + timedelta(weeks=1)

    def test_navigate_day(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_DAY)
        original = calendar_widget._current_date
        calendar_widget._navigate_next()
        assert calendar_widget._current_date == original + timedelta(days=1)

    def test_navigate_timeline_daily(self, calendar_widget):
        calendar_widget._set_sub_view(calendar_widget.SUB_TIMELINE)
        calendar_widget._set_timeline_sub_view(1)  # Daily
        original = calendar_widget._current_date
        calendar_widget._navigate_next()
        assert calendar_widget._current_date == original + timedelta(weeks=1)


# ---------------------------------------------------------------------------
# CalendarViewWidget — data flow
# ---------------------------------------------------------------------------


class TestDataFlow:
    def test_set_list(self, calendar_widget, todo_list):
        calendar_widget.set_list(todo_list)
        assert calendar_widget._todo_list is todo_list

    def test_set_list_none(self, calendar_widget):
        calendar_widget.set_list(None)
        assert calendar_widget._todo_list is None

    def test_refresh_no_crash(self, calendar_widget):
        calendar_widget.refresh()

    def test_set_filter(self, calendar_widget):
        from pytodo_qt.gui.widgets.search_filter import FilterState

        fs = FilterState(priority=1)
        calendar_widget.set_filter(fs)
        assert calendar_widget._filter_state is fs

    def test_get_selected_item_ids_empty(self, calendar_widget):
        assert calendar_widget.get_selected_item_ids() == []

    def test_set_active_session(self, calendar_widget, todo_list):
        item = list(todo_list.items.values())[0]
        calendar_widget.set_active_session(item.id, 120, "work")
        # Should not crash

    def test_set_active_session_none(self, calendar_widget):
        calendar_widget.set_active_session(None)


# ---------------------------------------------------------------------------
# _TimelineTasksWidget
# ---------------------------------------------------------------------------


class TestTimelineTasksWidget:
    @pytest.fixture()
    def tasks_widget(self, qtbot, todo_list):
        from pytodo_qt.gui.widgets.calendar_view import _TimelineTasksWidget

        w = _TimelineTasksWidget()
        qtbot.addWidget(w)
        w.set_data(list(todo_list.active_items()), date.today(), todo_list)
        return w

    def test_creation(self, tasks_widget):
        assert tasks_widget._span_bar is not None
        assert tasks_widget._pom_bar is not None
        assert tasks_widget._sw_bar is not None

    def test_batched_arrays(self, tasks_widget):
        n = len(tasks_widget._items)
        assert tasks_widget._pom_widths is not None
        assert len(tasks_widget._pom_widths) == n

    def test_item_indices(self, tasks_widget):
        for item in tasks_widget._items:
            assert item.id in tasks_widget._item_indices

    def test_set_active_session_updates(self, tasks_widget):
        item = tasks_widget._items[0]
        old_width = float(tasks_widget._pom_widths[0])
        tasks_widget.set_active_session(item.id, 600, "work")
        # Width should have changed (600 seconds of work added)
        new_width = float(tasks_widget._pom_widths[0])
        assert new_width >= old_width

    def test_set_active_session_none(self, tasks_widget):
        tasks_widget.set_active_session(None)
        # Should not crash

    def test_rebuild_on_item_change(self, tasks_widget):
        item1 = tasks_widget._items[0]
        item2 = tasks_widget._items[1] if len(tasks_widget._items) > 1 else item1
        tasks_widget.set_active_session(item1.id, 60, "work")
        # Changing active item triggers rebuild
        tasks_widget.set_active_session(item2.id, 60, "work")

    def test_empty_data(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _TimelineTasksWidget

        w = _TimelineTasksWidget()
        qtbot.addWidget(w)
        w.set_data([], date.today(), None)
        assert w._span_bar is None

    def test_tooltip_build(self, tasks_widget):
        item = tasks_widget._items[0]
        tooltip = tasks_widget._build_tooltip(item)
        assert item.reminder in tooltip

    def test_row_from_y(self, tasks_widget):
        n = len(tasks_widget._items)
        assert tasks_widget._row_from_y(float(n - 1)) == 0
        assert tasks_widget._row_from_y(-10.0) == -1

    def test_leave_hides_tooltip(self, tasks_widget):
        tasks_widget._tooltip_label.show()
        tasks_widget.leaveEvent(None)
        assert tasks_widget._tooltip_label.isHidden()

    def test_hide_hides_tooltip(self, tasks_widget):
        tasks_widget._tooltip_label.show()
        tasks_widget.hideEvent(None)
        assert tasks_widget._tooltip_label.isHidden()


# ---------------------------------------------------------------------------
# _TimelineDailyWidget
# ---------------------------------------------------------------------------


class TestTimelineDailyWidget:
    @pytest.fixture()
    def daily_widget(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _TimelineDailyWidget

        w = _TimelineDailyWidget()
        qtbot.addWidget(w)
        return w

    def test_creation(self, daily_widget):
        assert daily_widget._pom_bar is None  # No data yet
        assert daily_widget._analytics is None

    def test_rebuild_no_analytics(self, daily_widget):
        daily_widget.rebuild()
        # Should show empty state, not crash

    def test_rebuild_with_analytics(self, daily_widget, tmp_path):

        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.database import DatabaseStorage

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()
        analytics = AnalyticsService(storage.connection)
        daily_widget.set_analytics(analytics)
        daily_widget.rebuild()
        assert daily_widget._pom_bar is not None
        storage.close()

    def test_set_active_session(self, daily_widget, tmp_path):

        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.database import DatabaseStorage

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()
        analytics = AnalyticsService(storage.connection)
        daily_widget.set_analytics(analytics)
        daily_widget.rebuild()
        daily_widget.set_active_session(300, "work")
        # Should not crash; pom bar updated
        storage.close()

    def test_set_current_date(self, daily_widget, tmp_path):
        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.database import DatabaseStorage

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()
        daily_widget.set_analytics(AnalyticsService(storage.connection))
        daily_widget.set_current_date(date(2026, 3, 15))
        assert daily_widget._current_date == date(2026, 3, 15)
        storage.close()

    def test_gradient_brushes_created(self, daily_widget):
        assert daily_widget._pom_brush is not None
        assert daily_widget._sw_brush is not None
        assert daily_widget._pom_pen is not None


# ---------------------------------------------------------------------------
# _TimelineProductivityWidget
# ---------------------------------------------------------------------------


class TestTimelineProductivityWidget:
    @pytest.fixture()
    def prod_widget(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _TimelineProductivityWidget

        w = _TimelineProductivityWidget()
        qtbot.addWidget(w)
        return w

    def test_creation(self, prod_widget):
        assert prod_widget._block_pom_bars == []

    def test_alpha_bucketed_brushes(self, prod_widget):
        assert len(prod_widget._pom_brushes) == 9
        assert len(prod_widget._sw_brushes) == 9

    def test_alpha_brush_index(self, prod_widget):
        assert prod_widget._alpha_brush_index(0, 100) == 0
        assert prod_widget._alpha_brush_index(100, 100) == 8

    def test_rebuild_no_analytics(self, prod_widget):
        prod_widget.rebuild()
        # Should show empty state

    def test_rebuild_with_data(self, prod_widget, tmp_path):
        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.database import DatabaseStorage
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()
        # Insert a session so time_block_analysis has data
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2026-03-30T14:00:00",
                end_time="2026-03-30T14:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date="2026-03-30",
            )
        )
        analytics = AnalyticsService(storage.connection)
        prod_widget.set_analytics(analytics)
        prod_widget.rebuild()
        assert len(prod_widget._block_pom_bars) == 12
        assert len(prod_widget._block_sw_bars) == 12
        storage.close()

    def test_set_active_session(self, prod_widget, tmp_path):
        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.database import DatabaseStorage
        from pytodo_qt.core.models import FocusSession

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()
        storage.save_focus_session(
            FocusSession(
                item_id=uuid4(),
                list_id=uuid4(),
                start_time="2026-03-30T14:00:00",
                end_time="2026-03-30T14:25:00",
                duration_seconds=1500,
                completed=True,
                session_type="work",
                date="2026-03-30",
            )
        )
        prod_widget.set_analytics(AnalyticsService(storage.connection))
        prod_widget.rebuild()
        prod_widget.set_active_session(120, "stopwatch")
        # Should not crash
        storage.close()


# ---------------------------------------------------------------------------
# _TimelineAccuracyWidget
# ---------------------------------------------------------------------------


class TestTimelineAccuracyWidget:
    @pytest.fixture()
    def accuracy_widget(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _TimelineAccuracyWidget

        w = _TimelineAccuracyWidget()
        qtbot.addWidget(w)
        return w

    def test_creation(self, accuracy_widget):
        assert accuracy_widget._scatter is None

    def test_rebuild_no_analytics(self, accuracy_widget):
        accuracy_widget.rebuild()

    def test_rebuild_with_data(self, accuracy_widget, tmp_path):
        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.database import DatabaseStorage

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()
        lst = create_todo_list("Test")
        storage.save_list(lst)
        item = create_todo_item("Estimated task")
        item.estimated_pomodoros = 4
        item.time_spent = 5000
        storage.save_item(lst.id, item)

        analytics = AnalyticsService(storage.connection)
        accuracy_widget.set_analytics(analytics)
        accuracy_widget.rebuild()
        assert accuracy_widget._scatter is not None
        assert accuracy_widget._ref_line is not None
        storage.close()

    def test_set_active_session(self, accuracy_widget, tmp_path):
        from pytodo_qt.core.analytics import AnalyticsService
        from pytodo_qt.core.database import DatabaseStorage

        storage = DatabaseStorage(tmp_path / "test.db")
        storage.open()
        lst = create_todo_list("Test")
        storage.save_list(lst)
        item = create_todo_item("Est task")
        item.estimated_pomodoros = 2
        item.time_spent = 1000
        storage.save_item(lst.id, item)

        analytics = AnalyticsService(storage.connection)
        accuracy_widget.set_analytics(analytics)
        accuracy_widget.rebuild()
        accuracy_widget.set_active_session(item.id, 300, "work")
        # Scatter should still exist after update
        assert accuracy_widget._scatter is not None
        storage.close()

    def test_category_brushes_precreated(self, accuracy_widget):
        assert accuracy_widget._brush_over is not None
        assert accuracy_widget._brush_under is not None
        assert accuracy_widget._brush_accurate is not None


# ---------------------------------------------------------------------------
# _CalendarModel (Month view data model)
# ---------------------------------------------------------------------------


class TestCalendarModel:
    @pytest.fixture()
    def model(self):
        from pytodo_qt.gui.widgets.calendar_view import _CalendarModel

        m = _CalendarModel()
        return m

    def test_initial_state(self, model):
        assert model.columnCount() == 7
        assert model.rowCount() >= 4  # At least 4 weeks

    def test_set_month(self, model):
        model.set_month(2026, 3)
        assert model.rowCount() >= 4

    def test_set_items(self, model):
        today = date.today()
        item = create_todo_item("Test")
        item.due_date = today
        model.set_items({today: [item]})
        # Should not crash


# ---------------------------------------------------------------------------
# _WeekModel
# ---------------------------------------------------------------------------


class TestWeekModel:
    @pytest.fixture()
    def model(self):
        from pytodo_qt.gui.widgets.calendar_view import _WeekModel

        m = _WeekModel()
        return m

    def test_initial_state(self, model):
        assert model.columnCount() == 7
        assert model.rowCount() == 25  # all-day + 24 hours

    def test_set_week(self, model):
        model.set_week(date.today())
        dates = model.week_dates()
        assert len(dates) == 7

    def test_set_items(self, model):
        today = date.today()
        item = create_todo_item("Test")
        item.due_date = today
        model.set_items({today: [item]})


# ---------------------------------------------------------------------------
# _NowOverlay
# ---------------------------------------------------------------------------


class TestNowOverlay:
    @pytest.fixture()
    def table(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekModel,
            _WeekTableView,
        )

        view = _WeekTableView()
        view.setModel(_WeekModel())
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()
        return view

    def test_construction(self, table):
        from pytodo_qt.gui.widgets.calendar_view import _NowOverlay

        overlay = _NowOverlay(table)
        assert overlay.parent() is table.viewport()

    def test_overlay_is_mouse_transparent(self, table):
        from pytodo_qt.gui.widgets.calendar_view import _NowOverlay

        overlay = _NowOverlay(table)
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def test_overlay_geometry_matches_viewport(self, table):
        from pytodo_qt.gui.widgets.calendar_view import _NowOverlay

        overlay = _NowOverlay(table)
        viewport = table.viewport()
        assert viewport is not None
        assert overlay.geometry() == viewport.rect()

    def test_paint_does_not_crash_with_no_items(self, table, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _NowOverlay

        overlay = _NowOverlay(table)
        overlay.show()
        qtbot.wait(50)
        # Force a paint event
        overlay.repaint()

    def test_paint_with_items_due_today(self, table, qtbot):
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _NowOverlay

        today = date.today()
        item = create_todo_item("Test")
        item.due_date = today
        item.due_time = time(23, 0)  # later today
        model = table.model()
        model.set_items({today: [item]})

        overlay = _NowOverlay(table)
        overlay.show()
        qtbot.wait(50)
        overlay.repaint()

    def test_urgency_color_overdue_red(self, table):
        from pytodo_qt.gui.widgets.calendar_view import _NowOverlay

        overlay = _NowOverlay(table)
        c = overlay._urgency_color(-5)
        assert c.red() > c.green()  # Red dominates

    def test_urgency_color_under_15min_red(self, table):
        from pytodo_qt.gui.widgets.calendar_view import _NowOverlay

        overlay = _NowOverlay(table)
        c = overlay._urgency_color(10)
        assert c.red() > c.green()

    def test_urgency_color_under_60min_amber(self, table):
        from pytodo_qt.gui.widgets.calendar_view import _NowOverlay

        overlay = _NowOverlay(table)
        c = overlay._urgency_color(45)
        # Amber: high red, high green, low blue
        assert c.red() > 200
        assert c.green() > 100

    def test_urgency_color_plenty_green(self, table):
        from pytodo_qt.gui.widgets.calendar_view import _NowOverlay

        overlay = _NowOverlay(table)
        c = overlay._urgency_color(180)
        # Green dominates
        assert c.green() > c.red()


# ---------------------------------------------------------------------------
# _UnscheduledPanel
# ---------------------------------------------------------------------------


class TestUnscheduledPanel:
    @pytest.fixture()
    def panel(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _UnscheduledPanel

        p = _UnscheduledPanel()
        qtbot.addWidget(p)
        return p

    def test_empty(self, panel):
        panel.set_items([])

    def test_with_items(self, panel):
        item1 = create_todo_item("No date 1")
        item2 = create_todo_item("No date 2")
        panel.set_items([item1, item2])

    def test_with_todo_list(self, panel, todo_list):
        items = [i for i in todo_list.items.values() if i.due_date is None]
        panel.set_items(items, todo_list=todo_list)


# ---------------------------------------------------------------------------
# Gradient styles
# ---------------------------------------------------------------------------


class TestGradientStyles:
    def test_tasks_widget_styles(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _TimelineTasksWidget

        w = _TimelineTasksWidget()
        qtbot.addWidget(w)
        assert w._pom_brush is not None
        assert w._sw_brush is not None
        assert w._est_brush is not None
        assert w._span_brush is not None

    def test_daily_widget_styles(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _TimelineDailyWidget

        w = _TimelineDailyWidget()
        qtbot.addWidget(w)
        assert w._pom_brush is not None
        assert w._trend_pen is not None

    def test_productivity_widget_styles(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _TimelineProductivityWidget

        w = _TimelineProductivityWidget()
        qtbot.addWidget(w)
        assert len(w._pom_brushes) == 9
        assert w._pom_pen is not None


# ---------------------------------------------------------------------------
# Per-task work duration in charts
# ---------------------------------------------------------------------------


class TestPerTaskDuration:
    def test_item_work_mins_helper(self):
        from pytodo_qt.gui.widgets.calendar_view import _item_work_mins

        item = create_todo_item("Custom")
        item.work_duration = 50
        assert _item_work_mins(item, 25) == 50

    def test_item_work_mins_default(self):
        from pytodo_qt.gui.widgets.calendar_view import _item_work_mins

        item = create_todo_item("Default")
        item.work_duration = 0
        assert _item_work_mins(item, 25) == 25

    def test_tasks_widget_uses_per_task(self, qtbot, todo_list):
        from pytodo_qt.gui.widgets.calendar_view import _TimelineTasksWidget

        w = _TimelineTasksWidget()
        qtbot.addWidget(w)
        w.set_data(list(todo_list.active_items()), date.today(), todo_list)

        # Find the custom duration item (work_duration=50)
        for item in w._items:
            if item.work_duration == 50:
                idx = w._item_indices[item.id]
                # The estimate bar should reflect 50 min per session
                # item has estimated_pomodoros=3, so est = 3 * 50 = 150 min
                assert w._est_widths_arr is not None
                est_days = w._est_widths_arr[idx]
                # 150 min / 480 min_per_day = 0.3125 days
                assert abs(est_days - 0.3125) < 0.01
                break
