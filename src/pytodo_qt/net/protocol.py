"""protocol.py

Protocol v2.0 specification for pytodo-qt network communication.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

from ..core.logger import Logger

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


# Protocol constants
PROTOCOL_VERSION = 2
PROTOCOL_MAGIC = b"PTDO"  # 4-byte magic header


class MessageType(IntEnum):
    """Protocol message types."""

    # Handshake
    HELLO = 0x01
    HELLO_ACK = 0x02
    KEY_EXCHANGE = 0x03
    KEY_EXCHANGE_ACK = 0x04

    # Sync operations
    SYNC_REQUEST = 0x10
    SYNC_RESPONSE = 0x11
    DELTA_PUSH = 0x12
    DELTA_ACK = 0x13

    # Peer information
    PEER_INFO = 0x20
    PEER_LIST = 0x21

    # Connection management
    PING = 0x30
    PONG = 0x31

    # Errors
    ERROR = 0xFF


class ErrorCode(IntEnum):
    """Protocol error codes."""

    OK = 0x00
    UNKNOWN_ERROR = 0x01
    PROTOCOL_MISMATCH = 0x02
    AUTH_FAILED = 0x03
    PERMISSION_DENIED = 0x04
    INVALID_MESSAGE = 0x05
    SYNC_REJECTED = 0x06
    PEER_UNTRUSTED = 0x07


@dataclass
class MessageHeader:
    """Protocol message header.

    Wire format:
    [4 bytes: magic][4 bytes: length][1 byte: type][1 byte: flags]
    Total: 10 bytes
    """

    length: int
    msg_type: MessageType
    flags: int = 0

    HEADER_SIZE = 10
    FORMAT = ">4sIBB"  # Big-endian: magic, length, type, flags

    def pack(self) -> bytes:
        """Pack header to bytes."""
        return struct.pack(
            self.FORMAT,
            PROTOCOL_MAGIC,
            self.length,
            self.msg_type,
            self.flags,
        )

    @classmethod
    def unpack(cls, data: bytes) -> MessageHeader:
        """Unpack header from bytes."""
        if len(data) < cls.HEADER_SIZE:
            raise ValueError(f"Header too short: {len(data)} bytes")

        magic, length, msg_type, flags = struct.unpack(cls.FORMAT, data[: cls.HEADER_SIZE])

        if magic != PROTOCOL_MAGIC:
            raise ValueError(f"Invalid magic bytes: {magic!r}")

        return cls(
            length=length,
            msg_type=MessageType(msg_type),
            flags=flags,
        )


@dataclass
class Message:
    """Complete protocol message."""

    header: MessageHeader
    payload: bytes

    def pack(self) -> bytes:
        """Pack complete message to bytes."""
        return self.header.pack() + self.payload

    @classmethod
    def create(cls, msg_type: MessageType, payload: bytes, flags: int = 0) -> Message:
        """Create a message with auto-sized header."""
        header = MessageHeader(
            length=len(payload),
            msg_type=msg_type,
            flags=flags,
        )
        return cls(header=header, payload=payload)


@dataclass
class HelloMessage:
    """HELLO handshake message payload.

    Contains protocol version and identity public key.
    """

    version: int
    identity_pubkey: bytes  # 32 bytes Ed25519

    FORMAT = ">H32s"  # version (2 bytes), pubkey (32 bytes)
    SIZE = 34

    def pack(self) -> bytes:
        """Pack to bytes."""
        return struct.pack(self.FORMAT, self.version, self.identity_pubkey)

    @classmethod
    def unpack(cls, data: bytes) -> HelloMessage:
        """Unpack from bytes."""
        if len(data) < cls.SIZE:
            raise ValueError(f"HelloMessage too short: {len(data)} bytes")
        version, pubkey = struct.unpack(cls.FORMAT, data[: cls.SIZE])
        return cls(version=version, identity_pubkey=pubkey)


@dataclass
class KeyExchangeMessage:
    """Key exchange message containing signed ephemeral key bundle."""

    ephemeral_pubkey: bytes  # 32 bytes X25519
    identity_pubkey: bytes  # 32 bytes Ed25519
    signature: bytes  # 64 bytes Ed25519 signature

    FORMAT = ">32s32s64s"
    SIZE = 128

    def pack(self) -> bytes:
        """Pack to bytes."""
        return struct.pack(
            self.FORMAT,
            self.ephemeral_pubkey,
            self.identity_pubkey,
            self.signature,
        )

    @classmethod
    def unpack(cls, data: bytes) -> KeyExchangeMessage:
        """Unpack from bytes."""
        if len(data) < cls.SIZE:
            raise ValueError(f"KeyExchangeMessage too short: {len(data)} bytes")
        ephemeral, identity, sig = struct.unpack(cls.FORMAT, data[: cls.SIZE])
        return cls(
            ephemeral_pubkey=ephemeral,
            identity_pubkey=identity,
            signature=sig,
        )


@dataclass
class SyncRequest:
    """Request synchronization from peer."""

    request_full: bool = True  # Request full sync vs delta
    since_timestamp: int = 0  # For delta sync, timestamp of last sync

    FORMAT = ">?Q"  # bool, uint64 timestamp
    SIZE = 9

    def pack(self) -> bytes:
        """Pack to bytes."""
        return struct.pack(self.FORMAT, self.request_full, self.since_timestamp)

    @classmethod
    def unpack(cls, data: bytes) -> SyncRequest:
        """Unpack from bytes."""
        if len(data) < cls.SIZE:
            raise ValueError(f"SyncRequest too short: {len(data)} bytes")
        full, since = struct.unpack(cls.FORMAT, data[: cls.SIZE])
        return cls(request_full=full, since_timestamp=since)


@dataclass
class SyncResponse:
    """Response to sync request, contains serialized todo data."""

    error_code: ErrorCode = ErrorCode.OK
    timestamp: int = 0  # Current timestamp for delta tracking
    data: bytes = b""  # Serialized todo data (JSON)

    def pack(self) -> bytes:
        """Pack to bytes."""
        header = struct.pack(">BQ", self.error_code, self.timestamp)
        return header + self.data

    @classmethod
    def unpack(cls, data: bytes) -> SyncResponse:
        """Unpack from bytes."""
        if len(data) < 9:
            raise ValueError(f"SyncResponse too short: {len(data)} bytes")
        error, timestamp = struct.unpack(">BQ", data[:9])
        return cls(
            error_code=ErrorCode(error),
            timestamp=timestamp,
            data=data[9:],
        )


@dataclass
class ErrorMessage:
    """Error response message."""

    error_code: ErrorCode
    message: str = ""

    def pack(self) -> bytes:
        """Pack to bytes."""
        msg_bytes = self.message.encode("utf-8")
        return struct.pack(">B", self.error_code) + msg_bytes

    @classmethod
    def unpack(cls, data: bytes) -> ErrorMessage:
        """Unpack from bytes."""
        if len(data) < 1:
            raise ValueError("ErrorMessage too short")
        error = ErrorCode(data[0])
        message = data[1:].decode("utf-8") if len(data) > 1 else ""
        return cls(error_code=error, message=message)


@dataclass
class PeerInfo:
    """Information about a discovered peer."""

    identity_fingerprint: str
    hostname: str
    address: str
    port: int
    protocol_version: int
    is_trusted: bool = False

    def pack(self) -> bytes:
        """Pack to bytes."""
        fp_bytes = self.identity_fingerprint.encode("utf-8")
        host_bytes = self.hostname.encode("utf-8")
        addr_bytes = self.address.encode("utf-8")
        data = struct.pack(
            ">HHHH?",
            len(fp_bytes),
            len(host_bytes),
            len(addr_bytes),
            self.port,
            self.protocol_version,
        )
        return data + fp_bytes + host_bytes + addr_bytes

    @classmethod
    def unpack(cls, data: bytes) -> PeerInfo:
        """Unpack from bytes."""
        fp_len, host_len, addr_len, port, version = struct.unpack(">HHHH?", data[:9])
        offset = 9
        fingerprint = data[offset : offset + fp_len].decode("utf-8")
        offset += fp_len
        hostname = data[offset : offset + host_len].decode("utf-8")
        offset += host_len
        address = data[offset : offset + addr_len].decode("utf-8")
        return cls(
            identity_fingerprint=fingerprint,
            hostname=hostname,
            address=address,
            port=port,
            protocol_version=version,
        )


def create_hello(identity_pubkey: bytes) -> Message:
    """Create a HELLO message."""
    hello = HelloMessage(version=PROTOCOL_VERSION, identity_pubkey=identity_pubkey)
    return Message.create(MessageType.HELLO, hello.pack())


def create_hello_ack(identity_pubkey: bytes) -> Message:
    """Create a HELLO_ACK message."""
    hello = HelloMessage(version=PROTOCOL_VERSION, identity_pubkey=identity_pubkey)
    return Message.create(MessageType.HELLO_ACK, hello.pack())


def create_key_exchange(ephemeral_pub: bytes, identity_pub: bytes, signature: bytes) -> Message:
    """Create a KEY_EXCHANGE message."""
    kex = KeyExchangeMessage(
        ephemeral_pubkey=ephemeral_pub,
        identity_pubkey=identity_pub,
        signature=signature,
    )
    return Message.create(MessageType.KEY_EXCHANGE, kex.pack())


def create_key_exchange_ack(ephemeral_pub: bytes, identity_pub: bytes, signature: bytes) -> Message:
    """Create a KEY_EXCHANGE_ACK message."""
    kex = KeyExchangeMessage(
        ephemeral_pubkey=ephemeral_pub,
        identity_pubkey=identity_pub,
        signature=signature,
    )
    return Message.create(MessageType.KEY_EXCHANGE_ACK, kex.pack())


def create_sync_request(full: bool = True, since: int = 0) -> Message:
    """Create a SYNC_REQUEST message."""
    req = SyncRequest(request_full=full, since_timestamp=since)
    return Message.create(MessageType.SYNC_REQUEST, req.pack())


def create_sync_response(
    data: bytes, timestamp: int = 0, error: ErrorCode = ErrorCode.OK
) -> Message:
    """Create a SYNC_RESPONSE message."""
    resp = SyncResponse(error_code=error, timestamp=timestamp, data=data)
    return Message.create(MessageType.SYNC_RESPONSE, resp.pack())


def create_error(code: ErrorCode, message: str = "") -> Message:
    """Create an ERROR message."""
    err = ErrorMessage(error_code=code, message=message)
    return Message.create(MessageType.ERROR, err.pack())


def create_ping() -> Message:
    """Create a PING message."""
    return Message.create(MessageType.PING, b"")


def create_pong() -> Message:
    """Create a PONG message."""
    return Message.create(MessageType.PONG, b"")
