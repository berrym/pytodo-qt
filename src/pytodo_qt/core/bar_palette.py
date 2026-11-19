"""bar_palette.py

Shared color palette for the calendar Gantt-bar rendering model.

This module is the single source of truth for the colors used by
BarState lifecycle visualization. Both chart_export.render_gantt
(matplotlib) and the calendar_view delegate (PyQt6) consume these
values so the desktop calendar, chart export PNG/PDF, and the web
frontend all render the same task in the same color.

Two palettes are provided: LIGHT and DARK. Each maps a BarState to
(base_color, deviation_color). The deviation color is used for the
secondary visual zone on completed bars (early surplus, late overflow).
For non-completed states, the deviation color is identical to the base
color.

All base colors are chosen to meet WCAG SC 1.4.11 (>= 3:1 against the
theme canvas background, treating each bar as a UI component) and to
remain distinguishable to viewers with red-green color vision deficiency.

Deviation colors are paired sub-zones rendered *inside* the high-contrast
base bar (early surplus, late overflow). They intentionally read as
subtle tints next to the base — the lifecycle state is conveyed by the
base color, with the deviation acting as a textural/positional cue. Per
WCAG, decorative pair-zones whose meaning is carried by an adjacent
high-contrast element are not required to meet 3:1 against the canvas;
the audit script (`scripts/wcag_audit.py`) flags these pairs as
non-essential so they surface in the report without gating the run.
See issue #38 for the design rationale.

A bar carries its task's name, and a marker chip its label. The color
of that text is not part of the palette: `readable_text_on` gives black
or white for any fill, whichever has the higher WCAG contrast with it.
One of the two always reaches the 4.5:1 that WCAG SC 1.4.3 asks of
text, so a bar color can be changed without a text color to match.

Usage:

    from pytodo_qt.core.bar_palette import get_palette, BarColors

    palette = get_palette("dark")
    colors = palette[BarState.COMPLETED_LATE]
    base_hex = colors.base
    deviation_hex = colors.deviation
"""

from __future__ import annotations

from typing import NamedTuple

from .calendar_layout import BarState


class BarColors(NamedTuple):
    """Base + deviation colors for a single BarState.

    For non-completed states, `base` and `deviation` are the same.
    For completed-early, `base` is the completion color and `deviation`
    the color of the hatch over the unused planned span. For
    completed-late, `deviation` is the color of the hatch over the late
    overflow. A hatch is drawn over `base`, opaque, and has a contrast
    of 3:1 or more with it (WCAG SC 1.4.11).
    """

    base: str  # hex string e.g. "#10b981"
    deviation: str  # hex string for the secondary zone


# ---------------------------------------------------------------------------
# Light theme — for white-on-light backgrounds
# ---------------------------------------------------------------------------
# Base colors are chosen for ~5:1 contrast against #ffffff background.
# Color-blind-safe palette inspired by colorbrewer's qualitative scheme.

_LIGHT_PALETTE: dict[BarState, BarColors] = {
    # Future: muted blue, calm and recessed. Tailwind blue-600 (#2563eb)
    # was picked over the prior #60a5fa to clear WCAG SC 1.4.11 (3:1
    # against white canvas) while staying tonally close to the dark-theme
    # FUTURE blue.
    BarState.FUTURE: BarColors(base="#2563eb", deviation="#2563eb"),
    # Active work window: full-saturation teal, the "in progress" signal
    BarState.IN_WORK_WINDOW: BarColors(base="#0d9488", deviation="#0d9488"),
    # Approaching deadline: amber alert
    BarState.DUE_NOW: BarColors(base="#d97706", deviation="#d97706"),
    # Active overdue: red, attention-demanding
    BarState.OVERDUE_ACTIVE: BarColors(base="#dc2626", deviation="#dc2626"),
    # Completed early: green base + a pale green hatch over the unused
    # planned span (early surplus zone), 3.32:1 on the base
    BarState.COMPLETED_EARLY: BarColors(base="#059669", deviation="#d1fae5"),
    # Completed on time: solid green, no deviation zone
    BarState.COMPLETED_ONTIME: BarColors(base="#059669", deviation="#059669"),
    # Completed late: green base + a dark red hatch over the late
    # overflow, 4.28:1 on the base
    BarState.COMPLETED_LATE: BarColors(base="#059669", deviation="#450a0a"),
    # Completed unknown: identical to on-time visually (we render the
    # full planned span as completed) but classified separately for
    # transparency in tooltips and analytics
    BarState.COMPLETED_UNKNOWN: BarColors(base="#6b7280", deviation="#6b7280"),
}


# ---------------------------------------------------------------------------
# Dark theme — for dark-on-light text on dark backgrounds
# ---------------------------------------------------------------------------
# Base colors are chosen for ~5:1 contrast against #1f2937 background.

_DARK_PALETTE: dict[BarState, BarColors] = {
    BarState.FUTURE: BarColors(base="#93c5fd", deviation="#93c5fd"),
    BarState.IN_WORK_WINDOW: BarColors(base="#5eead4", deviation="#5eead4"),
    BarState.DUE_NOW: BarColors(base="#fbbf24", deviation="#fbbf24"),
    BarState.OVERDUE_ACTIVE: BarColors(base="#f87171", deviation="#f87171"),
    BarState.COMPLETED_EARLY: BarColors(base="#34d399", deviation="#064e3b"),
    BarState.COMPLETED_ONTIME: BarColors(base="#34d399", deviation="#34d399"),
    BarState.COMPLETED_LATE: BarColors(base="#34d399", deviation="#7f1d1d"),
    BarState.COMPLETED_UNKNOWN: BarColors(base="#9ca3af", deviation="#9ca3af"),
}


_PALETTES: dict[str, dict[BarState, BarColors]] = {
    "light": _LIGHT_PALETTE,
    "dark": _DARK_PALETTE,
}


def get_palette(theme: str = "light") -> dict[BarState, BarColors]:
    """Return the BarState → BarColors mapping for a given theme.

    Args:
        theme: "light" or "dark". Anything else falls back to "light".

    Returns:
        Dict from every BarState value to a BarColors NamedTuple.
    """
    return _PALETTES.get(theme, _LIGHT_PALETTE)


def get_colors(state: BarState, theme: str = "light") -> BarColors:
    """Convenience: look up colors for a single state."""
    return get_palette(theme)[state]


_WHITE = "#ffffff"
_BLACK = "#000000"


def relative_luminance(color: str) -> float:
    """The relative luminance of a `#rrggbb` color, as WCAG 2.1 defines it.

    0.0 for black, 1.0 for white.
    """

    def channel(value: int) -> float:
        share = value / 255
        return share / 12.92 if share <= 0.03928 else ((share + 0.055) / 1.055) ** 2.4

    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast_ratio(one: str, other: str) -> float:
    """The WCAG 2.1 contrast ratio of two `#rrggbb` colors: 1.0 to 21.0."""
    lighter, darker = sorted((relative_luminance(one), relative_luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def readable_text_on(fill: str) -> str:
    """Black or white, whichever has the higher contrast with the fill.

    The color of text written on a bar or a marker chip. The fill has
    to be painted opaque for the answer to hold: a fill that lets the
    grid show through is another color.

    The better of the two ratios is lowest on a fill of middling
    lightness, where both are 4.58:1, so the text meets WCAG AA
    (4.5:1) on any fill.

    Args:
        fill: The fill as `#rrggbb`.

    Returns:
        `"#ffffff"` or `"#000000"`.
    """
    if contrast_ratio(_WHITE, fill) >= contrast_ratio(_BLACK, fill):
        return _WHITE
    return _BLACK
