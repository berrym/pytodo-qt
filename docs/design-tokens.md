# Design Tokens

Canonical values for spacing, color, typography, border radii, and component patterns across the desktop (Qt) and web (CSS) surfaces. This document is the source of truth — `src/pytodo_qt/gui/styles/themes.py` and `src/pytodo_qt/web/static/style.css` must agree with the values defined here. Divergence is a bug, not a stylistic choice.

## Why this exists

The desktop and web UIs evolved independently. Spacing, font sizes, accent colors, and border radii drifted into uncoordinated values: desktop accent `#0078d4` vs web `#2196f3`, desktop 4 px radii vs web 6/10 px, ad-hoc spacing values (4/6/8/10/12/14/16/20 px) on both surfaces. Without a shared vocabulary, every new surface re-invents the wheel and visual incoherence accumulates. This document fixes the vocabulary.

## Scope

Tokens are platform-shared values. Individual surfaces (a specific dialog, a specific list-row layout) compose tokens but do not introduce new values. When a surface needs a value not in the token list, the token list grows — values are added here first, then applied.

Not in scope: theme-aware color *names* (those live in `themes.py` and the CSS `:root`), entity highlight colors (currently in `smart_input.py` and `app.js`), feature-specific palettes (calendar bar lifecycle states, chart colors).

---

## Spacing scale

A 4-px grid. Every padding, margin, gap, or contentsMargin uses one of these values.

| Token | Value | Use |
|---|---|---|
| `space-1` | 4 px | Tight padding (chip insets, tag-pill internal) |
| `space-2` | 8 px | Standard small (button padding-y, list-item compact rows, card row spacing) |
| `space-3` | 12 px | Comfortable (card padding, dialog field rows, sheet header) |
| `space-4` | 16 px | Section padding (dialog margins, list-item generous, sheet content) |
| `space-5` | 24 px | Major section gaps (group separators in dialogs, dialog inner padding) |
| `space-6` | 32 px | Top-level layout (window margins on large screens) |
| `space-7` | 48 px | Hero / empty-state padding |

Half-step values (2 px, 6 px, 10 px, 14 px, 18 px, 20 px) are not part of the scale. If a surface needs one, either it should be re-evaluated against the closest scale value, or the scale grows.

---

## Border radius

Tiered by element size. Smaller elements get smaller radii so the curve doesn't dominate the shape.

| Token | Value | Use |
|---|---|---|
| `radius-sm` | 4 px | Chips, tags, small overflow indicators, progress-bar fill |
| `radius-md` | 8 px | Buttons, inputs, list items, ComboBoxes, kanban-card-internal elements |
| `radius-lg` | 12 px | Cards, dialogs, sheets, board columns, calendar grid containers |
| `radius-pill` | 9999 px | Pill-shaped chips when used (filter chips, status pills) |

Desktop currently uses 4 px globally; web currently uses 6 / 10 px via CSS variables. Both migrate to this tiered system.

---

## Border widths

| Token | Value | Use |
|---|---|---|
| `border-thin` | 1 px | Standard borders (cards, inputs, dividers, table cells) |
| `border-thick` | 2 px | Emphasis borders (`:focus` indicators, `:default` button outlines, selected-state highlights) |

Anything beyond 2 px is a structural element (e.g., a 4-px priority indicator bar on a card's left edge) and is not a border in the token sense — it's a layout choice and uses an explicit pixel value.

---

## Color

Color values are theme-aware. The token system defines *roles* (accent, danger, success, etc.); the theme files define the actual hex values per light/dark theme.

### Roles (used across both surfaces)

| Role | Description |
|---|---|
| `accent` | Primary action color, used for buttons, links, active states, focus rings |
| `accent-hover` | Slightly darker `accent` for hover states (light theme) / lighter (dark theme) |
| `accent-subtle` | Translucent accent for backgrounds (`rgba(accent, 0.08)` typical) |
| `text` | Primary body text |
| `text-secondary` | Muted text (subtitles, hints, captions) — must still meet WCAG AA contrast against its background |
| `bg` | Primary surface background |
| `bg-secondary` | Subtle alternate surface (toolbars, headers, alternating rows) |
| `bg-card` | Card / sheet / dialog background |
| `border` | Standard border / divider |
| `danger` | Destructive actions, error states, overdue markers |
| `success` | Confirmation, completed states, on-time markers |
| `completed-bg` | Tinted background for completed task rows |
| `completed-text` | Muted text on completed rows |

### Canonical accent

`#2196f3` (Material Design 500 blue) on light theme; `#64b5f6` (lightened for dark-on-dark contrast) on dark theme. Both desktop `themes.py` and web `style.css` use these values.

### Anti-patterns to remove

- **`palette(mid)` for functional text.** Qt's `mid` palette role is a mid-tone gray that fails WCAG AA in dark mode (the dark-mode value of `mid` is itself dark). Use `palette(text)` for primary text and `text-secondary` for muted text — never `mid`.
- **Inline hex colors that bypass the theme system.** Currently present in `dialogs/focus_timer.py` (chart colors `#3498DB`, `#F39C12`, `#E74C3C`, `#27AE60`). These migrate to the theme files so dark theme renders them correctly.
- **Cross-surface accent divergence.** Desktop `#0078d4` (Microsoft Fluent) and web `#2196f3` (Material). Both unify on `#2196f3`.

---

## Typography

Font face is system-default with the bundled Noto Sans as a portable fallback. Sizes are role-driven and use pixel values on both surfaces. Where Qt expects point sizes, pixel values are converted via `QFont.setPixelSize()`.

| Role | Size | Weight | Use |
|---|---|---|---|
| `text-caption` | 11 px | 400 | Tag labels, "+N more" overflow, calendar item chips |
| `text-meta` | 12 px | 400 | Item meta (counts, dates, hint text), tab labels |
| `text-body-sm` | 13 px | 400 | Default body in compact contexts (sort bar, board card meta) |
| `text-body` | 14 px | 400 | Standard body text |
| `text-label` | 14 px | 600 | Form labels, section headers (small) |
| `text-row` | 15 px | 400 | List row primary text, item card primary |
| `text-input` | 15 px | 400 | Form input text |
| `text-section` | 16 px | 600 | Section headings inside surfaces |
| `text-heading` | 18 px | 600 | Sheet/dialog titles, top-level headings |
| `text-display` | 22 px | 600 | Login card, prominent display text |

Line-height defaults to 1.4 for body text and 1.2 for headings.

Desktop's current `themes.py` uses point sizes (10 pt default); migrating to explicit pixel sizes via `QFont.setPixelSize()` makes desktop and web visually agree.

---

## Hit-target minimums

| Element | Minimum |
|---|---|
| Mouse-only interactive (desktop with no touch path) | 24 × 24 px |
| Touch interactive (web mobile, desktop with touch input) | 44 × 44 px |
| Primary action buttons | 44 × 44 px (accommodates touch even on desktop) |
| Secondary buttons in dense dialogs | 32 × 32 px (acceptable for mouse-driven dialogs) |
| Close buttons (e.g., on dialogs) | 44 × 44 px (high error cost; size up) |

Apple HIG, Material Design, and WCAG 2.5.5 all converge on 44 × 44 as the touch minimum. Every interactive widget specifies a minimum size — no relying on font-plus-padding implicit heights.

---

## Button system

Four semantic classes applied identically on desktop (Qt stylesheets / dialog factories) and web (CSS classes).

| Class | Visual | Use |
|---|---|---|
| `primary` | Filled `accent` background, `bg-card` text, `radius-md`, `text-body` 600 weight | The single most important action in a context (Save, Connect, Add) |
| `secondary` | Transparent background, `text` color, `border-thin` solid `border`, `radius-md` | Common actions that aren't the primary (Cancel, Edit, Configure) |
| `danger` | `danger` background or `border-thin` solid `danger`, `bg-card` or `danger` text | Destructive actions (Delete, Disconnect) |
| `ghost` | Transparent background, no border, `text` color on hover only | Toolbar / context-menu actions, anywhere a button needs to disappear into the surface |

All four use the same padding scale (`space-2` vertical, `space-3` horizontal), the same `radius-md`, the same minimum height (44 px). They differ only in fill / border / color.

Hover state: `primary` darkens accent slightly; `secondary` and `ghost` get a `bg-secondary` tint; `danger` saturates.

Focus state: every button gets a `border-thick` solid `accent` outline (or `danger` for danger buttons). No exceptions — keyboard users see focus on every interactive surface.

Disabled state: opacity 0.5, cursor not-allowed (web) / standard Qt disabled appearance (desktop).

---

## Empty states

Every list-style surface defines two distinct empty states:

1. **Truly empty** — the data source has no items at all. Message includes an actionable next step ("Tap + to add your first task," "Add task" button).
2. **Filtered to empty** — items exist but the active filter / search hides all of them. Message includes a path to clear the filter ("No items match this filter — Clear filters").

Currently the list view confuses these into one state (`items.length === 0`). The filtered-empty case must be detected before render and given its own message.

Empty-state rendering uses `text-secondary` color, `space-7` (48 px) padding, centered text alignment, and a single optional action button using `primary` or `secondary`.

---

## Focus indicators

Every focusable element across both surfaces shows a visible focus state when focused via keyboard navigation. The pattern:

- **Web**: `:focus-visible` (not `:focus` — `:focus-visible` only triggers on keyboard navigation, not mouse clicks, so click-focused widgets don't paint a stray outline). The indicator is `outline: 2px solid var(--accent); outline-offset: 2px;` for non-input elements; `border-color: var(--accent); box-shadow: 0 0 0 2px rgba(accent, 0.2);` for inputs (since they already have borders).
- **Desktop (Qt)**: Default Qt focus rectangles are respected. Where `themes.py` overrides input borders, the override includes a `:focus` selector that swaps `border-color` to `palette(highlight)` with `border-width: 2px`.

No interactive element relies on color-change-only as the focus signal. Color *plus* a border or outline change.

---

## Cross-cutting rules

These apply to every change landing under the polish track:

- **WCAG AA color floor.** Every (foreground, background) pair meets 4.5:1 for body text and 3:1 for large text and UI components. Verified per change, not assumed.
- **`tr()` on every new GUI string.** Translation readiness is non-negotiable.
- **Token compliance is verified by code review, not automated yet.** Future improvement: a lint pass that flags hex colors outside the theme files, spacing values outside the scale, radii outside the radius set.
- **Cross-surface parity preserved on shared concepts.** A button on web and a button on desktop should be the same button, visually. Where platform conventions differ (titlebar vs sheet header, native vs custom scrollbar), document the divergence here.

---

## Platform considerations (Qt cross-platform rendering)

Qt renders identically on no two platforms. macOS uses Cocoa native widgets with custom QSS overrides; Windows uses Win32 native; Linux uses the xcb/wayland Qt platform plugin. Same nominal font sizes render at different actual pixel heights. Same widget classes have different default min-heights. HiDPI scaling differs. macOS is by far the most compact: the same QPushButton that natively sits at ~30 px on macOS may render ~36 px on Windows and 32–40 px on Linux depending on font and DPI.

Rules that protect against clipping, oversizing, and platform inconsistency:

- **Trust Qt's natural sizing.** Do not impose blanket `min-height` floors on text-bearing widgets. Adding `min-height: 36 px` to QPushButton / QComboBox / QSpinBox in the global stylesheet pushes macOS-native renderings (which are intentionally compact) up to that floor — the result is widgets that look bloated on the platform that renders most cleanly. If the baseline is acceptable on macOS, it is acceptable everywhere; Windows / Linux render at or above macOS's compact baseline.
- **Apply minimum sizes per-widget only when there's a specific reason.** A 44 × 44 hit-target on a primary action button: yes, set it inline at the call site. A blanket QPushButton min-height in the global stylesheet: no — that catches every button in the app including small icon-action buttons where 36 px is too tall.
- **Width sizing for text labels comes from `fontMetrics().horizontalAdvance()`, not magic numbers.** This is how the all-day band's label width is computed — see `_PinnedWeekContainer` in `calendar_view.py`. Hardcoded widths clip on platforms where the bundled font renders wider.
- **Padding values lean generous.** Inputs use 8 px padding rather than the older 6 px — slightly chunkier on macOS native but avoids clipping risk on Windows / Linux where font metrics run taller. This is a deliberate trade in favor of cross-platform safety.
- **Toolbar buttons are compact by convention.** QToolButton uses 6 px padding and no minimum size — toolbars want icon-tight buttons, not 32 × 32 boxes around 16 × 16 icons.
- **HiDPI is Qt-managed, not token-managed.** Logical pixels in QSS scale to physical pixels automatically. Don't try to second-guess this; trust the framework.
- **Test all three platforms before locking values.** The CI release workflow builds binaries for macOS / Windows / Linux. After every token change, the appropriate binary should be installed and inspected on a real session before the value is treated as canonical.

When a value is found to clip or render oddly on one specific platform, the fix is at the source — recompute the width from font metrics, set a per-widget minimum at the call site, or scope the override per platform — not a global stylesheet rule that catches every widget of that class.

---

## Migration strategy

The actual migration of the codebase to these values happens in waves, each its own commit so testing fits between:

1. **Theme files first.** Apply canonical accent, radius variables, spacing variables to `themes.py` and `style.css`. Most surfaces inherit from these and shift automatically.
2. **Critical accessibility.** Replace `palette(mid)` text usage. Add `:focus-visible` styles to web buttons. Add `setAccessibleName` to desktop dialogs. Set 44 × 44 minimums on undersized interactive elements.
3. **Per-surface migration.** Detail panel, kanban, calendar view, dialogs, web SPA — each migrated to use the canonical tokens. One surface per commit.
4. **Empty-state distinction.** Filtered-empty vs truly-empty rendering.
5. **Entity colors and chart colors.** Move out of `smart_input.py` / `focus_timer.py` into the theme files.
6. **Token-compliance audit.** A pass to find any remaining hex colors, ad-hoc spacing values, or off-scale radii.

The polish track closes when every wave is shipped and the project owner can browse the app without finding a visual inconsistency they'd want fixed before shipping.
