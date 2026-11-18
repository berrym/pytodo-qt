"""todo_table.py

Table widget for displaying and editing to-do items.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from PyQt6.QtCore import QDate, QEvent, QItemSelection, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.logger import Logger
from ...core.models import (
    TodoItem,
    TodoList,
    format_due_date,
    is_due_this_week,
    is_due_today,
    is_overdue,
)
from ..styles.themes import get_colors, make_font
from .time_combo import TimeComboBox

if TYPE_CHECKING:
    from .search_filter import FilterState


logger = Logger(__name__)

# How often a refresh that is waiting for a row to be free looks again.
_HELD_REFRESH_POLL_MS = 200


def _sort_fragment(item: TodoItem, dimension: str, reverse: bool) -> tuple:
    """Return a comparable tuple fragment for one sort dimension."""
    if dimension == "completion":
        val = 1 if item.complete else 0
        return (-val,) if reverse else (val,)
    elif dimension == "due_date":
        if item.due_date is None:
            return (1, 0, 0)
        date_ord = item.due_date.toordinal()
        time_secs = (
            item.due_time.hour * 3600 + item.due_time.minute * 60 + item.due_time.second
            if item.due_time
            else -1
        )
        return (0, -date_ord, -time_secs) if reverse else (0, date_ord, time_secs)
    elif dimension == "priority":
        val = item.priority
        return (-val,) if reverse else (val,)
    return ()


def _in_one_colour(pixmap: QPixmap, color: str) -> QPixmap:
    """The shape of a pixmap, drawn in one colour."""
    drawn = QPixmap(pixmap.size())
    drawn.setDevicePixelRatio(pixmap.devicePixelRatio())
    drawn.fill(Qt.GlobalColor.transparent)
    painter = QPainter(drawn)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(drawn.rect(), QColor(color))
    painter.end()
    return drawn


def _with_color(style: str, color: str) -> str:
    """A label's style with its text colour replaced."""
    return f"{style} color: {color};"


class ClickableLabel(QLabel):
    """QLabel that emits a clicked signal on mouse press."""

    clicked = pyqtSignal()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        self.clicked.emit()


class ReminderEdit(QLineEdit):
    """The name field of a row.

    It knows the task it belongs to and the name that is stored for it,
    so that text typed and not yet saved can be told from the stored
    name. Escape puts the stored name back.
    """

    def __init__(self, item_id: UUID, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.item_id = item_id
        self.stored_text = text

    def has_unsaved_text(self) -> bool:
        return not self.isReadOnly() and self.text() != self.stored_text

    def restore_stored_text(self) -> None:
        """Put the stored name back, the cursor staying where it is."""
        position = min(self.cursorPosition(), len(self.stored_text))
        self.setText(self.stored_text)
        self.setCursorPosition(position)

    def event(self, a0) -> bool:
        # The window has a shortcut on Escape, and a shortcut is asked
        # for before the key reaches the field. With unsaved text the
        # field claims the key for itself.
        if (
            isinstance(a0, QKeyEvent)
            and a0.type() == QEvent.Type.ShortcutOverride
            and a0.key() == Qt.Key.Key_Escape
            and self.has_unsaved_text()
        ):
            a0.accept()
            return True
        return super().event(a0)

    def keyPressEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.key() == Qt.Key.Key_Escape and self.has_unsaved_text():
            self.restore_stored_text()
            a0.accept()
            return
        super().keyPressEvent(a0)


@dataclass
class _ViewState:
    """What a rebuild of the table has to put back."""

    # The task in the row at the top of the view, that row's number, and
    # how far the row is scrolled out of the view, in pixels.
    top_id: UUID | None = None
    top_row: int = -1
    top_offset: int = 0
    horizontal: int = 0
    selected: list[UUID] = field(default_factory=list)
    current: tuple[UUID, int] | None = None
    # The cell whose widget has the keyboard focus: (task, column).
    focus: tuple[UUID, int] | None = None
    # The table itself has the keyboard focus.
    table_focused: bool = False
    focus_row_visible: bool = False
    # Text typed into the focused name field and not yet saved.
    unsaved_text: str | None = None
    cursor: int = 0
    selection_start: int = -1
    selection_length: int = 0


class DueDatePickerDialog(QDialog):
    """Dialog for picking or clearing a due date and optional time."""

    def __init__(
        self,
        current_date: date | None,
        current_time: time | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Set Due Date"))
        self._date = current_date
        self._time = current_time
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Date picker
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        if self._date:
            self.date_edit.setDate(QDate(self._date.year, self._date.month, self._date.day))
        else:
            self.date_edit.setDate(QDate.currentDate())
        layout.addWidget(self.date_edit)

        # Time picker with checkbox
        time_layout = QHBoxLayout()
        self.time_checkbox = QCheckBox(self.tr("Set due time"))
        self.time_checkbox.stateChanged.connect(self._on_time_toggled)
        time_layout.addWidget(self.time_checkbox)

        self.time_edit = TimeComboBox()
        self.time_edit.setEnabled(False)
        if self._time:
            self.time_edit.set_time(self._time)
            self.time_checkbox.setChecked(True)
        else:
            self.time_edit.default_to_next_hour()
        time_layout.addWidget(self.time_edit, 1)
        layout.addLayout(time_layout)

        # Buttons
        btn_layout = QHBoxLayout()

        clear_btn = QPushButton(self.tr("Clear"))
        clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()

        cancel_btn = QPushButton(self.tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton(self.tr("OK"))
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _on_time_toggled(self, state: int) -> None:
        self.time_edit.setEnabled(state == Qt.CheckState.Checked.value)

    def _on_ok(self) -> None:
        qdate = self.date_edit.date()
        self._date = date(qdate.year(), qdate.month(), qdate.day())
        if self.time_checkbox.isChecked():
            self._time = self.time_edit.get_time()
        else:
            self._time = None
        self.accept()

    def _on_clear(self) -> None:
        self._date = None
        self._time = None
        self.accept()

    def get_date(self) -> date | None:
        return self._date

    def get_time(self) -> time | None:
        return self._time


class DueDateLabel(QWidget):
    """Clickable due date label that opens date picker on click."""

    date_changed = pyqtSignal(object)  # Emits date or None
    time_changed = pyqtSignal(object)  # Emits time or None

    def __init__(
        self,
        due_date: date | None,
        complete: bool = False,
        recurring: bool = False,
        due_time: time | None = None,
        time_format: str = "system",
        due_time_end: time | None = None,
        due_time_block: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._due_date = due_date
        self._due_time = due_time
        self._due_time_end = due_time_end
        self._due_time_block = due_time_block
        self._complete = complete
        self._recurring = recurring
        self._time_format = time_format
        self._icon_label: QLabel | None = None
        self._icon_pixmap: QPixmap | None = None
        self._text_style = ""
        self._setup_ui()

    def set_text_style(self, style: str) -> None:
        """The style of the text on an ordinary row."""
        self._text_style = style
        self.label.setStyleSheet(style)

    def set_on_highlight(self, color: str | None) -> None:
        """Draw the text and the icon for a row filled with the highlight
        colour, in the colour given, or for an ordinary row (None)."""
        if color is None:
            self.label.setStyleSheet(self._text_style)
        else:
            self.label.setStyleSheet(_with_color(self._text_style, color))
        if self._icon_label is None or self._icon_pixmap is None:
            return
        if color is None:
            self._icon_label.setPixmap(self._icon_pixmap)
        else:
            self._icon_label.setPixmap(_in_one_colour(self._icon_pixmap, color))

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)

        # Center icon + label as a group within the cell
        layout.addStretch()

        if self._recurring:
            icon_path = Path(__file__).parent.parent / "icons" / "repeat.svg"
            if icon_path.exists():
                icon_label = QLabel()
                pixmap = QPixmap(str(icon_path)).scaled(
                    14,
                    14,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                # The icon's own blue is one colour for both themes and
                # every row background. It is drawn in the accent colour,
                # and in the muted text colour on a finished task.
                colors = get_colors()
                pixmap = _in_one_colour(
                    pixmap, colors["completed_text" if self._complete else "highlight"]
                )
                icon_label.setPixmap(pixmap)
                self._icon_label = icon_label
                self._icon_pixmap = pixmap
                layout.addWidget(icon_label)

        self.label = QLabel(
            format_due_date(
                self._due_date,
                self._complete,
                self._due_time,
                self._time_format,
                self._due_time_end,
                self._due_time_block,
            )
        )
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.label)

        layout.addStretch()

        # Ensure the widget itself reports enough width for time-inclusive strings
        self.setMinimumWidth(180)

    def mousePressEvent(self, a0) -> None:  # noqa: N802
        if a0 is not None and a0.button() == Qt.MouseButton.RightButton:
            # Let right-click propagate to parent table for context menu
            a0.ignore()
            return
        self._show_date_picker()

    def _show_date_picker(self) -> None:
        """Show date/time picker dialog."""
        dialog = DueDatePickerDialog(self._due_date, self._due_time, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_date = dialog.get_date()
            new_time = dialog.get_time()
            old_date = self._due_date
            old_time = self._due_time
            self._due_date = new_date
            self._due_time = new_time
            self.label.setText(
                format_due_date(
                    self._due_date,
                    self._complete,
                    self._due_time,
                    self._time_format,
                    self._due_time_end,
                    self._due_time_block,
                )
            )
            if new_date != old_date:
                self.date_changed.emit(self._due_date)
            if new_time != old_time:
                self.time_changed.emit(self._due_time)


class TodoTableWidget(QTableWidget):
    """Table widget for displaying and editing to-do items."""

    # Signals
    item_priority_changed = pyqtSignal(object, int)  # (item_id, new_priority)
    item_reminder_changed = pyqtSignal(object, str)  # (item_id, new_text)
    item_due_date_changed = pyqtSignal(object, object)  # (item_id, new_date or None)
    item_due_time_changed = pyqtSignal(object, object)  # (item_id, new_time or None)
    item_selected = pyqtSignal(object)  # (item_id or None)
    edit_tags_requested = pyqtSignal(object)  # (item_id)
    toggle_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    edit_recurrence_requested = pyqtSignal()
    focus_requested = pyqtSignal(object)  # (item_id)
    add_subtask_requested = pyqtSignal(object)  # (parent_id)
    set_time_block_requested = pyqtSignal(object)  # (item_id)
    set_event_date_requested = pyqtSignal(object)  # (item_id)
    # Empty-state action signals — wired by MainWindow to the same
    # handlers the kanban view uses, so the two views offer identical
    # exit paths from a zero-rows state.
    add_task_requested = pyqtSignal()
    clear_filters_requested = pyqtSignal()
    show_completed_requested = pyqtSignal()
    create_list_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_list: TodoList | None = None
        self._item_id_map: dict[int, UUID] = {}  # row -> item_id
        self._filter_state: FilterState | None = None
        self._v_header_filter_installed = False
        self._ellipsis_pairs: list[tuple[QLineEdit, ClickableLabel]] = []
        self._collapsed_parents: set[UUID] = set()
        self._context_row_ids: set[UUID] = set()

        # True while the rows are being made again: a name field that
        # loses the focus because it is being replaced saves nothing.
        self._rebuilding = False
        # A refresh that arrived while a row was in use, and is waiting.
        self._refresh_held = False
        self._held_background = False
        self._held_timer = QTimer(self)
        self._held_timer.setInterval(_HELD_REFRESH_POLL_MS)
        self._held_timer.timeout.connect(self._run_held_refresh)
        # Names to save once the event that ended their editing is over.
        self._names_to_save: list[tuple[UUID, str]] = []

        # What a row writes and draws straight on its own background, to
        # be recoloured when the row is selected and filled with the
        # highlight colour: labels and tag chips with the style they
        # have on an ordinary row, icons with their pixmap.
        self._row_labels: dict[int, list[tuple[QLabel, str]]] = {}
        self._row_chips: dict[int, list[tuple[QLabel, str]]] = {}
        self._row_icons: dict[int, list[tuple[QLabel, QPixmap]]] = {}
        self._rows_drawn_selected: set[int] = set()

        # Setup table
        self._setup_table()

        # Fonts
        self._normal_font = make_font(12)
        self._completed_font = make_font(12)
        self._completed_font.setBold(True)
        self._completed_font.setStrikeOut(True)

        # Empty-state overlay — child of the viewport so it stacks
        # above the table cells (a child of self would render behind
        # the QTableWidget's internal viewport). Three cases distinguish
        # "no items yet" (offer Add task) from "all complete and the
        # filter hides them" (offer Show completed) from "filter is
        # active and matches nothing" (offer Clear filters).
        _vp = self.viewport()
        self._empty_state = QFrame(_vp if _vp is not None else self)
        self._empty_state.setFrameShape(QFrame.Shape.StyledPanel)
        self._empty_state_label = QLabel("", self._empty_state)
        self._empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_state_label.setWordWrap(True)
        self._empty_state_button = QPushButton("", self._empty_state)
        self._empty_state_button.setCursor(Qt.CursorShape.PointingHandCursor)
        _es_layout = QVBoxLayout(self._empty_state)
        _es_layout.setContentsMargins(28, 22, 28, 22)
        _es_layout.setSpacing(14)
        _es_layout.addWidget(self._empty_state_label)
        _es_layout.addWidget(self._empty_state_button, 0, Qt.AlignmentFlag.AlignCenter)
        self._empty_state.hide()
        self._empty_state_action: str = ""
        self._empty_state_button.clicked.connect(self._on_empty_state_button)

    def _setup_table(self) -> None:
        """Configure the table widget."""
        # Columns: Priority, Reminder, Due
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels([self.tr("Priority"), self.tr("Reminder"), self.tr("Due")])

        # Configure column sizes
        header = self.horizontalHeader()
        if header:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            # Set minimum width for Due column to fit "Overdue (99d)" or day names
            header.setMinimumSectionSize(80)
            self.setColumnWidth(2, 130)
            header.sectionResized.connect(self._update_ellipsis_visibility)

        # Set row height so text is readable
        v_header = self.verticalHeader()
        if v_header:
            v_header.setDefaultSectionSize(42)

        # Corner button: toggle select-all / deselect-all
        corner = self.findChild(QAbstractButton)
        if corner:
            corner.clicked.disconnect()
            corner.clicked.connect(self._on_corner_clicked)

        # Selection behavior
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Alternating row colors
        self.setAlternatingRowColors(True)

        # Connect selection changed
        self.itemSelectionChanged.connect(self._on_selection_changed)

        # Context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def _on_context_menu(self, pos: QPoint) -> None:
        """Show context menu for the table."""
        item_ids = self.get_selected_item_ids()
        if not item_ids:
            return

        menu = QMenu(self)

        if len(item_ids) == 1:
            # Join meeting — only when the single selected row's
            # reminder contains a recognized video-conference URL.
            # Sits at the top of the menu for fast reach during a
            # meeting block, mirroring the calendar bar's pattern so
            # users encounter the same affordance shape across surfaces.
            item = self._current_list.get_item(item_ids[0]) if self._current_list else None
            if item is not None:
                from ...core.meeting_link import detect_meeting_link

                meeting = detect_meeting_link(item.reminder)
                if meeting is not None:
                    join_action = QAction(
                        self.tr("Join {provider} meeting").format(provider=meeting.provider),
                        self,
                    )

                    def _open_join(_checked=False, url=meeting.url):
                        from PyQt6.QtCore import QUrl
                        from PyQt6.QtGui import QDesktopServices

                        QDesktopServices.openUrl(QUrl(url))

                    join_action.triggered.connect(_open_join)
                    menu.addAction(join_action)
                    menu.addSeparator()

            edit_tags_action = QAction(self.tr("Edit Tags..."), self)
            edit_tags_action.triggered.connect(lambda: self.edit_tags_requested.emit(item_ids[0]))
            menu.addAction(edit_tags_action)

            edit_rec_action = QAction(self.tr("Edit Recurrence..."), self)
            edit_rec_action.triggered.connect(self.edit_recurrence_requested.emit)
            menu.addAction(edit_rec_action)

            time_block_action = QAction(self.tr("Set Time Block..."), self)
            time_block_action.triggered.connect(
                lambda checked=False, iid=item_ids[0]: self.set_time_block_requested.emit(iid)
            )
            menu.addAction(time_block_action)

            event_date_action = QAction(self.tr("Set Event Date..."), self)
            event_date_action.triggered.connect(
                lambda checked=False, iid=item_ids[0]: self.set_event_date_requested.emit(iid)
            )
            menu.addAction(event_date_action)

            focus_action = QAction(self.tr("Start Focus Session"), self)
            focus_action.triggered.connect(
                lambda checked=False, iid=item_ids[0]: self.focus_requested.emit(iid)
            )
            menu.addAction(focus_action)

            # Only allow adding subtasks to top-level items
            item = self._current_list.get_item(item_ids[0]) if self._current_list else None
            if item and item.parent_id is None:
                add_subtask_action = QAction(self.tr("Add Subtask..."), self)
                add_subtask_action.triggered.connect(
                    lambda checked=False, iid=item_ids[0]: self.add_subtask_requested.emit(iid)
                )
                menu.addAction(add_subtask_action)

            menu.addSeparator()

        toggle_action = QAction(self.tr("Toggle Complete"), self)
        toggle_action.triggered.connect(self.toggle_requested.emit)
        menu.addAction(toggle_action)

        delete_action = QAction(self.tr("Delete"), self)
        delete_action.triggered.connect(self.delete_requested.emit)
        menu.addAction(delete_action)

        viewport = self.viewport()
        assert viewport is not None
        menu.exec(viewport.mapToGlobal(pos))

    def showEvent(self, a0) -> None:  # noqa: N802
        """Install header viewport event filter on first show."""
        super().showEvent(a0)
        if not self._v_header_filter_installed:
            v_header = self.verticalHeader()
            if v_header:
                vp = v_header.viewport()
                if vp:
                    vp.installEventFilter(self)
                    self._v_header_filter_installed = True

    def resizeEvent(self, e) -> None:  # noqa: N802
        """Update ellipsis visibility when table resizes (e.g. scrollbar
        appears) and reposition the empty-state overlay so it stays
        centered on viewport changes."""
        super().resizeEvent(e)
        if self._ellipsis_pairs:
            self._update_ellipsis_visibility()
        if self._empty_state.isVisible():
            self._position_empty_state()

    def _on_corner_clicked(self) -> None:
        """Toggle between select-all and deselect-all."""
        sm = self.selectionModel()
        if sm and len(sm.selectedRows()) == self.rowCount():
            self.clearSelection()
        else:
            self.selectAll()

    def eventFilter(self, object, event):  # noqa: N802, A002
        """Toggle row selection when vertical header is clicked."""
        v_header = self.verticalHeader()
        if (
            v_header
            and object is v_header.viewport()
            and isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            row = v_header.logicalIndexAt(event.position().toPoint())
            sm = self.selectionModel()
            m = self.model()
            if row >= 0 and sm and m:
                if sm.isRowSelected(row):
                    sm.select(
                        m.index(row, 0),
                        sm.SelectionFlag.Deselect | sm.SelectionFlag.Rows,
                    )
                else:
                    sm.select(
                        m.index(row, 0),
                        sm.SelectionFlag.Select | sm.SelectionFlag.Rows,
                    )
                return True
        return super().eventFilter(object, event)

    def set_list(self, todo_list: TodoList | None, *, background: bool = False) -> None:
        """Set the list to display.

        ``background`` is for a refresh that nothing done in the window
        asked for: the minute tick, a sync, a change from the web page.
        Such a refresh waits while a name is being typed.
        """
        previous = self._current_list
        same_list = previous is not None and todo_list is not None and previous.id == todo_list.id
        self._current_list = todo_list
        if same_list:
            self.refresh(background=background)
        else:
            # Another list: it is shown from its top, with nothing selected.
            self._release_held_refresh()
            self._rebuild_keeping(None)

    def set_filter(self, filter_state: FilterState | None) -> None:
        """Set the current filter and refresh display."""
        self._filter_state = filter_state
        self.refresh()

    def _apply_filter(self, items: list) -> list:
        """Filter items based on current filter state.

        When a child matches but its parent doesn't, the parent is added as a
        context row (muted styling, read-only) so the hierarchy remains visible.
        """
        if self._filter_state is None:
            return items
        filtered = items
        if self._filter_state.text:
            search = self._filter_state.text.lower()
            filtered = [
                i
                for i in filtered
                if search in i.reminder.lower() or any(search in tag.lower() for tag in i.tags)
            ]
        if self._filter_state.priority != 0:
            filtered = [i for i in filtered if i.priority == self._filter_state.priority]
        if self._filter_state.status == 1:
            filtered = [i for i in filtered if not i.complete]
        elif self._filter_state.status == 2:
            filtered = [i for i in filtered if i.complete]
        # Due date filters
        if self._filter_state.due_date == 1:  # Overdue
            filtered = [i for i in filtered if is_overdue(i.due_date, i.due_time)]
        elif self._filter_state.due_date == 2:  # Today
            filtered = [i for i in filtered if is_due_today(i.due_date)]
        elif self._filter_state.due_date == 3:  # This Week
            filtered = [i for i in filtered if is_due_this_week(i.due_date)]
        elif self._filter_state.due_date == 4:  # No Due Date
            filtered = [i for i in filtered if i.due_date is None]
        elif self._filter_state.due_date == 5:  # Recurring
            filtered = [i for i in filtered if i.is_recurring]
        # Tag filter
        if self._filter_state.tag:
            filtered = [i for i in filtered if self._filter_state.tag in i.tags]

        # Pull in parent context rows for children whose parents aren't in results
        filtered_ids = {i.id for i in filtered}
        items_by_id = {i.id: i for i in items}
        self._context_row_ids.clear()
        parents_to_add: list[TodoItem] = []
        for item in filtered:
            if item.parent_id and item.parent_id not in filtered_ids:
                parent = items_by_id.get(item.parent_id)
                if parent and parent.id not in self._context_row_ids:
                    self._context_row_ids.add(parent.id)
                    parents_to_add.append(parent)
                    filtered_ids.add(parent.id)
        filtered.extend(parents_to_add)
        return filtered

    def _build_display_order(self, items: list[TodoItem], sort_key) -> list[tuple[TodoItem, bool]]:
        """Build hierarchical display order: parents followed by their children.

        Returns list of (item, is_child) tuples.
        """
        active_ids = {i.id for i in items}
        top_level: list[TodoItem] = []
        children_by_parent: dict[UUID, list[TodoItem]] = {}

        for item in items:
            if item.parent_id is None or item.parent_id not in active_ids:
                # Top-level item or orphan (parent deleted/filtered)
                top_level.append(item)
            else:
                children_by_parent.setdefault(item.parent_id, []).append(item)

        # Sort top-level items
        with contextlib.suppress(Exception):
            top_level.sort(key=sort_key)

        # Sort children within each group
        for children in children_by_parent.values():
            with contextlib.suppress(Exception):
                children.sort(key=sort_key)

        result: list[tuple[TodoItem, bool]] = []
        for item in top_level:
            result.append((item, False))
            if item.id not in self._collapsed_parents:
                for child in children_by_parent.get(item.id, []):
                    result.append((child, True))
        return result

    def _toggle_collapse(self, parent_id: UUID) -> None:
        """Toggle collapse state of a parent item."""
        if parent_id in self._collapsed_parents:
            self._collapsed_parents.discard(parent_id)
        else:
            self._collapsed_parents.add(parent_id)
        self.refresh()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        """Handle keyboard shortcuts for collapse/expand."""
        if self._current_list and e is not None:
            selected = self.get_selected_item_ids()
            if len(selected) == 1:
                item = self._current_list.get_item(selected[0])
                if item and item.parent_id is None:
                    if e.key() == Qt.Key.Key_Left and item.id not in self._collapsed_parents:
                        self._toggle_collapse(item.id)
                        return
                    if e.key() == Qt.Key.Key_Right and item.id in self._collapsed_parents:
                        self._toggle_collapse(item.id)
                        return
        super().keyPressEvent(e)

    def _on_empty_state_button(self) -> None:
        """Dispatch the empty-state button click to the right signal
        based on which case is currently displayed."""
        if self._empty_state_action == "add":
            self.add_task_requested.emit()
        elif self._empty_state_action == "show_completed":
            self.show_completed_requested.emit()
        elif self._empty_state_action == "clear_filters":
            self.clear_filters_requested.emit()
        elif self._empty_state_action == "create_list":
            self.create_list_requested.emit()

    def _show_empty_state(self, case: str) -> None:
        """Populate the overlay for one of the four cases and show it.

        case == "no_lists"       → "Welcome! Create your first list..." + Create list
        case == "no_list"        → "No tasks yet" + Add task
        case == "all_done"       → "All done!" + Show completed
        case == "filtered_empty" → "No tasks match..." + Clear filters
        """
        colors = get_colors()
        if case == "no_lists":
            self._empty_state_label.setText(
                self.tr(
                    "Welcome to PyTodo-Qt.\n"
                    "Create your first list to get started — it's where your tasks live."
                )
            )
            self._empty_state_button.setText(self.tr("Create list"))
            self._empty_state_action = "create_list"
        elif case == "no_list":
            self._empty_state_label.setText(
                self.tr("No tasks yet.\nAdd your first one to get started.")
            )
            self._empty_state_button.setText(self.tr("Add task"))
            self._empty_state_action = "add"
        elif case == "all_done":
            self._empty_state_label.setText(
                self.tr("All done!\nEvery task in this list is complete.")
            )
            self._empty_state_button.setText(self.tr("Show completed"))
            self._empty_state_action = "show_completed"
        else:
            self._empty_state_label.setText(self.tr("No tasks match the current filter."))
            self._empty_state_button.setText(self.tr("Clear filters"))
            self._empty_state_action = "clear_filters"

        self._empty_state.setStyleSheet(
            f"QFrame {{ background: {colors['base']}; "
            f"border: 1px solid {colors['border']}; border-radius: 12px; }}"
            f"QLabel {{ color: {colors['text']}; font-size: 14px; "
            f"background: transparent; border: none; }}"
            f"QPushButton {{ background: {colors['highlight']}; "
            f"color: {colors['highlight_text']}; border: none; "
            f"padding: 8px 18px; border-radius: 8px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {colors['link']}; }}"
        )
        self._empty_state.show()
        self._empty_state.raise_()
        self._position_empty_state()
        # Defer a second position pass to the next event-loop tick.
        # The first call may run before the viewport finishes its
        # layout (e.g. when set_list(None) fires from inside a
        # _refresh_ui sequence), leaving the overlay at (0, 0). The
        # deferred call always sees a settled layout.
        QTimer.singleShot(0, self._position_empty_state)

    def _hide_empty_state(self) -> None:
        self._empty_state.hide()
        self._empty_state_action = ""

    def _position_empty_state(self) -> None:
        """Center the overlay inside the viewport. The overlay is a
        viewport child, so the coordinates are viewport-local.
        """
        self._empty_state.adjustSize()
        viewport = self.viewport()
        if viewport is None:
            return
        # Empty viewport on initial layout — fall back to widget size
        # so the first paint after a fresh empty list still positions.
        vp_w = viewport.width() or self.width()
        vp_h = viewport.height() or self.height()
        cx = (vp_w - self._empty_state.width()) // 2
        cy = (vp_h - self._empty_state.height()) // 2
        self._empty_state.move(max(0, cx), max(0, cy))

    def refresh(self, *, background: bool = False) -> None:
        """Show the list as it now is, keeping what is on screen in place.

        The rows are made again, and the scroll position, the selected
        rows, the current cell and the keyboard focus are put back. A
        refresh that arrives while a popup or a picker of a row is open
        waits until it is closed. A ``background`` refresh also waits
        while a name is being typed; any other refresh carries the typed
        text over into the new row.
        """
        if self._must_wait(background):
            if self._refresh_held:
                self._held_background = self._held_background and background
            else:
                self._refresh_held = True
                self._held_background = background
            if not self._held_timer.isActive():
                self._held_timer.start()
            return
        self._release_held_refresh()
        self._rebuild_keeping(self._capture_view_state())

    def _release_held_refresh(self) -> None:
        self._refresh_held = False
        self._held_background = False
        self._held_timer.stop()

    def _run_held_refresh(self) -> None:
        """Carry out the waiting refresh as soon as the row is free."""
        if not self._refresh_held:
            self._held_timer.stop()
            return
        if not self._must_wait(self._held_background):
            self.refresh(background=self._held_background)

    def _owns(self, widget: QWidget | None) -> bool:
        """Whether a widget, or a window opened from one, belongs to the table."""
        while widget is not None:
            if widget is self:
                return True
            widget = widget.parentWidget()
        return False

    def _focused_widget(self) -> QWidget | None:
        """The table's widget that has, or on activation takes, the focus."""
        window = self.window()
        widget = window.focusWidget() if window is not None else None
        if widget is None or widget is self or not self._owns(widget):
            return None
        return widget

    def _must_wait(self, background: bool) -> bool:
        for opened in (QApplication.activePopupWidget(), QApplication.activeModalWidget()):
            if opened is not None and self._owns(opened):
                return True
        if background:
            focused = self._focused_widget()
            return isinstance(focused, ReminderEdit) and focused.has_unsaved_text()
        return False

    def _capture_view_state(self) -> _ViewState:
        state = _ViewState()
        if self.rowCount() == 0:
            return state
        top_row = self.rowAt(0)
        if top_row >= 0:
            state.top_row = top_row
            state.top_id = self._item_id_map.get(top_row)
            state.top_offset = -self.rowViewportPosition(top_row)
        h_bar = self.horizontalScrollBar()
        state.horizontal = h_bar.value() if h_bar is not None else 0
        state.selected = self.get_selected_item_ids()
        current = self.currentIndex()
        current_id = self._item_id_map.get(current.row()) if current.isValid() else None
        if current_id is not None:
            state.current = (current_id, current.column())

        window = self.window()
        state.table_focused = window is not None and window.focusWidget() is self
        focused = self._focused_widget()
        if focused is None:
            return state
        if isinstance(focused, ReminderEdit):
            state.focus = (focused.item_id, 1)
            if focused.has_unsaved_text():
                state.unsaved_text = focused.text()
            state.cursor = focused.cursorPosition()
            if focused.hasSelectedText():
                state.selection_start = focused.selectionStart()
                state.selection_length = len(focused.selectedText())
        else:
            for row, item_id in self._item_id_map.items():
                if self.cellWidget(row, 0) is focused:
                    state.focus = (item_id, 0)
                    break
        if state.focus is not None:
            viewport = self.viewport()
            height = viewport.height() if viewport is not None else 0
            for row, item_id in self._item_id_map.items():
                if item_id == state.focus[0]:
                    top = self.rowViewportPosition(row)
                    state.focus_row_visible = top + self.rowHeight(row) > 0 and top < height
                    break
        return state

    def _rebuild_keeping(self, state: _ViewState | None) -> None:
        """Make the rows again and put back what ``state`` holds."""
        selected_before = set(self.get_selected_item_ids())
        self._rebuilding = True
        self.setUpdatesEnabled(False)
        # The table's own signals are kept back: the selection is taken
        # away and put back, and nothing has to follow that.
        blocked = self.blockSignals(True)
        try:
            self._rebuild()
            if state is not None:
                self._restore_view_state(state)
            self._draw_selected_rows()
        finally:
            self.blockSignals(blocked)
            self.setUpdatesEnabled(True)
            self._rebuilding = False
        if set(self.get_selected_item_ids()) != selected_before:
            self._on_selection_changed()

    def _restore_view_state(self, state: _ViewState) -> None:
        if self.rowCount() == 0:
            return
        row_of = {item_id: row for row, item_id in self._item_id_map.items()}
        model = self.model()
        selection = self.selectionModel()

        # The order matters. Qt ties the keyboard focus and the current cell
        # together: a priority box that takes the focus becomes the current
        # cell and the only selected row, and a current cell with a priority
        # box gives it the focus. So the focus is put back first, then the
        # current cell where that moves no focus, then the selection; the
        # scroll position comes last, because making a cell the current one
        # scrolls the view to it.
        focus_row = row_of.get(state.focus[0]) if state.focus is not None else None
        focused: QWidget | None = None
        if state.focus is not None and focus_row is not None:
            focused = self.cellWidget(focus_row, state.focus[1])
            if state.focus[1] == 1 and focused is not None:
                focused = focused.findChild(ReminderEdit)
        if focused is not None:
            focused.setFocus(Qt.FocusReason.OtherFocusReason)
            if isinstance(focused, ReminderEdit):
                if state.unsaved_text is not None and not focused.isReadOnly():
                    focused.setText(state.unsaved_text)
                if state.selection_start >= 0:
                    focused.setSelection(state.selection_start, state.selection_length)
                else:
                    focused.setCursorPosition(min(state.cursor, len(focused.text())))

        if model is not None and selection is not None:
            flags = selection.SelectionFlag
            # A current cell in the priority column takes the focus, so it
            # is put back only when the focus was in the table already.
            if (
                focused is None
                and state.current is not None
                and (state.table_focused or state.current[1] != 0)
            ):
                row = row_of.get(state.current[0])
                if row is not None:
                    selection.setCurrentIndex(model.index(row, state.current[1]), flags.NoUpdate)
            chosen = QItemSelection()
            for item_id in state.selected:
                row = row_of.get(item_id)
                if row is not None:
                    index = model.index(row, 0)
                    chosen.select(index, index)
            selection.select(chosen, flags.ClearAndSelect | flags.Rows)

        # Scroll position: the task that was at the top is at the top
        # again; if it is gone, the row of the same number is.
        self.updateGeometries()
        if state.top_row >= 0:
            anchor = row_of.get(state.top_id) if state.top_id is not None else None
            offset = state.top_offset
            if anchor is None:
                anchor = min(state.top_row, self.rowCount() - 1)
            v_bar = self.verticalScrollBar()
            if v_bar is not None:
                if self.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerItem:
                    v_bar.setValue(anchor)
                else:
                    v_bar.setValue(v_bar.value() + self.rowViewportPosition(anchor) + offset)
        h_bar = self.horizontalScrollBar()
        if h_bar is not None:
            h_bar.setValue(state.horizontal)

        if (
            focused is not None
            and focus_row is not None
            and state.focus_row_visible
            and model is not None
        ):
            # The row being worked in stays in view when it has moved.
            self.scrollTo(model.index(focus_row, 0), QAbstractItemView.ScrollHint.EnsureVisible)

    def _rebuild(self) -> None:
        """Make every row again from the list."""
        self.setRowCount(0)
        self._item_id_map.clear()
        self._ellipsis_pairs.clear()
        self._context_row_ids.clear()
        self._row_labels.clear()
        self._row_chips.clear()
        self._row_icons.clear()
        self._rows_drawn_selected.clear()

        if self._current_list is None:
            # No active list — most often this means the database has
            # no lists at all (a fresh user, or the last list was just
            # deleted). Show the onboarding overlay with a Create list
            # action so the user has a path forward without needing to
            # discover the menu / toolbar.
            self._show_empty_state("no_lists")
            return

        colors = get_colors()

        # Load config once for sort order and time format
        from ...core.config import get_config

        try:
            config = get_config()
            sort_tiers = config.database.sort_tiers()
            time_fmt = config.appearance.time_format
        except Exception:
            logger.log.exception("Failed to load config for table refresh")
            sort_tiers = [("completion", False), ("due_date", False), ("priority", False)]
            time_fmt = "system"

        def sort_key(item):
            key: list = []
            for dimension, reverse in sort_tiers:
                key.extend(_sort_fragment(item, dimension, reverse))
            key.append(item.reminder.lower())
            return tuple(key)

        try:
            items = sorted(self._current_list.active_items(), key=sort_key)
        except Exception:
            logger.log.exception("Sort failed, falling back to unsorted")
            items = list(self._current_list.active_items())

        # Snapshot the unfiltered items so the empty-state dispatcher
        # can tell "no items at all" from "filter hides everything."
        items_all = list(items)

        # Apply filter if active
        if self._filter_state is not None and self._filter_state.is_active:
            items = self._apply_filter(items)

        # Empty-state dispatch — three cases mirror the kanban view so
        # the two surfaces offer identical exit paths from a zero-rows
        # state. "no_list" when there are no items at all; "all_done"
        # when the user is hiding completed and every item is complete;
        # "filtered_empty" for any other filter combo that matches
        # nothing.
        if not items:
            if not items_all:
                self._show_empty_state("no_list")
            elif (
                self._filter_state is not None
                and getattr(self._filter_state, "status", 0) == 1
                and all(it.complete for it in items_all)
            ):
                self._show_empty_state("all_done")
            else:
                self._show_empty_state("filtered_empty")
        else:
            self._hide_empty_state()

        # Build hierarchical display order
        display_items = self._build_display_order(items, sort_key)

        # Pre-compute children info for parent badges
        children_by_parent: dict[UUID, list[TodoItem]] = {}
        for item in items:
            if item.parent_id is not None:
                children_by_parent.setdefault(item.parent_id, []).append(item)

        for row, (item, is_child) in enumerate(display_items):
            is_context = item.id in self._context_row_ids
            self.insertRow(row)
            self.setRowHeight(row, 42)
            self._item_id_map[row] = item.id
            on_the_row = self._row_labels.setdefault(row, [])

            def write(label: QLabel, style: str, labels=on_the_row) -> None:
                """Style a label that stands on the row's own background."""
                label.setStyleSheet(style)
                labels.append((label, style))

            # Priority combo box
            priority_combo = QComboBox()
            priority_combo.setMinimumHeight(32)
            priority_combo.addItems([self.tr("Low"), self.tr("Normal"), self.tr("High")])
            priority_combo.setCurrentIndex(
                2 - item.priority + 1
            )  # 1=High->2, 2=Normal->1, 3=Low->0
            priority_combo.currentIndexChanged.connect(
                lambda idx, r=row: self._on_priority_changed(r, idx)
            )

            # Set priority color
            if item.priority == 1:
                priority_combo.setStyleSheet(f"color: {colors['priority_high']};")
            elif item.priority == 2:
                priority_combo.setStyleSheet(f"color: {colors['priority_normal']};")
            else:
                priority_combo.setStyleSheet(f"color: {colors['priority_low']};")

            from ...core.models import build_rich_tooltip

            priority_combo.setToolTip(build_rich_tooltip(item, theme_colors=colors))

            self.setCellWidget(row, 0, priority_combo)

            # Reminder column: text field + optional tag chips
            reminder_container = QWidget()
            reminder_layout = QHBoxLayout(reminder_container)
            reminder_layout.setContentsMargins(0, 0, 0, 0)
            reminder_layout.setSpacing(4)

            # Child indentation
            if is_child:
                indent = QWidget()
                indent.setFixedWidth(24)
                reminder_layout.addWidget(indent)
                prefix = QLabel("\u203a")  # Single right-pointing angle quotation mark
                write(prefix, f"color: {colors['completed_text']}; font-size: 14px;")
                prefix.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                reminder_layout.addWidget(prefix)

            # Parent expand/collapse toggle
            has_children = item.id in children_by_parent
            if has_children and not is_child:
                collapsed = item.id in self._collapsed_parents
                toggle_char = "\u25b6" if collapsed else "\u25bc"  # ▶ or ▼
                toggle_btn = ClickableLabel(toggle_char)
                write(
                    toggle_btn,
                    f"color: {colors['completed_text']}; font-size: 10px; padding: 0 2px;",
                )
                toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                toggle_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                toggle_btn.clicked.connect(lambda pid=item.id: self._toggle_collapse(pid))
                reminder_layout.addWidget(toggle_btn)

            reminder_edit = ReminderEdit(item.id, item.reminder)
            reminder_edit.setMinimumHeight(32)
            reminder_edit.returnPressed.connect(
                lambda edit=reminder_edit: self._save_reminder(edit)
            )
            reminder_edit.editingFinished.connect(
                lambda edit=reminder_edit: self._on_reminder_editing_finished(edit)
            )

            # Style based on completion status
            if is_context:
                reminder_edit.setFont(self._normal_font)
                reminder_edit.setStyleSheet(f"color: {colors['completed_text']};")
                reminder_edit.setReadOnly(True)
            elif item.complete:
                reminder_edit.setFont(self._completed_font)
                reminder_edit.setStyleSheet(
                    f"color: {colors['completed_text']}; "
                    f"background-color: {colors['completed_bg']};"
                )
            else:
                reminder_edit.setFont(self._normal_font)

            from ...core.models import build_rich_tooltip

            reminder_edit.setToolTip(build_rich_tooltip(item, theme_colors=colors))

            reminder_layout.addWidget(reminder_edit, 1)
            reminder_edit.setCursorPosition(0)

            # Ellipsis indicator for viewing full reminder text (shown only when truncated)
            ellipsis = ClickableLabel("…")
            write(ellipsis, f"color: {colors['completed_text']}; font-size: 10px;")
            ellipsis.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            ellipsis.setCursor(Qt.CursorShape.PointingHandCursor)
            ellipsis.clicked.connect(
                lambda iid=item.id, e=ellipsis: self._show_reminder_popup(iid, e)
            )
            ellipsis.setVisible(False)
            reminder_layout.addWidget(ellipsis)
            self._ellipsis_pairs.append((reminder_edit, ellipsis))

            # Inline time spent label
            if item.time_spent > 0:
                from .pomodoro import PomodoroWidget

                time_text = PomodoroWidget.format_time_spent(item.time_spent)
                time_label = QLabel(time_text)
                write(time_label, f"color: {colors['completed_text']}; font-size: 10px;")
                time_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                reminder_layout.addWidget(time_label)

            # Inline pomodoro count with tomato icon
            if item.pomodoro_count > 0 or item.estimated_pomodoros > 0:
                pomo_container = QHBoxLayout()
                pomo_container.setContentsMargins(0, 0, 0, 0)
                pomo_container.setSpacing(2)

                icon_path = Path(__file__).parent.parent / "icons" / "pomodoro-work.svg"
                if icon_path.exists():
                    pomo_icon = QLabel()
                    pomo_pixmap = QPixmap(str(icon_path)).scaled(
                        12,
                        12,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    pomo_icon.setPixmap(pomo_pixmap)
                    self._row_icons.setdefault(row, []).append((pomo_icon, pomo_pixmap))
                    pomo_icon.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                    pomo_container.addWidget(pomo_icon)

                if item.estimated_pomodoros > 0:
                    pomo_text = f"{item.pomodoro_count}/{item.estimated_pomodoros}"
                else:
                    pomo_text = str(item.pomodoro_count)
                pomo_label = QLabel(pomo_text)
                write(pomo_label, f"color: {colors['completed_text']}; font-size: 10px;")
                pomo_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                pomo_container.addWidget(pomo_label)

                pomo_widget = QWidget()
                pomo_widget.setLayout(pomo_container)
                pomo_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                reminder_layout.addWidget(pomo_widget)

            # Parent progress badge [completed/total]
            if has_children and not is_child:
                children = children_by_parent[item.id]
                completed = sum(1 for c in children if c.complete)
                total = len(children)
                badge_text = f"[{completed}/{total}]"
                badge_label = QLabel(badge_text)
                badge_color = (
                    colors.get("due_today", "#4CAF50")
                    if completed == total
                    else colors["completed_text"]
                )
                write(badge_label, f"color: {badge_color}; font-size: 10px; font-weight: bold;")
                badge_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                reminder_layout.addWidget(badge_label)

            # Tag chips (show max 2 inline, overflow badge for the rest)
            _MAX_VISIBLE_TAGS = 2
            if item.tags:
                chip_style = (
                    f"background-color: {colors['highlight']}; "
                    f"color: {colors.get('highlight_text', '#ffffff')}; "
                    "border-radius: 8px; padding: 1px 6px; font-size: 10px;"
                )
                for tag in item.tags[:_MAX_VISIBLE_TAGS]:
                    chip = QLabel(tag)
                    chip.setStyleSheet(chip_style)
                    chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                    reminder_layout.addWidget(chip)
                    self._row_chips.setdefault(row, []).append((chip, chip_style))
                overflow = len(item.tags) - _MAX_VISIBLE_TAGS
                if overflow > 0:
                    badge = ClickableLabel(f"+{overflow}")
                    badge.setStyleSheet(
                        f"background-color: {colors['button']}; "
                        f"color: {colors['text']}; "
                        "border-radius: 8px; padding: 1px 6px; font-size: 10px;"
                    )
                    badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                    badge.setCursor(Qt.CursorShape.PointingHandCursor)
                    badge.clicked.connect(lambda iid=item.id, b=badge: self._show_tag_popup(iid, b))
                    reminder_layout.addWidget(badge)

            self.setCellWidget(row, 1, reminder_container)

            # Due date widget
            due_widget = DueDateLabel(
                item.due_date,
                item.complete,
                recurring=item.is_recurring,
                due_time=item.due_time,
                time_format=time_fmt,
                due_time_end=item.due_time_end,
                due_time_block=item.due_time_block,
            )
            due_widget.date_changed.connect(lambda d, r=row: self._on_due_date_changed(r, d))
            due_widget.time_changed.connect(lambda t, r=row: self._on_due_time_changed(r, t))

            # Apply styling based on due date status
            if not item.complete:
                if is_overdue(item.due_date, item.due_time):
                    due_widget.set_text_style(f"color: {colors['due_overdue']}; font-weight: bold;")
                elif is_due_today(item.due_date):
                    due_widget.set_text_style(f"color: {colors['due_today']}; font-weight: bold;")
                elif item.due_date and is_due_this_week(item.due_date):
                    due_widget.set_text_style(f"color: {colors['due_soon']};")
            elif item.due_date:
                due_widget.set_text_style(f"color: {colors['completed_text']};")

            due_widget.setToolTip(build_rich_tooltip(item, theme_colors=colors))

            self.setCellWidget(row, 2, due_widget)

        logger.log.debug("Refreshed table with %d items", len(display_items))
        # Defer ellipsis check until cell widgets have been laid out and sized
        QTimer.singleShot(50, self._update_ellipsis_visibility)

    def _update_ellipsis_visibility(self) -> None:
        """Show/hide ellipsis indicators based on whether reminder text is truncated."""
        for edit, ellipsis in self._ellipsis_pairs:
            available = edit.contentsRect().width()
            # Skip widgets not yet laid out (e.g. last row at edge of viewport)
            if available <= 0:
                ellipsis.setVisible(False)
                continue
            text_width = edit.fontMetrics().horizontalAdvance(edit.text())
            ellipsis.setVisible(text_width > available)

    def get_selected_item_ids(self) -> list[UUID]:
        """Get IDs of selected items."""
        ids = []
        for row in {index.row() for index in self.selectedIndexes()}:
            if row in self._item_id_map:
                ids.append(self._item_id_map[row])
        return ids

    def get_item_id_at_row(self, row: int) -> UUID | None:
        """Get item ID for a specific row."""
        return self._item_id_map.get(row)

    def _on_priority_changed(self, row: int, combo_index: int) -> None:
        """Handle priority combo box change."""
        item_id = self._item_id_map.get(row)
        if item_id is None:
            return

        # Convert combo index to priority (0=Low->3, 1=Normal->2, 2=High->1)
        priority = 3 - combo_index
        self.item_priority_changed.emit(item_id, priority)

    def _take_reminder(self, edit: ReminderEdit) -> str | None:
        """The name to save from a field, or None when there is none.

        A field emptied of its text takes the stored name back: a task
        is not left without a name.
        """
        if self._rebuilding or not edit.has_unsaved_text():
            return None
        text = edit.text()
        if not text.strip():
            edit.restore_stored_text()
            return None
        edit.stored_text = text
        return text

    def _save_reminder(self, edit: ReminderEdit) -> None:
        """Save the name in a field on Enter, and leave the field.

        The cursor going out of the field shows that Enter was taken.
        The focus goes to the table, with the field's row as the current
        one, so that the arrow keys go on from there.
        """
        text = self._take_reminder(edit)
        model = self.model()
        selection = self.selectionModel()
        row = next((r for r, i in self._item_id_map.items() if i == edit.item_id), None)
        if row is not None and model is not None and selection is not None:
            selection.setCurrentIndex(model.index(row, 1), selection.SelectionFlag.NoUpdate)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        if text is not None:
            self.item_reminder_changed.emit(edit.item_id, text)

    def _on_reminder_editing_finished(self, edit: ReminderEdit) -> None:
        """Save the name in a field that is left.

        The saving is put off until the event that took the focus away
        is over: it makes the rows again, and the click that ends the
        editing may be on one of them.
        """
        if self._rebuilding:
            return
        text = self._take_reminder(edit)
        if not edit.hasFocus():
            # A field that is left shows the start of its text. Enter
            # ends the editing too, and leaves the cursor where it is.
            edit.setCursorPosition(0)
        if text is not None:
            self._names_to_save.append((edit.item_id, text))
            QTimer.singleShot(0, self._save_names)

    def _save_names(self) -> None:
        names, self._names_to_save = self._names_to_save, []
        for item_id, text in names:
            self.item_reminder_changed.emit(item_id, text)

    def _on_due_date_changed(self, row: int, due_date: date | None) -> None:
        """Handle due date change from inline picker."""
        item_id = self._item_id_map.get(row)
        if item_id is not None:
            self.item_due_date_changed.emit(item_id, due_date)

    def _on_due_time_changed(self, row: int, due_time: time | None) -> None:
        """Handle due time change from inline picker."""
        item_id = self._item_id_map.get(row)
        if item_id is not None:
            self.item_due_time_changed.emit(item_id, due_time)

    def _show_reminder_popup(self, item_id: UUID, anchor: QWidget) -> None:
        """Show a popup with the full reminder text."""
        if self._current_list is None:
            return
        item = self._current_list.get_item(item_id)
        if not item:
            return

        colors = get_colors()
        popup = QWidget(self, Qt.WindowType.Popup)
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(8, 6, 8, 6)

        label = QLabel(item.reminder)
        label.setWordWrap(True)
        label.setMaximumWidth(400)
        label.setStyleSheet(f"color: {colors['text']}; font-size: 12px;")
        layout.addWidget(label)

        popup.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 2))
        popup.move(pos)
        popup.show()

    def _show_tag_popup(self, item_id: UUID, badge: QWidget) -> None:
        """Show a popup with all overflow tags as styled chips."""
        if self._current_list is None:
            return
        item = self._current_list.get_item(item_id)
        if not item or len(item.tags) <= 2:
            return

        colors = get_colors()
        chip_style = (
            f"background-color: {colors['highlight']}; "
            f"color: {colors.get('highlight_text', '#ffffff')}; "
            "border-radius: 8px; padding: 2px 8px; font-size: 10px;"
        )

        popup = QWidget(self, Qt.WindowType.Popup)
        layout = QHBoxLayout(popup)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        for tag in item.tags[2:]:
            chip = QLabel(tag)
            chip.setStyleSheet(chip_style)
            layout.addWidget(chip)

        edit_btn = QPushButton(self.tr("Edit..."))
        edit_btn.setFixedHeight(20)
        edit_btn.setStyleSheet("font-size: 10px; padding: 1px 6px;")
        edit_btn.clicked.connect(lambda: self._on_popup_edit(popup, item_id))
        layout.addWidget(edit_btn)

        popup.adjustSize()
        pos = badge.mapToGlobal(QPoint(0, badge.height() + 2))
        popup.move(pos)
        popup.show()

    def _on_popup_edit(self, popup: QWidget, item_id: UUID) -> None:
        """Handle 'Edit...' click in tag popup."""
        popup.close()
        self.edit_tags_requested.emit(item_id)

    def _draw_selected_rows(self) -> None:
        """Recolour what stands on the rows whose selection has changed.

        A selected row is filled with the highlight colour, and the
        colours its labels have on the ordinary background do not read
        on that. Every label takes the highlight's text colour there, a
        tag chip gets an outline in it, as its fill is the highlight
        colour too, and an icon is drawn in it.
        """
        selected = {index.row() for index in self.selectedIndexes()}
        on_highlight = get_colors()["highlight_text"]
        for row in selected ^ self._rows_drawn_selected:
            color = on_highlight if row in selected else None
            for label, style in self._row_labels.get(row, []):
                label.setStyleSheet(style if color is None else _with_color(style, color))
            for chip, style in self._row_chips.get(row, []):
                chip.setStyleSheet(
                    style
                    if color is None
                    # The padding gives the outline its room, so that the
                    # chip keeps its size.
                    else f"{style} border: 1px solid {color}; padding: 0px 5px;"
                )
            for icon, pixmap in self._row_icons.get(row, []):
                icon.setPixmap(pixmap if color is None else _in_one_colour(pixmap, color))
            due_widget = self.cellWidget(row, 2)
            if isinstance(due_widget, DueDateLabel):
                due_widget.set_on_highlight(color)
        self._rows_drawn_selected = selected

    def _on_selection_changed(self) -> None:
        """Handle selection change."""
        self._draw_selected_rows()
        selected = self.get_selected_item_ids()
        if len(selected) == 1:
            self.item_selected.emit(selected[0])
        else:
            self.item_selected.emit(None)
