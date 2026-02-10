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
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut, QTextDocument
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
from ..core.database import DatabaseStorage
from ..core.logger import Logger
from ..core.migration import MigrationError, migrate_json_to_sqlite, needs_migration
from ..core.models import Database, Device, PendingSync, TodoList, create_todo_list
from ..core.offline_queue import OfflineQueue
from ..crypto.keyring_storage import get_or_create_identity
from ..net.client import AsyncClient
from ..net.discovery import get_discovery_service
from ..net.server import AsyncServer
from ..net.sync_queue import SyncQueue, SyncStatus, create_pull_operation, create_push_operation
from .dialogs import (
    AddTodoDialog,
    DeviceManagerDialog,
    ListSyncSettingsDialog,
    PeerManagerDialog,
    SettingsDialog,
    SyncDialog,
)
from .styles import apply_current_theme
from .styles.themes import Theme, get_system_theme
from .widgets import ListSelectorWidget, SearchFilterWidget, StatusBarWidget, TodoTableWidget

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
        self._storage = DatabaseStorage(self._config_manager.db_file)
        self._offline_queue = OfflineQueue(self._storage)
        self._sync_client = AsyncClient(self)
        self._sync_queue = SyncQueue(self._sync_client, self)
        self._printer = QPrinter()
        self._server: AsyncServer | None = None
        self._auto_syncing_devices: set[UUID] = set()
        self._event_loop = asyncio.get_event_loop()  # Store for thread-safe scheduling

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

        # Start sync queue
        self._sync_queue.operation_progress.connect(
            lambda op_id, msg: self.status_bar_widget.show_message(msg)
        )
        asyncio.ensure_future(self._sync_queue.start())

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

        self.toggle_private_action = QAction("Toggle &Private", self)
        self.toggle_private_action.setShortcut("Ctrl+Shift+P")
        self.toggle_private_action.triggered.connect(self._on_toggle_private)

        # Sync actions
        self.sync_pull_action = QAction("&Pull from Remote...", self)
        self.sync_pull_action.setShortcut("F6")
        self.sync_pull_action.triggered.connect(self._on_sync_pull)

        self.sync_push_action = QAction("Pu&sh to Remote...", self)
        self.sync_push_action.setShortcut("F7")
        self.sync_push_action.triggered.connect(self._on_sync_push)

        self.peer_manager_action = QAction("&Peer Manager...", self)
        self.peer_manager_action.triggered.connect(self._on_peer_manager)

        self.device_manager_action = QAction("&Device Manager...", self)
        self.device_manager_action.triggered.connect(self._on_device_manager)

        # Peer submenus (populated dynamically)
        self.pull_peers_menu: QMenu | None = None
        self.push_peers_menu: QMenu | None = None

        # Help actions
        self.about_action = QAction("&About", self)
        self.about_action.triggered.connect(self._on_about)

        self.about_qt_action = QAction("About &Qt", self)
        self.about_qt_action.triggered.connect(self._on_about_qt)

        # Search shortcuts
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.activated.connect(self._on_search_focus)

        self.escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.escape_shortcut.activated.connect(self._on_search_escape)

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
            list_menu.addSeparator()
            list_menu.addAction(self.toggle_private_action)

        # Sync menu
        sync_menu = menu_bar.addMenu("&Sync")
        if sync_menu:
            # Sync Group submenu
            self.sync_group_menu = sync_menu.addMenu("Sync &Group")
            if self.sync_group_menu:
                self.sync_group_menu.aboutToShow.connect(self._populate_sync_group_menu)

            # Sync All Trusted action
            self.sync_all_action = QAction("Sync &All Trusted", self)
            self.sync_all_action.setShortcut("Ctrl+Shift+S")
            self.sync_all_action.setToolTip("Sync with all online trusted devices")
            self.sync_all_action.triggered.connect(self._on_sync_all_trusted)
            sync_menu.addAction(self.sync_all_action)

            sync_menu.addSeparator()

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
            sync_menu.addAction(self.device_manager_action)
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
        self.list_selector.toggle_private_requested.connect(self._on_toggle_private)
        self.list_selector.sync_settings_requested.connect(self._on_list_sync_settings)
        layout.addWidget(self.list_selector)

        # Search/filter bar
        self.search_filter = SearchFilterWidget()
        self.search_filter.filter_changed.connect(self._on_filter_changed)
        layout.addWidget(self.search_filter)

        # Todo table
        self.todo_table = TodoTableWidget()
        self.todo_table.item_priority_changed.connect(self._on_item_priority_changed)
        self.todo_table.item_reminder_changed.connect(self._on_item_reminder_changed)
        self.todo_table.item_due_date_changed.connect(self._on_item_due_date_changed)
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

        # Use simple monochrome tray icon
        if sys.platform == "darwin":
            # Mark as template image for macOS menu bar (adapts to dark/light mode)
            icon = self._get_icon("tray.svg")
            icon.setIsMask(True)
        else:
            # Pick icon color based on system theme so it's visible on dark panels
            theme = get_system_theme()
            icon_name = "tray-light.svg" if theme == Theme.DARK else "tray.svg"
            icon = self._get_icon(icon_name)
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
                on_peer_added=self._on_peer_discovered,
            )
            logger.log.info("Discovery service started")

            # Clean up expired pending syncs on startup
            expired = self._offline_queue.cleanup_expired()
            if expired > 0:
                logger.log.info("Cleaned up %d expired pending syncs", expired)
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
                on_client_connected=self._on_client_connected,
                on_client_disconnected=self._on_client_disconnected,
            )
            logger.log.info("Server started")
        except Exception as e:
            logger.log.exception("Failed to start server: %s", e)

    def _on_client_connected(self, address: str, fingerprint: str) -> None:
        """Handle client connection - auto-track device."""
        try:
            self._track_device(fingerprint, address)
            logger.log.info("Client connected and tracked: %s (%s)", address, fingerprint[:19])
        except Exception as e:
            logger.log.exception("Error tracking connected device: %s", e)

    def _on_client_disconnected(self, address: str) -> None:
        """Handle client disconnection."""
        logger.log.debug("Client disconnected: %s", address)

    def _track_device(self, fingerprint: str, address: str | None = None) -> Device:
        """Track a device by fingerprint, creating or updating as needed.

        Args:
            fingerprint: Device fingerprint
            address: Optional address (host:port or IP)

        Returns:
            The tracked Device object
        """
        import time

        now = int(time.time() * 1000)

        # Check if device already exists
        existing = self._storage.get_device_by_fingerprint(fingerprint)

        if existing:
            # Update last_seen and address
            existing.last_seen = now
            if address:
                existing.last_address = address
            self._storage.save_device(existing)
            logger.log.debug("Updated existing device: %s", fingerprint[:19])
            return existing

        # Create new device
        device = Device(
            fingerprint=fingerprint,
            name="",  # User can name it later
            first_seen=now,
            last_seen=now,
            last_address=address,
            trust_level="normal",
        )
        self._storage.save_device(device)
        logger.log.info("New device tracked: %s (address=%s)", fingerprint[:19], address)
        return device

    def _on_peer_discovered(self, peer) -> None:
        """Handle peer discovery - check for pending syncs and auto-sync.

        Args:
            peer: DiscoveredPeer from discovery service
        """
        if peer.is_local:
            return

        fingerprint = peer.fingerprint
        if not fingerprint:
            return

        # Look up device by fingerprint
        device = self._storage.get_device_by_fingerprint(fingerprint)
        if device is None:
            return

        # Check for pending syncs for this device
        pending = self._offline_queue.get_pending_for_device(device.id)
        if pending:
            logger.log.info(
                "Device %s came online with %d pending sync(s)",
                device.name or fingerprint[:19],
                len(pending),
            )
            # Use thread-safe scheduling (callback comes from zeroconf thread)
            asyncio.run_coroutine_threadsafe(
                self._process_pending_syncs(device, peer, pending), self._event_loop
            )
            return  # Pending syncs take priority

        # Check for auto-sync on trusted devices
        config = get_config()
        if config.discovery.auto_sync_trusted and device.trust_level == "trusted":
            if device.id in self._auto_syncing_devices:
                logger.log.debug(
                    "Skipping auto-sync, already syncing with: %s",
                    device.name or fingerprint[:19],
                )
                return
            logger.log.info(
                "Auto-syncing with trusted device: %s",
                device.name or fingerprint[:19],
            )
            # Use thread-safe scheduling (callback comes from zeroconf thread)
            asyncio.run_coroutine_threadsafe(
                self._auto_sync_with_device(device, peer), self._event_loop
            )

    async def _auto_sync_with_device(self, device: Device, peer) -> None:
        """Perform automatic sync with a trusted device.

        Args:
            device: The trusted device
            peer: DiscoveredPeer with connection info
        """
        import random as _random

        if device.id in self._auto_syncing_devices:
            return
        self._auto_syncing_devices.add(device.id)
        try:
            # Random initial delay (1-3s) to avoid mutual discovery race
            delay = 1.0 + _random.random() * 2.0  # noqa: S311
            logger.log.debug(
                "Auto-sync with %s: waiting %.1fs before connecting",
                device.name or device.fingerprint[:19],
                delay,
            )
            await asyncio.sleep(delay)

            self.status_bar_widget.set_sync_status(
                "syncing",
                "sync",
                f"Auto-sync: {device.name or 'Trusted device'}",
            )

            # Pull first
            pull_op = create_pull_operation(peer.address, peer.port, device_id=device.id)
            pull_result = await self._sync_queue.execute(pull_op)
            pull_ok = pull_result.success
            if pull_ok:
                self._merge_sync_data_internal(pull_result.data)

            # Skip push if pull had a connection error (peer not ready)
            if pull_result.status == SyncStatus.CONNECTION_RETRY:
                logger.log.warning(
                    "Auto-sync pull connection failed for %s, skipping push",
                    device.name or device.fingerprint[:19],
                )
                self.status_bar_widget.set_sync_status("error")
                return

            # Push (filtered by sync rules)
            allowed_list_ids = self._storage.get_syncable_list_ids_for_device(device.id)
            push_data = json.dumps(self._database.to_dict_for_device(allowed_list_ids)).encode(
                "utf-8"
            )
            push_op = create_push_operation(peer.address, peer.port, push_data, device_id=device.id)
            push_result = await self._sync_queue.execute(push_op)
            push_ok = push_result.success

            if pull_ok and push_ok:
                self._track_device(device.fingerprint, f"{peer.address}:{peer.port}")
                self._save_database()
                self._refresh_ui()
                self.status_bar_widget.set_sync_status("success", auto=True)
                logger.log.info(
                    "Auto-sync completed with %s",
                    device.name or device.fingerprint[:19],
                )
            else:
                self.status_bar_widget.set_sync_status("error")
                logger.log.warning(
                    "Auto-sync failed with %s (pull=%s, push=%s)",
                    device.name,
                    pull_ok,
                    push_ok,
                )

        except Exception as e:
            self.status_bar_widget.set_sync_status("error")
            logger.log.exception("Auto-sync error with %s: %s", device.name, e)
        finally:
            self._auto_syncing_devices.discard(device.id)

    async def _process_pending_syncs(
        self, device: Device, peer, pending: list[PendingSync]
    ) -> None:
        """Process pending syncs for a device that came online.

        Args:
            device: The device that came online
            peer: DiscoveredPeer with connection info
            pending: List of pending syncs to process
        """
        for sync in pending:
            self._offline_queue.record_attempt(sync)

            try:
                self.status_bar_widget.set_sync_status(
                    "syncing",
                    "sync",
                    f"Processing queued sync: {device.name or 'Device'}",
                )

                # Pull first
                pull_op = create_pull_operation(peer.address, peer.port, device_id=device.id)
                pull_result = await self._sync_queue.execute(pull_op)
                pull_ok = pull_result.success
                if pull_ok:
                    self._merge_sync_data_internal(pull_result.data)

                # Skip push if pull had a connection error (peer not ready)
                if pull_result.status == SyncStatus.CONNECTION_RETRY:
                    logger.log.warning(
                        "Pending sync pull connection failed for %s, skipping push",
                        device.name or device.fingerprint[:19],
                    )
                    self.status_bar_widget.set_sync_status("error")
                    continue

                # Push (filtered by sync rules)
                allowed_list_ids = self._storage.get_syncable_list_ids_for_device(device.id)
                push_data = json.dumps(self._database.to_dict_for_device(allowed_list_ids)).encode(
                    "utf-8"
                )
                push_op = create_push_operation(
                    peer.address, peer.port, push_data, device_id=device.id
                )
                push_result = await self._sync_queue.execute(push_op)
                push_ok = push_result.success

                if pull_ok and push_ok:
                    # Success - remove from queue
                    self._offline_queue.remove(sync.id)
                    self._track_device(device.fingerprint, f"{peer.address}:{peer.port}")
                    self._save_database()
                    self._refresh_ui()
                    self.status_bar_widget.set_sync_status("success", auto=True)
                    logger.log.info(
                        "Processed queued sync for %s",
                        device.name or device.fingerprint[:19],
                    )
                else:
                    self.status_bar_widget.set_sync_status("error")
                    logger.log.warning(
                        "Queued sync failed for %s (pull=%s, push=%s)",
                        device.name,
                        pull_ok,
                        push_ok,
                    )

            except Exception as e:
                self.status_bar_widget.set_sync_status("error")
                logger.log.exception("Error processing queued sync: %s", e)

    def _stop_server(self) -> None:
        """Stop the TCP server."""
        if self._server is None:
            return

        try:
            asyncio.ensure_future(self._server.stop())
        except Exception as e:
            logger.log.warning("Error stopping server: %s", e)

    def _get_sync_data(self) -> bytes:
        """Get database as bytes for sync (excludes private lists)."""
        return json.dumps(self._database.to_dict_for_sync()).encode("utf-8")

    def _on_sync_received(self, data: bytes) -> None:
        """Handle received sync data from incoming push."""
        self.status_bar_widget.set_sync_status("syncing", "pull", "remote")
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
            self.status_bar_widget.set_sync_status("success")
        except Exception as e:
            self.status_bar_widget.set_sync_status("error")
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
        """Load the database from SQLite, migrating from JSON if needed."""
        json_path = self._config_manager.legacy_json_file
        sqlite_path = self._config_manager.db_file

        # Check if migration from JSON to SQLite is needed
        if needs_migration(json_path, sqlite_path):
            try:
                logger.log.info("Migrating database from JSON to SQLite...")
                migrate_json_to_sqlite(json_path, sqlite_path, backup=True)
                logger.log.info("Database migration completed successfully")
            except MigrationError as e:
                logger.log.exception("Database migration failed: %s", e)
                QMessageBox.warning(
                    self,
                    "Migration Error",
                    f"Failed to migrate database to new format: {e}\n\n"
                    "The application will continue with an empty database.",
                )

        # Open SQLite storage and load database
        try:
            self._storage.open()
            self._database = self._storage.load_database()
            logger.log.info("Loaded database from %s", sqlite_path)
        except Exception as e:
            logger.log.exception("Error loading database: %s", e)
            QMessageBox.warning(self, "Load Error", f"Failed to load database: {e}")
            self._database = Database()

        # Set active list from config (overrides stored active_list_id)
        active_list_name = self._config.database.active_list
        if active_list_name:
            self._database.set_active_list_by_name(active_list_name)
        elif self._database.lists and self._database.active_list_id is None:
            # Set first list as active if none set
            self._database.active_list_id = next(iter(self._database.lists.keys()))

        self._refresh_ui()

    def _save_database(self) -> bool:
        """Save the database to SQLite."""
        try:
            self._storage.save_database(self._database)
            logger.log.info("Saved database to %s", self._config_manager.db_file)
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
        total_completed = self._database.total_completed()

        self.status_bar_widget.update_stats(
            list_count=list_count,
            item_count=item_count,
            completed_count=completed,
            total_items=total_items,
            total_completed=total_completed,
        )

        # Server status
        config = get_config()
        self.status_bar_widget.set_server_status(
            running=config.server.enabled,
            address=config.server.address,
            port=config.server.port,
        )

        # Pending sync count
        pending_count = self._offline_queue.get_pending_count()
        self.status_bar_widget.set_pending_sync_count(pending_count)

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

    def _on_toggle_private(self) -> None:
        """Handle toggle private action."""
        active_list = self._database.active_list
        if active_list is None:
            return

        active_list.toggle_private()
        self._save_database()
        self._refresh_ui()

        status = "private (won't sync)" if active_list.private else "shared"
        self.status_bar_widget.show_message(f'List "{active_list.name}" is now {status}', 3000)

    def _on_list_sync_settings(self) -> None:
        """Handle list sync settings request."""
        active_list = self._database.active_list
        if active_list is None:
            return

        dialog = ListSyncSettingsDialog(
            self,
            todo_list=active_list,
            storage=self._storage,
        )

        if dialog.exec() == ListSyncSettingsDialog.DialogCode.Accepted:
            # Get potentially updated list (for private flag changes)
            updated_list = dialog.get_updated_list()
            if updated_list:
                # Update in database
                self._database.lists[updated_list.id] = updated_list
                self._save_database()
                self._refresh_ui()

                # Show status message
                if updated_list.private:
                    msg = f'List "{updated_list.name}" is now private'
                else:
                    rules = self._storage.get_sync_rules_for_list(updated_list.id)
                    if rules:
                        msg = f'List "{updated_list.name}" syncs to selected groups'
                    else:
                        msg = f'List "{updated_list.name}" syncs to all devices'
                self.status_bar_widget.show_message(msg, 3000)

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

    def _on_item_due_date_changed(self, item_id: UUID, due_date) -> None:
        """Handle item due date change."""
        active_list = self._database.active_list
        if active_list:
            item = active_list.get_item(item_id)
            if item:
                item.due_date = due_date
                item.mark_updated()
                self._save_database()
                self._refresh_ui()

    def _on_filter_changed(self, filter_state) -> None:
        """Handle filter state change."""
        self.todo_table.set_filter(filter_state)

    def _on_search_focus(self) -> None:
        """Handle Ctrl+F shortcut."""
        self.search_filter.focus_search()

    def _on_search_escape(self) -> None:
        """Handle Escape shortcut."""
        self.search_filter.handle_escape()

    def _populate_sync_group_menu(self) -> None:
        """Populate the sync group submenu with available groups."""
        if self.sync_group_menu is None:
            return

        self.sync_group_menu.clear()

        groups = self._storage.get_all_sync_groups()
        if not groups:
            action = self.sync_group_menu.addAction("No sync groups created")
            action.setEnabled(False)
            return

        discovery = get_discovery_service()
        online_fps = {p.fingerprint for p in discovery.get_peers() if not p.is_local}

        for group in groups:
            devices = self._storage.get_devices_in_group(group.id)
            online_count = sum(1 for d in devices if d.fingerprint in online_fps)

            action = self.sync_group_menu.addAction(
                f"{group.name} ({online_count}/{len(devices)} online)"
            )
            action.setData(group.id)
            action.setEnabled(online_count > 0)
            action.triggered.connect(lambda checked, gid=group.id: self._on_sync_group(gid))

    def _on_sync_group(self, group_id) -> None:
        """Handle sync group from menu."""
        asyncio.ensure_future(self._async_sync_group(group_id))

    async def _async_sync_group(self, group_id) -> None:
        """Async handler for syncing a group."""
        group = self._storage.get_sync_group(group_id)
        if group is None:
            return

        # Get online devices in group
        discovery = get_discovery_service()
        online_fps = {p.fingerprint for p in discovery.get_peers() if not p.is_local}
        devices = self._storage.get_devices_in_group(group_id)
        online_devices = [d for d in devices if d.fingerprint in online_fps]

        if not online_devices:
            QMessageBox.information(
                self,
                "No Online Devices",
                f"No devices in '{group.name}' are currently online.",
            )
            return

        result = QMessageBox.question(
            self,
            "Sync Group",
            f"Sync with {len(online_devices)} online device(s) in '{group.name}'?\n\n"
            + "\n".join(f"  - {d.name or 'Unnamed'}" for d in online_devices),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        await self._do_bulk_sync(online_devices, f"Syncing '{group.name}'")

    def _on_sync_all_trusted(self) -> None:
        """Handle sync all trusted devices."""
        asyncio.ensure_future(self._async_sync_all_trusted())

    async def _async_sync_all_trusted(self) -> None:
        """Async handler for syncing all trusted devices."""
        # Get online trusted devices
        discovery = get_discovery_service()
        online_fps = {p.fingerprint for p in discovery.get_peers() if not p.is_local}
        devices = [
            d
            for d in self._storage.get_all_devices()
            if d.trust_level == "trusted" and d.fingerprint in online_fps
        ]

        if not devices:
            QMessageBox.information(
                self,
                "No Trusted Devices",
                "No trusted devices are currently online.",
            )
            return

        result = QMessageBox.question(
            self,
            "Sync All Trusted",
            f"Sync with {len(devices)} trusted online device(s)?\n\n"
            + "\n".join(f"  - {d.name or 'Unnamed'}" for d in devices),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        await self._do_bulk_sync(devices, "Syncing trusted devices")

    async def _do_bulk_sync(
        self, devices: list, operation_name: str, queue_offline: bool = False
    ) -> None:
        """Perform bulk sync with multiple devices with progress reporting.

        Args:
            devices: List of Device objects to sync with
            operation_name: Name of the operation for status display
            queue_offline: If True, queue syncs for offline devices
        """
        discovery = get_discovery_service()
        success_count = 0
        fail_count = 0
        queued_count = 0
        total = len(devices)

        for i, device in enumerate(devices, 1):
            # Update status bar with progress
            self.status_bar_widget.set_sync_status(
                "syncing",
                "sync",
                f"{operation_name}: {device.name or 'Device'} ({i}/{total})",
            )

            # Find peer for device
            peer = None
            for p in discovery.get_peers():
                if p.fingerprint == device.fingerprint and not p.is_local:
                    peer = p
                    break

            if peer is None:
                if queue_offline:
                    self._offline_queue.enqueue(device.id)
                    queued_count += 1
                    logger.log.info(
                        "Queued sync for offline device: %s",
                        device.name or device.fingerprint[:19],
                    )
                else:
                    fail_count += 1
                continue

            try:
                # Pull
                pull_op = create_pull_operation(peer.address, peer.port, device_id=device.id)
                pull_result = await self._sync_queue.execute(pull_op)
                if pull_result.success:
                    self._merge_sync_data_internal(pull_result.data)

                # Push (filtered by sync rules)
                allowed_list_ids = self._storage.get_syncable_list_ids_for_device(device.id)
                push_data = json.dumps(self._database.to_dict_for_device(allowed_list_ids)).encode(
                    "utf-8"
                )
                push_op = create_push_operation(
                    peer.address, peer.port, push_data, device_id=device.id
                )
                push_result = await self._sync_queue.execute(push_op)

                if pull_result.success and push_result.success:
                    success_count += 1
                    # Track device
                    self._track_device(device.fingerprint, f"{peer.address}:{peer.port}")
                    # Clear any pending syncs for this device
                    self._offline_queue.clear_for_device(device.id)
                else:
                    fail_count += 1

            except Exception as e:
                logger.log.exception("Bulk sync with %s failed: %s", device.name, e)
                fail_count += 1

        # Save and refresh
        self._save_database()
        self._refresh_ui()

        # Show result
        if fail_count == 0 and queued_count == 0:
            self.status_bar_widget.set_sync_status("success")
            QMessageBox.information(
                self,
                "Sync Complete",
                f"Successfully synced with {success_count} device(s).",
            )
        elif queued_count > 0:
            self.status_bar_widget.set_sync_status("success")
            msg = f"Synced with {success_count} device(s)."
            if queued_count > 0:
                msg += f"\n{queued_count} device(s) offline - syncs queued."
            if fail_count > 0:
                msg += f"\n{fail_count} failed."
            QMessageBox.information(self, "Sync Complete", msg)
        else:
            self.status_bar_widget.set_sync_status("error")
            QMessageBox.warning(
                self,
                "Sync Partial",
                f"Synced with {success_count} device(s).\n{fail_count} failed.",
            )

    def queue_sync_for_device(self, device_id: UUID) -> bool:
        """Queue a sync for a device.

        Args:
            device_id: UUID of the device to queue sync for

        Returns:
            True if sync was queued, False if already queued
        """
        if self._offline_queue.has_pending(device_id):
            return False
        self._offline_queue.enqueue(device_id)
        return True

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

        async def do_pull():
            self.status_bar_widget.set_sync_status("syncing", "pull", f"{host}:{port}")
            try:
                logger.log.debug("Menu pull: connecting to %s:%d", host, port)
                pull_op = create_pull_operation(host, port)
                result = await self._sync_queue.execute(pull_op)
                if result.success:
                    # Track the device we synced with
                    peer_fingerprint = self._sync_client.get_last_peer_fingerprint()
                    if peer_fingerprint:
                        self._track_device(peer_fingerprint, f"{host}:{port}")

                    merged, local_newer, identical = self._merge_sync_data_internal(result.data)
                    self._save_database()
                    self._refresh_ui()
                    self.status_bar_widget.set_sync_status("success")
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
                    self.status_bar_widget.set_sync_status("error")
                    QMessageBox.warning(self, "Pull Failed", f"Could not pull from {host}:{port}")
            except Exception as e:
                self.status_bar_widget.set_sync_status("error")
                logger.log.exception("Menu pull failed: %s", e)
                QMessageBox.critical(self, "Pull Error", f"Pull failed: {e}")

        asyncio.ensure_future(do_pull())

    def _do_sync_push(self, host: str, port: int) -> None:
        """Perform sync push to specified host (excludes private lists)."""

        async def do_push():
            self.status_bar_widget.set_sync_status("syncing", "push", f"{host}:{port}")
            try:
                logger.log.debug("Menu push: connecting to %s:%d", host, port)
                data = json.dumps(self._database.to_dict_for_sync()).encode("utf-8")
                push_op = create_push_operation(host, port, data)
                result = await self._sync_queue.execute(push_op)
                if result.success:
                    # Track the device we synced with
                    peer_fingerprint = self._sync_client.get_last_peer_fingerprint()
                    if peer_fingerprint:
                        self._track_device(peer_fingerprint, f"{host}:{port}")

                    self.status_bar_widget.set_sync_status("success")
                    QMessageBox.information(
                        self,
                        "Push Complete",
                        f"Pushed {len(data)} bytes to {host}:{port}\nRemote will merge any new items.",
                    )
                else:
                    self.status_bar_widget.set_sync_status("error")
                    QMessageBox.warning(self, "Push Failed", f"Could not push to {host}:{port}")
            except Exception as e:
                self.status_bar_widget.set_sync_status("error")
                logger.log.exception("Menu push failed: %s", e)
                QMessageBox.critical(self, "Push Error", f"Push failed: {e}")

        asyncio.ensure_future(do_push())

    def _on_sync_pull(self) -> None:
        """Handle sync pull action."""
        dialog = SyncDialog(self, operation="pull", database=self._database)
        if dialog.exec() == SyncDialog.DialogCode.Accepted:
            # Track device
            fingerprint = dialog.get_peer_fingerprint()
            address = dialog.get_last_address()
            if fingerprint:
                self._track_device(fingerprint, address)

            result = dialog.get_sync_result()
            if result:
                self._merge_sync_data(result)

    def _on_sync_push(self) -> None:
        """Handle sync push action."""
        dialog = SyncDialog(self, operation="push", database=self._database)
        if dialog.exec() == SyncDialog.DialogCode.Accepted:
            # Track device
            fingerprint = dialog.get_peer_fingerprint()
            address = dialog.get_last_address()
            if fingerprint:
                self._track_device(fingerprint, address)

            self.status_bar_widget.set_sync_status("success")

    def _merge_sync_data(self, data: bytes) -> None:
        """Merge received sync data into local database."""
        try:
            merged, local_newer, identical = self._merge_sync_data_internal(data)
            self._save_database()
            self._refresh_ui()
            self.status_bar_widget.set_sync_status("success")
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
            self.status_bar_widget.set_sync_status("error")
            logger.log.exception("Error merging sync data: %s", e)
            QMessageBox.warning(self, "Merge Error", f"Failed to merge sync data: {e}")

    def _on_peer_manager(self) -> None:
        """Handle peer manager action."""
        dialog = PeerManagerDialog(self, database=self._database, storage=self._storage)
        dialog.sync_data_received.connect(self._on_peer_sync_received)
        dialog.exec()

    def _on_device_manager(self) -> None:
        """Handle device manager action."""
        dialog = DeviceManagerDialog(self, database=self._database, storage=self._storage)
        dialog.sync_data_received.connect(self._on_device_sync_received)
        dialog.exec()

    def _on_peer_sync_received(self, data: bytes) -> None:
        """Handle sync data received from peer manager."""
        self._save_database()
        self._refresh_ui()
        self.status_bar_widget.set_sync_status("success")

    def _on_device_sync_received(self, data: bytes) -> None:
        """Handle sync data received from device manager."""
        self._save_database()
        self._refresh_ui()
        self.status_bar_widget.set_sync_status("success")

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
        # Stop sync queue
        asyncio.ensure_future(self._sync_queue.stop())

        # Stop server
        self._stop_server()

        # Stop discovery service
        self._stop_discovery()

        # Save database
        self._save_database()

        # Close database connection
        self._storage.close()

        # Save config
        self._config_manager.save()

        # Hide tray icon
        if self.tray_icon is not None:
            self.tray_icon.hide()

        logger.log.info("Application closing")
        event.accept()
