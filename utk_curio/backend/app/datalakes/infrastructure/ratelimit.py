"""Per-(user, source) request budgets.

A token bucket per pair, so one user hammering one portal cannot spend another
user's allowance or another portal's. Refill is continuous rather than per
window, which avoids the burst-at-the-boundary that a fixed window has.

**In-process, and that is a real limitation, stated rather than implied.**
Under several worker processes each holds its own buckets, so the effective
rate is the configured rate times the worker count. This is a politeness
mechanism toward portals we do not own and a brake on accidental loops, not a
guarantee we can make to a third party. Making it a guarantee needs shared
state, which is a bigger change than this bound is worth today.
"""

from __future__ import annotations

import threading
import time

from utk_curio.backend.app.datalakes.domain.errors import RateLimited

#: How many downloads one account may have in flight. Two is enough to keep
#: working while one large file lands, and low enough that nobody can queue
#: fifty jobs against a municipal portal.
MAX_CONCURRENT_DOWNLOADS = 2


class TokenBucket:
    __slots__ = ("capacity", "per_second", "tokens", "updated")

    def __init__(self, capacity: int, per_second: float) -> None:
        self.capacity = float(capacity)
        self.per_second = per_second
        self.tokens = float(capacity)
        self.updated = time.monotonic()

    def take(self, now: float) -> bool:
        elapsed = max(0.0, now - self.updated)
        self.updated = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.per_second)
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], TokenBucket] = {}
        self._lock = threading.Lock()

    def check(self, user_key: str, source_dir: str, per_minute: int) -> None:
        """Spend one request, or raise :class:`RateLimited`."""
        now = time.monotonic()
        key = (user_key or "-", source_dir)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.capacity != float(per_minute):
                # A manifest edit changes the rate; rebuild rather than letting
                # the old capacity persist for the life of the process.
                bucket = TokenBucket(per_minute, per_minute / 60.0)
                self._buckets[key] = bucket
            if not bucket.take(now):
                raise RateLimited(
                    f"too many requests to this source - it allows "
                    f"{per_minute} per minute"
                )

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


class DownloadSlots:
    """A per-user semaphore over downloads in flight."""

    def __init__(self, limit: int = MAX_CONCURRENT_DOWNLOADS) -> None:
        self.limit = limit
        self._held: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, user_key: str) -> None:
        with self._lock:
            held = self._held.get(user_key, 0)
            if held >= self.limit:
                raise RateLimited(
                    f"you already have {held} downloads running - wait for one to finish"
                )
            self._held[user_key] = held + 1

    def release(self, user_key: str) -> None:
        with self._lock:
            held = self._held.get(user_key, 0)
            if held <= 1:
                self._held.pop(user_key, None)
            else:
                self._held[user_key] = held - 1

    def reset(self) -> None:
        with self._lock:
            self._held.clear()


#: Process-wide instances. Module-level for the same reason the rest of this
#: module is: the bound is per process by construction.
limiter = RateLimiter()
download_slots = DownloadSlots()
