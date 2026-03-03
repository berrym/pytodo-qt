# Feature Ideas for 0.3.x

Ideas borrowed from the broader productivity app landscape (Super Productivity, Todoist, TickTick, etc.) adapted to pytodo-qt's identity as a local-first, P2P-syncing, native Qt app.

These are candidates for the remaining 0.3.x releases. Each is low-to-moderate effort and pairs well with what already exists.

---

## Pomodoro / Focus Timer

A lightweight timer that pairs with the active todo item.

- Start a focus session from the currently selected item
- Configurable work/break intervals (default 25/5 min)
- Visual countdown in the status bar or a small floating widget
- Auto-log time spent on the item when session completes
- Optional break reminders
- Keyboard shortcut to start/stop

**Fits because:** pytodo-qt already has a status bar with dynamic content and per-item state tracking. A timer is a natural extension of "working on this item."

---

## Recurring / Repeating Tasks

Tasks that regenerate on a schedule after completion.

- Recurrence rules: daily, weekly, monthly, custom interval
- On completion, a new instance is created with the next due date
- Recurrence metadata stored per-item (syncs via existing P2P mechanism)
- UI: recurrence picker in the item editor, icon indicator on recurring items

**Fits because:** due dates already exist (added in 0.3.10). Recurrence is the natural next step and one of the most-requested features in any todo app.

---

## Tags

Lightweight cross-list categorization.

- Free-form text tags on items (e.g., `@errands`, `@work`, `@quick`)
- Filter/search by tag across all lists
- Tag completion/suggestions from previously used tags
- Colored tag chips in the item view
- Tags sync alongside item data

**Fits because:** search/filter already exists (added in 0.3.10). Tags add a cross-cutting organizational dimension without the overhead of nested projects or folders.

---

## Keyboard Shortcuts

Expand keyboard-driven workflow beyond undo/redo.

- Quick-add item without mouse (global hotkey or shortcut)
- Navigate between items with arrow keys
- Toggle completion, edit, delete from keyboard
- Switch lists via keyboard
- Shortcut cheat sheet (help overlay or dialog)
- Configurable bindings

**Fits because:** the app already has several shortcuts (Ctrl+Z/Y, Ctrl+Shift+P, etc.). A comprehensive keyboard layer makes the native Qt app feel fast and intentional — something Electron apps struggle with.

---

## CalDAV Import/Export

Interop with calendar and todo ecosystems without cloud dependency.

- Export lists as `.ics` (iCalendar VTODO format)
- Import `.ics` files into a list
- Optional CalDAV server mode for two-way sync with calendar apps
- Enables integration with Thunderbird, Apple Reminders, GNOME Calendar, etc.

**Fits because:** this preserves the no-cloud philosophy while enabling interop. Users can move data in and out without vendor lock-in — strengthening the local-first value proposition.

---

## Priorities

A rough ordering based on user value vs. implementation effort:

| Feature | Effort | Impact | Notes |
|---------|--------|--------|-------|
| Recurring tasks | Low-moderate | High | Builds directly on existing due dates |
| Keyboard shortcuts | Low | Moderate | Incremental, can ship piece by piece |
| Pomodoro timer | Moderate | Moderate | Standalone feature, no schema changes |
| Tags | Moderate | Moderate | Schema migration needed, but straightforward |
| CalDAV import/export | Moderate-high | Moderate | Export is easy, full CalDAV server is bigger |

These can be mixed into upcoming releases alongside the web UI work planned for 0.3.11, or grouped into their own point releases.
