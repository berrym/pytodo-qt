"""Manual visual-verification harness for the web "Remind ahead" row.

Serves the real web page from a throwaway in-memory database, so the
advance-reminder control in the item sheet can be checked — and edited
— without touching the real database, configuration or paired devices.
Nothing is saved: the tasks are rebuilt each time the script starts.

The server runs without pairing, which is what the web server does when
it is given no configuration.

This is **not** part of the pytest suite and **not** CI-gated — it
requires a human watching the screen.

Run from the repo root:

    uv run python scripts/verify_web_advance_reminder.py

and open ``http://127.0.0.1:8765/`` on this computer. To also reach the
page from a phone or tablet on the same network:

    uv run python scripts/verify_web_advance_reminder.py --phone

The page refuses plain HTTP from any address but this machine's own, so
``--phone`` adds a second listener, on the next port, that serves HTTPS
with the certificate the application's web server already uses. The
certificate and its key are only read. A device that trusts the
application's web interface trusts this page too. Anyone on the network
can open the throwaway page while the script runs with ``--phone``.

The addresses and the steps to follow are printed when the script
starts. The terminal then prints the reminder each task holds whenever
it changes, so what the page shows can be compared with what was
stored.
"""

from __future__ import annotations

import argparse
import asyncio
import ssl
import sys
from datetime import date, timedelta
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pytodo_qt.core import network, paths  # noqa: E402
from pytodo_qt.core.models import (  # noqa: E402
    Database,
    TodoItem,
    create_todo_item,
    create_todo_list,
)
from pytodo_qt.web.server import WebServer, tls_context  # noqa: E402

STEPS = """\
The list shows five tasks, numbered 1 to 5 from the top. Tap or click a
task to open "Item Details". REMIND AHEAD is the sixth field, under DUE
TIME. Close a task with the X at the top right. Each change is saved as
it is made: this terminal prints "Stored now:" with the new values, and
"Saved" is written near the bottom of the sheet, above "Delete Item".

1. Open "1 Due date, no reminder".
   - REMIND AHEAD shows "Off" and nothing beside it.
   - Choose "Once": a box holding 1 appears, followed by "day before".
   - Change the 1 to 2: the text becomes "days before".
   - Close the task and open it again: it still shows Once and 2.
   - Choose "Off": the box disappears.

2. Open "2 Once, 3 days before".
   - REMIND AHEAD shows "Once", 3, "days before".

3. Open "3 Every day, 14 days before".
   - REMIND AHEAD shows "Every day until due", 14, "days before".
   - Type 500 in the box and leave it: it becomes 90.
   - Type 0 in the box and leave it: it becomes 1.

4. Open "4 No due date".
   - REMIND AHEAD shows "Off", grayed, and cannot be changed.
   - "Needs a due date." is written under it.
   - Set a DUE DATE: REMIND AHEAD can be changed at once, and the line
     under it now says what the reminder does.
   - Straight away choose "Once". Close the task and open it again: the
     date and "Once" are both there.

5. Open "5 Reminder stored, no due date".
   - REMIND AHEAD shows "Once" and 5, grayed, with "Needs a due date."
   - Set a DUE DATE: it can be changed, and still shows Once and 5.

On a phone the box sits under the choice; on a wide screen it sits
beside it. "Every day until due" is never cut short.
"""


def build_database() -> Database:
    """Five tasks, named in the order the list shows them: tasks with a
    due date first, soonest first, then tasks without one."""
    today = date.today()
    db = Database()
    lst = create_todo_list("Remind ahead")

    def add(title: str, due_in: int | None, days: int = 0, cadence: str = "none") -> None:
        due = today + timedelta(days=due_in) if due_in is not None else None
        item = create_todo_item(title, due_date=due)
        item.remind_before_days = days
        item.reminder_cadence = cadence
        lst.add_item(item)

    add("1 Due date, no reminder", 7)
    add("2 Once, 3 days before", 10, 3, "once")
    add("3 Every day, 14 days before", 20, 14, "daily_until_due")
    add("4 No due date", None)
    add("5 Reminder stored, no due date", None, 5, "once")
    db.add_list(lst)
    db.set_active_list(lst.id)
    return db


def describe(item: TodoItem) -> str:
    due = item.due_date.isoformat() if item.due_date else "no due date"
    return (
        f"  {item.reminder:<34} {due:<12} "
        f"remind_before_days={item.remind_before_days} "
        f"reminder_cadence={item.reminder_cadence}"
    )


def application_certificate() -> tuple[ssl.SSLContext, list[str]]:
    """Return a TLS context that presents the application's web
    certificates as the application does, and the host name and
    addresses the machine has now that those certificates cover."""
    config_dir = paths.get_config_dir()
    cert_path = config_dir / "web_cert.pem"
    key_path = config_dir / "web_key.pem"
    host_cert_path = config_dir / "web_host_cert.pem"
    host_key_path = config_dir / "web_host_key.pem"
    if not cert_path.exists() or not key_path.exists():
        sys.exit(
            f"No web certificate in {config_dir}. Start the application with its "
            "web interface enabled once, so that it creates one."
        )
    context = tls_context(cert_path, key_path, host_cert_path, host_key_path)

    # The certificate for addresses lists the addresses it has had as
    # well; only what the machine has now can be opened.
    for_addresses = WebServer._certificate_names(cert_path) or ([], [])
    for_host_name = WebServer._certificate_names(host_cert_path) or ([], [])
    listed_names = {name.lower() for name in for_addresses[0] + for_host_name[0]}
    hosts = []
    host_name = network.get_local_hostname()
    if host_name and host_name.lower() in listed_names:
        hosts.append(host_name)
    hosts.extend(
        address
        for address in network.get_all_local_addresses()[0]
        if address in for_addresses[1] and not address.startswith("127.")
    )
    return context, hosts


async def serve(port: int, phone: bool) -> None:
    db = build_database()
    server = WebServer(database=db)
    runner = web.AppRunner(server.create_app())
    await runner.setup()

    await web.TCPSite(runner, "127.0.0.1", port).start()
    print(f"\nOn this computer:\n  http://127.0.0.1:{port}/")
    if phone:
        context, hosts = application_certificate()
        await web.TCPSite(runner, "0.0.0.0", port + 1, ssl_context=context).start()
        print("\nOn a phone or tablet on the same network, either of:")
        for name in hosts:
            print(f"  https://{name}:{port + 1}/")
    print(f"\n{STEPS}\nCtrl+C to stop.\n")

    def snapshot() -> list[str]:
        return [describe(item) for lst in db.lists.values() for item in lst.active_items()]

    last: list[str] = []
    try:
        while True:
            current = snapshot()
            if current != last:
                print("Stored now:")
                print("\n".join(current), flush=True)
                last = current
            await asyncio.sleep(0.5)
    finally:
        await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description='Serve the web "Remind ahead" row for a check.')
    parser.add_argument("--port", type=int, default=8765, help="port for this computer")
    parser.add_argument(
        "--phone",
        action="store_true",
        help="also serve HTTPS to the network, on the next port",
    )
    args = parser.parse_args()
    try:
        asyncio.run(serve(args.port, args.phone))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
