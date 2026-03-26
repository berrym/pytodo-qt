"""CalDAV import/export via iCalendar VTODO format (RFC 5545).

Provides file-based export and import of TodoList/TodoItem data using the
standard .ics format understood by Thunderbird, Apple Reminders, Nextcloud
Tasks, and other calendar/todo applications.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

from icalendar import Calendar, Todo
from icalendar.cal import Component

from pytodo_qt.core.models import TodoItem, create_todo_item

if TYPE_CHECKING:
    from pytodo_qt.core.models import TodoList

# Priority mapping: pytodo-qt (1-3) ↔ iCalendar (1-9)
_PRIORITY_TO_ICAL = {1: 1, 2: 5, 3: 9}
_RECURRENCE_TYPE_TO_FREQ = {
    "minutely": "MINUTELY",
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "monthly": "MONTHLY",
    "yearly": "YEARLY",
}
_FREQ_TO_RECURRENCE_TYPE = {v: k for k, v in _RECURRENCE_TYPE_TO_FREQ.items()}


def _ms_to_utc_datetime(ms: int) -> datetime:
    """Convert millisecond timestamp to timezone-aware UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _ical_priority_to_pytodo(ical_priority: int) -> int:
    """Map iCalendar priority (0-9) to pytodo-qt priority (1-3)."""
    if ical_priority == 0:
        return 2  # Undefined → Normal
    if ical_priority <= 4:
        return 1  # High
    if ical_priority == 5:
        return 2  # Normal
    return 3  # Low (6-9)


def _build_rrule(item: TodoItem) -> dict[str, object] | None:
    """Build an RRULE dict from item recurrence fields."""
    if not item.recurrence_type:
        return None

    freq = _RECURRENCE_TYPE_TO_FREQ.get(item.recurrence_type)
    if not freq:
        return None

    rule: dict[str, object] = {"FREQ": [freq]}
    if item.recurrence_interval > 1:
        rule["INTERVAL"] = [item.recurrence_interval]
    if item.recurrence_end_date:
        rule["UNTIL"] = [
            datetime(
                item.recurrence_end_date.year,
                item.recurrence_end_date.month,
                item.recurrence_end_date.day,
                tzinfo=UTC,
            )
        ]
    elif item.recurrence_end_count:
        rule["COUNT"] = [item.recurrence_end_count]
    return rule


def _item_to_vtodo(item: TodoItem) -> Todo:
    """Convert a TodoItem to an iCalendar VTODO component."""
    todo = Todo()
    todo.add("uid", str(item.id))
    todo.add("summary", item.reminder)
    todo.add("priority", _PRIORITY_TO_ICAL.get(item.priority, 5))
    todo.add("status", "COMPLETED" if item.complete else "NEEDS-ACTION")
    todo.add("percent-complete", 100 if item.complete else 0)

    # Always export DUE as datetime (RFC 5545 compliance).
    # Date-only items use midnight UTC — imported back as date-only
    # via the time(0,0,0) check in _vtodo_to_item.
    if item.due_date:
        if item.due_time:
            todo.add(
                "due",
                datetime(
                    item.due_date.year,
                    item.due_date.month,
                    item.due_date.day,
                    item.due_time.hour,
                    item.due_time.minute,
                    item.due_time.second,
                    tzinfo=UTC,
                ),
            )
        else:
            todo.add(
                "due",
                datetime(
                    item.due_date.year,
                    item.due_date.month,
                    item.due_date.day,
                    tzinfo=UTC,
                ),
            )

    # Strip @ prefix from tags for standard CATEGORIES format
    if item.tags:
        clean_tags = [t.lstrip("@") for t in item.tags]
        todo.add("categories", clean_tags)

    todo.add("created", _ms_to_utc_datetime(item.created_at))
    todo.add("last-modified", _ms_to_utc_datetime(item.updated_at))

    rrule = _build_rrule(item)
    if rrule:
        todo.add("rrule", rrule)

    return todo


def export_list_to_ics(todo_list: TodoList) -> bytes:
    """Export a TodoList as iCalendar VTODO data.

    Returns the .ics file content as bytes.
    """
    cal = Calendar()
    cal.add("prodid", "-//pytodo-qt//EN")
    cal.add("version", "2.0")

    for item in todo_list.items.values():
        if not item.deleted:
            cal.add_component(_item_to_vtodo(item))

    return cal.to_ical()


def import_ics_to_items(data: bytes) -> list[TodoItem]:
    """Parse iCalendar data and return new TodoItems.

    Each imported item gets a fresh UUID. Returns an empty list if no
    VTODO components are found.
    """
    cal = Calendar.from_ical(data)
    items: list[TodoItem] = []

    for component in cal.walk("VTODO"):
        item = _vtodo_to_item(component)
        if item:
            items.append(item)

    return items


def _vtodo_to_item(vtodo: Component) -> TodoItem | None:
    """Convert a VTODO component to a TodoItem."""
    summary = vtodo.get("summary")
    if not summary:
        return None

    item = create_todo_item(str(summary))

    # Priority
    priority_val = vtodo.get("priority")
    if priority_val is not None:
        item.priority = _ical_priority_to_pytodo(int(priority_val))

    # Completion
    status = vtodo.get("status")
    if status:
        item.complete = str(status).upper() == "COMPLETED"

    # Due date/time
    due = vtodo.get("due")
    if due is not None:
        dt = due.dt
        if isinstance(dt, datetime):
            item.due_date = dt.date()
            t = dt.time()
            if t != time(0, 0, 0):
                item.due_time = t
        elif isinstance(dt, date):
            item.due_date = dt

    # Tags — re-add @ prefix for pytodo-qt convention
    categories = vtodo.get("categories")
    if categories is not None:
        raw_tags: list[str] = []
        if hasattr(categories, "to_ical"):
            # Single categories property — decode the comma-separated value
            raw = categories.to_ical()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            raw_tags = [c.strip() for c in raw.split(",") if c.strip()]
        elif isinstance(categories, list):
            raw_tags = [str(c) for c in categories]
        # Ensure @ prefix
        item.tags = [t if t.startswith("@") else f"@{t}" for t in raw_tags]

    # Timestamps
    created = vtodo.get("created")
    if created is not None:
        dt = created.dt
        if isinstance(dt, datetime):
            item.created_at = int(dt.timestamp() * 1000)

    last_modified = vtodo.get("last-modified")
    if last_modified is not None:
        dt = last_modified.dt
        if isinstance(dt, datetime):
            item.updated_at = int(dt.timestamp() * 1000)

    # Recurrence
    rrule = vtodo.get("rrule")
    if rrule:
        freq_list = rrule.get("FREQ", [])
        if freq_list:
            freq = str(freq_list[0])
            rtype = _FREQ_TO_RECURRENCE_TYPE.get(freq)
            if rtype:
                item.recurrence_type = rtype

        interval_list = rrule.get("INTERVAL", [])
        if interval_list:
            item.recurrence_interval = int(interval_list[0])

        until_list = rrule.get("UNTIL", [])
        if until_list:
            until_val = until_list[0]
            if isinstance(until_val, datetime):
                item.recurrence_end_date = until_val.date()
            elif isinstance(until_val, date):
                item.recurrence_end_date = until_val

        count_list = rrule.get("COUNT", [])
        if count_list:
            item.recurrence_end_count = int(count_list[0])

    return item
