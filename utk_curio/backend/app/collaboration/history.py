"""A dataflow's history, kept by the server as points in its doc's log.

The update log of a dataflow's doc (``dataflow_docs.py``) is its one history:
every change, in daily segments, each starting from the doc's state when the
day's first change came. A **point** is a place in that log, with who made the
change there, when, and what it was. ``history/points.jsonl``, beside the spec
file, holds them, one line a point, in the order they were made. The dataflow as
it stood at a point is the doc rebuilt from the point's segment up to it
(:func:`dataflow_at`), and what changed between two points is what their
dataflows differ in.

**Versions.** Every point is one of the dataflow's versions but a run's and an
imported entry's (:data:`UNLISTED`): a node or a connection added or removed, a
point a transaction whoever made it; an agent's change; a person's typing in a
node, once they pause :data:`TYPING_PAUSE_S` or leave its editor; a Map Editor
edit; File > Save; a version put back; a node's code put back. A version's
parent is the version on the canvas when it was made, so after a put-back the
next change branches from the version put back.

**Entries.** A node's run or edit is a note on a point: a run names the kinds of
data it read and returned and its times, an edit its label. Its code is the
node's code at its point, rebuilt, and an edit's code before it is the node's
code where its point starts. A note holds code itself only where the log cannot
give it: a run whose code the doc no longer held when its note came, an imported
entry whose node was gone. A node's next entry descends from the entry in use:
its newest that holds the node's code, else its newest.

**First points.** A dataflow with no points gets them when its doc opens
(:func:`first_points`), in a doc of their own, one transaction and one point a
step: the history it carries in the two sections of the earlier history
(``storage.HISTORY_KEYS``), imported once, every version and then every entry in
time order, with their ids, times and parents; or, when it carries none, the
dataflow with no node, then one point a node, then one a connection.

**Clearing.** The owner may clear the history before a version
(:func:`clear_before`): the points before it go, and so does every log the
remaining ones do not need, and the earlier history set aside.

``dataflow_docs`` hands each change of an open doc to :func:`recorded`, under
the doc's lock. Who may read it
and change it is ``projects/services.py``'s to decide. ``points.jsonl`` is
written under storage's history lock, a leaf.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Optional

from pycrdt import Map, write_message

from utk_curio.backend.app.collaboration import dataflow_docs, doc_mapping, room_state
from utk_curio.backend.app.common import record_clock
from utk_curio.backend.app.projects import storage
from utk_curio.backend.config import COLLAB_NAMESPACE

logger = logging.getLogger(__name__)

#: Beside the spec file, in ``history/``: the points, one JSON line each.
POINTS_FILE = "points.jsonl"
#: What the room's owner and editors are told when the history gains a point
#: or loses some: ``{projectId}``.
CHANGED_EVENT = "history_changed"
#: Seconds a person's typing in a node waits for more before it is a point.
TYPING_PAUSE_S = 10.0
#: The awareness field naming the node whose editor a tab has the focus in.
EDITING_FIELD = "editing"

# The kinds of point.
LOAD = "load"
IMPORTED = "imported"
IMPORTED_ENTRY = "importedEntry"
GRAPH = "graph"
AGENT = "agent"
TYPING = "typing"
EDIT = "edit"
SAVED = "saved"
PUT_BACK = "putBack"
CODE = "code"
RUN = "run"
#: A record that only moves the version on the canvas: where an import left it.
HEAD = "head"
#: The points that are no version of the dataflow.
UNLISTED = frozenset({RUN, IMPORTED_ENTRY, HEAD})

#: How many dataflows rebuilt at points are kept in memory.
CACHE_SIZE = 512

_NOTE_RUN = "run"
_NOTE_EDIT = "edit"
_CONTENT = doc_mapping.CONTENT
_POINT_ID = re.compile(r"^p(\d+)$")


class HistoryError(Exception):
    """A request of the history it cannot do; ``status`` is its HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Refused(HistoryError):
    """A code write refused: the node holds other code than the write began
    from. ``by`` is who changed it last, as a point names a person."""

    def __init__(self, by: Optional[dict]):
        name = (by or {}).get("name") or "Someone"
        super().__init__(f"{name} changed this node after; nothing was undone.", 409)
        self.by = by


# ---------------------------------------------------------------------------
# What a change touched, and its origin
# ---------------------------------------------------------------------------

class Touched:
    """What the doc's transactions since the last commit changed: the nodes
    and connections added and removed, and the nodes whose code changed."""

    __slots__ = ("nodes_added", "nodes_removed", "edges_added", "edges_removed", "contents")

    def __init__(self):
        self.nodes_added: set = set()
        self.nodes_removed: set = set()
        self.edges_added: set = set()
        self.edges_removed: set = set()
        self.contents: set = set()

    def node(self, key: str, action: str) -> None:
        if action == "add":
            if key in self.nodes_removed:
                self.nodes_removed.discard(key)
                self.contents.add(key)
            else:
                self.nodes_added.add(key)
        elif action == "delete":
            if key in self.nodes_added:
                self.nodes_added.discard(key)
            else:
                self.nodes_removed.add(key)
        else:
            self.contents.add(key)

    def edge(self, key: str, action: str) -> None:
        if action == "add":
            if key in self.edges_removed:
                self.edges_removed.discard(key)
            else:
                self.edges_added.add(key)
        elif action == "delete":
            if key in self.edges_added:
                self.edges_added.discard(key)
            else:
                self.edges_removed.add(key)

    def graph(self) -> bool:
        return bool(self.nodes_added or self.nodes_removed or self.edges_added or self.edges_removed)

    def typed(self) -> set:
        """The nodes whose code changed and that neither came nor went."""
        return self.contents - self.nodes_added - self.nodes_removed


class Tab(NamedTuple):
    """The origin of a change a tab sent: its socket and its participant."""

    sid: str
    me: dict


class Change(NamedTuple):
    """One transaction the doc took: its origin (a :class:`Tab`, a writer's
    ``dataflow_docs.Actor``, ``dataflow_docs.SPEC_ORIGIN``), where its
    updates start and end in the log's segment, and what it touched."""

    origin: Any
    start: int
    end: int
    touched: Optional[Touched]


def observe(entry) -> None:
    """Note what each transaction of the open doc *entry* adds, removes and
    types (:attr:`entry.touched`), for :func:`recorded`. The observers live
    as long as the entry holds them (:attr:`entry.watching`): pycrdt drops an
    observer once its type's object and its subscription are gone. Each
    node's code is known by its digest as the doc holds it now
    (:attr:`entry.codes`), so a change knows the code it replaced."""
    entry.touched = Touched()
    nodes = entry.doc.get("nodes", type=Map)
    edges = entry.doc.get("edges", type=Map)
    entry.codes = {}
    for key in list(nodes.keys()):
        held = _code_in(entry.doc, str(key))
        if held is not None:
            entry.codes[str(key)] = _sha(held)

    def on_nodes(events) -> None:
        touched = entry.touched
        if touched is None:
            return
        for event in events:
            path = list(event.path)
            keys = getattr(event, "keys", None) or {}
            if not path:
                for key, change in keys.items():
                    touched.node(str(key), (change or {}).get("action", ""))
            elif len(path) >= 2 and path[1] == _CONTENT:
                touched.contents.add(str(path[0]))
            elif len(path) == 1 and _CONTENT in keys:
                touched.contents.add(str(path[0]))

    def on_edges(event) -> None:
        touched = entry.touched
        if touched is None:
            return
        for key, change in (getattr(event, "keys", None) or {}).items():
            touched.edge(str(key), (change or {}).get("action", ""))

    entry.watching = (nodes, edges, nodes.observe_deep(on_nodes), edges.observe(on_edges))


def take_touched(entry) -> Optional[Touched]:
    """What the doc's transactions touched since the last commit, and a fresh
    note for the next ones."""
    touched = entry.touched
    if touched is not None:
        entry.touched = Touched()
    return touched


def _by(origin) -> Optional[dict]:
    """Who made a change, as a point names them."""
    if isinstance(origin, Tab):
        me = origin.me or {}
        return {"kind": "person", "account": str(me.get("user_id")), "name": me.get("name") or me.get("username")}
    if isinstance(origin, dataflow_docs.Actor):
        by = {"kind": origin.kind, "account": origin.by}
        if origin.agent:
            by["agent"] = origin.agent
        return by
    return None


def _account(by: Optional[dict]) -> str:
    return str((by or {}).get("account"))


# ---------------------------------------------------------------------------
# The points file
# ---------------------------------------------------------------------------

def _folder(user_key: str, project_id: str) -> Path:
    return storage.project_dir(user_key, project_id)


def _points_path(folder: Path) -> Path:
    return folder / storage.HISTORY_DIR / POINTS_FILE


def _read_points(folder: Path) -> list[dict]:
    """The points in *folder*, in the order they were made. A line cut short,
    by a crash in the middle of a write, ends them."""
    try:
        data = _points_path(folder).read_bytes()
    except FileNotFoundError:
        return []
    out: list[dict] = []
    for line in data.split(b"\n"):
        if not line.strip():
            continue
        try:
            point = json.loads(line)
        except ValueError:
            break
        if isinstance(point, dict) and isinstance(point.get("id"), str):
            out.append(point)
    return out


def _line(point: dict) -> bytes:
    return json.dumps(point, separators=(",", ":")).encode("ascii") + b"\n"


def _append_points(user_key: str, project_id: str, points: list[dict]) -> None:
    """Add *points* at the end of the file, a line each, dropping what a write
    cut short left after its last whole line."""
    path = _points_path(_folder(user_key, project_id))
    with storage.history_lock(user_key, project_id):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab+") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size:
                handle.seek(max(0, size - 1))
                if handle.read(1) != b"\n":
                    handle.seek(0)
                    data = handle.read()
                    handle.truncate(data.rfind(b"\n") + 1)
            handle.seek(0, os.SEEK_END)
            handle.write(b"".join(_line(point) for point in points))
            handle.flush()
            os.fsync(handle.fileno())


def _write_points(user_key: str, project_id: str, points: list[dict]) -> None:
    """Write the points anew, swapped in whole."""
    path = _points_path(_folder(user_key, project_id))
    with storage.history_lock(user_key, project_id):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "wb") as handle:
                handle.write(b"".join(_line(point) for point in points))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()


def has_points(user_key: str, project_id: str) -> bool:
    """Whether the dataflow's history is points: from its first open while the
    history records."""
    try:
        return _points_path(_folder(user_key, project_id)).is_file()
    except (OSError, ValueError):
        return False


def points(user_key: str, project_id: str) -> list[dict]:
    """The dataflow's points, in the order they were made."""
    return _read_points(_folder(user_key, project_id))


def _listed(point: dict) -> bool:
    return point.get("kind") not in UNLISTED


def head_of(points_: Iterable[dict]) -> Optional[str]:
    """The version on the canvas: the newest, but where a :data:`HEAD`
    record moved it since."""
    head = None
    for point in points_:
        if point.get("kind") == HEAD:
            head = point.get("head")
        elif _listed(point):
            head = point["id"]
    return head


# ---------------------------------------------------------------------------
# The state of an open doc's history
# ---------------------------------------------------------------------------

class _Typing:
    """One person's typing in one node, since its last point: *parent* is the
    digest of the code it began from."""

    __slots__ = ("node", "by", "sid", "doc", "day", "start", "end", "last", "parent")

    def __init__(self, node: str, by: dict, sid: Optional[str], doc: str, day: str, start: int,
                 parent: Optional[str] = None):
        self.node, self.by, self.sid = node, by, sid
        self.doc, self.day, self.start, self.end = doc, day, start, start
        self.last = 0.0
        self.parent = parent


class _State:
    """An open doc's history in memory: the version on the canvas, the next
    ids, each node's entries' codes, the typing under way and who last
    changed each node's code. Guarded by the doc's lock."""

    def __init__(self, points_: list[dict]):
        self.ids: set = set()
        self.number = 0
        self.note_id = 0
        self.head: Optional[str] = None
        #: node -> [(note id, code's digest)], in the order they were made.
        self.notes: dict[str, list[tuple[int, str]]] = {}
        self.typing: dict[tuple[str, str], _Typing] = {}
        self.authors: dict[str, Optional[dict]] = {}
        #: When the oldest typing is due, read without the doc's lock.
        self.due: Optional[float] = None
        for point in points_:
            self.take(point)

    def take(self, point: dict) -> None:
        self.ids.add(point["id"])
        match = _POINT_ID.match(point["id"])
        if match:
            self.number = max(self.number, int(match.group(1)))
        if point.get("kind") == HEAD:
            self.head = point.get("head")
        elif _listed(point):
            self.head = point["id"]
        for note in point.get("notes") or []:
            if isinstance(note.get("id"), int):
                self.note_id = max(self.note_id, note["id"])
                self.notes.setdefault(str(note.get("node")), []).append((note["id"], note.get("sha") or ""))

    def next_id(self) -> str:
        while True:
            self.number += 1
            candidate = f"p{self.number}"
            if candidate not in self.ids:
                return candidate

    def next_note(self) -> int:
        self.note_id += 1
        return self.note_id

    def current(self, node: str, sha: Optional[str]) -> Optional[int]:
        """The entry a node's next one descends from: its newest that holds
        *sha*'s code, else its newest."""
        notes = self.notes.get(node) or []
        same = [note_id for note_id, digest in notes if sha is not None and digest == sha]
        if same:
            return max(same)
        return max((note_id for note_id, _ in notes), default=None)

    def retime(self) -> None:
        self.due = min((typing.last for typing in self.typing.values()), default=None)
        if self.due is not None:
            self.due += TYPING_PAUSE_S


def _state(entry) -> _State:
    if not isinstance(entry.history, _State):
        entry.history = _State(_read_points(entry.folder()))
    return entry.history


def _kept(entry) -> Optional[_State]:
    """The open doc's history state, if it has one in memory."""
    return entry.history if isinstance(entry.history, _State) else None


def _sha(code: Optional[str]) -> str:
    return hashlib.sha256((code or "").encode("utf-8")).hexdigest()[:16]


def _now_ms() -> int:
    return int(record_clock.utc_now().timestamp() * 1000)


def _now_text() -> str:
    return record_clock.utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _code_in(doc, node_id: str) -> Optional[str]:
    """The code of the doc's node *node_id*, or ``None`` when it has none."""
    nodes = doc.get("nodes", type=Map)
    if node_id not in nodes:
        return None
    node = nodes[node_id]
    if not isinstance(node, Map) or _CONTENT not in node:
        return ""
    held = node[_CONTENT]
    if isinstance(held, str):
        # Code that is no text, held as its JSON.
        value = doc_mapping.decode(held)
        return value if isinstance(value, str) else json.dumps(value)
    return str(held)


def _tell(entry) -> None:
    """Tell the doc's owner's and editors' tabs the history changed. A
    watcher's tab is told nothing: the history is not a watcher's to read."""
    sio = dataflow_docs._socketio()
    if sio is None:
        return
    room = room_state.room_for(entry.project_id)
    for sid in list(entry.tabs):
        me = room_state.participant(room, sid)
        if me is not None and me.get("role") in room_state.EDIT_ROLES:
            sio.emit(CHANGED_EVENT, {"projectId": entry.project_id}, to=sid, namespace=COLLAB_NAMESPACE)


def _first_made(entry) -> bool:
    """Make the open doc's first points if its dataflow has none, as when its
    history was dropped while it was open; whether it did, or tried and the
    history is off for this open doc."""
    if entry.history is False:
        return True
    if _points_path(entry.folder()).exists():
        return False
    if not first_points(entry):
        entry.history = False
    return True


def _add(entry, point: dict) -> dict:
    """Add *point*, with its id, time and parent, to the open doc's history."""
    _first_made(entry)
    if entry.history is False:
        raise HistoryError("This dataflow's history could not be started.", 409)
    state = _state(entry)
    point = dict(point)
    point.setdefault("id", state.next_id())
    point.setdefault("at", _now_ms())
    if _listed(point) and "parent" not in point:
        point["parent"] = state.head
    _append_points(entry.user_key, entry.project_id, [point])
    state.take(point)
    _tell(entry)
    return point


def _place(entry, start: int, end: int) -> dict:
    return {"doc": entry.doc_id, "day": entry.segment, "start": start, "end": end}


# ---------------------------------------------------------------------------
# Recording an open doc's changes
# ---------------------------------------------------------------------------

def _graph_label(touched: Touched) -> str:
    """What a change to the graph was, as a version is named."""

    def counted(n: int, one: str, many: str, verb: str) -> str:
        return f"{one} {verb}" if n == 1 else f"{n} {many} {verb}"

    added, removed = len(touched.nodes_added), len(touched.nodes_removed)
    if added and removed:
        return "Nodes added and deleted"
    if added:
        return counted(added, "Node", "nodes", "added")
    if removed:
        return counted(removed, "Node", "nodes", "deleted")
    added, removed = len(touched.edges_added), len(touched.edges_removed)
    if added and removed:
        return "Connections changed"
    if added:
        return counted(added, "Connection", "connections", "added")
    return counted(removed, "Connection", "connections", "deleted")


def recorded(entry, changes: list[Change], *, point: Optional[dict] = None) -> None:
    """Record each of *changes*, the transactions the open doc *entry* just
    logged, in the order it took them, as the history's points: one point a
    transaction and its origin. A writer's own *point* names a change in place
    of the point its kind would make. Under the doc's lock. A history that
    cannot be written never fails the change: it is logged and dropped. A
    dataflow with no points gets its first, which hold the change."""
    try:
        if _first_made(entry):
            return
    except Exception:  # noqa: BLE001 - the change is the doc's already
        logger.exception("dataflow %s: its first history points could not be made", entry.project_id)
        return
    for change in changes:
        try:
            _record(entry, change, point)
        except Exception:  # noqa: BLE001 - the change is the doc's already
            logger.exception("dataflow %s: a change could not be added to its history", entry.project_id)


def _record(entry, change: Change, point: Optional[dict]) -> None:
    touched = change.touched or Touched()
    # The digest of the code each node held before the change: an entry the
    # change makes descends from the newest entry that holds it.
    codes = getattr(entry, "codes", None) or {}
    before = {node: codes.get(node) for node in touched.contents}
    try:
        _record_change(entry, change, point, touched, before)
    finally:
        _remember_codes(entry, touched)


def _remember_codes(entry, touched: Touched) -> None:
    """The digests of the codes the change left (:attr:`entry.codes`)."""
    codes = getattr(entry, "codes", None)
    if not isinstance(codes, dict):
        codes = entry.codes = {}
    for node in touched.nodes_removed:
        codes.pop(node, None)
    for node in touched.contents | touched.nodes_added:
        held = _code_in(entry.doc, node)
        if held is None:
            codes.pop(node, None)
        else:
            codes[node] = _sha(held)


def _record_change(entry, change: Change, point: Optional[dict], touched: Touched,
                   before: dict[str, Optional[str]]) -> None:
    state = _state(entry)
    by = (point or {}).get("by") or _by(change.origin)
    for node in touched.contents:
        state.authors[node] = by
    if point is not None:
        made = dict(point)
        made.setdefault("by", by)
        _add(entry, {**made, **_place(entry, change.start, change.end)})
        return
    if isinstance(change.origin, Tab):
        if touched.graph():
            _add(entry, {"kind": GRAPH, "what": _graph_label(touched), "by": by,
                         **_place(entry, change.start, change.end)})
        for node in sorted(touched.typed()):
            _typed(entry, change.origin, by, node, change, before.get(node))
        return
    if isinstance(change.origin, dataflow_docs.Actor) and change.origin.kind == dataflow_docs.AGENT:
        if not (touched.graph() or touched.typed()):
            return
        notes = []
        for node in sorted(touched.typed()):
            code = _code_in(entry.doc, node)
            sha = _sha(code)
            notes.append({
                "id": state.next_note(), "node": node, "kind": _NOTE_EDIT,
                "parentId": state.current(node, before.get(node)), "label": "", "inputs": [], "outputs": [],
                "startTime": _now_text(), "endTime": _now_text(), "sha": sha, "chars": len(code or ""),
            })
        _add(entry, {"kind": AGENT, "what": "", "by": by, **_place(entry, change.start, change.end),
                     **({"notes": notes} if notes else {})})
        return
    if touched.graph():
        _add(entry, {"kind": GRAPH, "what": _graph_label(touched), "by": by,
                     **_place(entry, change.start, change.end)})


def _typed(entry, tab: Tab, by: dict, node: str, change: Change, parent: Optional[str]) -> None:
    """Note a person's typing in *node*, which began from the code whose
    digest is *parent*: their point waits for a pause."""
    state = _state(entry)
    key = (node, _account(by))
    typing = state.typing.get(key)
    if typing is not None and (typing.doc != entry.doc_id or typing.day != entry.segment):
        _close(entry, key)
        typing = None
    if typing is None:
        typing = state.typing[key] = _Typing(node, by, tab.sid, entry.doc_id, entry.segment, change.start,
                                             parent=parent)
    typing.end = change.end
    typing.sid = tab.sid
    typing.last = dataflow_docs._clock()
    state.retime()


def _close(entry, key: tuple[str, str], *, kind: str = TYPING, label: Optional[str] = None,
           end: Optional[int] = None) -> Optional[dict]:
    """Make one person's typing in one node its point: a version named after
    them, with an edit entry on the node, which descends from the newest
    entry that holds the code the typing began from. Typing that left the
    code as it began is no change, and no point."""
    state = _state(entry)
    typing = state.typing.pop(key, None)
    state.retime()
    if typing is None:
        return None
    code = _code_in(entry.doc, typing.node)
    sha = _sha(code)
    if kind == TYPING and typing.parent is not None and sha == typing.parent:
        return None
    name = (typing.by or {}).get("name") or "Someone"
    what = label if label is not None else f"{name} edited"
    at = _now_text()
    note = {
        "id": state.next_note(), "node": typing.node, "kind": _NOTE_EDIT,
        "parentId": state.current(typing.node, typing.parent), "label": what, "inputs": [], "outputs": [],
        "startTime": at, "endTime": at, "sha": sha, "chars": len(code or ""),
    }
    return _add(entry, {
        "kind": kind, "what": what, "by": typing.by, "doc": typing.doc, "day": typing.day,
        "start": typing.start, "end": typing.end if end is None else end, "notes": [note],
    })


def close_typing(entry, *, sid: Optional[str] = None) -> None:
    """End the typing under way in the open doc *entry*: all of it, or that
    the socket *sid* typed last. Under the doc's lock."""
    state = _kept(entry)
    if state is None:
        return
    for key, typing in list(state.typing.items()):
        if sid is None or typing.sid == sid:
            _close(entry, key)


def next_due(entry) -> Optional[float]:
    """When the open doc's oldest typing is due as a point (its clock),
    read without its lock."""
    state = _kept(entry)
    return state.due if state is not None else None


def typing_due(entry, now: float) -> None:
    """Make each typing that paused :data:`TYPING_PAUSE_S` its point. Under
    the doc's lock."""
    state = _kept(entry)
    if state is None:
        return
    for key, typing in list(state.typing.items()):
        if now - typing.last >= TYPING_PAUSE_S:
            _close(entry, key)


def editing(entry, sid: str) -> dict[int, Optional[str]]:
    """The node each of the socket *sid*'s awareness states has the editor of
    in focus, by client id."""
    out: dict[int, Optional[str]] = {}
    states = entry.awareness.states
    for client, owner in entry.awareness_owners.items():
        if owner == sid:
            state = states.get(client) or {}
            out[client] = state.get(EDITING_FIELD) if isinstance(state, dict) else None
    return out


def left_editors(entry, sid: str, me: dict, before: dict[int, Optional[str]]) -> None:
    """End the typing of each node whose editor the socket *sid* left, its
    awareness having been *before*."""
    now = editing(entry, sid)
    state = _kept(entry)
    if state is None:
        return
    account = str((me or {}).get("user_id"))
    for client, node in before.items():
        if node and now.get(client) != node:
            _close(entry, (str(node), account))


# ---------------------------------------------------------------------------
# A dataflow's first points
# ---------------------------------------------------------------------------

class _Built:
    """A doc of its own, built a step at a time, each step its log's next
    updates: the history's first points."""

    def __init__(self, doc_id: str, fields: dict):
        self.doc_id = doc_id
        self.doc = doc_mapping.new_doc()
        doc_mapping.dataflow_to_doc(fields, self.doc, doc_id=doc_id)
        self.checkpoint = self.doc.get_update()
        self.records = bytearray()
        self._updates: list[bytes] = []
        self.doc.observe(lambda event: self._updates.append(event.update))
        self.current = doc_mapping.doc_to_dataflow(self.doc)

    def step(self, target: dict) -> tuple[int, int]:
        """Make the doc *target*, one transaction; where its updates start and
        end. A step that fails partway leaves in the log what it changed, as
        the doc holds it, since a transaction is not undone."""
        start = len(self.records)
        try:
            with self.doc.transaction(origin=doc_mapping.TRILL_ORIGIN):
                doc_mapping.apply_dataflow(self.doc, self.current, target)
        finally:
            for update in self._updates:
                self.records += write_message(update)
            self._updates = []
            self.current = doc_mapping.doc_to_dataflow(self.doc)
        return start, len(self.records)

    def code(self, node_id: str) -> Optional[str]:
        return _code_in(self.doc, node_id)


def _holds_history(sections: dict) -> bool:
    versions = (sections.get("dataflowProvenance") or {}) if isinstance(sections, dict) else {}
    entries = sections.get("nodeProvenance") if isinstance(sections, dict) else None
    return bool(isinstance(versions, dict) and versions.get("versions")) or bool(
        isinstance(entries, dict) and any(isinstance(records, list) and records for records in entries.values())
    )


def first_points(entry) -> bool:
    """Give the open doc's dataflow its first points, if it has none: the
    history it carries, imported once, or the dataflow as its doc holds it, a
    node and then a connection at a time. Each in a doc of its own, whose log
    holds a step's change between each point and the next. The file of points
    is written last, whole, so a stop before it leaves the dataflow with no
    points, to be given them on its next open. A history that cannot be
    imported leaves its sections where they are and starts from the
    dataflow. Under the doc's lock; whether the dataflow has points."""
    folder = entry.folder()
    if _points_path(folder).exists():
        return True
    try:
        sections = storage.history_sections(entry.user_key, entry.project_id)
        dataflow = doc_mapping.doc_to_dataflow(entry.doc)
        doc_id = uuid.uuid4().hex
        day = dataflow_docs._today()
        imported = False
        if _holds_history(sections):
            try:
                built, made = _imported(sections, dataflow, doc_id)
                imported = True
            except Exception:  # noqa: BLE001 - the history starts from the dataflow then
                logger.exception("dataflow %s: its earlier history could not be imported", entry.project_id)
        if not imported:
            built, made = _loaded(dataflow, doc_id)
        dataflow_docs.write_segment(folder, doc_id, day, built.checkpoint, bytes(built.records))
        for point in made:
            point.setdefault("doc", doc_id)
            point.setdefault("day", day)
        _write_points(entry.user_key, entry.project_id, made)
        if sections and (imported or not _holds_history(sections)):
            storage.set_history_aside(entry.user_key, entry.project_id)
        entry.history = None
        return True
    except Exception:  # noqa: BLE001 - a doc opens whatever its history does
        logger.exception("dataflow %s: its first history points could not be made", entry.project_id)
        return False


def _loaded(dataflow: dict, doc_id: str) -> tuple[_Built, list[dict]]:
    """The points of a dataflow with no history: the dataflow with no node,
    then one a node, then one a connection, whose ends it holds by then."""
    fields = {name: value for name, value in dataflow.items() if name not in ("nodes", "edges")}
    built = _Built(doc_id, fields)
    at = _now_ms()
    made: list[dict] = [{"id": "p1", "kind": LOAD, "what": "", "parent": None, "at": at, "by": None,
                         "start": 0, "end": 0}]
    nodes = [node for node in dataflow.get("nodes") or [] if isinstance(node, dict)]
    edges = [edge for edge in dataflow.get("edges") or [] if isinstance(edge, dict)]
    target = {**fields, "nodes": [], "edges": []}
    for node in nodes:
        target = {**target, "nodes": [*target["nodes"], node]}
        start, end = built.step(target)
        made.append({"id": f"p{len(made) + 1}", "kind": LOAD, "what": "Node added", "parent": made[-1]["id"],
                     "at": at, "by": None, "start": start, "end": end})
    present = {node.get("id") for node in nodes}
    for edge in edges:
        if edge.get("source") not in present or edge.get("target") not in present:
            continue
        target = {**target, "edges": [*target["edges"], edge]}
        start, end = built.step(target)
        made.append({"id": f"p{len(made) + 1}", "kind": LOAD, "what": "Connection added",
                     "parent": made[-1]["id"], "at": at, "by": None, "start": start, "end": end})
    return built, made


_MONTHS = {name: i for i, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_FILED_AT = re.compile(r"^([A-Za-z]{3})\w*\.? (\d{1,2}) (\d{4}) (\d{1,2}):(\d{1,2}):(\d{1,2})$")


def _entry_time(text: Any) -> Optional[int]:
    """When an entry of the earlier history was filed, in milliseconds, read
    as UTC: the page filed it as its own clock's ``Oct 28 2026 14:5:3``, with
    no zone, or as ISO 8601."""
    if not isinstance(text, str) or not text.strip():
        return None
    match = _FILED_AT.match(text.strip())
    if match and match.group(1).lower() in _MONTHS:
        try:
            moment = datetime(int(match.group(3)), _MONTHS[match.group(1).lower()], int(match.group(2)),
                              int(match.group(4)), int(match.group(5)), int(match.group(6)), tzinfo=timezone.utc)
        except ValueError:
            return None
        return int(moment.timestamp() * 1000)
    try:
        moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def _imported(sections: dict, dataflow: dict, doc_id: str) -> tuple[_Built, list[dict]]:
    """The points of the earlier history *sections*: every version, then every
    entry, in the order they were made, each the transaction that makes the
    doc hold it and a point with its id, time and parent. A version the doc's
    layout has no place for is left out, its children taking its parent; an
    entry whose node the doc holds then sets that node's code, and one whose
    node it does not keeps its code."""
    from utk_curio.backend.app.projects.node_provenance import rekey_node_provenance

    versions_section = sections.get("dataflowProvenance") if isinstance(sections.get("dataflowProvenance"), dict) else {}
    graph = versions_section.get("graph") if isinstance(versions_section.get("graph"), dict) else {}
    versions = versions_section.get("versions") if isinstance(versions_section.get("versions"), dict) else {}
    graph_nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]
    order = [node["id"] for node in graph_nodes if node.get("id") in versions]
    order += [key for key in versions if key not in order]
    times = {node["id"]: node.get("timestamp") for node in graph_nodes if node.get("id") in versions}
    parents: dict[str, str] = {}
    labels: dict[str, str] = {}
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        target, source = edge.get("target"), edge.get("source")
        if target in versions and source in versions and target not in parents and source != target:
            parents[target] = source
            labels[target] = edge.get("label") or ""

    node_ids: list[str] = [str(node.get("id")) for node in dataflow.get("nodes") or [] if isinstance(node, dict)]
    for key in order:
        trill = versions.get(key)
        flow = trill.get("dataflow") if isinstance(trill, dict) and isinstance(trill.get("dataflow"), dict) else {}
        node_ids += [str(node.get("id")) for node in flow.get("nodes") or [] if isinstance(node, dict)]
    saved = sections.get("nodeProvenance") if isinstance(sections.get("nodeProvenance"), dict) else {}
    keyed = rekey_node_provenance(saved, list(dict.fromkeys(node_ids)))
    entries = sorted(
        ((node, record) for node, records in keyed.items() for record in records if isinstance(record, dict)),
        key=lambda item: item[1].get("id") if isinstance(item[1].get("id"), (int, float)) else 0,
    )

    # One timeline: versions in the order they were made, each entry after
    # the last version made before it or with it.
    timeline: list[tuple[str, Any]] = []
    last_entry_at: Optional[int] = None
    pending = list(entries)
    for key in order:
        version_at = _version_time(times.get(key), versions.get(key))
        while pending:
            at = _entry_time(pending[0][1].get("startTime"))
            at = at if at is not None else last_entry_at
            if version_at is None or at is None or at >= version_at:
                break
            last_entry_at = at
            timeline.append(("entry", pending.pop(0)))
        timeline.append(("version", key))
    timeline += [("entry", item) for item in pending]

    built = _Built(doc_id, {})
    made: list[dict] = []
    kept: dict[str, Optional[str]] = {}
    number = 0
    taken = set(versions)
    known = [_version_time(times.get(key), versions.get(key)) for key in order]
    at_last = next((at for at in known if at is not None), None) or _now_ms()
    note_ids = [record.get("id") for _node, record in entries]
    whole = [int(i) for i in note_ids if isinstance(i, (int, float)) and not isinstance(i, bool)
             and float(i).is_integer()]
    spare = max(whole, default=0)

    def note_id(value: Any) -> int:
        nonlocal spare
        if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer():
            return int(value)
        spare += 1
        return spare

    def next_id() -> str:
        nonlocal number
        while True:
            number += 1
            if f"p{number}" not in taken:
                taken.add(f"p{number}")
                return f"p{number}"

    for kind, item in timeline:
        if kind == "version":
            key = item
            trill = versions.get(key)
            flow = trill.get("dataflow") if isinstance(trill, dict) else None
            target = doc_mapping.owned(flow) if isinstance(flow, dict) else None
            parent = parents.get(key)
            while parent is not None and parent not in kept:
                parent = parents.get(parent)
            if target is None or not doc_mapping.mappable(target):
                logger.warning("an earlier version (%s) has no place in the doc's layout; it is left out", key)
                parents[key] = parent
                continue
            try:
                start, end = built.step(target)
            except doc_mapping.DocMappingError:
                logger.warning("an earlier version (%s) has no place in the doc's layout; it is left out", key)
                parents[key] = parent
                continue
            kept[key] = key
            at = _version_time(times.get(key), trill)
            at_last = at if at is not None else at_last
            made.append({"id": key, "kind": IMPORTED, "what": labels.get(key, "") if parent is not None else "",
                         "parent": parent, "at": at_last, "by": None, "start": start, "end": end})
            continue
        node, record = item
        code = record.get("code") if isinstance(record.get("code"), str) else ""
        at = _entry_time(record.get("startTime"))
        at_last = at if at is not None else at_last
        start = end = len(built.records)
        holds = built.code(node)
        if holds is not None and holds != code:
            current = built.current
            target = copy.deepcopy(current)
            for held in target.get("nodes") or []:
                if isinstance(held, dict) and held.get("id") == node:
                    held["content"] = code
            try:
                start, end = built.step(target)
            except doc_mapping.DocMappingError:
                start = end = len(built.records)
        note = {
            "id": note_id(record.get("id")), "node": node,
            "kind": _NOTE_EDIT if record.get("kind") == "edit" else _NOTE_RUN,
            "parentId": _whole(record.get("parentId")),
            "inputs": record.get("inputs") if isinstance(record.get("inputs"), list) else [],
            "outputs": record.get("outputs") if isinstance(record.get("outputs"), list) else [],
            "startTime": record.get("startTime") or "", "endTime": record.get("endTime") or "",
            "sha": _sha(code), "chars": len(code),
        }
        if isinstance(record.get("label"), str):
            note["label"] = record["label"]
        if isinstance(record.get("before"), str):
            note["before"] = record["before"]
        if holds is None:
            note["code"] = code
        made.append({"id": next_id(), "kind": IMPORTED_ENTRY, "what": "", "at": at_last, "by": None,
                     "start": start, "end": end, "notes": [note]})

    latest = versions_section.get("latest")
    listed = [point["id"] for point in made if point["kind"] == IMPORTED]
    head = latest if latest in kept else (listed[-1] if listed else None)
    if head is not None and head_of(made) != head:
        made.append({"id": next_id(), "kind": HEAD, "head": head, "at": at_last, "start": len(built.records),
                     "end": len(built.records)})
    return built, made


def _whole(value: Any) -> Optional[int]:
    """*value* as a whole number, or ``None`` when it is none."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer():
        return int(value)
    return None


def _version_time(timestamp: Any, trill: Any) -> Optional[int]:
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        return int(timestamp)
    flow = trill.get("dataflow") if isinstance(trill, dict) else None
    stamp = flow.get("timestamp") if isinstance(flow, dict) else None
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        return int(stamp)
    return None


# ---------------------------------------------------------------------------
# Reading the history
# ---------------------------------------------------------------------------

_cache: "OrderedDict[tuple, Optional[dict]]" = OrderedDict()
_cache_lock = threading.Lock()


def _forget(folder: Optional[Path] = None) -> None:
    with _cache_lock:
        if folder is None:
            _cache.clear()
            return
        for key in [key for key in _cache if key[0] == str(folder)]:
            del _cache[key]


def _dataflows_at(folder: Path, places: Iterable[tuple[str, str, int]]) -> dict[tuple[str, str, int], Optional[dict]]:
    """The dataflow at each place (doc, day, offset) in *folder*'s logs, each
    segment replayed once for all its places. ``None`` where the log cannot
    be read."""
    out: dict = {}
    wanted: dict[tuple[str, str], set] = {}
    with _cache_lock:
        for place in places:
            key = (str(folder), *place)
            if key in _cache:
                _cache.move_to_end(key)
                out[place] = _cache[key]
            else:
                wanted.setdefault((place[0], place[1]), set()).add(place[2])
    for (doc_id, day), offsets in wanted.items():
        found = _replay(folder, doc_id, day, sorted(offsets))
        with _cache_lock:
            for offset, flow in found.items():
                out[(doc_id, day, offset)] = flow
                _cache[(str(folder), doc_id, day, offset)] = flow
                while len(_cache) > CACHE_SIZE:
                    _cache.popitem(last=False)
    return out


def _replay(folder: Path, doc_id: str, day: str, offsets: list[int]) -> dict[int, Optional[dict]]:
    try:
        checkpoint, records = dataflow_docs.segment_in(folder, doc_id, day)
        doc = doc_mapping.new_doc()
        doc.apply_update(checkpoint)
    except (OSError, ValueError, RuntimeError):
        return {offset: None for offset in offsets}
    out: dict[int, Optional[dict]] = {}
    k = 0
    for end, record in records:
        while k < len(offsets) and offsets[k] < end:
            out[offsets[k]] = doc_mapping.doc_to_dataflow(doc)
            k += 1
        if k == len(offsets):
            return out
        try:
            doc.apply_update(record)
        except ValueError:
            break
    flow = doc_mapping.doc_to_dataflow(doc)
    for offset in offsets[k:]:
        out[offset] = flow
    return out


def dataflow_at(user_key: str, project_id: str, point_id: str) -> Optional[dict]:
    """The dataflow as it stood at the point *point_id*, the part the doc
    holds; ``None`` for no such point, or one whose log cannot be read."""
    folder = _folder(user_key, project_id)
    point = next((p for p in _read_points(folder) if p["id"] == point_id), None)
    if point is None or "doc" not in point:
        return None
    place = (point["doc"], point["day"], point["end"])
    return copy.deepcopy(_dataflows_at(folder, [place]).get(place))


def _node_code(flow: Optional[dict], node_id: str) -> Optional[str]:
    if not isinstance(flow, dict):
        return None
    for node in flow.get("nodes") or []:
        if isinstance(node, dict) and node.get("id") == node_id:
            content = node.get("content")
            return content if isinstance(content, str) else ("" if content is None else json.dumps(content))
    return None


def _preview(flow: Optional[dict]) -> Optional[dict]:
    """A version's graph as its thumbnail draws it."""
    if not isinstance(flow, dict):
        return None
    return {
        "nodes": [
            {"id": node.get("id"), "type": node.get("type"), "x": node.get("x", 0), "y": node.get("y", 0),
             "w": node.get("width"), "h": node.get("height")}
            for node in flow.get("nodes") or [] if isinstance(node, dict)
        ],
        "edges": [
            {"source": edge.get("source"), "target": edge.get("target")}
            for edge in flow.get("edges") or [] if isinstance(edge, dict)
        ],
    }


def _opened(user_key: str, project_id: str) -> None:
    """Open the dataflow's doc if it has no points yet, which gives it its
    first ones: a read can come before any tab opened it."""
    if not has_points(user_key, project_id):
        with _held(user_key, project_id):
            pass


def versions(user_key: str, project_id: str) -> dict:
    """The dataflow's versions, in the order they were made, each with its
    graph (``preview``), and the one on the canvas (``head``)."""
    _opened(user_key, project_id)
    folder = _folder(user_key, project_id)
    points_ = _read_points(folder)
    listed = [point for point in points_ if _listed(point) and "doc" in point]
    flows = _dataflows_at(folder, [(point["doc"], point["day"], point["end"]) for point in listed])
    out = []
    for point in listed:
        row = {name: point[name] for name in ("id", "parent", "at", "by", "kind", "what", "restores") if name in point}
        row["preview"] = _preview(flows.get((point["doc"], point["day"], point["end"])))
        out.append(row)
    return {"versions": out, "head": head_of(points_)}


def entries(user_key: str, project_id: str, node_id: str, *, code: Optional[str] = None) -> dict:
    """The entries of the node *node_id*, in the order they were made, each
    with its code, an edit's with the code it replaced, and the entry in use:
    the newest that holds *code*, the node's code now, else the newest."""
    _opened(user_key, project_id)
    folder = _folder(user_key, project_id)
    rows = [(point, note) for point in _read_points(folder) for note in point.get("notes") or []
            if note.get("node") == node_id and "doc" in point]
    places = set()
    for point, note in rows:
        if "code" not in note:
            places.add((point["doc"], point["day"], point["end"]))
        if note.get("kind") == _NOTE_EDIT and "before" not in note and point["start"] != point["end"]:
            places.add((point["doc"], point["day"], point["start"]))
    flows = _dataflows_at(folder, places)
    records = []
    for point, note in rows:
        held = note["code"] if "code" in note else _node_code(flows.get((point["doc"], point["day"], point["end"])), node_id)
        record = {
            "id": note.get("id"), "parentId": note.get("parentId"), "code": held or "",
            "inputs": note.get("inputs") or [], "outputs": note.get("outputs") or [],
            "startTime": note.get("startTime") or "", "endTime": note.get("endTime") or "",
            "point": point["id"],
        }
        if note.get("kind") == _NOTE_EDIT:
            record["kind"] = "edit"
            if note.get("label"):
                record["label"] = note["label"]
            before = note.get("before")
            if before is None and point["start"] != point["end"]:
                before = _node_code(flows.get((point["doc"], point["day"], point["start"])), node_id)
            if isinstance(before, str) and before != record["code"]:
                record["before"] = before
        if point.get("by"):
            record["by"] = point["by"]
        records.append(record)
    return {"entries": records, "current": entry_in_use(records, code)}


def entry_in_use(records: list[dict], code: Optional[str]) -> Optional[int]:
    """The entry a node's next one descends from: its newest that holds
    *code*, else its newest (the page's ``entryToContinue``)."""
    ids = [record["id"] for record in records if isinstance(record.get("id"), int)]
    same = [record["id"] for record in records if isinstance(record.get("id"), int) and record.get("code") == code]
    if same:
        return max(same)
    return max(ids, default=None)


# ---------------------------------------------------------------------------
# What a tab, or a person, adds to the history
# ---------------------------------------------------------------------------

@contextmanager
def _held(user_key: str, project_id: str):
    """The dataflow's open doc, with its lock held, or the refusal."""
    try:
        with dataflow_docs._held(project_id, user_key) as entry:
            yield entry
    except dataflow_docs._NoDataflow as exc:
        raise HistoryError("This dataflow has no saved spec.", 404) from exc


def note_run(user_key: str, project_id: str, by: dict, node_id: str, *, inputs: list, outputs: list,
             start_time: str, end_time: str, code: str) -> dict:
    """A run of the node *node_id*, which ran *code*, as a point at the log's
    end with its entry on the node. The runner's typing in the node is a
    point of its own first: typing, then running, is two entries."""
    with _held(user_key, project_id) as entry:
        held = _code_in(entry.doc, node_id)
        if held is None:
            raise HistoryError(f"The dataflow has no node {node_id!r}.", 404)
        state = _state(entry)
        _close(entry, (node_id, _account(by)))
        doc_id, day, end = dataflow_docs.log_end(entry)
        sha = _sha(code)
        note = {
            "id": state.next_note(), "node": node_id, "kind": _NOTE_RUN, "parentId": state.current(node_id, sha),
            "inputs": [str(kind) for kind in inputs or []], "outputs": [str(kind) for kind in outputs or []],
            "startTime": start_time or _now_text(), "endTime": end_time or _now_text(),
            "sha": sha, "chars": len(code or ""),
        }
        if (code or "") != held:
            note["code"] = code or ""
        return _add(entry, {"kind": RUN, "what": "Run", "by": by, "doc": doc_id, "day": day,
                            "start": end, "end": end, "notes": [note]})


def note_edit(user_key: str, project_id: str, by: dict, node_id: str, label: str) -> dict:
    """An edit made in the node *node_id*'s body (a Map Editor's), named
    *label*: the point the person's typing in the node would have been, under
    the edit's name, so one action is one entry."""
    with _held(user_key, project_id) as entry:
        if _code_in(entry.doc, node_id) is None:
            raise HistoryError(f"The dataflow has no node {node_id!r}.", 404)
        state = _state(entry)
        key = (node_id, _account(by))
        if key not in state.typing:
            doc_id, day, end = dataflow_docs.log_end(entry)
            state.typing[key] = _Typing(node_id, by, None, doc_id, day, end,
                                        parent=(getattr(entry, "codes", None) or {}).get(node_id))
        state.typing[key].by = by
        return _close(entry, key, kind=EDIT, label=label or "Edit")


def saved(user_key: str, project_id: str, by: dict) -> dict:
    """File > Save: a version named Saved, at the log's end."""
    with _held(user_key, project_id) as entry:
        doc_id, day, end = dataflow_docs.log_end(entry)
        return _add(entry, {"kind": SAVED, "what": "Saved", "by": by, "doc": doc_id, "day": day,
                            "start": end, "end": end})


def put_back(user_key: str, project_id: str, point_id: str, by: dict) -> dict:
    """Put the version *point_id* back: one transaction makes the doc hold
    it, for every tab, and a version named after it, its parent the version
    put back. ``refused``: the nodes whose code someone changed while it was
    being put back, which keep theirs."""
    folder = _folder(user_key, project_id)
    point = next((p for p in _read_points(folder) if p["id"] == point_id and _listed(p)), None)
    if point is None:
        raise HistoryError("This dataflow's history has no such version.", 404)
    target = dataflow_at(user_key, project_id, point_id)
    if target is None:
        raise HistoryError("This version can no longer be rebuilt.", 409)
    spec = dataflow_docs.live(user_key, project_id)
    if spec is None:
        raise HistoryError("This dataflow has no saved spec.", 404)
    flow = spec.get("dataflow") if isinstance(spec.get("dataflow"), dict) else {}
    spec["dataflow"] = {**{name: value for name, value in flow.items() if name in doc_mapping.OUTSIDE_THE_DOC},
                        **target}
    made = {"kind": PUT_BACK, "what": "Put back", "restores": point_id, "parent": point_id, "by": by}
    written = dataflow_docs.write(user_key, project_id, spec, dataflow_docs.person(_account(by), "putBack"),
                                  point=made)
    if not written.wrote:
        with _held(user_key, project_id) as entry:
            doc_id, day, end = dataflow_docs.log_end(entry)
            _add(entry, {**made, "doc": doc_id, "day": day, "start": end, "end": end})
    return {"refused": list(written.refused)}


def write_code(user_key: str, project_id: str, by: dict, node_id: str, *, expect: str, code: str,
               label: str) -> dict:
    """Put *code* in the node *node_id*, only if it still holds *expect*, the
    code the person's put-back, Undo or Redo began from: checked in the same
    transaction (``doc_mapping.apply_dataflow``'s code refusal). Refused, the
    node keeps what it holds, and :class:`Refused` names who changed it."""
    spec = dataflow_docs.live(user_key, project_id)
    if spec is None:
        raise HistoryError("This dataflow has no saved spec.", 404)

    def node_in(source) -> Optional[dict]:
        flow = source.get("dataflow") if isinstance(source, dict) else None
        return next((node for node in (flow or {}).get("nodes") or []
                     if isinstance(node, dict) and node.get("id") == node_id), None)

    node, base = node_in(spec), node_in(spec.base)
    if node is None or base is None:
        raise HistoryError(f"The dataflow has no node {node_id!r}.", 404)
    if expect == "" and "content" not in base:
        base.pop("content", None)
    else:
        base["content"] = expect
    node["content"] = code
    written = dataflow_docs.write(
        user_key, project_id, spec, dataflow_docs.person(_account(by), "code"),
        point={"kind": CODE, "what": label or "Code put back", "by": by},
    )
    if node_id in written.refused:
        entry = dataflow_docs._open_entry(project_id, user_key)
        state = _kept(entry) if entry is not None else None
        raise Refused(state.authors.get(node_id) if state is not None else None)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Clearing and dropping it
# ---------------------------------------------------------------------------

def clear_before(user_key: str, project_id: str, point_id: str) -> dict:
    """Clear the history before the version *point_id*: the points before it
    go, it is the first, and the logs keep only what the remaining points
    need. Its doc's log from it on is written into a doc of its own, from a
    checkpoint of the dataflow as it stood at it; the open doc's own log
    starts again from the dataflow as it is now; and every other log no point
    needs goes, with the earlier history set aside. The dataflow stays as it
    is. Each new file is written before the points name it, and an old one
    goes only once they no longer do."""
    with dataflow_docs._spec_lock(user_key, project_id):
        with _held(user_key, project_id) as entry:
            close_typing(entry)
            # The spec as the doc holds it, so the log that starts again
            # starts where the spec was written from.
            dataflow_docs._flush(entry)
            folder = entry.folder()
            points_ = _read_points(folder)
            index = next((i for i, point in enumerate(points_) if point["id"] == point_id), None)
            if index is None or not _listed(points_[index]):
                raise HistoryError("This dataflow's history has no such version.", 404)
            kept = [dict(point) for point in points_[index:]]
            first = kept[0]
            doc_id, day, offset = first["doc"], first["day"], first["end"]
            copy_id = uuid.uuid4().hex
            for later in dataflow_docs.segments(user_key, project_id, doc_id):
                if later < day:
                    continue
                checkpoint, records = dataflow_docs.segment_in(folder, doc_id, later)
                if later == day:
                    checkpoint = dataflow_docs.rebuilt(user_key, project_id, doc_id, day, upto=offset).get_update()
                    updates = b"".join(write_message(record) for end, record in records if end > offset)
                else:
                    updates = b"".join(write_message(record) for _end, record in records)
                dataflow_docs.write_segment(folder, copy_id, later, checkpoint, updates)
            for point in kept:
                if point.get("doc") != doc_id:
                    continue
                point["doc"] = copy_id
                if point.get("day") == day:
                    point["start"] = max(0, point.get("start", 0) - offset)
                    point["end"] = max(0, point.get("end", 0) - offset)
                elif point.get("day", day) < day:
                    point["day"], point["start"], point["end"] = day, 0, 0
            ids = {point["id"] for point in kept}
            first["start"] = 0
            first["parent"] = None
            for point in kept[1:]:
                if _listed(point) and point.get("parent") not in ids:
                    point["parent"] = first["id"]
                if point.get("kind") == HEAD and point.get("head") not in ids:
                    point["head"] = first["id"]
            _write_points(user_key, project_id, kept)
            if entry.doc_id == doc_id:
                dataflow_docs.restart_log(entry)
            needed = {point.get("doc") for point in kept} | {entry.doc_id}
            for other in dataflow_docs.doc_ids_in(folder):
                if other not in needed:
                    shutil.rmtree(folder / dataflow_docs.LOG_DIR / other, ignore_errors=True)
            entry.history = None
            _forget(folder)
            _tell(entry)
    storage.drop_history_aside(user_key, project_id)
    return {"first": point_id, "versions": sum(1 for point in kept if _listed(point))}


def copy_history(from_key: str, from_id: str, to_key: str, to_id: str) -> bool:
    """Give the dataflow *to_id*, the account *to_key*'s new copy of the
    dataflow *from_id*, that dataflow's history: its points, and the logs they
    name, copied as they are, before the copy's doc first opens. What the copy
    carries of the earlier history's sections goes: the points are its
    history. Whether there was a history to copy."""
    source, target = _folder(from_key, from_id), _folder(to_key, to_id)
    copied = _read_points(source)
    if not copied:
        return False
    for doc_id in sorted({point.get("doc") for point in copied if isinstance(point.get("doc"), str)}):
        logs = source / dataflow_docs.LOG_DIR / doc_id
        if logs.is_dir():
            shutil.copytree(logs, target / dataflow_docs.LOG_DIR / doc_id, dirs_exist_ok=True)
    _write_points(to_key, to_id, copied)
    storage.drop_history_aside(to_key, to_id)
    return True


def drop(user_key: str, project_id: str) -> None:
    """Drop the dataflow's history: its points, the logs only they needed, and
    the earlier history set aside. The seeder does, before it puts an example
    back to its shipped copy, which keeps none of the history of what it
    replaces."""
    try:
        folder = _folder(user_key, project_id)
    except ValueError:
        return
    if not folder.is_dir():
        return
    entry = dataflow_docs._open_entry(project_id, user_key)
    live = entry.doc_id if entry is not None else dataflow_docs.live_doc_id(folder)
    named = {point.get("doc") for point in _read_points(folder)}
    with storage.history_lock(user_key, project_id):
        _points_path(folder).unlink(missing_ok=True)
        shutil.rmtree(folder / storage.HISTORY_DIR / storage.IMPORTED_DIR, ignore_errors=True)
    for doc_id in named - {live, None}:
        if isinstance(doc_id, str) and doc_id in dataflow_docs.doc_ids_in(folder):
            shutil.rmtree(folder / dataflow_docs.LOG_DIR / doc_id, ignore_errors=True)
    if entry is not None:
        entry.history = None
    _forget(folder)
