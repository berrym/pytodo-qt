"""Tests for advance-reminder phrases in the natural-language parser.

"remind me 3 days before" asks for a mention in the daily summary on the
days before a task is due. The phrase is taken whole, before the steps
that would read "3 days" as a duration and "daily" as a recurrence.

Pure Python — no Qt dependency. Wednesday 2026-03-11 is "today".
"""

from __future__ import annotations

from datetime import date

import pytest

from pytodo_qt.core.nlp_parser import (
    EntityKind,
    EntitySpan,
    ParseResult,
    advance_reminder_label,
    parse,
)
from pytodo_qt.core.notification_policy import ADVANCE_DAYS_RANGE

TODAY = date(2026, 3, 11)
FRIDAY = date(2026, 3, 13)


def run(text: str) -> ParseResult:
    return parse(text, today=TODAY)


def reminder_of(result: ParseResult) -> tuple[int, str]:
    return result.remind_before_days, result.reminder_cadence


def advance_spans(result: ParseResult) -> list[EntitySpan]:
    return [s for s in result.spans if s.kind is EntityKind.ADVANCE_REMINDER]


# ---------------------------------------------------------------------------
# Phrases that are recognised
# ---------------------------------------------------------------------------


class TestOnce:
    @pytest.mark.parametrize(
        ("phrase", "days"),
        [
            ("remind me 3 days before", 3),
            ("remind me 1 day before", 1),
            ("remind me three days before", 3),
            ("remind me a week before", 7),
            ("remind me two weeks before", 14),
            ("remind me a month before", 30),
            ("remind me 2 months before", 60),
            ("remind me the day before", 1),
            ("remind me a day before", 1),
            ("remind me a couple of days before", 2),
            ("remind me a few days before", 3),
            ("remind 2 days ahead", 2),
            ("remind me 2 days in advance", 2),
            ("remind me 2 days ahead of time", 2),
            ("remind me 2 days beforehand", 2),
            ("remind me 2 days early", 2),
            ("reminder 2 days before", 2),
            ("remind me once 2 days before", 2),
        ],
    )
    def test_phrase(self, phrase: str, days: int) -> None:
        r = run(f"submit report friday {phrase}")
        assert reminder_of(r) == (days, "once")
        assert r.reminder == "submit report"
        assert r.due_date == FRIDAY

    def test_case_is_ignored(self) -> None:
        r = run("Submit report Friday Remind Me 3 Days Before")
        assert reminder_of(r) == (3, "once")
        assert r.reminder == "Submit report"

    def test_trailing_punctuation_on_the_closer(self) -> None:
        r = run("submit report friday remind me 3 days before.")
        assert reminder_of(r) == (3, "once")
        assert r.reminder == "submit report"

    def test_words_after_the_closer_that_add_nothing(self) -> None:
        r = run("submit report friday remind me 3 days before it's due")
        assert reminder_of(r) == (3, "once")
        assert r.reminder == "submit report"

    def test_phrase_may_come_first(self) -> None:
        r = run("remind me 3 days before submit report friday")
        assert reminder_of(r) == (3, "once")
        assert r.reminder == "submit report"
        assert r.due_date == FRIDAY

    def test_date_directly_after_the_closer(self) -> None:
        # "before" closes the phrase; it is not taken as the date's prefix,
        # which would leave the date unable to claim its own words.
        r = run("send invoice remind me 3 days before friday")
        assert reminder_of(r) == (3, "once")
        assert r.due_date == FRIDAY
        assert r.reminder == "send invoice"


class TestDaily:
    @pytest.mark.parametrize(
        ("phrase", "days"),
        [
            ("remind me daily 3 days before", 3),
            ("remind me every day from 5 days before", 5),
            ("remind me each day from a week before", 7),
            ("remind me daily starting 3 days before", 3),
            ("remind me from 5 days before", 5),
            ("remind me starting from 5 days before", 5),
        ],
    )
    def test_phrase(self, phrase: str, days: int) -> None:
        r = run(f"submit report friday {phrase}")
        assert reminder_of(r) == (days, "daily_until_due")
        assert r.reminder == "submit report"

    def test_cadence_word_is_not_a_recurrence(self) -> None:
        r = run("renew passport friday remind me daily 3 days before")
        assert r.recurrence_type is None
        assert r.due_date == FRIDAY

    def test_explicit_once_wins_over_from(self) -> None:
        r = run("submit report friday remind me once from 3 days before")
        assert reminder_of(r) == (3, "once")


class TestNotice:
    @pytest.mark.parametrize(
        ("phrase", "days"),
        [
            ("with 3 days notice", 3),
            ("with 3 days' notice", 3),
            ("with a week's notice", 7),
            ("with 2 weeks notice", 14),
            ("with 3-day notice", 3),
            ("with two-week notice", 14),
        ],
    )
    def test_phrase(self, phrase: str, days: int) -> None:
        r = run(f"pay rent friday {phrase}")
        assert reminder_of(r) == (days, "once")
        assert r.reminder == "pay rent"

    def test_notice_without_an_opener_is_title_text(self) -> None:
        r = run("give notice friday")
        assert reminder_of(r) == (0, "none")
        assert r.reminder == "give notice"


class TestLeadIns:
    @pytest.mark.parametrize(
        "lead_in",
        ["and", "please", "also", "and please", "and also"],
    )
    def test_lead_in_goes_with_the_phrase(self, lead_in: str) -> None:
        r = run(f"submit report friday {lead_in} remind me 2 days before")
        assert reminder_of(r) == (2, "once")
        assert r.reminder == "submit report"

    def test_with_a_reminder(self) -> None:
        r = run("submit report friday with a reminder 2 days before")
        assert reminder_of(r) == (2, "once")
        assert r.reminder == "submit report"

    def test_lead_in_word_elsewhere_is_title_text(self) -> None:
        r = run("salt and pepper friday remind me 2 days before")
        assert r.reminder == "salt and pepper"


# ---------------------------------------------------------------------------
# The day count
# ---------------------------------------------------------------------------


class TestDayCount:
    def test_more_than_the_most_is_limited(self) -> None:
        r = run("submit report friday remind me 100 days before")
        assert reminder_of(r) == (ADVANCE_DAYS_RANGE[1], "once")

    def test_weeks_beyond_the_most_are_limited(self) -> None:
        r = run("submit report friday remind me 20 weeks before")
        assert reminder_of(r) == (ADVANCE_DAYS_RANGE[1], "once")

    def test_months_beyond_the_most_are_limited(self) -> None:
        r = run("submit report friday remind me 4 months before")
        assert reminder_of(r) == (ADVANCE_DAYS_RANGE[1], "once")

    def test_zero_days_is_not_a_reminder(self) -> None:
        r = run("submit report friday remind me 0 days before")
        assert reminder_of(r) == (0, "none")
        assert advance_spans(r) == []

    def test_a_fraction_of_a_day_is_not_a_reminder(self) -> None:
        r = run("submit report friday remind me two and a half days before")
        assert reminder_of(r) == (0, "none")


# ---------------------------------------------------------------------------
# Text that is left alone
# ---------------------------------------------------------------------------


class TestLeftAlone:
    def test_remind_me_to(self) -> None:
        r = run("remind me to call mom friday")
        assert reminder_of(r) == (0, "none")
        assert r.reminder == "call mom"
        assert r.due_date == FRIDAY

    def test_remind_me_with_a_date(self) -> None:
        r = run("remind me tomorrow")
        assert reminder_of(r) == (0, "none")
        assert r.due_date == date(2026, 3, 12)

    def test_remind_me_in_three_days(self) -> None:
        r = run("call mom remind me in 3 days")
        assert reminder_of(r) == (0, "none")
        assert r.due_date == date(2026, 3, 14)

    def test_amount_and_closer_without_a_trigger(self) -> None:
        r = run("send invoice 3 days before friday")
        assert reminder_of(r) == (0, "none")
        assert advance_spans(r) == []

    def test_trigger_without_a_closer(self) -> None:
        r = run("submit report friday remind me 3 days")
        assert reminder_of(r) == (0, "none")

    def test_no_phrase(self) -> None:
        r = run("submit report friday")
        assert reminder_of(r) == (0, "none")
        assert advance_spans(r) == []


class TestOtherFieldsUnchanged:
    """The steps the phrase runs ahead of still see everything else."""

    def test_recurrence_outside_the_phrase(self) -> None:
        r = run("water plants daily remind me 1 day before")
        assert r.recurrence_type == "daily"
        assert reminder_of(r) == (1, "once")
        assert r.reminder == "water plants"

    def test_estimate_outside_the_phrase(self) -> None:
        r = run("write essay friday 2 hours remind me 3 days before")
        assert r.estimated_minutes == 120
        assert reminder_of(r) == (3, "once")
        assert r.reminder == "write essay"

    def test_phrase_gives_no_estimate(self) -> None:
        r = run("tax return friday remind me 3 days before")
        assert r.estimated_minutes is None

    def test_estimate_alone(self) -> None:
        r = run("study ~3 days friday")
        assert r.estimated_minutes == 3 * 24 * 60
        assert reminder_of(r) == (0, "none")

    def test_date_with_its_own_before(self) -> None:
        r = run("finish before friday")
        assert r.due_date == FRIDAY
        assert r.reminder == "finish"

    def test_priority_and_tag_beside_the_phrase(self) -> None:
        r = run("submit report friday remind me 3 days before p1 @work")
        assert r.priority == 1
        assert r.tags == ["@work"]
        assert reminder_of(r) == (3, "once")
        assert r.reminder == "submit report"

    def test_time_beside_the_phrase(self) -> None:
        r = run("submit by friday at 3pm remind me the day before")
        assert r.due_date == FRIDAY
        assert r.due_time is not None and r.due_time.hour == 15
        assert reminder_of(r) == (1, "once")


# ---------------------------------------------------------------------------
# The span and its text
# ---------------------------------------------------------------------------


class TestSpan:
    def test_covers_the_whole_phrase(self) -> None:
        text = "submit report friday remind me 3 days before"
        r = run(text)
        (span,) = advance_spans(r)
        assert text[span.start : span.end] == "remind me 3 days before"

    def test_covers_the_lead_in(self) -> None:
        text = "submit report friday and remind me 3 days before"
        (span,) = advance_spans(run(text))
        assert text[span.start : span.end] == "and remind me 3 days before"

    def test_text_for_once(self) -> None:
        (span,) = advance_spans(run("submit report friday remind me 3 days before"))
        assert span.display == "Remind 3 days before"

    def test_text_for_one_day(self) -> None:
        (span,) = advance_spans(run("submit report friday remind me the day before"))
        assert span.display == "Remind 1 day before"

    def test_text_for_daily(self) -> None:
        (span,) = advance_spans(run("submit report friday remind me daily 3 days before"))
        assert span.display == "Remind daily from 3 days before"

    def test_text_shows_the_limited_count(self) -> None:
        (span,) = advance_spans(run("submit report friday remind me 100 days before"))
        assert span.display == "Remind 90 days before"

    def test_is_certain(self) -> None:
        (span,) = advance_spans(run("submit report friday remind me 3 days before"))
        assert span.confidence == 1.0


class TestWithoutADueDate:
    def test_phrase_leaves_the_title_and_is_reported(self) -> None:
        r = run("call mom remind me 2 days before")
        assert r.reminder == "call mom"
        assert r.due_date is None
        # Reported so that a caller with a date of its own can keep it.
        assert reminder_of(r) == (2, "once")

    def test_text_says_a_due_date_is_needed(self) -> None:
        (span,) = advance_spans(run("call mom remind me 2 days before"))
        assert span.display == "Remind 2 days before (needs a due date)"

    def test_inferred_date_counts_as_a_due_date(self) -> None:
        (span,) = advance_spans(run("call mom at 3pm remind me 2 days before"))
        assert span.display == "Remind 2 days before"

    def test_recurrence_date_counts_as_a_due_date(self) -> None:
        (span,) = advance_spans(run("water plants daily remind me 1 day before"))
        assert span.display == "Remind 1 day before"


class TestTwoPhrases:
    TEXT = "submit report friday remind me 2 days before remind me daily 5 days before"

    def test_the_last_one_counts(self) -> None:
        assert reminder_of(run(self.TEXT)) == (5, "daily_until_due")

    def test_only_the_last_one_is_shown_as_a_reminder(self) -> None:
        (span,) = advance_spans(run(self.TEXT))
        assert span.display == "Remind daily from 5 days before"

    def test_the_earlier_one_stays_out_of_the_title(self) -> None:
        r = run(self.TEXT)
        assert r.reminder == "submit report"
        assert r.estimated_minutes is None
        fillers = [s for s in r.spans if s.kind is EntityKind.FILLER]
        assert [self.TEXT[s.start : s.end] for s in fillers] == ["remind me 2 days before"]


class TestLabel:
    def test_once(self) -> None:
        assert advance_reminder_label(3, "once") == "Remind 3 days before"

    def test_singular(self) -> None:
        assert advance_reminder_label(1, "once") == "Remind 1 day before"

    def test_daily(self) -> None:
        assert advance_reminder_label(4, "daily_until_due") == "Remind daily from 4 days before"

    def test_without_a_due_date(self) -> None:
        assert (
            advance_reminder_label(4, "daily_until_due", has_due_date=False)
            == "Remind daily from 4 days before (needs a due date)"
        )


class TestVocabulary:
    def test_missing_section_recognises_nothing(self, monkeypatch) -> None:
        """A dictionary written before the section existed still loads."""
        from pytodo_qt.core import intents

        built = intents._build_advance_reminder({})
        assert built["triggers"] == []
        assert built["units"] == {}
        patched = {**intents.get_intents(), "advance_reminder": built}
        monkeypatch.setattr("pytodo_qt.core.nlp_parser._get_intents", lambda: patched)
        r = run("submit report friday remind me 3 days before")
        assert reminder_of(r) == (0, "none")

    def test_longer_phrases_are_tried_first(self) -> None:
        from pytodo_qt.core import intents

        built = intents._build_advance_reminder({"triggers": ["remind", "remind me"]})
        assert built["triggers"] == [["remind", "me"], ["remind"]]
