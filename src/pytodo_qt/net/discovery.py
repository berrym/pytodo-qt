"""discovery.py

Zeroconf/mDNS service discovery for pytodo-qt.
"""

from __future__ import annotations

import contextlib
import socket
import threading
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

# Periodic health-check interval (seconds)
_HEALTH_CHECK_INTERVAL = 20 * 60  # 20 minutes

# Grace period before confirming a peer removal (seconds).
# mDNS TTL refreshes cause brief remove→add cycles; this absorbs them.
_REMOVE_GRACE_PERIOD = 30.0

# Extended TTL for our service's PTR/TXT records (seconds).
# Default is 4500 s (75 min); 7200 s (2 h) reduces refresh-churn frequency.
_SERVICE_OTHER_TTL = 7200


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
    # Deferred removal timers keyed by peer name
    _removal_timers: dict[str, threading.Timer] = field(default_factory=dict)
    # Health-check timer
    _health_timer: threading.Timer | None = None
    # Saved start() parameters so _restart() can re-use them
    _start_port: int = 0
    _start_fingerprint: str = ""
    _start_protocol_version: int = 2

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

        # Persist for _restart()
        self._start_port = port
        self._start_fingerprint = fingerprint
        self._start_protocol_version = protocol_version
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
                other_ttl=_SERVICE_OTHER_TTL,
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

            # Start periodic health check
            self._schedule_health_check()

        except Exception as e:
            logger.log.exception("Failed to start discovery: %s", e)
            self.stop()
            raise

    def stop(self) -> None:
        """Stop service advertisement and discovery."""
        # Cancel health-check timer
        if self._health_timer is not None:
            self._health_timer.cancel()
            self._health_timer = None

        # Cancel all pending removal timers
        for timer in self._removal_timers.values():
            timer.cancel()
        self._removal_timers.clear()

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

    # ------------------------------------------------------------------
    # Health check & re-registration
    # ------------------------------------------------------------------

    def _schedule_health_check(self) -> None:
        """Schedule the next periodic health check."""
        self._health_timer = threading.Timer(_HEALTH_CHECK_INTERVAL, self._run_health_check)
        self._health_timer.daemon = True
        self._health_timer.start()

    def _run_health_check(self) -> None:
        """Periodic health check: refresh addresses and re-broadcast."""
        if self._zeroconf is None or self._service_info is None:
            return

        try:
            new_addresses = self._get_local_addresses()
            old_addresses = list(self._service_info.addresses)

            if set(new_addresses) != set(old_addresses):
                logger.log.info("Network addresses changed, updating service registration")
                self._service_info.addresses = new_addresses

            self._zeroconf.update_service(self._service_info)
            logger.log.debug("Health check: refreshed mDNS service registration")

        except Exception as e:
            logger.log.warning("Health check failed, restarting discovery: %s", e)
            self._restart()
            return

        # Schedule next check
        self._schedule_health_check()

    def _restart(self) -> None:
        """Tear down and re-create the Zeroconf instance."""
        logger.log.info("Restarting discovery service")
        # Save callbacks before stop() clears state
        on_added = self._on_peer_added
        on_removed = self._on_peer_removed
        port = self._start_port
        fingerprint = self._start_fingerprint
        version = self._start_protocol_version

        self.stop()
        try:
            self.start(
                port=port,
                fingerprint=fingerprint,
                protocol_version=version,
                on_peer_added=on_added,
                on_peer_removed=on_removed,
            )
        except Exception as e:
            logger.log.exception("Failed to restart discovery: %s", e)
            # Schedule another attempt
            self._schedule_health_check()

    # ------------------------------------------------------------------
    # Address helpers
    # ------------------------------------------------------------------

    def _get_local_addresses(self) -> list[bytes]:
        """Get local addresses for service registration.

        Uses OS routing table to find preferred outbound addresses for
        both IPv4 and IPv6. Only falls back to hostname-resolved addresses
        when the routing table probe returns nothing (e.g. no default
        route). This avoids advertising virtual interface addresses like
        Docker bridges that hostname resolution may include.
        """
        addresses: list[bytes] = []

        # Preferred addresses via routing table (most reliable)
        for family, pack_fn in [
            (socket.AF_INET, socket.inet_aton),
            (socket.AF_INET6, lambda a: socket.inet_pton(socket.AF_INET6, a)),
        ]:
            preferred = self._get_preferred_address(family)
            if preferred:
                with contextlib.suppress(OSError):
                    addresses.append(pack_fn(preferred))

        # Fall back to hostname resolution only if routing table gave nothing
        if not addresses:
            try:
                hostname = socket.gethostname()
                for family in (socket.AF_INET, socket.AF_INET6):
                    try:
                        for addr_info in socket.getaddrinfo(hostname, None, family):
                            addr: str = str(addr_info[4][0])
                            if self._is_unusable_address(addr):
                                continue
                            if family == socket.AF_INET:
                                packed = socket.inet_aton(addr)
                            else:
                                packed = socket.inet_pton(socket.AF_INET6, addr)
                            if packed not in addresses:
                                addresses.append(packed)
                    except socket.gaierror:
                        pass
            except Exception as e:
                logger.log.warning("Error getting local addresses: %s", e)

        if not addresses:
            addresses.append(socket.inet_aton("127.0.0.1"))

        return addresses

    def _get_preferred_address(self, family: socket.AddressFamily) -> str | None:
        """Determine the preferred outbound address via OS routing.

        Opens a UDP socket and connects to a non-routable address without
        sending data. The OS selects the outbound interface based on its
        routing table, naturally avoiding virtual interfaces (Docker
        bridges, container networks) that lack a default route.
        """
        if family == socket.AF_INET:
            target = ("10.255.255.255", 1)
        else:
            # RFC 3849 documentation prefix — non-routable but triggers
            # a valid routing table lookup on IPv6-capable machines.
            target = ("2001:db8::1", 1)
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as s:
                s.connect(target)
                addr = s.getsockname()[0]
                if addr and addr not in ("0.0.0.0", "::"):
                    return addr
        except Exception as e:
            label = "IPv4" if family == socket.AF_INET else "IPv6"
            logger.log.debug("Could not determine preferred %s address: %s", label, e)
        return None

    @staticmethod
    def _is_unusable_address(addr: str) -> bool:
        """Check if an address is unsuitable for peer discovery."""
        return (
            addr.startswith("127.")  # IPv4 loopback
            or addr.startswith("169.254.")  # IPv4 link-local (APIPA)
            or addr == "::1"  # IPv6 loopback
            or addr.startswith("fe80:")  # IPv6 link-local
        )

    # ------------------------------------------------------------------
    # Peer tracking with churn suppression
    # ------------------------------------------------------------------

    def _add_peer(self, peer: DiscoveredPeer) -> None:
        """Add or refresh a discovered peer.

        If the peer is already known with the same address and port this
        is treated as an mDNS TTL refresh — the entry is updated silently
        without firing the on_peer_added callback.
        """
        # Cancel any pending deferred removal for this peer
        timer = self._removal_timers.pop(peer.name, None)
        if timer is not None:
            timer.cancel()
            logger.log.debug("Cancelled deferred removal for %s (TTL refresh)", peer.name)

        existing = self._peers.get(peer.name)
        self._peers[peer.name] = peer

        if existing is not None and existing.address == peer.address and existing.port == peer.port:
            # Same endpoint — treat as TTL refresh, no callback
            logger.log.debug(
                "TTL refresh for peer: %s at %s:%d",
                peer.name,
                peer.address,
                peer.port,
            )
            return

        logger.log.info("Discovered peer: %s at %s:%d", peer.name, peer.address, peer.port)
        if self._on_peer_added:
            try:
                self._on_peer_added(peer)
            except Exception as e:
                logger.log.exception("Error in peer added callback: %s", e)

    def _remove_peer(self, name: str) -> None:
        """Schedule deferred removal of a peer.

        A grace period absorbs the brief remove→add cycles caused by
        mDNS TTL refreshes.  If the peer is re-added within the window
        the removal is cancelled (see ``_add_peer``).
        """
        if name not in self._peers:
            return

        # If there is already a pending removal, let it run
        if name in self._removal_timers:
            return

        timer = threading.Timer(_REMOVE_GRACE_PERIOD, self._confirm_remove_peer, args=(name,))
        timer.daemon = True
        self._removal_timers[name] = timer
        timer.start()
        logger.log.debug(
            "Deferred removal for %s (%.0fs grace period)",
            name,
            _REMOVE_GRACE_PERIOD,
        )

    def _confirm_remove_peer(self, name: str) -> None:
        """Actually remove a peer after the grace period elapsed."""
        self._removal_timers.pop(name, None)
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

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is discovered."""
        info = zc.get_service_info(type_, name)
        if info is None:
            return

        try:
            # Parse service info — prefer IPv4 for wider compatibility
            addresses = info.parsed_addresses()
            if not addresses:
                return

            ipv4 = [a for a in addresses if "." in a]
            address = ipv4[0] if ipv4 else addresses[0]
            port = info.port
            if port is None:
                return
            properties = info.properties

            fingerprint = (properties.get(b"fingerprint") or b"").decode("utf-8")
            version = int((properties.get(b"version") or b"2").decode("utf-8"))
            hostname = (properties.get(b"hostname") or b"unknown").decode("utf-8")

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

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is removed."""
        service_name = name.replace(f".{SERVICE_TYPE}", "")
        self._discovery._remove_peer(service_name)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is updated."""
        # Re-add handles both update and TTL-refresh logic
        self.add_service(zc, type_, name)


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
