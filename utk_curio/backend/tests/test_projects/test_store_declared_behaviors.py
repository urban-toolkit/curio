"""A package in an account's own store is what its templates declare, for
that account.

A package of the account's own declares what its templates are, as Curio's
do: a Data Pool's behavior, a Data Export's, a loader's ``loadsDataset``. The
dashboard page and the Data Catalog's lineage read the owner's
store, then the catalog, then the packages Curio ships, so such a node is
treated as the built-in it declares for the account whose store holds its
package, and as an ordinary node for any other account. A run on the server
does the same (``test_runs/test_store_template_roles.py``).
"""
from __future__ import annotations

import json

from utk_curio.backend.app.projects import services

DATASET = "acme.parcels"


def _port() -> dict:
    return {"cardinality": "1", "types": ["DATAFRAME", "GEODATAFRAME"]}


#: A package an account saved nodes into, which only its store holds.
STORE_PACKAGE = {
    "id": "acme.mine",
    "name": "My nodes",
    "version": "1.0.0",
    "publisher": "alice",
    "license": "MIT",
    "description": "Nodes saved from a dataflow.",
    "createdAt": "2026-10-19T00:00:00Z",
    "compatibility": {"major": 1},
    "permissions": [],
    "dependencies": {"python": {}, "js": {}, "packages": {}},
    "templates": [
        {
            "id": "pool", "label": "My pool", "description": "", "category": "data",
            "engine": "python", "editor": "none", "behavior": "data-pool",
            "hasCode": False, "hasGrammar": False, "hasWidgets": False,
            "inputPorts": [_port()], "outputPorts": [_port()],
        },
        {
            "id": "fetch-parcels", "label": "Fetch parcels", "description": "", "category": "data",
            "engine": "python", "editor": "code", "behavior": "code",
            "hasCode": True, "hasGrammar": False, "hasWidgets": False, "loadsDataset": True,
            "inputPorts": [], "outputPorts": [_port()],
        },
        {
            "id": "fetch-roads", "label": "Fetch roads", "description": "", "category": "data",
            "engine": "python", "editor": "code", "behavior": "code",
            "hasCode": True, "hasGrammar": False, "hasWidgets": False,
            "inputPorts": [], "outputPorts": [_port()],
        },
    ],
}


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _second_account(db):
    from utk_curio.backend.app.users.models import User, UserSession

    bob = User(username="bob", name="Bob", email="bob@test.com")
    db.session.add(bob)
    db.session.flush()
    db.session.add(UserSession(user_id=bob.id, token="bob-token-789"))
    db.session.commit()
    return bob, "bob-token-789"


def _hold_the_package(user):
    """Put the package in *user*'s own store, and nowhere else."""
    from utk_curio.backend.app.packages import service as packages_service

    folder = packages_service.user_packages_dir(services._user_dir_key(user)) / "acme.mine@1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(STORE_PACKAGE), encoding="utf-8")


def _create(client, token, nodes, edges):
    resp = client.post(
        "/api/projects",
        data=json.dumps({
            "name": "Store nodes",
            "spec": {"dataflow": {
                "name": "Store nodes", "task": "", "timestamp": 1748990000000,
                "provenance_id": "store-nodes", "nodes": nodes, "edges": edges,
            }},
            "outputs": [],
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _node(node_id, node_type, content="", **fields):
    return {"id": node_id, "type": node_type, "content": content, "x": 0, "y": 0, **fields}


def _edge(source, target):
    return {"id": f"{source}-{target}", "source": source, "target": target}


def test_the_dashboard_walks_through_a_pool_saved_in_the_owners_store(client, db, user_and_token, monkeypatch):
    alice, alice_token = user_and_token
    bob, bob_token = _second_account(db)
    nodes = [
        _node("py", "curio.builtin/computation-analysis@1"),
        _node("pool", "acme.mine/pool@1"),
        _node("chart", "curio.builtin/vis-vega@1", "{}", dashboardPinned=True),
    ]
    edges = [_edge("py", "pool"), _edge("pool", "chart")]
    projects = {"alice": _create(client, alice_token, nodes, edges), "bob": _create(client, bob_token, nodes, edges)}
    _hold_the_package(alice)

    monkeypatch.setattr(
        services, "_dashboard_envelope_reader",
        lambda: (lambda filename: {"dataType": "dataframe", "data": {"a": [1]}, "schema": {}}),
    )
    monkeypatch.setattr(
        services,
        "load_shared_project",
        lambda project_id: {
            "project": type("D", (), {"name": "Store nodes"})(),
            "spec": {"dataflow": {"nodes": nodes, "edges": edges}},
            "outputs": [
                {"node_id": "py", "filename": "py.parquet", "data_type": "dataframe"},
                {"node_id": "pool", "filename": "pool.parquet", "data_type": "dataframe"},
            ],
        },
    )

    def embedded(owner):
        resp = client.get(f"/api/projects/{projects[owner]}/dashboard")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        return set(resp.get_json()["outputs"])

    # Alice's pool shows what reaches it, so her chart's rows are the producer's.
    assert embedded("alice") == {"py.parquet"}
    # Bob's store does not hold the package: to him it is a node that makes rows.
    assert embedded("bob") == {"pool.parquet"}


def test_the_data_catalog_counts_the_nodes_after_a_loader_saved_in_the_accounts_store(client, db, user_and_token):
    alice, alice_token = user_and_token
    bob, bob_token = _second_account(db)
    nodes = [
        _node("loader", "acme.mine/fetch-parcels@1", f'return curio_data_path("{DATASET}")'),
        _node("after", "curio.builtin/computation-analysis@1", "return input_0"),
    ]
    edges = [_edge("loader", "after")]
    _create(client, alice_token, nodes, edges)
    _create(client, bob_token, nodes, edges)
    _hold_the_package(alice)

    def consumers(token):
        resp = client.get(f"/api/datasets/{DATASET}/usage", headers=_auth(token))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        (flow,) = resp.get_json()["dataflows"]
        return [node["nodeId"] for node in flow["nodes"]]

    # Alice's loader brings the dataset in: the node after it reads it.
    assert consumers(alice_token) == ["after"]
    # To Bob it is a node that reads the dataset itself.
    assert consumers(bob_token) == ["loader"]


def test_a_data_template_saved_in_the_store_that_declares_no_loader_reads_the_dataset_itself(
    client, db, user_and_token,
):
    alice, alice_token = user_and_token
    nodes = [
        _node("loader", "acme.mine/fetch-roads@1", f'return curio_data_path("{DATASET}")'),
        _node("after", "curio.builtin/computation-analysis@1", "return input_0"),
    ]
    _create(client, alice_token, nodes, [_edge("loader", "after")])
    _hold_the_package(alice)

    resp = client.get(f"/api/datasets/{DATASET}/usage", headers=_auth(alice_token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    (flow,) = resp.get_json()["dataflows"]
    # The data category with no input port, but no loadsDataset: a consumer.
    assert [node["nodeId"] for node in flow["nodes"]] == ["loader"]
