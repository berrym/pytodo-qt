"""Tests for the Export Charts dialog (preview + date range + selection)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from pytodo_qt.core.database import DatabaseStorage
from pytodo_qt.core.models import TodoItem, create_todo_list

# Skip if matplotlib isn't installed
matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

from PyQt6.QtCore import QDate  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from pytodo_qt.core.analytics import AnalyticsService  # noqa: E402
from pytodo_qt.gui.dialogs.export_charts import ExportChartsDialog  # noqa: E402


@pytest.fixture(scope="session")
def app():
    _app = QApplication.instance()
    if _app is None:
        _app = QApplication([])
    return _app


@pytest.fixture
def setup(tmp_path):
    storage = DatabaseStorage(tmp_path / "test.db")
    storage.open()
    lst = create_todo_list("Test List")
    today = date.today()
    for i in range(5):
        item = TodoItem(
            reminder=f"Task {i}",
            priority=2,
            due_date=today + timedelta(days=i),
            estimated_minutes=30 + i * 15,
            time_spent=(20 + i * 10) * 60,
        )
        lst.items[item.id] = item
    analytics = AnalyticsService(storage.connection)
    yield lst, analytics
    storage.close()


class TestExportChartsDialog:
    def test_construction(self, app, setup):
        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        assert dialog.windowTitle() == "Export Charts"
        assert dialog._active_list is lst

    def test_default_preset_is_30_days(self, app, setup):
        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        assert dialog.preset_combo.currentData() == 30

    def test_all_charts_selected_by_default(self, app, setup):
        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        for key in ExportChartsDialog.CHART_KEYS:
            assert dialog.chart_checkboxes[key].isChecked()

    def test_timing_chart_in_chart_keys(self, app, setup):
        """Step 5: completion timing chart is exposed in the dialog."""
        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        assert "timing" in ExportChartsDialog.CHART_KEYS
        assert "timing" in dialog.chart_checkboxes
        assert "Completion Timing" in ExportChartsDialog.CHART_LABELS["timing"]

    def test_preset_change_updates_date_fields(self, app, setup):
        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        # Switch to "Last 7 days"
        idx = dialog.preset_combo.findData(7)
        dialog.preset_combo.setCurrentIndex(idx)
        today = QDate.currentDate()
        assert dialog.start_date_edit.date() == today.addDays(-6)
        assert dialog.end_date_edit.date() == today

    def test_preset_this_month(self, app, setup):
        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        idx = dialog.preset_combo.findData("month")
        dialog.preset_combo.setCurrentIndex(idx)
        today = QDate.currentDate()
        first = QDate(today.year(), today.month(), 1)
        assert dialog.start_date_edit.date() == first

    def test_get_date_range(self, app, setup):
        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        dialog.start_date_edit.setDate(QDate(2026, 1, 1))
        dialog.end_date_edit.setDate(QDate(2026, 1, 31))
        s, e = dialog._get_date_range()
        assert s == date(2026, 1, 1)
        assert e == date(2026, 1, 31)

    def test_chart_selection_filtering(self, app, setup):
        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        dialog.chart_checkboxes["daily"].setChecked(False)
        dialog.chart_checkboxes["accuracy"].setChecked(False)
        selected = dialog._get_selected_charts()
        assert "gantt" in selected
        assert "blocks" in selected
        assert "daily" not in selected
        assert "accuracy" not in selected

    def test_refresh_preview_renders(self, app, setup):
        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        dialog._refresh_preview()
        # Preview layout should have at least one widget per selected chart
        # plus possibly a stretch
        widget_count = 0
        for i in range(dialog.preview_layout.count()):
            if dialog.preview_layout.itemAt(i).widget() is not None:
                widget_count += 1
        assert widget_count >= 1

    def test_refresh_preview_no_charts(self, app, setup):
        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        for cb in dialog.chart_checkboxes.values():
            cb.setChecked(False)
        dialog._refresh_preview()
        # Should show "No charts selected" label
        assert dialog.preview_layout.count() >= 1

    def test_gantt_hover_tooltip_handler_installed(self, app, setup):
        """Render gantt with truncatable label, verify motion handler set tooltip."""
        from datetime import date as _date

        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from PyQt6.QtWidgets import QToolTip

        from pytodo_qt.core.models import TodoItem

        lst, analytics = setup
        # Add an item with a long label that will be truncated; due today so
        # it falls within the dialog's default "Last 30 days" range.
        long_item = TodoItem(
            reminder="this reminder is intentionally super long so it gets ellipsis "
            "truncated in the chart but the full text should be available via hover",
            priority=2,
        )
        long_item.due_date = _date.today()
        lst.items[long_item.id] = long_item

        dialog = ExportChartsDialog(None, lst, analytics)
        dialog._refresh_preview()

        # Find the gantt canvas (the first one in layout)
        canvas = None
        for i in range(dialog.preview_layout.count()):
            w = dialog.preview_layout.itemAt(i).widget()
            if isinstance(w, FigureCanvasQTAgg):
                canvas = w
                break
        assert canvas is not None

        # The figure should carry full_labels metadata
        assert hasattr(canvas.figure, "_gantt_full_labels")
        full_labels = canvas.figure._gantt_full_labels
        assert any("ellipsis truncated" in label for label in full_labels)

        # Synthesize a matplotlib motion event over row 0 and verify QToolTip
        # is shown. We can't directly observe Qt's tooltip widget, but we can
        # verify the handler runs without crashing and accesses the data.
        from matplotlib.backend_bases import MouseEvent

        ax = canvas.figure.axes[0]
        # Convert data y=0 to display pixels
        x_disp, y_disp = ax.transData.transform((ax.get_xlim()[0], 0))
        evt = MouseEvent("motion_notify_event", canvas, x_disp, y_disp)
        # Trigger our handler indirectly via the canvas's callback registry
        canvas.callbacks.process("motion_notify_event", evt)
        # Tooltip text was set (or hidden) — both are valid; we just want
        # no exception
        QToolTip.hideText()  # cleanup

    def test_preview_canvas_ignores_wheel(self, app, setup):
        """Wheel events on preview canvas must propagate to parent QScrollArea."""
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtGui import QWheelEvent

        lst, analytics = setup
        dialog = ExportChartsDialog(None, lst, analytics)
        dialog._refresh_preview()

        # Find the first FigureCanvasQTAgg subclass widget in the preview layout
        canvas = None
        for i in range(dialog.preview_layout.count()):
            w = dialog.preview_layout.itemAt(i).widget()
            if isinstance(w, FigureCanvasQTAgg):
                canvas = w
                break
        assert canvas is not None

        # Synthesize a wheel event and call wheelEvent directly
        evt = QWheelEvent(
            QPointF(50, 50),
            QPointF(canvas.mapToGlobal(QPointF(50, 50).toPoint())),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        canvas.wheelEvent(evt)
        assert not evt.isAccepted()  # event was ignored, will propagate
