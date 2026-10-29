"""An agent attached to a node, or a connection, goes with it when the node is
removed through the dataflow's doc, as a canvas bound to it removes one.

No tab saves a dataflow its canvas is bound to, and the whole save pruned the
attachments of removed nodes (dev/32). The attachments' listing prunes them
instead, and their transcripts with them, so the canvas's dock, which lists
them again once the server has the removal, shows no agent on a node that is
gone. An attachment whose node is still there stays.

New names are imported inside each test, so the module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

from utk_curio.backend.tests._support.agent_routes import _auth

COORD = "agent.curio.node-builder@1"


def _dataflow_with_an_agent_on_n1(client, token, project_id):
    """The dataflow: nodes n1 and n2 joined by e1, and the Node Builder
    attached to n1."""
    r = client.put(
        f"/api/projects/{project_id}",
        json={"name": "p", "spec": {"dataflow": {
            "nodes": [{"id": "n1", "content": "print(1)"}, {"id": "n2", "content": "print(2)"}],
            "edges": [{"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "out", "targetHandle": "in"}],
            "packages": [],
        }}, "outputs": []},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    r = client.post(f"/api/agents/projects/{project_id}/install", json={"coord": COORD}, headers=_auth(token))
    assert r.status_code == 201, r.get_data(as_text=True)
    on_node = client.post(
        f"/api/agents/projects/{project_id}/attachments",
        json={"coord": COORD, "target": {"kind": "node", "targetId": "n1"}}, headers=_auth(token),
    )
    assert on_node.status_code == 201, on_node.get_data(as_text=True)
    return on_node.get_json()


def _listed(client, token, project_id) -> list:
    r = client.get(f"/api/agents/projects/{project_id}/attachments", headers=_auth(token))
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["attachments"]


def _remove_on_the_canvas(user, project_id, node_id):
    """The node and its connections removed through the doc, as a bound
    canvas's change lands: no save of the dataflow."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects.services import _user_dir_key

    ukey = _user_dir_key(user)
    spec = dataflow_docs.live(ukey, project_id)
    flow = spec["dataflow"]
    flow["nodes"] = [n for n in flow["nodes"] if n["id"] != node_id]
    flow["edges"] = [e for e in flow["edges"] if node_id not in (e["source"], e["target"])]
    dataflow_docs.write(ukey, project_id, spec, dataflow_docs.person(ukey, "edit"))


def test_a_node_removed_through_the_doc_takes_its_agent_and_transcript_with_it(
    client, user_and_token, alice_project, tmp_curio,
):
    from utk_curio.backend.app.agents.repositories import sessions
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    attached = _dataflow_with_an_agent_on_n1(client, token, alice_project)
    ukey = _user_dir_key(user)
    sessions.append_turns(ukey, alice_project, attached["sessionId"], attached["attachmentId"],
                          [sessions.make_turn("user", "What does n1 do?")])
    transcript = sessions._session_path(ukey, alice_project, attached["sessionId"])
    assert transcript.exists()

    _remove_on_the_canvas(user, alice_project, "n1")

    assert [a["attachmentId"] for a in _listed(client, token, alice_project)] == []
    kept = (storage.read_spec(ukey, alice_project) or {}).get("dataflow", {}).get("agentAttachments") or []
    assert [a.get("attachmentId") for a in kept] == [], "the dataflow still holds the removed node's agent"
    assert not transcript.exists(), "the removed node's agent left its transcript behind"


def test_an_agent_whose_node_is_still_there_stays(client, user_and_token, alice_project, tmp_curio):
    user, token = user_and_token
    attached = _dataflow_with_an_agent_on_n1(client, token, alice_project)

    _remove_on_the_canvas(user, alice_project, "n2")

    assert [a["attachmentId"] for a in _listed(client, token, alice_project)] == [attached["attachmentId"]]
