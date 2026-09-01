"""Per-user default-datasets list: which dataset ids auto-seed into new projects.

Stored at ``<CURIO_LAUNCH_CWD>/.curio/users/<user_key>/default-datasets.json``
with the shape ``{"version": 1, "datasets": ["<dataset id>", ...]}``.

This is the dataset twin of :mod:`utk_curio.backend.app.packages.defaults`, and
deliberately mirrors it line for line: same directory, same schema envelope,
same never-raise read path. The Data Catalog page had no account-level concept
at all, so its cards could only ever offer "add to THIS project" - which is a
thing the standalone page cannot do, because it has no project. Nodes and
agents both had an all-projects affordance and data did not.

Unlike packages, this list IS user-managed in both directions: the catalog page
offers "Add to all projects" and "Remove from all projects", because a dataset
is a file the user chose rather than a dependency something else resolved. The
package list is managed implicitly (install adds, prune removes) precisely
because a package can be an invisible transitive requirement; a dataset never
is.

A missing file is equivalent to an empty list. A corrupt or schema-mismatched
file is also treated as empty (we never raise from the read path), matching the
seed-state convention in ``packages/seed_state.py`` - startup must not be
blockable by a bad JSON file the user cannot easily edit.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Iterable

from utk_curio.backend.app.packages.storage import (
    _user_key_segment,
    _users_base,
)

log = logging.getLogger(__name__)


_FILENAME = "default-datasets.json"
_SCHEMA_VERSION = 1

# Dataset ids are ``<origin>.<slug>[@<major>]`` (``data.chicago-green-roofs``,
# ``imported.abc123@1``, ``computed.<node>@1``) plus the OSM group ids. Kept
# permissive on purpose - this is a guard against path traversal and junk in a
# hand-edited file, not a schema. The service layer resolves the id for real,
# and a stale id is dropped at seed time rather than rejected here.
DATASET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:-]{0,200}$")


def _defaults_path(user_key: str) -> Path:
    return _users_base() / _user_key_segment(user_key) / _FILENAME


def load_dataset_defaults(user_key: str) -> set[str]:
    """Return the user's default-datasets set. Missing/corrupt → empty."""
    path = _defaults_path(user_key)
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Corrupt %s for %s - treating as empty", _FILENAME, user_key)
        return set()
    datasets = raw.get("datasets") if isinstance(raw, dict) else None
    if not isinstance(datasets, list):
        return set()
    return {
        d for d in datasets
        if isinstance(d, str) and DATASET_ID_RE.match(d)
    }


def save_dataset_defaults(user_key: str, dataset_ids: Iterable[str]) -> Path:
    """Persist *dataset_ids* as the user's default-datasets list (sorted)."""
    cleaned = sorted({
        d for d in dataset_ids
        if isinstance(d, str) and DATASET_ID_RE.match(d)
    })
    path = _defaults_path(user_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {"version": _SCHEMA_VERSION, "datasets": cleaned}
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Atomic swap, so a crash mid-write cannot leave a truncated list that the
    # read path would silently treat as "no defaults".
    os.replace(tmp, path)
    return path


def add_to_dataset_defaults(user_key: str, dataset_id: str) -> set[str]:
    """Idempotently add *dataset_id* to defaults; return the new set."""
    current = load_dataset_defaults(user_key)
    if dataset_id in current:
        return current
    current.add(dataset_id)
    save_dataset_defaults(user_key, current)
    return current


def remove_from_dataset_defaults(user_key: str, dataset_id: str) -> set[str]:
    """Idempotently remove *dataset_id* from defaults; return the new set."""
    current = load_dataset_defaults(user_key)
    if dataset_id not in current:
        return current
    current.discard(dataset_id)
    save_dataset_defaults(user_key, current)
    return current
