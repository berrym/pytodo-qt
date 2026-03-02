"""Tests for mDNS/Zeroconf discovery module."""

import socket
from unittest.mock import MagicMock, patch

import pytest

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

    def test_remove_peer_deferred(self):
        """Test removing a peer is deferred (grace period)."""
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

        # Peer should still be present during grace period
        assert service.get_peer("test-peer") is not None
        assert "test-peer" in service._removal_timers

        # Cancel the timer to avoid leaking into other tests
        service._removal_timers["test-peer"].cancel()

    def test_confirm_remove_peer(self):
        """Test confirmed removal actually removes the peer."""
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

        # Directly call confirmed removal (simulates timer firing)
        service._confirm_remove_peer("test-peer")

        assert len(service.get_peers()) == 0
        assert service.get_peer("test-peer") is None

    def test_confirm_remove_peer_with_callback(self):
        """Test confirmed removal triggers callback."""
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

        service._confirm_remove_peer("test-peer")

        callback.assert_called_once_with("test-peer")

    def test_remove_peer_cancelled_by_readd(self):
        """Test deferred removal is cancelled when peer is re-added."""
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
        callback.reset_mock()

        # Start deferred removal
        service._remove_peer("test-peer")
        assert "test-peer" in service._removal_timers

        # Re-add same peer (TTL refresh)
        service._add_peer(peer)

        # Timer should be cancelled, peer still present
        assert "test-peer" not in service._removal_timers
        assert service.get_peer("test-peer") is not None
        # Same address/port → no callback (TTL refresh)
        callback.assert_not_called()

    def test_remove_peer_not_found(self):
        """Test removing a peer that doesn't exist."""
        service = DiscoveryService()
        callback = MagicMock()
        service._on_peer_removed = callback

        # Should not raise
        service._remove_peer("nonexistent")

        # Callback should not be called, no timer created
        callback.assert_not_called()
        assert "nonexistent" not in service._removal_timers

    def test_add_peer_ttl_refresh_suppresses_callback(self):
        """Test re-adding same peer with same address skips callback."""
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
        callback.assert_called_once()
        callback.reset_mock()

        # Re-add with same address/port → TTL refresh, no callback
        service._add_peer(peer)
        callback.assert_not_called()

    def test_add_peer_address_change_fires_callback(self):
        """Test re-adding peer with different address fires callback."""
        service = DiscoveryService()
        callback = MagicMock()
        service._on_peer_added = callback

        peer1 = DiscoveredPeer(
            name="test-peer",
            address="192.168.1.100",
            port=5364,
            hostname="test.local",
            fingerprint="test:finger:print",
            protocol_version=2,
        )
        service._add_peer(peer1)
        callback.reset_mock()

        # Re-add with new address → fires callback
        peer2 = DiscoveredPeer(
            name="test-peer",
            address="192.168.1.200",
            port=5364,
            hostname="test.local",
            fingerprint="test:finger:print",
            protocol_version=2,
        )
        service._add_peer(peer2)
        callback.assert_called_once_with(peer2)

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

        # Should return at least one address
        assert len(addresses) >= 1
        # Each address should be 4 bytes (IPv4) or 16 bytes (IPv6)
        for addr in addresses:
            assert len(addr) in (4, 16)

    def test_get_local_addresses_preferred_first(self):
        """Test that routing-derived preferred address is first."""
        service = DiscoveryService()

        preferred = service._get_preferred_address(socket.AF_INET)
        if preferred is None:
            pytest.skip("No IPv4 preferred address available")

        addresses = service._get_local_addresses()
        # First address should be the preferred IPv4 address
        assert addresses[0] == socket.inet_aton(preferred)

    def test_get_preferred_address_ipv4(self):
        """Test IPv4 preferred address detection via routing table."""
        service = DiscoveryService()

        addr = service._get_preferred_address(socket.AF_INET)

        # Should return a non-loopback address on a networked machine
        # (may be None in isolated environments like CI)
        if addr is not None:
            assert not addr.startswith("127.")
            assert "." in addr  # Valid IPv4 format

    def test_get_preferred_address_ipv6(self):
        """Test IPv6 preferred address detection via routing table."""
        service = DiscoveryService()

        addr = service._get_preferred_address(socket.AF_INET6)

        # May be None if no IPv6 connectivity
        if addr is not None:
            assert addr != "::1"
            assert not addr.startswith("fe80:")

    def test_is_unusable_address(self):
        """Test address filtering for unusable addresses."""
        assert DiscoveryService._is_unusable_address("127.0.0.1") is True
        assert DiscoveryService._is_unusable_address("127.0.1.1") is True
        assert DiscoveryService._is_unusable_address("169.254.1.1") is True
        assert DiscoveryService._is_unusable_address("::1") is True
        assert DiscoveryService._is_unusable_address("fe80::1") is True
        assert DiscoveryService._is_unusable_address("fe80::abcd:1234") is True

        assert DiscoveryService._is_unusable_address("192.168.1.1") is False
        assert DiscoveryService._is_unusable_address("10.0.0.1") is False
        assert DiscoveryService._is_unusable_address("172.17.0.1") is False
        assert DiscoveryService._is_unusable_address("2001:db8::1") is False
        assert DiscoveryService._is_unusable_address("fd00::1") is False


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

    def test_remove_service_defers_removal(self):
        """Test remove_service starts deferred removal."""
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

        # Peer is still present during grace period
        assert service.get_peer("test-peer") is not None
        assert "test-peer" in service._removal_timers

        # Confirmed removal works
        service._confirm_remove_peer("test-peer")
        assert service.get_peer("test-peer") is None

    def test_update_service(self):
        """Test update_service re-adds peer with updated info."""
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

        # Mock updated service info with new address/port
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

        # Peer should be updated (address changed so callback fires)
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

    def test_add_service_prefers_ipv4(self):
        """Test that add_service prefers IPv4 when both are available."""
        from pytodo_qt.net.discovery import _PeerListener

        service = DiscoveryService()
        listener = _PeerListener(service)

        mock_zc = MagicMock()
        mock_info = MagicMock()
        # IPv6 first, IPv4 second — should still pick IPv4
        mock_info.parsed_addresses.return_value = [
            "2001:db8::1",
            "192.168.1.100",
        ]
        mock_info.port = 5364
        mock_info.properties = {
            b"fingerprint": b"test:fingerprint",
            b"version": b"2",
            b"hostname": b"testhost",
        }
        mock_zc.get_service_info.return_value = mock_info

        with patch("pytodo_qt.net.discovery.get_config") as mock_config:
            mock_config.return_value.discovery.get_service_name.return_value = "other"

            listener.add_service(mock_zc, SERVICE_TYPE, f"test-peer.{SERVICE_TYPE}")

        peer = service.get_peer("test-peer")
        assert peer is not None
        assert peer.address == "192.168.1.100"

    def test_add_service_falls_back_to_ipv6(self):
        """Test that add_service uses IPv6 when no IPv4 is available."""
        from pytodo_qt.net.discovery import _PeerListener

        service = DiscoveryService()
        listener = _PeerListener(service)

        mock_zc = MagicMock()
        mock_info = MagicMock()
        mock_info.parsed_addresses.return_value = ["2001:db8::1"]
        mock_info.port = 5364
        mock_info.properties = {
            b"fingerprint": b"test:fingerprint",
            b"version": b"2",
            b"hostname": b"testhost",
        }
        mock_zc.get_service_info.return_value = mock_info

        with patch("pytodo_qt.net.discovery.get_config") as mock_config:
            mock_config.return_value.discovery.get_service_name.return_value = "other"

            listener.add_service(mock_zc, SERVICE_TYPE, f"test-peer.{SERVICE_TYPE}")

        peer = service.get_peer("test-peer")
        assert peer is not None
        assert peer.address == "2001:db8::1"


class TestHealthCheck:
    """Tests for the periodic health check."""

    def test_no_update_when_addresses_unchanged(self):
        """Health check should not log changes when addresses are the same."""
        service = DiscoveryService()
        service._zeroconf = MagicMock()
        service._zeroconf.done = False
        service._service_info = MagicMock()
        addrs = [socket.inet_aton("192.168.1.10")]
        service._registered_addresses = set(addrs)

        with (
            patch.object(service, "_get_local_addresses", return_value=addrs),
            patch.object(service, "_schedule_health_check"),
        ):
            service._run_health_check()

        # update_service still called as health probe, but no address mutation
        service._zeroconf.update_service.assert_called_once()
        assert service._registered_addresses == set(addrs)

    def test_no_false_positive_with_ipv6(self):
        """Health check must not report changes when IPv6 addresses exist."""
        service = DiscoveryService()
        service._zeroconf = MagicMock()
        service._zeroconf.done = False
        service._service_info = MagicMock()
        ipv4 = socket.inet_aton("192.168.1.10")
        ipv6 = socket.inet_pton(socket.AF_INET6, "fd00::1")
        addrs = [ipv4, ipv6]
        service._registered_addresses = set(addrs)

        with (
            patch.object(service, "_get_local_addresses", return_value=addrs),
            patch.object(service, "_schedule_health_check"),
        ):
            service._run_health_check()

        # Addresses unchanged — registered_addresses must not change
        assert service._registered_addresses == {ipv4, ipv6}

    def test_update_when_addresses_changed(self):
        """Health check should call update_service and update state on change."""
        service = DiscoveryService()
        service._zeroconf = MagicMock()
        service._zeroconf.done = False
        service._service_info = MagicMock()
        old = [socket.inet_aton("192.168.1.10")]
        new = [socket.inet_aton("192.168.1.20")]
        service._registered_addresses = set(old)

        with (
            patch.object(service, "_get_local_addresses", return_value=new),
            patch.object(service, "_schedule_health_check"),
        ):
            service._run_health_check()

        service._zeroconf.update_service.assert_called_once_with(service._service_info)
        assert service._registered_addresses == set(new)

    def test_restart_when_zeroconf_done(self):
        """Health check should restart when zeroconf.done is True."""
        service = DiscoveryService()
        service._zeroconf = MagicMock()
        service._zeroconf.done = True
        service._service_info = MagicMock()

        with patch.object(service, "_restart") as mock_restart:
            service._run_health_check()

        mock_restart.assert_called_once()

    def test_restart_when_update_service_fails(self):
        """Health check should restart when update_service raises."""
        service = DiscoveryService()
        service._zeroconf = MagicMock()
        service._zeroconf.done = False
        service._zeroconf.update_service.side_effect = OSError("stale socket")
        service._service_info = MagicMock()
        addrs = [socket.inet_aton("192.168.1.10")]
        service._registered_addresses = set(addrs)

        with (
            patch.object(service, "_get_local_addresses", return_value=addrs),
            patch.object(service, "_restart") as mock_restart,
        ):
            service._run_health_check()

        mock_restart.assert_called_once()
