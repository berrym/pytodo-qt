"""Tests for sync groups data layer (0.3.10)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from uuid import uuid4

import pytest

from pytodo_qt.core.database import SCHEMA_VERSION, DatabaseStorage
from pytodo_qt.core.models import (
    Device,
    ListSyncRule,
    PendingSync,
    SyncGroup,
    create_device,
    create_pending_sync,
    create_sync_group,
    create_todo_list,
)


class TestDeviceModel:
    """Tests for Device model."""

    def test_create_device(self):
        """Test creating a device."""
        device = create_device("abc123fingerprint", "My MacBook")
        assert device.fingerprint == "abc123fingerprint"
        assert device.name == "My MacBook"
        assert device.trust_level == "normal"
        assert device.last_address is None

    def test_device_update_seen(self):
        """Test updating device last seen."""
        device = create_device("fp123", "Test")
        original_seen = device.last_seen

        time.sleep(0.01)  # Ensure time passes
        device.update_seen("192.168.1.100:5364")

        assert device.last_seen > original_seen
        assert device.last_address == "192.168.1.100:5364"

    def test_device_to_dict(self):
        """Test device serialization."""
        device = create_device("fp123", "Test Device")
        device.trust_level = "trusted"
        device.last_address = "10.0.0.1:5364"

        data = device.to_dict()

        assert data["fingerprint"] == "fp123"
        assert data["name"] == "Test Device"
        assert data["trust_level"] == "trusted"
        assert data["last_address"] == "10.0.0.1:5364"

    def test_device_from_dict(self):
        """Test device deserialization."""
        data = {
            "id": str(uuid4()),
            "fingerprint": "fp456",
            "name": "Remote Device",
            "first_seen": 1000000,
            "last_seen": 2000000,
            "last_address": "192.168.1.50:5364",
            "trust_level": "blocked",
        }

        device = Device.from_dict(data)

        assert device.fingerprint == "fp456"
        assert device.name == "Remote Device"
        assert device.trust_level == "blocked"
        assert device.last_address == "192.168.1.50:5364"


class TestSyncGroupModel:
    """Tests for SyncGroup model."""

    def test_create_sync_group(self):
        """Test creating a sync group."""
        group = create_sync_group("Work Devices")
        assert group.name == "Work Devices"
        assert group.created_at > 0
        assert group.updated_at > 0

    def test_sync_group_mark_updated(self):
        """Test marking group as updated."""
        group = create_sync_group("Test")
        original_updated = group.updated_at

        time.sleep(0.01)
        group.mark_updated()

        assert group.updated_at > original_updated

    def test_sync_group_serialization(self):
        """Test group serialization round-trip."""
        group = create_sync_group("Home")
        data = group.to_dict()
        restored = SyncGroup.from_dict(data)

        assert restored.id == group.id
        assert restored.name == group.name
        assert restored.created_at == group.created_at


class TestListSyncRuleModel:
    """Tests for ListSyncRule model."""

    def test_list_sync_rule_creation(self):
        """Test creating a list sync rule."""
        list_id = uuid4()
        group_id = uuid4()
        rule = ListSyncRule(list_id=list_id, group_id=group_id)

        assert rule.list_id == list_id
        assert rule.group_id == group_id

    def test_list_sync_rule_serialization(self):
        """Test rule serialization round-trip."""
        rule = ListSyncRule(list_id=uuid4(), group_id=uuid4())
        data = rule.to_dict()
        restored = ListSyncRule.from_dict(data)

        assert restored.list_id == rule.list_id
        assert restored.group_id == rule.group_id


class TestPendingSyncModel:
    """Tests for PendingSync model."""

    def test_create_pending_sync(self):
        """Test creating a pending sync."""
        device_id = uuid4()
        pending = create_pending_sync(device_id)

        assert pending.device_id == device_id
        assert pending.list_ids == []
        assert pending.attempts == 0
        assert pending.expires_at > pending.created_at

    def test_pending_sync_with_list_ids(self):
        """Test pending sync with specific lists."""
        device_id = uuid4()
        list_ids = [uuid4(), uuid4()]
        pending = create_pending_sync(device_id, list_ids)

        assert pending.list_ids == list_ids

    def test_pending_sync_is_expired(self):
        """Test expiration check."""
        pending = create_pending_sync(uuid4())
        assert not pending.is_expired()

        # Create expired sync
        pending.expires_at = pending.created_at - 1000
        assert pending.is_expired()

    def test_pending_sync_record_attempt(self):
        """Test recording sync attempt."""
        pending = create_pending_sync(uuid4())
        assert pending.attempts == 0
        assert pending.last_attempt is None

        pending.record_attempt()

        assert pending.attempts == 1
        assert pending.last_attempt is not None

    def test_pending_sync_serialization(self):
        """Test pending sync serialization round-trip."""
        list_ids = [uuid4(), uuid4()]
        pending = create_pending_sync(uuid4(), list_ids)
        pending.record_attempt()

        data = pending.to_dict()
        restored = PendingSync.from_dict(data)

        assert restored.id == pending.id
        assert restored.device_id == pending.device_id
        assert restored.list_ids == pending.list_ids
        assert restored.attempts == pending.attempts


class TestDatabaseStorageDevices:
    """Tests for device storage operations."""

    @pytest.fixture
    def storage(self):
        """Create a temporary database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            yield storage
            storage.close()

    def test_save_and_get_device(self, storage):
        """Test saving and retrieving a device."""
        device = create_device("fingerprint123", "Test MacBook")
        device.trust_level = "trusted"
        device.last_address = "192.168.1.10:5364"

        storage.save_device(device)
        retrieved = storage.get_device(device.id)

        assert retrieved is not None
        assert retrieved.fingerprint == "fingerprint123"
        assert retrieved.name == "Test MacBook"
        assert retrieved.trust_level == "trusted"

    def test_get_device_by_fingerprint(self, storage):
        """Test retrieving device by fingerprint."""
        device = create_device("unique_fp_123", "Device")
        storage.save_device(device)

        retrieved = storage.get_device_by_fingerprint("unique_fp_123")

        assert retrieved is not None
        assert retrieved.id == device.id

    def test_get_device_by_fingerprint_not_found(self, storage):
        """Test retrieving non-existent fingerprint."""
        retrieved = storage.get_device_by_fingerprint("nonexistent")
        assert retrieved is None

    def test_get_all_devices(self, storage):
        """Test retrieving all devices."""
        device1 = create_device("fp1", "Device 1")
        device2 = create_device("fp2", "Device 2")
        device2.trust_level = "blocked"

        storage.save_device(device1)
        storage.save_device(device2)

        # Without blocked
        devices = storage.get_all_devices(include_blocked=False)
        assert len(devices) == 1
        assert devices[0].name == "Device 1"

        # With blocked
        devices = storage.get_all_devices(include_blocked=True)
        assert len(devices) == 2

    def test_update_device_fingerprint(self, storage):
        """Test updating device fingerprint."""
        device = create_device("old_fp", "Device")
        storage.save_device(device)

        result = storage.update_device_fingerprint(device.id, "new_fp")

        assert result is True
        retrieved = storage.get_device(device.id)
        assert retrieved.fingerprint == "new_fp"

    def test_delete_device(self, storage):
        """Test deleting a device."""
        device = create_device("fp", "Device")
        storage.save_device(device)

        result = storage.delete_device(device.id)

        assert result is True
        assert storage.get_device(device.id) is None


class TestDatabaseStorageSyncGroups:
    """Tests for sync group storage operations."""

    @pytest.fixture
    def storage(self):
        """Create a temporary database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            yield storage
            storage.close()

    def test_save_and_get_sync_group(self, storage):
        """Test saving and retrieving a sync group."""
        group = create_sync_group("Home Devices")
        storage.save_sync_group(group)

        retrieved = storage.get_sync_group(group.id)

        assert retrieved is not None
        assert retrieved.name == "Home Devices"

    def test_get_sync_group_by_name(self, storage):
        """Test retrieving sync group by name."""
        group = create_sync_group("Work")
        storage.save_sync_group(group)

        retrieved = storage.get_sync_group_by_name("Work")

        assert retrieved is not None
        assert retrieved.id == group.id

    def test_get_all_sync_groups(self, storage):
        """Test retrieving all sync groups."""
        group1 = create_sync_group("Alpha")
        group2 = create_sync_group("Beta")

        storage.save_sync_group(group1)
        storage.save_sync_group(group2)

        groups = storage.get_all_sync_groups()

        assert len(groups) == 2
        # Should be sorted by name
        assert groups[0].name == "Alpha"
        assert groups[1].name == "Beta"

    def test_delete_sync_group(self, storage):
        """Test deleting a sync group."""
        group = create_sync_group("Temp")
        storage.save_sync_group(group)

        result = storage.delete_sync_group(group.id)

        assert result is True
        assert storage.get_sync_group(group.id) is None


class TestDatabaseStorageDeviceGroups:
    """Tests for device-group membership operations."""

    @pytest.fixture
    def storage(self):
        """Create a temporary database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            yield storage
            storage.close()

    def test_add_device_to_group(self, storage):
        """Test adding device to a group."""
        device = create_device("fp", "Device")
        group = create_sync_group("Group")
        storage.save_device(device)
        storage.save_sync_group(group)

        storage.add_device_to_group(device.id, group.id)

        devices = storage.get_devices_in_group(group.id)
        assert len(devices) == 1
        assert devices[0].id == device.id

    def test_get_groups_for_device(self, storage):
        """Test getting groups a device belongs to."""
        device = create_device("fp", "Device")
        group1 = create_sync_group("Group1")
        group2 = create_sync_group("Group2")

        storage.save_device(device)
        storage.save_sync_group(group1)
        storage.save_sync_group(group2)

        storage.add_device_to_group(device.id, group1.id)
        storage.add_device_to_group(device.id, group2.id)

        groups = storage.get_groups_for_device(device.id)

        assert len(groups) == 2

    def test_remove_device_from_group(self, storage):
        """Test removing device from a group."""
        device = create_device("fp", "Device")
        group = create_sync_group("Group")
        storage.save_device(device)
        storage.save_sync_group(group)
        storage.add_device_to_group(device.id, group.id)

        result = storage.remove_device_from_group(device.id, group.id)

        assert result is True
        assert len(storage.get_devices_in_group(group.id)) == 0

    def test_cascade_delete_device_removes_memberships(self, storage):
        """Test that deleting device removes group memberships."""
        device = create_device("fp", "Device")
        group = create_sync_group("Group")
        storage.save_device(device)
        storage.save_sync_group(group)
        storage.add_device_to_group(device.id, group.id)

        storage.delete_device(device.id)

        # Group should have no devices
        devices = storage.get_devices_in_group(group.id)
        assert len(devices) == 0


class TestDatabaseStorageListSyncRules:
    """Tests for list sync rule operations."""

    @pytest.fixture
    def storage(self):
        """Create a temporary database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            yield storage
            storage.close()

    def test_add_list_sync_rule(self, storage):
        """Test adding a sync rule for a list."""
        lst = create_todo_list("Test List")
        group = create_sync_group("Work")
        storage.save_list(lst)
        storage.save_sync_group(group)

        storage.add_list_sync_rule(lst.id, group.id)

        rules = storage.get_sync_rules_for_list(lst.id)
        assert len(rules) == 1
        assert rules[0].group_id == group.id

    def test_get_lists_for_group(self, storage):
        """Test getting lists that sync to a group."""
        lst1 = create_todo_list("List 1")
        lst2 = create_todo_list("List 2")
        group = create_sync_group("Home")

        storage.save_list(lst1)
        storage.save_list(lst2)
        storage.save_sync_group(group)

        storage.add_list_sync_rule(lst1.id, group.id)
        storage.add_list_sync_rule(lst2.id, group.id)

        list_ids = storage.get_lists_for_group(group.id)

        assert len(list_ids) == 2
        assert lst1.id in list_ids
        assert lst2.id in list_ids

    def test_clear_list_sync_rules(self, storage):
        """Test clearing all sync rules for a list."""
        lst = create_todo_list("Test")
        group1 = create_sync_group("Group1")
        group2 = create_sync_group("Group2")

        storage.save_list(lst)
        storage.save_sync_group(group1)
        storage.save_sync_group(group2)

        storage.add_list_sync_rule(lst.id, group1.id)
        storage.add_list_sync_rule(lst.id, group2.id)

        count = storage.clear_list_sync_rules(lst.id)

        assert count == 2
        assert len(storage.get_sync_rules_for_list(lst.id)) == 0


class TestDatabaseStoragePendingSyncs:
    """Tests for pending sync operations."""

    @pytest.fixture
    def storage(self):
        """Create a temporary database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            yield storage
            storage.close()

    def test_save_and_get_pending_sync(self, storage):
        """Test saving and retrieving a pending sync."""
        device = create_device("fp", "Device")
        storage.save_device(device)

        pending = create_pending_sync(device.id, [uuid4(), uuid4()])
        storage.save_pending_sync(pending)

        retrieved = storage.get_pending_syncs_for_device(device.id)

        assert len(retrieved) == 1
        assert retrieved[0].id == pending.id
        assert len(retrieved[0].list_ids) == 2

    def test_get_all_pending_syncs(self, storage):
        """Test getting all pending syncs."""
        device1 = create_device("fp1", "Device1")
        device2 = create_device("fp2", "Device2")
        storage.save_device(device1)
        storage.save_device(device2)

        pending1 = create_pending_sync(device1.id)
        pending2 = create_pending_sync(device2.id)
        storage.save_pending_sync(pending1)
        storage.save_pending_sync(pending2)

        all_pending = storage.get_all_pending_syncs()

        assert len(all_pending) == 2

    def test_delete_pending_sync(self, storage):
        """Test deleting a pending sync."""
        device = create_device("fp", "Device")
        storage.save_device(device)

        pending = create_pending_sync(device.id)
        storage.save_pending_sync(pending)

        result = storage.delete_pending_sync(pending.id)

        assert result is True
        assert len(storage.get_pending_syncs_for_device(device.id)) == 0

    def test_delete_expired_pending_syncs(self, storage):
        """Test deleting expired pending syncs."""
        device = create_device("fp", "Device")
        storage.save_device(device)

        # Create an expired sync
        pending = create_pending_sync(device.id)
        pending.expires_at = pending.created_at - 1000  # Already expired
        storage.save_pending_sync(pending)

        count = storage.delete_expired_pending_syncs()

        assert count == 1
        assert len(storage.get_pending_syncs_for_device(device.id)) == 0


class TestSchemaMigrationV5:
    """Tests for schema migration v4 to v5."""

    def test_schema_version_is_5(self):
        """Test that current schema version is 9."""
        assert SCHEMA_VERSION == 11

    def test_new_database_has_sync_groups_tables(self):
        """Test that new database has all sync groups tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()

            # Check all new tables exist
            cursor = storage.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            assert "devices" in tables
            assert "sync_groups" in tables
            assert "device_groups" in tables
            assert "list_sync_rules" in tables
            assert "pending_syncs" in tables

            storage.close()

    def test_migration_from_v4_creates_tables(self):
        """Test that migration from v4 creates new tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create a v4 database manually
            import sqlite3

            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            conn.execute(
                """
                CREATE TABLE lists (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    private INTEGER NOT NULL DEFAULT 0
                )
            """
            )
            conn.execute(
                """
                CREATE TABLE items (
                    id TEXT PRIMARY KEY,
                    list_id TEXT NOT NULL,
                    reminder TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 2,
                    complete INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                )
            """
            )
            conn.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '4')")
            conn.commit()
            conn.close()

            # Now open with DatabaseStorage which should run migration
            storage = DatabaseStorage(db_path)
            storage.open()

            # Check schema version was updated (migrates to v8 now)
            assert storage.get_schema_version() == 11

            # Check new tables exist
            cursor = storage.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='devices'"
            )
            assert cursor.fetchone() is not None

            storage.close()


class TestDeviceTracking:
    """Tests for device tracking functionality."""

    @pytest.fixture
    def storage(self):
        """Create a temporary database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            yield storage
            storage.close()

    def test_track_new_device(self, storage):
        """Test tracking a new device creates it."""
        fingerprint = "test:finger:print:1234"
        address = "192.168.1.10:5364"

        # Device doesn't exist yet
        existing = storage.get_device_by_fingerprint(fingerprint)
        assert existing is None

        # Create and save new device
        device = Device(
            fingerprint=fingerprint,
            name="",
            last_address=address,
            trust_level="normal",
        )
        storage.save_device(device)

        # Verify it was saved
        retrieved = storage.get_device_by_fingerprint(fingerprint)
        assert retrieved is not None
        assert retrieved.fingerprint == fingerprint
        assert retrieved.last_address == address
        assert retrieved.trust_level == "normal"

    def test_track_existing_device_updates(self, storage):
        """Test tracking an existing device updates its last_seen."""
        fingerprint = "existing:fp:1234"
        device = create_device(fingerprint, "Test Device")
        device.last_address = "192.168.1.5:5364"
        storage.save_device(device)

        original_seen = device.last_seen

        # Simulate time passing
        time.sleep(0.01)

        # Update the device
        existing = storage.get_device_by_fingerprint(fingerprint)
        assert existing is not None

        new_time = int(time.time() * 1000)
        existing.last_seen = new_time
        existing.last_address = "192.168.1.100:5364"
        storage.save_device(existing)

        # Verify update
        retrieved = storage.get_device_by_fingerprint(fingerprint)
        assert retrieved.last_seen > original_seen
        assert retrieved.last_address == "192.168.1.100:5364"

    def test_device_tracking_preserves_trust_level(self, storage):
        """Test that tracking doesn't change trust level."""
        fingerprint = "trusted:device:fp"
        device = create_device(fingerprint, "Trusted Device")
        device.trust_level = "trusted"
        storage.save_device(device)

        # Update last_seen like tracking would
        existing = storage.get_device_by_fingerprint(fingerprint)
        existing.last_seen = int(time.time() * 1000)
        storage.save_device(existing)

        # Trust level should be preserved
        retrieved = storage.get_device_by_fingerprint(fingerprint)
        assert retrieved.trust_level == "trusted"


class TestClientPeerFingerprint:
    """Tests for AsyncClient peer fingerprint tracking."""

    def test_client_has_last_peer_fingerprint_attr(self):
        """Test client initializes with no peer fingerprint."""
        from pytodo_qt.net.client import AsyncClient

        client = AsyncClient()
        assert client._last_peer_fingerprint is None
        assert client.get_last_peer_fingerprint() is None

    def test_get_last_peer_fingerprint_method_exists(self):
        """Test get_last_peer_fingerprint method exists."""
        from pytodo_qt.net.client import AsyncClient

        client = AsyncClient()
        assert hasattr(client, "get_last_peer_fingerprint")
        assert callable(client.get_last_peer_fingerprint)


class TestSyncGroupOperations:
    """Tests for sync group operations in database storage."""

    @pytest.fixture
    def storage(self):
        """Create a temporary database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            yield storage
            storage.close()

    def test_device_in_multiple_groups(self, storage):
        """Test a device can be in multiple groups."""
        device = create_device("fp1", "Device 1")
        group1 = create_sync_group("Group 1")
        group2 = create_sync_group("Group 2")

        storage.save_device(device)
        storage.save_sync_group(group1)
        storage.save_sync_group(group2)

        storage.add_device_to_group(device.id, group1.id)
        storage.add_device_to_group(device.id, group2.id)

        groups = storage.get_groups_for_device(device.id)
        assert len(groups) == 2

    def test_group_with_multiple_devices(self, storage):
        """Test a group can have multiple devices."""
        device1 = create_device("fp1", "Device 1")
        device2 = create_device("fp2", "Device 2")
        device3 = create_device("fp3", "Device 3")
        group = create_sync_group("Test Group")

        storage.save_device(device1)
        storage.save_device(device2)
        storage.save_device(device3)
        storage.save_sync_group(group)

        storage.add_device_to_group(device1.id, group.id)
        storage.add_device_to_group(device2.id, group.id)
        storage.add_device_to_group(device3.id, group.id)

        devices = storage.get_devices_in_group(group.id)
        assert len(devices) == 3

    def test_delete_group_removes_memberships(self, storage):
        """Test deleting a group removes device memberships."""
        device = create_device("fp1", "Device 1")
        group = create_sync_group("Test Group")

        storage.save_device(device)
        storage.save_sync_group(group)
        storage.add_device_to_group(device.id, group.id)

        # Verify membership exists
        groups = storage.get_groups_for_device(device.id)
        assert len(groups) == 1

        # Delete group
        storage.delete_sync_group(group.id)

        # Verify membership removed
        groups = storage.get_groups_for_device(device.id)
        assert len(groups) == 0

    def test_sync_group_rename_updates_timestamp(self, storage):
        """Test renaming a group updates its timestamp."""
        group = create_sync_group("Original Name")
        storage.save_sync_group(group)

        original_updated = group.updated_at

        time.sleep(0.01)
        group.name = "New Name"
        group.mark_updated()
        storage.save_sync_group(group)

        retrieved = storage.get_sync_group(group.id)
        assert retrieved.name == "New Name"
        assert retrieved.updated_at > original_updated

    def test_duplicate_group_membership_ignored(self, storage):
        """Test adding device to same group twice doesn't duplicate."""
        device = create_device("fp1", "Device 1")
        group = create_sync_group("Test Group")

        storage.save_device(device)
        storage.save_sync_group(group)

        # Add twice
        storage.add_device_to_group(device.id, group.id)
        storage.add_device_to_group(device.id, group.id)

        devices = storage.get_devices_in_group(group.id)
        assert len(devices) == 1


class TestListSyncRulesLogic:
    """Tests for list sync rule filtering logic."""

    @pytest.fixture
    def storage(self):
        """Create a temporary database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            yield storage
            storage.close()

    def test_list_without_rules_syncs_everywhere(self, storage):
        """Test lists without rules sync to all devices."""
        device1 = create_device("fp1", "Device 1")
        device2 = create_device("fp2", "Device 2")
        lst = create_todo_list("No Rules List")

        storage.save_device(device1)
        storage.save_device(device2)
        storage.save_list(lst)

        # No rules - should sync to both devices
        syncable1 = storage.get_syncable_list_ids_for_device(device1.id)
        syncable2 = storage.get_syncable_list_ids_for_device(device2.id)

        assert lst.id in syncable1
        assert lst.id in syncable2

    def test_list_with_rules_only_syncs_to_group_devices(self, storage):
        """Test lists with rules only sync to devices in those groups."""
        device_in_group = create_device("fp1", "Device In Group")
        device_not_in_group = create_device("fp2", "Device Not In Group")
        group = create_sync_group("Work")
        lst = create_todo_list("Work List")

        storage.save_device(device_in_group)
        storage.save_device(device_not_in_group)
        storage.save_sync_group(group)
        storage.save_list(lst)

        # Add device to group
        storage.add_device_to_group(device_in_group.id, group.id)

        # Add rule: list syncs to Work group
        storage.add_list_sync_rule(lst.id, group.id)

        # Check filtering
        syncable_in_group = storage.get_syncable_list_ids_for_device(device_in_group.id)
        syncable_not_in_group = storage.get_syncable_list_ids_for_device(device_not_in_group.id)

        assert lst.id in syncable_in_group
        assert lst.id not in syncable_not_in_group

    def test_private_list_never_syncs(self, storage):
        """Test private lists never sync to any device."""
        device = create_device("fp1", "Device")
        lst = create_todo_list("Private List")
        lst.private = True

        storage.save_device(device)
        storage.save_list(lst)

        syncable = storage.get_syncable_list_ids_for_device(device.id)

        assert lst.id not in syncable

    def test_list_with_multiple_group_rules(self, storage):
        """Test list with rules for multiple groups."""
        device1 = create_device("fp1", "Device 1")
        device2 = create_device("fp2", "Device 2")
        device3 = create_device("fp3", "Device 3")
        group1 = create_sync_group("Group 1")
        group2 = create_sync_group("Group 2")
        lst = create_todo_list("Multi Group List")

        storage.save_device(device1)
        storage.save_device(device2)
        storage.save_device(device3)
        storage.save_sync_group(group1)
        storage.save_sync_group(group2)
        storage.save_list(lst)

        # device1 in group1, device2 in group2, device3 in neither
        storage.add_device_to_group(device1.id, group1.id)
        storage.add_device_to_group(device2.id, group2.id)

        # List syncs to both groups
        storage.add_list_sync_rule(lst.id, group1.id)
        storage.add_list_sync_rule(lst.id, group2.id)

        # Both device1 and device2 should get it, but not device3
        assert lst.id in storage.get_syncable_list_ids_for_device(device1.id)
        assert lst.id in storage.get_syncable_list_ids_for_device(device2.id)
        assert lst.id not in storage.get_syncable_list_ids_for_device(device3.id)

    def test_deleted_list_not_synced(self, storage):
        """Test deleted lists are not synced."""
        device = create_device("fp1", "Device")
        lst = create_todo_list("Deleted List")
        lst.deleted = True

        storage.save_device(device)
        storage.save_list(lst)

        syncable = storage.get_syncable_list_ids_for_device(device.id)

        assert lst.id not in syncable


class TestDatabaseToDeviceDict:
    """Tests for Database.to_dict_for_device method."""

    def test_to_dict_for_device_filters_lists(self):
        """Test to_dict_for_device includes only allowed lists."""
        from pytodo_qt.core.models import Database

        lst1 = create_todo_list("List 1")
        lst2 = create_todo_list("List 2")
        lst3 = create_todo_list("List 3")

        db = Database(
            lists={lst1.id: lst1, lst2.id: lst2, lst3.id: lst3},
        )

        # Only allow list 1 and 3
        allowed = {lst1.id, lst3.id}
        result = db.to_dict_for_device(allowed)

        assert str(lst1.id) in result["lists"]
        assert str(lst2.id) not in result["lists"]
        assert str(lst3.id) in result["lists"]

    def test_to_dict_for_device_excludes_private(self):
        """Test to_dict_for_device still excludes private lists."""
        from pytodo_qt.core.models import Database

        lst1 = create_todo_list("Public List")
        lst2 = create_todo_list("Private List")
        lst2.private = True

        db = Database(lists={lst1.id: lst1, lst2.id: lst2})

        # Allow both
        allowed = {lst1.id, lst2.id}
        result = db.to_dict_for_device(allowed)

        # Private list should still be excluded
        assert str(lst1.id) in result["lists"]
        assert str(lst2.id) not in result["lists"]


class TestOfflineQueue:
    """Tests for OfflineQueue class."""

    @pytest.fixture
    def storage(self):
        """Create a temporary database storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage = DatabaseStorage(db_path)
            storage.open()
            yield storage
            storage.close()

    @pytest.fixture
    def queue(self, storage):
        """Create an OfflineQueue instance."""
        from pytodo_qt.core.offline_queue import OfflineQueue

        return OfflineQueue(storage)

    def test_enqueue_creates_pending_sync(self, queue, storage):
        """Test enqueue creates a pending sync."""
        device = create_device("fp1", "Device")
        storage.save_device(device)

        pending = queue.enqueue(device.id)

        assert pending.device_id == device.id
        assert pending.list_ids == []
        assert len(queue.get_pending_for_device(device.id)) == 1

    def test_enqueue_with_list_ids(self, queue, storage):
        """Test enqueue with specific list IDs."""
        device = create_device("fp1", "Device")
        storage.save_device(device)
        list_ids = [uuid4(), uuid4()]

        pending = queue.enqueue(device.id, list_ids)

        assert pending.list_ids == list_ids

    def test_enqueue_duplicate_returns_existing(self, queue, storage):
        """Test enqueue doesn't create duplicate for same lists."""
        device = create_device("fp1", "Device")
        storage.save_device(device)

        pending1 = queue.enqueue(device.id)
        pending2 = queue.enqueue(device.id)

        assert pending1.id == pending2.id
        assert len(queue.get_all_pending()) == 1

    def test_has_pending(self, queue, storage):
        """Test has_pending returns correct status."""
        device = create_device("fp1", "Device")
        storage.save_device(device)

        assert not queue.has_pending(device.id)

        queue.enqueue(device.id)

        assert queue.has_pending(device.id)

    def test_remove_pending(self, queue, storage):
        """Test removing a pending sync."""
        device = create_device("fp1", "Device")
        storage.save_device(device)
        pending = queue.enqueue(device.id)

        result = queue.remove(pending.id)

        assert result is True
        assert not queue.has_pending(device.id)

    def test_clear_for_device(self, queue, storage):
        """Test clearing all pending syncs for a device."""
        device = create_device("fp1", "Device")
        storage.save_device(device)

        queue.enqueue(device.id, [uuid4()])
        queue.enqueue(device.id, [uuid4(), uuid4()])

        count = queue.clear_for_device(device.id)

        assert count == 2
        assert not queue.has_pending(device.id)

    def test_record_attempt(self, queue, storage):
        """Test recording sync attempts."""
        device = create_device("fp1", "Device")
        storage.save_device(device)
        pending = queue.enqueue(device.id)

        assert pending.attempts == 0
        assert pending.last_attempt is None

        queue.record_attempt(pending)

        retrieved = queue.get_pending_for_device(device.id)[0]
        assert retrieved.attempts == 1
        assert retrieved.last_attempt is not None

    def test_get_pending_count(self, queue, storage):
        """Test getting total pending count."""
        device1 = create_device("fp1", "Device 1")
        device2 = create_device("fp2", "Device 2")
        storage.save_device(device1)
        storage.save_device(device2)

        assert queue.get_pending_count() == 0

        queue.enqueue(device1.id)
        queue.enqueue(device2.id)

        assert queue.get_pending_count() == 2

    def test_get_pending_devices(self, queue, storage):
        """Test getting list of devices with pending syncs."""
        device1 = create_device("fp1", "Device 1")
        device2 = create_device("fp2", "Device 2")
        device3 = create_device("fp3", "Device 3")
        storage.save_device(device1)
        storage.save_device(device2)
        storage.save_device(device3)

        queue.enqueue(device1.id)
        queue.enqueue(device2.id)

        pending_devices = queue.get_pending_devices()

        assert len(pending_devices) == 2
        assert device1.id in pending_devices
        assert device2.id in pending_devices
        assert device3.id not in pending_devices
