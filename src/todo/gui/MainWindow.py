"""MainWindow.py

This module implements the GUI for To-Do.
"""

import os
import sys

from PyQt5 import QtCore, QtGui, QtWidgets, QtPrintSupport

from todo.core import error_on_none_db, settings, json_helpers
from todo.core.Logger import Logger
from todo.gui.AddTodoDialog import AddTodoDialog
from todo.gui.SyncDialog import SyncDialog
from todo.net.sync_operations import sync_operations


logger = Logger(__name__)


class CreateMainWindow(QtWidgets.QMainWindow):
    """This class implements the bulk of the gui functionality in To-Do.

    It creates the main window, and helps to facilitate management of the
    list database for the user.
    """

    def __init__(self, *args):
        """Create the window, make a table, fill table with to-do data."""
        logger.log.info("Creating the main window")

        # create the window, set title and tooltip, resize and center window
        QtWidgets.QMainWindow.__init__(self)
        self.setWindowIcon(QtGui.QIcon("gui/icons/todo.png"))
        self.setWindowTitle("To-Do")
        self.setToolTip("Python3 + Qt5 = Happy <u>To-Do</u> Programmer!")
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

        # to-do actions
        add = QtWidgets.QAction(
            QtGui.QIcon("gui/icons/plus.png"), "Add new to-do", self
        )
        add.setShortcut("+")
        add.triggered.connect(self.add_todo)

        delete = QtWidgets.QAction(
            QtGui.QIcon("gui/icons/minus.png"), "Delete to-do", self
        )
        delete.setShortcut("-")
        delete.triggered.connect(self.delete_todo)

        toggle = QtWidgets.QAction(
            QtGui.QIcon("gui/icons/todo.png"), "Toggle to-do Status", self
        )
        toggle.setShortcut("%")
        toggle.triggered.connect(self.toggle_todo)

        # list actions
        list_add = QtWidgets.QAction(QtGui.QIcon(), "Add new list", self)
        list_add.setShortcut("Ctrl++")
        list_add.triggered.connect(self.add_list)

        list_delete = QtWidgets.QAction(
            QtGui.QIcon("gui/icons/minus.png"), "Delete list", self
        )

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

        # network server actions
        start_server = QtWidgets.QAction(
            QtGui.QIcon(), "Start the network server", self
        )
        start_server.triggered.connect(self.db_start_server)

        stop_server = QtWidgets.QAction(QtGui.QIcon(), "Stop the network server", self)
        stop_server.triggered.connect(self.db_stop_server)

        change_port = QtWidgets.QAction(
            QtGui.QIcon(), "Change network server port", self
        )
        change_port.triggered.connect(self.db_server_port)

        change_bind_address = QtWidgets.QAction(
            QtGui.QIcon(), "Change network server address", self
        )
        change_bind_address.triggered.connect(self.db_server_bind_address)

        # fanfare
        about = QtWidgets.QAction(QtGui.QIcon(), "About To-Do", self)
        about.triggered.connect(self.about_todo)

        about_qt = QtWidgets.QAction(QtGui.QIcon(), "About Qt", self)
        about_qt.triggered.connect(self.about_qt)

        # create a menu bar
        menu_bar = self.menuBar()
        if menu_bar is not None:
            main_menu = menu_bar.addMenu("&Menu")
            if main_menu is not None:
                main_menu.addAction(printer)
                main_menu.addAction(export)
                main_menu.addAction(_quit)
            else:
                msg = "Could not populate main menu, exiting"
                QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
                logger.log.exception(msg)
        else:
            msg = "Could not create menu bar, exiting"
            QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

        if menu_bar is not None:
            todo_menu = menu_bar.addMenu("&To-Do")
            if todo_menu is not None:
                todo_menu.addAction(add)
                todo_menu.addAction(delete)
                todo_menu.addAction(toggle)
            else:
                msg = "Could not populate to-do menu, exiting"
                QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
                logger.log.exception(msg)
                sys.exit(1)
        else:
            msg = "Menu bar error, exiting"
            QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

        if menu_bar is not None:
            list_menu = menu_bar.addMenu("&List")
            if list_menu is not None:
                list_menu.addAction(list_add)
                list_menu.addAction(list_delete)
                list_menu.addAction(list_rename)
                list_menu.addAction(list_switch)
            else:
                msg = "Could not populate list menu, exiting"
                QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
                logger.log.exception(msg)
                sys.exit(1)
        else:
            msg = "Menu bar error, exiting"
            QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

        if menu_bar is not None:
            sync_menu = menu_bar.addMenu("&Sync")
            if sync_menu is not None:
                sync_menu.addAction(sync_pull)
                sync_menu.addAction(sync_push)
            else:
                msg = "Could not populate sync menu, exiting"
                QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
                logger.log.exception(msg)
                sys.exit(1)
        else:
            msg = "Menu bar error, exiting"
            QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

        if menu_bar is not None:
            server_menu = menu_bar.addMenu("&Server")
            if server_menu is not None:
                server_menu.addAction(start_server)
                server_menu.addAction(stop_server)
                server_menu.addAction(change_port)
                server_menu.addAction(change_bind_address)
            else:
                msg = "Could not populate server menu, exiting"
                QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
                logger.log.exception(msg)
                sys.exit(1)
        else:
            msg = "Menu bar error, exiting"
            QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

        if menu_bar is not None:
            help_menu = menu_bar.addMenu("&Help")
            if help_menu is not None:
                help_menu.addAction(about)
                help_menu.addAction(about_qt)
            else:
                msg = "Could not populate help menu, exiting"
                QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
                logger.log.exception(msg)
                sys.exit(1)
        else:
            msg = "Menu bar error, exiting"
            QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

        # create action toolbar
        toolbar = self.addToolBar("To-Do Actions")
        if toolbar is not None:
            toolbar.addAction(add)
            toolbar.addAction(delete)
            toolbar.addAction(toggle)
            toolbar.addAction(_quit)
        else:
            msg = "Could not create toolbar, exiting"
            QtWidgets.QMessageBox.warning(self, "Creation Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

        # create table, set it as central widget
        self.table = QtWidgets.QTableWidget(self)
        if self.table is not None:
            self.table.insertColumn(0)
            self.table.insertColumn(1)
            self.table.setHorizontalHeaderLabels(["Priority", "Reminder"])
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.setToolTip("This is your <u>list</u> of to-do's.")
            self.setCentralWidget(self.table)
        else:
            msg = "Could not create to-do list table, exiting"
            QtWidgets.QMessageBox.critical(self, "Creation Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

        # create a status bar
        self.progressBar = QtWidgets.QProgressBar()
        self.statusBarLabel = QtWidgets.QLabel()
        self.statusBar = self.statusBar()
        if self.statusBar is not None:
            self.statusBar.addPermanentWidget(self.progressBar)
            self.statusBar.addPermanentWidget(self.statusBarLabel, 1)
        else:
            msg = "Could not create status bar, exiting"
            QtWidgets.QMessageBox.critical(self, "Creation Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

        # create a system tray icon
        self.tray_icon = QtWidgets.QSystemTrayIcon(
            QtGui.QIcon("gui/icons/todo.png"), self
        )
        self.tray_icon.activated.connect(self.tray_event)

        tray_exit = QtWidgets.QAction(QtGui.QIcon(), "Exit", self.tray_icon)
        tray_exit.triggered.connect(self.close)

        tray_menu = QtWidgets.QMenu("&To-Do", self)
        if tray_menu is not None:
            tray_menu.addAction(tray_exit)
            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.show()
        else:
            msg = "Could not create status tray menu, exiting"
            QtWidgets.QMessageBox.critical(self, "Creation Error", msg)
            logger.log.exception(msg)
            sys.exit(1)

        # create a printer if we can
        self.printer = QtPrintSupport.QPrinter()

        # show the window
        self.show()

        # read in any saved to-do data
        self.read_todo_data()

        # draw the table
        self.refresh()

        logger.log.info("Main window created")

    def read_todo_data(self):
        """Read lists of to-dos from database."""
        if os.path.exists(settings.lists_fn):
            self.update_progress_bar(0)
            self.update_status_bar("Reading in JSON data")
            result, msg = json_helpers.read_json_data()
            if not result:
                QtWidgets.QMessageBox.warning(self, "Read Error", str(msg))
                self.update_progress_bar()
                self.update_status_bar()
        else:
            return

        self.refresh()

    @error_on_none_db
    def write_todo_data(self, *args, **kwargs):
        """Write to-do lists to a JSON file."""
        if len(settings.db.todo_lists.keys()) == 0:
            msg = "No to-do information, aborting write"
            QtWidgets.QMessageBox.warning(self, "Write Error", msg)
            return

        self.update_progress_bar(0)
        self.update_status_bar("Writing JSON data")

        result, msg = json_helpers.write_json_data()
        if not result:
            QtWidgets.QMessageBox.warning(self, "Write Error", msg)
            self.update_progress_bar()
            self.update_status_bar()

    def db_sync_pull(self):
        """Pull lists from another network server."""
        self.update_progress_bar(0)
        self.update_status_bar("Sync Pull")
        SyncDialog(sync_operations["PULL_REQUEST"].name).exec()
        self.write_todo_data()
        self.refresh()

    def db_sync_push(self):
        """Push lists to another computer."""
        self.update_progress_bar(0)
        self.update_status_bar("Waiting for input")
        SyncDialog(sync_operations["PUSH_REQUEST"].name).exec()
        self.refresh()

    @error_on_none_db
    def db_update_active_list(self, list_name, *args, **kwargs):
        """Update the active list, and save the configuration."""
        settings.options["active_list"] = list_name

        settings.db.active_list = list_name
        result, msg = settings.db.write_config()
        if not result:
            QtWidgets.QMessageBox.critical(self, "Write Error", msg)
            sys.exit(1)
        else:
            QtWidgets.QMessageBox.information(self, "Write Success", msg)

    @error_on_none_db
    def db_start_server(self, *args, **kwargs):
        """Start the database server."""
        if settings.db.server_running():
            QtWidgets.QMessageBox.information(
                self, "Info", "The database server is already running."
            )
        else:
            settings.db.start_server()
            QtWidgets.QMessageBox.information(
                self, "Info", "The database server was started."
            )
            self.refresh()

    @error_on_none_db
    def db_stop_server(self, *args, **kwargs):
        """Stop the database server."""
        if not settings.db.server_running():
            QtWidgets.QMessageBox.information(
                self, "Info", "The database server is not running."
            )
        else:
            settings.db.stop_server()
            QtWidgets.QMessageBox.information(
                self, "Info", "The database server was stopped."
            )
            self.refresh()

    @error_on_none_db
    def db_server_port(self, *args, **kwargs):
        """Change the port the database server listens too."""
        port, ok = QtWidgets.QInputDialog.getInt(
            self, "Change database server port", "Port: "
        )
        if not ok:
            return

        if settings.options["port"] == port:
            QtWidgets.QMessageBox.information(
                self, "Info", f"Server is already using port {port}"
            )
        else:
            settings.options["port"] = port
            if settings.db.server_running():
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Restart Database Server?",
                    "The server needs to be restarted for changes to take effect, would you like to do that now?",
                    QtWidgets.QMessageBox.Yes,
                    QtWidgets.QMessageBox.No,
                )
                if reply == QtWidgets.QMessageBox.Yes:
                    settings.db.restart_server()
                    settings.db.write_config()
                    self.refresh()

    @error_on_none_db
    def db_server_bind_address(self, *args, **kwargs):
        """Bind database server to an ip address."""
        address, ok = QtWidgets.QInputDialog.getText(
            self, "Change server ip address", "IP Address: "
        )
        if not ok:
            return

        if settings.options["address"] == address:
            QtWidgets.QMessageBox.information(
                self, "Info", f"Server is already bound to {address}"
            )
        else:
            settings.options["address"] = address
            if settings.db.server_running():
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Restart Database Server?",
                    "The server needs to be restarted for changes to take effect, would you like to do that now?",
                    QtWidgets.QMessageBox.Yes,
                    QtWidgets.QMessageBox.No,
                )
                if reply == QtWidgets.QMessageBox.Yes:
                    settings.db.restart_server()
                    settings.db.write_config()
                    self.refresh()

    @error_on_none_db
    def add_list(self, *args, **kwargs):
        """Add a new list of to-dos."""
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

            if list_name not in settings.db.todo_lists.keys():
                settings.db.todo_lists[list_name] = []
                settings.options["active_list"] = list_name
                settings.db.active_list = list_name
                settings.db.write_config()
                self.write_todo_data()
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Duplicate List",
                    f'A list named "{list_name}" already exists.',
                )

        self.refresh()

    @error_on_none_db
    def delete_list(self, *args, **kwargs):
        """Delete user selected list."""
        self.update_progress_bar(0)

        # if there is more than one list, ask user which one to delete
        if len(settings.db.todo_lists.keys()) > 1:
            list_entry, ok = QtWidgets.QInputDialog.getItem(
                self,
                "Select List",
                "To-Do Lists: ",
                list(settings.db.todo_lists.keys()),
            )
            if not ok:
                self.update_progress_bar()
                return

            settings.db.todo_total -= len(settings.db.todo_lists[list_entry])
            del settings.db.todo_lists[list_entry]

            # use list switcher if there is still more than one list
            if len(settings.db.todo_lists) > 1:
                self.switch_list()
            else:
                for list_entry in settings.db.todo_lists.keys():
                    self.db_update_active_list(list_entry)
                    self.write_todo_data()
                    break
        else:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Confirm deletion",
                f'Really delete list "{settings.db.active_list}"?',
                QtWidgets.QMessageBox.Yes,
                QtWidgets.QMessageBox.No,
            )
            if reply == QtWidgets.QMessageBox.No:
                self.update_progress_bar()
                return

            settings.db.todo_total -= settings.db.todo_count
            del settings.db.todo_lists[settings.db.active_list]
            settings.db.list_count -= 1

            # reset database
            settings.db.active_list = ""
            settings.options["active_list"] = settings.db.active_list
            settings.db.todo_count = 0
            settings.db.write_config()
            if os.path.exists(settings.lists_fn):
                os.remove(settings.lists_fn)

        self.refresh()

    @error_on_none_db
    def rename_list(self, *args, **kwargs):
        """Rename the active list"""
        self.update_progress_bar(0)

        list_name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename to-do list", "Enter new name:"
        )
        if ok:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Confirm rename",
                f"Are you sure you want to rename list {settings.db.active_list} to {list_name}",
                QtWidgets.QMessageBox.Yes,
                QtWidgets.QMessageBox.No,
            )

            if reply == QtWidgets.QMessageBox.No:
                return

            settings.db.todo_lists[list_name] = settings.db.todo_lists[
                settings.db.active_list
            ]
            del settings.db.todo_lists[settings.db.active_list]
            settings.db.active_list = settings.db.todo_lists[list_name]
            settings.db.write_config()
            self.write_todo_data()
            self.refresh()

    @error_on_none_db
    def switch_list(self, *args, **kwargs):
        """Switch the active list.

        Present user with a drop-down dialog of lists,
        set their choice as the active list.
        """
        self.update_progress_bar(0)

        if len(settings.db.todo_lists.keys()) == 0:
            return

        list_entry, ok = QtWidgets.QInputDialog.getItem(
            self, "Select List", "To-Do Lists: ", list(settings.db.todo_lists.keys())
        )
        if ok:
            self.db_update_active_list(list_entry)
            self.write_todo_data()

        self.refresh()

    @error_on_none_db
    def export_list(self, fn=None, *args, **kwargs):
        """Export active list to text file."""
        self.update_progress_bar(0)

        if not settings.db.todo_count:
            return

        if fn is None:
            # prompt user for fn
            self.update_status_bar("Waiting for input")
            fn, ok = QtWidgets.QInputDialog.getText(
                self,
                "Save list to text file",
                "Enter name of file to write as text:",
            )
            if not ok:
                return

        self.update_status_bar(f"Exporting to text file {fn}.")
        settings.db.write_text_file(fn)
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

        accept = QtPrintSupport.QPrintDialog(self.printer).exec()
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

            # Open string as a QTextDocument and then print it
            doc = QtGui.QTextDocument(string)
            doc.print_(self.printer)

        self.update_progress_bar()
        self.update_status_bar("finished printing")

    @error_on_none_db
    def add_todo(self, *args, **kwargs):
        """Add a new to-do to active list."""
        self.update_progress_bar(0)

        if not settings.db.active_list:
            if settings.db.list_count == 0:
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
                    "There is currently no active list set, but lists do exist,"
                    "would you like to switch to one of them?",
                    QtWidgets.QMessageBox.Yes,
                    QtWidgets.QMessageBox.No,
                )

                # check the user response
                if reply == QtWidgets.QMessageBox.Yes:
                    self.switch_list()
                else:
                    return

        # Get a new to-do from user
        AddTodoDialog().exec()

        self.refresh()

    @error_on_none_db
    def delete_todo(self, *args, **kwargs):
        """Delete the currently selected to-do."""
        self.update_progress_bar(0)

        if self.table is None:
            msg = "To-Do List Table is invalid, exiting"
            QtWidgets.QMessageBox.critical(self, "To-Do List Error", msg)
            logger.log.exception(msg)
            sys.exit(1)
        else:
            if self.table.selectionModel().hasSelection():
                indices = [
                    QtCore.QPersistentModelIndex(index)
                    for index in self.table.selectionModel().selectedIndexes()
                ]
                for index in indices:
                    item = self.table.cellWidget(index.row(), 1)
                    text = item.text()
                    todo = settings.db.todo_index(text)
                    del settings.db.todo_lists[settings.db.active_list][todo]
                    settings.db.todo_count -= 1
                    settings.db.todo_total -= 1
                    self.write_todo_data()
                    self.table.removeRow(index.row())
                self.refresh()
            else:
                QtWidgets.QMessageBox.warning(
                    self, "Delete To-Do", "No reminders selected."
                )

    @error_on_none_db
    def toggle_todo(self, *args, **kwargs):
        """Toggle a to-do complete / incomplete."""
        self.update_progress_bar(0)

        for index in self.table.selectedIndexes():
            item = self.table.cellWidget(index.row(), 1)
            text = item.text()
            todo = settings.db.todo_index(text)
            if not settings.db.todo_lists[settings.db.active_list][todo]["complete"]:
                settings.db.todo_lists[settings.db.active_list][todo]["complete"] = True
            else:
                settings.db.todo_lists[settings.db.active_list][todo][
                    "complete"
                ] = False
                self.write_todo_data()
            self.refresh()

    @error_on_none_db
    def change_priority(self, *args, **kwargs):
        """Change a to-do's priority."""
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
            todo = settings.db.todo_index(reminder)
            settings.db.todo_lists[settings.db.active_list][todo]["priority"] = priority
            self.write_todo_data()
            self.refresh()

    @error_on_none_db
    def edit_reminder(self, *args, **kwargs):
        """Edit the reminder of a to-do."""
        for index in self.table.selectedIndexes():
            item = self.table.cellWidget(index.row(), 1)
            new_text = item.text()
            settings.db.todo_lists[settings.db.active_list][index.row()][
                "reminder"
            ] = new_text
        self.write_todo_data()

    def about_todo(self):
        """Display a message box with Program/Author information."""
        text = """<b><u>To-Do v0.2.0</u></b>
        <br><br>To-Do list program that works with multiple To-Do
        lists locally and over a network.
        <br><br>License: <a href="http://www.fsf.org/licenses/gpl.html">GPLv3</a>
        <br><br><b>Copyright (C) 2024 Michael Berry</b>
        """
        QtWidgets.QMessageBox.about(self, "About To-Do", text)

    def about_qt(self):
        """Display information about Qt."""
        QtWidgets.QMessageBox.aboutQt(self, "About Qt")

    def center(self):
        """Place the main window in the center of the screen."""
        qt_rectangle = self.frameGeometry()
        center_point = QtWidgets.QDesktopWidget().availableGeometry().center()
        qt_rectangle.moveCenter(center_point)
        self.move(qt_rectangle.topLeft())

    @error_on_none_db
    def update_progress_bar(self, value=None, *args, **kwargs):
        """Update the progress bar.

        Maximum value should be set to the total to-do count,
        while value should be the number of completed todos.
        This makes the progress bar show the total percentage
        of completed to-dos.
        """
        if value is None:
            return

        i = 0

        for list_entry in settings.db.todo_lists:
            for todo in settings.db.todo_lists[list_entry]:
                if todo["complete"]:
                    i += 1

        value = i

        self.progressBar.reset()
        self.progressBar.setMaximum(settings.db.todo_total)
        self.progressBar.setValue(value)

    @error_on_none_db
    def update_status_bar(self, msg="Ready", *args, **kwargs):
        """Update the status bar, display some statistics."""
        if settings.db.server_running():
            server_status = (
                f"Up on {settings.options['address']}: {settings.options['port']}"
            )
        else:
            server_status = "Down"

        # create our status bar text
        text = f"Lists: {settings.db.list_count}  Shown: {settings.db.active_list}  To-Do's: {settings.db.todo_count} of {settings.db.todo_total}  Status: {msg}  Server: {server_status}"

        self.statusBarLabel.setText(text)

    @error_on_none_db
    def refresh(self, *args, **kwargs):
        """Redraw the table and update the progress and status bars."""
        self.update_status_bar("Redrawing table")

        # clear the table
        self.table.setRowCount(0)

        # set the table headers
        self.table.setHorizontalHeaderLabels(["Priority", "Reminder"])

        # make sure we have a valid active list
        if settings.db.active_list not in settings.db.todo_lists:
            self.update_status_bar()
            return

        # add each to-do in the list to the table, show a progress bar
        i = 0
        settings.db.sort_active_list()

        # update the progress bar
        self.update_progress_bar(0)

        for todo in settings.db.todo_lists[settings.db.active_list]:
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
        settings.db.todo_count = len(settings.db.todo_lists[settings.db.active_list])
        settings.db.list_count = len(settings.db.todo_lists.keys())

        # update progress and status bars
        self.update_progress_bar()
        self.update_status_bar()

    def tray_event(self, reason=QtWidgets.QSystemTrayIcon.activated, *args, **kwargs):
        """Hide the main window when the system tray icon is clicked."""
        if reason == QtWidgets.QSystemTrayIcon.activated:
            if self.isVisible():
                self.hide()
            else:
                self.show()

    @error_on_none_db
    def closeEvent(self, event, *args, **kwargs):
        """Take care of clean up details."""
        # save configuration
        result, msg = settings.db.write_config()
        if not result:
            QtWidgets.QMessageBox.warning(self, "Write Error", msg)

        # save todo lists
        self.write_todo_data()

        # shutdown database network server
        if settings.db.server_running():
            settings.db.net_server.shutdown()

        # hide the tray icon
        self.tray_icon.hide()

        logger.log.info("Closing main window, quitting application")

        # close the window
        event.accept()
