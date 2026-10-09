"""Interaction frames: a gesture on one drawn node and the node it lights up,
compared before and after.
"""

import time

from playwright.sync_api import Page

from .canvas_authoring import node_execution_timeout_ms
from .images import _capture_element, _compare_images
from .screenshots import REMINT_MIN_RATIO, save_workflow_test_screenshot
from .closeups import CLOSEUP_MAX_DIFF_RATIO, CLOSEUP_PIXEL_THRESHOLD


# ---------------------------------------------------------------- interactions
#
# A gesture on one drawn node (a hover over a bar, a pick on a map) and the
# node it should light up, compared before and after. See
# test_workflows.INTERACTIONS.

#: How many pixels of the target have to change, by more than 40 in some
#: channel, for a gesture to count as having reached it. One bar of 90 turned
#: red was 63 at 55% zoom (CI run 36791426801); two captures of a node that is
#: not changing differ by none.
INTERACTION_MIN_CHANGED_PIXELS = 20

#: The page's size while interaction steps run: room to frame a pair of nodes
#: at up to 100% zoom. At the suite's 1280x720 a bar chart above a map fitted
#: at 55%, where one bar is two pixels wide.
INTERACTION_VIEWPORT = {"width": 1600, "height": 1440}

#: How close to its first capture a target has to come back once the gesture
#: is undone: the share of pixels over ``CLOSEUP_PIXEL_THRESHOLD``.
INTERACTION_RESTORED_RATIO = 0.01

#: How long a gesture, and taking it back, may take to show on the target: as
#: long as an Autark node may take to run. A map shows a change only in a frame
#: it draws after the change, and on a loaded GPU runner that frame waits for
#: every frame already queued for the GPU. Example 17 draws five maps: in CI run
#: 37724810297 its map's highlight was cleared 0.1 s after the double-click, and
#: reading the map back waited 20 to 35 s (#763).
INTERACTION_SHOWN_TIMEOUT_MS = node_execution_timeout_ms("AUTK_GRAMMAR")

# The element a node draws into: a Vega chart's canvas, an Autark map's canvas,
# or the box an Autark plot puts its svg in.
_DRAWING_SELECTOR_JS = """(id) => {
    for (const selector of ['#vega' + id + ' canvas', '#autk-grammar-map-' + id,
                            '#autk-grammar-plot-' + id]) {
        if (document.querySelector(selector)) return selector;
    }
    return null;
}"""

# The drawing now, kept on window so a later check can ask whether it is still
# the one in the page: a redraw replaces it, a highlight keeps it.
_KEEP_DRAWING_JS = """(selector) => {
    const el = document.querySelector(selector);
    (window.__curioKeptDrawings = window.__curioKeptDrawings || {})[selector] = el;
    return !!el;
}"""
_DRAWING_KEPT_JS = """(selector) => {
    const kept = (window.__curioKeptDrawings || {})[selector];
    return !!kept && kept.isConnected && document.querySelector(selector) === kept;
}"""

# Defines readMarks(el): a canvas's pixels, read through toDataURL (which a
# WebGPU map canvas answers as a 2D chart does), with where each one sits in
# the page and whether it is marked: opaque and saturated, so a bar or a
# polygon rather than an edge, an axis or the background.
_CANVAS_MARKS_JS = """
    const readMarks = async (el) => {
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        const img = new Image();
        img.src = el.toDataURL('image/png');
        await img.decode();
        const w = img.width, h = img.height;
        if (!w || !h) return null;
        const scratch = document.createElement('canvas');
        scratch.width = w;
        scratch.height = h;
        const ctx = scratch.getContext('2d');
        ctx.drawImage(img, 0, 0);
        const px = ctx.getImageData(0, 0, w, h).data;
        const box = el.getBoundingClientRect();
        const marked = (x, y) => {
            const i = (y * w + x) * 4;
            const hi = Math.max(px[i], px[i + 1], px[i + 2]);
            const lo = Math.min(px[i], px[i + 1], px[i + 2]);
            return px[i + 3] >= 250 && hi > 0 && (hi - lo) / hi > 0.3;
        };
        return { w, h, box, sx: box.width / w, sy: box.height / h, marked };
    };
"""

# A marked pixel of a canvas the page shows, in page coordinates: the one
# nearest a point given as fractions of the part of the canvas in view. A node
# can show less of its drawing than the canvas holds (a multi-view chart
# scrolls in its pane), and overlays sit on top of it (an Autark map's menu and
# legend), so what is in view is asked of elementFromPoint. Every pixel around
# the one chosen is marked too: 7x7 where the marks are that wide, as a map's
# polygons are, else 3x3, as a bar is, so the point is well inside its mark.
_MARK_POINT_JS = "async ({ selector, at }) => {" + _CANVAS_MARKS_JS + """
    const el = document.querySelector(selector);
    if (!el) return null;
    const marks = await readMarks(el);
    if (!marks) return null;
    const { w, h, box, sx, sy, marked } = marks;
    const onPage = (x, y) => [box.left + (x + 0.5) * sx, box.top + (y + 0.5) * sy];
    const shown = (x, y) => document.elementFromPoint(...onPage(x, y)) === el;
    const inside = (x, y, r) => {
        for (let dy = -r; dy <= r; dy++) {
            for (let dx = -r; dx <= r; dx++) if (!marked(x + dx, y + dy)) return false;
        }
        return true;
    };
    let x0 = w, y0 = h, x1 = -1, y1 = -1;
    const step = Math.max(1, Math.round(8 / sx));
    for (let y = 0; y < h; y += step) {
        for (let x = 0; x < w; x += step) {
            if (shown(x, y)) {
                x0 = Math.min(x0, x); y0 = Math.min(y0, y);
                x1 = Math.max(x1, x); y1 = Math.max(y1, y);
            }
        }
    }
    if (x1 < 0) return null;
    const cx = x0 + at[0] * (x1 - x0), cy = y0 + at[1] * (y1 - y0);
    for (const r of [3, 1]) {
        const found = [];
        for (let y = Math.max(y0, r); y <= Math.min(y1, h - 1 - r); y++) {
            for (let x = Math.max(x0, r); x <= Math.min(x1, w - 1 - r); x++) {
                if (inside(x, y, r)) found.push([(x - cx) ** 2 + (y - cy) ** 2, x, y]);
            }
        }
        found.sort((a, b) => a[0] - b[0]);
        for (const [, x, y] of found) {
            if (shown(x, y)) {
                const [pageX, pageY] = onPage(x, y);
                return { x: pageX, y: pageY };
            }
        }
    }
    return null;
}"""

# Where a brush gesture drags, in page coordinates: an Autark plot's d3 brush
# overlay, or, on a Vega canvas, the box its marks take.
_BRUSH_AREA_JS = "async (selector) => {" + _CANVAS_MARKS_JS + """
    const el = document.querySelector(selector);
    if (!el) return null;
    const asBox = (r) => ({ x: r.left, y: r.top, width: r.width, height: r.height });
    const overlay = el.querySelector('rect.overlay');
    if (overlay) return asBox(overlay.getBoundingClientRect());
    if (el.tagName !== 'CANVAS') return asBox(el.getBoundingClientRect());
    const marks = await readMarks(el);
    if (!marks) return null;
    const { w, h, box, sx, sy, marked } = marks;
    let x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
            if (marked(x, y)) {
                x0 = Math.min(x0, x); y0 = Math.min(y0, y);
                x1 = Math.max(x1, x); y1 = Math.max(y1, y);
            }
        }
    }
    if (x1 < 0) return null;
    return { x: box.left + x0 * sx, y: box.top + y0 * sy,
             width: (x1 - x0 + 1) * sx, height: (y1 - y0 + 1) * sy };
}"""


def drawing_selector(page: Page, node_id: str) -> str | None:
    """The selector of the element *node_id* draws into, or None before it drew."""
    return page.evaluate(_DRAWING_SELECTOR_JS, node_id)


def keep_drawing(page: Page, selector: str) -> None:
    assert page.evaluate(_KEEP_DRAWING_JS, selector), f"nothing matches {selector}"


def drawing_kept(page: Page, selector: str) -> bool:
    """Whether *selector* still matches the element :func:`keep_drawing` saw."""
    return bool(page.evaluate(_DRAWING_KEPT_JS, selector))


def mark_point(page: Page, selector: str, at=(0.5, 0.5)) -> dict | None:
    """``{x, y}`` in the page: the marked pixel of *selector*'s canvas nearest *at*
    of the part in view."""
    return page.evaluate(_MARK_POINT_JS, {"selector": selector, "at": list(at)})


def brush_area(page: Page, selector: str) -> dict | None:
    """``{x, y, width, height}`` in the page: where a brush on *selector* drags."""
    return page.evaluate(_BRUSH_AREA_JS, selector)


def at_fraction(area: dict, fraction) -> tuple[float, float]:
    """The page point at *fraction* ``(fx, fy)`` of *area*."""
    return (area["x"] + fraction[0] * area["width"], area["y"] + fraction[1] * area["height"])


def assert_in_view(page: Page, x: float, y: float, what: str) -> tuple[float, float]:
    """``(x, y)``, once it is inside the window.

    A pointer sent outside the window reaches no element, so a hover or click
    aimed there does nothing and the test fails later, on a selection that
    never came, with nothing saying why. Fail here instead, with the point."""
    width, height = page.evaluate("() => [window.innerWidth, window.innerHeight]")
    assert 0 <= x < width and 0 <= y < height, (
        f"{what} is at ({x:.0f}, {y:.0f}), outside the {width}x{height} window"
    )
    return x, y


#: An autk-plot mark's fill when it is selected (PlotStyle.highlight, #5dade2),
#: as getComputedStyle reads it.
AUTK_PLOT_HIGHLIGHT = "rgb(93, 173, 226)"

# The marks of an Autark plot lit where its brush is not, or under its brush and
# not lit; null when the plot holds no brush. The brush and the marks share one
# group, so their page boxes compare as autk-plot's own hit test does. A mark
# that only touches an edge of the brush could go either way, so it is left
# out. Under means inside the brush both across and down: a scatter's brush is
# 2D (example 08), and a histogram's x brush spans the plot's full height, so
# its bars come out as they would compared across only.
_BRUSH_MISMATCHES_JS = """({ selector, highlight }) => {
    const el = document.querySelector(selector);
    const brush = el && el.querySelector('.autkBrush rect.selection');
    if (!brush || brush.style.display === 'none') return null;
    const b = brush.getBoundingClientRect();
    if (!b.width) return null;
    const wrong = [];
    for (const mark of el.querySelectorAll('.autkMark')) {
        const r = mark.getBoundingClientRect();
        if (Math.abs(r.right - b.left) < 1 || Math.abs(r.left - b.right) < 1) continue;
        if (Math.abs(r.bottom - b.top) < 1 || Math.abs(r.top - b.bottom) < 1) continue;
        const under = r.right > b.left && r.left < b.right && r.bottom > b.top && r.top < b.bottom;
        const lit = getComputedStyle(mark).fill === highlight;
        if (under !== lit) wrong.push({ label: (mark.__data__ || {}).label ?? null, lit });
    }
    return wrong;
}"""


# The bars of an Autark plot, left to right, as page boxes with their labels.
_BAR_BOXES_JS = """(selector) => {
    const el = document.querySelector(selector);
    if (!el) return [];
    return Array.from(el.querySelectorAll('.autkMark')).map((mark) => {
        const r = mark.getBoundingClientRect();
        return { label: (mark.__data__ || {}).label ?? null, left: r.left, right: r.right,
                 top: r.top, bottom: r.bottom };
    }).sort((a, b) => a.left - b.left);
}"""

# Every time an Autark plot's brush rectangle shows or hides, with when, kept
# on window.__curioBrushLog: a brush the page takes away mid-gesture shows here.
_WATCH_BRUSH_JS = """(selector) => {
    const rect = document.querySelector(selector + ' .autkBrush rect.selection');
    if (!rect) return false;
    const log = window.__curioBrushLog = [];
    const t0 = performance.now();
    const note = (what) => log.push({ t: Math.round(performance.now() - t0), what,
        shown: rect.style.display !== 'none', width: Number(rect.getAttribute('width') || 0) });
    window.__curioBrushNote = note;
    new MutationObserver(() => note('change')).observe(rect, { attributes: true });
    for (const type of ['mousedown', 'mouseup']) {
        window.addEventListener(type, () => note(type), true);
    }
    return true;
}"""


def bar_boxes(page: Page, selector: str) -> list[dict]:
    """The bars of the Autark plot in *selector*, left to right, as page boxes."""
    return page.evaluate(_BAR_BOXES_JS, selector)


def watch_brush(page: Page, selector: str) -> None:
    """Start logging each show and hide of the plot's brush (see :func:`brush_log`)."""
    assert page.evaluate(_WATCH_BRUSH_JS, selector), f"no brush in {selector}"


def brush_log(page: Page) -> list[dict]:
    return page.evaluate("() => window.__curioBrushLog || []")


# Every lit or unlit an Autark plot's bars go through from now on, per bar, left
# to right, kept on window.__curioBarFills[selector] with the page's mousedowns
# and mouseups. autk-plot colours a mark through its inline style, and one task
# can restyle a bar more than once, so each change is read from the mutation
# record's old value rather than from the style the observer finds afterwards.
_WATCH_BAR_FILLS_JS = """({ selector, highlight }) => {
    const el = document.querySelector(selector);
    if (!el) return 0;
    const marks = Array.from(el.querySelectorAll('.autkMark'))
        .map((mark) => [mark.getBoundingClientRect().left, mark])
        .sort((a, b) => a[0] - b[0]).map(([, mark]) => mark);
    const probe = document.createElement('div');
    const litIn = (style) => { probe.setAttribute('style', style || ''); return probe.style.fill === highlight; };
    const litNow = (mark) => getComputedStyle(mark).fill === highlight;
    const all = window.__curioBarFills = window.__curioBarFills || {};
    const t0 = window.__curioBarFillsT0 = window.__curioBarFillsT0 ?? performance.now();
    const now = () => Math.round(performance.now() - t0);
    const states = marks.map((mark) => [{ t: now(), lit: litNow(mark) }]);
    all[selector] = { states, marks, labels: marks.map((m) => (m.__data__ || {}).label ?? null) };
    const index = new Map(marks.map((mark, i) => [mark, i]));
    const observer = new MutationObserver((records) => {
        const t = now();
        const olds = new Map();
        for (const record of records) {
            const i = index.get(record.target);
            if (i === undefined) continue;
            if (!olds.has(i)) olds.set(i, []);
            olds.get(i).push(litIn(record.oldValue));
        }
        for (const [i, before] of olds) {
            for (const lit of [...before.slice(1), litNow(marks[i])]) {
                if (states[i][states[i].length - 1].lit !== lit) states[i].push({ t, lit });
            }
        }
    });
    for (const mark of marks) {
        observer.observe(mark, { attributes: true, attributeFilter: ['style'], attributeOldValue: true });
    }
    window.__curioBarFillsObservers = window.__curioBarFillsObservers || {};
    window.__curioBarFillsObservers[selector]?.disconnect();
    window.__curioBarFillsObservers[selector] = observer;
    if (!window.__curioBarFillsPointer) {
        window.__curioBarFillsPointer = [];
        for (const type of ['mousedown', 'mouseup']) {
            window.addEventListener(type, () => window.__curioBarFillsPointer.push({ t: now(), type }), true);
        }
    }
    return marks.length;
}"""

_BAR_FILL_LOG_JS = """(selector) => {
    const watched = (window.__curioBarFills || {})[selector];
    if (!watched) return null;
    return { states: watched.states, labels: watched.labels,
             connected: watched.marks.every((mark) => mark.isConnected),
             pointer: window.__curioBarFillsPointer || [] };
}"""


def watch_bar_fills(page: Page, selector: str) -> None:
    """Start logging each lit and unlit of the plot's bars (see :func:`bar_fill_log`)."""
    count = page.evaluate(_WATCH_BAR_FILLS_JS, {"selector": selector, "highlight": AUTK_PLOT_HIGHLIGHT})
    assert count, f"no bars in {selector}"


def bar_fill_log(page: Page, selector: str) -> dict | None:
    """``{states, labels, connected, pointer}`` since :func:`watch_bar_fills`.

    ``states[i]`` lists bar *i*'s lit state, left to right, each with its time
    in ms: the state when the watch began, then one entry per change.
    ``connected`` is False if the plot replaced its bars since. ``pointer``
    holds the page's mousedowns and mouseups on the same clock."""
    return page.evaluate(_BAR_FILL_LOG_JS, selector)


def brush_mismatches(page: Page, selector: str, *, timeout_ms: int = 5000) -> list | None:
    """The bars of the Autark plot in *selector* whose highlight disagrees with
    its brush, once the selection coming back through a Data Pool has landed:
    asked until there are none, for up to *timeout_ms*. None when no brush shows."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        wrong = page.evaluate(_BRUSH_MISMATCHES_JS, {"selector": selector, "highlight": AUTK_PLOT_HIGHLIGHT})
        if not wrong or time.monotonic() >= deadline:
            return wrong
        page.wait_for_timeout(300)


# How many of an Autark plot's marks there are, and how many show its highlight.
_LIT_MARKS_JS = """({ selector, highlight }) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const marks = [...el.querySelectorAll('.autkMark')];
    return { total: marks.length,
             lit: marks.filter((m) => getComputedStyle(m).fill === highlight).length };
}"""


def lit_marks(page: Page, selector: str, *, at_least: float, timeout_ms: int = 5000) -> dict | None:
    """``{total, lit}``: the marks of the Autark plot in *selector*, and how many
    show its highlight, asked until *at_least* of them do, for up to *timeout_ms*."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        counts = page.evaluate(_LIT_MARKS_JS, {"selector": selector, "highlight": AUTK_PLOT_HIGHLIGHT})
        enough = bool(counts and counts["total"] and counts["lit"] >= at_least * counts["total"])
        if enough or time.monotonic() >= deadline:
            return counts
        page.wait_for_timeout(300)


def capture_node(page: Page, node_id: str):
    """The node as a frame of it shows it, in memory (maps painted, see #427)."""
    return _capture_element(page, f'.react-flow__node[data-id="{node_id}"]')


def changed_pixels(before, after, threshold: int = 40) -> int:
    """Pixels that differ by more than *threshold* in some channel."""
    return _compare_images(after, before, threshold).mismatched


def wait_for_node_capture(page: Page, node_id: str, done, *, timeout_ms: int = 15000):
    """Capture *node_id* until ``done(capture)`` holds. Returns ``(capture, held)``."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        capture = capture_node(page, node_id)
        if done(capture):
            return capture, True
        if time.monotonic() >= deadline:
            return capture, False
        page.wait_for_timeout(300)


def wait_for_node_still(page: Page, node_id: str, *, timeout_ms: int = 10000):
    """Capture *node_id* until two captures in a row match; returns the last."""
    previous = [capture_node(page, node_id)]

    def still(capture):
        same = _compare_images(capture, previous[0], CLOSEUP_PIXEL_THRESHOLD).ratio <= REMINT_MIN_RATIO
        previous[0] = capture
        return same

    capture, held = wait_for_node_capture(page, node_id, still, timeout_ms=timeout_ms)
    assert held, f"node {node_id} was still changing after {timeout_ms} ms"
    return capture


def save_interaction_frame(
    page: Page,
    workflow_filepath: str,
    node_id: str,
    *,
    test_name: str,
    interaction: dict,
) -> str:
    """Compare one node of an interaction, as it is framed now, against its baseline.

    Neither refits the canvas nor moves the pointer, and never sweeps toasts
    (that parks the pointer too): a held hover has to still be held when the
    shutter fires. Compared at ``CLOSEUP_PIXEL_THRESHOLD`` against
    ``CLOSEUP_MAX_DIFF_RATIO``, like a close-up, so it is taken inside the
    caller's ``canvas_painted_at_shown_zoom`` block, with the captures it is
    compared against in memory. *interaction* names the frame's place in its
    pair (step, phase, role, node) for the CI report's Interaction pairs.
    """
    return save_workflow_test_screenshot(
        page,
        workflow_filepath,
        test_name=test_name,
        pixel_threshold=CLOSEUP_PIXEL_THRESHOLD,
        max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO,
        clip_selector=f'.react-flow__node[data-id="{node_id}"]',
        fit_reactflow=False,
        interaction=interaction,
    )
