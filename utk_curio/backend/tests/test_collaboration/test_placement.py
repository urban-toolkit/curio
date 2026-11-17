"""New dataflows go to the backend process with the least load, its open
rooms and its recent placements (``collaboration/placement.py``).

``curio.py start --backend-processes N`` runs N backends, and a dataflow
belongs to the process its id's first two hex digits name
(``backend_processes.shard_of``). A new dataflow's id was a plain uuid4, so
the rooms of a start fell on its processes by chance: 10 rooms on 8
processes put 3 or more on one in most runs. A dataflow an account makes
now gets an id made for the process with the least load: its open rooms, a
room being open while a tab or an agent at work is in it, plus the new
dataflows it was given in the last 10 minutes. Processes with as little take
new dataflows in turn.

Each test names a start of its own, this test's process its home process,
with a state folder of its own. Another process of the start is a forked child
(``_support/two_processes.py``), which names itself by its number, opens rooms
of its own, and ends with its count kept in the start's document, as a
process still holding those rooms keeps it.
"""
from __future__ import annotations

import collections
import multiprocessing
import os
import uuid

import pytest

from ._processes import as_process
from ._support import NAMESPACE, connect, join, make_project, make_user

#: The agent the tests put at work.
NB = "agent.curio.node-builder@1"


@pytest.fixture()
def no_one_in_any_room(monkeypatch):
    """No tab and no agent in any room of this process, before and after."""
    from utk_curio.backend.app.collaboration import agent_peers, room_state

    monkeypatch.setattr(agent_peers, "BACKGROUND", False)
    room_state.reset_for_tests()
    agent_peers.reset_for_tests()
    yield
    room_state.reset_for_tests()
    agent_peers.reset_for_tests()


@pytest.fixture()
def start_of(no_one_in_any_room, tmp_path, monkeypatch):
    """A start of the given number of backend processes, this test's being
    home, with a state folder of the start's own: the placement of its new
    dataflows."""
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))

    def start(processes: int):
        from utk_curio.backend.app.collaboration import placement

        as_process(monkeypatch, 0, processes)
        return placement

    return start


def _tabs_in(rooms) -> None:
    """A tab of its own joins each of *rooms*, as a socket's join does."""
    from utk_curio.backend.app.collaboration import room_state

    for room in rooms:
        room_state.add_user(room, f"sid-{room}", {"participant_id": f"tab-{room}", "role": "owner", "user_id": 1})


def _tabs_leave(rooms) -> None:
    from utk_curio.backend.app.collaboration import room_state

    for room in rooms:
        room_state.remove_user(room, f"sid-{room}")


def _process_with_rooms(number: int, rooms: int) -> None:
    """The start's process *number*, a forked child, with a tab in each of
    *rooms* rooms of its own, none of this process's."""
    from utk_curio.backend.app.collaboration import room_state
    from utk_curio.backend.tests._support.two_processes import in_another_process

    def opens_its_rooms():
        os.environ["CURIO_BACKEND_PROCESS"] = str(number)
        room_state.reset_for_tests()
        _tabs_in([f"project:{number}-{index}" for index in range(rooms)])

    error = in_another_process(opens_its_rooms)
    assert error == "", error


# ---------------------------------------------------------------------------
# Which process a new dataflow goes to
# ---------------------------------------------------------------------------

def test_with_no_room_open_new_dataflows_go_to_each_process_in_turn(start_of):
    placement = start_of(3)

    assert [placement.choose() for _ in range(7)] == [0, 1, 2, 0, 1, 2, 0]


def test_ten_dataflows_made_together_on_eight_processes_go_two_two_one_one_one_one_one_one(start_of):
    """Ten rooms made at once, before any of them opens, as the stress
    stages' rooms are, spread over every process: two processes take two
    each, and every other takes one."""
    from utk_curio.common.backend_processes import shard_of

    placement = start_of(8)

    made = [placement.new_dataflow_id() for _ in range(10)]

    per_process = collections.Counter(shard_of(dataflow, 8) for dataflow in made)
    assert sorted(per_process.values(), reverse=True) == [2, 2, 1, 1, 1, 1, 1, 1], per_process
    assert all(uuid.UUID(dataflow).version == 4 for dataflow in made), made


def test_a_new_dataflow_goes_to_the_process_with_the_fewest_open_rooms(start_of):
    """Process 1 has two rooms open, process 2 one, and home three: the next
    new dataflow goes to process 2, whatever the turn. Each one placed counts
    toward its process's load, so the one after goes to process 1, as loaded
    as process 2 by then and first in turn, and the third to process 2 again.
    Once home's tabs leave, home has the least."""
    placement = start_of(3)
    _process_with_rooms(1, rooms=2)
    _process_with_rooms(2, rooms=1)
    home = [f"project:home-{index}" for index in range(3)]
    _tabs_in(home)

    counted = placement.open_rooms()
    chosen = [placement.choose() for _ in range(3)]
    _tabs_leave(home)
    after = placement.open_rooms()

    assert counted == [3, 2, 1], counted
    assert chosen == [2, 1, 2], f"new dataflows went to {chosen}, not to the process with the least load"
    assert after == [0, 2, 1], f"home's last tabs left and its count is {after[0]}"
    assert placement.loads() == [0, 3, 3]
    assert placement.choose() == 0


def test_processes_with_as_few_open_rooms_take_new_dataflows_in_turn(start_of):
    """Home and process 3 have a room open, processes 1 and 2 none: the first
    new dataflow goes to process 1, the first after the turn of the two, and
    the next to process 2. Each placed counts toward its process's load, so
    all four are then as loaded, and the next go to each in turn: 3, 0 and
    1."""
    placement = start_of(4)
    _process_with_rooms(3, rooms=1)
    _tabs_in(["project:home"])

    counted = placement.open_rooms()
    chosen = [placement.choose() for _ in range(5)]

    assert counted == [1, 0, 0, 1], counted
    assert chosen == [1, 2, 3, 0, 1], chosen


def test_a_burst_of_new_dataflows_spreads_over_the_processes_by_their_load(start_of):
    """Processes 1, 2 and 3 have a room open each and home none. Four new
    dataflows made at once, before any of their rooms opens, go to each
    process once, not all four to home: each counts toward its process's load
    as it is placed."""
    from utk_curio.common.backend_processes import shard_of

    placement = start_of(4)
    for number in (1, 2, 3):
        _process_with_rooms(number, rooms=1)

    counted = placement.open_rooms()
    made = [placement.new_dataflow_id() for _ in range(4)]

    assert counted == [0, 1, 1, 1], counted
    went = [shard_of(dataflow, 4) for dataflow in made]
    assert went == [0, 1, 2, 3], f"a burst of new dataflows went to {went}"
    assert placement.loads() == [1, 2, 2, 2]


def test_placements_older_than_the_window_no_longer_count(start_of, monkeypatch):
    """Home has no room open, and processes 1 and 2 two each: two new
    dataflows go to home, which is then as loaded as they are. Once the window
    has passed, those two count no more, so the next new dataflow goes to home
    again, not to process 1, whose turn it is, and the document keeps no
    placement older than the window."""
    placement = start_of(3)
    _process_with_rooms(1, rooms=2)
    _process_with_rooms(2, rooms=2)
    now = [1000.0]
    monkeypatch.setattr(placement, "_clock", lambda: now[0])

    burst = [placement.choose(), placement.choose()]
    within = placement.loads()
    now[0] += placement.RECENT_S + 1
    past = placement.loads()
    chosen = placement.choose()
    with placement._SHARED.held() as state:
        kept = state.get(placement.PLACED)

    assert burst == [0, 0], burst
    assert within == [2, 2, 2], within
    assert past == [0, 2, 2], f"placements older than the window still count: {past}"
    assert chosen == 0, f"the next new dataflow went to {chosen}: home's old placements still count"
    assert kept == {"0": [now[0]]}, f"the document keeps placements older than the window: {kept}"


def test_an_agent_at_work_keeps_its_room_open(doc_app, no_one_in_any_room, monkeypatch):
    """An agent at work in a dataflow with no tab open: its room is open as
    long as the agent works in it, so the next new dataflow goes to the other
    process, whatever the turn. That placement then weighs as much as the
    agent's room, and the one after goes to home, whose turn it is."""
    from utk_curio.backend.app.collaboration import agent_peers, placement
    from utk_curio.common.backend_processes import dataflow_id_on

    as_process(monkeypatch, 0, 2)
    alice, _session = make_user("alice")
    project_id = make_project(alice, dataflow_id_on(0, 2))

    with agent_peers.at_work(str(alice.id), project_id, attachment_id="att-1", coord=NB, name="Node Builder",
                             category="node", asked_by=agent_peers.asker(alice)):
        during = placement.open_rooms()
        first = placement.choose()
        then = placement.choose()
    after = placement.open_rooms()

    assert during == [1, 0], during
    assert first == 1, "a new dataflow went to the process an agent is at work in, which has more open rooms"
    assert then == 0, f"with the agent's room and a placement as one each, a new dataflow went to {then}, not home"
    assert after == [0, 0], f"the agent left and its room still counts: {after}"


def test_a_room_is_open_from_its_first_tab_to_its_last(doc_app, no_one_in_any_room, monkeypatch):
    """Two tabs of one dataflow, through the room's socket: the room counts
    once, while either is in it."""
    from utk_curio.backend.app.collaboration import placement
    from utk_curio.common.backend_processes import dataflow_id_on

    application, socketio = doc_app
    as_process(monkeypatch, 0, 2)
    alice, session = make_user("alice")
    project_id = make_project(alice, dataflow_id_on(0, 2))
    first = connect(socketio, application, session.token)
    second = connect(socketio, application, session.token)
    assert join(first, project_id)["ok"] is True
    assert join(second, project_id)["ok"] is True

    both = placement.open_rooms()
    first.disconnect(namespace=NAMESPACE)
    one = placement.open_rooms()
    second.disconnect(namespace=NAMESPACE)
    none = placement.open_rooms()

    assert both == [1, 0], both
    assert one == [1, 0], "the room closed while a tab was still in it"
    assert none == [0, 0], "the room's last tab left and it still counts"


# ---------------------------------------------------------------------------
# One turn each, and one start's
# ---------------------------------------------------------------------------

def test_two_processes_making_dataflows_at_once_take_two_turns(start_of, monkeypatch):
    """The turn is read and passed on in one step under the start's lock: a
    process that chooses while another is between its read and its write
    waits for it, then takes the next turn, never the one the other took."""
    from utk_curio.backend.tests._support.two_processes import Window, race

    placement = start_of(2)
    window = Window()
    pick = placement._pick

    def _read_then_stop(state, processes):
        chosen = pick(state, processes)
        window.stop_here()
        return chosen

    monkeypatch.setattr(placement, "_pick", _read_then_stop)
    there = multiprocessing.get_context("fork").Value("i", -1)

    def chooses_there():
        os.environ["CURIO_BACKEND_PROCESS"] = "1"
        there.value = placement.choose()

    raced = race(window, chooses_there, placement.choose, monkeypatch)

    assert raced.child_exit == 0, raced.child_error
    assert (there.value, raced.here) == (0, 1), (
        f"two processes making a dataflow at once took the turns {there.value} and {raced.here}"
    )
    assert placement.choose() == 0, "the turn did not pass on after both"


def test_each_start_begins_with_no_open_rooms_and_the_turn_at_home(start_of, monkeypatch):
    """What one start counted is its own: the next start's processes count
    their rooms anew, it holds none of the start before's placements, and its
    first new dataflow goes to home."""
    from utk_curio.backend.app.collaboration import room_state
    from utk_curio.backend.app.common import shared_budgets

    placement = start_of(3)
    _tabs_in(["project:the-start-before"])
    first = placement.choose()
    kept = placement.open_rooms()

    monkeypatch.setattr(shared_budgets, "BOOT_ID", "the next start")
    room_state.reset_for_tests()  # the next start's processes hold no tab yet

    assert (first, kept) == (1, [1, 0, 0])
    assert placement.open_rooms() == [0, 0, 0], "a start counts the rooms the start before it had open"
    assert placement.loads() == [0, 0, 0], "a start counts the placements the start before it made"
    assert placement.choose() == 0, "a start takes the turn the start before it left"


def test_a_retried_write_of_a_new_dataflow_takes_no_second_turn(doc_app, no_one_in_any_room, monkeypatch):
    """A create's write is replayed when it loses a race to another writer
    (``retry_on_write_conflict``). Its id is taken once, before the write, so
    the replay takes no second turn: the next create takes the next one, and
    the two creates took two turns."""
    from sqlalchemy.exc import OperationalError

    from utk_curio.backend.app.collaboration import placement
    from utk_curio.backend.app.projects import repositories
    from utk_curio.common.backend_processes import shard_of

    as_process(monkeypatch, 0, 3)
    dana, _session = make_user("dana")
    unique_slug = repositories._unique_slug
    asked = []

    def loses_the_first_race(*args, **kwargs):
        asked.append(args)
        if len(asked) == 1:
            # What SQLite raises when the write lost a race to another writer.
            raise OperationalError("INSERT", {}, Exception("database is locked"))
        return unique_slug(*args, **kwargs)

    monkeypatch.setattr(repositories, "_unique_slug", loses_the_first_race)

    first = repositories.upsert_project(user_id=dana.id, name="First", folder_path="")
    second = repositories.upsert_project(user_id=dana.id, name="Second", folder_path="")
    third = placement.choose()

    assert len(asked) == 3, "the first create's write was not replayed"
    assert [shard_of(first.id, 3), shard_of(second.id, 3)] == [0, 1], (
        f"the creates went to processes {shard_of(first.id, 3)} and {shard_of(second.id, 3)}: "
        "the replay of the first took a turn of its own"
    )
    assert third == 2, f"after two creates the turn is process {third}'s, not process 2's"


def test_with_one_process_every_new_dataflow_is_a_uuid4_of_home_and_nothing_is_kept(start_of):
    from utk_curio.backend.app.common import shared_budgets, user_storage

    placement = start_of(1)
    _tabs_in(["project:alone"])

    made = [placement.new_dataflow_id() for _ in range(64)]

    assert placement.choose() == 0
    assert all(uuid.UUID(dataflow).version == 4 for dataflow in made), made
    assert len({dataflow[:2] for dataflow in made}) > 1, "one process's ids start with one lead, not a uuid4's"
    folder = user_storage.curio_root() / shared_budgets.FOLDER
    assert not folder.exists(), sorted(str(path) for path in folder.rglob("*"))
