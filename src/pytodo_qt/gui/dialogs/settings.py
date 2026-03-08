"""settings.py

Unified settings dialog with tabbed interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.config import get_config, get_config_manager
from ...core.logger import Logger
from ...crypto import get_or_create_identity
from ..styles.themes import MONO_FONT_FAMILIES, apply_current_theme

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class SettingsDialog(QDialog):
    """Unified settings dialog with tabbed interface."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        self._config_manager = get_config_manager()
        self._config_manager.reload()  # Reload from disk to get saved values
        self._config = get_config()
        self._original_theme = self._config.appearance.theme  # Store for cancel

        self._setup_ui()
        self._load_settings()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Create tabs
        self.tabs.addTab(self._create_general_tab(), "General")
        self.tabs.addTab(self._create_network_tab(), "Network")
        self.tabs.addTab(self._create_security_tab(), "Security")
        self.tabs.addTab(self._create_sync_tab(), "Sync")
        self.tabs.addTab(self._create_appearance_tab(), "Appearance")
        self.tabs.addTab(self._create_pomodoro_tab(), "Focus Timer")
        self.tabs.addTab(self._create_web_tab(), "Web UI")

        # Button box
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        apply_btn = button_box.button(QDialogButtonBox.StandardButton.Apply)
        if apply_btn:
            apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(button_box)

    def _create_general_tab(self) -> QWidget:
        """Create the General settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Sort order group
        sort_group = QGroupBox("Sort Order")
        sort_layout = QFormLayout(sort_group)

        dimensions = [
            ("Completion", "completion"),
            ("Due Date", "due_date"),
            ("Priority", "priority"),
        ]

        self._sort_combos: list[QComboBox] = []
        self._sort_reverses: list[QCheckBox] = []

        for label_text in ["Primary:", "Secondary:", "Tertiary:"]:
            combo = QComboBox()
            for display, value in dimensions:
                combo.addItem(display, value)
            reverse = QCheckBox("Reverse")
            row_layout = QHBoxLayout()
            row_layout.addWidget(combo, 1)
            row_layout.addWidget(reverse)
            sort_layout.addRow(label_text, row_layout)
            self._sort_combos.append(combo)
            self._sort_reverses.append(reverse)
            combo.currentIndexChanged.connect(lambda _idx, c=combo: self._on_sort_tier_changed(c))

        layout.addWidget(sort_group)
        layout.addStretch()

        return widget

    def _on_sort_tier_changed(self, changed_combo: QComboBox) -> None:
        """Enforce no-duplicate constraint by swapping dimensions."""
        new_value = changed_combo.currentData()
        for combo in self._sort_combos:
            if combo is not changed_combo and combo.currentData() == new_value:
                all_values = {"completion", "due_date", "priority"}
                used = {c.currentData() for c in self._sort_combos if c is not combo}
                missing = all_values - used
                if missing:
                    old_value = missing.pop()
                    combo.blockSignals(True)
                    for i in range(combo.count()):
                        if combo.itemData(i) == old_value:
                            combo.setCurrentIndex(i)
                            break
                    combo.blockSignals(False)
                break

    def _create_network_tab(self) -> QWidget:
        """Create the Network settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Server settings group
        server_group = QGroupBox("Server")
        server_layout = QFormLayout(server_group)

        self.server_enabled_check = QCheckBox("Enable network server")
        server_layout.addRow("", self.server_enabled_check)

        self.server_address_edit = QLineEdit()
        self.server_address_edit.setPlaceholderText("0.0.0.0")
        server_layout.addRow("Bind address:", self.server_address_edit)

        self.server_port_spin = QSpinBox()
        self.server_port_spin.setRange(1024, 65535)
        self.server_port_spin.setValue(5364)
        server_layout.addRow("Port:", self.server_port_spin)

        layout.addWidget(server_group)

        # Permissions group
        perms_group = QGroupBox("Permissions")
        perms_layout = QVBoxLayout(perms_group)

        self.allow_pull_check = QCheckBox("Allow remote hosts to pull data")
        perms_layout.addWidget(self.allow_pull_check)

        self.allow_push_check = QCheckBox("Allow remote hosts to push data")
        perms_layout.addWidget(self.allow_push_check)

        layout.addWidget(perms_group)

        # Discovery settings group
        discovery_group = QGroupBox("Discovery")
        discovery_layout = QFormLayout(discovery_group)

        self.discovery_enabled_check = QCheckBox("Enable automatic discovery (mDNS)")
        discovery_layout.addRow("", self.discovery_enabled_check)

        self.service_name_edit = QLineEdit()
        self.service_name_edit.setPlaceholderText("pytodo-{hostname}")
        discovery_layout.addRow("Service name:", self.service_name_edit)

        self.auto_sync_check = QCheckBox("Auto-sync when trusted devices come online")
        discovery_layout.addRow("", self.auto_sync_check)

        layout.addWidget(discovery_group)
        layout.addStretch()

        return widget

    def _create_security_tab(self) -> QWidget:
        """Create the Security settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Identity group
        identity_group = QGroupBox("Identity")
        identity_layout = QFormLayout(identity_group)

        # Get current identity
        try:
            identity = get_or_create_identity()
            fingerprint = identity.fingerprint
        except Exception as e:
            fingerprint = f"Error: {e}"

        self.fingerprint_edit = QLineEdit(fingerprint)
        self.fingerprint_edit.setReadOnly(True)
        mono_css = ", ".join(f'"{f}"' for f in MONO_FONT_FAMILIES)
        self.fingerprint_edit.setStyleSheet(f"font-family: {mono_css};")
        identity_layout.addRow("Your fingerprint:", self.fingerprint_edit)

        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._copy_fingerprint)
        identity_layout.addRow("", copy_btn)

        layout.addWidget(identity_group)

        # Protocol group
        protocol_group = QGroupBox("Protocol")
        protocol_layout = QFormLayout(protocol_group)

        self.protocol_version_label = QLabel("2")
        protocol_layout.addRow("Protocol version:", self.protocol_version_label)

        layout.addWidget(protocol_group)

        # Trusted peers note
        note = QLabel(
            "Note: Peer trust is established on first connection (TOFU).\n"
            "Use the Peer Manager to view and manage trusted peers."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(note)

        layout.addStretch()

        return widget

    def _create_sync_tab(self) -> QWidget:
        """Create the Sync settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Sync options group
        sync_group = QGroupBox("Synchronization Options")
        sync_layout = QVBoxLayout(sync_group)

        info = QLabel(
            "Synchronization uses Last-Write-Wins (LWW) merge strategy.\n"
            "Items are identified by UUID, allowing conflict-free adds.\n"
            "Deleted items are marked as tombstones and cleaned up after 7 days."
        )
        info.setWordWrap(True)
        sync_layout.addWidget(info)

        layout.addWidget(sync_group)

        # Auto-sync group
        auto_group = QGroupBox("Automatic Sync")
        auto_layout = QFormLayout(auto_group)

        push_label = QLabel(
            "Automatically push local changes to online trusted peers\n"
            "after a quiet period with no further edits."
        )
        push_label.setWordWrap(True)
        push_label.setStyleSheet("color: gray; font-style: italic;")
        auto_layout.addRow(push_label)

        self.auto_sync_delay_spin = QSpinBox()
        self.auto_sync_delay_spin.setRange(0, 60)
        self.auto_sync_delay_spin.setSuffix(" seconds")
        self.auto_sync_delay_spin.setSpecialValueText("Disabled")
        auto_layout.addRow("Auto-push delay:", self.auto_sync_delay_spin)

        interval_label = QLabel(
            "Periodically perform a full bidirectional sync (pull + push)\n"
            "with all online trusted peers."
        )
        interval_label.setWordWrap(True)
        interval_label.setStyleSheet("color: gray; font-style: italic;")
        auto_layout.addRow(interval_label)

        self.auto_sync_interval_spin = QSpinBox()
        self.auto_sync_interval_spin.setRange(0, 120)
        self.auto_sync_interval_spin.setSuffix(" minutes")
        self.auto_sync_interval_spin.setSpecialValueText("Disabled")
        auto_layout.addRow("Periodic sync interval:", self.auto_sync_interval_spin)

        layout.addWidget(auto_group)
        layout.addStretch()

        return widget

    def _create_appearance_tab(self) -> QWidget:
        """Create the Appearance settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Theme group
        theme_group = QGroupBox("Theme")
        theme_layout = QFormLayout(theme_group)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("System (follow OS)", "system")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_layout.addRow("Theme:", self.theme_combo)

        layout.addWidget(theme_group)

        # Time display group
        time_group = QGroupBox("Time Display")
        time_layout = QFormLayout(time_group)

        self.time_format_combo = QComboBox()
        self.time_format_combo.addItem("System default", "system")
        self.time_format_combo.addItem("12-hour (2:30 PM)", "12h")
        self.time_format_combo.addItem("24-hour (14:30)", "24h")
        time_layout.addRow("Time format:", self.time_format_combo)

        layout.addWidget(time_group)

        # Preview note
        note = QLabel("Theme changes are applied immediately.")
        note.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(note)

        layout.addStretch()

        return widget

    def _create_pomodoro_tab(self) -> QWidget:
        """Create the Focus Timer settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("Focus Timer")
        form = QFormLayout(group)

        self.work_duration_spin = QSpinBox()
        self.work_duration_spin.setRange(1, 120)
        self.work_duration_spin.setSuffix(" minutes")
        form.addRow("Work duration:", self.work_duration_spin)

        self.break_duration_spin = QSpinBox()
        self.break_duration_spin.setRange(1, 30)
        self.break_duration_spin.setSuffix(" minutes")
        form.addRow("Break duration:", self.break_duration_spin)

        self.long_break_spin = QSpinBox()
        self.long_break_spin.setRange(5, 60)
        self.long_break_spin.setSuffix(" minutes")
        form.addRow("Long break:", self.long_break_spin)

        self.sessions_spin = QSpinBox()
        self.sessions_spin.setRange(2, 10)
        form.addRow("Sessions before long break:", self.sessions_spin)

        self.auto_break_check = QCheckBox("Auto-start break after work session")
        form.addRow("", self.auto_break_check)

        layout.addWidget(group)

        # Sound notifications group
        sound_group = QGroupBox("Sound Notifications")
        sound_form = QFormLayout(sound_group)

        self.sound_enabled_check = QCheckBox("Enable sound notifications")
        sound_form.addRow("", self.sound_enabled_check)

        volume_layout = QHBoxLayout()
        self.sound_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.sound_volume_slider.setRange(0, 100)
        self.sound_volume_label = QLabel("50%")
        self.sound_volume_label.setFixedWidth(40)
        volume_layout.addWidget(self.sound_volume_slider)
        volume_layout.addWidget(self.sound_volume_label)
        sound_form.addRow("Volume:", volume_layout)

        self.sound_enabled_check.stateChanged.connect(
            lambda state: self.sound_volume_slider.setEnabled(bool(state))
        )
        self.sound_volume_slider.valueChanged.connect(
            lambda val: self.sound_volume_label.setText(f"{val}%")
        )

        layout.addWidget(sound_group)

        # Daily goal group
        goal_group = QGroupBox("Daily Goal")
        goal_form = QFormLayout(goal_group)

        self.daily_goal_spin = QSpinBox()
        self.daily_goal_spin.setRange(0, 24)
        self.daily_goal_spin.setSuffix(" sessions")
        self.daily_goal_spin.setSpecialValueText("Disabled")
        goal_form.addRow("Daily target:", self.daily_goal_spin)

        self.milestone_check = QCheckBox("Show milestone celebrations")
        goal_form.addRow("", self.milestone_check)

        layout.addWidget(goal_group)
        layout.addStretch()

        return widget

    def _create_web_tab(self) -> QWidget:
        """Create the Web UI settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("Web Server")
        form = QFormLayout(group)

        self.web_enabled_check = QCheckBox("Enable Web UI")
        form.addRow("", self.web_enabled_check)

        self.web_port_spin = QSpinBox()
        self.web_port_spin.setRange(1024, 65535)
        form.addRow("Port:", self.web_port_spin)

        layout.addWidget(group)
        layout.addStretch()

        return widget

    def _load_settings(self) -> None:
        """Load current settings into the UI."""
        config = self._config

        # Sort order
        tier_values = [
            config.database.sort_tier1,
            config.database.sort_tier2,
            config.database.sort_tier3,
        ]
        tier_reverses = [
            config.database.sort_tier1_reverse,
            config.database.sort_tier2_reverse,
            config.database.sort_tier3_reverse,
        ]
        for combo, value in zip(self._sort_combos, tier_values, strict=True):
            combo.blockSignals(True)
            for i in range(combo.count()):
                if combo.itemData(i) == value:
                    combo.setCurrentIndex(i)
                    break
            combo.blockSignals(False)
        for check, rev in zip(self._sort_reverses, tier_reverses, strict=True):
            check.setChecked(rev)

        # Network
        self.server_enabled_check.setChecked(config.server.enabled)
        self.server_address_edit.setText(config.server.address)
        self.server_port_spin.setValue(config.server.port)
        self.allow_pull_check.setChecked(config.server.allow_pull)
        self.allow_push_check.setChecked(config.server.allow_push)

        # Discovery
        self.discovery_enabled_check.setChecked(config.discovery.enabled)
        self.service_name_edit.setText(config.discovery.service_name)
        self.auto_sync_check.setChecked(config.discovery.auto_sync_trusted)

        # Sync
        self.auto_sync_delay_spin.setValue(config.discovery.auto_sync_delay)
        self.auto_sync_interval_spin.setValue(config.discovery.auto_sync_interval)

        # Appearance - block signals to prevent triggering theme change during load
        self.theme_combo.blockSignals(True)
        theme = config.appearance.theme
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme:
                self.theme_combo.setCurrentIndex(i)
                break
        self.theme_combo.blockSignals(False)

        # Time format
        time_format = config.appearance.time_format
        for i in range(self.time_format_combo.count()):
            if self.time_format_combo.itemData(i) == time_format:
                self.time_format_combo.setCurrentIndex(i)
                break

        # Pomodoro
        self.work_duration_spin.setValue(config.pomodoro.work_duration)
        self.break_duration_spin.setValue(config.pomodoro.break_duration)
        self.long_break_spin.setValue(config.pomodoro.long_break_duration)
        self.sessions_spin.setValue(config.pomodoro.sessions_before_long_break)
        self.auto_break_check.setChecked(config.pomodoro.auto_start_break)
        self.sound_enabled_check.setChecked(config.pomodoro.sound_enabled)
        self.sound_volume_slider.setValue(config.pomodoro.sound_volume)
        self.sound_volume_slider.setEnabled(config.pomodoro.sound_enabled)
        self.daily_goal_spin.setValue(config.pomodoro.daily_goal)
        self.milestone_check.setChecked(config.pomodoro.milestone_notifications)

        # Web
        self.web_enabled_check.setChecked(config.web.enabled)
        self.web_port_spin.setValue(config.web.port)

    def _save_settings(self) -> bool:
        """Save settings from UI to config."""
        config = self._config

        # Sort order
        config.database.sort_tier1 = self._sort_combos[0].currentData()
        config.database.sort_tier1_reverse = self._sort_reverses[0].isChecked()
        config.database.sort_tier2 = self._sort_combos[1].currentData()
        config.database.sort_tier2_reverse = self._sort_reverses[1].isChecked()
        config.database.sort_tier3 = self._sort_combos[2].currentData()
        config.database.sort_tier3_reverse = self._sort_reverses[2].isChecked()

        # Network
        config.server.enabled = self.server_enabled_check.isChecked()
        config.server.address = self.server_address_edit.text() or "0.0.0.0"
        config.server.port = self.server_port_spin.value()
        config.server.allow_pull = self.allow_pull_check.isChecked()
        config.server.allow_push = self.allow_push_check.isChecked()

        # Discovery
        config.discovery.enabled = self.discovery_enabled_check.isChecked()
        config.discovery.service_name = self.service_name_edit.text()
        config.discovery.auto_sync_trusted = self.auto_sync_check.isChecked()

        # Sync
        config.discovery.auto_sync_delay = self.auto_sync_delay_spin.value()
        config.discovery.auto_sync_interval = self.auto_sync_interval_spin.value()

        # Appearance
        old_theme = config.appearance.theme
        new_theme = self.theme_combo.currentData()
        config.appearance.theme = new_theme
        config.appearance.time_format = self.time_format_combo.currentData()

        # Pomodoro
        config.pomodoro.work_duration = self.work_duration_spin.value()
        config.pomodoro.break_duration = self.break_duration_spin.value()
        config.pomodoro.long_break_duration = self.long_break_spin.value()
        config.pomodoro.sessions_before_long_break = self.sessions_spin.value()
        config.pomodoro.auto_start_break = self.auto_break_check.isChecked()
        config.pomodoro.sound_enabled = self.sound_enabled_check.isChecked()
        config.pomodoro.sound_volume = self.sound_volume_slider.value()
        config.pomodoro.daily_goal = self.daily_goal_spin.value()
        config.pomodoro.milestone_notifications = self.milestone_check.isChecked()

        # Web
        config.web.enabled = self.web_enabled_check.isChecked()
        config.web.port = self.web_port_spin.value()

        # Save to file
        if not self._config_manager.save():
            QMessageBox.warning(self, "Error", "Failed to save settings.")
            return False

        # Apply theme if changed
        if old_theme != new_theme:
            apply_current_theme()

        logger.log.info("Settings saved")
        return True

    def _copy_fingerprint(self) -> None:
        """Copy fingerprint to clipboard."""
        from PyQt6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.fingerprint_edit.text())
            QMessageBox.information(self, "Copied", "Fingerprint copied to clipboard.")

    def _on_accept(self) -> None:
        """Handle OK button."""
        if self._save_settings():
            self.accept()

    def _on_apply(self) -> None:
        """Handle Apply button."""
        self._save_settings()

    def _on_theme_changed(self, index: int) -> None:
        """Handle theme combo box change - apply immediately."""
        new_theme = self.theme_combo.currentData()
        self._config.appearance.theme = new_theme
        apply_current_theme()

    def reject(self) -> None:
        """Handle cancel - revert theme if changed."""
        current_theme = self._config.appearance.theme
        if current_theme != self._original_theme:
            self._config.appearance.theme = self._original_theme
            apply_current_theme()
        super().reject()
