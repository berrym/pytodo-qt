"""Text the desktop's widgets write on a coloured fill.

A fill taken from the theme is light in one theme and dark in the
other, so text on it cannot have one fixed colour. Text on the
highlight fill takes the palette's highlighted-text colour; text on a
fill of another theme colour is black or white, whichever has the
higher contrast with it. WCAG AA asks 4.5:1 of text.
"""

from __future__ import annotations

import re
from datetime import date, time
from pathlib import Path

import pytest
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from pytodo_qt.core.bar_palette import contrast_ratio, readable_text_on
from pytodo_qt.core.models import create_todo_item, create_todo_list
from pytodo_qt.gui.styles.themes import DARK_COLORS, LIGHT_COLORS, Theme, apply_theme

GUI_DIR = Path(__file__).resolve().parent.parent / "src" / "pytodo_qt" / "gui"
_THEME_COLORS = {"light": LIGHT_COLORS, "dark": DARK_COLORS}


def _gui_sources() -> list[tuple[Path, str]]:
    return [(path, path.read_text(encoding="utf-8")) for path in sorted(GUI_DIR.rglob("*.py"))]


@pytest.fixture(params=["light", "dark"])
def themed(request, qtbot, monkeypatch):
    """The application in one of the two themes; gives the theme's colours."""
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    theme = Theme(request.param)
    monkeypatch.setattr("pytodo_qt.gui.styles.themes.get_current_theme", lambda: theme)
    palette, sheet = app.palette(), app.styleSheet()
    apply_theme(app, theme)
    yield _THEME_COLORS[request.param]
    app.setPalette(palette)
    app.setStyleSheet(sheet)


def _colours(widget: QWidget) -> set[str]:
    """Every colour of the widget as it is painted."""
    app = QApplication.instance()
    assert app is not None
    for _ in range(3):
        app.processEvents()
    image = widget.grab().toImage()
    return {
        QColor(image.pixel(x, y)).name()
        for y in range(image.height())
        for x in range(image.width())
    }


class TestStylesNameNoFixedTextColourOnAFill:
    """Guards over the source of the desktop's widgets."""

    def test_no_style_writes_white_text(self):
        """White suits a fill in one theme only."""
        pattern = re.compile(r"(?<![-\w])color:\s*(white|#fff\b|#ffffff)", re.IGNORECASE)
        found = [
            f"{path.relative_to(GUI_DIR)}: {match.group(0)}"
            for path, text in _gui_sources()
            for match in pattern.finditer(text)
        ]
        assert found == []

    def test_highlighted_text_role_is_spelled_as_qt_takes_it(self):
        """A style sheet takes `palette(highlighted-text)`. The camel
        case spelling is dropped without a word, and the text keeps
        the ordinary text colour: 1.68:1 on the dark theme's highlight."""
        uses = 0
        for path, text in _gui_sources():
            assert "palette(highlightedText)" not in text, path.name
            uses += text.count("palette(highlighted-text)")
        assert uses >= 9

    def test_no_fill_is_taken_from_a_role_the_theme_does_not_set(self):
        """`mid` and `midlight` are not set by the theme: Qt derives
        them, light grey in both themes, and the dark theme's light
        text on them gives 1.24:1 and 1.50:1."""
        pattern = re.compile(r"background(-color)?:\s*palette\((mid|midlight|dark)\)")
        found = [
            f"{path.relative_to(GUI_DIR)}: {match.group(0)}"
            for path, text in _gui_sources()
            for match in pattern.finditer(text)
        ]
        assert found == []

    def test_every_style_on_the_highlight_fill_names_its_text_colour(self):
        """A rule that fills with the highlight colour and leaves the
        text colour alone gets the ordinary text colour, which was
        chosen for the list's background."""
        rule = re.compile(r"\{([^{}]*background(?:-color)?:\s*palette\(highlight\)[^{}]*)\}")
        for path, text in _gui_sources():
            # Adjacent string literals of one style sheet, joined.
            joined = re.sub(r'"\s*\n\s*f?"', "", text)
            for match in rule.finditer(joined):
                body = match.group(1)
                if "_AgendaRow" in joined[max(0, match.start() - 12) : match.start()]:
                    # The row colours its labels itself, one by one.
                    continue
                assert "color: palette(highlighted-text)" in body, f"{path.name}: {body}"


class TestQtTakesTheRole:
    def test_text_on_the_highlight_fill_is_the_themes_colour_for_it(self, themed, qtbot):
        label = QLabel("MMMMMMMM")
        qtbot.addWidget(label)
        label.setStyleSheet(
            "QLabel { background: palette(highlight); color: palette(highlighted-text);"
            " font-size: 20px; font-weight: bold; }"
        )
        label.resize(200, 40)
        label.show()
        colours = _colours(label)
        assert themed["highlight"] in colours
        assert themed["highlight_text"] in colours
        assert contrast_ratio(themed["highlight_text"], themed["highlight"]) >= 4.5


class TestCalendarButtons:
    def _calendar(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        widget = CalendarViewWidget()
        qtbot.addWidget(widget)
        widget.resize(1000, 500)
        widget.set_list(create_todo_list("List"))
        widget.show()
        return widget

    def test_checked_view_button(self, themed, qtbot):
        widget = self._calendar(qtbot)
        checked = widget._sub_buttons[widget._sub_view]
        assert checked.isChecked()
        colours = _colours(checked)
        assert themed["highlight"] in colours
        assert themed["highlight_text"] in colours
        other = "#ffffff" if themed["highlight_text"] != "#ffffff" else "#1a1a1a"
        assert other not in colours

    def test_checked_timeline_button(self, themed, qtbot, monkeypatch):
        widget = self._calendar(qtbot)
        # Shown without choosing the Timeline: choosing a view is saved.
        widget._timeline_pill_frame.setVisible(True)
        checked = [
            button
            for button in widget._timeline_pill_frame.findChildren(QPushButton)
            if button.isChecked()
        ]
        assert len(checked) == 1
        colours = _colours(checked[0])
        assert themed["highlight"] in colours
        assert themed["highlight_text"] in colours


class TestAgendaRow:
    def _row(self, qtbot, colors, complete=False):
        from pytodo_qt.gui.widgets.calendar_view import _AgendaRow

        item = create_todo_item("Write the report")
        item.due_date = date.today()
        item.due_time = time(16, 0)
        item.tags = ["home", "errand"]
        item.complete = complete
        row = _AgendaRow(item, "24h", colors)
        qtbot.addWidget(row)
        row.resize(600, 30)
        row.show()
        return row

    @staticmethod
    def _text_labels(row) -> list[QLabel]:
        return [label for label in row.findChildren(QLabel) if label.text()]

    def test_selected_rows_text_is_the_colour_for_the_highlight_fill(self, themed, qtbot):
        """The time, the name and the tags have colours of their own,
        chosen for the list's background: the tag's is 1.1:1 on the
        light theme's highlight."""
        row = self._row(qtbot, themed)
        row.set_selected(True)
        labels = self._text_labels(row)
        assert len(labels) == 3
        for label in labels:
            colours = _colours(label)
            assert themed["highlight_text"] in colours, label.text()
            assert themed["entity_tag"] not in colours, label.text()

    def test_completed_selected_row(self, themed, qtbot):
        row = self._row(qtbot, themed, complete=True)
        row.set_selected(True)
        for label in self._text_labels(row):
            assert f"color: {themed['highlight_text']};" in label.styleSheet()
        name = self._text_labels(row)[1]
        assert "text-decoration: line-through;" in name.styleSheet()

    def test_row_gets_its_own_colours_back_when_no_longer_selected(self, themed, qtbot):
        row = self._row(qtbot, themed)
        before = [label.styleSheet() for label in self._text_labels(row)]
        row.set_selected(True)
        assert [label.styleSheet() for label in self._text_labels(row)] != before
        row.set_selected(False)
        assert [label.styleSheet() for label in self._text_labels(row)] == before
        assert f"color: {themed['entity_tag']};" in before[2]

    def test_priority_dot_has_a_ring_on_the_highlight_fill(self, themed, qtbot):
        row = self._row(qtbot, themed)
        dot = next(label for label in row.findChildren(QLabel) if not label.text())
        assert "border: none;" in dot.styleSheet()
        row.set_selected(True)
        assert f"border: 1px solid {themed['highlight_text']};" in dot.styleSheet()

    def test_row_under_the_pointer_keeps_every_text_readable(self, themed):
        """The fill under the pointer is the theme's alternate base,
        with a border in the highlight colour to mark the row."""
        fill = themed["alternate_base"]
        for key in ("text", "completed_text", "entity_tag"):
            assert contrast_ratio(themed[key], fill) >= 4.5, key
        source = (GUI_DIR / "widgets" / "calendar_view.py").read_text(encoding="utf-8")
        start = source.index('"_AgendaRow:hover {')
        rule = source[start : source.index("}", start)]
        assert "background: palette(alternate-base);" in rule
        assert "border: 1px solid palette(highlight);" in rule


class TestWebConnect:
    def test_badge_text_is_the_readable_colour_for_its_fill(self, themed, qtbot):
        from pytodo_qt.gui.dialogs.web_connect import _security_badge

        for key in ("due_soon", "highlight"):
            badge = _security_badge("Encrypted", themed[key])
            qtbot.addWidget(badge)
            text = readable_text_on(themed[key])
            assert f"background: {themed[key]}; color: {text};" in badge.styleSheet()
            assert contrast_ratio(text, themed[key]) >= 4.5

    def test_cards_take_their_badge_colours_from_the_theme(self):
        source = (GUI_DIR / "dialogs" / "web_connect.py").read_text(encoding="utf-8")
        assert 'badge_color=get_colors()["due_soon"],' in source
        assert 'badge_color=get_colors()["highlight"],' in source
        assert "#4CAF50" not in source

    def test_recommended_card(self, themed, qtbot):
        from pytodo_qt.gui.dialogs.web_connect import _MethodCard

        card = _MethodCard(
            icon_text="!",
            title="Trusted Connect",
            subtitle="One-time setup",
            description="Install a certificate.",
            badge_text="Encrypted",
            badge_color=themed["highlight"],
            recommended=True,
        )
        qtbot.addWidget(card)
        card.resize(320, 330)
        card.show()
        ribbon = next(label for label in card.findChildren(QLabel) if label.text() == "Recommended")
        for widget in (ribbon, card._start_btn):
            colours = _colours(widget)
            assert themed["highlight"] in colours
            assert themed["highlight_text"] in colours

    def test_forget_button_under_the_pointer(self, themed):
        """Its fill is the theme's overdue red; the text on it is the
        readable one of black and white."""
        fill = themed["due_overdue"]
        assert contrast_ratio(readable_text_on(fill), fill) >= 4.5
        source = (GUI_DIR / "dialogs" / "web_connect.py").read_text(encoding="utf-8")
        assert 'f" color: {readable_text_on(_danger)}; }}"' in source


class TestOverlayLabels:
    def test_text_on_the_overlay_colour(self):
        """The drag preview and the resize label; the overlay colour
        is the same in both themes."""
        assert LIGHT_COLORS["interactive_overlay"] == DARK_COLORS["interactive_overlay"]
        overlay = LIGHT_COLORS["interactive_overlay"]
        assert contrast_ratio(readable_text_on(overlay), overlay) >= 4.5
        source = (GUI_DIR / "widgets" / "calendar_view.py").read_text(encoding="utf-8")
        assert source.count("color: {readable_text_on(_overlay)};") == 2


class TestFillsUnderOrdinaryText:
    """Fills that the ordinary text colour is written on: a button
    under the pointer, a tag's chip."""

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_button_colour_carries_the_text_colours(self, theme):
        colors = _THEME_COLORS[theme]
        assert contrast_ratio(colors["text"], colors["button"]) >= 4.5
        assert contrast_ratio(colors["button_text"], colors["button"]) >= 4.5

    def test_the_places_that_use_it(self):
        add_todo = (GUI_DIR / "dialogs" / "add_todo.py").read_text(encoding="utf-8")
        assert '" QToolButton:hover { background: palette(button); }"' in add_todo
        web_connect = (GUI_DIR / "dialogs" / "web_connect.py").read_text(encoding="utf-8")
        assert '" QPushButton:hover { background: palette(button);"' in web_connect
        detail = (GUI_DIR / "widgets" / "detail_panel.py").read_text(encoding="utf-8")
        assert "<span style='background: palette(button); padding: 1px 6px; " in detail


class TestListViewSelectedRow:
    """A selected row of the list view is filled with the highlight
    colour. What the row writes straight on its background has colours
    chosen for the ordinary background: 1.08:1 to 3.78:1 on the fill."""

    @pytest.fixture()
    def table(self, qtbot, themed):
        from datetime import timedelta

        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        today = date.today()
        todo_list = create_todo_list("Rows")

        def add(name, **fields):
            item = create_todo_item(name, due_date=fields.pop("due_date", None))
            for key, value in fields.items():
                setattr(item, key, value)
            todo_list.add_item(item)
            return item

        add("overdue", due_date=today - timedelta(days=6))
        add("today", due_date=today)
        add("within the week", due_date=today + timedelta(days=2))
        add("further off", due_date=today + timedelta(days=60))
        add("finished", due_date=today - timedelta(days=30), complete=True)
        add("worked on", time_spent=300, pomodoro_count=1, estimated_pomodoros=2)
        add("tagged", tags=["@one", "@two", "@three"])
        add(
            "recurring",
            due_date=today + timedelta(days=1),
            due_time=time(16, 0),
            recurrence_type="daily",
            recurrence_interval=1,
        )
        parent = add("parent with all done")
        add("child", parent_id=parent.id, complete=True)
        open_parent = add("parent with one open")
        add("open child", parent_id=open_parent.id)
        add("a name " + "that goes on " * 30)

        # A table shown as a window of its own gives the first row's
        # priority box the focus, and that selects the row. Here another
        # field has the focus, as in the application's window.
        window = QWidget()
        qtbot.addWidget(window)
        layout = QVBoxLayout(window)
        elsewhere = QLineEdit()
        widget = TodoTableWidget()
        layout.addWidget(elsewhere)
        layout.addWidget(widget)
        window.resize(900, 700)
        widget.set_list(todo_list)
        elsewhere.setFocus()
        window.show()
        qtbot.waitExposed(window)
        assert widget.get_selected_item_ids() == []
        widget.themed = themed
        widget.shown_in = window  # kept alive with the table
        return widget

    @staticmethod
    def _written_on_the_row(table) -> list[tuple[int, QLabel]]:
        """The labels of every row that have no background of their own."""
        found = []
        for row in range(table.rowCount()):
            for column in (1, 2):
                cell = table.cellWidget(row, column)
                for label in cell.findChildren(QLabel):
                    if label.text() and "background" not in label.styleSheet():
                        found.append((row, label))
        return found

    @staticmethod
    def _text_colour(label: QLabel) -> str:
        label.ensurePolished()
        return label.palette().color(label.foregroundRole()).name()

    def test_the_rows_have_every_kind_of_label(self, table):
        texts = {label.text() for _row, label in self._written_on_the_row(table)}
        assert {"›", "▼", "…", "[1/1]", "[0/1]", "5m", "1/2"} <= texts
        assert any(text.startswith("Overdue") for text in texts)
        assert "Today" in texts

    def test_text_on_a_selected_row_takes_the_highlights_text_colour(self, table):
        colors = table.themed
        table.selectAll()

        labels = self._written_on_the_row(table)
        assert len(labels) >= 20
        for _row, label in labels:
            colour = self._text_colour(label)
            assert colour == colors["highlight_text"], label.text()
            assert contrast_ratio(colour, colors["highlight"]) >= 4.5

    def test_the_colours_come_back_when_the_row_is_no_longer_selected(self, table):
        before = [self._text_colour(label) for _row, label in self._written_on_the_row(table)]
        assert len(set(before)) >= 4

        table.selectAll()
        table.clearSelection()

        after = [self._text_colour(label) for _row, label in self._written_on_the_row(table)]
        assert after == before

    def test_only_the_selected_row_is_recoloured(self, table):
        colors = table.themed
        before = {
            id(label): self._text_colour(label) for _row, label in self._written_on_the_row(table)
        }
        table.selectRow(0)

        for row, label in self._written_on_the_row(table):
            if row == 0:
                assert self._text_colour(label) == colors["highlight_text"]
            else:
                assert self._text_colour(label) == before[id(label)]

    def test_the_weight_that_marks_a_state_is_kept(self, table):
        table.selectAll()
        overdue = next(
            label
            for _row, label in self._written_on_the_row(table)
            if label.text().startswith("Overdue")
        )
        assert "font-weight: bold" in overdue.styleSheet()

    def test_a_row_selected_before_a_refresh_is_recoloured_after_it(self, table):
        colors = table.themed
        table.selectRow(0)

        table.refresh()

        assert table.selectionModel().isRowSelected(0)
        for row, label in self._written_on_the_row(table):
            if row == 0:
                assert self._text_colour(label) == colors["highlight_text"]

    def test_a_tag_chip_on_a_selected_row_has_an_outline(self, table):
        """The chip is filled with the highlight colour, as the row is."""
        colors = table.themed
        chips = [chip for chips in table._row_chips.values() for chip, _style in chips]
        assert len(chips) == 2
        sizes = [chip.sizeHint() for chip in chips]

        table.selectAll()

        for chip, size in zip(chips, sizes, strict=True):
            assert f"border: 1px solid {colors['highlight_text']}" in chip.styleSheet()
            assert chip.sizeHint() == size
        table.clearSelection()
        for chip in chips:
            assert "border: 1px solid" not in chip.styleSheet()

    def test_the_icons_of_a_selected_row_are_drawn_in_the_highlights_text_colour(self, table):
        """The recurrence icon has a fixed blue, 1.38:1 and 1.51:1 on the
        highlight, where a graphic needs 3:1."""
        from pytodo_qt.gui.widgets.todo_table import DueDateLabel

        colors = table.themed
        icons = [icon for icons in table._row_icons.values() for icon, _pixmap in icons]
        for row in range(table.rowCount()):
            due = table.cellWidget(row, 2)
            if isinstance(due, DueDateLabel) and due._icon_label is not None:
                icons.append(due._icon_label)
        assert len(icons) == 2

        def painted(icon: QLabel) -> set[str]:
            """The colours of the icon's strokes, their soft edges left out."""
            # Stored with the colour multiplied by the opacity; undone here.
            image = icon.pixmap().toImage().convertToFormat(QImage.Format.Format_ARGB32)
            colours = set()
            for y in range(image.height()):
                for x in range(image.width()):
                    pixel = QColor.fromRgba(image.pixel(x, y))
                    if pixel.alpha() >= 200:
                        colours.add(pixel.name())
            return colours

        before = [painted(icon) for icon in icons]
        assert all(before)
        table.selectAll()
        wanted = QColor(colors["highlight_text"])
        for icon in icons:
            for name in painted(icon):
                # A soft edge comes back a shade off, from the rounding.
                drawn = QColor(name)
                assert abs(drawn.red() - wanted.red()) <= 2, name
                assert abs(drawn.green() - wanted.green()) <= 2, name
                assert abs(drawn.blue() - wanted.blue()) <= 2, name
                assert contrast_ratio(name, colors["highlight"]) >= 3
        table.clearSelection()
        assert [painted(icon) for icon in icons] == before

    def test_the_selected_row_is_painted_in_two_colours_only(self, table):
        """The Due cell of a selected row, as it is painted: the fill and
        the text, and between them only the blends of the text's edges."""
        colors = table.themed
        table.selectRow(0)
        due = table.cellWidget(0, 2)
        fill, text = colors["highlight"], colors["highlight_text"]

        painted = _colours(due.label)

        assert text in painted
        lowest, highest = sorted((contrast_ratio(fill, fill), contrast_ratio(text, fill)))
        for colour in painted:
            assert lowest <= contrast_ratio(colour, fill) <= highest + 0.01, colour


class TestRecurrenceIcon:
    """The icon's own blue, `#4A90D9`, is one colour for both themes:
    2.93:1 on the light theme's alternate rows, and 1.49:1 to 1.84:1
    where it was faded on a finished task. A graphic needs 3:1."""

    @staticmethod
    def _icon_colours(complete: bool) -> set[str]:
        from pytodo_qt.gui.widgets.todo_table import DueDateLabel

        label = DueDateLabel(date.today(), complete, recurring=True)
        assert label._icon_label is not None
        assert label._icon_label.graphicsEffect() is None
        image = label._icon_label.pixmap().toImage().convertToFormat(QImage.Format.Format_ARGB32)
        colours = set()
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = QColor.fromRgba(image.pixel(x, y))
                if pixel.alpha() >= 200:
                    colours.add(pixel.name())
        assert colours
        return colours

    @staticmethod
    def _close_to(colours: set[str], wanted: str) -> bool:
        target = QColor(wanted)
        return all(
            abs(QColor(name).red() - target.red()) <= 2
            and abs(QColor(name).green() - target.green()) <= 2
            and abs(QColor(name).blue() - target.blue()) <= 2
            for name in colours
        )

    def test_the_icon_is_drawn_in_the_accent_colour(self, themed):
        assert self._close_to(self._icon_colours(complete=False), themed["highlight"])

    def test_the_icon_of_a_finished_task_is_drawn_in_the_muted_text_colour(self, themed):
        assert self._close_to(self._icon_colours(complete=True), themed["completed_text"])

    @pytest.mark.parametrize("key", ["highlight", "completed_text"])
    @pytest.mark.parametrize("row", ["base", "alternate_base"])
    def test_the_icon_can_be_made_out_on_both_row_backgrounds(self, themed, key, row):
        assert contrast_ratio(themed[key], themed[row]) >= 3


class TestListViewOrdinaryRows:
    """The list view's rows alternate between two backgrounds, and a
    colour chosen on the first has to read on the second as well. The
    light theme's green for a task due within the week gave 4.40:1 on
    the alternate row."""

    @pytest.mark.parametrize(
        "key", ["text", "completed_text", "due_overdue", "due_today", "due_soon"]
    )
    @pytest.mark.parametrize("row", ["base", "alternate_base"])
    def test_text_reads_on_both_row_backgrounds(self, themed, key, row):
        assert contrast_ratio(themed[key], themed[row]) >= 4.5
