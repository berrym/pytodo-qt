"""Manual verification harness for task notifications.

The left column shows every shape of task notification — lead reminders,
due-now alerts, several reminders merged into one, the daily summary,
missed items, and the evening preview — without waiting for real due
times. Each button
builds a sample result of the notification policy, formats it with the
same ``TaskNotifier`` the application uses, and delivers it through the
platform's notification channel: the in-app overlay on macOS, the
desktop's native notifications elsewhere.

The right column shows *when* notifications are given. It runs the real
notifier and policy against a scratch database and a handful of sample
tasks, with a clock that is stepped by hand, so quiet hours, the
focus-session hold and the evening preview can be watched without
waiting for the night or for a session to end. Nothing in it touches the real database or settings.

This is **not** part of the pytest suite and **not** CI-gated — it
requires a human watching the screen.

Run from the repo root:

    uv run python scripts/verify_task_notifications.py

Optional, to see times rendered in a specific format:

    uv run python scripts/verify_task_notifications.py --time-format 12h

The harness window sits in the lower-left of the primary screen so it
never covers the top-right notification stack.

Tracking: https://github.com/berrym/pytodo-qt/issues/58
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pytodo_qt.core.config import TimeBlockConfig  # noqa: E402
from pytodo_qt.core.database import DatabaseStorage  # noqa: E402
from pytodo_qt.core.models import TodoItem, TodoList  # noqa: E402
from pytodo_qt.core.notification_policy import (  # noqa: E402
    ComingUp,
    Evaluation,
    Kind,
    PolicySettings,
    Preview,
    Reminder,
    Summary,
    TimedItem,
    in_quiet_hours,
)
from pytodo_qt.gui.task_notifier import TaskNotifier  # noqa: E402
from pytodo_qt.gui.widgets.notification_overlay import NotificationManager  # noqa: E402

TODAY = date.today()
_TIMEOUT_SECONDS = 10


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(TODAY, time(hour, minute))


def _lead(title: str, when: datetime, minutes: int = 15, **fields) -> Reminder:
    fields.setdefault("is_event", False)
    fields.setdefault("block", None)
    return Reminder(uuid4(), title, Kind.LEAD, when, minutes_until=minutes, **fields)


def _due_now(title: str, when: datetime) -> Reminder:
    return Reminder(uuid4(), title, Kind.DUE_NOW, when, False, None, 0)


def _timed(title: str, when: datetime, **fields) -> TimedItem:
    fields.setdefault("is_event", False)
    fields.setdefault("block", None)
    return TimedItem(uuid4(), title, when, **fields)


_SIMULATION_START = _at(8, 55)

_SIMULATION_STEPS = """<b>Things to try</b> (press <i>Start over</i> before each):
<ol>
<li><b>Focus hold.</b> Tick <i>Focus session running</i>, press <i>+10 min</i>:
the log shows the daily summary held at 09:00. Untick it, press <i>+1 min</i>:
the summary appears.</li>
<li><b>Timed reminders pass through a session.</b> Tick <i>Focus session
running</i>, press <i>+1 hour</i>: the reminders for the expense report and
the standup appear on time while the summary stays held.</li>
<li><b>Quiet hours hold the summary.</b> Sleep until 23:30: nothing appears;
the log shows what is held. Sleep until 07:00: only the medication missed at
06:30 is reported. Sleep until 09:00: the new day's summary.</li>
<li><b>Timed reminders pass through quiet hours.</b> Sleep until 22:55, press
<i>+10 min</i>: the flight reminder appears at 23:00. With <i>Silence timed
reminders</i> ticked it is held instead.</li>
<li><b>Advance reminders.</b> Press <i>+10 min</i>: today's summary ends with
"Coming up: Book dentist in 2 days". Sleep until 09:00 three times: the next
day reads "Book dentist tomorrow, File tax return in 2 days", the day after
has no such line (the dentist is due, the tax return was mentioned once), and
neither has the last day.</li>
<li><b>Evening preview.</b> Tick <i>Evening preview</i>. Sleep until 19:59:
the day's summary appears. Press <i>+1 min</i>: at 20:00 a notification titled
"Tomorrow" reads "1 due · First: Take medication at 06:30". Press <i>+10
min</i>: it is not repeated.</li>
<li><b>Preview and summary together.</b> Tick <i>Evening preview</i>. Sleep
until 20:30: one notification, the "Today" summary with "Tomorrow: 1 due ·
First: Take medication at 06:30" as its last line.</li>
<li><b>Preview set inside quiet hours.</b> Tick <i>Evening preview</i> and set
its time to 23:00. Sleep until 21:58: only the summary. Press <i>+1 min</i>:
the preview appears at 21:59, the minute before quiet hours start. With
<i>Start over</i> and the same settings, sleep until 22:30 instead: the
preview is held, and sleeping on until 07:00 does not bring it back.</li>
<li><b>Preview and a focus session.</b> Tick <i>Evening preview</i> and
<i>Focus session running</i>. Sleep until 20:00: the log shows the summary and
the preview held. Untick the session, press <i>+1 min</i>: one notification
with both.</li>
</ol>"""


class HoldSimulation(QGroupBox):
    """The real notifier and policy, driven by a clock stepped by hand.

    Time passes in whole minutes with one evaluation per minute, as in
    the running application. "Sleep until" moves the clock in one jump
    and evaluates once on arrival, as after the machine wakes.
    """

    def __init__(
        self, time_format: str, show: Callable[[str, str], None], parent: QWidget | None = None
    ) -> None:
        super().__init__("When notifications are given — simulated clock", parent)
        self._show = show
        self._scratch = tempfile.TemporaryDirectory(prefix="pytodo-notifications-")
        self._storage = DatabaseStorage(Path(self._scratch.name) / "scratch.db")
        self._storage.open()
        self._now = _SIMULATION_START
        self._tasks = self._sample_tasks()
        self._shown: list[tuple[str, str]] = []
        self._last_held = ""

        self._clock_label = QLabel()
        self._clock_label.setTextFormat(Qt.TextFormat.RichText)
        self._focus_box = QCheckBox("Focus session running")
        self._silence_box = QCheckBox("Silence timed reminders in quiet hours (off in the app)")
        self._preview_box = QCheckBox("Evening preview (off in the app) at")
        self._preview_time = QTimeEdit(QTime(20, 0))
        self._preview_time.setDisplayFormat("HH:mm")
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(180)
        self._wake_time = QTimeEdit(QTime(23, 30))
        self._wake_time.setDisplayFormat("HH:mm")

        self._notifier = TaskNotifier(
            storage=self._storage,
            lists=lambda: [self._tasks],
            settings=self._settings,
            time_blocks=TimeBlockConfig,
            time_format=lambda: time_format,
            deliver=self._on_delivered,
            focus_active=self._focus_box.isChecked,
            clock=lambda: self._now,
            parent=self,
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self._clock_label)
        layout.addWidget(self._focus_box)
        layout.addWidget(self._silence_box)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self._preview_box)
        preview_row.addWidget(self._preview_time)
        preview_row.addStretch(1)
        layout.addLayout(preview_row)

        passing = QHBoxLayout()
        passing.addWidget(QLabel("Let time pass:"))
        for label, minutes in (("+1 min", 1), ("+10 min", 10), ("+1 hour", 60)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, m=minutes: self._pass_minutes(m))
            passing.addWidget(button)
        passing.addStretch(1)
        layout.addLayout(passing)

        sleeping = QHBoxLayout()
        sleeping.addWidget(QLabel("Sleep until:"))
        sleeping.addWidget(self._wake_time)
        wake = QPushButton("Wake")
        wake.clicked.connect(self._sleep_until_wake_time)
        sleeping.addWidget(wake)
        sleeping.addStretch(1)
        start_over = QPushButton("Start over")
        start_over.clicked.connect(self._start_over)
        sleeping.addWidget(start_over)
        layout.addLayout(sleeping)

        tasks = QLabel(
            "<b>Sample tasks</b> — yesterday: Renew passport. Today: Pay rent (no time), "
            "Submit expense report 09:30, Team standup 10:00–10:15, Check in for flight "
            "23:15. Tomorrow: Take medication 06:30. In 2 days: Book dentist "
            "(remind every day, from 3 days ahead). In 3 days: File tax return "
            "(remind once, 2 days ahead).<br>"
            "<b>Settings</b> — summary 09:00, reminders 15 min ahead, quiet hours "
            "22:00–07:00, evening preview off unless ticked above."
        )
        tasks.setWordWrap(True)
        tasks.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(tasks)
        layout.addWidget(self._log, 1)
        # A scrolling pane, not a label: a long word-wrapped label does
        # not report the height it needs and gets clipped.
        steps = QTextEdit()
        steps.setReadOnly(True)
        steps.setHtml(_SIMULATION_STEPS)
        steps.setMinimumHeight(200)
        layout.addWidget(steps, 1)
        self._start_over()

    @staticmethod
    def _sample_tasks() -> TodoList:
        def task(title: str, day_offset: int, **fields) -> TodoItem:
            return TodoItem(
                reminder=title,
                due_date=TODAY + timedelta(days=day_offset),
                created_at=0,
                updated_at=0,
                **fields,
            )

        items = [
            task("Renew passport", -1),
            task("Pay rent", 0),
            task("Submit expense report", 0, due_time=time(9, 30)),
            task("Team standup", 0, due_time=time(10), due_time_end=time(10, 15)),
            task("Check in for flight", 0, due_time=time(23, 15)),
            task("Take medication", 1, due_time=time(6, 30)),
            # Advance reminders: one mention, and one every day.
            task("File tax return", 3, remind_before_days=2, reminder_cadence="once"),
            task("Book dentist", 2, remind_before_days=3, reminder_cadence="daily_until_due"),
        ]
        return TodoList(name="Sample", items={item.id: item for item in items})

    def _settings(self) -> PolicySettings:
        preview_time = self._preview_time.time()
        return PolicySettings(
            quiet_allow_timed=not self._silence_box.isChecked(),
            preview_enabled=self._preview_box.isChecked(),
            preview_time=time(preview_time.hour(), preview_time.minute()),
        )

    def _on_delivered(self, title: str, body: str) -> None:
        self._shown.append((title, body))
        self._show(title, body)

    def _start_over(self) -> None:
        self._storage.clear()
        self._now = _SIMULATION_START
        self._last_held = ""
        self._focus_box.setChecked(False)
        self._silence_box.setChecked(False)
        self._preview_box.setChecked(False)
        self._preview_time.setTime(QTime(20, 0))
        self._log.clear()
        self._update_clock_label()

    def _pass_minutes(self, minutes: int) -> None:
        for _ in range(minutes):
            self._now += timedelta(minutes=1)
            self._evaluate()

    def _sleep_until_wake_time(self) -> None:
        wake = self._wake_time.time()
        target = datetime.combine(self._now.date(), time(wake.hour(), wake.minute()))
        if target <= self._now:
            target += timedelta(days=1)
        self._write(f"asleep until {target:%H:%M}")
        self._now = target
        self._evaluate()

    def _evaluate(self) -> None:
        self._shown = []
        result = self._notifier.evaluate()
        for title, body in self._shown:
            self._write("shown: " + title + " — " + body.replace("\n", " / "))
        held = self._describe_held(result)
        if held != self._last_held:
            if held:
                self._write("held: " + held)
            elif not self._shown:
                self._write("no longer held, and nothing shown: the day it belonged to is over")
            self._last_held = held
        self._update_clock_label()

    def _describe_held(self, result: Evaluation) -> str:
        parts = ["daily summary"] if result.held_summary else []
        if result.held_preview:
            parts.append("evening preview")
        parts.extend(item.title for item in result.held_items)
        if not parts:
            return ""
        quiet = in_quiet_hours(self._now.time(), self._settings())
        return ", ".join(parts) + (" (quiet hours)" if quiet else " (focus session)")

    def _write(self, line: str) -> None:
        self._log.appendPlainText(f"{self._now:%a %H:%M}  {line}")

    def _update_clock_label(self) -> None:
        quiet = in_quiet_hours(self._now.time(), self._settings())
        self._clock_label.setText(
            f"Simulated time: <b>{self._now:%A %H:%M}</b> — "
            f"quiet hours: <b>{'yes' if quiet else 'no'}</b>"
        )

    def shut_down(self) -> None:
        self._storage.close()
        self._scratch.cleanup()


def _coming(title: str, days: int) -> ComingUp:
    return ComingUp(uuid4(), title, TODAY + timedelta(days=days), days)


class Harness(QMainWindow):
    def __init__(self, time_format: str) -> None:
        super().__init__()
        self.setWindowTitle("Task notification verification")
        self._overlay = NotificationManager()
        self._os_notifier = self._make_os_notifier()
        # The notifier only formats here; nothing is evaluated or recorded.
        self._notifier = TaskNotifier(
            storage=DatabaseStorage(Path("unused.db")),
            lists=list,
            settings=PolicySettings,
            time_blocks=TimeBlockConfig,
            time_format=lambda: time_format,
            deliver=self._show,
            parent=self,
        )

        central = QWidget()
        columns = QHBoxLayout(central)
        shapes = QGroupBox("What each notification looks like")
        layout = QVBoxLayout(shapes)
        channel = "desktop notifications" if self._os_notifier else "in-app overlay"
        intro = QLabel(
            f"Delivering through: <b>{channel}</b>. Each button shows one "
            "notification. Check the title, the wording, the times, and that "
            "nothing is clipped."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setMinimumHeight(intro.fontMetrics().lineSpacing() * 3)
        layout.addWidget(intro)
        for label, fire in self._scenarios():
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, f=fire: f())
            layout.addWidget(button)
        layout.addStretch(1)
        self._simulation = HoldSimulation(time_format, self._show, self)
        columns.addWidget(shapes, 1)
        columns.addWidget(self._simulation, 1)
        self.setCentralWidget(central)

    def closeEvent(self, a0) -> None:  # noqa: N802 — Qt override
        self._simulation.shut_down()
        super().closeEvent(a0)

    def _scenarios(self) -> list[tuple[str, Callable[[], None]]]:
        n = self._notifier
        reminders = n.format_reminders
        tomorrow_first = _timed("Dentist", datetime.combine(TODAY + timedelta(days=1), time(9, 0)))
        soon = _at(15)
        return [
            (
                "Lead reminder — deadline",
                lambda: self._show(*reminders((_lead("Submit expense report", soon),))),
            ),
            (
                "Lead reminder — event",
                lambda: self._show(*reminders((_lead("Team standup", soon, is_event=True),))),
            ),
            (
                "Lead reminder — event with a meeting link in its text",
                lambda: self._show(
                    *reminders(
                        (
                            _lead(
                                "Design sync https://meet.google.com/abc-defg-hij",
                                soon,
                                is_event=True,
                            ),
                        )
                    )
                ),
            ),
            (
                "Lead reminder — time block (evening)",
                lambda: self._show(
                    *reminders((_lead("Call the landlord", _at(17), block="evening"),))
                ),
            ),
            (
                "Lead reminder — title too long for the banner",
                lambda: self._show(
                    *reminders(
                        (
                            _lead(
                                "Send the signed lease renewal and the deposit receipt "
                                "to the property manager",
                                soon,
                            ),
                        )
                    )
                ),
            ),
            (
                "Lead reminder — time block (late afternoon)",
                lambda: self._show(
                    *reminders((_lead("Water the plants", _at(14, 30), block="late_afternoon"),))
                ),
            ),
            (
                "Lead reminder — time block (night, crosses midnight)",
                lambda: self._show(*reminders((_lead("Run backup", _at(21), block="night"),))),
            ),
            (
                "Lead reminder — late start (6 minutes left)",
                lambda: self._show(*reminders((_lead("Submit expense report", soon, 6),))),
            ),
            (
                "Due now — deadline",
                lambda: self._show(*reminders((_due_now("Submit expense report", soon),))),
            ),
            (
                "Several reminders in one notification",
                lambda: self._show(
                    *reminders(
                        (
                            _due_now("Submit expense report", soon),
                            _lead("Team standup", soon + timedelta(minutes=15), is_event=True),
                            _lead("Send invoice", soon + timedelta(minutes=15)),
                            _lead("Gym", _at(17), block="evening"),
                        )
                    )
                ),
            ),
            (
                "Several reminders — more than fit (8)",
                lambda: self._show(
                    *reminders(tuple(_lead(f"Task number {i}", soon) for i in range(1, 9)))
                ),
            ),
            (
                "Daily summary — counts and next item",
                lambda: self._show(
                    *n.format_summary(
                        Summary(TODAY, 4, 2, _timed("Team standup", _at(10), is_event=True), ())
                    )
                ),
            ),
            (
                "Daily summary — only overdue",
                lambda: self._show(*n.format_summary(Summary(TODAY, 0, 3, None, ()))),
            ),
            (
                "Daily summary — with advance reminders",
                lambda: self._show(
                    *n.format_summary(
                        Summary(
                            TODAY,
                            4,
                            1,
                            _timed("Submit expense report", _at(9, 30)),
                            (),
                            (_coming("Passport renewal", 1), _coming("Tax return", 3)),
                        )
                    )
                ),
            ),
            (
                "Daily summary — only advance reminders, more than fit (5)",
                lambda: self._show(
                    *n.format_summary(
                        Summary(
                            TODAY,
                            0,
                            0,
                            None,
                            (),
                            tuple(_coming(f"Task number {i}", i) for i in range(1, 6)),
                        )
                    )
                ),
            ),
            (
                "Daily summary — late launch, with missed items",
                lambda: self._show(
                    *n.format_summary(
                        Summary(
                            TODAY,
                            5,
                            1,
                            _timed("Send invoice", _at(16)),
                            (
                                _timed("Early call", _at(8), is_event=True),
                                _timed("Submit expense report", _at(10)),
                            ),
                        )
                    )
                ),
            ),
            (
                "Missed items on their own",
                lambda: self._show(
                    *n.format_missed(
                        (
                            _timed("Early call", _at(8), is_event=True),
                            _timed("Submit expense report", _at(10)),
                        )
                    )
                ),
            ),
            (
                "Evening preview",
                lambda: self._show(*n.format_preview(Preview(TODAY, 3, tomorrow_first))),
            ),
            (
                "Evening preview — nothing with a time",
                lambda: self._show(*n.format_preview(Preview(TODAY, 2, None))),
            ),
            (
                "Summary with the preview as its last line",
                lambda: self._show(
                    *n.format_summary(
                        Summary(TODAY, 2, 1, None, ()), Preview(TODAY, 3, tomorrow_first)
                    )
                ),
            ),
            (
                "Missed items with the preview as the last line",
                lambda: self._show(
                    *n.format_missed(
                        (_timed("Submit expense report", _at(10)),),
                        Preview(TODAY, 3, tomorrow_first),
                    )
                ),
            ),
        ]

    def _make_os_notifier(self):
        """Match the application: native notifications except on macOS,
        where an ad-hoc-signed bundle gets a placeholder banner."""
        if sys.platform == "darwin":
            return None
        try:
            from desktop_notifier import DesktopNotifierSync

            return DesktopNotifierSync(app_name="PyTodo-Qt")
        except Exception as exc:  # noqa: BLE001 — fall back to the overlay
            print(f"desktop-notifier unavailable ({exc}); using the in-app overlay")
            return None

    def _show(self, title: str, body: str) -> None:
        print(f"--- {title}\n{body}\n")
        if self._os_notifier is not None:
            try:
                self._os_notifier.send(title=title, message=body, timeout=_TIMEOUT_SECONDS)
                return
            except Exception as exc:  # noqa: BLE001 — fall back to the overlay
                print(f"desktop notification failed ({exc}); using the in-app overlay")
        self._overlay.show(title, body, timeout_ms=_TIMEOUT_SECONDS * 1000)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--time-format", choices=("system", "12h", "24h"), default="system")
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])
    harness = Harness(args.time_format)
    screen = app.primaryScreen()
    available_height = screen.availableGeometry().height() if screen is not None else 800
    harness.resize(1000, min(820, available_height - 80))
    harness.show()
    if screen is not None:
        area = screen.availableGeometry()
        harness.move(area.left() + 40, area.bottom() - harness.frameGeometry().height() - 40)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
