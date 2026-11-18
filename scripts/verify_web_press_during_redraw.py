"""Manual verification harness for presses on a list that is being drawn again.

The web page draws its list again whenever the list's data changes, and
a redraw replaces every row. A tap, a long press or a swipe that has a
redraw arrive under it is hard to produce by hand: the change has to
come from elsewhere within the fraction of a second the finger is down.

This script serves the real web page from a throwaway in-memory database
in which one task renames itself several times a second, so that every
press has a redraw arrive under it, and one person can check what the
page then does. Nothing is saved: the tasks are rebuilt each time the
script starts. The server runs without pairing, which is what the web
server does when it is given no configuration.

The page is served from a temporary copy of its files, taken when the
script starts; the script is started again to pick up a change to the
page. In the copy, a row's entry animation is turned off: the task that
renames itself is a changed row at every redraw, and would flash without
pause. ``--with-animation`` leaves the animation on.

This is **not** part of the pytest suite and **not** CI-gated — it
requires a human watching the screen.

Run from the repo root:

    uv run python scripts/verify_web_press_during_redraw.py

and open ``http://127.0.0.1:8772/`` on this computer. To also reach the
page from a phone or tablet on the same network, which the swipe needs:

    uv run python scripts/verify_web_press_during_redraw.py --phone

The page refuses plain HTTP from any address but this machine's own, so
``--phone`` adds a second listener, on the next port, that serves HTTPS
with the certificate the application's web server already uses. The
certificate and its key are only read. A device that trusts the
application's web interface trusts this page too. Anyone on the network
can open the throwaway page while the script runs with ``--phone``.

The addresses and the steps to follow are printed when the script
starts.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_web_advance_reminder import application_certificate  # noqa: E402

from pytodo_qt.core.models import (  # noqa: E402
    Database,
    TodoItem,
    create_todo_item,
    create_todo_list,
)
from pytodo_qt.web import server as web_server  # noqa: E402
from pytodo_qt.web.api import _broadcast_refresh, ws_clients_key  # noqa: E402
from pytodo_qt.web.server import WebServer  # noqa: E402

STEPS = """\
The first task renames itself all the time: the list is being drawn
again under everything done below. Its number stops while a finger or
the mouse button is down, and runs on when it is let go.

  1. Tap "1 Tap me" several times, closing its sheet each time.
     - Each tap opens the task's sheet. No menu opens.
  2. Press and hold "2 Hold me" until its menu opens, then let go.
     - The menu is the one of "2 Hold me", and it stays open.
       Close it with Cancel.
  3. On a phone, swipe "3 Swipe me right" to the right.
     - It is ticked. Swipe it again to untick it.
  4. Open the board (the middle of the three view buttons at the top)
     and tap a card.
     - The task's sheet opens.
  5. Open the calendar (the right one) and tap a task in the Month.
     - The task's sheet opens.

A page that does not hold its redraw while a row is pressed fails
step 1: most taps open nothing, and half a second later the task's menu
opens.

Ctrl+C to stop."""

# Added to the copy of style.css: no entry animation for a row.
_NO_ENTRY_ANIMATION = "\n.item-enter { animation: none; }\n"


def build_database() -> tuple[Database, TodoItem]:
    """The tasks to press, and the one that renames itself."""
    db = Database()
    lst = create_todo_list("Press check")
    changing = create_todo_item("Changes by itself: 0")
    lst.add_item(changing)
    for title in ("1 Tap me", "2 Hold me", "3 Swipe me right", "4 Leave me alone"):
        # Due today, so that the calendar's Month shows them.
        lst.add_item(create_todo_item(title, due_date=date.today()))
    db.add_list(lst)
    db.set_active_list(lst.id)
    return db, changing


async def serve(port: int, phone: bool, interval: float) -> None:
    db, changing = build_database()
    app = WebServer(database=db).create_app()
    # No access log, so the steps stay readable; a short shutdown, so an
    # open WebSocket does not hold the server up when it is stopped.
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=1.0)
    await runner.setup()

    await web.TCPSite(runner, "127.0.0.1", port).start()
    print(f"\nOn this computer:\n  http://127.0.0.1:{port}/")
    if phone:
        context, hosts = application_certificate()
        await web.TCPSite(runner, "0.0.0.0", port + 1, ssl_context=context).start()
        print("\nOn a phone or tablet on the same network, either of:")
        for name in hosts:
            print(f"  https://{name}:{port + 1}/")
    print(f"\n{STEPS}\n", flush=True)

    count = 0
    try:
        while True:
            await asyncio.sleep(interval)
            count += 1
            changing.reminder = f"Changes by itself: {count}"
            changing.mark_updated()
            await _broadcast_refresh(app[ws_clients_key])
    finally:
        await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve the web page with a list that is drawn again all the time."
    )
    parser.add_argument("--port", type=int, default=8772, help="port for this computer")
    parser.add_argument(
        "--phone",
        action="store_true",
        help="also serve HTTPS to the network, on the next port",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.15,
        help="seconds between two renames of the first task",
    )
    parser.add_argument(
        "--with-animation",
        action="store_true",
        help="leave the rows' entry animation on",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as temporary:
        static_dir = Path(temporary) / "static"
        shutil.copytree(web_server._STATIC_DIR, static_dir)
        if not args.with_animation:
            with (static_dir / "style.css").open("a", encoding="utf-8") as css:
                css.write(_NO_ENTRY_ANIMATION)
        web_server._STATIC_DIR = static_dir
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(serve(args.port, args.phone, args.interval))
    print("\nStopped.")


if __name__ == "__main__":
    main()
