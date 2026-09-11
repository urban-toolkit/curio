"""Which sandbox the direct-call helpers address.

Two helpers in ``utils.py`` bypass the backend and talk to the sandbox
themselves - ``load_artifact_as_dict`` and ``execute_workflow_programmatically``
- because DuckDB wants a single writer. They read the port from the
environment, and they used to read *only* ``FLASK_SANDBOX_PORT``.

Nothing sets that in the ``CURIO_E2E_USE_EXISTING`` path: ``e2e_existing_servers``
honours ``CURIO_E2E_SANDBOX_PORT``, which is also the variable the README
documents. So running the suite against a stack on any non-default port sent
those two helpers to **port 2000** instead - another session's sandbox, or
nothing at all - and it surfaced as a bare ``401`` from a URL no test mentions.
That is the whole reason this file exists: the resolution order is load-bearing
and invisible, so it gets pinned rather than rediscovered.

Browser-free by design, so it lives in the unit sweep rather than under
``test_frontend/`` - that package's autouse ``e2e_clean_db`` fixture calls the
backend's ``/api/testing/*`` routes, which a test that deliberately unsets the
port variables cannot reach.
"""
from __future__ import annotations

import pytest

from utk_curio.backend.tests.test_frontend.utils import sandbox_base_url

SANDBOX_VARS = (
    "CURIO_E2E_HOST",
    "CURIO_E2E_SANDBOX_PORT",
    "FLASK_SANDBOX_HOST",
    "FLASK_SANDBOX_PORT",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Start every case from "nothing configured".

    The suite's own conftest and any inherited shell state both set some of
    these, and a test that silently read one of those would assert nothing.
    """
    for name in SANDBOX_VARS:
        monkeypatch.delenv(name, raising=False)


class TestSandboxBaseUrl:
    def test_falls_back_to_the_stock_sandbox(self):
        assert sandbox_base_url() == "http://127.0.0.1:2000"

    def test_the_documented_e2e_knob_is_honoured(self, monkeypatch):
        # The regression. `CURIO_E2E_SANDBOX_PORT` is what the README names and
        # what `e2e_existing_servers` reads; the direct callers ignored it.
        monkeypatch.setenv("CURIO_E2E_SANDBOX_PORT", "2500")
        assert sandbox_base_url() == "http://127.0.0.1:2500"

    def test_the_flask_var_still_works_on_its_own(self, monkeypatch):
        # `test_large_dataframe_e2e` sets these for the children it spawns, and
        # `curio.py start` exports them into the sandbox process.
        monkeypatch.setenv("FLASK_SANDBOX_HOST", "127.0.0.1")
        monkeypatch.setenv("FLASK_SANDBOX_PORT", "2186")
        assert sandbox_base_url() == "http://127.0.0.1:2186"

    def test_the_e2e_knob_wins_when_both_are_set(self, monkeypatch):
        # "Test the servers already running" is the more specific instruction,
        # so it outranks whatever a previously started sandbox left behind.
        monkeypatch.setenv("CURIO_E2E_SANDBOX_PORT", "2500")
        monkeypatch.setenv("FLASK_SANDBOX_PORT", "2000")
        assert sandbox_base_url() == "http://127.0.0.1:2500"

    def test_the_host_follows_the_same_order(self, monkeypatch):
        monkeypatch.setenv("FLASK_SANDBOX_HOST", "10.0.0.9")
        assert sandbox_base_url() == "http://10.0.0.9:2000"
        monkeypatch.setenv("CURIO_E2E_HOST", "localhost")
        assert sandbox_base_url() == "http://localhost:2000"

    def test_a_blank_value_is_not_a_configured_value(self, monkeypatch):
        # An exported-but-empty var is how a shell script that computed nothing
        # announces itself; treating "" as a port would build ":0".
        monkeypatch.setenv("CURIO_E2E_SANDBOX_PORT", "")
        monkeypatch.setenv("FLASK_SANDBOX_PORT", "2500")
        assert sandbox_base_url() == "http://127.0.0.1:2500"

    def test_the_port_is_returned_as_a_bare_integer(self, monkeypatch):
        # Whitespace from a heredoc-built env file must not reach the URL.
        monkeypatch.setenv("CURIO_E2E_SANDBOX_PORT", " 2500 ")
        assert sandbox_base_url() == "http://127.0.0.1:2500"
