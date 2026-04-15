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
from datetime import date, time, timedelta
from datetime import datetime as _datetime
from enum import Enum
from typing import Any, NamedTuple

from .logger import Logger
from .models import format_duration

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
    TIME_BLOCK = "time_block"
    EVENT_DATE = "event_date"
    CONDITION = "condition"


@dataclass
class EntitySpan:
    """A parsed entity's location in the original text."""

    start: int
    end: int
    kind: EntityKind
    display: str
    confidence: float = 1.0
    matched: str = ""  # The dictionary term that was fuzzy-matched (empty if exact)


@dataclass
class ParseResult:
    """Result of parsing a natural language task input."""

    reminder: str
    due_date: date | None = None
    due_time: time | None = None
    due_time_end: time | None = None  # End of ad-hoc time range
    due_time_block: str | None = None  # Canonical named time block
    priority: int | None = None
    tags: list[str] = field(default_factory=list)
    recurrence_type: str | None = None
    recurrence_interval: int = 1
    recurrence_end_date: date | None = None
    recurrence_end_count: int | None = None
    pomodoro_estimate: int | None = None
    estimated_minutes: int | None = None
    work_duration: int | None = None
    event_date: date | None = None  # Target period for scheduling tasks
    conditions: list[dict[str, str]] = field(default_factory=list)  # Structured conditions
    subtask_reminders: list[str] = field(default_factory=list)  # Inline subtask items
    spans: list[EntitySpan] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal result types
# ---------------------------------------------------------------------------


class _DateTimeResult(NamedTuple):
    """Structured return from _extract_dates_and_times."""

    due_date: date | None
    due_time: time | None
    due_time_end: time | None
    due_time_block: str | None
    event_date: date | None


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


def _get_intents() -> dict[str, Any]:
    from .intents import get_intents

    return get_intents()


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


def _tokens_to_number(tokens: list[_Token], start: int) -> tuple[int | float | None, int]:
    """Compose a multi-token number starting at index *start*.

    Handles:
        "forty five" → 45, "ninety" → 90, "one hundred" → 100,
        "two and a half" → 2.5, "one hour and thirty minutes" (via caller),
        "15" → 15

    Returns (value_or_None, last_token_index_consumed).
    If nothing matched, returns (None, start - 1).
    """
    n = len(tokens)
    if start >= n:
        return None, start - 1

    first = _token_to_number(tokens[start].text)
    if first is None:
        return None, start - 1

    idx = start

    # "X and a half" → X + 0.5
    if (
        idx + 3 < n
        and tokens[idx + 1].text == "and"
        and tokens[idx + 2].text == "a"
        and tokens[idx + 3].text == "half"
    ):
        return first + 0.5, idx + 3

    # "X hundred" → X * 100, optionally followed by "and Y"
    if idx + 1 < n and tokens[idx + 1].text == "hundred":
        total = first * 100
        idx += 1
        # "X hundred and Y"
        if idx + 2 < n and tokens[idx + 1].text == "and":
            addon = _token_to_number(tokens[idx + 2].text)
            if addon is not None:
                return total + addon, idx + 2
        return total, idx

    # Two-word composition: tens + ones ("forty five" → 45, "twenty one" → 21)
    if idx + 1 < n and first >= 20:
        second = _token_to_number(tokens[idx + 1].text)
        if second is not None and 1 <= second <= 9:
            return first + second, idx + 1

    return first, idx


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
    priority_display = intents["priority_display"]
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

    # Multi-token phrase matching FIRST (catches "not important", "high priority", etc.)
    # Build a set of phrase word-counts so we only try matching windows of the right size.
    _phrase_word_counts = {len(p.split()) for p in priority_phrases}
    for window_size in sorted(_phrase_word_counts, reverse=True):
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
                tracker.reserve(EntitySpan(start, end, EntityKind.PRIORITY, priority_display[val]))
                result_priority = val
                continue

            # Fuzzy phrase match — only against phrases of the SAME word count
            # (prevents "high priority fix" matching "high priority" at 86%)
            same_len_phrases = {
                p: v for p, v in priority_phrases.items() if len(p.split()) == window_size
            }
            if same_len_phrases:
                match = _fuzzy_match_phrase(phrase, same_len_phrases, threshold + 5)
                if match is not None:
                    matched_phrase, confidence = match
                    val = same_len_phrases[matched_phrase]
                    tracker.unreserve_kind(EntityKind.PRIORITY)
                    tracker.reserve(
                        EntitySpan(
                            start,
                            end,
                            EntityKind.PRIORITY,
                            priority_display[val],
                            confidence,
                            matched_phrase,
                        )
                    )
                    result_priority = val

    # Single-token exact matches (AFTER phrases so "not important" beats "important")
    for tok in tokens:
        if not tracker.is_free(tok.start, tok.end):
            continue
        if tok.text in priority_tokens:
            tracker.unreserve_kind(EntityKind.PRIORITY)
            val = priority_tokens[tok.text]
            tracker.reserve(
                EntitySpan(tok.start, tok.end, EntityKind.PRIORITY, priority_display[val])
            )
            result_priority = val

    # Single-token fuzzy match (for typos like "importnt", "urgnt")
    # Exclude common words that aren't priority-related
    _priority_exclude = {
        "three",
        "there",
        "through",
        "throw",
        "high",
        "low",
        "normal",
        "rent",
        "rest",
        "recent",
        "event",
        "front",
        "print",
        "point",
        "part",
        "port",
        "sort",
        "sport",
        "report",
        "import",
        "apart",
        "early",
        "every",
        "entry",
        "extra",
        "after",
        "later",
        "other",
    }
    for tok in tokens:
        if not tracker.is_free(tok.start, tok.end):
            continue
        if len(tok.text) < 4:
            continue  # Skip short tokens to avoid false positives
        if tok.text in _priority_exclude:
            continue
        if not tok.text.isalpha():
            continue  # Skip tokens with non-alpha chars like "(critical)"
        match = _fuzzy_match_token(tok.text, list(priority_tokens.keys()), threshold)
        if match is not None:
            matched_word, confidence = match
            if matched_word == tok.text:
                continue  # Already handled as exact match
            val = priority_tokens[matched_word]
            tracker.unreserve_kind(EntityKind.PRIORITY)
            tracker.reserve(
                EntitySpan(
                    tok.start,
                    tok.end,
                    EntityKind.PRIORITY,
                    priority_display[val],
                    confidence,
                    matched_word,
                )
            )
            result_priority = val

    return result_priority


# ---------------------------------------------------------------------------
# Recurrence extraction
# ---------------------------------------------------------------------------


def _extract_recurrence(
    text: str, tokens: list[_Token], tracker: _SpanTracker, today: date
) -> tuple[str | None, int, date | None, int | None, str | None, time | None]:
    """Extract recurrence pattern. Returns (type, interval, end_date, end_count, times_anno, time_hint)."""
    intents = _get_intents()
    rec_tokens = intents["recurrence_tokens"]
    unit_map = intents["unit_map"]
    unit_multiplier = intents["unit_multiplier"]
    threshold = intents["fuzzy_threshold"]
    rec_type: str | None = None
    rec_interval: int = 1
    rec_end_date: date | None = None
    rec_end_count: int | None = None
    times_anno: str | None = None
    time_hint: time | None = None
    rec_span_start: int | None = None
    rec_span_end: int | None = None
    rec_confidence: float = 1.0
    rec_matched: str = ""

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
                if unit_text in unit_map:
                    rec_type = unit_map[unit_text]
                    rec_interval = 2
                    if unit_text in unit_multiplier:
                        rec_interval = unit_multiplier[unit_text] * 2
                    rec_span_start = tok.start
                    rec_span_end = unit_tok.end
                    i += 3
                    continue

            # "every N <unit>" or "every <number_word> <unit>" or "every forty five minutes"
            num, num_end = _tokens_to_number(tokens, i + 1)
            if num is not None and num_end + 1 < len(tokens):
                unit_tok = tokens[num_end + 1]
                unit_match = _fuzzy_match_token(unit_tok.text, list(unit_map.keys()), threshold)
                if unit_match:
                    matched_unit, _ = unit_match
                    rec_type = unit_map[matched_unit]
                    rec_interval = int(num)
                    if matched_unit in unit_multiplier:
                        rec_interval = unit_multiplier[matched_unit] * int(num)
                    rec_span_start = tok.start
                    rec_span_end = unit_tok.end
                    i = num_end + 2
                    continue

            # "every <unit>" (including morning/night/evening/weekday)
            unit_text = next_tok.text
            every_map = intents["recurrence_every"]
            if unit_text in every_map and every_map[unit_text] is not None:
                entry = every_map[unit_text]
                rec_type, rec_interval = entry[0], entry[1]
                if unit_text in unit_multiplier:
                    rec_interval = unit_multiplier[unit_text]
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

        # Duration recurrence: "over/for/until ... N days/weeks/months"
        # Approximation prefixes ("about", "approximately") are quantity modifiers,
        # not duration triggers. The unit determines meaning — days/weeks = recurrence,
        # hours/minutes = time estimate. Approximation prefixes are handled separately
        # in _extract_estimated_minutes and _extract_pomodoro.
        if tok.text in ("over", "for", "until") and rec_type is None:
            _FILLER = {"the", "next", "a", "an", "period", "of"}
            j = i + 1
            while j < len(tokens) and tokens[j].text in _FILLER:
                j += 1
            if j < len(tokens):
                num = _token_to_number(tokens[j].text)
                if num is not None:
                    # Skip optional "of" after couple/few
                    unit_j = j + 1
                    if unit_j < len(tokens) and tokens[unit_j].text == "of":
                        unit_j += 1
                    if unit_j < len(tokens) and tokens[unit_j].text in unit_map:
                        rec_type = unit_map[tokens[unit_j].text]
                        rec_interval = 1
                        rec_end_count = num
                        rec_span_start = tok.start
                        rec_span_end = tokens[unit_j].end
                        # Consume trailing "is over/done/up" for "until" pattern
                        end_j = unit_j + 1
                        if end_j + 1 < len(tokens):
                            tail = f"{tokens[end_j].text} {tokens[end_j + 1].text}"
                            if tail in intents["duration_end_phrases"]:
                                rec_span_end = tokens[end_j + 1].end
                                end_j += 2
                        i = end_j
                        continue

        # Single-token frequency words: "daily", "weekly", etc.
        if tok.text in rec_tokens:
            entry = rec_tokens[tok.text]
            rec_type, rec_interval = entry[0], entry[1]
            rec_span_start = tok.start
            rec_span_end = tok.end
            i += 1
            continue

        # Fuzzy single-token frequency match (strict threshold, min 4 chars)
        _rec_exclude = {"early", "every", "really", "nearly", "easily", "mainly"}
        if tok.text in _rec_exclude:
            i += 1
            continue
        match = _fuzzy_match_token(tok.text, list(rec_tokens.keys()), threshold + 5)
        if match and len(tok.text) >= 4:
            matched_word, confidence = match
            if matched_word != tok.text:
                entry = rec_tokens[matched_word]
                rec_type, rec_interval = entry[0], entry[1]
                rec_span_start = tok.start
                rec_span_end = tok.end
                rec_confidence = confidence
                rec_matched = matched_word
                i += 1
                continue

        # "N times a <unit>" or "twice a <unit>"
        num = _token_to_number(tok.text)
        if num is not None or tok.text == "twice":
            if tok.text == "twice":
                num = 2
            # "twice a day" — no "times" token
            if (
                tok.text == "twice"
                and i + 1 < len(tokens)
                and tokens[i + 1].text == "a"
                and i + 2 < len(tokens)
            ):
                unit_tok = tokens[i + 2]
                if unit_tok.text in unit_map:
                    rec_type = unit_map[unit_tok.text]
                    rec_interval = 1
                    unit_label = (
                        unit_tok.text.rstrip("s") if unit_tok.text.endswith("s") else unit_tok.text
                    )
                    times_anno = f"({num}x/{unit_label})"
                    rec_span_start = tok.start
                    rec_span_end = unit_tok.end
                    i += 3
                    continue
            # "N times a <unit>"
            if (
                num is not None
                and i + 2 < len(tokens)
                and tokens[i + 1].text in ("times", "time")
                and i + 3 < len(tokens)
                and tokens[i + 2].text == "a"
            ):
                unit_tok = tokens[i + 3]
                unit_text = unit_tok.text
                if unit_text in unit_map:
                    rec_type = unit_map[unit_text]
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
            EntitySpan(
                rec_span_start,
                rec_span_end,
                EntityKind.RECURRENCE,
                display,
                rec_confidence,
                rec_matched,
            )
        )

    # Look for "for N <unit>" suffix — consumes tokens but doesn't create separate span
    # If no rec_type set yet, infer it: "for 5 days" → daily, "for 3 weeks" → weekly
    for i in range(len(tokens) - 2):
        if tokens[i].text != "for":
            continue
        if not tracker.is_free(tokens[i].start, tokens[i].end):
            continue
        num = _token_to_number(tokens[i + 1].text)
        if num is not None and i + 2 < len(tokens):
            unit_tok = tokens[i + 2]
            if unit_tok.text in unit_map:
                start = tokens[i].start
                end = unit_tok.end
                if tracker.is_free(start, end):
                    rec_end_count = num
                    if rec_type is None:
                        rec_type = unit_map[unit_tok.text]
                        rec_interval = 1
                    display = f"{rec_type.capitalize()} for {num}"
                    tracker.reserve(EntitySpan(start, end, EntityKind.RECURRENCE, display))
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
    """Extract pomodoro estimate: ~N/approx N followed by a pomodoro unit word."""
    intents = _get_intents()
    pom_units = intents["pomodoro_units"]
    approx_prefixes = intents["approximation_prefixes"]
    threshold = intents["fuzzy_threshold"]
    time_units = intents["time_estimate_units"]

    def _try_pom(num: int, start: int, end: int) -> int:
        tracker.reserve(EntitySpan(start, end, EntityKind.POMODORO, f"~{num} pom"))
        return num

    # Pattern 1: ~N tokens
    for i, tok in enumerate(tokens):
        if not tok.text.startswith("~"):
            continue
        if not tracker.is_free(tok.start, tok.end):
            continue

        rest = tok.text[1:]
        if not rest:
            continue

        # Parse number from rest (digits or number word)
        num_str = ""
        unit_part = ""
        for ch in rest:
            if ch.isdigit():
                num_str += ch
            else:
                unit_part = rest[len(num_str) :]
                break
        if num_str:
            num = int(num_str)
        else:
            num = _token_to_number(rest)
            if num is None:
                continue
            unit_part = ""

        # Unit in same token: ~3p, ~2pom
        if unit_part:
            if _fuzzy_match_token(unit_part, list(pom_units), threshold):
                return _try_pom(num, tok.start, tok.end)
            if unit_part in time_units:
                continue  # Time estimate, not pomodoro

        # Unit in next token: ~3 sessions, ~2 pom
        if i + 1 < len(tokens):
            next_tok = tokens[i + 1]
            if tracker.is_free(next_tok.start, next_tok.end):
                if _fuzzy_match_token(next_tok.text, list(pom_units), threshold):
                    return _try_pom(num, tok.start, next_tok.end)
                if next_tok.text in time_units:
                    continue  # Two-token estimate like ~2 hr — handled by estimate extractor

        # Bare ~N without unit — pomodoro if small number
        if num <= 20 and not unit_part:
            return _try_pom(num, tok.start, tok.end)

    # Pattern 2: approximation prefix + N + unit ("approximately 3 sessions", "about two pom")
    for i, tok in enumerate(tokens):
        if tok.text not in approx_prefixes:
            continue
        if not tracker.is_free(tok.start, tok.end):
            continue
        if i + 2 >= len(tokens):
            continue
        num = _token_to_number(tokens[i + 1].text)
        if num is None:
            continue
        unit_tok = tokens[i + 2]
        # Skip if unit is an am/pm marker (e.g., "around three pm" is a time, not pomodoro)
        if unit_tok.text in ("am", "pm", "a.m.", "p.m."):
            continue
        if tracker.is_free(unit_tok.start, unit_tok.end) and _fuzzy_match_token(
            unit_tok.text, list(pom_units), threshold
        ):
            return _try_pom(num, tok.start, unit_tok.end)

    return None


# ---------------------------------------------------------------------------
# Estimated minutes extraction (NEW)
# ---------------------------------------------------------------------------


def _fractional_hour_phrase(tokens: list[_Token], start: int) -> tuple[int, int] | None:
    """Match a fractional-hour idiom starting at tokens[start].

    Returns ``(minutes, end_idx_inclusive)`` or None. Handles:
        half an hour / half hour / a half hour / a half an hour → 30
        a quarter of an hour / quarter of an hour / quarter hour → 15
        N quarters of an hour  (N ∈ {1,2,3}) → N × 15
        three quarters hour → 45

    Used by both _extract_estimated_minutes (bare idiom → duration)
    and the "in" branch of _extract_dates_and_times (prefixed by
    "in" → relative future time). Keeping the match logic in one
    place guarantees the two extractors agree on what counts as a
    fractional-hour phrase, so a new form added here is picked up
    by both paths with no further changes.
    """
    n_toks = len(tokens)
    if start >= n_toks:
        return None
    t0 = tokens[start].text
    # "half an hour" / "half hour"
    if t0 == "half":
        if (
            start + 2 < n_toks
            and tokens[start + 1].text in ("an", "a")
            and tokens[start + 2].text in ("hour", "hr")
        ):
            return 30, start + 2
        if start + 1 < n_toks and tokens[start + 1].text in ("hour", "hr"):
            return 30, start + 1
    # "a half hour" / "a half an hour"
    if t0 in ("a", "an") and start + 1 < n_toks and tokens[start + 1].text == "half":
        if (
            start + 3 < n_toks
            and tokens[start + 2].text in ("an", "a")
            and tokens[start + 3].text in ("hour", "hr")
        ):
            return 30, start + 3
        if start + 2 < n_toks and tokens[start + 2].text in ("hour", "hr"):
            return 30, start + 2
    # "a quarter of an hour" / "quarter of an hour" / "quarter hour"
    if t0 == "quarter" or (
        t0 in ("a", "an") and start + 1 < n_toks and tokens[start + 1].text == "quarter"
    ):
        q_start = start + 1 if t0 in ("a", "an") else start
        if (
            q_start + 3 < n_toks
            and tokens[q_start + 1].text == "of"
            and tokens[q_start + 2].text in ("an", "a")
            and tokens[q_start + 3].text in ("hour", "hr")
        ):
            return 15, q_start + 3
        if q_start + 1 < n_toks and tokens[q_start + 1].text in ("hour", "hr"):
            return 15, q_start + 1
    # "N quarters of an hour" (N ∈ {1,2,3})
    n_val, n_end = _tokens_to_number(tokens, start)
    if (
        n_val is not None
        and 1 <= int(n_val) <= 3
        and n_end + 1 < n_toks
        and tokens[n_end + 1].text in ("quarters", "quarter")
    ):
        q_end = n_end + 1
        if (
            q_end + 3 < n_toks
            and tokens[q_end + 1].text == "of"
            and tokens[q_end + 2].text in ("an", "a")
            and tokens[q_end + 3].text in ("hour", "hr")
        ):
            return int(n_val) * 15, q_end + 3
        if q_end + 1 < n_toks and tokens[q_end + 1].text in ("hour", "hr"):
            return int(n_val) * 15, q_end + 1
    return None


def _extract_estimated_minutes(tokens: list[_Token], tracker: _SpanTracker) -> int | None:
    """Extract time estimate: ~90m, ~2h, ~1h30m, approximately 2 hours, about 90 min."""
    intents = _get_intents()
    time_units = intents["time_estimate_units"]
    approx_prefixes = intents["approximation_prefixes"]

    def _parse_inline_estimate(text: str) -> int | None:
        """Parse NhNm / Nm / Nh from a string like '90m', '2h', '1h30m'."""
        total = 0
        pos = 0
        found = False
        while pos < len(text):
            num_str = ""
            while pos < len(text) and text[pos].isdigit():
                num_str += text[pos]
                pos += 1
            if not num_str:
                break
            unit_str = ""
            while pos < len(text) and text[pos].isalpha():
                unit_str += text[pos]
                pos += 1
            if unit_str in time_units:
                total += int(num_str) * time_units[unit_str]
                found = True
            else:
                break
        return total if found and total > 0 else None

    def _make_display(minutes: int) -> str:
        return format_duration(minutes)

    # Pattern 1: ~NhNm / ~Nm / ~Nh in a single token
    for i, tok in enumerate(tokens):
        if not tok.text.startswith("~"):
            continue
        if not tracker.is_free(tok.start, tok.end):
            continue
        rest = tok.text[1:]
        if not rest:
            continue

        result = _parse_inline_estimate(rest)
        if result is not None:
            tracker.reserve(
                EntitySpan(tok.start, tok.end, EntityKind.ESTIMATE, _make_display(result))
            )
            return result

        # Pattern 2: ~N <unit> as two tokens (e.g. "~2 hr", "~90 min")
        num = _token_to_number(rest)
        if num is not None and i + 1 < len(tokens):
            next_tok = tokens[i + 1]
            if next_tok.text in time_units and tracker.is_free(tok.start, next_tok.end):
                total = num * time_units[next_tok.text]
                tracker.reserve(
                    EntitySpan(tok.start, next_tok.end, EntityKind.ESTIMATE, _make_display(total))
                )
                return total

    # Pattern 3: approximation prefix + N + unit ("approximately 2 hours", "about 90 min")
    for i, tok in enumerate(tokens):
        if tok.text not in approx_prefixes:
            continue
        if not tracker.is_free(tok.start, tok.end):
            continue
        if i + 2 >= len(tokens):
            continue
        num, num_end = _tokens_to_number(tokens, i + 1)
        if num is None:
            continue
        unit_idx = num_end + 1
        if unit_idx < len(tokens):
            unit_tok = tokens[unit_idx]
            if unit_tok.text in time_units and tracker.is_free(tok.start, unit_tok.end):
                total = int(num * time_units[unit_tok.text])
                tracker.reserve(
                    EntitySpan(tok.start, unit_tok.end, EntityKind.ESTIMATE, _make_display(total))
                )
                return total

    # Pattern 3.5: Fractional-hour idioms that don't fit the bare
    # "N unit" shape. Handles "half an hour" → 30, "a quarter of an
    # hour" → 15, "three quarters of an hour" → 45, and so on. Must
    # run before Pattern 4 or the bare number at the front of "three
    # quarters of an hour" would be consumed as if "three" were a
    # unit count.
    #
    # Guard: skip when any token in the matched phrase is preceded
    # (within 4 tokens) by "in". That's a relative-time prefix that
    # the date extractor will pick up later via the same
    # _fractional_hour_phrase helper, so we must leave the span
    # unreserved for it. The single-token lookback (prev tok == "in")
    # isn't enough because phrases like "in a quarter of an hour"
    # start matching two tokens after the "in" trigger.
    def _preceded_by_in(start: int) -> bool:
        for k in range(1, 5):
            j = start - k
            if j < 0:
                return False
            if tokens[j].text == "in":
                return True
        return False

    for i, tok in enumerate(tokens):
        if not tracker.is_free(tok.start, tok.end):
            continue
        if _preceded_by_in(i):
            continue
        match = _fractional_hour_phrase(tokens, i)
        if match is None:
            continue
        minutes, end_idx = match
        span_end = tokens[end_idx].end
        if not tracker.is_free(tok.start, span_end):
            continue
        tracker.reserve(
            EntitySpan(tok.start, span_end, EntityKind.ESTIMATE, _make_display(minutes))
        )
        return minutes

    # Pattern 4: bare N unit(s) [and M unit(s)] without prefix
    # "thirty minutes", "ninety minutes", "one hour and thirty minutes", "two and a half hours"
    # Guard: skip if the immediately preceding token is a work-duration
    # or fraction anchor, OR if any token within the last 4 positions
    # is "in" (relative-time prefix). The 4-token lookback catches
    # "in three quarters of an hour" matching at "an hour", where the
    # immediate prev is "of".
    _ESTIMATE_SKIP_PREV = {"length", "session", "half", "every"}
    for i, tok in enumerate(tokens):
        if not tracker.is_free(tok.start, tok.end):
            continue
        if i > 0 and tokens[i - 1].text in _ESTIMATE_SKIP_PREV:
            continue
        if _preceded_by_in(i):
            continue
        # Check 2 tokens back through articles: "in a couple days"
        if (
            i > 1
            and tokens[i - 1].text in ("a", "an")
            and tokens[i - 2].text in _ESTIMATE_SKIP_PREV
        ):
            continue
        num, num_end = _tokens_to_number(tokens, i)
        if num is None or num <= 0:
            continue
        unit_idx = num_end + 1
        if unit_idx >= len(tokens):
            continue
        unit_tok = tokens[unit_idx]
        if unit_tok.text not in time_units:
            continue
        # Guard: "a m" after a number word 1-12 is likely am/pm, not "1 minute"
        if tok.text == "a" and unit_tok.text == "m" and i > 0:
            prev_num = _token_to_number(tokens[i - 1].text)
            if prev_num is not None and 1 <= prev_num <= 12:
                continue
        if not tracker.is_free(tok.start, unit_tok.end):
            continue
        total = int(num * time_units[unit_tok.text])
        span_end = unit_tok.end

        # Check for compound forms after "N unit":
        #   (a) "N unit and a half" → + half the unit value
        #   (b) "N unit and M unit2" → + M * unit2
        #   (c) "N hour(s) M" (bare number, implies minutes)
        if (
            unit_idx + 3 < len(tokens)
            and tokens[unit_idx + 1].text == "and"
            and tokens[unit_idx + 2].text in ("a", "an")
            and tokens[unit_idx + 3].text == "half"
        ):
            half_minutes = time_units[unit_tok.text] // 2
            if half_minutes > 0 and tracker.is_free(tok.start, tokens[unit_idx + 3].end):
                total += half_minutes
                span_end = tokens[unit_idx + 3].end
        elif unit_idx + 3 < len(tokens) and tokens[unit_idx + 1].text == "and":
            num2, num2_end = _tokens_to_number(tokens, unit_idx + 2)
            if num2 is not None and num2_end + 1 < len(tokens):
                unit2_tok = tokens[num2_end + 1]
                if unit2_tok.text in time_units and tracker.is_free(tok.start, unit2_tok.end):
                    total += int(num2 * time_units[unit2_tok.text])
                    span_end = unit2_tok.end
        elif unit_tok.text in ("hour", "hours", "hr", "hrs") and unit_idx + 1 < len(tokens):
            # "one hour thirty" → 90, "two hours fifteen" → 135
            num2, num2_end = _tokens_to_number(tokens, unit_idx + 1)
            if (
                num2 is not None
                and 0 < int(num2) < 60
                and tracker.is_free(tok.start, tokens[num2_end].end)
            ):
                total += int(num2)
                span_end = tokens[num2_end].end

        tracker.reserve(EntitySpan(tok.start, span_end, EntityKind.ESTIMATE, _make_display(total)))
        return total

    return None


def _extract_work_duration(tokens: list[_Token], tracker: _SpanTracker) -> int | None:
    """Extract per-task work duration: 'session length N minutes/min'."""
    for i in range(len(tokens) - 3):
        if tokens[i].text != "session" or tokens[i + 1].text != "length":
            continue
        start = tokens[i].start
        if not tracker.is_free(start, tokens[i + 1].end):
            continue
        num = _token_to_number(tokens[i + 2].text)
        if num is None:
            continue
        # Check for unit: "minutes", "min"
        if i + 3 < len(tokens) and tokens[i + 3].text in ("minutes", "minute", "min"):
            end = tokens[i + 3].end
            if tracker.is_free(start, end):
                tracker.reserve(
                    EntitySpan(start, end, EntityKind.WORK_DURATION, f"{num}min session")
                )
                return num
        # No unit — just "session length N"
        end = tokens[i + 2].end
        if tracker.is_free(start, end):
            tracker.reserve(EntitySpan(start, end, EntityKind.WORK_DURATION, f"{num}min session"))
            return num

    return None


# ---------------------------------------------------------------------------
# Date/time extraction via dateparser
# ---------------------------------------------------------------------------


def _resolve_day_name(name: str, today: date) -> date:
    """Resolve a day name to the next occurrence (never today)."""
    import calendar as _cal

    day_map = {}
    for i, d in enumerate(_cal.day_name):
        day_map[d.lower()] = i
    for i, d in enumerate(_cal.day_abbr):
        day_map[d.lower()] = i

    target = day_map.get(name.lower())
    if target is None:
        return today
    diff = (target - today.weekday()) % 7
    if diff == 0:
        diff = 7  # Never today — "Friday" on Friday means next Friday
    return today + timedelta(days=diff)


def _resolve_next_day_name(name: str, today: date) -> date:
    """Resolve 'next <day>' to the occurrence AFTER the upcoming one."""
    upcoming = _resolve_day_name(name, today)
    return upcoming + timedelta(days=7)


def _add_months(d: date, months: int) -> date:
    """Add months to a date, clamping day to valid range."""
    import calendar as _cal

    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    max_day = _cal.monthrange(year, month)[1]
    return date(year, month, min(d.day, max_day))


def _ordinal_to_day(token_text: str, next_token_text: str | None = None) -> tuple[int | None, int]:
    """Convert token(s) to a day-of-month (1-31) from digit ordinals or ordinal words.

    Handles: "1st", "2nd", "15th", "first", "fifteenth", "twenty-first",
    and two-token "twenty first" (voice dictation, no hyphen).

    Returns (day_number_or_None, tokens_consumed). tokens_consumed is 1 or 2.
    """
    intents = _get_intents()
    ordinals = intents["ordinal_words"]

    # Digit-based: strip suffix
    stripped = (
        token_text.removesuffix("st").removesuffix("nd").removesuffix("rd").removesuffix("th")
    )
    if stripped.isdigit():
        num = int(stripped)
        if 1 <= num <= 31:
            return num, 1

    # Single word ordinal: "first", "fifteenth", "twentieth"
    val = ordinals.get(token_text)
    if val is not None:
        return val, 1

    # Two-token compound: "twenty first" → look up "twenty-first" (hyphenated form)
    if next_token_text is not None:
        hyphenated = f"{token_text}-{next_token_text}"
        val = ordinals.get(hyphenated)
        if val is not None:
            return val, 2

    return None, 0


def _extract_dates_and_times(
    text: str, tokens: list[_Token], tracker: _SpanTracker, today: date
) -> _DateTimeResult:
    """Extract dates and times: token-based for common patterns, dateparser for complex ones."""
    import calendar as _cal

    intents = _get_intents()
    due_date: date | None = None
    due_time: time | None = None
    due_time_end: time | None = None
    skip_dateparser = False

    day_names = {}
    for i, d in enumerate(_cal.day_name):
        day_names[d.lower()] = i
    for i, d in enumerate(_cal.day_abbr):
        day_names[d.lower()] = i

    month_names = {}
    for i in range(1, 13):
        month_names[_cal.month_name[i].lower()] = i
        month_names[_cal.month_abbr[i].lower()] = i

    def _set_date(d: date, start: int, end: int) -> None:
        nonlocal due_date
        # Check for prefix word(s) before the date tokens
        prefix_start = start
        # Single-word prefixes: "due", "by", "on", "before"
        for ptok in tokens:
            if (
                ptok.end <= start
                and start - ptok.end <= 1
                and ptok.text in intents["date_prefixes"]
            ):
                prefix_start = ptok.start
                break
        # Multi-word constraint prefixes: "no later than", "prior to", etc.
        for phrase in intents.get("constraint_keywords", []):
            phrase_words = phrase.split()
            phrase_len = len(phrase_words)
            for ti in range(len(tokens)):
                if tokens[ti].start >= start:
                    break
                if ti + phrase_len <= len(tokens):
                    candidate = " ".join(tokens[ti + j].text for j in range(phrase_len))
                    if (
                        candidate == phrase
                        and tokens[ti + phrase_len - 1].end <= start
                        and start - tokens[ti + phrase_len - 1].end <= 1
                    ):
                        prefix_start = min(prefix_start, tokens[ti].start)
                        break
        if tracker.is_free(prefix_start, end):
            tracker.unreserve_kind(EntityKind.DATE)
            due_date = d
            tracker.reserve(EntitySpan(prefix_start, end, EntityKind.DATE, d.strftime("%b %d, %Y")))

    def _set_time(t: time, start: int, end: int) -> None:
        nonlocal due_time
        if tracker.is_free(start, end):
            tracker.unreserve_kind(EntityKind.TIME)
            due_time = t
            tracker.reserve(
                EntitySpan(start, end, EntityKind.TIME, t.strftime("%I:%M %p").lstrip("0"))
            )

    # --- Event date: scheduling verb + "for" + date expression ---
    event_date: date | None = None
    scheduling_verbs = intents.get("scheduling_verbs", [])
    _single_sched = {v for v in scheduling_verbs if " " not in v}
    _multi_sched = [v for v in scheduling_verbs if " " in v]

    _has_sched_verb = any(
        tok.text in _single_sched and tracker.is_free(tok.start, tok.end) for tok in tokens
    )
    if not _has_sched_verb:
        for mv in _multi_sched:
            words = mv.split()
            for j in range(len(tokens) - len(words) + 1):
                phrase = " ".join(tokens[j + k].text for k in range(len(words)))
                if phrase == mv and tracker.is_free(
                    tokens[j].start, tokens[j + len(words) - 1].end
                ):
                    _has_sched_verb = True
                    break
            if _has_sched_verb:
                break

    if _has_sched_verb:
        for j, tok in enumerate(tokens):
            if tok.text != "for" or not tracker.is_free(tok.start, tok.end):
                continue
            if j + 1 >= len(tokens):
                continue
            next_tok = tokens[j + 1]
            resolved = intents["date_abbreviations"].get(next_tok.text, next_tok.text)
            ed: date | None = None
            ed_end = next_tok.end

            if resolved == "tomorrow":
                ed = today + timedelta(days=1)
            elif next_tok.text == "next" and j + 2 < len(tokens):
                target = tokens[j + 2]
                ed_end = target.end
                if target.text == "week":
                    ed = today + timedelta(days=7)
                elif target.text == "month":
                    ed = _add_months(today, 1)
                elif target.text in day_names:
                    ed = _resolve_next_day_name(target.text, today)
            elif next_tok.text in day_names:
                ed = _resolve_day_name(next_tok.text, today)
            elif next_tok.text in month_names and j + 2 < len(tokens):
                m = month_names[next_tok.text]
                day_tok = tokens[j + 2]
                day_num = None
                if day_tok.text.isdigit():
                    day_num = int(day_tok.text)
                else:
                    day_num = _token_to_number(day_tok.text.rstrip(","))
                if day_num is not None:
                    import contextlib

                    with contextlib.suppress(ValueError):
                        ed = date(today.year, m, day_num)
                        if ed < today:
                            ed = date(today.year + 1, m, day_num)
                        ed_end = day_tok.end

            if ed is not None:
                event_date = ed
                tracker.reserve(
                    EntitySpan(tok.start, ed_end, EntityKind.EVENT_DATE, ed.strftime("%b %d, %Y"))
                )
                break

    # --- Token-based date resolution ---
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tracker.is_free(tok.start, tok.end):
            i += 1
            continue

        # Resolve abbreviations for date words
        resolved = intents["date_abbreviations"].get(tok.text, tok.text)

        # "today", "tomorrow", "yesterday"
        if resolved == "today":
            _set_date(today, tok.start, tok.end)
        elif resolved == "tomorrow":
            _set_date(today + timedelta(days=1), tok.start, tok.end)
        elif resolved == "yesterday":
            _set_date(today - timedelta(days=1), tok.start, tok.end)

        # "day after tomorrow"
        elif (
            tok.text == "day"
            and i + 2 < len(tokens)
            and tokens[i + 1].text == "after"
            and tokens[i + 2].text == "tomorrow"
        ):
            _set_date(today + timedelta(days=2), tok.start, tokens[i + 2].end)
            i += 2

        # "next <day>", "next week", "next month"
        elif tok.text == "next" and i + 1 < len(tokens):
            next_tok = tokens[i + 1]
            if next_tok.text in day_names:
                _set_date(_resolve_next_day_name(next_tok.text, today), tok.start, next_tok.end)
                i += 1
            elif next_tok.text == "week":
                _set_date(today + timedelta(days=7), tok.start, next_tok.end)
                i += 1
            elif next_tok.text == "month":
                _set_date(_add_months(today, 1), tok.start, next_tok.end)
                i += 1

        # "this weekend"
        elif tok.text == "this" and i + 1 < len(tokens) and tokens[i + 1].text == "weekend":
            days_until_sat = (5 - today.weekday()) % 7
            if days_until_sat == 0:
                days_until_sat = 7
            _set_date(today + timedelta(days=days_until_sat), tok.start, tokens[i + 1].end)
            i += 1

        # "end of week", "end of the week"
        elif tok.text == "end" and i + 2 < len(tokens) and tokens[i + 1].text == "of":
            remaining_tokens = [t.text for t in tokens[i + 2 : i + 4]]
            if "week" in remaining_tokens:
                end_idx = i + 2
                if "the" in remaining_tokens:
                    end_idx = i + 3
                days_until_fri = (4 - today.weekday()) % 7
                if days_until_fri == 0:
                    days_until_fri = 7
                _set_date(today + timedelta(days=days_until_fri), tok.start, tokens[end_idx].end)
                i = end_idx
            elif "month" in remaining_tokens:
                end_idx = i + 2
                if "the" in remaining_tokens:
                    end_idx = i + 3
                next_month = _add_months(today.replace(day=1), 1)
                last_day = next_month - timedelta(days=1)
                _set_date(last_day, tok.start, tokens[end_idx].end)
                i = end_idx

        # "in N days/weeks/months" or "in a week/month" or "in a couple/few days"
        elif tok.text == "in" and i + 1 < len(tokens):
            next_tok = tokens[i + 1]

            # "in <fractional hour phrase>" → now + N minutes.
            # Covers "in half an hour", "in a quarter of an hour",
            # "in three quarters of an hour", etc. The shared
            # _fractional_hour_phrase helper is the single source of
            # truth for what counts as a fractional-hour idiom, so
            # the relative-time branch and the duration extractor
            # always agree.
            frac = _fractional_hour_phrase(tokens, i + 1)
            if frac is not None:
                from datetime import datetime as _dt_now

                minutes, end_idx = frac
                now = _dt_now.now()
                future = now + timedelta(minutes=minutes)
                _set_time(time(future.hour, future.minute), tok.start, tokens[end_idx].end)
                due_date = today  # Set directly — span already reserved for time
                i = end_idx + 1
                continue

            num = _token_to_number(next_tok.text)

            # "in a couple of days", "in a few days"
            couple_few = intents.get("couple_few", {})
            if next_tok.text == "a" and i + 2 < len(tokens):
                cf_tok = tokens[i + 2]
                if cf_tok.text in couple_few:
                    cf_num = couple_few[cf_tok.text]
                    # Check for "of" after couple/few
                    unit_idx = i + 3
                    if unit_idx < len(tokens) and tokens[unit_idx].text == "of":
                        unit_idx += 1
                    if unit_idx < len(tokens):
                        unit = tokens[unit_idx].text
                        if unit in ("day", "days"):
                            _set_date(
                                today + timedelta(days=cf_num), tok.start, tokens[unit_idx].end
                            )
                            i = unit_idx
                        elif unit in ("week", "weeks"):
                            _set_date(
                                today + timedelta(weeks=cf_num), tok.start, tokens[unit_idx].end
                            )
                            i = unit_idx
                    i += 1
                    continue

            if num is not None and i + 2 < len(tokens):
                unit_tok = tokens[i + 2]
                unit = unit_tok.text
                if unit in ("day", "days"):
                    _set_date(today + timedelta(days=num), tok.start, unit_tok.end)
                    i += 2
                elif unit in ("week", "weeks"):
                    _set_date(today + timedelta(weeks=num), tok.start, unit_tok.end)
                    i += 2
                elif unit in ("month", "months"):
                    _set_date(_add_months(today, num), tok.start, unit_tok.end)
                    i += 2
                elif unit in ("minute", "minutes"):
                    from datetime import datetime as _dt_now

                    now = _dt_now.now()
                    future = now + timedelta(minutes=num)
                    _set_time(time(future.hour, future.minute), tok.start, unit_tok.end)
                    i += 2
                elif unit in ("hour", "hours"):
                    from datetime import datetime as _dt_now

                    now = _dt_now.now()
                    future = now + timedelta(hours=num)
                    _set_time(time(future.hour, future.minute), tok.start, unit_tok.end)
                    i += 2

            # "in a week", "in a month"
            elif next_tok.text in ("a", "an") and i + 2 < len(tokens):
                unit = tokens[i + 2].text
                if unit in ("week",):
                    _set_date(today + timedelta(weeks=1), tok.start, tokens[i + 2].end)
                    i += 2
                elif unit in ("month",):
                    _set_date(_add_months(today, 1), tok.start, tokens[i + 2].end)
                    i += 2
                elif unit in ("hour",):
                    from datetime import datetime as _dt_now

                    now = _dt_now.now()
                    future = now + timedelta(hours=1)
                    _set_time(time(future.hour, future.minute), tok.start, tokens[i + 2].end)
                    i += 2

        # Nth weekday of month: "first Monday of April",
        # "last Friday of next month", "second Tuesday of this month".
        # Must precede the bare day-name branch or a standalone
        # "Monday" token would be consumed before this pattern fires.
        elif (
            (tok.text in intents["ordinal_words"] or tok.text == "last")
            and i + 3 < len(tokens)
            and tokens[i + 1].text in day_names
            and tokens[i + 2].text == "of"
        ):
            weekday_idx = day_names[tokens[i + 1].text]
            n = -1 if tok.text == "last" else intents["ordinal_words"][tok.text]
            # Month specifier: single-token month name, or
            # "next month" / "this month" / "the month".
            target_month: int | None = None
            target_year = today.year
            month_spec_end = i + 2
            spec_tok = tokens[i + 3]
            if spec_tok.text in month_names:
                target_month = month_names[spec_tok.text]
                month_spec_end = i + 3
            elif (
                i + 4 < len(tokens)
                and spec_tok.text in ("next", "this", "the")
                and tokens[i + 4].text == "month"
            ):
                if spec_tok.text == "next":
                    nm = _add_months(today.replace(day=1), 1)
                    target_month = nm.month
                    target_year = nm.year
                else:
                    target_month = today.month
                month_spec_end = i + 4

            if target_month is not None and (1 <= n <= 5 or n == -1):
                import calendar as _cal_mod

                # _n and _wd default args bind the loop variables at
                # definition time so the inner function is safe under
                # ruff's B023 (closure-over-loop-variable) check — the
                # parent while loop mutates `n` and `weekday_idx` each
                # iteration.
                def _resolve_nth_weekday(
                    y: int, m: int, _n: int = n, _wd: int = weekday_idx
                ) -> date:
                    fom = date(y, m, 1)
                    if _n == -1:
                        _, last_day_num = _cal_mod.monthrange(y, m)
                        last_d = date(y, m, last_day_num)
                        back = (last_d.weekday() - _wd) % 7
                        return last_d - timedelta(days=back)
                    off = (_wd - fom.weekday()) % 7
                    candidate = fom + timedelta(days=off + (_n - 1) * 7)
                    if candidate.month != m:
                        # Nth doesn't exist (e.g. "fifth Monday" in
                        # a 4-Monday month). Graceful fall back to
                        # the last occurrence so we always return
                        # something sensible instead of leaking
                        # the phrase to dateparser.
                        _, last_day_num = _cal_mod.monthrange(y, m)
                        last_d = date(y, m, last_day_num)
                        back = (last_d.weekday() - _wd) % 7
                        return last_d - timedelta(days=back)
                    return candidate

                resolved = _resolve_nth_weekday(target_year, target_month)

                # Push to next year if the resolved date is already past.
                # Only applies to bare month-name forms; "next/this/the
                # month" already picked their target month explicitly.
                if resolved is not None and spec_tok.text in month_names and resolved < today:
                    target_year += 1
                    resolved = _resolve_nth_weekday(target_year, target_month)

                if resolved is not None:
                    _set_date(resolved, tok.start, tokens[month_spec_end].end)
                # Always advance past the matched phrase so a non-
                # existent Nth (e.g. "fifth Monday" in a 4-Monday
                # month) doesn't fall through to the bare-weekday
                # branch and set a completely wrong date.
                i = month_spec_end

        # Day name (bare): "Friday", "Monday" etc.
        elif tok.text in day_names:
            _set_date(_resolve_day_name(tok.text, today), tok.start, tok.end)

        # "the 15th" / "the first" / "the fifteenth" / "the twenty first" or "... of <month>"
        elif tok.text == "the" and i + 1 < len(tokens):
            next2 = tokens[i + 2].text if i + 2 < len(tokens) else None
            day_num, ord_consumed = _ordinal_to_day(tokens[i + 1].text, next2)
            if day_num is not None:
                ord_end_idx = i + ord_consumed  # index of last ordinal token
                # Check for "of <month>" after the ordinal
                of_idx = ord_end_idx + 1
                if (
                    of_idx + 1 < len(tokens)
                    and tokens[of_idx].text == "of"
                    and tokens[of_idx + 1].text in month_names
                ):
                    m = month_names[tokens[of_idx + 1].text]
                    try:
                        d = date(today.year, m, day_num)
                        if d < today:
                            d = date(today.year + 1, m, day_num)
                        _set_date(d, tok.start, tokens[of_idx + 1].end)
                    except ValueError:
                        pass
                    i = of_idx + 1
                else:
                    # Just "the 15th" / "the first" — this month or next
                    try:
                        d = date(today.year, today.month, day_num)
                        if d <= today:
                            d = _add_months(d, 1)
                        _set_date(d, tok.start, tokens[ord_end_idx].end)
                    except ValueError:
                        pass
                    i = ord_end_idx

        # Month name + day: "March 20", "March 20 2027"
        elif tok.text in month_names:
            m = month_names[tok.text]
            if i + 1 < len(tokens):
                next2_month = tokens[i + 2].text if i + 2 < len(tokens) else None
                day_num, ord_consumed_m = _ordinal_to_day(
                    tokens[i + 1].text.rstrip(","), next2_month
                )
                if day_num is not None:
                    year = today.year
                    end_idx = i + ord_consumed_m
                    invalid_date = False
                    # Check for year after ordinal
                    year_idx = end_idx + 1
                    if (
                        year_idx < len(tokens)
                        and tokens[year_idx].text.isdigit()
                        and len(tokens[year_idx].text) == 4
                    ):
                        year = int(tokens[year_idx].text)
                        end_idx = year_idx
                    else:
                        try:
                            d = date(year, m, day_num)
                            if d < today:
                                year += 1
                        except ValueError:
                            invalid_date = True
                    if not invalid_date:
                        import contextlib

                        with contextlib.suppress(ValueError):
                            _set_date(date(year, m, day_num), tok.start, tokens[end_idx].end)
                    else:
                        # Invalid date (e.g. Feb 30) — skip dateparser fallback
                        skip_dateparser = True
                    i = end_idx

        i += 1

    # --- Phase 2: Time-of-day keywords ---
    tod = intents["time_of_day"]
    tod_phrases = intents["time_of_day_phrases"]
    time_block_words = intents.get("time_block_words", {})
    _today_implying_phrases = {"this morning", "this afternoon", "this evening"}
    _today_implying_words = {"tonight"}
    due_time_block: str | None = None

    # Multi-word time_of_day phrases first ("this morning", "this afternoon", etc.)
    for window_size in (3, 2):
        for j in range(len(tokens) - window_size + 1):
            phrase_tokens = tokens[j : j + window_size]
            start = phrase_tokens[0].start
            end = phrase_tokens[-1].end
            if not tracker.is_free(start, end):
                continue
            phrase = " ".join(t.text for t in phrase_tokens)
            if phrase in tod_phrases:
                _set_time(tod_phrases[phrase], start, end)
                if phrase in _today_implying_phrases and due_date is None:
                    due_date = today
                # Derive time_block from tod_phrase (e.g., "this afternoon" → "afternoon")
                if due_time_block is None:
                    last_word = phrase_tokens[-1].text
                    if last_word in time_block_words:
                        due_time_block = time_block_words[last_word]
            # Multi-word time block phrases ("late afternoon", "early morning", "first thing")
            if phrase in time_block_words and due_time_block is None:
                due_time_block = time_block_words[phrase]
                if not tracker.is_free(start, end):
                    continue  # Already reserved by tod_phrases above — that's fine
                tracker.reserve(
                    EntitySpan(
                        start, end, EntityKind.TIME_BLOCK, due_time_block.replace("_", " ").title()
                    )
                )

    # Track whether Phase 2 skipped "morning"/"evening" for AM/PM context in Phase 3
    _skipped_tod_context: str | None = None

    for j, tok in enumerate(tokens):
        if not tracker.is_free(tok.start, tok.end):
            continue
        if tok.text in tod:
            # Skip single-word time_of_day if followed by a time-introducing word + potential time
            if j + 2 < len(tokens) and tokens[j + 1].text in (
                "at",
                "by",
                "before",
                "after",
                "between",
                "from",
            ):
                _skipped_tod_context = tok.text
                continue
            # Don't override a time already set by Phase 1 relative expressions
            if due_time is not None:
                continue
            _set_time(tod[tok.text], tok.start, tok.end)
            # Set time_block from single-word matches (morning, evening, tonight, etc.)
            if tok.text in time_block_words and due_time_block is None:
                due_time_block = time_block_words[tok.text]
            if tok.text in _today_implying_words and due_date is None:
                due_date = today

    # --- Phase 2b: Time block words not in time_of_day (night, breakfast, dinner, etc.) ---
    # Meal words set the block but stay in the reminder (they're meaningful content).
    # Explicit time words (night, evening) take precedence over meal words (dinner, lunch).
    _meal_words = {"breakfast", "lunch", "dinner", "supper", "lunchtime"}
    if due_time_block is None:
        _meal_fallback: str | None = None
        for window_size in (2, 1):
            for j in range(len(tokens) - window_size + 1):
                phrase_tokens = tokens[j : j + window_size]
                start = phrase_tokens[0].start
                end = phrase_tokens[-1].end
                if not tracker.is_free(start, end):
                    continue
                phrase = (
                    " ".join(t.text for t in phrase_tokens) if window_size > 1 else tokens[j].text
                )
                if phrase in time_block_words:
                    block = time_block_words[phrase]
                    if phrase in _meal_words:
                        if _meal_fallback is None:
                            _meal_fallback = block
                    else:
                        # Explicit time word — use it and reserve span
                        due_time_block = block
                        tracker.reserve(
                            EntitySpan(
                                start,
                                end,
                                EntityKind.TIME_BLOCK,
                                block.replace("_", " ").title(),
                            )
                        )
                        break
            if due_time_block is not None:
                break
        # Fall back to meal-derived block if no explicit time word found
        if due_time_block is None and _meal_fallback is not None:
            due_time_block = _meal_fallback

    # --- Time ranges (between X and Y, from X to Y, X-Y) ---
    _range_closers_between = {"and"}
    _range_closers_from = {"to", "through", "till", "until"}
    _ampm_tokens = {"am", "pm", "a.m.", "p.m.", "a", "p"}
    number_words = intents["number_words"]

    def _range_hour(idx: int) -> tuple[int | None, int | None, int]:
        """Parse a simple time value for a range endpoint. No AM/PM application.

        Returns (hour, minute, last_consumed_idx) or (None, None, idx - 1).
        """
        if idx >= len(tokens):
            return None, None, idx - 1
        t = tokens[idx]
        # "now" — dynamic current time, already 24-hour
        if t.text == "now":
            _now = _datetime.now()
            return _now.hour, _now.minute, idx
        h: int | None = None
        if t.text.isdigit():
            h = int(t.text)
        else:
            h = number_words.get(t.text)
        # Colon form: "3:30", "10:15"
        if h is None and ":" in t.text:
            parts = t.text.split(":")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                hh, mm = int(parts[0]), int(parts[1])
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    return hh, mm, idx
            return None, None, idx - 1
        if h is None or not (1 <= h <= 12):
            return None, None, idx - 1
        # Check for minute word after hour — don't consume connectors or am/pm
        _no_consume = _range_closers_between | _range_closers_from | _ampm_tokens
        if idx + 1 < len(tokens) and tokens[idx + 1].text not in _no_consume:
            mv = _token_to_number(tokens[idx + 1].text)
            if mv is not None and 0 <= mv <= 59:
                return h, mv, idx + 1
        return h, 0, idx

    def _check_ampm_at(idx: int) -> tuple[str | None, int]:
        """Check for am/pm at token index. Returns (ampm, last_consumed_idx)."""
        if idx >= len(tokens):
            return None, idx - 1
        t = tokens[idx].text
        if t in ("am", "a.m."):
            return "am", idx
        if t in ("pm", "p.m."):
            return "pm", idx
        if t == "a" and idx + 1 < len(tokens) and tokens[idx + 1].text == "m":
            return "am", idx + 1
        if t == "p" and idx + 1 < len(tokens) and tokens[idx + 1].text == "m":
            return "pm", idx + 1
        return None, idx - 1

    def _apply_range_ampm(hour: int, ampm: str | None) -> int:
        """Apply AM/PM to a raw hour, falling back to skipped time-of-day context."""
        effective = ampm
        if effective is None and _skipped_tod_context is not None:
            if _skipped_tod_context in ("morning", "dawn", "sunrise"):
                effective = "am"
            elif _skipped_tod_context in ("evening", "night", "tonight", "dusk", "sunset"):
                effective = "pm"
        if effective == "pm" and hour < 12:
            return hour + 12
        if effective == "am" and hour == 12:
            return 0
        if effective == "am":
            return hour
        # No context — assume PM for ambiguous small numbers
        if ampm is None and effective is None and 1 <= hour <= 6:
            return hour + 12
        return hour

    def _adjust_range_pair(sh: int, eh: int, ampm: str | None) -> tuple[int, int]:
        """Apply AM/PM to both hours, correcting for noon-crossing ranges."""
        sh_adj = _apply_range_ampm(sh, ampm)
        eh_adj = _apply_range_ampm(eh, ampm)
        # "from 10 to 2 pm" — 10 PM > 2 PM, so start must be AM
        if sh_adj > eh_adj and ampm is not None:
            if ampm == "pm" and sh_adj >= 12:
                sh_adj -= 12
            elif ampm == "am" and sh_adj < 12:
                sh_adj += 12
        return sh_adj, eh_adj

    def _set_time_range(t_start: time, t_end: time, span_start: int, span_end: int) -> None:
        nonlocal due_time, due_time_end
        if tracker.is_free(span_start, span_end):
            tracker.unreserve_kind(EntityKind.TIME)
            due_time = t_start
            due_time_end = t_end
            d_s = t_start.strftime("%I:%M %p").lstrip("0")
            d_e = t_end.strftime("%I:%M %p").lstrip("0")
            tracker.reserve(EntitySpan(span_start, span_end, EntityKind.TIME, f"{d_s}\u2013{d_e}"))

    for j, tok in enumerate(tokens):
        if due_time_end is not None:
            break  # Already found a range
        if not tracker.is_free(tok.start, tok.end):
            continue

        # Opener patterns: "between X and Y [am/pm]", "from X to/through/till Y [am/pm]"
        if tok.text in ("between", "from"):
            closers = _range_closers_between if tok.text == "between" else _range_closers_from
            sh, sm, se = _range_hour(j + 1)
            if sh is None:
                continue
            ci = se + 1
            if ci >= len(tokens) or tokens[ci].text not in closers:
                continue
            eh, em, ee = _range_hour(ci + 1)
            if eh is None:
                continue
            ampm, ampm_end = _check_ampm_at(ee + 1)
            span_end_pos = tokens[ampm_end].end if ampm else tokens[ee].end
            sh_adj, eh_adj = _adjust_range_pair(sh, eh, ampm)
            _set_time_range(time(sh_adj, sm), time(eh_adj, em), tok.start, span_end_pos)
            continue

        # Dash pattern: "2-4" [am/pm]
        if "-" in tok.text and not tok.text.startswith("-") and not tok.text.endswith("-"):
            parts = tok.text.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                sh, eh = int(parts[0]), int(parts[1])
                if 1 <= sh <= 12 and 1 <= eh <= 12:
                    ampm, ampm_end = _check_ampm_at(j + 1)
                    span_end_pos = tokens[ampm_end].end if ampm else tok.end
                    sh_adj, eh_adj = _adjust_range_pair(sh, eh, ampm)
                    _set_time_range(time(sh_adj, 0), time(eh_adj, 0), tok.start, span_end_pos)
                    continue

        # Bare connector: "3 to 5", "six till eight pm"
        sh, sm, se = _range_hour(j)
        if sh is not None and se + 1 < len(tokens):
            ci = se + 1
            if tokens[ci].text in _range_closers_from:
                eh, em, ee = _range_hour(ci + 1)
                if eh is not None:
                    ampm, ampm_end = _check_ampm_at(ee + 1)
                    span_end_pos = tokens[ampm_end].end if ampm else tokens[ee].end
                    sh_adj, eh_adj = _adjust_range_pair(sh, eh, ampm)
                    _set_time_range(time(sh_adj, sm), time(eh_adj, em), tok.start, span_end_pos)
                    continue

    # --- "now" / "right now" (after ranges so "from now to X" works) ---
    if due_time is None and due_time_end is None:
        for j, tok in enumerate(tokens):
            if not tracker.is_free(tok.start, tok.end):
                continue
            if tok.text == "now":
                _now = _datetime.now()
                _set_time(time(_now.hour, _now.minute), tok.start, tok.end)
                if due_date is None:
                    due_date = today
                break
            if (
                tok.text == "right"
                and j + 1 < len(tokens)
                and tokens[j + 1].text == "now"
                and tracker.is_free(tokens[j + 1].start, tokens[j + 1].end)
            ):
                _now = _datetime.now()
                _set_time(time(_now.hour, _now.minute), tok.start, tokens[j + 1].end)
                if due_date is None:
                    due_date = today
                break

    # --- Explicit time patterns (at 3pm, by 5:00, after 10am, etc.) ---
    _time_prefixes = {"at", "by", "before", "after"} | intents["approximation_prefixes"]
    for j, tok in enumerate(tokens):
        if not tracker.is_free(tok.start, tok.end):
            continue

        # "at/by/before/around/about <time>" with prefix
        if tok.text in _time_prefixes and j + 1 < len(tokens):
            time_tok = tokens[j + 1]
            t = _parse_time_token(time_tok.text)
            if t is not None:
                _set_time(t, tok.start, time_tok.end)
                continue
            # "at 10 am" — three tokens with prefix
            if j + 2 < len(tokens) and time_tok.text.isdigit():
                combined = time_tok.text + tokens[j + 2].text
                t = _parse_time_token(combined)
                if t is not None:
                    _set_time(t, tok.start, tokens[j + 2].end)
                    continue
            # "at 5:30 pm" — three tokens with colon
            if j + 2 < len(tokens) and ":" in time_tok.text:
                combined = time_tok.text + tokens[j + 2].text
                t = _parse_time_token(combined)
                if t is not None:
                    _set_time(t, tok.start, tokens[j + 2].end)
                    continue
            # Spelled-out time: "at two thirty", "at half past three", "at eight"
            # Pass AM/PM context from a skipped time_of_day word ("morning" → am)
            _am_context = None
            if _skipped_tod_context in ("morning", "dawn", "sunrise"):
                _am_context = "am"
            elif _skipped_tod_context in ("evening", "night", "tonight", "dusk", "sunset"):
                _am_context = "pm"
            spoken_t, spoken_end = _parse_spoken_time(tokens, j + 1, ampm_hint=_am_context)
            if spoken_t is not None and tracker.is_free(tok.start, tokens[spoken_end].end):
                _set_time(spoken_t, tok.start, tokens[spoken_end].end)
                continue

        # Standalone spelled-out time without prefix: "six thirty pm", "nine a m"
        # Only match if the word is a number word in the 1-12 range
        if due_time is None:
            intents_num = _get_intents()["number_words"]
            if tok.text in intents_num and 1 <= intents_num[tok.text] <= 12:
                spoken_t, spoken_end = _parse_spoken_time(tokens, j)
                if spoken_t is not None and tracker.is_free(tok.start, tokens[spoken_end].end):
                    # Only claim if followed by am/pm or a minute word — avoid false positives
                    # on bare number words in the middle of reminder text
                    consumed_count = spoken_end - j + 1
                    if consumed_count >= 2:  # Must have consumed at least hour + something
                        _set_time(spoken_t, tok.start, tokens[spoken_end].end)
                        continue

        # Two-token time: "10 am", "3 pm", "5:30 pm" (no prefix)
        if j + 1 < len(tokens) and (tok.text.isdigit() or ":" in tok.text):
            next_tok = tokens[j + 1]
            if next_tok.text in ("am", "pm", "a.m.", "p.m."):
                suffix = "am" if "a" in next_tok.text else "pm"
                combined = tok.text + suffix
                t = _parse_time_token(combined)
                if t is not None and tracker.is_free(tok.start, next_tok.end):
                    _set_time(t, tok.start, next_tok.end)
                    continue

        # Bare single-token time: "3pm", "10:30am", "14:00"
        t = _parse_time_token(tok.text)
        if t is not None:
            _set_time(t, tok.start, tok.end)

    # --- Phase 4: dateparser fallback for anything we didn't catch ---
    if due_date is None and not skip_dateparser:
        try:
            from dateparser.search import search_dates

            settings = {
                "RELATIVE_BASE": _datetime(today.year, today.month, today.day),
                "PREFER_DATES_FROM": "future",
                "STRICT_PARSING": False,
            }
            results = search_dates(text, languages=["en"], settings=settings)
            if results:
                for matched_text, dt in results:
                    search_start = 0
                    while True:
                        pos = text.lower().find(matched_text.lower(), search_start)
                        if pos == -1:
                            break
                        end_pos = pos + len(matched_text)
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
                            has_date = dt.date() != today or matched_text.lower() in ("today",)
                            has_time = dt.hour != 0 or dt.minute != 0
                            if has_date:
                                tracker.unreserve_kind(EntityKind.DATE)
                                due_date = dt.date()
                                tracker.reserve(
                                    EntitySpan(
                                        prefix_start,
                                        end_pos,
                                        EntityKind.DATE,
                                        due_date.strftime("%b %d, %Y"),
                                    )
                                )
                            if has_time and due_time is None:
                                due_time = time(dt.hour, dt.minute)
                            break
                        search_start = pos + 1
        except Exception:
            logger.log.debug("dateparser search_dates failed", exc_info=True)

    return _DateTimeResult(due_date, due_time, due_time_end, due_time_block, event_date)


def _parse_spoken_time(
    tokens: list[_Token], start_idx: int, ampm_hint: str | None = None
) -> tuple[time | None, int]:
    """Parse spelled-out time from tokens starting at start_idx.

    Handles:
        "two thirty" → 14:30, "six thirty pm" → 18:30, "seven fifteen am" → 07:15,
        "half past three" → 15:30, "quarter to four" → 15:45, "quarter past twelve" → 12:15,
        "eleven oh five" → 11:05, "eight" → 08:00, "nine a m" → 09:00

    Args:
        ampm_hint: "am" or "pm" context from a skipped time_of_day word (e.g., "morning" → "am").

    Returns (time_or_None, last_token_index_consumed).
    last_token_index_consumed is start_idx - 1 if nothing matched.
    """
    n = len(tokens)
    if start_idx >= n:
        return None, start_idx - 1

    intents = _get_intents()
    number_words = intents["number_words"]

    def _word_num(idx: int) -> int | None:
        if idx >= n:
            return None
        t = tokens[idx].text
        if t.isdigit():
            return int(t)
        return number_words.get(t)

    def _is_am_pm(idx: int) -> str | None:
        if idx >= n:
            return None
        t = tokens[idx].text
        if t in ("am", "a.m.", "a"):
            # "a" alone only if followed by "m"
            if t == "a" and idx + 1 < n and tokens[idx + 1].text == "m":
                return "am"
            if t != "a":
                return "am"
        if t in ("pm", "p.m.", "p"):
            if t == "p" and idx + 1 < n and tokens[idx + 1].text == "m":
                return "pm"
            if t != "p":
                return "pm"
        return None

    def _am_pm_end(idx: int) -> int:
        """Return the token index AFTER consuming am/pm (handles 'a m' as two tokens)."""
        t = tokens[idx].text
        if t in ("a", "p") and idx + 1 < n and tokens[idx + 1].text == "m":
            return idx + 1
        return idx

    def _apply_ampm(hour: int, ampm: str | None) -> int:
        # Use explicit am/pm first, fall back to hint, then default heuristic
        effective = ampm or ampm_hint
        if effective == "pm" and hour < 12:
            return hour + 12
        if effective == "am" and hour == 12:
            return 0
        if effective == "am":
            return hour  # Morning context — keep as-is
        if ampm is None and ampm_hint is None and 1 <= hour <= 6:
            # No context at all — assume PM for ambiguous small numbers
            return hour + 12
        return hour

    i = start_idx

    # --- "half past X" ---
    if tokens[i].text == "half" and i + 2 < n and tokens[i + 1].text == "past":
        hour = _word_num(i + 2)
        if hour is not None and 1 <= hour <= 12:
            end = i + 2
            ampm = _is_am_pm(i + 3) if i + 3 < n else None
            if ampm:
                end = _am_pm_end(i + 3)
            return time(_apply_ampm(hour, ampm), 30), end

    # --- "quarter to/past X" ---
    if tokens[i].text == "quarter" and i + 2 < n:
        direction = tokens[i + 1].text
        hour = _word_num(i + 2)
        if hour is not None and 1 <= hour <= 12:
            end = i + 2
            ampm = _is_am_pm(i + 3) if i + 3 < n else None
            if ampm:
                end = _am_pm_end(i + 3)
            if direction == "past":
                return time(_apply_ampm(hour, ampm), 15), end
            if direction in ("to", "til", "till", "before"):
                h = _apply_ampm(hour, ampm)
                # "quarter to four" = 3:45
                h = h - 1 if h > 0 else 23
                return time(h, 45), end

    # --- Number-based: "two thirty", "six thirty pm", "eleven oh five", "eight" ---
    hour = _word_num(i)
    if hour is not None and 1 <= hour <= 12:
        end = i

        # Check for "a m" / "p m" BEFORE minute-word lookup
        # (prevents "a" being consumed as number_words["a"]=1)
        ampm_early = _is_am_pm(i + 1) if i + 1 < n else None
        if ampm_early is not None:
            end = _am_pm_end(i + 1)
            return time(_apply_ampm(hour, ampm_early), 0), end

        # Check for minute word(s): "two thirty", "seven fifteen", "three forty five"
        minute: int | float | None = None
        minute_end = i
        if i + 1 < n:
            minute, minute_end = _tokens_to_number(tokens, i + 1)
            # Reject if minute consumed token is an am/pm trigger
            if minute is not None and not (0 <= int(minute) <= 59):
                minute = None

        # "oh five" pattern — "eleven oh five"
        if minute is None and i + 2 < n and tokens[i + 1].text in ("oh", "o"):
            minute = _word_num(i + 2)
            if minute is not None and 0 <= minute <= 9:
                minute_end = i + 2
            else:
                minute = None

        if minute is not None and 0 <= int(minute) <= 59:
            end = minute_end
            # Check for am/pm after minute
            ampm = _is_am_pm(end + 1) if end + 1 < n else None
            if ampm:
                end = _am_pm_end(end + 1)
            return time(_apply_ampm(hour, ampm), int(minute)), end

        # Bare hour: "at eight" (am/pm already checked above)
        ampm = _is_am_pm(i + 1) if i + 1 < n else None
        if ampm:
            end = _am_pm_end(i + 1)
        return time(_apply_ampm(hour, ampm), 0), end

    return None, start_idx - 1


def _parse_time_token(text: str) -> time | None:
    """Parse a single token as a time value: 3pm, 10:30am, 14:00, 12am."""
    text = text.lower().rstrip(".")

    # HH:MM am/pm
    for suffix in ("am", "pm"):
        if text.endswith(suffix):
            core = text[: -len(suffix)]
            if ":" in core:
                parts = core.split(":")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    h, m = int(parts[0]), int(parts[1])
                    if suffix == "pm" and h != 12:
                        h += 12
                    elif suffix == "am" and h == 12:
                        h = 0
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        return time(h, m)
            elif core.isdigit():
                h = int(core)
                if suffix == "pm" and h != 12:
                    h += 12
                elif suffix == "am" and h == 12:
                    h = 0
                if 0 <= h <= 23:
                    return time(h, 0)

    # 24-hour HH:MM
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return time(h, m)

    return None


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
# Subtask extraction
# ---------------------------------------------------------------------------


def _extract_subtasks(reminder: str) -> tuple[str, list[str]]:
    """Extract inline subtask items from delimiter patterns in reminder text.

    Patterns: colon ("buy groceries: milk, bread, eggs"),
    "with tasks/subtasks", "including".

    Returns (parent_reminder, subtask_reminders). If no delimiter found,
    returns (reminder, []).
    """
    _delimiters = [": ", " with tasks ", " with subtasks ", " including "]

    lower = reminder.lower()
    for delim in _delimiters:
        idx = lower.find(delim)
        if idx == -1:
            continue
        parent = reminder[:idx].strip()
        items_text = reminder[idx + len(delim) :].strip()
        if not parent or not items_text:
            continue
        items = _split_list_items(items_text)
        if items:
            return parent, items

    return reminder, []


def _split_list_items(text: str) -> list[str]:
    """Split comma/and-separated text into individual items.

    Handles: "a, b, c", "a, b, and c", "a and b", "a, b and c".
    """
    parts = [p.strip() for p in text.split(",")]
    result: list[str] = []
    for part in parts:
        if not part:
            continue
        # Strip leading "and " from Oxford comma segments ("a, b, and c")
        if part.lower().startswith("and "):
            part = part[4:].strip()
        if not part:
            continue
        # Split on " and " within each segment ("charger and passport")
        for sub in part.split(" and "):
            sub = sub.strip()
            if sub:
                result.append(sub)
    return result


# ---------------------------------------------------------------------------
# Condition extraction
# ---------------------------------------------------------------------------


def _extract_conditions(tokens: list[_Token], tracker: _SpanTracker) -> list[dict[str, str]]:
    """Extract conditional expressions from unclaimed tokens.

    Runs AFTER all other extraction so claimed spans define expression boundaries.
    """
    intents = _get_intents()
    cond_keywords: dict[str, str] = intents.get("conditional_keywords", {})
    conditions: list[dict[str, str]] = []

    # Sort by phrase length (longest first) to match "only if" before "if"
    sorted_phrases = sorted(cond_keywords.keys(), key=len, reverse=True)
    matched_starts: set[int] = set()

    for phrase in sorted_phrases:
        words = phrase.split()
        wlen = len(words)
        for j in range(len(tokens) - wlen + 1):
            if tokens[j].start in matched_starts:
                continue
            candidate = " ".join(tokens[j + k].text for k in range(wlen))
            if candidate != phrase:
                continue
            kw_start = tokens[j].start
            kw_end = tokens[j + wlen - 1].end
            if not tracker.is_free(kw_start, kw_end):
                continue

            cond_type = cond_keywords[phrase]

            # Expression: unclaimed tokens after keyword until next reserved span or end
            expr_parts: list[str] = []
            expr_end = kw_end
            for k in range(j + wlen, len(tokens)):
                if not tracker.is_free(tokens[k].start, tokens[k].end):
                    break
                expr_parts.append(tokens[k].original)
                expr_end = tokens[k].end

            expression = " ".join(expr_parts).strip()
            if expression:
                conditions.append({"type": cond_type, "expression": expression})
                # Reserve keyword + expression so neither leaks into reminder
                tracker.reserve(
                    EntitySpan(
                        kw_start,
                        expr_end,
                        EntityKind.CONDITION,
                        f"{cond_type}: {expression}",
                    )
                )
                matched_starts.add(kw_start)

    return conditions


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

    # 6. Work duration ("session length N minutes")
    work_duration = _extract_work_duration(tokens, tracker)

    # 7. Dates and times
    dt_result = _extract_dates_and_times(text, tokens, tracker, today)
    due_date = dt_result.due_date
    due_time = dt_result.due_time
    due_time_end = dt_result.due_time_end
    due_time_block = dt_result.due_time_block
    event_date = dt_result.event_date

    # Apply recurrence time hint (e.g., "every morning" → 9:00)
    if rec_time is not None and due_time is None:
        due_time = rec_time

    # Rule 4: Recurrence implies due date today
    if rec_type is not None and due_date is None:
        due_date = today

    # 8. Conditions (after all other extraction so span boundaries are settled)
    conditions = _extract_conditions(tokens, tracker)

    # Build reminder from unclaimed text
    reminder = _build_reminder(text, tracker.spans)

    # Append times_annotation if present (e.g. "3 times a day" -> "(3x/day)")
    if times_anno and reminder:
        reminder = f"{reminder} {times_anno}"
    elif times_anno:
        reminder = times_anno

    # 9. Subtask extraction from reminder text
    reminder, subtask_reminders = _extract_subtasks(reminder)

    return ParseResult(
        reminder=reminder,
        due_date=due_date,
        due_time=due_time,
        due_time_end=due_time_end,
        due_time_block=due_time_block,
        priority=priority,
        tags=tags,
        recurrence_type=rec_type,
        recurrence_interval=rec_interval,
        recurrence_end_date=rec_end_date,
        recurrence_end_count=rec_end_count,
        pomodoro_estimate=pomodoro,
        estimated_minutes=estimated_minutes,
        work_duration=work_duration,
        event_date=event_date,
        conditions=conditions,
        subtask_reminders=subtask_reminders,
        spans=tracker.spans,
    )


# ---------------------------------------------------------------------------
# Span-aware text mutation helper for quick-action UI
# ---------------------------------------------------------------------------


def replace_or_append_category(
    text: str,
    spans: list[EntitySpan],
    kind: EntityKind,
    replacement: str,
    *,
    append_only: bool = False,
) -> str:
    """Replace the first span of ``kind`` with ``replacement``, or
    append ``replacement`` (with a leading space) if no such span
    exists in ``text``.

    Used by the smart-add quick-action UI in AddTodoDialog: when the
    user clicks a preset like "Priority: High", the existing priority
    span in the input (e.g. ``"low priority"``) is replaced in place
    with ``"high priority"``, preserving the surrounding reminder
    text. If no priority span exists yet, the replacement is
    appended.

    ``append_only=True`` bypasses the replace step and always appends.
    Tags use this mode because a single task can have multiple tags —
    picking a tag preset must never remove an existing one.

    This function is pure: it does not mutate ``spans`` or touch any
    parser state. The caller is responsible for re-parsing the new
    text (the smart input's debounced re-parse handles that when the
    text field is updated via ``set_text``).
    """
    if not append_only:
        target = next((s for s in spans if s.kind is kind), None)
        if target is not None:
            before = text[: target.start].rstrip()
            after = text[target.end :].lstrip()
            parts = [p for p in (before, replacement, after) if p]
            return " ".join(parts)
    sep = " " if text and not text.endswith(" ") else ""
    return text + sep + replacement
