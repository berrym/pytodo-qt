"""sync.py

Dialog for synchronization operations.
"""

from __future__ import annotations

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

from ...core.config import get_config
from ...core.logger import Logger

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class SyncDialog(QDialog):
    """Dialog for synchronization operations."""

    def __init__(self, parent=None, operation: str = "pull"):
        """Initialize sync dialog.

        Args:
            parent: Parent widget
            operation: "pull" or "push"
        """
        super().__init__(parent)
        self._operation = operation

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

    def _on_sync(self) -> None:
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

        # For now, just show a message - actual sync will be integrated later
        # In production, this would use AsyncClient
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)

        if self._operation == "pull":
            self.status_label.setText(f"Pull from {host}:{port} would happen here")
        else:
            self.status_label.setText(f"Push to {host}:{port} would happen here")

        self.button_box.setEnabled(True)

        QMessageBox.information(
            self,
            "Sync",
            f"Sync {self._operation} to {host}:{port}\n\n"
            "Note: Full async sync integration pending.",
        )

        logger.log.info("Sync %s to %s:%d initiated", self._operation, host, port)
        self.accept()

    def get_host(self) -> str:
        """Get the entered host."""
        return self.host_edit.text().strip()

    def get_port(self) -> int:
        """Get the entered port."""
        return self.port_spin.value()
