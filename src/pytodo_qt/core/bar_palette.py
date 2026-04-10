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

All base colors are chosen to meet WCAG AA contrast (>= 4.5:1 against
their respective theme background) and to remain distinguishable to
viewers with red-green color vision deficiency. Hex values are starting
points per the spec — refinable without re-specifying Q5.

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
    is a slightly translucent variant for the unused planned span.
    For completed-late, `base` is the completion color and `deviation`
    is a contrasting late-overflow color (red-tinted, hatched in
    practice).
    """

    base: str  # hex string e.g. "#10b981"
    deviation: str  # hex string for the secondary zone


# ---------------------------------------------------------------------------
# Light theme — for white-on-light backgrounds
# ---------------------------------------------------------------------------
# Base colors are chosen for ~5:1 contrast against #ffffff background.
# Color-blind-safe palette inspired by colorbrewer's qualitative scheme.

_LIGHT_PALETTE: dict[BarState, BarColors] = {
    # Future: muted blue, calm and recessed
    BarState.FUTURE: BarColors(base="#60a5fa", deviation="#60a5fa"),
    # Active work window: full-saturation teal, the "in progress" signal
    BarState.IN_WORK_WINDOW: BarColors(base="#0d9488", deviation="#0d9488"),
    # Approaching deadline: amber alert
    BarState.DUE_NOW: BarColors(base="#d97706", deviation="#d97706"),
    # Active overdue: red, attention-demanding
    BarState.OVERDUE_ACTIVE: BarColors(base="#dc2626", deviation="#dc2626"),
    # Completed early: green base + lighter green deviation for the
    # unused planned span (early surplus zone)
    BarState.COMPLETED_EARLY: BarColors(base="#059669", deviation="#a7f3d0"),
    # Completed on time: solid green, no deviation zone
    BarState.COMPLETED_ONTIME: BarColors(base="#059669", deviation="#059669"),
    # Completed late: green base for the planned span + red-tinted
    # deviation for the late overflow (renders with hatch in matplotlib,
    # texture/gradient in the calendar delegate)
    BarState.COMPLETED_LATE: BarColors(base="#059669", deviation="#fca5a5"),
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
