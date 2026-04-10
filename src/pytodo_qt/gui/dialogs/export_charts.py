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


def _make_preview_canvas_class():
    """Build _PreviewCanvas lazily so matplotlib import stays optional.

    Returns a FigureCanvasQTAgg subclass that propagates wheel events to the
    parent QScrollArea (instead of matplotlib's default behavior of emitting
    a scroll_event for zoom and swallowing the Qt event).
    """
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

    class _PreviewCanvas(FigureCanvasQTAgg):
        """FigureCanvasQTAgg that lets wheel events bubble up to parents."""

        def wheelEvent(self, event) -> None:  # noqa: N802
            # event.ignore() lets Qt propagate the wheel to the enclosing
            # QScrollArea so standard trackpad/mouse-wheel scrolling works.
            if event is not None:
                event.ignore()

    return _PreviewCanvas


_PreviewCanvas = None  # lazily initialized on first preview refresh


def _install_gantt_hover_tooltips(canvas, full_labels: list[str]) -> None:
    """Show the full untruncated reminder as a Qt tooltip when hovering over
    any y-row of the Gantt — including the y-label gutter outside the plot.

    Uses QToolTip.showText() directly (bypassing the standard hover delay)
    so the tooltip appears immediately as the cursor moves between rows.
    Maps cursor pixel y to the row index via the axes' data transform, which
    works even when the cursor is to the left of the plot area (over the
    truncated labels).
    """
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QToolTip

    def on_motion(event) -> None:
        if event.x is None or event.y is None:
            QToolTip.hideText()
            return
        if not canvas.figure.axes:
            return
        ax = canvas.figure.axes[0]
        try:
            _, data_y = ax.transData.inverted().transform((event.x, event.y))
        except Exception:
            QToolTip.hideText()
            return
        idx = int(round(data_y))
        if 0 <= idx < len(full_labels):
            QToolTip.showText(QCursor.pos(), full_labels[idx], canvas)
        else:
            QToolTip.hideText()

    def on_leave(_event) -> None:
        QToolTip.hideText()

    canvas.mpl_connect("motion_notify_event", on_motion)
    canvas.mpl_connect("axes_leave_event", on_leave)
    canvas.mpl_connect("figure_leave_event", on_leave)


class ExportChartsDialog(QDialog):
    """Dialog with date range, chart selection, and live preview."""

    CHART_KEYS = ["gantt", "daily", "blocks", "accuracy", "timing"]
    CHART_LABELS = {
        "gantt": "Tasks Timeline (Gantt)",
        "daily": "Daily Activity",
        "blocks": "Time Block Productivity",
        "accuracy": "Estimate Accuracy",
        "timing": "Completion Timing",
    }

    def __init__(
        self,
        parent,
        active_list: TodoList,
        analytics: AnalyticsService,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export Charts"))
        self.setMinimumSize(1100, 800)
        self.resize(1200, 900)

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
        global _PreviewCanvas
        try:
            from ...core.chart_export import (
                MatplotlibUnavailable,
                render_accuracy,
                render_completion_timing,
                render_daily_activity,
                render_gantt,
                render_time_blocks,
            )

            if _PreviewCanvas is None:
                _PreviewCanvas = _make_preview_canvas_class()
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
            "timing": lambda: render_completion_timing(
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
            canvas = _PreviewCanvas(fig)
            # Give each chart enough vertical room — figsize is in inches at 100 DPI
            inches_h = fig.get_size_inches()[1]
            canvas.setMinimumHeight(int(inches_h * 100))
            canvas.setMinimumWidth(800)

            # Hover tooltips for Gantt: show full untruncated reminder when
            # the mouse is over a y-row (useful when labels are ellipsis-cut)
            full_labels = getattr(fig, "_gantt_full_labels", None)
            if full_labels:
                _install_gantt_hover_tooltips(canvas, full_labels)
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
                render_completion_timing,
                render_daily_activity,
                render_gantt,
                render_time_blocks,
            )

            start_date, end_date = self._get_date_range()
            items = list(self._active_list.active_items())
            renderers = {
                "gantt": lambda: render_gantt(
                    items,
                    start_date=start_date,
                    end_date=end_date,
                    include_full_legend=True,  # zero data loss in exported PNG
                ),
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
                "timing": lambda: render_completion_timing(
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
