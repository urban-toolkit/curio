"""The canvas really fetches artifacts as Arrow, not just successfully.

Every other test of this path passes either way. `fetchData` falls back to
JSON on anything that is not a clean Arrow 200, which is the right behaviour
and also means a broken Arrow path looks exactly like a working one: the data
arrives, the table renders, the suite is green, and the 137x is silently gone.

Two real defects in this shape were caught by the stress harness rather than
by e2e, purely because the harness treats a 415 as an error: the backend was
dropping the client's WKB opt-in, and before that the harness was not sending
it. Both would have shipped as "works fine, falls back every time".

So this watches the wire. It asserts the response the browser actually got.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_arrow_artifacts_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    connect_nodes,
    drag_to_canvas,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    set_node_code,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADING_TILE = "#step-loading"
POOL_TILE = "#step-pool"
LOADING_TYPE = "curio.builtin/data-loading"
TAB_STRIP = '[data-testid="data-pool-tabs"]'

ARROW_MIME = "application/vnd.apache.arrow.stream"

POS_UP = (150, 150)
POS_DOWN = (760, 150)

FRAME_CODE = (
    "import pandas as pd\n"
    "df = pd.DataFrame({'idx': list(range(50)), "
    "'label': [f'row_{i:02d}' for i in range(50)]})\n"
    "return df\n"
)

GEOFRAME_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n"
    "gdf = gpd.GeoDataFrame({'idx': list(range(25)), "
    "'geometry': [Point(-87.6 + i / 100, 41.8 + i / 100) for i in range(25)]}, "
    "crs='EPSG:4326')\n"
    "return gdf\n"
)


class ArtifactFetches:
    """Every /get the browser made, and what came back."""

    def __init__(self, page):
        self.responses: list[dict] = []
        page.on("response", self._record)

    def _record(self, response) -> None:
        url = response.url
        # /get-preview is a different route that does not negotiate a format.
        if "/get?" not in url:
            return
        try:
            headers = response.all_headers()
        except Exception:  # noqa: BLE001 - a closed response is not a failure
            headers = {}
        self.responses.append({
            "status": response.status,
            "content_type": headers.get("content-type", ""),
            "kind": headers.get("x-curio-kind", ""),
        })

    @property
    def arrow(self) -> list[dict]:
        return [r for r in self.responses if ARROW_MIME in r["content_type"]]


def _run_and_open_pool(page, code: str):
    loading = drag_to_canvas(page, page.locator(LOADING_TILE), at=POS_UP)
    pool = drag_to_canvas(page, page.locator(POOL_TILE), at=POS_DOWN)
    connect_nodes(page, loading, pool)
    set_node_code(page, loading, code)
    run_node_and_wait(page, loading, node_type=LOADING_TYPE)
    node_locator(page, pool).locator(TAB_STRIP).first.wait_for(
        state="visible", timeout=30000
    )
    return pool


def _enter(page, app_frontend, current_server, username, project):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Arrow User",
        username=username,
        project_name=project,
    )
    require_owner_view(page)


def test_a_dataframe_is_fetched_as_arrow(
    app_frontend: "FrontendPage", current_server: str, page,
):
    fetches = ArtifactFetches(page)
    _enter(page, app_frontend, current_server, "arrow_frame", "Arrow Dataframe")

    _run_and_open_pool(page, FRAME_CODE)

    assert fetches.responses, (
        "the canvas made no /get call at all, so this test cannot tell an "
        "Arrow fetch from a JSON one - the flow it drives no longer exercises "
        "fetchData"
    )
    assert fetches.arrow, (
        "every /get came back as JSON: "
        f"{[r['content_type'] for r in fetches.responses]}. The canvas asked "
        "for Arrow and something refused or dropped the request, so it fell "
        "back silently and the artifact path is paying the JSON cost"
    )
    assert fetches.arrow[0]["kind"] == "dataframe"


def test_a_geodataframe_is_fetched_as_arrow(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The half that needs the WKB opt-in to survive the proxy.

    The sandbox refuses geometry unless the request carries
    X-Curio-Accept-Geometry, and the backend has to forward it. When it did
    not, this was a 415 followed by a silent JSON fallback.
    """
    fetches = ArtifactFetches(page)
    _enter(page, app_frontend, current_server, "arrow_geo", "Arrow Geodataframe")

    _run_and_open_pool(page, GEOFRAME_CODE)

    assert fetches.responses, "the canvas made no /get call at all"
    assert fetches.arrow, (
        "the geodataframe came back as JSON: "
        f"{[(r['status'], r['content_type']) for r in fetches.responses]}. "
        "A 415 here means the WKB opt-in did not reach the sandbox"
    )
    assert fetches.arrow[0]["kind"] == "geodataframe"
