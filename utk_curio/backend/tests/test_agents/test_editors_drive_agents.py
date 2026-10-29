"""The editors a dataflow's owner invited drive its agents (step 15a).

alice owns the dataflow, bob is an editor she invited, and carol is signed in
and invited to nothing, so she watches. The owner and the editors drive the
dataflow's agents: on the owner's storage, model and key, in chats they share,
where each message names its writer. A watcher, and a hosted guest on another
account's dataflow, are refused with a 403 and see nothing private. An editor's
run lists and resolves only the editor's own saved keys, never the owner's. An
install an editor's chat asks for waits for the owner's review, and so does a
download that confirming a dataset selection would make. An editor's agent
change is a point of the dataflow's history named after the editor.

New names are imported inside each test, so the module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests._support.agent_routes import _auth

COORD = "agent.curio.node-builder@1"
BOB_TOKEN = "bob-token-for-tests"
CAROL_TOKEN = "carol-token-for-tests"
#: Stand-ins for saved keys: a name, its host and its value. None is a real key.
ALICE_KEY = ("alices-census", "census.alice.example", "not-a-real-key-alice")
BOB_KEY = ("bobs-weather", "weather.bob.example", "not-a-real-key-bob")
ALICE_LLM_KEY = "not-a-real-llm-key-alice"
BOB_LLM_KEY = "not-a-real-llm-key-bob"


def _account(db, username: str, name: str, token: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=name, email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return user


@pytest.fixture()
def people(db, user_and_token):
    alice, alice_token = user_and_token
    return SimpleNamespace(
        alice=alice, alice_token=alice_token,
        bob=_account(db, "bob", "Bob", BOB_TOKEN),
        carol=_account(db, "carol", "Carol", CAROL_TOKEN),
    )


@pytest.fixture()
def flow(client, people, alice_project, tmp_curio):
    """alice's dataflow: one node with the Node Builder attached to it, and
    bob invited to edit it."""
    from utk_curio.backend.app.projects import access

    token = people.alice_token
    r = client.put(
        f"/api/projects/{alice_project}",
        json={"name": "p", "spec": {"dataflow": {"nodes": [{"id": "n1", "content": "print(1)"}],
                                                 "edges": [], "packages": []}}, "outputs": []},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    r = client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": COORD}, headers=_auth(token))
    assert r.status_code == 201, r.get_data(as_text=True)
    attached = client.post(
        f"/api/agents/projects/{alice_project}/attachments",
        json={"coord": COORD, "target": {"kind": "node", "targetId": "n1"}}, headers=_auth(token),
    ).get_json()
    access.add_editor(people.alice, alice_project, "bob")
    return SimpleNamespace(
        pid=alice_project, att=attached["attachmentId"], session=attached["sessionId"],
        owner_key=str(people.alice.id),
    )


class _Script:
    """The provider: each run's configuration and messages, answered in order."""

    def __init__(self, replies=("Here is what the node does.",)):
        self.replies = list(replies)
        self.calls: list = []

    def __call__(self, config, messages, **kwargs):
        from utk_curio.backend.app.agents.application.turns import titles

        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        self.calls.append((config, messages))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]


@pytest.fixture()
def script(monkeypatch):
    replies = _Script()
    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.run_chat_turn", replies)
    return replies


def _run(client, flow, token, message):
    return client.post(
        f"/api/agents/projects/{flow.pid}/attachments/{flow.att}/run",
        json={"message": message}, headers=_auth(token),
    )


def _turns(client, flow, token):
    r = client.get(f"/api/agents/projects/{flow.pid}/attachments/{flow.att}/session", headers=_auth(token))
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["turns"]


def _person(user) -> dict:
    return {"kind": "person", "account": str(user.id), "name": user.name}


def _own_model(client, token, model, api_key):
    r = client.post("/api/agents/llm/configs", json={
        "label": f"Own {model}", "apiType": "openai_compatible", "baseUrl": "https://llm.example.test/v1",
        "apiKey": api_key, "model": model,
    }, headers=_auth(token))
    assert r.status_code == 201, r.get_data(as_text=True)
    config_id = r.get_json()["config"]["id"]
    r = client.put("/api/agents/llm/default", json={"configId": config_id}, headers=_auth(token))
    assert r.status_code == 200, r.get_data(as_text=True)


def _save_key(user, name, host, value):
    from utk_curio.backend.app.users.connection_keys import default_store

    default_store().put(str(user.id), name, host, value, "query:key")


# ---------------------------------------------------------------------------
# Who drives the dataflow's agents
# ---------------------------------------------------------------------------

def test_an_invited_editors_chat_drives_the_owners_agent_on_the_owners_model_and_key(
    client, people, flow, script,
):
    """bob's message runs the owner's agent on the model and the key alice's
    API Settings give it, not bob's, and the exchange is kept in alice's
    dataflow, where alice reads it."""
    _own_model(client, people.alice_token, "owners-model", ALICE_LLM_KEY)
    _own_model(client, BOB_TOKEN, "editors-model", BOB_LLM_KEY)

    r = _run(client, flow, BOB_TOKEN, "What does this node do?")
    assert r.status_code == 200, r.get_data(as_text=True)
    config, _messages = script.calls[0]
    assert (config.model, config.api_key) == ("owners-model", ALICE_LLM_KEY)
    turns = _turns(client, flow, people.alice_token)
    assert [(t["role"], t["text"]) for t in turns] == [
        ("user", "What does this node do?"), ("agent", "Here is what the node does."),
    ]


def test_each_message_names_its_writer(client, people, flow, script, monkeypatch):
    """The owner and the editor share the attachment's chat: each message
    names who wrote it, streamed or not, and the agent's replies name nobody."""
    def _stream(config, messages, **kwargs):
        script.calls.append((config, messages))
        yield "Streamed reply."

    monkeypatch.setattr("utk_curio.backend.app.agents.infrastructure.providers.stream_chat_turn", _stream)
    r = client.post(
        f"/api/agents/projects/{flow.pid}/attachments/{flow.att}/run/stream",
        json={"message": "Load the street trees."}, headers=_auth(people.alice_token),
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    r.get_data()  # the stream runs to its end
    assert _run(client, flow, BOB_TOKEN, "Now count them by block.").status_code == 200

    turns = _turns(client, flow, BOB_TOKEN)
    assert [(t["role"], t["text"], t.get("by")) for t in turns] == [
        ("user", "Load the street trees.", _person(people.alice)),
        ("agent", "Streamed reply.", None),
        ("user", "Now count them by block.", _person(people.bob)),
        ("agent", "Here is what the node does.", None),
    ]


def test_a_watcher_is_refused_and_sees_nothing_private(client, people, flow, script):
    from utk_curio.backend.app.projects import access

    assert _run(client, flow, BOB_TOKEN, "a private question about layoffs").status_code == 200
    asked = len(script.calls)
    base = f"/api/agents/projects/{flow.pid}"
    for method, path, body in (
        ("get", f"{base}/attachments", None),
        ("get", f"{base}/attachments/{flow.att}/session", None),
        ("post", f"{base}/attachments/{flow.att}/run", {"message": "hello"}),
        ("post", f"{base}/attachments/{flow.att}/run/stream", {"message": "hello"}),
        ("delete", f"{base}/attachments/{flow.att}/session", None),
        ("post", f"{base}/attachments/{flow.att}/solve", {}),
        ("get", base, None),
        ("post", f"{base}/install", {"coord": COORD}),
    ):
        r = getattr(client, method)(path, json=body, headers=_auth(CAROL_TOKEN))
        text = r.get_data(as_text=True)
        assert r.status_code == 403, f"{method} {path}: {r.status_code} {text}"
        assert r.get_json()["error"] == access.AGENTS_WATCHER_REFUSAL, path
        for private in (flow.session, "a private question about layoffs", flow.att):
            assert private not in text, f"{method} {path} leaked {private!r}"
    assert len(script.calls) == asked, "a watcher's request reached the model"
    # The chat she was refused is untouched.
    assert len(_turns(client, flow, people.alice_token)) == 2


def test_a_hosted_guest_is_refused_on_another_accounts_dataflow(
    client, flow, guest_user_and_token, script, monkeypatch,
):
    from utk_curio.backend import config
    from utk_curio.backend.app.projects import access

    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    _guest, token = guest_user_and_token
    for method, path, body in (
        ("get", f"/api/agents/projects/{flow.pid}/attachments", None),
        ("post", f"/api/agents/projects/{flow.pid}/attachments/{flow.att}/run", {"message": "hi"}),
    ):
        r = getattr(client, method)(path, json=body, headers=_auth(token))
        assert r.status_code == 403, f"{path}: {r.get_data(as_text=True)}"
        assert r.get_json()["error"] == access.AGENTS_WATCHER_REFUSAL
        assert flow.session not in r.get_data(as_text=True)
    assert script.calls == []


def test_a_hosted_guest_still_drives_the_examples_its_account_owns(client, db, monkeypatch, tmp_curio):
    """Every hosted guest is the one account that owns the shared examples,
    and works with an example's agents as with its own dataflow's: the owner
    is told by account before the room's roles, which have every hosted guest
    watch."""
    from utk_curio.backend import config

    guest = _account(db, config.CURIO_SHARED_GUEST_USERNAME, "Guest", "shared-guest-token-for-tests")
    guest.is_guest = True
    db.session.commit()
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)  # the one local user makes the example
    r = client.post("/api/projects", json={
        "name": "Example", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": [],
    }, headers=_auth("shared-guest-token-for-tests"))
    assert r.status_code == 201, r.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)  # then Curio is hosted
    r = client.get(f"/api/agents/projects/{r.get_json()['id']}/attachments",
                   headers=_auth("shared-guest-token-for-tests"))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["attachments"] == []


# ---------------------------------------------------------------------------
# Keys: an editor's run names the editor's own, never the owner's
# ---------------------------------------------------------------------------

def _texts(messages) -> str:
    """What a run's messages say, one after another."""
    return "\n".join(
        m["content"] if isinstance(m.get("content"), str) else json.dumps(m.get("content"))
        for m in messages
    )


def test_an_editors_chat_lists_only_the_editors_saved_keys(client, people, flow, script):
    """The block a run that writes code is given lists the Node code keys of
    whoever asked: bob's in bob's chat, alice's in alice's, on one dataflow."""
    _save_key(people.alice, *ALICE_KEY)
    _save_key(people.bob, *BOB_KEY)

    assert _run(client, flow, BOB_TOKEN, "Fetch today's weather.").status_code == 200
    bobs = _texts(script.calls[-1][1])
    assert 'curio_secret("bobs-weather")' in bobs
    assert "alices-census" not in bobs and ALICE_KEY[1] not in bobs

    assert _run(client, flow, people.alice_token, "Fetch the census tracts.").status_code == 200
    alices = _texts(script.calls[-1][1])
    assert 'curio_secret("alices-census")' in alices
    assert "bobs-weather" not in alices


def test_an_editors_run_resolves_no_key_of_the_owners(app, people, flow):
    """Whatever an editor's run names back is looked up among the editor's
    keys alone: a request of bob's on alice's dataflow lists and resolves
    bob's key and resolves nothing of alice's, even by its name."""
    from flask import g

    from utk_curio.backend.app.agents.application import dataflow_block
    from utk_curio.backend.app.agents.application.turns import grounding

    _save_key(people.alice, *ALICE_KEY)
    _save_key(people.bob, *BOB_KEY)
    base = {"catalog_paths": {}, "catalog_ids": {}, "verified": {}, "texts": []}
    with app.test_request_context():
        g.user = people.bob
        ctx = grounding._grounding_context(flow.owner_key, flow.pid, {}, node_type=None, base=base)
        block = dataflow_block.compose(flow.owner_key, flow.pid, datasets=())
    assert sorted(ctx.secrets) == ["bobs-weather"]
    assert ctx.secret_values(["alices-census"]) == {}
    assert ctx.secret_values(["bobs-weather"]) == {"bobs-weather": BOB_KEY[2]}
    assert "bobs-weather" in block and "alices-census" not in block

    with app.test_request_context():
        g.user = people.alice
        own = grounding._grounding_context(flow.owner_key, flow.pid, {}, node_type=None, base=base)
    assert sorted(own.secrets) == ["alices-census"]
    assert own.secret_values(["alices-census"]) == {"alices-census": ALICE_KEY[2]}


def _alices_dataset(people, flow, *, in_her_dataflow: bool, name: str = "heat.csv",
                    body: bytes = b"tract,heat\nA,31\n") -> str:
    """A dataset of alice's Data Catalog, added to her dataflow as Add to
    project adds one when *in_her_dataflow*; its id."""
    from utk_curio.backend.app.datasets.install.installer import install_imported_file
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    dataset_id = install_imported_file(flow.owner_key, body, name, "csv").manifest.id
    if in_her_dataflow:
        DatasetCatalogService(people.alice).install_dataset(flow.pid, dataset_id)
    return dataset_id


def test_a_solve_job_keeps_the_keys_of_whoever_started_it(app, people, flow):
    """A Solve's job holds no request, so its grounding base keeps the keys
    of the request that started it: a job bob started lists and resolves
    bob's keys, never alice's, on the thread where no one is signed in. It
    grounds sources in the datasets alice's dataflow lists, which its block
    lists and its runs load."""
    from pathlib import Path

    from flask import g

    from utk_curio.backend.app.agents.application import dataflow_block
    from utk_curio.backend.app.agents.application.turns import grounding

    _save_key(people.alice, *ALICE_KEY)
    _save_key(people.bob, *BOB_KEY)
    dataset_id = _alices_dataset(people, flow, in_her_dataflow=True)
    spec = {"dataflow": {"nodes": [{"id": "n1", "content": "print(1)"}], "edges": []}}
    with app.test_request_context():
        g.user = people.bob
        base = grounding._solve_grounding_base(flow.owner_key, flow.pid, spec, {}, [])
        paths = grounding._resolve_catalog_execution_paths(flow.pid, [dataset_id])
    assert base.get("keys") == str(people.bob.id)
    assert sorted(base["secrets"]) == ["bobs-weather"]
    # The job's thread: no request, no one signed in.
    ctx = grounding._grounding_context(flow.owner_key, flow.pid, {}, node_type=None, base=base)
    assert ctx.secret_values(["alices-census"]) == {}
    assert ctx.secret_values(["bobs-weather"]) == {"bobs-weather": BOB_KEY[2]}
    resolver = grounding._exec_secrets_resolver(grounding._keys_of(base, flow.owner_key))
    assert resolver(['k = curio_secret("alices-census")']) == {}
    block = dataflow_block.compose(flow.owner_key, flow.pid, datasets=(), keys=grounding._keys_of(base, flow.owner_key))
    assert "bobs-weather" in block and "alices-census" not in block
    # The dataset alice's dataflow lists, from her Data Catalog.
    assert dataset_id in base["catalog_ids"], sorted(base["catalog_ids"])
    assert [dataset.id for dataset in base["dataflow_datasets"]] == [dataset_id]
    assert Path(paths[dataset_id]).read_bytes() == b"tract,heat\nA,31\n"


def test_an_editors_chat_reads_the_datasets_the_dataflow_lists_and_no_other_of_the_owners(app, people, flow):
    """In bob's chat, catalog.search and the dataflow block an agent that
    writes code is given list the dataset alice's dataflow lists, and not the
    one she keeps out of it."""
    from flask import g

    from utk_curio.backend.app.agents.application import dataflow_block, tools

    listed = _alices_dataset(people, flow, in_her_dataflow=True, name="tract_heat.csv")
    kept_out = _alices_dataset(people, flow, in_her_dataflow=False, name="tract_pay.csv", body=b"name,pay\nA,1\n")
    with app.test_request_context():
        g.user = people.bob
        # A search both of alice's datasets match, so only her list keeps one out.
        status, text = tools.execute_read_tool(
            "catalog.search", user_key=flow.owner_key, project_id=flow.pid, target=None, params={"q": "tract_"},
        )
        datasets = dataflow_block.read_datasets(flow.pid)
    assert status == "ok", text
    found = {row["id"]: row for row in json.loads(text)["datasets"]}
    assert listed in found and found[listed]["installed"] is True and found[listed]["path"]
    assert kept_out not in found
    assert [dataset.id for dataset in datasets] == [listed]


# ---------------------------------------------------------------------------
# Installs wait for the owner's review
# ---------------------------------------------------------------------------

def _pending_install(flow, tool: str = "dataset.install") -> str:
    """A pending install the attachment's agent proposed, as a mint stores one."""
    from utk_curio.backend.app.agents.application import spec_reads
    from utk_curio.backend.app.agents.application.proposals import store
    from utk_curio.backend.app.agents.domain import content

    spec = spec_reads._live_spec_or_404(flow.owner_key, flow.pid)
    proposal_id = "pending-install-1"
    part = content.make_proposal_part(
        proposal_id=proposal_id, tool=tool, summary="Add the street trees dataset",
        preview="street-trees", pins={"datasetId": "street-trees"},
    )
    store._store_proposal(
        flow.owner_key, flow.pid, spec, {"attachment_id": flow.att, "session_id": flow.session},
        {"proposalId": proposal_id, "tool": tool, "datasetId": "street-trees",
         "summary": "Add the street trees dataset", "status": "pending"},
        part,
    )
    return proposal_id


def _active_proposal(client, flow, token):
    listed = client.get(f"/api/agents/projects/{flow.pid}/attachments", headers=_auth(token)).get_json()
    return next(a for a in listed["attachments"] if a["attachmentId"] == flow.att)["activeProposal"]


@pytest.mark.parametrize("tool", ["dataset.install", "discovery.acquire", "package.install", "package.draft.apply"])
def test_an_install_an_editors_chat_asked_for_waits_for_the_owner(client, people, flow, tool):
    proposal_id = _pending_install(flow, tool)
    path = f"/api/agents/projects/{flow.pid}/attachments/{flow.att}/proposals/{proposal_id}"
    for refused in (client.post(f"{path}/apply", headers=_auth(BOB_TOKEN)),
                    client.delete(path, headers=_auth(BOB_TOKEN))):
        assert refused.status_code == 403, refused.get_data(as_text=True)
        assert "waits for Alice" in refused.get_json()["error"]
    assert _active_proposal(client, flow, BOB_TOKEN)["status"] == "pending"
    # The owner reviews it.
    r = client.delete(path, headers=_auth(people.alice_token))
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "dismissed"


def test_an_editors_dataset_selection_waits_for_the_owner_to_download(client, people, user_and_token, tmp_curio,
                                                                       monkeypatch):
    """Confirming a candidates card downloads the rows Curio can download
    into the Data Catalog. An editor's confirmation of one is refused before
    anything downloads or is recorded; the owner's goes on to download it."""
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.tests.test_agents.test_fetch_delegation import (
        CHICAGO, PORTAL_OBSERVATION, _FakeDiscovery, _discovery_harness,
    )

    alice, token = user_and_token
    fake = _FakeDiscovery(error="the portal refused the request")
    h, finder_id = _discovery_harness(client, alice, token, monkeypatch, fake)
    monkeypatch.setattr(
        "utk_curio.backend.app.agents.application.verify.verify_external_source",
        lambda url, **k: dict(PORTAL_OBSERVATION),
    )
    access.add_editor(alice, h.pid, "bob")
    path = f"/api/agents/projects/{h.pid}/attachments/{finder_id}/dataset-selection"
    picks = {"picks": [{"lane": "external", "key": "https://data.example.org/areas.geojson"}]}

    refused = client.post(path, json=picks, headers=_auth(BOB_TOKEN))
    assert refused.status_code == 403, refused.get_data(as_text=True)
    assert "waits for Alice" in refused.get_json()["error"]
    assert fake.calls == []

    confirmed = client.post(path, json=picks, headers=_auth(token))
    assert confirmed.status_code == 200, confirmed.get_data(as_text=True)
    assert fake.calls == [(CHICAGO, "cauq-8yn6", None)]


# ---------------------------------------------------------------------------
# Who an editor's agent change is by
# ---------------------------------------------------------------------------

def test_an_editors_agent_change_is_a_point_named_after_the_editor(client, people, flow, script, monkeypatch):
    from utk_curio.backend.app.collaboration import dataflow_docs, history

    monkeypatch.setattr(history, "RECORDING", True, raising=False)
    # The doc opens again on a server that records the history, so its first
    # points come before the agent's change.
    dataflow_docs.close(flow.pid)
    script.replies[:] = [
        '```curio.v1\n{"toolRequest": {"tool": "node.content.write", '
        '"params": {"nodeId": "n1", "content": "print(2)"}}}\n```',
        "Proposed: review it above.",
    ]
    ran = _run(client, flow, BOB_TOKEN, "Print two instead.")
    assert ran.status_code == 200, ran.get_data(as_text=True)
    proposal = next(p for p in ran.get_json()["content"] if p["type"] == "proposal")
    r = client.post(
        f"/api/agents/projects/{flow.pid}/attachments/{flow.att}/proposals/{proposal['proposalId']}/apply",
        headers=_auth(BOB_TOKEN),
    )
    assert r.status_code == 200, r.get_data(as_text=True)

    newest = history.points(flow.owner_key, flow.pid)[-1]
    assert (newest["kind"], newest["by"]) == ("agent", {"kind": "agent", "account": str(people.bob.id), "agent": COORD})
    listed = client.get(f"/api/projects/{flow.pid}/history", headers=_auth(BOB_TOKEN)).get_json()
    assert listed["versions"][-1]["what"] == "Node Builder, asked by Bob"
