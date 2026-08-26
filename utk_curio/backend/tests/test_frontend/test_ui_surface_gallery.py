"""Playwright screenshot gallery of every user-facing Curio surface.

Not an assertion suite. This walks the app and drops one PNG per surface into
``.curio/ui-gallery/<label>/`` so a restyle can be reviewed as images instead of
as a diff. Run it once before a change and once after, then compare the two
directories.

Deliberately *not* ``save_workflow_test_screenshot``: that helper's job is
baseline diffing against committed PNGs under
``docs/examples/dataflows/expected_outputs/`` with a 20 % tolerance. Here we want
raw captures with no baseline and no pass/fail, so a review is a review rather
than a threshold.

Opt-in, so it never slows the normal suite::

    CURIO_UI_GALLERY=1 pytest utk_curio/backend/tests/test_frontend/test_ui_surface_gallery.py -v

    # label the run so before/after land in separate directories
    CURIO_UI_GALLERY=1 CURIO_UI_GALLERY_LABEL=before pytest ...

Output goes to ``.curio/ui-gallery/`` (gitignored, same convention as
``tour.py``'s ``.curio/tour``). Override with ``CURIO_UI_GALLERY_OUT``.

A surface that cannot be reached is reported and skipped rather than failing the
run: a missing capture is a gap in the gallery, not a broken app, and a hard
failure two thirds of the way through would throw away the captures already
taken.
"""
from __future__ import annotations

import os
import re
from urllib.parse import quote

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .utils import (
    REPO_ROOT,
    api_json,
    open_tools_palette,
    require_project_page,
    require_user_auth,
    skip_if_shared_view,
    stub_db_login,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("CURIO_UI_GALLERY"),
    reason="Screenshot gallery is opt-in; set CURIO_UI_GALLERY=1.",
)

USERNAME = "uigallery"
USER_NAME = "UI Gallery User"

# One node per category, so a single capture shows all three node colours and
# the projects-list thumbnail has something to draw. The category is what
# `nodeTypeBorderColor` / `NODE_COLORS` key off, so this spec is the fixture
# behind "does a catalog package match its canvas node".
CATEGORY_NODES = [
    ("gallery-data", "curio.builtin/data-transformation", 240, 140),
    ("gallery-computation", "curio.builtin/computation-analysis", 240, 340),
    ("gallery-vis", "curio.builtin/vis-vega", 240, 540),
]


def _gallery_spec(name: str) -> dict:
    return {
        "dataflow": {
            "name": name,
            "task": "",
            "nodes": [
                {
                    "id": node_id,
                    "type": node_type,
                    "x": x,
                    "y": y,
                    "content": "return [1]",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
                for node_id, node_type, x, y in CATEGORY_NODES
            ],
            "edges": [],
        }
    }


def _out_dir() -> str:
    root = os.environ.get("CURIO_UI_GALLERY_OUT") or os.path.join(
        REPO_ROOT, ".curio", "ui-gallery"
    )
    label = os.environ.get("CURIO_UI_GALLERY_LABEL", "current")
    path = os.path.join(root, label)
    os.makedirs(path, exist_ok=True)
    return path


class Gallery:
    """Capture sink. Records what it managed to shoot and what it did not."""

    def __init__(self, page):
        self.page = page
        self.dir = _out_dir()
        self.taken: list[str] = []
        self.missed: list[tuple[str, str]] = []

    def shot(self, label: str, *, full_page: bool = False) -> None:
        path = os.path.join(self.dir, label + ".png")
        # Settle: fonts, icon sprites and the drawer transform all land within a
        # frame or two, and a capture taken mid-transform is the one artifact
        # that makes a review argue with itself.
        self.page.wait_for_timeout(400)
        self.page.screenshot(path=path, full_page=full_page)
        self.taken.append(label)

    def miss(self, label: str, why: str) -> None:
        self.missed.append((label, why.splitlines()[0][:200]))

    def report(self) -> None:
        print("\n[ui-gallery] " + str(len(self.taken)) + " captures -> " + self.dir)
        for label in self.taken:
            print("  ok   " + label)
        for label, why in self.missed:
            print("  MISS " + label + ": " + why)


@pytest.fixture()
def gallery(page):
    sink = Gallery(page)
    yield sink
    sink.report()


@pytest.fixture()
def owner(page, app_frontend, current_server):
    """Authenticated owner with a three-node dataflow, motion disabled.

    ``reduced_motion`` is set before any navigation: both catalog drawers slide
    in via ``transform: translate3d(100%)``, which keeps a full bounding box
    off-screen, so a capture taken on visibility alone can catch the panel
    mid-flight.
    """
    require_user_auth()
    require_project_page()
    page.emulate_media(reduced_motion="reduce")
    page.set_viewport_size({"width": 1440, "height": 900})
    result = stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        username=USERNAME,
        name=USER_NAME,
        project_name="Gallery Dataflow",
        project_spec=_gallery_spec("Gallery Dataflow"),
    )
    # A second project so the list page shows more than one card.
    stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        username=USERNAME,
        name=USER_NAME,
        project_name="Gallery Dataflow Two",
        project_spec=_gallery_spec("Gallery Dataflow Two"),
    )
    return result


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

def test_gallery_pages(gallery, owner, app_frontend, current_server, page):
    base = app_frontend.base_url

    page.goto(base + "/projects")
    expect(page.get_by_role("heading", name="Projects", level=1)).to_be_visible(
        timeout=20000
    )
    # The drawer auto-selects the first card, so this also covers the projects
    # detail drawer.
    gallery.shot("page-projects-grid")

    try:
        page.get_by_role("button", name="List", exact=True).click(timeout=10000)
        gallery.shot("page-projects-list")
    except (PlaywrightTimeoutError, AssertionError) as exc:
        gallery.miss("page-projects-list", str(exc))

    page.goto(base + "/catalog/nodes")
    expect(page.get_by_role("heading", name="Node Catalog", level=1)).to_be_visible(
        timeout=20000
    )
    gallery.shot("page-catalog-nodes")

    page.goto(base + "/catalog/data")
    expect(page.get_by_role("heading", name="Data Catalog", level=1)).to_be_visible(
        timeout=20000
    )
    gallery.shot("page-catalog-data")

    # The third catalog page. Reviewed against the two above: same header
    # band, same rail, same card geometry, or the reskin is not done.
    try:
        page.goto(base + "/catalog/agents")
        expect(page.get_by_role("heading", name="Agent Catalog", level=1)).to_be_visible(
            timeout=20000
        )
        gallery.shot("page-catalog-agents")
    except (PlaywrightTimeoutError, AssertionError) as exc:
        gallery.miss("page-catalog-agents", str(exc))

    # Dataset detail page. Navigated by id read from the catalog API rather
    # than by clicking a card's "View details": the id is what the route keys
    # on, and asking the backend for it keeps the capture working whatever the
    # running catalog happens to contain.
    try:
        catalog = api_json(
            current_server + "/api/datasets/catalog?includeHub=true",
            owner["token"],
        )
        items = catalog.get("items") or catalog.get("datasets") or []
        if not items:
            raise AssertionError("dataset catalog is empty")
        dataset_id = items[0]["id"]
        page.goto(base + "/catalog/data/" + quote(dataset_id, safe=""))
        # No locator assertion here on purpose. Every other capture has a
        # landmark worth waiting on; this route renders its own "Dataset not
        # found." state, and a capture of that is more useful to a reviewer than
        # a MISS line that says only "expected to be visible".
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
        gallery.shot("page-catalog-data-detail")
    except (PlaywrightTimeoutError, AssertionError, KeyError) as exc:
        gallery.miss("page-catalog-data-detail", str(exc))


# --------------------------------------------------------------------------- #
# Canvas, its drawers and its palettes
# --------------------------------------------------------------------------- #

def test_gallery_canvas_and_drawers(gallery, owner, app_frontend, current_server, page):
    project_id = owner["project"]["id"]
    page.goto(app_frontend.base_url + "/dataflow/" + project_id)
    page.wait_for_url("**/dataflow/" + project_id, timeout=20000)
    skip_if_shared_view(page)
    page.locator(".react-flow__node").first.wait_for(state="visible", timeout=30000)
    gallery.shot("canvas-three-node-categories")

    # Put a dataset in the dataflow first. An empty palette captures an empty
    # panel, which says nothing about the format colours that are the whole
    # reason this surface is in the gallery.
    try:
        catalog = api_json(
            current_server + "/api/datasets/catalog?includeHub=true", owner["token"]
        )
        items = catalog.get("items") or catalog.get("datasets") or []
        hub = next((d for d in items if d.get("origin") == "hub"), items[0] if items else None)
        if hub is not None:
            api_json(
                current_server + "/api/dataflows/" + project_id + "/datasets/install",
                owner["token"],
                method="POST",
                payload={"datasetId": hub["id"]},
            )
            page.reload()
            page.locator(".react-flow__node").first.wait_for(
                state="visible", timeout=30000
            )
    except Exception as exc:  # noqa: BLE001 - a bare palette is still worth capturing
        gallery.miss("canvas-palette-datasets:seed", str(exc))

    for kind, label in (
        ("packages", "canvas-palette-packages"),
        ("datasets", "canvas-palette-datasets"),
        ("agents", "canvas-palette-agents"),
    ):
        try:
            open_tools_palette(page, kind)
            gallery.shot(label)
            page.keyboard.press("Escape")
        except (PlaywrightTimeoutError, AssertionError) as exc:
            gallery.miss(label, str(exc))

    for menu_entry, label in (
        ("Node Catalog", "drawer-node-catalog"),
        ("Data Catalog", "drawer-data-catalog"),
        ("Agent Catalog", "drawer-agent-catalog"),
    ):
        try:
            # Fresh load per drawer. Driving both from one page left the Data
            # menu in whichever state the previous iteration toggled it into, so
            # the second entry was never shown and the click sat out its full
            # timeout on an invisible element.
            page.goto(app_frontend.base_url + "/dataflow/" + project_id)
            page.wait_for_url("**/dataflow/" + project_id, timeout=20000)
            page.locator(".react-flow__node").first.wait_for(
                state="visible", timeout=30000
            )
            page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
            page.get_by_role("button", name=menu_entry, exact=True).click(timeout=15000)
            drawer = page.get_by_role("dialog").filter(
                has=page.get_by_role("heading", name=menu_entry, exact=True)
            )
            expect(drawer).to_be_visible(timeout=20000)
            gallery.shot(label)
        except (PlaywrightTimeoutError, AssertionError) as exc:
            gallery.miss(label, str(exc))


# --------------------------------------------------------------------------- #
# Modals
# --------------------------------------------------------------------------- #

def test_gallery_modals(gallery, owner, app_frontend, page):
    project_id = owner["project"]["id"]
    page.goto(app_frontend.base_url + "/dataflow/" + project_id)
    page.wait_for_url("**/dataflow/" + project_id, timeout=20000)
    skip_if_shared_view(page)
    node = page.locator(".react-flow__node").first
    node.wait_for(state="visible", timeout=30000)
    node.scroll_into_view_if_needed()

    # Node settings, then Save as package node. The gear renders only for nodes
    # whose descriptor came from a package, which builtins are.
    try:
        node.get_by_role(
            "button", name=re.compile(r"^Node settings for ")
        ).click(timeout=30000)
        expect(
            page.get_by_role("heading", name="Node settings", level=2)
        ).to_be_visible(timeout=15000)
        gallery.shot("modal-node-settings")

        page.get_by_role("button", name="Save as package node…").click()
        expect(
            page.get_by_role("heading", name="Save as package node", level=2)
        ).to_be_visible(timeout=15000)
        gallery.shot("modal-save-as-package")
        page.get_by_role("button", name="Cancel", exact=True).click()
    except (PlaywrightTimeoutError, AssertionError) as exc:
        gallery.miss("modal-node-settings + modal-save-as-package", str(exc))

    # Dataset detail modal, opened from the Data Catalog browse drawer's CTA.
    try:
        page.goto(app_frontend.base_url + "/catalog/data")
        expect(
            page.get_by_role("heading", name="Data Catalog", level=1)
        ).to_be_visible(timeout=20000)
        page.get_by_role("button", name="View details").first.click(timeout=15000)
        gallery.shot("modal-dataset-detail")
    except (PlaywrightTimeoutError, AssertionError) as exc:
        gallery.miss("modal-dataset-detail", str(exc))

    # AI Settings, which now carries the agent spend limits on its second tab.
    # Captured from the projects page because that is where its header button
    # lives; the canvas reaches the same modal through the drawer's cog.
    try:
        page.goto(app_frontend.base_url + "/projects")
        expect(page.get_by_role("heading", name="Projects", level=1)).to_be_visible(
            timeout=20000
        )
        page.get_by_role("button", name="AI Settings", exact=True).click(timeout=15000)
        expect(
            page.get_by_role("heading", name="AI Settings", level=2)
        ).to_be_visible(timeout=15000)
        gallery.shot("modal-ai-settings")

        page.get_by_role("button", name="Agent limits", exact=True).click(timeout=10000)
        gallery.shot("modal-ai-settings-agent-limits")
    except (PlaywrightTimeoutError, AssertionError) as exc:
        gallery.miss("modal-ai-settings", str(exc))
