"""An agent attached to a dataflow, or taken off it, is told to its room.

The agents' attachments are kept beside the dataflow's doc, so no change of
the doc tells a tab of them. The dataflow's one writer tells the tabs of its
owner and editors instead (``agent_attachments_changed``), whatever writes
it: a person's attach or detach through the routes, or the listing that takes
off the agent of a node removed through the doc. Each tab then lists the
agents again, with no click on its canvas. A watcher's tab, whose dock lists
none, is told nothing, and a write that attaches and takes off no agent, such
as a new title for an agent's chat, tells no one.

alice owns the dataflow, bob is an editor she invited, and carol watches. The
app runs on a SQLite file, as the room's other tests do.

On main, where the room is told nothing of the agents, the first three tests
fail test by test at their check of what the tabs were told; the last guards
how seldom the room is told.
"""

from __future__ import annotations

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
#: What the room tells a tab when an agent is attached to the dataflow or taken off it.
EVENT = "agent_attachments_changed"


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


def _told(socket) -> list[dict]:
    """What the room told *socket* of the dataflow's agents since last read."""
    return [e["args"][0] for e in socket.get_received(namespace=NAMESPACE) if e["name"] == EVENT]


def _the_editors_are_told_once(flow, tabs) -> None:
    for name in ("alice", "bob"):
        assert _told(tabs[name]) == [{"projectId": flow.project}], (
            f"{name}'s tab was not told once that the dataflow's agents changed")
    assert _told(tabs["carol"]) == [], "a watcher's tab was told of the dataflow's agents"


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


def test_the_agent_of_a_node_removed_through_the_doc_is_told_once_the_listing_takes_it_off(flow, tabs):
    """The removal reaches the tabs through the doc; the agent it takes along
    leaves the dataflow when a listing prunes it, a write no route makes."""
    _remove_on_the_canvas(flow.alice, flow.project, "sum")
    for socket in tabs.values():
        _told(socket)

    assert _listed(flow.client, BOB, flow.project) == []

    _the_editors_are_told_once(flow, tabs)


def test_a_write_that_attaches_and_takes_off_no_agent_tells_no_one(flow, tabs):
    r = flow.client.patch(
        f"/api/agents/projects/{flow.project}/attachments/{flow.att}",
        json={"title": "Sums"}, headers=_auth(BOB),
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["title"] == "Sums"

    assert {name: _told(socket) for name, socket in tabs.items()} == {"alice": [], "bob": [], "carol": []}
