"""Network module for pytodo-qt.

Provides:
- Async TCP server and client with authenticated encryption
- Protocol v2.0 with Ed25519/X25519 handshake
- Zeroconf/mDNS service discovery
"""

from .client import AsyncClient, create_client
from .discovery import (
    SERVICE_TYPE,
    DiscoveredPeer,
    DiscoveryService,
    get_discovery_service,
    start_discovery,
    stop_discovery,
)
from .protocol import (
    PROTOCOL_VERSION,
    ErrorCode,
    Message,
    MessageHeader,
    MessageType,
)
from .server import AsyncServer, start_server

__all__ = [
    # Protocol
    "PROTOCOL_VERSION",
    "ErrorCode",
    "Message",
    "MessageHeader",
    "MessageType",
    # Discovery
    "DiscoveredPeer",
    "DiscoveryService",
    "SERVICE_TYPE",
    "get_discovery_service",
    "start_discovery",
    "stop_discovery",
    # Server
    "AsyncServer",
    "start_server",
    # Client
    "AsyncClient",
    "create_client",
]
