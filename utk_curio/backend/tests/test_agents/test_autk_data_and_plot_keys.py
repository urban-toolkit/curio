"""autk-grammar 5.1.0's data sources and 5.2.0's plot keys reach Curio's agents
as an Autark node runs them.

An Autark node loads ``sql``, ``update`` and ``drop`` sources, an OpenStreetMap
area's ``tagSets`` and ``forceRefresh``, the CRS its extract is in
(``autoLoadLayers.coordinateFormat``), a heatmap's normalized aggregates and a
document's ``workspaces``, through the grammar's own data adapter, and draws a
layer or a plot of OpenStreetMap elements (``osmElements``) and plots in the
colors, domains, ticks, titles and selection their keys set. So the
``autark`` skill names each, the reply schema a provider holds a reply to keeps
each, in both flavors, and the agents' document check takes each, and refuses
what the grammar refuses, in the schema's words: a camera whose eye would sit
on the ground (``"pitch": 90``), and tag sets with an extract. Everything is
imported inside each test, so a checkout without it fails each test on its own.
"""
from __future__ import annotations

import json

import pytest

AUTK = "curio.builtin/autk-grammar"

#: Documents that write the keys, a few to a document.
DOCUMENTS = {
    "sql, update and drop sources": {
        "data": [
            {"type": "csv", "outputTableName": "sales", "csvObject": [["month", "total"], ["Jan", 3]]},
            {"type": "update", "dataRef": "sales", "strategy": "update", "idColumn": "month",
             "jsonObject": [{"month": "Jan", "total": 4}]},
            {"type": "sql", "outputTableName": "totals", "query": "SELECT month, total FROM sales"},
            {"type": "geojson", "outputTableName": "zones", "geojsonFileUrl": "data/zones.geojson"},
            {"type": "sql", "outputTableName": "busy", "layerType": "polygons",
             "query": "SELECT properties->>'zone' AS zone, geometry FROM zones"},
            {"type": "drop", "dataRef": "sales"},
        ],
        "plot": {"dataRef": "totals", "mark": "bar", "axis": ["month", "total"]},
    },
    "workspaces": {
        "workspaces": [
            {"coordinateFormat": "EPSG:3857", "precisionGrid": 1},
            {"name": "east", "coordinateFormat": "EPSG:3395", "precisionGrid": 0.01},
        ],
        "data": [{"type": "geojson", "outputTableName": "parcels", "geojsonFileUrl": "data/parcels.geojson"}],
        "map": {"layerRefs": [{"dataRef": "parcels"}]},
    },
    "tag sets read again past the cache, an extract in its CRS, a normalized heatmap": {
        "data": [
            {
                "type": "osm", "outputTableName": "downtown", "forceRefresh": True,
                "queryArea": {"bbox": [-74.0125, 40.705, -74.008, 40.7085]},
                "tagSets": [{"name": "cafes", "type": "points", "tags": [{"key": "amenity", "value": "cafe"}]}],
            },
            {
                "type": "osm", "outputTableName": "tip", "pbfFileUrl": "docs/examples/data/lower_mnt.osm.pbf",
                "queryArea": {"bbox": [-74.0194, 40.7, -74.0085, 40.7085]},
                "autoLoadLayers": {"layers": ["roads"], "coordinateFormat": "EPSG:4326"},
            },
            {
                "type": "heatmap", "outputTableName": "heat", "joinDataRef": "downtown_cafes_points",
                "near": {"distance": 500}, "grid": {"rows": 4, "columns": 4},
                "groupBy": [{"column": "*", "aggregateFn": "count", "normalize": True}],
            },
        ],
        "map": {"layerRefs": [{"dataRef": "tip_roads", "osmElements": True}, {"dataRef": "heat"}]},
    },
    "a plot's colors, domains, ticks, titles and selection": {
        "plot": [
            {
                "id": "heights", "dataRef": "input_0", "mark": "bar", "axis": ["name", "height"], "color": "height",
                "colorMapInterpolator": "interpolateViridis", "colorMapRange": [0, 100],
                "normalization": {"mode": "percentile", "lowerPercentile": 5, "upperPercentile": 95},
                "tickFormats": ["d", ".1f"], "axisLabels": ["Building", "Height (m)"], "selection": [0],
                "markColor": "#2ca02c", "highlightColor": "#d62728",
            },
            {
                "id": "uses", "dataRef": "input_0", "mark": "scatter", "axis": ["area", "height"], "color": "use",
                "categoricalColorMapInterpolator": "schemeSet1", "colorMapDomain": ["home", "shop"],
                "osmElements": True,
            },
        ],
    },
}

#: Each key of autk-grammar 5.1.0 and 5.2.0 a node runs, as the autark skill names it.
NEW_KEYS = (
    "sql", "update", "drop", "query", "strategy", "idColumn",
    "workspaces", "precisionGrid", "tagSets", "forceRefresh", "osmElements", "normalize",
    "colorMapInterpolator", "categoricalColorMapInterpolator", "colorMapRange", "colorMapDomain", "normalization",
    "tickFormats", "axisLabels", "selection", "markColor", "highlightColor",
)


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


def test_the_autark_skill_names_each_key():
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.tests._support.prompt_files import prompt_text

    text = prompt_text("autark/SKILL.md")
    missing = [key for key in NEW_KEYS if f'"{key}"' not in text]
    assert missing == [], text
    # Each new source is a kind of its own, in the schema's words.
    for kind in ("sql", "update", "drop"):
        assert any(line.startswith(f'  - "{kind}": ') for line in text.splitlines()), kind
    # A document's workspaces, then each field the schema gives a workspace's
    # entry, in the schema's words.
    lines = text.splitlines()
    [line] = [row for row in lines if row.startswith('- "workspaces":')]
    at = lines.index(line)
    fields = contracts._definition(contracts.load_autk_schema(), "WorkspaceSpec")["properties"]
    assert {"name", "coordinateFormat", "precisionGrid"} <= set(fields)
    assert lines[at + 1:at + 1 + len(fields)] == [
        f'  - "{name}": {field["description"]}' for name, field in fields.items()
    ], lines[at:at + 1 + len(fields)]


@pytest.mark.parametrize("document, said", [
    pytest.param(
        {"map": {"camera": {"pitch": 90}, "layerRefs": [{"dataRef": "input_0"}]}},
        "map.camera.pitch: 90 is greater than or equal to the maximum of 90",
        id="a-camera-on-the-ground",
    ),
    pytest.param(
        {"data": [{
            "type": "osm", "outputTableName": "tip", "pbfFileUrl": "docs/examples/data/lower_mnt.osm.pbf",
            "queryArea": {"bbox": [-74.0194, 40.7, -74.0085, 40.7085]},
            "tagSets": [{"name": "cafes", "type": "points", "tags": [{"key": "amenity", "value": "cafe"}]}],
        }]},
        "data[0]",
        id="tag-sets-with-an-extract",
    ),
])
def test_the_document_check_refuses_what_the_grammar_refuses(document, said):
    from utk_curio.backend.app.agents.domain import document_validation as dv

    verdict = dv.validate(AUTK, json.dumps(document))
    assert verdict["status"] == dv.STATUS_INVALID
    assert said in verdict["detail"], verdict["detail"]
