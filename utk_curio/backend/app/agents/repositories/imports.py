"""Account-level imported-agents registry — the "My Imports" list.

Stored at ``<CURIO_LAUNCH_CWD>/.curio/users/<user_key>/imported-agents.json``
with the shape ``{"version": 1, "agents": ["<agentId>@<major>", ...],
"seeded": ["<agentId>@<major>", ...]}``. This is the direct analogue of the
node-package ``default-packages.json`` list and uses the same tolerant read
convention: a missing file is an empty set, and a corrupt/mismatched file is
also treated as empty (the read path never raises, so a bad JSON file the user
can't easily edit can't block startup).

``seeded`` names each agent Curio has added to the account by default
(``lifecycle.seed_default_agents``), whether or not the account still has it,
so one the account removed from all its projects is not added again. A file
without it has had none added.

Import is account-private: adding a coordinate here records that the account has
imported that definition. It does not install into any project (that is
``project_agents.py``) and does not publish.

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from utk_curio.backend.app.common.file_locks import exclusive_lock
from utk_curio.backend.app.common.user_storage import (
    user_key_segment as _user_key_segment,
    users_base as _users_base,
)

from utk_curio.backend.app.agents.repositories.storage import AGENT_DIR_RE

log = logging.getLogger(__name__)

_FILENAME = "imported-agents.json"
_SCHEMA_VERSION = 1
#: ``common.file_locks`` namespace of the lock one seeding of an account's
#: default agents holds (:func:`seeding`).
_SEED_LOCK_NAMESPACE = "default-agents-seed"


def _imports_path(user_key: str) -> Path:
    return _users_base() / _user_key_segment(user_key) / _FILENAME


def _read(user_key: str) -> dict:
    """The file's object; empty when it is missing or corrupt."""
    path = _imports_path(user_key)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Corrupt %s for %s — treating as empty", _FILENAME, user_key)
        return {}
    return raw if isinstance(raw, dict) else {}


def _coords(raw: dict, key: str) -> set[str]:
    listed = raw.get(key)
    if not isinstance(listed, list):
        return set()
    return {a for a in listed if isinstance(a, str) and AGENT_DIR_RE.match(a)}


def load_imported_agents(user_key: str) -> set[str]:
    """Return the account's imported-agent coordinate set. Missing/corrupt → empty."""
    return _coords(_read(user_key), "agents")


def load_seeded_agents(user_key: str) -> set[str]:
    """The agents Curio has added to the account by default, kept or not.
    Missing/corrupt → empty."""
    return _coords(_read(user_key), "seeded")


def save_imported_agents(user_key: str, coords: Iterable[str], *, seeded: Iterable[str] | None = None) -> Path:
    """Persist *coords* as the account's imported-agent list (sorted, validated).

    The file's ``seeded`` record is kept, or replaced by *seeded* when given."""
    cleaned = sorted({c for c in coords if isinstance(c, str) and AGENT_DIR_RE.match(c)})
    kept = sorted(
        load_seeded_agents(user_key) if seeded is None
        else {c for c in seeded if isinstance(c, str) and AGENT_DIR_RE.match(c)}
    )
    path = _imports_path(user_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload: dict = {"version": _SCHEMA_VERSION, "agents": cleaned}
    if kept:
        payload["seeded"] = kept
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def record_seeded(user_key: str, coords: Iterable[str]) -> set[str]:
    """Add *coords* to the record of the agents Curio has added to the account
    by default; return the new record. The imports themselves are untouched."""
    added = {c for c in coords if isinstance(c, str) and AGENT_DIR_RE.match(c)}
    current = load_seeded_agents(user_key)
    if added <= current:
        return current
    save_imported_agents(user_key, load_imported_agents(user_key), seeded=current | added)
    return current | added


@contextmanager
def seeding(user_key: str) -> Iterator[None]:
    """Hold the account's lock for adding its default agents, so two requests
    never add them at once; it sits beside the imports file."""
    path = _imports_path(user_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(path.parent / f".{_FILENAME}.lock", namespace=_SEED_LOCK_NAMESPACE, key=str(user_key)):
        yield


def add_imported_agent(user_key: str, coord: str) -> set[str]:
    """Idempotently record *coord* as imported; return the new set."""
    if not (isinstance(coord, str) and AGENT_DIR_RE.match(coord)):
        raise ValueError(f"invalid agent coordinate {coord!r}; expected '<agentId>@<major>'")
    current = load_imported_agents(user_key)
    if coord in current:
        return current
    current.add(coord)
    save_imported_agents(user_key, current)
    return current


def remove_imported_agent(user_key: str, coord: str) -> set[str]:
    """Idempotently drop *coord* from the imported list; return the new set."""
    current = load_imported_agents(user_key)
    if coord not in current:
        return current
    current.discard(coord)
    save_imported_agents(user_key, current)
    return current
