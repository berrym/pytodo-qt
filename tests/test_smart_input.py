"""Tests for SmartInputWidget, highlighter, chips, and tag completion."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from pytodo_qt.core.nlp_parser import EntityKind, EntitySpan
from pytodo_qt.gui.widgets.smart_input import (
    EntityChip,
    SmartInputWidget,
    _TagCompleterPopup,
)

# ---------------------------------------------------------------------------
# TestSmartInputHighlighter
# ---------------------------------------------------------------------------


class TestSmartInputHighlighter:
    """Test syntax highlighting of entity spans."""

    def test_highlighter_created(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        assert widget._highlighter is not None

    def test_set_spans_triggers_rehighlight(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        spans = [EntitySpan(0, 5, EntityKind.DATE, "today")]
        widget._highlighter.set_spans(spans)
        assert widget._highlighter._spans == spans

    def test_refresh_colors(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        # Should not raise
        widget._highlighter.refresh_colors()


# ---------------------------------------------------------------------------
# TestEntityChip
# ---------------------------------------------------------------------------


class TestEntityChip:
    """Test entity chip display and removal."""

    def test_chip_created(self, qtbot) -> None:
        span = EntitySpan(0, 8, EntityKind.DATE, "tomorrow")
        chip = EntityChip(span)
        qtbot.addWidget(chip)
        assert chip._span is span

    def test_chip_removed_signal(self, qtbot) -> None:
        span = EntitySpan(5, 13, EntityKind.TAG, "@errands")
        chip = EntityChip(span)
        qtbot.addWidget(chip)

        received = []
        chip.removed.connect(lambda s, e: received.append((s, e)))

        # Emit directly since mousePressEvent needs geometry
        chip.removed.emit(span.start, span.end)
        assert received == [(5, 13)]


# ---------------------------------------------------------------------------
# TestTagCompleterPopup
# ---------------------------------------------------------------------------


class TestTagCompleterPopup:
    """Test tag auto-completion popup."""

    def test_set_tags(self, qtbot) -> None:
        popup = _TagCompleterPopup()
        qtbot.addWidget(popup)
        popup.set_tags(["@work", "@home", "@errands"])
        assert popup._all_tags == ["@errands", "@home", "@work"]  # sorted

    def test_filter_shows_matching(self, qtbot) -> None:
        popup = _TagCompleterPopup()
        qtbot.addWidget(popup)
        popup.set_tags(["@work", "@home", "@hobby"])
        from PyQt6.QtCore import QPoint

        popup.filter_and_show("ho", QPoint(0, 0))
        assert popup.count() == 2  # @home, @hobby

    def test_filter_no_match_hides(self, qtbot) -> None:
        popup = _TagCompleterPopup()
        qtbot.addWidget(popup)
        popup.set_tags(["@work", "@home"])
        from PyQt6.QtCore import QPoint

        popup.filter_and_show("xyz", QPoint(0, 0))
        assert popup.count() == 0

    def test_tag_selected_signal(self, qtbot) -> None:
        popup = _TagCompleterPopup()
        qtbot.addWidget(popup)
        popup.set_tags(["@work"])

        received = []
        popup.tag_selected.connect(received.append)

        from PyQt6.QtCore import QPoint

        popup.filter_and_show("wor", QPoint(0, 0))
        item = popup.item(0)
        assert item is not None
        popup._on_activated(item)
        assert received == ["@work"]


# ---------------------------------------------------------------------------
# TestSmartInputWidget
# ---------------------------------------------------------------------------


class TestSmartInputWidget:
    """Test the main smart input widget."""

    def test_get_text_empty(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        assert widget.get_text() == ""

    def test_set_text(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        widget.set_text("hello world")
        assert widget.get_text() == "hello world"

    def test_parse_result_empty(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        result = widget.get_parse_result()
        assert result.reminder == ""

    def test_parse_result_after_text(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        widget.set_text("Buy groceries tomorrow")
        result = widget.get_parse_result()
        assert "groceries" in result.reminder
        assert result.due_date is not None

    def test_parse_changed_signal(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)

        received = []
        widget.parse_changed.connect(received.append)

        widget.set_text("test @tag")
        # Force parse (debounce timer)
        widget.get_parse_result()  # force parse
        assert len(received) >= 1

    def test_set_known_tags(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        widget.set_known_tags(["@work", "@home"])
        assert widget._tag_popup._all_tags == ["@home", "@work"]

    def test_set_focus(self, qtbot) -> None:
        parent = QWidget()
        qtbot.addWidget(parent)
        widget = SmartInputWidget(parent)
        parent.show()
        widget.set_focus()
        # In offscreen mode, focus may not transfer, but should not raise

    def test_refresh_theme(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        # Should not raise
        widget.refresh_theme()

    def test_chip_removal_updates_text(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        widget.set_text("Buy groceries @errands")
        result = widget.get_parse_result()

        # Find the tag span
        tag_spans = [s for s in result.spans if s.kind == EntityKind.TAG]
        assert len(tag_spans) == 1

        # Simulate chip removal
        widget._on_chip_removed(tag_spans[0].start, tag_spans[0].end)
        assert "@errands" not in widget.get_text()

    def test_enter_key_blocked(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        widget.set_text("test")

        from PyQt6.QtTest import QTest

        QTest.keyClick(widget._text_edit, Qt.Key.Key_Return)
        # Should not have a newline
        assert "\n" not in widget.get_text()

    def test_enter_emits_accepted(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        widget.set_text("test")

        from PyQt6.QtTest import QTest

        received = []
        widget.accepted.connect(lambda: received.append(True))
        QTest.keyClick(widget._text_edit, Qt.Key.Key_Return)
        assert len(received) == 1

    def test_multiple_entities_parsed(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        widget.set_text("Meeting tomorrow at 3pm p1 @work")
        result = widget.get_parse_result()
        assert result.due_date is not None
        assert result.due_time is not None
        assert result.priority == 1
        assert "@work" in result.tags

    def test_chips_created_for_entities(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        widget.set_text("Task tomorrow @work p1")
        widget.get_parse_result()  # force parse
        # Count chips (chip_layout has chips + stretch)
        chip_count = widget._chip_layout.count() - 1  # subtract stretch
        assert chip_count >= 1

    def test_placeholder_text(self, qtbot) -> None:
        widget = SmartInputWidget()
        qtbot.addWidget(widget)
        assert "groceries" in widget._text_edit.placeholderText()
