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

    def test_every_change_is_queued_before_it_is_sent(self):
        """One way to the server (#76): a change is stored in the queue
        first and sent from it, whether or not the server is there. What
        that does is tested in tests/js/queue_send.test.js."""
        js = self._read_app()
        send = js.split("async function sendOrQueue(")[1].split("\n  }\n")[0]
        assert "await queueChange(path, opts, step);" in send
        queue = js.split("async function queueChange(")[1].split("\n  }\n")[0]
        assert queue.index("enqueueOfflineEdit(path, opts);") < queue.index("await changeSent(")
        for body in (send, queue):
            assert "await api(" not in body
            assert "serverFetch(" not in body

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
        # One rule for what a reply means, in the one place that sends.
        assert js.count("QueueRules.replyOutcome(") == 1
        run = js.split("async function sendQueuedChanges() {")[1].split("\n  }\n")[0]
        assert "QueueRules.replyOutcome(resp.status, kind)" in run

    def test_one_replay_at_a_time(self):
        """One run in a copy of the page, and one across the copies by a
        lock (#78); what a run does is tested in tests/js/queue_send.test.js."""
        js = (STATIC_DIR / "app.js").read_text()
        run = js.split("async function replayOfflineQueue() {")[1].split("\n  }\n")[0]
        assert run.index("if (replayRunning) {") < run.index("replayRunning = true;")
        assert "await withQueueLock(async function () {" in run
        lock = js.split("function withQueueLock(run) {")[1].split("\n  }\n")[0]
        assert "return locks.request(QUEUE_LOCK, run);" in lock

    def test_changes_are_queued_in_one_place(self):
        """Every change that can be queued goes through sendOrQueue, so
        that a failed request and an offline device are handled alike."""
        js = (STATIC_DIR / "app.js").read_text()
        # "Add subtask" in the task sheet since #117, a card dropped on
        # the board since #76.
        assert js.count("await sendOrQueue(") == 8
        # The task sheet's edits go the same way, and say in the sheet
        # what became of them (#76).
        assert js.count("await queueChange(") == 2
        for name in ("sendItemFields", "executeDrop", "saveItemFieldForce"):
            body = re.split(rf"(?:async )?function {name}\(", js)[1].split("\n  }\n")[0]
            assert "api(" not in body, name
            assert "serverFetch(" not in body, name
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
        listener = "".join(js[start : js.index("\n  });", start)].split())
        assert "event.key!==OFFLINE_QUEUE_KEY" in listener
        assert "followStoredQueue(" in listener
        assert "storedQueueLength(event.newValue)<storedQueueLength(event.oldValue)" in listener
        follows = js.split("function followStoredQueue(shorter) {")[1].split("\n  }\n")[0]
        for call in (
            "clearOfflineUndo();",
            "updatePendingBadge();",
            "updateConnectionIndicator();",
            "if (replayRunning) return;",
            "if (shorter) refreshCurrentList();",
            "else showQueuedChanges();",
        ):
            assert call in follows

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
        assert "QueueRules.queuedAdds(waitingChanges(), currentListId)" in js
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


class TestCalendarViewIsRemembered:
    """The page opens on the view last in use; within the calendar, on
    the Month, Week, Day or Timeline last in use."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def test_calendars_view_is_read_from_the_browser(self):
        js = self._app()
        assert 'var CAL_VIEW_KEY = "pytodo_cal_view";' in js
        assert "var calSubView = localStorage.getItem(CAL_VIEW_KEY);" in js

    def test_a_stored_value_that_is_not_a_view_gives_the_month(self):
        js = self._app()
        assert 'var CAL_VIEWS = ["month", "week", "day", "timeline"];' in js
        assert 'if (CAL_VIEWS.indexOf(calSubView) === -1) calSubView = "month";' in js

    def test_choosing_a_tab_stores_it(self):
        js = self._app()
        start = js.index("  calTabs.forEach(function (tab) {")
        tabs = js[start : js.index("\n  });\n", start)]
        assert "localStorage.setItem(CAL_VIEW_KEY, calSubView);" in tabs

    def test_the_tab_of_the_view_in_use_is_marked_when_the_page_loads(self):
        """The page's markup marks the Month."""
        js = self._app()
        start = js.index("  calTabs.forEach(function (tab) {")
        tabs = js[start : js.index("\n  });\n", start)]
        assert 'tab.classList.toggle("active", tab.dataset.cal === calSubView);' in tabs
        assert tabs.index("tab.dataset.cal === calSubView") < tabs.index(
            'tab.addEventListener("click"'
        )

    def test_every_tab_of_the_page_is_a_view_that_can_be_stored(self):
        import re

        html = (STATIC_DIR / "index.html").read_text()
        tabs = re.findall(r'class="cal-tab[^"]*" data-cal="([a-z]+)"', html)
        assert tabs == ["month", "week", "day", "timeline"]


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

    def test_today_is_tinted_over_the_cells_own_color(self):
        """The translucent tint alone let the grid's border color
        through, and today was a gray block."""
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
        fit_both = self._function("_fitCalendar")
        assert "_fitWeekList();" in fit_both
        assert "_fitHourGrid();" in fit_both
        assert 'window.addEventListener("resize", _fitCalendar);' in js

    def test_calendar_is_fitted_again_when_what_is_above_it_changes_height(self):
        """The install banner is shown half a second after the page
        loads, and the offline banner comes and goes with the
        connection. Each moves the calendar down or up by its own
        height; the part that scrolls is given the new room down to the
        bottom bar."""
        import re

        js = self._app()
        assert "var calendarMoved = new ResizeObserver(_fitCalendar);" in js
        start = js.index("var _ABOVE_THE_CALENDAR = [")
        watched = re.findall(r'"([^"]+)"', js[start : js.index("];", start)])
        assert watched == [
            "#offline-banner",
            "#install-banner",
            "#header",
            "#calendar-view .cal-toolbar",
        ]
        observing = js[js.index("var calendarMoved") :]
        observing = observing[: observing.index("\n  }\n")]
        assert "_ABOVE_THE_CALENDAR.forEach(function (selector) {" in observing
        assert "if (el) calendarMoved.observe(el);" in observing

    def test_every_element_watched_above_the_calendar_is_in_the_page(self):
        """In the order of the page: each of them lies above the
        calendar's container."""
        html = (STATIC_DIR / "index.html").read_text()
        places = [
            html.index('<div id="offline-banner"'),
            html.index('<div id="install-banner"'),
            html.index('<header id="header">'),
            html.index('<div id="calendar-view"'),
            html.index('<div class="cal-toolbar">'),
            html.index('id="cal-container"'),
        ]
        assert places == sorted(places)

    def test_a_browser_without_resize_observer_keeps_the_page(self):
        js = self._app()
        assert 'if (typeof ResizeObserver === "function") {' in js

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
        """The color variables of the light theme, and of the dark one
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
        def luminance(color: str) -> float:
            def channel(value: int) -> float:
                c = value / 255
                return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

            r, g, b_ = (int(color[i : i + 2], 16) for i in (1, 3, 5))
            return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b_)

        la, lb = luminance(a), luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    def test_both_dark_blocks_set_the_same_colors(self):
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

    def test_text_on_the_accent_color(self):
        """The selected day, today in the week's strip, the active tab.
        White on the dark theme's accent, a light blue, is 2.2:1."""
        for theme, colors in self._themes().items():
            ratio = self._contrast(colors["on-accent"], colors["accent"])
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
        for theme, colors in self._themes().items():
            for what, fg, bg in pairs:
                ratio = self._contrast(colors[fg], colors[bg])
                assert ratio >= 4.5, (theme, what, round(ratio, 2))

    def test_a_day_of_another_month_is_dimmed_by_color_alone(self):
        """Faded as well, its number fell to 2.2:1 in the light theme
        and 2.9:1 in the dark one. It is a button like the others."""
        rule = self._css().split(".cal-mini-day.other .cal-mini-num {")[1].split("}")[0]
        assert "color: var(--text-secondary);" in rule
        assert "opacity" not in rule

    def test_dots_and_task_edges_stand_out_as_graphics(self):
        """WCAG asks 3:1 of a graphic that carries meaning."""
        for theme, colors in self._themes().items():
            for mark in ("normal", "high", "low", "text-secondary"):
                for ground in ("bg", "bg-card"):
                    ratio = self._contrast(colors[mark], colors[ground])
                    assert ratio >= 3.0, (theme, mark, ground, round(ratio, 2))


class TestTextOnFills:
    """Text and icons written on a fill of one of the theme's colors
    reach WCAG AA in both themes. The dark theme's colors are light
    tints; white on them is 1.7:1 to 2.2:1."""

    FILLS = ("accent", "danger", "success", "warning")

    def _css(self) -> str:
        return (STATIC_DIR / "style.css").read_text()

    def _rules(self) -> list[tuple[str, str]]:
        import re

        css = re.sub(r"/\*.*?\*/", "", self._css(), flags=re.S)
        return [
            (" ".join(selector.split()), body)
            for selector, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css)
        ]

    def _themes(self) -> dict[str, dict[str, str]]:
        """Every variable of the light theme, and of the dark one as the
        light theme with the dark block's values over it."""
        import re

        css = self._css()
        variable = re.compile(r"--([a-z-]+):\s*([^;]+);")
        light = dict(variable.findall(css.split(":root {")[1].split("\n}\n")[0]))
        dark_block = css.split(':root[data-theme="dark"] {')[1].split("\n}\n")[0]
        return {"light": light, "dark": {**light, **dict(variable.findall(dark_block))}}

    @staticmethod
    def _rgba(color: str) -> tuple[float, float, float, float]:
        import re

        color = color.strip()
        if color.startswith("#"):
            r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
            return (r, g, b, 1.0)
        parts = [float(v) for v in re.findall(r"[\d.]+", color)]
        return (parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else 1.0)

    @classmethod
    def _over(cls, top: str | tuple, under: str | tuple) -> tuple[float, float, float, float]:
        """One color laid over another that is opaque."""
        t = cls._rgba(top) if isinstance(top, str) else top
        u = cls._rgba(under) if isinstance(under, str) else under
        return (
            t[0] * t[3] + u[0] * (1 - t[3]),
            t[1] * t[3] + u[1] * (1 - t[3]),
            t[2] * t[3] + u[2] * (1 - t[3]),
            1.0,
        )

    @classmethod
    def _contrast(cls, a: str | tuple, b: str | tuple) -> float:
        def luminance(color: str | tuple) -> float:
            rgb = cls._rgba(color) if isinstance(color, str) else color

            def channel(value: float) -> float:
                c = value / 255
                return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

            return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])

        la, lb = luminance(a), luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    def test_each_fill_color_has_a_text_color_that_reaches_aa(self):
        for theme, v in self._themes().items():
            for fill in self.FILLS:
                ratio = self._contrast(v["on-" + fill], v[fill])
                assert ratio >= 4.5, (theme, fill, round(ratio, 2))
            # A pressed or hovered accent button.
            ratio = self._contrast(v["on-accent"], v["accent-hover"])
            assert ratio >= 4.5, (theme, "accent-hover", round(ratio, 2))

    def test_a_rule_that_fills_with_a_theme_color_takes_its_text_from_that_colors_token(self):
        """Every rule of the style sheet. A fill with no text color of
        its own is a mark, or takes the color of what it lies in."""
        import re

        checked = 0
        for selector, body in self._rules():
            fill = re.search(
                r"background(?:-color)?:\s*var\(--(accent|accent-hover|danger|success|warning)\)",
                body,
            )
            color = re.search(r"(?<![-\w])color:\s*([^;]+);", body)
            if not fill or not color:
                continue
            token = "on-accent" if fill.group(1) == "accent-hover" else "on-" + fill.group(1)
            assert color.group(1).strip() == f"var(--{token})", selector
            checked += 1
        assert checked >= 14

    def test_no_rule_writes_white_by_name_or_lays_white_over_a_fill(self):
        """White text is right on the light theme's fills only, and a
        white overlay lightens a fill toward white text."""
        import re

        for selector, body in self._rules():
            if selector.startswith(":root"):
                continue
            assert not re.search(r"(?<![-\w])color:\s*(#fff|#ffffff|white)\s*;", body), selector
            assert not re.search(r"(?<![-\w])color:\s*rgba\(255", body), selector
            assert not re.search(r"background(?:-color)?:\s*rgba\(255,\s*255,\s*255", body), (
                selector
            )

    def test_controls_on_the_accent_color(self):
        """The list picker and the view buttons in the header, the move
        banner's Cancel: their fills go away from the text's color."""
        css = self._css()
        for selector, fill in (
            (".list-picker-btn", "accent-overlay"),
            (".view-toggle", "accent-overlay"),
            (".view-btn.active", "accent-overlay-strong"),
            (".move-banner-cancel", "accent-overlay"),
        ):
            rule = css.split("\n" + selector + " {")[1].split("}")[0]
            assert f"background: var(--{fill});" in rule, selector
        for theme, v in self._themes().items():
            for overlay in ("accent-overlay", "accent-overlay-strong"):
                ground = self._over(v[overlay], v["accent"])
                ratio = self._contrast(v["on-accent"], ground)
                assert ratio >= 4.5, (theme, overlay, round(ratio, 2))
                # The text contrasts more on the overlay than on the accent itself.
                assert ratio > self._contrast(v["on-accent"], v["accent"]), (theme, overlay)

    def test_an_icon_that_is_not_the_selected_one_reaches_3_to_1(self):
        """A graphic. On the accent color, and on the fill the view
        buttons lie on."""
        rule = self._css().split("\n.view-btn {")[1].split("}")[0]
        assert "color: var(--on-accent-dim);" in rule
        for theme, v in self._themes().items():
            for ground in (v["accent"], self._over(v["accent-overlay"], v["accent"])):
                icon = self._over(v["on-accent-dim"], ground)
                ratio = self._contrast(icon, ground)
                assert ratio >= 3.0, (theme, round(ratio, 2))

    def test_small_text_on_the_accent_color_is_not_made_fainter(self):
        """White on the light theme's accent is 4.6:1; at 80% it was
        3.5:1."""
        css = self._css()
        assert "opacity" not in css.split("\n#last-synced {")[1].split("}")[0]
        for selector in ("#install-dismiss", ".undo-btn"):
            rule = css.split("\n" + selector + " {")[1].split("}")[0]
            assert "color: var(--on-accent);" in rule, selector

    def test_connection_dot_has_a_ring_in_the_headers_text_color(self):
        """Its green is 1.6:1 against the dark theme's header."""
        rule = self._css().split("\n.dot {")[1].split("}")[0]
        assert "box-shadow: 0 0 0 1.5px var(--on-accent);" in rule

    def test_a_chip_writes_its_color_darkened_on_a_tint_of_it(self):
        """Written straight on the tint, the light theme's priority and
        recurrence chips were 4.3:1."""
        css = self._css()
        rule = css.split("\n.entity-chip {\n  --chip-ink")[1].split("}")[0]
        assert "background: color-mix(in srgb, var(--chip-ink) 12%, transparent);" in rule
        assert "color: color-mix(in srgb, var(--chip-ink), #000 var(--chip-shade));" in rule
        inks = (
            "entity-date",
            "entity-priority",
            "entity-tag",
            "entity-recurrence",
            "entity-pomodoro",
            "danger",
        )
        for ink in inks:
            assert (
                f"var(--{ink})"
                in css.split("\n.entity-chip {\n  --chip-ink")[1].split(".add-meta-row")[0]
            ), ink
        for theme, v in self._themes().items():
            shade = float(v["chip-shade"].rstrip("%")) / 100
            for ink in inks:
                r, g, b, _ = self._rgba(v[ink])
                text = (r * (1 - shade), g * (1 - shade), b * (1 - shade), 1.0)
                for ground in ("bg", "bg-secondary", "bg-card"):
                    fill = self._over((r, g, b, 0.12), v[ground])
                    ratio = self._contrast(text, fill)
                    assert ratio >= 4.5, (theme, ink, ground, round(ratio, 2))

    def test_selected_row_of_the_list_picker(self):
        """On its tint the secondary color falls to 4.3:1."""
        css = self._css()
        assert (
            ".list-row.active .list-row-stats,\n.list-row.active .list-action-btn {\n  color: var(--text);"
            in css
        )
        for theme, v in self._themes().items():
            r, g, b, _ = self._rgba(v["accent"])
            for ground in ("bg", "bg-card"):
                row = self._over((r, g, b, 0.15), v[ground])
                ratio = self._contrast(v["text"], row)
                assert ratio >= 4.5, (theme, ground, round(ratio, 2))

    def test_board_cards_grip_is_not_faded(self):
        """A control; at half strength its glyph was 2:1."""
        rule = self._css().split("\n.board-card-grip {")[1].split("}")[0]
        assert "color: var(--text-secondary);" in rule
        assert "opacity" not in rule


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
    def _luminance(color: str) -> float:
        """WCAG relative luminance of a #rrggbb color."""

        def channel(value: int) -> float:
            c = value / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    def test_a_label_is_black_or_white_whichever_the_fill_sets_off(self):
        """The page's own text color is chosen for the page's
        background. On the dark theme's bars it measured 1.1:1 to 2.1:1,
        and on four of the light theme's six, under 4.5:1."""
        body = self._function("_barTextColor")
        assert "var onWhite = 1.05 / (lum + 0.05);" in body
        assert "var onBlack = (lum + 0.05) / 0.05;" in body
        assert 'return onWhite >= onBlack ? "#ffffff" : "#000000";' in body
        luminance = self._function("_luminance")
        assert "return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];" in luminance
        assert "c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)" in luminance

    def test_every_bar_color_of_both_themes_gives_its_label_aa_contrast(self):
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

    def test_no_label_on_a_bar_uses_the_pages_text_color(self):
        for name in ("_paintHourBar", "_paintAllDayChip", "_paintMarkerChip"):
            body = self._function(name)
            assert '_themeColor("text"' not in body, name
            assert 'ctx.fillStyle = "#ffffff";' not in body, name
            assert "_paintLabelOn(ctx, text," in body, name

    def test_a_bars_label_is_written_on_the_bars_color(self):
        """The label's color is chosen for the fill it is written on,
        and written inside that fill only. A deviation zone is hatched
        over the bar's color and not behind the label, so the label is
        on one color."""
        bar = self._function("_paintHourBar")
        assert "fill: base," in bar
        assert "fill: deviation" not in bar
        assert "if (labeled) zoneTop = Math.max(zoneTop, y + _BAR_LABEL_BAND);" in bar
        label = self._function("_paintLabelOn")
        assert (
            label.index("ctx.rect(zone.x, zone.y, zone.w, zone.h);")
            < label.index("ctx.clip();")
            < label.index("ctx.fillStyle = _barTextColor(zone.fill);")
            < label.index("ctx.fillText(text, tx, ty);")
        )

    def test_the_zone_of_a_completed_bar_is_drawn_from_the_servers_minutes(self):
        """What is drawn for a bar and its zone: tests/js/hour_bar.test.js,
        run under Node."""
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node.js is not installed")
        result = subprocess.run(
            [node, "--test", str(Path(__file__).parent / "js" / "hour_bar.test.js")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_bars_that_share_hours_stand_side_by_side(self):
        """Where the bars of a day go across its column, and the block
        for those a Week's column has no lane for:
        tests/js/day_lanes.test.js, run under Node."""
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node.js is not installed")
        result = subprocess.run(
            [node, "--test", str(Path(__file__).parent / "js" / "day_lanes.test.js")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_hours_are_painted_from_the_lanes(self):
        """Every bar of a day was painted at the column's full width,
        one over the other (#88). The hours are painted from where
        `_placeDayBars` puts each bar; the page works out no lane of
        its own, it takes the server's."""
        hours = "".join(self._function("_paintHoursZone").split())
        assert "_placeDayBars(known,colX,colWidth)" in hours
        assert "colWidth-4" not in hours
        place = self._function("_placeDayBars")
        assert "seg.lane" in place
        assert "seg.lanes" in place

    def test_the_day_is_as_wide_as_its_lanes_and_the_week_is_not(self):
        """The Day gives every bar a lane and grows wider than the
        screen for them; the Week keeps its width."""
        paint = "".join(self._function("_paintPinnedAndHours").split())
        assert (
            "if(days===1){W=Math.max(W,_HOUR_LABEL_WIDTH+_widthForLanes(_mostLanes(data)));}"
            in (paint)
        )

    def test_a_grid_wider_than_the_screen_moves_as_one(self):
        """The hours are in a box of their own that scrolls up and
        down. Left to the width of the frame, that box scrolled the
        hours sideways by themselves, and the header above stood
        still: it is as wide as the hours, and the frame moves both."""
        css = (STATIC_DIR / "style.css").read_text()
        rule = css.split(".cal-hour-grid-scroll {")[1].split("}")[0]
        assert "min-width: max-content;" in rule
        frame = css.split(".cal-hour-grid-wrap {")[1].split("}")[0]
        assert "overflow-x: auto;" in frame

    def test_a_tap_on_the_count_opens_the_day(self):
        """The block that stands for bars without a lane has a day
        where a bar has a task."""
        click = "".join(self._function("_installHourGridClickHandler").split())
        assert "if(r.day)_openCalendarDay(r.day);" in click
        opened = self._function("_openCalendarDay")
        assert 'calSubView = "day";' in opened
        assert "localStorage.setItem(CAL_VIEW_KEY, calSubView);" in opened
        assert "renderCalendar();" in opened

    def test_the_page_works_no_zone_out_for_itself(self):
        """The layout decides where a zone is. The page split an early
        bar's width by the share of its window that was used, whatever
        the time, and drew no late zone."""
        bar = self._function("_paintHourBar")
        for own_arithmetic in ("bar_origin_ms", "bar_end_ms", "completed_at", "splitX"):
            assert own_arithmetic not in bar, own_arithmetic
        assert "seg.zone_start_minute" in bar
        assert "seg.zone_end_minute" in bar

    def test_the_gantt_chart_hatches_a_zone_over_its_bar(self):
        """As the Week and the Day draw it: the zone's color alone is
        pale on the page in one theme and dark on it in the other."""
        chart = (
            self._app().split('_chartCanvas("Tasks / Gantt"')[1].split("return ch.container;")[1]
        )
        # Read without white space or the comma before a closing
        # bracket: where a call is broken over lines is the formatter's.
        calls = "".join(chart.split()).replace(",)", ")")
        assert "_paintHatch(ctx,xMidE,y,xEnd-xMidE,barH,colors.deviation,false);" in calls
        assert "_paintHatch(ctx,xEnd,y,xOverflow-xEnd,barH,colors.deviation,true);" in calls
        assert "ctx.fillStyle=colors.deviation;" not in calls

    def test_hours_scroll_in_the_room_above_the_bottom_bar(self):
        """The page, with the toolbar, stays in place."""
        fit = self._function("_fitHourGrid")
        assert "var room = _roomAboveBottomBar(wrap);" in fit
        assert 'wrap.style.maxHeight = room < _WEEK_LIST_MIN_HEIGHT ? "" : room + "px";' in fit
        assert "_fitHourGrid();" in self._function("_buildHourGrid")


class TestCalendarShowsTheChosenList:
    """All four of the calendar's views are about the list chosen in the
    header. The Week and the Day asked the server for the bars of every
    list, and a bar of another list could not be opened: the item sheet
    knows the chosen list's tasks only."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _function(self, name: str) -> str:
        return self._app().split(f"function {name}(")[1].split("\n  }\n")[0]

    def test_hour_grid_asks_for_the_chosen_lists_bars(self):
        assert '_listQuery("&"),' in self._function("_fetchSegments")
        query = self._function("_listQuery")
        assert '? lead + "list_id=" + encodeURIComponent(currentListId)' in query
        assert ': "";' in query

    def test_another_list_chosen_puts_a_new_grid_on_screen(self):
        """The grid on screen is known by its days and its list."""
        key = self._function("_hourGridKey")
        assert 'return _dayKey(startDate) + "/" + days + "/" + (currentListId || "");' in key
        assert "range: _hourGridKey(startDate, days)," in self._function("_renderHourGrid")
        refresh = self._function("_refreshHourGrid")
        assert "var key = _hourGridKey(range.start, range.days);" in refresh
        assert refresh.index("if (key !== hourGridShown.range) {") < refresh.index(
            "_fetchSegments("
        )

    def test_timelines_figures_are_the_chosen_lists(self):
        js = self._app()
        for path in ("completion_timing", "slip_rate", "cycle_time"):
            assert f'api("/analytics/{path}" + _listQuery("?"))' in js, path

    def test_a_task_that_cannot_be_opened_says_so(self):
        """Saying nothing left a tap without effect, and the address in
        place: a second tap on the same task changed nothing at all."""
        body = self._function("openDetailSheet")
        missing = body.split("if (!item) {")[1].split("return;")[0]
        assert 'if (location.hash.startsWith("#/item/")) location.hash = "#/";' in missing
        assert 'showToast("That task is not in this list");' in missing


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
        assert "await queueChange(path, opts, step);" in self._function("sendOrQueue")
        body = self._function("queueChange")
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
        assert "return takeBackQueuedStep(step);" in body
        assert body.index("if (takenBack) {") < body.index('showToast(name + " restored");')

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


class TestPageTakesUpTheServersVersion:
    """A page left open hears, each time it connects, which version of
    the page the server serves, and takes up one that is not its own.
    Loaded from the service worker's store while the server was down,
    and left in view, it otherwise went on running the old page against
    the new server."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _function(self, name: str) -> str:
        return self._app().split(f"function {name}(")[1].split("\n  }\n")[0]

    @pytest.mark.asyncio
    async def test_served_page_carries_its_version(self):
        from pytodo_qt.web.server import static_asset_version

        client = await _make_client()
        async with client:
            resp = await client.get("/")
            text = await resp.text()
            assert resp.content_type == "text/html"
        assert f'<meta name="page-version" content="{static_asset_version()}" />' in text
        assert "__ASSET_VERSION__" not in text

    def test_page_reads_its_version_from_itself(self):
        """Not from the server's answer: a page out of the worker's
        store is older than the server it then connects to."""
        html = (STATIC_DIR / "index.html").read_text()
        assert '<meta name="page-version" content="__ASSET_VERSION__" />' in html
        js = self._app()
        assert "document.querySelector('meta[name=\"page-version\"]')" in js
        # A page served without the version put in has none.
        assert 'return version.indexOf("__") === 0 ? "" : version;' in js

    def test_the_sockets_greeting_reaches_the_check(self):
        js = self._app()
        assert '} else if (msg.event === "hello") {' in js
        assert "onServerPageVersion(msg.page_version);" in js

    def test_the_same_version_or_none_changes_nothing(self):
        body = self._function("onServerPageVersion")
        assert "if (!version || !PAGE_VERSION || version === PAGE_VERSION) return;" in body

    def test_page_loads_itself_again_once_for_a_version(self):
        """A version it cannot take up, a worker that fails to install,
        must not make it reload without end."""
        body = self._function("onServerPageVersion")
        assert (
            body.index("if (sessionStorage.getItem(PAGE_RELOAD_KEY) === version) return;")
            < body.index("sessionStorage.setItem(PAGE_RELOAD_KEY, version);")
            < body.index(".then(reloadForUpdateWhenIdle);")
        )

    def test_the_worker_fetches_the_new_version_before_the_page_reloads(self):
        """Reloaded sooner, the page would come from the old worker's
        store again."""
        body = self._function("onServerPageVersion")
        assert "navigator.serviceWorker.getRegistration()" in body
        assert body.index(".update()") < body.index("return workerSettled(registration);")
        settled = self._function("workerSettled")
        assert "var worker = registration.installing || registration.waiting;" in settled
        assert 'worker.state === "activated" || worker.state === "redundant"' in settled

    def test_the_reload_waits_for_nothing_to_be_open(self):
        body = self._function("reloadForUpdateWhenIdle")
        assert "if (!pageIsIdle()) return;" in body


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


class TestServerNotReached:
    """The page took the browser's word for whether it was connected: a
    device with a network was "online", although the server did not
    answer and the page showed what the service worker had stored
    (#72). It now goes by the server's own answers, and says when it
    has none."""

    def _app(self) -> str:
        return (STATIC_DIR / "app.js").read_text()

    def _node(self, name: str) -> None:
        node = shutil.which("node")
        if node is None:
            pytest.skip("Node.js is not installed")
        result = subprocess.run(
            [node, "--test", str(Path(__file__).parent / "js" / name)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_worker_marks_what_it_takes_from_its_store(self):
        """tests/js/service_worker.test.js, run under Node."""
        self._node("service_worker.test.js")

    def test_the_page_goes_by_the_servers_answers(self):
        """tests/js/connection.test.js, run under Node."""
        self._node("connection.test.js")

    def test_one_copy_of_the_page_sends_the_queue_at_a_time(self):
        """tests/js/queue_send.test.js, run under Node (#78)."""
        self._node("queue_send.test.js")

    def test_every_task_the_page_adds_has_an_id_of_its_making(self):
        """The add sheet and "Add subtask": the server creates a task of
        an id once, however often its add is delivered (#117)."""
        js = self._app()
        adds = re.findall(r'"/lists/" \+ \w+ \+ "/items"', js)
        assert len(adds) == 2
        assert js.count("id: newItemId(),") == 2
        sheet = js.split("// Sent or queued as any added task is, with an id of its own.")[1]
        sheet = sheet.split("addSubInput.addEventListener")[0]
        assert "await sendOrQueue(" in sheet
        assert "parent_id: itemId," in sheet

    def test_only_changes_that_wait_are_shown_and_counted(self):
        """A change the server answers at once is in the queue for a
        moment only: what the page draws and counts is read through
        waitingChanges, never from the queue itself."""
        js = self._app()
        for name in (
            "showQueuedChanges",
            "updatePendingBadge",
            "updateConnectionIndicator",
            "renderItems",
            "refreshBoard",
            "refreshSettings",
        ):
            body = re.split(rf"(?:async )?function {name}\(", js)[1].split("\n  }\n")[0]
            assert "getOfflineQueue()" not in body, name
            assert "waitingChanges()" in body, name

    def test_the_queue_is_stored_twice(self):
        """tests/js/queue_copies.test.js, run under Node (#77)."""
        self._node("queue_copies.test.js")

    def test_one_place_reads_the_queue_and_one_writes_it(self):
        """The copy in IndexedDB follows every write of the queue only
        because every write goes through storeQueue."""
        js = self._app()
        assert js.count("localStorage.setItem(OFFLINE_QUEUE_KEY") == 2
        for name in ("storeQueue", "settleQueueCopies"):
            body = js.split("function " + name + "(")[1].split("\n  }\n")[0]
            assert "localStorage.setItem(OFFLINE_QUEUE_KEY" in body
            assert "localStorage.setItem(QUEUE_COUNTER_KEY" in body
        assert js.count("localStorage.getItem(OFFLINE_QUEUE_KEY") == 1

    def test_the_queue_is_settled_before_the_page_starts(self):
        js = self._app()
        start = js.split("async function startPage() {")[1].split("\n  }\n")[0]
        assert start.lstrip().startswith("await restoreQueue();")

    def test_every_request_of_the_page_is_noted(self):
        """One place calls the browser's fetch: serverFetch, which notes
        what the outcome says of the server."""
        js = self._app()
        calls = re.findall(r"(?<![A-Za-z.])fetch\(", js)
        assert len(calls) == 1
        noted = js.split("async function serverFetch(")[1].split("\n  }\n")[0]
        assert "await fetch(url, opts)" in noted

    def test_the_worker_and_the_page_agree_on_the_mark(self):
        js = self._app()
        sw = (STATIC_DIR / "sw.js").read_text()
        for name in ("SOURCE_HEADER", "STORED_AT_HEADER"):
            in_page = re.search(rf'var {name} = "([^"]+)";', js)
            in_worker = re.search(rf'var {name} = "([^"]+)";', sw)
            assert in_page and in_worker
            assert in_page.group(1) == in_worker.group(1)

    def test_a_network_is_not_taken_for_the_server(self):
        """The browser's "online" event starts another try; it does not
        set the state."""
        js = self._app()
        assert "updateOnlineStatus" not in js
        handler = js.split('window.addEventListener("online", function () {')[1].split("\n  });\n")[
            0
        ]
        assert "serverConnected" not in handler
        assert "serverAnswered" not in handler
        assert "probeServer();" in handler

    def test_the_start_goes_on_from_the_state_it_finds(self):
        js = self._app()
        start = js.split("async function init() {")[1].split("\n  }\n")[0]
        assert "navigator.onLine" not in start
        assert "if (serverConnected) {" in start
        assert "waitForServer();" in start

    def test_tasks_from_the_store_are_not_counted_as_synced(self):
        js = self._app()
        refresh = js.split("async function refreshCurrentList() {")[1].split("\n  }\n")[0]
        assert "if (fromServer) markSynced();" in refresh
        assert "if (fromServer) cacheListItems(currentListId, serverItems);" in refresh
        assert "setDataSavedAt(answer.savedAt);" in refresh

    def test_a_socket_closed_on_purpose_is_not_tried_again(self):
        js = self._app()
        close = js.split("function disconnectWebSocket() {")[1].split("\n  }\n")[0]
        assert close.index("ws.onclose = null;") < close.index("ws.close();")

    def test_the_notice_is_text_alone(self):
        """Nothing in it to press: the page cannot mend what keeps it
        from the server, and tries the server again by itself."""
        html = (STATIC_DIR / "index.html").read_text()
        notice = html.split('<div id="offline-banner"')[1].split("</div>")[0]
        assert 'role="status"' in notice
        assert 'id="offline-banner-text"' in notice
        assert "<a" not in notice
        assert "<button" not in notice

    def test_a_read_has_a_deadline_and_a_change_has_none(self):
        """A server that went away without closing its connections
        leaves a request waiting for a minute and more. Giving up a
        change says nothing of whether the server made it."""
        js = self._app()
        assert "var READ_DEADLINE = 10000;" in js
        assert "var PROBE_DEADLINE = 5000;" in js
        noted = js.split("async function serverFetch(")[1].split("\n  }\n")[0]
        # A change has a deadline only where one is passed: signing in,
        # where the person waits at the button.
        assert 'if ((method === "GET" || deadline) && !(opts && opts.signal)) {' in noted
        assert "var SIGN_IN_DEADLINE = 10000;" in js
        probe = js.split("function probeServer() {")[1].split("\n  }\n")[0]
        assert "PROBE_DEADLINE" in probe

    def test_an_open_socket_is_asked_whether_the_server_is_there(self):
        """An open WebSocket is not taken for a server that answers."""
        js = self._app()
        assert "var WS_PING_INTERVAL = 5000;" in js
        assert "var WS_PONG_DEADLINE = 3000;" in js
        assert "var WS_CONNECT_DEADLINE = 10000;" in js
        connect = js.split("function connectWebSocket() {")[1].split("\n  function ")[0]
        opened = connect.split("socket.onopen = function () {")[1].split("};")[0]
        assert "waitToPing();" in opened
        heard = connect.split("socket.onmessage = function (e) {")[1].split("try {")[0]
        # Anything the server says is an answer.
        assert "serverAnswered();" in heard
        assert "waitToPing();" in heard
        # A socket that does not open in time is closed, and tried again.
        assert "WebSocket.CONNECTING) socket.close();" in connect

    def test_the_server_is_not_asked_while_the_page_is_out_of_view(self):
        """The browser holds a hidden page's timers back; a late one
        would pass for a server that does not answer. It is asked at
        once when the page comes back into view."""
        js = self._app()
        seen = js.split("function pageViewChanged() {")[1].split("\n  }\n")[0]
        hidden, shown = seen.split("} else {", 1)
        assert "stopPinging();" in hidden
        assert "pingServer();" in shown

    def test_nothing_is_read_at_intervals_behind_the_pin_screen(self):
        js = self._app()
        polling = js.split("function startPolling() {")[1].split("\n  }\n")[0]
        assert polling.index("if (pinScreenUp) return;") < polling.index("setInterval(")
        online = js.split('window.addEventListener("online", function () {')[1].split("\n  });\n")[
            0
        ]
        assert online.index("if (pinScreenUp) return;") < online.index("connectWebSocket();")

    def test_a_second_start_adds_no_second_clock(self):
        """The page starts again after each sign-in."""
        js = self._app()
        start = js.split("async function init() {")[1].split("\n  }\n")[0]
        assert "if (lastSyncedTimer === null) {" in start
        assert start.count("setInterval(") == 1

    def test_no_request_is_left_to_the_browser_while_the_server_is_silent(self):
        """A request the page cannot give up waits a minute and more by
        a name whose address does not answer, and holds one of the few
        connections the browser makes to the server (#116)."""
        js = self._app()
        seen = js.split('.register("/sw.js")')[1].split(".catch(function (err)")[0]
        assert 'document.visibilityState === "visible" && serverConnected' in seen
        # The browser asks for /favicon.ico where the page names no icon;
        # the one named is among the files the service worker has stored.
        html = (STATIC_DIR / "index.html").read_text()
        assert '<link rel="icon" href="/static/icon-192.png" />' in html
        sw = (STATIC_DIR / "sw.js").read_text()
        assert '"/static/icon-192.png",' in sw.split("var STATIC_ASSETS = [")[1].split("];")[0]

    def test_the_view_handler_is_the_one_the_browser_calls(self):
        js = self._app()
        assert 'document.addEventListener("visibilitychange", pageViewChanged);' in js

    def test_the_start_is_run(self):
        """tests/js/connection.test.js runs startPage by name."""
        js = self._app()
        assert js.rstrip().endswith("  startPage();\n})();")

    def test_the_server_is_tried_again_for_as_long_as_it_is_silent(self):
        """Whatever becomes of the WebSocket: one that hangs while it
        connects starts no further try by itself."""
        js = self._app()
        again = js.split("function scheduleReconnect() {")[1].split("\n  }\n")[0]
        silent = again.split("if (!serverConnected) {")[1].split("}")[0]
        assert "probeServer();" in silent
        assert "scheduleReconnect();" in silent

    def test_the_server_answers_no_address_for_checking(self):
        """The link that opened the server in another tab is gone, and
        the address it opened with it."""
        from pytodo_qt.web import api

        assert "check-connection" not in (STATIC_DIR / "index.html").read_text()
        assert "check-connection" not in (STATIC_DIR / "style.css").read_text()
        assert "check-connection" not in self._app()
        assert "check-connection" not in Path(api.__file__).read_text()


# ===========================================================================
# Package data tests
# ===========================================================================


class TestPackageData:
    def test_pyproject_includes_json(self):
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject_path.read_text()
        assert "*.json" in content
