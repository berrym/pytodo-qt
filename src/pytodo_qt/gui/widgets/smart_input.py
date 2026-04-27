"""smart_input.py

Smart text input widget with inline NLP entity highlighting,
entity chips, and tag auto-completion.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.nlp_parser import EntityKind, EntitySpan, ParseResult, parse
from ..styles.themes import Theme, get_current_theme

# ---------------------------------------------------------------------------
# Entity colors — tuned for readability on light and dark backgrounds
# ---------------------------------------------------------------------------

_ENTITY_COLORS: dict[Theme, dict[EntityKind, str]] = {
    Theme.LIGHT: {
        EntityKind.DATE: "#4A90D9",
        EntityKind.TIME: "#4A90D9",
        EntityKind.PRIORITY: "#E8912D",
        EntityKind.TAG: "#2DA5A5",
        EntityKind.RECURRENCE: "#5BA55B",
        EntityKind.POMODORO: "#8B5CF6",
        EntityKind.ESTIMATE: "#D97706",
        EntityKind.WORK_DURATION: "#9333EA",
        EntityKind.TIME_BLOCK: "#4A90D9",
        EntityKind.EVENT_DATE: "#7C3AED",
        EntityKind.CONDITION: "#DC2626",
        EntityKind.FILLER: "#94A3B8",
        EntityKind.SUBTASK: "#0EA5E9",
    },
    Theme.DARK: {
        EntityKind.DATE: "#6AB0F3",
        EntityKind.TIME: "#6AB0F3",
        EntityKind.PRIORITY: "#F0A850",
        EntityKind.TAG: "#4DC4C4",
        EntityKind.RECURRENCE: "#7DC87D",
        EntityKind.POMODORO: "#A78BFA",
        EntityKind.ESTIMATE: "#FBBF24",
        EntityKind.WORK_DURATION: "#C084FC",
        EntityKind.TIME_BLOCK: "#6AB0F3",
        EntityKind.EVENT_DATE: "#A78BFA",
        EntityKind.CONDITION: "#F87171",
        EntityKind.FILLER: "#94A3B8",
        EntityKind.SUBTASK: "#38BDF8",
    },
}


def _get_entity_colors() -> dict[EntityKind, str]:
    """Return entity color map for the active theme."""
    theme = get_current_theme()
    if theme == Theme.DARK:
        return _ENTITY_COLORS[Theme.DARK]
    return _ENTITY_COLORS[Theme.LIGHT]


# ---------------------------------------------------------------------------
# Syntax highlighter
# ---------------------------------------------------------------------------


class SmartInputHighlighter(QSyntaxHighlighter):
    """Highlights NLP entity spans in the text input."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._spans: list[EntitySpan] = []
        self._colors = _get_entity_colors()

    def set_spans(self, spans: list[EntitySpan]) -> None:
        self._spans = spans
        self.rehighlight()

    def refresh_colors(self) -> None:
        self._colors = _get_entity_colors()
        self.rehighlight()

    def highlightBlock(self, text: str | None) -> None:  # noqa: N802
        if text is None:
            return
        block_start = self.currentBlock().position()
        block_end = block_start + len(text)

        for span in self._spans:
            if span.end <= block_start or span.start >= block_end:
                continue
            start = max(span.start - block_start, 0)
            length = min(span.end - block_start, len(text)) - start
            if length <= 0:
                continue

            fmt = QTextCharFormat()
            color = self._colors.get(span.kind, "#888888")
            fmt.setForeground(QColor(color))
            fmt.setFontWeight(700)  # Bold
            self.setFormat(start, length, fmt)


# ---------------------------------------------------------------------------
# Entity chip
# ---------------------------------------------------------------------------


_CONFIDENCE_THRESHOLD = 0.90


class EntityChip(QLabel):
    """Styled QLabel chip for a parsed entity.

    Same pattern as tag chips in todo_table and kanban_board — a single QLabel
    with direct inline stylesheet, mousePressEvent for click handling, and
    setToolTip for hover text. No container widgets, no layout nesting.

    Click on "×" suffix removes the entity. For uncertain matches (confidence < 0.90),
    clicking the chip body accepts the match.
    """

    removed = pyqtSignal(int, int)  # start, end offsets
    confirmed = pyqtSignal(int, int)  # start, end offsets — user accepted uncertain match

    def __init__(
        self,
        span: EntitySpan,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._span = span
        self._uncertain = span.confidence < _CONFIDENCE_THRESHOLD

        if self._uncertain and span.matched:
            # Show matched term inline so user sees why it was flagged
            display = f'{span.display}? \u2190 "{span.matched}"  \u00d7'
        elif self._uncertain:
            display = f"{span.display} ?  \u00d7"
        else:
            display = f"{span.display}  \u00d7"
        self.setText(display)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        if self._uncertain and span.matched:
            pct = round(span.confidence * 100)
            self.setToolTip(
                f"Fuzzy match ({pct}% confidence)\n"
                f'You typed: "{span.display.lower()}"\n'
                f'Matched: "{span.matched}"\n\n'
                f"Click to accept \u2022 \u00d7 to remove"
            )

        self._apply_style()

    def _apply_style(self) -> None:
        colors = _get_entity_colors()
        color = colors.get(self._span.kind, "#888888")
        r, g, b = _hex_to_rgb(color)
        # Scope to QLabel so tooltip rendering is not affected by cascade
        if self._uncertain:
            self.setStyleSheet(
                f"QLabel {{ background-color: rgba({r}, {g}, {b}, 15); "
                f"color: {color}; "
                f"border: 1px dashed rgba({r}, {g}, {b}, 128); "
                "border-radius: 8px; padding: 1px 6px; "
                "font-size: 11px; font-weight: bold; }"
            )
        else:
            self.setStyleSheet(
                f"QLabel {{ background-color: rgba({r}, {g}, {b}, 30); "
                f"color: {color}; "
                f"border: 1px solid rgba({r}, {g}, {b}, 97); "
                "border-radius: 8px; padding: 1px 6px; "
                "font-size: 11px; font-weight: bold; }"
            )

    def mousePressEvent(self, ev: QMouseEvent | None) -> None:  # noqa: N802
        if ev is None:
            return
        # Right ~16px is the "×" remove zone
        if ev.position().x() > self.width() - 18:
            self.removed.emit(self._span.start, self._span.end)
            return
        # Body click — accept uncertain match
        if self._uncertain:
            self._uncertain = False
            self._span = EntitySpan(
                self._span.start,
                self._span.end,
                self._span.kind,
                self._span.display,
                1.0,
                self._span.matched,
            )
            self.setText(f"{self._span.display}  \u00d7")
            self.setToolTip("")
            self._apply_style()
            self.confirmed.emit(self._span.start, self._span.end)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' to (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ---------------------------------------------------------------------------
# Tag completer popup
# ---------------------------------------------------------------------------


class _TagCompleterPopup(QListWidget):
    """Popup list for tag auto-completion."""

    tag_selected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Popup)
        self.setMaximumHeight(150)
        self.setMaximumWidth(200)
        self.itemActivated.connect(self._on_activated)
        self._all_tags: list[str] = []

    def set_tags(self, tags: list[str]) -> None:
        self._all_tags = sorted(tags)

    def filter_and_show(self, prefix: str, pos_global: QPoint) -> None:
        """Filter tags by prefix and show popup at global position."""
        self.clear()
        prefix_lower = prefix.lower()
        for tag in self._all_tags:
            # Strip @ for comparison
            tag_name = tag.lstrip("@")
            if tag_name.lower().startswith(prefix_lower):
                item = QListWidgetItem(tag)
                self.addItem(item)

        if self.count() == 0:
            self.hide()
            return

        self.setCurrentRow(0)
        self.move(pos_global)
        self.show()

    def _on_activated(self, item: QListWidgetItem) -> None:
        self.tag_selected.emit(item.text())
        self.hide()

    def keyPressEvent(self, e: QKeyEvent | None) -> None:  # noqa: N802
        if e is None:
            return
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
            current = self.currentItem()
            if current:
                self._on_activated(current)
            return
        super().keyPressEvent(e)


# ---------------------------------------------------------------------------
# Main smart input widget
# ---------------------------------------------------------------------------


class SmartInputWidget(QWidget):
    """Smart text input with NLP parsing, entity highlighting, and chips."""

    parse_changed = pyqtSignal(object)  # emits ParseResult
    accepted = pyqtSignal()  # Enter pressed (request dialog accept)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._parse_result = ParseResult(reminder="")
        self._accepted_spans: set[tuple[int, int]] = (
            set()
        )  # (start, end) of confirmed fuzzy matches
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(100)
        self._debounce_timer.timeout.connect(self._do_parse)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Text input — QTextEdit constrained to single line
        self._text_edit = QTextEdit()
        self._text_edit.setAcceptRichText(False)
        self._text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._text_edit.setFixedHeight(32)
        self._text_edit.setPlaceholderText(
            self.tr("e.g. Plan trip tomorrow at 3pm @errands p1: book flight, pack")
        )
        self._text_edit.textChanged.connect(self._on_text_changed)
        self._text_edit.installEventFilter(self)
        layout.addWidget(self._text_edit)

        # Highlighter
        doc = self._text_edit.document()
        assert doc is not None
        self._highlighter = SmartInputHighlighter(doc)

        # Chip row
        self._chip_container = QWidget()
        self._chip_layout = QHBoxLayout(self._chip_container)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(4)
        self._chip_layout.addStretch()
        layout.addWidget(self._chip_container)

        # Tag completer
        self._tag_popup = _TagCompleterPopup()
        self._tag_popup.tag_selected.connect(self._insert_tag)
        self._tag_prefix_start: int | None = None

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:  # noqa: N802
        """Intercept Enter to prevent newlines (single-line mode)."""
        if (
            a0 is self._text_edit
            and isinstance(a1, QKeyEvent)
            and a1.type() == QEvent.Type.KeyPress
        ):
            if a1.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._tag_popup.isVisible():
                    # Forward to popup
                    self._tag_popup.keyPressEvent(a1)
                    return True
                # Accept input on Enter
                self.accepted.emit()
                return True
            if a1.key() == Qt.Key.Key_Escape and self._tag_popup.isVisible():
                self._tag_popup.hide()
                return True
            # Track @ and # for tag completion
            if a1.text() in ("@", "#"):
                QTimer.singleShot(0, self._start_tag_completion)
        return super().eventFilter(a0, a1)

    def _start_tag_completion(self) -> None:
        """Start tag completion after @ or # is typed."""
        cursor = self._text_edit.textCursor()
        self._tag_prefix_start = cursor.position()
        self._update_tag_popup()

    def _on_text_changed(self) -> None:
        """Debounce text changes."""
        self._debounce_timer.start()
        # Update tag popup if active
        if self._tag_prefix_start is not None:
            self._update_tag_popup()

    def _update_tag_popup(self) -> None:
        """Update tag completion popup based on current cursor position."""
        if self._tag_prefix_start is None:
            return

        text = self._text_edit.toPlainText()
        cursor_pos = self._text_edit.textCursor().position()

        if cursor_pos < self._tag_prefix_start:
            self._tag_popup.hide()
            self._tag_prefix_start = None
            return

        # Extract typed prefix after @ or #
        prefix = text[self._tag_prefix_start : cursor_pos]
        if " " in prefix or not prefix:
            self._tag_popup.hide()
            self._tag_prefix_start = None
            return

        # Position popup below cursor
        cursor_rect = self._text_edit.cursorRect()
        pos = self._text_edit.mapToGlobal(cursor_rect.bottomLeft())
        self._tag_popup.filter_and_show(prefix, pos)

    def _insert_tag(self, tag: str) -> None:
        """Insert selected tag from popup."""
        if self._tag_prefix_start is None:
            return

        text = self._text_edit.toPlainText()
        cursor_pos = self._text_edit.textCursor().position()

        # Replace from the @ character (one before prefix_start) to cursor
        at_pos = self._tag_prefix_start - 1
        if at_pos >= 0:
            new_text = text[:at_pos] + tag + " " + text[cursor_pos:]
            self._text_edit.setPlainText(new_text)
            # Move cursor after inserted tag
            cursor = self._text_edit.textCursor()
            cursor.setPosition(at_pos + len(tag) + 1)
            self._text_edit.setTextCursor(cursor)

        self._tag_prefix_start = None
        self._tag_popup.hide()

    def _do_parse(self) -> None:
        """Parse current text and update UI.

        Guarded against the underlying C++ widgets being torn down
        while a debounce-timer tick is still queued — this happens
        in headless tests that construct an AddTodoDialog, check an
        attribute, and let the dialog fall out of scope before the
        100 ms debounce fires. Without the guard, the queued tick
        invokes `_do_parse` on a widget whose SmartInputHighlighter
        QObject has already been deleted by Qt, producing the
        ``RuntimeError: wrapped C/C++ object ... has been deleted``
        that was failing CI on Linux/3.12.
        """
        try:
            text = self._text_edit.toPlainText()
        except RuntimeError:
            return  # widget destroyed; nothing to do
        self._parse_result = parse(text)

        # Apply accepted state — user already confirmed these fuzzy matches
        for i, span in enumerate(self._parse_result.spans):
            if (span.start, span.end) in self._accepted_spans and span.confidence < 1.0:
                self._parse_result.spans[i] = EntitySpan(
                    span.start,
                    span.end,
                    span.kind,
                    span.display,
                    1.0,
                    span.matched,
                )

        # Update highlighter
        try:
            self._highlighter.set_spans(self._parse_result.spans)
        except RuntimeError:
            return  # highlighter was torn down mid-tick

        # Update chips
        try:
            self._update_chips()
        except RuntimeError:
            return  # chip container was torn down mid-tick

        self.parse_changed.emit(self._parse_result)

    def _update_chips(self) -> None:
        """Rebuild entity chips from current parse result."""
        # Clear existing chips
        while self._chip_layout.count() > 1:  # Keep the stretch
            item = self._chip_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()

        for span in self._parse_result.spans:
            if not span.display:
                continue
            chip = EntityChip(span, self._chip_container)
            chip.removed.connect(self._on_chip_removed)
            chip.confirmed.connect(self._on_chip_confirmed)
            # Insert before the stretch
            self._chip_layout.insertWidget(self._chip_layout.count() - 1, chip)

    def _on_chip_removed(self, start: int, end: int) -> None:
        """Remove entity text from input when chip X is clicked."""
        text = self._text_edit.toPlainText()

        # Check for leading prefix word (due, by, on, before)
        prefix_start = start
        if start > 0:
            before = text[:start]
            prefix_m = re.search(r"(?:due|by|on|before)\s+$", before, re.IGNORECASE)
            if prefix_m:
                prefix_start = prefix_m.start()

        # Remove the span and collapse whitespace
        new_text = text[:prefix_start] + text[end:]
        # Collapse multiple spaces
        new_text = " ".join(new_text.split())
        self._text_edit.setPlainText(new_text)

    def _on_chip_confirmed(self, start: int, end: int) -> None:
        """Mark a fuzzy match as accepted so re-parse preserves it."""
        self._accepted_spans.add((start, end))
        # Re-parse to rebuild chips with confirmed state
        self._do_parse()

    # --- Public API ---

    def get_parse_result(self) -> ParseResult:
        """Return the latest ParseResult."""
        # Force immediate parse if timer is active
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()
            self._do_parse()
        return self._parse_result

    def get_text(self) -> str:
        return self._text_edit.toPlainText()

    def set_text(self, text: str) -> None:
        self._accepted_spans.clear()
        self._text_edit.setPlainText(text)

    def set_known_tags(self, tags: list[str]) -> None:
        """Set tags available for auto-completion."""
        self._tag_popup.set_tags(tags)

    def set_focus(self) -> None:
        """Focus the text input."""
        self._text_edit.setFocus()

    def refresh_theme(self) -> None:
        """Refresh colors after a theme change."""
        self._highlighter.refresh_colors()
        self._update_chips()
