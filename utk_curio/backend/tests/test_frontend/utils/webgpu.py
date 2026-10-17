"""Whether the browser has a WebGPU adapter, asked by the app's own probe.

Every e2e test asks through the page's ``window.__curio_probeWebGpu``, the
probe of ``src/utils/webgpuSupport.ts``, so the rule lives in one place. The
probe waits until the page has drawn a frame (at most 10 s), then asks for an
adapter, asks again after a null (150 ms, doubling to 1 s, for 3 s), and gives
up on a request that has not answered in 8 s.

The frame wait is for Chrome's switch to software compositing. CI's headless
Chrome starts a page on GPU compositing and switches once its GPU process is
up, and the switch drops a request in flight: it resolves null, and the
browser log says "A valid external Instance reference no longer exists."
While several jobs share the one GPU, the GPU process can take 4 to 9 s to
start. A test that asked before the page drew (the shipped scenario drops, on
an empty dataflow) saw its first request wait that long and come back null
after the 3 s of retries. The page draws its first frame only after the
switch, so a request made once a frame is drawn is past it.

A browser that answers null for the whole 3 s has no adapter for the app
either.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

#: ``async () => ({ adapter, frame, answers, reason })``: one probe of the
#: app's, and its record: when the page drew (absent when it had drawn
#: already) and each request's answer, timed from the start of the probe.
PROBE_JS = """async () => {
    const support = await window.__curio_probeWebGpu();
    return {
        adapter: !!support.supported,
        frame: support.frame || null,
        answers: support.answers || [],
        reason: support.reason || null,
    };
}"""

_HOOK_READY_JS = "() => typeof window.__curio_probeWebGpu === 'function'"

#: The bundle defines the hook as it loads, long before a test asks.
_HOOK_TIMEOUT_MS = 30_000


class WebGpuAdapterRetried(UserWarning):
    """The browser answered null before it gave an adapter: the retry was needed."""


@dataclass(frozen=True)
class WebGpuAnswer:
    """What the probe saw; true when a request gave an adapter."""

    adapter: bool
    answers: tuple[str, ...]
    #: "drew a frame at 33 ms" or "drew no frame in 10000 ms"; None when the
    #: page had drawn already.
    frame: str | None = None
    #: Why not, in the app's words, when no request gave an adapter.
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.adapter

    def __str__(self) -> str:
        if self.answers:
            said = "the browser answered " + ", ".join(self.answers)
        else:
            said = self.reason or "the probe asked nothing"
        return f"the page {self.frame}; {said}" if self.frame else said


def wait_for_probe(page) -> None:
    """Wait until the page's bundle has defined the probe hook; fail when it never does."""
    try:
        # Polled on a timer: a page waiting for its GPU process draws no frames.
        page.wait_for_function(_HOOK_READY_JS, polling=100, timeout=_HOOK_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        pytest.fail(
            f"{page.url} has no window.__curio_probeWebGpu after {_HOOK_TIMEOUT_MS} ms: "
            "it is not running Curio's frontend bundle",
            pytrace=False,
        )


def webgpu_adapter(page) -> WebGpuAnswer:
    """Ask for a WebGPU adapter as the app does; the answer is true when one came.

    When it came after a null, a ``WebGpuAdapterRetried`` warning says so in
    the run's warnings summary.
    """
    wait_for_probe(page)
    found = page.evaluate(PROBE_JS)
    answer = WebGpuAnswer(
        bool(found["adapter"]), tuple(found["answers"]), found.get("frame"), found.get("reason"),
    )
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
