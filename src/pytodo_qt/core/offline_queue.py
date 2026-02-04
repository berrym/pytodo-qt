"""offline_queue.py

Manages pending syncs for offline devices.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from .logger import Logger
from .models import PendingSync

if TYPE_CHECKING:
    from .database import DatabaseStorage

logger = Logger(__name__)


class OfflineQueue:
    """Persistent queue for syncs to offline devices."""

    def __init__(self, storage: DatabaseStorage):
        self._storage = storage

    def enqueue(self, device_id: UUID, list_ids: list[UUID] | None = None) -> PendingSync:
        """Queue sync for offline device.

        Args:
            device_id: The device to sync to
            list_ids: Optional specific list IDs to sync. If None/empty, syncs all applicable lists.

        Returns:
            The created PendingSync
        """
        # Check for existing pending sync for this device
        existing = self._storage.get_pending_syncs_for_device(device_id)
        for pending in existing:
            if pending.list_ids == (list_ids or []):
                # Already have a pending sync for same lists
                logger.log.debug("Pending sync already exists for device %s", device_id)
                return pending

        pending = PendingSync(
            device_id=device_id,
            list_ids=list_ids or [],
        )
        self._storage.save_pending_sync(pending)
        logger.log.info("Queued sync for offline device %s", device_id)
        return pending

    def get_pending_for_device(self, device_id: UUID) -> list[PendingSync]:
        """Get all pending syncs for a device."""
        return self._storage.get_pending_syncs_for_device(device_id)

    def has_pending(self, device_id: UUID) -> bool:
        """Check if device has any pending syncs."""
        return len(self.get_pending_for_device(device_id)) > 0

    def get_all_pending(self) -> list[PendingSync]:
        """Get all pending syncs across all devices."""
        return self._storage.get_all_pending_syncs()

    def remove(self, pending_id: UUID) -> bool:
        """Remove a pending sync (after successful sync or user cancel)."""
        return self._storage.delete_pending_sync(pending_id)

    def clear_for_device(self, device_id: UUID) -> int:
        """Clear all pending syncs for a device."""
        pending = self.get_pending_for_device(device_id)
        count = 0
        for p in pending:
            if self._storage.delete_pending_sync(p.id):
                count += 1
        if count > 0:
            logger.log.info("Cleared %d pending syncs for device %s", count, device_id)
        return count

    def record_attempt(self, pending: PendingSync) -> None:
        """Record a sync attempt."""
        pending.record_attempt()
        self._storage.save_pending_sync(pending)

    def cleanup_expired(self) -> int:
        """Remove expired pending syncs."""
        return self._storage.delete_expired_pending_syncs()

    def get_pending_count(self) -> int:
        """Get total count of pending syncs."""
        return len(self.get_all_pending())

    def get_pending_devices(self) -> list[UUID]:
        """Get list of device IDs with pending syncs."""
        pending = self.get_all_pending()
        return list({p.device_id for p in pending})
