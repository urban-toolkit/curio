"""Account-scope agent settings record (memo ``dev/24``).

FS-backed (``DEC-040``): ``.curio/users/<key>/agents/settings.json`` holding
``{"revision": int, "settings": {...}}`` — the *Account policy* scope of memo
``dev/11``. Missing/corrupt reads as an empty first-revision record (the
sibling stores' posture). Writes are optimistic-concurrency guarded: a PATCH
carries the revision it read, and a stale revision raises
:class:`~.policy.StaleRevisionError` (→ 409) so concurrent editors never
silently lose updates.
"""

from __future__ import annotations

import json

from utk_curio.backend.app.agents import storage
from utk_curio.backend.app.agents.policy import StaleRevisionError

_EMPTY = {"revision": 1, "settings": {}}


def _path(user_key: str):
    return storage.user_agents_dir(user_key) / "settings.json"


def read_record(user_key: str) -> dict:
    try:
        data = json.loads(_path(user_key).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_EMPTY)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("revision"), int)
        or not isinstance(data.get("settings"), dict)
    ):
        return dict(_EMPTY)
    return data


def write_settings(user_key: str, settings: dict, expected_revision: int) -> dict:
    """Replace the settings at *expected_revision*; returns the new record."""
    current = read_record(user_key)
    if current["revision"] != expected_revision:
        raise StaleRevisionError(
            f"account settings changed (revision {current['revision']}, sent {expected_revision})"
        )
    record = {"revision": expected_revision + 1, "settings": settings}
    path = _path(user_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
