"""Tests for the Web UI PWA features (Phase 6).

Covers:
- Service worker serving from root scope
- Manifest serving and content
- Offline banner markup in index.html
- SW registration script in index.html
- Package-data includes .json files
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from pytodo_qt.core.models import Database
from pytodo_qt.web import server as web_server
from pytodo_qt.web.server import WebServer, static_asset_version

STATIC_DIR = Path(__file__).parent.parent / "src" / "pytodo_qt" / "web" / "static"


# ===========================================================================
# Static file existence tests
# ===========================================================================


class TestStaticFiles:
    def test_sw_js_exists(self):
        assert (STATIC_DIR / "sw.js").is_file()

    def test_manifest_json_exists(self):
        assert (STATIC_DIR / "manifest.json").is_file()

    def test_manifest_valid_json(self):
        data = json.loads((STATIC_DIR / "manifest.json").read_text())
        assert data["name"] == "PyTodo-Qt"
        assert data["display"] == "standalone"
        assert data["start_url"] == "/"
        assert len(data["icons"]) >= 1

    def test_manifest_has_required_fields(self):
        data = json.loads((STATIC_DIR / "manifest.json").read_text())
        for field in ("name", "short_name", "start_url", "display", "icons"):
            assert field in data, f"Missing required field: {field}"

    def test_sw_has_cache_version(self):
        content = (STATIC_DIR / "sw.js").read_text()
        assert "CACHE_VERSION" in content
        assert "STATIC_CACHE" in content

    def test_sw_has_install_handler(self):
        content = (STATIC_DIR / "sw.js").read_text()
        assert "install" in content
        assert "skipWaiting" in content

    def test_sw_has_activate_handler(self):
        content = (STATIC_DIR / "sw.js").read_text()
        assert "activate" in content
        assert "clients.claim" in content

    def test_sw_has_fetch_handler(self):
        content = (STATIC_DIR / "sw.js").read_text()
        assert "fetch" in content
        assert "cacheFirst" in content
        assert "networkFirst" in content

    def test_sw_caches_static_assets(self):
        content = (STATIC_DIR / "sw.js").read_text()
        assert "STATIC_ASSETS" in content
        assert "/static/style.css" in content
        assert "/static/app.js" in content


# ===========================================================================
# index.html PWA integration tests
# ===========================================================================


class TestIndexHtml:
    def _read_index(self) -> str:
        return (STATIC_DIR / "index.html").read_text()

    def test_manifest_link(self):
        html = self._read_index()
        assert 'rel="manifest"' in html
        assert "manifest.json" in html

    def test_apple_touch_icon(self):
        html = self._read_index()
        assert "apple-touch-icon" in html

    def test_sw_registration_script(self):
        html = self._read_index()
        assert "serviceWorker" in html
        assert 'register("/sw.js")' in html

    def test_offline_banner(self):
        html = self._read_index()
        assert 'id="offline-banner"' in html
        assert "hidden" in html  # initially hidden

    def test_theme_color_meta(self):
        html = self._read_index()
        assert 'name="theme-color"' in html


# ===========================================================================
# app.js offline queue tests
# ===========================================================================


class TestAppJsOfflineQueue:
    def _read_app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def test_offline_queue_key(self):
        js = self._read_app()
        assert "OFFLINE_QUEUE_KEY" in js
        assert "pytodo_offline_queue" in js

    def test_has_enqueue_function(self):
        js = self._read_app()
        assert "enqueueOfflineEdit" in js

    def test_has_replay_function(self):
        js = self._read_app()
        assert "replayOfflineQueue" in js

    def test_online_offline_listeners(self):
        js = self._read_app()
        assert '"online"' in js
        assert '"offline"' in js

    def test_offline_banner_ref(self):
        js = self._read_app()
        assert "offlineBanner" in js
        assert "offline-banner" in js

    def test_toggle_queues_when_offline(self):
        js = self._read_app()
        # onToggle should check isOnline
        assert "isOnline" in js

    def test_add_queues_when_offline(self):
        js = self._read_app()
        # The submit handler should enqueue when offline
        assert "enqueueOfflineEdit" in js


# ===========================================================================
# style.css offline banner tests
# ===========================================================================


class TestStyleCss:
    def _read_css(self) -> str:
        return (STATIC_DIR / "style.css").read_text()

    def test_offline_banner_styles(self):
        css = self._read_css()
        assert "#offline-banner" in css

    def test_hidden_class(self):
        css = self._read_css()
        assert ".hidden" in css


# ===========================================================================
# Server: service worker and manifest routes
# ===========================================================================


async def _make_client() -> TestClient:
    """Create an aiohttp test client."""
    db = Database()
    server = WebServer(db)
    app = server.create_app()
    return TestClient(TestServer(app))


class TestServiceWorkerRoute:
    @pytest.mark.asyncio
    async def test_sw_js_served_from_root(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/sw.js")
            assert resp.status == 200
            text = await resp.text()
            assert "CACHE_VERSION" in text

    @pytest.mark.asyncio
    async def test_sw_js_has_service_worker_allowed_header(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/sw.js")
            assert resp.status == 200
            assert resp.headers.get("Service-Worker-Allowed") == "/"

    @pytest.mark.asyncio
    async def test_sw_js_content_type(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/sw.js")
            assert resp.status == 200
            ct = resp.headers.get("Content-Type", "")
            assert "javascript" in ct or "text/" in ct


# ===========================================================================
# Version of the page's files
# ===========================================================================


@pytest.fixture
def static_copy(tmp_path, monkeypatch):
    """A copy of the static directory that the server serves from."""
    copy = tmp_path / "static"
    shutil.copytree(STATIC_DIR, copy)
    monkeypatch.setattr(web_server, "_STATIC_DIR", copy)
    return copy


class TestAssetVersion:
    def test_worker_script_has_one_placeholder(self):
        content = (STATIC_DIR / "sw.js").read_text()
        assert content.count("__ASSET_VERSION__") == 1

    def test_version_is_repeatable(self):
        assert static_asset_version() == static_asset_version()
        assert re.fullmatch(r"[0-9a-f]{16}", static_asset_version())

    @pytest.mark.parametrize("name", ["app.js", "style.css", "index.html", "sw.js", "icon-192.png"])
    def test_version_changes_when_a_file_changes(self, static_copy, name):
        before = static_asset_version()
        with (static_copy / name).open("ab") as handle:
            handle.write(b"\n")
        assert static_asset_version() != before

    def test_version_changes_when_a_file_is_added(self, static_copy):
        before = static_asset_version()
        (static_copy / "extra.js").write_text("// new")
        assert static_asset_version() != before

    def test_version_is_the_same_for_the_same_files(self, static_copy):
        """The version comes from names and contents, not from where the
        files are or when they were written."""
        original = static_asset_version()
        for path in static_copy.iterdir():
            path.touch()
        assert static_asset_version() == original

    def test_hidden_files_do_not_change_the_version(self, static_copy):
        before = static_asset_version()
        (static_copy / ".DS_Store").write_bytes(b"x")
        assert static_asset_version() == before

    @pytest.mark.asyncio
    async def test_served_worker_carries_the_version(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/sw.js")
            text = await resp.text()
            assert "__ASSET_VERSION__" not in text
            assert f'var CACHE_VERSION = "{static_asset_version()}";' in text

    @pytest.mark.asyncio
    async def test_served_worker_changes_when_a_file_changes(self, static_copy):
        client = await _make_client()
        async with client:
            before = await (await client.get("/sw.js")).text()
            with (static_copy / "style.css").open("ab") as handle:
                handle.write(b"\n")
            after = await (await client.get("/sw.js")).text()
            assert after != before


class TestPrecachedFiles:
    def test_every_precached_file_exists(self):
        """The worker's install fails as a whole when one file is missing."""
        content = (STATIC_DIR / "sw.js").read_text()
        block = re.search(r"var STATIC_ASSETS = \[(.*?)\];", content, re.DOTALL)
        assert block is not None
        urls = re.findall(r'"([^"]+)"', block.group(1))
        assert "/" in urls
        assert "/static/app.js" in urls
        for url in urls:
            if url == "/":
                continue
            assert url.startswith("/static/"), url
            assert (STATIC_DIR / url.removeprefix("/static/")).is_file(), url


class TestScriptSyntax:
    @pytest.mark.parametrize("name", ["sw.js", "app.js"])
    def test_script_parses(self, name):
        """A script that does not parse is dropped by the browser without
        a visible error; sw.js went unparsed for months that way."""
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node.js is not installed")
        result = subprocess.run(
            [node, "--check", str(STATIC_DIR / name)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


class TestManifestRoute:
    @pytest.mark.asyncio
    async def test_manifest_served_via_static(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/static/manifest.json")
            assert resp.status == 200
            data = await resp.json()
            assert data["name"] == "PyTodo-Qt"

    @pytest.mark.asyncio
    async def test_manifest_has_icons(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/static/manifest.json")
            data = await resp.json()
            assert len(data["icons"]) >= 1
            assert data["icons"][0]["sizes"] == "192x192"


class TestIndexRoute:
    @pytest.mark.asyncio
    async def test_index_has_manifest_link(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/")
            assert resp.status == 200
            text = await resp.text()
            assert "manifest.json" in text

    @pytest.mark.asyncio
    async def test_index_has_sw_registration(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/")
            text = await resp.text()
            assert "serviceWorker" in text

    @pytest.mark.asyncio
    async def test_index_has_offline_banner(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/")
            text = await resp.text()
            assert "offline-banner" in text


# ===========================================================================
# Package data tests
# ===========================================================================


class TestPackageData:
    def test_pyproject_includes_json(self):
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject_path.read_text()
        assert "*.json" in content
