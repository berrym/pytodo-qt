# NLP Overhaul — Intent-Based Token Parser

## Status: IMPLEMENTED (2026-04-02)

## Decision Date: 2026-03-31

## Why This Exists

The regex-based NLP parser was replaced with an intent-based token parser that uses:
- **Tokenizer** with character span preservation
- **Intent dictionaries** (YAML 1.2, per-language) with synonym expansion
- **Fuzzy matching** via `rapidfuzz` with confidence scoring
- **dateparser** for all date/time parsing (200+ languages)

## Implementation Summary

### What Was Built
- Token-based parser: `core/nlp_parser.py` (~1100 lines, pure Python, no Qt dependency)
- External YAML dictionary: `core/intents/en.yaml` (~300 lines, 200+ entries)
- YAML loader: `core/intents/__init__.py` with caching, synonym expansion, `set_language()` API
- `ruamel.yaml` (MIT) for YAML 1.2 parsing (no sexagesimal time corruption, preserves comments)
- Uncertain match UI: EntityChip with inline matched term display, click-to-accept, ×-to-remove
- New EntityKind: ESTIMATE, WORK_DURATION; new ParseResult fields: estimated_minutes, work_duration
- EntitySpan gained: `confidence` (float 0-1), `matched` (dictionary term)
- Approximation synonyms: "approximately", "about", "around", "roughly" for estimates/pomodoro
- Duration recurrence: "over/for/until N days/weeks" with filler word scanning
- Number word parity: `_token_to_number` used everywhere (couple=2, few=3, several=5)
- Date abbreviations: tmrw, tom, tdy, yday, etc. (externalized to YAML)
- Qt `tr()` pass across all 22 GUI files for i18n readiness
- Preset recurrence pills removed from desktop and web UI

### Architecture Decisions
- Approximation prefixes ("about", "around") are quantity modifiers, NOT recurrence triggers
- "over", "for", "until" are the only recurrence duration triggers
- Extraction order: tags → priority → recurrence → pomodoro → estimated_minutes → work_duration → dates/times
- EntityChip is a QLabel subclass with mousePressEvent (same ClickableLabel pattern as todo_table)
- Stylesheet scoping: `QLabel { ... }` prevents tooltip cascade interference
- Two i18n systems coexist: Qt tr()/.ts for GUI, YAML intent dicts for NLP vocabulary

### YAML Schema
Per-entity `fuzzy_threshold` + `min_length`, synonym groups with canonical values, version field.
Time values stored as `HH:MM` strings (YAML 1.2 keeps them as strings, no quoting needed).

### Dependencies Added
- `dateparser>=1.2` (BSD-3) — date/time parsing in 200+ languages
- `rapidfuzz>=3.0` (MIT) — fuzzy string matching
- `ruamel-yaml>=0.18` (MIT) — YAML 1.2 for intent dictionaries

### Test Coverage
- 248 NLP parser tests (192 original + 56 new capability tests)
- 29 YAML loader tests
- 2613 total project tests passing

### Files
| File | Status |
|------|--------|
| `core/nlp_parser.py` | Complete rewrite, same public API |
| `core/intents/__init__.py` | NEW — YAML loader with caching |
| `core/intents/en.yaml` | NEW — English intent dictionary |
| `gui/widgets/smart_input.py` | EntityChip rewritten as QLabel subclass |
| `gui/dialogs/add_todo.py` | Preset pills removed, tr() wrapped |
| All 22 GUI files | tr() wrapped for i18n readiness |
| `tests/test_nlp_parser.py` | 248 tests |
| `tests/test_intents.py` | 29 tests |

## Future Evolution Path

1. **Done**: Token parser + fuzzy matching + dateparser + YAML dictionaries
2. **Next**: Add language dictionaries as translation volunteers contribute
3. **Future**: Optional local LLM integration (e.g., Llama) for ambiguous inputs
   - LLM proposes a parse → intent dictionary validates → confidence scoring resolves conflicts
   - The intent dictionary becomes the validation/fallback layer, not obsolete
