"""themes.py

Theme management for pytodo-qt.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from ...core.config import get_config
from ...core.logger import Logger

if TYPE_CHECKING:
    pass


logger = Logger(__name__)


class Theme(Enum):
    """Available themes."""

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


# Modern color schemes
LIGHT_COLORS = {
    "window": "#f5f5f5",
    "window_text": "#1a1a1a",
    "base": "#ffffff",
    "alternate_base": "#f0f0f0",
    "text": "#1a1a1a",
    "button": "#e0e0e0",
    "button_text": "#1a1a1a",
    "highlight": "#0078d4",
    "highlight_text": "#ffffff",
    "link": "#0066cc",
    "border": "#d0d0d0",
    "completed_bg": "#f0f8f0",
    "completed_text": "#666666",
    "priority_high": "#e74c3c",
    "priority_normal": "#3498db",
    "priority_low": "#95a5a6",
}

DARK_COLORS = {
    "window": "#1e1e1e",
    "window_text": "#e0e0e0",
    "base": "#252526",
    "alternate_base": "#2d2d30",
    "text": "#e0e0e0",
    "button": "#3c3c3c",
    "button_text": "#e0e0e0",
    "highlight": "#0078d4",
    "highlight_text": "#ffffff",
    "link": "#58a6ff",
    "border": "#3c3c3c",
    "completed_bg": "#1a2f1a",
    "completed_text": "#808080",
    "priority_high": "#ff6b6b",
    "priority_normal": "#5dade2",
    "priority_low": "#7f8c8d",
}


def get_system_theme() -> Theme:
    """Detect system theme preference."""
    app = QApplication.instance()
    if app is None:
        return Theme.LIGHT

    palette = app.palette()
    window_color = palette.color(QPalette.ColorRole.Window)
    # If window is dark (low luminance), system is in dark mode
    luminance = (
        0.299 * window_color.red() + 0.587 * window_color.green() + 0.114 * window_color.blue()
    )
    return Theme.DARK if luminance < 128 else Theme.LIGHT


def get_current_theme() -> Theme:
    """Get the current theme based on config."""
    config = get_config()
    theme_str = config.appearance.theme.lower()

    if theme_str == "dark":
        return Theme.DARK
    elif theme_str == "light":
        return Theme.LIGHT
    else:
        return get_system_theme()


def get_colors() -> dict[str, str]:
    """Get color scheme for current theme."""
    theme = get_current_theme()
    if theme == Theme.DARK:
        return DARK_COLORS
    return LIGHT_COLORS


def create_palette(theme: Theme) -> QPalette:
    """Create a QPalette for the given theme."""
    colors = DARK_COLORS if theme == Theme.DARK else LIGHT_COLORS

    palette = QPalette()

    # Window colors
    palette.setColor(QPalette.ColorRole.Window, QColor(colors["window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["window_text"]))

    # Base colors (for input widgets)
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["base"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["alternate_base"]))

    # Text colors
    palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors["text"]).darker(150))

    # Button colors
    palette.setColor(QPalette.ColorRole.Button, QColor(colors["button"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["button_text"]))

    # Highlight colors
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["highlight"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["highlight_text"]))

    # Link colors
    palette.setColor(QPalette.ColorRole.Link, QColor(colors["link"]))

    return palette


def get_stylesheet(theme: Theme | None = None) -> str:
    """Generate stylesheet for the theme."""
    if theme is None:
        theme = get_current_theme()

    colors = DARK_COLORS if theme == Theme.DARK else LIGHT_COLORS

    return f"""
/* Global styles */
QMainWindow, QDialog {{
    background-color: {colors["window"]};
    color: {colors["window_text"]};
}}

/* Table styles */
QTableWidget {{
    background-color: {colors["base"]};
    alternate-background-color: {colors["alternate_base"]};
    border: 1px solid {colors["border"]};
    border-radius: 4px;
    gridline-color: {colors["border"]};
}}

QTableWidget::item {{
    padding: 8px;
    border-bottom: 1px solid {colors["border"]};
}}

QTableWidget::item:selected {{
    background-color: {colors["highlight"]};
    color: {colors["highlight_text"]};
}}

QHeaderView::section {{
    background-color: {colors["button"]};
    color: {colors["button_text"]};
    padding: 8px;
    border: none;
    border-bottom: 1px solid {colors["border"]};
    font-weight: bold;
}}

/* Button styles */
QPushButton {{
    background-color: {colors["button"]};
    color: {colors["button_text"]};
    border: 1px solid {colors["border"]};
    border-radius: 4px;
    padding: 8px 16px;
    min-width: 80px;
}}

QPushButton:hover {{
    background-color: {colors["highlight"]};
    color: {colors["highlight_text"]};
}}

QPushButton:pressed {{
    background-color: {colors["highlight"]};
}}

QPushButton:default {{
    border: 2px solid {colors["highlight"]};
}}

/* Input fields */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {colors["base"]};
    color: {colors["text"]};
    border: 1px solid {colors["border"]};
    border-radius: 4px;
    padding: 6px;
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {colors["highlight"]};
}}

/* Combo boxes */
QComboBox {{
    background-color: {colors["base"]};
    color: {colors["text"]};
    border: 1px solid {colors["border"]};
    border-radius: 4px;
    padding: 6px;
    min-width: 100px;
}}

QComboBox:hover {{
    border-color: {colors["highlight"]};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {colors["base"]};
    color: {colors["text"]};
    selection-background-color: {colors["highlight"]};
    selection-color: {colors["highlight_text"]};
}}

/* Tab widgets */
QTabWidget::pane {{
    border: 1px solid {colors["border"]};
    border-radius: 4px;
    background-color: {colors["base"]};
}}

QTabBar::tab {{
    background-color: {colors["button"]};
    color: {colors["button_text"]};
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}

QTabBar::tab:selected {{
    background-color: {colors["highlight"]};
    color: {colors["highlight_text"]};
}}

QTabBar::tab:hover:!selected {{
    background-color: {colors["alternate_base"]};
}}

/* Group boxes */
QGroupBox {{
    border: 1px solid {colors["border"]};
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}

/* Scroll bars */
QScrollBar:vertical {{
    background-color: {colors["base"]};
    width: 12px;
    border-radius: 6px;
}}

QScrollBar::handle:vertical {{
    background-color: {colors["border"]};
    border-radius: 6px;
    min-height: 20px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {colors["highlight"]};
}}

QScrollBar:horizontal {{
    background-color: {colors["base"]};
    height: 12px;
    border-radius: 6px;
}}

QScrollBar::handle:horizontal {{
    background-color: {colors["border"]};
    border-radius: 6px;
    min-width: 20px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}

/* Progress bar */
QProgressBar {{
    background-color: {colors["base"]};
    border: 1px solid {colors["border"]};
    border-radius: 4px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {colors["highlight"]};
    border-radius: 3px;
}}

/* Status bar */
QStatusBar {{
    background-color: {colors["window"]};
    border-top: 1px solid {colors["border"]};
}}

/* Menu */
QMenuBar {{
    background-color: {colors["window"]};
    color: {colors["window_text"]};
}}

QMenuBar::item:selected {{
    background-color: {colors["highlight"]};
    color: {colors["highlight_text"]};
}}

QMenu {{
    background-color: {colors["base"]};
    color: {colors["text"]};
    border: 1px solid {colors["border"]};
    border-radius: 4px;
}}

QMenu::item {{
    padding: 8px 24px;
}}

QMenu::item:selected {{
    background-color: {colors["highlight"]};
    color: {colors["highlight_text"]};
}}

QMenu::separator {{
    height: 1px;
    background-color: {colors["border"]};
    margin: 4px 8px;
}}

/* Toolbar */
QToolBar {{
    background-color: {colors["window"]};
    border-bottom: 1px solid {colors["border"]};
    spacing: 4px;
    padding: 4px;
}}

QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 6px;
}}

QToolButton:hover {{
    background-color: {colors["button"]};
    border-color: {colors["border"]};
}}

QToolButton:pressed {{
    background-color: {colors["highlight"]};
}}

/* Tooltips */
QToolTip {{
    background-color: {colors["base"]};
    color: {colors["text"]};
    border: 1px solid {colors["border"]};
    border-radius: 4px;
    padding: 4px;
}}

/* Check boxes and radio buttons */
QCheckBox, QRadioButton {{
    color: {colors["text"]};
    spacing: 8px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 2px solid {colors["border"]};
    border-radius: 4px;
    background-color: {colors["base"]};
}}

QRadioButton::indicator {{
    border-radius: 9px;
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {colors["highlight"]};
    border-color: {colors["highlight"]};
}}

/* Spin boxes */
QSpinBox, QDoubleSpinBox {{
    background-color: {colors["base"]};
    color: {colors["text"]};
    border: 1px solid {colors["border"]};
    border-radius: 4px;
    padding: 4px;
}}

/* Labels */
QLabel {{
    color: {colors["text"]};
}}

/* List views */
QListView {{
    background-color: {colors["base"]};
    color: {colors["text"]};
    border: 1px solid {colors["border"]};
    border-radius: 4px;
}}

QListView::item {{
    padding: 6px;
}}

QListView::item:selected {{
    background-color: {colors["highlight"]};
    color: {colors["highlight_text"]};
}}
"""


def apply_theme(app: QApplication, theme: Theme | None = None) -> None:
    """Apply theme to the application."""
    if theme is None:
        theme = get_current_theme()

    palette = create_palette(theme)
    app.setPalette(palette)
    app.setStyleSheet(get_stylesheet(theme))

    logger.log.info("Applied theme: %s", theme.value)


def apply_current_theme() -> None:
    """Apply the current theme from config."""
    app = QApplication.instance()
    if app is not None:
        apply_theme(app)
