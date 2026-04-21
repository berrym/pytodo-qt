# macOS Notifications — Migration to `desktop-notifier`

## Decision Date: 2026-04-21

## Context

On Linux the app's five `QSystemTrayIcon.showMessage(...)` call sites deliver
notifications through libnotify with full title + body text. On macOS (signed
DMG install, `com.berrym.pytodo-qt`, 0.3.11b1) the same calls surface as a
generic **"PyTodo-Qt Notification"** banner with no body.

Root cause: Qt 6's macOS backend for `QSystemTrayIcon::showMessage` routes
through `UNUserNotificationCenter` but never calls
`requestAuthorization(options:completionHandler:)`. Without an explicit
permission grant, macOS silently downgrades each notification to the anonymous
fallback banner (title and body dropped, only app name rendered). Tracked in
upstream Qt bugs QTBUG-111454 and QTBUG-96138; not fixable from Python.

Previous work on macOS notifications (see memory `project-macos-notifications.md`)
was scoped to the *icon*, not the *text*, and ended in abandonment of all
in-process bundle-synthesis approaches. That abandonment does not apply here:
the DMG install already provides a real signed `.app` bundle with a correct
`CFBundleIdentifier`, so `UNUserNotificationCenter` can be reached cleanly
from process code — the only missing piece is an explicit permission request
and a delivery path that actually uses it.

## Decision

Replace all `QSystemTrayIcon.showMessage(...)` calls with
[`desktop-notifier`](https://github.com/samschott/desktop-notifier) behind a
single internal helper. Keep `QSystemTrayIcon` itself for the menu-bar icon,
menu, and activation click — it is not being removed.

### Why `desktop-notifier`

- Uses `UNUserNotificationCenter` **with an explicit `requestAuthorization`
  call** on macOS — the exact missing piece behind the current bug.
- Cross-platform: libnotify/notify2 on Linux, WinRT on Windows. Solves the
  Windows notification story for free before we ship the Inno Setup build.
- Async-first API (`await notifier.send(...)`) that composes naturally with
  our existing `qasync` event loop.
- MIT license — compatible with our GPLv3 codebase.
- Maintainer pedigree: samschott (author of Maestral), a project with some of
  the best macOS-native Python desktop integration in the ecosystem.

### Risks acknowledged up front

1. **Source runs degrade.** Outside a `.app` bundle (i.e. `uv run`), macOS
   cannot reach `UNUserNotificationCenter`; `desktop-notifier` falls back to a
   stub/log backend. This is no worse than today. We explicitly accept the
   trade: correct behavior in the shipping DMG, best-effort from source.
2. **New transitive dep.** On macOS, `desktop-notifier` pulls in
   `rubicon-objc` (small, mature, BSD-3). PyInstaller needs `rubicon.objc`
   added to `hiddenimports` or the `.app` will silently break at runtime.
3. **Permission prompt UX.** macOS will show a one-time system prompt on
   first run after the migration ships. Users who dismiss it will never see
   notifications until they flip the switch manually in System Settings.
   Accepted — this is the standard macOS trust model and better than the
   current silent failure.

## Design

### The helper

Single method on `MainWindow`:

```python
async def _notify(self, title: str, body: str, *, timeout: float = 5.0) -> None:
    """Send a system notification.

    Fire-and-forget from sync Qt slots via asyncio.create_task(...).
    Silently degrades on platforms/backends that cannot deliver.
    """
    if self._notifier is None:
        return
    try:
        await self._notifier.send(title=title, message=body, timeout=timeout)
    except Exception as exc:  # library raises a variety of backend-specific errors
        logger.log.debug("Notification send failed: %s", exc)
```

Sync callers wrap the call:

```python
asyncio.create_task(self._notify(title, body))
```

No return value is needed anywhere; all five current sites ignore the
`showMessage` return.

### Notifier construction

In `_setup_tray_icon()` (or a new `_setup_notifier()` called adjacent to it):

```python
from desktop_notifier import DesktopNotifier

self._notifier: DesktopNotifier | None = None
try:
    self._notifier = DesktopNotifier(
        app_name="PyTodo-Qt",
        app_icon=None,  # macOS uses bundle icon; Linux uses app_name lookup
    )
except Exception as exc:
    logger.log.warning("Failed to initialize DesktopNotifier: %s", exc)
```

### Permission request

Call once at app startup, after the qasync loop is live but before the first
notification might fire. Placement: in `MainWindow.__init__` tail, or in a
`showEvent` one-shot, scheduled via `asyncio.create_task`:

```python
async def _request_notification_permission(self) -> None:
    if self._notifier is None:
        return
    try:
        granted = await self._notifier.request_authorisation()
        if not granted:
            logger.log.info("User declined notification permission")
    except Exception as exc:
        logger.log.debug("Notification authorization request failed: %s", exc)
```

This is idempotent on macOS: after first grant/deny, the OS caches the
decision and the call returns immediately without re-prompting.

### What `QSystemTrayIcon` keeps doing

Unchanged:
- Menu-bar icon rendering (template mask on macOS, theme-aware on Linux)
- Tray menu (Show / Hide / Quit)
- Activation click → show/hide window
- Right-click context menu

Removed:
- `self._notification_icon` attribute (line 1206) — only used by the five
  `showMessage` calls; `desktop-notifier` uses the bundle icon on macOS and
  the app-name icon lookup on Linux.

## Migration Plan — Three Commits

### Commit 1 — add dep, build helper, wire permission request

**Files touched:**
- `pyproject.toml` — add `"desktop-notifier>=6.0"` to `dependencies`.
- `uv.lock` — regenerated.
- `src/pytodo_qt/gui/main_window.py`:
  - Add import: `from desktop_notifier import DesktopNotifier`
  - Add import: `import asyncio`
  - In `_setup_tray_icon` (or nearby), initialize `self._notifier`.
  - Add `_notify(self, title, body, *, timeout=5.0)` coroutine method.
  - Add `_request_notification_permission(self)` coroutine method.
  - Schedule the permission request in `__init__` tail via
    `asyncio.create_task(...)` guarded by `if self._notifier is not None`.

**Does not touch:** the five existing `self.tray_icon.showMessage(...)` call
sites. They stay exactly as they are. This commit is a pure addition and is
safe to ship on its own (no behavior change for end users yet).

**Verification:**
- `uv run basedpyright src/` → 0 errors (no new type noise).
- Full test suite passes: `QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/ -v`.
- Manual sanity: launch via `uv run`, confirm permission request logs
  INFO-level message (on macOS from source it will fail to grant — expected).

### Commit 2 — migrate the 5 call sites

Mechanical rewrite. Each site drops the icon arg and the timeout arg (helper
uses a consistent default) and wraps in `asyncio.create_task`.

**Site 1 — `main_window.py:1981` — overdue / due-today reminder digest:**

```python
# before
self.tray_icon.showMessage(
    self.tr("PyTodo-Qt Reminders"),
    "\n".join(lines),
    self._notification_icon,
    10000,
)
# after
asyncio.create_task(self._notify(
    self.tr("PyTodo-Qt Reminders"),
    "\n".join(lines),
    timeout=10.0,
))
```

**Site 2 — `main_window.py:2997` — pomodoro focus session complete:**

```python
asyncio.create_task(self._notify(
    self.tr("Focus Session Complete"),
    self.tr("Time for a break!"),
))
```

**Site 3 — `main_window.py:3006` — pomodoro break over:**

```python
asyncio.create_task(self._notify(
    self.tr("Break Over"),
    self.tr("Ready for the next session?"),
))
```

**Site 4 — `main_window.py:3186` — stopwatch idle auto-pause:**

```python
asyncio.create_task(self._notify(
    self.tr("Stopwatch Paused"),
    self.tr(f"No activity detected for {timeout_mins} minutes"),
))
```

**Site 5 — `main_window.py:3332` — milestone (inside `_notify_milestone`):**

Rename `_notify_milestone` is tempting but unnecessary — keep it as the
semantic wrapper (it also updates the status bar). Internally, swap:

```python
# before
if self.tray_icon is not None:
    self.tray_icon.showMessage(title, message, self._notification_icon, 5000)
# after
asyncio.create_task(self._notify(title, message))
```

Remove the `if self.tray_icon is not None:` guard at each site; the helper
handles the `self._notifier is None` case internally.

**Also removed this commit:**
- `self._notification_icon = self._get_icon("pytodo-qt.svg")` (line 1206).
- The `QSystemTrayIcon,` import can stay — still used for tray construction.

**Verification:**
- Typecheck, full test suite, ruff all clean.
- `grep -n showMessage src/pytodo_qt/gui/main_window.py` → only tray-icon
  construction code, no notification sites.
- No reference to `_notification_icon` remains.

### Commit 3 — PyInstaller bundling + DMG verification

**Files touched:**
- `packaging/pyinstaller/pytodo-qt.spec`:
  - Add `"desktop_notifier"` to `hiddenimports`.
  - Add `"rubicon.objc"` to `hiddenimports` (macOS transitive).
  - Potentially `collect_submodules("desktop_notifier")` if the library uses
    dynamic dispatch for backend selection (verify by reading its source once
    the dep is installed).

**Verification loop (on macOS):**
1. `uv sync` — pulls in the new dep.
2. Build DMG locally: follow the usual packaging workflow (same as dev7).
3. Install DMG, launch installed `.app`.
4. Confirm the macOS permission prompt appears exactly once on first launch.
5. Trigger each of the five notification sites and visually verify:
   - Title renders correctly.
   - Body text renders correctly (multiline for the reminder digest).
   - App icon renders correctly (bundle icon, no rocketship regression).
6. Launch `.app` a second time; confirm no second permission prompt.
7. Revoke permission in System Settings, trigger a notification; confirm
   silent failure and DEBUG log line, no crash.
8. `uv run python -m pytodo_qt` (from source) — confirm notifications
   degrade silently, no crash.

## Test Strategy

- **Unit tests:** mock `DesktopNotifier.send` as an AsyncMock; verify each of
  the five call paths routes through `_notify` with the expected title/body.
  Add to `tests/gui/test_notifications.py` (new file, patterned after the
  existing tray tests).
- **No live notification delivery in tests.** `QT_QPA_PLATFORM=offscreen`
  already prevents real tray rendering; the `DesktopNotifier` instance can be
  replaced with a `MagicMock()` at `MainWindow.__init__` time in a fixture.
- **Integration:** covered by the manual DMG verification loop in Commit 3.
  There is no CI path for signed `.app` + permission prompts, so the manual
  loop is the contract.

## Platform Behavior Matrix

| Environment                    | Today                                     | After migration                               |
|--------------------------------|-------------------------------------------|-----------------------------------------------|
| macOS DMG `.app` (signed)      | Generic "PyTodo-Qt Notification" banner  | Full title + body, bundle icon, one-time prompt |
| macOS `uv run` (no bundle)     | Rocketship icon, sometimes full text      | Log-only fallback, no crash                   |
| Linux libnotify                | Full title + body                         | Full title + body (unchanged)                 |
| Windows (future Inno Setup)    | (not yet shipping)                        | Full title + body via WinRT                   |

## Rollback Plan

Each commit is independently revertible. If Commit 3 reveals a PyInstaller
bundling issue we can't resolve quickly, revert Commits 2 and 3 and ship
with the helper dormant in Commit 1 — behavior is identical to today. If the
library itself turns out to misbehave on a specific macOS version, revert all
three commits; the five `showMessage` call sites in Commit 2 are a pure
mechanical diff and restore cleanly.

## Out of Scope (explicitly not doing here)

- Rewriting the tray menu or activation logic.
- Changing the sound-playback side of pomodoro transitions
  (`self._sound_player.play(...)` stays as-is).
- Web UI notifications (separate PWA code path in `web/static/app.js`).
- Icon customization beyond what the bundle already provides. The memory
  `project-macos-notifications.md` abandonment stands — we are not trying to
  override the bundle icon from runtime APIs.

## Open Questions

None blocking. Confirm before Commit 3:

1. ~~Does `desktop-notifier>=6.0` actually exist with a 6.x line?~~ Resolved
   during Commit 1 — latest stable is 6.2.0, first stable 6.x is 6.1.0.
   Pinned `>=6.1` in `pyproject.toml`. Method name is `request_authorisation`
   (British spelling), `send()` timeout is `int` seconds.
2. Does `rubicon-objc` need explicit `binaries=` entries, or do
   `hiddenimports` alone suffice? Check PyInstaller output during the first
   DMG build; adjust as needed.
