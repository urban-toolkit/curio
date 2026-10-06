"""Playwright E2E: street-level images and models from the Discovery Catalog.

Against the recorded corpus, like ``test_discovery_catalog.py``: the whole
backend runs and only the socket is replaced. Mapillary's answers were
recorded with the auth header stripped; Google Street View's are written from
Google's documented formats, since no Google key is ever used to record; the
Hugging Face model's weights are a synthetic graph of the real one's shape.

What only a browser settles here:

* a key-gated source, with no key, says so and opens API Settings at its row;
* with a key, a service row's dialog takes the recorded answers and the images
  land as one collection in the Data Catalog;
* a model added from Hugging Face lands in the Model Catalog, goes onto example
  10's second Image Segmentation node by a drag from the left rail, and runs;
* a model dropped on the empty canvas becomes an Image Segmentation node that
  names it, as a dataset dropped there becomes a Data Loading node.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_discovery_imagery_models_e2e.py -v
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .test_discovery_catalog import _goto_discovery, _require_recorded_corpus
from .utils import (
    CANVAS_DROP_TARGET,
    REPO_ROOT,
    api_json,
    canvas_nodes,
    node_locator,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

MAPILLARY = "source.mapillary.imagery@1"
STREET_VIEW = "source.google.street-view@1"
HF_MODELS = "source.huggingface.models@1"

#: The box both street-level recordings answer, and what each was asked.
LINCOLN_PARK = ("-87.642", "41.918", "-87.639", "41.92")
MAPILLARY_SIZE, MAPILLARY_MOST = "256", "6"
STREET_VIEW_SPACING, STREET_VIEW_MOST = "60", "20"

#: The ONNX export the Hub search for "segformer" recorded.
ONNX_REPO = "Xenova/segformer-b0-finetuned-ade-512-512"

EXAMPLE = os.path.join(REPO_ROOT, "docs", "examples", "10-street-vision-cv-analysis.json")
PHOTOS = "5988175e-84aa-4964-84de-aba7d55cf122"
ROUTE_TWO = "b7d41c2e-5a8f-4c61-9e0b-2f3a6d9c8e14"
ROUTE_TWO_VIEW = "c3e85a7f-1d2b-4f90-8a6c-5b7e9d0f2a31"
SEGMENTATION = "curio.streetvision/image-segmentation"
DDRNET = "model.curio.ddrnet23-slim"
DDRNET_NAME = "DDRNet23-Slim (street scenes)"


def _spec(example: bool) -> dict:
    if example:
        with open(EXAMPLE, encoding="utf-8") as fh:
            return json.load(fh)
    return {"dataflow": {"name": "Imagery", "task": "", "edges": [], "nodes": [{
        "id": "imagery-node", "type": "curio.builtin/computation-analysis", "x": 420, "y": 300,
        "content": "return [1]", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": []},
    }]}}


def _enter(page, app_frontend, current_server, *, example: bool = False,
           spec: dict | None = None) -> dict:
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Imagery User",
        username=f"imagery_{uuid.uuid4().hex[:10]}",
        project_name="Street-level computer vision" if example else "Imagery",
        project_spec=spec or _spec(example),
    )
    require_owner_view(page)
    _require_recorded_corpus(current_server, session["token"])
    page.wait_for_selector(".react-flow__node", timeout=90000)
    return session


def _save_key(current_server: str, token: str, field: str) -> None:
    # A stand-in: the recorded answers ignore it, and it is never sent anywhere.
    api_json(f"{current_server}/api/auth/me", token, method="PATCH",
             payload={field: "MLY|e2e-stand-in" if "mapillary" in field else "AIzaE2eStandIn"})


def _set_box(dialog) -> None:
    dialog.get_by_role("tab", name="Coordinates").click()
    for label, value in zip(("West", "South", "East", "North"), LINCOLN_PARK):
        # The textbox: Street View's Headings are checkboxes with the same names.
        dialog.get_by_role("textbox", name=label, exact=True).fill(value)
    expect(dialog.get_by_text("Area is needed.")).to_have_count(0)


def _lands_as_a_collection(page, row, *, source_name: str, images: str) -> None:
    view = row.get_by_role("button", name="View dataset")
    expect(view).to_be_visible(timeout=120000)
    view.click()
    details = page.get_by_role("dialog", name="Dataset details")
    expect(details).to_be_visible(timeout=30000)
    expect(details.get_by_text("Collection", exact=True).first).to_be_visible()
    expect(details.get_by_text(images)).to_be_visible()
    # A collection says where it came from in its own section.
    expect(details.get_by_text("Indexed from")).to_be_visible(timeout=15000)
    expect(details.get_by_role("link", name=source_name)).to_be_visible(timeout=15000)
    expect(details.locator('img[src^="blob:"]').first).to_be_visible(timeout=30000)


def test_a_source_without_its_key_opens_api_settings_at_its_row(
    app_frontend: "FrontendPage", current_server: str, page
):
    _enter(page, app_frontend, current_server)
    # Below 1100px the details are a modal only, as the sibling details test
    # reads them; above, the drawer carries the same title.
    page.set_viewport_size({"width": 1000, "height": 800})
    _goto_discovery(page, app_frontend)

    card = page.locator(f'[data-discovery-source="{MAPILLARY}"]')
    expect(card).to_be_visible(timeout=30000)
    expect(card.get_by_text("Token needed")).to_be_visible()
    card.get_by_role("button", name="View details").click()
    details = page.get_by_role("dialog", name="Source details")
    expect(details).to_be_visible(timeout=15000)
    details.get_by_role("button", name="Add yours in API Settings").click()

    # From a catalog page it is the settings page, on the key's form.
    page.wait_for_url(re.compile(r"/settings/keys\?service=mapillary\.token$"), timeout=15000)
    expect(details).to_have_count(0)
    expect(page.get_by_label("Kind")).to_have_value("source:mapillary.token")
    field = page.locator("#api-settings-key-mapillary-token")
    expect(field).to_be_focused(timeout=15000)
    # The row it opened at is the Mapillary one, and says who sends it.
    row = page.locator('[data-key-slot="mapillary.token"]')
    expect(row.get_by_text("Used by Mapillary.")).to_be_visible()


def test_on_the_canvas_a_source_without_its_key_opens_api_settings_over_the_drawer(
    app_frontend: "FrontendPage", current_server: str, page
):
    _enter(page, app_frontend, current_server)
    page.locator("header[data-curio-menu-bar]").get_by_role(
        "button", name="Discovery Catalog", exact=True
    ).click()
    discovery = page.locator('[data-curio-discovery-catalog-drawer="true"]')
    expect(discovery).to_have_attribute("aria-hidden", "false", timeout=20000)
    card = discovery.locator(f'[data-discovery-source="{MAPILLARY}"]')
    expect(card).to_be_visible(timeout=30000)
    card.get_by_role("button", name="View details").click()
    details = page.get_by_role("dialog", name="Source details")
    expect(details).to_be_visible(timeout=15000)
    details.get_by_role("button", name="Add yours in API Settings").click()

    # The dataflow stays: API Settings opens as a drawer over the Discovery one.
    settings = page.locator('[data-curio-settings-drawer="true"]')
    expect(settings).to_have_attribute("aria-hidden", "false", timeout=20000)
    assert urlparse(page.url).path.startswith("/dataflow"), page.url
    expect(details).to_have_count(0)
    expect(settings.locator("#api-settings-key-mapillary-token")).to_be_focused(timeout=15000)

    # One Escape closes API Settings alone; the Discovery drawer is still open.
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, '[data-curio-settings-drawer="true"]')
    expect(discovery).to_have_attribute("aria-hidden", "false")


def test_mapillary_images_for_a_box_land_as_one_collection(
    app_frontend: "FrontendPage", current_server: str, page
):
    session = _enter(page, app_frontend, current_server)
    _save_key(current_server, session["token"], "mapillary_access_token")
    _goto_discovery(page, app_frontend)
    expect(
        page.locator(f'[data-discovery-source="{MAPILLARY}"]').get_by_text("Token set")
    ).to_be_visible(timeout=30000)

    _goto_discovery(page, app_frontend, f"/catalog/discovery/{MAPILLARY}")
    row = page.locator('[data-discovery-resource="images"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Download").click()
    dialog = page.get_by_role("dialog", name="Download Street-level images")
    expect(dialog).to_be_visible(timeout=15000)
    _set_box(dialog)
    dialog.locator('[data-parameter="size"] select').select_option(MAPILLARY_SIZE)
    dialog.locator('[data-parameter="maxImages"] input').fill(MAPILLARY_MOST)
    dialog.get_by_role("button", name="Download").click()
    expect(dialog).to_have_count(0)

    _lands_as_a_collection(page, row, source_name="Mapillary", images="6 images")


def test_street_view_images_for_a_box_land_as_one_collection(
    app_frontend: "FrontendPage", current_server: str, page
):
    session = _enter(page, app_frontend, current_server)
    _save_key(current_server, session["token"], "google_maps_api_key")

    _goto_discovery(page, app_frontend, f"/catalog/discovery/{STREET_VIEW}")
    row = page.locator('[data-discovery-resource="images"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Download").click()
    dialog = page.get_by_role("dialog", name="Download Street View images")
    expect(dialog).to_be_visible(timeout=15000)
    _set_box(dialog)
    dialog.locator('[data-parameter="spacing"] input').fill(STREET_VIEW_SPACING)
    dialog.locator('[data-parameter="maxImages"] input').fill(STREET_VIEW_MOST)
    dialog.get_by_role("button", name="Download").click()
    expect(dialog).to_have_count(0)

    # Five panoramas, four headings each, less the one Google answered with its
    # no-image placeholder.
    _lands_as_a_collection(page, row, source_name="Google Street View", images="19 images")


#: One HTML5 drag from a Models palette row onto a node. The drop is fired on
#: the node's `<id>resizable` box, where its drop listeners sit: an event aimed
#: at an ancestor, such as React Flow's node wrapper, never reaches them.
_DRAG_MODEL_ONTO_NODE_JS = r"""({ modelSelector, nodeId }) => {
    const row = document.querySelector(modelSelector);
    if (!row) return `no model row matching ${modelSelector}`;
    const source = row.querySelector("[draggable]");
    const target = document.getElementById(`${nodeId}resizable`);
    if (!source || !target) return "no drag source or drop target";
    const box = target.getBoundingClientRect();
    const coords = { clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 };
    const dataTransfer = new DataTransfer();
    const fire = (el, type) => el.dispatchEvent(new DragEvent(type, {
        bubbles: true, cancelable: true, dataTransfer, ...coords,
    }));
    fire(source, "dragstart");
    fire(target, "dragover");
    fire(target, "drop");
    fire(source, "dragend");
    return "ok";
}"""


def test_a_hugging_face_model_goes_onto_a_node_and_runs(
    app_frontend: "FrontendPage", current_server: str, page
):
    session = _enter(page, app_frontend, current_server, example=True)
    canvas_url = page.url

    # Add the model where models come from.
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{HF_MODELS}?q=segformer")
    row = page.locator(f'[data-discovery-resource="{ONNX_REPO}"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Add to Model Catalog").click()
    expect(row.get_by_role("button", name="View model")).to_be_visible(timeout=120000)
    # Listed again, the row knows the account holds it.
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{HF_MODELS}?q=segformer")
    expect(row.get_by_text("In your Model Catalog")).to_be_visible(timeout=30000)

    models = api_json(f"{current_server}/api/models/catalog", session["token"]) or {}
    added = [m for m in models.get("items", []) if (m.get("discoverySource") or {}).get("resourceId") == ONNX_REPO]
    assert len(added) == 1, models
    model_id = added[0]["id"]

    # Back on the canvas: drag it from the left rail onto route 2's node.
    page.goto(canvas_url)
    node_locator(page, ROUTE_TWO).locator("[data-curio-node-output]").wait_for(
        state="visible", timeout=300000
    )
    page.get_by_title("Open model palette").click()
    model_row = f'#models-palette [data-model-id="{model_id}"]'
    expect(page.locator(model_row)).to_be_visible(timeout=30000)
    assert page.evaluate(_DRAG_MODEL_ONTO_NODE_JS, {"modelSelector": model_row, "nodeId": ROUTE_TWO}) == "ok"
    page.wait_for_function(
        """([nodeId, needle]) => {
            const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
            const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
            const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
            const match = editorEl && editors.find((e) => editorEl.contains(e.getDomNode()));
            return Boolean(match && match.getValue().includes(needle));
        }""",
        arg=[ROUTE_TWO, f'curio_load_model("{model_id}")'],
        timeout=15000,
    )
    code = read_node_code(page, ROUTE_TWO)
    assert "model.curio.ddrnet23-slim" not in code, code
    assert "classes = None" in code, "the drop rewrites the model and nothing else"

    # And it runs: the photos through the downloaded model, overlays and all.
    # The palette floats over the left of the canvas, where the photos node is.
    page.get_by_title("Close model palette").click()
    run_node_and_wait(page, PHOTOS, node_type="data-loading", timeout_ms=180000)
    text = run_node_and_wait(page, ROUTE_TWO, node_type="image-segmentation", timeout_ms=180000)
    assert "Saved to file" in text, f"the downloaded model did not run: {text!r}"
    cards = node_locator(page, ROUTE_TWO_VIEW).locator(f'[id^="imageBox_content_{ROUTE_TWO_VIEW}_"]')
    cards.first.wait_for(state="visible", timeout=60000)
    assert cards.count() == 40


#: One HTML5 drag from a Models palette row onto an empty point of the canvas.
#: The point is searched for from the right, away from the palette floating
#: over the left of the canvas, and must hit no node: a node takes a model drop
#: itself. Returns what the app wrote to effectAllowed on dragstart and to
#: dropEffect on dragover, since a browser cancels the drop of a drag whose
#: two disagree. A DataTransfer built by script ignores both writes, so they
#: are recorded on the instance instead.
_DRAG_MODEL_ONTO_CANVAS_JS = r"""({ modelSelector, targetSelector }) => {
    const row = document.querySelector(modelSelector);
    if (!row) return { error: `no model row matching ${modelSelector}` };
    const source = row.querySelector("[draggable]");
    const target = document.querySelector(targetSelector);
    if (!source || !target) return { error: "no drag source or drop target" };
    const box = target.getBoundingClientRect();
    let coords = null;
    for (let fy = 0.5; fy < 0.95 && !coords; fy += 0.1) {
        for (let fx = 0.9; fx > 0.3 && !coords; fx -= 0.1) {
            const x = box.x + box.width * fx;
            const y = box.y + box.height * fy;
            const hit = document.elementFromPoint(x, y);
            if (hit && target.contains(hit) && !hit.closest(".react-flow__node")) {
                coords = { clientX: x, clientY: y };
            }
        }
    }
    if (!coords) return { error: "no empty point on the canvas" };
    const dataTransfer = new DataTransfer();
    const written = { effectAllowed: "uninitialized", dropEffect: "none" };
    for (const key of Object.keys(written)) {
        Object.defineProperty(dataTransfer, key, {
            get: () => written[key],
            set: (value) => { written[key] = value; },
        });
    }
    const fire = (el, type) => el.dispatchEvent(new DragEvent(type, {
        bubbles: true, cancelable: true, dataTransfer, ...coords,
    }));
    fire(source, "dragstart");
    fire(target, "dragover");
    const dropEffect = written.dropEffect;
    fire(target, "drop");
    fire(source, "dragend");
    return { effectAllowed: written.effectAllowed, dropEffect };
}"""


def test_a_model_dropped_on_the_canvas_becomes_a_node_that_runs_it(
    app_frontend: "FrontendPage", current_server: str, page
):
    """As a dataset dropped on the canvas becomes a Data Loading node."""
    spec = _spec(example=True)
    # Example 10's packages, and only its photos node, so the canvas has room.
    spec["dataflow"]["nodes"] = [n for n in spec["dataflow"]["nodes"] if n["id"] == PHOTOS]
    spec["dataflow"]["edges"] = []
    _enter(page, app_frontend, current_server, example=True, spec=spec)
    before = {node["id"] for node in canvas_nodes(page)}

    page.get_by_title("Open model palette").click()
    model_row = f'#models-palette [data-model-id="{DDRNET}"]'
    expect(page.locator(model_row)).to_be_visible(timeout=30000)
    dropped = page.evaluate(
        _DRAG_MODEL_ONTO_CANVAS_JS,
        {"modelSelector": model_row, "targetSelector": CANVAS_DROP_TARGET},
    )
    assert "error" not in dropped, dropped
    try:
        page.wait_for_function(
            "(n) => window.__curio_reactFlow.getNodes().length > n", arg=len(before), timeout=15000
        )
    except PlaywrightTimeoutError:
        pass
    added = [node for node in canvas_nodes(page) if node["id"] not in before]
    # Both halves at once: the browser keeps the drop only when the canvas
    # answers a copy drag with copy, and the drop must then make one node.
    assert (dropped, len(added)) == ({"effectAllowed": "copy", "dropEffect": "copy"}, 1), (
        dropped, added,
    )
    assert (added[0]["nodeType"] or "").startswith(SEGMENTATION), added
    expect(page.get_by_text(f"Created an Image Segmentation node for {DDRNET_NAME}.")).to_be_visible(
        timeout=15000
    )
    code = read_node_code(page, added[0]["id"])
    assert f'curio_load_model("{DDRNET}")' in code, code
    assert "curio_segment(" in code, "the node opens with its template's code"
