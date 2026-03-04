# Pomodoro / Focus Timer — Design Document

## Purpose

A lightweight focus timer integrated into pytodo-qt that pairs with the currently selected todo item. Users can start a timed work session, take structured breaks, and automatically track time spent on tasks. The timer brings the Pomodoro Technique — one of the most widely adopted productivity methods — directly into the task management workflow without requiring a separate app.

## Why This Feature

Productivity apps like Super Productivity, TickTick, and Toggl have demonstrated that timer integration is one of the most requested features in task management tools. The key insight is that a timer tied to a specific task turns a todo list from a passive record into an active work tool. pytodo-qt already tracks per-item state (priority, due date, completion) — a timer is the natural extension for tracking *effort*.

## Timer State Machine

```
                    ┌──────────────────────────────────────────┐
                    │                                          │
                    ▼                                          │
              ┌──────────┐    start()    ┌──────────────┐      │
              │          │──────────────→│              │      │
              │   IDLE   │               │   WORKING    │──────┤ stop()
              │          │←──────────────│              │      │
              └──────────┘    stop()     └──────┬───────┘      │
                    ▲                           │              │
                    │                     timer expires        │
                    │                           │              │
                    │                           ▼              │
                    │                    ┌──────────────┐      │
                    │       stop()       │              │      │
                    │←───────────────────│    BREAK     │──────┘
                    │                    │              │
                    │                    └──────┬───────┘
                    │                           │
                    │                     timer expires
                    │                           │
                    │                           ▼
                    │                    ┌──────────────┐
                    │       stop()       │              │
                    └────────────────────│   WORKING    │ (next session auto-starts
                                        │              │  if auto_start_break=True)
                                        └──────────────┘
```

### States

| State | Description | Display |
|-------|-------------|---------|
| **IDLE** | No timer running. Widget hidden or shows "Start Focus" button. | Hidden in status bar |
| **WORKING** | Active work session counting down. | `25:00` in status bar (red/orange) |
| **BREAK** | Break period counting down after work session completes. | `5:00` in status bar (green) |
| **PAUSED** | Timer frozen mid-session. Preserves remaining time. | `12:34` with pause indicator |

### Transitions

| From | To | Trigger | Side Effects |
|------|-----|---------|-------------|
| IDLE → WORKING | User clicks "Start" or presses shortcut | Capture selected item UUID, start countdown |
| WORKING → BREAK | Work timer expires | Add `work_duration` to item's `time_spent`, increment session count, emit `session_completed` signal |
| WORKING → PAUSED | User clicks "Pause" | Freeze remaining time |
| PAUSED → WORKING | User clicks "Resume" | Resume countdown from frozen time |
| BREAK → WORKING | Break timer expires (if auto-continue) | Start next work session on same item |
| BREAK → IDLE | Break timer expires (if not auto-continue) | Reset session |
| Any → IDLE | User clicks "Stop" | If stopping WORKING, partial time is NOT added (incomplete session) |

### Long Break Logic

After every `sessions_before_long_break` completed work sessions (default: 4), the break duration switches from `break_duration` (5 min) to `long_break_duration` (15 min). The session counter resets after the long break.

```
Session 1 (25 min) → Short break (5 min)
Session 2 (25 min) → Short break (5 min)
Session 3 (25 min) → Short break (5 min)
Session 4 (25 min) → Long break (15 min) → counter resets
Session 5 (25 min) → Short break (5 min)
...
```

## UI Components

### 1. Status Bar Timer

A compact display in the left section of `StatusBarWidget`, between the progress bar and list count:

```
[███████  45%] | 🍅 23:41 | Lists: 3 | Current: 5/12 | ...
```

- Shows tomato icon + countdown during WORKING
- Shows coffee icon + countdown during BREAK
- Shows pause icon when PAUSED
- Hidden when IDLE (no wasted space)
- Clicking the status bar timer opens/focuses the floating timer window

### 2. Floating Timer Window

A small always-on-top dialog (`QDialog` with `Qt.WindowStaysOnTopHint`) for when the user wants the timer visible while working in other apps:

```
┌─────────────────────────────────┐
│  Focus Timer           _ □ ✕   │
├─────────────────────────────────┤
│                                 │
│         23:41                   │
│    ━━━━━━━━━━━━━━━━━━━         │
│    "Write API endpoints"       │
│                                 │
│    Session 2 of 4              │
│                                 │
│   [ ⏸ Pause ]  [ ■ Stop ]     │
│                                 │
└─────────────────────────────────┘
```

Features:
- Large countdown display
- Progress bar showing session progress
- Current item reminder text
- Session counter (e.g., "Session 2 of 4")
- Pause/Resume and Stop buttons
- Accessible via menu: Tools → Focus Timer (Ctrl+T)

### 3. Context Menu Integration

Right-click on a todo item shows "Start Focus Session" which begins a Pomodoro timer for that specific item. If a session is already running on a different item, prompt: "A focus session is active on '{item}'. Stop it and start a new one?"

## Time Tracking Model

### Data Model Change

Add to `TodoItem` in `models.py`:

```python
time_spent: int = 0  # Total seconds of completed focus sessions
```

This field:
- Accumulates only from *completed* work sessions (stopping mid-session discards partial time)
- Is measured in seconds for precision (displayed as human-readable: "1h 25m")
- Serializes to/from dict like all other fields
- Syncs via existing LWW mechanism
- Requires schema v10 migration: `ALTER TABLE items ADD COLUMN time_spent INTEGER DEFAULT 0`

### Display

- Tooltip on item row: "Time spent: 1h 25m (3 sessions)"
- Optionally visible in a future "details panel" or "item info" dialog
- Web UI will show time_spent in item details

### Why Not Track Per-Session History

A simpler model (cumulative seconds) was chosen over per-session logging (timestamps, durations) because:
1. No UI to display session history is planned
2. Cumulative time is the only metric users typically want
3. Less storage, simpler sync, no additional schema complexity
4. Per-session logging can be added later without breaking the cumulative field

## Configuration

```python
@dataclass
class PomodoroConfig:
    work_duration: int = 25      # minutes (1-120)
    break_duration: int = 5      # minutes (1-30)
    long_break_duration: int = 15  # minutes (5-60)
    sessions_before_long_break: int = 4  # (2-10)
    auto_start_break: bool = True
```

### Settings Dialog — Pomodoro Tab

```
┌─────────────────────────────────────────────┐
│  Focus Timer                                │
│  ┌───────────────────────────────────────┐  │
│  │ Work duration:     [25    ▾] minutes  │  │
│  │ Break duration:    [ 5    ▾] minutes  │  │
│  │ Long break:        [15    ▾] minutes  │  │
│  │ Sessions before    [ 4    ▾]          │  │
│  │   long break:                         │  │
│  │ ☑ Auto-start break after work session │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

Spin boxes with reasonable min/max ranges. Config persisted in TOML under `[pomodoro]` section.

## Signals and Integration

### PomodoroWidget Signals

| Signal | Emitted When | MainWindow Handler |
|--------|-------------|-------------------|
| `session_completed(UUID, int)` | Work session ends normally | Add seconds to item's `time_spent`, save, refresh |
| `break_started()` | Break countdown begins | Update status bar |
| `timer_stopped()` | User manually stops | Update status bar, clear focus item |
| `state_changed(str)` | Any state transition | Update status bar display |

### MainWindow Wiring

```python
self._pomodoro = PomodoroWidget(self._config.pomodoro, self)
self._pomodoro.session_completed.connect(self._on_pomodoro_session_completed)
self._pomodoro.state_changed.connect(self._status_bar.update_pomodoro_display)
```

The `_on_pomodoro_session_completed` handler creates an `EditTimeSpentCommand` (undo-able) that adds the session duration to the item's `time_spent` field.

## Notifications

- System notification (via `QSystemTrayIcon.showMessage()`) when a work session ends: "Focus session complete! Time for a break."
- System notification when break ends: "Break is over. Ready for the next session?"
- Notifications are non-blocking and respect system notification settings
- No sound (rely on system notification sounds)

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Item deleted while timer running | Timer stops gracefully, time discarded |
| Item completed while timer running | Timer continues — user may be finishing work |
| App closed while timer running | Timer state is NOT persisted across sessions (ephemeral) |
| List switched while timer running | Timer continues — it's bound to item UUID, not list |
| Sync changes item while timer running | No effect — timer only reads item at start |
