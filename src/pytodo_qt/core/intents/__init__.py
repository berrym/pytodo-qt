"""Intent dictionary loader for NLP parser.

Loads per-language YAML intent dictionaries and converts them to the runtime
types expected by the parser (tuples, time objects, sets).

Two separate i18n systems coexist:
- Qt tr() / .ts files for GUI strings
- These YAML intent dictionaries for NLP vocabulary
"""

from __future__ import annotations

import importlib.resources
from datetime import time
from io import StringIO
from typing import Any

from ruamel.yaml import YAML

_SCHEMA_VERSION = 1

_cache: dict[str, dict[str, Any]] = {}
_current_lang: str = "en"


def load_intents(lang: str = "en") -> dict[str, Any]:
    """Load and parse an intent YAML file, converting to runtime types.

    Uses importlib.resources to locate the YAML relative to this package,
    so it works with both source trees and installed packages.
    """
    assert __package__ is not None
    ref = importlib.resources.files(__package__).joinpath(f"{lang}.yaml")
    try:
        text = ref.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        msg = (
            f"NLP intent dictionary not found: {lang}.yaml is missing from "
            f"the {__package__} package. The parser cannot function without it. "
            f"In a frozen build, this means the build spec did not bundle "
            f"src/pytodo_qt/core/intents/*.yaml — verify collect_data_files "
            f"covers this package in the PyInstaller spec datas list."
        )
        raise RuntimeError(msg) from exc

    y = YAML()
    y.version = (1, 2)
    raw = y.load(StringIO(text))

    # Validate schema version
    version = raw.get("version")
    if version != _SCHEMA_VERSION:
        msg = f"Intent dictionary version {version} != expected {_SCHEMA_VERSION}"
        raise ValueError(msg)

    result: dict[str, Any] = {}

    # --- Priority ---
    pri = raw["priority"]
    result["priority_tokens"] = _expand_priority_tokens(pri["tokens"])
    result["priority_phrases"] = _expand_priority_phrases(pri["phrases"])

    # --- Recurrence ---
    rec = raw["recurrence"]
    result["recurrence_tokens"] = _expand_recurrence_tokens(rec["tokens"])
    result["recurrence_every"] = _build_recurrence_every(rec["every_map"])
    result["recurrence_time_hints"] = {k: _parse_time(v) for k, v in rec["time_hints"].items()}

    # --- Sets ---
    result["pomodoro_units"] = set(raw["pomodoro_units"])
    result["date_prefixes"] = set(raw["date_prefixes"])
    result["approximation_prefixes"] = set(raw["approximation_prefixes"])
    result["duration_end_phrases"] = set(raw["duration_end_phrases"])

    # --- Simple mappings ---
    result["time_estimate_units"] = dict(raw["time_estimate_units"])
    result["number_words"] = dict(raw["number_words"])
    result["couple_few"] = dict(raw["couple_few"])
    result["unit_map"] = dict(raw["unit_map"])
    result["unit_multiplier"] = dict(raw["unit_multiplier"])
    result["date_abbreviations"] = dict(raw["date_abbreviations"])

    # --- Priority display ---
    result["priority_display"] = {int(k): v for k, v in raw["priority_display"].items()}

    # --- Time of day ---
    result["time_of_day"] = {k: _parse_time(v) for k, v in raw["time_of_day"].items()}
    result["time_of_day_phrases"] = {
        k: _parse_time(v) for k, v in raw["time_of_day_phrases"].items()
    }

    # --- Lists ---
    result["tag_voice_prefixes"] = list(raw["tag_voice_prefixes"])

    # --- New vocabulary sections (Phase 1) ---
    result["ordinal_words"] = dict(raw.get("ordinal_words", {}))
    result["preamble_patterns"] = list(raw.get("preamble_patterns", []))
    result["scheduling_verbs"] = list(raw.get("scheduling_verbs", []))
    result["conditional_keywords"] = dict(raw.get("conditional_keywords", {}))
    result["constraint_keywords"] = list(raw.get("constraint_keywords", []))
    result["availability_words"] = list(raw.get("availability_words", []))
    result["time_block_words"] = dict(raw.get("time_block_words", {}))

    # --- Scalars ---
    result["fuzzy_threshold"] = int(raw["fuzzy_threshold"])

    # Cache and return
    _cache[lang] = result
    return result


def get_intents(lang: str | None = None) -> dict[str, Any]:
    """Return cached intent dictionary for the given or current language."""
    lang = lang or _current_lang
    if lang in _cache:
        return _cache[lang]
    return load_intents(lang)


def set_language(lang: str) -> None:
    """Set the current NLP language. Clears cache to force reload."""
    global _current_lang  # noqa: PLW0603
    _current_lang = lang
    _cache.pop(lang, None)


def clear_cache() -> None:
    """Clear all cached intent dictionaries. For testing."""
    _cache.clear()


# ---------------------------------------------------------------------------
# Internal conversion helpers
# ---------------------------------------------------------------------------


def _parse_time(val: str) -> time:
    """Convert 'HH:MM' string to datetime.time."""
    parts = str(val).split(":")
    return time(int(parts[0]), int(parts[1]))


def _expand_priority_tokens(tokens: dict[str, Any]) -> dict[str, int]:
    """Expand priority tokens with synonyms into a flat {word: level} dict."""
    result: dict[str, int] = {}
    for word, entry in tokens.items():
        level = entry["level"]
        result[word] = level
        for syn in entry.get("synonyms", []):
            result[syn] = level
    return result


def _expand_priority_phrases(phrases: dict[str, Any]) -> dict[str, int]:
    """Expand priority phrases into a flat {phrase: level} dict."""
    return {phrase: entry["level"] for phrase, entry in phrases.items()}


def _expand_recurrence_tokens(tokens: dict[str, Any]) -> dict[str, tuple[str, int]]:
    """Expand recurrence tokens with synonyms into a flat {word: (type, interval)} dict."""
    result: dict[str, tuple[str, int]] = {}
    for word, entry in tokens.items():
        val = (entry["type"], entry["interval"])
        result[word] = val
        for syn in entry.get("synonyms", []):
            result[syn] = val
    return result


def _build_recurrence_every(every_map: dict[str, Any]) -> dict[str, tuple[str, int] | None]:
    """Build the 'every <word>' map with tuples or None."""
    result: dict[str, tuple[str, int] | None] = {}
    for word, entry in every_map.items():
        if entry is None:
            result[word] = None
        else:
            result[word] = (entry["type"], entry["interval"])
    return result
