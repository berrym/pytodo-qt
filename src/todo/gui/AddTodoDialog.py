"""AddTodoDialog.py

Simple dialog to create a to-do.
"""

from PyQt5 import QtWidgets

from todo.core import error_on_none_db, settings
from todo.core.Logger import Logger


logger = Logger(__name__)


class AddTodoDialog(QtWidgets.QDialog):
    """Create a new to-do."""

    def __init__(self):
        """Create a simple dialog.

        Get enough information to create a new to-do.
        """
        logger.log.info("Creating an add to-do dialog")

        super().__init__()

        # reminder
        reminder_label = QtWidgets.QLabel("Reminder", self)
        self.reminder_field = QtWidgets.QLineEdit(self)

        # priority
        priority_label = QtWidgets.QLabel("Priority", self)
        self.priority_field = QtWidgets.QComboBox(self)
        self.priority_field.addItems(["Low", "Normal", "High"])

        # add button
        self.add_button = QtWidgets.QPushButton("Add to-do", self)
        self.add_button.clicked.connect(self.get_todo)

        # create a vertical box layout
        v_box = QtWidgets.QVBoxLayout()
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
    def get_todo(self):
        """Get to-do information and append it to the current list."""
        reminder = self.reminder_field.text()
        if reminder == "":
            QtWidgets.QMessageBox.information(
                self, "Empty reminder", "Reminder cannot be empty"
            )
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
        if settings.db.todo_lists is not None and settings.db.active_list is not None:
            settings.db.todo_lists[settings.db.active_list].append(todo)
            settings.db.todo_count += 1
            settings.db.todo_total += 1
        else:
            logger.log.exception(
                "Error: settings.db.todo_list or setting.db.active list does not exist, exiting"
            )

        logger.log.info(f"New to-do created: {todo}")

        self.accept()
