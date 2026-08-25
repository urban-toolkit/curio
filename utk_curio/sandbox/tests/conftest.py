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
"""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _unauthenticated_sandbox():
    """Run the suite against the sandbox's unauthenticated local mode."""
    previous = os.environ.pop("CURIO_SANDBOX_TOKEN", None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ["CURIO_SANDBOX_TOKEN"] = previous
