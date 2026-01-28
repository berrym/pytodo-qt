"""GUI module for pytodo-qt.

Provides:
- MainWindow - the main application window
- Modular widgets (TodoTable, StatusBar, ListSelector)
- Dialogs (Settings, PeerManager, AddTodo, Sync)
- Theme support (light/dark/system)
"""

from .dialogs import AddTodoDialog, PeerManagerDialog, SettingsDialog, SyncDialog
from .main_window import MainWindow
from .styles import Theme, apply_current_theme, apply_theme, get_current_theme
from .widgets import ListSelectorWidget, StatusBarWidget, TodoTableWidget

__all__ = [
    "MainWindow",
    "TodoTableWidget",
    "StatusBarWidget",
    "ListSelectorWidget",
    "SettingsDialog",
    "PeerManagerDialog",
    "AddTodoDialog",
    "SyncDialog",
    "Theme",
    "apply_current_theme",
    "apply_theme",
    "get_current_theme",
]
