"""A Data Pool's conflict modes and a Simple View's image column, as an agent
sets them on a node it places: shaped as a node's ``metadata.dataPool`` and
``metadata.simpleVis`` in the Trill schema, judged by each node's own rule and
worded as the node's own controls word them, with an error the model can act
on for each one that is wrong. What a saved node's settings make it do,
a Spatial Join's operation and output among them, is what ``dataflow.read``
shows of it.

The pool's rule is ``utils/dataPoolSpec.ts``: a value that names no mode reads
as OVERWRITE, and only the modes that are not OVERWRITE are written.
``dataPoolSpec.cases.json`` beside it holds the cases both sides run
(``src/tests/utils/dataPoolSpec.test.ts`` is the pool's half). The words are
``src/contracts/nodeSettings.json``, which the pool, the view, the review card
and the backend read.

The modules this adds are imported inside each test, so a before-run fails
here and not the whole collection.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
FRONTEND_SRC = REPO_ROOT / "utk_curio" / "frontend" / "urban-workflows" / "src"
CASES_FILE = FRONTEND_SRC / "utils" / "dataPoolSpec.cases.json"
DATAFLOW_BUILDER = "agent.curio.dataflow-builder@1"


def _pool():
    from utk_curio.backend.app.agents.domain import data_pool_settings

    return data_pool_settings


def _view():
    from utk_curio.backend.app.agents.domain import simple_vis_settings

    return simple_vis_settings


def _words() -> dict:
    """The words of the nodes' settings, read as the backend reads them."""
    from utk_curio.common import shared_constants

    return shared_constants.read("nodeSettings")


def _trill() -> dict:
    return json.loads((REPO_ROOT / "docs" / "schemas" / "trill.v1.json").read_text(encoding="utf-8"))


def _trill_setting(key: str) -> dict:
    return _trill()["$defs"]["nodeMetadata"]["properties"][key]


def _resolution_types() -> list[str]:
    """The pool's modes, ``ResolutionType`` in ``constants.ts``, in its order."""
    text = (FRONTEND_SRC / "constants.ts").read_text(encoding="utf-8")
    block = re.search(r"export enum ResolutionType\s*\{(.*?)\}", text, re.S)
    assert block, "could not find the ResolutionType enum in constants.ts"
    modes = re.findall(r'=\s*"([A-Z_]+)"', block.group(1))
    assert modes, "parsed no members out of ResolutionType"
    return modes


def _cases():
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


def test_the_pools_shape_is_the_trill_schemas_and_its_modes_the_pools_own():
    pool = _pool()
    modes = _resolution_types()
    trill = _trill_setting("dataPool")
    assert list(trill["properties"]) == list(pool.SETTING_KEYS)
    assert trill["additionalProperties"] is False
    for key in pool.SETTING_KEYS:
        # What a saved dataflow takes is what the pool resolves with.
        assert trill["properties"][key]["enum"] == modes
    assert list(pool.MODES) == modes
    assert pool.DEFAULT == "OVERWRITE" and pool.DEFAULT in modes


def test_the_views_shape_is_the_trill_schemas():
    view = _view()
    trill = _trill_setting("simpleVis")
    assert list(trill["properties"]) == list(view.SETTING_KEYS)
    assert trill["properties"]["imageColumn"] == {"type": "string", "minLength": 1}
    assert trill["additionalProperties"] is False


def test_the_words_are_the_nodes_own_and_name_every_mode():
    """One file holds the words of the pool's two selects and of each mode,
    and the label of the view's image column, as the nodes show them today."""
    words = _words()
    pool = words["dataPool"]
    assert list(pool["settings"]) == list(_pool().SETTING_KEYS)
    assert list(pool["modes"]) == _resolution_types()
    assert pool["settings"] == {
        "insideChart": "Conflict inside visualization",
        "betweenCharts": "Conflict between visualizations",
    }
    assert pool["modes"] == {"OVERWRITE": "Overwrite", "MERGE_AND": "Merge (AND)", "MERGE_OR": "Merge (OR)"}
    assert words["simpleVis"]["settings"] == {"imageColumn": "Image column"}
    assert list(words["simpleVis"]["settings"]) == list(_view().SETTING_KEYS)


@pytest.mark.parametrize("case", _cases())
def test_an_agent_stores_what_the_pool_writes_and_is_refused_what_it_would_read_as_overwrite(case):
    pool = _pool()
    setting, errors = pool.parse(case["given"], "nodes[0].dataPool")
    agent = case["agent"]
    if "stores" in agent:
        assert errors == []
        assert setting == case["written"] == agent["stores"]
        return
    assert setting is None
    assert errors, "refused without saying why"
    assert all(e.startswith("nodes[0].dataPool") for e in errors), errors
    refused = agent["refuses"]
    if refused in pool.SETTING_KEYS:
        assert any(e.startswith(f"nodes[0].dataPool.{refused} ") for e in errors), errors
    elif refused is not None:
        assert any(refused in e for e in errors), errors


def test_a_setting_is_kept_as_the_node_stores_it():
    pool, view = _pool(), _view()
    assert pool.parse({"betweenCharts": "MERGE_AND"}, "w") == ({"betweenCharts": "MERGE_AND"}, [])
    assert pool.parse(None, "w") == (None, [])
    # The view trims the name it reads, so the name is kept trimmed.
    assert view.parse({"imageColumn": " overlay_url "}, "w") == ({"imageColumn": "overlay_url"}, [])
    # Absent, or empty, sets nothing: the view shows every image column.
    assert view.parse(None, "w") == (None, [])
    assert view.parse({}, "w") == (None, [])


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("MERGE_AND", "nodes[1].dataPool must be an object, such as"),
        ({"betweenCharts": "MERGE_AND", "propagate": "MERGE_OR"},
         "nodes[1].dataPool has keys a Data Pool does not: propagate (it has insideChart, betweenCharts)"),
        ({"betweenCharts": "MERGE_(AND)"},
         "nodes[1].dataPool.betweenCharts must be one of OVERWRITE, MERGE_AND, MERGE_OR; got 'MERGE_(AND)', "
         "which a Data Pool reads as OVERWRITE"),
        ({"insideChart": "AND", "betweenCharts": "or"},
         "nodes[1].dataPool.insideChart must be one of OVERWRITE, MERGE_AND, MERGE_OR; got 'AND'"),
    ],
)
def test_each_wrong_mode_is_named(raw, expected):
    setting, errors = _pool().parse(raw, "nodes[1].dataPool")
    assert setting is None
    assert any(expected in e for e in errors), errors
    assert all(e.startswith("nodes[1].dataPool") for e in errors), errors


def test_every_member_that_names_no_mode_is_named():
    _setting, errors = _pool().parse({"insideChart": "AND", "betweenCharts": "or"}, "params.dataPool")
    assert [e.split(" ", 1)[0] for e in errors] == ["params.dataPool.insideChart", "params.dataPool.betweenCharts"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("overlay_url", "nodes[1].simpleVis must be an object, such as"),
        ({"imageColumn": "overlay_url", "column": "image_url"},
         "nodes[1].simpleVis has keys a Simple View does not: column (it has imageColumn)"),
        ({"imageColumn": ""}, "nodes[1].simpleVis.imageColumn must name a column, such as"),
        ({"imageColumn": "   "}, "nodes[1].simpleVis.imageColumn must name a column, such as"),
        ({"imageColumn": None}, "nodes[1].simpleVis.imageColumn must name a column, such as"),
        ({"imageColumn": 3}, "nodes[1].simpleVis.imageColumn must name a column, such as"),
    ],
)
def test_each_wrong_image_column_is_named(raw, expected):
    setting, errors = _view().parse(raw, "nodes[1].simpleVis")
    assert setting is None
    assert any(expected in e for e in errors), errors
    assert all(e.startswith("nodes[1].simpleVis") for e in errors), errors


def test_only_a_template_with_the_nodes_behavior_takes_its_setting():
    """By the behavior its template names, as ``packages.template_behavior``
    reads it: the account's copy of the template, else the catalog's."""
    pool, view = _pool(), _view()
    assert pool.template_problem("data-pool", "Data Pool", "w") is None
    assert view.template_problem("simple-vis", "Simple View", "w") is None
    # A package's own template that names the node's behavior takes it too.
    assert pool.template_problem("data-pool", "Selections", "w") is None
    assert pool.template_problem("simple-vis", "Simple View", "params.dataPool") == (
        "params.dataPool: a Simple View node has no conflict modes; only a Data Pool node takes dataPool"
    )
    assert view.template_problem("data-pool", "Data Pool", "plan node 'pool'") == (
        "plan node 'pool': a Data Pool node has no image column; only a Simple View node takes simpleVis"
    )
    assert view.template_problem(None, "Computation Analysis", "params.simpleVis") == (
        "params.simpleVis: a Computation Analysis node has no image column; only a Simple View node takes simpleVis"
    )


def test_the_card_says_each_setting_in_the_nodes_own_words():
    pool, view = _pool(), _view()
    assert pool.describe({"betweenCharts": "MERGE_AND"}) == "Conflict between visualizations: Merge (AND)"
    assert pool.describe({"insideChart": "MERGE_OR", "betweenCharts": "MERGE_AND"}) == (
        "Conflict inside visualization: Merge (OR); Conflict between visualizations: Merge (AND)"
    )
    assert view.describe({"imageColumn": "overlay_url"}) == "Image column: overlay_url"


def test_both_tools_that_place_a_node_offer_the_settings_with_the_nodes_choices():
    from utk_curio.backend.app.agents.application import tools

    modes = _resolution_types()
    plan_node = tools.REGISTRY["dataflow.plan.write"].parameters["properties"]["nodes"]["items"]
    created = tools.REGISTRY["node.create"].parameters
    for properties in (plan_node["properties"], created["properties"]):
        pool = properties["dataPool"]
        assert pool["type"] == "object"
        assert list(pool["properties"]) == ["insideChart", "betweenCharts"]
        for key in ("insideChart", "betweenCharts"):
            assert pool["properties"][key]["type"] == "string"
            assert pool["properties"][key]["enum"] == modes
        view = properties["simpleVis"]
        assert view["type"] == "object"
        assert list(view["properties"]) == ["imageColumn"]
        assert view["properties"]["imageColumn"]["type"] == "string"
    for key in ("dataPool", "simpleVis"):
        # Optional on both: a node that is neither never gives it.
        assert key not in plan_node.get("required", [])
        assert key not in created.get("required", [])
        # And the fenced form names it too.
        assert f'"{key}"' in tools.REGISTRY["dataflow.plan.write"].description
        assert f'"{key}"' in tools.REGISTRY["node.create"].description


def test_every_agent_reads_the_settings_shapes_in_its_preamble():
    """The preamble's Trill block shows what an agent writes into a node's
    metadata: the pool's modes, with their choices, and the view's image
    column, read the way a run reads the preamble."""
    from utk_curio.backend.app.agents.domain import builtin, contracts

    text = contracts.render_trill_block(_trill())
    node = json.loads(text)["properties"]["dataflow"]["properties"]["nodes"]["items"]
    metadata = node["properties"]["metadata"]["properties"]
    modes = _resolution_types()
    assert metadata["dataPool"] == {
        "type": "object",
        "properties": {
            "insideChart": {"type": "string", "enum": modes},
            "betweenCharts": {"type": "string", "enum": modes},
        },
    }
    assert metadata["simpleVis"] == {"type": "object", "properties": {"imageColumn": {"type": "string"}}}
    preamble = builtin.read_prompt_text(DATAFLOW_BUILDER, "system")
    assert text in preamble
    assert json.dumps(modes) in preamble


def test_the_dataflow_builder_is_told_where_a_planned_pool_and_view_keep_their_settings():
    from utk_curio.backend.app.agents.domain import builtin

    instruction = builtin.read_prompt_text(DATAFLOW_BUILDER, "instruction")
    assert 'in its "dataPool"' in instruction
    assert '"metadata"."dataPool"' in instruction
    assert 'in its "simpleVis"' in instruction
    assert '"metadata"."simpleVis"' in instruction


def _row(metadata: dict) -> dict:
    from utk_curio.backend.app.agents.application import tools

    return tools._node_row({"id": "n1", "type": "t", "content": "", "metadata": metadata}, goal_cap=200)


def test_dataflow_read_shows_what_each_nodes_settings_make_it_do():
    """What an agent reads of a saved node is what the node does with it: the
    pool's modes other than Overwrite, the view's image column as the view
    trims it, and the join's operation and output other than its defaults."""
    pool = _row({"dataPool": {"insideChart": "OVERWRITE", "betweenCharts": "MERGE_AND"}})
    assert pool["dataPool"] == {"betweenCharts": "MERGE_AND"}
    view = _row({"simpleVis": {"imageColumn": " overlay_url "}})
    assert view["simpleVis"] == {"imageColumn": "overlay_url"}
    join = _row({"spatialJoin": {"predicate": "within", "output": "counts"}})
    assert join["spatialJoin"] == {"predicate": "within", "output": "counts"}
    assert _row({"spatialJoin": {"predicate": "nearest"}})["spatialJoin"] == {"predicate": "nearest"}


def test_dataflow_read_shows_no_setting_a_node_reads_as_its_default():
    # The pool reads a value that names no mode as Overwrite, the view an
    # empty name as every image column, and the join a predicate it does not
    # run as intersects.
    plain = _row({
        "dataPool": {"insideChart": "OVERWRITE", "betweenCharts": "MERGE_(AND)"},
        "simpleVis": {"imageColumn": "  "},
        "spatialJoin": {"predicate": "near", "output": "pairs"},
    })
    assert not {"dataPool", "simpleVis", "spatialJoin"} & set(plain), plain
    assert not {"dataPool", "simpleVis", "spatialJoin"} & set(_row({})), _row({})
