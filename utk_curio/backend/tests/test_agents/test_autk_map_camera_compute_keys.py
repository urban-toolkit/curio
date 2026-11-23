"""autk-grammar 5.3.0's map keys and 5.4.0's camera and compute keys reach
Curio's agents as an Autark node runs them.

An Autark node draws a map raised on a raster's band (``terrain``), in a
style of its own (``style``'s colors), its picked features and values it cannot
color in colors of its own (``highlightColor``, ``invalidValueColor``), with or
without autk-map's menu and legend (``showUi``); layers drawn as another type
(``layerType``), with each line's own width (``widthBy``), in the legend
(``legend``), with features hidden (``skippedComps``) or picked from the start
(``pickedComps``), and buildings without a height raised at random
(``buildingsZeroHeight``); a camera that looks at a point (``center``) and
plays a tour (``motion``); and ``windows`` and ``clusters`` passes. So the
``autark`` skill names each in the schema's words, the reply schema a provider
holds a reply to keeps each, in both flavors, and the agents' document check
takes each, and refuses what the grammar's schema refuses. Everything is
imported inside each test, so a checkout without it fails each test on its
own.
"""
from __future__ import annotations

import json

import pytest

AUTK = "curio.builtin/autk-grammar"

STYLE = {
    "background": "#0b1a2a", "surface": "#13263a", "parks": "#1f4d3a", "water": "#08121d", "roads": "#3a5068",
    "buildings": "#5b7083", "points": "#f2c14e", "polylines": "#7f97ad", "polygons": "#2a3d52",
}

#: Documents that write the keys, a few to a document.
DOCUMENTS = {
    "a map raised on a raster's band, in a style of its own, its own colors, no controls": {
        "data": [{"type": "geotiff", "outputTableName": "lst",
                  "geotiffFileUrl": "docs/examples/data/niteroi_lst_verao_2001_2024.tif"}],
        "map": {
            "terrain": {"dataRef": "lst", "band": "band_24"}, "style": STYLE,
            "highlightColor": "#ff7f0e", "invalidValueColor": "#bfbfbf", "showUi": False,
            "layerRefs": [{"dataRef": "lst", "getFnv": "band_24"}],
        },
    },
    "layers drawn as roads by their widths, in the legend, hidden, picked, of buildings with no height": {
        "map": {"style": "light", "layerRefs": [
            {"dataRef": "input_0", "layerType": "roads", "widthBy": "lanes", "skippedComps": [2, 5]},
            {"dataRef": "input_1", "getFnv": "height", "legend": True, "buildingsZeroHeight": True},
            {"dataRef": "input_2", "isPick": True, "pickedComps": [0, 4]},
        ]},
    },
    "a camera that looks at a point and plays a tour": {
        "map": {
            "camera": {"center": [-74.011, 40.7069], "zoom": 13, "motion": [
                {"type": "zoom", "amount": 1.5, "seconds": 2},
                {"type": "pitch", "amount": 55, "seconds": 2.5, "pan": 150},
                {"type": "bearing", "amount": 90, "seconds": 4},
                {"type": "roll", "amount": 15, "seconds": 1},
            ]},
            "layerRefs": [{"dataRef": "input_0"}],
        },
    },
    "windows and clusters passes": {
        "compute": [
            {"type": "windows", "dataRef": "input_0", "floors": 3, "outputTableName": "windows"},
            {"type": "clusters", "dataRef": "input_0", "outputColumnName": "block", "outputTableName": "blocks",
             "layerType": "polygons"},
            {"type": "clusters", "dataRef": "windows", "outputColumnName": "group"},
        ],
        "map": {"layerRefs": [{"dataRef": "blocks", "getFnv": "compute.block"}, {"dataRef": "windows"}]},
    },
}

#: The keys of a map the autark skill gives in the schema's words, each on a line of its own.
MAP_KEYS = ("style", "highlightColor", "invalidValueColor", "showUi", "terrain")
#: The keys of a map's layer the autark skill gives in the schema's words, each on a line of its own.
LAYER_KEYS = ("layerType", "widthBy", "legend", "skippedComps", "pickedComps", "buildingsZeroHeight")
#: The keys of a map's camera autk-grammar 5.4.0 adds.
CAMERA_KEYS = ("center", "motion")
#: The compute passes autk-grammar 5.4.0 adds, by their ``type``.
PASSES = ("windows", "clusters")


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_the_document_check_takes_each_key(name):
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.app.agents.domain import document_validation as dv

    document = DOCUMENTS[name]
    assert contracts.autk_key_problem(document) is None
    assert dv.validate(AUTK, json.dumps(document)) == {"status": dv.STATUS_VALID}


@pytest.mark.parametrize("flavor", ["closed", "strict"])
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_the_reply_schema_keeps_each_key(flavor, name):
    """A reply that writes the keys keeps them, whole, and fits the schema a provider holds it to."""
    import jsonschema

    from utk_curio.backend.app.agents.application import reply_schemas as rs

    reply = rs.autk_reply_schema(rs.FLAVOR_CLOSED if flavor == "closed" else rs.FLAVOR_STRICT)
    document = DOCUMENTS[name]
    encoded, dropped = reply.encode(document)
    assert dropped == []
    jsonschema.Draft202012Validator(reply.schema).validate(encoded)
    assert json.loads(reply.decode(json.dumps(encoded))) == document


def test_the_autark_skill_gives_each_key_in_the_schemas_words():
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.tests._support.prompt_files import prompt_text

    schema = contracts.load_autk_schema()
    map_spec = contracts._definition(schema, "MapSpec")
    layer_spec = contracts._definition(schema, "MapLayerSpec")
    camera = contracts._resolved(schema, map_spec["properties"]["camera"])
    missing = [key for key in MAP_KEYS if key not in map_spec["properties"]]
    missing += [key for key in LAYER_KEYS if key not in layer_spec["properties"]]
    missing += [key for key in CAMERA_KEYS if key not in camera["properties"]]
    assert missing == [], f"the vendored schema has no {missing}"

    lines = prompt_text("autark/SKILL.md").splitlines()
    # Each map key under the map's line, each layer key under its layers', in the schema's words.
    wanted = [f'  - "{key}": {contracts._said(schema, map_spec, key)}' for key in MAP_KEYS]
    wanted += [f'    - "{key}": {contracts._said(schema, layer_spec, key)}' for key in LAYER_KEYS]
    wanted += [f'    - "{key}": {camera["properties"][key]["description"]}' for key in CAMERA_KEYS]
    assert [line for line in wanted if line not in lines] == []
    # Each new pass is a kind of its own, in the schema's words, with the fields it requires.
    passes = contracts._compute_passes(schema)
    for kind in PASSES:
        description, branches = passes[kind]
        assert description and branches, kind
        [line] = [row for row in lines if row.startswith(f'  - "type": "{kind}": ')]
        assert description.split(" Read by the ", 1)[0] in line, line
        for field in branches[0].get("required", []):
            assert f'"{field}"' in line, (kind, field, line)


@pytest.mark.parametrize("document, said", [
    pytest.param(
        {"map": {"layerRefs": [{"dataRef": "input_0", "pickedComps": [0]}]}},
        'map.layerRefs[0]: missing "isPick"',
        id="picked-features-on-a-layer-that-does-not-pick",
    ),
    pytest.param(
        {"map": {"layerRefs": [{"dataRef": "input_0", "isPick": True, "pickedComps": [1.5]}]}},
        "map.layerRefs[0].pickedComps[0]: 1.5 is not a multiple of 1",
        id="a-picked-feature-that-is-no-position",
    ),
    pytest.param(
        {"map": {"layerRefs": [{"dataRef": "input_0", "widthBy": "lanes", "width": 3}]}},
        "map.layerRefs[0]",
        id="widths-by-feature-and-one-width",
    ),
    pytest.param(
        {"map": {"style": {"background": "#000000"}, "layerRefs": [{"dataRef": "input_0"}]}},
        'map.style: missing "surface"',
        id="a-style-without-all-its-colors",
    ),
    pytest.param(
        {"map": {"camera": {"center": [200, 0]}, "layerRefs": [{"dataRef": "input_0"}]}},
        "map.camera.center[0]: 200 is greater than the maximum of 180",
        id="a-center-off-the-globe",
    ),
    pytest.param(
        {"map": {"camera": {"motion": [{"type": "zoom", "amount": 1, "seconds": 0}]}, "layerRefs": [{"dataRef": "input_0"}]}},
        "map.camera.motion[0].seconds: 0 is less than or equal to the minimum of 0",
        id="a-tour-step-that-takes-no-time",
    ),
    pytest.param(
        {"map": {"camera": {"motion": [{"type": "zoom", "amount": 1, "seconds": 1, "pan": 5}]}, "layerRefs": [{"dataRef": "input_0"}]}},
        "map.camera.motion[0]",
        id="a-pan-on-a-zoom-step",
    ),
])
def test_the_document_check_refuses_what_the_grammar_refuses(document, said):
    from utk_curio.backend.app.agents.domain import document_validation as dv

    verdict = dv.validate(AUTK, json.dumps(document))
    assert verdict["status"] == dv.STATUS_INVALID
    assert said in verdict["detail"], verdict["detail"]
