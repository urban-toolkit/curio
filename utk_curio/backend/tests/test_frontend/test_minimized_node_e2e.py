"""Playwright E2E: a minimized node stays minimized when its dataflow is saved
and opened again, and its chip shows the node's title.

The report (komar41's #914): a node folded to its chip with the header's
Minimize opened full again after a reload. The gesture is the owner's own:
Minimize in a node's header, Save from the File menu, a reload of the page. The
node is then still a chip, the node beside it, never minimized, is still open,
and the saved spec says the same.

komar41's #1118: a chip showed only its kind's icon, so two Python nodes folded
side by side looked the same. The chip shows the node's title after its icon,
as the header shows it: a long title is cut with an ellipsis and its hover
gives it whole, a short one shows whole. A node saved minimized opens as its
chip, titled the same way.

The dataflow is loaded from a file on a new canvas, so it is the browser user's
own (#751) with accounts and on a stack without them, where the one local user
saves.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_minimized_node_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    activate_header_icon,
    hover_until_tooltip_says,
    node_locator,
    require_owner_view,
    save_dataflow,
    save_node_closeup,
    stub_db_login,
    upload_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

FOLDED_ID = "minimized-folded"
SHORT_ID = "minimized-short"
OPEN_ID = "minimized-open"
NODE_IDS = [FOLDED_ID, SHORT_ID, OPEN_ID]

#: Longer than a chip holds, so it is cut with an ellipsis.
LONG_TITLE = "Make ground grid and selected days for the whole year"
#: Short enough to show whole.
SHORT_TITLE = "Load streets"

#: A chip's size in canvas px, `MINIMIZED_NODE_WIDTH` and
#: `MINIMIZED_NODE_HEIGHT` in src/constants.ts.
CHIP = [250, 40]

#: The close-ups' baseline group.
CLOSEUP_STEM = "minimized-node-chip"


def _node(node_id: str, x: int, y: int, title: str | None = None, minimized: bool = False) -> dict:
    metadata: dict = {"keywords": []}
    if title:
        metadata["packageTemplateLabel"] = title
    node = {
        "id": node_id, "type": "curio.builtin/computation-analysis", "x": x, "y": y,
        "content": "return 1\n", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": metadata,
    }
    if minimized:
        node["minimized"] = True
    return node


def _spec() -> dict:
    return {"dataflow": {
        "name": "Minimized node", "task": "", "timestamp": 1789193389280,
        "provenance_id": "Minimized node",
        "nodes": [
            _node(FOLDED_ID, 0, 150, LONG_TITLE),
            # Saved minimized: it opens as its chip.
            _node(SHORT_ID, 0, 650, SHORT_TITLE, minimized=True),
            _node(OPEN_ID, 645, 150),
        ],
        "edges": [],
    }}


#: What the canvas draws for each node: its open card, or only its chip (the
#: card hidden, and the node the chip's size at the canvas's zoom, within the
#: pixel the zoom's rounding takes).
_DRAWN_JS = """([ids, chip]) => {
    const flow = window.__curio_reactFlow;
    if (!flow) return Object.fromEntries(ids.map((id) => [id, "no canvas"]));
    const zoom = flow.getViewport().zoom;
    return Object.fromEntries(ids.map((id) => {
        const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
        const card = document.getElementById(`${id}resizable`);
        if (!node || !card) return [id, "not drawn"];
        const box = node.getBoundingClientRect();
        const width = Math.round(box.width / zoom);
        const height = Math.round(box.height / zoom);
        const open = getComputedStyle(card).display !== "none";
        if (open && width >= 200) return [id, "card"];
        if (!open && Math.abs(width - chip[0]) <= 1 && Math.abs(height - chip[1]) <= 1) return [id, "chip"];
        return [id, `${open ? "card shown" : "card hidden"}, ${width} x ${height} px`];
    }));
}"""

#: What a chip shows as its title: the element whose tooltip is the title, its
#: text, and whether the text overflows its box, which its ellipsis then cuts.
_CHIP_TITLE_JS = """([id, title]) => {
    const chip = document.querySelector(`.react-flow__node[data-id="${id}"] .curio-node-chip`);
    if (!chip) return "no chip";
    const shown = [...chip.querySelectorAll("[data-tooltip]")].find(
        (el) => el.getAttribute("data-tooltip") === title);
    if (!shown) return `no title on the chip, its text is ${JSON.stringify(chip.textContent)}`;
    const style = getComputedStyle(shown);
    return {
        text: shown.textContent,
        cut: shown.scrollWidth > shown.clientWidth && style.textOverflow === "ellipsis",
        whole: shown.scrollWidth <= shown.clientWidth,
    };
}"""


def _drawn_once_settled(page, expected: dict) -> dict:
    """What the canvas draws, once it draws *expected* or twenty seconds pass."""
    try:
        page.wait_for_function(
            f"([ids, chip, expected]) => {{ const drawn = ({_DRAWN_JS})([ids, chip]);"
            " return ids.every((id) => drawn[id] === expected[id]); }",
            arg=[NODE_IDS, CHIP, expected],
            polling=100,
            timeout=20000,
        )
    except PlaywrightTimeoutError:
        pass
    return page.evaluate(_DRAWN_JS, [NODE_IDS, CHIP])


def _chip_titles(page) -> dict:
    """What each chip shows as its title, and whether it is cut or whole."""
    return {
        FOLDED_ID: page.evaluate(_CHIP_TITLE_JS, [FOLDED_ID, LONG_TITLE]),
        SHORT_ID: page.evaluate(_CHIP_TITLE_JS, [SHORT_ID, SHORT_TITLE]),
    }


def _chip_title_selector(node_id: str, title: str) -> str:
    return f'.react-flow__node[data-id="{node_id}"] .curio-node-chip [data-tooltip="{title}"]'


def test_a_minimized_node_is_still_minimized_after_a_save_and_a_reload(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
):
    stub_db_login(
        page,
        app_frontend.base_url,
        current_server,
        name="Minimized Node",
        username="minimized_node",
    )
    page.goto(f"{app_frontend.base_url}/dataflow/new", timeout=120000)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    require_owner_view(page)
    spec_file = tmp_path / "minimized-node.json"
    spec_file.write_text(json.dumps(_spec()), encoding="utf-8")
    upload_workflow(page, app_frontend, str(spec_file), len(NODE_IDS))
    for node_id in NODE_IDS:
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    folded = {FOLDED_ID: "chip", SHORT_ID: "chip", OPEN_ID: "card"}

    # Minimize in the node's header folds it to its chip.
    activate_header_icon(page.locator(f'[id="{FOLDED_ID}resizable"] .curio-node-tools [data-tooltip="Minimize"]'))
    minimized = _drawn_once_settled(page, folded)
    titled = _chip_titles(page)

    # Saved from the File menu: the spec as the server stored it.
    project = save_dataflow(page)
    saved = {node["id"]: node.get("minimized") for node in project["spec"]["dataflow"]["nodes"]}

    # And opened again, from the dataflow's own address.
    page.wait_for_url(f"**/dataflow/{project['id']}", timeout=30000)
    page.reload()
    for node_id in NODE_IDS:
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    reloaded = _drawn_once_settled(page, folded)
    titled_reloaded = _chip_titles(page)

    long_title = {"text": LONG_TITLE, "cut": True, "whole": False}
    short_title = {"text": SHORT_TITLE, "cut": False, "whole": True}
    seen = {
        "after Minimize": minimized,
        "chip titles after Minimize": titled,
        "saved": saved,
        "after the reload": reloaded,
        "chip titles after the reload": titled_reloaded,
    }
    expected = {
        "after Minimize": folded,
        "chip titles after Minimize": {FOLDED_ID: long_title, SHORT_ID: short_title},
        "saved": {FOLDED_ID: True, SHORT_ID: True, OPEN_ID: None},
        "after the reload": folded,
        "chip titles after the reload": {FOLDED_ID: long_title, SHORT_ID: short_title},
    }
    assert seen == expected, json.dumps(seen, indent=2)

    # The long title's hover gives it whole, as the header's title does.
    hover_until_tooltip_says(
        page, _chip_title_selector(FOLDED_ID, LONG_TITLE), "the long title on its chip", [LONG_TITLE],
    )

    # Last, since a missing baseline stops the test at its capture: the two
    # chips as the canvas draws them, the long title cut, the short one whole.
    save_node_closeup(page, CLOSEUP_STEM, FOLDED_ID, test_name="long_title", sweep_toasts=True)
    save_node_closeup(page, CLOSEUP_STEM, SHORT_ID, test_name="short_title", sweep_toasts=True)
