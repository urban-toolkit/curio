"""A token bucket: a request budget that refills continuously.

A bucket holds at most ``capacity`` tokens and earns ``per_second`` of them
back as time passes; each request spends one. Refill is continuous rather than
per window, which avoids the burst-at-the-boundary that a fixed window has: a
burst that crosses a boundary gets one allowance, not two.

Every call takes the time (``time.monotonic()``) from its caller, so a test
moves a bucket's clock by hand.
"""

from __future__ import annotations


class TokenBucket:
    __slots__ = ("capacity", "per_second", "tokens", "updated")

    def __init__(self, capacity: int, per_second: float, now: float) -> None:
        self.capacity = float(capacity)
        self.per_second = per_second
        self.tokens = float(capacity)
        self.updated = now

    def refill(self, now: float) -> float:
        """Earn the tokens due since the last call; return how many there are."""
        if now > self.updated:
            earned = (now - self.updated) * self.per_second
            self.tokens = min(self.capacity, self.tokens + earned)
            self.updated = now
        return self.tokens

    def take(self, now: float) -> bool:
        """Spend one token, or refuse when there is none."""
        if self.refill(now) < 1.0:
            return False
        self.tokens -= 1.0
        return True
