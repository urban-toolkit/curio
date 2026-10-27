"""What a capture waits for first: the viewport fit, toasts swept away, the
webfont, and no node running. Also a viewport that has landed after a move.
"""

import time

import allure
from playwright.sync_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
)


#: How often the viewport wait reads the viewport, in ms. On a timer, never per
#: animation frame: a browser on a loaded GPU runner can go tens of seconds
#: without drawing one.
VIEWPORT_READ_MS = 100

#: How many reads the viewport wait makes before it gives up: what 10 s allowed
#: at one read every ``VIEWPORT_READ_MS``. The page counts them, so a long task
#: on its main thread (decoding a large raster, #932) delays the reads without
#: using them up.
VIEWPORT_MAX_READS = 100

#: The most the viewport wait takes in wall-clock time, for a page that stops
#: answering.
VIEWPORT_WALL_CAP_MS = 120_000

# One read of the viewport wait. It fits the canvas through the hook
# MainCanvas.tsx (and the dashboard) expose, which measures the nodes React Flow
# has not measured yet, sets the viewport at once and returns it, or null while
# a node it frames has no size. It fits again
# whenever React Flow's viewport is no longer the one the fit set (the
# canvas's own load fit lands later, say), and passes once that viewport, as
# the page draws it, has held for *reads* reads in a row. It counts its reads,
# and returns false while it waits, then 'held', or 'out of reads' once it has
# made *maxReads*. Its record on window.__curio_fitWait says how the wait went.
_FIT_AND_HOLD_JS = """({ options, reads, maxReads }) => {
    const wait = window.__curio_fitWait = window.__curio_fitWait || {
        target: null, shown: null, held: 0,
        reads: 0, fits: 0, mostHeld: 0, lastReadAt: null, longestGapMs: 0,
    };
    const now = performance.now();
    if (wait.lastReadAt !== null) wait.longestGapMs = Math.max(wait.longestGapMs, now - wait.lastReadAt);
    wait.lastReadAt = now;
    wait.reads += 1;
    const holds = (() => {
        const fit = window.__curio_fitViewWithMenuOffset;
        const flow = window.__curio_reactFlow;
        if (typeof fit !== 'function' || !flow) return false;
        const at = flow.getViewport();
        const target = wait.target;
        if (!target || at.x !== target.x || at.y !== target.y || at.zoom !== target.zoom) {
            const set = fit(options);
            wait.fits += 1;
            wait.target = set ? { x: set.x, y: set.y, zoom: set.zoom } : null;
            wait.shown = null;
            wait.held = 0;
            return false;
        }
        const viewport = document.querySelector('.react-flow__viewport');
        const shown = viewport ? viewport.style.transform : '';
        if (!shown || shown !== wait.shown) {
            wait.shown = shown;
            wait.held = 1;
            return false;
        }
        wait.held += 1;
        return wait.held >= reads;
    })();
    wait.mostHeld = Math.max(wait.mostHeld, wait.held);
    if (holds) return 'held';
    return wait.reads >= maxReads ? 'out of reads' : false;
}"""

_FIT_WAIT_STATE_JS = """() => {
    const wait = window.__curio_fitWait || {};
    return {
        hook: typeof window.__curio_fitViewWithMenuOffset,
        fitSet: wait.target || null,
        viewport: window.__curio_reactFlow ? window.__curio_reactFlow.getViewport() : null,
        drawn: [...document.querySelectorAll('.react-flow__viewport')].map((v) => v.style.transform),
        unmeasured: window.__curio_reactFlow
            ? window.__curio_reactFlow.getNodes()
                .filter((n) => !(n.width > 0 && n.height > 0) && !(n.style && n.style.display === 'none'))
                .map((n) => n.id)
            : null,
        reads: wait.reads || 0,
        fits: wait.fits || 0,
        held: wait.held || 0,
        mostHeld: wait.mostHeld || 0,
        longestGapMs: Math.round(wait.longestGapMs || 0),
    };
}"""


def _did_not_hold(page: Page, options: dict, stable_reads: int, limit: str, took_s: float) -> str:
    """Why the viewport wait gave up, from its record in the page."""
    state = page.evaluate(_FIT_WAIT_STATE_JS)
    reads, fits = state.pop("reads"), state.pop("fits")
    held, most_held = state.pop("held"), state.pop("mostHeld")
    gap_ms = state.pop("longestGapMs")
    return (
        f"the canvas viewport did not hold where the fit set it within {limit} (fit {options}): "
        f"{reads} reads in {took_s:.1f} s, {max(fits - 1, 0)} re-fits, held for {held} of the "
        f"{stable_reads} reads it needs at the end ({most_held} at most), longest gap between "
        f"reads {gap_ms} ms: {state}"
    )


def _wait_for_reactflow_ready(
    page: Page,
    *,
    padding: float = 0.2,
    stable_reads: int = 3,
    timeout_ms: int = 10000,
    node_ids: list[str] | None = None,
    max_zoom: float | None = None,
) -> None:
    """Fit the canvas, and wait until its viewport holds where the fit set it.

    With *node_ids* the fit frames only those nodes, at most *max_zoom*.

    Without this, ``save_workflow_test_screenshot`` races the app-side
    ``fitView`` call in ``useWorkflowOperations`` (which runs on a
    ``setTimeout`` after the workflow is uploaded). The screenshot can
    fire before the transform has been applied, producing a pre-fit
    canvas where nodes overflow the viewport.

    It needs no animation frame, which a browser on a loaded GPU runner can go
    tens of seconds without. The fit goes through
    ``window.__curio_fitViewWithMenuOffset`` (``MainCanvas.tsx``), which sets a
    fit without a duration at once and returns the viewport it set; React
    Flow's ``setViewport`` would land it a frame or two later, through a d3
    transition. The viewport is then read every ``VIEWPORT_READ_MS``, not once
    a frame, until React Flow's viewport is the one the fit set and the page
    has drawn the same transform for *stable_reads* reads in a row
    (``test_frame_nodes_e2e.py`` holds the frames back). The hook also measures
    the nodes React Flow has not measured yet: React Flow measures a node only
    when the page draws a frame, and a freshly launched Chrome on a GPU runner
    that four test jobs shared drew none for more than 10 s (#1012).

    It gives up after ``VIEWPORT_MAX_READS`` reads rather than after a time.
    The reads run on the page's main thread, and one long task there (decoding
    a large raster, #932) used to leave the wait fewer reads than a pass needs
    inside its 10 s, with the viewport long settled. A page that stops
    answering still fails after ``VIEWPORT_WALL_CAP_MS``. *timeout_ms* bounds
    the wait for a first node.
    """
    page.wait_for_function(
        "() => document.querySelectorAll('.react-flow__node').length > 0",
        polling=VIEWPORT_READ_MS,
        timeout=timeout_ms,
    )

    options: dict = {"padding": padding, "duration": 0, "includeHiddenNodes": True}
    if node_ids:
        options["nodes"] = [{"id": node_id} for node_id in node_ids]
    if max_zoom is not None:
        options["maxZoom"] = max_zoom
    page.evaluate("() => { delete window.__curio_fitWait; }")
    started = time.monotonic()
    try:
        outcome = page.wait_for_function(
            _FIT_AND_HOLD_JS,
            arg={"options": options, "reads": stable_reads, "maxReads": VIEWPORT_MAX_READS},
            polling=VIEWPORT_READ_MS,
            timeout=VIEWPORT_WALL_CAP_MS,
        ).json_value()
    except PlaywrightTimeoutError:
        outcome = None
    if outcome != "held":
        limit = f"{VIEWPORT_MAX_READS} reads" if outcome else f"{VIEWPORT_WALL_CAP_MS} ms"
        raise AssertionError(
            _did_not_hold(page, options, stable_reads, limit, time.monotonic() - started)
        )
    page.evaluate("() => { delete window.__curio_fitWait; }")


#: React Flow's viewport, and whether a move of it has yet to land. React Flow
#: moves the view through a d3 transition on the element it zooms, the
#: canvas's `.react-flow__renderer`, and d3 keeps the transitions scheduled or
#: running on an element in its `__transition` until they end.
_VIEWPORT_MOVE_JS = """() => {
    const canvas = document.querySelector('.react-flow');
    const pane = canvas && canvas.querySelector('.react-flow__renderer');
    return {viewport: window.__curio_reactFlow.getViewport(), moving: !!(pane && pane.__transition)};
}"""


def settled_viewport(page: Page, *, timeout_ms: int = 30000) -> dict:
    """React Flow's viewport once its moves have landed: no d3 transition is
    left on the canvas, and two reads 250 ms apart agree.

    A move set through React Flow's ``setViewport`` (a fit, a zoom onto a
    node, a put-back) is a d3 transition, which moves only when the browser
    draws a frame. A loaded runner can draw none for longer than 250 ms, so
    two equal reads alone can catch a zoom halfway (the node card zoom test,
    10-20 and 10-27). Every read is on a timer, so the wait itself needs no
    frame."""
    last = None
    waited = 0
    while True:
        now = page.evaluate(_VIEWPORT_MOVE_JS)
        if not now["moving"] and now["viewport"] == last:
            return last
        last = None if now["moving"] else now["viewport"]
        if waited >= timeout_ms:
            break
        page.wait_for_timeout(250)
        waited += 250
    raise AssertionError(
        f"the canvas viewport did not land in {timeout_ms} ms: last read {now['viewport']}, "
        f"{'a move still under way' if now['moving'] else 'still moving'}"
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
