"""Read-only views over the local usage ledger.

The name is historical. There are no quotas: this module once resolved a
deployment run ceiling from ``CURIO_AGENT_RUNS_PER_DAY`` and re-exported the
``QuotaExceeded`` the ledger raised on denial. Curio no longer caps agent runs
at any scope, so neither exists and no run is ever denied for usage.

What is left are the two aggregate reads over
:mod:`utk_curio.backend.app.agents.ledger`, kept as a facade so callers do not
reach into the entry format.
"""

from __future__ import annotations

from utk_curio.backend.app.agents import ledger


def runs_used_today(user_key: str) -> int:
    """Runs started in the current window (0 for a missing/stale ledger)."""
    return ledger.aggregates(user_key)["runs"]


def usage_today(user_key: str) -> dict:
    """Actual tokens counted in the current window (settled runs plus
    housekeeping calls; zeros when nothing has settled)."""
    return ledger.aggregates(user_key)["usage"]
