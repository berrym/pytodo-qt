"""Tests for pytodo_qt.core.nlp_parser.

Pure Python tests — no Qt dependency required.
All date-dependent tests use the ``today`` parameter for deterministic results.
"""

from __future__ import annotations

from datetime import date, time

from pytodo_qt.core.nlp_parser import EntityKind, parse

# Fixed "today" for all tests that need deterministic dates.
# Wednesday, 2026-03-11
TODAY = date(2026, 3, 11)


# ---------------------------------------------------------------------------
# TestDateParsing
# ---------------------------------------------------------------------------


class TestDateParsing:
    """Date extraction from natural language."""

    def test_today(self) -> None:
        r = parse("finish report today", today=TODAY)
        assert r.due_date == TODAY
        assert r.reminder == "finish report"

    def test_tomorrow(self) -> None:
        r = parse("call dentist tomorrow", today=TODAY)
        assert r.due_date == date(2026, 3, 12)
        assert r.reminder == "call dentist"

    def test_yesterday(self) -> None:
        r = parse("log hours yesterday", today=TODAY)
        assert r.due_date == date(2026, 3, 10)

    def test_day_name_future(self) -> None:
        # TODAY is Wednesday; Friday is 2 days ahead
        r = parse("submit PR Friday", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_day_name_same_day_goes_next_week(self) -> None:
        # TODAY is Wednesday; "Wednesday" means next Wednesday
        r = parse("standup Wednesday", today=TODAY)
        assert r.due_date == date(2026, 3, 18)

    def test_day_name_abbreviation(self) -> None:
        r = parse("meeting Fri", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_next_day_name(self) -> None:
        # "next Friday" = Friday after the upcoming one
        r = parse("meet Sarah next Friday", today=TODAY)
        assert r.due_date == date(2026, 3, 20)

    def test_next_week(self) -> None:
        r = parse("review code next week", today=TODAY)
        assert r.due_date == date(2026, 3, 18)

    def test_next_month(self) -> None:
        r = parse("renew license next month", today=TODAY)
        assert r.due_date == date(2026, 4, 11)

    def test_in_n_days(self) -> None:
        r = parse("follow up in 3 days", today=TODAY)
        assert r.due_date == date(2026, 3, 14)

    def test_in_n_weeks(self) -> None:
        r = parse("review in 2 weeks", today=TODAY)
        assert r.due_date == date(2026, 3, 25)

    def test_in_n_months(self) -> None:
        r = parse("check back in 3 months", today=TODAY)
        assert r.due_date == date(2026, 6, 11)

    def test_month_day_current_year(self) -> None:
        # March 20 hasn't passed yet (today is March 11)
        r = parse("submit by March 20", today=TODAY)
        assert r.due_date == date(2026, 3, 20)

    def test_month_day_next_year_when_passed(self) -> None:
        # January 5 already passed
        r = parse("renew January 5", today=TODAY)
        assert r.due_date == date(2027, 1, 5)

    def test_month_day_with_year(self) -> None:
        r = parse("deadline January 1 2027", today=TODAY)
        assert r.due_date == date(2027, 1, 1)

    def test_month_abbreviation(self) -> None:
        r = parse("submit by Mar 20", today=TODAY)
        assert r.due_date == date(2026, 3, 20)

    def test_month_day_with_comma(self) -> None:
        r = parse("submit by March 20, 2027", today=TODAY)
        assert r.due_date == date(2027, 3, 20)

    def test_iso_date(self) -> None:
        r = parse("due 2026-03-15", today=TODAY)
        assert r.due_date == date(2026, 3, 15)

    def test_slash_date_mm_dd(self) -> None:
        r = parse("due 3/15", today=TODAY)
        assert r.due_date == date(2026, 3, 15)

    def test_slash_date_mm_dd_yyyy(self) -> None:
        r = parse("due 3/15/2026", today=TODAY)
        assert r.due_date == date(2026, 3, 15)

    def test_prefix_due(self) -> None:
        r = parse("finish report due tomorrow", today=TODAY)
        assert r.due_date == date(2026, 3, 12)
        assert "due" not in r.reminder.lower()

    def test_prefix_by(self) -> None:
        r = parse("finish report by Friday", today=TODAY)
        assert r.due_date == date(2026, 3, 13)
        assert "by" not in r.reminder.lower()

    def test_prefix_on(self) -> None:
        r = parse("meeting on Friday", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_prefix_before(self) -> None:
        r = parse("submit before Friday", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_invalid_date_feb_30_falls_through(self) -> None:
        r = parse("remember February 30", today=TODAY)
        # Feb 30 is invalid — text stays as reminder
        assert r.due_date is None
        assert "February 30" in r.reminder

    def test_last_date_wins(self) -> None:
        r = parse("schedule for tomorrow actually Friday", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_leap_year_feb_29(self) -> None:
        r = parse("event February 29", today=date(2024, 1, 1))
        assert r.due_date == date(2024, 2, 29)

    def test_day_name_case_insensitive(self) -> None:
        r = parse("submit FRIDAY", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_in_1_day(self) -> None:
        r = parse("do this in 1 day", today=TODAY)
        assert r.due_date == date(2026, 3, 12)


# ---------------------------------------------------------------------------
# TestTimeParsing
# ---------------------------------------------------------------------------


class TestTimeParsing:
    """Time extraction from natural language."""

    def test_at_hh_mm_24h(self) -> None:
        r = parse("meeting at 14:30", today=TODAY)
        assert r.due_time == time(14, 30)

    def test_at_hh_mm_am(self) -> None:
        r = parse("call at 9:30am", today=TODAY)
        assert r.due_time == time(9, 30)

    def test_at_hh_mm_pm(self) -> None:
        r = parse("call at 2:30pm", today=TODAY)
        assert r.due_time == time(14, 30)

    def test_at_h_pm(self) -> None:
        r = parse("lunch at 1pm", today=TODAY)
        assert r.due_time == time(13, 0)

    def test_by_hh_mm(self) -> None:
        r = parse("finish by 17:00", today=TODAY)
        assert r.due_time == time(17, 0)

    def test_noon(self) -> None:
        r = parse("lunch at noon", today=TODAY)
        assert r.due_time == time(12, 0)

    def test_midnight(self) -> None:
        r = parse("deploy at midnight", today=TODAY)
        assert r.due_time == time(0, 0)

    def test_morning(self) -> None:
        r = parse("run tomorrow morning", today=TODAY)
        assert r.due_time == time(9, 0)

    def test_afternoon(self) -> None:
        r = parse("meet Tuesday afternoon", today=TODAY)
        assert r.due_time == time(14, 0)

    def test_evening(self) -> None:
        r = parse("dinner Friday evening", today=TODAY)
        assert r.due_time == time(18, 0)

    def test_eod(self) -> None:
        r = parse("submit eod", today=TODAY)
        assert r.due_time == time(17, 0)

    def test_end_of_day(self) -> None:
        r = parse("submit end of day", today=TODAY)
        assert r.due_time == time(17, 0)

    def test_time_without_date_still_captured(self) -> None:
        r = parse("meeting at 3pm", today=TODAY)
        assert r.due_time == time(15, 0)
        # No date inferred from time alone
        assert r.due_date is None

    def test_at_the_office_not_matched(self) -> None:
        r = parse("meeting at the office", today=TODAY)
        assert r.due_time is None
        assert "at the office" in r.reminder

    def test_12pm_is_noon(self) -> None:
        r = parse("event at 12pm", today=TODAY)
        assert r.due_time == time(12, 0)

    def test_12am_is_midnight(self) -> None:
        r = parse("event at 12am", today=TODAY)
        assert r.due_time == time(0, 0)


# ---------------------------------------------------------------------------
# TestPriorityParsing
# ---------------------------------------------------------------------------


class TestPriorityParsing:
    """Priority extraction."""

    def test_p1(self) -> None:
        r = parse("fix crash p1", today=TODAY)
        assert r.priority == 1
        assert r.reminder == "fix crash"

    def test_p2(self) -> None:
        r = parse("update docs p2", today=TODAY)
        assert r.priority == 2

    def test_p3(self) -> None:
        r = parse("clean up logs p3", today=TODAY)
        assert r.priority == 3

    def test_single_exclamation(self) -> None:
        r = parse("fix crash !", today=TODAY)
        assert r.priority == 1

    def test_double_exclamation(self) -> None:
        r = parse("fix crash !!", today=TODAY)
        assert r.priority == 1

    def test_triple_exclamation(self) -> None:
        r = parse("fix crash !!!", today=TODAY)
        assert r.priority == 1

    def test_high_priority(self) -> None:
        r = parse("fix crash high priority", today=TODAY)
        assert r.priority == 1

    def test_low_priority(self) -> None:
        r = parse("refactor low priority", today=TODAY)
        assert r.priority == 3

    def test_urgent(self) -> None:
        r = parse("deploy fix urgent", today=TODAY)
        assert r.priority == 1

    def test_last_priority_wins(self) -> None:
        r = parse("fix bug p1 p3", today=TODAY)
        assert r.priority == 3

    def test_p1ckup_not_matched(self) -> None:
        r = parse("tell John p1ckup the car", today=TODAY)
        assert r.priority is None
        assert "p1ckup" in r.reminder


# ---------------------------------------------------------------------------
# TestTagParsing
# ---------------------------------------------------------------------------


class TestTagParsing:
    """Tag extraction."""

    def test_at_tag(self) -> None:
        r = parse("call plumber @home", today=TODAY)
        assert r.tags == ["@home"]
        assert r.reminder == "call plumber"

    def test_hash_tag_converted(self) -> None:
        r = parse("deploy #release", today=TODAY)
        assert r.tags == ["@release"]

    def test_multiple_tags(self) -> None:
        r = parse("fix bug @work #urgent", today=TODAY)
        assert "@work" in r.tags
        assert "@urgent" in r.tags
        assert len(r.tags) == 2

    def test_hyphenated_tag(self) -> None:
        r = parse("task @long-term", today=TODAY)
        assert r.tags == ["@long-term"]

    def test_email_not_matched(self) -> None:
        r = parse("email user@example.com", today=TODAY)
        assert r.tags == []
        assert "user@example.com" in r.reminder

    def test_tag_with_numbers(self) -> None:
        r = parse("task @sprint3", today=TODAY)
        assert r.tags == ["@sprint3"]

    def test_duplicate_tags_deduplicated(self) -> None:
        r = parse("task @work @work", today=TODAY)
        assert r.tags == ["@work"]

    def test_tag_case_preserved(self) -> None:
        r = parse("task @Work", today=TODAY)
        assert r.tags == ["@Work"]

    def test_hash_and_at_mixed(self) -> None:
        r = parse("task @home #shopping", today=TODAY)
        assert "@home" in r.tags
        assert "@shopping" in r.tags

    def test_tag_at_start(self) -> None:
        r = parse("@urgent fix the build", today=TODAY)
        assert r.tags == ["@urgent"]
        assert r.reminder == "fix the build"


# ---------------------------------------------------------------------------
# TestRecurrenceParsing
# ---------------------------------------------------------------------------


class TestRecurrenceParsing:
    """Recurrence extraction."""

    def test_every_day(self) -> None:
        r = parse("take pills every day", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_interval == 1

    def test_daily(self) -> None:
        r = parse("standup daily", today=TODAY)
        assert r.recurrence_type == "daily"

    def test_every_n_days(self) -> None:
        r = parse("water plants every 3 days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_interval == 3

    def test_every_week(self) -> None:
        r = parse("review every week", today=TODAY)
        assert r.recurrence_type == "weekly"

    def test_weekly(self) -> None:
        r = parse("review weekly", today=TODAY)
        assert r.recurrence_type == "weekly"

    def test_every_n_weeks(self) -> None:
        r = parse("report every 2 weeks", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert r.recurrence_interval == 2

    def test_every_month(self) -> None:
        r = parse("pay rent every month", today=TODAY)
        assert r.recurrence_type == "monthly"

    def test_monthly(self) -> None:
        r = parse("pay rent monthly", today=TODAY)
        assert r.recurrence_type == "monthly"

    def test_every_n_months(self) -> None:
        r = parse("dentist every 6 months", today=TODAY)
        assert r.recurrence_type == "monthly"
        assert r.recurrence_interval == 6

    def test_every_year(self) -> None:
        r = parse("renew license every year", today=TODAY)
        assert r.recurrence_type == "yearly"

    def test_yearly(self) -> None:
        r = parse("renew license yearly", today=TODAY)
        assert r.recurrence_type == "yearly"

    def test_annually(self) -> None:
        r = parse("review annually", today=TODAY)
        assert r.recurrence_type == "yearly"

    def test_daily_for_n_days(self) -> None:
        r = parse("take pills daily for 10 days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 10

    def test_weekly_for_n_weeks(self) -> None:
        r = parse("sprint review weekly for 6 weeks", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert r.recurrence_end_count == 6

    def test_recurrence_implies_due_date_today(self) -> None:
        r = parse("take pills daily", today=TODAY)
        assert r.due_date == TODAY

    def test_n_times_a_day(self) -> None:
        r = parse("stretch 3 times a day", today=TODAY)
        assert r.recurrence_type == "daily"
        assert "(3x/day)" in r.reminder

    def test_n_times_a_week(self) -> None:
        r = parse("exercise 3 times a week", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert "(3x/week)" in r.reminder

    def test_recurrence_with_explicit_date(self) -> None:
        r = parse("take pills daily tomorrow", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.due_date == date(2026, 3, 12)


# ---------------------------------------------------------------------------
# TestPomodoroParsing
# ---------------------------------------------------------------------------


class TestPomodoroParsing:
    """Pomodoro estimate extraction."""

    def test_tilde_np(self) -> None:
        r = parse("write report ~3p", today=TODAY)
        assert r.pomodoro_estimate == 3

    def test_tilde_n_pomodoros(self) -> None:
        r = parse("refactor ~2 pomodoros", today=TODAY)
        assert r.pomodoro_estimate == 2

    def test_tilde_n_pom(self) -> None:
        r = parse("review PR ~1 pom", today=TODAY)
        assert r.pomodoro_estimate == 1

    def test_tilde_n_poms(self) -> None:
        r = parse("design doc ~4 poms", today=TODAY)
        assert r.pomodoro_estimate == 4

    def test_tilde_n_sessions(self) -> None:
        r = parse("debug ~2 sessions", today=TODAY)
        assert r.pomodoro_estimate == 2

    def test_pomodoro_removed_from_reminder(self) -> None:
        r = parse("write report ~3p", today=TODAY)
        assert "~3p" not in r.reminder
        assert r.reminder == "write report"


# ---------------------------------------------------------------------------
# TestCombinedParsing
# ---------------------------------------------------------------------------


class TestCombinedParsing:
    """Multi-entity inputs."""

    def test_full_example_groceries(self) -> None:
        r = parse("Buy groceries tomorrow at 3pm @errands p1", today=TODAY)
        assert r.reminder == "Buy groceries"
        assert r.due_date == date(2026, 3, 12)
        assert r.due_time == time(15, 0)
        assert r.tags == ["@errands"]
        assert r.priority == 1

    def test_recurring_with_end_count_and_priority(self) -> None:
        r = parse("Take pills every day for 10 days p2", today=TODAY)
        assert r.reminder == "Take pills"
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 10
        assert r.priority == 2
        assert r.due_date == TODAY

    def test_tags_and_date_and_time(self) -> None:
        r = parse("meeting @work tomorrow at 2pm", today=TODAY)
        assert r.tags == ["@work"]
        assert r.due_date == date(2026, 3, 12)
        assert r.due_time == time(14, 0)
        assert r.reminder == "meeting"

    def test_multiple_tags_with_priority(self) -> None:
        r = parse("Fix login crash @work #urgent p1", today=TODAY)
        assert r.reminder == "Fix login crash"
        assert "@work" in r.tags
        assert "@urgent" in r.tags
        assert r.priority == 1

    def test_date_with_pomodoro(self) -> None:
        r = parse("Write quarterly report by March 20 ~4p", today=TODAY)
        assert r.reminder == "Write quarterly report"
        assert r.due_date == date(2026, 3, 20)
        assert r.pomodoro_estimate == 4

    def test_all_entity_types(self) -> None:
        r = parse("Review code tomorrow at 10am @dev p2 ~2p", today=TODAY)
        assert r.reminder == "Review code"
        assert r.due_date == date(2026, 3, 12)
        assert r.due_time == time(10, 0)
        assert r.tags == ["@dev"]
        assert r.priority == 2
        assert r.pomodoro_estimate == 2

    def test_order_independence_tags_first(self) -> None:
        r = parse("@work Fix bug tomorrow p1", today=TODAY)
        assert r.tags == ["@work"]
        assert r.due_date == date(2026, 3, 12)
        assert r.priority == 1
        assert r.reminder == "Fix bug"

    def test_order_independence_priority_first(self) -> None:
        r = parse("p1 Fix bug tomorrow @work", today=TODAY)
        assert r.priority == 1
        assert r.due_date == date(2026, 3, 12)
        assert r.tags == ["@work"]

    def test_relative_date_example(self) -> None:
        r = parse("Follow up with client in 3 days", today=TODAY)
        assert r.reminder == "Follow up with client"
        assert r.due_date == date(2026, 3, 14)

    def test_no_entities_just_reminder(self) -> None:
        r = parse("Remember to call mom", today=TODAY)
        assert r.reminder == "Remember to call mom"
        assert r.due_date is None
        assert r.due_time is None
        assert r.priority is None
        assert r.tags == []

    def test_date_and_recurrence_together(self) -> None:
        r = parse("Team standup daily tomorrow at 9am", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.due_date == date(2026, 3, 12)
        assert r.due_time == time(9, 0)

    def test_iso_date_with_priority(self) -> None:
        r = parse("deadline 2026-04-01 p1", today=TODAY)
        assert r.due_date == date(2026, 4, 1)
        assert r.priority == 1

    def test_slash_date_with_tags(self) -> None:
        r = parse("submit report 3/20 @work", today=TODAY)
        assert r.due_date == date(2026, 3, 20)
        assert r.tags == ["@work"]


# ---------------------------------------------------------------------------
# TestRemainderExtraction
# ---------------------------------------------------------------------------


class TestRemainderExtraction:
    """Remainder text after entity removal."""

    def test_entities_at_end(self) -> None:
        r = parse("Buy groceries tomorrow p1", today=TODAY)
        assert r.reminder == "Buy groceries"

    def test_entities_at_start(self) -> None:
        r = parse("@work Fix the database", today=TODAY)
        assert r.reminder == "Fix the database"

    def test_entities_in_middle(self) -> None:
        r = parse("call @home plumber tomorrow", today=TODAY)
        assert "call" in r.reminder
        assert "plumber" in r.reminder

    def test_double_spaces_collapsed(self) -> None:
        r = parse("Buy  groceries  tomorrow", today=TODAY)
        assert "  " not in r.reminder

    def test_prefix_words_consumed(self) -> None:
        r = parse("report due tomorrow", today=TODAY)
        assert r.reminder == "report"

    def test_empty_input(self) -> None:
        r = parse("", today=TODAY)
        assert r.reminder == ""

    def test_whitespace_only(self) -> None:
        r = parse("   ", today=TODAY)
        assert r.reminder == ""

    def test_only_entities_empty_remainder(self) -> None:
        r = parse("tomorrow p1 @work", today=TODAY)
        assert r.reminder == ""

    def test_unicode_text_preserved(self) -> None:
        r = parse("Buy croissants tomorrow", today=TODAY)
        assert "croissants" in r.reminder

    def test_special_characters_preserved(self) -> None:
        r = parse("Fix bug #123 (critical)", today=TODAY)
        assert "(critical)" in r.reminder


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and unusual inputs."""

    def test_empty_string(self) -> None:
        r = parse("", today=TODAY)
        assert r.reminder == ""
        assert r.due_date is None
        assert r.spans == []

    def test_no_entities(self) -> None:
        r = parse("just a plain reminder", today=TODAY)
        assert r.reminder == "just a plain reminder"
        assert r.due_date is None
        assert r.priority is None
        assert r.tags == []

    def test_very_long_input(self) -> None:
        text = "do something " * 100 + "tomorrow"
        r = parse(text, today=TODAY)
        assert r.due_date == date(2026, 3, 12)
        assert len(r.reminder) > 0

    def test_numeric_only(self) -> None:
        r = parse("12345", today=TODAY)
        # Should not crash, numbers alone don't match priority (no p prefix)
        assert r.priority is None

    def test_buy_3_apples_no_priority(self) -> None:
        r = parse("Buy 3 apples", today=TODAY)
        assert r.priority is None
        assert "3 apples" in r.reminder

    def test_priority_seating_no_extraction(self) -> None:
        # "Priority" alone doesn't trigger — only "high priority" / "low priority"
        r = parse("Priority seating at restaurant", today=TODAY)
        assert r.priority is None

    def test_parse_result_default_values(self) -> None:
        r = parse("simple task", today=TODAY)
        assert r.recurrence_type is None
        assert r.recurrence_interval == 1
        assert r.recurrence_end_date is None
        assert r.recurrence_end_count is None
        assert r.pomodoro_estimate is None

    def test_multiple_entity_types_dont_interfere(self) -> None:
        r = parse("@tag1 @tag2 p1 tomorrow ~2p", today=TODAY)
        assert len(r.tags) == 2
        assert r.priority == 1
        assert r.due_date == date(2026, 3, 12)
        assert r.pomodoro_estimate == 2

    def test_today_parameter_overrides_default(self) -> None:
        custom = date(2025, 6, 15)
        r = parse("task tomorrow", today=custom)
        assert r.due_date == date(2025, 6, 16)


# ---------------------------------------------------------------------------
# TestSpanAccuracy
# ---------------------------------------------------------------------------


class TestSpanAccuracy:
    """Verify EntitySpan offsets are correct for highlighting."""

    def test_tag_span(self) -> None:
        r = parse("task @work", today=TODAY)
        tag_spans = [s for s in r.spans if s.kind == EntityKind.TAG]
        assert len(tag_spans) == 1
        assert tag_spans[0].start == 5
        assert tag_spans[0].end == 10

    def test_date_span(self) -> None:
        r = parse("task tomorrow", today=TODAY)
        date_spans = [s for s in r.spans if s.kind == EntityKind.DATE]
        assert len(date_spans) == 1
        assert date_spans[0].start == 5
        assert date_spans[0].end == 13

    def test_priority_span(self) -> None:
        r = parse("fix bug p1", today=TODAY)
        prio_spans = [s for s in r.spans if s.kind == EntityKind.PRIORITY]
        assert len(prio_spans) == 1
        assert prio_spans[0].start == 8
        assert prio_spans[0].end == 10

    def test_time_span_includes_prefix(self) -> None:
        r = parse("meeting at 3pm", today=TODAY)
        time_spans = [s for s in r.spans if s.kind == EntityKind.TIME]
        assert len(time_spans) == 1
        # "at 3pm" should be the span
        assert time_spans[0].start == 8
        assert time_spans[0].end == 14

    def test_multiple_spans_non_overlapping(self) -> None:
        r = parse("task @work tomorrow p1", today=TODAY)
        for i in range(len(r.spans)):
            for j in range(i + 1, len(r.spans)):
                a, b = r.spans[i], r.spans[j]
                assert a.end <= b.start or b.end <= a.start, f"Spans overlap: {a} and {b}"

    def test_spans_sorted_by_start(self) -> None:
        r = parse("@work task tomorrow p1", today=TODAY)
        starts = [s.start for s in r.spans]
        assert starts == sorted(starts)

    def test_span_display_for_tag(self) -> None:
        r = parse("task @errands", today=TODAY)
        tag_spans = [s for s in r.spans if s.kind == EntityKind.TAG]
        assert tag_spans[0].display == "@errands"

    def test_span_display_for_priority(self) -> None:
        r = parse("fix bug p1", today=TODAY)
        prio_spans = [s for s in r.spans if s.kind == EntityKind.PRIORITY]
        assert prio_spans[0].display == "High"

    def test_pomodoro_span(self) -> None:
        r = parse("task ~3p", today=TODAY)
        pom_spans = [s for s in r.spans if s.kind == EntityKind.POMODORO]
        assert len(pom_spans) == 1
        assert pom_spans[0].display == "~3 pom"

    def test_recurrence_span(self) -> None:
        r = parse("task every day", today=TODAY)
        rec_spans = [s for s in r.spans if s.kind == EntityKind.RECURRENCE]
        assert len(rec_spans) == 1


# ===========================================================================
# Voice dictation date phrases
# ===========================================================================


class TestVoiceDatePhrases:
    """Date patterns commonly produced by voice dictation."""

    def test_this_friday(self) -> None:
        # TODAY is Wednesday 2026-03-11 → this Friday = 2026-03-13
        r = parse("Meeting this Friday", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_this_coming_monday(self) -> None:
        # TODAY is Wednesday → this coming Monday = 2026-03-16
        r = parse("Call dentist this coming Monday", today=TODAY)
        assert r.due_date == date(2026, 3, 16)

    def test_this_weekend(self) -> None:
        # TODAY is Wednesday → this weekend = Saturday 2026-03-14
        r = parse("Clean house this weekend", today=TODAY)
        assert r.due_date == date(2026, 3, 14)

    def test_day_after_tomorrow(self) -> None:
        r = parse("Submit report day after tomorrow", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_end_of_week(self) -> None:
        # TODAY is Wednesday → end of week = Friday 2026-03-13
        r = parse("Finish docs end of week", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_end_of_the_week(self) -> None:
        r = parse("Review PR end of the week", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_end_of_month(self) -> None:
        r = parse("Pay rent end of month", today=TODAY)
        assert r.due_date == date(2026, 3, 31)

    def test_end_of_the_month(self) -> None:
        r = parse("File taxes end of the month", today=TODAY)
        assert r.due_date == date(2026, 3, 31)

    def test_in_a_day(self) -> None:
        r = parse("Reply to email in a day", today=TODAY)
        assert r.due_date == date(2026, 3, 12)

    def test_in_a_week(self) -> None:
        r = parse("Follow up in a week", today=TODAY)
        assert r.due_date == date(2026, 3, 18)

    def test_in_a_month(self) -> None:
        r = parse("Renew subscription in a month", today=TODAY)
        assert r.due_date == date(2026, 4, 11)

    def test_in_a_couple_days(self) -> None:
        r = parse("Buy gift in a couple days", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_in_a_few_days(self) -> None:
        r = parse("Schedule call in a few days", today=TODAY)
        assert r.due_date == date(2026, 3, 14)

    def test_the_15th(self) -> None:
        r = parse("Meeting the 15th", today=TODAY)
        assert r.due_date == date(2026, 3, 15)

    def test_the_15th_past(self) -> None:
        # If the 10th has passed, should go to next month
        r = parse("Meeting the 10th", today=TODAY)
        assert r.due_date == date(2026, 4, 10)

    def test_the_3rd_of_april(self) -> None:
        r = parse("Conference the 3rd of April", today=TODAY)
        assert r.due_date == date(2026, 4, 3)


# ===========================================================================
# Voice dictation time phrases
# ===========================================================================


class TestVoiceTimePhrases:
    """Time patterns commonly produced by voice dictation."""

    def test_bare_3_pm(self) -> None:
        r = parse("Meeting 3 PM", today=TODAY)
        assert r.due_time == time(15, 0)

    def test_bare_10_am(self) -> None:
        r = parse("Call at 10 AM", today=TODAY)
        assert r.due_time == time(10, 0)

    def test_bare_330_pm(self) -> None:
        r = parse("Dentist 3:30 PM", today=TODAY)
        assert r.due_time == time(15, 30)

    def test_tonight(self) -> None:
        r = parse("Take out trash tonight", today=TODAY)
        assert r.due_time == time(20, 0)

    def test_this_morning(self) -> None:
        r = parse("Review emails this morning", today=TODAY)
        assert r.due_time == time(9, 0)

    def test_this_afternoon(self) -> None:
        r = parse("Pick up groceries this afternoon", today=TODAY)
        assert r.due_time == time(14, 0)

    def test_this_evening(self) -> None:
        r = parse("Cook dinner this evening", today=TODAY)
        assert r.due_time == time(18, 0)

    def test_before_5(self) -> None:
        r = parse("Submit form before 5 PM", today=TODAY)
        assert r.due_time == time(17, 0)

    def test_in_30_minutes(self) -> None:
        r = parse("Check oven in 30 minutes", today=TODAY)
        assert r.due_time is not None  # Can't assert exact time (depends on now)

    def test_in_2_hours(self) -> None:
        r = parse("Call back in 2 hours", today=TODAY)
        assert r.due_time is not None

    def test_in_an_hour(self) -> None:
        r = parse("Review document in an hour", today=TODAY)
        assert r.due_time is not None


# ===========================================================================
# Number word conversion
# ===========================================================================


class TestNumberWordConversion:
    """Voice dictation often spells out numbers."""

    def test_in_two_days(self) -> None:
        r = parse("Buy present in two days", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_every_three_weeks(self) -> None:
        r = parse("Review accounts every three weeks", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert r.recurrence_interval == 3

    def test_in_five_days(self) -> None:
        r = parse("Follow up in five days", today=TODAY)
        assert r.due_date == date(2026, 3, 16)

    def test_a_couple_of_days(self) -> None:
        r = parse("Fix bug in a couple of days", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_buy_two_apples_not_converted(self) -> None:
        """Number words in non-pattern contexts stay as text."""
        r = parse("Buy two apples", today=TODAY)
        assert "two" in r.reminder.lower() or "2" not in r.reminder

    def test_priority_one(self) -> None:
        r = parse("Fix server priority one", today=TODAY)
        assert r.priority == 1

    def test_priority_three(self) -> None:
        r = parse("Clean desk priority three", today=TODAY)
        assert r.priority == 3


# ===========================================================================
# Compound recurrence patterns
# ===========================================================================


class TestCompoundRecurrence:
    """Complex recurrence patterns for voice dictation."""

    def test_every_other_day(self) -> None:
        r = parse("Water plants every other day", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_interval == 2

    def test_every_other_week(self) -> None:
        r = parse("Team sync every other week", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert r.recurrence_interval == 2

    def test_every_other_month(self) -> None:
        r = parse("Haircut every other month", today=TODAY)
        assert r.recurrence_type == "monthly"
        assert r.recurrence_interval == 2

    def test_biweekly(self) -> None:
        r = parse("Payroll biweekly", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert r.recurrence_interval == 2

    def test_bi_weekly_hyphen(self) -> None:
        r = parse("Review bi-weekly", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert r.recurrence_interval == 2

    def test_bimonthly(self) -> None:
        r = parse("Newsletter bimonthly", today=TODAY)
        assert r.recurrence_type == "monthly"
        assert r.recurrence_interval == 2

    def test_twice_a_day(self) -> None:
        r = parse("Take medicine twice a day", today=TODAY)
        assert r.recurrence_type == "daily"
        assert "(2x/day)" in r.reminder

    def test_twice_a_week(self) -> None:
        r = parse("Exercise twice a week", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert "(2x/week)" in r.reminder

    def test_every_weekday(self) -> None:
        r = parse("Check email every weekday", today=TODAY)
        assert r.recurrence_type == "daily"

    def test_every_morning(self) -> None:
        r = parse("Meditate every morning", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.due_time == time(9, 0)

    def test_every_night(self) -> None:
        r = parse("Journal every night", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.due_time == time(21, 0)

    def test_every_evening(self) -> None:
        r = parse("Walk dog every evening", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.due_time == time(18, 0)


# ===========================================================================
# Voice priority phrases
# ===========================================================================


class TestVoicePriority:
    """Priority patterns commonly produced by voice dictation."""

    def test_important(self) -> None:
        r = parse("Fix login bug important", today=TODAY)
        assert r.priority == 1

    def test_not_important(self) -> None:
        r = parse("Organize bookmarks not important", today=TODAY)
        assert r.priority == 3

    def test_asap(self) -> None:
        r = parse("Deploy hotfix asap", today=TODAY)
        assert r.priority == 1

    def test_high_importance(self) -> None:
        r = parse("Client meeting high importance", today=TODAY)
        assert r.priority == 1


# ===========================================================================
# Full voice dictation sentences
# ===========================================================================


class TestVoiceDictationIntegration:
    """Full sentences as they might come from voice dictation."""

    def test_pick_up_groceries_this_afternoon(self) -> None:
        r = parse("Pick up groceries this afternoon", today=TODAY)
        assert "Pick up groceries" in r.reminder
        assert r.due_time == time(14, 0)

    def test_call_dentist_tomorrow_morning(self) -> None:
        r = parse("Call dentist tomorrow morning", today=TODAY)
        assert "Call dentist" in r.reminder
        assert r.due_date == date(2026, 3, 12)
        assert r.due_time == time(9, 0)

    def test_submit_report_end_of_week_important(self) -> None:
        r = parse("Submit report by end of week important", today=TODAY)
        assert "Submit report" in r.reminder
        assert r.due_date == date(2026, 3, 13)
        assert r.priority == 1

    def test_take_medicine_every_other_day_8am(self) -> None:
        r = parse("Take medicine every other day at 8 AM", today=TODAY)
        assert "Take medicine" in r.reminder
        assert r.recurrence_type == "daily"
        assert r.recurrence_interval == 2
        assert r.due_time == time(8, 0)

    def test_review_pull_requests_twice_a_week(self) -> None:
        r = parse("Review pull requests twice a week", today=TODAY)
        assert r.recurrence_type == "weekly"

    def test_buy_birthday_present_couple_days(self) -> None:
        r = parse("Buy birthday present in a couple days", today=TODAY)
        assert r.due_date == date(2026, 3, 13)

    def test_schedule_meeting_the_15th_3pm(self) -> None:
        r = parse("Schedule meeting the 15th 3 PM", today=TODAY)
        assert r.due_date == date(2026, 3, 15)
        assert r.due_time == time(15, 0)

    def test_water_plants_every_morning(self) -> None:
        r = parse("Water plants every morning", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.due_time == time(9, 0)

    def test_finish_presentation_this_friday_asap(self) -> None:
        r = parse("Finish presentation this Friday asap", today=TODAY)
        assert r.due_date == date(2026, 3, 13)
        assert r.priority == 1

    def test_every_three_days_for_two_weeks(self) -> None:
        r = parse("Check plants every three days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_interval == 3


# ---------------------------------------------------------------------------
# TestFuzzyMatching — typos, misspellings, abbreviations
# ---------------------------------------------------------------------------


class TestFuzzyMatching:
    """Tests for fuzzy matching capabilities (new in intent-based parser)."""

    def test_importnt_matches_important(self) -> None:
        r = parse("Fix bug importnt", today=TODAY)
        assert r.priority == 1

    def test_urgnt_matches_urgent(self) -> None:
        r = parse("Deploy patch urgnt", today=TODAY)
        assert r.priority == 1

    def test_daly_matches_daily(self) -> None:
        r = parse("Stand up daly", today=TODAY)
        assert r.recurrence_type == "daily"

    def test_weeky_matches_weekly(self) -> None:
        r = parse("Sync meeting weeky", today=TODAY)
        assert r.recurrence_type == "weekly"

    def test_montly_matches_monthly(self) -> None:
        r = parse("Review budget montly", today=TODAY)
        assert r.recurrence_type == "monthly"

    def test_sesions_matches_sessions(self) -> None:
        r = parse("Study math ~3 sesions", today=TODAY)
        assert r.pomodoro_estimate == 3

    def test_pomdoro_matches_pomodoro(self) -> None:
        r = parse("Deep work ~2 pomdoro", today=TODAY)
        assert r.pomodoro_estimate == 2

    def test_fuzzy_no_false_positive_short_word(self) -> None:
        """Short tokens (< 4 chars) should never fuzzy match."""
        r = parse("Do the big task", today=TODAY)
        assert r.priority is None  # "big" should not match anything

    def test_fuzzy_no_false_positive_parenthetical(self) -> None:
        """Tokens with non-alpha chars should not fuzzy match."""
        r = parse("Fix (critical) bug", today=TODAY)
        assert r.priority is None
        assert "(critical)" in r.reminder


# ---------------------------------------------------------------------------
# TestConfidenceScoring
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    """Tests for confidence values on fuzzy-matched EntitySpans."""

    def test_exact_match_confidence_1(self) -> None:
        r = parse("Task important", today=TODAY)
        priority_spans = [s for s in r.spans if s.kind == EntityKind.PRIORITY]
        assert len(priority_spans) == 1
        assert priority_spans[0].confidence == 1.0

    def test_fuzzy_match_confidence_below_1(self) -> None:
        r = parse("Task importnt", today=TODAY)
        priority_spans = [s for s in r.spans if s.kind == EntityKind.PRIORITY]
        assert len(priority_spans) == 1
        assert 0.80 <= priority_spans[0].confidence < 1.0

    def test_fuzzy_match_has_matched_field(self) -> None:
        r = parse("Task importnt", today=TODAY)
        priority_spans = [s for s in r.spans if s.kind == EntityKind.PRIORITY]
        assert len(priority_spans) == 1
        assert priority_spans[0].matched == "important"

    def test_exact_match_matched_field_empty(self) -> None:
        r = parse("Task important", today=TODAY)
        priority_spans = [s for s in r.spans if s.kind == EntityKind.PRIORITY]
        assert len(priority_spans) == 1
        assert priority_spans[0].matched == ""

    def test_fuzzy_recurrence_confidence(self) -> None:
        r = parse("Do task weeky", today=TODAY)
        rec_spans = [s for s in r.spans if s.kind == EntityKind.RECURRENCE]
        assert len(rec_spans) == 1
        assert 0.80 <= rec_spans[0].confidence < 1.0
        assert rec_spans[0].matched == "weekly"


# ---------------------------------------------------------------------------
# TestEstimatedMinutes — ~90m, ~2h, ~1h30m
# ---------------------------------------------------------------------------


class TestEstimatedMinutes:
    """Tests for estimated time parsing (~Nm, ~Nh patterns)."""

    def test_tilde_90m(self) -> None:
        r = parse("Write report ~90m", today=TODAY)
        assert r.estimated_minutes == 90

    def test_tilde_2h(self) -> None:
        r = parse("Code review ~2h", today=TODAY)
        assert r.estimated_minutes == 120

    def test_tilde_1h30m(self) -> None:
        r = parse("Workshop ~1h30m", today=TODAY)
        assert r.estimated_minutes == 90

    def test_estimate_span_kind(self) -> None:
        r = parse("Task ~45m", today=TODAY)
        est_spans = [s for s in r.spans if s.kind == EntityKind.ESTIMATE]
        assert len(est_spans) == 1
        assert "45" in est_spans[0].display

    def test_estimate_with_other_entities(self) -> None:
        r = parse("Fix bug tomorrow ~2h p1", today=TODAY)
        assert r.estimated_minutes == 120
        assert r.priority == 1
        assert r.due_date == date(2026, 3, 12)

    def test_tilde_pomodoro_not_estimate(self) -> None:
        """~N sessions should be pomodoro, not estimate."""
        r = parse("Study ~3 sessions", today=TODAY)
        assert r.pomodoro_estimate == 3
        assert r.estimated_minutes is None or r.estimated_minutes == 0

    # -- Extended duration units (days, weeks, months, years) --

    def test_about_three_days(self) -> None:
        r = parse("task about three days", today=TODAY)
        assert r.estimated_minutes == 3 * 1440

    def test_roughly_two_weeks(self) -> None:
        r = parse("project roughly two weeks", today=TODAY)
        assert r.estimated_minutes == 2 * 10080

    def test_approximately_four_months(self) -> None:
        r = parse("task approximately four months", today=TODAY)
        assert r.estimated_minutes == 4 * 43200

    def test_will_take_a_year(self) -> None:
        r = parse("this will take a year", today=TODAY)
        assert r.estimated_minutes == 525600

    def test_tilde_3d(self) -> None:
        r = parse("task ~3d", today=TODAY)
        assert r.estimated_minutes == 3 * 1440

    def test_tilde_2w(self) -> None:
        r = parse("project ~2w", today=TODAY)
        assert r.estimated_minutes == 2 * 10080

    def test_display_natural_scale_days(self) -> None:
        r = parse("task about three days", today=TODAY)
        est_spans = [s for s in r.spans if s.kind == EntityKind.ESTIMATE]
        assert len(est_spans) == 1
        assert "3d" in est_spans[0].display

    def test_display_natural_scale_weeks(self) -> None:
        r = parse("project roughly two weeks", today=TODAY)
        est_spans = [s for s in r.spans if s.kind == EntityKind.ESTIMATE]
        assert len(est_spans) == 1
        assert "2w" in est_spans[0].display

    def test_display_natural_scale_months(self) -> None:
        r = parse("task approximately four months", today=TODAY)
        est_spans = [s for s in r.spans if s.kind == EntityKind.ESTIMATE]
        assert len(est_spans) == 1
        assert "4mo" in est_spans[0].display


# ---------------------------------------------------------------------------
# TestFormatDuration
# ---------------------------------------------------------------------------


class TestFormatDuration:
    """Unit tests for format_duration utility."""

    def test_minutes(self) -> None:
        from pytodo_qt.core.models import format_duration

        assert format_duration(30) == "~30m"

    def test_hours(self) -> None:
        from pytodo_qt.core.models import format_duration

        assert format_duration(120) == "~2h"

    def test_hours_and_minutes(self) -> None:
        from pytodo_qt.core.models import format_duration

        assert format_duration(90) == "~1h 30m"

    def test_days(self) -> None:
        from pytodo_qt.core.models import format_duration

        assert format_duration(1440) == "~1d"

    def test_days_and_hours(self) -> None:
        from pytodo_qt.core.models import format_duration

        assert format_duration(1440 + 120) == "~1d 2h"

    def test_weeks(self) -> None:
        from pytodo_qt.core.models import format_duration

        assert format_duration(10080) == "~1w"

    def test_months(self) -> None:
        from pytodo_qt.core.models import format_duration

        assert format_duration(43200) == "~1mo"

    def test_years(self) -> None:
        from pytodo_qt.core.models import format_duration

        assert format_duration(525600) == "~1y"


# ---------------------------------------------------------------------------
# TestWorkDuration — "session length N minutes"
# ---------------------------------------------------------------------------


class TestWorkDuration:
    """Tests for per-task work duration parsing."""

    def test_session_length_50_minutes(self) -> None:
        r = parse("Deep focus session length 50 minutes", today=TODAY)
        assert r.work_duration == 50

    def test_session_length_45_min(self) -> None:
        r = parse("Study session length 45 min", today=TODAY)
        assert r.work_duration == 45

    def test_work_duration_span_kind(self) -> None:
        r = parse("Task session length 30 minutes", today=TODAY)
        wd_spans = [s for s in r.spans if s.kind == EntityKind.WORK_DURATION]
        assert len(wd_spans) == 1


# ---------------------------------------------------------------------------
# TestAbbreviations — common shorthand
# ---------------------------------------------------------------------------


class TestAbbreviations:
    """Tests for abbreviation handling."""

    def test_tmrw_tomorrow(self) -> None:
        r = parse("Call dentist tmrw", today=TODAY)
        assert r.due_date == date(2026, 3, 12)

    def test_tom_tomorrow(self) -> None:
        r = parse("Buy groceries tom", today=TODAY)
        assert r.due_date == date(2026, 3, 12)

    def test_p1_priority(self) -> None:
        r = parse("Fix crash p1", today=TODAY)
        assert r.priority == 1

    def test_p2_priority(self) -> None:
        r = parse("Update docs p2", today=TODAY)
        assert r.priority == 2

    def test_p3_priority(self) -> None:
        r = parse("Clean up code p3", today=TODAY)
        assert r.priority == 3


# ---------------------------------------------------------------------------
# TestDurationRecurrence — "over/for the next N days/weeks"
# ---------------------------------------------------------------------------


class TestDurationRecurrence:
    """Tests for duration-based recurrence: 'over the next N days'."""

    def test_over_the_next_10_days(self) -> None:
        r = parse("Practice piano over the next 10 days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_interval == 1
        assert r.recurrence_end_count == 10

    def test_for_the_next_2_weeks(self) -> None:
        r = parse("Take medicine for the next 2 weeks", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert r.recurrence_interval == 1
        assert r.recurrence_end_count == 2

    def test_over_the_next_3_months(self) -> None:
        r = parse("Review budget over the next 3 months", today=TODAY)
        assert r.recurrence_type == "monthly"
        assert r.recurrence_end_count == 3

    def test_duration_recurrence_implies_today(self) -> None:
        r = parse("Study over the next 5 days", today=TODAY)
        assert r.due_date == TODAY

    def test_duration_with_priority(self) -> None:
        r = parse("Test NLP over the next 10 days as high priority", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 10
        assert r.priority == 1

    def test_duration_with_tags(self) -> None:
        r = parse("Study @math over the next 5 days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 5
        assert "@math" in r.tags

    def test_for_5_days_standalone(self) -> None:
        """'for N days' without explicit recurrence type implies daily."""
        r = parse("Practice piano for 5 days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 5
        assert r.due_date == TODAY

    def test_for_3_weeks_standalone(self) -> None:
        r = parse("Take medicine for 3 weeks", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert r.recurrence_end_count == 3

    def test_for_2_months_standalone(self) -> None:
        r = parse("Review budget for 2 months", today=TODAY)
        assert r.recurrence_type == "monthly"
        assert r.recurrence_end_count == 2

    def test_daily_for_5_days_suffix(self) -> None:
        """'daily for 5 days' — explicit type + suffix."""
        r = parse("Study daily for 5 days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 5

    def test_over_a_few_days(self) -> None:
        r = parse("Test nlp over a few days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 3

    def test_for_a_few_days(self) -> None:
        r = parse("Practice piano for a few days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 3

    def test_for_a_couple_of_weeks(self) -> None:
        r = parse("Take medicine for a couple of weeks", today=TODAY)
        assert r.recurrence_type == "weekly"
        assert r.recurrence_end_count == 2

    def test_for_a_period_of_a_few_days(self) -> None:
        r = parse("Study for a period of a few days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 3

    def test_for_several_months(self) -> None:
        r = parse("Review budget for several months", today=TODAY)
        assert r.recurrence_type == "monthly"
        assert r.recurrence_end_count == 5

    def test_over_the_next_couple_days(self) -> None:
        r = parse("Clean house over the next couple days", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 2

    def test_until_3_days_is_over(self) -> None:
        r = parse("Practice until 3 days is over", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 3

    def test_until_five_days_is_done(self) -> None:
        r = parse("Study until five days is done", today=TODAY)
        assert r.recurrence_type == "daily"
        assert r.recurrence_end_count == 5


# ---------------------------------------------------------------------------
# TestApproximationSynonyms
# ---------------------------------------------------------------------------


class TestApproximationSynonyms:
    """Approximation prefixes work as synonyms for ~ in estimates and pomodoro."""

    def test_approximately_4_hours(self) -> None:
        r = parse("Task approximately 4 hours", today=TODAY)
        assert r.estimated_minutes == 240

    def test_about_2_hours(self) -> None:
        r = parse("Task about 2 hours", today=TODAY)
        assert r.estimated_minutes == 120

    def test_around_90_minutes(self) -> None:
        r = parse("Task around 90 minutes", today=TODAY)
        assert r.estimated_minutes == 90

    def test_roughly_two_hours(self) -> None:
        r = parse("Task roughly two hours", today=TODAY)
        assert r.estimated_minutes == 120

    def test_tilde_two_token_estimate(self) -> None:
        """~2 hr (space between number and unit) is estimated_minutes, not pomodoro."""
        r = parse("Task ~2 hr", today=TODAY)
        assert r.estimated_minutes == 120
        assert r.pomodoro_estimate is None

    def test_approx_3_sessions(self) -> None:
        r = parse("Task approx 3 sessions", today=TODAY)
        assert r.pomodoro_estimate == 3

    def test_about_two_pom(self) -> None:
        r = parse("Task about two pom", today=TODAY)
        assert r.pomodoro_estimate == 2

    def test_number_word_parity_estimate(self) -> None:
        """'approximately two hours' == 'approximately 2 hours'."""
        r1 = parse("Task approximately two hours", today=TODAY)
        r2 = parse("Task approximately 2 hours", today=TODAY)
        assert r1.estimated_minutes == r2.estimated_minutes == 120

    def test_number_word_parity_pomodoro(self) -> None:
        """'about three sessions' == 'about 3 sessions'."""
        r1 = parse("Task about three sessions", today=TODAY)
        r2 = parse("Task about 3 sessions", today=TODAY)
        assert r1.pomodoro_estimate == r2.pomodoro_estimate == 3

    def test_about_hours_not_recurrence(self) -> None:
        """'about 4 hours' is a time estimate, not minutely recurrence."""
        r = parse("Task about 4 hours", today=TODAY)
        assert r.estimated_minutes == 240
        assert r.recurrence_type is None


# ---------------------------------------------------------------------------
# TestTimeRanges
# ---------------------------------------------------------------------------


class TestTimeRanges:
    """Ad-hoc time range extraction — due_time + due_time_end."""

    # -- Opener patterns --

    def test_between_and_with_pm(self) -> None:
        r = parse("call between three and five pm", today=TODAY)
        assert r.due_time == time(15, 0)
        assert r.due_time_end == time(17, 0)
        assert "call" in r.reminder.lower()

    def test_between_and_with_am(self) -> None:
        r = parse("jog between six and seven am", today=TODAY)
        assert r.due_time == time(6, 0)
        assert r.due_time_end == time(7, 0)

    def test_from_to_with_pm(self) -> None:
        r = parse("meeting from 2 to 4 pm", today=TODAY)
        assert r.due_time == time(14, 0)
        assert r.due_time_end == time(16, 0)

    def test_from_through(self) -> None:
        r = parse("study from nine through eleven", today=TODAY)
        assert r.due_time == time(9, 0)
        assert r.due_time_end == time(11, 0)

    def test_from_till(self) -> None:
        r = parse("practice from two till four pm", today=TODAY)
        assert r.due_time == time(14, 0)
        assert r.due_time_end == time(16, 0)

    def test_from_to_crossing_noon(self) -> None:
        """Range crossing AM→PM with explicit PM on end."""
        r = parse("work from 10 to 2 pm", today=TODAY)
        assert r.due_time == time(10, 0)
        assert r.due_time_end == time(14, 0)

    # -- Bare connector patterns --

    def test_bare_to_digits(self) -> None:
        r = parse("call 3 to 5", today=TODAY)
        assert r.due_time == time(15, 0)
        assert r.due_time_end == time(17, 0)

    def test_bare_till_words_with_pm(self) -> None:
        r = parse("focus block six till eight pm", today=TODAY)
        assert r.due_time == time(18, 0)
        assert r.due_time_end == time(20, 0)

    def test_bare_through_words(self) -> None:
        r = parse("read ten through twelve", today=TODAY)
        assert r.due_time == time(10, 0)
        assert r.due_time_end == time(12, 0)

    # -- Dash pattern --

    def test_dash_with_pm(self) -> None:
        r = parse("meeting 2-4 pm", today=TODAY)
        assert r.due_time == time(14, 0)
        assert r.due_time_end == time(16, 0)

    def test_dash_with_am(self) -> None:
        r = parse("run 6-7 am", today=TODAY)
        assert r.due_time == time(6, 0)
        assert r.due_time_end == time(7, 0)

    def test_dash_no_ampm(self) -> None:
        r = parse("meeting 9-11", today=TODAY)
        assert r.due_time == time(9, 0)
        assert r.due_time_end == time(11, 0)

    # -- AM/PM propagation --

    def test_ampm_propagates_to_both(self) -> None:
        """Single am/pm after end time applies to both endpoints."""
        r = parse("between 1 and 3 pm", today=TODAY)
        assert r.due_time == time(13, 0)
        assert r.due_time_end == time(15, 0)

    def test_no_ampm_small_numbers_assume_pm(self) -> None:
        """Numbers 1-6 without am/pm context default to PM."""
        r = parse("available 2 to 4", today=TODAY)
        assert r.due_time == time(14, 0)
        assert r.due_time_end == time(16, 0)

    def test_no_ampm_large_numbers_stay_am(self) -> None:
        """Numbers 7-12 without context stay as-is (AM)."""
        r = parse("available 9 to 11", today=TODAY)
        assert r.due_time == time(9, 0)
        assert r.due_time_end == time(11, 0)

    # -- Context from time-of-day words --

    def test_morning_context_forces_am(self) -> None:
        r = parse("morning between nine and eleven", today=TODAY)
        assert r.due_time == time(9, 0)
        assert r.due_time_end == time(11, 0)

    def test_evening_context_forces_pm(self) -> None:
        r = parse("evening from five to seven", today=TODAY)
        assert r.due_time == time(17, 0)
        assert r.due_time_end == time(19, 0)

    # -- Colon-form endpoints --

    def test_colon_form_range(self) -> None:
        r = parse("from 9:30 to 11:00", today=TODAY)
        assert r.due_time == time(9, 30)
        assert r.due_time_end == time(11, 0)

    # -- No range → due_time_end stays None --

    def test_single_time_no_range(self) -> None:
        r = parse("call at 3pm", today=TODAY)
        assert r.due_time == time(15, 0)
        assert r.due_time_end is None

    # -- Reminder preservation --

    def test_reminder_preserved_with_range(self) -> None:
        r = parse("dentist appointment from 2 to 4 pm", today=TODAY)
        assert "dentist appointment" in r.reminder.lower()
        assert r.due_time == time(14, 0)
        assert r.due_time_end == time(16, 0)

    # -- "after" as time prefix --

    def test_after_time_prefix(self) -> None:
        r = parse("clean up after 5pm", today=TODAY)
        assert r.due_time == time(17, 0)
        assert r.due_time_end is None
        assert "clean up" in r.reminder.lower()


# ---------------------------------------------------------------------------
# TestNow
# ---------------------------------------------------------------------------


class TestNow:
    """'now' and 'right now' as dynamic current-time values."""

    def test_now_standalone(self) -> None:
        r = parse("start working now", today=TODAY)
        assert r.due_time is not None
        assert r.due_date == TODAY
        assert "start working" in r.reminder.lower()

    def test_right_now(self) -> None:
        r = parse("call boss right now", today=TODAY)
        assert r.due_time is not None
        assert r.due_date == TODAY
        assert "call boss" in r.reminder.lower()

    def test_now_in_range(self) -> None:
        """'from now to 5 pm' sets both due_time and due_time_end."""
        r = parse("from now to 5 pm", today=TODAY)
        assert r.due_time is not None
        assert r.due_time_end == time(17, 0)

    def test_now_does_not_override_explicit_time(self) -> None:
        """Explicit time takes precedence — 'now' is ignored."""
        r = parse("call at 3pm now", today=TODAY)
        assert r.due_time == time(15, 0)

    def test_no_now_means_no_time(self) -> None:
        r = parse("buy groceries", today=TODAY)
        assert r.due_time is None


# ---------------------------------------------------------------------------
# TestEventDate
# ---------------------------------------------------------------------------


class TestEventDate:
    """Event date extraction from scheduling verb + 'for' + date."""

    def test_schedule_for_next_month(self) -> None:
        r = parse("schedule dentist for next month", today=TODAY)
        assert r.event_date is not None
        assert r.event_date.month == (TODAY.month % 12) + 1
        assert "dentist" in r.reminder.lower()

    def test_book_for_friday(self) -> None:
        r = parse("book appointment for friday", today=TODAY)
        assert r.event_date is not None
        assert "appointment" in r.reminder.lower()

    def test_reserve_for_next_week(self) -> None:
        r = parse("reserve table for next week", today=TODAY)
        assert r.event_date is not None
        assert "table" in r.reminder.lower()

    def test_plan_for_tomorrow(self) -> None:
        r = parse("plan meeting for tomorrow", today=TODAY)
        assert r.event_date is not None
        assert r.event_date == TODAY + __import__("datetime").timedelta(days=1)

    def test_no_scheduling_verb_no_event_date(self) -> None:
        """'for' without a scheduling verb is not an event date trigger."""
        r = parse("study for the exam", today=TODAY)
        assert r.event_date is None

    def test_event_date_with_separate_due_date(self) -> None:
        """Scheduling verb claims 'for' as event_date; other dates become due_date."""
        r = parse("schedule dentist for next month before the twentieth", today=TODAY)
        assert r.event_date is not None
        assert r.due_date is not None
        assert r.due_date.day == 20


# ---------------------------------------------------------------------------
# TestConditions
# ---------------------------------------------------------------------------


class TestConditions:
    """Conditional expression extraction."""

    def test_if_condition(self) -> None:
        r = parse("book hotel if calendar is open", today=TODAY)
        assert len(r.conditions) >= 1
        assert r.conditions[0]["type"] == "if"
        assert "calendar" in r.conditions[0]["expression"]

    def test_unless_condition(self) -> None:
        r = parse("go running unless it rains", today=TODAY)
        assert len(r.conditions) >= 1
        assert r.conditions[0]["type"] == "unless"
        assert "rains" in r.conditions[0]["expression"]

    def test_otherwise_fallback(self) -> None:
        r = parse("eat lunch at the cafe otherwise at home", today=TODAY)
        assert len(r.conditions) >= 1
        assert r.conditions[0]["type"] == "fallback"
        assert "home" in r.conditions[0]["expression"]

    def test_when_condition(self) -> None:
        r = parse("deploy when tests pass", today=TODAY)
        assert len(r.conditions) >= 1
        assert r.conditions[0]["type"] == "when"
        assert "tests pass" in r.conditions[0]["expression"]

    def test_no_condition_no_keyword(self) -> None:
        r = parse("buy groceries tomorrow", today=TODAY)
        assert len(r.conditions) == 0

    def test_condition_removed_from_reminder(self) -> None:
        """Condition keyword + expression should not appear in reminder."""
        r = parse("submit report otherwise email it", today=TODAY)
        assert "otherwise" not in r.reminder.lower()
        assert "email" not in r.reminder.lower()


# ---------------------------------------------------------------------------
# TestSubtaskExtraction
# ---------------------------------------------------------------------------


class TestSubtaskExtraction:
    """Inline subtask creation from delimiter patterns."""

    # -- Colon delimiter --

    def test_colon_basic(self) -> None:
        r = parse("buy groceries: milk, bread, eggs", today=TODAY)
        assert r.reminder == "buy groceries"
        assert r.subtask_reminders == ["milk", "bread", "eggs"]

    def test_colon_oxford_comma(self) -> None:
        r = parse("buy groceries: milk, bread, and eggs", today=TODAY)
        assert r.subtask_reminders == ["milk", "bread", "eggs"]

    def test_colon_and_connector(self) -> None:
        r = parse("pack: clothes, charger and passport", today=TODAY)
        assert r.subtask_reminders == ["clothes", "charger", "passport"]

    def test_colon_single_item(self) -> None:
        r = parse("errand: pick up dry cleaning", today=TODAY)
        assert r.reminder == "errand"
        assert r.subtask_reminders == ["pick up dry cleaning"]

    # -- "with tasks" / "with subtasks" delimiter --

    def test_with_tasks(self) -> None:
        r = parse("project X with tasks design, implement, test", today=TODAY)
        assert r.reminder == "project X"
        assert r.subtask_reminders == ["design", "implement", "test"]

    def test_with_subtasks(self) -> None:
        r = parse("launch plan with subtasks research, draft, review", today=TODAY)
        assert r.reminder == "launch plan"
        assert r.subtask_reminders == ["research", "draft", "review"]

    # -- "including" delimiter --

    def test_including(self) -> None:
        r = parse("meeting prep including slides, handouts, agenda", today=TODAY)
        assert r.reminder == "meeting prep"
        assert r.subtask_reminders == ["slides", "handouts", "agenda"]

    # -- No subtasks --

    def test_no_delimiter_no_subtasks(self) -> None:
        r = parse("buy groceries tomorrow", today=TODAY)
        assert r.subtask_reminders == []

    def test_colon_no_items(self) -> None:
        """Colon at end with no items should not create empty subtasks."""
        r = parse("note:", today=TODAY)
        assert r.subtask_reminders == []

    # -- Metadata preserved alongside subtasks --

    def test_metadata_with_subtasks(self) -> None:
        r = parse("buy groceries tomorrow : milk, bread, eggs", today=TODAY)
        assert r.due_date is not None
        assert "groceries" in r.reminder.lower()
        assert r.subtask_reminders == ["milk", "bread", "eggs"]

    # -- Two-word "and" only (no commas) --

    def test_and_only(self) -> None:
        r = parse("errands: laundry and dishes", today=TODAY)
        assert r.subtask_reminders == ["laundry", "dishes"]


# ---------------------------------------------------------------------------
# replace_or_append_category helper — used by smart-add quick action buttons
# ---------------------------------------------------------------------------


class TestReplaceOrAppendCategory:
    """Pure text-mutation helper that replaces a span in the input
    with a new token, or appends if no such span exists. Exercised
    by AddTodoDialog's Priority / Date / Tag / Recurrence trigger
    buttons so the smart-add text stays in sync with the user's
    click-driven preset selections.
    """

    def test_replaces_existing_priority(self) -> None:
        from pytodo_qt.core.nlp_parser import replace_or_append_category

        text = "fix bug low priority tomorrow"
        result = parse(text, today=TODAY)
        new_text = replace_or_append_category(
            text, result.spans, EntityKind.PRIORITY, "high priority"
        )
        assert new_text == "fix bug high priority tomorrow"

    def test_appends_when_no_existing_priority(self) -> None:
        from pytodo_qt.core.nlp_parser import replace_or_append_category

        text = "fix bug"
        result = parse(text, today=TODAY)
        new_text = replace_or_append_category(
            text, result.spans, EntityKind.PRIORITY, "high priority"
        )
        assert new_text == "fix bug high priority"

    def test_replaces_existing_date(self) -> None:
        from pytodo_qt.core.nlp_parser import replace_or_append_category

        text = "call mom tomorrow"
        result = parse(text, today=TODAY)
        new_text = replace_or_append_category(text, result.spans, EntityKind.DATE, "next monday")
        assert new_text == "call mom next monday"

    def test_replaces_existing_recurrence(self) -> None:
        from pytodo_qt.core.nlp_parser import replace_or_append_category

        text = "standup daily"
        result = parse(text, today=TODAY)
        new_text = replace_or_append_category(text, result.spans, EntityKind.RECURRENCE, "weekly")
        assert new_text == "standup weekly"

    def test_append_only_mode_does_not_replace(self) -> None:
        """Tag mode: must append, not replace existing tags,
        because a task can have multiple tags."""
        from pytodo_qt.core.nlp_parser import replace_or_append_category

        text = "fix bug @work"
        result = parse(text, today=TODAY)
        new_text = replace_or_append_category(
            text, result.spans, EntityKind.TAG, "@urgent", append_only=True
        )
        assert new_text == "fix bug @work @urgent"

    def test_preserves_surrounding_reminder_text(self) -> None:
        from pytodo_qt.core.nlp_parser import replace_or_append_category

        text = "urgent fix report high priority friday"
        result = parse(text, today=TODAY)
        new_text = replace_or_append_category(
            text, result.spans, EntityKind.PRIORITY, "low priority"
        )
        assert "urgent" in new_text
        assert "low priority" in new_text
        assert "friday" in new_text
        assert "high priority" not in new_text

    def test_empty_text_append(self) -> None:
        from pytodo_qt.core.nlp_parser import replace_or_append_category

        new_text = replace_or_append_category("", [], EntityKind.PRIORITY, "high priority")
        assert new_text == "high priority"

    def test_trailing_space_append_does_not_double_space(self) -> None:
        from pytodo_qt.core.nlp_parser import replace_or_append_category

        new_text = replace_or_append_category("fix bug ", [], EntityKind.PRIORITY, "high priority")
        assert new_text == "fix bug high priority"


# ---------------------------------------------------------------------------
# TestFillerExtraction — connective / filler phrases removed from reminder
# ---------------------------------------------------------------------------


class TestFillerExtraction:
    """Filler phrases must be excluded from the reminder, with no false
    positives on legitimate reminder content (notably single particles
    like 'the', 'a', 'an' which are deliberately not in the dictionary).
    """

    def test_its_a_priority_pattern(self) -> None:
        # The case that motivated the redesign.
        result = parse("buy groceries @errands it's a high priority", today=TODAY)
        assert "it's a" not in result.reminder.lower()
        assert "buy groceries" in result.reminder.lower()
        assert result.priority == 1
        assert "@errands" in result.tags
        # Filler span emitted so the smart-input chip can render.
        filler_spans = [s for s in result.spans if s.kind == EntityKind.FILLER]
        assert any(s.display.lower() == "it's a" for s in filler_spans)

    def test_remind_me_to_prefix(self) -> None:
        result = parse("remind me to call mom tomorrow", today=TODAY)
        assert result.reminder == "call mom"
        assert any(
            s.kind == EntityKind.FILLER and s.display.lower() == "remind me to"
            for s in result.spans
        )

    def test_first_person_modal(self) -> None:
        result = parse("i need to pick up dry cleaning friday", today=TODAY)
        assert result.reminder == "pick up dry cleaning"
        assert any(
            s.kind == EntityKind.FILLER and s.display.lower() == "i need to" for s in result.spans
        )

    def test_dont_forget_to(self) -> None:
        result = parse("don't forget to feed the dog daily", today=TODAY)
        assert result.reminder == "feed the dog"
        assert result.recurrence_type == "daily"
        assert any(
            s.kind == EntityKind.FILLER and s.display.lower() == "don't forget to"
            for s in result.spans
        )

    def test_lets_prefix(self) -> None:
        result = parse("let's schedule a review next monday", today=TODAY)
        assert "let's" not in result.reminder.lower()
        # Verify the rest of the reminder survived.
        assert "schedule" in result.reminder
        assert "review" in result.reminder

    def test_we_need_to(self) -> None:
        result = parse("we need to plan vacation next month", today=TODAY)
        assert result.reminder == "plan vacation"

    def test_no_false_positive_on_the(self) -> None:
        # 'the' is intentionally NOT a filler — it's part of the reminder.
        result = parse("feed the dog", today=TODAY)
        assert result.reminder == "feed the dog"
        assert not any(s.kind == EntityKind.FILLER for s in result.spans)

    def test_no_false_positive_on_a(self) -> None:
        # 'a' alone is not a filler — single-particle handling is deferred.
        result = parse("buy a book", today=TODAY)
        assert "buy" in result.reminder
        assert "book" in result.reminder
        assert not any(s.kind == EntityKind.FILLER for s in result.spans)

    def test_no_filler_means_no_filler_span(self) -> None:
        result = parse("buy groceries tomorrow at 3pm", today=TODAY)
        assert not any(s.kind == EntityKind.FILLER for s in result.spans)

    def test_filler_inside_word_does_not_match(self) -> None:
        # A phrase like "i should" should not match inside 'fishing' or similar
        # word boundaries. Whole-word matching only.
        result = parse("go fishing tomorrow", today=TODAY)
        assert "fishing" in result.reminder
        assert not any(s.kind == EntityKind.FILLER for s in result.spans)

    def test_make_sure_to(self) -> None:
        result = parse("make sure to lock the door tonight", today=TODAY)
        assert "make sure to" not in result.reminder.lower()
        assert "lock the door" in result.reminder

    def test_filler_does_not_affect_other_extraction(self) -> None:
        # Adding filler in the middle of an entity-rich sentence must not
        # disturb date / time / priority / tag extraction.
        result = parse(
            "i need to finish the report by 5pm tomorrow @work p1",
            today=TODAY,
        )
        assert result.priority == 1
        assert result.due_time == time(17, 0)
        assert result.due_date is not None
        assert "@work" in result.tags
        assert "i need to" not in result.reminder.lower()
