"""models.py

Sync-aware data models with UUIDs and Lamport timestamps.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

from .logger import Logger

logger = Logger(__name__)


def _now_timestamp() -> int:
    """Get current timestamp in milliseconds."""
    return int(time.time() * 1000)


def _uuid_factory() -> UUID:
    """Generate a new UUID."""
    return uuid4()


@dataclass
class TodoItem:
    """A single to-do item with sync support."""

    id: UUID = field(default_factory=_uuid_factory)
    reminder: str = ""
    priority: int = 2  # 1=High, 2=Normal, 3=Low
    complete: bool = False
    due_date: date | None = None
    created_at: int = field(default_factory=_now_timestamp)
    updated_at: int = field(default_factory=_now_timestamp)
    deleted: bool = False  # Tombstone for sync

    def mark_updated(self) -> None:
        """Mark item as updated with current timestamp."""
        self.updated_at = _now_timestamp()

    def mark_deleted(self) -> None:
        """Mark item as deleted (tombstone)."""
        self.deleted = True
        self.mark_updated()

    def toggle_complete(self) -> None:
        """Toggle completion status."""
        self.complete = not self.complete
        self.mark_updated()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "reminder": self.reminder,
            "priority": self.priority,
            "complete": self.complete,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted": self.deleted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodoItem:
        """Create from dictionary."""
        due_date_str = data.get("due_date")
        due_date = date.fromisoformat(due_date_str) if due_date_str else None
        return cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            reminder=data.get("reminder", ""),
            priority=data.get("priority", 2),
            complete=data.get("complete", False),
            due_date=due_date,
            created_at=data.get("created_at", _now_timestamp()),
            updated_at=data.get("updated_at", _now_timestamp()),
            deleted=data.get("deleted", False),
        )

    @classmethod
    def from_legacy(cls, legacy: dict[str, Any]) -> TodoItem:
        """Create from legacy format (v0.2.x)."""
        now = _now_timestamp()
        return cls(
            id=uuid4(),
            reminder=legacy.get("reminder", ""),
            priority=legacy.get("priority", 2),
            complete=legacy.get("complete", False),
            due_date=None,
            created_at=now,
            updated_at=now,
            deleted=False,
        )


@dataclass
class TodoList:
    """A list of to-do items with sync support."""

    id: UUID = field(default_factory=_uuid_factory)
    name: str = ""
    items: dict[UUID, TodoItem] = field(default_factory=dict)
    created_at: int = field(default_factory=_now_timestamp)
    updated_at: int = field(default_factory=_now_timestamp)
    deleted: bool = False  # Tombstone for sync
    private: bool = False  # Private lists excluded from sync

    def mark_updated(self) -> None:
        """Mark list as updated with current timestamp."""
        self.updated_at = _now_timestamp()

    def mark_deleted(self) -> None:
        """Mark list as deleted (tombstone)."""
        self.deleted = True
        self.mark_updated()

    def toggle_private(self) -> None:
        """Toggle private status."""
        self.private = not self.private
        self.mark_updated()

    def add_item(self, item: TodoItem) -> None:
        """Add an item to the list."""
        self.items[item.id] = item
        self.mark_updated()

    def remove_item(self, item_id: UUID) -> bool:
        """Remove an item from the list (marks as deleted)."""
        if item_id in self.items:
            self.items[item_id].mark_deleted()
            self.mark_updated()
            return True
        return False

    def get_item(self, item_id: UUID) -> TodoItem | None:
        """Get an item by ID."""
        return self.items.get(item_id)

    def active_items(self) -> Iterator[TodoItem]:
        """Iterate over non-deleted items."""
        for item in self.items.values():
            if not item.deleted:
                yield item

    def active_item_count(self) -> int:
        """Count non-deleted items."""
        return sum(1 for _ in self.active_items())

    def completed_count(self) -> int:
        """Count completed non-deleted items."""
        return sum(1 for item in self.active_items() if item.complete)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "name": self.name,
            "items": {str(k): v.to_dict() for k, v in self.items.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted": self.deleted,
            "private": self.private,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodoList:
        """Create from dictionary."""
        items = {}
        for _, v in data.get("items", {}).items():
            item = TodoItem.from_dict(v)
            items[item.id] = item

        return cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            name=data.get("name", ""),
            items=items,
            created_at=data.get("created_at", _now_timestamp()),
            updated_at=data.get("updated_at", _now_timestamp()),
            deleted=data.get("deleted", False),
            private=data.get("private", False),
        )

    @classmethod
    def from_legacy(cls, name: str, legacy_items: list[dict[str, Any]]) -> TodoList:
        """Create from legacy format (v0.2.x)."""
        now = _now_timestamp()
        items = {}
        for legacy in legacy_items:
            item = TodoItem.from_legacy(legacy)
            items[item.id] = item

        return cls(
            id=uuid4(),
            name=name,
            items=items,
            created_at=now,
            updated_at=now,
            deleted=False,
        )


@dataclass
class Database:
    """Complete database with all lists."""

    lists: dict[UUID, TodoList] = field(default_factory=dict)
    active_list_id: UUID | None = None
    schema_version: int = 2

    @property
    def active_list(self) -> TodoList | None:
        """Get the currently active list."""
        if self.active_list_id is None:
            return None
        return self.lists.get(self.active_list_id)

    def set_active_list(self, list_id: UUID) -> bool:
        """Set the active list by ID."""
        if list_id in self.lists:
            self.active_list_id = list_id
            return True
        return False

    def set_active_list_by_name(self, name: str) -> bool:
        """Set the active list by name."""
        for lst in self.lists.values():
            if lst.name == name and not lst.deleted:
                self.active_list_id = lst.id
                return True
        return False

    def add_list(self, lst: TodoList) -> None:
        """Add a list to the database."""
        self.lists[lst.id] = lst

    def get_list(self, list_id: UUID) -> TodoList | None:
        """Get a list by ID."""
        return self.lists.get(list_id)

    def get_list_by_name(self, name: str) -> TodoList | None:
        """Get a list by name."""
        for lst in self.lists.values():
            if lst.name == name and not lst.deleted:
                return lst
        return None

    def active_lists(self) -> Iterator[TodoList]:
        """Iterate over non-deleted lists."""
        for lst in self.lists.values():
            if not lst.deleted:
                yield lst

    def list_names(self) -> list[str]:
        """Get names of all non-deleted lists."""
        return [lst.name for lst in self.active_lists()]

    def total_items(self) -> int:
        """Count total non-deleted items across all lists."""
        return sum(lst.active_item_count() for lst in self.active_lists())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "schema_version": self.schema_version,
            "active_list_id": str(self.active_list_id) if self.active_list_id else None,
            "lists": {str(k): v.to_dict() for k, v in self.lists.items()},
        }

    def to_dict_for_sync(self) -> dict[str, Any]:
        """Convert to dictionary for sync, excluding private lists."""
        return {
            "schema_version": self.schema_version,
            "active_list_id": str(self.active_list_id) if self.active_list_id else None,
            "lists": {str(k): v.to_dict() for k, v in self.lists.items() if not v.private},
        }

    def to_dict_for_device(self, allowed_list_ids: set[UUID]) -> dict[str, Any]:
        """Convert to dictionary for sync with a specific device.

        Args:
            allowed_list_ids: Set of list IDs that should be included

        Returns:
            Dictionary with only the allowed lists
        """
        return {
            "schema_version": self.schema_version,
            "active_list_id": str(self.active_list_id) if self.active_list_id else None,
            "lists": {
                str(k): v.to_dict()
                for k, v in self.lists.items()
                if k in allowed_list_ids and not v.private
            },
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def to_bytes(self) -> bytes:
        """Serialize to bytes for network transfer."""
        return self.to_json().encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Database:
        """Create from dictionary."""
        lists = {}
        for _, v in data.get("lists", {}).items():
            lst = TodoList.from_dict(v)
            lists[lst.id] = lst

        active_id = data.get("active_list_id")
        if active_id and isinstance(active_id, str):
            active_id = UUID(active_id)

        return cls(
            lists=lists,
            active_list_id=active_id,
            schema_version=data.get("schema_version", 2),
        )

    @classmethod
    def from_json(cls, json_str: str) -> Database:
        """Create from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> Database:
        """Create from bytes."""
        return cls.from_json(data.decode("utf-8"))

    @classmethod
    def from_legacy(cls, legacy_data: dict[str, list[dict[str, Any]]]) -> Database:
        """Create from legacy format (v0.2.x).

        Legacy format is: {"list_name": [{"reminder": ..., "priority": ..., "complete": ...}, ...]}
        """
        db = cls()
        for name, items in legacy_data.items():
            lst = TodoList.from_legacy(name, items)
            db.add_list(lst)

        # Set first list as active if any exist
        if db.lists:
            db.active_list_id = next(iter(db.lists.keys()))

        return db


@dataclass
class Device:
    """A known sync device identified by fingerprint."""

    id: UUID = field(default_factory=_uuid_factory)
    fingerprint: str = ""
    name: str = ""
    first_seen: int = field(default_factory=_now_timestamp)
    last_seen: int = field(default_factory=_now_timestamp)
    last_address: str | None = None
    trust_level: str = "normal"  # normal, trusted, blocked

    def update_seen(self, address: str | None = None) -> None:
        """Update last seen timestamp and optionally address."""
        self.last_seen = _now_timestamp()
        if address:
            self.last_address = address

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "fingerprint": self.fingerprint,
            "name": self.name,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_address": self.last_address,
            "trust_level": self.trust_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Device:
        """Create from dictionary."""
        return cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            fingerprint=data.get("fingerprint", ""),
            name=data.get("name", ""),
            first_seen=data.get("first_seen", _now_timestamp()),
            last_seen=data.get("last_seen", _now_timestamp()),
            last_address=data.get("last_address"),
            trust_level=data.get("trust_level", "normal"),
        )


@dataclass
class SyncGroup:
    """A group of devices for organized sync operations."""

    id: UUID = field(default_factory=_uuid_factory)
    name: str = ""
    created_at: int = field(default_factory=_now_timestamp)
    updated_at: int = field(default_factory=_now_timestamp)

    def mark_updated(self) -> None:
        """Mark group as updated with current timestamp."""
        self.updated_at = _now_timestamp()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncGroup:
        """Create from dictionary."""
        return cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            name=data.get("name", ""),
            created_at=data.get("created_at", _now_timestamp()),
            updated_at=data.get("updated_at", _now_timestamp()),
        )


@dataclass
class ListSyncRule:
    """Rule defining which groups a list syncs to."""

    list_id: UUID = field(default_factory=_uuid_factory)
    group_id: UUID = field(default_factory=_uuid_factory)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "list_id": str(self.list_id),
            "group_id": str(self.group_id),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ListSyncRule:
        """Create from dictionary."""
        return cls(
            list_id=UUID(data["list_id"]) if isinstance(data["list_id"], str) else data["list_id"],
            group_id=UUID(data["group_id"])
            if isinstance(data["group_id"], str)
            else data["group_id"],
        )


@dataclass
class PendingSync:
    """A queued sync operation for an offline device."""

    id: UUID = field(default_factory=_uuid_factory)
    device_id: UUID = field(default_factory=_uuid_factory)
    list_ids: list[UUID] = field(default_factory=list)  # Empty = all applicable lists
    created_at: int = field(default_factory=_now_timestamp)
    expires_at: int = field(
        default_factory=lambda: _now_timestamp() + 7 * 24 * 60 * 60 * 1000
    )  # 7 days
    attempts: int = 0
    last_attempt: int | None = None

    def is_expired(self) -> bool:
        """Check if this pending sync has expired."""
        return _now_timestamp() > self.expires_at

    def record_attempt(self) -> None:
        """Record a sync attempt."""
        self.attempts += 1
        self.last_attempt = _now_timestamp()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "device_id": str(self.device_id),
            "list_ids": [str(lid) for lid in self.list_ids],
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "attempts": self.attempts,
            "last_attempt": self.last_attempt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingSync:
        """Create from dictionary."""
        list_ids = [UUID(lid) if isinstance(lid, str) else lid for lid in data.get("list_ids", [])]
        return cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            device_id=UUID(data["device_id"])
            if isinstance(data["device_id"], str)
            else data["device_id"],
            list_ids=list_ids,
            created_at=data.get("created_at", _now_timestamp()),
            expires_at=data.get("expires_at", _now_timestamp() + 7 * 24 * 60 * 60 * 1000),
            attempts=data.get("attempts", 0),
            last_attempt=data.get("last_attempt"),
        )


def create_todo_item(reminder: str, priority: int = 2, due_date: date | None = None) -> TodoItem:
    """Create a new todo item."""
    return TodoItem(reminder=reminder, priority=priority, due_date=due_date)


def create_todo_list(name: str) -> TodoList:
    """Create a new todo list."""
    return TodoList(name=name)


def create_device(fingerprint: str, name: str = "") -> Device:
    """Create a new device."""
    return Device(fingerprint=fingerprint, name=name)


def create_sync_group(name: str) -> SyncGroup:
    """Create a new sync group."""
    return SyncGroup(name=name)


def create_pending_sync(device_id: UUID, list_ids: list[UUID] | None = None) -> PendingSync:
    """Create a new pending sync for an offline device."""
    return PendingSync(device_id=device_id, list_ids=list_ids or [])


def format_due_date(due_date: date | None, complete: bool = False) -> str:
    """Format due date for display: 'Today', 'Tomorrow', 'Overdue (2d)', 'Jan 15'.

    Args:
        due_date: The due date to format, or None.
        complete: Whether the item is completed. Completed items don't show as overdue.
    """
    if due_date is None:
        return ""
    today = date.today()
    delta = (due_date - today).days
    if delta < 0:
        if complete:
            # Completed items show the date, not "Overdue"
            if due_date.year == today.year:
                return due_date.strftime("%b %d")
            return due_date.strftime("%b %d, %Y")
        return f"Overdue ({abs(delta)}d)"
    elif delta == 0:
        return "Today"
    elif delta == 1:
        return "Tomorrow"
    elif delta < 7:
        return due_date.strftime("%A")  # Day name (unambiguous within 2-6 days)
    elif due_date.year == today.year:
        return due_date.strftime("%b %d")
    else:
        return due_date.strftime("%b %d, %Y")


def is_overdue(due_date: date | None) -> bool:
    """Check if the due date is in the past."""
    return due_date is not None and due_date < date.today()


def is_due_today(due_date: date | None) -> bool:
    """Check if the due date is today."""
    return due_date is not None and due_date == date.today()


def is_due_this_week(due_date: date | None) -> bool:
    """Check if the due date is within the next 7 days."""
    if due_date is None:
        return False
    today = date.today()
    return today <= due_date <= today + timedelta(days=7)
