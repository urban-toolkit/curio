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
    """Raised when a run is denied (→ 429). ``reason`` is ``"quota"`` for a
    runs/day limit (account or project template) or ``"budget"`` for the
    estimated daily-budget gate (memo dev/24)."""

    def __init__(self, message: str, reset_at: str, reason: str = "quota"):
        super().__init__(message)
        self.reset_at = reset_at
        self.reason = reason


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
    """The current counter window; a missing/corrupt/stale file reads as fresh.

    ``byTemplate`` holds per-project-template counts keyed ``"<pid>/<coord>"``
    (memo dev/24 — project-scope runs/day limits); it expires with the window.
    """
    path = _quota_path(user_key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict) or data.get("window") != today or not isinstance(
        data.get("runs"), int
    ):
        return {"window": today, "runs": 0, "byTemplate": {}}
    if not isinstance(data.get("byTemplate"), dict):
        data["byTemplate"] = {}
    return data


def _reset_at(now: datetime) -> str:
    return datetime.combine(
        now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc
    ).isoformat()


def admit(
    user_key: str,
    *,
    account_limit: int,
    template_key: str | None = None,
    template_limit: int | None = None,
    daily_budget_usd: float | None = None,
    estimated_cost_per_run_usd: float | None = None,
) -> int:
    """Admit one agent run against the effective policy, or raise
    :class:`QuotaExceeded` (memo dev/24).

    Checks, in order: the account runs/day limit, the project-template
    runs/day limit (when one applies), and the estimated daily budget (active
    only when both budget and estimate are configured). Denial consumes and
    persists nothing. Returns the account runs used today (incl. this one).
    Called after request validation and before provider dispatch.
    """
    now = _now()
    today = now.date().isoformat()
    data = _read_window(user_key, today)
    if data["runs"] >= account_limit:
        raise QuotaExceeded(
            f"daily agent-run limit reached ({account_limit}/day)", _reset_at(now)
        )
    if template_key is not None and template_limit is not None:
        used = data["byTemplate"].get(template_key, 0)
        if isinstance(used, int) and used >= template_limit:
            raise QuotaExceeded(
                f"this agent's project run limit is reached ({template_limit}/day)",
                _reset_at(now),
            )
    if daily_budget_usd is not None and estimated_cost_per_run_usd is not None:
        # Rounded so IEEE noise (3 × 0.1 > 0.3) can't deny a run early.
        projected = round((data["runs"] + 1) * estimated_cost_per_run_usd, 6)
        if projected > daily_budget_usd:
            raise QuotaExceeded(
                f"daily agent budget reached (estimated ~${projected:.2f} of "
                f"${daily_budget_usd:.2f})",
                _reset_at(now),
                reason="budget",
            )
    data["runs"] += 1
    if template_key is not None:
        used = data["byTemplate"].get(template_key, 0)
        data["byTemplate"][template_key] = (used if isinstance(used, int) else 0) + 1
    path = _quota_path(user_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data["runs"]


def check_and_count(user_key: str, limit: int | None = None) -> int:
    """Back-compat shim over :func:`admit` with only the account limit."""
    return admit(user_key, account_limit=limit if limit is not None else runs_per_day_limit())


def runs_used_today(user_key: str) -> int:
    """Runs counted in the current window (0 for a missing/stale/corrupt file)."""
    return _read_window(user_key, _now().date().isoformat())["runs"]


def _usage_counts(data: dict) -> dict:
    """The window's Actual usage counters, normalized (missing/malformed → 0)."""
    usage = data.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return {
        key: usage[key] if isinstance(usage.get(key), int) else 0
        for key in ("inputTokens", "outputTokens")
    }


def record_usage(user_key: str, input_tokens: object, output_tokens: object) -> None:
    """Add one run's Actual token usage to the daily window (memo dev/37).

    Advisory, like the run counters (ledgers are the T3 replacement): recorded
    post-run, so a denial never counts and racing writers may briefly
    under-count. Only provider-reported integers are added — never estimates
    (memo dev/11). The counters include internal housekeeping calls (e.g. the
    dev/25 title call), so they may exceed what the transcript's execution
    records sum to.
    """
    if not (isinstance(input_tokens, int) and isinstance(output_tokens, int)):
        return
    now = _now()
    data = _read_window(user_key, now.date().isoformat())
    usage = _usage_counts(data)
    usage["inputTokens"] += input_tokens
    usage["outputTokens"] += output_tokens
    data["usage"] = usage
    path = _quota_path(user_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def usage_today(user_key: str) -> dict:
    """Actual tokens counted in the current window (zeros for a missing/stale/
    corrupt file or a window that predates usage capture)."""
    return _usage_counts(_read_window(user_key, _now().date().isoformat()))
