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
    "highlight": "#1976d2",
    "highlight_text": "#ffffff",
    "link": "#1565c0",
    "border": "#d0d0d0",
    "completed_bg": "#f0f8f0",
    "completed_text": "#6c6c6c",
    "priority_high": "#b12f25",
    "priority_normal": "#1b5f98",
    "priority_low": "#757575",
    "due_overdue": "#b12f25",
    "due_today": "#92611f",
    "due_soon": "#2a7e4d",
    # Smart-input entity highlight palette — applied as foreground
    # color on parsed entity spans. Tuned for >= 4.5:1 contrast on the
    # light base background; values picked from Tailwind 700 /
    # Material 700-800 families so each entity kind reads at AA against
    # white while remaining tonally related to its dark-theme sibling.
    "entity_date": "#1976d2",
    "entity_time": "#1976d2",
    "entity_priority": "#b45309",
    "entity_tag": "#00796b",
    "entity_recurrence": "#15803d",
    "entity_pomodoro": "#6d28d9",
    "entity_estimate": "#92400e",
    "entity_work_duration": "#9333EA",
    "entity_time_block": "#1976d2",
    "entity_event_date": "#7C3AED",
    "entity_condition": "#DC2626",
    "entity_filler": "#64748b",
    "entity_subtask": "#0369a1",
    # Focus-timer state colors — drive the countdown text color in
    # `dialogs/focus_timer.py`. Distinct enough to read state at a
    # glance even out of the corner of the eye.
    "focus_timer_working": "#c0392b",
    "focus_timer_break": "#15803d",
    "focus_timer_paused": "#b45309",
    "focus_timer_stopwatch_running": "#1976d2",
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
    "highlight": "#64b5f6",
    "highlight_text": "#1a1a1a",
    "link": "#90caf9",
    "border": "#3c3c3c",
    "completed_bg": "#1a2f1a",
    "completed_text": "#9a9a9a",
    "priority_high": "#e77c74",
    "priority_normal": "#85b1d6",
    "priority_low": "#9ca3af",
    "due_overdue": "#e77c74",
    "due_today": "#ddad5f",
    "due_soon": "#6bc791",
    # Smart-input entity highlight palette — desaturated and lightened
    # so each entity reads against the dark base while staying tonally
    # related to its light-theme companion.
    "entity_date": "#6AB0F3",
    "entity_time": "#6AB0F3",
    "entity_priority": "#F0A850",
    "entity_tag": "#4DC4C4",
    "entity_recurrence": "#7DC87D",
    "entity_pomodoro": "#A78BFA",
    "entity_estimate": "#FBBF24",
    "entity_work_duration": "#C084FC",
    "entity_time_block": "#6AB0F3",
    "entity_event_date": "#A78BFA",
    "entity_condition": "#F87171",
    "entity_filler": "#94A3B8",
    "entity_subtask": "#38BDF8",
    # Focus-timer state colors, dark-theme variants. Previously the
    # focus-timer dialog used the light-theme hex values regardless of
    # active theme, producing washed-out chart colors on dark
    # backgrounds; this fixes that by giving each state a desaturated
    # dark-theme companion.
    "focus_timer_working": "#F87171",
    "focus_timer_break": "#34D399",
    "focus_timer_paused": "#FBBF24",
    "focus_timer_stopwatch_running": "#60A5FA",
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
# Menlo is listed first on macOS because SF Mono is not universally
# installed (it ships with Terminal.app / Xcode; fresh users without
# either see a ~115 ms Qt font-alias resolution cost plus a console
# warning on every app start). Menlo is always present on macOS and
# renders nearly identically to SF Mono for fixed-width display.
if sys.platform == "darwin":
    MONO_FONT_FAMILIES = ["Menlo", "Monaco"]
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

    # Register emoji font (best-effort)
    # macOS: use system Apple Color Emoji (Qt can't register CBDT fonts on macOS)
    # Windows: use system Segoe UI Emoji
    # Linux: register bundled Noto Color Emoji
    if sys.platform in ("darwin", "win32"):
        system_emoji = _emoji_family()
        if hasattr(QFontDatabase, "addApplicationEmojiFontFamily"):
            QFontDatabase.addApplicationEmojiFontFamily(system_emoji)
        logger.log.info("Using system emoji font: %s", system_emoji)
    else:
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


def _emoji_family() -> str:
    """Get the emoji font family for the current platform."""
    if sys.platform == "darwin":
        return "Apple Color Emoji"
    if sys.platform == "win32":
        return "Segoe UI Emoji"
    return "Noto Color Emoji"


def apply_bundled_font(app: QApplication) -> None:
    """Set bundled Noto Sans as the application-wide font."""
    font = QFont("Noto Sans", DEFAULT_FONT_SIZE)
    font.setFamilies(["Noto Sans", _emoji_family()])
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
            font.setFamilies(["Noto Sans", _emoji_family()])
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
    border-radius: 8px;
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
    border-radius: 8px;
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

QPushButton:focus {{
    border: 2px solid {colors["highlight"]};
}}

QPushButton:default {{
    border: 2px solid {colors["highlight"]};
}}

/* Input fields */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {colors["base"]};
    color: {colors["text"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    padding: 8px;
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {colors["highlight"]};
}}

/* Combo boxes */
QComboBox {{
    background-color: {colors["base"]};
    color: {colors["text"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    padding: 8px;
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
    border-radius: 8px;
    background-color: {colors["base"]};
}}

QTabBar::tab {{
    background-color: {colors["button"]};
    color: {colors["button_text"]};
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
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
    border-radius: 8px;
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
    border-radius: 4px;
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
    border-radius: 8px;
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
    border-radius: 8px;
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
    border-radius: 8px;
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
    border-radius: 8px;
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
    border-radius: 8px;
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
