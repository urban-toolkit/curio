"""Playwright E2E: a widget panel scrolls with the Data Catalog's thin scrollbar (#1003).

The Quad Cities flood dataflow's "Top-left corner" Parameter node lists the
five nodes whose code uses ``@topleft``. At the Parameter template's size, 360
by 230, the node's bottom edge cuts the fifth line, and its panel scrolls.
Every widget panel (a Parameter node's value and its form, a node's Widgets
tab) scrolls with the scrollbar of the Data Catalog's panels, one rule for all
of them (``styles/scrollbars.module.css``).

The dataflow holds the example's own nodes: its three Parameter nodes and the
five whose code uses the corner. A new Parameter node beside them shows its
form. The test opens a dataset's details in the Data Catalog, then the
dataflow, and checks:

1. The corner node lists five nodes, and the fifth ends below its panel's
   bottom edge. That held before the fix as well: it is why the scrollbar
   matters.
2. The corner node's panel, the new Parameter node's form and an "Average
   depth by period" node's Widgets tab compute the ``scrollbar-width`` and
   ``scrollbar-color`` of the Data Catalog's content column.
3. The corner node's scrollbar takes as much room as the Data Catalog's, and
   some: on CI's Linux browser a scrollbar sits beside the content.
4. Scrolled down, the panel shows its fifth line.

Then a close-up of the corner node, scrolled to the top, is a baseline to review.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_widget_panel_scrollbar_e2e.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from .test_widget_tags_e2e import _open_tab, _panel
from .utils import (
    REPO_ROOT,
    frame_node,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_node_closeup,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "quad-cities-flood-vulnerability.json"
PARAMETER_TYPE = "curio.builtin/parameter"
#: The corner Parameter node's widget, and how many nodes' code uses it.
CORNER = "topleft"
CORNER_USERS = 5
#: Whose Widgets tab is checked: a node that uses the corner and has a widget of its own.
WIDGETS_LABEL = "Average depth by period"
#: A Parameter node with no widget yet, which shows its form.
NEW_PARAMETER = "scrollbar-new-parameter"
#: Any dataset: its details hold the Data Catalog's scrolling columns.
DATASET = "data.cdc.quad-cities-svi-tracts"
CONTENT_COLUMN = 'section[aria-label="Dataset content"]'
#: The close-up's baseline is ``screenshot_widget-panel-scrollbar_parameter_used_by.png``.
CLOSEUP_STEM = "widget-panel-scrollbar"

#: A scroller's scrollbar: its computed style, and the room it takes beside the content.
_SCROLLBAR_JS = """(el) => {
    const cs = getComputedStyle(el);
    const borders = parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth);
    return { width: cs.scrollbarWidth, color: cs.scrollbarColor,
             room: el.offsetWidth - el.clientWidth - borders };
}"""

#: The Data Catalog column's scrollbar, on a box with that column's classes that
#: holds more than it shows: the column itself may hold too little to scroll.
_CATALOG_SCROLLBAR_JS = """(column) => {
    const probe = document.createElement("div");
    probe.className = column.className;
    probe.style.cssText = "position: fixed; left: 0; top: 0; display: block; width: 200px; "
        + "height: 100px; overflow-y: auto; visibility: hidden;";
    const inner = document.createElement("div");
    inner.style.height = "400px";
    probe.appendChild(inner);
    document.body.appendChild(probe);
    const cs = getComputedStyle(probe);
    const borders = parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth);
    const seen = { width: cs.scrollbarWidth, color: cs.scrollbarColor,
                   room: probe.offsetWidth - probe.clientWidth - borders };
    probe.remove();
    return seen;
}"""

#: How far the corner node's last listed node ends below its panel's bottom edge.
_LAST_USER_JS = """(panel) => {
    const users = panel.querySelectorAll("[data-parameter-users] [data-parameter-user]");
    const last = users[users.length - 1];
    const edge = panel.getBoundingClientRect().bottom;
    return { count: users.length, below: last ? last.getBoundingClientRect().bottom - edge : null };
}"""


def _uses_corner(node: dict) -> bool:
    return f"[!! @{CORNER} !!]" in (node.get("content") or "")


def _spec() -> dict:
    """The example's Parameter nodes and the nodes whose code uses the corner,
    and a new Parameter node, with no edges: nothing runs."""
    nodes = json.loads(EXAMPLE.read_text(encoding="utf-8"))["dataflow"]["nodes"]
    parameters = [node for node in nodes if node["type"].split("@")[0] == PARAMETER_TYPE]
    new = {
        "id": NEW_PARAMETER, "type": PARAMETER_TYPE, "x": 0, "y": 1350, "content": "",
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    return {
        "dataflow": {
            "name": "Widget panel scrollbar",
            "task": "",
            "nodes": [*parameters, *[node for node in nodes if _uses_corner(node)], new],
            "edges": [],
        }
    }


def test_widget_panels_scroll_with_the_data_catalogs_scrollbar(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    spec = _spec()
    nodes = spec["dataflow"]["nodes"]
    (corner,) = [
        node["id"] for node in nodes
        if any(widget.get("name") == CORNER for widget in node["metadata"].get("widgets", []))
    ]
    users = [node for node in nodes if _uses_corner(node)]
    assert len(users) == CORNER_USERS, (
        f"the example's code uses @{CORNER} in {len(users)} nodes, not {CORNER_USERS}"
    )
    (widgets_node, *_) = [
        node["id"] for node in users
        if node["metadata"].get("packageTemplateLabel") == WIDGETS_LABEL and node["metadata"].get("widgets")
    ]

    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_db_login(
        page,
        app_frontend.base_url,
        current_server,
        username="widget_panel_scrollbar_e2e",
        name="Widget Panel Scrollbar",
        project_name="Widget panel scrollbar",
        project_spec=spec,
    )
    project_id = session["project"]["id"]

    # The Data Catalog's scrollbar, from a dataset's details.
    page.goto(f"{app_frontend.base_url}/catalog/data/{quote(DATASET, safe='')}", timeout=120000)
    column = page.locator(CONTENT_COLUMN).first
    column.wait_for(state="visible", timeout=30000)
    catalog = column.evaluate(_CATALOG_SCROLLBAR_JS)
    assert catalog["width"] == "thin" and catalog["room"] > 0, (
        f"the Data Catalog's content column does not scroll with its thin scrollbar: {catalog}"
    )

    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    page.wait_for_load_state("domcontentloaded")
    require_owner_view(page)
    corner_panel = node_locator(page, corner).locator("[data-parameter-panel]").first
    corner_panel.wait_for(state="visible", timeout=45000)
    page.wait_for_function(
        """([id, count]) => document.querySelectorAll(
            `.react-flow__node[data-id="${id}"] [data-parameter-users] [data-parameter-user]`).length === count""",
        arg=[corner, CORNER_USERS],
        timeout=15000,
    )
    frame_node(page, corner)

    # 1. The corner node's list runs past its panel.
    last = corner_panel.evaluate(_LAST_USER_JS)
    assert last["count"] == CORNER_USERS and last["below"] > 1, (
        "at the Parameter template's size the corner node's list should run past its panel, "
        f"which is what makes its scrollbar matter: {last}"
    )

    # 2. Every widget panel computes the Data Catalog's scrollbar.
    form_panel = node_locator(page, NEW_PARAMETER).locator("[data-parameter-panel]").first
    form_panel.wait_for(state="visible", timeout=15000)
    _open_tab(page, widgets_node, "widgets")
    widgets_panel = _panel(page, widgets_node)
    widgets_panel.wait_for(state="visible", timeout=15000)
    panels = {
        "the Top-left corner node": corner_panel,
        "a new Parameter node's form": form_panel,
        f"{WIDGETS_LABEL}'s Widgets tab": widgets_panel,
    }
    seen = {name: panel.evaluate(_SCROLLBAR_JS) for name, panel in panels.items()}
    assert {name: (s["width"], s["color"]) for name, s in seen.items()} == {
        name: (catalog["width"], catalog["color"]) for name in panels
    }, (
        "a widget panel does not scroll with the Data Catalog's scrollbar (scrollbar-width "
        f"{catalog['width']!r}, scrollbar-color {catalog['color']!r}): {seen}"
    )

    # 3. The corner node's scrollbar takes the Data Catalog's room beside the list.
    room = seen["the Top-left corner node"]["room"]
    assert room > 0 and room == catalog["room"], (
        f"the corner node's scrollbar takes {room} px beside its list, "
        f"and the Data Catalog's takes {catalog['room']} px"
    )

    # 4. Scrolled down, the fifth line shows.
    corner_panel.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    scrolled = corner_panel.evaluate(_LAST_USER_JS)
    assert scrolled["below"] <= 1, (
        f"scrolled to the bottom, the corner node's panel still cuts its last line: {scrolled}"
    )

    # The corner node as a user first sees it, scrolled to the top: the
    # scrollbar says there is more below. No field holds the focus ring.
    corner_panel.evaluate(
        "el => { document.activeElement && document.activeElement.blur(); el.scrollTop = 0; }"
    )
    save_node_closeup(page, CLOSEUP_STEM, corner, test_name="parameter_used_by", sweep_toasts=True)
