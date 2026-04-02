"""time_combo.py

Editable QComboBox time picker with 30-minute interval presets.
"""

from __future__ import annotations

import re
from datetime import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox


def _generate_time_items(time_format: str = "system") -> list[tuple[str, time]]:
    """Generate 48 time entries at 30-minute intervals with display labels."""
    items: list[tuple[str, time]] = []
    for hour in range(24):
        for minute in (0, 30):
            t = time(hour, minute)
            label = _format_display(t, time_format)
            items.append((label, t))
    return items


def _format_display(t: time, time_format: str) -> str:
    """Format a time for display in the combo box."""
    if time_format == "24h":
        return t.strftime("%H:%M")
    elif time_format == "12h":
        return _format_12h(t)
    else:  # "system"
        try:
            formatted = t.strftime("%X")
            parts = formatted.rsplit(":", 1)
            if len(parts) == 2 and len(parts[1]) <= 2:
                return parts[0]
            return parts[0] + parts[1][2:]
        except Exception:
            return t.strftime("%H:%M")


def _format_12h(t: time) -> str:
    """Format time in 12-hour style."""
    h = t.hour % 12 or 12
    suffix = "AM" if t.hour < 12 else "PM"
    return f"{h}:{t.minute:02d} {suffix}"


def parse_time_text(text: str) -> time | None:
    """Parse a user-typed time string into a time object.

    Accepts formats like:
    - "2:30 PM", "2:30PM", "2:30pm"
    - "14:30"
    - "2pm", "2 PM"
    - "230pm" (interpreted as 2:30 PM)
    """
    text = text.strip()
    if not text:
        return None

    # Try HH:MM AM/PM  (e.g. "2:30 PM", "2:30pm", "12:00 AM")
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM|am|pm|Am|Pm)$", text)
    if m:
        h, mins, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if h < 1 or h > 12 or mins > 59:
            return None
        if ampm == "AM" and h == 12:
            h = 0
        elif ampm == "PM" and h != 12:
            h += 12
        return time(h, mins)

    # Try H AM/PM  (e.g. "2pm", "12 AM")
    m = re.match(r"^(\d{1,2})\s*(AM|PM|am|pm|Am|Pm)$", text)
    if m:
        h, ampm = int(m.group(1)), m.group(2).upper()
        if h < 1 or h > 12:
            return None
        if ampm == "AM" and h == 12:
            h = 0
        elif ampm == "PM" and h != 12:
            h += 12
        return time(h, 0)

    # Try HHMM AM/PM without colon (e.g. "230pm" → 2:30 PM)
    m = re.match(r"^(\d{1,2})(\d{2})\s*(AM|PM|am|pm|Am|Pm)$", text)
    if m:
        h, mins, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if h < 1 or h > 12 or mins > 59:
            return None
        if ampm == "AM" and h == 12:
            h = 0
        elif ampm == "PM" and h != 12:
            h += 12
        return time(h, mins)

    # Try 24h HH:MM  (e.g. "14:30", "9:00")
    m = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if m:
        h, mins = int(m.group(1)), int(m.group(2))
        if h > 23 or mins > 59:
            return None
        return time(h, mins)

    # Try bare number as hour in 24h (e.g. "14" → 14:00)
    m = re.match(r"^(\d{1,2})$", text)
    if m:
        h = int(m.group(1))
        if h > 23:
            return None
        return time(h, 0)

    return None


class TimeComboBox(QComboBox):
    """Editable combo box with 30-minute interval time presets.

    Users can select from the dropdown or type a custom time.
    """

    def __init__(self, time_format: str = "system", parent=None):
        super().__init__(parent)
        self._time_format = time_format
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        # Populate with 30-min intervals
        for label, t in _generate_time_items(time_format):
            self.addItem(label, t)

        # Placeholder and tooltip to aid discoverability
        line_edit = self.lineEdit()
        if line_edit:
            line_edit.setPlaceholderText(self.tr("e.g. 2:30 PM"))
            # Allow Enter to confirm without closing parent dialog
            line_edit.returnPressed.disconnect()
        self.setToolTip(self.tr("Click arrow for presets or type a time (e.g. 2:30 PM)"))

        # Scroll to selection when dropdown opens
        view = self.view()
        if view:
            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def set_time(self, t: time) -> None:
        """Set the current time value, selecting matching preset or showing custom text."""
        # Try to find exact match in presets
        for i in range(self.count()):
            if self.itemData(i) == t:
                self.setCurrentIndex(i)
                return
        # No exact match — show formatted custom text
        self.setCurrentText(_format_display(t, self._time_format))

    def get_time(self) -> time | None:
        """Get the currently selected or typed time value."""
        # First check if a preset is selected via index
        idx = self.currentIndex()
        if idx >= 0:
            data = self.itemData(idx)
            # Verify the displayed text matches what the index shows
            # (user may have typed something different)
            if data is not None and self.currentText() == self.itemText(idx):
                return data

        # Parse the typed text
        return parse_time_text(self.currentText())

    def default_to_next_hour(self) -> None:
        """Set the combo to the next whole hour from now."""
        from datetime import datetime

        now = datetime.now()
        next_hour = (now.hour + 1) % 24
        self.set_time(time(next_hour, 0))
