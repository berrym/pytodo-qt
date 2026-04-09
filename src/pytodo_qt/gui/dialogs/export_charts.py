"""export_charts.py

Dialog for exporting analytics charts as PNG or multi-page PDF.

Provides date range selection, chart inclusion checkboxes, and a live
matplotlib preview embedded in the dialog so users can see exactly
what they'll get before saving.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.logger import Logger

if TYPE_CHECKING:
    from ...core.analytics import AnalyticsService
    from ...core.models import TodoList

logger = Logger(__name__)


class ExportChartsDialog(QDialog):
    """Dialog with date range, chart selection, and live preview."""

    CHART_KEYS = ["gantt", "daily", "blocks", "accuracy"]
    CHART_LABELS = {
        "gantt": "Tasks Timeline (Gantt)",
        "daily": "Daily Activity",
        "blocks": "Time Block Productivity",
        "accuracy": "Estimate Accuracy",
    }

    def __init__(
        self,
        parent,
        active_list: TodoList,
        analytics: AnalyticsService,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export Charts"))
        self.setMinimumSize(900, 700)

        self._active_list = active_list
        self._analytics = analytics
        self._current_figure = None
        self._canvas = None

        self._setup_ui()
        self._refresh_preview()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- Top: Date range + Chart selection ---
        top_row = QHBoxLayout()

        # Date range group
        range_group = QGroupBox(self.tr("Date Range"))
        range_form = QFormLayout(range_group)

        self.preset_combo = QComboBox()
        self.preset_combo.addItem(self.tr("Last 7 days"), 7)
        self.preset_combo.addItem(self.tr("Last 30 days"), 30)
        self.preset_combo.addItem(self.tr("Last 90 days"), 90)
        self.preset_combo.addItem(self.tr("This month"), "month")
        self.preset_combo.addItem(self.tr("All time"), "all")
        self.preset_combo.addItem(self.tr("Custom"), "custom")
        self.preset_combo.setCurrentIndex(1)  # Default Last 30 days
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        range_form.addRow(self.tr("Preset:"), self.preset_combo)

        today = QDate.currentDate()
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(today.addDays(-29))
        range_form.addRow(self.tr("Start:"), self.start_date_edit)

        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(today)
        range_form.addRow(self.tr("End:"), self.end_date_edit)

        top_row.addWidget(range_group, 1)

        # Chart selection group
        chart_group = QGroupBox(self.tr("Charts to Include"))
        chart_layout = QVBoxLayout(chart_group)
        self.chart_checkboxes: dict[str, QCheckBox] = {}
        for key in self.CHART_KEYS:
            cb = QCheckBox(self.tr(self.CHART_LABELS[key]))
            cb.setChecked(True)
            self.chart_checkboxes[key] = cb
            chart_layout.addWidget(cb)
        chart_layout.addStretch()
        top_row.addWidget(chart_group, 1)

        layout.addLayout(top_row)

        # --- Refresh button ---
        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        self.refresh_btn = QPushButton(self.tr("Refresh Preview"))
        self.refresh_btn.clicked.connect(self._refresh_preview)
        refresh_row.addWidget(self.refresh_btn)
        layout.addLayout(refresh_row)

        # --- Preview area ---
        preview_group = QGroupBox(self.tr("Preview"))
        preview_layout = QVBoxLayout(preview_group)

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_container = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_scroll.setWidget(self.preview_container)
        preview_layout.addWidget(self.preview_scroll)

        layout.addWidget(preview_group, 1)

        # --- Buttons ---
        btn_box = QDialogButtonBox()
        self.export_pdf_btn = QPushButton(self.tr("Export PDF Report..."))
        self.export_pdf_btn.clicked.connect(self._on_export_pdf)
        btn_box.addButton(self.export_pdf_btn, QDialogButtonBox.ButtonRole.AcceptRole)

        self.export_png_btn = QPushButton(self.tr("Export Current Chart as PNG..."))
        self.export_png_btn.clicked.connect(self._on_export_png)
        btn_box.addButton(self.export_png_btn, QDialogButtonBox.ButtonRole.AcceptRole)

        cancel_btn = QPushButton(self.tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_box.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)

        layout.addWidget(btn_box)

    def _on_preset_changed(self, idx: int) -> None:
        data = self.preset_combo.itemData(idx)
        today = QDate.currentDate()
        if data == "custom":
            return
        if data == "all":
            self.start_date_edit.setDate(QDate(2000, 1, 1))
            self.end_date_edit.setDate(today)
        elif data == "month":
            first = QDate(today.year(), today.month(), 1)
            self.start_date_edit.setDate(first)
            self.end_date_edit.setDate(today)
        elif isinstance(data, int):
            self.start_date_edit.setDate(today.addDays(-(data - 1)))
            self.end_date_edit.setDate(today)
        self._refresh_preview()

    def _get_date_range(self) -> tuple[date, date]:
        s = self.start_date_edit.date()
        e = self.end_date_edit.date()
        return date(s.year(), s.month(), s.day()), date(e.year(), e.month(), e.day())

    def _get_selected_charts(self) -> set[str]:
        return {key for key, cb in self.chart_checkboxes.items() if cb.isChecked()}

    def _refresh_preview(self) -> None:
        """Re-render selected charts and embed in the preview area."""
        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

            from ...core.chart_export import (
                MatplotlibUnavailable,
                render_accuracy,
                render_daily_activity,
                render_gantt,
                render_time_blocks,
            )
        except ImportError as e:
            self._show_preview_error(str(e))
            return

        # Clear existing preview widgets
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        start_date, end_date = self._get_date_range()
        selected = self._get_selected_charts()
        items = list(self._active_list.active_items())

        renderers = {
            "gantt": lambda: render_gantt(items, start_date=start_date, end_date=end_date),
            "daily": lambda: render_daily_activity(
                self._analytics, start_date=start_date, end_date=end_date
            ),
            "blocks": lambda: render_time_blocks(
                self._analytics, start_date=start_date, end_date=end_date
            ),
            "accuracy": lambda: render_accuracy(
                self._analytics,
                list_id=self._active_list.id,
                start_date=start_date,
                end_date=end_date,
            ),
        }

        any_rendered = False
        for key in self.CHART_KEYS:
            if key not in selected:
                continue
            try:
                fig = renderers[key]()
            except MatplotlibUnavailable as e:
                self._show_preview_error(str(e))
                return
            except Exception as e:
                logger.log.exception("Failed to render %s chart", key)
                self._show_preview_error(f"Failed to render {key}: {e}")
                continue
            canvas = FigureCanvasQTAgg(fig)
            canvas.setMinimumHeight(300)
            self.preview_layout.addWidget(canvas)
            any_rendered = True
            if self._current_figure is None:
                self._current_figure = fig

        if not any_rendered:
            label = QLabel(self.tr("No charts selected."))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_layout.addWidget(label)

        self.preview_layout.addStretch()

    def _show_preview_error(self, msg: str) -> None:
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        label = QLabel(msg)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet("color: #ef4444; padding: 20px;")
        self.preview_layout.addWidget(label)

    def _on_export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export PDF Report"),
            f"{self._active_list.name}-charts.pdf",
            self.tr("PDF Files (*.pdf);;All Files (*)"),
        )
        if not path:
            return

        try:
            from ...core.chart_export import MatplotlibUnavailable, export_pdf_report

            start_date, end_date = self._get_date_range()
            items = list(self._active_list.active_items())
            export_pdf_report(
                self._analytics,
                items,
                path,
                list_id=self._active_list.id,
                start_date=start_date,
                end_date=end_date,
                include=self._get_selected_charts(),
            )
        except MatplotlibUnavailable as e:
            QMessageBox.critical(self, self.tr("Export Error"), str(e))
            return
        except Exception as e:
            logger.log.exception("PDF export failed")
            QMessageBox.critical(
                self, self.tr("Export Error"), self.tr(f"Could not export PDF:\n{e}")
            )
            return

        QMessageBox.information(
            self, self.tr("Export Complete"), self.tr(f"Saved to {Path(path).name}")
        )
        self.accept()

    def _on_export_png(self) -> None:
        """Export the first selected chart as a PNG."""
        selected = self._get_selected_charts()
        if not selected:
            QMessageBox.warning(
                self, self.tr("Export"), self.tr("Select at least one chart to export.")
            )
            return

        # Pick the first selected chart in canonical order
        key = next((k for k in self.CHART_KEYS if k in selected), None)
        if key is None:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export PNG"),
            f"{self._active_list.name}-{key}.png",
            self.tr("PNG Files (*.png);;All Files (*)"),
        )
        if not path:
            return

        try:
            from ...core.chart_export import (
                MatplotlibUnavailable,
                export_png,
                render_accuracy,
                render_daily_activity,
                render_gantt,
                render_time_blocks,
            )

            start_date, end_date = self._get_date_range()
            items = list(self._active_list.active_items())
            renderers = {
                "gantt": lambda: render_gantt(items, start_date=start_date, end_date=end_date),
                "daily": lambda: render_daily_activity(
                    self._analytics, start_date=start_date, end_date=end_date
                ),
                "blocks": lambda: render_time_blocks(
                    self._analytics, start_date=start_date, end_date=end_date
                ),
                "accuracy": lambda: render_accuracy(
                    self._analytics,
                    list_id=self._active_list.id,
                    start_date=start_date,
                    end_date=end_date,
                ),
            }
            fig = renderers[key]()
            export_png(fig, path)
        except MatplotlibUnavailable as e:
            QMessageBox.critical(self, self.tr("Export Error"), str(e))
            return
        except Exception as e:
            logger.log.exception("PNG export failed")
            QMessageBox.critical(
                self, self.tr("Export Error"), self.tr(f"Could not export PNG:\n{e}")
            )
            return

        QMessageBox.information(
            self, self.tr("Export Complete"), self.tr(f"Saved to {Path(path).name}")
        )
        self.accept()
