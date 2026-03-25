# Feature Roadmap for 0.3.x

Status of features for the 0.3.x release series. Current schema: **v15**. Test count: **2326+**.

---

## Shipped

| Feature | Version | Notes |
|---------|---------|-------|
| Recurring tasks | v0.3.10 | Advance-in-place model, auto-advance, minutely recurrence, missed tracking |
| Tags | v0.3.10 | Free-form tags, colored chips, autocomplete, filter/search |
| Due dates & times | v0.3.10-11 | Date picker, optional time, granular overdue display |
| Multi-tier sort | v0.3.11 | 3 configurable sort dimensions with reverse toggles, desktop + web parity |
| Pomodoro / Focus timer | v0.3.11 | State machine, floating window, status bar, per-task tracking, session logging, daily goals |
| Keyboard shortcuts | v0.3.11 | Comprehensive keyboard layer, row selection, navigation |
| P2P sync | v0.3.8+ | Zeroconf discovery, LWW merge, device trust, auto-sync scheduler, offline queue |
| Subtasks | v0.3.11 | One-level parent/child nesting, progress badges, cascade delete, recurrence independence |
| Kanban board | v0.3.11 | Board view toggle, drag-and-drop, WIP limits, layout presets, column management, 155+ tests |
| NLP smart input | v0.3.11 | Regex parser (dates, times, priority, tags, recurrence, pomodoro), SmartInputWidget with highlighting + chips |
| Web UI + PWA | v0.3.11 | 30 REST endpoints, vanilla JS SPA, offline queue, WebSocket push, IndexedDB cache |
| Web security | v0.3.11 | Per-device token auth, PIN pairing, TLS always-on with local CA, HSTS, CSP, rate limiting |
| Mobile Access Wizard | v0.3.11 | 5-page stateful wizard, device tracking, Quick/Trusted connect, cert reconfiguration |
| Font bundling | v0.3.11 | Noto Sans + Noto Sans Mono + Noto Color Emoji (Qt 6.9+), font selector in settings |

---

## Remaining for v0.3.11

| Feature | Priority | Notes |
|---------|----------|-------|
| Web undo/redo | **Critical** | At minimum undo accidental delete — items gone with no recovery is unshippable |
| Web sort parity | High | Web sometimes shows different order than desktop |
| CalDAV interop | Designed | [caldav-interop.md](caldav-interop.md) — export/import `.ics`, deferred to post-release or 0.4.x |
| NLP enhancements | Medium | "at 8am and 12pm", "first Monday of month", "every other week" |
| Packaging upgrades | High | AppImage (Linux), DMG (macOS), NSIS installer (Windows) |

---

## Future (0.4.x+)

| Feature | Notes |
|---------|-------|
| PySide6 port | LGPL licensing, server mode, enhanced web UI |
| Pomodoro Phases D-F | Analytics, gamification, sound/focus mode |
| CalDAV server mode | Full two-way sync with calendar apps |
| Task grouping | Visual grouping without parent/child — may be addressed by tags + kanban |
| Tablet split-view | Two-column layout for web UI on tablets |
| Native mobile | Evaluate after web UI matures |
