# Calendar Evolution Roadmap

The calendar surface grows into a first-class calendar application on par with
Google Calendar, Apple Calendar, Outlook, and Fantastical, without displacing
the productivity and pomodoro affordances already shipping. This document
synthesizes five parallel competitive-analysis rounds run on 2026-04-24 and an
audit of current-state wiring.

Not a locked specification. Phase ordering here is one option; sequencing gets
settled in planning rounds tied to each release milestone.

---

## 1. Current state

### Wired and working

- Temporal primitives on `TodoItem`: `due_date`, `due_time`, `due_time_end`,
  `due_time_block`, `event_date`, recurrence fields (`recurrence_type`,
  `_interval`, `_end_date`, `_end_count`, `_count`, `missed_recurrences`),
  `estimated_minutes`, `estimated_pomodoros`, `work_duration`, `time_spent`,
  `pomodoro_count`, `completed_at`, `board_column`. Schema at v19.
- Gantt-bar rendering with seven locked decisions: four origin rules (event /
  workback / deadline-from-created / all-day), eight lifecycle states
  (FUTURE / IN_WORK_WINDOW / DUE_NOW / OVERDUE_ACTIVE / COMPLETED_EARLY /
  ONTIME / LATE / UNKNOWN), cross-day clipping with edge markers, overdue
  growth cap with subsequent-day marker, top-anchored text, WCAG-AA palette,
  recurring cycle reset.
- Views: day, week, month, timeline analytics (Gantt / daily stacked /
  productivity heatmap / estimate accuracy).
- CalDAV / iCal interop: full VTODO round-trip (RFC 5545) and CalDAV HTTP
  endpoints (RFC 4791) for Thunderbird, DAVx5, Tasks.org sync. Implemented in
  `core/caldav.py` and `web/caldav_handler.py`.
- NLP parser: natural-language extraction of due dates, times, time blocks,
  recurrence, estimates. Intent-based via `dateparser + rapidfuzz + YAML
  intent dictionaries`.
- Web calendar parity: `/api/calendar/segments` endpoint, Canvas 2D week/day
  hour-grid, pinned all-day + marker rows, two-zone completion overlays,
  palette mirrored to CSS variables.
- Drag and drop: drop onto calendar cells, reverse-drop to unscheduled sidebar,
  drag out of the overflow popover.
- Subtask support (schema v11): parent/child items, detail-panel CRUD, kanban
  card expand. Subtasks do not render in calendar/unscheduled surfaces — they
  surface only through the detail panel (shipped 2026-04-24).

### Partially wired

- `due_time_end`: parsed by NLP, honored by the bar-window EVENT rule, but no
  interactive UI after item creation. Detail panel shows it read-only.
- `due_time_block`: add-dialog combo exists, detail panel shows the value, but
  no in-grid assignment UX.
- `event_date`: schema field, NLP-parseable, unused in calendar rendering.
  Semantics undefined.
- Drag-to-resize bar edges: drag-to-reschedule (change `due_date`) works; the
  resize-for-duration variant does not.
- Web calendar interactivity: REST API is complete, web UI is read-only.

### Missing

- Attendees / participants / RSVP tracking
- Location (address, Maps resolution)
- Meeting links (Zoom/Teams/Meet/Webex/Jitsi detection + Join button)
- Calendar categories beyond priority (named, color-coded, filterable)
- Multiple user-owned calendars / calendar sets / subscribed ICS feeds
- Shared calendars with granular permissions
- Scheduling-assistant grid across invitees
- Proposals (multi-time vote) and public booking links
- Travel time rendered as a time-blocking band
- Focus-mode integration (hide calendars during a focus session)
- Weather / sunrise-sunset overlays
- Busy/free visibility flag
- Recurring-instance editing (edit this vs. edit all vs. edit future)
- Schedule / agenda view (single scrollable list)
- Year heatmap view

---

## 2. Competitor feature inventory

Cross-app comparison, observed features. Checkmarks indicate native support;
parentheses indicate a notable variant or limitation.

| Feature area | Google | Apple | Outlook | Fantastical |
|---|---|---|---|---|
| **Views** | | | | |
| Day / Week / Month / Year | ✓ | ✓ | ✓ | ✓ |
| Schedule / agenda list | ✓ | ✓ (iOS) | ✓ | ✓ |
| Custom N-day | ✓ | — | — | ✓ (quarter) |
| Horizontal multi-attendee grid | — | — | ✓ | — |
| Heatmap year | (basic) | ✓ | — | — |
| DayTicker (horizontal multi-day strip) | — | — | — | ✓ |
| Board view (kanban + calendar hybrid) | — | — | ✓ (web new) | — |
| **Event primitives** | | | | |
| Title, location, notes | ✓ | ✓ | ✓ | ✓ |
| Map-autocomplete location | ✓ | ✓ | — | ✓ |
| Attendees + guest permissions | ✓ | ✓ | ✓ | ✓ |
| Attachments | ✓ | ✓ | ✓ | — |
| Per-event color | ✓ | — | ✓ (categories) | ✓ |
| Visibility (public/private) | ✓ | — | ✓ | ✓ |
| Busy/free flag | ✓ | ✓ | ✓ | ✓ |
| Meeting-link auto-detection | ✓ (Meet) | — | ✓ (Teams) | ✓ (~35 providers) |
| **Event types** | | | | |
| Regular / all-day / recurring | ✓ | ✓ | ✓ | ✓ |
| Out-of-office auto-decline | ✓ | — | ✓ | — |
| Focus time | ✓ | (via filters) | — | — |
| Task on calendar | ✓ | ✓ | ✓ | ✓ |
| Working hours / location | ✓ | — | ✓ | — |
| **Scheduling** | | | | |
| Find-a-time grid | ✓ | — | ✓ (best-in-class) | — |
| Suggested times auto-pick | ✓ | — | ✓ (traffic-light) | — |
| Room/resource booking | ✓ | — | ✓ (Room Finder) | — |
| Proposals (multi-time vote) | — | — | ✓ (Scheduling Poll) | ✓ (Openings) |
| Public booking link | ✓ (Appointments) | — | ✓ (Bookings) | ✓ (Openings) |
| **Multi-calendar** | | | | |
| Multiple user-owned | ✓ | ✓ | ✓ | ✓ |
| Subscribed ICS URL | ✓ | ✓ | ✓ | ✓ |
| Shared with permissions | ✓ (4-tier) | ✓ (2-tier) | ✓ (delegate) | (depends on source) |
| Calendar groups / sets | — | — | ✓ | ✓ (timed + location triggers) |
| Public calendar URL | ✓ | ✓ | ✓ | ✓ |
| Curated subscribable library | — | — | — | ✓ (Interesting) |
| **Entry & UX** | | | | |
| Natural-language quick create | ✓ (basic) | ✓ (basic) | — | ✓ (best) |
| Travel-time rendered | — | ✓ (hashed block) | — | ✓ |
| Weather overlay | — | — | — | ✓ |
| Focus-mode calendar filter | — | ✓ | — | ✓ |
| Conference-link detection | ✓ | — | ✓ | ✓ (~35 services) |
| Menu-bar glance view | — | — | — | ✓ |
| Widgets (OS integration) | (limited) | ✓ | (limited) | ✓ |
| Edge-drag-to-resize | ✓ | ✓ | ✓ | ✓ |
| Option-drag-to-duplicate | — | ✓ | — | ✓ |
| **Notifications** | | | | |
| Pop-up + email per-event | ✓ | ✓ | ✓ | ✓ |
| Time-to-Leave (live traffic) | — | ✓ | — | — |
| Second alert (get-ready) | — | ✓ | — | ✓ |

### Safe-bet features (≥3 of 4 competitors, cited as essential)

1. Attendees with RSVP tracking
2. Location with map resolution
3. Meeting-link detection with Join button
4. Multiple user-owned calendars + subscribed ICS feeds
5. Shared calendars with permission tiers
6. Recurring patterns with single-instance exceptions
7. Edge-drag to resize event duration
8. Calendar categories / colors beyond priority
9. Busy/free flag
10. Natural-language quick entry
11. Schedule / agenda view
12. Public booking link

### Selective-adoption differentiators

- **Apple**: travel time rendered as hashed block; second alert as first-class
  field; inspector-popover editing; option-drag duplication; year heatmap;
  Focus filter integration with on-screen "Filtered by Focus" banner.
- **Google**: four-tier sharing permissions; appointment schedules with
  buffers and lead-time limits; Gmail-auto-event extraction (structurally maps
  well onto the existing NLP parser); free/busy stacked availability grid.
- **Outlook**: Scheduling Assistant grid (attendees as rows, time as columns,
  live free/busy bands); Room Finder filtering by capacity/amenities;
  Suggested Times with traffic-light conflict scoring; Scheduling Poll for
  external voters with no account; calendar groups; schedule view.
- **Fantastical**: DayTicker as always-visible at-a-glance strip; parser
  quality (localized in 8+ languages, durations/alerts/invitees/calendar
  targeting); Openings (public booking); Calendar Sets with
  time-of-day/location triggers; conference-link detection across ~35
  services; first-class widgets; unified subscription across platforms.

### Universally-disliked pain points (do not repeat)

- New-client regressions that remove features from the old one (New Outlook
  is the case study).
- Two parallel tools for the same job (Outlook's Scheduling Assistant vs.
  Scheduling Poll).
- Feature disparity between desktop and mobile.
- Forced UI changes without an opt-out (Google mobile month-tap change).
- Time-zone edge cases in shared events.
- Rigid recurrence engines (Google 730-occurrence cap, Outlook series
  corruption under heavy exception editing, Apple parser dropping "every
  other week" phrases).
- Gating analytics / power features behind paid tiers that are not
  server-cost-justified.
- Burying sharing and delegation deep in settings (Apple).
- No menu-bar glance view on macOS (Apple).
- Conditional formatting stuck in legacy desktop only (Outlook).
- Sync settings that do not reliably propagate (Apple, Outlook mobile).

---

## 3. Gap analysis

Sizing buckets: **S** (under 1 day), **M** (1–3 days), **L** (1–2 weeks),
**XL** (multi-week / architectural), **XXL** (multi-month, requires
supporting infrastructure).

### Data-model additions

| Feature | Work | Size |
|---|---|---|
| Attendees / RSVP | New `attendees` field (list of contact entries: name/email/status). Schema migration. VTODO `ATTENDEE` mapping. Detail-panel UI. Invite-sending path. | **L→XL** |
| Location | New `location` string field. Detail-panel UI + tooltip. Optional Maps autocomplete. VTODO `LOCATION` mapping. | **M** |
| Meeting link | New `meeting_link` string field. Auto-detection of Zoom/Teams/Meet/Webex/Jitsi URLs in notes. Join button surfaced on bars/cards. | **M** |
| Calendar categories | New `category` field OR promote `board_column` semantics. Per-category color. Filter UX. | **M→L** |
| Busy/free flag | New `show_as` enum (busy / free / tentative / out-of-office). | **S→M** |
| Multiple user-owned calendars | Partial foundation (TodoList already exists). UX: multi-select visibility, per-list color, per-list filter. | **L** |
| Subscribed ICS feeds | New `SubscribedCalendar` entity. Periodic fetch + parse. Read-only items stored distinctly. | **L** |
| Shared calendars with permissions | Auth model, permission tiers, sync path beyond P2P. | **XXL** |

### Pure UX / wiring (no schema)

| Feature | Work | Size |
|---|---|---|
| `due_time_end` interactive UI | `QTimeEdit` in detail panel + add-dialog. | **S** |
| `due_time_block` in-grid assignment | Context menu in calendar cells. | **S→M** |
| Edge-drag-to-resize | Mouse hit-zone detection on bar edges; drag to adjust `due_time` / `estimated_minutes` / `due_time_end`. | **M** |
| Recurring-instance edit UI | "Edit this occurrence / all / future" dialog. Exception storage on recurrence rules. | **L** |
| Schedule / agenda view | New calendar sub-view; scrollable chronological list. | **M** |
| Year heatmap view | New calendar sub-view; density coloring. | **M** |
| Web calendar interactivity | Canvas-based drag-to-reschedule in web; time-block picker; detail edit sheet. | **L** |
| Quick natural-language entry (menu-bar / global hotkey) | Existing parser, new entry point. | **M** |

### Differentiators

| Feature | Rationale | Size |
|---|---|---|
| Travel time as hashed block | Apple-quality scheduling polish. Needs `travel_time_minutes` field + optional Maps integration (manual entry fallback). | **M→L** |
| Scheduling Assistant grid | Outlook-grade meeting support. Depends on attendees shipping first. | **L** (after attendees) |
| Proposals / Openings (public booking) | Fantastical-tier feature. Builds on the existing web server. | **L** |
| Calendar Sets with time/location triggers | High-value power-user feature. Builds on existing filter infrastructure. | **M** |
| Focus-mode integration | OS-specific; macOS easiest (Focus Filters API). | **M** |
| Conference-link detection across many services | Regex table + Join button. Low complexity, high perceived value. | **S→M** |
| Weather overlay | Third-party API integration. Inline strip in day/week. | **M** |
| Widgets | OS-specific; macOS WidgetKit. Desktop-only feasible. | **M→L** |

---

## 4. Sequencing options

Three candidate arcs. Arc selection happens per release milestone; nothing
here is binding. Each is internally coherent and independently shippable.

### Arc A — close obvious gaps (conservative)

Smallest items, highest payoff per hour of work. No schema changes.

1. `due_time_end` interactive UI (S)
2. Location string field + UI + VTODO (M)
3. Meeting-link field + detection + Join button (M)
4. Busy/free flag (S)
5. Edge-drag-to-resize in week/day (M)
6. Schedule / agenda view (M)
7. Conference-link detection extension (S)

Approximately 2–3 weeks. Delivers a recognizably more calendar-app-like
surface without schema or architecture work.

### Arc B — meeting app

For workflows centered on scheduling. Schema-heavy up front.

1. Attendees field + schema migration + VTODO `ATTENDEE` mapping (L→XL)
2. Location + meeting link (M + M)
3. Scheduling Assistant grid, after attendees ship (L)
4. Scheduling Poll / Proposals (public voting page) (L)
5. Openings / public booking link (L)

Approximately 6–10 weeks. Positions the app as an Outlook/Fantastical
alternative for scheduling-heavy use.

### Arc C — differentiators

Unique, loved features from each competitor. Less parity, more "reason to
switch."

1. Menu-bar quick-create entry point (existing NLP backing)
2. Calendar Sets with time/location triggers
3. DayTicker-style horizontal multi-day strip in day view
4. Travel time rendered as hashed block
5. Focus-mode integration (macOS first)
6. Conference-link detection (~35 services)
7. Custom N-day view (2–14 days)

Approximately 4–6 weeks. Skips the schema-heavy meeting-app work.

---

## 5. Cross-cutting invariants

Apply to every phase of any arc.

- **Universal planning platform**: every feature supports the full time scope
  (minutes → years → forever) and data-shape scope (single tasks → projects
  → medical regimens → life plans). Feature-gating that narrows the app's
  scope is out of bounds. See `project-vision-universal-platform.md`.
- **WCAG AA**: hard floor on all color work. Light + dark palettes.
- **i18n**: `tr()` on every new GUI string. YAML intent dictionaries for new
  parser vocabulary.
- **Visual verification mandatory** for UI work. CI-green is necessary, not
  sufficient. See `feedback-q8-calendar-catastrophe.md`.
- **Stress-test specs on realistic worst-case inputs** before locking rules
  that modify spatial extent, layout, or result sets.
- **No phase/step labels in code or commits**. Descriptive names only.
  See `feedback-no-phase-labels.md`.
- **CalDAV round-trip preserved** on every schema change touching exportable
  fields.

---

## 6. References

Primary external references cited in the analysis rounds:

- Google Calendar: [Views](https://support.google.com/calendar/answer/6110849),
  [Event types](https://developers.google.com/workspace/calendar/api/guides/event-types),
  [Sharing permissions](https://support.google.com/calendar/answer/15716974),
  [Reminders→Tasks migration](https://workspaceupdates.googleblog.com/2023/06/assistant-and-calendar-reminders-automatically-migrating-to-tasks.html)
- Apple Calendar: [Travel time](https://support.apple.com/guide/calendar/add-location-and-travel-time-to-events-icl43600/mac),
  [Focus filters](https://support.apple.com/guide/calendar/use-focus-filters-icld13f9da17/mac),
  [Quick event entry](https://www.imore.com/how-add-event-using-natural-language-mac-os-x-calendar-app),
  [Foregoing Fantastical (Six Colors)](https://sixcolors.com/post/2024/01/there-and-back-again-foregoing-fantastical/)
- Outlook Calendar: [Scheduling Assistant](https://support.microsoft.com/en-us/office/use-the-scheduling-assistant-and-room-finder-for-meetings-in-outlook-2e00ac07-cef1-47c8-9b99-77372434d3fa),
  [Scheduling Poll](https://support.microsoft.com/en-us/office/find-the-best-meeting-time-for-everyone-with-outlook-scheduling-poll-7b5ff6c7-4f65-48e6-89b8-3f053c40e382),
  [Delegates](https://support.microsoft.com/en-us/office/about-delegates-allow-someone-to-manage-your-mail-and-calendar-in-outlook-41c40c04-3bd1-4d22-963a-28eafec25926),
  [Neowin on New Outlook](https://www.neowin.net/news/it-and-sysadmins-overwhelmingly-feel-new-outlook-for-windows-is-hot-garbage/)
- Fantastical: [Scheduling (Openings/Proposals)](https://flexibits.com/fantastical/scheduling),
  [Conference-call support](https://flexibits.com/fantastical/help/conference-call-support),
  [NLP guide](https://flexibits.com/blog/2023/10/a-beginners-guide-to-natural-language-processing/),
  [MacStories review](https://www.macstories.net/reviews/the-new-fantastical-review/)

---

## 7. Open questions

Tracked here to prevent silent assumption:

- `event_date` semantics: undefined today; either wire into calendar
  rendering with a concrete interpretation or deprecate the field.
- Arc selection for the next calendar-expansion milestone.
- Release cadence: ship the beta staged today with the current calendar
  state, or hold for a first arc increment.
- Shared-calendar architecture: the existing P2P sync model needs explicit
  scoping work before any shared-calendar feature becomes feasible.
