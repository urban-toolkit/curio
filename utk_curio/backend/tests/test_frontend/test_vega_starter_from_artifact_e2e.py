"""Playwright E2E: an empty Vega-Lite node fed by a real loader gets a map.

The starter-spec ladder (``src/utils/vegaDefaultSpec.ts``) was verified against
inline payloads, but the app never hands a downstream node its data. After a
run, ``data.input`` is an artifact reference (``{path, dataType}``) and the node
fetches ``/get-preview`` to learn the column types. That response is
``parseOutput``'s envelope, ``{dataType, data, schema}``, and the node used to
read the schema off ``data`` (the FeatureCollection, which carries none). The
classifier then fell back to the feature properties, where the active geometry
column never appears, and a GeoDataFrame whose attributes are all strings came
out as the last ladder row: a bar of counts by ``zip``.

A hook test with an inline payload cannot see any of that, so this drives the
real loader, the real preview route and the real node, on the dataset from the
report.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_vega_starter_from_artifact_e2e.py -v
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .utils import (
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_ID = "starter-loader"
VEGA_ID = "starter-vega"

# The loader from the report, verbatim. Every attribute column of this dataset
# is a string and only ``geometry`` is geometry, so the right starter is the
# plain "geometry only" geoshape and the wrong one is a bar of counts by zip.
LOADER_CODE = (
    "import geopandas as gpd\n"
    "\n"
    'dataset_path = curio_dataset_path("data.urbanlab.chicago-boundary")\n'
    "gdf = gpd.read_file(dataset_path)\n"
    "\n"
    "return gdf\n"
)

# The Vega node's spec editor is a GrammarEditor whose Monaco model is named
# ``grammar-<nodeId>.json`` (src/components/editing/GrammarEditor.tsx).
_GRAMMAR_EDITOR_JS = """(nodeId) => {
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    return editors.find((e) => {
        const model = e.getModel();
        const path = model && model.uri && model.uri.path;
        return !!path && path.includes(`grammar-${nodeId}`);
    }) || null;
}"""


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Starter from artifact",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Starter from artifact",
            "nodes": [
                {
                    "id": LOADER_ID,
                    "type": "curio.builtin/data-loading",
                    "x": 0,
                    "y": 0,
                    "content": LOADER_CODE,
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                },
                {
                    "id": VEGA_ID,
                    "type": "curio.builtin/vis-vega",
                    "x": 645,
                    "y": 0,
                    # Empty on purpose: the starter only ever fills an empty buffer.
                    "content": "",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                },
            ],
            "edges": [
                {
                    "id": f"reactflow__edge-{LOADER_ID}out-{VEGA_ID}in",
                    "source": LOADER_ID,
                    "target": VEGA_ID,
                }
            ],
            "datasets": [
                {
                    "datasetId": "data.urbanlab.chicago-boundary",
                    "dirName": "data.urbanlab.chicago-boundary@1",
                    "origin": "imported",
                    "producerNodeId": None,
                    "consumerNodeIds": [],
                    "installedAt": "2026-09-12T00:00:00Z",
                }
            ],
        }
    }


def _grammar_value(page, node_id: str) -> str | None:
    return page.evaluate(
        "(nodeId) => { const ed = (" + _GRAMMAR_EDITOR_JS + ")(nodeId);"
        " return ed ? ed.getValue() : null; }",
        node_id,
    )


def test_an_empty_vega_node_maps_a_geodataframe_artifact(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Starter Spec",
        username="starter_spec_artifact",
        project_name="Starter from artifact",
        project_spec=_spec(),
    )
    require_owner_view(page)
    node_locator(page, LOADER_ID).wait_for(state="visible", timeout=45000)
    node_locator(page, VEGA_ID).wait_for(state="visible", timeout=45000)

    # An edge alone carries no schema, so nothing has been written yet.
    before = _grammar_value(page, VEGA_ID)
    assert before is None or before.strip() in ("", "{}"), (
        f"the Vega node was filled before its input had run: {before!r}"
    )

    # The loader produces an artifact; the app hands the Vega node only its
    # reference, which is the path this test exists to cover.
    run_node_and_wait(page, LOADER_ID, node_type="DATA_LOADING", timeout_ms=120000)

    page.wait_for_function(
        "(nodeId) => { const ed = (" + _GRAMMAR_EDITOR_JS + ")(nodeId);"
        " return !!ed && ed.getValue().includes('\"mark\"'); }",
        arg=VEGA_ID,
        timeout=60000,
    )
    text = _grammar_value(page, VEGA_ID)
    spec = json.loads(text)
    assert spec.get("mark") == "geoshape", (
        f"a GeoDataFrame input should start as a map, got {spec.get('mark')!r}:\n{text}"
    )
    assert spec["encoding"]["shape"] == {"field": "geometry", "type": "geojson"}, spec
    assert "projection" in spec, "the generated geo spec must be self-contained"
    # No colour channel: the frame has no quantitative column to colour by.
    assert "color" not in spec["encoding"], spec["encoding"]
