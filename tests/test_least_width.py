"""A least width set in code holds once the theme is applied.

The theme's style sheet has `min-width: 100px` for a combo box. When the
sheet polishes one, Qt makes that the widget's minimum width and drops a
minimum set with `setMinimumWidth`: the view-mode combo of the settings
dialog asked for 220 px and came out at 118, less than its widest entry
needs. `set_least_width` writes the width into the widget's own sheet as
well, which comes before the theme's.

The theme's sheet is set on the widget under test, not on the
application: a sheet on the application stays for the tests that follow.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton, QVBoxLayout, QWidget

from pytodo_qt.gui.styles.themes import Theme, get_stylesheet, set_least_width

GUI_DIR = Path(__file__).resolve().parent.parent / "src" / "pytodo_qt" / "gui"


def _themed(qtbot, *widgets: QWidget, theme: Theme = Theme.LIGHT) -> QWidget:
    """The widgets in a window that has the theme's style sheet, shown."""
    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    for widget in widgets:
        layout.addWidget(widget)
    window.setStyleSheet(get_stylesheet(theme))
    window.show()
    qtbot.waitExposed(window)
    for _ in range(4):
        QApplication.processEvents()
    return window


class TestTheThemeAlone:
    def test_it_drops_a_minimum_width_set_in_code(self, qtbot):
        """What `set_least_width` is there for."""
        combo = QComboBox()
        combo.setMinimumWidth(220)
        keep = _themed(qtbot, combo)
        assert combo.minimumWidth() < 220
        assert keep is not None


class TestSetLeastWidth:
    @pytest.mark.parametrize("theme", [Theme.LIGHT, Theme.DARK])
    def test_a_combo_box_keeps_its_least_width(self, qtbot, theme):
        combo = QComboBox()
        set_least_width(combo, 220)
        keep = _themed(qtbot, combo, theme=theme)
        assert combo.minimumWidth() >= 220
        assert keep is not None

    def test_it_holds_before_the_theme_is_applied_too(self, qtbot):
        combo = QComboBox()
        qtbot.addWidget(combo)
        set_least_width(combo, 220)
        assert combo.minimumWidth() == 220

    def test_a_button_keeps_its_least_width(self, qtbot):
        """The theme has a `min-width` for buttons as well."""
        button = QPushButton("Go")
        set_least_width(button, 200)
        keep = _themed(qtbot, button)
        assert button.minimumWidth() >= 200
        assert keep is not None

    def test_a_sheet_the_widget_has_already_is_kept(self, qtbot):
        combo = QComboBox()
        qtbot.addWidget(combo)
        combo.setStyleSheet("QComboBox { font-weight: bold; }")
        set_least_width(combo, 220)
        assert "font-weight: bold" in combo.styleSheet()
        assert "min-width: 220px" in combo.styleSheet()

    def test_the_rule_is_for_the_widget_only(self, qtbot):
        """A sheet of bare properties would reach the popup and the
        tooltip of the combo box as well."""
        combo = QComboBox()
        qtbot.addWidget(combo)
        set_least_width(combo, 220)
        assert combo.styleSheet() == "QComboBox { min-width: 220px; }"

    def test_other_combo_boxes_keep_the_themes_least_width(self, qtbot):
        plain = QComboBox()
        wide = QComboBox()
        set_least_width(wide, 220)
        keep = _themed(qtbot, plain, wide)
        assert plain.minimumWidth() < 220
        assert keep is not None


class TestTheCombosThatAskForAWidth:
    def test_the_view_mode_combo_of_the_settings_dialog(self, qtbot):
        from pytodo_qt.gui.dialogs.settings import SettingsDialog

        dialog = SettingsDialog()
        qtbot.addWidget(dialog)
        dialog.setStyleSheet(get_stylesheet(Theme.LIGHT))
        dialog.show()
        qtbot.waitExposed(dialog)
        combo = dialog._view_mode_combo
        widest = max(
            combo.fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count())
        )
        assert combo.minimumWidth() >= 220
        assert combo.minimumWidth() >= widest
        assert combo.width() >= combo.minimumWidth()

    def test_the_combo_of_the_list_selector(self, qtbot):
        from pytodo_qt.gui.widgets.list_selector import ListSelectorWidget

        selector = ListSelectorWidget()
        keep = _themed(qtbot, selector)
        assert selector.combo.minimumWidth() >= 200
        assert keep is not None

    def test_no_combo_box_is_given_a_minimum_width_the_theme_would_drop(self):
        """A combo box that needs a least width gets it from
        `set_least_width`."""
        pattern = re.compile(r"\w*combo\w*\.setMinimumWidth\(", re.IGNORECASE)
        found = [
            f"{path.relative_to(GUI_DIR)}: {match.group(0)}"
            for path in sorted(GUI_DIR.rglob("*.py"))
            for match in pattern.finditer(path.read_text(encoding="utf-8"))
        ]
        assert found == []
