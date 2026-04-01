# NLP Overhaul — Intent-Based Token Parser

## Decision Date: 2026-03-31

## Why This Exists

The existing regex-based NLP parser (`core/nlp_parser.py`, ~1000 lines, 192 tests) works for English users typing exact patterns but is fundamentally limited:

- **Regex is fragile**: every new pattern risks breaking existing ones
- **Not internationalizable**: would need parallel regex sets per language
- **No fuzzy tolerance**: typos, abbreviations, voice dictation artifacts all fail
- **No intent understanding**: matches strings, not meaning
- **Not future-proof**: adding patterns = adding regex = exponential complexity

## Architecture Decision

**Replace all regex-based NLP with an intent-based token parser.**

Components:
1. **Tokenizer**: Split input on whitespace, preserve character spans
2. **Intent dictionaries**: Lookup tables keyed by language, mapping tokens/phrases to intents
3. **Fuzzy matching**: `rapidfuzz` library for Levenshtein-based matching against intent vocabulary
4. **dateparser**: Handles all date/time parsing in 200+ languages
5. **Confidence scoring**: Each match returns a confidence (0.0-1.0) for UI feedback

### What Changes

| Layer | Before | After |
|-------|--------|-------|
| Date/time parsing | 15+ regex patterns | `dateparser` library (200+ languages) |
| Priority extraction | 10+ regex patterns | Intent dictionary lookup + fuzzy match |
| Recurrence extraction | 8+ regex patterns | Token sequence matching + intent dictionary |
| Tag extraction | 1 regex | Token prefix check (`@`/`#`) — no regex needed |
| Pomodoro/stopwatch | 1 regex | Token prefix check (`~`) + fuzzy match for units |
| Typo handling | None | Fuzzy matching (Levenshtein, threshold ~80%) |
| Abbreviations | Hardcoded patterns | Abbreviation dictionary + fuzzy match |
| Voice dictation | 60 hardcoded patterns | Natural fuzzy matching against intent vocabulary |
| Internationalization | Not possible | Swap intent dictionary per language |

### What Stays the Same

- `ParseResult` dataclass (same fields, same API)
- `EntitySpan` and `EntityKind` (same span tracking for highlighting)
- `SmartInputWidget` and `SmartInputHighlighter` (same UI)
- Integration with `AddTodoDialog` (same signal/slot connections)
- Preview chips below smart input (same UX)
- All 192 existing tests become acceptance criteria for the new parser
- Pure Python, no Qt dependency in parser module

## Intent Dictionary Design

```python
INTENT_PRIORITY = {
    "en": {
        "tokens": {
            "p1": 1, "p2": 2, "p3": 3,
            "urgent": 1, "important": 1, "critical": 1,
            "high": 1, "normal": 2, "low": 3,
            "asap": 1,
        },
        "phrases": {
            "high priority": 1, "highest priority": 1,
            "top priority": 1, "really important": 1,
            "low priority": 3, "not urgent": 3,
        },
        "fuzzy_threshold": 80,
    },
    # Future: "es", "fr", "de", "ja", etc.
}
```

Adding a language = adding a dictionary. No code changes.
Adding a new way to say something = one line in a dictionary. No parser changes.

## Fuzzy Matching

`rapidfuzz` (~2MB, MIT license, GPL v3 compatible) provides:
- `fuzz.ratio()` — full string similarity
- `fuzz.partial_ratio()` — substring matching for phrases
- `fuzz.token_sort_ratio()` — order-independent word matching (good for voice dictation)
- `process.extractOne()` — find best match from a list of candidates

### Confidence Scoring

Every match returns `(result, confidence)`:
- Exact match: confidence = 1.0
- Fuzzy match at 95%+: confidence = 0.95 — treated as certain
- Fuzzy match at 80-95%: confidence = 0.80-0.95 — shown with "?" in preview chip
- Below 80%: no match — falls through to reminder text

The UI can use confidence to show uncertain matches differently, letting users confirm or reject.

## Parser Flow

```
Input: "Buy groceries tmrw at 3pm @errands really importnt ~3 sessions"

1. Normalize: lowercase, strip, collapse whitespace, unicode NFC
2. Tokenize: ["buy", "groceries", "tmrw", "at", "3pm", "@errands",
              "really", "importnt", "~3", "sessions"]
3. Extract tags: "@errands" → tags=["@errands"], remove from tokens
4. Extract estimates: "~3" + "sessions" → pomodoro_estimate=3, remove
5. Intent matching on remaining tokens:
   - "really importnt" → fuzzy matches "really important" at 92%
     → priority=1, confidence=0.92
6. Remaining: ["buy", "groceries", "tmrw", "at", "3pm"]
7. dateparser.parse("tmrw at 3pm") → date=tomorrow, time=15:00
8. Remainder: "buy groceries" → reminder
```

## Dependencies

```toml
"dateparser>=1.2",     # Date/time parsing, 200+ languages, MIT license
"rapidfuzz>=3.0",      # Fuzzy string matching, MIT license
```

Both MIT licensed — GPL v3 compatible, PySide6 compatible for future migration.

## Input Sanitization

Before parsing:
- Lowercase normalization
- Unicode NFC normalization (accented characters)
- Collapse multiple whitespace
- Strip common filler words per language (configurable): "um", "uh", "like", "please", "remind me to"
- Strip leading articles when followed by verb: "a", "the" (configurable per language)

## Voice Dictation Support

Voice dictation produces natural language without abbreviations but with:
- Filler words ("um", "uh", "like")
- Full phrases instead of shortcuts ("highest priority" instead of "p1")
- Misrecognized words (fuzzy matching handles these)
- No punctuation or inconsistent punctuation

The token-based parser with fuzzy matching handles all of these naturally. No special "voice mode" needed — the same parser works for typed and dictated input.

## Internationalization Strategy

### Phase 1 (current): English only
- Single intent dictionary for English
- `dateparser` handles dates in all languages automatically
- Qt `tr()` for UI strings (separate from NLP vocabulary)

### Phase 2 (future): Add languages
- Create intent dictionary files per language
- Language detection: `dateparser` can auto-detect, or user sets locale
- Same parser engine, different vocabulary
- Latin-alphabet languages first (Spanish, French, German, Portuguese, Italian)
- CJK languages later (different tokenization needed — word segmentation)

### Qt Integration
- `QObject.tr()` for all user-visible GUI strings
- `.ts` translation files via `lupdate`/`lrelease`
- Intent dictionaries are NOT Qt translation files — they're parser vocabulary
- Both systems coexist: Qt handles UI, intent dictionaries handle NLP

## Relationship to Existing Code

### Replaces
- `core/nlp_parser.py` — complete rewrite, same module name, same public API
- All regex patterns in the parser
- `_normalize_number_words()` — replaced by fuzzy matching + number word dictionary

### Preserves
- `ParseResult`, `EntitySpan`, `EntityKind` — same dataclasses, same API
- `parse(text, today=None) -> ParseResult` — same function signature
- `gui/widgets/smart_input.py` — same SmartInputWidget, same highlighter
- All 192 existing tests — same inputs, same expected outputs

### New Files
- `core/intents/` — directory for intent dictionary files (or single module)

## Future Evolution Path

1. **Now**: Token parser + fuzzy matching + dateparser (this overhaul)
2. **Later**: Add language dictionaries as translation volunteers contribute
3. **Future**: Optional local LLM integration (e.g., Llama) for ambiguous inputs
   - LLM proposes a parse → intent dictionary validates → confidence scoring resolves conflicts
   - The intent dictionary becomes the validation/fallback layer, not obsolete
