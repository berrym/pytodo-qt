"""Tests for the Web UI PWA features (Phase 6).

Covers:
- Service worker serving from root scope
- Manifest serving and content
- Offline banner markup in index.html
- SW registration from app.js, and no inline script in index.html
- The version of the page's files carried by the served worker
- Revalidation of the page's files
- The rules of the offline queue, run under Node
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

    def test_no_inline_script(self):
        """The page's security policy allows scripts from its own origin
        only: an inline script is blocked, without a visible error."""
        scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", self._read_index(), re.DOTALL)
        assert scripts
        for attributes, body in scripts:
            assert "src=" in attributes
            assert body.strip() == ""

    def test_no_inline_event_handlers(self):
        assert not re.search(r"\son[a-z]+\s*=", self._read_index())

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


class TestAppJsServiceWorker:
    def _read_app_js(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def test_worker_is_registered_from_the_script(self):
        assert 'register("/sw.js")' in self._read_app_js()

    def test_worker_is_registered_over_https_only(self):
        js = self._read_app_js()
        guard = js.index('navigator.serviceWorker && location.protocol === "https:"')
        assert guard < js.index('register("/sw.js")')

    def test_page_reloads_for_a_new_worker(self):
        js = self._read_app_js()
        assert '"controllerchange"' in js
        assert "reloadForUpdateWhenIdle" in js


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

    def test_every_file_the_page_loads_is_precached(self):
        """A script or stylesheet the page loads and the worker does not
        store is missing when the page opens without the server."""
        content = (STATIC_DIR / "sw.js").read_text()
        block = re.search(r"var STATIC_ASSETS = \[(.*?)\];", content, re.DOTALL)
        assert block is not None
        urls = re.findall(r'"([^"]+)"', block.group(1))
        html = (STATIC_DIR / "index.html").read_text()
        loaded = re.findall(r'<script[^>]*\ssrc="([^"]+)"', html)
        loaded += re.findall(r'<link[^>]*rel="(?:stylesheet|manifest)"[^>]*href="([^"]+)"', html)
        assert "/static/app.js" in loaded
        assert "/static/style.css" in loaded
        for url in loaded:
            assert url in urls, url


class TestScriptSyntax:
    @pytest.mark.parametrize("name", ["sw.js", "app.js", "offline-queue.js"])
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


class TestOfflineQueueRules:
    """The rules of the offline queue are plain JavaScript with no page
    behind them; their tests are in tests/js and run under Node."""

    def test_rules(self):
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node.js is not installed")
        result = subprocess.run(
            [node, "--test", str(Path(__file__).parent / "js" / "offline_queue.test.js")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_rules_load_before_the_page_script(self):
        """app.js reads the rules when it starts."""
        html = (STATIC_DIR / "index.html").read_text()
        scripts = re.findall(r'<script[^>]*\ssrc="([^"]+)"', html)
        assert scripts.index("/static/offline-queue.js") < scripts.index("/static/app.js")

    def test_page_script_uses_the_rules(self):
        js = (STATIC_DIR / "app.js").read_text()
        assert "window.PytodoOfflineQueue" in js
        # One rule for what a reply means, at first sending and at replay.
        assert js.count("QueueRules.replyOutcome(") == 2

    def test_one_replay_at_a_time(self):
        js = (STATIC_DIR / "app.js").read_text()
        assert "if (replayRunning || getOfflineQueue().length === 0) return;" in js

    def test_changes_are_queued_in_one_place(self):
        """Every change that can be queued goes through sendOrQueue, so
        that a failed request and an offline device are handled alike."""
        js = (STATIC_DIR / "app.js").read_text()
        assert js.count("await sendOrQueue(") == 6
        # enqueueOfflineEdit: its definition and its one caller.
        assert js.count("enqueueOfflineEdit(") == 2


class TestQueuedChangesShown:
    """The page draws what the server last sent with the queued changes
    applied, and marks the tasks that have one."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def test_list_and_board_are_drawn_through_the_queue(self):
        js = self._app()
        assert "QueueRules.withQueuedChanges(serverItems, queue, columns)" in js
        # The board: when the queue changes, and when the board is loaded.
        assert js.count("QueueRules.boardWithQueuedChanges(") == 2

    def test_server_data_is_kept_apart_from_what_is_shown(self):
        """What is stored for offline use, and what the queue is applied
        to, is the server's answer; storing the shown items would apply
        a queued change twice on the next visit."""
        js = self._app()
        assert "cacheListItems(currentListId, serverItems);" in js
        assert "cacheListItems(currentListId, cachedItems)" not in js

    def test_page_follows_a_queue_stored_by_another_copy(self):
        """Two copies of the page share the stored queue. When one sends
        or changes it, the other redraws its count and list, and drops
        its undo steps, which hold the queue as it was before."""
        js = self._app()
        start = js.index('window.addEventListener("storage"')
        listener = js[start : js.index("\n  });", start)]
        assert "event.key !== OFFLINE_QUEUE_KEY" in listener
        for call in (
            "clearOfflineUndo();",
            "updatePendingBadge();",
            "updateConnectionIndicator();",
            "if (replayRunning) return;",
            "storedQueueLength(event.newValue) < storedQueueLength(event.oldValue)",
            "refreshCurrentList();",
            "showQueuedChanges();",
        ):
            assert call in listener

    def test_every_change_to_the_queue_redraws(self):
        js = self._app()
        body = js.split("function saveOfflineQueue(queue, quiet) {")[1].split("\n  }\n")[0]
        assert "if (!quiet) showQueuedChanges();" in body

    def test_rows_and_cards_carry_the_label(self):
        js = self._app()
        assert js.count("if (item.unsent) meta.appendChild(createUnsentLabel());") == 2
        assert 'label.textContent = "Not sent";' in js

    def test_label_is_styled(self):
        css = (STATIC_DIR / "style.css").read_text()
        assert ".item-unsent {" in css

    def test_tasks_waiting_to_be_added_are_drawn(self):
        js = self._app()
        assert "QueueRules.queuedAdds(getOfflineQueue(), currentListId)" in js
        assert "item.provisional ? createQueuedAddCard(item) : createBoardCard(item)" in js

    def test_a_task_waiting_to_be_added_can_only_be_removed(self):
        """Its row has no handler but the remove button's: nothing in the
        page can send a request about a task the server does not have."""
        js = self._app()
        for name in ("createQueuedAddRow", "createQueuedAddCard"):
            body = js.split(f"function {name}(queued) {{")[1].split("\n  }\n")[0]
            assert "addEventListener" not in body, name
            assert "attachLongPress" not in body, name
            assert "attachSwipe" not in body, name
            assert "createQueuedAddRemoveButton(queued," in body, name
        row = js.split("function createQueuedAddRow(queued) {")[1].split("\n  }\n")[0]
        assert "cb.disabled = true;" in row

    def test_waiting_rows_are_styled(self):
        css = (STATIC_DIR / "style.css").read_text()
        assert ".item.queued-add," in css
        assert ".board-card.queued-add {" in css


class TestLongPress:
    """A long press opens the task menu and nothing else."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def test_click_that_ends_a_long_press_is_discarded(self):
        """A mouse release is followed by a click, sent to the pressed
        task in one browser and to the menu over it in others. It is
        taken in the capture phase, wherever it lands."""
        js = self._app()
        body = js.split("function discardNextClick() {")[1].split("\n  }\n")[0]
        assert "e.preventDefault();" in body
        assert "e.stopPropagation();" in body
        assert 'window.addEventListener("click", discardedClick, true);' in body
        press = js.split("function attachLongPress(el, onLongPress) {")[1].split("\n  }\n")[0]
        fired = press.split("timer = setTimeout(function () {")[1].split("}, HOLD_MS);")[0]
        assert fired.index("discardNextClick();") < fired.index("onLongPress(e);")

    def test_wait_for_that_click_ends_at_the_next_press(self):
        """A long press by touch sends no click; the next press must not
        lose its own."""
        js = self._app()
        body = js.split("function discardNextClick() {")[1].split("\n  }\n")[0]
        assert 'window.addEventListener("pointerdown", stopDiscardingClick, true);' in body
        stop = js.split("function stopDiscardingClick() {")[1].split("\n  }\n")[0]
        assert 'window.removeEventListener("click", discardedClick, true);' in stop
        assert 'window.removeEventListener("pointerdown", stopDiscardingClick, true);' in stop


class TestRowEntryAnimation:
    """A redraw of the list builds every row anew. The entry animation,
    from transparent to opaque, is for the rows that are new or have
    changed; given to every row, it made the whole list dip each time a
    change arrived."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _function(self, name: str) -> str:
        return self._app().split(f"function {name}(")[1].split("\n  }\n")[0]

    def test_rows_are_not_built_with_the_animation(self):
        for name in ("createItemCard", "createQueuedAddRow"):
            assert "item-enter" not in self._function(name), name

    def test_a_row_comes_in_when_it_is_new_or_changed(self):
        body = self._function("renderItems")
        assert "var drawnFrom = fingerprint(source);" in body
        assert 'if (before[source.id] !== drawnFrom) el.classList.add("item-enter");' in body
        assert "rows[source.id] = drawnFrom;" in body

    def test_every_row_of_the_list_is_placed_that_way(self):
        """Tasks, subtasks and the tasks waiting to be added."""
        body = self._function("renderItems")
        assert body.count("itemsContainer.appendChild(") == 1
        assert "place(createQueuedAddRow(queued), queued);" in body
        assert "place(createItemCard(item, items, hasChildren, isCollapsed), item);" in body
        assert "place(el, child);" in body

    def test_rows_of_another_list_are_all_new(self):
        body = self._function("renderItems")
        assert "var before = drawnRows.list === currentListId ? drawnRows.rows : {};" in body
        assert "drawnRows = { list: currentListId, rows: rows };" in body

    def test_what_was_drawn_is_recorded_before_an_empty_list_returns(self):
        """A list emptied and filled again shows its rows as new."""
        body = self._function("renderItems")
        assert body.index("drawnRows = { list: currentListId, rows: rows };") < body.index(
            'if (emptyMsg) emptyMsg.classList.remove("hidden");'
        )

    def test_first_appearance_of_the_list_keeps_the_animation(self):
        """The page draws the list twice as it starts; the second draw
        would find every row unchanged."""
        body = self._app().split("async function init() {")[1].split("\n  }\n")[0]
        assert body.index("await refreshCurrentList();") < body.index(
            "drawnRows = { list: null, rows: {} };"
        )
        assert body.index("drawnRows = { list: null, rows: {} };") < body.index(
            "setViewMode(viewMode);"
        )

    def test_search_results_keep_the_animation(self):
        body = self._app().split("results.forEach(function (group) {")[1].split("\n    });\n")[0]
        assert 'row.classList.add("item-enter");' in body


class TestPressHoldsRedraw:
    """A redraw replaces every row and card. One that came while a row
    was pressed left the release with a new element: the tap opened
    nothing, and the old row's long-press timer opened the task menu."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _function(self, name: str) -> str:
        return self._app().split(f"function {name}(")[1].split("\n  }\n")[0]

    def test_list_board_and_calendar_wait_for_the_press_to_end(self):
        """After the check for unchanged data, so that a refresh with
        nothing new leaves nothing waiting; a forced redraw does not
        wait."""
        items = self._function("renderItems")
        assert (
            items.index("if (!force && fp === lastItemsFingerprint) return;")
            < items.index("if (!force && redrawHeld()) return;")
            < items.index("lastItemsFingerprint = fp;")
        )
        board = self._function("renderBoard")
        assert (
            board.index("if (!force && fp === lastBoardFingerprint) return;")
            < board.index("if (!force && redrawHeld()) return;")
            < board.index("lastBoardFingerprint = fp;")
        )
        assert "if (redrawHeld()) return;" in self._function("refreshCalendar")
        # The hour grid's answer can arrive after a press has begun.
        grid = self._function("_refreshHourGrid")
        assert grid.index("if (redrawHeld()) return;") < grid.index("_buildHourGrid(range.days);")

    def test_a_held_redraw_is_made_when_the_press_ends(self):
        held = self._function("redrawHeld")
        assert "if (!pressHeld) return false;" in held
        assert "redrawWaiting = true;" in held
        end = self._function("endPress")
        assert "pressHeld = false;" in end
        assert end.index("redrawWaiting = false;") < end.index("showQueuedChanges();")

    def test_press_is_followed_from_the_window(self):
        """Before any handler of the pressed element, which may stop the
        event; in the three views only."""
        js = self._app()
        start = js.index('  window.addEventListener(\n    "pointerdown",')
        down = js[start : js.index("    true,\n  );", start)]
        assert 'e.target.closest("#list-view, #board-view, #calendar-view")' in down
        assert "if (e.button !== 0) return;" in down
        assert "pressHeld = true;" in down

    def test_release_waits_for_its_handlers_and_for_the_click(self):
        """A redraw at the release itself would replace the row before
        its click, or under the handler of a swipe or a drag."""
        js = self._app()
        start = js.index('  window.addEventListener(\n    "pointerup",')
        up = js[start : js.index("    true,\n  );", start)]
        assert "pressMoved ? 0 : PRESS_CLICK_WAIT_MS," in up
        assert "endPress();" not in up
        start = js.index('  window.addEventListener(\n    "click",')
        click = js[start : js.index("    true,\n  );", start)]
        assert "if (!pressEndTimer) return;" in click
        assert "pressEndTimer = setTimeout(endPress, 0);" in click

    def test_a_press_without_a_release_does_not_hold_the_page(self):
        js = self._app()
        assert 'window.addEventListener("pointercancel", endPress, true);' in js
        assert "if (document.hidden) endPress();" in js

    def test_a_finger_held_down_is_not_ended_by_the_browsers_menu_event(self):
        """A phone sends contextmenu for a finger held down, before the
        long press here is due. Ending the press there drew the row
        again, and its menu never opened. A mouse press that opens the
        browser's menu loses its release to it, and is ended."""
        js = self._app()
        assert 'window.addEventListener("contextmenu", endPress, true);' not in js
        start = js.index('  window.addEventListener(\n    "contextmenu",')
        menu = js[start : js.index("    true,\n  );", start)]
        assert "if (pressByMouse) endPress();" in menu
        assert 'pressByMouse = e.pointerType === "mouse";' in js

    def test_timer_of_a_replaced_row_does_nothing(self):
        """A redraw that does not wait can still replace a pressed row."""
        body = self._function("attachLongPress")
        timer = body.split("timer = setTimeout(function () {")[1].split("}, HOLD_MS);")[0]
        assert (
            timer.index('el.classList.remove("long-press-active");')
            < timer.index("if (!el.isConnected) return;")
            < timer.index("onLongPress(e);")
        )


class TestCalendarToolbar:
    """The calendar's arrows and Today act on the month, week and day
    views; the Timeline is not about one date."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _function(self, name: str) -> str:
        return self._app().split(f"function {name}(")[1].split("\n  }\n")[0]

    def test_toolbar_has_a_today_button(self):
        html = (STATIC_DIR / "index.html").read_text()
        toolbar = html.split('<div class="cal-toolbar">')[1].split('<div id="cal-container"')[0]
        assert toolbar.index('id="cal-next"') < toolbar.index('id="cal-today"')
        assert toolbar.index('id="cal-today"') < toolbar.index('class="cal-sub-tabs"')

    def test_arrows_do_nothing_in_the_timeline(self):
        """They are hidden there; a press that reached the handler anyway
        would move the date of the other views unseen."""
        body = self._function("navigateCalendar")
        assert body.index('if (calSubView === "timeline") return;') < body.index("calDate.set")

    def test_month_arrows_do_not_skip_a_shorter_month(self):
        """From the 31st, setMonth alone lands in the month after the
        next. The day is set aside, and put back no later than the last
        day of the month arrived at."""
        body = self._function("navigateCalendar")
        month = body.split('if (calSubView === "month") {')[1].split("} else if")[0]
        assert month.index("calDate.setDate(1);") < month.index("calDate.setMonth(")
        assert "calDate.setDate(Math.min(day, lastDay));" in month

    def test_arrows_and_today_are_hidden_in_the_timeline_and_keep_their_place(self):
        body = self._function("renderCalendar")
        assert 'calToolbar.classList.toggle("cal-undated", !dated);' in body
        css = (STATIC_DIR / "style.css").read_text()
        rule = css.split(".cal-undated .cal-nav-btn,\n.cal-undated .cal-today-btn {")[1].split("}")[
            0
        ]
        # Hidden, not removed: the tabs beside them must not move.
        assert "visibility: hidden;" in rule
        assert "display" not in rule

    def test_today_is_disabled_where_today_is_already_shown(self):
        body = self._function("renderCalendar")
        assert "calToday.disabled = !dated || calShowsToday();" in body

    def test_calendar_follows_the_day_until_a_date_is_chosen(self):
        """A page left open overnight shows the new day; a month, week or
        day reached with the arrows is kept, until they or Today bring
        the calendar back to today."""
        assert "if (!calDateChosen) calDate = new Date();" in self._function("renderCalendar")
        assert "calDateChosen = !calShowsToday();" in self._function("navigateCalendar")
        js = self._app()
        assert 'if (viewMode === "calendar" && calDateIsStale()) renderCalendar();' in js


class TestCalendarMonth:
    """Seven columns of a phone's screen cannot hold task titles. On a
    narrow screen the Month is a grid of day numbers with a dot for a
    task due, and the selected day's tasks listed under it; on a wide
    one it is a cell of titles for each day."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _css(self) -> str:
        return (STATIC_DIR / "style.css").read_text()

    def _function(self, name: str) -> str:
        return self._app().split(f"function {name}(")[1].split("\n  }\n")[0]

    def _rule(self, selector: str) -> str:
        return self._css().split(selector + " {")[1].split("}")[0]

    def test_month_is_laid_out_for_the_width_of_the_screen(self):
        js = self._app()
        assert 'var calNarrowScreen = window.matchMedia("(max-width: 700px)");' in js
        body = self._function("renderMonthView")
        assert "if (calIsNarrow()) _renderCompactMonth(year, month, byDate);" in body
        assert "else _renderWideMonth(year, month, byDate);" in body

    def test_calendar_is_drawn_again_when_the_screen_crosses_that_width(self):
        js = self._app()
        start = js.index('calNarrowScreen.addEventListener("change"')
        listener = js[start : js.index("\n  });", start)]
        assert 'if (viewMode === "calendar") renderCalendar();' in listener

    def test_week_begins_on_monday(self):
        """As in the desktop application."""
        js = self._app()
        assert 'var _WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];' in js
        assert "return (d.getDay() + 6) % 7;" in self._function("_weekdayIndex")
        for name in ("_renderWideMonth", "_renderCompactMonth"):
            body = self._function(name)
            assert "var leading = _weekdayIndex(new Date(year, month, 1));" in body, name
            assert "_WEEKDAY_NAMES.forEach(" in body, name

    def test_columns_share_the_width_equally(self):
        """A plain 1fr column cannot be narrower than the longest title
        in it: the grid was 678 px wide on a 412 px screen."""
        for selector in (".cal-month-grid", ".cal-mini-grid"):
            assert "grid-template-columns: repeat(7, minmax(0, 1fr));" in self._rule(selector)

    def test_today_is_tinted_over_the_cells_own_colour(self):
        """The translucent tint alone let the grid's border colour
        through, and today was a grey block."""
        rule = self._rule(".cal-day.today")
        assert (
            "background-image: linear-gradient(var(--accent-subtle), var(--accent-subtle));" in rule
        )
        assert "background:" not in rule

    def test_wide_month_ends_on_a_whole_week(self):
        body = self._function("_renderWideMonth")
        assert "var trailing = (7 - ((leading + daysInMonth) % 7)) % 7;" in body
        # The title is cut by the cell, not by a count of characters.
        assert "_escHtml(it.reminder) +" in body
        assert "substring" not in body

    def test_compact_month_shows_whole_weeks_and_the_selected_days_tasks(self):
        body = self._function("_renderCompactMonth")
        assert "var cells = Math.ceil((leading + daysInMonth) / 7) * 7;" in body
        assert "var day = new Date(year, month, 1 - leading + i);" in body
        assert "other: day.getMonth() !== month," in body
        assert "selected: key === selectedKey," in body
        assert "_dayTaskList(calDate, byDate[selectedKey] || [])" in body

    def test_a_day_shows_three_dots_at_most_and_counts_the_rest(self):
        assert "var _MAX_DAY_DOTS = 3;" in self._app()
        body = self._function("_compactDay")
        assert "sorted.slice(0, _MAX_DAY_DOTS).forEach(" in body
        assert 'more.textContent = "+" + (sorted.length - _MAX_DAY_DOTS);' in body

    def test_a_day_is_a_button_that_names_itself(self):
        body = self._function("_compactDay")
        assert 'var cell = document.createElement("button");' in body
        assert 'cell.setAttribute("aria-pressed", is.selected ? "true" : "false");' in body
        assert '"aria-label",' in body
        assert "onTap(day);" in body
        assert "selectCalendarDay," in self._function("_renderCompactMonth")

    def test_selected_day_is_the_calendars_date(self):
        """The Day view opens on it, and Today is offered whenever it is
        not today, also within the current month."""
        select = self._function("selectCalendarDay")
        assert "calDate = new Date(day.getFullYear(), day.getMonth(), day.getDate());" in select
        assert "calDateChosen = !calShowsToday();" in select
        assert "keepingPageScroll(renderCalendar);" in select
        shows = self._function("calShowsToday")
        wide = shows.split("if (!calIsNarrow()) {")[1].split("\n    }\n")[0]
        assert 'if (calSubView === "month") {' in wide
        assert "return _dayKey(calDate) === _dayKey(today);" in shows.split("\n    }\n")[-1]

    def test_tasks_of_a_day_are_listed_in_order(self):
        """To do before done, timed before untimed, by time, by priority."""
        body = self._function("_sortDayTasks")
        assert "return items.slice().sort(" in body
        assert (
            body.index("a.complete !== b.complete")
            < body.index("Boolean(a.due_time) !== Boolean(b.due_time)")
            < body.index("a.due_time < b.due_time")
            < body.index("a.priority - b.priority")
        )

    def test_a_listed_task_says_when_it_is_due_and_opens(self):
        lines = self._function("_taskTimeLines")
        assert "[item.due_time.substring(0, 5), item.due_time_end.substring(0, 5)]" in lines
        assert 'return ["All day"];' in lines
        row = self._function("_calTaskRow")
        assert 'var row = document.createElement("button");' in row
        assert 'location.hash = "#/item/" + item.id;' in row

    def test_compact_month_is_styled(self):
        css = self._css()
        for selector in (
            ".cal-mini-day.selected .cal-mini-num {",
            ".cal-mini-day.today .cal-mini-num {",
            ".cal-mini-day.other .cal-mini-num {",
            ".cal-mini-dot.high {",
            ".cal-mini-dot.done {",
            ".cal-task.completed .cal-task-title {",
        ):
            assert selector in css, selector


class TestCalendarWeek:
    """On a wide screen the Week is the hour grid of the calendar week,
    Monday to Sunday. Seven columns of hours do not fit a phone, and
    most tasks have no hour: on a narrow screen the Week is seven days
    beginning at the calendar's date, with the tasks listed day by day."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _function(self, name: str) -> str:
        return self._app().split(f"function {name}(")[1].split("\n  }\n")[0]

    def test_calendar_week_begins_on_monday(self):
        body = self._function("_startOfWeek")
        assert "d.setDate(d.getDate() - _weekdayIndex(d));" in body

    def test_week_is_laid_out_for_the_width_of_the_screen(self):
        body = self._function("renderWeekView")
        assert "var narrow = calIsNarrow();" in body
        assert "? new Date(calDate.getFullYear(), calDate.getMonth(), calDate.getDate())" in body
        assert ": _startOfWeek(calDate);" in body
        assert "if (narrow) _renderWeekList(first);" in body
        assert "else _renderHourGrid(first, 7);" in body

    def test_narrow_week_is_drawn_from_the_lists_tasks(self):
        """Not an hour grid: a refresh compares the tasks, and does not
        ask the server for the grid's segments."""
        shows = self._function("calShowsHourGrid")
        assert 'calSubView === "day" || (calSubView === "week" && !calIsNarrow())' in shows
        assert "if (calShowsHourGrid()) {" in self._function("refreshCalendar")
        assert "_itemsByDate(_calItems())" in self._function("_renderWeekList")

    def test_narrow_week_is_where_today_is_when_it_begins_today(self):
        shows = self._function("calShowsToday")
        wide = shows.split("if (!calIsNarrow()) {")[1].split("\n    }\n")[0]
        assert 'if (calSubView === "week") {' in wide
        assert "_startOfWeek(calDate).getTime() === _startOfWeek(today).getTime()" in wide

    def test_a_section_for_each_of_seven_days(self):
        body = self._function("_renderWeekList")
        assert "for (var i = 0; i < 7; i++) {" in body
        assert "var section = _dayTaskList(day, items);" in body
        assert "sections.appendChild(section);" in body

    def test_a_day_of_the_strip_moves_the_list_and_not_the_date(self):
        body = self._function("_renderWeekList")
        assert "_showWeekDay(section);" in body
        assert "selectCalendarDay" not in body
        show = self._function("_showWeekDay")
        assert 'if (list.classList.contains("scrolls")) {' in show
        assert "top: section.offsetTop - list.firstElementChild.offsetTop," in show
        # Where the whole page scrolls: below the header, which stays
        # in place.
        assert 'section.scrollIntoView({ behavior: "smooth", block: "start" });' in show
        assert "section.style.scrollMarginTop =" in show

    def test_week_list_scrolls_under_the_toolbar_and_the_strip(self):
        """Scrolled with the page, the toolbar and the strip slid under
        the header, which cut off the arrows and the dates. The list has
        the room between the strip and the bottom bar to scroll in."""
        fit = self._function("_fitWeekList")
        assert "var room = _roomAboveBottomBar(list);" in fit
        room = self._function("_roomAboveBottomBar")
        assert 'var nav = document.getElementById("bottom-nav");' in room
        assert "return Math.floor(bottom - el.getBoundingClientRect().top - 8);" in room
        assert 'list.classList.add("scrolls");' in fit
        assert 'list.style.height = room + "px";' in fit
        css = (STATIC_DIR / "style.css").read_text()
        rule = css.split(".cal-week-days.scrolls {")[1].split("}")[0]
        assert "overflow-y: auto;" in rule
        assert "overscroll-behavior: contain;" in rule
        js = self._app()
        assert "_fitWeekList();" in self._function("_renderWeekList")
        resize = js.split('window.addEventListener("resize", function () {')[1].split("});")[0]
        assert "_fitWeekList();" in resize
        assert "_fitHourGrid();" in resize

    def test_last_day_of_the_week_can_reach_the_top_of_the_list(self):
        fit = self._function("_fitWeekList")
        assert "Math.max(0, room - last.offsetHeight)" in fit

    def test_too_little_room_leaves_the_page_to_scroll(self):
        """A phone on its side."""
        assert "var _WEEK_LIST_MIN_HEIGHT = 200;" in self._app()
        fit = self._function("_fitWeekList")
        small = fit.split("if (room < _WEEK_LIST_MIN_HEIGHT) {")[1].split("}")[0]
        assert 'list.classList.remove("scrolls");' in small
        assert 'list.style.height = "";' in small

    def test_week_drawn_again_stays_where_its_list_was_scrolled_to(self):
        body = self._function("_renderWeekList")
        assert "shown && shown.dataset.first === firstKey ? shown.scrollTop : 0;" in body
        assert body.index("var scrolled =") < body.index('calContainer.innerHTML = "";')
        assert "sections.dataset.first = firstKey;" in body
        assert body.index("_fitWeekList();") < body.index("sections.scrollTop = scrolled;")

    def test_pull_to_refresh_is_not_started_inside_a_scrolled_part(self):
        """A finger moving down inside a list that scrolls by itself
        scrolls that list back; it does not ask for a refresh."""
        js = self._app()
        body = js.split("(function initPullToRefresh() {")[1].split("})();")[0]
        start = body.split('"touchstart",')[1].split('"touchmove",')[0]
        assert "for (var el = e.target; el && el !== viewHome; el = el.parentElement) {" in start
        assert "if (el.scrollTop > 5) return;" in start
        assert start.index("if (el.scrollTop > 5) return;") < start.index("pulling = true;")

    def test_overdue_tasks_come_first_in_a_week_that_holds_today(self):
        """Those still to do that were due before the week's first day:
        a task of a day in the week is under its day."""
        body = self._function("_renderWeekList")
        assert "if (firstKey <= todayKey && todayKey <= lastKey) {" in body
        assert "return !item.complete && item.due_date < firstKey;" in body
        assert "if (overdue.length > 0) sections.appendChild(_overdueTaskList(overdue));" in body
        assert body.index("_overdueTaskList(overdue)") < body.index("days.forEach(")

    def test_an_overdue_task_shows_the_day_it_was_due(self):
        body = self._function("_overdueTaskList")
        assert 'name.textContent = "Overdue";' in body
        assert "_calTaskRow(item, [" in body
        assert 'weekday: "short",' in body

    def test_today_and_tomorrow_are_named_in_their_headings(self):
        body = self._function("_dayTaskList")
        assert '(isToday ? "Today \\u00B7 " : isTomorrow ? "Tomorrow \\u00B7 " : "") +' in body

    def test_week_list_is_styled(self):
        css = (STATIC_DIR / "style.css").read_text()
        for selector in (
            ".cal-week-strip .cal-mini-day {",
            ".cal-week-strip .cal-mini-day.today .cal-mini-num {",
            ".cal-day-heading.overdue .cal-day-name {",
        ):
            assert selector in css, selector


class TestCalendarContrast:
    """Text in the calendar reaches the 4.5:1 that WCAG AA asks of it,
    in the light theme and in the dark one."""

    def _css(self) -> str:
        return (STATIC_DIR / "style.css").read_text()

    def _themes(self) -> dict[str, dict[str, str]]:
        """The colour variables of the light theme, and of the dark one
        as the light theme with the dark block's values over it."""
        import re

        css = self._css()
        light_block = css.split(":root {")[1].split("\n}\n")[0]
        dark_block = css.split(':root[data-theme="dark"] {')[1].split("\n}\n")[0]
        variable = re.compile(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6});")
        light = dict(variable.findall(light_block))
        return {"light": light, "dark": {**light, **dict(variable.findall(dark_block))}}

    @staticmethod
    def _contrast(a: str, b: str) -> float:
        def luminance(colour: str) -> float:
            def channel(value: int) -> float:
                c = value / 255
                return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

            r, g, b_ = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
            return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b_)

        la, lb = luminance(a), luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    def test_both_dark_blocks_set_the_same_colours(self):
        """The dark theme is written twice, for the system's setting and
        for the page's own switch."""
        import re

        css = self._css()
        by_system = css.split(':root:not([data-theme="light"]) {')[1].split("\n  }\n")[0]
        by_switch = css.split(':root[data-theme="dark"] {')[1].split("\n}\n")[0]
        variable = re.compile(
            r"--(on-accent|accent|text-secondary|completed-text):\s*(#[0-9a-fA-F]{6});"
        )
        assert dict(variable.findall(by_system)) == dict(variable.findall(by_switch))

    def test_text_on_the_accent_colour(self):
        """The selected day, today in the week's strip, the active tab.
        White on the dark theme's accent, a light blue, is 2.2:1."""
        for theme, colours in self._themes().items():
            ratio = self._contrast(colours["on-accent"], colours["accent"])
            assert ratio >= 4.5, (theme, round(ratio, 2))
        css = self._css()
        for selector in (
            ".cal-tab.active",
            ".cal-mini-day.selected .cal-mini-num",
            ".cal-week-strip .cal-mini-day.today .cal-mini-num",
        ):
            rule = css.split(selector + " {")[1].split("}")[0]
            assert "background: var(--accent);" in rule, selector
            assert "color: var(--on-accent);" in rule, selector

    def test_text_of_the_month_and_the_week_list(self):
        pairs = (
            ("day number", "text", "bg"),
            ("day of another month, weekday names, notes", "text-secondary", "bg"),
            ("today's number and heading", "accent", "bg"),
            ("the Overdue heading", "high", "bg"),
            ("a task's title", "text", "bg-card"),
            ("a task's time", "text-secondary", "bg-card"),
            ("a done task's title", "completed-text", "bg-card"),
        )
        for theme, colours in self._themes().items():
            for what, fg, bg in pairs:
                ratio = self._contrast(colours[fg], colours[bg])
                assert ratio >= 4.5, (theme, what, round(ratio, 2))

    def test_a_day_of_another_month_is_dimmed_by_colour_alone(self):
        """Faded as well, its number fell to 2.2:1 in the light theme
        and 2.9:1 in the dark one. It is a button like the others."""
        rule = self._css().split(".cal-mini-day.other .cal-mini-num {")[1].split("}")[0]
        assert "color: var(--text-secondary);" in rule
        assert "opacity" not in rule

    def test_dots_and_task_edges_stand_out_as_graphics(self):
        """WCAG asks 3:1 of a graphic that carries meaning."""
        for theme, colours in self._themes().items():
            for mark in ("normal", "high", "low", "text-secondary"):
                for ground in ("bg", "bg-card"):
                    ratio = self._contrast(colours[mark], colours[ground])
                    assert ratio >= 3.0, (theme, mark, ground, round(ratio, 2))


class TestCalendarHourGrid:
    """The hour grid of the Day, and of the Week on a wide screen."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _function(self, name: str) -> str:
        return self._app().split(f"function {name}(")[1].split("\n  }\n")[0]

    def test_one_day_takes_the_width_it_is_given(self):
        """The least width is for seven columns. Given to one day as
        well, it made the Day scroll sideways on a phone."""
        body = self._function("_buildHourGrid")
        assert "width: days === 1 ? room : Math.max(room, _GRID_CANVAS_MIN_WIDTH)," in body
        assert "parseFloat(style.paddingLeft)" in body
        assert "_buildHourGrid(days);" in self._function("_renderHourGrid")
        assert "_buildHourGrid(range.days);" in self._function("_refreshHourGrid")

    def test_hours_open_at_the_present_time_or_the_first_timed_task(self):
        """Opened at midnight, the grid showed the empty night."""
        minute = self._function("_openingMinute")
        assert "return now.getHours() * 60 + now.getMinutes();" in minute
        assert "if (seg.is_all_day || seg.is_marker) return;" in minute
        assert "return first === null ? 8 * 60 : first;" in minute
        opened = self._function("_openHoursAt")
        assert "var minute = Math.max(0, _openingMinute(data) - 60);" in opened
        assert "scrollDiv.scrollTop = Math.round((minute / 60) * _HOUR_ROW_HEIGHT);" in opened

    def test_only_a_grid_put_on_screen_is_opened_there(self):
        """One drawn again after a refresh stays at the hour it was
        scrolled to."""
        assert "_openHoursAt(grid.scroll, data);" in self._function("_renderHourGrid")
        refresh = self._function("_refreshHourGrid")
        assert "_openHoursAt" not in refresh
        assert "grid.scroll.scrollTop = scrolled;" in refresh

    def test_canvases_have_the_screens_pixels(self):
        """With one pixel to each unit of the page, a phone's screen,
        which has two or three, showed the text blurred."""
        size = self._function("_sizeCanvas")
        assert "canvas.width = Math.round(width * ratio);" in size
        assert 'canvas.style.width = width + "px";' in size
        body = self._function("_paintPinnedAndHours")
        assert "var ratio = window.devicePixelRatio || 1;" in body
        assert "_sizeCanvas(pinned, W, pinnedH, ratio);" in body
        assert "_sizeCanvas(hours, W, hoursH, ratio);" in body
        for name, height in (("_paintPinnedZone", "pinnedH"), ("_paintHoursZone", "hoursH")):
            zone = self._function(name)
            assert "ctx.setTransform(layout.ratio, 0, 0, layout.ratio, 0, 0);" in zone, name
            assert "var W = layout.W;" in zone, name
            assert f"var H = layout.{height};" in zone, name
            assert "canvas.width" not in zone, name

    def test_a_click_is_found_in_the_units_the_bars_were_painted_in(self):
        body = self._function("_installHourGridClickHandler")
        assert "var scaleX = canvas._unitWidth / rect.width;" in body
        assert "var scaleY = canvas._unitHeight / rect.height;" in body

    @staticmethod
    def _luminance(colour: str) -> float:
        """WCAG relative luminance of a #rrggbb colour."""

        def channel(value: int) -> float:
            c = value / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    def test_a_label_is_black_or_white_whichever_the_fill_sets_off(self):
        """The page's own text colour is chosen for the page's
        background. On the dark theme's bars it measured 1.1:1 to 2.1:1,
        and on four of the light theme's six, under 4.5:1."""
        body = self._function("_barTextColor")
        assert "var onWhite = 1.05 / (lum + 0.05);" in body
        assert "var onBlack = (lum + 0.05) / 0.05;" in body
        assert 'return onWhite >= onBlack ? "#ffffff" : "#000000";' in body
        luminance = self._function("_luminance")
        assert "return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];" in luminance
        assert "c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)" in luminance

    def test_every_bar_colour_of_both_themes_gives_its_label_aa_contrast(self):
        """WCAG AA asks 4.5:1 of text. The rule above, worked here for
        every fill in the style sheet."""
        import re

        css = (STATIC_DIR / "style.css").read_text()
        fills = set(re.findall(r"--bar-[a-z-]+:\s*(#[0-9a-fA-F]{6});", css))
        assert len(fills) >= 12
        for fill in sorted(fills):
            lum = self._luminance(fill)
            best = max(1.05 / (lum + 0.05), (lum + 0.05) / 0.05)
            assert best >= 4.5, (fill, round(best, 2))

    def test_no_fill_can_leave_both_black_and_white_short_of_aa(self):
        """The two contrasts cross at 4.58:1, their lowest."""
        worst = min(max(1.05 / (n / 1000 + 0.05), (n / 1000 + 0.05) / 0.05) for n in range(1001))
        assert worst >= 4.5

    def test_no_label_on_a_bar_uses_the_pages_text_colour(self):
        for name in ("_paintHourBar", "_paintAllDayChip", "_paintMarkerChip"):
            body = self._function(name)
            assert '_themeColor("text"' not in body, name
            assert 'ctx.fillStyle = "#ffffff";' not in body, name
            assert "_paintLabelOn(ctx, text," in body, name

    def test_a_bar_of_two_colours_has_its_label_written_on_each(self):
        """Each part of the label is on the colour it was chosen for."""
        bar = self._function("_paintHourBar")
        assert "{ x: x, y: y, w: splitX - x, h: h, fill: base }," in bar
        assert "{ x: splitX, y: y, w: x + w - splitX, h: h, fill: deviation }," in bar
        assert "zones.forEach(function (zone) {" in bar
        label = self._function("_paintLabelOn")
        assert (
            label.index("ctx.rect(zone.x, zone.y, zone.w, zone.h);")
            < label.index("ctx.clip();")
            < label.index("ctx.fillStyle = _barTextColor(zone.fill);")
            < label.index("ctx.fillText(text, tx, ty);")
        )

    def test_hours_scroll_in_the_room_above_the_bottom_bar(self):
        """The page, with the toolbar, stays in place."""
        fit = self._function("_fitHourGrid")
        assert "var room = _roomAboveBottomBar(wrap);" in fit
        assert 'wrap.style.maxHeight = room < _WEEK_LIST_MIN_HEIGHT ? "" : room + "px";' in fit
        assert "_fitHourGrid();" in self._function("_buildHourGrid")


class TestCalendarFollowsData:
    """The calendar on screen is drawn again when a refresh, or a change
    to the queue, has changed what it shows, and only then."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _function(self, name: str) -> str:
        return self._app().split(f"function {name}(")[1].split("\n  }\n")[0]

    def test_every_refresh_reaches_the_calendar(self):
        """Refreshes and queue changes end in showQueuedChanges, which
        drew the list or the board and never the calendar."""
        body = self._function("showQueuedChanges")
        assert 'if (viewMode === "calendar") refreshCalendar();' in body

    def test_month_and_timeline_are_drawn_again_only_when_changed(self):
        body = self._function("refreshCalendar")
        assert body.index("if (calShownFrom() === calDrawnFrom) return;") < body.index(
            "keepingPageScroll(renderCalendar);"
        )
        assert "calDrawnFrom = calShownFrom();" in self._function("renderCalendar")
        shown = self._function("calShownFrom")
        assert "fingerprint([calSubView, _dayKey(calDate), _calItems()])" in shown

    def test_week_and_day_compare_the_servers_answer(self):
        """Their grid is drawn from the server's answer, which covers
        every list; the current list's tasks do not tell whether it has
        changed."""
        body = self._function("refreshCalendar")
        assert "if (calShowsHourGrid()) {" in body
        assert "_refreshHourGrid();" in body
        grid = self._function("_refreshHourGrid")
        assert (
            grid.index("_fetchSegments(range.start, range.days)")
            < grid.index("if (answer === hourGridShown.answer) return;")
            < grid.index("_buildHourGrid(range.days);")
        )

    def test_a_refreshed_grid_keeps_its_place_and_shows_no_loading(self):
        grid = self._function("_refreshHourGrid")
        assert "var scrolled = old ? old.scrollTop : 0;" in grid
        assert "grid.scroll.scrollTop = scrolled;" in grid
        assert "keepingPageScroll(function () {" in grid
        assert "cal-hour-grid-loading" not in grid
        # The first draw of a grid has nothing to show yet, and says so.
        assert "cal-hour-grid-loading" in self._function("_renderHourGrid")

    def test_a_refresh_that_fails_leaves_the_grid(self):
        grid = self._function("_refreshHourGrid")
        failed = grid.split(".catch(function () {")[1]
        assert "Failed" not in failed
        assert "innerHTML" not in failed

    def test_an_answer_for_a_calendar_no_longer_on_screen_is_dropped(self):
        """A tab, an arrow or another view chosen while the answer was
        on its way."""
        assert "calDraws++;" in self._function("renderCalendar")
        first = self._function("_renderHourGrid")
        assert first.count("if (draw !== calDraws) return;") == 2
        grid = self._function("_refreshHourGrid")
        assert "if (draw !== calDraws || refresh !== hourGridRefreshes) return;" in grid
        assert 'if (viewMode !== "calendar") return;' in grid
        # A grid waiting for its first answer is left to it.
        assert "if (hourGridLoading === calDraws) return;" in grid

    def test_page_scroll_is_kept_across_a_redraw(self):
        body = self._function("keepingPageScroll")
        assert body.index("var inPage = window.scrollY;") < body.index("draw();")
        assert "window.scrollTo(window.scrollX, inPage);" in body
        assert "main.scrollTop = inMain;" in body


class TestDeleteNotice:
    """A delete is announced once, with Undo, when it has been kept."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _delete(self) -> str:
        return self._app().split("async function onDelete(")[1].split("\n  }\n")[0]

    def test_every_delete_in_the_page_goes_the_same_way(self):
        """The row's button, the swipe, the task menu and the item sheet."""
        js = self._app()
        assert "onDeleteWithUndo" not in js
        # The definition and its four callers.
        assert js.count("onDelete(") == 5
        assert js.count('method: "DELETE" }') == 1

    def test_row_leaves_at_once(self):
        body = self._delete()
        assert body.index('cardEl.classList.add("item-exit");') < body.index("await sendOrQueue(")

    def test_notice_waits_for_the_delete_to_be_kept(self):
        """Shown before, its Undo has no delete to act on, and undoes
        whatever came before it."""
        body = self._delete()
        before, after = body.split("await sendOrQueue(")
        assert "showToast(" not in before
        assert after.count("showToast(") == 2

    def test_one_notice_for_each_outcome_with_undo(self):
        body = self._delete()
        sent = body.split('if (outcome === "sent") {')[1].split("} else if")[0]
        queued = body.split('} else if (outcome === "queued") {')[1].split("} else if")[0]
        assert 'showToast(name + " deleted", function () {' in sent
        assert 'showToast(name + " deleted (offline)", function () {' in queued

    def test_row_returns_when_the_delete_is_not_kept(self):
        """A refused delete leaves the list as it was, and a list that
        has not changed is not drawn again."""
        body = self._delete()
        rest = body.split('} else if (outcome === "queued") {')[1]
        assert 'cardEl.classList.remove("item-exit");' in rest


class TestNoticeUndo:
    """Undo on a notice that names a task acts on that task's change.
    The toolbar's Undo takes back the latest change, which may be a
    later one, or one made in the desktop window or on another device."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _function(self, name: str) -> str:
        return self._app().split(f"function {name}(")[1].split("\n  }\n")[0]

    def test_no_notice_undoes_the_latest_change(self):
        for name in ("onDelete", "removeQueuedAdd", "undoQueuedDelete", "restoreDeletedItem"):
            body = self._function(name)
            assert "onUndo()" not in body, name
            assert '"/undo"' not in body, name

    def test_a_queued_change_hands_its_step_to_the_caller(self):
        body = self._function("sendOrQueue")
        assert "step.before = before;" in body
        assert "step.after = after;" in body
        assert "var outcome = await sendOrQueue(path, opts, step);" in self._function("onDelete")

    def test_delete_applied_by_the_server_is_restored_by_its_id(self):
        sent = (
            self._function("onDelete").split('if (outcome === "sent") {')[1].split("} else if")[0]
        )
        assert "restoreDeletedItem(itemId, name);" in sent
        body = self._function("restoreDeletedItem")
        assert 'await api("/items/" + itemId + "/restore", { method: "PATCH" });' in body
        assert 'showToast(name + " restored");' in body

    def test_queued_delete_is_taken_out_of_the_queue(self):
        delete = self._function("onDelete")
        queued = delete.split('} else if (outcome === "queued") {')[1].split("} else if")[0]
        assert "undoQueuedDelete(step, itemId, name);" in queued
        body = self._function("undoQueuedDelete")
        assert "if (takeBackQueuedStep(step)) {" in body
        assert 'showToast(name + " restored");' in body

    def test_queued_delete_that_has_been_sent_is_restored_by_the_server(self):
        """The server answered again while the notice was showing. A run
        that is sending the queue is waited for: the delete may be on
        its way."""
        body = self._function("undoQueuedDelete")
        assert (
            body.index("while (replayRunning) {")
            < body.index("takeBackQueuedStep(step)")
            < body.index("await restoreDeletedItem(itemId, name);")
        )

    def test_taking_a_step_back_keeps_later_changes_and_is_a_step_itself(self):
        body = self._function("takeBackQueuedStep")
        assert "QueueRules.withStepTakenBack(queue, step.before, step.after);" in body
        assert "if (!result) return false;" in body
        assert body.index("saveOfflineQueue(result);") < body.index(
            "pushOfflineUndo(queue, result);"
        )

    def test_removed_task_waiting_to_be_added_is_put_back(self):
        body = self._function("removeQueuedAdd")
        assert "var step = { before: getOfflineQueue() };" in body
        assert "step.after = getOfflineQueue();" in body
        assert 'takeBackQueuedStep(step) ? name + " restored" : "Nothing to undo"' in body

    def test_a_restore_that_fails_says_so(self):
        body = self._function("restoreDeletedItem")
        assert "if (e.status === 404) {" in body
        assert 'showToast("Nothing to undo");' in body
        assert "not restored \\u2014 see Recently Deleted" in body


class TestRevalidation:
    """The page's files are checked with the server before reuse."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/", "/sw.js", "/static/app.js", "/static/style.css"])
    async def test_page_files_are_revalidated(self, path):
        client = await _make_client()
        async with client:
            resp = await client.get(path)
            assert resp.status == 200
            assert resp.headers.get("Cache-Control") == "no-cache"

    @pytest.mark.asyncio
    async def test_api_responses_are_left_alone(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/api/status")
            assert "Cache-Control" not in resp.headers

    @pytest.mark.asyncio
    async def test_unchanged_file_is_answered_without_a_body(self):
        client = await _make_client()
        async with client:
            first = await client.get("/static/app.js")
            etag = first.headers.get("ETag")
            assert etag
            second = await client.get("/static/app.js", headers={"If-None-Match": etag})
            assert second.status == 304
            assert second.headers.get("Cache-Control") == "no-cache"


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
    async def test_served_script_registers_the_worker(self):
        client = await _make_client()
        async with client:
            resp = await client.get("/static/app.js")
            text = await resp.text()
            assert 'register("/sw.js")' in text

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
