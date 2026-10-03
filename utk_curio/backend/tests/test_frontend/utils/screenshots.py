"""Screenshot baselines: capture, compare, mint and re-mint, node close-ups,
and what has to be quiet first (the viewport fit, toasts, running nodes).
"""

import os
import json
from contextlib import contextmanager
from io import BytesIO
from typing import NamedTuple

import allure
import pytest
from playwright.sync_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
    expect,
)

from .. import comparisons
from .environment import REPO_ROOT


# PNGs from workflow E2E tests: ``screenshot_{workflow_stem}_{test_name}.png``
WORKFLOW_SCREENSHOT_EXPECTED_DIR = os.path.join(
    REPO_ROOT, "docs", "examples", "dataflows", "expected_outputs"
)


def _wait_for_reactflow_ready(
    page: Page,
    *,
    padding: float = 0.2,
    stable_frames: int = 3,
    timeout_ms: int = 10000,
    node_ids: list[str] | None = None,
    max_zoom: float | None = None,
) -> None:
    """Force ReactFlow into a deterministic viewport before screenshotting.

    With *node_ids* the fit frames only those nodes, at most *max_zoom*.

    Without this, ``save_workflow_test_screenshot`` races the app-side
    ``fitView`` call in ``useWorkflowOperations`` (which runs on a
    ``setTimeout`` after the workflow is uploaded). The screenshot can
    fire before the transform has been applied, producing a pre-fit
    canvas where nodes overflow the viewport.

    Strategy:

    1. Wait until at least one ``.react-flow__node`` is on the page.
    2. Call ``fitView({ padding, duration: 0 })`` on the instance
       exposed at ``window.__curio_reactFlow`` (see ``MainCanvas.tsx``).
       ``duration: 0`` skips the ReactFlow animation so the transform
       is applied synchronously.
    3. Poll the ``.react-flow__viewport`` ``transform`` attribute until
       it has stayed identical for ``stable_frames`` consecutive reads
       (guards against Monaco's layout settling and any late
       node-size measurements from ReactFlow).
    """
    page.wait_for_function(
        "() => document.querySelectorAll('.react-flow__node').length > 0",
        timeout=timeout_ms,
    )

    page.evaluate(
        """({ padding, nodeIds, maxZoom }) => {
            const fit = window.__curio_fitViewWithMenuOffset;
            if (typeof fit === 'function') {
                const options = { padding, duration: 0, includeHiddenNodes: true };
                if (nodeIds) options.nodes = nodeIds.map((id) => ({ id }));
                if (maxZoom !== null) options.maxZoom = maxZoom;
                fit(options);
            }
        }""",
        {"padding": padding, "nodeIds": node_ids, "maxZoom": max_zoom},
    )

    page.wait_for_function(
        """(stable_frames) => {
            const vp = document.querySelector('.react-flow__viewport');
            if (!vp) return false;
            const current = vp.style.transform || '';
            if (!current) return false;
            window.__curio_vp_samples = window.__curio_vp_samples || [];
            const samples = window.__curio_vp_samples;
            samples.push(current);
            if (samples.length > stable_frames) samples.shift();
            if (samples.length < stable_frames) return false;
            return samples.every((s) => s === samples[0]);
        }""",
        arg=stable_frames,
        timeout=timeout_ms,
    )

    page.evaluate("delete window.__curio_vp_samples")


# Each Autark map canvas gets its own pixels as a CSS background for the length
# of one capture. On the GPU runner no Chrome screenshot includes a hardware
# WebGPU canvas (#427): the maps draw, and every frame showed them blank. A CSS
# background is painted by the page's own compositor, which the screenshot does
# capture, and it sits under the canvas and the map's overlays. Where the
# screenshot does include the canvas (a Mac), the opaque map covers it, so the
# frame is unchanged.
_PAINT_MAP_CANVASES_JS = """async () => {
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    let painted = 0;
    for (const c of document.querySelectorAll('canvas[id^="autk-grammar-map-"]')) {
        let url;
        try { url = c.toDataURL('image/png'); } catch (e) { continue; }
        c.dataset.curioCaptureBackground = JSON.stringify(
            [c.style.backgroundImage, c.style.backgroundSize, c.style.backgroundRepeat]);
        c.style.backgroundImage = `url("${url}")`;
        c.style.backgroundSize = '100% 100%';
        c.style.backgroundRepeat = 'no-repeat';
        painted += 1;
    }
    if (painted) await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    return painted;
}"""

_UNPAINT_MAP_CANVASES_JS = """() => {
    for (const c of document.querySelectorAll('canvas[data-curio-capture-background]')) {
        const [image, size, repeat] = JSON.parse(c.dataset.curioCaptureBackground);
        c.style.backgroundImage = image;
        c.style.backgroundSize = size;
        c.style.backgroundRepeat = repeat;
        delete c.dataset.curioCaptureBackground;
    }
}"""


@contextmanager
def _map_canvases_painted(page: Page):
    """Autark map canvases carry their own pixels as a background while inside."""
    painted = page.evaluate(_PAINT_MAP_CANVASES_JS)
    try:
        yield painted
    finally:
        if painted:
            page.evaluate(_UNPAINT_MAP_CANVASES_JS)


def _capture_full_page(page: Page):
    """Return a Pillow RGB image of the full scrollable page.

    Scrolls to top-left first so the capture is deterministic, then uses
    Playwright's ``full_page=True`` to grab everything.
    """
    from PIL import Image

    page.evaluate("window.scrollTo(0, 0)")
    with _map_canvases_painted(page):
        raw = page.screenshot(full_page=True)
    return Image.open(BytesIO(raw)).convert("RGB")


def _capture_element(page: Page, selector: str):
    """Return a Pillow RGB image of one element, or raise if it is not there.

    For a baseline whose subject is a panel rather than a page. A full-page
    capture of, say, an agent chat turn is more than half static canvas and
    chrome, which does not just waste the image - it dilutes the comparison,
    since a regression inside the panel is a small fraction of the frame
    against a 10% budget.
    """
    from PIL import Image

    locator = page.locator(selector)
    locator.wait_for(state="visible", timeout=15000)
    with _map_canvases_painted(page):
        raw = locator.screenshot()
    return Image.open(BytesIO(raw)).convert("RGB")


def _image_to_png_bytes(img) -> bytes:
    """Encode a Pillow image to PNG bytes for Allure attachments."""
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def dump_browser_log(
    workflow_filepath: str,
    test_name: str,
    log_entries: list,
    autk_errors: dict | None = None,
    webgpu_diagnostics: dict | None = None,
) -> str:
    """Write captured browser console + pageerror events (and any AUTK error
    tab text we extracted from the DOM) to a plain text file alongside the
    expected screenshot, and attach it to the Allure report.

    Returns the path written.
    """
    stem = os.path.splitext(os.path.basename(workflow_filepath))[0]
    os.makedirs(WORKFLOW_SCREENSHOT_EXPECTED_DIR, exist_ok=True)
    log_path = os.path.join(
        WORKFLOW_SCREENSHOT_EXPECTED_DIR,
        f"screenshot_{stem}_{test_name}_browser_log.txt",
    )
    lines: list[str] = []
    lines.append(f"# Browser log for {stem} :: {test_name}")
    lines.append(f"# Captured {len(log_entries)} console/pageerror events")
    lines.append("")
    if webgpu_diagnostics is not None:
        lines.append("## WebGPU diagnostics (probed once per session)")
        lines.append(json.dumps(webgpu_diagnostics, indent=2, default=str))
        lines.append("")
    if autk_errors:
        lines.append("## AUTK error tab text (extracted from DOM)")
        for node_id, text in autk_errors.items():
            lines.append(f"--- node {node_id} ---")
            lines.append(text or "(empty)")
            lines.append("")
    lines.append("## Console / pageerror events (chronological)")
    for entry in log_entries:
        if entry.get("kind") == "pageerror":
            lines.append(f"[pageerror] {entry.get('message', '')}")
        else:
            loc = entry.get("location") or {}
            url = loc.get("url", "")
            line_no = loc.get("lineNumber", "")
            lines.append(
                f"[{entry.get('type', 'log')}] {entry.get('text', '')}"
                f"  ({url}:{line_no})"
            )
    payload = "\n".join(lines) + "\n"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(payload)
    try:
        allure.attach(
            payload,
            name=f"screenshot_{stem}_{test_name}_browser_log.txt",
            attachment_type=allure.attachment_type.TEXT,
        )
    except Exception:
        pass
    return log_path


def accept_confirm_dialog(
    page: Page,
    *,
    title,
    button: str,
    timeout: float = 10000,
):
    """Accept the in-app confirmation a catalog raises (#196, #197).

    The three catalogs replaced ``window.confirm`` with a ``ConfirmDialog``
    built on ``ModalShell``, so ``page.once("dialog", ...)`` no longer fires -
    a test still relying on it clicks the card button and then silently does
    nothing, and fails later for the wrong reason.

    The drawers are themselves ``role="dialog"``, so a bare
    ``get_by_role("dialog")`` is ambiguous whenever one is open. The modal is
    located by its accessible name instead, which ConfirmDialog wires from its
    heading through ``aria-labelledby``.

    ``title`` takes a string or a compiled pattern; ``button`` is the confirm
    button's exact label (it often repeats the card's, e.g. "Add to project").
    Returns the dialog locator so a caller can assert on its body first.
    """
    dialog = page.get_by_role("dialog", name=title)
    expect(dialog).to_be_visible(timeout=timeout)
    dialog.get_by_role("button", name=button, exact=True).click()
    expect(dialog).to_have_count(0, timeout=timeout)
    return dialog


def leave_agent_badge(page: Page) -> None:
    """Take focus and the pointer off the agent's badge after a chat closes.

    Closing the chat hands focus back to the button that opened it, and the
    badge shows its name label and detach x while it has focus or hover, so
    both would otherwise sit in a canvas capture.
    """
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.mouse.move(0, 400)
    page.wait_for_function(
        "() => !document.querySelector('[aria-label^=\"Open chat with\"]:focus')",
        timeout=5000,
    )


def dismiss_toasts(
    page: Page,
    *,
    timeout: float = 3000,
    quiet_ms: float = 2500,
    max_rounds: int = 8,
) -> int:
    """Close visible toasts and wait for the toast region to go quiet.

    Worth doing before any visual baseline. Toasts are transient, bottom-right,
    and up to 360px wide, so whether one is on screen at capture time depends on
    timing rather than on the behaviour under test - and they sit exactly where
    canvas content usually is. Leaving them in makes the comparison flaky and
    obscures what the baseline is for.

    The *quiet* wait is the part that matters. A node reaching "Done" does not
    mean its follow-up work has finished: the dataset install-save is debounced
    500 ms past it and answers seconds later, so the toasts it raises (a save,
    an install) arrive well after the status flips. A single sweep dismisses
    nothing (there is nothing there yet) and the toast then lands in the
    capture. So sweep, wait ``quiet_ms`` for a late arrival, and sweep again
    until a full window passes with none.

    Never call this before an ASSERTION about a toast - it erases the evidence.
    A "couldn't be generated" warning in particular is a bug rather than routine
    noise (#180); ``test_computed_json_output_e2e.py`` records toasts through a
    MutationObserver and fails on that one.

    Safe to call when there are none. Bounded by *max_rounds*, so a toast that
    genuinely re-fires forever costs a few seconds rather than hanging - it just
    ends up in the screenshot, which is the honest outcome.

    Closes the stack from the bottom up; see the comment on the click for why
    the top of it may be unreachable.
    """
    container = page.locator('[aria-label="Notifications"]')
    dismissed = 0

    for _ in range(max_rounds):
        # Each close click re-renders the list, so re-resolve rather than
        # iterating a stale handle set.
        for _ in range(12):
            buttons = container.locator("button.btn-close")
            if buttons.count() == 0:
                break
            # From the BOTTOM of the stack, not the top. The region is anchored
            # to the bottom of the viewport and grows upward, so once enough
            # toasts are up the oldest is clipped off the TOP of the screen -
            # and a position:fixed element off-screen cannot be scrolled into
            # view, so clicking `first` times out and the sweep returns having
            # closed nothing. `run-all-survives-a-failed-node` ends with five
            # error toasts and lost 26.87% of its frame to exactly that. The
            # last toast is always on screen, and closing it brings the rest
            # down one slot.
            try:
                buttons.last.click(timeout=1000)
                dismissed += 1
            except PlaywrightTimeoutError:
                # Still unreachable - covered, or mid-transition. Close it the
                # way its own button would, so one stuck toast cannot wedge the
                # sweep for every toast behind it.
                try:
                    buttons.last.evaluate("el => el.click()")
                    dismissed += 1
                except Exception:
                    break

        # Did another arrive during the quiet window? wait_for_function resolving
        # means one showed up, so loop and clear it; a timeout means quiet.
        try:
            page.wait_for_function(
                "() => !!document.querySelector('[aria-label=\"Notifications\"] .toast')",
                timeout=quiet_ms,
            )
        except PlaywrightTimeoutError:
            break

    # A close click leaves the pointer where the toast was, often over a card
    # or button whose hover style would then sit in the capture.
    if dismissed:
        page.mouse.move(0, 400)
    return dismissed


#: Whether a missing baseline may be created by this run. Off unless
#: ``--mint-baselines`` was passed (see ``tests/conftest.py``), so no ordinary
#: run - local or CI, serial or parallel - can mint one as a side effect.
#:
#: A module global rather than an environment variable on purpose: an env var
#: survives in a shell and gets inherited by the next run, which is exactly how
#: someone mints without meaning to. A CLI flag has to be typed each time and is
#: recorded in the command.
MINT_BASELINES = False

#: Whether this run re-mints: every capture is compared with its committed
#: baseline, and one whose screen changed is written over it (a missing one is
#: minted). Off unless ``--remint-baselines`` was passed. The CI report page
#: shows each re-minted frame next to the baseline it replaced.
REMINT_BASELINES = False

#: How to ask for baselines, in every message that needs one.
REMINT_HOW = (
    "To make baselines, run `gh workflow run docker-compose.yml --ref <branch> "
    "-f remint=true`, review the frames on that run's curio-ci-report.html, "
    "then commit its reminted-baselines artifact."
)


#: Baselines a re-mint rewrites whatever it finds, named by a part of their
#: file names (``--remint-force``): the frames a fix is known to change by
#: less than REMINT_MIN_RATIO, such as a few words of text.
REMINT_FORCE: tuple = ()


def allow_baseline_writes(*, mint: bool, remint: bool, force=(), environ=os.environ) -> None:
    """Turn on ``--mint-baselines`` / ``--remint-baselines``, on CI only.

    A baseline is what CI renders. A capture from any other machine differs in
    text antialiasing, fonts and scrollbars, and would then fail on CI or hide
    a change there.
    """
    global MINT_BASELINES, REMINT_BASELINES, REMINT_FORCE
    force = tuple(part for part in force if part)
    if force and not remint:
        raise pytest.UsageError("--remint-force only means something with --remint-baselines.")
    if not (mint or remint):
        return
    if environ.get("GITHUB_ACTIONS") != "true":
        flag = "--remint-baselines" if remint else "--mint-baselines"
        raise pytest.UsageError(f"{flag} runs on CI only. {REMINT_HOW}")
    MINT_BASELINES = bool(mint)
    REMINT_BASELINES = bool(remint)
    REMINT_FORCE = force


#: A re-mint leaves a baseline alone when at most this share of its pixels
#: changed, not counting the volatile text below. A fix usually changes far
#: more; one that changes a few words may not, and names its frames with
#: ``--remint-force`` instead. Layout that moves between runs (an id wrapping
#: at another character, a node settling a pixel away) can pass it, so a few
#: frames are re-minted by every run.
REMINT_MIN_RATIO = 0.0005

#: Text a run writes fresh every time, so it differs from any baseline even
#: when the screen is the same: artifact file names (epoch milliseconds and a
#: random suffix), uuids, bare uuid hex and the 8-character short ids, a
#: package id's random segment, dates and times of day, and the app version in
#: the corner, which moves with every commit to main. A re-mint does not count
#: differences inside it, or in the rest of its line, which a token of another
#: width moves; ordinary comparisons still count everything.
VOLATILE_TEXT = (
    r"\b\d{13}_[0-9a-f]{8}\b",
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    r"\b[0-9a-f]{32}\b",
    r"\b(?=[0-9a-f]{0,7}\d)(?=[0-9a-f]{0,7}[a-f])[0-9a-f]{8}\b",
    r"(?<=\.)(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{8,10}(?=@\d)",
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s?[AP]M\b",
    r"^\s*\d+\.\d+\.\d+[\w.+-]*\s*$",
)

# The client boxes of every VOLATILE_TEXT match through the end of its line
# (or of its text node, when that is wrapped rather than broken), relative to
# *root* (the captured element) or to the top-left of the page.
_VOLATILE_BOXES_BODY = """
    const origin = root ? root.getBoundingClientRect() : {left: 0, top: 0};
    const res = patterns.map((p) => new RegExp(p, 'g'));
    const boxes = [];
    const walker = document.createTreeWalker(root || document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const text = node.nodeValue || '';
        if (!text.trim()) continue;
        for (const re of res) {
            re.lastIndex = 0;
            for (let m = re.exec(text); m; m = re.exec(text)) {
                if (!m[0]) { re.lastIndex += 1; continue; }
                const range = document.createRange();
                const lineEnd = text.indexOf('\\n', m.index + m[0].length);
                range.setStart(node, m.index);
                range.setEnd(node, lineEnd === -1 ? text.length : lineEnd);
                for (const r of range.getClientRects()) {
                    if (r.width > 0 && r.height > 0) {
                        boxes.push([r.left - origin.left, r.top - origin.top,
                                    r.right - origin.left, r.bottom - origin.top]);
                    }
                }
            }
        }
    }
    return {boxes, scale: window.devicePixelRatio || 1};
"""
_VOLATILE_BOXES_PAGE_JS = (
    "(patterns) => { window.scrollTo(0, 0); const root = null;" + _VOLATILE_BOXES_BODY + "}"
)
_VOLATILE_BOXES_ELEMENT_JS = "(root, patterns) => {" + _VOLATILE_BOXES_BODY + "}"


def _volatile_boxes(page, clip_selector: str | None) -> list:
    """Pixel boxes of the volatile text in what is about to be captured.

    Never raises: with no boxes a re-mint just counts every difference.
    """
    try:
        if clip_selector is None:
            found = page.evaluate(_VOLATILE_BOXES_PAGE_JS, list(VOLATILE_TEXT))
        else:
            # A missing element is the capture's failure to report, not this one's.
            found = page.locator(clip_selector).first.evaluate(
                _VOLATILE_BOXES_ELEMENT_JS, list(VOLATILE_TEXT), timeout=5000)
        scale = float(found.get("scale") or 1)
        return [tuple(v * scale for v in box) for box in found.get("boxes") or []]
    except Exception:  # noqa: BLE001 - best effort, like the webfont wait
        return []


def _box_mask(boxes, shape):
    """A boolean image of *shape* that is true inside *boxes*, one pixel padded."""
    import math

    import numpy as np

    mask = np.zeros(shape, dtype=bool)
    height, width = shape
    for x0, y0, x1, y1 in boxes:
        left, top = max(0, int(x0) - 1), max(0, int(y0) - 1)
        right, bottom = min(width, math.ceil(x1) + 1), min(height, math.ceil(y1) + 1)
        if right > left and bottom > top:
            mask[top:bottom, left:right] = True
    return mask

#: The app's first font is Rubik, fetched from Google Fonts at runtime
#: (src/index.html). Everything after it in the stack is a system fallback, so
#: whether that fetch lands decides the TYPEFACE, not just the antialiasing: a
#: baseline minted during a CDN hiccup is rendered in Liberation Sans or
#: Helvetica and then disagrees with every later run forever, for a reason no
#: diff percentage explains.
WEBFONT_FAMILY = "Rubik"
WEBFONT_TIMEOUT_MS = 15000


def _wait_for_webfont(page) -> bool:
    """Wait for the app's webfont to finish loading. Returns whether it did.

    Never raises. On a comparison run a missing font will show up as a diff,
    which is the honest outcome; it is the MINT path that must refuse (see
    :func:`_assert_mintable`). Waiting here rather than only when minting means
    both sides of a comparison are quiesced the same way.
    """
    try:
        page.wait_for_function(
            "document.fonts && document.fonts.status === 'loaded'",
            timeout=WEBFONT_TIMEOUT_MS,
        )
    except Exception:  # noqa: BLE001 - a font wait must never fail a test
        pass
    # NOT document.fonts.check(): it answers "would this render?", and with the
    # stylesheet missing there is no @font-face for Rubik at all, so the family
    # resolves straight to a system fallback and check() reports true. Verified
    # by blackholing fonts.googleapis.com: check() said true while the capture
    # came out in a different typeface, 9% off the real baseline.
    #
    # The honest signal is whether a FontFace for the family is actually loaded,
    # which is empty when the stylesheet never arrived.
    try:
        return bool(page.evaluate(
            "(family) => !!document.fonts && "
            "[...document.fonts].some(f => "
            "  (f.family || '').replace(/[\"\']/g, '').includes(family) "
            "  && f.status === 'loaded')",
            WEBFONT_FAMILY,
        ))
    except Exception:  # noqa: BLE001
        return False


def _assert_mintable(image, expected_path: str, page) -> None:
    """Refuse to write a baseline that is obviously not what we came for.

    Two ways a mint goes wrong silently, both of which pass the comparison that
    immediately follows because it compares the capture against itself:

    * the webfont did not load, so the text is in a fallback typeface;
    * the capture is blank - a renderer starved of memory, or an element that
      was 'visible' but not yet painted, yields a single flat colour.

    A wrong baseline is worse than no baseline: it enshrines the defect as
    expected output, which is the whole complaint behind #308 and #333.
    """
    if not _wait_for_webfont(page):
        raise AssertionError(
            f"refusing to mint {os.path.basename(expected_path)}: the "
            f"{WEBFONT_FAMILY} webfont did not load, so this capture is in a "
            f"fallback typeface and would disagree with every later run. Check "
            f"network access to fonts.googleapis.com and re-run."
        )
    if len(image.convert("RGB").getcolors(maxcolors=2) or []) == 1:
        raise AssertionError(
            f"refusing to mint {os.path.basename(expected_path)}: the capture "
            f"is a single flat colour, i.e. blank. The element was reported "
            f"visible but nothing was painted."
        )


#: The most any screenshot comparison may let differ. Two CI captures of the
#: same screen differ by at most about 1.3%, so this leaves room for run-to-run
#: noise and none for a screen that changed. A comparison may ask for less,
#: never more.
MAX_DIFF_RATIO = 0.40  # TMP PROOF: was 0.10; the ceiling tests must fail

#: How long a capture waits for the nodes on the canvas to stop running.
NODE_SETTLE_TIMEOUT_MS = 180_000

_NO_NODE_RUNNING_JS = """(need) => {
    const running = document.querySelectorAll(
        '.react-flow__node [data-curio-node-status="running"]').length;
    window.__curioIdleSamples = running ? 0 : (window.__curioIdleSamples || 0) + 1;
    return window.__curioIdleSamples >= need;
}"""

_RUNNING_NODE_IDS_JS = """() => [...document.querySelectorAll('.react-flow__node')]
    .filter((n) => n.querySelector('[data-curio-node-status="running"]'))
    .map((n) => n.getAttribute('data-id'))"""


def _wait_for_no_node_running(page: Page, *, timeout_ms: int = NODE_SETTLE_TIMEOUT_MS,
                              report_as: str | None = None) -> None:
    """Block until no node on the canvas is running, over three samples in a row.

    A view below a node that just ran draws on its own once the new input
    reaches it, which is after that node reports Done. A capture taken in that
    gap records the view mid-draw: a spinner and an empty body. The draw starts
    a few browser tasks after the upstream node settles, so one idle sample is
    not enough.

    With *report_as*, the nodes found running when the wait begins are noted in
    the test output and the Allure report under that name, so a run the caller
    did not start stays visible even when it ends in time.
    """
    if report_as:
        running = page.evaluate(_RUNNING_NODE_IDS_JS)
        if running:
            note = f"{report_as}: still running when the wait began: {running}"
            print(note)
            try:
                allure.attach(note, name=report_as, attachment_type=allure.attachment_type.TEXT)
            except Exception:
                pass
    page.evaluate("() => { window.__curioIdleSamples = 0; }")
    try:
        page.wait_for_function(_NO_NODE_RUNNING_JS, arg=3, polling=150, timeout=timeout_ms)
    except PlaywrightTimeoutError:
        running = page.evaluate(_RUNNING_NODE_IDS_JS)
        raise AssertionError(
            f"nodes still running after {timeout_ms} ms, so the capture would "
            f"show them mid-run: {running}. Pass allow_running=True only when a "
            "run in progress is what the baseline shows."
        ) from None


class _Comparison(NamedTuple):
    actual_cmp: object
    expected_cmp: object
    diff: object
    arr: object
    counted: object
    mismatched: int
    total: int
    ratio: float


def _compare_images(actual_img, expected_img, pixel_threshold: int) -> _Comparison:
    """Count the pixels where *actual_img* and *expected_img* differ by more than
    *pixel_threshold* in any channel, both resized to the larger of their sizes.
    """
    from PIL import Image, ImageChops
    import numpy as np

    target_w = max(actual_img.width, expected_img.width)
    target_h = max(actual_img.height, expected_img.height)
    actual_cmp = actual_img.resize((target_w, target_h), Image.LANCZOS)
    expected_cmp = expected_img.resize((target_w, target_h), Image.LANCZOS)

    diff = ImageChops.difference(actual_cmp, expected_cmp)
    arr = np.asarray(diff)
    total = int(arr.shape[0] * arr.shape[1])
    counted = (arr > pixel_threshold).any(axis=2)
    mismatched = int(counted.sum())
    ratio = mismatched / total if total else 0.0
    return _Comparison(actual_cmp, expected_cmp, diff, arr, counted, mismatched, total, ratio)


def _remint(page, expected_path, capture, *, clip_selector, pixel_threshold,
            max_diff_ratio, record_args) -> None:
    """Write a fresh capture over its baseline when the screen changed.

    Changed means more than REMINT_MIN_RATIO of the pixels differ outside the
    volatile text, or the baseline is one REMINT_FORCE names. Otherwise the
    baseline stays as committed and the record says ``unchanged``. A re-minted frame is recorded next to the baseline it
    replaced, for the CI report page, and captured a second time: when that
    capture differs from the first by more than the budget the screen had not
    settled, so the old baseline is put back and the test fails.

    The old-versus-new difference never fails the test: showing what changed is
    what a re-mint is for.
    """
    from PIL import Image

    name = os.path.basename(expected_path)
    with open(expected_path, "rb") as handle:
        old_bytes = handle.read()
    old_img = Image.open(BytesIO(old_bytes)).convert("RGB")
    boxes = _volatile_boxes(page, clip_selector)
    try:
        new_img = capture()
    except Exception as exc:
        comparisons.record(
            "capture-error", expected=old_img,
            error=f"{type(exc).__name__}: {exc}", **record_args,
        )
        raise

    cmp = _compare_images(new_img, old_img, pixel_threshold)
    volatile = _box_mask(boxes, cmp.counted.shape) if new_img.size == old_img.size else None
    changed = cmp.counted & ~volatile if volatile is not None else cmp.counted
    remint_ratio = int(changed.sum()) / cmp.total if cmp.total else 0.0
    forced = any(part in name for part in REMINT_FORCE)
    evidence = dict(
        expected=old_img, created=new_img, expected_cmp=cmp.expected_cmp,
        arr=cmp.arr, counted=cmp.counted, volatile=volatile,
        mismatched=cmp.mismatched, total=cmp.total, ratio=cmp.ratio,
        remint_ratio=remint_ratio, remint_min_ratio=REMINT_MIN_RATIO,
        forced=forced,
    )
    if remint_ratio <= REMINT_MIN_RATIO and not forced:
        comparisons.record("unchanged", **evidence, **record_args)
        return

    try:
        _assert_mintable(new_img, expected_path, page)
    except AssertionError as exc:
        comparisons.record("capture-error", error=str(exc), **evidence, **record_args)
        raise
    new_img.save(expected_path)
    try:
        again = capture()
    except Exception as exc:
        with open(expected_path, "wb") as handle:
            handle.write(old_bytes)
        comparisons.record(
            "capture-error", expected=old_img, created=new_img,
            error=f"second capture failed, baseline left as committed: "
                  f"{type(exc).__name__}: {exc}", **record_args,
        )
        raise
    settle = _compare_images(again, new_img, pixel_threshold)
    if settle.ratio > max_diff_ratio:
        with open(expected_path, "wb") as handle:
            handle.write(old_bytes)
        comparisons.record(
            "failed", expected=new_img, created=again,
            expected_cmp=settle.expected_cmp, arr=settle.arr,
            counted=settle.counted, mismatched=settle.mismatched,
            total=settle.total, ratio=settle.ratio,
            error="the screen was still changing: a second capture right "
                  "after the re-mint differs from it, so the baseline was left "
                  "as committed", **record_args,
        )
        raise AssertionError(
            f"not re-minting {name}: a second capture right after differs from "
            f"the first by {settle.ratio:.2%}, over the {max_diff_ratio:.2%} "
            "budget, so the screen had not settled. The baseline is left as "
            "committed."
        )
    comparisons.record(
        "reminted", expected_bytes=old_bytes, recapture_ratio=settle.ratio,
        **evidence, **record_args,
    )


def save_workflow_test_screenshot(
    page: Page,
    workflow_filepath: str,
    *,
    test_name: str,
    pixel_threshold: int = 30,
    max_diff_ratio: float = MAX_DIFF_RATIO,
    fit_reactflow: bool = True,
    clip_selector: str | None = None,
    sweep_toasts: bool = False,
    allow_running: bool = False,
    closeup: bool = False,
    interaction: dict | None = None,
) -> str:
    """Compare or create an expected screenshot for a workflow test.

    If the expected file already exists the current page is captured and
    compared pixel-by-pixel against it.  Both images are resized to the
    same dimensions before comparison so layout-only size changes don't
    cause false positives.  The assertion fails when more than
    *max_diff_ratio* (default 10%) of pixels differ by more than
    *pixel_threshold* (per-channel, 0-255).

    On failure the expected, actual, and diff images are attached to the
    Allure report so that reviewers can inspect the regression directly
    from the GitHub Actions artifact. With ``CURIO_E2E_COMPARE_DIR`` set,
    every comparison, passing or not, is also recorded there for the CI
    report page (see comparisons.py).

    If the file does **not** exist the run FAILS. Creating a baseline is a
    deliberate act, a CI run dispatched with ``remint=true`` (``--mint-baselines``
    and ``--remint-baselines`` refuse to run anywhere else), because whatever
    the app renders that day becomes the definition of correct for every run
    afterwards. Under ``--remint-baselines`` an existing baseline is compared
    and, when its screen changed, rewritten (see :func:`_remint`).

    A baseline captured against a broken build enshrines the bug as expected
    output, and the suite then *defends* it; one captured on another machine
    enshrines that machine. macOS rasterizes text with grayscale antialiasing
    and the runner uses LCD subpixel, so the macOS captures of the two #333
    scenes sat 6.11% and 10.05% from what CI renders, the second past its
    budget.

    Set *fit_reactflow* to ``False`` for pages with no canvas (the projects list,
    the catalog). The default path pins the ReactFlow viewport first, which waits
    on ``.react-flow__node`` and would otherwise spend its whole timeout waiting
    for a node that is never going to exist.

    Pass *clip_selector* when the subject of the baseline is one element rather
    than the page. The capture is then that element's box, so every pixel is
    about the thing under test and the diff budget is spent on it instead of on
    surrounding chrome.

    Pass *sweep_toasts* instead of calling :func:`dismiss_toasts` yourself
    beforehand - and never as well as, each sweep costs its own quiet window.
    Sweeping outside this helper leaves a gap between the region going quiet and
    the shutter: the viewport wait below is seconds on a loaded runner, and an
    error toast now stays until it is dismissed, so anything arriving in that gap
    is in the baseline for good. `run-all-survives-a-failed-node` collected five
    of them that way on CI - 26.87% of a frame whose budget is 5% - while the two
    earlier captures of the same walkthrough, taken before the run that raised
    them, passed.

    The capture waits until no node on the canvas is running, so a view that
    draws on its own after its input arrives is photographed drawn, not
    mid-draw. Pass *allow_running* only when a run in progress is the subject.

    *closeup* only labels the record, for the CI report's Close-ups filter, and
    *interaction* (see :func:`save_interaction_frame`) for its Interaction pairs.

    Returns the path to the expected screenshot file.
    """
    if not 0.0 <= max_diff_ratio <= MAX_DIFF_RATIO:
        raise ValueError(
            f"max_diff_ratio={max_diff_ratio} is above the {MAX_DIFF_RATIO:.0%} "
            "ceiling (MAX_DIFF_RATIO): a comparison may be tighter, never looser"
        )
    from PIL import Image, ImageEnhance

    stem = os.path.splitext(os.path.basename(workflow_filepath))[0]
    os.makedirs(WORKFLOW_SCREENSHOT_EXPECTED_DIR, exist_ok=True)
    filename = f"screenshot_{stem}_{test_name}.png"
    expected_path = os.path.join(WORKFLOW_SCREENSHOT_EXPECTED_DIR, filename)

    if not allow_running:
        _wait_for_no_node_running(page)

    # Pin the ReactFlow viewport to a deterministic fitView before any
    # capture, so baselines and subsequent comparisons share the same
    # zoom/pan regardless of when the in-app setTimeout(fitView) fires.
    if fit_reactflow:
        _wait_for_reactflow_ready(page)

    # After the viewport wait, not before it: this is the last moment the page
    # can be quieted, so it is the only sweep that holds until the capture.
    if sweep_toasts:
        dismiss_toasts(page)

    _wait_for_webfont(page)

    def _capture():
        if clip_selector is not None:
            return _capture_element(page, clip_selector)
        return _capture_full_page(page)

    record_args = dict(
        baseline=expected_path,
        pixel_threshold=pixel_threshold,
        max_diff_ratio=max_diff_ratio,
        capture=f"element {clip_selector}" if clip_selector is not None else "full page",
        closeup=closeup,
        interaction=interaction,
    )

    minted_now = False
    if not os.path.isfile(expected_path):
        if not (MINT_BASELINES or REMINT_BASELINES):
            message = (
                f"no baseline at {expected_path}. {REMINT_HOW} A baseline is "
                "the definition of correct for every later run, so it is not "
                "something a test run should produce as a side effect."
            )
            comparisons.record_missing(_capture, **record_args)
            raise AssertionError(message)
        minted = _capture()
        _assert_mintable(minted, expected_path, page)
        minted.save(expected_path)
        minted_now = True
    elif REMINT_BASELINES:
        _remint(
            page, expected_path, _capture, clip_selector=clip_selector,
            pixel_threshold=pixel_threshold, max_diff_ratio=max_diff_ratio,
            record_args=record_args,
        )
        return expected_path

    expected_img = Image.open(expected_path).convert("RGB")
    try:
        actual_img = _capture()
    except Exception as exc:
        comparisons.record(
            "capture-error", expected=expected_img,
            error=f"{type(exc).__name__}: {exc}", **record_args,
        )
        raise

    cmp = _compare_images(actual_img, expected_img, pixel_threshold)
    actual_cmp, expected_cmp, diff = cmp.actual_cmp, cmp.expected_cmp, cmp.diff
    mismatched, total, ratio = cmp.mismatched, cmp.total, cmp.ratio
    failed = ratio > max_diff_ratio

    comparisons.record(
        "failed" if failed else "minted" if minted_now else "passed",
        expected=expected_img, created=actual_img, expected_cmp=expected_cmp,
        arr=cmp.arr, counted=cmp.counted, mismatched=mismatched, total=total,
        ratio=ratio, **record_args,
    )

    if failed:
        actual_path = os.path.join(
            WORKFLOW_SCREENSHOT_EXPECTED_DIR,
            f"screenshot_{stem}_{test_name}_actual.png",
        )
        actual_img.save(actual_path)

        diff_highlighted = ImageEnhance.Brightness(diff).enhance(3.0)

        allure.attach(
            _image_to_png_bytes(expected_cmp),
            name=f"{filename} — expected",
            attachment_type=allure.attachment_type.PNG,
        )
        allure.attach(
            _image_to_png_bytes(actual_cmp),
            name=f"{filename} — actual",
            attachment_type=allure.attachment_type.PNG,
        )
        allure.attach(
            _image_to_png_bytes(diff_highlighted),
            name=f"{filename} — diff",
            attachment_type=allure.attachment_type.PNG,
        )

        raise AssertionError(
            f"Screenshot regression for {filename}: "
            f"{mismatched}/{total} pixels differ ({ratio:.2%}), "
            f"allowed {max_diff_ratio:.2%}. "
            f"Expected {expected_img.size[0]}x{expected_img.size[1]}, "
            f"actual {actual_img.size[0]}x{actual_img.size[1]}. "
            f"Actual saved to {actual_path}. "
            f"See Allure report attachments for visual diff."
        )
    return expected_path


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


def park_pointer(page: Page) -> None:
    """Move the pointer to the pane's empty bottom-right corner.

    The pointer is wherever the last click left it, and once a node is framed
    that spot can be over its map or its chart.
    """
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    page.mouse.move(viewport["width"] - 10, viewport["height"] - 60)


def frame_nodes(page: Page, node_ids) -> None:
    """Fit the canvas to *node_ids* at up to 100% zoom, the pointer parked first."""
    park_pointer(page)
    # The full-page fit's padding: less lets a tall node's header reach the
    # dataflow title in the canvas's top-left corner.
    _wait_for_reactflow_ready(page, node_ids=list(node_ids), max_zoom=1.0)
