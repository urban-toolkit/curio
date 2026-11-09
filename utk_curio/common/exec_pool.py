"""How many node runs the sandbox runs at once: isolated children, and
JavaScript nodes' Node processes.

The sandbox sizes its pool of isolated children with this
(``sandbox/isolation/runner.py``), and the backend reads the same number to
keep a dashboard viewer's runs to part of that pool (``runs/viewer.py``). The
sandbox's Node slots are :func:`js_parallelism` (``app/worker.py``), and the
thread budget the execution account's processes share counts both pools
(``runner.IsolationConfig.from_environment``).
"""

from __future__ import annotations

import os


def default_exec_parallelism() -> int:
    """How many isolated nodes may run at once when nobody says otherwise.

    Two was a single-user default and it is what a multi-user instance queues
    behind: at fifty simultaneous users the stress tiers measured a p95 of
    161s for a node that takes under a second on an idle stack, almost all of
    it spent waiting for a slot. Sizing to the host instead means a machine
    with cores to spare uses them.

    Capped at 8 because the real ceiling is memory, not CPU: peak usage is
    roughly this times ``CURIO_EXEC_MEMORY_MB`` (4096 by default), so an
    uncapped count on a 64-core box would promise far more memory than it has.
    An operator who knows their workload raises it with --exec-parallelism.
    """
    cores = os.cpu_count() or 2
    return max(2, min(cores // 2, 8))


def exec_parallelism(env=None) -> int:
    """The pool's size: ``CURIO_EXEC_PARALLELISM`` (``--exec-parallelism``),
    else :func:`default_exec_parallelism`."""
    env = os.environ if env is None else env
    try:
        return max(1, int(env.get("CURIO_EXEC_PARALLELISM", default_exec_parallelism())))
    except (TypeError, ValueError):
        return default_exec_parallelism()


def default_js_parallelism() -> int:
    """How many Node subprocesses may run at once when nobody says otherwise.

    Not a lock: JS nodes are meant to run in parallel, and this leaves them
    doing so. It is a ceiling on how many at once, which the route had none of
    -- one Node process per request, each loading autk-db and its own DuckDB.
    A hundred simultaneous Autark loads peaked the CI container at 51 GB and
    1313 processes, which is how a machine dies rather than queues.

    Half the cores, floor 2, cap 16: an Autark PBF load is CPU- and
    memory-heavy, and the work the child does is what costs, not the pipe.
    """
    cores = os.cpu_count() or 2
    return max(2, min(cores // 2, 16))


def js_parallelism(env=None) -> int:
    """The Node slots: ``CURIO_JS_PARALLELISM`` (``--js-parallelism``) when it
    is a positive number, else :func:`default_js_parallelism`."""
    env = os.environ if env is None else env
    try:
        configured = int(env.get("CURIO_JS_PARALLELISM", ""))
    except (TypeError, ValueError):
        configured = 0
    return configured if configured > 0 else default_js_parallelism()
