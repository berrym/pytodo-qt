"""A date or a time editor has the box a spin box has.

The theme's style sheet gave spin boxes, combo boxes and line edits a
box: the base color, a border of one pixel in the theme's border color,
a radius, padding. Date and time editors had no rule, and the platform's
style drew them: flat, ten pixels lower than a spin box, and in the dark
theme with the platform's light box. They stand beside the styled boxes
in the detail panel, in the dialogs for a task and in the settings.

The theme's sheet is set on the widget under test, not on the
application: a sheet on the application stays for the tests that follow.
"""

from __future__ import annotations

from collections import Counter

import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QDateEdit,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QTimeEdit,
    QWidget,
)

from pytodo_qt.core.bar_palette import contrast_ratio
from pytodo_qt.gui.styles.themes import DARK_COLORS, LIGHT_COLORS, Theme, get_stylesheet

_THEMES = [(Theme.LIGHT, LIGHT_COLORS), (Theme.DARK, DARK_COLORS)]


def _calendar_editor() -> QDateEdit:
    editor = QDateEdit()
    editor.setCalendarPopup(True)
    return editor


_EDITORS = {
    "date editor": QDateEdit,
    "date editor with a calendar": _calendar_editor,
    "time editor": QTimeEdit,
}


@pytest.fixture(params=_THEMES, ids=["light", "dark"])
def row(request, qtbot):
    """A spin box and the three editors in a window with the theme's
    sheet. Another field has the focus."""
    theme, colors = request.param
    window = QWidget()
    qtbot.addWidget(window)
    layout = QHBoxLayout(window)
    elsewhere = QLineEdit()
    layout.addWidget(elsewhere)
    boxes: dict[str, QWidget] = {"spin box": QSpinBox()}
    for name, make in _EDITORS.items():
        boxes[name] = make()
    for box in boxes.values():
        layout.addWidget(box)
    window.setStyleSheet(get_stylesheet(theme))
    window.resize(900, 70)
    window.show()
    elsewhere.setFocus()
    qtbot.waitExposed(window)
    for _ in range(6):
        QApplication.processEvents()
    return window, boxes, colors


def _top_edge(box: QWidget) -> str:
    """The color of the box's top edge, its rounded corners left out."""
    image = box.grab().toImage()
    edge = Counter(QColor(image.pixel(x, 0)).name() for x in range(12, image.width() - 12))
    return edge.most_common(1)[0][0]


def _inside(box: QWidget) -> str:
    image = box.grab().toImage()
    return QColor(image.pixel(8, image.height() - 6)).name()


class TestTheBox:
    @pytest.mark.parametrize("name", list(_EDITORS))
    def test_an_editor_has_the_themes_border(self, row, name):
        _window, boxes, colors = row
        assert _top_edge(boxes[name]) == colors["border"]
        assert _top_edge(boxes[name]) == _top_edge(boxes["spin box"])

    @pytest.mark.parametrize("name", list(_EDITORS))
    def test_an_editor_is_filled_with_the_base_color(self, row, name):
        """Not with the platform's own, which is light in both themes."""
        _window, boxes, colors = row
        assert _inside(boxes[name]) == colors["base"]

    @pytest.mark.parametrize("name", list(_EDITORS))
    def test_an_editor_is_as_high_as_a_spin_box(self, row, name):
        _window, boxes, _colors = row
        assert boxes[name].height() == boxes["spin box"].height()

    def test_the_border_can_be_made_out(self, row):
        _window, _boxes, colors = row
        assert contrast_ratio(colors["border"], colors["base"]) >= 3
        assert contrast_ratio(colors["border"], colors["window"]) >= 3

    def test_the_text_can_be_read(self, row):
        _window, _boxes, colors = row
        assert contrast_ratio(colors["text"], colors["base"]) >= 4.5


class TestTheStyleSheet:
    @pytest.mark.parametrize("theme", [Theme.LIGHT, Theme.DARK])
    def test_the_editors_are_named_with_the_spin_boxes(self, theme):
        sheet = get_stylesheet(theme)
        assert "QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {" in sheet


class TestTheDetailPanelsViewMode:
    def test_an_editor_that_only_shows_a_value_has_no_box(self, qtbot):
        """Outside its edit mode the panel shows its values as text:
        its own sheet for the editors comes before the theme's."""
        from pytodo_qt.gui.widgets.detail_panel import TaskDetailPanel

        panel = TaskDetailPanel()
        qtbot.addWidget(panel)
        view_mode = panel._VIEW_MODE_STYLE
        assert "QDateEdit, QTimeEdit" in view_mode
        assert "border: none" in view_mode
