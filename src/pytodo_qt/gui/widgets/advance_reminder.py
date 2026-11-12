"""Editor for a task's advance reminder.

An advance reminder is a line in the daily summary on the days leading
up to a task's due date. A task stores it as two fields,
``remind_before_days`` and ``reminder_cadence``; a day count with the
cadence "none" means nothing, so the two are edited together as one
choice — off, once, or every day until due — and a day count that only
applies when the choice is not "off".
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QBoxLayout, QComboBox, QSpinBox, QWidget

from ...core.notification_policy import ADVANCE_DAYS_RANGE, AdvanceCadence

DAYS_RANGE = ADVANCE_DAYS_RANGE
DEFAULT_DAYS = 1


class AdvanceReminderEditor(QWidget):
    """A cadence choice and a day count, side by side or stacked.

    ``changed`` carries (remind_before_days, reminder_cadence) as they
    are to be stored, and is emitted only for changes made by the user.

    ``stacked`` puts the day count under the choice, for a narrow
    column. ``hide_days_when_off`` hides the day count while the choice
    is "Off", where a greyed "1 day before" would read as a value.
    """

    changed = pyqtSignal(int, str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        stacked: bool = False,
        hide_days_when_off: bool = False,
    ) -> None:
        super().__init__(parent)
        self._hide_days_when_off = hide_days_when_off
        self._loading = False

        self.cadence_combo = QComboBox()
        self.cadence_combo.addItem(self.tr("Off"), AdvanceCadence.NONE.value)
        self.cadence_combo.addItem(self.tr("Once"), AdvanceCadence.ONCE.value)
        self.cadence_combo.addItem(
            self.tr("Every day until due"), AdvanceCadence.DAILY_UNTIL_DUE.value
        )
        self.cadence_combo.setAccessibleName(self.tr("Advance reminder"))
        self.cadence_combo.setAccessibleDescription(
            self.tr("How often to mention the task in the daily summary before it is due")
        )

        self.days_spin = QSpinBox()
        self.days_spin.setRange(*DAYS_RANGE)
        self.days_spin.setValue(DEFAULT_DAYS)
        # One change per committed value, not one per keystroke.
        self.days_spin.setKeyboardTracking(False)
        self.days_spin.setAccessibleName(self.tr("Days before the due date"))
        self.days_spin.setAccessibleDescription(
            self.tr("Applies to the advance reminder choice to its left")
        )

        direction = (
            QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight
        )
        layout = QBoxLayout(direction, self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.cadence_combo)
        layout.addWidget(self.days_spin)
        if not stacked:
            layout.addStretch(1)
        self.setFocusProxy(self.cadence_combo)

        self.cadence_combo.currentIndexChanged.connect(self._on_edited)
        self.days_spin.valueChanged.connect(self._on_edited)
        self._refresh()

    def value(self) -> tuple[int, str]:
        """Return (remind_before_days, reminder_cadence) to store."""
        cadence = self.cadence_combo.currentData() or AdvanceCadence.NONE.value
        if cadence == AdvanceCadence.NONE.value:
            return 0, cadence
        return self.days_spin.value(), cadence

    def set_value(self, days: int, cadence: str) -> None:
        """Show a stored reminder without reporting it as a change.

        A stored combination that asks for no reminder — an unknown
        cadence, or a day count below one — is shown as "Off".
        """
        index = self.cadence_combo.findData(cadence)
        if index < 0 or days < 1:
            index = 0
        self._loading = True
        try:
            self.cadence_combo.setCurrentIndex(index)
            if index != 0:
                low, high = DAYS_RANGE
                self.days_spin.setValue(min(max(days, low), high))
        finally:
            self._loading = False
        self._refresh()

    def _is_off(self) -> bool:
        return self.cadence_combo.currentData() == AdvanceCadence.NONE.value

    def _on_edited(self) -> None:
        self._refresh()
        if not self._loading:
            self.changed.emit(*self.value())

    def _refresh(self) -> None:
        off = self._is_off()
        self.days_spin.setEnabled(not off)
        if self._hide_days_when_off:
            self.days_spin.setVisible(not off)
        self.days_spin.setSuffix(
            self.tr(" day before") if self.days_spin.value() == 1 else self.tr(" days before")
        )
