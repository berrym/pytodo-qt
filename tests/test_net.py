"""Tests for network client and server modules."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pytodo_qt.net.client import AsyncClient, ConnectionState, create_client
from pytodo_qt.net.server import AsyncServer, ClientSession, start_server


class TestConnectionState:
    """Tests for ConnectionState dataclass."""

    def test_connection_state_creation(self):
        """Test creating a connection state."""
        reader = MagicMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)

        state = ConnectionState(reader=reader, writer=writer)

        assert state.reader is reader
        assert state.writer is writer
        assert state.peer_identity is None
        assert state.peer_fingerprint is None
        assert state.encrypt_cipher is None
        assert state.decrypt_cipher is None
        assert state.is_authenticated is False

    def test_connection_state_with_auth(self):
        """Test connection state with authentication info."""
        reader = MagicMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)

        state = ConnectionState(
            reader=reader,
            writer=writer,
            peer_identity=b"test_identity",
            peer_fingerprint="abcd:1234",
            is_authenticated=True,
        )

        assert state.peer_identity == b"test_identity"
        assert state.peer_fingerprint == "abcd:1234"
        assert state.is_authenticated is True


class TestClientSession:
    """Tests for ClientSession dataclass."""

    def test_client_session_creation(self):
        """Test creating a client session."""
        reader = MagicMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)

        session = ClientSession(
            reader=reader,
            writer=writer,
            peer_address=("192.168.1.100", 5364),
        )

        assert session.reader is reader
        assert session.writer is writer
        assert session.peer_address == ("192.168.1.100", 5364)
        assert session.peer_identity is None
        assert session.is_authenticated is False


class TestCreateClient:
    """Tests for create_client factory function."""

    def test_create_client_returns_async_client(self):
        """Test that create_client returns an AsyncClient."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            keypair = IdentityKeyPair.generate()
            mock_identity.return_value = MagicMock(keypair=keypair)

            client = create_client()

            assert isinstance(client, AsyncClient)
            assert client.identity is keypair


class TestAsyncClient:
    """Tests for AsyncClient class."""

    def test_client_initialization(self):
        """Test client initialization."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            keypair = IdentityKeyPair.generate()
            mock_identity.return_value = MagicMock(keypair=keypair)

            client = AsyncClient()

            assert client.identity is keypair
            assert client._connection is None
            assert client._timeout == 30.0

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        """Test disconnect when not connected does nothing."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())

            client = AsyncClient()
            # Should not raise
            await client.disconnect()

            assert client._connection is None

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        """Test connection timeout handling."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())

            client = AsyncClient()
            client._timeout = 0.001  # Very short timeout

            with patch("asyncio.open_connection", side_effect=TimeoutError()):
                result = await client.connect("localhost", 9999)

            assert result is False

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test connection failure handling."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())

            client = AsyncClient()

            with patch(
                "asyncio.open_connection",
                side_effect=ConnectionRefusedError("Connection refused"),
            ):
                result = await client.connect("localhost", 9999)

            assert result is False

    @pytest.mark.asyncio
    async def test_send_message_raw_not_connected(self):
        """Test sending message when not connected raises error."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())

            client = AsyncClient()

            with pytest.raises(RuntimeError, match="Not connected"):
                from pytodo_qt.net.protocol import Message, MessageType

                msg = Message.create(MessageType.PING, b"")
                await client._send_message_raw(msg)

    @pytest.mark.asyncio
    async def test_recv_message_not_connected(self):
        """Test receiving message when not connected returns None."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())

            client = AsyncClient()

            result = await client._recv_message()
            assert result is None

    @pytest.mark.asyncio
    async def test_recv_message_raw_not_connected(self):
        """Test receiving raw message when not connected returns None."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())

            client = AsyncClient()

            result = await client._recv_message_raw()
            assert result is None


class TestAsyncServer:
    """Tests for AsyncServer class."""

    def test_server_creation(self):
        """Test server creation with defaults."""
        server = AsyncServer()

        assert server.host == "0.0.0.0"
        assert server.port == 5364
        assert server.identity is None
        assert server._server is None
        assert server.handshake_timeout == 30.0
        assert server.message_timeout == 60.0

    def test_server_custom_config(self):
        """Test server creation with custom config."""
        server = AsyncServer(host="127.0.0.1", port=9999)

        assert server.host == "127.0.0.1"
        assert server.port == 9999

    def test_is_running_not_started(self):
        """Test is_running when server not started."""
        server = AsyncServer()

        assert server.is_running is False

    @pytest.mark.asyncio
    async def test_stop_not_started(self):
        """Test stopping server when not started does nothing."""
        server = AsyncServer()

        # Should not raise
        await server.stop()

        assert server._server is None

    @pytest.mark.asyncio
    async def test_serve_forever_not_started(self):
        """Test serve_forever raises when not started."""
        server = AsyncServer()

        with pytest.raises(RuntimeError, match="Server not started"):
            await server.serve_forever()


class TestStartServer:
    """Tests for start_server convenience function."""

    @pytest.mark.asyncio
    async def test_start_server_creates_server(self):
        """Test that start_server creates and starts a server."""
        with patch("pytodo_qt.net.server.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())

            # Mock the asyncio server
            mock_server = AsyncMock()
            mock_server.sockets = []

            with patch("asyncio.start_server", return_value=mock_server):
                server = await start_server(host="127.0.0.1", port=9999)

                assert isinstance(server, AsyncServer)
                assert server.host == "127.0.0.1"
                assert server.port == 9999
                assert server._server is mock_server


class TestClientSignals:
    """Tests for client Qt signals."""

    def test_client_has_signals(self):
        """Test that client has Qt signals defined."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())

            client = AsyncClient()

            # Check signals exist
            assert hasattr(client, "sync_completed")
            assert hasattr(client, "sync_failed")
            assert hasattr(client, "connected")
            assert hasattr(client, "disconnected")


class TestClientHandshakeValidation:
    """Tests for client handshake validation."""

    @pytest.mark.asyncio
    async def test_perform_handshake_no_connection(self):
        """Test handshake fails when no connection."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())

            client = AsyncClient()

            result = await client._perform_handshake()

            assert result is False

    @pytest.mark.asyncio
    async def test_perform_handshake_no_identity(self):
        """Test handshake fails when no identity."""
        with patch("pytodo_qt.net.client.get_or_create_identity") as mock_identity:
            mock_identity.return_value = MagicMock(keypair=None)

            client = AsyncClient()
            client.identity = None
            client._connection = MagicMock()

            result = await client._perform_handshake()

            assert result is False


class TestServerCallbacks:
    """Tests for server callback configuration."""

    @pytest.mark.asyncio
    async def test_server_callbacks_set_on_start(self):
        """Test that callbacks are set when starting server."""
        with patch("pytodo_qt.net.server.get_or_create_identity") as mock_identity:
            from pytodo_qt.crypto.key_exchange import IdentityKeyPair

            mock_identity.return_value = MagicMock(keypair=IdentityKeyPair.generate())

            server = AsyncServer()

            get_sync = MagicMock()
            on_sync = MagicMock()
            on_connect = MagicMock()
            on_disconnect = MagicMock()

            mock_server = AsyncMock()
            mock_server.sockets = []

            with patch("asyncio.start_server", return_value=mock_server):
                await server.start(
                    get_sync_data=get_sync,
                    on_sync_received=on_sync,
                    on_client_connected=on_connect,
                    on_client_disconnected=on_disconnect,
                )

            assert server._get_sync_data is get_sync
            assert server._on_sync_received is on_sync
            assert server._on_client_connected is on_connect
            assert server._on_client_disconnected is on_disconnect
