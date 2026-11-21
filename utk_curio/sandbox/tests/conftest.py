"""Shared setup for the sandbox unit suite.

These tests drive the sandbox through ``app.test_client()``, which means they
call ``/exec`` and ``/execJs`` directly rather than through the backend. Those
routes now require the shared secret (``utk_curio/sandbox/app/auth.py``), and
the sandbox treats an unset ``CURIO_SANDBOX_TOKEN`` as "unauthenticated local
mode" precisely so this suite keeps working.

The catch is that the variable may be set in the ambient environment. It is
inside the Docker image, because docker-compose.ci.yml pins it so the host-side
Playwright tests can authenticate, and ``docker compose exec`` inherits the
container's environment. That turned every existing ``/exec`` test into a 401.

So clear it for the whole suite. Tests that are *about* authentication set it
themselves with ``mock.patch.dict``, which still works because this only
removes an inherited value rather than forcing one.

The suite also gets a store of its own (``suite_store``), as the backend
suite does, so a test never writes into the store of the Curio a developer
runs from this checkout, nor waits on its lock.
"""

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def suite_store(environ=os.environ):
    """The folder the sandbox suite keeps its store in, absolute.

    Without ``CURIO_SHARED_DATA`` the sandbox falls back to ``./.curio/data/``
    under ``CURIO_LAUNCH_CWD`` (``util/db.py``, ``util/parsers.py``): the store
    of the Curio started from this checkout. That Curio's sandbox keeps the
    store's write lock after it runs a node, so the suite's tests failed on
    DuckDB's "Could not set lock on file", and the rest wrote their outputs into
    the developer's store.

    This is a folder under ``.curio/test/``, the test subtree the backend
    suite keeps its own state in (moved with ``CURIO_STATE_DIR``, as there), one
    per xdist worker. Standard library only: the exec-user job loads this
    conftest on the host, with only pytest installed.
    """
    state = environ.get("CURIO_STATE_DIR") or str(_REPO_ROOT / ".curio")
    worker = environ.get("PYTEST_XDIST_WORKER", "")
    return os.path.join(state, "test", "sandbox", worker, "data")


#: The store this conftest set, so that a process can tell it from a store the
#: caller gave. xdist starts its workers from the controller after the
#: controller read this file, so each worker inherits the controller's store and
#: must replace it with its own.
SUITE_STORE_SET = "CURIO_SANDBOX_SUITE_STORE"

# Only when nobody else gave one: a value the caller gives wins, the backend
# conftest's among them when both suites run in one session, and the tests that
# set their own store still patch over this one.
if os.environ.get("CURIO_SHARED_DATA") in (None, os.environ.get(SUITE_STORE_SET)):
    os.environ["CURIO_SHARED_DATA"] = os.environ[SUITE_STORE_SET] = suite_store()


def pytest_configure(config):
    """Leave the ``cuda`` tests out unless the ``-m`` expression names them.

    They run on the GPU (``test_cuda_mlp.py``, ``test_cuda_torch.py``,
    ``test_cuda_isolated.py``, ``test_cuda_sam3.py``), which
    only test-gpu's container has, and test-gpu runs them with ``-m cuda``. Composed with the
    caller's expression as the backend conftest composes its opt-in marks, but
    only when that expression does not name ``cuda``: ``(cuda) and not cuda``
    would select nothing.
    """
    config.addinivalue_line("markers", "cuda: runs on the GPU through CUDA; only test-gpu runs it, with -m cuda")
    config.addinivalue_line(
        "markers",
        "address_space: its isolated nodes run under the address-space cap (RLIMIT_AS), "
        "where a container's cgroups cannot hold them, whatever this one's can",
    )
    existing = getattr(config.option, "markexpr", "") or ""
    if "cuda" not in existing:
        setattr(config.option, "markexpr", f"({existing}) and not cuda" if existing else "not cuda")


@pytest.fixture(autouse=True, scope="session")
def _unauthenticated_sandbox():
    """Run the suite against the sandbox's unauthenticated local mode."""
    previous = os.environ.pop("CURIO_SANDBOX_TOKEN", None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ["CURIO_SANDBOX_TOKEN"] = previous
