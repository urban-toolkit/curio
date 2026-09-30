"""Which e2e tests need the utk runner, and how the rest split across runners.

CI runs the e2e suite on two kinds of machine. The self-hosted ``utk`` runner
has an NVIDIA GPU and is the only place hardware WebGPU exists; it is also one
machine, so everything on it runs in series. ``ubuntu-latest`` runners have no
GPU but come as many as a matrix asks for. So a test belongs on utk only when
the browser has to run WebGPU, and everything else is spread across a matrix of
ubuntu-latest jobs.

The line is drawn from the tests themselves, never from a list someone keeps:

* a ``test_workflows`` case needs WebGPU when its dataflow has an Autark node;
* a walkthrough scene does when its example dataflow does, or its script
  drives Autark or the browser's GPU;
* any other e2e module does when its source mentions Autark or WebGPU at all.

It errs one way on purpose. A test that mentions Autark without needing a GPU
stays on utk, which costs a little time; a test that needs a GPU and landed on
a GPU-less runner would skip or fail. A new test is classified the same way,
with nothing to register.

Selected with two environment variables, both unset for an ordinary local run
(which keeps running everything):

* ``CURIO_E2E_RUNNER`` - ``utk`` keeps only the WebGPU tests, ``desktop``
  only the others;
* ``CURIO_E2E_SHARD`` - ``k/n`` keeps the k-th of n shards (1-based) of what
  is left, balanced by the recorded group durations in ``e2e_durations.json``.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DURATIONS_FILE = Path(__file__).with_name("e2e_durations.json")

#: What marks a test, a scene or a dataflow as needing WebGPU in the browser.
WEBGPU_RE = re.compile(r"autk|autark|webgpu|navigator\.gpu", re.IGNORECASE)

#: A group whose duration is unknown (new since the file was recorded).
DEFAULT_GROUP_SECONDS = 30.0

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
    """The classification above, for one collected pytest item."""
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


def load_durations(path: Path = DURATIONS_FILE) -> dict:
    try:
        return {str(k): float(v) for k, v in json.loads(path.read_text()).items()}
    except (OSError, ValueError):
        return {}


def assign_shards(groups, shards: int, durations: dict) -> dict:
    """Longest-first onto the least-loaded shard. Deterministic for a given input."""
    load = [0.0] * shards
    placed = {}
    ordered = sorted(set(groups), key=lambda g: (-durations.get(g, DEFAULT_GROUP_SECONDS), g))
    for group in ordered:
        target = min(range(shards), key=lambda i: (load[i], i))
        placed[group] = target
        load[target] += durations.get(group, DEFAULT_GROUP_SECONDS)
    return placed


def parse_shard(value: str) -> tuple[int, int]:
    """``"k/n"`` -> (k-1, n), 1-based on the outside, 0-based inside."""
    try:
        k, n = (int(part) for part in value.split("/", 1))
    except ValueError:
        raise ValueError(f"CURIO_E2E_SHARD must be k/n, got {value!r}") from None
    if not 1 <= k <= n:
        raise ValueError(f"CURIO_E2E_SHARD {value!r}: k must be between 1 and n")
    return k - 1, n


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
        index, count = parse_shard(shard)
        placed = assign_shards([group_of(i) for i in kept], count,
                               load_durations() if durations is None else durations)
        mine = [i for i in kept if placed[group_of(i)] == index]
        dropped += [i for i in kept if placed[group_of(i)] != index]
        kept = mine
    return kept, dropped


def from_environment(environ=os.environ) -> tuple[str | None, str | None]:
    runner = (environ.get("CURIO_E2E_RUNNER") or "").strip() or None
    shard = (environ.get("CURIO_E2E_SHARD") or "").strip() or None
    return runner, shard
