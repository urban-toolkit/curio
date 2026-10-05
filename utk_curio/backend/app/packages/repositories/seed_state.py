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

It also remembers where each store copy came from (#564), because the
seeder refreshes an installed package from the catalog when the two differ
(#194) and must not do that to a copy the user changed:

* ``catalogCopy`` is the digest of the copy's ``integrity.json`` map at the
  moment the catalog wrote it (a catalog install or a seeder swap). While the
  copy's map still has that digest, nobody has changed it since.
* ``installedAt`` without ``catalogCopy`` is a copy holding the user's own
  content: an upload, a factory install, a promotion, a metadata edit.
* A record with neither predates this rule, or was lost. Such a copy is
  refreshed only when it is provably a catalog copy nobody changed: its
  map is one the catalog shipped (:func:`legacy_catalog_digests`) and its
  files still match that map.

The schema is intentionally tiny: only the five known keys survive a
rewrite, and a corrupt or missing file is treated as "no recorded state"
rather than raising.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from utk_curio.backend.app.packages.repositories.store import user_packages_dir

log = logging.getLogger(__name__)

STATE_FILENAME = ".seed-state.json"
STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PackageSeedRecord:
    """What the seeder remembers about one package for one user."""
    seeded_at: Optional[float] = None
    uninstalled_at: Optional[float] = None
    fixture_mtime: Optional[float] = None
    installed_at: Optional[float] = None
    catalog_copy: Optional[str] = None

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
        copy = raw.get("catalogCopy")
        return cls(
            seeded_at=_num("seededAt"),
            uninstalled_at=_num("uninstalledAt"),
            fixture_mtime=_num("fixtureMtime"),
            installed_at=_num("installedAt"),
            catalog_copy=copy if isinstance(copy, str) and copy else None,
        )

    def to_json(self) -> dict:
        out: dict = {}
        if self.seeded_at is not None:
            out["seededAt"] = self.seeded_at
        if self.uninstalled_at is not None:
            out["uninstalledAt"] = self.uninstalled_at
        if self.fixture_mtime is not None:
            out["fixtureMtime"] = self.fixture_mtime
        if self.installed_at is not None:
            out["installedAt"] = self.installed_at
        if self.catalog_copy is not None:
            out["catalogCopy"] = self.catalog_copy
        return out


def copy_digest(integrity: dict[str, str]) -> str:
    """One digest for a package copy's ``integrity.json`` map."""
    body = json.dumps(integrity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


_LEGACY_DIGESTS_PATH = Path(__file__).with_name("legacy_catalog_digests.json")


@functools.lru_cache(maxsize=1)
def legacy_catalog_digests() -> dict[str, frozenset[str]]:
    """Every :func:`copy_digest` a shipped package's ``integrity.json`` has had.

    Read from ``legacy_catalog_digests.json``, generated once from the git
    history of ``packages/<dir>/integrity.json``. It answers one question for
    a copy with no origin on record: is this byte for byte a catalog copy
    from some earlier release? The file is frozen on purpose. Every copy
    written since the record existed (#564) carries ``catalogCopy`` or
    ``installedAt`` and never asks; a copy whose record is lost later and
    whose digest postdates the file is simply kept, which loses nothing.
    """
    try:
        raw = json.loads(_LEGACY_DIGESTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("Could not read %s", _LEGACY_DIGESTS_PATH, exc_info=True)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): frozenset(d for d in digests if isinstance(d, str))
        for name, digests in raw.items()
        if isinstance(digests, list)
    }


def _state_path(user_key: str) -> Path:
    return user_packages_dir(user_key) / STATE_FILENAME


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


def mark_seeded(
    user_key: str, dir_name: str, fixture_mtime: float, *, catalog_copy: str | None = None,
) -> None:
    """Record that ``dir_name`` was just (re-)seeded for ``user_key``.

    *catalog_copy* is the digest of the copy the swap left (see
    :func:`copy_digest`).
    """
    records = load(user_key)
    records[dir_name] = PackageSeedRecord(
        seeded_at=time.time(),
        uninstalled_at=None,
        fixture_mtime=float(fixture_mtime),
        catalog_copy=catalog_copy,
    )
    save(user_key, records)


def mark_installed(user_key: str, dir_name: str, *, catalog_copy: str | None) -> None:
    """Record an install into the store, replacing any earlier record.

    *catalog_copy* is the digest of the copy the catalog just wrote, or
    ``None`` for a copy holding the user's own content. Replacing the record
    also drops an uninstall tombstone: the user just asked for the package.
    """
    records = load(user_key)
    records[dir_name] = PackageSeedRecord(installed_at=time.time(), catalog_copy=catalog_copy)
    save(user_key, records)


def mark_catalog_copy(user_key: str, dir_name: str, catalog_copy: str) -> None:
    """Record that the copy in the store is the catalog's, keeping the rest of
    the record (the seeder's adoption of a copy that predates the digest)."""
    records = load(user_key)
    prev = records.get(dir_name) or PackageSeedRecord()
    records[dir_name] = dataclasses.replace(prev, catalog_copy=catalog_copy)
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


def put(user_key: str, dir_name: str, raw: object) -> None:
    """Write back a record :meth:`PackageSeedRecord.to_json` produced earlier,
    or drop the entry when it holds nothing (a restore after a rollback)."""
    records = load(user_key)
    record = PackageSeedRecord.from_json(raw)
    if record.to_json():
        records[dir_name] = record
    else:
        records.pop(dir_name, None)
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
