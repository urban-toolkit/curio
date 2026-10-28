"""Which e2e tests need the utk runner, and how the rest split across runners.

CI runs the e2e suite on two kinds of machine. A self-hosted GPU runner
(``arcade-gpu-01..04``, ``utk-gpu`` or ``utk-desktop-01``; the share keeps the name
``utk``) has an NVIDIA GPU and is the only place hardware WebGPU exists; it is also
one machine, so everything on it runs in series. The CPU runners (GitHub-hosted
``ubuntu-latest``, self-hosted ``[self-hosted, cpu]`` or the utk-desktop runners'
``[self-hosted, desktop]``) have no GPU in use but come
as many as a matrix asks for. So a test belongs on utk only when the browser
has to run WebGPU, and everything else is spread across a matrix of CPU jobs.

The line is drawn from the tests themselves, never from a list someone keeps:

* a ``test_workflows`` case needs WebGPU when its dataflow has an Autark node;
* so does a ``test_shipped_scenario_drops_e2e`` case, by the dataflow it drops
  a scenario from;
* a walkthrough scene does when its example dataflow does, or its script
  drives Autark or the browser's GPU;
* any other e2e module does when its source mentions Autark or WebGPU at all.

One more thing only utk has: the sibling backends of ``--parallel``. A test that
needs them says so with ``pytest.mark.needs_parallel`` and runs there too;
anywhere else it would skip, which is a test lost rather than a test passed.

A third runner, ``collab``, is the one stack started with ``--collab`` (CI's
e2e-collab job). A test that needs real-time collaboration says so with
``pytest.mark.needs_collab``, runs there alone, and is left out of the other two.

It errs one way on purpose. A test that mentions Autark without needing a GPU
stays on utk, which costs a little time; a test that needs a GPU and landed on
a GPU-less runner would skip or fail. A new test is classified the same way,
with nothing to register.

Selected with two environment variables, both unset for an ordinary local run
(which keeps running everything):

* ``CURIO_E2E_RUNNER`` - ``utk`` keeps only the WebGPU tests, ``desktop``
  only the others, and ``collab`` only the ``needs_collab`` ones, which the
  other two leave out;
* ``CURIO_E2E_PART`` - ``k/n`` keeps the k-th of n parts (1-based) of what
  is left, balanced by the recorded seconds of each test in
  ``e2e_durations.json`` (see ``tests/parts.py``).

A part holds whole groups (``part_key``). Most groups are one test, since a
test that gets the per-test database reset shares nothing with the tests
around it. A class that shares a session keeps its xdist group (``group_of``),
and a module that defines a fixture outliving one test stays whole. The xdist
groups themselves are what the GPU runner's workers schedule by; the parts do
not change them.
"""

from __future__ import annotations

import ast
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

RUNNERS = ("utk", "desktop", "collab")

#: Modules classified per test rather than per file.
WORKFLOW_MODULE = "test_workflows"
WALKTHROUGH_MODULE = "test_walkthrough_baselines"
SHIPPED_DROPS_MODULE = "test_shipped_scenario_drops_e2e"


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


def item_needs_collab(item) -> bool:
    """Whether the item needs the stack started with ``--collab``."""
    closest = getattr(item, "get_closest_marker", None)
    return bool(closest and closest("needs_collab") is not None)


def item_needs_webgpu(item) -> bool:
    """Whether the item belongs on utk: WebGPU, or the parallel stack."""
    if item.get_closest_marker("needs_parallel") is not None:
        return True
    module = getattr(item, "module", None)
    name = module.__name__.rsplit(".", 1)[-1] if module is not None else ""
    params = getattr(getattr(item, "callspec", None), "params", {}) or {}
    if name == WORKFLOW_MODULE and "loaded_workflow" in params:
        return dataflow_needs_webgpu(str(params["loaded_workflow"]))
    if name == SHIPPED_DROPS_MODULE and "dataflow" in params:
        return dataflow_needs_webgpu(str(REPO_ROOT / params["dataflow"]))
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


@functools.lru_cache(maxsize=None)
def module_keeps_a_fixture(path: str) -> bool:
    """Whether an e2e module defines a fixture that outlives one test.

    A module-, class-, package- or session-scoped ``@pytest.fixture`` in the
    module's own code (at its top or in a class): a server, a session or a
    page its tests share. Read from the source, since every test also uses
    conftest's class-scoped ``browser``, which a part restarts at no risk.
    """
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return True  # cannot tell: keep it whole
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "fixture":
                continue
            for keyword in decorator.keywords:
                scope = keyword.value
                if keyword.arg == "scope" and not (
                        isinstance(scope, ast.Constant) and scope.value == "function"):
                    return True
    return False


def part_key(item) -> str:
    """What one CPU part runs whole with the item: one test, or a group of them.

    * A module that defines a fixture outliving one test stays whole, so its
      server or session starts once (``module_keeps_a_fixture``).
    * A test that skips the per-test database reset (``fixtures.skips_the_reset``:
      a class sharing one session, a ``wf-*`` workflow class whose methods run
      in order) keeps its xdist group.
    * Any other test is a group of its own: it gets the reset, so it shares
      nothing with the tests around it.
    """
    module = getattr(item, "module", None)
    path = getattr(module, "__file__", None)
    if module is not None and (not path or module_keeps_a_fixture(path)):
        return module.__name__.rsplit(".", 1)[-1]
    from .fixtures import skips_the_reset

    if skips_the_reset(getattr(item, "cls", None), getattr(item, "fixturenames", ())):
        return group_of(item)
    return item_key(item)


def item_key(item) -> str:
    """The item's key in ``e2e_durations.json`` (``parts.item_key``)."""
    return parts.item_key(item)


def parse_shard(value: str) -> tuple[int, int]:
    """``"k/n"`` -> (k-1, n), 1-based on the outside, 0-based inside."""
    return parts.parse_part(value, "CURIO_E2E_PART")


def select(items, runner: str | None, shard: str | None, durations: dict | None = None):
    """Split ``items`` into (kept, deselected) for this runner and shard."""
    if runner and runner not in RUNNERS:
        raise ValueError(f"CURIO_E2E_RUNNER must be one of {RUNNERS}, got {runner!r}")
    kept, dropped = [], []
    for item in items:
        if runner is None:
            keep = True
        elif item_needs_collab(item) or runner == "collab":
            keep = runner == "collab" and item_needs_collab(item)
        else:
            keep = (runner == "utk") == item_needs_webgpu(item)
        (kept if keep else dropped).append(item)
    if shard:
        kept, rest = parts.keep_part(
            kept, shard, part_key, item_key,
            parts.load_durations(DURATIONS_FILE) if durations is None else durations,
            "CURIO_E2E_PART")
        dropped += rest
    return kept, dropped


def environment_part(items):
    """(kept, deselected) for the runner and part the environment names."""
    runner, shard = from_environment()
    if not runner and not shard:
        return items, []
    return select(items, runner, shard)


def from_environment(environ=os.environ) -> tuple[str | None, str | None]:
    runner = (environ.get("CURIO_E2E_RUNNER") or "").strip() or None
    # Not CURIO_E2E_SHARD: tests/shards.py already means the in-container
    # xdist shard index by that.
    shard = (environ.get("CURIO_E2E_PART") or "").strip() or None
    return runner, shard
