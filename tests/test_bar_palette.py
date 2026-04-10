"""Tests for the shared bar_palette module.

These tests verify the palette structure rather than exact hex values
(which are refinable per spec). They guarantee that every BarState has
a defined entry in both light and dark themes, and that the palette
function contracts hold.
"""

from __future__ import annotations

import re

from pytodo_qt.core.bar_palette import (
    BarColors,
    get_colors,
    get_palette,
)
from pytodo_qt.core.calendar_layout import BarState

_HEX_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


class TestPaletteCompleteness:
    """Every BarState must have entries in both themes."""

    def test_light_palette_covers_every_state(self):
        palette = get_palette("light")
        for state in BarState:
            assert state in palette, f"light palette missing {state}"

    def test_dark_palette_covers_every_state(self):
        palette = get_palette("dark")
        for state in BarState:
            assert state in palette, f"dark palette missing {state}"


class TestPaletteFormat:
    """Every BarColors entry must contain valid hex colors."""

    def test_light_colors_are_hex(self):
        palette = get_palette("light")
        for state, colors in palette.items():
            assert _HEX_PATTERN.match(colors.base), (
                f"{state} light base is not a hex color: {colors.base}"
            )
            assert _HEX_PATTERN.match(colors.deviation), (
                f"{state} light deviation is not a hex color: {colors.deviation}"
            )

    def test_dark_colors_are_hex(self):
        palette = get_palette("dark")
        for _state, colors in palette.items():
            assert _HEX_PATTERN.match(colors.base)
            assert _HEX_PATTERN.match(colors.deviation)


class TestPaletteSemantics:
    """Spot-check that the palette respects the spec's semantic intent."""

    def test_active_states_have_no_deviation_zone(self):
        """Non-completed states use the same color for base and deviation
        (no two-zone visual)."""
        palette = get_palette("light")
        active_states = (
            BarState.FUTURE,
            BarState.IN_WORK_WINDOW,
            BarState.DUE_NOW,
            BarState.OVERDUE_ACTIVE,
        )
        for state in active_states:
            colors = palette[state]
            assert colors.base == colors.deviation, (
                f"{state} should not have a distinct deviation color"
            )

    def test_completed_early_has_distinct_deviation(self):
        """COMPLETED_EARLY should have a different (lighter) deviation color
        for the unused planned span."""
        for theme in ("light", "dark"):
            colors = get_palette(theme)[BarState.COMPLETED_EARLY]
            assert colors.base != colors.deviation, (
                f"{theme} COMPLETED_EARLY needs a deviation color"
            )

    def test_completed_late_has_distinct_deviation(self):
        """COMPLETED_LATE should have a different (red-tinted) deviation
        color for the late overflow."""
        for theme in ("light", "dark"):
            colors = get_palette(theme)[BarState.COMPLETED_LATE]
            assert colors.base != colors.deviation

    def test_completed_ontime_has_no_deviation(self):
        """COMPLETED_ONTIME should be a single solid color (no overflow)."""
        for theme in ("light", "dark"):
            colors = get_palette(theme)[BarState.COMPLETED_ONTIME]
            assert colors.base == colors.deviation


class TestPaletteAPI:
    def test_get_colors_returns_named_tuple(self):
        colors = get_colors(BarState.IN_WORK_WINDOW, "light")
        assert isinstance(colors, BarColors)
        assert hasattr(colors, "base")
        assert hasattr(colors, "deviation")

    def test_unknown_theme_falls_back_to_light(self):
        light = get_palette("light")
        fallback = get_palette("nonsense")
        # Fallback returns the light palette object, so they should be equal
        assert fallback == light

    def test_light_and_dark_are_different(self):
        """Sanity: light and dark are not accidentally the same dict."""
        light = get_palette("light")
        dark = get_palette("dark")
        # At least one state's base color should differ between themes
        assert any(light[s].base != dark[s].base for s in BarState), (
            "light and dark palettes are identical — at least one base must differ"
        )
