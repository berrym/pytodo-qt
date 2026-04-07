"""NLP Voice Dictation Corpus — Audit Tests.

Tests derived from docs/plans/nlp-voice-corpus.md.
Each test represents a realistic voice-dictation input and verifies
the parser produces the expected extraction.

Run with: QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/test_nlp_voice_corpus.py -v

The first run establishes the baseline: which entries pass and which fail.
Failures are the gap map — the work list for parser improvements.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from pytodo_qt.core.nlp_parser import parse

# Fixed "today" for deterministic results: Sunday, 2026-04-05
TODAY = date(2026, 4, 5)

# Helper dates
TOMORROW = TODAY + timedelta(days=1)  # Monday Apr 6
# Upcoming weekdays (first occurrence AFTER today, Sunday)
UPCOMING_MONDAY = date(2026, 4, 6)
UPCOMING_TUESDAY = date(2026, 4, 7)
UPCOMING_WEDNESDAY = date(2026, 4, 8)
UPCOMING_FRIDAY = date(2026, 4, 10)
UPCOMING_SATURDAY = date(2026, 4, 11)
# "Next" weekdays (following week = upcoming + 7)
NEXT_TUESDAY = UPCOMING_TUESDAY + timedelta(days=7)  # Apr 14
NEXT_FRIDAY = UPCOMING_FRIDAY + timedelta(days=7)  # Apr 17


# ===========================================================================
# A. Baseline Natural Captures
# ===========================================================================


class TestBaselineCaptures:
    """Section A: Standard task capture patterns."""

    def test_01_simple_reminder(self) -> None:
        r = parse("buy milk", today=TODAY)
        assert r.reminder == "buy milk"
        assert r.due_date is None

    def test_02_tomorrow(self) -> None:
        r = parse("call mom tomorrow", today=TODAY)
        assert "call mom" in r.reminder.lower()
        assert r.due_date == TOMORROW

    def test_03_by_friday(self) -> None:
        r = parse("finish report by friday", today=TODAY)
        assert "finish report" in r.reminder.lower()
        assert r.due_date == UPCOMING_FRIDAY

    def test_04_on_the_first(self) -> None:
        r = parse("pay rent on the first", today=TODAY)
        assert "pay rent" in r.reminder.lower()
        assert r.due_date is not None
        assert r.due_date.day == 1

    def test_05_at_five_pm(self) -> None:
        r = parse("walk the dog at five pm", today=TODAY)
        assert "walk the dog" in r.reminder.lower()
        assert r.due_time == time(17, 0)

    def test_06_high_priority(self) -> None:
        r = parse("high priority fix the bug", today=TODAY)
        assert "fix the bug" in r.reminder.lower()
        assert r.priority == 1  # high = 1

    def test_07_plain_reminder(self) -> None:
        r = parse("add groceries to the list", today=TODAY)
        assert "groceries" in r.reminder.lower()
        assert r.due_date is None
        assert r.priority is None

    def test_08_next_tuesday(self) -> None:
        r = parse("doctor appointment next tuesday", today=TODAY)
        assert "doctor appointment" in r.reminder.lower()
        assert r.due_date == NEXT_TUESDAY

    def test_09_daily_recurrence(self) -> None:
        r = parse("work out daily", today=TODAY)
        assert "work out" in r.reminder.lower()
        assert r.recurrence_type == "daily"

    def test_10_at_work_no_tag(self) -> None:
        r = parse("email boss at work", today=TODAY)
        # "at work" is a bare preposition — should NOT produce @work tag
        assert "at work" in r.reminder.lower()
        assert "@work" not in [t.lower() for t in r.tags]

    def test_11_april_fifteenth(self) -> None:
        r = parse("submit taxes by april fifteenth", today=TODAY)
        assert "submit taxes" in r.reminder.lower()
        assert r.due_date is not None
        assert r.due_date.month == 4
        assert r.due_date.day == 15

    def test_12_today(self) -> None:
        r = parse("review pull request today", today=TODAY)
        assert "review pull request" in r.reminder.lower()
        assert r.due_date == TODAY

    def test_13_schedule_for_next_month(self) -> None:
        # "for" after scheduling verb = target period, not recurrence duration.
        # Current parser may not have event_date yet — audit baseline.
        r = parse("schedule dentist for next month", today=TODAY)
        assert "schedule dentist" in r.reminder.lower()
        # Should NOT trigger daily recurrence for a month
        assert r.recurrence_type != "daily"

    def test_14_wednesday_night(self) -> None:
        r = parse("take out trash wednesday night", today=TODAY)
        assert "take out trash" in r.reminder.lower()
        assert r.due_date == UPCOMING_WEDNESDAY

    def test_15_thirty_minutes(self) -> None:
        r = parse("team meeting thirty minutes", today=TODAY)
        assert "team meeting" in r.reminder.lower()
        assert r.estimated_minutes == 30


# ===========================================================================
# B. Spelled-Out Times
# ===========================================================================


class TestSpelledOutTimes:
    """Section B: Speech-to-text renders times as words."""

    def test_16_two_thirty(self) -> None:
        r = parse("call dentist at two thirty", today=TODAY)
        assert "call dentist" in r.reminder.lower()
        assert r.due_time is not None
        assert r.due_time.hour in (14, 2)  # 2:30 or 14:30
        assert r.due_time.minute == 30

    def test_17_half_past_three(self) -> None:
        r = parse("meeting at half past three", today=TODAY)
        assert "meeting" in r.reminder.lower()
        assert r.due_time is not None
        assert r.due_time.minute == 30

    def test_18_quarter_to_four(self) -> None:
        r = parse("leave by quarter to four", today=TODAY)
        assert "leave" in r.reminder.lower()
        assert r.due_time is not None
        assert r.due_time.minute == 45

    def test_19_quarter_past_twelve(self) -> None:
        r = parse("lunch at quarter past twelve", today=TODAY)
        assert "lunch" in r.reminder.lower()
        assert r.due_time is not None
        assert r.due_time.hour == 12
        assert r.due_time.minute == 15

    def test_20_seven_fifteen_am(self) -> None:
        r = parse("wake up at seven fifteen am", today=TODAY)
        assert r.due_time is not None
        assert r.due_time.hour == 7
        assert r.due_time.minute == 15

    def test_21_eleven_oh_five(self) -> None:
        r = parse("flight at eleven oh five", today=TODAY)
        assert "flight" in r.reminder.lower()
        assert r.due_time is not None
        assert r.due_time.hour == 11
        assert r.due_time.minute == 5

    def test_22_three_forty_five(self) -> None:
        r = parse("pick up kids at three forty five", today=TODAY)
        assert r.due_time is not None
        assert r.due_time.minute == 45

    def test_23_at_eight(self) -> None:
        r = parse("breakfast at eight", today=TODAY)
        assert "breakfast" in r.reminder.lower()
        assert r.due_time is not None
        assert r.due_time.hour == 8

    def test_24_nine_a_m(self) -> None:
        r = parse("standup at nine a m", today=TODAY)
        assert r.due_time is not None
        assert r.due_time.hour == 9

    def test_25_six_thirty_pm(self) -> None:
        r = parse("dinner at six thirty pm", today=TODAY)
        assert r.due_time is not None
        assert r.due_time.hour == 18
        assert r.due_time.minute == 30


# ===========================================================================
# C. Compound Date+Time Phrases
# ===========================================================================


class TestCompoundDateTime:
    """Section C: Date and time combined in natural speech."""

    def test_26_tomorrow_at_three(self) -> None:
        r = parse("call mom tomorrow at three", today=TODAY)
        assert "call mom" in r.reminder.lower()
        assert r.due_date == TOMORROW
        assert r.due_time is not None
        assert r.due_time.hour in (3, 15)

    def test_27_next_friday_at_ten_thirty(self) -> None:
        r = parse("meeting next friday at ten thirty", today=TODAY)
        assert "meeting" in r.reminder.lower()
        assert r.due_date == NEXT_FRIDAY
        assert r.due_time is not None

    def test_28_fifteenth_at_two_pm(self) -> None:
        r = parse("dentist on the fifteenth at two pm", today=TODAY)
        assert "dentist" in r.reminder.lower()
        assert r.due_date is not None
        assert r.due_date.day == 15
        assert r.due_time == time(14, 0)

    def test_29_saturday_evening(self) -> None:
        # Time block — parser may not have due_time_block yet
        r = parse("birthday party saturday evening", today=TODAY)
        assert "birthday party" in r.reminder.lower()
        assert r.due_date == UPCOMING_SATURDAY

    def test_30_monday_morning_at_six(self) -> None:
        r = parse("early flight monday morning at six", today=TODAY)
        assert "flight" in r.reminder.lower()
        assert r.due_date == UPCOMING_MONDAY
        assert r.due_time is not None
        assert r.due_time.hour == 6

    def test_31_noon(self) -> None:
        r = parse("coffee tuesday at noon", today=TODAY)
        assert "coffee" in r.reminder.lower()
        assert r.due_date == UPCOMING_TUESDAY
        assert r.due_time == time(12, 0)

    def test_32_midnight_sunday(self) -> None:
        r = parse("midnight deadline sunday", today=TODAY)
        assert "deadline" in r.reminder.lower()

    def test_33_first_thing_monday(self) -> None:
        r = parse("first thing monday morning", today=TODAY)
        assert r.due_date == UPCOMING_MONDAY


# ===========================================================================
# D. Cross-Unit Durations
# ===========================================================================


class TestCrossUnitDurations:
    """Section D: Compound duration expressions."""

    def test_34_one_hour_thirty_minutes(self) -> None:
        r = parse("workout one hour and thirty minutes", today=TODAY)
        assert "workout" in r.reminder.lower()
        assert r.estimated_minutes == 90

    def test_35_two_and_a_half_hours(self) -> None:
        r = parse("write report two and a half hours", today=TODAY)
        assert "write report" in r.reminder.lower()
        assert r.estimated_minutes == 150

    def test_36_every_two_hours(self) -> None:
        r = parse("check email every two hours", today=TODAY)
        assert "check email" in r.reminder.lower()
        assert r.recurrence_type == "minutely"
        assert r.recurrence_interval == 120

    def test_37_fifteen_minutes_daily(self) -> None:
        r = parse("standup fifteen minutes daily", today=TODAY)
        assert "standup" in r.reminder.lower()
        assert r.estimated_minutes == 15
        assert r.recurrence_type == "daily"

    def test_38_ninety_minutes(self) -> None:
        r = parse("deep work ninety minutes", today=TODAY)
        assert "deep work" in r.reminder.lower()
        assert r.estimated_minutes == 90 or r.work_duration == 90

    def test_39_every_forty_five_minutes(self) -> None:
        r = parse("stand up break every forty five minutes", today=TODAY)
        assert r.recurrence_type == "minutely"
        assert r.recurrence_interval == 45


# ===========================================================================
# E. Filler Words & Spoken Punctuation
# ===========================================================================


class TestFillerWords:
    """Section E: STT artifacts — fillers, spoken punctuation, preambles."""

    def test_40_um_filler(self) -> None:
        r = parse("um remind me to buy milk tomorrow", today=TODAY)
        assert "buy milk" in r.reminder.lower()
        assert r.due_date == TOMORROW

    def test_41_uh_like_fillers(self) -> None:
        r = parse("uh call mom like tomorrow at three", today=TODAY)
        assert "call mom" in r.reminder.lower()
        assert r.due_date == TOMORROW

    def test_42_you_know_filler(self) -> None:
        r = parse("you know pay the bills today", today=TODAY)
        assert "pay the bills" in r.reminder.lower()
        assert r.due_date == TODAY

    def test_43_spoken_comma(self) -> None:
        r = parse("buy milk comma bread comma eggs", today=TODAY)
        assert "milk" in r.reminder.lower()
        assert "bread" in r.reminder.lower()
        assert "eggs" in r.reminder.lower()

    def test_44_spoken_period(self) -> None:
        r = parse("finish project period high priority", today=TODAY)
        assert "finish project" in r.reminder.lower()
        assert r.priority == 1

    def test_45_period_then_metadata(self) -> None:
        r = parse("call mom period tomorrow at three", today=TODAY)
        assert "call mom" in r.reminder.lower()
        assert r.due_date == TOMORROW

    def test_46_preamble_so(self) -> None:
        r = parse("so i need to finish the report by friday", today=TODAY)
        assert "finish the report" in r.reminder.lower()
        assert r.due_date == UPCOMING_FRIDAY

    def test_47_preamble_okay(self) -> None:
        r = parse("okay schedule dentist next week", today=TODAY)
        assert "schedule dentist" in r.reminder.lower()


# ===========================================================================
# F. Capitalization Artifacts
# ===========================================================================


class TestCapitalization:
    """Section F: Random mid-sentence caps from STT."""

    def test_48_all_caps_words(self) -> None:
        r = parse("Call Mom Tomorrow At Three", today=TODAY)
        assert "call mom" in r.reminder.lower()
        assert r.due_date == TOMORROW
        assert r.due_time is not None

    def test_49_caps_at_the_store(self) -> None:
        r = parse("Buy Milk and Bread at The Store", today=TODAY)
        # Article "The" prevents tag extraction
        assert "store" in r.reminder.lower()

    def test_50_caps_priority_today(self) -> None:
        r = parse("High Priority Fix The Bug Today", today=TODAY)
        assert "fix the bug" in r.reminder.lower()
        assert r.priority == 1
        assert r.due_date == TODAY

    def test_51_caps_at_work_morning(self) -> None:
        r = parse("Email boss At Work tomorrow morning", today=TODAY)
        assert "at work" in r.reminder.lower()
        assert r.due_date == TOMORROW


# ===========================================================================
# G. Run-On Inputs
# ===========================================================================


class TestRunOnInputs:
    """Section G: Multiple intents in a single utterance."""

    def test_52_full_run_on(self) -> None:
        r = parse("remind me tomorrow at three to call mom high priority", today=TODAY)
        assert "call mom" in r.reminder.lower()
        assert r.due_date == TOMORROW
        assert r.due_time is not None
        assert r.priority == 1

    def test_53_report_friday_priority(self) -> None:
        r = parse("finish the report by friday high priority", today=TODAY)
        assert "finish the report" in r.reminder.lower()
        assert r.due_date == UPCOMING_FRIDAY
        assert r.priority == 1

    def test_54_explicit_tag_keyword(self) -> None:
        r = parse("daily standup nine am tag work", today=TODAY)
        assert "standup" in r.reminder.lower()
        assert r.recurrence_type == "daily"
        assert r.due_time == time(9, 0)
        # "tag work" is an explicit tag signal
        assert any("work" in t.lower() for t in r.tags)

    def test_55_at_the_store_no_tag(self) -> None:
        r = parse("pick up groceries after work today at the store", today=TODAY)
        assert "at the store" in r.reminder.lower()
        assert r.due_date == TODAY
        # Article disqualifies tag inference
        assert "store" not in [t.lower().lstrip("@#") for t in r.tags]

    def test_56_estimate_and_priority(self) -> None:
        r = parse("review pr one hour estimate high priority", today=TODAY)
        assert "review pr" in r.reminder.lower()
        assert r.estimated_minutes == 60
        assert r.priority == 1

    def test_57_multi_metadata(self) -> None:
        r = parse("workout thirty minutes every day at six am", today=TODAY)
        assert "workout" in r.reminder.lower()
        assert r.estimated_minutes == 30
        assert r.recurrence_type == "daily"
        assert r.due_time == time(6, 0)


# ===========================================================================
# H. Homophones & STT Errors
# ===========================================================================


class TestHomophones:
    """Section H: STT misrenders — hardest category. Many will fail baseline."""

    def test_58_bye_for_buy(self) -> None:
        r = parse("bye milk tomorrow", today=TODAY)
        # Ideal: "buy milk". Acceptable baseline: "bye milk" stays as-is
        assert r.due_date == TOMORROW

    def test_59_for_for_four(self) -> None:
        r = parse("pick up for people at the airport", today=TODAY)
        # Ideal: "pick up four people at the airport"
        # Baseline: entire phrase stays as reminder
        assert "airport" in r.reminder.lower()

    def test_60_two_for_to(self) -> None:
        r = parse("remind me two call mom", today=TODAY)
        assert "call mom" in r.reminder.lower() or "two call mom" in r.reminder.lower()

    def test_61_texting_idiom(self) -> None:
        r = parse("add to the team meeting", today=TODAY)
        assert "team meeting" in r.reminder.lower()

    def test_62_right_for_write(self) -> None:
        r = parse("right a thank you note", today=TODAY)
        # Ideal: "write a thank you note"
        assert "thank you note" in r.reminder.lower()

    def test_63_weigh_for_way(self) -> None:
        r = parse("the weigh home", today=TODAY)
        assert "home" in r.reminder.lower()


# ===========================================================================
# I. Approximations
# ===========================================================================


class TestApproximations:
    """Section I: Qualifier words signal approximate values."""

    def test_64_about_thirty_minutes(self) -> None:
        r = parse("meeting about thirty minutes", today=TODAY)
        assert "meeting" in r.reminder.lower()
        assert r.estimated_minutes is not None
        assert 25 <= r.estimated_minutes <= 35

    def test_65_around_three_pm(self) -> None:
        r = parse("call around three pm", today=TODAY)
        assert "call" in r.reminder.lower()
        assert r.due_time is not None

    def test_66_roughly_forty_five(self) -> None:
        r = parse("workout roughly forty five minutes daily", today=TODAY)
        assert "workout" in r.reminder.lower()
        assert r.estimated_minutes is not None
        assert r.recurrence_type == "daily"

    def test_67_sometime_next_week(self) -> None:
        r = parse("deploy sometime next week", today=TODAY)
        assert "deploy" in r.reminder.lower()
        assert r.due_date is not None


# ===========================================================================
# J. Relative Time
# ===========================================================================


class TestRelativeTime:
    """Section J: Offsets from current moment."""

    def test_68_in_one_hour(self) -> None:
        r = parse("take medicine in one hour", today=TODAY)
        assert "take medicine" in r.reminder.lower()
        # Parser should recognize relative time offset
        assert r.due_date is not None or r.due_time is not None

    def test_69_in_ten_minutes(self) -> None:
        r = parse("call back in ten minutes", today=TODAY)
        assert "call back" in r.reminder.lower()

    def test_70_couple_days(self) -> None:
        r = parse("follow up in a couple days", today=TODAY)
        assert "follow up" in r.reminder.lower()
        assert r.due_date is not None
        assert r.due_date == TODAY + timedelta(days=2)

    def test_71_few_hours(self) -> None:
        r = parse("check on it in a few hours", today=TODAY)
        assert "check on it" in r.reminder.lower()

    def test_72_half_an_hour(self) -> None:
        r = parse("lunch in half an hour", today=TODAY)
        assert "lunch" in r.reminder.lower()


# ===========================================================================
# K1. Ad-Hoc Time Ranges
# ===========================================================================


class TestAdHocRanges:
    """Section K1: Explicit time windows — due_time + due_time_end extraction."""

    def test_73a_between_three_and_five(self) -> None:
        r = parse("call between three and five pm", today=TODAY)
        assert "call" in r.reminder.lower()
        assert r.due_time == time(15, 0)
        assert r.due_time_end == time(17, 0)

    def test_73b_from_two_to_four(self) -> None:
        r = parse("meeting from 2 to 4 pm", today=TODAY)
        assert "meeting" in r.reminder.lower()
        assert r.due_time == time(14, 0)
        assert r.due_time_end == time(16, 0)

    def test_73e_meds_between_nine_and_ten(self) -> None:
        r = parse("give meds between nine and ten am", today=TODAY)
        assert "meds" in r.reminder.lower()
        assert r.due_time == time(9, 0)
        assert r.due_time_end == time(10, 0)

    def test_73h_morning_between_nine_eleven(self) -> None:
        r = parse("tomorrow morning between nine and eleven", today=TODAY)
        assert r.due_date == TOMORROW
        assert r.due_time == time(9, 0)
        assert r.due_time_end == time(11, 0)

    def test_73i_bare_to_connector(self) -> None:
        r = parse("call 3 to 5", today=TODAY)
        assert "call" in r.reminder.lower()
        assert r.due_time == time(15, 0)
        assert r.due_time_end == time(17, 0)

    def test_73j_dash_form(self) -> None:
        r = parse("meeting 2-4 pm", today=TODAY)
        assert "meeting" in r.reminder.lower()
        assert r.due_time == time(14, 0)
        assert r.due_time_end == time(16, 0)

    def test_73k_through_connector(self) -> None:
        r = parse("work session from nine through eleven", today=TODAY)
        assert "work session" in r.reminder.lower()
        assert r.due_time == time(9, 0)
        assert r.due_time_end == time(11, 0)

    def test_73m_till_connector(self) -> None:
        r = parse("focus block six till eight pm", today=TODAY)
        assert "focus block" in r.reminder.lower()
        assert r.due_time == time(18, 0)
        assert r.due_time_end == time(20, 0)


# ===========================================================================
# K2. Time Blocks
# ===========================================================================


class TestTimeBlocks:
    """Section K2: Named time windows. Schema v18 feature — most will fail baseline."""

    def test_73_dinner_tonight(self) -> None:
        r = parse("dinner tonight", today=TODAY)
        assert "dinner" in r.reminder.lower()
        assert r.due_date == TODAY
        assert r.due_time_block == "evening"

    def test_74_breakfast_tomorrow(self) -> None:
        r = parse("breakfast tomorrow", today=TODAY)
        assert "breakfast" in r.reminder.lower()
        assert r.due_date == TOMORROW
        assert r.due_time_block == "morning"

    def test_77_friday_night(self) -> None:
        r = parse("dinner with parents friday night", today=TODAY)
        assert "dinner with parents" in r.reminder.lower()
        assert r.due_date == UPCOMING_FRIDAY
        assert r.due_time_block == "night"

    def test_79_this_afternoon(self) -> None:
        r = parse("call back this afternoon", today=TODAY)
        assert "call back" in r.reminder.lower()
        assert r.due_date == TODAY
        assert r.due_time_block == "afternoon"

    def test_83_first_thing(self) -> None:
        r = parse("take meds first thing", today=TODAY)
        assert "take meds" in r.reminder.lower()
        assert r.due_time_block == "early_morning"

    def test_84_daily_late_afternoon(self) -> None:
        r = parse("late afternoon snack daily", today=TODAY)
        assert "snack" in r.reminder.lower()
        assert r.recurrence_type == "daily"
        assert r.due_time_block == "late_afternoon"


# ===========================================================================
# L. Priority & Urgency
# ===========================================================================


class TestPriorityUrgency:
    """Section L: Priority markers and urgency vocabulary."""

    def test_85_urgent(self) -> None:
        r = parse("urgent fix the login bug", today=TODAY)
        assert "fix the login bug" in r.reminder.lower()
        assert r.priority == 1

    def test_86_asap(self) -> None:
        r = parse("asap call customer", today=TODAY)
        assert "call customer" in r.reminder.lower()
        assert r.priority == 1

    def test_87_low_priority(self) -> None:
        r = parse("low priority clean up old files", today=TODAY)
        assert "clean up old files" in r.reminder.lower()
        assert r.priority == 3

    def test_88_important(self) -> None:
        r = parse("important email the investor", today=TODAY)
        assert "email the investor" in r.reminder.lower()
        assert r.priority == 1


# ===========================================================================
# M. Conditional & Constraint Expressions
# ===========================================================================


class TestConditionalExpressions:
    """Section M: Conditions, constraints, and event dates."""

    def test_89_event_date_scheduling(self) -> None:
        r = parse("schedule dentist for next month before the twentieth", today=TODAY)
        assert "dentist" in r.reminder.lower()
        assert r.event_date is not None
        assert r.event_date.month == (TODAY.month % 12) + 1
        assert r.due_date is not None
        assert r.due_date.day == 20

    def test_90_if_calendar_open(self) -> None:
        r = parse("book hotel if calendar is open next weekend", today=TODAY)
        assert "book hotel" in r.reminder.lower() or "hotel" in r.reminder.lower()
        assert len(r.conditions) >= 1
        assert r.conditions[0]["type"] == "if"
        assert "calendar" in r.conditions[0]["expression"]

    def test_94_otherwise_fallback(self) -> None:
        r = parse("dentist appointment next month otherwise the month after", today=TODAY)
        assert "dentist" in r.reminder.lower()
        assert r.due_date is not None
        assert len(r.conditions) >= 1
        assert r.conditions[0]["type"] == "fallback"

    def test_95_before_at_the_latest(self) -> None:
        r = parse("call plumber before friday at the latest", today=TODAY)
        assert "call plumber" in r.reminder.lower()
        assert r.due_date is not None

    def test_96_no_later_than(self) -> None:
        r = parse("finish taxes no later than april fourteenth", today=TODAY)
        assert "finish taxes" in r.reminder.lower()
        assert r.due_date is not None
        assert r.due_date.month == 4
        assert r.due_date.day == 14

    def test_98_only_if(self) -> None:
        r = parse("only schedule meeting if both tuesday and thursday are free", today=TODAY)
        assert "meeting" in r.reminder.lower()
        assert len(r.conditions) >= 1
        assert r.conditions[0]["type"] == "if"
