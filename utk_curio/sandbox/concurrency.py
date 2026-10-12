"""How many runs the sandbox takes at once.

The sandbox sizes its queues from these, and the backend waits for a turn of
the same size before it sends a run (``execution/sandbox_client.exec_turn``),
so a request's timeout counts the node's run and not its wait for a place
(#863, #889). Both servers read them from the environment ``curio.py`` starts
them with, so they agree. Nothing here imports more than ``os``: the backend
reads these without loading the sandbox.
"""

import os


def exec_parallelism(env=None) -> int:
    """How many isolated nodes may run at once (``CURIO_EXEC_PARALLELISM``).

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
    env = env if env is not None else os.environ
    cores = os.cpu_count() or 2
    default = max(2, min(cores // 2, 8))
    try:
        configured = int(env.get("CURIO_EXEC_PARALLELISM", default))
    except (TypeError, ValueError):
        configured = default
    return max(1, configured)


def js_parallelism(env=None) -> int:
    """How many Node subprocesses may run at once (``CURIO_JS_PARALLELISM``).

    Not a lock: JS nodes are meant to run in parallel, and this leaves them
    doing so. It is a ceiling on how many at once, which the route had none of
    -- one Node process per request, each loading autk-db and its own DuckDB.
    A hundred simultaneous Autark loads peaked the CI container at 51 GB and
    1313 processes, which is how a machine dies rather than queues.

    Half the cores, floor 2, cap 16: an Autark PBF load is CPU- and
    memory-heavy, and the work the child does is what costs, not the pipe.
    ``CURIO_JS_PARALLELISM`` overrides it.
    """
    env = env if env is not None else os.environ
    try:
        configured = int(env.get("CURIO_JS_PARALLELISM", ""))
    except (TypeError, ValueError):
        configured = 0
    if configured > 0:
        return configured
    cores = os.cpu_count() or 2
    return max(2, min(cores // 2, 16))
