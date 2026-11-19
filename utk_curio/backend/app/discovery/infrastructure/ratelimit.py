"""Per-(user, source) request budgets, and per-user downloads in flight.

A token bucket per pair, so one user hammering one portal cannot spend another
user's allowance or another portal's. Refill is continuous rather than per
window, which avoids the burst-at-the-boundary that a fixed window has.

In this process's memory when the start runs one backend process. In a start
of several, Discovery's own requests go to the home process, but an agent's
searches and downloads (Dataset Finder) run in its dataflow's process, so the
module's two budgets hold across every process of the start
(``common/shared_budgets.py``): an account's allowance at a portal, and its
downloads in flight, are the configured ones, not that times the process
count. This is a politeness mechanism toward portals we do not own and a brake
on accidental loops.
"""

from __future__ import annotations

import threading
import time

from utk_curio.backend.app.common import shared_budgets
from utk_curio.backend.app.common.token_bucket import TokenBucket
from utk_curio.backend.app.discovery.domain.errors import RateLimited

#: How many downloads one account may have in flight. Two is enough to keep
#: working while one large file lands, and low enough that nobody can queue
#: fifty jobs against a municipal portal.
MAX_CONCURRENT_DOWNLOADS = 2

#: A bucket left alone this long is full again, the same as a new one.
_MINUTE = 60.0


class RateLimiter:
    """The budgets; across the processes of a start of several, as budget
    *shared*, when that names one."""

    def __init__(self, *, shared: str | None = None) -> None:
        self._buckets: dict[tuple[str, str], TokenBucket] = {}
        self._lock = threading.Lock()
        self._shared = shared_budgets.State(shared) if shared else None

    def check(self, user_key: str, source_dir: str, per_minute: int) -> None:
        """Spend one request, or raise :class:`RateLimited`."""
        now = time.monotonic()
        key = (user_key or "-", source_dir)
        with self._lock:
            if self._shared is None or not shared_budgets.across_processes():
                allowed = self._take(key, per_minute, now)
            else:
                with self._shared.held() as state:
                    self._as_kept(state, now)
                    allowed = self._take(key, per_minute, now)
                    self._keep(state, now)
        if not allowed:
            raise RateLimited(
                f"too many requests to this source - it allows "
                f"{per_minute} per minute"
            )

    def _take(self, key: tuple[str, str], per_minute: int, now: float) -> bool:
        bucket = self._buckets.get(key)
        if bucket is None or bucket.capacity != float(per_minute):
            # A manifest edit changes the rate; rebuild rather than letting
            # the old capacity persist for the life of the process.
            bucket = TokenBucket(per_minute, per_minute / 60.0, now)
            self._buckets[key] = bucket
        return bucket.take(now)

    def _as_kept(self, state: dict, now: float) -> None:
        """Take up the buckets as the start's processes left them in *state*:
        ``"<user>\\n<source>": [per minute, tokens, last refill]``."""
        self._buckets = {}
        kept = state.get("buckets")
        for name, row in (kept.items() if isinstance(kept, dict) else ()):
            user_key, _, source_dir = str(name).partition("\n")
            try:
                per_minute = int(row[0])
            except (TypeError, ValueError, IndexError):  # not one Curio wrote
                continue
            self._buckets[(user_key, source_dir)] = TokenBucket.from_state(
                per_minute, per_minute / 60.0, row[1:], now)

    def _keep(self, state: dict, now: float) -> None:
        """Leave the buckets in *state*, but those left alone for a minute:
        each is full again, the same as a new one."""
        state["buckets"] = {
            f"{user_key}\n{source_dir}": [int(bucket.capacity), *bucket.state()]
            for (user_key, source_dir), bucket in self._buckets.items()
            if now - bucket.updated < _MINUTE
        }

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
            if self._shared is not None:
                self._shared.clear()


class DownloadSlots:
    """A per-user semaphore over downloads in flight; across the processes of
    a start of several, as budget *shared*, when that names one."""

    def __init__(self, limit: int = MAX_CONCURRENT_DOWNLOADS, *, shared: str | None = None) -> None:
        self.limit = limit
        self._held: dict[str, int] = {}
        self._lock = threading.Lock()
        self._places = shared_budgets.Places(shared) if shared else None
        #: The places this process holds, by user, in a start of several.
        self._taken: dict[str, list[shared_budgets.Place]] = {}

    def acquire(self, user_key: str) -> None:
        if self._places is not None and shared_budgets.across_processes():
            place = self._places.take(user_key, self.limit)
            if place is None:
                raise RateLimited(
                    f"you already have {self.limit} downloads running - wait for one to finish"
                )
            with self._lock:
                self._taken.setdefault(user_key, []).append(place)
            return
        with self._lock:
            held = self._held.get(user_key, 0)
            if held >= self.limit:
                raise RateLimited(
                    f"you already have {held} downloads running - wait for one to finish"
                )
            self._held[user_key] = held + 1

    def release(self, user_key: str) -> None:
        with self._lock:
            taken = self._taken.get(user_key)
            place = taken.pop() if taken else None
            if taken == []:
                del self._taken[user_key]
            if place is None:
                held = self._held.get(user_key, 0)
                if held <= 1:
                    self._held.pop(user_key, None)
                else:
                    self._held[user_key] = held - 1
        if place is not None:
            place.release()

    def reset(self) -> None:
        with self._lock:
            self._held.clear()
            taken = [place for places in self._taken.values() for place in places]
            self._taken.clear()
        for place in taken:
            place.release()


#: Process-wide instances, whose budgets hold across a start's processes.
limiter = RateLimiter(shared="discovery-requests")
download_slots = DownloadSlots(shared="discovery-downloads")
