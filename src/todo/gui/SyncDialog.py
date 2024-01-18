"""SyncDialog.py

Simple dialog to collect information needed to perform a sync operation.
"""

import sys

from PyQt5 import QtGui, QtWidgets

from todo.core import error_on_none_db, settings
from todo.core.Logger import Logger
from todo.net.sync_operations import sync_operations


logger = Logger(__name__)


class SyncDialog(QtWidgets.QDialog):
    """Synchronize lists with remotes."""

    def __init__(self, operation=None):
        """Create a simple dialog.

        Get information about a remote host to perform a sync operation with.
        """
        logger.log.info("Creating a Sync dialog")

        super().__init__()

        self.operation = operation

        # address
        address_label = QtWidgets.QLabel("Host Address", self)
        self.address_field = QtWidgets.QLineEdit(self)

        # port
        port_label = QtWidgets.QLabel("Port", self)
        self.port_field = QtWidgets.QLineEdit(self)
        self.port_field.setText(str(settings.options["port"]))
        self.port_field.setValidator(QtGui.QIntValidator())

        # add button
        self.get_button = QtWidgets.QPushButton("Synchronize", self)
        self.get_button.clicked.connect(self.get_host)

        # create a vertical box layout
        v_box = QtWidgets.QVBoxLayout()
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
            QtWidgets.QMessageBox.information(
                self, "Empty address", "Address cannot be empty"
            )
            return

        # get remote port
        port = self.port_field.text()
        if port == "":
            QtWidgets.QMessageBox.information(
                self, "Empty port", "Port cannot be empty"
            )
            return

        port = int(port)

        logger.log.info("Got host information for sync operation")
        if self.operation == sync_operations["PULL_REQUEST"].name:
            # try the pull, inform user of the results
            result, msg = settings.db.sync_pull((address, port))
            QtWidgets.QMessageBox.information(self, "Sync Pull", msg)
            if not result:
                return
        elif self.operation == sync_operations["PUSH_REQUEST"].name:
            # temporarily enable pulling for the push
            pull_ok = settings.options["pull"]
            if not pull_ok:
                settings.options["pull"] = True

            # try the push, inform user of results
            result, msg = settings.db.sync_push((address, port))
            QtWidgets.QMessageBox.information(self, "Sync Push", msg)
            if not pull_ok:
                settings.options["pull"] = False

            if not result:
                return

        self.accept()
