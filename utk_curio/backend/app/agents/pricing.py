"""Deployment-owned provider price table (memo ``dev/40``, `DEC-044`).

Actual USD exists exactly when the **operator** states a price — the built-in
table is empty: Curio's default provider is a self-hosted aiconn endpoint with
no per-token USD price, and fabricating one would violate memo 11's honesty
rule (Actual is provider-grounded or absent, never invented).

Source: a JSON file at ``.curio/agents-pricing.json`` (path overridable via
``CURIO_AGENT_PRICE_TABLE``), mapping ``"<provider>/<model>"`` →
``{"inputUsdPerMtok": x, "outputUsdPerMtok": y, "effectiveDate": "YYYY-MM-DD"}``::

    {
      "openai_compatible/gemma4": {"inputUsdPerMtok": 0.0, "outputUsdPerMtok": 0.0},
      "anthropic/claude-sonnet-5": {"inputUsdPerMtok": 3.0, "outputUsdPerMtok": 15.0,
                                     "effectiveDate": "2026-07-01"}
    }

A missing/corrupt file ≡ empty table (standard FS tolerance). Snapshots are
resolved per run at reservation time and pinned into the ledger's reserve
entry (`dev/05`:1242 — immutable per-reservation attribution): editing the
table mid-day never rewrites what an earlier run was charged. Settlement math
lives with the ledger (`ledger._cost_usd`), fed by these snapshots.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PRICE_TABLE_ENV = "CURIO_AGENT_PRICE_TABLE"
PRICE_TABLE_FILENAME = "agents-pricing.json"


def _launch_dir() -> Path:
    return Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))


def _table_path() -> Path:
    override = os.environ.get(PRICE_TABLE_ENV)
    if override:
        return Path(override)
    return _launch_dir() / ".curio" / PRICE_TABLE_FILENAME


def _load_table() -> dict:
    """The operator's table; missing/corrupt/non-object reads as empty.

    Read per resolution (the file is tiny) — no process-lifetime cache to go
    stale between an operator edit and the next run."""
    try:
        data = json.loads(_table_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def price_snapshot(provider: str, model: str) -> dict | None:
    """The immutable per-run snapshot for ``<provider>/<model>``, or ``None``.

    ``None`` means "no USD price is configured" — the honest state for
    self-hosted providers; nothing downstream may substitute an estimate into
    an Actual field. A malformed table entry is treated as absent."""
    entry = _load_table().get(f"{provider}/{model}")
    if not isinstance(entry, dict):
        return None
    rate_in = entry.get("inputUsdPerMtok")
    rate_out = entry.get("outputUsdPerMtok")
    if not (isinstance(rate_in, (int, float)) and isinstance(rate_out, (int, float))):
        return None
    if rate_in < 0 or rate_out < 0:
        return None
    effective = entry.get("effectiveDate")
    return {
        "inputUsdPerMtok": float(rate_in),
        "outputUsdPerMtok": float(rate_out),
        "effectiveDate": effective if isinstance(effective, str) else None,
        "currency": "USD",
    }
