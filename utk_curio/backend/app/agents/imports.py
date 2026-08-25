"""Account-level imported-agents registry — the "My Imports" list.

Stored at ``<CURIO_LAUNCH_CWD>/.curio/users/<user_key>/imported-agents.json``
with the shape ``{"version": 1, "agents": ["<agentId>@<version>", ...]}``. This
is the direct analogue of the node-package ``default-packages.json`` list and
uses the same tolerant read convention: a missing file is an empty set, and a
corrupt/mismatched file is also treated as empty (the read path never raises, so
a bad JSON file the user can't easily edit can't block startup).

Import is account-private: adding a coordinate here records that the account has
imported that definition. It does not install into any project (that is
``project_agents.py``) and does not publish.

User-facing overview: ``docs/AGENTS.md``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterable

from utk_curio.backend.app.packages.storage import _user_key_segment, _users_base

from utk_curio.backend.app.agents.storage import AGENT_DIR_RE

log = logging.getLogger(__name__)

_FILENAME = "imported-agents.json"
_SCHEMA_VERSION = 1


def _imports_path(user_key: str) -> Path:
    return _users_base() / _user_key_segment(user_key) / _FILENAME


def load_imported_agents(user_key: str) -> set[str]:
    """Return the account's imported-agent coordinate set. Missing/corrupt → empty."""
    path = _imports_path(user_key)
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Corrupt %s for %s — treating as empty", _FILENAME, user_key)
        return set()
    agents = raw.get("agents") if isinstance(raw, dict) else None
    if not isinstance(agents, list):
        return set()
    return {a for a in agents if isinstance(a, str) and AGENT_DIR_RE.match(a)}


def save_imported_agents(user_key: str, coords: Iterable[str]) -> Path:
    """Persist *coords* as the account's imported-agent list (sorted, validated)."""
    cleaned = sorted({c for c in coords if isinstance(c, str) and AGENT_DIR_RE.match(c)})
    path = _imports_path(user_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {"version": _SCHEMA_VERSION, "agents": cleaned}
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def add_imported_agent(user_key: str, coord: str) -> set[str]:
    """Idempotently record *coord* as imported; return the new set."""
    if not (isinstance(coord, str) and AGENT_DIR_RE.match(coord)):
        raise ValueError(f"invalid agent coordinate {coord!r}; expected '<agentId>@<version>'")
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
