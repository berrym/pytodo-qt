# Timeline View — Analytics Bar Logic and Roadmap

## Current Implementation

The timeline sub-view of the calendar view shows horizontal bars per task representing three dimensions of task data.

### Bar Types

**Blue — Time Span**
- Spans from `created_at` date to end of `due_date` (inclusive)
- If no `due_date`, spans from creation to today
- Represents the window of time available to complete the task
- Scales proportionally against the 14-day timeline axis

**Amber — Estimated Effort**
- Appears only when `estimated_pomodoros > 0`
- Width = `estimated_pomodoros × 15px`, capped at blue bar width
- Minimum 20px for visibility
- Represents how much work the user expects the task to require
- Independent of time span — 12 sessions = 180px whether the task spans 1 day or 30 days

**Green — Actual Work Done**
- With estimate: `(actual_sessions / estimated_sessions) × amber_width`
  - 6 of 12 completed = green is exactly half of amber
  - Capped at ratio 1.0 (green never exceeds amber)
- Without estimate: `actual_sessions × 15px`, capped at blue bar width
  - Shows absolute effort independent of time span
- `actual_sessions` = `time_spent / (work_duration_mins × 60)` when `time_spent > 0`
- Falls back to `pomodoro_count` when `time_spent` is 0
- `work_duration_mins` read from `config.pomodoro.work_duration` (stored in minutes)

### Key Design Decision

Effort bars (amber/green) scale by session count × constant pixel width, NOT by calendar time. This avoids the dimensional mismatch of comparing effort-minutes to calendar-days, which produces nonsensical proportions (e.g., 12 minutes of work as a fraction of a 2-day span).

The tradeoff: bars show HOW MUCH work, not WHEN it happened.

### The 15px-per-session Constant

This is an arbitrary visual constant chosen to make session counts readable at typical window sizes. It has no mathematical basis — it simply produces bars that are wide enough to see and compare. Future versions should derive this from viewport width and task density.

---

## Known Limitations

### 1. Estimate Overflow
If estimated work exceeds available time (e.g., 20 sessions of 25 min = 8+ hours in a same-day deadline), amber caps at blue bar width. There is NO visual indication that the user has overcommitted — the amber bar silently caps.

**Should show:** Amber overflowing past blue with a distinct color/pattern to indicate "more work estimated than time available."

### 2. Actual Work Exceeding Estimate
Green bar ratio caps at 1.0. If you complete 15 sessions against a 12-session estimate, green equals amber. There is NO visual for working more than planned.

**Should show:** Green overflowing past amber to indicate "worked more than estimated."

### 3. Overdue Tasks
Blue bar ends at due date. If the task is overdue, there is NO red/warning section showing time past the deadline. An overdue task with work still being done has green growing within a blue bar that ended days ago.

**Should show:** Red section from due date to today, with green bars continuing into the red zone if work is ongoing.

### 4. Work Distribution Over Time
Green bar shows total sessions completed, not when they were done. A task where all 6 sessions happened in one morning looks identical to one where sessions were spread across 3 days. The timeline shows effort amount, not effort timing.

**Could show:** Using the existing `focus_sessions` table (which records start_time, end_time per session), render actual work blocks at their real positions on the time axis — Gantt-chart style.

### 5. Per-Task Pomodoro Duration
All tasks use the global `config.pomodoro.work_duration`. There is no per-task override. A coding task might need 50-minute deep work sessions while a quick email check is 5 minutes — both use the same global setting.

**Needed:** `work_duration` field on `TodoItem` (optional, falls back to config default).

### 6. Non-Pomodoro Work
The only way to log work time is through the pomodoro timer. If a user works on a task for 2 hours without starting a pomodoro session, that work is invisible to the timeline.

**Needed:** Manual time logging (start/stop timer or after-the-fact entry).

### 7. Variable Config Changes
If the user changes `work_duration` between sessions (e.g., 25 min → 45 min), `time_spent` accumulates correctly in seconds, but `pomodoro_count × current_duration` won't match historical `time_spent`. The timeline uses `time_spent` as ground truth when available, which is correct.

---

## Future Improvements (Pomodoro Phases D-F)

### Phase D: Productivity Analytics
- Use `focus_sessions` table timestamps for Gantt-chart work distribution
- Daily/weekly work summaries overlaid on timeline
- Overdue and overcommit visual indicators
- Heatmap density overlay (busy vs free periods)

### Phase E: Bottleneck Detection
- Identify tasks where actual work consistently exceeds estimates
- Flag tasks with work concentrated in deadline crunch (all sessions near due date)
- Show idle periods where no work happened on active tasks
- Suggest task breakdown when estimates exceed reasonable thresholds

### Phase F: Trends and Reporting
- Moving average of sessions per day/week
- Estimate accuracy tracking (actual/estimated ratio over time)
- Focus time distribution by tag/list/priority
- Exportable reports (PDF, CSV)

---

## Data Sources Available

| Source | What It Provides | Currently Used in Timeline |
|--------|-----------------|---------------------------|
| `TodoItem.created_at` | Task creation timestamp | Yes — blue bar start |
| `TodoItem.due_date` | Deadline | Yes — blue bar end |
| `TodoItem.due_time` | Specific time deadline | No |
| `TodoItem.estimated_pomodoros` | User's effort estimate | Yes — amber bar |
| `TodoItem.pomodoro_count` | Completed sessions | Yes — green bar fallback |
| `TodoItem.time_spent` | Actual seconds worked | Yes — green bar primary |
| `FocusSession.start_time` | When each session started | No — needed for Gantt |
| `FocusSession.end_time` | When each session ended | No — needed for Gantt |
| `FocusSession.duration_seconds` | Session length | No |
| `FocusSession.completed` | Was session finished | No |
| `config.pomodoro.work_duration` | Session length setting | Yes — conversion factor |
