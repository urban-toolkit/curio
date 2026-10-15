"""Whether the browser has a WebGPU adapter, asked the way the app asks.

One ``requestAdapter()`` can answer null where the next one, a moment later,
answers with an adapter. The app's probe (``src/utils/webgpuSupport.ts``,
#272) is built for that: it asks again after 150 ms, doubles the wait up to
1 s, calls the adapter missing after 3 s of null answers, and bounds the whole
probe at 8 s. A test that asks once fails where the app would have drawn: on
the GPU runners Chrome sometimes drops a first request (the browser log then
says "A valid external Instance reference no longer exists."), most often
while several jobs share the one GPU.

So every e2e test asks here, by the probe's rule and with its numbers. A
browser that answers null for the whole 3 s has no adapter for the app either.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass

import pytest

#: webgpuSupport.ts's WEBGPU_ADAPTER_RETRY_DELAY_MS, WEBGPU_ADAPTER_RETRY_MAX_DELAY_MS,
#: WEBGPU_ADAPTER_RETRY_BUDGET_MS and WEBGPU_PROBE_TIMEOUT_MS, which these follow.
ADAPTER_PROBE = {
    "delay": 150,
    "maxDelay": 1_000,
    "budget": 3_000,
    "timeout": 8_000,
}

#: ``async (gpu, ADAPTER_PROBE) => ({ adapter, answers })``: ``requestAdapterUntil``
#: and ``probe`` of webgpuSupport.ts, returning the adapter itself (null when
#: none came) and every answer with when it came.
REQUEST_ADAPTER_JS = """async (gpu, { delay, maxDelay, budget, timeout }) => {
    const started = Date.now();
    const answers = [];
    const note = (answer) => answers.push(`${answer} at ${Date.now() - started} ms`);
    const until = async (deadline) => {
        let wait = delay;
        for (;;) {
            let adapter;
            try {
                adapter = await gpu.requestAdapter();
            } catch (err) {
                note(`rejected (${(err && err.message) || err})`);
                return null;
            }
            note(adapter ? "an adapter" : "null");
            if (adapter) return adapter;
            if (Date.now() + wait >= deadline) return null;
            await new Promise((resolve) => setTimeout(resolve, wait));
            wait = Math.min(wait * 2, maxDelay);
        }
    };
    let timer = null;
    const timedOut = new Promise((resolve) => {
        timer = setTimeout(() => { note("no answer"); resolve(null); }, timeout);
    });
    try {
        return { adapter: await Promise.race([until(started + budget), timedOut]), answers };
    } finally {
        clearTimeout(timer);
    }
}"""

# The probe's first checks, then the adapter requests. Only a yes or no leaves
# the page, with the answers.
_ASK_JS = """async (probe) => {
    let gpu;
    try {
        gpu = navigator.gpu;
    } catch (err) {
        return { adapter: false, answers: [`navigator.gpu threw (${(err && err.message) || err})`] };
    }
    if (!gpu) {
        return { adapter: false, answers: [window.isSecureContext === false ? "no navigator.gpu on an insecure page" : "no navigator.gpu"] };
    }
    if (typeof gpu.requestAdapter !== "function" || typeof gpu.getPreferredCanvasFormat !== "function") {
        return { adapter: false, answers: ["an incomplete WebGPU implementation"] };
    }
    const { adapter, answers } = await (REQUEST_ADAPTER_JS)(gpu, probe);
    return { adapter: !!adapter, answers };
}""".replace("REQUEST_ADAPTER_JS", REQUEST_ADAPTER_JS)


class WebGpuAdapterRetried(UserWarning):
    """The browser answered null before it gave an adapter: the wait was needed."""


@dataclass(frozen=True)
class WebGpuAnswer:
    """What the browser answered, request by request; true when one gave an adapter."""

    adapter: bool
    answers: tuple[str, ...]

    def __bool__(self) -> bool:
        return self.adapter

    def __str__(self) -> str:
        return "the browser answered " + ", ".join(self.answers)


def webgpu_adapter(page) -> WebGpuAnswer:
    """Ask for a WebGPU adapter as the app does; the answer is true when one came.

    When it came after a null, a ``WebGpuAdapterRetried`` warning says so in
    the run's warnings summary.
    """
    found = page.evaluate(_ASK_JS, ADAPTER_PROBE)
    answer = WebGpuAnswer(bool(found["adapter"]), tuple(found["answers"]))
    if answer and len(answer.answers) > 1:
        warnings.warn(str(answer), WebGpuAdapterRetried, stacklevel=2)
    return answer


def require_webgpu(page) -> None:
    """Go on with a WebGPU adapter. Without one, fail on CI's GPU job
    (``CURIO_REQUIRE_HARDWARE_WEBGPU=1``) and skip anywhere else."""
    answer = webgpu_adapter(page)
    if answer:
        return
    if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
        pytest.fail(f"CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter: {answer}")
    pytest.skip(f"Autark needs a WebGPU adapter, and this browser has none: {answer}")
