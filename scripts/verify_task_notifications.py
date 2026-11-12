"""Manual visual-verification harness for task notification text.

Shows every shape of task notification — lead reminders, due-now alerts,
several reminders merged into one, the daily summary, and missed items —
without waiting for real due times. Each button builds a sample result
of the notification policy, formats it with the same ``TaskNotifier``
the application uses, and delivers it through the platform's
notification channel: the in-app overlay on macOS, the desktop's native
notifications elsewhere.

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
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pytodo_qt.core.config import TimeBlockConfig  # noqa: E402
from pytodo_qt.core.database import DatabaseStorage  # noqa: E402
from pytodo_qt.core.notification_policy import (  # noqa: E402
    Kind,
    PolicySettings,
    Reminder,
    Summary,
    TimedItem,
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
        layout = QVBoxLayout(central)
        channel = "desktop notifications" if self._os_notifier else "in-app overlay"
        intro = QLabel(
            f"Delivering through: <b>{channel}</b>. Each button shows one "
            "notification. Check the title, the wording, the times, and that "
            "nothing is clipped."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)
        for label, fire in self._scenarios():
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, f=fire: f())
            layout.addWidget(button)
        self.setCentralWidget(central)

    def _scenarios(self) -> list[tuple[str, Callable[[], None]]]:
        n = self._notifier
        reminders = n.format_reminders
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
    harness.resize(420, 0)
    harness.show()
    screen = app.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        harness.move(area.left() + 40, area.bottom() - harness.frameGeometry().height() - 40)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
