"""The ``.curio.zip`` archive format: member-name safety, the allowed layout, size caps, extraction, integrity hashing, the staging-dir validation of the manifest and the skills, and the deterministic re-zip.

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
from pathlib import Path, PurePosixPath

from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.common import safe_archive
from utk_curio.backend.app.common.safe_paths import (
    is_within,
    PathTraversalError,
)
from utk_curio.backend.app.packages.domain.manifest import PackageManifest
from utk_curio.backend.app.packages.domain.model_block import MODELS_DIR
from utk_curio.backend.app.packages.domain.package_id import PACKAGE_DIR_RE
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.publisher_record import RECORD_FILENAME
from utk_curio.backend.app.packages.repositories.skills import SKILLS_DIR


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
    # "skills": what the package tells Curio's agents, one folder per skill
    # (repositories/skills.py); text an agent reads, never run.
    "sources", "starters", "grammars", "widgets", "icons", "scripts", "backend", SKILLS_DIR,
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


# A model package (kind ``model``) ships its weights under ``models/``, and a
# file of it may reach 2 GiB; the whole package may hold that plus a node
# package's budget for everything else (``_model_caps``, read at call time so
# a patched cap bites).
_MAX_MODEL_FILE_BYTES: int = 2 * 1024 * 1024 * 1024


# The most bytes of ``manifest.json`` read to learn an archive's kind before
# anything is extracted.
_MAX_MANIFEST_BYTES: int = 1024 * 1024


def _model_caps() -> tuple[int, int]:
    """``(per-file, total)`` caps of a model package's archive."""
    return _MAX_MODEL_FILE_BYTES, _MAX_MODEL_FILE_BYTES + _MAX_TOTAL_BYTES


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


def _check_allowed_layout(segments: tuple[str, ...], *, kind: str = "node") -> None:
    """Reject members that don't belong in any of the allowed buckets.
    ``models/`` is a bucket of a model package (*kind* ``model``) only."""
    head = segments[0]
    if len(segments) == 1:
        if head not in _ALLOWED_TOP_FILES:
            raise InstallerError(
                f"archive top-level file {head!r} is not allowed; expected one of "
                f"{sorted(_ALLOWED_TOP_FILES)} or a directory in "
                f"{sorted(_ALLOWED_TOP_DIRS)}"
            )
        return
    if head == MODELS_DIR:
        if kind != "model":
            raise InstallerError(
                f"archive top-level directory {MODELS_DIR!r} is not allowed in a node package: "
                f"only a model package (manifest kind 'model') ships weights under {MODELS_DIR}/"
            )
        return
    if head not in _ALLOWED_TOP_DIRS:
        raise InstallerError(
            f"archive top-level directory {head!r} is not allowed; expected one of "
            f"{sorted(_ALLOWED_TOP_DIRS)}, or {MODELS_DIR!r} in a model package"
        )


def archive_kind(zf: zipfile.ZipFile) -> str:
    """The kind an archive's ``manifest.json`` declares, read before anything
    is extracted: ``model``, or ``node`` for anything else (no manifest, one
    too big to read here, invalid JSON), which the manifest's own validation
    then refuses after extraction with its own message."""
    try:
        info = zf.getinfo("manifest.json")
    except KeyError:
        return "node"
    if info.file_size > _MAX_MANIFEST_BYTES:
        return "node"
    try:
        with zf.open(info, "r") as handle:
            raw = json.loads(handle.read(_MAX_MANIFEST_BYTES + 1).decode("utf-8"))
    except (ValueError, OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile):
        return "node"
    return "model" if isinstance(raw, dict) and raw.get("kind") == "model" else "node"


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
    that re-zips a catalog directory (catalog install, the drawer install, the
    workflow-deps auto-install, export) would then refuse the package until
    someone republished it.
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


def is_weight_path(rel: str) -> bool:
    """Whether *rel*, a package-relative path, is under a model package's ``models/``."""
    return rel.split("/", 1)[0] == MODELS_DIR


def without_weights(integrity: dict[str, str]) -> dict[str, str]:
    """*integrity* without the files under ``models/``: what a user's copy of a
    shipped model package holds, whose weights are read where they ship."""
    return {rel: digest for rel, digest in integrity.items() if not is_weight_path(rel)}


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


def integrity_mismatch(package_root: Path) -> str | None:
    """Why the files of the package at *package_root* are not the ones the
    record its install wrote names (``integrity.json``, rewritten by each of
    Curio's own changes to the package), or None when they are: a file the
    record names that is gone or changed, or one it does not name. A package
    with no record that reads has nothing to be checked against, which is a
    reason too."""
    try:
        raw = json.loads((package_root / "integrity.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = None
    listed = raw.get("sha256") if isinstance(raw, dict) else None
    if not isinstance(listed, dict) or not listed:
        return "it has no record of its files (integrity.json) to check them against"
    actual = _build_integrity(package_root)
    for rel in sorted(listed):
        if rel not in actual:
            return f"its file {rel} is gone since it was installed"
        if actual[rel] != listed[rel]:
            return f"its file {rel} changed since it was installed"
    added = sorted(set(actual) - set(listed))
    if added:
        return f"its file {added[0]} was added since it was installed"
    return None


def _extract_into(zf: zipfile.ZipFile, target: Path) -> int:
    """Extract every member of *zf* under *target*.

    Returns the total number of bytes written. Raises :class:`InstallerError`
    when a member would escape *target* (defence in depth — every name
    has already passed :func:`_safe_member_path`) or exceeds the size
    caps: first by the sizes the archive declares, then by the bytes
    actually written, which :func:`safe_archive.copy_member` counts.

    The caps and the allowed folders are the archive's kind's
    (:func:`archive_kind`): a model package may ship ``models/`` and files up
    to :data:`_MAX_MODEL_FILE_BYTES`.
    """
    target.mkdir(parents=True, exist_ok=True)
    kind = archive_kind(zf)
    # Read at call time, so a cap patched on this module still bites.
    max_file, max_total = _model_caps() if kind == "model" else (_MAX_FILE_BYTES, _MAX_TOTAL_BYTES)
    budget = safe_archive.Budget(
        safe_archive.Caps(max_member_bytes=max_file, max_total_bytes=max_total)
    )
    written = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        segments = _safe_member_path(info.filename)
        _check_allowed_layout(segments, kind=kind)

        if info.file_size > max_file:
            raise InstallerError(
                f"archive member {info.filename!r} exceeds per-file limit "
                f"({info.file_size} > {max_file} bytes)"
            )
        written += info.file_size
        if written > max_total:
            raise InstallerError(
                f"archive total uncompressed size exceeds "
                f"{max_total} bytes"
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
    """Load + validate a manifest from a staging dir, then the package's
    skills (:func:`refuse_unreadable_skills`).

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
    #
    # Only the manifest is copied: the validator reads nothing else, and a model
    # package's weights may run to gigabytes.
    side_parent = Path(
        tempfile.mkdtemp(prefix=".validate-", dir=str(package_root.parent))
    )
    try:
        validate_root = side_parent / expected
        validate_root.mkdir()
        shutil.copyfile(manifest_path, validate_root / "manifest.json")
        manifest = load_package_manifest(validate_root)
    finally:
        shutil.rmtree(side_parent, ignore_errors=True)
    refuse_unreadable_skills(package_root)
    return manifest


def refuse_unreadable_skills(package_root: Path) -> None:
    """Refuse a package whose ``skills/`` breaks the Agent Skills format,
    checked as strictly as the skills Curio ships: ``skills/`` holds one
    folder per skill, each with a ``SKILL.md`` the strict reader takes
    (``agents/domain/skills.py``). Raises :class:`InstallerError` naming
    every problem; a package with no ``skills/`` has none."""
    root = Path(package_root) / SKILLS_DIR
    if not root.exists() and not root.is_symlink():
        return
    if root.is_symlink() or not root.is_dir():
        raise InstallerError(f"{SKILLS_DIR} is not a folder: a package's {SKILLS_DIR}/ holds one folder per skill")
    problems: list[str] = []
    for entry in sorted(root.iterdir()):
        if entry.name.startswith("."):
            continue
        where = f"{SKILLS_DIR}/{entry.name}"
        skill_file = entry / skill_format.SKILL_FILE
        if entry.is_symlink() or not entry.is_dir():
            problems.append(f"{where} is no skill's folder: {SKILLS_DIR}/ holds one folder per skill, "
                            f"each with its {skill_format.SKILL_FILE}")
        elif skill_file.is_symlink() or not skill_file.is_file():
            problems.append(f"{where} holds no {skill_format.SKILL_FILE}")
        else:
            try:
                skill_format.parse(entry)
            except skill_format.SkillError as exc:
                problems.append(f"{SKILLS_DIR}/{exc}")
            except UnicodeDecodeError:
                problems.append(f"{where}/{skill_format.SKILL_FILE} is not UTF-8 text")
    if problems:
        raise InstallerError(
            "the package's skills break the Agent Skills format (https://agentskills.io/specification): "
            + "; ".join(problems)
        )


def _package_members(
    source_dir: Path, *, leave_out_weights: bool = False, weights_dir: Path | None = None,
) -> list[tuple[str, Path]]:
    """``(member name, file)`` for every file an archive of *source_dir* holds,
    sorted by name: its content, bookkeeping left out
    (:func:`is_non_content_filename`). *leave_out_weights* leaves out
    ``models/``; *weights_dir*, a folder holding the package's ``models/``,
    gives the weights instead of *source_dir*'s own."""
    members: dict[str, Path] = {}
    for entry in sorted(source_dir.rglob("*")):
        if not entry.is_file() or is_non_content_filename(entry.name):
            continue
        rel = entry.relative_to(source_dir).as_posix()
        if (leave_out_weights or weights_dir is not None) and is_weight_path(rel):
            continue
        members[rel] = entry
    if weights_dir is not None and not leave_out_weights:
        for entry in sorted((weights_dir / MODELS_DIR).rglob("*")):
            if entry.is_file() and not entry.is_symlink() and not is_non_content_filename(entry.name):
                members[entry.relative_to(weights_dir).as_posix()] = entry
    # In path order, as the walk itself sorts.
    return sorted(members.items(), key=lambda member: PurePosixPath(member[0]))


def _write_package_zip(sink, members: list[tuple[str, Path]]) -> None:
    with zipfile.ZipFile(sink, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, entry in members:
            zf.write(entry, arcname=name)


def zip_package_tree_to(
    source_dir: Path, target: Path, *, leave_out_weights: bool = False, weights_dir: Path | None = None,
) -> Path:
    """Write the deterministic ``.curio.zip`` of *source_dir* to *target*, file by
    file, so a model package's weights stream through disk and never sit in
    memory. The same members as :func:`zip_package_tree`; *leave_out_weights*
    and *weights_dir* are :func:`_package_members`'. Returns *target*."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    members = _package_members(source_dir, leave_out_weights=leave_out_weights, weights_dir=weights_dir)
    try:
        with open(target, "wb") as sink:
            _write_package_zip(sink, members)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


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
    apart in what they emit. Those routes write it to disk with
    :func:`zip_package_tree_to`, the same members through the same writer.
    """
    buf = io.BytesIO()
    _write_package_zip(buf, _package_members(source_dir))
    return buf.getvalue()
