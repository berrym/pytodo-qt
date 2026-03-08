"""Tests for the Web UI REST API (Phase 5).

Covers:
- List CRUD (create, read, update, delete)
- Item CRUD (create, read, update, delete)
- Toggle completion
- Private list exclusion
- Error handling (404, 400)
- Status endpoint
- WebConfig serialization
"""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from pytodo_qt.core.config import AppConfig, WebConfig
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


async def _make_client(db: Database | None = None) -> TestClient:
    """Create an aiohttp test client with the given database."""
    if db is None:
        db = _make_db_with_data()

    ws = WebServer(database=db)
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
