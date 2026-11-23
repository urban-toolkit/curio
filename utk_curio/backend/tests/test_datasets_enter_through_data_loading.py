"""Example 32 and the Quad Cities test dataflow bring each dataset in through a
Data Loading node: no node picks a dataset or a collection in its code.

Example 32, the SAGE-IDOT rail crossings, had two Python nodes load three
collections each and use the one the Settings node's camera named; the Quad
Cities test dataflow had two Data Loading nodes pick one of three flood depths
by the projection period in their code. A node now reads the dataset its input
picks through its Data widget (``options.pickedBy`` and ``options.choices``),
so the canvas shows a Data Loading node for each dataset, and its code holds
only the call that loads what the widget holds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DATAFLOWS = {
    "example 32": REPO_ROOT / "docs" / "examples" / "32-sage-idot-rail-crossings.json",
    "Quad Cities": REPO_ROOT / "docs" / "examples" / "dataflows" / "quad-cities-flood-vulnerability.json",
}
DATA_LOADING = "curio.builtin/data-loading"
CODE_NODES = ("curio.builtin/python-computation", "curio.builtin/js-computation")


def _dataflow(name: str) -> dict:
    return json.loads(DATAFLOWS[name].read_text(encoding="utf-8"))["dataflow"]


def _named(node: dict) -> list:
    """The datasets and collections *node*'s code names in a literal call."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code

    return dataset_ids_in_code(node.get("content") or "")


def _held(node: dict) -> set:
    """What *node*'s Data widgets hold: a dataset each, or each choice of one
    an input picks."""
    held = set()
    for widget in (node.get("metadata") or {}).get("widgets") or []:
        if widget.get("type") != "dataset":
            continue
        choices = (widget.get("options") or {}).get("choices")
        if isinstance(choices, dict):
            held.update(choices.values())
        elif widget.get("value") or widget.get("default"):
            held.add(widget.get("value") or widget.get("default"))
    return held


def _title(node: dict) -> str:
    return f"{node['id']} ({node.get('title') or node['type']})"


@pytest.mark.parametrize("name", sorted(DATAFLOWS))
def test_no_python_or_javascript_node_loads_a_dataset(name):
    loading = {_title(n): _named(n) for n in _dataflow(name)["nodes"] if n["type"] in CODE_NODES and _named(n)}
    assert not loading, f"{name}: these code nodes load datasets themselves, not through a Data Loading node: {loading}"


@pytest.mark.parametrize("name", sorted(DATAFLOWS))
def test_no_data_loading_node_picks_among_datasets_in_its_code(name):
    picking = {_title(n): _named(n) for n in _dataflow(name)["nodes"] if n["type"] == DATA_LOADING and len(_named(n)) > 1}
    assert not picking, (
        f"{name}: these Data Loading nodes name several datasets in their code, and pick one there, "
        f"rather than through their Data widget: {picking}"
    )


@pytest.mark.parametrize("name", sorted(DATAFLOWS))
def test_every_dataset_the_dataflow_lists_has_its_data_loading_node(name):
    flow = _dataflow(name)
    listed = {ref["datasetId"] for ref in flow["datasets"]}
    loaded = set()
    for node in flow["nodes"]:
        if node["type"] == DATA_LOADING:
            loaded.update(_named(node))
            loaded.update(_held(node))
    assert listed - loaded == set(), f"{name}: no Data Loading node brings in {sorted(listed - loaded)}"


def test_example_32s_records_and_snapshots_follow_the_settings_camera():
    """Records and Snapshots each read the collection the camera of the
    Settings node picks, with a choice for each of the three cameras."""
    flow = _dataflow("example 32")
    by_id = {node["id"]: node for node in flow["nodes"]}
    settings = by_id["idot-settings"]
    cameras = [choice.split(" ")[0] for choice in settings["metadata"]["widgets"][0]["options"]["choices"]]
    pickers = {}
    for node in flow["nodes"]:
        if node["type"] != DATA_LOADING:
            continue
        for widget in (node.get("metadata") or {}).get("widgets") or []:
            options = widget.get("options") or {}
            if widget.get("type") == "dataset" and options.get("pickedBy"):
                pickers[node["id"]] = options
    assert sorted(pickers) == ["idot-records", "idot-snapshots"], pickers
    for node_id, options in pickers.items():
        assert options["pickedBy"] == "input_0.camera", node_id
        assert sorted(options["choices"]) == sorted(cameras), node_id
        feeding = [e["source"] for e in flow["edges"] if e["target"] == node_id and e.get("targetHandle") in (None, "in")]
        assert feeding == ["idot-settings"], (node_id, feeding)
