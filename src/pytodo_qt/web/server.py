"""Embedded aiohttp web server for mobile access.

The server runs as an asyncio task on the same qasync event loop as Qt,
so it can safely read the in-memory Database without locking.
"""

from __future__ import annotations

import contextlib
import ssl
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from ..core.logger import Logger
from .device_store import PairedDevice, WebDeviceStore, parse_device_name

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..core.config import ConfigManager, WebConfig
    from ..core.models import Database

logger = Logger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


class WebServer:
    """Embedded web server providing a REST API and mobile-friendly SPA."""

    def __init__(
        self,
        database: Database,
        save_callback: Callable[[], None] | None = None,
        config: WebConfig | None = None,
        config_manager: ConfigManager | None = None,
    ) -> None:
        self._database = database
        self._save_callback = save_callback
        self._config = config
        self._config_manager = config_manager
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._app: web.Application | None = None
        self._pairing_pin: str = ""
        self._pairing_pin_expiry: float = 0
        self._pin_attempts: dict[str, tuple[int, float]] = {}  # ip → (count, lockout_until)
        self._device_store: WebDeviceStore | None = None

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
    ) -> PairedDevice | None:
        """Validate a pairing PIN. Returns a new PairedDevice if valid.

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
            )
        else:
            # Test mode — return synthetic device without persistence
            device = PairedDevice(
                device_name=device_name,
                user_agent=user_agent,
                pairing_method=pairing_method,
                ca_generation=ca_gen,
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
        self.generate_pin()
        logger.log.info("All device tokens revoked — %d devices removed", count)
        return count

    def remove_device(self, device_id: str) -> bool:
        """Remove a single paired device. Returns True if found and removed."""
        if self._device_store:
            return self._device_store.remove_device(device_id)
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
        """Create TLS context using a local CA and server certificate.

        TLS is always enabled when a config_manager is available — there is
        no opt-out. On first run, generates a root CA key/cert (stored
        permanently) and a server cert signed by the CA with all detected
        local IPs in the SAN. If the local IP changes, the server cert is
        regenerated automatically.
        """
        if not self._config_manager:
            return None  # Test mode — no certs possible

        cert_dir = self._config_manager.config_dir
        ca_cert_path = cert_dir / "ca_cert.pem"
        ca_key_path = cert_dir / "ca_key.pem"
        srv_cert_path = cert_dir / "web_cert.pem"
        srv_key_path = cert_dir / "web_key.pem"

        # Ensure CA exists
        if not ca_cert_path.exists() or not ca_key_path.exists():
            self._generate_ca(ca_cert_path, ca_key_path)

        # Ensure server cert exists and covers current IPs
        local_ips = self._get_all_local_ips()
        if not srv_cert_path.exists() or not srv_key_path.exists():
            self._generate_server_cert(
                ca_cert_path, ca_key_path, srv_cert_path, srv_key_path, local_ips
            )
        elif not self._cert_covers_ips(srv_cert_path, local_ips):
            logger.log.info("Local IP changed — regenerating server certificate")
            self._generate_server_cert(
                ca_cert_path, ca_key_path, srv_cert_path, srv_key_path, local_ips
            )

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(srv_cert_path), str(srv_key_path))
        return ctx

    @property
    def ca_cert_path(self) -> Path | None:
        """Return the path to the CA certificate for device installation."""
        if not self._config_manager:
            return None
        p = self._config_manager.config_dir / "ca_cert.pem"
        return p if p.exists() else None

    @staticmethod
    def _get_all_local_ips() -> list[str]:
        """Detect all local IP addresses for the server certificate SAN."""
        import socket

        ips: set[str] = {"127.0.0.1"}
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                addr = info[4][0]
                if addr and addr != "0.0.0.0":
                    ips.add(addr)
        except OSError:
            pass
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                addr = s.getsockname()[0]
                if addr and addr != "0.0.0.0":
                    ips.add(addr)
        except OSError:
            pass
        return sorted(ips)

    @staticmethod
    def _cert_covers_ips(cert_path: Path, required_ips: list[str]) -> bool:
        """Check if an existing certificate's SAN covers all required IPs."""

        from cryptography import x509

        try:
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            cert_ips = {str(ip) for ip in san.value.get_values_for_type(x509.IPAddress)}
            return all(ip in cert_ips for ip in required_ips)
        except Exception:
            return False

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
        ca_key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
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
    ) -> None:
        """Generate a server certificate signed by the local CA."""
        import datetime
        import ipaddress as _ipa

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())

        srv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        san_entries: list[x509.GeneralName] = [x509.DNSName("localhost")]
        for ip_str in local_ips:
            with contextlib.suppress(ValueError):
                san_entries.append(x509.IPAddress(_ipa.IPv4Address(ip_str)))

        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PyTodo-Qt")]))
            .issuer_name(ca_cert.subject)
            .public_key(srv_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.UTC))
            .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        srv_key_path.write_bytes(
            srv_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
        srv_cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        ip_list = ", ".join(local_ips)
        logger.log.info("Generated server certificate (SAN: localhost, %s)", ip_list)

    def create_app(self) -> web.Application:
        """Create and configure the aiohttp application."""
        from .api import (
            auth_middleware,
            config_manager_key,
            database_key,
            device_store_key,
            save_callback_key,
            security_headers_middleware,
            setup_routes,
            web_server_key,
            ws_clients_key,
        )

        app = web.Application(middlewares=[security_headers_middleware, auth_middleware])
        app[database_key] = self._database
        app[ws_clients_key] = set()
        app[web_server_key] = self
        if self._save_callback:
            app[save_callback_key] = self._save_callback
        if self._config_manager:
            app[config_manager_key] = self._config_manager

        # Per-device token store + pairing PIN
        # Only enable auth when both config AND config_manager are present.
        # config_manager alone (e.g., sort persistence) does not enable auth.
        if self._config and self._config_manager:
            self._device_store = WebDeviceStore(self._config_manager.config_dir / "web_devices.db")
            self._device_store.open()
            app[device_store_key] = self._device_store
            self.generate_pin()

        # API routes
        setup_routes(app)

        # Static file serving
        app.router.add_get("/", self._serve_index)
        app.router.add_get("/sw.js", self._serve_sw)
        if _STATIC_DIR.is_dir():
            app.router.add_static("/static", _STATIC_DIR)

        self._app = app
        return app

    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Start the web server."""
        app = self._app if self._app is not None else self.create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        ssl_ctx = self._create_ssl_context()
        self._site = web.TCPSite(self._runner, host, port, ssl_context=ssl_ctx)
        await self._site.start()
        scheme = "https" if ssl_ctx else "http"
        logger.log.info("Web server started on %s://%s:%d", scheme, host, port)

    async def stop(self) -> None:
        """Stop the web server."""
        if self._device_store:
            self._device_store.close()
            self._device_store = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.log.info("Web server stopped")

    def regenerate_certs(self) -> bool:
        """Regenerate CA and server certificates with fresh keys.

        Returns True if successful, False if no config_manager available.
        """
        if not self._config_manager:
            return False
        cert_dir = self._config_manager.config_dir
        self._generate_ca(cert_dir / "ca_cert.pem", cert_dir / "ca_key.pem")
        local_ips = self._get_all_local_ips()
        self._generate_server_cert(
            cert_dir / "ca_cert.pem",
            cert_dir / "ca_key.pem",
            cert_dir / "web_cert.pem",
            cert_dir / "web_key.pem",
            local_ips,
        )
        # Increment CA generation so wizard can detect stale devices
        if self._config:
            self._config.ca_generation += 1
        if self._config_manager:
            self._config_manager.save()
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
        """Serve index.html for the root URL."""
        index_path = _STATIC_DIR / "index.html"
        if index_path.exists():
            return web.FileResponse(index_path)
        return web.Response(text="PyTodo-Qt Web UI", content_type="text/html")

    async def _serve_sw(self, request: web.Request) -> web.StreamResponse:
        """Serve service worker from root scope."""
        sw_path = _STATIC_DIR / "sw.js"
        if sw_path.exists():
            return web.FileResponse(
                sw_path,
                headers={"Service-Worker-Allowed": "/"},
            )
        return web.Response(status=404)
