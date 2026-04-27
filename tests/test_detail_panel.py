"""Tests for TaskDetailPanel subtask CRUD, drill-down, and breadcrumb."""

from __future__ import annotations

from pytodo_qt.core.models import create_todo_item, create_todo_list
from pytodo_qt.gui.widgets.detail_panel import TaskDetailPanel


class TestSubtasksSectionVisibility:
    """+ Add Subtask is visible for top-level items regardless of
    edit mode (it opens a confirmation dialog, so it's not destructive
    and doesn't need the edit-mode safety gate). Single-layer nesting
    means subtasks never expose the add control."""

    def test_add_button_visible_for_top_level_in_view_mode(self, qtbot):
        panel = TaskDetailPanel()
        panel.show()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        item = create_todo_item("Top-level")
        lst.add_item(item)
        panel.set_item(item, lst)
        # View mode (default) — add button is still visible because
        # add-subtask is non-destructive.
        assert panel._add_subtask_btn.isVisible() is True

    def test_add_button_visible_in_edit_mode_for_top_level_item(self, qtbot):
        panel = TaskDetailPanel()
        panel.show()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        item = create_todo_item("Top-level")
        lst.add_item(item)
        panel.set_item(item, lst)
        panel.set_edit_mode(True)
        assert panel._add_subtask_btn.isVisible() is True

    def test_add_button_hidden_for_subtask_in_view_mode(self, qtbot):
        """Single-layer nesting: when the current item is itself a
        subtask, the + Add Subtask button must stay hidden so a
        grandchild cannot be created from this panel."""
        panel = TaskDetailPanel()
        panel.show()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        parent = create_todo_item("Parent")
        lst.add_item(parent)
        sub = create_todo_item("Sub")
        sub.parent_id = parent.id
        lst.add_item(sub)

        panel.set_item(sub, lst)
        assert panel._add_subtask_btn.isVisible() is False

    def test_add_button_hidden_in_edit_mode_for_subtask(self, qtbot):
        """Edit mode does not unlock the add control for subtasks —
        single-layer nesting is enforced regardless of mode."""
        panel = TaskDetailPanel()
        panel.show()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        parent = create_todo_item("Parent")
        lst.add_item(parent)
        sub = create_todo_item("Sub")
        sub.parent_id = parent.id
        lst.add_item(sub)

        panel.set_item(sub, lst)
        panel.set_edit_mode(True)
        assert panel._add_subtask_btn.isVisible() is False


class TestSubtasksRendering:
    """The Subtasks section renders one row per direct child of the
    current item, respecting completion state."""

    def test_empty_state_when_no_subtasks(self, qtbot):
        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        item = create_todo_item("Lonely")
        lst.add_item(item)
        panel.set_item(item, lst)
        assert panel._subtasks_empty_label.isHidden() is False

    def test_rows_render_for_each_direct_child(self, qtbot):
        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        parent = create_todo_item("Parent")
        lst.add_item(parent)
        for n in range(3):
            sub = create_todo_item(f"Sub {n}")
            sub.parent_id = parent.id
            lst.add_item(sub)

        panel.set_item(parent, lst)
        # Empty-state label + 3 subtask rows = 4 items in the layout.
        assert panel._subtasks_layout.count() == 4
        assert panel._subtasks_empty_label.isHidden() is True

    def test_unrelated_items_are_not_rendered_as_subtasks(self, qtbot):
        """Items whose parent_id points to some OTHER parent must
        not appear as subtasks of the current item."""
        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        parent_a = create_todo_item("Parent A")
        parent_b = create_todo_item("Parent B")
        lst.add_item(parent_a)
        lst.add_item(parent_b)
        sub_b = create_todo_item("Sub under B")
        sub_b.parent_id = parent_b.id
        lst.add_item(sub_b)

        panel.set_item(parent_a, lst)
        # Empty-state label only — no rows for B's subtask.
        assert panel._subtasks_layout.count() == 1


class TestSubtasksSignals:
    """The four subtask signals fire correctly from user interactions."""

    def _top_level_with_one_sub(self):
        lst = create_todo_list("L")
        parent = create_todo_item("Parent")
        lst.add_item(parent)
        sub = create_todo_item("Sub")
        sub.parent_id = parent.id
        lst.add_item(sub)
        return lst, parent, sub

    def test_add_button_emits_subtask_add_requested(self, qtbot):
        panel = TaskDetailPanel()
        panel.show()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        parent = create_todo_item("Parent")
        lst.add_item(parent)
        panel.set_item(parent, lst)
        panel.set_edit_mode(True)

        received: list = []
        panel.subtask_add_requested.connect(received.append)
        panel._add_subtask_btn.click()
        assert received == [parent.id]

    def test_delete_button_emits_subtask_delete_requested(self, qtbot):
        panel = TaskDetailPanel()
        panel.show()
        qtbot.addWidget(panel)
        lst, parent, sub = self._top_level_with_one_sub()
        panel.set_item(parent, lst)
        panel.set_edit_mode(True)

        # Pick the delete button off the first subtask row.
        row_item = panel._subtasks_layout.itemAt(1)  # 0 = empty label (hidden)
        assert row_item is not None
        row_widget = row_item.widget()
        assert row_widget is not None
        delete_btn = row_widget._delete_btn

        received: list = []
        panel.subtask_delete_requested.connect(received.append)
        delete_btn.click()
        assert received == [sub.id]

    def test_toggle_emits_subtask_complete_toggled(self, qtbot):
        from PyQt6.QtWidgets import QCheckBox

        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst, parent, sub = self._top_level_with_one_sub()
        panel.set_item(parent, lst)

        row_item = panel._subtasks_layout.itemAt(1)
        assert row_item is not None
        row_widget = row_item.widget()
        assert row_widget is not None
        checkbox = row_widget.findChild(QCheckBox)
        assert checkbox is not None

        received: list = []
        panel.subtask_complete_toggled.connect(lambda iid, checked: received.append((iid, checked)))
        checkbox.setChecked(True)
        assert received == [(sub.id, True)]

    def test_title_click_emits_subtask_selected(self, qtbot):
        from PyQt6.QtWidgets import QPushButton

        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst, parent, sub = self._top_level_with_one_sub()
        panel.set_item(parent, lst)

        row_item = panel._subtasks_layout.itemAt(1)
        assert row_item is not None
        row_widget = row_item.widget()
        assert row_widget is not None
        # The row has two buttons (title + delete). The title button is
        # flat with the subtask's reminder as its text.
        title_btn: QPushButton | None = None
        for btn in row_widget.findChildren(QPushButton):
            if btn.text() == sub.reminder:
                title_btn = btn
                break
        assert title_btn is not None

        received: list = []
        panel.subtask_selected.connect(received.append)
        title_btn.click()
        assert received == [sub.id]


class TestParentBreadcrumb:
    """The parent breadcrumb is visible only when the current item is
    a subtask and fires parent_navigation_requested on click."""

    def test_breadcrumb_hidden_for_top_level_item(self, qtbot):
        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        item = create_todo_item("Top-level")
        lst.add_item(item)
        panel.set_item(item, lst)
        assert panel._parent_breadcrumb.isHidden() is True

    def test_breadcrumb_visible_for_subtask(self, qtbot):
        panel = TaskDetailPanel()
        panel.show()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        parent = create_todo_item("Plan the thing")
        lst.add_item(parent)
        sub = create_todo_item("Step 1")
        sub.parent_id = parent.id
        lst.add_item(sub)
        panel.set_item(sub, lst)
        assert panel._parent_breadcrumb.isHidden() is False
        assert "Plan the thing" in panel._parent_breadcrumb.text()

    def test_breadcrumb_click_emits_parent_navigation(self, qtbot):
        panel = TaskDetailPanel()
        panel.show()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        parent = create_todo_item("Plan")
        lst.add_item(parent)
        sub = create_todo_item("Step")
        sub.parent_id = parent.id
        lst.add_item(sub)
        panel.set_item(sub, lst)

        received: list = []
        panel.parent_navigation_requested.connect(received.append)
        panel._parent_breadcrumb.click()
        assert received == [parent.id]


class TestIndependentCompletion:
    """Parent/child completion states do not couple. Toggling one
    side via the panel signals must NOT touch the other side in the
    in-memory model (the commands route through MainWindow, which is
    not under test here; this test asserts the panel itself does
    not mutate completion state of items it did not receive a toggle
    for)."""

    def test_parent_complete_does_not_change_subtask_complete_in_panel(self, qtbot):
        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        parent = create_todo_item("Parent")
        lst.add_item(parent)
        sub = create_todo_item("Sub")
        sub.parent_id = parent.id
        lst.add_item(sub)

        # Complete the parent in the model directly; the panel just
        # displays.
        parent.complete = True
        panel.set_item(parent, lst)
        assert sub.complete is False  # sub untouched

    def test_toggle_emits_only_for_the_clicked_subtask(self, qtbot):
        from PyQt6.QtWidgets import QCheckBox

        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        parent = create_todo_item("Parent")
        lst.add_item(parent)
        subs = []
        for n in range(3):
            sub = create_todo_item(f"Sub {n}")
            sub.parent_id = parent.id
            lst.add_item(sub)
            subs.append(sub)
        panel.set_item(parent, lst)

        received: list = []
        panel.subtask_complete_toggled.connect(lambda iid, checked: received.append(iid))

        # Toggle the middle subtask only.
        middle_row = panel._subtasks_layout.itemAt(2).widget()  # 0=empty, 1=first
        assert middle_row is not None
        cb = middle_row.findChild(QCheckBox)
        assert cb is not None
        cb.setChecked(True)

        assert received == [subs[1].id]


class TestDueTimeEnd:
    """The detail panel exposes due_time_end as an editable QTimeEdit
    that round-trips through the item_due_time_end_changed signal."""

    def test_loads_due_time_end_from_item(self, qtbot):
        from datetime import time as time_type

        from PyQt6.QtCore import QTime

        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        item = create_todo_item("Standup")
        item.due_time_end = time_type(9, 30)
        lst.add_item(item)
        panel.set_item(item, lst)
        assert panel._due_time_end_edit.time() == QTime(9, 30)

    def test_loads_zero_when_no_due_time_end(self, qtbot):
        from PyQt6.QtCore import QTime

        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        item = create_todo_item("Standup")
        lst.add_item(item)
        panel.set_item(item, lst)
        assert panel._due_time_end_edit.time() == QTime(0, 0)

    def test_edit_emits_signal(self, qtbot):
        from datetime import time as time_type

        from PyQt6.QtCore import QTime

        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        item = create_todo_item("Standup")
        item.due_time_end = time_type(9, 0)
        lst.add_item(item)
        panel.set_item(item, lst)
        panel.set_edit_mode(True)

        received: list[tuple] = []
        panel.item_due_time_end_changed.connect(lambda iid, t: received.append((iid, t)))
        panel._due_time_end_edit.setTime(QTime(9, 45))
        assert len(received) == 1
        assert received[0][0] == item.id
        assert received[0][1] == time_type(9, 45)

    def test_view_mode_does_not_emit(self, qtbot):
        from datetime import time as time_type

        from PyQt6.QtCore import QTime

        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        lst = create_todo_list("L")
        item = create_todo_item("Standup")
        item.due_time_end = time_type(9, 0)
        lst.add_item(item)
        panel.set_item(item, lst)
        # No set_edit_mode(True) — stays in view mode.

        received: list = []
        panel.item_due_time_end_changed.connect(lambda iid, t: received.append((iid, t)))
        panel._due_time_end_edit.setTime(QTime(9, 45))
        assert received == []
