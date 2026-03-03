"""Comprehensive tests for network modules to improve coverage.

Covers:
- protocol.py: validation error paths, corrupt data, truncated messages
- sync_queue.py: SyncQueue construction, queue ops, async processing
- client.py: connection handling, request/response patterns, encryption
- server.py: message handling, sync lock, handshake, callbacks
"""

from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pytodo_qt.net.client import AsyncClient, ConnectionState
from pytodo_qt.net.protocol import (
    PROTOCOL_MAGIC,
    PROTOCOL_VERSION,
    BusyResponse,
    ErrorCode,
    ErrorMessage,
    HelloMessage,
    KeyExchangeMessage,
    Message,
    MessageHeader,
    MessageType,
    PeerInfo,
    SyncRequest,
    SyncResponse,
    create_busy_response,
    create_error,
    create_hello_ack,
    create_key_exchange,
    create_key_exchange_ack,
    create_ping,
    create_pong,
    create_sync_request,
    create_sync_response,
)
from pytodo_qt.net.server import AsyncServer, ClientSession

# ---------------------------------------------------------------------------
#  protocol.py — validation error paths
# ---------------------------------------------------------------------------


class TestHelloMessageValidation:
    """Tests for HelloMessage validation and edge cases."""

    def test_unpack_too_short_raises(self):
        """HelloMessage.unpack raises on truncated data."""
        with pytest.raises(ValueError, match="HelloMessage too short"):
            HelloMessage.unpack(b"\x00" * 10)

    def test_unpack_exactly_minimum_size(self):
        """HelloMessage.unpack succeeds with exactly SIZE bytes."""
        pubkey = b"\xab" * 32
        packed = struct.pack(">H32s", PROTOCOL_VERSION, pubkey)
        assert len(packed) == HelloMessage.SIZE
        msg = HelloMessage.unpack(packed)
        assert msg.version == PROTOCOL_VERSION
        assert msg.identity_pubkey == pubkey

    def test_unpack_extra_bytes_ignored(self):
        """HelloMessage.unpack ignores trailing bytes."""
        pubkey = b"\xcd" * 32
        packed = struct.pack(">H32s", PROTOCOL_VERSION, pubkey) + b"extra"
        msg = HelloMessage.unpack(packed)
        assert msg.identity_pubkey == pubkey

    def test_round_trip_all_versions(self):
        """HelloMessage round-trips with various version numbers."""
        for version in (0, 1, 2, 65535):
            pubkey = bytes(range(32))
            hello = HelloMessage(version=version, identity_pubkey=pubkey)
            restored = HelloMessage.unpack(hello.pack())
            assert restored.version == version
            assert restored.identity_pubkey == pubkey


class TestKeyExchangeMessageValidation:
    """Tests for KeyExchangeMessage validation."""

    def test_unpack_too_short_raises(self):
        """KeyExchangeMessage.unpack raises on truncated data."""
        with pytest.raises(ValueError, match="KeyExchangeMessage too short"):
            KeyExchangeMessage.unpack(b"\x00" * 64)

    def test_unpack_exactly_minimum_size(self):
        """KeyExchangeMessage.unpack succeeds with exactly SIZE bytes."""
        eph = b"\x01" * 32
        ident = b"\x02" * 32
        sig = b"\x03" * 64
        packed = struct.pack(">32s32s64s", eph, ident, sig)
        assert len(packed) == KeyExchangeMessage.SIZE
        msg = KeyExchangeMessage.unpack(packed)
        assert msg.ephemeral_pubkey == eph
        assert msg.identity_pubkey == ident
        assert msg.signature == sig

    def test_round_trip(self):
        """KeyExchangeMessage round-trips correctly."""
        kex = KeyExchangeMessage(
            ephemeral_pubkey=b"\xaa" * 32,
            identity_pubkey=b"\xbb" * 32,
            signature=b"\xcc" * 64,
        )
        restored = KeyExchangeMessage.unpack(kex.pack())
        assert restored.ephemeral_pubkey == kex.ephemeral_pubkey
        assert restored.identity_pubkey == kex.identity_pubkey
        assert restored.signature == kex.signature


class TestSyncRequestValidation:
    """Tests for SyncRequest validation."""

    def test_unpack_too_short_raises(self):
        """SyncRequest.unpack raises on truncated data."""
        with pytest.raises(ValueError, match="SyncRequest too short"):
            SyncRequest.unpack(b"\x00" * 5)

    def test_round_trip_delta(self):
        """SyncRequest round-trips delta request."""
        req = SyncRequest(request_full=False, since_timestamp=9999999)
        restored = SyncRequest.unpack(req.pack())
        assert restored.request_full is False
        assert restored.since_timestamp == 9999999

    def test_round_trip_full(self):
        """SyncRequest round-trips full request."""
        req = SyncRequest(request_full=True, since_timestamp=0)
        restored = SyncRequest.unpack(req.pack())
        assert restored.request_full is True
        assert restored.since_timestamp == 0


class TestSyncResponseValidation:
    """Tests for SyncResponse validation."""

    def test_unpack_too_short_raises(self):
        """SyncResponse.unpack raises on truncated data."""
        with pytest.raises(ValueError, match="SyncResponse too short"):
            SyncResponse.unpack(b"\x00" * 4)

    def test_unpack_empty_data(self):
        """SyncResponse.unpack with exactly the header produces empty data."""
        packed = struct.pack(">BQ", ErrorCode.OK, 42)
        resp = SyncResponse.unpack(packed)
        assert resp.error_code == ErrorCode.OK
        assert resp.timestamp == 42
        assert resp.data == b""

    def test_round_trip_with_error(self):
        """SyncResponse round-trips error codes."""
        resp = SyncResponse(
            error_code=ErrorCode.SYNC_REJECTED,
            timestamp=123456,
            data=b"error detail",
        )
        restored = SyncResponse.unpack(resp.pack())
        assert restored.error_code == ErrorCode.SYNC_REJECTED
        assert restored.timestamp == 123456
        assert restored.data == b"error detail"


class TestErrorMessageValidation:
    """Tests for ErrorMessage validation."""

    def test_unpack_empty_raises(self):
        """ErrorMessage.unpack raises on empty data."""
        with pytest.raises(ValueError, match="ErrorMessage too short"):
            ErrorMessage.unpack(b"")

    def test_unpack_code_only(self):
        """ErrorMessage.unpack with just the error code produces empty message."""
        data = struct.pack(">B", ErrorCode.AUTH_FAILED)
        msg = ErrorMessage.unpack(data)
        assert msg.error_code == ErrorCode.AUTH_FAILED
        assert msg.message == ""

    def test_round_trip_unicode_message(self):
        """ErrorMessage round-trips unicode error messages."""
        err = ErrorMessage(error_code=ErrorCode.UNKNOWN_ERROR, message="Connection refused")
        restored = ErrorMessage.unpack(err.pack())
        assert restored.error_code == ErrorCode.UNKNOWN_ERROR
        assert restored.message == "Connection refused"


class TestBusyResponseValidation:
    """Tests for BusyResponse validation."""

    def test_unpack_too_short_raises(self):
        """BusyResponse.unpack raises on truncated data."""
        with pytest.raises(ValueError, match="BusyResponse too short"):
            BusyResponse.unpack(b"\x00" * 3)

    def test_round_trip_with_long_peer(self):
        """BusyResponse round-trips with a longer peer address."""
        peer = "very-long-hostname.local:5364"
        busy = BusyResponse(retry_after=30, current_peer=peer)
        restored = BusyResponse.unpack(busy.pack())
        assert restored.retry_after == 30
        assert restored.current_peer == peer

    def test_round_trip_zero_retry(self):
        """BusyResponse round-trips with zero retry."""
        busy = BusyResponse(retry_after=0, current_peer="")
        restored = BusyResponse.unpack(busy.pack())
        assert restored.retry_after == 0
        assert restored.current_peer == ""


class TestPeerInfoPackUnpack:
    """Tests for PeerInfo pack/unpack."""

    def test_pack_unpack_basic(self):
        """PeerInfo round-trips basic data."""
        info = PeerInfo(
            identity_fingerprint="abcd:1234:ef56:7890",
            hostname="my-laptop",
            address="192.168.1.42",
            port=5364,
            protocol_version=2,
            is_trusted=False,
        )
        packed = info.pack()
        restored = PeerInfo.unpack(packed)
        assert restored.identity_fingerprint == "abcd:1234:ef56:7890"
        assert restored.hostname == "my-laptop"
        assert restored.address == "192.168.1.42"
        assert restored.port == 5364

    def test_pack_unpack_empty_strings(self):
        """PeerInfo round-trips with empty strings."""
        info = PeerInfo(
            identity_fingerprint="",
            hostname="",
            address="",
            port=0,
            protocol_version=1,
        )
        packed = info.pack()
        restored = PeerInfo.unpack(packed)
        assert restored.identity_fingerprint == ""
        assert restored.hostname == ""
        assert restored.address == ""
        assert restored.port == 0

    def test_pack_unpack_unicode_hostname(self):
        """PeerInfo round-trips unicode hostname."""
        info = PeerInfo(
            identity_fingerprint="fp",
            hostname="host-name",
            address="10.0.0.1",
            port=9999,
            protocol_version=2,
        )
        packed = info.pack()
        restored = PeerInfo.unpack(packed)
        assert restored.hostname == "host-name"
        assert restored.port == 9999

    def test_unpack_truncated_data(self):
        """PeerInfo.unpack raises on data shorter than header."""
        with pytest.raises(struct.error):
            PeerInfo.unpack(b"\x00" * 4)


class TestMessageHeaderEdgeCases:
    """Additional edge-case tests for MessageHeader."""

    def test_unpack_invalid_message_type(self):
        """MessageHeader.unpack raises on unknown message type."""
        # Pack with an invalid message type (0xFE is not in MessageType)
        packed = struct.pack(">4sIBB", PROTOCOL_MAGIC, 0, 0xFE, 0)
        with pytest.raises(ValueError):
            MessageHeader.unpack(packed)

    def test_pack_preserves_flags(self):
        """MessageHeader preserves flags through round-trip."""
        header = MessageHeader(length=42, msg_type=MessageType.PING, flags=0xFF)
        restored = MessageHeader.unpack(header.pack())
        assert restored.flags == 0xFF
        assert restored.length == 42

    def test_large_payload_length(self):
        """MessageHeader handles large payload lengths."""
        header = MessageHeader(length=2**30, msg_type=MessageType.SYNC_RESPONSE, flags=0)
        restored = MessageHeader.unpack(header.pack())
        assert restored.length == 2**30


class TestProtocolHelpers:
    """Tests for protocol helper functions (create_* wrappers)."""

    def test_create_hello_ack(self):
        """create_hello_ack builds correct message type."""
        pubkey = b"\xee" * 32
        msg = create_hello_ack(pubkey)
        assert msg.header.msg_type == MessageType.HELLO_ACK
        hello = HelloMessage.unpack(msg.payload)
        assert hello.version == PROTOCOL_VERSION
        assert hello.identity_pubkey == pubkey

    def test_create_key_exchange(self):
        """create_key_exchange builds correct message."""
        eph = b"\x01" * 32
        ident = b"\x02" * 32
        sig = b"\x03" * 64
        msg = create_key_exchange(eph, ident, sig)
        assert msg.header.msg_type == MessageType.KEY_EXCHANGE
        kex = KeyExchangeMessage.unpack(msg.payload)
        assert kex.ephemeral_pubkey == eph
        assert kex.identity_pubkey == ident
        assert kex.signature == sig

    def test_create_key_exchange_ack(self):
        """create_key_exchange_ack builds correct message."""
        eph = b"\x11" * 32
        ident = b"\x22" * 32
        sig = b"\x33" * 64
        msg = create_key_exchange_ack(eph, ident, sig)
        assert msg.header.msg_type == MessageType.KEY_EXCHANGE_ACK
        kex = KeyExchangeMessage.unpack(msg.payload)
        assert kex.ephemeral_pubkey == eph

    def test_create_sync_request_delta(self):
        """create_sync_request with delta parameters."""
        msg = create_sync_request(full=False, since=55555)
        assert msg.header.msg_type == MessageType.SYNC_REQUEST
        req = SyncRequest.unpack(msg.payload)
        assert req.request_full is False
        assert req.since_timestamp == 55555

    def test_create_sync_response_with_error(self):
        """create_sync_response with error code."""
        msg = create_sync_response(b"data", timestamp=100, error=ErrorCode.SYNC_REJECTED)
        assert msg.header.msg_type == MessageType.SYNC_RESPONSE
        resp = SyncResponse.unpack(msg.payload)
        assert resp.error_code == ErrorCode.SYNC_REJECTED
        assert resp.timestamp == 100
        assert resp.data == b"data"

    def test_create_error_empty_message(self):
        """create_error with empty message string."""
        msg = create_error(ErrorCode.PERMISSION_DENIED)
        assert msg.header.msg_type == MessageType.ERROR
        err = ErrorMessage.unpack(msg.payload)
        assert err.error_code == ErrorCode.PERMISSION_DENIED
        assert err.message == ""

    def test_create_busy_response_defaults(self):
        """create_busy_response with defaults."""
        msg = create_busy_response()
        assert msg.header.msg_type == MessageType.ERROR
        # First byte is SERVER_BUSY error code
        assert msg.payload[0] == ErrorCode.SERVER_BUSY
        busy = BusyResponse.unpack(msg.payload[1:])
        assert busy.retry_after == 5
        assert busy.current_peer == ""

    def test_create_busy_response_custom(self):
        """create_busy_response with custom values."""
        msg = create_busy_response(retry_after=15, current_peer="10.0.0.1:5364")
        busy = BusyResponse.unpack(msg.payload[1:])
        assert busy.retry_after == 15
        assert busy.current_peer == "10.0.0.1:5364"

    def test_create_ping_pong(self):
        """create_ping and create_pong produce empty payloads."""
        ping = create_ping()
        assert ping.header.msg_type == MessageType.PING
        assert ping.payload == b""
        assert ping.header.length == 0

        pong = create_pong()
        assert pong.header.msg_type == MessageType.PONG
        assert pong.payload == b""
        assert pong.header.length == 0


class TestMessagePackRoundTrip:
    """Tests for full Message pack/unpack round trips."""

    def test_message_pack_includes_header_and_payload(self):
        """Message.pack concatenates header + payload."""
        msg = Message.create(MessageType.HELLO, b"hello-payload")
        packed = msg.pack()
        assert packed[:4] == PROTOCOL_MAGIC
        assert packed[MessageHeader.HEADER_SIZE :] == b"hello-payload"

    def test_message_create_auto_sizes_header(self):
        """Message.create sets header length to payload size."""
        payload = b"x" * 200
        msg = Message.create(MessageType.SYNC_RESPONSE, payload)
        assert msg.header.length == 200

    def test_message_empty_payload(self):
        """Message with empty payload packs correctly."""
        msg = Message.create(MessageType.PING, b"")
        packed = msg.pack()
        assert len(packed) == MessageHeader.HEADER_SIZE
        header = MessageHeader.unpack(packed)
        assert header.length == 0


# ---------------------------------------------------------------------------
#  sync_queue.py — queue management
# ---------------------------------------------------------------------------


class TestSyncQueueConstruction:
    """Tests for SyncQueue construction and basic methods."""

    def test_sync_queue_init(self):
        """SyncQueue initializes with correct defaults."""
        from pytodo_qt.net.sync_queue import SyncQueue

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        assert queue._client is mock_client
        assert queue._current is None
        assert queue._running is False
        assert queue.get_queue_size() == 0
        assert queue.is_busy() is False
        assert queue.get_current_operation() is None

    def test_get_result_returns_none_for_unknown(self):
        """get_result returns None for unknown operation ID."""
        from pytodo_qt.net.sync_queue import SyncQueue

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        assert queue.get_result("nonexistent-id") is None

    def test_get_result_returns_stored_result(self):
        """get_result returns stored result when available."""
        from pytodo_qt.net.sync_queue import SyncQueue, SyncResult, SyncStatus

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        result = SyncResult(success=True, status=SyncStatus.SUCCESS)
        queue._results["op-123"] = result
        assert queue.get_result("op-123") is result

    def test_is_busy_when_current_set(self):
        """is_busy returns True when _current is set."""
        from pytodo_qt.net.sync_queue import SyncQueue

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        queue._current = MagicMock()
        assert queue.is_busy() is True

    def test_get_current_operation(self):
        """get_current_operation returns current operation."""
        from pytodo_qt.net.sync_queue import SyncQueue

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        op = MagicMock()
        queue._current = op
        assert queue.get_current_operation() is op


class TestSyncQueueStartStop:
    """Tests for SyncQueue start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        """start() creates processing task and sets running flag."""
        from pytodo_qt.net.sync_queue import SyncQueue

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        await queue.start()
        assert queue._running is True
        assert queue._process_task is not None
        # Cleanup
        await queue.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        """start() is idempotent — calling twice does not create two tasks."""
        from pytodo_qt.net.sync_queue import SyncQueue

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        await queue.start()
        task1 = queue._process_task
        await queue.start()
        assert queue._process_task is task1
        await queue.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """stop() cancels the process task."""
        from pytodo_qt.net.sync_queue import SyncQueue

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        await queue.start()
        assert queue._running is True
        await queue.stop()
        assert queue._running is False
        assert queue._process_task is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        """stop() is safe when not started."""
        from pytodo_qt.net.sync_queue import SyncQueue

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        await queue.stop()
        assert queue._running is False


class TestSyncQueueEnqueue:
    """Tests for SyncQueue enqueue operations."""

    @pytest.mark.asyncio
    async def test_enqueue_returns_operation_id(self):
        """enqueue() returns the operation's string ID."""
        from pytodo_qt.net.sync_queue import SyncQueue, create_pull_operation

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        op = create_pull_operation("host", 5364)
        op_id = await queue.enqueue(op)
        assert op_id == str(op.id)
        assert queue.get_queue_size() == 1

    @pytest.mark.asyncio
    async def test_enqueue_multiple(self):
        """enqueue() adds multiple operations."""
        from pytodo_qt.net.sync_queue import SyncQueue, create_pull_operation

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        await queue.enqueue(create_pull_operation("h1", 5364))
        await queue.enqueue(create_pull_operation("h2", 5364))
        assert queue.get_queue_size() == 2

    def test_enqueue_sync_with_running_loop(self):
        """enqueue_sync uses ensure_future when loop is running."""
        from pytodo_qt.net.sync_queue import SyncQueue, create_pull_operation

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        op = create_pull_operation("host", 5364)

        loop = asyncio.new_event_loop()
        try:
            # Simulate calling from within a running loop
            async def _test():
                op_id = queue.enqueue_sync(op)
                assert op_id == str(op.id)

            loop.run_until_complete(_test())
        finally:
            loop.close()

    def test_enqueue_sync_no_loop(self):
        """enqueue_sync handles missing event loop gracefully."""
        from pytodo_qt.net.sync_queue import SyncQueue, create_pull_operation

        mock_client = MagicMock()
        queue = SyncQueue(mock_client)
        op = create_pull_operation("host", 5364)
        # No running loop — should log warning but not raise
        op_id = queue.enqueue_sync(op)
        assert op_id == str(op.id)


class TestSyncQueueProcessLoop:
    """Tests for SyncQueue _process_loop execution."""

    @pytest.mark.asyncio
    async def test_process_pull_success(self):
        """Process loop handles a successful pull operation."""
        from pytodo_qt.net.sync_queue import SyncQueue, SyncStatus, create_pull_operation

        mock_client = MagicMock()
        mock_client.sync_pull = AsyncMock(return_value=(True, b"sync-data"))
        mock_client.get_last_busy_response = MagicMock(return_value=None)
        mock_client.had_connection_error = MagicMock(return_value=False)

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_pull_operation("host", 5364)
        await queue.enqueue(op)

        # Wait for processing
        await asyncio.sleep(0.1)
        await queue.stop()

        result = queue.get_result(str(op.id))
        assert result is not None
        assert result.success is True
        assert result.data == b"sync-data"
        assert result.status == SyncStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_process_push_success(self):
        """Process loop handles a successful push operation."""
        from pytodo_qt.net.sync_queue import SyncQueue, SyncStatus, create_push_operation

        mock_client = MagicMock()
        mock_client.sync_push = AsyncMock(return_value=True)
        mock_client.get_last_busy_response = MagicMock(return_value=None)
        mock_client.had_connection_error = MagicMock(return_value=False)

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_push_operation("host", 5364, b"push-data")
        await queue.enqueue(op)

        await asyncio.sleep(0.1)
        await queue.stop()

        result = queue.get_result(str(op.id))
        assert result is not None
        assert result.success is True
        assert result.status == SyncStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_process_pull_failure(self):
        """Process loop handles a failed pull operation."""
        from pytodo_qt.net.sync_queue import SyncQueue, SyncStatus, create_pull_operation

        mock_client = MagicMock()
        mock_client.sync_pull = AsyncMock(return_value=(False, b""))
        mock_client.get_last_busy_response = MagicMock(return_value=None)
        mock_client.had_connection_error = MagicMock(return_value=False)

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_pull_operation("host", 5364)
        await queue.enqueue(op)

        await asyncio.sleep(0.1)
        await queue.stop()

        result = queue.get_result(str(op.id))
        assert result is not None
        assert result.success is False
        assert result.status == SyncStatus.FAILED

    @pytest.mark.asyncio
    async def test_process_push_failure(self):
        """Process loop handles a failed push operation."""
        from pytodo_qt.net.sync_queue import SyncQueue, SyncStatus, create_push_operation

        mock_client = MagicMock()
        mock_client.sync_push = AsyncMock(return_value=False)
        mock_client.get_last_busy_response = MagicMock(return_value=None)
        mock_client.had_connection_error = MagicMock(return_value=False)

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_push_operation("host", 5364, b"data")
        await queue.enqueue(op)

        await asyncio.sleep(0.1)
        await queue.stop()

        result = queue.get_result(str(op.id))
        assert result is not None
        assert result.success is False
        assert result.status == SyncStatus.FAILED

    @pytest.mark.asyncio
    async def test_process_pull_busy_no_retry(self):
        """Pull that gets busy response with exhausted retries fails."""
        from pytodo_qt.net.sync_queue import SyncQueue, SyncStatus, create_pull_operation

        mock_client = MagicMock()
        mock_client.sync_pull = AsyncMock(return_value=(False, b""))
        mock_client.get_last_busy_response = MagicMock(
            return_value=BusyResponse(retry_after=1, current_peer="peer")
        )
        mock_client.had_connection_error = MagicMock(return_value=False)
        mock_client._last_busy_response = BusyResponse(retry_after=1, current_peer="peer")

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_pull_operation("host", 5364)
        op.max_retries = 0  # No retries allowed
        await queue.enqueue(op)

        await asyncio.sleep(0.1)
        await queue.stop()

        result = queue.get_result(str(op.id))
        assert result is not None
        assert result.success is False
        assert result.status == SyncStatus.BUSY_RETRY

    @pytest.mark.asyncio
    async def test_process_push_connection_error_no_retry(self):
        """Push that gets connection error with no retries fails."""
        from pytodo_qt.net.sync_queue import SyncQueue, SyncStatus, create_push_operation

        mock_client = MagicMock()
        mock_client.sync_push = AsyncMock(return_value=False)
        mock_client.get_last_busy_response = MagicMock(return_value=None)
        mock_client.had_connection_error = MagicMock(return_value=True)

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_push_operation("host", 5364, b"data")
        op.max_retries = 0
        await queue.enqueue(op)

        await asyncio.sleep(0.1)
        await queue.stop()

        result = queue.get_result(str(op.id))
        assert result is not None
        assert result.success is False
        assert result.status == SyncStatus.CONNECTION_RETRY

    @pytest.mark.asyncio
    async def test_process_exception_in_execution(self):
        """Process loop handles exceptions during operation execution."""
        from pytodo_qt.net.sync_queue import SyncQueue, create_pull_operation

        mock_client = MagicMock()
        mock_client.sync_pull = AsyncMock(side_effect=RuntimeError("network error"))

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_pull_operation("host", 5364)
        await queue.enqueue(op)

        await asyncio.sleep(0.1)
        await queue.stop()

        result = queue.get_result(str(op.id))
        assert result is not None
        assert result.success is False
        assert "network error" in result.error

    @pytest.mark.asyncio
    async def test_process_pull_connection_error_no_retry(self):
        """Pull that gets connection error with no retries returns CONNECTION_RETRY."""
        from pytodo_qt.net.sync_queue import SyncQueue, SyncStatus, create_pull_operation

        mock_client = MagicMock()
        mock_client.sync_pull = AsyncMock(return_value=(False, b""))
        mock_client.get_last_busy_response = MagicMock(return_value=None)
        mock_client.had_connection_error = MagicMock(return_value=True)

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_pull_operation("host", 5364)
        op.max_retries = 0
        await queue.enqueue(op)

        await asyncio.sleep(0.1)
        await queue.stop()

        result = queue.get_result(str(op.id))
        assert result is not None
        assert result.success is False
        assert result.status == SyncStatus.CONNECTION_RETRY

    @pytest.mark.asyncio
    async def test_process_push_busy_no_retry(self):
        """Push that gets busy response with exhausted retries fails."""
        from pytodo_qt.net.sync_queue import SyncQueue, SyncStatus, create_push_operation

        mock_client = MagicMock()
        mock_client.sync_push = AsyncMock(return_value=False)
        mock_client.get_last_busy_response = MagicMock(
            return_value=BusyResponse(retry_after=1, current_peer="peer")
        )
        mock_client._last_busy_response = BusyResponse(retry_after=1, current_peer="peer")
        mock_client.had_connection_error = MagicMock(return_value=False)

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_push_operation("host", 5364, b"data")
        op.max_retries = 0
        await queue.enqueue(op)

        await asyncio.sleep(0.1)
        await queue.stop()

        result = queue.get_result(str(op.id))
        assert result is not None
        assert result.success is False
        assert result.status == SyncStatus.BUSY_RETRY


class TestSyncQueueExecute:
    """Tests for SyncQueue.execute (await result)."""

    @pytest.mark.asyncio
    async def test_execute_returns_result(self):
        """execute() returns the SyncResult via a future."""
        from pytodo_qt.net.sync_queue import SyncQueue, create_pull_operation

        mock_client = MagicMock()
        mock_client.sync_pull = AsyncMock(return_value=(True, b"data"))
        mock_client.get_last_busy_response = MagicMock(return_value=None)
        mock_client.had_connection_error = MagicMock(return_value=False)

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_pull_operation("host", 5364)
        result = await asyncio.wait_for(queue.execute(op), timeout=2.0)

        assert result is not None
        assert result.success is True
        assert result.data == b"data"

        await queue.stop()


class TestSyncQueueRetry:
    """Tests for SyncQueue retry logic."""

    @pytest.mark.asyncio
    async def test_busy_retry_succeeds_on_second_attempt(self):
        """Operation retries on busy and succeeds on the second attempt."""
        from pytodo_qt.net.sync_queue import SyncQueue, create_pull_operation

        call_count = 0

        async def mock_sync_pull(host, port):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return False, b""
            return True, b"data"

        mock_client = MagicMock()
        mock_client.sync_pull = mock_sync_pull

        busy_resp = BusyResponse(retry_after=0, current_peer="peer")
        # First call returns busy, second returns None (success path)
        mock_client.get_last_busy_response = MagicMock(side_effect=[busy_resp, None])
        mock_client._last_busy_response = busy_resp
        mock_client.had_connection_error = MagicMock(return_value=False)

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_pull_operation("host", 5364)
        op.max_retries = 3
        with patch("pytodo_qt.net.sync_queue.asyncio.sleep", new=AsyncMock()):
            result = await asyncio.wait_for(queue.execute(op), timeout=5.0)

        assert result.success is True
        assert call_count == 2

        await queue.stop()

    @pytest.mark.asyncio
    async def test_connection_retry_succeeds_on_second_attempt(self):
        """Operation retries on connection error and succeeds."""
        from pytodo_qt.net.sync_queue import SyncQueue, create_pull_operation

        call_count = 0

        async def mock_sync_pull(host, port):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return False, b""
            return True, b"result"

        mock_client = MagicMock()
        mock_client.sync_pull = mock_sync_pull
        mock_client.get_last_busy_response = MagicMock(return_value=None)
        # First call: connection error; second call: no error
        mock_client.had_connection_error = MagicMock(side_effect=[True, False])

        queue = SyncQueue(mock_client)
        await queue.start()

        op = create_pull_operation("host", 5364)
        op.max_retries = 3
        with patch("pytodo_qt.net.sync_queue.asyncio.sleep", new=AsyncMock()):
            result = await asyncio.wait_for(queue.execute(op), timeout=5.0)

        assert result.success is True
        assert call_count == 2

        await queue.stop()


# ---------------------------------------------------------------------------
#  client.py — connection handling, request/response patterns
# ---------------------------------------------------------------------------


def _make_client():
    """Create an AsyncClient with mocked identity."""
    with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
        from pytodo_qt.crypto.key_exchange import IdentityKeyPair

        keypair = IdentityKeyPair.generate()
        mock_identity.return_value = MagicMock(keypair=keypair)
        client = AsyncClient()
    return client


class TestAsyncClientAccessors:
    """Tests for AsyncClient accessor methods."""

    def test_get_last_busy_response_none(self):
        """get_last_busy_response returns None initially."""
        client = _make_client()
        assert client.get_last_busy_response() is None

    def test_get_last_busy_response_set(self):
        """get_last_busy_response returns stored response."""
        client = _make_client()
        busy = BusyResponse(retry_after=10, current_peer="peer")
        client._last_busy_response = busy
        assert client.get_last_busy_response() is busy

    def test_had_connection_error_initially_false(self):
        """had_connection_error returns False initially."""
        client = _make_client()
        assert client.had_connection_error() is False

    def test_clear_connection_error(self):
        """clear_connection_error resets the flag."""
        client = _make_client()
        client._last_connection_error = True
        assert client.had_connection_error() is True
        client.clear_connection_error()
        assert client.had_connection_error() is False

    def test_get_last_peer_fingerprint_none(self):
        """get_last_peer_fingerprint returns None initially."""
        client = _make_client()
        assert client.get_last_peer_fingerprint() is None

    def test_get_last_peer_fingerprint_set(self):
        """get_last_peer_fingerprint returns stored fingerprint."""
        client = _make_client()
        client._last_peer_fingerprint = "ab:cd:ef:12"
        assert client.get_last_peer_fingerprint() == "ab:cd:ef:12"


class TestAsyncClientConnect:
    """Tests for AsyncClient.connect error handling."""

    @pytest.mark.asyncio
    async def test_connect_os_error(self):
        """connect handles OSError (connection refused)."""
        client = _make_client()
        with patch("asyncio.open_connection", side_effect=OSError("refused")):
            result = await client.connect("host", 5364)
        assert result is False
        assert client.had_connection_error() is True

    @pytest.mark.asyncio
    async def test_connect_generic_exception(self):
        """connect handles unexpected exceptions."""
        client = _make_client()
        with patch("asyncio.open_connection", side_effect=RuntimeError("unexpected")):
            result = await client.connect("host", 5364)
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_timeout_sets_error_flag(self):
        """connect sets connection error flag on timeout."""
        client = _make_client()
        with patch(
            "asyncio.wait_for",
            side_effect=TimeoutError(),
        ):
            result = await client.connect("host", 5364)
        assert result is False
        assert client.had_connection_error() is True

    @pytest.mark.asyncio
    async def test_close_connection_when_connected(self):
        """close_connection closes writer and clears state."""
        client = _make_client()
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        client._connection = ConnectionState(reader=MagicMock(), writer=mock_writer)
        await client.close_connection()
        mock_writer.close.assert_called_once()
        assert client._connection is None

    @pytest.mark.asyncio
    async def test_close_connection_writer_error(self):
        """close_connection handles writer errors gracefully."""
        client = _make_client()
        mock_writer = MagicMock()
        mock_writer.close = MagicMock(side_effect=OSError("broken pipe"))
        mock_writer.wait_closed = AsyncMock(side_effect=OSError("broken pipe"))
        client._connection = ConnectionState(reader=MagicMock(), writer=mock_writer)
        # Should not raise
        await client.close_connection()
        assert client._connection is None


class TestAsyncClientSyncPull:
    """Tests for AsyncClient.sync_pull."""

    @pytest.mark.asyncio
    async def test_sync_pull_connect_failure(self):
        """sync_pull returns failure when connect fails."""
        client = _make_client()
        with patch.object(client, "connect", new=AsyncMock(return_value=False)):
            success, data = await client.sync_pull("host", 5364)
        assert success is False
        assert data == b""

    @pytest.mark.asyncio
    async def test_sync_pull_no_response(self):
        """sync_pull returns failure on no response."""
        client = _make_client()
        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=None)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, data = await client.sync_pull("host", 5364)
        assert success is False

    @pytest.mark.asyncio
    async def test_sync_pull_error_response(self):
        """sync_pull handles ERROR response."""
        client = _make_client()
        err_msg = ErrorMessage(error_code=ErrorCode.PERMISSION_DENIED, message="denied")
        error_message = Message.create(MessageType.ERROR, err_msg.pack())

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=error_message)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, data = await client.sync_pull("host", 5364)
        assert success is False

    @pytest.mark.asyncio
    async def test_sync_pull_busy_response(self):
        """sync_pull handles SERVER_BUSY response and stores busy info."""
        client = _make_client()
        busy = BusyResponse(retry_after=5, current_peer="other-peer")
        payload = struct.pack(">B", ErrorCode.SERVER_BUSY) + busy.pack()
        busy_msg = Message.create(MessageType.ERROR, payload)

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=busy_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, data = await client.sync_pull("host", 5364)
        assert success is False
        assert client._last_busy_response is not None
        assert client._last_busy_response.retry_after == 5

    @pytest.mark.asyncio
    async def test_sync_pull_busy_response_parse_error(self):
        """sync_pull handles unparseable busy response gracefully."""
        client = _make_client()
        # SERVER_BUSY error code but truncated busy data
        payload = struct.pack(">B", ErrorCode.SERVER_BUSY) + b"\x00"
        busy_msg = Message.create(MessageType.ERROR, payload)

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=busy_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, data = await client.sync_pull("host", 5364)
        assert success is False

    @pytest.mark.asyncio
    async def test_sync_pull_unexpected_message_type(self):
        """sync_pull handles unexpected message type."""
        client = _make_client()
        wrong_msg = Message.create(MessageType.PING, b"")

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=wrong_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, data = await client.sync_pull("host", 5364)
        assert success is False

    @pytest.mark.asyncio
    async def test_sync_pull_sync_error_code(self):
        """sync_pull handles SYNC_RESPONSE with non-OK error code."""
        client = _make_client()
        resp = SyncResponse(error_code=ErrorCode.SYNC_REJECTED, timestamp=0, data=b"")
        resp_msg = Message.create(MessageType.SYNC_RESPONSE, resp.pack())

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=resp_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, data = await client.sync_pull("host", 5364)
        assert success is False

    @pytest.mark.asyncio
    async def test_sync_pull_success(self):
        """sync_pull returns data on success."""
        client = _make_client()
        resp = SyncResponse(error_code=ErrorCode.OK, timestamp=100, data=b"sync-payload")
        resp_msg = Message.create(MessageType.SYNC_RESPONSE, resp.pack())

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=resp_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, data = await client.sync_pull("host", 5364)
        assert success is True
        assert data == b"sync-payload"

    @pytest.mark.asyncio
    async def test_sync_pull_exception(self):
        """sync_pull handles exceptions during operation."""
        client = _make_client()

        with (
            patch.object(client, "connect", new=AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, data = await client.sync_pull("host", 5364)
        assert success is False
        assert data == b""


class TestAsyncClientSyncPush:
    """Tests for AsyncClient.sync_push."""

    @pytest.mark.asyncio
    async def test_sync_push_connect_failure(self):
        """sync_push returns failure when connect fails."""
        client = _make_client()
        with patch.object(client, "connect", new=AsyncMock(return_value=False)):
            result = await client.sync_push("host", 5364, b"data")
        assert result is False

    @pytest.mark.asyncio
    async def test_sync_push_no_acknowledgment(self):
        """sync_push returns failure on no acknowledgment."""
        client = _make_client()
        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=None)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            result = await client.sync_push("host", 5364, b"data")
        assert result is False

    @pytest.mark.asyncio
    async def test_sync_push_error_response(self):
        """sync_push handles ERROR response."""
        client = _make_client()
        err_msg = ErrorMessage(error_code=ErrorCode.PERMISSION_DENIED, message="no push")
        error_message = Message.create(MessageType.ERROR, err_msg.pack())

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=error_message)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            result = await client.sync_push("host", 5364, b"data")
        assert result is False

    @pytest.mark.asyncio
    async def test_sync_push_busy_response(self):
        """sync_push handles SERVER_BUSY response."""
        client = _make_client()
        busy = BusyResponse(retry_after=10, current_peer="peer")
        payload = struct.pack(">B", ErrorCode.SERVER_BUSY) + busy.pack()
        busy_msg = Message.create(MessageType.ERROR, payload)

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=busy_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            result = await client.sync_push("host", 5364, b"data")
        assert result is False
        assert client._last_busy_response is not None

    @pytest.mark.asyncio
    async def test_sync_push_busy_parse_error(self):
        """sync_push handles unparseable busy response gracefully."""
        client = _make_client()
        payload = struct.pack(">B", ErrorCode.SERVER_BUSY) + b"\x00"
        busy_msg = Message.create(MessageType.ERROR, payload)

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=busy_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            result = await client.sync_push("host", 5364, b"data")
        assert result is False

    @pytest.mark.asyncio
    async def test_sync_push_unexpected_response_type(self):
        """sync_push handles unexpected response type."""
        client = _make_client()
        wrong_msg = Message.create(MessageType.PONG, b"")

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=wrong_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            result = await client.sync_push("host", 5364, b"data")
        assert result is False

    @pytest.mark.asyncio
    async def test_sync_push_success(self):
        """sync_push returns True on successful DELTA_ACK."""
        client = _make_client()
        ack_msg = Message.create(MessageType.DELTA_ACK, b"")

        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=ack_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            result = await client.sync_push("host", 5364, b"data")
        assert result is True

    @pytest.mark.asyncio
    async def test_sync_push_exception(self):
        """sync_push handles exceptions during operation."""
        client = _make_client()

        with (
            patch.object(client, "connect", new=AsyncMock(side_effect=RuntimeError("crash"))),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            result = await client.sync_push("host", 5364, b"data")
        assert result is False


class TestAsyncClientPing:
    """Tests for AsyncClient.ping."""

    @pytest.mark.asyncio
    async def test_ping_connect_failure(self):
        """ping returns failure when connect fails."""
        client = _make_client()
        with (
            patch.object(client, "connect", new=AsyncMock(return_value=False)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, latency = await client.ping("host", 5364)
        assert success is False
        assert latency == 0.0

    @pytest.mark.asyncio
    async def test_ping_no_response(self):
        """ping returns failure on no response."""
        client = _make_client()
        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=None)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, latency = await client.ping("host", 5364)
        assert success is False

    @pytest.mark.asyncio
    async def test_ping_wrong_response_type(self):
        """ping returns failure on non-PONG response."""
        client = _make_client()
        wrong_msg = Message.create(MessageType.PING, b"")
        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=wrong_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, latency = await client.ping("host", 5364)
        assert success is False

    @pytest.mark.asyncio
    async def test_ping_success(self):
        """ping returns success and positive latency on PONG."""
        client = _make_client()
        pong_msg = Message.create(MessageType.PONG, b"")
        with (
            patch.object(client, "connect", new=AsyncMock(return_value=True)),
            patch.object(client, "_send_message", new=AsyncMock()),
            patch.object(client, "_recv_message", new=AsyncMock(return_value=pong_msg)),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, latency = await client.ping("host", 5364)
        assert success is True
        assert latency >= 0.0

    @pytest.mark.asyncio
    async def test_ping_exception(self):
        """ping handles exceptions."""
        client = _make_client()
        with (
            patch.object(client, "connect", new=AsyncMock(side_effect=RuntimeError("fail"))),
            patch.object(client, "close_connection", new=AsyncMock()),
        ):
            success, latency = await client.ping("host", 5364)
        assert success is False
        assert latency == 0.0


class TestAsyncClientSendRecv:
    """Tests for AsyncClient send/receive methods."""

    @pytest.mark.asyncio
    async def test_send_message_not_connected_raises(self):
        """_send_message raises when not connected."""
        client = _make_client()
        msg = Message.create(MessageType.PING, b"")
        with pytest.raises(RuntimeError, match="Not connected"):
            await client._send_message(msg)

    @pytest.mark.asyncio
    async def test_send_message_unauthenticated_sends_raw(self):
        """_send_message sends raw when not authenticated."""
        client = _make_client()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        from pytodo_qt.net.client import ConnectionState

        client._connection = ConnectionState(
            reader=MagicMock(), writer=mock_writer, is_authenticated=False
        )
        msg = Message.create(MessageType.PING, b"test")
        await client._send_message(msg)
        mock_writer.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_authenticated_encrypts(self):
        """_send_message encrypts when authenticated."""
        client = _make_client()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_cipher = MagicMock()
        mock_cipher.encrypt_bytes = MagicMock(return_value=b"encrypted-payload")
        from pytodo_qt.net.client import ConnectionState

        client._connection = ConnectionState(
            reader=MagicMock(),
            writer=mock_writer,
            is_authenticated=True,
            encrypt_cipher=mock_cipher,
        )
        msg = Message.create(MessageType.PING, b"plaintext")
        await client._send_message(msg)
        mock_cipher.encrypt_bytes.assert_called_once_with(b"plaintext")
        mock_writer.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_recv_message_raw_timeout(self):
        """_recv_message_raw returns None on timeout."""
        client = _make_client()
        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=TimeoutError())
        from pytodo_qt.net.client import ConnectionState

        client._connection = ConnectionState(reader=mock_reader, writer=MagicMock())

        with patch("asyncio.wait_for", side_effect=TimeoutError()):
            result = await client._recv_message_raw()
        assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_raw_incomplete_read(self):
        """_recv_message_raw returns None on IncompleteReadError."""
        client = _make_client()
        mock_reader = AsyncMock()
        from pytodo_qt.net.client import ConnectionState

        client._connection = ConnectionState(reader=mock_reader, writer=MagicMock())

        with patch(
            "asyncio.wait_for",
            side_effect=asyncio.IncompleteReadError(b"partial", 10),
        ):
            result = await client._recv_message_raw()
        assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_raw_generic_error(self):
        """_recv_message_raw returns None on generic exception."""
        client = _make_client()
        mock_reader = AsyncMock()
        from pytodo_qt.net.client import ConnectionState

        client._connection = ConnectionState(reader=mock_reader, writer=MagicMock())

        with patch("asyncio.wait_for", side_effect=RuntimeError("read error")):
            result = await client._recv_message_raw()
        assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_encrypted_timeout(self):
        """_recv_message returns None on timeout when authenticated."""
        client = _make_client()
        mock_cipher = MagicMock()
        from pytodo_qt.net.client import ConnectionState

        client._connection = ConnectionState(
            reader=AsyncMock(),
            writer=MagicMock(),
            is_authenticated=True,
            decrypt_cipher=mock_cipher,
        )

        with patch("asyncio.wait_for", side_effect=TimeoutError()):
            result = await client._recv_message()
        assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_encrypted_incomplete(self):
        """_recv_message returns None on IncompleteReadError when authenticated."""
        client = _make_client()
        mock_cipher = MagicMock()
        from pytodo_qt.net.client import ConnectionState

        client._connection = ConnectionState(
            reader=AsyncMock(),
            writer=MagicMock(),
            is_authenticated=True,
            decrypt_cipher=mock_cipher,
        )

        with patch(
            "asyncio.wait_for",
            side_effect=asyncio.IncompleteReadError(b"", 10),
        ):
            result = await client._recv_message()
        assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_encrypted_decrypt_error(self):
        """_recv_message returns None on decryption error."""
        client = _make_client()
        mock_cipher = MagicMock()
        from pytodo_qt.net.client import ConnectionState

        client._connection = ConnectionState(
            reader=AsyncMock(),
            writer=MagicMock(),
            is_authenticated=True,
            decrypt_cipher=mock_cipher,
        )

        with patch("asyncio.wait_for", side_effect=RuntimeError("decrypt fail")):
            result = await client._recv_message()
        assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_not_connected(self):
        """_recv_message returns None when not connected."""
        client = _make_client()
        result = await client._recv_message()
        assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_unauthenticated_delegates(self):
        """_recv_message delegates to _recv_message_raw when not authenticated."""
        client = _make_client()
        from pytodo_qt.net.client import ConnectionState

        client._connection = ConnectionState(
            reader=AsyncMock(), writer=MagicMock(), is_authenticated=False
        )
        with patch.object(client, "_recv_message_raw", new=AsyncMock(return_value=None)) as m:
            result = await client._recv_message()
        assert result is None
        m.assert_called_once()


class TestAsyncClientHandshake:
    """Tests for AsyncClient._perform_handshake edge cases."""

    @pytest.mark.asyncio
    async def test_handshake_unexpected_hello_ack(self):
        """Handshake fails on unexpected message instead of HELLO_ACK."""
        client = _make_client()
        from pytodo_qt.net.client import ConnectionState

        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        client._connection = ConnectionState(reader=MagicMock(), writer=mock_writer)

        wrong_msg = Message.create(MessageType.ERROR, b"\x00")
        with (
            patch.object(client, "_send_message_raw", new=AsyncMock()),
            patch.object(client, "_recv_message_raw", new=AsyncMock(return_value=wrong_msg)),
        ):
            result = await client._perform_handshake()
        assert result is False

    @pytest.mark.asyncio
    async def test_handshake_no_hello_ack(self):
        """Handshake fails on None HELLO_ACK response."""
        client = _make_client()
        from pytodo_qt.net.client import ConnectionState

        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        client._connection = ConnectionState(reader=MagicMock(), writer=mock_writer)

        with (
            patch.object(client, "_send_message_raw", new=AsyncMock()),
            patch.object(client, "_recv_message_raw", new=AsyncMock(return_value=None)),
        ):
            result = await client._perform_handshake()
        assert result is False

    @pytest.mark.asyncio
    async def test_handshake_version_mismatch(self):
        """Handshake fails on protocol version mismatch."""
        client = _make_client()
        from pytodo_qt.net.client import ConnectionState

        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        client._connection = ConnectionState(reader=MagicMock(), writer=mock_writer)

        # Build a HELLO_ACK with wrong version
        wrong_version_hello = HelloMessage(version=99, identity_pubkey=b"\x00" * 32)
        ack_msg = Message.create(MessageType.HELLO_ACK, wrong_version_hello.pack())

        with (
            patch.object(client, "_send_message_raw", new=AsyncMock()),
            patch.object(client, "_recv_message_raw", new=AsyncMock(return_value=ack_msg)),
        ):
            result = await client._perform_handshake()
        assert result is False

    @pytest.mark.asyncio
    async def test_handshake_no_kex_ack(self):
        """Handshake fails when KEY_EXCHANGE_ACK is None."""
        client = _make_client()
        from pytodo_qt.net.client import ConnectionState

        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        client._connection = ConnectionState(reader=MagicMock(), writer=mock_writer)

        # First recv returns HELLO_ACK, second returns None
        hello_ack = HelloMessage(version=PROTOCOL_VERSION, identity_pubkey=b"\x00" * 32)
        ack_msg = Message.create(MessageType.HELLO_ACK, hello_ack.pack())

        call_count = 0

        async def mock_recv():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ack_msg
            return None

        with (
            patch.object(client, "_send_message_raw", new=AsyncMock()),
            patch.object(client, "_recv_message_raw", new=mock_recv),
        ):
            result = await client._perform_handshake()
        assert result is False

    @pytest.mark.asyncio
    async def test_handshake_exception(self):
        """Handshake returns False on exception."""
        client = _make_client()

        client._connection = ConnectionState(reader=MagicMock(), writer=MagicMock())

        with patch.object(
            client, "_send_message_raw", new=AsyncMock(side_effect=RuntimeError("send fail"))
        ):
            result = await client._perform_handshake()
        assert result is False


# ---------------------------------------------------------------------------
#  server.py — message handling, sync lock, handshake, callbacks
# ---------------------------------------------------------------------------


class TestServerSyncLock:
    """Tests for server sync lock mechanism."""

    @pytest.mark.asyncio
    async def test_release_sync_lock_when_locked(self):
        """_release_sync_lock releases a locked lock."""
        server = AsyncServer()
        await server._sync_lock.acquire()
        server._sync_in_progress = True
        server._current_sync_peer = "peer"
        server._release_sync_lock()
        assert server._sync_in_progress is False
        assert server._current_sync_peer is None
        assert not server._sync_lock.locked()

    @pytest.mark.asyncio
    async def test_release_sync_lock_when_unlocked(self):
        """_release_sync_lock is safe when lock is not locked."""
        server = AsyncServer()
        # Should not raise
        server._release_sync_lock()

    @pytest.mark.asyncio
    async def test_try_acquire_sync_lock_success(self):
        """_try_acquire_sync_lock acquires free lock."""
        server = AsyncServer()
        session = ClientSession(
            reader=MagicMock(), writer=MagicMock(), peer_address=("127.0.0.1", 5364)
        )
        acquired = await server._try_acquire_sync_lock(session, "127.0.0.1:5364")
        assert acquired is True
        assert server._sync_in_progress is True
        assert server._current_sync_peer == "127.0.0.1:5364"
        server._release_sync_lock()

    @pytest.mark.asyncio
    async def test_try_acquire_sync_lock_busy(self):
        """_try_acquire_sync_lock sends busy when lock is held."""
        server = AsyncServer()
        server.sync_lock_timeout = 0.1
        # Hold the lock
        await server._sync_lock.acquire()
        server._sync_in_progress = True
        server._current_sync_peer = "first-peer"

        session = ClientSession(
            reader=MagicMock(), writer=MagicMock(), peer_address=("10.0.0.1", 5364)
        )
        with patch.object(server, "_send_message", new=AsyncMock()) as mock_send:
            acquired = await server._try_acquire_sync_lock(session, "10.0.0.1:5364")
        assert acquired is False
        mock_send.assert_called_once()

        # Cleanup
        server._sync_lock.release()


class TestServerRecvSend:
    """Tests for server recv/send methods."""

    @pytest.mark.asyncio
    async def test_recv_message_raw_incomplete(self):
        """_recv_message_raw returns None on IncompleteReadError."""
        server = AsyncServer()
        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=asyncio.IncompleteReadError(b"partial", 10))
        session = ClientSession(
            reader=mock_reader, writer=MagicMock(), peer_address=("127.0.0.1", 5364)
        )
        result = await server._recv_message_raw(session)
        assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_raw_exception(self):
        """_recv_message_raw returns None on generic exception."""
        server = AsyncServer()
        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=RuntimeError("read error"))
        session = ClientSession(
            reader=mock_reader, writer=MagicMock(), peer_address=("127.0.0.1", 5364)
        )
        result = await server._recv_message_raw(session)
        assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_unauthenticated_delegates(self):
        """_recv_message delegates to _recv_message_raw when not authenticated."""
        server = AsyncServer()
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
            is_authenticated=False,
        )
        with patch.object(server, "_recv_message_raw", new=AsyncMock(return_value=None)) as m:
            result = await server._recv_message(session)
        assert result is None
        m.assert_called_once()

    @pytest.mark.asyncio
    async def test_recv_message_authenticated_incomplete(self):
        """_recv_message returns None on IncompleteReadError when authenticated."""
        server = AsyncServer()
        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=asyncio.IncompleteReadError(b"", 10))
        mock_cipher = MagicMock()
        session = ClientSession(
            reader=mock_reader,
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
            is_authenticated=True,
            decrypt_cipher=mock_cipher,
        )
        result = await server._recv_message(session)
        assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_authenticated_exception(self):
        """_recv_message returns None on generic exception when authenticated."""
        server = AsyncServer()
        mock_reader = AsyncMock()
        mock_reader.readexactly = AsyncMock(side_effect=RuntimeError("decrypt fail"))
        mock_cipher = MagicMock()
        session = ClientSession(
            reader=mock_reader,
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
            is_authenticated=True,
            decrypt_cipher=mock_cipher,
        )
        result = await server._recv_message(session)
        assert result is None

    @pytest.mark.asyncio
    async def test_send_message_raw(self):
        """_send_message_raw writes and drains."""
        server = AsyncServer()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        session = ClientSession(
            reader=MagicMock(), writer=mock_writer, peer_address=("127.0.0.1", 5364)
        )
        msg = Message.create(MessageType.PONG, b"")
        await server._send_message_raw(session, msg)
        mock_writer.write.assert_called_once()
        mock_writer.drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_unauthenticated(self):
        """_send_message sends raw when not authenticated."""
        server = AsyncServer()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        session = ClientSession(
            reader=MagicMock(),
            writer=mock_writer,
            peer_address=("127.0.0.1", 5364),
            is_authenticated=False,
        )
        msg = Message.create(MessageType.PONG, b"")
        await server._send_message(session, msg)
        mock_writer.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_authenticated_encrypts(self):
        """_send_message encrypts when authenticated."""
        server = AsyncServer()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_cipher = MagicMock()
        mock_cipher.encrypt_bytes = MagicMock(return_value=b"encrypted")
        session = ClientSession(
            reader=MagicMock(),
            writer=mock_writer,
            peer_address=("127.0.0.1", 5364),
            is_authenticated=True,
            encrypt_cipher=mock_cipher,
        )
        msg = Message.create(MessageType.PONG, b"plain")
        await server._send_message(session, msg)
        mock_cipher.encrypt_bytes.assert_called_once_with(b"plain")
        mock_writer.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_error_raw(self):
        """_send_error_raw sends an unencrypted error message."""
        server = AsyncServer()
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        session = ClientSession(
            reader=MagicMock(), writer=mock_writer, peer_address=("127.0.0.1", 5364)
        )
        await server._send_error_raw(session, ErrorCode.AUTH_FAILED, "bad auth")
        mock_writer.write.assert_called_once()


class TestServerHandleMessage:
    """Tests for server _handle_message."""

    @pytest.mark.asyncio
    async def test_handle_ping(self):
        """Server responds with PONG to PING."""
        server = AsyncServer()
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
        )
        ping_msg = Message.create(MessageType.PING, b"")

        with (
            patch.object(server, "_send_message", new=AsyncMock()) as mock_send,
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(server=MagicMock(allow_pull=True, allow_push=True))
            await server._handle_message(session, ping_msg)
        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][1]
        assert sent_msg.header.msg_type == MessageType.PONG

    @pytest.mark.asyncio
    async def test_handle_sync_request_pull_not_allowed(self):
        """Server rejects SYNC_REQUEST when pull not allowed."""
        server = AsyncServer()
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
        )
        req = SyncRequest(request_full=True, since_timestamp=0)
        sync_msg = Message.create(MessageType.SYNC_REQUEST, req.pack())

        with (
            patch.object(server, "_send_message", new=AsyncMock()) as mock_send,
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(
                server=MagicMock(allow_pull=False, allow_push=True)
            )
            await server._handle_message(session, sync_msg)
        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][1]
        assert sent_msg.header.msg_type == MessageType.ERROR

    @pytest.mark.asyncio
    async def test_handle_sync_request_success(self):
        """Server handles SYNC_REQUEST with data callback."""
        server = AsyncServer()
        server._get_sync_data = MagicMock(return_value=b'{"lists": []}')
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
        )
        req = SyncRequest(request_full=True, since_timestamp=0)
        sync_msg = Message.create(MessageType.SYNC_REQUEST, req.pack())

        with (
            patch.object(server, "_send_message", new=AsyncMock()) as mock_send,
            patch.object(server, "_try_acquire_sync_lock", new=AsyncMock(return_value=True)),
            patch.object(server, "_release_sync_lock") as mock_release,
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(server=MagicMock(allow_pull=True, allow_push=True))
            await server._handle_message(session, sync_msg)
        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][1]
        assert sent_msg.header.msg_type == MessageType.SYNC_RESPONSE
        mock_release.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_sync_request_no_data_callback(self):
        """Server handles SYNC_REQUEST without data callback (uses default)."""
        server = AsyncServer()
        server._get_sync_data = None
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
        )
        req = SyncRequest(request_full=True, since_timestamp=0)
        sync_msg = Message.create(MessageType.SYNC_REQUEST, req.pack())

        with (
            patch.object(server, "_send_message", new=AsyncMock()) as mock_send,
            patch.object(server, "_try_acquire_sync_lock", new=AsyncMock(return_value=True)),
            patch.object(server, "_release_sync_lock"),
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(server=MagicMock(allow_pull=True, allow_push=True))
            await server._handle_message(session, sync_msg)
        # Should still send a response (with default b"{}")
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_sync_request_data_callback_exception(self):
        """Server handles exception in data callback gracefully."""
        server = AsyncServer()
        server._get_sync_data = MagicMock(side_effect=RuntimeError("db error"))
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
        )
        req = SyncRequest(request_full=True, since_timestamp=0)
        sync_msg = Message.create(MessageType.SYNC_REQUEST, req.pack())

        with (
            patch.object(server, "_send_message", new=AsyncMock()) as mock_send,
            patch.object(server, "_try_acquire_sync_lock", new=AsyncMock(return_value=True)),
            patch.object(server, "_release_sync_lock"),
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(server=MagicMock(allow_pull=True, allow_push=True))
            await server._handle_message(session, sync_msg)
        # Should still respond (with default data)
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_sync_request_lock_busy(self):
        """Server rejects SYNC_REQUEST when lock cannot be acquired."""
        server = AsyncServer()
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
        )
        req = SyncRequest(request_full=True, since_timestamp=0)
        sync_msg = Message.create(MessageType.SYNC_REQUEST, req.pack())

        with (
            patch.object(server, "_send_message", new=AsyncMock()),
            patch.object(server, "_try_acquire_sync_lock", new=AsyncMock(return_value=False)),
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(server=MagicMock(allow_pull=True, allow_push=True))
            await server._handle_message(session, sync_msg)
        # Lock not acquired, busy sent by _try_acquire_sync_lock, no further response

    @pytest.mark.asyncio
    async def test_handle_delta_push_not_allowed(self):
        """Server rejects DELTA_PUSH when push not allowed."""
        server = AsyncServer()
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
        )
        push_msg = Message.create(MessageType.DELTA_PUSH, b"push-data")

        with (
            patch.object(server, "_send_message", new=AsyncMock()) as mock_send,
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(
                server=MagicMock(allow_pull=True, allow_push=False)
            )
            await server._handle_message(session, push_msg)
        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][1]
        assert sent_msg.header.msg_type == MessageType.ERROR

    @pytest.mark.asyncio
    async def test_handle_delta_push_success(self):
        """Server handles DELTA_PUSH with callback."""
        server = AsyncServer()
        server._on_sync_received = MagicMock()
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
            peer_fingerprint="ab:cd",
        )
        push_msg = Message.create(MessageType.DELTA_PUSH, b"push-data")

        with (
            patch.object(server, "_send_message", new=AsyncMock()) as mock_send,
            patch.object(server, "_try_acquire_sync_lock", new=AsyncMock(return_value=True)),
            patch.object(server, "_release_sync_lock") as mock_release,
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(server=MagicMock(allow_pull=True, allow_push=True))
            await server._handle_message(session, push_msg)
        server._on_sync_received.assert_called_once_with(b"push-data", "ab:cd")
        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][1]
        assert sent_msg.header.msg_type == MessageType.DELTA_ACK
        mock_release.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_delta_push_callback_exception(self):
        """Server handles exception in sync callback gracefully."""
        server = AsyncServer()
        server._on_sync_received = MagicMock(side_effect=RuntimeError("merge error"))
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
            peer_fingerprint="ab:cd",
        )
        push_msg = Message.create(MessageType.DELTA_PUSH, b"push-data")

        with (
            patch.object(server, "_send_message", new=AsyncMock()) as mock_send,
            patch.object(server, "_try_acquire_sync_lock", new=AsyncMock(return_value=True)),
            patch.object(server, "_release_sync_lock"),
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(server=MagicMock(allow_pull=True, allow_push=True))
            # Should not raise
            await server._handle_message(session, push_msg)
        # Should still send ACK
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_delta_push_no_callback(self):
        """Server handles DELTA_PUSH without callback."""
        server = AsyncServer()
        server._on_sync_received = None
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
        )
        push_msg = Message.create(MessageType.DELTA_PUSH, b"push-data")

        with (
            patch.object(server, "_send_message", new=AsyncMock()) as mock_send,
            patch.object(server, "_try_acquire_sync_lock", new=AsyncMock(return_value=True)),
            patch.object(server, "_release_sync_lock"),
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(server=MagicMock(allow_pull=True, allow_push=True))
            await server._handle_message(session, push_msg)
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_delta_push_lock_busy(self):
        """Server rejects DELTA_PUSH when lock cannot be acquired."""
        server = AsyncServer()
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
        )
        push_msg = Message.create(MessageType.DELTA_PUSH, b"push-data")

        with (
            patch.object(server, "_send_message", new=AsyncMock()),
            patch.object(server, "_try_acquire_sync_lock", new=AsyncMock(return_value=False)),
            patch("pytodo_qt.net.server.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(server=MagicMock(allow_pull=True, allow_push=True))
            await server._handle_message(session, push_msg)

    @pytest.mark.asyncio
    async def test_handle_error_message(self):
        """Server logs ERROR message from client."""
        server = AsyncServer()
        session = ClientSession(
            reader=MagicMock(),
            writer=MagicMock(),
            peer_address=("127.0.0.1", 5364),
        )
        err = ErrorMessage(error_code=ErrorCode.UNKNOWN_ERROR, message="client error")
        error_msg = Message.create(MessageType.ERROR, err.pack())

        with patch("pytodo_qt.net.server.get_config") as mock_config:
            mock_config.return_value = MagicMock(server=MagicMock(allow_pull=True, allow_push=True))
            # Should not raise; server just logs the error
            await server._handle_message(session, error_msg)


class TestServerHandshake:
    """Tests for server _perform_handshake."""

    @pytest.mark.asyncio
    async def test_handshake_no_hello(self):
        """Server handshake fails when client doesn't send HELLO."""
        server = AsyncServer()
        server.identity = MagicMock()
        session = ClientSession(
            reader=MagicMock(), writer=MagicMock(), peer_address=("127.0.0.1", 5364)
        )
        with (
            patch.object(server, "_recv_message_raw", new=AsyncMock(return_value=None)),
            patch.object(server, "_send_error_raw", new=AsyncMock()),
        ):
            result = await server._perform_handshake(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_handshake_wrong_first_message(self):
        """Server handshake fails on wrong first message type."""
        server = AsyncServer()
        server.identity = MagicMock()
        wrong_msg = Message.create(MessageType.PING, b"")
        session = ClientSession(
            reader=MagicMock(), writer=MagicMock(), peer_address=("127.0.0.1", 5364)
        )
        with (
            patch.object(server, "_recv_message_raw", new=AsyncMock(return_value=wrong_msg)),
            patch.object(server, "_send_error_raw", new=AsyncMock()),
        ):
            result = await server._perform_handshake(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_handshake_version_mismatch(self):
        """Server handshake fails on protocol version mismatch."""
        server = AsyncServer()
        server.identity = MagicMock()
        hello = HelloMessage(version=99, identity_pubkey=b"\x00" * 32)
        hello_msg = Message.create(MessageType.HELLO, hello.pack())
        session = ClientSession(
            reader=MagicMock(), writer=MagicMock(), peer_address=("127.0.0.1", 5364)
        )
        with (
            patch.object(server, "_recv_message_raw", new=AsyncMock(return_value=hello_msg)),
            patch.object(server, "_send_error_raw", new=AsyncMock()) as mock_send_err,
        ):
            result = await server._perform_handshake(session)
        assert result is False
        mock_send_err.assert_called_once()
        assert mock_send_err.call_args[0][1] == ErrorCode.PROTOCOL_MISMATCH

    @pytest.mark.asyncio
    async def test_handshake_no_identity(self):
        """Server handshake fails when server has no identity."""
        server = AsyncServer()
        server.identity = None
        hello = HelloMessage(version=PROTOCOL_VERSION, identity_pubkey=b"\x00" * 32)
        hello_msg = Message.create(MessageType.HELLO, hello.pack())
        session = ClientSession(
            reader=MagicMock(), writer=MagicMock(), peer_address=("127.0.0.1", 5364)
        )
        with patch.object(server, "_recv_message_raw", new=AsyncMock(return_value=hello_msg)):
            result = await server._perform_handshake(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_handshake_no_key_exchange(self):
        """Server handshake fails when KEY_EXCHANGE is missing."""
        server = AsyncServer()
        from pytodo_qt.crypto.key_exchange import IdentityKeyPair

        server.identity = IdentityKeyPair.generate()

        hello = HelloMessage(version=PROTOCOL_VERSION, identity_pubkey=b"\x00" * 32)
        hello_msg = Message.create(MessageType.HELLO, hello.pack())

        call_count = 0

        async def mock_recv(session):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return hello_msg
            return None  # No KEY_EXCHANGE

        session = ClientSession(
            reader=MagicMock(), writer=MagicMock(), peer_address=("127.0.0.1", 5364)
        )
        with (
            patch.object(server, "_recv_message_raw", new=mock_recv),
            patch.object(server, "_send_message_raw", new=AsyncMock()),
            patch.object(server, "_send_error_raw", new=AsyncMock()),
        ):
            result = await server._perform_handshake(session)
        assert result is False

    @pytest.mark.asyncio
    async def test_handshake_exception(self):
        """Server handshake returns False on exception."""
        server = AsyncServer()
        server.identity = MagicMock()
        session = ClientSession(
            reader=MagicMock(), writer=MagicMock(), peer_address=("127.0.0.1", 5364)
        )
        with patch.object(
            server,
            "_recv_message_raw",
            new=AsyncMock(side_effect=RuntimeError("crash")),
        ):
            result = await server._perform_handshake(session)
        assert result is False


class TestServerHandleClient:
    """Tests for server _handle_client."""

    @pytest.mark.asyncio
    async def test_handle_client_handshake_failure(self):
        """Server closes connection on handshake failure."""
        server = AsyncServer()
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 5364))
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch.object(server, "_perform_handshake", new=AsyncMock(return_value=False)):
            await server._handle_client(mock_reader, mock_writer)

        mock_writer.close.assert_called()
        assert ("127.0.0.1", 5364) not in server._sessions

    @pytest.mark.asyncio
    async def test_handle_client_handshake_timeout(self):
        """Server handles handshake timeout."""
        server = AsyncServer()
        server.handshake_timeout = 0.01
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 5364))
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        async def slow_handshake(session):
            await asyncio.sleep(10)  # Will be timed out
            return True

        with patch.object(server, "_perform_handshake", new=slow_handshake):
            await server._handle_client(mock_reader, mock_writer)

        mock_writer.close.assert_called()

    @pytest.mark.asyncio
    async def test_handle_client_message_loop(self):
        """Server processes messages until None received."""
        server = AsyncServer()
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 5364))
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        ping_msg = Message.create(MessageType.PING, b"")
        # First call returns ping, second returns None (disconnect)
        recv_side_effects = [ping_msg, None]

        async def mock_recv(session):
            if recv_side_effects:
                return recv_side_effects.pop(0)
            return None

        async def mock_handshake(session):
            session.peer_fingerprint = "ab:cd:ef:12"
            return True

        with (
            patch.object(server, "_perform_handshake", new=mock_handshake),
            patch.object(server, "_recv_message", new=mock_recv),
            patch.object(server, "_handle_message", new=AsyncMock()),
        ):
            await server._handle_client(mock_reader, mock_writer)

    @pytest.mark.asyncio
    async def test_handle_client_connection_callback(self):
        """Server fires connection callback on successful handshake."""
        server = AsyncServer()
        on_connected = MagicMock()
        on_disconnected = MagicMock()
        server._on_client_connected = on_connected
        server._on_client_disconnected = on_disconnected

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value=("10.0.0.1", 5364))
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        async def mock_handshake(session):
            session.peer_fingerprint = "fp:12:34:56"
            return True

        with (
            patch.object(server, "_perform_handshake", new=mock_handshake),
            patch.object(
                server,
                "_recv_message",
                new=AsyncMock(return_value=None),
            ),
        ):
            await server._handle_client(mock_reader, mock_writer)

        on_connected.assert_called_once_with("10.0.0.1:5364", "fp:12:34:56")
        on_disconnected.assert_called_once_with("10.0.0.1:5364")

    @pytest.mark.asyncio
    async def test_handle_client_connection_callback_exception(self):
        """Server handles exception in connection callback."""
        server = AsyncServer()
        server._on_client_connected = MagicMock(side_effect=RuntimeError("callback error"))
        server._on_client_disconnected = MagicMock(side_effect=RuntimeError("disconnect error"))

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value=("10.0.0.1", 5364))
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        async def mock_handshake(session):
            session.peer_fingerprint = "fp:12:34:56"
            return True

        with (
            patch.object(server, "_perform_handshake", new=mock_handshake),
            patch.object(server, "_recv_message", new=AsyncMock(return_value=None)),
        ):
            # Should not raise despite callback exceptions
            await server._handle_client(mock_reader, mock_writer)

    @pytest.mark.asyncio
    async def test_handle_client_cancelled(self):
        """Server handles CancelledError in message loop."""
        server = AsyncServer()
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 5364))
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        async def mock_handshake(session):
            return True

        with (
            patch.object(server, "_perform_handshake", new=mock_handshake),
            patch.object(
                server,
                "_recv_message",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
        ):
            await server._handle_client(mock_reader, mock_writer)

        mock_writer.close.assert_called()

    @pytest.mark.asyncio
    async def test_handle_client_unexpected_exception(self):
        """Server handles unexpected exception in message loop."""
        server = AsyncServer()
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 5364))
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        async def mock_handshake(session):
            return True

        with (
            patch.object(server, "_perform_handshake", new=mock_handshake),
            patch.object(
                server,
                "_recv_message",
                new=AsyncMock(side_effect=RuntimeError("unexpected")),
            ),
        ):
            await server._handle_client(mock_reader, mock_writer)

        mock_writer.close.assert_called()


class TestServerStop:
    """Tests for server stop/cleanup."""

    @pytest.mark.asyncio
    async def test_stop_closes_sessions(self):
        """Server stop closes all active sessions."""
        server = AsyncServer()
        mock_tcp = AsyncMock()
        mock_tcp.sockets = []
        mock_tcp.close = MagicMock()
        mock_tcp.wait_closed = AsyncMock()
        server._server = mock_tcp

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        session = ClientSession(
            reader=MagicMock(), writer=mock_writer, peer_address=("127.0.0.1", 5364)
        )
        server._sessions[("127.0.0.1", 5364)] = session

        await server.stop()

        mock_writer.close.assert_called_once()
        assert len(server._sessions) == 0
        assert server._server is None

    @pytest.mark.asyncio
    async def test_stop_handles_session_close_error(self):
        """Server stop handles errors when closing sessions."""
        server = AsyncServer()
        mock_tcp = AsyncMock()
        mock_tcp.sockets = []
        mock_tcp.close = MagicMock()
        mock_tcp.wait_closed = AsyncMock()
        server._server = mock_tcp

        mock_writer = MagicMock()
        mock_writer.close = MagicMock(side_effect=OSError("pipe broken"))
        mock_writer.wait_closed = AsyncMock(side_effect=OSError("pipe broken"))
        session = ClientSession(
            reader=MagicMock(), writer=mock_writer, peer_address=("127.0.0.1", 5364)
        )
        server._sessions[("127.0.0.1", 5364)] = session

        # Should not raise
        await server.stop()
        assert server._server is None


class TestServerIsRunning:
    """Tests for server is_running property."""

    def test_is_running_with_serving_server(self):
        """is_running returns True when server is serving."""
        server = AsyncServer()
        mock_tcp = MagicMock()
        mock_tcp.is_serving = MagicMock(return_value=True)
        server._server = mock_tcp
        assert server.is_running is True

    def test_is_running_with_stopped_server(self):
        """is_running returns False when server object exists but is not serving."""
        server = AsyncServer()
        mock_tcp = MagicMock()
        mock_tcp.is_serving = MagicMock(return_value=False)
        server._server = mock_tcp
        assert server.is_running is False


class TestCreateClientFactory:
    """Tests for create_client factory function."""

    def test_create_client(self):
        """create_client creates an AsyncClient."""
        from pytodo_qt.net.client import create_client

        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            keypair = IdentityKeyPair.generate()
            mock_identity.return_value = MagicMock(keypair=keypair)
            client = create_client()
        assert isinstance(client, AsyncClient)


class TestStartServerFactory:
    """Tests for start_server factory function."""

    @pytest.mark.asyncio
    async def test_start_server_with_callbacks(self):
        """start_server passes callbacks to server."""
        from pytodo_qt.net.server import start_server

        get_sync = MagicMock()
        on_sync = MagicMock()

        with (
            patch("pytodo_qt.net.server.get_or_create_identity") as mock_identity,
            patch("asyncio.start_server") as mock_start,
        ):
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())
            mock_tcp = AsyncMock()
            mock_tcp.sockets = []
            mock_start.return_value = mock_tcp

            server = await start_server(
                host="0.0.0.0",
                port=5364,
                get_sync_data=get_sync,
                on_sync_received=on_sync,
            )

        assert server._get_sync_data is get_sync
        assert server._on_sync_received is on_sync
