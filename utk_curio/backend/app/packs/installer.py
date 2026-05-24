"""Sideload installer for ``.curio-nodepack`` archives.

This module materialises validated ``.curio-nodepack`` extracts into:

* **Per-user store:** ``<CURIO_LAUNCH_CWD>/.curio/users/<u>/packs/<packId>@<major>/``
  (everyday install paths).
Sideload (multipart zip upload) is the primary way users install arbitrary packs.
Catalog install copies committed packs from :func:`publish_pack_archive_to_catalog_dir`
when publishing from the factory.
A **hosted remote pack registry** (separate download service) is not implemented yet;
today the catalog lives on disk at ``<repo_root>/packs/``.

Hard rules enforced here (self-contained packs and archive safety):

* The archive is a regular ZIP file — nothing else (rar, tar) is accepted.
* Every entry name is normalised through :func:`_safe_member_path`, which
  rejects absolute paths, ``..`` traversal, NUL bytes, non-printables,
  and any segment outside ``[A-Za-z0-9._-]``. This is the same charset
  the rest of Curio's safe-path layer accepts.
* Top-level entries must be one of the allowed file names (manifest /
  README / LICENSE) or one of the allowed top-level *directories*
  (``templates`` / ``grammars`` / ``widgets`` / ``icons``).
* The manifest is validated **inside a temp dir** (via the existing
  :func:`load_pack_manifest`) before anything moves to the final
  per-user pack root. If validation fails, the temp dir is wiped and
  the on-disk pack store is untouched.
* Final directory name **must** match ``<packId>@<major>`` from the
  manifest. We never trust the archive's claimed directory name.

An ``integrity.json`` file with SHA256 of every shipped file is written
alongside the manifest, so downstream code (resolver lockfile, factory
re-export) can pin the bits exactly.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from utk_curio.backend.app.common.safe_paths import (
    PathTraversalError,
    is_within,
)
from utk_curio.backend.app.packs.manifest import (
    ManifestError,
    PackManifest,
    load_pack_manifest,
    merge_missing_manifest_created_at,
)
from utk_curio.backend.app.packs.storage import (
    PACK_DIR_RE,
    pack_dir,
    user_pack_staging_dir,
    user_packs_dir,
)

log = logging.getLogger(__name__)


_STAGING_PREFIX = "stage-"


def _purge_stale_staging(user_key: str) -> None:
    """Remove any orphaned staging directories for ``user_key``.

    Two sources need sweeping:

    * The current staging location ``<user>/.pack-staging/stage-*/`` —
      anything left there is from a crashed install (SIGKILL / power
      loss / Werkzeug reload before our atomic move completed).
    * The legacy location ``<user>/packs/.staging-*/`` from builds
      that staged inside the pack store. This is the directory the
      watchdog reloader was finding mid-install; the sweep migrates
      stragglers off before they can trigger another reload cycle.

    Best-effort; never raises.
    """
    staging_base = user_pack_staging_dir(user_key)
    if staging_base.is_dir():
        for entry in staging_base.iterdir():
            if not entry.is_dir():
                continue
            try:
                shutil.rmtree(entry, ignore_errors=True)
            except Exception:  # noqa: BLE001 — cleanup must never crash install
                log.warning("Failed to purge stale staging dir %s", entry, exc_info=True)

    legacy_base = user_packs_dir(user_key)
    if legacy_base.is_dir():
        for entry in legacy_base.iterdir():
            if not entry.is_dir():
                continue
            if not entry.name.startswith(".staging-") and not entry.name.startswith(".stage-"):
                continue
            try:
                shutil.rmtree(entry, ignore_errors=True)
            except Exception:  # noqa: BLE001
                log.warning("Failed to purge legacy staging dir %s", entry, exc_info=True)


# A pack archive may ship these top-level files and these top-level dirs.
# Anything else (executables, .pyc caches, dotfiles, ...) is rejected up
# front so a malicious zip cannot smuggle code outside the four asset
# kinds the manifest understands.
_ALLOWED_TOP_FILES: frozenset[str] = frozenset({
    "manifest.json", "README.md", "LICENSE", "LICENSE.md", "LICENSE.txt",
})
_ALLOWED_TOP_DIRS: frozenset[str] = frozenset({
    "templates", "grammars", "widgets", "icons",
})

# A safe path segment matches the existing safe-paths charset, with the
# addition of ``@`` so the (only) pack-root directory name can pass the
# guard. ``@`` is forbidden inside *interior* segments — kind ids are
# strictly ``[a-z][a-z0-9-]{0,62}`` (cf. ``storage.KIND_ID_RE``).
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")

# Cap an extracted file at 32 MiB. Packs are template-and-asset-oriented;
# real models and datasets travel out-of-band. This bound also prevents
# zip-bomb tail-end damage if the manifest validator missed something.
_MAX_FILE_BYTES: int = 32 * 1024 * 1024
# Cap the total uncompressed payload at 128 MiB to slap a ceiling on the
# zip-bomb amplification factor before we even start extracting.
_MAX_TOTAL_BYTES: int = 128 * 1024 * 1024


class InstallerError(ValueError):
    """Raised when an archive fails any structural / manifest check."""


@dataclass(frozen=True)
class InstallResult:
    manifest: PackManifest
    integrity: dict[str, str]
    replaced_existing: bool


# ---------------------------------------------------------------------------
# Path sanitisation helpers
# ---------------------------------------------------------------------------

def _safe_member_path(raw_name: str) -> tuple[str, ...]:
    """Validate a single zip member name and return its (POSIX) segments.

    Rejects:

    * Empty names, absolute paths, drive-letter prefixes.
    * Any segment equal to ``.`` or ``..``.
    * NUL bytes, control characters, non-printables.
    * Anything outside ``[A-Za-z0-9][A-Za-z0-9._-]*``.

    The check happens *before* the archive is touched on disk; together
    with the post-extract :func:`is_within` guard this makes zip-slip
    impossible.
    """
    if not isinstance(raw_name, str) or not raw_name:
        raise InstallerError("archive contains an empty member name")
    if "\x00" in raw_name:
        raise InstallerError(f"archive member contains a NUL byte: {raw_name!r}")
    # Reject Windows-style drive letters or backslashes outright.
    if "\\" in raw_name:
        raise InstallerError(
            f"archive member uses Windows-style separator: {raw_name!r}"
        )
    if raw_name.startswith("/"):
        raise InstallerError(f"archive member is absolute: {raw_name!r}")
    if ":" in raw_name:
        raise InstallerError(f"archive member contains ':': {raw_name!r}")

    parts = [p for p in raw_name.split("/") if p]
    if not parts:
        raise InstallerError(f"archive member normalises to empty: {raw_name!r}")
    for seg in parts:
        if seg in (".", ".."):
            raise InstallerError(f"archive member contains '{seg}': {raw_name!r}")
        if not _SAFE_SEGMENT_RE.match(seg):
            raise InstallerError(
                f"archive member has unsafe segment {seg!r}: {raw_name!r}"
            )
    return tuple(parts)


def _check_allowed_layout(segments: tuple[str, ...]) -> None:
    """Reject members that don't belong in any of the allowed buckets."""
    head = segments[0]
    if len(segments) == 1:
        if head not in _ALLOWED_TOP_FILES:
            raise InstallerError(
                f"archive top-level file {head!r} is not allowed; expected one of "
                f"{sorted(_ALLOWED_TOP_FILES)} or a directory in "
                f"{sorted(_ALLOWED_TOP_DIRS)}"
            )
        return
    if head not in _ALLOWED_TOP_DIRS:
        raise InstallerError(
            f"archive top-level directory {head!r} is not allowed; expected one of "
            f"{sorted(_ALLOWED_TOP_DIRS)}"
        )


# ---------------------------------------------------------------------------
# Core install
# ---------------------------------------------------------------------------

def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_integrity(pack_root: Path) -> dict[str, str]:
    """Compute SHA-256 of every regular file under *pack_root* (sorted)."""
    integrity: dict[str, str] = {}
    for entry in sorted(pack_root.rglob("*")):
        if not entry.is_file():
            continue
        if entry.name == "integrity.json":
            continue
        rel = entry.relative_to(pack_root).as_posix()
        integrity[rel] = _hash_file(entry)
    return integrity


def _touch_manifest_for_install_recency(pack_root: Path, *, mtime: float | None = None) -> None:
    """Bump ``manifest.json`` mtime so clients can expose ``installUpdatedAtMs`` (diagnostic).

    Pack ordering uses manifest ``createdAt`` / ``createdAtMs`` — not filesystem mtime.
    """

    mp = pack_root / "manifest.json"
    if not mp.is_file():
        return
    t = time.time() if mtime is None else mtime
    os.utime(mp, (t, t))


def refresh_pack_integrity(pack_root: Path) -> dict[str, str]:
    """Rewrite ``integrity.json`` after ``manifest.json`` (or asset) mutation on disk."""
    integrity = _build_integrity(pack_root)
    (pack_root / "integrity.json").write_text(
        json.dumps({"sha256": integrity}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return integrity


def _extract_into(zf: zipfile.ZipFile, target: Path) -> int:
    """Extract every member of *zf* under *target*.

    Returns the total number of bytes written. Raises :class:`InstallerError`
    when a member would escape *target* (defence in depth — every name
    has already passed :func:`_safe_member_path`) or exceeds the size
    caps.
    """
    target.mkdir(parents=True, exist_ok=True)
    written = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        segments = _safe_member_path(info.filename)
        _check_allowed_layout(segments)

        if info.file_size > _MAX_FILE_BYTES:
            raise InstallerError(
                f"archive member {info.filename!r} exceeds per-file limit "
                f"({info.file_size} > {_MAX_FILE_BYTES} bytes)"
            )
        written += info.file_size
        if written > _MAX_TOTAL_BYTES:
            raise InstallerError(
                f"archive total uncompressed size exceeds "
                f"{_MAX_TOTAL_BYTES} bytes"
            )

        dest = target.joinpath(*segments)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not is_within(dest, target):
            # Should be impossible after _safe_member_path, but the
            # containment check is the always-on backstop from
            # ``utk_curio.backend.app.common.safe_paths``.
            raise PathTraversalError(
                f"Path traversal blocked: archive member {dest!s} "
                f"escapes target {target!s}"
            )
        with zf.open(info, "r") as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out, length=1024 * 1024)
    return written


def publish_pack_archive_to_catalog_dir(
    archive: bytes | IO[bytes],
    catalog_parent: Path,
    *,
    replace: bool = False,
) -> InstallResult:
    """Extract and validate an archive directly under *catalog_parent*.

    Typical *catalog_parent* is ``<repo_root>/packs/`` — the committed
    catalog source used by ``GET /api/packs/catalog``. This must stay **off**
    unless the Flask route confirms an administrator opt-in env flag; writing
    there can trigger backend reload watchers in development.

    Layout and safety rules mirror :func:`install_pack_from_archive`, but the
    final directory is ``catalog_parent / <manifest.dir_name>/`` instead of the
    per-user pack tree. Uses :func:`shutil.move` so staging may live on a
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
                manifest = load_pack_manifest_from_dir(staging_root)
            except ManifestError as exc:
                raise InstallerError(str(exc)) from exc

            dir_name = manifest.dir_name
            if not PACK_DIR_RE.match(dir_name):
                raise InstallerError(
                    f"manifest derives malformed pack dir name {dir_name!r}"
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
                        f"pack {dir_name} already exists under catalog; "
                        "pass replace=True to overwrite the fixture directory"
                    )
                shutil.rmtree(final_dest)
                replaced_existing = True

            shutil.move(str(staging_root), str(final_dest))
            staging_alive = None

            loaded = load_pack_manifest(final_dest)
            log.info(
                "Published pack fixture %s to catalog dir %s (replace=%s)",
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


def remove_pack_from_catalog_dir(catalog_parent: Path, dir_name: str) -> bool:
    """Remove a committed catalog fixture directory under *catalog_parent*.

    Returns ``True`` when a directory was removed, ``False`` when absent.
    """
    if not PACK_DIR_RE.match(dir_name):
        raise InstallerError(f"malformed pack dir name {dir_name!r}")

    catalog_root = catalog_parent.resolve(strict=False)
    final_dest = (catalog_root / dir_name).resolve()
    if not is_within(final_dest, catalog_root):
        raise InstallerError(f"refusing to remove outside catalog root ({final_dest})")
    if not final_dest.is_dir():
        return False
    shutil.rmtree(final_dest)
    log.info("Removed pack fixture %s from catalog dir %s", dir_name, final_dest)
    return True


def install_pack_from_archive(
    user_key: str,
    archive: bytes | IO[bytes],
    *,
    replace: bool = False,
) -> InstallResult:
    """Install (or replace) a ``.curio-nodepack`` archive for *user_key*.

    Steps:

    1. Open the bytes as a ZipFile (memory-only, no disk roundtrip).
    2. Extract everything into a tmp dir under the per-user pack store
       — never the final destination. This means a half-broken archive
       can't leave a corrupted pack on disk.
    3. Load + validate the manifest from the tmp dir.
    4. Cross-check the manifest's ``<packId>@<major>`` against the
       final destination directory name; refuse if a pack at that
       coordinate is already installed unless ``replace=True``.
    5. Compute SHA-256 integrity of every shipped file and write
       ``integrity.json`` inside the pack root.
    6. Atomically move the tmp dir to the final destination.

    Parameters
    ----------
    user_key:
        Either ``"guest"`` or a numeric user id (validated by the
        storage layer's :func:`user_packs_dir`).
    archive:
        The raw zip bytes, or an open binary stream. The stream is
        rewound to 0 before reading.
    replace:
        When ``True``, an existing ``<packId>@<major>`` directory for
        *user_key* is removed first. Default ``False`` — repeat installs
        of the same coordinate raise.

    Returns
    -------
    InstallResult
        ``manifest`` (the validated :class:`PackManifest`),
        ``integrity`` (the ``{relative_path: sha256_hex}`` map), and
        ``replaced_existing`` (whether *replace* actually displaced an
        existing pack).

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
        # Stage extraction in a tmp dir **outside** the user's pack
        # store. Writing ``.py`` templates into ``<user>/packs/`` would
        # trigger Werkzeug's watchdog reloader mid-install and kill the
        # response before the atomic move completes (which is exactly
        # the "Failed to fetch" install bug this layout fixes). The
        # sibling ``.pack-staging/`` directory is on the same
        # filesystem so :func:`os.replace` still moves atomically.
        user_packs_dir(user_key).mkdir(parents=True, exist_ok=True)
        staging_base = user_pack_staging_dir(user_key)
        staging_base.mkdir(parents=True, exist_ok=True)
        # Best-effort sweep of any orphaned staging dirs from a previous
        # crashed install. ``tempfile.mkdtemp`` does not clean up after
        # a SIGKILL / power loss, and the orphans accumulate every cycle.
        _purge_stale_staging(user_key)
        staging_root = Path(
            tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=str(staging_base))
        )
        try:
            _extract_into(zf, staging_root)
            try:
                manifest = load_pack_manifest_from_dir(staging_root)
            except ManifestError as exc:
                raise InstallerError(str(exc)) from exc

            dir_name = manifest.dir_name
            if not PACK_DIR_RE.match(dir_name):
                raise InstallerError(
                    f"manifest derives malformed pack dir name {dir_name!r}"
                )

            final_dest = pack_dir(user_key, dir_name)
            replaced = False
            if final_dest.exists():
                if not replace:
                    raise InstallerError(
                        f"pack {dir_name} already installed; pass replace=True "
                        f"to overwrite"
                    )
                shutil.rmtree(final_dest)
                replaced = True

            merge_missing_manifest_created_at(staging_root)
            integrity = _build_integrity(staging_root)
            (staging_root / "integrity.json").write_text(
                json.dumps({"sha256": integrity}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            staging_root.replace(final_dest)
            _touch_manifest_for_install_recency(final_dest)
            merged_manifest = load_pack_manifest(final_dest)
            # An explicit (re)install supersedes any prior uninstall
            # tombstone the dev seeder might otherwise honour — the user
            # just asked for this pack to be present, so its seed-state
            # record gets refreshed below by mark_seeded only if the
            # caller is the seeder; here we just clear the tombstone so
            # subsequent restarts don't blow up the manifest cross-check.
            try:
                from utk_curio.backend.app.packs import seed_state  # local: no cycle
                seed_state.clear(user_key, dir_name)
            except Exception:  # noqa: BLE001 — bookkeeping is best-effort
                log.exception("Failed to clear uninstall tombstone for %s/%s", user_key, dir_name)

            try:
                from utk_curio.backend.app.packs.palette_dock_manifest import (
                    resync_fork_palette_parent_flags,
                )

                resync_fork_palette_parent_flags(user_key)
            except Exception:  # noqa: BLE001
                log.exception(
                    "Failed to sync fork-parent palette dock flags after install %s/%s",
                    user_key,
                    dir_name,
                )

            return InstallResult(
                manifest=merged_manifest,
                integrity=integrity,
                replaced_existing=replaced,
            )
        except Exception:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise


def load_pack_manifest_from_dir(pack_root: Path) -> PackManifest:
    """Load + validate a manifest from a staging dir.

    The on-disk validator in :func:`load_pack_manifest` cross-checks the
    dir name against the manifest's ``<packId>@<major>``. The installer
    extracts into a temporary directory whose name is arbitrary, so we
    materialise a **side** dir with the correct name in a dedicated
    tmp parent — *never* under the per-user pack base — load from
    there, and tear it down. This avoids any chance of clobbering a
    live pack at the target coordinate during validation.
    """
    manifest_path = pack_root / "manifest.json"
    if not manifest_path.is_file():
        raise InstallerError("archive is missing manifest.json")
    try:
        meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstallerError(f"manifest.json is not valid JSON: {exc}") from exc
    pack_id = meta.get("id")
    compat = meta.get("compatibility") or {}
    major = compat.get("major")
    if not isinstance(pack_id, str) or not isinstance(major, int):
        raise InstallerError(
            "manifest.json must declare a string 'id' and integer "
            "'compatibility.major'"
        )
    expected = f"{pack_id}@{major}"
    if not PACK_DIR_RE.match(expected):
        raise InstallerError(
            f"manifest yields malformed pack dir name {expected!r}"
        )

    side_parent = Path(tempfile.mkdtemp(prefix=".validate-"))
    try:
        validate_root = side_parent / expected
        shutil.copytree(pack_root, validate_root)
        return load_pack_manifest(validate_root)
    finally:
        shutil.rmtree(side_parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# Uninstall + export
# ---------------------------------------------------------------------------

def uninstall_pack(user_key: str, dir_name: str) -> bool:
    """Remove ``<user>/packs/<dir_name>``. Returns ``True`` if anything was deleted.

    Also drops a tombstone in the per-user seed-state file so the dev
    seeder (see :mod:`.seed`) does not resurrect this pack on the next
    backend hot-reload — that "uninstall isn't sticky" bug is the
    regression this side-effect exists to prevent.
    """
    target = pack_dir(user_key, dir_name)
    if not target.exists():
        return False
    shutil.rmtree(target)
    try:
        from utk_curio.backend.app.packs import seed_state  # local import: no cycle
        seed_state.mark_uninstalled(user_key, dir_name)
    except Exception:  # noqa: BLE001 — never block uninstall on bookkeeping
        log.exception("Failed to record uninstall tombstone for %s/%s", user_key, dir_name)
    try:
        from utk_curio.backend.app.packs.palette_dock_manifest import (
            resync_fork_palette_parent_flags,
        )

        resync_fork_palette_parent_flags(user_key)
    except Exception:  # noqa: BLE001
        log.exception(
            "Failed to sync fork-parent palette dock flags after uninstall %s/%s",
            user_key,
            dir_name,
        )
    return True


def install_pack_from_directory(
    user_key: str,
    source_dir: Path,
    *,
    replace: bool = False,
) -> InstallResult:
    """Install a pack from a directory on disk (committed catalog entry).

    ``POST /api/packs/catalog/install`` copies from
    ``<repo_root>/packs/<packId>@<major>/`` into the user's pack
    store by re-zipping and reusing :func:`install_pack_from_archive` — same
    validation and integrity hashing as sideload. No separate download
    service is required until a hosted registry exists.

    The implementation funnels through :func:`install_pack_from_archive`
    so the manifest validator, size caps, and integrity-hash writer are
    all the same code path the sideload uses.
    """
    if not source_dir.is_dir():
        raise InstallerError(f"catalog source {source_dir} is not a directory")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(source_dir.rglob("*")):
            if not entry.is_file():
                continue
            if entry.name == "integrity.json":
                continue
            rel = entry.relative_to(source_dir).as_posix()
            zf.write(entry, arcname=rel)
    return install_pack_from_archive(user_key, buf.getvalue(), replace=replace)


def export_pack_archive(user_key: str, dir_name: str) -> bytes:
    """Repackage an installed pack back into a deterministic ``.curio-nodepack`` zip.

    Useful for the factory ("Export pack" button) and for migrating an
    installed pack from one user to another. The archive layout matches
    the one :func:`install_pack_from_archive` accepts, so a round-trip
    install -> export -> install is lossless.
    """
    target = pack_dir(user_key, dir_name)
    if not target.is_dir():
        raise InstallerError(f"pack {dir_name} is not installed")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(target.rglob("*")):
            if not entry.is_file():
                continue
            if entry.name == "integrity.json":
                continue
            rel = entry.relative_to(target).as_posix()
            zf.write(entry, arcname=rel)
    return buf.getvalue()
