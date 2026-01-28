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

        title = "Sync Pull" if operation == "pull" else "Sync Push"
        self.setWindowTitle(title)
        self.setMinimumWidth(400)

        self._setup_ui()
        self._load_defaults()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Operation description
        if self._operation == "pull":
            desc = "Pull to-do lists from a remote host."
        else:
            desc = "Push your to-do lists to a remote host."
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Connection group
        conn_group = QGroupBox("Remote Host")
        conn_layout = QFormLayout(conn_group)

        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("hostname or IP address")
        conn_layout.addRow("Host:", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(5364)
        conn_layout.addRow("Port:", self.port_spin)

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
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Pull" if self._operation == "pull" else "Push"
        )
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
            QMessageBox.warning(self, "Validation Error", "Please enter a hostname or IP address.")
            self.host_edit.setFocus()
            return

        port = self.port_spin.value()

        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.status_label.setText(f"Connecting to {host}:{port}...")
        self.button_box.setEnabled(False)

        try:
            if self._operation == "pull":
                await self._do_pull(host, port)
            else:
                await self._do_push(host, port)
        except Exception as e:
            logger.log.exception("Sync failed: %s", e)
            self.status_label.setText(f"Error: {e}")
            QMessageBox.critical(self, "Sync Error", f"Sync failed: {e}")
        finally:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.button_box.setEnabled(True)

    async def _do_pull(self, host: str, port: int) -> None:
        """Perform sync pull operation."""
        self.status_label.setText(f"Pulling from {host}:{port}...")

        success, data = await self._client.sync_pull(host, port)
        if success:
            self._sync_result = data
            self.status_label.setText(f"Pulled {len(data)} bytes")
            QMessageBox.information(
                self,
                "Sync Complete",
                f"Successfully pulled {len(data)} bytes from {host}:{port}",
            )
            logger.log.info("Sync pull successful: %d bytes from %s:%d", len(data), host, port)
            self.accept()
        else:
            self.status_label.setText("Pull failed")
            QMessageBox.warning(self, "Sync Failed", f"Could not pull from {host}:{port}")

    async def _do_push(self, host: str, port: int) -> None:
        """Perform sync push operation."""
        if self._database is None:
            QMessageBox.warning(self, "Error", "No database available for push")
            return

        self.status_label.setText(f"Pushing to {host}:{port}...")

        data = json.dumps(self._database.to_dict()).encode("utf-8")
        success = await self._client.sync_push(host, port, data)

        if success:
            self.status_label.setText(f"Pushed {len(data)} bytes")
            QMessageBox.information(
                self,
                "Sync Complete",
                f"Successfully pushed {len(data)} bytes to {host}:{port}",
            )
            logger.log.info("Sync push successful: %d bytes to %s:%d", len(data), host, port)
            self.accept()
        else:
            self.status_label.setText("Push failed")
            QMessageBox.warning(self, "Sync Failed", f"Could not push to {host}:{port}")

    def get_host(self) -> str:
        """Get the entered host."""
        return self.host_edit.text().strip()

    def get_port(self) -> int:
        """Get the entered port."""
        return self.port_spin.value()

    def get_sync_result(self) -> bytes | None:
        """Get the pulled sync data (for pull operations)."""
        return self._sync_result
