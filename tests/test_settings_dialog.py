"""UI tests for SettingsDialog focused on the overhaul landing in
2026-04-16 — specifically the Default View + Remember-last-view
interaction and the form-wide field-growth policy.
"""

from __future__ import annotations

import copy
from datetime import time
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import QApplication, QFormLayout, QScrollArea

from pytodo_qt.core.config import NotificationConfig
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


class TestThemeAppliedSignal:
    """The dialog announces every live theme application so the main
    window can refresh theme-dependent chrome it owns (the system tray
    icon). Regression for the frozen-tray-icon bug."""

    def test_live_theme_switch_emits_theme_applied(self, app):
        dlg = SettingsDialog()
        fired: list[bool] = []
        dlg.theme_applied.connect(lambda: fired.append(True))
        combo = dlg.theme_combo
        original = combo.currentData()
        target = next(i for i in range(combo.count()) if combo.itemData(i) != original)
        # currentIndexChanged -> _on_theme_changed -> apply + emit
        combo.setCurrentIndex(target)
        assert fired, "theme_applied must fire on a live theme switch"
        # Restore the original theme so the shared QApplication palette
        # does not leak into later tests.
        combo.setCurrentIndex(
            next(i for i in range(combo.count()) if combo.itemData(i) == original)
        )
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


@pytest.fixture
def dialog(app):
    dlg = SettingsDialog()
    # Start every test from the defaults, whatever the config on disk says.
    dlg._show_notification_settings(NotificationConfig())
    dlg.time_format_combo.setCurrentIndex(dlg.time_format_combo.findData("24h"))
    yield dlg
    dlg.deleteLater()


class TestNotificationsTab:
    """The regrouped Notifications tab: what it shows, what it saves,
    and what a switched-off option greys out. Nothing here saves."""

    CHANGED = NotificationConfig(
        enabled=False,
        summary_enabled=False,
        summary_time=time(7, 45),
        preview_enabled=True,
        preview_time=time(19, 15),
        lead_enabled=False,
        lead_minutes=30,
        due_now="all",
        quiet_hours_enabled=False,
        quiet_start=time(23, 30),
        quiet_end=time(6, 15),
        quiet_allow_timed=False,
        hold_during_focus=False,
    )

    def test_shows_the_defaults(self, dialog):
        assert dialog._notification_settings_shown() == NotificationConfig()

    def test_what_is_shown_is_what_is_read_back(self, dialog):
        dialog._show_notification_settings(self.CHANGED)
        assert dialog._notification_settings_shown() == self.CHANGED

    def test_controls_carry_the_shown_values(self, dialog):
        dialog._show_notification_settings(self.CHANGED)
        assert dialog._notif_summary_time.time() == QTime(7, 45)
        assert dialog._notif_preview_enabled.isChecked()
        assert dialog._notif_preview_time.time() == QTime(19, 15)
        assert dialog._notif_lead_minutes.value() == 30
        assert dialog._notif_due_now.currentData() == "all"
        assert dialog._notif_quiet_start.time() == QTime(23, 30)
        assert dialog._notif_quiet_end.time() == QTime(6, 15)

    def test_due_now_offers_the_three_modes(self, dialog):
        combo = dialog._notif_due_now
        assert [combo.itemData(i) for i in range(combo.count())] == ["deadlines", "all", "off"]

    def test_unknown_due_now_mode_shows_the_first_choice(self, dialog):
        dialog._show_notification_settings(NotificationConfig(due_now="sometimes"))
        assert dialog._notif_due_now.currentData() == "deadlines"

    def test_lead_time_range(self, dialog):
        spin = dialog._notif_lead_minutes
        assert (spin.minimum(), spin.maximum()) == (1, 120)

    def test_removed_controls_are_gone(self, dialog):
        for name in (
            "_notif_overdue",
            "_notif_due_today",
            "_notif_check_hour",
            "_notif_upcoming_days",
        ):
            assert not hasattr(dialog, name)

    def test_time_fields_have_accessible_names(self, dialog):
        assert dialog._notif_summary_time.accessibleName()
        assert dialog._notif_preview_time.accessibleName()
        assert dialog._notif_quiet_start.accessibleName()
        assert dialog._notif_quiet_end.accessibleName()
        assert dialog._notif_lead_minutes.accessibleName()

    def test_saving_stores_what_the_tab_shows(self, dialog):
        """Saving replaces the notification settings wholesale. The
        dialog works on a copy here and its save to disk is stubbed."""
        dialog._config = copy.deepcopy(dialog._config)
        dialog._config_manager = MagicMock()
        dialog._config_manager.save.return_value = True
        dialog._show_notification_settings(self.CHANGED)

        assert dialog._save_settings()

        assert dialog._config.notifications == self.CHANGED
        dialog._config_manager.save.assert_called_once_with()

    # -- greying -----------------------------------------------------------

    def test_master_switch_greys_every_group(self, dialog):
        groups = (
            dialog._notif_summary_group,
            dialog._notif_preview_group,
            dialog._notif_timed_group,
            dialog._notif_quiet_group,
        )
        assert all(group.isEnabled() for group in groups)
        dialog._notif_enabled.setChecked(False)
        assert not any(group.isEnabled() for group in groups)
        dialog._notif_enabled.setChecked(True)
        assert all(group.isEnabled() for group in groups)

    def test_summary_switch_greys_its_time(self, dialog):
        dialog._notif_summary_enabled.setChecked(False)
        assert not dialog._notif_summary_time.isEnabled()
        assert not dialog._notif_summary_time_label.isEnabled()
        dialog._notif_summary_enabled.setChecked(True)
        assert dialog._notif_summary_time.isEnabled()

    def test_preview_is_off_and_its_time_greyed_by_default(self, dialog):
        assert not dialog._notif_preview_enabled.isChecked()
        assert not dialog._notif_preview_time.isEnabled()
        assert not dialog._notif_preview_time_label.isEnabled()
        assert dialog._notif_preview_time.time() == QTime(20, 0)

    def test_preview_switch_governs_its_time(self, dialog):
        dialog._notif_preview_enabled.setChecked(True)
        assert dialog._notif_preview_time.isEnabled()
        assert dialog._notif_preview_time_label.isEnabled()
        dialog._notif_preview_enabled.setChecked(False)
        assert not dialog._notif_preview_time.isEnabled()

    def test_preview_group_sits_between_the_summary_and_timed_reminders(self, dialog):
        layout = dialog._notif_summary_group.parentWidget().layout()
        order = [layout.itemAt(i).widget() for i in range(layout.count())]
        summary = order.index(dialog._notif_summary_group)
        assert order[summary + 1] is dialog._notif_preview_group
        assert order[summary + 2] is dialog._notif_timed_group

    def _notifications_page(self, dialog):
        names = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
        return dialog.tabs.widget(names.index("Notifications"))

    def test_tab_scrolls_rather_than_squeezing_its_rows(self, dialog):
        page = self._notifications_page(dialog)
        assert isinstance(page, QScrollArea)
        assert page.widgetResizable()
        assert page.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert page.widget() is dialog._notif_summary_group.parentWidget()

    def test_tab_asks_for_the_full_height_of_its_content(self, dialog):
        page = self._notifications_page(dialog)
        assert page.sizeHint().height() >= page.widget().sizeHint().height()
        # Tall enough that the dialog need not scroll where there is room.
        assert dialog.sizeHint().height() >= page.widget().sizeHint().height()

    def test_lead_switch_greys_the_lead_time_only(self, dialog):
        dialog._notif_lead_enabled.setChecked(False)
        assert not dialog._notif_lead_minutes.isEnabled()
        assert not dialog._notif_lead_minutes_label.isEnabled()
        assert dialog._notif_due_now.isEnabled()

    def test_quiet_switch_greys_what_it_governs(self, dialog):
        dialog._notif_quiet_enabled.setChecked(False)
        assert not dialog._notif_quiet_start.isEnabled()
        assert not dialog._notif_quiet_end.isEnabled()
        assert not dialog._notif_quiet_from_label.isEnabled()
        assert not dialog._notif_quiet_allow_timed.isEnabled()

    def test_focus_hold_does_not_depend_on_quiet_hours(self, dialog):
        dialog._notif_quiet_enabled.setChecked(False)
        assert dialog._notif_hold_during_focus.isEnabled()

    def test_greyed_values_are_still_saved(self, dialog):
        dialog._notif_quiet_start.setTime(QTime(21, 0))
        dialog._notif_quiet_enabled.setChecked(False)
        shown = dialog._notification_settings_shown()
        assert shown.quiet_hours_enabled is False
        assert shown.quiet_start == time(21, 0)

    def test_dialog_stylesheet_marks_disabled_controls(self, dialog):
        assert ":disabled" in dialog.styleSheet()
        assert "QTimeEdit" in dialog.styleSheet()

    # -- hints -------------------------------------------------------------

    def _summary_hint_shown(self, dialog) -> bool:
        return dialog._notif_summary_form.isRowVisible(dialog._notif_summary_hint)

    def _quiet_hint_shown(self, dialog) -> bool:
        return dialog._notif_quiet_form.isRowVisible(dialog._notif_quiet_hint)

    def _preview_hint_shown(self, dialog) -> bool:
        return dialog._notif_preview_form.isRowVisible(dialog._notif_preview_hint)

    def test_no_preview_hint_outside_quiet_hours(self, dialog):
        dialog._notif_preview_enabled.setChecked(True)
        assert not self._preview_hint_shown(dialog)

    def test_preview_inside_quiet_hours_says_when_it_is_shown(self, dialog):
        dialog._notif_preview_enabled.setChecked(True)
        dialog._notif_preview_time.setTime(QTime(23, 0))
        assert self._preview_hint_shown(dialog)
        assert "21:59" in dialog._notif_preview_hint.text()

    def test_preview_hint_follows_the_quiet_start(self, dialog):
        dialog._notif_preview_enabled.setChecked(True)
        dialog._notif_preview_time.setTime(QTime(23, 0))
        dialog._notif_quiet_start.setTime(QTime(22, 30))
        assert "22:29" in dialog._notif_preview_hint.text()

    def test_preview_hint_follows_the_time_format(self, dialog):
        dialog._notif_preview_enabled.setChecked(True)
        dialog._notif_preview_time.setTime(QTime(23, 0))
        dialog.time_format_combo.setCurrentIndex(dialog.time_format_combo.findData("12h"))
        assert "9:59 PM" in dialog._notif_preview_hint.text()

    def test_no_preview_hint_while_the_preview_is_off(self, dialog):
        dialog._notif_preview_time.setTime(QTime(23, 0))
        assert not self._preview_hint_shown(dialog)

    def test_no_preview_hint_while_quiet_hours_are_off(self, dialog):
        dialog._notif_preview_enabled.setChecked(True)
        dialog._notif_preview_time.setTime(QTime(23, 0))
        dialog._notif_quiet_enabled.setChecked(False)
        assert not self._preview_hint_shown(dialog)

    def test_preview_time_field_follows_the_time_format(self, dialog):
        assert dialog._notif_preview_time.displayFormat() == "HH:mm"
        dialog.time_format_combo.setCurrentIndex(dialog.time_format_combo.findData("12h"))
        assert dialog._notif_preview_time.displayFormat() == "h:mm AP"

    def test_no_hints_with_the_defaults(self, dialog):
        assert not self._summary_hint_shown(dialog)
        assert not self._quiet_hint_shown(dialog)

    def test_summary_time_inside_quiet_hours_says_when_it_is_delivered(self, dialog):
        dialog._notif_summary_time.setTime(QTime(6, 0))
        assert self._summary_hint_shown(dialog)
        assert "07:00" in dialog._notif_summary_hint.text()

    def test_summary_hint_follows_the_end_of_quiet_hours(self, dialog):
        dialog._notif_summary_time.setTime(QTime(6, 0))
        dialog._notif_quiet_end.setTime(QTime(8, 30))
        assert "08:30" in dialog._notif_summary_hint.text()

    def test_summary_hint_goes_when_the_time_leaves_quiet_hours(self, dialog):
        dialog._notif_summary_time.setTime(QTime(6, 0))
        dialog._notif_summary_time.setTime(QTime(7, 0))
        assert not self._summary_hint_shown(dialog)

    def test_no_summary_hint_with_quiet_hours_off(self, dialog):
        dialog._notif_summary_time.setTime(QTime(6, 0))
        dialog._notif_quiet_enabled.setChecked(False)
        assert not self._summary_hint_shown(dialog)

    def test_no_summary_hint_with_the_summary_off(self, dialog):
        dialog._notif_summary_time.setTime(QTime(6, 0))
        dialog._notif_summary_enabled.setChecked(False)
        assert not self._summary_hint_shown(dialog)

    def test_equal_quiet_start_and_end_is_pointed_out(self, dialog):
        dialog._notif_quiet_end.setTime(QTime(22, 0))
        assert self._quiet_hint_shown(dialog)
        assert dialog._notif_quiet_hint.text()
        dialog._notif_quiet_end.setTime(QTime(7, 0))
        assert not self._quiet_hint_shown(dialog)

    # -- time format -------------------------------------------------------

    def test_time_fields_follow_the_24_hour_setting(self, dialog):
        assert dialog._notif_summary_time.displayFormat() == "HH:mm"
        assert dialog._notif_quiet_start.displayFormat() == "HH:mm"
        assert dialog._notif_quiet_end.displayFormat() == "HH:mm"

    def test_time_fields_follow_the_12_hour_setting(self, dialog):
        dialog.time_format_combo.setCurrentIndex(dialog.time_format_combo.findData("12h"))
        assert dialog._notif_summary_time.displayFormat() == "h:mm AP"
        assert dialog._notif_quiet_end.displayFormat() == "h:mm AP"

    def test_hint_time_follows_the_format_setting(self, dialog):
        dialog._notif_summary_time.setTime(QTime(6, 0))
        dialog.time_format_combo.setCurrentIndex(dialog.time_format_combo.findData("12h"))
        assert "7:00 AM" in dialog._notif_summary_hint.text()

    def test_changing_the_format_keeps_the_times(self, dialog):
        dialog._show_notification_settings(self.CHANGED)
        dialog.time_format_combo.setCurrentIndex(dialog.time_format_combo.findData("12h"))
        assert dialog._notification_settings_shown() == self.CHANGED
