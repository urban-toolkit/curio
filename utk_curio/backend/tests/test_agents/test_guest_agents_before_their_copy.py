"""A hosted guest's agents before the guest's own copy of an example is made
(``agents/routes/common.py``'s ``_dataflow``, ``projects/visitor_copies.py``).

In a start of several backend processes a hosted guest's copy of an example
belongs to the process its own id names, made or not yet
(``collaboration/owner_guard.py``), and the guest's page names the copy in
every request once the load of the example answers with its id
(``src/utils/requestHeaders.ts``): its agents' requests too, whose paths name
the example. So the agents' reads the page sends before the guest's first
change makes the copy reach the copy's process, which does not own the
example. It reads the example for them, as a process reads a dataflow it does
not own (``dataflow_docs.read``), makes no copy, and writes nothing of the
example: the guest's agents have not written it, and nothing the guest asks
does. A listing that repairs what it finds writes, which only a dataflow's own
process may, so the guest's listing of the example's agents repairs nothing,
at any process count. The guest's first change makes the copy on its process,
and the listing answers the copy's from then on.

Here this test's process is set as one of two by the variables the launcher
sets, as ``test_collaboration/test_owner_guard.py`` sets it, once the example
of ``test_guest_agent_copies.py`` is made and holds an agent attached to its
canvas, as the shared guest's own account attaches one. Each visitor's sign-in
is made so its copy belongs to the process the example does not.
"""

from __future__ import annotations

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.projects import storage
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_guest_agent_copies import (  # noqa: F401 - shared_example is a fixture
    COORD,
    VISITOR_A,
    VISITOR_B,
    shared_example,
)
from utk_curio.backend.tests.test_collaboration._processes import as_process, as_the_one_process, owner_of


def _visitor_whose_copy_belongs_to(example: str, process: int) -> str:
    """A new visitor's sign-in to the shared guest account, as another
    browser's, whose own copy of *example* belongs to the backend process
    numbered *process* (``visitor_copies.copy_id``, ``shard_of``)."""
    from utk_curio.backend.app.projects import visitor_copies
    from utk_curio.backend.app.users.models import User, UserSession
    from utk_curio.backend.extensions import db

    guest = User.query.filter_by(username=config.CURIO_SHARED_GUEST_USERNAME).one()
    token = next(
        candidate for candidate in (f"hosted-guest-agents-visitor-{n}" for n in range(500))
        if owner_of(visitor_copies.copy_id(candidate, example)) == process
    )
    db.session.add(UserSession(user_id=guest.id, token=token))
    db.session.commit()
    return token


def _attached_to_the_example(client, example: str, monkeypatch) -> str:
    """The Node Builder attached to *example*'s canvas by the shared guest's
    own account, with sign-in off, the one local user, whose example is its
    own dataflow: the example then holds an agent, as an example may ship.
    The attachment's id."""
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    try:
        installed = client.post(f"/api/agents/projects/{example}/install",
                                json={"coord": COORD}, headers=_auth(VISITOR_A))
        assert installed.status_code == 201, installed.get_data(as_text=True)
        attached = client.post(f"/api/agents/projects/{example}/attachments",
                               json={"coord": COORD, "target": {"kind": "canvas"}}, headers=_auth(VISITOR_A))
        assert attached.status_code == 201, attached.get_data(as_text=True)
    finally:
        monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    return attached.get_json()["attachmentId"]


def _listed(client, token: str, example: str):
    """``GET /api/agents/projects/<example>/attachments`` as the page of the
    visitor signed in as *token* asks it, once the load named its copy: the
    list of the agents attached to the dataflow, which the dock and the
    nodes' badges read."""
    return client.get(f"/api/agents/projects/{example}/attachments", headers=_auth(token))


def _ids(answer) -> list:
    return [each["attachmentId"] for each in answer.get_json()["attachments"]]


def test_a_hosted_guests_list_of_its_agents_answers_on_its_copys_process_before_the_copy_is_made(
    client, shared_example, monkeypatch,
):
    """The guest only looks: its copy is not made. Its page's list of the
    agents reaches the process its copy's own id names, which answers the
    example's agents, read as a process reads a dataflow it does not own; it
    makes no copy and writes nothing of the example. Main refused it there
    (421): the listing took a writer's read of the example, which only the
    example's own process may take. The guest's first change, an agent it
    attaches, makes its copy on that process, and the list answers the copy's
    agents from then on; the example stays as it ships."""
    from utk_curio.backend.app.projects import visitor_copies

    example = shared_example
    canvas = _attached_to_the_example(client, example, monkeypatch)
    shipped = storage.read_spec(GUEST_KEY, example)
    examples = owner_of(example)
    copies = 1 - examples
    guest = _visitor_whose_copy_belongs_to(example, copies)
    own = visitor_copies.copy_id(guest, example)
    as_process(monkeypatch, copies)

    listed = _listed(client, guest, example)

    assert listed.status_code == 200, (
        f"{listed.status_code}: process {copies}, which the guest's copy {own} belongs to and the guest's page "
        f"names, refused the guest's list of the agents of example {example}, which process {examples} owns: "
        f"{listed.get_data(as_text=True)}"
    )
    assert _ids(listed) == [canvas], f"the guest's list before its copy is made is not the example's: {_ids(listed)}"
    assert not visitor_copies.is_copy(own), "the guest's list made it a copy"
    assert storage.read_spec(GUEST_KEY, example) == shipped, "the guest's list wrote the example"

    attached = client.post(f"/api/agents/projects/{example}/attachments",
                           json={"coord": COORD, "target": {"kind": "canvas"}}, headers=_auth(guest))
    assert attached.status_code == 201, attached.get_data(as_text=True)
    mine = attached.get_json()["attachmentId"]
    assert visitor_copies.is_copy(own), "the guest's first change made no copy"
    after = _listed(client, guest, example)
    assert after.status_code == 200, after.get_data(as_text=True)
    assert _ids(after) == [canvas, mine], f"the guest's list once its copy is made is not the copy's: {_ids(after)}"
    assert storage.read_spec(GUEST_KEY, example) == shipped, "the guest's change reached the example"


def test_a_hosted_guests_list_of_its_agents_before_its_copy_is_made_writes_nothing_of_the_example(
    client, shared_example, monkeypatch,
):
    """The example holds an agent attached to a node that is gone, as a node
    removed on a canvas no tab saved leaves it. A listing by a dataflow's own
    account takes such an attachment off and writes that; a hosted guest with
    no copy reads the example, which nothing the guest asks writes. So its
    list leaves the attachment out, and the example keeps it, in a start of
    one process too, where the example's process is the copy's."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    example = shared_example
    canvas = _attached_to_the_example(client, example, monkeypatch)
    as_the_one_process(monkeypatch)
    spec = dataflow_docs.live(GUEST_KEY, example)
    spec["dataflow"]["agentAttachments"].append({
        "attachmentId": "on-a-node-that-is-gone", "coord": COORD,
        "target": {"kind": "node", "targetId": "a-node-that-is-gone"},
        "sessionId": "a-session-of-a-node-that-is-gone", "revision": 1,
    })
    written = dataflow_docs.write(GUEST_KEY, example, spec, dataflow_docs.by_curio(GUEST_KEY, "seed"))
    assert written.wrote, "the example's attachment whose node is gone was not written"
    held = storage.read_spec(GUEST_KEY, example)

    listed = _listed(client, VISITOR_B, example)

    assert listed.status_code == 200, listed.get_data(as_text=True)
    assert _ids(listed) == [canvas], f"the guest's list holds an agent whose node is gone: {_ids(listed)}"
    assert storage.read_spec(GUEST_KEY, example) == held, (
        "the guest's list wrote the example: "
        f"{[each['attachmentId'] for each in storage.read_spec(GUEST_KEY, example)['dataflow']['agentAttachments']]}"
    )


#: Each other agent read the guest's page may send before its copy is made,
#: the example's canvas attachment named where it needs one: what it reads,
#: its path, and the answer it must give. The agents the example holds (the
#: dock's and the palette's), the Agent Catalog's listings, a chat's
#: transcript and skills, and whether a Solve runs for it.
_READS = {
    "held": ("the agents the example holds", "/api/agents/projects/{example}", 200),
    "catalog": ("the Agent Catalog", "/api/agents/catalog?projectId={example}", 200),
    "imports": ("the account's imports", "/api/agents/imports?projectId={example}", 200),
    "transcript": ("a chat's transcript", "/api/agents/projects/{example}/attachments/{canvas}/session", 200),
    "skills": ("a chat's skills", "/api/agents/projects/{example}/attachments/{canvas}/skills", 200),
    "solve": ("a chat's Solve", "/api/agents/projects/{example}/attachments/{canvas}/jobs/stream", 404),
}


@pytest.mark.parametrize("kind", list(_READS))
def test_every_other_agent_read_of_a_hosted_guests_page_answers_on_its_copys_process_before_the_copy_is_made(
    client, shared_example, monkeypatch, kind,
):
    """Each reads the example as it is, on the process the guest's copy
    belongs to, and makes no copy."""
    from utk_curio.backend.app.projects import visitor_copies

    example = shared_example
    canvas = _attached_to_the_example(client, example, monkeypatch)
    read, path, status = _READS[kind]
    url = path.format(example=example, canvas=canvas)
    copies = 1 - owner_of(example)
    guest = _visitor_whose_copy_belongs_to(example, copies)
    # In a start of one process first: a listing gives the account the agents
    # Curio adds by default, which in a start of several each dataflow's own
    # process adds over 127.0.0.1, where no test reaches.
    first = client.get(url, headers=_auth(guest))
    assert first.status_code == status, first.get_data(as_text=True)
    as_process(monkeypatch, copies)

    answered = client.get(url, headers=_auth(guest))

    assert answered.status_code == status, (
        f"{answered.status_code}, not {status}: process {copies}, which the guest's copy belongs to, answered "
        f"{read} of example {example}, which process {1 - copies} owns: {answered.get_data(as_text=True)}"
    )
    assert not visitor_copies.is_copy(visitor_copies.copy_id(guest, example)), f"{read} made the guest a copy"
