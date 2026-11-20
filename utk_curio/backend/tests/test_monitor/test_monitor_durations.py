"""Durations as the monitor's histories keep them (``monitor/durations.py``):
the 14 buckets a duration falls in, a row's counts, and the average and the
95th percentile read back from the sums, interpolated inside the bucket that
holds the percentile's rank, the last bucket giving its lower bound.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.monitor import durations
from utk_curio.backend.app.monitor import history as monitor_history


def _buckets(**placed) -> list[int]:
    """Bucket counts with *placed* counts, by bucket number (``b0`` to ``b13``)."""
    out = [0] * durations.BUCKETS
    for name, count in placed.items():
        out[int(name[1:])] = count
    return out


def test_fourteen_buckets_with_their_upper_bounds_in_milliseconds():
    assert durations.BOUNDS_MS == (
        50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000, 300000, 600000)
    assert durations.BUCKETS == 14


@pytest.mark.parametrize(("ms", "bucket"), [
    (0, 0), (1, 0), (50, 0), (50.4, 0), (51, 1), (50.6, 1), (100, 1), (101, 2), (250, 2), (500, 3),
    (999, 4), (1000, 4), (1001, 5), (2500, 5), (5000, 6), (10000, 7), (30000, 8), (60000, 9),
    (120000, 10), (300000, 11), (600000, 12), (600001, 13), (10 ** 9, 13),
])
def test_a_duration_falls_in_the_first_bucket_whose_upper_bound_it_does_not_pass(ms, bucket):
    assert durations.bucket_of(ms) == bucket
    assert durations.counts(ms) == _buckets(**{f"b{bucket}": 1})


@pytest.mark.parametrize(("value", "kept"), [
    (12, 12), (12.4, 12), (12.6, 13), (0, 0), (-3, 0), (-0.4, 0), (float("nan"), 0), (float("inf"), 0),
    (None, 0), ("12", 0), (True, 0),
])
def test_a_row_keeps_whole_milliseconds_and_nothing_for_what_is_not_a_duration(value, kept):
    assert durations.whole_ms(value) == kept
    assert type(durations.whole_ms(value)) is int


def test_the_average_is_the_total_over_the_count():
    assert durations.average(5120, 4) == 1280.0
    assert durations.average(0, 3) == 0.0
    assert durations.average(0, 0) is None
    assert durations.average(100, None) is None


def test_the_95th_percentile_is_interpolated_inside_the_bucket_that_holds_its_rank():
    # 20 durations of 50 ms or less: the rank, 19, is 19/20 of the way through
    # the first bucket, which starts at 0.
    assert durations.percentile(_buckets(b0=20)) == pytest.approx(47.5)
    # 10, 9 and 1: the rank, 19, is the last of the second bucket's 9.
    assert durations.percentile(_buckets(b0=10, b1=9, b2=1)) == pytest.approx(100.0)
    # 10, 5 and 5: the rank, 19, is the fourth of the third bucket's 5, from 100 to 250.
    assert durations.percentile(_buckets(b0=10, b1=5, b2=5)) == pytest.approx(100 + 150 * 4 / 5)
    # One request of 700 ms: 0.95 of the way through its bucket, from 500 to 1,000.
    assert durations.percentile(durations.counts(700)) == pytest.approx(975.0)


def test_another_fraction_reads_its_own_rank():
    assert durations.percentile(_buckets(b2=4), 0.5) == pytest.approx(175.0)
    assert durations.percentile(_buckets(b0=1, b4=1), 0.5) == pytest.approx(50.0)


def test_a_rank_in_the_last_bucket_reads_as_its_lower_bound():
    assert durations.percentile(_buckets(b13=1)) == 600000.0
    assert durations.percentile(_buckets(b0=1, b13=19)) == 600000.0


def test_no_durations_have_no_percentile_and_a_count_that_is_not_whole_counts_nothing():
    assert durations.percentile(_buckets()) is None
    assert durations.percentile([]) is None
    assert durations.percentile(None) is None
    assert durations.percentile([None, "3", True, 2.5] + [0] * 10) is None
    assert durations.percentile([-4, 2] + [0] * 12) == pytest.approx(50 + 50 * 0.95)


def test_rows_added_place_by_place_read_as_one_row_of_all_their_durations():
    """What two processes count apart, a history adds place by place
    (``history.summed``): the sums read back as the durations counted together."""
    seen = [30, 30, 75, 75, 75, 400, 400, 1200, 1200, 2600, 9000, 45000]
    first, second = seen[:5], seen[5:]

    def row(group):
        out = {"requests": 0, "ms": 0, "buckets": [0] * durations.BUCKETS}
        for ms in group:
            out = monitor_history.summed(out, {"requests": 1, "ms": ms, "buckets": durations.counts(ms)})
        return out

    together = monitor_history.summed(row(first), row(second))
    assert together == row(seen)
    assert together["buckets"] == [sum(column) for column in zip(*(durations.counts(ms) for ms in seen))]
    assert durations.average(together["ms"], together["requests"]) == pytest.approx(sum(seen) / len(seen))
    # The rank, 11.4, falls in the bucket from 30 to 60 s, which holds the 12th.
    assert durations.percentile(together["buckets"]) == pytest.approx(30000 + 30000 * 0.4)
