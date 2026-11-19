"""A request budget per visitor address, under a budget for everyone.

Both buckets matter: the one per address stops a single browser in a loop,
the overall one stops a spread-out flood. A request spends a token from both
buckets or from neither, so the refused requests of one browser leave the
overall allowance to everyone else. A bucket left alone for a minute is full
again, the same as a new one, so once a minute those are dropped and the table
holds only recent addresses.

In this process's memory; one named with *shared* holds across the backend
processes of a start that runs several (``shared_budgets.State``), where each
address is kept as a digest, so no file holds visitors' addresses.

The monitor's client error reports (``monitor/routes.py``), which only the home
process takes, and a dashboard viewer's runs (``runs/viewer.py``), whose
dashboards several processes own, each hold one.
"""

from __future__ import annotations

import hashlib
import threading

from utk_curio.backend.app.common import shared_budgets
from utk_curio.backend.app.common.token_bucket import TokenBucket

_MINUTE = 60.0


class AddressLimiter:
    """*per_address_per_minute* requests a minute from one address, and
    *overall_per_minute* from all of them together; across the processes of
    a start of several, as budget *shared*, when that names one."""

    def __init__(self, per_address_per_minute: int, overall_per_minute: int, *, shared: str | None = None) -> None:
        self.per_address_per_minute = per_address_per_minute
        self.overall_per_minute = overall_per_minute
        self._lock = threading.Lock()
        self._shared = shared_budgets.State(shared) if shared else None
        self._start_over()

    def reset(self) -> None:
        self._start_over()
        if self._shared is not None:
            self._shared.clear()

    def _start_over(self) -> None:
        with self._lock:
            self.overall: TokenBucket | None = None
            self.per_address: dict[str, TokenBucket] = {}
            self.swept_at: float | None = None

    def allow(self, key: str, now: float) -> bool:
        with self._lock:
            if self._shared is None or not shared_budgets.across_processes():
                return self._allow(key, now)
            with self._shared.held() as state:
                self._as_kept(state, now)
                allowed = self._allow(_digest(key), now)
                self._keep(state)
            return allowed

    def _allow(self, key: str, now: float) -> bool:
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

    def _as_kept(self, state: dict, now: float) -> None:
        """Take up the buckets as the start's processes left them in *state*."""
        overall = state.get("overall")
        self.overall = None if overall is None else TokenBucket.from_state(
            self.overall_per_minute, self.overall_per_minute / _MINUTE, overall, now)
        addresses = state.get("addresses")
        self.per_address = {
            str(key): TokenBucket.from_state(
                self.per_address_per_minute, self.per_address_per_minute / _MINUTE, kept, now)
            for key, kept in (addresses.items() if isinstance(addresses, dict) else ())
        }
        swept = state.get("swept")
        self.swept_at = float(swept) if isinstance(swept, (int, float)) else None

    def _keep(self, state: dict) -> None:
        """Leave the buckets in *state* for the start's processes."""
        state["overall"] = None if self.overall is None else self.overall.state()
        state["addresses"] = {key: bucket.state() for key, bucket in self.per_address.items()}
        state["swept"] = self.swept_at


def _digest(address: str) -> str:
    """An address as a shared budget keeps it."""
    return hashlib.sha256(f"{shared_budgets.BOOT_ID}\n{address}".encode("utf-8")).hexdigest()[:32]
