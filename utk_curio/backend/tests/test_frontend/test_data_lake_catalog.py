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
the rows that arrived, and that a download really ends up as a dataset in the
other catalog's details.

Covered more cheaply elsewhere and deliberately not re-asserted: the provider
parsing (``test_datalakes/test_providers.py``), the format ladder
(``test_formats.py``), and every row-level state of the download UI
(``src/tests/dataLakes/DataLakeResourceRow.test.tsx``).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_data_lake_catalog.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import urllib.error
import urllib.request
from urllib.parse import quote

import pytest
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


#: A query no recording answers. On the fixture transport this comes back as a
#: FixtureMissing; on real HTTP the portal would answer it perfectly well.
_UNRECORDED_QUERY = "zzz-not-a-recorded-query-zzz"


def _require_recorded_corpus(backend_url: str, token: str) -> None:
    """Skip unless this stack is serving portal responses from the corpus.

    Without it these specs are silently something else: a stack whose backend
    has no ``CURIO_DATALAKE_FIXTURES`` falls back to real HTTP, so every test
    below would quietly become a live call to a municipal portal. That is slow,
    it needs five third parties to be up, and it is exactly what the fixture
    transport exists to avoid, so it should be a visible skip rather than an
    invisible change of meaning.

    The probe is a query nothing recorded: the fixture transport refuses it by
    name (502, "no recorded response for ..."), a real portal answers it 200.
    """
    url = (
        f"{backend_url}/api/datalakes/sources/{CHICAGO}/search"
        f"?q={_UNRECORDED_QUERY}"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # The refusal arrives as a status, so it is read here rather than in
        # the success branch. Anything else is a broken probe, not a verdict.
        body = exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - a probe never fails a run
        pytest.skip(f"could not probe the lake transport: {exc}")
    if "no recorded response" not in body:
        pytest.skip(
            "this backend is not serving the recorded portal corpus "
            "(CURIO_DATALAKE_FIXTURES is unset for it), so these specs would "
            "reach live portals"
        )


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
    _require_recorded_corpus(current_server, result["token"])
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


def test_a_source_shows_its_details_where_the_drawer_cannot(
    app_frontend: "FrontendPage", current_server: str, page
):
    """A source's details open in a modal, as on the other three catalogs.

    Below 1100px the layout hides the drawer column, which was the only place a
    source's endpoint, formats and download cap appeared. The modal is how that
    width reads them, and it does not leave the page.
    """
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="lakedetails", project="Lake Details")
    page.set_viewport_size({"width": 1000, "height": 800})
    _goto_lakes(page, app_frontend)

    card = page.locator(f'[data-lake-source="{CHICAGO}"]')
    expect(card).to_be_visible(timeout=30000)
    browse_url = page.url
    card.get_by_role("button", name="View details").click()

    details = page.get_by_role("dialog", name="Data lake details")
    expect(details).to_be_visible(timeout=15000)
    expect(details.get_by_text("Endpoint", exact=True)).to_be_visible()
    expect(details.get_by_text("Max download", exact=True)).to_be_visible()
    assert page.url == browse_url

    # Its primary action is the drawer's: browse the portal. The modal goes
    # with the page it was opened over.
    details.get_by_role("button", name="Browse datasets").click()
    expect(details).to_have_count(0, timeout=30000)
    page.wait_for_url(f"**/catalog/lakes/{quote(CHICAGO, safe='')}", timeout=30000)
    expect(
        page.get_by_role("heading", name="City of Chicago Data Portal", exact=True)
    ).to_be_visible(timeout=30000)


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
    own importer, and then the OTHER catalog's details showing the result. Every
    layer runs; only the socket is replaced.
    """
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="lakeget", project="Lake Get")
    _goto_lakes(page, app_frontend, f"/catalog/lakes/{CHICAGO}?q={CHICAGO_QUERY}")

    row = page.locator('[data-lake-resource="ijzp-q8t2"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Download").click()

    # Polled server-side job: the button appears when it finishes.
    view = row.get_by_role("button", name="View dataset")
    expect(view).to_be_visible(timeout=60000)
    lake_url = page.url

    view.click()
    # It is an ordinary dataset now, in the Data Catalog's own details modal,
    # the one every catalog opens, over the lake page rather than instead of
    # it. The button used to be a link that left for /catalog/data/:id.
    details = page.get_by_role("dialog", name="Dataset details")
    expect(details).to_be_visible(timeout=30000)
    assert page.url == lake_url
    # Under the name the PORTAL gave it. Asserting the title and not merely
    # "a modal opened" is the point: it arrived named "ijzp-q8t2.csv" after the
    # remote file, because the download never sent the resource title.
    expect(
        details.get_by_role("heading", name="Crimes - 2001 to Present")
    ).to_be_visible(timeout=30000)
    # And it still says where it came from. Its origin is "imported", exactly
    # like a hand-uploaded file, so this block is the only thing in the details
    # that distinguishes the two.
    expect(details.get_by_text("Downloaded from")).to_be_visible(timeout=15000)
    expect(
        details.get_by_role("link", name="City of Chicago Data Portal")
    ).to_be_visible(timeout=15000)

    # The portal link inside the details points at the page already open, so
    # it closes the modal and keeps the search. As a plain link it navigated to
    # the same page again, clearing the results behind a modal left open.
    details.get_by_role("link", name="City of Chicago Data Portal").click()
    expect(details).to_have_count(0)
    assert page.url == lake_url
    expect(row).to_be_visible()

    # Opened again, Close does the same.
    row.get_by_role("button", name="View dataset").click()
    expect(details).to_be_visible(timeout=30000)
    details.get_by_role("button", name="Close").click()
    expect(details).to_have_count(0)
    expect(row).to_be_visible()


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
    expect(row.get_by_role("button", name="View dataset")).to_be_visible(timeout=60000)

    # Reload: the row now knows this account already holds it.
    _goto_lakes(page, app_frontend, f"/catalog/lakes/{CHICAGO}?q={CHICAGO_QUERY}")
    row = page.locator('[data-lake-resource="ijzp-q8t2"]')
    expect(row).to_be_visible(timeout=30000)
    expect(row.get_by_text("In your Data Catalog")).to_be_visible(timeout=15000)
    expect(row.get_by_role("button", name="Download")).to_have_count(0)
