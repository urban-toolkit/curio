"""Save-time computed dataset titling (the "Play All" / project-save path).

Non-CodeEditor nodes (autk-grammar, data-pool, …) persist their outputs only via
project save (``_auto_install_computed_outputs``), not the execution route. These
tests pin that the save path titles such datasets by the producing node — never
the raw generated filename — so a "Play All" rerun produces friendly titles.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment
from utk_curio.backend.app.projects.services import (
    _humanize_node_type,
    _computed_output_title,
)
from utk_curio.backend.app.projects.schemas import OutputRef
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)


def _grammar_spec(name: str, node_id: str) -> dict:
    return {
        "dataflow": {
            "name": name,
            "nodes": [{"id": node_id, "type": "curio.builtin/autk-grammar", "data": {}}],
            "edges": [],
        }
    }


def _computed_title(client, token, project_id, dataset_id):
    # The friendly node title lives on the account-store manifest and is surfaced
    # in the dataflow's scoped catalog (its own computed outputs).
    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    item = next(i for i in catalog["items"] if i["id"] == dataset_id)
    return item["title"]


def test_save_titles_computed_output_by_node_name(client, user_and_token):
    """The producing node's client-resolved label (``node_name``) becomes the
    computed dataset title on save — not the generated filename."""
    _, token = user_and_token
    project_id = create_project(client, token, name="Play All node-name title")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    filename = "1782757759504_31640bba.json"
    (shared / filename).write_text(json.dumps({"a": 1}), encoding="utf-8")

    node_id = "whatif-data"
    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({
            "spec": _grammar_spec("Play All node-name title", node_id),
            "outputs": [{
                "node_id": node_id,
                "filename": filename,
                "data_type": "dict",
                "node_name": "Knowledge Graph",
            }],
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    dataset_id = computed_dataset_id(node_id, project_id)
    assert _computed_title(client, token, project_id, dataset_id) == "Knowledge Graph"


def test_save_falls_back_to_humanized_node_type_without_node_name(client, user_and_token):
    """When no ``node_name`` is sent, the title is derived from the node type —
    never the raw filename."""
    _, token = user_and_token
    project_id = create_project(client, token, name="Play All type fallback")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    filename = "1782757838569_7121d215.json"
    (shared / filename).write_text(json.dumps({"a": 1}), encoding="utf-8")

    node_id = "whatif-baseline-compute"
    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({
            "spec": _grammar_spec("Play All type fallback", node_id),
            "outputs": [{"node_id": node_id, "filename": filename, "data_type": "dict"}],
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    dataset_id = computed_dataset_id(node_id, project_id)
    title = _computed_title(client, token, project_id, dataset_id)
    assert title == "Autk Grammar"  # humanized "curio.builtin/autk-grammar"
    assert ".json" not in title.lower()


def test_humanize_node_type():
    assert _humanize_node_type("curio.builtin/autk-grammar") == "Autk Grammar"
    assert _humanize_node_type("curio.builtin/data-pool") == "Data Pool"
    assert _humanize_node_type("PYTHON_COMPUTATION") == "Python Computation"
    assert _humanize_node_type(None) is None
    assert _humanize_node_type("") is None


def test_computed_output_title_precedence():
    dataflow = {
        "nodes": [
            {"id": "n1", "type": "curio.builtin/autk-grammar", "data": {"packageTemplateLabel": "My Step"}},
            {"id": "n2", "type": "curio.builtin/autk-grammar", "data": {}},
            {"id": "n3", "type": "curio.builtin/autk-grammar", "data": {}},
        ]
    }
    # 1. explicit node_name wins
    assert _computed_output_title(
        OutputRef(node_id="n2", filename="x.json", node_name="Knowledge Graph"), dataflow
    ) == "Knowledge Graph"
    # 2. spec node's custom label
    assert _computed_output_title(OutputRef(node_id="n1", filename="x.json"), dataflow) == "My Step"
    # 3. humanized node type
    assert _computed_output_title(OutputRef(node_id="n3", filename="x.json"), dataflow) == "Autk Grammar"
    # 4. unknown node → None (installer then derives a filename title; UI shows dirName)
    assert _computed_output_title(OutputRef(node_id="ghost", filename="x.json"), dataflow) is None
