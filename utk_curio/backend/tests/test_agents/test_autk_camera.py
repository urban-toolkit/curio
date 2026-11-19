"""A map's ``camera`` reaches Curio's agents as an Autark node runs it.

The node frames each map on its layers, then turns it by the ``camera`` of its
own ``map`` entry (``src/adapters/node/autkMapView.ts``). So the agents' document
check accepts a camera and holds it to the grammar's schema, the reply schema a
provider holds a reply to keeps it, in both flavors, and the ``autark`` skill
says what it does, in the schema's own words. Everything is imported inside
each test, so a checkout without it fails each test on its own.
"""
from __future__ import annotations

import json

import pytest

AUTK = "curio.builtin/autk-grammar"
LAYERS = [{"dataRef": "input_0"}]


@pytest.mark.parametrize("document", [
    pytest.param({"map": {"camera": {"pitch": 50, "bearing": 30}, "layerRefs": LAYERS}}, id="tilted-and-turned"),
    pytest.param({"map": [{"camera": {"zoom": 15, "pitch": 40}, "layerRefs": LAYERS}]}, id="a-list-of-one-map"),
    pytest.param({"map": {"camera": {"zoom": 14}, "layerRefs": LAYERS}}, id="a-zoom-alone"),
])
def test_the_document_check_accepts_a_maps_camera(document):
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.app.agents.domain import document_validation as dv

    assert contracts.autk_key_problem(document) is None
    assert dv.validate(AUTK, json.dumps(document)) == {"status": dv.STATUS_VALID}


def test_the_document_check_holds_a_camera_to_the_grammars_schema():
    from utk_curio.backend.app.agents.domain import document_validation as dv

    # A pitch is less than 90: at 90 the eye would sit on the ground.
    verdict = dv.validate(AUTK, json.dumps({"map": {"camera": {"pitch": 120}, "layerRefs": LAYERS}}))
    assert verdict["status"] == dv.STATUS_INVALID
    assert "map.camera.pitch: 120 is greater than or equal to the maximum of 90" in verdict["detail"]


@pytest.mark.parametrize("flavor", ["closed", "strict"])
def test_the_reply_schema_keeps_a_maps_camera(flavor):
    from utk_curio.backend.app.agents.application import reply_schemas as rs

    reply = rs.autk_reply_schema(rs.FLAVOR_CLOSED if flavor == "closed" else rs.FLAVOR_STRICT)
    document = {"map": {"camera": {"zoom": 15, "pitch": 50, "bearing": 30}, "layerRefs": LAYERS}}
    encoded, dropped = reply.encode(document)
    assert dropped == []
    assert json.loads(reply.decode(json.dumps(encoded))) == document


def test_the_autark_skill_says_what_a_maps_camera_does():
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.tests._support.prompt_files import prompt_text

    schema = contracts.load_autk_schema()
    camera = contracts._definition(schema, "CameraSpec")
    region = contracts.render_autk_region(schema, "Autark").splitlines()
    skill = prompt_text("autark/SKILL.md")
    # Right under the map's line: the camera, then each of its fields, in the
    # schema's words, all of them in the skill an agent reads.
    at = next(i for i, line in enumerate(region) if line.startswith('- "map":'))
    said = camera["description"].split(" Read by the ", 1)[0]
    assert region[at + 1] == f'  - "camera": {said}'
    fields = [f'    - "{name}": {field["description"]}' for name, field in camera["properties"].items()]
    assert {"zoom", "pitch", "bearing"} <= set(camera["properties"])
    assert region[at + 2:at + 2 + len(fields)] == fields
    for line in [region[at + 1], *fields]:
        assert line in skill
