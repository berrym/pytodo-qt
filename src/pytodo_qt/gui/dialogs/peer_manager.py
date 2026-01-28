"""peer_manager.py

Dialog for managing discovered peers and connections.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
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
from qasync import asyncSlot

from ...core.logger import Logger
from ...core.models import Database
from ...net.client import AsyncClient
from ...net.discovery import DiscoveredPeer, get_discovery_service

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class PeerManagerDialog(QDialog):
    """Dialog for managing discovered peers and connections."""

    # Signal emitted when sync data is received (data bytes)
    sync_data_received = pyqtSignal(bytes)

    def __init__(self, parent=None, database: Database | None = None):
        super().__init__(parent)
        self.setWindowTitle("Peer Manager")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self._discovery = get_discovery_service()
        self._client = AsyncClient(self)
        self._database = database
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

        self.ping_btn = QPushButton("Ping")
        self.ping_btn.clicked.connect(self._on_ping)
        self.ping_btn.setEnabled(False)
        peer_btns.addWidget(self.ping_btn)

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
        self.ping_btn.setEnabled(enabled)
        self.sync_btn.setEnabled(enabled)

    @asyncSlot()
    async def _on_ping(self) -> None:
        """Handle ping button click - test connectivity to peer."""
        logger.log.debug("Ping button clicked")
        peer = self._get_selected_peer()
        if peer is None:
            logger.log.debug("No peer selected")
            return

        logger.log.debug("Pinging peer: %s", peer.name)
        self._set_busy(True, f"Pinging {peer.name}...")

        try:
            logger.log.debug("Calling client.ping(%s, %d)", peer.address, peer.port)
            success, latency = await self._client.ping(peer.address, peer.port)
            logger.log.debug("Ping returned: success=%s, latency=%s", success, latency)
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
    async def _on_sync(self) -> None:
        """Handle sync button click - bidirectional sync with peer."""
        logger.log.debug("Sync button clicked")
        peer = self._get_selected_peer()
        if peer is None:
            logger.log.debug("No peer selected")
            return

        logger.log.debug("Syncing with peer: %s", peer.name)
        self._set_busy(True, f"Pulling from {peer.name}...")

        pull_success = False
        push_success = False
        merged_count = 0
        push_data = b""

        try:
            # First, pull from peer
            logger.log.debug("Calling client.sync_pull(%s, %d)", peer.address, peer.port)
            pull_success, data = await self._client.sync_pull(peer.address, peer.port)
            logger.log.debug(
                "Sync pull returned: success=%s, data_len=%d",
                pull_success,
                len(data) if data else 0,
            )

            local_newer = 0
            if pull_success:
                merged_count, local_newer, _ = self._merge_sync_data(data)
                self.sync_data_received.emit(data)

            # Then, push to peer
            if self._database is not None:
                self._set_busy(True, f"Pushing to {peer.name}...")
                push_data = json.dumps(self._database.to_dict()).encode("utf-8")
                logger.log.debug("Calling client.sync_push(%s, %d)", peer.address, peer.port)
                push_success = await self._client.sync_push(peer.address, peer.port, push_data)
                logger.log.debug("Sync push returned: success=%s", push_success)

            # Report results
            if pull_success and push_success:
                if merged_count > 0:
                    QMessageBox.information(
                        self,
                        "Sync Complete",
                        f"Synced with {peer.name}\n"
                        f"Merged {merged_count} new items.\n"
                        f"Pushed {len(push_data)} bytes.",
                    )
                elif local_newer > 0:
                    QMessageBox.information(
                        self,
                        "Sync Complete",
                        f"Synced with {peer.name}\n"
                        f"{local_newer} local items were newer (kept).\n"
                        f"Pushed {len(push_data)} bytes.",
                    )
                else:
                    QMessageBox.information(
                        self,
                        "Already In Sync",
                        f"Synced with {peer.name}\n"
                        f"Databases are identical.\n"
                        f"Pushed {len(push_data)} bytes.",
                    )
            elif pull_success:
                QMessageBox.warning(
                    self,
                    "Partial Sync",
                    f"Pulled {merged_count} items from {peer.name}\nbut push failed.",
                )
            elif push_success:
                QMessageBox.warning(
                    self,
                    "Partial Sync",
                    f"Pushed to {peer.name}\nbut pull failed.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Sync Failed",
                    f"Could not sync with {peer.name}",
                )
        except Exception as e:
            logger.log.exception("Sync failed: %s", e)
            QMessageBox.critical(self, "Error", f"Sync failed: {e}")
        finally:
            self._set_busy(False)

    def _merge_sync_data(self, data: bytes) -> tuple[int, int, int]:
        """Merge received sync data into local database.

        Returns:
            Tuple of (merged_count, local_newer_count, identical_count)
        """
        if self._database is None:
            logger.log.warning("No database available for merge")
            return 0, 0, 0

        try:
            remote_db = Database.from_dict(json.loads(data.decode("utf-8")))
            merged_count = 0
            local_newer_count = 0
            identical_count = 0

            for list_id, remote_list in remote_db.lists.items():
                if list_id in self._database.lists:
                    local_list = self._database.lists[list_id]
                    for item_id, remote_item in remote_list.items.items():
                        if item_id in local_list.items:
                            local_item = local_list.items[item_id]
                            if remote_item.updated_at > local_item.updated_at:
                                local_list.items[item_id] = remote_item
                                merged_count += 1
                            elif remote_item.updated_at < local_item.updated_at:
                                local_newer_count += 1
                            else:
                                identical_count += 1
                        else:
                            local_list.items[item_id] = remote_item
                            merged_count += 1
                else:
                    self._database.lists[list_id] = remote_list
                    merged_count += len(remote_list.items)

            logger.log.info(
                "Merge result: %d merged, %d local newer, %d identical",
                merged_count,
                local_newer_count,
                identical_count,
            )
            return merged_count, local_newer_count, identical_count
        except Exception as e:
            logger.log.exception("Error merging sync data: %s", e)
            return 0, 0, 0

    @asyncSlot()
    async def _on_manual_connect(self) -> None:
        """Handle manual connect button click."""
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

    def _set_busy(self, busy: bool, message: str = "") -> None:
        """Set UI busy state."""
        self.ping_btn.setEnabled(not busy)
        self.sync_btn.setEnabled(not busy)
        self.status_label.setText(
            message if busy else f"Found {len(self._discovery.get_peers())} peer(s)"
        )

    def closeEvent(self, event) -> None:
        """Handle dialog close."""
        self._refresh_timer.stop()
        super().closeEvent(event)
