"""main_window.py

Refactored main window using modular components.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QAction, QIcon, QPixmap, QTextDocument
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..core import settings
from ..core.config import get_config, get_config_manager
from ..core.logger import Logger
from ..core.models import Database, TodoList, create_todo_list
from ..crypto.keyring_storage import get_or_create_identity
from ..net.discovery import get_discovery_service
from ..net.server import AsyncServer
from .dialogs import AddTodoDialog, PeerManagerDialog, SettingsDialog, SyncDialog
from .styles import apply_current_theme
from .widgets import ListSelectorWidget, StatusBarWidget, TodoTableWidget

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        logger.log.info("Creating main window")

        self._database = Database()
        self._config = get_config()
        self._config_manager = get_config_manager()
        self._printer = QPrinter()
        self._server: AsyncServer | None = None

        self._setup_window()
        self._setup_actions()
        self._setup_menus()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_status_bar()
        self._setup_tray_icon()

        # Apply theme
        apply_current_theme()

        # Load data
        self._load_database()

        # Start discovery service
        self._start_discovery()

        # Start server
        self._start_server()

        # Show window
        self.show()
        logger.log.info("Main window created")

    def _setup_window(self) -> None:
        """Configure the main window."""
        self.setWindowTitle("PyTodo-Qt")
        self.setWindowIcon(self._get_icon("pytodo-qt.svg"))
        self.resize(900, 600)
        self._center_window()

    def _get_icon(self, name: str) -> QIcon:
        """Get an icon from the icons directory.

        For SVG icons, explicitly sets pixmaps for all icon modes to prevent
        Qt from auto-generating mode variants which can cause rendering issues.
        """
        icon_dir = Path(__file__).parent / "icons"
        icon_path = icon_dir / name
        if not icon_path.exists():
            return QIcon()

        if name.endswith(".svg"):
            # Load SVG as pixmap and set for all modes to prevent hover issues
            pixmap = QPixmap(str(icon_path))
            icon = QIcon()
            # Set same pixmap for all modes to prevent Qt from modifying it
            for mode in (
                QIcon.Mode.Normal,
                QIcon.Mode.Active,
                QIcon.Mode.Disabled,
                QIcon.Mode.Selected,
            ):
                icon.addPixmap(pixmap, mode)
            return icon
        return QIcon(str(icon_path))

    def _center_window(self) -> None:
        """Center the window on screen."""
        screen = self.screen()
        if screen:
            center = screen.availableGeometry().center()
            frame = self.frameGeometry()
            frame.moveCenter(center)
            self.move(frame.topLeft())

    def _setup_actions(self) -> None:
        """Create all actions."""
        # File actions
        self.print_action = QAction("&Print", self)
        self.print_action.setShortcut("Ctrl+P")
        self.print_action.triggered.connect(self._on_print)

        self.settings_action = QAction("&Settings...", self)
        self.settings_action.triggered.connect(self._on_settings)

        self.exit_action = QAction(self._get_icon("exit.svg"), "E&xit", self)
        self.exit_action.setShortcut("Ctrl+Q")
        self.exit_action.setToolTip("Exit application (Ctrl+Q)")
        self.exit_action.triggered.connect(self.close)

        # Todo actions
        self.add_todo_action = QAction(self._get_icon("plus.svg"), "&Add To-Do", self)
        self.add_todo_action.setShortcut("+")
        self.add_todo_action.setToolTip("Add new to-do (+)")
        self.add_todo_action.triggered.connect(self._on_add_todo)

        self.delete_todo_action = QAction(self._get_icon("minus.svg"), "&Delete To-Do", self)
        self.delete_todo_action.setShortcut("-")
        self.delete_todo_action.setToolTip("Delete selected to-do (-)")
        self.delete_todo_action.triggered.connect(self._on_delete_todo)

        self.toggle_todo_action = QAction(self._get_icon("toggle.svg"), "&Toggle Complete", self)
        self.toggle_todo_action.setShortcut("%")
        self.toggle_todo_action.setToolTip("Toggle completion status (%)")
        self.toggle_todo_action.triggered.connect(self._on_toggle_todo)

        # List actions
        self.add_list_action = QAction("Add &List", self)
        self.add_list_action.setShortcut("Ctrl++")
        self.add_list_action.triggered.connect(self._on_add_list)

        self.delete_list_action = QAction("&Delete List", self)
        self.delete_list_action.setShortcut("Ctrl+-")
        self.delete_list_action.triggered.connect(self._on_delete_list)

        self.rename_list_action = QAction("&Rename List", self)
        self.rename_list_action.setShortcut("Ctrl+R")
        self.rename_list_action.triggered.connect(self._on_rename_list)

        # Sync actions
        self.sync_pull_action = QAction("&Pull from Remote...", self)
        self.sync_pull_action.setShortcut("F6")
        self.sync_pull_action.triggered.connect(self._on_sync_pull)

        self.sync_push_action = QAction("Pu&sh to Remote...", self)
        self.sync_push_action.setShortcut("F7")
        self.sync_push_action.triggered.connect(self._on_sync_push)

        self.peer_manager_action = QAction("&Peer Manager...", self)
        self.peer_manager_action.triggered.connect(self._on_peer_manager)

        # Peer submenus (populated dynamically)
        self.pull_peers_menu: QMenu | None = None
        self.push_peers_menu: QMenu | None = None

        # Help actions
        self.about_action = QAction("&About", self)
        self.about_action.triggered.connect(self._on_about)

        self.about_qt_action = QAction("About &Qt", self)
        self.about_qt_action.triggered.connect(self._on_about_qt)

    def _setup_menus(self) -> None:
        """Create the menu bar."""
        menu_bar = self.menuBar()
        if menu_bar is None:
            return

        # File menu
        file_menu = menu_bar.addMenu("&File")
        if file_menu:
            file_menu.addAction(self.print_action)
            file_menu.addSeparator()
            file_menu.addAction(self.settings_action)
            file_menu.addSeparator()
            file_menu.addAction(self.exit_action)

        # Todo menu
        todo_menu = menu_bar.addMenu("&To-Do")
        if todo_menu:
            todo_menu.addAction(self.add_todo_action)
            todo_menu.addAction(self.delete_todo_action)
            todo_menu.addAction(self.toggle_todo_action)

        # List menu
        list_menu = menu_bar.addMenu("&List")
        if list_menu:
            list_menu.addAction(self.add_list_action)
            list_menu.addAction(self.delete_list_action)
            list_menu.addAction(self.rename_list_action)

        # Sync menu
        sync_menu = menu_bar.addMenu("&Sync")
        if sync_menu:
            # Pull submenu with discovered peers
            self.pull_peers_menu = sync_menu.addMenu("Pull from &Peer")
            if self.pull_peers_menu:
                self.pull_peers_menu.aboutToShow.connect(self._populate_pull_peers_menu)

            # Push submenu with discovered peers
            self.push_peers_menu = sync_menu.addMenu("Push to P&eer")
            if self.push_peers_menu:
                self.push_peers_menu.aboutToShow.connect(self._populate_push_peers_menu)

            sync_menu.addSeparator()
            sync_menu.addAction(self.sync_pull_action)
            sync_menu.addAction(self.sync_push_action)
            sync_menu.addSeparator()
            sync_menu.addAction(self.peer_manager_action)

        # Help menu
        help_menu = menu_bar.addMenu("&Help")
        if help_menu:
            help_menu.addAction(self.about_action)
            help_menu.addAction(self.about_qt_action)

    def _setup_toolbar(self) -> None:
        """Create the toolbar."""
        toolbar = self.addToolBar("Actions")
        if toolbar:
            toolbar.addAction(self.add_todo_action)
            toolbar.addAction(self.delete_todo_action)
            toolbar.addAction(self.toggle_todo_action)
            toolbar.addSeparator()
            toolbar.addAction(self.exit_action)

    def _setup_central_widget(self) -> None:
        """Set up the central widget."""
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        # List selector
        self.list_selector = ListSelectorWidget()
        self.list_selector.list_changed.connect(self._on_list_changed)
        self.list_selector.add_list_requested.connect(self._on_add_list)
        self.list_selector.delete_list_requested.connect(self._on_delete_list)
        self.list_selector.rename_list_requested.connect(self._on_rename_list)
        layout.addWidget(self.list_selector)

        # Todo table
        self.todo_table = TodoTableWidget()
        self.todo_table.item_priority_changed.connect(self._on_item_priority_changed)
        self.todo_table.item_reminder_changed.connect(self._on_item_reminder_changed)
        layout.addWidget(self.todo_table)

        self.setCentralWidget(central)

    def _setup_status_bar(self) -> None:
        """Set up the status bar."""
        self.status_bar_widget = StatusBarWidget()
        self.setStatusBar(self.status_bar_widget)

    def _setup_tray_icon(self) -> None:
        """Set up the system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.log.warning("System tray is not available on this platform")
            self.tray_icon = None
            return

        self.tray_icon = QSystemTrayIcon(self)

        # Use simple monochrome tray icon (works as macOS template)
        icon = self._get_icon("tray.svg")
        if sys.platform == "darwin":
            # Mark as template image for macOS menu bar (adapts to dark/light mode)
            icon.setIsMask(True)
        self.tray_icon.setIcon(icon)

        self._tray_menu = QMenu()
        self._tray_menu.addAction("Show", self.show)
        self._tray_menu.addAction("Hide", self.hide)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction("Exit", self.close)

        # On macOS, don't auto-attach context menu (it shows on every click)
        # Instead, we manually show it on right-click in _on_tray_activated
        if sys.platform != "darwin":
            self.tray_icon.setContextMenu(self._tray_menu)

        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

        if not self.tray_icon.isVisible():
            logger.log.warning("System tray icon failed to show")

    def _start_discovery(self) -> None:
        """Start the mDNS discovery service for peer discovery."""
        config = get_config()

        if not config.server.enabled or not config.discovery.enabled:
            logger.log.info(
                "Discovery disabled (server.enabled=%s, discovery.enabled=%s)",
                config.server.enabled,
                config.discovery.enabled,
            )
            return

        try:
            identity = get_or_create_identity()
            discovery = get_discovery_service()
            discovery.start(
                port=config.server.port,
                fingerprint=identity.fingerprint,
                protocol_version=config.security.protocol_version,
            )
            logger.log.info("Discovery service started")
        except Exception as e:
            logger.log.exception("Failed to start discovery service: %s", e)

    def _stop_discovery(self) -> None:
        """Stop the mDNS discovery service."""
        try:
            discovery = get_discovery_service()
            discovery.stop()
        except Exception as e:
            logger.log.warning("Error stopping discovery: %s", e)

    def _start_server(self) -> None:
        """Start the TCP server for sync connections."""
        config = get_config()

        if not config.server.enabled:
            logger.log.info("Server disabled")
            return

        try:
            self._server = AsyncServer(
                host=config.server.address,
                port=config.server.port,
            )
            # Schedule server start in the async event loop
            asyncio.ensure_future(self._async_start_server())
        except Exception as e:
            logger.log.exception("Failed to create server: %s", e)

    async def _async_start_server(self) -> None:
        """Async helper to start the server."""
        if self._server is None:
            return

        try:
            await self._server.start(
                get_sync_data=self._get_sync_data,
                on_sync_received=self._on_sync_received,
            )
            logger.log.info("Server started")
        except Exception as e:
            logger.log.exception("Failed to start server: %s", e)

    def _stop_server(self) -> None:
        """Stop the TCP server."""
        if self._server is None:
            return

        try:
            asyncio.ensure_future(self._server.stop())
        except Exception as e:
            logger.log.warning("Error stopping server: %s", e)

    def _get_sync_data(self) -> bytes:
        """Get database as bytes for sync."""
        return json.dumps(self._database.to_dict()).encode("utf-8")

    def _on_sync_received(self, data: bytes) -> None:
        """Handle received sync data from incoming push."""
        try:
            merged, local_newer, identical = self._merge_sync_data_internal(data)
            if merged > 0:
                self._save_database()
                self._refresh_ui()
                logger.log.info("Received and merged %d items from remote push", merged)
            else:
                logger.log.info(
                    "Received sync data: %d local newer, %d identical", local_newer, identical
                )
        except Exception as e:
            logger.log.exception("Error processing sync data: %s", e)

    def _merge_sync_data_internal(self, data: bytes) -> tuple[int, int, int]:
        """Internal merge logic, returns (merged_count, local_newer_count, identical_count)."""
        remote_db = Database.from_dict(json.loads(data.decode("utf-8")))
        merged_count = 0
        local_newer_count = 0
        identical_count = 0

        for list_id, remote_list in remote_db.lists.items():
            if list_id in self._database.lists:
                local_list = self._database.lists[list_id]
                for item_id, remote_item in remote_list.items.items():
                    if item_id in local_list.items:
                        local_item = local_list.items[item_id]
                        if remote_item.updated_at > local_item.updated_at:
                            local_list.items[item_id] = remote_item
                            merged_count += 1
                        elif remote_item.updated_at < local_item.updated_at:
                            local_newer_count += 1
                        else:
                            identical_count += 1
                    else:
                        local_list.items[item_id] = remote_item
                        merged_count += 1
            else:
                self._database.lists[list_id] = remote_list
                merged_count += len(remote_list.items)

        return merged_count, local_newer_count, identical_count

    def _load_database(self) -> None:
        """Load the database from file."""
        db_path = self._config_manager.db_file

        if db_path.exists():
            try:
                with open(db_path, encoding="utf-8") as f:
                    data = json.load(f)

                # Check if it's new format (has schema_version) or legacy
                if "schema_version" in data:
                    self._database = Database.from_dict(data)
                else:
                    # Legacy format
                    self._database = Database.from_legacy(data)
                    logger.log.info("Migrated legacy database format")

                logger.log.info("Loaded database from %s", db_path)
            except Exception as e:
                logger.log.exception("Error loading database: %s", e)
                QMessageBox.warning(self, "Load Error", f"Failed to load database: {e}")

        # Set active list from config
        active_list_name = self._config.database.active_list
        if active_list_name:
            self._database.set_active_list_by_name(active_list_name)
        elif self._database.lists:
            # Set first list as active
            self._database.active_list_id = next(iter(self._database.lists.keys()))

        self._refresh_ui()

    def _save_database(self) -> bool:
        """Save the database to file."""
        db_path = self._config_manager.db_file

        try:
            with open(db_path, "w", encoding="utf-8") as f:
                json.dump(self._database.to_dict(), f, indent=2)
            logger.log.info("Saved database to %s", db_path)
            return True
        except Exception as e:
            logger.log.exception("Error saving database: %s", e)
            QMessageBox.warning(self, "Save Error", f"Failed to save database: {e}")
            return False

    def _refresh_ui(self) -> None:
        """Refresh all UI components."""
        self.list_selector.set_database(self._database)
        self.todo_table.set_list(self._database.active_list)
        self._update_status()

    def _update_status(self) -> None:
        """Update the status bar."""
        active_list = self._database.active_list
        list_count = len(list(self._database.active_lists()))
        item_count = active_list.active_item_count() if active_list else 0
        completed = active_list.completed_count() if active_list else 0
        total_items = self._database.total_items()

        self.status_bar_widget.update_stats(
            list_count=list_count,
            item_count=item_count,
            completed_count=completed,
            total_items=total_items,
        )

        # Server status
        config = get_config()
        self.status_bar_widget.set_server_status(
            running=config.server.enabled,
            address=config.server.address,
            port=config.server.port,
        )

    # Action handlers

    def _on_add_todo(self) -> None:
        """Handle add to-do action."""
        if self._database.active_list is None:
            if not list(self._database.active_lists()):
                QMessageBox.information(self, "No List", "You need to create a list first.")
                self._on_add_list()
                return
            else:
                # Pick a list
                list_name, ok = QInputDialog.getItem(
                    self,
                    "Select List",
                    "Select a list:",
                    self._database.list_names(),
                )
                if not ok or not list_name:
                    return
                self._database.set_active_list_by_name(list_name)

        item = AddTodoDialog.create_item(self)
        if item is not None and self._database.active_list is not None:
            self._database.active_list.add_item(item)
            self._save_database()
            self._refresh_ui()

    def _on_delete_todo(self) -> None:
        """Handle delete to-do action."""
        item_ids = self.todo_table.get_selected_item_ids()
        if not item_ids:
            QMessageBox.information(self, "Delete", "No items selected.")
            return

        active_list = self._database.active_list
        if active_list is None:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete {len(item_ids)} item(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            for item_id in item_ids:
                active_list.remove_item(item_id)
            self._save_database()
            self._refresh_ui()

    def _on_toggle_todo(self) -> None:
        """Handle toggle to-do action."""
        item_ids = self.todo_table.get_selected_item_ids()
        if not item_ids:
            return

        active_list = self._database.active_list
        if active_list is None:
            return

        for item_id in item_ids:
            item = active_list.get_item(item_id)
            if item:
                item.toggle_complete()

        self._save_database()
        self._refresh_ui()

    def _on_add_list(self) -> None:
        """Handle add list action."""
        name, ok = QInputDialog.getText(self, "Add List", "Enter list name:")
        if not ok or not name.strip():
            return

        name = name.strip()

        # Check for duplicate
        if self._database.get_list_by_name(name):
            QMessageBox.warning(self, "Duplicate", f'A list named "{name}" already exists.')
            return

        new_list = create_todo_list(name)
        self._database.add_list(new_list)
        self._database.set_active_list(new_list.id)

        # Update config
        self._config.database.active_list = name
        self._config_manager.save()

        self._save_database()
        self._refresh_ui()

    def _on_delete_list(self) -> None:
        """Handle delete list action."""
        active_list = self._database.active_list
        if active_list is None:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f'Delete list "{active_list.name}" and all its items?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            active_list.mark_deleted()
            # Find another list to make active
            for lst in self._database.active_lists():
                self._database.set_active_list(lst.id)
                break
            else:
                self._database.active_list_id = None

            self._save_database()
            self._refresh_ui()

    def _on_rename_list(self) -> None:
        """Handle rename list action."""
        active_list = self._database.active_list
        if active_list is None:
            return

        name, ok = QInputDialog.getText(
            self,
            "Rename List",
            "Enter new name:",
            text=active_list.name,
        )
        if not ok or not name.strip():
            return

        active_list.name = name.strip()
        active_list.mark_updated()

        self._save_database()
        self._refresh_ui()

    @pyqtSlot(object)
    def _on_list_changed(self, todo_list: TodoList | None) -> None:
        """Handle list selection change."""
        self.todo_table.set_list(todo_list)

        # Update config
        if todo_list:
            self._config.database.active_list = todo_list.name
            self._config_manager.save()

        self._update_status()

    def _on_item_priority_changed(self, item_id: UUID, priority: int) -> None:
        """Handle item priority change."""
        active_list = self._database.active_list
        if active_list:
            item = active_list.get_item(item_id)
            if item:
                item.priority = priority
                item.mark_updated()
                self._save_database()
                self._refresh_ui()

    def _on_item_reminder_changed(self, item_id: UUID, text: str) -> None:
        """Handle item reminder text change."""
        active_list = self._database.active_list
        if active_list:
            item = active_list.get_item(item_id)
            if item:
                item.reminder = text
                item.mark_updated()
                self._save_database()

    def _populate_pull_peers_menu(self) -> None:
        """Populate the pull peers submenu with discovered peers."""
        if self.pull_peers_menu is None:
            return

        self.pull_peers_menu.clear()
        discovery = get_discovery_service()
        peers = [p for p in discovery.get_peers() if not p.is_local]

        if not peers:
            action = self.pull_peers_menu.addAction("No peers discovered")
            action.setEnabled(False)
        else:
            for peer in peers:
                action = self.pull_peers_menu.addAction(f"{peer.display_name} ({peer.address})")
                action.setData((peer.address, peer.port))
                action.triggered.connect(lambda checked, a=action: self._on_pull_from_peer(a))

    def _populate_push_peers_menu(self) -> None:
        """Populate the push peers submenu with discovered peers."""
        if self.push_peers_menu is None:
            return

        self.push_peers_menu.clear()
        discovery = get_discovery_service()
        peers = [p for p in discovery.get_peers() if not p.is_local]

        if not peers:
            action = self.push_peers_menu.addAction("No peers discovered")
            action.setEnabled(False)
        else:
            for peer in peers:
                action = self.push_peers_menu.addAction(f"{peer.display_name} ({peer.address})")
                action.setData((peer.address, peer.port))
                action.triggered.connect(lambda checked, a=action: self._on_push_to_peer(a))

    def _on_pull_from_peer(self, action: QAction) -> None:
        """Handle pull from a specific discovered peer."""
        data = action.data()
        if data:
            host, port = data
            self._do_sync_pull(host, port)

    def _on_push_to_peer(self, action: QAction) -> None:
        """Handle push to a specific discovered peer."""
        data = action.data()
        if data:
            host, port = data
            self._do_sync_push(host, port)

    def _do_sync_pull(self, host: str, port: int) -> None:
        """Perform sync pull from specified host."""
        from ..net.client import AsyncClient

        async def do_pull():
            try:
                logger.log.debug("Menu pull: connecting to %s:%d", host, port)
                client = AsyncClient(self)
                success, data = await client.sync_pull(host, port)
                if success:
                    merged, local_newer, identical = self._merge_sync_data_internal(data)
                    self._save_database()
                    self._refresh_ui()
                    if merged > 0:
                        QMessageBox.information(
                            self,
                            "Pull Complete",
                            f"Pulled and merged {merged} items from {host}:{port}",
                        )
                    elif local_newer > 0:
                        QMessageBox.information(
                            self,
                            "Local Is Newer",
                            f"No items merged - {local_newer} local items are newer.\n"
                            "Push to update remote with your changes.",
                        )
                    else:
                        QMessageBox.information(
                            self,
                            "Already In Sync",
                            f"Databases are identical with {host}:{port}",
                        )
                else:
                    QMessageBox.warning(self, "Pull Failed", f"Could not pull from {host}:{port}")
            except Exception as e:
                logger.log.exception("Menu pull failed: %s", e)
                QMessageBox.critical(self, "Pull Error", f"Pull failed: {e}")

        asyncio.ensure_future(do_pull())

    def _do_sync_push(self, host: str, port: int) -> None:
        """Perform sync push to specified host."""
        from ..net.client import AsyncClient

        async def do_push():
            try:
                logger.log.debug("Menu push: connecting to %s:%d", host, port)
                client = AsyncClient(self)
                data = json.dumps(self._database.to_dict()).encode("utf-8")
                success = await client.sync_push(host, port, data)
                if success:
                    QMessageBox.information(
                        self,
                        "Push Complete",
                        f"Pushed {len(data)} bytes to {host}:{port}\nRemote will merge any new items.",
                    )
                else:
                    QMessageBox.warning(self, "Push Failed", f"Could not push to {host}:{port}")
            except Exception as e:
                logger.log.exception("Menu push failed: %s", e)
                QMessageBox.critical(self, "Push Error", f"Push failed: {e}")

        asyncio.ensure_future(do_push())

    def _on_sync_pull(self) -> None:
        """Handle sync pull action."""
        dialog = SyncDialog(self, operation="pull", database=self._database)
        if dialog.exec() == SyncDialog.DialogCode.Accepted:
            result = dialog.get_sync_result()
            if result:
                self._merge_sync_data(result)

    def _on_sync_push(self) -> None:
        """Handle sync push action."""
        dialog = SyncDialog(self, operation="push", database=self._database)
        dialog.exec()

    def _merge_sync_data(self, data: bytes) -> None:
        """Merge received sync data into local database."""
        try:
            merged, local_newer, identical = self._merge_sync_data_internal(data)
            self._save_database()
            self._refresh_ui()
            logger.log.info(
                "Merged %d, local newer %d, identical %d", merged, local_newer, identical
            )
            if merged > 0:
                QMessageBox.information(
                    self, "Sync Complete", f"Merged {merged} items from remote."
                )
            elif local_newer > 0:
                QMessageBox.information(
                    self,
                    "Local Is Newer",
                    f"No items merged - {local_newer} local items are newer.\n"
                    "Push to update remote with your changes.",
                )
            else:
                QMessageBox.information(self, "Already In Sync", "Databases are identical.")
        except Exception as e:
            logger.log.exception("Error merging sync data: %s", e)
            QMessageBox.warning(self, "Merge Error", f"Failed to merge sync data: {e}")

    def _on_peer_manager(self) -> None:
        """Handle peer manager action."""
        dialog = PeerManagerDialog(self, database=self._database)
        dialog.sync_data_received.connect(self._on_peer_sync_received)
        dialog.exec()

    def _on_peer_sync_received(self, data: bytes) -> None:
        """Handle sync data received from peer manager."""
        self._save_database()
        self._refresh_ui()

    def _on_settings(self) -> None:
        """Handle settings action."""
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self._refresh_ui()

    def _on_print(self) -> None:
        """Handle print action."""
        active_list = self._database.active_list
        if active_list is None or active_list.active_item_count() == 0:
            QMessageBox.information(self, "Print", "No items to print.")
            return

        dialog = QPrintDialog(self._printer, self)
        if dialog.exec() == QPrintDialog.DialogCode.Accepted:
            # Build document
            lines = [f"{'=' * 20} {active_list.name} {'=' * 20}", ""]
            for item in active_list.active_items():
                status = "✓" if item.complete else "○"
                priority = ["High", "Normal", "Low"][item.priority - 1]
                lines.append(f"{status} [{priority}] {item.reminder}")

            doc = QTextDocument("\n".join(lines))
            doc.print(self._printer)
            QMessageBox.information(self, "Print", "Print job sent.")

    def _on_about(self) -> None:
        """Handle about action."""
        QMessageBox.about(
            self,
            "About pytodo-qt",
            f"<b>pytodo-qt v{settings.__version__}</b><br><br>"
            "A modern cross-platform to-do application with "
            "secure synchronization.<br><br>"
            "License: <a href='http://www.fsf.org/licenses/gpl.html'>GPLv3</a><br><br>"
            "<b>Copyright (C) 2024 Michael Berry</b>",
        )

    def _on_about_qt(self) -> None:
        """Handle about Qt action."""
        QMessageBox.aboutQt(self, "About Qt")

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Left-click: toggle window visibility
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.activateWindow()
        elif (
            reason == QSystemTrayIcon.ActivationReason.Context
            and sys.platform == "darwin"
            and self.tray_icon is not None
        ):
            # Right-click: show context menu (macOS needs manual handling)
            from PyQt6.QtGui import QCursor

            self._tray_menu.popup(QCursor.pos())

    def closeEvent(self, event) -> None:
        """Handle window close."""
        # Stop server
        self._stop_server()

        # Stop discovery service
        self._stop_discovery()

        # Save database
        self._save_database()

        # Save config
        self._config_manager.save()

        # Hide tray icon
        if self.tray_icon is not None:
            self.tray_icon.hide()

        logger.log.info("Application closing")
        event.accept()
