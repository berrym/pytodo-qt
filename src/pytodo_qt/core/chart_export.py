"""chart_export.py

Matplotlib-based chart rendering for PNG and PDF export.

Provides publication-quality renders of the four timeline analytics charts:
Tasks/Gantt, Daily Activity, Time Block Productivity, and Estimate Accuracy.

All render functions accept optional start_date/end_date for filtering.
Figures are created via matplotlib.figure.Figure (no pyplot), so they can
be embedded in Qt widgets or saved headlessly without backend conflicts.

Matplotlib is an optional dependency — install with `pytodo-qt[export]`.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .analytics import AnalyticsService
    from .models import TodoItem


class MatplotlibUnavailable(RuntimeError):
    """Raised when matplotlib is not installed."""


def _import_matplotlib():
    """Import matplotlib lazily so it stays optional. Returns (Figure, PdfPages)."""
    try:
        # Silence matplotlib's chatty findfont/PDF backend DEBUG logs.
        # These flood stdout when our app is run with DEBUG-level logging.
        import logging as _logging

        _logging.getLogger("matplotlib").setLevel(_logging.WARNING)
        _logging.getLogger("matplotlib.font_manager").setLevel(_logging.WARNING)
        _logging.getLogger("matplotlib.backends.backend_pdf").setLevel(_logging.WARNING)

        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.figure import Figure

        return Figure, PdfPages
    except ImportError as e:
        raise MatplotlibUnavailable(
            "matplotlib is not installed. Install with: pip install pytodo-qt[export]"
        ) from e


def _filter_items_by_date(
    items: list[TodoItem],
    start_date: date | None,
    end_date: date | None,
) -> list[TodoItem]:
    """Keep items whose due_date falls within [start_date, end_date]."""
    if start_date is None and end_date is None:
        return items
    out = []
    for item in items:
        if item.due_date is None:
            continue
        if start_date and item.due_date < start_date:
            continue
        if end_date and item.due_date > end_date:
            continue
        out.append(item)
    return out


def render_gantt(
    items: list[TodoItem],
    today: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Render a Gantt chart of items with due dates.

    Returns a matplotlib Figure.
    """
    Figure, _ = _import_matplotlib()

    if today is None:
        today = date.today()

    due_items = [i for i in items if i.due_date is not None]
    due_items = _filter_items_by_date(due_items, start_date, end_date)
    due_items.sort(key=lambda i: i.due_date or date.max)
    due_items = due_items[:30]

    fig = Figure(figsize=(10, max(4, len(due_items) * 0.3)))
    ax = fig.add_subplot(111)

    if not due_items:
        ax.text(0.5, 0.5, "No items with due dates", ha="center", va="center", fontsize=12)
        ax.set_axis_off()
        return fig

    for idx, item in enumerate(due_items):
        from datetime import datetime as _dt

        created = _dt.fromtimestamp(item.created_at / 1000).date() if item.created_at else today
        due = item.due_date
        if due is None:
            continue
        duration_days = max((due - created).days, 1)
        color = "#10b981" if item.complete else "#3b82f6"
        ax.barh(idx, duration_days, left=created.toordinal(), color=color, alpha=0.7)
        label = (item.reminder or "")[:30]
        ax.text(created.toordinal() - 0.5, idx, label, ha="right", va="center", fontsize=9)

    ax.axvline(today.toordinal(), color="#ef4444", linestyle="--", linewidth=1, label="Today")
    ax.set_yticks([])
    ax.set_xlabel("Date")
    title = "Tasks Timeline (Gantt)"
    if start_date or end_date:
        s = start_date.isoformat() if start_date else "*"
        e = end_date.isoformat() if end_date else "*"
        title += f"  [{s} → {e}]"
    ax.set_title(title)
    ax.legend(loc="upper right")

    xticks = ax.get_xticks()
    xtick_labels = []
    for t in xticks:
        try:
            xtick_labels.append(date.fromordinal(int(t)).strftime("%b %d"))
        except (ValueError, OverflowError):
            xtick_labels.append("")
    ax.set_xticks(xticks)
    ax.set_xticklabels(xtick_labels, rotation=45, ha="right")

    fig.tight_layout()
    return fig


def render_daily_activity(
    analytics: AnalyticsService,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Render a stacked bar chart of daily focus activity (pomodoro + stopwatch).

    If start_date/end_date are provided, they take precedence over `days`.
    Returns a matplotlib Figure.
    """
    Figure, _ = _import_matplotlib()

    if start_date is None or end_date is None:
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=days - 1))

    df = analytics.daily_summary(start_date=start_date.isoformat(), end_date=end_date.isoformat())

    fig = Figure(figsize=(10, 5))
    ax = fig.add_subplot(111)

    if df.empty:
        ax.text(0.5, 0.5, "No focus session data", ha="center", va="center", fontsize=12)
        ax.set_axis_off()
        return fig

    dates = df["date"].astype(str).tolist()
    work = df["work_minutes"].tolist()
    sw = df["stopwatch_minutes"].tolist()

    x = range(len(dates))
    ax.bar(x, work, color="#3b82f6", label="Pomodoro")
    ax.bar(x, sw, bottom=work, color="#10b981", label="Stopwatch")
    ax.set_xticks(list(x))
    ax.set_xticklabels(dates, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Minutes")
    ax.set_title(f"Daily Activity ({start_date.isoformat()} → {end_date.isoformat()})")
    ax.legend(loc="upper left")

    fig.tight_layout()
    return fig


def render_time_blocks(
    analytics: AnalyticsService,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Render a productivity heatmap of 12 two-hour time blocks.

    Note: time_block_analysis() uses all session data; date filter is
    applied to the title only for now (analytics method does not yet
    accept a date range).

    Returns a matplotlib Figure.
    """
    Figure, _ = _import_matplotlib()

    df = analytics.time_block_analysis()

    fig = Figure(figsize=(10, 5))
    ax = fig.add_subplot(111)

    if df.empty:
        ax.text(0.5, 0.5, "No focus session data", ha="center", va="center", fontsize=12)
        ax.set_axis_off()
        return fig

    labels = df["block_label"].tolist()
    pomo = df["pomodoro_minutes"].tolist()
    sw = df["stopwatch_minutes"].tolist()

    x = range(len(labels))
    ax.bar(x, pomo, color="#3b82f6", label="Pomodoro")
    ax.bar(x, sw, bottom=pomo, color="#10b981", label="Stopwatch")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Minutes")
    title = "Productivity by Time of Day"
    if start_date or end_date:
        s = start_date.isoformat() if start_date else "*"
        e = end_date.isoformat() if end_date else "*"
        title += f"  [{s} → {e}]"
    ax.set_title(title)
    ax.legend(loc="upper right")

    fig.tight_layout()
    return fig


def render_accuracy(
    analytics: AnalyticsService,
    list_id=None,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Render an estimate vs actual scatter plot with reference line.

    Returns a matplotlib Figure.
    """
    Figure, _ = _import_matplotlib()

    df = analytics.estimate_accuracy(list_id=list_id)

    fig = Figure(figsize=(7, 7))
    ax = fig.add_subplot(111)

    if df.empty:
        ax.text(
            0.5,
            0.5,
            "No items with both estimate and tracked time",
            ha="center",
            va="center",
            fontsize=12,
        )
        ax.set_axis_off()
        return fig

    est = df["estimated_minutes"].tolist()
    actual = df["actual_minutes"].tolist()
    ratios = df["accuracy_ratio"].tolist()

    colors = []
    for r in ratios:
        if r < 0.8:
            colors.append("#ef4444")
        elif r > 1.2:
            colors.append("#f59e0b")
        else:
            colors.append("#10b981")

    ax.scatter(est, actual, c=colors, s=60, alpha=0.7, edgecolors="white")

    max_val = max(max(est, default=1), max(actual, default=1)) * 1.1
    ax.plot([0, max_val], [0, max_val], "--", color="#888", label="Perfect estimate")

    ax.set_xlabel("Estimated (minutes)")
    ax.set_ylabel("Actual (minutes)")
    title = "Estimate Accuracy"
    if start_date or end_date:
        s = start_date.isoformat() if start_date else "*"
        e = end_date.isoformat() if end_date else "*"
        title += f"  [{s} → {e}]"
    ax.set_title(title)
    ax.legend(loc="upper left")
    ax.set_xlim(0, max_val)
    ax.set_ylim(0, max_val)

    fig.tight_layout()
    return fig


def export_png(figure, path: str | Path) -> None:
    """Save a matplotlib figure as PNG."""
    figure.savefig(str(path), dpi=150, bbox_inches="tight")


def export_pdf_report(
    analytics: AnalyticsService,
    items: list[TodoItem],
    path: str | Path,
    list_id=None,
    start_date: date | None = None,
    end_date: date | None = None,
    include: set[str] | None = None,
) -> None:
    """Export a multi-page PDF report containing the selected charts.

    `include` is a set of chart keys to include: {"gantt", "daily", "blocks", "accuracy"}.
    If None, all four charts are included.
    """
    _, PdfPages = _import_matplotlib()

    if include is None:
        include = {"gantt", "daily", "blocks", "accuracy"}

    chart_specs = [
        ("gantt", lambda: render_gantt(items, start_date=start_date, end_date=end_date)),
        (
            "daily",
            lambda: render_daily_activity(analytics, start_date=start_date, end_date=end_date),
        ),
        (
            "blocks",
            lambda: render_time_blocks(analytics, start_date=start_date, end_date=end_date),
        ),
        (
            "accuracy",
            lambda: render_accuracy(
                analytics, list_id=list_id, start_date=start_date, end_date=end_date
            ),
        ),
    ]

    with PdfPages(str(path)) as pdf:
        for key, renderer in chart_specs:
            if key not in include:
                continue
            fig = renderer()
            pdf.savefig(fig)
