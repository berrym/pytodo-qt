"""list_sync_settings.py

Dialog for configuring list sync rules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.database import DatabaseStorage
from ...core.logger import Logger
from ...core.models import TodoList

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class ListSyncSettingsDialog(QDialog):
    """Dialog for configuring which groups a list syncs to."""

    def __init__(
        self,
        parent=None,
        todo_list: TodoList | None = None,
        storage: DatabaseStorage | None = None,
    ):
        super().__init__(parent)
        self._list = todo_list
        self._storage = storage
        self._group_checkboxes: list[QCheckBox] = []

        if todo_list:
            self.setWindowTitle(f"Sync Settings: {todo_list.name}")
        else:
            self.setWindowTitle("Sync Settings")

        self.setMinimumWidth(400)
        self.setMinimumHeight(350)

        self._setup_ui()
        self._load_current_settings()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Description
        desc = QLabel(
            "Configure how this list syncs with other devices.\n"
            "Lists can sync to all devices, selected groups only, or be kept private."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Sync mode group
        mode_group = QGroupBox("Sync this list to:")
        mode_layout = QVBoxLayout(mode_group)

        self._mode_button_group = QButtonGroup(self)

        # All devices option
        self._all_devices_radio = QRadioButton("All devices (default)")
        self._all_devices_radio.setToolTip(
            "Sync to all non-blocked devices regardless of group membership"
        )
        self._mode_button_group.addButton(self._all_devices_radio, 0)
        mode_layout.addWidget(self._all_devices_radio)

        # Selected groups option
        self._selected_groups_radio = QRadioButton("Selected groups only:")
        self._selected_groups_radio.setToolTip("Only sync to devices in the selected groups")
        self._mode_button_group.addButton(self._selected_groups_radio, 1)
        self._selected_groups_radio.toggled.connect(self._on_mode_changed)
        mode_layout.addWidget(self._selected_groups_radio)

        # Groups list (scrollable)
        self._groups_scroll = QScrollArea()
        self._groups_scroll.setWidgetResizable(True)
        self._groups_scroll.setMaximumHeight(150)
        self._groups_widget = QWidget()
        self._groups_layout = QVBoxLayout(self._groups_widget)
        self._groups_layout.setContentsMargins(20, 5, 5, 5)

        self._populate_groups()

        self._groups_scroll.setWidget(self._groups_widget)
        mode_layout.addWidget(self._groups_scroll)

        # Private option
        self._private_radio = QRadioButton("Private (never sync)")
        self._private_radio.setToolTip("Keep this list local only - it will never be synced")
        self._mode_button_group.addButton(self._private_radio, 2)
        mode_layout.addWidget(self._private_radio)

        layout.addWidget(mode_group)

        # Preview
        self._preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(self._preview_group)
        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)
        preview_layout.addWidget(self._preview_label)
        layout.addWidget(self._preview_group)

        # Connect signals for preview update
        self._mode_button_group.buttonToggled.connect(self._update_preview)

        # Button box
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Default state
        self._all_devices_radio.setChecked(True)
        self._groups_scroll.setEnabled(False)

    def _populate_groups(self) -> None:
        """Populate the groups checkboxes."""
        if self._storage is None:
            no_groups = QLabel("(No storage available)")
            self._groups_layout.addWidget(no_groups)
            return

        groups = self._storage.get_all_sync_groups()

        if not groups:
            no_groups = QLabel("(No sync groups created)")
            no_groups.setStyleSheet("color: gray; font-style: italic;")
            self._groups_layout.addWidget(no_groups)
            return

        for group in groups:
            # Get device count for this group
            devices = self._storage.get_devices_in_group(group.id)
            cb = QCheckBox(
                f"{group.name} ({len(devices)} device{'s' if len(devices) != 1 else ''})"
            )
            cb.setProperty("group_id", group.id)
            cb.toggled.connect(self._update_preview)
            self._group_checkboxes.append(cb)
            self._groups_layout.addWidget(cb)

        self._groups_layout.addStretch()

    def _load_current_settings(self) -> None:
        """Load current sync settings for the list."""
        if self._list is None or self._storage is None:
            return

        # Check if list is private
        if self._list.private:
            self._private_radio.setChecked(True)
            return

        # Get current sync rules
        rules = self._storage.get_sync_rules_for_list(self._list.id)

        if not rules:
            # No rules = sync everywhere
            self._all_devices_radio.setChecked(True)
        else:
            # Has rules = selected groups only
            self._selected_groups_radio.setChecked(True)
            rule_group_ids = {rule.group_id for rule in rules}

            for cb in self._group_checkboxes:
                group_id = cb.property("group_id")
                if group_id in rule_group_ids:
                    cb.setChecked(True)

    def _on_mode_changed(self, checked: bool) -> None:
        """Handle sync mode change."""
        # Enable groups list only when "Selected groups" is selected
        self._groups_scroll.setEnabled(self._selected_groups_radio.isChecked())

    def _update_preview(self) -> None:
        """Update the preview text."""
        if self._storage is None:
            self._preview_label.setText("(Storage not available)")
            return

        if self._private_radio.isChecked():
            self._preview_label.setText(
                '<span style="color: gray;">This list will never sync with other devices.</span>'
            )
            return

        if self._all_devices_radio.isChecked():
            # Count non-blocked devices
            devices = self._storage.get_all_devices(include_blocked=False)
            self._preview_label.setText(
                f"Will sync to <b>all {len(devices)} device{'s' if len(devices) != 1 else ''}</b> "
                f"(except blocked devices)."
            )
            return

        # Selected groups
        selected_device_ids: set[UUID] = set()
        selected_group_names: list[str] = []

        for cb in self._group_checkboxes:
            if cb.isChecked():
                group_id = cb.property("group_id")
                group = self._storage.get_sync_group(group_id)
                if group:
                    selected_group_names.append(group.name)
                    devices = self._storage.get_devices_in_group(group_id)
                    for d in devices:
                        selected_device_ids.add(d.id)

        if not selected_group_names:
            self._preview_label.setText(
                '<span style="color: orange;">No groups selected. '
                "List will not sync to any devices.</span>"
            )
        else:
            groups_text = ", ".join(selected_group_names)
            self._preview_label.setText(
                f"Will sync to <b>{len(selected_device_ids)} device{'s' if len(selected_device_ids) != 1 else ''}</b> "
                f"in: {groups_text}"
            )

    def _on_save(self) -> None:
        """Save the sync settings."""
        if self._list is None or self._storage is None:
            self.reject()
            return

        # Handle private setting
        if self._private_radio.isChecked():
            if not self._list.private:
                self._list.private = True
                self._list.mark_updated()
            # Clear any existing rules
            self._storage.clear_list_sync_rules(self._list.id)
            logger.log.info("List '%s' set to private", self._list.name)
            self.accept()
            return

        # If was private, make it not private
        if self._list.private:
            self._list.private = False
            self._list.mark_updated()

        # Handle sync rules
        self._storage.clear_list_sync_rules(self._list.id)

        if self._selected_groups_radio.isChecked():
            # Add rules for selected groups
            for cb in self._group_checkboxes:
                if cb.isChecked():
                    group_id = cb.property("group_id")
                    self._storage.add_list_sync_rule(self._list.id, group_id)
                    logger.log.debug(
                        "Added sync rule: list '%s' -> group %s",
                        self._list.name,
                        group_id,
                    )
            logger.log.info(
                "List '%s' set to sync with selected groups",
                self._list.name,
            )
        else:
            # All devices - no rules needed (default behavior)
            logger.log.info("List '%s' set to sync with all devices", self._list.name)

        self.accept()

    def get_updated_list(self) -> TodoList | None:
        """Get the potentially updated list (for private flag changes)."""
        return self._list
