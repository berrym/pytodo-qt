"""themes.py

Theme management for pytodo-qt.
"""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication

from ...core.config import get_config
from ...core.logger import Logger

if TYPE_CHECKING:
    pass

_FONTS_DIR = Path(__file__).parent.parent / "fonts"

_BUNDLED_TEXT_FONTS = (
    "NotoSans-Regular.ttf",
    "NotoSans-Bold.ttf",
    "NotoSansMono-Regular.ttf",
)
_BUNDLED_EMOJI_FONT = "NotoColorEmoji.ttf"

# Set to True after successful font registration
_bundled_fonts_loaded = False


logger = Logger(__name__)


class Theme(Enum):
    """Available themes."""

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


# Modern color schemes — semantic colors tuned per-theme for WCAG AA contrast
# Light: darker, slightly desaturated accents on white (CR >= 4.5:1)
# Dark: lighter, more desaturated accents on dark surface (CR >= 4.5:1)
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
    "completed_text": "#787878",
    "priority_high": "#b12f25",
    "priority_normal": "#1b5f98",
    "priority_low": "#95a5a6",
    "due_overdue": "#b12f25",
    "due_today": "#ae6e13",
    "due_soon": "#2a7e4d",
    # Chart/timeline colors (Okabe-Ito + industry standards for light backgrounds)
    "chart_span": "#5470c6",  # ECharts blue — time span bar
    "chart_span_alpha": "100",  # Opacity 0-255
    "chart_estimate": "#D4E9F3",  # Light gray-blue — estimate baseline (recedes)
    "chart_estimate_border": "#B0C4D8",
    "chart_pomodoro": "#D55E00",  # Okabe-Ito vermillion — pomodoro actual
    "chart_pomodoro_alpha": "200",
    "chart_stopwatch": "#0072B2",  # Okabe-Ito blue — stopwatch actual
    "chart_stopwatch_alpha": "200",
    "chart_overdue": "#b12f25",  # Matches due_overdue
    "chart_overdue_alpha": "80",
    "chart_overflow_stripe": "#C0CCD8",
    "chart_overflow_actual": "#8B0000",
    "chart_overflow_actual_alpha": "100",
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
    "completed_text": "#8c8c8c",
    "priority_high": "#e77c74",
    "priority_normal": "#85b1d6",
    "priority_low": "#7f8c8d",
    "due_overdue": "#e77c74",
    "due_today": "#ddad5f",
    "due_soon": "#6bc791",
    # Chart/timeline colors (ECharts dark + desaturated for dark backgrounds)
    "chart_span": "#4992ff",  # ECharts dark blue — time span bar
    "chart_span_alpha": "90",  # Subtle, recedes
    "chart_estimate": "#3D4147",  # Dark gray — estimate baseline (recedes on dark bg)
    "chart_estimate_border": "#555B63",
    "chart_pomodoro": "#ff6e76",  # ECharts dark red — pomodoro actual (desaturated)
    "chart_pomodoro_alpha": "200",
    "chart_stopwatch": "#58d9f9",  # ECharts dark cyan — stopwatch actual (distinct from span)
    "chart_stopwatch_alpha": "200",
    "chart_overdue": "#ff6e76",  # Matches pomodoro red family
    "chart_overdue_alpha": "60",
    "chart_overflow_stripe": "#555B63",
    "chart_overflow_actual": "#ff6e76",
    "chart_overflow_actual_alpha": "80",
}


# Monospace font stack — platform-aware fallbacks for fingerprints etc.
if sys.platform == "darwin":
    MONO_FONT_FAMILIES = ["SF Mono", "Menlo", "Monaco"]
elif sys.platform == "win32":
    MONO_FONT_FAMILIES = ["Cascadia Mono", "Consolas", "Courier New"]
else:
    MONO_FONT_FAMILIES = ["Noto Sans Mono", "DejaVu Sans Mono", "Liberation Mono", "monospace"]

DEFAULT_FONT_SIZE = 10


def load_bundled_fonts() -> bool:
    """Register bundled Noto fonts with Qt. Returns True if successful."""
    global _bundled_fonts_loaded  # noqa: PLW0603

    if not _FONTS_DIR.is_dir():
        logger.log.warning("Bundled fonts directory not found: %s", _FONTS_DIR)
        return False

    text_ok = True

    # Register text fonts
    for name in _BUNDLED_TEXT_FONTS:
        path = _FONTS_DIR / name
        if not path.exists():
            logger.log.warning("Bundled font not found: %s", path)
            text_ok = False
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            logger.log.warning("Failed to register font: %s", name)
            text_ok = False
        else:
            families = QFontDatabase.applicationFontFamilies(font_id)
            logger.log.info("Registered font: %s -> %s", name, families)

    # Register emoji font (best-effort — may fail in offscreen/headless)
    emoji_path = _FONTS_DIR / _BUNDLED_EMOJI_FONT
    if emoji_path.exists():
        font_id = QFontDatabase.addApplicationFont(str(emoji_path))
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            logger.log.info("Registered emoji font: %s -> %s", _BUNDLED_EMOJI_FONT, families)
            if families and hasattr(QFontDatabase, "addApplicationEmojiFontFamily"):
                QFontDatabase.addApplicationEmojiFontFamily(families[0])
                logger.log.info("Set application emoji font family: %s", families[0])
        else:
            logger.log.warning("Failed to register emoji font: %s", _BUNDLED_EMOJI_FONT)
    else:
        logger.log.warning("Bundled emoji font not found: %s", emoji_path)

    _bundled_fonts_loaded = text_ok
    return text_ok


def apply_bundled_font(app: QApplication) -> None:
    """Set bundled Noto Sans as the application-wide font."""
    font = QFont("Noto Sans", DEFAULT_FONT_SIZE)
    font.setFamilies(["Noto Sans", "Noto Color Emoji"])
    app.setFont(font)
    logger.log.info("Applied bundled font: Noto Sans %dpt", DEFAULT_FONT_SIZE)


def _get_mono_families() -> list[str]:
    """Get monospace font families, prepending bundled font when loaded."""
    if _bundled_fonts_loaded:
        return ["Noto Sans Mono", *MONO_FONT_FAMILIES]
    return MONO_FONT_FAMILIES


def make_font(size: int = DEFAULT_FONT_SIZE, *, mono: bool = False) -> QFont:
    """Create a QFont using the configured font or a monospace fallback stack."""
    if mono:
        families = _get_mono_families()
        font = QFont(families[0], size)
        font.setFamilies(families)
    else:
        config = get_config()
        font_setting = config.appearance.font
        if font_setting == "bundled" and _bundled_fonts_loaded:
            font = QFont("Noto Sans", size)
            font.setFamilies(["Noto Sans", "Noto Color Emoji"])
        elif font_setting not in ("system", "bundled"):
            # Custom font family
            font = QFont(font_setting, size)
        else:
            font = QFont()
            font.setPointSize(size)
    return font


def get_system_theme() -> Theme:
    """Detect system theme preference from the OS."""
    if sys.platform == "darwin":
        # macOS: check system appearance directly
        try:
            from Foundation import NSUserDefaults

            defaults = NSUserDefaults.standardUserDefaults()
            style = defaults.stringForKey_("AppleInterfaceStyle")
            return Theme.DARK if style == "Dark" else Theme.LIGHT
        except ImportError:
            pass

    # Fallback: use Qt's style hints (works on most platforms)
    _app = QApplication.instance()
    if _app is None or not isinstance(_app, QApplication):
        return Theme.LIGHT
    app = _app

    # Qt 6.5+ has colorScheme() on QStyleHints
    style_hints = app.styleHints()
    if style_hints is not None and hasattr(style_hints, "colorScheme"):
        from PyQt6.QtCore import Qt

        scheme = style_hints.colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return Theme.DARK
        elif scheme == Qt.ColorScheme.Light:
            return Theme.LIGHT

    # Final fallback: check default palette (before any theming applied)
    # This may not work correctly if app theme was already changed
    palette = app.palette()
    window_color = palette.color(QPalette.ColorRole.Window)
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
    padding: 4px;
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

    logger.log.debug("Applied theme: %s", theme.value)


def apply_current_theme() -> None:
    """Apply the current theme from config."""
    app = QApplication.instance()
    if app is not None and isinstance(app, QApplication):
        apply_theme(app)
