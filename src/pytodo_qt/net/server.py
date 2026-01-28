"""server.py

Async TCP server for pytodo-qt protocol v2.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.config import get_config
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
    create_error,
    create_hello_ack,
    create_key_exchange_ack,
    create_pong,
    create_sync_response,
)

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


@dataclass
class ClientSession:
    """Active client connection session."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    peer_address: tuple[str, int]
    peer_identity: bytes | None = None
    peer_fingerprint: str | None = None
    encrypt_cipher: AESGCMCipher | None = None
    decrypt_cipher: AESGCMCipher | None = None
    is_authenticated: bool = False


@dataclass
class AsyncServer:
    """Async TCP server with authenticated encryption."""

    host: str = "0.0.0.0"
    port: int = 5364
    identity: IdentityKeyPair | None = None
    handshake_timeout: float = 30.0  # Timeout for handshake in seconds
    message_timeout: float = 60.0  # Timeout for receiving messages
    _server: asyncio.Server | None = None
    _sessions: dict[tuple[str, int], ClientSession] = field(default_factory=dict)
    _get_sync_data: Callable[[], bytes] | None = None
    _on_sync_received: Callable[[bytes], None] | None = None
    _on_client_connected: Callable[[str, str], None] | None = None
    _on_client_disconnected: Callable[[str], None] | None = None

    async def start(
        self,
        get_sync_data: Callable[[], bytes] | None = None,
        on_sync_received: Callable[[bytes], None] | None = None,
        on_client_connected: Callable[[str, str], None] | None = None,
        on_client_disconnected: Callable[[str], None] | None = None,
    ) -> None:
        """Start the server.

        Args:
            get_sync_data: Callback to get current sync data as bytes
            on_sync_received: Callback when sync data is received
            on_client_connected: Callback when client connects (address, fingerprint)
            on_client_disconnected: Callback when client disconnects
        """
        self._get_sync_data = get_sync_data
        self._on_sync_received = on_sync_received
        self._on_client_connected = on_client_connected
        self._on_client_disconnected = on_client_disconnected

        # Get or create identity
        stored = get_or_create_identity()
        self.identity = stored.keypair

        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            reuse_address=True,
        )

        addrs = ", ".join(str(sock.getsockname()) for sock in self._server.sockets)
        logger.log.info("Server started on %s", addrs)

    async def stop(self) -> None:
        """Stop the server."""
        if self._server is None:
            return

        # Close all client sessions
        for session in list(self._sessions.values()):
            try:
                session.writer.close()
                await session.writer.wait_closed()
            except Exception:
                pass

        self._sessions.clear()

        # Close server
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        logger.log.info("Server stopped")

    async def serve_forever(self) -> None:
        """Serve requests until stopped."""
        if self._server is None:
            raise RuntimeError("Server not started")
        async with self._server:
            await self._server.serve_forever()

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._server is not None and self._server.is_serving()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        peer_addr = writer.get_extra_info("peername")
        session = ClientSession(
            reader=reader,
            writer=writer,
            peer_address=peer_addr,
        )
        self._sessions[peer_addr] = session

        logger.log.info("Client connected from %s", peer_addr)

        try:
            # Perform handshake with timeout
            try:
                handshake_ok = await asyncio.wait_for(
                    self._perform_handshake(session),
                    timeout=self.handshake_timeout,
                )
                if not handshake_ok:
                    logger.log.warning("Handshake failed with %s", peer_addr)
                    return
            except TimeoutError:
                logger.log.warning("Handshake timed out with %s", peer_addr)
                return

            # Notify connection
            if self._on_client_connected and session.peer_fingerprint:
                try:
                    self._on_client_connected(
                        f"{peer_addr[0]}:{peer_addr[1]}",
                        session.peer_fingerprint,
                    )
                except Exception as e:
                    logger.log.exception("Error in connection callback: %s", e)

            # Handle messages with timeout
            while True:
                try:
                    msg = await asyncio.wait_for(
                        self._recv_message(session),
                        timeout=self.message_timeout,
                    )
                    if msg is None:
                        break
                    await self._handle_message(session, msg)
                except TimeoutError:
                    logger.log.info("Client %s timed out waiting for message", peer_addr)
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.log.exception("Error handling client %s: %s", peer_addr, e)
        finally:
            # Cleanup
            if peer_addr in self._sessions:
                del self._sessions[peer_addr]
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

            if self._on_client_disconnected:
                try:
                    self._on_client_disconnected(f"{peer_addr[0]}:{peer_addr[1]}")
                except Exception as e:
                    logger.log.exception("Error in disconnect callback: %s", e)

            logger.log.info("Client disconnected: %s", peer_addr)

    async def _perform_handshake(self, session: ClientSession) -> bool:
        """Perform the protocol handshake with key exchange."""
        try:
            # Receive client HELLO
            msg = await self._recv_message_raw(session)
            if msg is None or msg.header.msg_type != MessageType.HELLO:
                await self._send_error_raw(session, ErrorCode.INVALID_MESSAGE, "Expected HELLO")
                return False

            hello = HelloMessage.unpack(msg.payload)
            if hello.version != PROTOCOL_VERSION:
                await self._send_error_raw(
                    session,
                    ErrorCode.PROTOCOL_MISMATCH,
                    f"Version mismatch: expected {PROTOCOL_VERSION}, got {hello.version}",
                )
                return False

            session.peer_identity = hello.identity_pubkey

            # Send HELLO_ACK
            if self.identity is None:
                return False
            hello_ack = create_hello_ack(self.identity.public_bytes())
            await self._send_message_raw(session, hello_ack)

            # Receive client KEY_EXCHANGE
            msg = await self._recv_message_raw(session)
            if msg is None or msg.header.msg_type != MessageType.KEY_EXCHANGE:
                await self._send_error_raw(
                    session, ErrorCode.INVALID_MESSAGE, "Expected KEY_EXCHANGE"
                )
                return False

            kex = KeyExchangeMessage.unpack(msg.payload)
            peer_bundle = SignedKeyBundle(
                ephemeral_public=kex.ephemeral_pubkey,
                identity_public=kex.identity_pubkey,
                signature=kex.signature,
            )

            # Verify signature
            if not peer_bundle.verify():
                await self._send_error_raw(session, ErrorCode.AUTH_FAILED, "Invalid signature")
                return False

            # Generate our ephemeral key and perform exchange
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey

            ephemeral = EphemeralKeyPair.generate()
            peer_ephemeral = X25519PublicKey.from_public_bytes(peer_bundle.ephemeral_public)
            shared_secret = ephemeral.exchange(peer_ephemeral)

            # Derive session keys (server is responder)
            session_keys = derive_session_keys(
                shared_secret,
                ephemeral.public_bytes(),
                peer_bundle.ephemeral_public,
                is_initiator=False,
            )

            # Create our key exchange message
            our_bundle = create_signed_key_bundle(self.identity, ephemeral)
            kex_ack = create_key_exchange_ack(
                our_bundle.ephemeral_public,
                our_bundle.identity_public,
                our_bundle.signature,
            )
            await self._send_message_raw(session, kex_ack)

            # Set up encryption
            session.encrypt_cipher = AESGCMCipher(session_keys.encrypt_key)
            session.decrypt_cipher = AESGCMCipher(session_keys.decrypt_key)
            session.is_authenticated = True

            # Calculate peer fingerprint
            import hashlib

            digest = hashlib.sha256(session.peer_identity).hexdigest()
            session.peer_fingerprint = ":".join(digest[i : i + 4] for i in range(0, 32, 4))

            logger.log.info(
                "Handshake completed with %s (fingerprint: %s)",
                session.peer_address,
                session.peer_fingerprint,
            )
            return True

        except Exception as e:
            logger.log.exception("Handshake error: %s", e)
            return False

    async def _handle_message(self, session: ClientSession, msg: Message) -> None:
        """Handle a received message."""
        config = get_config()

        if msg.header.msg_type == MessageType.PING:
            pong = create_pong()
            await self._send_message(session, pong)

        elif msg.header.msg_type == MessageType.SYNC_REQUEST:
            if not config.server.allow_pull:
                error = create_error(ErrorCode.PERMISSION_DENIED, "Pull not allowed")
                await self._send_message(session, error)
                return

            # Get sync data and send response
            data = b"{}"
            if self._get_sync_data:
                try:
                    data = self._get_sync_data()
                except Exception as e:
                    logger.log.exception("Error getting sync data: %s", e)

            response = create_sync_response(data)
            await self._send_message(session, response)
            logger.log.info("Sent sync data to %s", session.peer_address)

        elif msg.header.msg_type == MessageType.DELTA_PUSH:
            if not config.server.allow_push:
                error = create_error(ErrorCode.PERMISSION_DENIED, "Push not allowed")
                await self._send_message(session, error)
                return

            # Process received data
            if self._on_sync_received:
                try:
                    self._on_sync_received(msg.payload)
                except Exception as e:
                    logger.log.exception("Error processing sync data: %s", e)

            # Send acknowledgment
            ack = Message.create(MessageType.DELTA_ACK, b"")
            await self._send_message(session, ack)
            logger.log.info("Received and acknowledged delta push from %s", session.peer_address)

        elif msg.header.msg_type == MessageType.ERROR:
            from .protocol import ErrorMessage

            err = ErrorMessage.unpack(msg.payload)
            logger.log.warning(
                "Received error from %s: %s - %s",
                session.peer_address,
                err.error_code.name,
                err.message,
            )

    async def _recv_message_raw(self, session: ClientSession) -> Message | None:
        """Receive a raw (unencrypted) message."""
        try:
            header_data = await session.reader.readexactly(MessageHeader.HEADER_SIZE)
            header = MessageHeader.unpack(header_data)
            payload = await session.reader.readexactly(header.length)
            return Message(header=header, payload=payload)
        except asyncio.IncompleteReadError:
            return None
        except Exception as e:
            logger.log.exception("Error receiving message: %s", e)
            return None

    async def _recv_message(self, session: ClientSession) -> Message | None:
        """Receive and decrypt a message."""
        if not session.is_authenticated or session.decrypt_cipher is None:
            return await self._recv_message_raw(session)

        try:
            header_data = await session.reader.readexactly(MessageHeader.HEADER_SIZE)
            header = MessageHeader.unpack(header_data)
            encrypted = await session.reader.readexactly(header.length)
            payload = session.decrypt_cipher.decrypt_bytes(encrypted)
            return Message(header=header, payload=payload)
        except asyncio.IncompleteReadError:
            return None
        except Exception as e:
            logger.log.exception("Error receiving/decrypting message: %s", e)
            return None

    async def _send_message_raw(self, session: ClientSession, msg: Message) -> None:
        """Send a raw (unencrypted) message."""
        session.writer.write(msg.pack())
        await session.writer.drain()

    async def _send_message(self, session: ClientSession, msg: Message) -> None:
        """Encrypt and send a message."""
        if not session.is_authenticated or session.encrypt_cipher is None:
            await self._send_message_raw(session, msg)
            return

        encrypted = session.encrypt_cipher.encrypt_bytes(msg.payload)
        encrypted_msg = Message.create(msg.header.msg_type, encrypted, msg.header.flags)
        session.writer.write(encrypted_msg.pack())
        await session.writer.drain()

    async def _send_error_raw(
        self,
        session: ClientSession,
        code: ErrorCode,
        message: str = "",
    ) -> None:
        """Send an unencrypted error message."""
        error = create_error(code, message)
        await self._send_message_raw(session, error)


# Convenience function to create and start server
async def start_server(
    host: str = "0.0.0.0",
    port: int = 5364,
    get_sync_data: Callable[[], bytes] | None = None,
    on_sync_received: Callable[[bytes], None] | None = None,
) -> AsyncServer:
    """Create and start an async server."""
    server = AsyncServer(host=host, port=port)
    await server.start(get_sync_data=get_sync_data, on_sync_received=on_sync_received)
    return server
