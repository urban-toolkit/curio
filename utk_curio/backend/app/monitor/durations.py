"""Durations as the monitor's histories keep them: a total and a count in each
of 14 fixed buckets, so the rows of any number of processes add up exactly,
and the average and the 95th percentile read back from the sums.

THE BUCKETS. A duration, in whole milliseconds (:func:`whole_ms`), falls in
the first bucket whose upper bound it does not pass (:data:`BOUNDS_MS`: 50 ms,
100, 250 and 500 ms, 1 s, 2.5, 5, 10, 30, 60, 120, 300 and 600 s), or in the
last, above 600 s. A row holds its durations' total milliseconds and its count
in each bucket (:func:`counts`), which a history adds place by place
(``history.summed``).

READING THEM BACK. The average is the total over the count (:func:`average`).
A percentile (:func:`percentile`) is read from the bucket counts alone: the
rank it names, the fraction of the count, falls in one bucket, and the
duration is interpolated across that bucket as the rank goes through its
count, from its lower bound (the upper bound of the bucket before it, 0 for
the first) to its upper bound. The last bucket has no upper bound, so a rank
in it reads as its lower bound, 600 s.

Pure: the histories that keep durations (``llm_performance.py``) read it.
"""

from __future__ import annotations

import bisect
import math
from typing import Optional, Sequence

#: The buckets' upper bounds, in milliseconds; the last bucket is above them all.
BOUNDS_MS = (50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 30_000, 60_000, 120_000, 300_000, 600_000)
#: How many buckets a row counts its durations in.
BUCKETS = len(BOUNDS_MS) + 1


def whole_ms(value) -> int:
    """*value*, a duration in milliseconds, as the whole milliseconds a row
    keeps: rounded, and 0 for anything that is not a duration (a negative
    number, a number that is not finite, or no number at all)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if not math.isfinite(value) or value <= 0:
        return 0
    return int(round(value))


def bucket_of(ms) -> int:
    """The bucket a duration of *ms* milliseconds falls in: the first whose
    upper bound it does not pass, else the last."""
    return bisect.bisect_left(BOUNDS_MS, whole_ms(ms))


def counts(ms) -> list[int]:
    """A row's bucket counts for one duration of *ms* milliseconds: 1 in its
    bucket, 0 in every other."""
    out = [0] * BUCKETS
    out[bucket_of(ms)] = 1
    return out


def average(total_ms, count) -> Optional[float]:
    """The average of *count* durations that add up to *total_ms*
    milliseconds; None when there is none."""
    if not _whole(count) or count <= 0 or not _whole(total_ms):
        return None
    return total_ms / count


def percentile(buckets: Sequence[int], fraction: float = 0.95) -> Optional[float]:
    """The duration, in milliseconds, under which *fraction* of the durations
    counted in *buckets* fall, interpolated inside the bucket that holds its
    rank; the last bucket gives its lower bound. None when *buckets* counts
    none. A count that is not a whole number counts nothing, and a place past
    the last bucket counts in it."""
    if not isinstance(buckets, (list, tuple)):
        return None
    held = [count if _whole(count) and count > 0 else 0 for count in buckets]
    total = sum(held)
    if total == 0:
        return None
    rank = fraction * total
    seen = 0
    for index, count in enumerate(held):
        if count == 0:
            continue
        if seen + count >= rank:
            if index >= len(BOUNDS_MS):
                return float(BOUNDS_MS[-1])
            lower = BOUNDS_MS[index - 1] if index else 0
            upper = BOUNDS_MS[index]
            return lower + (upper - lower) * (rank - seen) / count
        seen += count
    return float(BOUNDS_MS[-1])


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
