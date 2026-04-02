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
    QFontDialog,
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
        self.setWindowTitle(self.tr("Settings"))
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
        self.tabs.addTab(self._create_general_tab(), self.tr("General"))
        self.tabs.addTab(self._create_network_tab(), self.tr("Network"))
        self.tabs.addTab(self._create_security_tab(), self.tr("Security"))
        self.tabs.addTab(self._create_sync_tab(), self.tr("Sync"))
        self.tabs.addTab(self._create_appearance_tab(), self.tr("Appearance"))
        self.tabs.addTab(self._create_pomodoro_tab(), self.tr("Focus Timer"))
        self.tabs.addTab(self._create_web_tab(), self.tr("Web UI"))

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
        sort_group = QGroupBox(self.tr("Sort Order"))
        sort_layout = QFormLayout(sort_group)

        dimensions = [
            (self.tr("Completion"), "completion"),
            (self.tr("Due Date"), "due_date"),
            (self.tr("Priority"), "priority"),
        ]

        self._sort_combos: list[QComboBox] = []
        self._sort_reverses: list[QCheckBox] = []

        for label_text in [self.tr("Primary:"), self.tr("Secondary:"), self.tr("Tertiary:")]:
            combo = QComboBox()
            for display, value in dimensions:
                combo.addItem(display, value)
            reverse = QCheckBox(self.tr("Reverse"))
            row_layout = QHBoxLayout()
            row_layout.addWidget(combo, 1)
            row_layout.addWidget(reverse)
            sort_layout.addRow(label_text, row_layout)
            self._sort_combos.append(combo)
            self._sort_reverses.append(reverse)
            combo.currentIndexChanged.connect(lambda _idx, c=combo: self._on_sort_tier_changed(c))

        layout.addWidget(sort_group)

        # View mode group
        view_group = QGroupBox(self.tr("View"))
        view_layout = QFormLayout(view_group)
        self._view_mode_combo = QComboBox()
        self._view_mode_combo.addItem(self.tr("List"), "list")
        self._view_mode_combo.addItem(self.tr("Board (Kanban)"), "board")
        view_layout.addRow(self.tr("Default view:"), self._view_mode_combo)
        layout.addWidget(view_group)

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
        server_group = QGroupBox(self.tr("Server"))
        server_layout = QFormLayout(server_group)

        self.server_enabled_check = QCheckBox(self.tr("Enable network server"))
        server_layout.addRow("", self.server_enabled_check)

        self.server_address_edit = QLineEdit()
        self.server_address_edit.setPlaceholderText("0.0.0.0")
        server_layout.addRow(self.tr("Bind address:"), self.server_address_edit)

        self.server_port_spin = QSpinBox()
        self.server_port_spin.setRange(1024, 65535)
        self.server_port_spin.setValue(5364)
        server_layout.addRow(self.tr("Port:"), self.server_port_spin)

        layout.addWidget(server_group)

        # Permissions group
        perms_group = QGroupBox(self.tr("Permissions"))
        perms_layout = QVBoxLayout(perms_group)

        self.allow_pull_check = QCheckBox(self.tr("Allow remote hosts to pull data"))
        perms_layout.addWidget(self.allow_pull_check)

        self.allow_push_check = QCheckBox(self.tr("Allow remote hosts to push data"))
        perms_layout.addWidget(self.allow_push_check)

        layout.addWidget(perms_group)

        # Discovery settings group
        discovery_group = QGroupBox(self.tr("Discovery"))
        discovery_layout = QFormLayout(discovery_group)

        self.discovery_enabled_check = QCheckBox(self.tr("Enable automatic discovery (mDNS)"))
        discovery_layout.addRow("", self.discovery_enabled_check)

        self.service_name_edit = QLineEdit()
        self.service_name_edit.setPlaceholderText("pytodo-{hostname}")
        discovery_layout.addRow(self.tr("Service name:"), self.service_name_edit)

        self.auto_sync_check = QCheckBox(self.tr("Auto-sync when trusted devices come online"))
        discovery_layout.addRow("", self.auto_sync_check)

        layout.addWidget(discovery_group)
        layout.addStretch()

        return widget

    def _create_security_tab(self) -> QWidget:
        """Create the Security settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Identity group
        identity_group = QGroupBox(self.tr("Identity"))
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
        identity_layout.addRow(self.tr("Your fingerprint:"), self.fingerprint_edit)

        copy_btn = QPushButton(self.tr("Copy"))
        copy_btn.clicked.connect(self._copy_fingerprint)
        identity_layout.addRow("", copy_btn)

        layout.addWidget(identity_group)

        # Protocol group
        protocol_group = QGroupBox(self.tr("Protocol"))
        protocol_layout = QFormLayout(protocol_group)

        self.protocol_version_label = QLabel("2")
        protocol_layout.addRow(self.tr("Protocol version:"), self.protocol_version_label)

        layout.addWidget(protocol_group)

        # Trusted peers note
        note = QLabel(
            self.tr(
                "Note: Peer trust is established on first connection (TOFU).\n"
                "Use the Peer Manager to view and manage trusted peers."
            )
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
        sync_group = QGroupBox(self.tr("Synchronization Options"))
        sync_layout = QVBoxLayout(sync_group)

        info = QLabel(
            self.tr(
                "Synchronization uses Last-Write-Wins (LWW) merge strategy.\n"
                "Items are identified by UUID, allowing conflict-free adds.\n"
                "Deleted items are marked as tombstones and cleaned up after 7 days."
            )
        )
        info.setWordWrap(True)
        sync_layout.addWidget(info)

        layout.addWidget(sync_group)

        # Auto-sync group
        auto_group = QGroupBox(self.tr("Automatic Sync"))
        auto_layout = QFormLayout(auto_group)

        push_label = QLabel(
            self.tr(
                "Automatically push local changes to online trusted peers\n"
                "after a quiet period with no further edits."
            )
        )
        push_label.setWordWrap(True)
        push_label.setStyleSheet("color: gray; font-style: italic;")
        auto_layout.addRow(push_label)

        self.auto_sync_delay_spin = QSpinBox()
        self.auto_sync_delay_spin.setRange(0, 60)
        self.auto_sync_delay_spin.setSuffix(self.tr(" seconds"))
        self.auto_sync_delay_spin.setSpecialValueText(self.tr("Disabled"))
        auto_layout.addRow(self.tr("Auto-push delay:"), self.auto_sync_delay_spin)

        interval_label = QLabel(
            self.tr(
                "Periodically perform a full bidirectional sync (pull + push)\n"
                "with all online trusted peers."
            )
        )
        interval_label.setWordWrap(True)
        interval_label.setStyleSheet("color: gray; font-style: italic;")
        auto_layout.addRow(interval_label)

        self.auto_sync_interval_spin = QSpinBox()
        self.auto_sync_interval_spin.setRange(0, 120)
        self.auto_sync_interval_spin.setSuffix(self.tr(" minutes"))
        self.auto_sync_interval_spin.setSpecialValueText(self.tr("Disabled"))
        auto_layout.addRow(self.tr("Periodic sync interval:"), self.auto_sync_interval_spin)

        layout.addWidget(auto_group)
        layout.addStretch()

        return widget

    def _create_appearance_tab(self) -> QWidget:
        """Create the Appearance settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Theme group
        theme_group = QGroupBox(self.tr("Theme"))
        theme_layout = QFormLayout(theme_group)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem(self.tr("System (follow OS)"), "system")
        self.theme_combo.addItem(self.tr("Light"), "light")
        self.theme_combo.addItem(self.tr("Dark"), "dark")
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_layout.addRow(self.tr("Theme:"), self.theme_combo)

        layout.addWidget(theme_group)

        # Font group
        font_group = QGroupBox(self.tr("Font"))
        font_layout = QFormLayout(font_group)

        self.font_combo = QComboBox()
        self.font_combo.addItem(self.tr("Noto Sans (Bundled)"), "bundled")
        self.font_combo.addItem(self.tr("System Default"), "system")
        self.font_combo.addItem(self.tr("Custom..."), "custom")
        self.font_combo.currentIndexChanged.connect(self._on_font_changed)
        font_layout.addRow(self.tr("Font:"), self.font_combo)

        self._custom_font_family = ""

        layout.addWidget(font_group)

        # Time display group
        time_group = QGroupBox(self.tr("Time Display"))
        time_layout = QFormLayout(time_group)

        self.time_format_combo = QComboBox()
        self.time_format_combo.addItem(self.tr("System default"), "system")
        self.time_format_combo.addItem(self.tr("12-hour (2:30 PM)"), "12h")
        self.time_format_combo.addItem(self.tr("24-hour (14:30)"), "24h")
        time_layout.addRow(self.tr("Time format:"), self.time_format_combo)

        layout.addWidget(time_group)

        # Behavior group
        behavior_group = QGroupBox(self.tr("Behavior"))
        behavior_layout = QFormLayout(behavior_group)
        self.close_to_tray_check = QCheckBox(self.tr("Minimize to system tray when closed"))
        behavior_layout.addRow(self.close_to_tray_check)
        layout.addWidget(behavior_group)

        # Preview note
        note = QLabel(self.tr("Theme changes are applied immediately."))
        note.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(note)

        layout.addStretch()

        return widget

    def _create_pomodoro_tab(self) -> QWidget:
        """Create the Focus Timer settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox(self.tr("Focus Timer"))
        form = QFormLayout(group)

        self.work_duration_spin = QSpinBox()
        self.work_duration_spin.setRange(1, 120)
        self.work_duration_spin.setSuffix(self.tr(" minutes"))
        form.addRow(self.tr("Work duration:"), self.work_duration_spin)

        self.break_duration_spin = QSpinBox()
        self.break_duration_spin.setRange(1, 30)
        self.break_duration_spin.setSuffix(self.tr(" minutes"))
        form.addRow(self.tr("Break duration:"), self.break_duration_spin)

        self.long_break_spin = QSpinBox()
        self.long_break_spin.setRange(5, 60)
        self.long_break_spin.setSuffix(self.tr(" minutes"))
        form.addRow(self.tr("Long break:"), self.long_break_spin)

        self.sessions_spin = QSpinBox()
        self.sessions_spin.setRange(2, 10)
        form.addRow(self.tr("Sessions before long break:"), self.sessions_spin)

        self.auto_break_check = QCheckBox(self.tr("Auto-start break after work session"))
        form.addRow("", self.auto_break_check)

        layout.addWidget(group)

        # Sound notifications group
        sound_group = QGroupBox(self.tr("Sound Notifications"))
        sound_form = QFormLayout(sound_group)

        self.sound_enabled_check = QCheckBox(self.tr("Enable sound notifications"))
        sound_form.addRow("", self.sound_enabled_check)

        volume_layout = QHBoxLayout()
        self.sound_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.sound_volume_slider.setRange(0, 100)
        self.sound_volume_label = QLabel("50%")
        self.sound_volume_label.setFixedWidth(40)
        volume_layout.addWidget(self.sound_volume_slider)
        volume_layout.addWidget(self.sound_volume_label)
        sound_form.addRow(self.tr("Volume:"), volume_layout)

        self.sound_enabled_check.stateChanged.connect(
            lambda state: self.sound_volume_slider.setEnabled(bool(state))
        )
        self.sound_volume_slider.valueChanged.connect(
            lambda val: self.sound_volume_label.setText(f"{val}%")
        )

        layout.addWidget(sound_group)

        # Daily goal group
        goal_group = QGroupBox(self.tr("Daily Goal"))
        goal_form = QFormLayout(goal_group)

        self.daily_goal_spin = QSpinBox()
        self.daily_goal_spin.setRange(0, 24)
        self.daily_goal_spin.setSuffix(self.tr(" sessions"))
        self.daily_goal_spin.setSpecialValueText(self.tr("Disabled"))
        goal_form.addRow(self.tr("Daily target:"), self.daily_goal_spin)

        self.milestone_check = QCheckBox(self.tr("Show milestone celebrations"))
        goal_form.addRow("", self.milestone_check)

        layout.addWidget(goal_group)

        # Stopwatch group
        sw_group = QGroupBox(self.tr("Stopwatch"))
        sw_form = QFormLayout(sw_group)

        self.sw_min_session_spin = QSpinBox()
        self.sw_min_session_spin.setRange(0, 300)
        self.sw_min_session_spin.setSingleStep(10)
        self.sw_min_session_spin.setSuffix(self.tr(" seconds"))
        self.sw_min_session_spin.setSpecialValueText(self.tr("Record all"))
        self.sw_min_session_spin.setToolTip(
            self.tr("Sessions shorter than this are discarded (0 = record everything)")
        )
        sw_form.addRow(self.tr("Minimum session:"), self.sw_min_session_spin)

        self.sw_idle_timeout_spin = QSpinBox()
        self.sw_idle_timeout_spin.setRange(0, 120)
        self.sw_idle_timeout_spin.setSingleStep(5)
        self.sw_idle_timeout_spin.setSuffix(self.tr(" minutes"))
        self.sw_idle_timeout_spin.setSpecialValueText(self.tr("Disabled"))
        self.sw_idle_timeout_spin.setToolTip(
            self.tr("Auto-pause stopwatch after no keyboard/mouse activity (0 = disabled)")
        )
        sw_form.addRow(self.tr("Auto-pause after idle:"), self.sw_idle_timeout_spin)

        self.sw_status_bar_check = QCheckBox(self.tr("Show elapsed time in status bar"))
        sw_form.addRow("", self.sw_status_bar_check)

        self.sw_sound_check = QCheckBox(self.tr("Play sound when session is recorded"))
        sw_form.addRow("", self.sw_sound_check)

        layout.addWidget(sw_group)
        layout.addStretch()

        return widget

    def _create_web_tab(self) -> QWidget:
        """Create the Web UI settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox(self.tr("Web Server"))
        form = QFormLayout(group)

        self.web_enabled_check = QCheckBox(self.tr("Enable Web UI"))
        form.addRow("", self.web_enabled_check)

        self.web_port_spin = QSpinBox()
        self.web_port_spin.setRange(1024, 65535)
        form.addRow(self.tr("Port:"), self.web_port_spin)

        self.web_bind_combo = QComboBox()
        self.web_bind_combo.addItem(self.tr("All interfaces (0.0.0.0)"), "0.0.0.0")
        self.web_bind_combo.addItem(self.tr("Localhost only (127.0.0.1)"), "127.0.0.1")
        form.addRow(self.tr("Bind:"), self.web_bind_combo)

        # TLS is always on — no user toggle (security requirement)
        tls_label = QLabel(self.tr("\U0001f512 All connections are encrypted (TLS)"))
        tls_label.setStyleSheet("color: palette(highlight); font-size: 11px;")
        form.addRow("", tls_label)

        # Pairing PIN display
        self.web_pin_label = QLabel("------")
        self.web_pin_label.setStyleSheet(
            "font-size: 28px; font-weight: bold; font-family: monospace;"
            " letter-spacing: 6px; padding: 8px; color: palette(highlight);"
        )
        self.web_pin_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form.addRow(self.tr("Pairing PIN:"), self.web_pin_label)

        self.web_pin_hint = QLabel(self.tr("Enter this PIN on your phone to connect"))
        self.web_pin_hint.setStyleSheet("font-size: 11px; color: palette(mid);")
        form.addRow("", self.web_pin_hint)

        # Device count indicator
        self.web_device_count_label = QLabel(self.tr("0 devices paired"))
        self.web_device_count_label.setStyleSheet("font-size: 12px;")
        form.addRow(self.tr("Devices:"), self.web_device_count_label)

        self.web_revoke_btn = QPushButton(self.tr("Disconnect All Devices"))
        self.web_revoke_btn.setStyleSheet("color: #c0392b;")
        self.web_revoke_btn.clicked.connect(self._revoke_web_token)
        form.addRow("", self.web_revoke_btn)

        # CalDAV credentials
        caldav_group = QGroupBox(self.tr("CalDAV (Calendar Sync)"))
        caldav_form = QFormLayout(caldav_group)
        caldav_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.caldav_url_label = QLabel("")
        self.caldav_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.caldav_url_label.setStyleSheet("font-size: 11px;")
        caldav_form.addRow(self.tr("URL:"), self.caldav_url_label)

        self.caldav_user_label = QLabel("pytodo")
        self.caldav_user_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        caldav_form.addRow(self.tr("Username:"), self.caldav_user_label)

        caldav_pw_row = QHBoxLayout()
        self.caldav_password_label = QLineEdit()
        self.caldav_password_label.setReadOnly(True)
        self.caldav_password_label.setEchoMode(QLineEdit.EchoMode.Password)
        caldav_pw_row.addWidget(self.caldav_password_label)
        self.caldav_show_btn = QPushButton(self.tr("Show"))
        self.caldav_show_btn.setFixedWidth(50)
        self.caldav_show_btn.clicked.connect(self._toggle_caldav_visibility)
        caldav_pw_row.addWidget(self.caldav_show_btn)
        self.caldav_copy_btn = QPushButton(self.tr("Copy"))
        self.caldav_copy_btn.setFixedWidth(50)
        self.caldav_copy_btn.clicked.connect(self._copy_caldav_password)
        caldav_pw_row.addWidget(self.caldav_copy_btn)
        caldav_form.addRow(self.tr("Password:"), caldav_pw_row)

        # Certificate section
        cert_row = QHBoxLayout()
        self.caldav_cert_btn = QPushButton(self.tr("Open CA Certificate"))
        self.caldav_cert_btn.setToolTip(
            self.tr("Open the certificate file for import into your CalDAV client")
        )
        self.caldav_cert_btn.clicked.connect(self._open_caldav_cert)
        cert_row.addWidget(self.caldav_cert_btn)
        cert_row.addStretch()
        caldav_form.addRow(self.tr("Certificate:"), cert_row)

        caldav_hint = QLabel(
            self.tr(
                "CalDAV clients need to trust the certificate before connecting.\n"
                "Thunderbird: Settings \u2192 Privacy & Security \u2192 Certificates"
                " \u2192 View Certificates \u2192 Authorities \u2192 Import\n"
                "DAVx5: accepts self-signed certs during setup"
            )
        )
        caldav_hint.setWordWrap(True)
        caldav_hint.setStyleSheet("font-size: 10px; color: palette(mid);")
        caldav_form.addRow("", caldav_hint)

        layout.addWidget(caldav_group)

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

        # View mode
        view_mode = config.database.view_mode
        for i in range(self._view_mode_combo.count()):
            if self._view_mode_combo.itemData(i) == view_mode:
                self._view_mode_combo.setCurrentIndex(i)
                break

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

        # Font
        font_setting = config.appearance.font
        self.font_combo.blockSignals(True)
        if font_setting == "bundled":
            self.font_combo.setCurrentIndex(0)
        elif font_setting == "system":
            self.font_combo.setCurrentIndex(1)
        else:
            # Custom font family — update the "Custom..." item
            self._custom_font_family = font_setting
            self.font_combo.setItemText(2, f"Custom: {font_setting}")
            self.font_combo.setItemData(2, font_setting)
            self.font_combo.setCurrentIndex(2)
        self.font_combo.blockSignals(False)

        # Behavior
        self.close_to_tray_check.setChecked(config.appearance.close_to_tray)

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

        # Stopwatch
        self.sw_min_session_spin.setValue(config.stopwatch.minimum_session)
        self.sw_idle_timeout_spin.setValue(config.stopwatch.idle_timeout)
        self.sw_status_bar_check.setChecked(config.stopwatch.show_in_status_bar)
        self.sw_sound_check.setChecked(config.stopwatch.sound_on_stop)

        # Web
        self.web_enabled_check.setChecked(config.web.enabled)
        self.web_port_spin.setValue(config.web.port)
        # TLS always on — no toggle to load
        bind_idx = self.web_bind_combo.findData(config.web.bind_address)
        if bind_idx >= 0:
            self.web_bind_combo.setCurrentIndex(bind_idx)
        # Show device count and pairing PIN from running web server
        parent = self.parent()
        web_server = getattr(parent, "_web_server", None) if parent else None
        if web_server is not None:
            devices = web_server.get_paired_devices()
            count = len(devices)
            self.web_device_count_label.setText(f"{count} device{'s' if count != 1 else ''} paired")
            self.web_pin_label.setText(web_server.pairing_pin)
            # CalDAV credentials
            from ..dialogs.web_connect import _get_local_hostname

            hostname = _get_local_hostname()
            port = config.web.port
            if hostname:
                self.caldav_url_label.setText(f"https://{hostname}:{port}/caldav/")
            else:
                from ..dialogs.web_connect import _get_lan_ip

                ip = _get_lan_ip()
                if ip:
                    self.caldav_url_label.setText(f"https://{ip}:{port}/caldav/")
            self.caldav_password_label.setText(web_server.caldav_password)
        else:
            self.web_device_count_label.setText(self.tr("Server not running"))
            self.web_pin_label.setText(self.tr("Start web server to generate"))
            self.web_pin_label.setStyleSheet("font-size: 12px; color: palette(mid); padding: 8px;")
            self.caldav_url_label.setText(self.tr("Start web server first"))
            self.caldav_password_label.setText("")

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
        config.database.view_mode = self._view_mode_combo.currentData()

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
        config.appearance.font = self.font_combo.currentData()
        config.appearance.close_to_tray = self.close_to_tray_check.isChecked()

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

        # Stopwatch
        config.stopwatch.minimum_session = self.sw_min_session_spin.value()
        config.stopwatch.idle_timeout = self.sw_idle_timeout_spin.value()
        config.stopwatch.show_in_status_bar = self.sw_status_bar_check.isChecked()
        config.stopwatch.sound_on_stop = self.sw_sound_check.isChecked()

        # Web
        config.web.enabled = self.web_enabled_check.isChecked()
        config.web.port = self.web_port_spin.value()
        # TLS always on — no toggle to save
        config.web.bind_address = self.web_bind_combo.currentData() or "0.0.0.0"

        # Save to file
        if not self._config_manager.save():
            QMessageBox.warning(self, self.tr("Error"), self.tr("Failed to save settings."))
            return False

        # Apply theme if changed
        if old_theme != new_theme:
            apply_current_theme()

        logger.log.info("Settings saved")
        return True

    def _open_caldav_cert(self) -> None:
        """Open the CA certificate file for the user to import."""
        parent = self.parent()
        web_server = getattr(parent, "_web_server", None) if parent else None
        if web_server is None or web_server.ca_cert_path is None:
            QMessageBox.information(
                self, self.tr("Certificate"), self.tr("Web server is not running.")
            )
            return
        import subprocess
        import sys

        cert_path = str(web_server.ca_cert_path)
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", cert_path])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", cert_path])
        else:
            subprocess.Popen(["xdg-open", str(web_server.ca_cert_path.parent)])

    def _toggle_caldav_visibility(self) -> None:
        """Toggle CalDAV password visibility."""
        if self.caldav_password_label.echoMode() == QLineEdit.EchoMode.Password:
            self.caldav_password_label.setEchoMode(QLineEdit.EchoMode.Normal)
            self.caldav_show_btn.setText(self.tr("Hide"))
        else:
            self.caldav_password_label.setEchoMode(QLineEdit.EchoMode.Password)
            self.caldav_show_btn.setText(self.tr("Show"))

    def _copy_caldav_password(self) -> None:
        """Copy CalDAV password to clipboard."""
        from PyQt6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.caldav_password_label.text())
            self.caldav_copy_btn.setText("\u2713")
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(2000, lambda: self.caldav_copy_btn.setText(self.tr("Copy")))

    def _copy_fingerprint(self) -> None:
        """Copy fingerprint to clipboard."""
        from PyQt6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.fingerprint_edit.text())
            QMessageBox.information(
                self, self.tr("Copied"), self.tr("Fingerprint copied to clipboard.")
            )

    def _on_accept(self) -> None:
        """Handle OK button."""
        if self._save_settings():
            self.accept()

    def _on_apply(self) -> None:
        """Handle Apply button."""
        self._save_settings()

    def _revoke_web_token(self) -> None:
        """Revoke the web access token, disconnecting all devices."""
        parent = self.parent()
        web_server = getattr(parent, "_web_server", None) if parent else None
        if web_server is None:
            QMessageBox.information(self, self.tr("Info"), self.tr("Web server is not running."))
            return
        if (
            QMessageBox.question(
                self,
                self.tr("Disconnect All Devices"),
                self.tr(
                    "This will immediately disconnect all phones and tablets.\n"
                    "They will need to re-pair using a new PIN.\n\nContinue?"
                ),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        count = web_server.revoke_all_devices()
        self.web_device_count_label.setText(self.tr("0 devices paired"))
        self.web_pin_label.setText(web_server.pairing_pin)
        # Update status bar PIN
        main_window = parent
        if hasattr(main_window, "status_bar_widget"):
            main_window.status_bar_widget.set_web_status(
                True, port=self._config.web.port, pin=web_server.pairing_pin
            )
        logger.log.info("Revoked %d device(s) from settings", count)

    def _on_font_changed(self, index: int) -> None:
        """Handle font combo box change."""
        value = self.font_combo.itemData(index)
        if value == "custom":
            font, ok = QFontDialog.getFont(self)
            if ok:
                family = font.family()
                self._custom_font_family = family
                # Replace the "Custom..." item text with the chosen family
                self.font_combo.setItemText(index, f"Custom: {family}")
                self.font_combo.setItemData(index, family)
            else:
                # User cancelled — revert to previous selection
                self.font_combo.blockSignals(True)
                # Find the current config value
                current = self._config.appearance.font
                for i in range(self.font_combo.count()):
                    if self.font_combo.itemData(i) == current:
                        self.font_combo.setCurrentIndex(i)
                        break
                self.font_combo.blockSignals(False)

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
