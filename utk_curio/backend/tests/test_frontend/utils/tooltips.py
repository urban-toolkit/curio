"""The one Curio tooltip, as an e2e test reads it: where the pointer rests,
the tooltip that shows, and the box of a close-up of it with its target.

The pointer is moved with ``page.mouse`` to an element's middle: a locator's
hover fails its actionability check under React Flow's pane. A tooltip is in
a portal on ``document.body`` (``components/tooltip/TooltipLayer.tsx``), and
the element it describes names it in ``aria-describedby``.
"""

from __future__ import annotations

import math
import time

from .interactions import assert_in_view

#: How long a tooltip may take to show, in ms: its 400 ms, and a busy runner.
TOOLTIP_SHOW_MS = 5000

#: The room around a tooltip and its target in their close-up, in px.
TOOLTIP_FRAME_MARGIN_PX = 16

# The first element *selector* finds that is laid out, as a box.
_BOX_JS = r"""(selector) => {
    const el = Array.from(document.querySelectorAll(selector)).find((e) => e.getClientRects().length > 0);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
}"""

# A point on the canvas where the pointer rests on nothing that shows a
# tooltip, away from the element *avoid* finds: the bare pane when some is in
# view, else a part of a card that holds no control and no editor.
_QUIET_POINT_JS = r"""(avoid) => {
    const area = document.querySelector(".curio-canvas-drop-target") || document.body;
    const away = avoid ? Array.from(document.querySelectorAll(avoid)).find((e) => e.getClientRects().length > 0) : null;
    const loud = '[data-tooltip], [title], [aria-describedby], button, a, input, select, textarea, '
        + '[role="button"], [role="tab"], [draggable="true"], .monaco-editor, .react-flow__handle, canvas';
    const r = area.getBoundingClientRect();
    let fallback = null;
    for (let fy = 0.05; fy < 1; fy += 0.1) {
        for (let fx = 0.05; fx < 1; fx += 0.1) {
            const x = r.left + fx * r.width;
            const y = r.top + fy * r.height;
            const el = document.elementFromPoint(x, y);
            if (!el || el.closest(loud) || (away && (away.contains(el) || el.contains(away)))) continue;
            if (el.classList.contains("react-flow__pane")) return { x, y };
            fallback = fallback || { x, y };
        }
    }
    return fallback;
}"""

# The tooltips on screen: what each says, its box, where it hangs in the page,
# and the box of the element it describes (aria-describedby) that is, holds or
# sits in the element *selector* finds.
_TOOLTIPS_JS = r"""(selector) => {
    const seen = (el) => {
        const style = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) > 0
            && r.width > 0 && r.height > 0;
    };
    const asBox = (r) => ({ left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height });
    const hovered = selector
        ? Array.from(document.querySelectorAll(selector)).find((e) => e.getClientRects().length > 0) || null
        : null;
    const root = document.getElementById("root");
    return Array.from(document.querySelectorAll('[role="tooltip"]')).filter(seen).map((tip) => {
        const described = tip.id
            ? Array.from(document.querySelectorAll("[aria-describedby]")).filter((el) =>
                (el.getAttribute("aria-describedby") || "").split(/\s+/).includes(tip.id))
            : [];
        const target = described.find((el) =>
            !hovered || el === hovered || el.contains(hovered) || hovered.contains(el)) || null;
        return {
            id: tip.id,
            text: (tip.innerText || tip.textContent || "").replace(/\s+/g, " ").trim(),
            box: asBox(tip.getBoundingClientRect()),
            inViewport: !!tip.closest(".react-flow__viewport"),
            inRoot: !!(root && root.contains(tip)),
            inBody: document.body.contains(tip),
            described: described.length,
            target: target ? asBox(target.getBoundingClientRect()) : null,
        };
    });
}"""

# How many of Monaco's own hovers are on screen.
_MONACO_HOVERS_JS = r"""() => Array.from(document.querySelectorAll(".monaco-hover")).filter((el) => {
    const style = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && r.width > 0 && r.height > 0;
}).length"""

# The box of the chip `[!! inner !!]` in the editor *nodeId* shows, its line
# first scrolled to the editor's middle. Null until the line is drawn.
_CHIP_JS = r"""({ nodeId, inner }) => {
    const card = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const host = card && Array.from(card.querySelectorAll(".monaco-editor")).find((el) => el.getClientRects().length > 0);
    if (!host) return null;
    const written = `[!! ${inner} !!]`;
    const editor = ((window.monaco && window.monaco.editor.getEditors()) || []).find((e) => host.contains(e.getDomNode()));
    if (editor) {
        const at = editor.getModel().getValue().split("\n").findIndex((line) => line.includes(written));
        if (at >= 0) editor.revealLineInCenter(at + 1);
    }
    for (const line of host.querySelectorAll(".view-line")) {
        if (!(line.textContent || "").replace(/ /g, " ").includes(written)) continue;
        const spans = Array.from(line.querySelectorAll(".curio-widget-ref, .curio-widget-ref-problem"))
            .filter((span) => span.getClientRects().length > 0);
        if (!spans.length) return null;
        const boxes = spans.map((span) => span.getBoundingClientRect());
        const left = Math.min(...boxes.map((b) => b.left));
        const right = Math.max(...boxes.map((b) => b.right));
        const top = Math.min(...boxes.map((b) => b.top));
        const bottom = Math.max(...boxes.map((b) => b.bottom));
        return { left, top, right, bottom, width: right - left, height: bottom - top };
    }
    return null;
}"""


def element_box(page, selector: str) -> dict:
    box = page.evaluate(_BOX_JS, selector)
    assert box, f"nothing on the page matches {selector}"
    return box


def box_middle(box: dict) -> tuple[float, float]:
    return (box["left"] + box["right"]) / 2, (box["top"] + box["bottom"]) / 2


def move_pointer_away(page, avoid: str | None = None) -> None:
    """Rest the pointer where nothing shows a tooltip, away from what the
    selector *avoid* finds."""
    quiet = page.evaluate(_QUIET_POINT_JS, avoid)
    assert quiet, "the canvas has no point where nothing shows a tooltip"
    page.mouse.move(quiet["x"], quiet["y"])


def rest_pointer_on(page, box: dict, what: str, *, avoid: str | None = None) -> tuple[float, float]:
    """Move the pointer from a quiet point to the middle of *box*, and leave it
    there: a fresh hover, wherever the pointer was."""
    move_pointer_away(page, avoid)
    point = assert_in_view(page, *box_middle(box), what)
    page.mouse.move(*point)
    return point


def one_tooltip(page, what: str, selector: str | None = None, *, timeout: float = TOOLTIP_SHOW_MS) -> dict:
    """Wait for the one tooltip *what* shows, and return it.

    It counts once it is on screen with its text and, given *selector*, once
    the element it describes (``aria-describedby``) is, holds or sits in the
    element the selector finds. It is in a portal on ``document.body``,
    outside the app's root and the canvas's viewport, whose zoom would scale
    it.
    """
    deadline = time.time() + timeout / 1000
    tips = page.evaluate(_TOOLTIPS_JS, selector)
    while not (len(tips) == 1 and tips[0]["text"] and (selector is None or tips[0]["target"])):
        if time.time() >= deadline:
            break
        page.wait_for_timeout(100)
        tips = page.evaluate(_TOOLTIPS_JS, selector)
    assert len(tips) == 1, f"{what}: {len(tips)} tooltips on screen, not one: {tips}"
    tip = tips[0]
    assert tip["text"], f"{what}: the tooltip says nothing: {tip}"
    if selector is not None:
        assert tip["target"], (
            f"{what}: the tooltip describes no element that is, holds or sits in {selector} "
            f"(aria-describedby): {tip}"
        )
    assert tip["inBody"] and not tip["inRoot"], f"{what}: the tooltip is not in a portal on document.body: {tip}"
    assert not tip["inViewport"], f"{what}: the tooltip is inside the canvas's viewport, which its zoom scales: {tip}"
    return tip


def no_tooltip(page, what: str, *, timeout: float = 2000) -> None:
    deadline = time.time() + timeout / 1000
    tips = page.evaluate(_TOOLTIPS_JS, None)
    while tips and time.time() < deadline:
        page.wait_for_timeout(100)
        tips = page.evaluate(_TOOLTIPS_JS, None)
    assert tips == [], f"{what}: a tooltip is still on screen: {tips}"


def tooltip_close_up(page, tip: dict, target: dict | None = None) -> dict:
    """The box of the page that holds *tip* and its target, TOOLTIP_FRAME_MARGIN_PX
    around them, in whole pixels and inside the viewport: their close-up. An
    editor's chip names no element (*tip* has no target): its box is *target*."""
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    boxes = (tip["box"], target or tip["target"])
    left = max(0, math.floor(min(b["left"] for b in boxes) - TOOLTIP_FRAME_MARGIN_PX))
    top = max(0, math.floor(min(b["top"] for b in boxes) - TOOLTIP_FRAME_MARGIN_PX))
    right = min(viewport["width"], math.ceil(max(b["right"] for b in boxes) + TOOLTIP_FRAME_MARGIN_PX))
    bottom = min(viewport["height"], math.ceil(max(b["bottom"] for b in boxes) + TOOLTIP_FRAME_MARGIN_PX))
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def editor_chip_box(page, node_id: str, inner: str, *, timeout: float = 15000) -> dict:
    """The box of the chip ``[!! inner !!]`` in *node_id*'s editor, its line
    scrolled into the editor's view."""
    deadline = time.time() + timeout / 1000
    box = page.evaluate(_CHIP_JS, {"nodeId": node_id, "inner": inner})
    while box is None and time.time() < deadline:
        page.wait_for_timeout(200)
        box = page.evaluate(_CHIP_JS, {"nodeId": node_id, "inner": inner})
    assert box, f"{node_id}'s editor shows no chip [!! {inner} !!]"
    return box


def tooltips_on_screen(page, selector: str | None = None) -> list[dict]:
    """The tooltips on screen, each as ``_TOOLTIPS_JS`` reads it."""
    return page.evaluate(_TOOLTIPS_JS, selector)


def monaco_hovers(page) -> int:
    """How many of Monaco's own hovers are on screen."""
    return page.evaluate(_MONACO_HOVERS_JS)


def tooltip_saying(page, what: str, expected: list[str], selector: str | None = None, *, timeout: float = 15000) -> dict:
    """Wait until the one tooltip *what* shows says each of *expected*, as a
    chip's preview does once it has read what it shows, and return it as
    ``one_tooltip`` does."""
    deadline = time.time() + timeout / 1000
    tips = tooltips_on_screen(page, selector)
    while not (len(tips) == 1 and all(text in tips[0]["text"] for text in expected)) and time.time() < deadline:
        page.wait_for_timeout(200)
        tips = tooltips_on_screen(page, selector)
    tip = one_tooltip(page, what, selector, timeout=0)
    missing = [text for text in expected if text not in tip["text"]]
    assert not missing, f"{what}: the tooltip does not say {missing}: {tip['text']!r}"
    return tip
