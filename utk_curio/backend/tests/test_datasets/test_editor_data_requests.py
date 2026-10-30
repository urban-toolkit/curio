"""An invited editor's own data reaches the owner's dataflow through her review.

alice owns a dataflow that lists her street trees. bob is an editor she
invited, with datasets of his own Data Catalog; carol opened the dataflow's
link and watches it. Each way bob brings data of his in asks alice instead of
writing to her store or her dataflow: a file he drops, which goes into his Data
Catalog; his Add to project; and a card of his catalog he drags onto her
canvas, or onto a node. Each is a request in alice's review, a
``dataset.install`` of ``agentInstalls.json``, as an install an agent asks for
is: only alice applies or dismisses it. Her Apply copies the dataset into her
store and lists it in her dataflow, and bob's run then reads it from her store;
her Dismiss leaves nothing behind. bob's Remove from project takes a dataset out
of her dataflow and leaves her store alone. carol cannot ask.

Each test goes through the routes alone, so on a base without them it fails at
its first assertion on what the base does not do.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers, create_project
from utk_curio.backend.tests.test_datasets.test_editor_datasets import (
    HUB_ID,
    TREES,
    _account,
    _hub_dataset,
    _import,
    _install,
    _run,
)

BUS_STOPS = b"stop,routes\nClark,22\nState,29\n"
PARKS = b"park,acres\nGrant,319\n"
#: The requests file beside the dataflow's spec.
REQUESTS_FILE = "dataset-requests.json"


@pytest.fixture()
def flow(client, db, user_and_token):
    """alice's dataflow, which lists her street trees, with bob invited to
    edit it and carol, signed in, only its link; bob's bus stops, which only
    his store holds."""
    from utk_curio.backend.app.projects import access

    alice, alice_token = user_and_token
    bob, carol = _account(db, "bob"), _account(db, "carol")
    tokens = {"alice": alice_token, "bob": "bob-token-for-tests", "carol": "carol-token-for-tests"}
    pid = create_project(client, alice_token, name="Street trees")
    trees = _import(client, alice_token, "trees.csv", TREES)
    _install(client, alice_token, pid, trees["id"])
    access.add_editor(alice, pid, "bob")
    bus_stops = _import(client, tokens["bob"], "bus_stops.csv", BUS_STOPS)
    return SimpleNamespace(pid=pid, alice=alice, bob=bob, carol=carol, tokens=tokens, trees=trees,
                           bus_stops=bus_stops)


@pytest.fixture()
def sandbox(monkeypatch):
    """The sandbox, answering every run at once; each run's body, in order."""
    import json
    from unittest.mock import MagicMock

    state = SimpleNamespace(bodies=[])

    def fake_call(method, path, **kwargs):
        state.bodies.append(json.loads(kwargs["data"]))
        resp = MagicMock()
        resp.json.return_value = {"stdout": "", "stderr": "", "output": {}}
        return resp

    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake_call)
    return state


def _key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _store(user) -> set:
    """The folders of *user*'s dataset store, by name."""
    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets

    return {folder.name for folder in list_user_datasets(_key(user))}


def _listed(flow) -> list:
    """The datasets alice's dataflow lists, by id, as its spec holds them."""
    from utk_curio.backend.app.projects import storage as projects_storage

    refs = (projects_storage.read_spec(_key(flow.alice), flow.pid) or {})["dataflow"].get("datasets") or []
    return sorted(ref.get("datasetId") or ref.get("id") for ref in refs)


def _hers(flow) -> tuple:
    """What a request must not change: alice's store and her dataflow's list."""
    return _store(flow.alice), _listed(flow)


def _ask(client, flow, who: str, dataset_id: str, **body):
    return client.post(f"/api/dataflows/{flow.pid}/datasets/requests",
                       json={"datasetId": dataset_id, **body}, headers=auth_headers(flow.tokens[who]))


def _asked(client, flow, who: str, dataset_id: str, **body) -> dict:
    """*who*'s request for *dataset_id*, which the route made."""
    resp = _ask(client, flow, who, dataset_id, **body)
    assert resp.status_code == 201, f"{who}'s request answered {resp.status_code}: {resp.get_data(as_text=True)[:300]}"
    answer = resp.get_json()
    assert answer["requested"] is True, answer
    return answer["request"]


def _review(client, flow, who: str = "alice") -> list:
    """The requests alice's review shows, as *who* reads them."""
    resp = client.get(f"/api/dataflows/{flow.pid}/datasets/requests", headers=auth_headers(flow.tokens[who]))
    assert resp.status_code == 200, f"{who}'s review answered {resp.status_code}: {resp.get_data(as_text=True)[:300]}"
    return resp.get_json()["requests"]


def _apply(client, flow, who: str, request_id: str):
    return client.post(f"/api/dataflows/{flow.pid}/datasets/requests/{request_id}/apply",
                       headers=auth_headers(flow.tokens[who]))


def _dismiss(client, flow, who: str, request_id: str):
    return client.delete(f"/api/dataflows/{flow.pid}/datasets/requests/{request_id}",
                         headers=auth_headers(flow.tokens[who]))


def _in_review(request: dict, flow, dataset: dict) -> None:
    """*request* is bob's, for *dataset*, in the install review."""
    assert request["tool"] == "dataset.install", request
    assert request["status"] == "pending", request
    assert request["datasetId"] == dataset["id"], request
    assert request["by"] == {"kind": "person", "account": str(flow.bob.id), "name": "Bob"}, request


# ---------------------------------------------------------------------------
# Each way bob brings his data in asks alice, and writes nothing of hers
# ---------------------------------------------------------------------------

def test_an_editors_dropped_file_asks_the_owner_and_writes_nothing_of_hers(client, flow, sandbox):
    """bob drops a file of parks on alice's canvas: it goes into his Data
    Catalog, as Import dataset puts it there, and the Data Loading node the
    drop makes asks alice for it. Her review shows his request; her store and
    her dataflow's list are as they were, and her run still cannot read it,
    while his own run does."""
    before = _hers(flow)
    dropped = _import(client, flow.tokens["bob"], "parks.csv", PARKS)

    request = _asked(client, flow, "bob", dropped["id"], nodeId="parks-loader")

    _in_review(request, flow, dropped)
    assert request["nodeIds"] == ["parks-loader"]
    assert [r["proposalId"] for r in _review(client, flow)] == [request["proposalId"]]
    assert _hers(flow) == before, "bob's drop wrote to alice's store or her dataflow"
    _run(client, flow.tokens["alice"], flow.pid, dropped["id"])
    assert sandbox.bodies[-1]["dataset_paths"] == {}, "alice's run read bob's dataset before she added it"
    _run(client, flow.tokens["bob"], flow.pid, dropped["id"])
    assert Path(sandbox.bodies[-1]["dataset_paths"][dropped["id"]]).read_bytes() == PARKS


def test_an_editors_add_to_project_asks_the_owner_and_writes_nothing_of_hers(client, flow):
    """bob's Add to project of his bus stops asks alice: her review shows the
    request, which names no node, and her store and her dataflow's list are as
    they were."""
    before = _hers(flow)

    request = _asked(client, flow, "bob", flow.bus_stops["id"], add=True)

    _in_review(request, flow, flow.bus_stops)
    assert request["nodeIds"] == []
    assert [r["datasetId"] for r in _review(client, flow)] == [flow.bus_stops["id"]]
    assert [r["proposalId"] for r in _review(client, flow, "bob")] == [request["proposalId"]]
    assert _hers(flow) == before, "bob's Add to project wrote to alice's store or her dataflow"


def test_an_editors_card_dragged_onto_her_dataflow_asks_the_owner_once(client, flow):
    """bob drags the card of his bus stops onto alice's canvas, then onto a
    node: one request, which names both nodes, waits in her review, and her
    store and her dataflow's list are as they were."""
    before = _hers(flow)

    first = _asked(client, flow, "bob", flow.bus_stops["id"], nodeId="bus-loader")
    again = _asked(client, flow, "bob", flow.bus_stops["id"], nodeId="bus-count")

    _in_review(first, flow, flow.bus_stops)
    assert again["proposalId"] == first["proposalId"]
    assert again["nodeIds"] == ["bus-loader", "bus-count"]
    assert [r["proposalId"] for r in _review(client, flow)] == [first["proposalId"]]
    assert _hers(flow) == before, "bob's drag wrote to alice's store or her dataflow"


def test_an_editors_add_of_a_shared_dataset_asks_the_owner_and_his_drop_of_one_asks_nothing(
    client, flow, tmp_path, monkeypatch,
):
    """Every account reads the shared catalog, so bob's drop of its street
    lights asks nothing. His Add to project of them asks alice, whose Apply
    adds them as her own Add to project does."""
    _hub_dataset(tmp_path, monkeypatch)
    before = _hers(flow)

    dropped = _ask(client, flow, "bob", HUB_ID, nodeId="lights-loader")
    assert dropped.status_code == 200, dropped.get_data(as_text=True)[:300]
    assert dropped.get_json() == {"requested": False, "reason": "shared"}
    assert _review(client, flow) == []

    request = _asked(client, flow, "bob", HUB_ID, add=True)
    assert _hers(flow) == before, "bob's Add to project wrote to alice's store or her dataflow"
    applied = _apply(client, flow, "alice", request["proposalId"])
    assert applied.status_code == 200, applied.get_data(as_text=True)[:300]
    assert HUB_ID in _listed(flow)
    assert _review(client, flow) == []


def test_an_editors_own_collection_is_not_asked_for(client, flow, tmp_path, monkeypatch):
    """A collection's files stay where bob's store keeps them, which a copy of
    its index would not bring: his request for one is refused, and nothing
    waits in alice's review."""
    from utk_curio.backend.app.discovery.infrastructure import storage as discovery_storage
    from utk_curio.backend.tests.test_datasets.test_editor_datasets import REPO, _a_collection

    monkeypatch.setenv(discovery_storage.ENV_ROOT, str(REPO / "discovery"))
    collection = _a_collection(flow.bob, tmp_path)

    resp = _ask(client, flow, "bob", collection, add=True)

    assert resp.status_code == 400, f"bob's request answered {resp.status_code}: {resp.get_data(as_text=True)[:300]}"
    assert "collection" in resp.get_json()["error"]
    assert _review(client, flow) == []


# ---------------------------------------------------------------------------
# alice's review: Apply, Dismiss, and no one else's
# ---------------------------------------------------------------------------

def test_the_owners_apply_copies_the_dataset_into_her_store_and_his_run_reads_it_there(client, flow, sandbox):
    """alice applies bob's request for his bus stops: the folder is copied
    into her store, her dataflow lists it, and the request leaves her review.
    bob's run then reads the bus stops from her store, not his, and so does
    hers."""
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir

    request = _asked(client, flow, "bob", flow.bus_stops["id"], nodeId="bus-loader")
    folder = flow.bus_stops["dirName"]

    resp = _apply(client, flow, "alice", request["proposalId"])

    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["status"] == "applied"
    hers = dataset_dir(_key(flow.alice), folder)
    assert folder in _store(flow.alice)
    assert flow.bus_stops["id"] in _listed(flow)
    assert _review(client, flow) == []
    for who in ("bob", "alice"):
        _run(client, flow.tokens[who], flow.pid, flow.bus_stops["id"])
        path = Path(sandbox.bodies[-1]["dataset_paths"][flow.bus_stops["id"]]).resolve()
        assert path.is_relative_to(hers.resolve()), f"{who}'s run read the bus stops from {path}, not alice's store"
        assert path.read_bytes() == BUS_STOPS
    listing = client.get(f"/api/datasets/catalog?dataflowId={flow.pid}", headers=auth_headers(flow.tokens["bob"]))
    assert listing.status_code == 200, listing.get_data(as_text=True)[:300]
    assert {i["id"]: i for i in listing.get_json()["items"]}[flow.bus_stops["id"]]["installed"] is True


def test_the_owners_dismiss_leaves_nothing_behind_and_the_editor_reviews_nothing(client, flow):
    """bob can neither apply nor dismiss his own request: it waits for alice,
    as an install an agent asks for does. alice's Dismiss takes it out of her
    review and leaves nothing behind: no folder in her store, no dataset in her
    dataflow, no requests file; bob's own bus stops stay his."""
    from utk_curio.backend.app.projects import storage as projects_storage

    before = _hers(flow)
    request = _asked(client, flow, "bob", flow.bus_stops["id"], add=True)

    for refused in (_apply(client, flow, "bob", request["proposalId"]),
                    _dismiss(client, flow, "bob", request["proposalId"])):
        assert refused.status_code == 403, refused.get_data(as_text=True)[:300]
        assert refused.get_json()["error"] == (
            "This install waits for Alice, who owns this dataflow: an install changes their account, "
            "so they review it."
        )
    assert [r["proposalId"] for r in _review(client, flow)] == [request["proposalId"]]

    resp = _dismiss(client, flow, "alice", request["proposalId"])

    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["status"] == "dismissed"
    assert _review(client, flow) == []
    assert _hers(flow) == before
    assert not (projects_storage.project_dir(_key(flow.alice), flow.pid) / REQUESTS_FILE).exists()
    assert flow.bus_stops["dirName"] in _store(flow.bob)


def test_a_watcher_cannot_ask_nor_read_the_review(client, flow):
    """carol only opened the dataflow's link: her request for a dataset of her
    own is refused, as is her read of the review, and nothing of alice's
    changes."""
    own = _import(client, flow.tokens["carol"], "carols.csv", PARKS)
    before = _hers(flow)

    asked = _ask(client, flow, "carol", own["id"], add=True)
    read = client.get(f"/api/dataflows/{flow.pid}/datasets/requests", headers=auth_headers(flow.tokens["carol"]))

    assert asked.status_code == 403, f"carol's request answered {asked.status_code}: {asked.get_data(as_text=True)[:300]}"
    assert read.status_code == 403, f"carol's read answered {read.status_code}: {read.get_data(as_text=True)[:300]}"
    assert _review(client, flow) == []
    assert _hers(flow) == before


# ---------------------------------------------------------------------------
# bob's Remove from project
# ---------------------------------------------------------------------------

def test_an_editors_remove_from_project_takes_the_dataset_out_and_leaves_her_store_alone(client, flow):
    """alice's parks are an upload of hers only her dataflow uses: her own
    Remove from project would delete their folder with the reference. bob's
    takes the reference out of her dataflow and leaves the folder in her
    store; his store is as it was."""
    parks = _import(client, flow.tokens["alice"], "parks.csv", PARKS)
    _install(client, flow.tokens["alice"], flow.pid, parks["id"])
    bobs = _store(flow.bob)

    resp = client.delete(f"/api/dataflows/{flow.pid}/datasets/{parks['id']}", headers=auth_headers(flow.tokens["bob"]))

    assert resp.status_code == 200, f"bob's removal answered {resp.status_code}: {resp.get_data(as_text=True)[:300]}"
    assert parks["id"] not in _listed(flow)
    assert flow.trees["id"] in _listed(flow)
    assert parks["dirName"] in _store(flow.alice), "bob's removal deleted alice's upload from her store"
    assert _store(flow.bob) == bobs

    # Her own removal of the same upload deletes it, as it did before.
    _install(client, flow.tokens["alice"], flow.pid, parks["id"])
    resp = client.delete(f"/api/dataflows/{flow.pid}/datasets/{parks['id']}", headers=auth_headers(flow.tokens["alice"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert parks["dirName"] not in _store(flow.alice)
