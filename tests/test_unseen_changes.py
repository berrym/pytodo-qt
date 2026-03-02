"""Tests for unseen sync changes tracking and list selector indicators."""

from uuid import uuid4

import pytest
from PyQt6.QtGui import QStandardItemModel

from pytodo_qt.core.models import Database, TodoItem, TodoList
from pytodo_qt.gui.widgets.list_selector import ListSelectorWidget


@pytest.fixture()
def two_list_db():
    """Create a database with two non-empty lists."""
    db = Database()
    list_a = TodoList(name="Shopping")
    list_a.items[uuid4()] = TodoItem(reminder="Milk")
    list_b = TodoList(name="Work")
    list_b.items[uuid4()] = TodoItem(reminder="Review PR")
    db.lists[list_a.id] = list_a
    db.lists[list_b.id] = list_b
    db.active_list_id = list_a.id
    return db, list_a, list_b


class TestListSelectorUnseen:
    """Tests for unseen change indicators on the list selector."""

    def test_no_styling_when_no_unseen(self, qtbot, two_list_db):
        """Widget should have no special styling when no unseen changes."""
        db, list_a, _list_b = two_list_db
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        widget.set_database(db)
        widget.set_unseen(set())

        assert widget.combo.styleSheet() == ""

    def test_border_when_unseen(self, qtbot, two_list_db):
        """Combo box should get a highlighted border when unseen changes exist."""
        db, _list_a, list_b = two_list_db
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        widget.set_database(db)
        widget.set_unseen({list_b.id})

        assert widget.combo.styleSheet() != ""
        assert "border" in widget.combo.styleSheet()

    def test_border_clears_when_unseen_empty(self, qtbot, two_list_db):
        """Border should clear when unseen set becomes empty."""
        db, _list_a, list_b = two_list_db
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        widget.set_database(db)

        widget.set_unseen({list_b.id})
        assert widget.combo.styleSheet() != ""

        widget.set_unseen(set())
        assert widget.combo.styleSheet() == ""

    def test_dot_icon_on_unseen_non_private_list(self, qtbot, two_list_db):
        """Non-private list with unseen changes should get a dot icon."""
        db, _list_a, list_b = two_list_db
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        widget.set_database(db)
        widget.set_unseen({list_b.id})

        model = widget.combo.model()
        assert isinstance(model, QStandardItemModel)

        # Find the Work list item
        for i in range(model.rowCount()):
            if widget.combo.itemData(i) == list_b.id:
                item = model.item(i)
                assert item is not None
                assert not item.icon().isNull()
                break
        else:
            pytest.fail("Work list not found in combo box")

    def test_text_color_on_unseen_list(self, qtbot, two_list_db):
        """Unseen list should have tinted text color."""
        db, _list_a, list_b = two_list_db
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        widget.set_database(db)
        widget.set_unseen({list_b.id})

        model = widget.combo.model()
        assert isinstance(model, QStandardItemModel)

        for i in range(model.rowCount()):
            if widget.combo.itemData(i) == list_b.id:
                item = model.item(i)
                assert item is not None
                # Foreground should be set (non-default)
                brush = item.foreground()
                assert brush.color().name() != "#000000"  # Not default black
                break
        else:
            pytest.fail("Work list not found in combo box")

    def test_no_styling_on_non_unseen_list(self, qtbot, two_list_db):
        """Lists without unseen changes should have no special styling."""
        db, list_a, list_b = two_list_db
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        widget.set_database(db)
        widget.set_unseen({list_b.id})

        model = widget.combo.model()
        assert isinstance(model, QStandardItemModel)

        for i in range(model.rowCount()):
            if widget.combo.itemData(i) == list_a.id:
                item = model.item(i)
                assert item is not None
                # Non-private, non-unseen list should have no icon
                assert item.icon().isNull()
                break
        else:
            pytest.fail("Shopping list not found in combo box")

    def test_private_list_keeps_lock_icon(self, qtbot, two_list_db):
        """Private list with unseen changes should keep its lock icon."""
        db, _list_a, list_b = two_list_db
        list_b.private = True
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        widget.set_database(db)
        widget.set_unseen({list_b.id})

        model = widget.combo.model()
        assert isinstance(model, QStandardItemModel)

        for i in range(model.rowCount()):
            if widget.combo.itemData(i) == list_b.id:
                item = model.item(i)
                assert item is not None
                # Should have icon (the lock, not replaced by dot)
                assert not item.icon().isNull()
                # Should still have tinted text
                brush = item.foreground()
                assert brush.color().name() != "#000000"
                break
        else:
            pytest.fail("Work list not found in combo box")

    def test_refresh_preserves_unseen_styling(self, qtbot, two_list_db):
        """Unseen styling should survive a refresh() call."""
        db, _list_a, list_b = two_list_db
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        widget.set_database(db)
        widget.set_unseen({list_b.id})

        # Refresh rebuilds all items
        widget.refresh()

        # Styling should still be applied
        assert widget.combo.styleSheet() != ""
        model = widget.combo.model()
        assert isinstance(model, QStandardItemModel)
        for i in range(model.rowCount()):
            if widget.combo.itemData(i) == list_b.id:
                item = model.item(i)
                assert item is not None
                assert not item.icon().isNull()
                break

    def test_dot_clears_when_list_viewed(self, qtbot, two_list_db):
        """Dot icon and text color should clear when list is removed from unseen set."""
        db, list_a, list_b = two_list_db
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        widget.set_database(db)
        widget.set_unseen({list_b.id})

        model = widget.combo.model()
        assert isinstance(model, QStandardItemModel)

        # Verify dot is present
        for i in range(model.rowCount()):
            if widget.combo.itemData(i) == list_b.id:
                item = model.item(i)
                assert item is not None
                assert not item.icon().isNull()
                break

        # Clear unseen (simulates viewing the list)
        widget.set_unseen(set())

        # Dot and text color should be gone
        for i in range(model.rowCount()):
            if widget.combo.itemData(i) == list_b.id:
                item = model.item(i)
                assert item is not None
                assert item.icon().isNull()
                break

    def test_make_dot_icon_produces_valid_icon(self, qtbot):
        """_make_dot_icon should produce a non-null icon."""
        widget = ListSelectorWidget()
        qtbot.addWidget(widget)
        icon = widget._make_dot_icon("#0078d4")
        assert not icon.isNull()
