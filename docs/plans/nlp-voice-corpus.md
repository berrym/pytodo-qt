# NLP Voice Dictation Design — Intent Corpus & Parsing Rules

**Status:** Approved — ready for audit phase
**Scope:** English language, voice dictation input patterns
**Parser target:** `core/nlp_parser.py` with `core/intents/en.yaml` intent dictionary

This document defines the voice-dictation inputs that the NLP parser must handle correctly, the semantic rules governing interpretation, and the design principles for disambiguation. The corpus entries serve as both specification and regression test source — each entry becomes a parametrized test case during the audit phase.

Voice inputs exhibit characteristics distinct from typed input: random capitalization, spoken punctuation rendered literally, filler words, spelled-out numbers, and homophones from speech-to-text errors. The parser must handle all of these gracefully.

---

# Part 1: Semantic Rules

## 1.1 Date Resolution

- **Bare day name** ("Friday", "by Friday", "on Friday") → the **upcoming occurrence** of that day. If today IS that day, resolves to 7 days out (next occurrence, not today).
- **"next" + day name** ("next Friday") → the occurrence in the **following week** (upcoming + 7 days). "Next" is a week-shift operator, not a synonym for "upcoming."
- Applies uniformly to all day names.
- Reference: `docs/plans/natural-language-input.md:111`

## 1.2 Time Representation (Schema v18)

Three fields handle time specification on a task:

| Field | Type | Purpose |
|---|---|---|
| `due_time` | HH:MM, nullable | Specific time OR start of an ad-hoc range |
| `due_time_end` | HH:MM, nullable | End of an ad-hoc range; null indicates a point time |
| `due_time_block` | enum, nullable | Canonical named time block |

**Resolution priority:**
1. `due_time_block` set → named block; range derived from configuration at display time
2. `due_time` + `due_time_end` set → explicit ad-hoc range
3. `due_time` only → specific point time
4. All null → date-only

**Explicit times override blocks.** "Monday morning at six" → `due_time=06:00` (specific wins, block cleared).
**Explicit ranges override blocks.** "Morning between 9 and 11" → `due_time=09:00, due_time_end=11:00`.

### Canonical Time Blocks

Four user-configurable canonical ranges with derived subdivisions:

| Block | Default Range | Notes |
|---|---|---|
| `morning` | 06:00–12:00 | Configurable in Settings |
| `afternoon` | 12:00–17:00 | Configurable in Settings |
| `evening` | 17:00–21:00 | Configurable in Settings |
| `night` | 21:00–06:00 | Crosses midnight; configurable |
| `early_X` / `late_X` | First/second half of parent range | Derived automatically |
| `noon` | 11:30–12:30 | Fixed narrow band |
| `midnight` | 23:30–00:30 | Fixed narrow band |

**"Noon" as a specific time:** When a task specifies "at noon", this resolves to `due_time=12:00` (a specific point), not a time block. Noon is explicit enough to be treated as a point.

### Ad-Hoc Time Ranges

All of the following connector forms produce equivalent range parses:
- `between X and Y` · `from X to Y` · `X to Y` · `X-Y` · `X through Y` · `X till Y` · `X until Y`
- Optional prefixes: `between`, `from`, `any time`, `sometime`, `anywhere`
- Bare `X and Y` without a range-signaling prefix is NOT interpreted as a range.

## 1.3 Event Date (Schema v18)

The `event_date` field captures the **target period** for scheduling-type tasks, distinct from `due_date` (the deadline to act).

- "Schedule dentist **for next month**" → `event_date=next month`, `due_date=end of current month`
- The word "for" after a scheduling verb ("schedule", "book", "arrange", "plan", "set up") signals a target period, not a recurrence duration.
- This disambiguates from the existing recurrence pattern where "for" is a duration trigger: "walk daily **for two weeks**" → recurrence duration.

## 1.4 Qualifier-Word Disambiguation

Qualifier words between a preposition and a noun/number serve as primary intent-disambiguation signals. Two qualifier categories:

**Articles** ("the", "a", "an"):
- Qualifier + recognized entity type → extract with that interpretation: `"in the morning"` → time_block=morning
- Qualifier + arbitrary noun → descriptive phrase, stays in reminder: `"at the store"` → reminder text

**Approximation markers** ("about", "around", "roughly", "approximately"):
- Signal approximate quantity: `"at about five"` → approximate time ~17:00

**Unqualified prepositions** (no qualifier word):
- Numeric context → likely extraction: `"at five"` → probable time
- Non-numeric context → conservative (keep in reminder): `"at work"` → reminder text
- Genuinely ambiguous → triggers Did You Mean? UI

## 1.5 Tag Signals

Tags require explicit markers. No tag inference from bare preposition phrases.

| Signal | Example | Result |
|---|---|---|
| `@X` | `email boss @work` | tag=@work |
| `#X` | `fix bug #urgent` | tag=@urgent |
| `tag X` | `email boss tag work` | tag=@work |
| `hashtag X` | `call client hashtag sales` | tag=@sales |

"At work", "at store", "in office" — bare prepositions without explicit tag markers always remain as reminder text.

## 1.6 "For" Disambiguation

The word "for" has three distinct meanings depending on context:

| Context | Example | Interpretation |
|---|---|---|
| After scheduling verb | `schedule dentist for next month` | Target period → event_date |
| After recurrence indicator | `walk daily for two weeks` | Duration → recurrence end |
| Before non-temporal noun | `buy gift for mom` | Literal → stays in reminder |

Scheduling verbs recognized: "schedule", "book", "arrange", "plan", "set up", "make appointment", "reserve."

## 1.7 Ambiguity Resolution — Did You Mean? UI

When parse confidence is low or multiple plausible interpretations exist, the parser returns ranked alternatives alongside the primary parse. The UI displays these as selectable options below the input chip display.

**Triggers:**
- Unqualified prepositions with weak context signals
- Low-confidence fuzzy matches
- Multiple intent matches on the same token
- Ambiguous date/time phrases

**Suppressed when:**
- Parse confidence is uniformly high
- Interpretation has been explicitly accepted (locked for session)
- Input is pure reminder text with no extractable entities

**Data model:** `ParseResult.alternatives: list[ParseResult]` — no schema change; parser-layer only.

## 1.8 Conditional & Constraint Expressions

The parser recognizes conditional keywords and stores them as structured metadata. Recognition is immediate; execution (calendar queries, priority-aware rescheduling) matures incrementally.

| Category | Keywords | Interpretation |
|---|---|---|
| Deadline constraint | "before", "by", "no later than", "prior to" | Hard deadline on the action |
| Temporal window | "while", "as long as", "during" | Availability/timing constraint |
| Conditional trigger | "if", "only if", "when", "provided" | Condition that must hold |
| Negative conditional | "unless", "except if", "not if" | Condition that must NOT hold |
| Fallback | "otherwise", "if not", "else", "or else", "failing that" | Alternative action if condition fails |
| Availability signal | "open", "available", "free", "has room" | Calendar query indicator |
| Rescheduling | "reschedule", "move", "bump", "push back", "shift" | Modification action |

**Data model extension:**
```
Condition:
    type: str           # "if", "unless", "while", "before", "fallback"
    expression: str     # raw condition text
```

`ParseResult.conditions: list[Condition]` — stored as structured JSON on the task item.

---

# Part 2: Voice Dictation Corpus

112 entries across 13 categories. Each entry specifies a realistic voice input and the expected parse result.

## A. Baseline Natural Captures (15)

Sanity checks — standard task capture patterns.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 1 | `buy milk` | reminder="buy milk" |
| 2 | `call mom tomorrow` | reminder="call mom", due_date=tomorrow |
| 3 | `finish report by friday` | reminder="finish report", due_date=upcoming Friday |
| 4 | `pay rent on the first` | reminder="pay rent", due_date=next 1st of month |
| 5 | `walk the dog at five pm` | reminder="walk the dog", due_time=17:00 |
| 6 | `high priority fix the bug` | reminder="fix the bug", priority=high |
| 7 | `add groceries to the list` | reminder="add groceries to the list" |
| 8 | `doctor appointment next tuesday` | reminder="doctor appointment", due_date=Tuesday of following week |
| 9 | `work out daily` | reminder="work out", recurrence=daily |
| 10 | `email boss at work` | reminder="email boss at work" (no explicit tag signal) |
| 11 | `submit taxes by april fifteenth` | reminder="submit taxes", due_date=Apr 15 |
| 12 | `review pull request today` | reminder="review pull request", due_date=today |
| 13 | `schedule dentist for next month` | reminder="schedule dentist", event_date=next month, due_date=end of current month ("for" after scheduling verb = target period) |
| 14 | `take out trash wednesday night` | reminder="take out trash", due_date=upcoming Wednesday, due_time_block=night |
| 15 | `team meeting thirty minutes` | reminder="team meeting", estimated_minutes=30 |

## B. Spelled-Out Times (10)

Speech-to-text renders times as words, not digits.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 16 | `call dentist at two thirty` | reminder="call dentist", due_time=14:30 |
| 17 | `meeting at half past three` | reminder="meeting", due_time=15:30 |
| 18 | `leave by quarter to four` | reminder="leave", due_time=15:45 |
| 19 | `lunch at quarter past twelve` | reminder="lunch", due_time=12:15 |
| 20 | `wake up at seven fifteen am` | reminder="wake up", due_time=07:15 |
| 21 | `flight at eleven oh five` | reminder="flight", due_time=11:05 |
| 22 | `pick up kids at three forty five` | reminder="pick up kids", due_time=15:45 |
| 23 | `breakfast at eight` | reminder="breakfast", due_time=08:00 |
| 24 | `standup at nine a m` | reminder="standup", due_time=09:00 |
| 25 | `dinner at six thirty pm` | reminder="dinner", due_time=18:30 |

## C. Compound Date+Time Phrases (8)

Date and time combined in natural speech.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 26 | `call mom tomorrow at three` | reminder="call mom", due_date=tomorrow, due_time=15:00 |
| 27 | `meeting next friday at ten thirty` | reminder="meeting", due_date=Friday of following week, due_time=10:30 |
| 28 | `dentist on the fifteenth at two pm` | reminder="dentist", due_date=15th, due_time=14:00 |
| 29 | `birthday party saturday evening` | reminder="birthday party", due_date=upcoming Saturday, due_time_block=evening |
| 30 | `early flight monday morning at six` | reminder="early flight", due_date=upcoming Monday, due_time=06:00 (specific overrides block) |
| 31 | `coffee tuesday at noon` | reminder="coffee", due_date=upcoming Tuesday, due_time=12:00 |
| 32 | `midnight deadline sunday` | reminder="deadline", due_date=upcoming Sunday, due_time_block=midnight |
| 33 | `first thing monday morning` | reminder="first thing", due_date=upcoming Monday, due_time_block=early_morning |

## D. Cross-Unit Durations (6)

Estimated time, work duration, and recurrence intervals expressed in compound units.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 34 | `workout one hour and thirty minutes` | reminder="workout", estimated_minutes=90 |
| 35 | `write report two and a half hours` | reminder="write report", estimated_minutes=150 |
| 36 | `check email every two hours` | reminder="check email", recurrence=every 2 hours |
| 37 | `standup fifteen minutes daily` | reminder="standup", estimated_minutes=15, recurrence=daily |
| 38 | `deep work ninety minutes` | reminder="deep work", estimated_minutes=90 |
| 39 | `stand up break every forty five minutes` | reminder="stand up break", recurrence=every 45 minutes |

## E. Filler Words & Spoken Punctuation (8)

Speech-to-text artifacts: fillers ("um", "uh", "like", "you know"), spoken punctuation ("comma", "period"), and preamble phrases ("so", "okay", "remind me to").

| # | Voice Input | Expected Extraction |
|---|---|---|
| 40 | `um remind me to buy milk tomorrow` | reminder="buy milk", due_date=tomorrow |
| 41 | `uh call mom like tomorrow at three` | reminder="call mom", due_date=tomorrow, due_time=15:00 |
| 42 | `you know pay the bills today` | reminder="pay the bills", due_date=today |
| 43 | `buy milk comma bread comma eggs` | reminder="buy milk, bread, eggs" |
| 44 | `finish project period high priority` | reminder="finish project", priority=high |
| 45 | `call mom period tomorrow at three` | reminder="call mom", due_date=tomorrow, due_time=15:00 |
| 46 | `so i need to finish the report by friday` | reminder="finish the report", due_date=upcoming Friday |
| 47 | `okay schedule dentist next week` | reminder="schedule dentist", due_date=next week |

## F. Capitalization Artifacts (4)

Speech-to-text engines (iOS especially) insert random mid-sentence capitalization.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 48 | `Call Mom Tomorrow At Three` | reminder="Call Mom", due_date=tomorrow, due_time=15:00 |
| 49 | `Buy Milk and Bread at The Store` | reminder="Buy Milk and Bread at The Store" |
| 50 | `High Priority Fix The Bug Today` | reminder="Fix The Bug", priority=high, due_date=today |
| 51 | `Email boss At Work tomorrow morning` | reminder="Email boss at work", due_date=tomorrow, due_time_block=morning |

## G. Run-On Inputs (6)

Multiple intents compressed into a single utterance with no natural breaks.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 52 | `remind me tomorrow at three to call mom high priority` | reminder="call mom", due_date=tomorrow, due_time=15:00, priority=high |
| 53 | `finish the report by friday high priority` | reminder="finish the report", due_date=upcoming Friday, priority=high |
| 54 | `daily standup nine am tag work` | reminder="daily standup", recurrence=daily, due_time=09:00, tags=["@work"] |
| 55 | `pick up groceries after work today at the store` | reminder="pick up groceries after work at the store", due_date=today |
| 56 | `review pr one hour estimate high priority` | reminder="review pr", estimated_minutes=60, priority=high |
| 57 | `workout thirty minutes every day at six am` | reminder="workout", estimated_minutes=30, recurrence=daily, due_time=06:00 |

## H. Homophones & STT Errors (6)

The hardest category — speech-to-text misrenders homophones. Context-dependent disambiguation; may require Did You Mean? UI for low-confidence cases.

| # | Voice Input | Expected Extraction | STT Error |
|---|---|---|---|
| 58 | `bye milk tomorrow` | reminder="buy milk", due_date=tomorrow | bye → buy |
| 59 | `pick up for people at the airport` | reminder="pick up four people at the airport" | for → four |
| 60 | `remind me two call mom` | reminder="call mom" | two → to |
| 61 | `add to the team meeting` | reminder="add to the team meeting" | "add 2" is universally understood texting idiom; no extraction |
| 62 | `right a thank you note` | reminder="write a thank you note" | right → write |
| 63 | `the weigh home` | reminder="the way home" | weigh → way |

## I. Approximations (4)

Qualifier words signal approximate values rather than exact matches.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 64 | `meeting about thirty minutes` | reminder="meeting", estimated_minutes≈30 |
| 65 | `call around three pm` | reminder="call", due_time≈15:00 |
| 66 | `workout roughly forty five minutes daily` | reminder="workout", estimated_minutes≈45, recurrence=daily |
| 67 | `deploy sometime next week` | reminder="deploy", due_date≈next week |

## J. Relative Time (5)

Offsets from the current moment, common in voice capture for near-term tasks.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 68 | `take medicine in one hour` | reminder="take medicine", due=now+1h |
| 69 | `call back in ten minutes` | reminder="call back", due=now+10min |
| 70 | `follow up in a couple days` | reminder="follow up", due_date=today+2 |
| 71 | `check on it in a few hours` | reminder="check on it", due=now+3h |
| 72 | `lunch in half an hour` | reminder="lunch", due=now+30min |

## K1. Ad-Hoc Time Ranges (14)

Explicit time windows specified with range connectors. All connector forms are equivalent.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 73a | `call between three and five pm` | reminder="call", due_time=15:00, due_time_end=17:00 |
| 73b | `meeting from 2 to 4 pm` | reminder="meeting", due_time=14:00, due_time_end=16:00 |
| 73c | `available between nine and noon` | reminder="available", due_time=09:00, due_time_end=12:00 |
| 73d | `drop off kids between seven and seven thirty` | reminder="drop off kids", due_time=07:00, due_time_end=07:30 |
| 73e | `give meds between nine and ten am` | reminder="give meds", due_time=09:00, due_time_end=10:00 |
| 73f | `anytime six to eight` | reminder (context-dependent), due_time=18:00, due_time_end=20:00 |
| 73g | `workout between four thirty and five thirty` | reminder="workout", due_time=16:30, due_time_end=17:30 |
| 73h | `tomorrow morning between nine and eleven` | due_date=tomorrow, due_time=09:00, due_time_end=11:00 (explicit range overrides block) |
| 73i | `call 3 to 5` | reminder="call", due_time=15:00, due_time_end=17:00 |
| 73j | `meeting 2-4 pm` | reminder="meeting", due_time=14:00, due_time_end=16:00 |
| 73k | `work session from nine through eleven` | reminder="work session", due_time=09:00, due_time_end=11:00 |
| 73l | `available sometime between two and four` | reminder="available", due_time=14:00, due_time_end=16:00 |
| 73m | `focus block six till eight pm` | reminder="focus block", due_time=18:00, due_time_end=20:00 |
| 73n | `reading from seven until nine` | reminder="reading", due_time=19:00, due_time_end=21:00 |

## K2. Time Blocks (12)

Named time windows resolved from user-configurable canonical ranges.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 73 | `dinner tonight` | reminder="dinner", due_date=today, due_time_block=evening |
| 74 | `breakfast tomorrow` | reminder="breakfast", due_date=tomorrow, due_time_block=morning |
| 75 | `lunch` | reminder="lunch", due_time_block=noon |
| 76 | `pick up kids after school` | reminder="pick up kids after school", due_time_block=afternoon |
| 77 | `dinner with parents friday night` | reminder="dinner with parents", due_date=upcoming Friday, due_time_block=night |
| 78 | `morning meeting` | reminder="meeting", due_time_block=morning |
| 79 | `call back this afternoon` | reminder="call back", due_date=today, due_time_block=afternoon |
| 80 | `presentation late morning on friday` | reminder="presentation", due_date=upcoming Friday, due_time_block=late_morning |
| 81 | `early evening walk` | reminder="walk", due_time_block=early_evening |
| 82 | `end of day report` | reminder="report", due_time_block=late_evening |
| 83 | `take meds first thing` | reminder="take meds", due_time_block=early_morning |
| 84 | `late afternoon snack daily` | reminder="snack", recurrence=daily, due_time_block=late_afternoon |

## L. Priority & Urgency (4)

Explicit priority markers and urgency vocabulary.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 85 | `urgent fix the login bug` | reminder="fix the login bug", priority=high |
| 86 | `asap call customer` | reminder="call customer", priority=high |
| 87 | `low priority clean up old files` | reminder="clean up old files", priority=low |
| 88 | `important email the investor` | reminder="email the investor", priority=high |

## M. Conditional & Constraint Expressions (10)

Conditions, deadlines, availability checks, and fallback logic stored as structured metadata. Recognition is immediate; execution matures incrementally via calendar queries and scheduling engine.

| # | Voice Input | Expected Extraction |
|---|---|---|
| 89 | `schedule dentist for next month before the twentieth` | reminder="schedule dentist", event_date=next month, condition: before the 20th → due_date=20th of current month |
| 90 | `book hotel if calendar is open next weekend` | reminder="book hotel", event_date=next weekend, condition: if calendar is open |
| 91 | `make dentist appointment while next month still has availability` | reminder="make dentist appointment", event_date=next month, condition: while availability exists |
| 92 | `if calendar does not have opening next month check the following month` | reminder="calendar opening for appointment", event_date=next month, condition: if no opening, fallback: check following month |
| 93 | `reschedule meeting if something more important comes up` | reminder="reschedule meeting", condition: if higher priority conflict |
| 94 | `dentist appointment next month otherwise the month after` | reminder="dentist appointment", event_date=next month, fallback: the month after |
| 95 | `call plumber before friday at the latest` | reminder="call plumber", due_date=upcoming Friday, condition: hard deadline (reinforced) |
| 96 | `finish taxes no later than april fourteenth` | reminder="finish taxes", due_date=April 14, condition: hard deadline |
| 97 | `if lower priority tasks can be rescheduled fit in dentist appointment early afternoon next week` | reminder="fit in dentist appointment", event_date=next week, due_time_block=early_afternoon, condition: if lower priority reschedulable |
| 98 | `only schedule meeting if both tuesday and thursday are free` | reminder="schedule meeting", condition: only if Tuesday and Thursday both free |

---

# Part 3: Audit Methodology

This corpus drives a three-phase audit of the current NLP parser:

**Phase 1 — Baseline.** Convert all 112 entries into a pytest-parametrized test file. Run against the current parser. Document pass/fail for each entry. This produces the gap map — the definitive list of what works and what doesn't.

**Phase 2 — Systematic fix.** Address failures in priority order:
1. Pre-processing (filler word stripping, punctuation normalization) — highest coverage per line of code
2. Intent dictionary expansion (`en.yaml` vocabulary additions) — spelled-out times, time blocks, approximation markers, scheduling verbs, conditional keywords
3. Tokenizer/parser logic — compound number parsing, range connectors, qualifier-word detection, "for" disambiguation
4. Schema v18 fields — `due_time_end`, `due_time_block`, `event_date`, `conditions`
5. Did You Mean? UI — alternative parse rendering for ambiguous inputs

**Phase 3 — Regression lock.** All 112 corpus entries become permanent regression tests. Future parser changes must not break any passing entry. New voice patterns discovered by testers are added to the corpus and become additional regression tests.

The corpus is a living document. As real-world tester feedback arrives, new entries are added and the audit cycle repeats.
