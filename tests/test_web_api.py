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

from datetime import date, timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer

from pytodo_qt.core.config import AppConfig, ConfigManager, WebConfig
from pytodo_qt.core.models import (
    Database,
    create_todo_item,
    create_todo_list,
)
from pytodo_qt.web.api import database_key
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


class TestWebSocket:
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
                msg = await ws_conn.receive_json(timeout=2.0)
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
                msg = await ws_conn.receive_json(timeout=2.0)
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
                msg = await ws_conn.receive_json(timeout=2.0)
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
                msg1 = await ws1.receive_json(timeout=2.0)
                msg2 = await ws2.receive_json(timeout=2.0)
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
                msg = await ws2.receive_json(timeout=2.0)
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
                msg = await ws_conn.receive_json(timeout=2.0)
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
                msg = await ws_conn.receive_json(timeout=2.0)
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
                msg = await ws_conn.receive_json(timeout=2.0)
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
                msg = await ws_conn.receive_json(timeout=2.0)
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
                msg1 = await ws1.receive_json(timeout=2.0)
                msg2 = await ws2.receive_json(timeout=2.0)
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
