"""Each open dataflow's Yjs doc, kept by the server, and its sync with the tabs.

One pycrdt ``Doc`` and one ``Awareness`` per open dataflow live in this
process's memory, each behind a lock of its own. What the doc holds, and how it
maps to and from Trill, is ``doc_mapping.py``.

**The protocol.** The Yjs sync protocol and awareness travel as bytes, framed as
y-protocols frames them (sync 0, with step 1, step 2 and update 0 to 2;
awareness 1), in the ``message`` of a ``yjs`` event on the collaboration
namespace: ``{projectId, message}``. Only a socket that joined the dataflow's
room (``join_session``, ``events.py``) takes part.

* A tab starts with sync step 1, naming the doc it holds as ``docId`` if it
  holds one. The server answers with step 2, with its own step 1 when the tab
  edits, and with everyone's awareness; the ack is ``{ok, docId, role}``. A tab
  holding another doc than the server's, one built anew since, is told
  ``reload`` and starts again holding none. It sends updates once this ack is
  in: handlers run on threads of their own.
* The owner's and an editor's step 2 and updates are applied, appended to the
  update log and relayed to the doc's other tabs. The ack, ``{ok, kept}``,
  gives for each client the update brought changes of the clock the doc now
  holds for it, which the top bar's Saved reads.
* A watcher's step 2 and updates are dropped, ``read_only``: nothing is applied
  or relayed. The role is the room's (``room_state``), which a change to the
  editors updates at once (``roles.py``).
* Awareness is relayed to the doc's other tabs and sent whole to a tab that
  starts. The server writes each state's ``user``, the participant the room
  knows; a socket sets only client ids no other account's socket set; a
  watcher's state keeps only its presence (:data:`PRESENCE_FIELDS`), never an
  edit; and a socket's states are cleared when it disconnects (:func:`leave`).

**The log, the dataflow's one history.** Every change to the doc is appended to
its update log the moment it lands, and the log is never emptied. It is kept
beside ``spec.trill.json``, in ``ydoc/<doc id>/``, as a segment a day (UTC):
``<day>.bin``, the doc's state when the day's first change came, and
``<day>.updates``, that day's updates, each a length and then the update. So
the doc at any place in the log is that day's checkpoint and the updates up to
it (:func:`rebuilt`), and a damaged segment loses that day only. The doc keeps
garbage collection on, so no tab ever receives text deleted before it joined.

``ydoc.json`` says where the log is: the doc, its segment of today, and the
place in the log the spec was last written from, with that write's revision
(``storage.spec_revision``).

* After :data:`SAVE_IDLE_S` with no change, or every :data:`SAVE_EVERY_S` of
  steady changes, the doc is written to ``spec.trill.json`` through
  ``storage.write_spec``. The write carries what the spec file holds with the
  doc's dataflow, the agents' sections included, and leaves the history out
  (``storage.HISTORY_KEYS``), which storage keeps as it is.
* A restart reloads the same doc from its log, so tabs that reconnect sync with
  nothing doubled.
* A spec written outside the doc (its revision moved) becomes a transaction on
  the doc, of what that write changed since the doc last read or wrote the
  file; what the doc changed meanwhile stays (``doc_mapping.apply_dataflow``).
* A doc is built anew from Trill, with a new id and a new log, when its state
  is lost, or when no tab holds it and it has grown to :data:`GROWN_TOO_LARGE`
  times a doc built anew; the old log stays where it is, readable.
* A doc leaves memory :data:`CLOSE_AFTER_S` after its last tab, written first.

**Locks**, in this order: the spec lock (``storage.spec_write_lock``), then a
doc's lock, then this module's own; storage's history lock is a leaf. The spec
lock is never asked for while a doc's lock is held, and the thread that writes
the docs touches no database.

**Reads**: :func:`read` is the dataflow as it is now, an open doc's over the
file.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from flask import request
from flask_socketio import join_room
from pycrdt import (
    Awareness,
    Decoder,
    Encoder,
    YMessageType,
    YSyncMessageType,
    create_awareness_message,
    create_sync_message,
    create_update_message,
    handle_sync_message,
    write_message,
)

from utk_curio.backend.app.collaboration import doc_mapping, room_state
from utk_curio.backend.app.collaboration.events import (
    READ_ONLY_REFUSAL,
    _project,
    _valid_project_id,
)
from utk_curio.backend.app.projects import storage
from utk_curio.backend.config import COLLAB_NAMESPACE

logger = logging.getLogger(__name__)

EVENT = doc_mapping.EVENT

#: Beside ``spec.trill.json``: the docs' logs, a folder per doc.
LOG_DIR = "ydoc"
#: Where the log is.
POINTER_FILE = "ydoc.json"
#: The origin of the transaction that carries a spec written outside the doc.
SPEC_ORIGIN = "spec"

#: Seconds with no change before the doc is written to ``spec.trill.json``
#: (JupyterLab's default save delay).
SAVE_IDLE_S = 1.0
#: Seconds of steady changes after which it is written anyway.
SAVE_EVERY_S = 10.0
#: Seconds a doc stays in memory after its last tab leaves (JupyterLab's).
CLOSE_AFTER_S = 60.0
#: A doc no tab holds is built anew once its state is this many times the
#: size of a doc built anew from its Trill...
GROWN_TOO_LARGE = 4.0
#: ...and at least this many bytes, which each tab downloads when it joins.
REBUILD_FLOOR_BYTES = 256 * 1024

#: Whether a thread of this module writes the docs as their times come. Off,
#: :func:`flush_due` does it when it is called.
BACKGROUND = True

#: The awareness field the server writes: who the state is.
USER_FIELD = "user"
#: The awareness fields a watcher's state keeps: where it is, never an edit.
PRESENCE_FIELDS = frozenset({"pointer", "selection"})

_DOC_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _today() -> str:
    """The day a change is logged under, in UTC."""
    return time.strftime("%Y-%m-%d", time.gmtime())


class _NoDataflow(Exception):
    """The dataflow has no spec on disk."""


class _OpenDoc:
    """One open dataflow. Its fields are guarded by :attr:`lock`, but the
    times, which this module's lock guards."""

    def __init__(self, project_id: str, user_key: str):
        self.project_id = project_id
        self.user_key = user_key
        self.lock = threading.RLock()
        self.doc = None
        self.awareness: Optional[Awareness] = None
        self.doc_id: Optional[str] = None
        #: The spec revision the doc last read or wrote, and the doc's part of
        #: the dataflow the spec file held then.
        self.revision = 0
        self.base: dict = {}
        #: The day of the log's segment changes go to, and the place in the
        #: log the spec was last written from.
        self.segment: Optional[str] = None
        self.folded: dict = {}
        self.loaded = False
        self.closed = False
        #: The sockets that started a sync: sid -> participant.
        self.tabs: dict[str, dict] = {}
        #: Each awareness client id, and the socket that set it.
        self.awareness_owners: dict[int, str] = {}
        self.updates: list[bytes] = []
        self.awareness_changed: list[int] = []
        # Guarded by this module's lock.
        self.changed_at: Optional[float] = None
        self.dirty_since: Optional[float] = None
        self.idle_since: Optional[float] = None

    def folder(self) -> Path:
        return storage.project_dir(self.user_key, self.project_id)

    def log_dir(self) -> Path:
        return self.folder() / LOG_DIR / self.doc_id

    def on_update(self, event) -> None:
        self.updates.append(event.update)

    def on_awareness(self, topic, change) -> None:
        if topic == "update":
            changes, _origin = change
            self.awareness_changed += changes["added"] + changes["updated"] + changes["removed"]


_lock = threading.RLock()
_wake = threading.Condition(_lock)
_docs: dict[str, _OpenDoc] = {}
_sid_docs: dict[str, set[str]] = {}
_flusher: Optional[threading.Thread] = None
_clock = time.monotonic


def _relay_room(project_id: str) -> str:
    """The Socket.IO room of the tabs that sync the dataflow's doc."""
    return f"doc:{project_id}"


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------

def _write_atomically(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _records(data: bytes) -> list[tuple[int, bytes]]:
    """The updates in a segment, each with the place its record ends at. A
    record cut short, by a crash in the middle of an append, ends the segment."""
    records: list[tuple[int, bytes]] = []
    i, end = 0, len(data)
    while i < end:
        length = shift = 0
        while True:
            if i >= end:
                return records
            byte = data[i]
            i += 1
            length |= (byte & 0x7F) << shift
            shift += 7
            if byte < 0x80:
                break
        if i + length > end:
            logger.warning("a segment of an update log ends with an update cut short; the rest is dropped")
            return records
        records.append((i + length, data[i:i + length]))
        i += length
    return records


def _segment_files(log_dir: Path, day: str) -> tuple[Path, Path]:
    return log_dir / f"{day}.bin", log_dir / f"{day}.updates"


def _rebuild(folder: Path, doc_id: str, day: str, *, upto: Optional[int] = None):
    """The doc *doc_id* as its log holds it at the end of *day*'s segment, or
    *upto* bytes into its updates: the day's checkpoint, then its updates."""
    checkpoint, updates = _segment_files(folder / LOG_DIR / doc_id, day)
    doc = doc_mapping.new_doc()
    doc.apply_update(checkpoint.read_bytes())
    try:
        data = updates.read_bytes()
    except FileNotFoundError:
        data = b""
    for end, record in _records(data):
        if upto is not None and end > upto:
            break
        try:
            doc.apply_update(record)
        except ValueError:
            logger.warning("the log of doc %s, %s: an update does not apply; the rest is dropped", doc_id, day)
            break
    return doc


def segments(user_key: str, project_id: str, doc_id: str) -> list[str]:
    """The days of a doc's log, oldest first, the docs built anew since
    included."""
    log_dir = storage.project_dir(user_key, project_id) / LOG_DIR / doc_id
    if not _DOC_ID_RE.match(doc_id) or not log_dir.is_dir():
        return []
    return sorted(path.stem for path in log_dir.glob("*.bin") if _DAY_RE.match(path.stem))


def rebuilt(user_key: str, project_id: str, doc_id: str, day: str, *, upto: Optional[int] = None):
    """The doc *doc_id* at the end of *day*'s segment of its log, or *upto*
    bytes into that day's updates: any doc of the dataflow, the ones built anew
    since included."""
    if not _DOC_ID_RE.match(doc_id) or not _DAY_RE.match(day):
        raise ValueError(f"no log {doc_id!r} {day!r}")
    return _rebuild(storage.project_dir(user_key, project_id), doc_id, day, upto=upto)


def logged_updates(user_key: str, project_id: str, doc_id: str, day: str) -> list[bytes]:
    """The updates of *day*'s segment of a doc's log, in order."""
    if not _DOC_ID_RE.match(doc_id) or not _DAY_RE.match(day):
        return []
    _, updates = _segment_files(storage.project_dir(user_key, project_id) / LOG_DIR / doc_id, day)
    try:
        return [record for _end, record in _records(updates.read_bytes())]
    except FileNotFoundError:
        return []


def _read_pointer(folder: Path) -> Optional[dict]:
    try:
        pointer = json.loads((folder / POINTER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    folded = pointer.get("folded") if isinstance(pointer, dict) else None
    if not (
        isinstance(folded, dict)
        and isinstance(pointer.get("doc"), str) and _DOC_ID_RE.match(pointer["doc"])
        and isinstance(pointer.get("segment"), str) and _DAY_RE.match(pointer["segment"])
        and isinstance(pointer.get("specRevision"), int)
        and isinstance(folded.get("segment"), str) and _DAY_RE.match(folded["segment"])
        and isinstance(folded.get("offset"), int)
    ):
        return None
    return pointer


def _write_pointer(entry: _OpenDoc) -> None:
    _write_atomically(entry.folder() / POINTER_FILE, json.dumps({
        "doc": entry.doc_id,
        "segment": entry.segment,
        "specRevision": entry.revision,
        "folded": entry.folded,
    }).encode("utf-8"))


def _start_segment(entry: _OpenDoc, day: str) -> None:
    """Start the log's segment of *day*, the doc's state now its checkpoint."""
    log_dir = entry.log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    checkpoint, updates = _segment_files(log_dir, day)
    _write_atomically(checkpoint, entry.doc.get_update())
    updates.touch(exist_ok=True)
    entry.segment = day


def _begin_log(entry: _OpenDoc) -> None:
    """A log for a doc built anew, its first segment today."""
    _start_segment(entry, _today())
    entry.folded = {"segment": entry.segment, "offset": 0}
    _write_pointer(entry)


def _roll(entry: _OpenDoc) -> None:
    """Start today's segment, if the next change is the day's first."""
    day = _today()
    if day != entry.segment:
        _start_segment(entry, day)
        _write_pointer(entry)


def _append(entry: _OpenDoc, updates: list[bytes]) -> None:
    _, path = _segment_files(entry.log_dir(), entry.segment)
    with open(path, "ab") as log:
        for update in updates:
            log.write(write_message(update))


def _mark_written(entry: _OpenDoc) -> None:
    """The spec now holds the doc as the log holds it here."""
    _, path = _segment_files(entry.log_dir(), entry.segment)
    try:
        offset = path.stat().st_size
    except FileNotFoundError:
        offset = 0
    entry.folded = {"segment": entry.segment, "offset": offset}
    _write_pointer(entry)


def _behind(user_key: str, project_id: str) -> bool:
    """Whether a doc's log holds changes its spec was not written from, as a
    stopped backend can leave it."""
    try:
        folder = storage.project_dir(user_key, project_id)
    except ValueError:
        return False
    pointer = _read_pointer(folder)
    if pointer is None:
        return False
    _, path = _segment_files(folder / LOG_DIR / pointer["doc"], pointer["segment"])
    try:
        size = path.stat().st_size
    except OSError:
        return False
    folded = pointer["folded"]
    return size > (folded["offset"] if folded["segment"] == pointer["segment"] else 0)


# ---------------------------------------------------------------------------
# The spec beside the doc
# ---------------------------------------------------------------------------

def _spec_file(entry: _OpenDoc) -> "storage.SpecFile":
    """``spec.trill.json`` as the file holds it, with its revision
    (``storage.read_spec_file``): the dataflow, without the history
    ``storage.read_spec`` replays, which neither building the doc nor writing it
    needs."""
    try:
        return storage.read_spec_file(entry.user_key, entry.project_id)
    except ValueError:
        logger.error("the spec of dataflow %s does not read as JSON", entry.project_id)
        return storage.SpecFile(None, storage.spec_revision(entry.user_key, entry.project_id))


def _owned(spec: dict) -> dict:
    dataflow = spec.get("dataflow") if isinstance(spec.get("dataflow"), dict) else {}
    return doc_mapping.owned(dataflow)


def _with_dataflow(spec: dict, dataflow: dict) -> dict:
    """*spec* with *dataflow* as its dataflow, the sections kept outside the
    doc taken from *spec*."""
    out = dict(spec)
    old = spec.get("dataflow") if isinstance(spec.get("dataflow"), dict) else {}
    merged = dict(dataflow)
    for name in sorted(doc_mapping.OUTSIDE_THE_DOC):
        if name in old:
            merged[name] = old[name]
    out["dataflow"] = merged
    return out


def _normalized(dataflow: dict) -> dict:
    """*dataflow* as a doc built from it reads it back."""
    doc = doc_mapping.new_doc()
    doc_mapping.dataflow_to_doc(dataflow, doc, doc_id="normalized")
    return doc_mapping.doc_to_dataflow(doc)


def _catch_up(entry: _OpenDoc, file: "storage.SpecFile") -> None:
    """Carry a spec written outside the doc, since the doc last read or wrote
    the file, into the doc: one transaction of what that write changed, logged
    and relayed to every tab like a person's."""
    if file.revision == entry.revision or not isinstance(file.spec, dict):
        return
    theirs = _owned(file.spec)
    _roll(entry)
    try:
        with entry.doc.transaction(origin=SPEC_ORIGIN):
            refused = doc_mapping.apply_dataflow(entry.doc, entry.base, theirs)
    except doc_mapping.DocMappingError:
        logger.error("dataflow %s: a spec written outside its doc has a node field the doc has no "
                     "place for; the doc keeps its own", entry.project_id, exc_info=True)
        refused = []
    for node_id in refused:
        logger.warning("dataflow %s: node %s's code changed outside its doc and in it; the doc's stays",
                       entry.project_id, node_id)
    entry.revision, entry.base = file.revision, theirs
    _commit(entry, skip_sid=None)


# ---------------------------------------------------------------------------
# Opening, writing and closing a doc
# ---------------------------------------------------------------------------

def _attach(entry: _OpenDoc, doc) -> None:
    entry.doc = doc
    entry.doc_id = doc_mapping.doc_id(doc)
    entry.updates = []
    entry.awareness = Awareness(doc)
    entry.awareness.set_local_state(None)  # the server is no one in the room
    doc.observe(entry.on_update)
    entry.awareness.observe(entry.on_awareness)


def _built_anew(entry: _OpenDoc, dataflow: dict) -> None:
    """Make the open doc one built anew from *dataflow*, with a new id and a
    new log; the old doc's log stays where it is."""
    doc = doc_mapping.new_doc()
    doc_mapping.dataflow_to_doc(dataflow, doc, doc_id=uuid.uuid4().hex)
    _attach(entry, doc)
    _begin_log(entry)


def _load(entry: _OpenDoc) -> None:
    """Open the doc from its log, or build it anew from the spec when its state
    is lost; then carry in a spec written outside it, and build anew one grown
    too large."""
    folder = entry.folder()
    file = _spec_file(entry)
    if not isinstance(file.spec, dict):
        raise _NoDataflow(entry.project_id)
    pointer = _read_pointer(folder)
    doc = None
    if pointer is not None:
        try:
            doc = _rebuild(folder, pointer["doc"], pointer["segment"])
            if doc_mapping.doc_id(doc) != pointer["doc"]:
                logger.warning("the log of dataflow %s holds another doc than its pointer names", entry.project_id)
                doc = None
        except (OSError, ValueError, RuntimeError):
            logger.warning("the log of dataflow %s could not be read; its doc is built anew",
                           entry.project_id, exc_info=True)
            doc = None
    if doc is not None:
        _attach(entry, doc)
        entry.segment, entry.revision, entry.folded = pointer["segment"], pointer["specRevision"], pointer["folded"]
        if file.revision == entry.revision:
            entry.base = _owned(file.spec)
        else:
            # What the file held when the doc last wrote it: the log at that place.
            try:
                entry.base = doc_mapping.doc_to_dataflow(
                    _rebuild(folder, entry.doc_id, entry.folded["segment"], upto=entry.folded["offset"])
                )
            except (OSError, ValueError, RuntimeError):
                entry.base = doc_mapping.doc_to_dataflow(doc)  # the file's changes take every field
    else:
        entry.revision, entry.base = file.revision, _owned(file.spec)
        _built_anew(entry, entry.base)
    entry.loaded = True
    _catch_up(entry, file)
    if not entry.tabs:
        _built_anew_if_grown(entry)
    with _wake:
        # Idle until a tab starts its sync (a read opens a doc with none).
        entry.idle_since = _clock()
        _wake.notify_all()
    if not doc_mapping.same(_normalized(entry.base), doc_mapping.doc_to_dataflow(entry.doc)):
        _changed(entry)  # the spec is behind the doc
    else:
        _ensure_flusher()


def _built_anew_if_grown(entry: _OpenDoc) -> None:
    """Build anew a doc grown too large: each tab downloads its whole state when
    it joins, deleted items included."""
    size = len(entry.doc.get_update())
    if size <= REBUILD_FLOOR_BYTES:
        return
    dataflow = doc_mapping.doc_to_dataflow(entry.doc)
    fresh = doc_mapping.new_doc()
    doc_mapping.dataflow_to_doc(dataflow, fresh, doc_id="measure")
    if size <= GROWN_TOO_LARGE * len(fresh.get_update()):
        return
    logger.info("the doc of dataflow %s grew to %d bytes; it is built anew", entry.project_id, size)
    _built_anew(entry, dataflow)


@contextmanager
def _held(project_id: str, user_key: str) -> Iterator[_OpenDoc]:
    """The open doc of the dataflow, opened if it is not, with its lock held."""
    while True:
        with _lock:
            entry = _docs.get(project_id)
            if entry is None or entry.closed:
                entry = _docs[project_id] = _OpenDoc(project_id, user_key)
        with entry.lock:
            if entry.closed:
                continue
            if not entry.loaded:
                try:
                    _load(entry)
                except BaseException:
                    entry.closed = True
                    with _lock:
                        if _docs.get(project_id) is entry:
                            del _docs[project_id]
                    raise
            yield entry
            return


def _open_entry(project_id: str) -> Optional[_OpenDoc]:
    with _lock:
        entry = _docs.get(project_id)
    return entry if entry is not None and not entry.closed else None


def _changed(entry: _OpenDoc) -> None:
    """Note a change the spec does not have yet."""
    with _wake:
        now = _clock()
        entry.changed_at = now
        if entry.dirty_since is None:
            entry.dirty_since = now
        _wake.notify_all()
    _ensure_flusher()


def _save_due(entry: _OpenDoc) -> Optional[float]:
    """When the doc's changes are due in ``spec.trill.json``: a second after
    the last, and at most ten after the first."""
    if entry.dirty_since is None:
        return None
    return min(entry.changed_at + SAVE_IDLE_S, entry.dirty_since + SAVE_EVERY_S)


def _close_due(entry: _OpenDoc) -> Optional[float]:
    return None if entry.idle_since is None else entry.idle_since + CLOSE_AFTER_S


def _discard(entry: _OpenDoc) -> None:
    """Drop a doc whose dataflow is gone, writing nothing."""
    with entry.lock:
        entry.closed = True
        with _lock:
            if _docs.get(entry.project_id) is entry:
                del _docs[entry.project_id]


def _flush(entry: _OpenDoc) -> bool:
    """Write the doc's changes to ``spec.trill.json``, a spec written outside
    the doc carried in first. Whether it wrote."""
    try:
        folder = entry.folder()
    except ValueError:
        return False
    if not (folder / storage.SPEC_FILE).is_file():
        _discard(entry)  # the dataflow was deleted: its folder must not come back
        return False
    with storage.spec_write_lock(entry.user_key, entry.project_id):
        with entry.lock:
            with _lock:
                dirty = entry.dirty_since is not None
            if entry.closed or not entry.loaded or not dirty:
                return False
            file = _spec_file(entry)
            if not isinstance(file.spec, dict):
                _discard(entry)
                return False
            _catch_up(entry, file)
            # What the file holds, its dataflow the doc's, and no history: a
            # section a write leaves out stays on record (write_spec), so no
            # write of the doc reads or rewrites the history.
            dataflow = doc_mapping.doc_to_dataflow(entry.doc)
            kept = {key: value for key, value in file.spec.items() if key not in storage.HISTORY_KEYS}
            storage.write_spec(entry.user_key, entry.project_id, _with_dataflow(kept, dataflow))
            entry.revision, entry.base = file.revision + 1, dataflow
            _mark_written(entry)
            with _lock:
                entry.dirty_since = entry.changed_at = None
            return True


def _close(entry: _OpenDoc) -> bool:
    """Take a doc no tab syncs out of memory, written first. Whether it went."""
    if entry.dirty_since is not None:
        _flush(entry)
    with entry.lock:
        with _lock:
            if entry.closed or entry.tabs or entry.dirty_since is not None or entry.idle_since is None:
                return False
            entry.closed = True
            if _docs.get(entry.project_id) is entry:
                del _docs[entry.project_id]
    return True


def flush(project_id: str) -> bool:
    """Write the open doc's changes now. Whether it wrote ``spec.trill.json``."""
    entry = _open_entry(project_id)
    return entry is not None and _flush(entry)


def close(project_id: str) -> bool:
    """Take the doc out of memory now, written first, if no tab syncs it."""
    entry = _open_entry(project_id)
    if entry is None:
        return False
    with _lock:
        if entry.idle_since is None and not entry.tabs:
            entry.idle_since = _clock()
    return _close(entry)


def flush_due(now: Optional[float] = None) -> None:
    """Write each doc whose changes are due, and close each that is idle long
    enough."""
    now = _clock() if now is None else now
    with _lock:
        entries = list(_docs.values())
    for entry in entries:
        with _lock:
            close_due, save_due = _close_due(entry), _save_due(entry)
        if close_due is not None and now >= close_due:
            _close(entry)
        elif save_due is not None and now >= save_due:
            _flush(entry)


def _ensure_flusher() -> None:
    global _flusher
    if not BACKGROUND:
        return
    with _wake:
        if _flusher is None or not _flusher.is_alive():
            _flusher = threading.Thread(target=_run_flusher, name="dataflow-docs", daemon=True)
            _flusher.start()
        _wake.notify_all()


def _run_flusher() -> None:
    global _flusher
    while True:
        failed = False
        try:
            flush_due()
        except Exception:  # noqa: BLE001 - a failed write must not stop the next ones
            logger.exception("writing the open dataflows' docs failed")
            failed = True
        with _wake:
            if not _docs or not BACKGROUND:
                if _flusher is threading.current_thread():
                    _flusher = None
                return
            dues = [due for entry in _docs.values()
                    for due in (_save_due(entry), _close_due(entry)) if due is not None]
            wait = max(0.0, min(dues) - _clock()) if dues else CLOSE_AFTER_S
            if failed:
                wait = max(wait, SAVE_IDLE_S)  # a write that fails is tried again, not in a spin
            _wake.wait(timeout=wait)


def close_all() -> None:
    """Write every open doc and take them all out of memory."""
    with _lock:
        entries = list(_docs.values())
    for entry in entries:
        if entry.dirty_since is not None:
            _flush(entry)
        with entry.lock:
            entry.closed = True
    with _lock:
        _docs.clear()
        _sid_docs.clear()


def reset_for_tests() -> None:
    """Forget every open doc, writing nothing, as a backend that stopped does."""
    with _lock:
        for entry in _docs.values():
            entry.closed = True
        _docs.clear()
        _sid_docs.clear()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def read(user_key: str, project_id: str) -> Optional[dict]:
    """The dataflow's spec as it is now: its open doc's dataflow over the file.
    A doc that is not open but whose log holds changes its spec does not, which
    a stopped backend can leave, is opened to read them."""
    spec = storage.read_spec(user_key, project_id)
    if spec is None:
        return None
    if _open_entry(project_id) is None and not _behind(user_key, project_id):
        return spec
    try:
        with _held(project_id, user_key) as entry:
            _catch_up(entry, _spec_file(entry))
            return _with_dataflow(spec, doc_mapping.doc_to_dataflow(entry.doc))
    except (_NoDataflow, doc_mapping.DocMappingError):
        return spec


def is_open(project_id: str) -> bool:
    return _open_entry(project_id) is not None


def doc_id_of(project_id: str) -> Optional[str]:
    """The id of the dataflow's open doc."""
    entry = _open_entry(project_id)
    return entry.doc_id if entry is not None else None


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------

def _refused(error: str, **extra) -> dict:
    return {"ok": False, "error": error, **extra}


def _socketio():
    """The SocketIO server of the app at hand, else the backend's."""
    from flask import current_app, has_app_context

    from utk_curio.backend import extensions

    if has_app_context() and current_app.extensions.get("socketio") is not None:
        return current_app.extensions["socketio"]
    return extensions.socketio


def _emit(message: bytes, project_id: str, *, to: str, skip_sid: Optional[str] = None) -> None:
    sio = _socketio()
    if sio is not None:
        sio.emit(EVENT, {"projectId": project_id, "message": message},
                 to=to, skip_sid=skip_sid, namespace=COLLAB_NAMESPACE)


def _framed(data: bytes) -> bytes:
    """What a y-protocols frame carries after its type bytes: a length, then
    that many bytes."""
    payload = Decoder(data).read_message() if data else None
    if payload is None:
        raise ValueError("a frame with nothing in it")
    return payload


def _clocks(doc) -> dict[int, int]:
    """The doc's state vector: each client's next clock."""
    decoder = Decoder(doc.get_state())
    clocks: dict[int, int] = {}
    for _ in range(decoder.read_var_uint()):
        client = decoder.read_var_uint()
        clocks[client] = decoder.read_var_uint()
    return clocks


def _commit(entry: _OpenDoc, *, skip_sid: Optional[str]) -> bool:
    """Log and relay what the doc's last transaction changed. Whether the
    log has it."""
    updates, entry.updates = entry.updates, []
    if not updates:
        return True
    logged = True
    try:
        _append(entry, updates)
    except OSError:
        logged = False
        logger.error("dataflow %s: a change could not be added to its update log", entry.project_id,
                     exc_info=True)
    for update in updates:
        _emit(create_update_message(update), entry.project_id,
              to=_relay_room(entry.project_id), skip_sid=skip_sid)
    _changed(entry)
    return logged


def _relay_awareness(entry: _OpenDoc, *, skip_sid: Optional[str]) -> None:
    changed, entry.awareness_changed = entry.awareness_changed, []
    ids = sorted(set(changed))
    if ids:
        _emit(create_awareness_message(entry.awareness.encode_awareness_update(ids)), entry.project_id,
              to=_relay_room(entry.project_id), skip_sid=skip_sid)


def _user(me: dict) -> dict:
    """Who an awareness state is, as the room knows the participant."""
    return {
        "participant_id": me.get("participant_id"),
        "user_id": me.get("user_id"),
        "username": me.get("username"),
        "name": me.get("name"),
        "role": me.get("role"),
    }


def _named(state: dict, me: dict) -> dict:
    """*state* as the server relays it: named by the server, and a watcher's
    without its edits."""
    if me.get("role") in room_state.EDIT_ROLES:
        kept = {field: value for field, value in state.items() if field != USER_FIELD}
    else:
        kept = {field: value for field, value in state.items() if field in PRESENCE_FIELDS}
    kept[USER_FIELD] = _user(me)
    return kept


def _accepted_awareness(entry: _OpenDoc, sid: str, me: dict, data: bytes) -> bytes:
    """The states of an awareness update a socket may set, as the server
    relays them. A client id another account's socket set is not this one's."""
    decoder = Decoder(data)
    entries = []
    for _ in range(decoder.read_var_uint()):
        client_id = decoder.read_var_uint()
        clock = decoder.read_var_uint()
        entries.append((client_id, clock, decoder.read_var_string()))
    accepted = []
    for client_id, clock, text in entries:
        owner = entry.awareness_owners.get(client_id)
        if owner is not None and owner != sid:
            other = entry.tabs.get(owner)
            if other is not None and other.get("user_id") != me.get("user_id"):
                continue
        try:
            state = json.loads(text) if text else None
        except ValueError:
            continue
        if state is None:
            entry.awareness_owners.pop(client_id, None)
            accepted.append((client_id, clock, None))
        elif isinstance(state, dict):
            entry.awareness_owners[client_id] = sid
            accepted.append((client_id, clock, _named(state, me)))
    encoder = Encoder()
    encoder.write_var_uint(len(accepted))
    for client_id, clock, state in accepted:
        encoder.write_var_uint(client_id)
        encoder.write_var_uint(clock)
        # ASCII JSON: pycrdt's encoder writes a string's length in characters.
        encoder.write_var_string(json.dumps(state, separators=(",", ":")))
    return encoder.to_bytes()


def _start(sid: str, me: dict, project_id: str, message: bytes, held_id) -> dict:
    """A tab's sync step 1."""
    from utk_curio.backend.app.projects.services import _owner_user_dir_key

    project = _project(project_id)
    if project is None:
        return _refused("unknown_project")
    try:
        with _held(project_id, _owner_user_dir_key(project)) as entry:
            if held_id is not None and held_id != entry.doc_id:
                return _refused("reload", docId=entry.doc_id)
            _framed(message[2:])  # the tab's state, which step 2 answers
            _catch_up(entry, _spec_file(entry))
            replies = [handle_sync_message(message[1:], entry.doc)]
            if me.get("role") in room_state.EDIT_ROLES:
                replies.append(create_sync_message(entry.doc))
            states = sorted(entry.awareness.states)
            if states:
                replies.append(create_awareness_message(entry.awareness.encode_awareness_update(states)))
            entry.tabs[sid] = me
            with _lock:
                entry.idle_since = None
                _sid_docs.setdefault(sid, set()).add(project_id)
            join_room(_relay_room(project_id), sid=sid, namespace=COLLAB_NAMESPACE)
            for reply in replies:
                if reply:
                    _emit(reply, project_id, to=sid)
            return {"ok": True, "docId": entry.doc_id, "role": me.get("role")}
    except _NoDataflow:
        return _refused("no_dataflow")
    except doc_mapping.DocMappingError as exc:
        return _refused("unmappable", message=str(exc))
    except OSError:
        logger.error("the doc of dataflow %s could not be opened", project_id, exc_info=True)
        return _refused("unavailable")


def _synced(project_id: str, sid: str) -> Optional[_OpenDoc]:
    entry = _open_entry(project_id)
    return entry if entry is not None and sid in entry.tabs else None


def _update(sid: str, me: dict, project_id: str, message: bytes) -> dict:
    """A tab's sync step 2 or update."""
    if me.get("role") not in room_state.EDIT_ROLES:
        return _refused("read_only", message=READ_ONLY_REFUSAL)
    entry = _synced(project_id, sid)
    if entry is None:
        return _refused("not_synced")
    with entry.lock:
        if entry.closed or sid not in entry.tabs:
            return _refused("not_synced")
        update = _framed(message[2:])
        _roll(entry)
        before = _clocks(entry.doc)
        if update != b"\x00\x00":
            with entry.doc.transaction(origin=sid):
                entry.doc.apply_update(update)
        kept = {str(client): clock for client, clock in _clocks(entry.doc).items()
                if before.get(client) != clock}
        logged = _commit(entry, skip_sid=sid)
    if not logged:
        return _refused("not_kept")
    return {"ok": True, "kept": kept}


def _awareness(sid: str, me: dict, project_id: str, message: bytes) -> dict:
    entry = _synced(project_id, sid)
    if entry is None:
        return _refused("not_synced")
    with entry.lock:
        if entry.closed or sid not in entry.tabs:
            return _refused("not_synced")
        accepted = _accepted_awareness(entry, sid, me, _framed(message[1:]))
        entry.awareness.apply_awareness_update(accepted, sid)
        _relay_awareness(entry, skip_sid=sid)
    return {"ok": True}


def receive(sid: str, payload) -> dict:
    """One ``yjs`` message from the socket *sid*; the ack."""
    if not room_state.get_identity(sid):
        return _refused("unauthorized")
    if not isinstance(payload, dict):
        return _refused("invalid_payload")
    project_id = payload.get("projectId")
    if not _valid_project_id(project_id):
        return _refused("invalid_project_id")
    message = payload.get("message")
    if isinstance(message, bytearray):
        message = bytes(message)
    if not isinstance(message, bytes) or not message:
        return _refused("invalid_message")
    me = room_state.participant(room_state.room_for(project_id), sid)
    if me is None:
        return _refused("not_joined")
    try:
        if message[0] == YMessageType.SYNC and len(message) > 1:
            if message[1] == YSyncMessageType.SYNC_STEP1:
                return _start(sid, me, project_id, message, payload.get("docId"))
            if message[1] in (YSyncMessageType.SYNC_STEP2, YSyncMessageType.SYNC_UPDATE):
                return _update(sid, me, project_id, message)
        elif message[0] == YMessageType.AWARENESS:
            return _awareness(sid, me, project_id, message)
    except (ValueError, RuntimeError, IndexError, AssertionError):
        logger.info("a yjs message from %s for dataflow %s does not read", sid, project_id, exc_info=True)
    return _refused("invalid_message")


def leave(sid: str) -> None:
    """The socket *sid* disconnected: its tab leaves each doc it synced, and its
    awareness states are cleared for the others."""
    with _lock:
        project_ids = _sid_docs.pop(sid, set())
    for project_id in project_ids:
        entry = _open_entry(project_id)
        if entry is None:
            continue
        with entry.lock:
            if entry.closed:
                continue
            entry.tabs.pop(sid, None)
            ids = [client for client, owner in entry.awareness_owners.items() if owner == sid]
            for client in ids:
                del entry.awareness_owners[client]
            if ids:
                entry.awareness.remove_awareness_states(ids, sid)
                _relay_awareness(entry, skip_sid=sid)
            if not entry.tabs:
                with _wake:
                    entry.idle_since = _clock()
                    _wake.notify_all()
                _ensure_flusher()


def register(sio) -> None:
    """Attach the doc's event to the SocketIO server."""

    @sio.on(EVENT, namespace=COLLAB_NAMESPACE)
    def _yjs(payload=None):
        return receive(request.sid, payload)
