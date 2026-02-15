"""device_manager.py

Dialog for managing known devices and sync groups.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast
from uuid import UUID

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from ...core.database import DatabaseStorage
from ...core.logger import Logger
from ...core.models import Database, Device, create_device, create_sync_group
from ...core.offline_queue import OfflineQueue
from ...net.client import AsyncClient
from ...net.discovery import DiscoveredPeer, get_discovery_service
from ..styles.themes import make_font

if TYPE_CHECKING:
    pass


logger = Logger(__name__)

# Sentinel for the "All Devices" virtual group row
_ALL_DEVICES_SENTINEL = "__all_devices__"


class DeviceManagerDialog(QDialog):
    """Dialog for managing known devices and sync groups."""

    # Signals
    sync_data_received = pyqtSignal(bytes)
    device_updated = pyqtSignal()

    def __init__(
        self,
        parent=None,
        database: Database | None = None,
        storage: DatabaseStorage | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Device & Sync Manager")
        self.setMinimumWidth(700)
        self.setMinimumHeight(500)

        self._discovery = get_discovery_service()
        self._client = AsyncClient(self)
        self._database = database
        self._storage = storage
        self._offline_queue = OfflineQueue(storage) if storage else None
        self._selected_device: Device | None = None
        self._selected_group_id = None

        self._setup_ui()
        self._refresh_all()

        # Auto-refresh timer for online status
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_online_status)
        self._refresh_timer.start(5000)

    # ------------------------------------------------------------------ #
    # UI Setup
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        """Set up the dialog UI with a tab-based layout."""
        layout = QVBoxLayout(self)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.addTab(self._create_devices_tab(), "Devices")
        self._tabs.addTab(self._create_groups_tab(), "Sync Groups")
        self._tabs.addTab(self._create_discovery_tab(), "Discovery")
        layout.addWidget(self._tabs)

        # Bottom bar — always visible
        bottom_btns = QHBoxLayout()

        self.sync_all_btn = QPushButton("Sync All Trusted")
        self.sync_all_btn.setToolTip("Sync with all online trusted devices")
        self.sync_all_btn.clicked.connect(self._on_sync_all)
        bottom_btns.addWidget(self.sync_all_btn)

        self.sync_group_menu_btn = QPushButton("Sync Group...")
        self.sync_group_menu_btn.setToolTip("Sync with all online devices in a group")
        self._sync_group_menu = QMenu(self)
        self.sync_group_menu_btn.setMenu(self._sync_group_menu)
        self._sync_group_menu.aboutToShow.connect(self._populate_sync_group_menu)
        bottom_btns.addWidget(self.sync_group_menu_btn)

        bottom_btns.addStretch()

        self.status_label = QLabel()
        bottom_btns.addWidget(self.status_label)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom_btns.addWidget(close_btn)

        layout.addLayout(bottom_btns)

    # ---- Tab 1: Devices ------------------------------------------------ #

    def _create_devices_tab(self) -> QWidget:
        """Create the Devices tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Device table
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(5)
        self.device_table.setHorizontalHeaderLabels(
            ["Name", "Status", "Trust", "Groups", "Pending"]
        )
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.device_table.setAlternatingRowColors(True)
        header = self.device_table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.device_table.itemSelectionChanged.connect(self._on_device_selected)
        layout.addWidget(self.device_table)

        # Action buttons — single row
        action_btns = QHBoxLayout()

        self.sync_btn = QPushButton("Sync Now")
        self.sync_btn.clicked.connect(self._on_sync)
        self.sync_btn.setEnabled(False)
        action_btns.addWidget(self.sync_btn)

        self.test_btn = QPushButton("Test")
        self.test_btn.clicked.connect(self._on_test_connection)
        self.test_btn.setEnabled(False)
        action_btns.addWidget(self.test_btn)

        self.queue_sync_btn = QPushButton("Queue Sync")
        self.queue_sync_btn.setToolTip("Queue sync for when device comes online")
        self.queue_sync_btn.clicked.connect(self._on_queue_sync)
        self.queue_sync_btn.setEnabled(False)
        action_btns.addWidget(self.queue_sync_btn)

        action_btns.addStretch()

        add_device_btn = QPushButton("Add Device...")
        add_device_btn.setToolTip("Add a discovered device")
        add_device_btn.clicked.connect(self._on_add_to_devices)
        action_btns.addWidget(add_device_btn)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._on_remove)
        self.remove_btn.setEnabled(False)
        action_btns.addWidget(self.remove_btn)

        layout.addLayout(action_btns)

        # Device details group (hidden until selection)
        self.device_group = QGroupBox("Device Details")
        self.device_group.setVisible(False)
        device_form = QFormLayout(self.device_group)

        # Name + Save
        name_widget = QWidget()
        name_layout = QHBoxLayout(name_widget)
        name_layout.setContentsMargins(0, 0, 0, 0)
        self.device_name_edit = QLineEdit()
        self.device_name_edit.setPlaceholderText("Device name")
        name_layout.addWidget(self.device_name_edit)
        self.rename_btn = QPushButton("Save")
        self.rename_btn.setMaximumWidth(60)
        self.rename_btn.clicked.connect(self._on_rename)
        name_layout.addWidget(self.rename_btn)
        device_form.addRow("Name:", name_widget)

        # Fingerprint
        self.device_fingerprint_label = QLabel()
        self.device_fingerprint_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.device_fingerprint_label.setWordWrap(True)
        self.device_fingerprint_label.setFont(make_font(mono=True))
        device_form.addRow("Fingerprint:", self.device_fingerprint_label)

        # Hostname (from discovery or last_address)
        self.device_hostname_label = QLabel()
        self.device_hostname_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        device_form.addRow("Hostname:", self.device_hostname_label)

        # Address
        self.device_address_label = QLabel()
        device_form.addRow("Address:", self.device_address_label)

        # Last Seen
        self.device_last_seen_label = QLabel()
        device_form.addRow("Last Seen:", self.device_last_seen_label)

        # Trust Level
        self.trust_combo = QComboBox()
        self.trust_combo.addItems(["Normal", "Trusted", "Blocked"])
        self.trust_combo.currentTextChanged.connect(self._on_trust_changed)
        device_form.addRow("Trust Level:", self.trust_combo)

        # Groups
        groups_widget = QWidget()
        groups_layout = QHBoxLayout(groups_widget)
        groups_layout.setContentsMargins(0, 0, 0, 0)
        self.device_groups_label = QLabel()
        groups_layout.addWidget(self.device_groups_label)
        self.edit_device_groups_btn = QPushButton("Edit...")
        self.edit_device_groups_btn.setMaximumWidth(60)
        self.edit_device_groups_btn.setToolTip("Edit group membership for this device")
        self.edit_device_groups_btn.clicked.connect(self._on_edit_device_groups)
        groups_layout.addWidget(self.edit_device_groups_btn)
        device_form.addRow("Groups:", groups_widget)

        # Pending
        pending_widget = QWidget()
        pending_layout = QHBoxLayout(pending_widget)
        pending_layout.setContentsMargins(0, 0, 0, 0)
        self.pending_sync_label = QLabel()
        pending_layout.addWidget(self.pending_sync_label)
        self.clear_queue_btn = QPushButton("Clear")
        self.clear_queue_btn.setMaximumWidth(60)
        self.clear_queue_btn.setToolTip("Clear pending syncs for this device")
        self.clear_queue_btn.clicked.connect(self._on_clear_queue)
        pending_layout.addWidget(self.clear_queue_btn)
        device_form.addRow("Pending:", pending_widget)

        # Security
        self.update_fp_btn = QPushButton("Update Fingerprint...")
        self.update_fp_btn.setToolTip("Update fingerprint if device key has changed")
        self.update_fp_btn.clicked.connect(self._on_update_fingerprint)
        device_form.addRow("Security:", self.update_fp_btn)

        layout.addWidget(self.device_group)

        # Empty state label
        self.devices_empty_label = QLabel(
            "No known devices yet.\n"
            "Devices are added automatically when you sync,\n"
            "or add discovered peers from the Discovery tab."
        )
        self.devices_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.devices_empty_label.setStyleSheet("color: gray; font-style: italic; padding: 20px;")
        layout.addWidget(self.devices_empty_label)

        return tab

    # ---- Tab 2: Sync Groups -------------------------------------------- #

    def _create_groups_tab(self) -> QWidget:
        """Create the Sync Groups tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Group table
        self.group_table = QTableWidget()
        self.group_table.setColumnCount(3)
        self.group_table.setHorizontalHeaderLabels(["Name", "Devices", "Online"])
        self.group_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.group_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.group_table.setAlternatingRowColors(True)
        header = self.group_table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.group_table.itemSelectionChanged.connect(self._on_group_selected)
        layout.addWidget(self.group_table)

        # Action buttons
        group_btns = QHBoxLayout()

        self.sync_group_btn = QPushButton("Sync Group")
        self.sync_group_btn.setToolTip("Sync with all online devices in this group")
        self.sync_group_btn.clicked.connect(self._on_sync_group)
        self.sync_group_btn.setEnabled(False)
        group_btns.addWidget(self.sync_group_btn)

        self.edit_group_members_btn = QPushButton("Edit Members...")
        self.edit_group_members_btn.setToolTip("Add or remove devices from this group")
        self.edit_group_members_btn.clicked.connect(self._on_edit_group_members)
        self.edit_group_members_btn.setEnabled(False)
        group_btns.addWidget(self.edit_group_members_btn)

        group_btns.addStretch()

        add_group_btn = QPushButton("Add Group...")
        add_group_btn.setToolTip("Create a new sync group")
        add_group_btn.clicked.connect(self._on_add_group)
        group_btns.addWidget(add_group_btn)

        self.rename_group_btn = QPushButton("Rename")
        self.rename_group_btn.clicked.connect(self._on_rename_group)
        self.rename_group_btn.setEnabled(False)
        group_btns.addWidget(self.rename_group_btn)

        self.delete_group_btn = QPushButton("Delete")
        self.delete_group_btn.clicked.connect(self._on_delete_group)
        self.delete_group_btn.setEnabled(False)
        group_btns.addWidget(self.delete_group_btn)

        layout.addLayout(group_btns)

        # Group Members panel (hidden until selection)
        self.group_details = QGroupBox("Group Members")
        self.group_details.setVisible(False)
        gd_layout = QVBoxLayout(self.group_details)

        self.group_description_label = QLabel()
        self.group_description_label.setWordWrap(True)
        gd_layout.addWidget(self.group_description_label)

        self.group_members_table = QTableWidget()
        self.group_members_table.setColumnCount(3)
        self.group_members_table.setHorizontalHeaderLabels(["Device", "Status", "Trust"])
        self.group_members_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.group_members_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.group_members_table.setMaximumHeight(180)
        gh = self.group_members_table.horizontalHeader()
        assert gh is not None
        gh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        gh.setStretchLastSection(True)
        gd_layout.addWidget(self.group_members_table)

        layout.addWidget(self.group_details)

        # Empty state label (only when no user groups exist)
        self.groups_empty_label = QLabel(
            "Sync groups let you organize devices and control\n"
            "which lists sync to which devices.\n"
            "The 'All Devices' group represents the default sync policy."
        )
        self.groups_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.groups_empty_label.setStyleSheet("color: gray; font-style: italic; padding: 20px;")
        layout.addWidget(self.groups_empty_label)

        return tab

    # ---- Tab 3: Discovery ----------------------------------------------- #

    def _create_discovery_tab(self) -> QWidget:
        """Create the Discovery tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Description
        desc = QLabel(
            "Devices discovered on your local network.\n"
            "Add them as known devices to manage sync and trust."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Discovered Peers group
        peers_group = QGroupBox("Discovered Peers")
        peers_layout = QVBoxLayout(peers_group)

        self.peer_table = QTableWidget()
        self.peer_table.setColumnCount(5)
        self.peer_table.setHorizontalHeaderLabels(
            ["Name", "Address", "Port", "Fingerprint", "Known"]
        )
        self.peer_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.peer_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        ph = self.peer_table.horizontalHeader()
        assert ph is not None
        ph.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        ph.setStretchLastSection(True)
        self.peer_table.itemSelectionChanged.connect(self._on_peer_selected)
        peers_layout.addWidget(self.peer_table)

        peer_btns = QHBoxLayout()
        self.add_to_devices_btn = QPushButton("Add to Devices")
        self.add_to_devices_btn.clicked.connect(self._on_add_to_devices)
        self.add_to_devices_btn.setEnabled(False)
        peer_btns.addWidget(self.add_to_devices_btn)

        self.peer_ping_btn = QPushButton("Ping")
        self.peer_ping_btn.clicked.connect(self._on_ping)
        self.peer_ping_btn.setEnabled(False)
        peer_btns.addWidget(self.peer_ping_btn)

        self.peer_sync_btn = QPushButton("Sync")
        self.peer_sync_btn.clicked.connect(self._on_peer_sync)
        self.peer_sync_btn.setEnabled(False)
        peer_btns.addWidget(self.peer_sync_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_peers)
        peer_btns.addWidget(refresh_btn)

        peer_btns.addStretch()
        peers_layout.addLayout(peer_btns)

        layout.addWidget(peers_group)

        # Manual Connection group
        manual_group = QGroupBox("Manual Connection")
        manual_layout = QFormLayout(manual_group)

        self.manual_host_edit = QLineEdit()
        self.manual_host_edit.setPlaceholderText("hostname or IP address")
        manual_layout.addRow("Host:", self.manual_host_edit)

        self.manual_port_spin = QSpinBox()
        self.manual_port_spin.setRange(1024, 65535)
        self.manual_port_spin.setValue(5364)
        manual_layout.addRow("Port:", self.manual_port_spin)

        connect_btns = QHBoxLayout()
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self._on_manual_connect)
        connect_btns.addWidget(connect_btn)
        connect_btns.addStretch()
        manual_layout.addRow("", connect_btns)

        layout.addWidget(manual_group)

        # Discovery status
        self.discovery_status_label = QLabel()
        layout.addWidget(self.discovery_status_label)

        return tab

    # ------------------------------------------------------------------ #
    # Refresh methods
    # ------------------------------------------------------------------ #

    def _refresh_all(self) -> None:
        """Refresh all tabs."""
        self._refresh_devices()
        self._refresh_groups()
        self._refresh_peers()

    def _refresh_devices(self) -> None:
        """Refresh the device table."""
        self.device_table.setRowCount(0)

        if self._storage is None:
            self.devices_empty_label.setVisible(True)
            return

        devices = self._storage.get_all_devices(include_blocked=True)
        online_fingerprints = self._get_online_fingerprints()

        has_devices = len(devices) > 0
        self.devices_empty_label.setVisible(not has_devices)

        for device in devices:
            row = self.device_table.rowCount()
            self.device_table.insertRow(row)

            # Name
            name = device.name or f"Device {str(device.id)[:8]}"
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, device.id)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.device_table.setItem(row, 0, name_item)

            # Status
            is_online = device.fingerprint in online_fingerprints
            if device.trust_level == "blocked":
                status_item = QTableWidgetItem("Blocked")
                status_item.setForeground(QColor("gray"))
            elif is_online:
                status_item = QTableWidgetItem("Online")
                status_item.setForeground(QColor("green"))
            else:
                status_item = QTableWidgetItem("Offline")
                status_item.setForeground(QColor("gray"))
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.device_table.setItem(row, 1, status_item)

            # Trust
            trust_item = QTableWidgetItem(device.trust_level.capitalize())
            trust_item.setFlags(trust_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.device_table.setItem(row, 2, trust_item)

            # Groups
            groups = self._storage.get_groups_for_device(device.id) if self._storage else []
            groups_text = ", ".join(g.name for g in groups) if groups else "—"
            groups_item = QTableWidgetItem(groups_text)
            groups_item.setFlags(groups_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.device_table.setItem(row, 3, groups_item)

            # Pending
            pending_text = "—"
            if self._offline_queue:
                pending = self._offline_queue.get_pending_for_device(device.id)
                if pending:
                    pending_text = str(len(pending))
            pending_item = QTableWidgetItem(pending_text)
            if pending_text != "—":
                pending_item.setForeground(QColor("orange"))
            pending_item.setFlags(pending_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.device_table.setItem(row, 4, pending_item)

    def _refresh_groups(self) -> None:
        """Refresh the group table with 'All Devices' + user groups."""
        self.group_table.setRowCount(0)

        online_fps = self._get_online_fingerprints()

        # "All Devices" virtual row — always first
        all_devices = self._storage.get_all_devices(include_blocked=False) if self._storage else []
        all_online = sum(1 for d in all_devices if d.fingerprint in online_fps)

        self.group_table.insertRow(0)
        all_name_item = QTableWidgetItem("All Devices")
        all_name_item.setData(Qt.ItemDataRole.UserRole, _ALL_DEVICES_SENTINEL)
        italic_font = QFont()
        italic_font.setItalic(True)
        all_name_item.setFont(italic_font)
        all_name_item.setFlags(all_name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.group_table.setItem(0, 0, all_name_item)

        all_count_item = QTableWidgetItem(str(len(all_devices)))
        all_count_item.setFont(italic_font)
        all_count_item.setFlags(all_count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.group_table.setItem(0, 1, all_count_item)

        all_online_item = QTableWidgetItem(str(all_online))
        all_online_item.setFont(italic_font)
        all_online_item.setFlags(all_online_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.group_table.setItem(0, 2, all_online_item)

        # User-created groups
        has_user_groups = False
        if self._storage:
            groups = self._storage.get_all_sync_groups()
            has_user_groups = len(groups) > 0

            for group in groups:
                row = self.group_table.rowCount()
                self.group_table.insertRow(row)

                name_item = QTableWidgetItem(group.name)
                name_item.setData(Qt.ItemDataRole.UserRole, group.id)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.group_table.setItem(row, 0, name_item)

                devices_in_group = self._storage.get_devices_in_group(group.id)
                online_count = sum(1 for d in devices_in_group if d.fingerprint in online_fps)

                count_item = QTableWidgetItem(str(len(devices_in_group)))
                count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.group_table.setItem(row, 1, count_item)

                online_item = QTableWidgetItem(str(online_count))
                online_item.setFlags(online_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.group_table.setItem(row, 2, online_item)

        self.groups_empty_label.setVisible(not has_user_groups)

    def _refresh_peers(self) -> None:
        """Refresh the discovered peers table."""
        peers = self._discovery.get_peers()
        known_fingerprints = set()
        if self._storage:
            known_fingerprints = {
                d.fingerprint for d in self._storage.get_all_devices(include_blocked=True)
            }

        self.peer_table.setRowCount(0)

        for peer in peers:
            row = self.peer_table.rowCount()
            self.peer_table.insertRow(row)

            # Name
            name_text = peer.display_name
            name_item = QTableWidgetItem(name_text)
            if peer.is_local:
                name_item.setForeground(QColor("gray"))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.peer_table.setItem(row, 0, name_item)

            # Address
            addr_item = QTableWidgetItem(peer.address)
            addr_item.setFlags(addr_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.peer_table.setItem(row, 1, addr_item)

            # Port
            port_item = QTableWidgetItem(str(peer.port))
            port_item.setFlags(port_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.peer_table.setItem(row, 2, port_item)

            # Fingerprint (truncated)
            fp = peer.fingerprint[:20] + "..." if len(peer.fingerprint) > 20 else peer.fingerprint
            fp_item = QTableWidgetItem(fp)
            fp_item.setToolTip(peer.fingerprint)
            fp_item.setFlags(fp_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.peer_table.setItem(row, 3, fp_item)

            # Known
            is_known = peer.fingerprint in known_fingerprints
            known_item = QTableWidgetItem("Yes" if is_known else "No")
            known_item.setFlags(known_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.peer_table.setItem(row, 4, known_item)

        self.discovery_status_label.setText(f"Found {len(peers)} peer(s) on the network")

    def _refresh_online_status(self) -> None:
        """Refresh online status in device table and peer table without full rebuild."""
        online_fingerprints = self._get_online_fingerprints()

        if self._storage is None:
            return

        devices = self._storage.get_all_devices(include_blocked=True)

        for i in range(self.device_table.rowCount()):
            name_item = self.device_table.item(i, 0)
            status_item = self.device_table.item(i, 1)
            if name_item is None or status_item is None:
                continue

            device_id = name_item.data(Qt.ItemDataRole.UserRole)
            device = next((d for d in devices if d.id == device_id), None)
            if device is None:
                continue

            if device.trust_level == "blocked":
                status_item.setText("Blocked")
                status_item.setForeground(QColor("gray"))
            elif device.fingerprint in online_fingerprints:
                status_item.setText("Online")
                status_item.setForeground(QColor("green"))
            else:
                status_item.setText("Offline")
                status_item.setForeground(QColor("gray"))

        # Update selected device button states if visible
        if self._selected_device and self.device_group.isVisible():
            self._set_device_buttons_enabled(True)

        # Refresh peer table periodically too
        self._refresh_peers()

    # ------------------------------------------------------------------ #
    # Selection handlers
    # ------------------------------------------------------------------ #

    def _on_device_selected(self) -> None:
        """Handle device selection in the table."""
        sel = self.device_table.selectionModel()
        assert sel is not None
        rows = sel.selectedRows()
        if not rows:
            self._selected_device = None
            self.device_group.setVisible(False)
            self._set_device_buttons_enabled(False)
            return

        row = rows[0].row()
        name_item = self.device_table.item(row, 0)
        if name_item is None or self._storage is None:
            return

        device_id = name_item.data(Qt.ItemDataRole.UserRole)
        device = self._storage.get_device(device_id)
        if device is None:
            return

        self._selected_device = device
        self._show_device_details(device)
        self.device_group.setVisible(True)
        self._set_device_buttons_enabled(True)

    def _on_group_selected(self) -> None:
        """Handle group selection in the table."""
        sel = self.group_table.selectionModel()
        assert sel is not None
        rows = sel.selectedRows()
        if not rows:
            self._selected_group_id = None
            self.group_details.setVisible(False)
            self._set_group_buttons_enabled(False, is_all_devices=False)
            return

        row = rows[0].row()
        name_item = self.group_table.item(row, 0)
        if name_item is None:
            return

        group_id = name_item.data(Qt.ItemDataRole.UserRole)

        if group_id == _ALL_DEVICES_SENTINEL:
            # "All Devices" virtual group selected
            self._selected_group_id = _ALL_DEVICES_SENTINEL
            self._show_group_details_all_devices()
            self.group_details.setVisible(True)
            self._set_group_buttons_enabled(True, is_all_devices=True)
        else:
            # User group selected
            if self._storage is None:
                return
            group = self._storage.get_sync_group(group_id)
            if group is None:
                return
            self._selected_group_id = group_id
            self._show_group_details(group)
            self.group_details.setVisible(True)
            self._set_group_buttons_enabled(True, is_all_devices=False)

    def _on_peer_selected(self) -> None:
        """Handle peer selection in the discovery table."""
        peer = self._get_selected_peer()
        if peer is None:
            self.add_to_devices_btn.setEnabled(False)
            self.peer_ping_btn.setEnabled(False)
            self.peer_sync_btn.setEnabled(False)
            return

        is_non_local = not peer.is_local
        self.peer_ping_btn.setEnabled(is_non_local)
        self.peer_sync_btn.setEnabled(is_non_local)

        # "Add to Devices" only for unknown non-local peers
        is_known = False
        if self._storage:
            known_fps = {d.fingerprint for d in self._storage.get_all_devices(include_blocked=True)}
            is_known = peer.fingerprint in known_fps
        self.add_to_devices_btn.setEnabled(is_non_local and not is_known)

    # ------------------------------------------------------------------ #
    # Device details
    # ------------------------------------------------------------------ #

    def _show_device_details(self, device: Device) -> None:
        """Show device details in the panel."""
        self.device_name_edit.setText(device.name)
        self.device_fingerprint_label.setText(device.fingerprint)
        self.device_address_label.setText(device.last_address or "Unknown")

        # Hostname — cross-reference with discovered peers for live info
        peer = self._find_peer_for_device(device)
        if peer:
            hostname_text = peer.hostname
            if peer.name and peer.name != peer.hostname:
                hostname_text = f"{peer.hostname} ({peer.name})"
            self.device_hostname_label.setText(hostname_text)
        elif device.last_address:
            # Extract host part from last_address (host:port)
            host_part = device.last_address.rsplit(":", 1)[0]
            self.device_hostname_label.setText(
                f'{host_part} <span style="color: gray;">(last known)</span>'
            )
        else:
            self.device_hostname_label.setText("Unknown")

        # Format last seen
        from datetime import datetime

        last_seen = datetime.fromtimestamp(device.last_seen / 1000)
        self.device_last_seen_label.setText(last_seen.strftime("%Y-%m-%d %H:%M:%S"))

        # Trust level
        trust_map = {"normal": 0, "trusted": 1, "blocked": 2}
        self.trust_combo.setCurrentIndex(trust_map.get(device.trust_level, 0))

        # Groups
        if self._storage:
            groups = self._storage.get_groups_for_device(device.id)
            if groups:
                group_names = ", ".join(g.name for g in groups)
                self.device_groups_label.setText(group_names)
            else:
                self.device_groups_label.setText("(none)")

        # Pending sync
        online_fingerprints = self._get_online_fingerprints()
        is_online = device.fingerprint in online_fingerprints
        self._update_pending_sync_display(device, is_online)

    def _set_device_buttons_enabled(self, enabled: bool) -> None:
        """Enable/disable device action buttons."""
        is_blocked = self._selected_device and self._selected_device.trust_level == "blocked"
        online = False
        if self._selected_device:
            online = self._selected_device.fingerprint in self._get_online_fingerprints()

        self.sync_btn.setEnabled(enabled and not is_blocked and online)
        self.test_btn.setEnabled(enabled and not is_blocked)
        self.remove_btn.setEnabled(enabled)

        # Queue sync: enabled for offline, non-blocked devices with no pending
        has_pending = False
        if self._selected_device and self._offline_queue:
            pending = self._offline_queue.get_pending_for_device(self._selected_device.id)
            has_pending = bool(pending)
        self.queue_sync_btn.setEnabled(
            enabled and not is_blocked and not online and not has_pending
        )

    # ------------------------------------------------------------------ #
    # Group details
    # ------------------------------------------------------------------ #

    def _show_group_details_all_devices(self) -> None:
        """Show details for the 'All Devices' virtual group."""
        self.group_description_label.setText(
            "Default policy: lists sync to all non-blocked devices unless restricted."
        )

        online_fps = self._get_online_fingerprints()
        devices = self._storage.get_all_devices(include_blocked=False) if self._storage else []

        self.group_members_table.setRowCount(0)
        for device in devices:
            row = self.group_members_table.rowCount()
            self.group_members_table.insertRow(row)

            d_item = QTableWidgetItem(device.name or f"Device {str(device.id)[:8]}")
            d_item.setFlags(d_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.group_members_table.setItem(row, 0, d_item)

            is_online = device.fingerprint in online_fps
            s_item = QTableWidgetItem("Online" if is_online else "Offline")
            s_item.setForeground(QColor("green") if is_online else QColor("gray"))
            s_item.setFlags(s_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.group_members_table.setItem(row, 1, s_item)

            t_item = QTableWidgetItem(device.trust_level.capitalize())
            t_item.setFlags(t_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.group_members_table.setItem(row, 2, t_item)

    def _show_group_details(self, group) -> None:
        """Show group details in the panel."""
        from ...core.models import SyncGroup

        if not isinstance(group, SyncGroup) or self._storage is None:
            return

        # Get devices in group
        devices = self._storage.get_devices_in_group(group.id)
        self.group_description_label.setText(f"{len(devices)} device(s) in this group.")

        online_fps = self._get_online_fingerprints()
        self.group_members_table.setRowCount(0)

        for device in devices:
            row = self.group_members_table.rowCount()
            self.group_members_table.insertRow(row)

            d_item = QTableWidgetItem(device.name or f"Device {str(device.id)[:8]}")
            d_item.setFlags(d_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.group_members_table.setItem(row, 0, d_item)

            is_online = device.fingerprint in online_fps
            s_item = QTableWidgetItem("Online" if is_online else "Offline")
            s_item.setForeground(QColor("green") if is_online else QColor("gray"))
            s_item.setFlags(s_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.group_members_table.setItem(row, 1, s_item)

            t_item = QTableWidgetItem(device.trust_level.capitalize())
            t_item.setFlags(t_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.group_members_table.setItem(row, 2, t_item)

    def _set_group_buttons_enabled(self, enabled: bool, *, is_all_devices: bool) -> None:
        """Enable/disable group action buttons."""
        if is_all_devices:
            # "All Devices": can sync, but cannot edit/rename/delete
            has_online = False
            if self._storage:
                online_fps = self._get_online_fingerprints()
                devices = self._storage.get_all_devices(include_blocked=False)
                has_online = any(d.fingerprint in online_fps for d in devices)
            self.sync_group_btn.setEnabled(enabled and has_online)
            self.edit_group_members_btn.setEnabled(False)
            self.rename_group_btn.setEnabled(False)
            self.delete_group_btn.setEnabled(False)
        else:
            self.sync_group_btn.setEnabled(enabled)
            self.edit_group_members_btn.setEnabled(enabled)
            self.rename_group_btn.setEnabled(enabled)
            self.delete_group_btn.setEnabled(enabled)

    # ------------------------------------------------------------------ #
    # Discovery tab actions (ported from PeerManagerDialog)
    # ------------------------------------------------------------------ #

    def _get_selected_peer(self) -> DiscoveredPeer | None:
        """Get the currently selected peer from the peer table."""
        sel = self.peer_table.selectionModel()
        assert sel is not None
        rows = sel.selectedRows()
        if not rows:
            return None

        row = rows[0].row()
        name_item = self.peer_table.item(row, 0)
        if name_item is None:
            return None

        name = name_item.text()
        # Strip "(this device)" suffix if present
        if name.endswith(" (this device)"):
            name = name[:-14]

        return self._discovery.get_peer(name)

    def _on_add_to_devices(self) -> None:
        """Add the selected discovered peer (or a chosen one) as a known device."""
        if self._storage is None:
            return

        known_fingerprints = {
            d.fingerprint for d in self._storage.get_all_devices(include_blocked=True)
        }

        # If called from the Discovery tab with a peer selected, use it directly
        peer = self._get_selected_peer()
        if peer and not peer.is_local and peer.fingerprint not in known_fingerprints:
            device = create_device(
                fingerprint=peer.fingerprint,
                name=peer.name or peer.hostname or f"Device at {peer.address}",
            )
            device.last_address = f"{peer.address}:{peer.port}"
            self._storage.save_device(device)
            self._refresh_devices()
            self._refresh_peers()
            self.device_updated.emit()
            QMessageBox.information(self, "Device Added", f"Added device: {device.name}")
            return

        # Fallback: show a picker of unknown peers (e.g. called from Devices tab button)
        peers = [
            p
            for p in self._discovery.get_peers()
            if not p.is_local and p.fingerprint not in known_fingerprints
        ]

        if not peers:
            QMessageBox.information(
                self,
                "No New Devices",
                "No new devices discovered on the network.\n\n"
                "Devices are automatically added when you sync with them.",
            )
            return

        peer_names = [f"{p.display_name} ({p.address})" for p in peers]
        name, ok = QInputDialog.getItem(
            self,
            "Add Device",
            "Select a discovered device:",
            peer_names,
            editable=False,
        )
        if not ok:
            return

        idx = peer_names.index(name)
        selected_peer = peers[idx]

        device = create_device(
            fingerprint=selected_peer.fingerprint,
            name=selected_peer.name
            or selected_peer.hostname
            or f"Device at {selected_peer.address}",
        )
        device.last_address = f"{selected_peer.address}:{selected_peer.port}"

        self._storage.save_device(device)
        self._refresh_devices()
        self._refresh_peers()
        self.device_updated.emit()

        QMessageBox.information(self, "Device Added", f"Added device: {device.name}")

    @asyncSlot()
    async def _on_ping(self) -> None:
        """Ping the selected discovered peer."""
        peer = self._get_selected_peer()
        if peer is None:
            return

        self._set_busy(True, f"Pinging {peer.name}...")

        try:
            success, latency = await self._client.ping(peer.address, peer.port)
            if success:
                QMessageBox.information(
                    self,
                    "Connection Successful",
                    f"Connected to {peer.name}\n\n"
                    f"Address: {peer.address}:{peer.port}\n"
                    f"Latency: {latency:.1f}ms\n"
                    f"Fingerprint: {peer.fingerprint}",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Connection Failed",
                    f"Could not connect to {peer.name} at {peer.address}:{peer.port}",
                )
        except Exception as e:
            logger.log.exception("Ping failed: %s", e)
            QMessageBox.critical(self, "Error", f"Connection failed: {e}")
        finally:
            self._set_busy(False)

    @asyncSlot()
    async def _on_peer_sync(self) -> None:
        """Sync with the selected discovered peer."""
        peer = self._get_selected_peer()
        if peer is None or self._database is None:
            return

        self._set_busy(True, f"Syncing with {peer.name}...")

        try:
            # Pull
            pull_ok, data = await self._client.sync_pull(peer.address, peer.port)
            merged_count = 0
            if pull_ok:
                merged_count, _, _ = self._merge_sync_data(data, peer.name)
                self.sync_data_received.emit(data)

            # Push (excludes private lists)
            push_data = json.dumps(self._database.to_dict_for_sync()).encode("utf-8")
            push_ok = await self._client.sync_push(peer.address, peer.port, push_data)

            # Track the device
            fingerprint = self._client.get_last_peer_fingerprint()
            if fingerprint and (pull_ok or push_ok):
                self._track_device(fingerprint, f"{peer.address}:{peer.port}")

            if pull_ok and push_ok:
                QMessageBox.information(
                    self,
                    "Sync Complete",
                    f"Synced with {peer.name}\n"
                    f"Merged {merged_count} items, pushed {len(push_data)} bytes.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Sync Partial",
                    f"Sync with {peer.name} partially failed.",
                )
        except Exception as e:
            logger.log.exception("Peer sync failed: %s", e)
            QMessageBox.critical(self, "Error", f"Sync failed: {e}")
        finally:
            self._set_busy(False)
            self._refresh_devices()
            self._refresh_peers()

    @asyncSlot()
    async def _on_manual_connect(self) -> None:
        """Handle manual connection from the Discovery tab."""
        host = self.manual_host_edit.text().strip()
        port = self.manual_port_spin.value()

        if not host:
            QMessageBox.warning(self, "Error", "Please enter a hostname or IP address.")
            return

        self._set_busy(True, f"Pinging {host}:{port}...")

        try:
            success, latency = await self._client.ping(host, port)
            if success:
                QMessageBox.information(
                    self,
                    "Connection Successful",
                    f"Connected to {host}:{port}\nLatency: {latency:.1f}ms",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Connection Failed",
                    f"Could not connect to {host}:{port}",
                )
        except Exception as e:
            logger.log.exception("Manual connect failed: %s", e)
            QMessageBox.critical(self, "Error", f"Connection failed: {e}")
        finally:
            self._set_busy(False)

    def _track_device(self, fingerprint: str, address: str | None = None) -> None:
        """Track a device by fingerprint, creating or updating as needed."""
        if self._storage is None:
            return

        import time

        now = int(time.time() * 1000)

        try:
            existing = self._storage.get_device_by_fingerprint(fingerprint)
            if existing:
                existing.last_seen = now
                if address:
                    existing.last_address = address
                # Back-fill empty name from discovery if available
                if not existing.name:
                    peer = self._find_peer_by_fingerprint(fingerprint)
                    if peer:
                        existing.name = peer.name or peer.hostname or ""
                self._storage.save_device(existing)
            else:
                # Derive a useful default name from discovered peer info
                peer = self._find_peer_by_fingerprint(fingerprint)
                default_name = ""
                if peer:
                    default_name = peer.name or peer.hostname or ""

                device = Device(
                    fingerprint=fingerprint,
                    name=default_name,
                    first_seen=now,
                    last_seen=now,
                    last_address=address,
                    trust_level="normal",
                )
                self._storage.save_device(device)
                logger.log.info("New device tracked: %s (address=%s)", fingerprint[:19], address)
        except Exception as e:
            logger.log.exception("Error tracking device: %s", e)

    # ------------------------------------------------------------------ #
    # Pending sync display
    # ------------------------------------------------------------------ #

    def _update_pending_sync_display(self, device: Device, is_online: bool) -> None:
        """Update the pending sync display for a device."""
        if self._offline_queue is None:
            self.pending_sync_label.setText("(unavailable)")
            self.queue_sync_btn.setEnabled(False)
            self.clear_queue_btn.setEnabled(False)
            return

        pending = self._offline_queue.get_pending_for_device(device.id)

        if pending:
            # Show pending sync info
            sync = pending[0]
            from datetime import datetime

            created = datetime.fromtimestamp(sync.created_at / 1000)
            self.pending_sync_label.setText(
                f'<span style="color: orange;">Queued ({len(pending)}) - '
                f"since {created.strftime('%m/%d %H:%M')}</span>"
            )
            self.queue_sync_btn.setEnabled(False)
            self.clear_queue_btn.setEnabled(True)
        else:
            if is_online:
                self.pending_sync_label.setText("None (device online)")
                self.queue_sync_btn.setEnabled(False)
            else:
                self.pending_sync_label.setText("None")
                self.queue_sync_btn.setEnabled(True)
            self.clear_queue_btn.setEnabled(False)

    # ------------------------------------------------------------------ #
    # Device actions (business logic — unchanged)
    # ------------------------------------------------------------------ #

    def _on_queue_sync(self) -> None:
        """Queue a sync for the selected offline device."""
        if self._selected_device is None or self._offline_queue is None:
            return

        self._offline_queue.enqueue(self._selected_device.id)
        logger.log.info(
            "Queued sync for device: %s",
            self._selected_device.name or self._selected_device.fingerprint[:19],
        )

        # Update display
        is_online = self._selected_device.fingerprint in self._get_online_fingerprints()
        self._update_pending_sync_display(self._selected_device, is_online)

        QMessageBox.information(
            self,
            "Sync Queued",
            f"Sync queued for {self._selected_device.name or 'device'}.\n"
            "It will be processed when the device comes online.",
        )

    def _on_clear_queue(self) -> None:
        """Clear pending syncs for the selected device."""
        if self._selected_device is None or self._offline_queue is None:
            return

        result = QMessageBox.question(
            self,
            "Clear Pending Syncs",
            f"Clear all pending syncs for {self._selected_device.name or 'this device'}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        count = self._offline_queue.clear_for_device(self._selected_device.id)
        logger.log.info("Cleared %d pending syncs for device", count)

        # Update display
        is_online = self._selected_device.fingerprint in self._get_online_fingerprints()
        self._update_pending_sync_display(self._selected_device, is_online)

    def _on_trust_changed(self, text: str) -> None:
        """Handle trust level change."""
        if self._selected_device is None or self._storage is None:
            return

        trust_map = {"Normal": "normal", "Trusted": "trusted", "Blocked": "blocked"}
        new_trust = trust_map.get(text, "normal")

        if new_trust == self._selected_device.trust_level:
            return

        self._selected_device.trust_level = new_trust
        self._storage.save_device(self._selected_device)
        self._refresh_devices()
        self._set_device_buttons_enabled(True)
        self.device_updated.emit()

    def _on_rename(self) -> None:
        """Rename selected device using the name edit field."""
        if self._selected_device is None or self._storage is None:
            return

        new_name = self.device_name_edit.text().strip()
        if not new_name:
            return

        self._selected_device.name = new_name
        self._storage.save_device(self._selected_device)
        self._refresh_devices()
        self._show_device_details(self._selected_device)
        self.device_updated.emit()

    def _on_remove(self) -> None:
        """Remove selected device."""
        if self._selected_device is None or self._storage is None:
            return

        result = QMessageBox.question(
            self,
            "Remove Device",
            f"Remove '{self._selected_device.name}' from known devices?\n\n"
            f"This will also remove the device from any sync groups.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        self._storage.delete_device(self._selected_device.id)
        self._selected_device = None
        self.device_group.setVisible(False)
        self._set_device_buttons_enabled(False)
        self._refresh_all()
        self.device_updated.emit()

    def _on_update_fingerprint(self) -> None:
        """Update device fingerprint."""
        if self._selected_device is None or self._storage is None:
            return

        # Show warning
        result = QMessageBox.warning(
            self,
            "Update Fingerprint",
            f"<b>Security Warning</b><br><br>"
            f"You are about to update the fingerprint for '{self._selected_device.name}'.<br><br>"
            f"Only do this if you know why the device's key changed "
            f"(e.g., app reinstall, new machine).<br><br>"
            f"<b>Current fingerprint:</b><br>"
            f"<code>{self._selected_device.fingerprint}</code><br><br>"
            f"Do you want to select a new fingerprint from discovered devices?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        # Get discovered peers
        peers = [p for p in self._discovery.get_peers() if not p.is_local]
        if not peers:
            QMessageBox.information(
                self,
                "No Devices Found",
                "No devices discovered on the network to update fingerprint from.",
            )
            return

        # Let user select
        peer_info = [f"{p.display_name} ({p.address}) - {p.fingerprint[:20]}..." for p in peers]
        selected, ok = QInputDialog.getItem(
            self,
            "Select New Fingerprint",
            "Select the device with the new fingerprint:",
            peer_info,
            editable=False,
        )
        if not ok:
            return

        idx = peer_info.index(selected)
        new_fingerprint = peers[idx].fingerprint

        if new_fingerprint == self._selected_device.fingerprint:
            QMessageBox.information(
                self, "No Change", "Selected fingerprint is the same as current."
            )
            return

        # Update
        old_fp = self._selected_device.fingerprint
        self._storage.update_device_fingerprint(self._selected_device.id, new_fingerprint)
        self._selected_device.fingerprint = new_fingerprint

        logger.log.warning(
            "Device '%s' fingerprint updated from %s to %s",
            self._selected_device.name,
            old_fp[:20],
            new_fingerprint[:20],
        )

        self._show_device_details(self._selected_device)
        self.device_updated.emit()

        QMessageBox.information(
            self,
            "Fingerprint Updated",
            f"Fingerprint for '{self._selected_device.name}' has been updated.",
        )

    # ------------------------------------------------------------------ #
    # Sync actions (business logic — unchanged)
    # ------------------------------------------------------------------ #

    @asyncSlot()
    async def _on_sync(self) -> None:
        """Sync with selected device."""
        if self._selected_device is None or self._database is None:
            return

        # Find peer info
        peer = self._find_peer_for_device(self._selected_device)
        if peer is None:
            QMessageBox.warning(self, "Device Offline", "Cannot sync - device is not online.")
            return

        self._set_busy(True, f"Syncing with {self._selected_device.name}...")

        try:
            # Pull
            success, data = await self._client.sync_pull(peer.address, peer.port)
            merged_count = 0
            if success:
                merged_count, _, _ = self._merge_sync_data(data, self._selected_device.name)
                self.sync_data_received.emit(data)

            # Push (filtered by sync rules for this device)
            push_success = False
            push_data = self._get_sync_data_for_device(self._selected_device)
            push_success = await self._client.sync_push(peer.address, peer.port, push_data)

            # Update device last seen
            self._selected_device.update_seen(f"{peer.address}:{peer.port}")
            if self._storage is not None:
                self._storage.save_device(self._selected_device)

            if success and push_success:
                QMessageBox.information(
                    self,
                    "Sync Complete",
                    f"Synced with {self._selected_device.name}\n"
                    f"Merged {merged_count} items, pushed {len(push_data)} bytes.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Sync Partial",
                    f"Sync with {self._selected_device.name} partially failed.",
                )
        except Exception as e:
            logger.log.exception("Sync failed: %s", e)
            QMessageBox.critical(self, "Sync Error", f"Sync failed: {e}")
        finally:
            self._set_busy(False)

    @asyncSlot()
    async def _on_test_connection(self) -> None:
        """Test connection to selected device."""
        if self._selected_device is None:
            return

        # Try to find online peer
        peer = self._find_peer_for_device(self._selected_device)

        if peer is None:
            # Try last known address
            if self._selected_device.last_address:
                parts = self._selected_device.last_address.split(":")
                if len(parts) == 2:
                    host, port = parts[0], int(parts[1])
                else:
                    QMessageBox.warning(
                        self,
                        "Cannot Test",
                        "Device is offline and no valid last address available.",
                    )
                    return
            else:
                QMessageBox.warning(
                    self, "Cannot Test", "Device is offline and no last address known."
                )
                return
        else:
            host, port = peer.address, peer.port

        self._set_busy(True, f"Testing connection to {self._selected_device.name}...")

        try:
            success, latency = await self._client.ping(host, port)
            if success:
                # Update last seen
                self._selected_device.update_seen(f"{host}:{port}")
                if self._storage is not None:
                    self._storage.save_device(self._selected_device)
                self._show_device_details(self._selected_device)

                QMessageBox.information(
                    self,
                    "Connection Successful",
                    f"Connected to {self._selected_device.name}\n\n"
                    f"Address: {host}:{port}\n"
                    f"Latency: {latency:.1f}ms",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Connection Failed",
                    f"Could not connect to {self._selected_device.name} at {host}:{port}",
                )
        except Exception as e:
            logger.log.exception("Test connection failed: %s", e)
            QMessageBox.critical(self, "Error", f"Connection test failed: {e}")
        finally:
            self._set_busy(False)

    @asyncSlot()
    async def _on_sync_all(self) -> None:
        """Sync with all online trusted devices."""
        if self._storage is None or self._database is None:
            return

        # Get online trusted devices
        online_fps = self._get_online_fingerprints()
        devices = [
            d
            for d in self._storage.get_all_devices()
            if d.trust_level == "trusted" and d.fingerprint in online_fps
        ]

        if not devices:
            QMessageBox.information(
                self,
                "No Devices",
                "No trusted devices are currently online.",
            )
            return

        result = QMessageBox.question(
            self,
            "Sync All",
            f"Sync with {len(devices)} trusted online device(s)?\n\n"
            + "\n".join(f"  - {d.name}" for d in devices),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        success_count = 0
        fail_count = 0

        for device in devices:
            peer = self._find_peer_for_device(device)
            if peer is None:
                fail_count += 1
                continue

            self._set_busy(True, f"Syncing with {device.name}...")

            try:
                # Pull
                pull_ok, data = await self._client.sync_pull(peer.address, peer.port)
                if pull_ok:
                    self._merge_sync_data(data, device.name)
                    self.sync_data_received.emit(data)

                # Push (filtered by sync rules for this device)
                push_data = self._get_sync_data_for_device(device)
                push_ok = await self._client.sync_push(peer.address, peer.port, push_data)

                if pull_ok and push_ok:
                    success_count += 1
                    device.update_seen(f"{peer.address}:{peer.port}")
                    self._storage.save_device(device)
                else:
                    fail_count += 1
            except Exception as e:
                logger.log.exception("Sync with %s failed: %s", device.name, e)
                fail_count += 1

        self._set_busy(False)
        self._refresh_devices()

        QMessageBox.information(
            self,
            "Sync All Complete",
            f"Synced with {success_count} device(s).\n{fail_count} failed." if fail_count else "",
        )

    @asyncSlot()
    async def _on_sync_group(self) -> None:
        """Sync with all online devices in the selected group."""
        if self._storage is None or self._database is None:
            return

        if self._selected_group_id == _ALL_DEVICES_SENTINEL:
            # "All Devices" — sync all non-blocked online devices
            devices = self._storage.get_all_devices(include_blocked=False)
            group_name = "All Devices"
        elif self._selected_group_id is not None:
            group = self._storage.get_sync_group(cast(UUID, self._selected_group_id))
            if group is None:
                return
            devices = self._storage.get_devices_in_group(group.id)
            group_name = group.name
        else:
            return

        online_fps = self._get_online_fingerprints()
        online_devices = [d for d in devices if d.fingerprint in online_fps]

        if not online_devices:
            QMessageBox.information(
                self,
                "No Online Devices",
                f"No devices in '{group_name}' are currently online.",
            )
            return

        result = QMessageBox.question(
            self,
            "Sync Group",
            f"Sync with {len(online_devices)} online device(s) in '{group_name}'?\n\n"
            + "\n".join(f"  - {d.name}" for d in online_devices),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        success_count = 0
        fail_count = 0

        for device in online_devices:
            peer = self._find_peer_for_device(device)
            if peer is None:
                fail_count += 1
                continue

            self._set_busy(True, f"Syncing with {device.name}...")

            try:
                # Pull
                pull_ok, data = await self._client.sync_pull(peer.address, peer.port)
                if pull_ok:
                    self._merge_sync_data(data, device.name)
                    self.sync_data_received.emit(data)

                # Push (filtered by sync rules for this device)
                push_data = self._get_sync_data_for_device(device)
                push_ok = await self._client.sync_push(peer.address, peer.port, push_data)

                if pull_ok and push_ok:
                    success_count += 1
                    device.update_seen(f"{peer.address}:{peer.port}")
                    self._storage.save_device(device)
                else:
                    fail_count += 1
            except Exception as e:
                logger.log.exception("Sync with %s failed: %s", device.name, e)
                fail_count += 1

        self._set_busy(False)
        self._refresh_devices()

        if self._selected_group_id == _ALL_DEVICES_SENTINEL:
            self._show_group_details_all_devices()
        elif self._selected_group_id is not None:
            group = self._storage.get_sync_group(cast(UUID, self._selected_group_id))
            if group:
                self._show_group_details(group)

        msg = f"Synced with {success_count} device(s) in '{group_name}'."
        if fail_count:
            msg += f"\n{fail_count} failed."
        QMessageBox.information(self, "Sync Group Complete", msg)

    # ------------------------------------------------------------------ #
    # Group actions (business logic — unchanged)
    # ------------------------------------------------------------------ #

    def _on_add_group(self) -> None:
        """Add a new sync group."""
        if self._storage is None:
            return

        name, ok = QInputDialog.getText(self, "New Sync Group", "Enter group name:")
        if not ok or not name.strip():
            return

        # Check for duplicate
        if self._storage.get_sync_group_by_name(name.strip()):
            QMessageBox.warning(self, "Duplicate Name", f"A group named '{name}' already exists.")
            return

        group = create_sync_group(name.strip())
        self._storage.save_sync_group(group)
        self._refresh_groups()

    def _on_rename_group(self) -> None:
        """Rename selected sync group."""
        if self._selected_group_id is None or self._storage is None:
            return
        if self._selected_group_id == _ALL_DEVICES_SENTINEL:
            return

        group = self._storage.get_sync_group(cast(UUID, self._selected_group_id))
        if group is None:
            return

        name, ok = QInputDialog.getText(
            self,
            "Rename Group",
            "Enter new name:",
            text=group.name,
        )
        if not ok or not name.strip():
            return

        # Check for duplicate
        existing = self._storage.get_sync_group_by_name(name.strip())
        if existing and existing.id != group.id:
            QMessageBox.warning(self, "Duplicate Name", f"A group named '{name}' already exists.")
            return

        group.name = name.strip()
        group.mark_updated()
        self._storage.save_sync_group(group)
        self._refresh_groups()
        self._show_group_details(group)

    def _on_delete_group(self) -> None:
        """Delete selected sync group."""
        if self._selected_group_id is None or self._storage is None:
            return
        if self._selected_group_id == _ALL_DEVICES_SENTINEL:
            return

        group = self._storage.get_sync_group(cast(UUID, self._selected_group_id))
        if group is None:
            return

        devices = self._storage.get_devices_in_group(group.id)
        device_warning = ""
        if devices:
            device_warning = f"\n\n{len(devices)} device(s) will be removed from this group."

        result = QMessageBox.question(
            self,
            "Delete Group",
            f"Delete sync group '{group.name}'?{device_warning}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        self._storage.delete_sync_group(group.id)
        self._selected_group_id = None
        self.group_details.setVisible(False)
        self._set_group_buttons_enabled(False, is_all_devices=False)
        self._refresh_groups()

    def _on_edit_group_members(self) -> None:
        """Edit which devices belong to the selected group."""
        if self._selected_group_id is None or self._storage is None:
            return
        if self._selected_group_id == _ALL_DEVICES_SENTINEL:
            return

        group = self._storage.get_sync_group(cast(UUID, self._selected_group_id))
        if group is None:
            return

        # Get all devices and current members
        all_devices = self._storage.get_all_devices(include_blocked=False)
        current_members = self._storage.get_devices_in_group(group.id)
        current_member_ids = {d.id for d in current_members}

        if not all_devices:
            QMessageBox.information(
                self,
                "No Devices",
                "No devices available to add to the group.",
            )
            return

        # Create a multi-select dialog
        from PyQt6.QtWidgets import QCheckBox, QScrollArea

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Members: {group.name}")
        dialog.setMinimumWidth(300)
        dialog.setMinimumHeight(300)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Select devices for '{group.name}':"))

        # Scroll area for checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        checkboxes = []
        for device in all_devices:
            cb = QCheckBox(device.name or f"Device {str(device.id)[:8]}")
            cb.setChecked(device.id in current_member_ids)
            cb.setProperty("device_id", device.id)
            checkboxes.append(cb)
            scroll_layout.addWidget(cb)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Update memberships
        new_member_ids = set()
        for cb in checkboxes:
            if cb.isChecked():
                new_member_ids.add(cb.property("device_id"))

        # Remove devices no longer in group
        for device_id in current_member_ids - new_member_ids:
            self._storage.remove_device_from_group(device_id, group.id)

        # Add new devices
        for device_id in new_member_ids - current_member_ids:
            self._storage.add_device_to_group(device_id, group.id)

        self._refresh_groups()
        self._show_group_details(group)

    def _on_edit_device_groups(self) -> None:
        """Edit which groups the selected device belongs to."""
        if self._selected_device is None or self._storage is None:
            return

        # Get all groups and current memberships
        all_groups = self._storage.get_all_sync_groups()
        current_groups = self._storage.get_groups_for_device(self._selected_device.id)
        current_group_ids = {g.id for g in current_groups}

        if not all_groups:
            QMessageBox.information(
                self,
                "No Groups",
                "No sync groups exist. Create a group first.",
            )
            return

        # Create a multi-select dialog
        from PyQt6.QtWidgets import QCheckBox, QScrollArea

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Groups: {self._selected_device.name}")
        dialog.setMinimumWidth(300)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Select groups for '{self._selected_device.name}':"))

        # Scroll area for checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        checkboxes = []
        for group in all_groups:
            cb = QCheckBox(group.name)
            cb.setChecked(group.id in current_group_ids)
            cb.setProperty("group_id", group.id)
            checkboxes.append(cb)
            scroll_layout.addWidget(cb)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Update memberships
        new_group_ids = set()
        for cb in checkboxes:
            if cb.isChecked():
                new_group_ids.add(cb.property("group_id"))

        # Remove device from groups
        for group_id in current_group_ids - new_group_ids:
            self._storage.remove_device_from_group(self._selected_device.id, group_id)

        # Add device to new groups
        for group_id in new_group_ids - current_group_ids:
            self._storage.add_device_to_group(self._selected_device.id, group_id)

        self._refresh_groups()
        self._show_device_details(self._selected_device)

    # ------------------------------------------------------------------ #
    # Helpers (business logic — unchanged)
    # ------------------------------------------------------------------ #

    def _get_online_fingerprints(self) -> set[str]:
        """Get fingerprints of currently online peers."""
        peers = self._discovery.get_peers()
        return {p.fingerprint for p in peers if not p.is_local}

    def _find_peer_for_device(self, device: Device) -> DiscoveredPeer | None:
        """Find online peer matching device fingerprint."""
        return self._find_peer_by_fingerprint(device.fingerprint)

    def _find_peer_by_fingerprint(self, fingerprint: str) -> DiscoveredPeer | None:
        """Find a discovered peer by fingerprint."""
        for peer in self._discovery.get_peers():
            if peer.fingerprint == fingerprint and not peer.is_local:
                return peer
        return None

    def _get_sync_data_for_device(self, device: Device) -> bytes:
        """Get sync data filtered for a specific device based on sync rules.

        Args:
            device: The target device

        Returns:
            JSON-encoded sync data filtered to lists that should sync to this device
        """
        if self._database is None or self._storage is None:
            return b"{}"

        # Get list IDs that should sync to this device
        allowed_list_ids = self._storage.get_syncable_list_ids_for_device(device.id)

        # Generate filtered sync data
        return json.dumps(self._database.to_dict_for_device(allowed_list_ids)).encode("utf-8")

    def _merge_sync_data(self, data: bytes, peer_name: str = "") -> tuple[int, int, int]:
        """Merge received sync data into local database."""
        if self._database is None:
            return 0, 0, 0

        try:
            remote_db = Database.from_dict(json.loads(data.decode("utf-8")))
            merged = 0
            local_newer = 0
            identical = 0

            for list_id, remote_list in remote_db.lists.items():
                if list_id in self._database.lists:
                    local_list = self._database.lists[list_id]
                    # List-level metadata LWW
                    if remote_list.updated_at > local_list.updated_at:
                        if remote_list.name != local_list.name:
                            local_list.name = self._database.resolve_name_collision(
                                remote_list.name, peer_name
                            )
                        local_list.deleted = remote_list.deleted
                        local_list.updated_at = remote_list.updated_at
                        merged += 1
                    for item_id, remote_item in remote_list.items.items():
                        if item_id in local_list.items:
                            local_item = local_list.items[item_id]
                            if remote_item.updated_at > local_item.updated_at:
                                local_list.items[item_id] = remote_item
                                merged += 1
                            elif remote_item.updated_at < local_item.updated_at:
                                local_newer += 1
                            else:
                                identical += 1
                        else:
                            local_list.items[item_id] = remote_item
                            merged += 1
                else:
                    remote_list.name = self._database.resolve_name_collision(
                        remote_list.name, peer_name
                    )
                    self._database.lists[list_id] = remote_list
                    merged += len(remote_list.items)

            return merged, local_newer, identical
        except Exception as e:
            logger.log.exception("Error merging sync data: %s", e)
            return 0, 0, 0

    def _populate_sync_group_menu(self) -> None:
        """Populate the sync group dropdown menu."""
        self._sync_group_menu.clear()

        if self._storage is None:
            action = self._sync_group_menu.addAction("No groups")
            if action:
                action.setEnabled(False)
            return

        groups = self._storage.get_all_sync_groups()
        if not groups:
            action = self._sync_group_menu.addAction("No groups created")
            if action:
                action.setEnabled(False)
            return

        online_fps = self._get_online_fingerprints()

        for group in groups:
            devices = self._storage.get_devices_in_group(group.id)
            online_count = sum(1 for d in devices if d.fingerprint in online_fps)
            action = self._sync_group_menu.addAction(
                f"{group.name} ({online_count}/{len(devices)} online)"
            )
            if action:
                action.setData(group.id)
                action.setEnabled(online_count > 0)
                action.triggered.connect(
                    lambda checked, gid=group.id: self._on_sync_group_from_menu(gid)
                )

    def _on_sync_group_from_menu(self, group_id) -> None:
        """Handle sync group selection from menu."""
        # Select the group in the table
        for i in range(self.group_table.rowCount()):
            item = self.group_table.item(i, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == group_id:
                self.group_table.selectRow(i)
                break

        # Trigger sync
        import asyncio

        asyncio.ensure_future(self._on_sync_group())

    def _set_busy(self, busy: bool, message: str = "") -> None:
        """Set UI busy state."""
        self.sync_btn.setEnabled(not busy and self._selected_device is not None)
        self.test_btn.setEnabled(not busy and self._selected_device is not None)
        self.sync_all_btn.setEnabled(not busy)
        self.sync_group_menu_btn.setEnabled(not busy)

        if busy:
            self.status_label.setText(message)
            self.setWindowTitle(f"Device & Sync Manager - {message}")
        else:
            self.status_label.setText("")
            self.setWindowTitle("Device & Sync Manager")

    def closeEvent(self, a0) -> None:  # noqa: N802
        """Handle dialog close."""
        self._refresh_timer.stop()
        super().closeEvent(a0)
