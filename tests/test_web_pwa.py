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
        assert 'if (calSubView === "week" || calSubView === "day") {' in body
        assert "_refreshHourGrid();" in body
        grid = self._function("_refreshHourGrid")
        assert (
            grid.index("_fetchSegments(range.start, range.days)")
            < grid.index("if (answer === hourGridShown.answer) return;")
            < grid.index("_buildHourGrid();")
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
