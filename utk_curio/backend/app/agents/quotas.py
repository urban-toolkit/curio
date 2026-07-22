"""Basic quota admission — simple FS counters (memo ``dev/22``, v1).

Per-account daily run counters in ``.curio/users/<key>/agents/quota.json``
(``DEC-040`` — filesystem, no DB). Deliberately *advisory* simple counts, not
the v2 atomic reservation/ledger model (``REQ-QUOTA-001``): racing writers may
briefly over-admit by one, which is accepted at this stage. The limit is
fail-closed via ``CURIO_AGENT_RUNS_PER_DAY`` (interim default 200/day; the
settings screens later own tuning). Denial is stable and non-destructive —
nothing is persisted or consumed on a 429.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, time, timedelta, timezone

from utk_curio.backend.app.agents import storage

DEFAULT_RUNS_PER_DAY = 200


class QuotaExceeded(Exception):
    """Raised when the account's daily run quota is exhausted (→ 429)."""

    def __init__(self, message: str, reset_at: str):
        super().__init__(message)
        self.reset_at = reset_at


def runs_per_day_limit() -> int:
    raw = os.environ.get("CURIO_AGENT_RUNS_PER_DAY", "")
    try:
        value = int(raw)
        return value if value > 0 else DEFAULT_RUNS_PER_DAY
    except ValueError:
        return DEFAULT_RUNS_PER_DAY


def _quota_path(user_key: str):
    return storage.user_agents_dir(user_key) / "quota.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_window(user_key: str, today: str) -> dict:
    """The current counter window; a missing/corrupt/stale file reads as fresh."""
    path = _quota_path(user_key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict) or data.get("window") != today or not isinstance(
        data.get("runs"), int
    ):
        return {"window": today, "runs": 0}
    return data


def check_and_count(user_key: str, limit: int | None = None) -> int:
    """Admit one agent run and count it, or raise :class:`QuotaExceeded`.

    Returns the runs used so far today (including this one). Called after
    request validation and before provider dispatch, so a denied run never
    reaches a provider and an invalid request never consumes quota.
    """
    if limit is None:
        limit = runs_per_day_limit()
    now = _now()
    today = now.date().isoformat()
    data = _read_window(user_key, today)
    if data["runs"] >= limit:
        reset_at = datetime.combine(
            now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc
        ).isoformat()
        raise QuotaExceeded(
            f"daily agent-run limit reached ({limit}/day)", reset_at
        )
    data["runs"] += 1
    path = _quota_path(user_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data["runs"]
