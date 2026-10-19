"""Collect the real suite in pytest processes, several at a time.

``test_suite_parts.py`` and ``test_e2e_runner_split.py`` check how CI splits
the suites. They collect each suite whole and once per part, every time in a
new pytest process whose environment names the part, so the hooks CI relies on
pick it. Such a process imports every test module of its suite, about 20 s for
the backend one, so one after another the collections took two to three
minutes. Here up to ``COLLECTORS`` of them run at once, each still its own
pytest process with the same arguments and the same part.

Each process gets a folder of its own for the test state. A pytest process
that owns the test database (a run without ``CURIO_E2E_USE_EXISTING``) deletes
it when ``tests/conftest.py`` loads and builds its schema again, so processes
that shared it could delete it under one another. ``CURIO_STATE_DIR`` moves
that folder, and the database and DuckDB paths a process would otherwise
inherit from this one are left out of its environment, so ``tests/conftest.py``
puts them in its own folder. The app built for that schema logs to the
process's own output (``LOG_TO_STDOUT``), not to a ``logs/backend.log`` in the
working folder they share. No test module reads any of these at import, so a
collection finds the same tests as before.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

#: How many collections run at once: four, or one per core on a smaller machine.
COLLECTORS = max(1, min(4, os.cpu_count() or 1))

#: Set in this process by ``tests/conftest.py``. Left out of a collection's
#: environment, they follow its own ``CURIO_STATE_DIR``.
STATE_PATHS = ("DATABASE_URL_TEST", "DATABASE_URL", "CURIO_SHARED_DATA")


def collect(argv: list[str], cwd: Path, env: dict[str, str]) -> list[str]:
    """The test ids a ``pytest --collect-only -q`` process prints.

    *argv* runs in *cwd*, with *env* added to this process's environment and a
    state folder of its own. Fails with the end of the process's output when it
    collected nothing.
    """
    with tempfile.TemporaryDirectory(prefix="curio-collect-") as state:
        environ = {key: value for key, value in os.environ.items() if key not in STATE_PATHS}
        environ.update(CURIO_STATE_DIR=state, LOG_TO_STDOUT="1")
        environ.update(env)
        run = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=environ)
    ids = [line for line in run.stdout.splitlines() if "::" in line]
    if not ids:
        raise AssertionError(f"collection found nothing:\n{run.stdout[-2000:]}\n{run.stderr[-2000:]}")
    return ids


def collect_each(calls, cwd: Path) -> list[list[str]]:
    """:func:`collect` for each ``(argv, env)`` in *calls*, in their order.

    At most ``COLLECTORS`` run at once.
    """
    with ThreadPoolExecutor(max_workers=COLLECTORS) as pool:
        futures = [pool.submit(collect, argv, cwd, env) for argv, env in calls]
        return [future.result() for future in futures]
