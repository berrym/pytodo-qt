"""The status line said after tasks are ticked or unticked (#126).

A tick moves a task: by default finished tasks sort to the bottom of the
list, on the board a task goes to the last column, and a filter can take
it out of view. The line names the task, says where it went and how to
take the tick back, for example::

    Done: "check snooze" — moved to the finished tasks · ⌘Z to undo

Where it went is one of the places below, chosen by the main window in
a fixed order (``MainWindow._completion_place``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from PyQt6.QtCore import QCoreApplication

_tr = QCoreApplication.translate
_CONTEXT = "CompletionReport"

# How long the line stays, unless another message takes its place.
MESSAGE_MS = 10_000

# A longer name is cut short, so the line fits the status bar; where
# the status bar has less room, down to ``SHORTEST_NAME``.
NAME_LIMIT = 40
SHORTEST_NAME = 12


@dataclass(frozen=True)
class CompletionBefore:
    """Where ticked tasks were before the tick: their rows in the list
    view (only those shown) and their columns on the board."""

    rows: dict[UUID, int]
    columns: dict[UUID, str]


@dataclass(frozen=True)
class Ticked:
    """A task the tick changed, as it is after the change."""

    name: str
    complete: bool


def short_name(name: str, limit: int = NAME_LIMIT) -> str:
    """The name as the line shows it: at most ``limit`` characters."""
    name = " ".join(name.split())
    if len(name) <= limit:
        return name
    return name[: limit - 1].rstrip() + "…"


def _tasks(group: Sequence[Ticked], limit: int) -> str:
    if len(group) == 1:
        return f'"{short_name(group[0].name, limit)}"'
    return _tr(_CONTEXT, "{count} tasks").format(count=len(group))


def in_list(name: str) -> str:
    """The place of tasks in a list other than the one shown."""
    return _tr(_CONTEXT, 'in "{name}"').format(name=short_name(name))


def hidden_by_active_filter() -> str:
    return _tr(_CONTEXT, "hidden by the Active filter")


def hidden_by_completed_filter() -> str:
    return _tr(_CONTEXT, "hidden by the Completed filter")


def in_column(name: str) -> str:
    """The place on the board of tasks that moved to another column."""
    return _tr(_CONTEXT, 'moved to "{name}"').format(name=name)


def to_finished_tasks() -> str:
    return _tr(_CONTEXT, "moved to the finished tasks")


def to_open_tasks() -> str:
    return _tr(_CONTEXT, "moved back to the open tasks")


def undo_hint(shortcut: str) -> str:
    """How to take the tick back, with the shortcut as the platform writes it."""
    return _tr(_CONTEXT, "{shortcut} to undo").format(shortcut=shortcut)


def completion_line(
    ticked: Sequence[Ticked], place: str = "", hint: str = "", name_limit: int = NAME_LIMIT
) -> str:
    """The line for tasks just ticked or unticked.

    ``place`` says where they went and ``hint`` how to take the change
    back; either may be empty. Tasks ticked and tasks unticked by the
    same change are named in two parts, a name in at most ``name_limit``
    characters.
    """
    done = [t for t in ticked if t.complete]
    not_done = [t for t in ticked if not t.complete]
    parts = []
    if done:
        parts.append(_tr(_CONTEXT, "Done: {tasks}").format(tasks=_tasks(done, name_limit)))
    if not_done:
        parts.append(_tr(_CONTEXT, "Not done: {tasks}").format(tasks=_tasks(not_done, name_limit)))
    line = " · ".join(parts)
    if place:
        line += f" — {place}"
    if hint:
        line += f" · {hint}"
    return line


def fitted_line(
    ticked: Sequence[Ticked], place: str, hint: str, fits: Callable[[str], bool]
) -> str:
    """The line with the names as long as the room allows.

    Names are cut shorter, down to ``SHORTEST_NAME`` characters, until
    ``fits`` accepts the line, so that where the tasks went and how to
    undo stay in view; a line that does not fit even then is ended by
    the status bar.
    """
    for limit in range(NAME_LIMIT, SHORTEST_NAME - 1, -1):
        line = completion_line(ticked, place, hint, limit)
        if fits(line):
            return line
    return completion_line(ticked, place, hint, SHORTEST_NAME)
