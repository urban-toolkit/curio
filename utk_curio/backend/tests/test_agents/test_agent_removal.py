"""Removing an agent: from one dataflow, and from all the account's projects.

AGENT-CATALOG says **Remove from project** deletes the agent's attachments
"and their transcripts", and that **Remove from all projects** takes the
agent and its attachments out of every dataflow, the account's list
included. Two promises the code broke, each held here:

- the removal took the attachments out of the dataflow and left each one's
  transcript file behind, which nothing would ever read or delete again (a
  detach and a save that deletes a node delete theirs);
- "Remove from all projects" dropped the account's entry first and then
  walked the projects, so a dataflow that refused the removal (another agent
  there requires it) kept the agent while the account no longer listed it:
  the catalog said it was in none of the projects, new projects stopped
  getting it, and nothing said why.
"""

from __future__ import annotations

from utk_curio.backend.app.agents.repositories import imports
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.projects import storage as projects_storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth

DF = "agent.curio.dataset-finder@1"
NB = "agent.curio.node-builder@1"
DFB = "agent.curio.dataflow-builder@1"
RS = "agent.curio.researcher@1"


def _project(client, token, name: str) -> str:
    body = {"name": name, "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _agents_of(client, token, project_id: str) -> list[str]:
    resp = client.get(f"/api/agents/projects/{project_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return sorted(card["dirName"] for card in resp.get_json()["agents"])


def _chat_with_transcript(client, user, token, project_id: str, coord: str):
    """Attach *coord* to the canvas of *project_id* and give its chat one
    turn: the transcript file a removal must take with it."""
    resp = client.post(f"/api/agents/projects/{project_id}/attachments",
                       json={"coord": coord, "target": {"kind": "canvas"}}, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    card = resp.get_json()
    key = _user_dir_key(user)
    sessions.append_turns(key, project_id, card["sessionId"], card["attachmentId"],
                          [sessions.make_turn("user", "What can you find for this neighborhood?")])
    transcript = sessions._session_path(key, project_id, card["sessionId"])
    assert transcript.exists()
    return transcript


def test_removing_an_agent_from_a_dataflow_deletes_its_attachments_transcripts(
    client, user_and_token, tmp_curio, alice_project,
):
    user, token = user_and_token
    client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": RS}, headers=_auth(token))
    transcript = _chat_with_transcript(client, user, token, alice_project, RS)
    resp = client.delete(f"/api/agents/projects/{alice_project}/{RS}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert len(resp.get_json()["detached"]) == 1
    assert not transcript.exists(), "Remove from project left the attachment's transcript behind"


def test_removing_an_agent_from_all_projects_deletes_its_transcripts_in_each(client, user_and_token, tmp_curio):
    user, token = user_and_token
    first, second = _project(client, token, "Loop shade"), _project(client, token, "Bike lanes")
    assert client.post("/api/agents/imports", json={"coord": RS}, headers=_auth(token)).status_code == 201
    transcripts = [_chat_with_transcript(client, user, token, pid, RS) for pid in (first, second)]
    resp = client.delete(f"/api/agents/imports/{RS}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert [path.exists() for path in transcripts] == [False, False]
    assert RS not in imports.load_imported_agents(_user_dir_key(user))


def test_an_agent_one_dataflow_keeps_stays_in_all_projects_and_says_why(client, user_and_token, tmp_curio):
    """The Dataset Finder is in all the account's projects, and one of them
    also holds the Dataflow Builder, which requires it. Remove from all
    projects answers 409 before it writes anything, naming that dataflow and
    the agents that require it there, and the account keeps the Dataset
    Finder in all its projects, every one of them. A project with no spec has
    nothing to remove and keeps nothing. Once the Dataflow Builder and the
    Node Builder are gone from that dataflow, the removal goes through."""
    user, token = user_and_token
    key = _user_dir_key(user)
    plain = _project(client, token, "Loop shade")
    builder = _project(client, token, "Bike lanes")
    empty = _project(client, token, "Never saved")
    assert client.post(f"/api/agents/projects/{builder}/install", json={"coord": DFB},
                       headers=_auth(token)).status_code == 201
    assert client.post("/api/agents/imports", json={"coord": DF}, headers=_auth(token)).status_code == 201
    assert DF in _agents_of(client, token, plain) and DF in _agents_of(client, token, builder)
    dataflow_docs.close(empty)
    (projects_storage.project_dir(key, empty) / projects_storage.SPEC_FILE).unlink()

    resp = client.delete(f"/api/agents/imports/{DF}", headers=_auth(token))
    assert resp.status_code == 409, resp.get_data(as_text=True)
    said = resp.get_json()["error"]
    assert said == (
        "Dataset Finder stays in all your projects, because other agents require it in Bike lanes "
        "(Dataflow Builder, Node Builder). Remove those agents there first, then remove Dataset Finder again."
    ), said
    assert DF in imports.load_imported_agents(key)
    listed = client.get("/api/agents/imports", headers=_auth(token)).get_json()["agents"]
    assert DF in [card["dirName"] for card in listed]
    assert DF in _agents_of(client, token, plain), "a refused removal took the agent out of another dataflow"
    assert DF in _agents_of(client, token, builder)

    for coord in (DFB, NB):
        assert client.delete(f"/api/agents/projects/{builder}/{coord}", headers=_auth(token)).status_code == 200
    resp = client.delete(f"/api/agents/imports/{DF}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert DF not in imports.load_imported_agents(key)
    assert DF not in _agents_of(client, token, builder)
