"""Lineage has to read node code, not just bindings (#250).

The reporter's complaint was that a dataset's Lineage tab disagreed with itself:
nodes plainly using a dataset were not listed, and dataflows that used it were
not counted. The cause is that the backend's usage helper consults exactly three
sources - ``dataflow.datasets`` refs, ``node.metadata.datasetRefs``, and the
producer id decode - and never the node's ``content``.

That is where a dataset reference actually lives most of the time. Curio's own
shipped examples are the proof: their loaders reference datasets *only* through
``curio_dataset_path("...")`` inside ``content``, with ``metadata:
{"keywords": []}`` and no ``datasetRefs`` at all. Drag a dataset onto the canvas
and the binding exists; write or edit the loader by hand, or open a saved
example, and only the code does.

The frontend already solved this for the live canvas under #205
(``datasetIdsInCode`` + ``datasetLineageResolver``). The backend twin was never
made, so the same dataset got two different answers depending on which resolver
was asked - and the saved-spec one is what the detail page and the browse-card
counts use.
"""
from __future__ import annotations

import json

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers


def _create_project(client, token, name, spec):
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": name, "spec": spec, "outputs": []}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _usage(client, token, dataset_id):
    resp = client.get(
        f"/api/datasets/{dataset_id}/usage", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["dataflows"]


DATASET = "data.urbanlab.chicago-boundary"


def _loader(code: str) -> dict:
    return {"id": "loader", "type": "curio.builtin/data-loading", "x": 0, "y": 0,
            "content": code, "metadata": {"keywords": []}}


class TestADatasetReferencedOnlyInCode:
    """The shape every shipped example has: a hand-written loader, no binding."""

    def test_the_dataflow_is_reported_as_using_it(self, client, user_and_token):
        _user, token = user_and_token
        _create_project(client, token, "Hand-written loader", {
            "dataflow": {
                "name": "Hand-written loader",
                "nodes": [_loader(
                    "import geopandas as gpd\n"
                    f'dataset_path = curio_dataset_path("{DATASET}")\n'
                    "gdf = gpd.read_file(dataset_path)\n"
                )],
                "edges": [],
                "datasets": [],
            }
        })
        flows = _usage(client, token, DATASET)
        assert [f["dataflowName"] for f in flows] == ["Hand-written loader"]

    def test_its_downstream_nodes_are_reported_as_consumers(self, client, user_and_token):
        _user, token = user_and_token
        _create_project(client, token, "Loader and consumer", {
            "dataflow": {
                "name": "Loader and consumer",
                "nodes": [
                    _loader(f'dataset_path = curio_dataset_path("{DATASET}")\n'),
                    {"id": "plot", "type": "VIS_VEGA", "x": 200, "y": 0},
                ],
                "edges": [{"source": "loader", "target": "plot"}],
                "datasets": [],
            }
        })
        flows = _usage(client, token, DATASET)
        assert flows, "the dataflow was not reported at all"
        consumers = {n["nodeId"] for n in flows[0]["nodes"]}
        assert consumers == {"plot"}

    def test_single_quotes_are_found_too(self, client, user_and_token):
        # The generators emit double quotes; users edit the generated code.
        _user, token = user_and_token
        _create_project(client, token, "Single quoted", {
            "dataflow": {
                "name": "Single quoted",
                "nodes": [_loader(f"p = curio_dataset_path('{DATASET}')\n")],
                "edges": [],
                "datasets": [],
            }
        })
        assert [f["dataflowName"] for f in _usage(client, token, DATASET)] == ["Single quoted"]


class TestItDoesNotInventUsage:
    def test_a_different_dataset_in_code_is_not_a_match(self, client, user_and_token):
        _user, token = user_and_token
        _create_project(client, token, "Other dataset", {
            "dataflow": {
                "name": "Other dataset",
                "nodes": [_loader('p = curio_dataset_path("data.other.thing")\n')],
                "edges": [],
                "datasets": [],
            }
        })
        assert _usage(client, token, DATASET) == []

    def test_a_mismatched_quote_is_not_a_reference(self, client, user_and_token):
        # Mirrors the frontend scanner's own rejection cases so the two agree.
        _user, token = user_and_token
        _create_project(client, token, "Broken quoting", {
            "dataflow": {
                "name": "Broken quoting",
                "nodes": [_loader(f"p = curio_dataset_path(\"{DATASET}')\n")],
                "edges": [],
                "datasets": [],
            }
        })
        assert _usage(client, token, DATASET) == []

    def test_a_traversal_payload_is_not_a_dataset_id(self):
        # Asserted at the scanner rather than the route: such an id is not
        # URL-addressable, so a route-level check would pass on a 404 and prove
        # nothing about the charset. Mirrors the frontend scanner's own case.
        from utk_curio.backend.app.datasets.domain.code_refs import (
            dataset_ids_in_code,
        )

        assert dataset_ids_in_code(
            'p = curio_dataset_path("../../etc/passwd")'
        ) == []


class TestTheExistingSourcesStillWork:
    def test_a_binding_is_still_a_consumer(self, client, user_and_token):
        # Control: the paths that already worked must keep working.
        _user, token = user_and_token
        _create_project(client, token, "Bound", {
            "dataflow": {
                "name": "Bound",
                "nodes": [
                    {"id": "n1", "type": "VIS_VEGA", "x": 0, "y": 0,
                     "metadata": {"datasetRefs": [DATASET]}},
                ],
                "edges": [],
                "datasets": [],
            }
        })
        flows = _usage(client, token, DATASET)
        assert flows and {n["nodeId"] for n in flows[0]["nodes"]} == {"n1"}
