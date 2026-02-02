"""Tests for mDNS/Zeroconf discovery module."""

from unittest.mock import MagicMock, patch

from pytodo_qt.net.discovery import (
    SERVICE_TYPE,
    DiscoveredPeer,
    DiscoveryService,
    get_discovery_service,
)


class TestDiscoveredPeer:
    """Tests for DiscoveredPeer dataclass."""

    def test_peer_creation(self):
        """Test creating a discovered peer."""
        peer = DiscoveredPeer(
            name="pytodo-laptop",
            address="192.168.1.100",
            port=5364,
            hostname="laptop.local",
            fingerprint="abcd:1234:efgh:5678",
            protocol_version=2,
        )

        assert peer.name == "pytodo-laptop"
        assert peer.address == "192.168.1.100"
        assert peer.port == 5364
        assert peer.hostname == "laptop.local"
        assert peer.fingerprint == "abcd:1234:efgh:5678"
        assert peer.protocol_version == 2
        assert peer.is_local is False

    def test_peer_display_name_remote(self):
        """Test display name for remote peer."""
        peer = DiscoveredPeer(
            name="pytodo-desktop",
            address="192.168.1.101",
            port=5364,
            hostname="desktop.local",
            fingerprint="1234:5678:abcd:efgh",
            protocol_version=2,
            is_local=False,
        )

        assert peer.display_name == "pytodo-desktop"

    def test_peer_display_name_local(self):
        """Test display name for local peer."""
        peer = DiscoveredPeer(
            name="pytodo-myhost",
            address="127.0.0.1",
            port=5364,
            hostname="myhost.local",
            fingerprint="aaaa:bbbb:cccc:dddd",
            protocol_version=2,
            is_local=True,
        )

        assert peer.display_name == "pytodo-myhost (this device)"


class TestServiceType:
    """Test service type constant."""

    def test_service_type(self):
        """Test service type is correctly defined."""
        assert SERVICE_TYPE == "_pytodo._tcp.local."


class TestDiscoveryService:
    """Tests for DiscoveryService."""

    def test_initial_state(self):
        """Test initial state of discovery service."""
        service = DiscoveryService()

        assert service._zeroconf is None
        assert service._browser is None
        assert service._service_info is None
        assert len(service._peers) == 0

    def test_get_peers_empty(self):
        """Test getting peers when none discovered."""
        service = DiscoveryService()

        peers = service.get_peers()

        assert peers == []

    def test_get_peer_not_found(self):
        """Test getting a peer that doesn't exist."""
        service = DiscoveryService()

        peer = service.get_peer("nonexistent")

        assert peer is None

    def test_add_peer(self):
        """Test adding a peer."""
        service = DiscoveryService()
        peer = DiscoveredPeer(
            name="test-peer",
            address="192.168.1.100",
            port=5364,
            hostname="test.local",
            fingerprint="test:finger:print",
            protocol_version=2,
        )

        service._add_peer(peer)

        assert len(service.get_peers()) == 1
        assert service.get_peer("test-peer") == peer

    def test_add_peer_with_callback(self):
        """Test adding a peer triggers callback."""
        service = DiscoveryService()
        callback = MagicMock()
        service._on_peer_added = callback

        peer = DiscoveredPeer(
            name="test-peer",
            address="192.168.1.100",
            port=5364,
            hostname="test.local",
            fingerprint="test:finger:print",
            protocol_version=2,
        )

        service._add_peer(peer)

        callback.assert_called_once_with(peer)

    def test_add_peer_callback_exception_handled(self):
        """Test that callback exceptions are handled."""
        service = DiscoveryService()
        callback = MagicMock(side_effect=Exception("Callback error"))
        service._on_peer_added = callback

        peer = DiscoveredPeer(
            name="test-peer",
            address="192.168.1.100",
            port=5364,
            hostname="test.local",
            fingerprint="test:finger:print",
            protocol_version=2,
        )

        # Should not raise
        service._add_peer(peer)

        # Peer should still be added
        assert service.get_peer("test-peer") == peer

    def test_remove_peer(self):
        """Test removing a peer."""
        service = DiscoveryService()
        peer = DiscoveredPeer(
            name="test-peer",
            address="192.168.1.100",
            port=5364,
            hostname="test.local",
            fingerprint="test:finger:print",
            protocol_version=2,
        )
        service._add_peer(peer)

        service._remove_peer("test-peer")

        assert len(service.get_peers()) == 0
        assert service.get_peer("test-peer") is None

    def test_remove_peer_with_callback(self):
        """Test removing a peer triggers callback."""
        service = DiscoveryService()
        callback = MagicMock()
        service._on_peer_removed = callback

        peer = DiscoveredPeer(
            name="test-peer",
            address="192.168.1.100",
            port=5364,
            hostname="test.local",
            fingerprint="test:finger:print",
            protocol_version=2,
        )
        service._add_peer(peer)

        service._remove_peer("test-peer")

        callback.assert_called_once_with("test-peer")

    def test_remove_peer_not_found(self):
        """Test removing a peer that doesn't exist."""
        service = DiscoveryService()
        callback = MagicMock()
        service._on_peer_removed = callback

        # Should not raise
        service._remove_peer("nonexistent")

        # Callback should not be called
        callback.assert_not_called()

    def test_stop_clears_peers(self):
        """Test stopping service clears peers."""
        service = DiscoveryService()
        peer = DiscoveredPeer(
            name="test-peer",
            address="192.168.1.100",
            port=5364,
            hostname="test.local",
            fingerprint="test:finger:print",
            protocol_version=2,
        )
        service._add_peer(peer)

        service.stop()

        assert len(service.get_peers()) == 0

    def test_get_local_addresses(self):
        """Test getting local addresses."""
        service = DiscoveryService()

        addresses = service._get_local_addresses()

        # Should return at least localhost
        assert len(addresses) >= 1
        # Each address should be 4 bytes (IPv4)
        for addr in addresses:
            assert len(addr) == 4


class TestGetDiscoveryService:
    """Tests for global discovery service."""

    def test_get_discovery_service_singleton(self):
        """Test get_discovery_service returns same instance."""
        # Reset global instance
        import pytodo_qt.net.discovery as discovery_module

        discovery_module._discovery_service = None

        service1 = get_discovery_service()
        service2 = get_discovery_service()

        assert service1 is service2

        # Clean up
        discovery_module._discovery_service = None


class TestPeerListener:
    """Tests for _PeerListener class."""

    def test_add_service_creates_peer(self):
        """Test add_service creates peer from service info."""
        from pytodo_qt.net.discovery import _PeerListener

        service = DiscoveryService()
        listener = _PeerListener(service)

        # Mock Zeroconf and ServiceInfo
        mock_zc = MagicMock()
        mock_info = MagicMock()
        mock_info.parsed_addresses.return_value = ["192.168.1.100"]
        mock_info.port = 5364
        mock_info.properties = {
            b"fingerprint": b"test:fingerprint",
            b"version": b"2",
            b"hostname": b"testhost",
        }
        mock_zc.get_service_info.return_value = mock_info

        with patch("pytodo_qt.net.discovery.get_config") as mock_config:
            mock_config.return_value.discovery.get_service_name.return_value = "other-service"

            listener.add_service(mock_zc, SERVICE_TYPE, f"test-peer.{SERVICE_TYPE}")

        # Peer should be added
        peer = service.get_peer("test-peer")
        assert peer is not None
        assert peer.address == "192.168.1.100"
        assert peer.port == 5364
        assert peer.fingerprint == "test:fingerprint"

    def test_add_service_no_info(self):
        """Test add_service handles missing service info."""
        from pytodo_qt.net.discovery import _PeerListener

        service = DiscoveryService()
        listener = _PeerListener(service)

        mock_zc = MagicMock()
        mock_zc.get_service_info.return_value = None

        # Should not raise
        listener.add_service(mock_zc, SERVICE_TYPE, f"test-peer.{SERVICE_TYPE}")

        # No peer should be added
        assert len(service.get_peers()) == 0

    def test_add_service_no_addresses(self):
        """Test add_service handles service with no addresses."""
        from pytodo_qt.net.discovery import _PeerListener

        service = DiscoveryService()
        listener = _PeerListener(service)

        mock_zc = MagicMock()
        mock_info = MagicMock()
        mock_info.parsed_addresses.return_value = []
        mock_zc.get_service_info.return_value = mock_info

        # Should not raise
        listener.add_service(mock_zc, SERVICE_TYPE, f"test-peer.{SERVICE_TYPE}")

        # No peer should be added
        assert len(service.get_peers()) == 0

    def test_remove_service(self):
        """Test remove_service removes peer."""
        from pytodo_qt.net.discovery import _PeerListener

        service = DiscoveryService()
        listener = _PeerListener(service)

        # Add a peer first
        peer = DiscoveredPeer(
            name="test-peer",
            address="192.168.1.100",
            port=5364,
            hostname="test.local",
            fingerprint="test:finger:print",
            protocol_version=2,
        )
        service._add_peer(peer)

        mock_zc = MagicMock()
        listener.remove_service(mock_zc, SERVICE_TYPE, f"test-peer.{SERVICE_TYPE}")

        assert service.get_peer("test-peer") is None

    def test_update_service(self):
        """Test update_service re-adds peer."""
        from pytodo_qt.net.discovery import _PeerListener

        service = DiscoveryService()
        listener = _PeerListener(service)

        # Add a peer first
        peer = DiscoveredPeer(
            name="test-peer",
            address="192.168.1.100",
            port=5364,
            hostname="test.local",
            fingerprint="old:fingerprint",
            protocol_version=2,
        )
        service._add_peer(peer)

        # Mock updated service info
        mock_zc = MagicMock()
        mock_info = MagicMock()
        mock_info.parsed_addresses.return_value = ["192.168.1.101"]  # New address
        mock_info.port = 5365  # New port
        mock_info.properties = {
            b"fingerprint": b"new:fingerprint",
            b"version": b"2",
            b"hostname": b"testhost",
        }
        mock_zc.get_service_info.return_value = mock_info

        with patch("pytodo_qt.net.discovery.get_config") as mock_config:
            mock_config.return_value.discovery.get_service_name.return_value = "other-service"

            listener.update_service(mock_zc, SERVICE_TYPE, f"test-peer.{SERVICE_TYPE}")

        # Peer should be updated
        updated_peer = service.get_peer("test-peer")
        assert updated_peer is not None
        assert updated_peer.address == "192.168.1.101"
        assert updated_peer.port == 5365
        assert updated_peer.fingerprint == "new:fingerprint"

    def test_add_service_marks_local(self):
        """Test add_service correctly marks local service."""
        from pytodo_qt.net.discovery import _PeerListener

        service = DiscoveryService()
        listener = _PeerListener(service)

        mock_zc = MagicMock()
        mock_info = MagicMock()
        mock_info.parsed_addresses.return_value = ["192.168.1.100"]
        mock_info.port = 5364
        mock_info.properties = {
            b"fingerprint": b"my:fingerprint",
            b"version": b"2",
            b"hostname": b"myhost",
        }
        mock_zc.get_service_info.return_value = mock_info

        with patch("pytodo_qt.net.discovery.get_config") as mock_config:
            # Service name matches our own
            mock_config.return_value.discovery.get_service_name.return_value = "my-service"

            listener.add_service(mock_zc, SERVICE_TYPE, f"my-service.{SERVICE_TYPE}")

        peer = service.get_peer("my-service")
        assert peer is not None
        assert peer.is_local is True
