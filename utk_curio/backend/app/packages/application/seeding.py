"""Dev-only seeder that copies catalog packages into the guest user's package store.

The runtime ``.curio/users/<u>/packages/`` tree is gitignored, so committing a
package there is not an option. Instead we keep the source-of-truth package
at ``<repo_root>/packages/<dirname>/`` and copy it into the
guest user's package store at backend startup.

Besides ``curio.builtin`` (always seeded), the packages the bundled examples
declare as dependencies (see :func:`example_dep_package_ids`) are seeded too
when example projects are being seeded (``CURIO_SEED_EXAMPLES=1``, i.e.
``--with-examples``; ``docker-compose.deploy.yml`` passes it explicitly). Once they land in the user store, the
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

from utk_curio.backend.config import (
    CURIO_RESEED_PACKAGES,
    CURIO_SEED_EXAMPLES,
)
from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.domain.package_id import BUILTIN_PACKAGE_ID, PACKAGE_DIR_RE  # noqa: F401 — BUILTIN_PACKAGE_ID is read from here by the roster and the routes
from utk_curio.backend.app.packages.domain.spec_packages import (
    project_packages,
    set_project_packages,
)
from utk_curio.backend.app.packages.repositories import (
    catalog_dir as packages_catalog_dir,
    defaults as defaults_io,
    seed_state,
)
from utk_curio.backend.app.packages.repositories.archive import _build_integrity
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.publisher_record import RECORD_FILENAME
from utk_curio.backend.app.packages.repositories.store import (
    list_user_packages,
    user_packages_dir,
)
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.application.store_install import _purge_stale_staging

log = logging.getLogger(__name__)

# One seeding pass per user at a time (memo dev/93 D1). Four request handlers
# call the seeder (``GET /api/packages``, ``/catalog``, ``/defaults``, and the
# defaults POST), and the frontend fires several of them around canvas mount —
# so concurrent passes are the normal case, not a corner one. The contract
# itself lives in ``packages.locks`` (memo dev/99): readers hold the SAME lock,
# so neither side can drift from the other's filename or namespace.

# Staging lives INSIDE the package store so the swap rename is guaranteed
# same-filesystem. The prefix deliberately matches neither ``PACKAGE_DIR_RE``
# (so ``list_user_packages`` ignores it) nor the installer's ``.staging-*``
# / ``.stage-*`` sweep patterns (so a concurrent install cannot delete a
# seeding pass's half-built tree).
_SEED_STAGING_PREFIX = ".seed-staging-"



#: Packages we will not provision without being asked.
#:
#: A lockfile says what a dataflow NEEDS. This says what we are willing to
#: install as a side effect of booting with ``--with-examples`` or of opening a
#: dataflow that declares it. The two used to be the same list, which forced a
#: choice between a torch download on every boot and an example whose lockfile
#: lied about its own dependencies, and #233 is what the second one cost:
#: ``curio.streetvision`` went undeclared, so nothing could resolve the
#: example's node types and its three nodes sat on "Loading node…" forever with
#: nothing to say why.
#:
#: Membership is about install COST, not trust: a package whose libraries run
#: to gigabytes (torch, say) is a decision a user should make deliberately, in
#: the catalog, where the size is stated, and not something a project-open
#: request does to them. ``curio.streetvision`` was one until it needed only
#: onnxruntime; a Transformers model's torch now comes with that model, when
#: it is added from the Discovery Catalog.
INSTALL_ON_DEMAND_PACKAGE_IDS: frozenset[str] = frozenset()


def example_dep_package_ids() -> tuple[str, ...]:
    """Package IDs the seeded dataflows declare as dependencies.

    Walks every shipped dataflow (``projects/shipped.py``) and unions each spec's
    ``dataflow.packages`` lockfile, returning the package IDs (major
    stripped, sorted) — so the launcher (their python deps) and this seeder
    (copy into the user store) provision exactly the packages the examples
    depend on, with no hardcoded allowlist to keep in sync.

    Minus ``curio.builtin``, which every store is seeded with anyway (a test
    dataflow declares it), and minus :data:`INSTALL_ON_DEMAND_PACKAGE_IDS`.
    An example may declare a heavy
    package — it has to, or nothing downstream can tell what its nodes need —
    without that declaration turning into a multi-gigabyte pip run on every
    ``--with-examples`` / ``--deploy`` boot. Shared source of truth: the
    launcher's catalog dep walk
    (``utk_curio/main.py::install_manifest_dependencies``) calls this too.
    """
    from utk_curio.backend.app.projects.shipped import shipped_dataflows

    ids: set[str] = set()
    for json_path in (s.path for s in shipped_dataflows()):
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
    return tuple(sorted(ids - INSTALL_ON_DEMAND_PACKAGE_IDS - {BUILTIN_PACKAGE_ID}))


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

    try:
        load_package_manifest(dest)
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


def _integrity_map(package_root: Path) -> dict[str, str] | None:
    """The ``sha256`` map from a package's ``integrity.json``, or ``None``.

    ``None`` means "cannot say" - absent, unreadable or malformed - and every
    caller treats that as "leave it alone" rather than guessing.
    """
    path = package_root / "integrity.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    listed = raw.get("sha256") if isinstance(raw, dict) else None
    return listed if isinstance(listed, dict) else None


#: Computed catalog hashes, keyed by ``(package path, max mtime)``. Hashing a
#: package tree is the one expensive part of the staleness check, and the answer
#: cannot change while its newest mtime does not — so a boot that opens several
#: dataflows walks each package once, not once per open.
_CATALOG_CONTENT: dict[tuple[str, float], dict[str, str]] = {}


def _catalog_content_map(src: Path, fixture_mtime: float) -> dict[str, str] | None:
    """SHA-256 of every file in the CATALOG copy, computed rather than declared.

    Not ``integrity.json``: a package's committed map can disagree with the
    files committed beside it, after an edit that never re-ran the integrity
    refresh. Trusting it would mark every faithful install of that package
    permanently stale and re-copy it on every pass, which is precisely the
    per-request destruction memo dev/93 D1 removed.
    """
    key = (str(src), fixture_mtime)
    cached = _CATALOG_CONTENT.get(key)
    if cached is not None:
        return cached
    try:

        computed = _build_integrity(src)
    except Exception:  # noqa: BLE001 — a catalog we cannot hash is not "stale"
        log.warning("Could not hash catalog package %s", src, exc_info=True)
        return None
    _CATALOG_CONTENT.clear()  # one package's worth of memo is all that is useful
    _CATALOG_CONTENT[key] = computed
    return computed


def _store_copy_is_stale(src: Path, dest: Path, fixture_mtime: float) -> bool:
    """True when the catalog has moved on from the user's copy (#194).

    A fix can ship inside a package at an unchanged version - the catalog under
    ``<repo_root>/packages`` moves, the coordinate does not - and installing is
    copy-once, so the user keeps whatever they first copied. That is how the
    Column Filter fix failed to reach anyone who already had
    ``curio.example-ui@1``: same ``@1``, same version, older bytes.

    Content, not mtime. ``should_seed`` compares fixture mtimes, which is right
    for a dev fixture the author is editing, but git rewrites mtimes on
    checkout - so an mtime rule re-copies on every clone and still misses a
    change that happens to preserve them.

    The two sides are deliberately asymmetric. The catalog is **computed**, for
    the reason in :func:`_catalog_content_map`. The store's own
    ``integrity.json`` is **trusted**, because the installer writes it from the
    tree it just staged, so it describes that copy exactly and costs nothing to
    read - and a copy whose files drifted from its own map is damaged rather
    than out of date, which is a different problem with a different owner
    (:func:`_package_is_healthy`).

    Conservative on doubt: if either side cannot be read, nothing is touched.
    """
    catalog = _catalog_content_map(src, fixture_mtime)
    installed = _integrity_map(dest)
    if catalog is None or installed is None:
        return False
    return catalog != installed


def _refresh_decision(
    src: Path, dest: Path, fixture_mtime: float, record: seed_state.PackageSeedRecord | None,
) -> tuple[bool, str]:
    """Should the seeder replace the store copy at *dest* with the catalog's?

    Only when the catalog moved and the user did not (#564). Both make the two
    copies differ, so the difference alone cannot say which happened; the
    seed-state record says where the copy came from:

    * a copy the catalog wrote, whose map still has the recorded digest, is
      untouched and is refreshed when the catalog moves (#194);
    * a copy the catalog wrote and something changed since, or a copy holding
      the user's own content, is the user's and is left alone. **Update**
      replaces it with the catalog's copy and puts it back on this track;
    * a copy with no origin on record predates the record, or lost it (a
      corrupt or missing state file, a failed write). It is refreshed only
      when it is provably an untouched catalog copy from an earlier release
      (:func:`_is_untouched_catalog_copy`). Anything else may hold the user's
      work, so it is kept (``unrecorded-kept``) and recorded as theirs.
    """
    rec = record or seed_state.PackageSeedRecord()
    if rec.catalog_copy is not None:
        installed = _integrity_map(dest)
        if installed is None or seed_state.copy_digest(installed) != rec.catalog_copy:
            return False, "changed-since-catalog-copy"
    elif rec.installed_at is not None:
        return False, "user-content"
    stale = _store_copy_is_stale(src, dest, fixture_mtime)
    if stale:
        if rec.catalog_copy is None and not _is_untouched_catalog_copy(src.name, dest):
            return False, "unrecorded-kept"
        return True, "catalog-content-advanced"
    if rec.catalog_copy is None:
        return False, "unrecorded-content-identical"
    return False, "content-identical"


def _is_untouched_catalog_copy(dir_name: str, dest: Path) -> bool:
    """True when an unrecorded store copy is byte for byte an older catalog copy.

    Two things must hold. Its ``integrity.json`` map is one the catalog has
    shipped for this package (:func:`seed_state.legacy_catalog_digests`), so
    no install path wrote it from the user's content. And its files still
    hash to that map, so nothing was edited in place after the copy was made:
    a metadata edit before #564 rewrote the manifest without touching
    ``integrity.json``, and only this second check sees it.
    """
    installed = _integrity_map(dest)
    if installed is None:
        return False
    known = seed_state.legacy_catalog_digests().get(dir_name, frozenset())
    if seed_state.copy_digest(installed) not in known:
        return False
    try:
        return _build_integrity(dest) == installed
    except Exception:  # noqa: BLE001: a copy we cannot hash is not provably untouched
        log.warning("Could not hash store package %s", dest, exc_info=True)
        return False


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
        # The publisher record does not travel: it names whoever published the
        # package INTO THE CATALOG, and copying it would hand that key to every
        # other user's store and leave a file the store's own integrity map
        # does not describe. ``integrity.json`` does travel — it is the store
        # copy's own map, and :func:`_store_copy_is_stale` reads it.

        shutil.copytree(
            src, new_tree,
            ignore=lambda _dir, names: [n for n in names if n == RECORD_FILENAME],
        )
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


def seed_dev_packages(*, user_key: str = "guest") -> list[str]:
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
    return _seed_dev_packages_locked(user_key=user_key)


def _seed_dev_packages_locked(*, user_key: str) -> list[str]:
    """Body of :func:`seed_dev_packages`. Plans the fixture reads unlocked,
    then takes the per-user store lock for the store work itself."""
    src_root = packages_catalog_dir.catalog_root()
    if not src_root.is_dir():
        return []

    dest_base = user_packages_dir(user_key)
    dest_base.mkdir(parents=True, exist_ok=True)

    # Sweep any orphaned staging dirs left behind by an install that
    # was SIGKILL'd / lost power before its TemporaryDirectory could
    # clean up — both the current ``.package-staging/`` location and the
    # legacy ``packages/.staging-*`` location from earlier builds. The
    # installer does this on every install too, but the seeder is the
    # only thing that touches the package store on a cold startup with no
    # in-flight install request.
    try:
        _purge_stale_staging(user_key)
    except Exception:  # noqa: BLE001 — cleanup must never crash startup
        log.warning("Stale-staging sweep failed", exc_info=True)

    # memo dev/99 R1.3: everything that reads the FIXTURE catalog — not the
    # user's store — is resolved before the lock is taken. Readers now wait on
    # this lock, so its hold is exactly the store work: health checks, swaps,
    # state markers. The fixture rglob and the docs/examples scan are not
    # store work and would only lengthen every reader's wait.
    installed_names = frozenset(
        p.name for p in dest_base.iterdir() if p.is_dir() and PACKAGE_DIR_RE.match(p.name)
    ) if dest_base.is_dir() else frozenset()
    plan = _plan_seed(src_root, installed_names)
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


def _plan_seed(src_root: Path, installed_names: frozenset[str] = frozenset()) -> _SeedPlan:
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

    # Packages the user ALREADY has are candidates too, so an upgrade can reach
    # them (#194). They are only ever refreshed in place - never installed - and
    # a package the user uninstalled is not in the store, so it cannot come back
    # through this door.
    keep_names |= set(installed_names)

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
        elif dest.exists() and not is_builtin:
            # A package the store already holds. The only question here is
            # whether an upgrade moved the catalog underneath a copy nobody
            # changed (#194, #564): the mtime rules below are for deciding
            # whether to INSTALL something, and ``untracked-existing-copy`` in
            # particular declines to touch a copy that arrived through the
            # catalog drawer rather than the seeder, which is every package
            # this branch sees.
            #
            # Nothing else can happen to it here. It is never removed, and a
            # package the user uninstalled is absent from the store, so it is
            # not a candidate at all and cannot be resurrected.
            do_seed, reason = _refresh_decision(src, dest, fixture_mtime, record)
            if reason == "unrecorded-content-identical":
                # Identical to the catalog, so it is the catalog's copy: record
                # it as one, the way ``untracked-existing-copy`` is adopted below.
                installed = _integrity_map(dest)
                if installed is not None:
                    seed_state.mark_catalog_copy(
                        user_key, src.name, seed_state.copy_digest(installed),
                    )
            elif reason == "unrecorded-kept":
                # Differs from the catalog and is not provably a catalog copy:
                # record it as the user's, so later passes keep it without
                # hashing it again and **Update** is the way back.
                seed_state.mark_installed(user_key, src.name, catalog_copy=None)
                log.info("Kept unrecorded store package %s as the user's copy", src.name)
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
        swapped = _integrity_map(dest)
        seed_state.mark_seeded(
            user_key, src.name, fixture_mtime,
            catalog_copy=seed_state.copy_digest(swapped) if swapped is not None else None,
        )
        seeded.append(src.name)
        log.info("Seeded dev package %s into %s (%s)", src.name, dest_base, reason)
    return seeded


def ensure_user_packages_initialized(user_key: str) -> None:
    """Idempotently seed the per-user package store with ``curio.builtin``.

    The startup seeder in ``app/__init__.py`` only runs for the shared
    ``guest`` user, so the first time a real authenticated user touches the
    package system, their store is empty and the palette would be missing
    even the built-in nodes. Call this at the project-entry boundaries
    (save_project, load_project) so the user always has builtin available
    by the time the canvas mounts.

    Safe to call repeatedly: :func:`seed_dev_packages` consults the
    per-user marker file and only re-seeds when fixtures have actually
    moved.
    """
    try:
        seed_dev_packages(user_key=user_key)
    except Exception:  # noqa: BLE001 — seeding must never block a project request
        log.warning("Builtin seed failed for user_key=%s", user_key, exc_info=True)


def seed_spec_with_defaults(user_key: str, spec: dict | None) -> dict:
    """Merge per-user defaults into a new project's spec lockfile.

    Only acts when the spec's existing packages list is empty/missing.
    Returns the (possibly mutated) spec; safe to call with ``None``
    (returns an empty spec template).
    """
    if spec is None or not isinstance(spec, dict):
        spec = {"dataflow": {"nodes": [], "edges": [], "packages": []}}
    existing = project_packages(spec)
    if existing:
        return spec
    defaults = defaults_io.load_defaults(user_key)
    if not defaults:
        return spec
    set_project_packages(spec, defaults)
    return spec


def ensure_user_seeded(user_key: str) -> None:
    """Idempotently seed ``curio.builtin@1`` into ``user_key``'s package store
    AND defaults list.

    Startup-time seeding only handles the shared ``guest`` key, so signed-up
    accounts (and ``/api/testing/stub-login`` users during e2e tests) land
    with an empty store. ``/api/packages`` and ``/api/packages/catalog`` both
    rely on the user's store to compute "installed" - without a seed, the
    catalog page shows the built-in package as available-but-not-installed
    and any saved dataflow's nodes fail to find their descriptors. The
    catalog page additionally reads ``defaults`` to render the "Installed"
    badge, so we also add the seeded builtin to defaults - symmetric with
    the catalog-page install path. The seeder and defaults writer are both
    idempotent (a marker file + a sorted set on disk), so this is a no-op
    after the first call.
    """
    try:
        seed_dev_packages(user_key=user_key)
        # The seeder returns only NEWLY-seeded names, so a re-seed-suppressed
        # call returns []. Inspect the store directly to find whatever
        # ``curio.builtin@<major>`` the user actually has and ensure it's in
        # defaults - covers both first-run and "store exists but defaults
        # never got the entry" (e.g. an earlier seed before this code shipped).
        prefix = f"{BUILTIN_PACKAGE_ID}@"
        existing_defaults = defaults_io.load_defaults(user_key)
        # Names-only snapshot under the seed lock (memo dev/99); the defaults
        # write happens after release - the seed lock is a leaf.
        with package_seed_lock(user_key):
            builtin_names = [
                p.name for p in list_user_packages(user_key) if p.name.startswith(prefix)
            ]
        for name in builtin_names:
            if name not in existing_defaults:
                defaults_io.add_to_defaults(user_key, name)
    except Exception:  # noqa: BLE001 - never block the request on a seed error
        log.warning("Lazy builtin seed failed for user_key=%s", user_key, exc_info=True)
