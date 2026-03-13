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
