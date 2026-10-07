"""The catalog files the pip package leaves out, fetched from GitHub on first use.

The repository holds every file of the Data Catalog (``datasets/``) and the
Model Catalog (``models/``). PyPI takes no file over 100 MiB, so the pip
package (the sdist, and the wheel built from it) leaves out the big ones,
named in ``left_out_files.json`` beside this module. Each is the data file of
a dataset or the entry of a model; the small files of its folder (the
manifest, a parquet's decode sidecar, a license) still ship. ``MANIFEST.in``
excludes exactly the listed files, which ``test_left_out_files`` checks.

The release build records each listed file's size and sha256, and the commit
the package is built from: ``scripts/record_left_out_files.py`` writes
``left_out_files.record.json`` here before ``python -m build``, and the
package ships it. On a pip install, a reader that finds a listed file missing
calls :func:`fetch`, which downloads it from
``https://raw.githubusercontent.com/urban-toolkit/curio/<commit>/<path>``
through the egress policy (``agents/infrastructure/egress.download``), checks
its size and sha256 against the record, and places it under Curio's state
directory, at ``<state>/fetched/<commit>/<path>`` (``<state>`` is ``.curio``,
or ``CURIO_STATE_DIR``): a pip install's site-packages may be read-only. The
small files of its catalog folder are copied beside it, so the folder there
reads as the folder in a clone: a model's manifest beside its entry, a
parquet's sidecar beside the parquet.

- Placing is atomic. The bytes go to a file under ``.partial/`` on the same
  file system, are checked, are made readable by every account (an isolated
  node's execution account reads a hardlink of the file), and are renamed
  into place. A partial download never sits where a reader looks.
- One download per file at a time: a reader that finds another downloading
  the file waits for it (``common/file_locks.exclusive_lock``), then reads
  what it placed.
- ``<state>/fetched`` is its owner's alone, as the sandbox's isolation leaves
  the shipped models (``sandbox/isolation/hardening.py`` lists both): an
  execution account reads a fetched file through the hardlink a run stages.
- A download first removes the files fetched for other releases, so an
  upgrade does not keep the old ones.
- A checkout (a clone, the Docker image, CI) has every file and no record, so
  it never downloads.

A failure raises :class:`LeftOutFileUnavailable`, whose message says what
failed and how to get the file by hand. Readers that turn a failure into a
missing file still report it: :func:`failures` collects them, and a node run
fails with them (``execution/node_exec``).
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from utk_curio.backend.app.agents.infrastructure import egress
from utk_curio.backend.app.common.file_locks import exclusive_lock
from utk_curio.backend.app.common.user_storage import curio_root

#: The one list of the files the pip package leaves out.
LIST_PATH = Path(__file__).with_name("left_out_files.json")
#: What the release build recorded of them. A checkout has none.
RECORD_PATH = Path(__file__).with_name("left_out_files.record.json")

REPOSITORY = "https://github.com/urban-toolkit/curio"
RAW = "https://raw.githubusercontent.com/urban-toolkit/curio"
#: The folder of Curio's state directory the fetched files go to.
FETCHED = "fetched"
#: Long enough for the biggest listed file (about 13 MB) over a slow link.
DOWNLOAD_TIMEOUT_S = 600

#: The transport and the DNS resolver ``egress.download`` uses; ``None`` is
#: the network. Tests set both, since no test may open a socket.
request_fn = None
resolver = None

_HEX = frozenset("0123456789abcdef")
_failures: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "left_out_file_failures", default=None,
)


class LeftOutFileUnavailable(RuntimeError):
    """A file the pip package leaves out could not be had. The message says
    what failed and how to get the file."""


@dataclass(frozen=True)
class RecordedFile:
    size: int
    sha256: str


@dataclass(frozen=True)
class Record:
    """What the release build recorded: its commit, and each listed file."""

    commit: str
    files: dict[str, RecordedFile]


def left_out_paths() -> tuple[str, ...]:
    """The repository paths of the files the pip package leaves out."""
    return _read_list(str(LIST_PATH))


@functools.lru_cache(maxsize=4)
def _read_list(path: str) -> tuple[str, ...]:
    return tuple(json.loads(Path(path).read_text(encoding="utf-8"))["files"])


def is_left_out(repo_path: str) -> bool:
    return repo_path in left_out_paths()


def is_commit(value: object) -> bool:
    """A full commit hash: 40 lowercase hexadecimal digits."""
    return isinstance(value, str) and len(value) == 40 and set(value) <= _HEX


def read_record(path: Path | None = None) -> Record | None:
    """The release's record (``RECORD_PATH`` unless *path* is given), or
    ``None`` where there is none. Raises ``ValueError`` for a record that
    cannot be read."""
    path = Path(path or RECORD_PATH)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    return _parse_record(str(path), stamp)


@functools.lru_cache(maxsize=8)
def _parse_record(path: str, _stamp: int) -> Record:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} could not be read: {exc}") from exc
    if not isinstance(raw, dict) or not is_commit(raw.get("commit")):
        raise ValueError(f"{path} names no commit")
    files = {}
    for repo_path, entry in (raw.get("files") or {}).items():
        size = entry.get("size") if isinstance(entry, dict) else None
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError(f"{path} gives {repo_path} no size")
        if not isinstance(digest, str) or len(digest) != 64 or not set(digest.lower()) <= _HEX:
            raise ValueError(f"{path} gives {repo_path} no sha256")
        files[str(repo_path)] = RecordedFile(size=size, sha256=digest.lower())
    return Record(commit=raw["commit"], files=files)


def recorded_size(repo_path: str) -> int | None:
    """The size the release recorded for *repo_path*, or ``None``: what the
    Data Catalog shows for a file it has not fetched yet."""
    try:
        record = read_record()
    except ValueError:
        return None
    entry = record.files.get(repo_path) if record is not None else None
    return entry.size if entry is not None else None


def source_url(commit: str, repo_path: str) -> str:
    """Where GitHub serves *repo_path* as it is at *commit*."""
    return f"{RAW}/{commit}/{quote(repo_path, safe='/@')}"


def fetched_dir() -> Path:
    """Every fetched file is under this folder of Curio's state directory."""
    return curio_root() / FETCHED


def fetched_root(commit: str) -> Path:
    """Where the files of the release built from *commit* are placed: each at
    its repository path under it."""
    return fetched_dir() / commit


@contextlib.contextmanager
def failures():
    """Collect the fetches that fail inside the block, as ``{repo path:
    message}``, even where a reader turns the error into a missing file: a
    node run fails with them rather than with "not available"."""
    collected: dict[str, str] = {}
    token = _failures.set(collected)
    try:
        yield collected
    finally:
        _failures.reset(token)


def fetch(repo_path: str, shipped: Path) -> Path:
    """The file to read for *repo_path*, a path in the repository.

    *shipped* is where the package holds it. When it is there it is the
    answer, and nothing is fetched. Otherwise *repo_path* is a file the
    package leaves out, and the answer is its fetched copy, downloaded now
    when this is the first read. Raises :class:`LeftOutFileUnavailable`.
    """
    shipped = Path(shipped)
    if shipped.is_file():
        return shipped
    if not is_left_out(repo_path):
        raise ValueError(f"{repo_path} is not a file the pip package leaves out")
    try:
        record = read_record()
    except ValueError as exc:
        raise _unavailable(repo_path, (
            f"Curio could not read the record of its release, {exc}, so it cannot download "
            f"{repo_path}. Start Curio from a clone of {REPOSITORY}, which holds the file."
        )) from exc
    if record is None:
        raise _unavailable(repo_path, (
            f"{repo_path} is not in this Curio, which has no record of a release to download it "
            f"from. Start Curio from a clone of {REPOSITORY}, which holds the file "
            f"(git checkout -- {repo_path} puts it back in a clone)."
        ))
    entry = record.files.get(repo_path)
    if entry is None:
        raise _unavailable(repo_path, (
            f"{repo_path} is not in the record of this Curio's release, so Curio cannot download "
            f"it. Start Curio from a clone of {REPOSITORY}, which holds the file."
        ))
    root = fetched_root(record.commit)
    target = root / repo_path
    if target.is_file():
        return target
    _close_fetched_dir()
    locks = root / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    lock = locks / f"{hashlib.sha256(repo_path.encode('utf-8')).hexdigest()[:32]}.lock"
    with exclusive_lock(lock, namespace="left-out-files", key=f"{record.commit}/{repo_path}"):
        # Another reader may have placed it while this one waited.
        if not target.is_file():
            _remove_other_releases(record.commit)
            _download(repo_path, entry, record.commit, Path(shipped), target)
    return target


def _close_fetched_dir() -> None:
    """Create :func:`fetched_dir` for its owner alone, as the sandbox's
    isolation leaves the shipped ``models/`` (``.curio/fetched`` is in
    ``hardening.SENSITIVE_PATHS`` and ``HARDLINK_SOURCES``): an execution
    account reads a fetched file only through the hardlink a run stages, and
    cannot rename or replace one. Done here as well because the first fetch
    usually comes after the sandbox hardened what existed when it started."""
    folder = fetched_dir()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass  # another account's folder: the sandbox's hardening answers for it


def _remove_other_releases(commit: str) -> None:
    """Remove the files fetched for any release other than *commit*: an
    upgrade fetches its own files, and nothing reads the old ones again.

    Only folders named by a commit, directly under :func:`fetched_dir`, are
    removed; a symlink there is left alone, and nothing it points at is
    followed. The folder of *commit* itself, which a concurrent fetch may be
    filling, is never touched."""
    try:
        entries = list(os.scandir(fetched_dir()))
    except OSError:
        return
    for entry in entries:
        if entry.name == commit or not is_commit(entry.name):
            continue
        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
            continue
        shutil.rmtree(entry.path, ignore_errors=True)


def _download(repo_path: str, entry: RecordedFile, commit: str, shipped: Path, target: Path) -> None:
    url = source_url(commit, repo_path)
    root = fetched_root(commit)
    partial_dir = root / ".partial"
    partial_dir.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=partial_dir, suffix=".part")
    partial = Path(name)
    try:
        try:
            with os.fdopen(handle, "wb") as sink:
                result = egress.download(
                    url, sink=sink.write, max_bytes=entry.size,
                    request_fn=request_fn, resolver=resolver, timeout_s=DOWNLOAD_TIMEOUT_S,
                )
                sink.flush()
                os.fsync(sink.fileno())
        except Exception as exc:  # noqa: BLE001 - the policy's refusal, the network's error, a full disk
            reason = str(exc) or exc.__class__.__name__
            raise _unavailable(repo_path, _could_not_download(repo_path, url, target, reason)) from exc
        if result.status != 200:
            raise _unavailable(repo_path, _could_not_download(
                repo_path, url, target, f"GitHub answered HTTP {result.status}",
            ))
        if result.bytes_written != entry.size or result.sha256 != entry.sha256:
            raise _unavailable(repo_path, _could_not_download(repo_path, url, target, (
                f"the file GitHub sent ({result.bytes_written:,} bytes, sha256 {result.sha256}) is "
                f"not the one this release recorded ({entry.size:,} bytes, sha256 {entry.sha256})"
            )))
        os.chmod(partial, 0o644)
        _copy_folder(repo_path, shipped, root, partial_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def _copy_folder(repo_path: str, shipped: Path, root: Path, partial_dir: Path) -> None:
    """Copy the files of *repo_path*'s catalog folder that the package holds
    (``datasets/<dir>`` or ``models/<dir>``) to the same place under *root*,
    so the folder there reads as the folder in a clone."""
    parts = PurePosixPath(repo_path).parts
    folder = PurePosixPath(*parts[:2]).as_posix()
    shipped_folder = shipped
    for _ in parts[2:]:
        shipped_folder = shipped_folder.parent
    if not shipped_folder.is_dir():
        return
    left_out = set(left_out_paths())
    for path in sorted(shipped_folder.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(shipped_folder).as_posix()
        destination = root / folder / rel
        if f"{folder}/{rel}" in left_out or destination.is_file():
            continue
        handle, name = tempfile.mkstemp(dir=partial_dir, suffix=".part")
        os.close(handle)
        copy = Path(name)
        try:
            shutil.copyfile(path, copy)
            os.chmod(copy, 0o644)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(copy, destination)
        finally:
            copy.unlink(missing_ok=True)


def _could_not_download(repo_path: str, url: str, target: Path, reason: str) -> str:
    return (
        f"Curio could not download {repo_path}: {reason}. A pip install of Curio leaves this "
        f"file out of its package and downloads it from GitHub the first time it is needed, "
        f"from {url}. To add it by hand, download that file and save it as {target}, or start "
        f"Curio from a clone of {REPOSITORY}, which holds it."
    )


def _unavailable(repo_path: str, message: str) -> LeftOutFileUnavailable:
    collected = _failures.get()
    if collected is not None:
        collected.setdefault(repo_path, message)
    return LeftOutFileUnavailable(message)
