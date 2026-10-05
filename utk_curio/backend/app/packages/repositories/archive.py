"""The ``.curio.zip`` archive format: member-name safety, the allowed layout, size caps, extraction, integrity hashing, the staging-dir manifest validation, and the deterministic re-zip.

Repositories layer of the packages package (memo dev/143, B2): cut from ``installer.py``
by responsibility; every function keeps its name and body.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from utk_curio.backend.app.common import safe_archive
from utk_curio.backend.app.common.safe_paths import (
    is_within,
    PathTraversalError,
)
from utk_curio.backend.app.packages.domain.manifest import PackageManifest
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.publisher_record import RECORD_FILENAME


# A package archive may ship these top-level files and these top-level dirs.
# Anything else (executables, .pyc caches, dotfiles, ...) is rejected up
# front so a malicious zip cannot smuggle code outside the four asset
# kinds the manifest understands.
_ALLOWED_TOP_FILES: frozenset[str] = frozenset({
    "manifest.json", "README.md", "LICENSE", "LICENSE.md", "LICENSE.txt",
})


_ALLOWED_TOP_DIRS: frozenset[str] = frozenset({
    # "backend" (memo dev/91): the package's declared server-side entry —
    # inert on disk like sources/; executed ONLY by the backend sandbox.
    "sources", "starters", "grammars", "widgets", "icons", "scripts", "backend",
})


# A safe path segment matches the existing safe-paths charset, with the
# addition of ``@`` so the (only) package-root directory name can pass the
# guard. ``@`` is forbidden inside *interior* segments — kind ids are
# strictly ``[a-z][a-z0-9-]{0,62}`` (cf. ``storage.TEMPLATE_ID_RE``).
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")

# The one file name a member may have that starts with an underscore: a folder
# of Python modules in ``sources/`` is a regular package when it holds one
# (#468). ``__pycache__`` and every other leading underscore stay refused.
_PYTHON_PACKAGE_FILE = "__init__.py"


# Cap an extracted file at 32 MiB. Packages are template-and-asset-oriented;
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
    manifest: PackageManifest
    integrity: dict[str, str]
    replaced_existing: bool


def _safe_member_path(raw_name: str) -> tuple[str, ...]:
    """Validate a single zip member name and return its (POSIX) segments.

    Rejects:

    * Empty names, absolute paths, drive-letter prefixes.
    * Any segment equal to ``.`` or ``..``.
    * NUL bytes, control characters, non-printables.
    * Anything outside ``[A-Za-z0-9][A-Za-z0-9._-]*``, except a file named
      ``__init__.py``.

    The check happens *before* the archive is touched on disk; together
    with the post-extract :func:`is_within` guard this makes zip-slip
    impossible. The traversal rules are the shared ones
    (:func:`safe_archive.member_segments`); the charset is the package's own.
    """
    try:
        parts = safe_archive.member_segments(raw_name)
    except safe_archive.ArchiveRefused as exc:
        raise InstallerError(str(exc)) from exc
    for index, seg in enumerate(parts):
        if seg == _PYTHON_PACKAGE_FILE and index == len(parts) - 1:
            continue
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


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def non_content_filenames() -> frozenset[str]:
    """Files that live inside a package directory and are NOT the package.

    ``integrity.json`` is the installer's record of what it copied;
    ``.curio-publisher.json`` is the catalog's record of who published it.
    Both are bookkeeping written beside the package, and every rule about
    package CONTENT has to agree on excluding them or they disagree with each
    other. They did: the archive writer dropped the publisher record while the
    integrity hasher kept it, so a published package's catalog digest could
    never match the map written for a copy installed from it, the seeder read
    that as "the catalog has moved on", and every seed pass re-copied the
    package and carried one user's key into another user's store.
    """

    return frozenset({"integrity.json", RECORD_FILENAME})


def is_non_content_filename(name: str) -> bool:
    """Should *name* be left out of an archive built from a package directory?

    The named files above, plus ANY dotfile. The dotfile rule is provably
    lossless: ``_safe_member_path`` rejects every member whose segment starts
    with a dot, so a dotfile could never have been installed from an archive
    anyway - zipping one only turns an install into "archive member has unsafe
    segment" for the whole package.

    That is not hypothetical. ``record_publisher`` writes its record through a
    ``.curio-publisher.json.tmp`` and swallows an ``os.replace`` failure as a
    warning, so a full disk or a Windows sharing violation can leave the .tmp
    beside the package. The exact-name rule did not cover it, and every route
    that re-zips a catalog directory - catalog install, the drawer install,
    "Reload from catalog", the workflow-deps auto-install, export - would then
    refuse the package until someone republished it.
    """
    return name in non_content_filenames() or name.startswith(".")


def _build_integrity(package_root: Path) -> dict[str, str]:
    """Compute SHA-256 of every regular file under *package_root* (sorted)."""
    integrity: dict[str, str] = {}
    for entry in sorted(package_root.rglob("*")):
        if not entry.is_file():
            continue
        if is_non_content_filename(entry.name):
            continue
        rel = entry.relative_to(package_root).as_posix()
        integrity[rel] = _hash_file(entry)
    return integrity


def _touch_manifest_for_install_recency(package_root: Path, *, mtime: float | None = None) -> None:
    """Bump ``manifest.json`` mtime so clients can expose ``installUpdatedAtMs`` (diagnostic).

    Package ordering uses manifest ``createdAt`` / ``createdAtMs`` — not filesystem mtime.
    """

    mp = package_root / "manifest.json"
    if not mp.is_file():
        return
    t = time.time() if mtime is None else mtime
    os.utime(mp, (t, t))


def refresh_package_integrity(package_root: Path) -> dict[str, str]:
    """Rewrite ``integrity.json`` after ``manifest.json`` (or asset) mutation on disk."""
    integrity = _build_integrity(package_root)
    (package_root / "integrity.json").write_text(
        json.dumps({"sha256": integrity}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return integrity


def _extract_into(zf: zipfile.ZipFile, target: Path) -> int:
    """Extract every member of *zf* under *target*.

    Returns the total number of bytes written. Raises :class:`InstallerError`
    when a member would escape *target* (defence in depth — every name
    has already passed :func:`_safe_member_path`) or exceeds the size
    caps: first by the sizes the archive declares, then by the bytes
    actually written, which :func:`safe_archive.copy_member` counts.
    """
    target.mkdir(parents=True, exist_ok=True)
    # Read at call time, so a cap patched on this module still bites.
    budget = safe_archive.Budget(
        safe_archive.Caps(max_member_bytes=_MAX_FILE_BYTES, max_total_bytes=_MAX_TOTAL_BYTES)
    )
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
        try:
            safe_archive.copy_member(zf, info, dest, budget)
        except safe_archive.ArchiveRefused as exc:
            raise InstallerError(str(exc)) from exc
    return written


def load_package_manifest_from_dir(package_root: Path) -> PackageManifest:
    """Load + validate a manifest from a staging dir.

    The on-disk validator in :func:`load_package_manifest` cross-checks the
    dir name against the manifest's ``<packageId>@<major>``. The installer
    extracts into a temporary directory whose name is arbitrary, so we
    materialise a **side** dir with the correct name in a dedicated
    tmp parent — *never* under the per-user package base — load from
    there, and tear it down. This avoids any chance of clobbering a
    live package at the target coordinate during validation.
    """
    manifest_path = package_root / "manifest.json"
    if not manifest_path.is_file():
        raise InstallerError("archive is missing manifest.json")
    try:
        meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstallerError(f"manifest.json is not valid JSON: {exc}") from exc
    package_id = meta.get("id")
    compat = meta.get("compatibility") or {}
    major = compat.get("major")
    if not isinstance(package_id, str) or not isinstance(major, int):
        raise InstallerError(
            "manifest.json must declare a string 'id' and integer "
            "'compatibility.major'"
        )
    expected = f"{package_id}@{major}"
    if not PACKAGE_DIR_RE.match(expected):
        raise InstallerError(
            f"manifest yields malformed package dir name {expected!r}"
        )

    # Sibling of the tree being validated, not the system temp dir. Same
    # filesystem (so the copy is local and cheap), and out of reach of the
    # OS temp cleaners and scanners that were intermittently deleting
    # ``%TEMP%/.validate-*`` mid-copy - surfacing as a shutil.Error with
    # ``WinError 3`` on every destination path at once. The ".validate-" prefix
    # is deliberately not ``_STAGING_PREFIX``, so ``_purge_stale_staging``
    # leaves it alone.
    side_parent = Path(
        tempfile.mkdtemp(prefix=".validate-", dir=str(package_root.parent))
    )
    try:
        validate_root = side_parent / expected
        shutil.copytree(package_root, validate_root)
        return load_package_manifest(validate_root)
    finally:
        shutil.rmtree(side_parent, ignore_errors=True)


def zip_package_tree(source_dir: Path) -> bytes:
    """A deterministic ``.curio.zip`` of one package directory.

    Sorted walk, deflate, and the two files that are BOOKKEEPING rather than
    package content left out:

    * ``integrity.json`` — the installer's own record of what it copied,
      rewritten on every install, so an archive must not carry one.
    * ``.curio-publisher.json`` — the catalog's record of who published the
      package. It made a catalog entry uninstallable: the member validator
      rejects a leading dot, so ``publish-catalog`` produced a directory that
      ``catalog/install`` then refused with "archive member has unsafe
      segment", and every route that reaches a catalog copy — the drawer's
      install, "Reload from catalog", the workflow-deps auto-install — failed
      on anything published through the product's own route. Leaving it out
      also keeps one user's ``userKey`` out of every archive the export routes
      hand to somebody else.

    Shared by the catalog install (which re-zips a catalog directory to reuse
    the sideload validator) and the export routes, so the two cannot drift
    apart in what they emit.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(source_dir.rglob("*")):
            if not entry.is_file():
                continue
            if is_non_content_filename(entry.name):
                continue
            rel = entry.relative_to(source_dir).as_posix()
            zf.write(entry, arcname=rel)
    return buf.getvalue()
