"""The shared publish directory ``<repo_root>/packages/`` — the committed catalog every install copies from. The ONE ``catalog_root`` (memo dev/143 B2: routes, services and the seeder each carried a copy).

Memo dev/143, B2.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import IO

from utk_curio.backend.app.common.safe_paths import is_within
from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories.archive import (
    InstallerError,
    InstallResult,
    load_package_manifest_from_dir,
    _build_integrity,
    _extract_into,
)
from utk_curio.backend.app.packages.repositories.manifests import (
    load_package_manifest,
    merge_missing_manifest_created_at,
)

log = logging.getLogger(__name__)


#: Where the shared package catalog lives.
#:
#: ``<repo_root>/packages/`` by default, resolved from this file rather than
#: the launch CWD so a dev server finds it wherever it was started.
#:
#: Overridable because that default is one directory for every process on the
#: machine, whatever else they have been given their own copy of. Two backends
#: with separate ``CURIO_STATE_DIR``, ``CURIO_SHARED_DATA`` and databases still
#: shared this one: publishing on the first made the package appear in the
#: second's catalog, and left it untracked in a git-managed directory. Under
#: pytest-xdist that is one worker's fixture showing up in another worker's
#: catalog listing mid-test. The e2e shards set this per shard
#: (``backend/tests/shards.py``); nothing else should need to.
_CATALOG_ROOT_ENV = "CURIO_PACKAGES_ROOT"


def catalog_root() -> Path:
    """The shared package catalog directory for this process — the one copy
    (memo dev/143 B2): routes, the services module and the seeder each used to
    carry their own."""
    override = os.environ.get(_CATALOG_ROOT_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    # repositories/catalog_dir.py -> packages/ -> app/ -> backend/ -> utk_curio/ -> repo_root/packages/
    return Path(__file__).resolve().parents[5] / "packages"


def publish_package_archive_to_catalog_dir(
    archive: bytes | IO[bytes],
    catalog_parent: Path,
    *,
    replace: bool = False,
) -> InstallResult:
    """Extract and validate an archive directly under *catalog_parent*.

    Typical *catalog_parent* is ``<repo_root>/packages/`` — the committed
    catalog source used by ``GET /api/packages/catalog``. This must stay **off**
    unless the Flask route confirms an administrator opt-in env flag; writing
    there can trigger backend reload watchers in development.

    Layout and safety rules mirror :func:`install_package_from_archive`, but the
    final directory is ``catalog_parent / <manifest.dir_name>/`` instead of the
    per-user package tree. Uses :func:`shutil.move` so staging may live on a
    different filesystem than the catalog root.

    Raises
    ------
    InstallerError
        Same category of failures as the sideload installer (unsafe zip layout,
        bad manifest, existing dir when ``replace=False``).
    """
    if isinstance(archive, (bytes, bytearray)):
        stream: IO[bytes] = io.BytesIO(archive)
    else:
        stream = archive
        try:
            stream.seek(0)
        except (AttributeError, OSError):
            pass

    staging_root = Path(tempfile.mkdtemp(prefix="curio-publish-"))
    staging_alive: Path | None = staging_root
    try:
        try:
            zf_ctx = zipfile.ZipFile(stream, mode="r")
        except zipfile.BadZipFile as exc:
            raise InstallerError(f"archive is not a valid zip: {exc}") from exc

        with zf_ctx as zf:
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

            catalog_root = catalog_parent.resolve(strict=False)
            catalog_root.mkdir(parents=True, exist_ok=True)
            final_dest = (catalog_root / dir_name).resolve()
            if not is_within(final_dest, catalog_root):
                raise InstallerError(
                    f"refusing to publish outside catalog root ({final_dest})"
                )

            merge_missing_manifest_created_at(staging_root)

            integrity = _build_integrity(staging_root)
            (staging_root / "integrity.json").write_text(
                json.dumps({"sha256": integrity}, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            replaced_existing = False
            if final_dest.exists():
                if not replace:
                    raise InstallerError(
                        f"package {dir_name} already exists under catalog; "
                        "pass replace=True to overwrite the fixture directory"
                    )
                shutil.rmtree(final_dest)
                replaced_existing = True

            shutil.move(str(staging_root), str(final_dest))
            staging_alive = None

            loaded = load_package_manifest(final_dest)
            log.info(
                "Published package fixture %s to catalog dir %s (replace=%s)",
                loaded.dir_name,
                final_dest,
                replaced_existing,
            )
            return InstallResult(
                manifest=loaded,
                integrity=integrity,
                replaced_existing=replaced_existing,
            )
    finally:
        if staging_alive is not None:
            shutil.rmtree(staging_alive, ignore_errors=True)


def remove_package_from_catalog_dir(catalog_parent: Path, dir_name: str) -> bool:
    """Remove a committed catalog fixture directory under *catalog_parent*.

    Returns ``True`` when a directory was removed, ``False`` when absent.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise InstallerError(f"malformed package dir name {dir_name!r}")

    catalog_root = catalog_parent.resolve(strict=False)
    final_dest = (catalog_root / dir_name).resolve()
    if not is_within(final_dest, catalog_root):
        raise InstallerError(f"refusing to remove outside catalog root ({final_dest})")
    if not final_dest.is_dir():
        return False
    shutil.rmtree(final_dest)
    log.info("Removed package fixture %s from catalog dir %s", dir_name, final_dest)
    return True
