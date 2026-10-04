"""Install into the per-user package store: copy from the catalog, provision its libraries, report the outcome. (``install`` never stands alone — this is the STORE install; ``project_packages`` and ``defaults_install`` are the other two.)

Application layer of the packages package (memo dev/143, B2): cut from ``services.py``
by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``packages_<module>.name``) so a test that patches the owner is seen by
every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import IO

from utk_curio.backend.app.common.safe_paths import is_within
from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.domain.package_id import BUILTIN_PACKAGE_ID, PACKAGE_DIR_RE, PackageIdError
from utk_curio.backend.app.packages.repositories import (
    catalog_dir as packages_catalog_dir,
    python_modules as packages_python_modules,
    seed_state,
)
from utk_curio.backend.app.packages.repositories.archive import (
    InstallerError,
    InstallResult,
    load_package_manifest_from_dir,
    zip_package_tree,
    _build_integrity,
    _extract_into,
    _touch_manifest_for_install_recency,
)
from utk_curio.backend.app.packages.repositories.manifests import (
    load_package_manifest,
    merge_missing_manifest_created_at,
)
from utk_curio.backend.app.packages.repositories.store import (
    package_dir,
    user_package_staging_dir,
    user_packages_dir,
)
from utk_curio.backend.app.packages.infrastructure import backend_runtime as packages_backend_runtime
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.infrastructure.pip_runner import PipInstallError
from utk_curio.backend.app.packages.application import (
    provisioning as packages_provisioning,
    store_reads as packages_store_reads,
)
from utk_curio.backend.app.packages.domain.errors import PackageServiceError
from utk_curio.backend.app.packages.application.provisioning import InstallOutcome

log = logging.getLogger(__name__)


_STAGING_PREFIX = "stage-"


# A staging dir younger than this is assumed to belong to a live install and is
# never swept, whatever the caller passed as ``keep``. ``keep`` only protects the
# sweeper's *own* directory, which is no help against a sweeper that is not
# installing anything: ``seed_dev_packages`` runs on every ``GET
# /api/packages`` (see ``routes.py``), and the drawer's import flow fires that
# listing from ``refreshPackageRegistry`` while the upload it just posted is
# still extracting. The sweep then deletes the extraction mid-flight and the
# install fails with ENOENT on a file it had already written. Age is the right
# discriminator because an orphan is by definition one nothing is writing to;
# anything genuinely abandoned is still collected on the next sweep after this
# window.
_STAGING_ORPHAN_MIN_AGE_S = 600.0


def _is_recent(entry: "Path", now: float) -> bool:
    """True when *entry* was touched inside the live-install window."""
    try:
        return (now - entry.stat().st_mtime) < _STAGING_ORPHAN_MIN_AGE_S
    except OSError:
        # Vanished under us, or unreadable. Either way, leave it alone.
        return True


def _purge_stale_staging(user_key: str, keep: "Path | None" = None) -> None:
    """Remove any orphaned staging directories for ``user_key``.

    Two guards keep a live install safe, and both are needed:

    * *keep* is the caller's own in-flight staging directory, which must never be
      swept: Flask serves requests concurrently, so a second install starting
      while the first is mid-extract would otherwise delete the first's tree out
      from under it (surfacing as ``WinError 2`` from the manifest-validation
      copytree on a file that had just been written).
    * Age (``_STAGING_ORPHAN_MIN_AGE_S``) covers everyone *else*'s in-flight
      directory, which ``keep`` cannot: a sweeper that is not installing has no
      ``keep`` to pass. The seeder is exactly that case.

    Two sources need sweeping:

    * The current staging location ``<user>/.package-staging/stage-*/`` —
      anything left there is from a crashed install (SIGKILL / power
      loss / Werkzeug reload before our atomic move completed).
    * The legacy location ``<user>/packages/.staging-*/`` from builds
      that staged inside the package store. This is the directory the
      watchdog reloader was finding mid-install; the sweep migrates
      stragglers off before they can trigger another reload cycle.

    Best-effort; never raises.
    """
    staging_base = user_package_staging_dir(user_key)
    keep_resolved = keep.resolve() if keep is not None else None
    now = time.time()
    if staging_base.is_dir():
        for entry in staging_base.iterdir():
            if not entry.is_dir():
                continue
            if _is_recent(entry, now):
                # Someone else's live install (see _STAGING_ORPHAN_MIN_AGE_S).
                continue
            if not entry.name.startswith(_STAGING_PREFIX):
                # Only sweep what this module created. A concurrent install's
                # validate copy also lives here (see
                # load_package_manifest_from_dir) and deleting it mid-copy is
                # exactly the race this guard exists to prevent.
                continue
            if keep_resolved is not None and entry.resolve() == keep_resolved:
                continue
            try:
                shutil.rmtree(entry, ignore_errors=True)
            except Exception:  # noqa: BLE001 — cleanup must never crash install
                log.warning("Failed to purge stale staging dir %s", entry, exc_info=True)

    legacy_base = user_packages_dir(user_key)
    if legacy_base.is_dir():
        for entry in legacy_base.iterdir():
            if not entry.is_dir():
                continue
            if not entry.name.startswith(".staging-") and not entry.name.startswith(".stage-"):
                continue
            if _is_recent(entry, now):
                continue
            try:
                shutil.rmtree(entry, ignore_errors=True)
            except Exception:  # noqa: BLE001
                log.warning("Failed to purge legacy staging dir %s", entry, exc_info=True)


def install_package_from_archive(
    user_key: str,
    archive: bytes | IO[bytes],
    *,
    replace: bool = False,
    from_catalog: bool = False,
) -> InstallResult:
    """Install (or replace) a ``.curio.zip`` archive for *user_key*.

    Steps:

    1. Open the bytes as a ZipFile (memory-only, no disk roundtrip).
    2. Extract everything into a tmp dir under the per-user package store
       — never the final destination. This means a half-broken archive
       can't leave a corrupted package on disk.
    3. Load + validate the manifest from the tmp dir.
    4. Cross-check the manifest's ``<packageId>@<major>`` against the
       final destination directory name; refuse if a package at that
       coordinate is already installed unless ``replace=True``.
    5. Compute SHA-256 integrity of every shipped file and write
       ``integrity.json`` inside the package root.
    6. Atomically move the tmp dir to the final destination.

    Parameters
    ----------
    user_key:
        Either ``"guest"`` or a numeric user id (validated by the
        storage layer's :func:`user_packages_dir`).
    archive:
        The raw zip bytes, or an open binary stream. The stream is
        rewound to 0 before reading.
    replace:
        When ``True``, an existing ``<packageId>@<major>`` directory for
        *user_key* is removed first. Default ``False`` — repeat installs
        of the same coordinate raise.
    from_catalog:
        ``True`` when the archive is the shared catalog's copy, which keeps
        the store copy on the catalog's refresh track (#194). Everything
        else is the user's own content, and the seeder leaves it alone (#564).

    Returns
    -------
    InstallResult
        ``manifest`` (the validated :class:`PackageManifest`),
        ``integrity`` (the ``{relative_path: sha256_hex}`` map), and
        ``replaced_existing`` (whether *replace* actually displaced an
        existing package).

    Raises
    ------
    InstallerError
        Archive is malformed, paths are unsafe, manifest is invalid,
        size cap exceeded, or destination already exists and
        ``replace=False``.
    """
    if isinstance(archive, (bytes, bytearray)):
        stream: IO[bytes] = io.BytesIO(archive)
    else:
        stream = archive
        try:
            stream.seek(0)
        except (AttributeError, OSError):
            pass

    try:
        zf = zipfile.ZipFile(stream, mode="r")
    except zipfile.BadZipFile as exc:
        raise InstallerError(f"archive is not a valid zip: {exc}") from exc

    with zf:
        # Stage extraction in a tmp dir **outside** the user's package
        # store. Writing ``.py`` templates into ``<user>/packages/`` would
        # trigger Werkzeug's watchdog reloader mid-install and kill the
        # response before the atomic move completes (which is exactly
        # the "Failed to fetch" install bug this layout fixes). The
        # sibling ``.package-staging/`` directory is on the same
        # filesystem so :func:`os.replace` still moves atomically.
        user_packages_dir(user_key).mkdir(parents=True, exist_ok=True)
        staging_base = user_package_staging_dir(user_key)
        staging_base.mkdir(parents=True, exist_ok=True)
        # Claim our own staging dir BEFORE sweeping, then exclude it: the sweep
        # is indiscriminate, and a concurrent install must not delete a tree that
        # is still being extracted.
        staging_root = Path(
            tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=str(staging_base))
        )
        # Best-effort sweep of any orphaned staging dirs from a previous
        # crashed install. ``tempfile.mkdtemp`` does not clean up after
        # a SIGKILL / power loss, and the orphans accumulate every cycle.
        _purge_stale_staging(user_key, keep=staging_root)
        try:
            _extract_into(zf, staging_root)
            try:
                manifest = load_package_manifest_from_dir(staging_root)
            except ManifestError as exc:
                raise InstallerError(str(exc)) from exc

            dir_name = manifest.dir_name
            if not PACKAGE_DIR_RE.match(dir_name):
                raise InstallerError(
                    f"manifest derives malformed package dir name {dir_name!r}"
                )

            final_dest = package_dir(user_key, dir_name)
            merge_missing_manifest_created_at(staging_root)
            integrity = _build_integrity(staging_root)
            (staging_root / "integrity.json").write_text(
                json.dumps({"sha256": integrity}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            # Replace and record under the store lock (memo dev/99), the one
            # the seeder swaps under: a reader never sees the package missing
            # between the rmtree and the move, and a seeding pass cannot decide
            # to refresh the old copy and then swap it in over this one.
            with package_seed_lock(user_key):
                packages_python_modules.refuse_a_module_name_in_use(user_key, staging_root, manifest)
                replaced = False
                if final_dest.exists():
                    if not replace:
                        raise InstallerError(
                            f"package {dir_name} already installed; pass replace=True "
                            f"to overwrite"
                        )
                    shutil.rmtree(final_dest)
                    replaced = True
                staging_root.replace(final_dest)
                _touch_manifest_for_install_recency(final_dest)
                merged_manifest = load_package_manifest(final_dest)
                # An explicit (re)install supersedes any prior uninstall
                # tombstone the dev seeder might otherwise honour, and says where
                # this copy came from: the seeder refreshes a catalog copy nobody
                # has changed, and never the user's own content (#564).
                try:
                    seed_state.mark_installed(
                        user_key, dir_name,
                        catalog_copy=seed_state.copy_digest(integrity) if from_catalog else None,
                    )
                except Exception:  # noqa: BLE001: bookkeeping is best-effort
                    log.exception("Failed to record the install of %s/%s", user_key, dir_name)

            return InstallResult(
                manifest=merged_manifest,
                integrity=integrity,
                replaced_existing=replaced,
            )
        except Exception:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise


def uninstall_package(user_key: str, dir_name: str) -> bool:
    """Remove ``<user>/packages/<dir_name>``. Returns ``True`` if anything was deleted.

    Also drops a tombstone in the per-user seed-state file so the dev
    seeder (see :mod:`.seed`) does not resurrect this package on the next
    backend hot-reload — that "uninstall isn't sticky" bug is the
    regression this side-effect exists to prevent.
    """
    target = package_dir(user_key, dir_name)
    with package_seed_lock(user_key):  # memo dev/99: the seeder's lock
        if not target.exists():
            return False
        shutil.rmtree(target)
        try:
            seed_state.mark_uninstalled(user_key, dir_name)
        except Exception:  # noqa: BLE001: never block uninstall on bookkeeping
            log.exception("Failed to record uninstall tombstone for %s/%s", user_key, dir_name)
    return True


def install_package_from_directory(
    user_key: str,
    source_dir: Path,
    *,
    replace: bool = False,
) -> InstallResult:
    """Install a package from a directory on disk (committed catalog entry).

    ``POST /api/packages/catalog/install`` copies from
    ``<repo_root>/packages/<packageId>@<major>/`` into the user's package
    store by re-zipping and reusing :func:`install_package_from_archive` — same
    validation and integrity hashing as sideload. No separate download
    service is required until a hosted registry exists.

    The implementation funnels through :func:`install_package_from_archive`
    so the manifest validator, size caps, and integrity-hash writer are
    all the same code path the sideload uses.
    """
    if not source_dir.is_dir():
        raise InstallerError(f"catalog source {source_dir} is not a directory")
    return install_package_from_archive(
        user_key, zip_package_tree(source_dir), replace=replace, from_catalog=True,
    )


def export_package_archive(
    user_key: str,
    dir_name: str,
    *,
    catalog_root: Path | None = None,
) -> bytes:
    """Repackage a package back into a deterministic ``.curio.zip`` zip.

    Useful for the factory ("Export package" button) and for migrating an
    installed package from one user to another. The archive layout matches
    the one :func:`install_package_from_archive` accepts, so a round-trip
    install -> export -> install is lossless.

    The user's own store copy is preferred. When the account has never
    installed the package but it is in the committed catalog (*catalog_root*),
    the catalog copy is exported instead: the Node Catalog page offers "View
    details -> Export" on every row it lists, and a row the user had not added
    answered ``package X is not installed`` - true, and useless from a page
    whose whole point is that the package is right there (#275).
    """
    target = package_dir(user_key, dir_name)
    if target.is_dir():
        return zip_package_tree(target)
    if catalog_root is not None:
        base = catalog_root.resolve()
        candidate = (base / dir_name).resolve()
        if is_within(candidate, base) and (candidate / "manifest.json").is_file():
            return zip_package_tree(candidate)
        raise InstallerError(f"package {dir_name} is neither installed nor in the catalog")
    raise InstallerError(f"package {dir_name} is not installed")


def _ensure_user_store_install(user_key: str, dir_name: str) -> InstallOutcome:
    """Copy *dir_name* from the shared catalog when it is missing, install the
    python deps its manifest declares, and report whether they import.

    The pip step runs synchronously inside the request — heavy installs like
    ``torch`` can take many minutes (see :mod:`.pip_runner`). The Install button
    stays in its busy state for the whole duration. If pip fails the catalog
    copy is rolled back so a retry can re-attempt cleanly.

    Already-installed is answered, not skipped: the caller's real question is
    "can the user use this package now", and a package that has sat in the store
    for a week can have had its library broken under it since. For a host-routed
    package that costs one memo lookup after the first probe in the process; a
    backend-bearing one re-probes its overlay, which is deliberately unmemoised
    (see :func:`_declared_import_failures`).
    """
    if packages_store_reads._is_installed_in_user_store(user_key, dir_name):
        return InstallOutcome(
            copied=False,
            import_errors=packages_provisioning._declared_import_failures(user_key, dir_name),
        )
    # Before the copy, not in provision_python_deps: a refusal there leaves
    # the files in the store, and the next call takes the branch above (#451).
    packages_provisioning.assert_may_install()
    src = packages_catalog_dir.catalog_root() / dir_name
    if not src.is_dir():
        raise PackageServiceError(
            f"catalog has no package {dir_name}", 404,
        )
    try:
        result = install_package_from_directory(user_key, src, replace=False)
    except InstallerError as exc:
        raise PackageServiceError(str(exc)) from exc

    # memo dev/91: the catalog path is an install authority too — pin (or
    # clear) the backend entry digest so promote-less installs stay
    # verifiable and a reinstall never trips a stale pin.
    packages_backend_runtime.record_entry_pin(user_key, dir_name)

    try:
        outcome = packages_provisioning.provision_python_deps(user_key, dir_name, result.manifest)
    except (PipInstallError, packages_backend_runtime.BackendRuntimeError) as exc:
        # Roll the just-installed files back so the user-store doesn't show a
        # package that's unusable. Best-effort: log + continue on cleanup
        # failure (the original error is the one we surface).
        #
        # Reserved for pip actually failing. A library that installed and
        # cannot be imported never reaches here — undoing the install over an
        # environment problem the user has to fix anyway would only take away
        # the package that named the problem.
        try:
            shutil.rmtree(package_dir(user_key, dir_name), ignore_errors=True)
            packages_backend_runtime.remove_backend_residue(user_key, dir_name)
            seed_state.clear(user_key, dir_name)
        except Exception:  # noqa: BLE001
            log.warning("Failed to roll back %s after dep failure", dir_name, exc_info=True)
        raise PackageServiceError(
            f"package files installed but its dependencies failed: {exc}",
        ) from exc
    return InstallOutcome(
        copied=True,
        installed=outcome.installed,
        import_errors=outcome.import_errors,
    )


def install_to_store(user_key: str, dir_name: str) -> InstallOutcome:
    """Install *dir_name* into the user's package store (+ its python deps),
    without touching any project lockfile.

    Used by the workflow-deps auto-install: a freshly loaded/imported
    dataflow has no project to scope a lockfile to, but installing the
    owning package into the store is enough to make it show as installed
    (catalog drawer / libraries menu key off the store) and to provision
    its libraries + nodes. Raises :class:`PackageServiceError` on failure
    (catalog miss, pip failure); ``InstallOutcome.copied`` says whether a copy
    was performed, and ``.import_errors`` whether the libraries actually work.

    If the package is already in the store, its declared python deps are
    re-ensured (idempotent pip run) — this repairs the case where a lib was
    pip-uninstalled out from under an installed package. The repair routes by
    the same rule the original install did, so a backend-bearing package's
    overlay is rebuilt rather than its deps being quietly redirected at the
    host interpreter its handlers never import from.
    """
    packages_provisioning.assert_may_install()

    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")
    if not packages_store_reads._is_installed_in_user_store(user_key, dir_name):
        return _ensure_user_store_install(user_key, dir_name)
    # Already in the store — repair any declared dep that isn't present.
    manifest = packages_store_reads._read_manifest(user_key, dir_name)
    if manifest is None:
        return InstallOutcome()

    try:
        return packages_provisioning.provision_python_deps(user_key, dir_name, manifest)
    except (PipInstallError, packages_backend_runtime.BackendRuntimeError) as exc:
        raise PackageServiceError(f"pip install failed: {exc}", 502) from exc


def install_from_catalog(user_key: str, dir_name: str, *, replace: bool) -> InstallResult:
    """Install a catalog package by its on-disk directory name — the drawer's
    "Reload from catalog". Copies ``<repo_root>/packages/<dir_name>/`` into the
    user's store through the same validator, size caps and integrity writer the
    sideload uses; ``InstallerError`` propagates. A missing catalog entry is a
    :class:`PackageServiceError` 404."""
    packages_provisioning.assert_may_install()
    src = packages_catalog_dir.catalog_root() / dir_name
    if not src.is_dir():
        raise PackageServiceError(f"catalog has no package {dir_name}", 404)
    result = install_package_from_directory(user_key, src, replace=replace)
    # Same as the first copy in _ensure_user_store_install: a replaced backend
    # entry keeps its old pin otherwise, and every invocation is refused.
    packages_backend_runtime.record_entry_pin(user_key, dir_name)
    return result


def remove_package(user_key: str, dir_name: str) -> None:
    """Uninstall *dir_name* from the user store with its backend residue
    (dev/97: overlay, data dir, pin — the invocation ledger survives). The
    builtin is refused; a package that is not installed is a 404;
    ``PackageIdError`` propagates for a malformed name."""
    if dir_name.startswith(f"{BUILTIN_PACKAGE_ID}@"):
        raise PackageServiceError(f"{BUILTIN_PACKAGE_ID} is built-in and cannot be uninstalled", 400)
    if not uninstall_package(user_key, dir_name):
        raise PackageServiceError("package not installed", 404)
    packages_backend_runtime.remove_backend_residue(user_key, dir_name)


def archive_for_download(user_key: str, dir_name: str) -> bytes:
    """The archive a download answers with: the user's store copy, else the
    committed catalog copy (the catalog page exports every row it lists, #275).
    A package in neither place — or a malformed name — is a 404: to the
    caller it is not there."""
    try:
        return export_package_archive(
            user_key, dir_name, catalog_root=packages_catalog_dir.catalog_root(),
        )
    except (InstallerError, PackageIdError) as exc:
        raise PackageServiceError(str(exc), 404) from exc
