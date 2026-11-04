"""Playwright E2E: a narrow node's header shows its title before its pills.

The report (the frame audit of #1252): a narrow package node, such as the
Accumulated Shadow node of the Chicago Loop example, showed no title at all
in its header, not even "…". The title was the one part of the header that
gave way, and the pills, the status and the tools took all the room.

Here two Vega-Lite package charts have the same long title, one narrow and one
as wide as a new node. The narrow one shows the start of its title, its pills
compact and its PACKAGE button still there to click; the wide one shows its
title and its whole pills, as before.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_narrow_header_title_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    settled_viewport,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

NARROW, WIDE = "narrow-chart", "wide-chart"
TITLE = "Mean accumulated shadow by scenario"


def _chart(node_id: str, x: int, width: int) -> dict:
    return {
        "id": node_id, "type": "curio.vega-lite/bars", "title": TITLE, "x": x, "y": 0,
        "width": width, "height": 300, "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": []},
    }


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Narrow header", "task": "", "timestamp": 1789193389280, "provenance_id": "Narrow header",
            "packages": ["curio.vega-lite@1"],
            "nodes": [_chart(NARROW, 0, 340), _chart(WIDE, 400, 525)],
            "edges": [],
        }
    }


#: Each node's header as drawn: how wide its title shows, in canvas units,
#: whether its PACKAGE pill shows the word, and whether the button that opens
#: its package shows at all. The title is the button that renames the node, or,
#: where it cannot be renamed, the text whose tooltip is the title.
_HEADERS_JS = """([ids, name]) => {
    const zoom = window.__curio_reactFlow.getViewport().zoom;
    return Object.fromEntries(ids.map((id) => {
        const header = document.querySelector(`.react-flow__node[data-id="${id}"] .curio-node-header`);
        const title = header && (header.querySelector('button[aria-label^="Edit node title"]')
            || [...header.querySelectorAll('[data-tooltip]')].find((el) => el.getAttribute('data-tooltip') === name));
        if (!title) return [id, 'no title'];
        const button = header.querySelector('button[aria-label^="Open package "]');
        return [id, {
            title: Math.round(title.getBoundingClientRect().width / zoom),
            packagePill: header.innerText.includes('PACKAGE'),
            packageButton: !!button && button.getBoundingClientRect().width > 0,
        }];
    }));
}"""


def test_a_narrow_node_shows_its_title_and_a_wide_one_its_pills_too(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Narrow Header",
        username="narrow_header_e2e",
        project_name="Narrow header",
        project_spec=_spec(),
    )
    require_owner_view(page)
    for node_id in (NARROW, WIDE):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    # The wide node's PACKAGE pill: the package's template has loaded.
    page.locator(f'.react-flow__node[data-id="{WIDE}"] .curio-node-header').get_by_text(
        "PACKAGE", exact=True
    ).wait_for(state="visible", timeout=45000)
    settled_viewport(page)

    headers = page.evaluate(_HEADERS_JS, [[NARROW, WIDE], TITLE])

    narrow, wide = headers[NARROW], headers[WIDE]
    # The narrow node shows the start of its title, a few characters and "…",
    # and its button that opens the package is still there.
    assert isinstance(narrow, dict) and narrow["title"] >= 40, headers
    assert narrow["packageButton"], headers
    # The wide one keeps its whole pills beside a title that shows more than that.
    assert isinstance(wide, dict) and wide["packagePill"] and wide["title"] >= 64, headers
