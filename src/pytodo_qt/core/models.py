"""models.py

Sync-aware data models with UUIDs and Lamport timestamps.
"""

from __future__ import annotations

import calendar
import json
import time as _time_mod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

from .logger import Logger

logger = Logger(__name__)


def _now_timestamp() -> int:
    """Get current timestamp in milliseconds."""
    return int(_time_mod.time() * 1000)


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
    due_time: time | None = None  # Optional time-of-day for due date
    tags: list[str] = field(default_factory=list)  # Free-form text tags
    recurrence_type: str | None = None  # "daily", "weekly", "monthly", "yearly"
    recurrence_interval: int = 1  # Every N units
    recurrence_end_date: date | None = None  # Optional end date
    recurrence_end_count: int | None = None  # Optional max occurrences
    recurrence_count: int = 0  # Completed occurrences so far
    missed_recurrences: int = 0  # Auto-advanced overdue occurrences
    time_spent: int = 0  # Total seconds of completed focus sessions
    pomodoro_count: int = 0  # Completed focus sessions
    estimated_pomodoros: int = 0  # User estimate (0 = no estimate)
    created_at: int = field(default_factory=_now_timestamp)
    updated_at: int = field(default_factory=_now_timestamp)
    deleted: bool = False  # Tombstone for sync
    parent_id: UUID | None = None  # None = top-level item
    board_column: str = ""  # Kanban column assignment

    @property
    def is_subtask(self) -> bool:
        """Check if this item is a subtask (has a parent)."""
        return self.parent_id is not None

    @property
    def is_recurring(self) -> bool:
        """Check if this item has a recurrence rule."""
        return self.recurrence_type is not None

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
            "due_time": self.due_time.isoformat() if self.due_time else None,
            "tags": self.tags,
            "recurrence_type": self.recurrence_type,
            "recurrence_interval": self.recurrence_interval,
            "recurrence_end_date": (
                self.recurrence_end_date.isoformat() if self.recurrence_end_date else None
            ),
            "recurrence_end_count": self.recurrence_end_count,
            "recurrence_count": self.recurrence_count,
            "missed_recurrences": self.missed_recurrences,
            "time_spent": self.time_spent,
            "pomodoro_count": self.pomodoro_count,
            "estimated_pomodoros": self.estimated_pomodoros,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted": self.deleted,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "board_column": self.board_column,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodoItem:
        """Create from dictionary."""
        due_date_str = data.get("due_date")
        due_date = date.fromisoformat(due_date_str) if due_date_str else None
        due_time_str = data.get("due_time")
        due_time = time.fromisoformat(due_time_str) if due_time_str else None
        end_date_str = data.get("recurrence_end_date")
        recurrence_end_date = date.fromisoformat(end_date_str) if end_date_str else None
        parent_id_str = data.get("parent_id")
        parent_id = UUID(parent_id_str) if parent_id_str else None
        return cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            reminder=data.get("reminder", ""),
            priority=data.get("priority", 2),
            complete=data.get("complete", False),
            due_date=due_date,
            due_time=due_time,
            tags=data.get("tags", []),
            recurrence_type=data.get("recurrence_type"),
            recurrence_interval=data.get("recurrence_interval", 1),
            recurrence_end_date=recurrence_end_date,
            recurrence_end_count=data.get("recurrence_end_count"),
            recurrence_count=data.get("recurrence_count", 0),
            missed_recurrences=data.get("missed_recurrences", 0),
            time_spent=data.get("time_spent", 0),
            pomodoro_count=data.get("pomodoro_count", 0),
            estimated_pomodoros=data.get("estimated_pomodoros", 0),
            created_at=data.get("created_at", _now_timestamp()),
            updated_at=data.get("updated_at", _now_timestamp()),
            deleted=data.get("deleted", False),
            parent_id=parent_id,
            board_column=data.get("board_column", ""),
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
    board_columns: list[str] = field(default_factory=lambda: ["To Do", "In Progress", "Done"])
    wip_limits: dict[str, int] = field(default_factory=dict)

    def get_wip_limit(self, column: str) -> int:
        """Get WIP limit for a column (0 = no limit)."""
        return self.wip_limits.get(column, 0)

    def set_wip_limit(self, column: str, limit: int) -> None:
        """Set WIP limit for a column (0 to remove)."""
        if limit <= 0:
            self.wip_limits.pop(column, None)
        else:
            self.wip_limits[column] = limit

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

    def get_children(self, parent_id: UUID) -> list[TodoItem]:
        """Get active children of a parent item, sorted by created_at."""
        return sorted(
            (i for i in self.active_items() if i.parent_id == parent_id),
            key=lambda i: i.created_at,
        )

    def child_count(self, parent_id: UUID) -> int:
        """Count active children of a parent item."""
        return sum(1 for i in self.active_items() if i.parent_id == parent_id)

    def child_completed_count(self, parent_id: UUID) -> int:
        """Count completed active children of a parent item."""
        return sum(1 for i in self.active_items() if i.parent_id == parent_id and i.complete)

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
            "board_columns": self.board_columns,
            "wip_limits": self.wip_limits,
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
            board_columns=data.get("board_columns", ["To Do", "In Progress", "Done"]),
            wip_limits=data.get("wip_limits", {}),
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
    focus_sessions: list[FocusSession] = field(default_factory=list)
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

    def resolve_name_collision(self, name: str, peer_name: str = "") -> str:
        """Return a unique list name, renaming if it collides with an existing list.

        If no collision, returns the original name unchanged. Otherwise appends
        a suffix like "(from PeerName)" or "(synced)" to disambiguate.
        """
        existing = {lst.name for lst in self.lists.values() if not lst.deleted}
        if name not in existing:
            return name
        suffix = f"from {peer_name}" if peer_name else "synced"
        candidate = f"{name} ({suffix})"
        if candidate not in existing:
            return candidate
        counter = 2
        while f"{candidate} {counter}" in existing:
            counter += 1
        return f"{candidate} {counter}"

    def total_items(self) -> int:
        """Count total non-deleted items across all lists."""
        return sum(lst.active_item_count() for lst in self.active_lists())

    def total_completed(self) -> int:
        """Count total completed non-deleted items across all lists."""
        return sum(lst.completed_count() for lst in self.active_lists())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "schema_version": self.schema_version,
            "active_list_id": str(self.active_list_id) if self.active_list_id else None,
            "lists": {str(k): v.to_dict() for k, v in self.lists.items()},
            "focus_sessions": [s.to_dict() for s in self.focus_sessions],
        }

    def to_dict_for_sync(self) -> dict[str, Any]:
        """Convert to dictionary for sync, excluding private lists."""
        return {
            "schema_version": self.schema_version,
            "active_list_id": str(self.active_list_id) if self.active_list_id else None,
            "lists": {str(k): v.to_dict() for k, v in self.lists.items() if not v.private},
            "focus_sessions": [s.to_dict() for s in self.focus_sessions],
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
            "focus_sessions": [
                s.to_dict() for s in self.focus_sessions if s.list_id in allowed_list_ids
            ],
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

        sessions = [FocusSession.from_dict(s) for s in data.get("focus_sessions", [])]

        active_id = data.get("active_list_id")
        if active_id and isinstance(active_id, str):
            active_id = UUID(active_id)

        return cls(
            lists=lists,
            focus_sessions=sessions,
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
    estimated_pomodoros: int = 0,
    board_column: str = "",
) -> TodoItem:
    """Create a new todo item."""
    return TodoItem(
        reminder=reminder,
        priority=priority,
        due_date=due_date,
        due_time=due_time,
        tags=tags or [],
        recurrence_type=recurrence_type,
        recurrence_interval=recurrence_interval,
        recurrence_end_date=recurrence_end_date,
        recurrence_end_count=recurrence_end_count,
        parent_id=parent_id,
        estimated_pomodoros=estimated_pomodoros,
        board_column=board_column,
    )


def create_todo_list(name: str) -> TodoList:
    """Create a new todo list."""
    return TodoList(name=name)


def create_device(fingerprint: str, name: str = "") -> Device:
    """Create a new device."""
    return Device(fingerprint=fingerprint, name=name)


def create_sync_group(name: str) -> SyncGroup:
    """Create a new sync group."""
    return SyncGroup(name=name)


@dataclass
class FocusSession:
    """A recorded focus timer session."""

    id: UUID = field(default_factory=_uuid_factory)
    item_id: UUID = field(default_factory=_uuid_factory)
    list_id: UUID = field(default_factory=_uuid_factory)
    start_time: str = ""  # ISO 8601 datetime
    end_time: str = ""  # ISO 8601 datetime
    duration_seconds: int = 0
    completed: bool = True  # False if interrupted
    session_type: str = "work"  # "work" or "break"
    date: str = ""  # YYYY-MM-DD for easy grouping

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "list_id": str(self.list_id),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "completed": self.completed,
            "session_type": self.session_type,
            "date": self.date,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FocusSession:
        """Create from dictionary."""
        return cls(
            id=UUID(data["id"]) if isinstance(data["id"], str) else data["id"],
            item_id=UUID(data["item_id"]) if isinstance(data["item_id"], str) else data["item_id"],
            list_id=UUID(data["list_id"]) if isinstance(data["list_id"], str) else data["list_id"],
            start_time=data.get("start_time", ""),
            end_time=data.get("end_time", ""),
            duration_seconds=data.get("duration_seconds", 0),
            completed=data.get("completed", True),
            session_type=data.get("session_type", "work"),
            date=data.get("date", ""),
        )


def create_focus_session(
    item_id: UUID,
    list_id: UUID,
    start_time: str,
    end_time: str,
    duration_seconds: int,
    completed: bool = True,
    session_type: str = "work",
    date: str = "",
) -> FocusSession:
    """Create a new focus session record."""
    return FocusSession(
        item_id=item_id,
        list_id=list_id,
        start_time=start_time,
        end_time=end_time,
        duration_seconds=duration_seconds,
        completed=completed,
        session_type=session_type,
        date=date,
    )


def create_pending_sync(device_id: UUID, list_ids: list[UUID] | None = None) -> PendingSync:
    """Create a new pending sync for an offline device."""
    return PendingSync(device_id=device_id, list_ids=list_ids or [])


def _format_time(t: time, time_format: str = "system") -> str:
    """Format a time value respecting the configured format."""
    if time_format == "24h":
        return t.strftime("%H:%M")
    elif time_format == "12h":
        h = t.hour % 12 or 12
        return f"{h}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"
    else:  # "system" — detect from locale
        try:
            formatted = t.strftime("%X")  # Locale time, e.g. "14:30:00"
            # Strip seconds — find last colon-separated group of exactly 2 digits
            parts = formatted.rsplit(":", 1)
            if len(parts) == 2 and len(parts[1]) <= 2:
                return parts[0]
            # Handle "2:30:00 PM" → "2:30 PM"
            return parts[0] + parts[1][2:]
        except Exception:
            return t.strftime("%H:%M")


def _format_overdue_delta(due_date: date, due_time: time | None = None) -> str:
    """Format overdue duration. Two-unit for timed items, single-unit for date-only."""
    now = datetime.now()
    if due_time is not None:
        due_dt = datetime.combine(due_date, due_time)
    else:
        due_dt = datetime.combine(due_date + timedelta(days=1), time(0, 0))
    if now <= due_dt:
        return ""
    delta = now - due_dt
    total_minutes = int(delta.total_seconds() // 60)
    days = delta.days
    hours = (total_minutes % (24 * 60)) // 60
    minutes = total_minutes % 60
    if due_time is None:
        return f"Overdue ({(date.today() - due_date).days}d)"
    if days > 0:
        return f"Overdue ({days}d {hours}h)" if hours else f"Overdue ({days}d)"
    elif hours > 0:
        return f"Overdue ({hours}h {minutes}m)" if minutes else f"Overdue ({hours}h)"
    else:
        return f"Overdue ({max(minutes, 1)}m)"


def format_due_date(
    due_date: date | None,
    complete: bool = False,
    due_time: time | None = None,
    time_format: str = "system",
) -> str:
    """Format due date for display: 'Today', 'Tomorrow', 'Overdue (2d)', 'Jan 15'.

    Args:
        due_date: The due date to format, or None.
        complete: Whether the item is completed. Completed items always show
            the absolute date instead of urgency text like "Today" or "Overdue".
        due_time: Optional time-of-day. When set, appended to date strings and
            enables sub-day overdue granularity.
        time_format: Time display format — "system", "12h", or "24h".
    """
    if due_date is None:
        return ""
    today = date.today()
    time_suffix = f" {_format_time(due_time, time_format)}" if due_time else ""
    if complete:
        if due_date.year == today.year:
            return due_date.strftime("%b %d") + time_suffix
        return due_date.strftime("%b %d, %Y") + time_suffix
    delta = (due_date - today).days
    if delta < 0:
        return _format_overdue_delta(due_date, due_time)
    elif delta == 0:
        # Check if timed item is past its time today
        if due_time is not None and datetime.now().time() > due_time:
            return _format_overdue_delta(due_date, due_time)
        return "Today" + time_suffix
    elif delta == 1:
        return "Tomorrow" + time_suffix
    elif delta < 7:
        return due_date.strftime("%A") + time_suffix
    elif due_date.year == today.year:
        return due_date.strftime("%b %d") + time_suffix
    else:
        return due_date.strftime("%b %d, %Y") + time_suffix


def is_overdue(due_date: date | None, due_time: time | None = None) -> bool:
    """Check if the due date (and optional time) is in the past."""
    if due_date is None:
        return False
    today = date.today()
    if due_date < today:
        return True
    if due_date == today and due_time is not None:
        return datetime.now().time() > due_time
    return False


def is_due_today(due_date: date | None) -> bool:
    """Check if the due date is today."""
    return due_date is not None and due_date == date.today()


def is_due_this_week(due_date: date | None) -> bool:
    """Check if the due date is within the next 7 days."""
    if due_date is None:
        return False
    today = date.today()
    return today <= due_date <= today + timedelta(days=7)


def logical_today(day_start_hour: int = 0) -> date:
    """Return the logical current date respecting the user's day boundary.

    If the current hour is before day_start_hour, the logical day is
    still yesterday. A night owl with day_start_hour=4 sees 2am as
    part of the previous day.

    Uses the module-level ``date.today()`` so tests can monkeypatch it,
    and ``datetime.now().hour`` for the hour check.
    """
    today = date.today()
    if day_start_hour > 0 and datetime.now().hour < day_start_hour:
        return today - timedelta(days=1)
    return today


def compute_next_due_date(
    current_due: date,
    recurrence_type: str,
    interval: int = 1,
) -> date:
    """Compute the next due date for a recurring item.

    Calculates from today to avoid cascading completions for overdue items.
    Preserves day-of-week for weekly and day-of-month for monthly patterns.
    For minutely recurrence, returns the date component of the next occurrence.
    """
    today = date.today()
    if recurrence_type == "minutely":
        next_dt = datetime.now() + timedelta(minutes=interval)
        return next_dt.date()
    elif recurrence_type == "daily":
        return today + timedelta(days=interval)
    elif recurrence_type == "weekly":
        original_weekday = current_due.weekday()
        days_ahead = original_weekday - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7 * interval
        elif interval > 1:
            days_ahead += 7 * (interval - 1)
        return today + timedelta(days=days_ahead)
    elif recurrence_type == "monthly":
        target_month = today.month + interval
        target_year = today.year + (target_month - 1) // 12
        target_month = ((target_month - 1) % 12) + 1
        max_day = calendar.monthrange(target_year, target_month)[1]
        target_day = min(current_due.day, max_day)
        return date(target_year, target_month, target_day)
    elif recurrence_type == "yearly":
        target_year = today.year + interval
        if current_due.month == 2 and current_due.day == 29 and not calendar.isleap(target_year):
            return date(target_year, 2, 28)
        return date(target_year, current_due.month, current_due.day)
    else:
        msg = f"Unknown recurrence type: {recurrence_type}"
        raise ValueError(msg)


def compute_next_due_datetime(
    current_due_date: date,
    current_due_time: time | None,
    recurrence_type: str,
    interval: int = 1,
) -> tuple[date, time | None]:
    """Compute next due date AND time for any recurrence type.

    For minutely: advances by interval minutes from now, crossing midnight
    boundaries naturally.
    For daily/weekly/monthly/yearly: delegates to compute_next_due_date
    and preserves the existing due_time.
    """
    if recurrence_type == "minutely":
        next_dt = datetime.now() + timedelta(minutes=interval)
        return next_dt.date(), next_dt.time().replace(second=0, microsecond=0)
    next_date = compute_next_due_date(current_due_date, recurrence_type, interval)
    return next_date, current_due_time


def is_recurrence_ended(item: TodoItem, next_due: date | None = None) -> bool:
    """Check if a recurring item has reached its end condition."""
    if not item.is_recurring:
        return True
    if (
        item.recurrence_end_count is not None
        and item.recurrence_count + 1 >= item.recurrence_end_count
    ):
        return True
    return (
        item.recurrence_end_date is not None
        and next_due is not None
        and next_due > item.recurrence_end_date
    )


def advance_overdue_recurring(item: TodoItem) -> bool:
    """Auto-advance an overdue recurring item to the next valid due date.

    Returns True if the item was modified, False otherwise.
    Does NOT increment recurrence_count (that tracks completions only).
    Increments missed_recurrences for tracking purposes.

    For minutely recurrence, calculates all missed intervals at once and
    jumps directly to the next future occurrence (updates both due_date
    and due_time).  For daily+ recurrence, a single advance is sufficient
    since compute_next_due_date always produces a future date.
    """
    if not item.is_recurring or item.complete:
        return False
    if item.due_date is None or item.recurrence_type is None:
        return False
    if not is_overdue(item.due_date, item.due_time):
        return False
    # Don't advance if recurrence already exhausted by count
    if item.recurrence_end_count is not None and item.recurrence_count >= item.recurrence_end_count:
        return False

    if item.recurrence_type == "minutely":
        # Calculate all missed intervals at once to avoid runaway accumulation
        now = datetime.now()
        due_dt = datetime.combine(
            item.due_date,
            item.due_time if item.due_time is not None else time(0, 0),
        )
        elapsed_minutes = (now - due_dt).total_seconds() / 60
        interval = item.recurrence_interval or 1
        missed_count = max(1, int(elapsed_minutes / interval))

        # Jump to the next occurrence after now
        next_dt = due_dt + timedelta(minutes=interval * (missed_count + 1))
        # If we're still in the past (rounding), advance one more
        while next_dt <= now:
            next_dt += timedelta(minutes=interval)
            missed_count += 1

        next_date = next_dt.date()
        next_time = next_dt.time().replace(second=0, microsecond=0)

        if is_recurrence_ended(item, next_date):
            item.complete = True
            item.missed_recurrences += missed_count
            item.mark_updated()
            return True

        item.due_date = next_date
        item.due_time = next_time
        item.missed_recurrences += missed_count
        item.mark_updated()
        return True

    next_due = compute_next_due_date(item.due_date, item.recurrence_type, item.recurrence_interval)

    if is_recurrence_ended(item, next_due):
        # Recurrence expired while missed — mark as complete
        item.complete = True
        item.missed_recurrences += 1
        item.mark_updated()
        return True

    item.due_date = next_due
    item.missed_recurrences += 1
    item.mark_updated()
    return True


def cycle_completed_recurring(item: TodoItem, todo_list: TodoList, day_start_hour: int = 0) -> bool:
    """Cycle a completed recurring item to its next occurrence when due.

    After the user completes a recurring item, it stays complete until the
    next due date arrives. This function detects that the next occurrence
    is now due and resets the item: complete→False, due_date advanced,
    board_column reset, and all subtask completions cleared.

    For minutely recurrence, cycles when the interval has elapsed (sub-day).

    Returns True if the item was cycled, False otherwise.
    """
    if not item.is_recurring or not item.complete:
        return False
    if item.due_date is None or item.recurrence_type is None:
        return False
    # Don't cycle if recurrence is exhausted
    if item.recurrence_end_count is not None and item.recurrence_count >= item.recurrence_end_count:
        return False

    today = logical_today(day_start_hour)

    if item.recurrence_type == "minutely":
        # For minutely recurrence, check if the interval has elapsed
        if not is_overdue(item.due_date, item.due_time):
            return False  # Not yet time — stay complete
    else:
        # For daily+ recurrence, only cycle when the due date has passed
        if item.due_date >= today:
            return False  # Still the same logical day — stay complete

    next_date, next_time = compute_next_due_datetime(
        item.due_date, item.due_time, item.recurrence_type, item.recurrence_interval
    )

    if is_recurrence_ended(item, next_date):
        return False  # Recurrence ended — stay complete permanently

    # Cycle to next occurrence
    item.complete = False
    item.due_date = next_date
    if next_time is not None:
        item.due_time = next_time

    # Reset board column — items with work history go to progress, else inbox
    cols = todo_list.board_columns
    if cols and item.board_column == cols[-1]:
        first_col = cols[0]
        if len(cols) >= 3:
            # Check for work indicators (pomodoro time or completed subtasks)
            has_work = item.time_spent > 0
            if not has_work:
                has_work = any(
                    c.parent_id == item.id and not c.deleted and c.complete
                    for c in todo_list.items.values()
                )
            progress_col = next((c for c in cols[1:-1] if c == "In Progress"), cols[1])
            item.board_column = progress_col if has_work else first_col
        else:
            item.board_column = first_col

    # Reset subtask completions (only non-recurring subtasks — independently
    # recurring subtasks cycle on their own schedule)
    for child in todo_list.items.values():
        if (
            child.parent_id == item.id
            and not child.deleted
            and child.complete
            and not child.is_recurring
        ):
            child.complete = False
            child.mark_updated()

    item.mark_updated()
    return True


def advance_all_overdue_recurring(database: Database) -> int:
    """Scan all lists and auto-advance overdue recurring items.

    Handles two cases:
    1. Incomplete overdue items → advance due date (existing behavior)
    2. Completed recurring items whose next occurrence is due → cycle them

    Returns the number of items that were advanced or cycled.
    """
    advanced_count = 0
    for todo_list in database.active_lists():
        list_changed = False
        for item in list(todo_list.active_items()):
            if advance_overdue_recurring(item) or cycle_completed_recurring(item, todo_list):
                advanced_count += 1
                list_changed = True
        if list_changed:
            todo_list.mark_updated()
    return advanced_count


def _format_minutes_interval(minutes: int) -> str:
    """Format a minute interval smartly: 60→'hour', 240→'4 hours', 30→'30 min'."""
    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if minutes > 60:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"
    return f"{minutes} min"


def format_recurrence(item: TodoItem) -> str:
    """Format recurrence rule for display (e.g., 'Every day', 'Every 30 min')."""
    if not item.is_recurring or item.recurrence_type is None:
        return ""
    if item.recurrence_type == "minutely":
        text = f"Every {_format_minutes_interval(item.recurrence_interval)}"
    else:
        type_singular = {
            "daily": "day",
            "weekly": "week",
            "monthly": "month",
            "yearly": "year",
        }
        type_plural = {
            "daily": "days",
            "weekly": "weeks",
            "monthly": "months",
            "yearly": "years",
        }
        if item.recurrence_interval == 1:
            text = f"Every {type_singular.get(item.recurrence_type, item.recurrence_type)}"
        else:
            text = (
                f"Every {item.recurrence_interval} "
                f"{type_plural.get(item.recurrence_type, item.recurrence_type)}"
            )
    if item.recurrence_end_count is not None:
        text += f" ({item.recurrence_count}/{item.recurrence_end_count} completed)"
    elif item.recurrence_end_date is not None:
        text += f" (until {item.recurrence_end_date.strftime('%b %d, %Y')})"
    if item.missed_recurrences > 0:
        text += f" ({item.missed_recurrences} missed)"
    return text


def format_recurrence_short(item: TodoItem) -> str:
    """Compact recurrence display for cards and badges."""
    if not item.is_recurring or item.recurrence_type is None:
        return ""
    if item.recurrence_type == "minutely":
        return f"Every {_format_minutes_interval(item.recurrence_interval)}"
    labels = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly"}
    if item.recurrence_interval == 1:
        return labels.get(item.recurrence_type, item.recurrence_type)
    units = {"daily": "days", "weekly": "weeks", "monthly": "months", "yearly": "years"}
    return f"Every {item.recurrence_interval} {units.get(item.recurrence_type, '')}"


def format_next_occurrence(item: TodoItem, time_format: str = "system") -> str:
    """Format when the next occurrence is due for display."""
    if not item.is_recurring or item.recurrence_type is None or item.due_date is None:
        return ""
    if item.recurrence_end_count is not None and item.recurrence_count >= item.recurrence_end_count:
        return ""
    next_date, next_time = compute_next_due_datetime(
        item.due_date, item.due_time, item.recurrence_type, item.recurrence_interval
    )
    prefix = "Resets" if item.complete else "Next"
    date_str = format_due_date(next_date, due_time=next_time, time_format=time_format)
    return f"{prefix}: {date_str}"
