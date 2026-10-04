"""Whole-run (Run All) state, and holding a run open on purpose."""

import re

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


# ---------------------------------------------------------------------------
# Whole-run (Run All) state
# ---------------------------------------------------------------------------

#: The Run All control is ONE button whose accessible name flips with the run
#: (``ToolsMenu.tsx``: ``aria-label={isRunActive ? "Cancel run" : "Run all nodes"}``).
#: A locator written for one of the two names stops matching the moment the run
#: changes state, so a click on it can wait out its whole budget for an element
#: that is right there - the CI signature is a timeout with no "locator resolved
#: to" line in the call log. Match either name and read the state from
#: ``data-run-active``, never from which locator happens to resolve.
RUN_ALL_BUTTON_NAME = re.compile(r"^(Run all nodes|Cancel run)$")

#: The same element, for JS that has to reach it inside the page.
RUN_ALL_BUTTON_SELECTOR = (
    '#tools-menu button[aria-label="Run all nodes"], '
    '#tools-menu button[aria-label="Cancel run"]'
)


def run_all_button(page):
    """The Run All / Cancel button, in whichever state it currently is."""
    return page.get_by_role("button", name=RUN_ALL_BUTTON_NAME)


# Record every transition of the run guard, so a test can prove a run STARTED
# without having to catch it mid-flight. A run whose nodes all report in the
# tick they were triggered is over before any locator can resolve - there is no
# minimum in-flight window (providers/flow/usePlayAll.ts sets isRunActive true in playAllNodes
# and false in finishPlayAll, which fires as soon as the last node of the last
# level reports). Mutation records survive that; a locator cannot.
#
# Counted off ``record.oldValue`` rather than the live attribute: several
# mutations can arrive in one callback, and reading the DOM then reports only
# the final state. The attribute is either absent or "true", so a record whose
# oldValue was "true" is an end and any other record is a start.
#
# Observed on ``#tools-menu`` with subtree, so a re-created button is still
# watched.
_WATCH_RUN_ALL_JS = """() => {
    const root = document.querySelector('#tools-menu');
    if (!root) return false;
    if (window.__curioRunWatch) window.__curioRunWatch.observer.disconnect();
    const watch = { started: 0, ended: 0 };
    watch.observer = new MutationObserver((records) => {
        for (const record of records) {
            if (record.attributeName !== 'data-run-active') continue;
            if (record.oldValue === 'true') watch.ended += 1;
            else watch.started += 1;
        }
    });
    watch.observer.observe(root, {
        subtree: true,
        attributes: true,
        attributeFilter: ['data-run-active'],
        attributeOldValue: true,
    });
    window.__curioRunWatch = watch;
    return true;
}"""

_READ_RUN_WATCH_JS = """() => window.__curioRunWatch
    ? { started: window.__curioRunWatch.started,
        ended: window.__curioRunWatch.ended }
    : null"""


def watch_run_all(page) -> None:
    """Start recording run-guard transitions. Call BEFORE clicking Run All."""
    assert page.evaluate(_WATCH_RUN_ALL_JS), (
        "#tools-menu is not on the page; there is nothing to watch a run on"
    )


def wait_for_run_all_to_end(page, *, timeout_ms: int = 180000,
                            start_timeout_ms: int = 15000) -> dict:
    """Wait for the run :func:`watch_run_all` is watching to start and end.

    Returns ``{"started": n, "ended": n}``. Both halves of #271 without catching
    the run mid-flight: ``started`` says the click was accepted, so the guard
    had been released, and the wait says the run ended on its own rather than
    wedging every later click.

    The two waits are separate so a refused click fails in *start_timeout_ms*
    rather than sitting out the whole run budget - a guard that was never
    released is not going to release itself three minutes later.
    """
    try:
        page.wait_for_function(
            "() => (window.__curioRunWatch?.started || 0) > 0",
            timeout=start_timeout_ms,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            "Run All was never accepted: the run guard never went active "
            f"within {start_timeout_ms} ms of the click. That is #271 - the "
            "click was refused or silently dropped."
        ) from None
    try:
        page.wait_for_function(
            f"() => {{ const b = document.querySelector({RUN_ALL_BUTTON_SELECTOR!r});"
            " return !!b && b.getAttribute('data-run-active') !== 'true'; }",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"the run did not end within {timeout_ms} ms (guard transitions: "
            f"{page.evaluate(_READ_RUN_WATCH_JS)}); a node is holding its level"
        ) from None
    return page.evaluate(_READ_RUN_WATCH_JS)


def run_all_and_wait(page, *, timeout_ms: int = 180000) -> dict:
    """Click Run All, prove the run started, and wait for it to end."""
    watch_run_all(page)
    run_all_button(page).click()
    return wait_for_run_all_to_end(page, timeout_ms=timeout_ms)


def wait_for_run_guard_released(page, *, timeout_ms: int) -> None:
    """Block until no run holds the run guard.

    Playing one node runs its stale ancestors too (``playNodesUpTo``), and it
    takes the same guard as Run All (``isRunActive``, mirrored on the Run All
    button as ``data-run-active``). The played node can report Done before that
    run ends: an Autark map that already drew from its input stays Done while
    the ancestors it waits on re-run. Waiting on the guard waits for the whole
    run the click started.
    """
    try:
        page.wait_for_function(
            f"() => {{ const b = document.querySelector({RUN_ALL_BUTTON_SELECTOR!r});"
            " return !b || b.getAttribute('data-run-active') !== 'true'; }",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"the run a node's Play started did not end within {timeout_ms} ms"
        ) from None


# ---------------------------------------------------------------------------
# Holding a run open on purpose
# ---------------------------------------------------------------------------

# Every node execution leaves the browser as one POST: Python and data-loading
# nodes through ``/processPythonCode`` (PythonInterpreter.ts) and an Autark data
# section through ``/processJavaScriptCode`` (JavaScriptInterpreter.ts). A level
# cannot advance until its nodes report, so holding those requests holds the
# run - which is how a test that needs the button to say "Cancel run" gets a
# window it owns instead of one it races.
#
# Wrapped in the page rather than through ``page.route``: the sync API runs a
# route handler on the dispatcher thread, so blocking in one blocks the very
# wait it was supposed to make winnable.
_HOLD_NODE_EXEC_JS = r"""() => {
    if (window.__curioHeldExec) return true;
    const real = window.fetch.bind(window);
    const state = { real, held: [], seen: 0 };
    window.__curioHeldExec = state;
    window.fetch = (input, init) => {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        if (!/\/process(Python|JavaScript)Code/.test(url)) return real(input, init);
        state.seen += 1;
        return new Promise((resolve, reject) => {
            state.held.push(() => real(input, init).then(resolve, reject));
        });
    };
    return true;
}"""

_RELEASE_NODE_EXEC_JS = """() => {
    const state = window.__curioHeldExec;
    if (!state) return 0;
    window.fetch = state.real;
    window.__curioHeldExec = null;
    const waiting = state.held.length;
    for (const send of state.held) send();
    return waiting;
}"""


def hold_node_execution(page) -> None:
    """Hold every node-execution request in the page until it is released.

    Gives the caller a run that provably cannot end: the level's nodes are
    waiting on a request that has not been sent yet. Always pair it with
    :func:`release_node_execution`, including on the failure path - a hold left
    standing costs the run its whole timeout.
    """
    page.evaluate(_HOLD_NODE_EXEC_JS)


def wait_for_held_node_execution(page, *, count: int = 1,
                                 timeout_ms: int = 60000) -> None:
    """Wait until at least *count* node executions are being held.

    Also the tripwire for the hold itself: if node execution ever stops going
    through ``fetch``, this fails loudly instead of quietly leaving the test
    racing the run again.
    """
    try:
        page.wait_for_function(
            "(n) => (window.__curioHeldExec?.held.length || 0) >= n",
            arg=count,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"no run was held: {held_node_executions(page)} of {count} node "
            "execution(s) are waiting. Either the run never started, or node "
            "execution no longer goes out over window.fetch as "
            "/processPythonCode or /processJavaScriptCode."
        ) from None


def held_node_executions(page) -> int:
    """How many node executions are held right now (0 when not holding)."""
    return int(page.evaluate(
        "() => window.__curioHeldExec ? window.__curioHeldExec.held.length : 0"
    ))


def release_node_execution(page) -> int:
    """Send every held request and stop holding. Returns how many were let go."""
    return int(page.evaluate(_RELEASE_NODE_EXEC_JS))
