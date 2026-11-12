# Notification Policy — Timely Reminders, Bounded Volume

## Decision Date: 2026-11-11

## Release: lands before v0.3.11 final

## Context

Task notifications are produced by `MainWindow._check_due_notifications`,
which runs two seconds after launch and then on the 60-second overdue timer.
The behavior as implemented:

- **Two triggers only.** An incomplete item that is due today or overdue is
  added to a single batched banner whose body is a comma-joined list of
  titles, capped at five per group.
- **No alert at the relevant moment.** An item is notified at most once per
  calendar day, gated on `notified_at`. A task due at 15:00 is announced at
  launch as "due today" and is then skipped at 15:00 because it has already
  been notified that day. No reminder precedes a timed item.
- **Midnight batch.** With the app left running, every item due the next day
  becomes "due today" on the first tick after 00:00 and is announced then.
  `database.day_start_hour` is not consulted.
- **Unbounded repetition for overdue items.** An overdue item is re-announced
  once per day for as long as it stays incomplete.
- **Inert settings.** `notifications.check_hour` ("Daily check time") and
  `notifications.upcoming_days` ("Upcoming window") are persisted and shown
  in the Notifications tab but are read nowhere else.
- **Inert per-item fields.** `remind_before_days` and `reminder_cadence`
  exist on `TodoItem`, in the database, and in the web API. No code acts on
  them and the desktop has no control that sets them.
- **Notification as an edit.** Each notification writes `notified_at` and
  calls `mark_updated()`. Sync merges items last-writer-wins on `updated_at`,
  so firing a notification can override a genuine edit made on another device,
  and every notification produces a sync delta.
- **No suppression.** There are no quiet hours, and a running focus session
  does not hold anything back.
- **Tray gate.** The check returns early when `tray_icon is None`, although
  dispatch no longer goes through the tray.
- **Misplaced network check.** LAN address-change detection sits at the tail
  of the same function, after both early returns. It runs only on ticks that
  send a notification.

The result is a feature that fires at arbitrary times, repeats, and says
nothing when a timed commitment is actually approaching.

## Goals

- A notification arrives when something becomes actionable, and at most once
  for that moment.
- Default volume is small and predictable: per timed item, at most two
  banners per occurrence; per day, at most one summary.
- Every behavior is configurable; the defaults are usable without
  configuration.
- The decision logic is a pure function of data, configuration, and an
  injected clock, so every rule is unit-testable.
- Firing a notification never modifies synced data.

## Non-goals

- Action buttons on notifications (Done, Snooze, Open, Join). Deferred; see
  [Deferred work](#deferred-work).
- Notifications in the web UI or on mobile.
- Changes to focus-session, stopwatch, and milestone notifications. Those are
  immediate feedback on an action just taken and stay outside the policy.
- Changes to the dispatch channel. `_notify` keeps its one-channel-per-platform
  rule (OS notification on Linux and Windows, in-app overlay on macOS).

## Terminology

| Term | Definition |
|---|---|
| Eligible item | Incomplete, not deleted, in a list that is neither deleted nor private. Subtasks are eligible on the same terms as top-level items. |
| Timed item | Has `due_date` and `due_time`. |
| Event | A timed item with `due_time_end` set, or with a meeting link recognized by `detect_meeting_link`. Something attended over a span; the start is the moment that matters. |
| Deadline | A timed item that is not an event. Actionable at the cutoff. |
| Block item | Has `due_date` and `due_time_block` but no `due_time`. Its block start is the start of the named block as resolved through the `[time_blocks]` configuration. |
| Date-only item | Has `due_date` only. |
| Occurrence | The scheduled due datetime of an item at evaluation time. A recurring item has a new occurrence after each advance. |
| Logical day | The day as defined by `database.day_start_hour` (`logical_today`). |

## Notification kinds

| Kind | Default | Fires | Content |
|---|---|---|---|
| Daily summary | On, 09:00 | Once per logical day at the summary time | Counts of items due today and overdue, the earliest timed item of the day, and any advance-reminder lines |
| Lead reminder | On, 15 minutes | `lead_minutes` before each timed item's due time and each block item's block start | Title, time, minutes remaining; "starts at" for events, "due at" for deadlines. A block item names its window instead of counting down: "This evening · 17:00–21:00" |
| Due-now alert | Deadlines only | At the due time, if the item is still incomplete | Title and due time |
| Evening preview | Off, 20:00 | Once per logical day at the preview time | Count of items due the next day and the earliest timed one |
| Catch-up | Automatic | After a gap in evaluation, when reminders were missed | One banner listing what came due during the gap |

### Daily summary

- Skipped entirely when there is nothing to report.
- When the app is not running at the summary time, the summary fires on the
  first evaluation after that time on the same logical day. A launch before
  the summary time waits for it.
- Overdue items appear only as a count. There is no per-item overdue
  notification and no daily repetition per item.
- Date-only items appear in the summary and produce no other notification.
- The earliest timed item of the day is chosen across timed items and block
  items, block items ordered by their block start.

### Lead reminder

- Applies to events and deadlines alike.
- Applies to block items, measured from the block start. Time blocks are
  configured explicitly, so the start of "evening" is a known clock time, and
  a block item takes part in the schedule the same way a timed item does.
- Skipped when the item's `updated_at` is later than the scheduled fire time.
  An item created or edited inside its own lead window was just handled, and
  an immediate "in 4 minutes" banner is noise.
- Skipped for items with minutely recurrence; the due-now alert is the
  meaningful signal for sub-daily repetition.
- Delivered late with the true remaining time when evaluation resumes inside
  the lead window (for example, "starts in 6 min").

### Due-now alert

- Controlled by `due_now`: `deadlines` (default), `all`, or `off`.
- Events are excluded by default: a banner at the start of a meeting that is
  already being attended is redundant.
- Block items produce no due-now alert. A block is a window, not a cutoff.

### Advance deadline reminders

`remind_before_days` and `reminder_cadence` become functional:

- `once` — a line in the daily summary on the day `due_date − N`.
- `daily_until_due` — a line in each daily summary from `due_date − N`
  through the day before the due date.
- `none` or `remind_before_days == 0` — no advance reminder.

Advance reminders never produce their own banner. An advance line on its own
is enough to produce a summary on a day that would otherwise have none.

### Catch-up

Evaluation gaps occur when the app is closed or the machine is asleep.

- A lead reminder whose due time is still in the future is delivered normally.
- A lead reminder or due-now alert whose due time passed more than ten minutes
  earlier is not delivered as itself. It joins a missed set.
- The missed set is limited to the current logical day. Older items are simply
  overdue and are covered by the summary count.
- When the daily summary fires in the same evaluation, the missed set is
  absorbed by the summary's overdue count and no catch-up banner is shown.
  Otherwise one catch-up banner lists the missed items.

The first evaluation after upgrading to this design finds an empty fired
record. The same rules bound the result to at most one banner.

## Suppression rules

- **Master switch.** `enabled = false` silences every kind in this document.
- **Quiet hours.** Default 22:00–07:00; the window may cross midnight. It
  includes its start and excludes its end, and equal start and end times make
  an empty window. The daily summary, evening preview, and catch-up banner
  are never delivered inside it. Lead reminders and due-now alerts are
  delivered inside quiet hours by default: quiet hours shield against ambient
  digests, while a time-anchored commitment placed inside the window (an
  early flight) exists to interrupt. With `quiet_allow_timed = false` they
  are silenced as well and re-evaluated under the catch-up rules when the
  window ends: an alert no more than ten minutes old is delivered, an older
  one from the same logical day joins the missed set, and one from an earlier
  day is only counted as overdue.
- **A summary or preview time inside quiet hours.** It is treated as the end
  of quiet hours on the same logical day: with the default window, a summary
  set for 06:00 is delivered at 07:00, and one set for 23:00 is delivered at
  07:00 that morning. Waiting for the window to end instead would lose the
  23:00 summary altogether, because its logical day ends before the window
  does.
- **Focus sessions.** While a focus timer is in its work phase or the
  stopwatch is running, the daily summary, evening preview, and catch-up
  banner are held until the session ends. Lead reminders and due-now alerts
  are delivered regardless. Controlled by `hold_during_focus`.
  - A paused timer or stopwatch does not hold, and neither does a break. A
    session left paused would otherwise hold the summary indefinitely, and in
    a work/break cycle a held summary arrives at the next break.
  - There is no upper limit on the hold. A stopwatch that runs all morning
    holds the summary all morning; timed reminders are unaffected.
- **Holding and release.** A held notification is not written to the fired
  record, so each later evaluation reconsiders it. Nothing is queued, and
  there is no release event: the first once-a-minute evaluation after the
  window or the session ends delivers what was held, built from the state of
  the lists at that moment. Release therefore follows the end of a session by
  up to a minute, which also keeps a released summary from arriving in the
  same instant as the session-complete notification. A summary still held
  when its logical day ends is not delivered; the next day's summary counts
  the same items as overdue.
- **Coalescing.** Lead reminders and due-now alerts that fire in the same
  evaluation merge into one banner with one line per item, capped at five
  lines plus a remainder count. Summary, preview, and catch-up merge the same
  way among themselves. One evaluation therefore produces at most two banners.
- **Re-arming.** The fired record is keyed by item, kind, and occurrence.
  Rescheduling an item creates a new occurrence and re-arms its reminders.
  Completing or deleting an item removes it from eligibility. Reopening a
  completed item does not replay reminders already fired for that occurrence.
- **Private lists.** Excluded from every kind, including counts. A banner is
  an ambient surface visible in screen shares and OS notification history;
  a count alone discloses that private items exist.

## Multiple devices

Each device evaluates the policy independently against its own fired record.
A reminder fired on one device does not suppress it on another. Cross-device
suppression would depend on sync latency and on which devices are awake, and
would turn a sync delay into a missed or duplicated reminder.

## Architecture

### Policy module

`core/notification_policy.py`, with no Qt dependency:

- Input: the lists, the notification configuration, the current datetime, the
  fired record, and whether a focus session is active.
- Output: the notifications to deliver, the keys to record as fired, and
  what is being held by quiet hours or a focus session.
- The current time is always a parameter. The module does not call
  `date.today()` or `datetime.now()`.
- Notifications are returned as structured data (kind, item references,
  counts, times), not as display strings.

### Presentation and scheduling

`TaskNotifier` in `gui/` calls the policy, records the keys an evaluation
consumed, turns the structured results into translated strings via `tr()`,
and dispatches through the existing `_notify`. The logic leaves
`main_window.py`. Its sources (lists, settings, clock) and its delivery
callable are passed in, so it runs in tests with a fixed clock and no window.

- The main window's once-a-minute tick drives evaluation, alongside the
  overdue refresh and recurring-item advance it already performed. The tick
  is single-shot and re-armed each time for just after the next wall-clock
  minute, so a 15-minute lead lands on the minute. The previous repeating
  timer started at launch and could fire up to 59 seconds late.
- Fired keys are recorded before anything is delivered, so a delivery
  failure cannot cause a repeat.
- Evaluation compares stored fire times against the injected clock, so a
  timer that fires late after sleep catches up by construction.
- Evaluation runs before `advance_all_overdue_recurring` in each tick. That
  function moves an overdue recurring item to its next occurrence as soon as
  its due time passes; evaluated afterward, the due-now alert for the passed
  occurrence would never be seen.
- The `tray_icon is None` gate is removed.
- LAN address-change detection moves out of the notification path into the
  periodic tick so it runs every minute.

### Block resolution

A single resolver in `core/` maps a `due_time_block` and a due date to the
block's start datetime, and is shared by the policy and by display code.

- `morning`, `afternoon`, `evening`, and `night` start at their configured
  start hour.
- `early_X` starts where `X` starts; `late_X` starts at the midpoint of `X`.
- `noon` and `midnight` are the fixed bands 11:30–12:30 and 23:30–00:30 and
  start at 11:30 and 23:30.
- The night range crosses midnight and is resolved by offset from its start,
  so `late_night` under the default 21:00–06:00 range starts at 01:30 on the
  calendar day after the due date.

`_format_time_window` currently derives early and late halves inline with
`(start + end) // 2`, which yields 13:00 for the default night range. It
moves onto the shared resolver.

### Fired record

A local table in the SQLite database, added in schema v22:

```sql
CREATE TABLE notification_log (
    item_id    TEXT NOT NULL,     -- empty string for summary / preview / catch-up
    kind       TEXT NOT NULL,
    occurrence TEXT NOT NULL,     -- ISO datetime, or ISO date for per-day kinds
    fired_at   INTEGER NOT NULL,  -- ms since epoch
    PRIMARY KEY (item_id, kind, occurrence)
);
```

- Sync exchanges items and lists over the protocol, not database files, so the
  table is local to the device by construction.
- Rows whose occurrence is more than 30 days old are pruned.
- `notified_at` is removed from `TodoItem` and from the web API payload.
  Peers on older versions ignore its absence (`from_dict` defaults it to 0),
  and its presence in their payloads is ignored in turn.
- The `items.notified_at` column itself stays in the table for now. Builds
  through v0.3.11b8 share the database file with a source checkout and name
  the column when saving an item; dropping it would fail every save they
  make. It is dropped in a later migration once those builds are retired. A
  save from this version leaves the column at its default, so an older build
  run afterward may repeat its once-per-day banner.
- `AnalyticsService.notification_effectiveness` reads the log instead of
  `notified_at > 0`.

A file in the XDG state directory was considered. The table is preferred for
atomic writes alongside the data it describes and for a single migration path.

## Configuration

`[notifications]` in the TOML config:

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Master switch |
| `summary_enabled` | `true` | Daily summary |
| `summary_time` | `"09:00"` | Daily summary time |
| `lead_enabled` | `true` | Lead reminders |
| `lead_minutes` | `15` | Minutes before the due time |
| `due_now` | `"deadlines"` | `deadlines`, `all`, or `off` |
| `quiet_hours_enabled` | `true` | Quiet hours |
| `quiet_start` | `"22:00"` | Start of quiet hours |
| `quiet_end` | `"07:00"` | End of quiet hours |
| `quiet_allow_timed` | `true` | Deliver lead reminders and due-now alerts inside quiet hours |
| `hold_during_focus` | `true` | Hold summary, preview, and catch-up during focus sessions |

`preview_enabled` (`false`) and `preview_time` (`"20:00"`) are added together
with the evening preview, not before it.

Values:

- Times are `"HH:MM"` strings. An unquoted TOML local time is read as well.
- `lead_minutes` is a whole number from 1 to 120; a value outside the range
  is brought to the nearest limit.
- A value of the wrong kind is ignored in favor of its default, with a
  warning in the log. The other keys of the section are unaffected.

Existing keys are read when the key that replaces them is absent, and are not
written back, so the first save completes the migration:

- `check_hour` → `summary_time` (`N` becomes `"N:00"`).
- `notify_overdue`, `notify_due_today` → when both are `false`,
  `summary_enabled` loads as `false`. With only one of them `false` the
  summary stays on and shows both counts; the two were separate content
  switches and the summary has no equivalent.
- `upcoming_days` → dropped. Nothing read it.

Builds through v0.3.11b8 share the configuration file with a source checkout
and write it at exit with only the keys they know. After such a build has
run, the next launch of this version finds the keys above gone and reads the
old ones again: the summary time and switch survive, and every other value in
this section returns to its default. This ends when those builds are retired
and is to be stated in the release notes.

The Notifications tab in Preferences is regrouped to match: General, Daily
summary, Timed reminders, Quiet time. An Evening preview group is added with
the evening preview.

- Unticking the master switch disables the other groups; unticking a group's
  own switch disables what it governs. The focus-session hold does not depend
  on the quiet-hours switch.
- Time fields have minute precision and follow the 12- or 24-hour setting.
- A summary time inside quiet hours shows when the summary is delivered
  instead. Equal quiet-hours start and end times show that no quiet hours
  result.
- A change applies from the next once-a-minute evaluation.

## Testing

The policy module is covered by fixed-clock unit tests, including:

- A lead reminder fires at exactly `due − lead_minutes` and never twice.
- A deadline produces a due-now alert; an event does not under the default.
- An item edited inside its lead window produces no lead reminder.
- Rescheduling re-arms; completing cancels; reopening does not replay.
- The summary fires once per logical day, honors `day_start_hour`, is skipped
  when empty, and fires late on a launch after the summary time.
- Quiet hours crossing midnight, within one day, disabled, and with equal
  start and end times.
- A summary time inside quiet hours fires at the end of the window on the
  same logical day, including a late-evening summary time and a day start
  later than midnight.
- A launch inside quiet hours delivers no summary and records none.
- A lead reminder inside quiet hours is delivered by default and silenced
  with `quiet_allow_timed = false`; a silenced reminder is delivered, reported
  as missed, or dropped when the window ends, according to its age.
- Missed items found inside quiet hours are reported when the window ends,
  inside the summary when it is released in the same evaluation.
- A block item produces a lead reminder before its block start, no due-now
  alert, and re-arms when the block configuration changes.
- Block resolution for every canonical block, including `late_night` across
  midnight.
- Waking from sleep across a quiet-hours boundary.
- Catch-up: missed set limited to the logical day, absorbed by a same-tick
  summary, delivered as one banner otherwise.
- Focus hold releases at session end; timed reminders pass through; a
  released summary reflects the time it is delivered; a paused session, a
  break, and a paused stopwatch do not hold.
- Coalescing of simultaneous reminders and the five-line cap.
- Private and deleted lists contribute nothing, including to counts.
- Minutely recurrence: no lead reminder; due-now per occurrence.
- A recurring timed item still produces its due-now alert in the tick where
  it is auto-advanced.
- Config round-trip, loading of pre-existing `[notifications]` sections, and
  values of the wrong kind.
- Schema v21 → v22 migration, including that `items.notified_at` survives
  it and that an insert naming the column still succeeds.

Visual verification on macOS (overlay path) and Fedora KDE (OS path) covers
banner text, coalesced layout, and the regrouped Notifications tab.

## Delivery sequence

1. Policy module, block resolver, fired record, schema v22, and scheduler,
   replacing `_check_due_notifications`. Lead reminders for timed and block
   items, due-now alerts, daily summary, catch-up, coalescing, and re-arming.
2. Quiet hours and focus-session hold.
3. Configuration keys, migration of existing keys, and the regrouped
   Notifications tab.
4. Advance deadline reminders, with controls for `remind_before_days` and
   `reminder_cadence` in the AddTodo dialog and the detail panel.
5. Evening preview.

## Deferred work

- **Notification actions** — Done, Snooze, Open, and Join for events with a
  meeting link. `desktop-notifier` exposes buttons and click callbacks and
  reports per-platform support through its `Capability` enum; what each
  backend (libnotify servers, WinRT, the macOS overlay) honors is unverified
  and requires research before design. The macOS overlay has a body-click
  signal but no buttons.
- **Per-item lead time** — an override of `lead_minutes` on a single item.
- **Snooze** — depends on notification actions.
- **Web and mobile notifications.**
