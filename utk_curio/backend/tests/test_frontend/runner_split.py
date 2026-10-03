"""Which e2e tests need the utk runner, and how the rest split across runners.

CI runs the e2e suite on two kinds of machine. A self-hosted GPU runner
(``arcade-gpu-01..06`` or ``utk-gpu``; the share keeps the name ``utk``) has an NVIDIA
GPU and is the only place hardware WebGPU exists; it is also one machine, so
everything on it runs in series. The CPU runners (GitHub-hosted
``ubuntu-latest`` or self-hosted ``[self-hosted, cpu]``) have no GPU but come
as many as a matrix asks for. So a test belongs on utk only when the browser
has to run WebGPU, and everything else is spread across a matrix of CPU jobs.

The line is drawn from the tests themselves, never from a list someone keeps:

* a ``test_workflows`` case needs WebGPU when its dataflow has an Autark node;
* a walkthrough scene does when its example dataflow does, or its script
  drives Autark or the browser's GPU;
* any other e2e module does when its source mentions Autark or WebGPU at all.

One more thing only utk has: the sibling backends of ``--parallel``. A test that
needs them says so with ``pytest.mark.needs_parallel`` and runs there too;
anywhere else it would skip, which is a test lost rather than a test passed.

It errs one way on purpose. A test that mentions Autark without needing a GPU
stays on utk, which costs a little time; a test that needs a GPU and landed on
a GPU-less runner would skip or fail. A new test is classified the same way,
with nothing to register.

Selected with two environment variables, both unset for an ordinary local run
(which keeps running everything):

* ``CURIO_E2E_RUNNER`` - ``utk`` keeps only the WebGPU tests, ``desktop``
  only the others;
* ``CURIO_E2E_PART`` - ``k/n`` keeps the k-th of n parts (1-based) of what
  is left, balanced by the recorded group durations in ``e2e_durations.json``
  (see ``tests/parts.py``).
"""

from __future__ import annotations

import functools
import inspect
import os
import re
from pathlib import Path

from utk_curio.backend.tests import parts

REPO_ROOT = Path(__file__).resolve().parents[4]
DURATIONS_FILE = Path(__file__).with_name("e2e_durations.json")

#: What marks a test, a scene or a dataflow as needing WebGPU in the browser.
WEBGPU_RE = re.compile(r"autk|autark|webgpu|navigator\.gpu", re.IGNORECASE)

RUNNERS = ("utk", "desktop")

#: Modules classified per test rather than per file.
WORKFLOW_MODULE = "test_workflows"
WALKTHROUGH_MODULE = "test_walkthrough_baselines"


@functools.lru_cache(maxsize=None)
def dataflow_needs_webgpu(path: str) -> bool:
    """Whether a dataflow file has an Autark node (its text names one)."""
    try:
        return bool(WEBGPU_RE.search(Path(path).read_text(encoding="utf-8")))
    except OSError:
        # A dataflow that cannot be read cannot be judged; keep it on utk.
        return True


def walk_needs_webgpu(walk) -> bool:
    """Whether a walkthrough scene needs WebGPU: its example, or its script."""
    example = getattr(walk, "example", None)
    if example and dataflow_needs_webgpu(str(REPO_ROOT / "docs" / "examples" / example)):
        return True
    try:
        source = inspect.getsource(walk.run)
    except (OSError, TypeError):
        return True
    return bool(WEBGPU_RE.search(source))


@functools.lru_cache(maxsize=None)
def module_needs_webgpu(path: str) -> bool:
    """Whether an e2e module's source mentions Autark or WebGPU anywhere."""
    try:
        return bool(WEBGPU_RE.search(Path(path).read_text(encoding="utf-8")))
    except OSError:
        return True


def item_needs_webgpu(item) -> bool:
    """Whether the item belongs on utk: WebGPU, or the parallel stack."""
    if item.get_closest_marker("needs_parallel") is not None:
        return True
    module = getattr(item, "module", None)
    name = module.__name__.rsplit(".", 1)[-1] if module is not None else ""
    params = getattr(getattr(item, "callspec", None), "params", {}) or {}
    if name == WORKFLOW_MODULE and "loaded_workflow" in params:
        return dataflow_needs_webgpu(str(params["loaded_workflow"]))
    if name == WALKTHROUGH_MODULE and "walk" in params:
        return walk_needs_webgpu(params["walk"])
    path = getattr(module, "__file__", None)
    return module_needs_webgpu(path) if path else True


def group_of(item) -> str:
    """The item's xdist group: what must stay together on one worker."""
    marker = item.get_closest_marker("xdist_group")
    if marker is not None:
        return str(marker.kwargs.get("name") or (marker.args[0] if marker.args else ""))
    module = getattr(item, "module", None)
    return module.__name__.rsplit(".", 1)[-1] if module is not None else item.nodeid


def parse_shard(value: str) -> tuple[int, int]:
    """``"k/n"`` -> (k-1, n), 1-based on the outside, 0-based inside."""
    return parts.parse_part(value, "CURIO_E2E_PART")


def select(items, runner: str | None, shard: str | None, durations: dict | None = None):
    """Split ``items`` into (kept, deselected) for this runner and shard."""
    if runner and runner not in RUNNERS:
        raise ValueError(f"CURIO_E2E_RUNNER must be one of {RUNNERS}, got {runner!r}")
    kept, dropped = [], []
    for item in items:
        webgpu = item_needs_webgpu(item)
        if runner is None or (runner == "utk") == webgpu:
            kept.append(item)
        else:
            dropped.append(item)
    if shard:
        kept, rest = parts.keep_part(
            kept, shard, group_of,
            parts.load_durations(DURATIONS_FILE) if durations is None else durations,
            "CURIO_E2E_PART")
        dropped += rest
    return kept, dropped


def from_environment(environ=os.environ) -> tuple[str | None, str | None]:
    runner = (environ.get("CURIO_E2E_RUNNER") or "").strip() or None
    # Not CURIO_E2E_SHARD: tests/shards.py already means the in-container
    # xdist shard index by that.
    shard = (environ.get("CURIO_E2E_PART") or "").strip() or None
    return runner, shard
