"""Per-user marker file that records the dev seeder's intent.

The dev seeder copies committed catalog packages from
``<repo_root>/packages/`` into ``<user>/packages/`` on every
backend startup. Without a marker, a user-driven uninstall is
indistinguishable from "never seeded yet" the next time the backend
hot-reloads — Werkzeug's reloader fires on any imported-module edit,
and the seeder would happily re-install the package the user just
removed (the regression behind the "I can't uninstall packages" UX bug).

This module owns a single ``<user>/packages/.seed-state.json`` file that
remembers, per package dir name, whether the seeder has put a copy in
place and whether the user has explicitly uninstalled it. Both records
carry the ``fixtureMtime`` they were observed at, so:

* a package the user uninstalled stays uninstalled across hot-reloads,
* but if the dev pushes a *newer* fixture (e.g. a fresh manifest commit),
  the bumped ``fixtureMtime`` overrides the tombstone and the seeder
  re-seeds — the dev still wants their fixture refresh to surface.

The schema is intentionally tiny and forward-compatible: unknown keys
on a per-package record are preserved on rewrite, and a corrupt or
missing file is treated as "no recorded state" rather than raising.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from utk_curio.backend.app.packages.storage import user_packageages_dir

log = logging.getLogger(__name__)

STATE_FILENAME = ".seed-state.json"
STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PackageSeedRecord:
    """What the seeder remembers about one package for one user."""
    seeded_at: Optional[float] = None
    uninstalled_at: Optional[float] = None
    fixture_mtime: Optional[float] = None

    @property
    def is_uninstalled(self) -> bool:
        return self.uninstalled_at is not None and self.seeded_at is None

    @classmethod
    def from_json(cls, raw: object) -> "PackageSeedRecord":
        if not isinstance(raw, dict):
            return cls()
        def _num(key: str) -> Optional[float]:
            v = raw.get(key)
            return float(v) if isinstance(v, (int, float)) else None
        return cls(
            seeded_at=_num("seededAt"),
            uninstalled_at=_num("uninstalledAt"),
            fixture_mtime=_num("fixtureMtime"),
        )

    def to_json(self) -> dict:
        out: dict = {}
        if self.seeded_at is not None:
            out["seededAt"] = self.seeded_at
        if self.uninstalled_at is not None:
            out["uninstalledAt"] = self.uninstalled_at
        if self.fixture_mtime is not None:
            out["fixtureMtime"] = self.fixture_mtime
        return out


def _state_path(user_key: str) -> Path:
    return user_packageages_dir(user_key) / STATE_FILENAME


def load(user_key: str) -> dict[str, PackageSeedRecord]:
    """Return ``{ dir_name: PackageSeedRecord }`` for ``user_key``.

    Missing or corrupt state file → empty dict (treated as "no recorded
    seed history yet"). Never raises so a malformed state file cannot
    block backend startup.
    """
    path = _state_path(user_key)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read package seed-state %s: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    packages = raw.get("packages")
    if not isinstance(packages, dict):
        return {}
    out: dict[str, PackageSeedRecord] = {}
    for name, record in packages.items():
        if isinstance(name, str):
            out[name] = PackageSeedRecord.from_json(record)
    return out


def _atomic_write(path: Path, body: str) -> None:
    """``write_text`` is not safe under a hot-reload-triggered concurrent
    startup; do the rename dance so a half-written file never reaches disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".seed-state.", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save(user_key: str, records: dict[str, PackageSeedRecord]) -> None:
    """Persist the full set of records for ``user_key``.

    Records whose payload would serialise to ``{}`` (no fields set) are
    dropped so the on-disk file stays minimal.
    """
    path = _state_path(user_key)
    payload = {
        "version": STATE_SCHEMA_VERSION,
        "packages": {
            name: rec.to_json() for name, rec in records.items() if rec.to_json()
        },
    }
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True))


def mark_seeded(user_key: str, dir_name: str, fixture_mtime: float) -> None:
    """Record that ``dir_name`` was just (re-)seeded for ``user_key``."""
    records = load(user_key)
    records[dir_name] = PackageSeedRecord(
        seeded_at=time.time(),
        uninstalled_at=None,
        fixture_mtime=float(fixture_mtime),
    )
    save(user_key, records)


def mark_uninstalled(user_key: str, dir_name: str) -> None:
    """Record an explicit user uninstall so the seeder won't resurrect it.

    Keeps whatever ``fixture_mtime`` was last seeded so a newer fixture
    can still override the tombstone on a future restart.
    """
    records = load(user_key)
    prev = records.get(dir_name) or PackageSeedRecord()
    records[dir_name] = PackageSeedRecord(
        seeded_at=None,
        uninstalled_at=time.time(),
        fixture_mtime=prev.fixture_mtime,
    )
    save(user_key, records)


def clear(user_key: str, dir_name: str) -> None:
    """Forget any record for ``dir_name`` (used on explicit reinstall)."""
    records = load(user_key)
    if dir_name in records:
        records.pop(dir_name)
        save(user_key, records)


def should_seed(
    record: PackageSeedRecord | None,
    *,
    runtime_exists: bool,
    fixture_mtime: float,
) -> tuple[bool, str]:
    """Decide whether the seeder should (re-)copy a fixture.

    Returns ``(do_seed, reason)`` where ``reason`` is a short string the
    seeder logs at INFO so the dev can see why a fixture was or wasn't
    refreshed. The decision matrix mirrors the docstring on this module:

    * runtime missing + tombstone with matching mtime → ``skip``
      (respect the user's uninstall).
    * runtime missing + no record (or fixture is newer than tombstone) →
      ``seed`` (first-run or dev-fixture refresh).
    * runtime exists + fixture has advanced past the seeded mtime →
      ``refresh``.
    * runtime exists + fixture mtime unchanged → ``skip`` (idempotent).
    """
    rec = record or PackageSeedRecord()
    if not runtime_exists:
        if rec.is_uninstalled:
            # A tombstone without ``fixture_mtime`` came from an upgrade
            # path where the user uninstalled an untracked pre-tombstone
            # runtime copy. We have nothing to compare against, so the
            # safer default — and the one that matches user intent — is
            # to respect the uninstall. The ``CURIO_RESEED_PACKAGES`` env
            # escape hatch still lets the dev override this.
            if rec.fixture_mtime is None:
                return False, "uninstalled-by-user"
            if fixture_mtime <= rec.fixture_mtime:
                return False, "uninstalled-by-user"
            return True, "fixture-advanced-past-tombstone"
        return True, "first-run-or-missing"
    # Runtime copy is present.
    if rec.seeded_at is None or rec.fixture_mtime is None:
        # We have a runtime copy without a record (e.g. older install
        # before this state file existed). Leave it alone; only re-seed
        # if the fixture is strictly newer than the runtime copy.
        return False, "untracked-existing-copy"
    if fixture_mtime > rec.fixture_mtime:
        return True, "fixture-advanced"
    return False, "idempotent"
