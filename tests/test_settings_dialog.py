"""UI tests for SettingsDialog focused on the overhaul landing in
2026-04-16 — specifically the Default View + Remember-last-view
interaction and the form-wide field-growth policy.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFormLayout

from pytodo_qt.gui.dialogs.settings import SettingsDialog


@pytest.fixture(scope="session")
def app():
    _app = QApplication.instance()
    if _app is None:
        _app = QApplication([])
    return _app


class TestDefaultViewDropdown:
    """Default View dropdown presence, calendar option, width, and
    checkbox gating."""

    def test_dropdown_has_three_options_including_calendar(self, app):
        dlg = SettingsDialog()
        combo = dlg._view_mode_combo
        values = [combo.itemData(i) for i in range(combo.count())]
        assert values == ["list", "board", "calendar"], (
            "Default view dropdown must include Calendar alongside List and Board(Kanban)"
        )
        dlg.deleteLater()

    def test_dropdown_has_minimum_width(self, app):
        """The dropdown needs enough width to display 'Board (Kanban)'
        on any platform without truncation."""
        dlg = SettingsDialog()
        assert dlg._view_mode_combo.minimumWidth() >= 200
        dlg.deleteLater()

    def test_remember_checkbox_defaults_to_checked(self, app):
        dlg = SettingsDialog()
        # Mirrors the config default (True preserves pre-overhaul behaviour)
        assert dlg._remember_view_check.isChecked() is True
        # And the dropdown is disabled (greyed out) in that state —
        # it has no effect until the user opts out.
        assert dlg._view_mode_combo.isEnabled() is False
        dlg.deleteLater()

    def test_unchecking_enables_dropdown(self, app):
        dlg = SettingsDialog()
        dlg._remember_view_check.setChecked(False)
        assert dlg._view_mode_combo.isEnabled() is True
        dlg.deleteLater()

    def test_checking_disables_dropdown(self, app):
        dlg = SettingsDialog()
        # Start unchecked
        dlg._remember_view_check.setChecked(False)
        assert dlg._view_mode_combo.isEnabled() is True
        # Then check — dropdown must grey out
        dlg._remember_view_check.setChecked(True)
        assert dlg._view_mode_combo.isEnabled() is False
        dlg.deleteLater()


class TestSettingsDialogFormConsistency:
    """Every QFormLayout in the dialog must have
    AllNonFixedFieldsGrow set so LineEdits / ComboBoxes / SpinBoxes
    expand consistently across platforms."""

    def test_all_forms_expand_fields(self, app):
        dlg = SettingsDialog()
        forms = dlg.findChildren(QFormLayout)
        assert forms, "Dialog should contain at least one QFormLayout"
        for form in forms:
            assert (
                form.fieldGrowthPolicy() == QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
            ), f"QFormLayout at {form} is missing AllNonFixedFieldsGrow policy"
        dlg.deleteLater()

    def test_service_name_edit_has_min_width(self, app):
        dlg = SettingsDialog()
        assert dlg.service_name_edit.minimumWidth() >= 300
        dlg.deleteLater()

    def test_fingerprint_edit_has_min_width(self, app):
        dlg = SettingsDialog()
        # Must fit a 64-char SHA-256 hex at monospace without scrolling
        assert dlg.fingerprint_edit.minimumWidth() >= 500
        dlg.deleteLater()

    def test_dialog_stylesheet_sets_min_height(self, app):
        """The dialog-wide stylesheet rule that fixes Focus Timer
        spin-box vertical clipping must remain applied."""
        dlg = SettingsDialog()
        assert "min-height" in dlg.styleSheet()
        assert "QSpinBox" in dlg.styleSheet()
        dlg.deleteLater()

    def test_web_pairing_pin_label_has_min_height(self, app):
        """Web UI tab's PIN label uses a 28 px font; without an
        explicit minimum height Qt's sizeHint on styled QLabels
        undershoots and clips descenders vertically."""
        dlg = SettingsDialog()
        assert dlg.web_pin_label.minimumHeight() >= 50
        dlg.deleteLater()


class TestNoLiteralMonospaceFontFamily:
    """Regression guard: no Python source file should use the CSS
    generic "monospace" as a QSS font-family value or as a QFont
    constructor family argument. Qt's font-alias system triggers a
    ~120 ms resolution cost and a "Replace uses of missing font
    family" console warning on systems where the generic doesn't
    resolve to an installed family (common on fresh macOS installs
    without Terminal.app opened). Use the MONO_FONT_FAMILIES stack
    from gui.styles.themes instead.
    """

    def test_no_literal_monospace_in_python_sources(self) -> None:
        import re
        from pathlib import Path

        src_root = Path(__file__).parent.parent / "src" / "pytodo_qt"
        # Match either `font-family: monospace` inside a QSS string
        # or `QFont("monospace", ...)` / `QFont('monospace', ...)`.
        qss_pattern = re.compile(r"font-family\s*:\s*monospace\b")
        qfont_pattern = re.compile(r"""QFont\s*\(\s*["']monospace["']""")

        offenders: list[str] = []
        for path in src_root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if qss_pattern.search(text) or qfont_pattern.search(text):
                offenders.append(str(path.relative_to(src_root)))

        assert not offenders, (
            "The following Python files use the CSS generic 'monospace' "
            "literally. Use the MONO_FONT_FAMILIES stack from "
            "gui.styles.themes instead to avoid Qt font-alias resolution "
            f"warnings: {offenders}"
        )


class TestRememberLastViewQtEnum:
    """Regression guard for the Qt enum comparison in
    _on_remember_view_toggled — PyQt6 stateChanged emits an int,
    Qt.CheckState.Checked.value is also an int, so the comparison
    `state == Qt.CheckState.Checked.value` returns correctly."""

    def test_toggle_handler_reacts_to_checked_state(self, app):
        dlg = SettingsDialog()
        # Simulate the signal the way Qt would emit it
        dlg._on_remember_view_toggled(Qt.CheckState.Checked.value)
        assert dlg._view_mode_combo.isEnabled() is False
        dlg._on_remember_view_toggled(Qt.CheckState.Unchecked.value)
        assert dlg._view_mode_combo.isEnabled() is True
        dlg.deleteLater()
