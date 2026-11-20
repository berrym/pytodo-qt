"""Tests for the Web UI REST API.

Covers:
- List CRUD (create, read, update, delete)
- Item CRUD (create, read, update, delete)
- Toggle completion
- Private list exclusion
- Error handling (404, 400)
- Status endpoint
- WebConfig serialization
- Phase 1 API expansion: parse, board, move, tags, columns, parent, filters
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from uuid import UUID

import pytest
from aiohttp import WSCloseCode, WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from pytodo_qt.core.config import AppConfig, ConfigManager, WebConfig
from pytodo_qt.core.models import (
    Database,
    create_todo_item,
    create_todo_list,
)
from pytodo_qt.web.api import database_key, ws_clients_key
from pytodo_qt.web.server import WebServer

# ===========================================================================
# WebConfig tests
# ===========================================================================


class TestWebConfig:
    def test_defaults(self):
        config = WebConfig()
        assert config.enabled is False
        assert config.port == 8080

    def test_app_config_has_web(self):
        config = AppConfig()
        assert isinstance(config.web, WebConfig)
        assert config.web.enabled is False

    def test_toml_roundtrip(self):
        import tomllib

        config = AppConfig()
        config.web.enabled = True
        config.web.port = 9090
        toml_str = config.to_toml()
        data = tomllib.loads(toml_str)
        restored = AppConfig.from_dict(data)
        assert restored.web.enabled is True
        assert restored.web.port == 9090

    def test_from_dict_missing_web(self):
        config = AppConfig.from_dict({})
        assert config.web.enabled is False
        assert config.web.port == 8080


# ===========================================================================
# Test fixtures
# ===========================================================================


def _make_db_with_data() -> Database:
    """Create a test database with sample data."""
    db = Database()

    lst1 = create_todo_list("Shopping")
    lst1.add_item(create_todo_item("Buy milk"))
    lst1.add_item(create_todo_item("Buy bread"))
    item3 = create_todo_item("Buy eggs")
    item3.complete = True
    lst1.add_item(item3)
    db.add_list(lst1)

    lst2 = create_todo_list("Work")
    lst2.add_item(create_todo_item("Write report"))
    db.add_list(lst2)

    return db


def _make_db_with_private() -> Database:
    """Create a test database with a private list."""
    db = _make_db_with_data()

    private = create_todo_list("Secret")
    private.private = True
    private.add_item(create_todo_item("Hidden task"))
    db.add_list(private)

    return db


async def _make_client(
    db: Database | None = None,
    config_manager: ConfigManager | None = None,
) -> TestClient:
    """Create an aiohttp test client with the given database."""
    if db is None:
        db = _make_db_with_data()

    ws = WebServer(database=db, config_manager=config_manager)
    app = ws.create_app()
    return TestClient(TestServer(app))


# ===========================================================================
# List API tests
# ===========================================================================


class TestGetLists:
    @pytest.mark.asyncio
    async def test_get_lists(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/lists")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["lists"]) == 2
            names = {lst["name"] for lst in data["lists"]}
            assert names == {"Shopping", "Work"}
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_lists_excludes_private(self):
        db = _make_db_with_private()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/lists")
            data = await resp.json()
            names = {lst["name"] for lst in data["lists"]}
            assert "Secret" not in names
            assert len(data["lists"]) == 2
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_lists_has_counts(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/lists")
            data = await resp.json()
            shopping = next(lst for lst in data["lists"] if lst["name"] == "Shopping")
            assert shopping["item_count"] == 3
            assert shopping["completed_count"] == 1
            assert "overdue_count" in shopping
            assert "board_columns" in shopping
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_lists_excludes_deleted(self):
        db = _make_db_with_data()
        # Delete one list
        for lst in db.lists.values():
            if lst.name == "Work":
                lst.mark_deleted()
                break
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/lists")
            data = await resp.json()
            assert len(data["lists"]) == 1
        finally:
            await client.close()


class TestGetList:
    @pytest.mark.asyncio
    async def test_get_list(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{list_id}")
            assert resp.status == 200
            data = await resp.json()
            assert data["id"] == list_id
            assert "items" in data
            assert "board_columns" in data
            assert "wip_limits" in data
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_list_not_found(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/lists/00000000-0000-0000-0000-000000000000")
            assert resp.status == 404
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_list_invalid_id(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/lists/not-a-uuid")
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_list_private_returns_404(self):
        db = _make_db_with_private()
        private_id = None
        for lst in db.lists.values():
            if lst.private:
                private_id = str(lst.id)
                break
        assert private_id is not None
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{private_id}")
            assert resp.status == 404
        finally:
            await client.close()


class TestCreateList:
    @pytest.mark.asyncio
    async def test_create_list(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post("/api/lists", json={"name": "New List"})
            assert resp.status == 201
            data = await resp.json()
            assert data["name"] == "New List"
            assert "id" in data
            # Verify it's in the database
            assert len(db.lists) == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_list_empty_name(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post("/api/lists", json={"name": ""})
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_list_no_body(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post("/api/lists", data=b"not json")
            assert resp.status == 400
        finally:
            await client.close()


class TestRenameList:
    @pytest.mark.asyncio
    async def test_rename_list(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(f"/api/lists/{list_id}", json={"name": "Renamed"})
            assert resp.status == 200
            data = await resp.json()
            assert data["name"] == "Renamed"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_rename_list_not_found(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                "/api/lists/00000000-0000-0000-0000-000000000000",
                json={"name": "X"},
            )
            assert resp.status == 404
        finally:
            await client.close()


class TestDeleteList:
    @pytest.mark.asyncio
    async def test_delete_list(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.delete(f"/api/lists/{list_id}")
            assert resp.status == 200
        finally:
            await client.close()


# ===========================================================================
# Item API tests
# ===========================================================================


class TestCreateItem:
    @pytest.mark.asyncio
    async def test_create_item(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": "New item"},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["reminder"] == "New item"
            assert data["priority"] == 2  # default normal
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_with_priority(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": "Urgent", "priority": 1},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["priority"] == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_with_tags(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": "Tagged", "tags": ["@work"]},
            )
            assert resp.status == 201
            data = await resp.json()
            assert "@work" in data["tags"]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_empty_reminder(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": ""},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_list_not_found(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                "/api/lists/00000000-0000-0000-0000-000000000000/items",
                json={"reminder": "X"},
            )
            assert resp.status == 404
        finally:
            await client.close()


class TestUpdateItem:
    @pytest.mark.asyncio
    async def test_update_item_reminder(self):
        db = _make_db_with_data()
        # Get first item from first list
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item_id = str(item.id)

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item_id}",
                json={"reminder": "Updated text"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["reminder"] == "Updated text"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_item_priority(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item_id = str(item.id)

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item_id}",
                json={"priority": 1},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["priority"] == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_item_not_found(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                "/api/items/00000000-0000-0000-0000-000000000000",
                json={"reminder": "X"},
            )
            assert resp.status == 404
        finally:
            await client.close()


class TestDeleteItem:
    @pytest.mark.asyncio
    async def test_delete_item(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item_id = str(item.id)

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.delete(f"/api/items/{item_id}")
            assert resp.status == 200
            # Item should be soft-deleted
            assert item.deleted is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_delete_item_not_found(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.delete("/api/items/00000000-0000-0000-0000-000000000000")
            assert resp.status == 404
        finally:
            await client.close()


class TestToggleItem:
    @pytest.mark.asyncio
    async def test_toggle_item(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(i for i in lst.active_items() if not i.complete)
        item_id = str(item.id)

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(f"/api/items/{item_id}/toggle")
            assert resp.status == 200
            data = await resp.json()
            assert data["complete"] is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_toggle_item_again(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(i for i in lst.active_items() if i.complete)
        item_id = str(item.id)

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(f"/api/items/{item_id}/toggle")
            assert resp.status == 200
            data = await resp.json()
            assert data["complete"] is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_toggle_item_not_found(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch("/api/items/00000000-0000-0000-0000-000000000000/toggle")
            assert resp.status == 404
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_toggle_item_writes_completed_at(self):
        """Toggling an incomplete item via the API writes a completed_at timestamp."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(i for i in lst.active_items() if not i.complete)
        item_id = str(item.id)
        assert item.completed_at is None

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(f"/api/items/{item_id}/toggle")
            assert resp.status == 200
            data = await resp.json()
            assert data["complete"] is True
            assert data["completed_at"] is not None
            assert data["completed_at"] > 0
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_put_complete_writes_completed_at(self):
        """PUT /api/items/{id} with `complete: true` generates a completed_at timestamp."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(i for i in lst.active_items() if not i.complete)
        item_id = str(item.id)
        assert item.completed_at is None

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(f"/api/items/{item_id}", json={"complete": True})
            assert resp.status == 200
            data = await resp.json()
            assert data["complete"] is True
            assert data["completed_at"] is not None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_put_complete_false_clears_completed_at(self):
        """PUT with `complete: false` clears completed_at to None."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.complete = True
        item.completed_at = 1_700_000_000_000
        item_id = str(item.id)

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(f"/api/items/{item_id}", json={"complete": False})
            assert resp.status == 200
            data = await resp.json()
            assert data["complete"] is False
            assert data["completed_at"] is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_put_with_explicit_completed_at_preserves_value(self):
        """Sync mode: PUT with both `complete` and `completed_at` preserves the timestamp verbatim."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(i for i in lst.active_items() if not i.complete)
        item_id = str(item.id)

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item_id}",
                json={"complete": True, "completed_at": 1_650_000_000_000},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["complete"] is True
            assert data["completed_at"] == 1_650_000_000_000  # exact, not regenerated
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_item_json_includes_completed_at(self):
        """List item JSON includes completed_at field."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.complete = True
        item.completed_at = 1_700_000_000_000
        item_id = str(item.id)
        list_id = str(lst.id)

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{list_id}")
            assert resp.status == 200
            data = await resp.json()
            items = data.get("items", [])
            target = next((it for it in items if it["id"] == item_id), None)
            assert target is not None
            assert "completed_at" in target
            assert target["completed_at"] == 1_700_000_000_000
        finally:
            await client.close()


# ===========================================================================
# Status endpoint
# ===========================================================================


class TestItemPomodoroFields:
    @pytest.mark.asyncio
    async def test_item_includes_pomodoro_fields(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.pomodoro_count = 3
        item.estimated_pomodoros = 6
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            assert resp.status == 200
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["pomodoro_count"] == 3
            assert found["estimated_pomodoros"] == 6
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_item_pomodoro_defaults_zero(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": "Fresh item"},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["pomodoro_count"] == 0
            assert data["estimated_pomodoros"] == 0
        finally:
            await client.close()


class TestStatus:
    @pytest.mark.asyncio
    async def test_status(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/status")
            assert resp.status == 200
            data = await resp.json()
            assert "version" in data
            assert data["list_count"] == 2
            assert data["total_items"] >= 4
        finally:
            await client.close()


# ===========================================================================
# Static file serving
# ===========================================================================


class TestStaticServing:
    @pytest.mark.asyncio
    async def test_index_page(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/")
            assert resp.status == 200
            text = await resp.text()
            assert "PyTodo-Qt" in text
        finally:
            await client.close()


# ===========================================================================
# WebServer lifecycle
# ===========================================================================


class TestWebServerLifecycle:
    @pytest.mark.asyncio
    async def test_create_app(self):
        db = Database()
        server = WebServer(database=db)
        app = server.create_app()
        assert app is not None
        assert app[database_key] is db

    @pytest.mark.asyncio
    async def test_create_app_with_callback(self):
        db = Database()
        called = []
        server = WebServer(database=db, save_callback=lambda: called.append(1))
        app = server.create_app()
        from pytodo_qt.web.api import save_callback_key

        assert app[save_callback_key] is not None


# ===========================================================================
# Phase 1: _item_to_json expanded fields
# ===========================================================================


class TestItemJsonFields:
    @pytest.mark.asyncio
    async def test_item_includes_board_column(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.board_column = "In Progress"
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["board_column"] == "In Progress"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_item_includes_recurrence_fields(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.recurrence_type = "weekly"
        item.recurrence_interval = 2
        item.recurrence_count = 3
        item.recurrence_end_count = 10
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["recurrence_type"] == "weekly"
            assert found["recurrence_interval"] == 2
            assert found["recurrence_count"] == 3
            assert found["recurrence_end_count"] == 10
            assert found["recurrence_end_date"] is None
            assert found["is_recurring"] is True
        finally:
            await client.close()


class TestItemBarFields:
    """The serialized item carries the temporal window and lifecycle
    state used by calendar views — origin/end millisecond timestamps,
    the window kind enum, and the current lifecycle state. These let
    the web frontend render the same Gantt-style bars as the desktop
    without re-implementing the layout pipeline in JavaScript."""

    @pytest.mark.asyncio
    async def test_no_due_date_yields_null_bar_fields(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = None
        item.due_time = None
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["bar_origin_ms"] is None
            assert found["bar_end_ms"] is None
            assert found["bar_kind"] is None
            assert found["bar_state"] is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_all_day_window(self):
        from datetime import date as _date

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2030, 6, 15)
        item.due_time = None
        item.due_time_end = None
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["bar_kind"] == "all_day"
            assert found["bar_origin_ms"] is not None
            assert found["bar_end_ms"] is not None
            # Window spans exactly 24 hours.
            assert found["bar_end_ms"] - found["bar_origin_ms"] == 86_400_000
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_event_window(self):
        from datetime import date as _date
        from datetime import time as _time

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2030, 6, 15)
        item.due_time = _time(14, 0)
        item.due_time_end = _time(16, 0)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["bar_kind"] == "event"
            # 2-hour window.
            assert found["bar_end_ms"] - found["bar_origin_ms"] == 2 * 3_600_000
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_workback_window(self):
        from datetime import date as _date
        from datetime import time as _time

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2030, 6, 15)
        item.due_time = _time(14, 0)
        item.due_time_end = None
        item.estimated_minutes = 90
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["bar_kind"] == "workback"
            # 90-minute window backed off from the deadline.
            assert found["bar_end_ms"] - found["bar_origin_ms"] == 90 * 60_000
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_deadline_from_created_window(self):
        from datetime import date as _date
        from datetime import time as _time

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2030, 6, 15)
        item.due_time = _time(14, 0)
        item.due_time_end = None
        item.estimated_minutes = 0
        item.estimated_pomodoros = 0
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["bar_kind"] == "deadline_from_created"
            assert found["bar_origin_ms"] is not None
            assert found["bar_end_ms"] is not None
            assert found["bar_end_ms"] > found["bar_origin_ms"]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_future_state(self):
        from datetime import date as _date

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2099, 1, 1)
        item.due_time = None
        item.complete = False
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["bar_state"] == "future"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_overdue_state(self):
        from datetime import date as _date

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2000, 1, 1)
        item.due_time = None
        item.complete = False
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["bar_state"] == "overdue_active"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_completed_state(self):
        from datetime import date as _date
        from datetime import datetime as _datetime
        from datetime import time as _time

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2030, 6, 15)
        item.due_time = _time(14, 0)
        item.due_time_end = None
        item.estimated_minutes = 0
        item.complete = True
        # Completed an hour before the deadline → "early".
        early = _datetime.combine(item.due_date, _time(13, 0))
        item.completed_at = int(early.timestamp() * 1000)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["bar_state"] == "completed_early"
        finally:
            await client.close()


class TestEffectiveTimeBlock:
    """The serialized item carries a resolved time block label: either
    the stored due_time_block when the parser or a deliberate edit set
    one, or a value derived from the due_time hour against the active
    TimeBlockConfig. The web frontend reads this field directly rather
    than replicating the derivation rules in JavaScript."""

    @pytest.mark.asyncio
    async def test_stored_block_passes_through(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_time_block = "late_afternoon"
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["effective_time_block"] == "late_afternoon"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_derived_from_hour_when_block_missing(self):
        from datetime import time as _time

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_time_block = None
        # 15:00 falls into the default afternoon range [12, 17) past
        # the midpoint, so it should resolve to late_afternoon.
        item.due_time = _time(15, 0)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["effective_time_block"] == "late_afternoon"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_stored_wins_over_derivation(self):
        from datetime import time as _time

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        # Explicit block and an hour that would derive to a different
        # block — the stored value wins.
        item.due_time_block = "evening"
        item.due_time = _time(9, 0)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["effective_time_block"] == "evening"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_null_when_no_anchor(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_time_block = None
        item.due_time = None
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            found = next(i for i in data["items"] if i["id"] == str(item.id))
            assert found["effective_time_block"] is None
        finally:
            await client.close()


class TestCalendarSegments:
    """The hour-grid calendar endpoint returns bar segments ready for
    client-side Canvas 2D rendering. Segments come from the same pure
    layout pipeline the desktop uses, so the web and desktop calendars
    land on identical positions and lifecycle colors for every task."""

    @pytest.mark.asyncio
    async def test_response_shape(self):
        from datetime import date as _date
        from datetime import time as _time

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2030, 6, 15)
        item.due_time = _time(14, 0)
        item.estimated_minutes = 60

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/calendar/segments?start=2030-06-13&days=7")
            assert resp.status == 200
            data = await resp.json()
            assert data["start_date"] == "2030-06-13"
            assert data["end_date"] == "2030-06-19"
            assert "items" in data
            assert isinstance(data["items"], dict)
            assert "days" in data
            assert len(data["days"]) == 7
            for day in data["days"]:
                assert "date" in day
                assert "segments" in day
                assert isinstance(day["segments"], list)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_day_view(self):
        from datetime import date as _date
        from datetime import time as _time

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2030, 6, 15)
        item.due_time = _time(14, 0)
        item.estimated_minutes = 60

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/calendar/segments?start=2030-06-15&days=1")
            data = await resp.json()
            assert len(data["days"]) == 1
            assert data["days"][0]["date"] == "2030-06-15"
            # Should contain at least one segment for our item on its
            # due date.
            segments = data["days"][0]["segments"]
            matching = [s for s in segments if s["item_id"] == str(item.id)]
            assert len(matching) >= 1
            seg = matching[0]
            # Workback from 14:00 with a 60-minute estimate → 13:00..14:00.
            assert seg["start_minute"] == 13 * 60
            assert seg["end_minute"] == 14 * 60
            assert seg["state"] in (
                "future",
                "in_work_window",
                "due_now",
                "overdue_active",
            )
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_items_deduplicated(self):
        from datetime import date as _date

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        # All-day item should appear on exactly one day and the items
        # dict should carry it exactly once.
        item.due_date = _date(2030, 6, 16)
        item.due_time = None
        item.due_time_end = None

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/calendar/segments?start=2030-06-15&days=3")
            data = await resp.json()
            assert str(item.id) in data["items"]
            # The items dict key appears once regardless of how many
            # days reference it.
            item_count = sum(1 for k in data["items"] if k == str(item.id))
            assert item_count == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_defaults(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            # No query params → defaults to today for 7 days.
            resp = await client.get("/api/calendar/segments")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["days"]) == 7
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_invalid_start_date(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/calendar/segments?start=not-a-date")
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_days_clamped(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            # days=100 should clamp to 31.
            resp = await client.get("/api/calendar/segments?start=2030-06-15&days=100")
            data = await resp.json()
            assert len(data["days"]) == 31
            # days=0 should clamp to 1.
            resp2 = await client.get("/api/calendar/segments?start=2030-06-15&days=0")
            data2 = await resp2.json()
            assert len(data2["days"]) == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_a_bar_finished_late_carries_its_zone(self):
        """The page draws the zone from the minutes the layout gives:
        a bar due at 15:00 and finished at 16:20 runs on to 16:20, and
        its zone is that stretch."""
        from datetime import date as _date
        from datetime import datetime as _datetime
        from datetime import time as _time

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2020, 6, 15)
        item.due_time = _time(15, 0)
        item.estimated_minutes = 60
        item.complete = True
        item.completed_at = int(_datetime(2020, 6, 15, 16, 20).timestamp() * 1000)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/calendar/segments?start=2020-06-15&days=1")
            data = await resp.json()
        finally:
            await client.close()
        seg = next(s for s in data["days"][0]["segments"] if s["item_id"] == str(item.id))
        assert seg["state"] == "completed_late"
        assert (seg["start_minute"], seg["end_minute"]) == (14 * 60, 16 * 60 + 20)
        assert (seg["zone_start_minute"], seg["zone_end_minute"]) == (15 * 60, 16 * 60 + 20)

    @pytest.mark.asyncio
    async def test_bars_that_share_hours_carry_their_lanes(self):
        """The page draws bars that share time side by side, in the
        lanes the layout gives (#88): 09:00-10:00 and 09:30-11:00 are
        lanes 0 and 1 of 2, and a bar at noon has the width to itself."""
        from datetime import date as _date
        from datetime import time as _time

        from pytodo_qt.core.models import create_todo_item

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        made = {}
        for text, start, end in (
            ("Lane first", _time(9, 0), _time(10, 0)),
            ("Lane second", _time(9, 30), _time(11, 0)),
            ("Lane alone", _time(12, 0), _time(13, 0)),
        ):
            item = create_todo_item(text, due_date=_date(2030, 6, 15), due_time=start)
            item.due_time_end = end
            lst.add_item(item)
            made[text] = str(item.id)
        whole_day = create_todo_item("Lane without a time", due_date=_date(2030, 6, 15))
        lst.add_item(whole_day)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/calendar/segments?start=2030-06-15&days=1")
            data = await resp.json()
        finally:
            await client.close()
        by_item = {s["item_id"]: s for s in data["days"][0]["segments"]}
        assert (by_item[made["Lane first"]]["lane"], by_item[made["Lane first"]]["lanes"]) == (0, 2)
        assert (by_item[made["Lane second"]]["lane"], by_item[made["Lane second"]]["lanes"]) == (
            1,
            2,
        )
        assert (by_item[made["Lane alone"]]["lane"], by_item[made["Lane alone"]]["lanes"]) == (0, 1)
        # A chip of the rows above the hours has no lane.
        chip = by_item[str(whole_day.id)]
        assert chip["is_all_day"] is True
        assert (chip["lane"], chip["lanes"]) == (None, None)

    @pytest.mark.asyncio
    async def test_lanes_are_of_one_day(self):
        """Bars at the same hours of two days share no time."""
        from datetime import date as _date
        from datetime import time as _time

        from pytodo_qt.core.models import create_todo_item

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        ids = []
        for day in (15, 16):
            item = create_todo_item(
                f"Day {day}", due_date=_date(2030, 6, day), due_time=_time(9, 0)
            )
            item.due_time_end = _time(10, 0)
            lst.add_item(item)
            ids.append(str(item.id))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/calendar/segments?start=2030-06-15&days=2")
            data = await resp.json()
        finally:
            await client.close()
        for day, item_id in zip(data["days"], ids, strict=True):
            seg = next(s for s in day["segments"] if s["item_id"] == item_id)
            assert (seg["lane"], seg["lanes"]) == (0, 1)

    @pytest.mark.asyncio
    async def test_a_bar_without_a_zone_has_null_for_it(self):
        from datetime import date as _date
        from datetime import time as _time

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = _date(2030, 6, 15)
        item.due_time = _time(15, 0)
        item.estimated_minutes = 60
        item.complete = False
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/calendar/segments?start=2030-06-15&days=1")
            data = await resp.json()
        finally:
            await client.close()
        seg = next(s for s in data["days"][0]["segments"] if s["item_id"] == str(item.id))
        assert seg["zone_start_minute"] is None
        assert seg["zone_end_minute"] is None

    @staticmethod
    def _two_lists_with_a_task_each():
        """Each of the two lists has one task due on 2030-06-15."""
        from datetime import date as _date

        db = _make_db_with_data()
        first, second = list(db.lists.values())[:2]
        ours = next(iter(first.active_items()))
        theirs = next(iter(second.active_items()))
        for item in (ours, theirs):
            item.due_date = _date(2030, 6, 15)
        return db, first, second, ours, theirs

    @pytest.mark.asyncio
    async def test_without_a_list_the_bars_of_every_list_are_returned(self):
        db, _first, _second, ours, theirs = self._two_lists_with_a_task_each()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/calendar/segments?start=2030-06-15&days=1")
            data = await resp.json()
        finally:
            await client.close()
        assert {str(ours.id), str(theirs.id)} <= set(data["items"])

    @pytest.mark.asyncio
    async def test_a_list_is_given_its_own_bars_only(self):
        """The web page asks for the list chosen in its header: a bar of
        another list could not be opened there."""
        db, first, second, ours, theirs = self._two_lists_with_a_task_each()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(
                f"/api/calendar/segments?start=2030-06-15&days=1&list_id={first.id}"
            )
            assert resp.status == 200
            mine = await resp.json()
            resp = await client.get(
                f"/api/calendar/segments?start=2030-06-15&days=1&list_id={second.id}"
            )
            other = await resp.json()
        finally:
            await client.close()
        assert set(mine["items"]) == {str(ours.id)}
        assert {seg["item_id"] for seg in mine["days"][0]["segments"]} == {str(ours.id)}
        assert set(other["items"]) == {str(theirs.id)}

    @pytest.mark.asyncio
    async def test_a_list_that_is_unknown_private_or_deleted_is_not_found(self):
        db = _make_db_with_private()
        private = next(lst for lst in db.lists.values() if lst.private)
        deleted = next(lst for lst in db.lists.values() if not lst.private)
        deleted.deleted = True
        client = await _make_client(db)
        await client.start_server()
        try:
            for list_id in (
                "00000000-0000-0000-0000-000000000099",
                str(private.id),
                str(deleted.id),
            ):
                resp = await client.get(f"/api/calendar/segments?list_id={list_id}")
                assert resp.status == 404, list_id
            resp = await client.get("/api/calendar/segments?list_id=not-an-id")
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_private_list_excluded(self):
        from datetime import date as _date

        db = _make_db_with_private()
        # The private list's item gets a due date to make sure it's
        # actively excluded rather than just filtered by absence.
        for lst in db.lists.values():
            if lst.private:
                for item in lst.active_items():
                    item.due_date = _date(2030, 6, 15)

        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/calendar/segments?start=2030-06-15&days=1")
            data = await resp.json()
            # None of the items in the response should come from the
            # private list.
            for lst in db.lists.values():
                if not lst.private:
                    continue
                for item in lst.active_items():
                    assert str(item.id) not in data["items"]
        finally:
            await client.close()


# ===========================================================================
# Phase 1: NLP parse endpoint
# ===========================================================================


class TestParseEndpoint:
    @pytest.mark.asyncio
    async def test_parse_simple(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post("/api/parse", json={"text": "Buy groceries tomorrow"})
            assert resp.status == 200
            data = await resp.json()
            assert "reminder" in data
            assert data["due_date"] is not None
            assert "spans" in data
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_parse_with_priority_and_tag(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                "/api/parse",
                json={"text": "Fix bug p1 @work"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["priority"] == 1
            assert "@work" in data["tags"]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_parse_reports_an_advance_reminder(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                "/api/parse",
                json={"text": "Pay rent tomorrow remind me daily 3 days before"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["reminder"] == "Pay rent"
            assert data["remind_before_days"] == 3
            assert data["reminder_cadence"] == "daily_until_due"
            kinds = {span["kind"]: span["display"] for span in data["spans"]}
            assert kinds["advance_reminder"] == "Remind daily from 3 days before"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_parse_without_an_advance_reminder(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post("/api/parse", json={"text": "Pay rent tomorrow"})
            data = await resp.json()
            assert data["remind_before_days"] == 0
            assert data["reminder_cadence"] == "none"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_parse_empty_text(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post("/api/parse", json={"text": ""})
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post("/api/parse", data=b"not json")
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_parse_recurrence(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                "/api/parse",
                json={"text": "Standup every day"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["recurrence_type"] == "daily"
        finally:
            await client.close()


# ===========================================================================
# Phase 1: Create item with NLP and extended fields
# ===========================================================================


class TestCreateItemExtended:
    @pytest.mark.asyncio
    async def test_create_item_with_nlp(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": "Buy groceries tomorrow p1 @errands", "parse_nlp": True},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["priority"] == 1
            assert "@errands" in data["tags"]
            assert data["due_date"] is not None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_with_due_date(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": "Deadline task", "due_date": "2026-04-01"},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["due_date"] == "2026-04-01"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_with_due_time(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={
                    "reminder": "Meeting",
                    "due_date": "2026-04-01",
                    "due_time": "14:30:00",
                },
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["due_date"] == "2026-04-01"
            assert data["due_time"] == "14:30:00"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_with_recurrence(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={
                    "reminder": "Weekly standup",
                    "recurrence_type": "weekly",
                    "recurrence_interval": 1,
                    "due_date": "2026-03-16",
                },
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["recurrence_type"] == "weekly"
            assert data["recurrence_interval"] == 1
            assert data["is_recurring"] is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_with_parent(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        parent = next(iter(lst.active_items()))
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": "Subtask", "parent_id": str(parent.id)},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["parent_id"] == str(parent.id)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_with_estimated_pomodoros(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": "Big task", "estimated_pomodoros": 4},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["estimated_pomodoros"] == 4
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_with_nlp_keeps_an_advance_reminder(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={
                    "reminder": "Pay rent tomorrow remind me 3 days before",
                    "parse_nlp": True,
                },
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["reminder"] == "Pay rent"
            assert data["due_date"] is not None
            assert data["remind_before_days"] == 3
            assert data["reminder_cadence"] == "once"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_with_nlp_drops_an_advance_reminder_without_a_date(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": "Pay rent remind me 3 days before", "parse_nlp": True},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["reminder"] == "Pay rent"
            assert data["due_date"] is None
            assert data["remind_before_days"] == 0
            assert data["reminder_cadence"] == "none"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_with_nlp_advance_reminder_and_a_date_in_the_body(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={
                    "reminder": "Pay rent remind me 3 days before",
                    "parse_nlp": True,
                    "due_date": "2030-01-15",
                },
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["due_date"] == "2030-01-15"
            assert data["remind_before_days"] == 3
            assert data["reminder_cadence"] == "once"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_explicit_advance_reminder_overrides_the_text(self):
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={
                    "reminder": "Pay rent tomorrow remind me 3 days before",
                    "parse_nlp": True,
                    "remind_before_days": 5,
                    "reminder_cadence": "daily_until_due",
                },
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["remind_before_days"] == 5
            assert data["reminder_cadence"] == "daily_until_due"
        finally:
            await client.close()

    async def _quick_add(self, text: str, **extra):
        """Post ``text`` to the first list as the web page's add box does.
        Returns (response JSON, the list as stored)."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/items",
                json={"reminder": text, "parse_nlp": True, **extra},
            )
            assert resp.status == 201
            return await resp.json(), lst
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_quick_add_keeps_the_end_of_a_time_range(self):
        data, _ = await self._quick_add("Standup tomorrow 9am to 10am")
        assert data["reminder"] == "Standup"
        assert data["due_time"] == "09:00:00"
        assert data["due_time_end"] == "10:00:00"

    @pytest.mark.asyncio
    async def test_quick_add_keeps_a_time_block(self):
        data, _ = await self._quick_add("Laundry tomorrow morning")
        assert data["reminder"] == "Laundry"
        assert data["due_time_block"] == "morning"
        assert data["due_date"] is not None

    @pytest.mark.asyncio
    async def test_quick_add_keeps_an_estimate(self):
        data, _ = await self._quick_add("Write essay ~2h")
        assert data["reminder"] == "Write essay"
        assert data["estimated_minutes"] == 120

    @pytest.mark.asyncio
    async def test_quick_add_keeps_a_session_length(self):
        data, _ = await self._quick_add("Deep focus session length 50 minutes")
        assert data["work_duration"] == 50

    @pytest.mark.asyncio
    async def test_quick_add_keeps_an_event_date(self):
        data, _ = await self._quick_add("Book appointment for friday")
        assert data["event_date"] is not None

    @pytest.mark.asyncio
    async def test_quick_add_keeps_a_condition(self):
        data, _ = await self._quick_add("Go running unless it rains")
        assert data["conditions"] == [{"type": "unless", "expression": "it rains"}]

    @pytest.mark.asyncio
    async def test_quick_add_without_those_fields_leaves_them_unset(self):
        data, _ = await self._quick_add("Buy stamps")
        assert data["due_time_end"] is None
        assert data["due_time_block"] is None
        assert data["event_date"] is None
        assert data["estimated_minutes"] == 0
        assert data["work_duration"] == 0
        assert not data["conditions"]

    @pytest.mark.asyncio
    async def test_explicit_field_overrides_the_parsed_one(self):
        data, _ = await self._quick_add("Write essay ~2h", estimated_minutes=45)
        assert data["estimated_minutes"] == 45

    @pytest.mark.asyncio
    async def test_quick_add_creates_inline_subtasks(self):
        data, lst = await self._quick_add("Tomorrow p1 pack: socks, charger")
        assert data["reminder"] == "pack"
        parent = lst.items[UUID(data["id"])]
        children = [item for item in lst.items.values() if item.parent_id == parent.id]
        assert sorted(child.reminder for child in children) == ["charger", "socks"]

    @pytest.mark.asyncio
    async def test_subtasks_take_the_parents_priority_date_and_column(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        lst.board_columns = ["Backlog", "Doing"]
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/items",
                json={"reminder": "Tomorrow at 3pm p1 pack: socks, charger", "parse_nlp": True},
            )
            data = await resp.json()
        finally:
            await client.close()
        parent = lst.items[UUID(data["id"])]
        children = [item for item in lst.items.values() if item.parent_id == parent.id]
        assert len(children) == 2
        for child in children:
            assert child.priority == 1
            assert child.due_date == parent.due_date
            assert child.due_time == parent.due_time
            assert child.board_column == "Backlog"

    @pytest.mark.asyncio
    async def test_subtasks_follow_an_explicit_override_of_the_parent(self):
        data, lst = await self._quick_add("p1 pack: socks, charger", priority=3)
        children = [item for item in lst.items.values() if item.parent_id == UUID(data["id"])]
        assert [child.priority for child in children] == [3, 3]

    @pytest.mark.asyncio
    async def test_no_subtasks_without_the_inline_form(self):
        data, lst = await self._quick_add("Pack socks tomorrow")
        assert not [item for item in lst.items.values() if item.parent_id == UUID(data["id"])]

    @pytest.mark.asyncio
    async def test_an_item_added_as_a_subtask_gets_no_subtasks_of_its_own(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        existing = next(iter(lst.items.values()))
        before = len(lst.items)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/items",
                json={
                    "reminder": "Pack: socks, charger",
                    "parse_nlp": True,
                    "parent_id": str(existing.id),
                },
            )
            assert resp.status == 201
        finally:
            await client.close()
        assert len(lst.items) == before + 1

    @pytest.mark.asyncio
    async def test_text_is_stored_as_typed_without_parsing(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        before = len(lst.items)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/items", json={"reminder": "Pack: socks, charger"}
            )
            data = await resp.json()
        finally:
            await client.close()
        assert data["reminder"] == "Pack: socks, charger"
        assert len(lst.items) == before + 1

    @pytest.mark.asyncio
    async def test_with_the_desktop_running_the_item_and_its_subtasks_are_one_undo_step(self):
        """With a main window, the item goes through its undo stack with
        its subtasks, in one step: they are saved together."""
        from pytodo_qt.web.api import main_window_key

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        pushed = []

        class Stack:
            def push(self, command) -> None:
                pushed.append(command)
                command.redo()

        class Window:
            _database = db
            _undo_stack = Stack()

            def _save_database(self) -> None:
                pass

            def _refresh_ui(self) -> None:
                pass

        client = await _make_client(db)
        client.server.app[main_window_key] = Window()
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/items",
                json={"reminder": "Pack: socks, charger", "parse_nlp": True},
            )
            data = await resp.json()
        finally:
            await client.close()
        assert [command._item.reminder for command in pushed] == ["Pack"]
        children = pushed[0]._children
        assert [child.reminder for child in children] == ["socks", "charger"]
        assert [child.parent_id for child in children] == [UUID(data["id"])] * 2
        assert len([item for item in lst.items.values() if item.parent_id]) == 2

    @pytest.mark.asyncio
    async def test_create_item_nlp_with_override(self):
        """Explicit body fields override NLP-extracted values."""
        db = _make_db_with_data()
        list_id = str(next(iter(db.lists)))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={
                    "reminder": "Buy groceries p1",
                    "parse_nlp": True,
                    "priority": 3,  # override NLP-extracted p1
                },
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["priority"] == 3
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_create_item_gets_default_board_column(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{list_id}/items",
                json={"reminder": "New task"},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["board_column"] == lst.board_columns[0]
        finally:
            await client.close()


# ===========================================================================
# Phase 1: Update item extended fields
# ===========================================================================


class TestAddWithAnIdOfThePages:
    """The page gives an item its id, and may deliver the same add more
    than once: its answer was lost, or the request was given up while
    the server was silent. An id is created once (#117)."""

    ID = "7b0d6f0e-6c1b-4a54-9f0f-2f9b1c5a8d11"

    async def _post(self, client, lst, body):
        resp = await client.post(f"/api/lists/{lst.id}/items", json=body)
        return resp.status, await resp.json()

    @pytest.mark.asyncio
    async def test_the_item_is_created_under_the_id_given(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            status, data = await self._post(
                client, lst, {"reminder": "Feed the cat", "id": self.ID}
            )
        finally:
            await client.close()
        assert status == 201
        assert data["id"] == self.ID
        assert lst.items[UUID(self.ID)].reminder == "Feed the cat"
        assert UUID(self.ID) in db.web_added_ids

    @pytest.mark.asyncio
    async def test_a_second_delivery_creates_nothing(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        before = len(lst.items)
        client = await _make_client(db)
        await client.start_server()
        try:
            body = {"reminder": "Feed the cat", "id": self.ID}
            first = await self._post(client, lst, body)
            second = await self._post(client, lst, body)
            third = await self._post(client, lst, body)
        finally:
            await client.close()
        assert first[0] == 201
        assert second == (200, {"id": self.ID, "already_added": True})
        assert third == second
        assert len(lst.items) == before + 1

    @pytest.mark.asyncio
    async def test_two_deliveries_at_once_create_one_item(self):
        import asyncio

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        before = len(lst.items)
        client = await _make_client(db)
        await client.start_server()
        try:
            body = {"reminder": "Feed the cat", "id": self.ID}
            both = await asyncio.gather(
                self._post(client, lst, body), self._post(client, lst, body)
            )
        finally:
            await client.close()
        assert sorted(status for status, _ in both) == [200, 201]
        assert len(lst.items) == before + 1

    @pytest.mark.asyncio
    async def test_the_subtasks_in_the_text_are_created_with_the_first_delivery_only(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        before = len(lst.items)
        client = await _make_client(db)
        await client.start_server()
        try:
            body = {"reminder": "Pack: socks, charger", "parse_nlp": True, "id": self.ID}
            await self._post(client, lst, body)
            status, data = await self._post(client, lst, body)
        finally:
            await client.close()
        assert (status, data) == (200, {"id": self.ID, "already_added": True})
        assert len(lst.items) == before + 3
        children = [item for item in lst.items.values() if item.parent_id == UUID(self.ID)]
        assert sorted(child.reminder for child in children) == ["charger", "socks"]

    @pytest.mark.asyncio
    async def test_the_answer_is_the_same_whatever_became_of_the_item(self):
        """Deleted, gone for good, or in a list the page may not see: the
        answer has the id and nothing else of the item."""
        db = _make_db_with_data()
        lst, other = list(db.lists.values())[:2]
        client = await _make_client(db)
        await client.start_server()
        try:
            body = {"reminder": "Feed the cat", "id": self.ID}
            await self._post(client, lst, body)
            item = lst.items[UUID(self.ID)]
            expected = (200, {"id": self.ID, "already_added": True})

            item.mark_deleted()
            assert await self._post(client, lst, body) == expected
            assert item.deleted is True

            # Collected after its time as a deleted record.
            del lst.items[item.id]
            assert await self._post(client, lst, body) == expected
            assert UUID(self.ID) not in lst.items

            # Moved to a private list.
            item.deleted = False
            other.private = True
            other.items[item.id] = item
            assert await self._post(client, lst, body) == expected
            # And asked for at that list: it is not served at all.
            resp = await client.post(f"/api/lists/{other.id}/items", json=body)
            assert resp.status == 404
        finally:
            await client.close()
        assert UUID(self.ID) not in lst.items

    @pytest.mark.asyncio
    async def test_an_id_that_an_item_made_elsewhere_has_is_not_given_to_another(self):
        db = _make_db_with_data()
        lst, other = list(db.lists.values())[:2]
        taken = next(iter(other.items.values()))
        before = len(lst.items)
        client = await _make_client(db)
        await client.start_server()
        try:
            status, data = await self._post(
                client, lst, {"reminder": "Feed the cat", "id": str(taken.id)}
            )
            # The same where that item is in a list the page may not see.
            other.private = True
            hidden = await self._post(
                client, lst, {"reminder": "Feed the cat", "id": str(taken.id)}
            )
        finally:
            await client.close()
        assert (status, data) == (200, {"id": str(taken.id), "already_added": True})
        assert hidden == (status, data)
        assert len(lst.items) == before
        assert taken.reminder == "Write report"

    @pytest.mark.asyncio
    async def test_an_id_that_is_no_uuid_is_refused(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        before = len(lst.items)
        client = await _make_client(db)
        await client.start_server()
        try:
            for bad in ("not-an-id", "", 17, ["x"]):
                status, data = await self._post(
                    client, lst, {"reminder": "Feed the cat", "id": bad}
                )
                assert status == 400, bad
                assert data["error"] == "Invalid item ID"
        finally:
            await client.close()
        assert len(lst.items) == before
        assert db.web_added_ids == {}

    @pytest.mark.asyncio
    async def test_without_an_id_the_server_makes_one_as_before(self):
        """A page of an earlier version, still open in a tab."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        before = len(lst.items)
        client = await _make_client(db)
        await client.start_server()
        try:
            first = await self._post(client, lst, {"reminder": "Feed the cat"})
            second = await self._post(client, lst, {"reminder": "Feed the cat", "id": None})
        finally:
            await client.close()
        assert first[0] == second[0] == 201
        assert first[1]["id"] != second[1]["id"]
        assert len(lst.items) == before + 2
        assert db.web_added_ids == {}

    @pytest.mark.asyncio
    async def test_the_id_is_not_taken_for_a_field_of_the_item(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            status, data = await self._post(
                client, lst, {"reminder": "Feed the cat", "id": self.ID, "priority": 1}
            )
        finally:
            await client.close()
        assert status == 201
        assert data["priority"] == 1
        assert data["reminder"] == "Feed the cat"

    @pytest.mark.asyncio
    async def test_a_subtask_is_added_under_an_item_that_is_there(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        parent = next(iter(lst.items.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            status, data = await self._post(
                client, lst, {"reminder": "Oat", "id": self.ID, "parent_id": str(parent.id)}
            )
        finally:
            await client.close()
        assert status == 201
        assert data["parent_id"] == str(parent.id)

    @pytest.mark.asyncio
    async def test_a_subtask_of_an_item_that_is_gone_is_added_at_the_top_level(self):
        """As the subtasks of a deleted item go to the top level: nothing
        the person typed is lost, and nothing is refused."""
        db = _make_db_with_data()
        lst, other = list(db.lists.values())[:2]
        deleted = next(iter(lst.items.values()))
        deleted.mark_deleted()
        elsewhere = next(iter(other.items.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            cases = {
                "deleted": str(deleted.id),
                "unknown": "0d5c2f3a-1a2b-4c3d-8e9f-001122334455",
                "of another list": str(elsewhere.id),
            }
            for number, (what, parent_id) in enumerate(cases.items()):
                status, data = await self._post(
                    client,
                    lst,
                    {
                        "reminder": "Oat " + what,
                        "id": self.ID[:-1] + str(number),
                        "parent_id": parent_id,
                    },
                )
                assert status == 201, what
                assert data["parent_id"] is None, what
        finally:
            await client.close()
        assert deleted.deleted is True

    @pytest.mark.asyncio
    async def test_without_the_desktop_a_deleted_items_subtasks_go_to_the_top_level(self):
        """As the desktop's own delete does it: they are not left under
        an item that is gone, where the page would draw them nowhere."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        lst.board_columns = ["To Do", "Done"]
        parent, child, other = list(lst.items.values())[:3]
        child.parent_id = parent.id
        child.board_column = ""
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.delete(f"/api/items/{parent.id}", json={})
            assert resp.status == 200
        finally:
            await client.close()
        assert parent.deleted is True
        assert child.parent_id is None
        assert child.deleted is False
        assert child.board_column == "To Do"
        assert other.parent_id is None

    @pytest.mark.asyncio
    async def test_with_the_desktop_running_a_second_delivery_is_no_undo_step(self):
        from pytodo_qt.web.api import main_window_key

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        pushed = []
        saves = []

        class Stack:
            def push(self, command) -> None:
                pushed.append(command)
                command.redo()

        class Window:
            _database = db
            _undo_stack = Stack()

            def _save_database(self) -> None:
                # What a save stores: the id is on record by now.
                saves.append(UUID(TestAddWithAnIdOfThePages.ID) in db.web_added_ids)

            def _refresh_ui(self) -> None:
                pass

        client = await _make_client(db)
        client.server.app[main_window_key] = Window()
        await client.start_server()
        try:
            body = {"reminder": "Pack: socks, charger", "parse_nlp": True, "id": self.ID}
            first = await self._post(client, lst, body)
            second = await self._post(client, lst, body)
        finally:
            await client.close()
        assert first[0] == 201
        assert second == (200, {"id": self.ID, "already_added": True})
        assert len(pushed) == 1
        # One save for the item, its two subtasks and the record of its id.
        assert saves == [True]


class TestUpdateItemExtended:
    @pytest.mark.asyncio
    async def test_update_due_date(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"due_date": "2026-05-01"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["due_date"] == "2026-05-01"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_due_time(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"due_time": "09:00:00"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["due_time"] == "09:00:00"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_clear_due_date(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = date(2026, 5, 1)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"due_date": None},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["due_date"] is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_board_column(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.board_column = "To Do"
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"board_column": "In Progress"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["board_column"] == "In Progress"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_recurrence(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={
                    "recurrence_type": "monthly",
                    "recurrence_interval": 2,
                    "recurrence_end_count": 6,
                },
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["recurrence_type"] == "monthly"
            assert data["recurrence_interval"] == 2
            assert data["recurrence_end_count"] == 6
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_estimated_pomodoros(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"estimated_pomodoros": 5},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["estimated_pomodoros"] == 5
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_parent_id(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        parent = items[0]
        child = items[1]
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{child.id}",
                json={"parent_id": str(parent.id)},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["parent_id"] == str(parent.id)
        finally:
            await client.close()


class TestUpdateV18Fields:
    """Tests for v18 field CRUD via web API."""

    @pytest.mark.asyncio
    async def test_update_time_block(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"due_time_block": "evening"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["due_time_block"] == "evening"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_event_date(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"event_date": "2026-06-15"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["event_date"] == "2026-06-15"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_estimated_minutes(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"estimated_minutes": 120},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["estimated_minutes"] == 120
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_work_break_durations(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"work_duration": 45, "break_duration": 10, "long_break_duration": 20},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["work_duration"] == 45
            assert data["break_duration"] == 10
            assert data["long_break_duration"] == 20
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_clear_time_block(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_time_block = "morning"
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"due_time_block": None},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["due_time_block"] is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_v18_fields_in_get_response(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_time_block = "afternoon"
        item.event_date = date(2026, 7, 1)
        item.estimated_minutes = 90
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            assert resp.status == 200
            data = await resp.json()
            found = [i for i in data["items"] if i["id"] == str(item.id)]
            assert len(found) == 1
            assert found[0]["due_time_block"] == "afternoon"
            assert found[0]["event_date"] == "2026-07-01"
            assert found[0]["estimated_minutes"] == 90
        finally:
            await client.close()


# ===========================================================================
# Board endpoint
# ===========================================================================


class TestUpdateAdvanceReminder:
    """The day count and the cadence are stored as a consistent pair."""

    @staticmethod
    async def _put(stored: tuple[int, str], body: dict) -> tuple[int, str]:
        """Send ``body`` for an item holding ``stored``; return what the
        response reports, having checked that the item holds the same."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.due_date = date.today() + timedelta(days=30)
        item.remind_before_days, item.reminder_cadence = stored
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(f"/api/items/{item.id}", json=body)
            assert resp.status == 200
            data = await resp.json()
        finally:
            await client.close()
        reported = (data["remind_before_days"], data["reminder_cadence"])
        assert (item.remind_before_days, item.reminder_cadence) == reported
        return reported

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("stored", "body", "expected"),
        [
            # Both fields, as the page sends them.
            ((0, "none"), {"remind_before_days": 3, "reminder_cadence": "once"}, (3, "once")),
            (
                (3, "once"),
                {"remind_before_days": 14, "reminder_cadence": "daily_until_due"},
                (14, "daily_until_due"),
            ),
            ((3, "once"), {"remind_before_days": 0, "reminder_cadence": "none"}, (0, "none")),
            # Off stores no day count, whatever count comes with it.
            ((3, "once"), {"remind_before_days": 7, "reminder_cadence": "none"}, (0, "none")),
            ((3, "once"), {"reminder_cadence": "none"}, (0, "none")),
            # The count is held to 1-90 while a cadence is chosen.
            ((0, "none"), {"remind_before_days": 500, "reminder_cadence": "once"}, (90, "once")),
            ((0, "none"), {"remind_before_days": 90, "reminder_cadence": "once"}, (90, "once")),
            ((0, "none"), {"remind_before_days": 91, "reminder_cadence": "once"}, (90, "once")),
            ((0, "none"), {"remind_before_days": 0, "reminder_cadence": "once"}, (1, "once")),
            ((0, "none"), {"remind_before_days": -4, "reminder_cadence": "once"}, (1, "once")),
            # One field alone is read with the stored other.
            ((0, "none"), {"reminder_cadence": "daily_until_due"}, (1, "daily_until_due")),
            ((3, "once"), {"reminder_cadence": "daily_until_due"}, (3, "daily_until_due")),
            ((3, "once"), {"remind_before_days": 10}, (10, "once")),
            ((3, "once"), {"remind_before_days": 0}, (1, "once")),
            ((3, "once"), {"remind_before_days": 365}, (90, "once")),
            ((0, "none"), {"remind_before_days": 10}, (0, "none")),
            # A cadence that is not one of the three is ignored.
            ((3, "once"), {"reminder_cadence": "hourly"}, (3, "once")),
            ((0, "none"), {"remind_before_days": 5, "reminder_cadence": "hourly"}, (0, "none")),
        ],
    )
    async def test_the_pair_is_stored_consistently(self, stored, body, expected):
        assert await self._put(stored, body) == expected

    @pytest.mark.asyncio
    async def test_an_edit_to_another_field_leaves_a_stored_pair_alone(self):
        """A pair stored before the rule existed is not rewritten by an
        edit that does not mention the reminder."""
        assert await self._put((400, "once"), {"priority": 1}) == (400, "once")

    @pytest.mark.asyncio
    async def test_clearing_the_due_date_keeps_the_reminder(self):
        """The reminder lies dormant without a due date, as on the
        desktop, and is there again when a date is put back."""
        assert await self._put((3, "once"), {"due_date": None}) == (3, "once")

    @pytest.mark.asyncio
    async def test_create_holds_an_explicit_count_to_the_range(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/items",
                json={
                    "reminder": "Renew passport",
                    "due_date": "2027-03-01",
                    "remind_before_days": 500,
                    "reminder_cadence": "once",
                },
            )
            assert resp.status == 201
            data = await resp.json()
        finally:
            await client.close()
        assert (data["remind_before_days"], data["reminder_cadence"]) == (90, "once")


class TestBoardEndpoint:
    @pytest.mark.asyncio
    async def test_get_board(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        # Assign items to columns
        items = list(lst.active_items())
        items[0].board_column = "To Do"
        items[1].board_column = "In Progress"
        items[2].board_column = "Done"
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}/board")
            assert resp.status == 200
            data = await resp.json()
            assert "columns" in data
            assert "board_columns" in data
            assert "wip_limits" in data
            assert set(data["columns"].keys()) == {"To Do", "In Progress", "Done"}
            assert len(data["columns"]["To Do"]) == 1
            assert len(data["columns"]["In Progress"]) == 1
            assert len(data["columns"]["Done"]) == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_board_excludes_subtasks_as_top_level(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        parent = items[0]
        parent.board_column = "To Do"
        # Add a subtask
        subtask = create_todo_item("Child task")
        subtask.parent_id = parent.id
        subtask.board_column = "To Do"
        lst.add_item(subtask)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}/board")
            data = await resp.json()
            # Subtask should NOT appear as a top-level card
            all_ids = []
            for col_items in data["columns"].values():
                all_ids.extend(i["id"] for i in col_items)
            assert str(subtask.id) not in all_ids
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_board_includes_subtasks_nested(self):
        """Board cards include subtasks array for parent items."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        parent = items[0]
        parent.board_column = "To Do"
        # Add subtasks
        sub1 = create_todo_item("Subtask 1")
        sub1.parent_id = parent.id
        sub1.complete = True
        lst.add_item(sub1)
        sub2 = create_todo_item("Subtask 2")
        sub2.parent_id = parent.id
        lst.add_item(sub2)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}/board")
            data = await resp.json()
            # Find the parent card
            parent_card = None
            for col_items in data["columns"].values():
                for c in col_items:
                    if c["id"] == str(parent.id):
                        parent_card = c
                        break
            assert parent_card is not None
            assert "subtasks" in parent_card
            assert len(parent_card["subtasks"]) == 2
            sub_ids = {s["id"] for s in parent_card["subtasks"]}
            assert str(sub1.id) in sub_ids
            assert str(sub2.id) in sub_ids
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_board_not_found(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/lists/00000000-0000-0000-0000-000000000000/board")
            assert resp.status == 404
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_board_unknown_column_falls_to_first(self):
        """Items with unrecognized board_column are placed in the first column."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.board_column = "Nonexistent Column"
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}/board")
            data = await resp.json()
            first_col = data["board_columns"][0]
            ids_in_first = [i["id"] for i in data["columns"][first_col]]
            assert str(item.id) in ids_in_first
        finally:
            await client.close()


# ===========================================================================
# Phase 1: Column management endpoint
# ===========================================================================


class TestColumnManagement:
    @pytest.mark.asyncio
    async def test_add_column(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "add", "name": "Review"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert "Review" in data["board_columns"]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_add_duplicate_column(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "add", "name": "To Do"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_remove_column(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        lst.board_columns = ["To Do", "In Progress", "Review", "Done"]
        item = next(iter(lst.active_items()))
        item.board_column = "Review"
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "remove", "name": "Review"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert "Review" not in data["board_columns"]
            # Item should have been moved to first column (inbox)
            assert item.board_column == "To Do"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_remove_first_column_fails(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        lst.board_columns = ["To Do", "In Progress", "Review", "Done"]
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "remove", "name": "To Do"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_remove_last_column_fails(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "remove", "name": "Done"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_remove_below_min_3_fails(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        # Default is 3 columns — can't remove any middle column
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "remove", "name": "In Progress"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_wip_limit_first_column_fails(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "set_wip_limit", "name": "To Do", "limit": 3},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_wip_limit_last_column_fails(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "set_wip_limit", "name": "Done", "limit": 3},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_rename_column(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.board_column = "In Progress"
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "rename", "old_name": "In Progress", "new_name": "Doing"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert "Doing" in data["board_columns"]
            assert "In Progress" not in data["board_columns"]
            # Item should have been renamed
            assert item.board_column == "Doing"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_reorder_columns(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "reorder", "columns": ["Done", "In Progress", "To Do"]},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["board_columns"] == ["Done", "In Progress", "To Do"]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_reorder_columns_mismatch(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "reorder", "columns": ["Done", "To Do"]},  # missing one
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_set_wip_limit(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "set_wip_limit", "name": "In Progress", "limit": 3},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["wip_limits"]["In Progress"] == 3
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "explode"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_rename_column_preserves_wip_limit(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        lst.set_wip_limit("In Progress", 5)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "rename", "old_name": "In Progress", "new_name": "Doing"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["wip_limits"].get("Doing") == 5
            assert "In Progress" not in data["wip_limits"]
        finally:
            await client.close()


# ===========================================================================
# Phase 1: Move item to column
# ===========================================================================


class TestMoveItem:
    @pytest.mark.asyncio
    async def test_move_item(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.board_column = "To Do"
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{item.id}/move",
                json={"column": "In Progress"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["board_column"] == "In Progress"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_move_item_invalid_column(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{item.id}/move",
                json={"column": "Nonexistent"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_move_item_not_found(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                "/api/items/00000000-0000-0000-0000-000000000000/move",
                json={"column": "Done"},
            )
            assert resp.status == 404
        finally:
            await client.close()


# ===========================================================================
# Phase 1: Set parent (subtask management)
# ===========================================================================


class TestSetParent:
    @pytest.mark.asyncio
    async def test_set_parent(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        parent = items[0]
        child = items[1]
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{child.id}/parent",
                json={"parent_id": str(parent.id)},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["parent_id"] == str(parent.id)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_clear_parent(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        child = items[1]
        child.parent_id = items[0].id
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{child.id}/parent",
                json={"parent_id": None},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["parent_id"] is None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_set_parent_prevents_nesting(self):
        """Cannot make a subtask of a subtask."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        grandparent = items[0]
        parent = items[1]
        parent.parent_id = grandparent.id
        child = items[2]
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{child.id}/parent",
                json={"parent_id": str(parent.id)},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_set_parent_self_reference(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{item.id}/parent",
                json={"parent_id": str(item.id)},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_set_parent_not_found(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{item.id}/parent",
                json={"parent_id": "00000000-0000-0000-0000-000000000000"},
            )
            assert resp.status == 404
        finally:
            await client.close()


# ===========================================================================
# Phase 1: Tags endpoint
# ===========================================================================


class TestTagsEndpoint:
    @pytest.mark.asyncio
    async def test_get_tags(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        items[0].tags = ["@work", "@urgent"]
        items[1].tags = ["@work", "@home"]
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/tags")
            assert resp.status == 200
            data = await resp.json()
            assert set(data["tags"]) == {"@work", "@urgent", "@home"}
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_tags_empty(self):
        db = Database()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/tags")
            assert resp.status == 200
            data = await resp.json()
            assert data["tags"] == []
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_tags_excludes_private(self):
        db = _make_db_with_private()
        # Add tags to private list item
        for lst in db.lists.values():
            if lst.private:
                for item in lst.active_items():
                    item.tags = ["@secret"]
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/tags")
            data = await resp.json()
            assert "@secret" not in data["tags"]
        finally:
            await client.close()


# ===========================================================================
# Phase 1: Filtered queries on GET /api/lists/{list_id}
# ===========================================================================


class TestFilteredQuery:
    @pytest.mark.asyncio
    async def test_filter_by_text(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{list_id}?q=milk")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["items"]) == 1
            assert "milk" in data["items"][0]["reminder"].lower()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_filter_by_tags(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        items[0].tags = ["@grocery"]
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{list_id}?tags=@grocery")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["items"]) == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_filter_by_priority(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        items[0].priority = 1
        items[1].priority = 3
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{list_id}?priority=1")
            assert resp.status == 200
            data = await resp.json()
            assert all(i["priority"] == 1 for i in data["items"])
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_filter_by_status_active(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{list_id}?status=active")
            assert resp.status == 200
            data = await resp.json()
            assert all(not i["complete"] for i in data["items"])
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_filter_by_status_completed(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{list_id}?status=completed")
            assert resp.status == 200
            data = await resp.json()
            assert all(i["complete"] for i in data["items"])
            assert len(data["items"]) == 1  # "Buy eggs" is complete
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_filter_by_due_overdue(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        items[0].due_date = date.today() - timedelta(days=2)
        items[1].due_date = date.today() + timedelta(days=5)
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{list_id}?due=overdue")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["id"] == str(items[0].id)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_filter_by_due_none(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        # Give one item a due date
        items = list(lst.active_items())
        items[0].due_date = date.today()
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{list_id}?due=none")
            assert resp.status == 200
            data = await resp.json()
            assert all(i["due_date"] is None for i in data["items"])
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_filter_combined(self):
        """Multiple filters combine (AND logic)."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        items[0].priority = 1
        items[0].tags = ["@work"]
        items[1].priority = 1
        items[1].tags = ["@home"]
        list_id = str(lst.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{list_id}?priority=1&tags=@work")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["items"]) == 1
            assert data["items"][0]["id"] == str(items[0].id)
        finally:
            await client.close()


# ===========================================================================
# Phase 1: Overdue count in GET /api/lists
# ===========================================================================


class TestOverdueCount:
    @pytest.mark.asyncio
    async def test_overdue_count(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        items = list(lst.active_items())
        items[0].due_date = date.today() - timedelta(days=3)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/lists")
            data = await resp.json()
            target = next(x for x in data["lists"] if x["id"] == str(lst.id))
            assert target["overdue_count"] == 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_overdue_count_excludes_completed(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        # Buy eggs is complete — make it overdue and verify it's not counted
        for item in lst.active_items():
            if item.complete:
                item.due_date = date.today() - timedelta(days=5)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/lists")
            data = await resp.json()
            target = next(x for x in data["lists"] if x["id"] == str(lst.id))
            assert target["overdue_count"] == 0
        finally:
            await client.close()


# ===========================================================================
# Trash & restore tests
# ===========================================================================


class TestTrash:
    @pytest.mark.asyncio
    async def test_trash_empty_initially(self):
        client = await _make_client()
        await client.start_server()
        try:
            resp = await client.get("/api/trash")
            assert resp.status == 200
            data = await resp.json()
            assert data["items"] == []
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_deleted_item_appears_in_trash(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item_id = str(item.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.delete(f"/api/items/{item_id}")
            assert resp.status == 200
            resp = await client.get("/api/trash")
            data = await resp.json()
            ids = [i["id"] for i in data["items"]]
            assert item_id in ids
            # Verify list info is included
            trash_item = next(i for i in data["items"] if i["id"] == item_id)
            assert "list_name" in trash_item
            assert "deleted_ago_ms" in trash_item
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_trash_excludes_private_lists(self):
        db = _make_db_with_private()
        private_lst = next(lst for lst in db.lists.values() if lst.private)
        private_item = next(iter(private_lst.items.values()))
        private_item.mark_deleted()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/trash")
            data = await resp.json()
            ids = [i["id"] for i in data["items"]]
            assert str(private_item.id) not in ids
        finally:
            await client.close()


class TestRestore:
    @pytest.mark.asyncio
    async def test_restore_deleted_item(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item_id = str(item.id)
        client = await _make_client(db)
        await client.start_server()
        try:
            # Delete
            resp = await client.delete(f"/api/items/{item_id}")
            assert resp.status == 200
            # Verify gone from list
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            ids = [i["id"] for i in data["items"]]
            assert item_id not in ids
            # Restore
            resp = await client.patch(f"/api/items/{item_id}/restore")
            assert resp.status == 200
            restored = await resp.json()
            assert restored["id"] == item_id
            assert restored["reminder"] == item.reminder
            # Verify back in list
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            ids = [i["id"] for i in data["items"]]
            assert item_id in ids
            # Verify gone from trash
            resp = await client.get("/api/trash")
            data = await resp.json()
            ids = [i["id"] for i in data["items"]]
            assert item_id not in ids
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_restore_nonexistent_item(self):
        client = await _make_client()
        await client.start_server()
        try:
            resp = await client.patch("/api/items/00000000-0000-0000-0000-000000000099/restore")
            assert resp.status == 404
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_restore_non_deleted_item_404(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            # Item exists but is not deleted — restore should 404
            resp = await client.patch(f"/api/items/{item.id}/restore")
            assert resp.status == 404
        finally:
            await client.close()


class TestRestoreWithTheDesktopRunning:
    """With a main window, a restore names its item and leaves the rest of
    the undo stack alone. The subtasks its delete moved to the top
    level come back under it, whether the delete is the latest command,
    and is undone, or has other commands in front of it."""

    @staticmethod
    def _window(db: Database):
        from PyQt6.QtGui import QUndoStack

        class Window:
            _database = db
            _undo_stack = QUndoStack()

            def _save_database(self) -> None:
                pass

            def _refresh_ui(self) -> None:
                pass

        return Window()

    @staticmethod
    def _parent_with_subtask(db: Database):
        lst = next(iter(db.lists.values()))
        parent = next(iter(lst.active_items()))
        child = create_todo_item("Semi-skimmed")
        child.parent_id = parent.id
        lst.add_item(child)
        return lst, parent, child

    @pytest.mark.asyncio
    async def test_restore_undoes_the_delete_when_it_is_the_latest_command(self, qapp):
        from pytodo_qt.web.api import main_window_key

        db = _make_db_with_data()
        lst, parent, child = self._parent_with_subtask(db)
        window = self._window(db)
        stack = window._undo_stack
        client = await _make_client(db)
        client.server.app[main_window_key] = window
        await client.start_server()
        try:
            resp = await client.delete(f"/api/items/{parent.id}")
            assert resp.status == 200
            # The delete moved the subtask to the top level.
            assert parent.deleted is True
            assert child.parent_id is None

            resp = await client.patch(f"/api/items/{parent.id}/restore")
            assert resp.status == 200
            assert (await resp.json())["id"] == str(parent.id)
        finally:
            await client.close()
        assert parent.deleted is False
        assert child.parent_id == parent.id
        # The delete was undone, and no command was added.
        assert stack.count() == 1
        assert stack.canUndo() is False
        assert stack.canRedo() is True

    @pytest.mark.asyncio
    async def test_restore_leaves_a_later_command_in_place(self, qapp):
        """A command made after the delete, here or in the desktop
        window, is not the one taken back."""
        from pytodo_qt.gui.commands import RestoreItemCommand
        from pytodo_qt.web.api import main_window_key

        db = _make_db_with_data()
        lst, parent, child = self._parent_with_subtask(db)
        other = next(item for item in lst.active_items() if item.id not in (parent.id, child.id))
        was_complete = other.complete
        window = self._window(db)
        stack = window._undo_stack
        client = await _make_client(db)
        client.server.app[main_window_key] = window
        await client.start_server()
        try:
            resp = await client.delete(f"/api/items/{parent.id}")
            assert resp.status == 200
            resp = await client.patch(f"/api/items/{other.id}/toggle")
            assert resp.status == 200

            resp = await client.patch(f"/api/items/{parent.id}/restore")
            assert resp.status == 200
        finally:
            await client.close()
        assert parent.deleted is False
        # The later change stands.
        assert other.complete is not was_complete
        # The item came back with its subtask, as a command of its own.
        assert child.parent_id == parent.id
        assert stack.count() == 3
        assert isinstance(stack.command(2), RestoreItemCommand)
        assert stack.canRedo() is False

        # Undoing that command leaves things as the delete left them.
        stack.undo()
        assert parent.deleted is True
        assert child.parent_id is None
        assert other.complete is not was_complete

    @pytest.mark.asyncio
    async def test_restore_leaves_a_subtask_that_has_been_given_another_place(self, qapp):
        """A subtask made a subtask of another item, or deleted, since
        the delete is not taken back from where it was put."""
        from pytodo_qt.web.api import main_window_key

        db = _make_db_with_data()
        lst, parent, child = self._parent_with_subtask(db)
        moved = create_todo_item("Skimmed")
        moved.parent_id = parent.id
        lst.add_item(moved)
        gone = create_todo_item("Whole")
        gone.parent_id = parent.id
        lst.add_item(gone)
        other = next(
            item
            for item in lst.active_items()
            if item.id not in (parent.id, child.id, moved.id, gone.id)
        )
        window = self._window(db)
        client = await _make_client(db)
        client.server.app[main_window_key] = window
        await client.start_server()
        try:
            resp = await client.delete(f"/api/items/{parent.id}")
            assert resp.status == 200
            resp = await client.patch(
                f"/api/items/{moved.id}/parent", json={"parent_id": str(other.id)}
            )
            assert resp.status == 200
            resp = await client.delete(f"/api/items/{gone.id}")
            assert resp.status == 200

            resp = await client.patch(f"/api/items/{parent.id}/restore")
            assert resp.status == 200
        finally:
            await client.close()
        assert parent.deleted is False
        assert child.parent_id == parent.id
        assert moved.parent_id == other.id
        assert gone.deleted is True
        assert gone.parent_id is None

    @pytest.mark.asyncio
    async def test_restore_takes_the_subtasks_from_a_delete_of_several_items(self, qapp):
        """The desktop window deletes a selection as one command."""
        from pytodo_qt.gui.commands import DeleteItemsCommand
        from pytodo_qt.web.api import main_window_key

        db = _make_db_with_data()
        lst, parent, child = self._parent_with_subtask(db)
        other = next(item for item in lst.active_items() if item.id not in (parent.id, child.id))
        window = self._window(db)
        window._undo_stack.push(DeleteItemsCommand(window, lst.id, [parent.id, other.id]))
        assert child.parent_id is None
        client = await _make_client(db)
        client.server.app[main_window_key] = window
        await client.start_server()
        try:
            resp = await client.patch(f"/api/items/{parent.id}/restore")
            assert resp.status == 200
        finally:
            await client.close()
        assert parent.deleted is False
        assert other.deleted is True
        assert child.parent_id == parent.id

    @pytest.mark.asyncio
    async def test_restore_does_not_undo_a_delete_of_another_item(self, qapp):
        from pytodo_qt.web.api import main_window_key

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        first, second = list(lst.active_items())[:2]
        window = self._window(db)
        stack = window._undo_stack
        client = await _make_client(db)
        client.server.app[main_window_key] = window
        await client.start_server()
        try:
            for item in (first, second):
                resp = await client.delete(f"/api/items/{item.id}")
                assert resp.status == 200
            resp = await client.patch(f"/api/items/{first.id}/restore")
            assert resp.status == 200
        finally:
            await client.close()
        assert first.deleted is False
        assert second.deleted is True
        assert stack.count() == 3


# ===========================================================================
# Sort configuration API
# ===========================================================================


def _make_config_manager(tmp_path):
    """Create a ConfigManager with a temporary directory."""
    cm = ConfigManager(config_dir=tmp_path, data_dir=tmp_path)
    cm.ensure_directories()
    cm._config = AppConfig()
    return cm


class TestGetSort:
    @pytest.mark.asyncio
    async def test_get_sort_defaults(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            resp = await client.get("/api/sort")
            assert resp.status == 200
            data = await resp.json()
            tiers = data["sort_tiers"]
            assert len(tiers) == 3
            assert tiers[0] == {"dimension": "completion", "reverse": False}
            assert tiers[1] == {"dimension": "due_date", "reverse": False}
            assert tiers[2] == {"dimension": "priority", "reverse": False}
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_sort_no_config_manager(self):
        """GET /api/sort returns 503 when no config manager is available."""
        client = await _make_client()
        await client.start_server()
        try:
            resp = await client.get("/api/sort")
            assert resp.status == 503
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_status_includes_sort_tiers(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            resp = await client.get("/api/status")
            assert resp.status == 200
            data = await resp.json()
            assert "sort_tiers" in data
            assert len(data["sort_tiers"]) == 3
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_status_no_sort_tiers_without_config_manager(self):
        """GET /api/status omits sort_tiers when no config manager."""
        client = await _make_client()
        await client.start_server()
        try:
            resp = await client.get("/api/status")
            data = await resp.json()
            assert "sort_tiers" not in data
        finally:
            await client.close()


class TestUpdateSort:
    @pytest.mark.asyncio
    async def test_update_sort_tiers(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            resp = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "priority", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                        {"dimension": "due_date", "reverse": True},
                    ]
                },
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["sort_tiers"][0] == {"dimension": "priority", "reverse": True}
            assert data["sort_tiers"][1] == {"dimension": "completion", "reverse": False}
            assert data["sort_tiers"][2] == {"dimension": "due_date", "reverse": True}

            # Verify config was persisted
            assert cm.config.database.sort_tier1 == "priority"
            assert cm.config.database.sort_tier1_reverse is True
            assert cm.config.database.sort_tier2 == "completion"
            assert cm.config.database.sort_tier3 == "due_date"
            assert cm.config.database.sort_tier3_reverse is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_sort_persists_to_file(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "due_date", "reverse": False},
                        {"dimension": "priority", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                    ]
                },
            )
            # Reload from disk
            cm2 = ConfigManager(config_dir=tmp_path, data_dir=tmp_path)
            loaded = cm2.load()
            assert loaded.database.sort_tier1 == "due_date"
            assert loaded.database.sort_tier2 == "priority"
            assert loaded.database.sort_tier2_reverse is True
            assert loaded.database.sort_tier3 == "completion"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_sort_wrong_count(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            resp = await client.put(
                "/api/sort",
                json={"tiers": [{"dimension": "priority", "reverse": False}]},
            )
            assert resp.status == 400
            data = await resp.json()
            assert "3 sort tiers" in data["error"]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_sort_invalid_dimension(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            resp = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "completion", "reverse": False},
                        {"dimension": "bogus", "reverse": False},
                        {"dimension": "priority", "reverse": False},
                    ]
                },
            )
            assert resp.status == 400
            data = await resp.json()
            assert "bogus" in data["error"]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_sort_duplicate_dimensions(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            resp = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "completion", "reverse": False},
                        {"dimension": "completion", "reverse": True},
                        {"dimension": "priority", "reverse": False},
                    ]
                },
            )
            assert resp.status == 400
            data = await resp.json()
            assert "unique" in data["error"]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_sort_invalid_json(self, tmp_path):
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            resp = await client.put("/api/sort", data=b"not json")
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_sort_no_config_manager(self):
        client = await _make_client()
        await client.start_server()
        try:
            resp = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "completion", "reverse": False},
                        {"dimension": "due_date", "reverse": False},
                        {"dimension": "priority", "reverse": False},
                    ]
                },
            )
            assert resp.status == 503
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_sort_reflects_update(self, tmp_path):
        """GET /api/sort returns updated values after PUT."""
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "due_date", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                        {"dimension": "priority", "reverse": True},
                    ]
                },
            )
            resp = await client.get("/api/sort")
            data = await resp.json()
            assert data["sort_tiers"][0]["dimension"] == "due_date"
            assert data["sort_tiers"][0]["reverse"] is True
            assert data["sort_tiers"][1]["dimension"] == "completion"
            assert data["sort_tiers"][2]["dimension"] == "priority"
            assert data["sort_tiers"][2]["reverse"] is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_sort_returns_updated_at(self, tmp_path):
        """PUT /api/sort returns updated_at timestamp."""
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            resp = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "priority", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                        {"dimension": "due_date", "reverse": False},
                    ]
                },
            )
            assert resp.status == 200
            data = await resp.json()
            assert "updated_at" in data
            assert data["updated_at"] > 0
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_sort_conflict_stale(self, tmp_path):
        """PUT /api/sort returns 409 when client updated_at is stale."""
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            # First update to set a timestamp
            resp = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "priority", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                        {"dimension": "due_date", "reverse": False},
                    ]
                },
            )
            data = await resp.json()
            server_ts = data["updated_at"]

            # Second update with stale timestamp
            resp2 = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "due_date", "reverse": False},
                        {"dimension": "priority", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                    ],
                    "updated_at": server_ts - 1,
                },
            )
            assert resp2.status == 409
            conflict = await resp2.json()
            assert "current" in conflict
            assert conflict["current"]["sort_tiers"][0]["dimension"] == "priority"
            assert conflict["current"]["updated_at"] == server_ts
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_sort_conflict_force(self, tmp_path):
        """PUT /api/sort with force=true bypasses conflict guard."""
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            # First update
            resp = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "priority", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                        {"dimension": "due_date", "reverse": False},
                    ]
                },
            )
            data = await resp.json()
            server_ts = data["updated_at"]

            # Force update with stale timestamp
            resp2 = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "due_date", "reverse": False},
                        {"dimension": "priority", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                    ],
                    "updated_at": server_ts - 1,
                    "force": True,
                },
            )
            assert resp2.status == 200
            data2 = await resp2.json()
            assert data2["sort_tiers"][0]["dimension"] == "due_date"
            assert data2["updated_at"] > server_ts
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_sort_no_updated_at_succeeds(self, tmp_path):
        """PUT /api/sort without updated_at always succeeds (backwards compat)."""
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            # First update to set a timestamp
            await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "priority", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                        {"dimension": "due_date", "reverse": False},
                    ]
                },
            )

            # Update without updated_at — should succeed
            resp = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "due_date", "reverse": False},
                        {"dimension": "priority", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                    ]
                },
            )
            assert resp.status == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_sort_includes_updated_at(self, tmp_path):
        """GET /api/sort includes updated_at in response."""
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            resp = await client.get("/api/sort")
            data = await resp.json()
            assert "updated_at" in data
            assert data["updated_at"] == 0.0  # default
        finally:
            await client.close()


# ===========================================================================
# Board layout presets
# ===========================================================================


class TestPresets:
    @pytest.mark.asyncio
    async def test_get_presets(self):
        client = await _make_client()
        await client.start_server()
        try:
            resp = await client.get("/api/presets")
            assert resp.status == 200
            data = await resp.json()
            presets = data["presets"]
            assert len(presets) == 4
            names = [p["name"] for p in presets]
            assert "Simple" in names
            assert "With Review" in names
            assert "With Testing" in names
            assert "Backlog" in names
            # Each preset has columns
            for p in presets:
                assert len(p["columns"]) >= 3
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_apply_preset(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.board_column = "In Progress"
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/apply-preset",
                json={"columns": ["To Do", "In Progress", "Review", "Done"]},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["board_columns"] == ["To Do", "In Progress", "Review", "Done"]
            # Item stays in "In Progress" (exact name match)
            assert item.board_column == "In Progress"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_apply_preset_remaps_items(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.board_column = "In Progress"
        client = await _make_client(db)
        await client.start_server()
        try:
            # Apply a preset that doesn't have "In Progress"
            resp = await client.post(
                f"/api/lists/{lst.id}/apply-preset",
                json={"columns": ["Backlog", "To Do", "In Progress", "Done"]},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["board_columns"] == ["Backlog", "To Do", "In Progress", "Done"]
            assert data["remapped"] >= 0
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_apply_preset_completion_remap(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.board_column = "Done"  # In completion column
        client = await _make_client(db)
        await client.start_server()
        try:
            # Apply preset with different last column name
            resp = await client.post(
                f"/api/lists/{lst.id}/apply-preset",
                json={"columns": ["Inbox", "Working", "Finished"]},
            )
            assert resp.status == 200
            # Item was in "Done" (old last col) → "Finished" (new last col)
            assert item.board_column == "Finished"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_apply_preset_invalid_columns(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/apply-preset",
                json={"columns": ["Only"]},
            )
            assert resp.status == 400
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_apply_preset_duplicate_columns(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/apply-preset",
                json={"columns": ["To Do", "To Do", "Done"]},
            )
            assert resp.status == 400
        finally:
            await client.close()


# ===========================================================================
# Conflict guard tests
# ===========================================================================


def _make_db_with_stale_item():
    """Create a DB and simulate a server-side update so client timestamp is stale."""
    db = Database()
    lst = create_todo_list("Tasks")
    item = create_todo_item("Original reminder")
    lst.add_item(item)
    db.add_list(lst)
    stale_ts = item.updated_at
    # Simulate server-side modification with guaranteed timestamp advance
    item.reminder = "Server-updated reminder"
    item.updated_at = stale_ts + 1000
    return db, lst, item, stale_ts


class TestConflictGuardsItems:
    """Test conflict detection on item write endpoints."""

    @pytest.mark.asyncio
    async def test_update_item_conflict(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"reminder": "Client change", "updated_at": stale_ts},
            )
            assert resp.status == 409
            data = await resp.json()
            assert data["current"]["reminder"] == "Server-updated reminder"
            assert data["current"]["updated_at"] == item.updated_at
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_item_no_conflict_without_updated_at(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"reminder": "Client change"},
            )
            assert resp.status == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_item_no_conflict_with_current_timestamp(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        current_ts = item.updated_at
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"reminder": "Client change", "updated_at": current_ts},
            )
            assert resp.status == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_item_force_overrides_conflict(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"reminder": "Forced change", "updated_at": stale_ts, "force": True},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["reminder"] == "Forced change"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_delete_item_conflict(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.delete(
                f"/api/items/{item.id}",
                json={"updated_at": stale_ts},
            )
            assert resp.status == 409
            data = await resp.json()
            assert data["current"]["id"] == str(item.id)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_delete_item_no_body_skips_check(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.delete(f"/api/items/{item.id}")
            assert resp.status == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_toggle_item_conflict(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{item.id}/toggle",
                json={"updated_at": stale_ts},
            )
            assert resp.status == 409
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_toggle_item_no_body_skips_check(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(f"/api/items/{item.id}/toggle")
            assert resp.status == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_move_item_conflict(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{item.id}/move",
                json={"column": "In Progress", "updated_at": stale_ts},
            )
            assert resp.status == 409
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_set_parent_conflict(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        child = create_todo_item("Subtask")
        lst.add_item(child)
        client = await _make_client(db)
        await client.start_server()
        try:
            # Use the child's own updated_at — child was not modified, so this should pass
            resp = await client.patch(
                f"/api/items/{child.id}/parent",
                json={"parent_id": str(item.id), "updated_at": child.updated_at},
            )
            assert resp.status == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_set_parent_conflict_on_child(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        # item was modified server-side (stale_ts < item.updated_at)
        # Use item as the target of set_parent with its stale timestamp
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{item.id}/parent",
                json={"parent_id": None, "updated_at": stale_ts},
            )
            assert resp.status == 409
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_restore_item_conflict(self):
        db = Database()
        lst = create_todo_list("Tasks")
        item = create_todo_item("Deleted item")
        lst.add_item(item)
        db.add_list(lst)
        stale_ts = item.updated_at
        item.deleted = True
        item.updated_at = stale_ts + 1000  # Simulate later deletion
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/items/{item.id}/restore",
                json={"updated_at": stale_ts},
            )
            assert resp.status == 409
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_restore_item_no_body_skips_check(self):
        db = Database()
        lst = create_todo_list("Tasks")
        item = create_todo_item("Deleted item")
        lst.add_item(item)
        db.add_list(lst)
        item.mark_deleted()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(f"/api/items/{item.id}/restore")
            assert resp.status == 200
        finally:
            await client.close()


class TestConflictGuardsLists:
    """Test conflict detection on list write endpoints."""

    @pytest.mark.asyncio
    async def test_rename_list_conflict(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        stale_ts = lst.updated_at
        lst.name = "Server-renamed"
        lst.updated_at = stale_ts + 1000
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/lists/{lst.id}",
                json={"name": "Client rename", "updated_at": stale_ts},
            )
            assert resp.status == 409
            data = await resp.json()
            assert data["current"]["name"] == "Server-renamed"
            assert data["current"]["updated_at"] == lst.updated_at
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_rename_list_no_conflict_without_updated_at(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        lst.updated_at = lst.updated_at + 1000
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/lists/{lst.id}",
                json={"name": "New name"},
            )
            assert resp.status == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_rename_list_force_overrides(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        stale_ts = lst.updated_at
        lst.updated_at = stale_ts + 1000
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/lists/{lst.id}",
                json={"name": "Forced", "updated_at": stale_ts, "force": True},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["name"] == "Forced"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_delete_list_conflict(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        stale_ts = lst.updated_at
        lst.updated_at = stale_ts + 1000
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.delete(
                f"/api/lists/{lst.id}",
                json={"updated_at": stale_ts},
            )
            assert resp.status == 409
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_columns_conflict(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        stale_ts = lst.updated_at
        lst.updated_at = stale_ts + 1000
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "add", "name": "Review", "updated_at": stale_ts},
            )
            assert resp.status == 409
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_apply_preset_conflict(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        stale_ts = lst.updated_at
        lst.updated_at = stale_ts + 1000
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/apply-preset",
                json={
                    "columns": ["To Do", "In Progress", "Done"],
                    "updated_at": stale_ts,
                },
            )
            assert resp.status == 409
        finally:
            await client.close()


class TestConflictGuardsResponses:
    """Test 409 response payloads and updated_at in list responses."""

    @pytest.mark.asyncio
    async def test_conflict_response_includes_current_item(self):
        db, lst, item, stale_ts = _make_db_with_stale_item()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"reminder": "Stale", "updated_at": stale_ts},
            )
            assert resp.status == 409
            data = await resp.json()
            current = data["current"]
            assert current["id"] == str(item.id)
            assert current["reminder"] == item.reminder
            assert current["updated_at"] == item.updated_at
            assert current["priority"] == item.priority
            assert "complete" in current
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_conflict_response_includes_current_list(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        stale_ts = lst.updated_at
        lst.name = "Server name"
        lst.updated_at = stale_ts + 1000
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/lists/{lst.id}",
                json={"name": "Client name", "updated_at": stale_ts},
            )
            assert resp.status == 409
            data = await resp.json()
            current = data["current"]
            assert current["id"] == str(lst.id)
            assert current["name"] == "Server name"
            assert current["updated_at"] == lst.updated_at
            assert "board_columns" in current
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_lists_includes_updated_at(self):
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get("/api/lists")
            data = await resp.json()
            for lst in data["lists"]:
                assert "updated_at" in lst
                assert isinstance(lst["updated_at"], int)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_list_includes_updated_at(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}")
            data = await resp.json()
            assert "updated_at" in data
            assert data["updated_at"] == lst.updated_at
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_board_includes_updated_at(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.get(f"/api/lists/{lst.id}/board")
            data = await resp.json()
            assert "updated_at" in data
            assert data["updated_at"] == lst.updated_at
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_rename_list_response_includes_updated_at(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/lists/{lst.id}",
                json={"name": "Renamed"},
            )
            data = await resp.json()
            assert "updated_at" in data
            assert isinstance(data["updated_at"], int)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_update_columns_response_includes_updated_at(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "add", "name": "Review"},
            )
            data = await resp.json()
            assert "updated_at" in data
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_apply_preset_response_includes_updated_at(self):
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.post(
                f"/api/lists/{lst.id}/apply-preset",
                json={"columns": ["To Do", "In Progress", "Done"]},
            )
            data = await resp.json()
            assert "updated_at" in data
        finally:
            await client.close()


class TestConflictGuardsEdgeCases:
    """Test edge cases for conflict detection."""

    @pytest.mark.asyncio
    async def test_same_timestamp_proceeds(self):
        """Client sends the exact current timestamp — write should succeed."""
        db, lst, item, _stale_ts = _make_db_with_stale_item()
        current_ts = item.updated_at
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"reminder": "Same-ts update", "updated_at": current_ts},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["reminder"] == "Same-ts update"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_zero_timestamp_conflicts(self):
        """Client sends 0 as updated_at — should conflict with any real timestamp."""
        db, lst, item, _stale_ts = _make_db_with_stale_item()
        client = await _make_client(db)
        await client.start_server()
        try:
            resp = await client.put(
                f"/api/items/{item.id}",
                json={"reminder": "Zero-ts", "updated_at": 0},
            )
            assert resp.status == 409
        finally:
            await client.close()


# ===========================================================================
# WebSocket tests
# ===========================================================================


async def _receive_event(ws_conn, timeout: float = 2.0):
    """The next message of a socket that is not its greeting."""
    while True:
        msg = await ws_conn.receive_json(timeout=timeout)
        if msg.get("event") != "hello":
            return msg


class TestWebSocket:
    @pytest.mark.asyncio
    async def test_first_message_names_the_version_of_the_page(self):
        """A page that connects hears which version of the page's files
        the server serves, and can tell when it is running another."""
        from pytodo_qt.web.server import static_asset_version

        client = await _make_client(_make_db_with_data())
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                msg = await ws_conn.receive_json(timeout=2.0)
                await ws_conn.close()
        finally:
            await client.close()
        assert msg == {"event": "hello", "page_version": static_asset_version()}

    @pytest.mark.asyncio
    async def test_ws_connect(self):
        """WebSocket endpoint accepts connections."""
        db = _make_db_with_data()
        client = await _make_client(db)
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                assert not ws_conn.closed
                await ws_conn.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_answers_a_ping(self):
        """A page asks over the WebSocket whether the server is there."""
        client = await _make_client(_make_db_with_data())
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                await ws_conn.send_str("ping")
                assert await _receive_event(ws_conn) == {"event": "pong"}
                # And again: each ping has its answer.
                await ws_conn.send_str("ping")
                assert await _receive_event(ws_conn) == {"event": "pong"}
                await ws_conn.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_answers_nothing_else(self):
        """Other text from a page is read and left unanswered."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                await ws_conn.send_str("hello")
                await ws_conn.send_str("PING")
                await ws_conn.send_str("ping")
                assert await _receive_event(ws_conn) == {"event": "pong"}
                # One answer, for the one ping: what comes next is the
                # news of a change, not an answer to the other two.
                await client.post(f"/api/lists/{lst.id}/items", json={"reminder": "New task"})
                assert (await _receive_event(ws_conn))["event"] == "refresh"
                await ws_conn.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_broadcast_on_item_create(self):
        """Creating an item broadcasts a refresh event to WS clients."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                # Trigger a write
                await client.post(
                    f"/api/lists/{lst.id}/items",
                    json={"reminder": "New task"},
                )
                # Should receive refresh event
                msg = await _receive_event(ws_conn)
                assert msg["event"] == "refresh"
                await ws_conn.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_broadcast_on_item_update(self):
        """Updating an item broadcasts a refresh event to WS clients."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                await client.put(
                    f"/api/items/{item.id}",
                    json={"reminder": "Updated"},
                )
                msg = await _receive_event(ws_conn)
                assert msg["event"] == "refresh"
                await ws_conn.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_broadcast_on_toggle(self):
        """Toggling an item broadcasts a refresh event to WS clients."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                await client.patch(f"/api/items/{item.id}/toggle")
                msg = await _receive_event(ws_conn)
                assert msg["event"] == "refresh"
                await ws_conn.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_multiple_clients(self):
        """Multiple WS clients all receive the broadcast."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws1, client.ws_connect("/ws") as ws2:
                await client.post(
                    f"/api/lists/{lst.id}/items",
                    json={"reminder": "Broadcast test"},
                )
                msg1 = await _receive_event(ws1)
                msg2 = await _receive_event(ws2)
                assert msg1["event"] == "refresh"
                assert msg2["event"] == "refresh"
                await ws1.close()
                await ws2.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_disconnect_cleanup(self):
        """Disconnected WS clients are cleaned up and don't block broadcasts."""

        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            # Connect and disconnect first client
            ws1 = await client.ws_connect("/ws")
            await ws1.close()
            # Give the server a moment to process the disconnect
            import asyncio

            await asyncio.sleep(0.05)
            # Second client should still work
            async with client.ws_connect("/ws") as ws2:
                await client.post(
                    f"/api/lists/{lst.id}/items",
                    json={"reminder": "After disconnect"},
                )
                msg = await _receive_event(ws2)
                assert msg["event"] == "refresh"
                await ws2.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_notify_clients_from_server(self):
        """WebServer.notify_clients() broadcasts to connected WS clients."""
        db = _make_db_with_data()
        ws = WebServer(database=db)
        app = ws.create_app()
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                ws.notify_clients()
                msg = await _receive_event(ws_conn)
                assert msg["event"] == "refresh"
                await ws_conn.close()
        finally:
            await client.close()


# ===========================================================================
# Integration: multi-client interop
# ===========================================================================


class TestMultiClientInterop:
    """End-to-end integration tests for concurrent client scenarios."""

    @staticmethod
    async def _get_item_from_list(client, list_id, item_id):
        """Fetch a single item's data via the list endpoint."""
        resp = await client.get(f"/api/lists/{list_id}")
        data = await resp.json()
        for i in data["items"]:
            if i["id"] == str(item_id):
                return i
        return None

    @pytest.mark.asyncio
    async def test_concurrent_item_update_conflict(self):
        """Two clients updating the same item — second gets 409."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            # Both clients read the item at the same time
            data_a = await self._get_item_from_list(client, lst.id, item.id)
            ts = data_a["updated_at"]

            # Client A updates successfully
            resp_a = await client.put(
                f"/api/items/{item.id}",
                json={"reminder": "Client A edit", "updated_at": ts},
            )
            assert resp_a.status == 200

            # Client B tries to update with same (now stale) timestamp → 409
            resp_b = await client.put(
                f"/api/items/{item.id}",
                json={"reminder": "Client B edit", "updated_at": ts},
            )
            assert resp_b.status == 409
            conflict = await resp_b.json()
            assert conflict["current"]["reminder"] == "Client A edit"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_observer_sees_http_update(self):
        """A WS client sees changes made by an HTTP-only client."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                # HTTP client updates item
                await client.put(
                    f"/api/items/{item.id}",
                    json={"reminder": "Updated by HTTP"},
                )
                # WS observer gets notified
                msg = await _receive_event(ws_conn)
                assert msg["event"] == "refresh"

                # Observer fetches fresh state and sees the update
                data = await self._get_item_from_list(client, lst.id, item.id)
                assert data["reminder"] == "Updated by HTTP"
                await ws_conn.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_recurring_item_toggle_broadcasts(self):
        """Toggling a recurring item broadcasts to WS clients."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.recurrence_type = "daily"
        item.recurrence_interval = 1
        item.due_date = date.today()
        client = await _make_client(db)
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                await client.patch(f"/api/items/{item.id}/toggle")
                msg = await _receive_event(ws_conn)
                assert msg["event"] == "refresh"

                # Item should be toggled
                data = await self._get_item_from_list(client, lst.id, item.id)
                assert data["complete"] is True
                await ws_conn.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_column_rename_remaps_items(self):
        """Renaming a board column updates items' board_column field."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        item.board_column = "In Progress"
        client = await _make_client(db)
        await client.start_server()
        try:
            # Rename column via API
            resp = await client.patch(
                f"/api/lists/{lst.id}/columns",
                json={"action": "rename", "old_name": "In Progress", "new_name": "Doing"},
            )
            assert resp.status == 200

            # Verify board data shows item under new column name
            resp2 = await client.get(f"/api/lists/{lst.id}/board")
            data = await resp2.json()
            assert "Doing" in data["columns"]
            assert "In Progress" not in data["columns"]
            doing_ids = [i["id"] for i in data["columns"]["Doing"]]
            assert str(item.id) in doing_ids
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_column_rename_ws_broadcast(self):
        """Column rename broadcasts refresh to WS clients."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        client = await _make_client(db)
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws_conn:
                await client.patch(
                    f"/api/lists/{lst.id}/columns",
                    json={"action": "rename", "old_name": "In Progress", "new_name": "Review"},
                )
                msg = await _receive_event(ws_conn)
                assert msg["event"] == "refresh"
                await ws_conn.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_sort_conflict_between_clients(self, tmp_path):
        """Two clients changing sort config — second gets 409."""
        cm = _make_config_manager(tmp_path)
        client = await _make_client(config_manager=cm)
        await client.start_server()
        try:
            # Client A reads sort
            resp_a = await client.get("/api/sort")
            ts_a = (await resp_a.json())["updated_at"]

            # Client A updates
            resp_a2 = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "priority", "reverse": True},
                        {"dimension": "completion", "reverse": False},
                        {"dimension": "due_date", "reverse": False},
                    ],
                    "updated_at": ts_a,
                },
            )
            assert resp_a2.status == 200
            new_ts = (await resp_a2.json())["updated_at"]

            # Client B tries with stale timestamp
            resp_b = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "due_date", "reverse": True},
                        {"dimension": "priority", "reverse": False},
                        {"dimension": "completion", "reverse": False},
                    ],
                    "updated_at": ts_a,
                },
            )
            assert resp_b.status == 409

            # Client B fetches fresh state, retries with current timestamp
            resp_b2 = await client.get("/api/sort")
            current_ts = (await resp_b2.json())["updated_at"]
            assert current_ts == new_ts

            resp_b3 = await client.put(
                "/api/sort",
                json={
                    "tiers": [
                        {"dimension": "due_date", "reverse": True},
                        {"dimension": "priority", "reverse": False},
                        {"dimension": "completion", "reverse": False},
                    ],
                    "updated_at": current_ts,
                },
            )
            assert resp_b3.status == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_two_ws_clients_both_see_toggle(self):
        """Two WS clients both receive broadcast when item is toggled."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            async with client.ws_connect("/ws") as ws1, client.ws_connect("/ws") as ws2:
                await client.patch(f"/api/items/{item.id}/toggle")
                msg1 = await _receive_event(ws1)
                msg2 = await _receive_event(ws2)
                assert msg1["event"] == "refresh"
                assert msg2["event"] == "refresh"
                await ws1.close()
                await ws2.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_delete_conflict_stale_timestamp(self):
        """DELETE with stale updated_at returns 409."""
        db = _make_db_with_data()
        lst = next(iter(db.lists.values()))
        item = next(iter(lst.active_items()))
        client = await _make_client(db)
        await client.start_server()
        try:
            # Get current timestamp
            data = await self._get_item_from_list(client, lst.id, item.id)
            ts = data["updated_at"]

            # Update the item to advance its timestamp
            await client.put(
                f"/api/items/{item.id}",
                json={"reminder": "Modified"},
            )

            # Try to delete with stale timestamp
            resp2 = await client.request(
                "DELETE",
                f"/api/items/{item.id}",
                json={"updated_at": ts},
            )
            assert resp2.status == 409
        finally:
            await client.close()


# ===========================================================================
# Authentication tests
# ===========================================================================


def _make_authed_client(db: Database | None = None, tmp_path: str | None = None):
    """Create a WebServer with per-device auth via ConfigManager.

    Returns (WebServer, device_token) where device_token is a valid
    per-device token created via PIN pairing.
    """
    import tempfile

    if db is None:
        db = _make_db_with_data()
    if tmp_path is None:
        tmp_path = tempfile.mkdtemp()
    from pathlib import Path

    config_dir = Path(tmp_path)
    cm = ConfigManager(config_dir=config_dir, data_dir=config_dir)
    cm.ensure_directories()
    config = cm.config
    config.web.enabled = True
    ws = WebServer(database=db, config=config.web, config_manager=cm)
    ws.create_app()
    # Pair a device to get a valid token
    pin = ws.pairing_pin
    device = ws.validate_pin(pin, user_agent="TestAgent/1.0")
    assert device is not None
    return ws, device.token


class TestAuth:
    @pytest.mark.asyncio
    async def test_api_returns_401_without_token(self):
        ws, token = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.get("/api/lists")
            assert resp.status == 401
            data = await resp.json()
            assert data["error"] == "Authentication required"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_api_returns_200_with_correct_token(self):
        ws, token = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.get(
                "/api/lists",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status == 200
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_api_returns_401_with_wrong_token(self):
        ws, token = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.get(
                "/api/lists",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status == 401
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_static_files_accessible_without_token(self):
        ws, token = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.get("/")
            assert resp.status == 200
            resp_sw = await client.get("/sw.js")
            # sw.js returns 200 if file exists, 404 if not (but not 401)
            assert resp_sw.status != 401
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_accepts_token_in_query_param(self):
        ws, token = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            async with client.ws_connect(f"/ws?token={token}") as ws_conn:
                assert not ws_conn.closed
                await ws_conn.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_ws_rejects_without_token(self):
        ws, token = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.get("/ws")
            assert resp.status == 401
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_write_endpoint_requires_auth(self):
        db = _make_db_with_data()
        ws, token = _make_authed_client(db)
        lst = next(iter(db.lists.values()))
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            # Without token
            resp = await client.post(
                f"/api/lists/{lst.id}/items",
                json={"reminder": "Test"},
            )
            assert resp.status == 401
            # With token
            resp = await client.post(
                f"/api/lists/{lst.id}/items",
                json={"reminder": "Test"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status == 201
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_no_auth_without_config(self):
        """When no config is passed (test mode), auth is disabled."""
        client = await _make_client()
        await client.start_server()
        try:
            resp = await client.get("/api/lists")
            assert resp.status == 200
        finally:
            await client.close()


class TestPairing:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("named", "kept"),
        [
            ("planner.local:8080", "planner.local:8080"),
            ("192.168.1.20:8080", "192.168.1.20:8080"),
            ("planner.local", "planner.local"),
            ("[fe80::1]:8080", "[fe80::1]:8080"),
            # Not the plain form of an address: nothing is kept.
            ("planner.local:8080/<b>x</b>", ""),
            ("a b", ""),
            ("x" * 300, ""),
        ],
    )
    async def test_the_address_the_browser_named_is_kept_with_the_device(self, named, kept):
        """It is where the device is sent back to (#113). The header is
        the device's to write, and the address is shown on the desktop."""
        ws, _ = _make_authed_client()
        pin = ws.pairing_pin
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.post("/api/auth", json={"pin": pin}, headers={"Host": named})
            assert resp.status == 200
            token = (await resp.json())["token"]
            assert ws.device_store is not None
            device = ws.device_store.get_device_by_token(token)
            assert device is not None
            assert device.address == kept
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_the_address_to_come_back_by_sends_the_browser_to_the_page(self):
        """Without a token: a browser sends none when it opens an
        address. Not stored by the browser: it is asked for again each
        time a device comes back."""
        ws, _ = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.get("/reconnect", allow_redirects=False)
            assert resp.status == 302
            assert resp.headers["Location"] == "/"
            assert resp.headers["Cache-Control"] == "no-store"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_pair_with_valid_pin(self):
        ws, _ = _make_authed_client()
        pin = ws.pairing_pin
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.post("/api/auth", json={"pin": pin})
            assert resp.status == 200
            data = await resp.json()
            assert "token" in data
            assert "device_name" in data
            assert len(data["token"]) > 20
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_pair_with_invalid_pin(self):
        ws, _ = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.post("/api/auth", json={"pin": "000000"})
            assert resp.status == 401
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_pin_is_single_use(self):
        ws, _ = _make_authed_client()
        pin = ws.pairing_pin
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            # First use succeeds
            resp = await client.post("/api/auth", json={"pin": pin})
            assert resp.status == 200
            # Same PIN is consumed — second use fails
            resp2 = await client.post("/api/auth", json={"pin": pin})
            assert resp2.status == 401
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_pin_regenerates_after_use(self):
        ws, _ = _make_authed_client()
        old_pin = ws.pairing_pin
        ws.validate_pin(old_pin, user_agent="Test/1.0")
        new_pin = ws.pairing_pin
        assert new_pin != old_pin
        assert len(new_pin) == 6

    @pytest.mark.asyncio
    async def test_pair_endpoint_accessible_without_token(self):
        """Pairing endpoint must be public (no auth header required)."""
        ws, _ = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            # No Authorization header — should not get 401
            resp = await client.post("/api/auth", json={"pin": "wrong"})
            assert resp.status == 401  # Invalid PIN, but not "auth required"
            data = await resp.json()
            assert data["error"] == "Invalid or expired PIN"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_pair_creates_device_record(self):
        ws, _ = _make_authed_client()
        pin = ws.pairing_pin
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            initial_count = len(ws.get_paired_devices())
            resp = await client.post(
                "/api/auth",
                json={"pin": pin, "method": "trusted"},
                headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17)"},
            )
            assert resp.status == 200
            devices = ws.get_paired_devices()
            assert len(devices) == initial_count + 1
        finally:
            await client.close()


class TestPinRateLimit:
    def test_rate_limit_after_5_failures(self):
        ws, _ = _make_authed_client()
        for _ in range(5):
            result = ws.validate_pin("000000", client_ip="1.2.3.4")
            assert result is None
        # 6th attempt should be rate-limited (returns None even with correct PIN)
        pin = ws.pairing_pin
        result = ws.validate_pin(pin, client_ip="1.2.3.4")
        assert result is None

    def test_different_ips_independent(self):
        ws, _ = _make_authed_client()
        for _ in range(5):
            ws.validate_pin("000000", client_ip="1.2.3.4")
        # Different IP should not be locked out
        pin = ws.pairing_pin
        result = ws.validate_pin(pin, client_ip="5.6.7.8")
        assert result is not None

    @pytest.mark.asyncio
    async def test_rate_limit_returns_429(self):
        ws, _ = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            for _ in range(5):
                await client.post("/api/auth", json={"pin": "000000"})
            resp = await client.post("/api/auth", json={"pin": "000000"})
            assert resp.status == 429
            data = await resp.json()
            assert "Too many attempts" in data["error"]
        finally:
            await client.close()


class TestDeviceRevocation:
    def test_revoke_all_removes_devices(self):
        ws, _ = _make_authed_client()
        # Already has 1 device from _make_authed_client
        assert len(ws.get_paired_devices()) >= 1
        count = ws.revoke_all_devices()
        assert count >= 1
        assert ws.get_paired_devices() == []

    def test_remove_single_device(self):
        ws, token = _make_authed_client()
        # Pair a second device
        pin = ws.pairing_pin
        device2 = ws.validate_pin(pin, user_agent="Device2/1.0")
        assert device2 is not None

        devices = ws.get_paired_devices()
        assert len(devices) >= 2

        # Remove one device
        ws.remove_device(device2.id)
        remaining = ws.get_paired_devices()
        assert len(remaining) == len(devices) - 1
        # Original token still works
        assert ws.device_store is not None
        assert ws.device_store.get_device_by_token(token) is not None

    def test_rename_device_passthrough(self):
        ws, _token = _make_authed_client()
        devices = ws.get_paired_devices()
        assert len(devices) >= 1
        device_id = devices[0].id

        # Rename via the WebServer passthrough (the entry point used
        # by the Mobile Access Wizard's rename button)
        assert ws.rename_device(device_id, "Kitchen Tablet") is True

        refreshed = ws.get_paired_devices()
        renamed = next(d for d in refreshed if d.id == device_id)
        assert renamed.device_name == "Kitchen Tablet"

    def test_rename_device_passthrough_unknown_id(self):
        ws, _token = _make_authed_client()
        # Non-existent device id returns False, nothing crashes
        assert ws.rename_device("ghost-device-id", "Anything") is False

    @pytest.mark.asyncio
    async def test_revoked_device_token_returns_401(self):
        ws, token = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            # Token works
            resp = await client.get(
                "/api/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status == 200
            # Revoke all
            ws.revoke_all_devices()
            # Token fails
            resp = await client.get(
                "/api/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status == 401
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_removed_device_has_its_websocket_closed(self):
        """A page open on a removed device learns of it at once (#74)."""
        ws, token = _make_authed_client()
        other = ws.validate_pin(ws.pairing_pin, user_agent="Device2/1.0")
        assert other is not None
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            kept = await client.ws_connect(f"/ws?token={token}")
            removed = await client.ws_connect(f"/ws?token={other.token}")
            assert (await kept.receive_json())["event"] == "hello"
            assert (await removed.receive_json())["event"] == "hello"

            assert ws.remove_device(other.id) is True
            # Told of no change from here on, though the closing takes a moment.
            await asyncio.sleep(0)
            assert len(ws.app[ws_clients_key]) == 1

            closed = await removed.receive(timeout=5)
            assert closed.type == WSMsgType.CLOSE
            assert closed.data == WSCloseCode.POLICY_VIOLATION
            # The other device's WebSocket stays, and is still told of changes.
            await kept.send_str("ping")
            assert (await kept.receive_json(timeout=5))["event"] == "pong"
            assert len(ws.app[ws_clients_key]) == 1
            # What the page then asks is refused.
            resp = await client.get(
                "/api/status", headers={"Authorization": f"Bearer {other.token}"}
            )
            assert resp.status == 401
            await kept.close()
            await removed.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_removing_a_device_at_the_endpoint_closes_its_websocket(self):
        ws, token = _make_authed_client()
        other = ws.validate_pin(ws.pairing_pin, user_agent="Device2/1.0")
        assert other is not None
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            removed = await client.ws_connect(f"/ws?token={other.token}")
            assert (await removed.receive_json())["event"] == "hello"
            resp = await client.delete(
                f"/api/devices/{other.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status == 200
            closed = await removed.receive(timeout=5)
            assert closed.type == WSMsgType.CLOSE
            await removed.close()
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_revoking_all_devices_closes_every_websocket(self):
        ws, token = _make_authed_client()
        other = ws.validate_pin(ws.pairing_pin, user_agent="Device2/1.0")
        assert other is not None
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            first = await client.ws_connect(f"/ws?token={token}")
            second = await client.ws_connect(f"/ws?token={other.token}")
            assert (await first.receive_json())["event"] == "hello"
            assert (await second.receive_json())["event"] == "hello"

            assert ws.revoke_all_devices() == 2

            for conn in (first, second):
                closed = await conn.receive(timeout=5)
                assert closed.type == WSMsgType.CLOSE
                await conn.close()
            assert len(ws.app[ws_clients_key]) == 0
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_removing_a_device_that_is_not_there_closes_nothing(self):
        ws, token = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            kept = await client.ws_connect(f"/ws?token={token}")
            assert (await kept.receive_json())["event"] == "hello"
            assert ws.remove_device("no-such-device") is False
            await kept.send_str("ping")
            assert (await kept.receive_json(timeout=5))["event"] == "pong"
            await kept.close()
        finally:
            await client.close()

    def test_removing_a_device_without_a_running_loop_does_not_fail(self):
        """The desktop removes a device from Qt code; a test, with no loop at all."""
        ws, _token = _make_authed_client()
        # A WebSocket's place in the set, with no loop to close it on.
        ws.app[ws_clients_key].add(object())
        device = ws.get_paired_devices()[0]
        assert ws.remove_device(device.id) is True
        assert ws.revoke_all_devices() == 0

    @pytest.mark.asyncio
    async def test_device_list_endpoint(self):
        ws, token = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.get(
                "/api/devices",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert "devices" in data
            assert len(data["devices"]) >= 1
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_remove_device_endpoint(self):
        ws, token = _make_authed_client()
        devices = ws.get_paired_devices()
        device_id = devices[0].id
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.delete(
                f"/api/devices/{device_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["ok"] is True
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_rename_device_endpoint(self):
        ws, token = _make_authed_client()
        devices = ws.get_paired_devices()
        device_id = devices[0].id
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/devices/{device_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"device_name": "My iPad"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["ok"] is True
            assert data["device_name"] == "My iPad"

            # Verify via GET
            resp2 = await client.get(
                "/api/devices",
                headers={"Authorization": f"Bearer {token}"},
            )
            data2 = await resp2.json()
            names = [d["device_name"] for d in data2["devices"]]
            assert "My iPad" in names
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_rename_device_not_found(self):
        ws, token = _make_authed_client()
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.patch(
                "/api/devices/nonexistent-id",
                headers={"Authorization": f"Bearer {token}"},
                json={"device_name": "Test"},
            )
            assert resp.status == 404
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_rename_device_empty_name(self):
        ws, token = _make_authed_client()
        devices = ws.get_paired_devices()
        device_id = devices[0].id
        client = TestClient(TestServer(ws.app))
        await client.start_server()
        try:
            resp = await client.patch(
                f"/api/devices/{device_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"device_name": "  "},
            )
            assert resp.status == 400
        finally:
            await client.close()


class TestSecurityHeaders:
    @pytest.mark.asyncio
    async def test_api_has_security_headers(self):
        client = await _make_client()
        await client.start_server()
        try:
            resp = await client.get("/api/lists")
            assert resp.headers["X-Content-Type-Options"] == "nosniff"
            assert resp.headers["X-Frame-Options"] == "DENY"
            assert resp.headers["Referrer-Policy"] == "no-referrer"
            assert "default-src" in resp.headers["Content-Security-Policy"]
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_static_has_security_headers(self):
        client = await _make_client()
        await client.start_server()
        try:
            resp = await client.get("/")
            assert resp.headers["X-Content-Type-Options"] == "nosniff"
            assert resp.headers["Referrer-Policy"] == "no-referrer"
        finally:
            await client.close()


# ===========================================================================
# Analytics endpoint tests
# ===========================================================================


class _FakeAnalytics:
    """Stub AnalyticsService that records calls and returns canned NamedTuples.

    Lets the web tests verify request → response wiring without dragging
    SQLite into the in-memory web fixtures. Computation correctness is
    covered separately in tests/test_analytics.py.
    """

    def __init__(self) -> None:
        from pytodo_qt.core.analytics import (
            CompletionTimingResult,
            CycleTimeResult,
            ItemCompletionTiming,
            SlipRateResult,
        )

        self.last_completion_timing_kwargs: dict | None = None
        self.last_slip_rate_kwargs: dict | None = None
        self.last_cycle_time_kwargs: dict | None = None

        self._completion_timing_result = CompletionTimingResult(
            total=4,
            early_count=1,
            ontime_count=1,
            late_count=1,
            unknown_count=1,
            items=[
                ItemCompletionTiming(
                    item_id="11111111-1111-1111-1111-111111111111",
                    classification="early",
                    deviation_minutes=-30,
                ),
                ItemCompletionTiming(
                    item_id="22222222-2222-2222-2222-222222222222",
                    classification="ontime",
                    deviation_minutes=0,
                ),
                ItemCompletionTiming(
                    item_id="33333333-3333-3333-3333-333333333333",
                    classification="late",
                    deviation_minutes=45,
                ),
            ],
        )

        self._slip_rate_result = SlipRateResult(
            total=4,
            early_count=1,
            ontime_count=1,
            late_count=1,
            unknown_count=1,
            rate=1 / 3,
        )

        self._cycle_time_result = CycleTimeResult(
            sample_count=3,
            unknown_count=1,
            mean_minutes=120.0,
            median_minutes=90.0,
            p90_minutes=200.0,
        )

    def completion_timing(self, **kwargs):
        self.last_completion_timing_kwargs = kwargs
        return self._completion_timing_result

    def slip_rate(self, **kwargs):
        self.last_slip_rate_kwargs = kwargs
        return self._slip_rate_result

    def cycle_time(self, **kwargs):
        self.last_cycle_time_kwargs = kwargs
        return self._cycle_time_result


async def _make_client_with_analytics(
    analytics: _FakeAnalytics | None,
    db: Database | None = None,
) -> TestClient:
    """Build a test client and inject a fake AnalyticsService into the app."""
    if db is None:
        db = _make_db_with_data()
    ws = WebServer(database=db)
    app = ws.create_app()
    if analytics is not None:
        from pytodo_qt.web.api import analytics_key

        app[analytics_key] = analytics
    return TestClient(TestServer(app))


class TestAnalyticsCompletionTiming:
    @pytest.mark.asyncio
    async def test_basic_response_shape(self):
        analytics = _FakeAnalytics()
        client = await _make_client_with_analytics(analytics)
        await client.start_server()
        try:
            resp = await client.get("/api/analytics/completion_timing")
            assert resp.status == 200
            data = await resp.json()
            assert data["total"] == 4
            assert data["early_count"] == 1
            assert data["ontime_count"] == 1
            assert data["late_count"] == 1
            assert data["unknown_count"] == 1
            assert len(data["items"]) == 3
            first = data["items"][0]
            assert first["item_id"] == "11111111-1111-1111-1111-111111111111"
            assert first["classification"] == "early"
            assert first["deviation_minutes"] == -30
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_filters_passed_through(self):
        analytics = _FakeAnalytics()
        client = await _make_client_with_analytics(analytics)
        await client.start_server()
        try:
            await client.get(
                "/api/analytics/completion_timing"
                "?list_id=abc&start_date=2026-04-01&end_date=2026-04-30"
            )
            assert analytics.last_completion_timing_kwargs == {
                "list_id": "abc",
                "start_date": "2026-04-01",
                "end_date": "2026-04-30",
            }
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_empty_filters_become_none(self):
        analytics = _FakeAnalytics()
        client = await _make_client_with_analytics(analytics)
        await client.start_server()
        try:
            await client.get("/api/analytics/completion_timing")
            assert analytics.last_completion_timing_kwargs == {
                "list_id": None,
                "start_date": None,
                "end_date": None,
            }
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_no_analytics_returns_503(self):
        client = await _make_client_with_analytics(None)
        await client.start_server()
        try:
            resp = await client.get("/api/analytics/completion_timing")
            assert resp.status == 503
        finally:
            await client.close()


class TestAnalyticsSlipRate:
    @pytest.mark.asyncio
    async def test_basic_response_shape(self):
        analytics = _FakeAnalytics()
        client = await _make_client_with_analytics(analytics)
        await client.start_server()
        try:
            resp = await client.get("/api/analytics/slip_rate")
            assert resp.status == 200
            data = await resp.json()
            assert data["total"] == 4
            assert data["early_count"] == 1
            assert data["ontime_count"] == 1
            assert data["late_count"] == 1
            assert data["unknown_count"] == 1
            assert data["rate"] == pytest.approx(1 / 3)
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_filters_passed_through(self):
        analytics = _FakeAnalytics()
        client = await _make_client_with_analytics(analytics)
        await client.start_server()
        try:
            await client.get("/api/analytics/slip_rate?list_id=xyz&start_date=2026-01-01")
            assert analytics.last_slip_rate_kwargs == {
                "list_id": "xyz",
                "start_date": "2026-01-01",
                "end_date": None,
            }
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_no_analytics_returns_503(self):
        client = await _make_client_with_analytics(None)
        await client.start_server()
        try:
            resp = await client.get("/api/analytics/slip_rate")
            assert resp.status == 503
        finally:
            await client.close()


class TestAnalyticsCycleTime:
    @pytest.mark.asyncio
    async def test_basic_response_shape(self):
        analytics = _FakeAnalytics()
        client = await _make_client_with_analytics(analytics)
        await client.start_server()
        try:
            resp = await client.get("/api/analytics/cycle_time")
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 3
            assert data["unknown_count"] == 1
            assert data["mean_minutes"] == 120.0
            assert data["median_minutes"] == 90.0
            assert data["p90_minutes"] == 200.0
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_filters_passed_through(self):
        analytics = _FakeAnalytics()
        client = await _make_client_with_analytics(analytics)
        await client.start_server()
        try:
            await client.get("/api/analytics/cycle_time?end_date=2026-12-31")
            assert analytics.last_cycle_time_kwargs == {
                "list_id": None,
                "start_date": None,
                "end_date": "2026-12-31",
            }
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_no_analytics_returns_503(self):
        client = await _make_client_with_analytics(None)
        await client.start_server()
        try:
            resp = await client.get("/api/analytics/cycle_time")
            assert resp.status == 503
        finally:
            await client.close()
