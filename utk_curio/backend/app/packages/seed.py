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

Two properties this module must keep (memo dev/93 D1, which is where they
were lost): a pass is **serialized** per user and each package lands
**atomically**. The seeder is not only a startup path — four request
handlers call it, and the frontend fires several of them around canvas
mount — so passes overlap routinely. Before dev/93 the built-in package was
re-copied on every one of those calls by deleting the live directory and
rebuilding it in place, which left readers seeing a store whose templates
had silently vanished, and left one observed store holding a single file.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from utk_curio.backend.app.packages.locks import package_seed_lock
from utk_curio.backend.app.packages import seed_state
from utk_curio.backend.app.packages.storage import (
    PACKAGE_DIR_RE,
    user_packageages_dir,
)
from utk_curio.backend.config import CURIO_RESEED_PACKAGES, CURIO_SEED_EXAMPLES

log = logging.getLogger(__name__)

# One seeding pass per user at a time (memo dev/93 D1). Four request handlers
# call the seeder (``GET /api/packages``, ``/catalog``, ``/defaults``, and the
# defaults POST), and the frontend fires several of them around canvas mount —
# so concurrent passes are the normal case, not a corner one. The contract
# itself lives in ``packages.locks`` (memo dev/99): readers hold the SAME lock,
# so neither side can drift from the other's filename or namespace.

# Staging lives INSIDE the package store so the swap rename is guaranteed
# same-filesystem. The prefix deliberately matches neither ``PACKAGE_DIR_RE``
# (so ``list_user_packageages`` ignores it) nor the installer's ``.staging-*``
# / ``.stage-*`` sweep patterns (so a concurrent install cannot delete a
# seeding pass's half-built tree).
_SEED_STAGING_PREFIX = ".seed-staging-"


def _catalog_root() -> Path:
    # utk_curio/backend/app/packages/seed.py  ->  <repo_root>/packages/
    return Path(__file__).resolve().parents[4] / "packages"


BUILTIN_PACKAGE_ID = "curio.builtin"

#: Packages we will not provision without being asked.
#:
#: A lockfile says what a dataflow NEEDS. This says what we are willing to
#: install as a side effect of booting with ``--with-examples`` or of opening a
#: dataflow that declares it. The two used to be the same list, which forced a
#: choice between a torch download on every boot and an example whose lockfile
#: lied about its own dependencies — and #233 is what the second one cost:
#: ``curio.streetvision`` went undeclared, so nothing could resolve the
#: example's node types and its three nodes sat on "Loading node…" forever with
#: nothing to say why.
#:
#: Membership is about install COST, not trust: ``curio.streetvision`` pulls
#: torch + transformers + ultralytics, roughly 3 GB on a cold environment. That
#: is a decision a user should make deliberately, in the catalog, where the
#: size is stated — not something a project-open request does to them.
INSTALL_ON_DEMAND_PACKAGE_IDS = frozenset({"curio.streetvision"})


def example_dep_package_ids() -> tuple[str, ...]:
    """Package IDs the seeded example dataflows declare as dependencies.

    Scans ``docs/examples/*.json`` and unions each spec's
    ``dataflow.packages`` lockfile, returning the package IDs (major
    stripped, sorted) — so the launcher (their python deps) and this seeder
    (copy into the user store) provision exactly the packages the examples
    depend on, with no hardcoded allowlist to keep in sync.

    Minus :data:`INSTALL_ON_DEMAND_PACKAGE_IDS`. An example may declare a heavy
    package — it has to, or nothing downstream can tell what its nodes need —
    without that declaration turning into a multi-gigabyte pip run on every
    ``--with-examples`` / ``--deploy`` boot. Shared source of truth: the
    launcher's catalog dep walk
    (``utk_curio/main.py::install_manifest_dependencies``) calls this too.
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
    return tuple(sorted(ids - INSTALL_ON_DEMAND_PACKAGE_IDS))


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


def _package_is_healthy(dest: Path) -> bool:
    """True when the store copy at *dest* is complete enough to serve nodes.

    The gate is the manifest, because that is what the rest of the system
    reads: ``available_templates`` skips any package whose manifest will not
    load, and it skips it *silently*, so an incomplete copy vanishes from
    every roster with no diagnostic — an agent is then told the node type it
    was just offered "is not an available template for this project" (memo
    dev/93 D1/D2). When ``integrity.json`` is present we additionally require
    every file it names, which catches a copy that kept its manifest but lost
    other shipped files.

    Deviation from the memo (§3.1c): a *missing* ``integrity.json`` is NOT
    treated as unhealthy. Marking it so would re-seed on every request for
    any package that ships without one — reinstating the per-request
    destruction this whole change exists to remove.
    """
    if not dest.is_dir():
        return False
    from utk_curio.backend.app.packages.manifest import (
        ManifestError,
        load_packageage_manifest,
    )

    try:
        load_packageage_manifest(dest)
    except (ManifestError, OSError):
        return False
    integrity = dest / "integrity.json"
    if not integrity.is_file():
        return True
    try:
        raw = json.loads(integrity.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    listed = raw.get("sha256") if isinstance(raw, dict) else None
    if not isinstance(listed, dict):
        return False
    for rel in listed:
        # Only membership is checked here, not content: hashing every file on
        # a request path is what ``CURIO_VERIFY_PACKAGES`` would be for.
        if not isinstance(rel, str) or not rel or ".." in Path(rel).parts:
            return False
        if not (dest / rel).is_file():
            return False
    return True


def _sweep_seed_staging(dest_base: Path) -> None:
    """Remove staging trees left by a swap that was killed mid-flight.

    Safe to do unconditionally because the caller holds the per-user seed
    lock, so no live pass owns one of these directories.
    """
    if not dest_base.is_dir():
        return
    for entry in dest_base.iterdir():
        if entry.is_dir() and entry.name.startswith(_SEED_STAGING_PREFIX):
            shutil.rmtree(entry, ignore_errors=True)


def _swap_in_package(src: Path, dest: Path, dest_base: Path) -> bool:
    """Put a fresh copy of *src* at *dest*, atomically. Returns success.

    The previous ``rmtree(dest)`` then ``copytree(src, dest)`` mutated the
    LIVE directory: for the whole copy the package was missing or truncated,
    and every reader in that window (``available_templates`` walks these
    manifests on four request paths) saw a store that had silently lost its
    templates. Worse, a copy that raced a peer raised, was swallowed as a
    warning, and left the partial tree in place — which is exactly the state
    observed on 2026-08-21: a built-in package holding only ``integrity.json``.

    Instead: build the new tree in a staging sibling, move the old tree aside,
    then rename the new one in. Both renames are same-filesystem (staging is
    inside *dest_base*), so **a reader never sees a partially-built package**.

    What remains is a gap of two renames during which the directory is
    momentarily ABSENT: POSIX ``rename`` cannot replace a non-empty directory,
    so one atomic swap is not available. That state is microseconds long,
    happens only on an actual refresh (a healthy, current package is not
    re-copied at all now), and self-corrects — unlike the truncated tree the
    old path could leave behind permanently. Readers that must not observe
    even that gap would have to take the seed lock, the way dev/92's
    ``target_locks`` made invocation reads wait out a promote.
    """
    staging = Path(tempfile.mkdtemp(prefix=_SEED_STAGING_PREFIX, dir=str(dest_base)))
    new_tree = staging / src.name
    displaced = staging / f"{src.name}.displaced"
    try:
        shutil.copytree(src, new_tree)
        moved_aside = False
        if dest.exists():
            os.replace(dest, displaced)
            moved_aside = True
        try:
            os.replace(new_tree, dest)
        except OSError:
            # Put the old tree back rather than leaving the user with no
            # package at all — a failed refresh must not become a deletion.
            if moved_aside:
                os.replace(displaced, dest)
            raise
        return True
    except (OSError, shutil.Error) as exc:
        # ``shutil.Error`` (a partial copytree) is not an OSError, and it must
        # not escape into a request handler or backend startup.
        log.warning("Failed to seed fixture package %s -> %s: %s", src, dest, exc)
        return False
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def seed_dev_packageages(*, user_key: str = "guest") -> list[str]:
    """Copy every fixture package into ``<user_key>``'s package store.

    Returns the list of package directory names that were seeded or
    refreshed (empty if nothing was copied). Safe to call repeatedly —
    the per-user state file in :mod:`.seed_state` makes the decision
    idempotent and respects explicit user uninstalls.

    Concurrency-safe: the pass holds an exclusive per-user store lock
    (:func:`packages.locks.package_seed_lock`, thread- and process-safe)
    and each package is swapped into place atomically, so the request
    handlers that call this can overlap freely. That lock supersedes an
    in-process ``threading.Lock`` that guarded the same race.
    """
    return _seed_dev_packageages_locked(user_key=user_key)


def _seed_dev_packageages_locked(*, user_key: str) -> list[str]:
    """Body of :func:`seed_dev_packageages`. Plans the fixture reads unlocked,
    then takes the per-user store lock for the store work itself."""
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

    # memo dev/99 R1.3: everything that reads the FIXTURE catalog — not the
    # user's store — is resolved before the lock is taken. Readers now wait on
    # this lock, so its hold is exactly the store work: health checks, swaps,
    # state markers. The fixture rglob and the docs/examples scan are not
    # store work and would only lengthen every reader's wait.
    plan = _plan_seed(src_root)
    with package_seed_lock(user_key):
        return _seed_locked(user_key, dest_base, plan)


class _SeedPlan:
    """What the fixture catalog says should be seeded — computed UNLOCKED.

    ``candidates`` is ``(fixture_dir, fixture_mtime)`` in catalog order for
    every package this pass may seed; ``keep_builtin_name`` is the one
    ``curio.builtin@<major>`` that survives the prune of older majors.
    """

    __slots__ = ("keep_builtin_name", "candidates")

    def __init__(self, keep_builtin_name: str | None, candidates: list[tuple[Path, float]]):
        self.keep_builtin_name = keep_builtin_name
        self.candidates = candidates


def _plan_seed(src_root: Path) -> _SeedPlan:
    # The built-in package ships with every Curio install. We seed exactly the
    # latest installed major and clean up any older `curio.builtin@<X>` copies
    # the user may still have from a previous version. Tombstones don't apply
    # — user cannot opt out of having the default node kinds.
    builtin_dir = _latest_builtin_dir(src_root)
    keep_builtin_name = builtin_dir.name if builtin_dir is not None else None

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

    candidates: list[tuple[Path, float]] = []
    for src in sorted(src_root.iterdir()):
        if not src.is_dir():
            continue
        if not PACKAGE_DIR_RE.match(src.name):
            continue
        if src.name not in keep_names:
            continue
        candidates.append((src, _max_mtime(src)))
    return _SeedPlan(keep_builtin_name, candidates)


def _seed_locked(user_key: str, dest_base: Path, plan: _SeedPlan) -> list[str]:
    """One seeding pass over the user's STORE, holding the per-user seed lock.

    Everything about the fixture catalog arrived in *plan*; nothing in here
    reads outside ``dest_base`` and the seed-state marker.
    """
    _sweep_seed_staging(dest_base)

    force = CURIO_RESEED_PACKAGES
    records = seed_state.load(user_key)

    keep_builtin_name = plan.keep_builtin_name
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

    seeded: list[str] = []
    for src, fixture_mtime in plan.candidates:
        dest = dest_base / src.name
        record = records.get(src.name)
        is_builtin = src.name == keep_builtin_name
        if force:
            do_seed, reason = True, "forced-by-env"
        elif is_builtin and not dest.exists():
            # The user cannot opt out of the default node kinds, so a
            # tombstone must never suppress the built-in. (Nothing can
            # tombstone it through the UI either — ``uninstall`` refuses it —
            # but an older build could have left one behind.)
            do_seed, reason = True, "builtin-missing"
        elif is_builtin and not _package_is_healthy(dest):
            # Self-heal, replacing the old unconditional force (memo dev/93
            # D1). Forcing the built-in on EVERY call re-copied its whole tree
            # per package request, and because the copy went straight into the
            # live directory it opened the window that left this store holding
            # only ``integrity.json`` — templates silently gone. Re-seeding
            # only a *broken* copy keeps the guarantee while letting a healthy
            # one fall through to the ordinary mtime check, which still picks
            # up a genuine fixture refresh.
            do_seed, reason = True, "builtin-unhealthy"
            log.warning(
                "Built-in package %s at %s is incomplete or unreadable — re-seeding",
                src.name, dest,
            )
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
        if not _swap_in_package(src, dest, dest_base):
            continue
        seed_state.mark_seeded(user_key, src.name, fixture_mtime)
        seeded.append(src.name)
        log.info("Seeded dev package %s into %s (%s)", src.name, dest_base, reason)
    return seeded
