"""Node close-ups, compared tighter than a full page, and probes of the canvas
viewport's will-change hint.
"""

from contextlib import contextmanager

from playwright.sync_api import Page

from .screenshots import frame_nodes, save_workflow_test_screenshot


#: Per-channel tolerance of a node close-up. A map that drew nothing shows the
#: node's own gray (242, 242, 242), which is 10 per channel from the pale
#: background most Autark maps draw (232, 239, 242), so at the default 30 a
#: blank sparse map counted only its few features: 0.5% of the close-up in
#: proof run 36788122499. At 5 the same blank is 75%. Two CI captures of every
#: close-up were byte-identical or 0.02% apart at any tolerance (run 36788096514).
CLOSEUP_PIXEL_THRESHOLD = 5

#: Budget of a node close-up, tighter than MAX_DIFF_RATIO. A blank plot keeps
#: its panel and loses only its marks: the tallest-bar histogram blanked to
#: 9.27% and the scatter to 10.20% (proof run 36789368569), so at 10% one of
#: them passed. At 5% the smallest blank is 1.85 times the budget. GPU-computed
#: plots differ between GPUs: example 07's sunlight histogram is 4.29% apart on
#: an H100 and an RTX PRO 6000 (run 37082234799).
CLOSEUP_MAX_DIFF_RATIO = 0.05


# Sets the canvas viewport's inline will-change; "" hands it back to the stylesheet.
_VIEWPORT_WILL_CHANGE_JS = """(value) => {
    const viewport = document.querySelector('.react-flow__viewport');
    if (viewport) viewport.style.willChange = value;
}"""

# The page's own flow viewport is the first one: a flow drawn inside a node
# comes later in document order.
_VIEWPORT_COMPUTED_WILL_CHANGE_JS = """() => {
    const viewport = document.querySelector('.react-flow__viewport');
    return viewport ? getComputedStyle(viewport).willChange : null;
}"""

# Records whether the viewport ever took a will-change hint from now on: the
# hint comes with a class on the flow's wrapper (useViewportMotionHint).
_WATCH_VIEWPORT_HINT_JS = """() => {
    const flow = document.querySelector('.react-flow');
    const viewport = document.querySelector('.react-flow__viewport');
    window.__curio_viewport_hint_seen = [];
    if (window.__curio_viewport_hint_observer) window.__curio_viewport_hint_observer.disconnect();
    if (!flow || !viewport) return false;
    const observer = new MutationObserver(() => {
        window.__curio_viewport_hint_seen.push(getComputedStyle(viewport).willChange);
    });
    observer.observe(flow, { attributes: true, attributeFilter: ['class'] });
    window.__curio_viewport_hint_observer = observer;
    return true;
}"""

# A point beside a node where the pointer meets the bare pane, not a node, an
# edge or a menu: a press there pans, where a press on a node would drag it.
_EMPTY_PANE_POINT_JS = """(id) => {
    const pane = document.querySelector('.react-flow__pane');
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    if (!pane || !node) return null;
    const p = pane.getBoundingClientRect();
    const n = node.getBoundingClientRect();
    const midX = n.left + n.width / 2, midY = n.top + n.height / 2;
    for (let d = 20; d <= 600; d += 20) {
        for (const [x, y] of [[n.left - d, midY], [n.right + d, midY], [midX, n.top - d], [midX, n.bottom + d]]) {
            if (x < p.left + 5 || x > p.right - 5 || y < p.top + 5 || y > p.bottom - 5) continue;
            if (document.elementFromPoint(x, y) === pane) return { x, y };
        }
    }
    return null;
}"""

#: Long enough for a gesture to settle and drop the viewport's hint: d3 ends a
#: wheel gesture 150 ms after the last wheel event, and useViewportMotionHint
#: drops the hint 250 ms after the last move.
VIEWPORT_SETTLE_WAIT_MS = 1000


def empty_pane_point(page: Page, node_id: str) -> tuple[float, float]:
    """The nearest point beside *node_id* where a press lands on the bare pane."""
    point = page.evaluate(_EMPTY_PANE_POINT_JS, node_id)
    assert point, f"no bare pane in view beside node {node_id}"
    return point["x"], point["y"]


def viewport_will_change(page: Page) -> str | None:
    """The canvas viewport's computed ``will-change``: ``auto`` unless a gesture moves it."""
    return page.evaluate(_VIEWPORT_COMPUTED_WILL_CHANGE_JS)


def watch_viewport_hint(page: Page) -> None:
    """Start recording each ``will-change`` the viewport takes; read with ``viewport_hints``."""
    assert page.evaluate(_WATCH_VIEWPORT_HINT_JS), "no React Flow viewport on the page"


def viewport_hints(page: Page) -> list:
    """The computed ``will-change`` of the viewport at each change since ``watch_viewport_hint``."""
    return page.evaluate("() => window.__curio_viewport_hint_seen || []")


@contextmanager
def canvas_painted_at_shown_zoom(page: Page):
    """The canvas without a ``will-change`` hint while inside, for strict captures.

    The canvas viewport is a ``will-change: transform`` layer only while a
    pan or zoom gesture moves it (MainCanvas.css, useViewportMotionHint), and
    Chrome may keep such a layer painted at the zoom it had before a fit
    (#533): example 09's close-up once came out soft, its text and the map's
    tile seams 2.62% off the baseline (run 36791096981). The inline ``auto``
    keeps a node painted at the zoom it is shown at whatever the stylesheet
    says. Handing the hint back can start a fresh layer, so every capture
    compared against another one, on disk or in memory, belongs inside one
    block.
    """
    page.evaluate(_VIEWPORT_WILL_CHANGE_JS, "auto")
    try:
        yield
    finally:
        page.evaluate(_VIEWPORT_WILL_CHANGE_JS, "")


def save_node_closeup(
    page: Page,
    workflow_filepath: str,
    node_id: str,
    *,
    test_name: str,
    sweep_toasts: bool = False,
) -> str:
    """Compare one node, framed at up to 100% zoom, against its own baseline.

    For a node whose drawing is the claim: an Autark map or plot. In a
    full-page frame that node is a thumbnail, so one that drew nothing and
    left its body blank moves the frame by less than the 10% budget, and the
    comparison passes. Cropped to the node and compared at
    ``CLOSEUP_PIXEL_THRESHOLD`` against ``CLOSEUP_MAX_DIFF_RATIO``, the same
    blank is several times the budget.

    Leaves the viewport on the node; a later full-page capture fits it again.
    """
    with canvas_painted_at_shown_zoom(page):
        frame_nodes(page, [node_id])
        return save_workflow_test_screenshot(
            page,
            workflow_filepath,
            test_name=test_name,
            pixel_threshold=CLOSEUP_PIXEL_THRESHOLD,
            max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO,
            clip_selector=f'.react-flow__node[data-id="{node_id}"]',
            fit_reactflow=False,
            sweep_toasts=sweep_toasts,
            closeup=True,
        )
