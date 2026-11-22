"""A single-line label that ends an over-long text with an ellipsis."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPainter, QPalette
from PyQt6.QtWidgets import QLabel, QWidget


class ElidedLabel(QLabel):
    """A single-line label that ends its text with an ellipsis when the
    text is wider than the label.

    A plain QLabel cuts an over-long line at the widget's edge, mid-letter,
    and its minimum width is that of the whole text, so a long text widens
    what holds it: a notification banner, or the status bar and with it the
    window. The size hint is still that of the full text, so the label
    takes the room there is before any text is dropped; the minimum width
    is zero, so the layout can then narrow the label to what is left.
    ``text()`` stays the whole text, which is what a screen reader reads.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def displayed_text(self) -> str:
        """The text as drawn at the label's current width."""
        return self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())

    def paintEvent(self, a0) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.displayed_text(),
        )
        painter.end()
