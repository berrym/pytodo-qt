"""Lanes for the bars of one day that share time (#88).

The web page's Week and Day painted every bar of a day at the full
width of the day's column, one over the other: of bars that shared
hours only the last could be seen or opened. `assign_lanes` gives each
bar a lane among the bars it shares time with, and the page draws them
side by side.
"""

from __future__ import annotations

import random

import pytest

from pytodo_qt.core.calendar_layout import assign_lanes


def _share_time(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _most_at_one_minute(spans: list[tuple[int, int]]) -> int:
    return max(sum(1 for s in spans if s[0] <= minute < s[1]) for minute in range(1440))


class TestAssignLanes:
    def test_no_bars(self):
        assert assign_lanes([]) == []

    def test_a_bar_alone_has_the_full_width(self):
        assert assign_lanes([(540, 600)]) == [(0, 1)]

    def test_two_bars_that_share_time_stand_side_by_side(self):
        """09:00-10:00 and 09:30-11:00: the one that begins first is on
        the left."""
        assert assign_lanes([(540, 600), (570, 660)]) == [(0, 2), (1, 2)]

    def test_the_order_given_does_not_decide_the_lanes(self):
        assert assign_lanes([(570, 660), (540, 600)]) == [(1, 2), (0, 2)]

    def test_a_bar_that_ends_as_another_begins_shares_no_time_with_it(self):
        assert assign_lanes([(540, 600), (600, 660)]) == [(0, 1), (0, 1)]

    def test_bars_apart_are_each_alone(self):
        assert assign_lanes([(540, 600), (570, 660), (720, 780)]) == [(0, 2), (1, 2), (0, 1)]

    def test_five_bars_at_the_same_time_have_five_lanes(self):
        """The case measured for the issue: five tasks at 14:00-15:30
        were five rectangles in one place. Given in this order, they
        stand in this order."""
        assert assign_lanes([(840, 930)] * 5) == [(lane, 5) for lane in range(5)]

    def test_of_bars_that_begin_together_the_longer_is_on_the_left(self):
        assert assign_lanes([(540, 570), (540, 720)]) == [(1, 2), (0, 2)]

    def test_a_lane_is_taken_again_once_its_bar_has_ended(self):
        """A long bar with two short ones inside it, one after the
        other: two lanes, not three."""
        assert assign_lanes([(540, 780), (600, 630), (720, 750)]) == [(0, 2), (1, 2), (1, 2)]

    def test_a_group_is_joined_through_a_bar_between(self):
        """09:00-10:00 and 10:30-11:40 share no time, and both share
        some with 09:30-11:00. The three are one group of two lanes:
        the third takes the lane the first has left."""
        assert assign_lanes([(540, 600), (570, 660), (630, 700)]) == [(0, 2), (1, 2), (0, 2)]

    def test_every_bar_of_a_group_has_the_groups_number_of_lanes(self):
        """A bar that shares time with one other only, in a group that
        has three at once elsewhere, is a third of the width like the
        rest: its width is the same all the way down."""
        placed = assign_lanes([(540, 720), (540, 600), (540, 600), (660, 720)])
        assert [lanes for _lane, lanes in placed] == [3, 3, 3, 3]

    def test_a_span_without_length_takes_its_minute(self):
        assert assign_lanes([(540, 540), (540, 600)]) == [(1, 2), (0, 2)]

    @pytest.mark.parametrize("seed", range(40))
    def test_no_two_bars_that_share_time_share_a_lane(self, seed):
        rng = random.Random(seed)
        spans = []
        for _ in range(rng.randint(1, 14)):
            start = rng.randrange(0, 1380, 5)
            spans.append((start, min(1440, start + rng.randrange(30, 300, 5))))
        placed = assign_lanes(spans)

        assert len(placed) == len(spans)
        for i, a in enumerate(spans):
            lane, lanes = placed[i]
            assert 0 <= lane < lanes
            for j in range(i + 1, len(spans)):
                if _share_time(a, spans[j]):
                    assert placed[j][0] != lane, (spans, placed)
                    # Sharing time, they are of one group.
                    assert placed[j][1] == lanes, (spans, placed)
        # No more lanes anywhere than the most bars at one minute.
        assert max(lanes for _lane, lanes in placed) == _most_at_one_minute(spans)
