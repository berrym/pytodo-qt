# Feature Roadmap for 0.3.x

Status of features planned for the 0.3.x release series. Each feature has a dedicated design document where applicable.

---

## Shipped

| Feature | Version | Notes |
|---------|---------|-------|
| Recurring tasks | v0.3.10 | Advance-in-place model, 5 recurrence fields, exhaustion guard |
| Tags | v0.3.10 | Free-form tags, colored chips, autocomplete, filter/search |
| Due dates & times | v0.3.10-11 | Date picker, optional time, overdue display, configurable format |
| Multi-tier sort | v0.3.11 | 3 configurable sort dimensions with reverse toggles |
| Pomodoro / Focus timer | v0.3.11 | State machine, floating window, status bar, toolbar, context menu, system notifications, configurable durations, `time_spent` tracking |
| Keyboard shortcuts | v0.3.11 | Comprehensive keyboard layer, row selection, navigation |
| P2P sync | v0.3.8+ | Zeroconf discovery, LWW merge, device trust, auto-sync scheduler |
| CalDAV interop | Designed | [caldav-interop.md](caldav-interop.md) — export/import `.ics`, optional CalDAV server |

---

## Committed (next to implement)

### Subtasks

One level of parent/child nesting. `parent_id: UUID | None` on TodoItem. Indented display with expand/collapse, progress badges, drag-and-drop reparenting. This is the most-requested missing feature and the foundation for task breakdown suggestions, kanban card detail, and pomodoro estimation workflows.

**Design document:** [subtasks-design.md](subtasks-design.md)
**Schema:** v11 migration (combined with kanban fields)

### Pomodoro Evolution (Phase A: Foundation Fixes)

Complete the unfinished items from the original design: undo-able time tracking (`EditTimeSpentCommand`), time spent tooltips, graceful stop on item deletion, visible time display in table rows.

**Design document:** [pomodoro-evolution.md](pomodoro-evolution.md) — Phase A

---

## Planned (designed, implementation order TBD)

### Kanban Board View

Toggle between list and board views per list. `board_column` field on TodoItem, per-list column configuration, drag-and-drop between columns, WIP limits, keyboard navigation. Complements the list view for workflow-oriented tasks.

**Design document:** [kanban-design.md](kanban-design.md)
**Schema:** v11 migration (combined with subtasks)

### Natural Language Task Input

Smart text input that parses dates, times, priority, tags, recurrence, and pomodoro estimates from free-form English. Zero external dependencies — regex-based, fully offline. Replaces the multi-field dialog with a single smart input line.

**Design document:** [natural-language-input.md](natural-language-input.md)

### Pomodoro Evolution (Phases B-F)

- **Phase B:** Per-task pomodoro count and estimation (`pomodoro_count`, `estimated_pomodoros`)
- **Phase C:** Session logging with synced `focus_sessions` table (append-only merge)
- **Phase D:** Productivity analytics — daily goals, stats dialog, streak tracking
- **Phase E:** Gamification — progress indicators, milestone celebrations, focus score
- **Phase F:** Sound notifications via `QSoundEffect`, optional focus mode

**Design document:** [pomodoro-evolution.md](pomodoro-evolution.md)

---

## Under Consideration

| Idea | Notes |
|------|-------|
| Font bundling | Ship a licensed emoji font (e.g., Noto Color Emoji) for cross-platform consistency; font selector in settings |
| Task grouping | Visual grouping of related items without parent/child hierarchy — may be addressed by tags + kanban columns |
| CalDAV server mode | Full two-way sync with calendar apps — designed but lower priority than core features |
| Web UI | Flask/htmx interface for mobile access — [web-ui-architecture.md](web-ui-architecture.md), [pwa-mobile-strategy.md](pwa-mobile-strategy.md) |

---

## Implementation Sequencing

```
Subtasks ─────────────────┐
                          ├──> Kanban (needs subtask display)
Pomodoro Phase A ─────────┤
                          ├──> Pomodoro Phases B-F
NLP Parser (independent) ─┘
                          └──> NLP Dialog Integration
```

**Schema v11** combines: `parent_id` (subtasks) + `board_column` (kanban) + `board_columns` on lists + `pomodoro_count` / `estimated_pomodoros` (pomodoro Phase B).

Subtasks and Pomodoro Phase A can proceed in parallel. NLP parser (core module, no Qt) is fully independent. Kanban should follow subtasks. Pomodoro Phases B-F interleave as bandwidth allows.
