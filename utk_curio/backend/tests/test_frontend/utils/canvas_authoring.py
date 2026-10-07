"""Author a canvas by hand: drag a node in, connect it, give it code, run it."""

import re
import time

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    expect,
)

from .run_all import wait_for_run_guard_released
from .screenshots import park_pointer


# ---------------------------------------------------------------------------
# Canvas authoring helpers (drag a node in, connect it, give it code, run it)
# ---------------------------------------------------------------------------
#
# Everything above builds a canvas by *loading* a dataflow (a Trill JSON through
# the File menu, or a spec seeded into the DB). These helpers cover the other
# half: what a user does by hand. They are deliberately DOM/event driven rather
# than store driven, because the two are not equivalent -
# ``window.__curio_reactFlow.setNodes`` writes only React Flow's zustand store,
# and ReactFlow's ``useStoreUpdater`` pushes the provider's node array straight
# back over it on the next render, so a node (or a code edit) injected that way
# silently disappears.

CANVAS_DROP_TARGET = ".curio-canvas-drop-target"

# One HTML5 drag, start to finish, on the elements the app actually listens to.
#
# ``dragstart`` has to be fired on the SOURCE, not just the drop constructed by
# hand: the built-in tiles and the package palette rows put their payload on
# ``dataTransfer`` inside their own ``onDragStart``, and dataset rows go further
# and stash the payload in a module singleton via ``beginDatasetDrag`` (the
# canvas reads that singleton in preference to ``getData``, because custom MIME
# types do not round-trip reliably). Skipping ``dragstart`` therefore drops an
# empty payload, which ``handleDrop`` ignores without a word.
_DRAG_TO_CANVAS_JS = r"""({ source, targetSelector, clientX, clientY }) => {
    const target = document.querySelector(targetSelector);
    if (!target) return `no drop target matching ${targetSelector}`;
    // The identifying attribute and the draggable element are not always the
    // same node: a dataset palette row carries data-dataset-id on its wrapper
    // and puts onDragStart on an inner grip, so dispatching on the wrapper
    // would fire nothing (events bubble up, never down). Built-in tiles and
    // package rows are themselves draggable, so this resolves to the element
    // itself for them.
    const dragSource = source.hasAttribute("draggable")
        ? source
        : source.querySelector("[draggable]");
    if (!dragSource) return "source has no draggable element";
    const dataTransfer = new DataTransfer();
    const fire = (el, type, coords) => {
        el.dispatchEvent(new DragEvent(type, {
            bubbles: true,
            cancelable: true,
            dataTransfer,
            ...(coords || {}),
        }));
    };
    const coords = { clientX, clientY };
    fire(dragSource, "dragstart", coords);
    // dragover before drop: handleDragOver is where the canvas sets dropEffect,
    // and a dataset drag ("copy") is refused outright by a browser that saw
    // effectAllowed "move".
    fire(target, "dragover", coords);
    fire(target, "drop", coords);
    fire(dragSource, "dragend", coords);
    return "ok";
}"""


def edge_client_point(page, *, on_miss=None) -> tuple[float, float] | None:
    """A point that ``pickEdgeAtPoint`` will actually resolve to an edge.

    React Flow draws a wide invisible ``.react-flow__edge-interaction`` path
    under every edge precisely so a pointer can land on a curve, and
    ``pickEdgeAtPoint`` hit-tests it with ``elementFromPoint``
    (``agentCatalogEvents.ts``). Two things make the obvious "take the midpoint"
    version wrong:

    * a bezier's bounding-box centre is usually empty space, so the point has to
      come from ``getPointAtLength`` on the path itself; and
    * the open agent palette is a ~545px strip floating *over* the left of the
      canvas, so a point that is geometrically on the edge can still be occluded
      - and ``elementFromPoint`` would return the palette, which resolves to no
      edge and silently attaches to the canvas instead.

    So this samples along the curve and returns the first point that
    ``elementFromPoint`` resolves to an edge, which is the same question the drop
    handler asks. ``None`` means no such point exists right now, and the caller
    skips the beat rather than recording a mislabelled one.

    "The same question" is meant literally, and it has to be kept that way: an
    edge that already carries agent badges resolves through them as well as
    through its own group (``EDGE_AGENT_BADGES_ATTR``, #296), because the badges
    sit on React Flow's label layer and cover the midpoint this walk starts
    from. Before that branch was mirrored here, every caller on a canvas with a
    connection agent attached simply found nothing and skipped.
    """
    point = page.evaluate(
        """() => {
            const path = document.querySelector(
                '.react-flow__edge .react-flow__edge-interaction'
            ) || document.querySelector('.react-flow__edge path');
            if (!path || !path.getPointAtLength) return null;
            const total = path.getTotalLength();
            if (!total) return null;
            const svg = path.ownerSVGElement;
            const ctm = path.getScreenCTM();
            const rf = window.__curio_reactFlow;
            if (!svg || !ctm || !rf) return null;

            const toFlow = (x, y) => (
                rf.screenToFlowPosition
                    ? rf.screenToFlowPosition({ x, y })
                    : rf.project({ x, y })
            );
            // handleDrop's precedence, restated: pickNodeAtPoint runs first and
            // a hit there wins, so a point that is visually on the curve still
            // attaches to a NODE if it falls inside that node's box. React
            // Flow's boxes are generous - a node is 525x350 - and the bezier
            // dips back over them near its ends.
            const nodes = rf.getNodes();
            const insideANode = (flow) => nodes.some((n) => {
                const o = n.positionAbsolute ?? n.position;
                if (!o) return false;
                const w = n.width ?? 0;
                const h = n.height ?? 0;
                return flow.x >= o.x && flow.x <= o.x + w
                    && flow.y >= o.y && flow.y <= o.y + h;
            });

            // Walk outwards from the midpoint, which is the part of the curve
            // furthest from both node bodies.
            const fractions = [
                0.5, 0.48, 0.52, 0.45, 0.55, 0.42, 0.58, 0.4, 0.6, 0.35, 0.65,
                0.3, 0.7, 0.25, 0.75, 0.2, 0.8,
            ];
            for (const f of fractions) {
                const at = path.getPointAtLength(total * f);
                const pt = svg.createSVGPoint();
                pt.x = at.x;
                pt.y = at.y;
                const screen = pt.matrixTransform(ctm);
                const hit = document.elementFromPoint(screen.x, screen.y);
                if (!hit || !hit.closest) continue;
                // Occluded (the palette strip floats over the pane), so
                // pickEdgeAtPoint would miss it. An edge's own agent badges are
                // NOT occlusion: pickEdgeAtPoint resolves them back to their
                // edge, so a point on them is a real drop target for it.
                if (!hit.closest('.react-flow__edge')
                    && !hit.closest('[data-curio-edge-badges]')) continue;
                // Inside a node's box, so pickNodeAtPoint would claim it first.
                if (insideANode(toFlow(screen.x, screen.y))) continue;
                return { point: [screen.x, screen.y] };
            }
            // Nothing qualified. Hand back what was measured so the caller can
            // say why rather than just skipping the beat.
            const mid = path.getPointAtLength(total / 2);
            const mpt = svg.createSVGPoint();
            mpt.x = mid.x;
            mpt.y = mid.y;
            const mscreen = mpt.matrixTransform(ctm);
            const hit = document.elementFromPoint(mscreen.x, mscreen.y);
            return { why: {
                midScreen: [Math.round(mscreen.x), Math.round(mscreen.y)],
                midFlow: toFlow(mscreen.x, mscreen.y),
                topmost: hit ? (hit.className && hit.className.baseVal !== undefined
                    ? hit.className.baseVal : String(hit.className || hit.tagName)) : null,
                nodes: nodes.map((n) => {
                    const o = n.positionAbsolute ?? n.position;
                    return { id: n.id, x: o && o.x, y: o && o.y,
                             w: n.width, h: n.height };
                }),
            } };
        }"""
    )
    if not point:
        return None
    if point.get("point"):
        found = point["point"]
        return (found[0], found[1])
    if on_miss is not None:
        on_miss(point.get("why"))
    return None


def canvas_nodes(page) -> list[dict]:
    """Every node on the canvas as ``{"id", "nodeType"}``.

    Projected, not returned raw: ``node.data`` holds a ``PythonInterpreter``
    instance and the ``outputCallback`` / ``propagationCallback`` closures, and
    Playwright cannot serialize either, so handing back the real nodes fails
    with an unhelpful "Unexpected value" from inside evaluate().
    """
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)
    return page.evaluate(
        """() => window.__curio_reactFlow.getNodes().map((n) => ({
            id: n.id,
            nodeType: (n.data && n.data.nodeType) || null,
        }))"""
    )


def canvas_node_type(page, node_id: str) -> str | None:
    """The ``data.nodeType`` of one canvas node.

    Every node renders as the single React Flow type ``__curioUniversalNode``,
    so the DOM cannot tell a loader from a transformation; the real kind only
    exists in node data.
    """
    for node in canvas_nodes(page):
        if node["id"] == node_id:
            return node["nodeType"]
    return None


def node_locator(page, node_id: str):
    """Return a Playwright ``Locator`` for a ReactFlow node element."""
    return page.locator(f'.react-flow__node[data-id="{node_id}"]')


def enable_save_output(page, node_id: str) -> None:
    """Turn on one node's save-output toggle, so running it leaves a dataset.

    The database-icon switch beside the play button, and it is **off by
    default** (``CURIO_DEFAULT_SAVE_NODE_OUTPUT``, documented in
    ``docs/DATA-CATALOG.md``). With it off a run writes a parquet under
    ``.curio/data/`` and stops there: ``routes.py`` gates the auto-install on
    ``save_output_dataset``, so no ``computed.<dataflow>.<node>@1`` is ever
    installed into the account store.

    A test that runs a producing node and then looks for its dataset in a
    catalog therefore has to flip this first. Three catalog tests did not, and
    passed anyway for years because the per-user store outlived ``reset-db`` and
    held 37 ``computed.*`` rows from earlier runs - a ``computed.``-prefixed
    card was always there to find, just never this test's.

    Clicks the label rather than the input: the checkbox is visually hidden by
    ``SaveOutputToggle.module.css``, so ``check()`` fails actionability. Scoped
    inside the node because the id is built from Curio's ``data.nodeId``, which
    a caller holding React Flow's ``data-id`` cannot assume it has.
    """
    node = node_locator(page, node_id)
    box = node.locator('input[id^="save-output-"]').first
    box.wait_for(state="attached", timeout=15000)
    if box.is_checked():
        return
    node.locator('label:has(input[id^="save-output-"])').first.click()
    expect(box).to_be_checked(timeout=10000)


def save_dataflow(page, *, timeout: float = 30000) -> dict:
    """Save the open dataflow through the File menu, and wait for the write.

    Gates on the write itself rather than on the File menu closing: the menu can
    close before the PUT is answered, and a test that then reads the server sees
    the pre-save spec. Returns the saved project as the server answered it.
    """
    file_btn = page.get_by_role("button", name=re.compile("File"))
    file_btn.wait_for(state="visible", timeout=15000)
    file_btn.click(force=True)
    save_btn = page.get_by_role("button", name="Save dataflow", exact=True)
    save_btn.wait_for(state="visible", timeout=10000)
    with page.expect_response(
        lambda r: "/api/projects" in r.url
        and r.request.method in ("POST", "PUT")
        and r.ok,
        timeout=timeout,
    ) as saved:
        save_btn.click()
    save_btn.wait_for(state="hidden", timeout=timeout)
    return saved.value.json()


# True once the canvas header shows what a save leaves on it: the save icon
# reads saved, the Data Catalog button is no longer fetching its count, and,
# when the save gave the dataflow automatic categories, their chips are drawn.
# From the click on Save until the response is handled the icon reads saving,
# and the render that handles it both sets saved and starts the catalog
# refetch, which marks the button busy until the new count is in. So "saved
# and not busy" holds only once this save's count has landed, even when the
# header already showed an earlier save.
_HEADER_SHOWS_SAVE_JS = """(wantAutoChips) => {
    const save = document.querySelector('[data-curio-save-state]');
    const catalog = document.querySelector('#datasets-palette button[aria-busy]');
    if (!save || save.getAttribute('data-curio-save-state') !== 'saved') return false;
    if (!catalog || catalog.getAttribute('aria-busy') !== 'false') return false;
    if (!wantAutoChips) return true;
    return !!document.querySelector(
        '[data-curio-canvas-title] [data-curio-category-chip="auto"]');
}"""


def save_dataflow_and_settle_header(page, *, timeout: float = 30000) -> dict:
    """Save the open dataflow, then wait until the header shows the save.

    Three things in the canvas header change only when a save lands: the save
    icon (``data-curio-save-state``), the automatic category chips (the save
    response's ``categories``) and the Data Catalog count (refetched once the
    save is answered). A frame captured without a save shows whichever of them
    the 30 s autosave had reached, so the same frame came out saved on one run
    and unsaved on the next (issue #584).

    Leaves the pointer parked: the File menu's Save row sits over the title and
    its category chips, and a chip under the pointer is drawn hovered.
    Returns the saved project as the server answered it.
    """
    detail = save_dataflow(page, timeout=timeout)
    park_pointer(page)
    settle_header_after_save(page, detail, timeout=timeout)
    return detail


def settle_header_after_save(page, saved_project: dict, *, timeout: float = 30000) -> None:
    """Wait until the canvas header shows the save that answered *saved_project*.

    For a save made any way (File menu, status icon): the save icon, the Data
    Catalog count and, when the save gave the dataflow automatic categories,
    their chips.
    """
    categories = saved_project.get("categories") or {}
    auto = categories.get("auto") or {}
    want_auto_chips = bool(
        categories.get("source") or auto.get("tags") or auto.get("data_type")
    )
    try:
        page.wait_for_function(_HEADER_SHOWS_SAVE_JS, arg=want_auto_chips, timeout=timeout)
    except PlaywrightTimeoutError:
        seen = page.evaluate(_HEADER_STATE_JS)
        raise AssertionError(
            f"the header never showed the save within {timeout / 1000:.0f} s: {seen} "
            f"(automatic category chips expected: {want_auto_chips})"
        ) from None


_HEADER_STATE_JS = """() => ({
    saveState: document.querySelector('[data-curio-save-state]')
        ?.getAttribute('data-curio-save-state') ?? null,
    catalogBusy: document.querySelector('#datasets-palette button[aria-busy]')
        ?.getAttribute('aria-busy') ?? null,
    autoChips: document.querySelectorAll(
        '[data-curio-canvas-title] [data-curio-category-chip="auto"]').length,
})"""


def assert_header_shows_save(page) -> None:
    """Fail unless the canvas header shows a landed save right now.

    No wait, on purpose: a frame taken without a save shows "Unsaved", or
    whatever the 30 s autosave last left, and only a check made at the moment
    of the capture tells the two apart.
    """
    seen = page.evaluate(_HEADER_STATE_JS)
    assert seen["saveState"] == "saved" and seen["catalogBusy"] == "false", (
        f"the header does not show a landed save at capture time: {seen}"
    )


def frame_node(page, node_id: str, *, zoom: float = 0.9,
               settle_ms: float = 1000) -> None:
    """Pan and zoom the canvas so one node fills the frame.

    For scenes whose subject is *inside* a node. The baseline harness fits the
    viewport to the whole dataflow, which is right for a scene about the graph
    and wrong for one about a chart: at fit zoom a 525x350 node is a ~90x60
    thumbnail, and a screenshot of it cannot show what the scene claims. The
    `05-vega-lite-multi-view-drilldown` example has 28 nodes, so its captures
    were two near-identical canvas wallpapers.

    Keeps the full 1280x720 frame rather than clipping to the node, so the
    surrounding canvas still reads as context.

    ``window.__curio_reactFlow`` is the instance ``MainCanvas.tsx`` exposes for
    exactly this; ``setCenter`` takes flow coordinates, hence the node's own
    position plus half its measured size.
    """
    page.evaluate(
        """({ nodeId, zoom }) => {
            const rf = window.__curio_reactFlow;
            if (!rf) return;
            const node = rf.getNodes().find((n) => n.id === nodeId);
            if (!node) return;
            const w = node.width || node.measured?.width || 525;
            const h = node.height || node.measured?.height || 350;
            rf.setCenter(node.position.x + w / 2, node.position.y + h / 2, {
                zoom, duration: 700,
            });
        }""",
        {"nodeId": node_id, "zoom": zoom},
    )
    page.wait_for_timeout(settle_ms)


def drag_to_canvas(page, source, *, at: tuple[float, float] | None = None,
                   timeout: float = 15000) -> str:
    """Drag *source* onto the canvas and return the id of the node it created.

    *source* is a locator for anything draggable that the canvas accepts: a
    built-in palette tile (``#tile-data-transformation``), a package palette row
    (``[data-pkg-template-id="..."]``), or a dataset row/card
    (``[data-dataset-id="..."]``). *at* is an offset from the pane's top-left
    corner; the pane centre is used when omitted.

    Mind the geometry when dropping more than one node: a node renders 525x350
    at zoom 1, so offsets less than ~600px apart horizontally overlap, and the
    later node's body then covers the earlier one's connection handle. In a
    1280x720 viewport, ``(150, 150)`` and ``(760, 150)`` is a pair that leaves
    both facing handles exposed.

    Ids are ``uuid4`` and assigned inside ``createCodeNode``, so the only way to
    learn the new one is to diff the canvas before and after.
    """
    before = {node["id"] for node in canvas_nodes(page)}

    # Wait for the drag SOURCE too, not just the drop target. A tile that is
    # attached but not yet interactive produces an empty dataTransfer payload,
    # and the drop then silently creates nothing - which surfaces much later as
    # the "Drop produced no node" assertion below, blaming the canvas.
    source.wait_for(state="visible", timeout=timeout)

    pane = page.locator(CANVAS_DROP_TARGET)
    pane.wait_for(state="visible", timeout=timeout)
    box = pane.bounding_box()
    assert box, f"{CANVAS_DROP_TARGET} has no layout box"
    if at is None:
        client_x = box["x"] + box["width"] / 2
        client_y = box["y"] + box["height"] / 2
    else:
        client_x = box["x"] + at[0]
        client_y = box["y"] + at[1]

    source.wait_for(state="visible", timeout=timeout)
    source.scroll_into_view_if_needed()
    result = page.evaluate(
        _DRAG_TO_CANVAS_JS,
        {
            "source": source.element_handle(),
            "targetSelector": CANVAS_DROP_TARGET,
            "clientX": client_x,
            "clientY": client_y,
        },
    )
    assert result == "ok", f"drag to canvas failed: {result}"

    try:
        page.wait_for_function(
            "(n) => window.__curio_reactFlow.getNodes().length > n",
            arg=len(before),
            timeout=timeout,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            "Drop produced no node. Either the drag payload was empty (the "
            "source's own onDragStart did not run) or the canvas is refusing "
            "drops (a shared read-only view)."
        ) from None

    created = [n for n in canvas_nodes(page) if n["id"] not in before]
    assert len(created) == 1, (
        f"expected exactly one new node, got {created}"
    )
    node_id = created[0]["id"]
    node_locator(page, node_id).wait_for(state="visible", timeout=timeout)
    return node_id


# An element, named for a failure message: its tag, then its aria-label or its
# first class.
_NAME_ELEMENT_JS = r"""(el) => {
    if (!el || !el.tagName) return null;
    const label = el.getAttribute("aria-label");
    const cls = typeof el.className === "string" ? el.className.split(" ")[0] : "";
    return el.tagName.toLowerCase() + (label ? `[aria-label="${label}"]` : cls ? `.${cls}` : "");
}"""

# What a mouse drag did, recorded on the window in the capture phase so that
# nothing the app does can hide it: whether it started, which element took the
# drop (none when no element accepted it), and the drop effect it ended with.
_WATCH_MOUSE_DRAG_JS = r"""() => {
    const name = """ + _NAME_ELEMENT_JS + r""";
    const seen = { started: false, droppedOn: null, onCanvas: false, dropEffect: null };
    const onStart = () => { seen.started = true; };
    const onDrop = (event) => {
        seen.droppedOn = name(event.target);
        seen.onCanvas = !!(event.target.closest && event.target.closest(".curio-canvas-drop-target"));
    };
    const onEnd = (event) => {
        seen.dropEffect = event.dataTransfer ? event.dataTransfer.dropEffect : null;
        window.removeEventListener("dragstart", onStart, true);
        window.removeEventListener("drop", onDrop, true);
        window.removeEventListener("dragend", onEnd, true);
    };
    window.addEventListener("dragstart", onStart, true);
    window.addEventListener("drop", onDrop, true);
    window.addEventListener("dragend", onEnd, true);
    window.__curioMouseDrag = seen;
}"""

# The element a pointer at a client point reaches, named.
_ELEMENT_AT_JS = (
    "([x, y]) => (" + _NAME_ELEMENT_JS + ')(document.elementFromPoint(x, y)) || "nothing"'
)

# True when a press at the point lands on the grip's draggable element, and not
# on a control inside it (a button there takes the press as a click).
_PRESSES_ON_DRAGGABLE_JS = r"""(grip, [x, y]) => {
    const draggable = grip.closest('[draggable="true"]') || grip.querySelector('[draggable="true"]');
    const hit = document.elementFromPoint(x, y);
    return !!draggable && !!hit && draggable.contains(hit)
        && !hit.closest("button, a, input, select, textarea");
}"""


def drag_to_canvas_with_the_mouse(page, grip, *, at: tuple[float, float],
                                  timeout: float = 15000) -> str:
    """Drag with the mouse, as a person does, from *grip* onto the canvas, and
    return the id of the node the drop created.

    ``drag_to_canvas`` fires its drop on the pane itself, so nothing that lies
    over the canvas can stop it. A catalog drawer's scrim covers the whole
    window while the drawer is open, so only a real drag shows whether a card
    dragged out of the drawer reaches the canvas beneath it. This one presses,
    moves in steps and releases, and the browser decides where each event goes.

    *grip* is where the press lands: an element of the draggable card or row
    that is not a control, such as a card's title or a palette row's drag grip.
    *at* is an offset from the pane's top-left corner, as for
    ``drag_to_canvas``. Fails with where the drop went when no node arrives.
    """
    before = {node["id"] for node in canvas_nodes(page)}
    grip.wait_for(state="visible", timeout=timeout)
    grip.scroll_into_view_if_needed()
    box = grip.bounding_box()
    pane = page.locator(CANVAS_DROP_TARGET)
    pane.wait_for(state="visible", timeout=timeout)
    pane_box = pane.bounding_box()
    assert box and pane_box, "the grip or the canvas has no layout box"
    start = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    target = (pane_box["x"] + at[0], pane_box["y"] + at[1])
    width, height = page.evaluate("() => [window.innerWidth, window.innerHeight]")
    for point, what in ((start, "the press"), (target, "the drop")):
        assert 0 <= point[0] < width and 0 <= point[1] < height, (
            f"{what} at ({point[0]:.0f}, {point[1]:.0f}) is outside the {width}x{height} window"
        )
    assert grip.evaluate(_PRESSES_ON_DRAGGABLE_JS, list(start)), (
        f"a press at ({start[0]:.0f}, {start[1]:.0f}) does not land on the grip's draggable "
        f"element but on {page.evaluate(_ELEMENT_AT_JS, list(start))}"
    )
    # What a pointer at the drop point reaches before the drag: the canvas, or
    # whatever lies over it there.
    over_the_target = page.evaluate(_ELEMENT_AT_JS, list(target))

    page.evaluate(_WATCH_MOUSE_DRAG_JS)
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(start[0] - 40, start[1] + 10, steps=6)
    try:
        page.wait_for_function("() => window.__curioMouseDrag.started", timeout=5000)
    except PlaywrightTimeoutError:
        page.mouse.up()
        raise AssertionError(
            f"pressing at ({start[0]:.0f}, {start[1]:.0f}) and moving started no drag"
        ) from None
    page.mouse.move(*target, steps=12)
    page.mouse.up()

    try:
        page.wait_for_function(
            "(n) => window.__curio_reactFlow.getNodes().length > n",
            arg=len(before),
            timeout=timeout,
        )
    except PlaywrightTimeoutError:
        seen = page.evaluate("() => window.__curioMouseDrag")
        dropped = f"landed on {seen['droppedOn']}" if seen["droppedOn"] else "was taken by no element"
        raise AssertionError(
            f"the drag to ({target[0]:.0f}, {target[1]:.0f}) made no node: its drop {dropped} "
            f"(drop effect {seen['dropEffect']!r}), and before the drag a pointer there "
            f"reached {over_the_target}"
        ) from None

    created = [n for n in canvas_nodes(page) if n["id"] not in before]
    seen = page.evaluate("() => window.__curioMouseDrag")
    assert (len(created), seen["onCanvas"]) == (1, True), (
        f"expected one new node from a drop on the canvas, got {created} from a drop on "
        f"{seen['droppedOn']}"
    )
    node_id = created[0]["id"]
    node_locator(page, node_id).wait_for(state="attached", timeout=timeout)
    return node_id


# Monaco is bundled and pinned on ``window`` by index.tsx, so the editor
# instance is reachable; it is found by DOM containment because a canvas holds
# one editor per code node and ``getEditors()`` returns all of them.
_SET_NODE_CODE_JS = r"""({ nodeId, code }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    if (!nodeEl) return "node is not on the canvas";
    const editorEl = nodeEl.querySelector(".monaco-editor");
    if (!editorEl) return "node has no code editor";
    const editors = (window.monaco && window.monaco.editor
        && window.monaco.editor.getEditors && window.monaco.editor.getEditors()) || [];
    const match = editors.find((e) => editorEl.contains(e.getDomNode()));
    if (!match) return "no monaco instance owns this node's editor";
    match.setValue(code);
    return "ok";
}"""

_NODE_CODE_IS_JS = r"""({ nodeId, code }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
    if (!editorEl) return false;
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const match = editors.find((e) => editorEl.contains(e.getDomNode()));
    return !!match && match.getValue() === code;
}"""


def set_node_code(page, node_id: str, code: str, *, timeout: float = 15000) -> None:
    """Replace a code node's source with *code*.

    Goes through Monaco's ``setValue``, which fires
    ``onDidChangeModelContent`` -> ``handleCodeChange`` -> ``setCode`` ->
    ``floatCode`` -> ``data.code``. That last hop is the only thing that
    publishes editor text to the node, so this is the same path a keystroke
    takes rather than a back door around it.

    Do not reach for ``page.keyboard.type`` instead: the editor runs with
    ``autoClosingBrackets: "always"`` and ``formatOnType: true``, so typed
    Python comes back with extra brackets and re-indentation and never
    round-trips.
    """
    node_el = node_locator(page, node_id)
    node_el.scroll_into_view_if_needed()
    # The pane stays mounted when inactive, so the editor exists either way,
    # but activating the tab keeps a failure legible in --headed runs.
    code_tab = node_el.locator('.nav-link[data-rr-ui-event-key="code"]').first
    try:
        code_tab.wait_for(state="visible", timeout=2000)
        if "active" not in (code_tab.get_attribute("class") or ""):
            code_tab.dispatch_event("click")
    except PlaywrightTimeoutError:
        pass
    node_el.locator(".monaco-editor").first.wait_for(state="visible", timeout=timeout)

    deadline = time.time() + timeout / 1000
    result = None
    while True:
        result = page.evaluate(_SET_NODE_CODE_JS, {"nodeId": node_id, "code": code})
        if result == "ok" or time.time() >= deadline:
            break
        page.wait_for_timeout(250)
    assert result == "ok", f"could not set code on node {node_id}: {result}"

    # setValue is synchronous but the React round-trip to data.code is not, so
    # confirm the editor is actually holding the new text before running it.
    page.wait_for_function(
        _NODE_CODE_IS_JS, arg={"nodeId": node_id, "code": code}, timeout=timeout
    )


def read_node_code(page, node_id: str, *, timeout: float = 15000) -> str:
    """Return the Python/JS source a code node currently holds.

    Reads Monaco rather than ``data.code`` because the editor is what the run
    actually sends, and because node data cannot be serialized out of the page
    (see ``canvas_nodes``).
    """
    node_el = node_locator(page, node_id)
    node_el.locator(".monaco-editor").first.wait_for(state="attached", timeout=timeout)
    code = page.evaluate(
        """(nodeId) => {
            const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
            const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
            if (!editorEl) return null;
            const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
            const match = editors.find((e) => editorEl.contains(e.getDomNode()));
            return match ? match.getValue() : null;
        }""",
        node_id,
    )
    assert code is not None, f"could not read code from node {node_id}"
    return code


def _handle_locator(page, node_id: str, handle_id: str):
    return page.locator(
        f'.react-flow__node[data-id="{node_id}"] '
        f'.react-flow__handle[data-handleid="{handle_id}"]'
    )


def connect_nodes(page, source_id: str, target_id: str, *,
                  source_handle: str = "out", target_handle: str = "in",
                  timeout: float = 15000) -> str:
    """Drag an edge from *source_id*'s output handle to *target_id*'s input.

    Returns the edge id, which React Flow derives deterministically as
    ``reactflow__edge-<source><sourceHandle>-<target><targetHandle>``.

    Uses real pointer moves rather than a synthetic event pair, because React
    Flow tracks a connection through pointermove on the pane and never sees a
    lone pointerup on the target handle. The intermediate moves matter for the
    same reason. Coordinates come from ``bounding_box()`` so the viewport's CSS
    transform is already baked in.
    """
    src = _handle_locator(page, source_id, source_handle)
    tgt = _handle_locator(page, target_id, target_handle)
    for locator, node_id, handle_id in (
        (src, source_id, source_handle), (tgt, target_id, target_handle)
    ):
        try:
            locator.wait_for(state="visible", timeout=timeout)
        except PlaywrightTimeoutError:
            raise AssertionError(
                f"node {node_id} has no {handle_id!r} handle - check the "
                f"node type's manifest ports (a data-loading node has no "
                f"input, and a bidirectional node uses 'in/out')"
            ) from None
    src.scroll_into_view_if_needed()
    src_box, tgt_box = src.bounding_box(), tgt.bounding_box()
    assert src_box and tgt_box, "connection handles have no layout box"

    # React Flow starts and ends a connection by hit-testing whatever sits under
    # the pointer, so a handle that is merely *present* is not enough: if another
    # node's body overlaps it, mousedown lands on that instead and the whole drag
    # is a silent no-op. Check it up front, because the symptom otherwise is an
    # unexplained "no edge" 15 seconds later.
    for locator, node_id, handle_id in (
        (src, source_id, source_handle), (tgt, target_id, target_handle)
    ):
        covering = locator.evaluate(
            """(el) => {
                const r = el.getBoundingClientRect();
                const top = document.elementFromPoint(
                    r.x + r.width / 2, r.y + r.height / 2
                );
                if (!top) return "nothing (the handle is outside the viewport)";
                if (top === el || el.contains(top)) return null;
                return `<${top.tagName.toLowerCase()} class="${top.className}">`;
            }"""
        )
        if covering:
            raise AssertionError(
                f"node {node_id}'s {handle_id!r} handle is not the topmost "
                f"element at its own centre; {covering} is. Space the nodes "
                f"further apart when dropping them (a node is 525x350 at "
                f"zoom 1) or scroll the handle into view."
            )

    src_x = src_box["x"] + src_box["width"] / 2
    src_y = src_box["y"] + src_box["height"] / 2
    tgt_x = tgt_box["x"] + tgt_box["width"] / 2
    tgt_y = tgt_box["y"] + tgt_box["height"] / 2

    page.mouse.move(src_x, src_y)
    page.mouse.down()
    page.mouse.move(tgt_x, tgt_y, steps=16)
    # A second move on the spot: React Flow only marks a handle "connectable"
    # from a pointermove it receives while already over it.
    page.mouse.move(tgt_x, tgt_y)
    page.mouse.up()

    edge_id = (
        f"reactflow__edge-{source_id}{source_handle}-{target_id}{target_handle}"
    )
    try:
        page.wait_for_function(
            """({ source, target }) => (window.__curio_reactFlow.getEdges() || [])
                .some((e) => e.source === source && e.target === target)""",
            arg={"source": source_id, "target": target_id},
            timeout=timeout,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"no edge from {source_id} to {target_id} after the drag. A "
            f"rejected connection toasts instead of throwing (cycle, or "
            f"incompatible ports), so check the canvas for a toast."
        ) from None
    page.locator(f'[data-testid="rf__edge-{edge_id}"]').wait_for(
        state="attached", timeout=timeout
    )
    return edge_id


#: How long to wait for a browser download of an archive the server builds
#: on click (#334).
#:
#: Exporting a package or a dataset is not "save a file the browser already
#: has": the click makes the backend assemble a zip, and only then does
#: Chromium fire ``download``. On a shared runner under other jobs that took
#: longer than the 60 s these waits used to allow, so
#: ``test_save_export_import_and_run_package_nodes`` failed with
#: ``TimeoutError: ... waiting for event "download"`` on a branch that touched
#: neither export nor packaging.
#:
#: Raising the ceiling costs nothing when the machine is idle - the wait ends
#: when the event arrives, which is ~2 s locally - and it is the difference
#: between a red build and a slow one when it is not. A hang still fails,
#: two minutes later.
EXPORT_DOWNLOAD_TIMEOUT_MS = 120000

_HEAVY_NODE_TYPES = {
    "AUTK_GRAMMAR",
    "DATA_LOADING",
    "DATA_TRANSFORMATION",
    "COMPUTATION_ANALYSIS",
    # A model over every image of a collection: example 10's 40 photos.
    "IMAGE_SEGMENTATION",
}


def node_execution_timeout_ms(node_type: str) -> int:
    """Return a generous timeout for nodes that execute heavy data ops.

    AUTK_GRAMMAR shares the data-node budget: a node with a `data` section
    runs it in the backend sandbox - autk-db parses a local OSM PBF
    (multi-MB) via DuckDB-WASM in Node and round-trips the layers back over
    HTTP. This is deterministic and fast now that the data is local: a
    1.6 MB PBF (171k features) parses in ~12 s including cold-start WASM
    init, and the largest bundled PBF is ~6 MB, so 2 min is ~2.5x the
    worst case. The old 5-min budget dated from the Overpass era (a remote,
    throttled OSM endpoint), which has since been removed - a node that now
    runs past this budget is hung, not slow, so fail it.

    Accepts either the legacy uppercase name a ``NodeSpec`` carries
    (``DATA_LOADING``) or the namespaced id the frontend uses on the wire
    (``curio.builtin/data-loading``).
    """
    canonical = (node_type or "").rsplit("/", 1)[-1].split("@", 1)[0]
    canonical = canonical.replace("-", "_").upper()
    return 120000 if canonical in _HEAVY_NODE_TYPES else 30000


def read_node_error_text(node_el) -> str | None:
    """Return a failed node's error message, or ``None`` if it cannot be read.

    Two sources, in order:

    ``data-curio-node-error`` carries the message for EVERY node type, because
    it is rendered from the same output the status attribute reads. It is the
    only source for an AUTK_GRAMMAR node: the grammar editor has no output box,
    so an Autark failure used to reach this helper as ``None`` and an assertion
    read "execution failed with Error" with nothing after it (#318).

    Otherwise the inline output area, where CodeEditor renders any output
    (success or error) into the box carrying the ``[N]:`` counter — the
    sandbox's stderr/traceback for COMPUTATION_ANALYSIS / DATA_LOADING /
    DATA_TRANSFORMATION. We switch to the code tab so that area is in the
    layout, then read it.
    """
    try:
        attr = node_el.locator("[data-curio-node-error]").first
        if attr.count():
            text = attr.get_attribute("data-curio-node-error")
            if text and text.strip():
                return text
    except Exception:
        pass
    try:
        code_tab = node_el.locator(
            '.nav-link[data-rr-ui-event-key="code"]'
        ).first
        try:
            code_tab.wait_for(state="visible", timeout=2000)
            if "active" not in (code_tab.get_attribute("class") or ""):
                code_tab.click(force=True)
        except Exception:
            # Some autk nodes may not expose a code tab depending on
            # NodeEditor config; fall through and read whatever is
            # currently visible.
            pass
        output_area = node_el.locator("[data-curio-node-output]").first
        output_area.wait_for(state="visible", timeout=2000)
        return output_area.text_content()
    except Exception:
        return None


def read_node_output_text(page, node_id: str, *, timeout: float = 10000) -> str:
    """Return the text of a code node's inline output box.

    Reads ``[data-curio-node-output]`` rather than ``.nowheel.nodrag``: that
    class sits on the editor wrapper too, and the wrapper's ``textContent``
    starts with every line of code Monaco has rendered.

    The text is the Jupyter-style counter followed by the result, e.g.
    ``"[1]:Saved to file: xyz"`` or ``"[ ]:No output yet"``.
    """
    box = node_locator(page, node_id).locator("[data-curio-node-output]").first
    box.wait_for(state="visible", timeout=timeout)
    return box.text_content() or ""


def activate_header_icon(locator) -> None:
    """Press one of a node header's icon buttons (the pencil, the settings cog).

    Two reasons a normal click does not work here. The buttons activate on
    ``pointerdown`` + ``pointerup`` and deliberately swallow the native click
    (``useHeaderIconDragClick``, so that press-and-drag still moves the node),
    and app chrome overlaps the header band at the top of the canvas, which means
    a real click at the button's centre is delivered to the overlay instead.
    Dispatching the two pointer events skips hit-testing entirely, the same way
    the play button's ``dispatch_event("click")`` does.

    The drag threshold is satisfied for free: a dispatched event carries
    ``clientX``/``clientY`` of 0, so down and up read as the same point.
    """
    locator.wait_for(state="attached", timeout=15000)
    locator.dispatch_event("pointerdown")
    locator.dispatch_event("pointerup")


# Any of these proves the play click was honoured: the header swaps the play SVG
# for a spinner, the status attribute leaves "idle", or the inline counter flips
# from "[ ]:" to "[*]:".
_PLAY_ACKNOWLEDGED_JS = r"""(nodeId) => {
    const el = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    if (!el) return false;
    if (el.querySelector('.spinner-border')) return true;
    const status = el.querySelector('[data-curio-node-status]');
    if (status && status.getAttribute('data-curio-node-status') !== 'idle') return true;
    const texts = [...el.querySelectorAll('[data-curio-node-output], span')]
        .map(e => e.textContent);
    return texts.some(
        t => /\[(\d+|\*)\]:/.test(t) || /^(Running|Done|Error)$/.test(t.trim())
    );
}"""


def play_node(page, node_id: str, *, max_attempts: int = 3) -> None:
    """Click *play* on one node and confirm execution actually started.

    Note this runs the node's not-yet-successful ancestors too
    (``playNodesUpTo``), so playing the tail of a chain is enough to run it.

    We don't use ``play_btn.click(force=True)`` - ``force=True`` skips
    actionability checks so React Flow's transformed viewport, pointer
    events, or an overlay can swallow the click. And the button is an
    ``<svg>`` (FontAwesomeIcon), so ``SVGElement`` has no native ``click()``
    and calling it through evaluate raises ``TypeError``.
    ``dispatch_event("click")`` sends a bubbling synthetic ``MouseEvent``
    that React's onClick picks up regardless of where the element actually
    sits on screen.

    It first waits for any run already going to end. A click during one is
    refused with a toast, and a node that already reads Done would then pass
    the acknowledgement below on its previous run's output. A run on the server
    ends a moment after its last node shows its result.
    """
    wait_for_run_guard_released(page, timeout_ms=300000)
    node_el = node_locator(page, node_id)
    node_el.scroll_into_view_if_needed()
    play_btn = node_el.locator("svg.fa-circle-play")

    last_error = None
    for _ in range(max_attempts):
        try:
            play_btn.wait_for(state="visible", timeout=10000)
            play_btn.dispatch_event("click")
            try:
                page.wait_for_function(
                    _PLAY_ACKNOWLEDGED_JS, arg=node_id, timeout=20000
                )
                return
            except PlaywrightTimeoutError:
                last_error = TimeoutError("No spinner or counter-flip within 20s")
        except PlaywrightTimeoutError as e:
            last_error = e
    raise AssertionError(
        f"Node {node_id} never acknowledged Play after {max_attempts} "
        f"attempts; click is being silently dropped (React handler likely "
        f"not bound). Last error: {last_error}"
    )


def wait_for_node_settled(page, node_id: str, *, node_type: str = "",
                          timeout_ms: int | None = None) -> str:
    """Block until a node finishes and return ``"done"`` or ``"error"``.

    Use this when a *failure* is the expected outcome (a node that needs a
    library nobody installed yet, say). Prefer ``wait_for_node_done`` otherwise:
    it fails with the node's own error text instead of handing back a status
    string the caller has to remember to check.
    """
    budget = timeout_ms or node_execution_timeout_ms(node_type)
    node_el = node_locator(page, node_id)
    try:
        page.wait_for_function(
            """(nodeId) => {
                const el = document.querySelector(
                    `.react-flow__node[data-id="${nodeId}"] [data-curio-node-status]`
                );
                if (!el) return false;
                const status = el.getAttribute('data-curio-node-status');
                return status === 'done' || status === 'error';
            }""",
            arg=node_id,
            timeout=budget,
        )
    except PlaywrightTimeoutError:
        raise PlaywrightTimeoutError(
            f"Node {node_id} ({node_type or 'unknown type'}) timed out after "
            f"{budget} ms"
        ) from None
    return node_el.locator("[data-curio-node-status]").first.get_attribute(
        "data-curio-node-status"
    ) or "idle"


def wait_for_node_done(page, node_id: str, *, node_type: str = "",
                       timeout_ms: int | None = None) -> None:
    """Block until a node reports success, and fail loudly if it errors.

    Keys off ``data-curio-node-status`` rather than the header's "Done" /
    "Error" text, so the wait does not depend on that copy. A node that never
    settles is a hard timeout failure: there is no tolerance and no retry, since
    all data is local and deterministic.
    """
    status = wait_for_node_settled(
        page, node_id, node_type=node_type, timeout_ms=timeout_ms
    )
    if status == "error":
        detail = read_node_error_text(node_locator(page, node_id))
        raise AssertionError(
            f"Node {node_id} ({node_type or 'unknown type'}) execution failed "
            f"with Error"
            + (f"\n--- node error output ---\n{detail}" if detail else "")
        )


def run_node_and_wait(page, node_id: str, *, node_type: str = "",
                      timeout_ms: int | None = None) -> str:
    """``play_node`` + ``wait_for_node_done``, returning the output text."""
    play_node(page, node_id)
    wait_for_node_done(page, node_id, node_type=node_type, timeout_ms=timeout_ms)
    return read_node_output_text(page, node_id)


#: How often ``set_canvas_zoom`` reads the viewport back, in ms: on a timer,
#: never per animation frame.
_ZOOM_READ_MS = 100

# One read of set_canvas_zoom's wait. True once React Flow's viewport is the
# one asked for and the canvas draws it, for *reads* reads in a row. A view
# that got there and was then moved off is set again.
_ZOOM_HELD_JS = """({ zoom, reads }) => {
    const flow = window.__curio_reactFlow;
    const viewport = document.querySelector(".curio-canvas-drop-target .react-flow__viewport");
    if (!flow || !viewport) return false;
    const wait = window.__curio_zoomWait = window.__curio_zoomWait || { held: 0 };
    const at = flow.getViewport();
    const drawn = new DOMMatrixReadOnly(getComputedStyle(viewport).transform);
    const near = (a, b) => Math.abs(a - b) < 1e-4;
    const there = near(at.x, 0) && near(at.y, 0) && near(at.zoom, zoom)
        && near(drawn.e, 0) && near(drawn.f, 0) && near(drawn.a, zoom) && near(drawn.d, zoom);
    if (there) {
        wait.held += 1;
        return wait.held >= reads;
    }
    if (wait.held > 0) flow.setViewport({ x: 0, y: 0, zoom });
    wait.held = 0;
    return false;
}"""

_ZOOM_STATE_JS = """() => {
    const flow = window.__curio_reactFlow;
    const viewport = document.querySelector(".curio-canvas-drop-target .react-flow__viewport");
    return {
        viewport: flow ? flow.getViewport() : null,
        drawn: viewport ? getComputedStyle(viewport).transform : null,
    };
}"""


def set_canvas_zoom(page, zoom: float, *, timeout: float = 15000) -> None:
    """Pin the ReactFlow viewport so several nodes fit before dropping them.

    A node is 525x350 flow units, so at zoom 1 a 1280x720 viewport has room for
    two side by side and no more (see ``drag_to_canvas``). Zooming out first is
    what makes a three-node chain authorable by drag: the drop coordinates stay
    viewport-relative, but each node paints ``525 * zoom`` px wide, so the
    spacing needed to keep facing handles exposed shrinks with it.

    Returns once the canvas shows *zoom* at the origin. React Flow 11's
    ``setViewport`` moves through a d3 transition even with no duration, and a
    transition only advances on animation frames, so the view changes a frame
    or two after the call, or later on a runner short of frames, and a point
    read before then is read on the old view (``test_set_canvas_zoom_e2e.py``).
    So the viewport is read back every ``_ZOOM_READ_MS``, on a timer, until
    React Flow reports it and the page draws it for 3 reads in a row.

    Purely a camera change - node positions in flow space are unaffected, and
    ``save_workflow_test_screenshot`` re-pins its own fitView before capturing,
    so this does not influence a baseline.
    """
    page.wait_for_function(
        "() => !!window.__curio_reactFlow", polling=_ZOOM_READ_MS, timeout=timeout
    )
    page.evaluate("() => { delete window.__curio_zoomWait; }")
    page.evaluate(
        "(zoom) => window.__curio_reactFlow.setViewport({ x: 0, y: 0, zoom })",
        zoom,
    )
    try:
        page.wait_for_function(
            _ZOOM_HELD_JS,
            arg={"zoom": zoom, "reads": 3},
            polling=_ZOOM_READ_MS,
            timeout=timeout,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"the canvas did not show zoom {zoom} at the origin within {timeout:.0f} ms: "
            f"{page.evaluate(_ZOOM_STATE_JS)}"
        ) from None
    page.evaluate("() => { delete window.__curio_zoomWait; }")
