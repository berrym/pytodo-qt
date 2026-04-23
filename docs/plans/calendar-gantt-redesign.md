# Calendar Day/Week View — Gantt-Bar Rendering Redesign

**Status:** Specification locked, pre-implementation. No code written against this design yet.
**Scope:** Day and Week sub-views of `gui/widgets/calendar_view.py`. Month view, Timeline analytics view, and the unscheduled sidebar are out of scope for this redesign.
**Supersedes:** The previous `_NowOverlay` widget approach and the subsequent delegate-based "now span" painting in `_WeekDelegate._paint_now_overlays()`. Both are to be removed/replaced.

---

## Why This Redesign

The previous approaches tried to communicate "now-awareness" by painting translucent colored spans across whole hour cells regardless of whether tasks occupied them. The result was visually dishonest: cells with zero tasks were colored as if they contained work, and cells with tasks gave no indication of how those tasks related to the current moment in time.

The fundamental error was treating "now" as a property of the **calendar grid** rather than as a property of each **task**. A task has a lifecycle (planned → in-progress → due → overdue → complete). The calendar's job is to render that lifecycle honestly against the time axis. The grid is just the coordinate system.

This redesign replaces the cell-overlay model with a **Gantt-bar model**: each task gets a single bar anchored at its computed origin, extending to its computed end, with visual states that reflect where "now" falls within that bar's timeline. Empty cells stay empty.

---

## Foundational Decisions (Locked)

The seven questions below define the rendering model. Q1 and Q2 are **load-bearing** — they define what a bar *means*. Q3–Q7 are **refinable** — visual treatment can iterate, but the underlying rules cannot change without re-specifying Q1/Q2.

### Q1: Origin Definition (LOCKED, load-bearing)

Each task in the day/week grid has exactly one origin, determined by which fields are set on the `TodoItem`. The four rules are exhaustive and mutually exclusive:

| Case | Fields Set | Origin | End | Rendered Where |
|------|------------|--------|-----|----------------|
| **Event** | `due_time` AND `due_time_end` | `due_time` | `due_time_end` | Hour grid |
| **Deadline with estimate** | `due_time` AND `estimated_minutes` | `due_time − estimated_minutes` | `due_time` | Hour grid |
| **Deadline only** | `due_time` (no `estimated_minutes`, no `due_time_end`) | `created_at` | `due_time` | Hour grid |
| **No due_time** | `due_date` only or no temporal anchor | n/a | n/a | All Day row (or unscheduled sidebar) |

**Sanitization:** If any rule produces an end before its origin (negative duration), the task is treated as if the end fields were unset and falls through to the next applicable rule. Sanitization happens at the rendering layer, not by mutating the model.

**Future origins:** Arbitrary future start times are fully supported via the existing fields. A task created today with `due_time` set to next Tuesday 2 PM and `estimated_minutes=60` has origin = next Tuesday 1 PM. This is not deferred; it works because the rules are field-driven, not "now"-relative.

### Q2: estimated_minutes Semantics (LOCKED, load-bearing)

When a task has both `due_time` and `estimated_minutes`, the estimate means **work-back from the deadline**:

- Origin = `due_time − estimated_minutes`
- End = `due_time`
- The bar represents the planned work window leading up to the deadline.

`estimated_minutes` is the **core calculation unit**. Display layers MUST convert to natural units (hours, days, weeks) when presenting durations to humans. "360 minutes" is not acceptable user-facing copy; "6h" or "6 hours" is.

Use the existing `format_duration()` utility in `core/models.py` for all human-facing duration display.

### Q3: Cross-Day Origin (LOCKED, refinable visuals)

A bar's computed origin or end may fall outside the visible day(s). The bar always represents the truth; what changes as the user navigates is which **slice** of that truth is visible.

**Rule:** Clip the bar at the day boundary and paint a clear edge marker indicating "this continues beyond the visible range." The marker style (arrow, gradient fade, angled cut) is iterable; the *meaning* — "more truth exists outside this view" — is locked.

**Tooltip / click contract:** The full timeline is always available without navigation. Hover or click reveals origin, end, and any deviation history. Nothing is ever hidden.

**Past navigation:** When the user navigates to a previous day, the same bar is drawn with the appropriate slice clipped. The visual state may shift to reflect the historical context (a bar that's now overdue may have appeared "in work window" when viewed against its origin day), but the bar's identity and full truth remain consistent. Implementation may iterate on whether past-view rendering uses a different visual treatment, but it must never invent or hide information.

**Long-running deadline-only tasks:** A task created weeks ago with a future deadline (Interpretation X from spec discussion) renders its full honest span. On any middle day it appears as a full-column bar clipped at both ends. This may produce visual noise for very old tasks; that is accepted as the honest starting point and may be tuned later (e.g., a "compact mode" toggle), but the default is full-span honesty.

### Q4: Bar Text Placement (LOCKED, refinable visuals)

- **Anchor:** Reminder text anchored to the **top** of the visible bar segment. If the bar is clipped at the top of the viewport, the text sits at the top edge.
- **Truncation:** Ellipsis truncation when the bar is too narrow or short to display the full reminder.
- **Tooltip:** Always carries the full untruncated reminder, plus origin/end/state details.

This matches standard Gantt-chart conventions and gives a consistent read position regardless of bar height or scroll state.

### Q5: Color Palette and State Visuals (LOCKED, refinable hex values)

A bar's lifecycle is communicated through a uniform base color per state, with optional secondary visual zones for completion deviation.

**Lifecycle states:**

| State | Condition | Base Color (semantic) |
|-------|-----------|----------------------|
| **Future** | now < origin | Soft blue, muted |
| **Work window** | origin ≤ now < due_time | Teal/cyan, full opacity |
| **Due now** | within ~15 min of due_time | Amber/yellow, possibly subtle pulse or border emphasis |
| **Overdue (active)** | now > due_time AND not done | Red, growing past due_time (see Q6 for cap behavior) |
| **Completed** | done = True | Green |

**Two-zone bars for completed tasks:** A completed task's bar tells the full story of how it was finished relative to plan, using up to two visual zones distinguished by translucency, gradient, or texture (not by completely different colors):

- **Completed early** — Solid completion color from origin to actual completion point; the remaining planned span (completion → original due_time) rendered with reduced opacity/translucency. Conveys "this time was allocated but not needed."
- **Completed on time** — Single solid completion-color span from origin to due_time. No secondary zone.
- **Completed late** — Solid completion color across the original planned span (origin → due_time); the overdue extension (due_time → actual completion) rendered with a distinct texture/gradient/hatching. Conveys "this is how far past due it went before completion."

**Active overdue → late completion transition:** When an active overdue task is finally completed, its overdue red zone transitions to the "completed but late" texture/gradient. The historical overdue extent is preserved in the visual.

**WCAG AA is a hard floor.** All base colors must meet WCAG AA contrast requirements against both light and dark themes. Textures, translucency, and gradients are *additions* on top of compliant colors, never substitutes for them. Two palettes (light theme, dark theme) are required.

Exact hex values are deferred to implementation and will be picked from / harmonized with the existing app theme. They are iterable without re-specifying Q5.

### Q6: Overdue Growth Cap (LOCKED, refinable visuals)

An active overdue task could in principle extend its bar indefinitely. To avoid a single forgotten task painting every visible day red:

- **Through the due day:** The bar grows in real time past `due_time` in the overdue color. This portion is honest hour-by-hour representation — the task is occupying the timeline as it slips.
- **On subsequent days:** The bar is rendered as a **fixed top-of-grid marker** with a duration label (e.g., "3d overdue", "~2w overdue"). The marker sits in a dedicated overdue strip at the top of the day's hour grid (or at the top of the All Day row), not as a full-column hour-grid bar.
- **Tooltip / click:** Always reveals the full honest timeline — original due time, current overdue duration, and projected impact.

This is honest because:
1. The task's existence and overdue state are immediately visible every day it remains unresolved.
2. The duration label quantifies the slippage at a glance.
3. The full timeline is one tooltip away.

What it avoids is the *false implication* that an overdue task is occupying specific hours of subsequent days. After day one, "overdue" means "unresolved obligation," not "actively being worked at 9 AM."

### Q7: Recurring Task Cycle Reset (LOCKED)

Each recurrence cycle is an **independent bar** with its own origin computed via Q1's rules.

- When a recurring task's current instance completes, the next instance begins with a fresh origin (its own `due_time`, its own `estimated_minutes`, its own `created_at` if applicable).
- The completed instance freezes with its Q5 visual treatment (early/on-time/late) and remains visible in its historical position when navigating to past days.
- There is no carryover from the previous incarnation's origin or duration.

This matches the semantic intent of recurrence: "this resets." Carrying the original `created_at` forward would create an ever-growing bar that defeats the purpose.

---

## Rendering Implementation Notes (Non-Binding Sketch)

These are starting-point implementation notes, not part of the locked specification. They will be refined in formal planning mode.

### Pinned All Day Row

The All Day row sits above the scrollable hour grid as a **frozen row** (does not scroll with the hour grid). It contains:
- Tasks with no `due_time` but a `due_date` matching the visible day(s)
- Q6 overdue markers (subsequent-day mode)
- Optional: Q3 long-running deadline-only tasks if a "compact mode" toggle is added later

Implementation: likely a separate small QTableView pinned above the main hour QTableView, or a fixed-height row painted by a custom widget composing both views.

### Bar Painting

Bars are painted by the `_WeekDelegate` (and a corresponding `_DayDelegate` if day view diverges). The delegate computes, for each cell, which bars intersect it and paints only the intersecting slice. This is the standard approach for delegate-painted Gantt grids and avoids any overlay-widget pitfalls.

The paint sequence per cell:
1. Background (today highlight, weekend tint, etc.)
2. Bar slices that intersect this cell, in stable Z-order
3. Now line, if the current time falls within this cell
4. Selection / hover highlights

### Hover and Click

- **Hover** on any bar slice shows a tooltip with reminder, origin, end, state, and deviation info. Use `QToolTip.showText()` directly (per the chart export pattern) for immediate display, bypassing Qt's hover delay.
- **Click** on a bar slice selects the task. Double-click opens the editor (existing behavior).
- **Context menu** on a bar slice exposes the same actions as the list view's context menu.

### Now Tick

A 30-second `QTimer` triggers a viewport update so bars in the "due now" or "overdue (active)" state advance smoothly. The same timer drives the now line painted in the cell containing the current time.

### Test Surface

Replace the existing `TestWeekDelegateNowOverlays` and any leftover `TestNowOverlay` tests. New test classes will cover:
- Origin computation (each Q1 rule, including sanitization)
- Q2 work-back math
- Q3 clipping at day boundaries (top, bottom, both)
- Q4 text anchoring and ellipsis
- Q5 state transitions and two-zone completed bars
- Q6 marker mode for subsequent-day overdue
- Q7 recurring cycle independence
- Interaction: hover tooltip content, click selection, context menu

Tests should drive on the **rendering model** (an extracted function that takes a list of items and a date range and returns drawable bar segments), not on pixel comparisons. Pixel-level visuals are iterable and should not be locked into tests.

---

## Rejected Alternatives

Recording these so future sessions don't re-litigate them.

1. **Cell-overlay coloring** (the previous `_NowOverlay` and `_paint_now_overlays()` approaches) — visually dishonest, paints empty cells, makes the grid say things about cells rather than about tasks. **Rejected.**

2. **Single now-line only** — pragmatic but uninspiring; communicates nothing about each task's state relative to now. **Rejected** as insufficient.

3. **Collapsing long deadline-only spans into a deadline marker** (Interpretation Y for Q3) — less noisy but loses honest span representation. **Rejected** in favor of Interpretation X (full span). May be revisited as an opt-in compact mode after testing.

4. **Carrying recurring task origins forward** — defeats the semantic of recurrence. **Rejected.**

5. **Mixed-state coloring within a single bar** (e.g., shading "elapsed" portion vs "remaining" portion of an active work-window bar) — considered for Q5 but rejected in favor of uniform per-state base color for clarity. May be revisited if testing shows it would help.

---

## What Is NOT Locked

These are explicit refinement points and require implementation contact + testing feedback to resolve:

- Exact hex values for the Q5 palettes (light + dark)
- The visual style of the Q3 clipping edge marker (arrow vs gradient vs angled cut)
- The exact threshold for "due now" pulse (15 min is a starting guess)
- Whether the Q6 overdue strip is a separate visual element or merges into the All Day row
- The exact format string for `format_duration()` in the Q6 marker label
- Whether long-running deadline-only tasks (Q3) should get a future opt-in "compact mode" toggle
- Pixel-level layout of bar text, padding, corner radius, etc.

These are acceptable to iterate on without re-specifying the locked decisions above. Anything that would require changing Q1 or Q2 must come back for a new specification round.

---

## Reference

- Specification locked: 2026-04-10
- Related: `docs/plans/calendar-view-design.md` (original calendar view plan, now superseded for day/week sub-views)
- Related: `core/models.py:format_duration()` (natural duration display utility)
- Related: `core/models.py:TodoItem` (the source-of-truth for `due_time`, `due_time_end`, `estimated_minutes`, `due_date`, `created_at`, `done`, recurrence fields)
