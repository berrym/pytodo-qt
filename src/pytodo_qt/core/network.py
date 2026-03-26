"""network.py

Shared network address resolution utilities.

Provides dual-stack (IPv4 + IPv6) address detection via OS routing
table probes, with hostname-resolution fallback. Used by both the web
server (TLS certificate SAN) and the Mobile Access Wizard (QR URL).
"""

from __future__ import annotations

import socket


def get_preferred_address(family: socket.AddressFamily) -> str | None:
    """Determine the preferred outbound address via OS routing table.

    Opens a UDP socket and connects to a non-routable address without
    sending data. The OS selects the outbound interface based on its
    routing table, naturally avoiding virtual interfaces (Docker bridges,
    container networks) that lack a default route.
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
    except OSError:
        pass
    return None


def is_unusable_address(addr: str) -> bool:
    """Check if an address is unsuitable for external access."""
    return (
        addr.startswith("127.")  # IPv4 loopback
        or addr.startswith("169.254.")  # IPv4 link-local (APIPA)
        or addr == "::1"  # IPv6 loopback
        or addr.startswith("fe80:")  # IPv6 link-local
    )


def get_all_local_addresses() -> tuple[list[str], list[str]]:
    """Return all usable local addresses as (ipv4_list, ipv6_list).

    Uses routing-table probe first (most reliable), falls back to
    hostname resolution if the probe yields nothing.
    """
    ipv4: list[str] = []
    ipv6: list[str] = []

    # Routing table probe (preferred)
    for family, out_list in [
        (socket.AF_INET, ipv4),
        (socket.AF_INET6, ipv6),
    ]:
        preferred = get_preferred_address(family)
        if preferred and not is_unusable_address(preferred):
            out_list.append(preferred)

    # Hostname resolution fallback
    if not ipv4 and not ipv6:
        try:
            hostname = socket.gethostname()
            for family, out_list in [
                (socket.AF_INET, ipv4),
                (socket.AF_INET6, ipv6),
            ]:
                try:
                    for info in socket.getaddrinfo(hostname, None, family):
                        addr = str(info[4][0])
                        if not is_unusable_address(addr) and addr not in out_list:
                            out_list.append(addr)
                except socket.gaierror:
                    pass
        except OSError:
            pass

    return ipv4, ipv6


def get_lan_ip() -> str | None:
    """Return the preferred LAN IPv4 address, or None."""
    return get_preferred_address(socket.AF_INET)


def get_local_hostname() -> str | None:
    """Return the mDNS .local hostname, or None."""
    try:
        hostname = socket.gethostname()
        if hostname and hostname != "localhost":
            # Strip any existing .local suffix
            if hostname.endswith(".local"):
                return hostname
            return f"{hostname}.local"
    except OSError:
        pass
    return None


def format_url(host: str, port: int) -> str:
    """Format an HTTPS URL, using bracket notation for IPv6."""
    if ":" in host and not host.startswith("["):
        return f"https://[{host}]:{port}"
    return f"https://{host}:{port}"
