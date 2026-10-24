"""How many isolated node runs the sandbox runs at once.

The sandbox sizes its pool of isolated children with this
(``sandbox/isolation/runner.py``), and the backend reads the same number to
keep a dashboard viewer's runs to part of that pool (``runs/viewer.py``).
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
