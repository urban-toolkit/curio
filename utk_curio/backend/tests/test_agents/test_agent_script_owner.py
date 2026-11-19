"""Scripted replies reach the backend process that runs the turns they answer.

The scripted model's queues live in each backend process
(``testing_provider.py``), and a dataflow's turns run in the process that owns
it (``collaboration/owner_guard.py``). In a start of several processes a call
to ``/api/testing/agent-script`` names the dataflow whose turns it scripts in
the ``X-Curio-Dataflow`` header, which nginx routes by, and a process that does
not own that dataflow refuses it: a script that reached the wrong process would
otherwise leave the turn on the fallback reply, and a test pass over a turn it
never scripted. A script for an attachment's runs must name its dataflow. A
script for the shared queue that names none is the home process's, as nginx
sends it. With one process nothing changes (``test_agent_script_routes.py``).
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.tests.test_collaboration._processes import (
    as_process,
    as_the_one_process,
    assert_names_the_owner,
    owned_by,
)

SCRIPT_URL = "/api/testing/agent-script"
ROUTE_HEADER = "X-Curio-Dataflow"


@pytest.fixture(autouse=True)
def _testing_enabled(monkeypatch):
    """The routes 404 unless the scripted provider is available at all."""
    monkeypatch.setattr(testing_provider, "enabled", lambda: True)
    testing_provider.reset()
    yield
    testing_provider.reset()


def test_a_script_reaches_the_process_that_owns_its_dataflow_and_no_other(client, monkeypatch):
    as_process(monkeypatch, 1)
    theirs, ours = owned_by(0), owned_by(1)
    body = {"replies": ["the turn's reply"], "attachmentId": "att-1", "reset": False}

    misrouted = client.post(SCRIPT_URL, json=body, headers={ROUTE_HEADER: theirs})
    queued_by_it = testing_provider.pending()
    read = client.get(SCRIPT_URL, headers={ROUTE_HEADER: theirs})
    released = client.post(f"{SCRIPT_URL}/release", json={"hold": "slow"}, headers={ROUTE_HEADER: theirs})
    dropped = client.delete(SCRIPT_URL, headers={ROUTE_HEADER: theirs})
    owned = client.post(SCRIPT_URL, json=body, headers={ROUTE_HEADER: ours})
    with testing_provider.answering("att-1"):
        reply = testing_provider.run_scripted_completion([])

    assert misrouted.status_code == 421, misrouted.get_data(as_text=True)
    assert_names_the_owner(misrouted.get_json()["error"], theirs, owner=0, here=1)
    assert queued_by_it == 0, "a script the process does not own the dataflow of was queued"
    assert (read.status_code, released.status_code, dropped.status_code) == (421, 421, 421), (
        read.get_data(as_text=True), released.get_data(as_text=True), dropped.get_data(as_text=True))
    assert owned.status_code == 200, owned.get_data(as_text=True)
    assert reply == "the turn's reply"


def test_a_script_for_an_attachment_names_its_dataflow_when_there_are_several_processes(client, monkeypatch):
    as_process(monkeypatch, 1)

    unnamed = client.post(SCRIPT_URL, json={"replies": ["lost"], "attachmentId": "att-1"})
    queued_by_it = testing_provider.pending()
    shared = client.post(SCRIPT_URL, json={"replies": ["for the home process"]})
    queued_for_home = testing_provider.pending()
    as_the_one_process(monkeypatch)
    alone = client.post(SCRIPT_URL, json={"replies": ["one process"], "attachmentId": "att-1"})

    assert unnamed.status_code == 400, unnamed.get_data(as_text=True)
    assert ROUTE_HEADER in unnamed.get_json()["error"], unnamed.get_json()
    assert queued_by_it == 0
    assert shared.status_code == 200 and queued_for_home == 1, shared.get_data(as_text=True)
    assert alone.status_code == 200, "a start of one process asked for the dataflow's key"
