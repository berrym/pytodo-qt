# Natural Language Task Input -- Design Document

## Purpose

Replace the multi-field AddTodoDialog with a single smart text input where users type tasks the way they think about them. The parser extracts structured fields (dates, times, priority, tags, recurrence, pomodoro estimates) from free-form English text, leaving the remainder as the reminder. No external NLP dependencies -- everything is regex-based and fully offline.

Example: typing `Buy groceries tomorrow at 3pm @errands p1` produces:

| Field | Value |
|-------|-------|
| reminder | Buy groceries |
| due_date | tomorrow's date |
| due_time | 15:00 |
| tags | ["@errands"] |
| priority | 1 (High) |

This makes creating todos feel as natural as writing a sentence.

## Parser Architecture

### Module Location

`src/pytodo_qt/core/nlp_parser.py` -- pure Python, no Qt dependency. This keeps it testable without `QT_QPA_PLATFORM=offscreen` and usable from both the desktop GUI and the web API.

### Core Data Structure

```python
@dataclass
class ParseResult:
    """Result of parsing a natural language task input."""
    reminder: str                          # Everything not claimed by an entity
    due_date: date | None = None
    due_time: time | None = None
    priority: int | None = None            # 1-3, None means use default
    tags: list[str] = field(default_factory=list)
    recurrence_type: str | None = None     # "daily", "weekly", "monthly", "yearly"
    recurrence_interval: int = 1
    recurrence_end_date: date | None = None
    recurrence_end_count: int | None = None
    pomodoro_estimate: int | None = None   # Estimated number of pomodoro sessions
    spans: list[EntitySpan] = field(default_factory=list)  # For UI highlighting

@dataclass
class EntitySpan:
    """A parsed entity's location in the original text."""
    start: int          # Character offset in original input
    end: int            # Character offset (exclusive)
    kind: EntityKind    # What type of entity
    display: str        # Human-readable summary, e.g. "Mar 15" or "High"

class EntityKind(Enum):
    DATE = "date"
    TIME = "time"
    PRIORITY = "priority"
    TAG = "tag"
    RECURRENCE = "recurrence"
    POMODORO = "pomodoro"
```

### Parsing Strategy

The parser operates in a single pass with greedy matching, processing entities in a fixed priority order. Each entity matcher marks the character span it consumed. After all matchers run, everything not consumed becomes the reminder text.

**Order of matching (highest priority first):**

1. **Tags** -- `@word` or `#word` tokens. Unambiguous syntax, never conflicts.
2. **Priority** -- `p1`, `p2`, `p3`, `!`, `!!`, `!!!`, `high priority`, etc.
3. **Recurrence** -- `every day`, `weekly`, `daily for 2 weeks`, etc. Must match before dates because "every Monday" contains a day name.
4. **Pomodoro estimates** -- `~3 pomodoros`, `~2p`, `~1 pom`. Tilde prefix prevents false positives.
5. **Dates** -- `tomorrow`, `next Friday`, `March 15`, `in 3 days`, etc.
6. **Times** -- `at 3pm`, `by noon`, `at 14:00`. Only matched if a date was also found (standalone time without date is ambiguous).

**Greedy from the end:** When the same text could be reminder or an entity, the parser prefers treating it as reminder text. Entities are typically appended to the end of a task description, so the parser scans for patterns anywhere in the string but prefers end-of-string matches when there is ambiguity.

**Remainder extraction:** After all entity spans are collected, they are sorted and removed from the original string. The remaining text is stripped and collapsed (multiple spaces become one). This is the reminder.

```python
def parse(text: str, today: date | None = None) -> ParseResult:
    """Parse a natural language task description into structured fields.

    Args:
        text: Raw user input, e.g. "Buy groceries tomorrow at 3pm @errands"
        today: Override for today's date (for testing). Defaults to date.today().
    """
```

The `today` parameter enables deterministic testing without date mocking.

## Pattern Specifications

### Dates

| Pattern | Example Input | Result |
|---------|--------------|--------|
| `today` | "finish report today" | date.today() |
| `tomorrow` | "call dentist tomorrow" | today + 1 day |
| `yesterday` | "log hours yesterday" | today - 1 day |
| Day name | "submit PR Friday" | Next occurrence of that weekday |
| `next <day>` | "meet Sarah next Tuesday" | The Tuesday after this coming one |
| `next week` | "review code next week" | today + 7 days |
| `next month` | "renew license next month" | today + 1 month |
| `in N days` | "follow up in 3 days" | today + 3 |
| `in N weeks` | "review in 2 weeks" | today + 14 |
| `in N months` | "check back in 3 months" | today + 3 months |
| Month + day | "submit by March 15" | March 15 of current/next year |
| Month + day + year | "deadline January 1 2027" | January 1, 2027 |
| ISO date | "due 2026-03-15" | March 15, 2026 |
| `MM/DD` | "due 3/15" | March 15 of current/next year |
| `MM/DD/YYYY` | "due 3/15/2026" | March 15, 2026 |

**Day name resolution:** "Friday" means the upcoming Friday. If today is Friday, it means next Friday (7 days out), not today. `next Friday` means the Friday of the following week. This avoids confusion -- if the user wanted today, they would type "today".

**Month + day ambiguity:** "March 15" resolves to the current year if March 15 has not yet passed, otherwise next year. "March 15 2025" always uses the explicit year regardless.

**Regex patterns:**

```python
# Day names (case-insensitive)
_DAYS = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_MONTHS = r"(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"

_DATE_PATTERNS = [
    (r"\btoday\b", _resolve_today),
    (r"\btomorrow\b", _resolve_tomorrow),
    (r"\byesterday\b", _resolve_yesterday),
    (r"\bnext\s+" + _DAYS + r"\b", _resolve_next_day),
    (r"\b" + _DAYS + r"\b", _resolve_day),
    (r"\bnext\s+week\b", _resolve_next_week),
    (r"\bnext\s+month\b", _resolve_next_month),
    (r"\bin\s+(\d+)\s+days?\b", _resolve_in_days),
    (r"\bin\s+(\d+)\s+weeks?\b", _resolve_in_weeks),
    (r"\bin\s+(\d+)\s+months?\b", _resolve_in_months),
    (r"\b" + _MONTHS + r"\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?\b", _resolve_month_day),
    (r"\b(\d{4})-(\d{2})-(\d{2})\b", _resolve_iso_date),
    (r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", _resolve_slash_date),
]
```

### Times

| Pattern | Example Input | Result |
|---------|--------------|--------|
| `at HH:MM` | "meeting at 14:30" | time(14, 30) |
| `at H:MMam/pm` | "call at 2:30pm" | time(14, 30) |
| `at Ham/pm` | "lunch at noon" | time(12, 0) |
| `by HH:MM` | "finish by 17:00" | time(17, 0) |
| `noon` | "lunch at noon" | time(12, 0) |
| `midnight` | "deploy at midnight" | time(0, 0) |
| `morning` | "run tomorrow morning" | time(9, 0) |
| `afternoon` | "meet Tuesday afternoon" | time(14, 0) |
| `evening` | "dinner Friday evening" | time(18, 0) |
| `end of day` / `eod` | "submit eod" | time(17, 0) |

**Time without date:** If a time pattern is found but no date was parsed, the time is still captured in the ParseResult but no date is inferred. The UI can decide whether to default the date to today. This prevents false positives -- "at 3pm" alone in the input could be part of a description like "movie showing at 3pm is sold out".

**Exception:** When time appears alongside words like "today", "tomorrow", or a day name in the same input, the date is inferred from context as expected. The rule only applies to inputs with time but zero date-like tokens.

```python
_TIME_PATTERNS = [
    (r"\b(?:at|by)\s+(\d{1,2}):(\d{2})\s*(am|pm)\b", _resolve_time_12h),
    (r"\b(?:at|by)\s+(\d{1,2})\s*(am|pm)\b", _resolve_time_12h_no_min),
    (r"\b(?:at|by)\s+(\d{1,2}):(\d{2})\b", _resolve_time_24h),
    (r"\b(?:at|by)\s+noon\b", lambda: time(12, 0)),
    (r"\b(?:at|by)\s+midnight\b", lambda: time(0, 0)),
    (r"\bnoon\b", lambda: time(12, 0)),
    (r"\bmidnight\b", lambda: time(0, 0)),
    (r"\bmorning\b", lambda: time(9, 0)),
    (r"\bafternoon\b", lambda: time(14, 0)),
    (r"\bevening\b", lambda: time(18, 0)),
    (r"\b(?:eod|end of day)\b", lambda: time(17, 0)),
]
```

### Priority

| Pattern | Example Input | Result |
|---------|--------------|--------|
| `p1` | "fix crash p1" | 1 (High) |
| `p2` | "update docs p2" | 2 (Normal) |
| `p3` | "clean up logs p3" | 3 (Low) |
| `!` | "fix crash !" | 1 |
| `!!` | "fix crash !!" | 1 |
| `!!!` | "fix crash !!!" | 1 |
| `high priority` | "fix crash high priority" | 1 |
| `low priority` | "refactor low priority" | 3 |
| `urgent` | "deploy fix urgent" | 1 |

Multiple exclamation marks all map to priority 1 (High). The priority system is 1-3, not 1-5, matching the existing `TodoItem.priority` field (1=High, 2=Normal, 3=Low).

```python
_PRIORITY_PATTERNS = [
    (r"\bp([1-3])\b", _resolve_p_number),         # p1, p2, p3
    (r"\b(!!!?)\s*$", lambda: 1),                  # ! or !! or !!! at end
    (r"\bhigh\s+prio(?:rity)?\b", lambda: 1),
    (r"\blow\s+prio(?:rity)?\b", lambda: 3),
    (r"\burgent\b", lambda: 1),
]
```

### Tags

Tags use `@` or `#` prefix and match word characters (letters, digits, underscores, hyphens).

| Pattern | Example Input | Result |
|---------|--------------|--------|
| `@word` | "call plumber @home" | ["@home"] |
| `#word` | "deploy #release" | ["#release"] |
| Multiple | "fix bug @work #urgent" | ["@work", "#urgent"] |

```python
_TAG_PATTERN = re.compile(r"(?<!\S)[@#]([\w-]+)\b")
```

The `(?<!\S)` lookbehind ensures the `@`/`#` is at a word boundary or start of string, preventing email addresses from being parsed as tags (e.g., `email user@example.com` does not extract `@example`).

Tags parsed from the smart input use the same format as existing tags in the app: the `@` prefix is preserved. `#` tags are converted to `@` format for storage since `TodoItem.tags` uses `@` prefix by convention.

### Recurrence

Recurrence parsing is the most complex entity type due to the variety of natural language expressions.

| Pattern | Example Input | recurrence_type | interval | end condition |
|---------|--------------|-----------------|----------|---------------|
| `every day` | "take pills every day" | daily | 1 | -- |
| `daily` | "standup daily" | daily | 1 | -- |
| `every N days` | "water plants every 3 days" | daily | 3 | -- |
| `every week` / `weekly` | "review weekly" | weekly | 1 | -- |
| `every N weeks` | "report every 2 weeks" | weekly | 2 | -- |
| `every month` / `monthly` | "pay rent monthly" | monthly | 1 | -- |
| `every N months` | "dentist every 6 months" | monthly | 6 | -- |
| `every year` / `yearly` / `annually` | "renew license yearly" | yearly | 1 | -- |
| `daily for N days` | "take pills daily for 10 days" | daily | 1 | end_count=10 |
| `weekly for N weeks` | "sprint review weekly for 6 weeks" | weekly | 1 | end_count=6 |
| `every day for N days` | "take pills every day for 10 days" | daily | 1 | end_count=10 |
| `every week until <date>` | "report every week until June 1" | weekly | 1 | end_date=Jun 1 |
| `N times a day` | "stretch 3 times a day" | daily | 1 | **see note** |
| `N times a week` | "exercise 3 times a week" | weekly | 1 | **see note** |

**Note on "N times a day/week":** The current recurrence model does not support multiple occurrences per interval. `3 times a week` cannot be faithfully represented as a single `recurrence_type=weekly, interval=1` rule because the model has no concept of "3 occurrences within each weekly period." Two options:

1. **Current approach (recommended):** Parse `3 times a week` as `weekly` with `interval=1` and add a parenthetical note to the reminder: `"stretch (3x/week)"`. This preserves the user's intent in a human-readable way without requiring a model extension.
2. **Future model extension:** Add a `frequency_per_interval` field to `TodoItem`. This is out of scope for the initial implementation but documented here as a possible enhancement.

**"every Monday and Thursday":** Multi-day recurrence (e.g., specific days of the week) is not supported by the current recurrence model. The parser should not attempt to parse this -- it falls through to reminder text. The advanced fields remain available for users who need to set up such patterns manually (or a future model extension adds `recurrence_days: list[int]`).

**Recurrence end condition parsing:** The `for N days/weeks` pattern calculates `end_count` directly. The `until <date>` pattern reuses the date parser to resolve the end date.

```python
_RECURRENCE_PATTERNS = [
    # "every N days/weeks/months/years"
    (r"\bevery\s+(\d+)\s+(days?|weeks?|months?|years?)\b", _resolve_every_n),
    # "every day/week/month/year"
    (r"\bevery\s+(day|week|month|year)\b", _resolve_every_unit),
    # "daily/weekly/monthly/yearly/annually" with optional "for N ..."
    (r"\b(daily|weekly|monthly|yearly|annually)\b", _resolve_frequency_word),
    # "for N days/weeks" suffix (attaches to preceding recurrence)
    (r"\bfor\s+(\d+)\s+(days?|weeks?|months?|years?)\b", _resolve_end_count),
    # "until <date>" suffix
    (r"\buntil\s+(.+?)(?:\s+(?:at|by|p[1-3]|@|#|~)|\s*$)", _resolve_end_date),
    # "N times a day/week/month"
    (r"\b(\d+)\s+times?\s+a\s+(day|week|month)\b", _resolve_times_per),
]
```

### Pomodoro Estimates

Pomodoro estimates let users set an expected effort level when creating a task. The tilde (`~`) prefix distinguishes these from other numbers in the input.

| Pattern | Example Input | Result |
|---------|--------------|--------|
| `~Np` | "write report ~3p" | 3 |
| `~N pomodoros` | "refactor ~2 pomodoros" | 2 |
| `~N pom` | "review PR ~1 pom" | 1 |
| `~N poms` | "design doc ~4 poms" | 4 |
| `~N sessions` | "debug ~2 sessions" | 2 |

```python
_POMODORO_PATTERN = re.compile(
    r"~(\d+)\s*(?:p(?:omodoros?|oms?)?|sessions?)\b", re.IGNORECASE
)
```

**Data model note:** `TodoItem` does not currently have a `pomodoro_estimate` field. Adding one requires a schema migration (v11). Until then, the parsed estimate can be stored in a future field or surfaced only in the UI as informational. The parser should extract it regardless so the feature is ready when the field is added. The `ParseResult` carries the value; the `AddTodoDialog` can display it without persisting it.

## Input UX

### Smart Input Field

The smart input replaces the top-level text field in `AddTodoDialog`. It is a custom `QLineEdit` subclass (or `QTextEdit` for multi-line support) that provides real-time parse feedback.

**File:** `src/pytodo_qt/gui/widgets/smart_input.py`

#### Real-Time Highlighting

As the user types, the parser runs on every keystroke (debounced by 100ms via `QTimer.singleShot` to avoid lag on fast typing). Recognized entities are highlighted inline using `QTextCharFormat` with distinct colors:

| Entity | Color | Example Appearance |
|--------|-------|--------------------|
| Date | Blue (#4A90D9) | `tomorrow` in blue |
| Time | Blue (#4A90D9) | `at 3pm` in blue (same as date -- they are related) |
| Priority | Orange (#E8912D) | `p1` in orange |
| Tag | Teal (#2DA5A5) | `@errands` in teal |
| Recurrence | Green (#5BA55B) | `every day` in green |
| Pomodoro | Purple (#8B5CF6) | `~3p` in purple |
| Remainder | Default text color | "Buy groceries" in normal color |

Colors are drawn from the current theme palette so they work in both light and dark mode. The theme module already provides `highlight`, `text`, and accent colors.

**Implementation:** Use a `QTextEdit` with `QSyntaxHighlighter` subclass. The highlighter calls `parse()` on the current text and applies `QTextCharFormat` to each `EntitySpan`. This is the same pattern Qt uses for code editors.

```
class SmartInputHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text: str) -> None:
        result = parse(text)
        for span in result.spans:
            fmt = self._format_for(span.kind)
            self.setFormat(span.start, span.end - span.start, fmt)
```

#### Preview Chips

Below the input field, a horizontal row of small chip widgets shows the parsed values. Each chip has:

- An icon or colored dot matching the entity color
- A short text label: "Tomorrow 3:00 PM", "High", "@errands", "Every day", "~3 pom"
- A small X button to remove that entity from the input text

Chips update live as the user types. Clicking the X on a chip removes the corresponding text span from the input and re-parses.

```
 ┌─────────────────────────────────────────────────────────┐
 │ Buy groceries tomorrow at 3pm @errands p1               │
 └─────────────────────────────────────────────────────────┘
   [Tomorrow 3:00 PM x]  [@errands x]  [High x]
```

Chips are implemented as a `QHBoxLayout` of small `QPushButton` widgets with custom styling (rounded rectangle, colored background matching entity type at 15% opacity, colored text).

#### Advanced Mode Toggle

A small "Advanced" link/button below the chips expands the full discrete field editors (the current AddTodoDialog form layout). When expanded:

- The parsed values from the smart input are pre-populated into the discrete fields
- Editing a discrete field updates the smart input text accordingly (bidirectional sync)
- The toggle label changes to "Simple" to collapse back

This ensures power users and accessibility needs are met -- the smart input is a convenience layer, not a replacement for structured input.

```
 ┌─────────────────────────────────────────────────────────┐
 │ Buy groceries tomorrow at 3pm @errands p1               │
 └─────────────────────────────────────────────────────────┘
   [Tomorrow 3:00 PM x]  [@errands x]  [High x]

   [v Advanced]
   ┌───────────────────────────────────────────────────────┐
   │ Priority:    [High    v]                              │
   │ Due Date:    [x] [2026-03-09]                         │
   │ Due Time:    [x] [15:00     ]                         │
   │ Tags:        [@errands            ]                   │
   │ Recurrence:  [ ] Every [1] [Day(s) v]                 │
   └───────────────────────────────────────────────────────┘
```

#### Tag Completion

When the user types `@`, a completion popup appears showing previously used tags from the database. The popup filters as the user continues typing.

**Data source:** `Database.active_lists()` -> iterate all items -> collect unique tags. Cache this on dialog open (not on every keystroke). The existing `SearchFilterWidget` already collects tags for its filter dropdown -- the same collection logic can be extracted into a shared helper.

**Implementation:** `QCompleter` attached to the `QTextEdit`, activated when the cursor is after a `@` or `#` character. The completer's model is a `QStringListModel` populated with known tags.

### Keyboard Interaction

| Key | Behavior |
|-----|----------|
| Enter | Accept the parsed input (same as OK button) |
| Escape | Cancel the dialog |
| Tab | When inside a `@` token, accept the top completion suggestion |
| Ctrl+Enter | Accept input and immediately start a pomodoro session on the new item |
| Up/Down | Navigate tag completion popup |

### Inline Table Editing

The existing inline reminder `QLineEdit` in `TodoTableWidget` can optionally be made smart-parse-aware. When the user edits a reminder inline and the new text contains a recognized entity pattern, a subtle tooltip or popup asks: "Detected 'tomorrow' -- set due date?" This is non-intrusive -- the inline edit remains a simple text field by default.

**Implementation priority:** This is a stretch goal. The primary integration point is `AddTodoDialog`. Inline smart parsing can be added later without architectural changes since the parser is a standalone module.

## Parsing Rules and Edge Cases

### Rule 1: Remainder Is Everything Not Claimed

The reminder text is constructed by removing all matched entity spans from the input and cleaning up whitespace. Leading/trailing whitespace and double spaces are collapsed.

```
Input:  "Buy groceries tomorrow at 3pm @errands p1"
Spans:  [15:23 DATE] [24:30 TIME] [31:39 TAG] [40:42 PRIORITY]
Remove: "Buy groceries                           "
Clean:  "Buy groceries"
```

### Rule 2: No False Positives

When a token is ambiguous, the parser does NOT extract it. Examples:

| Input | Parsing Decision |
|-------|-----------------|
| "Watch Friday the 13th" | "Friday" could be a date, but "Friday the 13th" is likely a movie title. However, the parser cannot know this -- it will extract "Friday" as a date. **This is acceptable.** Users can use Advanced mode to correct false positives, and the preview chips make them visible. |
| "Buy 3 apples" | "3" is just a number, not a priority. No extraction. |
| "Meeting at the office" | "at the office" -- "at" followed by non-time text. No time extraction. |
| "Priority seating" | "Priority" is part of the phrase, not a command. Only `high priority` and `low priority` as complete phrases trigger extraction. |
| "Tell John p1ckup the car" | `p1` must be at a word boundary. `p1ckup` does not match `\bp1\b`. |

### Rule 3: Last Match Wins for Conflicting Entities

If the input contains two date patterns (e.g., "schedule for tomorrow, actually make it Friday"), the last match in the string wins. This matches natural correction behavior.

### Rule 4: Recurrence Implies Due Date

If a recurrence pattern is matched but no date pattern is found, the parser sets `due_date = today`. A recurring task without a start date defaults to starting today. This mirrors the behavior in the existing `AddTodoDialog` where recurrence requires a due date to be set.

### Rule 5: Prefix Words Are Consumed

Context words immediately before an entity are consumed with it:

- "due tomorrow" -- "due" is consumed with the date
- "by Friday" -- "by" is consumed with the date
- "at 3pm" -- "at" is consumed with the time
- "tagged @work" -- "tagged" is consumed with the tag? **No.** Only `@work` itself is consumed. "tagged" stays in the reminder. The list of consumed prefix words is limited to: `due`, `by`, `on`, `at`, `before`.

```python
_DATE_PREFIX = r"(?:due|by|on|before)\s+"
```

## Worked Examples

### Example 1: Simple Task With Date and Tag

```
Input:   "Buy groceries tomorrow at 3pm @errands"
Parsed:  reminder="Buy groceries"
         due_date=2026-03-09
         due_time=15:00
         tags=["@errands"]
```

### Example 2: Recurring Task With End Count

```
Input:   "Take pills every day for 10 days p2"
Parsed:  reminder="Take pills"
         due_date=2026-03-08 (today, implied by recurrence)
         recurrence_type="daily"
         recurrence_interval=1
         recurrence_end_count=10
         priority=2
```

### Example 3: High Priority With Multiple Tags

```
Input:   "Fix login crash @work #urgent p1"
Parsed:  reminder="Fix login crash"
         tags=["@work", "@urgent"]  (# converted to @)
         priority=1
```

### Example 4: Specific Date and Pomodoro Estimate

```
Input:   "Write quarterly report by March 20 ~4p"
Parsed:  reminder="Write quarterly report"
         due_date=2026-03-20
         pomodoro_estimate=4
```

### Example 5: Weekly Recurrence With End Date

```
Input:   "Team standup every week until June 1 at 9am"
Parsed:  reminder="Team standup"
         due_date=2026-03-08 (today, implied by recurrence)
         due_time=09:00
         recurrence_type="weekly"
         recurrence_interval=1
         recurrence_end_date=2026-06-01
```

### Example 6: Relative Date

```
Input:   "Follow up with client in 3 days"
Parsed:  reminder="Follow up with client"
         due_date=2026-03-11
```

### Example 7: No Entities (Just a Reminder)

```
Input:   "Remember to call mom"
Parsed:  reminder="Remember to call mom"
         (all other fields None/empty)
```

### Example 8: Frequency Phrasing

```
Input:   "Stretch 3 times a day"
Parsed:  reminder="Stretch (3x/day)"
         due_date=2026-03-08 (today)
         recurrence_type="daily"
         recurrence_interval=1
```

## Integration With Existing UI

### AddTodoDialog Changes

The dialog gains two modes:

1. **Smart mode (default):** Single `SmartInputWidget` at the top, preview chips below, optional Advanced toggle.
2. **Advanced mode:** Full discrete field editors (current layout), visible when toggled.

The dialog's `_on_accept()` method reads from `ParseResult` in smart mode or from the discrete widgets in advanced mode. The `TodoItem` construction at the end is identical in both paths.

**The existing discrete-field UI is not removed.** It becomes the Advanced view, ensuring zero regression for users who prefer explicit field entry.

### MainWindow Integration

No changes required to `MainWindow._on_add_todo()`. The `AddTodoDialog.create_item()` class method continues to return `TodoItem | None`. The dialog's internal mode (smart vs. advanced) is transparent to the caller.

### Undo/Redo

No impact. The smart input produces the same `TodoItem` fields that the discrete editor produces. The existing `AddItemCommand` handles it identically.

### Sync

No impact. `TodoItem.to_dict()` / `from_dict()` are unchanged. The `pomodoro_estimate` field, when added, follows the same `.get(field, default)` backward-compatibility pattern.

## Error Handling

- **Unparseable text stays as reminder.** The parser never raises exceptions on user input. Unrecognized patterns are left in the reminder text.
- **Invalid dates (e.g., February 30):** The date resolver catches `ValueError` from `date()` constructor and skips the match. The text stays in the reminder.
- **Multiple conflicting priorities:** Last one wins. `"fix bug p1 p3"` results in priority=3.
- **Empty reminder after extraction:** If entity extraction consumes the entire input (e.g., "tomorrow p1"), the dialog shows a validation warning: "Please enter a reminder." Same behavior as the current dialog.
- **Parser performance:** The regex patterns are compiled once at module level (`re.compile` with `re.IGNORECASE`). Parsing a single input runs in under 1ms even with all patterns. The 100ms debounce on the highlighter is for smoothness, not performance.

## Internationalization

### English First

The initial implementation supports English only. All patterns, day names, month names, and keywords are English.

### Extension Points for Other Languages

The parser is designed so that adding a new language requires:

1. A new set of `_DAYS`, `_MONTHS`, and keyword constants (e.g., `_DAYS_DE` for German)
2. A language-specific pattern list that mirrors the English patterns
3. A `parse(text, lang="en")` parameter to select the pattern set

The pattern structure (compiled regex + resolver function) is the same regardless of language. Day/month name resolution already uses `calendar.day_name` / `calendar.month_name` for validation -- extending to other locales is straightforward.

**Recommended approach for i18n:**

```python
# Each language provides a PatternSet
@dataclass
class PatternSet:
    days: dict[str, int]        # {"monday": 0, "tuesday": 1, ...}
    months: dict[str, int]      # {"january": 1, "february": 2, ...}
    keywords: dict[str, str]    # {"today": "today", "tomorrow": "tomorrow", ...}
    date_patterns: list[tuple[re.Pattern, Callable]]
    time_patterns: list[tuple[re.Pattern, Callable]]
    recurrence_patterns: list[tuple[re.Pattern, Callable]]
    priority_patterns: list[tuple[re.Pattern, Callable]]

_PATTERN_SETS: dict[str, PatternSet] = {
    "en": _build_english_patterns(),
    # "de": _build_german_patterns(),  # future
    # "es": _build_spanish_patterns(), # future
}
```

The system locale can be detected via `QLocale.system().language()` to auto-select the pattern set, with English as the fallback.

## Task Gating (Future Consideration)

Natural language dependency expressions like "do X before Y" or "after completing A, start B" are noted here for future reference but are explicitly out of scope.

**Why deferred:**
- The `TodoItem` data model has no dependency/ordering fields
- Dependencies require a DAG (directed acyclic graph) structure to prevent cycles
- UI implications are significant (blocked task indicators, dependency visualization)
- Sync implications are non-trivial (dependency references across devices)

**When to revisit:** After the data model gains a `blocked_by: list[UUID]` field and the UI supports dependency visualization. The parser can then be extended with patterns like:

```
"write tests after implementing feature" -> blocked_by=[UUID of "implementing feature"]
"deploy after tests pass" -> blocked_by=[UUID of "tests pass"]
```

This requires fuzzy matching against existing task reminders, which is a substantially different problem from regex-based entity extraction.

## Testing Strategy

### Unit Tests: `tests/test_nlp_parser.py`

Pure Python tests with no Qt dependency. The `today` parameter on `parse()` enables deterministic date assertions.

**Test categories:**

1. **Date parsing** (~30 tests): Every date pattern with edge cases (year boundaries, leap years, ambiguous months)
2. **Time parsing** (~15 tests): 12h/24h formats, noon/midnight, contextual words
3. **Priority parsing** (~10 tests): p1/p2/p3, exclamation marks, word forms, conflicts
4. **Tag parsing** (~10 tests): Single/multiple tags, @/# prefix, email-like strings, hyphenated tags
5. **Recurrence parsing** (~20 tests): All frequency patterns, end conditions, edge cases
6. **Pomodoro parsing** (~5 tests): All notation variants
7. **Combined parsing** (~15 tests): Multiple entity types in one input, ordering independence
8. **Remainder extraction** (~10 tests): Whitespace cleanup, prefix word consumption, empty remainder
9. **Edge cases** (~10 tests): Empty input, only entities, Unicode text, very long input
10. **Span accuracy** (~10 tests): Verify EntitySpan offsets for highlighting

**Estimated total: ~135 tests**

### Integration Tests: `tests/test_smart_input.py`

Qt widget tests requiring `QT_QPA_PLATFORM=offscreen`. Test the `SmartInputWidget` highlighting, chip display, and Advanced mode toggle.

**Estimated: ~20 tests**

## Implementation Plan

### Phase 1: Parser Core

1. Create `src/pytodo_qt/core/nlp_parser.py` with `ParseResult`, `EntitySpan`, `EntityKind`
2. Implement tag parsing (simplest, highest confidence)
3. Implement priority parsing
4. Implement date parsing (largest pattern set)
5. Implement time parsing
6. Implement recurrence parsing
7. Implement pomodoro estimate parsing
8. Implement remainder extraction and span tracking
9. Write `tests/test_nlp_parser.py` -- full coverage

### Phase 2: Smart Input Widget

1. Create `src/pytodo_qt/gui/widgets/smart_input.py` with `SmartInputWidget`
2. Implement `SmartInputHighlighter` (QSyntaxHighlighter subclass)
3. Implement preview chips row
4. Implement chip removal (click X -> update input text)
5. Implement tag completion with `QCompleter`
6. Write `tests/test_smart_input.py`

### Phase 3: Dialog Integration

1. Modify `AddTodoDialog` to use `SmartInputWidget` as default mode
2. Add Advanced toggle to show/hide discrete fields
3. Wire bidirectional sync between smart input and discrete fields
4. Ensure `_on_accept()` works from both modes
5. Update existing `AddTodoDialog` tests

### Phase 4: Polish

1. Theme-aware highlighting colors
2. Keyboard shortcut refinements
3. Inline table editing awareness (stretch goal)
4. Performance profiling of real-time parsing

### Dependencies

- Phase 1 has no dependencies and can begin immediately
- Phase 2 depends on Phase 1
- Phase 3 depends on Phase 2
- Phase 4 depends on Phase 3
- The `pomodoro_estimate` field on `TodoItem` requires a schema migration (v11) but the parser and UI can handle it without the field -- the estimate is simply not persisted until the migration ships

### No External Dependencies

The entire feature is implemented with Python stdlib (`re`, `datetime`, `calendar`) and PyQt6 (already a project dependency). No new packages are added. This is consistent with the project's local-first, no-cloud philosophy.
