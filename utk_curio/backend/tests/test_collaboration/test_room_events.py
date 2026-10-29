"""The events a dataflow's room answers: exactly those docs/COLLABORATION.md
lists in "The room's events".

``ROOM_EVENTS`` is that list. The server is held to it here, by the handlers it
has on the room's namespace, whatever way each was registered. The guide is
held to it by the Jest test ``providers/collab/roomEventsDocs.test.ts``, which
reads this file, since the unit tests' image ships no guides. Each tab runs its
own nodes, so the room relays no run and keeps no output
(``test_collaboration_roles.py`` sends it the events it answered before).
"""

from __future__ import annotations

from utk_curio.backend.config import COLLAB_NAMESPACE

from ._support import connect, join, make_project, make_user

#: The room's events, as docs/COLLABORATION.md lists them.
ROOM_EVENTS = (
    "connect",
    "join_session",
    "node_lock",
    "node_unlock",
    "yjs",
    "disconnect",
)


def test_the_room_answers_exactly_the_events_collaboration_lists(collab_app):
    _application, socketio, _ = collab_app

    handled = set(socketio.server.handlers.get(COLLAB_NAMESPACE, {}))

    assert len(set(ROOM_EVENTS)) == len(ROOM_EVENTS), "ROOM_EVENTS names an event twice"
    assert sorted(handled - set(ROOM_EVENTS)) == [], "the room answers events COLLABORATION does not list"
    assert sorted(set(ROOM_EVENTS) - handled) == [], "COLLABORATION lists events the room does not answer"


def test_a_join_brings_the_room_and_no_outputs(collab_app):
    application, socketio, _ = collab_app
    with application.app_context():
        alice, session = make_user("alice")
        token = session.token
        project_id = make_project(alice)

    ack = join(connect(socketio, application, token), project_id)

    assert ack["ok"] is True, ack
    assert {"users", "locks", "activity"} <= set(ack["snapshot"]), ack["snapshot"]
    assert "outputs" not in ack["snapshot"], "the room still keeps outputs"
