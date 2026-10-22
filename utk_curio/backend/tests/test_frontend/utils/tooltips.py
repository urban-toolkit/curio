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

#: How many times a hover reads its target's box and moves onto it, when the
#: target moved from under the pointer.
HOVER_TRIES = 3
#: How long the pointer stays on its target before it is checked again, in ms:
#: less than the 400 ms a tooltip waits.
HOVER_SETTLE_MS = 300

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

# Whether the page point (x, y) lies in the element *selector* finds, and what
# lies there.
_ON_ELEMENT_JS = r"""({ x, y, selector }) => {
    const el = document.elementFromPoint(x, y);
    if (!el) return { on: false, under: "nothing" };
    const under = `${el.tagName.toLowerCase()}.${(el.getAttribute("class") || "").trim().split(/\s+/).join(".")} `
        + JSON.stringify((el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40));
    return { on: !!el.closest(selector), under };
}"""

# Whether the page point (x, y) lies on a chip's span whose chip reads *name*,
# and what lies there. A chip's name is drawn as a run of spans, one per token
# and decoration, each with the chip's class; its brackets are hidden spans.
# A chip with a problem is drawn whole, its brackets in the run.
_ON_CHIP_JS = r"""({ x, y, name }) => {
    const el = document.elementFromPoint(x, y);
    if (!el) return { on: false, under: "nothing" };
    const under = `${el.tagName.toLowerCase()}.${(el.getAttribute("class") || "").trim().split(/\s+/).join(".")} `
        + JSON.stringify((el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40));
    const isChip = (node) => !!node && node.nodeType === 1
        && (node.classList.contains("curio-widget-ref") || node.classList.contains("curio-widget-ref-problem"));
    const span = el.closest(".curio-widget-ref, .curio-widget-ref-problem");
    if (!span) return { on: false, under };
    let first = span;
    while (isChip(first.previousElementSibling)) first = first.previousElementSibling;
    let text = "";
    for (let node = first; isChip(node); node = node.nextElementSibling) text += node.textContent || "";
    text = text.replace(/ /g, " ");
    const on = text === name || text === `[!! ${name} !!]`;
    return { on, under: `${under}, in a chip that reads ${JSON.stringify(text)}` };
}"""

# What lies under the page point (x, y): the element, its classes and text,
# and whether it sits in an editor or in a target that asks for a tooltip.
_UNDER_POINT_JS = r"""({ x, y }) => {
    const el = document.elementFromPoint(x, y);
    if (!el) return null;
    const target = el.closest("[data-tooltip], [data-tooltip-content]");
    return {
        tag: el.tagName.toLowerCase(),
        classes: el.getAttribute("class") || "",
        text: (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80),
        inEditor: !!el.closest(".monaco-editor"),
        tooltipTarget: target ? `${target.tagName.toLowerCase()} ${target.getAttribute("class") || ""}`.trim() : null,
    };
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
    scrolled into the editor's view. Monaco draws a scroll in a later frame,
    so a box read in the same call as the scroll is where the chip was: the
    box counts once two reads in a row agree."""
    deadline = time.time() + timeout / 1000
    box = page.evaluate(_CHIP_JS, {"nodeId": node_id, "inner": inner})
    previous = None
    while (box is None or box != previous) and time.time() < deadline:
        previous = box
        page.wait_for_timeout(200)
        box = page.evaluate(_CHIP_JS, {"nodeId": node_id, "inner": inner})
    assert box, f"{node_id}'s editor shows no chip [!! {inner} !!]"
    assert box == previous, f"the chip [!! {inner} !!] in {node_id}'s editor kept moving: {previous}, then {box}"
    return box


def tooltips_on_screen(page, selector: str | None = None) -> list[dict]:
    """The tooltips on screen, each as ``_TOOLTIPS_JS`` reads it."""
    return page.evaluate(_TOOLTIPS_JS, selector)


def monaco_hovers(page) -> int:
    """How many of Monaco's own hovers are on screen."""
    return page.evaluate(_MONACO_HOVERS_JS)


def tooltip_saying(
    page,
    what: str,
    expected: list[str],
    selector: str | None = None,
    *,
    absent: tuple[str, ...] = (),
    timeout: float = 15000,
) -> dict:
    """Wait until the one tooltip *what* shows says each of *expected* and
    none of *absent*, as a chip's preview does once it has read what it shows,
    and return it as ``one_tooltip`` does. *absent* tells it from another
    target's tooltip that says the same and more."""
    def says(text: str) -> bool:
        return all(part in text for part in expected) and not any(part in text for part in absent)

    deadline = time.time() + timeout / 1000
    tips = tooltips_on_screen(page, selector)
    while not (len(tips) == 1 and says(tips[0]["text"])) and time.time() < deadline:
        page.wait_for_timeout(200)
        tips = tooltips_on_screen(page, selector)
    tip = one_tooltip(page, what, selector, timeout=0)
    missing = [part for part in expected if part not in tip["text"]]
    assert not missing, f"{what}: the tooltip does not say {missing}: {tip['text']!r}"
    stray = [part for part in absent if part in tip["text"]]
    assert not stray, f"{what}: the tooltip says {stray}, which is another target's: {tip['text']!r}"
    return tip


def _hover(page, what: str, expected: list[str], selector: str | None, *, read_box, on_target, absent, timeout) -> dict:
    """A fresh hover: the pointer rests where nothing shows a tooltip until
    none shows, then on the middle of its target's box, read only now, and the
    tooltip there is waited for as ``tooltip_saying`` waits for it.

    Then what lies under the pointer is checked to be the target (*on_target*),
    and again a moment later, before the tooltip's wait ends: a target that
    moved after its box was read (an editor drawing a scroll in a later frame)
    has its box read again and the pointer moved again, up to HOVER_TRIES
    times. The tooltip comes back with the box hovered, under ``hovered``."""
    move_pointer_away(page, selector)
    no_tooltip(page, f"{what}, before the pointer moves onto it", timeout=5000)
    tries: list[str] = []
    for _ in range(HOVER_TRIES):
        box = read_box()
        point = assert_in_view(page, *box_middle(box), what)
        page.mouse.move(*point)
        check = on_target(point)
        if check["on"]:
            page.wait_for_timeout(HOVER_SETTLE_MS)
            check = on_target(point)
        tries.append(f"box {box} at ({point[0]:.0f}, {point[1]:.0f}): {check['under']}")
        if check["on"]:
            break
    else:
        raise AssertionError(
            f"{what}: the pointer did not rest on its target in {HOVER_TRIES} tries:\n  " + "\n  ".join(tries)
        )
    try:
        tip = tooltip_saying(page, what, expected, selector, absent=absent, timeout=timeout)
    except AssertionError as error:
        under = page.evaluate(_UNDER_POINT_JS, {"x": point[0], "y": point[1]})
        try:
            now = read_box()
        except AssertionError as reread:
            now = f"not read again: {reread}"
        raise AssertionError(
            f"{error}\n  under the pointer at ({point[0]:.0f}, {point[1]:.0f}): {under}"
            f"\n  tries:\n    " + "\n    ".join(tries) + f"\n  the box now: {now}"
        ) from None
    return {**tip, "hovered": box}


def hover_until_tooltip_says(
    page,
    selector: str,
    what: str,
    expected: list[str],
    *,
    absent: tuple[str, ...] = (),
    timeout: float = 15000,
) -> dict:
    """A fresh hover of the element *selector* finds, its box read once no
    tooltip shows, and the point checked to lie in it (``_hover``)."""

    def on_element(point: tuple[float, float]) -> dict:
        return page.evaluate(_ON_ELEMENT_JS, {"x": point[0], "y": point[1], "selector": selector})

    return _hover(
        page, what, expected, selector,
        read_box=lambda: element_box(page, selector), on_target=on_element, absent=absent, timeout=timeout,
    )


def hover_chip_until_tooltip_says(
    page,
    node_id: str,
    inner: str,
    what: str,
    expected: list[str],
    *,
    absent: tuple[str, ...] = (),
    timeout: float = 15000,
) -> dict:
    """A fresh hover of the chip ``[!! inner !!]`` in *node_id*'s editor: its
    box read once no tooltip shows (``editor_chip_box``), and the point checked
    to lie on a span of that chip, whose text is *inner* (``_hover``)."""

    def on_chip(point: tuple[float, float]) -> dict:
        return page.evaluate(_ON_CHIP_JS, {"x": point[0], "y": point[1], "name": inner})

    return _hover(
        page, what, expected, None,
        read_box=lambda: editor_chip_box(page, node_id, inner), on_target=on_chip, absent=absent, timeout=timeout,
    )
