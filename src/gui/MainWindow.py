"""MainWindow.py

This module implements the GUI for Todo.
"""

import os

from PyQt5 import QtGui, QtWidgets, QtPrintSupport
from PyQt5.QtCore import QPersistentModelIndex
from PyQt5.QtWidgets import QDesktopWidget

from src.core import core, json_helpers
from src.core.core import SyncOperations
from src.core.Logger import Logger
from src.gui.AddTodoDialog import AddTodoDialog
from src.gui.SyncDialog import SyncDialog

logger = Logger(__name__)


class CreateMainWindow(QtWidgets.QMainWindow):
    """This class implements the bulk of the gui functionality in PyTodo.

    It creates the main window, and helps to facilitate management of the
    list data base for the user.
    """

    def __init__(self, *args):
        """Create the window, make a table, fill table with todo data."""
        logger.log.info("Creating the main window")

        # create the window, set title and tooltip, resize and center window
        QtWidgets.QMainWindow.__init__(self)
        self.setWindowIcon(QtGui.QIcon("gui/icons/todo.png"))
        self.setWindowTitle("To-Do")
        self.setToolTip("Python3 + Qt5 = Happy <u>PyTodo</u> Programmer!")
        QtWidgets.QToolTip.setFont(QtGui.QFont("Helvetica", 10))
        self.resize(800, 500)
        self.center()

        # create our special font
        self.complete_font = QtGui.QFont("Helvetica", 10, QtGui.QFont.Bold)
        self.complete_font.setStrikeOut(True)

        # create our normal font
        self.normal_font = QtGui.QFont("Helvetica", 10, QtGui.QFont.Normal)
        self.normal_font.setStrikeOut(False)

        # create some actions
        printer = QtWidgets.QAction(QtGui.QIcon(), "Print", self)
        printer.setShortcut("Ctrl+P")
        printer.triggered.connect(self.print_list)

        export = QtWidgets.QAction(QtGui.QIcon(), "Export to Text File", self)
        export.setShortcut("Ctrl+E")
        export.triggered.connect(self.export_list)

        _quit = QtWidgets.QAction(QtGui.QIcon(), "Exit", self)
        _quit.setShortcut("Ctrl+Q")
        _quit.triggered.connect(self.close)

        # todo actions
        add = QtWidgets.QAction(QtGui.QIcon("gui/icons/plus.png"), "Add new todo", self)
        add.setShortcut("+")
        add.triggered.connect(self.add_todo)

        delete = QtWidgets.QAction(
            QtGui.QIcon("gui/icons/minus.png"), "Delete todo", self
        )
        delete.setShortcut("-")
        delete.triggered.connect(self.delete_todo)

        toggle = QtWidgets.QAction(
            QtGui.QIcon("gui/icons/todo.png"), "Toggle Status", self
        )
        toggle.setShortcut("%")
        toggle.triggered.connect(self.toggle_todo)

        # list actions
        list_add = QtWidgets.QAction(QtGui.QIcon(), "Add new list", self)
        list_add.setShortcut("Ctrl++")
        list_add.triggered.connect(self.add_list)

        list_delete = QtWidgets.QAction(QtGui.QIcon(), "Delete list", self)
        list_delete.setShortcut("Ctrl+-")
        list_delete.triggered.connect(self.delete_list)

        list_rename = QtWidgets.QAction(QtGui.QIcon(), "Rename list", self)
        list_rename.setShortcut("Ctrl+R")
        list_rename.triggered.connect(self.rename_list)

        list_switch = QtWidgets.QAction(QtGui.QIcon(), "Switch List", self)
        list_switch.setShortcut("Ctrl+L")
        list_switch.triggered.connect(self.switch_list)

        sync_pull = QtWidgets.QAction(
            QtGui.QIcon(), "Get lists from another computer", self
        )
        sync_pull.setShortcut("F6")
        sync_pull.triggered.connect(self.db_sync_pull)

        sync_push = QtWidgets.QAction(
            QtGui.QIcon(), "Send lists to another computer", self
        )
        sync_push.setShortcut("F7")
        sync_push.triggered.connect(self.db_sync_push)

        # net_server actions
        start_server = QtWidgets.QAction(QtGui.QIcon(), "Start the net_server", self)
        start_server.triggered.connect(self.db_start_server)

        stop_server = QtWidgets.QAction(QtGui.QIcon(), "Stop the net_server", self)
        stop_server.triggered.connect(self.db_stop_server)

        change_port = QtWidgets.QAction(QtGui.QIcon(), "Change net_server port", self)
        change_port.triggered.connect(self.db_server_port)

        change_bind_address = QtWidgets.QAction(
            QtGui.QIcon(), "Change net_server address", self
        )
        change_bind_address.triggered.connect(self.db_server_bind_address)

        # fanfare
        about = QtWidgets.QAction(QtGui.QIcon(), "About To-Do", self)
        about.triggered.connect(self.about_todo)

        about_qt = QtWidgets.QAction(QtGui.QIcon(), "About Qt", self)
        about_qt.triggered.connect(self.about_qt)

        # create a menu bar
        menu_bar = self.menuBar()
        main_menu = menu_bar.addMenu("&Menu")
        main_menu.addAction(printer)
        main_menu.addAction(export)
        main_menu.addAction(_quit)

        todo_menu = menu_bar.addMenu("&Todo")
        todo_menu.addAction(add)
        todo_menu.addAction(delete)
        todo_menu.addAction(toggle)

        list_menu = menu_bar.addMenu("&List")
        list_menu.addAction(list_add)
        list_menu.addAction(list_delete)
        list_menu.addAction(list_rename)
        list_menu.addAction(list_switch)

        sync_menu = menu_bar.addMenu("&Sync")
        sync_menu.addAction(sync_pull)
        sync_menu.addAction(sync_push)

        server_menu = menu_bar.addMenu("&Server")
        server_menu.addAction(start_server)
        server_menu.addAction(stop_server)
        server_menu.addAction(change_port)
        server_menu.addAction(change_bind_address)

        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(about)
        help_menu.addAction(about_qt)

        # create action toolbar
        toolbar = self.addToolBar("PyTodo Actions")
        toolbar.addAction(add)
        toolbar.addAction(delete)
        toolbar.addAction(toggle)
        toolbar.addAction(_quit)

        # create table, set it as central widget
        self.table = QtWidgets.QTableWidget(self)
        self.table.insertColumn(0)
        self.table.insertColumn(1)
        self.table.setHorizontalHeaderLabels(["Priority", "Reminder"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setToolTip("This is your <u>list</u> of todo's.")
        self.setCentralWidget(self.table)

        # create a status bar
        self.progressBar = QtWidgets.QProgressBar()
        self.statusBarLabel = QtWidgets.QLabel()
        self.statusBar = self.statusBar()
        self.statusBar.addPermanentWidget(self.progressBar)
        self.statusBar.addPermanentWidget(self.statusBarLabel, 1)

        # create a system tray icon
        self.trayIcon = QtWidgets.QSystemTrayIcon(
            QtGui.QIcon("gui/icons/todo.png"), self
        )
        self.trayIcon.activated.connect(self.tray_event)

        tray_exit = QtWidgets.QAction(QtGui.QIcon(), "Exit", self.trayIcon)
        tray_exit.triggered.connect(self.close)

        tray_menu = QtWidgets.QMenu("&PyTodo", self)
        tray_menu.addAction(tray_exit)
        self.trayIcon.setContextMenu(tray_menu)
        self.trayIcon.show()

        # create a printer if we can
        self.printer = QtPrintSupport.QPrinter()

        # show the window
        self.show()

        # read in any saved todo data
        self.read_todo_data()

        # draw the table
        self.refresh()

        logger.log.info("Main window created")

    def read_todo_data(self):
        """Read lists of todos from database."""
        if os.path.exists(core.lists_fn):
            self.update_progress_bar(0)
            self.update_status_bar("Reading in JSON data")
            result, msg = json_helpers.read_json_data()
            if not result:
                QtWidgets.QMessageBox.warning(self, "Read Error", msg)
                self.update_progress_bar()
                self.update_status_bar()
        else:
            return

        self.refresh()

    def write_todo_data(self):
        """Write todo lists to a JSON file."""
        if len(core.db.todo_lists.keys()) == 0:
            return

        self.update_progress_bar(0)
        self.update_status_bar("Writing JSON data")
        result, msg = json_helpers.write_json_data()
        if not result:
            QtWidgets.QMessageBox.warning(self, "Write Error", msg)
            self.update_progress_bar()
            self.update_status_bar()

    def db_sync_pull(self):
        """Pull lists from another net_server."""
        self.update_progress_bar(0)
        self.update_status_bar("Sync Pull")
        SyncDialog(SyncOperations["PULL_REQUEST"].name).exec_()
        self.write_todo_data()
        self.refresh()

    def db_sync_push(self):
        """Push lists to another computer."""
        self.update_progress_bar(0)
        self.update_status_bar("Waiting for input")
        SyncDialog(SyncOperations["PUSH_REQUEST"].name).exec_()
        self.refresh()

    def db_update_active_list(self, list_name):
        """Update the active list, and save the configuration."""
        core.options["active_list"] = list_name
        core.db.active_list = list_name
        result, msg = core.db.write_config()
        if not result:
            QtWidgets.QMessageBox.warning(self, "Write Error", msg)

    def db_start_server(self):
        """Start the database server."""
        if core.db.server_running():
            QtWidgets.QMessageBox.information(
                self, "Info", "The data base server is already running."
            )
        else:
            core.db.start_server()
            QtWidgets.QMessageBox.information(
                self, "Info", "The data base server was started."
            )
            self.refresh()

    def db_stop_server(self):
        """Stop the database server."""
        if not core.db.server_running():
            QtWidgets.QMessageBox.information(
                self, "Info", "The data base server is not running."
            )
        else:
            core.db.stop_server()
            QtWidgets.QMessageBox.information(
                self, "Info", "The data base server was stopped."
            )
            self.refresh()

    def db_server_port(self):
        """Change the port the database server listens too."""
        port, ok = QtWidgets.QInputDialog.getInt(self, "Change server port", "Port: ")
        if not ok:
            return

        if core.options["port"] == port:
            QtWidgets.QMessageBox.information(
                self, "Info", f"Server port is already set to {port}"
            )
        else:
            core.options["port"] = port
            if core.db.server_running():
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Restart Server?",
                    """The Server needs to be restarted for changes to take effect, would you like to do that now?""",
                    QtWidgets.QMessageBox.Yes,
                    QtWidgets.QMessageBox.No,
                )
                if reply == QtWidgets.QMessageBox.Yes:
                    core.db.restart_server()
                    core.db.write_config()
                    self.refresh()

    def db_server_bind_address(self):
        """Bind server to an address."""
        address, ok = QtWidgets.QInputDialog.getText(
            self, "Change server address", "Address: "
        )
        if not ok:
            return

        if core.options["address"] == address:
            QtWidgets.QMessageBox.information(
                self, "Info", f"Server address is already bound to {address}"
            )
        else:
            core.options["address"] = address
            if core.db.server_running():
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Restart Server?",
                    "The Server needs to be restarted for changes to take effect, would you like to do that now?",
                    QtWidgets.QMessageBox.Yes,
                    QtWidgets.QMessageBox.No,
                )
                if reply == QtWidgets.QMessageBox.Yes:
                    core.db.restart_server()
                    core.db.write_config()
                    self.refresh()

    def add_list(self):
        """Add a new list of todos."""
        self.update_progress_bar(0)
        self.update_status_bar("Waiting for input")

        list_name, ok = QtWidgets.QInputDialog.getText(
            self, "Add New List", "Enter a name for the new list: "
        )
        if ok:
            if len(list_name) == 0:
                self.update_progress_bar()
                self.update_status_bar()
                return

            if list_name not in core.db.todo_lists.keys():
                core.db.todo_lists[list_name] = []
                core.options["active_list"] = list_name
                core.db.active_list = list_name
                core.db.write_config()
                self.write_todo_data()
            else:
                QtWidgets.QMessageBox.warning(
                    self, "Name Exists", f'A list named "{list_name}" already exists.'
                )

        self.refresh()

    def delete_list(self):
        """Delete user selected list."""
        self.update_progress_bar(0)

        # if there is more than one list, ask user which one to delete
        if len(core.db.todo_lists.keys()) > 1:
            list_entry, ok = QtWidgets.QInputDialog.getItem(
                self, "Select List", "Todo Lists: ", list(core.db.todo_lists.keys())
            )
            if not ok:
                self.update_progress_bar()
                return

            core.db.todo_total -= len(core.db.todo_lists[list_entry])
            del core.db.todo_lists[list_entry]

            # use list switcher if there is still more than one list
            if len(core.db.todo_lists) > 1:
                self.switch_list()
            else:
                for list_entry in core.db.todo_lists.keys():
                    self.db_update_active_list(list_entry)
                    self.write_todo_data()
                    break
        else:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Confirm deletion",
                f'Really delete list "{core.db.active_list}"?',
                QtWidgets.QMessageBox.Yes,
                QtWidgets.QMessageBox.No,
            )
            if reply == QtWidgets.QMessageBox.No:
                self.update_progress_bar()
                return

            core.db.todo_total -= core.db.todo_count
            del core.db.todo_lists[core.db.active_list]
            core.db.list_count -= 1

            # reset database
            core.db.active_list = ""
            core.options["active_list"] = core.db.active_list
            core.db.todo_count = 0
            core.db.write_config()
            if os.path.exists(core.lists_fn):
                os.remove(core.lists_fn)

        self.refresh()

    def rename_list(self):
        """Rename the active list"""
        self.update_progress_bar(0)

        list_name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename todo list", "Enter new name:"
        )
        if ok:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Confirm rename",
                f"Are you sure you want to rename list {core.db.active_list} to {list_name}",
                QtWidgets.QMessageBox.Yes,
                QtWidgets.QMessageBox.No,
            )

            if reply == QtWidgets.QMessageBox.No:
                return

            core.db.todo_lists[list_name] = core.db.todo_lists[core.db.active_list]
            del core.db.todo_lists[core.db.active_list]
            core.db.active_list = core.db.todo_lists[list_name]
            core.db.write_config()
            self.write_todo_data()
            self.refresh()

    def switch_list(self):
        """Switch the active list.

        Present user with a drop down dialog of lists,
        set their choice as the active list.
        """
        self.update_progress_bar(0)

        if len(core.db.todo_lists.keys()) < 1:
            return

        list_entry, ok = QtWidgets.QInputDialog.getItem(
            self, "Select List", "Todo Lists: ", list(core.db.todo_lists.keys())
        )
        if ok:
            self.db_update_active_list(list_entry)
            self.write_todo_data()

        self.refresh()

    def export_list(self, fn=None):
        """Export active list to text file."""
        self.update_progress_bar(0)

        if core.db.todo_count == 0:
            return

        if not fn:
            # prompt user for fn
            self.update_status_bar("Waiting for input")
            fn, ok = QtWidgets.QInputDialog.getText(
                self, "Save list to text file", "Enter name of file to write text as:"
            )
            if not ok:
                return

        self.update_status_bar(f"Exporting to text file {fn}.")
        core.db.write_text_file(fn)
        self.update_status_bar(f"finished exporting to {fn}.")
        self.update_progress_bar()

    def print_list(self):
        """Print the active list."""
        self.update_progress_bar(0)

        # check that we have a printer first
        if not self.printer:
            self.update_progress_bar()
            return

        tmp_fn = ".todo_printer.tmp"

        accept = QtPrintSupport.QPrintDialog(self.printer).exec_()
        if accept:
            self.update_status_bar("Printing")

            # Write formatted list to temporary file
            self.export_list(tmp_fn)
            if not os.path.exists(tmp_fn):
                return

            # Read in formatted list as one big string
            string = ""
            with open(tmp_fn, encoding="utf-8") as f:
                for line in f:
                    string += line

            # Remove temporary file
            os.remove(tmp_fn)

            # Open string as a a QTextDocument and then print it
            doc = QtGui.QTextDocument(string)
            doc.print_(self.printer)

        self.update_progress_bar()
        self.update_status_bar("finished printing.")

    def add_todo(self):
        """Add a new todo to active list."""
        self.update_progress_bar(0)

        if not core.db.active_list:
            if core.db.list_count == 0:
                QtWidgets.QMessageBox.information(
                    self,
                    "No list",
                    "You need to create a list before you add a reminder",
                )
                self.update_progress_bar()
                self.update_status_bar()
                return self.add_list()
            else:
                # ask the user if they would like to switch to an existing list
                self.update_status_bar("Waiting for input")
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Set an active list",
                    "There is currently no active list set, but lists do exist, would you like to switch to one of them?",
                    QtWidgets.QMessageBox.Yes,
                    QtWidgets.QMessageBox.No,
                )

                # check the user response
                if reply == QtWidgets.QMessageBox.Yes:
                    self.switch_list()
                else:
                    return

        # Get a new todo from user
        AddTodoDialog().exec_()

        self.refresh()

    def delete_todo(self):
        """Delete the currently selected todo."""
        self.update_progress_bar(0)

        if self.table.selectionModel().hasSelection():
            indices = [
                QPersistentModelIndex(index)
                for index in self.table.selectionModel().selectedIndexes()
            ]
            for index in indices:
                item = self.table.cellWidget(index.row(), 1)
                text = item.text()
                todo = core.db.todo_index(text)
                del core.db.todo_lists[core.db.active_list][todo]
                core.db.todo_count -= 1
                core.db.todo_total -= 1
                self.write_todo_data()
                self.table.removeRow(index.row())
            self.refresh()
        else:
            QtWidgets.QMessageBox.warning(
                self, "Delete To-Do", "No reminders selected."
            )

    def toggle_todo(self):
        """Toggle a todo complete / incomplete."""
        self.update_progress_bar(0)

        for index in self.table.selectedIndexes():
            item = self.table.cellWidget(index.row(), 1)
            text = item.text()
            todo = core.db.todo_index(text)
            if not core.db.todo_lists[core.db.active_list][todo]["complete"]:
                core.db.todo_lists[core.db.active_list][todo]["complete"] = True
            else:
                core.db.todo_lists[core.db.active_list][todo]["complete"] = False
                self.write_todo_data()
            self.refresh()

    def change_priority(self):
        """Change a todo's priority."""
        for index in self.table.selectedIndexes():
            item_p = self.table.cellWidget(index.row(), 0)
            item_r = self.table.cellWidget(index.row(), 1)

            text = item_p.currentText()
            if text == "Low":
                priority = 3
            elif text == "Normal":
                priority = 2
            else:
                priority = 1

            reminder = item_r.text()
            todo = core.db.todo_index(reminder)
            core.db.todo_lists[core.db.active_list][todo]["priority"] = priority
            self.write_todo_data()
            self.refresh()

    def edit_reminder(self):
        """Edit the reminder of a todo."""
        for index in self.table.selectedIndexes():
            item = self.table.cellWidget(index.row(), 1)
            new_text = item.text()
            core.db.todo_lists[core.db.active_list][index.row()]["reminder"] = new_text
            self.write_todo_data()

    def about_todo(self):
        """Display an about message box with Program/Author information."""
        text = """<b><u>To-Do v0.1.1</u></b>
        <br><br>To-Do list program that works with multiple To-Do
        lists locally and over a network.
        <br><br>License: <a href="http://www.fsf.org/licenses/gpl.html">GPLv3</a>
        <br><br><b>Copyright (C) 2020 Michael Berry</b>
        """
        QtWidgets.QMessageBox.about(self, "About PyTodo", text)

    def about_qt(self):
        """Display information about Qt."""
        QtWidgets.QMessageBox.aboutQt(self, "About Qt")

    def center(self):
        """Place the main window in the center of the screen."""
        qt_rectangle = self.frameGeometry()
        center_point = QDesktopWidget().availableGeometry().center()
        qt_rectangle.moveCenter(center_point)
        self.move(qt_rectangle.topLeft())

    def update_progress_bar(self, value=None):
        """Update the progress bar.

        Maximum value should be set to the total todo count,
        while value should be the number of completed todos.
        This makes the progress bar show the total percentage
        of completed todos.
        """
        if value is None:
            return

        i = 0
        for list_name in core.db.todo_lists:
            for todo in core.db.todo_lists[list_name]:
                if todo["complete"]:
                    i += 1
        value = i

        self.progressBar.reset()
        self.progressBar.setMaximum(core.db.todo_total)
        self.progressBar.setValue(value)

    def update_status_bar(self, msg="Ready"):
        """Update the status bar, display some statistics."""
        if core.db.server_running():
            server_status = f"Up on {core.options['address']}: {core.options['port']}"
        else:
            server_status = "Down"

        # create our status bar text
        text = f"Lists: {core.db.list_count}  Shown: {core.db.active_list}  Todos: {core.db.todo_count} of {core.db.todo_total}  Status: {msg}  Server: {server_status}"

        self.statusBarLabel.setText(text)

    def refresh(self):
        """Redraw the table and update the progress and status bars."""
        self.update_status_bar("Redrawing table")

        # clear the table
        self.table.setRowCount(0)

        # set the table headers
        self.table.setHorizontalHeaderLabels(["Priority", "Reminder"])

        # make sure we have a valid active list
        if core.db.active_list not in core.db.todo_lists:
            self.update_status_bar()
            return

        # add each todo in the list to the table, show a progress bar
        i = 0
        core.db.sort_active_list()

        # update the progress bar
        self.update_progress_bar(0)

        for todo in core.db.todo_lists[core.db.active_list]:
            # create priority table item
            item_p = QtWidgets.QComboBox(self)
            item_p.addItems(["Low", "Normal", "High"])
            item_p.currentIndexChanged.connect(self.change_priority)
            if todo["priority"] == 1:
                item_p.setCurrentIndex(2)
            elif todo["priority"] == 2:
                item_p.setCurrentIndex(1)
            else:
                item_p.setCurrentIndex(0)

            # create reminder table item
            item_r = QtWidgets.QLineEdit(todo["reminder"])
            item_r.returnPressed.connect(self.edit_reminder)

            # set the font
            if todo["complete"] is True:
                item_r.setFont(self.complete_font)
            else:
                item_r.setFont(self.normal_font)

            # put the items in the table
            row_count = self.table.rowCount()
            assert row_count == i
            self.table.insertRow(i)
            self.table.setCellWidget(i, 0, item_p)
            self.table.setCellWidget(i, 1, item_r)
            i += 1

        # update the database todo_count
        core.db.todo_count = len(core.db.todo_lists[core.db.active_list])
        core.db.list_count = len(core.db.todo_lists.keys())

        # update progress and status bars
        self.update_progress_bar()
        self.update_status_bar()

    def tray_event(self, reason):
        """Hide the main window when the system tray icon is clicked."""
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()

    def closeEvent(self, event):
        """Take care of clean up details."""
        # save configuration
        result, msg = core.db.write_config()
        if not result:
            QtWidgets.QMessageBox.warning(self, "Write Error", msg)

        # save todo lists
        self.write_todo_data()

        # shutdown database net_server
        if core.db.server_running():
            core.db.net_server.shutdown()

        # hide the tray icon
        self.trayIcon.hide()

        logger.log.info("Closing main window, quitting application")

        # close the window
        event.accept()
