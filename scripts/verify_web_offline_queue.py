"""Manual verification harness for changes made in the web page while
the server cannot be reached.

Serves the real web page from a throwaway in-memory database, stops the
server, and walks through the changes the page keeps for sending later:
a tick, a second tick on the same task, a priority, a delete, and a task
added. Each is shown in the page at once and after the page is opened
again, marked "Not sent", and is sent when the server is started again.
Nothing is saved, and the application's own files are not changed.

The page opens without the server only where a service worker is in
place, which needs HTTPS and a device that trusts the application's web
certificate; the page is served with that certificate, which is only
read. Anyone on the network can open the throwaway page while the script
runs.

This is **not** part of the pytest suite and **not** CI-gated — it
requires a human watching the screen.

Run from the repo root:

    uv run python scripts/verify_web_offline_queue.py

and follow the steps it prints. Each step ends by pressing Enter in the
terminal: the server stops after the first, and starts again after the
third.

With --trace the page also records what it does: each time it stores its
queue of changes and which of its functions did so, each request it
sends and the answer, each tap on a button, each notice it shows, and
when it is opened, hidden or closed. The records are kept on the device
and sent when the server can be reached; together with the requests the
server received they are written, in order of time, to a file whose path
is printed. The file is for finding out what happened when a step does
not go as described.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_web_advance_reminder import application_certificate  # noqa: E402
from verify_web_service_worker import ADDRESS_NOTES, REPORT_JS, worker_report  # noqa: E402

from pytodo_qt.core.models import Database, create_todo_item, create_todo_list  # noqa: E402
from pytodo_qt.web import server as web_server  # noqa: E402
from pytodo_qt.web.server import WebServer  # noqa: E402

# In list order: each is due a day after the one before.
TASKS = (
    "1 Tick me",
    "2 Tick me twice",
    "3 Change my priority",
    "4 Delete me",
    "5 Leave me alone",
)

PRIORITIES = {1: "high", 2: "normal", 3: "low"}

# Added in front of the copy of app.js with --trace: records what the page
# does, keeps the records on the device, and sends them to this script
# whenever the server answers.
TRACE_JS = r"""
(function () {
  "use strict";
  var KEY = "pytodo_offline_queue";
  var page = Math.random().toString(36).slice(2, 6);
  var count = 0;
  var realFetch = window.fetch.bind(window);
  var held = [];
  var database = null;
  var sending = false;

  function short(text) {
    return String(text).replace(/([0-9a-f]{4})[0-9a-f]{4}-[0-9a-f-]{27}/g, "$1");
  }

  function queueText(stored) {
    var queue;
    try {
      queue = JSON.parse(stored || "[]");
    } catch (e) {
      return "unreadable";
    }
    if (!queue.length) return "(0)";
    return (
      "(" + queue.length + ") " +
      queue.map(function (change) {
        return ((change.opts && change.opts.method) || "?") + " " + short(change.path);
      }).join(", ")
    );
  }

  function callers() {
    var names = [];
    String(new Error().stack || "").split("\n").forEach(function (line) {
      var found =
        /^\s*at (?:async )?(?:Object\.|Storage\.)?([A-Za-z_$][\w$]*)/.exec(line) ||
        /^(?:async\*)?([A-Za-z_$][\w$]*)@/.exec(line);
      if (found && ["callers", "setItem", "note", "Error"].indexOf(found[1]) === -1) {
        names.push(found[1]);
      }
    });
    return names.slice(0, 5).join(" < ") || "?";
  }

  function note(what, detail) {
    count += 1;
    var record = {
      id: page + "-" + count,
      page: page,
      n: count,
      at: Date.now(),
      what: what + (detail ? ": " + detail : "") + (document.hidden ? " [hidden]" : ""),
    };
    if (database) put(record);
    else held.push(record);
  }

  function put(record) {
    try {
      var tx = database.transaction("records", "readwrite");
      tx.objectStore("records").put(record);
      tx.oncomplete = send;
    } catch (e) {
      /* the record is lost */
    }
  }

  function send() {
    if (sending || !database) return;
    sending = true;
    var done = function () {
      sending = false;
    };
    var request;
    try {
      request = database.transaction("records").objectStore("records").getAll();
    } catch (e) {
      done();
      return;
    }
    request.onerror = done;
    request.onsuccess = function () {
      var records = request.result || [];
      if (!records.length) {
        done();
        return;
      }
      realFetch("/check/trace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sent_at: Date.now(), records: records }),
      })
        .then(function (reply) {
          if (!reply.ok) throw new Error("not taken");
          var tx = database.transaction("records", "readwrite");
          records.forEach(function (record) {
            tx.objectStore("records").delete(record.id);
          });
          tx.oncomplete = function () {
            done();
            send();
          };
          tx.onabort = done;
        })
        .catch(done);
    };
  }

  var opening = indexedDB.open("pytodo_check_trace", 1);
  opening.onupgradeneeded = function () {
    opening.result.createObjectStore("records", { keyPath: "id" });
  };
  opening.onsuccess = function () {
    database = opening.result;
    held.forEach(put);
    held = [];
    send();
  };
  setInterval(send, 5000);

  var realSet = Storage.prototype.setItem;
  Storage.prototype.setItem = function (key, value) {
    if (key === KEY) note("queue stored", queueText(value) + " by " + callers());
    return realSet.apply(this, arguments);
  };
  var realRemove = Storage.prototype.removeItem;
  Storage.prototype.removeItem = function (key) {
    if (key === KEY) note("queue removed", "by " + callers());
    return realRemove.apply(this, arguments);
  };
  var realClear = Storage.prototype.clear;
  Storage.prototype.clear = function () {
    note("storage cleared", "by " + callers());
    return realClear.apply(this, arguments);
  };

  window.fetch = function (input, init) {
    var method = (init && init.method) || (input && input.method) || "GET";
    var url = String(typeof input === "string" ? input : input.url);
    var path = short(url.replace(/^.*\/api/, ""));
    var watched =
      method !== "GET" && url.indexOf("/api/") !== -1 && path.indexOf("/parse") !== 0;
    var promise = realFetch(input, init);
    if (watched) {
      promise.then(
        function (reply) {
          note("request answered", method + " " + path + " -> " + reply.status);
        },
        function () {
          note("request not answered", method + " " + path);
        },
      );
    }
    return promise;
  };

  var RealSocket = window.WebSocket;
  function Socket(url, protocols) {
    var socket =
      protocols === undefined ? new RealSocket(url) : new RealSocket(url, protocols);
    var opened = false;
    socket.addEventListener("open", function () {
      opened = true;
      note("connection to the server opened");
    });
    socket.addEventListener("close", function () {
      if (opened) note("connection to the server closed");
    });
    return socket;
  }
  Socket.prototype = RealSocket.prototype;
  ["CONNECTING", "OPEN", "CLOSING", "CLOSED"].forEach(function (name) {
    Socket[name] = RealSocket[name];
  });
  window.WebSocket = Socket;

  function stored() {
    return "queue " + queueText(localStorage.getItem(KEY));
  }

  note(
    "page opened",
    stored() +
      (navigator.serviceWorker && navigator.serviceWorker.controller
        ? ""
        : ", no service worker in control"),
  );
  document.addEventListener("visibilitychange", function () {
    note(document.hidden ? "page hidden" : "page shown", stored());
  });
  window.addEventListener("pagehide", function (event) {
    note("page left", event.persisted ? "kept by the browser" : "");
  });
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) note("page brought back by the browser", stored());
  });
  document.addEventListener("freeze", function () {
    note("page frozen");
  });
  document.addEventListener("resume", function () {
    note("page resumed", stored());
  });
  window.addEventListener("online", function () {
    note("browser reports the device online");
  });
  window.addEventListener("offline", function () {
    note("browser reports the device offline");
  });
  window.addEventListener("storage", function (event) {
    if (event.key === KEY) {
      note("queue stored by another open page", queueText(event.newValue));
    }
  });
  document.addEventListener(
    "click",
    function (event) {
      var target = event.target.closest && event.target.closest("button, input, a");
      if (!target) return;
      var name = target.id || target.className || target.tagName;
      var label = target.getAttribute("aria-label") || target.textContent || "";
      note("tap", name + (label ? " (" + label.trim().slice(0, 40) + ")" : ""));
    },
    true,
  );
  new MutationObserver(function (changes) {
    changes.forEach(function (change) {
      Array.prototype.forEach.call(change.addedNodes, function (node) {
        if (node.classList && node.classList.contains("toast")) {
          note("notice", node.textContent);
        }
      });
    });
  }).observe(document, { childList: true, subtree: true });
})();
"""

STEP_1 = """\
Step 1: the page is stored. The server is running.

  Open the address above on the phone or tablet.
  - The page shows five tasks, numbered 1 to 5 in that order.
  - This terminal prints
      Service worker on the device: installed and active
    If it prints "refused" instead, the page cannot open without the
    server on that device, and the steps below cannot be followed there.

  Then open the board (the middle of the three view buttons at the top)
  and go back to the list (the left one). The board is stored for use
  without the server once it has been opened.

  Press Enter when that is done. The server then stops."""

STEP_2 = """\
Step 2: ticks. The server is stopped.

  Within a few seconds a notice appears at the top of the page:
      Can't reach the server. Showing data saved at <the time>.
  and the dot by the title is red.

  1. Tick "1 Tick me".
     - It is shown ticked and struck through, with an orange "Not sent"
       label under its name. With the list sorted by completion, as it
       is at first, it moves below the other tasks.
     - A red 1 appears on "More".
  2. Close the page (or the browser tab) and open the same address again.
     - "1 Tick me" is still ticked, with the label. The red 1 is there.
  3. Tick "2 Tick me twice".
     - It is ticked, with the label. The count is 2.
  4. Tick "2 Tick me twice" again.
     - It is unticked and has no label: the second tick took the first
       back, and nothing is kept for it. The count is 1 again.

  Press Enter to go on. The server stays stopped."""

STEP_3 = """\
Step 3: other changes. The server is still stopped.

  1. Press and hold "3 Change my priority", choose Priority, then High.
     - Its left edge takes the color of a high priority, and it has
       the label.
  2. Remove "4 Delete me" with the x at the right of its row.
     - The row goes. A notice offers Undo.
     - Tap Undo: the row is back, without a label. Remove it again.
  3. Add a task: tap +, type
         6 Added offline tomorrow
     and tap Add.
     - A row with a dashed outline appears at the top of the list, with
       the text as it was typed and the label. It cannot be ticked or
       opened.
  4. Add another task, "7 Remove me". Remove it with the x on its row.
     - The row goes.
  5. Close the page and open it again.
     - Everything is as it was left: 1 ticked, 3 high, 4 gone, and the
       dashed "6 Added offline tomorrow" at the top. The count is 4.
  6. Open the board.
     - "6 Added offline tomorrow" is at the top of the first column,
       dashed, with the label. "3 Change my priority" below it has the
       label. "4 Delete me" is not there.
     - Swipe to the last column: "1 Tick me" is in it, with the label.
     Go back to the list.

  Leave the page open and press Enter. The server then starts again."""

STEP_4 = """\
Step 4: the changes are sent. The server is running again.

  Leave the page open. Within about half a minute, without anything
  being touched:
  - The notice at the top goes, and the dot is green.
  - A notice reads "All changes synced".
  - Every label is gone, and the count on "More" is gone.
  - "6 Added offline" is an ordinary task, due tomorrow: the server read
    "tomorrow" out of the text.
  - "Stored now" below shows what the server holds:
      1 Tick me              done
      2 Tick me twice        not done
      3 Change my priority   not done, high
      5 Leave me alone       not done
      6 Added offline        not done, due tomorrow
    with no "4 Delete me" and no "7 Remove me".

  Press Enter to stop."""


def build_database() -> Database:
    today = date.today()
    db = Database()
    lst = create_todo_list("Offline queue")
    for number, title in enumerate(TASKS, start=1):
        lst.add_item(create_todo_item(title, due_date=today + timedelta(days=number)))
    db.add_list(lst)
    db.set_active_list(lst.id)
    return db


def describe(db: Database) -> list[str]:
    tomorrow = date.today() + timedelta(days=1)
    lines = []
    for lst in db.lists.values():
        for item in sorted(lst.active_items(), key=lambda item: item.reminder):
            state = "done" if item.complete else "not done"
            if item.priority != 2:
                state += f", {PRIORITIES.get(item.priority, item.priority)}"
            if item.reminder not in TASKS and item.due_date is not None:
                when = "tomorrow" if item.due_date == tomorrow else item.due_date.isoformat()
                state += f", due {when}"
            lines.append(f"  {item.reminder:<22} {state}")
    return lines


_ID = re.compile(r"([0-9a-f]{4})[0-9a-f]{4}-[0-9a-f-]{27}")


class Trace:
    """What the page and the server did, in order of time, in a file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lines: dict[str, tuple[float, str]] = {}
        self._count = 0

    def add(self, when: float, who: str, text: str, key: str | None = None) -> None:
        """Add a line; a line with a key already added is ignored."""
        if key is None:
            self._count += 1
            key = f"server-{self._count}"
        if key in self._lines:
            return
        clock = datetime.fromtimestamp(when).strftime("%H:%M:%S.%f")[:-3]
        self._lines[key] = (when, f"{clock}  {who:<10} {text}")
        ordered = sorted(self._lines.values())
        self.path.write_text("".join(f"{line}\n" for _, line in ordered), encoding="utf-8")

    async def receive(self, request: web.Request) -> web.Response:
        """Take the records a page kept while it could not send them."""
        body = await request.json()
        # The device's clock is not this machine's: place the records by
        # how long before sending each was made.
        offset = time.time() - body["sent_at"] / 1000
        for record in body["records"]:
            self.add(
                record["at"] / 1000 + offset,
                f"page {record['page']}",
                f"#{record['n']} {record['what']}",
                key=record["id"],
            )
        return web.json_response({"ok": True})

    @web.middleware
    async def requests(self, request: web.Request, handler: Any) -> web.StreamResponse:
        """Note each change the server is asked to make, and its answer."""
        status = 500
        try:
            response = await handler(request)
            status = response.status
            return response
        except web.HTTPException as error:
            status = error.status
            raise
        finally:
            if request.method != "GET" and request.path.startswith("/api/"):
                path = _ID.sub(r"\1", request.path.removeprefix("/api"))
                if not path.startswith("/parse"):
                    self.add(time.time(), "server", f"{request.method} {path} -> {status}")


async def start(db: Database, port: int, trace: Trace | None = None) -> web.AppRunner:
    app = WebServer(database=db).create_app()
    app.router.add_get("/check/worker", worker_report)
    if trace is not None:
        app.middlewares.append(trace.requests)
        app.router.add_post("/check/trace", trace.receive)
        trace.add(time.time(), "server", "started")
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


async def watch(db: Database) -> None:
    last: list[str] = []
    while True:
        current = describe(db)
        if current != last:
            print("Stored now:\n" + "\n".join(current), flush=True)
            last = current
        await asyncio.sleep(0.5)


async def serve(port: int, trace: Trace | None) -> None:
    db = build_database()
    _, hosts = application_certificate()

    if trace is not None:
        for lst in db.lists.values():
            trace.add(time.time(), "server", f"list {str(lst.id)[:4]} is {lst.name}")
            for item in lst.active_items():
                trace.add(time.time(), "server", f"item {str(item.id)[:4]} is {item.reminder}")
        print(f"\nWhat the page does is written to:\n  {trace.path}")
    runner: web.AppRunner | None = await start(db, port, trace)
    watcher = asyncio.create_task(watch(db))
    try:
        print("\nOn a phone or tablet on the same network, either of:")
        for name in hosts:
            print(f"  https://{name}:{port}/")
        print(ADDRESS_NOTES)
        await enter(STEP_1)

        await runner.cleanup()
        runner = None
        if trace is not None:
            trace.add(time.time(), "server", "stopped")
        await enter(STEP_2)
        await enter(STEP_3)

        runner = await start(db, port, trace)
        await enter(STEP_4)
    finally:
        watcher.cancel()
        if runner is not None:
            await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the web page for an offline queue check.")
    parser.add_argument("--port", type=int, default=8771, help="port to serve HTTPS on")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="record what the page does, and write it to a file",
    )
    args = parser.parse_args()
    trace = None
    if args.trace:
        trace = Trace(Path(tempfile.gettempdir()) / "pytodo-offline-queue-trace.txt")

    # A copy of the page's files, so that the lines that report on the
    # service worker can be added to app.js without touching the original.
    with tempfile.TemporaryDirectory() as temporary:
        static_dir = Path(temporary) / "static"
        shutil.copytree(web_server._STATIC_DIR, static_dir)
        page_script = static_dir / "app.js"
        text = page_script.read_text(encoding="utf-8") + REPORT_JS
        if trace is not None:
            text = TRACE_JS + text
        page_script.write_text(text, encoding="utf-8")
        web_server._STATIC_DIR = static_dir
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(serve(args.port, trace))
    print("\nStopped.")
    if trace is not None:
        print(f"What the page did is in:\n  {trace.path}")


if __name__ == "__main__":
    main()
