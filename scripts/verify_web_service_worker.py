"""Manual verification harness for the web page's service worker.

Serves the real web page from a throwaway in-memory database and a
temporary copy of the page's files, and walks through what the service
worker is for: storing the page, showing it while the server cannot be
reached, and picking up a new version of the page by itself. Nothing is
saved, and the application's own files are not changed. The copy of
app.js gains a few lines that tell this script whether the browser took
the service worker, and the script prints the answer.

A browser registers a service worker only over HTTPS and only when it
trusts the server's certificate, so the page is served with the
certificate the application's web server already uses, and the check is
for a device that trusts the application's web interface. The
certificate and its key are only read. Anyone on the network can open
the throwaway page while the script runs.

This is **not** part of the pytest suite and **not** CI-gated — it
requires a human watching the screen.

Run from the repo root:

    uv run python scripts/verify_web_service_worker.py

and follow the steps it prints. Each step ends by pressing Enter in the
terminal, which changes what the server does: it stops, comes back with
a changed page, and changes the page once more.

A stopped server refuses a connection at once. Away from the network
the server is on, a request waits before it fails; that case is not
covered here.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_web_advance_reminder import application_certificate  # noqa: E402

from pytodo_qt.core.models import Database, create_todo_item, create_todo_list  # noqa: E402
from pytodo_qt.web import server as web_server  # noqa: E402
from pytodo_qt.web.server import WebServer, static_asset_version  # noqa: E402

# A label drawn over the page, added to the copy of style.css to stand
# for a new version of the page.
_LABEL_CSS = """
body::after {{
  content: "{text}";
  position: fixed;
  top: 0;
  right: 0;
  z-index: 99999;
  padding: 3px 10px;
  background: {colour};
  color: #fff;
  font: 600 13px sans-serif;
}}
"""

ADDRESS_NOTES = """\
  Type the address in full, with https:// in front. Without it the
  browser asks over plain HTTP, the server does not answer, and the
  browser reports an empty response (ERR_EMPTY_RESPONSE in Chrome).

  If the browser warns about the certificate, the device does not trust
  the application's web interface, and no service worker will register
  there: the page opens, but none of the steps below can pass. The
  application's Web Connect dialog has the steps for installing the
  certificate on a device."""

# Added to the copy of app.js: tells this script whether the browser took
# the service worker, so the answer does not depend on the browser's
# developer tools.
REPORT_JS = """
(function () {
  function report(state) {
    fetch("/check/worker?state=" + encodeURIComponent(state)).catch(function () {});
  }
  if (!navigator.serviceWorker) {
    report("not available in this browser for this page");
    return;
  }
  navigator.serviceWorker.register("/sw.js").catch(function (err) {
    report("refused: " + err.message);
  });
  navigator.serviceWorker.ready.then(function () {
    report("installed and active");
  });
})();
"""

STEP_1 = """\
Step 1: the page is stored.

  Open the address above on the phone or tablet.
  - The page shows three tasks.
  - Below, this terminal lists the page's files as they are fetched,
    then prints one of:
      Service worker on the device: installed and active
      Service worker on the device: refused: <the browser's reason>
  - When installed, the files are listed a second time: that is the
    service worker storing them. The second list includes
    "fetched /static/icon-512.png". (Chrome on Android fetches
    icon-192.png by itself; that line alone is not the worker.)
  - When refused, the steps below cannot pass on that device.

  Press Enter when "installed and active" has appeared."""

STEP_2 = """\
Step 2: the page opens without the server. The server is now stopped.

  Close the page (or the browser tab) and open the same address again.
  - The page appears, with the three tasks.
  Optional: tick a task. A red count appears on "More": the change is
  kept on the device, and is sent in step 3.

  The page shows no offline notice here, because the device itself is
  still online. In airplane mode the page opens in the same way and
  shows the notice.

  Press Enter to start the server again."""

STEP_3 = """\
Step 3: a new version arrives. The server is running again, and the
page it serves now has a green label, UPDATED, in the top right corner.

  Close the page and open the same address again.
  - The page appears as before, without the label.
  - Within a few seconds it reloads by itself and shows the label.
  - If a task was ticked in step 2, "Stored now" below shows it done.

  Press Enter when the label is showing."""

STEP_4 = """\
Step 4: a new version waits for an open task. Do this in order.

  1. Open a task, and leave its sheet open.
  2. Press Enter here. The page's label changes to an orange UPDATED
     AGAIN on the server.
  3. Switch to another app and back to the page.
     - Nothing happens while the sheet is open, however long it is left.
  4. Close the sheet.
     - Within a few seconds the page reloads and shows the orange label.

  Press Enter now, with the sheet open."""

STEP_5 = """\
  The page has changed on the server. Continue with 3 and 4 above.

  Press Enter to stop."""


def build_database() -> Database:
    today = date.today()
    db = Database()
    lst = create_todo_list("Service worker")
    for number, title in enumerate(("First task", "Second task", "Third task"), start=1):
        lst.add_item(create_todo_item(title, due_date=today + timedelta(days=number)))
    db.add_list(lst)
    db.set_active_list(lst.id)
    return db


@web.middleware
async def print_page_files(request: web.Request, handler: Any) -> web.StreamResponse:
    """Print each request for one of the page's files."""
    response = await handler(request)
    if not request.path.startswith(("/api/", "/check/")) and request.path != "/ws":
        print(f"    fetched {request.path}", flush=True)
    return response


_last_report = ""


async def worker_report(request: web.Request) -> web.Response:
    """Print what the page says about its service worker, when it changes."""
    global _last_report
    state = request.query.get("state", "")[:200]
    if state != _last_report:
        _last_report = state
        print(f"  Service worker on the device: {state}", flush=True)
    return web.Response(status=204)


def describe(db: Database) -> list[str]:
    return [
        f"  {item.reminder:<14} {'done' if item.complete else 'not done'}"
        for lst in db.lists.values()
        for item in lst.active_items()
    ]


async def start(db: Database, port: int) -> web.AppRunner:
    app = WebServer(database=db).create_app()
    app.middlewares.append(print_page_files)
    app.router.add_get("/check/worker", worker_report)
    # No access log, so the steps stay readable; a short shutdown, so an
    # open WebSocket does not hold the server up when it is stopped.
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=1.0)
    await runner.setup()
    context, _ = application_certificate()
    await web.TCPSite(runner, "0.0.0.0", port, ssl_context=context).start()
    return runner


async def enter(text: str) -> None:
    print(f"\n{text}\n", flush=True)
    await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)


def label(static_dir: Path, original_css: str, text: str, colour: str) -> None:
    (static_dir / "style.css").write_text(
        original_css + _LABEL_CSS.format(text=text, colour=colour), encoding="utf-8"
    )
    print(f"  Page version on the server: {static_asset_version()}", flush=True)


async def watch(db: Database) -> None:
    last: list[str] = []
    while True:
        current = describe(db)
        if current != last:
            print("Stored now:\n" + "\n".join(current), flush=True)
            last = current
        await asyncio.sleep(0.5)


async def serve(port: int, static_dir: Path) -> None:
    db = build_database()
    original_css = (static_dir / "style.css").read_text(encoding="utf-8")
    _, hosts = application_certificate()

    runner = await start(db, port)
    watcher = asyncio.create_task(watch(db))
    try:
        print("\nOn a phone or tablet on the same network, either of:")
        for name in hosts:
            print(f"  https://{name}:{port}/")
        print(ADDRESS_NOTES)
        print(f"  Page version on the server: {static_asset_version()}")
        await enter(STEP_1)

        await runner.cleanup()
        await enter(STEP_2)

        label(static_dir, original_css, "UPDATED", "#2e7d32")
        runner = await start(db, port)
        await enter(STEP_3)

        await enter(STEP_4)
        label(static_dir, original_css, "UPDATED AGAIN", "#e65100")
        await enter(STEP_5)
    finally:
        watcher.cancel()
        await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the web page for a service worker check.")
    parser.add_argument("--port", type=int, default=8770, help="port to serve HTTPS on")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as temporary:
        static_dir = Path(temporary) / "static"
        shutil.copytree(web_server._STATIC_DIR, static_dir)
        with (static_dir / "app.js").open("a", encoding="utf-8") as script:
            script.write(REPORT_JS)
        web_server._STATIC_DIR = static_dir
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(serve(args.port, static_dir))
    print("\nStopped.")


if __name__ == "__main__":
    main()
