"""REST API handlers for the embedded web server.

All handlers operate on the in-memory Database object directly (safe because
the aiohttp server runs on the same qasync event loop as Qt). After writes,
a UI refresh is scheduled via QTimer.singleShot(0, ...).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from aiohttp import web

from ..core import settings
from ..core.models import TodoItem, TodoList, create_todo_item, create_todo_list

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..core.models import Database

# Typed app keys (shared with server.py, defined here to avoid circular imports)
database_key: web.AppKey[Database] = web.AppKey("database")
save_callback_key: web.AppKey[Callable[[], None]] = web.AppKey("save_callback")


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
        "pomodoro_count": item.pomodoro_count,
        "estimated_pomodoros": item.estimated_pomodoros,
        "is_recurring": item.is_recurring,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _error(status: int, message: str) -> web.Response:
    """Return a JSON error response."""
    return web.json_response({"error": message, "status": status}, status=status)


def setup_routes(app: web.Application) -> None:
    """Register all API routes on the aiohttp application."""
    app.router.add_get("/api/lists", handle_get_lists)
    app.router.add_get("/api/lists/{list_id}", handle_get_list)
    app.router.add_post("/api/lists", handle_create_list)
    app.router.add_put("/api/lists/{list_id}", handle_rename_list)
    app.router.add_delete("/api/lists/{list_id}", handle_delete_list)
    app.router.add_post("/api/lists/{list_id}/items", handle_create_item)
    app.router.add_put("/api/items/{item_id}", handle_update_item)
    app.router.add_delete("/api/items/{item_id}", handle_delete_item)
    app.router.add_patch("/api/items/{item_id}/toggle", handle_toggle_item)
    app.router.add_get("/api/status", handle_status)


async def handle_get_lists(request: web.Request) -> web.Response:
    """GET /api/lists — Return all non-private lists with item counts."""
    db: Database = request.app[database_key]
    result = []
    for lst in db.lists.values():
        if lst.deleted or lst.private:
            continue
        result.append(
            {
                "id": str(lst.id),
                "name": lst.name,
                "item_count": lst.active_item_count(),
                "completed_count": sum(1 for i in lst.active_items() if i.complete),
                "is_private": False,
            }
        )
    return web.json_response({"lists": result})


async def handle_get_list(request: web.Request) -> web.Response:
    """GET /api/lists/{list_id} — Return a single list with all items."""
    db: Database = request.app[database_key]
    try:
        list_id = UUID(request.match_info["list_id"])
    except ValueError:
        return _error(400, "Invalid list ID")

    lst = db.get_list(list_id)
    if lst is None or lst.deleted or lst.private:
        return _error(404, "List not found")

    items = [_item_to_json(item) for item in lst.active_items()]
    return web.json_response(
        {
            "id": str(lst.id),
            "name": lst.name,
            "items": items,
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

    lst.name = name
    lst.mark_updated()

    _schedule_save_and_refresh(request)
    return web.json_response({"id": str(lst.id), "name": lst.name})


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

    lst.mark_deleted()

    _schedule_save_and_refresh(request)
    return web.json_response({"ok": True})


async def handle_create_item(request: web.Request) -> web.Response:
    """POST /api/lists/{list_id}/items — Add an item to a list."""
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

    item = create_todo_item(reminder)
    if "priority" in body:
        p = int(body["priority"])
        if p in (1, 2, 3):
            item.priority = p
    if "tags" in body and isinstance(body["tags"], list):
        item.tags = [str(t) for t in body["tags"]]
    # Assign default board column for kanban view consistency
    if lst.board_columns:
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

    item = _find_item(db, item_id)
    if item is None:
        return _error(404, "Item not found")

    try:
        body = await request.json()
    except Exception:
        return _error(400, "Invalid JSON body")

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


async def handle_status(request: web.Request) -> web.Response:
    """GET /api/status — Return app status info."""
    db: Database = request.app[database_key]
    return web.json_response(
        {
            "version": settings.__version__,
            "list_count": sum(1 for lst in db.lists.values() if not lst.deleted),
            "total_items": db.total_items(),
            "total_completed": db.total_completed(),
        }
    )


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


def _schedule_save_and_refresh(request: web.Request) -> None:
    """Schedule database save and UI refresh on the Qt event loop."""
    save_callback = request.app.get(save_callback_key)
    if save_callback:
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(0, save_callback)
