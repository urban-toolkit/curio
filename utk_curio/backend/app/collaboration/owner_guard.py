"""Which backend process keeps a dataflow live, and the refusal of every other.

``curio.py start`` may run several backend processes
(``common/backend_processes.py``). Each dataflow belongs to one of them, its
owner: the process ``shard_of`` names for the dataflow's id (:func:`room_key`).
A hosted guest's copy of a dataflow goes by the copy's own id, never by the id
of the dataflow it copies, and so does a hosted guest's own new dataflow
(``projects/visitor_copies.py``): the copies of one example, one for each guest
who opens it, spread over the processes as their ids do. The guest's page
names its copy's id once the dataflow's load gives it
(``src/utils/requestHeaders.ts``). A dataflow's requests and sockets reach its
owner by the same rule, and only the owner keeps anything live for it: its doc
and its room (``dataflow_docs.py``, ``events.py``), its agents' turns, its
Solves, its runs and its dashboard's runs. A hosted guest's dashboard of an
example runs the guest's copy as a run of that dashboard, which the example's
owner keeps: the dashboard's page names the example (``runs/viewer.py``).

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

The home process does the startup work before the launcher starts the others
(``cli/backend_group.py``), so while it does, no other process listens and a
change sent to a dataflow's owner would reach no one. So home owns every
dataflow until that work is done (:func:`before_the_others_serve`), then
writes and drops every doc it opened of a dataflow another process owns.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from werkzeug.exceptions import MisdirectedRequest

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
#: Whether this process owns every dataflow for now: the home process while it
#: does the startup work, before the start's other processes serve.
_alone = False

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


def room_key(project_id: str) -> str:
    """The id that names the process *project_id* belongs to: its own, for
    every dataflow. A hosted guest's copy of a dataflow goes by the copy's
    id, not by the id of the dataflow it copies, and a guest's own new
    dataflow by its own: the id the guest's page names."""
    return project_id


def owner_of(project_id: str) -> int:
    """The process *project_id* belongs to among this start's."""
    processes = backend_processes.process_count()
    if processes <= 1:
        return backend_processes.HOME
    return backend_processes.shard_of(room_key(project_id), processes)


def elsewhere(project_id: str) -> Optional[int]:
    """The process that owns *project_id* when it is not this one; ``None``
    when this process owns it, as the one process of a start owns every
    dataflow, and the home process does while it does the startup work
    (:func:`before_the_others_serve`)."""
    processes = backend_processes.process_count()
    if processes <= 1 or _alone:
        return None
    owner = backend_processes.shard_of(room_key(project_id), processes)
    return None if owner == backend_processes.this_process() else owner


@contextmanager
def before_the_others_serve(does_startup_work: bool) -> Iterator[None]:
    """The home process's startup work, in a start of several processes:
    inside, this process owns every dataflow, so the agents and the examples
    it puts back write each dataflow here rather than send a change to an
    owner that does not listen yet. When the work ends, the dataflows are
    their owners' again, and every doc this process opened of one another
    process owns is written and dropped (``dataflow_docs.close_others``):
    its owner opens it once it serves. Nothing changes in a process that does
    no startup work, or in a start of one process."""
    global _alone
    if not does_startup_work or backend_processes.process_count() <= 1:
        yield
        return
    _alone = True
    try:
        yield
    finally:
        _alone = False
        from utk_curio.backend.app.collaboration import dataflow_docs

        closed = dataflow_docs.close_others()
        if closed:
            logger.info("[owner-guard] process %d of %d wrote and dropped the docs of %d dataflow(s) other "
                        "processes own, opened by its startup work", backend_processes.this_process(),
                        backend_processes.process_count(), len(closed))


def refuse(project_id: str, *, what: str) -> None:
    """Raise :class:`NotTheOwner` when another process owns *project_id*;
    *what*, in a few words, is what this process was asked to keep or start
    for it. The refusal is counted and logged."""
    owner = elsewhere(project_id)
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
    """Forget the counts, as a process that starts."""
    global _alone
    with _lock:
        _counts.clear()
        _by_caller.clear()
        _alone = False
