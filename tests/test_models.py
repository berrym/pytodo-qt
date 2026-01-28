"""Tests for data models."""

from uuid import UUID

from pytodo_qt.core.models import (
    Database,
    TodoItem,
    TodoList,
    create_todo_item,
    create_todo_list,
)


class TestTodoItem:
    """Tests for TodoItem model."""

    def test_create_item(self):
        """Test creating a todo item."""
        item = create_todo_item("Test reminder", priority=1)

        assert item.reminder == "Test reminder"
        assert item.priority == 1
        assert item.complete is False
        assert item.deleted is False
        assert isinstance(item.id, UUID)

    def test_toggle_complete(self):
        """Test toggling completion status."""
        import time

        item = create_todo_item("Test")
        original_updated = item.updated_at

        time.sleep(0.002)  # Ensure timestamp advances
        item.toggle_complete()

        assert item.complete is True
        assert item.updated_at >= original_updated

        item.toggle_complete()

        assert item.complete is False

    def test_mark_deleted(self):
        """Test marking item as deleted."""
        item = create_todo_item("Test")

        item.mark_deleted()

        assert item.deleted is True

    def test_serialization(self):
        """Test to_dict and from_dict."""
        item = create_todo_item("Test reminder", priority=2)
        item.complete = True

        data = item.to_dict()
        item2 = TodoItem.from_dict(data)

        assert item2.id == item.id
        assert item2.reminder == item.reminder
        assert item2.priority == item.priority
        assert item2.complete == item.complete

    def test_from_legacy(self):
        """Test creating from legacy format."""
        legacy = {
            "reminder": "Old item",
            "priority": 1,
            "complete": True,
        }

        item = TodoItem.from_legacy(legacy)

        assert item.reminder == "Old item"
        assert item.priority == 1
        assert item.complete is True
        assert isinstance(item.id, UUID)


class TestTodoList:
    """Tests for TodoList model."""

    def test_create_list(self):
        """Test creating a todo list."""
        lst = create_todo_list("My List")

        assert lst.name == "My List"
        assert len(lst.items) == 0
        assert isinstance(lst.id, UUID)

    def test_add_item(self):
        """Test adding items to list."""
        lst = create_todo_list("Test")
        item = create_todo_item("Task 1")

        lst.add_item(item)

        assert len(lst.items) == 1
        assert item.id in lst.items

    def test_remove_item(self):
        """Test removing items from list."""
        lst = create_todo_list("Test")
        item = create_todo_item("Task 1")
        lst.add_item(item)

        result = lst.remove_item(item.id)

        assert result is True
        assert item.deleted is True

    def test_active_items(self):
        """Test filtering active (non-deleted) items."""
        lst = create_todo_list("Test")
        item1 = create_todo_item("Task 1")
        item2 = create_todo_item("Task 2")
        lst.add_item(item1)
        lst.add_item(item2)

        item1.mark_deleted()

        active = list(lst.active_items())

        assert len(active) == 1
        assert active[0].id == item2.id

    def test_completed_count(self):
        """Test counting completed items."""
        lst = create_todo_list("Test")
        item1 = create_todo_item("Task 1")
        item2 = create_todo_item("Task 2")
        lst.add_item(item1)
        lst.add_item(item2)

        item1.complete = True

        assert lst.completed_count() == 1

    def test_serialization(self):
        """Test to_dict and from_dict."""
        lst = create_todo_list("Test List")
        item = create_todo_item("Task 1")
        lst.add_item(item)

        data = lst.to_dict()
        lst2 = TodoList.from_dict(data)

        assert lst2.id == lst.id
        assert lst2.name == lst.name
        assert len(lst2.items) == 1

    def test_from_legacy(self):
        """Test creating from legacy format."""
        legacy_items = [
            {"reminder": "Task 1", "priority": 1, "complete": False},
            {"reminder": "Task 2", "priority": 2, "complete": True},
        ]

        lst = TodoList.from_legacy("Old List", legacy_items)

        assert lst.name == "Old List"
        assert lst.active_item_count() == 2


class TestDatabase:
    """Tests for Database model."""

    def test_create_database(self):
        """Test creating a database."""
        db = Database()

        assert len(db.lists) == 0
        assert db.active_list_id is None

    def test_add_list(self):
        """Test adding lists to database."""
        db = Database()
        lst = create_todo_list("Test")

        db.add_list(lst)

        assert len(db.lists) == 1
        assert db.get_list(lst.id) == lst

    def test_active_list(self):
        """Test active list management."""
        db = Database()
        lst = create_todo_list("Test")
        db.add_list(lst)

        db.set_active_list(lst.id)

        assert db.active_list == lst

    def test_set_active_list_by_name(self):
        """Test setting active list by name."""
        db = Database()
        lst = create_todo_list("My List")
        db.add_list(lst)

        result = db.set_active_list_by_name("My List")

        assert result is True
        assert db.active_list_id == lst.id

    def test_list_names(self):
        """Test getting list names."""
        db = Database()
        db.add_list(create_todo_list("List A"))
        db.add_list(create_todo_list("List B"))

        names = db.list_names()

        assert "List A" in names
        assert "List B" in names

    def test_total_items(self):
        """Test counting total items."""
        db = Database()
        lst1 = create_todo_list("List 1")
        lst1.add_item(create_todo_item("Task 1"))
        lst1.add_item(create_todo_item("Task 2"))

        lst2 = create_todo_list("List 2")
        lst2.add_item(create_todo_item("Task 3"))

        db.add_list(lst1)
        db.add_list(lst2)

        assert db.total_items() == 3

    def test_json_serialization(self):
        """Test JSON serialization."""
        db = Database()
        lst = create_todo_list("Test")
        lst.add_item(create_todo_item("Task"))
        db.add_list(lst)
        db.set_active_list(lst.id)

        json_str = db.to_json()
        db2 = Database.from_json(json_str)

        assert len(db2.lists) == 1
        assert db2.active_list_id == lst.id

    def test_from_legacy(self):
        """Test creating from legacy format."""
        legacy = {
            "Shopping": [
                {"reminder": "Buy milk", "priority": 2, "complete": False},
            ],
            "Work": [
                {"reminder": "Email boss", "priority": 1, "complete": True},
            ],
        }

        db = Database.from_legacy(legacy)

        assert len(list(db.active_lists())) == 2
        assert db.total_items() == 2
