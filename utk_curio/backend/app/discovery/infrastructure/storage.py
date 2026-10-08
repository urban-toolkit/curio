"""Where source manifests live on disk, and how they are found.

Transcribes ``datasets/infrastructure/storage.py``'s shape so the two catalog
roots are configured and resolved the same way. Like that one, the roots are
never created eagerly: a deployment with no sources should have no empty
directory suggesting otherwise.

Two roots are read:

- the **shipped** catalog, ``<repo>/discovery`` (``CURIO_DISCOVERY_ROOT`` moves
  it), which comes with Curio;
- the **instance** directory, ``.curio/discovery/``, where an operator adds
  their own sources without rebuilding an image. It persists wherever
  ``.curio`` does. No HTTP route writes to it.

A source id is unique across both. A shipped source wins, and an instance
manifest reusing its id is skipped.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from utk_curio import shipped
from utk_curio.backend.app.common.safe_paths import is_within
from utk_curio.backend.app.discovery.domain.errors import StorageUnavailable
from utk_curio.backend.app.discovery.domain.source_id import SOURCE_DIR_RE, SourceId

logger = logging.getLogger(__name__)

ENV_ROOT = "CURIO_DISCOVERY_ROOT"

SHIPPED = "shipped"
INSTANCE = "instance"


class StorageRootError(StorageUnavailable):
    """A folder source's root that cannot be used.

    The message is shown to users, so it never names the folder; ``path`` is
    for the operator's log.
    """

    def __init__(self, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


def discovery_root() -> Path:
    """The shipped catalog root: ``discovery/`` (``utk_curio/shipped.py``)
    unless overridden."""
    override = os.environ.get(ENV_ROOT)
    if override and override.strip():
        return Path(override).expanduser().resolve()
    return shipped.path("discovery")


def instance_root() -> Path:
    """``.curio/discovery/``: the operator's own sources."""
    from utk_curio.backend.app.common.user_storage import curio_root

    return curio_root() / "discovery"


def _scan(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not SOURCE_DIR_RE.match(entry.name):
            continue
        if not (entry / "manifest.json").is_file():
            continue
        found.append(entry)
    return found


#: Sources already reported as skipped, by path and manifest time, so a
#: listing that runs on every request says so once per edit.
_reported: set[tuple[str, int]] = set()
_reported_lock = threading.Lock()


def report_skipped(path: Path, reason: str) -> None:
    """Log, once per edit of its manifest, that the source at *path* is not listed."""
    try:
        stamp = (Path(path) / "manifest.json").stat().st_mtime_ns
    except OSError:
        stamp = 0
    key = (str(path), stamp)
    with _reported_lock:
        if key in _reported:
            return
        _reported.add(key)
    logger.warning("Discovery Catalog source %s is not listed: %s", path, reason)


def list_discovery_sources() -> list[Path]:
    """Every well-formed source directory, shipped first, sorted within each.

    A directory whose name does not parse, or which carries no manifest, is
    skipped rather than raised on - one malformed folder must not take the
    whole catalog listing down with it.
    """
    shipped = _scan(discovery_root())
    names = {path.name for path in shipped}
    out = list(shipped)
    for path in _scan(instance_root()):
        if path.name in names:
            report_skipped(path, "a shipped source has the same id")
            continue
        out.append(path)
    return out


def origin_of(path: Path) -> str:
    """``shipped`` or ``instance``: which root *path* was found under."""
    try:
        if is_within(Path(path), instance_root().resolve()):
            return INSTANCE
    except OSError:
        pass
    return SHIPPED


def source_dir(dir_name: str) -> Path:
    """Resolve one source directory, refusing anything outside the roots.

    ``SourceId.parse_dir`` already rejects separators and traversal, so the
    containment check is belt-and-braces - but it is the check that stays
    correct if the id grammar is ever loosened. The shipped root is asked
    first, matching :func:`list_discovery_sources`.
    """
    SourceId.parse_dir(dir_name)
    candidates = []
    for root in (discovery_root(), instance_root()):
        candidate = (root / dir_name).resolve()
        if not is_within(candidate, root.resolve()):
            raise ValueError(f"{dir_name!r} resolves outside the Discovery Catalog root")
        candidates.append(candidate)
    for candidate in candidates:
        if (candidate / "manifest.json").is_file():
            return candidate
    return candidates[0]


def storage_root(manifest) -> Path:
    """A ``folder`` source's root, resolved and checked.

    An absolute root is used as written. A relative one is only honoured for a
    shipped manifest: it is a repository path, found through
    ``utk_curio/shipped.py``, so the example sources travel with a checkout
    and a pip install. An instance manifest must name an absolute path, which
    is what an operator mounting a folder writes anyway.
    """
    raw = manifest.provider.root
    if not raw:
        raise StorageRootError(f"{manifest.name} declares no folder")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        if getattr(manifest, "origin", SHIPPED) != SHIPPED:
            raise StorageRootError(
                f"{manifest.name}: an instance source's root must be an absolute path"
            )
        try:
            path = shipped.path(path.as_posix())
        except ValueError:
            raise StorageRootError(
                f"{manifest.name}: its folder is not available on this machine", path=str(raw)
            ) from None
    resolved = path.resolve()
    if not resolved.is_dir():
        raise StorageRootError(
            f"{manifest.name}: its folder is not available on this machine", path=str(raw)
        )
    return resolved


def unreadable_part(path: Path, uid: int, gids: set[int]) -> Path | None:
    """What stops *uid* reading *path*: itself, or a folder on the way to it.

    None when nothing does. From the mode bits, since ``os.access`` answers
    for this process's user and the backend runs as root.
    """
    import stat as stat_module

    def allows(st, owner_bit: int, group_bit: int, other_bit: int) -> bool:
        if st.st_uid == uid:
            return bool(st.st_mode & owner_bit)
        if st.st_gid in gids:
            return bool(st.st_mode & group_bit)
        return bool(st.st_mode & other_bit)

    target = Path(path).resolve()
    try:
        # Outermost first, so the answer is the first folder that stops the way.
        for parent in reversed(list(target.parents)):
            if not allows(parent.stat(), stat_module.S_IXUSR, stat_module.S_IXGRP, stat_module.S_IXOTH):
                return parent
        st = target.stat()
        if not allows(st, stat_module.S_IRUSR, stat_module.S_IRGRP, stat_module.S_IROTH):
            return target
        if stat_module.S_ISDIR(st.st_mode) and not allows(
            st, stat_module.S_IXUSR, stat_module.S_IXGRP, stat_module.S_IXOTH
        ):
            return target
        return None
    except OSError:
        return target


def readable_by(path: Path, uid: int, gids: set[int]) -> bool:
    """Whether *uid* can read *path* and reach it through every parent."""
    return unreadable_part(path, uid, gids) is None


#: How many of a root's files the boot audit looks at, beside the root itself.
AUDIT_SAMPLE_FILES = 20


def audit_folder_roots(log=logger) -> list[str]:
    """Warn about every folder source a sandboxed node could not read.

    Under fork isolation a node runs as the execution user and reads a folder
    collection's files by path, so a root that user cannot read is a
    collection whose nodes fail. Checked once at boot; returns the warnings.
    """
    if (os.environ.get("CURIO_ISOLATION") or "").strip().lower() != "fork":
        return []
    user = (os.environ.get("CURIO_EXEC_USER") or "").strip()
    if not user:
        return []
    try:
        import pwd

        entry = pwd.getpwnam(user)
    except (ImportError, KeyError):
        return []
    gids = {entry.pw_gid} | set(os.getgrouplist(user, entry.pw_gid)) if hasattr(os, "getgrouplist") else {entry.pw_gid}
    from utk_curio.backend.app.discovery.domain.manifest import ManifestError, load_source_manifest_from_dir

    warnings = []
    for path in list_discovery_sources():
        try:
            manifest = load_source_manifest_from_dir(path)
        except (ManifestError, ValueError):
            continue
        if manifest.provider.type != "folder":
            continue
        try:
            from dataclasses import replace

            root = storage_root(replace(manifest, origin=origin_of(path)))
        except StorageRootError as exc:
            where = f" ({exc.path})" if exc.path else ""
            warnings.append(f"{manifest.dir_name}: {exc}{where}")
            continue
        blocked = unreadable_part(root, entry.pw_uid, gids)
        if blocked is None:
            blocked = _unreadable_sample(root, entry.pw_uid, gids)
        if blocked is not None:
            warnings.append(
                f"{manifest.dir_name}: {user} cannot read {blocked}, so nodes cannot open "
                f"the files of {root}"
            )
    for warning in warnings:
        log.warning("Discovery Catalog folder source %s", warning)
    return warnings


def _unreadable_sample(root: Path, uid: int, gids: set[int]) -> Path | None:
    """The first of a few of *root*'s files that *uid* cannot read, if any."""
    looked = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            blocked = unreadable_part(Path(dirpath) / name, uid, gids)
            if blocked is not None:
                return blocked
            looked += 1
            if looked >= AUDIT_SAMPLE_FILES:
                return None
    return None
