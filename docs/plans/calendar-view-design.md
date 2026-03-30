# Calendar View — Complete Design Plan

**Status:** In progress — skeleton committed (64cc7a3), month view being rewritten with QTableView+Delegate

## Vision

Third view mode alongside List and Kanban Board. Provides Day, Week, Month, and Timeline sub-views with a pill toggle, navigation controls, and an unscheduled tasks sidebar panel. Tasks displayed on their due dates, draggable between dates and from the unscheduled panel.

Must appear in both desktop app (PyQt6) and web UI (vanilla JS) with feature parity.

---

## Sub-Views

### Day
24-hour vertical timeline with hourly slots. Tasks with due_time placed at their time. Tasks with due_date only shown in an "all day" section at top.

### Week
7-day columns, each with hourly slots. Same time placement logic. Most useful for planning.

### Month
Traditional grid of days. Tasks shown as compact items on their due date. Best for overview.

### Timeline
Passive analytical view (read-only, no drag-and-drop). Rendered with pyqtgraph (not QPainter). Has its own secondary pill toggle with 4 chart sub-views:

- **Tasks**: Gantt horizontal bars per task — time span (blue), estimate baseline (gray), split actual work (pomodoro red + stopwatch cyan). Pseudo-real-time bar projection during active sessions. Persistent hover tooltips with full task details. 14-day range with daily navigation.
- **Daily**: Stacked vertical bars showing pomodoro + stopwatch minutes per day, with 7-day rolling average trend line overlay. Weekly navigation.
- **Productivity**: Time block heatmap — 12 two-hour blocks with intensity-scaled color by session count and completion rate text overlays. All-time view, no navigation.
- **Accuracy**: Scatter plot of estimated vs actual minutes per item, with diagonal y=x reference line. Points colored by variance (under-estimated/accurate/over-estimated). All-time view, no navigation.

All chart data comes from `AnalyticsService` (pandas DataFrames via `pd.read_sql_query()`). Unscheduled panel hidden in timeline mode. See `docs/plans/analytics-service.md` and `docs/plans/timeline-bar-redesign.md` for full architecture.

**Default:** Week view (most actionable granularity for task management).

**Navigation:** `< Today >` buttons to move forward/backward.

---

## Unscheduled Panel

Collapsible sidebar showing all tasks with no due_date. Draggable — user drags a task onto a calendar date/time slot to assign due_date (and due_time in day/week views). The drag creates an `EditDueDateCommand` through the undo stack.

Panel shows task count, scrolls if many items, respects current filter state.

---

## Task Rendering

- **Compact item chips** on due date — reminder text, truncated with ellipsis
- **Priority color** — left border (red=high, blue=normal, gray=low)
- **Overdue** — red background/tint, carried forward to today
- **Completed** — strikethrough text, muted color
- **Recurring** — recurrence icon/indicator
- **Subtasks** — top-level only (consistent with kanban); subtask count badge
- **Focus session** — highlight for active pomodoro item
- **"+N more"** — overflow indicator when items exceed cell height, click opens popover

---

## Interaction

- **Click task** — select (enables toolbar actions)
- **Double-click task** — open edit dialog
- **Drag task between dates** — changes due_date via undo command
- **Drag from unscheduled panel** — sets due_date
- **Right-click task** — context menu
- **Click empty date** — quick-add with date pre-filled
- **Click "+N more"** — popover showing all items for that day

---

## Integration

Follows exact same patterns as TodoTableWidget and KanbanBoardWidget:

- **10 shared signals**: item_priority_changed, item_reminder_changed, item_due_date_changed, item_due_time_changed, edit_tags_requested, focus_requested, add_subtask_requested, toggle_requested, delete_requested, edit_recurrence_requested
- **Public API**: `set_list()`, `set_filter()`, `get_selected_item_ids()`, `refresh()`, `set_focus_session_item()`
- **Filter/sort**: same FilterState, same multi-tier sort within each day's items
- **Undo**: all changes through QUndoCommands
- **View mode**: stored in config as "calendar"
- **Inline toggle buttons**: [List] [Board] [Calendar]
- **Keyboard**: Ctrl+Shift+B cycles list→board→calendar→list

---

## Architecture Decision: QTableView + Custom Delegate

Research confirmed QGridLayout with QFrame cells causes unsolvable layout issues. Qt's own QCalendarWidget, Google Calendar, Apple Calendar, and FullCalendar all use model/view/delegate.

### Classes
- `_CalendarModel(QAbstractTableModel)` — 7×6 grid, data() returns TodoItem lists per date
- `_CalendarDelegate(QStyledItemDelegate)` — QPainter rendering of day numbers, task chips, overflow
- `_CalendarTableView(QTableView)` — Stretch columns, equal row heights in resizeEvent

### Key Techniques
- `header.setSectionResizeMode(Stretch)` — guaranteed equal columns
- `setRowHeight(row, viewport_height // 6)` — guaranteed equal rows
- `QFontMetrics.elidedText()` — pixel-perfect text truncation
- QPainter automatic clipping to cell rect
- Zero child widgets — all rendering via delegate paint

---

## Implementation Order

1. CalendarViewWidget skeleton (DONE — 64cc7a3)
2. Month view rewrite with QTableView+Delegate (DONE — cd11fb6)
3. MainWindow integration (DONE — 64cc7a3)
4. Week view (DONE — 4a3b6df)
5. Day view (DONE — 3fac4c3)
6. Timeline view (DONE — 183763d)
7. Calendar interaction layer + visual polish (DONE — 2fc5b1f)
8. Unscheduled panel drag-to-schedule
9. Drag-and-drop between dates
10. Web UI calendar mode
11. Calendar SVG icon for inline toggle
12. 12h/24h time toggle for day/week views
13. Tests

---

## Web UI Implementation

Add calendar as third view mode in app.js:
- Sub-view toggle pills (Day/Week/Month/Timeline)
- Navigation (< Today >)
- Month grid with task chips (CSS Grid or HTML table)
- Week view with time columns
- Day view with hourly slots
- Timeline view with horizontal bars
- Unscheduled section (collapsible)
- Drag-and-drop (touch + mouse)
- Responsive breakpoints

---

## Files

### New
- `src/pytodo_qt/gui/widgets/calendar_view.py` (EXISTS — skeleton)
- `src/pytodo_qt/gui/icons/view-calendar.svg` (EXISTS)

### Modified
- `src/pytodo_qt/gui/main_window.py` (DONE — integration)
- `src/pytodo_qt/core/config.py` (view_mode "calendar" accepted)
- `src/pytodo_qt/web/static/app.js` (web calendar)
- `src/pytodo_qt/web/static/style.css` (calendar styles)
- `src/pytodo_qt/web/static/index.html` (calendar HTML)
