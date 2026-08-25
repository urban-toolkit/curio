"""Append-only usage ledger with atomic reservations (memo ``dev/40``, `DEC-044`).

Replaces the dev/22/24 advisory counters outright (`REQ-QUOTA-001`,
`RISK-COST-001`): every run is a **reserve → settle pair** keyed by its
execution id, admission is one flock-guarded critical section (read the day's
aggregates → check every limit → append → fsync), and every aggregate is
derived from the single append-only stream — nothing is stored twice, nothing
can drift.

FS-backed per `DEC-040`::

    .curio/users/<key>/agents/ledger/<YYYY-MM-DD>.jsonl   # append-only entries
    .curio/users/<key>/agents/ledger/.lock                # flock guard

Entry kinds (the dev/05 usage-ledger-entry shape — corrections and settlements
append, never rewrite):

- ``reserve``: admission — reservation id (= the T1 executionId), template
  key, the monetary hold (the account's advisory estimate) and the immutable
  provider **price snapshot** pinned for later settlement.
- ``settle``: completion — Actual usage, status, and ``costUsd`` computed from
  the *pinned* snapshot (Actual-or-null, never estimated; memo dev/11).
  Idempotent: the first settle per reservation wins.
- ``usage``: housekeeping provider calls (the dev/25 title call) — counted,
  never run-counted, no reservation.
- ``seed``: the one-time same-day carry-over of the legacy ``quota.json``
  counts, so a deploy-day switch cannot re-open an exhausted quota.

Budget gate (`REQ-COST-001`) — the spend ladder, checked inside the critical
section::

    charged = actualSpendUsd            (settled runs with a real price)
            + settledEstimatedUsd       (settled runs without one: their held estimate)
            + heldUsd                   (in-flight reservations)
            + thisRunHold

with the **fail-closed rule**: a configured ``dailyBudgetUsd`` with neither an
estimate nor a table price makes the run's cost unknowable under a hard cap →
deny. A crashed run's hold self-expires at the day boundary (conservative;
lease-based reconciliation stays with background execution).

Locking mirrors ``projects/storage.py``: a per-account in-process
``threading.Lock`` (the Flask-threaded case, all platforms) plus
``fcntl.flock`` (cross-process, POSIX; degrades to thread-only on Windows
exactly as project-spec writes already do). Reads tolerate corrupt lines and
missing files, like every other FS store.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, time as _time, timedelta, timezone

try:  # POSIX advisory file locking; unavailable on Windows.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

from utk_curio.backend.app.agents import storage


class QuotaExceeded(Exception):
    """Raised when a run is denied (→ 429). ``reason`` is ``"quota"`` for a
    runs/day limit (account or project template) or ``"budget"`` for the
    monetary gate. (Moved here from ``quotas.py`` in T3 — ``quotas``
    re-exports it, so the route contract is unchanged.)"""

    def __init__(self, message: str, reset_at: str, reason: str = "quota"):
        super().__init__(message)
        self.reset_at = reset_at
        self.reason = reason


_ZERO_USAGE = {"inputTokens": 0, "outputTokens": 0}

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _account_lock(user_key: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(user_key)
        if lock is None:
            lock = threading.Lock()
            _locks[user_key] = lock
        return lock


def _ledger_dir(user_key: str):
    return storage.user_agents_dir(user_key) / "ledger"


def _day_path(user_key: str, day: str):
    return _ledger_dir(user_key) / f"{day}.jsonl"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return _now().date().isoformat()


def _reset_at(now: datetime) -> str:
    return datetime.combine(
        now.date() + timedelta(days=1), _time.min, tzinfo=timezone.utc
    ).isoformat()


@contextmanager
def _locked(user_key: str):
    """The reservation critical section: in-process lock + flock."""
    with _account_lock(user_key):
        directory = _ledger_dir(user_key)
        directory.mkdir(parents=True, exist_ok=True)
        handle = open(directory / ".lock", "a+")
        try:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX)
            yield
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()


def _read_entries(user_key: str, day: str) -> list[dict]:
    """The day's entries, oldest first; corrupt lines skipped, never fatal."""
    path = _day_path(user_key, day)
    if not path.exists():
        return []
    entries: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (ValueError, TypeError):
            continue  # append-only tolerance: a torn/corrupt line is skipped
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _append(user_key: str, day: str, entry: dict) -> None:
    path = _day_path(user_key, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _usage_counts(raw: object) -> dict:
    usage = raw if isinstance(raw, dict) else {}
    return {
        key: usage[key] if isinstance(usage.get(key), int) else 0
        for key in _ZERO_USAGE
    }


def _add_usage(total: dict, raw: object) -> None:
    counts = _usage_counts(raw)
    total["inputTokens"] += counts["inputTokens"]
    total["outputTokens"] += counts["outputTokens"]


def _cost_usd(price: dict | None, usage: dict | None) -> float | None:
    """Settlement math: Actual tokens × the pinned snapshot — or ``None``
    when either half is missing (Actual-or-absent, never estimated)."""
    if not isinstance(price, dict) or not isinstance(usage, dict):
        return None
    tokens_in = usage.get("inputTokens")
    tokens_out = usage.get("outputTokens")
    rate_in = price.get("inputUsdPerMtok")
    rate_out = price.get("outputUsdPerMtok")
    if not (
        isinstance(tokens_in, int)
        and isinstance(tokens_out, int)
        and isinstance(rate_in, (int, float))
        and isinstance(rate_out, (int, float))
    ):
        return None
    return round(tokens_in * rate_in / 1e6 + tokens_out * rate_out / 1e6, 6)


def _aggregate(entries: list[dict]) -> dict:
    runs = 0
    by_template: dict[str, int] = {}
    by_attachment: dict[str, int] = {}
    usage = dict(_ZERO_USAGE)
    actual = 0.0
    reserves: dict[str, float | None] = {}  # reservationId -> holdUsd
    settled: dict[str, float | None] = {}  # reservationId -> costUsd (first wins)
    for entry in entries:
        kind = entry.get("kind")
        if kind == "seed":
            if isinstance(entry.get("runs"), int):
                runs += entry["runs"]
            for key, count in (entry.get("byTemplate") or {}).items():
                if isinstance(key, str) and isinstance(count, int):
                    by_template[key] = by_template.get(key, 0) + count
            _add_usage(usage, entry.get("usage"))
        elif kind == "reserve":
            rid = entry.get("reservationId")
            if not isinstance(rid, str) or rid in reserves:
                continue
            hold = entry.get("holdUsd")
            reserves[rid] = float(hold) if isinstance(hold, (int, float)) else None
            runs += 1
            template_key = entry.get("templateKey")
            if isinstance(template_key, str):
                by_template[template_key] = by_template.get(template_key, 0) + 1
            attachment_key = entry.get("attachmentKey")
            if isinstance(attachment_key, str):  # absent on pre-dev/42 entries
                by_attachment[attachment_key] = by_attachment.get(attachment_key, 0) + 1
        elif kind == "settle":
            rid = entry.get("reservationId")
            if not isinstance(rid, str) or rid in settled:
                continue  # idempotent: the first settle per reservation wins
            cost = entry.get("costUsd")
            settled[rid] = float(cost) if isinstance(cost, (int, float)) else None
            _add_usage(usage, entry.get("usage"))
            if isinstance(cost, (int, float)):
                actual += float(cost)
        elif kind == "usage":
            _add_usage(usage, entry.get("usage"))
            cost = entry.get("costUsd")
            if isinstance(cost, (int, float)):
                actual += float(cost)
    held = sum(
        hold for rid, hold in reserves.items() if rid not in settled and hold is not None
    )
    settled_estimated = sum(
        hold
        for rid, hold in reserves.items()
        if rid in settled and settled[rid] is None and hold is not None
    )
    return {
        "runs": runs,
        "byTemplate": by_template,
        "byAttachment": by_attachment,
        "usage": usage,
        "actualSpendUsd": round(actual, 6),
        "heldUsd": round(held, 6),
        "settledEstimatedUsd": round(settled_estimated, 6),
    }


def _legacy_seed_entry(user_key: str, day: str) -> dict | None:
    """The one-time same-day carry-over of the retired advisory counters.

    Read exactly once per account (only when the day has no ledger file yet)
    so a deploy-day switch can neither re-open an exhausted quota nor re-zero
    the token counters. A cross-day or missing/corrupt legacy file seeds
    nothing (the window naturally reset)."""
    path = storage.user_agents_dir(user_key) / "quota.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("window") != day:
        return None
    if not isinstance(data.get("runs"), int):
        return None
    by_template = {
        key: count
        for key, count in (data.get("byTemplate") or {}).items()
        if isinstance(key, str) and isinstance(count, int)
    } if isinstance(data.get("byTemplate"), dict) else {}
    return {
        "kind": "seed",
        "ts": _now().isoformat(),
        "runs": data["runs"],
        "byTemplate": by_template,
        "usage": _usage_counts(data.get("usage")),
    }


def aggregates(user_key: str, day: str | None = None) -> dict:
    """The window's derived totals (missing/stale/corrupt reads as zeros).

    Includes the legacy same-day counts even before the first reserve of the
    day materializes the seed entry, so the settings surfaces never under-
    report across the deploy-day switch."""
    day = day or _today()
    entries = _read_entries(user_key, day)
    if not entries:
        seed = _legacy_seed_entry(user_key, day)
        if seed is not None:
            entries = [seed]
    return _aggregate(entries)


def reserve(
    user_key: str,
    *,
    account_limit: int,
    template_key: str | None = None,
    template_limit: int | None = None,
    attachment_key: str | None = None,
    attachment_limit: int | None = None,
    daily_budget_usd: float | None = None,
    estimated_cost_per_run_usd: float | None = None,
    price: dict | None = None,
    reservation_id: str | None = None,
) -> dict:
    """Atomically admit one run, or raise :class:`QuotaExceeded`.

    One critical section owns admission: read the day's aggregates, check the
    account limit → the template limit → the attachment limit (dev/42) → the
    budget spend ladder, append the reserve entry. Two concurrent last-slot
    attempts serialize; exactly one admits (`REQ-QUOTA-001`). *price* is the
    immutable snapshot pinned for settlement (`dev/05`:1242); a table edit
    mid-day never rewrites what an earlier run was charged.
    ``attachment_key`` is always recorded when given (attribution);
    ``attachment_limit`` gates only when an attachment-scope runs/day limit
    binds. Denial appends and consumes nothing."""
    now = _now()
    day = now.date().isoformat()
    with _locked(user_key):
        entries = _read_entries(user_key, day)
        if not entries:
            seed = _legacy_seed_entry(user_key, day)
            if seed is not None:
                _append(user_key, day, seed)
                entries = [seed]
        agg = _aggregate(entries)
        if agg["runs"] >= account_limit:
            raise QuotaExceeded(
                f"daily agent-run limit reached ({account_limit}/day)", _reset_at(now)
            )
        if template_key is not None and template_limit is not None:
            if agg["byTemplate"].get(template_key, 0) >= template_limit:
                raise QuotaExceeded(
                    f"this agent's project run limit is reached ({template_limit}/day)",
                    _reset_at(now),
                )
        if attachment_key is not None and attachment_limit is not None:
            if agg["byAttachment"].get(attachment_key, 0) >= attachment_limit:
                raise QuotaExceeded(
                    f"this attachment's run limit is reached ({attachment_limit}/day)",
                    _reset_at(now),
                )
        hold: float | None = None
        if estimated_cost_per_run_usd is not None:
            hold = float(estimated_cost_per_run_usd)
        if daily_budget_usd is not None:
            if hold is None and price is None:
                # REQ-COST-001 fail-closed: a hard monetary cap with neither
                # an estimate nor a price makes the run's cost unknowable.
                raise QuotaExceeded(
                    "a daily budget is set but no cost estimate or price is "
                    "configured — set one, or clear the budget",
                    _reset_at(now),
                    reason="budget",
                )
            charged = round(
                agg["actualSpendUsd"]
                + agg["settledEstimatedUsd"]
                + agg["heldUsd"]
                + (hold or 0.0),
                6,
            )
            if charged > daily_budget_usd:
                raise QuotaExceeded(
                    f"daily agent budget reached (~${charged:.2f} of "
                    f"${daily_budget_usd:.2f})",
                    _reset_at(now),
                    reason="budget",
                )
        rid = reservation_id or uuid.uuid4().hex
        _append(
            user_key,
            day,
            {
                "kind": "reserve",
                "reservationId": rid,
                "ts": now.isoformat(),
                "templateKey": template_key,
                "attachmentKey": attachment_key,
                "holdUsd": hold,
                "holdSource": "estimate" if hold is not None else None,
                "price": price,
            },
        )
        return {"reservationId": rid, "day": day, "holdUsd": hold, "price": price}


def settle(
    user_key: str, reservation: dict, *, usage: dict | None = None, status: str = "ok"
) -> dict:
    """Settle one reservation with its Actual usage (idempotent, appended to
    the reservation's own day — a run crossing midnight settles into the day
    it was admitted). ``costUsd`` comes from the pinned snapshot × Actual
    tokens, or ``None`` when either is missing. A settle whose reservation is
    unknown still appends and counts — usage is never lost."""
    day = reservation.get("day") or _today()
    rid = reservation.get("reservationId", "")
    with _locked(user_key):
        for entry in _read_entries(user_key, day):
            if entry.get("kind") == "settle" and entry.get("reservationId") == rid:
                return entry  # first-write-wins idempotence
        entry = {
            "kind": "settle",
            "reservationId": rid,
            "ts": _now().isoformat(),
            "status": status,
            "usage": _usage_counts(usage) if usage else None,
            "costUsd": _cost_usd(reservation.get("price"), usage),
        }
        _append(user_key, day, entry)
        return entry


def record_housekeeping_usage(
    user_key: str, usage: dict | None, *, price: dict | None = None, note: str = "housekeeping"
) -> None:
    """Count an internal provider call (the dev/25 title call): tokens and —
    when priced — cost, never run-counted, no reservation (the T1 rule: the
    counters may exceed what the transcript's execution records sum to)."""
    if not usage:
        return
    day = _today()
    with _locked(user_key):
        _append(
            user_key,
            day,
            {
                "kind": "usage",
                "ts": _now().isoformat(),
                "note": note,
                "usage": _usage_counts(usage),
                "costUsd": _cost_usd(price, usage),
            },
        )
