# Pomodoro Evolution — Complete Focus Timer Roadmap

## Context

The basic Pomodoro timer is functional: state machine, floating window, status bar display, toolbar buttons, context menu, system notifications, configurable durations, and cumulative `time_spent` tracking. This document plans the evolution from "functional timer" to "complete productivity system" — making pytodo-qt's focus timer implementation as good or better than anything in the commercial task management space, while staying true to the local-first, privacy-respecting identity.

The goal is not to copy Todoist but to serve users Todoist can't serve: those who want the best focus timer experience without giving up their data.

---

## Current State (What Exists)

| Feature | Status |
|---------|--------|
| Timer state machine (IDLE/WORKING/BREAK/PAUSED) | Done |
| Configurable work/break/long break durations | Done |
| Auto-start break, sessions before long break | Done |
| Floating timer window (always-on-top) | Done |
| Status bar display with SVG icons | Done |
| Toolbar play/pause/stop buttons | Done |
| Context menu "Start Focus Session" | Done |
| Active-session prompt (switch item confirmation) | Done |
| System tray notifications (work/break transitions) | Done |
| Pause during break | Done |
| `time_spent` cumulative field on TodoItem | Done |
| `PomodoroConfig` in TOML with Settings UI | Done |

---

## Gap Analysis (What's Missing)

### From the Original Design Doc (unimplemented)
1. `EditTimeSpentCommand` — time tracking should be undo-able
2. Tooltip on item row: "Time spent: 1h 25m (3 sessions)"
3. Graceful timer stop when item is deleted while running
4. `break_started()` / `timer_stopped()` signals (currently only `state_changed`)

### From Pomodoro Technique Best Practices
5. Per-task pomodoro count (completed sessions, not just cumulative seconds)
6. Per-task pomodoro estimate (how many sessions the user thinks a task will take)
7. Session logging with timestamps (foundation for analytics)
8. Daily pomodoro goal / target
9. Task breakdown suggestion (when estimate exceeds 4 pomodoros)
10. Interruption tracking during sessions
11. Sound/audio notifications (optional, in addition to system notifications)

### From Productivity App Landscape
12. Productivity reporting / analytics (daily, weekly, trends)
13. Gamification (streaks, achievements, visual progress indicators)
14. Focus mode / distraction shielding
15. Session history view

---

## Phased Implementation Plan

### Phase A: Foundation Fixes (Low effort, high correctness)

**Goal:** Complete what the design doc specified but wasn't implemented.

#### A1. Undo-able Time Tracking

Add `EditTimeSpentCommand` to `gui/commands.py`:

```python
class EditTimeSpentCommand(QUndoCommand):
    """Add focus session time to an item (undo-able)."""
    def __init__(self, main_window, item_id, seconds_to_add):
        self._old_time_spent = item.time_spent
        self._new_time_spent = item.time_spent + seconds_to_add
```

Update `_on_pomodoro_session_completed()` to push this command onto the undo stack instead of mutating directly.

#### A2. Time Spent Tooltip

In `TodoTableWidget.refresh()`, set tooltip on each row's reminder `QLineEdit`:

```python
if item.time_spent > 0:
    spent_str = PomodoroWidget.format_time_spent(item.time_spent)
    edit.setToolTip(f"Time spent: {spent_str}")
```

#### A3. Graceful Stop on Item Deletion

In `_on_delete_todo()`, check if the pomodoro timer is running on the deleted item:

```python
if self._pomodoro.item_id == item_id:
    self._on_stop_focus()
```

#### A4. Time Spent Display in Table

Add a subtle time indicator near the reminder text (or as a separate narrow column) for items with `time_spent > 0`. Display as "25m" or "1h 25m" — unobtrusive but visible.

---

### Phase B: Per-Task Pomodoro Tracking (Moderate effort, schema change)

**Goal:** Track completed pomodoro count per task, separate from raw seconds. Enable estimation and comparison.

#### B1. Schema Changes

Add to `TodoItem` in `models.py`:

```python
pomodoro_count: int = 0           # Completed pomodoro sessions
estimated_pomodoros: int = 0      # User's estimate (0 = no estimate)
```

Schema migration (v11 or later):
```sql
ALTER TABLE items ADD COLUMN pomodoro_count INTEGER DEFAULT 0;
ALTER TABLE items ADD COLUMN estimated_pomodoros INTEGER DEFAULT 0;
```

Backward-compatible via `.get()` defaults in `from_dict()`.

#### B2. Increment on Session Complete

`_on_pomodoro_session_completed()` also increments `pomodoro_count`:

```python
item.pomodoro_count += 1
```

Include in the `EditTimeSpentCommand` (or create `EditPomodoroSessionCommand` that updates both `time_spent` and `pomodoro_count` atomically).

#### B3. Pomodoro Estimate UI

In `AddTodoDialog` (and future item detail view):
- Optional "Estimated pomodoros" spin box (0 = no estimate, 1-12)
- Display in table as "🍅×3" or "2/4 🍅" (completed/estimated)

#### B4. Task Breakdown Suggestion

When a task's `pomodoro_count` reaches its `estimated_pomodoros` and the task isn't complete, or when `estimated_pomodoros > 4`:
- Show a gentle suggestion: "This task has taken {N} pomodoros. Consider breaking it into subtasks."
- Non-blocking — a status bar message or tooltip, not a modal dialog
- When subtasks are implemented (see [subtasks-design.md](subtasks-design.md) — committed for this release cycle), the suggestion can offer a one-click "Break into subtasks" action that creates child items under the current task

---

### Phase C: Session Logging (Moderate effort, new table)

**Goal:** Record individual focus sessions for analytics and history.

#### C1. Focus Session Table

New SQLite table:

```sql
CREATE TABLE IF NOT EXISTS focus_sessions (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    list_id TEXT NOT NULL,
    start_time TEXT NOT NULL,      -- ISO 8601
    end_time TEXT NOT NULL,        -- ISO 8601
    duration_seconds INTEGER NOT NULL,
    completed BOOLEAN NOT NULL,    -- True if session ran to completion
    session_type TEXT NOT NULL,    -- "work" or "break"
    date TEXT NOT NULL             -- YYYY-MM-DD for easy grouping
);
```

#### C2. Session Recording

On `session_completed`, create a `FocusSession` record and persist it. On `stop()` during WORKING, optionally record an incomplete session (for interruption tracking).

#### C3. Session History in Floating Timer

Add a collapsible "Today's Sessions" section to `FocusTimerDialog`:

```
Session 1: 25:00 ✓  (10:15 - 10:40)
Session 2: 25:00 ✓  (10:45 - 11:10)
Session 3: 18:32 ✗  (11:15 - 11:33)  ← interrupted
```

#### C4. Sync Strategy

Focus sessions **should sync** across devices. The rationale for keeping them local-only (reduced complexity) doesn't hold up for multi-device users — pytodo-qt's core audience. If you work on your laptop at a coffee shop then your desktop at home, your "today's sessions" and weekly analytics must reflect both devices' work. Incomplete data produces misleading analytics, which undermines trust in the system.

Fortunately, session sync is **simpler than item sync**:
- Sessions are **append-only** — once created, they're never edited
- No LWW conflicts are possible — each session has a unique UUID
- Merge is trivial: if the remote has a session ID we don't have, add it
- Sessions reference items by UUID, which already syncs
- The `focus_sessions` table gets included in the sync payload alongside items

The existing sync protocol's `to_dict()`/`from_dict()` pattern extends naturally. Session data is small (one row per 25-minute session) so bandwidth impact is negligible.

---

### Phase D: Productivity Analytics (Moderate-high effort, new dialog)

**Goal:** Help users understand their focus patterns and improve over time.

#### D1. Daily Pomodoro Goal

Add to `PomodoroConfig`:

```python
daily_goal: int = 0  # Target pomodoros per day (0 = no goal)
```

Display progress in the floating timer or status bar: "Today: 3/8 🍅"

#### D2. Focus Stats Dialog

New dialog accessible from Tools → Focus Stats (or a tab in the floating timer):

```
┌─────────────────────────────────────────────┐
│  Focus Statistics                           │
├─────────────────────────────────────────────┤
│                                             │
│  Today          This Week       This Month  │
│  ━━━━━━━━       ━━━━━━━━━━      ━━━━━━━━━  │
│  6 pomodoros    28 pomodoros    89 pomodoros │
│  2h 30m         11h 40m        37h 05m     │
│  Goal: 8 🍅     Avg: 5.6/day               │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  Weekly Chart (bar graph)           │    │
│  │  Mon ████████ 7                     │    │
│  │  Tue ██████ 5                       │    │
│  │  Wed ████████████ 10                │    │
│  │  Thu ████ 3                         │    │
│  │  Fri ██████ 5                       │    │
│  │  Sat ██ 2                           │    │
│  │  Sun ████ 3                         │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  Top Tasks This Week:                       │
│  1. Write API endpoints    — 8 🍅 (3h 20m) │
│  2. Fix sync bug           — 5 🍅 (2h 05m) │
│  3. Review pull requests   — 4 🍅 (1h 40m) │
│                                             │
│  Current Streak: 5 days 🔥                  │
│                                             │
└─────────────────────────────────────────────┘
```

Implementation: Query `focus_sessions` table grouped by date. Use Qt's QPainter or simple styled QProgressBars for the bar chart (no external charting dependency).

#### D3. Streak Tracking

A "streak" is consecutive days with at least 1 completed pomodoro (or reaching the daily goal). Computed from `focus_sessions` on demand — no separate storage needed.

Display in floating timer footer or stats dialog.

---

### Phase E: Gamification & Habit Building (Moderate effort)

**Goal:** Make the Pomodoro experience rewarding and habit-forming. Associate focus time with progress, not obligation.

#### E1. Visual Progress Indicators

- Tomato icons that "fill up" as pomodoros are completed: ◯◯◯◯ → 🍅◯◯◯ → 🍅🍅◯◯ → etc.
- Daily goal progress ring in status bar (subtle, like Apple Watch activity rings)
- "Pomodori" count badge on the floating timer

#### E2. Milestone Celebrations

Non-intrusive celebrations at milestones:
- First pomodoro of the day: "Good start! 🍅"
- Daily goal reached: "Goal achieved! 🎯"
- New streak record: "New record: 10-day streak! 🔥"
- 100th lifetime pomodoro: "Century! 💯"

Delivered via system notification or a brief toast in the floating timer. Keep it lightweight — no modal dialogs or animations that interrupt flow.

#### E3. Focus Score (Optional)

A simple daily "focus score" computed from:
- Pomodoros completed vs. goal
- Completion rate (completed vs. interrupted sessions)
- Consistency (streak)

Displayed as a single number (0-100) or letter grade. Helps users track improvement without being prescriptive.

---

### Phase F: Sound & Focus Mode (Low-moderate effort)

**Goal:** Complete the sensory feedback loop and reduce distractions during focus time.

#### F1. Sound Notifications

Add to `PomodoroConfig`:

```python
sound_enabled: bool = False       # Play sound on session transitions
sound_volume: int = 50            # 0-100
```

Use Qt's `QSoundEffect` for cross-platform audio. Bundle 2-3 subtle sound files (bell, chime, soft alert). Play on:
- Work session complete
- Break complete
- Timer start (optional)

Settings UI: checkbox + volume slider in the Pomodoro settings tab.

#### F2. Focus Mode (Future)

A "Do Not Disturb" integration that, while a pomodoro is running:
- Suppresses auto-sync status bar messages (queue them for after the session)
- Optionally dims or hides non-essential UI elements
- Shows a subtle "In Focus" indicator

This is lower priority — the floating timer window already provides visual focus, and system-level DND is better handled by the OS.

---

## Schema Evolution Summary

| Version | Fields Added | Phase |
|---------|-------------|-------|
| v10 (current) | `time_spent` | Already done |
| v11 | `pomodoro_count`, `estimated_pomodoros` | Phase B |
| v11+ | `focus_sessions` table (new, not ALTER) | Phase C |

All item field additions follow the established pattern: `ALTER TABLE`, `.get()` defaults, LWW-compatible.

The `focus_sessions` table syncs via append-only merge (no conflicts possible). Sessions are included in the sync payload and merged by unique ID.

---

## Priority and Sequencing

| Phase | Effort | Value | Dependency |
|-------|--------|-------|------------|
| **A: Foundation Fixes** | Low | High | None — correctness |
| **B: Per-Task Tracking** | Moderate | High | Phase A |
| **C: Session Logging** | Moderate | Moderate | Phase B (for pomodoro_count) |
| **D: Analytics** | Moderate-high | High | Phase C (needs session data) |
| **E: Gamification** | Moderate | Moderate | Phase C-D (needs data to gamify) |
| **F: Sound & Focus** | Low-moderate | Moderate | None — independent |

**Recommended order:** A → B → F → C → D → E

Phase F (sound) is independent and can slot in anywhere — it's a quick win for perceived completeness. Gamification (E) comes last because it requires the data infrastructure from C and D to be meaningful.

---

## Design Principles

1. **Never interrupt flow** — Celebrations, suggestions, and analytics should never block a running timer or require dismissal during a work session
2. **Earn trust through accuracy** — Time tracking must be precise and undo-able. Users should trust the numbers
3. **Opt-in complexity** — Basic use (start timer, work, take break) should work with zero configuration. Estimates, goals, analytics, and gamification are progressive disclosure
4. **Sync everything valuable** — Focus session data syncs across devices via append-only merge. Multi-device users (pytodo-qt's core audience) need complete analytics, not per-device fragments. Complexity is never a reason to withhold genuine value
5. **Adapt to the user** — The system should help users discover their natural rhythm, not enforce a rigid 25/5 structure. Customizable intervals are already supported; analytics will reveal what actually works for each person
6. **Don't fear hard changes** — Schema migrations, architectural changes, and new subsystems are welcome when they deliver real value. The 0.3.x series has as many releases as it needs before 0.4.x

---

## Related Design Documents

- [subtasks-design.md](subtasks-design.md) — Subtask system (committed for this release cycle). Task breakdown suggestions in Phase B4 will create subtasks directly
- [kanban-design.md](kanban-design.md) — Kanban board view. "In Progress" column ties naturally to active focus sessions
- [natural-language-input.md](natural-language-input.md) — Smart task input. Pomodoro estimates parseable as "~3p" or "~2 pomodoros"

---

## What This Achieves

When fully implemented, pytodo-qt's focus timer will offer:

- **What Todoist has:** Timer integration, task association, session tracking
- **What Todoist doesn't have:** Built-in timer (Todoist requires third-party integration like Toggl), privacy-respecting analytics synced across devices, per-task pomodoro estimation with actual-vs-estimate tracking, undo-able time tracking, always-on-top floating window, sound notifications without a browser, P2P-synced session history, subtask integration for task breakdown, Kanban board integration for visual workflow
- **What nobody has well:** A complete productivity system — Pomodoro + Kanban + subtasks + analytics — that respects user privacy, syncs peer-to-peer, and never sends data to a third party
