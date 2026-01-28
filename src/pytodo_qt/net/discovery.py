"""discovery.py

Zeroconf/mDNS service discovery for pytodo-qt.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from ..core.config import get_config
from ..core.logger import Logger

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


# Service type for pytodo-qt
SERVICE_TYPE = "_pytodo._tcp.local."


@dataclass
class DiscoveredPeer:
    """Information about a discovered peer on the network."""

    name: str
    address: str
    port: int
    hostname: str
    fingerprint: str
    protocol_version: int
    is_local: bool = False  # True if this is our own service

    @property
    def display_name(self) -> str:
        """Get a user-friendly display name."""
        if self.is_local:
            return f"{self.name} (this device)"
        return self.name


@dataclass
class DiscoveryService:
    """Manages Zeroconf service advertisement and discovery."""

    _zeroconf: Zeroconf | None = None
    _browser: ServiceBrowser | None = None
    _service_info: ServiceInfo | None = None
    _peers: dict[str, DiscoveredPeer] = field(default_factory=dict)
    _listener: _PeerListener | None = None
    _on_peer_added: Callable[[DiscoveredPeer], None] | None = None
    _on_peer_removed: Callable[[str], None] | None = None

    def start(
        self,
        port: int,
        fingerprint: str,
        protocol_version: int = 2,
        on_peer_added: Callable[[DiscoveredPeer], None] | None = None,
        on_peer_removed: Callable[[str], None] | None = None,
    ) -> None:
        """Start service advertisement and discovery.

        Args:
            port: Port the server is listening on
            fingerprint: Our identity fingerprint
            protocol_version: Protocol version we support
            on_peer_added: Callback when a peer is discovered
            on_peer_removed: Callback when a peer disappears
        """
        if self._zeroconf is not None:
            logger.log.warning("Discovery already started")
            return

        self._on_peer_added = on_peer_added
        self._on_peer_removed = on_peer_removed

        try:
            zc = Zeroconf()
            self._zeroconf = zc

            # Register our service
            config = get_config()
            service_name = config.discovery.get_service_name()
            hostname = socket.gethostname()

            # Get local addresses
            addresses = self._get_local_addresses()
            if not addresses:
                logger.log.warning("No local addresses found for discovery")
                addresses = [socket.inet_aton("127.0.0.1")]

            self._service_info = ServiceInfo(
                SERVICE_TYPE,
                f"{service_name}.{SERVICE_TYPE}",
                port=port,
                properties={
                    "fingerprint": fingerprint,
                    "version": str(protocol_version),
                    "hostname": hostname,
                },
                addresses=addresses,
            )

            zc.register_service(self._service_info, allow_name_change=True)
            logger.log.info("Registered mDNS service: %s", service_name)

            # Start browsing for peers
            self._listener = _PeerListener(self)
            self._browser = ServiceBrowser(
                self._zeroconf,
                SERVICE_TYPE,
                self._listener,
            )
            logger.log.info("Started mDNS browser for %s", SERVICE_TYPE)

        except Exception as e:
            logger.log.exception("Failed to start discovery: %s", e)
            self.stop()
            raise

    def stop(self) -> None:
        """Stop service advertisement and discovery."""
        if self._service_info is not None and self._zeroconf is not None:
            try:
                self._zeroconf.unregister_service(self._service_info)
                logger.log.info("Unregistered mDNS service")
            except Exception as e:
                logger.log.warning("Error unregistering service: %s", e)
            self._service_info = None

        if self._browser is not None:
            try:
                self._browser.cancel()
            except Exception as e:
                logger.log.warning("Error canceling browser: %s", e)
            self._browser = None

        if self._zeroconf is not None:
            try:
                self._zeroconf.close()
            except Exception as e:
                logger.log.warning("Error closing zeroconf: %s", e)
            self._zeroconf = None

        self._peers.clear()
        self._listener = None
        logger.log.info("Discovery stopped")

    def get_peers(self) -> list[DiscoveredPeer]:
        """Get list of discovered peers."""
        return list(self._peers.values())

    def get_peer(self, name: str) -> DiscoveredPeer | None:
        """Get a specific peer by name."""
        return self._peers.get(name)

    def _get_local_addresses(self) -> list[bytes]:
        """Get local IPv4 addresses for service registration."""
        addresses = []
        try:
            # Get all local addresses
            hostname = socket.gethostname()
            for addr_info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                sockaddr = addr_info[4]
                addr: str = sockaddr[0]  # type: ignore[assignment]
                if not addr.startswith("127."):
                    addresses.append(socket.inet_aton(addr))
        except Exception as e:
            logger.log.warning("Error getting local addresses: %s", e)

        # Add localhost as fallback
        if not addresses:
            addresses.append(socket.inet_aton("127.0.0.1"))

        return addresses

    def _add_peer(self, peer: DiscoveredPeer) -> None:
        """Add a discovered peer."""
        self._peers[peer.name] = peer
        logger.log.info("Discovered peer: %s at %s:%d", peer.name, peer.address, peer.port)
        if self._on_peer_added:
            try:
                self._on_peer_added(peer)
            except Exception as e:
                logger.log.exception("Error in peer added callback: %s", e)

    def _remove_peer(self, name: str) -> None:
        """Remove a peer that is no longer available."""
        if name in self._peers:
            del self._peers[name]
            logger.log.info("Peer removed: %s", name)
            if self._on_peer_removed:
                try:
                    self._on_peer_removed(name)
                except Exception as e:
                    logger.log.exception("Error in peer removed callback: %s", e)


class _PeerListener(ServiceListener):
    """Internal listener for Zeroconf service events."""

    def __init__(self, discovery: DiscoveryService):
        self._discovery = discovery

    def add_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        """Called when a service is discovered."""
        info = zc.get_service_info(service_type, name)
        if info is None:
            return

        try:
            # Parse service info
            addresses = info.parsed_addresses()
            if not addresses:
                return

            address = addresses[0]
            port = info.port
            properties = info.properties

            fingerprint = properties.get(b"fingerprint", b"").decode("utf-8")
            version = int(properties.get(b"version", b"2").decode("utf-8"))
            hostname = properties.get(b"hostname", b"unknown").decode("utf-8")

            # Extract service name (remove service type suffix)
            service_name = name.replace(f".{SERVICE_TYPE}", "")

            # Check if this is our own service
            config = get_config()
            our_name = config.discovery.get_service_name()
            is_local = service_name == our_name

            peer = DiscoveredPeer(
                name=service_name,
                address=address,
                port=port,
                hostname=hostname,
                fingerprint=fingerprint,
                protocol_version=version,
                is_local=is_local,
            )

            self._discovery._add_peer(peer)

        except Exception as e:
            logger.log.exception("Error processing discovered service: %s", e)

    def remove_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        """Called when a service is removed."""
        service_name = name.replace(f".{SERVICE_TYPE}", "")
        self._discovery._remove_peer(service_name)

    def update_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        """Called when a service is updated."""
        # Treat update as remove + add
        self.remove_service(zc, service_type, name)
        self.add_service(zc, service_type, name)


# Global discovery service instance
_discovery_service: DiscoveryService | None = None


def get_discovery_service() -> DiscoveryService:
    """Get the global discovery service instance."""
    global _discovery_service
    if _discovery_service is None:
        _discovery_service = DiscoveryService()
    return _discovery_service


def start_discovery(
    port: int,
    fingerprint: str,
    on_peer_added: Callable[[DiscoveredPeer], None] | None = None,
    on_peer_removed: Callable[[str], None] | None = None,
) -> DiscoveryService:
    """Start the global discovery service."""
    service = get_discovery_service()
    service.start(
        port=port,
        fingerprint=fingerprint,
        on_peer_added=on_peer_added,
        on_peer_removed=on_peer_removed,
    )
    return service


def stop_discovery() -> None:
    """Stop the global discovery service."""
    if _discovery_service is not None:
        _discovery_service.stop()
