# Charting Library Decision — Desktop Analytics Stack

## Decision Date: 2026-03-29

## Context

The timeline view in the calendar sub-view needed professional chart rendering for time tracking analytics (pomodoro + stopwatch dual-mode visualization). A QPainter-based implementation was attempted and proven insufficient — it produced amateur-looking output regardless of color/layout iteration. Professional time tracking tools use charting libraries, and so must we.

## Decision

### Primary: pyqtgraph (real-time interactive charts)
### Secondary: matplotlib (static report generation)
### Data pipeline: pandas (SQLite → DataFrame → chart)

## Rationale

### Why pyqtgraph for real-time

**Pros:**
- GPU-accelerated rendering via Qt's QGraphicsScene — native 1-second update rate without hacks
- `BarGraphItem` supports Gantt-style horizontal bars with per-bar colors
- Built-in interactivity: hover tooltips (`setToolTip()`), click events (`mouseClickEvent`), zoom/pan (ViewBox)
- Tiny package: ~3-5 MB
- Uses Qt primitives directly (QColor, QPen, QBrush) — integrates naturally with our semantic theme system
- MIT license — GPL v3 compatible, carries forward to future PySide6 migration
- Full PyQt6 support, also supports PyQt5, PySide2, PySide6
- Actively maintained (0.15.0.dev0 as of 2026)
- `setData()` triggers efficient partial redraw — no full replot for updates

**Cons:**
- Default appearance is "scientific" rather than polished — requires QDarkStyle/PyQtDarkTheme for professional look
- No native sticky axis headers (requires custom QWidget layout)
- Less familiar to general developers than matplotlib
- Gantt charts are possible but not purpose-built (need to compose from BarGraphItem instances)

### Why matplotlib for static reports

**Pros:**
- Publication-quality output — best static chart rendering available
- Extensive Gantt chart examples and documentation
- `FigureCanvasQTAgg` embeds directly into PyQt6
- PDF/PNG export built-in
- Familiar to data scientists and analysts
- PSF/BSD-like license — GPL v3 compatible

**Cons:**
- Real-time updates require blitting (complex, fragile)
- Larger package (~15-20 MB)
- Not designed for interactive desktop use
- Theme switching requires figure clear + redraw (not instant)

### Why pandas for data pipeline

**Pros:**
- `pd.read_sql_query()` bridges SQLite → DataFrame directly
- groupby, rolling averages, resampling, pivot tables — replaces dozens of SQL queries
- Statistical operations (mean session length, estimate accuracy, trends) are one-liners
- Natural fit for focus_sessions table structure
- Standard professional analytics stack
- BSD 3-Clause license — GPL v3 compatible

**Cons:**
- ~30 MB package (plus numpy ~20 MB dependency)
- Bundle size concern is dismissed — user explicitly stated professional quality is priority

## Alternatives Evaluated

### plotly + QWebEngineView
- **Rejected.** Best interactivity and visual polish, but:
  - +200 MB memory overhead (spawns multiple QtWebEngineProcess instances)
  - +150 MB bundle size for QWebEngineView
  - Slow at 1-second refresh rate (web rendering overhead)
  - Communication between Python and JS adds complexity
  - Overkill for desktop — designed for web dashboards

### QtCharts (PyQt6-Charts)
- **Rejected.** Native Qt look is polished, but:
  - GPL v3 + Commercial ONLY license (not LGPL)
  - Redundant restriction on top of PyQt6's GPL (no benefit)
  - Would block future PySide6 migration (QtCharts would need separate LGPL Qt Charts module)
  - Less flexible than pyqtgraph for custom Gantt layouts

### vispy
- **Rejected.** GPU-accelerated 3D visualization — wrong tool for 2D bar charts. Unnecessarily complex.

### bokeh
- **Rejected.** Similar web-embedding approach as plotly. Same overhead problems.

### altair
- **Rejected.** Statistical declarative visualization — not designed for timeline/Gantt charts.

## Licensing Compatibility

All chosen libraries are compatible with our GPL v3 obligation (from PyQt6):

| Library | License | GPL v3 Compatible | PySide6 (LGPL) Compatible |
|---------|---------|-------------------|--------------------------|
| pyqtgraph | MIT | Yes | Yes |
| matplotlib | PSF/BSD-like | Yes | Yes |
| pandas | BSD 3-Clause | Yes | Yes |
| numpy | BSD 3-Clause | Yes | Yes |

The entire stack carries forward cleanly to the planned PySide6 migration with zero licensing friction. No commercial licenses required.

## Web UI Independence

These library choices are **desktop-only**. The web UI (vanilla JS SPA) has a completely independent rendering stack:
- Web UI would use a JS charting library (Chart.js, D3.js, Plotly.js, ECharts) when charts are needed
- Data comes from the same REST API endpoints the web UI already uses
- The Python-side pandas/pyqtgraph code never touches the web UI
- Desktop and web chart library decisions are independent

## What pyqtgraph Replaces

The existing QPainter-based `_TimelineWidget.paintEvent()` will be replaced with pyqtgraph rendering. The data flow infrastructure stays:
- Theme-aware chart colors (already in `themes.py`)
- Active session projection for pseudo-real-time updates
- Split actual bar logic (pomodoro red + stopwatch blue)
- Adaptive display based on available time data
- Overflow indicators (overcommitted, over-estimate, overdue)

## Dependencies

Already added to `pyproject.toml` (commit 13d71b2):
```toml
"pyqtgraph>=0.13",
"pandas>=2.0",
```

matplotlib will be added when report generation is implemented (phases D-F).

## Implementation Status

- **pyqtgraph**: Fully integrated. All 5 chart widgets rewritten with correct patterns (d4de807): persistent items, gradient brushes, setOpts/setData real-time updates, batched numpy arrays. 4 timeline sub-views (Tasks/Daily/Productivity/Accuracy) + WeeklyChartWidget.
- **pandas**: Fully integrated. `AnalyticsService` (`core/analytics.py`) with 12 methods, 56 tests, feeding all chart widgets. See `docs/plans/analytics-service.md`.
- **matplotlib**: Not yet integrated. Planned for PDF report generation in phases D-F.
