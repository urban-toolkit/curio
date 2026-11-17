"""The backend process a new dataflow goes to: the one with the least load,
its open rooms and its recent placements.

``curio.py start --backend-processes N`` runs N backend processes, and each
dataflow belongs to the one its id names (``backend_processes.shard_of``):
nginx sends its requests and sockets there, and the owner guard keeps its doc,
room, turns and runs there (``cli/backend_group.py``, ``owner_guard.py``). A
dataflow an account makes, new, imported or duplicated
(``projects/repositories.py``), gets an id made for the process
:func:`choose` takes (:func:`new_dataflow_id`,
``backend_processes.dataflow_id_on``), once per create, before the write that
may be retried. Seeded examples and hosted guests' copies keep the ids they
are made with.

A process's load is its open rooms plus its recent placements:

* A room is open in a process while a tab (``room_state.py``) or an agent at
  work (``agent_peers.py``) is in it. As a tab or an agent joins or leaves a
  room, the process counts its open rooms again (:func:`changed`) and writes
  the count when it changed: as a room's first tab or agent joins it, and as
  its last one leaves. Nothing is written on a timer.
* A placement is a new dataflow :func:`choose` gave the process. It counts for
  :data:`RECENT_S` after it, so a burst of new dataflows made before any of
  their rooms opens spreads over the processes, rather than all going to the
  one with the fewest open rooms. A placement whose room has opened since
  counts twice for the rest of that window, as an open room and as a
  placement, and that is fine: it ends with the window.

Both are kept in one document the start's processes share
(``common/shared_budgets.State``), with whose turn is next. :func:`choose`
drops the placements older than the window, takes the process with the least
load, the first at or after the turn among those with as little, notes its
placement, and gives the turn to the process after it, in one step under the
document's lock, so two processes making dataflows at once take two turns.
The document is the start's: each start begins with no open rooms, no
placements and the turn at the home process.

With one process every new dataflow is home's, its id a plain uuid4, and
nothing is counted or kept.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Optional

from utk_curio.backend.app.common import shared_budgets
from utk_curio.backend.app.common.user_storage import curio_root
from utk_curio.common import backend_processes

logger = logging.getLogger(__name__)

#: The document the start's processes share.
_SHARED = shared_budgets.State("dataflow-placement")
#: Its fields: each process's open rooms and the times of its placements, by
#: its number, and whose turn is next.
ROOMS = "rooms"
PLACED = "placed"
TURN = "turn"

#: How long a placement counts toward its process's load, in seconds.
RECENT_S = 600.0
#: The clock placements are timed by, which every process of a start reads
#: alike (as ``discovery/application/places.py``'s shared pace does).
_clock = time.monotonic

#: Held while this process counts its open rooms and writes the count, so the
#: count written last is the one counted last.
_lock = threading.Lock()
#: What this process last wrote, under ``"count"``: where it wrote its count
#: (the start, its state folder and this process's number) with the count,
#: or ``None`` before its first write. Held under :data:`_lock`.
_written: dict[str, Optional[tuple]] = {"count": None}


def changed() -> None:
    """A tab or an agent joined or left a room of this process: count the
    process's open rooms again, and write the count when it changed. A count
    that cannot be written is logged, and written with the next change: no
    join and no agent's work fails for it."""
    if not shared_budgets.across_processes():
        return
    try:
        with _lock:
            count = len(_open_here())
            where = _where()
            if _written["count"] == (where, count):
                return
            with _SHARED.held() as state:
                rooms = state.get(ROOMS)
                rooms = dict(rooms) if isinstance(rooms, dict) else {}
                rooms[str(backend_processes.this_process())] = count
                state[ROOMS] = rooms
            _written["count"] = (where, count)
    except Exception:  # noqa: BLE001 - a room's count never fails a tab's join or an agent's work
        logger.exception("this backend process's open rooms could not be written for the placement of new dataflows")


def choose() -> int:
    """The process a new dataflow goes to: the one with the least load, its
    open rooms plus its placements of the last :data:`RECENT_S`, the first at
    or after the turn among those with as little. The placement is noted, the
    older ones dropped, and the turn passes to the process after it."""
    processes = backend_processes.process_count()
    if processes <= 1:
        return backend_processes.HOME
    with _SHARED.held() as state:
        now = _clock()
        placed = state[PLACED] = _recent(state, now)
        chosen = _pick(state, processes)
        placed.setdefault(str(chosen), []).append(now)
        state[TURN] = (chosen + 1) % processes
    return chosen


def new_dataflow_id() -> str:
    """A new dataflow's id, made for the process :func:`choose` takes. When
    no process can be chosen, a plain uuid4, which names one at random, so the
    dataflow is made all the same."""
    processes = backend_processes.process_count()
    try:
        process = choose()
    except Exception:  # noqa: BLE001 - a dataflow is made even when no process could be chosen for it
        logger.exception("no backend process could be chosen for a new dataflow; its id names one at random")
        return str(uuid.uuid4())
    return backend_processes.dataflow_id_on(process, processes)


def open_rooms() -> list[int]:
    """Each process's open rooms, by its number: as the start's document
    holds them, or with one process, this one's, counted now."""
    processes = backend_processes.process_count()
    if processes <= 1:
        return [len(_open_here())]
    with _SHARED.held() as state:
        return _rooms(state, processes)


def loads() -> list[int]:
    """Each process's load, by its number: its open rooms plus its placements
    of the last :data:`RECENT_S`, as the start's document holds them, or with
    one process, this one's open rooms, counted now."""
    processes = backend_processes.process_count()
    if processes <= 1:
        return [len(_open_here())]
    with _SHARED.held() as state:
        return _load({**state, PLACED: _recent(state, _clock())}, processes)


def reset_for_tests() -> None:
    """Forget the count this process last wrote, as a process that starts."""
    with _lock:
        _written["count"] = None


def _open_here() -> set:
    """This process's open rooms: those a tab or an agent at work is in."""
    from utk_curio.backend.app.collaboration import agent_peers, room_state

    return room_state.rooms_with_tabs() | agent_peers.rooms_at_work()


def _where() -> tuple:
    """Where this process's count is written: the start, its state folder and
    this process's number."""
    return shared_budgets.BOOT_ID, str(curio_root()), backend_processes.this_process()


def _count(value) -> int:
    """A count the document holds, and 0 for anything else."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _rooms(state: dict, processes: int) -> list[int]:
    """Each process's open rooms in *state*, by its number."""
    kept = state.get(ROOMS)
    kept = kept if isinstance(kept, dict) else {}
    return [_count(kept.get(str(number))) for number in range(processes)]


def _recent(state: dict, now: float) -> dict:
    """The placements in *state* made in the last :data:`RECENT_S` before
    *now*, each process's times by its number; the older ones are left out."""
    kept = state.get(PLACED)
    kept = kept if isinstance(kept, dict) else {}
    recent = {}
    for number, times in kept.items():
        fresh = [at for at in (times if isinstance(times, list) else ())
                 if isinstance(at, (int, float)) and not isinstance(at, bool) and at > now - RECENT_S]
        if fresh:
            recent[str(number)] = fresh
    return recent


def _load(state: dict, processes: int) -> list[int]:
    """Each process's load in *state*, by its number: its open rooms plus the
    placements *state* holds of it, those of the window."""
    placed = state.get(PLACED)
    placed = placed if isinstance(placed, dict) else {}
    times = [placed.get(str(number)) for number in range(processes)]
    return [rooms + (len(at) if isinstance(at, list) else 0) for rooms, at in zip(_rooms(state, processes), times)]


def _pick(state: dict, processes: int) -> int:
    """The process with the least load in *state*, the first at or after its
    turn among those with as little. The document is held, and holds only the
    placements of the window."""
    load = _load(state, processes)
    least = min(load)
    turn = _count(state.get(TURN)) % processes
    return next(number for number in ((turn + step) % processes for step in range(processes))
                if load[number] == least)
