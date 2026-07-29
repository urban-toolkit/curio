"""Quota facade over the usage ledger (memos ``dev/22``/``dev/24``/``dev/40``).

The v1 advisory counters that lived here (``admit``/``check_and_count``/
``record_usage`` over ``quota.json``) are **retired** — T3 (memo dev/40,
`DEC-044`) replaced them with the atomic append-only ledger in
:mod:`utk_curio.backend.app.agents.ledger`, which owns admission
(:func:`ledger.reserve`), settlement, and the budget gate. The legacy
``quota.json`` window is read exactly once per account as the ledger's
same-day seed and never written again.

What remains here: the deployment runs/day limit (env-derived, consumed by
``policy.deployment_defaults``) and the read-only today-aggregates the
settings surfaces consume — thin views over :func:`ledger.aggregates`.
``QuotaExceeded`` is re-exported so the route contract (429 body, ``reason``)
is unchanged.
"""

from __future__ import annotations

import os

from utk_curio.backend.app.agents import ledger
from utk_curio.backend.app.agents.ledger import QuotaExceeded  # noqa: F401 — re-export

DEFAULT_RUNS_PER_DAY = 200


def runs_per_day_limit() -> int:
    raw = os.environ.get("CURIO_AGENT_RUNS_PER_DAY", "")
    try:
        value = int(raw)
        return value if value > 0 else DEFAULT_RUNS_PER_DAY
    except ValueError:
        return DEFAULT_RUNS_PER_DAY


def runs_used_today(user_key: str) -> int:
    """Runs reserved in the current window (0 for a missing/stale ledger)."""
    return ledger.aggregates(user_key)["runs"]


def usage_today(user_key: str) -> dict:
    """Actual tokens counted in the current window (settled runs plus
    housekeeping calls; zeros when nothing has settled)."""
    return ledger.aggregates(user_key)["usage"]
