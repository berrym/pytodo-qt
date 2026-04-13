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

    def test_completed_at_default_is_none(self):
        """A new TodoItem has completed_at=None (we don't know when it was completed)."""
        item = create_todo_item("Test")
        assert item.completed_at is None

    def test_set_complete_true_writes_timestamp(self):
        """set_complete(True) writes a fresh completed_at timestamp."""
        item = create_todo_item("Test")
        assert item.complete is False
        assert item.completed_at is None

        item.set_complete(True)

        assert item.complete is True
        assert item.completed_at is not None
        assert item.completed_at > 0

    def test_set_complete_false_clears_timestamp(self):
        """set_complete(False) clears completed_at to None."""
        item = create_todo_item("Test")
        item.set_complete(True)
        assert item.completed_at is not None

        item.set_complete(False)

        assert item.complete is False
        assert item.completed_at is None

    def test_set_complete_is_noop_when_already_in_state(self):
        """set_complete to the current state does not modify the item."""
        item = create_todo_item("Test")
        # Already incomplete, calling set_complete(False) should be a no-op
        original_updated = item.updated_at
        item.set_complete(False)
        assert item.completed_at is None
        assert item.updated_at == original_updated

        # Mark complete, then call set_complete(True) again — also a no-op
        item.set_complete(True)
        first_completion = item.completed_at
        first_updated = item.updated_at
        item.set_complete(True)
        assert item.completed_at == first_completion  # not regenerated
        assert item.updated_at == first_updated

    def test_toggle_complete_now_writes_timestamp(self):
        """toggle_complete delegates to set_complete and writes the timestamp."""
        item = create_todo_item("Test")
        assert item.completed_at is None

        item.toggle_complete()
        assert item.complete is True
        assert item.completed_at is not None

        item.toggle_complete()
        assert item.complete is False
        assert item.completed_at is None

    def test_completed_at_round_trip(self):
        """completed_at survives to_dict / from_dict round-trip including None."""
        item = create_todo_item("Test")
        item.complete = True
        item.completed_at = 1_700_000_000_000  # arbitrary ms timestamp

        data = item.to_dict()
        assert data["completed_at"] == 1_700_000_000_000

        item2 = TodoItem.from_dict(data)
        assert item2.completed_at == 1_700_000_000_000

        # NULL round-trip
        item3 = create_todo_item("Test 3")
        item3.complete = True  # complete but unknown when
        data3 = item3.to_dict()
        assert data3["completed_at"] is None
        item4 = TodoItem.from_dict(data3)
        assert item4.completed_at is None


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
