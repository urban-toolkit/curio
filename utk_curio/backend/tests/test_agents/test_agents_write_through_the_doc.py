"""The agents write a dataflow through its doc (``collaboration/dataflow_docs.py``):
a tab in the dataflow's room gets each change an agent makes as it lands, and
the agent's change never replaces code someone typed while it worked.

Each test opens a tab of alice's dataflow, a pycrdt doc syncing over a
Flask-SocketIO test client (``test_collaboration/_ydoc_client.py``), before
the agent writes, and asserts what reaches that tab through its own socket.
The route tests' helpers are reached through their modules, so their classes
run only in their own files.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth

#: The agent that writes node code: proposals' and Solve's.
NODE_BUILDER = "agent.curio.node-builder@1"


@pytest.fixture(autouse=True)
def _rooms():
    from utk_curio.backend.app.collaboration import room_state

    room_state.reset_for_tests()
    yield
    room_state.reset_for_tests()


def _tab(app, token, project_id):
    from utk_curio.backend.tests.test_collaboration._ydoc_client import synced_tab

    return synced_tab(app, token, project_id)


def _origins(project_id, root="nodes"):
    from utk_curio.backend.tests.test_collaboration._ydoc_client import Origins

    return Origins(project_id, root)


def _typed(node_id: str, text: str):
    """A tab's change that types *text* at the start of *node_id*'s code."""

    def change(doc):
        from pycrdt import Map, Text

        node = doc.get("nodes", type=Map)[node_id]
        if "content" in node and isinstance(node["content"], Text):
            node["content"].insert(0, text)
        else:
            node["content"] = Text(text)

    return change


def _nodes(tab) -> dict:
    return {node["id"]: node for node in tab.dataflow()["nodes"]}


def _on_disk(user, project_id) -> dict:
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    return storage.read_spec(_user_dir_key(user), project_id)


def _minted_plan(client, user, token, project_id, monkeypatch):
    """A Dataflow Builder plan minted and not applied, as Solve's tests mint
    one (``TestSolve._applied_plan``): the attachment and the proposal id."""
    from utk_curio.backend.tests.test_agents import test_routes_proposals as proposal_routes

    helper = proposal_routes.TestDataflowPlanMint()
    att_id, _calls = helper._setup(client, user, token, project_id, monkeypatch)
    monkeypatch.setattr(
        "utk_curio.backend.app.execution.runner._http_exec",
        lambda endpoint, payload: {"stdout": [], "stderr": "",
                                   "output": {"path": "art-1", "dataType": "dataframe"}},
    )
    client.post(f"/api/agents/projects/{project_id}/install", json={"coord": NODE_BUILDER}, headers=_auth(token))
    run = helper._run(client, token, project_id, att_id)
    proposal = next(p for p in run.get_json()["content"] if p["type"] == "proposal")
    return att_id, proposal["proposalId"]


def _apply(client, token, project_id, att_id, proposal_id):
    return client.post(
        f"/api/agents/projects/{project_id}/attachments/{att_id}/proposals/{proposal_id}/apply",
        headers=_auth(token),
    )


def _solve(client, token, project_id, att_id):
    return client.post(f"/api/agents/projects/{project_id}/attachments/{att_id}/solve", json={}, headers=_auth(token))


def _content_proposal(client, token, project_id, monkeypatch):
    """A Node Builder's pending proposal of new code for node n1 ("print(1)"),
    minted as the review tests mint one: the attachment and the proposal."""
    from utk_curio.backend.tests.test_agents import test_routes_proposals as proposal_routes

    helper = proposal_routes.TestReviewProposals()
    att_id, _calls = helper._setup(client, token, project_id, monkeypatch)
    proposal = helper._proposal_from_run(helper._run(client, token, project_id, att_id))
    return att_id, proposal


def test_an_applied_code_proposal_reaches_a_tab_in_the_room(app, client, user_and_token, tmp_curio, alice_project,
                                                            monkeypatch):
    from utk_curio.backend.app.collaboration.dataflow_docs import by_agent
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    att_id, proposal = _content_proposal(client, token, alice_project, monkeypatch)
    tab = _tab(app, token, alice_project)
    origins = _origins(alice_project)

    resp = _apply(client, token, alice_project, att_id, proposal["proposalId"])

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert _nodes(tab)["n1"].get("content") == "print(2)", "the applied code never reached the tab"
    assert by_agent(NODE_BUILDER, _user_dir_key(user), "apply") in origins.seen, origins.seen


def test_code_typed_while_its_proposal_is_applied_stays_and_the_proposal_goes_stale(
    app, client, user_and_token, tmp_curio, alice_project, monkeypatch,
):
    """alice types in n1 after the apply read the node and before it writes:
    the doc keeps what she typed, the apply lands nothing and says the node
    changed, as a node changed before the apply does."""
    from utk_curio.backend.app.agents.application import attachments

    user, token = user_and_token
    att_id, proposal = _content_proposal(client, token, alice_project, monkeypatch)
    tab = _tab(app, token, alice_project)
    listed = attachments.list_attachments
    typed = []

    def typed_meanwhile(spec):
        if not typed:
            typed.append(True)
            tab.edit(_typed("n1", "# mine\n"))
        return listed(spec)

    monkeypatch.setattr(attachments, "list_attachments", typed_meanwhile)

    resp = _apply(client, token, alice_project, att_id, proposal["proposalId"])

    assert typed, "nothing was typed while the apply ran"
    assert resp.status_code == 409, resp.get_data(as_text=True)
    assert "changed since this was proposed" in resp.get_json()["error"]
    node = next(n for n in _on_disk(user, alice_project)["dataflow"]["nodes"] if n["id"] == "n1")
    assert node["content"] == "# mine\nprint(1)", "the apply replaced what alice typed"
    record = attachments.get_attachment(_on_disk(user, alice_project), att_id)
    assert record["activeProposal"]["status"] == "stale"
    assert _nodes(tab)["n1"]["content"] == "# mine\nprint(1)"


def test_an_applied_plan_reaches_a_tab_in_the_room(app, client, user_and_token, tmp_curio, alice_project,
                                                   monkeypatch):
    user, token = user_and_token
    att_id, proposal_id = _minted_plan(client, user, token, alice_project, monkeypatch)
    tab = _tab(app, token, alice_project)

    resp = _apply(client, token, alice_project, att_id, proposal_id)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    created = {node["id"] for node in resp.get_json()["appliedGraph"]["nodes"]}
    seen = _nodes(tab)
    assert created and created <= set(seen), f"the plan's nodes never reached the tab: {sorted(seen)}"
    ends = {(edge.get("source"), edge.get("target")) for edge in tab.dataflow()["edges"]}
    applied = resp.get_json()["appliedGraph"].get("edges") or []
    assert {(edge.get("source"), edge.get("target")) for edge in applied} <= ends


def test_a_solve_waves_code_reaches_a_tab_in_the_room(app, client, user_and_token, tmp_curio, alice_project,
                                                     monkeypatch):
    from utk_curio.backend.app.collaboration.dataflow_docs import Actor

    user, token = user_and_token
    att_id, proposal_id = _minted_plan(client, user, token, alice_project, monkeypatch)
    assert _apply(client, token, alice_project, att_id, proposal_id).status_code == 200
    tab = _tab(app, token, alice_project)
    origins = _origins(alice_project)

    body = _solve(client, token, alice_project, att_id).get_json()

    contents = {item["nodeId"]: item["content"] for item in body["appliedContents"]}
    assert contents, body
    seen = _nodes(tab)
    assert {node_id: seen[node_id].get("content") for node_id in contents} == contents, (
        "the wave's code never reached the tab"
    )
    assert any(isinstance(o, Actor) and o.what == "solve" and o.agent == NODE_BUILDER for o in origins.seen), (
        origins.seen
    )


def test_code_typed_while_a_solve_wave_runs_stays_and_the_wave_says_so(app, client, user_and_token, tmp_curio,
                                                                       alice_project, monkeypatch):
    """alice types into a node after the wave read the dataflow and before it
    writes the node's code. What she typed survives, in the file and in her
    tab; the wave's code for that node is refused and the wave says so (the
    node skipped, with why), while its other nodes get their code."""
    from utk_curio.backend.app.agents.application.solve.batch import SolveBatch

    user, token = user_and_token
    att_id, proposal_id = _minted_plan(client, user, token, alice_project, monkeypatch)
    assert _apply(client, token, alice_project, att_id, proposal_id).status_code == 200
    tab = _tab(app, token, alice_project)
    apply_contents = SolveBatch.apply_contents
    typed: list = []

    def typed_meanwhile(self, spec_doc):
        writing = [item["nodeId"] for item in self.applied_contents if item["nodeId"] not in self.persisted]
        if writing and not typed:
            typed.append(writing[0])
            tab.edit(_typed(writing[0], "# mine\n"))
        return apply_contents(self, spec_doc)

    monkeypatch.setattr(SolveBatch, "apply_contents", typed_meanwhile)

    body = _solve(client, token, alice_project, att_id).get_json()

    assert typed, "nothing was typed while the wave ran"
    mine = typed[0]
    result = body["results"][mine]
    assert result["status"] == "skipped" and "changed while Solve worked" in (result.get("reason") or ""), result
    assert body["builderSession"]["nodeRuns"][mine] == "skipped"
    assert mine not in {item["nodeId"] for item in body["appliedContents"]}
    on_disk = {n["id"]: n for n in _on_disk(user, alice_project)["dataflow"]["nodes"]}
    assert on_disk[mine]["content"] == "# mine\n", "the wave's code replaced what alice typed"
    seen = _nodes(tab)
    assert seen[mine]["content"] == "# mine\n", "the tab got the wave's code for alice's node"
    others = {item["nodeId"]: item["content"] for item in body["appliedContents"]}
    assert others and {node_id: seen[node_id].get("content") for node_id in others} == others


def test_a_package_draft_whose_nodes_fail_is_stale_on_record(app, client, user_and_token, tmp_curio, alice_project,
                                                             monkeypatch):
    """A package draft installs, then its nodes cannot be created: the apply
    is refused as stale, and the spec on record says so, so the card does not
    offer the apply again."""
    from types import SimpleNamespace

    from utk_curio.backend.app.agents.application import attachments
    from utk_curio.backend.app.packages.builder import promotion
    from utk_curio.backend.app.packages.repositories import manifests
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    key = _user_dir_key(user)
    spec = storage.read_spec(key, alice_project)
    spec["dataflow"]["agents"] = [NODE_BUILDER]
    spec["dataflow"]["agentAttachments"] = [{
        "attachmentId": "a1", "coord": NODE_BUILDER, "target": {"kind": "canvas"}, "revision": 1,
        "activeProposal": {
            "proposalId": "p1", "tool": "package.draft.apply", "status": "pending",
            "target": "curio.draft-test@1", "artifactDigest": "d" * 64, "packageName": "Draft",
            "requestedNodes": [{"templateId": "missing", "content": "x = 1"}],
        },
    }]
    storage.write_spec(key, alice_project, spec)
    monkeypatch.setattr(promotion, "promote", lambda *args, **kwargs: {})
    monkeypatch.setattr(promotion, "rollback", lambda *args, **kwargs: {"rollback": {"status": "rolled-back"}})
    monkeypatch.setattr(manifests, "load_package_manifest", lambda path: SimpleNamespace(templates=[]))

    resp = _apply(client, token, alice_project, "a1", "p1")

    assert resp.status_code == 409, resp.get_data(as_text=True)
    record = attachments.get_attachment(storage.read_spec(key, alice_project), "a1")
    assert record["activeProposal"]["status"] == "stale", "the refused apply left its proposal pending"
