"""Curio's agents are never shown a key an Autark node does not run yet.

Each key under the node's interim refusal (``contracts.AUTK_NOT_RUN_YET``,
from ``autkGrammar.json``'s ``notRunYet``) is left out of the schema the
agents read (``contracts.autk_schema_curio_runs``), so it is out of the
autark skill's text and out of the reply schema a provider holds a reply to,
in both flavors. A document of the kinds a node runs is still described and
still fits. Everything is imported inside each test, so a checkout without it
fails each test on its own.
"""
from __future__ import annotations

import json

import pytest

#: Where each place of a rule is in the schema: the root's property it names.
_PLACES = ("", "data[]", "compute[]", "map[]", "plot[]")


def _resolve(defs: dict, node):
    while isinstance(node, dict) and "$ref" in node:
        node = defs.get(node["$ref"].rsplit("/", 1)[-1], {})
    return node


def _holders(defs: dict, node, seen=None) -> list[dict]:
    """The objects a value written at *node* can be: through ``$ref``,
    ``items``, ``anyOf``, ``oneOf`` and an ``allOf`` member's ``then``, not
    into an object's own properties."""
    seen = set() if seen is None else seen
    node = _resolve(defs, node)
    if not isinstance(node, dict) or id(node) in seen:
        return []
    seen.add(id(node))
    found = [node] if isinstance(node.get("properties"), dict) else []
    for inner in [node.get("items"), *node.get("anyOf", []), *node.get("oneOf", []),
                  *[clause.get("then") for clause in node.get("allOf", []) if isinstance(clause, dict)]]:
        if isinstance(inner, dict):
            found += _holders(defs, inner, seen)
    return found


def _place(schema: dict, defs: dict, place: str):
    root = _resolve(defs, {"$ref": schema.get("$ref", "#/definitions/UrbanSpec")}) if "$ref" in schema else schema
    if place == "":
        return root
    return root.get("properties", {}).get(place.removesuffix("[]"))


def _written(schema: dict, rule: dict) -> list[str]:
    """Where *schema* still lets a document write what *rule* refuses."""
    defs = schema.get("definitions") or schema.get("$defs") or {}
    found = []
    for holder in _holders(defs, _place(schema, defs, rule["in"])):
        prop = _resolve(defs, holder["properties"].get(rule["key"]))
        if not isinstance(prop, dict):
            continue
        if "value" not in rule:
            found.append(f'{rule["in"]} {rule["key"]}')
            continue
        values = [prop.get("const"), *prop.get("enum", [])]
        for member in prop.get("anyOf", []):
            member = _resolve(defs, member)
            if isinstance(member, dict):
                values += [member.get("const"), *member.get("enum", [])]
        if rule["value"] in values:
            found.append(f'{rule["in"]} {rule["key"]} {rule["value"]}')
    return found


def test_every_rule_names_a_place_of_the_document():
    from utk_curio.backend.app.agents.domain import contracts

    assert contracts.AUTK_NOT_RUN_YET
    for rule in contracts.AUTK_NOT_RUN_YET:
        assert rule["in"] in _PLACES, rule
        # The full schema lets a document write it: the rule refuses a key of the grammar.
        assert _written(contracts.load_autk_schema(), rule), rule


def test_the_schema_the_agents_read_lets_no_document_write_a_refused_key():
    from utk_curio.backend.app.agents.domain import contracts

    schema = contracts.autk_schema_curio_runs(contracts.load_autk_schema())
    assert [where for rule in contracts.AUTK_NOT_RUN_YET for where in _written(schema, rule)] == []
    # Leaving them out leaves the rest: a GPGPU pass, a join, a map and a plot.
    assert {"compute", "data", "map", "plot"} <= set(contracts.autk_families(schema))
    types = schema["definitions"]["DataSourceSpec"]["properties"]["type"]["enum"]
    assert {"osm", "csv", "json", "geojson", "join"} <= set(types)


@pytest.mark.parametrize("flavor", ["closed", "strict"])
def test_the_reply_schema_lets_no_reply_write_a_refused_key(flavor):
    from utk_curio.backend.app.agents.application import reply_schemas as rs
    from utk_curio.backend.app.agents.domain import contracts

    reply = rs.autk_reply_schema(rs.FLAVOR_CLOSED if flavor == "closed" else rs.FLAVOR_STRICT)
    found = [where for rule in contracts.AUTK_NOT_RUN_YET for where in _written(reply.schema, rule)]
    assert found == []
    # A refused key in a reply is not kept: the projection drops it.
    document = {"map": {"camera": {"pitch": 40}, "layerRefs": [{"dataRef": "input_0"}]}}
    encoded, dropped = reply.encode(document)
    assert dropped == ["$.map.camera"]
    assert json.loads(reply.decode(json.dumps(encoded))) == {"map": {"layerRefs": [{"dataRef": "input_0"}]}}


@pytest.mark.parametrize("flavor", ["closed", "strict"])
def test_the_reply_schema_keeps_a_pass_that_writes_a_new_table_and_its_type(flavor):
    """A node runs a pass's ``outputTableName`` and ``layerType``, so a reply
    that writes them keeps them, whole."""
    from utk_curio.backend.app.agents.application import reply_schemas as rs

    reply = rs.autk_reply_schema(rs.FLAVOR_CLOSED if flavor == "closed" else rs.FLAVOR_STRICT)
    document = {
        "compute": [{
            "dataRef": "input_0", "attributes": {"v": "properties.value"}, "wgslFunction": "return v * 2.0;",
            "outputColumnName": "twice", "outputTableName": "doubled", "layerType": "points",
        }],
        "map": {"layerRefs": [{"dataRef": "doubled", "getFnv": "twice"}]},
    }
    encoded, dropped = reply.encode(document)
    assert dropped == []
    assert json.loads(reply.decode(json.dumps(encoded))) == document


#: A document whose render pass writes the table its map draws: the towers
#: seen from each spot, in four directions, with the share of the sky.
RENDER_DOCUMENT = {
    "compute": [{
        "type": "render", "outputTableName": "sky",
        "layers": [{"id": "towers", "dataRef": "towers", "type": "buildings"}],
        "viewpoints": {"dataRef": "spots", "sampling": {"directions": 4, "pitchDeg": 45}},
        "aggregation": {"type": "classes", "includeBackground": True, "backgroundLayerType": "sky"},
        "tileSize": 64,
    }],
    "map": {"layerRefs": [{"dataRef": "sky", "getFnv": "compute.render.classes.sky"}]},
}


@pytest.mark.parametrize("flavor", ["closed", "strict"])
def test_the_reply_schema_lets_a_reply_write_a_render_pass(flavor):
    """A node runs render passes, so the reply schema holds their branch: a
    reply that writes one fits the schema a provider holds it to, and decodes
    back whole."""
    import jsonschema

    from utk_curio.backend.app.agents.application import reply_schemas as rs

    reply = rs.autk_reply_schema(rs.FLAVOR_CLOSED if flavor == "closed" else rs.FLAVOR_STRICT)
    assert _written(reply.schema, {"in": "compute[]", "key": "type", "value": "render"})
    encoded, dropped = reply.encode(RENDER_DOCUMENT)
    assert dropped == []
    jsonschema.Draft202012Validator(reply.schema).validate(encoded)
    assert json.loads(reply.decode(json.dumps(encoded))) == RENDER_DOCUMENT


def test_the_autark_skill_says_what_a_render_pass_requires():
    """The autark skill tells a render pass apart from a GPGPU pass, with what
    each requires, and so does the shape a refusal names."""
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.tests._support.prompt_files import prompt_text

    text = prompt_text("autark/SKILL.md")
    render = next((line for line in text.splitlines() if line.startswith('  - "type": "render":')), None)
    assert render is not None, text
    for field in ("aggregation", "layers", "outputTableName", "viewpoints"):
        assert f'"{field}"' in render, render
    # The types a render layer is drawn as; a render pass draws no points.
    for layer_type in ("surface", "parks", "water", "roads", "buildings", "polygons", "polylines"):
        assert f'"{layer_type}"' in render, render
    assert '"points"' not in render, render
    compute = next(line for line in text.splitlines() if line.startswith('- "compute":'))
    assert "Every pass" not in compute, compute
    shape = contracts.render_autk_shape(contracts.load_autk_schema())
    assert '"type": "render"' in shape and '"viewpoints"' in shape, shape


def test_the_autark_skill_names_no_family_or_kind_a_node_refuses():
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.tests._support.prompt_files import prompt_text

    text = prompt_text("autark/SKILL.md")
    families = next(line for line in text.splitlines() if "A document names at least one of" in line)
    for rule in contracts.AUTK_NOT_RUN_YET:
        if rule["in"] == "":
            assert f'"{rule["key"]}"' not in families, rule
        elif rule["in"] == "data[]" and "value" in rule:
            assert f'- "{rule["value"]}":' not in text, rule
    compute = next(line for line in text.splitlines() if line.startswith('- "compute":'))
    for rule in contracts.AUTK_NOT_RUN_YET:
        if rule["in"] == "compute[]" and "value" not in rule:
            assert f'"{rule["key"]}"' not in compute, rule
    # What a node runs is still there.
    for family in ("compute", "data", "map", "plot"):
        assert f'"{family}"' in families
    assert '- "join":' in text
