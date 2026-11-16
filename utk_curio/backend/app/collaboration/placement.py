"""The backend process a new dataflow goes to: the one with the fewest open rooms.

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

A room is open in a process while a tab (``room_state.py``) or an agent at
work (``agent_peers.py``) is in it. As a tab or an agent joins or leaves a
room, the process counts its open rooms again (:func:`changed`) and writes
the count into one document the start's processes share
(``common/shared_budgets.State``) when it changed: as a room's first tab or
agent joins it, and as its last one leaves. Nothing is written on a timer.
The document also holds whose turn is next. :func:`choose` takes the process
with the fewest open rooms, the first at or after the turn among those with
as few, and gives the turn to the process after it, in one step under the
document's lock, so two processes making dataflows at once take two turns.
The document is the start's: each start begins with no open rooms and the turn
at the home process.

With one process every new dataflow is home's, its id a plain uuid4, and
nothing is counted or kept.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Optional

from utk_curio.backend.app.common import shared_budgets
from utk_curio.backend.app.common.user_storage import curio_root
from utk_curio.common import backend_processes

logger = logging.getLogger(__name__)

#: The document the start's processes share.
_SHARED = shared_budgets.State("dataflow-placement")
#: Its fields: each process's open rooms, by its number, and whose turn is next.
ROOMS = "rooms"
TURN = "turn"

#: Held while this process counts its open rooms and writes the count, so the
#: count written last is the one counted last.
_lock = threading.Lock()
#: Where this process last wrote its count (the start, its state folder and
#: this process's number), with the count.
_written: Optional[tuple] = None


def changed() -> None:
    """A tab or an agent joined or left a room of this process: count the
    process's open rooms again, and write the count when it changed. A count
    that cannot be written is logged, and written with the next change: no
    join and no agent's work fails for it."""
    global _written
    if not shared_budgets.across_processes():
        return
    try:
        with _lock:
            count = len(_open_here())
            where = _where()
            if _written == (where, count):
                return
            with _SHARED.held() as state:
                rooms = state.get(ROOMS)
                rooms = dict(rooms) if isinstance(rooms, dict) else {}
                rooms[str(backend_processes.this_process())] = count
                state[ROOMS] = rooms
            _written = (where, count)
    except Exception:  # noqa: BLE001 - a room's count never fails a tab's join or an agent's work
        logger.exception("this backend process's open rooms could not be written for the placement of new dataflows")


def choose() -> int:
    """The process a new dataflow goes to: the one with the fewest open
    rooms, the first at or after the turn among those with as few. The turn
    passes to the process after it."""
    processes = backend_processes.process_count()
    if processes <= 1:
        return backend_processes.HOME
    with _SHARED.held() as state:
        chosen = _pick(state, processes)
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


def reset_for_tests() -> None:
    """Forget the count this process last wrote, as a process that starts."""
    global _written
    with _lock:
        _written = None


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


def _pick(state: dict, processes: int) -> int:
    """The process with the fewest open rooms in *state*, the first at or
    after its turn among those with as few. The document is held."""
    rooms = _rooms(state, processes)
    fewest = min(rooms)
    turn = _count(state.get(TURN)) % processes
    return next(number for number in ((turn + step) % processes for step in range(processes))
                if rooms[number] == fewest)
