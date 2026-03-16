"""Embedded aiohttp web server for mobile access.

The server runs as an asyncio task on the same qasync event loop as Qt,
so it can safely read the in-memory Database without locking.
"""

from __future__ import annotations

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

    def generate_pin(self) -> str:
        """Generate a new 6-digit pairing PIN, valid for 5 minutes."""
        import random
        import time as _time

        rng = random.SystemRandom()
        self._pairing_pin = str(rng.randint(100000, 999999))
        self._pairing_pin_expiry = _time.time() + 300  # 5 minutes
        return self._pairing_pin

    def validate_pin(self, pin: str) -> str | None:
        """Validate a pairing PIN. Returns auth token if valid, None otherwise.

        PIN is single-use — consumed on successful validation and regenerated.
        """
        import time as _time

        if not self._pairing_pin or not pin:
            return None
        if _time.time() > self._pairing_pin_expiry:
            self.generate_pin()  # Expired — regenerate
            return None
        if pin != self._pairing_pin:
            return None
        # Success — consume PIN and regenerate
        token = self.auth_token
        self.generate_pin()
        return token

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
        """Create TLS context with auto-generated self-signed certificate."""
        if not self._config or not self._config.tls_enabled:
            return None
        if not self._config_manager:
            return None

        cert_dir = self._config_manager.config_dir
        cert_path = cert_dir / "web_cert.pem"
        key_path = cert_dir / "web_key.pem"

        if not cert_path.exists() or not key_path.exists():
            self._generate_self_signed_cert(cert_path, key_path)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))
        return ctx

    @staticmethod
    def _generate_self_signed_cert(cert_path: Path, key_path: Path) -> None:
        """Generate a self-signed TLS certificate and key."""
        import datetime
        import ipaddress

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PyTodo-Qt")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.UTC))
            .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    ]
                ),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        logger.log.info("Generated self-signed TLS certificate")

    def create_app(self) -> web.Application:
        """Create and configure the aiohttp application."""
        from .api import (
            auth_middleware,
            auth_token_key,
            config_manager_key,
            database_key,
            save_callback_key,
            setup_routes,
            web_server_key,
            ws_clients_key,
        )

        app = web.Application(middlewares=[auth_middleware])
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
        if self._app:
            from .api import auth_token_key

            return self._app.get(auth_token_key, "")
        return ""

    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Start the web server."""
        app = self.create_app()
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
        import contextlib

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
