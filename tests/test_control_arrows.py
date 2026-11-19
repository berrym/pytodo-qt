"""Spin, date, time and combo boxes show arrows the theme draws.

A style sheet that gives a box a border and padding takes its drawing
away from the platform style, and Qt then draws its own arrows: three
pixels wide, in no color the theme chose. The arrows are images in the
theme's text color, one pair for each theme.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QSpinBox,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionSpinBox,
    QTimeEdit,
)

from pytodo_qt.gui.styles.themes import (
    DARK_COLORS,
    LIGHT_COLORS,
    Theme,
    arrow_icon_path,
    get_stylesheet,
)

ARROW_PX = 16


class TestTheArrowImages:
    @pytest.mark.parametrize("theme", [Theme.DARK, Theme.LIGHT])
    @pytest.mark.parametrize("direction", ["up", "down"])
    def test_each_theme_has_one_in_its_text_color(self, theme, direction):
        path = Path(arrow_icon_path(direction, theme))
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        colors = DARK_COLORS if theme == Theme.DARK else LIGHT_COLORS
        assert re.search(rf'fill="{colors["text"]}"', text, re.IGNORECASE)

    @pytest.mark.parametrize("theme", [Theme.DARK, Theme.LIGHT])
    def test_the_style_sheet_names_them(self, theme):
        sheet = get_stylesheet(theme)
        up = arrow_icon_path("up", theme)
        down = arrow_icon_path("down", theme)
        for selector in (
            "QSpinBox::up-arrow",
            "QDoubleSpinBox::up-arrow",
            "QDateEdit::up-arrow",
            "QTimeEdit::up-arrow",
        ):
            assert re.search(rf"{selector}[^}}]*image:\s*url\(\"?{re.escape(up)}\"?\)", sheet), (
                selector
            )
        for selector in (
            "QSpinBox::down-arrow",
            "QDoubleSpinBox::down-arrow",
            "QDateEdit::down-arrow",
            "QTimeEdit::down-arrow",
            "QComboBox::down-arrow",
        ):
            assert re.search(rf"{selector}[^}}]*image:\s*url\(\"?{re.escape(down)}\"?\)", sheet), (
                selector
            )


class TestTheButtonsHaveRoom:
    """The sheet is set on the box itself, not the application: a sheet
    on the application stays with it for the tests that follow."""

    @pytest.mark.parametrize("cls", [QSpinBox, QDateEdit, QTimeEdit])
    def test_the_spin_buttons_are_wide_enough(self, qtbot, cls):
        box = cls()
        qtbot.addWidget(box)
        box.setStyleSheet(get_stylesheet(Theme.DARK))
        box.resize(200, 36)
        box.show()
        qtbot.waitExposed(box)
        option = QStyleOptionSpinBox()
        box.initStyleOption(option)
        style = box.style()
        assert style is not None
        for sub_control in (QStyle.SubControl.SC_SpinBoxUp, QStyle.SubControl.SC_SpinBoxDown):
            rect = style.subControlRect(QStyle.ComplexControl.CC_SpinBox, option, sub_control, box)
            assert rect.width() >= ARROW_PX, sub_control

    def test_the_combo_drop_down_is_wide_enough(self, qtbot):
        combo = QComboBox()
        combo.addItems(["one", "two"])
        qtbot.addWidget(combo)
        combo.setStyleSheet(get_stylesheet(Theme.DARK))
        combo.resize(200, 36)
        combo.show()
        qtbot.waitExposed(combo)
        option = QStyleOptionComboBox()
        combo.initStyleOption(option)
        style = combo.style()
        assert style is not None
        rect = style.subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxArrow, combo
        )
        assert rect.width() >= ARROW_PX
