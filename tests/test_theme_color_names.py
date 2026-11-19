"""Style sheets name their colors in a way the theme decides and Qt takes.

Three ways of naming a color gave text and lines the theme had no say
over:

- A CSS color name is one color for both themes. `gray` gave 3.62:1 on
  the light theme's window, `orange` 1.81:1, `green` 2.98:1 on the dark
  theme's base.
- A palette role in camel case, `palette(placeholderText)`, is dropped
  by Qt without a word: the text keeps the ordinary color.
- A role the theme does not set, `palette(mid)`, is derived by Qt, the
  same light gray in both themes: 1.82:1 as text on the light theme's
  window, and a bright line as a border in the dark theme.

WCAG AA asks 4.5:1 of text and 3:1 of a line that marks something.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget

from pytodo_qt.core.bar_palette import contrast_ratio
from pytodo_qt.core.models import build_rich_tooltip, create_todo_item
from pytodo_qt.gui.styles.themes import (
    DARK_COLORS,
    LIGHT_COLORS,
    Theme,
    apply_theme,
    border_color,
)

SOURCE_DIR = Path(__file__).resolve().parent.parent / "src" / "pytodo_qt"
_THEME_COLORS = {"light": LIGHT_COLORS, "dark": DARK_COLORS}

# The color names of CSS that a style could plausibly be given.
_NAMED = (
    "black|silver|gr[ae]y|white|maroon|red|purple|fuchsia|green|lime|olive|yellow|navy|blue"
    "|teal|aqua|orange|darkgr[ae]y|lightgr[ae]y|dimgr[ae]y|darkred|darkgreen"
    "|darkblue|darkorange|gold|pink|brown|cyan|magenta"
)

# The palette roles a style sheet may name: those the theme sets, in
# the spelling Qt takes.
_ROLES = {
    "base": ("Base", "base"),
    "alternate-base": ("AlternateBase", "alternate_base"),
    "window": ("Window", "window"),
    "window-text": ("WindowText", "window_text"),
    "text": ("Text", "text"),
    "button": ("Button", "button"),
    "button-text": ("ButtonText", "button_text"),
    "highlight": ("Highlight", "highlight"),
    "highlighted-text": ("HighlightedText", "highlight_text"),
    "link": ("Link", "link"),
    "placeholder-text": ("PlaceholderText", "completed_text"),
}


def _sources() -> list[tuple[Path, str]]:
    return [(path, path.read_text(encoding="utf-8")) for path in sorted(SOURCE_DIR.rglob("*.py"))]


@pytest.fixture(params=["light", "dark"])
def themed(request, qtbot, monkeypatch):
    """The application in one of the two themes; gives the theme's colors."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    theme = Theme(request.param)
    monkeypatch.setattr("pytodo_qt.gui.styles.themes.get_current_theme", lambda: theme)
    palette, sheet = app.palette(), app.styleSheet()
    apply_theme(app, theme)
    yield _THEME_COLORS[request.param]
    app.setPalette(palette)
    app.setStyleSheet(sheet)


class TestSourcesNameColorsTheThemeDecides:
    def test_no_text_has_a_css_color_name(self):
        """In a style sheet and in rich text alike."""
        pattern = re.compile(rf"(?<![-\w])color:\s*({_NAMED})\b", re.IGNORECASE)
        found = [
            f"{path.relative_to(SOURCE_DIR)}: {match.group(0)}"
            for path, text in _sources()
            for match in pattern.finditer(text)
        ]
        assert found == []

    def test_every_palette_role_is_one_the_theme_sets_spelled_as_qt_takes_it(self):
        pattern = re.compile(r"(?<![\w.])palette\(([^)]*)\)")
        found = [
            f"{path.relative_to(SOURCE_DIR)}: {match.group(0)}"
            for path, text in _sources()
            for match in pattern.finditer(text)
            if match.group(1) not in _ROLES
        ]
        assert found == []

    def test_the_roles_are_in_use(self):
        """The check above finds something to check."""
        text = "\n".join(text for _path, text in _sources())
        assert text.count("palette(placeholder-text)") >= 30
        assert text.count("palette(highlighted-text)") >= 9


class TestTheThemeSetsTheRoles:
    @pytest.mark.parametrize("role", sorted(_ROLES))
    def test_the_palette_has_the_themes_color_for_the_role(self, themed, role):
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        name, key = _ROLES[role]
        assert app.palette().color(getattr(QPalette.ColorRole, name)).name() == themed[key]

    def test_the_placeholder_role_is_the_muted_text(self, themed):
        """Derived from the text color, it was `#111111` in the light
        theme: darker than the text a field is filled in with."""
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        placeholder = app.palette().color(QPalette.ColorRole.PlaceholderText).name()
        assert placeholder == themed["completed_text"]
        assert placeholder != themed["text"]

    @pytest.mark.parametrize("around", ["base", "window"])
    def test_the_muted_text_can_be_read(self, themed, around):
        assert contrast_ratio(themed["completed_text"], themed[around]) >= 4.5

    def test_qt_takes_the_role_in_a_style_sheet(self, themed, qtbot):
        label = QLabel("a hint")
        qtbot.addWidget(label)
        label.setStyleSheet("color: palette(placeholder-text); font-style: italic;")
        label.ensurePolished()
        assert label.palette().color(label.foregroundRole()).name() == themed["completed_text"]

    def test_qt_drops_the_camel_case_spelling(self, themed, qtbot):
        """What made the hints as dark as ordinary text."""
        label = QLabel("a hint")
        qtbot.addWidget(label)
        label.setStyleSheet("color: palette(placeholderText);")
        label.ensurePolished()
        assert label.palette().color(label.foregroundRole()).name() != themed["completed_text"]


class TestTheHintInAnEmptyField:
    """A field whose text color comes from a style sheet shows its
    placeholder in that color at half opacity, whatever the palette's
    role says: 3.36:1 in the light theme, 4.04:1 in the dark. The
    application's style sheet names the color itself."""

    @staticmethod
    def _strongest(widget, background: str) -> str:
        """The painted color that stands out most from the background,
        the field's border left out."""
        for _ in range(4):
            QApplication.processEvents()
        image = widget.grab().toImage()
        colors = {
            QColor(image.pixel(x, y)).name()
            for y in range(8, image.height() - 8)
            for x in range(12, image.width() - 12)
        }
        return max(colors, key=lambda name: contrast_ratio(name, background))

    @pytest.fixture()
    def fields(self, qtbot):
        """An empty field with a placeholder in thick type, which has
        whole pixels on every platform, next to one that has the focus."""
        host = QWidget()
        qtbot.addWidget(host)
        layout = QVBoxLayout(host)
        focused = QLineEdit()
        field = QLineEdit()
        field.setPlaceholderText("MMMM MMMM")
        font = QFont(field.font())
        font.setPixelSize(22)
        font.setBold(True)
        field.setFont(font)
        layout.addWidget(focused)
        layout.addWidget(field)
        host.resize(420, 160)
        host.show()
        focused.setFocus()
        qtbot.waitExposed(host)
        return host, field

    def test_the_hint_is_painted_in_the_muted_text_color(self, themed, fields):
        _host, field = fields
        painted = QColor(self._strongest(field, themed["base"]))
        wanted = QColor(themed["completed_text"])
        assert abs(painted.red() - wanted.red()) <= 16
        assert abs(painted.green() - wanted.green()) <= 16
        assert abs(painted.blue() - wanted.blue()) <= 16

    def test_the_hint_can_be_read(self, themed, fields):
        _host, field = fields
        strongest = self._strongest(field, themed["base"])
        assert contrast_ratio(strongest, themed["base"]) >= 4.5

    def test_the_style_sheet_names_the_hints_color(self, themed):
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        assert f"placeholder-text-color: {themed['completed_text']};" in app.styleSheet()


class TestTheAccentAsText:
    """The accent, `highlight`, is a fill. As text it gives 4.22:1 on the
    light theme's window, which dialogs, the detail panel and the status
    bar have behind them. Text in the accent is written in the theme's
    link color, which gives 4.5:1 on every background text stands on."""

    def test_no_style_writes_text_in_the_accent(self):
        pattern = re.compile(r"(?<![-\w])color:\s*(palette\(highlight\)|\{colors\[.highlight.\]\})")
        found = [
            f"{path.relative_to(SOURCE_DIR)}: {match.group(0)}"
            for path, text in _sources()
            for match in pattern.finditer(text)
        ]
        assert found == []

    def test_the_link_color_is_in_use(self):
        text = "\n".join(text for _path, text in _sources())
        assert text.count("color: palette(link)") >= 12

    @pytest.mark.parametrize(
        "around", ["window", "base", "alternate_base", "button", "completed_bg"]
    )
    def test_the_link_color_can_be_read_on_every_background(self, themed, around):
        """The button color lies under a tool button under the pointer."""
        assert contrast_ratio(themed["link"], themed[around]) >= 4.5

    def test_the_accent_itself_is_unchanged(self):
        assert LIGHT_COLORS["highlight"] == "#1976d2"
        assert DARK_COLORS["highlight"] == "#64b5f6"

    def test_what_the_link_color_is_for(self):
        """The accent as text on the light theme's window."""
        assert contrast_ratio(LIGHT_COLORS["highlight"], LIGHT_COLORS["window"]) < 4.5

    @pytest.mark.parametrize(
        "key",
        [
            "focus_timer_working",
            "focus_timer_break",
            "focus_timer_paused",
            "focus_timer_stopwatch_running",
        ],
    )
    def test_a_focus_timer_state_can_be_read_on_the_status_bar(self, themed, key):
        assert contrast_ratio(themed[key], themed["window"]) >= 4.5

    def test_syncing_is_written_in_the_link_color(self, themed, qtbot):
        from pytodo_qt.gui.widgets.status_bar import StatusBarWidget

        status_bar = StatusBarWidget()
        qtbot.addWidget(status_bar)
        status_bar.set_sync_status("syncing")
        assert status_bar.sync_status_label.styleSheet() == f"color: {themed['link']};"

    def test_a_button_written_as_a_link_has_no_fill_under_the_pointer(self):
        """The application's rule for a button under the pointer fills
        it with the highlight color, and a text color the button gives
        itself stays on top of that fill: blue on blue."""
        from pytodo_qt.gui.dialogs.web_connect import _LINK_BUTTON_STYLE

        normal, hover = _LINK_BUTTON_STYLE.split("QPushButton:hover")
        assert "color: palette(link)" in normal
        assert "background: transparent" in normal
        assert "background" not in hover
        assert "text-decoration: underline" in hover

    def test_no_flat_button_gives_itself_a_text_color_in_bare_properties(self):
        """A sheet of bare properties holds under the pointer too, where
        the application's rule fills a button with the highlight color:
        the button's own text color then stands on that fill. "Forget all
        devices" was red on blue there. A flat button with a text color
        of its own has rules with selectors, and no fill under the
        pointer."""
        flat = re.compile(r"(\w+)\.setFlat\(True\)")
        for path, text in _sources():
            for match in flat.finditer(text):
                name = re.escape(match.group(1))
                sheet = re.search(
                    rf"{name}\.setStyleSheet\((.*?)\n\s*\)?\n", text[match.end() :], re.DOTALL
                )
                if sheet is None or "color:" not in sheet.group(1):
                    continue
                written = sheet.group(1)
                if "_LINK_BUTTON_STYLE" in written:
                    continue
                assert "QPushButton" in written, f"{path.name}: {match.group(1)}"

    def test_qt_takes_the_link_role_in_a_style_sheet(self, themed, qtbot):
        label = QLabel("a heading")
        qtbot.addWidget(label)
        label.setStyleSheet("color: palette(link);")
        label.ensurePolished()
        assert label.palette().color(label.foregroundRole()).name() == themed["link"]


class TestBorders:
    def test_the_border_color_is_the_themes(self, themed):
        assert border_color() == themed["border"]

    @pytest.mark.parametrize("around", ["base", "window", "alternate_base"])
    def test_a_border_can_be_made_out(self, themed, around):
        assert contrast_ratio(themed["border"], themed[around]) >= 3

    def test_the_calendars_own_tooltips_take_the_themes_colors(self, themed):
        from pytodo_qt.gui.widgets.calendar_view import _persistent_tooltip_sheet

        sheet = _persistent_tooltip_sheet()
        assert f"background: {themed['base']};" in sheet
        assert f"color: {themed['text']};" in sheet
        assert f"border: 1px solid {themed['border']};" in sheet
        assert contrast_ratio(themed["text"], themed["base"]) >= 4.5


class TestStatusBarStates:
    @pytest.fixture()
    def status_bar(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import StatusBarWidget

        widget = StatusBarWidget()
        qtbot.addWidget(widget)
        return widget

    def test_the_states_are_written_in_the_themes_colors(self, themed, status_bar):
        status_bar.set_server_status(True, "192.0.2.1", 5364)
        status_bar.set_web_status(True, 8080)
        status_bar.set_sync_status("error")
        status_bar.set_pending_sync_count(2)

        assert status_bar.server_status_label.styleSheet() == f"color: {themed['due_soon']};"
        assert status_bar.web_status_label.styleSheet() == f"color: {themed['due_soon']};"
        assert status_bar.sync_status_label.styleSheet() == f"color: {themed['due_overdue']};"
        assert status_bar.pending_sync_label.styleSheet() == f"color: {themed['due_today']};"

    @pytest.mark.parametrize("key", ["due_soon", "due_overdue", "due_today", "completed_text"])
    def test_a_state_can_be_read_on_the_status_bar(self, themed, key):
        """The status bar has the window's color."""
        assert contrast_ratio(themed[key], themed["window"]) >= 4.5

    def test_what_is_off_is_muted(self, themed, status_bar):
        status_bar.set_server_status(False)
        status_bar.set_web_status(False)
        status_bar.set_sync_status("idle")

        for label in (
            status_bar.server_status_label,
            status_bar.web_status_label,
            status_bar.sync_status_label,
        ):
            assert label.styleSheet() == "color: palette(placeholder-text);"

    def test_a_state_takes_the_other_themes_color_when_the_theme_changes(
        self, qtbot, monkeypatch, status_bar
    ):
        """The color is written into the label's style when the state
        is set, and a state may stay as it is for hours."""
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        palette, sheet = app.palette(), app.styleSheet()
        try:
            monkeypatch.setattr(
                "pytodo_qt.gui.styles.themes.get_current_theme", lambda: Theme.LIGHT
            )
            apply_theme(app, Theme.LIGHT)
            status_bar.set_server_status(True, "192.0.2.1", 5364)
            status_bar.set_sync_status("error")
            assert LIGHT_COLORS["due_soon"] in status_bar.server_status_label.styleSheet()

            monkeypatch.setattr("pytodo_qt.gui.styles.themes.get_current_theme", lambda: Theme.DARK)
            apply_theme(app, Theme.DARK)
            QApplication.sendEvent(status_bar, QEvent(QEvent.Type.PaletteChange))

            assert status_bar.server_status_label.styleSheet() == (
                f"color: {DARK_COLORS['due_soon']};"
            )
            assert status_bar.sync_status_label.styleSheet() == (
                f"color: {DARK_COLORS['due_overdue']};"
            )
        finally:
            app.setPalette(palette)
            app.setStyleSheet(sheet)

    def test_a_state_that_was_taken_away_is_not_colored_again(self, themed, status_bar):
        status_bar.set_sync_status("error")
        status_bar.set_sync_status("idle")

        QApplication.sendEvent(status_bar, QEvent(QEvent.Type.PaletteChange))

        assert status_bar.sync_status_label.styleSheet() == "color: palette(placeholder-text);"


class TestRichTooltip:
    def test_the_last_line_is_in_the_themes_muted_color(self, themed):
        html = build_rich_tooltip(create_todo_item("a task"), theme_colors=themed)
        assert f"<span style='color:{themed['completed_text']}'>Created " in html

    def test_without_a_theme_the_line_has_no_color(self):
        html = build_rich_tooltip(create_todo_item("a task"))
        assert "color:" not in html
        assert "Created " in html
