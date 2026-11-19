"""No text is smaller than the platform's least size.

Style sheets and painters gave texts a size in pixels. Such a size does
not follow the application's own type size, and what it comes to beside
that type depends on the platform: macOS counts 72 pixels to the inch,
so that the application's 10 pt type is 10 px high, Linux and Windows
count 96, and it is 13.3 px. A text of 10 px was the application's own
size on macOS and three quarters of it elsewhere, 7.5 pt: 96 texts were
at 6.75 pt to 8.25 pt there, the rows of the calendar's unscheduled
panel among them.
"""

from __future__ import annotations

import re
import sys
from datetime import date, time, timedelta
from pathlib import Path

import pytest
from PyQt6.QtGui import QFontInfo, QFontMetrics
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QLabel,
    QLineEdit,
    QWidget,
)

from pytodo_qt.core.models import create_todo_item, create_todo_list
from pytodo_qt.gui.styles.themes import MIN_FONT_PX, font_px

GUI_DIR = Path(__file__).resolve().parent.parent / "src" / "pytodo_qt" / "gui"


def _sources() -> list[tuple[Path, str]]:
    return [(path, path.read_text(encoding="utf-8")) for path in sorted(GUI_DIR.rglob("*.py"))]


class TestTheLeastSize:
    def test_it_is_ten_points_on_macos_and_nine_elsewhere(self):
        """Ten points are ten pixels on macOS; nine points are twelve
        pixels where 96 are counted to the inch."""
        assert (10 if sys.platform == "darwin" else 12) == MIN_FONT_PX

    @pytest.mark.parametrize("size", [1, 9, 10, 11])
    def test_a_smaller_size_is_raised_to_it(self, size):
        assert font_px(size) == max(size, MIN_FONT_PX)
        assert font_px(size) >= MIN_FONT_PX

    @pytest.mark.parametrize("size", [12, 13, 14, 18, 32])
    def test_a_size_above_it_is_kept(self, size):
        """The steps between a caption, a label and a heading stay."""
        assert font_px(size) == size

    def test_it_is_not_above_the_applications_own_size(self, qtbot):
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        assert QFontInfo(app.font()).pixelSize() >= MIN_FONT_PX - 2


class TestSourcesNameNoSmallerSize:
    def test_no_style_sheet_gives_a_size_under_twelve_pixels(self):
        """Twelve is the least size where it is highest. A smaller size
        is written `font_px(n)`, which raises it where it has to be."""
        pattern = re.compile(r"font-size:\s*(\d+)px")
        found = [
            f"{path.relative_to(GUI_DIR)}: {match.group(0)}"
            for path, text in _sources()
            for match in pattern.finditer(text)
            if int(match.group(1)) < 12
        ]
        assert found == []

    def test_no_font_is_set_to_a_size_under_twelve_pixels(self):
        pattern = re.compile(r"setPixelSize\((\d+)\)")
        found = [
            f"{path.relative_to(GUI_DIR)}: {match.group(0)}"
            for path, text in _sources()
            for match in pattern.finditer(text)
            if int(match.group(1)) < 12
        ]
        assert found == []

    def test_no_font_is_set_to_a_size_under_nine_points(self):
        pattern = re.compile(r"setPointSize\((\d+)\)")
        found = [
            f"{path.relative_to(GUI_DIR)}: {match.group(0)}"
            for path, text in _sources()
            for match in pattern.finditer(text)
            if int(match.group(1)) < 9
        ]
        assert found == []

    def test_the_raised_sizes_are_in_use(self):
        text = "\n".join(text for _path, text in _sources())
        assert text.count("font_px(") >= 90


def _todo_list():
    today = date.today()
    todo_list = create_todo_list("Sizes")

    def add(name, **fields):
        item = create_todo_item(name, due_date=fields.pop("due_date", None))
        for key, value in fields.items():
            setattr(item, key, value)
        todo_list.add_item(item)
        return item

    add(
        "due today, repeating",
        due_date=today,
        due_time=time(15, 0),
        tags=["@one", "@two", "@three"],
        recurrence_type="daily",
        recurrence_interval=1,
        time_spent=300,
        pomodoro_count=1,
        estimated_pomodoros=2,
    )
    parent = add("a parent", due_date=today + timedelta(days=2))
    add("a child", parent_id=parent.id, complete=True)
    add("finished", due_date=today - timedelta(days=1), complete=True, board_column="Done")
    add("without a date", tags=["@one"])
    add("finished without a date", complete=True)
    return todo_list


def _texts(root: QWidget) -> list[QWidget]:
    """The widgets under `root` that show a text of their own."""
    found = []
    for widget in [root, *root.findChildren(QWidget)]:
        if not widget.isVisibleTo(root) and widget is not root:
            continue
        if (
            isinstance(widget, QLabel | QAbstractButton)
            and widget.text()
            or isinstance(widget, QLineEdit)
        ):
            found.append(widget)
    return found


def _too_small(root: QWidget) -> list[str]:
    for _ in range(4):
        QApplication.processEvents()
    small = []
    for widget in _texts(root):
        widget.ensurePolished()
        size = QFontInfo(widget.font()).pixelSize()
        if size < MIN_FONT_PX:
            small.append(
                f"{type(widget).__name__} {getattr(widget, 'text', lambda: '')()[:30]!r}: {size}px"
            )
    return small


class TestNoWidgetShowsSmallerText:
    @pytest.fixture(autouse=True)
    def _nothing_is_saved(self, monkeypatch):
        """Choosing a view of the calendar saves the configuration."""
        monkeypatch.setattr("pytodo_qt.core.config.ConfigManager.save", lambda self: None)

    def _shown(self, qtbot, widget: QWidget, size=(1100, 700)) -> QWidget:
        qtbot.addWidget(widget)
        widget.resize(*size)
        widget.show()
        qtbot.waitExposed(widget)
        return widget

    def test_the_list_view(self, qtbot):
        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        table = TodoTableWidget()
        table.set_list(_todo_list())
        assert _too_small(self._shown(qtbot, table)) == []

    def test_the_board(self, qtbot):
        from pytodo_qt.gui.widgets.kanban_board import KanbanBoardWidget

        board = KanbanBoardWidget()
        board.set_list(_todo_list())
        assert _too_small(self._shown(qtbot, board)) == []

    @pytest.mark.parametrize(
        "sub_view", ["SUB_DAY", "SUB_WEEK", "SUB_MONTH", "SUB_AGENDA", "SUB_TIMELINE"]
    )
    def test_the_calendar(self, qtbot, sub_view):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        calendar = CalendarViewWidget()
        calendar.set_list(_todo_list())
        self._shown(qtbot, calendar)
        calendar._set_sub_view(getattr(calendar, sub_view))
        assert _too_small(calendar) == []

    def test_the_rows_of_the_unscheduled_panel(self, qtbot):
        """The texts that were named as too small to read."""
        from pytodo_qt.gui.widgets.calendar_view import _UnscheduledPanel

        panel = _UnscheduledPanel()
        todo_list = _todo_list()
        panel.set_items([item for item in todo_list.items.values() if item.due_date is None])
        self._shown(qtbot, panel, (260, 400))
        labels = [label for label in panel.findChildren(QLabel) if label.text()]
        assert len(labels) >= 3
        assert _too_small(panel) == []

    def test_the_detail_panel(self, qtbot):
        from pytodo_qt.gui.widgets.detail_panel import TaskDetailPanel

        todo_list = _todo_list()
        panel = TaskDetailPanel()
        self._shown(qtbot, panel, (340, 700))
        panel.set_item(next(iter(todo_list.items.values())), todo_list)
        assert _too_small(panel) == []

    def test_the_status_bar(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import StatusBarWidget

        status_bar = StatusBarWidget()
        self._shown(qtbot, status_bar, (1100, 40))
        status_bar.set_server_status(True, "192.0.2.1", 5364)
        status_bar.set_web_status(True, 8080, "123456")
        status_bar.set_sync_status("error")
        status_bar.set_pending_sync_count(2)
        assert _too_small(status_bar) == []

    def test_the_focus_timer_dialog(self, qtbot):
        from pytodo_qt.gui.dialogs.focus_timer import FocusTimerDialog

        assert _too_small(self._shown(qtbot, FocusTimerDialog(), (420, 400))) == []

    def test_the_settings_dialog(self, qtbot):
        from pytodo_qt.gui.dialogs.settings import SettingsDialog

        dialog = self._shown(qtbot, SettingsDialog(), (760, 700))
        for index in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(index)
            assert _too_small(dialog) == [], dialog.tabs.tabText(index)


class TestDailyGoalRing:
    def test_the_count_is_written_at_the_least_size_or_above(self, qtbot):
        from pytodo_qt.gui.widgets.status_bar import DailyGoalRingWidget

        ring = DailyGoalRingWidget()
        qtbot.addWidget(ring)
        assert QFontInfo(ring._count_font).pixelSize() >= MIN_FONT_PX

    def test_the_ring_has_room_for_two_digits(self, qtbot):
        """The ring was 22 pixels wide for a count of 7 pt."""
        from pytodo_qt.gui.widgets.status_bar import _RING_INSET, DailyGoalRingWidget

        ring = DailyGoalRingWidget()
        qtbot.addWidget(ring)
        two_digits = QFontMetrics(ring._count_font).horizontalAdvance("00")
        assert ring.width() == ring.height()
        assert ring.width() >= 22
        assert ring.width() - 2 * _RING_INSET >= two_digits


def _clipped(root: QWidget) -> list[str]:
    """The labels and buttons under `root` that are lower than their text."""
    for _ in range(8):
        QApplication.processEvents()
    found = []
    for widget in root.findChildren(QWidget):
        if not widget.isVisibleTo(root):
            continue
        if isinstance(widget, QLabel) and widget.text() and widget.pixmap().isNull():
            needed = (
                widget.heightForWidth(widget.width())
                if widget.wordWrap()
                else QFontMetrics(widget.font()).height()
            )
        elif isinstance(widget, QAbstractButton) and widget.text():
            needed = QFontMetrics(widget.font()).height()
        else:
            continue
        if widget.height() < needed - 1:
            found.append(f"{widget.text()[:30]!r}: {widget.height()} < {needed}")
    return found


class TestTextFitsAtTheLargestLeastSize:
    """Twelve pixels is the least size on Linux and Windows. The checks
    run with it on every platform: a text that grows has to have the
    room to."""

    @pytest.fixture(autouse=True)
    def _twelve_pixels(self, monkeypatch):
        monkeypatch.setattr("pytodo_qt.gui.styles.themes.MIN_FONT_PX", 12)
        monkeypatch.setattr("pytodo_qt.core.config.ConfigManager.save", lambda self: None)

    def _shown(self, qtbot, widget: QWidget, size) -> QWidget:
        qtbot.addWidget(widget)
        widget.resize(*size)
        widget.show()
        qtbot.waitExposed(widget)
        return widget

    @staticmethod
    def _long():
        item = create_todo_item(
            "A reminder that is long enough to need more than one line in a narrow panel"
        )
        item.tags = ["@long"]
        return item

    def test_a_row_of_the_unscheduled_panel_is_as_tall_as_its_text(self, qtbot):
        """A row is a button with its text in labels inside it. It had
        a button's own height, and a title with a line of detail under
        it was squeezed into the room of one line and a half."""
        from pytodo_qt.gui.widgets.calendar_view import _DraggableTaskButton, _UnscheduledPanel

        tagged = create_todo_item("Pick up the parcel")
        tagged.tags = ["@errand"]
        panel = _UnscheduledPanel()
        panel.set_items([tagged, create_todo_item("Renew the passport"), self._long()])
        self._shown(qtbot, panel, (220, 400))

        assert len(panel.findChildren(_DraggableTaskButton)) == 3
        assert _clipped(panel) == []

    def test_a_title_that_wraps_gets_its_lines(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import _DraggableTaskButton, _UnscheduledPanel

        panel = _UnscheduledPanel()
        panel.set_items([self._long()])
        self._shown(qtbot, panel, (220, 400))
        for _ in range(8):
            QApplication.processEvents()

        row = panel.findChildren(_DraggableTaskButton)[0]
        title = row.findChildren(QLabel)[0]
        assert title.wordWrap()
        assert title.heightForWidth(title.width()) > QFontMetrics(title.font()).height()
        assert title.height() >= title.heightForWidth(title.width())

    def test_a_row_of_the_day_popover_is_as_tall_as_its_text(self, qtbot):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        todo_list = create_todo_list("Popover")
        items = []
        for name in ("Short", self._long().reminder, "Tagged"):
            item = create_todo_item(name, due_date=date.today())
            item.tags = ["@one"]
            todo_list.add_item(item)
            items.append(item)
        calendar = CalendarViewWidget()
        calendar.set_list(todo_list)
        self._shown(qtbot, calendar, (1100, 700))
        calendar._show_day_popover(date.today(), items)
        try:
            assert _clipped(calendar._popover) == []
        finally:
            calendar._close_popover()

    def test_the_list_view(self, qtbot):
        from pytodo_qt.gui.widgets.todo_table import TodoTableWidget

        table = TodoTableWidget()
        table.set_list(_todo_list())
        assert _clipped(self._shown(qtbot, table, (1000, 420))) == []

    def test_the_board(self, qtbot):
        from pytodo_qt.gui.widgets.kanban_board import KanbanBoardWidget

        board = KanbanBoardWidget()
        board.set_list(_todo_list())
        assert _clipped(self._shown(qtbot, board, (1000, 520))) == []

    @pytest.mark.parametrize("sub_view", ["SUB_DAY", "SUB_WEEK", "SUB_MONTH", "SUB_AGENDA"])
    def test_the_calendar(self, qtbot, sub_view):
        from pytodo_qt.gui.widgets.calendar_view import CalendarViewWidget

        calendar = CalendarViewWidget()
        calendar.set_list(_todo_list())
        self._shown(qtbot, calendar, (1200, 700))
        calendar._set_sub_view(getattr(calendar, sub_view))
        assert _clipped(calendar) == []

    def test_the_detail_panel(self, qtbot):
        from pytodo_qt.gui.widgets.detail_panel import TaskDetailPanel

        todo_list = _todo_list()
        panel = TaskDetailPanel()
        self._shown(qtbot, panel, (340, 900))
        panel.set_item(next(iter(todo_list.items.values())), todo_list)
        assert _clipped(panel) == []

    def test_the_cards_of_mobile_access(self, qtbot):
        from pytodo_qt.gui.dialogs.web_connect import _MethodCard

        # A letter for the icon: the check is of the card's texts. An
        # emoji's line is higher than its glyph, by more than the card
        # gives it once the emoji font is loaded.
        card = _MethodCard(
            icon_text="Q",
            title="Quick Connect",
            subtitle="Scan and go",
            description="Scan a QR code and enter a PIN.",
            badge_text="Encrypted",
            badge_color="#297a4b",
            recommended=True,
        )
        assert _clipped(self._shown(qtbot, card, (320, 330))) == []
