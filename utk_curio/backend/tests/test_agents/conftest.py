"""Shared fixtures for agent tests - reuses the common app/DB/auth fixtures."""

from __future__ import annotations

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.agents.infrastructure import agent_jobs
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401
    app,
    client,
    db,
    guest_user_and_token,
    tmp_curio,
    user_and_token,
)


@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makeitem(collector, name, obj):
    """The route test files (test_routes_*.py) import each other's test
    classes to call their helpers, such as
    ``TestNodeCreate()._write_builtin_package``. pytest would otherwise run an
    imported class again in every file that imports it, so in those files a
    class runs only where it is defined. Other files keep pytest's default."""
    if (
        isinstance(obj, type)
        and isinstance(collector, pytest.Module)
        and collector.path.name.startswith("test_routes_")
        and obj.__module__ != collector.obj.__name__
    ):
        return []
    return None


@pytest.fixture()
def alice_project(client, user_and_token):
    _, token = user_and_token
    body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


@pytest.fixture(autouse=True)
def _default_provider(monkeypatch):
    """Give the suite a deployment-configured default LLM provider.

    Almost every test here drives a route that resolves a provider before it
    validates anything else, so with no default configured they all fail at
    that first step with a 400 instead of exercising what they are about.

    Curio ships no built-in endpoint (see ``config.DEFAULT_LLM_*``), which is
    deliberate: an instance whose operator configured nothing must not send
    prompts to a third party. The tests therefore stand in for the operator
    rather than leaning on a shipped default. The URL is unroutable on purpose
    - anything that actually reaches out is stubbed, and a test that forgot to
    stub should fail loudly rather than make a real call.
    """
    # provider_config reads these at call time, so patching the config module
    # is what every resolution sees.
    monkeypatch.setattr(config, "DEFAULT_LLM_API_TYPE", "openai_compatible")
    monkeypatch.setattr(config, "DEFAULT_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(config, "DEFAULT_LLM_MODEL", "test-model")
    monkeypatch.setattr(config, "DEFAULT_LLM_API_KEY", "test-key")


@pytest.fixture(autouse=True)
def _endpoint_not_asked_about_tools(monkeypatch):
    """The suite's endpoint is never asked whether it calls tools natively.

    A run with tools asks an OpenAI-compatible endpoint once per model
    (``chat_capabilities``, through ``providers.probe_native_tools``). The
    endpoint above is unroutable, so the answer here is the one an endpoint
    that cannot be asked gets: the fenced protocol, which every scripted fake
    in the suite speaks. The trial's own tests restore the real probe.
    """
    from utk_curio.backend.app.agents.infrastructure import providers

    monkeypatch.setattr(
        providers, "probe_native_tools",
        lambda config, usage_out=None: (None, "not asked in the test suite"),
    )


@pytest.fixture(autouse=True)
def _pinned_repair_budget(monkeypatch):
    """dev/127: pin the repair loop to the historical THREE attempts.

    Every test written before dev/127 scripts a fixed number of provider
    replies and asserts on "three attempts" — the cap that existed when it was
    written. dev/127 raises the DEFAULT to five corrections and adds a
    wall-clock budget, which would silently change what those scripts mean (a
    fourth round reads a reply nobody wrote). Pinning it here keeps each of
    those tests about its own subject; the new budget has its own tests, which
    delete this variable and assert the shipped default instead.
    """
    monkeypatch.setenv("CURIO_SOLVE_MAX_ATTEMPTS", "3")
    # dev/131: Solve became a SESSION that keeps making passes until the user
    # stops it or fifteen minutes pass. Every test written before it asserts on
    # ONE pass, and a session that waits for a user who is not there would hang
    # the suite, so the session budget is one second and its inter-pass wait is
    # one second here. The clock starts when the batch is built, so how many
    # passes fit in that second depends on the machine: a test that needs a
    # later pass bounds its session by pass count instead, by patching
    # ``SolveBatch._session_deadline_passed`` (issue #583). That second is also
    # each node's repair budget, since the batch gives a node what is left of
    # the session (at least one second), so how many rounds a pass gets depends
    # on the machine too: a test that needs all of a pass's rounds also raises
    # CURIO_SOLVE_SESSION_DEADLINE, since that patch alone leaves the node's
    # budget at one second (issue #729).
    monkeypatch.setenv("CURIO_SOLVE_SESSION_DEADLINE", "1")
    monkeypatch.setenv("CURIO_SOLVE_SESSION_WAIT", "1")


@pytest.fixture(autouse=True)
def _fresh_agent_jobs():
    """dev/115: the detached-job registry is process state — every test starts
    with none and leaves none behind (a leaked live job would hit the
    per-attachment guard or the per-user cap in an unrelated test)."""
    agent_jobs.reset_registry()
    yield
    agent_jobs.reset_registry()
