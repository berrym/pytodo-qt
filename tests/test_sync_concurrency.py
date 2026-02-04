"""Tests for sync concurrency protection (Phase 2)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from pytodo_qt.net.protocol import (
    BusyResponse,
    ErrorCode,
    create_busy_response,
)
from pytodo_qt.net.sync_queue import (
    SyncOperation,
    SyncOperationType,
    SyncResult,
    SyncStatus,
    create_pull_operation,
    create_push_operation,
)


class TestBusyResponse:
    """Tests for BusyResponse protocol message."""

    def test_busy_response_creation(self):
        """Test creating a busy response."""
        busy = BusyResponse(retry_after=5, current_peer="192.168.1.10:5364")
        assert busy.retry_after == 5
        assert busy.current_peer == "192.168.1.10:5364"

    def test_busy_response_pack_unpack(self):
        """Test busy response serialization round-trip."""
        original = BusyResponse(retry_after=10, current_peer="laptop:5364")
        packed = original.pack()
        unpacked = BusyResponse.unpack(packed)

        assert unpacked.retry_after == 10
        assert unpacked.current_peer == "laptop:5364"

    def test_busy_response_empty_peer(self):
        """Test busy response with empty peer."""
        busy = BusyResponse(retry_after=3, current_peer="")
        packed = busy.pack()
        unpacked = BusyResponse.unpack(packed)

        assert unpacked.retry_after == 3
        assert unpacked.current_peer == ""

    def test_create_busy_response_message(self):
        """Test creating a complete busy response message."""
        msg = create_busy_response(retry_after=5, current_peer="test:5364")

        # Should be an ERROR message type
        from pytodo_qt.net.protocol import MessageType

        assert msg.header.msg_type == MessageType.ERROR

        # Payload should start with SERVER_BUSY error code
        assert msg.payload[0] == ErrorCode.SERVER_BUSY

        # Rest should be BusyResponse
        busy = BusyResponse.unpack(msg.payload[1:])
        assert busy.retry_after == 5
        assert busy.current_peer == "test:5364"


class TestSyncOperation:
    """Tests for SyncOperation dataclass."""

    def test_create_pull_operation(self):
        """Test creating a pull operation."""
        op = create_pull_operation("192.168.1.10", 5364)

        assert op.operation_type == SyncOperationType.PULL
        assert op.host == "192.168.1.10"
        assert op.port == 5364
        assert op.data == b""
        assert op.max_retries == 3
        assert op.retry_count == 0

    def test_create_push_operation(self):
        """Test creating a push operation."""
        data = b'{"test": "data"}'
        op = create_push_operation("192.168.1.10", 5364, data)

        assert op.operation_type == SyncOperationType.PUSH
        assert op.host == "192.168.1.10"
        assert op.port == 5364
        assert op.data == data

    def test_operation_with_device_id(self):
        """Test creating operation with device ID."""
        device_id = uuid4()
        op = create_pull_operation("host", 5364, device_id=device_id)

        assert op.device_id == device_id

    def test_operation_with_list_ids(self):
        """Test creating operation with specific list IDs."""
        list_ids = [uuid4(), uuid4()]
        op = create_push_operation("host", 5364, b"data", list_ids=list_ids)

        assert op.list_ids == list_ids

    def test_can_retry(self):
        """Test retry logic."""
        op = SyncOperation(max_retries=3)

        assert op.can_retry() is True
        op.retry_count = 2
        assert op.can_retry() is True
        op.retry_count = 3
        assert op.can_retry() is False


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_success_result(self):
        """Test successful sync result."""
        result = SyncResult(success=True, data=b"test data", status=SyncStatus.SUCCESS)

        assert result.success is True
        assert result.data == b"test data"
        assert result.error == ""

    def test_failure_result(self):
        """Test failed sync result."""
        result = SyncResult(success=False, error="Connection refused", status=SyncStatus.FAILED)

        assert result.success is False
        assert result.error == "Connection refused"

    def test_busy_result(self):
        """Test busy retry result."""
        result = SyncResult(
            success=False,
            status=SyncStatus.BUSY_RETRY,
            retry_after=5,
            current_peer="laptop:5364",
        )

        assert result.success is False
        assert result.status == SyncStatus.BUSY_RETRY
        assert result.retry_after == 5
        assert result.current_peer == "laptop:5364"


class TestSyncStatus:
    """Tests for SyncStatus enum."""

    def test_status_values(self):
        """Test all status values exist."""
        assert SyncStatus.PENDING.value == "pending"
        assert SyncStatus.IN_PROGRESS.value == "in_progress"
        assert SyncStatus.SUCCESS.value == "success"
        assert SyncStatus.FAILED.value == "failed"
        assert SyncStatus.BUSY_RETRY.value == "busy_retry"
        assert SyncStatus.CANCELLED.value == "cancelled"


class TestSyncQueueBasic:
    """Basic tests for SyncQueue (without network operations)."""

    def test_queue_initial_state(self):
        """Test queue initial state."""
        # We can't easily test SyncQueue without a real AsyncClient,
        # but we can test the operation creation
        op = create_pull_operation("host", 5364)
        assert op.status == SyncStatus.PENDING
        assert op.result is None

    def test_operation_id_uniqueness(self):
        """Test that operations get unique IDs."""
        op1 = create_pull_operation("host1", 5364)
        op2 = create_pull_operation("host2", 5364)

        assert op1.id != op2.id


class TestServerSyncLock:
    """Tests for server-side sync lock behavior.

    Note: These are unit tests for the lock logic, not integration tests.
    Full integration tests would require running an actual server.
    """

    @pytest.mark.asyncio
    async def test_asyncio_lock_basic(self):
        """Test basic asyncio.Lock behavior used by server."""
        lock = asyncio.Lock()

        # Lock should be acquirable
        assert not lock.locked()
        await lock.acquire()
        assert lock.locked()

        # Release should work
        lock.release()
        assert not lock.locked()

    @pytest.mark.asyncio
    async def test_lock_timeout_behavior(self):
        """Test lock acquisition with timeout."""
        lock = asyncio.Lock()

        # Acquire the lock
        await lock.acquire()

        # Try to acquire with timeout (should fail)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=0.1)
            acquired = True
        except TimeoutError:
            acquired = False

        assert acquired is False

        # Release and try again
        lock.release()

        try:
            await asyncio.wait_for(lock.acquire(), timeout=0.1)
            acquired = True
        except TimeoutError:
            acquired = False

        assert acquired is True
        lock.release()

    @pytest.mark.asyncio
    async def test_concurrent_lock_requests(self):
        """Test multiple concurrent lock requests."""
        lock = asyncio.Lock()
        results = []

        async def try_acquire(name: str, delay: float = 0):
            if delay:
                await asyncio.sleep(delay)
            try:
                await asyncio.wait_for(lock.acquire(), timeout=0.5)
                results.append(f"{name}:acquired")
                await asyncio.sleep(0.1)  # Hold lock briefly
                lock.release()
                results.append(f"{name}:released")
            except TimeoutError:
                results.append(f"{name}:timeout")

        # Start multiple tasks
        await asyncio.gather(
            try_acquire("A"),
            try_acquire("B", 0.05),
            try_acquire("C", 0.1),
        )

        # First should acquire and release, others should eventually get it too
        assert "A:acquired" in results
        assert "A:released" in results


class TestProtocolErrorCodes:
    """Tests for protocol error codes."""

    def test_server_busy_error_code(self):
        """Test SERVER_BUSY error code exists."""
        assert ErrorCode.SERVER_BUSY == 0x08

    def test_all_error_codes_unique(self):
        """Test all error codes are unique."""
        values = [e.value for e in ErrorCode]
        assert len(values) == len(set(values))
