"""The agents' document check refuses the documents an Autark node refuses for
their keys, with the same sentence.

``contracts.autk_key_problem`` runs the "keys" cases of
``contracts/autkGrammar.cases.json``, which
``src/tests/contracts/autkGrammarKeys.test.ts`` runs through the node's own
``autkKeyProblem``: a key autk-grammar 5 renamed is named with its new name,
and a key a node does not run yet is named as one, both with where they are
written. The files are read inside each test, so a checkout without them
fails each test on its own.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CONTRACTS = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "contracts"
)
CASES_FILE = CONTRACTS / "autkGrammar.cases.json"
SHARED_FILE = CONTRACTS / "autkGrammar.json"
AUTK = "curio.builtin/autk-grammar"


def _cases(refused_only: bool = False):
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8")).get("keys", [])
    if refused_only:
        cases = [case for case in cases if case["says"] is not None]
    return [pytest.param(case, id=case["name"]) for case in cases] or [pytest.param(None, id="no-key-cases")]


def _shared() -> dict:
    assert SHARED_FILE.is_file(), f"{SHARED_FILE} is missing"
    return json.loads(SHARED_FILE.read_text(encoding="utf-8"))


def test_the_cases_refuse_every_key_the_file_names_and_run_documents_that_write_none():
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8")).get("keys", [])
    shared = _shared()
    said = [case["says"] or "" for case in cases]
    for rule in shared["renamedKeys"]:
        assert any(f'"{rule["key"]}"' in s and f'"{rule["renamedTo"]}"' in s for s in said), rule
    for rule in shared["notRunYet"]:
        assert any(f"uses {rule['what']}" in s for s in said), rule
    assert len([case for case in cases if case["says"] is None]) > 1


@pytest.mark.parametrize("case", _cases())
def test_a_document_is_told_what_the_node_tells_it_of_its_keys(case):
    assert case is not None, f"{CASES_FILE} holds no key cases"
    from utk_curio.backend.app.agents.domain import contracts

    assert contracts.autk_key_problem(case["spec"]) == case["says"]


@pytest.mark.parametrize("case", _cases(refused_only=True))
def test_the_document_check_refuses_it_with_that_sentence(case):
    assert case is not None, f"{CASES_FILE} holds no key cases"
    from utk_curio.backend.app.agents.domain import document_validation as dv

    verdict = dv.validate(AUTK, json.dumps(case["spec"]))
    assert verdict == {"status": dv.STATUS_INVALID, "detail": case["says"]}


#: A heatmap of the parks near each cell, drawn on a map by its band's
#: aggregate and table, as docs/USAGE.md's Heatmaps section writes it.
HEATMAP_DOCUMENT = {
    "data": [
        {"type": "osm", "pbfFileUrl": "docs/examples/data/lower_mnt.osm.pbf", "outputTableName": "tip",
         "queryArea": {"bbox": [-74.0194, 40.7, -74.0085, 40.7085]},
         "autoLoadLayers": {"layers": ["surface", "parks", "roads"]}},
        {"type": "heatmap", "joinDataRef": "tip_parks", "outputTableName": "park_access",
         "near": {"distance": 200, "useCentroid": False}, "grid": {"rows": 30, "columns": 30},
         "groupBy": [{"column": "*", "aggregateFn": "count"}]},
    ],
    "map": {"layerRefs": [
        {"dataRef": "tip_roads"},
        {"dataRef": "park_access", "getFnv": "count.tip_parks", "title": "Parks within about 150 m", "opacity": 0.6},
    ]},
}


def test_the_document_check_accepts_a_heatmap_drawn_on_a_map():
    from utk_curio.backend.app.agents.domain import document_validation as dv

    assert dv.validate(AUTK, json.dumps(HEATMAP_DOCUMENT)) == {"status": dv.STATUS_VALID}


def test_the_document_check_refuses_a_heatmap_that_collects_its_rows():
    from utk_curio.backend.app.agents.domain import document_validation as dv

    document = json.loads(json.dumps(HEATMAP_DOCUMENT))
    document["data"][1]["groupBy"][0]["aggregateFn"] = "collect"
    verdict = dv.validate(AUTK, json.dumps(document))
    assert verdict["status"] == dv.STATUS_INVALID
    assert verdict["detail"].startswith("data[1].groupBy[0].aggregateFn: 'collect' is not one of"), verdict


def test_the_document_check_takes_a_pass_that_writes_a_new_table_and_its_type():
    """A node runs a GPGPU pass that writes its result as a new table
    (``outputTableName``), drawn as its ``layerType``, and a map of that table,
    so the agents may write one."""
    from utk_curio.backend.app.agents.domain import document_validation as dv

    document = {
        "compute": [{
            "dataRef": "input_0", "attributes": {"v": "properties.value"}, "wgslFunction": "return v * 2.0;",
            "outputColumnName": "twice", "outputTableName": "doubled", "layerType": "points",
        }],
        "map": {"layerRefs": [{"dataRef": "doubled", "getFnv": "twice"}]},
    }
    assert dv.validate(AUTK, json.dumps(document)) == {"status": dv.STATUS_VALID}


def test_the_document_check_takes_a_render_pass():
    """A node runs a render pass, which writes the table a map draws: the
    towers seen from each spot, with the share of its frames each covers and
    the sky. So the agents may write one."""
    from utk_curio.backend.app.agents.domain import document_validation as dv

    document = {
        "compute": [{
            "type": "render", "outputTableName": "sky",
            "layers": [{"id": "towers", "dataRef": "towers", "type": "buildings"}],
            "viewpoints": {"dataRef": "spots", "sampling": {"directions": 4, "pitchDeg": 45}},
            "aggregation": {"type": "classes", "includeBackground": True, "backgroundLayerType": "sky"},
            "tileSize": 64,
        }],
        "map": {"layerRefs": [{"dataRef": "sky", "getFnv": "compute.render.classes.sky"}]},
    }
    assert dv.validate(AUTK, json.dumps(document)) == {"status": dv.STATUS_VALID}


def test_a_document_is_told_only_the_files_sentences():
    from utk_curio.backend.app.agents.domain import contracts

    shared = _shared()
    shapes = [
        re.compile("^" + re.sub(r"\\\{\w+\\\}", ".*", re.escape(template)) + "$")
        for template in (shared["renamedKey"], shared["notRunYetKey"])
    ]
    for case in json.loads(CASES_FILE.read_text(encoding="utf-8")).get("keys", []):
        said = contracts.autk_key_problem(case["spec"])
        if said is not None:
            assert any(shape.match(said) for shape in shapes), said


#: Niterói's summer surface temperature in 2024, a GeoTIFF of the repository,
#: drawn under the city's parks, as docs/USAGE.md's GeoTIFF section writes it.
GEOTIFF_DOCUMENT = {
    "data": [
        {"type": "osm", "pbfFileUrl": "docs/examples/data/niteroi.osm.pbf", "outputTableName": "table_osm",
         "queryArea": {"geocodeArea": "Rio de Janeiro", "areas": ["Niterói"]},
         "autoLoadLayers": {"layers": ["parks"]}},
        {"type": "geotiff", "geotiffFileUrl": "docs/examples/data/niteroi_lst_verao_2001_2024.tif",
         "outputTableName": "lst", "resampleMethod": "nearest"},
    ],
    "map": {"layerRefs": [
        {"dataRef": "lst", "getFnv": "band_24", "colorMapInterpolator": "interpolateYlOrRd",
         "title": "Summer surface temperature, 2024 (°C)"},
        {"dataRef": "table_osm_parks", "color": "#2ca02c"},
    ]},
}


def test_the_document_check_accepts_a_geotiff_drawn_on_a_map():
    from utk_curio.backend.app.agents.domain import document_validation as dv

    assert dv.validate(AUTK, json.dumps(GEOTIFF_DOCUMENT)) == {"status": dv.STATUS_VALID}


def test_the_document_check_refuses_a_geotiff_shrunk_a_way_autk_db_does_not_know():
    from utk_curio.backend.app.agents.domain import document_validation as dv

    document = json.loads(json.dumps(GEOTIFF_DOCUMENT))
    document["data"][1]["resampleMethod"] = "cubic"
    verdict = dv.validate(AUTK, json.dumps(document))
    assert verdict["status"] == dv.STATUS_INVALID
    assert verdict["detail"].startswith("data[1].resampleMethod: 'cubic' is not one of"), verdict
