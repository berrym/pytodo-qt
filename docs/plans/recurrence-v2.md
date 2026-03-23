# Recurrence v2: Natural Cycling with Subtask Reset

**Status:** Design
**Depends on:** Schema v15 (current), subtasks, kanban board, pomodoro

---

## Problem

Recurring items complete and never come back. The user marks "Take morning meds" done, it stays in the Done column permanently. The current model advances the due date and resets `complete=False` immediately on toggle — the user never sees the satisfying checkmark. And subtasks (individual doses, steps within a routine) are never reset, so the next occurrence shows stale completion state.

The medication tracking use case makes this concrete: a person takes 3 doses daily. Each dose is a subtask. They check off each dose throughout the day. At the start of the next day, the whole thing should cycle back to "To Do" with all subtasks unchecked — ready for the new day. Not immediately on the last checkmark. Naturally.

---

## What Already Works

| Component | Status |
|-----------|--------|
| `recurrence_type` (daily/weekly/monthly/yearly) + `interval` | Working |
| `compute_next_due_date()` | Working |
| `advance_overdue_recurring()` — runs on startup, every 60s, after sync | Working |
| `missed_recurrences` tracking | Working |
| `recurrence_count` / `recurrence_end_count` / `recurrence_end_date` | Working |
| Subtasks (`parent_id`, `get_children()`, child completion tracking) | Working |
| `_best_incomplete_column()` — smart kanban placement | Working |
| Desktop `ToggleCompleteRecurringCommand` | Working (but resets immediately) |
| Auto-advance timer (60s interval) | Working |
| Pomodoro/focus per item | Working |
| iCal basic support | Working |

---

## Design

### Core Principle: Complete Now, Cycle Naturally

1. **User toggles recurring item complete** → item shows as complete (checkmark visible, moves to Done column). User gets the feedback they earned.
2. **At the next cycle boundary** (next due date arrives), the auto-advance system resets the item:
   - `complete` → `False`
   - `due_date` → next occurrence
   - `recurrence_count` += 1
   - `board_column` → "In Progress" (if has work history/subtask progress) or "To Do" (first column)
   - All subtasks → `complete = False` (reset for next cycle)
3. **In list view**: reset item appears at essentially new-task priority so it's never lost in the noise.

### Toggle Behavior Change

**Current:** `ToggleCompleteRecurringCommand.redo()` immediately sets `complete=False`, advances `due_date`, increments `recurrence_count`. User never sees the completion.

**New:** Toggle just sets `complete=True` and increments `recurrence_count`. Due date stays at current value. The item is genuinely complete — for now. The auto-advance system handles the cycle reset when the next occurrence is due.

Same for the web API `handle_toggle_item`: mark complete, increment count, sync board column to Done. Don't advance inline.

### Auto-Advance Extension

`advance_overdue_recurring()` currently skips complete items (`if item.complete: return False`). Extend it to also handle complete recurring items whose next occurrence has arrived:

```
if item.is_recurring and item.complete:
    next_due = compute_next_due_date(item.due_date, ...)
    if next_due <= today:
        # Time to cycle
        item.complete = False
        item.due_date = next_due
        item.board_column = best_column(item, list)
        reset_subtask_completions(item, list)
        item.mark_updated()
```

The 60-second timer is the check frequency, NOT the reset delay. The reset only fires when `next_due <= today` — meaning the next occurrence has actually arrived. A daily item completed at 2pm Tuesday stays complete all of Tuesday. It resets Wednesday morning (within 60 seconds of the app running on Wednesday, or at next app startup). A weekly item completed Monday stays complete all week. It resets the following Monday. The item is genuinely done for its current cycle — it only comes back when the user actually needs it again.

### Subtask Reset

When a recurring parent cycles to its next occurrence, ALL child subtasks reset:

```python
def reset_subtask_completions(parent_id: UUID, todo_list: TodoList) -> None:
    for child in todo_list.items.values():
        if child.parent_id == parent_id and not child.deleted and child.complete:
            child.complete = False
            child.mark_updated()
```

This means "Morning dose", "Afternoon dose", "Evening dose" all come back unchecked for the new day.

### Kanban Column Reset Logic

On cycle reset, the item's board column is set by `_best_incomplete_column()`:

- If item has pomodoro time or completed subtask history → "In Progress" (it's been worked on before)
- Otherwise → first column ("To Do" / inbox)
- If no suitable column found in preset/custom layout → first column

In list view: recurring items that just cycled should sort near the top (they're active, they're due).

### What Doesn't Change

- **Exhaustion**: if `recurrence_count >= recurrence_end_count`, the toggle path is normal (stays complete permanently). No cycling.
- **Manual stop**: user can delete recurrence rule at any time → normal item behavior.
- **Missed occurrences**: `missed_recurrences` still tracks auto-advanced overdue items. Only completed-then-cycled items go through the new path.
- **Pomodoro**: focus sessions are independent. A recurring item's focus history persists across cycles. User starts/stops/completes focus whenever they want.
- **Subtask structure**: subtasks are user-created and user-managed. The system only resets their `complete` flag, never creates/deletes/modifies them.

---

## Schema Changes

**None required.** All fields needed already exist:
- `complete`, `due_date`, `recurrence_*`, `missed_recurrences`, `board_column` on TodoItem
- `parent_id` for subtasks
- Subtask `complete` flag

The behavior change is in the advance/toggle logic, not the data model.

---

## Implementation Plan

### Step 1: Change toggle to mark complete without immediate advance

**Desktop (`gui/commands.py`):**
- `ToggleCompleteRecurringCommand.redo()`: set `complete=True`, increment `recurrence_count`, sync `board_column` to completion column. Do NOT advance `due_date` or reset `complete`.
- `ToggleCompleteRecurringCommand.undo()`: restore previous state (existing behavior works).

**Web API (`web/api.py`):**
- `handle_toggle_item`: same logic — mark complete, increment count, sync to Done column. No inline advance.

### Step 2: Extend auto-advance to cycle completed recurring items

**Core (`core/models.py`):**
- Extend `advance_overdue_recurring()` to handle `item.complete == True` case.
- Add `_reset_subtask_completions()` helper.
- When next occurrence date has arrived AND item is complete → cycle it.

### Step 3: Ensure kanban column resets correctly

- `_best_incomplete_column()` already handles this correctly.
- Verify it's called from the auto-advance path.
- Verify web API toggle syncs board column to Done on completion.

### Step 4: Tests

- Toggle recurring item → shows as complete, due_date unchanged
- Auto-advance picks up completed recurring → resets complete, advances date, resets subtasks
- Subtask completion preserved until cycle boundary
- Kanban column cycling: To Do → Done (on complete) → In Progress or To Do (on cycle reset)
- Exhausted recurrence stays complete (no cycling)
- Web API toggle matches desktop toggle behavior
- List view: cycled items sort appropriately

### Step 5: Verify interop

- Desktop toggle → web sees completion → web sees cycle reset
- Web toggle → desktop sees completion → desktop sees cycle reset
- P2P sync carries recurring state correctly

---

## Subtask Recurrence Independence

Subtasks are already full `TodoItem` instances with their own `due_date`, `due_time`, `recurrence_type`, `recurrence_interval`, and all other fields. Currently these recurrence fields are ignored on subtasks — only the parent drives the cycle.

### The Change

Allow subtask recurrence fields to function independently when set:

- A subtask with no recurrence of its own follows the parent's cycle (reset when parent cycles — current plan above)
- A subtask WITH its own recurrence runs on its own schedule, independent of the parent
- This enables: parent "Take Medication X" (daily) with subtasks "Morning dose" (due 8am, daily), "Afternoon dose" (due 12pm, daily), "Evening dose" (due 6pm, daily)
- Each subtask tracks its own `recurrence_count`, `missed_recurrences`, completion state
- The auto-advance system handles subtasks the same way it handles top-level items — complete ones cycle when their next occurrence arrives

### Dead Simple by Default

- User creates a recurring task with subtasks → subtasks have no recurrence → they reset with the parent. Simple.
- User WANTS per-subtask scheduling → they set due_time and/or recurrence on individual subtasks. Full control.
- The system provides the capability. The user decides how much complexity they need. Zero to full flexibility with no mode switches.

### No Schema Change

Subtasks already have all the recurrence fields (they're TodoItems). The change is purely behavioral — `advance_overdue_recurring` needs to process subtasks with independent recurrence, and the toggle/reset logic respects subtask-level recurrence when present.

---

## Future Extensions (not in this pass)

- **Calendar view**: visual display of recurring items on a timeline.
- **Dose/titration tracking**: user annotations per completion ("took 500mg", "felt dizzy").
- **Smart notifications**: "You missed your 12pm dose" based on due_time + subtask completion state.
- **Adaptive scheduling**: system suggests optimal times based on completion patterns.
