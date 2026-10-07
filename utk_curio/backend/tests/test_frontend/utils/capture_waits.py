"""What a capture waits for first: the viewport fit, toasts swept away, the
webfont, and no node running.
"""

import allure
from playwright.sync_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
)


#: How often the viewport wait reads the viewport, in ms. On a timer, never per
#: animation frame: a browser on a loaded GPU runner can go tens of seconds
#: without drawing one.
VIEWPORT_READ_MS = 100

# One read of the viewport wait. It fits the canvas through the hook
# MainCanvas.tsx (and the dashboard) expose, which sets the viewport at once and
# returns it, or null while a node it frames is not measured yet. It fits again
# whenever React Flow's viewport is no longer the one the fit set (the
# canvas's own load fit lands later, say), and passes once that viewport, as
# the page draws it, has held for *reads* reads in a row.
_FIT_AND_HOLD_JS = """({ options, reads }) => {
    const fit = window.__curio_fitViewWithMenuOffset;
    const flow = window.__curio_reactFlow;
    if (typeof fit !== 'function' || !flow) return false;
    const wait = window.__curio_fitWait = window.__curio_fitWait || { target: null, shown: null, held: 0 };
    const at = flow.getViewport();
    const target = wait.target;
    if (!target || at.x !== target.x || at.y !== target.y || at.zoom !== target.zoom) {
        const set = fit(options);
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
}"""

_FIT_WAIT_STATE_JS = """() => ({
    hook: typeof window.__curio_fitViewWithMenuOffset,
    fitSet: (window.__curio_fitWait || {}).target || null,
    viewport: window.__curio_reactFlow ? window.__curio_reactFlow.getViewport() : null,
    drawn: [...document.querySelectorAll('.react-flow__viewport')].map((v) => v.style.transform),
})"""


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
    (``test_frame_nodes_e2e.py`` holds the frames back).
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
    try:
        page.wait_for_function(
            _FIT_AND_HOLD_JS,
            arg={"options": options, "reads": stable_reads},
            polling=VIEWPORT_READ_MS,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"the canvas viewport did not hold where the fit set it within {timeout_ms} ms "
            f"(fit {options}): {page.evaluate(_FIT_WAIT_STATE_JS)}"
        ) from None
    page.evaluate("() => { delete window.__curio_fitWait; }")


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
