"""SyncDialog.py

Simple dialog to collect information needed to perform a sync operation.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QMessageBox,
)
from PyQt6.QtGui import QIntValidator

from ..core import error_on_none_db, settings
from ..core.Logger import Logger
from ..net.sync_operations import sync_operations


logger = Logger(__name__)


class SyncDialog(QDialog):
    """Synchronize lists with remotes."""

    def __init__(self, operation=None):
        """Create a simple dialog.

        Get information about a remote host to perform a sync operation with.
        """
        logger.log.info("Creating a Sync dialog")

        super().__init__()

        self.operation = operation

        # address
        address_label = QLabel("Host Address", self)
        self.address_field = QLineEdit(self)

        # port
        port_label = QLabel("Port", self)
        self.port_field = QLineEdit(self)
        self.port_field.setText(str(settings.options["port"]))
        self.port_field.setValidator(QIntValidator())

        # add button
        self.get_button = QPushButton("Synchronize", self)
        self.get_button.clicked.connect(self.get_host)

        # create a vertical box layout
        v_box = QVBoxLayout()
        v_box.addWidget(address_label)
        v_box.addWidget(self.address_field)
        v_box.addWidget(port_label)
        v_box.addWidget(self.port_field)
        v_box.addWidget(self.get_button)

        # set layout and window title
        self.setLayout(v_box)
        self.setWindowTitle(f"Sync {operation}")
        self.setMinimumWidth(350)

        logger.log.info("Sync dialog created")

    @error_on_none_db
    def get_host(self, *args, **kwargs):
        """Get host information."""
        address = self.address_field.text()
        if address == "":
            QMessageBox.information(self, "Empty address", "Address cannot be empty")
            return

        # get remote port
        port = self.port_field.text()
        if port == "":
            QMessageBox.information(self, "Empty port", "Port cannot be empty")
            return

        port = int(port)

        logger.log.info("Got host information for sync operation")
        if self.operation == sync_operations["PULL_REQUEST"].name:
            # try the pull, inform user of the results
            result, msg = settings.DB.sync_pull((address, port))
            logger.log.info(msg)
            if not result:
                return
        elif self.operation == sync_operations["PUSH_REQUEST"].name:
            # temporarily enable pulling for the push
            pull_ok = settings.options["pull"]
            if not pull_ok:
                settings.options["pull"] = True

            # try the push, inform user of results
            logger.log.info("Sending a sync push request to %s:%d", address, port)
            result, msg = settings.DB.sync_push((address, port))
            logger.log.info(msg)
            if not pull_ok:
                settings.options["pull"] = False

            if not result:
                return

        self.accept()
