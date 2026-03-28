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
| ~~Web undo/redo~~ | ~~Critical~~ | **Done** (c583d3f + 0cdabda) — unified QUndoStack + offline undo |
| ~~.local hostname~~ | ~~Critical~~ | **Done** (0e47342) — IP-resilient mobile access |
| NLP enhancements | **Blocker** | Voice dictation patterns, compound times, "first Monday of month", "every other week" |
| CalDAV interop | **Blocker** | [caldav-interop.md](caldav-interop.md) — full .ics export/import, testers need this |
| Subtask collapsible toggle | High | Web UI parity with desktop |
| Device name editing | High | Let users rename devices in wizard |
| Auto-cleanup stale devices | High | Remove devices not seen in 30+ days |
| Web sort parity | High | May already be fixed — needs verification |
| Packaging upgrades | High | AppImage (Linux), DMG (macOS), NSIS installer (Windows) |

---

## In Scope for 0.3.x (not necessarily 0.3.11)

All items below are in scope for the 0.3.x series. 0.4.0 changes the fundamental nature of the program (headless server, PySide6).

| Feature | Notes |
|---------|-------|
| Pomodoro Phases D-F | Analytics, gamification, sound/focus mode |
| Web pomodoro control | Start/stop focus timer from phone |
| Batch operations in web | Multi-select for bulk toggle/delete/move |
| Tablet split-view | Two-column layout for web UI |
| Smart add quick actions | Priority/date/tag/recurrence pickers below NLP input |
| Web dark/light theme toggle | Manual toggle (currently auto only) |
| CalDAV server mode | Full two-way sync with calendar apps |
| Background sync API | Browser Background Sync where supported |

---

## 0.4.x Vision

- PySide6 port (LGPL licensing)
- Headless server mode (Docker, multi-user)
- Possible rebrand / new project identity
- Native mobile exploration
