"""sync_engine.py

Synchronization engine with Last-Write-Wins merge algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .logger import Logger
from .models import Database, TodoItem, TodoList

logger = Logger(__name__)


@dataclass
class ConflictInfo:
    """Information about a merge conflict."""

    item_type: str  # "list" or "item"
    item_id: UUID
    list_id: UUID | None  # For items, the containing list
    local_value: Any
    remote_value: Any
    winner: str  # "local" or "remote"
    field: str  # Which field conflicted


@dataclass
class MergeResult:
    """Result of a merge operation."""

    merged_db: Database
    conflicts: list[ConflictInfo] = field(default_factory=list)
    added_lists: list[UUID] = field(default_factory=list)
    updated_lists: list[UUID] = field(default_factory=list)
    deleted_lists: list[UUID] = field(default_factory=list)
    added_items: list[tuple[UUID, UUID]] = field(default_factory=list)  # (list_id, item_id)
    updated_items: list[tuple[UUID, UUID]] = field(default_factory=list)
    deleted_items: list[tuple[UUID, UUID]] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        """Check if there were any conflicts."""
        return len(self.conflicts) > 0

    @property
    def changes_made(self) -> bool:
        """Check if any changes were made."""
        return (
            len(self.added_lists) > 0
            or len(self.updated_lists) > 0
            or len(self.deleted_lists) > 0
            or len(self.added_items) > 0
            or len(self.updated_items) > 0
            or len(self.deleted_items) > 0
        )


class SyncEngine:
    """Handles synchronization and merging of databases."""

    def __init__(self):
        self._tombstone_ttl_ms = 7 * 24 * 60 * 60 * 1000  # 7 days in ms

    def merge(self, local: Database, remote: Database) -> MergeResult:
        """Merge remote database into local using Last-Write-Wins.

        The merge algorithm:
        1. For each list in remote:
           - If not in local, add it
           - If in local, merge using LWW on updated_at
        2. For each item in remote lists:
           - If not in local list, add it
           - If in local, merge using LWW on updated_at
        3. Track conflicts for notification

        Args:
            local: The local database
            remote: The remote database to merge in

        Returns:
            MergeResult with merged database and conflict info
        """
        result = MergeResult(merged_db=local)

        # Merge lists
        for remote_list in remote.lists.values():
            if remote_list.id in local.lists:
                # Merge existing list
                self._merge_list(
                    local.lists[remote_list.id],
                    remote_list,
                    result,
                )
            else:
                # Add new list from remote
                local.lists[remote_list.id] = remote_list
                result.added_lists.append(remote_list.id)
                logger.log.info("Added list from remote: %s", remote_list.name)

        # Garbage collect old tombstones
        self._garbage_collect(local)

        logger.log.info(
            "Merge complete: %d lists added, %d updated, %d deleted; "
            "%d items added, %d updated, %d deleted; %d conflicts",
            len(result.added_lists),
            len(result.updated_lists),
            len(result.deleted_lists),
            len(result.added_items),
            len(result.updated_items),
            len(result.deleted_items),
            len(result.conflicts),
        )

        return result

    def _merge_list(
        self,
        local_list: TodoList,
        remote_list: TodoList,
        result: MergeResult,
    ) -> None:
        """Merge a remote list into a local list."""
        # Check if list metadata changed
        if remote_list.updated_at > local_list.updated_at:
            # Remote wins for list metadata
            if local_list.name != remote_list.name:
                result.conflicts.append(
                    ConflictInfo(
                        item_type="list",
                        item_id=local_list.id,
                        list_id=None,
                        local_value=local_list.name,
                        remote_value=remote_list.name,
                        winner="remote",
                        field="name",
                    )
                )
                local_list.name = remote_list.name

            if local_list.deleted != remote_list.deleted:
                local_list.deleted = remote_list.deleted
                if remote_list.deleted:
                    result.deleted_lists.append(local_list.id)
                else:
                    result.updated_lists.append(local_list.id)

            local_list.updated_at = remote_list.updated_at
            if local_list.id not in result.deleted_lists:
                result.updated_lists.append(local_list.id)

        # Merge items
        for remote_item in remote_list.items.values():
            if remote_item.id in local_list.items:
                self._merge_item(
                    local_list.items[remote_item.id],
                    remote_item,
                    local_list.id,
                    result,
                )
            else:
                # Add new item from remote
                local_list.items[remote_item.id] = remote_item
                result.added_items.append((local_list.id, remote_item.id))
                logger.log.info("Added item from remote: %s", remote_item.reminder[:50])

    def _merge_item(
        self,
        local_item: TodoItem,
        remote_item: TodoItem,
        list_id: UUID,
        result: MergeResult,
    ) -> None:
        """Merge a remote item into a local item using LWW."""
        if remote_item.updated_at <= local_item.updated_at:
            # Local is newer or same, keep local
            return

        # Remote is newer, check each field
        changes_made = False

        if local_item.reminder != remote_item.reminder:
            result.conflicts.append(
                ConflictInfo(
                    item_type="item",
                    item_id=local_item.id,
                    list_id=list_id,
                    local_value=local_item.reminder,
                    remote_value=remote_item.reminder,
                    winner="remote",
                    field="reminder",
                )
            )
            local_item.reminder = remote_item.reminder
            changes_made = True

        if local_item.priority != remote_item.priority:
            result.conflicts.append(
                ConflictInfo(
                    item_type="item",
                    item_id=local_item.id,
                    list_id=list_id,
                    local_value=local_item.priority,
                    remote_value=remote_item.priority,
                    winner="remote",
                    field="priority",
                )
            )
            local_item.priority = remote_item.priority
            changes_made = True

        if local_item.complete != remote_item.complete:
            result.conflicts.append(
                ConflictInfo(
                    item_type="item",
                    item_id=local_item.id,
                    list_id=list_id,
                    local_value=local_item.complete,
                    remote_value=remote_item.complete,
                    winner="remote",
                    field="complete",
                )
            )
            local_item.complete = remote_item.complete
            changes_made = True

        if local_item.deleted != remote_item.deleted:
            local_item.deleted = remote_item.deleted
            if remote_item.deleted:
                result.deleted_items.append((list_id, local_item.id))
            changes_made = True

        if changes_made:
            local_item.updated_at = remote_item.updated_at
            if not local_item.deleted:
                result.updated_items.append((list_id, local_item.id))

    def _garbage_collect(self, db: Database) -> None:
        """Remove old tombstones that have passed TTL."""
        import time

        now = int(time.time() * 1000)
        cutoff = now - self._tombstone_ttl_ms

        # Collect lists to fully remove
        lists_to_remove = []
        for lst in db.lists.values():
            if lst.deleted and lst.updated_at < cutoff:
                lists_to_remove.append(lst.id)
            else:
                # Collect items to fully remove
                items_to_remove = []
                for item in lst.items.values():
                    if item.deleted and item.updated_at < cutoff:
                        items_to_remove.append(item.id)

                for item_id in items_to_remove:
                    del lst.items[item_id]

        for list_id in lists_to_remove:
            del db.lists[list_id]

        if lists_to_remove or any(db.lists.values()):
            logger.log.info(
                "Garbage collected %d lists and items older than TTL",
                len(lists_to_remove),
            )

    def diff(self, local: Database, remote: Database) -> dict[str, Any]:
        """Calculate the difference between two databases.

        Returns a summary of what would change if remote were merged into local.
        """
        diff = {
            "new_lists": [],
            "updated_lists": [],
            "deleted_lists": [],
            "new_items": [],
            "updated_items": [],
            "deleted_items": [],
        }

        for remote_list in remote.lists.values():
            if remote_list.id not in local.lists:
                diff["new_lists"].append(remote_list.name)
            else:
                local_list = local.lists[remote_list.id]
                if remote_list.updated_at > local_list.updated_at:
                    if remote_list.deleted and not local_list.deleted:
                        diff["deleted_lists"].append(local_list.name)
                    else:
                        diff["updated_lists"].append(local_list.name)

                # Check items
                for remote_item in remote_list.items.values():
                    if remote_item.id not in local_list.items:
                        diff["new_items"].append(remote_item.reminder[:50])
                    else:
                        local_item = local_list.items[remote_item.id]
                        if remote_item.updated_at > local_item.updated_at:
                            if remote_item.deleted and not local_item.deleted:
                                diff["deleted_items"].append(local_item.reminder[:50])
                            else:
                                diff["updated_items"].append(local_item.reminder[:50])

        return diff


# Global sync engine instance
_sync_engine: SyncEngine | None = None


def get_sync_engine() -> SyncEngine:
    """Get the global sync engine instance."""
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = SyncEngine()
    return _sync_engine


def merge_databases(local: Database, remote: Database) -> MergeResult:
    """Merge remote database into local."""
    return get_sync_engine().merge(local, remote)
