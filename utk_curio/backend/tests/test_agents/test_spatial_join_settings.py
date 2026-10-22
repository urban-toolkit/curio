"""The operation and output an agent sets on a Spatial Join node: shaped as a
node's ``metadata.spatialJoin`` in the Trill schema and judged by the join's
own rule, the one its route answers with, with an error the model can act on
for each one that is wrong.

The modules this adds are imported inside each test, so a before-run fails
here and not the whole collection.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DATAFLOW_BUILDER = "agent.curio.dataflow-builder@1"


def _settings():
    from utk_curio.backend.app.agents.domain import spatial_join_settings

    return spatial_join_settings


def _trill_setting() -> dict:
    schema = json.loads((REPO_ROOT / "docs" / "schemas" / "trill.v1.json").read_text(encoding="utf-8"))
    return schema["$defs"]["nodeMetadata"]["properties"]["spatialJoin"]


def test_the_shape_is_the_trill_schemas_and_the_choices_are_the_joins():
    from utk_curio.backend.app.common import spatial

    settings = _settings()
    trill = _trill_setting()
    assert list(trill["properties"]) == list(settings.SETTING_KEYS)
    # What a saved dataflow takes is what the join runs.
    assert trill["properties"]["predicate"]["enum"] == list(spatial.PREDICATES)
    assert trill["properties"]["output"]["enum"] == list(spatial.OUTPUTS)


def test_the_node_describes_every_operation_it_runs():
    """The manifest's description, which the palette and every agent's preamble
    show, names each operation the join runs."""
    import re

    from utk_curio.backend.app.common import spatial

    manifest = json.loads((REPO_ROOT / "packages" / "curio.builtin@1" / "manifest.json").read_text(encoding="utf-8"))
    join = next(t for t in manifest["templates"] if t.get("behavior") == "spatial-join")
    for predicate in spatial.PREDICATES:
        assert re.search(rf"\b{predicate}\b", join["description"]), predicate


def test_a_setting_is_kept_as_a_node_stores_it():
    settings = _settings()
    assert settings.parse({"predicate": "within", "output": "counts"}, "nodes[2].spatialJoin") == (
        {"predicate": "within", "output": "counts"}, [],
    )
    assert settings.parse({"predicate": "nearest"}, "w") == ({"predicate": "nearest"}, [])
    # Absent, or empty, sets nothing: the node keeps intersects and pairs.
    assert settings.parse(None, "w") == (None, [])
    assert settings.parse({}, "w") == (None, [])


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("within", "must be an object"),
        ({"predicate": "within", "operation": "within"}, "has keys a Spatial Join does not: operation"),
        ({"predicate": "near"}, "The operation must be one of intersects, within, contains, touches, "
                                "overlaps, crosses, nearest; got 'near'."),
        ({"output": "polygons"}, "The output must be one of pairs, counts; got 'polygons'."),
        ({"predicate": None}, "The operation must be one of"),
    ],
)
def test_each_wrong_setting_is_named(raw, expected):
    setting, errors = _settings().parse(raw, "nodes[1].spatialJoin")
    assert setting is None
    assert any(expected in e for e in errors), errors
    assert all(e.startswith("nodes[1].spatialJoin") for e in errors), errors


def test_a_wrong_operation_is_refused_in_the_words_the_joins_route_answers_with(client):
    """One rule: the agents' check and the node's own route both ask it."""
    from utk_curio.backend.app.common import spatial

    points = {"type": "FeatureCollection", "features": []}
    answer = client.post("/spatial_join", json={"left": points, "right": points, "predicate": "near"})
    assert answer.status_code == 400
    assert answer.get_json()["error"] == spatial.settings_problem("near", spatial.DEFAULT_OUTPUT)
    _, errors = _settings().parse({"predicate": "near"}, "params.spatialJoin")
    assert errors == [f"params.spatialJoin: {spatial.settings_problem('near', spatial.DEFAULT_OUTPUT)}"]


def test_only_a_template_with_the_joins_behavior_takes_a_setting():
    """By the behavior its template names, as ``packages.template_behavior``
    reads it: the account's copy of the template, else the catalog's."""
    settings = _settings()
    assert settings.template_problem("spatial-join", "Spatial Join", "w") is None
    # A package's own template that names the join's behavior takes it too.
    assert settings.template_problem("spatial-join", "Overlay", "w") is None
    assert settings.template_problem(None, "Computation Analysis", "params.spatialJoin") == (
        "params.spatialJoin: a Computation Analysis node has no operation or output; "
        "only a Spatial Join node takes spatialJoin"
    )


def test_both_tools_that_place_a_node_offer_the_setting_with_the_joins_choices():
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.common import spatial

    settings = _settings()
    plan_node = tools.REGISTRY["dataflow.plan.write"].parameters["properties"]["nodes"]["items"]
    created = tools.REGISTRY["node.create"].parameters
    for schema in (plan_node["properties"]["spatialJoin"], created["properties"]["spatialJoin"]):
        assert schema["type"] == "object"
        assert list(schema["properties"]) == list(settings.SETTING_KEYS)
        assert schema["properties"]["predicate"]["enum"] == list(spatial.PREDICATES)
        assert schema["properties"]["output"]["enum"] == list(spatial.OUTPUTS)
    # Optional on both: a node that is no Spatial Join never gives it.
    assert "spatialJoin" not in plan_node.get("required", [])
    assert "spatialJoin" not in created.get("required", [])
    # And the fenced form names it too.
    assert '"spatialJoin"' in tools.REGISTRY["dataflow.plan.write"].description
    assert '"spatialJoin"' in tools.REGISTRY["node.create"].description


def test_every_agent_reads_the_settings_shape_in_its_preamble():
    """The preamble's Trill block shows what an agent writes into a node's
    metadata: the setting is there, with the join's choices, read the way a
    run reads the preamble."""
    from utk_curio.backend.app.agents.domain import builtin
    from utk_curio.backend.app.common import spatial

    preamble = builtin.read_prompt_text(DATAFLOW_BUILDER, "system")
    assert '"spatialJoin": {' in preamble
    assert json.dumps(list(spatial.PREDICATES)) in preamble
    assert json.dumps(list(spatial.OUTPUTS)) in preamble


def test_the_dataflow_builder_is_told_where_a_planned_join_says_how_it_joins():
    from utk_curio.backend.app.agents.domain import builtin

    instruction = builtin.read_prompt_text(DATAFLOW_BUILDER, "instruction")
    assert 'in "spatialJoin"' in instruction
    assert '"metadata"."spatialJoin"' in instruction
