"""Playwright E2E: models dropped from the Model Catalog drawer, saved as packages and removed.

A model is a package of kind ``model`` with one node. Its card in the Model
Catalog drawer drags as the Node Catalog drawer's cards do:

* dropped on the canvas, the card becomes its package's node, whose code names
  the model with ``curio_load_model("<id>")``. A dataflow that has not added
  the package goes through the drawer's Add review first. Each card does it:
  DDRNet23-Slim, Deep Umbra, the SCOUT weather GNN and a model added from
  Hugging Face, and DDRNet's node runs. Cancel on that review makes no node
  and installs nothing;
* the Tools panel's Models dropdown lists the dataflow's models only, as the
  Data Catalog dropdown lists its datasets: none in a dataflow that has added
  none, then the one added in the drawer. Its row drops as the card does, and
  makes the node at once, since the dataflow has the model;
* a node on the canvas that loads a model, saved with **Save as package
  node**, becomes a model package of its own: it shows in the Model Catalog,
  holds a copy of the model's weights, and its node names the new id, so it
  runs once the model it was copied from has left the account;
* Remove from project keeps a model that a node is bound to (the
  ``modelRefs`` a drop onto the node writes), as it keeps a node package whose
  node is on the canvas, and names every dataflow whose nodes only name the
  model in their code, this one and the account's others.

The libraries of these packages are installed at launch (``--with-examples``,
whose dataflows declare the shipped ones), so no Add installs anything new.
``test_package_libraries_offline_e2e.py`` covers the Add that installs a
library, offline.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_model_drops_e2e.py -v
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .test_discovery_catalog import _goto_discovery, _require_recorded_corpus
from .test_model_catalog_e2e import (
    LOCAL_RELIEF,
    LOCAL_RELIEF_FOLDER,
    LOCAL_RELIEF_ID,
    _add_to_project,
    _card,
    _close_drawer,
    _import_into_project,
    _local_relief_archive,
    _open_drawer,
    _tab,
)
from .utils import (
    CANVAS_DROP_TARGET,
    REPO_ROOT,
    _wait_for_reactflow_ready,
    accept_confirm_dialog,
    api_json,
    canvas_node_type,
    canvas_nodes,
    close_tools_palette,
    connect_nodes,
    drag_with_the_mouse_onto_canvas,
    frame_nodes,
    node_locator,
    open_tools_palette,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_dataflow,
    set_canvas_zoom,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

MODEL_DRAWER = '[data-curio-model-catalog-drawer="true"]'
NOTIFICATIONS = '[aria-label="Notifications"]'

#: The shipped model packages, each with its one node.
SHIPPED_CARDS = {
    "ddrnet": ("model.curio.ddrnet23-slim@1", "image-segmentation"),
    "deep-umbra": ("model.scout.deep-umbra@1", "accumulated-shadow"),
    "weather-gnn": ("model.scout.weather-gnn@1", "weather-routing"),
}
#: A model added from the Discovery Catalog's Hugging Face source: the ONNX
#: export the recorded Hub search for "segformer" holds.
HF_MODELS = "source.huggingface.models@1"
ONNX_REPO = "Xenova/segformer-b0-finetuned-ade-512-512"

#: Example 10's photos: a Data Loading node DDRNet's node runs on.
EXAMPLE_10 = Path(REPO_ROOT) / "docs" / "examples" / "10-street-vision-cv-analysis.json"
PHOTOS = "5988175e-84aa-4964-84de-aba7d55cf122"

#: A Python node that runs a model on an 8 by 8 height grid.
NODE = "runs-a-model"
MARKER = "RELIEF_RAN"
SAVE_AS_NEW = "__save_as_new__"
SAVED_PACKAGE_NAME = "Relief from the canvas"
#: Another dataflow of the account, whose node loads Local Relief in code.
OTHER_DATAFLOW = "Relief in code"


def _manifest(dir_name: str) -> dict:
    return json.loads((Path(REPO_ROOT) / "packages" / dir_name / "manifest.json").read_text(encoding="utf-8"))


def _relief_code(model_id: str) -> str:
    return (
        "import numpy as np\n"
        f'model = curio_load_model("{model_id}")\n'
        'relief = model.run({"height": np.arange(64, dtype=np.float32).reshape(1, 1, 8, 8)})[0]\n'
        f'print("{MARKER}", tuple(relief.shape))\n'
        "return float(np.abs(relief).sum())\n"
    )


def _one_node(code: str) -> dict:
    return {"dataflow": {"name": "Model drops", "task": "", "edges": [], "nodes": [{
        "id": NODE, "type": "curio.builtin/computation-analysis", "x": 0, "y": 0,
        "content": code, "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": []},
    }]}}


def _empty() -> dict:
    return {"dataflow": {
        "name": "Model drops", "task": "", "nodes": [], "edges": [], "packages": ["curio.builtin@1"],
    }}


def _photos_only() -> dict:
    """Example 10 with only its photos, and without DDRNet's package."""
    spec = json.loads(EXAMPLE_10.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    dataflow["nodes"] = [node for node in dataflow["nodes"] if node["id"] == PHOTOS]
    dataflow["edges"] = []
    dataflow["packages"] = [d for d in dataflow.get("packages", []) if not d.startswith("model.")]
    dataflow["name"] = "Model drops"
    return spec


def _enter(page, app_frontend, current_server, *, spec: dict) -> dict:
    require_project_page()
    require_user_auth()
    # Before navigating: the drawers slide in through useSlideDrawerPresentation,
    # which reads prefers-reduced-motion.
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Model Drops User",
        username=f"model_drops_{uuid.uuid4().hex[:10]}",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    _wait_for_canvas(page)
    return session


def _wait_for_canvas(page) -> None:
    page.locator(CANVAS_DROP_TARGET).wait_for(state="visible", timeout=45000)
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)


def _node_ids(page) -> set[str]:
    return {node["id"] for node in canvas_nodes(page)}


def _new_node(page, before: set[str], *, timeout: float = 30000) -> str:
    page.wait_for_function(
        "(n) => window.__curio_reactFlow.getNodes().length > n", arg=len(before), timeout=timeout,
    )
    created = sorted(_node_ids(page) - before)
    assert len(created) == 1, f"expected one new node, got {created}"
    return created[0]


#: A point of the canvas left of the open drawer, under its scrim, where a new
#: node (as big as the nodes already there) lies clear of them: so the two
#: nodes' circles can be wired. Clear of the tool rail on the left (which ends
#: 170 px from the canvas's left edge), of the drawer and of the toasts in the
#: bottom right.
_FREE_POINT_JS = r"""([pane, drawer]) => {
    const box = document.querySelector(pane).getBoundingClientRect();
    const panel = document.querySelector(drawer).getBoundingClientRect();
    const nodes = [...document.querySelectorAll(".react-flow__node")].map((n) => n.getBoundingClientRect());
    const w = Math.max(0, ...nodes.map((r) => r.width));
    const h = Math.max(0, ...nodes.map((r) => r.height));
    const right = Math.min(box.right, panel.left) - 60;
    for (let y = box.top + 140; y < box.bottom - 160; y += 20) {
        for (let x = box.left + 200; x + w < right; x += 20) {
            const clear = nodes.every(
                (r) => x + w < r.left - 30 || x > r.right + 30 || y + h < r.top - 30 || y > r.bottom + 30,
            );
            if (clear) return [x - box.left, y - box.top];
        }
    }
    return null;
}"""


def _free_point(page) -> tuple[float, float]:
    point = page.evaluate(_FREE_POINT_JS, [CANVAS_DROP_TARGET, f'{MODEL_DRAWER} [role="dialog"]'])
    assert point, "no empty point of the canvas left of the drawer"
    return tuple(point)


def _add_review(page, name: str):
    return page.get_by_role("dialog").filter(has=page.get_by_role("heading", name=f'Add "{name}"', exact=True))


def _drop_card_and_add(page, drawer, dir_name: str, name: str) -> str:
    """Drop *dir_name*'s card on the canvas, confirm the Add review it opens,
    and return the node the drop made."""
    card = _card(drawer, dir_name)
    expect(card).to_have_count(1, timeout=30000)
    expect(card).to_have_attribute("draggable", "true")
    before = _node_ids(page)

    drop = drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=_free_point(page))

    assert drop["onCanvas"], f"the card's drop landed on {drop['droppedOn']}, not on the canvas"
    review = _add_review(page, name)
    expect(review).to_be_visible(timeout=30000)
    assert _node_ids(page) == before, "the drop made a node before the Add review was confirmed"
    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url and r.url.endswith("/install") and r.request.method == "POST",
        timeout=180000,
    ) as added:
        review.get_by_role("button", name="Add to project", exact=True).click()
    assert added.value.status == 201, f"{added.value.status}: {added.value.text()[:600]}"
    expect(review).to_have_count(0, timeout=30000)
    return _new_node(page, before)


def _wait_for_code_naming(page, node_id: str, model_id: str) -> str:
    """The node's code once it names *model_id* (a fresh node's code arrives
    with its template's starter)."""
    needle = f'curio_load_model("{model_id}")'
    page.wait_for_function(
        """([id, needle]) => {
            const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
            return !!node && typeof node.data.code === "string" && node.data.code.includes(needle);
        }""",
        arg=[node_id, needle],
        timeout=30000,
    )
    code = read_node_code(page, node_id)
    assert needle in code, code
    return code


def _add_the_hugging_face_model(page, app_frontend, current_server: str, token: str) -> tuple[str, str]:
    """Add the recorded Hugging Face model from the Discovery Catalog; its
    package's dirName and name."""
    _require_recorded_corpus(current_server, token)
    _goto_discovery(page, app_frontend, f"/catalog/discovery/{HF_MODELS}?q=segformer")
    row = page.locator(f'[data-discovery-resource="{ONNX_REPO}"]')
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Add to Model Catalog").click()
    expect(row.get_by_role("button", name="View model")).to_be_visible(timeout=120000)
    models = api_json(f"{current_server}/api/packages?kind=model", token) or {}
    added = [
        m for m in models.get("packages", [])
        if ((m.get("model") or {}).get("discoverySource") or {}).get("resourceId") == ONNX_REPO
    ]
    assert len(added) == 1, models
    return added[0]["dirName"], added[0]["name"]


@pytest.mark.parametrize("card", ["ddrnet", "deep-umbra", "weather-gnn", "hugging-face"])
def test_a_model_card_dropped_on_the_canvas_adds_its_package_and_becomes_its_node(
    app_frontend: "FrontendPage", current_server: str, page, card: str,
):
    spec = _photos_only() if card == "ddrnet" else _empty()
    session = _enter(page, app_frontend, current_server, spec=spec)
    if card == "hugging-face":
        canvas_url = page.url
        dir_name, name = _add_the_hugging_face_model(page, app_frontend, current_server, session["token"])
        template = "image-segmentation"
        page.goto(canvas_url)
        _wait_for_canvas(page)
    else:
        dir_name, template = SHIPPED_CARDS[card]
        name = _manifest(dir_name)["name"]
    model_id = dir_name.split("@")[0]
    if card == "ddrnet":
        # Room beside the photos for DDRNet's node, so the two can be wired.
        set_canvas_zoom(page, 0.5)

    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    node = _drop_card_and_add(page, drawer, dir_name, name)

    assert (canvas_node_type(page, node) or "").startswith(f"{model_id}/{template}"), canvas_node_type(page, node)
    _wait_for_code_naming(page, node, model_id)
    expect(page.locator(NOTIFICATIONS).get_by_text(re.compile(rf"node for {re.escape(name)}\."))).to_be_visible(
        timeout=15000
    )
    if card != "ddrnet":
        return

    # DDRNet's node runs on the photos.
    _close_drawer(page, MODEL_DRAWER)
    frame_nodes(page, [PHOTOS, node])
    connect_nodes(page, PHOTOS, node)
    run_node_and_wait(page, PHOTOS, node_type="data-loading", timeout_ms=180000)
    text = run_node_and_wait(page, node, node_type=template, timeout_ms=180000)
    assert "Saved to file" in text, f"DDRNet's node did not run: {text!r}"


def _right_of_the_palette(page) -> tuple[float, float]:
    """A point of the empty canvas right of the open Models dropdown, in the
    canvas's coordinates, clear of the toasts in the bottom right."""
    pane = page.locator(CANVAS_DROP_TARGET).bounding_box()
    panel = page.locator('#models-palette [role="region"]').bounding_box()
    assert pane and panel, "the canvas or the Models dropdown has no layout box"
    x = max(panel["x"] + panel["width"] + 120, pane["x"] + pane["width"] * 0.5)
    return x - pane["x"], pane["height"] * 0.4


def _record_installs(page) -> list[str]:
    """The URLs of the dataflow installs the page asks for, from now on."""
    installs: list[str] = []
    page.on(
        "request",
        lambda r: installs.append(r.url)
        if r.method == "POST" and "/api/packages/projects/" in r.url and r.url.endswith("/install")
        else None,
    )
    return installs


def _models_trigger(page):
    """The rail's Models card: its count, then its label."""
    return page.locator('#models-palette button[aria-haspopup="true"]')


def test_the_models_dropdown_lists_only_the_dataflows_models_and_a_row_drops_as_its_node(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The Models dropdown lists this dataflow's models, as the Data Catalog
    dropdown lists its datasets. A dataflow that has added none shows the
    empty state and the way into the drawer. The drawer's own card, dropped
    on the canvas while the dataflow lacks the model, opens its Add review,
    and Cancel makes no node and installs nothing. Once Deep Umbra is added in
    the drawer, the dropdown lists exactly Deep Umbra, and its row dropped on
    the canvas makes its node at once, with no Add review and no install."""
    dir_name, template = SHIPPED_CARDS["deep-umbra"]
    name = _manifest(dir_name)["name"]
    model_id = dir_name.split("@")[0]
    _enter(page, app_frontend, current_server, spec=_empty())

    panel = open_tools_palette(page, "models")
    # Shown once the listing is in. Every model ships in the catalog, and
    # this dataflow has added none of them.
    expect(panel.get_by_text("Add or import a model to use it here.", exact=True)).to_be_visible(timeout=30000)
    expect(panel.locator("[data-model-id]")).to_have_count(0)
    expect(panel.locator("summary")).to_have_text(re.compile(r"^\s*Models in project\s*0\s*$"))
    expect(panel.get_by_text("No models added yet.", exact=True)).to_be_visible()
    expect(_models_trigger(page)).to_have_text(re.compile(r"^\s*0\s*Model Catalog\s*$"))
    expect(panel.get_by_role("button", name="Browse Model Catalog +", exact=True)).to_be_visible()

    # The drawer's own card dropped on the canvas: its Add review, and Cancel
    # makes no node and installs nothing. The open dropdown floats over the
    # left of the canvas, where the drop goes, so it is closed first.
    close_tools_palette(page, "models")
    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    card = _card(drawer, dir_name)
    expect(card).to_have_count(1, timeout=30000)
    expect(card).to_have_attribute("draggable", "true")
    installs = _record_installs(page)
    before = _node_ids(page)
    drop = drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=_free_point(page))
    assert drop["onCanvas"], f"the card's drop landed on {drop['droppedOn']}, not on the canvas"
    review = _add_review(page, name)
    expect(review).to_be_visible(timeout=30000)
    review.get_by_role("button", name="Cancel", exact=True).click()
    expect(review).to_have_count(0, timeout=10000)
    assert (_node_ids(page), installs) == (before, []), "a cancelled Add made a node or installed"

    # Added in the drawer, with no node for the cancelled drop: the dropdown
    # lists it, and nothing else.
    _add_to_project(page, card, name)
    assert _node_ids(page) == before, "the Add made a node for the cancelled drop"
    _close_drawer(page, MODEL_DRAWER)
    panel = open_tools_palette(page, "models")
    expect(panel.locator(f'[data-model-id="{model_id}"]')).to_have_count(1, timeout=30000)
    expect(panel.locator("[data-model-id]")).to_have_count(1)
    expect(panel.locator("summary")).to_have_text(re.compile(r"^\s*Models in project\s*1\s*$"))
    expect(panel.get_by_text("Add or import a model to use it here.", exact=True)).to_have_count(0)
    expect(_models_trigger(page)).to_have_text(re.compile(r"^\s*1\s*Model Catalog\s*$"))

    # Its row dropped on the canvas: the node, with no Add asked for.
    installs = _record_installs(page)
    before = _node_ids(page)
    grip = panel.locator(f'[data-model-id="{model_id}"] [draggable="true"]')
    drop = drag_with_the_mouse_onto_canvas(page, grip, at=_right_of_the_palette(page))
    assert drop["onCanvas"], f"the row's drop landed on {drop['droppedOn']}, not on the canvas"
    node = _new_node(page, before)
    assert (canvas_node_type(page, node) or "").startswith(f"{model_id}/{template}"), canvas_node_type(page, node)
    _wait_for_code_naming(page, node, model_id)
    expect(page.locator(NOTIFICATIONS).get_by_text(re.compile(rf"node for {re.escape(name)}\."))).to_be_visible(
        timeout=15000
    )
    assert (_add_review(page, name).count(), page.locator(MODEL_DRAWER).count(), installs) == (0, 0, []), (
        "the row's drop asked for an Add"
    )


def test_a_node_that_loads_a_model_saved_as_a_package_is_a_model_package_that_runs_on_its_own_weights(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path,
):
    session = _enter(page, app_frontend, current_server, spec=_one_node(_relief_code(LOCAL_RELIEF_ID)))
    token = session["token"]
    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    _import_into_project(page, drawer, _local_relief_archive(tmp_path / "local-relief.curio.zip"))
    _close_drawer(page, MODEL_DRAWER)

    node = node_locator(page, NODE)
    node.wait_for(state="visible", timeout=60000)
    _wait_for_reactflow_ready(page)
    node.scroll_into_view_if_needed()
    node.get_by_role("button", name=re.compile(r"^Node settings for ")).click()
    page.get_by_role("button", name="Save as package node…").click()
    modal = page.get_by_role("heading", name="Save as package node", level=2).locator("xpath=..")
    expect(modal).to_be_visible(timeout=15000)
    modal.locator("#save-as-package-target").select_option(SAVE_AS_NEW)
    modal.locator("#save-as-new-package-name").fill(SAVED_PACKAGE_NAME)
    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/factory/install") and r.request.method == "POST",
        timeout=180000,
    ) as saved:
        modal.get_by_role("button", name="Save", exact=True).click()
    response = saved.value
    assert response.status == 201, f"{response.status}: {response.text()[:600]}"

    # A model package: the model block of the model the node loads.
    package = response.json()["package"]
    source = json.loads((LOCAL_RELIEF_FOLDER / "manifest.json").read_text(encoding="utf-8"))["model"]
    copied = package.get("model") or {}
    assert (package.get("kind"), copied.get("entry"), copied.get("type"), copied.get("sizeBytes")) == (
        "model", source["entry"], source["type"], source["sizeBytes"],
    ), package
    new_id, new_dir = package["packageId"], package["dirName"]
    assert new_id != LOCAL_RELIEF_ID

    # The node on the canvas is the new package's node, and names the new id.
    _wait_for_code_naming(page, NODE, new_id)
    assert (canvas_node_type(page, NODE) or "").startswith(f"{new_id}/"), canvas_node_type(page, NODE)

    # The Model Catalog lists it in this dataflow.
    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    _tab(drawer, "In project").click()
    expect(_card(drawer, new_dir)).to_have_count(1, timeout=20000)
    _close_drawer(page, MODEL_DRAWER)

    # Its own weights: the model it was copied from leaves the account, and the
    # node still runs.
    api_json(f"{current_server}/api/packages/{LOCAL_RELIEF}", token, method="DELETE")
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", token)["packages"]]
    assert (LOCAL_RELIEF in store, new_dir in store) == (False, True), store
    text = run_node_and_wait(page, NODE, timeout_ms=180000)
    assert f"{MARKER} (1, 1, 8, 8)" in text, text


def test_remove_keeps_a_model_a_node_is_bound_to_and_warns_about_a_call_in_code(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path,
):
    name = "Local Relief (example)"
    session = _enter(page, app_frontend, current_server, spec=_one_node(_relief_code(LOCAL_RELIEF_ID)))
    project_id = session["project"]["id"]
    # Another dataflow of the account loads the model in its code alone.
    other = _one_node(_relief_code(LOCAL_RELIEF_ID))
    other["dataflow"]["name"] = OTHER_DATAFLOW
    created = api_json(
        f"{current_server}/api/projects", session["token"], method="POST",
        payload={"name": OTHER_DATAFLOW, "spec": other, "outputs": []},
    )
    assert created and created.get("id"), created
    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    _import_into_project(page, drawer, _local_relief_archive(tmp_path / "local-relief.curio.zip"))
    _tab(drawer, "In project").click()
    card = _card(drawer, LOCAL_RELIEF)
    expect(card).to_have_count(1, timeout=20000)

    # The node names the model in its code only, and so does the other
    # dataflow's: Remove names both dataflows, says that code stays behind,
    # and the person cancels.
    card.get_by_role("button", name="Remove from project", exact=True).click()
    confirm = page.get_by_role("dialog", name=f"Remove {name}?")
    expect(confirm).to_be_visible(timeout=10000)
    expect(confirm).to_contain_text(
        f"Nodes in Model drops, {OTHER_DATAFLOW} load this model in code. "
        "That code is left as it is, and fails once the model leaves your account."
    )
    confirm.get_by_role("button", name="Cancel", exact=True).click()
    expect(confirm).to_have_count(0, timeout=10000)

    # Dropped onto the node, the model binds it.
    box = node_locator(page, NODE).bounding_box()
    pane = page.locator(CANVAS_DROP_TARGET).bounding_box()
    panel = drawer.bounding_box()
    assert box and pane and panel, "the node, the canvas or the drawer has no layout box"
    at = (box["x"] + 40, box["y"] + box["height"] / 2)
    assert at[0] < panel["x"] - 20, f"the node at {box} is under the drawer at {panel}"
    drag_with_the_mouse_onto_canvas(page, card.locator("h3"), at=(at[0] - pane["x"], at[1] - pane["y"]))
    expect(page.locator(NOTIFICATIONS).get_by_text(f"Model set to {name}")).to_be_visible(timeout=10000)

    _close_drawer(page, MODEL_DRAWER)
    save_dataflow(page)
    spec = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]
    (saved,) = [n for n in spec["dataflow"]["nodes"] if n["id"] == NODE]
    assert saved["metadata"].get("modelRefs") == [{"id": LOCAL_RELIEF_ID, "name": name}], saved["metadata"]

    # Remove is refused while the node is bound to the model.
    drawer = _open_drawer(page, "Model Catalog", MODEL_DRAWER)
    _tab(drawer, "In project").click()
    card = _card(drawer, LOCAL_RELIEF)
    card.get_by_role("button", name="Remove from project", exact=True).click()
    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url and r.request.method == "DELETE", timeout=30000,
    ) as removed:
        accept_confirm_dialog(page, title=f"Remove {name}?", button="Remove")
    assert removed.value.status == 409, f"{removed.value.status}: {removed.value.text()[:600]}"
    expect(page.get_by_text(f"1 node on this canvas uses {LOCAL_RELIEF}").first).to_be_visible(timeout=10000)
    expect(card).to_have_count(1)
