"""Embedded aiohttp web server for mobile access.

The server runs as an asyncio task on the same qasync event loop as Qt,
so it can safely read the in-memory Database without locking.
"""

from __future__ import annotations

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

    def create_app(self) -> web.Application:
        """Create and configure the aiohttp application."""
        from .api import (
            config_manager_key,
            database_key,
            save_callback_key,
            setup_routes,
            ws_clients_key,
        )

        app = web.Application()
        app[database_key] = self._database
        app[ws_clients_key] = set()
        if self._save_callback:
            app[save_callback_key] = self._save_callback
        if self._config_manager:
            app[config_manager_key] = self._config_manager

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
        app = self.create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()
        logger.log.info("Web server started on http://%s:%d", host, port)

    async def stop(self) -> None:
        """Stop the web server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.log.info("Web server stopped")

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
