"""Durations as the monitor's histories keep them (``monitor/durations.py``):
the 19 buckets a duration falls in, as it was measured, a row's counts, its
total in whole milliseconds or whole microseconds, the average and the 95th
percentile read back from the sums, interpolated inside the bucket that holds
the percentile's rank, the last bucket giving its lower bound, and each time
as a route gives it.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.monitor import durations
from utk_curio.backend.app.monitor import history as monitor_history


def _buckets(**placed) -> list[int]:
    """Bucket counts with *placed* counts, by bucket number (``b0`` to ``b18``)."""
    out = [0] * durations.BUCKETS
    for name, count in placed.items():
        out[int(name[1:])] = count
    return out


def test_nineteen_buckets_with_their_upper_bounds_in_milliseconds():
    assert durations.BOUNDS_MS == (
        1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000, 300000, 600000)
    assert durations.BUCKETS == 19


@pytest.mark.parametrize(("ms", "bucket"), [
    (0, 0), (0.4, 0), (1, 0), (1.2, 1), (2, 1), (2.5, 2), (5, 2), (7, 3), (10, 3), (12, 4), (25, 4),
    (40, 5), (50, 5), (50.4, 6), (51, 6), (100, 6), (101, 7), (250, 7), (500, 8), (999, 9), (1000, 9),
    (1001, 10), (2500, 10), (5000, 11), (10000, 12), (30000, 13), (60000, 14), (120000, 15),
    (300000, 16), (600000, 17), (600001, 18), (10 ** 9, 18),
])
def test_a_duration_falls_in_the_first_bucket_whose_upper_bound_it_does_not_pass(ms, bucket):
    assert durations.bucket_of(ms) == bucket
    assert durations.counts(ms) == _buckets(**{f"b{bucket}": 1})


@pytest.mark.parametrize("value", [-3, -0.4, float("nan"), float("inf"), None, "12", True])
def test_what_is_not_a_duration_falls_in_the_first_bucket(value):
    assert durations.bucket_of(value) == 0
    assert durations.counts(value) == _buckets(b0=1)


def test_a_duration_is_bucketed_as_it_was_measured_not_as_a_row_rounds_it():
    # 1.4 ms is past the 1 ms bucket, though it rounds to 1 ms; 0.6 ms is in it.
    assert (durations.whole_ms(1.4), durations.bucket_of(1.4)) == (1, 1)
    assert (durations.whole_ms(0.6), durations.bucket_of(0.6)) == (1, 0)


@pytest.mark.parametrize(("value", "kept"), [
    (12, 12), (12.4, 12), (12.6, 13), (0, 0), (-3, 0), (-0.4, 0), (float("nan"), 0), (float("inf"), 0),
    (None, 0), ("12", 0), (True, 0),
])
def test_a_row_keeps_whole_milliseconds_and_nothing_for_what_is_not_a_duration(value, kept):
    assert durations.whole_ms(value) == kept
    assert type(durations.whole_ms(value)) is int


@pytest.mark.parametrize(("value", "kept"), [
    (0.4321, 432), (0.0004, 0), (0.0006, 1), (12, 12000), (12.0004, 12000), (12.0006, 12001), (1500.25, 1500250),
    (0, 0), (-3, 0), (-0.4, 0), (float("nan"), 0), (float("inf"), 0), (None, 0), ("12", 0), (True, 0),
])
def test_a_row_of_short_durations_keeps_whole_microseconds(value, kept):
    assert durations.whole_us(value) == kept
    assert type(durations.whole_us(value)) is int


def test_the_average_is_the_total_over_the_count():
    assert durations.average(5120, 4) == 1280.0
    assert durations.average(0, 3) == 0.0
    assert durations.average(0, 0) is None
    assert durations.average(100, None) is None


def test_the_95th_percentile_is_interpolated_inside_the_bucket_that_holds_its_rank():
    # 20 durations of 1 ms or less: the rank, 19, is 19/20 of the way through
    # the first bucket, which starts at 0.
    assert durations.percentile(_buckets(b0=20)) == pytest.approx(0.95)
    # 20 durations from 25 to 50 ms: 19/20 of the way from 25 to 50.
    assert durations.percentile(_buckets(b5=20)) == pytest.approx(48.75)
    # 10, 9 and 1: the rank, 19, is the last of the second bucket's 9.
    assert durations.percentile(_buckets(b5=10, b6=9, b7=1)) == pytest.approx(100.0)
    # 10, 5 and 5: the rank, 19, is the fourth of the third bucket's 5, from 100 to 250.
    assert durations.percentile(_buckets(b5=10, b6=5, b7=5)) == pytest.approx(100 + 150 * 4 / 5)
    # One request of 700 ms: 0.95 of the way through its bucket, from 500 to 1,000.
    assert durations.percentile(durations.counts(700)) == pytest.approx(975.0)


def test_a_slowdown_under_50_ms_moves_the_95th_percentile():
    """What the buckets from 1 ms are for: requests of a fraction of a
    millisecond, of 5 ms and of 40 ms each read as their own."""
    fast, slower, slowest = ([0.4] * 20, [5] * 20, [40] * 20)

    def p95(group):
        return durations.percentile([sum(column) for column in zip(*(durations.counts(ms) for ms in group))])

    assert p95(fast) == pytest.approx(0.95)
    assert p95(slower) == pytest.approx(2 + 3 * 0.95)
    assert p95(slowest) == pytest.approx(25 + 25 * 0.95)
    assert p95(fast) < 1 < p95(slower) < 5 < 25 < p95(slowest) < 50


def test_another_fraction_reads_its_own_rank():
    assert durations.percentile(_buckets(b7=4), 0.5) == pytest.approx(175.0)
    assert durations.percentile(_buckets(b5=1, b9=1), 0.5) == pytest.approx(50.0)


def test_a_rank_in_the_last_bucket_reads_as_its_lower_bound():
    assert durations.percentile(_buckets(b18=1)) == 600000.0
    assert durations.percentile(_buckets(b5=1, b18=19)) == 600000.0


def test_no_durations_have_no_percentile_and_a_count_that_is_not_whole_counts_nothing():
    assert durations.percentile(_buckets()) is None
    assert durations.percentile([]) is None
    assert durations.percentile(None) is None
    assert durations.percentile([None, "3", True, 2.5] + [0] * 15) is None
    assert durations.percentile([-4, 2] + [0] * 17) == pytest.approx(1 + 1 * 0.95)


@pytest.mark.parametrize(("ms", "given"), [
    (None, None), (0, 0.0), (0.4, 0.4), (0.43219, 0.432), (0.0123456, 0.0123), (4.5678, 4.57), (9.994, 9.99),
    (9.996, 10.0), (10, 10), (48.75, 49), (1200.5, 1200), (2350.0, 2350), (600000.0, 600000),
])
def test_a_route_gives_whole_milliseconds_from_10_ms_and_three_significant_digits_below(ms, given):
    assert durations.shown(ms) == given
    if given is not None:
        assert type(durations.shown(ms)) is (int if ms >= durations.WHOLE_FROM_MS else float)


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
