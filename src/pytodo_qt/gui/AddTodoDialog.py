"""AddTodoDialog.py

Simple dialog to create a to-do.
"""

from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QVBoxLayout,
    QMessageBox,
)

from ..core import error_on_none_db, settings
from ..core.Logger import Logger


logger = Logger(__name__)


class AddTodoDialog(QDialog):
    """Create a new to-do."""

    def __init__(self):
        """Create a simple dialog.

        Get enough information to create a new to-do.
        """
        logger.log.info("Creating an add to-do dialog")

        super().__init__()

        # reminder
        reminder_label = QLabel("Reminder", self)
        self.reminder_field = QLineEdit(self)

        # priority
        priority_label = QLabel("Priority", self)
        self.priority_field = QComboBox(self)
        self.priority_field.addItems(["Low", "Normal", "High"])

        # add button
        self.add_button = QPushButton("Add to-do", self)
        self.add_button.clicked.connect(self.get_todo)

        # create a vertical box layout
        v_box = QVBoxLayout()
        v_box.addWidget(reminder_label)
        v_box.addWidget(self.reminder_field)
        v_box.addWidget(priority_label)
        v_box.addWidget(self.priority_field)
        v_box.addWidget(self.add_button)

        # set layout and window title
        self.setLayout(v_box)
        self.setWindowTitle("Add New to-do")
        self.setMinimumWidth(500)

        logger.log.info("Add to-do dialog created")

    @error_on_none_db
    def get_todo(self, *args, **kwargs):
        """Get to-do information and append it to the current list."""
        reminder = self.reminder_field.text()
        if reminder == "":
            QMessageBox.information(self, "Empty reminder", "Reminder cannot be empty")
            return

        # get to-do information
        todo = {"complete": False, "reminder": reminder}
        priority = self.priority_field.currentText()
        if priority == "High":
            todo["priority"] = 1
        elif priority == "Normal":
            todo["priority"] = 2
        else:
            todo["priority"] = 3

        # update the database
        if settings.DB.todo_lists is not None and settings.DB.active_list is not None:
            settings.DB.todo_lists[settings.DB.active_list].append(todo)
            settings.DB.todo_count += 1
            settings.DB.todo_total += 1
        else:
            logger.log.exception(
                "Error: settings.db.todo_list or setting.db.active list does not exist, exiting"
            )

        logger.log.info("New to-do created: %s", todo)

        self.accept()
