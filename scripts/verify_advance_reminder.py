"""Manual visual-verification harness for the "Remind ahead" control.

An advance reminder mentions a task in the daily summary on the days
before it is due. It is set on one row — a choice of Off, Once or Every
day until due, and a day count — in the Scheduling group of the Add Todo
dialog and in the Schedule section of the detail panel.

It can also be typed into Add Todo's input line: "remind me 3 days
before", "remind me daily from a week before", "with 3 days notice".

This window hosts a real detail panel showing a sample task, and opens
the real Add Todo dialog. Both write to nothing: the sample task lives
in memory and the configuration is a scratch one. The lines under the
buttons show the fields as they would be stored.

This is **not** part of the pytest suite and **not** CI-gated — it
requires a human watching the screen. Undo of a change made in the
detail panel is part of the main window and is checked in the
application itself.

Run from the repo root:

    uv run python scripts/verify_advance_reminder.py

To see the note shown when the daily summary is switched off:

    uv run python scripts/verify_advance_reminder.py --summary-off

What to check in the detail panel (press its edit toggle first):

- "Remind ahead" reads "Off" with no day count beside or under it.
- Choosing "Once" or "Every day until due" shows the day count, and the
  stored fields under the buttons follow each change.
- "1 day before" becomes "2 days before" as the count goes up.
- Out of edit mode the row is read-only and still reads correctly.
- With "Sample task has a due date" unticked the row is greyed even in
  edit mode.

What to check with "Open Add Todo with Advanced open":

- "Remind ahead" is greyed until "Set due date" is ticked.
- Alt+I moves to the choice.
- The day count is greyed while the choice is "Off".
- After OK, the stored fields under the buttons show what the new task
  would carry.
- With --summary-off, a note under the row says the daily summary is
  off.

Still with Advanced open, type in the line at the top. The fields below
follow the line, and a field set by hand keeps its value until the line
says something new about it:

- "Tax return friday remind me 3 days before" — Title, "Set due date"
  and "Remind ahead" fill in as the words are typed, and OK stores the
  task. (Before, the fields stayed empty and OK asked for a reminder.)
- Set Priority to High by hand, then add " @taxes" to the line — the
  tag appears and Priority stays High.
- Add " p3" to the line — Priority changes to Low: the line said
  something new about it.
- Clear the line and type "Dentist". Tick "Set due date" and pick a
  date some weeks ahead by hand. Add " at 3pm" to the line — the time
  is set and the date picked by hand stays.
- Add " tomorrow" to the line — the date changes to tomorrow: a date
  written in the line replaces one picked by hand.
- Clear the line and type "Call mom remind me 2 days before" — "Remind
  ahead" shows "Once", "2 days before", greyed, and the chip says a due
  date is needed. Tick "Set due date": the row goes live and the chip
  loses its note.

What to check with "Open Add Todo for typing" (Advanced stays closed).
Type each line, look at the highlight and the chips, then press OK and
read the stored fields:

- "Tax return friday remind me 3 days before" — the phrase is coloured
  like the date, a chip reads "Remind 3 days before", the title is "Tax
  return", and no duration or recurrence chip appears.
- "Renew passport friday remind me daily from a week before" — the chip
  reads "Remind daily from 7 days before"; stored as daily_until_due.
- "Pay rent friday with 3 days notice" — the same reminder, once.
- "Call mom remind me 2 days before" — no date: the chip reads "Remind
  2 days before (needs a due date)", the phrase is still out of the
  title, and nothing is stored.
- "Water plants daily remind me 1 day before" — "daily" outside the
  phrase is still a recurrence.
- "Remind me to call mom friday" — no reminder chip; the title is "call
  mom".
- The × on the reminder chip removes the phrase from the line.
- Type "Tax return friday remind me a week before", then open Advanced:
  "Remind ahead" reads "Once", "7 days before".

What to check with "Open Add Todo as from a calendar cell" (the dialog
is given a date ten days ahead, as when a calendar day is clicked):

- "Call mom remind me 2 days before" — the chip reads "Remind 2 days
  before" with no note, and the stored task has the date and the
  reminder.

Tracking: https://github.com/berrym/pytodo-qt/issues/58
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path


def _use_scratch_directories() -> Path:
    """Point configuration, data and state away from the real ones.
    Must run before anything from the application is imported."""
    root = Path(tempfile.mkdtemp(prefix="pytodo-advance-"))
    os.environ["XDG_CONFIG_HOME"] = str(root / "config")
    os.environ["XDG_DATA_HOME"] = str(root / "data")
    os.environ["XDG_STATE_HOME"] = str(root / "state")
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--summary-off",
        action="store_true",
        help="start with the daily summary switched off in the scratch configuration",
    )
    args = parser.parse_args()

    scratch_root = _use_scratch_directories()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QLabel,
        QMainWindow,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from pytodo_qt.core.config import get_config_manager
    from pytodo_qt.core.models import create_todo_item, create_todo_list
    from pytodo_qt.gui.dialogs.add_todo import AddTodoDialog
    from pytodo_qt.gui.styles import apply_current_theme
    from pytodo_qt.gui.styles.themes import apply_font_setting, load_bundled_fonts
    from pytodo_qt.gui.widgets.detail_panel import TaskDetailPanel

    manager = get_config_manager()
    if args.summary_off:
        manager.config_file.parent.mkdir(parents=True, exist_ok=True)
        manager.config_file.write_text(
            "[notifications]\nsummary_enabled = false\n", encoding="utf-8"
        )
    config = manager.load()

    app = QApplication(sys.argv[:1])
    load_bundled_fonts()
    apply_font_setting(app, config.appearance.font)
    apply_current_theme()

    due = date.today() + timedelta(days=5)
    todo_list = create_todo_list("Sample")
    task = create_todo_item("File tax return")
    task.due_date = due
    todo_list.add_item(task)

    window = QMainWindow()
    window.setWindowTitle("Advance reminder verification")
    central = QWidget()
    layout = QVBoxLayout(central)
    intro = QLabel(
        "The detail panel on the right shows a sample task held in memory. "
        "Press its edit toggle to change <b>Remind ahead</b>."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)
    has_date = QCheckBox("Sample task has a due date")
    has_date.setChecked(True)
    layout.addWidget(has_date)
    open_add = QPushButton("Open Add Todo with Advanced open")
    layout.addWidget(open_add)
    open_typing = QPushButton("Open Add Todo for typing")
    layout.addWidget(open_typing)
    open_cell = QPushButton("Open Add Todo as from a calendar cell")
    layout.addWidget(open_cell)
    layout.addWidget(QLabel("<b>Lines to type</b> (select and copy)"))
    phrases = QLabel(
        "Tax return friday remind me 3 days before\n"
        "Renew passport friday remind me daily from a week before\n"
        "Pay rent friday with 3 days notice\n"
        "Call mom remind me 2 days before\n"
        "Water plants daily remind me 1 day before\n"
        "Remind me to call mom friday"
    )
    phrases.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(phrases)
    layout.addWidget(QLabel("<b>Sample task, as stored</b>"))
    panel_fields = QLabel()
    panel_fields.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(panel_fields)
    layout.addWidget(QLabel("<b>Last task made in Add Todo, as stored</b>"))
    dialog_fields = QLabel("(none yet)")
    dialog_fields.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(dialog_fields)
    layout.addStretch(1)
    window.setCentralWidget(central)

    panel = TaskDetailPanel(window)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, panel)

    def stored(item) -> str:
        return (
            f'reminder = "{item.reminder}"\n'
            f"due_date = {item.due_date}\n"
            f"remind_before_days = {item.remind_before_days}\n"
            f'reminder_cadence = "{item.reminder_cadence}"'
        )

    def show_task() -> None:
        panel.set_item(task, todo_list)
        panel_fields.setText(stored(task))

    def on_panel_change(_item_id: object, days: int, cadence: str) -> None:
        # What the main window does, without the undo stack.
        task.remind_before_days = days
        task.reminder_cadence = cadence
        show_task()

    def on_has_date(checked: bool) -> None:
        task.due_date = due if checked else None
        show_task()

    def run_dialog(dialog: AddTodoDialog) -> None:
        if dialog.exec():
            item = dialog.get_item()
            if item is not None:
                dialog_fields.setText(stored(item))

    def open_add_todo() -> None:
        dialog = AddTodoDialog(window)
        dialog._advanced_toggle.setChecked(True)
        run_dialog(dialog)

    def open_for_typing() -> None:
        run_dialog(AddTodoDialog(window))

    def open_from_cell() -> None:
        cell = date.today() + timedelta(days=10)
        run_dialog(AddTodoDialog(window, default_due_date=cell))

    panel.item_advance_reminder_changed.connect(on_panel_change)
    has_date.toggled.connect(on_has_date)
    open_add.clicked.connect(open_add_todo)
    open_typing.clicked.connect(open_for_typing)
    open_cell.clicked.connect(open_from_cell)
    show_task()

    window.resize(820, 760)
    window.show()
    print(f"Scratch directory: {scratch_root}")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
