"""client.py

Async TCP client for pytodo-qt protocol v2.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal

from ..core.logger import Logger
from ..crypto import (
    AESGCMCipher,
    EphemeralKeyPair,
    IdentityKeyPair,
    SignedKeyBundle,
    create_signed_key_bundle,
    derive_session_keys,
    get_or_create_identity,
)
from .protocol import (
    PROTOCOL_VERSION,
    ErrorCode,
    HelloMessage,
    KeyExchangeMessage,
    Message,
    MessageHeader,
    MessageType,
    SyncResponse,
    create_hello,
    create_key_exchange,
    create_ping,
    create_sync_request,
)

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


@dataclass
class ConnectionState:
    """State of an active connection."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    peer_identity: bytes | None = None
    peer_fingerprint: str | None = None
    encrypt_cipher: AESGCMCipher | None = None
    decrypt_cipher: AESGCMCipher | None = None
    is_authenticated: bool = False


class AsyncClient(QObject):
    """Async TCP client with authenticated encryption."""

    # Signals for Qt integration
    sync_completed = pyqtSignal(str)  # Emitted when sync completes (message)
    sync_failed = pyqtSignal(str)  # Emitted when sync fails (error message)
    connected = pyqtSignal(str)  # Emitted on connection (fingerprint)
    disconnected = pyqtSignal()  # Emitted on disconnect

    def __init__(self, parent=None):
        super().__init__(parent)
        self.identity: IdentityKeyPair | None = None
        self._connection: ConnectionState | None = None
        self._timeout: float = 30.0

        # Get identity
        stored = get_or_create_identity()
        self.identity = stored.keypair

    async def connect(self, host: str, port: int) -> bool:
        """Connect to a server.

        Args:
            host: Server hostname or IP
            port: Server port

        Returns:
            True if connection and handshake succeeded
        """
        logger.log.debug("connect() called: %s:%d", host, port)
        try:
            logger.log.debug("Opening connection...")
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self._timeout,
            )
            logger.log.debug("Connection opened, performing handshake...")

            self._connection = ConnectionState(reader=reader, writer=writer)

            # Perform handshake
            if not await self._perform_handshake():
                await self.disconnect()
                return False

            if self._connection.peer_fingerprint:
                self.connected.emit(self._connection.peer_fingerprint)

            logger.log.info("Connected to %s:%d", host, port)
            return True

        except TimeoutError:
            logger.log.error("Connection to %s:%d timed out", host, port)
            self.sync_failed.emit("Connection timed out")
            return False
        except Exception as e:
            logger.log.exception("Connection to %s:%d failed: %s", host, port, e)
            self.sync_failed.emit(f"Connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from server."""
        if self._connection is None:
            return

        try:
            self._connection.writer.close()
            await self._connection.writer.wait_closed()
        except Exception:
            pass

        self._connection = None
        self.disconnected.emit()
        logger.log.info("Disconnected from server")

    async def sync_pull(self, host: str, port: int) -> tuple[bool, bytes]:
        """Pull sync data from server.

        Args:
            host: Server hostname or IP
            port: Server port

        Returns:
            Tuple of (success, data)
        """
        try:
            if not await self.connect(host, port):
                return False, b""

            # Send sync request
            request = create_sync_request(full=True)
            await self._send_message(request)

            # Receive response
            msg = await self._recv_message()
            if msg is None:
                self.sync_failed.emit("No response from server")
                return False, b""

            if msg.header.msg_type == MessageType.ERROR:
                from .protocol import ErrorMessage

                err = ErrorMessage.unpack(msg.payload)
                self.sync_failed.emit(f"Server error: {err.message}")
                return False, b""

            if msg.header.msg_type != MessageType.SYNC_RESPONSE:
                self.sync_failed.emit(f"Unexpected response type: {msg.header.msg_type.name}")
                return False, b""

            response = SyncResponse.unpack(msg.payload)
            if response.error_code != ErrorCode.OK:
                self.sync_failed.emit(f"Sync error: {response.error_code.name}")
                return False, b""

            self.sync_completed.emit(f"Pulled {len(response.data)} bytes from {host}")
            logger.log.info("Sync pull successful: %d bytes", len(response.data))
            return True, response.data

        except Exception as e:
            logger.log.exception("Sync pull failed: %s", e)
            self.sync_failed.emit(f"Sync pull failed: {e}")
            return False, b""
        finally:
            await self.disconnect()

    async def sync_push(self, host: str, port: int, data: bytes) -> bool:
        """Push sync data to server.

        Args:
            host: Server hostname or IP
            port: Server port
            data: Data to push

        Returns:
            True if push succeeded
        """
        try:
            if not await self.connect(host, port):
                return False

            # Send delta push
            push_msg = Message.create(MessageType.DELTA_PUSH, data)
            await self._send_message(push_msg)

            # Wait for acknowledgment
            msg = await self._recv_message()
            if msg is None:
                self.sync_failed.emit("No acknowledgment from server")
                return False

            if msg.header.msg_type == MessageType.ERROR:
                from .protocol import ErrorMessage

                err = ErrorMessage.unpack(msg.payload)
                self.sync_failed.emit(f"Server error: {err.message}")
                return False

            if msg.header.msg_type != MessageType.DELTA_ACK:
                self.sync_failed.emit(f"Unexpected response: {msg.header.msg_type.name}")
                return False

            self.sync_completed.emit(f"Pushed {len(data)} bytes to {host}")
            logger.log.info("Sync push successful: %d bytes", len(data))
            return True

        except Exception as e:
            logger.log.exception("Sync push failed: %s", e)
            self.sync_failed.emit(f"Sync push failed: {e}")
            return False
        finally:
            await self.disconnect()

    async def ping(self, host: str, port: int) -> tuple[bool, float]:
        """Ping a server and measure latency.

        Args:
            host: Server hostname or IP
            port: Server port

        Returns:
            Tuple of (success, latency_ms)
        """
        import time

        try:
            start = time.monotonic()

            if not await self.connect(host, port):
                return False, 0.0

            ping_msg = create_ping()
            await self._send_message(ping_msg)

            msg = await self._recv_message()
            if msg is None or msg.header.msg_type != MessageType.PONG:
                return False, 0.0

            latency = (time.monotonic() - start) * 1000
            logger.log.info("Ping to %s:%d: %.2fms", host, port, latency)
            return True, latency

        except Exception as e:
            logger.log.exception("Ping failed: %s", e)
            return False, 0.0
        finally:
            await self.disconnect()

    async def _perform_handshake(self) -> bool:
        """Perform the protocol handshake with key exchange."""
        if self._connection is None or self.identity is None:
            logger.log.debug("Handshake: no connection or identity")
            return False

        try:
            # Send HELLO
            logger.log.debug("Handshake: sending HELLO")
            hello = create_hello(self.identity.public_bytes())
            await self._send_message_raw(hello)
            logger.log.debug("Handshake: HELLO sent, waiting for HELLO_ACK")

            # Receive HELLO_ACK
            msg = await self._recv_message_raw()
            logger.log.debug("Handshake: received response")
            if msg is None or msg.header.msg_type != MessageType.HELLO_ACK:
                logger.log.error(
                    "Expected HELLO_ACK, got %s", msg.header.msg_type.name if msg else "nothing"
                )
                return False

            hello_ack = HelloMessage.unpack(msg.payload)
            if hello_ack.version != PROTOCOL_VERSION:
                logger.log.error(
                    "Protocol version mismatch: %d != %d", hello_ack.version, PROTOCOL_VERSION
                )
                return False

            self._connection.peer_identity = hello_ack.identity_pubkey

            # Generate ephemeral key and send KEY_EXCHANGE
            ephemeral = EphemeralKeyPair.generate()
            our_bundle = create_signed_key_bundle(self.identity, ephemeral)
            kex = create_key_exchange(
                our_bundle.ephemeral_public,
                our_bundle.identity_public,
                our_bundle.signature,
            )
            await self._send_message_raw(kex)

            # Receive KEY_EXCHANGE_ACK
            msg = await self._recv_message_raw()
            if msg is None or msg.header.msg_type != MessageType.KEY_EXCHANGE_ACK:
                logger.log.error("Expected KEY_EXCHANGE_ACK")
                return False

            kex_ack = KeyExchangeMessage.unpack(msg.payload)
            peer_bundle = SignedKeyBundle(
                ephemeral_public=kex_ack.ephemeral_pubkey,
                identity_public=kex_ack.identity_pubkey,
                signature=kex_ack.signature,
            )

            # Verify server's signature
            if not peer_bundle.verify():
                logger.log.error("Server key exchange signature invalid")
                return False

            # Perform X25519 exchange
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey

            peer_ephemeral = X25519PublicKey.from_public_bytes(peer_bundle.ephemeral_public)
            shared_secret = ephemeral.exchange(peer_ephemeral)

            # Derive session keys (client is initiator)
            session_keys = derive_session_keys(
                shared_secret,
                ephemeral.public_bytes(),
                peer_bundle.ephemeral_public,
                is_initiator=True,
            )

            # Set up encryption
            self._connection.encrypt_cipher = AESGCMCipher(session_keys.encrypt_key)
            self._connection.decrypt_cipher = AESGCMCipher(session_keys.decrypt_key)
            self._connection.is_authenticated = True

            # Calculate peer fingerprint
            import hashlib

            digest = hashlib.sha256(self._connection.peer_identity).hexdigest()
            self._connection.peer_fingerprint = ":".join(digest[i : i + 4] for i in range(0, 32, 4))

            logger.log.info(
                "Handshake completed (peer fingerprint: %s)", self._connection.peer_fingerprint
            )
            return True

        except Exception as e:
            logger.log.exception("Handshake error: %s", e)
            return False

    async def _send_message_raw(self, msg: Message) -> None:
        """Send a raw (unencrypted) message."""
        if self._connection is None:
            raise RuntimeError("Not connected")
        self._connection.writer.write(msg.pack())
        await self._connection.writer.drain()

    async def _send_message(self, msg: Message) -> None:
        """Encrypt and send a message."""
        if self._connection is None:
            raise RuntimeError("Not connected")

        if not self._connection.is_authenticated or self._connection.encrypt_cipher is None:
            await self._send_message_raw(msg)
            return

        encrypted = self._connection.encrypt_cipher.encrypt_bytes(msg.payload)
        encrypted_msg = Message.create(msg.header.msg_type, encrypted, msg.header.flags)
        self._connection.writer.write(encrypted_msg.pack())
        await self._connection.writer.drain()

    async def _recv_message_raw(self) -> Message | None:
        """Receive a raw (unencrypted) message."""
        if self._connection is None:
            return None

        try:
            header_data = await asyncio.wait_for(
                self._connection.reader.readexactly(MessageHeader.HEADER_SIZE),
                timeout=self._timeout,
            )
            header = MessageHeader.unpack(header_data)
            payload = await asyncio.wait_for(
                self._connection.reader.readexactly(header.length),
                timeout=self._timeout,
            )
            return Message(header=header, payload=payload)
        except TimeoutError:
            logger.log.error("Receive timeout")
            return None
        except asyncio.IncompleteReadError:
            return None
        except Exception as e:
            logger.log.exception("Error receiving message: %s", e)
            return None

    async def _recv_message(self) -> Message | None:
        """Receive and decrypt a message."""
        if self._connection is None:
            return None

        if not self._connection.is_authenticated or self._connection.decrypt_cipher is None:
            return await self._recv_message_raw()

        try:
            header_data = await asyncio.wait_for(
                self._connection.reader.readexactly(MessageHeader.HEADER_SIZE),
                timeout=self._timeout,
            )
            header = MessageHeader.unpack(header_data)
            encrypted = await asyncio.wait_for(
                self._connection.reader.readexactly(header.length),
                timeout=self._timeout,
            )
            payload = self._connection.decrypt_cipher.decrypt_bytes(encrypted)
            return Message(header=header, payload=payload)
        except TimeoutError:
            logger.log.error("Receive timeout")
            return None
        except asyncio.IncompleteReadError:
            return None
        except Exception as e:
            logger.log.exception("Error receiving/decrypting message: %s", e)
            return None


# Convenience functions for synchronous callers
def create_client() -> AsyncClient:
    """Create a new async client."""
    return AsyncClient()
