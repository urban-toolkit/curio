"""Playwright E2E: a node's Widgets tab scrolls with the Data Catalog's thin scrollbar (#1003).

A node's Widgets tab scrolls with the scrollbar of the Data Catalog's panels,
one rule for both (``styles/scrollbars.module.css``).

Chrome draws that rule's ``::-webkit-scrollbar`` bar: 6 px, a thumb of
``rgba(30, 31, 35, 0.18)``, shown at rest on every system. On a Mac, Chrome's
own bar would hide until you scroll, so the rule keeps ``scrollbar-width`` and
``scrollbar-color``, which would turn the webkit bar off, for the browsers
without ``::-webkit-scrollbar``. A bar that shows at rest takes room beside the
content (``offsetWidth - clientWidth``); one that shows only while scrolling
takes none.

The dataflow holds one Python node with more widgets than its Widgets tab
shows at the node's size, and no edges. The test opens a dataset's details in
the Data Catalog, then the dataflow, and checks:

1. The node's last widget ends below its Widgets tab's bottom edge: the tab
   holds more than it shows, which is why its scrollbar matters.
2. The Data Catalog's content column and the Widgets tab draw the rule's bar
   at rest: a box with their classes that holds more than it shows gives its
   bar 6 px beside the content, with the rule's thumb, and the Widgets tab,
   which holds more than it shows, gives its own bar those 6 px. The Widgets
   tab also computes the Data Catalog's ``scrollbar-width`` and
   ``scrollbar-color``.
3. Scrolled down, the Widgets tab shows its last widget.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_widget_panel_scrollbar_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from .test_widget_tags_e2e import _open_tab, _panel
from .utils import (
    frame_node,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: A Python node whose widgets are more rows than its Widgets tab shows.
NODE = "scrollbar-widgets"
SOLUTIONS = ["Bioswales/Infiltration trenches", "Permeable pavements", "Retention ponds", "Constructed wetlands"]
WEIGHTS = range(1, 11)
WIDGETS = [
    {"name": "use_NBS_classes", "type": "checkbox-group", "label": "Nature-based solutions",
     "default": SOLUTIONS, "options": {"choices": SOLUTIONS}},
    *[{"name": f"weight_{i}", "type": "number", "label": f"Weight {i}", "default": i} for i in WEIGHTS],
]
CODE = (
    "chosen = [!! use_NBS_classes !!]\n"
    "weights = [" + ", ".join(f"[!! weight_{i} !!]" for i in WEIGHTS) + "]\n"
    "return len(chosen) * sum(weights)\n"
)
TAB = "the node's Widgets tab"
#: Any dataset: its details hold the Data Catalog's scrolling columns.
DATASET = "data.cdc.quad-cities-svi-tracts"
CONTENT_COLUMN = 'section[aria-label="Dataset content"]'
#: The shared rule's bar (``styles/scrollbars.module.css``): its width, and its thumb at rest.
BAR_PX = 6
THUMB = "rgba(30, 31, 35, 0.18)"

#: A scroller's scrollbar. ``own`` is the room its own bar takes beside the
#: content, and ``scrolls`` whether it holds more than it shows. The rest is
#: read on a box with its classes that holds more than it shows, so that a
#: panel with too little in it still tells its bar; the box is hidden, so no
#: pointer rests on it and its thumb keeps its colour at rest. A bar that shows
#: only while scrolling takes no room.
_SCROLLBAR_JS = """(el) => {
    const room = (box) => {
        const cs = getComputedStyle(box);
        return box.offsetWidth - box.clientWidth
            - parseFloat(cs.borderLeftWidth) - parseFloat(cs.borderRightWidth);
    };
    const probe = document.createElement("div");
    probe.className = el.className;
    probe.style.cssText = "position: fixed; left: 0; top: 0; display: block; width: 200px; "
        + "height: 100px; overflow-y: auto; visibility: hidden;";
    const inner = document.createElement("div");
    inner.style.height = "400px";
    probe.appendChild(inner);
    document.body.appendChild(probe);
    const cs = getComputedStyle(el);
    const seen = {
        width: cs.scrollbarWidth,
        color: cs.scrollbarColor,
        bar: room(probe),
        webkit_width: getComputedStyle(probe, "::-webkit-scrollbar").width,
        thumb: getComputedStyle(probe, "::-webkit-scrollbar-thumb").backgroundColor,
        scrolls: el.scrollHeight > el.clientHeight,
        own: room(el),
    };
    probe.remove();
    return seen;
}"""

#: How far the Widgets tab's last widget ends below the tab's bottom edge.
_LAST_ROW_JS = """(panel) => {
    const rows = panel.querySelectorAll("[data-widget-row]");
    const last = rows[rows.length - 1];
    const edge = panel.getBoundingClientRect().bottom;
    return { count: rows.length, below: last ? last.getBoundingClientRect().bottom - edge : null };
}"""


def _spec() -> dict:
    """The one node, with no edges: nothing runs."""
    return {
        "dataflow": {
            "name": "Widget panel scrollbar",
            "task": "",
            "nodes": [{
                "id": NODE, "type": "curio.builtin/computation-analysis", "x": 0, "y": 0, "content": CODE,
                "in": "DEFAULT", "out": "DEFAULT", "goal": "",
                "metadata": {"keywords": [], "widgets": WIDGETS},
            }],
            "edges": [],
        }
    }


def test_the_widgets_tab_scrolls_with_the_data_catalogs_scrollbar(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
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
        project_spec=_spec(),
    )
    project_id = session["project"]["id"]

    # The Data Catalog's scrollbar, from a dataset's details. It is checked
    # with the Widgets tab's in step 2.
    page.goto(f"{app_frontend.base_url}/catalog/data/{quote(DATASET, safe='')}", timeout=120000)
    column = page.locator(CONTENT_COLUMN).first
    column.wait_for(state="visible", timeout=30000)
    catalog = column.evaluate(_SCROLLBAR_JS)

    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    page.wait_for_load_state("domcontentloaded")
    require_owner_view(page)
    node_locator(page, NODE).wait_for(state="visible", timeout=45000)
    frame_node(page, NODE)
    _open_tab(page, NODE, "widgets")
    panel = _panel(page, NODE)
    panel.wait_for(state="visible", timeout=15000)
    page.wait_for_function(
        """([id, count]) => document.querySelectorAll(
            `.react-flow__node[data-id="${id}"] [data-widgets-panel] [data-widget-row]`).length === count""",
        arg=[NODE, len(WIDGETS)],
        timeout=15000,
    )

    # 1. The Widgets tab holds more than it shows.
    last = panel.evaluate(_LAST_ROW_JS)
    assert last["count"] == len(WIDGETS) and last["below"] > 1, (
        "at the node's size its last widget should end below its Widgets tab, "
        f"which is what makes the tab's scrollbar matter: {last}"
    )

    # 2. The Data Catalog's column and the Widgets tab draw the rule's bar at
    #    rest, and the Widgets tab's own bar takes its 6 px beside its rows.
    seen = {"the Data Catalog's content column": catalog, TAB: panel.evaluate(_SCROLLBAR_JS)}
    wanted = {
        name: {
            **drawn,
            "width": catalog["width"],
            "color": catalog["color"],
            "bar": BAR_PX,
            "webkit_width": f"{BAR_PX}px",
            "thumb": THUMB,
            "own": BAR_PX if drawn["scrolls"] else 0,
        }
        for name, drawn in seen.items()
    }
    wanted[TAB].update(scrolls=True, own=BAR_PX)
    assert seen == wanted, (
        f"a panel does not draw the shared scrollbar at rest ({BAR_PX} px beside the content, "
        f"thumb {THUMB}), as the Data Catalog's content column should: {seen}"
    )

    # 3. Scrolled down, the last widget shows.
    panel.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    scrolled = panel.evaluate(_LAST_ROW_JS)
    assert scrolled["below"] <= 1, (
        f"scrolled to the bottom, the Widgets tab still cuts its last widget: {scrolled}"
    )
