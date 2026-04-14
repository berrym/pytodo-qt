"""sync.py

Dialog for synchronization operations.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
)
from qasync import asyncSlot

from ...core.config import get_config
from ...core.logger import Logger
from ...core.models import Database
from ...net.client import AsyncClient

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class SyncDialog(QDialog):
    """Dialog for synchronization operations."""

    def __init__(self, parent=None, operation: str = "pull", database: Database | None = None):
        """Initialize sync dialog.

        Args:
            parent: Parent widget
            operation: "pull" or "push"
            database: Database instance for sync operations
        """
        super().__init__(parent)
        self._operation = operation
        self._database = database
        self._client = AsyncClient(self)
        self._sync_result: bytes | None = None
        self._last_host: str = ""
        self._last_port: int = 0

        title = self.tr("Sync Pull") if operation == "pull" else self.tr("Sync Push")
        self.setWindowTitle(title)
        self.setMinimumWidth(400)

        self._setup_ui()
        self._load_defaults()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Operation description
        if self._operation == "pull":
            desc = self.tr("Pull todo lists from a remote host.")
        else:
            desc = self.tr("Push your todo lists to a remote host.")
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Connection group
        conn_group = QGroupBox(self.tr("Remote Host"))
        conn_layout = QFormLayout(conn_group)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText(self.tr("hostname or IP address"))
        conn_layout.addRow(self.tr("Host:"), self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(5364)
        conn_layout.addRow(self.tr("Port:"), self.port_spin)

        layout.addWidget(conn_group)

        # Progress bar (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        # Button box
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText(self.tr("Pull") if self._operation == "pull" else self.tr("Push"))
        self.button_box.accepted.connect(self._on_sync)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _load_defaults(self) -> None:
        """Load default values from config."""
        config = get_config()
        self.port_spin.setValue(config.server.port)

    @asyncSlot()
    async def _on_sync(self) -> None:
        """Handle sync button click."""
        host = self.host_edit.text().strip()
        if not host:
            QMessageBox.warning(
                self, self.tr("Validation Error"), self.tr("Please enter a hostname or IP address.")
            )
            self.host_edit.setFocus()
            return

        port = self.port_spin.value()

        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.status_label.setText(self.tr(f"Connecting to {host}:{port}..."))
        self.button_box.setEnabled(False)

        self._last_host = host
        self._last_port = port

        try:
            if self._operation == "pull":
                await self._do_pull(host, port)
            else:
                await self._do_push(host, port)
        except Exception as e:
            logger.log.exception("Sync failed: %s", e)
            self.status_label.setText(self.tr(f"Error: {e}"))
            QMessageBox.critical(self, self.tr("Sync Error"), self.tr(f"Sync failed: {e}"))
        finally:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.button_box.setEnabled(True)

    async def _do_pull(self, host: str, port: int) -> None:
        """Perform sync pull operation."""
        self.status_label.setText(self.tr(f"Pulling from {host}:{port}..."))

        success, data = await self._client.sync_pull(host, port)
        if success:
            self._sync_result = data
            self.status_label.setText(self.tr(f"Pulled {len(data)} bytes"))
            QMessageBox.information(
                self,
                self.tr("Sync Complete"),
                self.tr(f"Successfully pulled {len(data)} bytes from {host}:{port}"),
            )
            logger.log.info("Sync pull successful: %d bytes from %s:%d", len(data), host, port)
            self.accept()
        else:
            self.status_label.setText(self.tr("Pull failed"))
            QMessageBox.warning(
                self, self.tr("Sync Failed"), self.tr(f"Could not pull from {host}:{port}")
            )

    async def _do_push(self, host: str, port: int) -> None:
        """Perform sync push operation (excludes private lists)."""
        if self._database is None:
            QMessageBox.warning(self, self.tr("Error"), self.tr("No database available for push"))
            return

        self.status_label.setText(self.tr(f"Pushing to {host}:{port}..."))

        data = json.dumps(self._database.to_dict_for_sync()).encode("utf-8")
        success = await self._client.sync_push(host, port, data)

        if success:
            self.status_label.setText(self.tr(f"Pushed {len(data)} bytes"))
            QMessageBox.information(
                self,
                self.tr("Sync Complete"),
                self.tr(f"Successfully pushed {len(data)} bytes to {host}:{port}"),
            )
            logger.log.info("Sync push successful: %d bytes to %s:%d", len(data), host, port)
            self.accept()
        else:
            self.status_label.setText(self.tr("Push failed"))
            QMessageBox.warning(
                self, self.tr("Sync Failed"), self.tr(f"Could not push to {host}:{port}")
            )

    def get_host(self) -> str:
        """Get the entered host."""
        return self.host_edit.text().strip()

    def get_port(self) -> int:
        """Get the entered port."""
        return self.port_spin.value()

    def get_sync_result(self) -> bytes | None:
        """Get the pulled sync data (for pull operations)."""
        return self._sync_result

    def get_peer_fingerprint(self) -> str | None:
        """Get the fingerprint of the last synced peer."""
        return self._client.get_last_peer_fingerprint()

    def get_last_address(self) -> str | None:
        """Get the address of the last synced peer (host:port)."""
        if self._last_host:
            return f"{self._last_host}:{self._last_port}"
        return None
