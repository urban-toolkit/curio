"""Playwright E2E: the Discovery Catalog, end to end and without a socket.

**The whole backend runs for real.** The harness points the stack at the
recorded portal corpus (``CURIO_DISCOVERY_FIXTURES``, set in ``fixtures.py``),
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
parsing (``test_discovery/test_providers.py``), the format ladder
(``test_formats.py``), and every row-level state of the download UI
(``src/tests/discovery/DiscoveryResourceRow.test.tsx``).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_discovery_catalog.py -v
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
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

CHICAGO = "source.cityofchicago.data-portal@1"
GEOSAMPA = "source.saopaulo.geosampa@1"

#: The queries the corpus was recorded with. Anything else is a FixtureMissing,
#: which is the intended behaviour - a fixture set answers the questions it was
#: recorded for and says so loudly about the rest.
CHICAGO_QUERY = "crimes"
GEOSAMPA_QUERY = "ciclo"


def _one_node_spec() -> dict:
    """A single node, so the canvas is not empty and ReactFlow reports ready."""
    return {
        "dataflow": {
            "name": "DiscoveryBaseline",
            "task": "",
            "nodes": [
                {
                    "id": "discovery-baseline-node",
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
    has no ``CURIO_DISCOVERY_FIXTURES`` falls back to real HTTP, so every test
    below would quietly become a live call to a municipal portal. That is slow,
    it needs five third parties to be up, and it is exactly what the fixture
    transport exists to avoid, so it should be a visible skip rather than an
    invisible change of meaning.

    The probe is a query nothing recorded: the fixture transport refuses it by
    name (502, "no recorded response for ..."), a real portal answers it 200.
    """
    url = (
        f"{backend_url}/api/discovery/sources/{CHICAGO}/search"
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
        pytest.skip(f"could not probe the discovery transport: {exc}")
    if "no recorded response" not in body:
        pytest.skip(
            "this backend is not serving the recorded portal corpus "
            "(CURIO_DISCOVERY_FIXTURES is unset for it), so these specs would "
            "reach live portals"
        )


def _enter(page, app_frontend, current_server, *, username, project):
    page.emulate_media(reduced_motion="reduce")
    result = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Discovery Catalog User",
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


def _goto_discovery(page, app_frontend, path="/catalog/discovery"):
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
    _enter(page, app_frontend, current_server, username="discoverytab", project="Discovery Tab")

    page.goto(f"{app_frontend.base_url}/catalog/data")
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="Discovery Catalog", exact=True).click()
    page.wait_for_load_state("networkidle")

    expect(
        page.get_by_role("heading", name="Discovery Catalog", exact=True)
    ).to_be_visible(timeout=30000)


def test_the_roster_lists_the_shipped_portals(
    app_frontend: "FrontendPage", current_server: str, page
):
    """Served from disk: this page renders with no portal reachable at all."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="discoveryroster", project="Discovery Roster")
    _goto_discovery(page, app_frontend)

    expect(page.locator(f'[data-discovery-source="{CHICAGO}"]')).to_be_visible(timeout=30000)
    expect(page.locator(f'[data-discovery-source="{GEOSAMPA}"]')).to_be_visible()
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
    _enter(page, app_frontend, current_server, username="discoverydetails", project="Discovery Details")
    page.set_viewport_size({"width": 1000, "height": 800})
    _goto_discovery(page, app_frontend)

    card = page.locator(f'[data-discovery-source="{CHICAGO}"]')
    expect(card).to_be_visible(timeout=30000)
    browse_url = page.url
    card.get_by_role("button", name="View details").click()

    details = page.get_by_role("dialog", name="Source details")
    expect(details).to_be_visible(timeout=15000)
    expect(details.get_by_text("Endpoint", exact=True)).to_be_visible()
    expect(details.get_by_text("Max download", exact=True)).to_be_visible()
    assert page.url == browse_url

    # Its primary action is the drawer's: browse the portal. The modal goes
    # with the page it was opened over.
    details.get_by_role("button", name="Browse datasets").click()
    expect(details).to_have_count(0, timeout=30000)
    page.wait_for_url(f"**/catalog/discovery/{quote(CHICAGO, safe='')}", timeout=30000)
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
    _enter(page, app_frontend, current_server, username="discoverysearch", project="Discovery Search")
    _goto_discovery(page, app_frontend, f"/catalog/discovery?q={GEOSAMPA_QUERY}")

    # Rows, tagged with the portal each came from - which on this page is not
    # implied by anything else.
    expect(page.locator("[data-discovery-resource]").first).to_be_visible(timeout=30000)
    expect(page.get_by_text("GeoSampa").first).to_be_visible()
    # The source CARDS are gone while results are showing.
    expect(page.locator("[data-discovery-source]")).to_have_count(0)


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
    _enter(page, app_frontend, current_server, username="discoverypartial", project="Discovery Partial")
    _goto_discovery(page, app_frontend, f"/catalog/discovery?q={GEOSAMPA_QUERY}")

    expect(page.locator("[data-discovery-resource]").first).to_be_visible(timeout=30000)
    expect(page.get_by_text("did not answer", exact=False)).to_be_visible(timeout=15000)


def test_a_single_portal_page_scopes_the_search(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="discoveryone", project="Discovery One")
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{GEOSAMPA}?q={GEOSAMPA_QUERY}")

    expect(
        page.get_by_role("heading", name="GeoSampa", exact=True)
    ).to_be_visible(timeout=30000)
    expect(page.locator("[data-discovery-resource]").first).to_be_visible(timeout=30000)


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
    _enter(page, app_frontend, current_server, username="discoveryget", project="Discovery Get")
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{CHICAGO}?q={CHICAGO_QUERY}")

    row = page.locator('[data-discovery-resource="ijzp-q8t2"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Download").click()

    # Polled server-side job: the button appears when it finishes.
    view = row.get_by_role("button", name="View dataset")
    expect(view).to_be_visible(timeout=60000)
    discovery_url = page.url

    view.click()
    # It is an ordinary dataset now, in the Data Catalog's own details modal,
    # the one every catalog opens, over the Discovery Catalog page rather than instead of
    # it. The button used to be a link that left for /catalog/data/:id.
    details = page.get_by_role("dialog", name="Dataset details")
    expect(details).to_be_visible(timeout=30000)
    assert page.url == discovery_url
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
    assert page.url == discovery_url
    expect(row).to_be_visible()

    # Opened again, Close does the same.
    row.get_by_role("button", name="View dataset").click()
    expect(details).to_be_visible(timeout=30000)
    details.get_by_role("button", name="Close").click()
    expect(details).to_have_count(0)
    expect(row).to_be_visible()



OSM = "source.osm.openstreetmap@1"

#: The box its parks were recorded for, inside the Village of Golf, Illinois.
GOLF_BOX = ("-87.8", "42.05", "-87.78", "42.06")


def test_openstreetmap_asks_for_an_area_and_lands_autarks_layer(
    app_frontend: "FrontendPage", current_server: str, page
):
    """A service row: Download asks for the area first, then autk-db's own
    loader runs in Node on the backend (against the recorded Overpass answers)
    and the layer lands as a dataset named after its area."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="discoveryosm", project="Discovery OSM")
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{OSM}")

    row = page.locator('[data-discovery-resource="parks"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Download").click()

    dialog = page.get_by_role("dialog", name="Download Parks")
    expect(dialog).to_be_visible(timeout=15000)
    expect(dialog.get_by_text("Area is needed.")).to_be_visible()
    dialog.get_by_role("tab", name="Coordinates").click()
    for label, value in zip(("West", "South", "East", "North"), GOLF_BOX):
        dialog.get_by_label(label, exact=True).fill(value)
    expect(dialog.get_by_text("Area is needed.")).to_have_count(0)
    dialog.get_by_role("button", name="Download").click()
    expect(dialog).to_have_count(0)

    view = row.get_by_role("button", name="View dataset")
    expect(view).to_be_visible(timeout=120000)
    view.click()
    details = page.get_by_role("dialog", name="Dataset details")
    expect(details).to_be_visible(timeout=30000)
    expect(
        details.get_by_role("heading", name="Parks, -87.8000, 42.0500 to -87.7800, 42.0600")
    ).to_be_visible(timeout=30000)
    expect(details.get_by_text("Downloaded from")).to_be_visible(timeout=15000)
    expect(details.get_by_role("link", name="OpenStreetMap")).to_be_visible(timeout=15000)
    expect(details.get_by_text("-87.8000, 42.0500, -87.7800, 42.0600")).to_be_visible(timeout=15000)
    # Each row names its OpenStreetMap element: the schema lists the columns.
    schema = details.get_by_role("region", name="Schema")
    for column in ("osm_type", "osm_id"):
        expect(schema.get_by_text(column, exact=True)).to_be_visible(timeout=15000)


#: The box across Chicago's Loop that the mock Overpass answers cover
#: (``test_discovery/overpass_mock.py``).
LOOP_BOX = (-87.6295, 41.8805, -87.615, 41.8825)


def test_openstreetmap_points_of_interest_land_as_their_geometries(
    app_frontend: "FrontendPage", current_server: str, page
):
    """Points of interest for a box: autk-db's own loader runs in Node, its
    Overpass requests answered by the mock answers, and the points, lines and
    polygons land as one group named after the area."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="discoverypoi", project="Discovery POI")
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{OSM}")

    row = page.locator('[data-discovery-resource="points-of-interest"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Download").click()

    dialog = page.get_by_role("dialog", name="Download Points of interest")
    expect(dialog).to_be_visible(timeout=15000)
    dialog.get_by_role("tab", name="Coordinates").click()
    for label, value in zip(("West", "South", "East", "North"), LOOP_BOX):
        dialog.get_by_label(label, exact=True).fill(str(value))
    expect(dialog.get_by_text("Area is needed.")).to_have_count(0)
    dialog.get_by_role("button", name="Download").click()
    expect(dialog).to_have_count(0)

    view = row.get_by_role("button", name="View dataset")
    expect(view).to_be_visible(timeout=120000)
    view.click()
    details = page.get_by_role("dialog", name="Dataset details")
    expect(details).to_be_visible(timeout=30000)
    # The area as the title shows a box with no place name (``place_label``).
    west, south, east, north = LOOP_BOX
    place = f"{west:.4f}, {south:.4f} to {east:.4f}, {north:.4f}"
    expect(details.get_by_role("heading", name=f"Points of interest, {place} (points)")).to_be_visible(timeout=30000)
    schema = details.get_by_role("region", name="Schema")
    for column in ("osm_type", "osm_id", "amenity"):
        expect(schema.get_by_text(column, exact=True)).to_be_visible(timeout=15000)


def test_a_second_download_offers_the_dataset_instead_of_a_copy(
    app_frontend: "FrontendPage", current_server: str, page
):
    """Idempotency, as a user sees it: the row stops offering Download."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="discoveryagain", project="Discovery Again")
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{CHICAGO}?q={CHICAGO_QUERY}")

    row = page.locator('[data-discovery-resource="ijzp-q8t2"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Download").click()
    expect(row.get_by_role("button", name="View dataset")).to_be_visible(timeout=60000)

    # Reload: the row now knows this account already holds it.
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{CHICAGO}?q={CHICAGO_QUERY}")
    row = page.locator('[data-discovery-resource="ijzp-q8t2"]')
    expect(row).to_be_visible(timeout=30000)
    expect(row.get_by_text("In your Data Catalog")).to_be_visible(timeout=15000)
    expect(row.get_by_role("button", name="Download")).to_have_count(0)


def test_the_canvas_opens_the_discovery_catalog_and_downloads_from_it(
    app_frontend: "FrontendPage", current_server: str, page
):
    """From the canvas's top bar, as the other catalogs are, and without
    leaving the dataflow: a source opened in the drawer is searched and
    downloaded from there, and the dataset lands in the Data Catalog."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="discoverycanvas", project="Discovery Canvas")
    canvas_url = page.url

    page.get_by_role("button", name="Discovery Catalog", exact=True).click()
    drawer = page.locator('[data-curio-discovery-catalog-drawer="true"][aria-hidden="false"]')
    expect(drawer).to_be_visible(timeout=15000)

    card = drawer.locator(f'[data-discovery-source="{CHICAGO}"]')
    expect(card).to_be_visible(timeout=30000)
    card.get_by_role("button", name="Browse datasets").click()
    drawer.get_by_role("searchbox", name="Search City of Chicago Data Portal").fill(CHICAGO_QUERY)

    row = drawer.locator('[data-discovery-resource="ijzp-q8t2"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Download").click()
    expect(row.get_by_role("button", name="View dataset")).to_be_visible(timeout=60000)
    expect(
        page.get_by_text("Downloaded Crimes - 2001 to Present to your Data Catalog.")
    ).to_be_visible(timeout=15000)
    assert page.url == canvas_url, "the drawer left the dataflow"

    # Back to every source, as the page's "All portals" goes back to the page.
    drawer.get_by_role("button", name="All portals").click()
    expect(drawer.locator(f'[data-discovery-source="{CHICAGO}"]')).to_be_visible(timeout=15000)


# ── A dialog over the canvas drawer (issue #921) ───────────────────────────

#: The Chicago row the corpus holds, and the name its dialog is titled with.
CRIMES = "ijzp-q8t2"
CRIMES_NAME = "Crimes - 2001 to Present"

#: How many controls inside an element Tab can stop on.
_TAB_STOPS = """(root) => [...root.querySelectorAll(
  'a[href], button, input, select, textarea, [tabindex]'
)].filter((el) => el.tabIndex >= 0 && !el.disabled).length"""

#: Where the keyboard is: in the dialog on top, in the Discovery Catalog drawer
#: behind it, and whether it is back on the control it started from.
_FOCUS = """() => {
  const dialogs = document.querySelectorAll('[data-curio-modal-shell="true"]');
  const dialog = dialogs[dialogs.length - 1];
  const el = document.activeElement;
  const label = el ? (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 40) : '';
  return {
    inDialog: Boolean(dialog && el && dialog.contains(el)),
    inDrawer: Boolean(el && el.closest('[data-curio-discovery-catalog-drawer="true"]')),
    atStart: el === window.__curioFocusStart,
    what: el ? `${el.tagName.toLowerCase()} "${label}"` : 'nothing',
  };
}"""


def _open_narrow_from_the_canvas_drawer(page, app_frontend, current_server, *, username, project):
    """The steps of issue #921: on the canvas, the Discovery Catalog drawer,
    City of Chicago Data Portal, and a dataset's Narrow… dialog."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username=username, project=project)

    page.get_by_role("button", name="Discovery Catalog", exact=True).click()
    drawer = page.locator('[data-curio-discovery-catalog-drawer="true"][aria-hidden="false"]')
    expect(drawer).to_be_visible(timeout=15000)
    card = drawer.locator(f'[data-discovery-source="{CHICAGO}"]')
    expect(card).to_be_visible(timeout=30000)
    card.get_by_role("button", name="Browse datasets").click()
    drawer.get_by_role("searchbox", name="Search City of Chicago Data Portal").fill(CHICAGO_QUERY)

    row = drawer.locator(f'[data-discovery-resource="{CRIMES}"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Narrow…").click()
    dialog = page.get_by_role("dialog", name=f"Download {CRIMES_NAME}", exact=True)
    expect(dialog).to_be_visible(timeout=15000)
    return drawer, row, dialog


def _press_round_the_dialog(page, dialog, key: str) -> None:
    """Press ``key`` until the focus is back on the control it started from,
    and check that every stop on the way is inside the dialog."""
    stops = dialog.evaluate(_TAB_STOPS)
    page.evaluate("() => { window.__curioFocusStart = document.activeElement; }")
    for press in range(1, 2 * stops + 2):
        page.keyboard.press(key)
        focus = page.evaluate(_FOCUS)
        where = focus["what"] + (" in the Discovery Catalog drawer" if focus["inDrawer"] else "")
        assert focus["inDialog"], f"{key} number {press} took the keyboard out of the dialog, to {where}"
        if focus["atStart"]:
            return
    pytest.fail(f"{2 * stops + 1} presses of {key} never came back round to where they started")


def test_a_dialog_from_the_canvas_drawer_keeps_tab_inside_it(
    app_frontend: "FrontendPage", current_server: str, page
):
    """Tab and Shift+Tab go round the dialog's own controls (issue #921).

    They used to walk out of it into the drawer behind, where another row's
    Narrow… opened a second dialog over the first."""
    _drawer, _row, dialog = _open_narrow_from_the_canvas_drawer(
        page, app_frontend, current_server, username="discoverykeys", project="Discovery Keys",
    )
    dialog.get_by_label("Name in your Data Catalog").click()
    # Backwards first: the step past the dialog's first control was the drawer.
    _press_round_the_dialog(page, dialog, "Shift+Tab")
    _press_round_the_dialog(page, dialog, "Tab")
    expect(dialog).to_be_visible()


def test_a_dialog_from_the_canvas_drawer_takes_typing_and_downloads(
    app_frontend: "FrontendPage", current_server: str, page
):
    """A click in the dialog's field, and on its Download, stays in the dialog
    (issue #921): the field takes typing, the download starts under the name
    typed, and the drawer stays open. Both clicks used to land on the drawer's
    scrim, which closed the dialog and the drawer and did nothing else."""
    drawer, row, dialog = _open_narrow_from_the_canvas_drawer(
        page, app_frontend, current_server, username="discoverytyping", project="Discovery Typing",
    )
    canvas_url = page.url

    name = dialog.get_by_label("Name in your Data Catalog")
    name.click()
    page.keyboard.press("End")
    page.keyboard.type(", from the canvas")
    expect(name).to_have_value(f"{CRIMES_NAME}, from the canvas")
    expect(drawer).to_be_visible()

    dialog.get_by_role("button", name="Download", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(row.get_by_role("button", name="View dataset")).to_be_visible(timeout=60000)
    expect(
        page.get_by_text(f"Downloaded {CRIMES_NAME}, from the canvas to your Data Catalog.")
    ).to_be_visible(timeout=15000)
    expect(drawer).to_be_visible()
    assert page.url == canvas_url, "the download left the dataflow"


# ── Storage sources ────────────────────────────────────────────────────────

EXAMPLE_STORAGE = "source.curio.example-storage@1"

#: Every resource the example storage source declares, by the name its row shows.
EXAMPLE_STORAGE_ROWS = {
    "air-quality": "Air quality readings",
    "stations": "Sensor stations",
    "roads": "Roads",
    "parks": "Parks",
    "orthos": "Drone orthoimagery",
    "dashcam": "Dashcam frames",
    "survey": "Street survey",
    "noise": "Noise recordings",
    "mapillary": "Mapillary street photos",
}


def test_a_storage_source_lists_what_its_manifest_declares(
    app_frontend: "FrontendPage", current_server: str, page
):
    """A folder is scanned on first use and lists one row per declared
    resource, never one per file."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="discoverystore", project="Discovery Store")
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{EXAMPLE_STORAGE}")

    for resource_id, name in EXAMPLE_STORAGE_ROWS.items():
        row = page.locator(f'[data-discovery-resource="{resource_id}"]')
        expect(row).to_be_visible(timeout=30000)
        expect(row.get_by_role("heading", name=name, exact=True)).to_be_visible()
    expect(page.locator("[data-discovery-resource]")).to_have_count(len(EXAMPLE_STORAGE_ROWS))
    expect(page.get_by_role("button", name="Rescan")).to_be_enabled()

    # A collection row draws its first files; the thumbnails are fetched with
    # the token, so they only appear if the authed route answered.
    orthos = page.locator('[data-discovery-resource="orthos"]')
    expect(orthos.get_by_text("Rasters", exact=True)).to_be_visible()
    expect(orthos.locator('img[src^="blob:"]').first).to_be_visible(timeout=30000)


def test_adding_a_collection_narrowed_by_year(
    app_frontend: "FrontendPage", current_server: str, page
):
    """Add opens the dialog, a year is left out, and the collection that lands
    says what it holds and where its files are."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="discoverycoll", project="Discovery Collection")
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{EXAMPLE_STORAGE}")

    row = page.locator('[data-discovery-resource="orthos"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Add to Data Catalog").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_text("year", exact=True)).to_be_visible()
    dialog.get_by_label("2023", exact=True).uncheck()
    dialog.get_by_role("button", name="Add to Data Catalog").click()

    # A narrowed add is a new dataset beside the row, so the row keeps
    # offering the whole resource; the toast is the way to the dataset.
    expect(page.get_by_text("Added Drone orthoimagery to your Data Catalog.")).to_be_visible(
        timeout=60000
    )
    page.get_by_role("button", name="View details").first.click()
    details = page.get_by_role("dialog", name="Dataset details")
    expect(details).to_be_visible(timeout=30000)
    expect(details.get_by_text("Collection", exact=True).first).to_be_visible()
    expect(details.get_by_text("2 rasters")).to_be_visible()
    # The kept year, as Narrowed to says it; Path fields says it too, with the tiles.
    expect(details.get_by_text("year 2024", exact=True)).to_be_visible()
    expect(details.get_by_text("year 2024 · tile tile_0001, tile_0002")).to_be_visible()
    expect(details.get_by_role("link", name="Example storage")).to_be_visible()
    expect(details.locator('img[src^="blob:"]').first).to_be_visible(timeout=30000)


def test_the_files_list_adds_only_the_picked_files(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="discoveryfiles", project="Discovery Files")
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{EXAMPLE_STORAGE}")

    row = page.locator('[data-discovery-resource="survey"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Files").click()
    expect(row.get_by_text("1 to 4 of 4")).to_be_visible(timeout=30000)
    row.get_by_label("Pick survey/2024/IMG_0001.jpg").check()
    row.get_by_role("button", name="Add 1 picked file").click()
    expect(page.get_by_text("to your Data Catalog.")).to_be_visible(timeout=60000)


DIRECT = "source.curio.direct-url@1"

#: A made-up GeoParquet file the corpus serves one byte range at a time
#: (``test_discovery/remote_parquet_fixture.py``), and a box over its first
#: six blocks.
BLOCKS_LINK = "https://portal.test/blocks.parquet"
BLOCKS_BOX = ("-87.64", "41.87", "-87.62", "41.89")


def test_a_geoparquet_link_downloads_only_the_area_asked_for(
    app_frontend: "FrontendPage", current_server: str, page
):
    """#608: a link to a GeoParquet file takes an Area, and the dataset that
    lands holds only the rows inside it, named after the file and the area."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend, current_server, username="discoveryarea", project="Discovery Area")
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{DIRECT}")

    form = page.get_by_role("form", name="Add a file by its link")
    form.get_by_label("Link to a file").fill(BLOCKS_LINK)
    area = form.get_by_role("group", name="Area")
    expect(area).to_be_visible(timeout=15000)
    area.get_by_role("tab", name="Coordinates").click()
    for label, value in zip(("West", "South", "East", "North"), BLOCKS_BOX):
        area.get_by_label(label, exact=True).fill(value)
    save_workflow_test_screenshot(
        page, "discovery-link-area",
        test_name="test_a_geoparquet_link_downloads_only_the_area_asked_for", fit_reactflow=False,
    )
    form.get_by_role("button", name="Download").click()

    row = page.locator(f'[data-discovery-resource="{BLOCKS_LINK}"]')
    view = row.get_by_role("button", name="View dataset")
    expect(view).to_be_visible(timeout=120000)
    view.click()
    details = page.get_by_role("dialog", name="Dataset details")
    expect(details).to_be_visible(timeout=30000)
    expect(
        details.get_by_role("heading", name="blocks.parquet, -87.6400, 41.8700 to -87.6200, 41.8900")
    ).to_be_visible(timeout=30000)
    # Total features, or records: the six blocks inside the box, of twenty.
    total = details.locator("dt", has_text="Total").first.locator("xpath=following-sibling::dd[1]")
    expect(total).to_have_text("6", timeout=30000)
