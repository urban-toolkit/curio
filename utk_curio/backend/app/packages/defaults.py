"""Per-user default-packages list: which dirNames auto-seed into new projects.

Stored at ``<CURIO_LAUNCH_CWD>/.curio/users/<user_key>/default-packages.json``
with the shape ``{"version": 1, "packages": ["<pkg>@<major>", ...]}``.

Managed implicitly: ``/catalog`` page install adds a dirName,
``prune_unreferenced_packages`` removes it when no project still
references the package. There is no user-facing "remove from defaults"
action — that's a deliberate UX choice in the plan.

A missing file is equivalent to an empty list. A corrupt or
schema-mismatched file is also treated as empty (we never raise from
the read path), matching the seed-state convention in
``packages/seed_state.py`` — startup must not be blockable by a bad
JSON file the user can't easily edit.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterable

from utk_curio.backend.app.packages.storage import (
    PACKAGE_DIR_RE,
    _user_key_segment,
    _users_base,
)

log = logging.getLogger(__name__)


_FILENAME = "default-packages.json"
_SCHEMA_VERSION = 1


def _defaults_path(user_key: str) -> Path:
    return _users_base() / _user_key_segment(user_key) / _FILENAME


def load_defaults(user_key: str) -> set[str]:
    """Return the user's default-packages set. Missing/corrupt → empty."""
    path = _defaults_path(user_key)
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Corrupt %s for %s — treating as empty", _FILENAME, user_key)
        return set()
    packages = raw.get("packages") if isinstance(raw, dict) else None
    if not isinstance(packages, list):
        return set()
    return {
        p for p in packages
        if isinstance(p, str) and PACKAGE_DIR_RE.match(p)
    }


def save_defaults(user_key: str, dirs: Iterable[str]) -> Path:
    """Persist *dirs* as the user's default-packages list (sorted)."""
    cleaned = sorted({
        d for d in dirs
        if isinstance(d, str) and PACKAGE_DIR_RE.match(d)
    })
    path = _defaults_path(user_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {"version": _SCHEMA_VERSION, "packages": cleaned}
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def add_to_defaults(user_key: str, dir_name: str) -> set[str]:
    """Idempotently add *dir_name* to defaults; return the new set."""
    current = load_defaults(user_key)
    if dir_name in current:
        return current
    current.add(dir_name)
    save_defaults(user_key, current)
    return current


def remove_from_defaults(user_key: str, dir_name: str) -> set[str]:
    """Idempotently remove *dir_name* from defaults; return the new set."""
    current = load_defaults(user_key)
    if dir_name not in current:
        return current
    current.discard(dir_name)
    save_defaults(user_key, current)
    return current
