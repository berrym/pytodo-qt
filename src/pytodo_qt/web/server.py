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

    def validate_pin(self, pin: str, client_ip: str = "") -> str | None:
        """Validate a pairing PIN. Returns auth token if valid, None otherwise.

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
        token = self.auth_token
        self.generate_pin()
        if client_ip:
            self._pin_attempts.pop(client_ip, None)
        return token

    def revoke_token(self) -> str:
        """Revoke the current auth token and generate a new one.

        All existing sessions will immediately fail with 401.
        Returns the new token.
        """
        import secrets

        new_token = secrets.token_urlsafe(32)
        if self._config:
            self._config.auth_token = new_token
        if self._config_manager:
            self._config_manager.save()
        self.generate_pin()
        logger.log.info("Auth token revoked — all sessions invalidated")
        return new_token

    @property
    def pairing_pin(self) -> str:
        """Return the current pairing PIN, regenerating if expired."""
        import time as _time

        if not self._pairing_pin or _time.time() > self._pairing_pin_expiry:
            self.generate_pin()
        return self._pairing_pin

    def _ensure_auth_token(self) -> str:
        """Generate an auth token if one doesn't exist, persist to config.

        Returns empty string if no config is available (e.g., tests),
        which disables auth via the middleware's empty-token check.
        """
        if not self._config:
            return ""  # No config = no auth (test mode)
        if self._config.auth_token:
            return self._config.auth_token
        import secrets

        token = secrets.token_urlsafe(32)
        self._config.auth_token = token
        if self._config_manager:
            self._config_manager.save()
        logger.log.info("Generated new web access token")
        return token

    def _create_ssl_context(self) -> ssl.SSLContext | None:
        """Create TLS context using a local CA and server certificate.

        On first run, generates a root CA key/cert (stored permanently) and a
        server cert signed by the CA with all detected local IPs in the SAN.
        If the local IP changes, the server cert is regenerated automatically.
        """
        if not self._config or not self._config.tls_enabled:
            return None
        if not self._config_manager:
            return None

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
            auth_token_key,
            config_manager_key,
            database_key,
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

        # Auth token + pairing PIN
        token = self._ensure_auth_token()
        app[auth_token_key] = token
        if token:
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

    @property
    def auth_token(self) -> str:
        """Return the current auth token."""
        if self._config and self._config.auth_token:
            return self._config.auth_token
        if self._app:
            from .api import auth_token_key

            return self._app.get(auth_token_key, "")
        return ""

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
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.log.info("Web server stopped")

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
