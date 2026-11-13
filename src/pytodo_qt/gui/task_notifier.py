"""Deliver the task notifications the policy says are due.

``TaskNotifier`` is the bridge between the pure policy in
``core.notification_policy`` and the application: it reads what has
already fired from storage, evaluates the policy at the current time,
records what the evaluation consumed, turns the structured result into
translated text and hands each notification to a delivery callable.

Everything it depends on is passed in — where the lists, settings and
clock come from, and how a notification is delivered — so it can be
driven in tests with a fixed clock and no window.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QObject

from ..core.config import TimeBlockConfig
from ..core.database import DatabaseStorage
from ..core.logger import Logger
from ..core.meeting_link import detect_meeting_link
from ..core.models import TodoList, _format_time
from ..core.notification_policy import (
    ComingUp,
    Evaluation,
    Kind,
    PolicySettings,
    Preview,
    Reminder,
    Summary,
    TimedItem,
    evaluate,
)

logger = Logger(__name__)

# Lines shown in a notification that lists several items; the rest are
# counted in a trailing "+N more".
_MAX_LINES = 5
# Missed items named inline in the daily summary.
_MAX_SUMMARY_MISSED = 3
# Advance reminders named inline in the daily summary.
_MAX_SUMMARY_COMING_UP = 3
# Log entries older than this are deleted. Nothing looks further back
# than the current day, so the margin only bounds the table's size.
_LOG_RETENTION = timedelta(days=30)


class TaskNotifier(QObject):
    """Evaluates the notification policy and delivers what is due."""

    def __init__(
        self,
        *,
        storage: DatabaseStorage,
        lists: Callable[[], Iterable[TodoList]],
        settings: Callable[[], PolicySettings],
        time_blocks: Callable[[], TimeBlockConfig],
        time_format: Callable[[], str],
        deliver: Callable[[str, str], None],
        focus_active: Callable[[], bool] = lambda: False,
        clock: Callable[[], datetime] = datetime.now,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._storage = storage
        self._lists = lists
        self._settings = settings
        self._time_blocks = time_blocks
        self._time_format = time_format
        self._deliver = deliver
        self._focus_active = focus_active
        self._clock = clock
        self._last_pruned: date | None = None

    def evaluate(self) -> Evaluation:
        """Deliver every notification due now and record it as fired.

        What the evaluation consumed is recorded before anything is
        delivered, so a failure while delivering cannot cause the same
        notification to be produced again on the next evaluation.

        A notification held back by quiet hours or a running focus
        session is neither recorded nor delivered; a later evaluation
        produces it once the wait is over.
        """
        now = self._clock()
        result = evaluate(
            self._lists(),
            self._settings(),
            now,
            self._storage.get_fired_notifications(),
            self._time_blocks(),
            focus_active=self._focus_active(),
        )
        if result.fired:
            self._storage.record_notifications(result.fired)
        self._prune(now)

        if result.reminders:
            self._deliver(*self.format_reminders(result.reminders))
        # The summary, the report of missed items and the evening
        # preview share one notification: a preview due together with
        # either of the others is a line in it.
        if result.summary is not None:
            self._deliver(*self.format_summary(result.summary, result.preview))
        elif result.missed:
            self._deliver(*self.format_missed(result.missed, result.preview))
        elif result.preview is not None:
            self._deliver(*self.format_preview(result.preview))
        return result

    def _prune(self, now: datetime) -> None:
        """Delete old log entries, at most once per day."""
        today = now.date()
        if self._last_pruned == today:
            return
        self._last_pruned = today
        removed = self._storage.prune_notification_log((today - _LOG_RETENTION).isoformat())
        if removed:
            logger.log.debug("Pruned %d notification log entries", removed)

    # ------------------------------------------------------------------
    # Text
    # ------------------------------------------------------------------

    def format_reminders(self, reminders: tuple[Reminder, ...]) -> tuple[str, str]:
        """Return (title, body) for the lead reminders and due-now alerts
        of one evaluation. A single reminder is titled with its item; several
        are listed one per line."""
        if len(reminders) == 1:
            reminder = reminders[0]
            when = self._time(reminder.at)
            if reminder.kind is Kind.DUE_NOW:
                body = self.tr("Due now · {time}").format(time=when)
            elif reminder.block is not None:
                body = self._block_window(reminder)
            elif reminder.is_event:
                body = self.tr("Starts at {time} · in {minutes} min").format(
                    time=when, minutes=reminder.minutes_until
                )
            else:
                body = self.tr("Due at {time} · in {minutes} min").format(
                    time=when, minutes=reminder.minutes_until
                )
            return self._title(reminder.title), body

        lines = [
            self.tr("{time}  {title} — {what}").format(
                time=self._time(r.at), title=self._title(r.title), what=self._what(r)
            )
            for r in reminders
        ]
        return self.tr("%n reminders", "", len(reminders)), self._capped(lines)

    def format_summary(self, summary: Summary, preview: Preview | None = None) -> tuple[str, str]:
        """Return (title, body) for the daily summary, with the evening
        preview as its last line when both are due together."""
        counts: list[str] = []
        if summary.due_today:
            counts.append(self.tr("%n due today", "", summary.due_today))
        if summary.overdue:
            counts.append(self.tr("%n overdue", "", summary.overdue))

        lines: list[str] = []
        if counts:
            lines.append(" · ".join(counts))
        if summary.next_up is not None:
            lines.append(
                self.tr("Next: {title} at {time}").format(
                    title=self._title(summary.next_up.title), time=self._time(summary.next_up.at)
                )
            )
        if summary.missed:
            shown = [
                self.tr("{title} ({time})").format(
                    title=self._title(item.title), time=self._time(item.at)
                )
                for item in summary.missed[:_MAX_SUMMARY_MISSED]
            ]
            hidden = len(summary.missed) - len(shown)
            if hidden > 0:
                shown.append(self.tr("+{count} more").format(count=hidden))
            lines.append(self.tr("Earlier today: {items}").format(items=", ".join(shown)))
        if summary.coming_up:
            shown = [self._coming_up(item) for item in summary.coming_up[:_MAX_SUMMARY_COMING_UP]]
            hidden = len(summary.coming_up) - len(shown)
            if hidden > 0:
                shown.append(self.tr("+{count} more").format(count=hidden))
            lines.append(self.tr("Coming up: {items}").format(items=", ".join(shown)))
        if preview is not None:
            lines.append(self._preview_line(preview))
        return self.tr("Today"), "\n".join(lines)

    def format_preview(self, preview: Preview) -> tuple[str, str]:
        """Return (title, body) for the evening preview on its own."""
        if preview.first is None:
            return self.tr("Tomorrow"), self.tr("%n due tomorrow", "", preview.due_tomorrow)
        return self.tr("Tomorrow"), self._preview_counts(preview)

    def _preview_line(self, preview: Preview) -> str:
        """The evening preview as a line of another notification."""
        return self.tr("Tomorrow: {preview}").format(preview=self._preview_counts(preview))

    def _preview_counts(self, preview: Preview) -> str:
        count = self.tr("%n due", "", preview.due_tomorrow)
        if preview.first is None:
            return count
        first = self.tr("First: {title} at {time}").format(
            title=self._title(preview.first.title), time=self._time(preview.first.at)
        )
        return f"{count} · {first}"

    def _coming_up(self, item: ComingUp) -> str:
        """An advance reminder as it reads within the summary's line."""
        title = self._title(item.title)
        if item.days_until == 1:
            return self.tr("{title} tomorrow").format(title=title)
        return self.tr("{title} in {days} days").format(title=title, days=item.days_until)

    def format_missed(
        self, missed: tuple[TimedItem, ...], preview: Preview | None = None
    ) -> tuple[str, str]:
        """Return (title, body) for reminders whose moment passed while
        nothing was evaluating, with the evening preview as the last
        line when both are due together."""
        lines = [
            self.tr("{time}  {title}").format(
                time=self._time(item.at), title=self._title(item.title)
            )
            for item in missed
        ]
        body = self._capped(lines)
        if preview is not None:
            body = f"{body}\n{self._preview_line(preview)}"
        return self.tr("Earlier today"), body

    def _what(self, reminder: Reminder) -> str:
        if reminder.kind is Kind.DUE_NOW:
            return self.tr("due now")
        if reminder.block is not None:
            return self._block_phrase(reminder.block, inline=True)
        if reminder.is_event:
            return self.tr("starts in {minutes} min").format(minutes=reminder.minutes_until)
        return self.tr("due in {minutes} min").format(minutes=reminder.minutes_until)

    def _block_window(self, reminder: Reminder) -> str:
        """Describe a block reminder by its window: "This evening ·
        17:00–21:00". A block is a stretch of the day, not a moment to
        count down to."""
        assert reminder.block is not None
        phrase = self._block_phrase(reminder.block, inline=False)
        block_range = self._time_blocks().block_range(reminder.block)
        if block_range is None:
            return phrase
        end = reminder.at + timedelta(minutes=block_range[1] - block_range[0])
        return self.tr("{block} · {start}–{end}").format(
            block=phrase, start=self._time(reminder.at), end=self._time(end)
        )

    def _block_phrase(self, block: str, *, inline: bool) -> str:
        """How a block is referred to on the day it falls: "This
        evening" on its own line, "this evening" within a line."""
        standalone = {
            "early_morning": self.tr("Early this morning"),
            "morning": self.tr("This morning"),
            "late_morning": self.tr("Late this morning"),
            "noon": self.tr("Around noon"),
            "early_afternoon": self.tr("Early this afternoon"),
            "afternoon": self.tr("This afternoon"),
            "late_afternoon": self.tr("Late this afternoon"),
            "early_evening": self.tr("Early this evening"),
            "evening": self.tr("This evening"),
            "late_evening": self.tr("Late this evening"),
            "night": self.tr("Tonight"),
            "late_night": self.tr("Late tonight"),
            "midnight": self.tr("Around midnight"),
        }
        within_line = {
            "early_morning": self.tr("early this morning"),
            "morning": self.tr("this morning"),
            "late_morning": self.tr("late this morning"),
            "noon": self.tr("around noon"),
            "early_afternoon": self.tr("early this afternoon"),
            "afternoon": self.tr("this afternoon"),
            "late_afternoon": self.tr("late this afternoon"),
            "early_evening": self.tr("early this evening"),
            "evening": self.tr("this evening"),
            "late_evening": self.tr("late this evening"),
            "night": self.tr("tonight"),
            "late_night": self.tr("late tonight"),
            "midnight": self.tr("around midnight"),
        }
        phrases = within_line if inline else standalone
        return phrases.get(block, _block_label(block))

    def _capped(self, lines: list[str]) -> str:
        if len(lines) > _MAX_LINES:
            hidden = len(lines) - _MAX_LINES
            lines = [*lines[:_MAX_LINES], self.tr("+{count} more").format(count=hidden)]
        return "\n".join(lines)

    def _time(self, moment: datetime) -> str:
        return _format_time(moment.time(), self._time_format())

    def _title(self, title: str) -> str:
        """An item's text as shown in a notification: a meeting URL is
        dropped, since it is long and cannot be followed from a banner."""
        link = detect_meeting_link(title)
        if link is None:
            return title
        stripped = " ".join(title.replace(link.url, " ").split())
        return stripped or self.tr("{provider} meeting").format(provider=link.provider)


def _block_label(block: str) -> str:
    return block.replace("_", " ").title()
