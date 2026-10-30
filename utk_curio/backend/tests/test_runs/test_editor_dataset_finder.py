"""The Dataset Finder an editor's Solve asks holds the skills of the owner's
packages as the editor's runs do.

alice's dataflow holds the Node Builder, attached to its node ``lights``, and
the Dataset Finder. Her store holds the package ``ai.test.street-lights@1``,
whose node loads a dataset and whose skill serves that node. bob, an editor
she invited, adds the package to her dataflow from his tab, with that node.
His Solve of the node runs on a job's thread, which holds no request, and
resolves the node's source first: with nothing in the Data Catalog to ground
it, the Solve asks the Dataset Finder for candidates.
The Solve hands that run its asker, its ``acting_user``, so bob's holds only
the skills of the packages alice added herself, which the package bob added is
not, while alice's Solve holds its skill. Once alice adds a node of the
package herself, bob's holds it too.

A tab is a pycrdt doc syncing over a Flask-SocketIO test client
(``test_collaboration/_ydoc_client.py``), whose change is written to the spec
as the server writes it a second later. The model is a fake behind
``providers.run_chat_turn``, which keeps what each run is told, and a run of
the node reaches a fake behind ``runner._http_exec``. The module is here,
beside the other runs' tests, for their database in a file: a Solve writes
from its job's thread.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

LIGHTS = "ai.test.street-lights"
LIGHTS_DIR = f"{LIGHTS}@1"
LIGHTS_NODE = f"{LIGHTS}/lights@1"
SKILL = "street-lamps"
#: Words of the package's skill, which a run handed the skill is told.
WORDS = "the lamps of Test City"
NODE_BUILDER = "agent.curio.node-builder@1"
FINDER = "agent.curio.dataset-finder@1"
ATTACHMENT = "att-street-lamps"
BOB_TOKEN = "bob-token-for-tests"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _account(db, username: str, token: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return user


def _write(folder: Path, files: dict) -> None:
    for relative, text in files.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _lights_package(key: str) -> None:
    """alice's package as an install leaves it: a node that loads a dataset,
    and a skill that serves it."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    _write(user_packages_dir(key) / LIGHTS_DIR, {
        "manifest.json": json.dumps({
            "id": LIGHTS, "version": "1.0.0", "name": "Street lights", "publisher": "Test", "license": "MIT",
            "compatibility": {"major": 1}, "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "lights", "label": "Lights", "category": "computation", "engine": "python",
                "editor": "code", "behavior": "code", "hasCode": True, "loadsDataset": True,
                "inputPorts": [], "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
                "source": "sources/lights.py",
            }],
        }),
        "sources/lights.py": "return 1\n",
        f"skills/{SKILL}/SKILL.md": (
            f"---\nname: {SKILL}\ndescription: Use this skill when a node loads street lamps.\n"
            "license: MIT\nmetadata:\n  author: test\n  curio-templates: lights\n---\n"
            f"Read {WORDS} from the city's open data portal.\n"
        ),
    })


def _node(node_id: str) -> dict:
    """A node of alice's package as a canvas writes it."""
    return {"id": node_id, "type": LIGHTS_NODE, "content": "return 1\n", "in": "DEFAULT", "out": "DEFAULT",
            "goal": "Load the street lamps.", "x": 0, "y": 0}


def _owners_model(client, token: str) -> None:
    """alice's LLM configuration, which her agents answer with whoever asks
    them; its key is a stand-in, no real key."""
    resp = client.post("/api/agents/llm/configs", json={
        "label": "Owner's model", "apiType": "openai_compatible", "baseUrl": "https://llm.example.test/v1",
        "apiKey": "not-a-real-llm-key-alice", "model": "owners-model",
    }, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    resp = client.put("/api/agents/llm/default", json={"configId": resp.get_json()["config"]["id"]},
                      headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)


@pytest.fixture(autouse=True)
def _rooms():
    from utk_curio.backend.app.collaboration import room_state

    room_state.reset_for_tests()
    yield
    room_state.reset_for_tests()


@pytest.fixture()
def flow(client, db, user_and_token):
    """alice's dataflow, with the Node Builder attached to its node
    ``lights``, which no one has added yet, and the Dataset Finder; her
    package in her store, her model, and bob invited to edit it."""
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.app.projects import storage as projects_storage

    alice, alice_token = user_and_token
    bob = _account(db, "bob", BOB_TOKEN)
    key = _key(alice)
    _lights_package(key)
    _owners_model(client, alice_token)
    resp = client.post("/api/projects", json={
        "name": "Street lamps", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": [],
    }, headers=_auth(alice_token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    pid = resp.get_json()["id"]
    spec = projects_storage.read_spec(key, pid)
    spec["dataflow"]["agents"] = [NODE_BUILDER, FINDER]
    spec["dataflow"]["agentAttachments"] = [{
        "attachmentId": ATTACHMENT, "coord": NODE_BUILDER, "target": {"kind": "node", "targetId": "lights"},
    }]
    projects_storage.write_spec(key, pid, spec)
    access.add_editor(alice, pid, "bob")
    return SimpleNamespace(pid=pid, key=key, alice=alice, bob=bob,
                           tokens={"alice": alice_token, "bob": BOB_TOKEN})


def _edit(app, flow, who: str, edit) -> None:
    """*who*'s tab changes alice's dataflow: *edit*, a function of the Trill
    dataflow the tab holds, written into its doc as a canvas writes what
    changed and sent over its socket. The server's doc is then written to
    the spec."""
    from utk_curio.backend.app.collaboration import dataflow_docs, doc_mapping
    from utk_curio.backend.tests.test_collaboration._ydoc_client import synced_tab

    tab = synced_tab(app, flow.tokens[who], flow.pid)
    tab.pump()

    def change(doc):
        base = doc_mapping.doc_to_dataflow(doc)
        target = copy.deepcopy(base)
        edit(target)
        doc_mapping.apply_dataflow(doc, base, target)

    acks = tab.edit(change)
    assert acks and all(ack.get("ok") is True for ack in acks), acks
    assert dataflow_docs.flush(flow.pid), "the server's doc held no change to write"


def _strings(value) -> list:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _strings(item)]
    return []


def _finder_asked(flow) -> bool:
    """Whether a Solve asked the Dataset Finder for the source of the node
    ``lights``: the Finder's attachment on the node, which asking makes."""
    from utk_curio.backend.app.agents.application import dataset_resolution
    from utk_curio.backend.app.projects import storage as projects_storage

    spec = projects_storage.read_spec(flow.key, flow.pid)
    return dataset_resolution.finder_attachment(spec, "lights", user_key=flow.key) is not None


def _solve_told(client, flow, monkeypatch, who: str) -> str:
    """*who*'s Solve of the node ``lights``, to its end: what the runs it made
    were told, every text of each call's messages and options, the Dataset
    Finder's first. The Data Catalog the Solve grounds sources in lists
    nothing, so nothing grounds the node's source before the Finder is asked."""
    from utk_curio.backend.app.agents.application.turns import grounding

    monkeypatch.setattr(grounding, "_catalog_listing_items", lambda project_id: [])
    calls: list = []

    def _model(config, messages, **kwargs):
        calls.append("\n".join(_strings([messages, kwargs])))
        return "{}"

    def _exec(_endpoint, payload):
        return {"stdout": [], "stderr": "", "output": {"path": f"art-{who}", "dataType": "str"}}

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", _model)
    monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
    resp = client.post(f"/api/agents/projects/{flow.pid}/attachments/{ATTACHMENT}/solve-node",
                       json={"nodeId": "lights"}, headers=_auth(flow.tokens[who]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    events = []
    for block in resp.get_data(as_text=True).strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines.get("data") or "null")))
    assert events and events[-1][0] == "done", events
    assert calls, f"the Solve asked no model, so the Dataset Finder was not asked: {events}"
    return "\n".join(calls)


def test_an_editors_solve_asks_the_dataset_finder_with_the_skills_of_her_packages_alone(
    app, client, flow, monkeypatch,
):
    """bob's tab adds alice's street lights package to her dataflow, with the
    node her Node Builder is attached to. bob's Solve of that node asks the
    Dataset Finder for its source, and no run it makes is told the skill the
    package ships, since alice did not add the package herself; alice's Solve
    is. Once alice adds a node of the package herself, bob's Solve is told it
    too."""

    def bobs_change(dataflow: dict) -> None:
        dataflow["packages"] = [*dataflow.get("packages", []), LIGHTS_DIR]
        dataflow["nodes"] = [*dataflow.get("nodes", []), _node("lights")]

    _edit(app, flow, "bob", bobs_change)

    bobs = _solve_told(client, flow, monkeypatch, "bob")
    assert _finder_asked(flow), "bob's Solve did not ask the Dataset Finder"
    assert WORDS not in bobs
    assert WORDS in _solve_told(client, flow, monkeypatch, "alice")

    _edit(app, flow, "alice", lambda dataflow: dataflow.__setitem__(
        "nodes", [*dataflow["nodes"], _node("lights-2")],
    ))
    assert WORDS in _solve_told(client, flow, monkeypatch, "bob")
