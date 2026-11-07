"""An agent attached to a dataflow, taken off it or changed is told to its room.

The agents' attachments are kept beside the dataflow's doc, so no change of
the doc tells a tab of them. The dataflow's one writer tells the tabs of its
owner and editors instead (``agent_attachments_changed``), whatever writes
it: a person's attach, detach or new title for an agent's chat through the
routes, or the listing that takes off the agent of a node removed through the
doc. Each tab then lists the agents again, with no click on its canvas. A
watcher's tab, whose dock lists none, is told nothing, and so is every tab of
a write that leaves the attachments as they were. The room is told at once,
then at most once more per wait (``ATTACHMENTS_TOLD_EVERY_S``): the changes
made during a wait are told when it ends, so a burst's last is told too.

alice owns the dataflow, bob is an editor she invited, and carol watches. The
app runs on a SQLite file, as the room's other tests do. A word can come when
a wait ends, so each test reads what its tabs heard over a while.

On main, where the room is told nothing of the agents, every test but the
guard of a write that changes no attachment fails at its check of what the
tabs were told.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_agent_changes import _setup
from utk_curio.backend.tests.test_agents.test_attachments_follow_the_doc import _listed, _remove_on_the_canvas
from utk_curio.backend.tests.test_agents.test_turn_jobs import _tab

NB = "agent.curio.node-builder@1"
ALICE = "alice-token-room-agents"
BOB = "bob-token-room-agents"
CAROL = "carol-token-room-agents"
#: The room's namespace, as a tab joins it.
NAMESPACE = "/collab"
#: What the room tells a tab when the dataflow's agents change.
EVENT = "agent_attachments_changed"
#: How long a test reads what its tabs were told: past the end of any wait.
HEARD_FOR_S = 1.5


@pytest.fixture()
def flow(tmp_curio, tmp_path):
    """alice's dataflow, a loader feeding a sum, with the Node Builder
    attached to the sum; bob invited to edit it, carol signed in and invited
    to nothing."""
    from utk_curio.backend.app import create_app
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.app.users.models import User, UserSession
    from utk_curio.backend.extensions import db
    from utk_curio.backend.tests._unit_fixtures import TestConfig

    class FileTestConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'room-agents.db'}"

    application = create_app(FileTestConfig)
    with application.app_context():
        db.create_all()
        people = {}
        for username, name, token in (("alice", "Alice", ALICE), ("bob", "Bob", BOB), ("carol", "Carol", CAROL)):
            person = User(username=username, name=name, email=f"{username}@test.com")
            db.session.add(person)
            db.session.flush()
            db.session.add(UserSession(user_id=person.id, token=token))
            people[username] = person
        db.session.commit()
        client = application.test_client()
        project, att = _setup(client, people["alice"], ALICE, target={"kind": "node", "targetId": "sum"})
        access.add_editor(people["alice"], project, "bob")
        yield SimpleNamespace(app=application, client=client, project=project, att=att, **people)
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture()
def tabs(flow):
    """A tab of alice's, one of bob's and one of carol's in the dataflow's room."""
    joined = {"alice": _tab(flow, ALICE), "bob": _tab(flow, BOB), "carol": _tab(flow, CAROL)}
    yield joined
    for socket in joined.values():
        socket.disconnect(namespace=NAMESPACE)


def _heard(tabs, seconds: float = HEARD_FOR_S) -> dict[str, list[dict]]:
    """What the room told each tab of the dataflow's agents over *seconds*."""
    heard: dict[str, list[dict]] = {name: [] for name in tabs}
    end = time.monotonic() + seconds
    while True:
        for name, socket in tabs.items():
            heard[name] += [e["args"][0] for e in socket.get_received(namespace=NAMESPACE) if e["name"] == EVENT]
        if time.monotonic() >= end:
            return heard
        time.sleep(0.05)


def _the_editors_are_told_once(flow, tabs) -> None:
    heard = _heard(tabs)
    for name in ("alice", "bob"):
        assert heard[name] == [{"projectId": flow.project}], (
            f"{name}'s tab was not told once that the dataflow's agents changed: {heard[name]}")
    assert heard["carol"] == [], "a watcher's tab was told of the dataflow's agents"


def _retitle(flow, token, title: str) -> None:
    r = flow.client.patch(
        f"/api/agents/projects/{flow.project}/attachments/{flow.att}",
        json={"title": title}, headers=_auth(token),
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["title"] == title


def test_an_agent_an_editor_attaches_is_told_to_the_owners_and_the_editors_tabs(flow, tabs):
    r = flow.client.post(
        f"/api/agents/projects/{flow.project}/attachments",
        json={"coord": NB, "target": {"kind": "canvas"}}, headers=_auth(BOB),
    )
    assert r.status_code == 201, r.get_data(as_text=True)

    _the_editors_are_told_once(flow, tabs)


def test_an_agent_taken_off_the_dataflow_is_told_to_the_owners_and_the_editors_tabs(flow, tabs):
    r = flow.client.delete(f"/api/agents/projects/{flow.project}/attachments/{flow.att}", headers=_auth(ALICE))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["detached"] is True

    _the_editors_are_told_once(flow, tabs)


def test_a_new_title_for_an_agents_chat_is_told_to_the_owners_and_the_editors_tabs(flow, tabs):
    _retitle(flow, BOB, "Sums")

    _the_editors_are_told_once(flow, tabs)


def test_the_agent_of_a_node_removed_through_the_doc_is_told_once_the_listing_takes_it_off(flow, tabs):
    """The removal reaches the tabs through the doc; the agent it takes along
    leaves the dataflow when a listing prunes it, a write no route makes."""
    _remove_on_the_canvas(flow.alice, flow.project, "sum")
    assert _heard(tabs) == {"alice": [], "bob": [], "carol": []}, "the removal itself is the doc's to tell"

    assert _listed(flow.client, BOB, flow.project) == []

    _the_editors_are_told_once(flow, tabs)


def test_a_write_that_leaves_the_attachments_as_they_were_tells_no_one(flow, tabs):
    """A node's new code, as an agent or a canvas writes it, changes no agent."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects.services import _user_dir_key

    ukey = _user_dir_key(flow.alice)
    spec = dataflow_docs.live(ukey, flow.project)
    for node in spec["dataflow"]["nodes"]:
        if node["id"] == "sum":
            node["content"] = "return input_0 * 2"
    written = dataflow_docs.write(ukey, flow.project, spec, dataflow_docs.person(ukey, "edit"))
    assert written.wrote

    assert _heard(tabs) == {"alice": [], "bob": [], "carol": []}


def test_a_burst_of_changes_is_told_at_once_and_once_more_when_the_wait_ends(flow, tabs, monkeypatch):
    """Three new titles in a row, well inside one wait: the first is told at
    once, and the two after it once, when the wait ends, so the last is told."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    # The fixture's attach was told before the tabs joined; its wait is over.
    time.sleep(0.5)
    monkeypatch.setattr(dataflow_docs, "ATTACHMENTS_TOLD_EVERY_S", 3.0, raising=False)
    for title in ("One", "Two", "Three"):
        _retitle(flow, BOB, title)

    heard = _heard(tabs, seconds=4.0)

    for name in ("alice", "bob"):
        assert heard[name] == [{"projectId": flow.project}] * 2, (
            f"{name}'s tab was not told the burst at once and once more when the wait ended: {heard[name]}")
    assert heard["carol"] == []
    assert [a["title"] for a in _listed(flow.client, ALICE, flow.project)] == ["Three"]
