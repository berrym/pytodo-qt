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
