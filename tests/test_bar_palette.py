"""Tests for the shared bar_palette module.

These tests verify the palette structure rather than exact hex values
(which are refinable per spec). They guarantee that every BarState has
a defined entry in both light and dark themes, and that the palette
function contracts hold.
"""

from __future__ import annotations

import re

import pytest

from pytodo_qt.core.bar_palette import (
    BarColors,
    contrast_ratio,
    get_colors,
    get_palette,
    readable_text_on,
    relative_luminance,
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


class TestTextOnAFill:
    """A bar carries its task's name and a marker chip its label. The
    text is black or white, whichever has the higher WCAG contrast with
    the fill, and reaches the 4.5:1 that AA asks of text on any fill."""

    def test_luminance_of_black_and_white(self):
        assert relative_luminance("#000000") == 0.0
        assert relative_luminance("#ffffff") == pytest.approx(1.0)

    def test_contrast_of_black_and_white_is_twenty_one(self):
        assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
        assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)

    def test_contrast_of_a_colour_with_itself_is_one(self):
        assert contrast_ratio("#2563eb", "#2563eb") == pytest.approx(1.0)

    def test_contrast_matches_published_values(self):
        """White on Tailwind blue-600 and on red-600, as the audit of
        the theme has them."""
        assert contrast_ratio("#ffffff", "#2563eb") == pytest.approx(5.17, abs=0.01)
        assert contrast_ratio("#ffffff", "#dc2626") == pytest.approx(4.83, abs=0.01)

    def test_hex_digits_in_either_case(self):
        assert relative_luminance("#FBBF24") == relative_luminance("#fbbf24")

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_text_on_every_bar_colour_meets_aa(self, theme):
        for state, colors in get_palette(theme).items():
            text = readable_text_on(colors.base)
            ratio = contrast_ratio(text, colors.base)
            assert ratio >= 4.5, f"{theme} {state}: {text} on {colors.base} is {ratio:.2f}:1"

    def test_text_is_the_better_of_black_and_white(self):
        for theme in ("light", "dark"):
            for colors in get_palette(theme).values():
                text = readable_text_on(colors.base)
                other = "#000000" if text == "#ffffff" else "#ffffff"
                assert contrast_ratio(text, colors.base) >= contrast_ratio(other, colors.base)

    def test_text_on_any_grey_meets_aa(self):
        """The better of the two ratios is lowest on a fill of middling
        lightness, where both are 4.58:1; it does not fall under that."""
        lowest = min(
            contrast_ratio(readable_text_on(f"#{v:02x}{v:02x}{v:02x}"), f"#{v:02x}{v:02x}{v:02x}")
            for v in range(256)
        )
        assert 4.58 <= lowest < 4.7

    def test_light_theme_has_white_and_black_labels(self):
        """White stays on the blue, the red and the grey; the teal, the
        amber and the green are too light for it."""
        light = get_palette("light")
        assert readable_text_on(light[BarState.FUTURE].base) == "#ffffff"
        assert readable_text_on(light[BarState.OVERDUE_ACTIVE].base) == "#ffffff"
        assert readable_text_on(light[BarState.COMPLETED_UNKNOWN].base) == "#ffffff"
        assert readable_text_on(light[BarState.IN_WORK_WINDOW].base) == "#000000"
        assert readable_text_on(light[BarState.DUE_NOW].base) == "#000000"
        assert readable_text_on(light[BarState.COMPLETED_ONTIME].base) == "#000000"

    def test_dark_theme_has_black_labels(self):
        for colors in get_palette("dark").values():
            assert readable_text_on(colors.base) == "#000000"
