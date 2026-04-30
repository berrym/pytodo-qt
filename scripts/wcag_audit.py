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

ROOT = "/Users/mberry/Lab/python/pytodo-qt"
sys.path.insert(0, f"{ROOT}/src")

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
        "text-secondary": "#757575",
        "border": "#e0e0e0",
        "accent": "#1976d2",
        "accent-hover": "#1565c0",
        "danger": "#c62828",
        "success": "#2e7d32",
        "warning": "#b45309",
        "completed-bg": "#f5f5f5",
        "completed-text": "#757575",
        "tag-bg": "#e3f2fd",
        "tag-text": "#1565c0",
        "entity-date": "#1565c0",
        "entity-priority": "#b45309",
        "entity-tag": "#00695c",
        "entity-recurrence": "#2e7d32",
        "entity-pomodoro": "#6a1b9a",
        "high": "#c62828",
        "normal": "#1976d2",
        "low": "#9e9e9e",
    }
    dark = {
        "bg": "#121212",
        "bg-secondary": "#1e1e1e",
        "bg-card": "#1e1e1e",
        "surface": "#1e1e1e",
        "text": "#e0e0e0",
        "text-secondary": "#9e9e9e",
        "border": "#333333",
        "accent": "#64b5f6",
        "accent-hover": "#42a5f5",
        "danger": "#ef9a9a",
        "success": "#81c784",
        "warning": "#ffb74d",
        "completed-bg": "#1a1a1a",
        "completed-text": "#8a8a8a",
        "tag-bg": "#1a3a5c",
        "tag-text": "#90caf9",
        "entity-date": "#1565c0",  # CSS doesn't override these in dark
        "entity-priority": "#e65100",
        "entity-tag": "#00695c",
        "entity-recurrence": "#2e7d32",
        "entity-pomodoro": "#6a1b9a",
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
    """Calendar Gantt-bar lifecycle palette — UI components, 3:1.

    Bars are rectangular fills against the calendar grid background;
    they carry no in-bar text, so the threshold is the UI component
    floor. The grid background matches `base` in each theme.
    """
    light_bg = LIGHT_COLORS["base"]
    dark_bg = DARK_COLORS["base"]
    light_bars = {
        "bar-future": "#60a5fa",
        "bar-in-work-window": "#0d9488",
        "bar-due-now": "#d97706",
        "bar-overdue-active": "#dc2626",
        "bar-completed-early-base": "#059669",
        "bar-completed-early-deviation": "#a7f3d0",
        "bar-completed-ontime": "#059669",
        "bar-completed-late-base": "#059669",
        "bar-completed-late-deviation": "#fca5a5",
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
    out: list[Pair] = []
    for theme_name, bars, bg in (("light", light_bars, light_bg), ("dark", dark_bars, dark_bg)):
        for name, hex_val in bars.items():
            out.append(Pair(f"{name} on base", theme_name, hex_val, bg, THRESHOLD_UI, "ui"))
    return out


def _inline_pairs() -> list[Pair]:
    """Inline color literals embedded in widgets and dialogs.

    Each pair tests a hex color used in `setStyleSheet(...)` or HTML
    `<span style=...>` against the background it is most likely to
    appear over. Both themes are included where the foreground is a
    pure hex (not a `palette(...)` call).
    """
    light_base = LIGHT_COLORS["base"]
    dark_base = DARK_COLORS["base"]
    light_window = LIGHT_COLORS["window"]
    dark_window = DARK_COLORS["window"]

    out: list[Pair] = []

    # Detail panel / models / calendar — overdue / warning span colors
    # in HTML rendering inside QLabel (lives in the detail panel which
    # uses base as its background).
    for theme, bg in (("light", light_base), ("dark", dark_base)):
        out.append(
            Pair(
                "inline #ef4444 (overdue text) on base",
                theme,
                "#ef4444",
                bg,
                THRESHOLD_TEXT,
                "text",
            )
        )
        out.append(
            Pair(
                "inline #f59e0b (warning text) on base",
                theme,
                "#f59e0b",
                bg,
                THRESHOLD_TEXT,
                "text",
            )
        )
        out.append(
            Pair(
                "inline #ff6e76 (calendar overdue) on base",
                theme,
                "#ff6e76",
                bg,
                THRESHOLD_TEXT,
                "text",
            )
        )

    # Settings / web_connect destructive-action hint text. Text sits on
    # the dialog window background.
    for theme, bg in (("light", light_window), ("dark", dark_window)):
        out.append(
            Pair(
                "inline #c0392b (revoke text) on window",
                theme,
                "#c0392b",
                bg,
                THRESHOLD_TEXT,
                "text",
            )
        )
        out.append(
            Pair(
                "inline #e67e22 (warning title) on window",
                theme,
                "#e67e22",
                bg,
                THRESHOLD_TEXT,
                "text",
            )
        )

    # White-on-button pairs (calendar resize labels, web-connect CTA).
    out.append(
        Pair("inline white on #2563eb button", "both", "#ffffff", "#2563eb", THRESHOLD_TEXT, "text")
    )
    out.append(
        Pair("inline white on #1976D2 button", "both", "#ffffff", "#1976D2", THRESHOLD_TEXT, "text")
    )
    out.append(
        Pair(
            "inline white on #c0392b button hover",
            "both",
            "#ffffff",
            "#c0392b",
            THRESHOLD_TEXT,
            "text",
        )
    )

    # status_bar.py pomodoro state inlines were retired in #33 — the
    # widget now reads `focus_timer_*` from `themes.get_colors()`, so
    # the desktop focus_timer pairs above are the only check needed.

    # Calendar tag chip — small text on base.
    for theme, bg in (("light", light_base), ("dark", dark_base)):
        out.append(
            Pair("inline #2DA5A5 (tag chip) on base", theme, "#2DA5A5", bg, THRESHOLD_TEXT, "text")
        )

    return out


def collect_pairs() -> list[Pair]:
    return [*_desktop_pairs(), *_web_pairs(), *_bar_pairs(), *_inline_pairs()]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt_row(
    label: str, theme: str, fg: str, bg: str, ratio: float, threshold: float, status: str
) -> str:
    return (
        f"  {status}  {ratio:5.2f}:1  (need {threshold:>3.1f})  [{theme:>5}]  {label}  {fg} on {bg}"
    )


def main() -> int:
    pairs = collect_pairs()
    failed: list[Pair] = []

    sections: dict[str, list[Pair]] = {
        "Desktop (themes.py)": _desktop_pairs(),
        "Web (style.css)": _web_pairs(),
        "Calendar bar palette": _bar_pairs(),
        "Inline literals": _inline_pairs(),
    }

    print("=" * 78)
    print("WCAG 2.1 AA contrast audit — pytodo-qt")
    print(f"  Normal text threshold: {THRESHOLD_TEXT}:1")
    print(f"  UI component threshold: {THRESHOLD_UI}:1")
    print(f"  Total pairs: {len(pairs)}")
    print("=" * 78)

    for section, group in sections.items():
        print(f"\n[{section}]  ({len(group)} pairs)")
        for p in group:
            r = contrast_ratio(p.fg, p.bg)
            ok = r >= p.threshold
            status = "PASS" if ok else "FAIL"
            print(_fmt_row(p.label, p.theme, p.fg, p.bg, r, p.threshold, status))
            if not ok:
                failed.append(p)

    print("\n" + "=" * 78)
    print(f"Result: {len(pairs) - len(failed)} pass, {len(failed)} fail")
    print("=" * 78)

    if failed:
        print("\nFailures (sorted worst-first):")
        for p in sorted(failed, key=lambda q: contrast_ratio(q.fg, q.bg)):
            r = contrast_ratio(p.fg, p.bg)
            print(_fmt_row(p.label, p.theme, p.fg, p.bg, r, p.threshold, "FAIL"))
        return 1

    print("\nAll pairs meet WCAG 2.1 AA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
