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

def runs_per_day_limit() -> int | None:
    """The deployment ceiling on runs per user per day, or ``None`` for none.

    Curio ships **no** run cap. It used to default to 200/day, which meant an
    install nobody had configured still enforced a number Curio picked: the
    operator pays for the tokens, so the ceiling is theirs to set, not ours to
    assume. ``None`` is the same "unset, no gate" the sibling knob
    ``cost.dailyBudgetUsd`` has always used, and ``policy._resolve`` already
    treats a ``None`` deployment value as "no ceiling, any user value stands".

    Set ``CURIO_AGENT_RUNS_PER_DAY`` to impose one. A non-numeric or
    non-positive value is treated as unset rather than silently substituting a
    number of our own.
    """
    raw = os.environ.get("CURIO_AGENT_RUNS_PER_DAY", "")
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def runs_used_today(user_key: str) -> int:
    """Runs reserved in the current window (0 for a missing/stale ledger)."""
    return ledger.aggregates(user_key)["runs"]


def usage_today(user_key: str) -> dict:
    """Actual tokens counted in the current window (settled runs plus
    housekeeping calls; zeros when nothing has settled)."""
    return ledger.aggregates(user_key)["usage"]
