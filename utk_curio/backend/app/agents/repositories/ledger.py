"""Append-only local record of agent runs and token usage.

This used to be a gate as well as a record: it held per-day run limits, a
monetary spend ladder, and a fail-closed rule that denied a run whose cost was
unknowable under a hard cap. All of that is gone. Curio does not meter, cap, or
bill agent runs - the tokens are billed to whoever's key is in use, so the
ceiling is theirs to impose rather than Curio's to assume - and the interface
that configured those limits has been removed along with them.

What remains is bookkeeping, written from token counts each provider already
returns on the completion itself. Nothing is polled, no usage or billing API is
ever called, and no USD figure is computed: Curio has no price table and would
have to invent the numbers.

FS-backed::

    .curio/users/<key>/agents/ledger/<YYYY-MM-DD>.jsonl   # append-only entries
    .curio/users/<key>/agents/ledger/.lock                # flock guard

Entry kinds (corrections and settlements append, never rewrite):

- ``reserve``: a run starts - reservation id (= the executionId), template key
  and attachment key for attribution.
- ``settle``: it finishes - actual token usage and status. Idempotent: the
  first settle per reservation wins.
- ``usage``: an internal provider call (the title call) - counted as tokens,
  never as a run, with no reservation.

The reserve/settle pair is kept rather than collapsed into one entry because it
is what makes a crashed run visible: a reserve with no settle is a run that
started and never reported back.

Locking mirrors ``projects/storage.py``: a per-account in-process
``threading.Lock`` (the Flask-threaded case, all platforms) plus
``fcntl.flock`` (cross-process, POSIX; degrades to thread-only on Windows
exactly as project-spec writes already do). Reads tolerate corrupt lines and
missing files, like every other FS store.

A line is written under that lock and synced to disk once the lock is let go
(:func:`_locked`), as storage syncs what a writer of a dataflow wrote
(``storage.sync_when_free``): on a strained disk one sync takes seconds, and
each run of an account appends three lines (its reserve, its settle and its
title's usage), so a sync under the lock queued every run of the account
behind the others'. The run that appends still returns only once its line is
on disk.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

try:  # POSIX advisory file locking; unavailable on Windows.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

from utk_curio.backend.app.agents.repositories import storage

_ZERO_USAGE = {"inputTokens": 0, "outputTokens": 0}
#: Counted when a provider reports them: inputTokens already includes both.
_CACHE_KEYS = ("cacheReadTokens", "cacheWriteTokens")

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


@contextmanager
def _locked(user_key: str):
    """The append critical section: in-process lock + flock. It yields the
    list :func:`_append` puts each file it wrote in, each synced to disk once
    both locks are let go (:func:`_sync`)."""
    written: list[int] = []
    ended = False
    try:
        with _account_lock(user_key):
            directory = _ledger_dir(user_key)
            directory.mkdir(parents=True, exist_ok=True)
            handle = open(directory / ".lock", "a+")
            try:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_EX)
                yield written
            finally:
                try:
                    if fcntl is not None:
                        fcntl.flock(handle, fcntl.LOCK_UN)
                finally:
                    handle.close()
        ended = True
    finally:
        _sync(written, raising=ended)


def _sync(written: list[int], *, raising: bool = True) -> None:
    """Sync each file a locked block wrote to disk, then close it, with no
    lock held. A sync that fails raises once all are done, as it did under
    the lock, unless the block failed already, whose error stands."""
    failed = None
    for descriptor in written:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            failed = failed or exc
        finally:
            os.close(descriptor)
    if failed is not None and raising:
        raise failed


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


def _append(user_key: str, day: str, entry: dict, written: list[int]) -> None:
    """Write *entry*'s line, whole, under the block of :func:`_locked`, which
    syncs it to disk once the block lets its locks go (*written*)."""
    path = _day_path(user_key, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
        handle.flush()
        written.append(os.dup(handle.fileno()))


def _usage_counts(raw: object) -> dict:
    usage = raw if isinstance(raw, dict) else {}
    counts = {
        key: usage[key] if isinstance(usage.get(key), int) else 0
        for key in _ZERO_USAGE
    }
    counts.update({key: usage[key] for key in _CACHE_KEYS if isinstance(usage.get(key), int)})
    return counts


def _add_usage(total: dict, raw: object) -> None:
    counts = _usage_counts(raw)
    total["inputTokens"] += counts["inputTokens"]
    total["outputTokens"] += counts["outputTokens"]
    for key in _CACHE_KEYS:
        if key in counts:
            total[key] = total.get(key, 0) + counts[key]


def _aggregate(entries: list[dict]) -> dict:
    runs = 0
    by_template: dict[str, int] = {}
    by_attachment: dict[str, int] = {}
    usage = dict(_ZERO_USAGE)
    seen: set[str] = set()
    settled: set[str] = set()
    for entry in entries:
        kind = entry.get("kind")
        if kind == "reserve":
            rid = entry.get("reservationId")
            if not isinstance(rid, str) or rid in seen:
                continue
            seen.add(rid)
            runs += 1
            template_key = entry.get("templateKey")
            if isinstance(template_key, str):
                by_template[template_key] = by_template.get(template_key, 0) + 1
            attachment_key = entry.get("attachmentKey")
            if isinstance(attachment_key, str):
                by_attachment[attachment_key] = by_attachment.get(attachment_key, 0) + 1
        elif kind == "settle":
            rid = entry.get("reservationId")
            if not isinstance(rid, str) or rid in settled:
                continue  # idempotent: the first settle per reservation wins
            settled.add(rid)
            _add_usage(usage, entry.get("usage"))
        elif kind == "usage":
            _add_usage(usage, entry.get("usage"))
    return {
        "runs": runs,
        "byTemplate": by_template,
        "byAttachment": by_attachment,
        "usage": usage,
    }


def aggregates(user_key: str, day: str | None = None) -> dict:
    """The window's derived totals (missing/corrupt reads as zeros)."""
    return _aggregate(_read_entries(user_key, day or _today()))


def reserve(
    user_key: str,
    *,
    template_key: str | None = None,
    attachment_key: str | None = None,
    reservation_id: str | None = None,
    llm_config_id: str | None = None,
) -> dict:
    """Record that one run is starting. Never denies: nothing is capped.

    The append still happens under the lock so concurrent runs cannot tear a
    line, and the returned handle is what :func:`settle` closes.
    ``llm_config_id`` is the LLM configuration that answers the run (None for
    the deployment's own).
    """
    now = _now()
    day = now.date().isoformat()
    rid = reservation_id or uuid.uuid4().hex
    with _locked(user_key) as written:
        _append(
            user_key,
            day,
            {
                "kind": "reserve",
                "reservationId": rid,
                "ts": now.isoformat(),
                "templateKey": template_key,
                "attachmentKey": attachment_key,
                "llmConfigId": llm_config_id,
            },
            written,
        )
    return {"reservationId": rid, "day": day}


def settle(
    user_key: str, reservation: dict, *, usage: dict | None = None, status: str = "ok"
) -> dict:
    """Settle one reservation with its actual usage (idempotent, appended to
    the reservation's own day, so a run crossing midnight settles into the day
    it started). A settle whose reservation is unknown still appends and
    counts: usage is never lost."""
    day = reservation.get("day") or _today()
    rid = reservation.get("reservationId", "")
    with _locked(user_key) as written:
        for entry in _read_entries(user_key, day):
            if entry.get("kind") == "settle" and entry.get("reservationId") == rid:
                return entry  # first-write-wins idempotence
        entry = {
            "kind": "settle",
            "reservationId": rid,
            "ts": _now().isoformat(),
            "status": status,
            "usage": _usage_counts(usage) if usage else None,
        }
        _append(user_key, day, entry, written)
        return entry


def record_housekeeping_usage(
    user_key: str, usage: dict | None, *, note: str = "housekeeping",
    llm_config_id: str | None = None,
) -> None:
    """Count an internal provider call (the title call): tokens only, never
    run-counted, no reservation. The token counters may therefore exceed what
    the transcript's execution records sum to."""
    if not usage:
        return
    with _locked(user_key) as written:
        _append(
            user_key,
            _today(),
            {
                "kind": "usage",
                "ts": _now().isoformat(),
                "note": note,
                "usage": _usage_counts(usage),
                "llmConfigId": llm_config_id,
            },
            written,
        )
