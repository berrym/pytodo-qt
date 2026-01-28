"""settings.py

Unified settings dialog with tabbed interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.config import get_config, get_config_manager
from ...core.logger import Logger
from ...crypto import get_or_create_identity
from ..styles.themes import apply_current_theme

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

        self._config = get_config()
        self._config_manager = get_config_manager()

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

        # Button box
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        layout.addWidget(button_box)

    def _create_general_tab(self) -> QWidget:
        """Create the General settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Database settings group
        db_group = QGroupBox("Database")
        db_layout = QFormLayout(db_group)

        self.sort_key_combo = QComboBox()
        self.sort_key_combo.addItems(["Priority", "Reminder"])
        db_layout.addRow("Sort by:", self.sort_key_combo)

        self.reverse_sort_check = QCheckBox("Reverse sort order")
        db_layout.addRow("", self.reverse_sort_check)

        layout.addWidget(db_group)
        layout.addStretch()

        return widget

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
        self.fingerprint_edit.setStyleSheet("font-family: monospace;")
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
        theme_layout.addRow("Theme:", self.theme_combo)

        layout.addWidget(theme_group)

        # Preview note
        note = QLabel("Theme changes take effect immediately.")
        note.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(note)

        layout.addStretch()

        return widget

    def _load_settings(self) -> None:
        """Load current settings into the UI."""
        config = self._config

        # General
        sort_key = config.database.sort_key
        self.sort_key_combo.setCurrentIndex(0 if sort_key == "priority" else 1)
        self.reverse_sort_check.setChecked(config.database.reverse_sort)

        # Network
        self.server_enabled_check.setChecked(config.server.enabled)
        self.server_address_edit.setText(config.server.address)
        self.server_port_spin.setValue(config.server.port)
        self.allow_pull_check.setChecked(config.server.allow_pull)
        self.allow_push_check.setChecked(config.server.allow_push)

        # Discovery
        self.discovery_enabled_check.setChecked(config.discovery.enabled)
        self.service_name_edit.setText(config.discovery.service_name)

        # Appearance
        theme = config.appearance.theme
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme:
                self.theme_combo.setCurrentIndex(i)
                break

    def _save_settings(self) -> bool:
        """Save settings from UI to config."""
        config = self._config

        # General
        config.database.sort_key = (
            "priority" if self.sort_key_combo.currentIndex() == 0 else "reminder"
        )
        config.database.reverse_sort = self.reverse_sort_check.isChecked()

        # Network
        config.server.enabled = self.server_enabled_check.isChecked()
        config.server.address = self.server_address_edit.text() or "0.0.0.0"
        config.server.port = self.server_port_spin.value()
        config.server.allow_pull = self.allow_pull_check.isChecked()
        config.server.allow_push = self.allow_push_check.isChecked()

        # Discovery
        config.discovery.enabled = self.discovery_enabled_check.isChecked()
        config.discovery.service_name = self.service_name_edit.text()

        # Appearance
        old_theme = config.appearance.theme
        new_theme = self.theme_combo.currentData()
        config.appearance.theme = new_theme

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
