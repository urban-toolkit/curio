"""What an agent writes for a Spatial Join: its operation and output are its
two widgets, Operation and Output, which its template declares and the code
it starts with places. An agent sets them as it sets any widgets: by name and
type in a plan or a node.create, keeping the template's choices, and by name
through node.settings.write on a join already on the canvas. A value they do
not offer is refused naming the widget's choices, and the setting the join
kept before its code, ``spatialJoin``, is refused where a plan or a
node.create still gives it.

The choices are those the join's function runs (``spatial_join`` in the
built-in package). The routes are ``test_node_settings_write.py``'s
(node.settings.write) and ``test_spatial_join_proposals.py``'s (a plan and a
node.create).

The names this adds are read inside each test, so a before-run fails here and
not the whole collection.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import re
from pathlib import Path

from utk_curio.backend.tests.test_agents.test_node_settings_write import JOIN_CODE, OPERATION, OUTPUT

REPO_ROOT = Path(__file__).resolve().parents[4]
BUILTIN = REPO_ROOT / "packages" / "curio.builtin@1"
DATAFLOW_BUILDER = "agent.curio.dataflow-builder@1"
NODE_BUILDER = "agent.curio.node-builder@1"
#: The Operation widget's choices, as a refusal names them.
OPERATIONS = "intersects, within, contains, touches, overlaps, crosses, nearest"
#: What a plan or a node.create is told, after where it gives the join's old setting.
OLD_SETTING = (
    ": a Spatial Join keeps its operation and output in its widgets operation and output: set them by name "
    'in widgets in a plan or a node.create, such as {"name": "operation", "type": "choice", "value": "within"}'
)


def _join_template() -> dict:
    manifest = json.loads((BUILTIN / "manifest.json").read_text(encoding="utf-8"))
    (template,) = [t for t in manifest["templates"] if t["id"] == "spatial-join"]
    return template


def _join_module():
    """The built-in package's ``spatial_join`` module, which the join's code imports."""
    spec = importlib.util.spec_from_file_location("spatial_join", BUILTIN / "sources" / "spatial_join.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_joins_two_widgets_offer_what_its_function_runs():
    template = _join_template()
    join = _join_module()
    assert template["widgets"] == [OPERATION, OUTPUT]
    assert OPERATION["options"]["choices"] == list(join.OPERATIONS)
    assert OUTPUT["options"]["choices"] == list(join.OUTPUTS)
    # A node with neither set does what the function does with neither given.
    parameters = inspect.signature(join.spatial_join).parameters
    assert (parameters["operation"].default, parameters["output"].default) == (OPERATION["default"], OUTPUT["default"])


def test_a_new_join_starts_with_its_templates_code_which_places_both_widgets():
    """Its starter is its whole content: a plan or a node.create gives a new
    join that code, and an agent never writes it."""
    template = _join_template()
    assert template.get("starterIsContent") is True
    assert (BUILTIN / template["source"]).read_text(encoding="utf-8") == JOIN_CODE
    assert re.findall(r"\[!! (\w+) !!\]", JOIN_CODE) == ["operation", "output"]


def test_the_node_describes_every_operation_it_runs():
    """The manifest's description, which the palette and every agent's
    preamble show, names each operation the join runs."""
    template = _join_template()
    for operation in OPERATION["options"]["choices"]:
        assert re.search(rf"\b{operation}\b", template["description"]), operation


def test_a_plan_or_a_node_create_sets_each_widget_by_name_and_type_among_its_choices():
    from utk_curio.backend.app.agents.domain import widget_grammar

    declared = [OPERATION, OUTPUT]
    written = [{"name": "operation", "type": "choice", "value": "within"},
               {"name": "output", "type": "choice", "value": "counts"}]
    assert widget_grammar.parse_widgets(written, "nodes[2].widgets", declared) == (
        [{**OPERATION, "value": "within"}, {**OUTPUT, "value": "counts"}], [],
    )
    # A value the widget does not offer is named with its choices.
    assert widget_grammar.parse_widgets(
        [{"name": "operation", "type": "choice", "value": "near"}], "nodes[2].widgets", declared,
    ) == ([], [f'nodes[2].widgets[0].value must be one of the operation widget\'s choices: {OPERATIONS}; got "near"'])
    # Its name and value alone are no widget: a plan's or a node.create's names its type too.
    assert widget_grammar.parse_widgets([{"name": "output", "value": "counts"}], "params.widgets", declared) == (
        [], ["params.widgets[0].type must be a text"],
    )


def test_a_join_on_the_canvas_takes_a_value_by_name_among_its_choices():
    from utk_curio.backend.app.agents.domain import widget_grammar

    widgets = [OPERATION, {**OUTPUT, "value": "counts"}]
    assert widget_grammar.parse_values({"operation": "within"}, widgets, "params.widgets", "Spatial Join") == (
        {"operation": "within"}, [],
    )
    assert widget_grammar.parse_values({"output": "polygons"}, widgets, "params.widgets", "Spatial Join") == (
        None, ['params.widgets.output must be one of the output widget\'s choices: pairs, counts; got "polygons"'],
    )
    # The change card names it as the node's Widgets tab does.
    assert widget_grammar.describe_value(OPERATION, "within") == "Operation: within"


def test_the_old_setting_is_refused_where_a_plan_or_a_node_create_gives_it():
    """A request that still gives it would otherwise land a join at
    intersects and pairs with no word: it is told where they went."""
    from utk_curio.backend.app.agents.domain import node_settings

    for setting in ({"predicate": "within", "output": "counts"}, {}, "within"):
        assert node_settings.parse({"spatialJoin": setting}, "nodes[2]") == (
            {}, [f"nodes[2].spatialJoin{OLD_SETTING}"],
        ), setting
    # Beside a setting a node keeps, which it still reads.
    assert node_settings.parse(
        {"spatialJoin": {"predicate": "nearest"}, "dataPool": {"betweenCharts": "MERGE_AND"}}, "params",
    ) == ({"dataPool": {"betweenCharts": "MERGE_AND"}}, [f"params.spatialJoin{OLD_SETTING}"])
    assert node_settings.parse({}, "params") == ({}, [])
    # No node keeps it: none of the settings a node keeps goes by it.
    assert node_settings.KEYS == ("dataPool", "simpleVis")


def test_the_example_the_refusal_gives_is_a_widget_a_join_takes():
    from utk_curio.backend.app.agents.domain import widget_grammar

    example = json.loads(OLD_SETTING.split("such as ", 1)[1])
    assert widget_grammar.parse_widgets([example], "params.widgets", [OPERATION, OUTPUT]) == (
        [{**OPERATION, "value": "within"}, OUTPUT], [],
    )


def test_no_tool_offers_the_old_setting():
    from utk_curio.backend.app.agents.application import tools

    planned = tools.REGISTRY["dataflow.plan.write"].parameters["properties"]["nodes"]["items"]["properties"]
    created = tools.REGISTRY["node.create"].parameters["properties"]
    changed = tools.REGISTRY["node.settings.write"].parameters["properties"]
    for properties in (planned, created, changed):
        assert "spatialJoin" not in properties
        assert "widgets" in properties
    for tool_id in ("dataflow.plan.write", "node.create", "node.settings.write", "dataflow.read"):
        contract = tools.REGISTRY[tool_id]
        for text in (contract.description, contract.native_description or ""):
            assert "spatialJoin" not in text and "Spatial Join's operation" not in text, tool_id


def test_every_agent_reads_what_a_join_holds_and_how_its_widgets_are_set():
    """The preamble places the nodes skill: the join's code calls
    spatial_join with its two widgets, a new join starts with that code and a
    plan or a node.create sets them by name, and node.settings.write changes
    them. Its Trill block shows no setting of the join's own."""
    from utk_curio.backend.app.agents.domain import builtin

    for coord in (DATAFLOW_BUILDER, NODE_BUILDER):
        preamble = builtin.read_prompt_text(coord, "system")
        assert (
            "A Spatial Join node's python code calls `spatial_join` to pair the rows of the GeoDataFrames on its two "
            "input circles whose shapes meet, as its choice widgets operation and output say. A new one starts "
            "with that code: set those widgets by name in a plan or a node.create, and one already on the canvas "
            "changes them through node.settings.write's widgets."
        ) in preamble, coord
        assert "spatialJoin" not in preamble, coord


def test_the_builders_set_a_joins_widgets_and_never_its_old_setting():
    from utk_curio.backend.app.agents.domain import builtin, widget_grammar

    instruction = builtin.read_prompt_text(DATAFLOW_BUILDER, "instruction")
    told = (
        "A planned Spatial Join starts with its template's code: set its operation and output widgets by name "
        'in a plan or a node.create, such as {"name": "operation", "type": "choice", "value": "within"}.'
    )
    assert told in instruction
    # The example it gives is one a plan's join takes.
    example = json.loads(told.split("such as ", 1)[1].rstrip("."))
    assert widget_grammar.parse_widgets([example], "nodes[0].widgets", [OPERATION, OUTPUT])[1] == []
    for coord in (DATAFLOW_BUILDER, NODE_BUILDER):
        text = builtin.read_prompt_text(coord, "instruction")
        assert "spatialJoin" not in text and "Spatial Join's operation" not in text, coord
