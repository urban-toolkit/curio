"""What the backend processes of a start share is divided among them
(``common/backend_processes.share``).

A budget over something the processes share, the sandbox's isolated slots or
a rate a minute, is held in each process's memory. So each of N processes
holds its share of it: the budget divided by N, at least 1. With one process,
every install's default, each budget stays whole:

* a dashboard viewer's runs (``runs/viewer.py``): the nodes they run at once,
  half the sandbox's isolated pool, and the runs a minute per visitor address
  and overall;
* the package backend handlers that run at once
  (``packages/infrastructure/backend_runtime.py``, ``--package-workers``).

Each count is read in an interpreter of its own, started as the launcher
starts a backend, so the numbers are the ones the modules hold at import.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]

_READ = """
import json
from utk_curio.backend.app.runs import viewer
from utk_curio.backend.app.packages.infrastructure import backend_runtime
print("BUDGETS " + json.dumps({
    "viewer steps at once": viewer.STEP_SLOTS,
    "viewer runs a minute per address": viewer._LIMITER.per_address_per_minute,
    "viewer runs a minute overall": viewer._LIMITER.overall_per_minute,
    "package handlers at once": backend_runtime.MAX_CONCURRENT_WORKERS,
}))
"""


def _budgets(**given: str) -> dict:
    """The budgets a backend holds, started with the sandbox's isolated pool
    and the package handlers at 8, and *given*."""
    env = {name: value for name, value in os.environ.items()
           if name not in ("CURIO_BACKEND_PROCESS", "CURIO_BACKEND_PROCESSES")}
    env.update(PYTHONPATH=str(REPO_ROOT), CURIO_EXEC_PARALLELISM="8", CURIO_PACKAGE_WORKERS="8", **given)
    done = subprocess.run([sys.executable, "-c", _READ], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=300)
    lines = [line for line in done.stdout.splitlines() if line.startswith("BUDGETS ")]
    assert done.returncode == 0 and lines, f"exit {done.returncode}\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}"
    return json.loads(lines[-1][len("BUDGETS "):])


WHOLE = {
    "viewer steps at once": 4,
    "viewer runs a minute per address": 10,
    "viewer runs a minute overall": 120,
    "package handlers at once": 8,
}


#: Each process's share, by how many processes the start runs.
SHARES = {
    2: {"viewer steps at once": 2, "viewer runs a minute per address": 5,
        "viewer runs a minute overall": 60, "package handlers at once": 4},
    4: {"viewer steps at once": 1, "viewer runs a minute per address": 2,
        "viewer runs a minute overall": 30, "package handlers at once": 2},
    # Never below one: a process with no slot could never run a viewer's node.
    8: {"viewer steps at once": 1, "viewer runs a minute per address": 1,
        "viewer runs a minute overall": 15, "package handlers at once": 1},
}


def test_one_process_holds_every_budget_whole_and_each_of_several_its_share():
    assert _budgets() == WHOLE, "a start of one process must keep today's budgets"
    for processes, number in ((2, 1), (4, 3), (8, 0), (8, 7)):
        held = _budgets(CURIO_BACKEND_PROCESS=str(number), CURIO_BACKEND_PROCESSES=str(processes))
        assert held == SHARES[processes], (
            f"process {number} of {processes} holds {held}, not its share of what the processes share"
        )


def test_a_share_is_the_budget_divided_by_the_processes_and_at_least_one():
    from utk_curio.common.backend_processes import share

    assert share(120, {}) == 120
    assert share(120, {"CURIO_BACKEND_PROCESS": "3", "CURIO_BACKEND_PROCESSES": "8"}) == 15
    assert share(10, {"CURIO_BACKEND_PROCESS": "0", "CURIO_BACKEND_PROCESSES": "4"}) == 2
    assert share(3, {"CURIO_BACKEND_PROCESS": "1", "CURIO_BACKEND_PROCESSES": "8"}) == 1
