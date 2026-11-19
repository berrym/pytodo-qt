"""A tooltip has the theme's background wherever it is shown.

A tooltip takes the style sheets of the widget it is shown for, and of
that widget's ancestors, before the application's. A sheet written as
bare properties, without a selector, applies to everything below the
widget, and a tooltip counts as below. The board's column had
`background: transparent;` in that form on the scroll area of its cards:
every tooltip of a card had no background, appeared on black, and in the
light theme its dark text gave 1.21:1.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, time, timedelta

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QLabel, QToolTip, QVBoxLayout, QWidget

from pytodo_qt.core.bar_palette import contrast_ratio
from pytodo_qt.core.models import create_todo_item, create_todo_list
from pytodo_qt.gui.styles.themes import DARK_COLORS, LIGHT_COLORS, Theme, apply_theme
from pytodo_qt.gui.widgets.kanban_board import KanbanBoardWidget, KanbanCardWidget
from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

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
    QToolTip.hideText()
    app.setPalette(palette)
    app.setStyleSheet(sheet)


def _tooltip_of(widget: QWidget) -> tuple[str, int, str]:
    """The tooltip shown for a widget: its background, the background's
    opacity, and its text colour."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    QToolTip.hideText()
    QToolTip.showText(widget.mapToGlobal(QPoint(1, 1)), "MMMM tooltip", widget)
    app.processEvents()
    shown = [
        top
        for top in app.topLevelWidgets()
        if top.metaObject().className() == "QTipLabel" and top.isVisible()
    ]
    assert shown, "no tooltip was shown"
    tip = shown[-1]
    image = tip.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    counts: Counter[tuple[str, int]] = Counter()
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = QColor.fromRgba(image.pixel(x, y))
            counts[(pixel.name(), pixel.alpha())] += 1
    (background, opacity), _ = counts.most_common(1)[0]
    return background, opacity, tip.palette().color(tip.foregroundRole()).name()


def _with_a_tooltip(root: QWidget) -> list[QWidget]:
    return [
        widget
        for widget in [root, *root.findChildren(QWidget)]
        if widget.toolTip() and widget.isVisible() and widget.width() > 1 and widget.height() > 1
    ]


def _todo_list():
    today = date.today()
    todo_list = create_todo_list("Tooltips")

    def add(name, **fields):
        item = create_todo_item(name, due_date=fields.pop("due_date", None))
        for key, value in fields.items():
            setattr(item, key, value)
        todo_list.add_item(item)
        return item

    add(
        "repeating, due today",
        due_date=today,
        due_time=time(15, 0),
        recurrence_type="daily",
        recurrence_interval=1,
        missed_recurrences=2,
        tags=["@one"],
    )
    add("overdue", due_date=today - timedelta(days=3))
    add("due later", due_date=today + timedelta(days=3), event_date=today + timedelta(days=5))
    add("finished", due_date=today, complete=True, board_column="Done")
    return todo_list


def _show(qtbot, widget: QWidget) -> None:
    qtbot.addWidget(widget)
    widget.resize(1000, 600)
    widget.show()
    qtbot.waitExposed(widget)
    for _ in range(3):
        QApplication.processEvents()


class TestTheMechanism:
    def test_a_bare_sheet_on_an_ancestor_reaches_the_tooltip(self, themed, qtbot):
        """What the widgets have to avoid."""
        outer = QWidget()
        outer.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(outer)
        label = QLabel("inside")
        layout.addWidget(label)
        _show(qtbot, outer)

        _background, opacity, _text = _tooltip_of(label)

        assert opacity == 0

    def test_a_sheet_with_a_selector_does_not(self, themed, qtbot):
        outer = QWidget()
        outer.setObjectName("outer")
        outer.setStyleSheet("#outer { background: transparent; }")
        layout = QVBoxLayout(outer)
        label = QLabel("inside")
        layout.addWidget(label)
        _show(qtbot, outer)

        assert _tooltip_of(label) == (themed["base"], 255, themed["text"])


class TestBoard:
    @pytest.fixture()
    def board(self, qtbot, themed):
        widget = KanbanBoardWidget()
        widget.set_list(_todo_list())
        _show(qtbot, widget)
        return widget

    def test_a_cards_tooltip_has_the_themes_colours(self, board, themed):
        cards = board.findChildren(KanbanCardWidget)
        assert len(cards) == 4
        for card in cards:
            assert card.toolTip()
            assert _tooltip_of(card) == (themed["base"], 255, themed["text"])

    def test_every_tooltip_on_the_board_has_the_themes_colours(self, board, themed):
        """The Due text, the recurrence mark, the missed count and the
        event date of a card have tooltips of their own, and the first
        and the last column an icon with one."""
        widgets = _with_a_tooltip(board)
        assert len(widgets) >= 10
        for widget in widgets:
            assert _tooltip_of(widget) == (themed["base"], 255, themed["text"]), (
                type(widget).__name__,
                widget.toolTip()[:40],
            )

    def test_the_tooltips_text_can_be_read(self, board, themed):
        background, opacity, text = _tooltip_of(board.findChildren(KanbanCardWidget)[0])
        assert opacity == 255
        assert contrast_ratio(text, background) >= 4.5


class TestListView:
    def test_every_tooltip_has_the_themes_background_and_text_that_can_be_read(self, qtbot, themed):
        """The priority box gives its tooltip its own text colour, which
        is one of the priority colours and reads on the background."""
        table = TodoTableWidget()
        table.set_list(_todo_list())
        _show(qtbot, table)

        widgets = _with_a_tooltip(table)
        assert len(widgets) >= 8
        for widget in widgets:
            background, opacity, text = _tooltip_of(widget)
            assert (background, opacity) == (themed["base"], 255), type(widget).__name__
            assert contrast_ratio(text, background) >= 4.5, type(widget).__name__
