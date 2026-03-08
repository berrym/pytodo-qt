# Subtasks — Design Document

## Purpose

Add one level of parent/child nesting to todo items. A parent item can have zero or more child items (subtasks) that appear indented beneath it in the table. This covers the vast majority of real-world subtask needs — breaking a task like "Plan birthday party" into "Book venue", "Send invitations", "Order cake" — without the complexity of arbitrary-depth nesting.

## Why One Level

Unlimited nesting sounds flexible but creates exponential complexity in sort order, display layout, drag-and-drop targeting, sync conflict resolution, and keyboard navigation. Todoist, Things 3, and Microsoft To Do all limit subtasks to one level and none of their users are clamouring for deeper nesting. One level keeps the mental model simple: every item is either a top-level task or a subtask of exactly one parent.

## Data Model

### New field on `TodoItem`

```python
@dataclass
class TodoItem:
    # ... existing fields ...
    parent_id: UUID | None = None  # None = top-level item
```

An item with `parent_id = None` is a top-level item. An item with `parent_id` set to another item's UUID is a subtask of that parent. Both parent and child are full `TodoItem` instances in the same `TodoList.items` dict — subtasks are not a separate collection.

### Constraints (enforced in application logic, not SQL)

- `parent_id` must reference an item in the same list, or be `None`.
- An item whose `parent_id` is not `None` cannot itself be a parent (no grandchildren). Enforced by rejecting attempts to add a subtask to an item that already has a `parent_id`.
- A deleted (tombstoned) parent does not cascade-delete children — see Edge Cases.

### Helper properties on `TodoItem`

```python
@property
def is_subtask(self) -> bool:
    return self.parent_id is not None
```

### Helper methods on `TodoList`

```python
def get_children(self, parent_id: UUID) -> list[TodoItem]:
    """Get active (non-deleted) children of a parent, sorted by created_at."""
    return sorted(
        [i for i in self.active_items() if i.parent_id == parent_id],
        key=lambda i: i.created_at,
    )

def child_count(self, parent_id: UUID) -> int:
    """Count active children of a parent."""
    return sum(1 for i in self.active_items() if i.parent_id == parent_id)

def child_completed_count(self, parent_id: UUID) -> int:
    """Count completed active children of a parent."""
    return sum(
        1 for i in self.active_items()
        if i.parent_id == parent_id and i.complete
    )
```

### Serialization

`to_dict()` / `from_dict()` — add `parent_id` as a string UUID or `None`:

```python
# to_dict
"parent_id": str(self.parent_id) if self.parent_id else None,

# from_dict
parent_id_str = data.get("parent_id")  # .get() with no default = backward-compatible
parent_id = UUID(parent_id_str) if parent_id_str else None
```

The `.get("parent_id")` pattern (no default needed, returns `None`) means older peers that have never seen this field will deserialize items with `parent_id=None`, treating everything as top-level. This is the same pattern used for `due_date`, `due_time`, `tags`, and every other field added post-v1.

### `create_todo_item()` factory

Add optional `parent_id` parameter:

```python
def create_todo_item(
    reminder: str,
    priority: int = 2,
    due_date: date | None = None,
    due_time: time | None = None,
    tags: list[str] | None = None,
    recurrence_type: str | None = None,
    recurrence_interval: int = 1,
    recurrence_end_date: date | None = None,
    recurrence_end_count: int | None = None,
    parent_id: UUID | None = None,
) -> TodoItem:
```

## Schema Migration (v10 -> v11)

```python
def _migrate_schema_10_to_11(self) -> None:
    """Migrate schema from version 10 to 11 (add parent_id column)."""
    current_version = self.get_schema_version()
    if current_version >= 11:
        return

    cursor = self.connection.execute("PRAGMA table_info(items)")
    columns = [row[1] for row in cursor.fetchall()]

    if "parent_id" not in columns:
        self.connection.execute("ALTER TABLE items ADD COLUMN parent_id TEXT")
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_parent_id ON items(parent_id)"
        )
        logger.log.info("Migrated schema 10->11: added parent_id column")

    self.set_schema_version(11)
```

Update `SCHEMA_VERSION = 11`.

Update `_CREATE_ITEMS_TABLE` to include `parent_id TEXT` (for fresh installs).

Update `_CREATE_INDEXES` to include `idx_items_parent_id`.

Update `save_item()` to persist `parent_id`, and `_row_to_item()` to read it with the same try/except fallback pattern used for every other optional column.

## Table Display

### Rendering approach

The table remains a flat `QTableWidget` — no `QTreeView` migration needed. Subtasks are rendered as regular rows that happen to be indented and positioned immediately after their parent.

### Sort behavior

The sort pipeline in `refresh()` changes from:

```
items = sorted(active_items, key=sort_key)
```

to a two-phase approach:

```
1. Separate items into top-level (parent_id is None) and children
2. Sort top-level items using the existing multi-tier sort_key
3. For each top-level item, insert its children immediately after it,
   sorted among themselves using the same sort_key
4. Collapsed parents: skip inserting children entirely
```

```python
def _build_display_order(self, items: list[TodoItem], sort_key) -> list[TodoItem]:
    """Build flat display list with children grouped under parents."""
    top_level = [i for i in items if i.parent_id is None]
    children_by_parent: dict[UUID, list[TodoItem]] = {}
    for i in items:
        if i.parent_id is not None:
            children_by_parent.setdefault(i.parent_id, []).append(i)

    top_level.sort(key=sort_key)
    result: list[TodoItem] = []
    for parent in top_level:
        result.append(parent)
        kids = children_by_parent.get(parent.id, [])
        if kids and not self._is_collapsed(parent.id):
            kids.sort(key=sort_key)
            result.extend(kids)
    return result
```

Children whose parent was filtered out (e.g., parent doesn't match a tag filter) are shown as standalone top-level items — they don't disappear just because their parent is hidden.

### Visual indentation

```
+----------+-------------------------------------------+----------+---------+
| Priority | Reminder                                  | Due Date | Tags    |
+----------+-------------------------------------------+----------+---------+
| High     | Plan birthday party                [3/5]  | Mar 15   | @home   |
| Normal   |   > Book venue                            | Mar 10   |         |
| Normal   |   > Send invitations                 [x]  | Mar 08   |         |
| Normal   |   > Order cake                            | Mar 12   |         |
| Normal   |   > Buy decorations                  [x]  | Mar 13   |         |
| Normal   |   > Plan music playlist              [x]  | Mar 14   |         |
| Low      | Buy groceries                             | Today    | @errand |
| Normal   | Read chapter 5                            |          | @study  |
+----------+-------------------------------------------+----------+---------+
```

Implementation details:

- **Indent**: The reminder `QLineEdit` for subtask rows gets `setContentsMargins(24, 0, 0, 0)` on its parent container (or a 24px spacer). A small ">" indicator prefix is painted via a `QLabel` before the `QLineEdit`.
- **Progress badge**: Parent rows show a `[3/5]` badge widget after the reminder text (or after the ellipsis label). This is a `QLabel` styled with the theme's `muted_text` color. Hidden when a parent has zero children.
- **Expand/collapse toggle**: A small disclosure triangle (or +/- icon) is placed at the left edge of the reminder container for parent items. Clicking it toggles the collapsed state. The toggle is a `QPushButton` with a fixed 16x16 size, flat style, and a theme-appropriate icon.

### Collapse state

```python
# On TodoTableWidget
_collapsed_parents: set[UUID]  # Session-local, not persisted
```

When a parent is collapsed, its children are simply not emitted by `_build_display_order()`. The collapse state is session-local — all parents start expanded on launch. This avoids adding persistent state for what is purely a display concern.

### Row height

Subtask rows use the same 42px row height as top-level items. No special sizing.

## Expand/Collapse Toggle

### Widget

A `QPushButton` placed as the leftmost element in the reminder container for parent items:

```
Parent row:   [v] [QLineEdit: "Plan birthday party"] [3/5] [...] [tags]
Subtask row:  [  24px spacer  ] [>] [QLineEdit: "Book venue"] [...] [tags]
```

The button shows:
- Expanded: a downward-pointing triangle (or "v")
- Collapsed: a right-pointing triangle (or ">")
- Not a parent (no children): no button, no spacer consumed

The toggle emits a signal that `refresh()` picks up. Since `refresh()` rebuilds the entire table, toggling is implemented as: flip the collapsed state, call `refresh()`.

### Keyboard shortcut

`Left Arrow` on a parent row collapses it. `Right Arrow` expands. When collapsed and `Right Arrow` is pressed, expand. When expanded and `Left Arrow` is pressed, collapse. These are table-level key event overrides that check whether the current row is a parent.

## Completion Logic

### Chosen model: independent completion (with visual nudge)

Parent and child completion are independent. Completing all children does NOT auto-complete the parent. Completing the parent does NOT auto-complete the children. Rationale:

- Users have different mental models. Some people use the parent as a "milestone" that represents more than just its subtasks. Auto-completing the parent when children are done removes user agency.
- Auto-completing children when the parent is completed destroys undo granularity — a single undo would need to reverse N+1 toggles.
- Todoist and Things 3 both use independent completion for this reason.

However, when all children of an incomplete parent are completed, the progress badge `[5/5]` turns green (theme's `success` color) as a visual nudge that the parent may be ready to complete.

### Recurring parents with subtasks

If a parent is recurring and gets completed (advancing its due date), its children are NOT reset. Children are independent items. If the user wants repeating subtasks, they should make each child recurring independently.

## Add Subtask UI

### Right-click context menu

When right-clicking a single item, add a new action:

```python
# In _on_context_menu, within the `if len(item_ids) == 1:` block:

# Only show "Add Subtask" if the item is not already a subtask
item = self._current_list.get_item(item_ids[0])
if item and item.parent_id is None:
    add_subtask_action = QAction("Add Subtask", self)
    add_subtask_action.triggered.connect(
        lambda: self.add_subtask_requested.emit(item_ids[0])
    )
    menu.addAction(add_subtask_action)
```

New signal on `TodoTableWidget`:

```python
add_subtask_requested = pyqtSignal(object)  # parent_id: UUID
```

### Handler in MainWindow

The `add_subtask_requested` signal is connected to `_on_add_subtask(parent_id)`, which opens the same `AddTodoDialog` but pre-sets `parent_id` on the created `TodoItem`. The dialog title changes to "Add Subtask" when a parent is specified. The new item inherits the parent's tags by default (user can modify before confirming).

### Keyboard shortcut

`Ctrl+Shift+N` (or `Cmd+Shift+N` on macOS) when a single top-level item is selected adds a subtask to it.

### Inline add

Pressing `Tab` while the "Add todo" input at the bottom has focus and a single parent item is selected could create a subtask instead of a top-level item. This is a nice-to-have for v2 of subtasks — not required for initial implementation.

## Undo/Redo Commands

### `AddSubtaskCommand`

Not strictly needed as a separate command — `AddItemCommand` already handles adding an item to a list. The only difference is the item has `parent_id` set. `AddItemCommand.redo()` already does `todo_list.items[self._item.id] = self._item`, which works regardless of whether `parent_id` is set.

Recommendation: reuse `AddItemCommand` directly. The item passed in already has `parent_id` set by the handler. No new command class needed.

### `ReparentCommand`

A new command for drag-and-drop reparenting:

```python
class ReparentCommand(QUndoCommand):
    """Change an item's parent (or make it top-level)."""

    def __init__(
        self,
        window: MainWindow,
        list_id: UUID,
        item_id: UUID,
        old_parent_id: UUID | None,
        new_parent_id: UUID | None,
    ) -> None:
        if new_parent_id is not None:
            super().__init__("Make subtask")
        else:
            super().__init__("Make top-level")
        self._window = window
        self._list_id = list_id
        self._item_id = item_id
        self._old_parent_id = old_parent_id
        self._new_parent_id = new_parent_id

    def redo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.parent_id = self._new_parent_id
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()

    def undo(self) -> None:
        todo_list = self._window._database.lists.get(self._list_id)
        if not todo_list:
            return
        item = todo_list.get_item(self._item_id)
        if item:
            item.parent_id = self._old_parent_id
            item.mark_updated()
        self._window._save_database()
        self._window._refresh_ui()
```

## Drag-and-Drop Reparenting

### Interaction model

Drag a top-level item onto another top-level item to make it a subtask. Drag a subtask out of its parent group (above or below the parent's child block) to make it top-level. Drag a subtask from one parent to another to reparent it.

### Visual feedback during drag

- When dragging over a valid drop target (a top-level item that is not itself a subtask), highlight the target row with a 2px border in the theme's `highlight` color.
- When dragging over the gap between parent groups (or above/below the table), show a horizontal insertion line — this means "drop as top-level item."
- Invalid targets (dropping a parent onto one of its own children, or making a subtask a parent of another item) show the "no-drop" cursor.

### Implementation

Enable drag-and-drop on the `QTableWidget`:

```python
self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
self.setDefaultDropAction(Qt.DropAction.MoveAction)
self.setDragEnabled(True)
self.viewport().setAcceptDrops(True)
```

Override `dropEvent` to:

1. Determine the source item(s) being dragged (from selection).
2. Determine the drop target row.
3. Look up the target item — if it is a top-level item, reparent the source under it. If the target is a subtask, reparent the source under the same parent. If dropped in empty space or between groups, make top-level.
4. Validate: reject if source already has children (would create grandchildren). Reject if source is the target.
5. Push a `ReparentCommand` onto the undo stack.

### Constraints

- Multi-select drag: if multiple items are selected, only reparent if ALL items are eligible. If any has children, reject the entire operation.
- Cross-list drag is not supported (items stay in their list).

## Filter/Search Behavior

### Text search (search bar)

When the user types a search query:

- Match against both parent and child items independently.
- If a child matches, show it AND its parent (even if the parent doesn't match the query). The parent provides context.
- If a parent matches, show the parent. Its children are shown/hidden per the expand/collapse state — matching children are shown regardless of collapse state.

### Filter bar (due date, priority, tags, completion)

Filters operate on individual items. A child that matches the filter is shown even if its parent doesn't match. The parent is pulled in as a "context row" styled with reduced opacity (muted) to indicate it's shown for context, not because it matched.

If a parent matches but none of its children match, only the parent is shown (children are filtered out).

### Stats (progress bar, counts)

Subtask completion counts toward the list total and the global total. Both parent and child items are counted equally in `active_item_count()`, `completed_count()`, and the status bar progress bar. A parent with 5 subtasks contributes 6 items to the count (1 parent + 5 children).

## Sync Compatibility

### Wire format

`parent_id` is serialized as a string UUID or `null` in the JSON dict. Peers running older versions that have never seen the `parent_id` field will:

1. Deserialize it as `None` (via `.get("parent_id")` returning `None`).
2. Treat all items as top-level.
3. When they send data back, the field will be absent from their serialized items.
4. The receiving (newer) peer sees `.get("parent_id")` return `None`, which is correct — the older peer never set a parent.

This is the exact same backward-compatibility pattern used for `due_date` (v6), `recurrence_*` (v7), `due_time` (v8), `tags` (v9), and `time_spent` (v10).

### Merge behavior in `_merge_sync_data_internal`

`parent_id` participates in LWW like any other item field. When two peers both modify an item and the remote has a newer `updated_at`, the entire item (including `parent_id`) is taken from the remote. No field-level merge is needed.

One subtlety: if a remote sync sets `parent_id` to a UUID that does not exist in the local list (because the parent item was deleted locally), the child becomes an orphan. This is handled by the orphan recovery logic described in Edge Cases.

### No schema version gating

Unlike schema migrations (which gate on the SQLite schema version), the sync wire format does not need gating. The `.get()` pattern handles missing fields gracefully. Older peers simply ignore the field.

## Edge Cases

### 1. Delete parent with existing children

**Behavior**: Orphan the children (make them top-level).

When `DeleteItemsCommand.redo()` marks a parent as deleted, a post-deletion sweep sets `parent_id = None` on all children of that parent. The children are NOT deleted.

```python
# In DeleteItemsCommand.redo(), after marking items deleted:
for item_id in self._item_ids:
    # Orphan any children of this item
    for child in list(todo_list.active_items()):
        if child.parent_id == item_id:
            child.parent_id = None
            child.mark_updated()
```

The command stores the old `parent_id` values so that `undo()` can restore them:

```python
# In DeleteItemsCommand.__init__:
self._orphaned_children: list[tuple[UUID, UUID]] = []  # (child_id, old_parent_id)
```

### 2. Delete subtask

Standard item deletion. No special logic. The parent's progress badge updates on the next `refresh()`.

### 3. Complete parent with incomplete children

Allowed. The parent is marked complete independently. The incomplete children remain incomplete and visible (not hidden). The progress badge still shows, e.g., `[2/5]`.

### 4. Move subtask to a different list

Not directly supported in the current UI (there is no cross-list move operation at all). If added in the future, moving a subtask to a different list should clear its `parent_id` (make it top-level) since the parent does not exist in the target list.

### 5. Orphaned children from sync

If a sync merge introduces a child whose `parent_id` references a non-existent (or deleted) item, the child is treated as an orphan. On the next `refresh()`, orphan recovery runs:

```python
def _recover_orphans(self, items: list[TodoItem]) -> None:
    """Reset parent_id for items whose parent is missing or deleted."""
    active_ids = {i.id for i in items}
    for item in items:
        if item.parent_id is not None and item.parent_id not in active_ids:
            item.parent_id = None
            item.mark_updated()
```

This is called at the start of `refresh()` or in `_merge_sync_data_internal()` after merge completes.

### 6. Subtask of a subtask (depth violation)

Rejected at the UI level. The "Add Subtask" context menu action is not shown for items where `parent_id is not None`. Drag-and-drop onto a subtask reparents under the subtask's parent, not the subtask itself. The `ReparentCommand` validates and no-ops if the target is itself a subtask.

### 7. Recurring subtask

Allowed. A subtask can independently have recurrence settings. When completed, it advances its own due date just like any other recurring item. The parent's progress badge updates accordingly.

### 8. Filter hides parent but not child

The child is shown as a top-level item for display purposes (no indent). When the filter is cleared, it returns to its normal indented position under its parent.

### 9. All items selected + delete

Works the same as today. Both parents and children in the selection are deleted. The orphan sweep is a no-op because the children are being deleted too.

### 10. Copy/duplicate item

If a parent item is duplicated, only the parent is duplicated (not its children). The duplicate is a new top-level item with `parent_id = None`. If a subtask is duplicated, the duplicate is also a subtask of the same parent.

## Progress Indicator on Parent

### Display

A compact badge after the reminder text showing `[completed/total]`:

```
Plan birthday party                                   [3/5]
```

### Implementation

In `refresh()`, when building the reminder container for a parent item:

```python
children = current_list.get_children(item.id)
if children:
    done = sum(1 for c in children if c.complete)
    total = len(children)
    badge = QLabel(f"[{done}/{total}]")
    badge.setFont(make_font(size=11))
    if done == total:
        badge.setStyleSheet(f"color: {colors['success']};")
    else:
        badge.setStyleSheet(f"color: {colors['muted_text']};")
    reminder_layout.addWidget(badge)
```

The badge is placed in the reminder `QHBoxLayout` between the ellipsis label and the tag chips:

```
[toggle] [QLineEdit] [...] [3/5] [tag1] [tag2]
```

### Performance

`get_children()` iterates the items dict, which is O(n) per parent. For a list with P parents and N total items, this is O(P * N) in the worst case. With typical list sizes (< 500 items), this is negligible. If lists grow larger, a pre-built `children_by_parent` index (computed once at the start of `refresh()`) avoids the repeated scan:

```python
children_by_parent: dict[UUID, list[TodoItem]] = {}
for item in items:
    if item.parent_id is not None:
        children_by_parent.setdefault(item.parent_id, []).append(item)
```

This index is already built for `_build_display_order()`, so it can be shared.

## Implementation Plan

### Phase 1: Data model + storage (low risk)

1. Add `parent_id` field to `TodoItem` dataclass.
2. Add `is_subtask` property, `get_children()` / `child_count()` / `child_completed_count()` helpers.
3. Update `to_dict()` / `from_dict()` / `create_todo_item()`.
4. Write schema migration v10 -> v11.
5. Update `save_item()` / `_row_to_item()` in `DatabaseStorage`.
6. Tests: model serialization round-trip, migration, orphan cases.

### Phase 2: Display + sort (medium risk)

1. Implement `_build_display_order()` in `TodoTableWidget`.
2. Add visual indentation (spacer + ">" prefix) for subtask rows.
3. Add progress badge `[X/Y]` on parent rows.
4. Add expand/collapse toggle button on parent rows.
5. Track `_collapsed_parents: set[UUID]` session state.
6. Update sort to group children under parents.
7. Tests: display order with various sort configs, collapse toggle.

### Phase 3: Interactions (medium risk)

1. Add "Add Subtask" to right-click context menu.
2. Connect signal to `_on_add_subtask()` handler in `MainWindow`.
3. Implement `ReparentCommand`.
4. Update `DeleteItemsCommand` to orphan children on parent delete.
5. Add keyboard shortcuts (Left/Right for collapse, Cmd+Shift+N for add subtask).
6. Tests: undo/redo for add subtask, reparent, delete parent.

### Phase 4: Drag-and-drop (higher risk)

1. Enable internal drag-and-drop on `TodoTableWidget`.
2. Implement `dropEvent` with reparent logic.
3. Add visual drop target highlighting.
4. Validate constraints (no grandchildren, no self-parent).
5. Tests: drag reparent, drag to top-level, drag validation.

### Phase 5: Filter integration

1. Update `_apply_filter()` to pull in parent as context row when child matches.
2. Update text search to show parent when child matches.
3. Handle orphan display when parent is filtered out.
4. Tests: filter with subtasks, search with subtasks.

## Not In Scope (future work)

- **Multi-level nesting**: Explicitly excluded. One level only.
- **Subtask templates**: Pre-defined sets of subtasks for common workflows (e.g., "Code Review" auto-creates "Read PR", "Test locally", "Leave comments").
- **Subtask-level sync rules**: All items in a list sync together. No per-subtask sync control.
- **Subtask progress as percentage**: The badge shows `[3/5]`, not `60%`. Percentage adds no information for small counts and is harder to read.
- **Drag to reorder within siblings**: Children are sorted by the active sort key, not by manual order. Manual ordering is a separate feature that would require a `sort_order` field on all items.
- **Collapse persistence**: Collapsed state is session-local. Persisting it would require a separate table or config entry mapping parent UUIDs to collapsed state, which is not worth the complexity.
