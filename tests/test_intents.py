"""Tests for pytodo_qt.core.intents — YAML intent dictionary loader.

Pure Python tests — no Qt dependency required.
"""

from __future__ import annotations

from datetime import time

import pytest

from pytodo_qt.core.intents import clear_cache, get_intents, load_intents, set_language


@pytest.fixture(autouse=True)
def _clean_cache():
    """Ensure each test starts with a fresh cache."""
    clear_cache()
    yield
    clear_cache()
    set_language("en")


# ---------------------------------------------------------------------------
# Loading and schema
# ---------------------------------------------------------------------------


class TestLoading:
    def test_load_english(self) -> None:
        d = load_intents("en")
        assert d is not None
        assert len(d) > 0

    def test_schema_version(self) -> None:
        d = load_intents("en")
        # Version is validated during load — if we get here, it passed
        assert d  # non-empty

    def test_missing_language_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_intents("xx_nonexistent")

    def test_all_required_keys(self) -> None:
        d = load_intents("en")
        required = {
            "priority_tokens",
            "priority_phrases",
            "recurrence_tokens",
            "recurrence_every",
            "recurrence_time_hints",
            "pomodoro_units",
            "time_estimate_units",
            "time_of_day",
            "time_of_day_phrases",
            "tag_voice_prefixes",
            "number_words",
            "couple_few",
            "date_prefixes",
            "approximation_prefixes",
            "duration_end_phrases",
            "fuzzy_threshold",
            "unit_map",
            "unit_multiplier",
            "date_abbreviations",
            "priority_display",
        }
        assert required <= set(d.keys())


# ---------------------------------------------------------------------------
# Type correctness
# ---------------------------------------------------------------------------


class TestTypes:
    def test_priority_tokens_are_int(self) -> None:
        d = load_intents("en")
        for word, level in d["priority_tokens"].items():
            assert isinstance(level, int), f"{word} level is {type(level)}"

    def test_priority_phrases_are_int(self) -> None:
        d = load_intents("en")
        for phrase, level in d["priority_phrases"].items():
            assert isinstance(level, int), f"{phrase} level is {type(level)}"

    def test_recurrence_tokens_are_tuples(self) -> None:
        d = load_intents("en")
        for word, val in d["recurrence_tokens"].items():
            assert isinstance(val, tuple), f"{word} is {type(val)}"
            assert len(val) == 2
            assert isinstance(val[0], str)
            assert isinstance(val[1], int)

    def test_recurrence_every_tuples_or_none(self) -> None:
        d = load_intents("en")
        for word, val in d["recurrence_every"].items():
            assert val is None or isinstance(val, tuple), f"{word} is {type(val)}"

    def test_time_of_day_are_time_objects(self) -> None:
        d = load_intents("en")
        for word, val in d["time_of_day"].items():
            assert isinstance(val, time), f"{word} is {type(val)}"

    def test_time_of_day_phrases_are_time_objects(self) -> None:
        d = load_intents("en")
        for phrase, val in d["time_of_day_phrases"].items():
            assert isinstance(val, time), f"{phrase} is {type(val)}"

    def test_recurrence_time_hints_are_time_objects(self) -> None:
        d = load_intents("en")
        for word, val in d["recurrence_time_hints"].items():
            assert isinstance(val, time), f"{word} is {type(val)}"

    def test_sets_are_sets(self) -> None:
        d = load_intents("en")
        assert isinstance(d["pomodoro_units"], set)
        assert isinstance(d["date_prefixes"], set)
        assert isinstance(d["approximation_prefixes"], set)
        assert isinstance(d["duration_end_phrases"], set)

    def test_tag_voice_prefixes_is_list(self) -> None:
        d = load_intents("en")
        assert isinstance(d["tag_voice_prefixes"], list)

    def test_priority_display_int_keys(self) -> None:
        d = load_intents("en")
        for k in d["priority_display"]:
            assert isinstance(k, int), f"priority_display key {k} is {type(k)}"

    def test_fuzzy_threshold_is_int(self) -> None:
        d = load_intents("en")
        assert isinstance(d["fuzzy_threshold"], int)


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestCaching:
    def test_cache_hit(self) -> None:
        d1 = get_intents("en")
        d2 = get_intents("en")
        assert d1 is d2

    def test_clear_cache_forces_reload(self) -> None:
        d1 = get_intents("en")
        clear_cache()
        d2 = get_intents("en")
        assert d1 is not d2
        assert d1 == d2

    def test_get_intents_default_lang(self) -> None:
        d = get_intents()
        assert d["priority_tokens"]["urgent"] == 1

    def test_set_language(self) -> None:
        set_language("en")
        d = get_intents()
        assert d is not None


# ---------------------------------------------------------------------------
# Synonym expansion
# ---------------------------------------------------------------------------


class TestSynonymExpansion:
    def test_priority_synonyms_expanded(self) -> None:
        d = load_intents("en")
        # "important" has synonyms [vital, crucial, critical, essential, pressing]
        assert d["priority_tokens"]["vital"] == 1
        assert d["priority_tokens"]["crucial"] == 1
        assert d["priority_tokens"]["critical"] == 1
        assert d["priority_tokens"]["essential"] == 1
        assert d["priority_tokens"]["pressing"] == 1

    def test_recurrence_synonyms_expanded(self) -> None:
        d = load_intents("en")
        # "daily" has synonym [everyday]
        assert d["recurrence_tokens"]["everyday"] == ("daily", 1)
        # "yearly" has synonym [annually]
        assert d["recurrence_tokens"]["annually"] == ("yearly", 1)
        # "biweekly" has synonym [fortnightly]
        assert d["recurrence_tokens"]["fortnightly"] == ("weekly", 2)

    def test_canonical_and_synonym_same_value(self) -> None:
        d = load_intents("en")
        assert d["priority_tokens"]["important"] == d["priority_tokens"]["vital"]
        assert d["recurrence_tokens"]["daily"] == d["recurrence_tokens"]["everyday"]


# ---------------------------------------------------------------------------
# Round-trip equivalence with hardcoded dict
# ---------------------------------------------------------------------------


class TestParserUsesYAML:
    def test_parser_uses_yaml_dict(self) -> None:
        """Confirm the parser's _get_intents() returns the YAML-cached dict."""
        from pytodo_qt.core.nlp_parser import _get_intents

        parser_intents = _get_intents()
        cached_intents = get_intents("en")
        assert parser_intents is cached_intents

    def test_parser_reflects_loaded_data(self) -> None:
        """Parse result uses vocabulary from the YAML dictionary."""
        from pytodo_qt.core.nlp_parser import parse

        r = parse("task urgent", today=None)
        assert r.priority == 1  # "urgent" comes from YAML priority_tokens


# ---------------------------------------------------------------------------
# Specific value checks
# ---------------------------------------------------------------------------


class TestValues:
    def test_time_values(self) -> None:
        d = load_intents("en")
        assert d["time_of_day"]["noon"] == time(12, 0)
        assert d["time_of_day"]["midnight"] == time(0, 0)
        assert d["time_of_day"]["morning"] == time(9, 0)
        assert d["time_of_day"]["eod"] == time(17, 0)

    def test_recurrence_values(self) -> None:
        d = load_intents("en")
        assert d["recurrence_tokens"]["daily"] == ("daily", 1)
        assert d["recurrence_tokens"]["hourly"] == ("minutely", 60)
        assert d["recurrence_tokens"]["biweekly"] == ("weekly", 2)
        assert d["recurrence_every"]["other"] is None

    def test_unit_map(self) -> None:
        d = load_intents("en")
        assert d["unit_map"]["day"] == "daily"
        assert d["unit_map"]["hours"] == "minutely"

    def test_unit_multiplier(self) -> None:
        d = load_intents("en")
        assert d["unit_multiplier"]["hour"] == 60
        assert d["unit_multiplier"]["minute"] == 1

    def test_date_abbreviations(self) -> None:
        d = load_intents("en")
        assert d["date_abbreviations"]["tmrw"] == "tomorrow"
        assert d["date_abbreviations"]["2day"] == "today"

    def test_priority_display(self) -> None:
        d = load_intents("en")
        assert d["priority_display"][1] == "High"
        assert d["priority_display"][2] == "Normal"
        assert d["priority_display"][3] == "Low"
