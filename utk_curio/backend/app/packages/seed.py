"""Dev-only seeder that copies catalog packages into the guest user's package store.

The runtime ``.curio/users/<u>/packages/`` tree is gitignored, so committing a
package there is not an option. Instead we keep the source-of-truth package
at ``<repo_root>/packages/<dirname>/`` and copy it into the
guest user's package store at backend startup.

Besides ``curio.builtin`` (always seeded), the packages the bundled examples
declare as dependencies (see :func:`example_dep_package_ids`) are seeded too
when example projects are being seeded (``CURIO_SEED_EXAMPLES=1``, i.e.
``--with-examples`` / ``--deploy``). Once they land in the user store, the
launcher's per-user manifest walk re-installs their python deps on every
subsequent start — so seeded examples keep working across plain
``curio start`` runs.

Each seed/uninstall decision is recorded in
``<user>/packages/.seed-state.json`` (see :mod:`.seed_state`). That marker
file is what lets us tell "the user uninstalled this package" apart from
"the package was never seeded yet" — without it, the seeder would happily
resurrect any package the user removed the next time Werkzeug's reloader
fired (which is exactly the regression the marker exists to prevent).

This is only ever invoked from dev startup (gated by
:func:`utk_curio.backend.config._is_dev`); production builds skip it.

Set ``CURIO_RESEED_PACKAGES=1`` to force re-seeding even when the marker
heuristic does not flag a refresh — useful after a ``git checkout``
that preserves mtimes, and as an escape hatch for the dev who *does*
want a tombstoned package back.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from utk_curio.backend.app.packages import seed_state
from utk_curio.backend.app.packages.storage import (
    PACKAGE_DIR_RE,
    user_packageages_dir,
)
from utk_curio.backend.config import CURIO_RESEED_PACKAGES, CURIO_SEED_EXAMPLES

log = logging.getLogger(__name__)


def _catalog_root() -> Path:
    # utk_curio/backend/app/packages/seed.py  ->  <repo_root>/packages/
    return Path(__file__).resolve().parents[4] / "packages"


BUILTIN_PACKAGE_ID = "curio.builtin"


def example_dep_package_ids() -> tuple[str, ...]:
    """Package IDs the seeded example dataflows declare as dependencies.

    Scans ``docs/examples/*.json`` and unions each spec's
    ``dataflow.packages`` lockfile, returning the package IDs (major
    stripped, sorted) — so the launcher (their python deps) and this seeder
    (copy into the user store) provision exactly the packages the examples
    depend on, with no hardcoded allowlist to keep in sync.

    A heavy package (e.g. ``curio.streetvision`` → torch/transformers) stays
    out of every ``--with-examples`` / ``--deploy`` boot simply by not being
    declared in any example's lockfile; users install it from the catalog
    drawer when they want it. Shared source of truth: the launcher's catalog
    dep walk (``utk_curio/main.py::install_manifest_dependencies``) calls
    this too.
    """
    repo_root = Path(__file__).resolve().parents[4]
    examples_dir = repo_root / "docs" / "examples"
    ids: set[str] = set()
    if not examples_dir.is_dir():
        return ()
    for json_path in sorted(examples_dir.glob("*.json")):
        try:
            spec = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
        declared = dataflow.get("packages") if isinstance(dataflow, dict) else None
        if isinstance(declared, list):
            for dir_name in declared:
                if isinstance(dir_name, str) and "@" in dir_name:
                    ids.add(dir_name.split("@", 1)[0])
    return tuple(sorted(ids))


def _latest_package_dir(catalog_root: Path, package_id: str) -> Path | None:
    """Return the highest-major ``<package_id>@<X>/`` directory in *catalog_root*."""
    candidates: list[tuple[int, Path]] = []
    if not catalog_root.is_dir():
        return None
    prefix = f"{package_id}@"
    for entry in catalog_root.iterdir():
        if not entry.is_dir() or not entry.name.startswith(prefix):
            continue
        suffix = entry.name[len(prefix):]
        if not suffix.isdigit():
            continue
        candidates.append((int(suffix), entry))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def _latest_builtin_dir(catalog_root: Path) -> Path | None:
    """Return the highest-major ``curio.builtin@<X>/`` directory in *catalog_root*.

    Built-in is always installed as the latest available major — re-installs
    on every login so users can never end up without the default kinds.
    """
    return _latest_package_dir(catalog_root, BUILTIN_PACKAGE_ID)


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


def seed_dev_packageages(*, user_key: str = "guest") -> list[str]:
    """Copy every fixture package into ``<user_key>``'s package store.

    Returns the list of package directory names that were seeded or
    refreshed (empty if nothing was copied). Safe to call repeatedly —
    the per-user state file in :mod:`.seed_state` makes the decision
    idempotent and respects explicit user uninstalls.
    """
    src_root = _catalog_root()
    if not src_root.is_dir():
        return []

    dest_base = user_packageages_dir(user_key)
    dest_base.mkdir(parents=True, exist_ok=True)

    # Sweep any orphaned staging dirs left behind by an install that
    # was SIGKILL'd / lost power before its TemporaryDirectory could
    # clean up — both the current ``.package-staging/`` location and the
    # legacy ``packages/.staging-*`` location from earlier builds. The
    # installer does this on every install too, but the seeder is the
    # only thing that touches the package store on a cold startup with no
    # in-flight install request.
    try:
        from utk_curio.backend.app.packages.installer import _purge_stale_staging
        _purge_stale_staging(user_key)
    except Exception:  # noqa: BLE001 — cleanup must never crash startup
        log.warning("Stale-staging sweep failed", exc_info=True)

    force = CURIO_RESEED_PACKAGES
    records = seed_state.load(user_key)

    # The built-in package ships with every Curio install. We seed exactly the
    # latest installed major and clean up any older `curio.builtin@<X>` copies
    # the user may still have from a previous version. Tombstones don't apply
    # — user cannot opt out of having the default node kinds.
    builtin_dir = _latest_builtin_dir(src_root)
    keep_builtin_name = builtin_dir.name if builtin_dir is not None else None
    if keep_builtin_name:
        prefix = f"{BUILTIN_PACKAGE_ID}@"
        for old in dest_base.iterdir():
            if not old.is_dir() or not old.name.startswith(prefix):
                continue
            if old.name == keep_builtin_name:
                continue
            try:
                shutil.rmtree(old)
                log.info("Pruned superseded builtin package %s", old.name)
            except OSError as exc:
                log.warning("Failed to prune old builtin %s: %s", old, exc)

    # Only auto-install the built-in package — plus, when example projects
    # are being seeded, the packages those examples declare as dependencies
    # (derived from their dataflow.packages lockfiles). Other catalog
    # packages remain in <repo_root>/packages/ but the user must install them
    # explicitly via the catalog drawer. (No prune-older-majors sweep for
    # example packages: only one major of each exists.)
    keep_names: set[str] = {keep_builtin_name} if keep_builtin_name else set()
    if CURIO_SEED_EXAMPLES:
        for pid in example_dep_package_ids():
            pkg_dir = _latest_package_dir(src_root, pid)
            if pkg_dir is not None:
                keep_names.add(pkg_dir.name)

    seeded: list[str] = []
    for src in sorted(src_root.iterdir()):
        if not src.is_dir():
            continue
        if not PACKAGE_DIR_RE.match(src.name):
            continue
        if src.name not in keep_names:
            continue
        dest = dest_base / src.name
        fixture_mtime = _max_mtime(src)
        record = records.get(src.name)
        is_builtin = src.name == keep_builtin_name
        if force or is_builtin:
            do_seed, reason = True, "forced-builtin" if is_builtin else "forced-by-env"
        else:
            do_seed, reason = seed_state.should_seed(
                record,
                runtime_exists=dest.exists(),
                fixture_mtime=fixture_mtime,
            )
        if not do_seed:
            log.debug("Skipping dev package %s: %s", src.name, reason)
            # Upgrade from a pre-tombstone build: there is an existing
            # runtime copy with no recorded state. Adopt it so future
            # uninstalls have a stable mtime anchor (otherwise a
            # subsequent restart with a tombstoned-but-untracked package
            # would fall back into ``first-run-or-missing`` and reseed).
            if reason == "untracked-existing-copy":
                seed_state.mark_seeded(user_key, src.name, fixture_mtime)
            continue
        if dest.exists():
            try:
                shutil.rmtree(dest)
            except OSError as exc:
                log.warning("Failed to remove stale runtime package %s: %s", dest, exc)
                continue
        try:
            shutil.copytree(src, dest)
        except OSError as exc:
            log.warning("Failed to seed fixture package %s -> %s: %s", src, dest, exc)
            continue
        seed_state.mark_seeded(user_key, src.name, fixture_mtime)
        seeded.append(src.name)
        log.info("Seeded dev package %s into %s (%s)", src.name, dest_base, reason)
    return seeded
