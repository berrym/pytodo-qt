"""WCAG 2.1 contrast audit for the pytodo-qt color systems.

Walks the semantic (foreground, background) pairs that the desktop
themes (`gui/styles/themes.py`), the web stylesheet
(`web/static/style.css`), the calendar bar palette
(`core/bar_palette.py`), and the inline-style hotspots produce, then
checks each against the WCAG 2.1 AA thresholds:

    Normal text        4.5:1
    Large/bold text    3:1
    UI components      3:1

Run from the repo root:

    uv run python scripts/wcag_audit.py

Exits 1 if any pair fails; the report names every pair so failures can
be located and fixed without re-running. Pairs are defined in this
script (not extracted by AST/regex parsing) — colors live in semantic
groups, not in arbitrary positions, so the explicit table is more
robust than a parser and lets each pair carry its own pass criterion.

Tracking issue: https://github.com/berrym/pytodo-qt/issues/24
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pytodo_qt.core import bar_palette  # noqa: E402
from pytodo_qt.gui.styles.themes import DARK_COLORS, LIGHT_COLORS  # noqa: E402

# ---------------------------------------------------------------------------
# WCAG math
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _channel_lum(c: int) -> float:
    s = c / 255.0
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _channel_lum(r) + 0.7152 * _channel_lum(g) + 0.0722 * _channel_lum(b)


def _blend(over_hex: str, under_hex: str, alpha: float) -> str:
    """The color seen where `over_hex` at `alpha` lies on `under_hex`."""
    over, under = _hex_to_rgb(over_hex), _hex_to_rgb(under_hex)
    return "#" + "".join(
        f"{round(o * alpha + u * (1 - alpha)):02x}" for o, u in zip(over, under, strict=True)
    )


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """WCAG 2.1 contrast ratio for two solid hex colors."""
    l1 = _relative_luminance(_hex_to_rgb(fg_hex))
    l2 = _relative_luminance(_hex_to_rgb(bg_hex))
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# Pair table
# ---------------------------------------------------------------------------

THRESHOLD_TEXT = 4.5
THRESHOLD_UI = 3.0


@dataclass(frozen=True)
class Pair:
    label: str
    theme: str  # "light" | "dark"
    fg: str  # hex
    bg: str  # hex
    threshold: float
    kind: str  # "text" | "ui" — for the report column
    essential: bool = True
    """Whether a failure should gate the run (`True`) or surface
    informatively only (`False`).  Non-essential pairs cover decorative
    zones whose meaning is carried by an adjacent high-contrast element
    — the canonical case is a paired sub-zone inside a calendar
    Gantt bar where the base color identifies the state and the
    deviation color is intentionally a subtle tint.  See issue #38."""


def _desktop_pairs() -> list[Pair]:
    """Pairs derived from `themes.py` LIGHT_COLORS / DARK_COLORS."""
    out: list[Pair] = []
    for theme_name, c in (("light", LIGHT_COLORS), ("dark", DARK_COLORS)):
        # Core text/background pairs (4.5:1)
        text_pairs = [
            ("window_text on window", c["window_text"], c["window"]),
            ("text on base", c["text"], c["base"]),
            ("text on alternate_base", c["text"], c["alternate_base"]),
            ("button_text on button", c["button_text"], c["button"]),
            ("highlight_text on highlight", c["highlight_text"], c["highlight"]),
            ("link on base", c["link"], c["base"]),
            ("link on window", c["link"], c["window"]),
            ("completed_text on completed_bg", c["completed_text"], c["completed_bg"]),
            ("completed_text on base", c["completed_text"], c["base"]),
            # Status colors used as text in lists / detail panel / cards
            ("priority_high on base", c["priority_high"], c["base"]),
            ("priority_normal on base", c["priority_normal"], c["base"]),
            ("priority_low on base", c["priority_low"], c["base"]),
            ("due_overdue on base", c["due_overdue"], c["base"]),
            ("due_today on base", c["due_today"], c["base"]),
            ("due_soon on base", c["due_soon"], c["base"]),
            # Smart-input entity highlight palette — applied as foreground
            # on parsed entity spans against the base background.
            ("entity_date on base", c["entity_date"], c["base"]),
            ("entity_time on base", c["entity_time"], c["base"]),
            ("entity_priority on base", c["entity_priority"], c["base"]),
            ("entity_tag on base", c["entity_tag"], c["base"]),
            ("entity_recurrence on base", c["entity_recurrence"], c["base"]),
            ("entity_pomodoro on base", c["entity_pomodoro"], c["base"]),
            ("entity_estimate on base", c["entity_estimate"], c["base"]),
            ("entity_work_duration on base", c["entity_work_duration"], c["base"]),
            ("entity_time_block on base", c["entity_time_block"], c["base"]),
            ("entity_event_date on base", c["entity_event_date"], c["base"]),
            ("entity_condition on base", c["entity_condition"], c["base"]),
            ("entity_filler on base", c["entity_filler"], c["base"]),
            ("entity_subtask on base", c["entity_subtask"], c["base"]),
            ("entity_advance_reminder on base", c["entity_advance_reminder"], c["base"]),
            # Focus-timer countdown text against panel base
            ("focus_timer_working on base", c["focus_timer_working"], c["base"]),
            ("focus_timer_break on base", c["focus_timer_break"], c["base"]),
            ("focus_timer_paused on base", c["focus_timer_paused"], c["base"]),
            (
                "focus_timer_stopwatch_running on base",
                c["focus_timer_stopwatch_running"],
                c["base"],
            ),
        ]
        for label, fg, bg in text_pairs:
            out.append(Pair(label, theme_name, fg, bg, THRESHOLD_TEXT, "text"))

        # UI component pairs (3:1) — borders, indicators
        ui_pairs = [
            ("border on base", c["border"], c["base"]),
            ("border on window", c["border"], c["window"]),
            ("highlight on base", c["highlight"], c["base"]),  # focus ring
            ("highlight on window", c["highlight"], c["window"]),  # focus ring
            # Persistent-selection indicator bar painted on the left edge
            # of selected list/tree/combo items, against the highlight
            # band that fills the rest of the row.
            ("selection_indicator on highlight", c["selection_indicator"], c["highlight"]),
        ]
        for label, fg, bg in ui_pairs:
            out.append(Pair(label, theme_name, fg, bg, THRESHOLD_UI, "ui"))
    return out


def _web_pairs() -> list[Pair]:
    """Pairs derived from `web/static/style.css` :root and dark overrides."""
    light = {
        "bg": "#ffffff",
        "bg-secondary": "#f5f5f5",
        "bg-card": "#ffffff",
        "surface": "#ffffff",
        "text": "#212121",
        "text-secondary": "#6c6c6c",
        "border": "#878787",
        "accent": "#1976d2",
        "accent-hover": "#1565c0",
        "danger": "#c62828",
        "success": "#2e7d32",
        "warning": "#b45309",
        "completed-bg": "#f5f5f5",
        "completed-text": "#6c6c6c",
        "tag-bg": "#e3f2fd",
        "tag-text": "#1565c0",
        "entity-date": "#1565c0",
        "entity-priority": "#b45309",
        "entity-tag": "#00695c",
        "entity-recurrence": "#2e7d32",
        "entity-pomodoro": "#6a1b9a",
        "high": "#c62828",
        "normal": "#1976d2",
        "low": "#757575",
    }
    dark = {
        "bg": "#121212",
        "bg-secondary": "#1e1e1e",
        "bg-card": "#1e1e1e",
        "surface": "#1e1e1e",
        "text": "#e0e0e0",
        "text-secondary": "#9e9e9e",
        "border": "#787878",
        "accent": "#64b5f6",
        "accent-hover": "#42a5f5",
        "danger": "#ef9a9a",
        "success": "#81c784",
        "warning": "#ffb74d",
        "completed-bg": "#1a1a1a",
        "completed-text": "#8a8a8a",
        "tag-bg": "#1a3a5c",
        "tag-text": "#90caf9",
        "entity-date": "#6AB0F3",
        "entity-priority": "#F0A850",
        "entity-tag": "#4DC4C4",
        "entity-recurrence": "#7DC87D",
        "entity-pomodoro": "#A78BFA",
        "high": "#ef9a9a",
        "normal": "#2196f3",
        "low": "#9e9e9e",
    }
    out: list[Pair] = []
    for theme_name, c in (("light", light), ("dark", dark)):
        text_pairs = [
            ("text on bg", c["text"], c["bg"]),
            ("text on bg-secondary", c["text"], c["bg-secondary"]),
            ("text on bg-card", c["text"], c["bg-card"]),
            ("text on surface", c["text"], c["surface"]),
            ("text-secondary on bg", c["text-secondary"], c["bg"]),
            ("text-secondary on bg-secondary", c["text-secondary"], c["bg-secondary"]),
            ("text-secondary on surface", c["text-secondary"], c["surface"]),
            ("accent on bg", c["accent"], c["bg"]),
            ("accent on surface", c["accent"], c["surface"]),
            ("accent-hover on bg", c["accent-hover"], c["bg"]),
            ("danger on bg", c["danger"], c["bg"]),
            ("danger on surface", c["danger"], c["surface"]),
            ("success on bg", c["success"], c["bg"]),
            ("warning on bg", c["warning"], c["bg"]),
            # The "Not sent" label and the button that takes a waiting
            # subtask back, in a board card's list of subtasks; in the
            # task sheet they are on bg.
            ("warning on bg-card", c["warning"], c["bg-card"]),
            ("text-secondary on bg-card", c["text-secondary"], c["bg-card"]),
            # The "Not sent" label on a task row; a ticked task that is
            # waiting to be sent is drawn on the completed background.
            ("warning on completed-bg", c["warning"], c["completed-bg"]),
            ("completed-text on completed-bg", c["completed-text"], c["completed-bg"]),
            ("tag-text on tag-bg", c["tag-text"], c["tag-bg"]),
            ("entity-date on bg", c["entity-date"], c["bg"]),
            ("entity-priority on bg", c["entity-priority"], c["bg"]),
            ("entity-tag on bg", c["entity-tag"], c["bg"]),
            ("entity-recurrence on bg", c["entity-recurrence"], c["bg"]),
            ("entity-pomodoro on bg", c["entity-pomodoro"], c["bg"]),
            ("high on bg", c["high"], c["bg"]),
            ("normal on bg", c["normal"], c["bg"]),
            ("low on bg", c["low"], c["bg"]),
        ]
        for label, fg, bg in text_pairs:
            out.append(Pair(label, theme_name, fg, bg, THRESHOLD_TEXT, "text"))

        ui_pairs = [
            ("border on bg", c["border"], c["bg"]),
            ("border on surface", c["border"], c["surface"]),
            ("accent on bg (focus ring)", c["accent"], c["bg"]),
        ]
        for label, fg, bg in ui_pairs:
            out.append(Pair(label, theme_name, fg, bg, THRESHOLD_UI, "ui"))
    return out


def _bar_pairs() -> list[Pair]:
    """Calendar Gantt-bar lifecycle palette.

    Bars are rectangular fills against the calendar grid background,
    measured against it at the UI component floor, 3:1. The grid
    background matches `base` in each theme.

    A bar carries its task's name and a marker chip its label, as
    text: each color of `core/bar_palette.py` is also measured
    against the text the desktop writes on it, at 4.5:1. The text is
    the one `bar_palette.readable_text_on` chooses; the ratio is this
    script's own.

    The deviation colors of the completed states (early surplus, late
    overflow) are hatches drawn over the bar's own color, never on the
    grid: a hatch is measured against that color, at 3:1. The hatch is
    what tells a task finished late from one finished on time, so the
    pair gates the run.
    """
    light_bg = LIGHT_COLORS["base"]
    dark_bg = DARK_COLORS["base"]
    light_bars = {
        "bar-future": "#2563eb",
        "bar-in-work-window": "#0d9488",
        "bar-due-now": "#d97706",
        "bar-overdue-active": "#dc2626",
        "bar-completed-early-base": "#059669",
        "bar-completed-early-deviation": "#d1fae5",
        "bar-completed-ontime": "#059669",
        "bar-completed-late-base": "#059669",
        "bar-completed-late-deviation": "#450a0a",
        "bar-completed-unknown": "#6b7280",
    }
    dark_bars = {
        "bar-future": "#93c5fd",
        "bar-in-work-window": "#5eead4",
        "bar-due-now": "#fbbf24",
        "bar-overdue-active": "#f87171",
        "bar-completed-early-base": "#34d399",
        "bar-completed-early-deviation": "#064e3b",
        "bar-completed-ontime": "#34d399",
        "bar-completed-late-base": "#34d399",
        "bar-completed-late-deviation": "#7f1d1d",
        "bar-completed-unknown": "#9ca3af",
    }
    hatch_bars = {
        "bar-completed-early-deviation": "bar-completed-early-base",
        "bar-completed-late-deviation": "bar-completed-late-base",
    }
    out: list[Pair] = []
    for theme_name, bars, bg in (("light", light_bars, light_bg), ("dark", dark_bars, dark_bg)):
        for name, hex_val in bars.items():
            if name in hatch_bars:
                out.append(
                    Pair(
                        f"{name} hatch on its bar",
                        theme_name,
                        hex_val,
                        bars[hatch_bars[name]],
                        THRESHOLD_UI,
                        "ui",
                    )
                )
                continue
            out.append(Pair(f"{name} on base", theme_name, hex_val, bg, THRESHOLD_UI, "ui"))
        for state, colors in bar_palette.get_palette(theme_name).items():
            out.append(
                Pair(
                    f"desktop label on bar {state.name.lower()}",
                    theme_name,
                    bar_palette.readable_text_on(colors.base),
                    colors.base,
                    THRESHOLD_TEXT,
                    "text",
                )
            )
    return out


def _inline_pairs() -> list[Pair]:
    """Inline color literals embedded in widgets and dialogs.

    All previously-tracked inline hex literals were retired in the
    #33 / #40 cleanup waves — the widgets / dialogs / models now read
    foreground colors from `themes.get_colors()`. Surfaces that need
    a theme-invariant cursor-affordance color (drag-preview labels,
    resize-snap indicator) read the new `interactive_overlay` theme
    key, which carries the same `#2563eb` value across LIGHT_COLORS
    and DARK_COLORS by design.

    The `interactive_overlay` pair below confirms the white text used
    by those affordances clears AA against the overlay background; it
    is the only inline pair the audit still tracks.
    """
    out: list[Pair] = []
    overlay = LIGHT_COLORS["interactive_overlay"]
    out.append(
        Pair(
            "white text on interactive_overlay",
            "both",
            "#ffffff",
            overlay,
            THRESHOLD_TEXT,
            "text",
        )
    )
    return out


def readable_text_on(fill: str) -> str:
    """Black or white, whichever has the higher contrast with the fill.

    The rule the web page uses for a label on a calendar bar. One of the
    two always reaches the text threshold: the lower of the best ratios,
    on a fill of middling lightness, is 4.58:1.
    """
    white, black = "#ffffff", "#000000"
    return white if contrast_ratio(white, fill) >= contrast_ratio(black, fill) else black


def _web_fill_pairs() -> list[Pair]:
    """Text the web page writes on a fill of one of the theme's colors.

    The `--on-*` variables of `web/static/style.css` are the colors of
    text on the accent, danger, success and warning fills (the header,
    buttons, banners, the pending count, the swipe's two sides). The
    labels on the calendar's bars take their color from the fill, by
    `readable_text_on`.
    """
    fills = {
        "light": {
            "accent": "#1976d2",
            "accent-hover": "#1565c0",
            "danger": "#c62828",
            "success": "#2e7d32",
            "warning": "#b45309",
        },
        "dark": {
            "accent": "#64b5f6",
            "accent-hover": "#42a5f5",
            "danger": "#ef9a9a",
            "success": "#81c784",
            "warning": "#ffb74d",
        },
    }
    on_fill = {"light": "#ffffff", "dark": "#000000"}
    bars = {
        "light": {
            "bar-future": "#2563eb",
            "bar-in-work-window": "#0d9488",
            "bar-due-now": "#d97706",
            "bar-overdue-active": "#dc2626",
            "bar-completed": "#059669",
            "bar-completed-unknown": "#6b7280",
        },
        "dark": {
            "bar-future": "#93c5fd",
            "bar-in-work-window": "#5eead4",
            "bar-due-now": "#fbbf24",
            "bar-overdue-active": "#f87171",
            "bar-completed": "#34d399",
            "bar-completed-unknown": "#9ca3af",
        },
    }
    # The block in a day of the Week that stands for the bars the
    # column has no lane for: a count on a fill of --text-secondary,
    # on the card or on today's column (--accent-subtle, the accent at
    # 8% over the card).
    more_blocks = {
        "light": {"fill": "#6c6c6c", "card": "#ffffff", "accent": "#1976d2"},
        "dark": {"fill": "#9e9e9e", "card": "#1e1e1e", "accent": "#64b5f6"},
    }
    out: list[Pair] = []
    for theme in ("light", "dark"):
        block = more_blocks[theme]
        today = _blend(block["accent"], block["card"], 0.08)
        out.append(
            Pair(
                "web count on the block of bars without a lane",
                theme,
                readable_text_on(block["fill"]),
                block["fill"],
                THRESHOLD_TEXT,
                "text",
            )
        )
        out.append(
            Pair(
                "web block of bars without a lane on bg-card",
                theme,
                block["fill"],
                block["card"],
                THRESHOLD_UI,
                "ui",
            )
        )
        out.append(
            Pair(
                "web block of bars without a lane on today's column",
                theme,
                block["fill"],
                today,
                THRESHOLD_UI,
                "ui",
            )
        )
        for name, fill in fills[theme].items():
            out.append(
                Pair(
                    f"web text on {name} fill", theme, on_fill[theme], fill, THRESHOLD_TEXT, "text"
                )
            )
        for name, fill in bars[theme].items():
            out.append(
                Pair(
                    f"web label on {name}",
                    theme,
                    readable_text_on(fill),
                    fill,
                    THRESHOLD_TEXT,
                    "text",
                )
            )
    return out


def _desktop_fill_pairs() -> list[Pair]:
    """Text the desktop's widgets write on a fill of one of the theme's colors.

    Text on the highlight fill takes the palette's highlighted-text
    color, which `_desktop_pairs` measures. Text on a fill of another
    theme color is the one `bar_palette.readable_text_on` chooses
    (`_inline_pairs` has the overlay color). The button color and the
    alternate base lie under text in its ordinary colors where a row
    or a button is under the pointer.
    """
    out: list[Pair] = []
    readable_on = (
        ("due_overdue", "Forget under the pointer"),
        ("due_soon", "Encrypted badge"),
        ("highlight", "Encrypted + Trusted badge"),
    )
    ordinary_on = (
        ("button", ("text", "button_text"), "button under the pointer, tag chip"),
        (
            "alternate_base",
            ("text", "completed_text", "entity_tag"),
            "Agenda row under the pointer",
        ),
        (
            "alternate_base",
            ("due_overdue", "due_today", "due_soon"),
            "list view, Due text on an alternate row",
        ),
    )
    for theme, colors in (("light", LIGHT_COLORS), ("dark", DARK_COLORS)):
        for key, where in readable_on:
            fill = colors[key]
            out.append(
                Pair(
                    f"readable text on {key} ({where})",
                    theme,
                    bar_palette.readable_text_on(fill),
                    fill,
                    THRESHOLD_TEXT,
                    "text",
                )
            )
        # The border of a finished task's box and card: against the row
        # and the alternate row, which is the board's column too, and
        # against the fill inside it.
        for around in ("base", "alternate_base", "completed_bg"):
            out.append(
                Pair(
                    f"finished task's border (due_soon) on {around}",
                    theme,
                    colors["due_soon"],
                    colors[around],
                    THRESHOLD_UI,
                    "ui",
                )
            )
        # The list view's recurrence icon, on a row and on an alternate row.
        for icon_key in ("highlight", "completed_text"):
            for row_key in ("base", "alternate_base"):
                out.append(
                    Pair(
                        f"recurrence icon in {icon_key} on {row_key}",
                        theme,
                        colors[icon_key],
                        colors[row_key],
                        THRESHOLD_UI,
                        "ui",
                    )
                )
        for fill_key, text_keys, where in ordinary_on:
            for text_key in text_keys:
                out.append(
                    Pair(
                        f"{text_key} on {fill_key} ({where})",
                        theme,
                        colors[text_key],
                        colors[fill_key],
                        THRESHOLD_TEXT,
                        "text",
                    )
                )
    out.append(
        Pair(
            "white on the step circle (Mobile Access)",
            "both",
            "#ffffff",
            "#1976d2",
            THRESHOLD_TEXT,
            "text",
        )
    )
    return out


def _desktop_window_pairs() -> list[Pair]:
    """Muted and state texts on the window background.

    Dialogs and the status bar have the window's color behind them,
    not the base's, and it is the darker of the two in the light theme.
    The muted text is what `palette(placeholder-text)` gives; the three
    state colors are what the status bar writes its states in. The
    border color is drawn on both backgrounds.
    """
    out: list[Pair] = []
    for theme, colors in (("light", LIGHT_COLORS), ("dark", DARK_COLORS)):
        for key in ("completed_text", "due_soon", "due_overdue", "due_today"):
            out.append(
                Pair(
                    f"{key} on window",
                    theme,
                    colors[key],
                    colors["window"],
                    THRESHOLD_TEXT,
                    "text",
                )
            )
        # The accent as text is the link color: on every background text
        # stands on, the button color included, which lies under a tool
        # button under the pointer.
        for around in ("window", "base", "alternate_base", "button", "completed_bg"):
            out.append(
                Pair(
                    f"link on {around} (accent-colored text)",
                    theme,
                    colors["link"],
                    colors[around],
                    THRESHOLD_TEXT,
                    "text",
                )
            )
        # The focus timer's states, as the status bar writes them.
        for key in (
            "focus_timer_working",
            "focus_timer_break",
            "focus_timer_paused",
            "focus_timer_stopwatch_running",
        ):
            out.append(
                Pair(
                    f"{key} on window", theme, colors[key], colors["window"], THRESHOLD_TEXT, "text"
                )
            )
        for around in ("window", "base", "alternate_base"):
            out.append(
                Pair(
                    f"border on {around} (frames and rules in dialogs and the calendar)",
                    theme,
                    colors["border"],
                    colors[around],
                    THRESHOLD_UI,
                    "ui",
                )
            )
    return out


def sections() -> dict[str, list[Pair]]:
    """Every pair of the audit, under the heading it is reported under.

    The one list of what is measured: a group left out of it is
    neither reported nor counted.
    """
    return {
        "Desktop (themes.py)": _desktop_pairs(),
        "Desktop text on fills": _desktop_fill_pairs(),
        "Desktop on the window background": _desktop_window_pairs(),
        "Web (style.css)": _web_pairs(),
        "Web text on fills": _web_fill_pairs(),
        "Calendar bar palette": _bar_pairs(),
        "Inline literals": _inline_pairs(),
    }


def collect_pairs() -> list[Pair]:
    return [pair for group in sections().values() for pair in group]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt_row(
    label: str,
    theme: str,
    fg: str,
    bg: str,
    ratio: float,
    threshold: float,
    status: str,
    essential: bool = True,
) -> str:
    tag = "" if essential else " [exempt]"
    return (
        f"  {status}{tag}  {ratio:5.2f}:1  (need {threshold:>3.1f})  "
        f"[{theme:>5}]  {label}  {fg} on {bg}"
    )


def main() -> int:
    groups = sections()
    pairs = [pair for group in groups.values() for pair in group]
    failed_essential: list[Pair] = []
    failed_exempt: list[Pair] = []

    print("=" * 78)
    print("WCAG 2.1 AA contrast audit — pytodo-qt")
    print(f"  Normal text threshold: {THRESHOLD_TEXT}:1")
    print(f"  UI component threshold: {THRESHOLD_UI}:1")
    print(f"  Total pairs: {len(pairs)}")
    print("=" * 78)

    for section, group in groups.items():
        print(f"\n[{section}]  ({len(group)} pairs)")
        for p in group:
            r = contrast_ratio(p.fg, p.bg)
            ok = r >= p.threshold
            status = "PASS" if ok else "FAIL"
            print(_fmt_row(p.label, p.theme, p.fg, p.bg, r, p.threshold, status, p.essential))
            if not ok:
                if p.essential:
                    failed_essential.append(p)
                else:
                    failed_exempt.append(p)

    pass_count = len(pairs) - len(failed_essential) - len(failed_exempt)
    print("\n" + "=" * 78)
    print(
        f"Result: {pass_count} pass, {len(failed_essential)} fail, {len(failed_exempt)} exempt-fail"
    )
    print("=" * 78)

    failed = failed_essential + failed_exempt
    if failed:
        print("\nFailures (sorted worst-first):")
        for p in sorted(failed, key=lambda q: contrast_ratio(q.fg, q.bg)):
            r = contrast_ratio(p.fg, p.bg)
            print(_fmt_row(p.label, p.theme, p.fg, p.bg, r, p.threshold, "FAIL", p.essential))

    if failed_essential:
        return 1

    if failed_exempt:
        print("\nAll essential pairs meet WCAG 2.1 AA. Exempt-fail pairs are decorative.")
    else:
        print("\nAll pairs meet WCAG 2.1 AA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
