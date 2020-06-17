"""AddTodoDialog.py

Simple dialog to create a todo.
"""

from PyQt5 import QtWidgets

from core import core
from core.Logger import Logger

logger = Logger(__name__)


class AddTodoDialog(QtWidgets.QDialog):
    """Create a new todo."""

    def __init__(self):
        """Create a simple dialog.

        Get enough information to create a new todo.
        """
        logger.log.info("Creating an add todo dialog")

        super().__init__()

        # reminder
        reminder_label = QtWidgets.QLabel("Reminder", self)
        self.reminder_field = QtWidgets.QLineEdit(self)

        # priority
        priority_label = QtWidgets.QLabel("Priority", self)
        self.priority_field = QtWidgets.QComboBox(self)
        self.priority_field.addItems(["Low", "Normal", "High"])

        # add button
        self.add_button = QtWidgets.QPushButton("Add Todo", self)
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
        self.setWindowTitle("Add New Todo")
        self.setMinimumWidth(500)

        logger.log.info("Add todo dialog created")

    def get_todo(self):
        """Get todo information and append it to the current list."""
        reminder = self.reminder_field.text()
        if reminder == "":
            QtWidgets.QMessageBox.information(
                self, "Empty reminder", "Reminder cannot be empty"
            )
            return

        # get todo information
        todo = {"complete": False, "reminder": reminder}
        priority = self.priority_field.currentText()
        if priority == "High":
            todo["priority"] = 1
        elif priority == "Normal":
            todo["priority"] = 2
        else:
            todo["priority"] = 3

        # update the database
        core.db.todo_lists[core.db.active_list].append(todo)
        core.db.todo_count += 1
        core.db.todo_total += 1

        logger.log.info(f"New todo created: {todo}")

        self.accept()
