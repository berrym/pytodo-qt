# Timeline Bar Redesign — Multi-Mode Visualization

## Implementation Status (2026-03-30)

### Completed
- QPainter timeline fully replaced with pyqtgraph PlotWidget (commit 13d71b2)
- QPainter WeeklyChartWidget replaced with pyqtgraph (commit 5998d0c)
- 4 timeline sub-views implemented (commit 12a9429):
  - **Tasks**: Gantt horizontal bars (time span, gray estimate baseline, split red+cyan actual)
  - **Daily**: Stacked vertical bars (pomodoro+stopwatch per day) + 7-day rolling average trend line
  - **Productivity**: Time block heatmap (12 two-hour blocks, intensity-scaled, completion rate overlays)
  - **Accuracy**: Scatter plot (estimated vs actual minutes, y=x reference line, variance coloring)
- Secondary pill toggle: Tasks / Daily / Productivity / Accuracy (visible only in Timeline mode)
- Theme-aware colors: Okabe-Ito (light) + ECharts dark palettes in semantic theme system
- Persistent hover tooltips on Tasks view
- Pseudo-real-time bar projection during active focus sessions
- Unscheduled panel hidden in timeline mode (passive analytical view)
- Navigation: daily shift (Tasks), weekly shift (Daily), disabled (Productivity/Accuracy)
- All charts fed by AnalyticsService DataFrames (pandas pipeline)
- Always-visible legends on all sub-views
- Empty state messages with user guidance

### Not Yet Implemented
- Pomodoro/stopwatch filter toggles on existing filter dropdowns (additive, low effort)
- Stopwatch idle timeout auto-pause (StopwatchConfig has the field, not wired)
- PDF/PNG chart export (matplotlib planned for this, not yet added)
- Timeline sub-view persistence in config (defaults to Tasks on load)

---

## Design History

### Context

The stopwatch feature introduces a second time tracking mode alongside pomodoro. The timeline view needs to visualize data from both modes meaningfully. This exposed several fundamental design problems with the original QPainter bar rendering.

## Original QPainter State (historical, replaced)

### Dimensions
- `ROW_HEIGHT = 32px` — total height per task row
- `BAR_HEIGHT = 8px` — height of each individual bar
- `HEADER_HEIGHT = 30px` — date header at top
- `LABEL_WIDTH = 160px` — left task name column
- 3 bars per row (blue, amber, green), 2px gaps between them
- Total bar stack = 28px within 32px row (2px top margin)
- `pixels_per_session = 15` — arbitrary visual constant for effort scaling
- Font sizes: header 10px, labels 11px, legend 9px
- Scroll area wraps the widget; total height = 50 + (item_count x 32)px

### Three Bar Types
1. **Blue (time span)**: creation_date -> due_date (or today if no due date)
2. **Amber (estimated effort)**: `estimated_pomodoros x 15px` or `estimated_minutes / work_duration x 15px`
3. **Green (actual work)**: ratio of amber (if estimate) or `sessions x 15px` (if no estimate)

## Problems Identified

### 1. Dimensional Mismatch Between Modes
The current amber bar converts `estimated_minutes` to "equivalent sessions" using `config_work_mins`. This is fundamentally broken:
- Stopwatch estimates in minutes shouldn't change width when pomodoro `work_duration` changes
- When per-task pomodoro durations arrive, the conversion becomes nonsensical
- A 90-minute stopwatch estimate and a 3x25min pomodoro estimate render differently despite ~equal effort

### 2. No Visual Distinction Between Tracking Modes
Both pomodoro and stopwatch data render as identical amber/green bars. A user who uses both modes on a task can't tell which effort came from where.

### 3. Estimate Overflow Not Shown (Known Limitation)
- Amber overflowing blue (overcommitted): amber silently caps at span width
- Green exceeding amber (worked more than planned): green caps at ratio 1.0
- Overdue tasks: no red indicator past due date

### 4. Bars Too Thin to Be Useful
At 8px height, bars are indicators rather than a real visualization. The timeline should feel like an actual chart, not thin colored lines. This is the right time to fix this since we're touching bar rendering anyway.

### 5. No Combined Progress View
If a user tracks time with both pomodoro AND stopwatch on the same task, there's no way to see total combined progress vs estimate at a glance.

## Design Discussion — Key Decisions Needed

### Separate Lanes vs Single-Lane Mode-Aware

**Separate lanes per mode** (user's preferred direction):
- Blue span bar (time available)
- Pomodoro estimate bar (sessions x pixels, own scale)
- Stopwatch estimate bar (minutes x pixels, independent scale)
- Green actual work bar (or split into pomodoro actual + stopwatch actual)
- Total combined progress bar
- Pro: Each mode has its own honest scale, no conversion needed
- Pro: With taller rows, becomes a genuinely appealing visualization
- Con: More vertical space per row — fewer items visible without scroll
- Con: Items with only one mode would have empty lanes

**Single-lane mode-aware** (discussed alternative):
- Keep 3 bars but scale amber/green based on which estimate type is set
- Items with `estimated_minutes` use minutes-based scale
- Items with `estimated_pomodoros` use sessions-based scale
- Pro: Compact, no extra vertical space
- Con: Fragile when per-task pomodoro durations arrive
- Con: Can't show both modes on same item

**Current leaning**: Separate lanes with taller rows. The timeline is already the least dense view (14-day range), and users who use time tracking are exactly the users who benefit from richer visualization. Making rows taller turns thin indicators into a proper chart.

### Color Scheme Questions
- Should pomodoro and stopwatch estimates both be amber? No — user correctly identified this as confusing
- Need distinct colors per tracking mode that are still WCAG AA compliant
- Need a combined/total progress color that reads as "sum of both"
- Possible scheme (needs validation):
  - Blue: time span (unchanged)
  - Red/warm: pomodoro effort (matches pomodoro's red identity in status bar)
  - Blue/cool: stopwatch effort (matches stopwatch's blue identity in status bar)
  - Green: total actual work (combined from both modes)
  - The estimate bars match their mode color but lighter/desaturated

### Combined Progress Bar
User raised: if someone uses both pomodoros and stopwatch on a task, a total combined progress bar makes sense. This would show:
- Total `time_spent` (which already accumulates from both modes) against...
- Total estimated time (which needs both `estimated_minutes` and `estimated_pomodoros x work_duration` combined)
- This gives a single "how done is this task" indicator regardless of tracking method

### Adaptive Row Heights
Items with more data (both estimates, actual work) could get taller rows than items with just a blue span. This prevents wasting space on simple items while giving rich items room to breathe.

## Overflow Indicators (Implement Now)

### Amber Overflowing Blue (Overcommitted)
When estimated effort exceeds available time span:
- Amber bar extends past blue bar end
- Overflow section uses a hatched/striped pattern or distinct color
- Communicates: "you've estimated more work than time available"

### Green Exceeding Amber (Worked More Than Planned)
When actual sessions exceed estimate:
- Green bar extends past amber bar width
- Overflow section shifts color (e.g., yellow-green or darker green)
- Communicates: "you've worked more than you estimated"

### Overdue Indicator
When task is past due date:
- Red section from due_date to today on the time span bar
- Green bars can continue into red zone if work is ongoing
- Communicates: "this task is past deadline"

## Stopwatch Toolbar Icon
- Need a distinct `stopwatch.svg` matching existing icon style
- Current icons use simple line art with consistent stroke width
- Must not reuse play.svg — too confusing to have identical icons for different actions
- Icon should evoke a stopwatch/timer concept distinct from the play button

## Research Findings

### Bar Height Guidelines
- D3.js convention: **20-30px** per bar at standard DPI (96 DPI)
- Material Design: hide labels when bar height drops below 60px
- No universal standard, but 20-30px is industry consensus for readable bars
- Current 8px bars are well below any recommended minimum

### Color Differentiation
- Max **8-10 colors** reliably distinguishable in categorical data
- For our use case (3-5 bar types per row), well within limits
- Key principle: **dual encoding** — never rely on color alone. Use patterns, borders, or text labels as secondary channel
- Gray as baseline/planned, bold colors for actual — this is the Gantt chart standard
- WCAG 2.1 AA requires **3:1 contrast ratio** for graphical elements with neighbors
- Separate bars with white space to reduce contrast burden between adjacent bars

### Time Tracking Tool Patterns
- **Toggl, Clockify, Harvest** all use **separate horizontal lanes** (one row per task/entry)
- None use stacked bars for time tracking — lanes are the standard
- Bars represent time allocation on a horizontal timeline axis
- This validates our separate-lanes approach

### Stacked vs Grouped vs Lanes
- **Stacked bars have HIGH error rates** — only the bottom segment has a stable baseline, all others "float"
- **Grouped bars** are better for direct comparison (consistent baselines) but need more space
- **Separate lanes** (Gantt-style) are the standard for planned-vs-actual in project management
- Recommendation: lanes with overlaid or adjacent bars, not stacking
- Limit to **2-5 segments** per bar if any stacking is used

### Gantt Chart Estimated vs Actual Patterns
Standard industry approach:
- **Light gray bar** = planned/baseline/estimated
- **Darker colored bar** = actual progress, overlaid or adjacent
- **Conditional coloring**: green = on track, orange/red = delayed/overdue
- Text labels essential when bars overlap
- This is the pattern used by TeamGantt, MS Project, JIRA, etc.

### Material Design / Apple HIG
- Material Design: "Never omit space between bars", charts start at zero, emphasis on accessibility
- Apple HIG: principles-based (clarity, visual appeal, adaptability) — no specific pixel values
- Both emphasize responsive sizing and accessibility over fixed dimensions

### WCAG AA for Charts
- **3:1 minimum** contrast ratio between graphical elements and neighbors
- **4.5:1** for text within charts
- Must use dual encoding (color + something else)
- Dark themes enable more colors meeting 3:1

### Finalized Approach (Approved 2026-03-29)

**3-lane layout with split actual bar:**

| Lane | Height | Color | Purpose |
|------|--------|-------|---------|
| Time span | 6px | Blue | creation → due_date (context, not focus) |
| Estimate | 24px | Light gray (#D5D8DC) with 1px border | Total estimated effort |
| Actual work | 24px | Split red+blue | Total time_spent, subdivided by mode |

**Split actual bar:**
The actual work bar is one bar with two side-by-side segments sharing the same left-edge baseline:
- Red segment (#E74C3C, 60% opacity): pomodoro portion (from `focus_sessions WHERE session_type='work'`)
- Blue segment (#3498DB, 60% opacity): stopwatch portion (from `focus_sessions WHERE session_type='stopwatch'`)
- Total width = total time_spent. Read the whole bar for progress, or read segments for mode breakdown.
- Single-mode tasks show one color. Mixed-mode shows the split naturally.

**Why split bar over separate lanes:**
- ~70px rows instead of ~110px — more items visible
- The split bar IS the combined progress — no redundant "total" lane
- No empty lanes for single-mode tasks
- Follows Gantt "gray baseline + colored actual overlaid" standard
- 2 segments shares a common baseline — avoids the "floating baseline" error-prone stacked bar problem
- Well within 2-5 max segments research recommendation

**Estimate bar for mixed-mode tasks:**
When both `estimated_pomodoros` and `estimated_minutes` are set, convert to common unit (minutes) and sum: `(estimated_pomodoros × work_duration) + estimated_minutes`. One honest gray baseline.

**Adaptive row heights:**
- Items with no time data: ~16px (just 6px blue span + padding)
- Items with time data: ~70px (span + estimate + actual + gaps + padding)

**Overflow indicators:**
- Estimate exceeds time span: gray bar extends past blue bar end with diagonal stripe pattern
- Actual exceeds estimate: red/blue actual segments extend past gray bar width, overflow portion shifts darker
- Overdue: red tint on time span bar from due_date to today

## Timeline Interactivity Decision (2026-03-29)

**Decision: Read-only analytical view** (user has not finalized — leaning this way, revisit later)

### Arguments for passive/read-only:
- Day/week/month sub-views are already interactive task management surfaces — redundancy without value
- Professional analytics tools (Toggl, Clockify, Grafana, Jira burndowns) are universally passive
- The timeline x-axis is *time* and bars represent *effort* — dragging an unscheduled task onto a timeline has unclear semantics (what day? what effort?)
- Significant code for marginal value (drag-and-drop, context menus, editing infrastructure)
- pyqtgraph's interaction model is chart-oriented (zoom/pan/hover), not task-management-oriented

### What clicking DOES currently:
- Left click: emits `task_clicked` signal (selects task in other views)
- Hover: persistent tooltip with full task details
- Zoom/pan: mouse wheel on x-axis, drag to pan

### What it does NOT do (by design):
- No drag-and-drop acceptance from unscheduled panel
- No context menu for editing
- No inline editing
- No double-click-to-edit

### Unscheduled panel:
Tasks in the unscheduled panel are visible but cannot be dragged into the timeline. This is consistent with the timeline being a visualization, not an editor. Users manage tasks in list/board/month/week/day views, and see the results in the timeline.

### Sort order:
Currently sorts by creation time (from database order). Should be configurable — due date, time spent, estimated effort, or priority would be more analytically useful. This ties into timeline sub-views/filters.

### Revisit criteria:
If users report wanting to edit from the timeline, reconsider. But start with passive — it's the professional standard and avoids scope creep.

**Color scheme follows mode identity:**
- Red for pomodoro (matches status bar #E74C3C)
- Blue for stopwatch (matches status bar #3498DB)
- Gray for estimate (Gantt baseline convention)
- Users already associate these colors from status bar usage

## Mixed-Mode Tasks (Pomodoro + Stopwatch on Same Task)

A first-class scenario, not an edge case. Users will use pomodoro for structured deep work and stopwatch for follow-up, meetings, or less structured effort — on the same task.

### What Already Works
- `time_spent` accumulates from both modes — total is always correct
- `focus_sessions` records `session_type` ("work", "break", "stopwatch") — modes are distinguishable in queries
- `EditTimeSpentCommand(increment_pomodoro=False)` correctly separates pomodoro_count from stopwatch time

### What Needs Design
- **Timeline visualization**: Must show BOTH modes' contributions on the same row
- **Dual estimates**: If a task has `estimated_pomodoros=3` AND `estimated_minutes=45`, how is the estimate bar rendered? Options: sum to total minutes, show both separately, use whichever is larger
- **Completion logic**: Current auto-complete fires when `pomodoro_count >= estimated_pomodoros`. A mixed-mode task might have most work via stopwatch, never hitting the pomodoro threshold. Need to consider `time_spent` vs combined estimate.
- **Session history**: The floating dialog and any analytics views must distinguish session types when showing a mixed-mode task's history

### Design Principle
The task's total `time_spent` is ground truth. Estimates from either mode set expectations, but progress is judged on actual time invested vs whatever estimate(s) exist.

---

## Analytics Architecture

**The analytics data layer is now being implemented as `AnalyticsService` (`core/analytics.py`).** See `docs/plans/analytics-service.md` for the full architecture, DataFrame schemas, and integration plan.

The timeline widget will consume DataFrames from the analytics service rather than computing metrics inline. This replaces the current approach of reading TodoItem fields directly with proper analytical views.

### Timeline Sub-Views and Filters
The timeline should support sub-views or filter modes:
- Filter by tracking mode: "pomodoro only", "stopwatch only", "combined"
- Filter by tag, list, priority
- Different chart types per perspective (bar chart, heatmap, burndown, trend line)
- Follows existing sub-view pattern (Day/Week/Month/Timeline pills) — timeline could have its own mode toggles
- User wants many distinct measurements — proper analytics requires multiple perspectives

### Pandas DataFrames for Analytics
Instead of raw SQL + manual Python aggregation, use **pandas**:
- `focus_sessions` maps naturally to a DataFrame (start_time, end_time, duration, session_type, item_id, date)
- TodoItem time fields are natural DataFrame columns
- Provides: groupby, rolling averages, resampling, pivot tables, merge/join
- Statistical operations (mean session length, estimate accuracy, daily/weekly trends) are one-liners
- `pd.read_sql_query()` bridges SQLite → DataFrame directly
- Much of current and future tracking data fits pandas naturally
- Replaces dozens of SQL queries and Python loops with declarative operations

### Charting Library Instead of QPainter
Instead of hand-painting every chart:
- **matplotlib** → `FigureCanvasQTAgg` renders directly into QWidget. Proper axes, legends, gridlines, zoom, export (PDF/PNG) for free.
- **pyqtgraph** → lighter weight, real-time/interactive, native Qt integration
- **plotly** → web-based via QWebEngineView, interactive but heavier
- Keep QPainter for simple cell rendering (month/week/day views) where it works well
- Use charting library for analytics-heavy timeline and future chart types
- Handles responsive scaling, DPI awareness, color accessibility automatically
- Critical as analytics grow: overflow indicators, mode bars, adaptive heights, heatmaps, burndowns, trend lines would be unmaintainable in raw QPainter

### Pseudo-Real-Time Timeline Updates

**Problem:** During an active focus session (pomodoro or stopwatch), the timeline green bar is stale — it only reflects `time_spent` after the session is committed via `EditTimeSpentCommand` on stop/completion. A user could be 2 hours into a stopwatch session and the timeline shows zero progress for that session.

**Solution:** Pseudo-real-time projection in `paintEvent`. No database writes, no undo commands — display-only.

**Implementation (~10 lines):**
1. Pass `active_item_id` and `active_elapsed_seconds` to `_TimelineWidget` (from MainWindow, which already knows both via `_pomodoro` / `_stopwatch` widgets)
2. In `paintEvent`, when rendering green bars: if `item.id == active_item_id`, use `item.time_spent + active_elapsed_seconds` instead of `item.time_spent`
3. The existing 1-second `_pomodoro_display_timer` that drives the status bar also calls `_timeline_widget.update()` to trigger repaint — green bar grows in real time while watching

**Why pseudo-real-time over full real-time:**
- No undo stack pollution (no intermediate `EditTimeSpentCommand` pushes)
- No spurious `focus_session` records
- Matches how the status bar already works (display-only projection of in-progress state)
- Zero data model changes — purely a rendering concern
- On session stop/completion, the real `EditTimeSpentCommand` fires and the timeline transitions seamlessly from projected to committed state

**Edge case:** If the user is viewing a different list than the one containing the active item, no projection needed (item not visible). The active_item_id lookup naturally handles this.

### Dependency Considerations
- pandas is ~30MB, numpy ~20MB — significant size increase for packaged app
- matplotlib adds ~40MB more
- pyqtgraph is lighter (~5MB) but less feature-rich for static charts
- Could make analytics features optional (lazy import, graceful degradation without pandas)
- Decision needed: bundle always, or optional dependency?

## QPainter Implementation — Results and Lessons Learned

### What Was Built (2026-03-29)
- 3-lane layout: thin blue span (6px), gray estimate baseline (24px), split actual bar (24px)
- Split actual bar: red pomodoro + cyan stopwatch segments side by side
- Adaptive row heights: 20px compact, 74px full
- Theme-aware colors via semantic color system (Okabe-Ito light, ECharts dark)
- Overflow indicators: overdue tint, estimate overflow stripes, actual overflow overlay
- Pseudo-real-time updates during active sessions
- Stopwatch SVG icon

### Why QPainter Failed
Despite correct colors, layout logic, and data flow, the result looks amateur:

1. **Variable row heights create visual incoherence** — thin strips next to chunky blocks, no consistent rhythm
2. **No sticky headers** — date references disappear on scroll, making bars unreadable
3. **No sticky legend** — color reference disappears on scroll
4. **Completed item backgrounds overwhelm data** — green bands drown out actual bars
5. **No anti-aliasing on bars** — hard pixel edges look hand-drawn
6. **No hover states, tooltips on bars, or interactivity**
7. **No proper axes, gridlines, or tick marks**
8. **Every improvement requires manual pixel math** — unsustainable as analytics grow

**Core lesson:** QPainter is a drawing primitive, not a charting framework. Iterating on pixel values will never produce professional chart output. Professional time tracking tools (Toggl, Clockify, Harvest) all use charting libraries — this is simply how it's done.

### What QPainter IS Good For
- Calendar month/week/day cell rendering (simple, fixed-layout grids)
- Kanban card rendering
- Small UI decorations (step circles, progress rings)
- Anything where the layout is predetermined and the content is text/rectangles

### What Requires a Charting Library
- Timeline/Gantt visualization
- Burndown charts, trend lines
- Heatmaps, distribution charts
- Any chart where the user expects professional visual quality, interactivity, zoom, export

## Path Forward — Charting Library Migration

**The QPainter timeline implementation is a placeholder.** It works functionally (data flows correctly, theme colors are wired, pseudo-real-time updates work) but needs to be replaced with a proper charting library for professional output.

### Requirements for the charting solution:
1. Renders into a QWidget (embeddable in the existing CalendarViewWidget)
2. Dark and light theme support
3. Horizontal bar/Gantt chart with multiple series per row
4. Sticky axis headers
5. Hover tooltips on bars
6. Zoom and pan
7. Anti-aliased, polished rendering
8. Exportable (PNG, PDF)
9. Supports real-time data updates without full re-render

### Data pipeline:
- pandas DataFrames as the analytics data layer
- SQLite → pandas via `pd.read_sql_query()`
- DataFrame → charting library for visualization
- This is the standard professional stack

### Library Research Results (2026-03-29)

Thorough comparison of matplotlib, pyqtgraph, plotly+QWebEngineView, and QtCharts.

#### Recommendation: pyqtgraph (primary) + matplotlib (static reports)

**pyqtgraph for real-time timeline:**

| Criteria | pyqtgraph |
|----------|-----------|
| PyQt6 compatible | Yes, full support |
| Gantt/horizontal bars | Yes, `BarGraphItem` |
| 1-second real-time updates | Native strength — GPU-accelerated via QGraphicsScene |
| Dark/light theme | Programmatic via QColor/QPen/QBrush, use QDarkStyle for polish |
| Hover tooltips | Built-in `setToolTip()` |
| Click events | `mouseClickEvent` on items |
| Zoom/pan | Built-in via ViewBox |
| Package size | ~3-5 MB (tiny) |
| Memory overhead | Low |
| License | MIT (free, no restrictions) |
| Actively maintained | Yes |
| Learning curve | Easy — uses Qt primitives directly |

**Why not the others:**

- **matplotlib**: Good for static charts but requires blitting complexity for 1-sec updates. Better suited for PDF export and static reports (use as secondary).
- **plotly + QWebEngineView**: Best interactivity/polish but +200MB memory, +150MB bundle, slow at 1-sec refresh rate. Overkill for desktop.
- **QtCharts**: GPL-only license — requires commercial license for proprietary use or open-sourcing.

**Dual-library strategy:**
- pyqtgraph for all real-time, interactive timeline/analytics views in the app
- matplotlib for static report generation (PDF export, print) when analytics phases D-F arrive
- pandas as the data pipeline for both (SQLite → DataFrame → chart)

#### Sticky Headers
No library natively supports frozen axis headers on scroll. All require a custom QWidget layout:
- Top: frozen date axis (separate QFrame)
- Main: scrollable plot area
- Synchronize via QScrollBar signals
This is medium complexity but well-documented.

#### Key Implementation Notes
- `BarGraphItem` takes arrays: x, y, width, height, brushes — maps naturally to DataFrame columns
- `setData()` call triggers efficient redraw (no full replot needed)
- Multiple `BarGraphItem` instances layer for split actual bars (pomodoro + stopwatch)
- QDarkStyle or PyQtDarkTheme for polished appearance beyond pyqtgraph defaults
- Event handlers: subclass `BarGraphItem`, override `mouseClickEvent` / `hoverEvent`

#### Sources
- pyqtgraph.org — official docs, BarGraphItem API
- pythonguis.com/tutorials/pyqt6-plotting-pyqtgraph/ — PyQt6 integration tutorial
- matplotlib.org/stable/gallery/user_interfaces/embedding_in_qt_sgskip.html — Qt embedding
- plotly.com/python/gantt/ — Gantt chart reference (for design inspiration)
- riverbankcomputing.com/commercial/license-faq — QtCharts licensing
