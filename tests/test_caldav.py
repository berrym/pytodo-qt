"""Tests for CalDAV import/export (Phase 4).

Covers:
- Export: TodoItem → VTODO field mapping
- Import: VTODO → TodoItem field mapping
- Roundtrip: export → import preserves data
- Edge cases: empty lists, missing fields, recurrence, tags
- Priority scale mapping
"""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

import pytest
from icalendar import Calendar, Todo

from pytodo_qt.core.caldav import (
    _PRIORITY_TO_ICAL,
    _build_rrule,
    _ical_priority_to_pytodo,
    export_list_to_ics,
    import_ics_to_items,
)
from pytodo_qt.core.models import create_todo_item, create_todo_list

# ===========================================================================
# Priority mapping tests
# ===========================================================================


class TestPriorityMapping:
    def test_high_to_ical(self):
        assert _PRIORITY_TO_ICAL[1] == 1

    def test_normal_to_ical(self):
        assert _PRIORITY_TO_ICAL[2] == 5

    def test_low_to_ical(self):
        assert _PRIORITY_TO_ICAL[3] == 9

    def test_ical_undefined_to_normal(self):
        assert _ical_priority_to_pytodo(0) == 2

    def test_ical_1_to_high(self):
        assert _ical_priority_to_pytodo(1) == 1

    def test_ical_4_to_high(self):
        assert _ical_priority_to_pytodo(4) == 1

    def test_ical_5_to_normal(self):
        assert _ical_priority_to_pytodo(5) == 2

    def test_ical_6_to_low(self):
        assert _ical_priority_to_pytodo(6) == 3

    def test_ical_9_to_low(self):
        assert _ical_priority_to_pytodo(9) == 3


# ===========================================================================
# Export tests
# ===========================================================================


class TestExportBasic:
    def test_empty_list_produces_valid_ics(self):
        lst = create_todo_list("Empty")
        data = export_list_to_ics(lst)
        assert b"BEGIN:VCALENDAR" in data
        assert b"END:VCALENDAR" in data
        assert b"VTODO" not in data

    def test_single_item(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Buy milk")
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"BEGIN:VTODO" in data
        assert b"SUMMARY:Buy milk" in data

    def test_multiple_items(self):
        lst = create_todo_list("Test")
        for name in ["Task 1", "Task 2", "Task 3"]:
            lst.add_item(create_todo_item(name))

        data = export_list_to_ics(lst)
        assert data.count(b"BEGIN:VTODO") == 3

    def test_deleted_items_excluded(self):
        lst = create_todo_list("Test")
        item1 = create_todo_item("Active")
        item2 = create_todo_item("Deleted")
        item2.deleted = True
        lst.add_item(item1)
        lst.add_item(item2)

        data = export_list_to_ics(lst)
        assert data.count(b"BEGIN:VTODO") == 1
        assert b"SUMMARY:Active" in data

    def test_prodid(self):
        lst = create_todo_list("Test")
        data = export_list_to_ics(lst)
        assert b"PRODID:-//pytodo-qt//EN" in data


class TestExportFieldMapping:
    def test_uid(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Test")
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert str(item.id).encode() in data

    def test_priority_high(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Test")
        item.priority = 1
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"PRIORITY:1" in data

    def test_priority_low(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Test")
        item.priority = 3
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"PRIORITY:9" in data

    def test_completed_status(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Done")
        item.complete = True
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"STATUS:COMPLETED" in data
        assert b"PERCENT-COMPLETE:100" in data

    def test_incomplete_status(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Todo")
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"STATUS:NEEDS-ACTION" in data
        assert b"PERCENT-COMPLETE:0" in data

    def test_due_date_only(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Test")
        item.due_date = date(2026, 3, 15)
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"DUE" in data
        assert b"20260315" in data

    def test_due_date_with_time(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Test")
        item.due_date = date(2026, 3, 15)
        item.due_time = time(14, 30)
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"DUE" in data
        assert b"20260315T143000" in data

    def test_tags_as_categories(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Test")
        item.tags = ["@work", "@urgent"]
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"CATEGORIES" in data
        assert b"@work" in data
        assert b"@urgent" in data

    def test_created_timestamp(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Test")
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"CREATED" in data

    def test_last_modified(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Test")
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"LAST-MODIFIED" in data


class TestExportRecurrence:
    def test_daily_recurrence(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Daily")
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"RRULE" in data
        assert b"FREQ=DAILY" in data

    def test_weekly_with_interval(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Biweekly")
        item.recurrence_type = "weekly"
        item.recurrence_interval = 2
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"FREQ=WEEKLY" in data
        assert b"INTERVAL=2" in data

    def test_monthly(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Monthly")
        item.recurrence_type = "monthly"
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"FREQ=MONTHLY" in data

    def test_yearly(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Yearly")
        item.recurrence_type = "yearly"
        lst.add_item(item)

        data = export_list_to_ics(lst)
        assert b"FREQ=YEARLY" in data

    def test_recurrence_with_end_count(self):
        item = create_todo_item("Test")
        item.recurrence_type = "daily"
        item.recurrence_end_count = 10
        rrule = _build_rrule(item)
        assert rrule is not None
        assert rrule["COUNT"] == [10]

    def test_recurrence_with_end_date(self):
        item = create_todo_item("Test")
        item.recurrence_type = "daily"
        item.recurrence_end_date = date(2026, 12, 31)
        rrule = _build_rrule(item)
        assert rrule is not None
        until = rrule["UNTIL"]
        assert isinstance(until, list)
        assert len(until) == 1

    def test_no_recurrence(self):
        item = create_todo_item("Test")
        assert _build_rrule(item) is None

    def test_interval_1_not_in_rrule(self):
        item = create_todo_item("Test")
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        rrule = _build_rrule(item)
        assert rrule is not None
        assert "INTERVAL" not in rrule


# ===========================================================================
# Import tests
# ===========================================================================


class TestImportBasic:
    def test_empty_calendar(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        items = import_ics_to_items(cal.to_ical())
        assert items == []

    def test_single_vtodo(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Buy groceries")
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert len(items) == 1
        assert items[0].reminder == "Buy groceries"

    def test_multiple_vtodos(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        for name in ["Task 1", "Task 2", "Task 3"]:
            todo = Todo()
            todo.add("summary", name)
            cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert len(items) == 3

    def test_new_uuids_generated(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Test")
        todo.add("uid", "original-uid-123")
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert len(items) == 1
        assert isinstance(items[0].id, UUID)
        assert str(items[0].id) != "original-uid-123"

    def test_vtodo_without_summary_skipped(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("uid", "no-summary")
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items == []


class TestImportFieldMapping:
    def test_priority_high(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Important")
        todo.add("priority", 1)
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].priority == 1

    def test_priority_normal(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Normal")
        todo.add("priority", 5)
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].priority == 2

    def test_priority_low(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Low")
        todo.add("priority", 9)
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].priority == 3

    def test_completed_status(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Done")
        todo.add("status", "COMPLETED")
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].complete is True

    def test_needs_action_status(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Todo")
        todo.add("status", "NEEDS-ACTION")
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].complete is False

    def test_due_date_only(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Test")
        todo.add("due", date(2026, 3, 15))
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].due_date == date(2026, 3, 15)
        assert items[0].due_time is None

    def test_due_datetime(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Test")
        todo.add("due", datetime(2026, 3, 15, 14, 30))
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].due_date == date(2026, 3, 15)
        assert items[0].due_time == time(14, 30)

    def test_tags_from_categories(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Test")
        todo.add("categories", ["@work", "@urgent"])
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert "@work" in items[0].tags
        assert "@urgent" in items[0].tags

    def test_no_priority_defaults_normal(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Test")
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].priority == 2


class TestImportRecurrence:
    def test_daily(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Daily")
        todo.add("rrule", {"FREQ": ["DAILY"]})
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].recurrence_type == "daily"
        assert items[0].recurrence_interval == 1

    def test_weekly_with_interval(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Biweekly")
        todo.add("rrule", {"FREQ": ["WEEKLY"], "INTERVAL": [2]})
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].recurrence_type == "weekly"
        assert items[0].recurrence_interval == 2

    def test_monthly(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Monthly")
        todo.add("rrule", {"FREQ": ["MONTHLY"]})
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].recurrence_type == "monthly"

    def test_yearly(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Yearly")
        todo.add("rrule", {"FREQ": ["YEARLY"]})
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].recurrence_type == "yearly"

    def test_count(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Test")
        todo.add("rrule", {"FREQ": ["DAILY"], "COUNT": [10]})
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].recurrence_end_count == 10

    def test_until(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        todo = Todo()
        todo.add("summary", "Test")
        todo.add("rrule", {"FREQ": ["DAILY"], "UNTIL": [datetime(2026, 12, 31)]})
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert items[0].recurrence_end_date == date(2026, 12, 31)


# ===========================================================================
# Roundtrip tests
# ===========================================================================


class TestRoundtrip:
    def test_basic_roundtrip(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Buy milk")
        item.priority = 1
        item.due_date = date(2026, 3, 15)
        item.tags = ["@errands"]
        lst.add_item(item)

        data = export_list_to_ics(lst)
        imported = import_ics_to_items(data)

        assert len(imported) == 1
        result = imported[0]
        assert result.reminder == "Buy milk"
        assert result.priority == 1
        assert result.due_date == date(2026, 3, 15)
        assert "@errands" in result.tags

    def test_completed_roundtrip(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Done task")
        item.complete = True
        lst.add_item(item)

        data = export_list_to_ics(lst)
        imported = import_ics_to_items(data)

        assert imported[0].complete is True

    def test_recurrence_roundtrip(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Weekly")
        item.recurrence_type = "weekly"
        item.recurrence_interval = 2
        item.due_date = date(2026, 3, 15)
        lst.add_item(item)

        data = export_list_to_ics(lst)
        imported = import_ics_to_items(data)

        assert imported[0].recurrence_type == "weekly"
        assert imported[0].recurrence_interval == 2

    def test_due_time_roundtrip(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Meeting")
        item.due_date = date(2026, 3, 15)
        item.due_time = time(14, 30)
        lst.add_item(item)

        data = export_list_to_ics(lst)
        imported = import_ics_to_items(data)

        assert imported[0].due_date == date(2026, 3, 15)
        assert imported[0].due_time == time(14, 30)

    def test_multiple_items_roundtrip(self):
        lst = create_todo_list("Test")
        for i, name in enumerate(["Task A", "Task B", "Task C"]):
            item = create_todo_item(name)
            item.priority = (i % 3) + 1
            lst.add_item(item)

        data = export_list_to_ics(lst)
        imported = import_ics_to_items(data)

        assert len(imported) == 3
        names = {item.reminder for item in imported}
        assert names == {"Task A", "Task B", "Task C"}

    def test_multiple_tags_roundtrip(self):
        lst = create_todo_list("Test")
        item = create_todo_item("Tagged")
        item.tags = ["@work", "@urgent", "@project"]
        lst.add_item(item)

        data = export_list_to_ics(lst)
        imported = import_ics_to_items(data)

        for tag in ["@work", "@urgent", "@project"]:
            assert tag in imported[0].tags


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_item_no_due_date(self):
        lst = create_todo_list("Test")
        item = create_todo_item("No date")
        lst.add_item(item)

        data = export_list_to_ics(lst)
        imported = import_ics_to_items(data)

        assert imported[0].due_date is None

    def test_item_no_tags(self):
        lst = create_todo_list("Test")
        item = create_todo_item("No tags")
        lst.add_item(item)

        data = export_list_to_ics(lst)
        imported = import_ics_to_items(data)

        assert imported[0].tags == []

    def test_item_empty_reminder(self):
        lst = create_todo_list("Test")
        item = create_todo_item("")
        lst.add_item(item)

        data = export_list_to_ics(lst)
        # Empty summary will be in the export but may not re-import
        # since we skip items without summary
        cal = Calendar.from_ical(data)
        vtodos = list(cal.walk("VTODO"))
        assert len(vtodos) == 1

    def test_vevent_ignored_on_import(self):
        """VEVENT components should be ignored, only VTODOs imported."""
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")

        from icalendar import Event

        event = Event()
        event.add("summary", "Meeting")
        event.add("dtstart", datetime(2026, 3, 15, 10, 0))
        cal.add_component(event)

        todo = Todo()
        todo.add("summary", "Task")
        cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        assert len(items) == 1
        assert items[0].reminder == "Task"

    def test_invalid_ics_raises(self):
        with pytest.raises(ValueError):
            import_ics_to_items(b"not valid ics data")

    def test_new_ids_are_unique(self):
        cal = Calendar()
        cal.add("prodid", "-//Test//EN")
        cal.add("version", "2.0")
        for _ in range(5):
            todo = Todo()
            todo.add("summary", "Same name")
            cal.add_component(todo)

        items = import_ics_to_items(cal.to_ical())
        ids = {item.id for item in items}
        assert len(ids) == 5
