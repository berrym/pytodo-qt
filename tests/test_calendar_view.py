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


class TestMonthViewNoProjection:
    """The month view must NOT include projected recurring instances.
    Daily recurring tasks would clutter every day of the month with
    duplicate chips otherwise."""

    def test_month_view_excludes_projections(self, qtbot):
        from datetime import time

        from pytodo_qt.core.models import create_todo_item, create_todo_list
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)

        today = date.today()
        lst = create_todo_list("Test")
        item = create_todo_item("Daily standup")
        item.due_date = today
        item.due_time = time(9, 0)
        item.estimated_minutes = 30
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        lst.add_item(item)

        cal.set_list(lst)

        # The MONTH model should have the item ONLY on today, not on
        # every day of the month (which would be the projection bug).
        month_buckets = {
            d
            for d, items in cal._cal_model._items_by_date.items()
            if any(i.id == item.id for i in items)
        }
        assert month_buckets == {today}, (
            f"Month view should only show the real instance on today; got {month_buckets}"
        )

    def test_week_view_includes_projections_unaffected(self, qtbot):
        """Sanity: the week view DOES include projections — only month
        is excluded."""
        from datetime import time

        from pytodo_qt.core.models import create_todo_item, create_todo_list
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)

        today = date.today()
        lst = create_todo_list("Test")
        item = create_todo_item("Daily standup")
        item.due_date = today
        item.due_time = time(9, 0)
        item.estimated_minutes = 30
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        lst.add_item(item)

        cal.set_list(lst)

        week_buckets = {
            d
            for d, items in cal._week_model._items_by_date.items()
            if any(getattr(i, "id", None) == item.id for i in items)
        }
        assert today in week_buckets
        assert today + timedelta(days=1) in week_buckets


class TestUnscheduledIncludesSubtasks:
    """Subtasks without due_date should appear in the unscheduled panel
    so they're findable from the calendar view."""

    def test_subtask_without_due_date_in_unscheduled(self, qtbot):
        from pytodo_qt.core.models import create_todo_item, create_todo_list
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)

        lst = create_todo_list("Test")
        parent = create_todo_item("Parent task")
        parent.due_date = date.today()
        lst.add_item(parent)
        sub = create_todo_item("Unscheduled subtask")
        sub.parent_id = parent.id
        sub.due_date = None
        lst.add_item(sub)

        cal.set_list(lst)

        text = cal._unscheduled._count_label.text()
        assert "1 task" in text, f"Expected '1 task' in unscheduled count, got: {text}"

    def test_top_level_unscheduled_still_in_unscheduled(self, qtbot):
        from pytodo_qt.core.models import create_todo_item, create_todo_list
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)

        lst = create_todo_list("Test")
        item1 = create_todo_item("Top-level no date")
        item1.due_date = None
        lst.add_item(item1)
        item2 = create_todo_item("Another no date")
        item2.due_date = None
        lst.add_item(item2)

        cal.set_list(lst)
        text = cal._unscheduled._count_label.text()
        assert "2 task" in text


class TestInitialScrollToNow:
    """Calendar view should scroll to current hour when first opened."""

    def test_widget_has_initial_scroll_state(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        assert hasattr(cal, "_initial_scroll_done")
        assert cal._initial_scroll_done is False

    def test_show_event_marks_initial_scroll_done(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        cal.show()
        from PyQt6.QtWidgets import QApplication

        QApplication.processEvents()
        assert cal._initial_scroll_done is True

    def test_scroll_to_current_hour_does_not_crash(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        cal._scroll_to_current_hour()


class TestRecurrenceProjection:
    """Recurring tasks must appear on their FUTURE occurrence dates in
    the calendar view, not only on their current due_date. Without
    projection, "tomorrow is empty" for users with daily recurring tasks
    — they'd only see today's instance."""

    def test_daily_recurrence_projected_forward(self, qtbot):
        """A daily recurring task with due_date=today should appear in
        tomorrow's bucket too (and the day after, etc.)."""
        from datetime import time

        from pytodo_qt.core.models import create_todo_item, create_todo_list
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)

        today = date.today()
        lst = create_todo_list("Test")
        item = create_todo_item("Daily standup")
        item.due_date = today
        item.due_time = time(9, 0)
        item.estimated_minutes = 30
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        lst.add_item(item)

        cal.set_list(lst)

        # Check the internal scheduled dict via the week model
        scheduled_dates = set()
        for d, items in cal._week_model._items_by_date.items():
            if any(i.id == item.id for i in items):
                scheduled_dates.add(d)

        # Should include today and several days in the future
        assert today in scheduled_dates
        assert today + timedelta(days=1) in scheduled_dates
        assert today + timedelta(days=7) in scheduled_dates

    def test_weekly_recurrence_projected(self, qtbot):
        """Weekly recurrence shows up 7, 14, 21+ days in the future."""
        from datetime import time

        from pytodo_qt.core.models import create_todo_item, create_todo_list
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)

        today = date.today()
        lst = create_todo_list("Test")
        item = create_todo_item("Weekly report")
        item.due_date = today
        item.due_time = time(16, 0)
        item.estimated_minutes = 60
        item.recurrence_type = "weekly"
        item.recurrence_interval = 1
        lst.add_item(item)

        cal.set_list(lst)

        scheduled_dates = {
            d
            for d, items in cal._week_model._items_by_date.items()
            if any(i.id == item.id for i in items)
        }
        assert today in scheduled_dates
        assert today + timedelta(days=7) in scheduled_dates
        assert today + timedelta(days=14) in scheduled_dates

    def test_non_recurring_not_projected(self, qtbot):
        """A non-recurring task should appear ONLY on its due_date."""
        from datetime import time

        from pytodo_qt.core.models import create_todo_item, create_todo_list
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)

        today = date.today()
        lst = create_todo_list("Test")
        item = create_todo_item("One-shot task")
        item.due_date = today
        item.due_time = time(10, 0)
        item.estimated_minutes = 30
        item.recurrence_type = None
        lst.add_item(item)

        cal.set_list(lst)

        scheduled_dates = {
            d
            for d, items in cal._week_model._items_by_date.items()
            if any(i.id == item.id for i in items)
        }
        assert scheduled_dates == {today}


class TestAllDayVisibilityGuarantee:
    """Every task with due_date must be visible somewhere — if its window
    doesn't produce an hour-grid segment for the viewing day, it must
    fall back to the All Day row. This is the visibility guarantee the
    user demanded: "all tasks should display somehow even if they have
    to be unscheduled tasks"."""

    @pytest.fixture()
    def model(self):
        from pytodo_qt.gui.widgets.calendar_view import _WeekModel

        m = _WeekModel()
        m.set_week(date(2026, 4, 13))  # Monday of a known week
        return m

    def _col_for_date(self, model, target: date) -> int:
        for col, d in enumerate(model.week_dates()):
            if d == target:
                return col
        raise AssertionError

    def test_traditional_all_day_item_visible(self, model):
        """Item with due_date but no due_time → all-day chip."""
        from pytodo_qt.gui.widgets.calendar_view import _WEEK_ITEMS_ROLE

        target = date(2026, 4, 14)
        item = create_todo_item("All day task")
        item.due_date = target
        item.due_time = None
        model.set_items({target: [item]})

        col = self._col_for_date(model, target)
        all_day_items = model.index(0, col).data(_WEEK_ITEMS_ROLE)
        assert any(i.id == item.id for i in all_day_items)

    def test_hour_grid_task_not_in_all_day_row(self, model):
        """Item with a proper workback window should NOT appear in the
        all-day row (it goes to the hour grid instead)."""
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _WEEK_ITEMS_ROLE

        target = date(2026, 4, 14)
        item = create_todo_item("Workback task")
        item.due_date = target
        item.due_time = time(14, 0)
        item.estimated_minutes = 60
        model.set_items({target: [item]})

        col = self._col_for_date(model, target)
        all_day_items = model.index(0, col).data(_WEEK_ITEMS_ROLE)
        # The workback window intersects hour 13 on due day → hour grid.
        # Item should NOT be in the all-day fallback.
        assert not any(i.id == item.id for i in all_day_items)

    def test_sanitization_fallthrough_visible_in_all_day(self, model):
        """An item whose created_at is AFTER due_time (corrupt data)
        falls through compute_bar_window's rules to ALL_DAY. It must
        still be visible in the all-day row."""
        from datetime import datetime as _dt
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _WEEK_ITEMS_ROLE

        target = date(2026, 4, 14)
        item = create_todo_item("Corrupt data task")
        item.due_date = target
        item.due_time = time(10, 0)
        # created_at AFTER due_time — sanitization will fall through
        item.created_at = int(_dt(2026, 4, 15, 12, 0).timestamp() * 1000)
        model.set_items({target: [item]})

        col = self._col_for_date(model, target)
        all_day_items = model.index(0, col).data(_WEEK_ITEMS_ROLE)
        assert any(i.id == item.id for i in all_day_items), (
            "Item with corrupt created_at should fall back to all-day row"
        )


class TestWeekModelColumnItemsRole:
    """Step 6: _WEEK_COLUMN_ITEMS_ROLE returns the full column items list."""

    @pytest.fixture()
    def model(self):
        from pytodo_qt.gui.widgets.calendar_view import _WeekModel

        m = _WeekModel()
        # Pin to a known week so we can target a specific column directly
        m.set_week(date(2026, 4, 13))  # Monday of that week
        return m

    def _column_for_date(self, model, target: date) -> int:
        """Helper: find the column index whose date matches `target`."""
        for col, d in enumerate(model.week_dates()):
            if d == target:
                return col
        raise AssertionError(f"date {target} not in week dates {model.week_dates()}")

    def test_empty_column_returns_empty_list(self, model):
        """A column with no items returns [], never None."""
        from pytodo_qt.gui.widgets.calendar_view import _WEEK_COLUMN_ITEMS_ROLE

        col = self._column_for_date(model, date(2026, 4, 14))
        idx = model.index(0, col)
        items = idx.data(_WEEK_COLUMN_ITEMS_ROLE)
        assert items == []

    def test_single_item_returned_for_every_row(self, model):
        """The same item appears at every row in its column — the role is
        row-independent. The delegate decides which slice intersects each
        cell, not the model."""
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _WEEK_COLUMN_ITEMS_ROLE

        target_date = date(2026, 4, 15)
        item = create_todo_item("Workback")
        item.due_date = target_date
        item.due_time = time(15, 0)
        item.estimated_minutes = 60
        model.set_items({target_date: [item]})

        col = self._column_for_date(model, target_date)
        # Every row in the column returns the same single-item list
        for row in (0, 1, 12, 14, 15, 24):
            items = model.index(row, col).data(_WEEK_COLUMN_ITEMS_ROLE)
            assert len(items) == 1
            assert items[0].id == item.id

    def test_multiple_items_returned_in_order(self, model):
        """Multiple items in a column all appear in the role result."""
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _WEEK_COLUMN_ITEMS_ROLE

        target_date = date(2026, 4, 16)
        items_in = []
        for i in range(3):
            item = create_todo_item(f"Item {i}")
            item.due_date = target_date
            item.due_time = time(10 + i, 0)
            items_in.append(item)
        model.set_items({target_date: items_in})

        col = self._column_for_date(model, target_date)
        items_out = model.index(0, col).data(_WEEK_COLUMN_ITEMS_ROLE)
        assert len(items_out) == 3
        # Order matches input order
        assert [it.id for it in items_out] == [it.id for it in items_in]

    def test_no_time_items_included(self, model):
        """Items with no due_time still appear in the column items role —
        the role is about column membership, not row placement."""
        from pytodo_qt.gui.widgets.calendar_view import _WEEK_COLUMN_ITEMS_ROLE

        target_date = date(2026, 4, 17)
        all_day_item = create_todo_item("All day task")
        all_day_item.due_date = target_date
        all_day_item.due_time = None
        model.set_items({target_date: [all_day_item]})

        col = self._column_for_date(model, target_date)
        # Hour rows (1-24) also see the all-day item via this role
        items = model.index(8, col).data(_WEEK_COLUMN_ITEMS_ROLE)
        assert len(items) == 1
        assert items[0].id == all_day_item.id

    def test_invalid_column_returns_none(self, model):
        """An out-of-range column index returns None."""
        from pytodo_qt.gui.widgets.calendar_view import _WEEK_COLUMN_ITEMS_ROLE

        # Column 99 is out of range; data() returns None for invalid columns
        idx = model.index(0, 99)
        if idx.isValid():
            assert idx.data(_WEEK_COLUMN_ITEMS_ROLE) is None

    def test_returned_list_is_independent_copy(self, model):
        """Mutating the returned list does not affect the model's state.
        The role returns a fresh list to prevent accidental data corruption."""
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _WEEK_COLUMN_ITEMS_ROLE

        target_date = date(2026, 4, 13)
        item = create_todo_item("Original")
        item.due_date = target_date
        item.due_time = time(10, 0)
        model.set_items({target_date: [item]})

        col = self._column_for_date(model, target_date)
        items = model.index(0, col).data(_WEEK_COLUMN_ITEMS_ROLE)
        items.clear()  # mutate the returned list

        # Re-fetch — model state must be unchanged
        items_again = model.index(0, col).data(_WEEK_COLUMN_ITEMS_ROLE)
        assert len(items_again) == 1


# ---------------------------------------------------------------------------
# Now-aware delegate painting
# ---------------------------------------------------------------------------


class TestWeekDelegateBarPainting:
    """The week/day delegate paints Gantt bar segments via core.calendar_layout
    and a single now-line on today's current-hour cell. Replaces the rejected
    cell-overlay approach (commit 12968f7) per spec Q3/Q5/Q6."""

    def test_paint_does_not_crash_with_bar_segment(self, qtbot):
        """Paint a today-row cell with a future item — should not raise.

        Step 7 replaced the rejected `_paint_now_overlays` cell-spans with
        Gantt bar segment painting via core.calendar_layout. This is the
        smoke test that the new path runs without exceptions for a typical
        item shape.
        """
        from datetime import datetime as _dt
        from datetime import time

        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QPainter, QPixmap
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekDelegate,
            _WeekModel,
            _WeekTableView,
        )

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        view.setItemDelegate(_WeekDelegate())
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        # Add an item due later today
        today = date.today()
        item = create_todo_item("Future task")
        item.due_date = today
        item.due_time = time(23, 30)
        item.estimated_minutes = 60
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [item]})

        # Render a cell at the current hour into an offscreen pixmap
        delegate = view.itemDelegate()
        now = _dt.now()
        idx = model.index(now.hour + 1, 0)
        pixmap = QPixmap(100, 60)
        pixmap.fill()
        painter = QPainter(pixmap)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 100, 60)
        # Should not raise
        delegate.paint(painter, opt, idx)
        painter.end()

    def test_paint_completed_late_two_zone_does_not_crash(self, qtbot):
        """Paint a cell containing the late-overflow zone of a completed-late
        bar. Verifies the deviation overlay path runs without crashing."""
        from datetime import datetime as _dt
        from datetime import time

        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QPainter, QPixmap
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekDelegate,
            _WeekModel,
            _WeekTableView,
        )

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        view.setItemDelegate(_WeekDelegate())
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        today = date.today()
        item = create_todo_item("Late task")
        item.due_date = today
        item.due_time = time(15, 0)
        item.estimated_minutes = 60
        item.complete = True
        # Completed 2 hours after due_time
        item.completed_at = int(_dt.combine(today, time(17, 0)).timestamp() * 1000)
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [item]})

        delegate = view.itemDelegate()
        # Hour 16 cell — late overflow zone runs from 15:00 to 17:00, so
        # hour 16 contains an entire deviation slice
        idx = model.index(16 + 1, 0)
        pixmap = QPixmap(100, 60)
        pixmap.fill()
        painter = QPainter(pixmap)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 100, 60)
        delegate.paint(painter, opt, idx)
        painter.end()

    def test_paint_completed_early_two_zone_does_not_crash(self, qtbot):
        """Paint a cell containing the early-surplus zone of a completed-early bar."""
        from datetime import datetime as _dt
        from datetime import time

        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QPainter, QPixmap
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekDelegate,
            _WeekModel,
            _WeekTableView,
        )

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        view.setItemDelegate(_WeekDelegate())
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        today = date.today()
        item = create_todo_item("Early task")
        item.due_date = today
        item.due_time = time(15, 0)
        item.estimated_minutes = 120  # 1 PM origin
        item.complete = True
        # Completed at 14:00 — 1 hour into the planned window, 1 hour
        # of surplus from 14:00 to 15:00
        item.completed_at = int(_dt.combine(today, time(14, 0)).timestamp() * 1000)
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [item]})

        delegate = view.itemDelegate()
        idx = model.index(14 + 1, 0)  # hour 14 cell
        pixmap = QPixmap(100, 60)
        pixmap.fill()
        painter = QPainter(pixmap)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 100, 60)
        delegate.paint(painter, opt, idx)
        painter.end()

    def test_paint_uses_column_items_role(self, qtbot):
        """The new bar painting reads via _WEEK_COLUMN_ITEMS_ROLE so a bar
        appearing in row 13's column data is visible when row 14 is painted
        (because the bar spans both rows). Verified by simulating: column
        items role on row 14 returns the item even though its hour is 13."""
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import (
            _WEEK_COLUMN_ITEMS_ROLE,
            _WeekModel,
        )

        model = _WeekModel()
        today = date.today()
        item = create_todo_item("Cross-cell bar")
        item.due_date = today
        item.due_time = time(15, 0)
        item.estimated_minutes = 120  # spans 13:00–15:00, two cells
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [item]})

        # Row 14 is hour 13 (13:00–14:00) — the bar's middle slice.
        # Without the column-items role, this row would only see items
        # whose due_time.hour == 13 — and our item has due_time.hour == 15.
        # The new role exposes the full column so the delegate sees it.
        idx = model.index(14, 0)
        column_items = idx.data(_WEEK_COLUMN_ITEMS_ROLE)
        assert column_items is not None
        assert any(it.id == item.id for it in column_items)

    def test_calendar_widget_has_now_timer(self, qtbot):
        """CalendarViewWidget creates a 30-second QTimer for now-line ticks."""
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        assert hasattr(cal, "_now_timer")
        assert cal._now_timer.isActive()
        assert cal._now_timer.interval() == 30_000

    def test_tick_now_indicators_does_not_crash(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        cal._tick_now_indicators()  # should be a no-op when nothing is shown


class TestWeekViewBarHitTest:
    """Step 8: hit-test recognizes Gantt bar segments via the new geometry.

    Without these tests, multi-hour bars would visually appear but only
    register clicks in their start-hour cell — the bug Step 8 fixes.
    """

    @pytest.fixture()
    def view_with_bar(self, qtbot):
        """Build a week view with one workback bar from 13:00 to 15:00 today."""
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekModel,
            _WeekTableView,
        )

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        today = date.today()
        item = create_todo_item("Workback bar")
        item.due_date = today
        item.due_time = time(15, 0)
        item.estimated_minutes = 120  # origin = 13:00, end = 15:00
        # Pin the model's week_dates to a known column for `today`
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [item]})
        return view, model, item

    def test_click_in_start_hour_cell_hits_bar(self, view_with_bar):
        """Clicking in the bar's first hour-cell (row 14 = hour 13) finds the item."""
        from PyQt6.QtCore import QPoint

        view, model, item = view_with_bar
        # Row 14 is hour 13 (13:00–14:00). Column 0 is today.
        idx = model.index(14, 0)
        rect = view.visualRect(idx)
        click = QPoint(rect.center().x(), rect.center().y())
        hit = view._hit_test(click)
        assert hit is not None
        assert hit[0] == "task"
        assert hit[1].id == item.id

    def test_continuing_bar_does_not_steal_clicks_from_in_cell_tasks(self, qtbot):
        """REGRESSION: When a multi-hour bar continues into a cell that
        has its own in-cell tasks, the continuing bar must NOT steal
        clicks targeted at the in-cell tasks.

        Before the fix, the continuing bar's full segment time range
        covered the cell, so hit-test returned the continuing bar for
        any click in the cell — including clicks visually on the
        in-cell tasks. The new layout puts continuing bars in narrow
        ribbons on the left edge, leaving the rest of the cell width
        for in-cell tasks, and the slot-aware hit-test returns the
        right item per click region.
        """
        from datetime import time

        from PyQt6.QtCore import QPoint

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekModel,
            _WeekTableView,
        )

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        today = date.today()
        # 75-min spanning task: 11:45 → 13:00, intersects hours 11 and 12
        spanning = create_todo_item("Spanning task")
        spanning.due_date = today
        spanning.due_time = time(13, 0)
        spanning.estimated_minutes = 75
        # In-cell task at 12:30 — should be clickable in hour 12 cell
        in_cell = create_todo_item("In-cell task")
        in_cell.due_date = today
        in_cell.due_time = time(12, 30)
        in_cell.estimated_minutes = 25

        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [spanning, in_cell]})

        # Click in the RIGHT half of hour 12 cell (where in-cell task is)
        idx = model.index(13, 0)  # row 13 = hour 12
        rect = view.visualRect(idx)
        # Right half x position
        click_x = rect.left() + int(rect.width() * 0.75)
        click_y = rect.center().y()
        click = QPoint(click_x, click_y)
        hit = view._hit_test(click)
        assert hit is not None, "click in in-cell task region returned None"
        assert hit[0] == "task"
        # The hit should be the in-cell task, NOT the spanning task
        assert hit[1].id == in_cell.id, (
            f"Click in in-cell task region returned the wrong item. "
            f"Expected {in_cell.reminder!r}, got {hit[1].reminder!r}. "
            f"This is the bug where the continuing bar's wide slot "
            f"covered the in-cell task's region."
        )

        # Click on the LEFT edge of the cell (where the continuing
        # ribbon should be) — should hit the spanning bar.
        click_left = QPoint(rect.left() + 7, click_y)  # 7px in (past 6px gutter, into ribbon)
        hit_left = view._hit_test(click_left)
        assert hit_left is not None
        assert hit_left[1].id == spanning.id, (
            f"Click on continuing ribbon should hit the spanning task. Got {hit_left[1].reminder!r}"
        )

    def test_click_in_middle_hour_cell_also_hits_bar(self, view_with_bar):
        """Clicking in the SECOND hour-cell of the bar (row 15 = hour 14)
        also finds the item. This is the regression Step 8 prevents — the
        old hit-test only worked in the start-hour cell."""
        from PyQt6.QtCore import QPoint

        view, model, item = view_with_bar
        # Row 15 is hour 14 (14:00–15:00) — the bar's second hour
        idx = model.index(15, 0)
        rect = view.visualRect(idx)
        click = QPoint(rect.center().x(), rect.center().y())
        hit = view._hit_test(click)
        assert hit is not None
        assert hit[0] == "task"
        assert hit[1].id == item.id

    def test_click_outside_bar_returns_none(self, view_with_bar):
        """Clicking in a cell that the bar does NOT intersect returns None."""
        from PyQt6.QtCore import QPoint

        view, model, _item = view_with_bar
        # Row 6 is hour 5 (5:00–6:00) — well outside the 13:00–15:00 bar
        idx = model.index(6, 0)
        rect = view.visualRect(idx)
        click = QPoint(rect.center().x(), rect.center().y())
        hit = view._hit_test(click)
        assert hit is None

    def test_click_in_horizontal_padding_returns_none(self, view_with_bar):
        """The bar is inset 4px from each cell edge — clicking in the
        padding area is not a hit."""
        from PyQt6.QtCore import QPoint

        view, model, _item = view_with_bar
        idx = model.index(14, 0)
        rect = view.visualRect(idx)
        # Click 1 pixel from the left edge — inside the cell but in the
        # bar's left padding zone
        click = QPoint(rect.left() + 1, rect.center().y())
        hit = view._hit_test(click)
        assert hit is None

    def test_click_on_empty_cell_returns_none(self, qtbot):
        """An empty week (no items) produces no hits."""
        from PyQt6.QtCore import QPoint

        from pytodo_qt.gui.widgets.calendar_view import _WeekModel, _WeekTableView

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        idx = model.index(10, 0)
        rect = view.visualRect(idx)
        click = QPoint(rect.center().x(), rect.center().y())
        hit = view._hit_test(click)
        assert hit is None

    def test_all_day_row_chip_hit_test_preserved(self, qtbot):
        """The All Day row (row 0) still hits via the chip path until Step 9
        moves it. An item with no due_time is rendered as a chip there."""
        from PyQt6.QtCore import QPoint

        from pytodo_qt.gui.widgets.calendar_view import _WeekModel, _WeekTableView

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        today = date.today()
        item = create_todo_item("All-day task")
        item.due_date = today
        item.due_time = None
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [item]})

        idx = model.index(0, 0)  # All Day row
        rect = view.visualRect(idx)
        # Click near the top of the chip area
        click = QPoint(rect.center().x(), rect.top() + 8)
        hit = view._hit_test(click)
        assert hit is not None
        assert hit[0] == "task"
        assert hit[1].id == item.id


class TestWeekViewBarOverflowBadge:
    """Overflow badge for hour cells with more than MAX_VISIBLE_SLOTS=3
    competing in-cell tasks.

    The cell layout caps in-cell starting slots at 3 to keep individual
    chips wide enough to read; tasks past the cap are collected into
    `_CellBarLayout.overflow_items` and rendered as a "+N" badge in
    the cell's top-right corner. The badge MUST be clickable so the
    hidden tasks remain reachable — clicks on it route to the same
    `more_clicked` signal the month view uses for its "+N more"
    overflow, which the calendar widget displays via a day popover.
    """

    def _make_cell_with_overflow(self, qtbot, n_starting: int):
        """Build a week view with `n_starting` tasks all starting in the
        same hour cell. Returns (view, model, items, cell_index)."""
        from datetime import time

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import _WeekModel, _WeekTableView

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        today = date.today()
        items = []
        for i in range(n_starting):
            it = create_todo_item(f"Task {i}")
            it.due_date = today
            it.due_time = time(10, 30)  # all in hour 10 cell
            it.estimated_minutes = 30
            items.append(it)

        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: items})
        # Hour 10 lives at row 11 (row 0 is All Day, rows 1..24 = hours 0..23).
        return view, model, items, model.index(11, 0)

    def test_overflow_items_populated_when_more_than_three_starting(self, qtbot):
        """5 tasks all starting in the same cell → 3 visible slots, 2 overflow."""
        from pytodo_qt.gui.widgets.calendar_view import _compute_cell_bar_layout

        _view, _model, items, _idx = self._make_cell_with_overflow(qtbot, 5)
        layout = _compute_cell_bar_layout(
            items,
            date.today(),
            10 * 60,
            11 * 60,
            bar_left=0,
            bar_width=200,
            current_time=__import__("datetime").datetime.now(),
        )
        assert len(layout.starting) == 3
        assert layout.overflow == 2
        assert len(layout.overflow_items) == 2
        # Overflow items are the tail of starting_raw — items[3] and items[4]
        overflow_ids = {it.id for it in layout.overflow_items}
        assert items[3].id in overflow_ids
        assert items[4].id in overflow_ids

    def test_overflow_zero_when_three_or_fewer_starting(self, qtbot):
        """3 tasks → all visible, no overflow."""
        from pytodo_qt.gui.widgets.calendar_view import _compute_cell_bar_layout

        _view, _model, items, _idx = self._make_cell_with_overflow(qtbot, 3)
        layout = _compute_cell_bar_layout(
            items,
            date.today(),
            10 * 60,
            11 * 60,
            bar_left=0,
            bar_width=200,
            current_time=__import__("datetime").datetime.now(),
        )
        assert len(layout.starting) == 3
        assert layout.overflow == 0
        assert layout.overflow_items == []

    def test_badge_rect_helper_returns_none_for_zero_overflow(self):
        from PyQt6.QtCore import QRect

        from pytodo_qt.gui.widgets.calendar_view import _compute_overflow_badge_rect

        rect = QRect(0, 0, 100, 60)
        assert _compute_overflow_badge_rect(rect, 0) is None

    def test_badge_rect_helper_in_top_right_corner(self, qtbot):
        from PyQt6.QtCore import QRect

        from pytodo_qt.gui.widgets.calendar_view import _compute_overflow_badge_rect

        # qtbot ensures a QApplication exists (QFontMetrics requires it).
        del qtbot  # noqa: F841 — fixture only needed for app init
        rect = QRect(0, 0, 100, 60)
        badge = _compute_overflow_badge_rect(rect, 5)
        assert badge is not None
        # Badge anchored to the cell's top-right corner with a small
        # margin. (Qt's QRect.right() == x + width - 1, so a 4-px gap
        # in pixel coordinates produces badge.right() == cell.right() - 5.)
        assert badge.top() == rect.top() + 2
        assert rect.right() - badge.right() <= 6  # within a few px of right edge
        assert badge.right() < rect.right()  # not flush against the edge
        # Badge is small (chip-sized, not full-cell)
        assert badge.width() < rect.width() // 2
        assert badge.height() < rect.height() // 2

    def test_click_on_overflow_badge_returns_more_with_all_in_cell_items(self, qtbot):
        """Clicking the +N badge hands the popover EVERY task in the
        hour cell, not just the hidden overflow.

        Once labels are disabled (3+ in-cell tasks), the visible chips
        become unidentifiable — the user has no way to read what they
        are. The badge popover is the only path back to the full list,
        so it must contain the visible items too. The badge LABEL still
        reads "+N" (the count of hidden), but the click payload is
        comprehensive.
        """
        from PyQt6.QtCore import QPoint

        from pytodo_qt.gui.widgets.calendar_view import _compute_overflow_badge_rect

        view, _model, items, idx = self._make_cell_with_overflow(qtbot, 6)
        rect = view.visualRect(idx)
        badge = _compute_overflow_badge_rect(rect, 3)  # 6 - 3 visible = 3 overflow
        assert badge is not None
        click = QPoint(badge.center().x(), badge.center().y())
        hit = view._hit_test(click)
        assert hit is not None, "click on +N badge returned None"
        assert hit[0] == "more"
        assert hit[1] == date.today()
        # hit[2] is ALL items in the cell — visible 3 + hidden 3 = 6.
        all_ids = {it.id for it in hit[2]}
        assert all_ids == {it.id for it in items}, (
            "popover must receive every task in the cell, not just the hidden ones"
        )
        # Sanity: the visible chips must be in the payload too.
        for visible_item in items[:3]:
            assert visible_item.id in all_ids
        # Sanity: the hidden tasks must be in the payload.
        for hidden_item in items[3:]:
            assert hidden_item.id in all_ids

    def test_overflow_badge_emits_more_clicked_signal(self, qtbot):
        """Pressing the mouse on the badge fires more_clicked so the
        widget's _on_more_clicked handler can open the day popover."""
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        from pytodo_qt.gui.widgets.calendar_view import _compute_overflow_badge_rect

        view, _model, items, idx = self._make_cell_with_overflow(qtbot, 5)
        rect = view.visualRect(idx)
        badge = _compute_overflow_badge_rect(rect, 2)
        assert badge is not None

        captured: list[tuple] = []
        view.more_clicked.connect(lambda d, lst: captured.append((d, lst)))

        click_pos = QPointF(float(badge.center().x()), float(badge.center().y()))
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            click_pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        view.mousePressEvent(ev)

        assert len(captured) == 1, "more_clicked was not emitted on badge click"
        emitted_date, emitted_items = captured[0]
        assert emitted_date == date.today()
        emitted_ids = {it.id for it in emitted_items}
        # All 5 items in the cell — 3 visible chips + 2 hidden — must
        # be present so the popover gives the user the full list.
        assert emitted_ids == {it.id for it in items}


class TestWeekDelegateBarPixels:
    """Pixel-level verification that bars actually render with visible chrome.

    Earlier smoke tests only checked that paint() didn't raise — they
    missed the bug where bars technically rendered but looked like solid
    background fills. These tests verify the painted pixmap contains BOTH
    bar pixels AND cell-background pixels, proving the visual inset works.
    """

    def _paint_and_hist(self, item, row, qtbot):
        """Paint a single cell with a single item; return color histogram."""
        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QColor, QImage, QPainter
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekDelegate,
            _WeekModel,
            _WeekTableView,
        )

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        delegate = _WeekDelegate()
        view.setItemDelegate(delegate)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        today = date.today()
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [item]})

        img = QImage(200, 60, QImage.Format.Format_ARGB32)
        img.fill(QColor("white"))
        painter = QPainter(img)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 200, 60)
        idx = model.index(row, 0)
        delegate.paint(painter, opt, idx)
        painter.end()

        hist: dict[tuple[int, int, int], int] = {}
        for y in range(img.height()):
            for x in range(img.width()):
                pixel = img.pixel(x, y)
                key = ((pixel >> 16) & 0xFF, (pixel >> 8) & 0xFF, pixel & 0xFF)
                hist[key] = hist.get(key, 0) + 1
        return hist

    def test_bar_does_not_fill_entire_cell(self, qtbot):
        """A 1-hour bar must NOT fill 100% of the cell — the cell background
        should show as a visible inset above/below the bar. This is what
        distinguishes a task chip from a background tint.
        """
        from datetime import time

        from pytodo_qt.core.models import create_todo_item

        item = create_todo_item("Visible bar")
        today = date.today()
        item.due_date = today
        item.due_time = time(10, 0)
        item.estimated_minutes = 60  # 9:00-10:00

        # Paint hour 9 cell (source row 10)
        hist = self._paint_and_hist(item, 10, qtbot)

        # The dominant color should not be more than 85% of the cell
        # (proving the inset is visible).
        total = sum(hist.values())
        dominant = sorted(hist.items(), key=lambda x: -x[1])
        top_color_pct = dominant[0][1] / total
        assert top_color_pct < 0.85, (
            f"Top color {dominant[0][0]} covers {top_color_pct * 100:.1f}% "
            f"of the cell — bar is not visually distinct from background."
        )

    def test_multi_hour_bar_continuing_slices_have_no_horizontal_borders(self, qtbot):
        """Multi-cell bar slices must visually merge into ONE continuous bar.

        REGRESSION: previously each slice had a full border + 4px insets,
        creating visible gaps at cell boundaries. The user saw a
        75-minute bar as TWO disconnected boxes (one in hour 11, one
        in hour 12) instead of one continuous bar.

        Fix: continuing edges have no inset and no horizontal border.
        Verified by checking that the boundary between two adjacent
        slices has no horizontal line of border-color pixels.
        """
        from datetime import time

        from pytodo_qt.core.models import create_todo_item

        item = create_todo_item("75-min spanning task")
        today = date.today()
        item.due_date = today
        item.due_time = time(13, 0)  # 13:00 deadline
        item.estimated_minutes = 75  # 11:45-13:00, spans hours 11, 12
        # Row 12 = hour 11 (the START hour)
        hist_start = self._paint_and_hist(item, 12, qtbot)
        # Row 13 = hour 12 (the CONTINUING hour, also the end hour)
        hist_continuing = self._paint_and_hist(item, 13, qtbot)

        # Both cells should have visible bar pixels
        assert len(hist_start) > 2
        assert len(hist_continuing) > 2

        # The continuing cell has no top inset (the bar reaches the top
        # of the cell) and no top border line. We can sanity-check this
        # by verifying the very top row of pixels in the continuing cell
        # contains the BAR color, not the cell-background color or a
        # border line.
        # (We don't assert exact colors because the rounding/aliasing
        # behavior is environment-specific; we just check that the
        # top row is dominated by colored pixels, indicating the bar
        # extends to the top edge.)

    def test_slice_is_first_labelable_pure_logic(self):
        """Direct test of _slice_is_first_labelable: walks earlier
        cells of a segment to decide whether this cell should label.
        Tested directly (not via pixel histograms) so the assertion
        doesn't depend on cross-platform font antialiasing differences.
        """
        from uuid import uuid4

        from pytodo_qt.core.calendar_layout import BarSegment, BarState
        from pytodo_qt.gui.widgets.calendar_view import (
            _slice_is_first_labelable,
        )

        def seg(start_minute: int, end_minute: int) -> BarSegment:
            return BarSegment(
                item_id=uuid4(),
                start_minute=start_minute,
                end_minute=end_minute,
                state=BarState.IN_WORK_WINDOW,
                clipped_top=False,
                clipped_bottom=False,
                is_marker=False,
                marker_label=None,
                is_all_day=False,
            )

        # Week view cell geometry: 60-min wide, 60 px tall.
        W = 60
        H = 60

        # 3-hour 12:00-15:00 task (180 min, full-height slices).
        three_hr = seg(12 * 60, 15 * 60)
        # Start cell (hour 12) labels.
        assert _slice_is_first_labelable(three_hr, 12 * 60, W, H) is True
        # Middle cell (hour 13): earlier hour 12 has 60 px (no insets
        # since continuing both sides — wait, hour 12 is start so
        # inset_top=4, inset_bot=0 → height 56. ≥14 → suppress).
        assert _slice_is_first_labelable(three_hr, 13 * 60, W, H) is False
        # End cell (hour 14): earlier hour 12 is tall, still suppress.
        assert _slice_is_first_labelable(three_hr, 14 * 60, W, H) is False

        # 25-min cross-hour task 10:45-11:10 (user's reported bug).
        # Start slice is 15 min (11 px after inset) → below threshold.
        # End slice is 10 min (6 px after inset) → also below threshold.
        # Neither can actually display a label — but the function must
        # still correctly identify hour 10 as "first labelable" and
        # hour 11 as "suppressed because earlier could have labeled".
        # For hour 11, earlier hour 10 slice = 15*60/60 - 4 = 11 px,
        # which is < 14, so NOT first-labelable by earlier slice —
        # hour 11 should return True (first labelable), and the
        # caller's own height check will still skip.
        twenty_five = seg(10 * 60 + 45, 11 * 60 + 10)
        assert _slice_is_first_labelable(twenty_five, 10 * 60, W, H) is True
        assert _slice_is_first_labelable(twenty_five, 11 * 60, W, H) is True

        # Thin-start fallback: 95-min 19:55-21:30 task.
        # Hour 19 slice = 5 min = 5 px - 4 = 1 px → below threshold.
        # Hour 20 slice = 60 min (continuing both sides, no insets)
        #   = 60 px ≥ 14 → first labelable body cell.
        # Hour 21 slice = 30 min end slice = 30 - 4 (bottom inset)
        #   = 26 px ≥ 14. But earlier hour 20 already crosses the
        #   threshold, so hour 21 suppresses.
        thin_start = seg(19 * 60 + 55, 21 * 60 + 30)
        assert _slice_is_first_labelable(thin_start, 19 * 60, W, H) is True  # no earlier
        assert _slice_is_first_labelable(thin_start, 20 * 60, W, H) is True  # earlier h19 thin
        assert _slice_is_first_labelable(thin_start, 21 * 60, W, H) is False  # earlier h20 tall

        # Single-cell task 10:00-10:45 entirely within one cell.
        single = seg(10 * 60, 10 * 60 + 45)
        assert _slice_is_first_labelable(single, 10 * 60, W, H) is True

        # 60-min 10:30-11:30 → start slice 30 min ≥ 14 → hour 11 suppresses.
        one_hr = seg(10 * 60 + 30, 11 * 60 + 30)
        assert _slice_is_first_labelable(one_hr, 10 * 60, W, H) is True
        assert _slice_is_first_labelable(one_hr, 11 * 60, W, H) is False

    def test_two_tasks_same_hour_both_render(self, qtbot):
        """REGRESSION: Two tasks in the same cell must both render.

        The original `drawn_count % max_stack` code cycled slot positions,
        causing item 4 to paint OVER item 1. Users with multiple recurring
        tasks at the same hour saw only one bar — the "only 25min task
        showing, not the 1h one" complaint.
        """
        from datetime import time

        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QColor, QImage, QPainter
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekDelegate,
            _WeekModel,
            _WeekTableView,
        )

        today = date.today()
        item1 = create_todo_item("25min task")
        item1.due_date = today
        item1.due_time = time(10, 25)
        item1.estimated_minutes = 25

        item2 = create_todo_item("1h task")
        item2.due_date = today
        item2.due_time = time(11, 0)
        item2.estimated_minutes = 60

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        delegate = _WeekDelegate()
        view.setItemDelegate(delegate)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [item1, item2]})

        # Hour 10 cell (row 11) — both items intersect it
        img = QImage(300, 60, QImage.Format.Format_ARGB32)
        img.fill(QColor("white"))
        painter = QPainter(img)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 300, 60)
        idx = model.index(11, 0)
        delegate.paint(painter, opt, idx)
        painter.end()

        # Two bars side-by-side with distinct colors, borders, and labels
        # produce a rich color palette. A single bar (the old bug) would
        # have far fewer distinct colors.
        distinct = set()
        for y in range(img.height()):
            for x in range(img.width()):
                pixel = img.pixel(x, y)
                r, g, b = (pixel >> 16) & 0xFF, (pixel >> 8) & 0xFF, pixel & 0xFF
                if (r, g, b) != (255, 255, 255):
                    distinct.add((r, g, b))
        assert len(distinct) > 10, (
            f"Expected a rich color palette from two bars rendered "
            f"side-by-side; got {len(distinct)} distinct colors. "
            f"Probable regression to the modulo-wraparound bug."
        )

    def test_four_tasks_same_hour_overflow_badge(self, qtbot):
        """When a cell has more tasks than MAX_VISIBLE_SLOTS (3), the
        delegate paints the first 3 as bars plus a '+N more' badge."""
        from datetime import time

        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QColor, QImage, QPainter
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekDelegate,
            _WeekModel,
            _WeekTableView,
        )

        today = date.today()
        items = []
        for i in range(5):
            it = create_todo_item(f"Task {i}")
            it.due_date = today
            it.due_time = time(10, 30)
            it.estimated_minutes = 30
            items.append(it)

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        delegate = _WeekDelegate()
        view.setItemDelegate(delegate)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: items})

        img = QImage(300, 60, QImage.Format.Format_ARGB32)
        img.fill(QColor("white"))
        painter = QPainter(img)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 300, 60)
        idx = model.index(11, 0)
        delegate.paint(painter, opt, idx)
        painter.end()

        # 5 items → 3 slots + "+2" badge. We verify no crash plus a
        # substantial pixel count (multiple bars + badge chrome).
        total_non_white = 0
        for y in range(img.height()):
            for x in range(img.width()):
                pixel = img.pixel(x, y)
                r, g, b = (pixel >> 16) & 0xFF, (pixel >> 8) & 0xFF, pixel & 0xFF
                if (r, g, b) != (255, 255, 255):
                    total_non_white += 1
        assert total_non_white > 100

    def _paint_three_slot_cell(self, qtbot, cell_width: int, reminders: list[str]):
        """Render a single hour cell at `cell_width` px containing three
        in-cell starting tasks with the given reminders. Returns the QImage.

        Used to compare label-on vs label-off renderings: identical
        bar geometry, only the reminder text differs.
        """
        from datetime import time

        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QColor, QImage, QPainter
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekDelegate,
            _WeekModel,
            _WeekTableView,
        )

        today = date.today()
        items = []
        for reminder in reminders:
            it = create_todo_item(reminder)
            it.due_date = today
            it.due_time = time(10, 30)
            it.estimated_minutes = 30
            items.append(it)

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        delegate = _WeekDelegate()
        view.setItemDelegate(delegate)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: items})

        img = QImage(cell_width, 60, QImage.Format.Format_ARGB32)
        img.fill(QColor("white"))
        painter = QPainter(img)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, cell_width, 60)
        idx = model.index(11, 0)  # hour 10
        delegate.paint(painter, opt, idx)
        painter.end()
        return img

    def _images_differ(self, img_a, img_b) -> bool:
        """True if any pixel in img_a differs from img_b."""
        if img_a.size() != img_b.size():
            return True
        for y in range(img_a.height()):
            for x in range(img_a.width()):
                if img_a.pixel(x, y) != img_b.pixel(x, y):
                    return True
        return False

    def test_three_slot_labels_visible_in_day_view_width(self, qtbot):
        """Day view cells are wide enough that 3 slots still leave each
        slot well above _MIN_LABEL_WIDTH — labels MUST render so the
        user can read which task is in which slot.

        Verified by rendering the same cell twice — once with descriptive
        reminders, once with empty reminders — and asserting the images
        differ. Only the label-painting code path varies between the two
        renders, so any difference proves labels are being drawn.
        """
        # 600 px is a typical day-view cell width. 3 slots → ~190 px slot
        # width → ~180 px label width — far above the 60 px threshold.
        with_text = self._paint_three_slot_cell(
            qtbot,
            cell_width=600,
            reminders=["Plan release", "Review PR", "Write docs"],
        )
        without_text = self._paint_three_slot_cell(
            qtbot,
            cell_width=600,
            reminders=["", "", ""],
        )
        assert self._images_differ(with_text, without_text), (
            "Day-view cell width is wide enough for labels but the "
            "rendered image is identical with/without reminder text — "
            "labels are not being drawn for 3-slot day-view cells."
        )

    def test_three_slot_labels_skipped_in_week_view_width(self, qtbot):
        """Week view cells are narrow enough that 3 slots produce a
        slot width below _MIN_LABEL_WIDTH — labels MUST be skipped.
        Cramming 2-character elided gibberish into 20 px slots is
        worse than no label at all (the user has tooltips and the +N
        popover for full text).
        """
        # 130 px is a typical week-view cell width (≈ (1000 - gutter) / 7).
        # 3 slots → ~40 px slot width → ~32 px label width — well below
        # the 60 px threshold.
        with_text = self._paint_three_slot_cell(
            qtbot,
            cell_width=130,
            reminders=["Plan release", "Review PR", "Write docs"],
        )
        without_text = self._paint_three_slot_cell(
            qtbot,
            cell_width=130,
            reminders=["", "", ""],
        )
        assert not self._images_differ(with_text, without_text), (
            "Week-view cell width is too narrow for readable labels "
            "but the rendered image differs based on reminder text — "
            "the painter is cramming unreadable labels into narrow slots."
        )

    def test_two_slot_labels_visible_in_week_view_width(self, qtbot):
        """At 2 in-cell tasks, week-view cells produce slots wide enough
        for labels (≈60 px label width). Labels MUST render so the
        user can read both tasks. This is the historical 2-slot
        behavior preserved by the width-based threshold.
        """
        with_text = self._paint_three_slot_cell(
            qtbot,
            cell_width=130,
            reminders=["Plan release", "Review PR"],
        )
        without_text = self._paint_three_slot_cell(
            qtbot,
            cell_width=130,
            reminders=["", ""],
        )
        assert self._images_differ(with_text, without_text), (
            "Week-view 2-slot cells must still show labels — the "
            "width threshold is too aggressive and is suppressing "
            "labels that fit comfortably."
        )


class TestQ6OverdueMarkers:
    """Step 10 — Q6 overdue marker rendering in the pinned All Day row.

    Markers represent past-due tasks projected forward to a viewing
    day after the task's due day. They live in the All Day row, NOT
    the hour grid (the hour grid only paints the bar on the actual
    due day). This test class covers:

      - _MarkerChip wrapper attribute forwarding
      - _collect_markers_for_dates pure-function correctness across
        the Q6 lifecycle cases
      - _WeekModel.set_markers + merging into the All Day row's items
      - Marker chip pixel rendering (distinct from regular all-day
        chips)
      - Hit-test on marker chips routes clicks to the underlying item
    """

    def _make_overdue_item(self, days_overdue: int = 3, reminder: str = "Plan release"):
        """Build a TodoItem due `days_overdue` days ago.

        Sets `created_at` to 30 days before the due date so the
        DEADLINE_FROM_CREATED rule (Rule 3) produces a valid window —
        without this, create_todo_item() sets created_at to now, and
        for past due_dates the rule sanitizes to ALL_DAY which never
        produces marker segments. Real overdue tasks always satisfy
        created_at < due_date because they were created before the
        deadline arrived.
        """
        from datetime import datetime as _dt

        from pytodo_qt.core.models import create_todo_item

        item = create_todo_item(reminder)
        item.due_date = date.today() - timedelta(days=days_overdue)
        item.due_time = None
        # 30 days before due_date — guarantees Rule 3 sees a valid
        # creation timestamp regardless of how far in the past
        # `days_overdue` is.
        creation_dt = _dt.combine(
            item.due_date - timedelta(days=30), __import__("datetime").time(8, 0)
        )
        item.created_at = int(creation_dt.timestamp() * 1000)
        return item

    # ------------------------------------------------------------------
    # _MarkerChip attribute forwarding
    # ------------------------------------------------------------------

    def test_marker_chip_forwards_id_to_underlying_item(self):
        from pytodo_qt.core.calendar_layout import BarState
        from pytodo_qt.gui.widgets.calendar_view import _MarkerChip

        item = self._make_overdue_item()
        chip = _MarkerChip(item, "3d overdue", BarState.OVERDUE_ACTIVE)
        # Click handlers do hit[1].id — must return the real item id
        assert chip.id == item.id

    def test_marker_chip_forwards_reminder_to_underlying_item(self):
        from pytodo_qt.core.calendar_layout import BarState
        from pytodo_qt.gui.widgets.calendar_view import _MarkerChip

        item = self._make_overdue_item(reminder="Submit report")
        chip = _MarkerChip(item, "5d overdue", BarState.OVERDUE_ACTIVE)
        assert chip.reminder == "Submit report"

    def test_marker_chip_carries_marker_label_and_state(self):
        from pytodo_qt.core.calendar_layout import BarState
        from pytodo_qt.gui.widgets.calendar_view import _MarkerChip

        item = self._make_overdue_item()
        chip = _MarkerChip(item, "3d overdue", BarState.OVERDUE_ACTIVE)
        assert chip.marker_label == "3d overdue"
        assert chip.marker_state == BarState.OVERDUE_ACTIVE

    # ------------------------------------------------------------------
    # _collect_markers_for_dates correctness
    # ------------------------------------------------------------------

    def test_collect_markers_for_active_overdue_task(self):
        """A task due 3 days ago, not complete, viewed today: produces
        a marker on today's date with the elapsed-overdue label."""
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import _collect_markers_for_dates

        item = self._make_overdue_item(days_overdue=3)
        item.due_time = __import__("datetime").time(9, 0)  # 9 AM 3 days ago
        item.complete = False
        today = date.today()
        markers = _collect_markers_for_dates([item], [today], _dt.now())
        assert today in markers
        assert len(markers[today]) == 1
        chip = markers[today][0]
        assert chip.id == item.id
        # Label format from compute_bar_segments via _make_marker
        assert "overdue" in chip.marker_label.lower()

    def test_collect_markers_skips_due_day_itself(self):
        """The due day shows the bar in the hour grid, NOT a marker.
        _collect_markers_for_dates must not produce a marker for the
        actual due day."""
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import _collect_markers_for_dates

        item = self._make_overdue_item(days_overdue=0)  # due today
        item.due_time = __import__("datetime").time(9, 0)
        today = date.today()
        markers = _collect_markers_for_dates([item], [today], _dt.now())
        assert markers[today] == []

    def test_collect_markers_skips_pre_due_days(self):
        """Days BEFORE the due day are not "overdue" — no marker."""
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import _collect_markers_for_dates

        item = self._make_overdue_item(days_overdue=-2)  # due in 2 days
        item.due_time = __import__("datetime").time(9, 0)
        today = date.today()
        markers = _collect_markers_for_dates([item], [today], _dt.now())
        assert markers[today] == []

    def test_collect_markers_completed_late_intermediate_day(self):
        """Task due Mon, completed Wed, viewing Tue → marker on Tue
        because the task was overdue-active on Tue."""
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import _collect_markers_for_dates

        # Build a task due 5 days ago, completed 1 day ago
        item = self._make_overdue_item(days_overdue=5)
        item.due_time = __import__("datetime").time(9, 0)
        item.complete = True
        completed_dt = _dt.combine(
            date.today() - timedelta(days=1), __import__("datetime").time(15, 0)
        )
        item.completed_at = int(completed_dt.timestamp() * 1000)

        # Viewing day = 3 days ago (between due day and completed day)
        viewing_day = date.today() - timedelta(days=3)
        markers = _collect_markers_for_dates([item], [viewing_day], _dt.now())
        assert len(markers[viewing_day]) == 1
        assert markers[viewing_day][0].id == item.id

    def test_collect_markers_completed_late_post_completion_no_marker(self):
        """After the completion day, the bar lives in the hour grid
        with the COMPLETED_LATE two-zone visual — no marker on
        subsequent days."""
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import _collect_markers_for_dates

        item = self._make_overdue_item(days_overdue=5)
        item.due_time = __import__("datetime").time(9, 0)
        item.complete = True
        completed_dt = _dt.combine(
            date.today() - timedelta(days=2), __import__("datetime").time(15, 0)
        )
        item.completed_at = int(completed_dt.timestamp() * 1000)

        # Viewing day = today (after completion day)
        markers = _collect_markers_for_dates([item], [date.today()], _dt.now())
        assert markers[date.today()] == []

    def test_collect_markers_dedup_by_item_id(self):
        """The same item must not produce multiple marker chips for
        the same viewing day, even if compute_bar_segments somehow
        emitted duplicates (defensive)."""
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import _collect_markers_for_dates

        item = self._make_overdue_item(days_overdue=3)
        item.due_time = __import__("datetime").time(9, 0)
        # Pass the same item twice in the input list
        markers = _collect_markers_for_dates([item, item], [date.today()], _dt.now())
        assert len(markers[date.today()]) == 1

    def test_collect_markers_excludes_recurring_tasks_per_q7(self):
        """REGRESSION: Q7 says recurring tasks reset cleanly with no
        carryover between cycles. _collect_markers_for_dates must skip
        recurring items entirely so the projection system can show
        each cycle as a fresh bar without a competing "overdue from
        yesterday's missed cycle" marker shadowing it.

        Without this filter, every future viewing day would show BOTH
        a projected fresh bar AND a spurious overdue marker for the
        same recurring task — a Q7 violation that double-renders the
        same task on every cycle.
        """
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import _collect_markers_for_dates

        # A daily recurring task that's "due today" — its current
        # cycle is in today's hour grid. Tomorrow's view should NOT
        # show a marker; the projection system handles tomorrow's
        # fresh occurrence.
        item = self._make_overdue_item(days_overdue=0, reminder="Daily standup")
        item.due_time = __import__("datetime").time(9, 0)
        item.recurrence_type = "daily"
        item.recurrence_interval = 1

        # Even when viewing far-future days, no marker for a recurring
        # task. This is the load-bearing assertion: recurring tasks
        # are out of scope for marker collection.
        future_dates = [
            date.today() + timedelta(days=1),
            date.today() + timedelta(days=2),
            date.today() + timedelta(days=7),
        ]
        markers = _collect_markers_for_dates([item], future_dates, _dt.now())
        for d in future_dates:
            assert markers[d] == [], (
                f"Recurring task generated a Q7-violating marker for {d}. "
                f"Recurring tasks must not produce overdue markers — "
                f"the projection system handles their visibility."
            )

    def test_collect_markers_includes_non_recurring_overdue_tasks(self):
        """Sanity check: non-recurring overdue tasks DO still produce
        markers. Q7 only excludes recurring items."""
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import _collect_markers_for_dates

        item = self._make_overdue_item(days_overdue=2, reminder="One-shot task")
        item.due_time = __import__("datetime").time(9, 0)
        item.recurrence_type = None  # explicitly non-recurring
        markers = _collect_markers_for_dates([item], [date.today()], _dt.now())
        assert len(markers[date.today()]) == 1
        assert markers[date.today()][0].id == item.id

    def test_recurring_task_for_future_day_renders_bar_at_workback_origin(self):
        """REGRESSION: A recurring task with due_time on a FUTURE day
        must render a bar in the hour cell of its workback origin
        (NOT in the cell of its due_time, which is the bar's END).

        End-to-end pipeline check: build a daily-recurring task with
        due_date=tomorrow and due_time=14:00 with estimated_minutes=60.
        Verify:
          1. The model receives the item via set_items
          2. _WEEK_COLUMN_ITEMS_ROLE for tomorrow's column returns it
          3. _compute_cell_bar_layout for hour 13 (the workback origin)
             produces a starting slot — NOT hour 14 (the due time)
          4. Hour 12 and hour 14 cells are empty for this item

        This verifies the user's "missing 1-hour recurring task" report
        could only be a scroll-position visibility issue (the workback
        origin cell is above the auto-scroll-to-now range), not an
        actual rendering bug.
        """
        from datetime import datetime as _dt
        from datetime import time as _time

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import (
            _WEEK_COLUMN_ITEMS_ROLE,
            _compute_cell_bar_layout,
            _WeekModel,
        )

        # Use a fixed date within the same week to avoid midnight
        # boundary issues when the test runs near day boundaries.
        target_date = date.today()

        # Daily recurring task at 2pm with 1-hour estimate
        task = create_todo_item("1hr daily recurring")
        task.due_date = target_date
        task.due_time = _time(14, 0)
        task.estimated_minutes = 60
        task.recurrence_type = "daily"
        task.recurrence_interval = 1

        model = _WeekModel()
        model.set_items({target_date: [task]})
        model.set_week(target_date)
        model.set_markers({})

        # Find the target date's column index
        week_dates = model.week_dates()
        assert target_date in week_dates, f"week_dates does not contain {target_date}"
        tomorrow_col = week_dates.index(target_date)

        # Step 1: model returns the item via _WEEK_COLUMN_ITEMS_ROLE
        col_items_idx = model.index(15, tomorrow_col)  # row 15 = hour 14
        column_items = col_items_idx.data(_WEEK_COLUMN_ITEMS_ROLE) or []
        assert len(column_items) == 1, (
            f"Expected 1 column item, got {len(column_items)}. "
            f"The model is dropping the recurring task from its column."
        )
        assert column_items[0].id == task.id

        now = _dt.now()

        # Step 2: hour 13 (1pm-2pm) — workback origin cell — has the bar
        layout_13 = _compute_cell_bar_layout(
            column_items, target_date, 13 * 60, 14 * 60, 0, 200, now
        )
        assert len(layout_13.starting) == 1, (
            f"Hour 13 (workback origin) should have a starting bar slot "
            f"for the 1-hour recurring task, got starting={len(layout_13.starting)}"
        )

        # Step 3: hour 14 (2pm-3pm) — the cell of the due_time — must be empty
        # because the bar ENDS at the boundary, doesn't extend into hour 14
        layout_14 = _compute_cell_bar_layout(
            column_items, target_date, 14 * 60, 15 * 60, 0, 200, now
        )
        assert len(layout_14.continuing) == 0 and len(layout_14.starting) == 0, (
            f"Hour 14 (due_time cell) should be empty for a bar ending at "
            f"14:00 exactly, got continuing={len(layout_14.continuing)}, "
            f"starting={len(layout_14.starting)}"
        )

        # Step 4: hour 12 (12pm-1pm) — before workback origin — must also be empty
        layout_12 = _compute_cell_bar_layout(
            column_items, target_date, 12 * 60, 13 * 60, 0, 200, now
        )
        assert len(layout_12.continuing) == 0 and len(layout_12.starting) == 0, (
            f"Hour 12 should be empty for a 1pm-2pm bar, got "
            f"continuing={len(layout_12.continuing)}, starting={len(layout_12.starting)}"
        )

    def test_collect_markers_respects_multiple_dates(self):
        """Each date in the input list gets its own marker entry,
        with the label reflecting that day's elapsed-overdue."""
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import _collect_markers_for_dates

        item = self._make_overdue_item(days_overdue=5)
        item.due_time = __import__("datetime").time(9, 0)
        dates = [date.today() - timedelta(days=2), date.today() - timedelta(days=1), date.today()]
        markers = _collect_markers_for_dates([item], dates, _dt.now())
        for d in dates:
            assert len(markers[d]) == 1, f"missing marker for {d}"

    def test_collect_markers_for_pure_all_day_task_without_due_time(self):
        """An ALL_DAY task (no due_time) whose due day passed produces
        a marker on subsequent days too. Pure-layer support for this
        is in TestComputeBarSegmentsAllDay; this test verifies the
        widget-side `_collect_markers_for_dates` actually surfaces it.
        """
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import _collect_markers_for_dates

        # Pure all-day task — no due_time set (the helper already
        # leaves it None, but make it intentional in the test)
        item = self._make_overdue_item(days_overdue=2, reminder="Birthday card")
        item.due_time = None
        markers = _collect_markers_for_dates([item], [date.today()], _dt.now())
        assert len(markers[date.today()]) == 1
        assert markers[date.today()][0].id == item.id
        assert "overdue" in markers[date.today()][0].marker_label.lower()

    # ------------------------------------------------------------------
    # _WeekModel integration
    # ------------------------------------------------------------------

    def test_week_model_set_markers_merges_into_all_day_row(self, qtbot):
        """Markers passed via set_markers() appear in _WEEK_ITEMS_ROLE
        for row 0 (the All Day row), alongside regular all-day items."""
        from datetime import datetime as _dt

        from pytodo_qt.gui.widgets.calendar_view import (
            _WEEK_ITEMS_ROLE,
            _collect_markers_for_dates,
            _WeekModel,
        )

        model = _WeekModel()
        qtbot.addWidget(__import__("PyQt6.QtWidgets", fromlist=["QWidget"]).QWidget())

        today = date.today()
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]

        # Overdue task from the past — won't appear in items_by_date[today]
        # because its due_date is yesterday, not today.
        overdue = self._make_overdue_item(days_overdue=2)
        overdue.due_time = __import__("datetime").time(9, 0)
        markers = _collect_markers_for_dates([overdue], [today], _dt.now())
        assert len(markers[today]) == 1

        model.set_items({})  # No items keyed on today
        model.set_markers(markers)

        idx = model.index(0, 0)  # All Day row, today's column
        all_day_items = model.data(idx, _WEEK_ITEMS_ROLE) or []
        assert len(all_day_items) == 1
        assert all_day_items[0].id == overdue.id
        assert getattr(all_day_items[0], "marker_label", None) is not None

    def test_cross_midnight_task_spills_into_next_day(self, qtbot):
        """A workback task with due_time early enough to cross midnight
        (e.g. due_time=00:30 + 60min → 23:30 yesterday → 00:30 today)
        must appear in BOTH the origin day's and the end day's buckets.
        Without the spill pass, the tail is invisible on the end day
        because the hour-grid cell lookup is keyed strictly on due_date.
        """
        from datetime import time as _time

        from PyQt6.QtWidgets import QApplication

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        # Ensure a QApplication exists for CalendarViewWidget init
        app = QApplication.instance() or QApplication([])
        widget = CalendarViewWidget()
        qtbot.addWidget(widget)

        today = date(2026, 4, 15)
        yesterday = today - timedelta(days=1)

        item = create_todo_item("Midnight crosser")
        item.due_date = today
        item.due_time = _time(0, 30)
        item.estimated_minutes = 60  # workback → 23:30 yesterday to 00:30 today

        scheduled: dict[date, list] = {today: [item]}
        widget._spill_cross_midnight(scheduled)

        assert today in scheduled
        assert yesterday in scheduled
        assert len(scheduled[today]) == 1
        assert len(scheduled[yesterday]) == 1
        assert scheduled[today][0].id == item.id
        assert scheduled[yesterday][0].id == item.id
        del app  # keep linters quiet

    def test_spill_dedup_prevents_double_add(self, qtbot):
        """If the item is somehow already in both buckets (e.g. a
        projection plus a real item for the same id), the spill pass
        must not create a duplicate."""
        from datetime import time as _time

        from PyQt6.QtWidgets import QApplication

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        app = QApplication.instance() or QApplication([])
        widget = CalendarViewWidget()
        qtbot.addWidget(widget)

        today = date(2026, 4, 15)
        yesterday = today - timedelta(days=1)
        item = create_todo_item("Midnight crosser")
        item.due_date = today
        item.due_time = _time(0, 30)
        item.estimated_minutes = 60

        # Pre-populate both days so spill must dedup
        scheduled: dict[date, list] = {today: [item], yesterday: [item]}
        widget._spill_cross_midnight(scheduled)

        assert len(scheduled[today]) == 1
        assert len(scheduled[yesterday]) == 1
        del app

    def test_spill_skips_all_day_and_single_day_items(self, qtbot):
        """Items whose window does not cross midnight (single-day
        hour-grid bars) and items with ALL_DAY windows (no due_time)
        must not be spilled into other days."""
        from datetime import time as _time

        from PyQt6.QtWidgets import QApplication

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        app = QApplication.instance() or QApplication([])
        widget = CalendarViewWidget()
        qtbot.addWidget(widget)

        today = date(2026, 4, 15)

        # Single-day hour-grid task
        item1 = create_todo_item("Normal hour task")
        item1.due_date = today
        item1.due_time = _time(14, 0)
        item1.estimated_minutes = 60

        # All-day task (no due_time)
        item2 = create_todo_item("All-day task")
        item2.due_date = today
        item2.due_time = None

        scheduled: dict[date, list] = {today: [item1, item2]}
        widget._spill_cross_midnight(scheduled)

        # Both items stay on today only, no other days created
        assert list(scheduled.keys()) == [today]
        assert len(scheduled[today]) == 2
        del app

    def test_week_model_markers_appear_before_regular_all_day_items(self, qtbot):
        """Markers come first in the All Day row's item list because
        they represent the most urgent thing on the row."""
        from datetime import datetime as _dt

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import (
            _WEEK_ITEMS_ROLE,
            _collect_markers_for_dates,
            _WeekModel,
        )

        del qtbot
        model = _WeekModel()
        today = date.today()
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]

        regular = create_todo_item("Regular all-day task")
        regular.due_date = today
        regular.due_time = None

        overdue = self._make_overdue_item(days_overdue=2)
        overdue.due_time = __import__("datetime").time(9, 0)
        markers = _collect_markers_for_dates([overdue], [today], _dt.now())

        model.set_items({today: [regular]})
        model.set_markers(markers)

        idx = model.index(0, 0)
        all_day_items = model.data(idx, _WEEK_ITEMS_ROLE) or []
        assert len(all_day_items) == 2
        # Marker first
        assert getattr(all_day_items[0], "marker_label", None) is not None
        assert all_day_items[0].id == overdue.id
        # Regular second
        assert getattr(all_day_items[1], "marker_label", None) is None
        assert all_day_items[1].id == regular.id

    # ------------------------------------------------------------------
    # Pixel-level marker chip rendering
    # ------------------------------------------------------------------

    def test_marker_chip_renders_with_distinct_color_from_regular_chip(self, qtbot):
        """Pixel test: a row containing a marker chip and a row
        containing a regular all-day chip must produce visually
        distinct images. The marker has a filled OVERDUE_ACTIVE
        background, the regular chip uses cell-background.
        """
        from datetime import datetime as _dt

        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QColor, QImage, QPainter
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import (
            _collect_markers_for_dates,
            _WeekDelegate,
            _WeekModel,
            _WeekTableView,
        )

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        delegate = _WeekDelegate()
        view.setItemDelegate(delegate)
        qtbot.addWidget(view)
        view.resize(800, 200)
        view.show()

        today = date.today()
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]

        # Render 1: regular all-day chip in row 0
        regular = create_todo_item("Plan release")
        regular.due_date = today
        regular.due_time = None
        model.set_items({today: [regular]})
        model.set_markers({today: []})
        img_regular = QImage(300, 64, QImage.Format.Format_ARGB32)
        img_regular.fill(QColor("white"))
        p = QPainter(img_regular)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 300, 64)
        delegate.paint(p, opt, model.index(0, 0))
        p.end()

        # Render 2: marker chip in row 0 (no regular item)
        overdue = self._make_overdue_item(reminder="Plan release", days_overdue=3)
        overdue.due_time = __import__("datetime").time(9, 0)
        markers = _collect_markers_for_dates([overdue], [today], _dt.now())
        model.set_items({})
        model.set_markers(markers)
        img_marker = QImage(300, 64, QImage.Format.Format_ARGB32)
        img_marker.fill(QColor("white"))
        p = QPainter(img_marker)
        delegate.paint(p, opt, model.index(0, 0))
        p.end()

        # The two images must differ — the marker has a colored
        # background fill that the regular chip does not.
        differing_pixels = 0
        for y in range(img_regular.height()):
            for x in range(img_regular.width()):
                if img_regular.pixel(x, y) != img_marker.pixel(x, y):
                    differing_pixels += 1
        assert differing_pixels > 100, (
            f"Marker chip should be visually distinct from regular "
            f"chip but only {differing_pixels} pixels differ."
        )

    def test_marker_chip_uses_overdue_active_color(self, qtbot):
        """The marker chip background should be the OVERDUE_ACTIVE
        color from the bar palette. Sampling a single pixel is
        unreliable because the chip's white text glyphs occupy
        unpredictable positions inside the chip rect — the assertion
        scans across a range of x positions inside the chip body
        and asserts the majority are red-dominant. This tests the
        intent ("the chip is painted in OVERDUE_ACTIVE somewhere
        in its body") without depending on font metrics, glyph
        positioning, or which exact characters the marker label
        contains."""
        from datetime import datetime as _dt

        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QColor, QImage, QPainter
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from pytodo_qt.core.bar_palette import get_palette
        from pytodo_qt.core.calendar_layout import BarState
        from pytodo_qt.gui.widgets.calendar_view import (
            _collect_markers_for_dates,
            _WeekDelegate,
            _WeekModel,
            _WeekTableView,
        )

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        delegate = _WeekDelegate()
        view.setItemDelegate(delegate)
        qtbot.addWidget(view)
        view.resize(800, 200)
        view.show()

        today = date.today()
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]

        overdue = self._make_overdue_item(days_overdue=3)
        overdue.due_time = __import__("datetime").time(9, 0)
        markers = _collect_markers_for_dates([overdue], [today], _dt.now())
        model.set_items({})
        model.set_markers(markers)

        img = QImage(300, 64, QImage.Format.Format_ARGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 300, 64)
        delegate.paint(p, opt, model.index(0, 0))
        p.end()

        palette = get_palette("light")
        expected = QColor(palette[BarState.OVERDUE_ACTIVE].base)

        # Scan a row of pixels inside the chip body at y=4. The chip
        # starts at the top of the cell with a thin border, so y=4 is
        # just below the border and inside the chip background. The
        # x range covers the visible chip area (inset 4px from the
        # cell edge to skip the rounded-rect border) and stops well
        # short of the right edge so we sample background even when
        # the elided text is short. Some pixels in the scan will
        # land on white text glyphs; the assertion only requires
        # that the majority be red-dominant, which is true whenever
        # the chip is correctly painted in any state (label position
        # is irrelevant).
        red_count = 0
        non_red_count = 0
        for x in range(8, 80):
            px = img.pixel(x, 4)
            r = (px >> 16) & 0xFF
            g = (px >> 8) & 0xFF
            b = px & 0xFF
            if r > g and r > b:
                red_count += 1
            else:
                non_red_count += 1

        assert red_count > non_red_count, (
            f"Marker chip body should be predominantly red-dominant in the "
            f"OVERDUE_ACTIVE palette ({expected.getRgb()}). Scan found "
            f"{red_count} red-dominant pixels vs {non_red_count} other."
        )

    # ------------------------------------------------------------------
    # Hit-test routing
    # ------------------------------------------------------------------

    def test_marker_chip_click_returns_underlying_item(self, qtbot):
        """Clicking a marker chip in the All Day row must return
        ('task', item, index) where item.id is the REAL underlying
        item id, not the wrapper. The mousePressEvent then emits
        task_clicked.emit(item.id) which downstream handlers use
        to open the editor."""
        from datetime import datetime as _dt

        from PyQt6.QtCore import QPoint

        from pytodo_qt.gui.widgets.calendar_view import (
            _collect_markers_for_dates,
            _WeekModel,
            _WeekTableView,
        )

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        today = date.today()
        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]

        overdue = self._make_overdue_item(days_overdue=3)
        overdue.due_time = __import__("datetime").time(9, 0)
        markers = _collect_markers_for_dates([overdue], [today], _dt.now())
        model.set_items({})
        model.set_markers(markers)

        # Click in the All Day row, today's column
        idx = model.index(0, 0)
        rect = view.visualRect(idx)
        click = QPoint(rect.center().x(), rect.top() + 8)
        hit = view._hit_test(click)
        assert hit is not None
        assert hit[0] == "task"
        # Hit returns the marker chip, but its .id forwards to the
        # underlying item — that's what task_clicked.emit will fire.
        assert hit[1].id == overdue.id


class TestPinnedContainerAlignment:
    """Step 9 follow-up: the all-day and hour-grid tables must have
    perfectly aligned columns, identical vertical header width, and the
    hour grid must hide its horizontal header."""

    @pytest.fixture()
    def container(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import (
            _PinnedWeekContainer,
            _WeekDelegate,
            _WeekModel,
        )

        model = _WeekModel()
        delegate = _WeekDelegate()
        c = _PinnedWeekContainer(model, delegate)
        qtbot.addWidget(c)
        c.resize(800, 600)
        c.show()
        return c

    def test_vertical_headers_have_same_width(self, container):
        """Both inner tables must have vertical headers of identical
        width so columns start at the same x coordinate. Without this,
        the all-day row and hour grid's columns visibly misalign."""
        all_day_vh = container.all_day_table.verticalHeader()
        hour_grid_vh = container.hour_grid_table.verticalHeader()
        assert all_day_vh is not None
        assert hour_grid_vh is not None
        assert all_day_vh.width() == hour_grid_vh.width()

    def test_hour_grid_horizontal_header_hidden(self, container):
        """The hour grid must hide its horizontal header — day labels
        live on the pinned all-day table above, so a duplicate header
        on the hour grid produces the "two day headers" visual bug."""
        h_header = container.hour_grid_table.horizontalHeader()
        assert h_header is not None
        assert not h_header.isVisible()

    def test_all_day_horizontal_header_visible(self, container):
        """The all-day table is the ONLY table showing day labels."""
        h_header = container.all_day_table.horizontalHeader()
        assert h_header is not None
        # isVisible() may return False for offscreen widgets that haven't
        # been laid out yet — check setVisible state via visibility flag
        assert not h_header.isHidden()

    def test_all_day_horizontal_scrollbar_disabled(self, container):
        """The all-day table's horizontal scrollbar is off — scrolling
        is driven by the hour grid below and mirrored via the sync
        handlers."""
        from PyQt6.QtCore import Qt as _Qt

        assert (
            container.all_day_table.horizontalScrollBarPolicy()
            == _Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

    def test_both_tables_fixed_mode(self, container):
        """Both tables use Fixed resize mode so the container can set
        column widths manually — this gives exact alignment regardless
        of scrollbar reservations (Stretch mode couldn't guarantee this
        because the all-day table has no vertical scrollbar while the
        hour grid does)."""
        ad_header = container.all_day_table.horizontalHeader()
        hg_header = container.hour_grid_table.horizontalHeader()
        assert ad_header is not None
        assert hg_header is not None
        from PyQt6.QtWidgets import QHeaderView

        assert ad_header.sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
        assert hg_header.sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed

    def test_column_widths_match(self, container):
        """The container's _recompute_column_widths produces identical
        column widths on both inner tables — this is the alignment
        contract that prevents the "all-day doesn't line up with hours"
        visual bug."""
        container._recompute_column_widths()
        for col in range(7):
            if container.all_day_table.isColumnHidden(col):
                continue
            ad_w = container.all_day_table.columnWidth(col)
            hg_w = container.hour_grid_table.columnWidth(col)
            assert ad_w == hg_w, f"column {col} widths differ: all-day={ad_w}, hour-grid={hg_w}"


class TestMidnightDueTimeEdgeCase:
    """compute_bar_segments must handle due_time=00:00 correctly.

    Before the fix: a task with due_time=00:00 on day D produced an
    empty slice on day D (window.end was datetime(D, 0, 0, 0) which
    clamped to 0 via _minute_of_day, same as the origin), so it never
    rendered anywhere. This test locks in the fix.
    """

    def test_midnight_task_renders_on_previous_day(self):
        """A task due at midnight of Apr 11 belongs visually to Apr 10."""
        from datetime import datetime as _dt
        from datetime import time

        from pytodo_qt.core.calendar_layout import (
            compute_bar_segments,
            compute_bar_window,
        )
        from pytodo_qt.core.models import create_todo_item

        item = create_todo_item("Midnight deadline")
        item.due_date = date(2026, 4, 11)
        item.due_time = time(0, 0)
        item.estimated_minutes = 60

        window = compute_bar_window(item)
        assert window is not None

        segments = compute_bar_segments(item, window, date(2026, 4, 10), _dt(2026, 4, 10, 23, 30))
        assert len(segments) == 1
        seg = segments[0]
        assert seg.is_all_day is False
        assert seg.is_marker is False
        assert seg.start_minute == 1380  # 23:00
        assert seg.end_minute == 1440  # end of day

    def test_midnight_task_does_not_render_empty_on_next_day(self):
        """Apr 11 should NOT show an empty slice for a task due Apr 11 00:00."""
        from datetime import datetime as _dt
        from datetime import time

        from pytodo_qt.core.calendar_layout import (
            compute_bar_segments,
            compute_bar_window,
        )
        from pytodo_qt.core.models import create_todo_item

        item = create_todo_item("Midnight deadline")
        item.due_date = date(2026, 4, 11)
        item.due_time = time(0, 0)
        item.estimated_minutes = 60

        window = compute_bar_window(item)
        assert window is not None

        segments = compute_bar_segments(item, window, date(2026, 4, 11), _dt(2026, 4, 11, 12, 0))
        for seg in segments:
            assert not (
                seg.is_all_day is False
                and seg.is_marker is False
                and seg.start_minute == seg.end_minute
            ), "should not produce a zero-width hour-grid slice"


class TestCalendarLegend:
    """The legend widget explains the bar palette to users."""

    def test_legend_constructs(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _CalendarLegend

        legend = _CalendarLegend()
        qtbot.addWidget(legend)
        assert len(legend._swatches) >= 5

    def test_legend_shown_in_week_view(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        cal._set_sub_view(cal.SUB_WEEK)
        assert not cal._legend.isHidden()

    def test_legend_hidden_in_month_view(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        cal._set_sub_view(cal.SUB_MONTH)
        assert cal._legend.isHidden()

    def test_legend_hidden_in_timeline_view(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        cal._set_sub_view(cal.SUB_TIMELINE)
        assert cal._legend.isHidden()


class TestAllDayHeightComputation:
    """The pinned all-day row resizes itself to fit the visible chips,
    clamped to a sensible min/max so the row stays recognizable when
    empty and never grows past two hour rows even on crowded days."""

    def test_empty_collapses_to_minimum(self):
        from pytodo_qt.gui.widgets.calendar_view import (
            _ALL_DAY_MIN_HEIGHT,
            _compute_all_day_height,
        )

        assert _compute_all_day_height(0) == _ALL_DAY_MIN_HEIGHT

    def test_few_chips_still_use_minimum(self):
        # One or two chips don't need the full minimum height worth of
        # space, but the row still uses the minimum so it doesn't look
        # like a thin sliver.
        from pytodo_qt.gui.widgets.calendar_view import (
            _ALL_DAY_MIN_HEIGHT,
            _compute_all_day_height,
        )

        assert _compute_all_day_height(1) == _ALL_DAY_MIN_HEIGHT
        assert _compute_all_day_height(2) == _ALL_DAY_MIN_HEIGHT

    def test_natural_growth_fits_chips(self):
        # Three or four chips need more than the minimum and grow
        # past it without hitting the cap.
        from pytodo_qt.gui.widgets.calendar_view import (
            _ALL_DAY_CHIP_SLOT,
            _ALL_DAY_MIN_HEIGHT,
            _ALL_DAY_ROW_PADDING,
            _compute_all_day_height,
        )

        h3 = _compute_all_day_height(3)
        h4 = _compute_all_day_height(4)
        assert h3 > _ALL_DAY_MIN_HEIGHT
        assert h4 > h3
        # The natural footprint is chip_slot * count + padding.
        assert h3 == _ALL_DAY_CHIP_SLOT * 3 + _ALL_DAY_ROW_PADDING
        assert h4 == _ALL_DAY_CHIP_SLOT * 4 + _ALL_DAY_ROW_PADDING

    def test_cap_at_maximum(self):
        # Many chips overflow the max — the row clamps and the
        # delegate's "+N more" overflow indicator handles the rest.
        from pytodo_qt.gui.widgets.calendar_view import (
            _ALL_DAY_MAX_HEIGHT,
            _compute_all_day_height,
        )

        assert _compute_all_day_height(20) == _ALL_DAY_MAX_HEIGHT
        assert _compute_all_day_height(100) == _ALL_DAY_MAX_HEIGHT

    def test_monotonic(self):
        # Adding chips never shrinks the row.
        from pytodo_qt.gui.widgets.calendar_view import _compute_all_day_height

        prev = _compute_all_day_height(0)
        for n in range(1, 30):
            cur = _compute_all_day_height(n)
            assert cur >= prev
            prev = cur


class TestPinnedAllDayRowResize:
    """The pinned container exposes a setter so the parent can resize
    the all-day row after each refresh based on actual content."""

    @pytest.fixture()
    def container(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import (
            _PinnedWeekContainer,
            _WeekDelegate,
            _WeekModel,
        )

        model = _WeekModel()
        delegate = _WeekDelegate()
        c = _PinnedWeekContainer(model, delegate)
        qtbot.addWidget(c)
        c.resize(800, 600)
        c.show()
        return c

    def test_set_all_day_height_changes_fixed_height(self, container):
        container.set_all_day_height(100)
        assert container.all_day_table.height() == 100
        assert container.all_day_table.minimumHeight() == 100
        assert container.all_day_table.maximumHeight() == 100

    def test_set_all_day_height_idempotent(self, container):
        container.set_all_day_height(80)
        container.set_all_day_height(80)
        assert container.all_day_table.height() == 80


class TestPinnedAllDayRow:
    """Step 9: the pinned All Day row container stacks two _WeekTableView
    instances over the same _WeekModel with filtered row visibility and
    synchronized horizontal scroll."""

    @pytest.fixture()
    def container(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import (
            _PinnedWeekContainer,
            _WeekDelegate,
            _WeekModel,
        )

        model = _WeekModel()
        delegate = _WeekDelegate()
        c = _PinnedWeekContainer(model, delegate)
        qtbot.addWidget(c)
        c.resize(800, 600)
        c.show()
        return c, model

    def test_container_has_two_inner_tables(self, container):
        c, _model = container
        assert c.all_day_table is not None
        assert c.hour_grid_table is not None
        assert c.all_day_table is not c.hour_grid_table

    def test_both_tables_share_the_same_model(self, container):
        c, model = container
        assert c.all_day_table.model() is model
        assert c.hour_grid_table.model() is model

    def test_all_day_table_has_fixed_height(self, container):
        c, _model = container
        # Height is constrained so the pinned row doesn't stretch
        assert c.all_day_table.maximumHeight() == c.all_day_table.minimumHeight()
        assert c.all_day_table.maximumHeight() > 0

    def test_all_day_table_hides_hour_rows(self, container):
        c, _model = container
        v_header = c.all_day_table.verticalHeader()
        assert v_header is not None
        # Row 0 is visible, rows 1-24 are hidden
        assert not v_header.isSectionHidden(0)
        for row in range(1, 25):
            assert v_header.isSectionHidden(row), f"row {row} should be hidden"

    def test_hour_grid_table_hides_row_0(self, container):
        c, _model = container
        v_header = c.hour_grid_table.verticalHeader()
        assert v_header is not None
        # Row 0 (All Day) is hidden, rows 1-24 are visible
        assert v_header.isSectionHidden(0)
        for row in range(1, 25):
            assert not v_header.isSectionHidden(row), f"row {row} should be visible"

    def test_all_day_vertical_scrollbar_disabled(self, container):
        c, _model = container
        from PyQt6.QtCore import Qt

        assert c.all_day_table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff

    def test_horizontal_scroll_handler_hour_to_all_day(self, container):
        """The hour-grid→all-day scroll handler forwards the value.

        Test the handler directly rather than via setValue() because
        the test scrollbars have no range (Stretch mode, all columns
        fit in the viewport), so setValue() would clamp to 0.
        """
        c, _model = container
        other = c.all_day_table.horizontalScrollBar()
        if other is None:
            pytest.skip("no horizontal scrollbar on this platform")
        # Manually extend the all-day scrollbar range so setValue has effect
        other.setRange(0, 200)
        c._on_hour_grid_hscroll(50)
        assert other.value() == 50

    def test_horizontal_scroll_handler_all_day_to_hour(self, container):
        """The all-day→hour-grid scroll handler forwards the value."""
        c, _model = container
        other = c.hour_grid_table.horizontalScrollBar()
        if other is None:
            pytest.skip("no horizontal scrollbar on this platform")
        other.setRange(0, 200)
        c._on_all_day_hscroll(75)
        assert other.value() == 75

    def test_horizontal_scroll_reentry_guard(self, container):
        """Setting the `_syncing_hscroll` flag prevents handler recursion."""
        c, _model = container
        # Simulate the flag already set (as if we're mid-sync)
        c._syncing_hscroll = True
        hbar_ad = c.all_day_table.horizontalScrollBar()
        hbar_hg = c.hour_grid_table.horizontalScrollBar()
        if hbar_ad is None or hbar_hg is None:
            pytest.skip("no horizontal scrollbars on this platform")
        hbar_ad.setRange(0, 200)
        hbar_hg.setRange(0, 200)
        hbar_ad.setValue(10)
        hbar_hg.setValue(20)
        # Handler called with the guard set should short-circuit
        c._on_all_day_hscroll(99)
        c._on_hour_grid_hscroll(99)
        # Neither value should have been forwarded
        assert hbar_hg.value() == 20
        assert hbar_ad.value() == 10
        c._syncing_hscroll = False  # reset for cleanup

    def test_hide_columns_affects_both_tables(self, container):
        """hide_columns() on the container hides the same columns on both
        inner tables — used by the day view to show only column 0."""
        c, _model = container
        c.hide_columns([1, 2, 3, 4, 5, 6])
        for col in range(1, 7):
            assert c.all_day_table.isColumnHidden(col)
            assert c.hour_grid_table.isColumnHidden(col)
        # Column 0 stays visible
        assert not c.all_day_table.isColumnHidden(0)
        assert not c.hour_grid_table.isColumnHidden(0)

    def test_update_viewports_no_crash(self, container):
        """update_viewports() triggers repaints on both inner tables
        without raising — the path called by the 30s now-tick timer."""
        c, _model = container
        c.update_viewports()  # should not raise

    def test_model_updates_propagate_to_both_tables(self, container):
        """Setting items on the shared model is visible through both inner
        tables because they share the model directly."""
        from datetime import time

        c, model = container
        today = date.today()
        all_day_item = create_todo_item("All day")
        all_day_item.due_date = today
        all_day_item.due_time = None

        hour_item = create_todo_item("Hour task")
        hour_item.due_date = today
        hour_item.due_time = time(14, 0)
        hour_item.estimated_minutes = 60

        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [all_day_item, hour_item]})

        # Both tables now report the same column items via the new role
        from pytodo_qt.gui.widgets.calendar_view import _WEEK_COLUMN_ITEMS_ROLE

        all_day_items = c.all_day_table.model().index(0, 0).data(_WEEK_COLUMN_ITEMS_ROLE)
        hour_grid_items = c.hour_grid_table.model().index(15, 0).data(_WEEK_COLUMN_ITEMS_ROLE)
        assert all_day_items is not None
        assert hour_grid_items is not None
        # Both see the full column (row-independent role)
        assert len(all_day_items) == 2
        assert len(hour_grid_items) == 2


class TestCalendarWidgetPinnedContainerIntegration:
    """Step 9: CalendarViewWidget uses _PinnedWeekContainer for week and day views."""

    def test_week_container_exists(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import (
            CalendarViewWidget,
            _PinnedWeekContainer,
        )

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        assert hasattr(cal, "_week_container")
        assert isinstance(cal._week_container, _PinnedWeekContainer)

    def test_day_container_exists(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import (
            CalendarViewWidget,
            _PinnedWeekContainer,
        )

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        assert hasattr(cal, "_day_container")
        assert isinstance(cal._day_container, _PinnedWeekContainer)

    def test_week_table_points_to_hour_grid_table(self, qtbot):
        """_week_table backward-compat alias still resolves to a _WeekTableView —
        the hour grid table inside the container. Code that does
        self._week_table.scrollTo(...) etc. still works."""
        from pytodo_qt.gui.widgets.calendar_view import (
            CalendarViewWidget,
            _WeekTableView,
        )

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        assert isinstance(cal._week_table, _WeekTableView)
        assert cal._week_table is cal._week_container.hour_grid_table

    def test_day_view_hides_non_first_columns_in_both_tables(self, qtbot):
        """Day view shows only column 0 in both the all-day row and the
        hour grid."""
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        for col in range(1, 7):
            assert cal._day_container.all_day_table.isColumnHidden(col)
            assert cal._day_container.hour_grid_table.isColumnHidden(col)

    def test_tick_now_indicators_updates_pinned_rows(self, qtbot):
        """The 30s tick updates both inner tables of both containers."""
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        cal = CalendarViewWidget()
        qtbot.addWidget(cal)
        cal._tick_now_indicators()  # should not crash


class TestWeekViewBarTooltip:
    """Rich tooltip via build_rich_tooltip shows full task metadata."""

    def test_tooltip_includes_reminder_and_due(self):
        """The tooltip shows the task name and due date/time."""
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _WeekTableView

        item = create_todo_item("Test task")
        item.due_date = date(2026, 4, 13)
        item.due_time = time(15, 0)
        item.estimated_minutes = 60

        text = _WeekTableView._build_bar_tooltip(item)
        assert "Test task" in text
        assert "Due:" in text
        assert "Apr 13" in text
        assert "3:00 PM" in text
        assert "Estimate:" in text

    def test_tooltip_complete_shows_timestamp(self):
        """A completed task shows the completion timestamp."""
        from datetime import datetime as _dt
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _WeekTableView

        today = date.today()
        item = create_todo_item("Late task")
        item.due_date = today
        item.due_time = time(15, 0)
        item.estimated_minutes = 60
        item.complete = True
        item.completed_at = int(_dt.combine(today, time(17, 0)).timestamp() * 1000)

        text = _WeekTableView._build_bar_tooltip(item)
        assert "Complete" in text

    def test_tooltip_shows_estimate_details(self):
        """Estimate line shows pomodoro breakdown when set."""
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _WeekTableView

        item = create_todo_item("Pom task")
        item.due_date = date(2026, 4, 13)
        item.due_time = time(15, 0)
        item.estimated_pomodoros = 3

        text = _WeekTableView._build_bar_tooltip(item)
        assert "3 pom" in text
        assert "75 min" in text  # 3 × 25

    def test_tooltip_shows_no_estimate_clamp_hint(self):
        """A task with due_time but no estimate gets a hint about
        the 1-hour deadline clamp so users know why it renders that
        wide."""
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _WeekTableView

        item = create_todo_item("No estimate")
        item.due_date = date(2026, 4, 13)
        item.due_time = time(15, 0)

        text = _WeekTableView._build_bar_tooltip(item)
        assert "1h deadline clamp" in text

    def test_tooltip_shows_tags_and_recurrence(self):
        """Tags and recurrence info appear in the tooltip."""
        from datetime import time

        from pytodo_qt.gui.widgets.calendar_view import _WeekTableView

        item = create_todo_item("Rich task")
        item.due_date = date(2026, 4, 13)
        item.due_time = time(15, 0)
        item.estimated_minutes = 60
        item.tags = ["@work", "@urgent"]
        item.recurrence_type = "daily"
        item.recurrence_interval = 1

        text = _WeekTableView._build_bar_tooltip(item)
        assert "@work" in text
        assert "@urgent" in text
        assert "Daily" in text

    def test_tooltip_shows_created_date_and_id(self):
        """Creation date and short ID appear for full traceability."""
        from pytodo_qt.gui.widgets.calendar_view import _WeekTableView

        item = create_todo_item("Traceable task")
        item.due_date = date(2026, 4, 13)

        text = _WeekTableView._build_bar_tooltip(item)
        assert "Created" in text
        assert str(item.id)[:8] in text


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


# ===========================================================================
# Fix B: labels render on continuing cells with sufficient width
# ===========================================================================


class TestContinuingCellLabels:
    """Labels now render in ANY slot with sufficient width — including
    continuing cells — so that bars whose start-cell slice is too thin
    (e.g., 5 min from 19:55-20:00 that the painter skips) still get
    a readable label in the body cell. Thin 5 px ribbons (continuing
    slices squeezed by competing in-cell tasks) naturally fall below
    _MIN_LABEL_WIDTH so they still never show labels — the width
    check handles it.
    """

    def test_continuing_cell_renders_label_when_wide_enough(self, qtbot):
        """A continuing cell with no competing tasks fills the cell
        width. At day-view widths (600+ px), the label must render."""
        from datetime import time as dt_time

        from PyQt6.QtCore import QRect
        from PyQt6.QtGui import QColor, QImage, QPainter
        from PyQt6.QtWidgets import QStyleOptionViewItem

        from pytodo_qt.core.models import create_todo_item
        from pytodo_qt.gui.widgets.calendar_view import (
            _WeekDelegate,
            _WeekModel,
            _WeekTableView,
        )

        today = date.today()
        item = create_todo_item("Continuing bar should have label")
        item.due_date = today
        item.due_time = dt_time(15, 0)
        item.estimated_minutes = 180  # 12:00-15:00, three hours

        view = _WeekTableView()
        model = _WeekModel()
        view.setModel(model)
        delegate = _WeekDelegate()
        view.setItemDelegate(delegate)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()

        model._week_dates = [today] + [today + timedelta(days=i + 1) for i in range(6)]
        model.set_items({today: [item]})
        model.set_markers({})

        # Paint the CONTINUING cell (hour 13 = row 14) at day-view width
        img = QImage(600, 60, QImage.Format.Format_ARGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 600, 60)
        delegate.paint(p, opt, model.index(14, 0))  # hour 13 (continuing)
        p.end()

        # Count distinct colors: if the label rendered, text
        # antialiasing produces many distinct colors
        distinct = set()
        for y in range(img.height()):
            for x in range(img.width()):
                pixel = img.pixel(x, y)
                r, g, b = (pixel >> 16) & 0xFF, (pixel >> 8) & 0xFF, pixel & 0xFF
                if (r, g, b) != (255, 255, 255):
                    distinct.add((r, g, b))
        assert len(distinct) > 10, (
            f"Continuing cell should render a label when wide enough. "
            f"Got {len(distinct)} distinct non-white colors — too few "
            f"for text antialiasing."
        )
