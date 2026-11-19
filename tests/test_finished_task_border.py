"""The green border that marks a finished task in the list view and on the board.

A finished task's Reminder box and its card are filled with the theme's
`completed_bg`, which is too near the colour around it to mark anything
by itself: 1.08:1 against the row in the light theme. The box and the
card have a border in the theme's `due_soon` green as well. WCAG AA asks
3:1 of a graphic that carries a state.
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from pytodo_qt.core.bar_palette import contrast_ratio
from pytodo_qt.core.models import create_todo_item, create_todo_list
from pytodo_qt.gui.styles.themes import (
    DARK_COLORS,
    FINISHED_BORDER_PX,
    LIGHT_COLORS,
    Theme,
    apply_theme,
)
from pytodo_qt.gui.widgets.kanban_board import KanbanCardWidget
from pytodo_qt.gui.widgets.todo_table import ReminderEdit, TodoTableWidget

_THEME_COLORS = {"light": LIGHT_COLORS, "dark": DARK_COLORS}


@pytest.fixture(params=["light", "dark"])
def themed(request, qtbot, monkeypatch):
    """The application in one of the two themes; gives the theme's colours."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    theme = Theme(request.param)
    monkeypatch.setattr("pytodo_qt.gui.styles.themes.get_current_theme", lambda: theme)
    palette, sheet = app.palette(), app.styleSheet()
    apply_theme(app, theme)
    yield _THEME_COLORS[request.param]
    app.setPalette(palette)
    app.setStyleSheet(sheet)


def _colours(widget: QWidget) -> set[str]:
    """Every colour of the widget as it is painted."""
    app = QApplication.instance()
    assert app is not None
    for _ in range(3):
        app.processEvents()
    image = widget.grab().toImage()
    return {
        QColor(image.pixel(x, y)).name()
        for y in range(image.height())
        for x in range(image.width())
    }


class TestTheGreenCanBeMadeOut:
    @pytest.mark.parametrize("around", ["base", "alternate_base", "completed_bg"])
    def test_the_border_has_three_to_one_against_what_is_around_it(self, themed, around):
        """The row and the alternate row outside the box, the board's
        column, which has the alternate row's colour, and the fill inside."""
        assert contrast_ratio(themed["due_soon"], themed[around]) >= 3

    def test_the_fill_alone_does_not(self, themed):
        """What the border is there for."""
        assert contrast_ratio(themed["completed_bg"], themed["base"]) < 1.2

    def test_the_border_is_wider_than_an_ordinary_one(self):
        assert FINISHED_BORDER_PX == 2


class TestListView:
    @pytest.fixture()
    def table(self, qtbot, themed):
        todo_list = create_todo_list("Rows")
        todo_list.add_item(create_todo_item("an open task"))
        finished = create_todo_item("a finished task")
        finished.complete = True
        todo_list.add_item(finished)

        # Another field has the focus, so that no row's field is drawn
        # with the border of a focused one.
        window = QWidget()
        qtbot.addWidget(window)
        layout = QVBoxLayout(window)
        elsewhere = QLineEdit()
        widget = TodoTableWidget()
        layout.addWidget(elsewhere)
        layout.addWidget(widget)
        window.resize(700, 300)
        widget.set_list(todo_list)
        elsewhere.setFocus()
        window.show()
        qtbot.waitExposed(window)
        widget.clearSelection()
        widget.themed = themed
        widget.shown_in = window  # kept alive with the table
        return widget

    @staticmethod
    def _field(table, text: str) -> ReminderEdit:
        for row in range(table.rowCount()):
            field = table.cellWidget(row, 1).findChild(ReminderEdit)
            if field.stored_text == text:
                return field
        raise AssertionError(text)

    def test_a_finished_tasks_box_has_the_green_border(self, table):
        colors = table.themed
        field = self._field(table, "a finished task")
        assert f"border: {FINISHED_BORDER_PX}px solid {colors['due_soon']}" in field.styleSheet()
        painted = _colours(field)
        assert colors["due_soon"] in painted
        assert colors["completed_bg"] in painted

    def test_an_open_tasks_box_has_not(self, table):
        colors = table.themed
        field = self._field(table, "an open task")
        assert colors["due_soon"] not in field.styleSheet()
        assert colors["due_soon"] not in _colours(field)

    def test_the_focused_box_keeps_the_border_of_a_focused_field(self, table):
        """The field's own sheet comes before the application's, whose
        rule for a focused field it would otherwise hide."""
        colors = table.themed
        sheet = self._field(table, "a finished task").styleSheet()
        assert f"QLineEdit:focus {{ border: 2px solid {colors['highlight']}; }}" in sheet

    def test_the_text_keeps_its_colours(self, table):
        colors = table.themed
        sheet = self._field(table, "a finished task").styleSheet()
        assert f"color: {colors['completed_text']};" in sheet
        assert f"background-color: {colors['completed_bg']};" in sheet
        assert contrast_ratio(colors["completed_text"], colors["completed_bg"]) >= 4.5


class TestBoardCard:
    @staticmethod
    def _card(qtbot, colors, complete: bool) -> KanbanCardWidget:
        item = create_todo_item("a task")
        item.complete = complete
        card = KanbanCardWidget(item, colors, "24h", [], False)
        qtbot.addWidget(card)
        card.resize(240, 60)
        card.show()
        return card

    def test_a_finished_tasks_card_has_the_green_border(self, themed, qtbot):
        card = self._card(qtbot, themed, complete=True)
        assert f"border: {FINISHED_BORDER_PX}px solid {themed['due_soon']};" in card.styleSheet()
        assert themed["due_soon"] in _colours(card)

    def test_an_open_tasks_card_has_not(self, themed, qtbot):
        card = self._card(qtbot, themed, complete=False)
        assert themed["due_soon"] not in card.styleSheet()
        assert f"border: 1px solid {themed['border']};" in card.styleSheet()

    def test_the_priority_bar_at_the_left_is_kept(self, themed, qtbot):
        card = self._card(qtbot, themed, complete=True)
        assert f"border-left: 4px solid {themed['priority_normal']};" in card.styleSheet()

    def test_a_selected_finished_card_has_the_border_of_a_selected_one(self, themed, qtbot):
        card = self._card(qtbot, themed, complete=True)
        card.set_selected(True)
        assert f"border: 2px solid {themed['highlight']};" in card.styleSheet()
        card.set_selected(False)
        assert f"border: {FINISHED_BORDER_PX}px solid {themed['due_soon']};" in card.styleSheet()
