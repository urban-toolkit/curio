"""Assertions on what a node drew: a Vega canvas, an Autark map or plot, an
empty state.
"""

import json
import time
from io import BytesIO

import allure
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .canvas_authoring import node_locator


# Shared by the wait_for_function poll and the final evaluate in
# ``assert_vega_canvas_rendered``; returns {width, height, nonBlank} or null.
VEGA_CANVAS_PROBE_JS = """(containerId) => {
    const el = document.getElementById(containerId);
    if (!el) return null;
    const canvas = el.querySelector('canvas');
    if (!canvas) return null;
    const w = canvas.width, h = canvas.height;
    if (!w || !h) return { width: w, height: h, nonBlank: false };
    let nonBlank = false;
    try {
        const ctx = canvas.getContext('2d');
        const { data } = ctx.getImageData(0, 0, w, h);
        for (let i = 0; i < data.length; i += 4) {
            const r = data[i], g = data[i + 1],
                  b = data[i + 2], a = data[i + 3];
            // any opaque, non-white pixel means a mark was drawn
            if (a !== 0 && !(r === 255 && g === 255 && b === 255)) {
                nonBlank = true;
                break;
            }
        }
    } catch (e) {
        // getImageData throws on a tainted canvas —
        // treat as drawn rather than failing.
        nonBlank = true;
    }
    return { width: w, height: h, nonBlank };
}"""


def assert_vega_canvas_rendered(
    page, node_id: str, *, timeout: float = 30000, expect_blank: bool = False
) -> None:
    """Assert a VIS_VEGA node actually drew marks from its upstream data.

    Vega-Lite renders to a ``<canvas>`` (the renderer switched from SVG in
    3a2a14a), so there is no DOM structure to diff - what can be checked is that
    the canvas exists, has a non-zero backing size, and is not blank. The
    container id is ``"vega" + nodeId``, a convention owned by ``useVega.ts``.

    Vega paints asynchronously after the canvas becomes visible, so on a slow
    runner the element can be attached and sized before any mark is drawn; a
    single pixel sample would race the paint. Poll until the probe reports drawn
    content, then take one final sample so a timeout still produces the detailed
    assertion message below rather than a bare Playwright timeout.

    ``expect_blank`` is for the handful of views that legitimately draw nothing:
    an empty frame, or a geometry column that is null in every row. There the
    canvas still has to exist and be sized, but demanding marks would assert the
    opposite of what the view is demonstrating.
    """
    container_id = f"vega{node_id}"
    node_el = node_locator(page, node_id)
    canvas = node_el.locator(f"#{container_id} canvas")
    canvas.first.wait_for(state="visible", timeout=15000)
    assert canvas.count() >= 1, (
        f"Vega node {node_id} is missing its rendered canvas inside "
        f"#{container_id}"
    )

    if not expect_blank:
        try:
            page.wait_for_function(
                "(containerId) => {"
                f" const probe = {VEGA_CANVAS_PROBE_JS};"
                "  const info = probe(containerId);"
                "  return !!(info && info.width > 0"
                "        && info.height > 0 && info.nonBlank);"
                "}",
                arg=container_id,
                timeout=timeout,
                polling=500,
            )
        except PlaywrightTimeoutError:
            pass

    info = page.evaluate(VEGA_CANVAS_PROBE_JS, container_id)
    assert info is not None, (
        f"Vega node {node_id}: could not find a canvas inside #{container_id}"
    )
    assert info["width"] > 0 and info["height"] > 0, (
        f"Vega node {node_id}: canvas has zero backing size "
        f"({info['width']}x{info['height']})"
    )
    if not expect_blank:
        assert info["nonBlank"], (
            f"Vega node {node_id}: canvas rendered blank, no chart marks drawn "
            f"from the upstream data"
        )


# An Autark map's canvas as it last drew, read after two animation frames. The
# id is autkGrammarBehavior's ``'autk-grammar-map-' + nodeId``.
_AUTK_MAP_PIXELS_JS = """async (id) => {
    const canvas = document.getElementById('autk-grammar-map-' + id);
    if (!canvas) return null;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return canvas.toDataURL('image/png');
}"""

# How the map canvas sits in the page: its box, the styles that could hide it,
# and what the page reports on top at its centre.
_AUTK_MAP_PLACEMENT_JS = """(id) => {
    const canvas = document.getElementById('autk-grammar-map-' + id);
    if (!canvas) return null;
    const box = canvas.getBoundingClientRect();
    const style = getComputedStyle(canvas);
    const top = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    const describe = (el) => el ? `${el.tagName.toLowerCase()}#${el.id}.${String(el.className).slice(0, 60)}` : null;
    return {
        box: [box.left, box.top, box.width, box.height],
        backing: [canvas.width, canvas.height],
        style: {display: style.display, visibility: style.visibility, opacity: style.opacity,
                position: style.position, zIndex: style.zIndex},
        topElement: describe(top),
        topIsCanvas: top === canvas,
    };
}"""


def assert_autark_map_drawn(
    page, node_id: str, *, timeout: float = 30000, attach_as: str = ""
) -> None:
    """Assert an Autark map node's canvas holds a drawn, opaque map.

    Read in the page, not from a screenshot. A drawn map is mostly opaque and
    holds more than 8 colours; a cleared canvas is transparent, and a
    background-only one holds one or two. With ``attach_as``, the Allure report
    gets the canvas pixels, the canvas as an element, viewport and full-page
    screenshot, and how the canvas is placed, so a map that drew but does not
    show can be told apart from one that did not draw.
    """
    import base64

    from PIL import Image

    deadline = time.monotonic() + timeout / 1000
    png, colours, opaque = None, 0, 0.0
    while True:
        url = page.evaluate(_AUTK_MAP_PIXELS_JS, node_id)
        if url:
            png = base64.b64decode(url.split(",", 1)[1])
            pixels = list(Image.open(BytesIO(png)).convert("RGBA").getdata())
            solid = [p[:3] for p in pixels if p[3] >= 250]
            opaque = len(solid) / max(1, len(pixels))
            colours = len(set(solid))
            if (colours > 8 and opaque > 0.5) or time.monotonic() >= deadline:
                break
        elif time.monotonic() >= deadline:
            break
        page.wait_for_timeout(500)
    if attach_as:
        if png:
            allure.attach(png, name=f"{attach_as}: canvas pixels", attachment_type=allure.attachment_type.PNG)
        canvas = page.locator(f"#autk-grammar-map-{node_id}")
        if canvas.count():
            allure.attach(canvas.first.screenshot(), name=f"{attach_as}: canvas screenshot",
                          attachment_type=allure.attachment_type.PNG)
        # The same moment as a viewport capture and as the full-page capture the
        # baselines use, which re-renders the page into a larger surface.
        page.evaluate("window.scrollTo(0, 0)")
        allure.attach(page.screenshot(), name=f"{attach_as}: viewport screenshot",
                      attachment_type=allure.attachment_type.PNG)
        allure.attach(page.screenshot(full_page=True), name=f"{attach_as}: full-page screenshot",
                      attachment_type=allure.attachment_type.PNG)
        placement = page.evaluate(_AUTK_MAP_PLACEMENT_JS, node_id)
        allure.attach(json.dumps({"opaqueShare": opaque, "opaqueColours": colours, "placement": placement}, indent=1),
                      name=f"{attach_as}: canvas placement", attachment_type=allure.attachment_type.JSON)
    assert png, f"Autark node {node_id} has no map canvas"
    assert colours > 8 and opaque > 0.5, (
        f"Autark node {node_id}: the map canvas is {opaque:.0%} opaque with {colours} opaque "
        f"colours, so no map was drawn"
    )


# An Autark node's drawing (its map canvas or plot div) and the node body it is
# shown in, in layout pixels, which the canvas zoom does not scale.
_AUTK_DRAWING_FIT_JS = """(id) => {
    const map = document.getElementById('autk-grammar-map-' + id);
    const drawing = map || document.getElementById('autk-grammar-plot-' + id);
    const pane = drawing && drawing.closest('.tab-pane');
    if (!pane) return null;
    return {
        kind: map ? 'map' : 'plot',
        drawing: [drawing.offsetWidth, drawing.offsetHeight],
        body: [pane.clientWidth, pane.clientHeight],
    };
}"""


def assert_autark_drawing_fits(page, node_id: str, *, timeout: float = 5000) -> None:
    """Assert an Autark node's map or plot fills its node body exactly.

    A drawing taller than the body runs on under the node's footer, where it
    cannot be seen or picked, and a map is then centred below the middle of
    what shows (#534). A node with no drawing is left to the checks that
    expect one.
    """
    deadline = time.monotonic() + timeout / 1000
    while True:
        fit = page.evaluate(_AUTK_DRAWING_FIT_JS, node_id)
        if fit is None:
            return
        shown = min(fit["body"]) > 0
        fits = shown and all(abs(d - b) <= 1 for d, b in zip(fit["drawing"], fit["body"]))
        if fits or time.monotonic() >= deadline:
            break
        page.wait_for_timeout(250)
    (dw, dh), (bw, bh) = fit["drawing"], fit["body"]
    assert shown, f"Autark node {node_id}: its {fit['kind']} is in an output tab that is not shown"
    assert fits, (
        f"Autark node {node_id}: its {fit['kind']} is {dw}x{dh} px in a {bw}x{bh} px "
        f"node body, so it does not fill the body"
        + (f" and {dh - bh} px of it are hidden" if dh > bh else "")
    )


def assert_vega_node_empty_state(page, node_id: str, reason: str, *, timeout: float = 30000) -> None:
    """Assert a VIS_VEGA node explains why it has nothing to draw.

    The counterpart to ``assert_vega_canvas_rendered``: some specs cannot be
    drawn at all, and the node is supposed to say so in its body rather than
    leave a blank rectangle behind (#224). ``useVega`` marks the container with
    ``data-curio-node-empty="<reason>"``, so the assertion is on the reason
    rather than merely on the presence of some text.
    """
    marker = page.locator(f'#vega{node_id}[data-curio-node-empty="{reason}"]')
    marker.wait_for(state="attached", timeout=timeout)
    assert marker.count() == 1, (
        f"Vega node {node_id}: expected the node body to report "
        f"{reason!r}, found nothing"
    )
    text = page.locator(f"#vega{node_id}").inner_text().strip()
    assert text, (
        f"Vega node {node_id}: reported {reason!r} but rendered no message for "
        f"the user to read"
    )
