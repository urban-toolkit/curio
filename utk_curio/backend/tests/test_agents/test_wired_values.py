"""A value several nodes read is a widget on one Python node, wired into each
reader: what the agents accept of such a wiring, with the roster rows the
shipped templates give (``_template_entry``, the rows every template listing
returns).

- A plan may wire a node into a Data Loading node: the loader takes inputs,
  so the plan's fan-in check (``_validate_plan_fanin``) passes it.

The packages are read inside each test, so a checkout without the change
fails each test on its own.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

PYTHON = "curio.builtin/computation-analysis"
LOADER = "curio.builtin/data-loading"


def _rows(*dir_names: str) -> dict:
    """The roster rows of the shipped packages *dir_names*, by canonical id,
    as the agents' template listings build them."""
    from utk_curio.backend.app.packages.application.templates import _template_entry
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    rows = {}
    for dir_name in dir_names:
        manifest = load_package_manifest(REPO / "packages" / dir_name)
        for template in manifest.templates:
            row = _template_entry(manifest.package_id, template)
            rows[row["id"]] = row
    return rows


def _plan_node(ref: str, node_type: str) -> dict:
    return {"ref": ref, "nodeType": node_type, "title": ref.title(), "intent": f"the {ref}"}


def test_a_plan_may_wire_a_value_node_into_data_loading_nodes():
    """An area node feeds two loaders, and a period node the second one's next
    circle: no refusal. Before Data Loading took inputs, the check refused
    every one of these edges ("accepts no inputs")."""
    from utk_curio.backend.app.agents.application.proposals.plans import _validate_plan_fanin

    available = _rows("curio.builtin@1")
    loader = available[LOADER]
    assert [(port["types"], port["min"], port["max"]) for port in loader["inputs"]] == [
        (["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON", "RASTER"], 0, None),
    ]
    assert loader["maxIncomingEdges"] is None
    plan = {
        "goal": "Read one area's window of two rasters, one for a period.",
        "nodes": [
            _plan_node("area", PYTHON), _plan_node("period", PYTHON),
            _plan_node("classes", LOADER), _plan_node("depth", LOADER),
        ],
        "edges": [
            {"from": "area", "to": "classes"},
            {"from": "area", "to": "depth", "toHandle": "in"},
            {"from": "period", "to": "depth", "toHandle": "in_1"},
        ],
    }
    assert _validate_plan_fanin(plan, available, {}, [], set(), set()) == []
