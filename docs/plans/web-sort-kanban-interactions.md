# Web UI: Three-Tier Sorting + Kanban Interactions Plan

**Status:** Complete (2026-03-15)
**Scope:** 4 features, ~12 commits
**Depends on:** v0.3.11 web overhaul core (complete)

---

## Overview

Four tightly sequenced features that bring the web SPA to parity with the desktop app's sorting and kanban experience:

1. **Three-tier sorting** — match desktop's configurable sort system
2. **Long-press context menu** — foundational mobile interaction pattern
3. **Kanban column management** — presets, protection rules, header menus
4. **Kanban drag-and-drop** — pick-up-and-place card movement

---

## Feature 1: Three-Tier Sorting

### Problem
Desktop uses a 3-tier configurable sort (completion / due_date / priority, each with independent reverse toggle, unique dimensions enforced via auto-swap). Web has 5 hardcoded sort modes with no direction control, producing different item ordering than the desktop — breaking UX consistency.

### Design Decisions
- **Shared config by default**: Web reads/writes the same TOML sort config as the desktop. Changing sort on phone updates desktop on next refresh (and vice versa). A future option can allow per-client independent sort, but sync-by-default is the right starting point.
- **Same sort engine**: Port `_sort_fragment()` to JS with identical logic (completion: 0/1, due_date: 3-element tuple with no-date-last, priority: numeric, reverse via negation, reminder tie-breaker).

### API Changes
- `GET /api/status` — add `sort_tiers` field: `[{"dimension": "completion", "reverse": false}, ...]`
- `PUT /api/sort` — accept `{"tiers": [...]}`, validate (3 tiers, unique dimensions, valid names), write to `ConfigManager`

### Web UI Changes
- Replace 5-mode `sortItems()` with `sortByTiers(items, tiers)` using ported `_sort_fragment()`
- Fetch sort tiers from `/api/status` on load, cache in `currentSortTiers`
- Replace sort dropdown with sort configuration sheet:
  - 3 rows: Primary / Secondary / Tertiary
  - Each row: dimension picker (Completion, Due Date, Priority) + direction toggle (↑/↓)
  - Auto-swap enforcement: selecting a dimension used in another tier swaps the displaced dimension into the changed row (matches desktop `_on_sort_tier_changed()`)
  - Save button calls `PUT /api/sort` and re-renders items
- Sort button in header shows current primary dimension as label (e.g. "Sort: Due Date")

### Commits
1. **Add three-tier sort configuration to web API** — expose tiers in `/api/status`, add `PUT /api/sort` endpoint with validation, read/write via `ConfigManager`
2. **Port three-tier sort engine to web UI** — implement `sortFragment()` and `sortByTiers()` in JS matching desktop `_sort_fragment()`, replace hardcoded sort modes, fetch config on load
3. **Add sort configuration sheet to web UI** — 3-tier picker with dimension selectors, direction toggles, auto-swap logic, persist via API

---

## Feature 2: Long-Press Context Menu

### Problem
No way to quickly act on items without opening the full detail sheet. Standard mobile interaction pattern (long-press → action sheet) is missing.

### Design
- **Reusable component**: `showContextMenu(title, actions)` renders a bottom sheet with action rows, backdrop, focus trap, haptic feedback
- **Long-press detection**: pointer events with 500ms timer, cancel on move >10px or on scroll
- **Visual feedback**: slight scale reduction (0.97) on the pressed item during the hold period
- **Works on both list items and board cards** (same handler, different action sets)

### Actions Available
| Action | List View | Board View | API Call |
|--------|-----------|------------|----------|
| Edit (open detail) | ✅ | ✅ | Navigate to `#/item/{id}` |
| Toggle complete | ✅ | ✅ | `PATCH /api/items/{id}/toggle` |
| Set priority → sub-menu (High/Normal/Low) | ✅ | ✅ | `PUT /api/items/{id}` |
| Move to column → sub-menu (column list) | ✅ | ✅ | `PATCH /api/items/{id}/move` |
| Delete | ✅ | ✅ | `DELETE /api/items/{id}` + undo toast |

### Commits
4. **Add reusable context menu sheet component** — bottom sheet renderer with action rows, sub-menus, backdrop, focus trap, haptic, Escape-to-close, CSS animations
5. **Add long-press detection for list items and board cards** — pointer event handler (500ms hold, 10px move cancel, scroll cancel), visual hold feedback, wire to context menu
6. **Wire context menu actions with API calls** — edit, toggle, priority sub-menu, move-to-column sub-menu, delete with undo toast

---

## Feature 3: Kanban Column Management

### Problem
Web has zero column management UI despite full API support. No protection rules matching desktop. Users can't rename, delete, or configure WIP limits from the web.

### Protection Rules (match desktop exactly)
- **First column (Inbox)**: Cannot be deleted. No WIP limit option. Shows 📥 icon. New items land here.
- **Last column (Completion)**: Cannot be deleted. No WIP limit option. Shows ✅ icon. Items moved here auto-complete.
- **Minimum 3 columns**: Cannot delete below this threshold. Presets are the safe way to restructure.
- **Middle columns**: Full management — rename, set WIP limit, delete (with item displacement to first column).

### Layout Presets (match desktop)
| Preset | Columns |
|--------|---------|
| Simple | To Do, In Progress, Done |
| With Review | To Do, In Progress, Review, Done |
| With Testing | To Do, In Progress, Review, Testing, Done |
| Backlog | Backlog, To Do, In Progress, Done |

### API Changes
- `PATCH /api/lists/{id}/columns` — add validation: reject delete on first/last column, reject WIP on first/last, enforce min 3 columns, return error messages explaining why
- `GET /api/presets` — return the 4 preset layouts with names and column lists
- `POST /api/lists/{id}/apply-preset` — smart item remapping matching desktop `ApplyLayoutPresetCommand` logic:
  1. Exact column name match → keep
  2. Last column → new last column (completion mapping)
  3. Positional remapping for remaining items
  4. Unknown → first column (inbox)

### Web UI — Column Header Management
- Long-press on column header opens context menu (reuses Feature 2 component)
- **First column menu**: Rename only. Header shows 📥 icon.
- **Last column menu**: Rename only. Header shows ✅ icon.
- **Middle column menu**: Rename, Set WIP Limit, Delete
- **Rename**: Inline text input replacing column name, Enter to confirm, Escape to cancel (max 50 chars)
- **Set WIP Limit**: Number input sheet (0 = no limit, 1-99 range)
- **Delete**: Confirmation dialog showing "N items will be moved to [first column]"

### Web UI — Layout Preset Picker
- "Layout" button (⚙) in board view header bar
- Opens sheet with 4 preset cards showing column names as preview
- Current layout highlighted
- Tap to apply → API call → toast confirmation
- Warning if items will be remapped: "Items will be redistributed to match the new layout"

### Commits
7. **Add column protection rules and preset API endpoints** — validate first/last/min-3 in PATCH columns, add GET presets, add POST apply-preset with smart item remapping
8. **Add column header management via long-press** — context menu on headers with role-aware actions (inbox/completion/middle), inline rename, WIP limit sheet, delete confirmation
9. **Add layout preset picker to board view** — preset selection sheet with column previews, apply-preset API call, remapping warning, toast confirmation

---

## Feature 4: Kanban Drag-and-Drop (Pick-Up-and-Place)

### Problem
Moving cards between columns requires opening detail sheet → column dropdown. No tactile kanban experience. On phone, each column is a full screen — traditional drag-and-drop can't cross column boundaries.

### Design: Pick-Up-and-Place

The core insight: **decouple "holding a card" from "navigating between columns"**.

#### Flow
1. Each board card shows a **grip icon** (⠿) on the right side
2. **Tap grip** → card enters "held" state:
   - Card visually lifts in place (scale + shadow + slight opacity)
   - **Move banner** appears at top of board: "Moving: [task name]" with ✕ cancel button
   - Column drop zones activate (highlighted dashed border area within each column)
3. **User swipes freely** between columns — normal scroll behavior, card stays "held"
4. **Drop zone shows sort-position indicator** — a horizontal line/gap at the exact position where the card would land based on current 3-tier sort order
5. **Tap drop zone** in target column → card moves there via API
   - If target is last column: drop zone shows "Drop to complete ✓" hint
   - Toast confirms move (with undo)
   - If item was completed/uncompleted by the move, secondary toast notes this
6. **Cancel**: tap ✕ on banner, tap the held card again, or press Escape

#### Completion Column Awareness
- **Drop zone in last column**: Shows "Drop here to complete ✓" visual hint
- **Dragging OUT of last column**: Toast confirms "Item marked incomplete" after drop
- Both behaviors match desktop's bidirectional completion↔column sync

#### Hybrid: Direct Drag on Tablet/Desktop
When multiple columns are visible side-by-side (tablet/desktop breakpoint):
- **Hold grip + drag** across visible columns works as traditional drag-and-drop
- Same sort-position indicator shows in target column as card hovers
- If target column is off-screen, auto-scroll with edge hotzone (100px from edge, smooth scroll)
- Pick-up-and-place also still works (for consistency and preference)

Both paths produce identical visual feedback and API calls.

#### Gesture Disambiguation (final, no conflicts)
| Gesture | List View | Board View |
|---------|-----------|------------|
| Tap card | Open detail | Open detail |
| Tap grip icon | — (no grip in list) | Enter move mode (pick-up-and-place) |
| Hold grip + drag | — | Direct drag (tablet/desktop) |
| Long-press card (500ms) | Context menu | Context menu |
| Swipe left/right | Complete/Delete | Scroll columns (normal) |

### Commits
10. **Add pick-up-and-place move mode for board cards** — grip icon on cards, tap-to-hold state, move banner with cancel, column drop zone activation, sort-position preview indicator
11. **Add drop zone interaction and move API integration** — tap drop zone to place, completion column hints, auto-complete/uncomplete handling, undo toast, haptic feedback
12. **Add direct drag-and-drop for tablet and desktop** — hold-grip-and-drag across visible columns, edge hotzone auto-scroll, same sort-position indicator and completion awareness as pick-and-place

---

## Cross-Cutting Concerns

### Testing Strategy
- **Sort engine**: Unit-style tests comparing JS sort output against known desktop sort orders (can use existing test fixtures)
- **API endpoints**: Extend `test_web_api.py` for sort config, presets, apply-preset, column protection validation
- **PWA tests**: Extend `test_web_pwa.py` for new static asset changes
- **Manual**: Test all interactions on iPhone Safari, Android Chrome, iPad, desktop browsers

### Service Worker Cache
- Bump SW cache version on each deploy (currently v7)
- No new static files needed (all changes are in existing app.js / style.css / index.html)

### Accessibility
- Context menu: ARIA `role="dialog"`, focus trap, Escape-to-close (matching existing sheet pattern)
- Drag mode: `aria-live="polite"` announcement for "Moving [task name]" and "Placed in [column]"
- Drop zones: `role="button"` with `aria-label="Drop in [column name]"`
- Grip icon: `aria-label="Move card"`, `role="button"`

### Performance
- Sort engine: O(n log n) — negligible for expected item counts (<1000)
- Drop zone position preview: compute once on column enter, not on every frame
- Board re-render after move: full refresh from API (consistent with existing pattern)
