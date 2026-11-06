"""Nothing a hosted guest does to an example reaches the example or another
guest (``projects/visitor_copies.py``).

Every hosted guest signs in to the one shared guest account, which owns the
examples. Visitor A here does on an example everything a guest's canvas and
agents do: A changes a node's code through the room, plays a node, adds and
removes datasets, renames the dataflow, reads its categories and history, asks
an agent that reads the dataflow and searches the Data Catalog, applies a
Dataset Finder's install, and has an agent plan nodes and Solve them. All of it
lands on A's own copy, and the agents read the copy as A's canvas shows it.
Visitor B then opens the example as it ships, and the example's spec,
manifest and kept outputs, and the guest account's dataset store, are byte
for byte what they were. The language model is scripted. Each test imports
what main lacks inside itself.
"""

from __future__ import annotations

import hashlib
import json

from pycrdt import Map

from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (  # noqa: F401 - fixtures
    SHIPPED,
    VISITOR_A,
    VISITOR_B,
    _digests,
    _in_the_dataflow,
    _open,
    _play,
    _results,
    app,
    datasets,
    example,
    sandbox,
)

NODE_BUILDER = "agent.curio.node-builder@1"
DATAFLOW_BUILDER = "agent.curio.dataflow-builder@1"
DATASET_FINDER = "agent.curio.dataset-finder@1"
#: What A types into node a's code, through the room.
MARK = "# A's own change\n"


def _kept_on(project_id: str) -> str:
    """The outputs kept on *project_id*, every column of every row, by digest."""
    from utk_curio.backend.app.runs.models import KeptStepOutput

    rows = sorted(
        json.dumps({column.name: str(getattr(row, column.name)) for column in row.__table__.columns}, sort_keys=True)
        for row in KeptStepOutput.query.filter_by(project_id=project_id)
    )
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _script(monkeypatch, replies: list[str]) -> list:
    """The provider answers with *replies*, one per call, the last one again
    after them, and a conversation title apart; the messages of each call."""
    calls: list = []

    def _fake_run(config_, messages, **kwargs):
        from utk_curio.backend.app.agents.application.turns import titles

        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        calls.append(messages)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _fake_run)
    return calls


def _tool(tool: str, params: dict) -> str:
    return "```curio.v1\n" + json.dumps({"toolRequest": {"tool": tool, "params": params}}) + "\n```"


def _attached(client, project_id: str, coord: str, target: dict) -> dict:
    """A's attachment of the agent *coord*, installed in the dataflow first."""
    installed = client.post(f"/api/agents/projects/{project_id}/install", json={"coord": coord},
                            headers=_auth(VISITOR_A))
    assert installed.status_code in (200, 201), installed.get_data(as_text=True)
    attached = client.post(f"/api/agents/projects/{project_id}/attachments",
                           json={"coord": coord, "target": target}, headers=_auth(VISITOR_A))
    assert attached.status_code == 201, attached.get_data(as_text=True)
    return attached.get_json()


def _edit_through_the_room(app, project_id: str) -> str:
    """A's tab of the example types MARK into node a's code; the id of the
    room it joined, A's own copy's."""
    from utk_curio.backend.tests.test_collaboration._support import NAMESPACE, connect, join
    from utk_curio.backend.tests.test_collaboration._ydoc_client import DocClient

    socket = connect(app.extensions["socketio"], app, VISITOR_A)
    joined = join(socket, project_id)
    assert joined["ok"] is True and joined["role"] == "owner", joined
    socket.get_received(namespace=NAMESPACE)
    tab = DocClient(socket, joined["projectId"])
    assert tab.sync()["ok"] is True

    def change(doc):
        doc.get("nodes", type=Map)["a"]["content"].insert(0, MARK)

    acks = tab.edit(change)
    assert acks and all(ack.get("ok") for ack in acks), acks
    return joined["projectId"]


def _code_of(client, token: str, project_id: str, node: str = "a") -> str:
    nodes = _open(client, token, project_id)["spec"]["dataflow"]["nodes"]
    return next(n for n in nodes if n["id"] == node)["content"]


def test_everything_a_hosted_guest_does_stays_in_its_own_copy(client, example, datasets, sandbox, monkeypatch):
    from flask import g

    from utk_curio.backend.app.agents.application import dataflow_block, tools
    from utk_curio.backend.app.agents.application import spec_reads
    from utk_curio.backend.app.agents.application.proposals import store
    from utk_curio.backend.app.agents.domain import content
    from utk_curio.backend.app.projects import visitor_copies
    from utk_curio.backend.app.users.models import User

    uploaded = datasets
    before, kept_before = _digests(example), _kept_on(example)
    as_shipped = _open(client, VISITOR_B, example)["spec"]
    test_routes_proposals.TestNodeCreate()._write_builtin_package(GUEST_KEY)
    app = client.application

    # A's edit through the room makes A's copy, which A's canvas opens.
    own = _edit_through_the_room(app, example)
    assert own == visitor_copies.copy_id(VISITOR_A, example)
    assert _code_of(client, VISITOR_A, example).startswith(MARK)

    # A plays a node, renames the dataflow, reads its categories and history.
    _play(client, VISITOR_A, example, "a")
    renamed = client.put(f"/api/projects/{example}", json={"name": "Mine"}, headers=_auth(VISITOR_A))
    assert renamed.status_code == 200, renamed.get_data(as_text=True)
    for token in (VISITOR_A, VISITOR_B):
        categories = client.get(f"/api/projects/{example}/categories", headers=_auth(token))
        assert categories.status_code == 200, categories.get_data(as_text=True)
    history = client.get(f"/api/projects/{example}/history", headers=_auth(VISITOR_A))
    assert history.status_code == 200, history.get_data(as_text=True)
    assert history.get_json()["versions"], "A's copy has no history"
    unmade = client.get(f"/api/projects/{example}/history", headers=_auth(VISITOR_B))
    assert unmade.status_code == 200 and unmade.get_json()["versions"] == [], unmade.get_data(as_text=True)

    # An agent on A's node reads the dataflow as A's canvas shows it, and
    # searches A's Data Catalog for the copy.
    node_builder = _attached(client, example, NODE_BUILDER, {"kind": "node", "targetId": "a"})
    calls = _script(monkeypatch, [_tool("dataflow.read", {}), _tool("catalog.search", {"q": "trees"}), "Read."])
    run = client.post(f"/api/agents/projects/{example}/attachments/{node_builder['attachmentId']}/run",
                      json={"message": "what does this node do?"}, headers=_auth(VISITOR_A))
    assert run.status_code == 200, run.get_data(as_text=True)
    assert len(calls) >= 3, len(calls)
    assert MARK.strip() in json.dumps(calls[1]), "the agent read the example, not A's copy"
    assert uploaded in json.dumps(calls[2]), "the agent's catalog.search failed on A's copy"
    guest = User.query.filter_by(is_guest=True).first()
    with app.test_request_context(headers={"Authorization": f"Bearer {VISITOR_A}"}):
        g.user = guest
        status, found = tools.execute_read_tool("catalog.search", user_key=GUEST_KEY, project_id=own,
                                                target=None, params={"q": "trees"})
        block = dataflow_block.read_datasets(own)
    assert status == "ok", found
    assert uploaded in {row["id"] for row in json.loads(found)["datasets"]}
    assert [dataset.id for dataset in block] == [SHIPPED]

    # The Dataset Finder's install, applied by A, adds the dataset to A's copy.
    finder = _attached(client, example, DATASET_FINDER, {"kind": "canvas"})
    spec = spec_reads._live_spec_or_404(GUEST_KEY, own)
    part = content.make_proposal_part(proposal_id="finder-install", tool="dataset.install",
                                      summary="Add the trees", preview=uploaded, pins={"datasetId": uploaded})
    store._store_proposal(
        GUEST_KEY, own, spec, {"attachment_id": finder["attachmentId"], "session_id": finder["sessionId"]},
        {"proposalId": "finder-install", "tool": "dataset.install", "datasetId": uploaded,
         "summary": "Add the trees", "status": "pending"},
        part,
    )
    applied = client.post(
        f"/api/agents/projects/{example}/attachments/{finder['attachmentId']}/proposals/finder-install/apply",
        headers=_auth(VISITOR_A),
    )
    assert applied.status_code == 200, applied.get_data(as_text=True)
    assert _in_the_dataflow(client, VISITOR_A, example) == [SHIPPED, uploaded]

    # A removes it and adds it again through the Data Catalog.
    removed = client.delete(f"/api/dataflows/{example}/datasets/{uploaded}", headers=_auth(VISITOR_A))
    assert removed.status_code == 200, removed.get_data(as_text=True)
    added = client.post(f"/api/dataflows/{example}/datasets/install", json={"datasetId": uploaded},
                        headers=_auth(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)

    # An agent plans two nodes on A's copy, and Solve writes their code, with
    # the Node Builder installed above.
    planner = _attached(client, example, DATAFLOW_BUILDER, {"kind": "canvas"})
    _script(monkeypatch, ["Here is the plan.\n" + test_routes_proposals.TestDataflowPlanMint()._plan_tail()])
    monkeypatch.setattr(
        "utk_curio.backend.app.execution.runner._http_exec",
        lambda endpoint, payload: {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}},
    )
    planned = client.post(f"/api/agents/projects/{example}/attachments/{planner['attachmentId']}/run",
                          json={"message": "plan it"}, headers=_auth(VISITOR_A))
    assert planned.status_code == 200, planned.get_data(as_text=True)
    solved = client.post(f"/api/agents/projects/{example}/attachments/{planner['attachmentId']}/solve",
                         json={}, headers=_auth(VISITOR_A))
    assert solved.status_code == 200, solved.get_data(as_text=True)
    landed = solved.get_json()["appliedContents"]
    assert len(landed) == 2, solved.get_json()

    # A's copy holds all of it.
    mine = _open(client, VISITOR_A, example)
    assert mine["project"]["name"] == "Mine"
    assert _code_of(client, VISITOR_A, example).startswith(MARK)
    assert {item["nodeId"] for item in landed} <= {n["id"] for n in mine["spec"]["dataflow"]["nodes"]}
    assert _in_the_dataflow(client, VISITOR_A, example) == [SHIPPED, uploaded]
    # B opens the example as it ships, with none of A's results.
    theirs = _open(client, VISITOR_B, example)
    assert theirs["project"]["name"] == "Example"
    assert theirs["spec"]["dataflow"]["nodes"] == as_shipped["dataflow"]["nodes"]
    assert _in_the_dataflow(client, VISITOR_B, example) == [SHIPPED]
    assert _results(client, VISITOR_B, example) == {}
    # And the example, its kept outputs and the guests' store are as they were.
    assert _digests(example) == before
    assert _kept_on(example) == kept_before
