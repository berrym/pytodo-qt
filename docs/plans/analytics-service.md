# Analytics Service — Pandas Data Pipeline

## Implementation Status (2026-03-30)

**Fully implemented and integrated.** `core/analytics.py` is live with 12 public methods, version-counter cache, 56 tests. Consumers:
- **MainWindow**: daily goal, streak, focus score, milestones (replaced manual loops)
- **FocusStatsDialog**: summary cards, weekly chart, top tasks, insights (replaced 300+ lines of manual aggregation)
- **Timeline sub-views**: Daily chart uses `daily_summary()` + `rolling_averages()`, Productivity uses `time_block_analysis()`, Accuracy uses `estimate_accuracy()`

---

## Why This Exists

The app tracks rich time data across two modes (pomodoro and stopwatch) with per-session granularity in a SQLite database. Until now, all analytics were computed ad-hoc — manual Python loops in MainWindow, FocusStatsDialog, and the timeline widget, each duplicating similar aggregation logic with raw SQL queries.

This is the wrong architecture. Professional analytics applications use a data pipeline:

```
SQLite → pandas DataFrame → analytical views → visualization (pyqtgraph/matplotlib)
```

The AnalyticsService is the missing middle layer. It reads from SQLite, produces typed DataFrames with computed analytical columns, caches results, and serves every consumer in the app — timeline, stats dialog, daily goal tracking, milestone detection, and all future chart widgets.

## Why Pandas

Decision documented in `docs/plans/charting-library-decision.md`. Summary:

- **pd.read_sql_query()** bridges SQLite to DataFrames directly — no manual row iteration
- **groupby, rolling, resample** replace dozens of manual aggregation loops
- **Statistical operations** (mean, correlation, percentile) are one-liners
- **BSD 3-Clause license** — GPL v3 compatible, PySide6 compatible for future migration
- **Industry standard** for data analytics in Python — well-documented, well-tested, actively maintained
- **~30 MB + numpy ~20 MB** — bundle size is not a concern (user confirmed)

## Architecture

### Module: `src/pytodo_qt/core/analytics.py`

**Pure Python + pandas. No Qt dependency.** Testable without Qt, importable without a running application.

### Class: `AnalyticsService`

```
AnalyticsService(connection: sqlite3.Connection, work_duration_minutes: int = 25)
│
├── Configuration
│   ├── invalidate()                    # Bump cache version, forces re-query
│   └── set_work_duration(minutes)      # Update pomodoro duration (affects conversions)
│
├── Session-Level Analytics
│   ├── sessions(filters...)            # Base DataFrame: all sessions with computed fields
│   └── time_block_analysis()           # 2-hour blocks with completion rates
│
├── Daily Analytics
│   ├── daily_summary(filters...)       # Per-day aggregates (sessions, minutes, rates)
│   ├── weekly_chart(week_start)        # 7-day breakdown for bar charts
│   └── rolling_averages(windows)       # 7d/30d rolling means for trend lines
│
├── Item-Level Analytics
│   ├── item_summary(list_id)           # Per-item productivity metrics
│   ├── estimate_accuracy(list_id)      # Actual vs estimated per item
│   └── top_items(start, end, limit)    # Top items ranked by session count
│
└── Scalar Metrics
    ├── streak(daily_goal)              # Consecutive-day count (int)
    └── focus_score(daily_goal, today)  # 0-100 score or -1 (int)
```

### Data Flow

```
                    ┌─────────────────┐
                    │   SQLite DB     │
                    │  (WAL mode)     │
                    └────────┬────────┘
                             │ pd.read_sql_query()
                    ┌────────▼────────┐
                    │ AnalyticsService│
                    │  (cached DFs)   │
                    └────────┬────────┘
                             │ DataFrame / scalar
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───┐   ┌─────▼─────┐  ┌─────▼─────┐
     │  Timeline  │   │ FocusStats │  │ MainWindow│
     │  (pyqtgraph)│   │  Dialog   │  │  (goals,  │
     │            │   │           │  │  streaks) │
     └────────────┘   └───────────┘  └───────────┘
```

### Cache Strategy

Version-counter pattern. Simple, correct, and efficient at this data scale.

- Each DataFrame cached with a version number
- `invalidate()` bumps the version counter
- Stale cache entries (version mismatch) trigger re-query on next access
- Cache keys include method name + filter parameters

**Invalidation triggers** (called by MainWindow, not by the service):
1. After recording a focus session (`_record_focus_session`)
2. After sync merges focus sessions from a peer (`_merge_sync_data_internal`)
3. After switching the active list (context change)

**NOT invalidated** on the 1-second display timer — the active session projection is a UI concern handled by consumers, not by rebuilding DataFrames.

## DataFrame Schemas

### `sessions()` — the foundation everything derives from

| Column | Type | Source |
|--------|------|--------|
| id | str | focus_sessions.id |
| item_id | str | focus_sessions.item_id |
| list_id | str | focus_sessions.list_id |
| start_time | datetime64 | Parsed from ISO 8601 |
| end_time | datetime64 | Parsed from ISO 8601 |
| duration_seconds | int64 | focus_sessions.duration_seconds |
| duration_minutes | float64 | Computed: duration_seconds / 60.0 |
| completed | bool | focus_sessions.completed (cast from int) |
| session_type | str | "work", "break", or "stopwatch" |
| date | datetime64 | Parsed from YYYY-MM-DD |
| hour_of_day | int64 | start_time.dt.hour |
| day_of_week | int64 | 0=Monday through 6=Sunday |
| day_name | str | Monday, Tuesday, ... |
| is_work | bool | session_type == "work" |

Filters: `start_date`, `end_date`, `list_id`, `item_id`, `session_type`

### `daily_summary()`
Per-day row with: date, total_sessions, completed_sessions, interrupted_sessions, total_minutes, work_minutes, stopwatch_minutes, completion_rate (0.0-1.0)

### `item_summary()`
Per-item row with: item_id, total_seconds, total_minutes, work_sessions, completed_sessions, interrupted_sessions, stopwatch_sessions, completion_rate, avg_session_minutes

### `estimate_accuracy()`
Per-item row with: item_id, estimated_minutes (combined from both estimate types using work_duration), actual_minutes (from time_spent), accuracy_ratio (actual/estimated), variance_minutes (actual - estimated)

### `weekly_chart()`
7 rows (Mon-Sun) with: date, day_name, session_count, total_minutes

### `rolling_averages()`
Per-day row with: date, daily_sessions, daily_minutes, rolling_7d_sessions, rolling_7d_minutes, rolling_30d_sessions, rolling_30d_minutes

### `time_block_analysis()`
12 rows (2-hour blocks) with: block_start_hour, block_label, session_count, completed_count, completion_rate, avg_duration_minutes

### `top_items()`
Top N items by session count with: item_id, session_count, total_minutes, completed_sessions

## Design Decisions

### pd.read_sql_query() over in-memory lists
The in-memory `Database.focus_sessions` list has no indexing. SQL WHERE clauses with indexed columns are more efficient for filtered views. The items table data (needed for estimate_accuracy joins) is only complete in SQLite, not fully mirrored in the Database dataclass.

### Service does NOT resolve item names
Returns `item_id` strings. UI consumers join with `Database.lists` to get display names. This keeps the analytics layer free of the in-memory Database dependency and makes it independently testable.

### Version-counter cache, not TTL-based
The app has discrete mutation events (session recorded, sync completed). A version counter is simpler and more correct than time-based expiry. No stale data risk.

### No Qt dependency
The service imports only `sqlite3`, `pandas`, and standard library modules. This means:
- Unit tests run without `QT_QPA_PLATFORM=offscreen`
- The service can be used in CLI tools or scripts
- Import doesn't trigger Qt initialization

### Scalars where appropriate
`streak()` and `focus_score()` return integers, not single-row DataFrames. They're inherently scalar results. They use cached sessions DataFrames internally but expose clean scalar APIs.

## Relationship to Existing Systems

### What it replaces
- `MainWindow._get_today_session_count()` → `analytics.sessions().query("completed").shape[0]`
- `MainWindow._compute_focus_score()` → `analytics.focus_score(goal)`
- `MainWindow._check_milestones()` lifetime count → `analytics.sessions(session_type="work")`
- `FocusStatsDialog._count_work_sessions()` → `analytics.sessions()`
- `FocusStatsDialog._sum_work_duration()` → `analytics.daily_summary()`
- `FocusStatsDialog._compute_week_counts()` → `analytics.weekly_chart()`
- `FocusStatsDialog._compute_top_tasks()` → `analytics.top_items()`
- `FocusStatsDialog` 6 insight helper methods → `analytics.time_block_analysis()` + `analytics.item_summary()`

### What it does NOT replace
- `DatabaseStorage` query methods — those continue to exist for sync, migration, and non-analytics access
- `TodoItem` fields (`time_spent`, `pomodoro_count`) — item-level data accessed directly, not through analytics
- Active session projection — UI-level concern, not analytics
- Undo/redo — analytics never writes to the database

### What it enables (future)
- **Burndown charts**: `daily_summary()` with cumulative task completion
- **Heatmaps**: `time_block_analysis()` across weeks/months
- **Trend lines**: `rolling_averages()` in pyqtgraph line plots
- **PDF reports**: DataFrames → matplotlib static charts → PDF export
- **Tag-based analytics**: `sessions()` joined with item tags
- **Estimate calibration**: `estimate_accuracy()` over time to improve future estimates
- **Timeline sub-views**: Filter sessions by mode/tag/priority for different chart perspectives

## Testing Strategy

### Test file: `tests/test_analytics.py`

In-memory SQLite fixtures — no real database, no Qt.

~40-50 tests covering:
1. **Empty data** (5): Every method returns valid empty DataFrame or 0/default
2. **Sessions** (8): Column types, computed fields, filtering
3. **Daily summary** (5): Aggregation, zero-session days, completion_rate edge cases
4. **Item summary** (5): Per-item grouping, mixed-mode tasks
5. **Weekly chart** (3): 7 rows always, zero-session days
6. **Rolling averages** (4): Window sizes, short data series
7. **Streak** (5): Consecutive counting, goal threshold, gaps
8. **Focus score** (4): Components weighted correctly, -1 for no data
9. **Time blocks** (3): 12 blocks, completion rates
10. **Estimate accuracy** (3): Combined estimates, ratio calculation
11. **Cache** (4): Same-version hits, invalidation, filter-key isolation

## Dependencies

Already in `pyproject.toml`:
```toml
"pandas>=2.0",
```

numpy is installed as a pandas dependency. No additional dependencies needed.
