"""Embedded aiohttp web server for mobile access.

The server runs as an asyncio task on the same qasync event loop as Qt,
so it can safely read the in-memory Database without locking.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ssl
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from aiohttp import web

from ..core.logger import Logger
from ..core.private_files import make_private, write_private_file
from .device_store import PairedDevice, WebDeviceStore, parse_device_name
from .shared_port import SharedPortListener

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..core.config import ConfigManager, WebConfig
    from ..core.models import Database

logger = Logger(__name__)

# How long a server certificate serves, in days. Apple's systems refuse
# a server certificate that serves for more than 825 days, whoever
# issued it.
_CERTIFICATE_DAYS = 825
# A server certificate is replaced when it has fewer days left than this.
_RENEW_DAYS_BEFORE_END = 30
# How many names, and how many addresses, a server certificate lists at
# most.
_NAMES_KEPT = 16


def tls_context(
    address_cert: Path, address_key: Path, host_cert: Path, host_key: Path
) -> ssl.SSLContext:
    """The TLS context that presents the certificate for the host name
    to a browser that asks for the server by a name that certificate
    lists, and the certificate for addresses otherwise."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(address_cert), str(address_key))
    names = WebServer._certificate_names(host_cert) if host_key.exists() else None
    if names and names[0]:
        for_host_name = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        for_host_name.load_cert_chain(str(host_cert), str(host_key))
        host_names = {name.lower() for name in names[0]}

        def choose(
            ssl_object: ssl.SSLObject | ssl.SSLSocket,
            server_name: str | None,
            _context: ssl.SSLContext,
        ) -> None:
            # A browser names the server it asks for unless it asks by
            # address.
            if server_name and server_name.lower() in host_names:
                ssl_object.context = for_host_name

        context.sni_callback = choose
    return context


def _public_bytes(public_key: Any) -> bytes:
    """A public key in a form two of them can be compared in."""
    from cryptography.hazmat.primitives import serialization

    return public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _replace_file(path: Path, content: bytes) -> None:
    """Write a file whole or not at all: a write cut short leaves the
    file as it was."""
    import os

    temporary = path.with_name(path.name + ".new")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _ipv4_only(addresses: list[str]) -> list[str]:
    """The IPv4 addresses among addresses, in their order."""
    import ipaddress

    kept = []
    for address in addresses:
        try:
            if ipaddress.ip_address(address).version == 4:
                kept.append(address)
        except ValueError:
            continue
    return kept


_STATIC_DIR = Path(__file__).parent / "static"

# Files the SPA cannot function without; validated at app creation so a
# missing-asset failure surfaces as a clear startup error rather than as
# a stub HTML response or 404 mid-session.
_REQUIRED_STATIC_FILES = ("index.html", "sw.js")


# Stands in sw.js for the version of the page's files; replaced when the
# worker script is served.
_ASSET_VERSION_PLACEHOLDER = "__ASSET_VERSION__"

# The last version computed, with the names, sizes and modification times
# of the files it was computed from.
_asset_version_memo: tuple[tuple[tuple[str, int, int], ...], str] | None = None


def static_asset_version() -> str:
    """Return a short hash of the files in the static directory.

    The service worker stores the page's files under this version, so it
    has to change whenever any of them does. It is computed from their
    contents and recomputed only when a file's size or modification time
    has changed, which lets an edit made while the server runs take
    effect without a restart.
    """
    global _asset_version_memo
    files = sorted(
        path for path in _STATIC_DIR.rglob("*") if path.is_file() and not path.name.startswith(".")
    )
    stamp = tuple(
        (path.relative_to(_STATIC_DIR).as_posix(), stat.st_size, stat.st_mtime_ns)
        for path, stat in ((path, path.stat()) for path in files)
    )
    if _asset_version_memo is not None and _asset_version_memo[0] == stamp:
        return _asset_version_memo[1]

    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(_STATIC_DIR).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    version = digest.hexdigest()[:16]
    _asset_version_memo = (stamp, version)
    return version


def _verify_static_assets() -> None:
    """Raise RuntimeError when the bundled web/static directory or required files are absent.

    In a frozen build this typically means the build spec did not bundle
    src/pytodo_qt/web/static/* — the most likely cause of an SPA that
    fails to mount in an installed application.
    """
    missing: list[Path] = []
    if not _STATIC_DIR.is_dir():
        missing.append(_STATIC_DIR)
    else:
        missing.extend(
            _STATIC_DIR / name
            for name in _REQUIRED_STATIC_FILES
            if not (_STATIC_DIR / name).exists()
        )
    if not missing:
        return
    paths = ", ".join(str(p) for p in missing)
    msg = (
        f"Web UI static assets missing: {paths}. The web server cannot "
        "serve the SPA without these. In a frozen build, verify "
        "collect_data_files covers pytodo_qt.web/static in the "
        "PyInstaller spec datas list."
    )
    raise RuntimeError(msg)


def _abort_connection(handler: Any, transport: asyncio.Transport) -> None:
    """Takes the place of ``web.Server.connection_made`` on a server that
    is stopping or has stopped: the connection is closed at once, and is
    not counted among the server's connections."""
    transport.abort()


class WebServer:
    """Embedded web server providing a REST API and mobile-friendly SPA."""

    def __init__(
        self,
        database: Database,
        save_callback: Callable[[], None] | None = None,
        config: WebConfig | None = None,
        config_manager: ConfigManager | None = None,
        main_window: Any | None = None,
    ) -> None:
        self._database = database
        self._save_callback = save_callback
        self._config = config
        self._config_manager = config_manager
        self._main_window = main_window
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        # With TLS: the listener that serves HTTPS and redirects plain
        # HTTP on the same port (#82).
        self._listener: SharedPortListener | None = None
        self._app: web.Application | None = None
        self._pairing_pin: str = ""
        self._pairing_pin_expiry: float = 0
        self._pin_attempts: dict[str, tuple[int, float]] = {}  # ip → (count, lockout_until)
        self._device_store: WebDeviceStore | None = None
        self._closing_sockets: set[asyncio.Task[None]] = set()

    def generate_pin(self) -> str:
        """Generate a new 6-digit pairing PIN, valid for 5 minutes."""
        import random
        import time as _time

        rng = random.SystemRandom()
        self._pairing_pin = str(rng.randint(100000, 999999))
        self._pairing_pin_expiry = _time.time() + 300  # 5 minutes
        return self._pairing_pin

    def check_pin_rate_limit(self, client_ip: str) -> bool:
        """Check if a client IP is rate-limited for PIN attempts.

        Returns True if the client is locked out.
        """
        import time as _time

        entry = self._pin_attempts.get(client_ip)
        if entry is None:
            return False
        count, lockout_until = entry
        if _time.time() < lockout_until:
            return True  # Still locked out
        if count >= 5 and _time.time() >= lockout_until:
            # Lockout expired — reset
            del self._pin_attempts[client_ip]
        return False

    def record_pin_failure(self, client_ip: str) -> None:
        """Record a failed PIN attempt. Lockout after 5 failures."""
        import time as _time

        entry = self._pin_attempts.get(client_ip)
        count = (entry[0] if entry else 0) + 1
        lockout_until = _time.time() + 60 if count >= 5 else 0
        self._pin_attempts[client_ip] = (count, lockout_until)
        if count >= 5:
            logger.log.warning("PIN rate limit: %s locked out for 60s", client_ip)

    def validate_pin(
        self,
        pin: str,
        client_ip: str = "",
        user_agent: str = "",
        pairing_method: str = "quick",
        address: str = "",
    ) -> PairedDevice | None:
        """Validate a pairing PIN. Returns a new PairedDevice if valid.

        address is the address the device's browser named the server by;
        it is kept with the device, to send the device back to.

        On success, creates a per-device token and stores the device record.
        PIN is single-use — consumed on successful validation and regenerated.
        Rate-limited to 5 attempts per IP, then 60-second lockout.
        """
        import time as _time

        if client_ip and self.check_pin_rate_limit(client_ip):
            return None
        if not self._pairing_pin or not pin:
            if client_ip:
                self.record_pin_failure(client_ip)
            return None
        if _time.time() > self._pairing_pin_expiry:
            self.generate_pin()  # Expired — regenerate
            if client_ip:
                self.record_pin_failure(client_ip)
            return None
        if pin != self._pairing_pin:
            if client_ip:
                self.record_pin_failure(client_ip)
            return None
        # Success — consume PIN, regenerate, clear rate limit
        self.generate_pin()
        if client_ip:
            self._pin_attempts.pop(client_ip, None)

        device_name = parse_device_name(user_agent)
        ca_gen = self._config.ca_generation if self._config else 0

        if self._device_store:
            device = self._device_store.add_device(
                device_name=device_name,
                user_agent=user_agent,
                pairing_method=pairing_method,
                ca_generation=ca_gen,
                address=address,
            )
        else:
            # Test mode — return synthetic device without persistence
            device = PairedDevice(
                device_name=device_name,
                user_agent=user_agent,
                pairing_method=pairing_method,
                ca_generation=ca_gen,
                address=address,
            )
        logger.log.info("Device paired: %s (%s) UA: %s", device_name, pairing_method, user_agent)
        return device

    def revoke_all_devices(self) -> int:
        """Revoke all paired device tokens.

        All existing sessions will immediately fail with 401.
        Returns the number of devices revoked.
        """
        count = 0
        if self._device_store:
            count = self._device_store.remove_all_devices()
            self._close_device_sockets(None)
        self.generate_pin()
        logger.log.info("All device tokens revoked — %d devices removed", count)
        return count

    def remove_device(self, device_id: str) -> bool:
        """Remove a single paired device. Returns True if found and removed."""
        if self._device_store and self._device_store.remove_device(device_id):
            self._close_device_sockets(device_id)
            return True
        return False

    def _close_device_sockets(self, device_id: str | None) -> None:
        """Close the WebSockets of a removed device; of every device for None.

        Safe to call from sync Qt code: the closing is scheduled on the
        running event loop. Without one there is no WebSocket to close.
        """
        if not self._app:
            return
        from .api import close_device_sockets, ws_clients_key

        clients = self._app.get(ws_clients_key)
        if not clients:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        closing = loop.create_task(close_device_sockets(clients, device_id))
        # The loop keeps no reference of its own to a task.
        self._closing_sockets.add(closing)
        closing.add_done_callback(self._closing_sockets.discard)

    def rename_device(self, device_id: str, new_name: str) -> bool:
        """Rename a paired device. Returns True if the device was updated.

        Thin passthrough to the device store, matching the shape of
        remove_device so the wizard and web API handler can call
        through a single entry point.
        """
        if self._device_store:
            return self._device_store.rename_device(device_id, new_name)
        return False

    def get_paired_devices(self) -> list[PairedDevice]:
        """Return all paired devices."""
        if self._device_store:
            return self._device_store.get_all_devices()
        return []

    @property
    def pairing_pin(self) -> str:
        """Return the current pairing PIN, regenerating if expired."""
        import time as _time

        if not self._pairing_pin or _time.time() > self._pairing_pin_expiry:
            self.generate_pin()
        return self._pairing_pin

    @property
    def device_store(self) -> WebDeviceStore | None:
        """Return the device store (for middleware and testing)."""
        return self._device_store

    def _create_ssl_context(self) -> ssl.SSLContext | None:
        """Create the TLS context from a local CA and two server certificates.

        TLS is always enabled when a config_manager is available — there is
        no opt-out. On first run a root CA key and certificate are generated
        and kept.

        A browser that was let through by hand ("Quick Connect") accepted
        one certificate for one address, and is turned away by any other
        certificate until that is accepted in turn, which the page cannot
        bring about. A certificate is therefore replaced only when it has
        to be, and one certificate is kept apart for the host name:

        - The certificate for the host name is presented to a browser
          that asks for the server by that name. It does not list
          addresses, so no change of address touches it.
        - The certificate for addresses is presented otherwise. It lists
          the IPv4 addresses the server is reached at and keeps those it
          has listed before, so that going back to an earlier network
          does not replace it. No IPv6 address is listed: the server does
          not listen on one, and the one the system prefers is temporary
          and is replaced about daily.
        """
        if not self._config_manager:
            return None  # Test mode — no certs possible

        return tls_context(*self._ensure_certificates())

    def _ensure_certificates(self) -> tuple[Path, Path, Path, Path]:
        """Create or replace what is missing or no longer usable among the
        CA and the two server certificates, and return the paths of the
        certificate for addresses, its key, the certificate for the host
        name and its key."""
        assert self._config_manager is not None
        from ..core.network import get_all_local_addresses, get_local_hostname

        cert_dir = self._config_manager.config_dir
        ca_cert_path = cert_dir / "ca_cert.pem"
        ca_key_path = cert_dir / "ca_key.pem"
        address_cert = cert_dir / "web_cert.pem"
        address_key = cert_dir / "web_key.pem"
        host_cert = cert_dir / "web_host_cert.pem"
        host_key = cert_dir / "web_host_key.pem"

        if not ca_cert_path.exists() or not ca_key_path.exists():
            self._generate_ca(ca_cert_path, ca_key_path)
        # Keys written by an earlier version are readable by every
        # account on the machine.
        for key_path in (ca_key_path, address_key, host_key):
            make_private(key_path)

        host_name = get_local_hostname()
        dns_names = ["localhost"] + ([host_name] if host_name else [])
        addresses = ["127.0.0.1"] + [
            address for address in get_all_local_addresses()[0] if address != "127.0.0.1"
        ]

        # The host name's certificate is looked at whenever there is one,
        # with or without a host name at this start: it is presented for
        # the names it lists either way.
        host_names = [host_name] if host_name else []
        has_host_files = host_cert.exists() or host_key.exists()

        def faults() -> tuple[str | None, str | None]:
            for_host = (
                self._certificate_fault(host_cert, host_key, ca_cert_path, host_names, [])
                if host_name or has_host_files
                else None
            )
            for_addresses = self._certificate_fault(
                address_cert, address_key, ca_cert_path, [], addresses
            )
            return for_host, for_addresses

        host_fault, address_fault = faults()

        # A version before this one had a single certificate. Browsers
        # have accepted it for the host name, so it goes on being
        # presented for that, whatever becomes of it for addresses below.
        # The key is written first: a copy cut short leaves no
        # certificate, and is made again at the next start.
        if (
            host_fault
            and host_name
            and not host_cert.exists()
            and not self._certificate_fault(address_cert, address_key, ca_cert_path, host_names, [])
        ):
            write_private_file(host_key, address_key.read_bytes())
            _replace_file(host_cert, address_cert.read_bytes())
            host_fault = None

        # A CA whose key is not its certificate's cannot issue anything
        # that passes for its own: each start would replace the server
        # certificates again. It is found out here, when one is due, and
        # not before: until then what it issued earlier still serves.
        if (host_fault or address_fault) and not self._ca_fits(ca_cert_path, ca_key_path):
            logger.log.warning(
                "The certificate authority's key is not its certificate's: making a new one"
            )
            self._new_certificate_authority(ca_cert_path, ca_key_path)
            host_fault, address_fault = faults()

        if host_fault:
            before = self._certificate_names(host_cert) or ([], [])
            logger.log.info("Server certificate for the host name replaced: %s", host_fault)
            self._generate_server_cert(
                ca_cert_path,
                ca_key_path,
                host_cert,
                host_key,
                [],
                self._names_to_keep(before[0], dns_names),
            )
        if address_fault:
            before = self._certificate_names(address_cert) or ([], [])
            logger.log.info("Server certificate for addresses replaced: %s", address_fault)
            self._generate_server_cert(
                ca_cert_path,
                ca_key_path,
                address_cert,
                address_key,
                self._names_to_keep(_ipv4_only(before[1]), addresses),
                self._names_to_keep(before[0], dns_names),
            )
        return address_cert, address_key, host_cert, host_key

    @property
    def ca_cert_path(self) -> Path | None:
        """Return the path to the CA certificate for device installation."""
        if not self._config_manager:
            return None
        p = self._config_manager.config_dir / "ca_cert.pem"
        return p if p.exists() else None

    @staticmethod
    def _ca_fits(ca_cert_path: Path, ca_key_path: Path) -> bool:
        """Whether the CA's key is the one its certificate was made for."""
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        try:
            key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
            cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
            return _public_bytes(key.public_key()) == _public_bytes(cert.public_key())
        except Exception:
            return False

    def _new_certificate_authority(self, ca_cert_path: Path, ca_key_path: Path) -> None:
        """Make a new CA, and count it: devices that installed the one
        before are shown as needing the new one."""
        self._generate_ca(ca_cert_path, ca_key_path)
        if self._config:
            self._config.ca_generation += 1
        if self._config_manager:
            self._config_manager.save()

    @staticmethod
    def _certificate_names(cert_path: Path) -> tuple[list[str], list[str]] | None:
        """The DNS names and the addresses a certificate lists, or None
        for a certificate that cannot be read."""
        from cryptography import x509

        try:
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        except Exception:
            return None
        return (
            list(san.get_values_for_type(x509.DNSName)),
            [str(address) for address in san.get_values_for_type(x509.IPAddress)],
        )

    @staticmethod
    def _certificate_fault(
        cert_path: Path,
        key_path: Path,
        ca_cert_path: Path,
        dns_names: list[str],
        addresses: list[str],
    ) -> str | None:
        """Why a server certificate has to be replaced, or None when it
        serves: it is there with the key it was made for, was issued by
        the CA in use, has begun to serve and has more than
        _RENEW_DAYS_BEFORE_END days left, and lists every name and
        address given."""
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        if not cert_path.exists() or not key_path.exists():
            return "there is none"
        try:
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        except Exception:
            return "it cannot be read"
        # A certificate beside another's key, or beside a damaged one,
        # stops the server at every start.
        try:
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            if _public_bytes(key.public_key()) != _public_bytes(cert.public_key()):
                return "its key is another certificate's"
        except Exception:
            return "its key cannot be read"
        try:
            cert.verify_directly_issued_by(
                x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
            )
        except Exception:
            return "it was issued by another certificate authority"
        ends = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(
            tzinfo=datetime.UTC
        )
        now = datetime.datetime.now(datetime.UTC)
        begins = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before.replace(
            tzinfo=datetime.UTC
        )
        if begins > now:
            # Made while the machine's clock was ahead.
            return "it does not serve yet"
        left = ends - now
        if left < datetime.timedelta(days=_RENEW_DAYS_BEFORE_END):
            return f"it ends in {max(left.days, 0)} days"
        listed_names = {name.lower() for name in san.get_values_for_type(x509.DNSName)}
        listed_addresses = {str(address) for address in san.get_values_for_type(x509.IPAddress)}
        for name in dns_names:
            if name.lower() not in listed_names:
                return "the host name is new to it"
        for address in addresses:
            if address not in listed_addresses:
                return "an address is new to it"
        return None

    @staticmethod
    def _names_to_keep(before: list[str], now: list[str]) -> list[str]:
        """The names or addresses for a new certificate: those in use
        now, and before them those the certificate it replaces listed,
        the oldest dropped beyond _NAMES_KEPT. A browser that comes back
        at an earlier name then meets a certificate that still lists it."""
        current = {name.lower() for name in now}
        earlier = [name for name in before if name.lower() not in current]
        room = max(_NAMES_KEPT - len(now), 0)
        return (earlier[-room:] if room else []) + list(now)

    @staticmethod
    def _generate_ca(ca_cert_path: Path, ca_key_path: Path) -> None:
        """Generate a root Certificate Authority key and certificate."""
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "PyTodo-Qt Local CA"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PyTodo-Qt"),
            ]
        )
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.UTC))
            .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_cert_sign=True,
                    crl_sign=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(key, hashes.SHA256())
        )
        write_private_file(
            ca_key_path,
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ),
        )
        ca_cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        logger.log.info("Generated local CA certificate (10-year validity)")

    @staticmethod
    def _generate_server_cert(
        ca_cert_path: Path,
        ca_key_path: Path,
        srv_cert_path: Path,
        srv_key_path: Path,
        local_ips: list[str],
        dns_names: list[str] | None = None,
        days: int = _CERTIFICATE_DAYS,
    ) -> None:
        """Generate a server certificate signed by the local CA.

        It lists dns_names, by default "localhost" and the machine's
        host name, and the addresses in local_ips. It serves for days,
        counted from a day ago: a device whose clock is behind this
        machine's, or this machine after its own clock was set back by
        some hours, would otherwise meet a certificate that does not
        serve yet.
        """
        import datetime
        import ipaddress as _ipa

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.asymmetric.types import (
            CertificateIssuerPrivateKeyTypes,
        )
        from cryptography.x509.oid import NameOID

        ca_key = cast(
            CertificateIssuerPrivateKeyTypes,
            serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None),
        )
        ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())

        srv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        if dns_names is None:
            from ..core.network import get_local_hostname

            # The .local host name, for mDNS: it outlasts a change of address.
            local_hostname = get_local_hostname()
            dns_names = ["localhost"] + ([local_hostname] if local_hostname else [])

        san_entries: list[x509.GeneralName] = [x509.DNSName(name) for name in dns_names]
        begins = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
        for ip_str in local_ips:
            with contextlib.suppress(ValueError):
                san_entries.append(x509.IPAddress(_ipa.IPv4Address(ip_str)))
            with contextlib.suppress(ValueError):
                san_entries.append(x509.IPAddress(_ipa.IPv6Address(ip_str)))

        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PyTodo-Qt")]))
            .issuer_name(ca_cert.subject)
            .public_key(srv_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(begins)
            .not_valid_after(begins + datetime.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        write_private_file(
            srv_key_path,
            srv_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ),
        )
        _replace_file(srv_cert_path, cert.public_bytes(serialization.Encoding.PEM))
        logger.log.info(
            "Generated server certificate (SAN: %s)", ", ".join([*dns_names, *local_ips])
        )

    def create_app(self) -> web.Application:
        """Create and configure the aiohttp application."""
        _verify_static_assets()
        from .api import (
            auth_middleware,
            config_manager_key,
            database_key,
            device_store_key,
            main_window_key,
            revalidation_middleware,
            save_callback_key,
            security_headers_middleware,
            setup_routes,
            web_server_key,
            ws_clients_key,
        )

        app = web.Application(
            middlewares=[security_headers_middleware, revalidation_middleware, auth_middleware]
        )
        app[database_key] = self._database
        app[ws_clients_key] = set()
        app[web_server_key] = self
        if self._save_callback:
            app[save_callback_key] = self._save_callback
        if self._config_manager:
            app[config_manager_key] = self._config_manager
        if self._main_window:
            app[main_window_key] = self._main_window

        # Per-device token store + pairing PIN
        # Only enable auth when both config AND config_manager are present.
        # config_manager alone (e.g., sort persistence) does not enable auth.
        if self._config and self._config_manager:
            self._device_store = WebDeviceStore(self._config_manager.config_dir / "web_devices.db")
            self._device_store.open()
            app[device_store_key] = self._device_store
            self.generate_pin()

            # Auto-cleanup inactive devices on startup
            inactivity_days = self._config.device_inactivity_days
            if inactivity_days > 0:
                max_age_ms = inactivity_days * 86_400_000
                removed = self._device_store.remove_inactive_devices(max_age_ms)
                if removed:
                    logger.log.info(
                        "Removed %d inactive device(s) (>%d days)", removed, inactivity_days
                    )

        # API routes
        setup_routes(app)

        # Static file serving
        app.router.add_get("/", self._serve_index)
        app.router.add_get("/sw.js", self._serve_sw)
        app.router.add_static("/static", _STATIC_DIR)

        self._app = app
        return app

    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Start the web server."""
        app = self._app if self._app is not None else self.create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        ssl_ctx = self._create_ssl_context()
        server = self._runner.server
        if ssl_ctx is not None and server is not None:
            # An address typed without https:// reaches this port as plain
            # HTTP: it is sent on to the HTTPS address, where TCPSite gave
            # it a closed connection and no word.
            self._listener = SharedPortListener(server, ssl_ctx, host, port)
            await self._listener.start()
        else:
            self._site = web.TCPSite(self._runner, host, port, ssl_context=ssl_ctx)
            await self._site.start()
        scheme = "https" if ssl_ctx else "http"
        logger.log.info("Web server started on %s://%s:%d", scheme, host, port)

    async def stop(self) -> None:
        """Stop the web server.

        When this returns no connection to the server is open or is
        served, whenever it was made. The connections are closed first
        and the device store last: a request under way while the server
        stops is answered with the store open.
        """
        if self._runner:
            # The runner closes the connections aiohttp knows of, and it
            # knows a connection once its TLS handshake is done. One that
            # was accepted before the stop and ends its handshake after
            # it was never closed: it went on being served, by an
            # application whose device store was closed, for as long as
            # it stayed open. Every connection is reported to the server
            # object when its handshake is done
            # (RequestHandler.connection_made); from here on that report
            # aborts the connection.
            stopped = self._runner.server
            if stopped is not None:
                # An attribute of this one object: the next start makes
                # a server object of its own.
                stopped.connection_made = _abort_connection
            # No connection is taken from here on, and none that is still
            # being looked at is handed on.
            if self._listener is not None:
                await self._listener.close()
                self._listener = None
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.log.info("Web server stopped")
        if self._device_store:
            self._device_store.close()
            self._device_store = None

    def regenerate_certs(self) -> bool:
        """Regenerate CA and server certificates with fresh keys.

        Returns True if successful, False if no config_manager available.
        """
        if not self._config_manager:
            return False
        cert_dir = self._config_manager.config_dir
        # Counted, so that the wizard can tell the devices that have the
        # CA before this one.
        self._new_certificate_authority(cert_dir / "ca_cert.pem", cert_dir / "ca_key.pem")
        # No server certificate was issued by the new CA: each is
        # replaced.
        self._ensure_certificates()
        logger.log.info("Certificates regenerated — devices must reinstall CA cert")
        return True

    def notify_clients(self) -> None:
        """Broadcast a refresh event to all connected WebSocket clients.

        Safe to call from sync Qt code — schedules the async broadcast
        on the running event loop.
        """
        if not self._app:
            return
        from .api import _broadcast_refresh, ws_clients_key

        clients = self._app.get(ws_clients_key)
        if not clients:
            return
        import asyncio

        with contextlib.suppress(RuntimeError):
            asyncio.ensure_future(_broadcast_refresh(clients))

    @property
    def app(self) -> web.Application | None:
        """Return the aiohttp application (for testing)."""
        return self._app

    async def _serve_index(self, request: web.Request) -> web.StreamResponse:
        """Serve index.html for the root URL, carrying the version of the
        page's files it belongs to.

        The page reads the version from itself. A page loaded from the
        service worker's store, with the server down, then knows which
        version it is, and can tell when the server it connects to
        serves another.
        """
        page = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return web.Response(
            text=page.replace(_ASSET_VERSION_PLACEHOLDER, static_asset_version()),
            content_type="text/html",
        )

    async def _serve_sw(self, request: web.Request) -> web.StreamResponse:
        """Serve the service worker from the root scope, carrying the
        version of the page's files it is to store."""
        script = (_STATIC_DIR / "sw.js").read_text(encoding="utf-8")
        return web.Response(
            text=script.replace(_ASSET_VERSION_PLACEHOLDER, static_asset_version()),
            content_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )
