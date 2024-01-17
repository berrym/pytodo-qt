from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QProgressDialog

from src.core.Logger import Logger


logger = Logger(__name__)


class SyncProgressDialog(QProgressDialog):
    """Synchronize lists with remotes."""
    def __init__(self, header_size):
        """Create a simple dialog.

        Display a progress bar for sync operations.
        """
        logger.log.info("Creating a Sync dialog progress bar")

        super().__init__("Sync To-Do lists", "Abort sync", 0, header_size, None)

        self.setMinimumWidth(375)
        self.setWindowModality(Qt.WindowModal)
        self.setRange(0, header_size)
        self.setValue(0)
        self.exec()

        # create a vertical box layout
        # v_box = QtWidgets.QVBoxLayout()
        # v_box.addWidget(self.progress)

        # set layout and window title
        # self.setLayout(v_box)
        # self.setWindowTitle(f"Sync Progress")
        # self.setMinimumWidth(350)

    # def set_value(self, i):
    #     self.progress.setValue(i)