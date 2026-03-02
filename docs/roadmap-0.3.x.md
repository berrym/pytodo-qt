# pytodo-qt 0.3.x Roadmap

This document outlines the remaining 0.3.x releases, focusing on foundational improvements that deliver immediate value while preparing for future evolution.

## Overview

| Release | Focus | Status |
|---------|-------|--------|
| 0.3.7 | Platform-specific release binaries | Complete |
| 0.3.8 | SQLite migration | Complete |
| 0.3.9 | Private lists | **Complete** |
| 0.3.10 | Sync groups & UX | **Complete** |
| 0.3.11 | Mobile access (Web UI) | Planned |

Each release is backward compatible and delivers standalone value.

---

## 0.3.8: SQLite Migration

**Status:** Implementation complete. Ready for release.

**Goal:** Replace JSON file storage with SQLite for better data integrity, query support, and multi-user foundation.

### Why SQLite

- **ACID transactions**: No more corrupted data from interrupted writes
- **Concurrent access**: Multiple processes can safely read/write
- **Query support**: Filtering, searching, sorting at database level
- **Schema enforcement**: Data integrity built-in
- **Still file-based**: No separate database server required

### What Was Implemented

- `DatabaseStorage` class with full CRUD operations
- SQLite schema with metadata, lists, and items tables
- WAL mode enabled for better concurrency
- Automatic migration from JSON on first run
- Timestamped backup of JSON before migration
- Migration verification (count comparison)
- 70 new tests (31 database, 28 migration, 11 integration)

### Migration Behavior

On first launch after upgrade:
1. Detects existing JSON database
2. Creates timestamped backup (`pytodo-qt-db.json.backup_YYYYMMDD_HHMMSS`)
3. Migrates all data to SQLite (`pytodo-qt.db`)
4. Verifies migration succeeded
5. Continues with SQLite storage

Users see no difference in functionality. JSON file is preserved for safety.

### Files Changed

See [0.3.8 SQLite Migration Plan](./plans/0.3.8-sqlite-migration.md) for details.

### Success Criteria - All Met

- [x] All existing tests pass with SQLite backend
- [x] Clean migration from JSON for existing users
- [x] No user-visible behavior changes
- [x] Performance equivalent or better than JSON
- [x] 311 tests passing

---

## 0.3.9: Private Lists

**Status:** Implementation complete. Released.

**Goal:** Allow users to mark lists as private, excluding them from sync.

### Why Private Lists

- Keep personal/sensitive lists on one device only
- Work tasks that shouldn't sync to home machines
- Temporary lists that don't need to clutter other devices
- User control over what data leaves their machine

### What Was Implemented

- `private` field added to TodoList model (default: `False`)
- `toggle_private()` method to toggle status with timestamp update
- `to_dict_for_sync()` on Database class filters out private lists
- Schema migration v3→v4 adds `private` column to SQLite
- Lock icon (`lock.svg`) displays for private lists in selector
- Context menu on list selector: "Make Private" / "Make Shared"
- Menu action: List → Toggle Private (Ctrl+Shift+P)
- Status bar feedback when toggling private status
- 14 new tests covering model, sync filtering, SQLite, and migration

### User Experience

- New lists default to shared (unchanged behavior)
- Right-click list selector → "Make Private" / "Make Shared"
- Lock icon appears next to private list names
- Keyboard shortcut: Ctrl+Shift+P
- Status bar shows confirmation message

### Success Criteria - All Met

- [x] Private lists never appear in sync data
- [x] Visibility toggle works in UI (context menu + keyboard)
- [x] Existing lists remain shared (no surprise behavior changes)
- [x] Visual indicator (lock icon) for private lists
- [x] 325 tests passing

See [0.3.9 Private Lists Plan](./plans/0.3.9-private-lists.md) for details.

---

## 0.3.10: Sync Groups & UX

**Status:** Implementation complete. Ready for release.

**Goal:** Mature the sync system with device management, sync groups, and major UX improvements including undo/redo, due dates, search, and auto-sync.

### What Was Implemented

This was the largest release in the 0.3.x series, delivering sync maturity and desktop UX polish across 30 commits.

#### Sync & Device Management
- **Device management** — auto-track devices by fingerprint, user-friendly naming, trust levels (normal/trusted/blocked)
- **Sync groups** — organize devices into groups (e.g., "Work", "Home"), assign lists to groups
- **List sync rules** — control which lists sync to which groups, per-list settings dialog
- **Concurrency protection** — server-side sync lock, client-side SyncQueue with busy retry
- **Offline queue** — queue syncs for offline devices, auto-execute when discovered online (7-day expiry)
- **Auto-sync on discovery** — trusted devices trigger automatic bidirectional sync when they come online
- **Auto-sync scheduler** — debounced push after local changes + periodic full sync on configurable timers
- **Unseen change indicators** — two-level visual feedback: highlighted list selector border + per-item dot icons for lists with unviewed remote changes
- **List metadata sync** — name, deleted, and updated_at fields sync between peers via LWW
- **List name collision resolution** — auto-rename on conflict ("Shopping" → "Shopping (from Mac)")
- **Active list switching** — automatically switches away from a list when sync marks it deleted

#### Desktop UX
- **Undo/redo system** — full QUndoStack with 10 command classes covering all mutation types
- **Due dates** — date picker, overdue highlighting, 7-day relative display, filtering
- **Search/filter bar** — real-time filtering of todo items
- **List creation dialog** — create lists with optional private flag in one step
- **WCAG AA themes** — contrast-compliant light and dark themes with system-following

#### Robustness
- **Discovery hardening** — Docker bridge filtering, TTL churn suppression, health check with auto-restart, 30s grace period for peer removal
- **Cross-platform fixes** — font handling, tray icon visibility on dark Linux panels, Linux text clipping in status bar

### Schema Changes

SQLite schema v4 → v5 adds tables: `devices`, `sync_groups`, `device_groups`, `list_sync_rules`, `pending_syncs`.

### Success Criteria - All Met

- [x] Devices automatically tracked on first sync
- [x] Sync groups organize devices logically
- [x] List sync rules control which lists go where
- [x] Concurrent syncs handled safely (no race conditions)
- [x] Bulk sync works reliably with progress feedback
- [x] Offline queue persists syncs for later execution
- [x] Auto-sync triggers for trusted devices (configurable)
- [x] Undo/redo for all mutation types
- [x] Due dates with filtering and overdue highlighting
- [x] Search/filter for todo items
- [x] Migration preserves all existing functionality
- [x] 606 tests passing
- [x] No lint or type errors

See [0.3.10 Sync Groups Plan](./plans/0.3.10-sync-groups.md) for the original detailed plan.

---

## 0.3.11: Mobile Access (Web UI)

**Status:** Planned.

**Goal:** Enable mobile access to pytodo-qt data via an embedded web server with a mobile-friendly interface.

### Why

- Users can sync between desktop/laptop devices but not phones or tablets
- Mobile is where people often need quick todo access (on the go, in stores, commuting)
- Web UI avoids app store distribution and works on any phone with a browser

### Scope

#### Phase 1: Embedded Web Server
- FastAPI or Flask web server as optional mode
- Simple, mobile-optimized HTML interface
- Basic CRUD: view lists, view items, toggle complete, add item
- Menu option or command-line flag to enable
- Works on home wifi (same network)

#### Phase 2: PWA Enhancement (Optional)
- Service worker for offline caching
- "Add to Home Screen" on phones
- Background sync when connection restored

### Non-Goals

- Full feature parity with desktop (mobile should be focused/simplified)
- App store distribution
- Native mobile apps (evaluate after web UI proves out)

See [Mobile Access Plan](./plans/mobile-access.md) for detailed evaluation of options.

---

## Migration Path

Each release migrates data from the previous:

```
0.3.7 (JSON)
    ↓ automatic migration
0.3.8 (SQLite schema v3)
    ↓ automatic schema migration
0.3.9 (SQLite schema v4 + private column)
    ↓ automatic schema migration
0.3.10 (SQLite schema v5 + devices, sync groups, rules, offline queue)
```

Users upgrading from any 0.3.x version get automatic migration. Original data is backed up before migration.

---

## Timeline

No fixed dates. Each release ships when ready:
- Feature complete
- Tests passing
- Documentation updated
- Migration tested

Quality over speed.

---

## Relationship to Vision

These releases are grounded in the [Strategic Roadmap](./vision/strategic-roadmap.md) but don't commit to it. After 0.3.10, pytodo-qt has:

- A proper database (SQLite with automatic migration)
- Privacy controls (private lists)
- Device management and sync groups
- Full undo/redo, due dates, search, and auto-sync
- Robust encrypted P2P sync with offline queuing

This foundation supports multiple futures:
- Continue as enhanced desktop app
- Add mobile access via web UI (0.3.11)
- Add server mode (0.4.x vision)
- Add user/permission model for collaboration
- Something else entirely

The work is valuable regardless of which path follows.
