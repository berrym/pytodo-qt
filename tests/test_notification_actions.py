"""The buttons on a notification about one task (#60).

Done, Snooze and Join, a click on the text (Open) and the closing of the
notification all come to MainWindow._on_notification_action, whatever
platform the notification was shown on. These tests drive that entry
point and the delivery of notifications with buttons on a stand-in for
the window, as the command tests do (tests/test_pomodoro.py).
"""

from __future__ import annotations

import asyncio
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtGui import QUndoStack

from pytodo_qt.core.config import NotificationConfig
from pytodo_qt.core.database import DatabaseStorage
from pytodo_qt.core.models import Database, create_todo_item, create_todo_list
from pytodo_qt.core.notification_policy import FiredKey
from pytodo_qt.gui import main_window as main_window_module
from pytodo_qt.gui.main_window import MainWindow
from pytodo_qt.gui.task_notifier import ReminderTarget

KEY_TIME = "2026-11-23T14:30"


class _ConfigManager:
    def save(self) -> None:
        pass


def _window(tmp_path: Path, *items) -> SimpleNamespace:
    """A stand-in for the main window with a real database, storage and
    undo stack, and the window's own methods bound to it."""
    db = Database()
    todo_list = create_todo_list("Home")
    for item in items:
        todo_list.add_item(item)
    db.add_list(todo_list)
    db.set_active_list(todo_list.id)
    storage = DatabaseStorage(tmp_path / "test.db")
    storage.open()
    window = SimpleNamespace(
        _database=db,
        _storage=storage,
        _undo_stack=QUndoStack(),
        _save_database=MagicMock(),
        _refresh_ui=MagicMock(),
        _config=SimpleNamespace(
            notifications=NotificationConfig(snooze_minutes=15),
            database=SimpleNamespace(active_list=""),
        ),
        _config_manager=_ConfigManager(),
        _shutting_down=False,
        status_bar_widget=MagicMock(),
        _open_item=MagicMock(),
        tr=lambda text: text,
        list=todo_list,
    )
    for name in ("_find_item_anywhere", "_completion_commands", "_on_notification_action"):
        setattr(window, name, getattr(MainWindow, name).__get__(window))
    return window


def _target(item, kind: str = "lead", join: bool = False) -> ReminderTarget:
    return ReminderTarget(item.id, FiredKey(str(item.id), kind, KEY_TIME), join)


def _said(window) -> list[str]:
    return [call.args[0] for call in window.status_bar_widget.show_message.call_args_list]


# --- Done ---


def test_done_ticks_the_task_as_the_task_list_does(tmp_path, qtbot):
    item = create_todo_item("Call the bank")
    window = _window(tmp_path, item)
    window._on_notification_action("done", _target(item))
    assert item.complete is True
    # One step on the undo stack, as a tick in the window is.
    assert window._undo_stack.count() == 1
    window._undo_stack.undo()
    assert item.complete is False
    window._storage.close()


def test_done_on_a_recurring_task_completes_this_cycle_as_the_task_list_does(tmp_path, qtbot):
    """The task stays done until its next due date, when the window's
    advance moves it on (ToggleCompleteRecurringCommand)."""
    item = create_todo_item("Water the plants")
    item.due_date = date(2026, 11, 23)
    item.recurrence_type = "daily"
    item.recurrence_interval = 1
    window = _window(tmp_path, item)
    window._on_notification_action("done", _target(item))
    assert item.complete is True
    assert item.recurrence_count == 1
    assert item.due_date == date(2026, 11, 23)
    assert window._undo_stack.count() == 1
    window._undo_stack.undo()
    assert item.complete is False
    assert item.recurrence_count == 0
    window._storage.close()


def test_done_on_a_task_already_done_changes_nothing(tmp_path, qtbot):
    item = create_todo_item("Call the bank")
    item.complete = True
    window = _window(tmp_path, item)
    window._on_notification_action("done", _target(item))
    assert item.complete is True
    assert window._undo_stack.count() == 0
    assert _said(window) == ["That task is already done"]
    window._storage.close()


def test_a_task_that_is_gone_is_left_alone_with_a_word(tmp_path, qtbot):
    item = create_todo_item("Call the bank")
    window = _window(tmp_path)
    for action in ("done", "snooze", "join", "open"):
        window._on_notification_action(action, _target(item))
    assert _said(window) == ["That task no longer exists"] * 4
    assert window._undo_stack.count() == 0
    assert window._storage.get_snoozed_reminders() == {}
    window._open_item.assert_not_called()
    window._storage.close()


def test_a_deleted_task_counts_as_gone(tmp_path, qtbot):
    item = create_todo_item("Call the bank")
    window = _window(tmp_path, item)
    item.deleted = True
    window._on_notification_action("done", _target(item))
    assert _said(window) == ["That task no longer exists"]
    window._storage.close()


def test_a_task_in_another_list_is_found(tmp_path, qtbot):
    window = _window(tmp_path)
    work = create_todo_list("Work")
    item = create_todo_item("File the claim")
    work.add_item(item)
    window._database.add_list(work)
    window._on_notification_action("done", _target(item))
    assert item.complete is True
    window._storage.close()


# --- Snooze ---


def test_snooze_puts_the_reminder_off_for_the_set_minutes(tmp_path, qtbot):
    item = create_todo_item("Call the bank")
    window = _window(tmp_path, item)
    before = time.time()
    window._on_notification_action("snooze", _target(item))
    ((key, until),) = window._storage.get_snoozed_reminders().items()
    assert key == (str(item.id), "lead", KEY_TIME)
    # An absolute moment: the press, and the setting's 15 minutes.
    assert before + 15 * 60 <= until <= time.time() + 15 * 60
    assert _said(window) == ["Reminder snoozed for 15 min"]
    # No change to the task, and no undo step.
    assert window._undo_stack.count() == 0
    assert item.complete is False
    window._storage.close()


def test_snooze_on_a_task_already_done_is_not_kept(tmp_path, qtbot):
    item = create_todo_item("Call the bank")
    item.complete = True
    window = _window(tmp_path, item)
    window._on_notification_action("snooze", _target(item))
    assert window._storage.get_snoozed_reminders() == {}
    assert _said(window) == ["That task is already done"]
    window._storage.close()


# --- Join, Open, closing ---


def test_join_opens_the_link_the_task_has_now(tmp_path, qtbot, monkeypatch):
    opened = []
    monkeypatch.setattr(
        main_window_module.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )
    item = create_todo_item("Stand-up https://meet.google.com/abc-defg-hij")
    window = _window(tmp_path, item)
    window._on_notification_action("join", _target(item, join=True))
    assert opened == ["https://meet.google.com/abc-defg-hij"]
    # The link was taken out of the task since: nothing is opened.
    item.reminder = "Stand-up"
    window._on_notification_action("join", _target(item, join=True))
    assert opened == ["https://meet.google.com/abc-defg-hij"]
    assert _said(window) == ["That task has no meeting link now"]
    window._storage.close()


def test_join_works_on_a_task_already_done(tmp_path, qtbot, monkeypatch):
    opened = []
    monkeypatch.setattr(
        main_window_module.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )
    item = create_todo_item("Stand-up https://meet.google.com/abc-defg-hij")
    item.complete = True
    window = _window(tmp_path, item)
    window._on_notification_action("join", _target(item, join=True))
    assert len(opened) == 1
    window._storage.close()


def test_a_click_on_the_text_opens_the_task(tmp_path, qtbot):
    item = create_todo_item("Call the bank")
    window = _window(tmp_path, item)
    window._on_notification_action("open", _target(item))
    window._open_item.assert_called_once_with(window.list, item)
    window._storage.close()


def test_closing_the_notification_does_nothing(tmp_path, qtbot):
    item = create_todo_item("Call the bank")
    window = _window(tmp_path, item)
    window._on_notification_action("dismiss", _target(item))
    assert window._undo_stack.count() == 0
    assert _said(window) == []
    window._open_item.assert_not_called()
    window._storage.close()


def test_closing_the_notification_of_a_task_that_is_gone_says_nothing(tmp_path, qtbot):
    item = create_todo_item("Call the bank")
    window = _window(tmp_path)
    window._on_notification_action("dismiss", _target(item))
    assert _said(window) == []
    window._storage.close()


def test_nothing_is_done_once_the_window_has_closed_for_good(tmp_path, qtbot):
    item = create_todo_item("Call the bank")
    window = _window(tmp_path, item)
    window._shutting_down = True
    for action in ("done", "snooze", "open"):
        window._on_notification_action(action, _target(item))
    assert item.complete is False
    assert window._storage.get_snoozed_reminders() == {}
    window._open_item.assert_not_called()
    window._storage.close()


# --- The buttons, and the notifications kept on screen ---


def _deliverer(notifier=None) -> SimpleNamespace:
    """A stand-in for the window as far as delivering goes."""
    window = SimpleNamespace(
        _notifier=notifier,
        _notification_manager=MagicMock(),
        _actionable=[],
        _ACTIONABLE_KEPT=MainWindow._ACTIONABLE_KEPT,
        actions=[],
        tr=lambda text: text,
    )
    window._on_notification_action = lambda action, target: window.actions.append(
        (action, target.item_id)
    )
    for name in (
        "_actions_for",
        "_notify_actionable",
        "_withdraw_actionable",
        "_forget_actionable",
    ):
        setattr(window, name, getattr(MainWindow, name).__get__(window))
    return window


def test_the_buttons_are_done_and_snooze_and_join_with_a_link():
    window = _deliverer()
    item = create_todo_item("Call the bank")
    assert window._actions_for(_target(item)) == [("done", "Done"), ("snooze", "Snooze")]
    assert window._actions_for(_target(item, join=True)) == [
        ("done", "Done"),
        ("snooze", "Snooze"),
        ("join", "Join"),
    ]


def test_on_macos_the_overlay_shows_the_buttons_and_keeps_the_banner(monkeypatch):
    monkeypatch.setattr(main_window_module.sys, "platform", "darwin")
    window = _deliverer()
    item = create_todo_item("Call the bank")
    asyncio.run(window._notify_actionable("Call the bank", "Due at 14:30", _target(item)))
    call = window._notification_manager.show.call_args
    assert call.args == ("Call the bank", "Due at 14:30")
    assert call.kwargs["timeout_ms"] == 0
    assert call.kwargs["actions"] == [("done", "Done"), ("snooze", "Snooze")]
    assert call.kwargs["tag"] == str(item.id)
    # The overlay's button and a click on its text come to the one place.
    call.kwargs["on_action"]("snooze")
    call.kwargs["on_click"]()
    assert window.actions == [("snooze", item.id), ("open", item.id)]


class _Notifier:
    """desktop-notifier as far as these tests use it."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.cleared: list[str] = []

    async def send(self, **kwargs) -> str:
        self.sent.append(kwargs)
        return f"id-{len(self.sent)}"

    async def clear(self, identifier: str) -> None:
        self.cleared.append(identifier)


def test_on_linux_and_windows_the_notification_has_buttons_and_does_not_expire(monkeypatch):
    monkeypatch.setattr(main_window_module.sys, "platform", "linux")
    notifier = _Notifier()
    window = _deliverer(notifier)
    item = create_todo_item("Stand-up https://meet.google.com/abc-defg-hij")
    asyncio.run(window._notify_actionable("Stand-up", "Starts at 14:30", _target(item, join=True)))
    (sent,) = notifier.sent
    assert [button.title for button in sent["buttons"]] == ["Done", "Snooze", "Join"]
    assert sent["timeout"] == 0
    sent["buttons"][0].on_pressed()
    sent["on_clicked"]()
    sent["on_dismissed"]()
    assert window.actions == [("done", item.id), ("open", item.id), ("dismiss", item.id)]
    # Acted on: no longer counted as on screen.
    assert window._actionable == []


def test_a_new_notification_about_the_same_task_takes_the_earlier_one_away(monkeypatch):
    monkeypatch.setattr(main_window_module.sys, "platform", "linux")
    notifier = _Notifier()
    window = _deliverer(notifier)
    item = create_todo_item("Call the bank")

    async def twice() -> None:
        await window._notify_actionable("Call the bank", "in 15 min", _target(item))
        await window._notify_actionable("Call the bank", "Due now", _target(item, "due_now"))

    asyncio.run(twice())
    assert notifier.cleared == ["id-1"]
    assert window._actionable == [(str(item.id), "id-2")]


def test_at_most_three_stay_on_screen_and_the_oldest_goes(monkeypatch):
    monkeypatch.setattr(main_window_module.sys, "platform", "linux")
    notifier = _Notifier()
    window = _deliverer(notifier)
    items = [create_todo_item(f"Task {n}") for n in range(4)]

    async def four() -> None:
        for item in items:
            await window._notify_actionable(item.reminder, "Due now", _target(item))

    asyncio.run(four())
    assert notifier.cleared == ["id-1"]
    assert [tag for tag, _ in window._actionable] == [str(item.id) for item in items[1:]]


def test_overlay_banners_are_taken_away_by_their_tag(monkeypatch):
    monkeypatch.setattr(main_window_module.sys, "platform", "darwin")
    window = _deliverer()
    items = [create_todo_item(f"Task {n}") for n in range(4)]

    async def four() -> None:
        for item in items:
            await window._notify_actionable(item.reminder, "Due now", _target(item))

    asyncio.run(four())
    window._notification_manager.dismiss_tagged.assert_called_once_with(str(items[0].id))


def test_a_failed_os_notification_falls_back_to_the_overlay(monkeypatch):
    monkeypatch.setattr(main_window_module.sys, "platform", "linux")

    class Broken(_Notifier):
        async def send(self, **kwargs) -> str:
            raise RuntimeError("no notification server")

    window = _deliverer(Broken())
    item = create_todo_item("Call the bank")
    asyncio.run(window._notify_actionable("Call the bank", "Due now", _target(item)))
    window._notification_manager.show.assert_called_once()
    assert window._actionable == [(str(item.id), None)]


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_a_notification_without_a_task_is_delivered_as_before(platform, monkeypatch):
    """The summary and several reminders in one: no buttons, gone by
    itself."""
    created = []
    window = SimpleNamespace(_notify=MagicMock(return_value=None))

    def fake_create_task(coroutine):
        created.append(coroutine)

    monkeypatch.setattr(main_window_module.asyncio, "create_task", fake_create_task)
    MainWindow._deliver_task_notification(window, "Today", "2 due today", None)
    window._notify.assert_called_once_with("Today", "2 due today", timeout=10)
