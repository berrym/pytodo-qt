"""smart_input.py

Smart text input widget with inline NLP entity highlighting,
entity chips, and tag auto-completion.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
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
    },
    Theme.DARK: {
        EntityKind.DATE: "#6AB0F3",
        EntityKind.TIME: "#6AB0F3",
        EntityKind.PRIORITY: "#F0A850",
        EntityKind.TAG: "#4DC4C4",
        EntityKind.RECURRENCE: "#7DC87D",
        EntityKind.POMODORO: "#A78BFA",
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


class EntityChip(QWidget):
    """Small pill showing a parsed entity with a remove button."""

    removed = pyqtSignal(int, int)  # start, end offsets

    def __init__(
        self,
        span: EntitySpan,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._span = span

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 2, 1)
        layout.setSpacing(2)

        label = QLabel(span.display)
        label.setStyleSheet(self._label_style())
        layout.addWidget(label)

        remove_btn = QPushButton("\u00d7")  # × character
        remove_btn.setFixedSize(16, 16)
        remove_btn.setStyleSheet(
            "QPushButton { border: none; font-weight: bold; font-size: 12px; }"
        )
        remove_btn.clicked.connect(self._on_remove)
        layout.addWidget(remove_btn)

        self.setStyleSheet(self._pill_style())
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _label_style(self) -> str:
        colors = _get_entity_colors()
        color = colors.get(self._span.kind, "#888888")
        return f"QLabel {{ color: {color}; font-weight: bold; font-size: 11px; }}"

    def _pill_style(self) -> str:
        colors = _get_entity_colors()
        color = colors.get(self._span.kind, "#888888")
        return (
            f"EntityChip {{ background: {color}20; border: 1px solid {color}60; "
            f"border-radius: 8px; }}"
        )

    def _on_remove(self) -> None:
        self.removed.emit(self._span.start, self._span.end)


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
        self._text_edit.setPlaceholderText("e.g. Buy groceries tomorrow at 3pm @errands p1")
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
        """Parse current text and update UI."""
        text = self._text_edit.toPlainText()
        self._parse_result = parse(text)

        # Update highlighter
        self._highlighter.set_spans(self._parse_result.spans)

        # Update chips
        self._update_chips()

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
