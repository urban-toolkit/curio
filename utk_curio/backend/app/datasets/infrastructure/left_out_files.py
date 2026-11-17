"""The catalog files the pip package leaves out, fetched from GitHub on first use.

The repository holds every file of the Data Catalog (``datasets/``) and of the
model packages (``packages/<dir>/models/``). PyPI takes no file over 100 MiB,
so the pip package (the sdist, and the wheel built from it) leaves out the big
ones: the data file of a dataset, or the weights of a model package, that its
manifest names in ``downloadOnFirstUse``
(``packages/domain/download_on_first_use.py``); ``setup.py`` leaves them out.
The small files of its folder (the manifest, a parquet's decode sidecar, a
license, a package's code) still ship, so a pip install reads the same
manifests (:func:`declared_paths`, through ``utk_curio/shipped.py``). A model
package's weight must also match the sha256 its package's ``integrity.json``
names (``fetch``'s *expected_sha256*).

The release build records each left-out file's size and sha256, and the commit
the package is built from: ``scripts/record_left_out_files.py`` writes
``left_out_files.record.json`` here before ``python -m build``, and the
package ships it. On a pip install, a reader that finds a left-out file missing
calls :func:`fetch`, which downloads it from
``https://raw.githubusercontent.com/urban-toolkit/curio/<commit>/<path>``
through the egress policy (``agents/infrastructure/egress.download``), checks
its size and sha256 against the record, and places it under Curio's state
directory, at ``<state>/fetched/<commit>/<path>`` (``<state>`` is ``.curio``,
or ``CURIO_STATE_DIR``): a pip install's site-packages may be read-only. The
small files of its catalog folder are copied beside it, so the folder there
reads as the folder in a clone: a model package's manifest and code beside
its weights, a parquet's sidecar beside the parquet.

- Placing is atomic (:func:`download_checked`). The bytes go to a file under
  ``.partial/`` on the same file system, are checked, are made readable by
  every account (an isolated node's execution account reads a hardlink of the
  file), and are renamed into place. A partial download never sits where a
  reader looks.
- A download that stops, its connection dropped or its process killed by a
  restart, leaves its partial file, one per file, and the next goes on from
  where it ends: it asks for the rest alone, and checks the whole file. A
  file so made that does not match is downloaded again from its first byte.
- One download per file at a time: a reader that finds another downloading
  the file waits for it (:func:`one_download_at_a_time`), then reads what it
  placed.
- A download has no time limit of its own: it fails when the network sends
  nothing for :data:`IDLE_TIMEOUT_S`, so a big file takes as long as its bytes
  take to come. It says how far it has come to whoever runs what reads it
  (:func:`reporting`): a run on the server shows it on the node.
- ``<state>/fetched`` is its owner's alone, as the sandbox's isolation leaves
  the shipped model packages' weights (``sandbox/isolation/hardening.py``
  lists both): an
  execution account reads a fetched file through the hardlink a run stages.
- A download first removes the files fetched for other releases, so an
  upgrade does not keep the old ones.
- A checkout (a clone, the Docker image, CI) has every file and no record, so
  it never downloads.

A failure raises :class:`LeftOutFileUnavailable`, whose message says what
failed and how to get the file by hand. Readers that turn a failure into a
missing file still report it: :func:`failures` collects them, and a node run
fails with them (``execution/node_exec``).

The weights a shipped model package's ``fetch`` names download the first time
a node needs them through the same code: :func:`download_checked`,
:func:`one_download_at_a_time`, :func:`remove_stale_partials` and
:func:`unavailable` (``packages/infrastructure/fetched_weights.py``).
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from utk_curio import shipped as shipped_folders
from utk_curio.backend.app.agents.infrastructure import egress
from utk_curio.backend.app.common.file_locks import exclusive_lock
from utk_curio.backend.app.common.user_storage import curio_root

#: The folder that holds the ``datasets/`` and ``packages/`` whose manifests
#: name the files the pip package leaves out; ``None`` is Curio's own
#: (``root()`` in ``utk_curio/shipped.py``). Tests set it.
SHIPPED_ROOT: Path | None = None
#: What the release build recorded of them. A checkout has none.
RECORD_PATH = Path(__file__).with_name("left_out_files.record.json")

REPOSITORY = "https://github.com/urban-toolkit/curio"
RAW = "https://raw.githubusercontent.com/urban-toolkit/curio"
#: The folder of Curio's state directory the fetched files go to.
FETCHED = "fetched"
#: The longest a download waits for its connection, and then for its next
#: bytes, before it fails: the transport's connect and read timeout
#: (``egress.download``). It bounds a stall, never the whole download.
IDLE_TIMEOUT_S = 600
#: What a partial file's name ends with.
PARTIAL_SUFFIX = ".part"
#: What the name of a partial file the next download goes on from ends with:
#: one per file, whose download's lock makes that download its one writer.
#: It is never stale (:func:`remove_stale_partials`).
RESUMABLE_SUFFIX = ".download" + PARTIAL_SUFFIX
#: A partial file no download has written for this long was left by a
#: process that died mid-download: a live download writes at least once an
#: idle timeout, after its connection and its first bytes.
STALE_PARTIAL_S = 3 * IDLE_TIMEOUT_S
_CHUNK = 1024 * 1024

#: The transport and the DNS resolver ``egress.download`` uses; ``None`` is
#: the network. Tests set both, since no test may open a socket.
request_fn = None
resolver = None

log = logging.getLogger(__name__)

_HEX = frozenset("0123456789abcdef")
_failures: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "left_out_file_failures", default=None,
)
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-\d+/(\d+|\*)$")


class LeftOutFileUnavailable(RuntimeError):
    """A file Curio downloads on first use could not be had: one the pip
    package leaves out, or a file of the weights a model package's ``fetch``
    names. The message says what failed and how to get the file."""


@dataclass(frozen=True)
class RecordedFile:
    size: int
    sha256: str


@dataclass(frozen=True)
class Record:
    """What the release build recorded: its commit, and each listed file."""

    commit: str
    files: dict[str, RecordedFile]


def size_text(size: int) -> str:
    """*size* bytes as a person reads them: ``3.44 GB``, ``512 B``."""
    for unit, scale in (("GB", 10**9), ("MB", 10**6), ("kB", 10**3)):
        if size >= scale:
            return f"{size / scale:.2f} {unit}"
    return f"{size} B"


def _part_text(done: int, total: int) -> str:
    """*done* of *total* bytes, in *total*'s unit: ``1.21 of 3.44 GB``."""
    for unit, scale in (("GB", 10**9), ("MB", 10**6), ("kB", 10**3)):
        if total >= scale:
            return f"{done / scale:.2f} of {total / scale:.2f} {unit}"
    return f"{done} of {total} B"


@dataclass(frozen=True)
class Progress:
    """How far one download on first use has come: *what* it downloads, as a
    person reads it, the bytes *done*, the *total*, None when the source
    names no size, and *resumed*, the bytes an earlier download had left,
    which this one goes on from."""

    what: str
    done: int
    total: int | None
    resumed: int = 0

    @property
    def message(self) -> str:
        """What the node that reads it says while it downloads:
        ``Downloading <what>: 1.21 of 3.44 GB (35%)``."""
        if self.total:
            text = f"Downloading {self.what}: {_part_text(self.done, self.total)} ({self.done * 100 // self.total}%)"
        else:
            text = f"Downloading {self.what}: {size_text(self.done)} so far"
        if self.resumed:
            text += f", going on from the {size_text(self.resumed)} an earlier download left"
        return text


class _Reporter:
    """Where the downloads of one run report their progress, and whether one
    has since its downloads began (:func:`downloading`)."""

    def __init__(self, report):
        self.report = report
        self.reported = False

    def send(self, progress: Progress | None) -> None:
        if progress is not None:
            self.reported = True
        try:
            self.report(progress)
        except Exception:  # noqa: BLE001 - what shows the progress never fails the download
            log.warning("A download's progress could not be reported", exc_info=True)


_progress: contextvars.ContextVar[_Reporter | None] = contextvars.ContextVar(
    "first_use_download_progress", default=None,
)


@contextlib.contextmanager
def reporting(report):
    """Hand *report* the :class:`Progress` of each download on first use made
    inside the block, on this thread, as it goes: a run's step, which shows
    it on the node that reads what downloads (``execution/run_engine.py``).
    *report* gets None once the downloads of a run's resolution are over
    (:func:`downloading`). A report that raises is logged and never fails a
    download; *report* None reports nothing."""
    token = _progress.set(_Reporter(report) if report is not None else None)
    try:
        yield
    finally:
        _progress.reset(token)


@contextlib.contextmanager
def downloading():
    """The part of a node's run in which what it reads downloads on first use
    (``execution/node_exec.py``): once it ends, a reporter one of its
    downloads reported to (:func:`reporting`) gets None, so what shows the
    progress says the downloads are over and the node runs."""
    reporter = _progress.get()
    if reporter is not None:
        reporter.reported = False
    try:
        yield
    finally:
        if reporter is not None and reporter.reported:
            reporter.reported = False
            reporter.send(None)


class _Meter:
    """Reports one download's progress to the run's reporter, if any: as it
    starts, as it passes each whole percent of its size, or of its bound when
    the source names no size, and as it ends."""

    def __init__(self, what: str, max_bytes: int):
        self.reporter = _progress.get()
        self.what = what
        self.max_bytes = max(int(max_bytes), 1)
        self.total: int | None = None
        self.resumed = 0
        self.last: tuple[int, int] | None = None

    def start(self, total: int | None, resumed: int) -> None:
        self.total, self.resumed, self.last = total, resumed, None
        self.at(resumed)

    def at(self, done: int, *, end: bool = False) -> None:
        """Report *done* bytes: the first time, at each whole percent not
        reported yet, and with *end* unless that count was just reported."""
        if self.reporter is None:
            return
        whole = done * 100 // (self.total or self.max_bytes)
        if self.last is not None:
            last_whole, last_done = self.last
            if done == last_done or (whole == last_whole and not end):
                return
        self.last = (whole, done)
        self.reporter.send(Progress(self.what, done, self.total, self.resumed))


def _shipped_root() -> Path:
    return Path(SHIPPED_ROOT) if SHIPPED_ROOT is not None else shipped_folders.root()


def declared_paths() -> tuple[str, ...]:
    """The repository paths the shipped manifests name in
    ``downloadOnFirstUse``: files, and folders of files. A manifest that
    cannot be read names none; the catalog's reader refuses it."""
    return _declared(str(_shipped_root()))


@functools.lru_cache(maxsize=4)
def _declared(root: str) -> tuple[str, ...]:
    return shipped_folders.downloaded_on_first_use(Path(root), strict=False)


def left_out_paths() -> tuple[str, ...]:
    """The repository paths of the files the pip package leaves out: each
    file a shipped manifest names, and each file in a folder one names, as
    the folder holds them in a checkout or as the release recorded them."""
    root = _shipped_root()
    recorded = _recorded_paths()
    files: list[str] = []
    for repo_path in declared_paths():
        folder = root / repo_path
        if folder.is_dir():
            inside = [
                f"{repo_path}/{path.relative_to(folder).as_posix()}"
                for path in sorted(folder.rglob("*")) if path.is_file()
            ]
        else:
            inside = [path for path in recorded if path.startswith(f"{repo_path}/")]
        files += inside or [repo_path]
    return tuple(dict.fromkeys(files))


def _recorded_paths() -> list[str]:
    try:
        record = read_record()
    except ValueError:
        return []
    return sorted(record.files) if record is not None else []


def is_left_out(repo_path: str) -> bool:
    """Whether the pip package leaves *repo_path* out: a file a shipped
    manifest names, or a file in a folder one names."""
    return shipped_folders.covers(declared_paths(), repo_path)


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


def fetch(repo_path: str, shipped: Path, *, expected_sha256: str | None = None) -> Path:
    """The file to read for *repo_path*, a path in the repository.

    *shipped* is where the package holds it. When it is there it is the
    answer, and nothing is fetched. Otherwise *repo_path* is a file the
    package leaves out, and the answer is its fetched copy, downloaded now
    when this is the first read. *expected_sha256*, when given, is a second
    digest the download must have besides the record's: the one a model
    package's ``integrity.json`` names for its weight. Raises
    :class:`LeftOutFileUnavailable`.
    """
    shipped = Path(shipped)
    if shipped.is_file():
        return shipped
    if not is_left_out(repo_path):
        raise ValueError(f"{repo_path} is not a file the pip package leaves out")
    try:
        record = read_record()
    except ValueError as exc:
        raise unavailable(repo_path, (
            f"Curio could not read the record of its release, {exc}, so it cannot download "
            f"{repo_path}. Start Curio from a clone of {REPOSITORY}, which holds the file."
        )) from exc
    if record is None:
        raise unavailable(repo_path, (
            f"{repo_path} is not in this Curio, which has no record of a release to download it "
            f"from. Start Curio from a clone of {REPOSITORY}, which holds the file "
            f"(git checkout -- {repo_path} puts it back in a clone)."
        ))
    entry = record.files.get(repo_path)
    if entry is None:
        raise unavailable(repo_path, (
            f"{repo_path} is not in the record of this Curio's release, so Curio cannot download "
            f"it. Start Curio from a clone of {REPOSITORY}, which holds the file."
        ))
    root = fetched_root(record.commit)
    target = root / repo_path
    if target.is_file():
        return target
    _close_fetched_dir()
    lock = root / ".locks" / f"{_path_key(repo_path)}.lock"
    with one_download_at_a_time(lock, key=f"{record.commit}/{repo_path}"):
        # Another reader may have placed it while this one waited.
        if not target.is_file():
            _remove_other_releases(record.commit)
            remove_stale_partials(root / ".partial")
            _download(repo_path, entry, record.commit, Path(shipped), target, expected_sha256=expected_sha256)
    return target


def _path_key(repo_path: str) -> str:
    """The name *repo_path*'s lock and partial file go by in its release's
    folder: one per file, whatever its name, which another file may share."""
    return hashlib.sha256(repo_path.encode("utf-8")).hexdigest()[:32]


@contextlib.contextmanager
def one_download_at_a_time(lock: Path, *, key: str):
    """Hold the lock under which one download places what *key* names, in
    this process and across processes (``common/file_locks.exclusive_lock``),
    on the file *lock*, which is made readable by every account and
    writable by its owner alone. A second reader waits for the first, then
    finds what it placed."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    os.close(os.open(lock, os.O_WRONLY | os.O_CREAT, 0o644))
    with contextlib.suppress(OSError):
        os.chmod(lock, 0o644)  # whatever the umask; another account's lock keeps its own mode
    with exclusive_lock(lock, namespace="downloads-on-first-use", key=key):
        yield


def remove_stale_partials(folder: Path) -> None:
    """Remove the partial files in *folder* that no download writes any more:
    each one a process left when it died mid-download, unwritten for
    :data:`STALE_PARTIAL_S`. A live download's partial is newer, and stays,
    as does one the next download of its file goes on from
    (:data:`RESUMABLE_SUFFIX`), however old."""
    now = time.time()
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    for entry in entries:
        if not entry.name.endswith(PARTIAL_SUFFIX) or entry.name.endswith(RESUMABLE_SUFFIX):
            continue
        try:
            if entry.is_file(follow_symlinks=False) and now - entry.stat(follow_symlinks=False).st_mtime > STALE_PARTIAL_S:
                os.unlink(entry.path)
        except OSError:
            continue  # gone already, or not this account's to remove: the next download tries again


@dataclass(frozen=True)
class Received:
    """What a download wrote to its partial file, as a ``check`` of
    :func:`download_checked` reads it: the answer's *status*, 200 for a file
    whose every byte is in the partial file, and its *headers*; and the whole
    file's *bytes_written* and *sha256*, the bytes an earlier download had
    left (*resumed*) among them."""

    status: int
    headers: dict
    bytes_written: int
    sha256: str
    resumed: int = 0


class _Refused(Exception):
    """An answer that is not the file asked for, seen before its body."""

    def __init__(self, status: int, headers: dict):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.headers = headers


class _NothingAfter(Exception):
    """A source that has no byte after the partial file's end (HTTP 416)."""


def _content_range(headers: dict) -> tuple[int, int | None] | None:
    """``(first byte, size or None)`` of a ``Content-Range`` answer header."""
    raw = (headers or {}).get("Content-Range") or (headers or {}).get("content-range") or ""
    found = _CONTENT_RANGE.match(str(raw).strip())
    if found is None:
        return None
    return int(found.group(1)), (None if found.group(2) == "*" else int(found.group(2)))


def _content_length(headers: dict) -> int | None:
    raw = (headers or {}).get("Content-Length") or (headers or {}).get("content-length")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _sha256_of(path: Path, limit: int):
    """A sha256 of the first *limit* bytes of *path*, to be fed what follows."""
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        left = limit
        while left > 0:
            chunk = source.read(min(_CHUNK, left))
            if not chunk:
                break
            digest.update(chunk)
            left -= len(chunk)
    return digest


def _receive(url: str, partial: Path, *, max_bytes: int, failed, meter: _Meter, go_on: bool) -> Received:
    """Download *url* into *partial*, from its first byte, or with *go_on*
    from where *partial* ends: only the rest is asked for (``Range``), and a
    source that sends the whole file instead writes it over. Up to
    *max_bytes* in all. An answer that is not the file is returned before a
    byte of it is written, the partial file as it was. Raises what
    *failed(reason)* makes of the transport's or the disk's failure, the
    partial file keeping the bytes that came."""
    start = 0
    if go_on:
        try:
            start = partial.stat().st_size
        except OSError:
            start = 0
        if start >= max_bytes:
            start = 0
    try:
        digest = _sha256_of(partial, start) if start else hashlib.sha256()
        handle = os.open(partial, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise failed(str(exc) or exc.__class__.__name__) from exc
    state = {"start": start, "written": 0, "digest": digest}
    with os.fdopen(handle, "r+b") as sink:
        sink.seek(start)
        sink.truncate()

        def before_body(headers: dict, _final_url: str, *, status: int) -> None:
            if status == 206 and start and (_content_range(headers) or (None,))[0] == start:
                meter.start((_content_range(headers) or (None, None))[1], start)
                return
            if status == 200:
                if start:
                    # The whole file, whatever was asked: written over from its first byte.
                    sink.seek(0)
                    sink.truncate()
                    state["start"], state["digest"] = 0, hashlib.sha256()
                meter.start(_content_length(headers), 0)
                return
            if status == 416 and start:
                raise _NothingAfter()
            raise _Refused(status, dict(headers or {}))

        def write(chunk: bytes) -> None:
            if state["start"] + state["written"] + len(chunk) > max_bytes:
                raise egress.EgressTooLarge(f"the file exceeded the {max_bytes}-byte bound while streaming")
            sink.write(chunk)
            state["digest"].update(chunk)
            state["written"] += len(chunk)

        try:
            try:
                answer = egress.download(
                    url, sink=write, max_bytes=max_bytes,
                    request_fn=request_fn, resolver=resolver, timeout_s=IDLE_TIMEOUT_S,
                    headers={"Range": f"bytes={start}-"} if start else None,
                    progress=lambda written, _declared: meter.at(state["start"] + written),
                    before_body=before_body,
                )
            finally:
                # What came is on disk, for the next download to go on from.
                sink.flush()
                os.fsync(sink.fileno())
        except _Refused as refused:
            return Received(refused.status, refused.headers, 0, "", resumed=start)
        except _NothingAfter:
            # The partial file may be the whole file: checked as it is.
            return Received(200, {}, start, digest.hexdigest(), resumed=start)
        except Exception as exc:  # noqa: BLE001 - the policy's refusal, the network's error, a full disk
            if isinstance(exc, egress.EgressTooLarge):
                # A file over its bound: nothing of it is gone on from.
                sink.seek(0)
                sink.truncate()
            raise failed(str(exc) or exc.__class__.__name__) from exc
    done = state["start"] + state["written"]
    meter.at(done, end=True)
    return Received(200, dict(answer.headers or {}), done, state["digest"].hexdigest(), resumed=state["start"])


def download_checked(
    url: str, target: Path, *, partial_dir: Path, max_bytes: int, check, failed, before_place=None,
    partial_name: str | None = None, what: str | None = None,
) -> None:
    """Download *url* and place it at *target*, as Curio places every file it
    downloads on first use.

    The bytes stream through the egress policy (``egress.download``, which
    waits :data:`IDLE_TIMEOUT_S` for each and has no limit on the whole) into
    a file of *partial_dir*, on *target*'s file system, up to *max_bytes*.
    *check(result, partial)* says why they are not the file asked for, or
    None: *result* is what came (:class:`Received`), the whole file's bytes
    and sha256 when its status is 200. Then the file is made readable by
    every account (an isolated node's execution account reads it),
    *before_place* runs when given, and the file is renamed into place. The
    download reports how far it has come (:func:`reporting`), naming *what*
    it downloads, *target*'s name unless given.

    The partial file has a name of its own, gone when the call ends, or
    *partial_name* when the caller's lock is the only writer of it. Then a
    download that stops, its connection dropped or its process killed,
    leaves it, and the next goes on from where it ends, asking for the rest
    alone and checking the whole file. A file so made that *check* refuses
    is downloaded again from its first byte, once. An answer that is not the
    file leaves the partial file as it was.

    Raises what *failed(reason)* makes of a failure, the transport's, the
    disk's or *check*'s, and places nothing.
    """
    meter = _Meter(what or target.name, max_bytes)
    resumable = partial_name is not None
    try:
        partial_dir.mkdir(parents=True, exist_ok=True)
        if resumable:
            partial = partial_dir / partial_name
        else:
            handle, name = tempfile.mkstemp(dir=partial_dir, prefix=f".{target.name}.", suffix=PARTIAL_SUFFIX)
            os.close(handle)
            partial = Path(name)
    except OSError as exc:
        raise failed(str(exc) or exc.__class__.__name__) from exc
    placed = False
    try:
        result = _receive(url, partial, max_bytes=max_bytes, failed=failed, meter=meter, go_on=resumable)
        reason = check(result, partial)
        if reason is not None and result.status == 200 and result.resumed:
            # What an earlier download left did not begin the file.
            result = _receive(url, partial, max_bytes=max_bytes, failed=failed, meter=meter, go_on=False)
            reason = check(result, partial)
        if reason is not None:
            if result.status == 200:
                # Bytes that are not the file: none of them is gone on from.
                partial.unlink(missing_ok=True)
            raise failed(reason)
        os.chmod(partial, 0o644)
        if before_place is not None:
            before_place()
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(partial, target)
        placed = True
    finally:
        if not resumable or (not placed and _is_empty(partial)):
            partial.unlink(missing_ok=True)


def _is_empty(path: Path) -> bool:
    """Whether *path* holds no byte to go on from."""
    try:
        return path.stat().st_size == 0
    except OSError:
        return False


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


def _download(
    repo_path: str, entry: RecordedFile, commit: str, shipped: Path, target: Path,
    *, expected_sha256: str | None = None,
) -> None:
    url = source_url(commit, repo_path)
    root = fetched_root(commit)
    partial_dir = root / ".partial"

    def check(result, _partial: Path) -> str | None:
        if result.status != 200:
            return f"GitHub answered HTTP {result.status}"
        if result.bytes_written != entry.size or result.sha256 != entry.sha256:
            return (
                f"the file GitHub sent ({result.bytes_written:,} bytes, sha256 {result.sha256}) is "
                f"not the one this release recorded ({entry.size:,} bytes, sha256 {entry.sha256})"
            )
        if expected_sha256 is not None and result.sha256 != expected_sha256.lower():
            return (
                f"the file GitHub sent (sha256 {result.sha256}) is not the one its package's "
                f"integrity.json names (sha256 {expected_sha256})"
            )
        return None

    download_checked(
        url, target, partial_dir=partial_dir, max_bytes=entry.size, check=check,
        failed=lambda reason: unavailable(repo_path, _could_not_download(repo_path, url, target, reason)),
        before_place=lambda: _copy_folder(repo_path, shipped, root, partial_dir),
        # The file's lock makes this download the one writer of its partial
        # file, which the next goes on from when this one stops.
        partial_name=f"{_path_key(repo_path)}{RESUMABLE_SUFFIX}",
        what=repo_path,
    )


def _copy_folder(repo_path: str, shipped: Path, root: Path, partial_dir: Path) -> None:
    """Copy the files of *repo_path*'s catalog folder that the package holds
    (``datasets/<dir>``, ``models/<dir>`` or ``packages/<dir>``) to the same
    place under *root*, so the folder there reads as the folder in a clone."""
    parts = PurePosixPath(repo_path).parts
    folder = PurePosixPath(*parts[:2]).as_posix()
    shipped_folder = shipped
    for _ in parts[2:]:
        shipped_folder = shipped_folder.parent
    if not shipped_folder.is_dir():
        return
    for path in sorted(shipped_folder.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(shipped_folder).as_posix()
        destination = root / folder / rel
        if is_left_out(f"{folder}/{rel}") or destination.is_file():
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


def unavailable(key: str, message: str) -> LeftOutFileUnavailable:
    """The error of a file Curio could not download on first use, which
    *message* explains, for its caller to raise. A block that collects
    failures (:func:`failures`) keeps *message* under *key*, the first for
    each key, so a node's run fails with it."""
    collected = _failures.get()
    if collected is not None:
        collected.setdefault(key, message)
    return LeftOutFileUnavailable(message)
