"""``scripts/ci_isolated_threads.py``: test-isolated's stack runs node code on the job's thread count.

The check runs a node in an isolated child of the stack and reads what torch
uses there. Torch's x86 build sizes its pool through MKL, which counts physical
cores, so on a 4-CPU hosted runner (2 cores) it takes 2 threads under
``OMP_NUM_THREADS=4``: fewer than the job's count, which costs nothing, and main's
run 42323207500 failed the check for it. What the check is for is more: torch
spread over 96 threads in a child on an arcade runner (run 42230248452). These
hand the check what a child reported.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load():
    path = REPO_ROOT / "scripts" / "ci_isolated_threads.py"
    spec = importlib.util.spec_from_file_location("_scripts_ci_isolated_threads", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


threads = _load()


@pytest.mark.parametrize("seen, wanted, passes", [
    # A hosted runner: 4 CPUs, 2 cores, and MKL counts the cores.
    ({"torch": 2, "omp": "4", "cpus": 4}, "4", True),
    # An arcade runner once test-isolated has sized its stack.
    ({"torch": 8, "omp": "8", "cpus": 192}, "8", True),
    # An arcade runner before it: torch on every core it sees.
    ({"torch": 96, "omp": None, "cpus": 192}, "8", False),
    # More threads than the job's count, or a stack that never got the count.
    ({"torch": 9, "omp": "8", "cpus": 192}, "8", False),
    ({"torch": 8, "omp": None, "cpus": 192}, "8", False),
], ids=["hosted-cores", "arcade-sized", "arcade-unsized", "over-the-count", "count-not-passed"])
def test_a_child_passes_with_the_jobs_count_or_fewer(monkeypatch, capsys, seen, wanted, passes):
    monkeypatch.setattr(threads, "child_threads", lambda: seen)
    monkeypatch.setenv("CURIO_CI_LIBRARY_THREADS", wanted)
    assert (threads.main() == 0) is passes, capsys.readouterr().out


def test_a_job_that_handed_its_stack_no_count_fails(monkeypatch):
    monkeypatch.setattr(threads, "child_threads", lambda: {"torch": 96, "omp": None, "cpus": 192})
    monkeypatch.delenv("CURIO_CI_LIBRARY_THREADS", raising=False)
    assert threads.main() == 1
