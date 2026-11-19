"""An Autark document's data section may read the node's input: a heatmap bins,
and a join reads, a table of the input, named as a map names it (``input_0``,
or a layer's own name), which the node loads into the entry's workspace
(``adapters/node/autkDataCompile.ts`` ``sectionInputTables``).

So the agents' document check accepts such a document, and the ``autark``
skill says what the node does with it, in the words the agents read.
Everything is imported inside each test, so a checkout without it fails each
test on its own.
"""
from __future__ import annotations

import json

import pytest

AUTK = "curio.builtin/autk-grammar"
HEATMAP = {"type": "heatmap", "joinDataRef": "input_0", "outputTableName": "density",
           "near": {"distance": 200}, "grid": {"rows": 2, "columns": 3}}
#: The Loop's surface and roads, loaded as example 07 loads them.
ROADS = {"type": "osm", "pbfFileUrl": "docs/examples/data/chicago_loop.osm.pbf", "outputTableName": "loop",
         "queryArea": {"geocodeArea": "Chicago", "areas": ["Loop"]},
         "autoLoadLayers": {"layers": ["surface", "roads"]}}


@pytest.mark.parametrize("document", [
    pytest.param({"data": [HEATMAP]}, id="a-heatmap-of-input-0"),
    pytest.param({"data": [ROADS, {**HEATMAP, "joinDataRef": "table_osm_parks"}],
                  "map": {"layerRefs": [{"dataRef": "loop_roads"}, {"dataRef": "density", "getFnv": "band_1"}]}},
                 id="a-heatmap-of-an-upstream-layer-drawn-on-a-map"),
    pytest.param({"data": [ROADS, {"type": "join", "dataRef": "loop_roads", "joinDataRef": "input_0",
                                   "near": {"distance": 30}, "groupBy": [{"column": "*", "aggregateFn": "count"}]}]},
                 id="a-join-of-input-0-onto-a-loaded-layer"),
])
def test_the_document_check_accepts_a_data_section_that_reads_the_nodes_input(document):
    """Guard: the document check names no table of the input as missing; the
    node finds each among its input's tables when it runs."""
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.app.agents.domain import document_validation as dv

    assert contracts.autk_key_problem(document) is None
    assert dv.validate(AUTK, json.dumps(document)) == {"status": dv.STATUS_VALID}


def test_the_autark_skill_says_a_heatmap_or_a_join_reads_the_nodes_input():
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.tests._support.prompt_files import prompt_text

    schema = contracts.load_autk_schema()
    region = contracts.render_autk_region(schema, "Autark")
    skill = prompt_text("autark/SKILL.md")
    said = (
        'A "heatmap" bins, and a "join" reads, a table the document\'s own "data" loads before it, '
        'or a table of the node\'s input, named as above ("input_0", or a layer\'s own name), '
        'which the node loads into the entry\'s workspace and does not hand on again unless a "join" '
        "wrote its columns onto it;"
    )
    assert said in region
    assert said in skill
    assert "never an input" not in region
