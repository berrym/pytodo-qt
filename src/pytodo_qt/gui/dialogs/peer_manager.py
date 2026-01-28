"""peer_manager.py

Dialog for managing discovered peers and connections.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...core.logger import Logger
from ...net.discovery import DiscoveredPeer, get_discovery_service

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class PeerManagerDialog(QDialog):
    """Dialog for managing discovered peers and connections."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Peer Manager")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self._discovery = get_discovery_service()
        self._setup_ui()
        self._refresh_peers()

        # Auto-refresh timer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_peers)
        self._refresh_timer.start(5000)  # Refresh every 5 seconds

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Discovered peers section
        peers_group = QGroupBox("Discovered Peers")
        peers_layout = QVBoxLayout(peers_group)

        # Peer table
        self.peer_table = QTableWidget()
        self.peer_table.setColumnCount(5)
        self.peer_table.setHorizontalHeaderLabels(
            ["Name", "Address", "Port", "Version", "Fingerprint"]
        )
        self.peer_table.horizontalHeader().setStretchLastSection(True)
        self.peer_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.peer_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.peer_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        peers_layout.addWidget(self.peer_table)

        # Peer action buttons
        peer_btns = QHBoxLayout()

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._on_connect)
        self.connect_btn.setEnabled(False)
        peer_btns.addWidget(self.connect_btn)

        self.sync_btn = QPushButton("Sync")
        self.sync_btn.clicked.connect(self._on_sync)
        self.sync_btn.setEnabled(False)
        peer_btns.addWidget(self.sync_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_peers)
        peer_btns.addWidget(refresh_btn)

        peer_btns.addStretch()
        peers_layout.addLayout(peer_btns)

        layout.addWidget(peers_group)

        # Manual connection section
        manual_group = QGroupBox("Manual Connection")
        manual_layout = QFormLayout(manual_group)

        self.manual_host_edit = QLineEdit()
        self.manual_host_edit.setPlaceholderText("hostname or IP address")
        manual_layout.addRow("Host:", self.manual_host_edit)

        self.manual_port_spin = QSpinBox()
        self.manual_port_spin.setRange(1024, 65535)
        self.manual_port_spin.setValue(5364)
        manual_layout.addRow("Port:", self.manual_port_spin)

        manual_btns = QHBoxLayout()
        manual_connect_btn = QPushButton("Connect")
        manual_connect_btn.clicked.connect(self._on_manual_connect)
        manual_btns.addWidget(manual_connect_btn)
        manual_btns.addStretch()
        manual_layout.addRow("", manual_btns)

        layout.addWidget(manual_group)

        # Status label
        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        # Connect selection changed
        self.peer_table.itemSelectionChanged.connect(self._on_selection_changed)

    def _refresh_peers(self) -> None:
        """Refresh the peer list."""
        peers = self._discovery.get_peers()

        self.peer_table.setRowCount(0)

        for peer in peers:
            row = self.peer_table.rowCount()
            self.peer_table.insertRow(row)

            # Name
            name_item = QTableWidgetItem(peer.display_name)
            if peer.is_local:
                name_item.setForeground(QColor("gray"))
            self.peer_table.setItem(row, 0, name_item)

            # Address
            self.peer_table.setItem(row, 1, QTableWidgetItem(peer.address))

            # Port
            self.peer_table.setItem(row, 2, QTableWidgetItem(str(peer.port)))

            # Version
            self.peer_table.setItem(row, 3, QTableWidgetItem(f"v{peer.protocol_version}"))

            # Fingerprint (truncated)
            fp = peer.fingerprint[:20] + "..." if len(peer.fingerprint) > 20 else peer.fingerprint
            fp_item = QTableWidgetItem(fp)
            fp_item.setToolTip(peer.fingerprint)
            self.peer_table.setItem(row, 4, fp_item)

        self.status_label.setText(f"Found {len(peers)} peer(s)")

    def _get_selected_peer(self) -> DiscoveredPeer | None:
        """Get the currently selected peer."""
        rows = self.peer_table.selectionModel().selectedRows()
        if not rows:
            return None

        row = rows[0].row()
        name_item = self.peer_table.item(row, 0)
        if name_item is None:
            return None

        # Find peer by name (strip "(this device)" suffix if present)
        name = name_item.text()
        if name.endswith(" (this device)"):
            name = name[:-14]

        return self._discovery.get_peer(name)

    def _on_selection_changed(self) -> None:
        """Handle selection change."""
        peer = self._get_selected_peer()
        enabled = peer is not None and not peer.is_local
        self.connect_btn.setEnabled(enabled)
        self.sync_btn.setEnabled(enabled)

    def _on_connect(self) -> None:
        """Handle connect button click."""
        peer = self._get_selected_peer()
        if peer is None:
            return

        # Just ping for now
        QMessageBox.information(
            self,
            "Connect",
            f"Would connect to {peer.name} at {peer.address}:{peer.port}\n\n"
            f"Fingerprint: {peer.fingerprint}",
        )

    def _on_sync(self) -> None:
        """Handle sync button click."""
        peer = self._get_selected_peer()
        if peer is None:
            return

        QMessageBox.information(
            self, "Sync", f"Would sync with {peer.name} at {peer.address}:{peer.port}"
        )

    def _on_manual_connect(self) -> None:
        """Handle manual connect button click."""
        host = self.manual_host_edit.text().strip()
        port = self.manual_port_spin.value()

        if not host:
            QMessageBox.warning(self, "Error", "Please enter a hostname or IP address.")
            return

        QMessageBox.information(self, "Manual Connect", f"Would connect to {host}:{port}")

    def closeEvent(self, event) -> None:
        """Handle dialog close."""
        self._refresh_timer.stop()
        super().closeEvent(event)
