"""A request budget per visitor address, under a budget for everyone.

Both buckets matter: the one per address stops a single browser in a loop,
the overall one stops a spread-out flood. A request spends a token from both
buckets or from neither, so the refused requests of one browser leave the
overall allowance to everyone else. A bucket left alone for a minute is full
again, the same as a new one, so once a minute those are dropped and the table
holds only recent addresses. In-process, with no store.

The monitor's client error reports (``monitor/routes.py``) and a dashboard
viewer's runs (``runs/viewer.py``) each hold one.
"""

from __future__ import annotations

import threading

from utk_curio.backend.app.common.token_bucket import TokenBucket

_MINUTE = 60.0


class AddressLimiter:
    """*per_address_per_minute* requests a minute from one address, and
    *overall_per_minute* from all of them together."""

    def __init__(self, per_address_per_minute: int, overall_per_minute: int) -> None:
        self.per_address_per_minute = per_address_per_minute
        self.overall_per_minute = overall_per_minute
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.overall: TokenBucket | None = None
            self.per_address: dict[str, TokenBucket] = {}
            self.swept_at: float | None = None

    def allow(self, key: str, now: float) -> bool:
        with self._lock:
            self._forget_full_buckets(now)
            if self.overall is None:
                self.overall = TokenBucket(
                    self.overall_per_minute, self.overall_per_minute / _MINUTE, now)
            if self.overall.refill(now) < 1.0:
                return False
            bucket = self.per_address.get(key)
            if bucket is None:
                bucket = TokenBucket(
                    self.per_address_per_minute, self.per_address_per_minute / _MINUTE, now)
                self.per_address[key] = bucket
            if not bucket.take(now):
                return False
            self.overall.take(now)
            return True

    def _forget_full_buckets(self, now: float) -> None:
        if self.swept_at is not None and now - self.swept_at < _MINUTE:
            return
        self.swept_at = now
        self.per_address = {
            key: bucket for key, bucket in self.per_address.items()
            if bucket.refill(now) < bucket.capacity
        }
