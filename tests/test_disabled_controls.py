"""A disabled control can be told from an enabled one.

The theme's style sheet had no rule for a disabled control: a combo box,
a field, a spin box and a button had the same border, fill and text
color disabled as enabled, in both themes. The default view dropdown of
the settings dialog, disabled while the last view is remembered, did not
open and did not look as if it would not.

The theme's sheet is set on the widget under test, not on the
application: a sheet on the application stays for the tests that follow.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, QPoint
from PyQt6.QtGui import QColor, QFont, QHelpEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from pytodo_qt.core.bar_palette import contrast_ratio
from pytodo_qt.gui.styles.themes import (
    DARK_COLORS,
    LIGHT_COLORS,
    Theme,
    arrow_icon_path,
    get_stylesheet,
)

_THEMES = [(Theme.LIGHT, LIGHT_COLORS), (Theme.DARK, DARK_COLORS)]


def _combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("MMMM")
    return combo


def _thick(widget: QWidget) -> QWidget:
    """In large bold type, whose strokes have whole pixels on every platform."""
    font = QFont(widget.font())
    font.setPixelSize(20)
    font.setBold(True)
    widget.setFont(font)
    return widget


_KINDS = {
    "line edit": lambda: QLineEdit("MMMM"),
    "combo box": _combo,
    "spin box": QSpinBox,
    "date editor": QDateEdit,
    "time editor": QTimeEdit,
    "button": lambda: QPushButton("MMMM"),
}


@pytest.fixture(params=_THEMES, ids=["light", "dark"])
def pairs(request, qtbot):
    """Each kind of control enabled and disabled, in a window with the
    theme's sheet."""
    theme, colors = request.param
    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    made: dict[str, tuple[QWidget, QWidget]] = {}
    for name, make in _KINDS.items():
        enabled, disabled = _thick(make()), _thick(make())
        disabled.setEnabled(False)
        layout.addWidget(enabled)
        layout.addWidget(disabled)
        made[name] = (enabled, disabled)
    window.setStyleSheet(get_stylesheet(theme))
    window.resize(420, 760)
    window.show()
    qtbot.waitExposed(window)
    for _ in range(6):
        QApplication.processEvents()
    return made, colors, window


def _fill(widget: QWidget) -> str:
    """The color inside the control's box, clear of its text and arrows."""
    image = widget.grab().toImage()
    return QColor(image.pixel(image.width() // 2, image.height() - 4)).name()


def _strongest(widget: QWidget, against: str) -> float:
    """The highest contrast any painted pixel inside the box has with a color."""
    image = widget.grab().toImage()
    return max(
        contrast_ratio(QColor(image.pixel(x, y)).name(), against)
        for y in range(6, image.height() - 6)
        for x in range(8, image.width() - 30)
    )


class TestADisabledControl:
    @pytest.mark.parametrize("kind", list(_KINDS))
    def test_it_has_the_windows_color_as_its_fill(self, pairs, kind):
        made, colors, _window = pairs
        enabled, disabled = made[kind]
        assert _fill(disabled) == colors["window"]
        assert _fill(enabled) != _fill(disabled)

    @pytest.mark.parametrize("kind", ["line edit", "combo box", "button"])
    def test_its_text_is_muted(self, pairs, kind):
        """No pixel of it is as strong as ordinary text."""
        made, colors, _window = pairs
        _enabled, disabled = made[kind]
        muted = contrast_ratio(colors["completed_text"], colors["window"])
        ordinary = contrast_ratio(colors["text"], colors["window"])
        strongest = _strongest(disabled, colors["window"])
        assert strongest <= muted + 0.4
        assert strongest < ordinary - 2

    @pytest.mark.parametrize("kind", ["line edit", "combo box", "button"])
    def test_its_text_can_still_be_read(self, pairs, kind):
        made, colors, _window = pairs
        _enabled, disabled = made[kind]
        assert _strongest(disabled, colors["window"]) >= 4.5
        assert contrast_ratio(colors["completed_text"], colors["window"]) >= 4.5

    def test_its_border_can_be_made_out(self, pairs):
        _made, colors, _window = pairs
        assert contrast_ratio(colors["border"], colors["window"]) >= 3


class TestTheStyleSheet:
    @pytest.mark.parametrize(("theme", "colors"), _THEMES, ids=["light", "dark"])
    def test_every_kind_of_box_has_the_rule(self, theme, colors):
        sheet = get_stylesheet(theme)
        rule = re.search(r"QLineEdit:disabled,[^{]*\{([^}]*)\}", sheet)
        assert rule is not None
        selectors = sheet[rule.start() : rule.start(1)]
        for kind in (
            "QLineEdit",
            "QTextEdit",
            "QPlainTextEdit",
            "QComboBox",
            "QSpinBox",
            "QDoubleSpinBox",
            "QDateEdit",
            "QTimeEdit",
        ):
            assert f"{kind}:disabled" in selectors
        assert f"background-color: {colors['window']};" in rule.group(1)
        assert f"color: {colors['completed_text']};" in rule.group(1)

    @pytest.mark.parametrize(("theme", "colors"), _THEMES, ids=["light", "dark"])
    def test_a_disabled_box_has_a_muted_arrow(self, theme, colors):
        sheet = get_stylesheet(theme)
        for direction in ("up", "down"):
            muted = arrow_icon_path(direction, theme, muted=True)
            assert Path(muted).is_file()
            assert f'fill="{colors["completed_text"]}"' in Path(muted).read_text()
            assert f'image: url("{muted}");' in sheet
        assert "QComboBox::down-arrow:disabled" in sheet
        assert "QSpinBox::up-arrow:disabled" in sheet

    @pytest.mark.parametrize("theme", [Theme.LIGHT, Theme.DARK])
    def test_the_muted_arrow_is_not_the_ordinary_one(self, theme):
        for direction in ("up", "down"):
            assert arrow_icon_path(direction, theme, muted=True) != arrow_icon_path(
                direction, theme
            )

    @pytest.mark.parametrize(("theme", "colors"), _THEMES, ids=["light", "dark"])
    def test_a_disabled_check_box_is_muted_too(self, theme, colors, qtbot):
        sheet = get_stylesheet(theme)
        assert "QCheckBox:disabled" in sheet
        assert "QCheckBox::indicator:checked:disabled" in sheet
        box = QCheckBox("MMMM")
        box.setChecked(True)
        box.setEnabled(False)
        window = QWidget()
        qtbot.addWidget(window)
        QVBoxLayout(window).addWidget(box)
        window.setStyleSheet(sheet)
        window.show()
        qtbot.waitExposed(window)
        painted = box.grab().toImage()
        colors_painted = {
            QColor(painted.pixel(x, y)).name()
            for y in range(painted.height())
            for x in range(min(30, painted.width()))
        }
        assert colors["completed_text"] in colors_painted
        assert colors["highlight"] not in colors_painted


class TestTheDefaultViewDropdown:
    """Disabled while "Remember last view between sessions" is checked."""

    HINT = "Uncheck 'Remember last view between sessions' to choose a default view."

    @pytest.fixture
    def dialog(self, qtbot):
        from pytodo_qt.gui.dialogs.settings import SettingsDialog

        settings_dialog = SettingsDialog()
        qtbot.addWidget(settings_dialog)
        return settings_dialog

    def test_disabled_it_says_what_enables_it(self, dialog):
        dialog._remember_view_check.setChecked(True)
        assert not dialog._view_mode_combo.isEnabled()
        assert dialog._view_mode_combo.toolTip() == self.HINT

    def test_enabled_it_has_no_hint(self, dialog):
        dialog._remember_view_check.setChecked(True)
        dialog._remember_view_check.setChecked(False)
        assert dialog._view_mode_combo.isEnabled()
        assert dialog._view_mode_combo.toolTip() == ""

    def test_the_state_the_dialog_opens_with_has_the_hint_too(self, dialog):
        """The check box is set from the configuration without the
        signal that a click sends."""
        assert dialog._remember_view_check.isChecked() != dialog._view_mode_combo.isEnabled()
        expected = "" if dialog._view_mode_combo.isEnabled() else self.HINT
        assert dialog._view_mode_combo.toolTip() == expected

    def test_a_disabled_control_shows_its_tooltip(self, dialog, qtbot):
        """Qt delivers the tooltip event to a disabled widget."""
        dialog._remember_view_check.setChecked(True)
        dialog.show()
        qtbot.waitExposed(dialog)
        combo = dialog._view_mode_combo
        spot = QPoint(5, 5)
        QApplication.sendEvent(
            combo, QHelpEvent(QEvent.Type.ToolTip, spot, combo.mapToGlobal(spot))
        )
        try:
            assert QToolTip.text() == self.HINT
        finally:
            QToolTip.hideText()
