# pytodo-qt — Universal Planning Platform

**Status:** Active design principle
**Last updated:** 2026-04-07

## Identity

pytodo-qt is not a todo app. It is a universal planning and productivity platform for any human's concept of what they want to track, plan, build, or do. It handles the full spectrum from a grocery list to a multi-year life project.

## Scope Spectrum

| Scale | Examples |
|---|---|
| **Quick** | "buy milk", "call mom", "take out trash" |
| **Daily** | Tasks with due dates, time blocks, recurring chores |
| **Focused** | Pomodoro sessions, deep work blocks, stopwatch tracking |
| **Medical** | Medication schedules, titration tracking, treatment appointments |
| **Projects** | Multi-week undertakings with subtasks, milestones, blockers |
| **Software** | Development sprints, issue tracking, release milestones |
| **Life** | Multi-year goals, career plans, open-ended aspirations |

## Time Concepts

The system handles all human time concepts without bias toward any scale:

- **Now** — fundamental anchor, always present
- **Minutes/hours** — standard short-term (meetings, focus sessions)
- **Days/weeks** — medium-term (project phases, deadlines)
- **Months/years** — long-term (career goals, life plans, medical treatments)
- **Open-ended/forever** — items with no end ("maintain health", "keep learning")

Estimated duration displays at the natural scale: "~30 min", "~2 hours", "~3 weeks", "~6 months", "~2 years". Users are never forced to compute minutes manually.

## Natural Language

The NLP parser handles:

- **Single items** — "buy milk tomorrow"
- **Subtask creation** — "buy groceries: milk, bread, eggs" creates parent + subtasks
- **Multi-unit durations** — "two weeks", "four months", "a year" as estimates
- **Time windows** — "tomorrow morning", "between 3 and 5", "from now until evening"
- **Scheduling** — "schedule dentist for next month" (event_date vs due_date)
- **Conditions** — "if calendar is open", "before the 20th"
- **Any connector form** — "between X and Y", "from X to Y", "X through Y", "X till Y"

## Rich Annotation (Future)

Beyond the reminder string, items will support:

- **Notes/commentary** — free-form text for context, decisions, reasoning
- **Milestones** — progress markers within long-running items
- **Blockers/issues** — dependencies and obstacles
- **Labels beyond tags** — status indicators, priority dimensions
- **Memory/feedback** — structured learnings attached to items

## Internationalization

Non-negotiable foundation:

- Qt `tr()` / `.ts` files for GUI strings
- YAML intent dictionaries for NLP vocabulary
- Locale-aware time/date formatting
- Every new feature maintains i18n readiness

## Design Principles

1. **No arbitrary limits.** If a user can think it, the tool can hold it.
2. **Natural scale.** Display and accept input at whatever unit the user naturally uses.
3. **Structural awareness.** The parser understands relationships, not just flat strings.
4. **i18n always.** New strings get `tr()`. New NLP vocab goes in YAML.
5. **Simple by default, deep by choice.** A user who wants "buy milk" gets a clean experience. A user who needs project management gets full capability. Neither impedes the other.
