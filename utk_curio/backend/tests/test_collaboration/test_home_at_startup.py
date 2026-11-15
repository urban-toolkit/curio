"""The home process's startup work, before the start's other backend
processes serve (``collaboration/owner_guard.before_the_others_serve``).

The launcher starts the others only once home answers, so during home's
startup work no other process listens, and a change sent to a dataflow's owner
would reach no one. So home owns every dataflow while it does that work:
putting back the agents every account has writes each dataflow here. When the
work is done, home writes and drops every doc it opened of a dataflow another
process owns, which that process opens itself once it serves: no dataflow has
a live doc in two processes. Then the dataflows are their owners' again.

Here alice's dataflow belongs to process 1 of 2. Its owner's tab typed in it
and the owner stopped before writing it, as a backend that stops leaves a
dataflow: the change is in its doc's log alone. Then this test's process is
the next start's home, process 0, with no other process listening.
"""

from __future__ import annotations

import copy
import socket

from ._processes import as_process, owned_by
from ._support import make_project, make_user
from .test_dataflow_docs import SPEC, _code, _Room, _type

#: What the owner's tab typed before its process stopped.
TYPED = "# typed before the restart\n"


def _a_port_no_one_listens_on() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_alone_at_startup_home_writes_every_dataflow_then_keeps_no_doc_another_process_owns(doc_app, monkeypatch):
    from utk_curio.backend.app.projects import storage

    application, socketio = doc_app
    alice_user, session = make_user("alice")
    users, tokens = {"alice": alice_user}, {"alice": session.token}
    theirs = make_project(users["alice"], owned_by(1))
    room = _Room(application, socketio, users, tokens, theirs)
    storage.write_spec(room.owner_key, theirs, copy.deepcopy(SPEC))
    monkeypatch.setattr(room.docs, "_today", lambda: room.day)

    # Its owner, process 1, held its doc and stopped before writing the change.
    as_process(monkeypatch, 1)
    alice = room.tab("alice")
    synced = alice.sync()
    assert synced["ok"] is True, synced
    alice.edit(_type(TYPED))
    room.docs.reset_for_tests()
    assert _code(room.on_disk()["dataflow"]) == "x = 1\n", "the change was written; the test needs it in the log alone"

    # The next start's home process, with no other process listening yet.
    as_process(monkeypatch, 0)
    monkeypatch.setenv("CURIO_BACKEND_PORTS", f"{_a_port_no_one_listens_on()},{_a_port_no_one_listens_on()}")
    monkeypatch.setenv("CURIO_BACKEND_TOKEN", "the start's own secret")
    from utk_curio.backend.app.agents.application import lifecycle
    from utk_curio.backend.app.agents.repositories import project_agents
    from utk_curio.backend.app.collaboration import owner_guard

    owner_guard.reset_for_tests()
    defaults = lifecycle.default_agent_coords()
    assert defaults, "Curio ships no agent every account has"

    with application.test_request_context():
        with owner_guard.before_the_others_serve(True):
            owner_during = owner_guard.elsewhere(theirs, room.owner_key)
            lifecycle.seed_default_agents(room.owner_key, users["alice"])
            open_during = room.docs._open_entry(theirs) is not None

    assert owner_during is None, "during its startup work home must own every dataflow: no other process listens"
    assert open_during, "the startup work read the dataflow through its doc, which held a change its file did not"
    assert room.docs._open_entry(theirs) is None, (
        "home kept a doc of a dataflow process 1 owns, which process 1 opens too once it serves"
    )
    on_disk = room.on_disk()
    missing = sorted(set(defaults) - set(project_agents.project_agents(on_disk)))
    assert missing == [], f"the agents every account has did not reach the dataflow: {missing}"
    assert _code(on_disk["dataflow"]) == TYPED + "x = 1\n", "home dropped the doc without writing what it held"
    assert "sent" not in owner_guard.counts(), "home sent a change to a process that does not listen yet"
    assert owner_guard.elsewhere(theirs, room.owner_key) == 1, "after the startup work the dataflow is process 1's again"
