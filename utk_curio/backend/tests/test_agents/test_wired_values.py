"""A value several nodes read is a widget on one Python node, wired into each
reader: what the agents accept of such a wiring, with the roster rows the
shipped templates give (``_template_entry``, the rows every template listing
returns).

- A plan may wire a node into a Data Loading node: the loader takes inputs,
  so the plan's fan-in check (``_validate_plan_fanin``) passes it. So may it
  wire a season into an Accumulated Shadow's second circle, and a region into
  a Raster Calculator's third.
- The values pass a run's check of a node's output against what the nodes it
  feeds declare (``validation._consumer_type_mismatch``): a season, a str, is
  a VALUE an Accumulated Shadow takes, and a region, a dict, is JSON a Raster
  Calculator and a Data Loading node take.

The packages are read inside each test, so a checkout without the change
fails each test on its own.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

PYTHON = "curio.builtin/computation-analysis"
LOADER = "curio.builtin/data-loading"
RASTERIZE = "curio.scout/rasterize-buildings"
CALCULATOR = "curio.scout/raster-calculator"
SHADOW = "model.scout.deep-umbra/accumulated-shadow"
PACKAGES = ("curio.builtin@1", "curio.scout@1", "model.scout.deep-umbra@1")


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


def test_a_plan_may_wire_a_season_into_a_shadow_and_a_region_into_a_raster_calculator():
    """A season node feeds two Accumulated Shadow nodes' second circles, after
    their height rasters, and a region node a Raster Calculator's third, after
    two layers: no refusal. A shadow node takes two inputs at most, so a third
    is refused. Before, a shadow node took one input and a calculator no JSON."""
    from utk_curio.backend.app.agents.application.proposals.plans import _validate_plan_fanin

    available = _rows(*PACKAGES)
    assert [(port["types"], port["min"], port["max"]) for port in available[SHADOW]["inputs"]] == [
        (["RASTER", "VALUE"], 1, 2),
    ]
    assert [(port["types"], port["min"], port["max"]) for port in available[CALCULATOR]["inputs"]] == [
        (["RASTER", "GEODATAFRAME", "JSON"], 1, 3),
    ]
    nodes = [
        _plan_node("season", PYTHON), _plan_node("region", PYTHON),
        _plan_node("heights", RASTERIZE), _plan_node("towers", RASTERIZE),
        _plan_node("shadow", SHADOW), _plan_node("removed", SHADOW),
        _plan_node("tracts", LOADER), _plan_node("water", LOADER), _plan_node("average", CALCULATOR),
    ]
    edges = [
        {"from": "heights", "to": "shadow", "toHandle": "in"},
        {"from": "season", "to": "shadow", "toHandle": "in_1"},
        {"from": "towers", "to": "removed", "toHandle": "in"},
        {"from": "season", "to": "removed", "toHandle": "in_1"},
        {"from": "tracts", "to": "average", "toHandle": "in"},
        {"from": "water", "to": "average", "toHandle": "in_1"},
        {"from": "region", "to": "average", "toHandle": "in_2"},
    ]
    plan = {"goal": "Shadows in one season, and a region's mean depth.", "nodes": nodes, "edges": edges}
    assert _validate_plan_fanin(plan, available, {}, [], set(), set()) == []

    crowded = {**plan, "edges": [*edges, {"from": "region", "to": "shadow"}]}
    (refusal,) = _validate_plan_fanin(crowded, available, {}, [], set(), set())
    assert f"({SHADOW}) accepts at most 2 inputs but the plan wires 3" in refusal, refusal


def test_a_season_and_a_region_reach_their_readers_with_no_type_mismatch():
    """A run checks a node's output against what the nodes it feeds declare.
    The season node returns a str, a VALUE, which an Accumulated Shadow
    takes; the region node returns a dict, JSON, which a Raster Calculator
    and a Data Loading node take. A str into a Raster Calculator, which
    declares no VALUE, is still a mismatch."""
    from utk_curio.backend.app.agents.domain import validation

    available = _rows(*PACKAGES)
    spec = {"dataflow": {
        "nodes": [
            {"id": "season", "type": PYTHON, "goal": "The season"},
            {"id": "region", "type": f"{PYTHON}@1", "goal": "The region"},
            {"id": "shadow", "type": f"{SHADOW}@1", "goal": "Shadow"},
            {"id": "average", "type": f"{CALCULATOR}@1", "goal": "Average depth"},
            {"id": "load", "type": f"{LOADER}@1", "goal": "Depth"},
        ],
        "edges": [
            {"id": "e1", "source": "season", "target": "shadow", "targetHandle": "in_1"},
            {"id": "e2", "source": "region", "target": "average", "targetHandle": "in_2"},
            {"id": "e3", "source": "region", "target": "load", "targetHandle": "in"},
        ],
    }}
    assert validation._consumer_type_mismatch(spec, "season", "str", available) is None
    assert validation._consumer_type_mismatch(spec, "region", "dict", available) is None
    wrong = validation._consumer_type_mismatch(spec, "region", "str", available)
    assert wrong and "'Average depth'" in wrong, wrong
