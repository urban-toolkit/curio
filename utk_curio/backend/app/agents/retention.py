"""Deployment-owned retention declaration + sweep (memo dev/87, ``DEC-057``).

DEC-057's honesty rule made mechanical: retention durations are never invented
by the platform — they exist exactly when the **operator** declares them, in a
JSON file at ``.curio/agents-retention.json`` (path overridable via
``CURIO_AGENT_RETENTION``; the ``agents-pricing.json`` pattern)::

    {
      "backups": "none" | {"expiryDays": 30},
      "ledger": {"archiveAfterDays": 365},
      "closure": {"graceDays": 14}
    }

Absent/empty ≡ the DEC-057 defaults: **no automatic expiry anywhere**, backup
posture *undeclared* (and the UI copy says so — see the frontend's
``retentionCopy``). The sweep enforces ONLY declared values: with
``ledger.archiveAfterDays`` set, day files older than the age are MOVED into
``ledger/archive/`` — the append-only ledger is archived, never rewritten
(``DEC-044`` unchanged). Unknown declaration keys are logged loudly: a rule the
operator wrote but nothing enforces must never be silent.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

RETENTION_ENV = "CURIO_AGENT_RETENTION"
RETENTION_FILENAME = "agents-retention.json"

_KNOWN_KEYS = {"backups", "ledger", "closure"}
_LEDGER_DAY_FILE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.jsonl$")


def _launch_dir() -> Path:
    return Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))


def _declaration_path() -> Path:
    override = os.environ.get(RETENTION_ENV)
    if override:
        return Path(override)
    return _launch_dir() / ".curio" / RETENTION_FILENAME


def load_declaration() -> dict:
    """The operator's declaration; missing/corrupt/non-object reads as empty.

    Read per call (tiny file) so an operator edit needs no restart to be seen.
    Unknown top-level keys are reported (once per read) — declared-but-
    unenforced must be loud, never silently ignored.
    """
    try:
        data = json.loads(_declaration_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    unknown = sorted(set(data) - _KNOWN_KEYS)
    if unknown:
        log.warning(
            "agents-retention.json declares keys nothing enforces: %s "
            "(known: %s) — these rules are NOT applied",
            ", ".join(unknown), ", ".join(sorted(_KNOWN_KEYS)),
        )
    return data


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def backup_posture(declaration: dict | None = None) -> object:
    """``"none"`` | ``{"expiryDays": N}`` | ``None`` (undeclared)."""
    decl = load_declaration() if declaration is None else declaration
    raw = decl.get("backups")
    if raw == "none":
        return "none"
    if isinstance(raw, dict):
        days = _positive_int(raw.get("expiryDays"))
        if days is not None:
            return {"expiryDays": days}
    return None


def ledger_archive_after_days(declaration: dict | None = None) -> int | None:
    decl = load_declaration() if declaration is None else declaration
    raw = decl.get("ledger")
    return _positive_int(raw.get("archiveAfterDays")) if isinstance(raw, dict) else None


def closure_grace_days(declaration: dict | None = None) -> int | None:
    decl = load_declaration() if declaration is None else declaration
    raw = decl.get("closure")
    return _positive_int(raw.get("graceDays")) if isinstance(raw, dict) else None


def public_declaration() -> dict:
    """The shape ``GET /api/config/public`` serves — ``null`` = undeclared,
    so the frontend's deletion copy can be honest about the gap."""
    decl = load_declaration()
    return {
        "backups": backup_posture(decl),
        "ledgerArchiveAfterDays": ledger_archive_after_days(decl),
        "closureGraceDays": closure_grace_days(decl),
    }


def _users_base() -> Path:
    return (_launch_dir() / ".curio" / "users").resolve()


def run_retention_sweep(today: date | None = None) -> dict:
    """Enforce ONLY declared retention (DEC-057 §3.3). Best-effort: failures
    are logged per file and never raise — retention housekeeping must never
    take the server down.

    Currently one declared class exists: ``ledger.archiveAfterDays`` moves
    every user's ledger day files older than the age into ``ledger/archive/``
    byte-identically (``shutil.move`` — archived, never rewritten). Returns
    ``{"ledgerFilesArchived": n}``.
    """
    archived = 0
    age_days = ledger_archive_after_days()
    if age_days is None:
        return {"ledgerFilesArchived": 0}
    cutoff = (today or date.today()) - timedelta(days=age_days)
    base = _users_base()
    if not base.is_dir():
        return {"ledgerFilesArchived": 0}
    for user_dir in sorted(base.iterdir()):
        ledger_dir = user_dir / "agents" / "ledger"
        if not ledger_dir.is_dir():
            continue
        for entry in sorted(ledger_dir.iterdir()):
            m = _LEDGER_DAY_FILE.match(entry.name)
            if m is None or not entry.is_file():
                continue  # .lock, archive/, and anything non-day-file stay put
            try:
                file_day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            if file_day >= cutoff:
                continue
            target = ledger_dir / "archive" / entry.name
            if target.exists():
                log.warning("retention sweep: %s already archived — skipped, never overwritten", entry)
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(entry), str(target))
                archived += 1
            except OSError:
                log.warning("retention sweep: could not archive %s", entry, exc_info=True)
    if archived:
        log.info("retention sweep archived %d ledger day file(s)", archived)
    return {"ledgerFilesArchived": archived}
