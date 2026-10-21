"""Playwright E2E: the Map Edits node (its type id is still
``curio.builtin/edit-features``).

Two scenarios count the buildings of one layer: "Every building", whose Map
Edits node has no edits, and "One removed", a copy of it. The layer holds
three building parts, two of them one building's, so they share its
``building_id``, as Autark's buildings do. The node draws the layer on a map,
on its left, and shows the feature a double-click selects on its right, as the
JSON of its properties. Its code is its only state.

1. A building double-clicked on One removed's map: the panel shows the
   properties the map drew for it, without its geometry, and how many
   features an edit applies to. Remove takes out every part of the building:
   the node's code holds it, the panel lists it under Removed, the map draws
   the layer without it, and the dataflow reads Unsaved. Playing the count
   below runs the node again, and the count drops; the other scenario's does
   not. Saved and opened again, the code, the panel and the Remove's entry in
   the node's Provenance drawer come back.
2. The map zoomed in, a building selected, its height set in the field:
   Apply writes the height into the node's code, the map draws again and
   keeps the view, and a run hands on the new height.
3. Two Applies and a Remove on one building, before the node ever runs: the
   node's Provenance drawer lists the three as entries, each named by what it
   changed. The first entry's code put back (it opens the Code tab) leaves
   only the first Apply's edit, on the map and in the panel, and adds no
   entry.

It runs an Autark map, which needs WebGPU: without an adapter it skips, unless
``CURIO_REQUIRE_HARDWARE_WEBGPU=1`` (CI's GPU job), where it fails.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_map_edits_e2e.py -v
"""

from __future__ import annotations

import base64
import json
import re
import time
from io import BytesIO
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_scenario_drop_e2e import _saved_spec
from .test_widget_tags_e2e import _open_tab
from .utils import (
    _OUTPUT_ARTIFACT_JS,
    INTERACTION_SHOWN_TIMEOUT_MS,
    _compare_images,
    assert_in_view,
    autark_map_framing,
    dismiss_toasts,
    drawing_kept,
    frame_nodes,
    keep_drawing,
    load_artifact_as_dict,
    mark_point,
    node_locator,
    play_node,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    run_all_and_wait,
    run_node_and_wait,
    save_dataflow,
    save_dataflow_and_settle_header,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
    wait_for_node_settled,
    wait_for_run_guard_released,
)
from .utils.node_drawings import _AUTK_MAP_PIXELS_IN_FRAME_JS
from .walkthroughs.steps import PROVENANCE_DRAWER, PROVENANCE_PANEL, await_drawer_at_rest

if TYPE_CHECKING:
    from .utils import FrontendPage

EDIT_TYPE = "curio.builtin/edit-features"
LOAD = "me-load"
EDIT, EDIT_2 = "me-edit", "me-edit-2"
COUNT, COUNT_2 = "me-count", "me-count-2"
EVERY, LESS = "s-every", "s-less"

# Building 1 in two parts, side by side on the left; building 2, one part as
# wide as both, on the right. Near Back Bay, in degrees, about 4 km across, so
# they fill much of the map an Autark node draws a city in.
LOAD_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "x, y, w, h = -71.1000, 42.3400, 0.0120, 0.0250\n"
    "return gpd.GeoDataFrame(\n"
    '    {"building_id": [1, 1, 2], "height": [20.0, 35.0, 50.0]},\n'
    "    geometry=[box(x, y, x + w, y + h), box(x + w, y, x + 2 * w, y + h), box(x + 2 * w, y, x + 4 * w, y + h)],\n"
    "    crs=4326,\n"
    ")\n"
)
#: Each building's parts and their heights.
PARTS = {1: 2, 2: 1}
HEIGHTS = {1: [20.0, 35.0], 2: [50.0]}
COUNT_CODE = "return len(input_0)\n"
#: The second test's last nodes sum the buildings' heights instead.
TOTAL_CODE = 'return float(input_0["height"].sum())\n'
TOTAL = 20.0 + 35.0 + 50.0
#: The height the tests write into a building's properties, and the value of
#: the property the third test adds.
NEW_HEIGHT = 99
NAME = "North"

#: Where a double-click is tried on the map, as fractions of the part of it in view.
PICK_SPOTS = ((0.4, 0.5), (0.6, 0.5), (0.45, 0.55), (0.7, 0.5), (0.3, 0.5), (0.5, 0.5), (0.2, 0.6), (0.8, 0.6))
#: How the second test zooms the map in: wheel steps over its middle, at most.
ZOOM_STEPS = 12
ZOOM_DELTA = 240
#: The share of the map's pixels a removed building takes away from the
#: drawing, at least: each of the two buildings fills a good part of it.
REMOVED_MIN_SHARE = 0.02
#: How long a run of the node and the nodes below it may take.
RUN_MS = 300000


def _py(values: dict) -> str:
    """*values* as the node writes them: a dict of names to numbers and texts."""
    return "{" + ", ".join(f"{json.dumps(name)}: {json.dumps(value)}" for name, value in values.items()) + "}"


def _code(remove=(), change=()) -> str:
    """The node's code as its map writes it (``mapEditsCode`` in
    ``utils/mapEdits/mapEdits.ts``): its own comment lines, then one call of
    ``curio_map_edits`` by building_id. *change* holds ``(id, values)``, in the
    order the ids were first changed: one on the call's line, several one per
    line."""
    entries = [f"{building}: {_py(values)}" for building, values in change]
    if len(entries) <= 1:
        changed = ["    change={" + "".join(entries) + "},"]
    else:
        changed = ["    change={", *(f"        {entry}," for entry in entries), "    },"]
    return "\n".join([
        "# Map Edits writes this code from its map: the features it removes and the",
        "# values it changes, matched by building_id. Comment lines above the return stay.",
        "return curio_map_edits(",
        "    input_0,",
        '    key="building_id",',
        f"    remove=[{', '.join(str(building) for building in remove)}],",
        *changed,
        ")",
        "",
    ])


#: A new node's code, by building_id: no edits yet.
NO_EDITS = _code()


def _spec(last_code: str = COUNT_CODE, last_title: str = "Count") -> dict:
    def node(node_id, node_type, x, y, content, title, metadata=None):
        return {
            "id": node_id, "type": node_type, "x": x, "y": y, "content": content, "title": title,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], **(metadata or {})},
        }

    def edge(source, target, handle="in"):
        return {"id": f"e-{source}-{target}", "source": source, "target": target, "sourceHandle": "out", "targetHandle": handle}

    # The Map Edits nodes are 900 wide and 460 tall.
    return {
        "dataflow": {
            "name": "Map Edits",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Map Edits",
            "nodes": [
                node(LOAD, "curio.builtin/data-loading", 0, 300, LOAD_CODE, "Buildings"),
                node(EDIT, EDIT_TYPE, 700, 0, NO_EDITS, "Map Edits"),
                node(COUNT, "curio.builtin/computation-analysis", 1720, 0, last_code, last_title),
                node(EDIT_2, EDIT_TYPE, 700, 600, NO_EDITS, "Map Edits", {"copiedFrom": [EDIT]}),
                node(COUNT_2, "curio.builtin/computation-analysis", 1720, 600, last_code, last_title,
                     {"copiedFrom": [COUNT]}),
            ],
            "edges": [edge(LOAD, EDIT), edge(EDIT, COUNT), edge(LOAD, EDIT_2), edge(EDIT_2, COUNT_2)],
            "scenarios": [
                {"id": EVERY, "name": "Every building", "color": "#3567c7", "nodes": [EDIT, COUNT]},
                {"id": LESS, "name": "One removed", "color": "#2f8f4a", "nodes": [EDIT_2, COUNT_2]},
            ],
        }
    }


def _enter(page, app_frontend, current_server, spec: dict, username: str) -> dict:
    """Sign in, open *spec* as one's own dataflow, and wait for its nodes."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Map Edits",
        username=username,
        project_name="Map Edits",
        project_spec=spec,
    )
    require_owner_view(page)
    for node_id in (LOAD, EDIT, EDIT_2, COUNT, COUNT_2):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    require_webgpu(page)
    return session


def _done(page, node_id: str, node_type: str = "") -> None:
    status = wait_for_node_settled(page, node_id, node_type=node_type, timeout_ms=180000)
    assert status == "done", f"{node_id} ended {status!r}: {read_node_error_text(node_locator(page, node_id))}"


def _value(page, node_id: str):
    """What *node_id*'s last run saved: a number."""
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, f"{node_id} shows no saved output"
    stored = load_artifact_as_dict(artifact)
    assert stored["dataType"] in ("int", "float"), stored
    return stored["data"]


def _run_below(page, node_id: str, edit: str) -> None:
    """Play *node_id*, below *edit*, and wait until both ran again: *edit* is
    stale after an edit, so playing the node below it runs it first."""
    before = {n: page.evaluate(_OUTPUT_ARTIFACT_JS, n) for n in (edit, node_id)}
    assert all(before.values()), f"a node shows no saved output before the run: {before}"
    play_node(page, node_id)
    deadline = time.time() + RUN_MS / 1000
    now = dict(before)
    while time.time() < deadline:
        now = {n: page.evaluate(_OUTPUT_ARTIFACT_JS, n) for n in (edit, node_id)}
        if all(now[n] and now[n] != before[n] for n in now):
            break
        page.wait_for_timeout(500)
    assert all(now[n] and now[n] != before[n] for n in now), (
        f"playing {node_id} did not run {edit} and it again: their outputs are saved to {now}, "
        f"as before the play ({before}). {read_node_error_text(node_locator(page, node_id))}"
    )
    _done(page, edit, EDIT_TYPE)
    _done(page, node_id)
    wait_for_run_guard_released(page, timeout_ms=RUN_MS)


# The node's code editor, not the field that shows a feature's properties.
_NODE_CODE_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    if (!node || !window.monaco) return null;
    const editors = window.monaco.editor.getEditors().filter((editor) => {
        const el = editor.getDomNode();
        return el && node.contains(el) && !el.closest('[data-testid="map-edits-field"]');
    });
    return editors.length === 1 ? editors[0].getValue() : null;
}"""


def _wait_for_code(page, node_id: str, expected: str, what: str) -> None:
    """Wait until the node's code is *expected*, the code its map writes."""
    code = None
    deadline = time.time() + 15
    while time.time() < deadline:
        code = page.evaluate(_NODE_CODE_JS, node_id)
        if code == expected:
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"after {what}, the node's code is\n{code}\nnot the code its map writes:\n{expected}")


# The Monaco editor of the panel's field: its text, after *text* is set when
# one is given, as a keystroke sets it (canvas_authoring.set_node_code).
_FIELD_JS = """({ id, text }) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const field = node && node.querySelector('[data-testid="map-edits-field"] .monaco-editor');
    if (!field) return { problem: "the panel shows no field" };
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = editors.find((e) => field.contains(e.getDomNode()));
    if (!editor) return { problem: "no Monaco editor owns the field" };
    if (text !== null) editor.setValue(text);
    return { text: editor.getValue() };
}"""


def _field(page, node_id: str) -> dict:
    """The selected feature's properties, as the field holds them."""
    found = None
    deadline = time.time() + 15
    while time.time() < deadline:
        found = page.evaluate(_FIELD_JS, {"id": node_id, "text": None})
        if "text" in found:
            return json.loads(found["text"])
        page.wait_for_timeout(250)
    raise AssertionError(f"{node_id}: {found['problem']}")


def _apply(page, node_id: str, properties: dict) -> None:
    """Write *properties* into the field, as typing would, and press Apply."""
    found = page.evaluate(_FIELD_JS, {"id": node_id, "text": json.dumps(properties, indent=2)})
    assert "text" in found, f"{node_id}: {found['problem']}"
    apply = node_locator(page, node_id).get_by_test_id("map-edits-apply")
    expect(apply).to_be_enabled(timeout=10000)
    apply.click()


def _panel(page, node_id: str):
    return page.locator(f'[data-map-edits-panel="{node_id}"]')


def _selected(page, node_id: str) -> str:
    return _panel(page, node_id).get_attribute("data-map-edits-selected") or ""


def _listed(page, node_id: str, attribute: str) -> list[str]:
    """The ids the panel lists under Removed (``put-back``) or Changed (``show``)."""
    return _panel(page, node_id).locator(f"[data-map-edits-{attribute}]").evaluate_all(
        f"(buttons) => buttons.map((button) => button.getAttribute('data-map-edits-{attribute}'))"
    )


def _map(node_id: str) -> str:
    """The node's map canvas: the Autark node's map code draws into it."""
    return f"#autk-grammar-map-{node_id}"


def _wait_for_map_drawn(page, node_id: str, timeout_ms: int = 90000) -> None:
    box = node_locator(page, node_id)
    box.locator('[data-map-edits-map-state]:not([data-map-edits-map-state="drawing"])').wait_for(
        state="attached", timeout=timeout_ms,
    )
    state = box.locator("[data-map-edits-map-state]").get_attribute("data-map-edits-map-state")
    problem = box.locator("[data-map-edits-map-problem]").all_inner_texts()
    assert state == "drawn", f"the Map Edits map of {node_id} ended {state!r}: {problem}"


def _wait_for_redraw(page, node_id: str, what: str) -> None:
    """Wait until the map drew again after *what*: each draw makes a canvas of
    its own (keep the old one with ``keep_drawing`` before the change)."""
    deadline = time.time() + INTERACTION_SHOWN_TIMEOUT_MS / 1000
    while time.time() < deadline and drawing_kept(page, _map(node_id)):
        page.wait_for_timeout(250)
    assert not drawing_kept(page, _map(node_id)), f"the map of {node_id} did not draw again after {what}"
    _wait_for_map_drawn(page, node_id)


def _map_pixels(page, node_id: str):
    """The map as it draws now, in its canvas's own pixels."""
    from PIL import Image

    url = page.evaluate(_AUTK_MAP_PIXELS_IN_FRAME_JS, node_id)
    assert url, f"the Map Edits node {node_id} has no map canvas"
    return Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")


def _changed(before, after) -> float:
    """The share of the map's pixels that differ by more than 10 in some channel.
    A feature's gray fill, (220, 220, 218), is at most 24 off the map's
    background, (232, 239, 242): a coarser threshold sees only its outline."""
    return _compare_images(after, before, 10).ratio


def _drawn_share(image) -> float:
    """The share of the map's pixels its drawing takes: those more than 8 off
    its top-left corner's colour in some channel, as ``autark_map_framing``
    reads them."""
    import numpy as np

    pixels = np.asarray(image).astype(int)
    return float((np.abs(pixels - pixels[0, 0]).max(axis=2) > 8).mean())


_SHOWN_JS = """([selector, x, y]) => document.elementFromPoint(x, y) === document.querySelector(selector)"""


def _pick_a_building(page, node_id: str) -> int:
    """Double-click the map where it draws a building, until the panel shows one.

    The buildings fill the layer's extent, which the map fits, so a spot along
    the map's middle lands on one: the marked pixel nearest the spot when the
    buildings are drawn in a saturated colour, else the spot itself."""
    canvas = _map(node_id)
    tried = []
    for at in PICK_SPOTS:
        dismiss_toasts(page)
        point = mark_point(page, canvas, at)
        if not point:
            box = page.locator(canvas).bounding_box()
            assert box, f"the Map Edits map of {node_id} has no layout box"
            point = {"x": box["x"] + at[0] * box["width"], "y": box["y"] + at[1] * box["height"]}
        x, y = assert_in_view(page, point["x"], point["y"], f"the building near {at} of the Map Edits map")
        if not page.evaluate(_SHOWN_JS, [canvas, x, y]):
            tried.append((at, "covered"))
            continue
        page.mouse.dblclick(x, y)
        deadline = time.time() + 10
        while time.time() < deadline:
            selected = _selected(page, node_id)
            if selected:
                assert int(selected) in PARTS, f"a double-click on one building selected {selected!r}"
                return int(selected)
            page.wait_for_timeout(250)
        tried.append((at, (round(x), round(y))))
    raise AssertionError(f"no double-click on the Map Edits map selected a building: {tried}")


def _assert_shows(page, node_id: str, building: int, *, heights) -> dict:
    """The panel shows *building*: the properties the map drew for the part
    selected, its height one of *heights*, without the geometry, and how many
    features an edit of it applies to."""
    expect(_panel(page, node_id)).to_have_attribute("data-map-edits-selected", str(building), timeout=10000)
    shown = _field(page, node_id)
    assert {"building_id", "height"} <= set(shown) and "geometry" not in shown, shown
    assert shown["building_id"] == building and shown["height"] in heights, (shown, heights)
    applies = node_locator(page, node_id).get_by_test_id("map-edits-applies-to")
    if PARTS[building] > 1:
        expect(applies).to_have_text(
            f"Applies to the {PARTS[building]} features with building_id {building}", timeout=10000,
        )
    else:
        expect(applies).to_have_count(0)
    return shown


# Records each state the dataflow's save indicator takes from now on, so an
# Unsaved that the 30 second autosave clears soon after is still seen.
_WATCH_SAVE_STATE_JS = """() => {
    const el = document.querySelector('[data-curio-save-state]');
    if (!el) return null;
    if (window.__curioSaveStateObserver) window.__curioSaveStateObserver.disconnect();
    window.__curioSaveStates = [el.getAttribute('data-curio-save-state')];
    const observer = new MutationObserver(() => {
        window.__curioSaveStates.push(el.getAttribute('data-curio-save-state'));
    });
    observer.observe(el, { attributes: true, attributeFilter: ['data-curio-save-state'] });
    window.__curioSaveStateObserver = observer;
    return window.__curioSaveStates[0];
}"""


def _watch_save_state(page) -> str:
    """Start recording the save indicator's states; returns the one it shows."""
    state = page.evaluate(_WATCH_SAVE_STATE_JS)
    assert state, "the canvas header shows no save state"
    return state


def _wait_for_unsaved(page, what: str) -> None:
    states: list = []
    deadline = time.time() + 10
    while time.time() < deadline:
        states = page.evaluate("() => window.__curioSaveStates || []")
        if "unsaved" in states:
            return
        page.wait_for_timeout(200)
    raise AssertionError(f"after {what}, the dataflow never read Unsaved: its save states were {states}")


def _open_provenance(page, node_id: str):
    """The node's Provenance drawer, opened from the button in its header."""
    node_locator(page, node_id).locator('.nav-link[data-rr-ui-event-key="provenance"]').first.click()
    expect(page.get_by_role("dialog", name="Node provenance")).to_be_visible(timeout=20000)
    await_drawer_at_rest(page)
    return page.locator(PROVENANCE_PANEL)


def _close_provenance(page) -> None:
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, PROVENANCE_DRAWER)


def _entries(panel) -> list[tuple[str, str]]:
    """``(id, text)`` of each entry the drawer lists, in its order."""
    items = panel.locator("[data-provenance-item]")
    ids = items.evaluate_all("(els) => els.map((el) => el.dataset.provenanceItem)")
    return [(entry, items.nth(i).inner_text()) for i, entry in enumerate(ids)]


def test_a_building_removed_on_the_map_leaves_it_drops_the_count_and_is_kept(
    app_frontend: "FrontendPage", current_server: str, page,
):
    session = _enter(page, app_frontend, current_server, _spec(), "map_edits_remove_e2e")
    token, project_id = session["token"], session["project"]["id"]

    run_all_and_wait(page, timeout_ms=300000)
    for node_id in (EDIT, EDIT_2):
        _done(page, node_id, EDIT_TYPE)
    for node_id in (COUNT, COUNT_2):
        _done(page, node_id)
    assert (_value(page, COUNT), _value(page, COUNT_2)) == (3, 3), "with no edits every part is counted"

    # The map draws the layer, by building_id, and the panel says what to do.
    edit = node_locator(page, EDIT_2)
    frame_nodes(page, [EDIT_2])
    _open_tab(page, EDIT_2, "output")
    _wait_for_map_drawn(page, EDIT_2)
    # Three flat boxes fill the map with a few colours, under the many a city
    # map holds (assert_autark_map_drawn's test): the double-click below is
    # what proves the buildings are drawn, landing on one; the close-up is
    # compared with its baseline.
    assert edit.get_by_test_id("edit-features-key").input_value() == "building_id"
    assert edit.locator("[data-map-edits-refusal]").count() == 0
    expect(_panel(page, EDIT_2)).to_contain_text(re.compile(r"Double-click a (building|feature) to see and edit its"))
    assert _listed(page, EDIT_2, "put-back") == [] and _listed(page, EDIT_2, "show") == []
    before = _map_pixels(page, EDIT_2)

    # A double-click selects a building: its properties, as the map drew them.
    picked = _pick_a_building(page, EDIT_2)
    _assert_shows(page, EDIT_2, picked, heights=HEIGHTS[picked])
    save_node_closeup(
        page, "map-edits", EDIT_2,
        test_name="test_a_building_removed_on_the_map_leaves_it_drops_the_count_and_is_kept",
        sweep_toasts=True,
    )

    # Remove takes out every part of it: the code holds it, the panel lists it,
    # the map draws without it, and the dataflow reads Unsaved.
    save_dataflow_and_settle_header(page)
    assert _watch_save_state(page) == "saved"
    keep_drawing(page, _map(EDIT_2))
    edit.get_by_test_id("edit-features-remove").click()
    removed = _code(remove=[picked])
    _wait_for_code(page, EDIT_2, removed, f"a Remove of building {picked}")
    # Nothing is selected then, and the panel lists the building as removed.
    expect(_panel(page, EDIT_2).locator(f'[data-map-edits-put-back="{picked}"]')).to_be_visible(timeout=10000)
    assert _selected(page, EDIT_2) == "", "the removed building is still selected"
    assert _listed(page, EDIT_2, "put-back") == [str(picked)]
    _wait_for_unsaved(page, f"a Remove of building {picked}")
    _wait_for_redraw(page, EDIT_2, f"a Remove of building {picked}")
    gone = _changed(before, _map_pixels(page, EDIT_2))
    assert gone >= REMOVED_MIN_SHARE, (
        f"removing building {picked} changed {gone:.2%} of the map: it still draws the building"
    )
    # The Id menu holds while the node has edits: they name features by it.
    expect(edit.get_by_test_id("edit-features-key")).to_be_disabled()

    # The count below: playing it runs the node again first, and the building
    # is gone with every part. The other scenario's count does not move.
    _run_below(page, COUNT_2, EDIT_2)
    expected = 3 - PARTS[picked]
    assert _value(page, COUNT_2) == expected < 3, (
        f"removing building {picked} ({PARTS[picked]} parts) left {_value(page, COUNT_2)} of 3 parts"
    )
    assert _value(page, COUNT) == 3, "the other scenario's count changed"

    # Saved and opened again: the code, the panel and the Remove's entry.
    project = save_dataflow(page)
    saved = {node["id"]: node for node in _saved_spec(current_server, token, project_id)["dataflow"]["nodes"]}
    assert saved[EDIT_2]["content"] == removed, saved[EDIT_2]["content"]
    assert saved[EDIT]["content"] == NO_EDITS, "the other scenario's node changed its code"
    assert "editFeatures" not in saved[EDIT_2]["metadata"], saved[EDIT_2]["metadata"]
    page.wait_for_url(f"**/dataflow/{project['id']}", timeout=30000)
    page.reload()
    for node_id in (LOAD, EDIT, EDIT_2, COUNT, COUNT_2):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    require_owner_view(page)
    frame_nodes(page, [EDIT_2])
    _open_tab(page, EDIT_2, "output")
    _wait_for_map_drawn(page, EDIT_2)
    _wait_for_code(page, EDIT_2, removed, "a reload")
    expect(_panel(page, EDIT_2).locator(f'[data-map-edits-put-back="{picked}"]')).to_be_visible(timeout=15000)
    save_node_closeup(
        page, "map-edits-removed", EDIT_2,
        test_name="test_a_building_removed_on_the_map_leaves_it_drops_the_count_and_is_kept",
        sweep_toasts=True,
    )
    panel = _open_provenance(page, EDIT_2)
    texts = [text for _entry, text in _entries(panel)]
    assert any(f"remove building_id {picked}" in text for text in texts), (
        f"the node's Provenance drawer lost the Remove: it lists {texts}"
    )
    _close_provenance(page)


def test_a_height_applied_on_a_zoomed_map_keeps_the_view_and_runs_through(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """The map frames its layers when it first draws. Zoomed in, a building
    selected and its height set in the field, Apply writes the height into
    the node's code for every part of the building, and the map draws again
    in the view it was zoomed to: not framed on its layers again, and nearer
    the zoomed view than the framed one. Playing the total below runs the node
    again, and the total holds the new height."""
    _enter(page, app_frontend, current_server, _spec(TOTAL_CODE, "Total height"), "map_edits_apply_e2e")
    run_all_and_wait(page, timeout_ms=300000)
    for node_id in (EDIT, EDIT_2):
        _done(page, node_id, EDIT_TYPE)
    for node_id in (COUNT, COUNT_2):
        _done(page, node_id)
    assert (_value(page, COUNT), _value(page, COUNT_2)) == (TOTAL, TOTAL), "with no edits every height is summed"

    frame_nodes(page, [EDIT_2])
    _open_tab(page, EDIT_2, "output")
    _wait_for_map_drawn(page, EDIT_2)
    framing = autark_map_framing(page, EDIT_2)
    assert framing is None, f"the map's first draw did not frame its layers: {framing}"
    framed = _map_pixels(page, EDIT_2)

    # Zoomed in with the wheel over the map's middle, until the drawing runs
    # past the canvas's edges.
    box = page.locator(_map(EDIT_2)).bounding_box()
    assert box, "the Map Edits map has no layout box"
    x, y = assert_in_view(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, "the middle of the map")
    page.mouse.move(x, y)
    delta = -ZOOM_DELTA
    share = _drawn_share(framed)
    zoomed = None
    for step in range(ZOOM_STEPS):
        page.mouse.wheel(0, delta)
        page.wait_for_timeout(500)
        if step == 0 and _drawn_share(_map_pixels(page, EDIT_2)) < share:
            # This wheel zooms out the other way round.
            delta = -delta
            continue
        if autark_map_framing(page, EDIT_2, timeout=0) is not None:
            zoomed = _map_pixels(page, EDIT_2)
            break
    assert zoomed is not None, f"{ZOOM_STEPS} wheel steps over the map did not zoom it in past its layers"
    zoom = _changed(framed, zoomed)

    # A building selected, its height set in the field, and Apply.
    picked = _pick_a_building(page, EDIT_2)
    shown = _field(page, EDIT_2)
    assert shown["height"] in HEIGHTS[picked], shown
    keep_drawing(page, _map(EDIT_2))
    _apply(page, EDIT_2, {**shown, "height": NEW_HEIGHT})
    applied = _code(change=[(picked, {"height": NEW_HEIGHT})])
    _wait_for_code(page, EDIT_2, applied, f"an Apply of height {NEW_HEIGHT} on building {picked}")
    _wait_for_redraw(page, EDIT_2, "the Apply")

    # The map keeps the view it was zoomed to.
    framing = autark_map_framing(page, EDIT_2, timeout=5000)
    assert framing is not None, "the map framed its layers again after the Apply, though it was zoomed in"
    after = _map_pixels(page, EDIT_2)
    assert _changed(zoomed, after) < _changed(framed, after), (
        f"after the Apply the map is {_changed(framed, after):.2%} off its framed view and "
        f"{_changed(zoomed, after):.2%} off the view it was zoomed to ({zoom:.2%} apart): "
        "a redraw after an edit keeps the view"
    )
    # The building stays in the panel, with its new height.
    _assert_shows(page, EDIT_2, picked, heights=[NEW_HEIGHT])
    save_node_closeup(
        page, "map-edits-applied", EDIT_2,
        test_name="test_a_height_applied_on_a_zoomed_map_keeps_the_view_and_runs_through",
        sweep_toasts=True,
    )

    # A run hands on the new height, for every part of the building.
    _run_below(page, COUNT_2, EDIT_2)
    expected = TOTAL - sum(HEIGHTS[picked]) + PARTS[picked] * NEW_HEIGHT
    assert _value(page, COUNT_2) == expected, (
        f"after the Apply of height {NEW_HEIGHT} on building {picked} ({PARTS[picked]} parts), "
        f"the total height is {_value(page, COUNT_2)}, not {expected}"
    )
    assert _value(page, COUNT) == TOTAL, "the other scenario's total changed"


def test_each_change_is_an_entry_in_the_node_provenance_and_putting_one_back_restores_its_edits(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Only the buildings run, so the Map Edits node never does. Two Applies
    and a Remove on one building each add an entry to the node's Provenance
    drawer at once, named by what it changed, each branching from the one
    before. The first entry's code put back opens the Code tab and adds no
    entry; on the Output tab, only the first Apply's edit is left: the map
    draws the building again, and the panel lists it as changed and shows it
    with its new height."""
    _enter(page, app_frontend, current_server, _spec(), "map_edits_provenance_e2e")
    run_node_and_wait(page, LOAD, node_type="data-loading", timeout_ms=180000)
    frame_nodes(page, [EDIT_2])
    _open_tab(page, EDIT_2, "output")
    _wait_for_map_drawn(page, EDIT_2)

    picked = _pick_a_building(page, EDIT_2)
    shown = _field(page, EDIT_2)
    labels = [
        f"height {NEW_HEIGHT} on building_id {picked}",
        f'name "{NAME}" on building_id {picked}',
        f"remove building_id {picked}",
    ]
    first = _code(change=[(picked, {"height": NEW_HEIGHT})])
    _apply(page, EDIT_2, {**shown, "height": NEW_HEIGHT})
    _wait_for_code(page, EDIT_2, first, "the first Apply")
    _assert_shows(page, EDIT_2, picked, heights=[NEW_HEIGHT])
    _apply(page, EDIT_2, {**_field(page, EDIT_2), "name": NAME})
    _wait_for_code(page, EDIT_2, _code(change=[(picked, {"height": NEW_HEIGHT, "name": NAME})]), "the second Apply")
    keep_drawing(page, _map(EDIT_2))
    node_locator(page, EDIT_2).get_by_test_id("edit-features-remove").click()
    _wait_for_code(page, EDIT_2, _code(remove=[picked]), "the Remove")
    _wait_for_redraw(page, EDIT_2, "the Remove")
    without = _map_pixels(page, EDIT_2)

    # Three entries, before the node runs, each named by what it changed.
    panel = _open_provenance(page, EDIT_2)
    entries = _entries(panel)
    assert len(entries) == 3, f"the drawer lists {entries}, not the three changes"
    for (_entry, text), label in zip(entries, labels):
        assert label in text, f"an entry reads {text!r}, not {label!r}: {entries}"
    # Each branches from the one before: one line, the Remove the newest.
    lines = {entry: panel.locator(f'[data-provenance-item="{entry}"]').evaluate(
        "(el) => el.closest('ol').dataset.provenanceLine") for entry, _text in entries}
    assert len(set(lines.values())) == 1, f"the three changes are not on one line: {lines}"
    expect(panel.locator(f'[data-provenance-item="{entries[2][0]}"]')).to_have_attribute(
        "data-provenance-current", "true",
    )

    # The first entry's code put back: the Code tab opens, and nothing is added.
    item = panel.locator(f'[data-provenance-item="{entries[0][0]}"]')
    head = item.locator("button").first
    if head.get_attribute("aria-expanded") != "true":
        head.click()
    keep_drawing(page, _map(EDIT_2))
    item.get_by_role("button", name="Put this code back in the node", exact=True).click()
    expect(item).to_have_attribute("data-provenance-current", "true")
    # The put back writes the node's code, which records no change of its own.
    page.wait_for_timeout(1000)
    assert len(_entries(panel)) == 3, f"putting an entry's code back added an entry: {_entries(panel)}"
    _close_provenance(page)
    expect(node_locator(page, EDIT_2).locator('.nav-link[data-rr-ui-event-key="code"]').first).to_have_class(
        re.compile(r"\bactive\b"),
    )
    _wait_for_code(page, EDIT_2, first, "the first entry's code was put back")

    # On the Output tab: only the first Apply's edit, on the map and in the panel.
    _open_tab(page, EDIT_2, "output")
    _wait_for_redraw(page, EDIT_2, "the first entry's code was put back")
    back = _changed(without, _map_pixels(page, EDIT_2))
    assert back >= REMOVED_MIN_SHARE, (
        f"putting the first entry's code back changed {back:.2%} of the map: building {picked} is not drawn again"
    )
    assert _listed(page, EDIT_2, "put-back") == [], "the Remove is still listed"
    assert _listed(page, EDIT_2, "show") == [str(picked)]
    _panel(page, EDIT_2).locator(f'[data-map-edits-show="{picked}"]').click()
    shown = _assert_shows(page, EDIT_2, picked, heights=[NEW_HEIGHT])
    assert "name" not in shown, f"the second Apply's name is still shown: {shown}"
    save_node_closeup(
        page, "map-edits-put-back", EDIT_2,
        test_name="test_each_change_is_an_entry_in_the_node_provenance_and_putting_one_back_restores_its_edits",
        sweep_toasts=True,
    )
