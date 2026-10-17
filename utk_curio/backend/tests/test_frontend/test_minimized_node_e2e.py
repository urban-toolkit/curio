"""Playwright E2E: a minimized node stays minimized when its dataflow is saved
and opened again.

The report (komar41's #914): a node folded to its chip with the header's
Minimize opened full again after a reload. The gesture is the owner's own:
Minimize in the node's header, Save from the File menu, a reload of the page.
The node is then still a chip, the node beside it, never minimized, is still
open, and the saved spec says the same.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_minimized_node_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    activate_header_icon,
    api_json,
    node_locator,
    require_owner_view,
    save_dataflow,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

FOLDED_ID = "minimized-folded"
OPEN_ID = "minimized-open"
NODE_IDS = [FOLDED_ID, OPEN_ID]


def _node(node_id: str, x: int) -> dict:
    return {
        "id": node_id, "type": "curio.builtin/computation-analysis", "x": x, "y": 150,
        "content": "return 1\n", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": []},
    }


def _spec() -> dict:
    return {"dataflow": {
        "name": "Minimized node", "task": "", "timestamp": 1789193389280,
        "provenance_id": "Minimized node",
        "nodes": [_node(FOLDED_ID, 0), _node(OPEN_ID, 645)],
        "edges": [],
    }}


#: What the canvas draws for each node: its open card, or only its chip (the
#: card hidden, and the node far narrower than a card at the canvas's zoom).
_DRAWN_JS = """(ids) => {
    const flow = window.__curio_reactFlow;
    if (!flow) return Object.fromEntries(ids.map((id) => [id, "no canvas"]));
    const zoom = flow.getViewport().zoom;
    return Object.fromEntries(ids.map((id) => {
        const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
        const card = document.getElementById(`${id}resizable`);
        if (!node || !card) return [id, "not drawn"];
        const width = Math.round(node.getBoundingClientRect().width / zoom);
        const open = getComputedStyle(card).display !== "none";
        if (open && width >= 200) return [id, "card"];
        if (!open && width < 200) return [id, "chip"];
        return [id, `${open ? "card shown" : "card hidden"}, ${width} px wide`];
    }));
}"""


def _drawn_once_settled(page, expected: dict) -> dict:
    """What the canvas draws, once it draws *expected* or ten seconds pass."""
    try:
        page.wait_for_function(
            f"([ids, expected]) => {{ const drawn = ({_DRAWN_JS})(ids);"
            " return ids.every((id) => drawn[id] === expected[id]); }",
            arg=[NODE_IDS, expected],
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        pass
    return page.evaluate(_DRAWN_JS, NODE_IDS)


def test_a_minimized_node_is_still_minimized_after_a_save_and_a_reload(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Minimized Node",
        username="minimized_node",
        project_name="Minimized node",
        project_spec=_spec(),
    )
    require_owner_view(page)
    for node_id in NODE_IDS:
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    folded = {FOLDED_ID: "chip", OPEN_ID: "card"}

    # Minimize in the node's header folds it to its chip.
    activate_header_icon(page.locator(f'[id="{FOLDED_ID}resizable"] .curio-node-tools [title="Minimize"]'))
    minimized = _drawn_once_settled(page, folded)

    # Saved from the File menu.
    save_dataflow(page)
    project = api_json(f"{current_server}/api/projects/{session['project']['id']}", session["token"])
    saved = {node["id"]: node.get("minimized") for node in project["spec"]["dataflow"]["nodes"]}

    # And opened again.
    page.reload()
    for node_id in NODE_IDS:
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    reloaded = _drawn_once_settled(page, folded)

    seen = {"after Minimize": minimized, "saved": saved, "after the reload": reloaded}
    expected = {
        "after Minimize": folded,
        "saved": {FOLDED_ID: True, OPEN_ID: None},
        "after the reload": folded,
    }
    assert seen == expected, json.dumps(seen, indent=2)
