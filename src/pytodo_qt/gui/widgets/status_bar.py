"""status_bar.py

Enhanced status bar widget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QLabel, QProgressBar, QStatusBar, QWidget

from ...core.logger import Logger

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class StatusBarWidget(QStatusBar):
    """Enhanced status bar with progress and statistics."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Progress bar for completion
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(150)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p% complete")

        # Statistics labels
        self.list_count_label = QLabel()
        self.item_count_label = QLabel()
        self.status_label = QLabel()
        self.server_status_label = QLabel()

        # Add widgets
        self.addWidget(self.progress_bar)
        self.addWidget(self._create_separator())
        self.addWidget(self.list_count_label)
        self.addWidget(self._create_separator())
        self.addWidget(self.item_count_label)
        self.addPermanentWidget(self.server_status_label)
        self.addPermanentWidget(self._create_separator())
        self.addPermanentWidget(self.status_label)

        # Initialize
        self.update_stats(0, 0, 0, 0)
        self.set_status("Ready")
        self.set_server_status(False, "", 0)

    def _create_separator(self) -> QWidget:
        """Create a visual separator."""
        separator = QWidget()
        separator.setFixedWidth(10)
        return separator

    def update_stats(
        self,
        list_count: int,
        item_count: int,
        completed_count: int,
        total_items: int,
    ) -> None:
        """Update statistics display."""
        self.list_count_label.setText(f"Lists: {list_count}")
        self.item_count_label.setText(f"Items: {item_count}/{total_items}")

        # Update progress bar
        if total_items > 0:
            self.progress_bar.setMaximum(total_items)
            self.progress_bar.setValue(completed_count)
        else:
            self.progress_bar.setMaximum(1)
            self.progress_bar.setValue(0)

    def set_status(self, message: str) -> None:
        """Set the status message."""
        self.status_label.setText(message)

    def set_server_status(self, running: bool, address: str = "", port: int = 0) -> None:
        """Set the server status display."""
        if running:
            self.server_status_label.setText(f"Server: {address}:{port}")
            self.server_status_label.setStyleSheet("color: green;")
        else:
            self.server_status_label.setText("Server: Off")
            self.server_status_label.setStyleSheet("color: gray;")

    def show_message(self, message: str, timeout: int = 3000) -> None:
        """Show a temporary message."""
        self.showMessage(message, timeout)
