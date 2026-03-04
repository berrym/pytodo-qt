"""search_filter.py

Search and filter widget for filtering todo items.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QWidget,
)

from ..styles.themes import get_colors

if TYPE_CHECKING:
    pass


@dataclass
class FilterState:
    """State of the search/filter controls."""

    text: str = ""
    priority: int = 0  # 0=All, 1=High, 2=Normal, 3=Low
    status: int = 0  # 0=All, 1=Active, 2=Completed
    due_date: int = 0  # 0=All, 1=Overdue, 2=Today, 3=This Week, 4=No Due Date
    tag: str = ""  # Empty = all, otherwise filter by specific tag

    @property
    def is_active(self) -> bool:
        """Return True if any filter is active."""
        return (
            bool(self.text)
            or self.priority != 0
            or self.status != 0
            or self.due_date != 0
            or bool(self.tag)
        )


class SearchFilterWidget(QWidget):
    """Widget for searching and filtering todo items."""

    # Signal emitted when filter state changes
    filter_changed = pyqtSignal(object)  # Emits FilterState

    def __init__(self, parent=None):
        super().__init__(parent)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(150)
        self._debounce_timer.timeout.connect(self._emit_filter)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the widget UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        # Search field
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search todos...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumHeight(32)

        # Set search icon
        search_icon = self._load_icon("search.svg")
        if not search_icon.isNull():
            action = self.search_edit.addAction(
                search_icon, QLineEdit.ActionPosition.LeadingPosition
            )
            if action:
                action.setToolTip("Search")

        self.search_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.search_edit, 1)

        # Priority combo
        self.priority_combo = QComboBox()
        self.priority_combo.setMinimumHeight(32)
        self.priority_combo.addItem("Priority: All", 0)
        self.priority_combo.addItem("High", 1)
        self.priority_combo.addItem("Normal", 2)
        self.priority_combo.addItem("Low", 3)
        self.priority_combo.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self.priority_combo)

        # Status combo
        self.status_combo = QComboBox()
        self.status_combo.setMinimumHeight(32)
        self.status_combo.addItem("Status: All", 0)
        self.status_combo.addItem("Active", 1)
        self.status_combo.addItem("Completed", 2)
        self.status_combo.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self.status_combo)

        # Due date combo
        self.due_date_combo = QComboBox()
        self.due_date_combo.setMinimumHeight(32)
        self.due_date_combo.addItem("Due: All", 0)
        self.due_date_combo.addItem("Overdue", 1)
        self.due_date_combo.addItem("Due Today", 2)
        self.due_date_combo.addItem("This Week", 3)
        self.due_date_combo.addItem("No Due Date", 4)
        self.due_date_combo.addItem("Recurring", 5)
        self.due_date_combo.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self.due_date_combo)

        # Tag combo
        self.tag_combo = QComboBox()
        self.tag_combo.setMinimumHeight(32)
        self.tag_combo.addItem("Tag: All", "")
        self.tag_combo.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self.tag_combo)

    def _load_icon(self, name: str) -> QIcon:
        """Load an icon from the icons directory."""
        icon_dir = Path(__file__).parent.parent / "icons"
        icon_path = icon_dir / name
        if not icon_path.exists():
            # Try theme icon as fallback
            theme_icon = QIcon.fromTheme("edit-find")
            if not theme_icon.isNull():
                return theme_icon
            return QIcon()

        if name.endswith(".svg"):
            pixmap = QPixmap(str(icon_path))
            icon = QIcon()
            for mode in (
                QIcon.Mode.Normal,
                QIcon.Mode.Active,
                QIcon.Mode.Disabled,
                QIcon.Mode.Selected,
            ):
                icon.addPixmap(pixmap, mode)
            return icon
        return QIcon(str(icon_path))

    def _on_text_changed(self, text: str) -> None:
        """Handle search text change with debounce."""
        self._debounce_timer.start()
        self._update_visual_indicator()

    def _on_combo_changed(self, index: int) -> None:
        """Handle combo box change (immediate emit)."""
        self._emit_filter()

    def _emit_filter(self) -> None:
        """Emit the current filter state."""
        self._update_visual_indicator()
        self.filter_changed.emit(self.get_filter())

    def _update_visual_indicator(self) -> None:
        """Update visual indicator based on filter state."""
        filter_state = self.get_filter()
        if filter_state.is_active:
            colors = get_colors()
            self.search_edit.setStyleSheet(
                f"QLineEdit {{ border: 2px solid {colors['highlight']}; }}"
            )
        else:
            self.search_edit.setStyleSheet("")

    def get_filter(self) -> FilterState:
        """Get the current filter state."""
        return FilterState(
            text=self.search_edit.text().strip(),
            priority=self.priority_combo.currentData() or 0,
            status=self.status_combo.currentData() or 0,
            due_date=self.due_date_combo.currentData() or 0,
            tag=self.tag_combo.currentData() or "",
        )

    def clear_filters(self) -> None:
        """Reset all controls to defaults."""
        self.search_edit.clear()
        self.priority_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.due_date_combo.setCurrentIndex(0)
        self.tag_combo.setCurrentIndex(0)
        self._emit_filter()

    def focus_search(self) -> None:
        """Focus the search field and select all text."""
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def update_tags(self, tags: list[str]) -> None:
        """Update the tag filter combo with available tags.

        Preserves the current selection if the tag still exists.
        """
        current_tag = self.tag_combo.currentData() or ""
        self.tag_combo.blockSignals(True)
        self.tag_combo.clear()
        self.tag_combo.addItem("Tag: All", "")
        for tag in sorted(tags):
            self.tag_combo.addItem(tag, tag)
        # Restore selection
        if current_tag:
            idx = self.tag_combo.findData(current_tag)
            if idx >= 0:
                self.tag_combo.setCurrentIndex(idx)
        self.tag_combo.blockSignals(False)

    def handle_escape(self) -> None:
        """Handle escape key: clear filters if active, then unfocus."""
        if self.get_filter().is_active:
            self.clear_filters()
        self.search_edit.clearFocus()
