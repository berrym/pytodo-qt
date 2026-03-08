# Kanban Board View -- Design Document

## Purpose

A board view for pytodo-qt that displays items as cards arranged in vertical columns, complementing the existing list/table view. Users can toggle between list and board views for any list. The board view provides spatial organization for workflow-oriented tasks, making pytodo-qt the first privacy-focused todo app to offer both list and Kanban views with P2P sync.

## Why This Feature

Every major commercial todo app (Todoist, TickTick, Notion, Trello) offers a board/Kanban view. Privacy-focused alternatives (Tasks.org, Vikunja, OpenTasks) overwhelmingly offer only list views. Adding a board view directly addresses the gap described in the strategic roadmap -- "Todoist for people who care about privacy" needs feature parity where it matters. A board view is particularly valuable for:

- Tracking work through stages (research, writing, review, done)
- Limiting work-in-progress to maintain focus
- Visualizing bottlenecks in personal workflows
- Providing a complementary view of the same data without forcing users to restructure their habits

## Data Model: The `board_column` Field

### Decision: Explicit Field vs. Derived State

The board needs to know which column each item belongs to. Two options were considered:

**Option A (rejected): Derive columns from existing fields.** Map `complete=False` to "To Do", introduce an `in_progress` boolean for "In Progress", and `complete=True` to "Done". This breaks down with custom columns and conflates item state with workflow position.

**Option B (chosen): Add a `board_column` field to `TodoItem`.** A string field that stores the column name. Default is empty string (meaning "To Do" / the first column). This is orthogonal to `complete` -- an item can be in any column regardless of completion state, though moving to "Done" can optionally auto-toggle `complete`.

### New Field on TodoItem

```python
@dataclass
class TodoItem:
    # ... existing fields ...
    board_column: str = ""  # Empty = first column (default "To Do")
```

### Why a String, Not an Integer Index

Column names are human-readable and survive column reordering. If columns were stored by index, reordering columns would require updating every item. A string is also more readable in the JSON sync payload and in the SQLite database.

### Relationship to `complete`

The `board_column` field and `complete` field are independent:

- Moving a card to the "Done" column does NOT auto-toggle `complete` by default. The user can enable "auto-complete on Done" in settings if desired.
- Toggling `complete` (via checkbox or keyboard) does NOT move the card to "Done" by default. Same optional behavior.
- This independence is important because some workflows use "Done" to mean "ready for review" rather than "completed."

## Column Model

### Default Columns

Every list starts with three columns:

```
"To Do"  |  "In Progress"  |  "Done"
```

These are the standard Kanban defaults and match most personal productivity workflows.

### Column Configuration: Per-List

Columns are defined per-list, not globally. Different lists serve different workflows:

- A "Grocery" list might just need "To Buy" | "Got It"
- A "Writing" list might need "Ideas" | "Drafting" | "Editing" | "Published"
- A "Chores" list uses the defaults

### Storage: `board_columns` Field on TodoList

```python
@dataclass
class TodoList:
    # ... existing fields ...
    board_columns: list[str] = field(
        default_factory=lambda: ["To Do", "In Progress", "Done"]
    )
```

Stored as a JSON array in the SQLite `lists` table (TEXT column, same pattern as `tags` on items).

### Column Operations

| Operation | Effect | Undo Support |
|-----------|--------|--------------|
| Add column | Appends to `board_columns` list | Yes -- `AddColumnCommand` |
| Remove column | Removes from list; items in that column get `board_column = ""` (back to first column) | Yes -- captures displaced items |
| Rename column | Updates the column name in `board_columns` and all items referencing it | Yes -- `RenameColumnCommand` |
| Reorder columns | Swaps positions in the `board_columns` list; item `board_column` strings unchanged | Yes -- `ReorderColumnsCommand` |

### Column Name Constraints

- Non-empty, stripped of leading/trailing whitespace
- Unique within a list (case-insensitive comparison)
- Maximum 50 characters
- No restrictions on characters (emoji allowed)

## Schema Changes

### Schema v11: `board_column` on Items

```sql
ALTER TABLE items ADD COLUMN board_column TEXT NOT NULL DEFAULT ''
```

### Schema v11: `board_columns` on Lists

```sql
ALTER TABLE lists ADD COLUMN board_columns TEXT
```

When `board_columns` is NULL, the UI uses the default `["To Do", "In Progress", "Done"]`. This means existing lists work without migration beyond the column addition.

### Migration

Follows the established pattern in `database.py`:

```python
def _upgrade_10_to_11(self) -> None:
    cursor = self.connection.execute("PRAGMA table_info(items)")
    columns = [row[1] for row in cursor.fetchall()]

    if "board_column" not in columns:
        self.connection.execute(
            "ALTER TABLE items ADD COLUMN board_column TEXT NOT NULL DEFAULT ''"
        )
        logger.log.info("Migrated schema 10->11: added board_column to items")

    cursor = self.connection.execute("PRAGMA table_info(lists)")
    columns = [row[1] for row in cursor.fetchall()]

    if "board_columns" not in columns:
        self.connection.execute(
            "ALTER TABLE lists ADD COLUMN board_columns TEXT"
        )
        logger.log.info("Migrated schema 10->11: added board_columns to lists")

    self.set_schema_version(11)
```

## Sync Compatibility

Both new fields use the established backward-compatibility pattern:

- `TodoItem.to_dict()` includes `"board_column": self.board_column`
- `TodoItem.from_dict()` uses `data.get("board_column", "")` -- older peers without the field treat all items as first-column
- `TodoList.to_dict()` includes `"board_columns": self.board_columns`
- `TodoList.from_dict()` uses `data.get("board_columns", ["To Do", "In Progress", "Done"])`
- LWW per-item merge handles `board_column` naturally -- it is just another field on the winning item
- LWW per-list merge handles `board_columns` as part of list metadata

### Conflict Scenario

If peer A moves a card to "In Progress" and peer B moves the same card to "Done", the peer with the later `updated_at` wins. This is consistent with how all other fields (priority, due_date, reminder) resolve conflicts.

## View Mode Architecture

### Toggle Mechanism

A view mode toggle in the toolbar switches between list and board views:

```
[List View] [Board View]
```

Implemented as a `QButtonGroup` with two `QToolButton` widgets using exclusive toggle. The selected view mode is stored in the config.

### Config: View Preference

```python
@dataclass
class DatabaseConfig:
    # ... existing fields ...
    view_mode: str = "list"  # "list" or "board"
```

The view mode is global (not per-list) to match user expectation -- "I prefer to work in board view" is a personal preference, not a list property. However, the `board_columns` configuration remains per-list.

### Central Widget Layout

The existing `_setup_central_widget` layout changes from:

```
ListSelectorWidget
SearchFilterWidget
TodoTableWidget
```

To:

```
ListSelectorWidget
SearchFilterWidget
QStackedWidget
  ├── TodoTableWidget (index 0)
  └── KanbanBoardWidget (index 1)
```

`QStackedWidget` shows one child at a time. Switching views calls `setCurrentIndex()`. Both widgets remain alive and share the same underlying data. The `_refresh_ui()` method on MainWindow already calls `self.todo_table.set_list(active_list)` -- it will additionally call `self.kanban_board.set_list(active_list)` (or only refresh the visible widget for performance).

### Signal Routing

Both `TodoTableWidget` and `KanbanBoardWidget` emit the same set of signals for item mutations:

```python
# Shared signal interface (both widgets emit these)
item_priority_changed = pyqtSignal(object, int)
item_reminder_changed = pyqtSignal(object, str)
item_due_date_changed = pyqtSignal(object, object)
item_due_time_changed = pyqtSignal(object, object)
item_selected = pyqtSignal(object)
edit_tags_requested = pyqtSignal(object)
toggle_requested = pyqtSignal()
delete_requested = pyqtSignal()
edit_recurrence_requested = pyqtSignal()
focus_requested = pyqtSignal(object)
# New signal for board view:
item_column_changed = pyqtSignal(object, str)  # (item_id, new_column_name)
```

MainWindow connects to signals from both widgets. The `item_column_changed` signal triggers a `MoveToColumnCommand` on the undo stack.

## Widget Architecture

### KanbanBoardWidget

```
KanbanBoardWidget (QWidget)
└── QScrollArea (horizontal scroll for many columns)
    └── QWidget (container)
        └── QHBoxLayout
            ├── KanbanColumnWidget ("To Do")
            ├── KanbanColumnWidget ("In Progress")
            ├── KanbanColumnWidget ("Done")
            └── QPushButton ("+") [Add Column]
```

### KanbanColumnWidget

```
KanbanColumnWidget (QFrame)
└── QVBoxLayout
    ├── QHBoxLayout (header)
    │   ├── QLabel (column name, bold)
    │   ├── QLabel (item count / WIP indicator)
    │   └── QToolButton (column menu: rename, delete, WIP limit)
    ├── QScrollArea (vertical scroll for cards)
    │   └── QVBoxLayout
    │       ├── KanbanCardWidget
    │       ├── KanbanCardWidget
    │       ├── KanbanCardWidget
    │       └── (stretch)
    └── QPushButton ("+ Add item") [quick-add to this column]
```

### KanbanCardWidget

```
KanbanCardWidget (QFrame)
└── QVBoxLayout
    ├── QHBoxLayout (top row)
    │   ├── QLabel (priority indicator — colored dot)
    │   ├── QLabel (reminder text, elided)
    │   └── QCheckBox (complete toggle)
    ├── QHBoxLayout (metadata row, only if applicable)
    │   ├── QLabel (due date, colored by urgency)
    │   ├── QLabel (recurrence icon)
    │   └── QLabel (pomodoro count: "2x 🍅" if time_spent > 0)
    └── QHBoxLayout (tags row, only if tags exist)
        ├── QLabel (tag chip)
        ├── QLabel (tag chip)
        └── ...
```

## Card Display

### What Each Card Shows

| Element | Visibility | Details |
|---------|------------|---------|
| Priority dot | Always | Colored circle: red (high), blue (normal), gray (low) |
| Reminder text | Always | First ~60 chars, elided with ellipsis |
| Completion checkbox | Always | Small checkbox in top-right |
| Due date | If set | "Today", "Tomorrow", "Overdue (2d)", etc. Same `format_due_date()` |
| Due time | If set | Appended to due date string |
| Recurrence icon | If recurring | Small repeat icon, same SVG as list view |
| Pomodoro count | If time_spent > 0 | Session count (time_spent / work_duration) |
| Tags | If any | Compact colored chips, max 3 visible + "+N" overflow |
| Active focus | If Pomodoro running | Pulsing border or glow effect |

### Card Styling

Cards use `QFrame` with `StyledPanel` shape and `Raised` shadow. Theme colors from `get_colors()`:

- Default card: `base` background, `border` outline
- Completed card: `completed_bg` background, `completed_text` for text, strikethrough on reminder
- Overdue card: Left border accent in `due_overdue` color
- Active focus card: Border in `highlight` color, subtle pulse animation

### Card Interaction

- **Single click**: Selects card (highlights border, emits `item_selected`)
- **Double click**: Opens inline edit for reminder text
- **Right click**: Context menu (same options as table view: Edit Tags, Edit Recurrence, Start Focus, Toggle Complete, Delete)
- **Drag**: Initiates drag to another column or position (see Drag-and-Drop section)

## Drag-and-Drop

### Implementation: Qt Drag-and-Drop Framework

Cards use Qt's built-in drag-and-drop system via `QDrag`:

```python
class KanbanCardWidget(QFrame):
    def mouseMoveEvent(self, event):  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            if (event.pos() - self._drag_start).manhattanLength() > 10:
                self._start_drag()

    def _start_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-pytodo-card", str(self._item_id).encode())
        drag.setMimeData(mime)
        # Create semi-transparent pixmap of the card
        pixmap = self.grab()
        pixmap.setDevicePixelRatio(2.0)  # for Retina
        drag.setPixmap(pixmap.scaled(
            pixmap.width() // 2, pixmap.height() // 2,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        drag.exec(Qt.DropAction.MoveAction)
```

### Drop Targets

Each `KanbanColumnWidget` accepts drops:

```python
class KanbanColumnWidget(QFrame):
    def __init__(self, ...):
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasFormat("application/x-pytodo-card"):
            event.acceptProposedAction()
            self._set_drop_highlight(True)

    def dragLeaveEvent(self, event):  # noqa: N802
        self._set_drop_highlight(False)

    def dropEvent(self, event):  # noqa: N802
        item_id = UUID(event.mimeData().data("application/x-pytodo-card").data().decode())
        self._set_drop_highlight(False)
        self.card_dropped.emit(item_id, self._column_name)
        event.acceptProposedAction()
```

### Visual Feedback During Drag

- Source card becomes semi-transparent (opacity 0.4)
- Target column gets a highlighted border (`highlight` color, 2px)
- Drop position indicator: a horizontal line between cards showing where the card will land
- If WIP limit would be exceeded: column border turns `due_overdue` red, tooltip shows "WIP limit reached"

### Within-Column Reordering

Cards within a column can be reordered by dragging. This requires a `board_order` field:

```python
@dataclass
class TodoItem:
    # ... existing fields ...
    board_order: int = 0  # Sort position within column (lower = higher)
```

When a card is dropped between two existing cards, its `board_order` is set to the midpoint. Periodic normalization re-indexes orders to prevent floating-point-like gaps from growing indefinitely.

**Alternatively**, within-column order can reuse the existing multi-tier sort system (completion, due date, priority). This avoids a new field but means the user cannot manually reorder within a column. The recommended approach is to use the existing sort system as the default, with manual reordering as a stretch goal that adds `board_order`.

**Decision for v1:** Use the existing sort system for within-column ordering. Cards in each column are sorted by the same tiers configured in Settings (completion, due date, priority). Manual drag-to-reorder within a column is deferred.

## WIP Limits

### Core Kanban Principle

Work-in-progress limits prevent overcommitting. Each column can have an optional maximum number of items.

### Configuration

WIP limits are stored per-column in the list's `board_columns` data. The simple string list becomes a structured format:

```python
# Simple format (backward compatible):
board_columns: list[str] = ["To Do", "In Progress", "Done"]

# Extended format (when WIP limits are configured):
# Stored as JSON: [{"name": "To Do"}, {"name": "In Progress", "wip_limit": 3}, {"name": "Done"}]
```

To maintain backward compatibility with the simple string format, `board_columns` accepts both forms:

```python
def _parse_board_columns(raw: list) -> list[dict]:
    """Normalize board_columns to structured format."""
    result = []
    for col in raw:
        if isinstance(col, str):
            result.append({"name": col})
        elif isinstance(col, dict):
            result.append(col)
    return result
```

### Visual Indicators

| State | Column Count Display | Styling |
|-------|---------------------|---------|
| Under limit | `2 / 5` | Normal text |
| At limit | `5 / 5` | Bold, `due_today` amber color |
| Over limit | `7 / 5` | Bold, `due_overdue` red, column header background tinted red |
| No limit set | `3` | Normal text, no denominator |

### WIP Limit Behavior

- WIP limits are **advisory, not enforced**. Items can still be moved into an over-limit column. The visual warning is sufficient -- hard blocks frustrate users.
- When dragging a card into an at-limit column, the drop highlight uses amber/red to warn the user, but the drop is allowed.
- The "Done" column typically has no WIP limit.

### Settings UI for WIP Limits

Right-click on a column header shows a context menu:

```
Rename Column...
Set WIP Limit...
────────────────
Delete Column
```

"Set WIP Limit..." opens a small dialog with a `QSpinBox` (0 = no limit, 1-99).

## Pomodoro Integration

### Active Focus Highlighting

When a Pomodoro session is running on an item:

1. The card for that item gets a distinctive border (2px solid `highlight` color with subtle pulse)
2. A small timer badge appears on the card showing remaining time: `23:41`
3. The card is always visible -- if it scrolls out of view in its column, the column auto-scrolls to show it

### "In Progress" Column Tie-in

The "In Progress" column is a natural home for items being actively worked on. When starting a focus session from the board view:

1. If the item is not already in "In Progress", offer to move it there (optional, configurable)
2. When a focus session completes, DO NOT auto-move the card -- the user decides when work is truly done

### Starting Focus from Board

Right-click card context menu includes "Start Focus Session" (same as table view). Additionally, a small play-button icon on the card can start a session directly.

## Keyboard Navigation

### Board-Specific Shortcuts

| Shortcut | Action |
|----------|--------|
| `Left` / `Right` | Move focus between columns |
| `Up` / `Down` | Move focus between cards within a column |
| `Enter` | Select focused card (emit `item_selected`) |
| `Space` | Toggle completion of focused card |
| `M` then `Left`/`Right` | Move selected card to adjacent column |
| `Ctrl+Left` / `Ctrl+Right` | Move selected card to previous/next column |
| `Delete` / `Backspace` | Delete selected card |
| `E` | Edit tags on selected card |
| `F` | Start focus session on selected card |
| `+` or `N` | Add new item to focused column |

### Focus Model

The board maintains a focus position as `(column_index, card_index)`. The focused card gets a dotted outline (distinct from selection highlight). Navigation wraps: pressing Down on the last card in a column wraps to the first card, Left on the first column wraps to the last column.

### Keyboard Card Movement

Moving cards between columns via keyboard creates the same `MoveToColumnCommand` as drag-and-drop. The status bar shows a brief confirmation: "Moved to In Progress".

## Undo/Redo Commands

### New Commands

```python
class MoveToColumnCommand(QUndoCommand):
    """Move an item to a different board column."""

    def __init__(self, window, list_id, item_id, old_column, new_column):
        super().__init__(f"Move to {new_column}")
        # ...

class AddColumnCommand(QUndoCommand):
    """Add a new column to the board."""

    def __init__(self, window, list_id, column_name):
        super().__init__(f"Add column '{column_name}'")
        # ...

class RemoveColumnCommand(QUndoCommand):
    """Remove a column from the board, displacing items to first column."""

    def __init__(self, window, list_id, column_name, displaced_item_ids):
        super().__init__(f"Remove column '{column_name}'")
        # ...

class RenameColumnCommand(QUndoCommand):
    """Rename a board column."""

    def __init__(self, window, list_id, old_name, new_name):
        super().__init__(f"Rename column '{old_name}' to '{new_name}'")
        # ...

class SetWipLimitCommand(QUndoCommand):
    """Set WIP limit on a column."""

    def __init__(self, window, list_id, column_name, old_limit, new_limit):
        super().__init__(f"Set WIP limit on '{column_name}'")
        # ...
```

All commands follow the existing pattern: capture state in `__init__`, mutate in `redo()`, reverse in `undo()`, call `mark_updated()` on affected items/lists, then `_save_database()` and `_refresh_ui()`.

## ASCII Mockups

### Full Board View

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ [Groceries ▼] [+ New List]                                                     │
│ [🔍 Search...] [Priority ▼] [Status ▼] [Due ▼] [Tag ▼]                        │
│                                                                                 │
│  [≡ List]  [⊞ Board]                                                           │
│                                                                                 │
│ ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐               │
│ │ TO DO         7  │  │ IN PROGRESS  2/3 │  │ DONE          4  │               │
│ ├──────────────────┤  ├──────────────────┤  ├──────────────────┤               │
│ │                  │  │                  │  │                  │               │
│ │ ┌──────────────┐ │  │ ┌──────────────┐ │  │ ┌──────────────┐ │               │
│ │ │ ● Buy milk   │ │  │ │ ● Write blog │ │  │ │ ✓ Fix bug #42│ │               │
│ │ │   Today      │ │  │ │   Tomorrow   │ │  │ │   Mar 05     │ │               │
│ │ │   @errands   │ │  │ │   @work      │ │  │ │   @work      │ │               │
│ │ └──────────────┘ │  │ │   ▶ 23:41    │ │  │ └──────────────┘ │               │
│ │                  │  │ └──────────────┘ │  │                  │               │
│ │ ┌──────────────┐ │  │                  │  │ ┌──────────────┐ │               │
│ │ │ ● Call dentist│ │  │ ┌──────────────┐ │  │ │ ✓ Update deps│ │               │
│ │ │   Overdue 2d │ │  │ │ ● Review PR  │ │  │ │   Mar 03     │ │               │
│ │ │   🔁         │ │  │ │   Friday     │ │  │ └──────────────┘ │               │
│ │ └──────────────┘ │  │ │   @code      │ │  │                  │               │
│ │                  │  │ └──────────────┘ │  │ ┌──────────────┐ │               │
│ │ ┌──────────────┐ │  │                  │  │ │ ✓ Groceries  │ │               │
│ │ │ ○ Read ch. 5 │ │  │                  │  │ │   Mar 01     │ │               │
│ │ │   This week  │ │  │                  │  │ │   2x focus   │ │               │
│ │ │              │ │  │                  │  │ └──────────────┘ │               │
│ │ └──────────────┘ │  │                  │  │                  │               │
│ │                  │  │                  │  │                  │               │
│ │  [+ Add item]    │  │  [+ Add item]    │  │  [+ Add item]    │               │
│ └──────────────────┘  └──────────────────┘  └──────────────────┘               │
│                                                                                 │
│ Current: 5/13  ████████░░ 38%  │  Total: 12/28       Last sync: 2m ago         │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Card Detail (zoomed)

```
┌────────────────────────┐
│ ●  Write blog post   ☐ │    ● = priority dot (colored)
│    Tomorrow  3:00 PM    │    ☐ = completion checkbox
│    🔁 Every week        │    🔁 = recurrence indicator
│    ▶ 23:41              │    ▶ = active Pomodoro timer
│    ┌────┐ ┌──────┐      │    Colored tag chips
│    │work│ │urgent│      │
│    └────┘ └──────┘      │
└────────────────────────┘
```

### WIP Limit Warning

```
┌──────────────────┐
│ IN PROGRESS  4/3 │  ← Red text, column header tinted
├──────────────────┤
│  (4 cards here,  │
│   limit is 3)    │
└──────────────────┘
```

### Drag in Progress

```
                    ┌ ─ ─ ─ ─ ─ ─ ─┐
                      ● Buy milk        ← Dragged card (semi-transparent)
                    └ ─ ─ ─ ─ ─ ─ ─┘
                           │
┌──────────────────┐  ┌────▼─────────────┐
│ TO DO         6  │  │ IN PROGRESS  2/3 │  ← Column highlighted
├──────────────────┤  ├──────────────────┤
│                  │  │ ┌──────────────┐ │
│ (source card     │  │ │ Write blog   │ │
│  is grayed out)  │  │ └──────────────┘ │
│                  │  │ ═══════════════  │  ← Drop position indicator
│                  │  │ ┌──────────────┐ │
│                  │  │ │ Review PR    │ │
│                  │  │ └──────────────┘ │
└──────────────────┘  └──────────────────┘
```

## Relationship to Other Features

### Search/Filter

The `SearchFilterWidget` applies identically to board view. Filtered-out cards are hidden from all columns. The column counts update to reflect visible cards only. WIP limits are evaluated against total (unfiltered) card counts -- a column with 3 items does not appear under-limit just because a filter hides 2 of them.

### Sort Order

The multi-tier sort system (completion, due date, priority) determines card order within each column. The sort tiers from `DatabaseConfig` apply to both views. Since the board already separates items by column, the "completion" sort tier has less impact in board view, but remains active for consistency.

### Tags

Tags are displayed as compact colored chips on cards. The tag filter in `SearchFilterWidget` hides cards that do not match. This works identically across both views.

### Recurrence

Recurring items show the repeat icon on their card. When a recurring item is completed and advances its due date, the card stays in its current column (the `board_column` is not reset). This preserves the user's workflow position -- a daily task that lives in "In Progress" should stay there after completion advances it.

### Due Dates

Due date display on cards uses the same `format_due_date()` function with the same urgency coloring (overdue red, today amber, this week green). Cards with overdue dates get a left-border accent in red for quick scanning.

### Pomodoro / Focus Timer

- Active focus session: card gets highlighted border and countdown badge
- `time_spent > 0`: card shows session count (e.g., "2x focus")
- Starting a focus session from the board context menu works identically to the table view
- The status bar Pomodoro display is unchanged -- it is view-independent

### Subtasks (Future)

If subtasks are implemented in a future version, cards would show a progress indicator (e.g., "2/5 subtasks"). The board column of a parent item is independent of its subtasks' columns. Subtasks could optionally be shown as nested cards within the parent card.

### Unseen Sync Changes

The existing unseen-changes indicator on `ListSelectorWidget` is view-independent. If a sync brings changes that affect cards in the board view, the column containing the changed card could flash briefly or show a badge, but this is a polish item, not a requirement for v1.

## Implementation Plan

### Phase 1: Data Model + Schema (Small)

1. Add `board_column: str = ""` to `TodoItem` dataclass
2. Add `board_columns` to `TodoList` dataclass
3. Schema v11 migration in `database.py`
4. Update `to_dict()` / `from_dict()` on both classes
5. Update `_save_item()` / `_load_item()` in `DatabaseStorage`
6. Tests: serialization round-trip, migration, sync compat

### Phase 2: View Toggle Infrastructure (Small)

1. Add `view_mode` to `DatabaseConfig` and TOML serialization
2. Create `QStackedWidget` in `_setup_central_widget()`
3. Add toolbar toggle buttons (list/board)
4. Wire view mode persistence to config
5. `_refresh_ui()` refreshes only the visible widget

### Phase 3: KanbanBoardWidget Core (Medium)

1. Create `src/pytodo_qt/gui/widgets/kanban_board.py`
2. Implement `KanbanBoardWidget` with `set_list()` and `refresh()`
3. Implement `KanbanColumnWidget` with header and scrollable card area
4. Implement `KanbanCardWidget` with priority, reminder, due date, tags display
5. Wire signals: `item_selected`, `toggle_requested`, `delete_requested`
6. Apply theme colors from `get_colors()`
7. Tests: widget creation, signal emission, card display

### Phase 4: Drag-and-Drop (Medium)

1. Implement `QDrag` initiation on `KanbanCardWidget.mouseMoveEvent`
2. Implement drop handling on `KanbanColumnWidget`
3. Create `MoveToColumnCommand` for undo/redo
4. Visual feedback: source opacity, target highlight, drop indicator
5. Tests: drag-and-drop via command, undo/redo

### Phase 5: Column Management (Small)

1. Add column, remove column, rename column UI
2. Create `AddColumnCommand`, `RemoveColumnCommand`, `RenameColumnCommand`
3. Column context menu (right-click header)
4. Tests: column CRUD, item displacement on remove

### Phase 6: WIP Limits (Small)

1. Extend `board_columns` format to support `{"name": ..., "wip_limit": ...}`
2. WIP limit display in column header
3. Visual warnings (amber/red) when approaching/exceeding
4. `SetWipLimitCommand` for undo/redo
5. Tests: WIP limit display, warning thresholds

### Phase 7: Keyboard Navigation (Small)

1. Focus model `(column_index, card_index)` on `KanbanBoardWidget`
2. Arrow key navigation between columns and cards
3. `Ctrl+Left/Right` to move cards between columns
4. `Space` to toggle, `Delete` to delete, `+` to add
5. Tests: keyboard navigation, card movement

### Phase 8: Pomodoro + Polish (Small)

1. Active focus card highlighting
2. Timer badge on focused card
3. Auto-scroll to focused card
4. Smooth animations for card movement (optional, QPropertyAnimation)
5. Integration test: full workflow across views

## Estimated Effort

| Phase | Scope | Estimate |
|-------|-------|----------|
| Phase 1: Data Model | Model, schema, serialization | 1-2 hours |
| Phase 2: View Toggle | Config, stacked widget, toolbar | 1-2 hours |
| Phase 3: Board Widget | Three widget classes, theming | 4-6 hours |
| Phase 4: Drag-and-Drop | Qt DnD, undo command, visuals | 3-4 hours |
| Phase 5: Column Mgmt | CRUD, undo commands | 2-3 hours |
| Phase 6: WIP Limits | Data format, display, warnings | 1-2 hours |
| Phase 7: Keyboard Nav | Focus model, shortcuts | 2-3 hours |
| Phase 8: Pomodoro + Polish | Integration, animations | 2-3 hours |
| **Total** | | **16-25 hours** |

## Files Changed or Created

### New Files

| File | Purpose |
|------|---------|
| `src/pytodo_qt/gui/widgets/kanban_board.py` | `KanbanBoardWidget`, `KanbanColumnWidget`, `KanbanCardWidget` |
| `tests/test_kanban.py` | Board widget tests |
| `tests/test_kanban_commands.py` | Undo/redo command tests for board operations |

### Modified Files

| File | Changes |
|------|---------|
| `src/pytodo_qt/core/models.py` | `board_column` on `TodoItem`, `board_columns` on `TodoList` |
| `src/pytodo_qt/core/config.py` | `view_mode` on `DatabaseConfig` |
| `src/pytodo_qt/core/database.py` | Schema v11 migration, column read/write |
| `src/pytodo_qt/gui/commands.py` | `MoveToColumnCommand`, `AddColumnCommand`, `RemoveColumnCommand`, `RenameColumnCommand`, `SetWipLimitCommand` |
| `src/pytodo_qt/gui/main_window.py` | `QStackedWidget` in central layout, view toggle, `item_column_changed` handler |
| `src/pytodo_qt/gui/widgets/__init__.py` | Export `KanbanBoardWidget` |

## Open Questions

1. **Should the "Done" column auto-hide completed items after N days?** This would keep the board clean but might surprise users. Recommendation: no auto-hide in v1; add as a per-column option later.

2. **Column limit: how many columns should be allowed?** Practical limit around 10. Beyond that, the horizontal scroll becomes unwieldy. Not a hard technical limit, just a UX guideline.

3. **Should we support swimlanes (horizontal grouping by tag/priority)?** This is a significant complexity increase. Defer to a future version. The search/filter bar already provides tag/priority filtering which achieves a similar result.

4. **Mobile/web board view:** The web UI (planned for future phases) should also support board view. The data model designed here (stored columns and column assignments) is UI-framework-agnostic and will work with any frontend.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Drag-and-drop is finicky on some Linux DEs | Medium | Low | Keyboard movement as full alternative |
| Many cards in one column = slow scroll | Low | Medium | Virtual scrolling if needed (QListView with delegate) |
| PySide6 migration breaks Qt DnD API | Low | Medium | DnD APIs are nearly identical between PyQt6 and PySide6 |
| Users expect Trello-like richness | Medium | Low | Set expectations: this is a personal productivity board, not a team collaboration tool |
| Sync conflicts on `board_column` | Low | Low | LWW resolves deterministically; same pattern as all other fields |
