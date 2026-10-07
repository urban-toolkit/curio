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


#: A framed map's drawing spans at least this share of its canvas along one
#: axis. The camera fits the layers' extent with 8% to spare, about 93% of the
#: canvas along the side that limits it; autk-map's own view, 10,000 world
#: units up, left example 24's Loop at 5% to 9% of it.
AUTK_MAP_MIN_FRAMED_SPAN = 0.75


def autark_map_framing(page, node_id: str, *, min_span: float = AUTK_MAP_MIN_FRAMED_SPAN,
                       timeout: float = 5000) -> str | None:
    """Why an Autark map is not framed on what it draws, or None when it is (#773).

    The drawing is the box of the canvas pixels that differ from its top-left
    corner, which a framed map leaves to the map's background. A framed map's
    drawing spans at least *min_span* of the canvas along one axis and leaves
    the background showing at both ends of that axis: neither a speck in the
    middle nor a crop that runs past the canvas's edges. Read in the page, as
    ``assert_autark_map_drawn`` reads the map.
    """
    import base64

    from PIL import Image, ImageChops

    deadline = time.monotonic() + timeout / 1000
    while True:
        problem = None
        url = page.evaluate(_AUTK_MAP_PIXELS_JS, node_id)
        if not url:
            problem = f"Autark node {node_id} has no map canvas"
        else:
            image = Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
            width, height = image.size
            # A pixel is drawn when one of its channels is more than 8 off the corner's.
            channels = ImageChops.difference(image, Image.new("RGB", image.size, image.getpixel((0, 0)))).split()
            moved = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
            box = moved.point(lambda v: 255 if v > 8 else 0).getbbox()
            if not box:
                problem = (f"Autark node {node_id}: its {width}x{height} map canvas is one colour, "
                           f"so it drew nothing to frame")
            else:
                left, top, right, bottom = box
                axes = {
                    "across": ((right - left) / width, left > 0 and right < width),
                    "down": ((bottom - top) / height, top > 0 and bottom < height),
                }
                if not any(span >= min_span and clear for span, clear in axes.values()):
                    spans = max(span for span, _ in axes.values())
                    why = (f"a speck under {min_span:.0%} of it" if spans < min_span
                           else "cut by the canvas's edges on every side it fills")
                    problem = (
                        f"Autark node {node_id}: its map's drawing spans "
                        f"{axes['across'][0]:.0%} of the canvas across and {axes['down'][0]:.0%} down "
                        f"(box {box} in {width}x{height}), {why}, so the map did not open "
                        f"framed on its layers"
                    )
        if problem is None or time.monotonic() >= deadline:
            return problem
        page.wait_for_timeout(500)


# An Autark node's drawing (its map canvas or plot div) and the content mount it
# is shown in, in layout pixels, which the canvas zoom does not scale; then the
# drawing's and the port markers' horizontal extents on screen.
_AUTK_DRAWING_FIT_JS = """(id) => {
    const map = document.getElementById('autk-grammar-map-' + id);
    const drawing = map || document.getElementById('autk-grammar-plot-' + id);
    if (!drawing) return null;
    const mount = drawing.closest('.curio-content-mount');
    const node = drawing.closest('.react-flow__node');
    const box = drawing.getBoundingClientRect();
    const markers = node ? [...node.querySelectorAll('[data-curio-port-marker]')].map((m) => {
        const r = m.getBoundingClientRect();
        return {side: m.dataset.curioPortMarker, x: [r.left, r.right]};
    }) : [];
    return {
        kind: map ? 'map' : 'plot',
        drawing: [drawing.offsetWidth, drawing.offsetHeight],
        body: mount ? [mount.clientWidth, mount.clientHeight] : null,
        x: [box.left, box.right],
        markers,
    };
}"""


def assert_autark_drawing_fits(page, node_id: str, *, timeout: float = 5000) -> None:
    """Assert an Autark node's map or plot fills its node body, clear of the markers.

    The body is the content mount, which fills the editor pane; the node body
    keeps that pane clear of the port markers (#631, #668), which once covered
    a map's edge or a plot's axis. A drawing taller than the body runs on under the
    node's footer, where it cannot be seen or picked, and a map is then centred
    below the middle of what shows (#534). A node with no drawing is left to
    the checks that expect one.
    """
    deadline = time.monotonic() + timeout / 1000
    while True:
        fit = page.evaluate(_AUTK_DRAWING_FIT_JS, node_id)
        if fit is None:
            return
        assert fit["body"] is not None, (
            f"Autark node {node_id}: its {fit['kind']} is not in a content mount, so "
            f"nothing keeps it clear of the port markers"
        )
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
    assert fit["markers"], (
        f"Autark node {node_id}: no port markers found, so nothing shows they clear its {fit['kind']}"
    )
    left, right = fit["x"]
    covered = {
        m["side"]: round(min(right, m["x"][1]) - max(left, m["x"][0]), 1)
        for m in fit["markers"]
        if min(right, m["x"][1]) - max(left, m["x"][0]) > 0
    }
    assert not covered, (
        f"Autark node {node_id}: the port markers cover its {fit['kind']} "
        f"(screen px per marker: {covered})"
    )


# Each shown node's editor panes (NodeEditor's Tab.Content, the first one in the
# node; an output can hold its own) and its port markers, on screen.
_EDITOR_PANES_JS = """() => [...document.querySelectorAll('.react-flow__node')].map((node) => {
    const rect = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 ? [r.left, r.top, r.right, r.bottom] : null;
    };
    const panes = node.querySelector('.tab-content');
    return {
        id: node.dataset.id,
        panes: panes ? rect(panes) : null,
        markers: [...node.querySelectorAll('[data-curio-port-marker]')]
            .map((m) => ({side: m.dataset.curioPortMarker, box: rect(m)}))
            .filter((m) => m.box),
    };
})"""


def assert_editor_panes_clear_of_markers(page, *, expect_some: bool = True) -> None:
    """Assert no port marker covers any part of a node's editor panes.

    The panes (code, grammar, widgets, provenance, output) sit in the node
    body, which is inset from the node's edges further than the markers reach
    (#668). ``expect_some`` asserts at least one node with a marker was
    measured, so a dataflow whose editors never showed cannot pass.
    """
    nodes = page.evaluate(_EDITOR_PANES_JS)
    measured = [n for n in nodes if n["panes"] and n["markers"]]
    covered = {}
    for n in measured:
        left, top, right, bottom = n["panes"]
        for m in n["markers"]:
            m_left, m_top, m_right, m_bottom = m["box"]
            width = min(right, m_right) - max(left, m_left)
            height = min(bottom, m_bottom) - max(top, m_top)
            if width > 0 and height > 0:
                covered[f"{n['id']} {m['side']}"] = round(width, 1)
    assert not expect_some or measured, (
        "No node shows both editor panes and a port marker, so nothing shows the markers clear them"
    )
    assert not covered, (
        f"The port markers cover the editor panes (screen px across, per node and marker: {covered})"
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
