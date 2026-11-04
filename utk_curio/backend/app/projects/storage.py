"""Filesystem operations for project artifacts.

Every path composed here routes through
:mod:`utk_curio.backend.app.common.safe_paths`, which validates untrusted
segments *and* enforces a proper containment check against the base dir.
Because segment validation rejects ``..`` / path separators before the
filesystem is touched, a traversal attempt like ``project_id="../../etc"``
fails immediately regardless of how deeply the target would have nested
under the users base.

The spec written here is a *trill* document (canonical spec:
``docs/schemas/trill.v1.json``). Note that ``write_spec`` deliberately does not
validate it - the readers downstream are all tolerant of malformed members, and a
save-time gate would reject specs users can currently save. Enforcement lives in
``backend/tests/test_projects/test_trill_schema.py`` and
``scripts/validate_trill.py`` instead.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

from utk_curio.backend.app.common.file_locks import exclusive_lock

logger = logging.getLogger(__name__)

# The two-layer lock (in-process threading lock + cross-process flock) lives in
# ``common.file_locks``; the package seeder needs the identical dance, and one
# implementation means a platform quirk is fixed in one place.
_SPEC_LOCK_NAMESPACE = "spec"

from utk_curio.backend.app.common.safe_paths import (
    PathTraversalError,
    safe_join,
    validate_component,
)
from utk_curio.backend.app.projects.schemas import OutputRef


# Re-exported under the module-private names this file has always used, so the
# ~10 import sites elsewhere are untouched. ``user_storage`` explains why the
# root moves under ``.curio/test/`` for a test rig.
from utk_curio.backend.app.common.user_storage import (
    GUEST_KEY as _GUEST_KEY,
    launch_dir as _launch_dir,
    user_key_segment as _user_key_segment,
    users_base as _users_base,
)


def _shared_data_dir() -> Path:
    rel = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    return (_launch_dir() / rel).resolve()


# ---------------------------------------------------------------------------
# Directory management
# ---------------------------------------------------------------------------

def project_dir(user_key: str, project_id: str) -> Path:
    return safe_join(
        _users_base(),
        _user_key_segment(user_key),
        "projects",
        project_id,
        field="project_id",
    )


def ensure_project_dir(user_key: str, project_id: str) -> Path:
    d = project_dir(user_key, project_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "data").mkdir(exist_ok=True)
    return d


def user_dir(user_key: str) -> Path:
    """The user's own root under ``.curio/users/``."""
    return safe_join(_users_base(), _user_key_segment(user_key), field="user_key")


# ---------------------------------------------------------------------------
# Spec I/O
# ---------------------------------------------------------------------------

#: Where a project's write counter lives (memo dev/124): a one-line file beside
#: the spec rather than a key inside it, for three reasons. A client sends the
#: whole spec, so a key inside it is a number the client can reset — the basis
#: has to be something only the server writes. Reading one small file is
#: cheaper than parsing the previous spec on every write, and every write has
#: to bump it. And it stays invisible to every reader of the spec, so nothing
#: downstream — the trill schema, an export, a copy — grows a field it has no
#: use for.
#:
#: It counts EVERY write, which is the property the ``spec_revision`` column
#: cannot have: that one is bumped by ``repositories.upsert_project``, which
#: runs for a client save and nothing else, so it stays equal across exactly
#: the background writes a client needs to notice (an agent apply, a Solve
#: wave, an install).
SPEC_REVISION_FILE = ".spec.rev"


def spec_revision(user_key: str, project_id: str) -> int:
    """How many times this project's spec has been written.

    ``0`` for a project last written before dev/124, and for one that does not
    exist — both mean "no basis to compare against", which is how the guard
    reads it.
    """
    try:
        path = project_dir(user_key, project_id) / SPEC_REVISION_FILE
    except (PathTraversalError, ValueError):
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0

def _write_json_atomically(path: Path, payload: dict) -> None:
    """Write *payload* so a concurrent reader never sees a half-written file.

    ``Path.write_text`` truncates first and writes second, so any reader that
    arrives between the two gets zero bytes. Readers here take no lock (the
    spec lock serializes writers against writers only), so this is reachable
    from ordinary use: it surfaced as the Agent Catalog 500ing with
    ``Expecting value: line 1 column 1 (char 0)`` while a save was in flight,
    which is ``json.loads("")``.

    A temp file in the SAME directory plus ``os.replace`` makes the swap
    atomic on POSIX and on Windows, so a reader sees either the whole old file
    or the whole new one.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        # A crash between write and replace would otherwise leave the temp
        # behind; replace() has already consumed it on the happy path.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


SPEC_FILE = "spec.trill.json"


def write_spec(user_key: str, project_id: str, spec: dict) -> Path:
    """Persist *spec* and bump the project's write counter.

    Only ``collaboration/dataflow_docs.py`` calls it: every writer of a
    dataflow goes through the dataflow's doc, which writes this file
    (``test_only_the_doc_writes_a_dataflow`` holds it).

    Its two history sections go to the project's history logs, not to the
    spec file (:data:`HISTORY_KEYS`): a section *spec* holds becomes the one
    on record, and one it does not hold stays as it is on record, so a writer
    that leaves the history out never erases it (:func:`drop_history` does).
    A section the spec file on disk still holds, saved before the history
    moved beside it, is on record there: a write that leaves it out moves it
    into its log before the spec file is replaced.
    The logs are written first, then the spec file, so a crash between the
    two leaves the history on disk, and a spec file that still holds it is
    read as it is (:func:`read_spec_in`). All of it under the history lock,
    so two writers that do not hold the spec lock cannot leave one's spec
    beside the other's history.

    The counter is bumped BEFORE the spec is written, so a crash between the
    two leaves it ahead rather than behind: a client is then told its basis is
    stale when it is not, which costs it a reload, where the other order would
    let it silently overwrite the write that did land.
    """
    d = ensure_project_dir(user_key, project_id)
    with _history_lock(d):
        _bump_spec_revision(d)
        live = spec
        if isinstance(spec, dict):
            left_out = [key for key in HISTORY_KEYS if key not in spec]
            in_file = _sections_in_spec_file(d) if left_out else {}
            for key in HISTORY_KEYS:
                if key in spec:
                    _write_section(d, key, spec[key])
                elif key in in_file:
                    _write_section(d, key, in_file[key])
            live = {k: v for k, v in spec.items() if k not in HISTORY_KEYS}
        p = d / SPEC_FILE
        _write_json_atomically(p, live)
    return p


def drop_history(user_key: str, project_id: str) -> None:
    """Remove the project's history, from its logs and from a spec file that
    still holds it, so its document holds no history until a write gives it
    one. The seeder calls it before it writes an example's shipped copy,
    which keeps no history of the copy it replaces. The write counter stays
    as it is: the seeder's write follows."""
    d = project_dir(user_key, project_id)
    if not d.is_dir():
        return
    with _history_lock(d):
        for key in HISTORY_KEYS:
            _drop_section(d, key)
        if _sections_in_spec_file(d):
            spec = json.loads((d / SPEC_FILE).read_text(encoding="utf-8"))
            _write_json_atomically(
                d / SPEC_FILE, {k: v for k, v in spec.items() if k not in HISTORY_KEYS},
            )


@contextmanager
def history_lock(user_key: str, project_id: str):
    """The project's history lock (:func:`_history_lock`), for the history's
    points (``collaboration/history.py``), which it guards beside the logs."""
    with _history_lock(project_dir(user_key, project_id)):
        yield


def history_sections(user_key: str, project_id: str) -> dict:
    """The history sections (:data:`HISTORY_KEYS`) the project holds on
    record, as a spec holds them: each log's, or the spec file's for one it
    still holds. What the history's points import once
    (``collaboration/history.py``)."""
    d = project_dir(user_key, project_id)
    if not d.is_dir():
        return {}
    with _history_lock(d):
        in_file = _sections_in_spec_file(d)
        logs = {key: _read_log_bytes(d, key) for key in HISTORY_KEYS if key not in in_file}
    out = dict(in_file)
    for key, data in logs.items():
        if data is None:
            continue
        value, _committed = _replay(data, _SECTIONS[key])
        if value is not _ABSENT:
            out[key] = value
    return out


#: Where the history sections go once the history's points hold them:
#: ``history/imported/``, kept as the logs were, and read by nothing.
IMPORTED_DIR = "imported"


def set_history_aside(user_key: str, project_id: str) -> None:
    """Move the history sections on record into ``history/imported/``, as
    logs, once the history's points hold them: no read or write of the
    document finds them again. A spec file that still holds one leaves it,
    the rest of the file as it is, and the write counter as it is."""
    d = project_dir(user_key, project_id)
    if not d.is_dir():
        return
    with _history_lock(d):
        in_file = _sections_in_spec_file(d)
        aside = d / HISTORY_DIR / IMPORTED_DIR
        for key in HISTORY_KEYS:
            path = _log_path(d, key)
            target = aside / HISTORY_FILES[key]
            if path.is_file():
                aside.mkdir(parents=True, exist_ok=True)
                os.replace(path, target)
            elif key in in_file:
                aside.mkdir(parents=True, exist_ok=True)
                _rewrite(target, _SECTIONS[key].records(in_file[key]))
        if in_file:
            spec = json.loads((d / SPEC_FILE).read_text(encoding="utf-8"))
            _write_json_atomically(
                d / SPEC_FILE, {k: v for k, v in spec.items() if k not in HISTORY_KEYS},
            )


def drop_history_aside(user_key: str, project_id: str) -> None:
    """Remove what :func:`set_history_aside` kept, and the logs a later write
    made, with what a spec file still holds: the history's points clear the
    history before a version, or drop it (``collaboration/history.py``)."""
    d = project_dir(user_key, project_id)
    if not d.is_dir():
        return
    drop_history(user_key, project_id)
    with _history_lock(d):
        shutil.rmtree(d / HISTORY_DIR / IMPORTED_DIR, ignore_errors=True)


def write_history(user_key: str, project_id: str, sections: dict) -> bool:
    """Put *sections*, history sections (:data:`HISTORY_KEYS`) as a spec holds
    them, on record as the project's history, and write nothing else: not its
    dataflow, which its doc writes, and not the write counter. A section the
    spec file still holds, saved before the history moved beside it, leaves
    the file, which keeps the rest as it is, so the log is what a read finds.
    A tab bound to the doc saves this way (``services.update_project``).
    Whether the project has a spec to keep a history beside."""
    d = project_dir(user_key, project_id)
    if not (d / SPEC_FILE).is_file():
        return False
    sent = {key: sections[key] for key in HISTORY_KEYS if key in sections}
    with _history_lock(d):
        for key, value in sent.items():
            _write_section(d, key, value)
        if set(_sections_in_spec_file(d)) & set(sent):
            spec = json.loads((d / SPEC_FILE).read_text(encoding="utf-8"))
            _write_json_atomically(d / SPEC_FILE, {k: v for k, v in spec.items() if k not in sent})
    return True


def _sections_in_spec_file(folder: Path) -> dict:
    """The history sections the spec file in *folder* still holds, saved
    before the history moved beside it: none for a file written since, or
    for none at all. A file that names neither section is not parsed."""
    try:
        data = (folder / SPEC_FILE).read_bytes()
    except FileNotFoundError:
        return {}
    if not any(f'"{key}"'.encode("ascii") in data for key in HISTORY_KEYS):
        return {}
    try:
        spec = json.loads(data)
    except ValueError:
        return {}
    if not isinstance(spec, dict):
        return {}
    return {key: spec[key] for key in HISTORY_KEYS if key in spec}


def _bump_spec_revision(project_dir_path: Path) -> int:
    path = project_dir_path / SPEC_REVISION_FILE
    try:
        current = int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        current = 0
    nxt = current + 1
    try:
        path.write_text(f"{nxt}\n", encoding="utf-8")
    except OSError:
        # A counter that cannot be written must not fail the save: the guard
        # reads a missing counter as "no basis", which is today's behaviour.
        return current
    return nxt


def read_spec(user_key: str, project_id: str) -> Optional[dict]:
    """The project's whole document, its history put back (:func:`read_spec_in`),
    or ``None`` when it has no spec."""
    return read_spec_in(project_dir(user_key, project_id))


def read_spec_in(folder: Path) -> Optional[dict]:
    """The whole document of the project in *folder*: its spec file, and each
    history section the file does not hold, read back from its log. A spec
    file that still holds a section is read as it is; its next write moves
    the section into the log. ``None`` when there is no spec file.

    The files are read under the history lock, so a write is seen whole or
    not at all, and parsed once it is released.
    """
    p = folder / SPEC_FILE
    if not p.exists():
        return None
    if not (folder / HISTORY_DIR).is_dir():
        return json.loads(p.read_text(encoding="utf-8"))
    with _history_lock(folder):
        text = p.read_text(encoding="utf-8")
        logs = {key: _read_log_bytes(folder, key) for key in HISTORY_KEYS}
    spec = json.loads(text)
    if isinstance(spec, dict):
        for key in HISTORY_KEYS:
            if key in spec or logs[key] is None:
                continue
            value, _committed = _replay(logs[key], _SECTIONS[key])
            if value is not _ABSENT:
                spec[key] = value
    return spec


class SpecFile(NamedTuple):
    """A project's spec file as it is (``None`` when it has none), and the
    revision (:func:`spec_revision`) it was written at."""

    spec: Optional[dict]
    revision: int


def read_spec_file(user_key: str, project_id: str) -> SpecFile:
    """The project's spec file as it is, its document without the history the
    logs keep, which this does not replay, with its revision. For a reader that
    needs only what the file holds, as each open dataflow's doc does
    (``collaboration/dataflow_docs.py``).

    The two are read under the history lock, which every write holds around
    its revision bump and its file, so they belong to one write.
    """
    folder = project_dir(user_key, project_id)
    if not folder.is_dir():
        return SpecFile(None, 0)
    with _history_lock(folder):
        try:
            text = (folder / SPEC_FILE).read_text(encoding="utf-8")
        except FileNotFoundError:
            text = None
        revision = spec_revision(user_key, project_id)
    return SpecFile(None if text is None else json.loads(text), revision)


def list_project_ids(user_key: str) -> list[str]:
    """Project ids (on-disk folder names) that have a saved spec for *user_key*."""
    base = _users_base() / _user_key_segment(user_key) / "projects"
    if not base.is_dir():
        return []
    ids: list[str] = []
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and (entry / SPEC_FILE).is_file():
            ids.append(entry.name)
    return ids


# ---------------------------------------------------------------------------
# History: the nodes' entries and the dataflow's versions, beside the spec
# ---------------------------------------------------------------------------

#: The two sections of a dataflow that hold its history: each node's runs and
#: edits, and the dataflow's own versions, every one a whole copy of the
#: dataflow. They stay out of the spec file, each in a log of its own in
#: ``history/``, so a write adds what the history gained instead of writing
#: every version again.
HISTORY_KEYS = ("nodeProvenance", "dataflowProvenance")
HISTORY_DIR = "history"
HISTORY_FILES = {"nodeProvenance": "entries.jsonl", "dataflowProvenance": "versions.jsonl"}

#: Closes the lines one write added to a log. A reader applies a write's lines
#: only once this one follows them, so a write cut short reads as not made,
#: and the next write starts where the last whole one ended.
_END = ["end"]

_HISTORY_LOCK_FILE = ".history.lock"
_HISTORY_LOCK_NAMESPACE = "history"

#: A section no log holds.
_ABSENT = object()


@contextmanager
def _history_lock(folder: Path):
    """The lock every write of a project's spec and history logs takes, and
    every read of them once the project has logs.

    It holds nothing else: inside it no other lock is asked for and the
    database is never written, so it is taken under the spec lock and by a
    thread holding an uncommitted database write alike, which the spec lock
    refuses (#909). Its thread lock is not reentrant, and nothing in it calls
    a function that takes it again.
    """
    with exclusive_lock(
        folder / _HISTORY_LOCK_FILE,
        namespace=_HISTORY_LOCK_NAMESPACE,
        key=str(folder),
    ):
        yield


def _log_path(folder: Path, key: str) -> Path:
    return folder / HISTORY_DIR / HISTORY_FILES[key]


def _read_log_bytes(folder: Path, key: str) -> Optional[bytes]:
    try:
        return _log_path(folder, key).read_bytes()
    except FileNotFoundError:
        return None


def _line(record: list) -> bytes:
    """One record as the log writes it: compact JSON on one line, ASCII only,
    as the spec file escapes what is not."""
    return json.dumps(record, separators=(",", ":")).encode("ascii") + b"\n"


def _replay(data: bytes, section) -> tuple:
    """The section *data*, a log's bytes, holds, and how many of its bytes
    the writes that ended hold: ``(value, committed)``, the value
    :data:`_ABSENT` when no write ended. A line cut short (a crash mid write)
    or damaged ends the reading there."""
    value = section.empty()
    present = False
    pending: list = []
    committed = 0
    offset = 0
    for raw in data.split(b"\n")[:-1]:
        end = offset + len(raw) + 1
        try:
            record = json.loads(raw)
        except ValueError:
            logger.warning("A history log holds a line that cannot be read; what follows it is not read")
            break
        if not isinstance(record, list) or not record or not isinstance(record[0], str):
            logger.warning("A history log holds a line that is no record; what follows it is not read")
            break
        if record == _END:
            for pending_record in pending:
                value = section.apply(value, pending_record)
            pending = []
            present = True
            committed = end
        else:
            pending.append(record)
        offset = end
    return (value if present else _ABSENT), committed


def _write_section(folder: Path, key: str, value) -> None:
    """Make *value* the section *key* the project's log holds: the lines that
    take what is on record to it, added to the log, or, when no line does
    (an entry or a version removed or changed), the log written again."""
    section = _SECTIONS[key]
    path = _log_path(folder, key)
    data = _read_log_bytes(folder, key)
    if data is not None:
        stored, committed = _replay(data, section)
        if stored is not _ABSENT:
            records = section.diff(stored, value)
            if records is not None:
                if records:
                    _append(path, committed, records)
                elif committed < len(data):
                    _truncate(path, committed)
                return
    _rewrite(path, section.records(value))


def _drop_section(folder: Path, key: str) -> None:
    try:
        _log_path(folder, key).unlink()
    except FileNotFoundError:
        pass


def _append(path: Path, committed: int, records: list) -> None:
    """Add *records* and the end of their write after the *committed* bytes,
    dropping anything a write cut short left beyond them."""
    data = b"".join(_line(record) for record in records) + _line(_END)
    with open(path, "r+b") as handle:
        handle.seek(committed)
        handle.truncate()
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _truncate(path: Path, committed: int) -> None:
    with open(path, "r+b") as handle:
        handle.truncate(committed)


def _rewrite(path: Path, records: list) -> None:
    """Write the log anew, swapped in whole as the spec file is. The log and
    its place in the folder are flushed to disk before the spec file is
    written: the log may hold the only copy of a history a spec file held
    until this write."""
    made = not path.parent.is_dir()
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(b"".join(_line(record) for record in records) + _line(_END))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    _flush_folder(path.parent)
    if made:
        _flush_folder(path.parent.parent)


def _flush_folder(folder: Path) -> None:
    """Flush *folder*'s entries to disk, so a file swapped or made in it stays
    after a power loss. Where a folder cannot be opened (Windows), the swap
    stands as the spec file's does."""
    try:
        descriptor = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _same(a, b) -> bool:
    """Whether a section's part on record and the one a write sends are the
    same, as Python compares parsed JSON: an object's members in any order,
    and a number written ``1`` or ``1.0``. A page that sends back what it
    loaded writes numbers its own way, so its history is still the one on
    record. ``true`` and ``1`` also compare equal; no writer turns one into
    the other in a history it was handed."""
    return a == b


def _extends(stored: list, sent: list) -> bool:
    """Whether the list *sent* is the list on record with items added at its end."""
    return len(stored) <= len(sent) and sent[: len(stored)] == stored


class _NodeEntries:
    """``nodeProvenance``: each node's entries, by node id, in ``entries.jsonl``.

    ``["node", id, value]`` puts a node's value in place, ``[]`` for a list
    its entries then fill, and ``["entry", id, entry]`` adds one entry at the
    end of its list. ``["whole", value]`` holds a section that is no object.
    """

    @staticmethod
    def empty():
        return {}

    @staticmethod
    def records(value) -> list:
        if not isinstance(value, dict):
            return [["whole", value]]
        out: list = []
        for node_id, held in value.items():
            if isinstance(held, list):
                out.append(["node", node_id, []])
                out.extend(["entry", node_id, entry] for entry in held)
            else:
                out.append(["node", node_id, held])
        return out

    @staticmethod
    def apply(value, record):
        kind = record[0]
        if kind == "whole" and len(record) == 2:
            return record[1]
        if not isinstance(value, dict) or len(record) != 3:
            return value
        if kind == "node":
            value[record[1]] = record[2]
        elif kind == "entry":
            held = value.get(record[1])
            if isinstance(held, list):
                held.append(record[2])
        return value

    @staticmethod
    def diff(stored, sent) -> Optional[list]:
        """The records that take *stored* to *sent*, or ``None`` when only
        writing the log again does: a node's history gone, or one of its
        entries removed or changed."""
        if not (isinstance(stored, dict) and isinstance(sent, dict)):
            return [] if _same(stored, sent) else None
        if any(node_id not in sent for node_id in stored):
            return None
        out: list = []
        for node_id, held in sent.items():
            before = stored.get(node_id, _ABSENT)
            if isinstance(held, list):
                if isinstance(before, list):
                    if not _extends(before, held):
                        return None
                    out.extend(["entry", node_id, entry] for entry in held[len(before):])
                else:
                    out.append(["node", node_id, []])
                    out.extend(["entry", node_id, entry] for entry in held)
            elif before is _ABSENT or not _same(before, held):
                out.append(["node", node_id, held])
        return out


#: The two lists of the version graph, and the record that adds to each.
_GRAPH_LISTS = {"nodes": "graphNode", "edges": "graphEdge"}


class _Versions:
    """``dataflowProvenance``: the dataflow's versions, in ``versions.jsonl``.

    ``["version", key, trill]`` adds a version, and ``["graphNode", node]``
    and ``["graphEdge", edge]`` add to the graph that orders them.
    ``["field", name, value]`` and ``["graphField", name, value]`` set any
    other member of the section or of its graph (``latest`` among them), and
    put ``{}`` or ``[]`` in place for the records above to fill.
    ``["whole", value]`` holds a section that is no object.
    """

    @staticmethod
    def empty():
        return {}

    @staticmethod
    def _graph_records(graph: dict) -> list:
        out: list = [["field", "graph", {}]]
        for name, held in graph.items():
            if name in _GRAPH_LISTS and isinstance(held, list):
                out.append(["graphField", name, []])
                out.extend([_GRAPH_LISTS[name], item] for item in held)
            else:
                out.append(["graphField", name, held])
        return out

    @classmethod
    def records(cls, value) -> list:
        if not isinstance(value, dict):
            return [["whole", value]]
        out: list = []
        for name, held in value.items():
            if name == "versions" and isinstance(held, dict):
                out.append(["field", "versions", {}])
                out.extend(["version", key, trill] for key, trill in held.items())
            elif name == "graph" and isinstance(held, dict):
                out.extend(cls._graph_records(held))
            else:
                out.append(["field", name, held])
        return out

    @staticmethod
    def apply(value, record):
        kind = record[0]
        if kind == "whole" and len(record) == 2:
            return record[1]
        if not isinstance(value, dict):
            return value
        graph = value.get("graph")
        if kind == "field" and len(record) == 3:
            value[record[1]] = record[2]
        elif kind == "version" and len(record) == 3:
            versions = value.get("versions")
            if isinstance(versions, dict):
                versions[record[1]] = record[2]
        elif kind == "graphField" and len(record) == 3:
            if isinstance(graph, dict):
                graph[record[1]] = record[2]
        elif kind in ("graphNode", "graphEdge") and len(record) == 2:
            name = "nodes" if kind == "graphNode" else "edges"
            held = graph.get(name) if isinstance(graph, dict) else None
            if isinstance(held, list):
                held.append(record[1])
        return value

    @classmethod
    def diff(cls, stored, sent) -> Optional[list]:
        """The records that take *stored* to *sent*, or ``None`` when only
        writing the log again does: a member gone, or a version, a graph node
        or a graph edge removed or changed."""
        if not (isinstance(stored, dict) and isinstance(sent, dict)):
            return [] if _same(stored, sent) else None
        if any(name not in sent for name in stored):
            return None
        out: list = []
        for name, held in sent.items():
            before = stored.get(name, _ABSENT)
            if name == "versions" and isinstance(held, dict):
                if isinstance(before, dict):
                    if any(key not in held or not _same(held[key], trill) for key, trill in before.items()):
                        return None
                    out.extend(["version", key, trill] for key, trill in held.items() if key not in before)
                else:
                    out.append(["field", "versions", {}])
                    out.extend(["version", key, trill] for key, trill in held.items())
            elif name == "graph" and isinstance(held, dict):
                if not isinstance(before, dict):
                    out.extend(cls._graph_records(held))
                    continue
                if any(part not in held for part in before):
                    return None
                for part, items in held.items():
                    had = before.get(part, _ABSENT)
                    if part in _GRAPH_LISTS and isinstance(items, list):
                        if isinstance(had, list):
                            if not _extends(had, items):
                                return None
                            out.extend([_GRAPH_LISTS[part], item] for item in items[len(had):])
                        else:
                            out.append(["graphField", part, []])
                            out.extend([_GRAPH_LISTS[part], item] for item in items)
                    elif had is _ABSENT or not _same(had, items):
                        out.append(["graphField", part, items])
            elif before is _ABSENT or not _same(before, held):
                out.append(["field", name, held])
        return out


_SECTIONS = {"nodeProvenance": _NodeEntries, "dataflowProvenance": _Versions}


class SpecLockOrderError(RuntimeError):
    """A thread asked for a spec lock while holding an uncommitted database write."""


@contextmanager
def spec_write_lock(user_key: str, project_id: str):
    """Serialize read-modify-write of a project's spec across processes.

    Two concurrent saves that both upsert into ``dataflow.datasets`` would
    otherwise race — each reads the spec, mutates its own copy, and the last
    writer clobbers the other's ref (lost update). An exclusive ``flock`` on a
    per-project lock file makes the read+merge+write critical section atomic.

    Serialization has two layers: an in-process threading lock (all platforms,
    same-process threads) and a cross-process file lock (POSIX ``flock`` or, on
    Windows, ``msvcrt.locking``). Only a platform with neither falls back to the
    in-process layer alone. Both live in ``common.file_locks``.

    The lock comes before the database: a thread that has written and not
    committed holds SQLite's write lock, and the holder of this lock needs that
    write lock to index each output it installs, so the two would wait for each
    other until the busy timeout (#909). Such a thread is refused here with
    :class:`SpecLockOrderError` before it waits.
    """
    from utk_curio.backend.extensions import session_holds_write_lock

    if session_holds_write_lock():
        raise SpecLockOrderError(
            f"Spec lock for project {project_id} asked for while this thread "
            "holds an uncommitted database write. Take the spec lock first, "
            "then write to the database, or commit before asking for it."
        )
    d = ensure_project_dir(user_key, project_id)
    with exclusive_lock(
        d / ".spec.lock",
        namespace=_SPEC_LOCK_NAMESPACE,
        key=f"{user_key}/{project_id}",
    ):
        held = _spec_locks_held()
        key = (str(user_key), project_id)
        held.add(key)
        try:
            yield
        finally:
            held.discard(key)


_spec_lock_holder = threading.local()


def _spec_locks_held() -> set:
    """The projects whose spec lock this thread holds."""
    held = getattr(_spec_lock_holder, "projects", None)
    if held is None:
        held = _spec_lock_holder.projects = set()
    return held


def holds_spec_lock(user_key: str, project_id: str) -> bool:
    """Whether this thread holds the project's spec lock. The lock is not
    reentrant, so the one writer of a dataflow (``dataflow_docs.write``), which
    a caller may run under the lock it took for a longer read-modify-write,
    asks for it only when this thread does not hold it already."""
    return (str(user_key), project_id) in _spec_locks_held()


# ---------------------------------------------------------------------------
# Saved outputs: where each one is read
# ---------------------------------------------------------------------------

def _installed_file_for_node(
    user_key: str,
    spec: Optional[dict],
    node_id: str,
) -> Optional[Path]:
    """Resolve an installed dataset file for *node_id* from ``spec.dataflow.datasets``."""
    if not spec or not node_id:
        return None
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict):
        return None

    from utk_curio.backend.app.datasets.install.installer import (
        InstallerError,
        resolve_installed_data_path,
    )
    from utk_curio.backend.app.common.safe_paths import PathTraversalError
    from utk_curio.backend.app.datasets.domain.manifest import ManifestError, load_dataset_manifest
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    for ds_ref in dataflow.get("datasets") or []:
        if not isinstance(ds_ref, dict):
            continue
        if ds_ref.get("producerNodeId") != node_id:
            continue
        dir_name = ds_ref.get("dirName")
        if not dir_name:
            continue
        try:
            installed_dir = dataset_dir(user_key, dir_name)
            manifest = load_dataset_manifest(installed_dir)
            return resolve_installed_data_path(user_key, manifest)
        except (ManifestError, InstallerError, ValueError, PathTraversalError):
            # A stale/broken/crafted ref for this producer shouldn't abort the
            # search (or 500 the whole project load) — a later ref (e.g. a
            # freshly re-installed output) may still resolve. PathTraversalError
            # is a PermissionError, so it must be named explicitly here.
            continue
    return None


def _account_store_computed_file(
    user_key: str,
    project_id: str,
    node_id: str,
) -> Optional[Path]:
    """Resolve a node's computed output in the account store by its deterministic
    dataflow-namespaced dir (``computed.<dataflowId>.<nodeId>@1``).

    Computed outputs are saved to the account store on generation without a
    project ref, so this — not the spec ref — is the authoritative durable copy.
    """
    if not node_id or not project_id:
        return None
    from utk_curio.backend.app.datasets.install.installer import (
        InstallerError,
        computed_dataset_id,
        resolve_installed_data_path,
    )
    from utk_curio.backend.app.common.safe_paths import PathTraversalError
    from utk_curio.backend.app.datasets.domain.manifest import ManifestError, load_dataset_manifest
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    dir_name = f"{computed_dataset_id(node_id, project_id)}@1"
    try:
        installed_dir = dataset_dir(user_key, dir_name)
        manifest = load_dataset_manifest(installed_dir)
        return resolve_installed_data_path(user_key, manifest)
    except (ManifestError, InstallerError, ValueError, PathTraversalError):
        return None


def installed_dataset_file_for_node(
    user_key: str,
    spec: Optional[dict],
    node_id: str,
) -> Optional[Path]:
    """The installed dataset file *node_id* reads, or ``None``.

    Public name for the resolver :func:`_durable_source_for` uses. The dataset
    installers call it to tell "this node's output IS a dataset the account
    already holds" from "this node computed something new". The first needs no
    computed copy: a reload restores its output from the very dataset the node
    reads, so installing one would leave the user with two rows for one file.
    """
    return _installed_file_for_node(user_key, spec, node_id)


def _durable_source_for(
    user_key: str,
    project_id: str,
    ref: OutputRef,
    *,
    spec: Optional[dict],
) -> Optional[Path]:
    """Resolve *ref* to a DURABLE on-disk source a reload can restore from.

    A source is durable when it survives independently of the shared scratch
    cache: the node's computed output in the account store
    (``computed.<dataflowId>.<nodeId>@1`` — the default home for a generated
    output, no project ref required), or a dataset explicitly installed into
    this dataflow (*spec* ``dataflow.datasets``). The shared cache is a
    global, by-filename dir that gets cleared, so it is intentionally NOT a
    durable source.

    This is the single definition of "durable" shared by every reader of a
    saved output, which reads this file in place (:func:`saved_output_file`),
    and by :func:`persisted_output_refs`, which keeps a ref iff a durable
    source exists. Keeping one resolver stops the two from drifting apart —
    e.g. a future durable source added to one but not the other would
    otherwise let save drop an output reload could restore, or record one it
    can't.

    Returns the source ``Path`` or ``None``.
    """
    account = _account_store_computed_file(user_key, project_id, ref.node_id)
    if account is not None and account.is_file():
        return account
    installed = _installed_file_for_node(user_key, spec, ref.node_id)
    if installed is not None and installed.is_file():
        return installed
    return None


def readable_saved_outputs(
    user_key: str,
    project_id: str,
    refs: List[OutputRef],
    *,
    spec: Optional[dict] = None,
) -> List[OutputRef]:
    """The *refs* a reader can read: those whose node's durable source is
    there (:func:`_durable_source_for`), which every reader reads in place
    (:func:`saved_output_file`). Nothing is copied. An output with no source
    left is left out, with a warning in the log.

    Every caller holds the project's spec lock, a project load among them, so
    this never meets the manifest halfway through a save (#941).
    """
    readable = persisted_output_refs(user_key, project_id, refs, spec=spec)
    for ref in refs:
        if ref not in readable:
            logger.warning(
                "Saved output %s of node %s in project %s has no file left to read; "
                "it is left out",
                ref.filename, ref.node_id, project_id,
            )
    return readable


def record_outputs(user_key: str, project_id: str, entries: List[Dict]) -> None:
    """Add *entries* (``{node_id, filename, data_type?, produced_at?}``) to the
    outputs the manifest records, each taking its node's place, and keep the
    rest of the manifest as it is. The caller holds the project's spec lock."""
    path = ensure_project_dir(user_key, project_id) / "manifest.json"
    manifest = read_manifest(user_key, project_id) or {"project_id": project_id, "user_id": user_key}
    nodes = {entry["node_id"] for entry in entries}
    kept = [
        entry for entry in manifest.get("outputs") or []
        if isinstance(entry, dict) and entry.get("node_id") not in nodes
    ]
    manifest["outputs"] = kept + [dict(entry) for entry in entries]
    _write_json_atomically(path, manifest)


def drop_outputs(user_key: str, project_id: str, node_ids) -> bool:
    """Remove the outputs of *node_ids* from those the manifest records, and
    keep the rest of the manifest as it is; whether any went. The caller holds
    the project's spec lock."""
    manifest = read_manifest(user_key, project_id)
    if not manifest:
        return False
    nodes = set(node_ids)
    outputs = manifest.get("outputs") or []
    left = [entry for entry in outputs if not (isinstance(entry, dict) and entry.get("node_id") in nodes)]
    if len(left) == len(outputs):
        return False
    manifest["outputs"] = left
    _write_json_atomically(project_dir(user_key, project_id) / "manifest.json", manifest)
    return True


def persisted_output_refs(
    user_key: str,
    project_id: str,
    refs: List[OutputRef],
    *,
    spec: Optional[dict] = None,
) -> List[OutputRef]:
    """Subset of *refs* that a later reload can restore from a DURABLE source.

    A reload reads an output from its node's dataset in the user store: its
    computed dataset, or a dataset installed into the dataflow (via *spec*
    ``dataflow.datasets``), see :func:`_durable_source_for`. The shared cache
    is a global, by-filename scratch dir that gets cleared and is not a
    per-project guarantee, so it is intentionally *excluded* here: an output
    backed only by the cache silently vanishes once it's evicted.

    The manifest must therefore record only outputs backed by a dataset.
    Recording the raw client list instead lets a swallowed auto-install error
    (or a pruned sink-node dataset) leave a phantom entry the manifest claims
    exists but reload can never restore (issue #144).
    """
    kept: List[OutputRef] = []
    for ref in refs:
        try:
            validate_component(ref.filename, field="output filename")
        except PathTraversalError:
            # An unsafe filename (separator/traversal or a char outside the
            # safe set) can never be durably persisted — the load-path
            # resolvers reject it the same way — so drop it from the manifest
            # instead of letting PathTraversalError (a PermissionError, which
            # the save routes don't catch) bubble up as an HTTP 500 (#144).
            continue
        if _durable_source_for(user_key, project_id, ref, spec=spec) is not None:
            kept.append(ref)
    return kept


@dataclass(frozen=True)
class SavedOutputFile:
    """Where a dataflow's saved output is read: the file its owner's store
    holds for it, and the data type the manifest records."""

    path: Path
    data_type: Optional[str]


def saved_output_file(
    user_key: str,
    project_id: str,
    name: str,
    *,
    spec: Optional[dict] = None,
) -> Optional[SavedOutputFile]:
    """The file that holds the saved output *name* of *project_id*, read in
    place from its owner's store, or None.

    *name* must be a filename the project's manifest records. Its node's
    durable source is the file (:func:`_durable_source_for`): the node's
    computed dataset, or the installed dataset the node reads. Nothing is
    copied, so every reader of a saved output reads the one file the Data
    Catalog keeps.
    """
    try:
        validate_component(name, field="output filename")
    except PathTraversalError:
        return None
    manifest = read_manifest(user_key, project_id) or {}
    for entry in manifest.get("outputs") or []:
        if not isinstance(entry, dict) or entry.get("filename") != name or not entry.get("node_id"):
            continue
        ref = OutputRef(node_id=entry["node_id"], filename=name, data_type=entry.get("data_type"))
        if spec is None:
            spec = read_spec(user_key, project_id)
        source = _durable_source_for(user_key, project_id, ref, spec=spec)
        return SavedOutputFile(source, ref.data_type) if source is not None else None
    return None


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def write_manifest(
    user_key: str,
    project_id: str,
    spec_revision: int,
    refs: List[OutputRef],
    *,
    name: str = "",
    description: Optional[str] = None,
    thumbnail_accent: str = "peach",
    produced_at: Optional[Dict[str, Optional[str]]] = None,
) -> Path:
    """Write ``manifest.json``. *produced_at* maps a node id to when the server
    first saw that node's output; an entry without one counts as oldest."""
    d = ensure_project_dir(user_key, project_id)
    p = d / "manifest.json"
    entries: List[Dict] = []
    data_dir = d / "data"
    for ref in refs:
        fp = data_dir / ref.filename
        entry: Dict = {"node_id": ref.node_id, "filename": ref.filename}
        if getattr(ref, "data_type", None):
            entry["data_type"] = ref.data_type
        stamp = (produced_at or {}).get(ref.node_id)
        if stamp:
            entry["produced_at"] = stamp
        if fp.exists():
            stat = fp.stat()
            entry["size"] = stat.st_size
            entry["mtime"] = stat.st_mtime
        entries.append(entry)
    manifest = {
        "project_id": project_id,
        "user_id": user_key,
        "name": name,
        "description": description,
        "thumbnail_accent": thumbnail_accent,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "spec_revision": spec_revision,
        "outputs": entries,
    }
    _write_json_atomically(p, manifest)
    return p


def mutate_dataflow_datasets(
    user_key: str,
    project_id: str,
    mutate,
    *,
    actor=None,
) -> Optional[tuple[dict, bool]]:
    """Atomically read-modify-write ``dataflow.datasets`` (dev/82).

    The dataset endpoints' section writer: under the per-project spec lock,
    reads the dataflow as it is now (its doc over its file,
    ``dataflow_docs.live``), hands the dict-filtered current refs to *mutate*,
    and writes the list it returns through the dataflow's doc, its one writer.
    So a concurrent mutation of a DIFFERENT dataset can never be lost to a
    stale pre-lock read, and a tab in the dataflow's room gets the change.
    Only the datasets section changes; nodes/edges/agents/packages are
    untouched.

    *mutate* runs while the spec lock is held: it must be a pure list
    transform (no project I/O, nothing that re-acquires the lock). Returning
    ``None`` means "no change": nothing is written. *actor* is who changes
    the refs (``dataflow_docs.Actor``), by default the account.

    Returns ``(spec, changed)``, the spec without its history, or ``None``
    when the project has no spec.
    """
    # The doc writes through this module, so it is imported where it is used.
    from utk_curio.backend.app.collaboration import dataflow_docs

    # Cheap existence check first so we don't create a project dir (and lock
    # file) for a project that doesn't exist.
    if not (project_dir(user_key, project_id) / SPEC_FILE).exists():
        return None
    with spec_write_lock(user_key, project_id):
        spec = dataflow_docs.live(user_key, project_id)
        if not spec:
            return None
        dataflow = spec.setdefault("dataflow", {})
        current = [r for r in (dataflow.get("datasets") or []) if isinstance(r, dict)]
        new_refs = mutate(current)
        if new_refs is None:
            return spec, False
        dataflow["datasets"] = new_refs
        dataflow_docs.write(
            user_key, project_id, spec, actor or dataflow_docs.person(user_key, "datasets"),
        )
        return spec, True


def replace_dataflow_datasets(
    user_key: str,
    project_id: str,
    refs: list[dict],
) -> Optional[dict]:
    """Replace ``dataflow.datasets`` wholesale (dev/81) — a constant-callback
    :func:`mutate_dataflow_datasets`, kept for whole-list writes (seeding,
    carry-overs) where the caller does not depend on the prior list.
    Returns the written spec, or ``None`` when the project has no spec."""
    result = mutate_dataflow_datasets(user_key, project_id, lambda _current: refs)
    return None if result is None else result[0]


def read_manifest(
    user_key: str, project_id: str
) -> Optional[dict]:
    d = project_dir(user_key, project_id)
    p = d / "manifest.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------

def delete_tree(user_key: str, project_id: str) -> None:
    d = project_dir(user_key, project_id)
    if d.exists():
        shutil.rmtree(d)
