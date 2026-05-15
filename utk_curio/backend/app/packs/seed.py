"""Dev-only seeder that copies fixture packs into the guest user's pack store.

The runtime ``.curio/users/<u>/packs/`` tree is gitignored, so committing a
fixture there is not an option. Instead we keep the source-of-truth fixture
at ``utk_curio/backend/fixtures/packs/<dirname>/`` and copy it into the
guest user's pack store at backend startup.

Each seed/uninstall decision is recorded in
``<user>/packs/.seed-state.json`` (see :mod:`.seed_state`). That marker
file is what lets us tell "the user uninstalled this pack" apart from
"the pack was never seeded yet" — without it, the seeder would happily
resurrect any pack the user removed the next time Werkzeug's reloader
fired (which is exactly the regression the marker exists to prevent).

This is only ever invoked from dev startup (gated by
:func:`utk_curio.backend.config._is_dev`); production builds skip it.

Set ``CURIO_RESEED_PACKS=1`` to force re-seeding even when the marker
heuristic does not flag a refresh — useful after a ``git checkout``
that preserves mtimes, and as an escape hatch for the dev who *does*
want a tombstoned pack back.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from utk_curio.backend.app.packs import seed_state
from utk_curio.backend.app.packs.storage import (
    PACK_DIR_RE,
    user_packs_dir,
)

log = logging.getLogger(__name__)


def _fixtures_root() -> Path:
    # utk_curio/backend/app/packs/seed.py  ->  utk_curio/backend/fixtures/packs/
    return Path(__file__).resolve().parents[2] / "fixtures" / "packs"


def _max_mtime(root: Path) -> float:
    """Return the newest mtime under ``root`` (0.0 if the tree is empty)."""
    newest = 0.0
    for path in root.rglob("*"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > newest:
            newest = mtime
    return newest


def seed_dev_packs(*, user_key: str = "guest") -> list[str]:
    """Copy every fixture pack into ``<user_key>``'s pack store.

    Returns the list of pack directory names that were seeded or
    refreshed (empty if nothing was copied). Safe to call repeatedly —
    the per-user state file in :mod:`.seed_state` makes the decision
    idempotent and respects explicit user uninstalls.
    """
    src_root = _fixtures_root()
    if not src_root.is_dir():
        return []

    dest_base = user_packs_dir(user_key)
    dest_base.mkdir(parents=True, exist_ok=True)

    # Sweep any orphaned staging dirs left behind by an install that
    # was SIGKILL'd / lost power before its TemporaryDirectory could
    # clean up — both the current ``.pack-staging/`` location and the
    # legacy ``packs/.staging-*`` location from earlier builds. The
    # installer does this on every install too, but the seeder is the
    # only thing that touches the pack store on a cold startup with no
    # in-flight install request.
    try:
        from utk_curio.backend.app.packs.installer import _purge_stale_staging
        _purge_stale_staging(user_key)
    except Exception:  # noqa: BLE001 — cleanup must never crash startup
        log.warning("Stale-staging sweep failed", exc_info=True)

    force = os.environ.get("CURIO_RESEED_PACKS", "").strip().lower() in {"1", "true", "yes"}
    records = seed_state.load(user_key)

    seeded: list[str] = []
    for src in sorted(src_root.iterdir()):
        if not src.is_dir():
            continue
        if not PACK_DIR_RE.match(src.name):
            continue
        dest = dest_base / src.name
        fixture_mtime = _max_mtime(src)
        record = records.get(src.name)
        if force:
            do_seed, reason = True, "forced-by-env"
        else:
            do_seed, reason = seed_state.should_seed(
                record,
                runtime_exists=dest.exists(),
                fixture_mtime=fixture_mtime,
            )
        if not do_seed:
            log.debug("Skipping dev pack %s: %s", src.name, reason)
            # Upgrade from a pre-tombstone build: there is an existing
            # runtime copy with no recorded state. Adopt it so future
            # uninstalls have a stable mtime anchor (otherwise a
            # subsequent restart with a tombstoned-but-untracked pack
            # would fall back into ``first-run-or-missing`` and reseed).
            if reason == "untracked-existing-copy":
                seed_state.mark_seeded(user_key, src.name, fixture_mtime)
            continue
        if dest.exists():
            try:
                shutil.rmtree(dest)
            except OSError as exc:
                log.warning("Failed to remove stale runtime pack %s: %s", dest, exc)
                continue
        try:
            shutil.copytree(src, dest)
        except OSError as exc:
            log.warning("Failed to seed fixture pack %s -> %s: %s", src, dest, exc)
            continue
        seed_state.mark_seeded(user_key, src.name, fixture_mtime)
        seeded.append(src.name)
        log.info("Seeded dev pack %s into %s (%s)", src.name, dest_base, reason)
    return seeded
