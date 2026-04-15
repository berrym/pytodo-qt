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

from PyQt6.QtCore import QDate, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QIcon,
    QKeySequence,
    QPixmap,
    QShortcut,
    QTextDocument,
    QUndoStack,
)
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import settings
from ..core.config import get_config, get_config_manager
from ..core.database import DatabaseStorage
from ..core.logger import Logger
from ..core.models import Database, Device, PendingSync, TodoItem, TodoList
from ..core.offline_queue import OfflineQueue
from ..crypto.keyring_storage import get_or_create_identity
from ..net.client import AsyncClient
from ..net.discovery import get_discovery_service
from ..net.server import AsyncServer
from ..net.sync_queue import SyncQueue, SyncStatus, create_pull_operation, create_push_operation
from ..web.server import WebServer
from .auto_sync import AutoSyncScheduler
from .dialogs import (
    AddListDialog,
    AddTodoDialog,
    DeviceManagerDialog,
    ListSyncSettingsDialog,
    PeerManagerDialog,
    SettingsDialog,
    ShortcutsHelpDialog,
    SyncDialog,
)
from .styles import apply_current_theme
from .styles.themes import Theme, get_system_theme
from .widgets import (
    KanbanBoardWidget,
    ListSelectorWidget,
    PomodoroWidget,
    SearchFilterWidget,
    StatusBarWidget,
    StopwatchWidget,
    TodoTableWidget,
)

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
        self._unseen_changes: set[UUID] = set()  # Lists with unviewed sync changes
        self._force_quit = False
        self._event_loop = asyncio.get_event_loop()  # Store for thread-safe scheduling

        # Undo/redo
        self._undo_stack = QUndoStack(self)
        self._undo_stack.setUndoLimit(50)
        self._refreshing = False

        # Auto-sync scheduler (debounced push + periodic full sync)
        self._auto_scheduler = AutoSyncScheduler(
            delay_seconds=self._config.discovery.auto_sync_delay,
            interval_minutes=self._config.discovery.auto_sync_interval,
            parent=self,
        )
        self._undo_stack.indexChanged.connect(self._on_undo_index_changed)
        self._auto_scheduler.push_requested.connect(self._on_auto_push)
        self._auto_scheduler.sync_requested.connect(self._on_auto_sync)

        # Focus timer
        self._pomodoro = PomodoroWidget(self._config.pomodoro, self)
        self._pomodoro.session_completed.connect(self._on_pomodoro_session_completed)
        self._pomodoro.break_completed.connect(self._on_pomodoro_break_completed)
        self._pomodoro.stopped.connect(self._on_pomodoro_stopped)
        self._pomodoro.state_changed.connect(self._on_pomodoro_state_changed)

        # Stopwatch timer
        self._stopwatch = StopwatchWidget(self._config.stopwatch, self)
        self._stopwatch.session_completed.connect(self._on_stopwatch_completed)
        self._stopwatch.stopped.connect(self._on_stopwatch_stopped)
        self._stopwatch.state_changed.connect(self._on_stopwatch_state_changed)

        # Idle timeout for stopwatch auto-pause
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle_timeout)

        # Sound notifications
        from .widgets.sound_player import SoundPlayer

        self._sound_player = SoundPlayer(self._config.pomodoro, self)
        self._pomodoro_display_timer = QTimer(self)
        self._pomodoro_display_timer.setInterval(1000)
        self._pomodoro_display_timer.timeout.connect(self._update_pomodoro_display)
        self._best_streak = 0  # Updated after analytics service is created

        # Floating focus timer dialog (lazy-created)
        self._focus_timer_dialog = None

        # Web server
        self._web_server: WebServer | None = None

        self._setup_window()
        self._setup_actions()
        self._setup_menus()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_status_bar()
        self._setup_tray_icon()

        # Apply theme and watch for system theme changes
        apply_current_theme()
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            style_hints = app.styleHints()
            if style_hints is not None and hasattr(style_hints, "colorSchemeChanged"):
                style_hints.colorSchemeChanged.connect(self._on_system_theme_changed)

        # Load data
        self._load_database()

        # Start discovery service
        self._start_discovery()

        # Start sync queue
        asyncio.ensure_future(self._sync_queue.start())

        # Start server
        self._start_server()

        # Track LAN IP for change detection
        from ..core.network import get_lan_ip

        self._last_known_ip = get_lan_ip()

        # Start web server
        self._start_web_server()

        # Start auto-sync scheduler
        self._auto_scheduler.start()

        # Overdue refresh timer — checks every 60s if timed items have become overdue
        self._overdue_timer = QTimer(self)
        self._overdue_timer.timeout.connect(self._check_timed_overdue)
        self._overdue_timer.start(60_000)

        # Show window
        self.show()
        logger.log.info("Main window created")

        # Check for due/overdue items and notify (after window shown so tray is ready)
        QTimer.singleShot(2000, self._check_due_notifications)

    def _setup_window(self) -> None:
        """Configure the main window."""
        self.setWindowTitle(self.tr("PyTodo-Qt"))
        self.setWindowIcon(self._get_icon("pytodo-qt.svg"))
        self.resize(1100, 700)
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
            for mode in (
                QIcon.Mode.Normal,
                QIcon.Mode.Active,
                QIcon.Mode.Selected,
            ):
                icon.addPixmap(pixmap, mode)
            # Disabled mode: 30% opacity for clear visual feedback
            from PyQt6.QtGui import QColor, QPainter

            disabled = QPixmap(pixmap.size())
            disabled.fill(QColor(0, 0, 0, 0))
            painter = QPainter(disabled)
            painter.setOpacity(0.3)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            icon.addPixmap(disabled, QIcon.Mode.Disabled)
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

    @staticmethod
    def _tip(description: str, shortcut: str = "") -> str:
        """Build a tooltip with platform-native shortcut text.

        Uses QKeySequence.NativeText so macOS shows ⌘/⇧/⌥ symbols
        instead of Ctrl/Shift/Alt.
        """
        if not shortcut:
            return description
        native = QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText)
        return f"{description} ({native})"

    def _on_undo_text_changed(self, text: str) -> None:
        """Update undo tooltip when the undo stack description changes."""
        label = self.tr(f"Undo {text}") if text else self.tr("Undo")
        self.undo_action.setToolTip(f"{label} ({self._undo_native})")

    def _on_redo_text_changed(self, text: str) -> None:
        """Update redo tooltip when the redo stack description changes."""
        label = self.tr(f"Redo {text}") if text else self.tr("Redo")
        self.redo_action.setToolTip(f"{label} ({self._redo_native})")

    def _setup_actions(self) -> None:
        """Create all actions."""
        # File actions
        self.import_ics_action = QAction(self.tr("&Import from .ics..."), self)
        self.import_ics_action.setShortcut("Ctrl+I")
        self.import_ics_action.setToolTip(self._tip(self.tr("Import from .ics file"), "Ctrl+I"))
        self.import_ics_action.triggered.connect(self._on_import_ics)

        self.export_ics_action = QAction(self.tr("&Export List as .ics..."), self)
        self.export_ics_action.setShortcut("Ctrl+E")
        self.export_ics_action.setToolTip(self._tip(self.tr("Export list as .ics file"), "Ctrl+E"))
        self.export_ics_action.triggered.connect(self._on_export_ics)

        self.export_charts_action = QAction(self.tr("Export &Charts..."), self)
        self.export_charts_action.setToolTip(
            self.tr("Export analytics charts as PNG or multi-page PDF report")
        )
        self.export_charts_action.triggered.connect(self._on_export_charts)

        self.print_action = QAction(self.tr("&Print"), self)
        self.print_action.setShortcut("Ctrl+P")
        self.print_action.setToolTip(self._tip(self.tr("Print current list"), "Ctrl+P"))
        self.print_action.triggered.connect(self._on_print)

        self.settings_action = QAction(self.tr("&Settings..."), self)
        self.settings_action.triggered.connect(self._on_settings)

        self.exit_action = QAction(self._get_icon("exit.svg"), self.tr("&Quit"), self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.setToolTip(self._tip(self.tr("Quit application"), "Ctrl+Q"))
        self.exit_action.triggered.connect(self._quit_application)

        # Todo actions
        self.add_todo_action = QAction(self._get_icon("plus.svg"), self.tr("&Add Todo"), self)
        self.add_todo_action.setShortcut("+")
        self.add_todo_action.setToolTip(self._tip(self.tr("Add new todo"), "+"))
        self.add_todo_action.triggered.connect(self._on_add_todo)

        self.delete_todo_action = QAction(
            self._get_icon("minus.svg"), self.tr("&Delete Todo"), self
        )
        self.delete_todo_action.setShortcut("-")
        self.delete_todo_action.setToolTip(self._tip(self.tr("Delete selected todo"), "-"))
        self.delete_todo_action.triggered.connect(self._on_delete_todo)

        self.toggle_todo_action = QAction(
            self._get_icon("toggle.svg"), self.tr("&Toggle Complete"), self
        )
        self.toggle_todo_action.setShortcut("%")
        self.toggle_todo_action.setToolTip(self._tip(self.tr("Toggle completion status"), "%"))
        self.toggle_todo_action.triggered.connect(self._on_toggle_todo)

        self.edit_tags_action = QAction(self._get_icon("tag.svg"), self.tr("Edit &Tags..."), self)
        self.edit_tags_action.setShortcut("Ctrl+Shift+T")
        self.edit_tags_action.setToolTip(self._tip(self.tr("Edit tags"), "Ctrl+Shift+T"))
        self.edit_tags_action.triggered.connect(self._on_edit_tags)

        self.edit_recurrence_action = QAction(
            self._get_icon("clock.svg"), self.tr("Edit &Recurrence..."), self
        )
        self.edit_recurrence_action.setShortcut("Ctrl+Shift+R")
        self.edit_recurrence_action.setToolTip(
            self._tip(self.tr("Edit recurrence"), "Ctrl+Shift+R")
        )
        self.edit_recurrence_action.triggered.connect(self._on_edit_recurrence)

        self.add_subtask_action = QAction(self.tr("Add &Subtask..."), self)
        self.add_subtask_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.add_subtask_action.setToolTip(
            self._tip(self.tr("Add subtask to selected item"), "Ctrl+Shift+N")
        )
        self.add_subtask_action.triggered.connect(lambda: self._on_add_subtask())
        self.addAction(self.add_subtask_action)

        self.edit_due_date_action = QAction(
            self._get_icon("calendar.svg"), self.tr("Edit Due &Date..."), self
        )
        self.edit_due_date_action.setShortcut("Ctrl+D")
        self.edit_due_date_action.setToolTip(self._tip(self.tr("Edit due date"), "Ctrl+D"))
        self.edit_due_date_action.triggered.connect(self._on_edit_due_date)

        # List actions
        self.add_list_action = QAction(self.tr("Add &List"), self)
        self.add_list_action.setShortcut("Ctrl++")
        self.add_list_action.setToolTip(self._tip(self.tr("Add new list"), "Ctrl++"))
        self.add_list_action.triggered.connect(self._on_add_list)

        self.delete_list_action = QAction(self.tr("&Delete List"), self)
        self.delete_list_action.setShortcut("Ctrl+-")
        self.delete_list_action.setToolTip(self._tip(self.tr("Delete current list"), "Ctrl+-"))
        self.delete_list_action.triggered.connect(self._on_delete_list)

        self.rename_list_action = QAction(self.tr("&Rename List"), self)
        self.rename_list_action.setShortcut("Ctrl+R")
        self.rename_list_action.setToolTip(self._tip(self.tr("Rename current list"), "Ctrl+R"))
        self.rename_list_action.triggered.connect(self._on_rename_list)

        self.toggle_private_action = QAction(self.tr("Toggle &Private"), self)
        self.toggle_private_action.setShortcut("Ctrl+Shift+P")
        self.toggle_private_action.setToolTip(
            self._tip(self.tr("Toggle list private/shared"), "Ctrl+Shift+P")
        )
        self.toggle_private_action.triggered.connect(self._on_toggle_private)

        # Sync actions
        self.sync_pull_action = QAction(self.tr("&Pull from Remote..."), self)
        self.sync_pull_action.setShortcut("F6")
        self.sync_pull_action.setToolTip(self._tip(self.tr("Pull from remote"), "F6"))
        self.sync_pull_action.triggered.connect(self._on_sync_pull)

        self.sync_push_action = QAction(self.tr("Pu&sh to Remote..."), self)
        self.sync_push_action.setShortcut("F7")
        self.sync_push_action.setToolTip(self._tip(self.tr("Push to remote"), "F7"))
        self.sync_push_action.triggered.connect(self._on_sync_push)

        self.peer_manager_action = QAction(self.tr("&Peer Manager..."), self)
        self.peer_manager_action.triggered.connect(self._on_peer_manager)

        self.device_manager_action = QAction(self.tr("&Device Manager..."), self)
        self.device_manager_action.triggered.connect(self._on_device_manager)

        # Peer submenus (populated dynamically)
        self.pull_peers_menu: QMenu | None = None
        self.push_peers_menu: QMenu | None = None

        # Help actions
        self.about_action = QAction(self.tr("&About"), self)
        self.about_action.triggered.connect(self._on_about)

        self.about_qt_action = QAction(self.tr("About &Qt"), self)
        self.about_qt_action.triggered.connect(self._on_about_qt)

        # Undo/redo actions (auto-enable/disable and update text from QUndoStack)
        undo_action = self._undo_stack.createUndoAction(self, self.tr("&Undo"))
        assert undo_action is not None
        self.undo_action = undo_action
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setIcon(self._get_icon("undo.svg"))
        self._undo_native = QKeySequence(QKeySequence.StandardKey.Undo).toString(
            QKeySequence.SequenceFormat.NativeText
        )

        redo_action = self._undo_stack.createRedoAction(self, self.tr("&Redo"))
        assert redo_action is not None
        self.redo_action = redo_action
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.setIcon(self._get_icon("redo.svg"))
        self._redo_native = QKeySequence(QKeySequence.StandardKey.Redo).toString(
            QKeySequence.SequenceFormat.NativeText
        )
        self._undo_stack.undoTextChanged.connect(self._on_undo_text_changed)
        self._undo_stack.redoTextChanged.connect(self._on_redo_text_changed)
        self._on_undo_text_changed(self._undo_stack.undoText())
        self._on_redo_text_changed(self._undo_stack.redoText())

        # Focus timer actions
        self.start_focus_action = QAction(
            self._get_icon("play.svg"), self.tr("Start &Focus Session"), self
        )
        self.start_focus_action.setShortcut("Ctrl+T")
        self.start_focus_action.setToolTip(
            self._tip(self.tr("Start focus timer on selected item"), "Ctrl+T")
        )
        self.start_focus_action.triggered.connect(self._on_start_focus)

        self.pause_focus_action = QAction(
            self._get_icon("pause.svg"), self.tr("&Pause/Resume Focus"), self
        )
        self.pause_focus_action.setShortcut("Ctrl+Space")
        self.pause_focus_action.setToolTip(
            self._tip(self.tr("Pause or resume focus timer"), "Ctrl+Space")
        )
        self.pause_focus_action.triggered.connect(self._on_pause_focus)

        self.stop_focus_action = QAction(
            self._get_icon("stop.svg"), self.tr("S&top Focus Session"), self
        )
        self.stop_focus_action.setShortcut("Ctrl+.")
        self.stop_focus_action.setToolTip(self._tip(self.tr("Stop focus timer"), "Ctrl+."))
        self.stop_focus_action.triggered.connect(self._on_stop_focus)

        self.start_stopwatch_action = QAction(
            self._get_icon("stopwatch.svg"), self.tr("Start &Stopwatch"), self
        )
        self.start_stopwatch_action.setShortcut("Ctrl+Shift+T")
        self.start_stopwatch_action.setToolTip(
            self._tip(self.tr("Start stopwatch on selected item"), "Ctrl+Shift+T")
        )
        self.start_stopwatch_action.triggered.connect(self._on_start_stopwatch)

        # View toggle actions
        self.list_view_action = QAction(
            self._get_icon("view-list.svg"), self.tr("&List View"), self
        )
        self.list_view_action.setCheckable(True)
        self.list_view_action.setToolTip(self._tip(self.tr("Switch to list view"), "Ctrl+Shift+B"))
        self.list_view_action.triggered.connect(lambda: self._set_view_mode(0))

        self.board_view_action = QAction(
            self._get_icon("view-board.svg"), self.tr("&Board View"), self
        )
        self.board_view_action.setCheckable(True)
        self.board_view_action.setToolTip(
            self._tip(self.tr("Switch to board view"), "Ctrl+Shift+B")
        )
        self.board_view_action.triggered.connect(lambda: self._set_view_mode(1))

        self.calendar_view_action = QAction(
            self._get_icon("view-calendar.svg"), self.tr("&Calendar View"), self
        )
        self.calendar_view_action.setCheckable(True)
        self.calendar_view_action.setToolTip(
            self._tip(self.tr("Switch to calendar view"), "Ctrl+Shift+B")
        )
        self.calendar_view_action.triggered.connect(lambda: self._set_view_mode(2))

        self._view_action_group = QActionGroup(self)
        self._view_action_group.addAction(self.list_view_action)
        self._view_action_group.addAction(self.board_view_action)
        self._view_action_group.addAction(self.calendar_view_action)
        self._view_action_group.setExclusive(True)

        # Tools actions
        self.focus_stats_action = QAction(self.tr("Focus &Stats..."), self)
        self.focus_stats_action.triggered.connect(self._on_focus_stats)

        self.web_connect_action = QAction(
            self._get_icon("mobile.svg"), self.tr("Mobile &Setup..."), self
        )
        self.web_connect_action.triggered.connect(self._on_web_connect)

        # Help actions
        self.shortcuts_help_action = QAction(self.tr("&Keyboard Shortcuts"), self)
        self.shortcuts_help_action.setShortcut("F1")
        self.shortcuts_help_action.triggered.connect(self._on_shortcuts_help)

        # Search shortcuts
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.activated.connect(self._on_search_focus)

        self.escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.escape_shortcut.activated.connect(self._on_search_escape)

        # List switching shortcuts: Ctrl+1..9
        for i in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            shortcut.activated.connect(lambda idx=i - 1: self._on_switch_list_by_index(idx))
            setattr(self, f"_list_shortcut_{i}", shortcut)  # prevent GC

        # Ctrl+Left/Right to cycle lists
        self._list_prev_shortcut = QShortcut(QKeySequence("Ctrl+Left"), self)
        self._list_prev_shortcut.activated.connect(lambda: self.list_selector.cycle_list(-1))

        self._list_next_shortcut = QShortcut(QKeySequence("Ctrl+Right"), self)
        self._list_next_shortcut.activated.connect(lambda: self.list_selector.cycle_list(1))

    def _setup_menus(self) -> None:
        """Create the menu bar."""
        menu_bar = self.menuBar()
        if menu_bar is None:
            return

        # File menu
        file_menu = menu_bar.addMenu(self.tr("&File"))
        if file_menu:
            file_menu.addAction(self.import_ics_action)
            file_menu.addAction(self.export_ics_action)
            file_menu.addAction(self.export_charts_action)
            file_menu.addSeparator()
            file_menu.addAction(self.print_action)
            file_menu.addSeparator()
            file_menu.addAction(self.settings_action)
            file_menu.addSeparator()
            file_menu.addAction(self.exit_action)

        # Edit menu
        edit_menu = menu_bar.addMenu(self.tr("&Edit"))
        if edit_menu:
            edit_menu.addAction(self.undo_action)
            edit_menu.addAction(self.redo_action)

        # View menu
        view_menu = menu_bar.addMenu(self.tr("&View"))
        if view_menu:
            view_menu.addAction(self.list_view_action)
            view_menu.addAction(self.board_view_action)
            view_menu.addAction(self.calendar_view_action)
            view_menu.addSeparator()
            self._detail_panel_action = QAction(self.tr("Task &Details"), self)
            self._detail_panel_action.setShortcut("Ctrl+Shift+D")
            self._detail_panel_action.setCheckable(True)
            self._detail_panel_action.setChecked(False)
            self._detail_panel_action.triggered.connect(self._toggle_detail_panel)
            view_menu.addAction(self._detail_panel_action)

        # Todo menu
        todo_menu = menu_bar.addMenu(self.tr("&Todo"))
        if todo_menu:
            todo_menu.addAction(self.add_todo_action)
            todo_menu.addAction(self.add_subtask_action)
            todo_menu.addAction(self.delete_todo_action)
            todo_menu.addAction(self.toggle_todo_action)
            todo_menu.addSeparator()
            todo_menu.addAction(self.edit_tags_action)
            todo_menu.addAction(self.edit_due_date_action)
            todo_menu.addAction(self.edit_recurrence_action)
            todo_menu.addSeparator()
            todo_menu.addAction(self.start_focus_action)
            todo_menu.addAction(self.start_stopwatch_action)
            todo_menu.addAction(self.pause_focus_action)
            todo_menu.addAction(self.stop_focus_action)

        # List menu
        list_menu = menu_bar.addMenu(self.tr("&List"))
        if list_menu:
            list_menu.addAction(self.add_list_action)
            list_menu.addAction(self.delete_list_action)
            list_menu.addAction(self.rename_list_action)
            list_menu.addSeparator()
            list_menu.addAction(self.toggle_private_action)

        # Sync menu
        sync_menu = menu_bar.addMenu(self.tr("&Sync"))
        if sync_menu:
            # Sync Group submenu
            self.sync_group_menu = sync_menu.addMenu(self.tr("Sync &Group"))
            if self.sync_group_menu:
                self.sync_group_menu.aboutToShow.connect(self._populate_sync_group_menu)

            # Sync All Trusted action
            self.sync_all_action = QAction(self.tr("Sync &All Trusted"), self)
            self.sync_all_action.setShortcut("Ctrl+Shift+S")
            self.sync_all_action.setToolTip(
                self._tip(self.tr("Sync with all online trusted devices"), "Ctrl+Shift+S")
            )
            self.sync_all_action.triggered.connect(self._on_sync_all_trusted)
            sync_menu.addAction(self.sync_all_action)

            sync_menu.addSeparator()

            # Pull submenu with discovered peers
            self.pull_peers_menu = sync_menu.addMenu(self.tr("Pull from &Peer"))
            if self.pull_peers_menu:
                self.pull_peers_menu.aboutToShow.connect(self._populate_pull_peers_menu)

            # Push submenu with discovered peers
            self.push_peers_menu = sync_menu.addMenu(self.tr("Push to P&eer"))
            if self.push_peers_menu:
                self.push_peers_menu.aboutToShow.connect(self._populate_push_peers_menu)

            sync_menu.addSeparator()
            sync_menu.addAction(self.sync_pull_action)
            sync_menu.addAction(self.sync_push_action)
            sync_menu.addSeparator()
            sync_menu.addAction(self.device_manager_action)
            sync_menu.addAction(self.peer_manager_action)

        # Tools menu
        tools_menu = menu_bar.addMenu(self.tr("&Tools"))
        if tools_menu:
            tools_menu.addAction(self.focus_stats_action)
            tools_menu.addAction(self.web_connect_action)

        # Help menu
        help_menu = menu_bar.addMenu(self.tr("&Help"))
        if help_menu:
            help_menu.addAction(self.shortcuts_help_action)
            help_menu.addSeparator()
            help_menu.addAction(self.about_action)
            help_menu.addAction(self.about_qt_action)

    def _setup_toolbar(self) -> None:
        """Create the toolbar."""
        toolbar = self.addToolBar(self.tr("Actions"))
        if toolbar:
            toolbar.addAction(self.undo_action)
            toolbar.addAction(self.redo_action)
            toolbar.addSeparator()
            toolbar.addAction(self.add_todo_action)
            toolbar.addAction(self.delete_todo_action)
            toolbar.addAction(self.toggle_todo_action)
            toolbar.addSeparator()
            toolbar.addAction(self.edit_tags_action)
            toolbar.addAction(self.edit_recurrence_action)
            toolbar.addAction(self.edit_due_date_action)
            toolbar.addSeparator()
            toolbar.addAction(self.start_focus_action)
            toolbar.addAction(self.start_stopwatch_action)
            toolbar.addAction(self.pause_focus_action)
            toolbar.addAction(self.stop_focus_action)
            toolbar.addSeparator()
            toolbar.addAction(self.list_view_action)
            toolbar.addAction(self.board_view_action)
            toolbar.addAction(self.calendar_view_action)
            toolbar.addSeparator()
            toolbar.addAction(self.web_connect_action)
            toolbar.addSeparator()
            toolbar.addAction(self.exit_action)

    def _setup_central_widget(self) -> None:
        """Set up the central widget."""
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        # List selector + view toggle row
        top_row = QHBoxLayout()
        self.list_selector = ListSelectorWidget()
        self.list_selector.list_changed.connect(self._on_list_changed)
        self.list_selector.add_list_requested.connect(self._on_add_list)
        self.list_selector.delete_list_requested.connect(self._on_delete_list)
        self.list_selector.rename_list_requested.connect(self._on_rename_list)
        self.list_selector.toggle_private_requested.connect(self._on_toggle_private)
        self.list_selector.sync_settings_requested.connect(self._on_list_sync_settings)
        top_row.addWidget(self.list_selector, 1)

        # View toggle buttons
        from pathlib import Path as _Path

        _icon_dir = _Path(__file__).parent / "icons"

        self._list_view_btn = QToolButton()
        self._list_view_btn.setText(self.tr("List"))
        self._list_view_btn.setCheckable(True)
        self._list_view_btn.setToolTip(self.tr("List view"))
        _list_icon_path = _icon_dir / "view-list.svg"
        if _list_icon_path.exists():
            self._list_view_btn.setIcon(QIcon(str(_list_icon_path)))

        self._board_view_btn = QToolButton()
        self._board_view_btn.setText(self.tr("Board"))
        self._board_view_btn.setCheckable(True)
        self._board_view_btn.setToolTip(self.tr("Board view (Ctrl+Shift+B)"))
        _board_icon_path = _icon_dir / "view-board.svg"
        if _board_icon_path.exists():
            self._board_view_btn.setIcon(QIcon(str(_board_icon_path)))

        self._calendar_view_btn = QToolButton()
        self._calendar_view_btn.setText(self.tr("Calendar"))
        self._calendar_view_btn.setCheckable(True)
        self._calendar_view_btn.setToolTip(self.tr("Calendar view (Ctrl+Shift+B)"))
        _cal_icon_path = _icon_dir / "view-calendar.svg"
        if _cal_icon_path.exists():
            self._calendar_view_btn.setIcon(QIcon(str(_cal_icon_path)))

        self._view_btn_group = QButtonGroup(self)
        self._view_btn_group.addButton(self._list_view_btn, 0)
        self._view_btn_group.addButton(self._board_view_btn, 1)
        self._view_btn_group.addButton(self._calendar_view_btn, 2)
        self._view_btn_group.idClicked.connect(self._on_view_toggle)

        top_row.addWidget(self._list_view_btn)
        top_row.addWidget(self._board_view_btn)
        top_row.addWidget(self._calendar_view_btn)

        # Detail panel toggle — small info button after the view buttons
        self._detail_btn = QToolButton()
        self._detail_btn.setText(self.tr("\u2139"))  # ℹ info symbol
        self._detail_btn.setCheckable(True)
        self._detail_btn.setToolTip(self.tr("Task details (Ctrl+Shift+D)"))
        self._detail_btn.setStyleSheet(
            "QToolButton { font-size: 14px; padding: 2px 6px; color: palette(highlight); }"
            "QToolButton:checked { font-weight: bold; }"
        )
        self._detail_btn.toggled.connect(self._on_detail_btn_toggled)
        top_row.addWidget(self._detail_btn)

        layout.addLayout(top_row)

        # Search/filter bar
        self.search_filter = SearchFilterWidget()
        self.search_filter.filter_changed.connect(self._on_filter_changed)
        layout.addWidget(self.search_filter)

        # View stack: index 0 = list, index 1 = board
        self._view_stack = QStackedWidget()

        # Todo table (list view)
        self.todo_table = TodoTableWidget()
        self._connect_table_signals()
        self._view_stack.addWidget(self.todo_table)

        # Kanban board
        self.kanban_board = KanbanBoardWidget()
        self._connect_kanban_signals()
        self._view_stack.addWidget(self.kanban_board)

        # Calendar view
        from .widgets.calendar_view import CalendarViewWidget

        self.calendar_view = CalendarViewWidget()
        self._connect_calendar_signals()
        self._view_stack.addWidget(self.calendar_view)

        layout.addWidget(self._view_stack)

        # Set initial view mode from config
        view_mode = self._config.database.view_mode
        if view_mode == "board":
            self._view_stack.setCurrentIndex(1)
            self._board_view_btn.setChecked(True)
            self.board_view_action.setChecked(True)
        elif view_mode == "calendar":
            self._view_stack.setCurrentIndex(2)
            self._calendar_view_btn.setChecked(True)
            self.calendar_view_action.setChecked(True)
        else:
            self._view_stack.setCurrentIndex(0)
            self._list_view_btn.setChecked(True)
            self.list_view_action.setChecked(True)

        # Keyboard shortcut for view toggle
        view_toggle_shortcut = QShortcut(QKeySequence("Ctrl+Shift+B"), self)
        view_toggle_shortcut.activated.connect(self._toggle_view_mode)

        self.setCentralWidget(central)

        # Task detail panel — docked to the right, hidden by default.
        # Shows full metadata for the selected task. Toggle with Ctrl+I.
        from .widgets.detail_panel import TaskDetailPanel

        self._detail_panel = TaskDetailPanel(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._detail_panel)
        self._detail_panel.hide()
        self._connect_detail_panel_signals()

        detail_shortcut = QShortcut(QKeySequence("Ctrl+Shift+D"), self)
        detail_shortcut.activated.connect(self._toggle_detail_panel)

    def _connect_table_signals(self) -> None:
        """Connect TodoTableWidget signals to handlers."""
        self.todo_table.item_priority_changed.connect(self._on_item_priority_changed)
        self.todo_table.item_reminder_changed.connect(self._on_item_reminder_changed)
        self.todo_table.item_due_date_changed.connect(self._on_item_due_date_changed)
        self.todo_table.item_due_time_changed.connect(self._on_item_due_time_changed)
        self.todo_table.edit_tags_requested.connect(self._on_edit_tags_for_item)
        self.todo_table.toggle_requested.connect(self._on_toggle_todo)
        self.todo_table.delete_requested.connect(self._on_delete_todo)
        self.todo_table.edit_recurrence_requested.connect(self._on_edit_recurrence)
        self.todo_table.focus_requested.connect(self._on_context_menu_focus)
        self.todo_table.add_subtask_requested.connect(self._on_add_subtask)
        self.todo_table.set_time_block_requested.connect(self._on_set_time_block)
        self.todo_table.set_event_date_requested.connect(self._on_set_event_date)
        self.todo_table.item_selected.connect(lambda _: self._update_detail_panel())

    def _connect_kanban_signals(self) -> None:
        """Connect KanbanBoardWidget signals to handlers (same as table)."""
        self.kanban_board.item_priority_changed.connect(self._on_item_priority_changed)
        self.kanban_board.item_reminder_changed.connect(self._on_item_reminder_changed)
        self.kanban_board.item_due_date_changed.connect(self._on_item_due_date_changed)
        self.kanban_board.item_due_time_changed.connect(self._on_item_due_time_changed)
        self.kanban_board.edit_tags_requested.connect(self._on_edit_tags_for_item)
        self.kanban_board.toggle_requested.connect(self._on_toggle_todo)
        self.kanban_board.delete_requested.connect(self._on_delete_todo)
        self.kanban_board.edit_recurrence_requested.connect(self._on_edit_recurrence)
        self.kanban_board.focus_requested.connect(self._on_context_menu_focus)
        self.kanban_board.add_subtask_requested.connect(self._on_add_subtask)
        # Kanban-only signals
        self.kanban_board.item_column_changed.connect(self._on_item_column_changed)
        self.kanban_board.layout_preset_requested.connect(self._on_layout_preset)
        self.kanban_board.remove_column_requested.connect(self._on_remove_column)
        self.kanban_board.rename_column_requested.connect(self._on_rename_column)
        self.kanban_board.add_item_in_column_requested.connect(self._on_add_item_in_column)
        self.kanban_board.wip_limit_changed.connect(self._on_wip_limit_changed)
        self.kanban_board.item_selected.connect(lambda _: self._update_detail_panel())
        # Empty-state overlay actions
        self.kanban_board.add_task_requested.connect(self._on_add_todo)
        self.kanban_board.clear_filters_requested.connect(self.search_filter.clear_filters)
        self.kanban_board.show_completed_requested.connect(self._on_show_completed_requested)

    def _connect_calendar_signals(self) -> None:
        """Connect CalendarViewWidget signals to handlers (same as table/board)."""
        self.calendar_view.item_priority_changed.connect(self._on_item_priority_changed)
        self.calendar_view.item_reminder_changed.connect(self._on_item_reminder_changed)
        self.calendar_view.item_due_date_changed.connect(self._on_item_due_date_changed)
        self.calendar_view.item_due_time_changed.connect(self._on_item_due_time_changed)
        self.calendar_view.date_and_time_dropped.connect(self._on_date_and_time_dropped)
        self.calendar_view.edit_tags_requested.connect(self._on_edit_tags_for_item)
        self.calendar_view.toggle_requested.connect(self._on_toggle_todo)
        self.calendar_view.delete_requested.connect(self._on_delete_todo)
        self.calendar_view.edit_recurrence_requested.connect(self._on_edit_recurrence)
        self.calendar_view.focus_requested.connect(self._on_context_menu_focus)
        self.calendar_view.add_subtask_requested.connect(self._on_add_subtask)
        self.calendar_view.item_selected.connect(lambda _: self._update_detail_panel())
        self.calendar_view.item_edit_requested.connect(self._on_calendar_edit_requested)

    def _on_calendar_edit_requested(self, item_id: object) -> None:
        """Open the detail panel for an item and switch to edit mode.

        The calendar view fires this when the user picks a task from
        the all-day overflow popover. The popover's whole purpose is
        the "I picked one, now let me change it" path, so the panel
        opens already in edit mode rather than the default read-only
        view.
        """
        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.items.get(item_id)
        if item is None:
            return
        if not self._detail_panel.isVisible():
            self._detail_panel.show()
            if hasattr(self, "_detail_panel_action"):
                self._detail_panel_action.setChecked(True)
        self._detail_panel.set_item(item)
        self._detail_panel.set_edit_mode(True)

    def _connect_detail_panel_signals(self) -> None:
        """Connect TaskDetailPanel edit signals to the same handlers
        the list/kanban/calendar views use. Edits from the panel go
        through the same undo-command infrastructure."""
        self._detail_panel.item_reminder_changed.connect(self._on_item_reminder_changed)
        self._detail_panel.item_priority_changed.connect(self._on_item_priority_changed)
        self._detail_panel.item_due_date_changed.connect(self._on_item_due_date_changed)
        self._detail_panel.item_due_time_changed.connect(self._on_item_due_time_changed)
        self._detail_panel.toggle_requested.connect(self._on_toggle_todo)
        self._detail_panel.edit_tags_requested.connect(self._on_edit_tags_for_item)
        self._detail_panel.edit_requested.connect(self._on_detail_panel_edit)

    def _on_detail_panel_edit(self, item_id: object, field_name: str, value: object) -> None:
        """Handle generic field edits from the detail panel (estimated_minutes, etc.)."""
        from uuid import UUID as _UUID

        if not isinstance(item_id, _UUID):
            return
        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.get_item(item_id)
        if item is None:
            return
        old_value = getattr(item, field_name, None)
        if old_value == value:
            return
        setattr(item, field_name, value)
        item.mark_updated()
        active_list.mark_dirty()
        self._refresh_ui()

    def _on_view_toggle(self, view_id: int) -> None:
        """Handle view toggle button click."""
        self._set_view_mode(view_id)

    def _toggle_detail_panel(self) -> None:
        """Toggle the task detail panel visibility (Ctrl+Shift+D)."""
        visible = not self._detail_panel.isVisible()
        self._detail_panel.setVisible(visible)
        self._detail_btn.setChecked(visible)
        if hasattr(self, "_detail_panel_action"):
            self._detail_panel_action.setChecked(visible)
        if visible:
            self._update_detail_panel()

    def _on_detail_btn_toggled(self, checked: bool) -> None:
        """Handle the inline detail button toggle."""
        self._detail_panel.setVisible(checked)
        if hasattr(self, "_detail_panel_action"):
            self._detail_panel_action.setChecked(checked)
        if checked:
            self._update_detail_panel()

    def _update_detail_panel(self) -> None:
        """Update the detail panel with the currently selected task.

        Called when the panel opens and whenever the selection changes
        in any view. Looks up the full TodoItem from the database so
        the panel always shows current data.
        """
        if not self._detail_panel.isVisible():
            return
        item_ids = self._active_view_widget().get_selected_item_ids()
        if not item_ids:
            self._detail_panel.set_item(None)
            return
        active_list = self._database.active_list
        if active_list is None:
            self._detail_panel.set_item(None)
            return
        item = active_list.items.get(item_ids[0])
        self._detail_panel.set_item(item)

    def _toggle_view_mode(self) -> None:
        """Cycle through list → board → calendar (Ctrl+Shift+B)."""
        current = self._view_stack.currentIndex()
        new_index = (current + 1) % 3
        self._set_view_mode(new_index)

    def _set_view_mode(self, view_id: int) -> None:
        """Set the view mode (0=list, 1=board, 2=calendar), syncing all UI controls."""
        self._view_stack.setCurrentIndex(view_id)
        # Sync inline toggle buttons
        self._list_view_btn.setChecked(view_id == 0)
        self._board_view_btn.setChecked(view_id == 1)
        self._calendar_view_btn.setChecked(view_id == 2)
        # Sync toolbar actions
        self.list_view_action.setChecked(view_id == 0)
        self.board_view_action.setChecked(view_id == 1)
        self.calendar_view_action.setChecked(view_id == 2)
        if view_id == 1:
            self._reconcile_board_columns()
        mode = {0: "list", 1: "board", 2: "calendar"}.get(view_id, "list")
        self._config.database.view_mode = mode
        self._config_manager.save()
        self._refresh_ui()

    def _reconcile_board_columns(self) -> None:
        """Normalize board_column values for all top-level items in the active list.

        Catches edge cases from sync, migration, web API, or any missed code path.
        Items with work indicators (pomodoro time or completed subtasks) are
        placed in the second column (In Progress) rather than inbox.
        """
        from .commands import _best_incomplete_column

        active_list = self._database.active_list
        if not active_list:
            return
        cols = active_list.board_columns
        if not cols:
            return
        col_set = set(cols)
        last_col = cols[-1]
        changed = False
        for item in active_list.active_items():
            if item.parent_id is not None:
                continue  # Subtasks don't appear on the board
            old = item.board_column
            if not old or old not in col_set:
                item.board_column = _best_incomplete_column(item, active_list)
                item.mark_updated()
                changed = True
            elif item.complete and old != last_col:
                item.board_column = last_col
                item.mark_updated()
                changed = True
            elif not item.complete and old == last_col:
                item.board_column = _best_incomplete_column(item, active_list)
                item.mark_updated()
                changed = True
        if changed:
            active_list.mark_updated()
            self._save_database()

    def _advance_overdue_recurring(self) -> None:
        """Auto-advance overdue recurring items across all lists."""
        from ..core.models import advance_all_overdue_recurring

        count = advance_all_overdue_recurring(self._database)
        if count > 0:
            logger.log.info("Auto-advanced %d overdue recurring item(s)", count)
            self._reconcile_board_columns()
            self._save_database()

    def _on_item_column_changed(self, item_id: object, new_column: str) -> None:
        """Handle item moved to a different kanban column."""
        from uuid import UUID as _UUID

        if not isinstance(item_id, _UUID):
            return
        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.get_item(item_id)
        if not item:
            return

        old_column = item.board_column
        if old_column == new_column:
            return

        from .commands import MoveToColumnCommand

        # Determine auto-complete behavior
        cols = active_list.board_columns
        last_col = cols[-1] if cols else None
        auto_complete: bool | None = None
        if last_col:
            if new_column == last_col and not item.complete:
                auto_complete = True
            elif old_column == last_col and item.complete:
                auto_complete = False

        cmd = MoveToColumnCommand(
            self, active_list.id, item_id, old_column, new_column, auto_complete
        )
        self._undo_stack.push(cmd)

    def _on_layout_preset(self, columns: object) -> None:
        """Handle board layout preset selection."""
        if not isinstance(columns, list):
            return
        active_list = self._database.active_list
        if active_list is None:
            return
        if active_list.board_columns == columns:
            return  # Already this layout

        from .commands import ApplyLayoutPresetCommand

        cmd = ApplyLayoutPresetCommand(self, active_list.id, columns)
        self._undo_stack.push(cmd)

    def _on_add_item_in_column(self, column_name: str) -> None:
        """Handle '+ Add item' click in a kanban column."""
        active_list = self._database.active_list
        if active_list is None:
            return

        known_tags = self._collect_known_tags()
        # Pass the column list + user's implicit choice. The dialog's
        # column dropdown pre-selects `column_name` and writes whatever
        # the user confirms onto item.board_column — no post-hoc
        # override needed here.
        item = AddTodoDialog.create_item(
            self,
            title=self.tr(f"Add Item \u2014 {column_name}"),
            known_tags=known_tags,
            columns=list(active_list.board_columns),
            selected_column=column_name,
        )
        if item is None:
            return

        from .commands import AddItemCommand

        cmd = AddItemCommand(self, active_list.id, item)
        self._undo_stack.push(cmd)

    def _on_remove_column(self, column_name: str) -> None:
        """Handle remove column request from kanban board."""
        active_list = self._database.active_list
        if active_list is None:
            return
        if len(active_list.board_columns) <= 3:
            QMessageBox.warning(
                self,
                self.tr("Cannot Remove"),
                self.tr(
                    "Board must have at least 3 columns. Use the Layout button to change board layout."
                ),
            )
            return
        # Protect the inbox column (first column)
        if column_name == active_list.board_columns[0]:
            QMessageBox.warning(
                self,
                self.tr("Cannot Remove"),
                self.tr("Cannot remove the inbox column. New items land here."),
            )
            return
        # Protect the completion column (last column)
        if column_name == active_list.board_columns[-1]:
            QMessageBox.warning(
                self,
                self.tr("Cannot Remove"),
                self.tr(
                    "Cannot remove the completion column. Items moved to this column are automatically marked complete."
                ),
            )
            return
        try:
            index = active_list.board_columns.index(column_name)
        except ValueError:
            return

        from .commands import RemoveColumnCommand

        cmd = RemoveColumnCommand(self, active_list.id, column_name, index)
        self._undo_stack.push(cmd)

    def _on_rename_column(self, old_name: str, new_name: str) -> None:
        """Handle rename column request from kanban board."""
        active_list = self._database.active_list
        if active_list is None:
            return
        if not new_name.strip() or new_name == old_name:
            return
        if new_name in active_list.board_columns:
            return  # Duplicate

        from .commands import RenameColumnCommand

        cmd = RenameColumnCommand(self, active_list.id, old_name, new_name)
        self._undo_stack.push(cmd)

    def _on_wip_limit_changed(self, column_name: str, limit: int) -> None:
        """Handle WIP limit change from kanban board."""
        active_list = self._database.active_list
        if active_list is None:
            return

        old_limit = active_list.get_wip_limit(column_name)
        if old_limit == limit:
            return

        from .commands import SetWipLimitCommand

        cmd = SetWipLimitCommand(self, active_list.id, column_name, old_limit, limit)
        self._undo_stack.push(cmd)

    def _setup_status_bar(self) -> None:
        """Set up the status bar."""
        self.status_bar_widget = StatusBarWidget()
        self.status_bar_widget.pomodoro_clicked.connect(self._show_focus_timer_dialog)
        self.status_bar_widget.web_connect_clicked.connect(self._on_web_connect)
        self.setStatusBar(self.status_bar_widget)

    def _setup_tray_icon(self) -> None:
        """Set up the system tray icon."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.log.warning("System tray is not available on this platform")
            self.tray_icon = None
            return

        self.tray_icon = QSystemTrayIcon(self)

        # Full-color app icon for notification popups (not the monochrome tray icon)
        self._notification_icon = self._get_icon("pytodo-qt.svg")

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
        self._tray_menu.addAction(self.tr("Show"), self.show)
        self._tray_menu.addAction(self.tr("Hide"), self.hide)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction(self.tr("Quit"), self._quit_application)

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

            self.status_bar_widget.set_sync_status("syncing")

            # Pull first
            pull_op = create_pull_operation(peer.address, peer.port, device_id=device.id)
            pull_result = await self._sync_queue.execute(pull_op)
            pull_ok = pull_result.success
            if pull_ok:
                _, _, _, changed = self._merge_sync_data_internal(
                    pull_result.data, device.name or peer.hostname
                )
                self._record_unseen_changes(changed)

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
                from ..core.models import advance_all_overdue_recurring

                advance_all_overdue_recurring(self._database)
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

    def _on_undo_index_changed(self) -> None:
        """Notify auto-sync scheduler and web clients of changes."""
        active_list = self._database.active_list
        if active_list and active_list.private:
            return
        self._auto_scheduler.notify_change()
        if self._web_server is not None:
            self._web_server.notify_clients()

    def _on_auto_push(self) -> None:
        """Handle debounced auto-push: push local data to online trusted peers."""
        if self._auto_syncing_devices:
            logger.log.info("Auto-push skipped: sync already in progress")
            return
        logger.log.info("Auto-push triggered")
        asyncio.ensure_future(self._async_auto_push())

    async def _async_auto_push(self) -> None:
        """Push local data to all online trusted peers (change-triggered)."""
        discovery = get_discovery_service()
        online_peers = {p.fingerprint: p for p in discovery.get_peers() if not p.is_local}
        if not online_peers:
            logger.log.info("Auto-push: no online peers found")
            return

        devices = [
            d
            for d in self._storage.get_all_devices()
            if d.trust_level == "trusted" and d.fingerprint in online_peers
        ]
        if not devices:
            logger.log.info("Auto-push: no trusted devices among online peers")
            return

        logger.log.info("Auto-push to %d trusted peer(s)", len(devices))
        any_success = False
        any_failure = False
        for device in devices:
            peer = online_peers[device.fingerprint]
            peer_label = device.name or device.fingerprint[:19]
            try:
                self.status_bar_widget.set_sync_status("syncing")
                allowed_list_ids = self._storage.get_syncable_list_ids_for_device(device.id)
                push_data = json.dumps(self._database.to_dict_for_device(allowed_list_ids)).encode(
                    "utf-8"
                )
                push_op = create_push_operation(
                    peer.address, peer.port, push_data, device_id=device.id
                )
                result = await self._sync_queue.execute(push_op)
                if result.success:
                    self._track_device(device.fingerprint, f"{peer.address}:{peer.port}")
                    any_success = True
                    logger.log.info("Auto-push to %s succeeded", peer_label)
                else:
                    any_failure = True
                    logger.log.warning("Auto-push to %s failed: %s", peer_label, result.status.name)
            except Exception as e:
                any_failure = True
                logger.log.warning("Auto-push to %s error: %s", peer_label, e)

        if any_failure:
            self.status_bar_widget.set_sync_status("error")
        elif any_success:
            self.status_bar_widget.set_sync_status("success", auto=True)

    def _on_auto_sync(self) -> None:
        """Handle periodic auto-sync: full pull+push with online trusted peers."""
        if self._auto_syncing_devices:
            logger.log.info("Auto-sync periodic skipped: sync already in progress")
            return
        logger.log.info("Auto-sync periodic triggered")
        asyncio.ensure_future(self._async_auto_periodic_sync())

    async def _async_auto_periodic_sync(self) -> None:
        """Periodic full pull+push with all online trusted peers."""
        discovery = get_discovery_service()
        online_peers = {p.fingerprint: p for p in discovery.get_peers() if not p.is_local}
        if not online_peers:
            logger.log.info("Periodic auto-sync: no online peers found")
            return

        devices = [
            d
            for d in self._storage.get_all_devices()
            if d.trust_level == "trusted" and d.fingerprint in online_peers
        ]
        if not devices:
            logger.log.info("Periodic auto-sync: no trusted devices among online peers")
            return

        logger.log.info("Periodic auto-sync with %d trusted peer(s)", len(devices))
        for device in devices:
            if device.id in self._auto_syncing_devices:
                continue
            peer = online_peers[device.fingerprint]
            await self._auto_sync_with_device(device, peer)

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
                self.status_bar_widget.set_sync_status("syncing")

                # Pull first
                pull_op = create_pull_operation(peer.address, peer.port, device_id=device.id)
                pull_result = await self._sync_queue.execute(pull_op)
                pull_ok = pull_result.success
                if pull_ok:
                    _, _, _, changed = self._merge_sync_data_internal(
                        pull_result.data, device.name or peer.hostname
                    )
                    self._record_unseen_changes(changed)

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

    def _start_web_server(self) -> None:
        """Start the embedded web server if enabled."""
        if not self._config.web.enabled:
            return
        try:
            self._web_server = WebServer(
                database=self._database,
                save_callback=self._web_save_and_refresh,
                config=self._config.web,
                config_manager=self._config_manager,
                main_window=self,
            )
            # Create app synchronously so PIN is available immediately
            self._web_server.create_app()
            asyncio.ensure_future(
                self._web_server.start(
                    host=self._config.web.bind_address,
                    port=self._config.web.port,
                )
            )
            self.status_bar_widget.set_web_status(
                True, port=self._config.web.port, pin=self._web_server.pairing_pin
            )
            logger.log.info("Web server started on port %d", self._config.web.port)
        except Exception as e:
            logger.log.warning("Failed to start web server: %s", e)

    def _stop_web_server(self) -> None:
        """Stop the embedded web server."""
        if self._web_server is None:
            return
        try:
            asyncio.ensure_future(self._web_server.stop())
            self._web_server = None
            self.status_bar_widget.set_web_status(False)
        except Exception as e:
            logger.log.warning("Error stopping web server: %s", e)

    def _web_save_and_refresh(self) -> None:
        """Save database and refresh UI after a web API write."""
        self._storage.save_database(self._database)
        self._refresh_ui()
        self._auto_scheduler.notify_change()

    def _get_sync_data(self) -> bytes:
        """Get database as bytes for sync (excludes private lists)."""
        return json.dumps(self._database.to_dict_for_sync()).encode("utf-8")

    def _on_sync_received(self, data: bytes, peer_fingerprint: str = "") -> None:
        """Handle received sync data from incoming push."""
        self.status_bar_widget.set_sync_status("syncing")
        try:
            peer_name = ""
            if peer_fingerprint:
                device = self._storage.get_device_by_fingerprint(peer_fingerprint)
                if device:
                    peer_name = device.name
            merged, local_newer, identical, changed = self._merge_sync_data_internal(
                data, peer_name
            )
            self._record_unseen_changes(changed)
            if merged > 0:
                from ..core.models import advance_all_overdue_recurring

                advance_all_overdue_recurring(self._database)
                self._save_database()
                self._refresh_ui()
                if self._web_server is not None:
                    self._web_server.notify_clients()
                logger.log.info("Received and merged %d items from remote push", merged)
            else:
                logger.log.info(
                    "Received sync data: %d local newer, %d identical", local_newer, identical
                )
            self.status_bar_widget.set_sync_status("success")
        except Exception as e:
            self.status_bar_widget.set_sync_status("error")
            logger.log.exception("Error processing sync data: %s", e)

    def _record_unseen_changes(self, changed_list_ids: set[UUID]) -> None:
        """Record lists with unviewed sync changes, excluding the active list."""
        self._unseen_changes |= changed_list_ids
        if self._database.active_list_id:
            self._unseen_changes.discard(self._database.active_list_id)

    def _merge_sync_data_internal(
        self, data: bytes, peer_name: str = ""
    ) -> tuple[int, int, int, set[UUID]]:
        """Internal merge logic.

        Returns:
            (merged_count, local_newer_count, identical_count, changed_list_ids)
        """
        remote_db = Database.from_dict(json.loads(data.decode("utf-8")))
        merged_count = 0
        local_newer_count = 0
        identical_count = 0
        changed_list_ids: set[UUID] = set()

        for list_id, remote_list in remote_db.lists.items():
            if list_id in self._database.lists:
                local_list = self._database.lists[list_id]
                # List-level metadata LWW
                if remote_list.updated_at > local_list.updated_at:
                    if remote_list.name != local_list.name:
                        local_list.name = self._database.resolve_name_collision(
                            remote_list.name, peer_name
                        )
                    local_list.deleted = remote_list.deleted
                    local_list.updated_at = remote_list.updated_at
                    merged_count += 1
                    changed_list_ids.add(list_id)
                for item_id, remote_item in remote_list.items.items():
                    if item_id in local_list.items:
                        local_item = local_list.items[item_id]
                        if remote_item.updated_at > local_item.updated_at:
                            local_list.items[item_id] = remote_item
                            merged_count += 1
                            changed_list_ids.add(list_id)
                        elif remote_item.updated_at < local_item.updated_at:
                            local_newer_count += 1
                        elif remote_item.to_dict() != local_item.to_dict():
                            # Same timestamp but different data (e.g. new fields
                            # from schema upgrade) — adopt remote version
                            local_list.items[item_id] = remote_item
                            merged_count += 1
                            changed_list_ids.add(list_id)
                        else:
                            identical_count += 1
                    else:
                        local_list.items[item_id] = remote_item
                        merged_count += 1
                        changed_list_ids.add(list_id)
            else:
                remote_list.name = self._database.resolve_name_collision(
                    remote_list.name, peer_name
                )
                self._database.lists[list_id] = remote_list
                merged_count += len(remote_list.items)
                changed_list_ids.add(list_id)

        # Merge focus sessions (append-only — unique by UUID)
        import contextlib

        local_session_ids = {s.id for s in self._database.focus_sessions}
        for session in remote_db.focus_sessions:
            if session.id not in local_session_ids:
                self._database.focus_sessions.append(session)
                with contextlib.suppress(Exception):
                    self._storage.save_focus_session(session)
                merged_count += 1

        return merged_count, local_newer_count, identical_count, changed_list_ids

    def _load_database(self) -> None:
        """Load the database from SQLite."""
        sqlite_path = self._config_manager.db_file

        # Open SQLite storage and load database
        try:
            self._storage.open()
            self._database = self._storage.load_database()
            logger.log.info("Loaded database from %s", sqlite_path)
        except Exception as e:
            logger.log.exception("Error loading database: %s", e)
            QMessageBox.warning(
                self, self.tr("Load Error"), self.tr(f"Failed to load database: {e}")
            )
            self._database = Database()

        # Analytics service (pandas data pipeline)
        from ..core.analytics import AnalyticsService

        self._analytics = AnalyticsService(
            self._storage.connection, self._config.pomodoro.work_duration
        )
        if hasattr(self, "calendar_view"):
            self.calendar_view.set_analytics(self._analytics)
        goal = self._config.pomodoro.daily_goal
        self._best_streak = self._analytics.streak(goal if goal > 0 else 1)

        # Set active list from config (overrides stored active_list_id)
        active_list_name = self._config.database.active_list
        if active_list_name:
            self._database.set_active_list_by_name(active_list_name)
        elif self._database.lists and self._database.active_list_id is None:
            # Set first list as active if none set
            self._database.active_list_id = next(iter(self._database.lists.keys()))

        # Auto-advance overdue recurring items, then reconcile board columns
        self._advance_overdue_recurring()
        if self._config.database.view_mode == "board":
            self._reconcile_board_columns()

        self._refresh_ui()

    def _save_database(self) -> bool:
        """Save the database to SQLite."""
        try:
            self._storage.save_database(self._database)
            logger.log.info("Saved database to %s", self._config_manager.db_file)
            return True
        except Exception as e:
            logger.log.exception("Error saving database: %s", e)
            QMessageBox.warning(
                self, self.tr("Save Error"), self.tr(f"Failed to save database: {e}")
            )
            return False

    def _check_timed_overdue(self) -> None:
        """Auto-advance overdue recurring items and refresh UI for timed items."""
        from datetime import date

        from ..core.models import advance_all_overdue_recurring

        # Auto-advance overdue recurring items (handles midnight rollover)
        count = advance_all_overdue_recurring(self._database)
        if count > 0:
            self._reconcile_board_columns()
            self._save_database()
            if self._web_server is not None:
                self._web_server.notify_clients()

        active_list = self._database.active_list
        if active_list is None:
            if count > 0:
                self._refresh_ui()
            return
        today = date.today()
        needs_refresh = count > 0
        if not needs_refresh:
            for item in active_list.active_items():
                if item.due_date == today and item.due_time is not None and not item.complete:
                    needs_refresh = True
                    break
        if needs_refresh:
            self._refresh_ui()

        # Refresh status bar PIN (auto-regenerates when expired)
        if self._web_server is not None:
            self.status_bar_widget.set_web_status(
                True, port=self._config.web.port, pin=self._web_server.pairing_pin
            )

        # Periodic notification check (piggyback on the 60s timer)
        self._check_due_notifications()

    def _check_due_notifications(self) -> None:
        """Send desktop notifications for due-today and overdue items.

        Checks all lists for items that are due today or overdue,
        and sends a system tray notification if the item hasn't been
        notified today. Updates notified_at to prevent re-alerting.
        """
        from datetime import date as _date
        from datetime import datetime as _datetime

        from ..core.models import is_due_today, is_overdue

        notif_config = self._config.notifications
        if not notif_config.enabled or self.tray_icon is None:
            return

        today = _date.today()
        today_start_ms = int(_datetime(today.year, today.month, today.day).timestamp() * 1000)

        overdue_items: list[str] = []
        due_today_items: list[str] = []

        for lst in self._database.lists.values():
            if lst.deleted or lst.private:
                continue
            for item in lst.active_items():
                if item.complete:
                    continue
                # Skip if already notified today
                if item.notified_at >= today_start_ms:
                    continue
                if notif_config.notify_overdue and is_overdue(item.due_date, item.due_time):
                    overdue_items.append(item.reminder)
                    item.notified_at = int(_datetime.now().timestamp() * 1000)
                    item.mark_updated()
                elif notif_config.notify_due_today and is_due_today(item.due_date):
                    due_today_items.append(item.reminder)
                    item.notified_at = int(_datetime.now().timestamp() * 1000)
                    item.mark_updated()

        if not overdue_items and not due_today_items:
            return

        # Build notification message
        lines: list[str] = []
        if overdue_items:
            lines.append(
                self.tr("Overdue (%n item(s))", "", len(overdue_items))
                + ": "
                + ", ".join(overdue_items[:5])
            )
            if len(overdue_items) > 5:
                lines[-1] += f" (+{len(overdue_items) - 5} more)"
        if due_today_items:
            lines.append(
                self.tr("Due today (%n item(s))", "", len(due_today_items))
                + ": "
                + ", ".join(due_today_items[:5])
            )
            if len(due_today_items) > 5:
                lines[-1] += f" (+{len(due_today_items) - 5} more)"

        self.tray_icon.showMessage(
            self.tr("PyTodo-Qt Reminders"),
            "\n".join(lines),
            self._notification_icon,
            10000,
        )

        # Save the notified_at updates
        self._save_database()

        # IP change detection
        from ..core.network import get_lan_ip as _get_current_ip

        current_ip = _get_current_ip()
        if current_ip and current_ip != self._last_known_ip:
            old_ip = self._last_known_ip
            self._last_known_ip = current_ip
            logger.log.info("Network address changed: %s → %s", old_ip, current_ip)
            self.status_bar_widget.show_message(self.tr(f"Network address changed to {current_ip}"))

    def _active_view_widget(self) -> TodoTableWidget | KanbanBoardWidget:
        """Return the currently visible view widget.

        Returns the table or board widget for action dispatching.
        Calendar view also supports the shared API but returns
        through the board/table interface for type compatibility.
        """
        from .widgets.calendar_view import CalendarViewWidget

        w = self._view_stack.currentWidget()
        if isinstance(w, KanbanBoardWidget):
            return w
        if isinstance(w, CalendarViewWidget):
            return w  # type: ignore[return-value]
        return self.todo_table

    def _refresh_ui(self) -> None:
        """Refresh all UI components."""
        self._refreshing = True
        try:
            # If active list was deleted (e.g. via sync), switch to another
            active = self._database.active_list
            if active and active.deleted:
                remaining = list(self._database.active_lists())
                if remaining:
                    self._database.set_active_list(remaining[0].id)
                    self._config.database.active_list = remaining[0].name
                else:
                    self._database.active_list_id = None
                    self._config.database.active_list = ""
                self._config_manager.save()

            self.list_selector.set_database(self._database)
            self.list_selector.set_unseen(self._unseen_changes)
            idx = self._view_stack.currentIndex()
            if idx == 0:
                self.todo_table.set_list(self._database.active_list)
            elif idx == 1:
                self.kanban_board.set_list(self._database.active_list)
            else:
                self.calendar_view.set_list(self._database.active_list)
            self._update_tags()
            self._update_status()
            self._update_detail_panel()
        finally:
            self._refreshing = False

    def _update_tags(self) -> None:
        """Update the tag filter combo with tags from the active list."""
        active_list = self._database.active_list
        tags: set[str] = set()
        if active_list:
            for item in active_list.active_items():
                tags.update(item.tags)
        self.search_filter.update_tags(sorted(tags))

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
        self._update_daily_goal()

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

    def _collect_known_tags(self) -> list[str]:
        """Collect all unique tags from the active list for auto-completion."""
        tags: set[str] = set()
        if self._database.active_list:
            for item in self._database.active_list.active_items():
                tags.update(item.tags)
        return sorted(tags)

    def _on_add_todo(self) -> None:
        """Handle add to-do action."""
        if self._database.active_list is None:
            if not list(self._database.active_lists()):
                QMessageBox.information(
                    self, self.tr("No List"), self.tr("You need to create a list first.")
                )
                self._on_add_list()
                return
            else:
                # Pick a list
                list_name, ok = QInputDialog.getItem(
                    self,
                    self.tr("Select List"),
                    self.tr("Select a list:"),
                    self._database.list_names(),
                )
                if not ok or not list_name:
                    return
                self._database.set_active_list_by_name(list_name)

        known_tags = self._collect_known_tags()
        # Pass the board-column list so the dialog's Column dropdown
        # is populated and the item's board_column is written directly
        # by the dialog (defaults to the first column when no explicit
        # selected_column is passed).
        cols = list(self._database.active_list.board_columns)
        dialog = AddTodoDialog(
            self,
            known_tags=known_tags,
            columns=cols,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        item = dialog.get_item()
        if item is None or self._database.active_list is None:
            return

        # Fallback for the edge case where the dialog was constructed
        # without columns (shouldn't happen from this entry point, but
        # defensive) — first column wins.
        if not item.board_column and cols:
            item.board_column = cols[0]

        from .commands import AddItemCommand

        list_id = self._database.active_list.id
        cmd = AddItemCommand(self, list_id, item)
        self._undo_stack.push(cmd)

        # Create child items from inline subtask syntax ("task: a, b, c")
        for sub_text in dialog.get_subtask_reminders():
            child = TodoItem(
                reminder=sub_text,
                priority=item.priority,
                due_date=item.due_date,
                due_time=item.due_time,
                parent_id=item.id,
                board_column=item.board_column,
            )
            sub_cmd = AddItemCommand(self, list_id, child)
            self._undo_stack.push(sub_cmd)

    def _on_add_subtask(self, parent_id: UUID | None = None) -> None:
        """Handle add subtask action."""
        active_list = self._database.active_list
        if active_list is None:
            return

        # If no parent_id given, use selected item
        if parent_id is None:
            selected = self._active_view_widget().get_selected_item_ids()
            if len(selected) != 1:
                return
            parent_id = selected[0]

        # Validate parent exists and is not itself a subtask
        parent = active_list.get_item(parent_id)
        if not parent or parent.parent_id is not None:
            return

        known_tags = self._collect_known_tags()
        item = AddTodoDialog.create_item(self, title=self.tr("Add Subtask"), known_tags=known_tags)
        if item is not None:
            item.parent_id = parent_id
            # Assign default board column (may get promoted to top-level later)
            if not item.board_column:
                cols = active_list.board_columns
                if cols:
                    item.board_column = cols[0]
            from .commands import AddItemCommand

            cmd = AddItemCommand(self, active_list.id, item)
            self._undo_stack.push(cmd)

    def _on_delete_todo(self) -> None:
        """Handle delete to-do action."""
        item_ids = self._active_view_widget().get_selected_item_ids()
        if not item_ids:
            QMessageBox.information(self, self.tr("Delete"), self.tr("No items selected."))
            return

        active_list = self._database.active_list
        if active_list is None:
            return

        # Stop focus timer if running on a deleted item
        if self._pomodoro.item_id in item_ids:
            self._on_stop_focus()

        from .commands import DeleteItemsCommand

        cmd = DeleteItemsCommand(self, active_list.id, item_ids)
        self._undo_stack.push(cmd)

    def _on_toggle_todo(self) -> None:
        """Handle toggle to-do action."""
        item_ids = self._active_view_widget().get_selected_item_ids()
        if not item_ids:
            return

        active_list = self._database.active_list
        if active_list is None:
            return

        # Split items into recurring (completing) and normal groups
        normal_states: list[tuple[UUID, bool]] = []
        recurring_commands = []

        for item_id in item_ids:
            item = active_list.get_item(item_id)
            if not item:
                continue
            # Use recurring path only for incomplete recurring items whose
            # recurrence hasn't already been exhausted.
            already_exhausted = (
                item.recurrence_end_count is not None
                and item.recurrence_count >= item.recurrence_end_count
            )
            if (
                item.is_recurring
                and not item.complete
                and not already_exhausted
                and item.due_date
                and item.recurrence_type
            ):
                from ..core.models import compute_next_due_date, is_recurrence_ended
                from .commands import ToggleCompleteRecurringCommand

                next_due = compute_next_due_date(
                    item.due_date, item.recurrence_type, item.recurrence_interval
                )
                ended = is_recurrence_ended(item, next_due)
                cmd = ToggleCompleteRecurringCommand(
                    self,
                    active_list.id,
                    item_id,
                    old_due_date=item.due_date,
                    new_due_date=None if ended else next_due,
                    old_count=item.recurrence_count,
                    recurrence_ended=ended,
                )
                recurring_commands.append(cmd)
            else:
                normal_states.append((item_id, item.complete))

        if normal_states:
            from .commands import ToggleCompleteCommand

            cmd = ToggleCompleteCommand(self, active_list.id, normal_states)
            self._undo_stack.push(cmd)

        for rcmd in recurring_commands:
            self._undo_stack.push(rcmd)

    def _on_add_list(self) -> None:
        """Handle add list action."""
        new_list = AddListDialog.create_list(self, self._database)
        if new_list is None:
            return

        from .commands import AddListCommand

        prev_active = self._database.active_list_id
        cmd = AddListCommand(self, new_list, prev_active)
        self._undo_stack.push(cmd)

    def _on_delete_list(self) -> None:
        """Handle delete list action."""
        active_list = self._database.active_list
        if active_list is None:
            return

        reply = QMessageBox.question(
            self,
            self.tr("Confirm Delete"),
            self.tr(f'Delete list "{active_list.name}" and all its items?'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            from .commands import DeleteListCommand

            # Find another list to make active after deletion
            new_active_id: UUID | None = None
            for lst in self._database.active_lists():
                if lst.id != active_list.id:
                    new_active_id = lst.id
                    break

            cmd = DeleteListCommand(self, active_list.id, active_list.name, new_active_id)
            self._undo_stack.push(cmd)

    def _on_rename_list(self) -> None:
        """Handle rename list action."""
        active_list = self._database.active_list
        if active_list is None:
            return

        name, ok = QInputDialog.getText(
            self,
            self.tr("Rename List"),
            self.tr("Enter new name:"),
            text=active_list.name,
        )
        if not ok or not name.strip():
            return

        from .commands import RenameListCommand

        cmd = RenameListCommand(self, active_list.id, active_list.name, name.strip())
        self._undo_stack.push(cmd)

    def _on_toggle_private(self) -> None:
        """Handle toggle private action."""
        active_list = self._database.active_list
        if active_list is None:
            return

        from .commands import TogglePrivateCommand

        cmd = TogglePrivateCommand(self, active_list.id, active_list.private)
        self._undo_stack.push(cmd)

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
                    msg = self.tr(f'List "{updated_list.name}" is now private')
                else:
                    rules = self._storage.get_sync_rules_for_list(updated_list.id)
                    if rules:
                        msg = self.tr(f'List "{updated_list.name}" syncs to selected groups')
                    else:
                        msg = self.tr(f'List "{updated_list.name}" syncs to all devices')
                self.status_bar_widget.show_message(msg, 3000)

    @pyqtSlot(object)
    def _on_list_changed(self, todo_list: TodoList | None) -> None:
        """Handle list selection change."""
        self._analytics.invalidate()
        if self._view_stack.currentIndex() == 0:
            self.todo_table.set_list(todo_list)
        else:
            self.kanban_board.set_list(todo_list)

        # Clear unseen indicator for the list being viewed
        if todo_list:
            self._unseen_changes.discard(todo_list.id)
            self.list_selector.set_unseen(self._unseen_changes)

        # Update config
        if todo_list:
            self._config.database.active_list = todo_list.name
            self._config_manager.save()

        self._update_status()

    def _on_item_priority_changed(self, item_id: UUID, priority: int) -> None:
        """Handle item priority change."""
        if self._refreshing:
            return
        active_list = self._database.active_list
        if active_list:
            item = active_list.get_item(item_id)
            if item:
                from .commands import EditPriorityCommand

                cmd = EditPriorityCommand(self, active_list.id, item_id, item.priority, priority)
                self._undo_stack.push(cmd)

    def _on_item_reminder_changed(self, item_id: UUID, text: str) -> None:
        """Handle item reminder text change."""
        if self._refreshing:
            return
        active_list = self._database.active_list
        if active_list:
            item = active_list.get_item(item_id)
            if item:
                from .commands import EditReminderCommand

                cmd = EditReminderCommand(self, active_list.id, item_id, item.reminder, text)
                self._undo_stack.push(cmd)

    def _on_item_due_date_changed(self, item_id: UUID, due_date) -> None:
        """Handle item due date change."""
        if self._refreshing:
            return
        active_list = self._database.active_list
        if active_list:
            item = active_list.get_item(item_id)
            if item:
                from .commands import EditDueDateCommand

                cmd = EditDueDateCommand(
                    self,
                    active_list.id,
                    item_id,
                    item.due_date,
                    due_date,
                    old_due_time=item.due_time,
                )
                self._undo_stack.push(cmd)

    def _on_item_due_time_changed(self, item_id: UUID, due_time) -> None:
        """Handle item due time change."""
        if self._refreshing:
            return
        active_list = self._database.active_list
        if active_list:
            item = active_list.get_item(item_id)
            if item:
                from .commands import EditDueTimeCommand

                cmd = EditDueTimeCommand(self, active_list.id, item_id, item.due_time, due_time)
                self._undo_stack.push(cmd)

    def _on_date_and_time_dropped(self, item_id: UUID, due_date, due_time) -> None:
        """Handle task dropped with both date and time — single undo macro."""
        if self._refreshing:
            return
        active_list = self._database.active_list
        if not active_list:
            return
        item = active_list.get_item(item_id)
        if not item:
            return
        from .commands import EditDueDateCommand, EditDueTimeCommand

        self._undo_stack.beginMacro("Set due date and time")
        cmd_date = EditDueDateCommand(
            self, active_list.id, item_id, item.due_date, due_date, old_due_time=item.due_time
        )
        self._undo_stack.push(cmd_date)
        cmd_time = EditDueTimeCommand(self, active_list.id, item_id, item.due_time, due_time)
        self._undo_stack.push(cmd_time)
        self._undo_stack.endMacro()

    def _on_edit_recurrence(self) -> None:
        """Handle edit recurrence action."""
        item_ids = self._active_view_widget().get_selected_item_ids()
        if len(item_ids) != 1:
            return
        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.get_item(item_ids[0])
        if not item:
            return

        from .dialogs.edit_recurrence import EditRecurrenceDialog

        dialog = EditRecurrenceDialog(item, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            new_rec = dialog.get_recurrence()
            old_rec = (
                item.recurrence_type,
                item.recurrence_interval,
                item.recurrence_end_date,
                item.recurrence_end_count,
            )
            if new_rec != old_rec:
                from .commands import EditRecurrenceCommand

                cmd = EditRecurrenceCommand(self, active_list.id, item.id, old_rec, new_rec)
                self._undo_stack.push(cmd)

    def _on_edit_tags(self) -> None:
        """Handle edit tags action (from menu/shortcut)."""
        item_ids = self._active_view_widget().get_selected_item_ids()
        if len(item_ids) != 1:
            return
        self._on_edit_tags_for_item(item_ids[0])

    def _on_edit_tags_for_item(self, item_id: UUID) -> None:
        """Show tag editor for a specific item."""
        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.get_item(item_id)
        if not item:
            return

        current_text = ", ".join(item.tags) if item.tags else ""
        text, ok = QInputDialog.getText(
            self,
            self.tr("Edit Tags"),
            self.tr("Tags (comma-separated, e.g. @work, @errands):"),
            text=current_text,
        )
        if not ok:
            return

        # Parse tags: split by comma, strip, deduplicate, prefix @ if missing
        new_tags: list[str] = []
        seen: set[str] = set()
        for raw in text.split(","):
            tag = raw.strip()
            if not tag:
                continue
            if not tag.startswith("@"):
                tag = f"@{tag}"
            if tag not in seen:
                new_tags.append(tag)
                seen.add(tag)

        if new_tags != item.tags:
            from .commands import EditTagsCommand

            cmd = EditTagsCommand(self, active_list.id, item.id, item.tags, new_tags)
            self._undo_stack.push(cmd)

    def _on_edit_due_date(self) -> None:
        """Handle edit due date action — single or multi-select."""
        item_ids = self._active_view_widget().get_selected_item_ids()
        if not item_ids:
            return
        active_list = self._database.active_list
        if active_list is None:
            return

        if len(item_ids) == 1:
            # Single item — use existing DueDatePickerDialog
            item = active_list.get_item(item_ids[0])
            if not item:
                return
            from .widgets.todo_table import DueDatePickerDialog

            dialog = DueDatePickerDialog(item.due_date, item.due_time, self)
            if dialog.exec() == dialog.DialogCode.Accepted:
                new_date = dialog.get_date()
                new_time = dialog.get_time()
                if new_date != item.due_date:
                    from .commands import EditDueDateCommand

                    cmd = EditDueDateCommand(
                        self, active_list.id, item.id, item.due_date, new_date, item.due_time
                    )
                    self._undo_stack.push(cmd)
                if new_time != item.due_time:
                    from .commands import EditDueTimeCommand

                    cmd = EditDueTimeCommand(self, active_list.id, item.id, item.due_time, new_time)
                    self._undo_stack.push(cmd)
        else:
            # Multiple items — use BatchDueDateDialog
            items = [active_list.get_item(iid) for iid in item_ids]
            valid_items = [i for i in items if i is not None]
            if not valid_items:
                return

            from .dialogs.batch_due_date import BatchDueDateDialog

            dialog = BatchDueDateDialog(valid_items, self)
            if dialog.exec() == dialog.DialogCode.Accepted:
                changes = dialog.get_changes()
                if not changes:
                    return
                from .commands import EditDueDateCommand, EditDueTimeCommand

                self._undo_stack.beginMacro("Edit due dates")
                for item_id, new_date, new_time in changes:
                    item = active_list.get_item(item_id)
                    if not item:
                        continue
                    if new_date != item.due_date:
                        cmd = EditDueDateCommand(
                            self, active_list.id, item.id, item.due_date, new_date, item.due_time
                        )
                        self._undo_stack.push(cmd)
                    if new_time != item.due_time:
                        cmd_t = EditDueTimeCommand(
                            self, active_list.id, item.id, item.due_time, new_time
                        )
                        self._undo_stack.push(cmd_t)
                self._undo_stack.endMacro()

    def _on_filter_changed(self, filter_state) -> None:
        """Handle filter state change."""
        self.todo_table.set_filter(filter_state)
        self.kanban_board.set_filter(filter_state)
        self.calendar_view.set_filter(filter_state)

    def _on_show_completed_requested(self) -> None:
        """Kanban 'All done!' empty state — flip the status filter
        to 'Completed' so the user's just-finished tasks come back
        into view."""
        self.search_filter.status_combo.setCurrentIndex(2)

    def _on_search_focus(self) -> None:
        """Handle Ctrl+F shortcut."""
        self.search_filter.focus_search()

    def _on_search_escape(self) -> None:
        """Handle Escape shortcut."""
        self.search_filter.handle_escape()

    def _on_switch_list_by_index(self, index: int) -> None:
        """Handle Ctrl+1..9 shortcut to switch list by position."""
        self.list_selector.set_current_by_index(index)

    def _on_shortcuts_help(self) -> None:
        """Handle F1 shortcut to show keyboard shortcuts help."""
        dialog = ShortcutsHelpDialog(self)
        dialog.exec()

    def _on_start_focus(self) -> None:
        """Start a focus timer on the selected item."""
        item_ids = self._active_view_widget().get_selected_item_ids()
        if not item_ids:
            self.status_bar_widget.show_message(self.tr("Select an item to start focus timer"))
            return
        self._start_focus_on_item(item_ids[0])

    def _on_context_menu_focus(self, item_id: object) -> None:
        """Handle 'Start Focus Session' from context menu."""
        from uuid import UUID as _UUID

        if isinstance(item_id, _UUID):
            self._start_focus_on_item(item_id)

    def _on_set_time_block(self, item_id: object) -> None:
        """Handle 'Set Time Block...' from context menu."""
        from uuid import UUID as _UUID

        if not isinstance(item_id, _UUID):
            return
        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.get_item(item_id)
        if item is None:
            return

        blocks = [
            "None",
            "Early Morning",
            "Morning",
            "Late Morning",
            "Noon",
            "Early Afternoon",
            "Afternoon",
            "Late Afternoon",
            "Early Evening",
            "Evening",
            "Late Evening",
            "Night",
            "Late Night",
            "Midnight",
        ]
        block_ids = [
            "",
            "early_morning",
            "morning",
            "late_morning",
            "noon",
            "early_afternoon",
            "afternoon",
            "late_afternoon",
            "early_evening",
            "evening",
            "late_evening",
            "night",
            "late_night",
            "midnight",
        ]
        current_idx = 0
        if item.due_time_block and item.due_time_block in block_ids:
            current_idx = block_ids.index(item.due_time_block)

        choice, ok = QInputDialog.getItem(
            self,
            self.tr("Set Time Block"),
            self.tr("Time block:"),
            blocks,
            current_idx,
            False,
        )
        if ok:
            idx = blocks.index(choice)
            new_block = block_ids[idx] if block_ids[idx] else None
            if new_block != item.due_time_block:
                from .commands import SetFieldCommand

                cmd = SetFieldCommand(self, active_list.id, item_id, "due_time_block", new_block)
                self._undo_stack.push(cmd)

    def _on_set_event_date(self, item_id: object) -> None:
        """Handle 'Set Event Date...' from context menu."""
        from uuid import UUID as _UUID

        if not isinstance(item_id, _UUID):
            return
        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.get_item(item_id)
        if item is None:
            return

        from datetime import date as _date

        from PyQt6.QtWidgets import QDateEdit as _QDateEdit

        dlg = QDialog(self)
        dlg.setWindowTitle(self.tr("Set Event Date"))
        lay = QVBoxLayout(dlg)
        date_edit = _QDateEdit()
        date_edit.setCalendarPopup(True)
        if item.event_date:
            date_edit.setDate(
                QDate(item.event_date.year, item.event_date.month, item.event_date.day)
            )
        else:
            date_edit.setDate(QDate.currentDate())
        lay.addWidget(date_edit)

        from PyQt6.QtWidgets import QDialogButtonBox as _QBB

        btn_box = _QBB(
            _QBB.StandardButton.Ok | _QBB.StandardButton.Cancel | _QBB.StandardButton.Reset
        )
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        btn_box.button(_QBB.StandardButton.Reset).clicked.connect(lambda: dlg.done(2))
        lay.addWidget(btn_box)

        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted:
            qd = date_edit.date()
            new_date = _date(qd.year(), qd.month(), qd.day())
            if new_date != item.event_date:
                from .commands import SetFieldCommand

                cmd = SetFieldCommand(self, active_list.id, item_id, "event_date", new_date)
                self._undo_stack.push(cmd)
        elif result == 2:
            if item.event_date is not None:
                from .commands import SetFieldCommand

                cmd = SetFieldCommand(self, active_list.id, item_id, "event_date", None)
                self._undo_stack.push(cmd)

    def _is_any_timer_active(self) -> bool:
        """Check if either pomodoro or stopwatch is active."""
        from .widgets.pomodoro import TimerState
        from .widgets.stopwatch import StopwatchState

        return (
            self._pomodoro.state != TimerState.IDLE or self._stopwatch.state != StopwatchState.IDLE
        )

    def _get_active_timer_name(self) -> str:
        """Get human-readable name of the active timer, or empty string."""
        from .widgets.pomodoro import TimerState
        from .widgets.stopwatch import StopwatchState

        if self._pomodoro.state != TimerState.IDLE:
            return self._pomodoro.item_name or self.tr("another item")
        if self._stopwatch.state != StopwatchState.IDLE:
            return self._stopwatch.item_name or self.tr("another item")
        return ""

    def _stop_all_timers(self) -> None:
        """Stop both pomodoro and stopwatch timers."""
        from .widgets.pomodoro import TimerState
        from .widgets.stopwatch import StopwatchState

        if self._pomodoro.state != TimerState.IDLE:
            self._pomodoro.stop()
        if self._stopwatch.state != StopwatchState.IDLE:
            self._stopwatch.stop()

    def _prompt_stop_active_timer(self, new_mode: str) -> bool:
        """Prompt user to stop active timer. Returns True if OK to proceed."""
        active_name = self._get_active_timer_name()
        if not active_name:
            return True
        result = QMessageBox.question(
            self,
            self.tr("Timer Active"),
            self.tr(f'A session is active on "{active_name}".\nStop it and start {new_mode}?'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return False
        self._stop_all_timers()
        self._pomodoro_display_timer.stop()
        self.status_bar_widget.update_pomodoro_display("idle")
        self.kanban_board.set_focus_session_item(None)
        if self._focus_timer_dialog is not None:
            self._focus_timer_dialog.hide()
        return True

    def _start_focus_on_item(self, item_id: UUID) -> None:
        """Start a focus timer on the given item, prompting if one is already active."""
        from .widgets.pomodoro import TimerState

        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.get_item(item_id)
        if item is None:
            return

        # If any timer is running on a different item, prompt
        if (
            self._is_any_timer_active()
            and (self._pomodoro.item_id != item_id or self._pomodoro.state == TimerState.IDLE)
            and not self._prompt_stop_active_timer(self.tr("a focus session"))
        ):
            return

        self._pomodoro.start(
            item.id,
            item.reminder,
            work_duration=item.work_duration,
            break_duration=item.break_duration,
            long_break_duration=item.long_break_duration,
            pomodoro_count=item.pomodoro_count,
        )
        self._pomodoro_display_timer.start()
        self.kanban_board.set_focus_session_item(item.id)

    def _on_pause_focus(self) -> None:
        """Toggle pause/resume on whichever timer is active."""
        from .widgets.pomodoro import TimerState
        from .widgets.stopwatch import StopwatchState

        # Check pomodoro first
        pom_state = self._pomodoro.state
        if pom_state in (TimerState.WORKING, TimerState.BREAK):
            self._pomodoro.pause()
            return
        if pom_state == TimerState.PAUSED:
            self._pomodoro.resume()
            return

        # Check stopwatch
        sw_state = self._stopwatch.state
        if sw_state == StopwatchState.RUNNING:
            self._stopwatch.pause()
        elif sw_state == StopwatchState.PAUSED:
            self._stopwatch.resume()

    def _on_stop_focus(self) -> None:
        """Stop whichever timer is active."""
        from .widgets.pomodoro import TimerState
        from .widgets.stopwatch import StopwatchState

        if self._pomodoro.state != TimerState.IDLE:
            self._pomodoro.stop()
        if self._stopwatch.state != StopwatchState.IDLE:
            self._stopwatch.stop()
        self._pomodoro_display_timer.stop()
        self.status_bar_widget.update_pomodoro_display("idle")
        self.kanban_board.set_focus_session_item(None)
        if hasattr(self, "calendar_view"):
            self.calendar_view.set_active_session(None)
        if self._focus_timer_dialog is not None:
            self._focus_timer_dialog.hide()

    def _on_pomodoro_session_completed(
        self, item_id: object, seconds: int, start_iso: str = ""
    ) -> None:
        """Handle completed focus session — add time to item and record session."""
        from uuid import UUID as _UUID

        if not isinstance(item_id, _UUID):
            return
        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.get_item(item_id)
        if item is None:
            return
        from .commands import EditTimeSpentCommand

        # Record focus session FIRST (invalidates analytics cache before UI refresh)
        self._record_focus_session(
            item_id, active_list.id, start_iso, seconds, completed=True, session_type="work"
        )

        cmd = EditTimeSpentCommand(
            self, active_list.id, item_id, item.time_spent, seconds, item.pomodoro_count
        )
        self._undo_stack.push(cmd)

        self._update_daily_goal()
        self._update_focus_item_progress()
        self._update_pomodoro_display()  # Refresh session counter immediately
        self._check_milestones()

        from .widgets.pomodoro import PomodoroWidget

        spent_str = PomodoroWidget.format_time_spent(item.time_spent)
        sessions = item.pomodoro_count
        self.status_bar_widget.show_message(
            self.tr(f"Focus session complete! Total: {spent_str} ({sessions} sessions)")
        )

        # Auto-complete recurring tasks when pomodoro estimate is met
        if (
            item.estimated_pomodoros > 0
            and item.pomodoro_count >= item.estimated_pomodoros
            and not item.complete
        ):
            if item.is_recurring and item.due_date and item.recurrence_type:
                already_exhausted = (
                    item.recurrence_end_count is not None
                    and item.recurrence_count >= item.recurrence_end_count
                )
                if not already_exhausted:
                    from ..core.models import compute_next_due_date, is_recurrence_ended
                    from .commands import ToggleCompleteRecurringCommand

                    next_due = compute_next_due_date(
                        item.due_date, item.recurrence_type, item.recurrence_interval
                    )
                    ended = is_recurrence_ended(item, next_due)
                    cmd = ToggleCompleteRecurringCommand(
                        self,
                        active_list.id,
                        item_id,
                        old_due_date=item.due_date,
                        new_due_date=None if ended else next_due,
                        old_count=item.recurrence_count,
                        recurrence_ended=ended,
                    )
                    self._undo_stack.push(cmd)
                    self.status_bar_widget.show_message(
                        self.tr("Recurring task completed \u2014 next occurrence scheduled"), 3000
                    )
            else:
                self.status_bar_widget.show_message(
                    self.tr(
                        "This task has reached its estimate \u2014 consider breaking it into subtasks"
                    ),
                    5000,
                )

    def _on_pomodoro_state_changed(self, state: str) -> None:
        """Handle focus timer state transition."""
        if state == "idle":
            self._pomodoro_display_timer.stop()
            self.status_bar_widget.update_pomodoro_display("idle")
            if self._focus_timer_dialog is not None:
                self._focus_timer_dialog.hide()
        else:
            if not self._pomodoro_display_timer.isActive():
                self._pomodoro_display_timer.start()
            self._update_pomodoro_display()

        # System notifications and sound for state transitions
        if state == "break":
            self._sound_player.play("work-complete")
            if self.tray_icon is not None:
                self.tray_icon.showMessage(
                    self.tr("Focus Session Complete"),
                    self.tr("Time for a break!"),
                    self._notification_icon,
                    5000,
                )
        elif state == "working" and self._pomodoro.session_count > 0:
            self._sound_player.play("break-complete")
            if self.tray_icon is not None:
                self.tray_icon.showMessage(
                    self.tr("Break Over"),
                    self.tr("Ready for the next session?"),
                    self._notification_icon,
                    5000,
                )

    def _on_pomodoro_break_completed(
        self, item_id: object, seconds: int, start_iso: str = ""
    ) -> None:
        """Handle completed break session — record it."""
        from uuid import UUID as _UUID

        if not isinstance(item_id, _UUID):
            return
        active_list = self._database.active_list
        if active_list is None:
            return
        self._record_focus_session(
            item_id, active_list.id, start_iso, seconds, completed=True, session_type="break"
        )

    def _on_pomodoro_stopped(
        self, item_id: object, elapsed: int, start_iso: str, session_type: str
    ) -> None:
        """Handle interrupted session — record if elapsed > 60s."""
        from uuid import UUID as _UUID

        if not isinstance(item_id, _UUID):
            return
        if elapsed < 60:
            return  # Skip accidental starts
        active_list = self._database.active_list
        if active_list is None:
            return
        self._record_focus_session(
            item_id, active_list.id, start_iso, elapsed, completed=False, session_type=session_type
        )

    # --- Stopwatch handlers ---

    def _on_start_stopwatch(self) -> None:
        """Start a stopwatch on the selected item."""
        item_ids = self._active_view_widget().get_selected_item_ids()
        if not item_ids:
            self.status_bar_widget.show_message(self.tr("Select an item to start stopwatch"))
            return
        self._start_stopwatch_on_item(item_ids[0])

    def _start_stopwatch_on_item(self, item_id: UUID) -> None:
        """Start stopwatch on the given item, prompting if another timer is active."""
        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.get_item(item_id)
        if item is None:
            return

        if self._is_any_timer_active() and not self._prompt_stop_active_timer(
            self.tr("stopwatch tracking")
        ):
            return

        self._stopwatch.start(item.id, item.reminder)
        self._pomodoro_display_timer.start()
        self.kanban_board.set_focus_session_item(item.id)

    def _on_stopwatch_completed(self, item_id: object, seconds: int, start_iso: str = "") -> None:
        """Handle completed stopwatch session — add time without incrementing pomodoro count."""
        from uuid import UUID as _UUID

        if not isinstance(item_id, _UUID):
            return
        active_list = self._database.active_list
        if active_list is None:
            return
        item = active_list.get_item(item_id)
        if item is None:
            return
        from .commands import EditTimeSpentCommand

        # Record focus session FIRST (invalidates analytics cache before UI refresh)
        self._record_focus_session(
            item_id, active_list.id, start_iso, seconds, completed=True, session_type="stopwatch"
        )

        cmd = EditTimeSpentCommand(
            self,
            active_list.id,
            item_id,
            item.time_spent,
            seconds,
            item.pomodoro_count,
            increment_pomodoro=False,
        )
        self._undo_stack.push(cmd)

        from .widgets.stopwatch import StopwatchWidget

        spent_str = StopwatchWidget.format_time_spent(item.time_spent)
        elapsed_str = StopwatchWidget.format_elapsed(seconds)
        self.status_bar_widget.show_message(
            self.tr(f"Tracked {elapsed_str} \u2014 Total: {spent_str}")
        )

    def _on_stopwatch_stopped(
        self, item_id: object, elapsed: int, start_iso: str, session_type: str
    ) -> None:
        """Handle stopwatch stopped below minimum_session threshold."""
        from uuid import UUID as _UUID

        if not isinstance(item_id, _UUID):
            return
        min_s = self._config.stopwatch.minimum_session
        if elapsed < min_s:
            if elapsed > 0:
                self.status_bar_widget.show_message(
                    self.tr(
                        f"Session too short ({elapsed}s < {min_s}s minimum) \u2014 not recorded"
                    )
                )
            return
        active_list = self._database.active_list
        if active_list is None:
            return
        self._record_focus_session(
            item_id, active_list.id, start_iso, elapsed, completed=False, session_type="stopwatch"
        )

    def _on_stopwatch_state_changed(self, state: str) -> None:
        """Handle stopwatch state transition."""
        if state == "idle":
            self._pomodoro_display_timer.stop()
            self.status_bar_widget.update_pomodoro_display("idle")
            self.kanban_board.set_focus_session_item(None)
            if self._focus_timer_dialog is not None:
                self._focus_timer_dialog.hide()
            self._stop_idle_timer()
        elif state == "stopwatch_running":
            if not self._pomodoro_display_timer.isActive():
                self._pomodoro_display_timer.start()
            self._update_pomodoro_display()
            self._start_idle_timer()
        elif state == "stopwatch_paused":
            if not self._pomodoro_display_timer.isActive():
                self._pomodoro_display_timer.start()
            self._update_pomodoro_display()
            self._stop_idle_timer()

    def _start_idle_timer(self) -> None:
        """Start the idle timeout timer if configured."""
        timeout_mins = self._config.stopwatch.idle_timeout
        if timeout_mins > 0:
            from PyQt6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
            self._idle_timer.start(timeout_mins * 60 * 1000)

    def _stop_idle_timer(self) -> None:
        """Stop the idle timeout timer."""
        self._idle_timer.stop()
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def _on_idle_timeout(self) -> None:
        """Auto-pause stopwatch after idle timeout."""
        from .widgets.stopwatch import StopwatchState

        if self._stopwatch.state == StopwatchState.RUNNING:
            self._stopwatch.pause()
            timeout_mins = self._config.stopwatch.idle_timeout
            self.status_bar_widget.show_message(
                self.tr(f"Stopwatch paused \u2014 no activity for {timeout_mins}m")
            )
            if self.tray_icon is not None:
                self.tray_icon.showMessage(
                    self.tr("Stopwatch Paused"),
                    self.tr(f"No activity detected for {timeout_mins} minutes"),
                    self._notification_icon,
                    5000,
                )

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """Reset idle timer on any user input (keyboard/mouse)."""
        from PyQt6.QtCore import QEvent

        if event is not None and event.type() in (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.KeyPress,
            QEvent.Type.Wheel,
        ):
            timeout_mins = self._config.stopwatch.idle_timeout
            if timeout_mins > 0 and self._idle_timer.isActive():
                self._idle_timer.start(timeout_mins * 60 * 1000)
        return super().eventFilter(obj, event)

    def _record_focus_session(
        self,
        item_id: UUID,
        list_id: UUID,
        start_iso: str,
        duration_seconds: int,
        completed: bool,
        session_type: str,
    ) -> None:
        """Create and persist a focus session record."""
        from datetime import date, datetime

        from ..core.models import FocusSession

        session = FocusSession(
            item_id=item_id,
            list_id=list_id,
            start_time=start_iso,
            end_time=datetime.now().isoformat(),
            duration_seconds=duration_seconds,
            completed=completed,
            session_type=session_type,
            date=date.today().isoformat(),
        )
        self._database.focus_sessions.append(session)
        import contextlib

        with contextlib.suppress(Exception):
            self._storage.save_focus_session(session)

        # Invalidate analytics cache
        self._analytics.invalidate()

        # Update floating dialog if visible
        self._update_focus_timer_sessions()

    def _update_focus_timer_sessions(self) -> None:
        """Push today's sessions to the floating timer dialog."""
        if self._focus_timer_dialog is None or not self._focus_timer_dialog.isVisible():
            return
        from datetime import date

        today = date.today().isoformat()
        sessions = [
            {
                "start_time": s.start_time,
                "end_time": s.end_time,
                "duration_seconds": s.duration_seconds,
                "completed": s.completed,
                "session_type": s.session_type,
            }
            for s in self._database.focus_sessions
            if s.date == today and s.session_type == "work"
        ]
        self._focus_timer_dialog.update_sessions(sessions)

    def _get_today_session_count(self) -> int:
        """Count today's completed work/stopwatch sessions via analytics."""
        from datetime import date

        today = date.today().isoformat()
        df = self._analytics.sessions(start_date=today, end_date=today)
        work_sw = df[df["session_type"] != "break"]
        return int(work_sw["completed"].sum()) if not work_sw.empty else 0

    def _update_daily_goal(self) -> None:
        """Update daily goal display in status bar and floating dialog."""
        goal = self._config.pomodoro.daily_goal
        completed = self._get_today_session_count() if goal > 0 else 0
        self.status_bar_widget.update_daily_goal(completed, goal)
        if self._focus_timer_dialog is not None:
            self._focus_timer_dialog.update_daily_goal(completed, goal)
            streak = self._analytics.streak(goal if goal > 0 else 1)
            self._focus_timer_dialog.update_streak(streak)
            score = self._analytics.focus_score(goal)
            self._focus_timer_dialog.update_focus_score(score)

    def _check_milestones(self) -> None:
        """Check for and celebrate focus session milestones."""
        if not self._config.pomodoro.milestone_notifications:
            return

        today_count = self._get_today_session_count()
        goal = self._config.pomodoro.daily_goal

        # First session of the day
        if today_count == 1:
            self._notify_milestone(
                self.tr("Good start!"), self.tr("First focus session of the day")
            )
            return

        # Daily goal reached
        if goal > 0 and today_count == goal:
            self._notify_milestone(
                self.tr("Goal achieved!"), self.tr(f"Completed {goal} sessions today")
            )
            return

        # Lifetime milestones
        lifetime_df = self._analytics.sessions(session_type="work")
        lifetime = int(lifetime_df["completed"].sum()) if not lifetime_df.empty else 0
        milestones = {10, 25, 50, 100, 250, 500, 1000}
        if lifetime in milestones:
            self._notify_milestone(
                self.tr(f"Milestone: {lifetime}!"), self.tr(f"{lifetime} lifetime focus sessions")
            )
            return

        # Streak record
        streak = self._analytics.streak(goal if goal > 0 else 1)
        if streak > self._best_streak:
            self._best_streak = streak
            if streak >= 3:
                self._notify_milestone(
                    self.tr(f"{streak}-day streak!"), self.tr("New personal best")
                )

    def _notify_milestone(self, title: str, message: str) -> None:
        """Show a milestone notification via system tray and status bar toast."""
        if self.tray_icon is not None:
            self.tray_icon.showMessage(
                title,
                message,
                self._notification_icon,
                5000,
            )
        self.status_bar_widget.show_message(f"{title} {message}")

    def _get_focused_item_stats(self) -> tuple[int, int]:
        """Get the focused item's (pomodoro_count, estimated_pomodoros)."""
        item_id = self._pomodoro.item_id
        if item_id is None:
            return 0, 0
        for todo_list in self._database.lists.values():
            item = todo_list.get_item(item_id)
            if item is not None:
                return item.pomodoro_count, item.estimated_pomodoros
        return 0, 0

    def _get_focused_item_estimated_minutes(self) -> int:
        """Get the focused item's estimated_minutes for stopwatch display."""
        item_id = self._stopwatch.item_id
        if item_id is None:
            return 0
        for todo_list in self._database.lists.values():
            item = todo_list.get_item(item_id)
            if item is not None:
                return item.estimated_minutes
        return 0

    def _update_focus_item_progress(self) -> None:
        """Push the focused item's pomodoro stats to the floating dialog."""
        if self._focus_timer_dialog is None:
            return
        count, estimated = self._get_focused_item_stats()
        self._focus_timer_dialog.update_item_progress(count, estimated)

    def _update_pomodoro_display(self) -> None:
        """Update status bar and floating dialog with current timer state."""
        from .widgets.pomodoro import TimerState
        from .widgets.stopwatch import StopwatchState, StopwatchWidget

        # Pseudo-real-time timeline update
        if hasattr(self, "calendar_view"):
            if self._stopwatch.state != StopwatchState.IDLE and self._stopwatch.item_id:
                self.calendar_view.set_active_session(
                    self._stopwatch.item_id, self._stopwatch.elapsed_seconds, "stopwatch"
                )
            elif self._pomodoro.state != TimerState.IDLE and self._pomodoro.item_id:
                elapsed = self._pomodoro_total_duration() - self._pomodoro.remaining_seconds
                self.calendar_view.set_active_session(
                    self._pomodoro.item_id, max(0, elapsed), "work"
                )
            else:
                self.calendar_view.set_active_session(None)

        # Check if stopwatch is active
        if self._stopwatch.state != StopwatchState.IDLE:
            sw_state = self._stopwatch.state.value
            time_str = StopwatchWidget.format_elapsed(self._stopwatch.elapsed_seconds)
            self.status_bar_widget.update_pomodoro_display(sw_state, time_str)

            if self._focus_timer_dialog is not None and self._focus_timer_dialog.isVisible():
                estimated_min = self._get_focused_item_estimated_minutes()
                self._focus_timer_dialog.update_stopwatch_display(
                    sw_state,
                    self._stopwatch.elapsed_seconds,
                    self._stopwatch.item_name,
                    estimated_minutes=estimated_min,
                )
            return

        # Pomodoro display
        if self._pomodoro.state == TimerState.IDLE:
            return
        from .widgets.pomodoro import PomodoroWidget

        state = self._pomodoro.state.value
        time_str = PomodoroWidget.format_time(self._pomodoro.remaining_seconds)
        self.status_bar_widget.update_pomodoro_display(state, time_str)

        if self._focus_timer_dialog is not None and self._focus_timer_dialog.isVisible():
            count, estimated = self._get_focused_item_stats()
            self._focus_timer_dialog.update_display(
                state,
                self._pomodoro.remaining_seconds,
                self._pomodoro.item_name,
                self._pomodoro.session_count,
                self._pomodoro.sessions_before_long_break,
                self._pomodoro_total_duration(),
                item_pomodoro_count=count,
                item_estimated=estimated,
            )

    def _pomodoro_total_duration(self) -> int:
        """Get the total duration in seconds for the current pomodoro phase."""
        from .widgets.pomodoro import TimerState

        state = self._pomodoro.state
        if state in (TimerState.WORKING, TimerState.PAUSED):
            return self._pomodoro.effective_work_duration * 60
        if state == TimerState.BREAK:
            sc = self._pomodoro.session_count
            if sc > 0 and sc % self._pomodoro.sessions_before_long_break == 0:
                return self._pomodoro.effective_long_break_duration * 60
            return self._pomodoro.effective_break_duration * 60
        return 0

    def _show_focus_timer_dialog(self) -> None:
        """Show the floating focus timer window."""
        from .dialogs.focus_timer import FocusTimerDialog
        from .widgets.stopwatch import StopwatchState

        if not self._is_any_timer_active():
            self.status_bar_widget.show_message(self.tr("No focus session active"))
            return

        if self._focus_timer_dialog is None:
            self._focus_timer_dialog = FocusTimerDialog(self)
            self._focus_timer_dialog.pause_requested.connect(self._on_pause_focus)
            self._focus_timer_dialog.stop_requested.connect(self._on_stop_focus)
            self._focus_timer_dialog.skip_break_requested.connect(self._on_skip_break)

        # Set mode and populate based on active timer
        if self._stopwatch.state != StopwatchState.IDLE:
            self._focus_timer_dialog.set_mode("stopwatch")
            estimated_min = self._get_focused_item_estimated_minutes()
            self._focus_timer_dialog.update_stopwatch_display(
                self._stopwatch.state.value,
                self._stopwatch.elapsed_seconds,
                self._stopwatch.item_name,
                estimated_minutes=estimated_min,
            )
        else:
            self._focus_timer_dialog.set_mode("pomodoro")
            count, estimated = self._get_focused_item_stats()
            self._focus_timer_dialog.update_display(
                self._pomodoro.state.value,
                self._pomodoro.remaining_seconds,
                self._pomodoro.item_name,
                self._pomodoro.session_count,
                self._pomodoro.sessions_before_long_break,
                self._pomodoro_total_duration(),
                item_pomodoro_count=count,
                item_estimated=estimated,
            )
        self._focus_timer_dialog.show()
        self._focus_timer_dialog.raise_()
        self._focus_timer_dialog.activateWindow()
        # Must be called after show() — the visibility guard skips updates on hidden dialogs
        self._update_focus_timer_sessions()
        self._update_focus_item_progress()
        self._update_daily_goal()

    def _on_skip_break(self) -> None:
        """Skip the current break and start the next work session."""
        from .widgets.pomodoro import TimerState

        if self._pomodoro.state == TimerState.BREAK:
            self._pomodoro._start_work_session()

    def _populate_sync_group_menu(self) -> None:
        """Populate the sync group submenu with available groups."""
        if self.sync_group_menu is None:
            return

        self.sync_group_menu.clear()

        groups = self._storage.get_all_sync_groups()
        if not groups:
            no_groups = self.sync_group_menu.addAction(self.tr("No sync groups created"))
            if no_groups:
                no_groups.setEnabled(False)
            return

        discovery = get_discovery_service()
        online_fps = {p.fingerprint for p in discovery.get_peers() if not p.is_local}

        for group in groups:
            devices = self._storage.get_devices_in_group(group.id)
            online_count = sum(1 for d in devices if d.fingerprint in online_fps)

            action = self.sync_group_menu.addAction(
                f"{group.name} ({online_count}/{len(devices)} online)"
            )
            if action:
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
                self.tr("No Online Devices"),
                self.tr(f"No devices in '{group.name}' are currently online."),
            )
            return

        result = QMessageBox.question(
            self,
            self.tr("Sync Group"),
            self.tr(f"Sync with {len(online_devices)} online device(s) in '{group.name}'?")
            + "\n\n"
            + "\n".join(f"  - {d.name or self.tr('Unnamed')}" for d in online_devices),
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
                self.tr("No Trusted Devices"),
                self.tr("No trusted devices are currently online."),
            )
            return

        result = QMessageBox.question(
            self,
            self.tr("Sync All Trusted"),
            self.tr(f"Sync with {len(devices)} trusted online device(s)?")
            + "\n\n"
            + "\n".join(f"  - {d.name or self.tr('Unnamed')}" for d in devices),
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

        for device in devices:
            # Update status bar with progress
            self.status_bar_widget.set_sync_status("syncing")

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
                    _, _, _, changed = self._merge_sync_data_internal(
                        pull_result.data, device.name or peer.hostname
                    )
                    self._record_unseen_changes(changed)

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
                self.tr("Sync Complete"),
                self.tr(f"Successfully synced with {success_count} device(s)."),
            )
        elif queued_count > 0:
            self.status_bar_widget.set_sync_status("success")
            msg = self.tr(f"Synced with {success_count} device(s).")
            if queued_count > 0:
                msg += self.tr(f"\n{queued_count} device(s) offline - syncs queued.")
            if fail_count > 0:
                msg += self.tr(f"\n{fail_count} failed.")
            QMessageBox.information(self, self.tr("Sync Complete"), msg)
        else:
            self.status_bar_widget.set_sync_status("error")
            QMessageBox.warning(
                self,
                self.tr("Sync Partial"),
                self.tr(f"Synced with {success_count} device(s).\n{fail_count} failed."),
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
            no_peers = self.pull_peers_menu.addAction(self.tr("No peers discovered"))
            if no_peers:
                no_peers.setEnabled(False)
        else:
            for peer in peers:
                action = self.pull_peers_menu.addAction(f"{peer.display_name} ({peer.address})")
                if action:
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
            no_peers = self.push_peers_menu.addAction(self.tr("No peers discovered"))
            if no_peers:
                no_peers.setEnabled(False)
        else:
            for peer in peers:
                action = self.push_peers_menu.addAction(f"{peer.display_name} ({peer.address})")
                if action:
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
            self.status_bar_widget.set_sync_status("syncing")
            try:
                logger.log.debug("Menu pull: connecting to %s:%d", host, port)
                pull_op = create_pull_operation(host, port)
                result = await self._sync_queue.execute(pull_op)
                if result.success:
                    # Track the device we synced with
                    peer_fingerprint = self._sync_client.get_last_peer_fingerprint()
                    if peer_fingerprint:
                        self._track_device(peer_fingerprint, f"{host}:{port}")

                    peer_name = ""
                    if peer_fingerprint:
                        dev = self._storage.get_device_by_fingerprint(peer_fingerprint)
                        if dev:
                            peer_name = dev.name
                    merged, local_newer, _, changed = self._merge_sync_data_internal(
                        result.data, peer_name or host
                    )
                    self._record_unseen_changes(changed)
                    self._save_database()
                    self._refresh_ui()
                    self.status_bar_widget.set_sync_status("success")
                    if merged > 0:
                        QMessageBox.information(
                            self,
                            self.tr("Pull Complete"),
                            self.tr(f"Pulled and merged {merged} items from {host}:{port}"),
                        )
                    elif local_newer > 0:
                        QMessageBox.information(
                            self,
                            self.tr("Local Is Newer"),
                            self.tr(
                                f"No items merged - {local_newer} local items are newer.\n"
                                "Push to update remote with your changes."
                            ),
                        )
                    else:
                        QMessageBox.information(
                            self,
                            self.tr("Already In Sync"),
                            self.tr(f"Databases are identical with {host}:{port}"),
                        )
                else:
                    self.status_bar_widget.set_sync_status("error")
                    QMessageBox.warning(
                        self, self.tr("Pull Failed"), self.tr(f"Could not pull from {host}:{port}")
                    )
            except Exception as e:
                self.status_bar_widget.set_sync_status("error")
                logger.log.exception("Menu pull failed: %s", e)
                QMessageBox.critical(self, self.tr("Pull Error"), self.tr(f"Pull failed: {e}"))

        asyncio.ensure_future(do_pull())

    def _do_sync_push(self, host: str, port: int) -> None:
        """Perform sync push to specified host (excludes private lists)."""

        async def do_push():
            self.status_bar_widget.set_sync_status("syncing")
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
                        self.tr("Push Complete"),
                        self.tr(
                            f"Pushed {len(data)} bytes to {host}:{port}\nRemote will merge any new items."
                        ),
                    )
                else:
                    self.status_bar_widget.set_sync_status("error")
                    QMessageBox.warning(
                        self, self.tr("Push Failed"), self.tr(f"Could not push to {host}:{port}")
                    )
            except Exception as e:
                self.status_bar_widget.set_sync_status("error")
                logger.log.exception("Menu push failed: %s", e)
                QMessageBox.critical(self, self.tr("Push Error"), self.tr(f"Push failed: {e}"))

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
                peer_name = ""
                if fingerprint:
                    dev = self._storage.get_device_by_fingerprint(fingerprint)
                    if dev:
                        peer_name = dev.name
                self._merge_sync_data(result, peer_name)

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

    def _merge_sync_data(self, data: bytes, peer_name: str = "") -> None:
        """Merge received sync data into local database."""
        try:
            merged, local_newer, identical, changed = self._merge_sync_data_internal(
                data, peer_name
            )
            self._record_unseen_changes(changed)
            self._reconcile_board_columns()
            from ..core.models import advance_all_overdue_recurring

            advance_all_overdue_recurring(self._database)
            self._save_database()
            self._refresh_ui()
            self.status_bar_widget.set_sync_status("success")
            logger.log.info(
                "Merged %d, local newer %d, identical %d", merged, local_newer, identical
            )
            if merged > 0:
                QMessageBox.information(
                    self, self.tr("Sync Complete"), self.tr(f"Merged {merged} items from remote.")
                )
            elif local_newer > 0:
                QMessageBox.information(
                    self,
                    self.tr("Local Is Newer"),
                    self.tr(
                        f"No items merged - {local_newer} local items are newer.\n"
                        "Push to update remote with your changes."
                    ),
                )
            else:
                QMessageBox.information(
                    self, self.tr("Already In Sync"), self.tr("Databases are identical.")
                )
        except Exception as e:
            self.status_bar_widget.set_sync_status("error")
            logger.log.exception("Error merging sync data: %s", e)
            QMessageBox.warning(
                self, self.tr("Merge Error"), self.tr(f"Failed to merge sync data: {e}")
            )

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

    def _on_peer_sync_received(self, _data: bytes) -> None:
        """Handle sync data received from peer manager."""
        self._save_database()
        self._refresh_ui()
        self.status_bar_widget.set_sync_status("success")

    def _on_device_sync_received(self, _data: bytes) -> None:
        """Handle sync data received from device manager."""
        self._save_database()
        self._refresh_ui()
        self.status_bar_widget.set_sync_status("success")

    def _on_settings(self) -> None:
        """Handle settings action."""
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            # Re-fetch config — reload() in SettingsDialog creates a new object
            self._config = get_config()
            self._auto_scheduler.update_config(
                delay_seconds=self._config.discovery.auto_sync_delay,
                interval_minutes=self._config.discovery.auto_sync_interval,
            )
            self._pomodoro.update_config(self._config.pomodoro)
            self._stopwatch.update_config(self._config.stopwatch)
            self._analytics.set_work_duration(self._config.pomodoro.work_duration)
            self._sound_player.update_config(self._config.pomodoro)
            self._update_daily_goal()
            # Restart web server if config changed
            if self._config.web.enabled and self._web_server is None:
                self._start_web_server()
            elif not self._config.web.enabled and self._web_server is not None:
                self._stop_web_server()
            self._refresh_ui()

    def _on_system_theme_changed(self) -> None:
        """Handle system dark/light mode change (macOS auto-switch)."""
        if self._config.appearance.theme == "system":
            apply_current_theme()
            self._refresh_ui()

    def _on_focus_stats(self) -> None:
        """Show the Focus Statistics dialog."""
        from .dialogs.focus_stats import FocusStatsDialog

        dialog = FocusStatsDialog(self._analytics, self._database, self._config.pomodoro, self)
        dialog.exec()

    def _on_web_connect(self) -> None:
        """Show the mobile access wizard for connecting phones and tablets."""
        from .dialogs.web_connect import MobileAccessWizard

        dialog = MobileAccessWizard(parent=self)
        dialog.exec()

    def _on_import_ics(self) -> None:
        """Import items from an .ics file into the active list."""
        from ..core.caldav import import_ics_to_items

        active_list = self._database.active_list
        if active_list is None:
            QMessageBox.warning(self, self.tr("Import"), self.tr("No list selected."))
            return

        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Import from .ics"), "", self.tr("iCalendar Files (*.ics);;All Files (*)")
        )
        if not path:
            return

        try:
            data = Path(path).read_bytes()
            items = import_ics_to_items(data)
        except Exception as e:
            QMessageBox.critical(
                self, self.tr("Import Error"), self.tr(f"Could not parse file:\n{e}")
            )
            return

        if not items:
            QMessageBox.information(
                self,
                self.tr("Import"),
                self.tr("No tasks found in file (may contain only events)."),
            )
            return

        # Import through undo stack for consistency with unified undo system
        from .commands import AddItemCommand

        completed = 0
        self._undo_stack.beginMacro(f"Import {len(items)} items from .ics")
        for item in items:
            # Assign default board column
            if not item.board_column and active_list.board_columns:
                item.board_column = active_list.board_columns[0]
            cmd = AddItemCommand(self, active_list.id, item)
            self._undo_stack.push(cmd)
            if item.complete:
                completed += 1
        self._undo_stack.endMacro()

        self.status_bar_widget.show_message(
            self.tr(f"Imported {len(items)} items ({completed} completed) from {Path(path).name}")
        )

    def _on_export_ics(self) -> None:
        """Export the active list as an .ics file."""
        from ..core.caldav import export_list_to_ics

        active_list = self._database.active_list
        if active_list is None:
            QMessageBox.warning(self, self.tr("Export"), self.tr("No list selected."))
            return

        default_name = f"{active_list.name}.ics"
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export List as .ics"),
            default_name,
            self.tr("iCalendar Files (*.ics);;All Files (*)"),
        )
        if not path:
            return

        try:
            ics_data = export_list_to_ics(active_list)
            Path(path).write_bytes(ics_data)
        except Exception as e:
            QMessageBox.critical(
                self, self.tr("Export Error"), self.tr(f"Could not write file:\n{e}")
            )
            return

        count = active_list.active_item_count()
        self.status_bar_widget.show_message(self.tr(f"Exported {count} items to {Path(path).name}"))

    def _on_export_charts(self) -> None:
        """Open the Export Charts dialog with date range, selection, and live preview."""
        active_list = self._database.active_list
        if active_list is None:
            QMessageBox.warning(self, self.tr("Export Charts"), self.tr("No list selected."))
            return

        try:
            from .dialogs.export_charts import ExportChartsDialog
        except ImportError as e:
            QMessageBox.critical(
                self,
                self.tr("Export Error"),
                self.tr(f"Chart export module unavailable:\n{e}"),
            )
            return

        dialog = ExportChartsDialog(self, active_list, self._analytics)
        dialog.exec()

    def _on_print(self) -> None:
        """Handle print action."""
        active_list = self._database.active_list
        if active_list is None or active_list.active_item_count() == 0:
            QMessageBox.information(self, self.tr("Print"), self.tr("No items to print."))
            return

        dialog = QPrintDialog(self._printer, self)
        if dialog.exec() == QPrintDialog.DialogCode.Accepted:
            # Build document
            lines = [f"{'=' * 20} {active_list.name} {'=' * 20}", ""]
            for item in active_list.active_items():
                status = "✓" if item.complete else "○"
                priority = [self.tr("High"), self.tr("Normal"), self.tr("Low")][item.priority - 1]
                lines.append(f"{status} [{priority}] {item.reminder}")

            doc = QTextDocument("\n".join(lines))
            doc.print(self._printer)
            QMessageBox.information(self, self.tr("Print"), self.tr("Print job sent."))

    def _on_about(self) -> None:
        """Handle about action."""
        QMessageBox.about(
            self,
            self.tr("About PyTodo-Qt"),
            self.tr(
                f"<b>PyTodo-Qt v{settings.__version__}</b><br><br>"
                "A modern cross-platform todo application with "
                "encrypted peer-to-peer synchronization.<br><br>"
                "License: <a href='http://www.fsf.org/licenses/gpl.html'>GPLv3</a><br><br>"
                "<b>Copyright (C) 2024-2026 Michael Berry</b>"
            ),
        )

    def _on_about_qt(self) -> None:
        """Handle about Qt action."""
        QMessageBox.aboutQt(self, self.tr("About Qt"))

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

    def _quit_application(self) -> None:
        """Fully quit the application (bypasses close-to-tray)."""
        self._force_quit = True
        # Ensure window is visible before close — on macOS, close() on a
        # hidden window may not trigger closeEvent at all.
        if not self.isVisible():
            self.show()
        self.close()

    def closeEvent(self, a0) -> None:  # noqa: N802
        """Handle window close."""
        # Minimize to tray instead of quitting (if enabled and tray available)
        if (
            not self._force_quit
            and self._config.appearance.close_to_tray
            and self.tray_icon is not None
            and self.tray_icon.isVisible()
        ):
            if a0:
                a0.ignore()
            self.hide()
            return

        # Stop auto-sync scheduler
        self._auto_scheduler.stop()

        # Stop sync queue
        asyncio.ensure_future(self._sync_queue.stop())

        # Stop server
        self._stop_server()

        # Stop web server
        self._stop_web_server()

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
        if a0:
            a0.accept()
