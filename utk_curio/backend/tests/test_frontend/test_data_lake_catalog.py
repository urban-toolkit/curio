"""Playwright E2E: the Data Lake Catalog, end to end and without a socket.

**The whole backend runs for real.** The harness points the stack at the
recorded portal corpus (``CURIO_DATALAKE_FIXTURES``, set in ``fixtures.py``),
so a search goes through the route, the service, the provider and the parser,
and a download goes on through the format ladder into the Data Catalog's own
importer - with only the socket replaced.

Stubbing at ``page.route`` instead would have tested the page against a
fiction and left every one of those layers uncovered in e2e, which is exactly
where they meet. What is asserted here is what only a browser can settle: that
the two-mode browse page really swaps, that a partial failure really renders
the rows that arrived, and that a download really ends up as a dataset on the
other catalog's page.

Covered more cheaply elsewhere and deliberately not re-asserted: the provider
parsing (``test_datalakes/test_providers.py``), the format ladder
(``test_formats.py``), and every row-level state of the download UI
(``src/tests/dataLakes/DataLakeResourceRow.test.tsx``).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_data_lake_catalog.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

CHICAGO = "lake.cityofchicago.data-portal@1"
GEOSAMPA = "lake.saopaulo.geosampa@1"

#: The queries the corpus was recorded with. Anything else is a FixtureMissing,
#: which is the intended behaviour - a fixture set answers the questions it was
#: recorded for and says so loudly about the rest.
CHICAGO_QUERY = "crimes"
GEOSAMPA_QUERY = "ciclo"


def _one_node_spec() -> dict:
    """A single node, so the canvas is not empty and ReactFlow reports ready."""
    return {
        "dataflow": {
            "name": "LakeBaseline",
            "task": "",
            "nodes": [
                {
                    "id": "lake-baseline-node",
                    "type": "curio.builtin/computation-analysis",
                    "x": 420,
                    "y": 300,
                    "content": "return [1]",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [],
        }
    }


def _enter(page, app_frontend, current_server, *, username, project):
    page.emulate_media(reduced_motion="reduce")
    result = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Data Lake User",
        username=username,
        project_name=project,
        project_spec=_one_node_spec(),
    )
    require_owner_view(page)
    # Absorb the cold webpack compile on the canvas, the way the rest of this
    # suite does: the fixture's readiness gate is port-based, and
    # webpack-dev-server opens its port before the first build finishes.
    page.wait_for_selector(".react-flow__node", timeout=90000)
    return result


def _goto_lakes(page, app_frontend, path="/catalog/lakes"):
    page.goto(f"{app_frontend.base_url}{path}")
    # `networkidle`, not `domcontentloaded`: the rail, the chips and the cards
    # are all rendered from the roster response, so the markup this reads does
    # not exist until that request has come back.
    page.wait_for_load_state("networkidle")


def test_the_fourth_tab_reaches_the_catalog(
    app_frontend: "FrontendPage", current_server: str, page
):
    """The tab exists beside the other three and navigates."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="laketab", project="Lake Tab")

    page.goto(f"{app_frontend.base_url}/catalog/data")
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="Data Lake Catalog", exact=True).click()
    page.wait_for_load_state("networkidle")

    expect(
        page.get_by_role("heading", name="Data Lake Catalog", exact=True)
    ).to_be_visible(timeout=30000)


def test_the_roster_lists_the_shipped_portals(
    app_frontend: "FrontendPage", current_server: str, page
):
    """Served from disk: this page renders with no portal reachable at all."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="lakeroster", project="Lake Roster")
    _goto_lakes(page, app_frontend)

    expect(page.locator(f'[data-lake-source="{CHICAGO}"]')).to_be_visible(timeout=30000)
    expect(page.locator(f'[data-lake-source="{GEOSAMPA}"]')).to_be_visible()
    # The direct-URL source has nothing to browse, and says so rather than
    # offering a Browse button that would refuse.
    expect(page.get_by_text("Link only").first).to_be_visible()


def test_searching_swaps_the_cards_for_federated_results(
    app_frontend: "FrontendPage", current_server: str, page
):
    """The two modes, and the tagging that makes a fan-out legible.

    Only a browser settles this: the page holds one search box that changes
    what the grid *is*, driven by a debounced abortable hook.
    """
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="lakesearch", project="Lake Search")
    _goto_lakes(page, app_frontend, f"/catalog/lakes?q={GEOSAMPA_QUERY}")

    # Rows, tagged with the portal each came from - which on this page is not
    # implied by anything else.
    expect(page.locator("[data-lake-resource]").first).to_be_visible(timeout=30000)
    expect(page.get_by_text("GeoSampa").first).to_be_visible()
    # The source CARDS are gone while results are showing.
    expect(page.locator("[data-lake-source]")).to_have_count(0)


def test_a_portal_that_did_not_answer_does_not_empty_the_page(
    app_frontend: "FrontendPage", current_server: str, page
):
    """The property this whole design turns on.

    The corpus has a recording for GeoSampa's query and none for Chicago's, so
    that leg fails for real inside the backend. The page must still show what
    arrived, and say which portal did not answer.
    """
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="lakepartial", project="Lake Partial")
    _goto_lakes(page, app_frontend, f"/catalog/lakes?q={GEOSAMPA_QUERY}")

    expect(page.locator("[data-lake-resource]").first).to_be_visible(timeout=30000)
    expect(page.get_by_text("did not answer", exact=False)).to_be_visible(timeout=15000)


def test_a_single_portal_page_scopes_the_search(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="lakeone", project="Lake One")
    _goto_lakes(page, app_frontend, f"/catalog/lakes/{GEOSAMPA}?q={GEOSAMPA_QUERY}")

    expect(
        page.get_by_role("heading", name="GeoSampa", exact=True)
    ).to_be_visible(timeout=30000)
    expect(page.locator("[data-lake-resource]").first).to_be_visible(timeout=30000)


def test_downloading_lands_a_real_dataset_in_the_data_catalog(
    app_frontend: "FrontendPage", current_server: str, page
):
    """The claim only a full-stack test can make.

    Browser → route → provider → download → format ladder → the Data Catalog's
    own importer, and then the OTHER catalog's page showing the result. Every
    layer runs; only the socket is replaced.
    """
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="lakeget", project="Lake Get")
    _goto_lakes(page, app_frontend, f"/catalog/lakes/{CHICAGO}?q={CHICAGO_QUERY}")

    row = page.locator('[data-lake-resource="ijzp-q8t2"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Download").click()

    # Polled server-side job: the link appears when it finishes.
    link = row.get_by_role("link", name="View dataset")
    expect(link).to_be_visible(timeout=60000)

    link.click()
    page.wait_for_load_state("networkidle")
    # It is an ordinary dataset now, on the Data Catalog's own detail page.
    expect(page.get_by_text("Crimes", exact=False).first).to_be_visible(timeout=30000)


def test_a_second_download_offers_the_dataset_instead_of_a_copy(
    app_frontend: "FrontendPage", current_server: str, page
):
    """Idempotency, as a user sees it: the row stops offering Download."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="lakeagain", project="Lake Again")
    _goto_lakes(page, app_frontend, f"/catalog/lakes/{CHICAGO}?q={CHICAGO_QUERY}")

    row = page.locator('[data-lake-resource="ijzp-q8t2"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Download").click()
    expect(row.get_by_role("link", name="View dataset")).to_be_visible(timeout=60000)

    # Reload: the row now knows this account already holds it.
    _goto_lakes(page, app_frontend, f"/catalog/lakes/{CHICAGO}?q={CHICAGO_QUERY}")
    row = page.locator('[data-lake-resource="ijzp-q8t2"]')
    expect(row).to_be_visible(timeout=30000)
    expect(row.get_by_text("In your Data Catalog")).to_be_visible(timeout=15000)
    expect(row.get_by_role("button", name="Download")).to_have_count(0)
