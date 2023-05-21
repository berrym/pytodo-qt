"""AddTodoDialog.py

Simple dialog to create a to-do.
"""

from PyQt5 import QtWidgets

from core import defaults
from core.Logger import Logger
from core.TodoDatabase import Todo

logger = Logger(__name__)


class AddTodoDialog(QtWidgets.QDialog):
    """Create a new to-do."""

    def __init__(self):
        """Create a simple dialog.

        Get enough information to create a new to-do.
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
        """Get to-do information and append it to the current list."""
        reminder = self.reminder_field.text()
        if not reminder:
            QtWidgets.QMessageBox.information(
                self, "Empty reminder", "Reminder cannot be empty"
            )
            return

        # get to-do information
        priority = self.priority_field.currentText()
        match priority:
            case "High":
                priority = 1
            case "Normal":
                priority = 2
            case _:
                priority = 3
        complete = False
        todo = Todo(reminder=reminder, priority=priority, complete=complete)
        # update the database
        defaults.db.todo_lists[defaults.db.active_list]["todo_list"].append(todo)
        defaults.db.todo_lists[defaults.db.active_list]["todo_count"] += 1
        defaults.db.todo_total += 1

        logger.log.info(f"New todo created: {todo}")

        self.accept()
