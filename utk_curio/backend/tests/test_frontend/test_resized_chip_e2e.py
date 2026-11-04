"""Playwright E2E: a chip's corner resizes the chip (#1235).

A node folded to its chip with the header's Minimize, then the chip's corner
dragged right and down: the chip grows. Opened with a click, the node is the
size it was before; folded again, its chip is the size its corner gave it.

The dataflow is loaded from a file on a new canvas, so it is the browser user's
own (#751) with accounts and on a stack without them.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_resized_chip_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import (
    activate_header_icon,
    node_locator,
    require_owner_view,
    stub_db_login,
    upload_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

NODE_ID = "resized-chip"

#: A chip's size in canvas px before its corner moves, `MINIMIZED_NODE_WIDTH`
#: and `MINIMIZED_NODE_HEIGHT` in src/constants.ts.
CHIP = [250, 40]

#: Whether the node shows its open card, and its size in canvas px.
_SIZE_JS = """(id) => {
    const flow = window.__curio_reactFlow;
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const card = document.getElementById(`${id}resizable`);
    if (!flow || !node || !card) return null;
    const zoom = flow.getViewport().zoom;
    const box = node.getBoundingClientRect();
    return {
        open: getComputedStyle(card).display !== "none",
        width: Math.round(box.width / zoom),
        height: Math.round(box.height / zoom),
    };
}"""


def _spec() -> dict:
    return {"dataflow": {
        "name": "Resized chip", "task": "", "timestamp": 1789193389280, "provenance_id": "Resized chip",
        "nodes": [{
            "id": NODE_ID, "type": "curio.builtin/computation-analysis", "x": 0, "y": 150,
            "content": "return 1\n", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": []}, "title": "Load streets",
        }],
        "edges": [],
    }}


def _size_once(page, condition: str) -> dict:
    """The node's size once *condition* (JavaScript on its size, ``s``) holds,
    or twenty seconds pass."""
    try:
        page.wait_for_function(
            f"(id) => {{ const s = ({_SIZE_JS})(id); return !!s && ({condition}); }}",
            arg=NODE_ID,
            polling=100,
            timeout=20000,
        )
    except PlaywrightTimeoutError:
        pass
    return page.evaluate(_SIZE_JS, NODE_ID)


def test_a_chip_keeps_the_size_its_corner_gives_it_and_the_open_node_keeps_its_own(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
):
    stub_db_login(
        page,
        app_frontend.base_url,
        current_server,
        name="Resized Chip",
        username="resized_chip",
    )
    page.goto(f"{app_frontend.base_url}/dataflow/new", timeout=120000)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    require_owner_view(page)
    spec_file = tmp_path / "resized-chip.json"
    spec_file.write_text(json.dumps(_spec()), encoding="utf-8")
    upload_workflow(page, app_frontend, str(spec_file), 1)
    node_locator(page, NODE_ID).wait_for(state="visible", timeout=45000)
    opened = _size_once(page, "s.open")
    minimize = page.locator(f'[id="{NODE_ID}resizable"] .curio-node-tools [data-tooltip="Minimize"]')

    activate_header_icon(minimize)
    folded = _size_once(page, f"!s.open && s.width === {CHIP[0]} && s.height === {CHIP[1]}")
    assert folded == {"open": False, "width": CHIP[0], "height": CHIP[1]}, folded

    # The chip's corner, dragged right and down.
    corner = page.locator(f'[id="{NODE_ID}resizer"]').bounding_box()
    assert corner, "the chip has no corner to resize it by"
    x, y = corner["x"] + corner["width"] / 2, corner["y"] + corner["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 120, y + 40, steps=12)
    page.mouse.up()
    resized = _size_once(page, f"!s.open && s.width > {CHIP[0]} && s.height > {CHIP[1]}")
    assert not resized["open"] and resized["width"] > CHIP[0] and resized["height"] > CHIP[1], (
        f"the chip's corner left it {resized}"
    )

    # Opened, it is the size it was; folded again, its chip is the size its
    # corner gave it.
    page.locator(f'.react-flow__node[data-id="{NODE_ID}"] .curio-node-chip').click()
    reopened = _size_once(page, "s.open")
    activate_header_icon(minimize)
    refolded = _size_once(page, "!s.open")
    assert {"opened again": reopened, "folded again": refolded} == {"opened again": opened, "folded again": resized}
