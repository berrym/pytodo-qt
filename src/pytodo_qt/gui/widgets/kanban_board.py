"""kanban_board.py

Kanban board view with card, column, and board widgets.
"""

from __future__ import annotations

import contextlib
from datetime import date, time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtCore import QMimeData, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.logger import Logger
from ...core.models import TodoItem, TodoList
from ..styles.themes import get_colors


class ClickableLabel(QLabel):
    """QLabel that emits a clicked signal on mouse press."""

    clicked = pyqtSignal()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        self.clicked.emit()


_CHECK_ICON_PATH: str | None = None


def _check_icon_path() -> str:
    """Return the absolute path to check.svg, cached."""
    global _CHECK_ICON_PATH  # noqa: PLW0603
    if _CHECK_ICON_PATH is None:
        _CHECK_ICON_PATH = str(Path(__file__).parent.parent / "icons" / "check.svg")
    return _CHECK_ICON_PATH


if TYPE_CHECKING:
    from ..widgets.search_filter import FilterState

logger = Logger(__name__)

CARD_WIDTH = 260
COLUMN_WIDTH = 310
KANBAN_MIME_TYPE = "application/x-pytodo-kanban-item"

# Board layout presets — last column is always the completion column
BOARD_PRESETS: dict[str, list[str]] = {
    "Simple": ["To Do", "In Progress", "Done"],
    "With Review": ["To Do", "In Progress", "Review", "Done"],
    "With Testing": ["To Do", "In Progress", "Review", "Testing", "Done"],
    "Backlog": ["Backlog", "To Do", "In Progress", "Done"],
}


def _sort_fragment(item: TodoItem, dimension: str, reverse: bool) -> tuple:
    """Return a comparable tuple fragment for one sort dimension."""
    if dimension == "completion":
        val = 1 if item.complete else 0
        return (-val,) if reverse else (val,)
    elif dimension == "due_date":
        if item.due_date is None:
            return (1, 0, 0)
        date_ord = item.due_date.toordinal()
        time_secs = -1
        if item.due_time is not None:
            time_secs = item.due_time.hour * 3600 + item.due_time.minute * 60 + item.due_time.second
        if reverse:
            return (0, -date_ord, -time_secs)
        return (0, date_ord, time_secs)
    elif dimension == "priority":
        val = item.priority
        return (-val,) if reverse else (val,)
    return ()


def _is_overdue(due_date: date | None, due_time: time | None) -> bool:
    """Check if an item is overdue."""
    if due_date is None:
        return False
    from datetime import datetime

    today = date.today()
    if due_date < today:
        return True
    if due_date == today and due_time is not None:
        now = datetime.now().time()
        return due_time < now
    return False


def _format_due(due_date: date, due_time: time | None, time_format: str) -> str:
    """Format a due date for display on a card."""
    today = date.today()
    delta = (due_date - today).days
    if delta == 0:
        label = "Today"
    elif delta == 1:
        label = "Tomorrow"
    elif delta == -1:
        label = "Yesterday"
    elif 0 < delta <= 6:
        label = due_date.strftime("%A")
    else:
        label = due_date.strftime("%b %d")
    if due_time is not None:
        if time_format == "12h":
            label += due_time.strftime(" %I:%M %p").replace(" 0", " ")
        elif time_format == "24h":
            label += due_time.strftime(" %H:%M")
        else:
            label += due_time.strftime(" %I:%M %p").replace(" 0", " ")
    return label


def _recurrence_tooltip(item: TodoItem) -> str:
    """Build a descriptive tooltip for recurrence settings."""
    rtype = item.recurrence_type or "daily"
    interval = item.recurrence_interval
    unit_map = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}
    unit = unit_map.get(rtype, rtype)
    if interval == 1:
        text = f"Repeats {rtype}"
    else:
        text = f"Every {interval} {unit}s"
    if item.recurrence_end_date:
        text += f"\nUntil {item.recurrence_end_date.strftime('%b %d, %Y')}"
    if item.recurrence_end_count is not None:
        text += f"\n{item.recurrence_count}/{item.recurrence_end_count} completed"
    if item.missed_recurrences > 0:
        text += f"\n{item.missed_recurrences} missed (auto-advanced)"
    return text


# ---------------------------------------------------------------------------
# KanbanCardWidget
# ---------------------------------------------------------------------------


class KanbanCardWidget(QFrame):
    """A single kanban card representing a todo item."""

    clicked = pyqtSignal(object)  # (item_id)
    double_clicked = pyqtSignal(object)  # (item_id)
    context_menu_requested = pyqtSignal(object, QPoint)  # (item_id, global_pos)
    toggle_requested = pyqtSignal(object)  # (item_id) — card-level, has ID
    edit_tags_requested = pyqtSignal(object)  # (item_id)

    def __init__(
        self,
        item: TodoItem,
        colors: dict[str, str],
        time_format: str,
        subtasks: list[TodoItem] | None = None,
        is_focus_item: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._item_id = item.id
        self._colors = colors
        self._tags = list(item.tags) if item.tags else []
        self._expanded = False
        self._subtasks = subtasks or []
        self._drag_start: QPoint | None = None
        self._is_focus_item = is_focus_item

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_menu_requested.emit(self._item_id, self.mapToGlobal(pos))
        )

        # Priority color
        priority_colors = {
            1: colors["priority_high"],
            2: colors["priority_normal"],
            3: colors["priority_low"],
        }
        border_color = priority_colors.get(item.priority, colors["priority_normal"])

        # Background
        bg = colors["completed_bg"] if item.complete else colors["base"]
        text_color = colors["completed_text"] if item.complete else colors["text"]

        self._style_normal = (
            f"KanbanCardWidget {{ background: {bg};"
            f" border: 1px solid {colors['border']};"
            f" border-left: 4px solid {border_color};"
            " border-radius: 8px; padding: 0px; }"
        )
        self._style_selected = (
            f"KanbanCardWidget {{ background: {bg};"
            f" border: 2px solid {colors['highlight']};"
            f" border-left: 4px solid {border_color};"
            " border-radius: 8px; padding: 0px; }"
        )
        self.setStyleSheet(self._style_normal)

        # Drop shadow (enhanced glow for active focus session)
        shadow = QGraphicsDropShadowEffect(self)
        if is_focus_item:
            from PyQt6.QtGui import QColor

            shadow.setBlurRadius(16)
            shadow.setOffset(0, 0)
            shadow.setColor(QColor(colors["highlight"]))
        else:
            shadow.setBlurRadius(6)
            shadow.setOffset(0, 1)
            shadow.setColor(Qt.GlobalColor.gray)
        self.setGraphicsEffect(shadow)

        # Layout
        card_layout = QVBoxLayout(self)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(4)

        # Row 1: Priority dot + Reminder + Checkbox
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        # Priority dot
        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background: {border_color}; border-radius: 5px; border: none;")
        row1.addWidget(dot)

        # Reminder label
        reminder_label = QLabel(item.reminder or "(no text)")
        reminder_label.setWordWrap(True)
        reminder_label.setStyleSheet(
            f"color: {text_color}; border: none; font-size: 13px;"
            + (" text-decoration: line-through;" if item.complete else "")
        )
        row1.addWidget(reminder_label, 1)

        # Checkbox — custom styled circle with checkmark
        checkbox = QCheckBox()
        checkbox.setChecked(item.complete)
        checkbox.setFixedSize(20, 20)
        check_svg = _check_icon_path()
        checkbox.setStyleSheet(
            "QCheckBox { border: none; }"
            "QCheckBox::indicator {"
            "  width: 16px; height: 16px;"
            "  border-radius: 8px;"
            f"  border: 2px solid {colors['highlight']};"
            "  background: transparent;"
            "}"
            "QCheckBox::indicator:checked {"
            f"  background: {colors['highlight']};"
            f"  border: 2px solid {colors['highlight']};"
            f"  image: url({check_svg});"
            "}"
        )
        checkbox.toggled.connect(lambda _: self.toggle_requested.emit(self._item_id))
        row1.addWidget(checkbox)

        card_layout.addLayout(row1)

        # Row 2: Due date + Recurrence + Pomo count (conditional)
        has_due = item.due_date is not None
        has_recurrence = item.is_recurring
        has_pomo = item.pomodoro_count > 0

        if has_due or has_recurrence or has_pomo or is_focus_item:
            row2 = QHBoxLayout()
            row2.setSpacing(6)

            if has_due and item.due_date is not None:
                due_text = _format_due(item.due_date, item.due_time, time_format)
                overdue = _is_overdue(item.due_date, item.due_time) and not item.complete
                if overdue:
                    due_text = f"\u26a0 {due_text}"  # ⚠ prefix
                due_label = QLabel(due_text)
                if overdue:
                    due_color = colors["due_overdue"]
                    due_label.setStyleSheet(
                        f"color: {due_color}; font-size: 11px; font-weight: bold; border: none;"
                    )
                elif item.due_date == date.today():
                    due_color = colors["due_today"]
                    due_label.setStyleSheet(f"color: {due_color}; font-size: 11px; border: none;")
                else:
                    due_color = colors["due_soon"]
                    due_label.setStyleSheet(f"color: {due_color}; font-size: 11px; border: none;")
                # Tooltip with full date/time details
                tip_parts = [item.due_date.strftime("%A, %B %d, %Y")]
                if item.due_time is not None:
                    if time_format == "24h":
                        tip_parts.append(item.due_time.strftime("%H:%M"))
                    else:
                        tip_parts.append(item.due_time.strftime("%I:%M %p").lstrip("0"))
                if overdue:
                    tip_parts.append("(overdue)")
                due_label.setToolTip(" ".join(tip_parts))
                row2.addWidget(due_label)

            if has_recurrence:
                rec_label = QLabel("\u21bb")  # ↻
                rec_label.setToolTip(_recurrence_tooltip(item))
                rec_label.setStyleSheet(
                    f"color: {colors['completed_text']}; font-size: 13px; border: none;"
                )
                row2.addWidget(rec_label)

                if item.missed_recurrences > 0:
                    missed_label = QLabel(f"{item.missed_recurrences} missed")
                    missed_label.setToolTip(
                        f"{item.missed_recurrences} occurrence(s) auto-advanced"
                    )
                    missed_label.setStyleSheet(
                        f"color: {colors['due_today']}; font-size: 10px;"
                        " font-style: italic; border: none;"
                    )
                    row2.addWidget(missed_label)

            row2.addStretch()

            if has_pomo:
                pomo_label = QLabel(f"\U0001f345 {item.pomodoro_count}")
                pomo_label.setStyleSheet(
                    f"color: {colors['completed_text']}; font-size: 11px; border: none;"
                )
                row2.addWidget(pomo_label)

            if is_focus_item:
                focus_label = QLabel("\u23f1 Focus")  # ⏱ Focus
                focus_label.setStyleSheet(
                    f"color: {colors['highlight']}; font-size: 11px; "
                    "font-weight: bold; border: none;"
                )
                row2.addWidget(focus_label)

            card_layout.addLayout(row2)

        # Row 3: Tags (if any)
        if item.tags:
            row3 = QHBoxLayout()
            row3.setSpacing(4)
            max_tags = 3
            for tag in item.tags[:max_tags]:
                chip = QLabel(tag)
                chip.setStyleSheet(
                    f"background: {colors['alternate_base']}; "
                    f"color: {colors['text']}; "
                    "border-radius: 4px; padding: 1px 4px; "
                    "font-size: 10px; border: none;"
                )
                row3.addWidget(chip)
            if len(item.tags) > max_tags:
                overflow = ClickableLabel(f"+{len(item.tags) - max_tags}")
                overflow.setStyleSheet(
                    f"background-color: {colors['button']}; "
                    f"color: {colors['text']}; "
                    "border-radius: 8px; padding: 1px 6px; font-size: 10px; border: none;"
                )
                overflow.setCursor(Qt.CursorShape.PointingHandCursor)
                overflow.clicked.connect(lambda b=overflow: self._show_tag_popup(max_tags, b))
                row3.addWidget(overflow)
            row3.addStretch()
            card_layout.addLayout(row3)

        # Row 4: Subtask badge (if any)
        if self._subtasks:
            done = sum(1 for s in self._subtasks if s.complete)
            total = len(self._subtasks)
            self._subtask_badge = QPushButton(f"\u2630 {done}/{total} subtasks")
            badge_color = colors["due_soon"] if done == total else colors["completed_text"]
            self._subtask_badge.setStyleSheet(
                f"color: {badge_color}; font-size: 11px; "
                "border: none; text-align: left; padding: 2px 0px; "
                "background: transparent;"
            )
            self._subtask_badge.setCursor(Qt.CursorShape.PointingHandCursor)
            self._subtask_badge.clicked.connect(self._toggle_subtask_list)
            card_layout.addWidget(self._subtask_badge)

            # Row 5: Subtask checklist (hidden by default)
            self._subtask_container = QWidget()
            self._subtask_container.setVisible(False)
            sub_layout = QVBoxLayout(self._subtask_container)
            sub_layout.setContentsMargins(16, 0, 0, 0)
            sub_layout.setSpacing(2)

            for subtask in self._subtasks:
                sub_row = QHBoxLayout()
                sub_row.setSpacing(4)
                sub_cb = QCheckBox()
                sub_cb.setChecked(subtask.complete)
                sub_cb.setFixedSize(16, 16)
                sub_cb.setStyleSheet(
                    "QCheckBox { border: none; }"
                    "QCheckBox::indicator {"
                    "  width: 12px; height: 12px;"
                    "  border-radius: 6px;"
                    f"  border: 2px solid {colors['highlight']};"
                    "  background: transparent;"
                    "}"
                    "QCheckBox::indicator:checked {"
                    f"  background: {colors['highlight']};"
                    f"  border: 2px solid {colors['highlight']};"
                    f"  image: url({check_svg});"
                    "}"
                )
                sub_id = subtask.id
                sub_cb.toggled.connect(lambda _, sid=sub_id: self.toggle_requested.emit(sid))
                sub_row.addWidget(sub_cb)
                sub_label = QLabel(subtask.reminder)
                sub_label.setStyleSheet(
                    f"color: {text_color}; font-size: 11px; border: none;"
                    + (" text-decoration: line-through;" if subtask.complete else "")
                )
                sub_label.setWordWrap(True)
                sub_row.addWidget(sub_label, 1)
                sub_layout.addLayout(sub_row)

            card_layout.addWidget(self._subtask_container)

    def _show_tag_popup(self, max_tags: int, badge: QWidget) -> None:
        """Show a popup with all overflow tags as styled chips."""
        colors = self._colors
        chip_style = (
            f"background-color: {colors['highlight']}; "
            f"color: {colors.get('highlight_text', '#ffffff')}; "
            "border-radius: 8px; padding: 2px 8px; font-size: 10px;"
        )

        popup = QWidget(self, Qt.WindowType.Popup)
        layout = QHBoxLayout(popup)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        for tag in self._tags[max_tags:]:
            chip = QLabel(tag)
            chip.setStyleSheet(chip_style)
            layout.addWidget(chip)

        edit_btn = QPushButton("Edit...")
        edit_btn.setFixedHeight(20)
        edit_btn.setStyleSheet("font-size: 10px; padding: 1px 6px;")
        edit_btn.clicked.connect(lambda: self._on_popup_edit(popup))
        layout.addWidget(edit_btn)

        popup.adjustSize()
        pos = badge.mapToGlobal(QPoint(0, badge.height() + 2))
        popup.move(pos)
        popup.show()

    def _on_popup_edit(self, popup: QWidget) -> None:
        """Handle 'Edit...' click in tag popup."""
        popup.close()
        self.edit_tags_requested.emit(self._item_id)

    def _toggle_subtask_list(self) -> None:
        """Toggle subtask checklist visibility."""
        self._expanded = not self._expanded
        self._subtask_container.setVisible(self._expanded)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        """Track drag start position."""
        if a0 is None:
            return
        if a0.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(a0.pos())
            if isinstance(child, QCheckBox):
                super().mousePressEvent(a0)
                return
            self._drag_start = a0.pos()
        super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        """Start drag if moved enough."""
        if a0 is None or self._drag_start is None:
            return
        if (a0.pos() - self._drag_start).manhattanLength() < 10:
            return
        self._start_drag()

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        """Handle click (not drag)."""
        if a0 is None:
            return
        if self._drag_start is not None and a0.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(a0.pos())
            if not isinstance(child, QCheckBox):
                self.clicked.emit(self._item_id)
        self._drag_start = None
        super().mouseReleaseEvent(a0)

    def set_selected(self, selected: bool) -> None:
        """Set visual selection state."""
        self.setStyleSheet(self._style_selected if selected else self._style_normal)

    def mouseDoubleClickEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        """Handle double-click — emit for edit reminder."""
        if a0 is not None:
            self.double_clicked.emit(self._item_id)

    def _start_drag(self) -> None:
        """Initiate drag-and-drop."""
        from PyQt6 import sip

        item_id = self._item_id
        board = self._find_board()
        if board:
            board._dragging = True

        drag = QDrag(board or self)  # Parent to board for safety
        mime = QMimeData()
        mime.setData(KANBAN_MIME_TYPE, str(item_id).encode())
        drag.setMimeData(mime)

        drag.exec(Qt.DropAction.MoveAction)

        if board:
            board._dragging = False
            if board._refresh_pending:
                board._refresh_pending = False
                board.refresh()

        if sip.isdeleted(self):
            return
        self._drag_start = None

    def _find_board(self) -> KanbanBoardWidget | None:
        """Walk up parent chain to find the board widget."""
        p = self.parent()
        while p is not None:
            if isinstance(p, KanbanBoardWidget):
                return p
            p = p.parent()
        return None


# ---------------------------------------------------------------------------
# KanbanColumnWidget
# ---------------------------------------------------------------------------


class KanbanColumnWidget(QFrame):
    """A single kanban column containing cards."""

    card_clicked = pyqtSignal(object)  # (item_id)
    card_double_clicked = pyqtSignal(object)  # (item_id)
    card_context_menu = pyqtSignal(object, QPoint)  # (item_id, global_pos)
    card_toggle = pyqtSignal(object)  # (item_id)
    card_edit_tags = pyqtSignal(object)  # (item_id)
    card_dropped = pyqtSignal(object, str)  # (item_id, column_name)
    add_item_clicked = pyqtSignal(str)  # (column_name)
    rename_requested = pyqtSignal(str)  # (column_name)
    delete_requested_col = pyqtSignal(str)  # (column_name)
    set_wip_limit_requested = pyqtSignal(str)  # (column_name)

    def __init__(
        self,
        column_name: str,
        colors: dict[str, str],
        wip_limit: int = 0,
        is_first: bool = False,
        is_last: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._column_name = column_name
        self._colors = colors
        self._cards: list[KanbanCardWidget] = []
        self._wip_limit = wip_limit
        self._is_first = is_first
        self._is_last = is_last

        self.setFixedWidth(COLUMN_WIDTH)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            f"""
            KanbanColumnWidget {{
                background: {colors["alternate_base"]};
                border: 1px solid {colors["border"]};
                border-radius: 8px;
            }}
            """
        )

        col_layout = QVBoxLayout(self)
        col_layout.setContentsMargins(8, 8, 8, 8)
        col_layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        # Column role indicator
        if is_first:
            inbox_icon = QLabel("\U0001f4e5")  # 📥
            inbox_icon.setToolTip("Inbox column — new items land here")
            inbox_icon.setStyleSheet("border: none; font-size: 12px;")
            header.addWidget(inbox_icon)
        elif is_last:
            check_icon = QLabel("\u2705")  # ✅
            check_icon.setToolTip("Completion column — items moved here are marked complete")
            check_icon.setStyleSheet("border: none; font-size: 12px;")
            header.addWidget(check_icon)
        self._title_label = QLabel(column_name)
        self._title_label.setStyleSheet(
            f"color: {colors['text']}; font-weight: bold; font-size: 14px; border: none;"
        )
        header.addWidget(self._title_label)

        self._count_label = QLabel("0")
        self._count_label.setStyleSheet(
            f"color: {colors['completed_text']}; font-size: 12px; border: none;"
        )
        header.addWidget(self._count_label)
        header.addStretch()

        # Column menu button
        menu_btn = QPushButton("\u22ee")  # ⋮
        menu_btn.setFixedSize(24, 24)
        menu_btn.setStyleSheet(
            f"color: {colors['completed_text']}; border: none; "
            "font-size: 16px; background: transparent;"
        )
        menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_btn.clicked.connect(self._show_column_menu)
        header.addWidget(menu_btn)

        col_layout.addLayout(header)

        # Scroll area for cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background: transparent;")
        self._card_container = QWidget()
        self._card_container.setStyleSheet("background: transparent;")
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(4, 2, 4, 2)
        self._card_layout.setSpacing(6)
        self._card_layout.addStretch()
        scroll.setWidget(self._card_container)
        col_layout.addWidget(scroll, 1)

        # Add item button
        add_btn = QPushButton("+ Add item")
        add_btn.setStyleSheet(
            f"color: {colors['completed_text']}; border: none; "
            "text-align: left; padding: 4px; background: transparent; font-size: 12px;"
        )
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(lambda: self.add_item_clicked.emit(self._column_name))
        col_layout.addWidget(add_btn)

    def add_card(self, card: KanbanCardWidget) -> None:
        """Add a card to this column."""
        # Insert before the stretch
        self._card_layout.insertWidget(self._card_layout.count() - 1, card)
        self._cards.append(card)
        # Connect card signals
        card.clicked.connect(self.card_clicked.emit)
        card.double_clicked.connect(self.card_double_clicked.emit)
        card.context_menu_requested.connect(self.card_context_menu.emit)
        card.toggle_requested.connect(self.card_toggle.emit)
        card.edit_tags_requested.connect(self.card_edit_tags.emit)
        self._update_count_display()

    def clear_cards(self) -> None:
        """Remove all cards from this column."""
        for card in self._cards:
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._update_count_display()

    def _update_count_display(self) -> None:
        """Update the count label with WIP limit color coding."""
        count = len(self._cards)
        if self._wip_limit > 0:
            text = f"{count}/{self._wip_limit}"
            if count > self._wip_limit:
                color = self._colors["due_overdue"]  # Red — over limit
            elif count == self._wip_limit:
                color = self._colors["due_today"]  # Amber — at limit
            else:
                color = self._colors["completed_text"]  # Normal
        else:
            text = str(count)
            color = self._colors["completed_text"]
        self._count_label.setText(text)
        self._count_label.setStyleSheet(f"color: {color}; font-size: 12px; border: none;")

    @property
    def column_name(self) -> str:
        return self._column_name

    def _show_column_menu(self) -> None:
        """Show the column header context menu."""
        menu = QMenu(self)

        rename_action = menu.addAction("Rename Column...")
        if rename_action:
            rename_action.triggered.connect(lambda: self.rename_requested.emit(self._column_name))

        # WIP limit only makes sense for middle columns (not inbox or completion)
        if not self._is_first and not self._is_last:
            wip_action = menu.addAction("Set WIP Limit...")
            if wip_action:
                wip_action.triggered.connect(
                    lambda: self.set_wip_limit_requested.emit(self._column_name)
                )

            menu.addSeparator()

            delete_action = menu.addAction("Delete Column")
            if delete_action:
                delete_action.triggered.connect(
                    lambda: self.delete_requested_col.emit(self._column_name)
                )

        menu.exec(self.mapToGlobal(QPoint(COLUMN_WIDTH - 40, 30)))

    # -- Drag-and-drop target --

    def dragEnterEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        mime = a0.mimeData()
        if mime is not None and mime.hasFormat(KANBAN_MIME_TYPE):
            a0.acceptProposedAction()
            self.setStyleSheet(
                self.styleSheet()
                + f"\nKanbanColumnWidget {{ border: 2px dashed {self._colors['highlight']}; }}"
            )
        else:
            a0.ignore()

    def dragLeaveEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None:
            self.setStyleSheet(
                f"""
                KanbanColumnWidget {{
                    background: {self._colors["alternate_base"]};
                    border: 1px solid {self._colors["border"]};
                    border-radius: 8px;
                }}
                """
            )

    def dropEvent(self, a0) -> None:  # noqa: N802
        if a0 is None:
            return
        mime = a0.mimeData()
        if mime is None or not mime.hasFormat(KANBAN_MIME_TYPE):
            a0.ignore()
            return
        raw = mime.data(KANBAN_MIME_TYPE)
        data = raw.data().decode() if raw else ""
        try:
            item_id = UUID(data)
        except ValueError:
            a0.ignore()
            return
        a0.acceptProposedAction()
        # Reset border
        self.setStyleSheet(
            f"""
            KanbanColumnWidget {{
                background: {self._colors["alternate_base"]};
                border: 1px solid {self._colors["border"]};
                border-radius: 8px;
            }}
            """
        )
        self.card_dropped.emit(item_id, self._column_name)


# ---------------------------------------------------------------------------
# KanbanBoardWidget
# ---------------------------------------------------------------------------


class KanbanBoardWidget(QWidget):
    """Kanban board view with columns and cards."""

    # Shared signals (MUST match TodoTableWidget exactly)
    item_priority_changed = pyqtSignal(object, int)
    item_reminder_changed = pyqtSignal(object, str)
    item_due_date_changed = pyqtSignal(object, object)
    item_due_time_changed = pyqtSignal(object, object)
    edit_tags_requested = pyqtSignal(object)
    focus_requested = pyqtSignal(object)
    add_subtask_requested = pyqtSignal(object)
    toggle_requested = pyqtSignal()  # NO ARGS
    delete_requested = pyqtSignal()  # NO ARGS
    edit_recurrence_requested = pyqtSignal()  # NO ARGS

    # Kanban-only signals
    item_column_changed = pyqtSignal(object, str)
    layout_preset_requested = pyqtSignal(object)  # (list[str]) — preset columns
    remove_column_requested = pyqtSignal(str)
    rename_column_requested = pyqtSignal(str, str)
    wip_limit_changed = pyqtSignal(str, int)
    add_item_in_column_requested = pyqtSignal(str)  # (column_name) — new item

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected_item_id: UUID | None = None
        self._todo_list: TodoList | None = None
        self._filter_state: FilterState | None = None
        self._columns: list[KanbanColumnWidget] = []
        self._layout_btn: QPushButton | None = None
        self._dragging = False
        self._refresh_pending = False
        self._focus_col: int = 0
        self._focus_card: int = -1  # -1 = no card focused
        self._focus_session_item_id: UUID | None = None  # Active pomodoro item
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Horizontal scroll area for columns
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none;")
        self._scroll = scroll

        self._board_container = QWidget()
        self._board_layout = QHBoxLayout(self._board_container)
        self._board_layout.setContentsMargins(8, 4, 8, 4)
        self._board_layout.setSpacing(8)
        self._board_layout.addStretch()
        scroll.setWidget(self._board_container)
        outer_layout.addWidget(scroll)

    def set_list(self, todo_list: TodoList | None) -> None:
        """Set the list to display."""
        self._todo_list = todo_list
        self.refresh()

    def set_filter(self, filter_state: FilterState) -> None:
        """Apply a filter."""
        self._filter_state = filter_state
        self.refresh()

    def set_focus_session_item(self, item_id: UUID | None) -> None:
        """Set the item with an active focus session for visual highlighting."""
        if self._focus_session_item_id != item_id:
            self._focus_session_item_id = item_id
            self.refresh()

    def refresh(self) -> None:
        """Rebuild all columns and cards."""
        if self._dragging:
            self._refresh_pending = True
            return

        # Clear existing columns and add-column button
        for col in self._columns:
            self._board_layout.removeWidget(col)
            col.deleteLater()
        self._columns.clear()
        if self._layout_btn is not None:
            self._board_layout.removeWidget(self._layout_btn)
            self._layout_btn.deleteLater()
            self._layout_btn = None

        if self._todo_list is None:
            return

        colors = get_colors()
        time_format = self._get_time_format()
        columns = self._todo_list.board_columns

        # Build children map for subtask data
        children_by_parent: dict[UUID, list[TodoItem]] = {}
        for item in self._todo_list.active_items():
            if item.parent_id is not None:
                children_by_parent.setdefault(item.parent_id, []).append(item)

        # Get top-level items only
        top_items = [item for item in self._todo_list.active_items() if item.parent_id is None]

        # Apply filter
        top_items = self._apply_filter(top_items)

        # Sort items
        sort_tiers = self._get_sort_tiers()
        top_items = self._sort_items(top_items, sort_tiers)

        # Distribute items into columns
        items_by_col: dict[str, list[TodoItem]] = {col: [] for col in columns}
        for item in top_items:
            col = item.board_column
            if col in items_by_col:
                items_by_col[col].append(item)
            elif columns:
                # Item has no/invalid column — put in first column
                items_by_col[columns[0]].append(item)

        # Create column widgets
        for i, col_name in enumerate(columns):
            wip_limit = self._todo_list.get_wip_limit(col_name)
            is_first = i == 0
            is_last = i == len(columns) - 1
            col_widget = KanbanColumnWidget(
                col_name, colors, wip_limit, is_first=is_first, is_last=is_last
            )
            col_widget.card_clicked.connect(self._on_card_clicked)
            col_widget.card_double_clicked.connect(self._on_card_double_clicked)
            col_widget.card_context_menu.connect(self._on_card_context_menu)
            col_widget.card_toggle.connect(self._on_card_toggle)
            col_widget.card_edit_tags.connect(self.edit_tags_requested.emit)
            col_widget.card_dropped.connect(self._on_card_dropped)
            col_widget.add_item_clicked.connect(self._on_add_item_in_column)
            col_widget.rename_requested.connect(self._on_column_rename)
            col_widget.delete_requested_col.connect(self.remove_column_requested.emit)
            col_widget.set_wip_limit_requested.connect(self._on_column_wip_limit)

            for item in items_by_col.get(col_name, []):
                subtasks = children_by_parent.get(item.id, [])
                is_focus_item = item.id == self._focus_session_item_id
                card = KanbanCardWidget(item, colors, time_format, subtasks, is_focus_item)
                col_widget.add_card(card)

            # Insert before the stretch
            self._board_layout.insertWidget(self._board_layout.count() - 1, col_widget)
            self._columns.append(col_widget)

        # "Board Layout" preset button
        self._layout_btn = QPushButton("\u2699 Layout")  # ⚙ Layout
        self._layout_btn.setFixedWidth(100)
        self._layout_btn.setStyleSheet(
            f"color: {colors['completed_text']}; border: 2px dashed {colors['border']}; "
            f"border-radius: 8px; padding: 8px; background: transparent; font-size: 12px;"
        )
        self._layout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._layout_btn.clicked.connect(self._show_layout_menu)
        self._board_layout.insertWidget(
            self._board_layout.count() - 1, self._layout_btn, 0, Qt.AlignmentFlag.AlignTop
        )

    def get_selected_item_ids(self) -> list[UUID]:
        """Return currently selected item IDs."""
        if self._selected_item_id is not None:
            return [self._selected_item_id]
        return []

    # -- Keyboard navigation --

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:  # noqa: N802
        """Handle keyboard navigation."""
        if a0 is None:
            return
        key = a0.key()
        modifiers = a0.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)

        if not self._columns:
            super().keyPressEvent(a0)
            return

        if key == Qt.Key.Key_Left:
            if ctrl:
                self._move_card_to_adjacent(-1)
            else:
                self._move_focus_column(-1)
        elif key == Qt.Key.Key_Right:
            if ctrl:
                self._move_card_to_adjacent(1)
            else:
                self._move_focus_column(1)
        elif key == Qt.Key.Key_Up:
            self._move_focus_card(-1)
        elif key == Qt.Key.Key_Down:
            self._move_focus_card(1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._select_focused_card()
        elif key == Qt.Key.Key_Space:
            self._toggle_focused_card()
        elif key == Qt.Key.Key_Delete or key == Qt.Key.Key_Backspace:
            self._delete_focused_card()
        elif key == Qt.Key.Key_N or key == Qt.Key.Key_Plus:
            self._add_item_to_focused_column()
        else:
            super().keyPressEvent(a0)
            return
        a0.accept()

    def _move_focus_column(self, direction: int) -> None:
        """Move focus to adjacent column."""
        if not self._columns:
            return
        new_col = self._focus_col + direction
        if 0 <= new_col < len(self._columns):
            self._focus_col = new_col
            # Clamp card index to new column's card count
            card_count = len(self._columns[new_col]._cards)
            if card_count == 0:
                self._focus_card = -1
            elif self._focus_card >= card_count:
                self._focus_card = card_count - 1
            elif self._focus_card < 0 and card_count > 0:
                self._focus_card = 0
            self._update_focus_highlight()

    def _move_focus_card(self, direction: int) -> None:
        """Move focus to adjacent card within current column."""
        if not self._columns:
            return
        col = self._columns[self._focus_col]
        card_count = len(col._cards)
        if card_count == 0:
            return
        new_card = self._focus_card + direction
        if new_card < 0:
            new_card = 0
        elif new_card >= card_count:
            new_card = card_count - 1
        self._focus_card = new_card
        self._update_focus_highlight()

    def _select_focused_card(self) -> None:
        """Select the focused card (Enter key)."""
        card = self._get_focused_card()
        if card:
            self._selected_item_id = card._item_id
            self._update_selection_highlight()
            self._update_focus_highlight()

    def _toggle_focused_card(self) -> None:
        """Toggle focused card (Space key)."""
        card = self._get_focused_card()
        if card:
            self._selected_item_id = card._item_id
            self.toggle_requested.emit()

    def _delete_focused_card(self) -> None:
        """Delete focused card (Delete key)."""
        card = self._get_focused_card()
        if card:
            self._selected_item_id = card._item_id
            self.delete_requested.emit()

    def _add_item_to_focused_column(self) -> None:
        """Add item to focused column (N or + key)."""
        if self._columns:
            col_name = self._columns[self._focus_col].column_name
            self.add_item_in_column_requested.emit(col_name)

    def _move_card_to_adjacent(self, direction: int) -> None:
        """Move focused card to adjacent column (Ctrl+Left/Right)."""
        card = self._get_focused_card()
        if not card or not self._columns:
            return
        target_col = self._focus_col + direction
        if 0 <= target_col < len(self._columns):
            target_name = self._columns[target_col].column_name
            self.item_column_changed.emit(card._item_id, target_name)

    def _get_focused_card(self) -> KanbanCardWidget | None:
        """Get the currently focused card widget, or None."""
        if not self._columns or self._focus_col >= len(self._columns):
            return None
        col = self._columns[self._focus_col]
        if 0 <= self._focus_card < len(col._cards):
            return col._cards[self._focus_card]
        return None

    def _update_focus_highlight(self) -> None:
        """Update visual focus indicator on cards."""
        for col_idx, col in enumerate(self._columns):
            for card_idx, card in enumerate(col._cards):
                if col_idx == self._focus_col and card_idx == self._focus_card:
                    # Focused card gets a dotted outline
                    colors = self._get_colors_cached()
                    card.setProperty("kanban_focused", True)
                    # Update existing style — add focus border
                    current = card.styleSheet()
                    if "outline:" not in current:
                        card.setStyleSheet(
                            current.rstrip().rstrip("}")
                            + f"\n  outline: 2px dotted {colors['highlight']};\n}}"
                        )
                else:
                    if card.property("kanban_focused"):
                        card.setProperty("kanban_focused", False)
                        # Remove focus outline by re-triggering style
                        style = card.styleSheet()
                        # Remove outline line
                        lines = [ln for ln in style.split("\n") if "outline:" not in ln]
                        card.setStyleSheet("\n".join(lines))
        # Ensure focused card is visible (auto-scroll)
        card = self._get_focused_card()
        if card:
            card.ensurePolished()
            # Scroll column into view
            if self._columns and self._focus_col < len(self._columns):
                col_widget = self._columns[self._focus_col]
                self._scroll.ensureWidgetVisible(col_widget)

    def _update_selection_highlight(self) -> None:
        """Update visual selection border on cards."""
        for col in self._columns:
            for card in col._cards:
                card.set_selected(card._item_id == self._selected_item_id)

    def _get_colors_cached(self) -> dict[str, str]:
        """Get colors (cached from last refresh)."""
        return get_colors()

    # -- Signal bridge methods (THE critical safety mechanism) --

    def _on_card_clicked(self, item_id: object) -> None:
        """Handle card click — select it and highlight."""
        if isinstance(item_id, UUID):
            self._selected_item_id = item_id
            self._update_selection_highlight()

    def _on_card_toggle(self, item_id: object) -> None:
        """Bridge: card checkbox → select + emit no-args toggle."""
        if isinstance(item_id, UUID):
            self._selected_item_id = item_id
            self.toggle_requested.emit()

    def _on_card_double_clicked(self, item_id: object) -> None:
        """Bridge: double-click → open edit reminder dialog."""
        if not isinstance(item_id, UUID) or self._todo_list is None:
            return
        item = self._todo_list.get_item(item_id)
        if not item:
            return
        text, ok = QInputDialog.getText(self, "Edit Reminder", "Reminder:", text=item.reminder)
        if ok and text != item.reminder:
            self.item_reminder_changed.emit(item_id, text)

    def _on_card_context_menu(self, item_id: object, pos: QPoint) -> None:
        """Show context menu for a card."""
        if not isinstance(item_id, UUID) or self._todo_list is None:
            return
        item = self._todo_list.get_item(item_id)
        if not item:
            return

        menu = QMenu(self)

        # Set Priority submenu
        priority_menu = menu.addMenu("Set Priority")
        if priority_menu:
            priority_labels = {1: "High", 2: "Normal", 3: "Low"}
            for pval, plabel in priority_labels.items():
                prefix = "\u2713 " if item.priority == pval else "   "
                p_action = priority_menu.addAction(f"{prefix}{plabel}")
                if p_action:
                    p_action.triggered.connect(
                        lambda _, p=pval: self.item_priority_changed.emit(item_id, p)
                    )

        # Edit Reminder
        edit_action = menu.addAction("Edit Reminder...")
        if edit_action:
            edit_action.triggered.connect(lambda: self._edit_reminder_for(item_id))

        # Edit Tags
        tags_action = menu.addAction("Edit Tags...")
        if tags_action:
            tags_action.triggered.connect(lambda: self.edit_tags_requested.emit(item_id))

        # Edit Due Date
        due_action = menu.addAction("Edit Due Date...")
        if due_action:
            due_action.triggered.connect(lambda: self._edit_due_date_for(item_id))

        # Edit Recurrence
        rec_action = menu.addAction("Edit Recurrence...")
        if rec_action:
            rec_action.triggered.connect(lambda: self._bridge_recurrence(item_id))

        # Start Focus
        focus_action = menu.addAction("Start Focus Session")
        if focus_action:
            focus_action.triggered.connect(lambda: self.focus_requested.emit(item_id))

        # Add Subtask (top-level only)
        if item.parent_id is None:
            sub_action = menu.addAction("Add Subtask...")
            if sub_action:
                sub_action.triggered.connect(lambda: self.add_subtask_requested.emit(item_id))

        menu.addSeparator()

        # Move to Column submenu
        columns = self._todo_list.board_columns if self._todo_list else []
        if len(columns) > 1:
            move_menu = menu.addMenu("Move to Column")
            if move_menu:
                for col in columns:
                    if col != item.board_column:
                        col_action = move_menu.addAction(col)
                        if col_action:
                            col_name = col  # capture
                            col_action.triggered.connect(
                                lambda _, c=col_name: self.item_column_changed.emit(item_id, c)
                            )

        menu.addSeparator()

        # Toggle Complete
        toggle_text = "Mark Incomplete" if item.complete else "Mark Complete"
        toggle_action = menu.addAction(toggle_text)
        if toggle_action:
            toggle_action.triggered.connect(lambda: self._bridge_toggle(item_id))

        # Delete
        del_action = menu.addAction("Delete")
        if del_action:
            del_action.triggered.connect(lambda: self._bridge_delete(item_id))

        menu.exec(pos)

    def _edit_reminder_for(self, item_id: UUID) -> None:
        """Show edit reminder dialog for a specific item."""
        if self._todo_list is None:
            return
        item = self._todo_list.get_item(item_id)
        if not item:
            return
        text, ok = QInputDialog.getText(self, "Edit Reminder", "Reminder:", text=item.reminder)
        if ok and text != item.reminder:
            self.item_reminder_changed.emit(item_id, text)

    def _edit_due_date_for(self, item_id: UUID) -> None:
        """Show due date picker dialog for a specific item."""
        if self._todo_list is None:
            return
        item = self._todo_list.get_item(item_id)
        if not item:
            return
        from .todo_table import DueDatePickerDialog

        dialog = DueDatePickerDialog(item.due_date, item.due_time, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            new_date = dialog.get_date()
            new_time = dialog.get_time()
            if new_date != item.due_date:
                self.item_due_date_changed.emit(item_id, new_date)
            if new_time != item.due_time:
                self.item_due_time_changed.emit(item_id, new_time)

    def _bridge_toggle(self, item_id: UUID) -> None:
        """Bridge: select + emit no-args toggle."""
        self._selected_item_id = item_id
        self.toggle_requested.emit()

    def _bridge_delete(self, item_id: UUID) -> None:
        """Bridge: select + emit no-args delete."""
        self._selected_item_id = item_id
        self.delete_requested.emit()

    def _bridge_recurrence(self, item_id: UUID) -> None:
        """Bridge: select + emit no-args edit_recurrence."""
        self._selected_item_id = item_id
        self.edit_recurrence_requested.emit()

    def _on_card_dropped(self, item_id: object, column_name: str) -> None:
        """Handle card dropped onto a column."""
        if isinstance(item_id, UUID):
            self.item_column_changed.emit(item_id, column_name)

    def _on_add_item_in_column(self, column_name: str) -> None:
        """Handle '+ Add item' click in a column."""
        self.add_item_in_column_requested.emit(column_name)

    def _show_layout_menu(self) -> None:
        """Show board layout preset menu."""
        menu = QMenu(self)

        # Determine current layout for checkmark
        current = self._todo_list.board_columns if self._todo_list else []

        arrow = " \u2192 "
        for preset_name, preset_cols in BOARD_PRESETS.items():
            prefix = "\u2713 " if current == preset_cols else "   "
            cols_text = arrow.join(preset_cols)
            action = menu.addAction(f"{prefix}{preset_name}  ({cols_text})")
            if action:
                cols = list(preset_cols)  # capture
                action.triggered.connect(lambda _, c=cols: self.layout_preset_requested.emit(c))

        if self._layout_btn:
            menu.exec(self._layout_btn.mapToGlobal(QPoint(0, self._layout_btn.height())))

    def _on_column_rename(self, column_name: str) -> None:
        """Handle column rename request — prompt for new name."""
        new_name, ok = QInputDialog.getText(self, "Rename Column", "New name:", text=column_name)
        if not ok or not new_name.strip() or new_name == column_name:
            return
        new_name = new_name.strip()
        if len(new_name) > 50:
            new_name = new_name[:50]
        if self._todo_list and new_name in self._todo_list.board_columns:
            return
        self.rename_column_requested.emit(column_name, new_name)

    def _on_column_wip_limit(self, column_name: str) -> None:
        """Handle WIP limit request — prompt for limit value."""
        current = 0
        if self._todo_list:
            current = self._todo_list.get_wip_limit(column_name)
        limit, ok = QInputDialog.getInt(
            self,
            "WIP Limit",
            f"WIP limit for '{column_name}' (0 = no limit):",
            current,
            0,
            99,
        )
        if ok:
            self.wip_limit_changed.emit(column_name, limit)

    # -- Internal helpers --

    def _get_time_format(self) -> str:
        """Get time format from config."""
        try:
            from ...core.config import get_config

            return get_config().appearance.time_format
        except Exception:
            return "system"

    def _get_sort_tiers(self) -> list[tuple[str, bool]]:
        """Get sort tiers from config."""
        try:
            from ...core.config import get_config

            return get_config().database.sort_tiers()
        except Exception:
            return [("completion", False), ("due_date", False), ("priority", False)]

    def _sort_items(
        self, items: list[TodoItem], sort_tiers: list[tuple[str, bool]]
    ) -> list[TodoItem]:
        """Sort items using the same multi-tier sort as the table view."""

        def sort_key(item: TodoItem) -> tuple:
            key: list = []
            for dimension, reverse in sort_tiers:
                key.extend(_sort_fragment(item, dimension, reverse))
            key.append(item.reminder.lower())
            return tuple(key)

        with contextlib.suppress(Exception):
            items.sort(key=sort_key)
        return items

    def _apply_filter(self, items: list[TodoItem]) -> list[TodoItem]:
        """Apply filter predicates (same logic as TodoTableWidget)."""
        if self._filter_state is None:
            return items

        filtered = list(items)

        # Text search
        search = getattr(self._filter_state, "text", "").lower()
        if search:
            filtered = [
                i
                for i in filtered
                if search in i.reminder.lower() or any(search in tag.lower() for tag in i.tags)
            ]

        # Priority (0 = no filter)
        priority = getattr(self._filter_state, "priority", 0)
        if priority:
            filtered = [i for i in filtered if i.priority == priority]

        # Status (0=all, 1=incomplete, 2=complete)
        status = getattr(self._filter_state, "status", 0)
        if status == 1:
            filtered = [i for i in filtered if not i.complete]
        elif status == 2:
            filtered = [i for i in filtered if i.complete]

        # Due date (0=all, 1=overdue, 2=today, 3=this week, 4=no date, 5=recurring)
        due_filter = getattr(self._filter_state, "due_date", 0)
        if due_filter == 1:
            filtered = [i for i in filtered if _is_overdue(i.due_date, i.due_time)]
        elif due_filter == 2:
            filtered = [i for i in filtered if i.due_date == date.today()]
        elif due_filter == 3:
            from datetime import timedelta

            today = date.today()
            week_end = today + timedelta(days=7)
            filtered = [i for i in filtered if i.due_date is not None and i.due_date <= week_end]
        elif due_filter == 4:
            filtered = [i for i in filtered if i.due_date is None]
        elif due_filter == 5:
            filtered = [i for i in filtered if i.is_recurring]

        # Tag filter
        tag = getattr(self._filter_state, "tag", "")
        if tag:
            filtered = [i for i in filtered if tag in i.tags]

        return filtered
