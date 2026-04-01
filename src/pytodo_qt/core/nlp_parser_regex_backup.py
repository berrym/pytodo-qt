"""nlp_parser.py

Natural language task input parser.

Extracts dates, times, priority, tags, recurrence, and pomodoro estimates
from free-form English text.  Pure Python — no Qt dependency, no external
packages.  All patterns are compiled once at module level.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from datetime import datetime as _datetime
from enum import Enum

from .logger import Logger

logger = Logger(__name__)


# ---------------------------------------------------------------------------
# Number word preprocessing
# ---------------------------------------------------------------------------

_NUMBER_WORDS: dict[str, str] = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "fifteen": "15",
    "twenty": "20",
    "thirty": "30",
}

# Contexts where number words should be converted to digits
_NUMBER_CONTEXT_RE = re.compile(
    r"\b(?:in|every|for|priority)\s+("
    + "|".join(re.escape(w) for w in sorted(_NUMBER_WORDS, key=len, reverse=True))
    + r")\b"
    r"|"
    r"\b("
    + "|".join(re.escape(w) for w in sorted(_NUMBER_WORDS, key=len, reverse=True))
    + r")\s+(?:minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?"
    r"|times?|pomodoros?|poms?|sessions?)\b",
    re.IGNORECASE,
)

# Multi-word number phrases
_COUPLE_FEW_RE = re.compile(
    r"\b(?:a\s+couple\s+(?:of\s+)?|a\s+few\s+)(days?|weeks?|months?|hours?|minutes?)\b",
    re.IGNORECASE,
)


def _normalize_number_words(text: str) -> str:
    """Convert number words to digits in pattern-relevant contexts only."""

    # Handle "a couple of days" / "a few days"
    def _couple_few_replace(m: re.Match[str]) -> str:
        full = m.group(0).lower()
        unit = m.group(1)
        if "couple" in full:
            return f"2 {unit}"
        return f"3 {unit}"

    text = _COUPLE_FEW_RE.sub(_couple_few_replace, text)

    # Handle contextual number words
    def _number_replace(m: re.Match[str]) -> str:
        word = (m.group(1) or m.group(2)).lower()
        digit = _NUMBER_WORDS.get(word, word)
        return m.group(0).replace(m.group(1) or m.group(2), digit, 1)

    return _NUMBER_CONTEXT_RE.sub(_number_replace, text)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class EntityKind(Enum):
    """Types of entities the parser can extract."""

    DATE = "date"
    TIME = "time"
    PRIORITY = "priority"
    TAG = "tag"
    RECURRENCE = "recurrence"
    POMODORO = "pomodoro"


@dataclass
class EntitySpan:
    """A parsed entity's location in the original text."""

    start: int
    end: int
    kind: EntityKind
    display: str


@dataclass
class ParseResult:
    """Result of parsing a natural language task input."""

    reminder: str
    due_date: date | None = None
    due_time: time | None = None
    priority: int | None = None
    tags: list[str] = field(default_factory=list)
    recurrence_type: str | None = None
    recurrence_interval: int = 1
    recurrence_end_date: date | None = None
    recurrence_end_count: int | None = None
    pomodoro_estimate: int | None = None
    spans: list[EntitySpan] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Calendar constants
# ---------------------------------------------------------------------------

_DAYS_MAP: dict[str, int] = {}
for _i, _name in enumerate(calendar.day_name):
    _DAYS_MAP[_name.lower()] = _i
for _i, _name in enumerate(calendar.day_abbr):
    _DAYS_MAP[_name.lower()] = _i

_MONTHS_MAP: dict[str, int] = {}
for _i in range(1, 13):
    _MONTHS_MAP[calendar.month_name[_i].lower()] = _i
    _MONTHS_MAP[calendar.month_abbr[_i].lower()] = _i

_DAYS_RE = (
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tue|wed|thu|fri|sat|sun)"
)
_MONTHS_RE = (
    r"(?:january|february|march|april|may|june|july|august|september"
    r"|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
)


# ---------------------------------------------------------------------------
# Span tracking
# ---------------------------------------------------------------------------


class _SpanTracker:
    """Tracks reserved character ranges to prevent double-extraction."""

    def __init__(self) -> None:
        self._spans: list[EntitySpan] = []

    def is_free(self, start: int, end: int) -> bool:
        """Check that [start, end) doesn't overlap any reserved span."""
        return all(not (start < s.end and end > s.start) for s in self._spans)

    def reserve(self, span: EntitySpan) -> None:
        self._spans.append(span)

    @property
    def spans(self) -> list[EntitySpan]:
        return sorted(self._spans, key=lambda s: s.start)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _resolve_day_name(name: str, today: date) -> date:
    """Resolve a day name to the next occurrence (never today)."""
    target = _DAYS_MAP[name.lower()]
    current = today.weekday()
    days_ahead = (target - current) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def _resolve_next_day_name(name: str, today: date) -> date:
    """Resolve 'next <day>' — the occurrence after the upcoming one."""
    target = _DAYS_MAP[name.lower()]
    current = today.weekday()
    days_ahead = (target - current) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead + 7)


def _resolve_month_name(name: str) -> int | None:
    """Resolve month name/abbreviation to month number 1-12."""
    return _MONTHS_MAP.get(name.lower())


def _add_months(d: date, months: int) -> date:
    """Add N months to a date, clamping day to valid range."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    import calendar as _cal

    max_day = _cal.monthrange(year, month)[1]
    return date(year, month, min(d.day, max_day))


def _unit_to_recurrence_type(unit: str) -> tuple[str, int | None]:
    """Map 'minute'/'hour'/'day'/... to (recurrence_type, interval_multiplier).

    For minute/hour units, returns ("minutely", multiplier) where multiplier
    converts the user's number into minutes. For day+ units, returns the
    standard type with no multiplier.
    """
    u = unit.lower().rstrip("s")
    # Normalize shortened forms
    if u in ("min", "minute"):
        return ("minutely", 1)  # interval is already in minutes
    if u in ("hr", "hour"):
        return ("minutely", 60)  # multiply user's number by 60
    mapping = {"day": "daily", "week": "weekly", "month": "monthly", "year": "yearly"}
    return (mapping[u], None)


def _freq_word_to_type(word: str) -> tuple[str, int]:
    """Map 'minutely'/'hourly'/'daily'/... to (recurrence_type, interval)."""
    w = word.lower().replace("-", "")
    if w == "annually":
        return ("yearly", 1)
    if w == "minutely":
        return ("minutely", 1)
    if w == "hourly":
        return ("minutely", 60)
    if w == "biweekly":
        return ("weekly", 2)
    if w == "bimonthly":
        return ("monthly", 2)
    return (w, 1)


# ---------------------------------------------------------------------------
# Tag extraction
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"(?<!\S)[@#]([\w-]+)", re.IGNORECASE)


def _extract_tags(text: str, tracker: _SpanTracker) -> list[str]:
    """Extract @tag and #tag tokens."""
    tags: list[str] = []
    seen: set[str] = set()
    for m in _TAG_RE.finditer(text):
        if not tracker.is_free(m.start(), m.end()):
            continue
        raw = m.group(1)
        tag = f"@{raw}"
        if tag.lower() not in seen:
            tags.append(tag)
            seen.add(tag.lower())
        tracker.reserve(EntitySpan(m.start(), m.end(), EntityKind.TAG, tag))
    return tags


# ---------------------------------------------------------------------------
# Priority extraction
# ---------------------------------------------------------------------------

_PRIORITY_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3}

_PRIORITY_PATTERNS: list[tuple[re.Pattern[str], int | None]] = [
    (re.compile(r"\bp([1-3])\b", re.IGNORECASE), None),  # group capture
    (re.compile(r"(!{1,3})\s*$"), 1),
    (re.compile(r"\bhigh\s+(?:prio(?:rity)?|importance)\b", re.IGNORECASE), 1),
    (re.compile(r"\blow\s+prio(?:rity)?\b", re.IGNORECASE), 3),
    (re.compile(r"\bnot\s+important\b", re.IGNORECASE), 3),  # must be before "important"
    (re.compile(r"\bimportant\b", re.IGNORECASE), 1),
    (re.compile(r"\burgent\b", re.IGNORECASE), 1),
    (re.compile(r"\basap\b", re.IGNORECASE), 1),
    (re.compile(r"\bpriority\s+(one|two|three|[1-3])\b", re.IGNORECASE), None),
]

_PRIORITY_DISPLAY = {1: "High", 2: "Normal", 3: "Low"}


def _extract_priority(text: str, tracker: _SpanTracker) -> int | None:
    """Extract priority (last match wins)."""
    result: int | None = None
    result_span: EntitySpan | None = None

    for pattern, fixed_value in _PRIORITY_PATTERNS:
        for m in pattern.finditer(text):
            if not tracker.is_free(m.start(), m.end()):
                continue
            if fixed_value is not None:
                value = fixed_value
            else:
                raw = m.group(1).lower()
                value = _PRIORITY_NUMBER_WORDS.get(raw, int(raw) if raw.isdigit() else 2)
            # Last match wins — overwrite previous
            result = value
            if result_span is not None:
                # Un-reserve the previous span by removing it
                tracker._spans = [s for s in tracker._spans if s is not result_span]
            result_span = EntitySpan(
                m.start(), m.end(), EntityKind.PRIORITY, _PRIORITY_DISPLAY.get(value, "")
            )
            tracker.reserve(result_span)

    return result


# ---------------------------------------------------------------------------
# Recurrence extraction
# ---------------------------------------------------------------------------

_RECURRENCE_EVERY_N_RE = re.compile(
    r"\bevery\s+(\d+)\s+(minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?)\b", re.IGNORECASE
)
_RECURRENCE_EVERY_OTHER_RE = re.compile(r"\bevery\s+other\s+(day|week|month|year)\b", re.IGNORECASE)
_RECURRENCE_EVERY_UNIT_RE = re.compile(
    r"\bevery\s+(minute|hour|day|week|month|year)\b", re.IGNORECASE
)
_RECURRENCE_EVERY_TIME_OF_DAY_RE = re.compile(r"\bevery\s+(morning|night|evening)\b", re.IGNORECASE)
_RECURRENCE_EVERY_WEEKDAY_RE = re.compile(r"\bevery\s+weekday\b", re.IGNORECASE)
_RECURRENCE_FREQ_WORD_RE = re.compile(
    r"\b(minutely|hourly|daily|weekly|monthly|yearly|annually"
    r"|biweekly|bi-weekly|bimonthly|bi-monthly)\b",
    re.IGNORECASE,
)
_RECURRENCE_TIMES_RE = re.compile(
    r"\b(?:(\d+)\s+times?|twice)\s+a\s+(day|week|month)\b", re.IGNORECASE
)
_RECURRENCE_FOR_RE = re.compile(r"\bfor\s+(\d+)\s+(days?|weeks?|months?|years?)\b", re.IGNORECASE)
_RECURRENCE_UNTIL_RE = re.compile(
    r"\buntil\s+(.+?)(?:\s+(?:at|by|p[1-3]|[@#~])|\s*$)", re.IGNORECASE
)

_TIME_OF_DAY_MAP = {"morning": time(9, 0), "night": time(21, 0), "evening": time(18, 0)}


def _extract_recurrence(
    text: str, tracker: _SpanTracker, today: date
) -> tuple[str | None, int, date | None, int | None, str | None]:
    """Extract recurrence pattern.

    Returns (type, interval, end_date, end_count, times_annotation).
    times_annotation is e.g. "(3x/day)" for "3 times a day".
    """
    rec_type: str | None = None
    interval: int = 1
    end_date: date | None = None
    end_count: int | None = None
    times_annotation: str | None = None
    main_span_start: int | None = None
    main_span_end: int | None = None
    display_base: str = ""

    # Track time-of-day hint from recurrence (e.g., "every morning" → daily + 9:00)
    rec_time_hint: time | None = None

    # Try "every N minutes/hours/days/weeks/months/years"
    m = _RECURRENCE_EVERY_N_RE.search(text)
    if m and tracker.is_free(m.start(), m.end()):
        user_interval = int(m.group(1))
        rec_type, multiplier = _unit_to_recurrence_type(m.group(2))
        interval = user_interval * multiplier if multiplier else user_interval
        display_base = f"every {m.group(1)} {m.group(2).lower()}"
        main_span_start = m.start()
        main_span_end = m.end()

    # Try "every other day/week/month/year"
    if rec_type is None:
        m = _RECURRENCE_EVERY_OTHER_RE.search(text)
        if m and tracker.is_free(m.start(), m.end()):
            unit = m.group(1).lower()
            rec_type, _ = _unit_to_recurrence_type(unit)
            interval = 2
            display_base = f"every other {unit}"
            main_span_start = m.start()
            main_span_end = m.end()

    # Try "every morning/night/evening" → daily + time hint
    if rec_type is None:
        m = _RECURRENCE_EVERY_TIME_OF_DAY_RE.search(text)
        if m and tracker.is_free(m.start(), m.end()):
            tod = m.group(1).lower()
            rec_type = "daily"
            rec_time_hint = _TIME_OF_DAY_MAP.get(tod)
            display_base = f"every {tod}"
            main_span_start = m.start()
            main_span_end = m.end()

    # Try "every weekday"
    if rec_type is None:
        m = _RECURRENCE_EVERY_WEEKDAY_RE.search(text)
        if m and tracker.is_free(m.start(), m.end()):
            rec_type = "daily"
            display_base = "every weekday"
            main_span_start = m.start()
            main_span_end = m.end()

    # Try "every minute/hour/day/week/month/year"
    if rec_type is None:
        m = _RECURRENCE_EVERY_UNIT_RE.search(text)
        if m and tracker.is_free(m.start(), m.end()):
            rec_type, multiplier = _unit_to_recurrence_type(m.group(1))
            if multiplier:
                interval = multiplier
            display_base = f"every {m.group(1).lower()}"
            main_span_start = m.start()
            main_span_end = m.end()

    # Try "minutely/hourly/daily/weekly/monthly/yearly/annually/biweekly/bimonthly"
    if rec_type is None:
        m = _RECURRENCE_FREQ_WORD_RE.search(text)
        if m and tracker.is_free(m.start(), m.end()):
            rec_type, interval = _freq_word_to_type(m.group(1))
            display_base = m.group(1).lower()
            main_span_start = m.start()
            main_span_end = m.end()

    # Try "N times a day/week/month" or "twice a day/week/month"
    if rec_type is None:
        m = _RECURRENCE_TIMES_RE.search(text)
        if m and tracker.is_free(m.start(), m.end()):
            n = int(m.group(1)) if m.group(1) else 2  # "twice" has no group(1)
            unit = m.group(2).lower()
            rec_type, _ = _unit_to_recurrence_type(unit)
            times_annotation = f"({n}x/{unit})"
            display_base = m.group(0).lower()
            main_span_start = m.start()
            main_span_end = m.end()

    if rec_type is None:
        return None, 1, None, None, None, None

    # Display text preserves the user's original phrasing
    display_parts = [display_base]

    # Reserve main span
    assert main_span_start is not None and main_span_end is not None

    # Look for "for N days/weeks" suffix after the main match
    suffix_text = text[main_span_end:]
    m_for = _RECURRENCE_FOR_RE.search(suffix_text)
    if m_for:
        abs_start = main_span_end + m_for.start()
        abs_end = main_span_end + m_for.end()
        if tracker.is_free(abs_start, abs_end):
            end_count = int(m_for.group(1))
            main_span_end = abs_end
            display_parts.append(f"for {end_count}")

    # Look for "until <date>" suffix
    if end_count is None:
        m_until = _RECURRENCE_UNTIL_RE.search(suffix_text)
        if m_until:
            abs_start = main_span_end + m_until.start()
            abs_end = main_span_end + m_until.end()
            if tracker.is_free(abs_start, abs_end):
                date_text = m_until.group(1).strip()
                parsed_end = _parse_date_text(date_text, today)
                if parsed_end is not None:
                    end_date = parsed_end
                    main_span_end = abs_end
                    display_parts.append(f"until {end_date}")

    tracker.reserve(
        EntitySpan(main_span_start, main_span_end, EntityKind.RECURRENCE, " ".join(display_parts))
    )

    return rec_type, interval, end_date, end_count, times_annotation, rec_time_hint


# ---------------------------------------------------------------------------
# Pomodoro extraction
# ---------------------------------------------------------------------------

_POMODORO_RE = re.compile(r"~(\d+)\s*(?:p(?:omodoros?|oms?)?|sessions?)\b", re.IGNORECASE)


def _extract_pomodoro(text: str, tracker: _SpanTracker) -> int | None:
    """Extract pomodoro estimate (~3p, ~2 pomodoros, etc.)."""
    m = _POMODORO_RE.search(text)
    if m and tracker.is_free(m.start(), m.end()):
        value = int(m.group(1))
        tracker.reserve(EntitySpan(m.start(), m.end(), EntityKind.POMODORO, f"~{value} pom"))
        return value
    return None


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

# Optional prefix words that are consumed with the date
_DATE_PREFIX_RE = re.compile(r"\b(?:due|by|on|before)\s+", re.IGNORECASE)


def _parse_date_text(text: str, today: date) -> date | None:
    """Try to parse a date from a short text fragment (used by recurrence 'until')."""
    text = text.strip()
    # Try simple patterns
    for pattern, resolver in _DATE_RESOLVERS:
        m = pattern.search(text)
        if m:
            try:
                return resolver(m, today)
            except (ValueError, KeyError):
                continue
    return None


def _resolve_today(m: re.Match[str], today: date) -> date:
    return today


def _resolve_tomorrow(m: re.Match[str], today: date) -> date:
    return today + timedelta(days=1)


def _resolve_yesterday(m: re.Match[str], today: date) -> date:
    return today - timedelta(days=1)


def _resolve_next_day(m: re.Match[str], today: date) -> date:
    day_name = m.group(1).lower()
    return _resolve_next_day_name(day_name, today)


def _resolve_day(m: re.Match[str], today: date) -> date:
    day_name = m.group(0).lower()
    return _resolve_day_name(day_name, today)


def _resolve_next_week(m: re.Match[str], today: date) -> date:
    return today + timedelta(days=7)


def _resolve_next_month(m: re.Match[str], today: date) -> date:
    return _add_months(today, 1)


def _resolve_in_days(m: re.Match[str], today: date) -> date:
    return today + timedelta(days=int(m.group(1)))


def _resolve_in_weeks(m: re.Match[str], today: date) -> date:
    return today + timedelta(weeks=int(m.group(1)))


def _resolve_in_months(m: re.Match[str], today: date) -> date:
    return _add_months(today, int(m.group(1)))


def _resolve_day_after_tomorrow(m: re.Match[str], today: date) -> date:
    return today + timedelta(days=2)


def _resolve_this_weekend(m: re.Match[str], today: date) -> date:
    # Saturday of this week (or next if already Saturday/Sunday)
    days_until_sat = (5 - today.weekday()) % 7
    if days_until_sat == 0:
        days_until_sat = 7
    return today + timedelta(days=days_until_sat)


def _resolve_end_of_week(m: re.Match[str], today: date) -> date:
    # Friday of this week (or next Friday if already past)
    days_until_fri = (4 - today.weekday()) % 7
    if days_until_fri == 0 and today.weekday() != 4:
        days_until_fri = 7
    if days_until_fri == 0:
        days_until_fri = 7  # If today IS Friday, next Friday
    return today + timedelta(days=days_until_fri)


def _resolve_end_of_month(m: re.Match[str], today: date) -> date:
    last_day = calendar.monthrange(today.year, today.month)[1]
    eom = date(today.year, today.month, last_day)
    if eom <= today:
        # Already past end of month — next month
        return _add_months(today, 1).replace(
            day=calendar.monthrange(_add_months(today, 1).year, _add_months(today, 1).month)[1]
        )
    return eom


def _resolve_in_one_unit(m: re.Match[str], today: date) -> date:
    unit = m.group(1).lower()
    if unit == "day":
        return today + timedelta(days=1)
    if unit == "week":
        return today + timedelta(weeks=1)
    return _add_months(today, 1)


def _resolve_ordinal_day(m: re.Match[str], today: date) -> date:
    day = int(m.group(1))
    # This month if not passed, else next month
    try:
        candidate = date(today.year, today.month, day)
    except ValueError:
        return _add_months(today, 1).replace(day=min(day, 28))
    if candidate <= today:
        return _add_months(today, 1).replace(
            day=min(
                day, calendar.monthrange(_add_months(today, 1).year, _add_months(today, 1).month)[1]
            )
        )
    return candidate


def _resolve_ordinal_of_month(m: re.Match[str], today: date) -> date:
    day = int(m.group(1))
    month_name = m.group(2).lower()
    month = _MONTHS_MAP.get(month_name)
    if month is None:
        raise ValueError(f"Unknown month: {month_name}")
    year = today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        raise
    if candidate < today:
        year += 1
    return date(year, month, day)


def _resolve_month_day(m: re.Match[str], today: date) -> date:
    month_name = m.group(1).lower()
    month = _MONTHS_MAP.get(month_name)
    if month is None:
        raise ValueError(f"Unknown month: {month_name}")
    day = int(m.group(2))
    year_str = m.group(3)
    if year_str:
        year = int(year_str)
    else:
        # Current year if date hasn't passed, else next year
        year = today.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            raise
        if candidate < today:
            year += 1
    return date(year, month, day)


def _resolve_iso_date(m: re.Match[str], today: date) -> date:
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _resolve_slash_date(m: re.Match[str], today: date) -> date:
    month = int(m.group(1))
    day = int(m.group(2))
    year_str = m.group(3)
    if year_str:
        year = int(year_str)
    else:
        year = today.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            raise
        if candidate < today:
            year += 1
    return date(year, month, day)


# Ordered list of (compiled pattern, resolver function)
_DateResolver = Callable[[re.Match[str], date], date]

_DATE_RESOLVERS: list[tuple[re.Pattern[str], _DateResolver]] = [
    (re.compile(r"\btoday\b", re.IGNORECASE), _resolve_today),
    (re.compile(r"\bday\s+after\s+tomorrow\b", re.IGNORECASE), _resolve_day_after_tomorrow),
    (re.compile(r"\btomorrow\b", re.IGNORECASE), _resolve_tomorrow),
    (re.compile(r"\byesterday\b", re.IGNORECASE), _resolve_yesterday),
    (
        re.compile(r"\bthis\s+coming\s+(" + _DAYS_RE + r")\b", re.IGNORECASE),
        lambda m, today: _resolve_day_name(m.group(1).lower(), today),
    ),
    (
        re.compile(r"\bnext\s+(" + _DAYS_RE + r")\b", re.IGNORECASE),
        _resolve_next_day,
    ),
    (
        re.compile(r"\bthis\s+(" + _DAYS_RE + r")\b", re.IGNORECASE),
        lambda m, today: _resolve_day_name(m.group(1).lower(), today),
    ),
    (re.compile(r"\b(" + _DAYS_RE + r")\b", re.IGNORECASE), _resolve_day),
    (re.compile(r"\bthis\s+weekend\b", re.IGNORECASE), _resolve_this_weekend),
    (re.compile(r"\bnext\s+week\b", re.IGNORECASE), _resolve_next_week),
    (re.compile(r"\bnext\s+month\b", re.IGNORECASE), _resolve_next_month),
    (
        re.compile(r"\bend\s+of\s+(?:the\s+)?week\b", re.IGNORECASE),
        _resolve_end_of_week,
    ),
    (
        re.compile(r"\bend\s+of\s+(?:the\s+)?month\b", re.IGNORECASE),
        _resolve_end_of_month,
    ),
    (re.compile(r"\bin\s+an?\s+(day|week|month)\b", re.IGNORECASE), _resolve_in_one_unit),
    (re.compile(r"\bin\s+(\d+)\s+days?\b", re.IGNORECASE), _resolve_in_days),
    (re.compile(r"\bin\s+(\d+)\s+weeks?\b", re.IGNORECASE), _resolve_in_weeks),
    (re.compile(r"\bin\s+(\d+)\s+months?\b", re.IGNORECASE), _resolve_in_months),
    (
        re.compile(
            r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\s+of\s+(" + _MONTHS_RE + r")\b",
            re.IGNORECASE,
        ),
        _resolve_ordinal_of_month,
    ),
    (
        re.compile(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE),
        _resolve_ordinal_day,
    ),
    (
        re.compile(
            r"\b(" + _MONTHS_RE + r")\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?\b",
            re.IGNORECASE,
        ),
        _resolve_month_day,
    ),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), _resolve_iso_date),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b"), _resolve_slash_date),
]


def _extract_dates(text: str, tracker: _SpanTracker, today: date) -> date | None:
    """Extract date (last match wins)."""
    result: date | None = None
    result_span: EntitySpan | None = None

    for pattern, resolver in _DATE_RESOLVERS:
        for m in pattern.finditer(text):
            start = m.start()
            end = m.end()

            # Check for prefix word before the match
            prefix_start = start
            before = text[:start]
            pm = _DATE_PREFIX_RE.search(before)
            if pm and pm.end() == start:
                prefix_start = pm.start()

            if not tracker.is_free(prefix_start, end):
                continue

            try:
                resolved = resolver(m, today)
            except (ValueError, KeyError):
                continue

            # Last match wins
            result = resolved
            if result_span is not None:
                tracker._spans = [s for s in tracker._spans if s is not result_span]
            display = result.strftime("%b %d, %Y") if result else ""
            result_span = EntitySpan(prefix_start, end, EntityKind.DATE, display)
            tracker.reserve(result_span)

    return result


# ---------------------------------------------------------------------------
# Time extraction
# ---------------------------------------------------------------------------


def _resolve_time_12h(m: re.Match[str]) -> time:
    hour = int(m.group(1))
    minute = int(m.group(2))
    ampm = m.group(3).lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return time(hour, minute)


def _resolve_time_12h_no_min(m: re.Match[str]) -> time:
    hour = int(m.group(1))
    ampm = m.group(2).lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return time(hour, 0)


def _resolve_time_24h(m: re.Match[str]) -> time:
    return time(int(m.group(1)), int(m.group(2)))


_TimeResolver = Callable[[re.Match[str]], time]


def _resolve_in_minutes_time(m: re.Match[str]) -> time:
    mins = int(m.group(1))
    dt = _datetime.now() + timedelta(minutes=mins)
    return dt.time().replace(second=0, microsecond=0)


def _resolve_in_hours_time(m: re.Match[str]) -> time:
    hours = int(m.group(1))
    dt = _datetime.now() + timedelta(hours=hours)
    return dt.time().replace(second=0, microsecond=0)


def _resolve_in_one_hour_time(m: re.Match[str]) -> time:
    dt = _datetime.now() + timedelta(hours=1)
    return dt.time().replace(second=0, microsecond=0)


_TIME_PATTERNS: list[tuple[re.Pattern[str], _TimeResolver]] = [
    # With "at/by" prefix (most specific)
    (
        re.compile(r"\b(?:at|by|before)\s+(\d{1,2}):(\d{2})\s*(am|pm)\b", re.IGNORECASE),
        _resolve_time_12h,
    ),
    (
        re.compile(r"\b(?:at|by|before)\s+(\d{1,2})\s*(am|pm)\b", re.IGNORECASE),
        _resolve_time_12h_no_min,
    ),
    (
        re.compile(r"\b(?:at|by|before)\s+(\d{1,2}):(\d{2})\b"),
        _resolve_time_24h,
    ),
    (re.compile(r"\b(?:at|by)\s+noon\b", re.IGNORECASE), lambda _m: time(12, 0)),
    (re.compile(r"\b(?:at|by)\s+midnight\b", re.IGNORECASE), lambda _m: time(0, 0)),
    # Bare times without prefix (voice dictation often omits "at")
    (
        re.compile(r"\b(\d{1,2}):(\d{2})\s*(am|pm)\b", re.IGNORECASE),
        _resolve_time_12h,
    ),
    (
        re.compile(r"\b(\d{1,2})\s*(am|pm)\b", re.IGNORECASE),
        _resolve_time_12h_no_min,
    ),
    # Relative times
    (
        re.compile(r"\bin\s+(\d+)\s+minutes?\b", re.IGNORECASE),
        _resolve_in_minutes_time,
    ),
    (
        re.compile(r"\bin\s+(\d+)\s+hours?\b", re.IGNORECASE),
        _resolve_in_hours_time,
    ),
    (
        re.compile(r"\bin\s+an?\s+hour\b", re.IGNORECASE),
        _resolve_in_one_hour_time,
    ),
    # Contextual keywords
    (re.compile(r"\bnoon\b", re.IGNORECASE), lambda _m: time(12, 0)),
    (re.compile(r"\bmidnight\b", re.IGNORECASE), lambda _m: time(0, 0)),
    (re.compile(r"\btonight\b", re.IGNORECASE), lambda _m: time(20, 0)),
    (re.compile(r"\bthis\s+morning\b", re.IGNORECASE), lambda _m: time(9, 0)),
    (re.compile(r"\bthis\s+afternoon\b", re.IGNORECASE), lambda _m: time(14, 0)),
    (re.compile(r"\bthis\s+evening\b", re.IGNORECASE), lambda _m: time(18, 0)),
    (re.compile(r"\bmorning\b", re.IGNORECASE), lambda _m: time(9, 0)),
    (re.compile(r"\bafternoon\b", re.IGNORECASE), lambda _m: time(14, 0)),
    (re.compile(r"\bevening\b", re.IGNORECASE), lambda _m: time(18, 0)),
    (re.compile(r"\b(?:eod|end\s+of\s+day)\b", re.IGNORECASE), lambda _m: time(17, 0)),
]


def _extract_times(text: str, tracker: _SpanTracker) -> time | None:
    """Extract time (last match wins)."""
    result: time | None = None
    result_span: EntitySpan | None = None

    for pattern, resolver in _TIME_PATTERNS:
        for m in pattern.finditer(text):
            if not tracker.is_free(m.start(), m.end()):
                continue
            try:
                resolved = resolver(m)
            except (ValueError, TypeError):
                continue

            result = resolved
            if result_span is not None:
                tracker._spans = [s for s in tracker._spans if s is not result_span]
            display = result.strftime("%I:%M %p").lstrip("0") if result else ""
            result_span = EntitySpan(m.start(), m.end(), EntityKind.TIME, display)
            tracker.reserve(result_span)

    return result


# ---------------------------------------------------------------------------
# Remainder extraction
# ---------------------------------------------------------------------------


def _build_reminder(text: str, spans: list[EntitySpan]) -> str:
    """Build reminder text from everything not claimed by entity spans."""
    if not spans:
        return text.strip()

    sorted_spans = sorted(spans, key=lambda s: s.start)
    parts: list[str] = []
    pos = 0
    for span in sorted_spans:
        if span.start > pos:
            parts.append(text[pos : span.start])
        pos = span.end
    if pos < len(text):
        parts.append(text[pos:])

    # Join, collapse whitespace, strip
    raw = "".join(parts)
    return re.sub(r"\s+", " ", raw).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(text: str, today: date | None = None) -> ParseResult:
    """Parse a natural language task description into structured fields.

    Args:
        text: Raw user input, e.g. "Buy groceries tomorrow at 3pm @errands"
        today: Override for today's date (for testing). Defaults to date.today().

    Returns:
        ParseResult with extracted fields and remainder as the reminder.
    """
    if today is None:
        today = date.today()

    # Preprocess: convert number words to digits in relevant contexts
    text = _normalize_number_words(text)

    tracker = _SpanTracker()

    # 1. Tags (most unambiguous)
    tags = _extract_tags(text, tracker)

    # 2. Priority
    priority = _extract_priority(text, tracker)

    # 3. Recurrence (before dates — "every Monday" contains a day name)
    rec_type, rec_interval, rec_end_date, rec_end_count, times_anno, rec_time = _extract_recurrence(
        text, tracker, today
    )

    # 4. Pomodoro estimate
    pomodoro = _extract_pomodoro(text, tracker)

    # 5. Dates
    due_date = _extract_dates(text, tracker, today)

    # 6. Times
    due_time = _extract_times(text, tracker)

    # Apply recurrence time hint (e.g., "every morning" → 9:00)
    if rec_time is not None and due_time is None:
        due_time = rec_time

    # Rule 4: Recurrence implies due date today
    if rec_type is not None and due_date is None:
        due_date = today

    # Build reminder from unclaimed text
    reminder = _build_reminder(text, tracker.spans)

    # Append times_annotation if present (e.g. "3 times a day" -> "(3x/day)")
    if times_anno and reminder:
        reminder = f"{reminder} {times_anno}"
    elif times_anno:
        reminder = times_anno

    return ParseResult(
        reminder=reminder,
        due_date=due_date,
        due_time=due_time,
        priority=priority,
        tags=tags,
        recurrence_type=rec_type,
        recurrence_interval=rec_interval,
        recurrence_end_date=rec_end_date,
        recurrence_end_count=rec_end_count,
        pomodoro_estimate=pomodoro,
        spans=tracker.spans,
    )
