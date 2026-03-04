# CalDAV Import/Export — Design Document

## Purpose

Enable interoperability between pytodo-qt and the broader calendar/todo ecosystem via the iCalendar standard (RFC 5545). Users can export their lists as `.ics` files that open in any calendar app, and import `.ics` files from other apps into pytodo-qt. This preserves the no-cloud philosophy while enabling data portability — users can move their data in and out without vendor lock-in.

## Why iCalendar / VTODO

The iCalendar format (`.ics` files) is the universal interchange format for calendar and task data. Every major calendar and todo application supports it:

| Application | Platform | VTODO Support |
|-------------|----------|---------------|
| Thunderbird | Cross-platform | Full read/write |
| Apple Reminders | macOS/iOS | Import/export |
| GNOME Calendar | Linux | Read |
| Nextcloud Tasks | Web | Full CalDAV |
| Outlook | Windows | Import |
| Google Calendar | Web | Limited (events only, not tasks) |
| Fantastical | macOS/iOS | Full read/write |
| DAVx5 | Android | CalDAV sync |

By supporting VTODO export/import, pytodo-qt becomes interoperable with this entire ecosystem without requiring any cloud dependency or account creation.

## Field Mapping

### Export: TodoItem → VTODO

| TodoItem Field | VTODO Property | Mapping Logic |
|----------------|---------------|---------------|
| `id` (UUID) | `UID` | Direct: `str(item.id)` |
| `reminder` | `SUMMARY` | Direct: text content |
| `priority` | `PRIORITY` | Map: 1(High)→1, 2(Normal)→5, 3(Low)→9 |
| `complete` | `STATUS` | Map: True→`COMPLETED`, False→`NEEDS-ACTION` |
| `complete` | `PERCENT-COMPLETE` | Map: True→100, False→0 |
| `due_date` | `DUE` | Date-only: `DATE` value type |
| `due_date` + `due_time` | `DUE` | Date+time: `DATE-TIME` value type |
| `tags` | `CATEGORIES` | Comma-separated list |
| `created_at` | `CREATED` | Millisecond timestamp → `DATE-TIME` |
| `updated_at` | `LAST-MODIFIED` | Millisecond timestamp → `DATE-TIME` |
| `recurrence_type` + `recurrence_interval` | `RRULE` | See recurrence mapping below |
| `recurrence_end_date` | `RRULE;UNTIL=` | Date value in RRULE |
| `recurrence_end_count` | `RRULE;COUNT=` | Integer in RRULE |

### Import: VTODO → TodoItem

| VTODO Property | TodoItem Field | Mapping Logic |
|---------------|----------------|---------------|
| `UID` | — | Ignored; new UUID generated for each import |
| `SUMMARY` | `reminder` | Direct text |
| `PRIORITY` | `priority` | Map: 1-4→1(High), 5→2(Normal), 6-9→3(Low), 0/absent→2 |
| `STATUS` | `complete` | Map: `COMPLETED`→True, else→False |
| `DUE` | `due_date` / `due_time` | Parse DATE or DATE-TIME |
| `CATEGORIES` | `tags` | Split comma-separated list |
| `CREATED` | `created_at` | DATE-TIME → millisecond timestamp |
| `LAST-MODIFIED` | `updated_at` | DATE-TIME → millisecond timestamp |
| `RRULE` | recurrence fields | See recurrence mapping below |
| `DESCRIPTION` | — | Not mapped (no description field on TodoItem) |
| `DTSTART` | — | Not mapped (pytodo-qt has no start date concept) |
| `GEO` | — | Not mapped |
| `ATTACH` | — | Not mapped |

### Recurrence Mapping

#### Export: pytodo-qt → RRULE

| `recurrence_type` | `recurrence_interval` | RRULE |
|-------------------|-----------------------|-------|
| `"daily"` | 1 | `FREQ=DAILY` |
| `"daily"` | 3 | `FREQ=DAILY;INTERVAL=3` |
| `"weekly"` | 1 | `FREQ=WEEKLY` |
| `"weekly"` | 2 | `FREQ=WEEKLY;INTERVAL=2` |
| `"monthly"` | 1 | `FREQ=MONTHLY` |
| `"yearly"` | 1 | `FREQ=YEARLY` |

With optional end conditions:
- `recurrence_end_date` → `UNTIL=20260315`
- `recurrence_end_count` → `COUNT=10`

#### Import: RRULE → pytodo-qt

| RRULE Component | Field | Notes |
|----------------|-------|-------|
| `FREQ=DAILY` | `recurrence_type="daily"` | |
| `FREQ=WEEKLY` | `recurrence_type="weekly"` | |
| `FREQ=MONTHLY` | `recurrence_type="monthly"` | |
| `FREQ=YEARLY` | `recurrence_type="yearly"` | |
| `INTERVAL=N` | `recurrence_interval=N` | Default 1 if absent |
| `UNTIL=date` | `recurrence_end_date=date` | |
| `COUNT=N` | `recurrence_end_count=N` | |
| `BYDAY`, `BYMONTH`, etc. | — | Not supported (silently ignored) |

Advanced RRULE features (BYDAY, BYMONTHDAY, BYSETPOS, EXDATE) are not supported in pytodo-qt's recurrence model. These are silently ignored during import — the base frequency and interval are still captured.

## Priority Scale Mapping

iCalendar uses a 0-9 priority scale (0=undefined, 1=highest, 9=lowest). pytodo-qt uses a 1-3 scale. The mapping:

```
iCal 1-4  ←→  pytodo-qt 1 (High)
iCal 5    ←→  pytodo-qt 2 (Normal)
iCal 6-9  ←→  pytodo-qt 3 (Low)
iCal 0    ←→  pytodo-qt 2 (Normal) [undefined → default]
```

This mapping is lossy — a round trip through export/import may shift iCal priority 3 to pytodo-qt High (1) and back to iCal priority 1. This is acceptable because pytodo-qt's three-level model is intentionally simple.

## Data Flow

### Export Flow

```
User: File → Export List as .ics...
         │
         ▼
┌─────────────────────┐
│  QFileDialog         │
│  getSaveFileName()   │
│  filter: "*.ics"     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  export_list_to_ics()│
│                      │
│  TodoList            │
│   → Calendar()       │
│   → for item in list:│
│       → VTODO()      │
│       → map fields   │
│   → cal.to_ical()    │
└──────────┬──────────┘
           │ bytes
           ▼
┌─────────────────────┐
│  Write to file       │
│  path.write_bytes()  │
└──────────┬──────────┘
           │
           ▼
  Status bar: "Exported 12 items to Shopping.ics"
```

### Import Flow

```
User: File → Import from .ics...
         │
         ▼
┌─────────────────────┐
│  QFileDialog         │
│  getOpenFileName()   │
│  filter: "*.ics"     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Read file bytes     │
│  path.read_bytes()   │
└──────────┬──────────┘
           │ bytes
           ▼
┌─────────────────────┐
│  import_ics_to_items()│
│                      │
│  Calendar.from_ical()│
│   → for vtodo in cal:│
│       → TodoItem()   │
│       → map fields   │
│       → new UUID     │
│   → return items[]   │
└──────────┬──────────┘
           │ list[TodoItem]
           ▼
┌─────────────────────────────────────┐
│  Add items to active list           │
│  (or prompt to create new list)     │
│                                     │
│  for item in items:                 │
│      active_list.add_item(item)     │
│      database.save_item(item)       │
└──────────┬──────────────────────────┘
           │
           ▼
  Status bar: "Imported 15 items (3 completed) from Tasks.ics"
  UI refreshes to show new items
```

## Library: icalendar

The `icalendar` Python package (PyPI: `icalendar>=6.0`) provides:

- RFC 5545 compliant iCalendar parser and generator
- Pure Python, no system dependencies
- Cross-platform (Linux, macOS, Windows)
- Well-maintained, actively developed
- Handles timezone-aware and naive datetimes
- Supports VTODO, VEVENT, and all standard components

Example usage:

```python
from icalendar import Calendar, Todo

# Export
cal = Calendar()
cal.add("prodid", "-//pytodo-qt//EN")
cal.add("version", "2.0")

todo = Todo()
todo.add("summary", "Buy groceries")
todo.add("priority", 5)
todo.add("status", "NEEDS-ACTION")
todo.add("due", date(2026, 3, 15))
todo.add("categories", ["@errands", "@quick"])
cal.add_component(todo)

ics_bytes = cal.to_ical()

# Import
cal = Calendar.from_ical(ics_bytes)
for component in cal.walk("VTODO"):
    summary = str(component.get("summary", ""))
    priority = component.get("priority")
    ...
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Export with no active list | Show warning: "No list selected" |
| Export empty list | Export valid .ics with no VTODO components |
| Import invalid .ics file | Show error: "Could not parse file: {details}" |
| Import .ics with no VTODOs | Show info: "No tasks found in file (may contain only events)" |
| Import .ics with VEVENT only | Ignore events, report "No tasks found" |
| Import file with encoding issues | Try UTF-8, fall back to latin-1, report errors |
| Items with unmappable fields | Skip gracefully, log warning |

## Menu Integration

```
File
├── New List...            Ctrl+Shift+N
├── ─────────────
├── Import from .ics...    Ctrl+I
├── Export List as .ics... Ctrl+E
├── ─────────────
├── Print...               Ctrl+P
└── Exit
```

## Scope Boundaries

**In scope for v0.3.11:**
- File-based export (`.ics` file output)
- File-based import (`.ics` file input)
- Full VTODO field mapping as described above

**Not in scope (future consideration):**
- Live CalDAV server mode (bidirectional sync with calendar apps)
- CalDAV client mode (connecting to Nextcloud/Radicale/etc.)
- VEVENT support (pytodo-qt is a task app, not a calendar)
- Drag-and-drop `.ics` import
