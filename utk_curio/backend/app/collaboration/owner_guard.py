"""Which backend process keeps a dataflow live, and the refusal of every other.

``curio.py start`` may run several backend processes
(``common/backend_processes.py``). Each dataflow belongs to one of them, its
owner: the process ``shard_of`` names for the dataflow's id, or for a hosted
guest's copy of a dataflow, for the id of the dataflow it copies, the one the
guest's page names (``projects/visitor_copies.py``). A dataflow's requests and
sockets reach its owner by the same rule, and only the owner keeps anything
live for it: its doc and its room (``dataflow_docs.py``, ``events.py``), its
agents' turns, its Solves, its runs and its dashboard's runs.

In any other process:

* opening the dataflow's doc, a writer's read or write of it, a tab's join or
  sync, and the start of a turn, a Solve, a run or a dashboard's run fail with
  :class:`NotTheOwner`, which names the dataflow, its owner and this process,
  and a request is answered 421. A request that reaches the wrong process is a
  routing bug, never a second live doc;
* a read replays the dataflow's file and its log into a doc it does not keep,
  and a create writes the dataflow's files and keeps no doc
  (``dataflow_docs.read``, ``dataflow_docs.create``);
* a change made for an account rather than for one dataflow, an agent added to
  every dataflow or a dataset's id migrated, is made by the dataflow's owner
  over an internal call (``owner_calls.py``).

Each refusal, read, create and call is counted (:func:`counts`) and logged as
an ``[owner-guard]`` line naming its caller, so a deployment shows which
callers reach across processes. With one process every check is one
comparison, and nothing is refused, looked up or counted.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Optional

from werkzeug.exceptions import MisdirectedRequest

from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.common import backend_processes

logger = logging.getLogger(__name__)

#: Of each kind of line from each caller, the first this many are logged, then
#: every :data:`LOGGED_EVERY`-th with the count so far, so a flood stays short
#: and still counts.
LOGGED_FIRST = 20
LOGGED_EVERY = 100

_lock = threading.Lock()
#: How many of each kind this process made: reads, creates, refusals, calls.
_counts: dict[str, int] = {}
#: The same, by kind and caller, for the lines.
_by_caller: dict[tuple[str, str], int] = {}
#: Each hosted guest's copy's source, once known: a copy's id is made from the
#: dataflow it copies, so it names that dataflow for good.
_sources: dict[str, str] = {}

#: Where the lines' callers are not: this module, the doc server's, and the
#: blocks they run in.
_INSIDE = (
    os.path.join("collaboration", "owner_guard.py"),
    os.path.join("collaboration", "dataflow_docs.py"),
    os.path.join("collaboration", "owner_calls.py"),
    "contextlib.py",
)


class NotTheOwner(MisdirectedRequest):
    """What a process that does not own a dataflow raises when asked to keep
    or start something live for it: 421, naming the dataflow, the process that
    owns it and this one."""

    def __init__(self, dataflow_id: str, owner: int, process: int, processes: int, what: str):
        self.dataflow_id = dataflow_id
        self.owner = owner
        self.process = process
        self.processes = processes
        self.what = what
        super().__init__(description=(
            f"Dataflow {dataflow_id} belongs to backend process {owner}, and this is process "
            f"{process} of {processes}: {what} is refused here."
        ))


def room_key(project_id: str, user_key=None, *, source: Optional[str] = None) -> str:
    """The id that names the process *project_id* belongs to: its own, or for
    a hosted guest's copy of a dataflow, that dataflow's. *source* is what the
    copy copies when the caller holds its row (``visitor_copies.Copy``);
    otherwise the copy's ``visitor.json`` says, or for a copy not made yet,
    the room of it this process opened. A guest's own new dataflow copies
    none and goes by its own id, as its page names it. Only the guest account
    holds copies: another account's dataflow goes by its own id at once."""
    if source is None:
        if user_key is not None and str(user_key) != GUEST_KEY:
            return project_id
        source = _source_of(project_id)
    if not source or _new(source):
        return project_id
    return source


def _source_of(project_id: str) -> Optional[str]:
    known = _sources.get(project_id)
    if known is not None:
        return known
    from utk_curio.backend.app.projects import visitor_copies

    source = visitor_copies.source_of(project_id)
    if source:
        with _lock:
            _sources[project_id] = source
    return source


def _new(source: str) -> bool:
    from utk_curio.backend.app.projects.visitor_copies import NEW

    return source.startswith(NEW)


def owner_of(project_id: str, user_key=None, *, source: Optional[str] = None) -> int:
    """The process *project_id* belongs to among this start's."""
    processes = backend_processes.process_count()
    if processes <= 1:
        return backend_processes.HOME
    return backend_processes.shard_of(room_key(project_id, user_key, source=source), processes)


def elsewhere(project_id: str, user_key=None, *, source: Optional[str] = None) -> Optional[int]:
    """The process that owns *project_id* when it is not this one; ``None``
    when this process owns it, as the one process of a start owns every
    dataflow."""
    processes = backend_processes.process_count()
    if processes <= 1:
        return None
    owner = backend_processes.shard_of(room_key(project_id, user_key, source=source), processes)
    return None if owner == backend_processes.this_process() else owner


def refuse(project_id: str, user_key=None, *, what: str, source: Optional[str] = None) -> None:
    """Raise :class:`NotTheOwner` when another process owns *project_id*;
    *what*, in a few words, is what this process was asked to keep or start
    for it. The refusal is counted and logged."""
    owner = elsewhere(project_id, user_key, source=source)
    if owner is None:
        return
    _note("refused", f"refused {what} for", project_id, owner, logging.ERROR)
    raise NotTheOwner(project_id, owner, backend_processes.this_process(),
                      backend_processes.process_count(), what)


def noted(kind: str, project_id: str, owner: int) -> None:
    """Count and log a *kind* of dataflow *project_id*, which process *owner*
    owns, made here: ``read`` or ``create``."""
    _note(kind, f"a {kind} of", project_id, owner, logging.WARNING)


def sent(operation: str, project_id: str, owner: int) -> None:
    """Count and log a change sent to the process *owner*, which owns
    *project_id*: the operation *operation* (``owner_calls.py``)."""
    _note("sent", f"sent {operation} of", project_id, owner, logging.INFO)


def _note(kind: str, words: str, project_id: str, owner: int, level: int) -> None:
    caller = _caller()
    with _lock:
        _counts[kind] = _counts.get(kind, 0) + 1
        seen = _by_caller[(kind, caller)] = _by_caller.get((kind, caller), 0) + 1
    if seen <= LOGGED_FIRST or seen % LOGGED_EVERY == 0:
        logger.log(
            level, "[owner-guard] process %d of %d: %s dataflow %s, which process %d owns, from %s (%d from there)",
            backend_processes.this_process(), backend_processes.process_count(), words, project_id, owner, caller, seen,
        )


def _caller() -> str:
    """The first frame outside this module and the doc server's, as
    ``path:line`` under ``utk_curio/`` or a library's file name."""
    frame = sys._getframe(2)
    while frame is not None:
        name = frame.f_code.co_filename
        if not name.endswith(_INSIDE):
            normal = name.replace("\\", "/")
            at = normal.rfind("utk_curio/")
            return f"{normal[at + len('utk_curio/'):] if at >= 0 else os.path.basename(normal)}:{frame.f_lineno}"
        frame = frame.f_back
    return "?"


def counts() -> dict[str, int]:
    """How many of each kind this process made since it started: ``read``,
    ``create``, ``refused`` and ``sent``, each only once one was made."""
    with _lock:
        return dict(_counts)


def reset_for_tests() -> None:
    """Forget the counts and the copies' sources, as a process that starts."""
    with _lock:
        _counts.clear()
        _by_caller.clear()
        _sources.clear()
