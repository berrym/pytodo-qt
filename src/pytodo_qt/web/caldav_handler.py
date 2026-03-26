"""caldav_handler.py

CalDAV (RFC 4791) endpoint handlers for the embedded web server.

Maps TodoLists to calendar collections and TodoItems to VTODO resources,
enabling live sync with Thunderbird, DAVx5, Tasks.org, Fantastical, and
other CalDAV clients.

All writes go through QUndoCommands for unified undo/redo and sync.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from aiohttp import web

from .api import (
    _apply_item_fields,
    _schedule_save_and_refresh,
    database_key,
    main_window_key,
)
from .caldav_xml import (
    _CALENDAR_DATA,
    _DISPLAYNAME,
    _GETCONTENTTYPE,
    _GETCTAG,
    _GETETAG,
    _RESOURCETYPE,
    _SUPPORTED_CALENDAR_COMPONENT_SET,
    _SYNC_TOKEN,
    build_multistatus,
    make_response,
    make_response_404,
    parse_report,
    prop_calendar_data,
    prop_calendar_home_set,
    prop_current_user_principal,
    prop_resourcetype_calendar,
    prop_resourcetype_collection,
    prop_supported_components,
)

_XML_CONTENT = "application/xml"
_ICS_CONTENT = "text/calendar"


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def setup_caldav_routes(app: web.Application) -> None:
    """Register CalDAV routes on the aiohttp application."""
    # Well-known discovery
    app.router.add_route("GET", "/.well-known/caldav", handle_wellknown)

    # OPTIONS and HEAD for DAV capability discovery (Thunderbird probes with these)
    app.router.add_route("OPTIONS", "/caldav/{path:.*}", handle_options)
    app.router.add_route("HEAD", "/caldav/{path:.*}", handle_head)
    app.router.add_route("GET", "/caldav/", handle_get_root)

    # PROPFIND at each level
    app.router.add_route("PROPFIND", "/caldav/", handle_propfind_root)
    app.router.add_route("PROPFIND", "/caldav/user/", handle_propfind_principal)
    app.router.add_route("PROPFIND", "/caldav/user/calendars/", handle_propfind_home)
    app.router.add_route(
        "PROPFIND",
        "/caldav/user/calendars/{list_id}/",
        handle_propfind_calendar,
    )
    app.router.add_route(
        "PROPFIND",
        "/caldav/user/calendars/{list_id}/{item_id}.ics",
        handle_propfind_item,
    )

    # REPORT
    app.router.add_route(
        "REPORT",
        "/caldav/user/calendars/{list_id}/",
        handle_report,
    )

    # VTODO resource operations
    app.router.add_route(
        "GET",
        "/caldav/user/calendars/{list_id}/{item_id}.ics",
        handle_get_item,
    )
    app.router.add_route(
        "PUT",
        "/caldav/user/calendars/{list_id}/{item_id}.ics",
        handle_put_item,
    )
    app.router.add_route(
        "DELETE",
        "/caldav/user/calendars/{list_id}/{item_id}.ics",
        handle_delete_item,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db(request: web.Request) -> Any:
    return request.app[database_key]


def _etag(item: Any) -> str:
    return f'"{item.updated_at}"'


def _ctag(lst: Any) -> str:
    return f"ctag-{lst.updated_at}"


def _sync_token(lst: Any) -> str:
    return f"sync-token-{lst.updated_at}"


def _item_href(list_id: UUID, item_id: UUID) -> str:
    return f"/caldav/user/calendars/{list_id}/{item_id}.ics"


def _calendar_props(lst: Any) -> dict[str, Any]:
    """Build property dict for a calendar collection."""
    return {
        _RESOURCETYPE: prop_resourcetype_calendar(),
        _DISPLAYNAME: lst.name,
        _SUPPORTED_CALENDAR_COMPONENT_SET: prop_supported_components(),
        _GETCTAG: _ctag(lst),
        _SYNC_TOKEN: _sync_token(lst),
    }


def _item_props(item: Any, list_id: UUID, include_data: bool = False) -> dict[str, Any]:
    """Build property dict for a VTODO resource."""
    props: dict[str, Any] = {
        _GETETAG: _etag(item),
        _GETCONTENTTYPE: _ICS_CONTENT,
    }
    if include_data:
        from ..core.caldav import item_to_ics

        props[_CALENDAR_DATA] = prop_calendar_data(item_to_ics(item))
    return props


# ---------------------------------------------------------------------------
# Discovery handlers
# ---------------------------------------------------------------------------


async def handle_wellknown(request: web.Request) -> web.Response:
    """GET /.well-known/caldav — redirect to CalDAV root."""
    raise web.HTTPMovedPermanently("/caldav/")


async def handle_options(request: web.Request) -> web.Response:
    """OPTIONS /caldav/* — DAV capability discovery."""
    return web.Response(
        status=200,
        headers={
            "DAV": "1, 2, 3, calendar-access",
            "Allow": "OPTIONS, HEAD, GET, PUT, DELETE, PROPFIND, REPORT",
        },
    )


async def handle_head(request: web.Request) -> web.Response:
    """HEAD /caldav/* — connection test (Thunderbird probes before PROPFIND)."""
    return web.Response(
        status=200,
        headers={
            "DAV": "1, 2, 3, calendar-access",
        },
    )


async def handle_get_root(request: web.Request) -> web.Response:
    """GET /caldav/ — simple response for connection verification."""
    return web.Response(
        status=200,
        text="PyTodo-Qt CalDAV Server",
        content_type="text/plain",
        headers={
            "DAV": "1, 2, 3, calendar-access",
        },
    )


# ---------------------------------------------------------------------------
# PROPFIND handlers
# ---------------------------------------------------------------------------


async def handle_propfind_root(request: web.Request) -> web.Response:
    """PROPFIND /caldav/ — return current-user-principal."""
    resp = make_response(
        "/caldav/",
        {
            _RESOURCETYPE: prop_resourcetype_collection(),
            prop_current_user_principal("/caldav/user/").tag: prop_current_user_principal(
                "/caldav/user/"
            ),
        },
    )
    return web.Response(
        status=207,
        body=build_multistatus([resp]),
        content_type=_XML_CONTENT,
    )


async def handle_propfind_principal(request: web.Request) -> web.Response:
    """PROPFIND /caldav/user/ — return calendar-home-set."""
    resp = make_response(
        "/caldav/user/",
        {
            _RESOURCETYPE: prop_resourcetype_collection(),
            prop_calendar_home_set("/caldav/user/calendars/").tag: prop_calendar_home_set(
                "/caldav/user/calendars/"
            ),
        },
    )
    return web.Response(
        status=207,
        body=build_multistatus([resp]),
        content_type=_XML_CONTENT,
    )


async def handle_propfind_home(request: web.Request) -> web.Response:
    """PROPFIND /caldav/user/calendars/ — enumerate calendar collections."""
    db = _get_db(request)
    depth = request.headers.get("Depth", "0")

    responses = [
        make_response(
            "/caldav/user/calendars/",
            {_RESOURCETYPE: prop_resourcetype_collection()},
        )
    ]

    if depth == "1":
        for lst in db.lists.values():
            if lst.deleted or lst.private:
                continue
            href = f"/caldav/user/calendars/{lst.id}/"
            responses.append(make_response(href, _calendar_props(lst)))

    return web.Response(
        status=207,
        body=build_multistatus(responses),
        content_type=_XML_CONTENT,
    )


async def handle_propfind_calendar(request: web.Request) -> web.Response:
    """PROPFIND /caldav/user/calendars/{list_id}/ — calendar metadata + item listing."""
    db = _get_db(request)
    try:
        list_id = UUID(request.match_info["list_id"])
    except ValueError:
        return web.Response(status=400, text="Invalid list ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return web.Response(status=404, text="Calendar not found")

    depth = request.headers.get("Depth", "0")
    href = f"/caldav/user/calendars/{list_id}/"
    responses = [make_response(href, _calendar_props(lst))]

    if depth == "1":
        for item in lst.items.values():
            if item.deleted:
                continue
            item_href = _item_href(list_id, item.id)
            responses.append(make_response(item_href, _item_props(item, list_id)))

    return web.Response(
        status=207,
        body=build_multistatus(responses),
        content_type=_XML_CONTENT,
    )


async def handle_propfind_item(request: web.Request) -> web.Response:
    """PROPFIND /caldav/user/calendars/{list_id}/{item_id}.ics — single item."""
    db = _get_db(request)
    try:
        list_id = UUID(request.match_info["list_id"])
        item_id = UUID(request.match_info["item_id"])
    except ValueError:
        return web.Response(status=400, text="Invalid ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return web.Response(status=404)

    item = lst.items.get(item_id)
    if item is None or item.deleted:
        return web.Response(status=404)

    href = _item_href(list_id, item_id)
    resp = make_response(href, _item_props(item, list_id))
    return web.Response(
        status=207,
        body=build_multistatus([resp]),
        content_type=_XML_CONTENT,
    )


# ---------------------------------------------------------------------------
# REPORT handlers
# ---------------------------------------------------------------------------


async def handle_report(request: web.Request) -> web.Response:
    """REPORT /caldav/user/calendars/{list_id}/ — multiget, query, or sync."""
    db = _get_db(request)
    try:
        list_id = UUID(request.match_info["list_id"])
    except ValueError:
        return web.Response(status=400, text="Invalid list ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return web.Response(status=404)

    body = await request.read()
    report_type, hrefs, req_props, sync_token_str = parse_report(body)

    include_data = _CALENDAR_DATA in req_props

    if report_type == "calendar-multiget":
        return _handle_multiget(lst, list_id, hrefs, include_data)
    if report_type == "calendar-query":
        return _handle_query(lst, list_id, include_data)
    if report_type == "sync-collection":
        return _handle_sync_collection(lst, list_id, sync_token_str, include_data)

    return web.Response(status=400, text="Unsupported report type")


def _handle_multiget(lst: Any, list_id: UUID, hrefs: list[str], include_data: bool) -> web.Response:
    """Handle calendar-multiget REPORT."""
    responses = []
    for href in hrefs:
        # Extract item_id from href
        parts = href.rstrip("/").split("/")
        if not parts or not parts[-1].endswith(".ics"):
            responses.append(make_response_404(href))
            continue
        try:
            item_id = UUID(parts[-1][:-4])  # strip .ics
        except ValueError:
            responses.append(make_response_404(href))
            continue

        item = lst.items.get(item_id)
        if item is None or item.deleted:
            responses.append(make_response_404(href))
        else:
            responses.append(make_response(href, _item_props(item, list_id, include_data)))

    return web.Response(
        status=207,
        body=build_multistatus(responses),
        content_type=_XML_CONTENT,
    )


def _handle_query(lst: Any, list_id: UUID, include_data: bool) -> web.Response:
    """Handle calendar-query REPORT — return all VTODOs."""
    responses = []
    for item in lst.items.values():
        if item.deleted:
            continue
        href = _item_href(list_id, item.id)
        responses.append(make_response(href, _item_props(item, list_id, include_data)))

    return web.Response(
        status=207,
        body=build_multistatus(responses),
        content_type=_XML_CONTENT,
    )


def _handle_sync_collection(
    lst: Any, list_id: UUID, sync_token_str: str, include_data: bool
) -> web.Response:
    """Handle sync-collection REPORT (RFC 6578)."""
    # Parse the timestamp from the sync token
    old_timestamp = 0
    if sync_token_str.startswith("sync-token-"):
        try:
            old_timestamp = int(sync_token_str[len("sync-token-") :])
        except ValueError:
            return web.Response(status=409, text="Invalid sync token")

    responses = []
    for item in lst.items.values():
        if item.updated_at <= old_timestamp:
            continue
        href = _item_href(list_id, item.id)
        if item.deleted:
            responses.append(make_response_404(href))
        else:
            responses.append(make_response(href, _item_props(item, list_id, include_data)))

    return web.Response(
        status=207,
        body=build_multistatus(responses, sync_token=_sync_token(lst)),
        content_type=_XML_CONTENT,
    )


# ---------------------------------------------------------------------------
# Resource handlers (GET/PUT/DELETE)
# ---------------------------------------------------------------------------


async def handle_get_item(request: web.Request) -> web.Response:
    """GET /caldav/user/calendars/{list_id}/{item_id}.ics — fetch VTODO."""
    db = _get_db(request)
    try:
        list_id = UUID(request.match_info["list_id"])
        item_id = UUID(request.match_info["item_id"])
    except ValueError:
        return web.Response(status=400, text="Invalid ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return web.Response(status=404)

    item = lst.items.get(item_id)
    if item is None or item.deleted:
        return web.Response(status=404)

    from ..core.caldav import item_to_ics

    return web.Response(
        status=200,
        body=item_to_ics(item),
        content_type=_ICS_CONTENT,
        headers={"ETag": _etag(item)},
    )


async def handle_put_item(request: web.Request) -> web.Response:
    """PUT /caldav/user/calendars/{list_id}/{item_id}.ics — create or update."""
    db = _get_db(request)
    try:
        list_id = UUID(request.match_info["list_id"])
        item_id = UUID(request.match_info["item_id"])
    except ValueError:
        return web.Response(status=400, text="Invalid ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return web.Response(status=404, text="Calendar not found")

    # Read and parse the VTODO
    data = await request.read()
    from ..core.caldav import vtodo_to_field_dict

    fields = vtodo_to_field_dict(data)
    if not fields:
        return web.Response(status=400, text="No VTODO found in body")

    existing = lst.items.get(item_id)

    # Conditional update: If-Match etag check
    if_match = request.headers.get("If-Match")
    if if_match and existing and if_match.strip('"') != str(existing.updated_at):
        return web.Response(status=412, text="Precondition Failed")

    window = request.app.get(main_window_key)

    if existing and not existing.deleted:
        # Update existing item
        if window:
            from ..gui.commands import WebUpdateItemCommand

            cmd = WebUpdateItemCommand(window, list_id, item_id, fields)
            window._undo_stack.push(cmd)
        else:
            _apply_item_fields(existing, fields, lst)
            existing.mark_updated()
            _schedule_save_and_refresh(request)

        return web.Response(
            status=204,
            headers={"ETag": _etag(existing)},
        )
    else:
        # Create new item
        from ..core.models import create_todo_item

        item = create_todo_item(fields.get("reminder", ""))
        # Force the UUID to match the URL
        item.id = item_id
        _apply_item_fields(item, fields, lst)
        if not item.board_column and lst.board_columns:
            item.board_column = lst.board_columns[0]

        if window:
            from ..gui.commands import AddItemCommand

            cmd = AddItemCommand(window, list_id, item)
            window._undo_stack.push(cmd)
        else:
            lst.add_item(item)
            _schedule_save_and_refresh(request)

        return web.Response(
            status=201,
            headers={"ETag": _etag(item)},
        )


async def handle_delete_item(request: web.Request) -> web.Response:
    """DELETE /caldav/user/calendars/{list_id}/{item_id}.ics — soft-delete."""
    db = _get_db(request)
    try:
        list_id = UUID(request.match_info["list_id"])
        item_id = UUID(request.match_info["item_id"])
    except ValueError:
        return web.Response(status=400, text="Invalid ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return web.Response(status=404)

    item = lst.items.get(item_id)
    if item is None or item.deleted:
        return web.Response(status=404)

    # Conditional delete: If-Match etag check
    if_match = request.headers.get("If-Match")
    if if_match and if_match.strip('"') != str(item.updated_at):
        return web.Response(status=412, text="Precondition Failed")

    window = request.app.get(main_window_key)
    if window:
        from ..gui.commands import DeleteItemsCommand

        cmd = DeleteItemsCommand(window, list_id, [item_id])
        window._undo_stack.push(cmd)
    else:
        item.mark_deleted()
        _schedule_save_and_refresh(request)

    return web.Response(status=204)
