"""A node's code leaves the sandbox's process as it found it.

Without isolation (a local install, and CI's shared sandbox) a node's Python
runs in the sandbox's own process (``worker.execute_code``), which every later
node of every dataflow shares. So what its code sets for the process would
stay for them all:

- the environment, which the worker puts back after each run, whether the
  code returns or raises: each variable the code added, changed or removed,
  and no other, so a thread count's variable is as it was, never a count
  Curio picks;
- a library's settings, which only the code that changed them can put back:
  examples 27 to 30 make torch give the same numbers on every run (cuBLAS's
  workspace, a seed, deterministic kernels only, full float32 precision and
  no cuDNN benchmark), and each node reads every setting first and puts it
  back when it ends.

Under isolation each node runs in a child of its own, which ends with it.

Run:  python -m pytest utk_curio/sandbox/tests/test_node_code_process_state.py -v
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import textwrap
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "docs" / "examples"


# ---------------------------------------------------------------------------
# The environment, put back by the worker
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def worker():
    """The worker, its globals loaded and its store open, as the sandbox starts it."""
    from utk_curio.sandbox.app import worker as module
    from utk_curio.sandbox.util.db import init_db

    module._worker_init()
    init_db()
    return module


def _run(worker, code: str, session_id: str) -> dict:
    """*code* run as a node's, in this process, indented as the canvas sends it."""
    body = "".join("    " + line + "\n" for line in textwrap.dedent(code).strip("\n").split("\n"))
    return worker.execute_code(
        body, "", "curio.builtin/python-computation", "", session_id=session_id, save_dataset=False,
    )


@pytest.fixture
def variables(monkeypatch):
    """The variables a node changes here: one of this test's own that the
    process does not hold, two it holds, and the thread count's, each as it
    was again once the test ends, whatever a node left."""
    tag = uuid.uuid4().hex[:8].upper()
    names = {
        "added": f"CURIO_TEST_ADDED_{tag}",
        "changed": f"CURIO_TEST_CHANGED_{tag}",
        "removed": f"CURIO_TEST_REMOVED_{tag}",
        "threads": "OMP_NUM_THREADS",
    }
    threads = os.environ.get("OMP_NUM_THREADS")
    monkeypatch.setenv(names["changed"], "as it was")
    monkeypatch.setenv(names["removed"], "as it was")
    yield names
    os.environ.pop(names["added"], None)
    if threads is None:
        os.environ.pop("OMP_NUM_THREADS", None)
    else:
        os.environ["OMP_NUM_THREADS"] = threads


def _changing(names: dict, ending: str) -> str:
    """A node's code that adds a variable, changes one, removes one and sets
    the thread count's, prints what it set, then returns or raises."""
    last = ("return 1" if ending == "returns"
            else "raise RuntimeError('the node failed after it changed the environment')")
    return "\n".join([
        "import os",
        f"os.environ[{names['added']!r}] = 'added by a node'",
        f"os.environ[{names['changed']!r}] = 'changed by a node'",
        f"del os.environ[{names['removed']!r}]",
        "os.environ['OMP_NUM_THREADS'] = '1'",
        f"print(os.environ[{names['added']!r}])",
        last,
    ])


def _reading(names: dict) -> str:
    """A node's code that prints what it reads of the variables *names*, None
    for one the process does not hold."""
    return "\n".join([
        "import json",
        "import os",
        f"print(json.dumps({{name: os.environ.get(name) for name in {sorted(names.values())!r}}}))",
        "return 1",
    ])


@pytest.mark.parametrize("ending", ["returns", "raises"])
def test_the_environment_a_nodes_code_changed_is_as_it_was_for_the_next_node(worker, variables, ending):
    """A node adds a variable, changes one, removes one and sets the thread
    count's, then returns or raises. Its code sees its own changes while it
    runs. The next node, of its dataflow or of another, reads each variable as
    it was before the first node ran, and so does the sandbox itself."""
    names = sorted(variables.values())
    before = {name: os.environ.get(name) for name in names}

    first = _run(worker, _changing(variables, ending), "flow-a")
    if ending == "raises":
        assert "the node failed after it changed the environment" in first["stderr"], first["stderr"]
    else:
        assert not first["stderr"], first["stderr"]
    assert first["stdout"] == ["added by a node"], first["stdout"]

    for session in ("flow-a", "flow-b"):
        read = _run(worker, _reading(variables), session)
        assert not read["stderr"], read["stderr"]
        seen = json.loads(read["stdout"][-1])
        left = {name: (before[name], seen.get(name)) for name in names if seen.get(name) != before[name]}
        assert not left, (
            f"after a node that {ending}, a node of {session} read the environment as that node left it, "
            f"not as it was (each as it was, then as read): {left}")
    still = {name: (before[name], os.environ.get(name)) for name in names if os.environ.get(name) != before[name]}
    assert not still, f"the sandbox's own environment is as the node left it (as it was, then now): {still}"


# ---------------------------------------------------------------------------
# torch's settings, put back by examples 27 to 30
# ---------------------------------------------------------------------------

#: The node of each of examples 27 to 30 whose code runs torch.
TORCH_NODES = {
    "27-pytorch-shape-classifier": "shape-classifier",
    "28-pytorch-training-on-the-gpu": "training-run",
    "29-pytorch-street-photos": "photo-measures",
    "30-pytorch-sidewalk-clusters": "label-clusters",
}

#: What each of those nodes sets while its work runs, so that a rerun gives
#: the same numbers.
WHILE_IT_RUNS = {
    "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
    "deterministic algorithms": True,
    "deterministic algorithms only warn": False,
    "float32 precision": "ieee",
    "cuDNN benchmark": False,
}

#: torch's float32 precision for each backend and kind of op, besides the
#: generic one the examples set: each inherits the generic one unless set.
BACKEND_PRECISIONS = (
    "cuda.matmul", "cudnn", "cudnn.conv", "cudnn.rnn", "mkldnn", "mkldnn.matmul", "mkldnn.conv", "mkldnn.rnn",
)

#: What the process holds before the node runs: as torch starts, or as a node
#: of a person's own may leave it (:func:`_as_another_node_left_it`).
BEFORE = ("as-torch-starts", "as-another-node-left-it")


def _node_code(example: str, node_id: str) -> str:
    nodes = json.loads((EXAMPLES / f"{example}.json").read_text(encoding="utf-8"))["dataflow"]["nodes"]
    return next(node["content"] for node in nodes if node["id"] == node_id)


def _call(example: str, node_id: str, value=None, slots=None, namespace=None):
    """The code of the example's node *node_id*, run in this process as the
    sandbox runs it (``input_names.call_as_node``), on *value* split over the
    circles *slots*."""
    from utk_curio.sandbox.util.input_names import call_as_node

    body = "\n".join("    " + line for line in _node_code(example, node_id).splitlines())
    return call_as_node(body, dict(namespace or {}), value, slots)


def _backend_precision(path: str) -> str:
    import torch

    value = torch.backends
    try:
        for part in path.split("."):
            value = getattr(value, part)
        return value.fp32_precision
    except Exception as error:  # a backend or a kind of op this build of torch does not have
        return f"not read: {type(error).__name__}"


def _settings() -> dict:
    """What examples 27 to 30 change of this process, as it is now: the
    variable cuBLAS reads, torch's deterministic mode and whether it only
    warns, its float32 precision, generic and for each backend, cuDNN's
    benchmark and deterministic flags, and the state of torch's random
    numbers on the CPU."""
    import torch

    settings = {
        "CUBLAS_WORKSPACE_CONFIG": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
        "deterministic algorithms": torch.are_deterministic_algorithms_enabled(),
        "deterministic algorithms only warn": torch.is_deterministic_algorithms_warn_only_enabled(),
        "float32 precision": torch.backends.fp32_precision,
        "cuDNN benchmark": torch.backends.cudnn.benchmark,
        "cuDNN deterministic": torch.backends.cudnn.deterministic,
        "random numbers": hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest()[:16],
    }
    settings.update({f"float32 precision of {path}": _backend_precision(path) for path in BACKEND_PRECISIONS})
    return settings


def _changed(before: dict, after: dict) -> dict:
    """Each setting *after* holds otherwise than *before*: as it was, then as it is."""
    return {key: (before[key], after.get(key)) for key in before if after.get(key) != before[key]}


@pytest.fixture
def torch_as_found():
    """torch's settings and the variable cuBLAS reads, as this test found
    them again once it ends, whatever a node left; and a few CPU threads
    meanwhile: an arcade runner shows 192 CPUs, and torch would take half."""
    import torch

    cublas = os.environ.get("CUBLAS_WORKSPACE_CONFIG")
    found = (
        torch.are_deterministic_algorithms_enabled(), torch.is_deterministic_algorithms_warn_only_enabled(),
        torch.backends.fp32_precision, torch.backends.cudnn.benchmark, torch.get_rng_state(), torch.get_num_threads(),
    )
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    yield
    deterministic, warn_only, precision, benchmark, random_state, threads = found
    torch.use_deterministic_algorithms(deterministic, warn_only=warn_only)
    torch.backends.fp32_precision = precision
    torch.backends.cudnn.benchmark = benchmark
    torch.set_rng_state(random_state)
    torch.set_num_threads(threads)
    if cublas is None:
        os.environ.pop("CUBLAS_WORKSPACE_CONFIG", None)
    else:
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = cublas


def _as_another_node_left_it():
    """The process as a node of a person's own may leave it: cuBLAS's other
    deterministic workspace, deterministic mode that only warns, TF32, cuDNN's
    benchmark on, and random numbers seeded and drawn from."""
    import torch

    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":16:8"
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.backends.fp32_precision = "tf32"
    torch.backends.cudnn.benchmark = True
    torch.manual_seed(5)
    torch.rand(3)


def _leave_the_process(before: str) -> dict:
    """The process as *before* says, and what it then holds (:func:`_settings`)."""
    if before == "as-another-node-left-it":
        _as_another_node_left_it()
    else:
        os.environ.pop("CUBLAS_WORKSPACE_CONFIG", None)
    return _settings()


@pytest.fixture(scope="module")
def upstream():
    """The outputs of the example nodes before the torch nodes that need no
    data of the catalog, each made once by its own code: example 27's
    pictures and weights and example 28's pictures. A relative path in a
    node's code is the shipped file's, as from the folder Curio starts in."""
    with contextlib.chdir(REPO):
        return {
            "shape-pictures": _call("27-pytorch-shape-classifier", "shape-pictures"),
            "shape-weights": _call("27-pytorch-shape-classifier", "shape-weights"),
            "training-pictures": _call("28-pytorch-training-on-the-gpu", "training-pictures"),
        }


def _photos(folder: Path):
    """Two small photos, as Data Loading hands on the Data Catalog's Mapillary
    sample: each partly green, the rest light gray."""
    import numpy as np
    import pandas as pd
    from PIL import Image

    rows = []
    for index in range(2):
        picture = np.full((24, 32, 3), 200, dtype=np.uint8)
        picture[:, : 8 * (index + 1)] = (40, 160, 50)
        path = folder / f"photo-{index}.png"
        Image.fromarray(picture).save(path)
        rows.append({
            "image_id": f"photo-{index}", "creator": "a photographer", "dataset_id": "data.test.photos",
            "file_id": path.name, "path": str(path), "thumbnail": f"/media/{path.name}?variant=thumb",
        })
    return pd.DataFrame(rows)


def _derived_file(folder: Path):
    """``curio_derived_file`` as a run gets it: where a file made from a
    collection's file is kept, and its link."""
    def curio_derived_file(dataset_id, file_id, start_ms, ext, kind=None, tag=None):
        path = folder / f"{file_id}@{start_ms}-{tag}.{ext}"
        return {"path": str(path), "image_url": f"/media/{path.name}"}

    return curio_derived_file


def _labels():
    """Forty of Project Sidewalk's labels around the Loop, as Data Loading
    hands them on."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    places = np.random.default_rng(30).uniform(-0.05, 0.05, size=(40, 2))
    return gpd.GeoDataFrame(
        {"label_type": ["CurbRamp", "Obstacle"] * 20, "severity": [1, 3] * 20, "neighborhood": ["Loop"] * 40},
        geometry=[Point(-87.63 + dx, 41.88 + dy) for dx, dy in places], crs=4326,
    )


def _handed(example: str, upstream: dict, folder: Path):
    """``(value, slots, namespace)``: what the example's torch node is handed
    on its circles, kept small, and the functions its code calls besides."""
    if example == "27-pytorch-shape-classifier":
        return [upstream["shape-pictures"], upstream["shape-weights"]], [0, 1], {}
    if example == "28-pytorch-training-on-the-gpu":
        # Thirty pictures of each set, so its twenty epochs take a second.
        return upstream["training-pictures"].groupby("split", sort=False).head(30), [0], {}
    if example == "29-pytorch-street-photos":
        return _photos(folder), [0], {"curio_derived_file": _derived_file(folder)}
    return _labels(), [0], {}


@pytest.mark.parametrize("before", BEFORE)
@pytest.mark.parametrize("example", sorted(TORCH_NODES))
def test_a_pytorch_examples_node_leaves_torch_as_it_found_it(example, before, upstream, torch_as_found, tmp_path):
    """The example's torch node, run in this process on a few rows, returns
    its rows; then the variable cuBLAS reads, torch's deterministic mode, its
    float32 precision, cuDNN's flags and torch's random numbers are as they
    were before it ran, whether the process held torch's own settings or
    those another node left."""
    held = _leave_the_process(before)
    value, slots, namespace = _handed(example, upstream, tmp_path)

    out = _call(example, TORCH_NODES[example], value, slots, namespace)

    assert len(out) > 0 and "device" in out.columns, out
    left = _changed(held, _settings())
    assert not left, (
        f"example {example}'s node {TORCH_NODES[example]} returned and left torch changed for every later node "
        f"of this process (as it was, then as left): {left}")


class _UnreadAttribute(AttributeError):
    """What reading an attribute of an :class:`_Unreadable` input raises."""


class _UnreadItem(LookupError):
    """What reading an item of an :class:`_Unreadable` input raises."""


class _Unreadable:
    """An input whose every read raises, noting first, in *seen*, the
    process's settings as the node's work sees them at its first read."""

    def __init__(self, seen: list):
        self._seen = seen

    def _note(self):
        if not self._seen:
            self._seen.append(_settings())

    def __getattr__(self, name):
        self._note()
        raise _UnreadAttribute(f"the node read {name!r} of an input it cannot read")

    def __getitem__(self, key):
        self._note()
        raise _UnreadItem(f"the node read {key!r} of an input it cannot read")


@pytest.mark.parametrize("before", BEFORE)
@pytest.mark.parametrize("example", sorted(TORCH_NODES))
def test_a_pytorch_examples_node_that_raises_leaves_torch_as_it_found_it(example, before, torch_as_found, tmp_path):
    """The example's torch node is handed an input it cannot read, so its
    work raises at its first read of it. While its work ran, its settings
    were the ones that give the same numbers on every run; once it raised,
    they are as they were before it ran."""
    held = _leave_the_process(before)
    seen = []
    slots = [0, 1] if example == "27-pytorch-shape-classifier" else [0]
    value = [_Unreadable(seen), _Unreadable(seen)] if len(slots) == 2 else _Unreadable(seen)

    with pytest.raises((_UnreadAttribute, _UnreadItem)):
        _call(example, TORCH_NODES[example], value, slots, {"curio_derived_file": _derived_file(tmp_path)})

    assert seen, f"example {example}'s node raised before its work read its input"
    while_it_ran = {key: seen[0][key] for key in WHILE_IT_RUNS}
    assert while_it_ran == WHILE_IT_RUNS, (
        f"while example {example}'s work ran, torch's settings were {while_it_ran}, not the ones that give "
        f"the same numbers on every run, {WHILE_IT_RUNS}")
    left = _changed(held, _settings())
    assert not left, (
        f"example {example}'s node {TORCH_NODES[example]} raised and left torch changed for every later node "
        f"of this process (as it was, then as left): {left}")
