"""Playwright E2E: a test's WebGPU check finds the adapter of a page that draws late.

Every test that needs WebGPU asks through ``utils/webgpu.py`` (``require_webgpu``
or ``webgpu_adapter``), which runs the app's own probe
(``src/utils/webgpuSupport.ts``). CI's Chrome starts a page on GPU compositing
and switches to software compositing once its GPU process is up, and the
switch drops a WebGPU request in flight: it resolves null (#926). The page
draws its first frame only after the switch, so the probe waits up to 10 s for
a drawn frame, then asks, and asks again after a null for 3 s from its first
request.

On a GPU runner that several test jobs share, a freshly launched Chrome can
draw nothing for longer than 10 s (#1017). The probe then asks while the GPU
process is still starting, and the switch drops that request. In #1015's run
39324927016 it came back null at 13784 ms, past the 3 s of retries: "the page
drew no frame in 10000 ms; the browser answered null at 13784 ms". In main's
run 39072275174 it did not come back within the probe's 8 s. Every sighting
was in ``test_shipped_scenario_drops_e2e``, which asks on an empty dataflow
right after sign-in, before the page has drawn. The page draws right after
the switch, so a probe whose wait ran out and that found no adapter with
every request made before the page drew waits for a frame once more, and asks
again once one comes; the helper runs the probe again only when the page drew
nothing through that wait too.

These tests play that GPU process. An init script holds the page's animation
frames back once a test switches it on, as a page that draws nothing does, and
stands in for ``navigator.gpu``. A request made while frames are held waits
for the switch, which comes a set time after that request, answers it null and
lets frames come. A request made after the switch gets an adapter. Each test
opens an empty dataflow, as the shipped scenario drops do, and asks with
``webgpu_adapter``. The last test checks that a browser with no adapter is
still told it has none.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_webgpu_adapter_e2e.py -v
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    webgpu_adapter,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: When the switch comes after the request made while the page drew nothing:
#: as in #1015's run, where the request made at the end of the 10 s frame wait
#: came back null at 13784 ms, after the probe's 3 s of retries.
NULL_AFTER_THE_RETRIES_MS = 3_784

#: Past the 8 s the probe gives one request, as in main's run 39072275174.
NO_ANSWER_IN_8_S_MS = 9_000

#: The probe waits 10 s for a drawn frame before it asks. A first request made
#: sooner than this after frames were held means the page had drawn already.
ASKED_AFTER_MS = 9_000

#: How long the check may take to call a browser with no adapter missing. The
#: frame wait, the dropped request and the probe's 3 s of retries once the page
#: draws come to about 17 s.
NO_ADAPTER_WITHIN_S = 40

EMPTY = {"dataflow": {
    "name": "Elsewhere", "task": "", "timestamp": 1789193389280,
    "provenance_id": "Elsewhere", "nodes": [], "edges": [],
}}

# Before the app's own scripts. Once a test switches it on, it holds the page's
# animation frames back, as test_frame_nodes_e2e.py does, and plays Chrome
# while its GPU process starts: a request made while frames are held waits for
# the switch to software compositing. The switch comes switchAfterMs after the
# first such request; it answers every waiting request null, then lets frames
# come. A request made after the switch gets an adapter, or null for a browser
# that has none. Each request is logged, timed from the switch-on.
_SLOW_GPU_START_JS = """(() => {
    const request = window.requestAnimationFrame.bind(window);
    const cancel = window.cancelAnimationFrame.bind(window);
    let held = null;
    let nextId = -1;
    window.requestAnimationFrame = (callback) => {
        if (!held) return request(callback);
        const id = nextId--;
        held.set(id, callback);
        return id;
    };
    window.cancelAnimationFrame = (id) => {
        if (held && held.delete(id)) return;
        cancel(id);
    };
    const gpu = window.__curioTestGpu = { log: [], since: 0, switchAfterMs: 0, hasAdapter: true };
    const note = (what) => gpu.log.push({ what, ms: Date.now() - gpu.since });
    let waiting = [];
    let switchTimer = null;
    const switchToSoftware = () => {
        const dropped = waiting;
        waiting = [];
        dropped.forEach((resolve) => {
            note('dropped');
            resolve(null);
        });
        const deferred = held ? [...held.values()] : [];
        held = null;
        deferred.forEach((callback) => request(callback));
    };
    Object.defineProperty(navigator, 'gpu', {
        configurable: true,
        value: {
            getPreferredCanvasFormat: () => 'bgra8unorm',
            requestAdapter: () => {
                if (held) {
                    note('held');
                    if (switchTimer === null) switchTimer = setTimeout(switchToSoftware, gpu.switchAfterMs);
                    return new Promise((resolve) => waiting.push(resolve));
                }
                const adapter = gpu.hasAdapter ? {} : null;
                note(adapter ? 'an adapter' : 'null');
                return Promise.resolve(adapter);
            },
        },
    });
    window.__curioTestSlowGpuStart = ({ switchAfterMs, hasAdapter }) => {
        gpu.since = Date.now();
        gpu.switchAfterMs = switchAfterMs;
        gpu.hasAdapter = hasAdapter;
        held = new Map();
    };
})();"""

# A frame asked for now: whether it ran tells whether the page draws.
_ASK_FOR_A_FRAME_JS = """() => {
    window.__curioTestFrameRan = false;
    window.requestAnimationFrame(() => { window.__curioTestFrameRan = true; });
}"""


def _open_empty_dataflow(page, frontend_url: str, backend_url: str, *, username: str) -> None:
    """Sign in and open an empty dataflow, where the shipped scenario drops ask,
    and wait until the page draws: the slow start is the test's, not the runner's."""
    page.context.add_init_script(_SLOW_GPU_START_JS)
    stub_login_and_enter_workflow(
        page,
        frontend_url=frontend_url,
        backend_url=backend_url,
        name="WebGPU Adapter",
        username=username,
        project_name="Elsewhere",
        project_spec=EMPTY,
    )
    require_owner_view(page)
    assert page.evaluate("() => typeof window.__curioTestSlowGpuStart === 'function'"), (
        "the init script that plays the GPU process is not in the page"
    )
    page.evaluate(_ASK_FOR_A_FRAME_JS)
    page.wait_for_function("() => window.__curioTestFrameRan === true", polling=100, timeout=60000)


def _ask_while_the_gpu_starts(page, *, switch_after_ms: int, has_adapter: bool):
    """Hold frames back, ask as a test does, and return the answer, the
    requests the page saw and how long the check took."""
    page.evaluate(
        "(options) => window.__curioTestSlowGpuStart(options)",
        {"switchAfterMs": switch_after_ms, "hasAdapter": has_adapter},
    )
    started = time.monotonic()
    answer = webgpu_adapter(page)
    took = time.monotonic() - started
    return answer, page.evaluate("() => window.__curioTestGpu.log"), took


def _said(log: list[dict]) -> str:
    return ", ".join(f"{entry['what']} at {entry['ms']} ms" for entry in log) or "none"


def _assert_asked_before_the_page_drew(log: list[dict]) -> None:
    assert log and log[0]["what"] == "held", (
        f"no adapter request waited for the switch, so this test proves nothing: {_said(log)}"
    )
    assert log[0]["ms"] >= ASKED_AFTER_MS, (
        f"the probe asked {log[0]['ms']} ms after frames were held, before its wait for a "
        f"frame could end, so the page had drawn already and this test proves nothing: {_said(log)}"
    )


@pytest.mark.parametrize(
    "switch_after_ms",
    [
        pytest.param(NULL_AFTER_THE_RETRIES_MS, id="null-after-the-retries"),
        pytest.param(NO_ANSWER_IN_8_S_MS, id="no-answer-in-8-s"),
    ],
)
def test_the_adapter_is_found_when_the_page_draws_its_first_frame_after_the_probe_asked(
    app_frontend: "FrontendPage", current_server: str, page, switch_after_ms: int,
):
    require_project_page()
    require_user_auth()
    _open_empty_dataflow(
        page, app_frontend.base_url, current_server, username=f"webgpu_adapter_{switch_after_ms}",
    )

    answer, log, _took = _ask_while_the_gpu_starts(page, switch_after_ms=switch_after_ms, has_adapter=True)

    _assert_asked_before_the_page_drew(log)
    assert answer, (
        "the check found no adapter in a browser that has one, whose page drew its first frame "
        f"{switch_after_ms} ms after the probe asked: {answer} (requests: {_said(log)})"
    )
    assert "drew no frame" in str(answer), (
        f"the answer's record leaves out the probe that asked before the page drew: {answer}"
    )


def test_a_browser_with_no_adapter_still_has_none_once_its_page_draws(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    _open_empty_dataflow(page, app_frontend.base_url, current_server, username="webgpu_adapter_none")

    answer, log, took = _ask_while_the_gpu_starts(
        page, switch_after_ms=NULL_AFTER_THE_RETRIES_MS, has_adapter=False,
    )

    _assert_asked_before_the_page_drew(log)
    assert not answer, f"a browser with no adapter was found to have one: {answer} (requests: {_said(log)})"
    assert took < NO_ADAPTER_WITHIN_S, (
        f"the check took {took:.1f} s to call a browser with no adapter missing, not under "
        f"{NO_ADAPTER_WITHIN_S} s: {answer} (requests: {_said(log)})"
    )
