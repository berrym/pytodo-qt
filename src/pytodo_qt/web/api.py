"""REST API handlers for the embedded web server.

All handlers operate on the in-memory Database object directly (safe because
the aiohttp server runs on the same qasync event loop as Qt). After writes,
a UI refresh is scheduled via QTimer.singleShot(0, ...).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from aiohttp import web

from ..core import settings
from ..core.models import (
    TodoItem,
    TodoList,
    create_todo_item,
    create_todo_list,
    format_recurrence,
    format_recurrence_short,
    is_overdue,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..core.config import ConfigManager
    from ..core.models import Database

# Typed app keys (shared with server.py, defined here to avoid circular imports)
database_key: web.AppKey[Database] = web.AppKey("database")
save_callback_key: web.AppKey[Callable[[], None]] = web.AppKey("save_callback")
config_manager_key: web.AppKey[ConfigManager] = web.AppKey("config_manager")
ws_clients_key: web.AppKey[set[web.WebSocketResponse]] = web.AppKey("ws_clients")
auth_token_key: web.AppKey[str] = web.AppKey("auth_token")
web_server_key: web.AppKey[Any] = web.AppKey("web_server")


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';"
        " img-src 'self' data:; connect-src 'self' ws: wss:; font-src 'self'"
    ),
}


@web.middleware
async def security_headers_middleware(
    request: web.Request, handler: Callable[..., Any]
) -> web.StreamResponse:
    """Add security headers to all responses."""
    response = await handler(request)
    for key, value in _SECURITY_HEADERS.items():
        # Don't override per-response CSP (e.g., auto-login nonce)
        if key not in response.headers:
            response.headers[key] = value
    return response


@web.middleware
async def auth_middleware(request: web.Request, handler: Callable[..., Any]) -> web.StreamResponse:
    """Require Bearer token for API and WebSocket requests."""
    server = request.app.get(web_server_key)
    token = server.auth_token if server else request.app.get(auth_token_key, "")
    if not token:
        return await handler(request)  # No token configured — allow all

    # Public paths: static assets, login page, pairing endpoint, auto-login URL
    path = request.path
    if (
        path in ("/", "/sw.js", "/api/auth", "/ca.pem")
        or path.startswith("/static/")
        or path.startswith("/auth/")
    ):
        return await handler(request)

    # Check Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == token:
        return await handler(request)

    # Check query parameter (for WebSocket — browsers can't set WS headers)
    if request.query.get("token") == token:
        return await handler(request)

    return web.json_response({"error": "Authentication required", "status": 401}, status=401)


def _item_to_json(item: TodoItem) -> dict[str, Any]:
    """Serialize a TodoItem for the JSON API."""
    return {
        "id": str(item.id),
        "reminder": item.reminder,
        "priority": item.priority,
        "complete": item.complete,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "due_time": item.due_time.isoformat() if item.due_time else None,
        "tags": item.tags,
        "time_spent": item.time_spent,
        "parent_id": str(item.parent_id) if item.parent_id else None,
        "board_column": item.board_column,
        "pomodoro_count": item.pomodoro_count,
        "estimated_pomodoros": item.estimated_pomodoros,
        "is_recurring": item.is_recurring,
        "recurrence_type": item.recurrence_type,
        "recurrence_interval": item.recurrence_interval,
        "recurrence_end_date": (
            item.recurrence_end_date.isoformat() if item.recurrence_end_date else None
        ),
        "recurrence_end_count": item.recurrence_end_count,
        "recurrence_count": item.recurrence_count,
        "missed_recurrences": item.missed_recurrences,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "recurrence_display": format_recurrence_short(item),
        "recurrence_display_full": format_recurrence(item),
    }


def _list_to_json(lst: TodoList) -> dict[str, Any]:
    """Serialize a TodoList for the JSON API."""
    return {
        "id": str(lst.id),
        "name": lst.name,
        "board_columns": lst.board_columns,
        "wip_limits": lst.wip_limits,
        "updated_at": lst.updated_at,
    }


def _error(status: int, message: str) -> web.Response:
    """Return a JSON error response."""
    return web.json_response({"error": message, "status": status}, status=status)


def _conflict_response(current_data: dict[str, Any]) -> web.Response:
    """Return a 409 Conflict response with the entity's current state."""
    return web.json_response(
        {"error": "Conflict: item was modified", "status": 409, "current": current_data},
        status=409,
    )


def setup_routes(app: web.Application) -> None:
    """Register all API routes on the aiohttp application."""
    # List endpoints
    app.router.add_get("/api/lists", handle_get_lists)
    app.router.add_get("/api/lists/{list_id}", handle_get_list)
    app.router.add_post("/api/lists", handle_create_list)
    app.router.add_put("/api/lists/{list_id}", handle_rename_list)
    app.router.add_delete("/api/lists/{list_id}", handle_delete_list)
    # Board / column endpoints
    app.router.add_get("/api/lists/{list_id}/board", handle_get_board)
    app.router.add_patch("/api/lists/{list_id}/columns", handle_update_columns)
    # Item endpoints
    app.router.add_post("/api/lists/{list_id}/items", handle_create_item)
    app.router.add_put("/api/items/{item_id}", handle_update_item)
    app.router.add_delete("/api/items/{item_id}", handle_delete_item)
    app.router.add_patch("/api/items/{item_id}/toggle", handle_toggle_item)
    app.router.add_patch("/api/items/{item_id}/move", handle_move_item)
    app.router.add_patch("/api/items/{item_id}/parent", handle_set_parent)
    app.router.add_patch("/api/items/{item_id}/restore", handle_restore_item)
    # Trash endpoint (recently deleted)
    app.router.add_get("/api/trash", handle_get_trash)
    # Utility endpoints
    app.router.add_post("/api/parse", handle_parse)
    app.router.add_get("/api/tags", handle_get_tags)
    app.router.add_get("/api/status", handle_status)
    # Sort configuration
    app.router.add_get("/api/sort", handle_get_sort)
    app.router.add_put("/api/sort", handle_update_sort)
    # Board layout presets
    app.router.add_get("/api/presets", handle_get_presets)
    app.router.add_post("/api/lists/{list_id}/apply-preset", handle_apply_preset)
    # WebSocket
    app.router.add_get("/ws", handle_websocket)
    # Authentication
    app.router.add_post("/api/auth", handle_pair)
    app.router.add_get("/auth/{token}", handle_auto_login)
    app.router.add_get("/ca.pem", handle_ca_cert_download)


# ---------------------------------------------------------------------------
# List handlers
# ---------------------------------------------------------------------------


async def handle_get_lists(request: web.Request) -> web.Response:
    """GET /api/lists — Return all non-private lists with item counts."""
    db: Database = request.app[database_key]
    result = []
    for lst in db.lists.values():
        if lst.deleted or lst.private:
            continue
        overdue_count = sum(
            1 for i in lst.active_items() if not i.complete and is_overdue(i.due_date, i.due_time)
        )
        result.append(
            {
                "id": str(lst.id),
                "name": lst.name,
                "item_count": lst.active_item_count(),
                "completed_count": sum(1 for i in lst.active_items() if i.complete),
                "overdue_count": overdue_count,
                "board_columns": lst.board_columns,
                "is_private": False,
                "updated_at": lst.updated_at,
            }
        )
    return web.json_response({"lists": result})


async def handle_get_list(request: web.Request) -> web.Response:
    """GET /api/lists/{list_id} — Return a single list with all items.

    Supports query-string filtering:
      ?q=text         — substring match on reminder
      ?tags=@a,@b     — items matching ANY of the given tags
      ?priority=1,2   — items matching any of the given priorities
      ?status=active  — "active", "completed", or "all" (default: "all")
      ?due=overdue    — "overdue", "today", "week", "none" (items with no date)
    """
    db: Database = request.app[database_key]
    try:
        list_id = UUID(request.match_info["list_id"])
    except ValueError:
        return _error(400, "Invalid list ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return _error(404, "List not found")

    items_iter = lst.active_items()
    items = _apply_filters(list(items_iter), request.query)

    return web.json_response(
        {
            "id": str(lst.id),
            "name": lst.name,
            "board_columns": lst.board_columns,
            "wip_limits": lst.wip_limits,
            "updated_at": lst.updated_at,
            "items": [_item_to_json(i) for i in items],
        }
    )


async def handle_create_list(request: web.Request) -> web.Response:
    """POST /api/lists — Create a new list."""
    db: Database = request.app[database_key]
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    name = body.get("name", "").strip()
    if not name:
        return _error(400, "List name is required")

    lst = create_todo_list(name)
    db.add_list(lst)

    _schedule_save_and_refresh(request)
    return web.json_response({"id": str(lst.id), "name": lst.name}, status=201)


async def handle_rename_list(request: web.Request) -> web.Response:
    """PUT /api/lists/{list_id} — Rename a list."""
    db: Database = request.app[database_key]
    try:
        list_id = UUID(request.match_info["list_id"])
    except ValueError:
        return _error(400, "Invalid list ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return _error(404, "List not found")

    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    name = body.get("name", "").strip()
    if not name:
        return _error(400, "List name is required")

    client_updated_at = body.get("updated_at")
    if (
        client_updated_at is not None
        and not body.get("force")
        and client_updated_at < lst.updated_at
    ):
        return _conflict_response(_list_to_json(lst))

    lst.name = name
    lst.mark_updated()

    _schedule_save_and_refresh(request)
    return web.json_response({"id": str(lst.id), "name": lst.name, "updated_at": lst.updated_at})


async def handle_delete_list(request: web.Request) -> web.Response:
    """DELETE /api/lists/{list_id} — Soft-delete a list."""
    db: Database = request.app[database_key]
    try:
        list_id = UUID(request.match_info["list_id"])
    except ValueError:
        return _error(400, "Invalid list ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return _error(404, "List not found")

    try:
        body = await request.json()
    except Exception:
        body = {}
    client_updated_at = body.get("updated_at")
    if (
        client_updated_at is not None
        and not body.get("force")
        and client_updated_at < lst.updated_at
    ):
        return _conflict_response(_list_to_json(lst))

    lst.mark_deleted()

    _schedule_save_and_refresh(request)
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# Board / column handlers
# ---------------------------------------------------------------------------


async def handle_get_board(request: web.Request) -> web.Response:
    """GET /api/lists/{list_id}/board — Items grouped by kanban column."""
    db: Database = request.app[database_key]
    try:
        list_id = UUID(request.match_info["list_id"])
    except ValueError:
        return _error(400, "Invalid list ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return _error(404, "List not found")

    columns: dict[str, list[dict[str, Any]]] = {col: [] for col in lst.board_columns}
    for item in lst.active_items():
        if item.parent_id is not None:
            continue  # subtasks don't appear as top-level board cards
        col = item.board_column if item.board_column in columns else lst.board_columns[0]
        columns[col].append(_item_to_json(item))

    return web.json_response(
        {
            "id": str(lst.id),
            "name": lst.name,
            "board_columns": lst.board_columns,
            "wip_limits": lst.wip_limits,
            "updated_at": lst.updated_at,
            "columns": columns,
        }
    )


async def handle_update_columns(request: web.Request) -> web.Response:
    """PATCH /api/lists/{list_id}/columns — Manage board columns.

    Body actions:
      {"action": "add", "name": "Review"}
      {"action": "remove", "name": "Review"}
      {"action": "rename", "old_name": "Review", "new_name": "QA"}
      {"action": "reorder", "columns": ["To Do", "Review", "Done"]}
      {"action": "set_wip_limit", "name": "In Progress", "limit": 3}
    """
    db: Database = request.app[database_key]
    try:
        list_id = UUID(request.match_info["list_id"])
    except ValueError:
        return _error(400, "Invalid list ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return _error(404, "List not found")

    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    client_updated_at = body.get("updated_at")
    if (
        client_updated_at is not None
        and not body.get("force")
        and client_updated_at < lst.updated_at
    ):
        return _conflict_response(_list_to_json(lst))

    action = body.get("action", "")

    if action == "add":
        name = body.get("name", "").strip()
        if not name:
            return _error(400, "Column name is required")
        if name in lst.board_columns:
            return _error(400, "Column already exists")
        lst.board_columns.append(name)

    elif action == "remove":
        name = body.get("name", "").strip()
        if name not in lst.board_columns:
            return _error(404, "Column not found")
        if len(lst.board_columns) <= 3:
            return _error(400, "Cannot have fewer than 3 columns")
        if name == lst.board_columns[0]:
            return _error(400, "Cannot delete the first column (inbox)")
        if name == lst.board_columns[-1]:
            return _error(400, "Cannot delete the last column (completion)")
        fallback = lst.board_columns[0]
        for item in lst.active_items():
            if item.board_column == name:
                item.board_column = fallback
                item.mark_updated()
        lst.board_columns.remove(name)
        lst.wip_limits.pop(name, None)

    elif action == "rename":
        old_name = body.get("old_name", "").strip()
        new_name = body.get("new_name", "").strip()
        if not new_name:
            return _error(400, "New column name is required")
        if old_name not in lst.board_columns:
            return _error(404, "Column not found")
        if new_name in lst.board_columns:
            return _error(400, "Column name already exists")
        idx = lst.board_columns.index(old_name)
        lst.board_columns[idx] = new_name
        if old_name in lst.wip_limits:
            lst.wip_limits[new_name] = lst.wip_limits.pop(old_name)
        for item in lst.active_items():
            if item.board_column == old_name:
                item.board_column = new_name
                item.mark_updated()

    elif action == "reorder":
        columns = body.get("columns")
        if not isinstance(columns, list) or set(columns) != set(lst.board_columns):
            return _error(400, "Must provide all existing columns in new order")
        lst.board_columns = columns

    elif action == "set_wip_limit":
        name = body.get("name", "").strip()
        limit = int(body.get("limit", 0))
        if name not in lst.board_columns:
            return _error(404, "Column not found")
        if name == lst.board_columns[0] or name == lst.board_columns[-1]:
            return _error(400, "Cannot set WIP limit on first or last column")
        lst.set_wip_limit(name, limit)

    else:
        return _error(400, f"Unknown action: {action}")

    lst.mark_updated()
    _schedule_save_and_refresh(request)
    return web.json_response(
        {
            "board_columns": lst.board_columns,
            "wip_limits": lst.wip_limits,
            "updated_at": lst.updated_at,
        }
    )


# ---------------------------------------------------------------------------
# Item handlers
# ---------------------------------------------------------------------------


def _apply_item_fields(item: TodoItem, body: dict[str, Any], lst: TodoList | None = None) -> None:
    """Apply mutable fields from a request body to a TodoItem."""
    if "reminder" in body:
        item.reminder = str(body["reminder"]).strip()
    if "priority" in body:
        p = int(body["priority"])
        if p in (1, 2, 3):
            item.priority = p
    if "complete" in body:
        item.complete = bool(body["complete"])
    if "tags" in body and isinstance(body["tags"], list):
        item.tags = [str(t) for t in body["tags"]]
    if "due_date" in body:
        val = body["due_date"]
        item.due_date = date.fromisoformat(val) if val else None
    if "due_time" in body:
        val = body["due_time"]
        item.due_time = time.fromisoformat(val) if val else None
    if "board_column" in body:
        col = str(body["board_column"])
        if lst is None or col in lst.board_columns:
            item.board_column = col
    if "parent_id" in body:
        val = body["parent_id"]
        item.parent_id = UUID(val) if val else None
    if "estimated_pomodoros" in body:
        item.estimated_pomodoros = max(0, int(body["estimated_pomodoros"]))
    if "recurrence_type" in body:
        val = body["recurrence_type"]
        if val in ("minutely", "daily", "weekly", "monthly", "yearly", None):
            item.recurrence_type = val
    if "recurrence_interval" in body:
        item.recurrence_interval = max(1, int(body["recurrence_interval"]))
    if "recurrence_end_date" in body:
        val = body["recurrence_end_date"]
        item.recurrence_end_date = date.fromisoformat(val) if val else None
    if "recurrence_end_count" in body:
        val = body["recurrence_end_count"]
        item.recurrence_end_count = int(val) if val is not None else None


async def handle_create_item(request: web.Request) -> web.Response:
    """POST /api/lists/{list_id}/items — Add an item to a list.

    Accepts all item fields. When ``parse_nlp`` is true, the ``reminder``
    text is run through the NLP parser first and extracted fields are applied
    (explicit fields in the body override parsed values).
    """
    db: Database = request.app[database_key]
    try:
        list_id = UUID(request.match_info["list_id"])
    except ValueError:
        return _error(400, "Invalid list ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return _error(404, "List not found")

    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    reminder = body.get("reminder", "").strip()
    if not reminder:
        return _error(400, "Item reminder text is required")

    # NLP parsing: extract fields from natural language, then let explicit
    # body fields override.
    if body.get("parse_nlp"):
        from ..core.nlp_parser import parse as nlp_parse

        result = nlp_parse(reminder)
        item = create_todo_item(result.reminder)
        if result.due_date is not None:
            item.due_date = result.due_date
        if result.due_time is not None:
            item.due_time = result.due_time
        if result.priority is not None:
            item.priority = result.priority
        if result.tags:
            item.tags = result.tags
        if result.recurrence_type is not None:
            item.recurrence_type = result.recurrence_type
            item.recurrence_interval = result.recurrence_interval
            # Minutely recurrence needs a due_time — auto-set to now + interval
            if result.recurrence_type == "minutely" and item.due_time is None:
                next_dt = datetime.now() + timedelta(minutes=result.recurrence_interval)
                item.due_time = next_dt.time().replace(second=0, microsecond=0)
        if result.recurrence_end_date is not None:
            item.recurrence_end_date = result.recurrence_end_date
        if result.recurrence_end_count is not None:
            item.recurrence_end_count = result.recurrence_end_count
        if result.pomodoro_estimate is not None:
            item.estimated_pomodoros = result.pomodoro_estimate
    else:
        item = create_todo_item(reminder)

    # Explicit body fields override NLP results
    _apply_item_fields(item, {k: v for k, v in body.items() if k != "reminder"}, lst)

    # Assign default board column if not explicitly set
    if not item.board_column and lst.board_columns:
        item.board_column = lst.board_columns[0]

    lst.add_item(item)

    _schedule_save_and_refresh(request)
    return web.json_response(_item_to_json(item), status=201)


async def handle_update_item(request: web.Request) -> web.Response:
    """PUT /api/items/{item_id} — Update item fields."""
    db: Database = request.app[database_key]
    try:
        item_id = UUID(request.match_info["item_id"])
    except ValueError:
        return _error(400, "Invalid item ID")

    item, lst = _find_item_and_list(db, item_id)
    if item is None:
        return _error(404, "Item not found")

    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    client_updated_at = body.get("updated_at")
    if (
        client_updated_at is not None
        and not body.get("force")
        and client_updated_at < item.updated_at
    ):
        return _conflict_response(_item_to_json(item))

    _apply_item_fields(item, body, lst)
    item.mark_updated()

    _schedule_save_and_refresh(request)
    return web.json_response(_item_to_json(item))


async def handle_delete_item(request: web.Request) -> web.Response:
    """DELETE /api/items/{item_id} — Soft-delete an item."""
    db: Database = request.app[database_key]
    try:
        item_id = UUID(request.match_info["item_id"])
    except ValueError:
        return _error(400, "Invalid item ID")

    item = _find_item(db, item_id)
    if item is None:
        return _error(404, "Item not found")

    try:
        body = await request.json()
    except Exception:
        body = {}
    client_updated_at = body.get("updated_at")
    if (
        client_updated_at is not None
        and not body.get("force")
        and client_updated_at < item.updated_at
    ):
        return _conflict_response(_item_to_json(item))

    item.mark_deleted()

    _schedule_save_and_refresh(request)
    return web.json_response({"ok": True})


async def handle_toggle_item(request: web.Request) -> web.Response:
    """PATCH /api/items/{item_id}/toggle — Toggle item completion."""
    db: Database = request.app[database_key]
    try:
        item_id = UUID(request.match_info["item_id"])
    except ValueError:
        return _error(400, "Invalid item ID")

    item, lst = _find_item_and_list(db, item_id)
    if item is None:
        return _error(404, "Item not found")

    try:
        body = await request.json()
    except Exception:
        body = {}
    client_updated_at = body.get("updated_at")
    if (
        client_updated_at is not None
        and not body.get("force")
        and client_updated_at < item.updated_at
    ):
        return _conflict_response(_item_to_json(item))

    # Recurring item completion: mark complete for this cycle, let auto-advance
    # handle cycling to the next occurrence when the next due date arrives.
    already_exhausted = (
        item.recurrence_end_count is not None and item.recurrence_count >= item.recurrence_end_count
    )
    if item.is_recurring and not item.complete and not already_exhausted:
        item.complete = True
        item.recurrence_count += 1
    else:
        item.toggle_complete()

    # Sync board_column with completion state
    if lst and lst.board_columns:
        last_col = lst.board_columns[-1]
        if item.complete and item.board_column != last_col:
            item.board_column = last_col
        elif not item.complete and item.board_column == last_col:
            from ..gui.commands import _best_incomplete_column

            item.board_column = _best_incomplete_column(item, lst)

    _schedule_save_and_refresh(request)
    return web.json_response(_item_to_json(item))


async def handle_move_item(request: web.Request) -> web.Response:
    """PATCH /api/items/{item_id}/move — Move item to a kanban column."""
    db: Database = request.app[database_key]
    try:
        item_id = UUID(request.match_info["item_id"])
    except ValueError:
        return _error(400, "Invalid item ID")

    item, lst = _find_item_and_list(db, item_id)
    if item is None:
        return _error(404, "Item not found")

    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    client_updated_at = body.get("updated_at")
    if (
        client_updated_at is not None
        and not body.get("force")
        and client_updated_at < item.updated_at
    ):
        return _conflict_response(_item_to_json(item))

    column = body.get("column", "").strip()
    if not lst or column not in lst.board_columns:
        return _error(400, "Invalid column name")

    item.board_column = column
    item.mark_updated()

    _schedule_save_and_refresh(request)
    return web.json_response(_item_to_json(item))


async def handle_set_parent(request: web.Request) -> web.Response:
    """PATCH /api/items/{item_id}/parent — Set or clear parent_id (subtask management)."""
    db: Database = request.app[database_key]
    try:
        item_id = UUID(request.match_info["item_id"])
    except ValueError:
        return _error(400, "Invalid item ID")

    item = _find_item(db, item_id)
    if item is None:
        return _error(404, "Item not found")

    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    client_updated_at = body.get("updated_at")
    if (
        client_updated_at is not None
        and not body.get("force")
        and client_updated_at < item.updated_at
    ):
        return _conflict_response(_item_to_json(item))

    parent_id_str = body.get("parent_id")
    if parent_id_str:
        try:
            parent_id = UUID(parent_id_str)
        except ValueError:
            return _error(400, "Invalid parent ID")
        parent = _find_item(db, parent_id)
        if parent is None:
            return _error(404, "Parent item not found")
        if parent.parent_id is not None:
            return _error(400, "Cannot nest subtasks more than one level")
        if parent_id == item_id:
            return _error(400, "Item cannot be its own parent")
        item.parent_id = parent_id
    else:
        item.parent_id = None

    item.mark_updated()

    _schedule_save_and_refresh(request)
    return web.json_response(_item_to_json(item))


async def handle_restore_item(request: web.Request) -> web.Response:
    """PATCH /api/items/{item_id}/restore — Un-delete a soft-deleted item."""
    db: Database = request.app[database_key]
    try:
        item_id = UUID(request.match_info["item_id"])
    except ValueError:
        return _error(400, "Invalid item ID")

    try:
        body = await request.json()
    except Exception:
        body = {}

    # Search across all lists for the deleted item
    for lst in db.lists.values():
        if lst.deleted or lst.private:
            continue
        item = lst.items.get(item_id)
        if item and item.deleted:
            client_updated_at = body.get("updated_at")
            if (
                client_updated_at is not None
                and not body.get("force")
                and client_updated_at < item.updated_at
            ):
                return _conflict_response(_item_to_json(item))
            item.deleted = False
            item.mark_updated()
            lst.mark_updated()
            _schedule_save_and_refresh(request)
            return web.json_response(_item_to_json(item))

    return _error(404, "Deleted item not found")


# ---------------------------------------------------------------------------
# Trash handlers
# ---------------------------------------------------------------------------


async def handle_get_trash(request: web.Request) -> web.Response:
    """GET /api/trash — Return recently deleted items across all lists.

    Items remain as tombstones for 7 days before the sync engine
    garbage-collects them.  This endpoint lets the web UI offer a
    recovery path during that window.
    """
    db: Database = request.app[database_key]
    import time as _time

    now = int(_time.time() * 1000)
    ttl_ms = 7 * 24 * 60 * 60 * 1000  # 7 days

    result: list[dict[str, Any]] = []
    for lst in db.lists.values():
        if lst.deleted or lst.private:
            continue
        for item in lst.items.values():
            if item.deleted and (now - item.updated_at) < ttl_ms:
                entry = _item_to_json(item)
                entry["list_id"] = str(lst.id)
                entry["list_name"] = lst.name
                entry["deleted_ago_ms"] = now - item.updated_at
                result.append(entry)

    # Sort by most recently deleted first
    result.sort(key=lambda x: x["deleted_ago_ms"])
    return web.json_response({"items": result})


# ---------------------------------------------------------------------------
# Utility handlers
# ---------------------------------------------------------------------------


async def handle_parse(request: web.Request) -> web.Response:
    """POST /api/parse — Parse natural language text into structured fields."""
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    text = body.get("text", "").strip()
    if not text:
        return _error(400, "Text is required")

    from ..core.nlp_parser import parse as nlp_parse

    result = nlp_parse(text)

    return web.json_response(
        {
            "reminder": result.reminder,
            "due_date": result.due_date.isoformat() if result.due_date else None,
            "due_time": result.due_time.isoformat() if result.due_time else None,
            "priority": result.priority,
            "tags": result.tags,
            "recurrence_type": result.recurrence_type,
            "recurrence_interval": result.recurrence_interval,
            "recurrence_end_date": (
                result.recurrence_end_date.isoformat() if result.recurrence_end_date else None
            ),
            "recurrence_end_count": result.recurrence_end_count,
            "pomodoro_estimate": result.pomodoro_estimate,
            "spans": [
                {
                    "start": s.start,
                    "end": s.end,
                    "kind": s.kind.value,
                    "display": s.display,
                }
                for s in result.spans
            ],
        }
    )


async def handle_get_tags(request: web.Request) -> web.Response:
    """GET /api/tags — Return all known tags across non-private lists."""
    db: Database = request.app[database_key]
    tags: set[str] = set()
    for lst in db.lists.values():
        if lst.deleted or lst.private:
            continue
        for item in lst.active_items():
            tags.update(item.tags)
    return web.json_response({"tags": sorted(tags)})


async def handle_status(request: web.Request) -> web.Response:
    """GET /api/status — Return app status info."""
    db: Database = request.app[database_key]
    result: dict[str, Any] = {
        "version": settings.__version__,
        "list_count": sum(1 for lst in db.lists.values() if not lst.deleted),
        "total_items": db.total_items(),
        "total_completed": db.total_completed(),
    }
    # Include sort tiers if config manager is available
    cm = request.app.get(config_manager_key)
    if cm is not None:
        result["sort_tiers"] = [
            {"dimension": dim, "reverse": rev} for dim, rev in cm.config.database.sort_tiers()
        ]
    return web.json_response(result)


# ---------------------------------------------------------------------------
# Sort configuration handlers
# ---------------------------------------------------------------------------

_VALID_SORT_DIMENSIONS = {"completion", "due_date", "priority"}


async def handle_get_sort(request: web.Request) -> web.Response:
    """GET /api/sort — Return current three-tier sort configuration."""
    cm = request.app.get(config_manager_key)
    if cm is None:
        return _error(503, "Sort configuration not available")
    tiers = cm.config.database.sort_tiers()
    return web.json_response(
        {
            "sort_tiers": [{"dimension": dim, "reverse": rev} for dim, rev in tiers],
        }
    )


async def handle_update_sort(request: web.Request) -> web.Response:
    """PUT /api/sort — Update three-tier sort configuration.

    Body: {"tiers": [{"dimension": "completion", "reverse": false}, ...]}

    Validates:
      - Exactly 3 tiers
      - Each dimension is one of: completion, due_date, priority
      - All 3 dimensions are unique (no duplicates)
    """
    cm = request.app.get(config_manager_key)
    if cm is None:
        return _error(503, "Sort configuration not available")

    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    tiers = body.get("tiers")
    if not isinstance(tiers, list) or len(tiers) != 3:
        return _error(400, "Exactly 3 sort tiers are required")

    dimensions: list[str] = []
    reverses: list[bool] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            return _error(400, "Each tier must be an object with dimension and reverse")
        dim = tier.get("dimension", "")
        if dim not in _VALID_SORT_DIMENSIONS:
            return _error(400, f"Invalid sort dimension: {dim!r}")
        dimensions.append(dim)
        reverses.append(bool(tier.get("reverse", False)))

    if len(set(dimensions)) != 3:
        return _error(400, "All 3 sort dimensions must be unique")

    # Apply to config
    db_config = cm.config.database
    db_config.sort_tier1 = dimensions[0]
    db_config.sort_tier1_reverse = reverses[0]
    db_config.sort_tier2 = dimensions[1]
    db_config.sort_tier2_reverse = reverses[1]
    db_config.sort_tier3 = dimensions[2]
    db_config.sort_tier3_reverse = reverses[2]
    cm.save()

    _schedule_save_and_refresh(request)
    return web.json_response(
        {
            "sort_tiers": [
                {"dimension": dim, "reverse": rev}
                for dim, rev in zip(dimensions, reverses, strict=True)
            ],
        }
    )


# ---------------------------------------------------------------------------
# Board layout presets
# ---------------------------------------------------------------------------

_BOARD_PRESETS: dict[str, list[str]] = {
    "Simple": ["To Do", "In Progress", "Done"],
    "With Review": ["To Do", "In Progress", "Review", "Done"],
    "With Testing": ["To Do", "In Progress", "Review", "Testing", "Done"],
    "Backlog": ["Backlog", "To Do", "In Progress", "Done"],
}


async def handle_get_presets(request: web.Request) -> web.Response:
    """GET /api/presets — Return available board layout presets."""
    _ = request  # unused but required by aiohttp handler signature
    return web.json_response(
        {"presets": [{"name": name, "columns": cols} for name, cols in _BOARD_PRESETS.items()]}
    )


async def handle_apply_preset(request: web.Request) -> web.Response:
    """POST /api/lists/{list_id}/apply-preset — Apply a board layout preset.

    Body: {"columns": ["To Do", "In Progress", "Done"]}

    Smart item remapping:
      1. Exact column name match -> keep
      2. Last column -> new last column (completion mapping)
      3. Positional remapping for remaining items
      4. Unknown -> first column (inbox)
    """
    db: Database = request.app[database_key]
    try:
        list_id = UUID(request.match_info["list_id"])
    except ValueError:
        return _error(400, "Invalid list ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return _error(404, "List not found")

    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    client_updated_at = body.get("updated_at")
    if (
        client_updated_at is not None
        and not body.get("force")
        and client_updated_at < lst.updated_at
    ):
        return _conflict_response(_list_to_json(lst))

    new_columns = body.get("columns")
    if not isinstance(new_columns, list) or len(new_columns) < 2:
        return _error(400, "At least 2 columns are required")
    if len(new_columns) != len(set(new_columns)):
        return _error(400, "Column names must be unique")

    old_columns = list(lst.board_columns)
    new_set = set(new_columns)
    last_old = old_columns[-1] if old_columns else ""
    last_new = new_columns[-1]
    first_new = new_columns[0]
    old_index = {col: i for i, col in enumerate(old_columns)}
    old_len = max(len(old_columns) - 1, 1)
    new_len = max(len(new_columns) - 1, 1)

    remapped = 0
    for item in lst.active_items():
        if item.parent_id is not None:
            continue
        if item.board_column in new_set:
            continue  # Column still exists
        if item.board_column == last_old and last_new:
            item.board_column = last_new
            item.mark_updated()
            remapped += 1
        elif item.board_column in old_index:
            rel_pos = old_index[item.board_column] / old_len
            new_idx = round(rel_pos * new_len)
            new_idx = max(0, min(new_idx, len(new_columns) - 1))
            item.board_column = new_columns[new_idx]
            item.mark_updated()
            remapped += 1
        else:
            item.board_column = first_new
            item.mark_updated()
            remapped += 1

    # Clear WIP limits for removed columns
    for col in old_columns:
        if col not in new_set:
            lst.set_wip_limit(col, 0)

    lst.board_columns = list(new_columns)
    lst.mark_updated()

    _schedule_save_and_refresh(request)
    return web.json_response(
        {
            "board_columns": lst.board_columns,
            "wip_limits": lst.wip_limits,
            "updated_at": lst.updated_at,
            "remapped": remapped,
        }
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _apply_filters(items: list[TodoItem], query: Any) -> list[TodoItem]:
    """Filter items based on query-string parameters."""
    # Text search
    q = query.get("q", "").strip().lower()
    if q:
        items = [i for i in items if q in i.reminder.lower()]

    # Tag filter (comma-separated, match ANY)
    tags_param = query.get("tags", "").strip()
    if tags_param:
        filter_tags = {t.strip() for t in tags_param.split(",") if t.strip()}
        items = [i for i in items if filter_tags & set(i.tags)]

    # Priority filter (comma-separated)
    priority_param = query.get("priority", "").strip()
    if priority_param:
        try:
            priorities = {int(p.strip()) for p in priority_param.split(",")}
            items = [i for i in items if i.priority in priorities]
        except ValueError:
            pass

    # Status filter
    status = query.get("status", "all").strip().lower()
    if status == "active":
        items = [i for i in items if not i.complete]
    elif status == "completed":
        items = [i for i in items if i.complete]

    # Due filter
    due = query.get("due", "").strip().lower()
    if due == "overdue":
        items = [i for i in items if not i.complete and is_overdue(i.due_date, i.due_time)]
    elif due == "today":
        from ..core.models import is_due_today

        items = [i for i in items if is_due_today(i.due_date)]
    elif due == "week":
        from ..core.models import is_due_this_week

        items = [i for i in items if is_due_this_week(i.due_date)]
    elif due == "none":
        items = [i for i in items if i.due_date is None]

    return items


def _find_item(db: Database, item_id: UUID) -> TodoItem | None:
    """Find an item by ID across all non-private lists."""
    for lst in db.lists.values():
        if lst.deleted or lst.private:
            continue
        item = lst.items.get(item_id)
        if item and not item.deleted:
            return item
    return None


def _find_item_and_list(db: Database, item_id: UUID) -> tuple[TodoItem | None, TodoList | None]:
    """Find an item and its containing list by ID across all non-private lists."""
    for lst in db.lists.values():
        if lst.deleted or lst.private:
            continue
        item = lst.items.get(item_id)
        if item and not item.deleted:
            return item, lst
    return None, None


async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    """GET /ws — WebSocket endpoint for real-time push updates."""
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)

    clients = request.app.get(ws_clients_key)
    if clients is not None:
        clients.add(ws)

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.ERROR:
                break
    finally:
        if clients is not None:
            clients.discard(ws)

    return ws


async def handle_pair(request: web.Request) -> web.Response:
    """POST /api/auth — Validate a 6-digit pairing PIN and return the auth token."""
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

    pin = str(body.get("pin", "")).strip()
    if not pin:
        return _error(400, "PIN is required")

    server = request.app.get(web_server_key)
    if server is None:
        return _error(503, "Pairing not available")

    client_ip = request.remote or ""
    if server.check_pin_rate_limit(client_ip):
        return _error(429, "Too many attempts — try again in 60 seconds")

    token = server.validate_pin(pin, client_ip)
    if token is None:
        return _error(401, "Invalid or expired PIN")

    return web.json_response({"token": token})


async def handle_auto_login(request: web.Request) -> web.Response:
    """GET /auth/{token} — Auto-login page that stores token and redirects."""
    import secrets as _secrets

    url_token = request.match_info["token"]
    server = request.app.get(web_server_key)
    real_token = server.auth_token if server else request.app.get(auth_token_key, "")

    if not real_token or url_token != real_token:
        return web.Response(
            text="<html><body><h2>Invalid or expired link</h2></body></html>",
            content_type="text/html",
            status=403,
        )

    nonce = _secrets.token_urlsafe(16)
    return web.Response(
        text=(
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>PyTodo-Qt</title></head><body>"
            f"<script nonce='{nonce}'>"
            f"localStorage.setItem('pytodo_auth_token','{url_token}');"
            "location.href='/';"
            "</script>"
            "<p>Connecting...</p></body></html>"
        ),
        content_type="text/html",
        headers={
            "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'",
        },
    )


async def handle_ca_cert_download(request: web.Request) -> web.Response:
    """GET /ca.pem — Download the local CA certificate for device installation."""
    server = request.app.get(web_server_key)
    if server is None:
        return _error(404, "CA certificate not available")
    ca_path = server.ca_cert_path
    if ca_path is None or not ca_path.exists():
        return _error(404, "CA certificate not available")
    return web.Response(
        body=ca_path.read_bytes(),
        content_type="application/x-pem-file",
        headers={
            "Content-Disposition": 'attachment; filename="PyTodo-Qt-CA.pem"',
        },
    )


async def _broadcast_refresh(clients: set[web.WebSocketResponse]) -> None:
    """Send a refresh event to all connected WebSocket clients."""
    msg = '{"event":"refresh"}'
    closed = []
    for ws in clients:
        try:
            await ws.send_str(msg)
        except Exception:
            closed.append(ws)
    for ws in closed:
        clients.discard(ws)


def _schedule_save_and_refresh(request: web.Request) -> None:
    """Schedule database save and UI refresh on the Qt event loop."""
    save_callback = request.app.get(save_callback_key)
    if save_callback:
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(0, save_callback)

    # Broadcast refresh to WebSocket clients
    clients = request.app.get(ws_clients_key)
    if clients:
        import asyncio

        asyncio.ensure_future(_broadcast_refresh(clients))
