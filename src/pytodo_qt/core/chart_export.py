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

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .analytics import AnalyticsService
    from .models import TodoItem


# ---------------------------------------------------------------------------
# Style: a clean, modern, publication-quality look
# ---------------------------------------------------------------------------

# Distinct professional palette (color-blind safe)
_COLOR_PRIMARY = "#2563eb"  # blue
_COLOR_SECONDARY = "#059669"  # green
_COLOR_ACCENT = "#d97706"  # amber
_COLOR_DANGER = "#dc2626"  # red
_COLOR_NEUTRAL = "#6b7280"  # gray
_COLOR_GRID = "#e5e7eb"  # light gray
_COLOR_TEXT = "#111827"  # near-black
_COLOR_TEXT_MUTED = "#6b7280"

_RC_PARAMS: dict = {
    "figure.facecolor": "white",
    "figure.dpi": 100,
    "axes.facecolor": "white",
    "axes.edgecolor": _COLOR_NEUTRAL,
    "axes.linewidth": 0.8,
    "axes.labelcolor": _COLOR_TEXT,
    "axes.titlecolor": _COLOR_TEXT_MUTED,
    "axes.titlesize": 11,
    "axes.titleweight": "normal",
    "axes.titlelocation": "left",
    "axes.titlepad": 10,
    "axes.labelsize": 11,
    "axes.labelpad": 8,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "grid.color": _COLOR_GRID,
    "grid.linewidth": 0.8,
    "grid.linestyle": "-",
    "xtick.color": _COLOR_TEXT_MUTED,
    "ytick.color": _COLOR_TEXT_MUTED,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "legend.frameon": False,
    "font.family": "sans-serif",
    "font.size": 11,
    "figure.titlesize": 15,
    "figure.titleweight": "bold",
}


class MatplotlibUnavailable(RuntimeError):
    """Raised when matplotlib is not installed."""


def _import_matplotlib():
    """Import matplotlib lazily. Returns (Figure, PdfPages, mdates)."""
    try:
        # Silence matplotlib's chatty findfont/PDF backend DEBUG logs.
        import logging as _logging

        _logging.getLogger("matplotlib").setLevel(_logging.WARNING)
        _logging.getLogger("matplotlib.font_manager").setLevel(_logging.WARNING)
        _logging.getLogger("matplotlib.backends.backend_pdf").setLevel(_logging.WARNING)

        import matplotlib.dates as mdates
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.figure import Figure

        return Figure, PdfPages, mdates
    except ImportError as e:
        raise MatplotlibUnavailable(
            "matplotlib is not installed. Install with: pip install pytodo-qt[export]"
        ) from e


def _make_figure(
    figsize: tuple[float, float],
    *,
    has_legend_right: bool = False,
    extra_bottom: float = 0.0,
    left_margin: float = 0.10,
):
    """Create a Figure with project rcParams and explicit margins.

    Uses subplots_adjust (not constrained_layout) so we have predictable
    pixel-perfect control over the title area at the top of the figure.

    Args:
        figsize: figure size in inches
        has_legend_right: reserve more right margin for an outside legend
        extra_bottom: additional bottom margin for rotated x-tick labels
        left_margin: left margin (default 0.10 = 10% of figure width)
    """
    import contextlib

    Figure, _, _ = _import_matplotlib()

    # Apply rcParams BEFORE creating the figure so it picks them up.
    from matplotlib import rcParams as _rc

    for key, value in _RC_PARAMS.items():
        with contextlib.suppress(KeyError, ValueError):
            _rc[key] = value

    fig = Figure(figsize=figsize, dpi=100)
    # Reserved top area for chart title + date subtitle (~14% of fig height)
    top = 0.86
    bottom = 0.14 + extra_bottom
    right = 0.78 if has_legend_right else 0.96
    fig.subplots_adjust(left=left_margin, right=right, top=top, bottom=bottom)
    return fig


def _set_title_with_subtitle(
    fig,
    ax,  # noqa: ARG001 — kept for signature symmetry
    title: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> None:
    """Draw chart title + date subtitle in the reserved top area of the figure.

    Both texts use absolute figure coordinates with explicit y positions so
    they never overlap regardless of figure size or content. Coordinates are
    chosen to sit ABOVE the axes top (which lives at y=0.86 per _make_figure).
    """
    # Chart title — larger, bold, dark
    fig.text(
        0.05,
        0.945,
        title,
        fontsize=15,
        fontweight="bold",
        color=_COLOR_TEXT,
        ha="left",
        va="center",
    )
    # Date range subtitle — smaller, muted, on its own line below the title
    if start_date or end_date:
        s = start_date.strftime("%b %d, %Y") if start_date else "—"
        e = end_date.strftime("%b %d, %Y") if end_date else "—"
        fig.text(
            0.05,
            0.895,
            f"{s}  →  {e}",
            fontsize=10,
            color=_COLOR_TEXT_MUTED,
            ha="left",
            va="center",
        )


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


def _empty_figure(title: str, message: str):
    fig = _make_figure((11, 5.5))
    ax = fig.add_subplot(111)
    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        fontsize=13,
        color=_COLOR_TEXT_MUTED,
        transform=ax.transAxes,
    )
    ax.set_axis_off()
    fig.text(
        0.05,
        0.945,
        title,
        fontsize=15,
        fontweight="bold",
        color=_COLOR_TEXT,
        ha="left",
        va="center",
    )
    return fig


# ---------------------------------------------------------------------------
# Gantt timeline
# ---------------------------------------------------------------------------

# Maximum fraction of figure width we'll reserve for y-tick labels before we
# start truncating. Beyond this the bars get too cramped to be useful, and
# truncation is the right tradeoff.
_GANTT_LABEL_MAX_FRACTION = 0.32
# Padding in points around the label column
_GANTT_LABEL_PAD_POINTS = 14


def _measure_label_widths(fig, labels: list[str], fontsize: int = 10) -> list[float]:
    """Return pixel widths of each label after a temporary render.

    Attaches an Agg canvas to the figure so we can get a real renderer,
    measures each Text object's bounding box, and returns widths in pixels.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.text import Text

    # Attach an Agg canvas so the figure has a renderer.
    # The caller's dialog will replace this with FigureCanvasQTAgg later if
    # the figure is embedded in Qt — that's a supported replacement.
    FigureCanvasAgg(fig)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    widths = []
    for label in labels:
        t = Text(0, 0, label, fontsize=fontsize, figure=fig)
        bbox = t.get_window_extent(renderer=renderer)
        widths.append(bbox.width)
    return widths


def _truncate_to_width(label: str, max_width_px: float, fig, fontsize: int = 10) -> str:
    """Truncate `label` with an ellipsis so its rendered width ≤ max_width_px."""
    from matplotlib.text import Text

    renderer = fig.canvas.get_renderer()

    def measure(s: str) -> float:
        t = Text(0, 0, s, fontsize=fontsize, figure=fig)
        return t.get_window_extent(renderer=renderer).width

    if measure(label) <= max_width_px:
        return label

    ellipsis = "…"
    # Binary search on truncation length
    lo, hi = 1, len(label)
    best = ellipsis
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = label[:mid].rstrip() + ellipsis
        if measure(candidate) <= max_width_px:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def render_gantt(
    items: list[TodoItem],
    today: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    include_full_legend: bool = False,
):
    """Horizontal Gantt chart of items with due dates.

    Args:
        items: list of TodoItems; only those with due_date are plotted
        today: override for today (for testing)
        start_date, end_date: optional date range filter
        include_full_legend: when True, append a numbered list of full (un-
            truncated) task reminders below the chart. Used for PNG/PDF
            export so no information is lost even when the in-chart labels
            are ellipsis-truncated.
    """
    _, _, mdates = _import_matplotlib()

    if today is None:
        today = date.today()

    due_items = [i for i in items if i.due_date is not None]
    due_items = _filter_items_by_date(due_items, start_date, end_date)
    due_items.sort(key=lambda i: i.due_date or date.max, reverse=True)
    due_items = due_items[:25]

    if not due_items:
        return _empty_figure("Tasks Timeline", "No items with due dates in this range")

    # Full (untruncated) reminder text, kept for the optional legend below
    full_labels = [(i.reminder or "") for i in due_items]

    # ------------------------------------------------------------------
    # Figure sizing
    # ------------------------------------------------------------------
    chart_h = max(5.5, min(14.0, 1.5 + len(due_items) * 0.42))
    legend_h = 0.0
    if include_full_legend:
        # ~0.22 inches per legend row + a small header padding
        legend_h = 0.6 + len(due_items) * 0.22

    fig_w = 12.0
    fig_h = chart_h + legend_h

    # Start with a placeholder left margin; the two-pass measurement below
    # replaces it with a fitted value.
    fig = _make_figure((fig_w, fig_h), left_margin=0.08)
    ax = fig.add_subplot(111)

    # If we have a bottom legend, reserve space for it by shrinking the
    # chart's bottom edge. The legend gets drawn via fig.text() below.
    if include_full_legend:
        legend_top_fraction = legend_h / fig_h
        # chart_bottom sits above the legend area with a small gap
        chart_bottom = legend_top_fraction + 0.03
        fig.subplots_adjust(bottom=chart_bottom)

    # ------------------------------------------------------------------
    # Two-pass label measurement + dynamic margin + ellipsis truncation
    # ------------------------------------------------------------------
    fig_width_px = fig_w * fig.get_dpi()
    cap_px = fig_width_px * _GANTT_LABEL_MAX_FRACTION - _GANTT_LABEL_PAD_POINTS

    widths = _measure_label_widths(fig, full_labels, fontsize=10)
    max_width_px = max(widths) if widths else 0

    if max_width_px <= cap_px:
        # Everything fits — use the natural width plus padding
        needed_px = max_width_px + _GANTT_LABEL_PAD_POINTS
        display_labels = list(full_labels)
    else:
        # At least one label overflows the cap — truncate those that do
        needed_px = cap_px + _GANTT_LABEL_PAD_POINTS
        display_labels = []
        for lbl, w in zip(full_labels, widths, strict=True):
            if w <= cap_px:
                display_labels.append(lbl)
            else:
                display_labels.append(_truncate_to_width(lbl, cap_px, fig))

    left_fraction = max(0.06, min(_GANTT_LABEL_MAX_FRACTION + 0.02, needed_px / fig_width_px))
    fig.subplots_adjust(left=left_fraction)

    # Expose full labels on the figure so interactive embedders (like the
    # Export Charts dialog's preview canvas) can show tooltips with the
    # untruncated text when the user hovers over a y-row.
    fig._gantt_full_labels = list(full_labels)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Draw bars — Q5 lifecycle visualization with two-zone deviation
    # ------------------------------------------------------------------
    # Use the calendar_layout pure functions for state classification so
    # the chart matches what the calendar UI shows for the same task.
    from .bar_palette import get_palette
    from .calendar_layout import (
        BarState,
        compute_bar_state,
        compute_bar_window,
    )

    palette = get_palette("light")  # chart export always uses light theme
    today_dt = datetime.combine(today, datetime.min.time())
    today_num = mdates.date2num(today)

    # Pre-pass: classify every item, compute its bar window and the
    # mdates extent of every visual element it will produce. We need
    # the full x-axis range up front to enforce a minimum visible bar
    # width — otherwise a 25-minute task on a 16-day chart paints a
    # 1-pixel rectangle that's effectively invisible.
    bars: list[dict] = []
    x_min = today_num
    x_max = today_num
    for idx, item in enumerate(due_items):
        window = compute_bar_window(item)
        if window is None:
            continue
        origin_num = mdates.date2num(window.origin)
        end_num = mdates.date2num(window.end)
        if end_num <= origin_num:
            continue

        as_of = today_dt
        completed_num: float | None = None
        if item.complete and item.completed_at is not None:
            completed_dt = datetime.fromtimestamp(item.completed_at / 1000)
            as_of = completed_dt
            completed_num = mdates.date2num(completed_dt)
        state = compute_bar_state(item, window, as_of)

        bars.append(
            {
                "idx": idx,
                "state": state,
                "origin_num": origin_num,
                "end_num": end_num,
                "completed_num": completed_num,
            }
        )
        x_min = min(x_min, origin_num)
        x_max = max(x_max, end_num)
        if completed_num is not None:
            x_min = min(x_min, completed_num)
            x_max = max(x_max, completed_num)

    # Honour an explicit user date range as a lower bound on the
    # x-axis extent so the chart frame matches the export dialog
    # selection even when actual task data is narrower.
    if start_date is not None:
        x_min = min(x_min, mdates.date2num(start_date))
    if end_date is not None:
        x_max = max(x_max, mdates.date2num(end_date))

    x_range = max(x_max - x_min, 1.0)
    # 0.6 % of the chart's x-axis range is roughly seven pixels on a
    # 1200-pixel-wide figure — enough to register as a real shape
    # rather than a hairline. Sub-day tasks below this threshold get
    # painted at the minimum width with their left edge held at the
    # actual origin so the start-of-window position stays correct.
    min_visible_width = x_range * 0.006

    def _visible_width(actual: float) -> float:
        return max(actual, min_visible_width)

    for bar in bars:
        idx = bar["idx"]
        state = bar["state"]
        origin_num = bar["origin_num"]
        end_num = bar["end_num"]
        completed_num = bar["completed_num"]
        colors = palette[state]

        # The full planned span (origin → end) is always drawn.
        ax.barh(
            idx,
            _visible_width(end_num - origin_num),
            left=origin_num,
            color=colors.base,
            alpha=0.85,
            edgecolor="white",
            linewidth=0.5,
            height=0.65,
        )

        # Deviation zone for completed bars
        if state == BarState.COMPLETED_EARLY and completed_num is not None:
            # Early surplus: translucent deviation color from completed_at
            # to end. Communicates "this time was allocated but not used."
            if origin_num <= completed_num < end_num:
                # Overlay a lighter translucent rectangle over the surplus
                ax.barh(
                    idx,
                    _visible_width(end_num - completed_num),
                    left=completed_num,
                    color=colors.deviation,
                    alpha=0.45,
                    edgecolor="white",
                    linewidth=0.5,
                    height=0.65,
                )
        elif (
            state == BarState.COMPLETED_LATE
            and completed_num is not None
            and completed_num > end_num
        ):
            # Late overflow: hatched deviation zone from end to completed_at
            ax.barh(
                idx,
                _visible_width(completed_num - end_num),
                left=end_num,
                color=colors.deviation,
                alpha=0.85,
                edgecolor="white",
                linewidth=0.5,
                height=0.65,
                hatch="///",
            )

    ax.set_yticks(range(len(due_items)))
    ax.set_yticklabels(display_labels, fontsize=10)
    ax.invert_yaxis()

    # Lock the x-axis to the pre-computed extent so auto-scale doesn't
    # collapse the frame around the bars after they're drawn (which
    # would defeat the minimum-width math).
    ax.set_xlim(x_min, x_max)

    # Today marker
    ax.axvline(
        today_num,
        color=_COLOR_DANGER,
        linestyle="--",
        linewidth=1.2,
        alpha=0.7,
        zorder=0,
    )
    ax.text(
        mdates.date2num(today),
        -0.7,
        " Today",
        color=_COLOR_DANGER,
        fontsize=9,
        ha="left",
        va="bottom",
    )

    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_tick_params(rotation=0)

    ax.grid(True, axis="x", alpha=0.5)
    ax.grid(False, axis="y")

    _set_title_with_subtitle(fig, ax, "Tasks Timeline", start_date, end_date)

    from matplotlib.patches import Patch

    # Legend reflects every BarState that could appear, in lifecycle order.
    # Two-zone completed bars get their own deviation entries.
    legend_handles = [
        Patch(
            facecolor=palette[BarState.IN_WORK_WINDOW].base,
            alpha=0.85,
            label="In progress",
        ),
        Patch(
            facecolor=palette[BarState.DUE_NOW].base,
            alpha=0.85,
            label="Due soon",
        ),
        Patch(
            facecolor=palette[BarState.OVERDUE_ACTIVE].base,
            alpha=0.85,
            label="Overdue",
        ),
        Patch(
            facecolor=palette[BarState.COMPLETED_ONTIME].base,
            alpha=0.85,
            label="Completed",
        ),
        Patch(
            facecolor=palette[BarState.COMPLETED_EARLY].deviation,
            alpha=0.45,
            label="Early surplus",
        ),
        Patch(
            facecolor=palette[BarState.COMPLETED_LATE].deviation,
            alpha=0.85,
            hatch="///",
            label="Late overflow",
        ),
    ]
    ax.legend(handles=legend_handles, loc="lower right", framealpha=0.9, frameon=True)

    # ------------------------------------------------------------------
    # Optional: numbered full-text legend below the chart
    # ------------------------------------------------------------------
    if include_full_legend:
        header_y = legend_top_fraction - 0.01
        fig.text(
            0.05,
            header_y,
            "Full task reminders",
            fontsize=11,
            fontweight="bold",
            color=_COLOR_TEXT,
            ha="left",
            va="top",
        )
        # Each legend row — numbered, full untruncated text
        row_step = 0.22 / fig_h  # inches → figure fraction (0.22" per row)
        # Display order: match what the user sees in the chart (top-down)
        # ax.invert_yaxis() puts lowest idx at top — due_items is currently
        # reverse-sorted so index 0 is the latest due date (topmost).
        for i, text in enumerate(full_labels):
            y = header_y - 0.03 - i * row_step
            fig.text(
                0.05,
                y,
                f"{i + 1}.  {text}",
                fontsize=9,
                color=_COLOR_TEXT,
                ha="left",
                va="top",
            )

    return fig


# ---------------------------------------------------------------------------
# Daily activity (stacked bars)
# ---------------------------------------------------------------------------


def render_daily_activity(
    analytics: AnalyticsService,
    days: int = 30,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Stacked bar chart of daily focus activity (pomodoro + stopwatch)."""
    _, _, mdates = _import_matplotlib()

    if start_date is None or end_date is None:
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=days - 1))

    df = analytics.daily_summary(start_date=start_date.isoformat(), end_date=end_date.isoformat())

    if df.empty:
        return _empty_figure("Daily Activity", "No focus session data in this range")

    # Wider figure for date axes
    fig = _make_figure((12, 6))
    ax = fig.add_subplot(111)

    # Convert ISO strings to dates for proper date axis
    dates = [date.fromisoformat(s) for s in df["date"].astype(str).tolist()]
    work = df["work_minutes"].tolist()
    sw = df["stopwatch_minutes"].tolist()

    width = 0.85  # day width
    ax.bar(dates, work, width=width, color=_COLOR_PRIMARY, label="Pomodoro", edgecolor="white")
    ax.bar(
        dates,
        sw,
        width=width,
        bottom=work,
        color=_COLOR_SECONDARY,
        label="Stopwatch",
        edgecolor="white",
    )

    ax.set_ylabel("Minutes")
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_tick_params(rotation=0)

    _set_title_with_subtitle(fig, ax, "Daily Activity", start_date, end_date)
    ax.legend(loc="upper left", frameon=True, framealpha=0.9)

    return fig


# ---------------------------------------------------------------------------
# Time block productivity
# ---------------------------------------------------------------------------


def render_time_blocks(
    analytics: AnalyticsService,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Stacked bar chart of productivity by 2-hour time block."""
    _, _, _ = _import_matplotlib()

    df = analytics.time_block_analysis()

    if df.empty:
        return _empty_figure("Productivity by Time of Day", "No focus session data")

    # Rotated x-labels need extra bottom padding so they don't get clipped
    fig = _make_figure((12, 6), extra_bottom=0.06)
    ax = fig.add_subplot(111)

    labels = df["block_label"].tolist()
    pomo = df["pomodoro_minutes"].tolist()
    sw = df["stopwatch_minutes"].tolist()

    x = list(range(len(labels)))
    ax.bar(x, pomo, color=_COLOR_PRIMARY, label="Pomodoro", edgecolor="white", width=0.7)
    ax.bar(
        x,
        sw,
        bottom=pomo,
        color=_COLOR_SECONDARY,
        label="Stopwatch",
        edgecolor="white",
        width=0.7,
    )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=9)
    ax.set_ylabel("Minutes")
    ax.set_xlabel("Time of Day (2-hour blocks)")

    _set_title_with_subtitle(fig, ax, "Productivity by Time of Day", start_date, end_date)
    ax.legend(loc="upper right", frameon=True, framealpha=0.9)

    return fig


# ---------------------------------------------------------------------------
# Estimate accuracy scatter
# ---------------------------------------------------------------------------


def render_accuracy(
    analytics: AnalyticsService,
    list_id=None,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Estimate vs actual scatter plot with reference line."""
    _, _, _ = _import_matplotlib()

    df = analytics.estimate_accuracy(list_id=list_id)

    if df.empty:
        return _empty_figure("Estimate Accuracy", "No items with both an estimate and tracked time")

    # Square aspect for scatter, with extra height for title clearance
    fig = _make_figure((8.5, 8.5))
    ax = fig.add_subplot(111)

    est = df["estimated_minutes"].tolist()
    actual = df["actual_minutes"].tolist()
    ratios = df["accuracy_ratio"].tolist()

    # Bucket points by accuracy category for legend grouping
    over_est = ([], [])  # actual < est * 0.8 (over-estimated work)
    accurate = ([], [])  # 0.8 <= ratio <= 1.2
    under_est = ([], [])  # actual > est * 1.2 (under-estimated work)
    for e_v, a_v, r in zip(est, actual, ratios, strict=True):
        if r < 0.8:
            over_est[0].append(e_v)
            over_est[1].append(a_v)
        elif r > 1.2:
            under_est[0].append(e_v)
            under_est[1].append(a_v)
        else:
            accurate[0].append(e_v)
            accurate[1].append(a_v)

    if over_est[0]:
        ax.scatter(
            over_est[0],
            over_est[1],
            s=80,
            color=_COLOR_DANGER,
            alpha=0.75,
            edgecolors="white",
            linewidth=1,
            label=f"Over-estimated ({len(over_est[0])})",
        )
    if accurate[0]:
        ax.scatter(
            accurate[0],
            accurate[1],
            s=80,
            color=_COLOR_SECONDARY,
            alpha=0.75,
            edgecolors="white",
            linewidth=1,
            label=f"Accurate ({len(accurate[0])})",
        )
    if under_est[0]:
        ax.scatter(
            under_est[0],
            under_est[1],
            s=80,
            color=_COLOR_ACCENT,
            alpha=0.75,
            edgecolors="white",
            linewidth=1,
            label=f"Under-estimated ({len(under_est[0])})",
        )

    max_val = max(max(est, default=1), max(actual, default=1)) * 1.1
    ax.plot(
        [0, max_val],
        [0, max_val],
        "--",
        color=_COLOR_NEUTRAL,
        linewidth=1.2,
        label="Perfect estimate",
    )

    ax.set_xlabel("Estimated (minutes)")
    ax.set_ylabel("Actual (minutes)")
    ax.set_xlim(0, max_val)
    ax.set_ylim(0, max_val)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.5)

    _set_title_with_subtitle(fig, ax, "Estimate Accuracy", start_date, end_date)
    ax.legend(loc="upper left", frameon=True, framealpha=0.9)

    return fig


def render_completion_timing(
    analytics: AnalyticsService,
    list_id=None,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """Distribution of completion timing: early / on-time / late / unknown.

    Two-panel layout:
      - Left: bar chart of cohort counts (early, ontime, late, unknown)
      - Right: horizontal scatter of per-item deviation in minutes,
        colored by classification

    Uses the same BarState palette as render_gantt and the calendar UI
    so the visualization is consistent across surfaces.
    """
    _, _, _ = _import_matplotlib()

    from .bar_palette import get_palette
    from .calendar_layout import BarState

    palette = get_palette("light")

    start_str = start_date.isoformat() if start_date else None
    end_str = end_date.isoformat() if end_date else None
    result = analytics.completion_timing(
        list_id=str(list_id) if list_id else None,
        start_date=start_str,
        end_date=end_str,
    )

    if result.total == 0:
        return _empty_figure(
            "Completion Timing",
            "No completed items in this range",
        )

    fig = _make_figure((13.0, 6.0), left_margin=0.06)
    # Two side-by-side axes — counts on the left, scatter on the right.
    # subplots_adjust already set top/bottom; use add_axes for precise layout.
    ax_counts = fig.add_axes((0.06, 0.16, 0.30, 0.66))
    ax_scatter = fig.add_axes((0.46, 0.16, 0.50, 0.66))

    # ------------------------------------------------------------------
    # Left panel: cohort count bars
    # ------------------------------------------------------------------
    cohort_labels = ["Early", "On time", "Late", "Unknown"]
    cohort_counts = [
        result.early_count,
        result.ontime_count,
        result.late_count,
        result.unknown_count,
    ]
    cohort_colors = [
        palette[BarState.COMPLETED_EARLY].base,
        palette[BarState.COMPLETED_ONTIME].base,
        palette[BarState.COMPLETED_LATE].deviation,  # late-overflow color
        palette[BarState.COMPLETED_UNKNOWN].base,
    ]
    bars = ax_counts.bar(
        cohort_labels,
        cohort_counts,
        color=cohort_colors,
        alpha=0.85,
        edgecolor="white",
        linewidth=0.8,
    )
    # Annotate each bar with its count above the top
    for bar, count in zip(bars, cohort_counts, strict=True):
        if count > 0:
            ax_counts.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                str(count),
                ha="center",
                va="bottom",
                fontsize=10,
                color=_COLOR_TEXT,
                fontweight="bold",
            )
    ax_counts.set_ylabel("Count")
    ax_counts.set_title("Cohort breakdown", loc="left", pad=8, fontsize=11)
    ax_counts.spines["top"].set_visible(False)
    ax_counts.spines["right"].set_visible(False)
    ax_counts.grid(True, axis="y", alpha=0.5)
    ax_counts.set_axisbelow(True)
    if max(cohort_counts) > 0:
        ax_counts.set_ylim(0, max(cohort_counts) * 1.15)

    # ------------------------------------------------------------------
    # Right panel: per-item deviation scatter
    # ------------------------------------------------------------------
    if result.items:
        # Sort by deviation so the visual flows left (early) to right (late)
        sorted_items = sorted(result.items, key=lambda i: i.deviation_minutes)
        deviations = [i.deviation_minutes for i in sorted_items]
        # Y position: spread vertically to reduce overlap, with a small jitter
        # for visibility. Use index-based positions evenly spaced in [0, 1].
        n = len(sorted_items)
        y_positions = [(i + 0.5) / n if n > 0 else 0.5 for i in range(n)]
        point_colors = []
        for it in sorted_items:
            if it.classification == "early":
                point_colors.append(palette[BarState.COMPLETED_EARLY].base)
            elif it.classification == "ontime":
                point_colors.append(palette[BarState.COMPLETED_ONTIME].base)
            else:
                point_colors.append(palette[BarState.COMPLETED_LATE].deviation)
        ax_scatter.scatter(
            deviations,
            y_positions,
            c=point_colors,
            s=80,
            alpha=0.75,
            edgecolors="white",
            linewidth=1,
        )
        # Vertical reference line at deviation = 0
        ax_scatter.axvline(
            0,
            color=_COLOR_NEUTRAL,
            linestyle="--",
            linewidth=1.2,
            alpha=0.7,
            zorder=0,
        )
        # Symmetric x range so the zero line stays visually centered
        # unless skew is extreme
        if deviations:
            max_abs = max(abs(d) for d in deviations)
            x_pad = max(max_abs * 0.1, 5)
            ax_scatter.set_xlim(-max_abs - x_pad, max_abs + x_pad)
        ax_scatter.set_yticks([])
        ax_scatter.set_xlabel("Deviation (minutes) — negative = early, positive = late")
        ax_scatter.set_title(
            f"Per-item deviation ({len(result.items)} items)",
            loc="left",
            pad=8,
            fontsize=11,
        )
        ax_scatter.spines["top"].set_visible(False)
        ax_scatter.spines["right"].set_visible(False)
        ax_scatter.spines["left"].set_visible(False)
        ax_scatter.grid(True, axis="x", alpha=0.5)
        ax_scatter.set_axisbelow(True)
    else:
        # All UNKNOWN cohort — no per-item data to show
        ax_scatter.text(
            0.5,
            0.5,
            f"All {result.unknown_count} completions in this range\n"
            "have no recorded completion timestamp\n(pre-v19 data)",
            ha="center",
            va="center",
            fontsize=11,
            color=_COLOR_TEXT_MUTED,
            transform=ax_scatter.transAxes,
        )
        ax_scatter.set_xticks([])
        ax_scatter.set_yticks([])
        for spine in ax_scatter.spines.values():
            spine.set_visible(False)

    _set_title_with_subtitle(fig, None, "Completion Timing", start_date, end_date)
    return fig


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_png(figure, path: str | Path) -> None:
    """Save a matplotlib figure as PNG at publication-quality DPI."""
    figure.savefig(str(path), dpi=200, bbox_inches="tight", facecolor="white")


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

    `include` is a set of chart keys to include:
    {"gantt", "daily", "blocks", "accuracy", "timing"}.
    If None, all five charts are included.
    """
    _, PdfPages, _ = _import_matplotlib()

    if include is None:
        include = {"gantt", "daily", "blocks", "accuracy", "timing"}

    chart_specs = [
        (
            "gantt",
            lambda: render_gantt(
                items,
                start_date=start_date,
                end_date=end_date,
                include_full_legend=True,  # zero data loss for exported artifact
            ),
        ),
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
        (
            "timing",
            lambda: render_completion_timing(
                analytics, list_id=list_id, start_date=start_date, end_date=end_date
            ),
        ),
    ]

    with PdfPages(str(path)) as pdf:
        for key, renderer in chart_specs:
            if key not in include:
                continue
            fig = renderer()
            pdf.savefig(fig, bbox_inches="tight", facecolor="white")
