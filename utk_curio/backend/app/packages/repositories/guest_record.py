"""What ``--guest-packages`` gave the shared guest's account.

One file, ``<guest>/packages/.guest-packages.json``, beside the seed state
(``seed_state.py``) and written as it is: whole, through a rename, so a
half-written file never reaches disk. For each package the flag gave, it
says whether a start's add made the store's copy of it and whether it wrote
its defaults entry, so a later start takes off only that
(``application/guest_packages.py``). A missing or unreadable file reads as
nothing given.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories.store import user_packages_dir

log = logging.getLogger(__name__)

RECORD_FILENAME = ".guest-packages.json"
RECORD_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GivenPackage:
    """What the flag gave of one package: the store's copy, which a start's
    add made (*store*), and the defaults entry, which it wrote (*defaults*)."""

    store: bool = False
    defaults: bool = False


def _record_path(user_key: str) -> Path:
    return user_packages_dir(user_key) / RECORD_FILENAME


def load(user_key: str) -> dict[str, GivenPackage]:
    """``{dirName: GivenPackage}`` for *user_key*; empty when nothing is recorded."""
    path = _record_path(user_key)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Could not read the guest packages record %s: %s", path, exc)
        return {}
    packages = raw.get("packages") if isinstance(raw, dict) else None
    if not isinstance(packages, dict):
        return {}
    return {
        dir_name: GivenPackage(store=entry.get("store") is True, defaults=entry.get("defaults") is True)
        for dir_name, entry in packages.items()
        if isinstance(dir_name, str) and PACKAGE_DIR_RE.match(dir_name) and isinstance(entry, dict)
    }


def save(user_key: str, given: dict[str, GivenPackage]) -> None:
    """Record *given* as what the flag gave *user_key*; with nothing given,
    the record goes."""
    path = _record_path(user_key)
    kept = {dir_name: entry for dir_name, entry in given.items() if entry.store or entry.defaults}
    if not kept:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    body = json.dumps({
        "version": RECORD_SCHEMA_VERSION,
        "packages": {
            dir_name: {"store": entry.store, "defaults": entry.defaults}
            for dir_name, entry in sorted(kept.items())
        },
    }, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, partial = tempfile.mkstemp(prefix=".guest-packages.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.replace(partial, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(partial)
        raise
