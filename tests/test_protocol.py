"""Tests for network protocol."""

import pytest

from pytodo_qt.net.protocol import (
    PROTOCOL_VERSION,
    ErrorCode,
    ErrorMessage,
    HelloMessage,
    KeyExchangeMessage,
    Message,
    MessageHeader,
    MessageType,
    SyncRequest,
    SyncResponse,
    create_error,
    create_hello,
    create_ping,
    create_pong,
    create_sync_request,
    create_sync_response,
)


class TestMessageHeader:
    """Tests for MessageHeader."""

    def test_pack_unpack(self):
        """Test header serialization."""
        header = MessageHeader(
            length=100,
            msg_type=MessageType.HELLO,
            flags=0,
        )

        packed = header.pack()
        assert len(packed) == MessageHeader.HEADER_SIZE

        unpacked = MessageHeader.unpack(packed)
        assert unpacked.length == 100
        assert unpacked.msg_type == MessageType.HELLO
        assert unpacked.flags == 0

    def test_invalid_magic_raises(self):
        """Test that invalid magic bytes raise error."""
        bad_data = b"XXXX" + b"\x00" * 6

        with pytest.raises(ValueError, match="Invalid magic"):
            MessageHeader.unpack(bad_data)

    def test_short_data_raises(self):
        """Test that short data raises error."""
        with pytest.raises(ValueError, match="too short"):
            MessageHeader.unpack(b"short")


class TestMessage:
    """Tests for Message."""

    def test_create_and_pack(self):
        """Test message creation and packing."""
        msg = Message.create(MessageType.PING, b"payload", flags=1)

        assert msg.header.msg_type == MessageType.PING
        assert msg.header.length == 7  # len("payload")
        assert msg.header.flags == 1
        assert msg.payload == b"payload"

        packed = msg.pack()
        assert len(packed) == MessageHeader.HEADER_SIZE + 7


class TestHelloMessage:
    """Tests for HelloMessage."""

    def test_pack_unpack(self):
        """Test HelloMessage serialization."""
        pubkey = b"x" * 32

        hello = HelloMessage(version=PROTOCOL_VERSION, identity_pubkey=pubkey)
        packed = hello.pack()

        assert len(packed) == HelloMessage.SIZE

        unpacked = HelloMessage.unpack(packed)
        assert unpacked.version == PROTOCOL_VERSION
        assert unpacked.identity_pubkey == pubkey

    def test_create_hello(self):
        """Test create_hello helper."""
        pubkey = b"y" * 32
        msg = create_hello(pubkey)

        assert msg.header.msg_type == MessageType.HELLO

        hello = HelloMessage.unpack(msg.payload)
        assert hello.version == PROTOCOL_VERSION
        assert hello.identity_pubkey == pubkey


class TestKeyExchangeMessage:
    """Tests for KeyExchangeMessage."""

    def test_pack_unpack(self):
        """Test KeyExchangeMessage serialization."""
        kex = KeyExchangeMessage(
            ephemeral_pubkey=b"e" * 32,
            identity_pubkey=b"i" * 32,
            signature=b"s" * 64,
        )

        packed = kex.pack()
        assert len(packed) == KeyExchangeMessage.SIZE

        unpacked = KeyExchangeMessage.unpack(packed)
        assert unpacked.ephemeral_pubkey == b"e" * 32
        assert unpacked.identity_pubkey == b"i" * 32
        assert unpacked.signature == b"s" * 64


class TestSyncRequest:
    """Tests for SyncRequest."""

    def test_pack_unpack(self):
        """Test SyncRequest serialization."""
        req = SyncRequest(request_full=False, since_timestamp=12345)

        packed = req.pack()
        unpacked = SyncRequest.unpack(packed)

        assert unpacked.request_full is False
        assert unpacked.since_timestamp == 12345

    def test_create_sync_request(self):
        """Test create_sync_request helper."""
        msg = create_sync_request(full=True, since=0)

        assert msg.header.msg_type == MessageType.SYNC_REQUEST


class TestSyncResponse:
    """Tests for SyncResponse."""

    def test_pack_unpack(self):
        """Test SyncResponse serialization."""
        data = b'{"test": "data"}'
        resp = SyncResponse(
            error_code=ErrorCode.OK,
            timestamp=99999,
            data=data,
        )

        packed = resp.pack()
        unpacked = SyncResponse.unpack(packed)

        assert unpacked.error_code == ErrorCode.OK
        assert unpacked.timestamp == 99999
        assert unpacked.data == data

    def test_create_sync_response(self):
        """Test create_sync_response helper."""
        data = b'{"lists": []}'
        msg = create_sync_response(data, timestamp=12345)

        assert msg.header.msg_type == MessageType.SYNC_RESPONSE

        resp = SyncResponse.unpack(msg.payload)
        assert resp.data == data


class TestErrorMessage:
    """Tests for ErrorMessage."""

    def test_pack_unpack(self):
        """Test ErrorMessage serialization."""
        err = ErrorMessage(
            error_code=ErrorCode.PERMISSION_DENIED,
            message="Access denied",
        )

        packed = err.pack()
        unpacked = ErrorMessage.unpack(packed)

        assert unpacked.error_code == ErrorCode.PERMISSION_DENIED
        assert unpacked.message == "Access denied"

    def test_create_error(self):
        """Test create_error helper."""
        msg = create_error(ErrorCode.AUTH_FAILED, "Invalid signature")

        assert msg.header.msg_type == MessageType.ERROR

        err = ErrorMessage.unpack(msg.payload)
        assert err.error_code == ErrorCode.AUTH_FAILED
        assert err.message == "Invalid signature"


class TestPingPong:
    """Tests for ping/pong messages."""

    def test_create_ping(self):
        """Test create_ping helper."""
        msg = create_ping()
        assert msg.header.msg_type == MessageType.PING
        assert msg.payload == b""

    def test_create_pong(self):
        """Test create_pong helper."""
        msg = create_pong()
        assert msg.header.msg_type == MessageType.PONG
        assert msg.payload == b""
