"""nlp_parser.py

Intent-based natural language task input parser.

Extracts dates, times, priority, tags, recurrence, pomodoro estimates,
estimated minutes, and work duration from free-form text using:
- Token-based intent dictionaries (no regex for NLP patterns)
- rapidfuzz for fuzzy matching (typos, abbreviations, voice dictation)
- dateparser for date/time extraction (200+ languages)

Pure Python — no Qt dependency. The only regex is for @/# tag syntax detection.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, time
from datetime import datetime as _datetime
from enum import Enum
from typing import Any

from .logger import Logger

logger = Logger(__name__)


# ---------------------------------------------------------------------------
# Public data structures (API preserved from previous parser)
# ---------------------------------------------------------------------------


class EntityKind(Enum):
    DATE = "date"
    TIME = "time"
    PRIORITY = "priority"
    TAG = "tag"
    RECURRENCE = "recurrence"
    POMODORO = "pomodoro"
    ESTIMATE = "estimate"
    WORK_DURATION = "work_duration"


@dataclass
class EntitySpan:
    """A parsed entity's location in the original text."""

    start: int
    end: int
    kind: EntityKind
    display: str
    confidence: float = 1.0


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
    estimated_minutes: int | None = None
    work_duration: int | None = None
    spans: list[EntitySpan] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Token:
    """A word token with character span from the original text."""

    text: str  # Lowercase
    original: str  # Original case
    start: int  # Character offset
    end: int  # Character offset (exclusive)


def _tokenize(text: str) -> list[_Token]:
    """Split text on whitespace, preserving character spans."""
    tokens: list[_Token] = []
    i = 0
    n = len(text)
    while i < n:
        # Skip whitespace
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        # Collect non-whitespace
        start = i
        while i < n and not text[i].isspace():
            i += 1
        word = text[start:i]
        tokens.append(_Token(text=word.lower(), original=word, start=start, end=i))
    return tokens


# ---------------------------------------------------------------------------
# Span tracking (preserved from previous parser)
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

    def unreserve_kind(self, kind: EntityKind) -> None:
        """Remove all spans of a given kind (for last-match-wins)."""
        self._spans = [s for s in self._spans if s.kind != kind]

    @property
    def spans(self) -> list[EntitySpan]:
        return sorted(self._spans, key=lambda s: s.start)


# ---------------------------------------------------------------------------
# Intent dictionaries (English)
# ---------------------------------------------------------------------------

_PRIORITY_DISPLAY = {1: "High", 2: "Normal", 3: "Low"}

_INTENTS: dict[str, dict[str, Any]] = {
    "en": {
        "priority_tokens": {
            "p1": 1,
            "p2": 2,
            "p3": 3,
            "urgent": 1,
            "important": 1,
            "critical": 1,
            "asap": 1,
            "high": 1,
            "normal": 2,
            "low": 3,
        },
        "priority_phrases": {
            "high priority": 1,
            "highest priority": 1,
            "top priority": 1,
            "high prio": 1,
            "high importance": 1,
            "really important": 1,
            "very important": 1,
            "most important": 1,
            "priority one": 1,
            "priority two": 2,
            "priority three": 3,
            "priority 1": 1,
            "priority 2": 2,
            "priority 3": 3,
            "low priority": 3,
            "low prio": 3,
            "lowest priority": 3,
            "not important": 3,
            "not urgent": 3,
        },
        "recurrence_tokens": {
            "daily": ("daily", 1),
            "weekly": ("weekly", 1),
            "monthly": ("monthly", 1),
            "yearly": ("yearly", 1),
            "annually": ("yearly", 1),
            "minutely": ("minutely", 1),
            "hourly": ("minutely", 60),
            "biweekly": ("weekly", 2),
            "bimonthly": ("monthly", 2),
        },
        "recurrence_every": {
            "day": ("daily", 1),
            "days": ("daily", 1),
            "week": ("weekly", 1),
            "weeks": ("weekly", 1),
            "month": ("monthly", 1),
            "months": ("monthly", 1),
            "year": ("yearly", 1),
            "years": ("yearly", 1),
            "minute": ("minutely", 1),
            "minutes": ("minutely", 1),
            "hour": ("minutely", 60),
            "hours": ("minutely", 60),
            "weekday": ("daily", 1),
            "morning": ("daily", 1),
            "night": ("daily", 1),
            "evening": ("daily", 1),
            "other": None,  # "every other" prefix — needs next token
        },
        "recurrence_time_hints": {
            "morning": time(9, 0),
            "night": time(21, 0),
            "evening": time(18, 0),
        },
        "pomodoro_units": {
            "pomodoro",
            "pomodoros",
            "pom",
            "poms",
            "session",
            "sessions",
            "p",
        },
        "time_estimate_units": {
            "m": 1,
            "min": 1,
            "mins": 1,
            "minute": 1,
            "minutes": 1,
            "h": 60,
            "hr": 60,
            "hrs": 60,
            "hour": 60,
            "hours": 60,
        },
        "time_of_day": {
            "noon": time(12, 0),
            "midnight": time(0, 0),
            "morning": time(9, 0),
            "afternoon": time(14, 0),
            "evening": time(18, 0),
            "tonight": time(20, 0),
            "eod": time(17, 0),
        },
        "time_of_day_phrases": {
            "end of day": time(17, 0),
            "this morning": time(9, 0),
            "this afternoon": time(14, 0),
            "this evening": time(18, 0),
        },
        "tag_voice_prefixes": ["hashtag", "with tag", "at tag", "at sign", "with group"],
        "number_words": {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "fifteen": 15,
            "twenty": 20,
            "thirty": 30,
            "a": 1,
            "an": 1,
        },
        "couple_few": {
            "couple": 2,
            "few": 3,
        },
        "date_prefixes": {"due", "by", "on", "before"},
        "fuzzy_threshold": 80,
    },
}

_LANG = "en"  # Current language — future: detect or configure


def _get_intents() -> dict[str, Any]:
    return _INTENTS[_LANG]


# ---------------------------------------------------------------------------
# Fuzzy matching wrapper
# ---------------------------------------------------------------------------


def _fuzzy_match_token(
    query: str, choices: list[str] | set[str], threshold: int = 80
) -> tuple[str, float] | None:
    """Fuzzy match a single token against choices. Returns (match, confidence) or None."""
    from rapidfuzz import fuzz, process

    if not choices:
        return None
    choice_list = list(choices) if isinstance(choices, set) else choices
    result = process.extractOne(query, choice_list, scorer=fuzz.ratio, score_cutoff=threshold)
    if result is None:
        return None
    match, score, _idx = result
    return (match, score / 100.0)


def _fuzzy_match_phrase(
    query: str, choices: list[str] | dict[str, Any], threshold: int = 80
) -> tuple[str, float] | None:
    """Fuzzy match a phrase against choices using token_sort_ratio (word-order independent)."""
    from rapidfuzz import fuzz, process

    choice_list = list(choices) if isinstance(choices, dict) else choices
    if not choice_list:
        return None
    result = process.extractOne(
        query, choice_list, scorer=fuzz.token_sort_ratio, score_cutoff=threshold
    )
    if result is None:
        return None
    match, score, _idx = result
    return (match, score / 100.0)


def _token_to_number(token_text: str) -> int | None:
    """Convert a token to a number (digit string or number word)."""
    if token_text.isdigit():
        return int(token_text)
    intents = _get_intents()
    return intents["number_words"].get(token_text)


# ---------------------------------------------------------------------------
# Input sanitization
# ---------------------------------------------------------------------------


def _sanitize(text: str) -> str:
    """Normalize input text before tokenization."""
    # Unicode NFC normalization
    text = unicodedata.normalize("NFC", text)
    # Collapse whitespace
    text = " ".join(text.split())
    return text.strip()


# ---------------------------------------------------------------------------
# Tag extraction (keeps @/# detection — syntactic marker, not NLP)
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"(?<!\S)[@#]([\w-]+)")


def _extract_tags(text: str, tokens: list[_Token], tracker: _SpanTracker) -> list[str]:
    """Extract @tags and #tags, plus voice patterns like 'hashtag X'."""
    tags: list[str] = []
    seen_lower: set[str] = set()
    intents = _get_intents()

    # 1. Standard @/# syntax
    for m in _TAG_RE.finditer(text):
        start, end = m.start(), m.end()
        if not tracker.is_free(start, end):
            continue
        raw = m.group(1)
        normalized = f"@{raw}" if not raw.startswith("@") else raw
        key = normalized.lower()
        if key not in seen_lower:
            tags.append(normalized)
            seen_lower.add(key)
        tracker.reserve(EntitySpan(start, end, EntityKind.TAG, normalized))

    # 2. Voice tag patterns: "hashtag X", "with tag X", etc.
    for prefix_phrase in intents.get("tag_voice_prefixes", []):
        prefix_tokens = prefix_phrase.split()
        prefix_len = len(prefix_tokens)
        for i in range(len(tokens) - prefix_len):
            # Check if consecutive tokens match the prefix
            match = True
            for j, pt in enumerate(prefix_tokens):
                if tokens[i + j].text != pt:
                    match = False
                    break
            if match and i + prefix_len < len(tokens):
                tag_token = tokens[i + prefix_len]
                # Don't match if tag token is already claimed
                start = tokens[i].start
                end = tag_token.end
                if tracker.is_free(start, end):
                    tag_text = f"@{tag_token.original}"
                    key = tag_text.lower()
                    if key not in seen_lower:
                        tags.append(tag_text)
                        seen_lower.add(key)
                    tracker.reserve(EntitySpan(start, end, EntityKind.TAG, tag_text))

    return tags


# ---------------------------------------------------------------------------
# Priority extraction
# ---------------------------------------------------------------------------


def _extract_priority(text: str, tokens: list[_Token], tracker: _SpanTracker) -> int | None:
    """Extract priority from tokens using intent dictionary + fuzzy matching."""
    intents = _get_intents()
    priority_tokens = intents["priority_tokens"]
    priority_phrases = intents["priority_phrases"]
    threshold = intents["fuzzy_threshold"]
    result_priority: int | None = None

    # Check exclamation marks at end of text
    stripped = text.rstrip()
    if stripped.endswith("!!!") or stripped.endswith("!!") or stripped.endswith("!"):
        # Find the exclamation span
        exc_start = len(stripped.rstrip("!"))
        exc_end = len(stripped)
        if tracker.is_free(exc_start, exc_end):
            tracker.unreserve_kind(EntityKind.PRIORITY)
            tracker.reserve(EntitySpan(exc_start, exc_end, EntityKind.PRIORITY, "High"))
            result_priority = 1

    # Single-token exact matches
    for tok in tokens:
        if not tracker.is_free(tok.start, tok.end):
            continue
        if tok.text in priority_tokens:
            tracker.unreserve_kind(EntityKind.PRIORITY)
            val = priority_tokens[tok.text]
            tracker.reserve(
                EntitySpan(tok.start, tok.end, EntityKind.PRIORITY, _PRIORITY_DISPLAY[val])
            )
            result_priority = val

    # Multi-token phrase matching (2-3 token windows)
    for window_size in (2, 3):
        for i in range(len(tokens) - window_size + 1):
            phrase_tokens = tokens[i : i + window_size]
            start = phrase_tokens[0].start
            end = phrase_tokens[-1].end
            if not tracker.is_free(start, end):
                continue
            phrase = " ".join(t.text for t in phrase_tokens)

            # Exact phrase match
            if phrase in priority_phrases:
                tracker.unreserve_kind(EntityKind.PRIORITY)
                val = priority_phrases[phrase]
                tracker.reserve(EntitySpan(start, end, EntityKind.PRIORITY, _PRIORITY_DISPLAY[val]))
                result_priority = val
                continue

            # Fuzzy phrase match
            match = _fuzzy_match_phrase(phrase, priority_phrases, threshold)
            if match is not None:
                matched_phrase, confidence = match
                val = priority_phrases[matched_phrase]
                tracker.unreserve_kind(EntityKind.PRIORITY)
                tracker.reserve(
                    EntitySpan(start, end, EntityKind.PRIORITY, _PRIORITY_DISPLAY[val], confidence)
                )
                result_priority = val

    # Single-token fuzzy match (for typos like "importnt", "urgnt")
    for tok in tokens:
        if not tracker.is_free(tok.start, tok.end):
            continue
        if len(tok.text) < 3:
            continue  # Skip very short tokens to avoid false positives
        match = _fuzzy_match_token(tok.text, list(priority_tokens.keys()), threshold)
        if match is not None:
            matched_word, confidence = match
            if matched_word == tok.text:
                continue  # Already handled as exact match
            val = priority_tokens[matched_word]
            tracker.unreserve_kind(EntityKind.PRIORITY)
            tracker.reserve(
                EntitySpan(
                    tok.start, tok.end, EntityKind.PRIORITY, _PRIORITY_DISPLAY[val], confidence
                )
            )
            result_priority = val

    return result_priority


# ---------------------------------------------------------------------------
# Recurrence extraction
# ---------------------------------------------------------------------------

_UNIT_MAP = {
    "day": "daily",
    "days": "daily",
    "week": "weekly",
    "weeks": "weekly",
    "month": "monthly",
    "months": "monthly",
    "year": "yearly",
    "years": "yearly",
    "minute": "minutely",
    "minutes": "minutely",
    "hour": "minutely",
    "hours": "minutely",
}

_UNIT_MULTIPLIER = {
    "hour": 60,
    "hours": 60,
    "minute": 1,
    "minutes": 1,
}


def _extract_recurrence(
    text: str, tokens: list[_Token], tracker: _SpanTracker, today: date
) -> tuple[str | None, int, date | None, int | None, str | None, time | None]:
    """Extract recurrence pattern. Returns (type, interval, end_date, end_count, times_anno, time_hint)."""
    intents = _get_intents()
    rec_tokens = intents["recurrence_tokens"]
    threshold = intents["fuzzy_threshold"]
    rec_type: str | None = None
    rec_interval: int = 1
    rec_end_date: date | None = None
    rec_end_count: int | None = None
    times_anno: str | None = None
    time_hint: time | None = None
    rec_span_start: int | None = None
    rec_span_end: int | None = None

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tracker.is_free(tok.start, tok.end):
            i += 1
            continue

        # "every ..." patterns
        if tok.text == "every" and i + 1 < len(tokens):
            next_tok = tokens[i + 1]

            # "every other <unit>"
            if next_tok.text == "other" and i + 2 < len(tokens):
                unit_tok = tokens[i + 2]
                unit_text = unit_tok.text
                if unit_text in _UNIT_MAP:
                    rec_type = _UNIT_MAP[unit_text]
                    rec_interval = 2
                    if unit_text in _UNIT_MULTIPLIER:
                        rec_interval = _UNIT_MULTIPLIER[unit_text] * 2
                    rec_span_start = tok.start
                    rec_span_end = unit_tok.end
                    i += 3
                    continue

            # "every N <unit>" or "every <number_word> <unit>"
            num = _token_to_number(next_tok.text)
            if num is not None and i + 2 < len(tokens):
                unit_tok = tokens[i + 2]
                unit_match = _fuzzy_match_token(unit_tok.text, list(_UNIT_MAP.keys()), threshold)
                if unit_match:
                    matched_unit, _ = unit_match
                    rec_type = _UNIT_MAP[matched_unit]
                    rec_interval = num
                    if matched_unit in _UNIT_MULTIPLIER:
                        rec_interval = _UNIT_MULTIPLIER[matched_unit] * num
                    rec_span_start = tok.start
                    rec_span_end = unit_tok.end
                    i += 3
                    continue

            # "every <unit>" (including morning/night/evening/weekday)
            unit_text = next_tok.text
            every_map = intents["recurrence_every"]
            if unit_text in every_map and every_map[unit_text] is not None:
                entry = every_map[unit_text]
                rec_type, rec_interval = entry[0], entry[1]
                if unit_text in _UNIT_MULTIPLIER:
                    rec_interval = _UNIT_MULTIPLIER[unit_text]
                rec_span_start = tok.start
                rec_span_end = next_tok.end
                # Time hint for morning/night/evening
                time_hints = intents["recurrence_time_hints"]
                if unit_text in time_hints:
                    time_hint = time_hints[unit_text]
                i += 2
                continue

            # "every <day_name>" (e.g., "every Monday")
            import calendar as _cal

            day_names = {d.lower() for d in _cal.day_name} | {d.lower() for d in _cal.day_abbr}
            day_match = _fuzzy_match_token(next_tok.text, list(day_names), threshold)
            if day_match:
                rec_type = "weekly"
                rec_interval = 1
                rec_span_start = tok.start
                rec_span_end = next_tok.end
                i += 2
                continue

        # Single-token frequency words: "daily", "weekly", etc.
        if tok.text in rec_tokens:
            entry = rec_tokens[tok.text]
            rec_type, rec_interval = entry[0], entry[1]
            rec_span_start = tok.start
            rec_span_end = tok.end
            i += 1
            continue

        # Fuzzy single-token frequency match
        match = _fuzzy_match_token(tok.text, list(rec_tokens.keys()), threshold)
        if match and len(tok.text) >= 4:
            matched_word, confidence = match
            if matched_word != tok.text:
                entry = rec_tokens[matched_word]
                rec_type, rec_interval = entry[0], entry[1]
                rec_span_start = tok.start
                rec_span_end = tok.end
                i += 1
                continue

        # "N times a <unit>" or "twice a <unit>"
        num = _token_to_number(tok.text)
        if num is not None or tok.text == "twice":
            if tok.text == "twice":
                num = 2
            if (
                i + 2 < len(tokens)
                and tokens[i + 1].text in ("times", "time")
                and i + 3 < len(tokens)
                and tokens[i + 2].text == "a"
            ):
                unit_tok = tokens[i + 3]
                unit_text = unit_tok.text
                if unit_text in _UNIT_MAP:
                    rec_type = _UNIT_MAP[unit_text]
                    rec_interval = 1
                    unit_label = unit_text.rstrip("s") if unit_text.endswith("s") else unit_text
                    times_anno = f"({num}x/{unit_label})"
                    rec_span_start = tok.start
                    rec_span_end = unit_tok.end
                    i += 4
                    continue

        i += 1

    # Reserve the recurrence span
    if (
        rec_type is not None
        and rec_span_start is not None
        and rec_span_end is not None
        and tracker.is_free(rec_span_start, rec_span_end)
    ):
        # Check for prefix word before recurrence
        for ptok in tokens:
            if (
                ptok.end == rec_span_start
                or (ptok.end <= rec_span_start and rec_span_start - ptok.end <= 1)
            ) and ptok.text in intents["date_prefixes"]:
                rec_span_start = ptok.start
                break

            display_parts = []
            if rec_type == "minutely":
                display_parts.append(f"Every {rec_interval}m")
            else:
                if rec_interval > 1:
                    display_parts.append(f"Every {rec_interval} {rec_type.replace('ly', '')}s")
                else:
                    display_parts.append(rec_type.capitalize())
            display = display_parts[0]

            tracker.reserve(
                EntitySpan(rec_span_start, rec_span_end, EntityKind.RECURRENCE, display)
            )

    # Look for "for N <unit>" suffix
    for i in range(len(tokens) - 2):
        if tokens[i].text == "for" and not tracker.is_free(tokens[i].start, tokens[i].end):
            continue
        if tokens[i].text != "for":
            continue
        num = _token_to_number(tokens[i + 1].text)
        if num is not None and i + 2 < len(tokens):
            unit_tok = tokens[i + 2]
            if unit_tok.text in _UNIT_MAP:
                start = tokens[i].start
                end = unit_tok.end
                if tracker.is_free(start, end):
                    rec_end_count = num
                    tracker.reserve(EntitySpan(start, end, EntityKind.RECURRENCE, f"for {num}"))
                    break

    # Look for "until <date>" suffix
    for i in range(len(tokens) - 1):
        if tokens[i].text != "until":
            continue
        start = tokens[i].start
        if not tracker.is_free(start, tokens[i].end):
            continue
        # Remaining text after "until"
        remaining = text[tokens[i + 1].start :]
        try:
            import dateparser as _dp

            dt = _dp.parse(
                remaining,
                languages=["en"],
                settings={
                    "RELATIVE_BASE": _datetime(today.year, today.month, today.day),
                    "PREFER_DATES_FROM": "future",
                },
            )
            if dt is not None:
                rec_end_date = dt.date()
                end = len(text)  # Consume rest of text
                tracker.reserve(
                    EntitySpan(start, end, EntityKind.RECURRENCE, f"until {rec_end_date}")
                )
        except Exception:
            pass
        break

    return rec_type, rec_interval, rec_end_date, rec_end_count, times_anno, time_hint


# ---------------------------------------------------------------------------
# Pomodoro extraction
# ---------------------------------------------------------------------------


def _extract_pomodoro(tokens: list[_Token], tracker: _SpanTracker) -> int | None:
    """Extract pomodoro estimate: ~N followed by a pomodoro unit word."""
    intents = _get_intents()
    pom_units = intents["pomodoro_units"]
    threshold = intents["fuzzy_threshold"]

    for i, tok in enumerate(tokens):
        if not tok.text.startswith("~"):
            continue
        if not tracker.is_free(tok.start, tok.end):
            continue

        # Parse ~N or ~Np
        rest = tok.text[1:]
        if not rest:
            continue

        # ~3p, ~2pom (number + unit suffix in same token)
        num_str = ""
        unit_part = ""
        for ch in rest:
            if ch.isdigit():
                num_str += ch
            else:
                unit_part = rest[len(num_str) :]
                break
        if not num_str:
            continue
        num = int(num_str)

        # Check if unit part is in the same token
        if unit_part:
            match = _fuzzy_match_token(unit_part, list(pom_units), threshold)
            if match:
                tracker.reserve(EntitySpan(tok.start, tok.end, EntityKind.POMODORO, f"~{num} pom"))
                return num
            # Check if it's a time estimate unit instead
            time_units = intents["time_estimate_units"]
            if unit_part in time_units:
                # This is estimated_minutes, not pomodoro — skip here
                continue

        # Check next token for unit word
        if i + 1 < len(tokens):
            next_tok = tokens[i + 1]
            if tracker.is_free(next_tok.start, next_tok.end):
                match = _fuzzy_match_token(next_tok.text, list(pom_units), threshold)
                if match:
                    end = next_tok.end
                    tracker.reserve(EntitySpan(tok.start, end, EntityKind.POMODORO, f"~{num} pom"))
                    return num

        # Bare ~N without unit — treat as pomodoro if number is small
        if num <= 20 and not unit_part:
            tracker.reserve(EntitySpan(tok.start, tok.end, EntityKind.POMODORO, f"~{num} pom"))
            return num

    return None


# ---------------------------------------------------------------------------
# Estimated minutes extraction (NEW)
# ---------------------------------------------------------------------------


def _extract_estimated_minutes(tokens: list[_Token], tracker: _SpanTracker) -> int | None:
    """Extract time estimate: ~90m, ~2h, ~1h30m."""
    intents = _get_intents()
    time_units = intents["time_estimate_units"]

    for tok in tokens:
        if not tok.text.startswith("~"):
            continue
        if not tracker.is_free(tok.start, tok.end):
            continue

        rest = tok.text[1:]
        if not rest:
            continue

        # Parse ~Nm, ~Nh, ~NhNm patterns
        total_minutes = 0
        pos = 0
        found_unit = False
        while pos < len(rest):
            # Extract number
            num_str = ""
            while pos < len(rest) and rest[pos].isdigit():
                num_str += rest[pos]
                pos += 1
            if not num_str:
                break
            num = int(num_str)

            # Extract unit suffix
            unit_str = ""
            while pos < len(rest) and rest[pos].isalpha():
                unit_str += rest[pos]
                pos += 1

            if unit_str in time_units:
                total_minutes += num * time_units[unit_str]
                found_unit = True
            else:
                break

        if found_unit and total_minutes > 0:
            display = (
                f"~{total_minutes}m"
                if total_minutes < 60
                else f"~{total_minutes // 60}h {total_minutes % 60}m"
            )
            tracker.reserve(EntitySpan(tok.start, tok.end, EntityKind.ESTIMATE, display))
            return total_minutes

    return None


# ---------------------------------------------------------------------------
# Date/time extraction via dateparser
# ---------------------------------------------------------------------------


def _extract_dates_and_times(
    text: str, tokens: list[_Token], tracker: _SpanTracker, today: date
) -> tuple[date | None, time | None]:
    """Extract dates and times using dateparser.search.search_dates()."""
    intents = _get_intents()
    due_date: date | None = None
    due_time: time | None = None

    # 1. Time-of-day keywords from intent dictionary (before dateparser)
    tod = intents["time_of_day"]
    tod_phrases = intents["time_of_day_phrases"]

    # Check phrases first (2-3 token windows)
    for window_size in (3, 2):
        for i in range(len(tokens) - window_size + 1):
            phrase_tokens = tokens[i : i + window_size]
            start = phrase_tokens[0].start
            end = phrase_tokens[-1].end
            if not tracker.is_free(start, end):
                continue
            phrase = " ".join(t.text for t in phrase_tokens)
            if phrase in tod_phrases:
                t = tod_phrases[phrase]
                tracker.unreserve_kind(EntityKind.TIME)
                tracker.reserve(
                    EntitySpan(start, end, EntityKind.TIME, t.strftime("%I:%M %p").lstrip("0"))
                )
                due_time = t

    # Check single tokens
    for tok in tokens:
        if not tracker.is_free(tok.start, tok.end):
            continue
        if tok.text in tod:
            t = tod[tok.text]
            tracker.unreserve_kind(EntityKind.TIME)
            tracker.reserve(
                EntitySpan(tok.start, tok.end, EntityKind.TIME, t.strftime("%I:%M %p").lstrip("0"))
            )
            due_time = t

    # 2. Use dateparser for remaining date/time extraction
    # Build unclaimed text for dateparser
    try:
        from dateparser.search import search_dates

        settings = {
            "RELATIVE_BASE": _datetime(today.year, today.month, today.day),
            "PREFER_DATES_FROM": "future",
            "STRICT_PARSING": False,
        }

        # Search for dates in the full text
        results = search_dates(text, languages=["en"], settings=settings)
        if results:
            for matched_text, dt in results:
                # Find the position of the matched text in the original string
                search_start = 0
                while True:
                    pos = text.lower().find(matched_text.lower(), search_start)
                    if pos == -1:
                        break
                    end_pos = pos + len(matched_text)

                    # Check for prefix words (due, by, on, before)
                    prefix_start = pos
                    for ptok in tokens:
                        if (
                            ptok.end <= pos
                            and pos - ptok.end <= 1
                            and ptok.text in intents["date_prefixes"]
                        ):
                            prefix_start = ptok.start
                            break

                    if tracker.is_free(prefix_start, end_pos):
                        # Determine if this is a date, time, or both
                        has_date = dt.date() != today or matched_text.lower() in ("today",)
                        has_time = dt.hour != 0 or dt.minute != 0

                        if has_date:
                            tracker.unreserve_kind(EntityKind.DATE)
                            due_date = dt.date()
                            display = due_date.strftime("%b %d, %Y")
                            tracker.reserve(
                                EntitySpan(prefix_start, end_pos, EntityKind.DATE, display)
                            )

                        if has_time and due_time is None:
                            due_time = time(dt.hour, dt.minute)
                            # Only add time span if not already covered by the date span
                            # (dateparser often returns combined date+time)
                        break
                    search_start = pos + 1

    except Exception:
        logger.log.debug("dateparser search_dates failed", exc_info=True)

    return due_date, due_time


# ---------------------------------------------------------------------------
# Remainder builder (preserved from previous parser)
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
    return " ".join(raw.split()).strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(text: str, today: date | None = None) -> ParseResult:
    """Parse a natural language task description into structured fields.

    Uses intent dictionaries + fuzzy matching + dateparser.
    No regex for NLP patterns (only @/# tag syntax).

    Args:
        text: Raw user input, e.g. "Buy groceries tomorrow at 3pm @errands"
        today: Override for today's date (for testing). Defaults to date.today().

    Returns:
        ParseResult with extracted fields and remainder as the reminder.
    """
    if today is None:
        today = date.today()

    text = _sanitize(text)
    if not text:
        return ParseResult(reminder="")

    tokens = _tokenize(text)
    tracker = _SpanTracker()

    # 1. Tags (most unambiguous)
    tags = _extract_tags(text, tokens, tracker)

    # 2. Priority
    priority = _extract_priority(text, tokens, tracker)

    # 3. Recurrence (before dates — "every Monday" contains a day name)
    rec_type, rec_interval, rec_end_date, rec_end_count, times_anno, rec_time = _extract_recurrence(
        text, tokens, tracker, today
    )

    # 4. Pomodoro estimate
    pomodoro = _extract_pomodoro(tokens, tracker)

    # 5. Estimated minutes (~90m, ~2h)
    estimated_minutes = _extract_estimated_minutes(tokens, tracker)

    # 6. Dates and times (via dateparser)
    due_date, due_time = _extract_dates_and_times(text, tokens, tracker, today)

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
        estimated_minutes=estimated_minutes,
        spans=tracker.spans,
    )
