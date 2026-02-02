# pytodo-qt 0.3.x Roadmap

This document outlines the remaining 0.3.x releases, focusing on foundational improvements that deliver immediate value while preparing for future evolution.

## Overview

| Release | Focus | Status |
|---------|-------|--------|
| 0.3.7 | Platform-specific release binaries | Complete |
| 0.3.8 | SQLite migration | **Implementation Complete** |
| 0.3.9 | Private lists | Planned |
| 0.3.10 | Users & access control | Planned |

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

**Goal:** Allow users to mark lists as private, excluding them from sync.

### Why Private Lists

- Keep personal/sensitive lists on one device only
- Work tasks that shouldn't sync to home machines
- Temporary lists that don't need to clutter other devices
- User control over what data leaves their machine

### Scope

- Visibility flag per list: `shared` (default) or `private`
- Private lists excluded from sync operations
- UI toggle in list settings
- Sync protocol respects visibility (private lists never transmitted)

### User Experience

- New lists default to shared (current behavior)
- Right-click or list settings → "Make Private" / "Make Shared"
- Visual indicator for private lists (icon or label)
- Clear feedback when toggling visibility

### Success Criteria

- Private lists never appear in sync data
- Visibility toggle works in UI
- Existing lists remain shared (no surprise behavior changes)

---

## 0.3.10: Users & Access Control

**Goal:** Introduce user model and permission system, preparing for multi-user scenarios while working seamlessly in single-user mode.

### Why Now

- Foundation for server mode (0.4.x)
- Enables list sharing with permissions
- Data model ready for collaboration features
- Works transparently for single-user (no added complexity for simple use)

### Scope

#### User Model
- Users table in database
- Default "local" user created automatically
- User has identity keypair (existing Ed25519 keys)
- Single-user mode: everything owned by local user

#### List Ownership
- Every list has an owner (user)
- Owner has full control (rename, delete, manage permissions)

#### Permission Levels
- **Owner**: Full control, can delete list, manage permissions
- **Editor**: Add/edit/delete items, cannot delete list
- **Viewer**: Read-only access

#### Groups (Optional)
- Group users for easier permission management
- "Family" group, "Work" group, etc.
- Assign permissions to groups, not just individuals
- *May defer to 0.4.x if scope is too large*

### Single-User Experience

For users who just want a todo app:
- Everything works exactly as before
- Local user owns all lists
- No login, no accounts, no complexity
- Permission system is invisible unless sharing

### Success Criteria

- Single-user workflow unchanged
- Database schema supports multi-user
- Permissions enforced in data layer
- UI shows ownership/permissions for lists
- Migration from 0.3.9 assigns all lists to local user

---

## Migration Path

Each release migrates data from the previous:

```
0.3.7 (JSON)
    ↓ automatic migration
0.3.8 (SQLite, same schema as JSON conceptually)
    ↓ schema migration
0.3.9 (SQLite + visibility column)
    ↓ schema migration
0.3.10 (SQLite + users, ownership, permissions)
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

These releases are grounded in the [Strategic Roadmap](./vision/strategic-roadmap.md) but don't commit to it. After 0.3.10, pytodo-qt will have:

- A proper database (SQLite)
- Privacy controls (private lists)
- User/permission model

This foundation supports multiple futures:
- Continue as enhanced desktop app
- Add server mode (0.4.x vision)
- Fork into new project
- Something else entirely

The work is valuable regardless of which path follows.
