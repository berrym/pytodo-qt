"""Manual visual-verification harness for time-block items on the calendar.

A task with a named time block and no clock time is drawn across its
block's window in the hour grid — "afternoon" as a bar from 12:00 to
17:00 — instead of sitting in the All Day row. This window shows the
calendar with one sample task of each kind, dated today and tomorrow, so
the placement can be checked without creating tasks by hand.

This is **not** part of the pytest suite and **not** CI-gated — it
requires a human watching the screen. It reads the configured time block
boundaries and theme. The sample tasks are never saved; switching
between Day, Week and Agenda is remembered, as it is in the application.

Run from the repo root:

    uv run python scripts/verify_calendar_blocks.py

What to check, in the Week and Day views:

- "Afternoon block" spans the afternoon rows; "Late afternoon block"
  spans the second half of them.
- "Night block" starts today at the night boundary and continues in the
  small hours of tomorrow's column.
- "Deadline 15:00" and "Event 10:00-11:00" look as they always have.
- "All day" is the only sample in the All Day row.
- "Block with a time" is placed by its time (16:00), not by its block.
- A block bar shows no resize cursor at its top or bottom edge.
- Dragging a block bar onto an hour gives the task that time; dragging
  it onto another day's All Day row moves it to that day's block.

In the Agenda view the block tasks show the block's name in the time
column and sort by the block's start.

Tracking: https://github.com/berrym/pytodo-qt/issues/58
"""

from __future__ import annotations

import sys
from datetime import date, time, timedelta
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMainWindow

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pytodo_qt.core.models import TodoItem, TodoList  # noqa: E402
from pytodo_qt.gui.styles import apply_current_theme  # noqa: E402
from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget  # noqa: E402


def sample_list() -> TodoList:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    todo_list = TodoList(name="Time block samples")
    for item in (
        TodoItem(reminder="Afternoon block", due_date=today, due_time_block="afternoon"),
        TodoItem(reminder="Late afternoon block", due_date=today, due_time_block="late_afternoon"),
        TodoItem(reminder="Night block", due_date=today, due_time_block="night"),
        TodoItem(reminder="Morning block", due_date=tomorrow, due_time_block="morning"),
        TodoItem(reminder="Evening block", due_date=tomorrow, due_time_block="evening"),
        TodoItem(reminder="Deadline 15:00", due_date=tomorrow, due_time=time(15, 0)),
        TodoItem(
            reminder="Event 10:00-11:00",
            due_date=today,
            due_time=time(10, 0),
            due_time_end=time(11, 0),
        ),
        TodoItem(reminder="All day", due_date=today),
        TodoItem(
            reminder="Block with a time",
            due_date=tomorrow,
            due_time=time(16, 0),
            due_time_block="afternoon",
            estimated_minutes=30,
        ),
    ):
        todo_list.add_item(item)
    return todo_list


def main() -> int:
    app = QApplication(sys.argv[:1])
    apply_current_theme()
    window = QMainWindow()
    window.setWindowTitle("Time blocks on the calendar")
    calendar = CalendarViewWidget()
    calendar.set_list(sample_list())
    window.setCentralWidget(calendar)
    window.resize(1200, 900)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
